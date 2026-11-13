# SPDX-License-Identifier: GPL-3.0-or-later
"""The loaded solution point under the solution of a run with FIXBOH.

    python loadedpoint.py <solution.db3> <the file of the loaded point> <model.db3 or model_parquet>

A run with FIXBOH loads the levels and marginals of an earlier run before its solve (spoint.mod 43-47,
execute_loadpoint), fixes the periods up to FIXBOH at them and solves the rest (solve.stp).  The solve replaces the
levels and marginals of the variables and equations of the model; every other record keeps what was loaded: the
equations of the fixed periods, which are not generated, and the variables that are in none of the generated
equations.  The reports and the solution point written after the solve (rptmain.mod, spoint.mod 14-18) read both,
so the fixed periods are reported from the loaded point.

under() does the same for a solution of this implementation: the records of the loaded point that the solution does
not have are added to solution.db3 (level and marginal; no bounds).  The solution holds every column and row of the
model, so a record it does not have is one the model does not have.  Labels are compared without case.

What TIMES clears of the loaded point is cleared in the records added (RT_PP: the periods of a region after its
REG_FIXT, the window; NO_RT: its fixed periods):

    clearsol.stp 9-25 (before the solve)   the levels in the window:
        %VAR%_ACT.L(RVT,P,S) = 0;  _FLO, _IRE, _SIN, _SOUT, _SCAP, _BSPRS alike   (RVT(R,VNT(V,T))$RT_PP(R,T))
        %VAR%_NCAP.L(RT_PP,P) = 0;  %VAR%_COMNET.L(RT_PP,C,S) = 0;  %VAR%_COMPRD.L(RT_PP,C,S) = 0;
        %VAR%_UCT.L(UC_N,T(FIL)) = 0;  %VAR%_UCTS.L(UC_N,T(FIL),S) = 0;       (FIL: the periods fixed in no region)
        %VAR%_UCRT.L(UC_N,RT_PP) = 0;  %VAR%_UCRTS.L(UC_N,RT_PP,S) = 0;  %EQ%G_COMBAL.L(RT_PP,C,S) = 0;
    solve.stp 61                           VAR_ACT.M(RVT,P,S)=0;
    solve.stp 326-329 (after the solve)    the marginals in the fixed periods:
        %VAR%_NCAP.M(R,T,P)$NO_RT(R,T) = 0;  %VAR%_ACT.M(R,V,T,P,S)$NO_RT(R,T) = 0;
        %VAR%_FLO.M(R,V,T,P,C,S)$NO_RT(R,T) = 0;  %VAR%_IRE.M(R,V,T,P,C,S,IE)$NO_RT(R,T) = 0;

A record left with neither level nor marginal is not added.
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "times_pp"))

from timespp import refpoint  # noqa: E402

MARK = "__loaded_point"
# symbol: (position of the region, position of the period) in its key; None: no region (FIL)
LEVEL_WINDOW = {"VAR_ACT": (0, 2), "VAR_FLO": (0, 2), "VAR_IRE": (0, 2), "VAR_SIN": (0, 2), "VAR_SOUT": (0, 2),
                "VAR_SCAP": (0, 2), "VAR_BSPRS": (0, 2), "VAR_NCAP": (0, 1), "VAR_COMNET": (0, 1), "VAR_COMPRD": (0, 1),
                "VAR_UCT": (None, 1), "VAR_UCTS": (None, 1), "VAR_UCRT": (1, 2), "VAR_UCRTS": (1, 2), "EQG_COMBAL": (0, 1)}
MARGINAL_FIXED = {"VAR_NCAP": (0, 1), "VAR_ACT": (0, 2), "VAR_FLO": (0, 2), "VAR_IRE": (0, 2)}


def fixed_periods(model):
    """NO_RT of the step of a run with FIXBOH: {(region, period)}, labels in upper case.  model: model.db3, or the
    folder model_parquet (the tables of the step are then in model_steps.db3 beside it)."""
    f = os.path.join(os.path.dirname(os.path.abspath(model)), "model_steps.db3") if os.path.isdir(model) else model
    con = sqlite3.connect(f)
    try:
        if not con.execute("select 1 from sqlite_master where name = '__step1_NO_RT'").fetchone():
            raise SystemExit(f"{f} has no table __step1_NO_RT: not the model of a run with FIXBOH")
        return {(str(r).upper(), str(t).upper()) for r, t, v in con.execute('select * from "__step1_NO_RT"') if v}
    finally:
        con.close()


def cleared(sym, rows, dim, no_rt):
    """rows (labels..., level, marginal) of a symbol of the loaded point with what TIMES clears set to 0."""
    lw, mf = LEVEL_WINDOW.get(sym), MARGINAL_FIXED.get(sym)
    if lw is None and mf is None:
        return rows
    fixed_t = {t for _, t in no_rt}
    out = []
    for r in rows:
        k = [str(x).upper() for x in r[:dim]]
        lev, mar = r[dim], r[dim + 1]
        if lw is not None:
            window = k[lw[1]] not in fixed_t if lw[0] is None else (k[lw[0]], k[lw[1]]) not in no_rt
            lev = 0.0 if window else lev
        if sym == "VAR_ACT" or (mf is not None and (k[mf[0]], k[mf[1]]) in no_rt):
            mar = 0.0      # (VAR_ACT: in the window by solve.stp 61, in the fixed periods by solve.stp 327)
        if lev or mar:
            out.append(tuple(r[:dim]) + (lev, mar))
    return out


def under(solution, point, model):
    """Add to solution.db3 the records of the results file `point` that it does not have, less what TIMES clears
    (the fixed periods from `model`).  -> {symbol: records added}; {} when it was done before (the mark __loaded_point)."""
    no_rt = fixed_periods(model)
    con = sqlite3.connect(solution)
    try:
        if con.execute("select 1 from sqlite_master where name = ?", [MARK]).fetchone():
            return {}
        have = {n.upper(): (n, k, d) for n, k, d in con.execute("select name, kind, dim from __symbols")}
        added = {}
        for sym, (kind, rows) in sorted(refpoint.read(point).items()):
            if kind not in ("variable", "equation") or not rows:
                continue
            dim = len(rows[0]) - 2
            name = sym
            if sym in have:
                name, _, d = have[sym]
                empty = con.execute(f'select 1 from "{name}" limit 1').fetchone() is None
                if d != dim and empty:              # (a symbol without records is written without index columns)
                    con.execute(f'drop table "{name}"')
                    con.execute("delete from __symbols where name = ?", [name])
                    del have[sym]
                elif d != dim:
                    continue                        # another symbol of the same name: not this model's
            if sym not in have:
                cols = "".join(f'"d{i}" TEXT, ' for i in range(dim))
                con.execute(f'create table "{name}" ({cols}level REAL, marginal REAL, lower REAL, upper REAL)')
                con.execute("insert into __symbols values (?,?,?)", (name, kind, dim))
                there = set()
            else:
                # (upper case by Python, as for the point's labels below: SQLite's upper() leaves letters beyond ASCII)
                sel = ", ".join(f'"d{i}"' for i in range(dim)) or "1"
                there = {tuple(str(x).upper() for x in r) for r in con.execute(f'select {sel} from "{name}"')} if dim else {()}
            new = [r + (None, None) for r in cleared(sym, [r for r in rows if tuple(str(x).upper() for x in r[:dim]) not in there], dim, no_rt)]
            if new:
                con.executemany(f'insert into "{name}" values ({",".join("?" * (dim + 4))})', new)
                added[name] = len(new)
        # the mark: the file, and for each symbol the records added (they are the last rows of its table)
        con.execute(f"create table {MARK} (file TEXT, symbol TEXT, records INTEGER)")
        con.executemany(f"insert into {MARK} values (?,?,?)", [(os.path.abspath(point), n, k) for n, k in added.items()] or
                        [(os.path.abspath(point), None, 0)])
        con.commit()
        return added
    finally:
        con.close()


def main(argv):
    solution, point, model = argv[1:4]
    added = under(solution, point, model)
    print(f"  the loaded point {os.path.basename(point)} under the solution: {sum(added.values()):,} records of "
          f"{len(added)} variables and equations that the model of this run does not have")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
