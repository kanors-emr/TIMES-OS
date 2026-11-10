# SPDX-License-Identifier: GPL-3.0-or-later
"""Solve the linear program of TimesEq.GamsLP.Optimizer (times_eq/src/gamslp.jl) with Gurobi's Python interface
(gurobipy), without GAMS: the arrays gamslp.jl writes in, the arrays gamslp.py's solution step makes out.

  python gurobilp.py <folder> [--optfile <file>] [--option name=value ...] [--threads n] [--time-limit s]
                              [--log <file>] [--console]

In <folder>: meta.json, rows_lower.f64, rows_upper.f64, cols_lower.f64, cols_upper.f64, a_i.i32, a_j.i32, a_value.f64,
c.f64 (see times_eq/gams/gamslp.py).  Written back: x_level.f64, x_marginal.f64 (reduced costs), row_marginal.f64
(row duals), result.txt (modelstat, solvestat, objval, iterations, seconds, gentime, duals: 1 when Gurobi gave them,
0 when it did not, e.g. a solve stopped at a limit, so that no marginals are read back), gurobi_info.json, and
options_applied.txt / options_skipped.txt (the option lines Gurobi took as parameters, and the ones it did not).
Signs are those of GAMS's marginals (the change of the objective per unit of the right-hand side: Gurobi's Pi and RC);
modelstat and solvestat are GAMS's codes, so that gamslp.jl reads the result as it reads GAMS's.

Rows: lo = up an equality; one side infinite an inequality; both finite and unequal a ranged row, written as two
inequalities whose duals are added back; both infinite: dropped (dual 0).  The option file has the format of GAMS's
gurobi.opt (one "name value" or "name=value" per line, * starts a comment); each line is a Gurobi parameter.
"""
import os, sys, json, time


def read_options(optfile, options):
    lines = open(optfile).read().splitlines() if optfile else []
    lines += options
    out = []
    for ln in lines:
        ln = ln.split("#")[0].strip()
        if not ln or ln.startswith("*"):
            continue
        if "=" in ln:
            k, v = [s.strip() for s in ln.split("=", 1)]
        else:
            parts = ln.split(None, 1)
            k, v = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        out.append((k, v))
    return out


def main(argv):
    import numpy as np
    import scipy.sparse as sp
    import gurobipy as gp
    from gurobipy import GRB

    folder = argv[0]
    optfile, options, threads, tlimit, log, console = "", [], 0, 0.0, "", False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--optfile": optfile = argv[i + 1]; i += 1
        elif a == "--option": options.append(argv[i + 1]); i += 1
        elif a == "--threads": threads = int(argv[i + 1]); i += 1
        elif a == "--time-limit": tlimit = float(argv[i + 1]); i += 1
        elif a == "--log": log = argv[i + 1]; i += 1
        elif a == "--console": console = True
        i += 1

    t0 = time.time()
    meta = json.load(open(os.path.join(folder, "meta.json")))
    rd = lambda n, t: np.fromfile(os.path.join(folder, n), dtype=t)
    nr, nc = meta["rows"], meta["columns"]
    rlo, rup = rd("rows_lower.f64", "<f8"), rd("rows_upper.f64", "<f8")
    xlo, xup = rd("cols_lower.f64", "<f8"), rd("cols_upper.f64", "<f8")
    c = rd("c.f64", "<f8")

    eq = rlo == rup
    ge = ~eq & np.isfinite(rlo)
    le = ~eq & np.isfinite(rup)
    src = np.concatenate([np.nonzero(eq)[0], np.nonzero(ge)[0], np.nonzero(le)[0]])
    sns = np.array(["="] * int(eq.sum()) + [">"] * int(ge.sum()) + ["<"] * int(le.sum()))
    rhs = np.concatenate([rlo[eq], rlo[ge], rup[le]])
    # The matrix in the order of src, built once from the entries: each entry goes to the new number of its row (a
    # ranged row is in src twice, as >= and as <=, and its entries go to both), so the matrix is never copied by rows.
    first, second = np.full(nr, -1, np.int64), np.full(nr, -1, np.int64)
    k = np.arange(len(src), dtype=np.int64)
    taken = np.zeros(nr, bool)
    for part in (np.nonzero(eq)[0], np.nonzero(ge)[0], np.nonzero(le)[0]):
        pos, k = k[:len(part)], k[len(part):]
        again = taken[part]
        first[part[~again]] = pos[~again]
        second[part[again]] = pos[again]
        taken[part] = True
    ai, aj, av = rd("a_i.i32", "<i4").astype(np.int64) - 1, rd("a_j.i32", "<i4") - 1, rd("a_value.f64", "<f8")
    r1, r2 = first[ai], second[ai]
    k1, k2 = r1 >= 0, r2 >= 0
    if k2.any():
        rows, cols, vals = np.concatenate([r1[k1], r2[k2]]), np.concatenate([aj[k1], aj[k2]]), np.concatenate([av[k1], av[k2]])
    else:
        rows, cols, vals = r1[k1], aj[k1], av[k1]
    del ai, aj, av, r1, r2, k1, k2, first, second, taken
    A = sp.csr_matrix((vals, (rows, cols)), shape=(len(src), nc))
    del rows, cols, vals

    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 1)
    env.setParam("LogToConsole", 1 if console else 0)
    if log:
        env.setParam("LogFile", log)
    env.start()
    m = gp.Model("times_lp", env=env)
    x = m.addMVar(nc, lb=xlo, ub=xup, obj=c, name="x")
    m.ObjCon = float(meta["constant"])
    m.ModelSense = GRB.MAXIMIZE if meta["sense"] == "max" else GRB.MINIMIZE
    cons = m.addMConstr(A, x, sns, rhs)
    m.update()
    del A                                             # Gurobi holds its own copy now
    gentime = time.time() - t0

    if threads > 0:
        m.Params.Threads = threads
    if tlimit > 0:
        m.Params.TimeLimit = tlimit
    applied, skipped = [], []
    for k, v in read_options(optfile, options):
        try:
            typ = m.getParamInfo(k)[1]                 # gurobipy wants the value in the parameter's own type
            val = int(float(v)) if typ is int else float(v) if typ is float else v
            m.setParam(k, val)
            applied.append(f"{k} {val}")
        except Exception as e:
            skipped.append(f"{k} {v}".strip())
            print(f"gurobi option '{k} {v}' not applied: {e}", file=sys.stderr)
    for name, lines in (("options_applied.txt", applied), ("options_skipped.txt", skipped)):
        with open(os.path.join(folder, name), "w") as f:
            f.writelines(l + "\n" for l in lines)
    m.optimize()

    st = m.Status
    if st == GRB.INF_OR_UNBD:
        # presolve could not tell infeasible from unbounded: solve again without dual reductions, which tells
        m.Params.DualReductions = 0
        m.optimize()
        st = m.Status
    has_sol = m.SolCount > 0
    solvestat, modelstat = 1, 12
    if st == GRB.OPTIMAL: modelstat = 1
    elif st in (GRB.INFEASIBLE, GRB.INF_OR_UNBD): modelstat = 19
    elif st == GRB.UNBOUNDED: modelstat = 18
    elif st == GRB.TIME_LIMIT: solvestat, modelstat = 3, (7 if has_sol else 14)
    elif st == GRB.ITERATION_LIMIT: solvestat, modelstat = 2, (7 if has_sol else 14)
    elif st == GRB.INTERRUPTED: solvestat, modelstat = 8, (7 if has_sol else 14)
    elif st == GRB.SUBOPTIMAL: modelstat = 7 if has_sol else 14
    else: solvestat = 4

    xl, xm, rm = np.zeros(nc), np.zeros(nc), np.zeros(nr)
    objval = float("nan")
    duals = 0                                         # 1 when Gurobi gave the duals and reduced costs
    if has_sol:
        objval = m.ObjVal
        xl = np.asarray(x.X)
        try:
            xm = np.asarray(x.RC)
            np.add.at(rm, src, np.asarray(cons.Pi))
            duals = 1
        except gp.GurobiError as e:
            xm, rm = np.zeros(nc), np.zeros(nr)
            print(f"no duals from Gurobi ({e}); the marginals are not written",
                  file=sys.stderr)
    xl.astype("<f8").tofile(os.path.join(folder, "x_level.f64"))
    xm.astype("<f8").tofile(os.path.join(folder, "x_marginal.f64"))
    rm.astype("<f8").tofile(os.path.join(folder, "row_marginal.f64"))
    try:
        iters = int(m.IterCount) + int(m.BarIterCount)
    except gp.GurobiError:
        iters = 0
    res = {"modelstat": modelstat, "solvestat": solvestat, "objval": objval, "iterations": iters,
           "seconds": m.Runtime, "gentime": gentime, "duals": duals}
    with open(os.path.join(folder, "result.txt"), "w") as f:
        f.writelines(f"{k} {val!r}\n" for k, val in res.items())
    with open(os.path.join(folder, "gurobi_info.json"), "w") as f:
        json.dump({"version": ".".join(map(str, gp.gurobi.version())), "options": applied, "status": int(st)}, f)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
