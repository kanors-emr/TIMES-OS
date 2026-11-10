# SPDX-License-Identifier: GPL-3.0-or-later
"""
TIMES equations in JuMP.

Input is a model that has already been preprocessed (by the Python preprocessor `timespp`, or by
GAMS, its tables written to SQLite before the solve). This package only states the equations.

    d = TimesEq.load("model.db3")       # tables -> typed sets, parameters and variable bounds
    m = TimesEq.build(d)                # JuMP model in m.jump

Layout:
- `schema.jl`     what is read: every set, parameter and variable with its named columns,
                  the lookups built on them, and the input that is not supported yet
- `data.jl`       loading and the table types
- `model.jl`      variables (created on first use), `row!`, clean-up
- `terms.jl`      expressions shared by several equations (flows by timeslice, trade, capacity)
- `equations/`    one file per equation family
- `checks.jl`     row counts, non-zeros, coefficient table, test of a given solution
- `compare.jl`    a built model against the rows, columns, levels and marginals of the GAMS run
"""
module TimesEq

import JuMP
import SQLite
import PrecompileTools
const MOI = JuMP.MOI

include("schema.jl")
include("data.jl")
include("tjb.jl")
include("model.jl")
include("stochastic.jl")
include("lx.jl")
include("terms.jl")
include("equations/actflo.jl")
include("equations/capact.jl")
include("equations/flofr.jl")
include("equations/caflac.jl")
include("equations/cpt.jl")
include("equations/actbnd.jl")
include("equations/bndcom.jl")
include("equations/floshr.jl")
include("equations/ashar.jl")
include("equations/flobnd.jl")
include("equations/flomrk.jl")
include("equations/ptrans.jl")
include("equations/acteff.jl")
include("equations/combal.jl")
include("equations/ire.jl")
include("equations/irebnd.jl")
include("equations/blend.jl")
include("equations/peak.jl")
include("equations/storage.jl")
include("equations/loadshift.jl")
include("equations/dispatch.jl")
include("equations/startup.jl")
include("equations/bndcst.jl")
include("equations/objbal.jl")
include("equations/grids.jl")
include("equations/resloadc.jl")
include("equations/abs.jl")
include("equations/ucbet.jl")
include("equations/dsc.jl")
include("equations/capvac.jl")
include("equations/ptdf.jl")
include("equations/retire.jl")
include("equations/cumcom.jl")
include("equations/cumflo.jl")
include("equations/ucrtp.jl")
include("equations/userco.jl")
include("equations/objels.jl")
include("equations/objann.jl")
include("equations/mlf.jl")
include("equations/cli.jl")
include("negishi.jl")
include("checks.jl")
include("compare.jl")
include("steps.jl")
include("solution.jl")
include("highs.jl")
include("gamslp.jl")

"""Equation families in the order they are generated."""
const EQUATIONS = (eq_actflo!, eq_capact!, eq_capvac!, eq_caflac!, eq_cpt!, eq_actbnd!, eq_bndcom!, eq_floshr!, eq_ashar!, eq_flobnd!, eq_flofr!, eq_flomrk!,
    eq_ptrans!, eq_acteff!, eq_combal!, eq_ire!, eq_irebnd!, eq_blnd!, eq_peak!, eq_stgtss!, eq_stgips!, eq_stgaux!, eq_stgccl!, eq_stsbal!, eq_stgflo!, eq_slsift!, eq_capload!, eq_actramp!, eq_actrmpc!, eq_actpl!, eq_actups!, eq_actupc!, eq_sdlogic!, eq_sudupt!, eq_sdslant!, eq_sdminon!, eq_sudload!, eq_sudtime!, eq_sudpll!, eq_gr_ptdflo!, eq_gr_powflo!, eq_gr_virt!, eq_gr_genall!, eq_gr_demall!, eq_gr_xbnd!, eq_gg!, eq_ucbet!, eq_rl!, eq_bs!, eq_cumret!, eq_scap!, eq_dscret!, eq_dsc!, eq_refit!,
    eq_bndcst!, eq_objbal!, eq_cumcom!, eq_cumflo!, eq_userco!, eq_ucrtp!, eq_ucrtc!, eq_objels!, eq_obj!, eq_mlf!, eq_cli!)

"""
    build(d::Data; cufscal = 10.0, names = false) -> Model

State all equations for the preprocessed model `d`. Stops with an error when `d` uses a TIMES
feature whose equations are not written yet (`strict = false` only warns: the model is then
incomplete, which is useful to see how far a new case gets). `progress(name, seconds, model)` is called
after each equation family. `names = true` names every row and column
(`VAR_FLO(REG1,2020,...)`), which is slower and only needed to write readable LP/MPS files.
`stats = BuildStats()` records the times of a build in threads in it (see BuildStats).
"""
function build(d::Data; cufscal::Float64 = 10.0, names::Bool = false, strict::Bool = true, progress = nothing,
               parallel::Bool = parallel_build(), stats = nothing)
    check_supported(d; strict)
    m = Model(d; cufscal, names)
    ensure_scratch!()
    clear_branch!()
    empty!(NOROW_INFES)                                     # (left by a build that stopped before its finish!)
    if m.sw !== nothing && !parallel
        # stochastic TIMES: each family once for every SOW, in order (stochastic.jl), one after another
        year0(m); sow_labels!(m)
        for eq! in EQUATIONS
            t = @elapsed for w in m.sw.sows
                sow!(m.sw, w)
                eq!(m)
            end
            progress === nothing || progress(nameof(eq!), t, m)
        end
    elseif parallel
        # The label "0" (year0), added here when no table read has it: the families in threads then only look it up.
        # It gets the number one after another would give it: eq_flobnd! asks for it first thing, and no family before
        # it adds a label.
        year0(m)
        m.sw === nothing || sow_labels!(m)
        build_parallel!(m, progress; stats)
    else
        for eq! in EQUATIONS
            t = @elapsed eq!(m)
            progress === nothing || progress(nameof(eq!), t, m)
        end
    end
    finish!(m)
    clear_branch!()                                         # the positions onbranch took (terms.jl)
    return m
end

"""Families built side by side in threads (with Julia started with more than one thread); TIMESEQ_PARALLEL=0: one
after another."""
parallel_build() = Threads.nthreads() > 1 && get(ENV, "TIMESEQ_PARALLEL", "1") != "0"

# Families built at their turn on the main thread, not in a thread: they may add labels (id!), set bounds or variable
# types while they build (a family in a thread has provisional variables: a type set on them would land on other
# columns). (The families that read the label "0", year0, only look it up: build() adds it before the threads.)
const DIRECT = (:eq_stgips!, :eq_stgccl!, :eq_gg!, :eq_rl!, :eq_bs!, :eq_dscret!, :eq_dsc!)

"""
The times of a build in threads (build_parallel!), recorded only when one is given to `build(d; stats)`; without it
the build reads no clock but the one of `progress`. `barrier = true` (a measurement) waits until every family is
computed before the first commit.
"""
Base.@kwdef mutable struct BuildStats
    barrier::Bool = false
    # family => (seconds computing in its task(s), seconds committing)
    par::Dict{Symbol,NTuple{2,Float64}} = Dict{Symbol,NTuple{2,Float64}}()
    # family => per piece (a family not cut: one), as time(): when its task got a slot, when its compute ended, when the
    # look-up of its variables started and ended (stage_vars!), when its commit (its rows) started and ended
    pieces::Dict{Symbol,Vector{NTuple{6,Float64}}} = Dict{Symbol,Vector{NTuple{6,Float64}}}()
    commit_vars::Float64 = 0.0      # seconds of the look-ups of variables (stage_vars!)
    commit_gc::Float64 = 0.0        # seconds of garbage collection during the commits of rows (stage_rows!)
    commit_replays::Int = 0         # variables of the recordings looked up or created by the commits
end

# Families computed in pieces (TIMESEQ_PAR_PIECES = n > 1: about n each), each piece in a task of its own: family =>
# the function that cuts it, (m, n) -> the pieces, each a function of a recording model. The pieces are committed one
# after another in their order, so the family's rows and the order in which it first asks for variables stay those of
# the family built whole: a piece is a contiguous block of the family's loop, cut where the loop carries nothing from
# one entry to the next (see each function).
const PIECES = Dict{Symbol,Function}(:eq_actflo! => actflo_pieces, :eq_capact! => capact_pieces, :eq_floshr! => floshr_pieces,
    :eq_ptrans! => ptrans_pieces, :eq_acteff! => acteff_pieces, :eq_combal! => combal_pieces, :eq_userco! => userco_pieces)

"""About `n` contiguous blocks of `rows` (the rows of a table a family loops over), as views, in order."""
function blocks(rows::AbstractVector, n::Int)
    k = max(1, min(n, length(rows)))
    cuts = [round(Int, j * length(rows) / k) for j in 0:k]
    return [view(rows, cuts[j]+1:cuts[j+1]) for j in 1:k]
end

"""
Every family except DIRECT is computed in its own task (`Threads.@spawn`) into a buffer, over variables of its own
(`recording`); in a stochastic run (STAGES) a task for each SOW of each family, committed SOW after SOW as the build
one after another writes them (stochastic.jl). The buffers are then added to the model one after another in the order of EQUATIONS
(`commit_staged!`), each as soon as it is ready, while later families are still computing. The variables are created
in the order the families ask for them, family by family, so the model is the one the sequential build makes, row for
row and column for column. A DIRECT family waits until every task has finished (it may change the labels the tasks
read), then builds into the model at its turn.

At most `workers` families compute at once, taking their slots about in the order of EQUATIONS; `pieces` > 1 computes
the families of PIECES in about that many pieces each.
"""
function build_parallel!(m::Model, @nospecialize(progress);
                         workers::Int = parse(Int, get(ENV, "TIMESEQ_PAR_WORKERS", string(Threads.nthreads()))),
                         pieces::Int = parse(Int, get(ENV, "TIMESEQ_PAR_PIECES", "8")),
                         stats::Union{Nothing,BuildStats} = nothing)
    n = length(EQUATIONS)
    tasks = Vector{Union{Nothing,Vector{Union{Nothing,Task}}}}(nothing, n)
    sem = Base.Semaphore(max(1, workers))               # at most `workers` families computing at once
    # (SENSIS: one SOW and the deterministic variables: the tasks of a deterministic build, compiled with the package;
    # recording gives each the SOW of the context)
    sows = (m.sw === nothing || m.sw.sensis) ? Union{Nothing,Id}[nothing] : m.sw.sows
    for (i, eq!) in enumerate(EQUATIONS)
        nameof(eq!) in DIRECT && continue
        parts = pieces > 1 && haskey(PIECES, nameof(eq!)) ? PIECES[nameof(eq!)](m, pieces) : Function[eq!]
        ts = Union{Nothing,Task}[]                     # a loop: a comprehension over both compiles for half a minute
        for w in sows, f in parts
            push!(ts, piece_task(f, m, sem, stats !== nothing, w))
        end
        tasks[i] = ts
    end
    waitall() = foreach(ts -> ts === nothing || foreach(t -> t === nothing || untask(wait, t), ts), tasks)
    stats !== nothing && stats.barrier && waitall()
    return commit_staged!(m, tasks, progress, waitall, stats)
end

# The commits of build_parallel! in two stages (see Staged): a task takes the families' and pieces' results in the
# order of EQUATIONS and looks up their variables (stage_vars!); the main thread adds them to the model in the same
# order (stage_rows!). At a DIRECT family the task waits until it is built (it may add variables), then goes on from
# the model's count of variables. A family's seconds for `progress` are those of its commits (a DIRECT family: its build).
function commit_staged!(m::Model, tasks, @nospecialize(progress), waitall, stats::Union{Nothing,BuildStats})
    ch = Channel{Any}(Inf)
    resume = Channel{Int}(1)
    st = Staged(JuMP.num_variables(m.jump), Tuple{Float64,Float64,Int64}[])
    Threads.@spawn try
        for (i, ts) in enumerate(tasks)
            if ts === nothing
                put!(ch, (:direct, i))
                st.next = take!(resume)
                continue
            end
            for k in eachindex(ts)
                rm, tk, a, b = untask(fetch, ts[k])::Tuple{Model,Float64,Float64,Float64}
                ts[k] = nothing
                v0 = stats === nothing ? 0.0 : time()
                st.new = Tuple{Float64,Float64,Int64}[]
                pmap = stage_vars!(m, rm, st)
                stats === nothing || (stats.commit_replays += length(pmap))
                put!(ch, (:piece, rm, pmap, st.new, tk, (a, b, v0, stats === nothing ? 0.0 : time())))
            end
            put!(ch, (:done, i))
        end
    catch e
        isopen(ch) && put!(ch, (:error, e))
    end
    try
        for (i, eq!) in enumerate(EQUATIONS)
            tc = t = 0.0
            clock = NTuple{6,Float64}[]
            while true
                x = take!(ch)
                if x[1] === :error
                    throw(x[2])
                elseif x[1] === :direct
                    waitall()
                    if stats === nothing && progress === nothing
                        direct!(eq!, m)
                    else
                        c0 = time()
                        t = @elapsed direct!(eq!, m)
                        push!(clock, (c0, c0, c0, c0, c0, time()))
                    end
                    put!(resume, JuMP.num_variables(m.jump))
                    break
                elseif x[1] === :done
                    break
                end
                _, rm, pmap, new, tk, (a, b, v0, v1) = x
                if stats === nothing && progress === nothing
                    stage_rows!(m, rm, pmap, new)
                    continue
                end
                c0 = time(); g0 = stats === nothing ? UInt64(0) : Base.gc_time_ns()
                t += @elapsed stage_rows!(m, rm, pmap, new)
                stats === nothing && continue
                tc += tk
                stats.commit_vars += v1 - v0
                stats.commit_gc += (Base.gc_time_ns() - g0) / 1e9
                push!(clock, (a, b, v0, v1, c0, time()))
            end
            if stats !== nothing
                stats.par[nameof(eq!)] = (tc, t)
                stats.pieces[nameof(eq!)] = clock
            end
            progress === nothing || progress(nameof(eq!), t, m)
        end
    finally
        close(resume); close(ch)
    end
    fill!(tasks, nothing)
    return nothing
end

# A DIRECT family at its turn, on the model: in a stochastic run once for each SOW, in order.
direct!(eq!, m::Model) = m.sw === nothing ? eq!(m) : foreach(w -> (sow!(m.sw, w); eq!(m)), m.sw.sows)

# The task of a family or a piece (of the rows of SOW w in a stochastic run): it waits for a slot, then computes into a
# recording view of the model; `timed`: with the slot's time, the seconds of the compute and its end (BuildStats),
# else zeros.
@noinline piece_task(f, m::Model, sem::Base.Semaphore, timed::Bool, w = nothing) = Threads.@spawn begin
    Base.acquire(sem)
    try
        a = timed ? time() : 0.0
        task_local_storage(:cmag, IdDict{AE,Float64}())
        rm = recording(m, w)
        if timed
            t = @elapsed f(rm)
            (rm, t, a, time())
        else
            f(rm)
            (rm, 0.0, 0.0, 0.0)
        end
    finally
        Base.release(sem)
    end
end

# A family that stops in its thread (an unsupported feature, a "division by eps" as GAMS has it) stops the build with
# its own error, not Julia's TaskFailedException around it, so that the message is the one the report shows.
function untask(f, t::Task)
    try
        return f(t)
    catch e
        e isa TaskFailedException ? throw(e.task.exception) : rethrow()
    end
end

include("runcase.jl")

# Compiled with the package, so that a run does not wait for the compiler. An empty model compiles the equation
# functions themselves; what they call depends on the data and is compiled only when a real model runs through it.
# So the workload also runs a whole case on the tables of models/DemoS_012, which `TIMES.py setup` writes to
# precompile/model.db3 with the preprocessor (with a solve that writes the solution, then a comparison with that
# solution that writes the model's matrix, as a run with --gams and --check does). precompile/WORKLOAD.txt says which (mode: full, or dev for `setup --dev`:
# the empty model only) and is a dependency: when its text changes, Julia compiles the package again. The whole
# case runs whenever model.db3 is there, unless the file says dev (a file of an older setup has no mode line).
const WORKLOAD_DIR = joinpath(dirname(@__DIR__), "precompile")
const WORKLOAD_TXT = joinpath(WORKLOAD_DIR, "WORKLOAD.txt")
isfile(WORKLOAD_TXT) && include_dependency(WORKLOAD_TXT)
const WHOLE_CASE = !(isfile(WORKLOAD_TXT) && occursin(r"(?m)^mode: dev", read(WORKLOAD_TXT, String)))
PrecompileTools.@compile_workload begin
    build(Data("", Labels(), Dict{Symbol,Any}(), Dict{Symbol,Any}(), Dict{Symbol,Any}(), Dict{Symbol,Int}()); names = true)
    # the equation functions for the variable families of stochastic TIMES (STAGES: VarsST): an empty model with one
    # state of the world (SOW '1' in SW_TSW), so that a stochastic run does not wait for the compiler either
    let L = Labels(), w = id!(L, "1"), t = id!(L, "2020")
        sw = Dict{Symbol,Any}(:SW_TSW => Table{NTuple{3,Id}}([(w, t, w)], Set([(w, t, w)])), :SOW => Table{Id}([w], Set([w])),
                              :SW_T => Table{NTuple{2,Id}}([(t, w)], Set([(t, w)])))
        build(Data("", L, sw, Dict{Symbol,Any}(), Dict{Symbol,Any}(), Dict{Symbol,Int}()); names = true)
        # the same in threads (build_parallel!): its tasks and commits for these variable families
        build(Data("", L, sw, Dict{Symbol,Any}(), Dict{Symbol,Any}(), Dict{Symbol,Int}()); names = true, parallel = true)
    end
    # deleting variables (drop_unused!): models/DemoS_012 has no unused variable, so without this MOI's deletion code
    # was compiled in every run of a model that has one (on a model of 10 M rows, far longer than the deletion itself)
    let jm = JuMP.Model()
        x = [JuMP.@variable(jm) for _ in 1:3]
        JuMP.set_lower_bound(x[1], 0.0); JuMP.fix(x[3], 1.0)
        JuMP.add_constraint(jm, JuMP.ScalarConstraint(JuMP.AffExpr(0.0, x[1] => 1.0, x[2] => 2.0), MOI.LessThan(1.0)))
        JuMP.add_constraint(jm, JuMP.ScalarConstraint(JuMP.AffExpr(0.0, x[1] => 1.0), MOI.GreaterThan(0.0)))
        JuMP.add_constraint(jm, JuMP.ScalarConstraint(JuMP.AffExpr(0.0, x[2] => 1.0), MOI.EqualTo(0.0)))
        JuMP.delete(jm, [x[3]])
    end
    db = joinpath(WORKLOAD_DIR, "model.db3")
    if WHOLE_CASE && isfile(db)
        tmp = mktempdir()
        # A failing workload only means less is compiled ahead: say so and let the package build. Windows keeps a
        # file open by an SQLite handle that is not yet finalized, so collect before removing the folder, and
        # leave the folder if it is still held.
        try
            st = redirect_stdout(devnull) do
                (RunCase.run_case([db, joinpath(tmp, "solve.json"), "--solution", joinpath(tmp, "solution.db3"),
                                   "--highs-log", joinpath(tmp, "highs.log")]),
                 # (with the model's matrix written, as --check and --jacobian have it: write_matrix compiled took
                 # about 1 s of every such run, whatever the model's size)
                 RunCase.run_case([db, joinpath(tmp, "compare.json"), "--gams", joinpath(tmp, "solution.db3"),
                                   "--no-solve", "--matrix-out", joinpath(tmp, "matrix_here")]))
            end
            all(==(0), st) || @warn "TimesEq precompile workload: run_case returned $st; the package is built, less is compiled ahead"
            # the families in threads (build_parallel!): recording variables, the two-stage commit and the look-up of
            # every variable family (with one thread at compile time the tasks run one after another; the code is the same)
            build(load(db); parallel = true)
        catch e
            @warn "TimesEq precompile workload failed; the package is built, less is compiled ahead" exception = (e, catch_backtrace())
        end
        GC.gc(); GC.gc()
        try
            rm(tmp; recursive = true, force = true)
        catch
        end
    end
end
function __init__()
    ARRAY_ROWS[] = get(ENV, "TIMESEQ_ARRAY_ROWS", "1") != "0"      # lx.jl: 0 builds every row through JuMP expressions
end

# a SENSIS build: the deterministic variables with a SOW context; its families are those of a deterministic build
# (build_parallel!), the labels of the stochastic objective rows are added first
precompile(sow_labels!, (Model{VarsT},))
precompile(load, (String,))
for n in 0:8
    precompile(read_set, (SQLite.DB, String, Labels, Val{n}))
    precompile(read_par, (SQLite.DB, String, Labels, Symbol, Val{n}))
    precompile(read_bounds, (SQLite.DB, String, Labels, Val{n}))
    precompile(key, (Labels, SQLite.Row{false}, Val{n}))
end

end # module
