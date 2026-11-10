# SPDX-License-Identifier: GPL-3.0-or-later
"""The model's matrix as a GDX in the layout of the jacobian GDX that GAMS's CONVERT solver writes (`jacobian
<file>.gdx`), so that the two can be compared (compare_jacobian.py: by the names of the rows and columns).

  python jacobian_gdx.py <write_matrix folder> <out.gdx> [--uncompressed]

Input: what times_eq's write_matrix wrote (run_case.jl --matrix-out; TIMES.py run --jacobian <file> does both).
Output, as CONVERT writes it:
  i        set of the rows e1, e2, ... (element text: the row's name, NAME('label',...))
  j        set of the columns x1, x2, ... (element text: the column's name)
  e(i)     equations (type =E= throughout, as CONVERT writes them): lower and upper are the right-hand side bounds,
           with all variable terms on the left (lower = upper: an equality; -INF or +INF on one side: an inequality)
  x(j)     variables (free): lower and upper are the column bounds
  A(i,j)   the coefficients; EPS where a coefficient is an explicit zero
  iobj, jobj, objcoef, objconst, objjacval   the objective row and column, as CONVERT writes them
and, not in CONVERT's file: cancel(i), the size of the constants that cancelled in a row's right-hand side (its value
is then a rounding remainder; compare_jacobian.py allows for that rounding). Labels in quotes, but numbers. The rows
and columns are numbered in this model's order, not GAMS's (GAMS numbers them in the order its run first met the
labels): compare by name, not by number."""
import os, sys, json, time

KEYSEP = "\x1f"


_DLL_DIRS = []


def _dll_folder(d):
    """The GDX library's folder, also added to the DLL search path on Windows. gams.transfer only puts the folder on
    PATH, and some Pythons (the Microsoft Store's, for one) do not look in PATH for the libraries a DLL needs: there
    gmdcclib64.dll does not load (WinError 126) unless its folder is added this way."""
    if d and os.name == "nt" and hasattr(os, "add_dll_directory") and os.path.isdir(d):
        _DLL_DIRS.append(os.add_dll_directory(d))
    return d


def system_directory():
    try:
        import gamspy_base
        return _dll_folder(gamspy_base.directory)
    except ImportError:
        return _dll_folder(os.environ.get("GAMS_DIR"))


def write(src, out, compress=True):
    import numpy as np, pandas as pd, duckdb
    t0 = time.time()
    meta = json.load(open(os.path.join(src, "meta.json")))
    rd = lambda n, t: np.fromfile(os.path.join(src, n), dtype=t)
    names = open(os.path.join(src, "names.txt"), encoding="utf-8").read().split("\n")[:-1]
    labels = open(os.path.join(src, "labels.txt"), encoding="utf-8").read().split("\n")[:-1]
    con = duckdb.connect()
    # a label as the element text shows it: a number as it is, any other in quotes ('...', or "..." if it has a ')
    con.register("labels_", pd.DataFrame({"id": np.arange(1, len(labels) + 1, dtype=np.int32), "l": labels}))
    con.execute("create table lab as select id, case when regexp_full_match(l, '-?[0-9]+') then l "
                "when contains(l, '''') then '\"' || l || '\"' else '''' || l || '''' end as l from labels_")
    con.register("names_", pd.DataFrame({"id": np.arange(len(names), dtype=np.int32), "name": names}))

    def texts(kind, dims, n):
        d = {"pos": np.arange(1, n + 1, dtype=np.int64), "name_id": rd(f"{kind}_name.i32", "<i4")}
        for k in range(1, dims + 1):
            d[f"k{k}"] = rd(f"{kind}_k{k}.i32", "<i4")
        con.register("t_", pd.DataFrame(d, copy=False))
        joins = " ".join(f"left join lab l{k} on l{k}.id = t_.k{k}" for k in range(1, dims + 1))
        inner = f"concat_ws(',', {', '.join(f'l{k}.l' for k in range(1, dims + 1))})" if dims else "''"
        r = con.execute(f"select n_.name || case when {inner} = '' then '' else '(' || {inner} || ')' end from t_ "
                        f"join names_ n_ on n_.id = t_.name_id {joins} order by t_.pos").fetchnumpy()
        con.unregister("t_")
        return next(iter(r.values()))

    nr, nc = meta["rows"], meta["columns"]
    rtext, ctext = texts("rows", meta["row_dims"], nr), texts("cols", meta["col_dims"], nc)
    con.close()
    t_text = time.time() - t0
    # the symbols straight from numpy arrays through the GDX library (no pandas frames): the labels e1..eN, x1..xM are
    # registered once, as UELs 1..N and N+1..N+M, and each symbol is written in raw mode (records sorted by those numbers)
    from gams.core import gdx
    from gams.core.numpy import Gams2Numpy
    from gams.transfer import SpecialValues
    sysdir = system_directory()
    g2np = Gams2Numpy(sysdir)
    h = gdx.new_gdxHandle_tp()
    rc, msg = gdx.gdxCreateD(h, sysdir, gdx.GMS_SSSIZE)
    if not rc:
        raise RuntimeError(msg)
    if not gdx.gdxOpenWriteEx(h, out, "TIMES jacobian_gdx.py", 1 if compress else 0)[0]:
        raise RuntimeError(f"cannot write {out}")
    sv = gdx.doubleArray(gdx.GMS_SVIDX_MAX)              # the special values as gams.transfer sets them (EPS: -0.0)
    sv[gdx.GMS_SVIDX_UNDEF], sv[gdx.GMS_SVIDX_NA], sv[gdx.GMS_SVIDX_EPS] = SpecialValues.UNDEF, SpecialValues.NA, SpecialValues.EPS
    sv[gdx.GMS_SVIDX_PINF], sv[gdx.GMS_SVIDX_MINF] = SpecialValues.POSINF, SpecialValues.NEGINF
    gdx.gdxSetSpecialValues(h, sv)
    g2np.gdxRegisterUels(h, [f"e{k}" for k in range(1, nr + 1)] + [f"x{k}" for k in range(1, nc + 1)])
    ie = np.arange(1, nr + 1, dtype=np.int32)            # the UEL of row k (from 0): k + 1; of column k: nr + k + 1
    jx = np.arange(nr + 1, nr + nc + 1, dtype=np.int32)

    def sym(name, text, typ, sub, keys, vals, domains):
        g2np.gdxWriteSymbolRaw(h, name, text, keys.shape[1], typ, sub, keys, vals, domains)
        if gdx.gdxDataErrorCount(h):
            raise RuntimeError(f"GDX data errors in symbol {name}")

    col = lambda a: a.reshape(-1, 1)
    sym("i", "Equation names", gdx.GMS_DT_SET, 0, col(ie), col(rtext.astype(object)), ["*"])
    sym("j", "Variable names", gdx.GMS_DT_SET, 0, col(jx), col(ctext.astype(object)), ["*"])
    rv = np.zeros((nr, gdx.GMS_VAL_MAX)); rv[:, gdx.GMS_VAL_LOWER] = rd("rows_lower.f64", "<f8"); rv[:, gdx.GMS_VAL_UPPER] = rd("rows_upper.f64", "<f8"); rv[:, gdx.GMS_VAL_SCALE] = 1.0
    sym("e", "equations", gdx.GMS_DT_EQU, gdx.GMS_EQU_USERINFO_BASE + gdx.GMS_EQUTYPE_E, col(ie), rv, ["i"])
    del rv
    cv = np.zeros((nc, gdx.GMS_VAL_MAX)); cv[:, gdx.GMS_VAL_LOWER] = rd("cols_lower.f64", "<f8"); cv[:, gdx.GMS_VAL_UPPER] = rd("cols_upper.f64", "<f8"); cv[:, gdx.GMS_VAL_SCALE] = 1.0
    sym("x", "variables", gdx.GMS_DT_VAR, gdx.GMS_VARTYPE_FREE, col(jx), cv, ["j"])
    del cv
    # the coefficients: the row's position, the column's position in cols (from JuMP's index); EPS for a zero
    cj = rd("cols_j.i32", "<i4")
    pos = np.zeros(int(cj.max()) + 1 if nc else 1, dtype=np.int32)
    pos[cj] = np.arange(nc, dtype=np.int32)
    ai = rd("a_i.i32", "<i4")
    ne = len(ai)
    keys = np.empty((ne, 2), dtype=np.int32)
    keys[:, 0] = ai                                     # (rows from 1: the UEL of row ai - 1)
    keys[:, 1] = pos[rd("a_j.i32", "<i4")]
    del pos
    av = rd("a_value.f64", "<f8")
    av[av == 0] = SpecialValues.EPS
    # the objective's coefficient (CONVERT's objjacval), before A is sorted
    ro = np.nonzero(rtext == "EQ_OBJ")[0]
    co = np.nonzero(ctext == "OBJZ")[0]
    jac = None
    if len(ro) == 1 and len(co) == 1:
        sel = (keys[:, 0] - 1 == ro[0]) & (keys[:, 1] == co[0])
        jac = float(av[sel][0]) if sel.any() else 0.0
    keys[:, 1] += nr + 1
    # raw mode wants the records in the order of their UELs: rows are in order already; sort the columns within each row
    order = None
    if ne and np.any((np.diff(keys[:, 0]) == 0) & (np.diff(keys[:, 1]) < 0)):
        order = np.lexsort((keys[:, 1], keys[:, 0]))
        keys, av = keys[order], av[order]
        del order
    sym("A", "jacobian", gdx.GMS_DT_PAR, 0, keys, col(av), ["i", "j"])
    del keys, av, ai
    cancel = rd("rows_cancel.f64", "<f8")
    k = np.nonzero(cancel > 0)[0]
    sym("cancel", "size of the constants that cancelled in the right-hand side (not CONVERT's)", gdx.GMS_DT_PAR, 0,
        col(ie[k]), col(cancel[k]), ["i"])
    # the objective, as CONVERT writes it: the row EQ_OBJ and the column OBJZ (minimised), objjacval its coefficient
    if jac is not None:
        scalar = lambda v: (np.zeros((1, 0), dtype=np.int32), np.array([[v]]))
        sym("iobj", "objective row (if reformulation possible, empty otherwise)", gdx.GMS_DT_SET, 0, col(ie[ro]), np.full((1, 1), "", dtype=object), ["i"])
        sym("jobj", "objective variable", gdx.GMS_DT_SET, 0, col(jx[co]), np.full((1, 1), "", dtype=object), ["j"])
        sym("objcoef", "objective coefficient", gdx.GMS_DT_PAR, 0, *scalar(1.0), [])
        sym("objconst", "objective constant", gdx.GMS_DT_PAR, 0, *scalar(0.0), [])
        sym("objjacval", "objective jacobian value", gdx.GMS_DT_PAR, 0, *scalar(jac), [])
    t_build = time.time() - t0 - t_text
    gdx.gdxAutoConvert(h, 0)                     # (as gams.transfer: the file stays as written, compressed as GAMS writes it)
    gdx.gdxClose(h)
    gdx.gdxFree(h)
    return {"rows": nr, "columns": nc, "entries": int(ne), "seconds": round(time.time() - t0, 1),
            "texts_seconds": round(t_text, 1), "write_seconds": round(t_build, 1), "compressed": compress}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(write(sys.argv[1], sys.argv[2], compress="--uncompressed" not in sys.argv[3:])))
