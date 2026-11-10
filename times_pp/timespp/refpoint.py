# SPDX-License-Identifier: GPL-3.0-or-later
"""The results of an earlier run that a run reads: its solution point (spoint.mod) and its base prices
(wrtbprice.mod, readbprice.mod).

TIMES in GAMS keeps them as GDX files:

    <GDXPATH><run>_p.gdx    the solution point (SPOINT 1 or YES; spoint.mod 14-18): levels and marginals of every
                            variable and equation, which a later run loads (LPOINT, FIXBOH: execute_loadpoint)
    <GDXPATH><run>_DP.gdx   the base prices SOL_BPRICE (and SOL_ACFR) of the demands (wrtbprice.mod 34), and the same
    com_bprice.gdx          in the working folder (wrtbprice.mod 33); a later run reads them with TIMESED
    <GDXPATH><run>.gdx      the whole run (the GDX that GAMS writes at the end, GDX=); FIXBOH loads it first

GDXPATH is the folder gamssave/ of the run folder when there is one, else the run folder (initmty.mod 415-416). A
run reads %GDXPATH%<LPOINT> and %GDXPATH%<TIMESED>_DP: the name is pasted after GDXPATH, so it may carry a path
(spoint.mod 10, readbprice.mod 14); com_bprice is read from the run folder itself.

This implementation finds them by the same rule, from the run folder as its user gave it (not from a copy of it),
and writes the same content where TIMES writes it, as Parquet files of the same name (<run>_p.parquet,
<run>_DP.parquet, com_bprice.parquet). It reads only those: a Parquet file with the mark of the run of this
implementation that wrote it. A GDX file (written by GAMS) is not read, so that a run never mixes the results of
the two. The solution point <run>_p is written after every solve, not only with SPOINT: it stands in for the GDX
of the whole run that a run of TIMES in GAMS writes with GDX= on its command line.

Veda copies the GDX files a run reads into its run folder before it starts it; nothing copies the Parquet files of
this implementation. So when a file is not where TIMES looks, it is looked for where the run that wrote it left it:

    the folders the user names (TIMESPP_POINTS, from --points or TIMES_POINTS; several separated by os.pathsep):
        <folder>\\<file> and <folder>\\GAMSSAVE\\<file>: the result folder or the run folder of the earlier run
    the result folders of the runner (TIMESPP_RESULTS: its --out folder and runs\\):
        <results>\\<run>\\<file>, <run> the name of the file without _p or _DP; read only when its mark names the run <run>

A file found there is read as one found where TIMES looks (the log names it). With TIMESPP_BASE_FROM_GAMS the run
reads what GAMS reads, and only where GAMS reads it.

A Parquet file of results is one table: symbol, kind (variable, equation, parameter), dim, d0..d<n> (the labels),
level (the value of a parameter), marginal.  A parameter record of value 0 is EPS.  One row of kind "written_by" says
which run wrote the file (d0: the run name, d1: its folder, d2: the time).
"""
import os

EXT = ".parquet"
KINDS = ("variable", "equation", "parameter")


def gdxpath(folder):
    """The folder of the results of earlier runs: initmty.mod 416  $ IFI EXIST gamssave\\nul $SETGLOBAL GDXPATH 'gamssave/'"""
    for f in os.listdir(folder) if os.path.isdir(folder) else ():
        if f.lower() == "gamssave" and os.path.isdir(os.path.join(folder, f)):
            return os.path.join(folder, f)
    return folder


def run_folder(db=None):
    """The run folder as its user gave it: where TIMES in GAMS runs, and where the results of earlier runs are found
    and written.  A runner that works in a copy of the folder names the original in TIMESPP_RUN_FOLDER."""
    return os.environ.get("TIMESPP_RUN_FOLDER") or getattr(db, "case_dir", None) or "."


def from_gams():
    """True when the run is being compared with a run of TIMES in GAMS (TIMESPP_BASE_FROM_GAMS=1): it then reads the
    results of earlier runs that GAMS reads (the GDX files), so that both start from the same point."""
    return os.environ.get("TIMESPP_BASE_FROM_GAMS", "").strip() == "1"


def locate(folder, name, in_gdxpath=True):
    """(folder, stem) of the file TIMES names %GDXPATH%<name> from the run folder (in_gdxpath False: <name> in the run
    folder itself, as com_bprice): name may carry a path, relative to GDXPATH or absolute."""
    base = gdxpath(folder) if in_gdxpath else folder
    p = os.path.normpath(os.path.join(base, name.replace("\\", "/")))
    return os.path.dirname(p), os.path.basename(p)


def _exists(folder, name):
    """A file of the folder named name, in any case (GAMS on Windows), or None."""
    low = name.lower()
    for f in os.listdir(folder) if os.path.isdir(folder) else ():
        if f.lower() == low and os.path.isfile(os.path.join(folder, f)):
            return os.path.join(folder, f)
    return None


def no_gdx():
    """True with the setting TIMES_NO_GDX=1: the GDX library is not used."""
    return os.environ.get("TIMES_NO_GDX", "").strip() == "1"


def _ours(path):
    """True when the Parquet file at path carries the mark of a run of this implementation."""
    return describe(path)["written_by"].startswith("this implementation")


def _folders(var):
    """The folders a setting of the runner names (os.pathsep between them), as given."""
    return [f for f in os.environ.get(var, "").split(os.pathsep) if f.strip()]


def run_of(stem):
    """The run that writes a file named stem: the name without _p (the solution point) or _DP (the base prices)."""
    for end in ("_p", "_DP"):
        if stem.lower().endswith(end.lower()) and len(stem) > len(end):
            return stem[:-len(end)]
    return stem


def _mark_run(path):
    """The run named in the mark of a Parquet file of results, or None."""
    try:
        import duckdb
        con = duckdb.connect()
        try:
            w = con.execute(f"select d0 from read_parquet('{_q(path)}') where kind = 'written_by' limit 1").fetchone()
        finally:
            con.close()
        return str(w[0]) if w else None
    except Exception:
        return None


def elsewhere(stems):
    """[(folder, stem, run)] where the earlier run left the files named stems, beyond where TIMES looks: the folders
    of --points (run None: any run of this implementation), then <results>\\<run> of the runner's result folders (the
    file's mark must name <run>).  stems are file names without their folder (a path in LPOINT is TIMES's look)."""
    out = []
    for s in stems:
        for f in _folders("TIMESPP_POINTS"):
            out += [(f, s, None), (gdxpath(f), s, None)]
        for r in _folders("TIMESPP_RESULTS"):
            out.append((os.path.join(r, run_of(s)), s, run_of(s)))
    seen, uniq = set(), []
    for d, s, r in out:
        k = (os.path.normcase(os.path.abspath(d)), s.lower())
        if k not in seen:
            seen.add(k)
            uniq.append((d, s, r))
    return uniq


def find(candidates):
    """The first of candidates [(folder, stem)] that the run may read: (path, looked), looked naming every file
    considered and why it was passed over.  A run reads <stem>.parquet written by a run of this implementation;
    a GDX file, or a Parquet file without that mark, is passed over; then where the earlier run left it
    (elsewhere()).  When the run is compared with TIMES in GAMS
    (from_gams()), it reads what GAMS reads: <stem>.gdx, else the Parquet file; with TIMES_NO_GDX=1, the Parquet file."""
    looked = []
    for d, s in candidates:
        if from_gams():
            for ext in (EXT,) if no_gdx() else (".gdx", EXT):
                p = _exists(d, s + ext)
                if p:
                    return p, looked
                looked.append(f"{os.path.join(d, s + ext)} (not there)")
            continue
        p = _exists(d, s + EXT)
        if p and _ours(p):
            return p, looked
        looked.append(f"{os.path.join(d, s + EXT)} " + ("(not written by this implementation: not read)" if p else "(not there)"))
        g = _exists(d, s + ".gdx")
        if g:
            looked.append(f"{g} (a GDX file: not read)")
    if from_gams():
        return None, looked
    for d, s, run in elsewhere([s for _, s in candidates]):
        p = _exists(d, s + EXT)
        if p is None:
            looked.append(f"{os.path.join(d, s + EXT)} (not there)")
        elif not _ours(p):
            looked.append(f"{p} (not written by this implementation: not read)")
        elif run is not None and (_mark_run(p) or "").lower() != run.lower():
            looked.append(f"{p} (written by run {_mark_run(p)}, not {run}: not read)")
        else:
            return p, looked
    return None, looked


# ------------------------------------------------------------------------------------------------ the GDX library
_lib = None


def gdx_library():
    """(gams.transfer, system directory) when the GDX library loads, else (None, why)."""
    global _lib
    if no_gdx():
        return None, "the setting TIMES_NO_GDX=1"
    if _lib is not None:
        return _lib
    try:
        import gams.transfer as gt
        try:
            import gamspy_base
            d = gamspy_base.directory
        except ImportError:
            d = os.environ.get("GAMS_DIR")
        if d and os.name == "nt" and hasattr(os, "add_dll_directory") and os.path.isdir(d):
            _keep.append(os.add_dll_directory(d))      # the library's dependencies (gamslp.py)
        c = gt.Container(system_directory=d)           # loads the library
        del c
        _lib = (gt, d)
    except Exception as e:                             # not installed, or the DLL does not load
        _lib = (None, f"{type(e).__name__}: {e}")
    return _lib


_keep = []


# ------------------------------------------------------------------------------------------------ reading
def describe(path):
    """{file, format, written_by} of a results file: a run of this implementation (its name, folder and time) or GAMS."""
    out = {"file": os.path.abspath(path), "format": "Parquet" if path.lower().endswith(EXT) else "GDX"}
    w = None
    try:
        if out["format"] == "Parquet":
            import duckdb
            con = duckdb.connect()
            try:
                w = con.execute(f"select d0, d1, d2 from read_parquet('{_q(path)}') where kind = 'written_by' limit 1").fetchone()
            finally:
                con.close()
        else:
            gt, d = gdx_library()
            if gt is not None:
                c = gt.Container(system_directory=d)
                c.read(path, symbols=["PORT_RUN"]) if "PORT_RUN" in _gdx_names(path, gt, d) else None
                if "PORT_RUN" in c.data and c["PORT_RUN"].records is not None and len(c["PORT_RUN"].records):
                    w = tuple(str(x) for x in c["PORT_RUN"].records.iloc[0, :3])
    except Exception:
        w = None
    out["written_by"] = (f"this implementation: run {w[0]} ({w[1]}), {w[2]}" if w else
                         "GAMS" if out["format"] == "GDX" else "unknown (no mark of the run that wrote it)")
    return out


def note_read(db, path, what):
    """Record on db that the results file path was read, for what, and by whom it was written; say so in the log."""
    info = dict(describe(path), read_for=what)
    if info["format"] == "GDX":
        info["warning"] = (f"read the GDX file {os.path.basename(path)}, as TIMES in GAMS does: this run is compared with "
                           "a run of TIMES in GAMS, and both start from the results GAMS reads")
    if not hasattr(db, "earlier_results"):
        db.earlier_results = []
    db.earlier_results.append(info)
    print(f"  {what}: read {info['file']} ({info['format']}, written by {info['written_by']})")
    if info.get("warning"):
        print("  WARNING: " + info["warning"])
    return info


def _gdx_names(path, gt, d):
    c = gt.Container(system_directory=d)
    c.read(path, records=False)
    return set(c.data)


def read(path, symbols=None):
    """{symbol: (kind, rows)} of a results file, rows as tuples (labels..., level, marginal); symbols: only those
    (names in upper case).  A GDX file needs the GDX library: without it, NotPorted with the reason."""
    want = None if symbols is None else {s.upper() for s in symbols}
    if path.lower().endswith(EXT):
        import duckdb
        con = duckdb.connect()
        try:
            out = {}
            for sym, kind, dim in con.execute(f"select distinct symbol, kind, dim from read_parquet('{_q(path)}')").fetchall():
                if kind == "written_by" or want is not None and sym.upper() not in want:
                    continue
                sel = ", ".join([f"d{i}" for i in range(dim)] + ["level", "marginal"])
                rows = con.execute(f"select {sel} from read_parquet('{_q(path)}') where symbol = ?", [sym]).fetchall()
                out[sym.upper()] = (kind, rows)
            return out
        finally:
            con.close()
    gt, d = gdx_library()
    if gt is None:
        from .controls import NotPorted
        raise NotPorted(f"{path} is a GDX file and the GDX library does not load ({d}); the results of a run of this "
                        f"implementation are read without it ({os.path.splitext(os.path.basename(path))[0]}{EXT})")
    c = gt.Container(system_directory=d)
    c.read(path, symbols=None)
    out = {}
    for name, s in c.data.items():
        if want is not None and name.upper() not in want:
            continue
        kind = "variable" if isinstance(s, gt.Variable) else "equation" if isinstance(s, gt.Equation) else \
               "parameter" if isinstance(s, gt.Parameter) else None
        if kind is None or s.records is None or len(s.records) == 0:
            if kind is not None:
                out[name.upper()] = (kind, [])
            continue
        df = s.records
        n = s.dimension
        labels = [df.iloc[:, i].astype(str).tolist() for i in range(n)]
        if kind == "parameter":
            vals, margs = _plain(df["value"].to_numpy(), gt), [None] * len(df)
        else:
            vals, margs = _plain(df["level"].to_numpy(), gt), _plain(df["marginal"].to_numpy(), gt)
        out[name.upper()] = (kind, [tuple(lab[i] for lab in labels) + (vals[i], margs[i]) for i in range(len(df))])
    return out


def _plain(v, gt):
    """EPS -> 0 (a parameter record of value 0 is EPS here), +-INF kept."""
    import numpy as np
    return np.where(gt.SpecialValues.isEps(v), 0.0, v).astype(float).tolist()


def _q(p):
    return p.replace("'", "''")


# ------------------------------------------------------------------------------------------------ writing
def write(stem, symbols, gdx=False, by=None):
    """Write {symbol: (kind, rows)} (rows: labels..., level, marginal; a parameter: labels..., value, None) to
    <stem>.parquet and, with gdx (a tool, not a run: a run writes Parquet only) and when the GDX library loads,
    <stem>.gdx.  by: (run name, folder, time) of the run that writes them.  Returns (files written, note)."""
    import pandas as pd
    import duckdb
    nd = max([len(r) - 2 for _, rows in symbols.values() for r in rows[:1]] + [3])
    recs = {k: [] for k in ["symbol", "kind", "dim"] + [f"d{i}" for i in range(nd)] + ["level", "marginal"]}
    for sym, (kind, rows) in symbols.items():
        dim = len(rows[0]) - 2 if rows else 0
        for r in rows:
            recs["symbol"].append(sym)
            recs["kind"].append(kind)
            recs["dim"].append(dim)
            for i in range(nd):
                recs[f"d{i}"].append(r[i] if i < dim else None)
            recs["level"].append(r[dim])
            recs["marginal"].append(r[dim + 1])
    if by:
        recs["symbol"].append("PORT_RUN")
        recs["kind"].append("written_by")
        recs["dim"].append(3)
        for i in range(nd):
            recs[f"d{i}"].append(str(by[i]) if i < 3 else None)
        recs["level"].append(None)
        recs["marginal"].append(None)
    df = pd.DataFrame(recs)
    df["level"] = df["level"].astype(float)
    df["marginal"] = pd.to_numeric(df["marginal"], errors="coerce").astype(float)
    for i in range(nd):
        df[f"d{i}"] = df[f"d{i}"].astype("string")
    os.makedirs(os.path.dirname(os.path.abspath(stem)), exist_ok=True)
    pq = stem + EXT
    tmp = pq + ".tmp"
    con = duckdb.connect()
    try:
        con.register("df", df)
        con.execute(f"copy (select * from df) to '{_q(tmp)}' (format parquet)")
    finally:
        con.close()
    os.replace(tmp, pq)
    files, note = [pq], None
    if gdx:
        gt, d = gdx_library()
        if gt is None:
            note = f"the GDX library does not load ({d}): {os.path.basename(stem)}.gdx not written"
        else:
            files.append(_write_gdx(stem + ".gdx", symbols, gt, d, by))
    return files, note


def _write_gdx(path, symbols, gt, d, by=None):
    import pandas as pd
    c = gt.Container(system_directory=d)
    if by:
        gt.Set(c, "PORT_RUN", ["*"] * 3, records=pd.DataFrame({f"d{i}": [str(by[i])] for i in range(3)}),
               description="the run of the TIMES port that wrote this file")
    for sym, (kind, rows) in symbols.items():
        dim = len(rows[0]) - 2 if rows else 0
        cols = {f"d{i}": [r[i] for r in rows] for i in range(dim)}
        dom = ["*"] * dim
        if kind == "parameter":
            v = [r[dim] for r in rows]
            cols["value"] = [gt.SpecialValues.EPS if x == 0 else x for x in v]
            gt.Parameter(c, sym, dom, records=pd.DataFrame(cols) if rows else None)
        else:
            cols["level"] = [r[dim] for r in rows]
            cols["marginal"] = [0.0 if r[dim + 1] is None else r[dim + 1] for r in rows]
            df = pd.DataFrame(cols) if rows else None
            if kind == "variable":
                gt.Variable(c, sym, "free", dom, records=df)
            else:
                gt.Equation(c, sym, "eq", dom, records=df)
    tmp = path + ".tmp.gdx"
    c.write(tmp)
    os.replace(tmp, path)
    return path
