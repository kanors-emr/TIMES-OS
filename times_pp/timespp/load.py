# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 1: read the run file, TIMES declarations and DD files into a DB."""
from __future__ import annotations
import os, re, json
from .gamsdata import Reader, EPS, read_source
from .engine import DB

# A run file includes the DD files, these files of TIMES, and the driver of the run: maindrv.mod, or the name given in
# TIMESPP_DRIVER.  A file of the run folder that is not a file of TIMES, included without arguments, is the model's own
# GAMS code: read where it stands, as a DD file is (its declarations, data and the statements ddexec.py applies; the
# rest refused).  $BATINCLUDE of anything else is code that GAMS would run: refused, whether the file exists or not.
INCLUDE = re.compile(r"(?i)\s*\$\s*(?:BAT)?INCLUDE\s+(\S+)(.*)$")
SYS_FILES = ["initsys.mod", "units.def", "maplists.def", "globals.def", "initmty.mod",
             "initmty.vda"]
HERE = os.path.dirname(__file__)
# TIMES's own declaration files (v4.9.8), carried with the port (times_src/README.md): no TIMES source folder is needed
BUNDLED_SRC = os.path.join(HERE, "times_src")


def read_case(run_file: str, src_dir: str = None, workers=None):
    """Return (Reader, dd_order). Follows the include order of the Veda run file.
    The DD files are parsed in `workers` processes (ddpar.py; default: ddpar.workers_wanted), with the same result.
    `src_dir`: the folder of TIMES's declaration files; None or "-" for the copy carried with the port (times_src/)."""
    src_dir = BUNDLED_SRC if src_dir in (None, "", "-") else src_dir
    from . import ddpar
    case_dir = os.path.dirname(os.path.abspath(run_file))
    rd = Reader(include_dirs=[case_dir, src_dir])
    rd.case_dir = case_dir                     # (the results of earlier runs: refpoint.gdxpath)
    src_name = rd.run_src = os.path.basename(run_file)
    dd_order = []
    dd_names = set()
    rd.input_files = []                        # the DD files and the model's code files read, in order
    sysdone = False
    text = read_source(run_file)
    buf = []
    dd_paths = [_find(m.strip("'\""), [case_dir, os.path.dirname(case_dir)])
                for m in re.findall(r"(?im)^\s*\$\s*(?:BAT)?INCLUDE\s+(\S+)", text) if m.strip("'\"").lower().endswith(".dd")]
    nw = workers or ddpar.workers_wanted(dd_paths)
    pool, k = None, 0

    def flush():
        if buf:
            rd.read_text("\n".join(buf), src=src_name)
            buf.clear()

    for raw in text.splitlines():
        m = INCLUDE.match(raw)
        if not m:
            buf.append(raw)
            continue
        flush()
        name = m.group(1).strip("'\"")
        low = name.lower()
        if low.endswith(".dd"):
            p = _find(name, [case_dir, os.path.dirname(case_dir)])
            # $ONEPS / $OFFEPS are local to the included file: after it the setting is that of before (GAMS 54)
            eps0 = rd.oneps
            if nw > 1 and pool is None:
                try:
                    pool = ddpar.Pool(dd_paths, rd, nw)
                except Exception:                     # no processes on this system: read here
                    nw = 1
            if pool is not None and k < len(dd_paths) and dd_paths[k] == p:
                names = pool.read(k)
            else:
                rd.read_file(p)
                names = ddpar.dd_names(read_source(p))
            rd.oneps = eps0
            k += 1
            dd_order.append(os.path.basename(p))
            rd.input_files.append(p)
            # names of the sets and parameters the DD file gives data for (for controls.inputs_known)
            dd_names.update(names)
        elif low in ("initsys.mod", "initmty.mod") and m.group(2).strip():
            # initmty.mod 476: $BATINCLUDE main_ext.mod initmty %EXTEND%: its arguments are extensions
            rd.dd_unsupported.append((src_name, raw.strip(), "arguments that this implementation does not read"))
        elif low == "initsys.mod":
            for f in SYS_FILES[:4]:
                rd.read_file(os.path.join(src_dir, f))
        elif low == "initmty.mod":
            rd.read_file(os.path.join(src_dir, SYS_FILES[4]))
            # initmty.mod 435-437: $IFI %SENSIS%==YES $SETLOCAL STAGES yes ... $IFI %STAGES%==YES $BATINCLUDE initmty.stc
            #   (the declarations of stochastic TIMES; SENSIS and SPINES are refused in controls.py)
            if any(str(rd.env.get(k, "")).strip().strip("'\"").upper() == "YES" for k in ("STAGES", "SENSIS", "SPINES")):
                rd.read_file(os.path.join(src_dir if os.path.isfile(os.path.join(src_dir, "initmty.stc")) else BUNDLED_SRC, "initmty.stc"))
            # initmty.mod 464, 476: $IFI '%MACRO%'==MLF $SETGLOBAL EXTEND '%EXTEND% MLF';  $BATINCLUDE main_ext.mod initmty
            #   %EXTEND%: initmty.mlf (which includes initmty.tm) before initmty.vda.  Its $SETGLOBAL MACRO Yes and
            #   SPOINT '' are shadowed in the run file by a $SET of the same name (readbprice.mod opens the MLF path).
            if str(rd.env.get("MACRO", "")).strip().strip("'\"").upper() == "MLF":
                keep = {k: rd.env[k] for k in ("MACRO", "SPOINT") if k in rd.env}
                for f in ("initmty.tm", "initmty.mlf"):
                    rd.read_file(os.path.join(src_dir if os.path.isfile(os.path.join(src_dir, f)) else BUNDLED_SRC, f))
                rd.env.update(keep)
                if "SPOINT" not in keep and not str(rd.env.get("SPOINT", "")).strip("'\""):
                    rd.env.pop("SPOINT", None)          # empty: no solution point saved or loaded (maindrv.mod 123)
            # initmty.mod 466, 476: $IFI '%CLI%' == YES $SETGLOBAL EXTEND '%EXTEND% CLI'
            #   (the declarations and defaults of the climate module, after those of MLF and before those of VDA)
            if str(rd.env.get("CLI", "")).strip().strip("'\"").upper() == "YES":
                rd.read_file(os.path.join(src_dir if os.path.isfile(os.path.join(src_dir, "initmty.cli")) else BUNDLED_SRC, "initmty.cli"))
            rd.read_file(os.path.join(src_dir, SYS_FILES[5]))
            # initmty.mod 469, 476: $IFI '%ABS%' == YES $SETGLOBAL EXTEND '%EXTEND% ABS';  $BATINCLUDE main_ext.mod initmty %EXTEND%
            #   (the declarations of the ancillary balancing services, after those of VDA: EXTEND lists VDA before ABS)
            if str(rd.env.get("ABS", "")).strip().strip("'\"").upper() == "YES":
                rd.read_file(os.path.join(src_dir if os.path.isfile(os.path.join(src_dir, "initmty.abs")) else BUNDLED_SRC, "initmty.abs"))
        elif low in ("maindrv.mod", os.environ.get("TIMESPP_DRIVER", "").lower()):
            pass                                # the executable code of TIMES, ported in the stage modules
        elif _own_code(name, case_dir, src_dir) and not m.group(2).strip():
            p = _find(name, [case_dir])
            before = set(rd.sym)
            rd.code_srcs.add(os.path.basename(p))
            rd.read_file(p)
            rd.input_files.append(p)
            # the sets and parameters of TIMES (or of the DD files) it gives data for; its own new ones are not input
            dd_names.update(n for n in ddpar.dd_names(read_source(p)) if n in before)
        else:
            there = any(os.path.isfile(os.path.join(d, name)) for d in (case_dir, src_dir))
            rd.dd_unsupported.append((src_name, raw.strip(), "an include this implementation does not read"
                                      + ("" if there else "; the file does not exist, and GAMS would stop")))
    flush()
    if pool is not None:
        pool.close()
    rd.dd_workers = nw if pool is not None else 1
    rd.dd_serial = pool.serial if pool is not None else []
    rd.dd_names = dd_names
    # init_ext.vda 138-152: $IF NOT EXIST %GDXPATH%%GDX_IREBND%.GDX (and GDX_IPRIC): trade bounds or prices loaded from
    # an earlier run's GDX, applied by bnd_ire.vda; GDXPATH is 'gamssave/' when that folder exists (initmty.mod 415-416)
    gp = os.path.join(case_dir, "gamssave") if os.path.isdir(os.path.join(case_dir, "gamssave")) else case_dir
    rd.trade_gdx = [k for k in ("GDX_IREBND", "GDX_IPRIC")
                    if str(rd.env.get(k, "")).strip("'\"") and
                    os.path.isfile(os.path.join(gp, str(rd.env[k]).strip("'\"") + ".gdx"))]
    return rd, dd_order


def _own_code(name, case_dir, src_dir):
    """A file of the run folder that is not one of TIMES's source files."""
    def has(d):
        return os.path.isdir(d) and any(c.lower() == name.lower() for c in os.listdir(d))
    return has(case_dir) and not has(src_dir) and not has(BUNDLED_SRC)


def _find(name, dirs):
    for d in dirs:
        for cand in os.listdir(d):
            if cand.lower() == name.lower():
                return os.path.join(d, cand)
    raise FileNotFoundError(name)


def fallback_domains():
    with open(os.path.join(HERE, "declarations.json")) as f:
        return json.load(f)


def build_db(rd: Reader, path=":memory:") -> DB:
    db = DB(path)
    db.casing = rd.casing
    db.sym_text = {}
    db.elem_text = {}
    db.env = dict(rd.env)
    db.dd_names = set(getattr(rd, "dd_names", ()))
    db.case_dir = getattr(rd, "case_dir", ".")
    db.alias = dict(rd.alias)
    db.dd_applied = list(getattr(rd, "dd_applied", ()))
    db.dd_unsupported = list(getattr(rd, "dd_unsupported", ()))
    db.user_sets = list(getattr(rd, "user_sets", ()))
    db.input_files = list(getattr(rd, "input_files", ()))
    db.trade_gdx = list(getattr(rd, "trade_gdx", ()))
    # the encoding of the DD files, for the report files (times_rpt vd.py): Latin-1 if any file was read that way
    db.dd_encoding = "latin-1" if "latin-1" in getattr(rd, "encodings", ()) else "utf-8"
    fb = fallback_domains()
    # declare every known symbol (parsed declarations first, then fallback list)
    for name, s in rd.sym.items():
        dom = s.domain
        if dom is None:
            if name in fb:
                dom = fb[name]["domain"]
            else:
                n = len(next(iter(s.data))) if s.data else 1
                dom = ["*"] * n
        db.declare(name, s.kind, dom)
    for name, d in fb.items():
        if name not in db.sym:
            db.declare(name, d["kind"], d["domain"])
    # load data
    for name, s in rd.sym.items():
        sy = db.sym[name]
        db.sym_text[name] = s.text or ""
        if sy.kind == "scalar":
            if () in s.data:
                v = s.data[()]
                db.s[name] = 0.0 if v == EPS else v
            continue
        nd = len(sy.cols)
        if sy.kind == "set":
            rows = [k for k in s.data if len(k) == nd]
            db.elem_text[name] = {k: v for k, v in s.data.items()
                                  if len(k) == nd and isinstance(v, str) and v}
        else:
            rows = [k + (0.0 if v == EPS else v,) for k, v in s.data.items() if len(k) == nd]
        db.load_rows(name, rows)
    # universe entry order (needed for ORD on unordered user sets, e.g. timeslices)
    db.x("create table __uel(label VARCHAR, ord INTEGER)")
    import pandas as pd
    u = pd.DataFrame({"label": list(rd.uel.keys()), "ord": list(rd.uel.values())})
    db.con.register("u_", u); db.x("insert into __uel select * from u_"); db.con.unregister("u_")
    return db
