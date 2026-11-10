# SPDX-License-Identifier: GPL-3.0-or-later
"""The tables as a folder of Parquet files, each written as soon as it is final, beside the steps; and the tables
dropped from DuckDB once written and no longer read (TIMESPP_DB3_STREAM=1, TIMESPP_DROP=1).

The folder (model_parquet/ beside model.tjb, in place of model.db3): <TABLE>.parquet for every table of model.db3's
__symbols, with the same rows in the same order and the same columns (i0.., value; for a variable d0.., level,
marginal, lower, upper: export.table_sql, the SELECT and ORDER BY of model.db3), a scalar as one row of "value"; and
the metadata as model.db3 has it: __symbols, __casing, __texts, __encoding, __tjb (the token of model.tjb, also as
__tjb.txt for times_eq). It is written as model_parquet.part/ and renamed when complete. model.db3 can be made
from it, the same as export.to_sqlite writes it.

When: like model.tjb's pieces (tjb.py), whose statement watch it shares: after each step the tables that
db3_final.json lists as final after it are queued to the writer threads (TIMESPP_DB3_WRITERS, default 1), each on a
DuckDB connection of its own, each table a COPY to its file. A table of more rows than TIMESPP_DB3_DEFER (default:
none) waits until model.tjb is complete: the sort and write of a large table beside the steps takes DuckDB's threads
from them (on a large model the steps 10 s longer, so model.tjb later for Julia); written after model.tjb, with DuckDB's
threads as TIMESPP_DB3_THREADS says (the runner's setting for model.db3 beside the equation build), it does not. A file read while a statement writing its table ran, or
before one that writes it, or a table shadowed by a temp table, is written again at the end (`finish`), so a wrong
db3_final.json costs time, never a difference.

Drops (TIMESPP_DROP=1): a table is dropped from DuckDB once its file is written and, if the equations read it, its
model.tjb piece, and once every step that reads it has run: db3_drop.json gives the last step that reads or writes it
on the models traced (main steps; "sides": the parts run beside the main thread that read it, which must have
ended). The check is made after each step, on the main thread; after the last step, once model.tjb is complete,
every table is dropped as soon as its file is written. A statement that reads a dropped table fails (DuckDB: no such
table), so a missing reader stops the run, it never reads an empty table. A dropped table's columns and rows are kept
(db.dropped) for model.tjb's index and __symbols.

Off (the default): model.db3 as before. --low-memory and runs without model.tjb's pieces write model.db3 as before.
A myopic run (TIMESTEP, FIXBOH) writes the folder too, with no drops, and its steps in model_steps.db3 beside it
(export.to_steps), before the folder is finished.
"""
import os, json, time, queue, threading, shutil

FOLDER = "_parquet"                 # model.db3 -> model_parquet


def enabled():
    return os.environ.get("TIMESPP_DB3_STREAM", "0") == "1"


def drops():
    return enabled() and os.environ.get("TIMESPP_DROP", "0") == "1"


def folder_of(path):
    """The folder written in place of `path` (model.db3 -> model_parquet)."""
    return os.path.splitext(path)[0] + FOLDER


def _json(name):
    try:
        return json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), encoding="utf-8"))
    except OSError:
        return {}


class Stream:
    """The Parquet folder, written as its tables become final: see the module's text."""

    def __init__(self, db, path, pieces, drops_allowed=True):
        self.db, self.pieces = db, pieces
        self.folder = folder_of(path)
        self.tmp = self.folder + ".part"
        for p in (self.folder, self.tmp):
            shutil.rmtree(p, ignore_errors=True)
        if os.path.exists(path):
            os.remove(path)
        os.makedirs(self.tmp)
        self.final = _json("db3_final.json")
        self.dropmap = _json("db3_drop.json") if drops() and drops_allowed else None
        self.done = {}              # source relation (upper case) -> (sequence number at its read, rows counted then)
        self.queued = set()
        self.passed = set()         # the steps ended (main steps and "side: <name>")
        self.dropped = 0
        self.dropped_rows = 0
        self.ended = False          # the steps are over and model.tjb complete: drop each table once written
        self.shadowed = set()       # (then) the tables shadowed by a temp table of the main connection
        self.tail = False           # model.tjb is complete: a large table is written now (TIMESPP_DB3_DEFER)
        self.err = []
        self.seconds = 0.0
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.threads = []
        self.nw = max(1, int(os.environ.get("TIMESPP_DB3_WRITERS", "1")))
        self.defer = int(float(os.environ.get("TIMESPP_DB3_DEFER", "0") or 0))   # rows: larger tables after model.tjb
        self.deferred = 0
        db.dropped = getattr(db, "dropped", {})
        self.dbname = db.con._c.execute("select current_database()").fetchone()[0]
        self._consumers(self.nw)
        pieces.listeners.append(self.after)

    # -- the writers
    def _consumers(self, n):
        for _ in range(n):
            con = self.db.con._c.cursor()
            t = threading.Thread(target=self._run, args=(con,), name="model_parquet", daemon=True)
            t.start()
            self.threads.append((t, con))

    def _join(self):
        for _ in self.threads:
            self.q.put(None)
        for t, con in self.threads:
            t.join()
            con.close()
        self.threads = []

    def _src(self, name):
        return f"B_{name}" if name not in self.db.sym else name

    def _run(self, con):
        p = self.pieces
        spent = 0.0
        while True:
            name = self.q.get()
            if name is None:
                with self.lock:
                    self.seconds += spent
                return
            t = time.perf_counter()
            u = self._src(name).upper()
            d = self.done.get(u)
            if d is not None and max(p.last.get(u, 0), p.last_del.get(u, 0)) < d[0]:
                continue                         # queued again, and its file is good
            if u in self.db.dropped:
                continue
            # as tjb.Pieces._run: the number first, then whether a statement writes the table now
            k = next(p.seq)
            if not p.running.get(u):
                try:
                    n = self._write(con, name)
                    if n is not None and not p.running.get(u) and p.last.get(u, 0) < k:
                        self.done[u] = (k, n)
                        if self.ended and u not in self.shadowed:
                            self._drop(u, con)
                except Exception as e:           # written again at the end, on the main thread
                    self.err.append(f"{type(e).__name__}: {str(e)[:200]}")
            spent += time.perf_counter() - t

    def _write(self, con, name):
        """The file of one table (replaced if there); its rows counted before. None: not written now (a large table
        before model.tjb is complete: TIMESPP_DB3_DEFER)."""
        from . import export
        src, sel = export.table_sql(self.db, name, con)
        n = con.execute(f'select count(*) from "{src}"').fetchone()[0]
        if self.defer and n > self.defer and not self.tail:
            with self.lock:
                self.deferred += 1
            return None
        f = os.path.join(self.tmp, name + ".parquet").replace("\\", "/").replace("'", "''")
        con.execute(f"COPY ({sel}) TO '{f}' (FORMAT parquet)")
        return n

    # -- the steps
    def after(self, step, db=None):
        """The step `step` is done (tjb.Pieces.after tells): queue the tables final after it; then the drops."""
        side = db is not None
        for n in self.final.get(step, ()):
            if n in self.db.sym and self.db.sym[n].kind == "scalar":
                continue
            u = n.upper()
            if u in self.queued and not side:
                continue
            if n not in self.db.sym and n not in getattr(self.db, "bounds", ()):
                continue                         # (not a table of this model)
            self.queued.add(u)
            self.q.put(n)
        self.passed.add(step)
        if self.dropmap is not None and threading.current_thread() is threading.main_thread():
            self._drops()

    def _droppable(self, name):
        """Every step that reads the table `name` has ended (db3_drop.json)."""
        e = self.dropmap.get(name)
        if e is None:
            return False                         # not traced: kept
        return (e["after"] is None or e["after"] in self.passed) and all(("side: " + s) in self.passed for s in e["sides"])

    def _drops(self):
        """After a step: drop the tables written to both files that no later step reads (not one shadowed now by a
        temp table of its name, which is what model.db3 would get: see finish)."""
        p = self.pieces
        shadowed = _temp(self.db.con._c)
        for name, e in self.dropmap.items():
            u = name.upper()
            if u in self.db.dropped or u not in self.done or not self._droppable(name):
                continue
            src = self._src(name) if name in self.db.sym or name[2:] in getattr(self.db, "bounds", ()) else None
            if src is None or src.upper() != u:
                continue
            if u in shadowed or not self._written(u, p):
                continue
            self._drop(u, self.db.con._c)

    def _written(self, u, p):
        """Its file and (if the equations read it) its model.tjb piece are of the table as it is."""
        d = self.done.get(u)
        if d is None or max(p.last.get(u, 0), p.last_del.get(u, 0)) > d[0] or p.running.get(u):
            return False
        t = p.done.get(u)
        if self._eq(u) and (t is None or max(p.last.get(u, 0), p.last_del.get(u, 0)) > t[2]):
            return False
        return True

    def _eq(self, u):
        from . import export
        want = export._wanted()
        name = u[2:] if u.startswith("B_") and u not in self.db.sym else u
        return want is None or name in want

    def _drop(self, u, con):
        """Drop one table (the table itself, by its full name: never a temp table of its name), keeping its columns
        and rows for model.tjb's index and __symbols."""
        with self.lock:
            if u in self.db.dropped:
                return
            full = f'{self.dbname}.main."{u}"'
            cols = [r[0] for r in con.execute(f"describe {full}").fetchall()]
            rows = self.done[u][1]
            con.execute(f"drop table {full}")
            self.db.dropped[u] = (cols, rows)
            self.dropped += 1
            self.dropped_rows += rows

    # -- the end
    def finish(self, token):
        """After model.tjb is complete: wait for the writers; write every table they have not written (or that changed
        since), the scalars and the metadata; rename the folder. Returns the number of tables in __symbols."""
        from . import export
        db, p = self.db, self.pieces
        t0 = time.perf_counter()
        self.tail = True
        shadowed = _temp(db.con._c)
        self.shadowed = shadowed
        self.ended = self.dropmap is not None
        if self.ended:                           # model.tjb is complete: what is written can go
            for u in list(self.done):
                if u not in db.dropped and u not in shadowed and self._written(u, p):
                    self._drop(u, db.con._c)
        early = len(self.done)
        again, main = [], []
        with self.lock:                          # (no drop while the columns of the bounds are read)
            syms = export.symbols(db)
        for name, kind, dim in syms:
            if name in db.sym and db.sym[name].kind == "scalar":
                continue
            u = self._src(name).upper()
            if u in shadowed:                    # what model.db3 gets: the temp table, on the main connection
                main.append(name)
                self.done.pop(u, None)
                continue
            if u in db.dropped:
                continue
            d = self.done.get(u)
            if d is not None and u not in shadowed and max(p.last.get(u, 0), p.last_del.get(u, 0)) < d[0] and not p.running.get(u):
                continue
            if d is not None:
                again.append(name)
                del self.done[u]
            self.q.put(name)
        self._join()                             # (the writers end once the queue is empty)
        waited = time.perf_counter() - t0
        # on the main thread: a table shadowed by a temp table of its name (this connection's), and any the writers
        # could not write
        for name, _, _ in syms:
            u = self._src(name).upper()
            if (name in db.sym and db.sym[name].kind == "scalar") or u in self.done or (u in db.dropped and u not in shadowed):
                continue
            self.done[u] = (0, self._write(db.con._c, name))
            if self.ended and u not in shadowed:
                self._drop(u, db.con._c)
        # the scalars and the metadata
        x = db.con._c.execute
        for name, sy in db.sym.items():
            if sy.kind == "scalar":
                v = export._num(float(db.s.get(name, 0.0)))
                v = 0.0 if v == 0 else v             # (as model.db3: SQLite gives a -0.0 back as 0.0)
                f = os.path.join(self.tmp, name + ".parquet").replace("\\", "/").replace("'", "''")
                x(f"COPY (select {'NULL' if v is None else repr(float(v))}::DOUBLE as \"value\") TO '{f}' (FORMAT parquet)")
        for name, (decl, rows) in export.metadata(db, token).items():
            _meta(db.con._c, os.path.join(self.tmp, name + ".parquet"), decl, rows)
        with open(os.path.join(self.tmp, "__tjb.txt"), "w") as f:
            f.write(f"{token}\n")
        for i in range(300):                     # (Windows refuses a rename while a scanner has a file open)
            try:
                os.replace(self.tmp, self.folder)
                break
            except PermissionError:
                if i == 299:
                    raise
                time.sleep(0.1)
        self.info = {"early": early - len(again), "written_again": len(again), "again": again[:20],
                     "waited": round(waited, 2), "writer_seconds": round(self.seconds, 1), "writer_errors": self.err[:5],
                     "dropped": self.dropped, "dropped_rows": self.dropped_rows, "deferred": self.deferred}
        return len(syms)

    def abandon(self):
        """No folder (the preprocessing failed): stop the writers, remove the partial folder."""
        self._join()
        shutil.rmtree(self.tmp, ignore_errors=True)


def _meta(con, path, decl, rows):
    """One metadata table as a Parquet file: the columns of `decl` (TEXT -> VARCHAR), the rows as given."""
    cols = [c.split() for c in decl.split(", ")]
    ty = {"TEXT": "VARCHAR", "INTEGER": "BIGINT"}
    con.execute("create or replace temp table __pq_meta (" + ", ".join(f'"{n}" {ty[t]}' for n, t in cols) + ")")
    if rows:                                     # (through a DataFrame: DuckDB's executemany is one statement a row)
        import pandas as pd
        con.register("__pq_rows", pd.DataFrame([tuple(r) for r in rows], columns=[n for n, _ in cols], dtype=object))
        con.execute("insert into __pq_meta select * from __pq_rows")
        con.unregister("__pq_rows")
    f = path.replace("\\", "/").replace("'", "''")
    con.execute(f"COPY __pq_meta TO '{f}' (FORMAT parquet)")
    con.execute("drop table __pq_meta")


def _temp(con):
    """The names (upper case) of the temp tables of a connection."""
    return {r[0].upper() for r in con.execute("select table_name from duckdb_tables() where temporary").fetchall()}
