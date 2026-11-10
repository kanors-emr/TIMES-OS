# SPDX-License-Identifier: GPL-3.0-or-later
"""Julia kernels inside the preprocessor's process: the switch, the start of Julia, tables across and back.

A kernel does one step's computation in Julia (times_pp/jlkernels, package TimesPPKernels) instead of Python / SQL,
to the bit; the SQL stays the reference. How to add one: jlkernels/README.md.

The switch: TIMESPP_KERNELS, a comma list of kernel names, or `all`; `none` (or empty, `off`, `0`): no kernel, and
neither Julia nor this module's machinery is touched (the preprocessor is then exactly what it is without this module).
Unset: the kernels of DEFAULT, when setup has installed TimesPPKernels (settings.json's julia_bindir and the package in
the project's Manifest.toml); if it has not, or if Julia does not start, the reference runs instead, with one line in
the log saying so. A kernel asked for by name stops the run when Julia does not start.
`check:<name>` (or check:all) runs the reference and the kernel on every call, compares every table the call writes
(rows, order, Float64 bits) and stops at the first difference, naming the table.

Julia runs in this process: libjulia is loaded with ctypes and initialised once, at the first kernel call
(start-up), then TimesPPKernels is loaded (precompiled by `TIMES.py setup`). Columns cross as C pointers to
NumPy buffers, in both directions, without conversion: integers for labels, Float64 for values. Labels get codes in
DuckDB (`Labels`: a table of every label a kernel has seen, codes for the life of the process), so a kernel works on
integers and the result comes back as codes, turned into labels by DuckDB when it reads the frame (categorical
columns).

Where Julia is: TIMESPP_JULIA_BINDIR, else settings.json's julia_bindir (written by setup), else the `julia` program
is asked once. Its project: TIMESPP_KERNELS_PROJECT, else the repository's .julia_env. Julia's threads:
TIMESPP_KERNELS_THREADS (default 1: the kernels are serial; DuckDB has the processors).
"""
from __future__ import annotations
import ctypes, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAMES = ("fillparm", "coef_ptr", "fillcost", "objective", "retirement")  # the kernels there are (TimesPPKernels also has `echo`, for tests)
DEFAULT = ("fillparm", "fillcost", "objective")   # on when TIMESPP_KERNELS is unset (and installed); coef_ptr is not:
                                                   # it does not pay; retirement is not: a few seconds won where there is
                                                   # much retirement, lost where there is little (TIMESPP_KERNELS names it)
_OFF = {"", "none", "off", "0", "no"}


class Decline(Exception):
    """The kernel does not take this call (input it does not cover): the reference runs instead."""


class Mismatch(Exception):
    """check:<name>: the kernel's result differs from the reference's."""


# ------------------------------------------------------------------------------------------------ the switch
def installed():
    """Whether setup has installed TimesPPKernels: libjulia's folder known and the package in the project."""
    b = os.environ.get("TIMESPP_JULIA_BINDIR") or _settings().get("julia_bindir")
    project = os.environ.get("TIMESPP_KERNELS_PROJECT") or os.path.join(ROOT, ".julia_env")
    try:
        with open(os.path.join(project, "Manifest.toml"), encoding="utf-8") as f:
            man = f.read()
    except OSError:
        return False
    return bool(b) and os.path.isdir(b) and "TimesPPKernels" in man


_AUTO = False                               # the kernels are on by default (TIMESPP_KERNELS unset)
_NOTE = ""                                  # why the default kernels are off, for the log


def _parse():
    global _AUTO, _NOTE
    raw = os.environ.get("TIMESPP_KERNELS")
    if raw is None:
        if installed():
            _AUTO = True
            return set(DEFAULT), set()
        _NOTE = "not installed (run: python TIMES.py setup); the Python code ran"
        return set(), set()
    v = raw.strip()
    on, check = set(), set()
    if v.lower() in _OFF:
        return on, check
    for w in filter(None, (s.strip() for s in v.split(","))):
        dst = on
        if w.startswith("check:"):
            dst, w = check, w[6:]
        names = set(NAMES) if w == "all" else {w}
        unknown = names - set(NAMES)
        if unknown:
            raise SystemExit(f"TIMESPP_KERNELS: no kernel {', '.join(sorted(unknown))} (there are: {', '.join(NAMES)})")
        dst |= names
    return on - check, check




def mode(name):
    """'off', 'on' or 'check' for kernel `name`."""
    return "check" if name in _CHECK else "on" if name in _ON else "off"


def active():
    return bool(_ON or _CHECK or _NOTE)


def _fall_back(e):
    """The default kernels when Julia does not start: all off for this run, the reference instead, said once."""
    global _NOTE
    _ON.clear()
    _NOTE = f"Julia did not start ({str(e).splitlines()[0][:200]}); the Python code ran"


# ------------------------------------------------------------------------------------------------ timers
_T = {"julia start (jl_init)": 0.0, "TimesPPKernels load": 0.0}
_K = {}            # kernel -> {calls, declined, rows_in, rows_out, seconds by part}


def tally(kernel, part, seconds, rows=0):
    k = _K.setdefault(kernel, {"calls": 0, "declined": 0, "rows to julia": 0, "rows from julia": 0, "s": {}})
    k["s"][part] = k["s"].get(part, 0.0) + seconds
    if part == "duckdb -> julia":
        k["rows to julia"] += rows
    elif part == "julia -> duckdb":
        k["rows from julia"] += rows


def report():
    """What the kernels cost: start-up, and per kernel its calls, rows each way and seconds by part. 'julia: kernel'
    and 'julia: compilation' are Julia's own measure of the kernel calls (compilation is inside the call time)."""
    out = {"start-up": {k: round(v, 3) for k, v in _T.items()}, "kernels": {}}
    if _NOTE:
        out["note"] = _NOTE
    out["default"] = os.environ.get("TIMESPP_KERNELS") is None
    try:                                          # Julia's own clock; absent when the kernels did not start fully
        times = _JL.times() if _JL.lib is not None and "times" in (getattr(_JL, "f", None) or {}) else {}
    except Exception:
        times = {}
    for name, k in _K.items():
        d = {kk: vv for kk, vv in k.items() if kk != "s"}
        d["seconds"] = {p: round(s, 3) for p, s in sorted(k["s"].items(), key=lambda kv: -kv[1])}
        if name in times:
            d["seconds"]["julia: kernel (Julia's clock)"] = round(times[name][1], 3)
            d["seconds"]["julia: compilation"] = round(times[name][2], 3)
        out["kernels"][name] = d
    return out


# ------------------------------------------------------------------------------------------------ Julia
_TYPES = {1: "int32", 2: "int64", 3: "float64", 4: "uint8"}
_CODES = {v: k for k, v in _TYPES.items()}


def _settings():
    try:
        with open(os.path.join(ROOT, "settings.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def julia_bindir():
    """The folder of libjulia: TIMESPP_JULIA_BINDIR, settings.json's julia_bindir, or Sys.BINDIR of `julia`."""
    b = os.environ.get("TIMESPP_JULIA_BINDIR") or _settings().get("julia_bindir")
    if b:
        return b
    import shutil
    exe = _settings().get("julia") or shutil.which("julia")
    if not exe:
        raise RuntimeError("Julia not found: run `python TIMES.py setup`, or set TIMESPP_JULIA_BINDIR")
    r = subprocess.run([exe, "--startup-file=no", "-e", "print(Sys.BINDIR)"], capture_output=True, text=True, timeout=300)
    return r.stdout.strip()


_ON, _CHECK = _parse()                      # here, after _settings: the switch is read once, when the module loads


class _Julia:
    def __init__(self):
        self.lib = None
        self.f = {}

    def start(self):
        if self.lib is not None:
            return
        t = time.perf_counter()
        bindir = julia_bindir()
        lib_name = {"win32": "libjulia.dll", "darwin": "libjulia.dylib"}.get(sys.platform, "libjulia.so")
        libdir = bindir if sys.platform == "win32" else os.path.join(os.path.dirname(bindir), "lib")
        if sys.platform == "win32":
            os.add_dll_directory(bindir)
            os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")    # Julia's own libraries
        lib = ctypes.CDLL(os.path.join(libdir, lib_name), mode=ctypes.RTLD_GLOBAL)
        project = os.environ.get("TIMESPP_KERNELS_PROJECT") or os.path.join(ROOT, ".julia_env")
        threads = os.environ.get("TIMESPP_KERNELS_THREADS", "1")
        # Julia leaves the signals to Python (Ctrl-C stays Python's), no startup file, the project with TimesPPKernels
        args = [b"julia", b"--handle-signals=no", b"--startup-file=no", f"--threads={threads}".encode(),
                f"--project={project}".encode()]
        argv = (ctypes.c_char_p * len(args))(*args)
        argc = ctypes.c_int(len(args))
        pargv = ctypes.cast(argv, ctypes.POINTER(ctypes.c_char_p))
        lib.jl_parse_opts(ctypes.byref(argc), ctypes.byref(pargv))
        lib.jl_init.restype = None
        lib.jl_init()
        lib.jl_eval_string.restype = ctypes.c_void_p
        lib.jl_eval_string.argtypes = [ctypes.c_char_p]
        lib.jl_string_ptr.restype = ctypes.c_char_p
        lib.jl_string_ptr.argtypes = [ctypes.c_void_p]
        self.lib = lib
        # Julia's GC stops every thread that runs Julia; this thread is one (jl_init) and, back in Python, would never
        # reach a safepoint: a kernel called from another thread (a part run beside the main thread, side.py) would
        # wait for it for ever. So between calls this thread is marked GC-safe; the kernels' C entries (@cfunction)
        # make the thread GC-unsafe while they run and restore the state, and eval_str leaves and re-enters it.
        self.internal = ctypes.CDLL(os.path.join(libdir, lib_name.replace("libjulia", "libjulia-internal")))
        self.internal.jl_gc_safe_enter.restype = ctypes.c_int8
        self.internal.jl_gc_safe_enter.argtypes = [ctypes.c_void_p]
        self.internal.jl_gc_safe_leave.restype = None
        self.internal.jl_gc_safe_leave.argtypes = [ctypes.c_void_p, ctypes.c_int8]
        lib.jl_unbox_voidpointer.restype = ctypes.c_void_p
        lib.jl_unbox_voidpointer.argtypes = [ctypes.c_void_p]
        self.ptls = lib.jl_unbox_voidpointer(lib.jl_eval_string(b"ccall(:jl_get_ptls_states, Ptr{Cvoid}, ())"))
        self.gc_state = self.internal.jl_gc_safe_enter(self.ptls)
        _T["julia start (jl_init)"] = time.perf_counter() - t
        t = time.perf_counter()
        r = self.eval_str('try; @eval Main using TimesPPKernels; "ok " * Main.TimesPPKernels.cpointers(); '
                          'catch e; "error " * sprint(showerror, e); end')
        _T["TimesPPKernels load"] = time.perf_counter() - t
        if not r.startswith("ok "):
            raise RuntimeError(f"TimesPPKernels could not be loaded (run `python TIMES.py setup`): {r[6:]}")
        ptr = dict(w.split("=") for w in r[3:].split())
        P, I32, I64 = ctypes.c_void_p, ctypes.c_int32, ctypes.c_int64
        self.f["call"] = ctypes.CFUNCTYPE(I32, ctypes.c_char_p, I32, ctypes.POINTER(P), ctypes.POINTER(I32),
                                          ctypes.POINTER(I64), ctypes.POINTER(I64))(int(ptr["call"]))
        self.f["ncols"] = ctypes.CFUNCTYPE(I32, I64)(int(ptr["ncols"]))
        self.f["col"] = ctypes.CFUNCTYPE(I32, I64, I32, ctypes.POINTER(P), ctypes.POINTER(I32),
                                         ctypes.POINTER(I64))(int(ptr["col"]))
        self.f["free"] = ctypes.CFUNCTYPE(I32, I64)(int(ptr["free"]))
        self.f["error"] = ctypes.CFUNCTYPE(ctypes.c_char_p)(int(ptr["error"]))
        self.f["times"] = ctypes.CFUNCTYPE(ctypes.c_char_p)(int(ptr["times"]))

    def eval_str(self, code):
        """Evaluate Julia code that returns a String; the text."""
        self.internal.jl_gc_safe_leave(self.ptls, self.gc_state)
        try:
            v = self.lib.jl_eval_string(code.encode())
            out = self.lib.jl_string_ptr(v).decode() if v else None
        finally:
            self.gc_state = self.internal.jl_gc_safe_enter(self.ptls)
        if out is None:
            raise RuntimeError(f"Julia could not evaluate: {code[:200]}")
        return out

    def times(self):
        out = {}
        for line in self.f["times"]().decode().splitlines():
            n, c, s, comp = line.split()
            out[n] = (int(c), float(s), float(comp))
        return out

    def call(self, name, cols):
        """Kernel `name` on the columns (NumPy arrays of int32, int64, float64 or uint8): its columns, as NumPy
        arrays (copies: Julia's memory is released before this returns). Timed as 'julia (call)' (the kernel, the
        copies; not Julia's start)."""
        import numpy as np
        self.start()                                # (timed apart: start-up)
        t0 = time.perf_counter()
        cols = [np.ascontiguousarray(c) for c in cols]
        n = len(cols)
        ptrs = (ctypes.c_void_p * n)(*[c.ctypes.data for c in cols])
        types = (ctypes.c_int32 * n)(*[_CODES[c.dtype.name] for c in cols])
        lens = (ctypes.c_int64 * n)(*[len(c) for c in cols])
        h = ctypes.c_int64(0)
        rc = self.f["call"](name.encode(), n, ptrs, types, lens, ctypes.byref(h))
        if rc != 0:
            msg = self.f["error"]().decode()
            if msg.startswith("kernel declines: "):
                raise Decline(msg.split("\n")[0][17:])
            raise RuntimeError(f"kernel {name} failed in Julia: {msg}")
        try:
            out = []
            p, t, ln = ctypes.c_void_p(), ctypes.c_int32(), ctypes.c_int64()
            for i in range(1, self.f["ncols"](h.value) + 1):
                self.f["col"](h.value, i, ctypes.byref(p), ctypes.byref(t), ctypes.byref(ln))
                dt = np.dtype(_TYPES[t.value])
                if ln.value == 0:
                    out.append(np.empty(0, dt))
                else:
                    buf = (ctypes.c_char * (ln.value * dt.itemsize)).from_address(p.value)
                    out.append(np.frombuffer(buf, dt).copy())
            return out
        finally:
            self.f["free"](h.value)
            tally(name, "julia (call)", time.perf_counter() - t0)


_JL = _Julia()
call = _JL.call


def start():
    """Start Julia now (it starts at the first kernel call otherwise). Call it in the main thread before a kernel
    runs in another thread: Julia is initialised in the thread that starts it."""
    _JL.start()


# ------------------------------------------------------------------------------------------------ labels
class Labels:
    """Integer codes for labels, the same in every table and for the life of the database: the table
    __klab(label VARCHAR, code INTEGER), codes 0, 1, 2 ... A kernel sees only codes; DuckDB turns them into codes on
    the way in (to_julia) and back into labels on the way out (from_julia), both by a join with __klab."""

    def __init__(self, db):
        self.db = db
        db.con.execute("create temp table __klab (label VARCHAR, code INTEGER)")
        self.n = 0

    def add(self, sql_labels):
        """Codes for the labels the query `sql_labels` (one column) returns that have none yet."""
        self.db.x(f"""insert into __klab select x, {self.n} + cast(row_number() over () as INTEGER) - 1
                      from (select distinct x from ({sql_labels}) q(x) where x is not null
                            except select label from __klab)""", kind="kernels: codes")
        self.n = self.db.con.execute("select count(*) from __klab").fetchone()[0]


def labels(db):
    k = db.__dict__.get("_kernels")
    if k is None or k["con"] is not db.con:     # __klab is a temp table: one per connection (side.py)
        k = db._kernels = {"labels": Labels(db), "ctrl": {}, "con": db.con}
    return k["labels"]


def to_julia(db, kernel, table, label_cols, extra="", where=None, alias=""):
    """The records of `table` for a kernel, in table order, as NumPy arrays: the label columns as codes (int32
    columns c0, c1, ... in the order of `label_cols`; a record with a NULL label is left out), then the `extra`
    select expressions, written over the table's columns as f.<column>; `where`, a condition on the table's rows (with
    `alias`, the name it gives the table, e.g. "a" for a condition written over a.<column>). Timed as 'duckdb -> julia'."""
    t = time.perf_counter()
    if label_cols:
        labels(db).add(" union all ".join(f'select {c} from "{table}"' for c in label_cols))
    cond = " and ".join([f"{c} is not null" for c in label_cols] + ([where] if where else [])) or "true"
    sel = ", ".join([f"k{i}.code as c{i}" for i in range(len(label_cols))] + ([extra] if extra else []))
    joins = " ".join(f"join __klab k{i} on k{i}.label = f.{c}" for i, c in enumerate(label_cols))
    r = db.con.execute(f'select {sel} from (select rowid as rid_, * from "{table}" {alias} where {cond}) f {joins} '
                       f'order by f.rid_').fetchnumpy()
    tally(kernel, "duckdb -> julia", time.perf_counter() - t, len(next(iter(r.values()))) if r else 0)
    return r


BAD_INT = -2147483648                  # (rows_to_julia: a year label that is not the text of an integer)


def rows_to_julia(db, kernel, src, spec, where=None):
    """The rows of table `src` (in table order, those that meet `where`) or of the query `src` (in its order), as
    NumPy arrays, one per column of `spec`, a list of (column, kind): L a label as its code (int32), Y a label that is
    an integer as that integer (int32), V a value (float64; NULL as NaN). Declines a NULL label and a Y label that is
    not the text of an integer."""
    import numpy as np
    table = src
    if not src.isidentifier():
        table = "t_kin"
        db.x(f"create or replace temp table t_kin as {src}")
    n = db.q1(f'select count(*) from "{table}"' + (f" where {where}" if where else ""))
    labels_ = [c for c, k in spec if k == "L"]
    extra = ", ".join(f"coalesce(try_cast(f.{c} as INTEGER), {BAD_INT}) as {c}" if k == "Y" else
                      f"coalesce(cast(f.{c} as DOUBLE), 'NaN'::DOUBLE) as {c}" for c, k in spec if k != "L")
    r = to_julia(db, kernel, table, labels_, extra, where=where)
    out, li = [], 0
    for c, k in spec:
        if k == "L":
            a = np.asarray(r[f"c{li}"], np.int32)
            li += 1
        elif k == "Y":
            a = np.asarray(r[c], np.int32)
            if len(a) and a.min() == BAD_INT:
                raise Decline("a year that is not the text of an integer")
        else:
            a = np.asarray(r[c], np.float64)
        if len(a) != n:
            raise Decline("a NULL label")
        out.append(a)
    return out


def frame_to_julia(db, kernel, rows, spec):
    """rows_to_julia over Python rows (tuples, in the order given; spec as there)."""
    import numpy as np, pandas as pd
    if not rows:
        return [np.empty(0, np.float64 if k == "V" else np.int32) for _c, k in spec]
    db.con.register("f_kin", pd.DataFrame(list(rows), columns=[c for c, _k in spec], dtype=object))
    try:
        db.x("create or replace temp table t_kin as select * from f_kin")
    finally:
        db.con.unregister("f_kin")
    return rows_to_julia(db, kernel, "t_kin", spec)


def from_julia(db, rel, label_cols, codes, cols=None, select=None):
    """A kernel's result as a relation DuckDB can read: registers the frame `rel` (the codes as c0, c1, ... and the
    other columns `cols`, a dict of NumPy arrays) and returns the SQL of a select over it with the label columns as
    VARCHAR under the names `label_cols`, then `select` (expressions over f.<column>; default: the columns as they
    are). Unregister `rel` when the statement that reads it is done. The rows come in no particular order (they are
    a set: identity is to the rows, see same_rows)."""
    import pandas as pd
    d = {f"c{i}": c for i, c in enumerate(codes)}
    d.update(cols or {})
    db.con.register(rel, pd.DataFrame(d, copy=False))
    sel = ", ".join([f"k{i}.label as {c}" for i, c in enumerate(label_cols)]
                    + [select or ", ".join(f"f.{c}" for c in (cols or {}))])
    joins = " ".join(f"join __klab k{i} on k{i}.code = f.c{i}" for i in range(len(label_cols)))
    return f"(select {sel} from {rel} f {joins})"


# ------------------------------------------------------------------------------------------------ checks
def snapshot(db, tables):
    """Copies of the tables (in table order), for check mode."""
    for i, n in enumerate(tables):
        db.con.execute(f'create or replace temp table __kchk{i} as select * from "{n}"')


def restore(db, tables):
    for i, n in enumerate(tables):
        db.con.execute(f'delete from "{n}"')
        db.con.execute(f'insert into "{n}" select * from __kchk{i}')


def same_rows(a, b):
    """Two tables fetched as {column: NumPy array}: 'identical' (the same rows in the same order), 'same rows, other
    order', or what differs. Rows are compared to the bit: every label equal, every Float64 the same bit pattern
    (-0.0 and 0.0 differ; an EPS row, value 0, and an absent row differ). Table order is not part of identity: two
    runs of the same code can give the rows of a table in another order (DuckDB inserts in parallel)."""
    import numpy as np, pandas as pd
    if list(a) != list(b):
        return f"DIFFERENT columns {list(a)} / {list(b)}"
    na = len(next(iter(a.values()))) if a else 0
    nb = len(next(iter(b.values()))) if b else 0
    if na != nb:
        return f"DIFFERENT: {na} rows against {nb}"

    def frame(t):
        return pd.DataFrame({c: (np.asarray(v, np.float64).view(np.int64) if np.asarray(v).dtype.kind == "f"
                                 else np.asarray(v, object)) for c, v in t.items()})

    fa, fb = frame(a), frame(b)
    if all((fa[c].to_numpy() == fb[c].to_numpy()).all() for c in fa):
        return "identical"
    by = list(fa.columns)
    fa = fa.sort_values(by, kind="stable", ignore_index=True)
    fb = fb.sort_values(by, kind="stable", ignore_index=True)
    bad = np.zeros(na, bool)
    for c in by:
        bad |= fa[c].to_numpy() != fb[c].to_numpy()
    if not bad.any():
        return "same rows, other order"
    return f"DIFFERENT: {int(bad.sum())} rows differ"


def differs(db, table, ref_table):
    """None when `table` has the rows of `ref_table`, to the bit (see same_rows); else what differs."""
    r = same_rows(db.con.execute(f'select * from "{table}"').fetchnumpy(),
                  db.con.execute(f'select * from "{ref_table}"').fetchnumpy())
    return None if r in ("identical", "same rows, other order") else r


def _declined(k, e):
    """A declined call: counted, and its reason kept (each reason once, for the log)."""
    k["declined"] += 1
    why = k.setdefault("why declined", [])
    if str(e) not in why:
        why.append(str(e))


def run(kernel, db, tables, reference, fast):
    """Run one call of a step: the kernel `fast()` or the reference `reference()`, as the switch says.

    tables: the tables the call writes (compared in check mode). A kernel that declines (Decline) leaves the call
    to the reference. In check mode the reference runs first, then the tables are put back as they were, the kernel
    runs, and each table is compared with the reference's; the first difference stops the run."""
    m = mode(kernel)
    if m == "on" and _AUTO and _JL.lib is None:
        try:
            _JL.start()
        except Exception as e:                      # default kernels only: a kernel asked for by name stops the run
            _fall_back(e)
            return reference()
    if m == "off" or mode(kernel) == "off":
        return reference()
    k = _K.setdefault(kernel, {"calls": 0, "declined": 0, "rows to julia": 0, "rows from julia": 0, "s": {}})
    k["calls"] += 1
    if m == "on":
        t = time.perf_counter()
        try:
            fast()
            tally(kernel, "total (kernel path)", time.perf_counter() - t)
            return
        except Decline as e:
            _declined(k, e)
            tally(kernel, "total (kernel path)", time.perf_counter() - t)
        return reference()
    snapshot(db, tables)
    t = time.perf_counter()
    reference()
    tally(kernel, "check: reference", time.perf_counter() - t)
    for i, n in enumerate(tables):
        db.con.execute(f'create or replace temp table __kref{i} as select * from "{n}"')
    restore(db, tables)
    t = time.perf_counter()
    try:
        fast()
    except Decline as e:
        _declined(k, e)
        restore(db, tables)
        reference()
        return
    tally(kernel, "total (kernel path)", time.perf_counter() - t)
    for i, n in enumerate(tables):
        d = differs(db, n, f"__kref{i}")
        if d:
            raise Mismatch(f"kernel {kernel}: table {n} differs from the reference: {d}")
    for i in range(len(tables)):
        db.con.execute(f"drop table if exists __kref{i}")
        db.con.execute(f"drop table if exists __kchk{i}")
