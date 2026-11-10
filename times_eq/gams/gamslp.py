# SPDX-License-Identifier: GPL-3.0-or-later
"""The GDX files of TimesEq.GamsLP.Optimizer (times_eq/src/gamslp.jl): the linear program to a GDX for
solve_lp.gms, and GAMS's solution back to arrays.

  python gamslp.py lp <folder>        the arrays of the folder (below) -> <folder>/lp.gdx (through the GDX library)
  python gamslp.py lp_frames <folder> the same lp.gdx through gams.transfer's data frames (slower; for comparison)
  python gamslp.py solution <folder>  <folder>/solution.gdx -> the arrays of the solution (below)
  python gamslp.py named <folder> <names>   the arrays of the folder by TIMES's names -> <folder>/named.gdx and the
                                      program <folder>/lp_names.gms, which writes the same solution.gdx (below)

The arrays are little-endian binary files, as gamslp.jl writes and reads them:
  lp:       meta.json (rows, columns, entries, sense, constant), rows_lower.f64, rows_upper.f64, cols_lower.f64,
            cols_upper.f64, a_i.i32, a_j.i32, a_value.f64 (rows and columns numbered from 1), c.f64 (one per column)
  solution: x_level.f64, x_marginal.f64 (one per column), row_marginal.f64 (one per row: the marginals of the
            equations eqe, eqg and eql of the row added), result.txt (modelstat, solvestat, objval, iterations,
            seconds, gentime; one "name value" per line)
  named:    the arrays of lp, and named_rows.i32, named_cols.i32: the row and column (from 1; 0: none) in <names>, the
            files of write_matrix (times_eq/src/compare.jl), of each row and column; named.txt says what was written
Rows and columns are the elements "1", "2", ... of the sets i and j. Zeros are not written (GAMS reads an absent
value of a parameter as 0). The GDX is written uncompressed: it is read once and removed.

By names (named), each equation family of the model is an equation of the program, over the labels of its rows, and
each variable family a variable: per equation <E> the set <E>_dom of its rows, its right-hand side <E>_rhs and the
map <E>_i of its rows to the row numbers i; per variable <V> its bounds <V>_lo and <V>_up (absent: 0 and +INF; a
bound of 0 written as EPS) and the map <V>_j to the column numbers j; per equation and variable family with
coefficients, the parameter A_<E>_<V> over the labels of the row and of the column (EPS: an explicit zero of the
model). A row of a family is =E=, =G= or =L= by its bounds (one sense per family, as its name says; a family with
rows of another sense, or a ranged row, gets one more equation for those rows, <E>_g or <E>_l). After the solve the
levels and marginals go back through the maps to x(j) and eqe, eqg, eql(i) in solution.gdx, as solve_lp.gms writes
them."""
import os, sys, json, time


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


def write_lp(folder):
    import numpy as np, pandas as pd
    import gams.transfer as gt
    t0 = time.time()
    meta = json.load(open(os.path.join(folder, "meta.json")))
    rd = lambda n, t: np.fromfile(os.path.join(folder, n), dtype=t)
    nr, nc = meta["rows"], meta["columns"]
    n = max(nr, nc)
    uel = np.arange(1, n + 1).astype(str)
    c = gt.Container(system_directory=system_directory())
    i = gt.Set(c, "i", ["*"], records=pd.DataFrame({"uni": pd.Categorical.from_codes(np.arange(nr), uel)}))
    j = gt.Set(c, "j", ["*"], records=pd.DataFrame({"uni": pd.Categorical.from_codes(np.arange(nc), uel)}))

    def par(name, dom, codes, values):
        k = np.nonzero(values)[0]
        recs = {d.name: pd.Categorical.from_codes(cd[k], uel) for d, cd in zip(dom, codes)}
        recs["value"] = values[k]
        gt.Parameter(c, name, dom, records=pd.DataFrame(recs))

    ri, ci = np.arange(nr), np.arange(nc)
    par("rlo", [i], [ri], rd("rows_lower.f64", "<f8"))
    par("rup", [i], [ri], rd("rows_upper.f64", "<f8"))
    par("xlo", [j], [ci], rd("cols_lower.f64", "<f8"))
    par("xup", [j], [ci], rd("cols_upper.f64", "<f8"))
    par("c", [j], [ci], rd("c.f64", "<f8"))
    par("A", [i, j], [rd("a_i.i32", "<i4") - 1, rd("a_j.i32", "<i4") - 1], rd("a_value.f64", "<f8"))
    gt.Parameter(c, "c0", records=float(meta["constant"]))
    gt.Parameter(c, "sense", records=-1.0 if meta["sense"] == "max" else 1.0)
    c.write(os.path.join(folder, "lp.gdx"), compress=False)
    return {"seconds": round(time.time() - t0, 2)}


def write_lp_raw(folder):
    """The same lp.gdx as write_lp (the same symbols, records and order), written through the GDX library in raw mode
    (as write_named does): no data frames, about half the time on large models."""
    import numpy as np
    from gams.core import gdx
    from gams.core.numpy import Gams2Numpy
    from gams.transfer import SpecialValues
    t0 = time.time()
    meta = json.load(open(os.path.join(folder, "meta.json")))
    rd = lambda n, t: np.fromfile(os.path.join(folder, n), dtype=t)
    nr, nc = meta["rows"], meta["columns"]
    sysdir = system_directory()
    g2np = Gams2Numpy(sysdir)
    h = gdx.new_gdxHandle_tp()
    rc, msg = gdx.gdxCreateD(h, sysdir, gdx.GMS_SSSIZE)
    if not rc:
        raise RuntimeError(msg)
    if not gdx.gdxOpenWriteEx(h, os.path.join(folder, "lp.gdx"), "TIMES gamslp.py lp", 0)[0]:
        raise RuntimeError(f"cannot write {os.path.join(folder, 'lp.gdx')}")
    sv = gdx.doubleArray(gdx.GMS_SVIDX_MAX)              # the special values as gams.transfer sets them
    sv[gdx.GMS_SVIDX_UNDEF], sv[gdx.GMS_SVIDX_NA], sv[gdx.GMS_SVIDX_EPS] = SpecialValues.UNDEF, SpecialValues.NA, SpecialValues.EPS
    sv[gdx.GMS_SVIDX_PINF], sv[gdx.GMS_SVIDX_MINF] = SpecialValues.POSINF, SpecialValues.NEGINF
    gdx.gdxSetSpecialValues(h, sv)
    g2np.gdxRegisterUels(h, [str(n) for n in range(1, max(nr, nc) + 1)])    # UEL n: the element "n"

    def sym(name, dom, keys, vals=None):                 # keys: UEL numbers, sorted; vals None: a set
        keys = np.ascontiguousarray(keys, dtype=np.int32)
        v = np.full((len(keys), 1), "", dtype=object) if vals is None else np.asarray(vals, dtype=float).reshape(-1, 1)
        g2np.gdxWriteSymbolRaw(h, name, "", keys.shape[1], gdx.GMS_DT_SET if vals is None else gdx.GMS_DT_PAR, 0,
                               keys, v, dom)
        if gdx.gdxDataErrorCount(h):
            raise RuntimeError(f"GDX data errors in symbol {name}")

    def par(name, dom, n, values):                       # one value per row (column) n, zeros left out
        k = np.nonzero(values)[0]
        sym(name, dom, (k + 1).reshape(-1, 1), values[k])

    sym("i", ["*"], np.arange(1, nr + 1).reshape(-1, 1))
    sym("j", ["*"], np.arange(1, nc + 1).reshape(-1, 1))
    par("rlo", ["i"], nr, rd("rows_lower.f64", "<f8"))
    par("rup", ["i"], nr, rd("rows_upper.f64", "<f8"))
    par("xlo", ["j"], nc, rd("cols_lower.f64", "<f8"))
    par("xup", ["j"], nc, rd("cols_upper.f64", "<f8"))
    par("c", ["j"], nc, rd("c.f64", "<f8"))
    ai, aj, av = rd("a_i.i32", "<i4"), rd("a_j.i32", "<i4"), rd("a_value.f64", "<f8")
    k = np.nonzero(av)[0]
    o = k[np.lexsort((aj[k], ai[k]))]
    sym("A", ["i", "j"], np.stack([ai[o], aj[o]], axis=1), av[o])
    sym("c0", [], np.zeros((1, 0), dtype=np.int32), [float(meta["constant"])])
    sym("sense", [], np.zeros((1, 0), dtype=np.int32), [-1.0 if meta["sense"] == "max" else 1.0])
    gdx.gdxAutoConvert(h, 0)
    gdx.gdxClose(h)
    gdx.gdxFree(h)
    return {"seconds": round(time.time() - t0, 2)}


def write_named(folder, names):
    import numpy as np
    from gams.core import gdx
    from gams.core.numpy import Gams2Numpy
    from gams.transfer import SpecialValues
    t0 = time.time()
    meta = json.load(open(os.path.join(folder, "meta.json")))
    wm = json.load(open(os.path.join(names, "meta.json")))
    rd = lambda n, t, d=folder: np.fromfile(os.path.join(d, n), dtype=t)
    lines = lambda n: open(os.path.join(names, n), encoding="utf-8").read().split("\n")[:-1]
    nr, nc = meta["rows"], meta["columns"]
    rlo, rup = rd("rows_lower.f64", "<f8"), rd("rows_upper.f64", "<f8")
    xlo, xup, cost = rd("cols_lower.f64", "<f8"), rd("cols_upper.f64", "<f8"), rd("c.f64", "<f8")
    ai, aj, av = rd("a_i.i32", "<i4") - 1, rd("a_j.i32", "<i4") - 1, rd("a_value.f64", "<f8")
    rpos, cpos = rd("named_rows.i32", "<i4") - 1, rd("named_cols.i32", "<i4") - 1     # -1: no name
    fam, labels = lines("names.txt"), lines("labels.txt")

    def keys(kind, dims, pos):                           # the name and the labels (0 past its arity) of rows or columns
        k = np.zeros((len(pos), dims), dtype=np.int32)
        for n in range(dims):
            k[:, n] = rd(f"{kind}_k{n + 1}.i32", "<i4", names)[pos]
        return rd(f"{kind}_name.i32", "<i4", names)[pos], k

    if (rpos < 0).any():
        raise SystemExit(f"{int((rpos < 0).sum())} rows have no name in {names}")
    used = np.zeros(nc, dtype=bool)
    used[aj] = True
    used |= cost != 0
    if (used & (cpos < 0)).any():
        raise SystemExit(f"{int((used & (cpos < 0)).sum())} columns with coefficients have no name in {names}")
    rname, rkey = keys("rows", wm["row_dims"], rpos)
    cn = cpos >= 0                                       # the columns with a name (the others are in no row)
    cname, ckey = np.full(nc, -1, dtype=np.int32), np.zeros((nc, wm["col_dims"]), dtype=np.int32)
    cname[cn], ckey[cn] = keys("cols", wm["col_dims"], cpos[cn])
    # the explicit zeros of the model (in write_matrix, not in the LP): EPS, where the row has no other term of the column
    wi, wj, wv = rd("a_i.i32", "<i4", names), rd("a_j.i32", "<i4", names), rd("a_value.f64", "<f8", names)
    z = wv == 0
    if z.any():
        lp_row = np.zeros(int(wm["rows"]), dtype=np.int64)
        lp_row[rpos] = np.arange(nr)
        cj = rd("cols_j.i32", "<i4", names)
        lp_col = np.full(int(cj.max()) + 1, -1, dtype=np.int64)
        lp_col[cj[cpos[cn]]] = np.nonzero(cn)[0]
        zk = np.unique(lp_row[wi[z] - 1] * nc + lp_col[wj[z]])
        zk = zk[~np.isin(zk, ai.astype(np.int64) * nc + aj)]
        ai = np.concatenate([ai, (zk // nc).astype(np.int32)])
        aj = np.concatenate([aj, (zk % nc).astype(np.int32)])
        av = np.concatenate([av, np.full(len(zk), SpecialValues.EPS)])
    del wi, wj, wv, z

    def arity(name, key):                                # per family: the number of labels of its rows (columns)
        n = (key != 0).sum(axis=1)
        out = {}
        for f in np.unique(name[name >= 0]):
            k = n[name == f]
            if k.min() != k.max():
                raise SystemExit(f"{fam[f]}: rows or columns of {k.min()} and of {k.max()} labels")
            out[int(f)] = int(k[0])
        return out

    rar, car = arity(rname, rkey), arity(cname, ckey)
    # each row's sense: =E= (lo = up), =G= (lo finite), =L= (up finite); a ranged row both =G= and =L=; a free row none
    eq = rlo == rup
    ge, le = ~eq & (rlo > -np.inf), ~eq & (rup < np.inf)
    groups = []                                          # (equation, family, sense, rows)
    for f in sorted(rar, key=lambda f: fam[f]):
        mine = rname == f
        here = [(s, np.nonzero(mine & m)[0]) for s, m in (("E", eq), ("G", ge), ("L", le))]
        here = [(s, r) for s, r in here if len(r)]
        main = fam[f][2] if fam[f][:2] == "EQ" and fam[f][3:4] == "_" else None
        if main not in [s for s, _ in here]:
            main = max(here, key=lambda h: len(h[1]))[0] if here else None
        groups += [(fam[f] if s == main else f"{fam[f]}_{s.lower()}", f, s, r) for s, r in here]
    live = np.zeros(nr, dtype=bool)
    for g in groups:
        live[g[3]] = True
    k = live[ai]
    ai, aj, av = ai[k], aj[k], av[k]

    # the GDX, written as jacobian_gdx.py writes its own: the UELs registered once (UEL n: label n, then the row and
    # column numbers that are not labels), each symbol in raw mode (records sorted by those numbers)
    uel_of = {l: n + 1 for n, l in enumerate(labels)}
    num = [str(n) for n in range(1, max(nr, nc) + 1)]
    extra = [s for s in num if s not in uel_of]
    uel_of.update((s, len(labels) + n + 1) for n, s in enumerate(extra))
    nuel = np.array([uel_of[s] for s in num], dtype=np.int32)      # the UEL of row (column) number n + 1
    sysdir = system_directory()
    g2np = Gams2Numpy(sysdir)
    h = gdx.new_gdxHandle_tp()
    rc, msg = gdx.gdxCreateD(h, sysdir, gdx.GMS_SSSIZE)
    if not rc:
        raise RuntimeError(msg)
    if not gdx.gdxOpenWriteEx(h, os.path.join(folder, "named.gdx"), "TIMES gamslp.py named", 0)[0]:
        raise RuntimeError(f"cannot write {os.path.join(folder, 'named.gdx')}")
    sv = gdx.doubleArray(gdx.GMS_SVIDX_MAX)              # the special values as gams.transfer sets them (EPS: -0.0)
    sv[gdx.GMS_SVIDX_UNDEF], sv[gdx.GMS_SVIDX_NA], sv[gdx.GMS_SVIDX_EPS] = SpecialValues.UNDEF, SpecialValues.NA, SpecialValues.EPS
    sv[gdx.GMS_SVIDX_PINF], sv[gdx.GMS_SVIDX_MINF] = SpecialValues.POSINF, SpecialValues.NEGINF
    gdx.gdxSetSpecialValues(h, sv)
    g2np.gdxRegisterUels(h, labels + extra)
    count = {"symbols": 0, "records": 0}

    def sym(name, text, keys, vals=None, dom=None):     # a set (vals None) or a parameter
        if keys.shape[1] and len(keys) > 1:
            o = np.lexsort(keys.T[::-1])
            keys, vals = keys[o], None if vals is None else vals[o]
        v = np.full((len(keys), 1), "", dtype=object) if vals is None else np.asarray(vals, dtype=float).reshape(-1, 1)
        g2np.gdxWriteSymbolRaw(h, name, text, keys.shape[1], gdx.GMS_DT_SET if vals is None else gdx.GMS_DT_PAR, 0,
                               keys, v, dom or ["*"] * keys.shape[1])
        if gdx.gdxDataErrorCount(h):
            raise RuntimeError(f"GDX data errors in symbol {name}")
        count["symbols"] += 1
        count["records"] += len(keys)

    numbered = lambda key, n: np.concatenate([nuel[n].reshape(-1, 1), key], axis=1)   # row (column) number and labels
    # (loaded first, so that GAMS orders the labels, and so the rows and columns of its listing, as the model does)
    sym("labels", "the labels of the model, in its order", np.arange(1, len(labels) + 1, dtype=np.int32).reshape(-1, 1))
    sym("i", "rows", nuel[:nr].reshape(-1, 1))
    sym("j", "columns", nuel[:nc].reshape(-1, 1))
    ra, ca = max(list(rar.values()) + [0]), max(list(car.values()) + [0])
    R, C = [f"r{n}" for n in range(1, ra + 1)], [f"c{n}" for n in range(1, ca + 1)]
    ix = lambda d: f"({','.join(d)})" if d else ""
    star = lambda n: ix(["*"] * n)
    over = lambda d, a: f"sum({ix(d) if len(d) > 1 else d[0]}$({a}), {a}*" if d else f"({a}*"   # a sum, closed by the caller
    sets, pars, vars_, load, bounds, defs = [], [], [], [], [], []
    # after the solve, per family a term of the sum that gives each row (column) its marginal (level): by the maps,
    # whose first index is the number (a loop over the maps instead takes time with the square of their size)
    back = {"x": [], "e": [], "g": [], "l": []}
    term = lambda m, k, d, sym: (f"sum({ix(d) if len(d) > 1 else d[0]}$({m}({k},{','.join(d)})), {sym}{ix(d)})" if d
                                 else f"{sym}$({m}({k}))")
    # the variables
    for f in sorted(car, key=lambda f: fam[f]):
        V, n = fam[f], car[f]
        cols = np.nonzero(cname == f)[0]
        key = ckey[cols, :n]
        sym(f"{V}_j", f"the column number of each column of {V}", numbered(key, cols), dom=["j"] + ["*"] * n)
        k = xlo[cols] != 0
        sym(f"{V}_lo", f"the lower bounds of {V} (absent: 0)", key[k], xlo[cols][k])
        k = xup[cols] < np.inf
        sym(f"{V}_up", f"the upper bounds of {V} (absent: +INF)", key[k], np.where(xup[cols][k] == 0, SpecialValues.EPS, xup[cols][k]))
        sets.append(f"{V}_j{ix(['j'] + ['*'] * n)}")
        pars.append(f"{V}_lo{star(n)}, {V}_up{star(n)}")
        vars_.append(f"{V}{star(n)}")
        load.append(f"$load {V}_j {V}_lo {V}_up")
        c = ix(C[:n])
        bounds.append(f"{V}.lo{c}$({V}_lo{c}) = {V}_lo{c};  {V}.up{c}$({V}_up{c}) = {V}_up{c};")
        back["x"].append((f"{V}_j", C[:n], V))
    # the coefficients, per equation family and variable family
    pairs = {}
    if len(ai):
        nv = len(fam)
        pk = rname[ai].astype(np.int64) * nv + cname[aj]
        o = np.argsort(pk, kind="stable")
        pk, ai, aj, av = pk[o], ai[o], aj[o], av[o]
        cut = np.flatnonzero(np.diff(pk)) + 1
        for a, b in zip(np.r_[0, cut], np.r_[cut, len(pk)]):
            f, v = divmod(int(pk[a]), nv)
            E, V, d = fam[f], fam[v], rar[f] + car[v]
            if d > 20:
                raise SystemExit(f"{E} x {V}: {d} indexes, more than GAMS's 20")
            name = f"A_{E}_{V}" if len(E) + len(V) + 3 <= 63 else f"A{sum(len(p) for p in pairs.values()) + 1}"
            sym(name, f"{E} x {V}", np.concatenate([rkey[ai[a:b], :rar[f]], ckey[aj[a:b], :car[v]]], axis=1), av[a:b])
            pairs.setdefault(f, []).append((name, v))
            pars.append(f"{name}{star(d)} '{E} x {V}'")
            load.append(f"$load {name}")
    widest = max(((rar[f] + car[v], f"{fam[f]}x{fam[v]}") for f, ps in pairs.items() for _, v in ps), default=(0, "-"))
    # the equations
    for E, f, s, rows in groups:
        n = rar[f]
        key = rkey[rows, :n]
        rhs = (rup if s == "L" else rlo)[rows]
        k = rhs != 0
        n and sym(f"{E}_dom", f"the rows of {E}", key)
        sym(f"{E}_rhs", f"the right-hand side of {E}", key[k], rhs[k])
        sym(f"{E}_i", f"the row number of each row of {E}", numbered(key, rows), dom=["i"] + ["*"] * n)
        sets.append(f"{E}_i{ix(['i'] + ['*'] * n)}" + (f", {E}_dom{star(n)}" if n else ""))
        pars.append(f"{E}_rhs{star(n)}")
        load.append(f"$load {E}_i {E}_rhs" + (f" {E}_dom" if n else ""))
        r = ix(R[:n])
        terms = [over(C[:car[v]], f"{a}{ix(R[:n] + C[:car[v]])}") + f"{fam[v]}{ix(C[:car[v]])})" +
                 ("" if car[v] else f"$({a}{ix(R[:n])})") for a, v in pairs.get(f, [])]
        defs.append((E, f"{E}{r}{f'$({E}_dom{r})' if n else ''}..\n    " + ("\n  + ".join(terms) or "0") + f"\n  ={s}= {E}_rhs{r};"))
        back[s.lower()].append((f"{E}_i", R[:n], E))
    # the objective: one free variable without labels, minimised (TIMES's OBJZ), as it is; any other through an equation
    cc = np.nonzero(cost)[0]
    # (GAMS minimises a free variable only: a column with bounds is not one)
    if (len(cc) == 1 and cost[cc[0]] == 1 and meta["constant"] == 0 and car[int(cname[cc[0]])] == 0
            and xlo[cc[0]] == -np.inf and xup[cc[0]] == np.inf):
        obj = fam[int(cname[cc[0]])]
    else:
        obj, terms = "lp_objective", []
        for f in sorted({int(cname[j]) for j in cc}, key=lambda f: fam[f]):
            V, n = fam[f], car[f]
            cols = cc[cname[cc] == f]
            sym(f"{V}_c", f"the objective coefficients of {V}", ckey[cols, :n], cost[cols])
            pars.append(f"{V}_c{star(n)}")
            load.append(f"$load {V}_c")
            terms.append(over(C[:n], f"{V}_c{ix(C[:n])}") + f"{V}{ix(C[:n])})")
        defs.append(("lp_objective_def", "lp_objective_def.. lp_objective =e= " + " + ".join(terms + [f"({float(meta['constant'])!r})"]) + ";"))
    gdx.gdxAutoConvert(h, 0)
    gdx.gdxClose(h)
    gdx.gdxFree(h)
    t_gdx = time.time() - t0
    out = ["* SPDX-License-Identifier: GPL-3.0-or-later",
           "* The model by TIMES's names, its data in a GDX (named.gdx), solved with the LP solver of this GAMS run (LP=...);",
           "* the solution by row and column number to a GDX, as solve_lp.gms writes it. Written by gamslp.py (named).",
           "*   gams lp_names.gms --IN=named.gdx --OUT=solution.gdx lp=<solver> [optfile=1] [threads=<n>] [reslim=<seconds>]",
           "* More of the equation and column listing: limrow=<rows per equation> limcol=<columns per variable>.",
           "$onEmpty"]
    out += [f"Alias (*, {', '.join(R + C)});"] if R or C else []
    out += ["Set labels 'the labels of the model, in its order', i 'rows', j 'columns';"] + [f"Set {s};" for s in sets] + [f"Parameter {s};" for s in pars]
    out += ["Scalar modelstat, solvestat, objval, iterations, seconds, gentime;"]
    out += [f"{'Variable' if s == obj else 'Positive Variable'} {s};" for s in vars_]
    out += ["Variable x(j) 'the columns by number'" + (", lp_objective;" if obj == "lp_objective" else ";")]
    out += [f"Equation {E}{star(rar[f])};" for E, f, _, _ in groups]
    out += ["Equation lp_objective_def;"] if obj == "lp_objective" else []
    out += ["Equation eqe(i), eqg(i), eql(i) 'the marginals of the rows by number';"]
    out += ["$gdxIn %IN%", "$load labels i j"] + load + ["$gdxIn", ""] + bounds + [""] + [d for _, d in defs] + [""]
    out += ["Model TIMES /\n  " + ",\n  ".join(E for E, _ in defs) + " /;", "TIMES.solprint = 0; TIMES.holdfixed = 0;",
            f"solve TIMES using lp {'maximizing' if meta['sense'] == 'max' else 'minimizing'} {obj};", "",
            f"modelstat = TIMES.modelstat; solvestat = TIMES.solvestat; objval = {obj}.l;",
            "iterations = TIMES.iterusd; seconds = TIMES.resusd; gentime = TIMES.resgen;",
            "* the levels and marginals by row and column number"]
    for what, k, ts in (("x.l", "j", back["x"]), ("x.m", "j", back["x"]), ("eqe.m", "i", back["e"]),
                        ("eqg.m", "i", back["g"]), ("eql.m", "i", back["l"])):
        ts and out.append(f"{what}({k}) =\n    " + "\n  + ".join(term(m, k, d, f"{v}.{what[-1]}") for m, d, v in ts) + ";")
    out += ["execute_unload '%OUT%', x, eqe, eqg, eql, modelstat, solvestat, objval, iterations, seconds, gentime;"]
    with open(os.path.join(folder, "lp_names.gms"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    res = {"equations": len(groups), "variables": len(car), "pairs": sum(len(p) for p in pairs.values()),
           "widest_pair": widest[0], "widest_pair_names": widest[1], "records": count["records"],
           "gdx_seconds": round(t_gdx, 2), "seconds": round(time.time() - t0, 2)}
    with open(os.path.join(folder, "named.txt"), "w") as fh:
        fh.writelines(f"{k} {v}\n" for k, v in res.items())
    return res


def read_solution(folder):
    import numpy as np
    import gams.transfer as gt
    t0 = time.time()
    meta = json.load(open(os.path.join(folder, "meta.json")))
    nr, nc = meta["rows"], meta["columns"]
    c = gt.Container(os.path.join(folder, "solution.gdx"), system_directory=system_directory())

    def dense(sym, n, field):
        out = np.zeros(n)
        r = c[sym].records
        if r is not None and len(r):
            k = r.iloc[:, 0]
            pos = k.cat.categories.astype(np.int64).to_numpy()[k.cat.codes.to_numpy()] - 1
            out[pos] = r[field].to_numpy()
        return out

    dense("x", nc, "level").astype("<f8").tofile(os.path.join(folder, "x_level.f64"))
    dense("x", nc, "marginal").astype("<f8").tofile(os.path.join(folder, "x_marginal.f64"))
    m = dense("eqe", nr, "marginal") + dense("eqg", nr, "marginal") + dense("eql", nr, "marginal")
    m.astype("<f8").tofile(os.path.join(folder, "row_marginal.f64"))
    res = {k: float(c[k].records.iloc[0, 0]) if c[k].records is not None and len(c[k].records) else 0.0
           for k in ("modelstat", "solvestat", "objval", "iterations", "seconds", "gentime")}
    res["read_seconds"] = round(time.time() - t0, 2)
    with open(os.path.join(folder, "result.txt"), "w") as f:
        f.writelines(f"{k} {v!r}\n" for k, v in res.items())
    return res


if __name__ == "__main__":
    if not (len(sys.argv) == 3 and sys.argv[1] in ("lp", "lp_frames", "solution") or len(sys.argv) == 4 and sys.argv[1] == "named"):
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "named":
        print(json.dumps(write_named(sys.argv[2], sys.argv[3])))
    else:
        print(json.dumps(write_lp_raw(sys.argv[2]) if sys.argv[1] == "lp" else write_lp(sys.argv[2]) if sys.argv[1] == "lp_frames"
                         else read_solution(sys.argv[2])))
