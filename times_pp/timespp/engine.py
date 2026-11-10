# SPDX-License-Identifier: GPL-3.0-or-later
"""Sparse relational store for TIMES symbols, on DuckDB.

Conventions
-----------
* One table per symbol.  Sets: index columns only.  Parameters: index columns
  + ``value DOUBLE``.
* A parameter row exists  <=>  GAMS has a record.  A row with value 0 is EPS.
  Assigning a plain zero deletes the row (see `put`).
* Labels are upper-case VARCHAR.  Years are labels too ('2005', '0').
* For every symbol two SQL macros are created:
      in_NAME(k1,..,kn)  -> BOOLEAN   record exists      ($NAME(...) in GAMS)
      v_NAME(k1,..,kn)   -> DOUBLE    value, 0 if absent  (NAME(...) in GAMS)
* Scalars live in ``db.s`` (a dict) and are substituted into SQL as {NAME}.
"""
from __future__ import annotations
import duckdb, json, os, re, time
from . import tjb

# DB.load_rows hands the labels to DuckDB as Python objects (0: as pandas's string type)
LOAD_OBJECT = os.environ.get("TIMESPP_LOAD_OBJECT", "1") != "0"

# canonical column names for GAMS domain names (aliases collapse to one name)
_CANON = {}
for names, col in [
    ("R REG ALL_REG ALL_R", "r"), ("P PRC", "p"), ("C COM COM1 COM2 COM3", "c"),
    ("CG COM_GRP CG1 CG2 CG3 CG4 COM_TYPE", "cg"),
    ("ALLYEAR YEAR LL T TT V K PYR DATAYEAR MILESTONYR PASTYEAR MODLYEAR BOHYEAR EOHYEAR", "y"),
    ("TS S ALL_TS SL S2", "s"), ("BD LIM L BND_TYPE LIM_TYPE", "l"), ("CUR CURR", "cur"),
    ("IO IN_OUT", "io"), ("IE IMPEXP", "ie"), ("UC_N UCN", "uc"), ("SIDE", "side"),
    ("TSLVL TSL", "tsl"), ("J JJ", "j"), ("AGE LIFE SPAN", "age"), ("ITEM * U", "u"),
    ("UC_GRPTYPE", "grp"), ("UC_NAME COSTYPE UC_COST", "ucn"), ("COSTAGG COSTCAT", "agg"),
    ("ALLSOW SOW W", "w"), ("COM_VAR", "cv"), ("UNITS UNITS_ACT UNITS_CAP UNITS_COM UNITS_MONY", "unit"),
]:
    for n in names.split():
        _CANON[n] = col


def columns_for(domain):
    cols, seen = [], {}
    for d in domain:
        base = _CANON.get(d.upper(), re.sub(r"\W", "_", d.lower()))
        seen[base] = seen.get(base, 0) + 1
        cols.append(base if seen[base] == 1 else f"{base}{seen[base]}")
    return cols


class Sym:
    __slots__ = ("name", "kind", "domain", "cols")

    def __init__(self, name, kind, domain):
        self.name, self.kind, self.domain = name, kind, list(domain)
        self.cols = columns_for(domain)
        if kind == "set" and len(domain) == 1 and domain[0] == "*" and name in _CANON:
            self.cols = [_CANON[name]]          # e.g. ALL_TS(*) -> column s


_SLOW = float(os.environ["TIMESPP_SLOW"]) if os.environ.get("TIMESPP_SLOW") else None


def _bytes(size):
    """'3GB', '500MB', '2.5GiB', '1T' -> bytes."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([KMGT]?)(I?B)?\s*", str(size).upper())
    if not m:
        raise ValueError(f"memory size not understood: {size!r} (e.g. 3GB, 500MB)")
    return int(float(m.group(1)) * 1024 ** " KMGT".index(m.group(2) or " "))


def _size(b):
    return f"{b / 2**30:.1f} GB" if b >= 2**30 else f"{b / 2**20:.0f} MB"


def _physical_memory():
    """Bytes of physical memory (Windows, Linux, macOS); 8 GB if the platform does not tell."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.ullTotalPhys
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        return 8 * 2**30


def default_threads():
    """DuckDB's threads when TIMESPP_THREADS is not set: 8 (or the processors, if fewer), 4 on Windows's NT heap."""
    from . import winheap
    return min(4 if winheap.heap() == "nt" else 8, os.cpu_count() or 4)


class _Con:
    """The DuckDB connection, noting the DataFrames registered on it: a statement that reads one is data crossing
    from Python into DuckDB, and is timed as such (see `DB.handoffs`)."""
    __slots__ = ("_c", "frames")

    def __init__(self, c):
        self._c, self.frames = c, set()

    def __getattr__(self, a):
        return getattr(self._c, a)

    def execute(self, sql, *a):
        # while model.tjb is written in pieces beside the steps (tjb.py), it is told of every statement
        if tjb._W is None:
            return self._c.execute(sql, *a)
        w = tjb.watch_begin(sql)
        try:
            return self._c.execute(sql, *a)
        finally:
            tjb.watch_end(w)

    def register(self, name, df):
        self.frames.add(name)
        return self._c.register(name, df)

    def unregister(self, name):
        self.frames.discard(name)
        return self._c.unregister(name)


class DB:
    def __init__(self, path=":memory:"):
        self.con = _Con(duckdb.connect(path))
        self.hand: dict[str, list] = {}        # hand-off timers: kind -> [seconds, statements, rows]
        # DuckDB's threads: TIMESPP_THREADS, else 8 (or the processors, if fewer), but 4 on Windows's default heap.
        # The results do not depend on it (every sum whose order could change the last digit is ordered).  On the
        # NT heap more threads are slower (they contend for its lock: on a large model 408 s with 4 threads, 712 s
        # with 22; on another 8% slower with 8 than with 4).  On the Segment Heap (the interpreter copy of
        # TIMES.py setup) and on Linux, 8 beat 4 by 10% and 12 added nothing.
        th = os.environ.get("TIMESPP_THREADS")
        self.con.execute(f"set threads = {max(1, int(th)) if th else default_threads()}")
        self.sym: dict[str, Sym] = {}
        self.s: dict[str, float] = {}          # scalars
        self.casing: dict[str, str] = {}
        self.log: list[str] = []               # QA log lines
        self.trace = None
        self.bounds: set[str] = set()          # variables with a bounds table B_<name>

    # ------------------------------------------------------------ declare
    def declare(self, name, kind, domain):
        name = name.upper()
        if name in self.sym:
            return self.sym[name]
        if kind == "par" and len(domain) == 0:
            self.s.setdefault(name, 0.0)
            kind = "scalar"
        sy = self.sym[name] = Sym(name, kind, domain)
        if kind == "scalar":
            return sy
        cols = ", ".join(f"{c} VARCHAR" for c in sy.cols)
        if kind == "par":
            cols += (", " if cols else "") + "value DOUBLE"
        self.con.execute(f'create table "{name}" ({cols})')
        n = len(sy.cols)
        # lookup macros go through a view with neutral column names (k0_.., val_), so that
        # arguments such as "y" always refer to the calling query, never to the looked-up table
        kcols = ", ".join(f"{c} as k{i}_" for i, c in enumerate(sy.cols))
        if kind == "par":
            kcols += (", " if kcols else "") + "value as val_"
        self.con.execute(f'create view k_{name} as select {kcols if kcols else "1 as one_"} from "{name}"')
        args = ", ".join(f"a{i}" for i in range(n))
        cond = " and ".join(f"t_.k{i}_=a{i}" for i in range(n)) or "true"
        self.con.execute(f'create macro in_{name}({args}) as exists(select 1 from k_{name} t_ where {cond})')
        if kind == "par":
            self.con.execute(f'create macro v_{name}({args}) as coalesce((select t_.val_ from k_{name} t_ where {cond}),0)')
        return sy

    def cols(self, name):
        return self.sym[name.upper()].cols

    # -------------------------------------------------------------- query
    def fmt(self, sql):
        if "{" in sql:
            sql = re.sub(r"\{(\w+)\}", lambda m: repr(float(self.s[m.group(1)])) if m.group(1) in self.s else m.group(0), sql)
        return sql

    def x(self, sql, params=None, kind=None):
        t = time.perf_counter()
        while True:
            try:
                r = self._x(sql, params)
                break
            except duckdb.OutOfMemoryException:
                # --low-memory: a statement that needs more than the memory limit (DuckDB cannot write every part of
                # a statement to disk) is run again with a higher limit; a statement that failed changed nothing.
                if not self._grow():
                    raise
        if kind is None:
            kind = "frame -> duckdb" if self._reads_frame(sql) else "sql"
        self.tally(kind, time.perf_counter() - t)
        return r

    def _reads_frame(self, sql):
        return bool(self.con.frames) and any(re.search(rf"\b{f}\b", sql) for f in self.con.frames)

    def tally(self, kind, seconds, rows=0):
        h = self.hand.get(kind)
        if h is None:
            h = self.hand[kind] = [0.0, 0, 0]
        h[0] += seconds; h[1] += 1; h[2] += rows

    def handoffs(self):
        """The hand-off timers, largest first: seconds, statements and rows per kind.  'sql' is every other
        statement; 'fetch' turns query results into Python tuples; 'frame -> duckdb' reads a registered DataFrame;
        'frame build' makes one from Python tuples; put.* are the steps of `put` (materialise into n_tmp, delete the
        old records of its keys, insert)."""
        return {k: {"seconds": round(v[0], 2), "statements": v[1], "rows": v[2]}
                for k, v in sorted(self.hand.items(), key=lambda kv: -kv[1][0])}

    mem_limit = None                    # bytes: DuckDB's memory limit, when one was set (see `set_memory`)

    def set_memory(self, limit):
        """SET memory_limit (e.g. '3GB'); a statement that needs more raises it, up to 85% of the physical memory."""
        self.con.execute(f"SET memory_limit='{limit}'")
        self.mem_limit = _bytes(limit)

    def _grow(self):
        if self.mem_limit is None:
            return False
        cap = int(0.85 * _physical_memory())
        new = min(int(self.mem_limit * 1.5), cap)
        if new <= self.mem_limit * 1.05:
            return False
        self.con.execute(f"SET memory_limit='{new // 2**20}MB'")
        print(f"  (DuckDB memory limit raised from {_size(self.mem_limit)} to {_size(new)}: a statement needed more)",
              flush=True)
        self.mem_limit = new
        return True

    def _x(self, sql, params=None):
        if _SLOW is None:
            return self.con.execute(self.fmt(sql), params) if params else self.con.execute(self.fmt(sql))
        import time, traceback
        t = time.time()
        r = self.con.execute(self.fmt(sql), params) if params else self.con.execute(self.fmt(sql))
        if time.time() - t >= _SLOW:                    # TIMESPP_SLOW=<seconds>: name the statements that take longer
            at = [f for f in traceback.extract_stack()[:-1] if "timespp" in f.filename and "engine.py" not in f.filename]
            where = f"{os.path.basename(at[-1].filename)}:{at[-1].lineno} {at[-1].name}" if at else "?"
            print(f"  SLOW {time.time() - t:7.1f}s  {where}  {' '.join(sql.split())[:160]}", flush=True)
        return r

    def q(self, sql):
        r = self.x(sql)
        t = time.perf_counter()
        rows = r.fetchall()
        self.tally("fetch", time.perf_counter() - t, len(rows))
        return rows

    def q1(self, sql):
        r = self.x(sql).fetchone()
        return None if r is None else r[0]

    def insert_rows(self, table, rows):
        """INSERT INTO table VALUES (..) for a list of tuples, in one statement through a DataFrame.
        (DuckDB's executemany runs the statement once per row: about 0.25 ms each, minutes for the 844,200
        discount-rate rows of a 70-region model.)  A None or NaN in a numeric column arrives as NULL, as with
        executemany."""
        if not rows:
            return
        import pandas as pd
        t = time.perf_counter()
        rows = list(rows)
        self.con.register("rows_", pd.DataFrame(rows, columns=[f"col{i}" for i in range(len(rows[0]))]))
        self.tally("frame build", time.perf_counter() - t, len(rows))
        try:
            self.x(f"insert into {table} select * from rows_", kind="frame -> duckdb")
            self.hand["frame -> duckdb"][2] += len(rows)
        finally:
            self.con.unregister("rows_")

    def card(self, name):
        return self.q1(f'select count(*) from "{name.upper()}"')

    # ---------------------------------------------------------------- sets
    def add(self, name, select):
        """S(idx) = YES for the tuples returned by `select`."""
        name = name.upper(); c = ", ".join(self.cols(name))
        if self._empty(name):                    # nothing to exclude: the distinct rows as they come (half the time)
            self.x(f'insert into "{name}" select distinct {c} from ({select}) n_')
            return
        self.x(f'insert into "{name}" select distinct {c} from ({select}) n_ '
               f'where not exists(select 1 from "{name}" o_ where ({self._eq(name,"o_","n_")}))')

    def _empty(self, name):
        """True when the table has no rows (one row is enough to know otherwise)."""
        return self.con.execute(f'select count(*) from (select 1 from "{name}" limit 1)').fetchone()[0] == 0

    def remove(self, name, select=None, where=None):
        """S(idx) = NO for tuples returned by `select`, or rows matching `where`."""
        name = name.upper()
        if where is not None:
            self.x(f'delete from "{name}" where {where}')
        else:
            self.x(f'delete from "{name}" o_ where exists(select 1 from ({select}) n_ where {self._eq(name,"o_","n_")})')

    def assign(self, name, select):
        """Replace the whole set by `select` (OPTION CLEAR + assignment)."""
        self.clear(name); self.add(name, select)

    def clear(self, *names):
        for n in names:
            n = n.upper()
            if self.sym[n].kind == "scalar":
                self.s[n] = 0.0
            else:
                self.x(f'delete from "{n}"')

    def project(self, dst, src, cols=None):
        """OPTION dst < src / dst <= src : projection of src onto dst's columns.
        `cols` gives the src columns to take (default: columns of dst by name)."""
        dst = dst.upper(); src = src.upper()
        cols = cols or self.cols(dst)
        sel = ", ".join(f"{sc} as {dc}" for sc, dc in zip(cols, self.cols(dst)))
        self.assign(dst, f'select distinct {sel} from "{src}"')

    def _eq(self, name, a, b):
        return " and ".join(f"{a}.{c}={b}.{c}" for c in self.cols(name)) or "true"

    # ---------------------------------------------------------- parameters
    def put(self, name, select, zero="delete"):
        """Assign parameter values from `select` (index columns + value).

        zero = 'delete' : GAMS '='   - a zero result removes the record
        zero = 'skip'   : GAMS '$='  - zero results leave the target untouched
        zero = 'eps'    : zero results are stored as EPS (explicit zero)
        NULL values are always skipped.
        """
        name = name.upper(); c = ", ".join(self.cols(name))
        frame = self._reads_frame(select)
        t = time.perf_counter()
        target_empty = self._empty(name)
        self.tally("put.empty checks", time.perf_counter() - t)
        if target_empty:
            # nothing to replace: the rows go straight into the table, without the copy in n_tmp (the same rows, in the
            # same order, as the steps below would insert)
            keep = "value is not null" + ("" if zero == "eps" else " and (value <> 0 or isnan(value))")
            kind = "put.insert direct" + (" (from a frame)" if frame else "")
            r = self.x(f'insert into "{name}" select {c + ", " if c else ""}value from ({select}) where {keep}', kind=kind)
            self.hand[kind][2] += r.fetchone()[0]
            return
        r = self.x(f"create or replace temp table n_tmp as select {c + ', ' if c else ''}value from ({select}) where value is not null",
                   kind="put.materialise" + (" (from a frame)" if frame else ""))
        self.hand["put.materialise" + (" (from a frame)" if frame else "")][2] += r.fetchone()[0]
        if zero == "skip":
            self.x("delete from n_tmp where value = 0", kind="put.materialise")
        t = time.perf_counter()
        empty = self._empty("n_tmp")
        self.tally("put.empty checks", time.perf_counter() - t)
        if empty:
            return
        # the old records of the keys assigned
        r = self.x(f'delete from "{name}" o_ where exists(select 1 from n_tmp n_ where {self._eq(name,"o_","n_")})',
                   kind="put.delete")
        self.hand["put.delete"][2] += r.fetchone()[0]
        keep = "" if zero == "eps" else " where value <> 0 or isnan(value)"
        r = self.x(f'insert into "{name}" select {c + ", " if c else ""}value from n_tmp{keep}', kind="put.insert")
        self.hand["put.insert"][2] += r.fetchone()[0]

    def tmp(self, name, select):
        """Scratch relation (GAMS work sets such as TRACKP, RXX): a temp table named `name`."""
        self.x(f"create or replace temp table {name} as {select}")
        return self.q1(f"select count(*) from {name}")

    def zap(self, name, where="true"):
        self.x(f'delete from "{name.upper()}" where {where}')

    # --------------------------------------------------------------- load
    def load_rows(self, name, rows):
        name = name.upper(); sy = self.sym[name]
        if not rows:
            return
        import pandas as pd
        cols = sy.cols + (["value"] if sy.kind == "par" else [])
        t = time.perf_counter()
        # the labels as Python objects: DuckDB reads them 2.5x as fast as pandas's own string type, which pandas 3
        # gives them otherwise (TIMESPP_LOAD_OBJECT=0); the value as float64 either way
        if LOAD_OBJECT:
            df = pd.DataFrame(rows, columns=cols, dtype=object)
            if sy.kind == "par":
                df["value"] = df["value"].astype("float64")
        else:
            df = pd.DataFrame(rows, columns=cols)
        self.con.register("ld_", df)
        self.tally("load_rows: frame build", time.perf_counter() - t, len(df))
        self.x(f'insert into "{name}" select * from ld_', kind="load_rows: frame -> duckdb")
        self.hand["load_rows: frame -> duckdb"][2] += len(df)
        self.con.unregister("ld_")
