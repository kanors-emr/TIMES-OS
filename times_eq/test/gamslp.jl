# SPDX-License-Identifier: GPL-3.0-or-later
# TimesEq.GamsLP.Optimizer on a small LP with every row kind, a fixed and a free column, minimised and maximised:
# levels, row activities, duals and reduced costs as HiGHS gives them, to 1e-9. Skipped when no GAMS is found
# (TIMES_GAMS or gams on the PATH) or it has no LP solver TIMES_GAMS_LP (default cplex).
using Test, JuMP, HiGHS, TimesEq

function gamslp_gams()
    g = get(ENV, "TIMES_GAMS", "")
    g != "" && isfile(g) && return g
    g = Sys.which("gams")
    return g === nothing ? "" : g
end

function gamslp_model(opt, sense)
    m = Model(opt)
    @variable(m, 0 <= x1 <= 10)
    @variable(m, x2)                       # free
    @variable(m, x3 == 0.5)                # fixed
    @variable(m, x4 >= 1)
    @variable(m, x5 <= 3)
    @constraint(m, e, x1 + x2 + x4 == 6)
    @constraint(m, g, x1 - x3 + x5 >= 1)
    @constraint(m, l, x2 + x3 - x5 <= 5)
    @constraint(m, r, 1 <= x1 + x3 + 2x4 <= 7)
    @constraint(m, l2, x1 + 2x2 + 3x5 <= 12)
    if sense == MIN_SENSE
        @objective(m, Min, x1 + 2x2 - x3 + 3x4 - x5 + 0.5)
    else
        @objective(m, Max, -x1 + x2 + 2x3 - 2x4 + 3x5 - 0.5)
    end
    return m, [x1, x2, x3, x4, x5], [e, g, l, r, l2]
end

@testset "GamsLP against HiGHS" begin
    gams = gamslp_gams()
    if gams == ""
        @info "GamsLP: no GAMS found (TIMES_GAMS or gams on the PATH): skipped"
    else
        for sense in (MIN_SENSE, MAX_SENSE)
            h, hx, hr = gamslp_model(HiGHS.Optimizer, sense)
            set_silent(h); optimize!(h)
            work = mktempdir()
            g, gx, gr = gamslp_model(() -> TimesEq.GamsLP.Optimizer(; gams, solver = get(ENV, "TIMES_GAMS_LP", "cplex"),
                workdir = joinpath(work, "gamslp"), console = false), sense)
            optimize!(g)
            @test termination_status(g) == OPTIMAL
            @test isapprox(objective_value(g), objective_value(h); atol = 1e-9)
            @test all(isapprox.(value.(gx), value.(hx); atol = 1e-9))
            @test all(isapprox.(value.(gr), value.(hr); atol = 1e-9))
            @test all(isapprox.(dual.(gr), dual.(hr); atol = 1e-9))
            @test all(isapprox.(reduced_cost.(gx), reduced_cost.(hx); atol = 1e-9))
            @test all(isapprox.(dual.(LowerBoundRef.(gx[[1, 4]])), dual.(LowerBoundRef.(hx[[1, 4]])); atol = 1e-9))
            @test isapprox(dual(FixRef(gx[3])), dual(FixRef(hx[3])); atol = 1e-9)
        end
        m = Model(() -> TimesEq.GamsLP.Optimizer(; gams, console = false, workdir = joinpath(mktempdir(), "gamslp")))
        @test_throws Exception begin                  # LP only: an integer column stops the solve
            @variable(m, y, Int)
            @objective(m, Min, y)
            optimize!(m)
        end
    end
end

# The same LP by names (names, lp_names.gms): what write_matrix writes, for this LP's rows and columns (in another
# order than the LP's, and an explicit zero), so that GAMS gets equations and variables by family and labels.
# Families: VAR_X(a) x1, (b) x4, (c) x5; VAR_F x2 (no label); VAR_FX(a,c) x3; EQE_BAL(a) e; EQG_LO g; EQL_UP(a) l,
# (b) l2; EQ_RNG(b,c) r (ranged: two equations); an objective with a constant (an objective equation).
function gamslp_names(dir, x, rows)
    mkpath(dir)
    w(name, v) = open(io -> write(io, v), joinpath(dir, name), "w")
    names = ["EQ_RNG", "EQL_UP", "EQG_LO", "EQE_BAL", "VAR_X", "VAR_F", "VAR_FX"]
    labels = ["a", "b", "c"]
    write(joinpath(dir, "names.txt"), join(names, "\n") * "\n")
    write(joinpath(dir, "labels.txt"), join(labels, "\n") * "\n")
    e, g, l, r, l2 = rows
    order = [r, l2, l, g, e]                               # write_matrix's rows: by name
    w("rows_name.i32", Int32[0, 1, 1, 2, 3]); w("rows_k1.i32", Int32[2, 2, 1, 0, 1]); w("rows_k2.i32", Int32[3, 0, 0, 0, 0])
    cols = [x[5], x[4], x[1], x[2], x[3]]
    w("cols_j.i32", Int32[index(c).value for c in cols]); w("cols_name.i32", Int32[4, 4, 4, 5, 6])
    w("cols_k1.i32", Int32[3, 2, 1, 0, 1]); w("cols_k2.i32", Int32[0, 0, 0, 0, 3])
    w("a_i.i32", Int32[3]); w("a_j.i32", Int32[index(x[4]).value]); w("a_value.f64", [0.0])   # x4 in l: an explicit zero
    write(joinpath(dir, "meta.json"), "{\"rows\": 5, \"columns\": 5, \"entries\": 1, \"row_dims\": 2, \"col_dims\": 2}")
    return MOI.ConstraintIndex[index(c) for c in order]
end

@testset "GamsLP by names against HiGHS" begin
    gams = gamslp_gams()
    if gams == ""
        @info "GamsLP by names: no GAMS found (TIMES_GAMS or gams on the PATH): skipped"
    else
        for sense in (MIN_SENSE, MAX_SENSE)
            h, hx, hr = gamslp_model(HiGHS.Optimizer, sense)
            set_silent(h); optimize!(h)
            work = mktempdir()
            o = TimesEq.GamsLP.Optimizer(; gams, solver = get(ENV, "TIMES_GAMS_LP", "cplex"), workdir = joinpath(work, "gamslp"),
                console = false, keep = true, names = joinpath(work, "names"))
            g, gx, gr = gamslp_model(() -> o, sense)
            o.name_rows = gamslp_names(o.names, gx, gr)
            optimize!(g)
            @test termination_status(g) == OPTIMAL
            @test isapprox(objective_value(g), objective_value(h); atol = 1e-9)
            @test all(isapprox.(value.(gx), value.(hx); atol = 1e-9))
            @test all(isapprox.(value.(gr), value.(hr); atol = 1e-9))
            @test all(isapprox.(dual.(gr), dual.(hr); atol = 1e-9))
            @test all(isapprox.(reduced_cost.(gx), reduced_cost.(hx); atol = 1e-9))
            @test all(isapprox.(dual.(LowerBoundRef.(gx[[1, 4]])), dual.(LowerBoundRef.(hx[[1, 4]])); atol = 1e-9))
            @test isapprox(dual(FixRef(gx[3])), dual(FixRef(hx[3])); atol = 1e-9)
            lst = read(joinpath(work, "gamslp", "lp_names.lst"), String)
            @test occursin("EQE_BAL(a)..", lst) && occursin("EQ_RNG(b,c)..", lst) && occursin("EQ_RNG_l(b,c)..", lst)
            @test occursin("EPS*VAR_X(b)", lst) && occursin("VAR_FX(a,c)", lst)
        end
    end
end

# An optimum with infeasibilities after unscaling (GAMS: model status 1, solve status 4) is an optimum, with its
# violations measured. A script in place of a solver returns x = 0, which breaks the bound of x4 by 1 and the
# row e by 6.
@testset "GamsLP: optimal, flagged in the original scale" begin
    @test TimesEq.GamsLP.statuses(1, 4) == (TimesEq.GamsLP.MOI.OPTIMAL, TimesEq.GamsLP.MOI.FEASIBLE_POINT)
    @test TimesEq.GamsLP.statuses(12, 4) == (TimesEq.GamsLP.MOI.OTHER_ERROR, TimesEq.GamsLP.MOI.NO_SOLUTION)
    py = get(ENV, "TIMES_PYTHON", something(Sys.which("python"), Sys.which("python3"), ""))
    if py == ""
        @info "GamsLP flagged optimum: no Python: skipped"
    else
        work = mktempdir()
        script = joinpath(work, "flagged.py")
        write(script, """
        import json, os, sys
        d = sys.argv[1]
        m = json.load(open(os.path.join(d, "meta.json")))
        for name, n in (("x_level", m["columns"]), ("x_marginal", m["columns"]), ("row_marginal", m["rows"])):
            open(os.path.join(d, name + ".f64"), "wb").write(bytes(8 * n))
        open(os.path.join(d, "result.txt"), "w").write(chr(10).join(["modelstat 1", "solvestat 4", "objval 1.5", "iterations 7", "seconds 0.1", "gentime 0.1"]))
        """)
        lp = TimesEq.GamsLP.Optimizer(; direct = script, python = py, solver = "gurobi", workdir = joinpath(work, "gamslp"), console = false)
        g, gx, gr = gamslp_model(() -> lp, MIN_SENSE)
        optimize!(g)
        @test termination_status(g) == OPTIMAL
        @test primal_status(g) == FEASIBLE_POINT
        @test dual_status(g) == FEASIBLE_POINT
        @test objective_value(g) == 1.5
        @test lp.info["infeasibility"] == "largest row violation 6.0, largest bound violation 1.0"
    end
end

# The same LP solved by Gurobi through its Python interface (solvers/gurobilp.py, --gurobi). Skipped when the Python
# of TIMES_PYTHON (default python) has no gurobipy and scipy; gurobipy's own licence is enough for a model this size.
function gamslp_python_gurobi()
    py = get(ENV, "TIMES_PYTHON", something(Sys.which("python"), Sys.which("python3"), ""))
    py == "" && return ""
    ok = success(pipeline(`$py -c "import gurobipy, scipy"`; stdout = devnull, stderr = devnull))
    return ok ? py : ""
end

@testset "GamsLP direct (Gurobi through Python) against HiGHS" begin
    py = gamslp_python_gurobi()
    if py == ""
        @info "GamsLP direct: no Python with gurobipy and scipy (TIMES_PYTHON): skipped"
    else
        script = joinpath(@__DIR__, "..", "solvers", "gurobilp.py")
        for sense in (MIN_SENSE, MAX_SENSE)
            h, hx, hr = gamslp_model(HiGHS.Optimizer, sense)
            set_silent(h); optimize!(h)
            g, gx, gr = gamslp_model(() -> TimesEq.GamsLP.Optimizer(; direct = script, python = py, solver = "gurobi",
                workdir = joinpath(mktempdir(), "gamslp"), console = false), sense)
            optimize!(g)
            @test termination_status(g) == OPTIMAL
            @test isapprox(objective_value(g), objective_value(h); atol = 1e-9)
            @test all(isapprox.(value.(gx), value.(hx); atol = 1e-9))
            @test all(isapprox.(value.(gr), value.(hr); atol = 1e-9))
            @test all(isapprox.(dual.(gr), dual.(hr); atol = 1e-9))
            @test all(isapprox.(reduced_cost.(gx), reduced_cost.(hx); atol = 1e-9))
            @test all(isapprox.(dual.(LowerBoundRef.(gx[[1, 4]])), dual.(LowerBoundRef.(hx[[1, 4]])); atol = 1e-9))
            @test isapprox(dual(FixRef(gx[3])), dual(FixRef(hx[3])); atol = 1e-9)
        end
    end
end
