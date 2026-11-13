# SPDX-License-Identifier: GPL-3.0-or-later
# The run of one case for TIMES.py: load, build, compare with GAMS, solve, write the result and the solution.
# Called by the runner's Julia script; part of the package so that it is precompiled (see the workload in TimesEq.jl).
module RunCase

using JuMP, HiGHS, Profile
import ..TimesEq

# Where the time of a run goes, phase by phase: wall seconds, the part of them Julia spent compiling, garbage
# collection, and memory allocated. Written into the result file as "phases", with "using_seconds" (loading the
# packages), "script_seconds" (all of this script), "maxrss_gb" (peak memory of the process) and "maxrss_build_gb"
# (peak memory up to the built model, before the comparisons and the solve).
const PHASES = Dict{String,Dict{String,Float64}}()
const MAIN_ENTERED = Ref(0.0)                 # when run_case starts: the time before it is the script being compiled
const T_SCRIPT = Ref(0.0)                     # when the script started (passed in by the script)
const USING_SECONDS = Ref(0.0)                # loading the packages, measured by the script
const EARLY_SECONDS = Ref(0.0)                # the same, when it was done before the run (the script's --wait)

"""CPU seconds (user and system, all threads) the process has used so far; NaN where it cannot be read.
Divided by the wall seconds of a phase, it is the number of cores the phase kept busy on average."""
function process_cpu_seconds()
    try
        if Sys.iswindows()
            h = ccall((:GetCurrentProcess, "kernel32"), stdcall, Ptr{Cvoid}, ())
            c = Ref{UInt64}(0); e = Ref{UInt64}(0); k = Ref{UInt64}(0); u = Ref{UInt64}(0)
            ok = ccall((:GetProcessTimes, "kernel32"), stdcall, Cint,
                (Ptr{Cvoid}, Ref{UInt64}, Ref{UInt64}, Ref{UInt64}, Ref{UInt64}), h, c, e, k, u)
            return ok == 0 ? NaN : (k[] + u[]) / 1e7          # 100 ns units
        else
            ru = zeros(Int64, 18)                            # struct rusage: ru_utime, ru_stime (timeval) first
            ccall(:getrusage, Cint, (Cint, Ptr{Int64}), 0, ru) == 0 || return NaN
            return ru[1] + ru[2] / 1e6 + ru[3] + ru[4] / 1e6
        end
    catch
        return NaN
    end
end

"""Run `f` as phase `name` and add its timings to PHASES. Returns the value of `f` and its wall seconds."""
function timed(f, name)
    Base.cumulative_compile_timing(true)
    c0 = Base.cumulative_compile_time_ns()[1]
    u0 = process_cpu_seconds()
    s = @timed f()
    u1 = process_cpu_seconds()
    c1 = Base.cumulative_compile_time_ns()[1]
    Base.cumulative_compile_timing(false)
    p = get!(() -> Dict("seconds" => 0.0, "cpu_seconds" => 0.0, "compile_seconds" => 0.0, "gc_seconds" => 0.0, "alloc_gb" => 0.0), PHASES, name)
    p["seconds"] += s.time
    p["cpu_seconds"] += isnan(u1 - u0) ? 0.0 : u1 - u0
    p["compile_seconds"] += (c1 - c0) / 1e9
    p["gc_seconds"] += s.gctime
    p["alloc_gb"] += s.bytes / 2^30
    return s.value, s.time
end

"""The timings so far, rounded, into the result."""
function note_timings!(res)
    res["phases"] = Dict(k => Dict(n => round(v; digits = n == "alloc_gb" ? 2 : 1) for (n, v) in p) for (k, p) in PHASES)
    res["using_seconds"] = round(USING_SECONDS[]; digits = 1)
    EARLY_SECONDS[] > 0 && (res["using_seconds_early"] = round(EARLY_SECONDS[]; digits = 1))
    res["script_seconds"] = round(time() - T_SCRIPT[]; digits = 1)
    res["maxrss_gb"] = round(Sys.maxrss() / 2^30; digits = 2)
    MAIN_ENTERED[] > 0 && (res["before_main_seconds"] = round(MAIN_ENTERED[] - T_SCRIPT[] - USING_SECONDS[]; digits = 1))
end

json(io, x::Nothing) = print(io, "null")
json(io, x::Bool) = print(io, x)
json(io, x::Integer) = print(io, x)
json(io, x::AbstractFloat) = isfinite(x) ? print(io, x) : print(io, "null")
json(io, x::Union{AbstractString,Symbol}) = (print(io, '"'); for c in String(x)
        c == '"' ? print(io, "\\\"") : c == '\\' ? print(io, "\\\\") : c == '\n' ? print(io, "\\n") : c == '\t' ? print(io, "\\t") : c < ' ' ? print(io, ' ') : print(io, c)
    end; print(io, '"'))
json(io, x::Union{AbstractVector,Tuple}) = (print(io, '['); for (i, y) in enumerate(x); i > 1 && print(io, ','); json(io, y); end; print(io, ']'))
json(io, x::Pair) = json(io, [x.first, x.second])
function json(io, x::Union{AbstractDict,NamedTuple})
    print(io, '{')
    for (i, (k, v)) in enumerate(pairs(x))
        i > 1 && print(io, ",\n")
        json(io, String(k)); print(io, ": "); json(io, v)
    end
    print(io, '}')
end

message(e) = first(sprint(showerror, e), 2000)

# --profile: samples of the table load and the equation build. Empty means off.
# The comparison and the HiGHS solve are not wrapped, so they stay out of the profile.
const PROFILE_MODE = Ref("")
const PROFILE_OUT = Ref("")
const PROFILE_WRITTEN = Ref(false)

"""Run `f` under the sampler when --profile is on. The result of `f` is returned either way."""
function prof(f)
    mode = PROFILE_MODE[]
    mode == "" && return f()
    mode == "cpu" && return Profile.@profile f()
    return Profile.Allocs.@profile sample_rate=0.01 f()
end

function start_profile(mode, path)
    mode in ("cpu", "allocs") || error("--profile is cpu or allocs, got \"$mode\"")
    path == "" && error("--profile-out is required with --profile")
    PROFILE_MODE[] = mode
    PROFILE_OUT[] = path
    if mode == "cpu"
        # one sample every 10 ms: at 1 ms the sampler crashed Julia on Windows during a large build (an access
        # violation in RtlVirtualUnwind while it walked the stack of freshly compiled code)
        Profile.init(n = 10_000_000, delay = 0.01)
        Profile.clear()
    else
        Profile.Allocs.clear()
    end
    println("profiling the table load and the equation build (", mode, ")"); flush(stdout)
end

"""Write the samples collected so far. Once per run, so a later comparison is not added and a failure still leaves the file."""
function write_profile()
    PROFILE_WRITTEN[] && return
    mode, path = PROFILE_MODE[], PROFILE_OUT[]
    (mode == "" || path == "") && return
    open(path, "w") do io
        println(io, "Julia $(VERSION)  $(mode) profile of the table load and the equation build")
        println(io, "The matrix comparison and the HiGHS solve are not in this profile.")
        if mode == "cpu"
            println(io, "Each count is one sample, taken about every 10 ms.")
            println(io, "The flat list is shortest count first: the lines just above \"Total snapshots\" are where the time went.")
            println(io)
            println(io, "---- where the time went (flat) ----")
            Profile.print(IOContext(io, :displaysize => (10^6, 220)); format = :flat, mincount = 5, sortedby = :count)
            println(io, "\n---- call tree ----")
            Profile.print(IOContext(io, :displaysize => (10^6, 220)); maxdepth = 25, mincount = 20, sortedby = :count)
        else
            println(io, "One allocation in 100 was recorded (sample_rate 0.01).")
            println(io)
            Profile.Allocs.print(io; format = :flat, mincount = 5)
        end
    end
    PROFILE_WRITTEN[] = true
    println("profile: ", path); flush(stdout)
end

function note_profile(res)
    write_profile()
    PROFILE_WRITTEN[] || return
    res["profile"] = PROFILE_OUT[]
    res["profile_mode"] = PROFILE_MODE[]
end

const INTERIOR = ("ipm", "hipo", "ipx")

"""The --highs-option name=value pairs of the command line, each converted to the type HiGHS has for that option."""
function highs_options(args)
    out = Pair{String,Any}[]
    h = HiGHS.Highs_create()
    try
        for (i, a) in enumerate(args)
            a == "--highs-option" && i < length(args) || continue
            kv = args[i+1]
            occursin('=', kv) || error("--highs-option needs name=value, got \"$kv\"")
            name, val = String.(strip.(split(kv, '='; limit = 2)))      # a String, not a SubString: HiGHS reads it as a C string
            t = Ref{Cint}(0)
            HiGHS.Highs_getOptionType(h, name, t) == 0 || error("HiGHS has no option \"$name\"")
            v = t[] == 0 ? lowercase(val) in ("true", "on", "1") : t[] == 1 ? parse(Int, val) : t[] == 2 ? parse(Float64, val) : String(val)
            push!(out, String(name) => v)
        end
    finally
        HiGHS.Highs_destroy(h)
    end
    return out
end

"""
The solver settings of a run on the JuMP model `jm`: the method (auto: simplex up to 150,000 rows, the interior point code
ipx above; an interior point solve without crossover), the threads, then the user's HiGHS options, which come last and win.
Returns the method used and the settings applied.
"""
# HiGHS 1.15 (highs/ipm/hipo/ipm/Solver.cpp, setOptions): HiPO writes no log at all, not even to log_file, when
# log_to_console is off. For HiPO the console stays on, so its iteration table reaches highs.log (and julia.log).
quiet_console(solver) = !(solver in ("hipo", "ipm"))

function configure_highs!(jm, solver, threads, extra; rows = num_constraints(jm; count_variable_in_set_constraints = false))
    s = solver == "auto" ? (rows > 150_000 ? "ipx" : "simplex") : solver
    applied = Pair{String,Any}[]
    if s in INTERIOR
        push!(applied, "solver" => s, "run_crossover" => "off")
    elseif s == "simplex"
        push!(applied, "solver" => "simplex")
    end
    threads > 0 && push!(applied, "threads" => threads)
    append!(applied, extra)
    for (k, v) in applied
        set_attribute(jm, k, v)
    end
    # HiGHS.jl installs, before each solve without a user callback, a Julia callback on the simplex, ipx and MIP
    # interrupt events so that Ctrl-C can stop HiGHS: a call into Julia at every check (78,311 in one solve, which made
    # it much slower than through the C API). A user callback with no events replaces it: HiGHS never calls back into
    # Julia.
    # Ctrl-C then waits until HiGHS returns; --time-limit still stops it.
    set_attribute(jm, HiGHS.CallbackFunction(Cint[]), (_, _, _) -> Cint(0))
    # On an infeasible model HiGHS.jl asks for a dual ray, which solves the unpresolved LP again (on a large model, the
    # whole time limit); nothing here uses the ray.
    set_attribute(jm, HiGHS.ComputeInfeasibilityCertificate(), false)
    for (k, v) in extra                                           # a user option may change the method
        k == "solver" && (s = String(v))
    end
    return s, applied
end

"""
A SENSIS run (`\$SET SENSIS YES`): one deterministic model for each SOW distinct in the first period, built and solved
one after the other as TIMES does (solve.stc 35-52, `TimesEq.sensis_sows`). Each is a "step" of the result (its size,
and with a solve its objective), compared with the solves of the GAMS listing in order. --matrix-out <folder>: the
matrix of the first solve (GAMS's run with CONVERT stops after its first solve: the matrix check is of that one). Solved with HiGHS, or with --lp <solver> by that LP solver of the user's GAMS
(GamsLP.Optimizer), each in its own work folder (gamslp/sow_<w>).
"""
function sensis_run(d, res, opt, args, save)
    res["stage"] = "sensis"
    save()
    lp = lowercase(opt("--lp", "highs"))
    lp == "gurobipy" && (lp = "gurobi")
    res["steps"] = Any[]
    mout = opt("--matrix-out", "")
    solve = !("--no-solve" in args)
    for (k, w) in enumerate(TimesEq.sensis_sows(d))
        lab = TimesEq.label(d.L, w)
        TimesEq.SENS_W[] = w
        m, tb = timed(() -> prof(() -> TimesEq.build(d)), "build")
        e = Dict{String,Any}("step" => k, "year" => 0, "window" => "SOW " * lab, "sow" => lab,
            "rows" => sum(values(TimesEq.row_counts(m)); init = 0), "columns" => num_variables(m.jump),
            "nonzeros" => TimesEq.nonzeros(m), "build_seconds" => round(tb; digits = 1))
        if solve
            if lp == "highs"
                TimesEq.use_highs!(m.jump)                 # HiGHS without the bridge layer, as a run of one solve
                s, applied = configure_highs!(m.jump, opt("--solver", "auto"), parse(Int, opt("--threads", "0")), highs_options(args); rows = e["rows"])
                res["highs_options"] = Dict(applied)
                limit = parse(Float64, opt("--time-limit", "0"))
                limit > 0 && set_time_limit_sec(m.jump, limit)
                TimesEq.attach_highs!(m.jump)
                res["solver"] = "HiGHS " * s
            else
                kw = gamslp_options(lp, opt, args)
                workdir = joinpath(opt("--lp-work", joinpath(dirname(abspath(args[2])), "gamslp")), "sow_" * lab)
                o = TimesEq.GamsLP.Optimizer(; kw..., workdir, names = "", name_rows = MOI.ConstraintIndex[])
                TimesEq.discrete_for_solve!(m.jump)
                JuMP.set_optimizer(m.jump, () -> o; add_bridges = false)
                res["solver"] = uppercase(lp) * (o.direct == "" ? " through GAMS" : " through Python")
            end
            _, ts = timed(() -> optimize!(m.jump), "solve")
            st = termination_status(m.jump)
            e["status"] = string(st)
            e["objective"] = st == OPTIMAL ? objective_value(m.jump) : nothing
            e["solve_seconds"] = round(ts; digits = 1)
            # --solution <file>: the solution of each solve in <file without extension>~<w><extension>, which the report
            # of the run reads SOW by SOW (times_rpt stochastic.sensis_solution)
            sfile = opt("--solution", "")
            if sfile != "" && e["objective"] !== nothing
                b, x = splitext(sfile)
                sol = TimesEq.record!(TimesEq.Solution(d.L), m; info = Dict{String,Any}("step" => k, "year" => 0, "window" => "SOW " * lab,
                    "rows" => e["rows"], "columns" => e["columns"], "nonzeros" => e["nonzeros"], "status" => e["status"],
                    "objective" => e["objective"], "seconds" => e["solve_seconds"]))
                TimesEq.write_solution(b * "~" * lab * x, sol)
                e["solution_file"] = b * "~" * lab * x
            end
        end
        (mout == "" || k > 1) || (res["matrix_out"] = e["matrix_out"] = TimesEq.write_matrix(m, mout))
        push!(res["steps"], e)
        println("SOW ", lab, ": rows ", e["rows"], "  columns ", e["columns"], "  nonzeros ", e["nonzeros"],
                solve ? string("  ", e["status"], "  objective ", e["objective"]) : "", "  (", e["build_seconds"], " s)"); flush(stdout)
        save()
    end
    TimesEq.SENS_W[] = TimesEq.Id(0)
    last = res["steps"][end]
    res["rows"], res["columns"], res["nonzeros"] = last["rows"], last["columns"], last["nonzeros"]
    res["build_seconds"] = round(sum(s["build_seconds"] for s in res["steps"]); digits = 1)
    if solve
        res["solve_seconds"] = round(sum(s["solve_seconds"] for s in res["steps"]); digits = 1)
        res["objective"] = last["objective"]
        res["optimal_proved"] = all(s["status"] == "OPTIMAL" for s in res["steps"])
        res["termination"] = last["status"]
    end
    note_profile(res)
end

"""
A myopic run (TIMESTEP): the steps one after the other, each fixed outside its window at the solution of the
steps before; the merged solution is written with --solution, and compared with the GAMS solution (--gams). With
--lp <solver>, each step is solved by that LP solver of the user's GAMS (GamsLP.Optimizer, as one solve is).
"""
function myopic(d, res, opt, args, save)
    res["stage"] = "steps"
    save()
    if "--no-solve" in args
        # the models of the steps are built (and checked against GAMS by the step size in the listing) without the solver:
        # a step outside the first can then only be fixed at zero levels; a run with FIXBOH is fixed at its loaded point
        # and relaxed, as solve_steps does
        res["steps"] = Any[]
        sol = TimesEq.Solution(d.L)
        R = nothing
        built = nothing
        timed("steps") do
            for (k, yr) in TimesEq.steps(d.source)
                ds = TimesEq.load_step(d, k)
                R === nothing && (R = TimesEq.Relax(ds))
                m = built = prof(() -> TimesEq.build(ds))
                pt = TimesEq.load_point(d, k)
                lev = isempty(pt) ? sol : pt
                TimesEq.fix_window!(m, lev)
                TimesEq.relax!(R, m, lev)
                TimesEq.apply_relax!(R, m)
                push!(res["steps"], Dict("step" => k, "year" => yr, "rows" => sum(values(TimesEq.row_counts(m)); init = 0),
                    "columns" => num_variables(m.jump), "nonzeros" => TimesEq.nonzeros(m)))
                TimesEq.reset_capacity!(R, m)       # as solve_steps does after each step: the next step starts from its own bounds
            end
        end
        last = res["steps"][end]
        res["rows"], res["columns"], res["nonzeros"] = last["rows"], last["columns"], last["nonzeros"]
        # a run with FIXBOH is one model (one step): its matrix for the check, as the solving path below writes it
        mout = opt("--matrix-out", "")
        if mout != "" && length(res["steps"]) == 1 && built !== nothing
            res["matrix_out"], t = timed(() -> TimesEq.write_matrix(built, mout), "matrix out")
            res["matrix_out_seconds"] = round(t; digits = 1)
            println("matrix written for the check: ", res["matrix_out"], " (", res["matrix_out_seconds"], " s)"); flush(stdout)
        end
        note_profile(res)
        return
    end
    lp = lowercase(opt("--lp", "highs"))
    solver = opt("--solver", "auto")
    limit = parse(Float64, opt("--time-limit", "0"))
    hlog = opt("--highs-log", "")
    threads = parse(Int, opt("--threads", "0"))
    extra = highs_options(args)
    used = Ref("")
    function configure(jm)
        s, applied = configure_highs!(jm, solver, threads, extra)
        used[] = s
        res["highs_options"] = Dict(applied)
        hlog == "" || (set_attribute(jm, "log_file", hlog); set_attribute(jm, "log_to_console", !quiet_console(s)))
        limit > 0 && set_time_limit_sec(jm, limit)
    end
    # as for a run without steps: HiGHS has two interior point codes; when the newer one (HiPO) ends without a solution,
    # the step is solved again with ipx
    function retry(jm)
        st = termination_status(jm)
        (used[] in ("ipm", "hipo") && st != OPTIMAL && !(st in (INFEASIBLE, DUAL_INFEASIBLE, TIME_LIMIT))) || return false
        println("  HiGHS ", used[], " ended with ", st, "; the step is solved again with ipx"); flush(stdout)
        set_attribute(jm, "solver", "ipx"); used[] = "ipx"
        return true
    end
    # --lp <solver>: each step solved by the LP solver of the user's GAMS (GamsLP.Optimizer), in its own work folder
    # (gamslp/step<k>) with its own GAMS log (gamslp_step<k>.log); what each solve did goes into the step's info
    optimizer, lps, kwlp = HiGHS.Optimizer, TimesEq.GamsLP.Optimizer[], ""
    if lp != "highs"
        kwlp = lp
        kw = gamslp_options(lp, opt, args)
        base = opt("--lp-work", joinpath(dirname(abspath(args[2])), "gamslp"))
        "--lp-names" in args && (res["lp_names"] = "--lp-names ignored: a myopic run gives GAMS each step by number"; println(res["lp_names"]))
        function step_optimizer()
            k = length(lps) + 1
            b, e = splitext(kw.log)
            log = kw.log == "" ? "" : b * "_step$k" * e
            push!(lps, TimesEq.GamsLP.Optimizer(; kw..., workdir = joinpath(base, "step$k"), log))
            return lps[end]
        end
        optimizer = step_optimizer
        println("solving each step with ", uppercase(kw.solver), kw.direct == "" ? " through GAMS (" * kw.gams * ")" : " through Python (gurobipy)"); flush(stdout)
    end
    println("a myopic run: ", length(TimesEq.steps(d.source)), " steps (", Libc.strftime("%H:%M:%S", time()), ")"); flush(stdout)
    function progress(info, m)
        isempty(lps) || (info["gamslp"] = Dict{String,Any}(k => v isa AbstractFloat ? round(v; digits = 2) : v for (k, v) in lps[end].info))
        println("  step ", info["step"], " (", info["window"], "): rows ", info["rows"], "  columns ", info["columns"], "  nonzeros ", info["nonzeros"],
            "  ", info["status"], "  objective ", info["objective"], "  (", info["seconds"], " s)")
        flush(stdout)
    end
    say(msg) = (println("  ", Libc.strftime("%H:%M:%S", time()), "  ", msg); flush(stdout))
    # as for a run without steps: an interior point solve without crossover that ends "imprecise" with a feasible point
    accept(jm) = termination_status(jm) == OPTIMAL ||
        (termination_status(jm) in (OTHER_ERROR, ALMOST_OPTIMAL) && primal_status(jm) in (FEASIBLE_POINT, NEARLY_FEASIBLE_POINT))
    (sol, m), t = timed(() -> TimesEq.solve_steps(d, optimizer; progress, say, accept,
        configure = isempty(kwlp) ? configure : jm -> nothing, retry = isempty(kwlp) ? retry : jm -> false,
        make = (ds; progress) -> prof(() -> TimesEq.build(ds; progress))), "steps")
    note_profile(res)
    res["steps"] = sol.steps
    last = sol.steps[end]
    res["rows"], res["columns"], res["nonzeros"] = last["rows"], last["columns"], last["nonzeros"]
    res["row_counts"] = Dict(String(k) => v for (k, v) in TimesEq.row_counts(m))
    res["solver"] = "HiGHS " * (used[] == "" ? solver : used[])
    isempty(lps) || gamslp_steps!(res, lps)
    res["build_seconds"] = round(sum(s["build_seconds"] for s in sol.steps); digits = 1)
    res["solve_seconds"] = round(sum(s["solve_seconds"] for s in sol.steps); digits = 1)
    res["cpu_threads"] = Sys.CPU_THREADS
    res["termination"] = last["status"]
    res["objective"] = last["objective"]
    complete = length(sol.steps) == length(TimesEq.steps(d.source)) && all(s["objective"] !== nothing for s in sol.steps)
    res["optimal_proved"] = complete && all(s["status"] == "OPTIMAL" for s in sol.steps)
    # a run with FIXBOH is one model (one step): its matrix for the check, as for a run without steps (--matrix-out)
    mout = opt("--matrix-out", "")
    if mout != "" && length(sol.steps) == 1 && m !== nothing
        res["matrix_out"], t = timed(() -> TimesEq.write_matrix(m, mout), "matrix out")
        res["matrix_out_seconds"] = round(t; digits = 1)
        say("matrix written for the check: $(res["matrix_out"])")
    end
    sfile = opt("--solution", "")
    if sfile != ""
        say("writing the solution file")
        timed(() -> TimesEq.write_solution(sfile, sol), "solution")
        res["solution_file"] = sfile
    end
    gams = opt("--gams", "")
    if gams != "" && complete
        res["stage"] = "compare"
        save()
        say("comparing the merged solution with GAMS")
        res["compare_steps"], _ = timed(() -> TimesEq.compare_solution(sol, gams), "compare")
    end
    say("done")
end

"""The keywords of GamsLP.Optimizer from the runner's options (--gams-exe, --lp-optfile, --solver-option, --python,
--lp-log, --keep, --threads, --time-limit); `lp` is GAMS's LP= ("gurobipy": Gurobi through Python, without GAMS)."""
function gamslp_options(lp, opt, args)
    direct = lp == "gurobipy" ? joinpath(@__DIR__, "..", "solvers", "gurobilp.py") : ""
    return (; direct, gams = opt("--gams-exe", "gams"), solver = lp == "gurobipy" ? "gurobi" : lp, optfile = opt("--lp-optfile", ""),
            options = [args[i+1] for i in 1:length(args)-1 if args[i] == "--solver-option"],
            python = opt("--python", get(ENV, "TIMES_PYTHON", "python")), log = opt("--lp-log", ""), keep = "--keep" in args,
            threads = parse(Int, opt("--threads", "0")), time_limit = parse(Float64, opt("--time-limit", "0")))
end

"""The solver line and the hand-over of a myopic run with --lp, from the optimizer of each step: res["solver"] as for one
solve (the option lines of the last step), res["gamslp"] the seconds and iterations summed over the steps."""
function gamslp_steps!(res, lps)
    info = lps[end].info
    opts = isempty(get(info, "option_lines", String[])) ? "no option file" :
        (lps[end].optfile == "" ? "options" : basename(lps[end].optfile)) * ": " * join(info["option_lines"], ", ")
    res["solver"] = uppercase(lps[end].solver) * (haskey(info, "solver_version") ? " " * info["solver_version"] : "") *
        (lps[end].direct == "" ? " through GAMS" : " through Python") * (haskey(info, "gams_version") ? " " * info["gams_version"] : "") *
        " (" * opts * (length(lps) == 1 ? "" : "; " * string(length(lps)) * " steps") * ")"
    g = Dict{String,Any}(k => v for (k, v) in info if !(v isa Real))
    for o in lps, (k, v) in o.info
        (v isa Real && !(k in ("modelstat", "solvestat"))) && (g[k] = get(g, k, 0) + v)
    end
    flagged = [string("step ", i, ": ", o.info["infeasibility"]) for (i, o) in enumerate(lps) if haskey(o.info, "infeasibility")]
    isempty(flagged) || (g["infeasibility"] = join(flagged, "; "))
    res["gamslp"] = Dict{String,Any}(k => v isa AbstractFloat ? round(v; digits = 2) : v for (k, v) in g)
    res["gamslp"]["steps"] = length(lps)
    res["iterations"] = get(g, "iterations", 0)
end

"""
--lp <solver>: the model solved by an LP solver of the user's GAMS (GamsLP.Optimizer): the LP to a GDX, GAMS solves it,
the solution read back; then as after a HiGHS solve. The option file is the run folder's <solver>.opt (--lp-optfile)
with the --solver-option lines after it; the GAMS log goes to --lp-log and to the console.
--lp-names (with --keep): GAMS gets the model by TIMES's names (lp_names.gms in the work folder), from the matrix as
write_matrix writes it (into --matrix-out when given, which is then not written again after the solve; else into a
folder beside the work folder, removed after the solve); without --keep it is ignored (the work folder, and so the
listing, is removed after the solve).
"""
function solve_gams!(m, d, res, lp, opt, args)
    kw = gamslp_options(lp, opt, args)
    direct = kw.direct
    lp == "gurobipy" && (lp = "gurobi")
    workdir = opt("--lp-work", joinpath(dirname(abspath(args[2])), "gamslp"))
    keep = "--keep" in args
    names = ""
    if "--lp-names" in args
        if !keep || direct != ""
            res["lp_names"] = "--lp-names ignored: " * (direct != "" ? "Gurobi through Python does not use GAMS" :
                "it needs --keep (without it the GAMS work folder, and so its listing, is removed after the solve)")
            println(res["lp_names"])
        else
            names = opt("--matrix-out", workdir * "_names")
            res["stage"] = "matrix out"
            res["matrix_out"], t = timed(() -> TimesEq.write_matrix(m, names), "matrix out")
            res["matrix_out_seconds"] = round(t; digits = 1)
            println("matrix written for the names of the GAMS model: ", res["matrix_out"], " (", res["matrix_out_seconds"], " s)"); flush(stdout)
            res["stage"] = "solve"
        end
    end
    o = TimesEq.GamsLP.Optimizer(; kw..., workdir, names, name_rows = names == "" ? MOI.ConstraintIndex[] : TimesEq.matrix_rows(m))
    timed("solver setup") do
        TimesEq.discrete_for_solve!(m.jump)          # the variable types of the DSC extension: GamsLP stops on them
        JuMP.set_optimizer(m.jump, () -> o; add_bridges = false)
    end
    println("solving with ", uppercase(lp), o.direct == "" ? " through GAMS (" * o.gams * "), " : " through Python (gurobipy), ", res["rows"], " rows ..."); flush(stdout)
    TimesEq.release_db3()
    res["solve_started_unix"] = time()
    _, t = timed(() -> optimize!(m.jump), "solve")
    info = o.info
    opts = isempty(info["option_lines"]) ? "no option file" :
        (o.optfile == "" ? "options" : basename(o.optfile)) * ": " * join(info["option_lines"], ", ")
    res["solver"] = uppercase(lp) * (haskey(info, "solver_version") ? " " * info["solver_version"] : "") * (o.direct == "" ? " through GAMS" : " through Python") *
        (haskey(info, "gams_version") ? " " * info["gams_version"] : "") * " (" * opts * ")"
    haskey(info, "options_skipped") && println("option lines not applied (not parameters of ", uppercase(lp), "): ", join(info["options_skipped"], ", "))
    res["gamslp"] = Dict{String,Any}(k => v isa AbstractFloat ? round(v; digits = 2) : v for (k, v) in info)
    res["gamslp"]["optimize_seconds"] = round(t; digits = 2)
    if names != ""
        names == opt("--matrix-out", "") || rm(names; recursive = true, force = true)
        res["lp_names"] = "the GAMS model by TIMES's names: " * info["listing"] * " (its program lp_names.gms, data named.gdx)"
        println(res["lp_names"])
    end
    res["solve_seconds"] = round(t; digits = 1)
    res["iterations"] = info["iterations"]
    res["termination"] = string(termination_status(m.jump))
    res["raw_status"] = JuMP.raw_status(m.jump)
    proved = termination_status(m.jump) == OPTIMAL
    point = primal_status(m.jump) == FEASIBLE_POINT
    res["objective"] = point ? objective_value(m.jump) : nothing
    res["optimal_proved"] = proved
    sfile = opt("--solution", "")
    if point && sfile != ""
        sol, _ = timed(() -> TimesEq.record!(TimesEq.Solution(d.L), m; info = Dict{String,Any}("step" => 0, "year" => 0, "window" => "",
            "rows" => res["rows"], "columns" => res["columns"], "nonzeros" => res["nonzeros"], "status" => res["termination"],
            "objective" => res["objective"], "seconds" => res["solve_seconds"])), "solution")
        timed(() -> TimesEq.write_solution(sfile, sol), "solution file")
        res["solution_file"] = sfile
    end
    println("
solve: ", res["termination"], "  objective ", res["objective"], "  (", res["solve_seconds"], " s; ", res["solver"], ")")
end

"""
    run_case(args; t_script = time(), using_seconds = 0.0, early_seconds = 0.0) -> exit status

What the runner's Julia script does, as a function of the package so that it is compiled with it (the precompile workload
runs it on a small model). `args` as on the command line of the script. 0 when every stage ran, 1 otherwise.
early_seconds: the packages' loading, when the script did it before the run was asked for (its --wait).
"""
function run_case(args; t_script = time(), using_seconds = 0.0, early_seconds = 0.0)
    empty!(PHASES); PROFILE_MODE[] = ""; PROFILE_OUT[] = ""; PROFILE_WRITTEN[] = false
    T_SCRIPT[] = t_script; USING_SECONDS[] = using_seconds; EARLY_SECONDS[] = early_seconds
    MAIN_ENTERED[] = time()
    file, out = args[1], args[2]
    opt(name, default) = (i = findfirst(==(name), args); i === nothing ? default : args[i+1])
    res = Dict{String,Any}("file" => file, "julia" => string(VERSION), "threads" => Threads.nthreads(), "stage" => "load")
    save() = (note_timings!(res); timed(() -> open(io -> json(io, res), out, "w"), "result file"); nothing)
    mode = opt("--profile", "")
    mode == "" || start_profile(mode, opt("--profile-out", ""))
    try
        d, t = timed(() -> prof(() -> TimesEq.load(file)), "load")
        res["load_seconds"] = round(t; digits = 1)
        println("tables read  (", res["load_seconds"], " s, ", Libc.strftime("%H:%M:%S", time()), ")"); flush(stdout)
        res["unsupported"], _ = timed(() -> [(what = w, tables = String.(n)) for (w, n) in TimesEq.unsupported(d)], "checks")
        stepwise, _ = timed(() -> !isempty(TimesEq.steps(file)), "checks")
        if stepwise
            myopic(d, res, opt, args, save)
            res["stage"] = "done"
            save()
            return 0
        end
        if TimesEq.sensis(d)
            sensis_run(d, res, opt, args, save)
            res["stage"] = "done"
            save()
            return 0
        end
        res["stage"] = "build"
        save()
        step(name, sec, m) = (println("  ", Libc.strftime("%H:%M:%S", time()), "  ", rpad(name, 14), lpad(round(sec; digits = 1), 8), " s   rows so far ", sum(length(r.refs) for r in values(m.rows); init = 0)); flush(stdout))
        println("writing the equations, one family after another:"); flush(stdout)
        m, t = timed(() -> prof(() -> TimesEq.build(d; progress = step)), "build")
        res["build_seconds"] = round(t; digits = 1)
        timed("counts") do
            res["rows"] = sum(values(TimesEq.row_counts(m)); init = 0)
            res["columns"] = num_variables(m.jump)
            res["nonzeros"] = TimesEq.nonzeros(m)
            res["row_counts"] = Dict(String(k) => v for (k, v) in TimesEq.row_counts(m))
            res["column_counts"] = Dict(String(k) => v for (k, v) in TimesEq.column_counts(m))
        end
        # the peak memory of the process up to the built model, before the comparisons with GAMS (which need the GAMS
        # matrix in memory beside the model) and the solve: what running the model costs, without the checks
        res["maxrss_build_gb"] = round(Sys.maxrss() / 2^30; digits = 2)
        println("built: rows ", res["rows"], "  columns ", res["columns"], "  nonzeros ", res["nonzeros"], "  (", res["build_seconds"], " s)"); flush(stdout)
        note_profile(res)
        gams = opt("--gams", "")
        if gams != ""
            res["stage"] = "compare"
            save()
            println("comparing with the GAMS model and solution ..."); flush(stdout)
            res["compare"], t = timed(() -> TimesEq.compare_gams(m, d, gams), "compare")
            flush(stdout)
            res["compare_seconds"] = round(t; digits = 1)
        end
        jac = opt("--matrix", "")
        if jac != ""
            res["stage"] = "matrix"
            save()
            println("comparing the matrix with the one GAMS generated ..."); flush(stdout)
            res["matrix"], t = timed(() -> TimesEq.compare_matrix(m, d, jac), "matrix")
            res["matrix_seconds"] = round(t; digits = 1)
            flush(stdout)
        end
        # above --max-solve-rows (default 2,000,000) HiGHS is not tried unless --solve says so: the model is checked against
        # GAMS by its matrix (check 4); solving a model that size is for a commercial solver
        limit = parse(Float64, opt("--max-solve-rows", "2000000"))
        lp = lowercase(opt("--lp", "highs"))
        if !("--no-solve" in args) && lp != "highs"
            res["stage"] = "solve"
            save()
            solve_gams!(m, d, res, lp, opt, args)
        elseif !("--no-solve" in args) && !("--solve" in args) && res["rows"] > limit
            res["solve_skipped"] = "the model has $(res["rows"]) rows, more than $(Int(limit)): HiGHS is not tried (--solve to try anyway)"
            println("\nnot solved: ", res["solve_skipped"]); flush(stdout)
        elseif !("--no-solve" in args)
            res["stage"] = "solve"
            save()
            # interior point without crossover for models too large for the simplex; --threads and --highs-option on top
            (solver, applied), _ = timed("solver setup") do
                TimesEq.use_highs!(m.jump)
                configure_highs!(m.jump, opt("--solver", "auto"), parse(Int, opt("--threads", "0")), highs_options(args); rows = res["rows"])
            end
            res["highs_options"] = Dict(applied)
            hlog = opt("--highs-log", "")                    # the solver log in a file as well: it can be followed while the solve runs
            hlog == "" || (set_attribute(m.jump, "log_file", hlog); set_attribute(m.jump, "log_to_console", !quiet_console(solver)))
            println("solving with HiGHS (", solver, "), ", res["rows"], " rows ..."); flush(stdout)
            limit = parse(Float64, opt("--time-limit", "0"))
            limit > 0 && set_time_limit_sec(m.jump, limit)
            # JuMP keeps its own copy of the model and copies it into HiGHS at optimize!: done here first, in one call
            # (highs.jl), and timed apart
            res["highs_copy"] = string(timed(() -> TimesEq.attach_highs!(m.jump), "copy to HiGHS")[1])
            TimesEq.release_db3()
            # the moment HiGHS starts (Unix seconds): the runner's "to the solver". highs.log is opened when log_file is
            # set, before the copy, so its creation time is not that moment
            res["solve_started_unix"] = time()
            _, t = timed(() -> optimize!(m.jump), "solve")
            if solver in ("ipm", "hipo") && termination_status(m.jump) != OPTIMAL && !(termination_status(m.jump) in (INFEASIBLE, DUAL_INFEASIBLE, TIME_LIMIT))
                # HiGHS has two interior point codes; the default one (HiPO) sometimes ends with "no progress": try the other
                res["first_attempt"] = "HiGHS " * solver * " ended with " * string(termination_status(m.jump)) * " after " * string(round(t; digits = 1)) * " s; solved again with ipx"
                println("\n", res["first_attempt"])
                set_attribute(m.jump, "solver", "ipx")
                solver = "ipx"
                t += timed(() -> optimize!(m.jump), "solve")[2]
            end
            # TIMES-MACRO MLF: the Negishi iterations of rpt_ext.mlf, each further LP built again and solved the same way
            if !isempty(d.tables.MLF) && termination_status(m.jump) == OPTIMAL
                function again!(mm)
                    TimesEq.use_highs!(mm.jump)
                    s, _ = configure_highs!(mm.jump, opt("--solver", "auto"), parse(Int, opt("--threads", "0")), highs_options(args); rows = res["rows"])
                    limit > 0 && set_time_limit_sec(mm.jump, limit)
                    TimesEq.attach_highs!(mm.jump)
                    optimize!(mm.jump)
                    st = termination_status(mm.jump)
                    if s in ("ipm", "hipo") && st != OPTIMAL && !(st in (INFEASIBLE, DUAL_INFEASIBLE, TIME_LIMIT))    # as the first solve
                        println("\nHiGHS ", s, " ended with ", st, " in a Negishi iteration; solved again with ipx")
                        set_attribute(mm.jump, "solver", "ipx")
                        optimize!(mm.jump)
                    end
                    termination_status(mm.jump) == OPTIMAL ||
                        error("a Negishi iteration ended with " * string(termination_status(mm.jump)) * ": the iterations stop here")
                end
                (m, its), tn = timed(() -> TimesEq.negishi!(d, m, again!), "negishi")
                t += tn
                res["negishi"] = [Dict(String(k) => v for (k, v) in pairs(it)) for it in its]
                # the loop can end at NITER with the weights still moving (rpt_ext.mlf: LOOP(NITER$DOITER,...)): TIMES goes
                # on with the last LP, and so does this; the report says so
                res["negishi_converged"] = isempty(its) || !its[end].solve_again
                isempty(its) || (res["negishi_last"] = Dict("iterations" => its[end].iteration, "gap" => its[end].gap, "tolerance" => its[end].tolerance))
                for it in its
                    println("Negishi iteration ", it.iteration, ": gap ", it.gap, ", tolerance ", it.tolerance,
                            it.solve_again ? ": solved again" : ": done")
                end
            end
            res["solver"] = "HiGHS " * solver
            res["solve_seconds"] = round(t; digits = 1)
            res["solve_cpu_seconds"] = round(PHASES["solve"]["cpu_seconds"]; digits = 1)
            res["julia_threads"] = Threads.nthreads()
            res["cpu_threads"] = Sys.CPU_THREADS
            res["termination"] = string(termination_status(m.jump))
            # An interior point solve without crossover can end "imprecise": HiGHS then reports no optimum, but hands back
            # a feasible point. Its objective is an upper bound of the optimum, and is reported as such.
            proved = termination_status(m.jump) == OPTIMAL
            point = proved || (termination_status(m.jump) in (OTHER_ERROR, ALMOST_OPTIMAL) && primal_status(m.jump) in (FEASIBLE_POINT, NEARLY_FEASIBLE_POINT))
            res["objective"] = point ? objective_value(m.jump) : nothing
            res["optimal_proved"] = proved
            sfile = opt("--solution", "")
            if point && sfile != ""
                sol, _ = timed(() -> TimesEq.record!(TimesEq.Solution(d.L), m; info = Dict{String,Any}("step" => 0, "year" => 0, "window" => "",
                    "rows" => res["rows"], "columns" => res["columns"], "nonzeros" => res["nonzeros"], "status" => res["termination"],
                    "objective" => res["objective"], "seconds" => res["solve_seconds"])), "solution")
                timed(() -> TimesEq.write_solution(sfile, sol), "solution file")
                res["solution_file"] = sfile
            end
            println("\nsolve: ", res["termination"], "  objective ", res["objective"], "  (", res["solve_seconds"], " s)")
        end
        # --matrix-out <folder>: the matrix for the check without a second build (write_matrix),
        # written after the solve, so that HiGHS does not start later
        mout = opt("--matrix-out", "")
        if mout != "" && !haskey(res, "matrix_out")       # (written before the solve for --lp-names)
            res["stage"] = "matrix out"
            save()
            res["matrix_out"], t = timed(() -> TimesEq.write_matrix(m, mout), "matrix out")
            res["matrix_out_seconds"] = round(t; digits = 1)
            println("matrix written for the check: ", res["matrix_out"], " (", res["matrix_out_seconds"], " s)"); flush(stdout)
        end
        res["stage"] = "done"
    catch e
        note_profile(res)
        res["error"] = message(e)
        println("\nstopped in stage '", res["stage"], "': ", res["error"])
        e isa ErrorException || Base.showerror(stdout, e, catch_backtrace())
    end
    TimesEq.release_db3()
    save()
    return res["stage"] == "done" ? 0 : 1
end

end # module RunCase
