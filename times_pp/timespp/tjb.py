# SPDX-License-Identifier: GPL-3.0-or-later
"""model.tjb in pieces (TJB2): each table written as soon as it is final, beside the steps that follow.

The file (little-endian):
  "TJB2"  u64 token (the same number is in model.db3, table __tjb)  u8 steps (1: a myopic run, steps in model.db3,
    or model_steps.db3 beside the Parquet folder)
  the pieces, one per table with data, in the order they were written (any order): u32 number of labels; u32 byte
    length of each; the labels, UTF-8, sorted as DuckDB sorts text (numbered from 0); dim columns of i32 numbers into
    this list; then for a parameter its f64 values, for a variable f64 lower and upper (+-inf as they are)
  the index, in the order of __symbols in model.db3 (the order times_eq reads the tables in): u64 number of tables;
    for each, u16 length + name (UTF-8); u8 kind (0 set, 1 parameter, 2 variable); u8 dim; u64 rows; u8 data (0: the
    rows are in model.db3 only: a table the equations do not read, as times_eq/src/schema.jl lists them); u64 the
    offset of its piece (0: none). A scalar is a parameter of no index column: a piece of no label and one value.
  u64 offset of the index; "TJB2"

The rows of each piece are those of version 1 (export.to_bin), in the same order: sorted by their label columns when
there are two or more (or a variable), ties in the order of the table; a one-column table of numbers by number; any
other in the order of the table. A table's own labels sort among themselves as they do among all labels, so the
order is the same. times_eq numbers the labels on first sight, reading the tables in the index's order: the same
numbers as from version 1 or from model.db3.

When: `Pieces` is made before the first step (preprocess()); it starts a writer thread on a second DuckDB connection,
and after each step the tables that FINAL lists as final after it are queued to it (`after`); so are those of a part
run beside the main thread when it ends (side.py). Every statement of the
preprocessor is watched (engine._Con.execute): a piece read while a statement writing its table ran, or before one
that writes it, is written again at the end, as is a table shadowed by a temp table (a scratch relation of the
preprocessor with a symbol's name, which the writer's connection does not see), but for DELETEs that took no row
away. So a wrong FINAL costs time, never a difference. `finish` writes the rest on the main thread, then the index.

TIMESPP_TJB_PIECES=0: model.tjb version 1, written after the last step (export.to_bin), as before.
TIMESPP_TJB_OVERLAP=0: version 2, every piece written after the last step, on the main thread.
"""
import os, re, struct, threading, queue, time, itertools, json
import numpy as np

MAGIC = b"TJB2"

# the tables a statement writes: insert into, update, delete from, create (or replace) table, drop table, alter table
_WRITE = re.compile(r'\b(delete\s+from|insert\s+(?:or\s+replace\s+)?into|update|truncate|copy|'
                    r'create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?table\s+(?:if\s+not\s+exists\s+)?|'
                    r'drop\s+table\s+(?:if\s+exists\s+)?|alter\s+table|rename\s+to)\s+(?:"([^"]+)"|([A-Za-z_]\w*))', re.I)


def enabled():
    return os.environ.get("TIMESPP_TJB_PIECES", "1") != "0" and os.environ.get("TIMESPP_TJB", "1") != "0"


def overlap():
    return enabled() and os.environ.get("TIMESPP_TJB_OVERLAP", "1") != "0"


def _final():
    """FINAL: step -> the tables the equations read that no later step writes (tjb_final.json, made from the
    tables each step reads and writes; the steps named as preprocess() names them)."""
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tjb_final.json")
    try:
        return json.load(open(f, encoding="utf-8"))
    except OSError:
        return {}


def tables(db):
    """(table, source relation, kind code, label columns, value columns, read by the equations) of every table, in the
    order of model.db3's __symbols."""
    from . import export
    want = export._wanted()
    return [(n, s, k, c, v, want is None or n.upper() in want) for n, s, k, c, v in export._label_cols(db)]


def piece(con, src, kind, cols, vals):
    """The piece of one table: (rows, [byte strings]). con: a DuckDB connection (it makes temp tables of its own)."""
    x = con.execute
    n = len(cols)
    labels, num = [], None
    if n:
        # the table's labels, numbered in sorted order
        lab = " union ".join(f'select distinct cast("{c}" as VARCHAR) as l from "{src}"' for c in cols)
        x("create or replace temp table __tjb_lab as select l, (row_number() over (order by l) - 1)::INTEGER as i "
          f"from ({lab}) where l is not null")
        if n == 1 and kind != 2:
            # each label as a number, as the ORDER BY of model.db3 takes it (try_cast; NaN: not a number)
            r = x("select l, try_cast(l as double) from __tjb_lab order by i").fetchall()
            labels = [a for a, _ in r]
            num = np.array([np.nan if v is None else v for _, v in r] or [0.0], dtype=float)
        else:
            labels = [r[0] for r in x("select l from __tjb_lab order by i").fetchall()]
    sel = [f"l{i}.i as k{i}" for i in range(n)] + [f'cast(t_."{c}" as DOUBLE) as v{i}' for i, c in enumerate(vals)]
    joins = " ".join(f'join __tjb_lab l{i} on l{i}.l = cast(t_."{c}" as VARCHAR)' for i, c in enumerate(cols))
    by = n >= 2 or (kind == 2 and n > 0)
    q = f'select t_.rowid as rid_, {", ".join(sel)} from "{src}" t_ {joins}'
    if not sel:
        arr, rows = {}, x(f'select count(*) from "{src}"').fetchone()[0]
    elif by:
        # sorted into a temp table, then read (export.to_bin says why); rid_ last, so no ties
        x(f"create or replace temp table __tjb_sorted as {q} order by " + ", ".join(f"k{i}" for i in range(n)) + ", rid_")
        arr = x("select * exclude (rid_) from __tjb_sorted").fetchnumpy()
        x("drop table __tjb_sorted")
    else:
        arr = x(q).fetchnumpy()
        rid = np.asarray(arr.pop("rid_"))
        if num is not None and not np.isnan(num[np.asarray(arr["k0"])]).any():
            o = np.lexsort([rid, num[np.asarray(arr["k0"])]])       # a one-column table of numbers: by number
        else:
            o = np.argsort(rid, kind="stable")                       # the order of the table
        arr = {k: np.asarray(v)[o] for k, v in arr.items()}
    if n:
        x("drop table __tjb_lab")
    if arr:
        rows = len(next(iter(arr.values())))
    enc = [l.encode("utf-8") for l in labels]
    out = [struct.pack("<I", len(enc)), np.array([len(b) for b in enc], dtype="<u4").tobytes(), b"".join(enc)]
    for i in range(n):
        out.append(np.ascontiguousarray(arr[f"k{i}"], dtype="<i4").tobytes())
    for i in range(len(vals)):
        a = arr[f"v{i}"]
        if hasattr(a, "mask"):                   # a NULL value: NaN (TimesEq stops on it, as on a NULL in model.db3)
            a = a.filled(np.nan)
        out.append(np.ascontiguousarray(a, dtype="<f8").tobytes())
    return rows, out


def _one(db, name):
    """tables(db)'s entry of the table `name` (None: not a table the equations read)."""
    from . import export
    want = export._wanted()
    u = name.upper()
    if want is not None and u not in want:
        return None
    if u in getattr(db, "dropped", ()) or f"B_{u}" in getattr(db, "dropped", ()):
        return None                              # (dropped once written: stream.py)
    sy = db.sym.get(u) or db.sym.get(name)
    if sy is not None and sy.kind in ("set", "par"):
        tc = [r[0] for r in db.q(f'describe "{u if u in db.sym else name}"')]
        n = len(sy.cols)
        return (u if u in db.sym else name, u if u in db.sym else name, 0 if sy.kind == "set" else 1, tc[:n],
                [tc[n]] if sy.kind == "par" else [])
    var = next((v for v in getattr(db, "bounds", ()) if v.upper() == u), None)
    if var is not None:
        bc = [r[0] for r in db.q(f'describe "B_{var}"')]
        return (var, f"B_{var}", 2, bc[:len(bc) - 2], bc[len(bc) - 2:])
    return None


_W = None                       # the Pieces being written: engine._Con.execute tells it of every statement


def watch_begin(sql):
    w = _W
    return w.begin(sql) if w is not None else None


def side_done(db, name):
    """A part run beside the main thread (side.py) has ended: its tables are final (FINAL lists them as "side: name")."""
    w = _W
    if w is not None:
        w.after("side: " + name, db)


def watch_end(t):
    w = _W
    if w is not None and t:
        w.end(t)


class Pieces:
    """model.tjb written in pieces: see the module's text."""

    def __init__(self, db, path, token, thread=True):
        global _W
        self.db, self.path, self.token = db, path, token
        self.tmp = path + ".part"
        for p in (path, self.tmp):
            if os.path.exists(p):
                os.remove(p)
        self.f = open(self.tmp, "wb")
        self.f.write(MAGIC + struct.pack("<QB", token, 0))
        self.lock = threading.Lock()
        self.done = {}            # source relation (upper case) -> (rows, offset, sequence number at its read, rows
                                  # counted then, bytes)
        self.free = {}            # source relation (upper case) -> (offset, bytes) of a piece found stale
        self.seq = itertools.count(1)
        self.last = {}            # source relation (upper case) -> sequence number of the last statement writing it
        self.last_del = {}        # ... of the last DELETE from it (counted apart: see `_valid`)
        self.running = {}         # source relation (upper case) -> statements writing it now
        self.queued = set()
        self.final = _final() if thread else {}
        self.err = []
        self.listeners = []       # f(step, db): told of each step after this (stream.py)
        self.seconds = 0.0        # the writer threads' time
        self.q = None
        self.threads = []
        if thread:
            self.q = queue.Queue()
            self._consumers(self.q, 1)
        _W = self

    # -- every statement of the preprocessor (engine._Con.execute)
    def begin(self, sql):
        if not isinstance(sql, str):
            return None
        found = [(m.group(1)[0] in "dD", (m.group(2) or m.group(3)).upper()) for m in _WRITE.finditer(sql)]
        if not found:
            return None
        for _, n in found:                       # running first, then its number (the writer's check: _run)
            self.running[n] = self.running.get(n, 0) + 1
        k = next(self.seq)
        for d, n in found:
            (self.last_del if d else self.last)[n] = k
        return [n for _, n in found]

    def end(self, names):
        for n in names:
            self.running[n] -= 1

    # -- the writer threads
    def _consumers(self, q, n):
        """n threads writing the pieces of the tables put on q (each on a connection of its own), until a None each."""
        for _ in range(n):
            con = self.db.con._c.cursor()
            t = threading.Thread(target=self._run, args=(q, con), name="model.tjb", daemon=True)
            t.start()
            self.threads.append((t, con))

    def _join(self, q):
        for _ in self.threads:
            q.put(None)
        for t, con in self.threads:
            t.join()
            con.close()
        self.threads = []

    def _run(self, q, con):
        spent = 0.0
        while True:
            item = q.get()
            if item is None:
                self.seconds += spent
                return
            name, src, kind, cols, vals = item
            t = time.perf_counter()
            u = src.upper()
            d = self.done.get(u)
            if d is not None and max(self.last.get(u, 0), self.last_del.get(u, 0)) < d[2]:
                continue                         # queued again, and its piece is good
            # its number, then whether a statement writes the table now: one that began before is running (the piece
            # waits for the end) or done (committed before the read); one that begins after has a larger number than
            # k (the piece is stale; begin() marks it running before taking its number)
            k = next(self.seq)
            if not self.running.get(u):
                try:
                    n = con.execute(f'select count(*) from "{src}"').fetchone()[0]
                    rows, chunks = piece(con, src, kind, cols, vals)
                    if not self.running.get(u) and self.last.get(u, 0) < k:
                        self._write(u, rows, chunks, k, n)
                except Exception as e:           # written at the end, on the main thread
                    self.err.append(f"{type(e).__name__}: {str(e)[:200]}")
            spent += time.perf_counter() - t

    def _write(self, u, rows, chunks, k, n=None):
        size = sum(map(len, chunks))
        with self.lock:
            old = self.free.pop(u, None)
            if old is None and u in self.done:       # (a table queued again: its piece of before)
                old = self.done[u][1], self.done[u][4]
            if old is not None and size <= old[1]:   # a piece written again: in the place of the old one, if it fits
                off = old[0]
                self.f.seek(off)
            else:
                self.f.seek(0, 2)
                off = self.f.tell()
            for c in chunks:
                self.f.write(c)
            self.done[u] = (rows, off, k, n, size)

    def _stale(self, u, src, shadowed):
        """Why the piece of `src` is not the table as it is now ('' if it is): none, a temp table of its name, a
        statement writing it after its read began (k), but DELETEs that left its number of rows as it was (a delete only
        takes rows away: the same number, nothing taken)."""
        d = self.done.get(u)
        if d is None:
            return "none"
        if u in shadowed:
            return "temp"
        if u in getattr(self.db, "dropped", ()):
            return ""                            # dropped once written (stream.py): its piece is the table
        if self.last.get(u, 0) > d[2]:
            return "written"
        if self.last_del.get(u, 0) > d[2] and self.db.q1(f'select count(*) from "{src}"') != d[3]:
            return "deleted"
        return ""

    def after(self, step, db=None):
        """The step `step` is done: queue the tables final after it to the writer thread. db: the database as the
        caller's thread has it (a part run beside the main thread: side.py, whose tables are queued again: queued
        after the step that started the part, they were read while it wrote them), else the main one."""
        if self.q is None:
            return
        for n in self.final.get(step, ()):
            if n.upper() in self.queued and db is None:
                continue
            self.queued.add(n.upper())
            t = _one(db or self.db, n)
            if t is not None:
                self.q.put(t)
        for f in self.listeners:
            f(step, db)

    def _stop(self, helpers=0):
        """Stop the writer thread once its queue is empty, with `helpers` more threads emptying it."""
        global _W
        if self.q is not None:
            self._consumers(self.q, helpers)
            self._join(self.q)
            self.q = None
        if _W is self:
            _W = None

    def abandon(self):
        """No model.tjb (the preprocessing failed): stop the writer, remove the partial file."""
        self._stop()
        self.f.close()
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def finish(self):
        """Wait for the writer thread (helped by more threads: TIMESPP_TJB_THREADS, default 4 in all); write every table
        it has not written (or that changed since), the same way, then the index; rename."""
        db = self.db
        nth = max(1, int(os.environ.get("TIMESPP_TJB_THREADS", "4")))
        t0 = time.perf_counter()
        self._stop(nth - 1)
        waited = time.perf_counter() - t0
        early = len(self.done)
        shadowed = {r[0].upper() for r in db.con.execute("select table_name from duckdb_tables() where temporary").fetchall()}
        tabs = tables(db)
        again, rest, main = [], [], []
        for name, src, kind, cols, vals, data in tabs:
            if src is None:                      # a scalar: a piece of one value
                self._write(("scalar", name), 1, [struct.pack("<I", 0), struct.pack("<d", float(db.s.get(name, 0.0)))], 0)
                continue
            if not data:
                continue
            u = src.upper()
            why = self._stale(u, src, shadowed)
            if not why:
                continue
            if u in self.done:
                again.append(f"{name}: {why}")
                d = self.done.pop(u)
                self.free[u] = (d[1], d[4])
            (main if u in shadowed else rest).append((name, src, kind, cols, vals))
        if rest:                                 # the rest, by the threads (largest first would need counts: as listed)
            q = queue.Queue()
            for t in rest:
                q.put(t)
            self._consumers(q, min(nth, len(rest)))
            self._join(q)
        for name, src, kind, cols, vals in main + [t for t in rest if t[1].upper() not in self.done]:
            rows, chunks = piece(db.con._c, src, kind, cols, vals)    # (a temp table of its name: this connection's)
            self._write(src.upper(), rows, chunks, 0)
        # the index
        w = self.f.write
        self.f.seek(0, 2)
        at = self.f.tell()
        w(struct.pack("<Q", len(tabs)))
        for name, src, kind, cols, vals, data in tabs:
            nb = name.encode("utf-8")
            w(struct.pack("<H", len(nb))); w(nb)
            if src is None or data:              # (a scalar: a parameter of no index, one row)
                rows, off = self.done[("scalar", name) if src is None else src.upper()][:2]
                w(struct.pack("<BBQBQ", kind, len(cols), rows, 1, off))
            else:
                dr = getattr(db, "dropped", {}).get(src.upper()) if src.upper() not in shadowed else None
                w(struct.pack("<BBQBQ", kind, len(cols), dr[1] if dr else db.q1(f'select count(*) from "{src}"'), 0, 0))
        w(struct.pack("<Q", at)); w(MAGIC)
        self.f.seek(12)
        self.f.write(struct.pack("<B", 1 if getattr(db, "steps", None) else 0))
        self.f.close()
        os.replace(self.tmp, self.path)
        return {"early": early - len(again), "written_again": len(again), "again": again[:20], "waited": round(waited, 2),
                "at_end": len(rest) + len(main), "writer_seconds": round(self.seconds, 1), "writer_errors": self.err[:5]}
