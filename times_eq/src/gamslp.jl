# SPDX-License-Identifier: GPL-3.0-or-later
"""
    TimesEq.GamsLP.Optimizer(; gams, solver = "cplex", optfile = "", options = String[], workdir, ...)

An MOI optimizer that has a linear program solved by an LP solver of the user's GAMS installation (CPLEX, Gurobi,
Xpress, ... as the GAMS licence has them): at `optimize!` the LP goes to a GDX in `workdir` (gamslp.py), GAMS solves it
with the one fixed file ../gams/solve_lp.gms, and the solution GDX is read back, in the order of the model's rows and
columns. Everything after `optimize!` (value, dual, reduced_cost, termination_status, objective_value) works as with
any solver. LP only: columns with bounds and affine rows (=, >=, <=, ranged); a model with integer, SOS or
semi-continuous variables stops with a message.

Keywords: `gams` the GAMS executable; `solver` GAMS's LP= (e.g. "cplex"); `optfile` an option file of the solver
(used as it is) and `options` lines added after it ("name value"; "name=value" is written so), both written to
<solver>.opt in `workdir` (none of either: no option file); `threads`, `time_limit` (seconds) for GAMS's threads= and
reslim=; `python` the Python with gams.transfer; `log` a file for GAMS's log; `console` the log to stdout as well;
`keep` the work folder stays after the read-back.

Names (`names`, a folder of `write_matrix`'s files, with `name_rows` the constraint of each of its rows, as
`matrix_rows` gives them): GAMS gets the model by TIMES's names instead of rows and columns by number. gamslp.py
`named` writes the GDX (named.gdx) and the program (lp_names.gms) from the same arrays, through the maps of the rows
and columns to their names; GAMS solves it and writes the same solution.gdx, read back as on the numbered route. Its
listing (lp_names.lst in `workdir`, kept with `keep`) reads like TIMES's: the rows and columns by name, as many as
GAMS's limrow and limcol show (GAMS's defaults: rerun the program with limrow= and limcol= for more).

Signs (checked on an LP with every row kind against HiGHS, test/gamslp.jl): GAMS's marginal of a row is the change of
the objective per unit of its right-hand side, that of a column its reduced cost. MOI's duals are those of the
minimisation: for minimising they are GAMS's marginals; for maximising, the marginals with the sign changed. A
column's reduced cost goes to its bound constraints: a positive one (after that sign) to the lower bound, a negative
one to the upper bound, all of it to a fixed column's or to the only bound a column has.
"""
module GamsLP

import JuMP
const MOI = JuMP.MOI

const ROW_SETS = (MOI.EqualTo{Float64}, MOI.GreaterThan{Float64}, MOI.LessThan{Float64}, MOI.Interval{Float64})
const RowSet = Union{ROW_SETS...}
const SAF = MOI.ScalarAffineFunction{Float64}
const SCRIPT = joinpath(@__DIR__, "..", "gams", "gamslp.py")
const GMS = joinpath(@__DIR__, "..", "gams", "solve_lp.gms")

bounds(s::MOI.EqualTo) = (s.value, s.value)
bounds(s::MOI.GreaterThan) = (s.lower, Inf)
bounds(s::MOI.LessThan) = (-Inf, s.upper)
bounds(s::MOI.Interval) = (s.lower, s.upper)

Base.@kwdef mutable struct Optimizer <: MOI.AbstractOptimizer
    gams::String = "gams"
    solver::String = "cplex"
    optfile::String = ""
    options::Vector{String} = String[]
    workdir::String = joinpath(tempdir(), "gamslp")
    python::String = get(ENV, "TIMES_PYTHON", "python")
    log::String = ""
    console::Bool = true
    keep::Bool = false
    threads::Int = 0
    time_limit::Float64 = 0.0
    direct::String = ""                       # a script that solves the arrays itself (solvers/gurobilp.py): no GDX, no GAMS
    names::String = ""                        # write_matrix's folder: GAMS gets the model by TIMES's names (lp_names.gms)
    name_rows::Vector{MOI.ConstraintIndex} = MOI.ConstraintIndex[]   # with names: the constraint of each row there
    index::Union{Nothing,MOI.Utilities.IndexMap} = nothing           # with names: copy_to's map of the source to the LP
    # the LP, as copy_to took it: rows and columns numbered from 1 (a row's constraint index is its number, a bound's
    # the number of its column)
    collo::Vector{Float64} = Float64[]
    colup::Vector{Float64} = Float64[]
    bound::Vector{UInt8} = UInt8[]            # per column: 1 lower, 2 upper, 4 fixed, 8 interval constraint (or-ed)
    rowlo::Vector{Float64} = Float64[]
    rowup::Vector{Float64} = Float64[]
    I::Vector{Int32} = Int32[]
    J::Vector{Int32} = Int32[]
    V::Vector{Float64} = Float64[]
    c::Vector{Float64} = Float64[]
    c0::Float64 = 0.0
    maximize::Bool = false
    # the solution
    status::MOI.TerminationStatusCode = MOI.OPTIMIZE_NOT_CALLED
    primal::MOI.ResultStatusCode = MOI.NO_SOLUTION
    dual::MOI.ResultStatusCode = MOI.NO_SOLUTION
    raw::String = ""
    x::Vector{Float64} = Float64[]
    rc::Vector{Float64} = Float64[]           # reduced costs, MOI's sign
    y::Vector{Float64} = Float64[]            # row duals, MOI's sign
    act::Vector{Float64} = Float64[]          # row activities
    objval::Float64 = NaN
    iterations::Int = 0
    seconds::Float64 = NaN
    copy_seconds::Float64 = 0.0               # copy_to: the model taken from JuMP as arrays
    # what the solve did: the seconds of each part, the solver's and GAMS's version, the option file's lines
    info::Dict{String,Any} = Dict{String,Any}()
end

MOI.get(o::Optimizer, ::MOI.SolverName) = uppercase(o.solver) * (o.direct == "" ? " through GAMS" : " through Python")
MOI.get(o::Optimizer, ::MOI.SolverVersion) = string(get(o.info, "solver_version", ""))
MOI.is_empty(o::Optimizer) = isempty(o.collo) && isempty(o.rowlo) && o.status == MOI.OPTIMIZE_NOT_CALLED
function MOI.empty!(o::Optimizer)
    for v in (o.collo, o.colup, o.bound, o.rowlo, o.rowup, o.I, o.J, o.V, o.c, o.x, o.rc, o.y, o.act)
        empty!(v)
    end
    o.c0, o.maximize, o.index = 0.0, false, nothing
    o.status, o.primal, o.dual, o.raw = MOI.OPTIMIZE_NOT_CALLED, MOI.NO_SOLUTION, MOI.NO_SOLUTION, ""
    o.objval, o.iterations, o.seconds = NaN, 0, NaN
    empty!(o.info)
    return
end

MOI.supports_incremental_interface(::Optimizer) = false
MOI.supports_constraint(::Optimizer, ::Type{MOI.VariableIndex}, ::Type{<:RowSet}) = true
MOI.supports_constraint(::Optimizer, ::Type{SAF}, ::Type{<:RowSet}) = true
MOI.supports(::Optimizer, ::MOI.ObjectiveSense) = true
MOI.supports(::Optimizer, ::MOI.ObjectiveFunction{<:Union{MOI.VariableIndex,SAF}}) = true
MOI.supports(::Optimizer, ::MOI.Silent) = true
MOI.supports(::Optimizer, ::MOI.TimeLimitSec) = true
MOI.supports(::Optimizer, ::MOI.NumberOfThreads) = true
MOI.set(o::Optimizer, ::MOI.Silent, v::Bool) = (o.console = !v)
MOI.get(o::Optimizer, ::MOI.Silent) = !o.console
MOI.set(o::Optimizer, ::MOI.TimeLimitSec, v) = (o.time_limit = v === nothing ? 0.0 : Float64(v))
MOI.get(o::Optimizer, ::MOI.TimeLimitSec) = o.time_limit > 0 ? o.time_limit : nothing
MOI.set(o::Optimizer, ::MOI.NumberOfThreads, v) = (o.threads = v === nothing ? 0 : Int(v))
MOI.get(o::Optimizer, ::MOI.NumberOfThreads) = o.threads > 0 ? o.threads : nothing

function MOI.copy_to(o::Optimizer, src::MOI.ModelLike)
    MOI.empty!(o)
    t0 = time()
    for (F, S) in MOI.get(src, MOI.ListOfConstraintTypesPresent())
        (F in (MOI.VariableIndex, SAF) && S in ROW_SETS) && continue
        error("the LP solver $(o.solver) through GAMS takes a linear program only; this model has constraints $F in $S " *
              "(integer, SOS or semi-continuous variables, or rows that are not linear)")
    end
    map = MOI.Utilities.IndexMap()
    vars = MOI.get(src, MOI.ListOfVariableIndices())
    n = length(vars)
    for (k, v) in enumerate(vars)
        map[v] = MOI.VariableIndex(k)
    end
    o.collo, o.colup, o.bound = fill(-Inf, n), fill(Inf, n), zeros(UInt8, n)
    for (S, flag) in zip(ROW_SETS, (0x04, 0x01, 0x02, 0x08))
        for ci in MOI.get(src, MOI.ListOfConstraintIndices{MOI.VariableIndex,S}())
            k = map[MOI.get(src, MOI.ConstraintFunction(), ci)].value
            lo, up = bounds(MOI.get(src, MOI.ConstraintSet(), ci))
            isfinite(lo) && (o.collo[k] = lo)
            isfinite(up) && (o.colup[k] = up)
            o.bound[k] |= flag
            map[ci] = MOI.ConstraintIndex{MOI.VariableIndex,S}(k)
        end
    end
    r = 0
    for (F, S) in MOI.get(src, MOI.ListOfConstraintTypesPresent())
        F == SAF || continue
        for ci in MOI.get(src, MOI.ListOfConstraintIndices{SAF,S}())
            f = MOI.Utilities.canonical(MOI.get(src, MOI.ConstraintFunction(), ci))   # repeated terms added, zeros out
            lo, up = bounds(MOI.get(src, MOI.ConstraintSet(), ci))
            r += 1
            push!(o.rowlo, lo - f.constant); push!(o.rowup, up - f.constant)
            for t in f.terms
                push!(o.I, r); push!(o.J, map[t.variable].value); push!(o.V, t.coefficient)
            end
            map[ci] = MOI.ConstraintIndex{SAF,S}(r)
        end
    end
    sense = MOI.get(src, MOI.ObjectiveSense())
    o.maximize = sense == MOI.MAX_SENSE
    o.c = zeros(n)
    if sense != MOI.FEASIBILITY_SENSE
        F = MOI.get(src, MOI.ObjectiveFunctionType())
        f = convert(SAF, MOI.get(src, MOI.ObjectiveFunction{F}()))
        for t in f.terms
            o.c[map[t.variable].value] += t.coefficient
        end
        o.c0 = f.constant
    end
    o.names == "" || (o.index = map)
    o.copy_seconds = time() - t0
    return map
end

"""The largest violation of a row and of a bound by the solution, in the units of the model."""
infeasibility(o) = (maximum(max.(o.rowlo .- o.act, o.act .- o.rowup); init = 0.0), maximum(max.(o.collo .- o.x, o.x .- o.colup); init = 0.0))

writef(dir, name, v) = open(io -> write(io, v), joinpath(dir, name), "w")
readf(dir, name, n) = (v = Vector{Float64}(undef, n); open(io -> read!(io, v), joinpath(dir, name)); v)

# GAMS model status and solve status -> MOI termination, primal and dual status
function statuses(modelstat, solvestat)
    solvestat == 2 && return MOI.ITERATION_LIMIT, modelstat in (7, 8) ? MOI.FEASIBLE_POINT : MOI.NO_SOLUTION
    solvestat == 3 && return MOI.TIME_LIMIT, modelstat in (7, 8) ? MOI.FEASIBLE_POINT : MOI.NO_SOLUTION
    solvestat == 8 && return MOI.INTERRUPTED, modelstat in (7, 8) ? MOI.FEASIBLE_POINT : MOI.NO_SOLUTION
    # an optimum with infeasibilities after unscaling (CPLEX: "optimal with unscaled infeasibilities") is an optimum;
    # what it violates is measured (infeasibility) and shown in the report
    (solvestat == 4 && modelstat == 1) && return MOI.OPTIMAL, MOI.FEASIBLE_POINT
    solvestat == 1 || return MOI.OTHER_ERROR, MOI.NO_SOLUTION
    modelstat == 1 && return MOI.OPTIMAL, MOI.FEASIBLE_POINT
    modelstat == 2 && return MOI.LOCALLY_SOLVED, MOI.FEASIBLE_POINT
    modelstat in (3, 18) && return MOI.DUAL_INFEASIBLE, MOI.NO_SOLUTION
    modelstat in (4, 19) && return MOI.INFEASIBLE, MOI.NO_SOLUTION
    modelstat == 5 && return MOI.LOCALLY_INFEASIBLE, MOI.NO_SOLUTION
    modelstat == 7 && return MOI.OTHER_LIMIT, MOI.FEASIBLE_POINT
    return MOI.OTHER_ERROR, MOI.NO_SOLUTION
end

const MODELSTAT = Dict(1 => "Optimal", 2 => "Locally Optimal", 3 => "Unbounded", 4 => "Infeasible", 5 => "Locally Infeasible",
    6 => "Intermediate Infeasible", 7 => "Feasible Solution", 11 => "Licensing Problem", 12 => "Error Unknown", 13 => "Error No Solution",
    14 => "No Solution Returned", 18 => "Unbounded - No Solution", 19 => "Infeasible - No Solution")

"""The lines of the option file: the user's file as it is, then each of `options` ("name=value" as "name value")."""
function option_lines(o::Optimizer)
    lines = o.optfile == "" ? String[] : readlines(o.optfile)
    for kv in o.options
        k, v = occursin('=', kv) ? strip.(split(kv, '='; limit = 2)) : (strip(kv), "")
        push!(lines, strip("$k $v"))
    end
    return lines
end

"""gamslp.py `what` `dir` (`extra`...) with the Python of `o` (GAMS_DIR: the GAMS of `o`, for gams.transfer); stops when it fails."""
function python_step(o::Optimizer, what, dir, extra...)
    p = run(pipeline(ignorestatus(addenv(`$(o.python) -I $SCRIPT $what $dir $extra`, "GAMS_DIR" => dirname(o.gams))); stdout = devnull, stderr = stderr))
    p.exitcode == 0 || error("the GDX step `$(basename(SCRIPT)) $what` failed (exit code $(p.exitcode)) with $(o.python): " *
                             "its message is above (python TIMES.py setup checks the Python packages and the GDX library)")
end

"""With names: the write_matrix row and column (from 1; 0: none) of each row and column of the LP, to `dir`
(named_rows.i32, named_cols.i32) for gamslp.py `named`."""
function name_maps(o::Optimizer, dir)
    f = joinpath(o.names, "cols_j.i32")
    cj = Vector{Int32}(undef, filesize(f) ÷ 4)
    open(io -> read!(io, cj), f)
    cpos = zeros(Int32, length(o.collo))
    for (p, j) in enumerate(cj)
        cpos[o.index[MOI.VariableIndex(j)].value] = p
    end
    rpos = zeros(Int32, length(o.rowlo))
    for (p, ci) in enumerate(o.name_rows)
        rpos[o.index[ci].value] = p
    end
    writef(dir, "named_rows.i32", rpos); writef(dir, "named_cols.i32", cpos)
end

"""The direct solver script (o.direct) on the arrays in `dir`: it writes the solution arrays and result.txt as the GAMS route does."""
function direct_step(o::Optimizer, dir, info)
    info["option_file"] = o.optfile
    info["option_lines"] = option_lines(o)
    log = o.log == "" ? joinpath(dir, "solver.log") : o.log
    args = String[dir, "--log", log]
    o.optfile == "" || push!(args, "--optfile", o.optfile)
    for kv in o.options
        push!(args, "--option", kv)
    end
    o.threads > 0 && push!(args, "--threads", string(o.threads))
    o.time_limit > 0 && push!(args, "--time-limit", string(o.time_limit))
    o.console && push!(args, "--console")
    t = time()
    p = run(pipeline(ignorestatus(`$(o.python) $(abspath(o.direct)) $args`); stdout = o.console ? stdout : devnull, stderr = stderr))
    info["python_seconds"] = time() - t
    (p.exitcode == 0 && isfile(joinpath(dir, "result.txt"))) ||
        error("$(basename(o.direct)) failed (exit code $(p.exitcode)) with $(o.python): see the Python error above; it needs " *
              "the Python packages gurobipy and scipy (pip install gurobipy==<the version of your Gurobi licence> scipy) " *
              "and a Gurobi licence (GRB_LICENSE_FILE or gurobi.lic)")
    # the option lines Gurobi took as parameters, and the ones it did not (GAMS link options in a gurobi.opt, typos)
    lines(f) = isfile(joinpath(dir, f)) ? filter(!isempty, readlines(joinpath(dir, f))) : String[]
    info["option_lines"] = lines("options_applied.txt")
    skipped = lines("options_skipped.txt")
    isempty(skipped) || (info["options_skipped"] = skipped)
    gi = joinpath(dir, "gurobi_info.json")
    if isfile(gi)
        m = match(r"\"version\":\s*\"([^\"]+)\"", read(gi, String))
        m === nothing || (info["solver_version"] = m.captures[1])
    end
    return
end

function MOI.optimize!(o::Optimizer)
    t0 = time()
    dir = o.workdir
    isdir(dir) && rm(dir; recursive = true)
    mkpath(dir)
    nr, nc = length(o.rowlo), length(o.collo)
    info = o.info
    empty!(info)
    info["copy_seconds"] = o.copy_seconds
    # the LP to a GDX
    t = time()
    writef(dir, "rows_lower.f64", o.rowlo); writef(dir, "rows_upper.f64", o.rowup)
    writef(dir, "cols_lower.f64", o.collo); writef(dir, "cols_upper.f64", o.colup)
    writef(dir, "a_i.i32", o.I); writef(dir, "a_j.i32", o.J); writef(dir, "a_value.f64", o.V); writef(dir, "c.f64", o.c)
    open(joinpath(dir, "meta.json"), "w") do io
        print(io, "{\"rows\": $nr, \"columns\": $nc, \"entries\": $(length(o.V)), \"sense\": \"$(o.maximize ? "max" : "min")\", ",
              "\"constant\": $(repr(o.c0))}")
    end
    info["arrays_seconds"] = time() - t
    if o.direct != ""
        direct_step(o, dir, info)
        t = time()                            # read_seconds: the reading of the solution arrays below
    else
    t = time()
    named = o.names != ""
    if named
        name_maps(o, dir)
        python_step(o, "named", dir, abspath(o.names))
        nf = joinpath(dir, "named.txt")              # what the step wrote: "name value" per line
        isfile(nf) && (info["names"] = Dict{String,Any}(String(k) => something(tryparse(Float64, v), String(v))
                                                        for (k, v) in (split(l; limit = 2) for l in eachline(nf))))
        info["listing"] = joinpath(dir, "lp_names.lst")
    else
        python_step(o, "lp", dir)
    end
    info["gdx_seconds"] = time() - t
    # the option file
    lines = option_lines(o)
    info["option_file"] = o.optfile
    info["option_lines"] = lines
    isempty(lines) || open(io -> foreach(l -> println(io, l), lines), joinpath(dir, lowercase(o.solver) * ".opt"), "w")
    # GAMS
    log = o.log == "" ? joinpath(dir, "gams.log") : o.log
    args = ["--IN=$(named ? "named" : "lp").gdx", "--OUT=solution.gdx", "lp=$(o.solver)", "optfile=$(isempty(lines) ? 0 : 1)", "curdir=$dir",
            "lo=$(o.console ? 4 : 2)", "lf=$log"]
    o.threads > 0 && push!(args, "threads=$(o.threads)")
    o.time_limit > 0 && push!(args, "reslim=$(o.time_limit)")
    t = time()
    p = run(pipeline(ignorestatus(`$(o.gams) $(named ? joinpath(dir, "lp_names.gms") : abspath(GMS)) $args`); stdout = o.console ? stdout : devnull, stderr = stderr))
    info["gams_seconds"] = time() - t
    text = isfile(log) ? read(log, String) : ""
    m = match(r"(?m)^GAMS (\d[\d.]*)", text)
    m === nothing || (info["gams_version"] = m.captures[1])
    # GAMS's start to the solver's start: its stamp "--- Executing CPLEX (Solvelink=2): elapsed 0:00:01.234"
    m = match(r"(?m)^--- Executing (?!after solve)\S+?(?: \([^)]*\))?: elapsed (\d+):(\d+):([\d.]+)", text)
    m === nothing || (info["gams_to_solver_seconds"] = 3600 * parse(Int, m.captures[1]) + 60 * parse(Int, m.captures[2]) + parse(Float64, m.captures[3]))
    m = match(Regex("(?mi)^[-\\s]*$(o.solver)\\s+(\\d+\\.\\d+\\.[\\d.]+)"), text)     # e.g. "--- Cplex 22.1.2.0 link memory ..."
    m === nothing && (m = match(r"(?mi)\b(?:library|version)\s+(\d+\.\d+\.\d+[\d.]*)", text))
    m === nothing || (info["solver_version"] = m.captures[1])
    if !isfile(joinpath(dir, "solution.gdx"))
        tail = join(last(split(text, '\n'), 20), '\n')
        error("GAMS stopped (exit code $(p.exitcode)) before writing the solution; the end of its log ($log):\n$tail")
    end
    # the solution back
    t = time()
    python_step(o, "solution", dir)
    end
    res = Dict{String,Float64}()
    for l in eachline(joinpath(dir, "result.txt"))
        k, v = split(l; limit = 2)
        res[k] = parse(Float64, v)
    end
    σ = o.maximize ? -1.0 : 1.0
    o.x = readf(dir, "x_level.f64", nc)
    xm = readf(dir, "x_marginal.f64", nc)
    o.y = σ .* readf(dir, "row_marginal.f64", nr)
    used = falses(nc)
    used[o.J] .= true
    for k in 1:nc
        used[k] || o.c[k] != 0 || (o.x[k] = clamp(0.0, o.collo[k], o.colup[k]))   # a column GAMS did not generate
    end
    o.rc = σ .* xm
    o.act = zeros(nr)
    for (i, j, v) in zip(o.I, o.J, o.V)
        o.act[i] += v * o.x[j]
    end
    info["read_seconds"] = time() - t
    ms, ss = Int(res["modelstat"]), Int(res["solvestat"])
    o.status, o.primal = statuses(ms, ss)
    # duals: written by the direct solver script (0 when the solver gave none, e.g. a solve stopped at a limit); the GAMS
    # route always reads GAMS's marginals
    o.dual = o.status in (MOI.OPTIMAL, MOI.LOCALLY_SOLVED) && get(res, "duals", 1.0) != 0 ? MOI.FEASIBLE_POINT : MOI.NO_SOLUTION
    o.status in (MOI.OPTIMAL, MOI.LOCALLY_SOLVED) && get(res, "duals", 1.0) == 0 && (info["no_duals"] = true)
    if ms == 1 && ss == 4
        rows, bounds = infeasibility(o)
        info["infeasibility"] = "largest row violation $(round(rows; sigdigits = 3)), largest bound violation $(round(bounds; sigdigits = 3))"
    end
    o.raw = "model status $ms ($(get(MODELSTAT, ms, "?"))), solve status $ss"
    o.objval = res["objval"]
    o.iterations = round(Int, res["iterations"])
    info["solver_seconds"] = res["seconds"]
    info["generation_seconds"] = res["gentime"]
    info["iterations"] = o.iterations
    info["modelstat"], info["solvestat"] = ms, ss
    o.keep || rm(dir; recursive = true, force = true)
    o.seconds = time() - t0
    return
end

MOI.get(o::Optimizer, ::MOI.TerminationStatus) = o.status
MOI.get(o::Optimizer, ::MOI.RawStatusString) = o.raw
MOI.get(o::Optimizer, ::MOI.ResultCount) = o.primal == MOI.NO_SOLUTION ? 0 : 1
MOI.get(o::Optimizer, a::MOI.PrimalStatus) = a.result_index == 1 ? o.primal : MOI.NO_SOLUTION
MOI.get(o::Optimizer, a::MOI.DualStatus) = a.result_index == 1 ? o.dual : MOI.NO_SOLUTION
MOI.get(o::Optimizer, ::MOI.SolveTimeSec) = o.seconds
MOI.get(o::Optimizer, ::MOI.SimplexIterations) = Int64(o.iterations)
function MOI.get(o::Optimizer, a::MOI.ObjectiveValue)
    MOI.check_result_index_bounds(o, a)
    return o.objval
end
function MOI.get(o::Optimizer, a::MOI.VariablePrimal, v::MOI.VariableIndex)
    MOI.check_result_index_bounds(o, a)
    return o.x[v.value]
end
function MOI.get(o::Optimizer, a::MOI.ConstraintPrimal, ci::MOI.ConstraintIndex{SAF,<:RowSet})
    MOI.check_result_index_bounds(o, a)
    return o.act[ci.value]
end
function MOI.get(o::Optimizer, a::MOI.ConstraintPrimal, ci::MOI.ConstraintIndex{MOI.VariableIndex,<:RowSet})
    MOI.check_result_index_bounds(o, a)
    return o.x[ci.value]
end
function MOI.get(o::Optimizer, a::MOI.ConstraintDual, ci::MOI.ConstraintIndex{SAF,<:RowSet})
    MOI.check_result_index_bounds(o, a)
    return o.y[ci.value]
end
function MOI.get(o::Optimizer, a::MOI.ConstraintDual, ci::MOI.ConstraintIndex{MOI.VariableIndex,S}) where {S<:RowSet}
    MOI.check_result_index_bounds(o, a)
    k = ci.value
    d = o.rc[k]
    (S <: Union{MOI.EqualTo,MOI.Interval} || count_ones(o.bound[k] & 0x03) < 2) && return d
    return S <: MOI.GreaterThan ? max(d, 0.0) : min(d, 0.0)
end

end # module GamsLP
