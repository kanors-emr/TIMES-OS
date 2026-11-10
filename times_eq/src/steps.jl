# SPDX-License-Identifier: GPL-3.0-or-later
"""
Myopic runs (run-file switch TIMESTEP, solve.stp): the model is solved as a sequence of steps, each over a
window of periods. The preprocessor writes the data of every step (`load_step`); here the periods outside the
window are fixed (solve.stp, before each solve):

    periods before the window (BACKWARD):  activities, flows, trade, storage, start-ups, ramping, net and gross
                                           production, new and retired capacity at their level in the solution of
                                           the previous steps (new capacity at least EPS); capacity free
    periods after the window (FORWARD):    activities, flows, storage, net and gross production at zero;
                                           capacity without a lower bound

Levels are kept as TIMES keeps them with SOLVEOPT=MERGE: a column takes the value of the last step that had it.

A run with FIXBOH (solve.stp with REG_FIXT) is one step whose periods up to REG_FIXT(R) are fixed by region (NO_RT, not
BACKWARD) at the levels of an earlier run's solution point, loaded by spoint.mod (`load_point`).
"""
const Levels = Dict{Symbol,Dict{Tuple,Float64}}

level(L::Levels, name::Symbol, k::Tuple) = haskey(L, name) ? get(L[name], k, 0.0) : 0.0

function set_bounds!(x::JuMP.VariableRef, lo::Float64, up::Float64)
    if lo == up
        JuMP.fix(x, lo; force = true)
        return
    end
    JuMP.is_fixed(x) && JuMP.unfix(x)
    isfinite(lo) ? JuMP.set_lower_bound(x, lo) : (JuMP.has_lower_bound(x) && JuMP.delete_lower_bound(x))
    isfinite(up) ? JuMP.set_upper_bound(x, up) : (JuMP.has_upper_bound(x) && JuMP.delete_upper_bound(x))
end
lower(x) = JuMP.is_fixed(x) ? JuMP.fix_value(x) : JuMP.has_lower_bound(x) ? JuMP.lower_bound(x) : -Inf
upper(x) = JuMP.is_fixed(x) ? JuMP.fix_value(x) : JuMP.has_upper_bound(x) ? JuMP.upper_bound(x) : Inf

"""
    fix_window!(m, levels)

Fix the columns of the periods before the window of a step at `levels` (the solution of the previous steps)
and those of the periods after it at zero, as solve.stp does before each solve.
"""
function fix_window!(m::Model, levels)
    m.stepped || return m
    d, K = m.d, m.K
    back, fwd = Set{Id}(d.BACKWARD.rows), m.fwd
    isback = fixed_periods(m)
    bd = (K.LO, K.UP, K.FX)
    fixto(x, v) = JuMP.fix(x, v; force = true)
    function each(f, var, tpos, cond; forward = true)
        for (k, x) in var.x
            t = k[tpos]
            if isback(k[1], t)
                cond(k, true) && fixto(x, f(level(levels, var.name, k)))
            elseif forward && t in fwd
                cond(k, false) && fixto(x, 0.0)
            end
        end
    end
    same = identity
    # activities and flows
    each(same, m.v.VAR_ACT, 3, ((r, v, t, p, s), _) -> (r, p, s) in d.PRC_TS)
    each(same, m.v.VAR_FLO, 3, ((r, v, t, p, c, s), _) -> (r, p, c, s) in d.RPCS_VAR && (r, p) in d.RP_FLO)
    each(same, m.v.VAR_IRE, 3, ((r, v, t, p, c, s, ie), _) -> (r, p, c, s) in d.RPCS_VAR && (r, p, c, ie) in d.RPC_IRE; forward = false)
    each(same, m.v.VAR_SIN, 3, ((r, v, t, p, c, s), _) -> (r, p, c, s) in d.RPCS_VAR && (r, p, c) in d.RPC_STG)
    each(same, m.v.VAR_SOUT, 3, ((r, v, t, p, c, s), _) -> (r, p, c, s) in d.RPCS_VAR && (r, p, c) in d.RPC_STG)
    each(same, m.v.VAR_UPS, 3, ((r, v, t, p, s, l), _) -> l in bd && (r, p, s) in d.RPS_UPS; forward = false)
    # solve.stp 206: VAR_UPT.FX(RTP_VINTYR(R,V,BACKWARD(T),P),S,UPT)$(RPS_UPS(R,P,S)$RP_DP(R,P)) = VAR_UPT.L(R,V,T,P,S,UPT)
    each(same, m.v.VAR_UPT, 3, ((r, v, t, p, s, upt), _) -> (r, p, s) in d.RPS_UPS && (r, p) in d.RP_DP; forward = false)
    each(same, m.v.VAR_UDP, 3, ((r, v, t, p, s, l), _) -> l in bd && (r, p, s) in d.PRC_TS && (r, p, l) in d.RP_UPR; forward = false)
    # commodities: before the window those with a net / gross production variable, after it all tracked ones
    each(same, m.v.VAR_COMNET, 2, ((r, t, c, s), b) -> b ? ((r, t, c) in d.RTC_NET && (r, c, s) in d.COM_TS) : (r, t, c, s) in d.RTCS_VARC)
    each(same, m.v.VAR_COMPRD, 2, ((r, t, c, s), b) -> b ? ((r, t, c) in d.RTC_PRD && (r, c, s) in d.COM_TS) : (r, t, c, s) in d.RTCS_VARC)
    # elastic demands (solve.stp 211, 276): VAR_ELAST.FX(RTC(R,BACKWARD(T),C),S,J,BD)$(COM_TS(R,C,S)$RCJ(R,C,J,BD)), = 0 after the window
    each(same, m.v.VAR_ELAST, 2, ((r, t, c, s, j, bd), _) -> true)
    # capacities
    each(x -> max(0.0, x), m.v.VAR_NCAP, 2, ((r, t, p), _) -> (r, p) in d.RP; forward = false)
    each(same, m.v.VAR_SCAP, 3, ((r, v, t, p), _) -> (r, v, t, p) in d.RTP_CPTYR && (r, p) in d.PRC_RCAP; forward = false)
    for (k, x) in m.v.VAR_CAP.x
        r, t, p = k
        (r, t, p) in d.RTP || continue
        isback(r, t) && set_bounds!(x, 0.0, Inf)
        t in fwd && set_bounds!(x, 0.0, upper(x))
    end
    isempty(d.FIXB_IRE) || relax_trade!(m, levels)
    return m
end

"""The test of a fixed period: (r, t) -> Bool. In a run with FIXBOH by region (NO_RT), else the periods before the window."""
function fixed_periods(m::Model)
    if m.rt === nothing
        back = Set{Id}(m.d.BACKWARD.rows)
        return (r, t) -> t in back
    end
    nort = Set{NTuple{2,Id}}(m.d.FIXB_NORT.rows)
    return (r, t) -> (r, t) in nort
end

const TOLX = 1e-5           # relative tolerance of the relaxation of fixed trade (%TOLX%)

# solve.stp 250-256 (a run with FIXBOH): trade fixed in a region whose trade partner is in the window, and the activity
# of its process with REDUCE YES, are bounded around the loaded level instead of fixed:
#   VAR_IRE.UP(RTP_VINTYR(R,V,T,P),C,S,IE)$(RTP_IRE(R,T,P,IE)*RPCS_VAR(R,P,C,S)*RPC_IREIO(R,P,C,IE,'IN')) = VAR_IRE.L(R,V,T,P,C,S,IE)*(1+%TOLX%*POWER(8,-1$XPT(IE)));
#   VAR_IRE.LO(...) = VAR_IRE.L(R,V,T,P,C,S,IE)*(1-%TOLX%*POWER(8,-1$IMP(IE)));
#   LOOP(IE, VAR_ACT.UP(RTP_VINTYR(R,V,T,P),S)$(RTP_IRE(R,T,P,IE)*PRC_TS(R,P,S)*RP_PGACT(R,P)) = VAR_ACT.L(R,V,T,P,S)*(1+%TOLX%*POWER(8,-1$XPT(IE)));
#            VAR_ACT.LO(...) = VAR_ACT.L(R,V,T,P,S)*(1-%TOLX%*POWER(8,-1$IMP(IE))));      ($IF %REDUCE%==YES)
function relax_trade!(m::Model, levels)
    d, K = m.d, m.K
    ire = Set{NTuple{4,Id}}(d.FIXB_IRE.rows)
    up(ie) = 1 + TOLX * (ie == K.EXP ? 1 / 8 : 1.0)
    lo(ie) = 1 - TOLX * (ie == K.IMP ? 1 / 8 : 1.0)
    for (k, x) in m.v.VAR_IRE.x
        r, v, t, p, c, s, ie = k
        ((r, t, p, ie) in ire && (r, p, c, s) in d.RPCS_VAR && (r, p, c, ie, K.IN) in d.RPC_IREIO) || continue
        l = level(levels, :VAR_IRE, k)
        set_bounds!(x, l * lo(ie), l * up(ie))
    end
    isempty(d.FIXB_IREACT) && return m               # (REDUCE NO)
    act = Set{NTuple{4,Id}}(d.FIXB_IREACT.rows)
    for (k, x) in m.v.VAR_ACT.x
        r, v, t, p, s = k
        ((r, p, s) in d.PRC_TS && (r, p) in d.RP_PGACT) || continue
        for ie in (K.IMP, K.EXP)                       # the order of the loop over IE: the last one stays
            (r, t, p, ie) in act || continue
            l = level(levels, :VAR_ACT, k)
            set_bounds!(x, l * lo(ie), l * up(ie))
        end
    end
    return m
end

"""Merge the solution of a step into `levels` (SOLVEOPT=MERGE: what the step did not have keeps its value)."""
function merge_levels!(levels::Levels, m::Model)
    for var in m.v, (k, x) in var.x
        get!(Dict{Tuple,Float64}, levels, var.name)[k] = JuMP.value(x)
    end
    return levels
end

level(S, name::Symbol, k::Tuple) = haskey(S.vars, name) ? get(S.vars[name], k, (0.0,))[1] : 0.0

const TOLR = 3e-6           # relative tolerance of the relaxations of solve.stp (%TOLR%)
const TOLA = 1e-4           # absolute, for user constraints with coefficients of both signs (%TOLA%)

"""
The relaxations of solve.stp that need the levels of the previous step, kept from step to step as TIMES keeps
them in its data:

- `CAP_BND`: from the second step on, `UP = MAX(UP, VAR_CAP.L*(1+TOLR))`, `LO = LO*(1-TOLR)`. The bounds of
  `VAR_CAP` in a step are those that bndmain.mod set at the end of the step before (from `CAP_BND` as it was then);
  the capacity of the window built with vintages fixed before it (`NO_RVP`) and that of the periods after the
  window take the bounds as relaxed in the step; before the window capacity is free.
- `UC_RHST`, `UC_RHSTS` of the global user constraints in `UC_T` (those with capacity terms, in the window): the
  RHS widened to the level of the step before, then by `TOLR` (and `TOLA` with coefficients of both signs); the
  bounds of their slack variables follow.
"""
mutable struct Relax
    cap::Dict{NTuple{4,Id},Float64}
    capreset::Union{Nothing,Dict{NTuple{3,Id},NTuple{2,Float64}}}
    rhst::Dict{NTuple{3,Id},Float64}
    rhsts::Dict{NTuple{4,Id},Float64}
end
Relax(d::Data) = Relax(Dict(k => plain(v) for (k, v) in d.tables.CAP_BND), nothing,
    Dict(k => plain(v) for (k, v) in d.tables.UC_RHST), Dict(k => plain(v) for (k, v) in d.tables.UC_RHSTS))

"""Relax the data with the levels of the steps before (`levels`: a Solution or Levels), when the window has periods before it."""
function relax!(R::Relax, m::Model, levels)
    isempty(m.d.BACKWARD) && return R
    m.rt === nothing || return R                   # FIXBOH: relaxed by the preprocessor, with the loaded levels
    (; UP, LO) = m.K
    for (k, v) in R.cap
        k[4] == UP && (R.cap[k] = max(v, level(levels, :VAR_CAP, (k[1], k[2], k[3])) * (1 + TOLR)))
        k[4] == LO && v != 0 && (R.cap[k] = v * (1 - TOLR))
    end
    impexp = id!(m.L, "IMPEXP")
    function widen(rhs::Dict, key, lev, uc)
        for bd in (UP, LO)
            k = (key..., bd)
            haskey(rhs, k) || continue
            b = bd == UP ? max(rhs[k], lev == 0 ? -Inf : lev) : min(rhs[k], lev == 0 ? Inf : lev)
            isfinite(b) || continue             # a RHS given as 0 is EPS: an EPS record of UC_BND, relaxed like the others
            tol = abs(b) * TOLR + ((uc, impexp) in m.d.UC_RN ? TOLA : 0.0)
            rhs[k] = bd == UP ? b + tol : b - tol
        end
    end
    for (uc, t) in m.d.UC_T
        widen(R.rhst, (uc, t), level(levels, :VAR_UCT, (uc, t)), uc)
        for s in unique(k[3] for k in keys(R.rhsts) if k[1] == uc && k[2] == t)
            widen(R.rhsts, (uc, t, s), level(levels, :VAR_UCTS, (uc, t, s)), uc)
        end
    end
    return R
end

"""The bounds of capacity and of the slack variables of global user constraints in the step, from the relaxed data."""
function apply_relax!(R::Relax, m::Model)
    d, fwd = m.d, m.fwd
    isback = fixed_periods(m)
    (; UP, LO) = m.K
    for (k, x) in m.v.VAR_CAP.x
        r, t, p = k
        lo, up = R.capreset === nothing ? get(m.v.VAR_CAP.bounds, k, (0.0, Inf)) : get(R.capreset, k, (0.0, Inf))
        if (r, t, p) in d.RTP
            if isback(r, t)
                lo, up = 0.0, Inf
            elseif (r, t, p) in d.NO_RVP
                haskey(R.cap, (r, t, p, LO)) && (lo = R.cap[(r, t, p, LO)])
                haskey(R.cap, (r, t, p, UP)) && (up = R.cap[(r, t, p, UP)])
            elseif t in fwd
                lo = 0.0
                haskey(R.cap, (r, t, p, UP)) && (up = R.cap[(r, t, p, UP)])
            end
        end
        set_bounds!(x, lo, up)
    end
    for (var, rhs) in ((m.v.VAR_UCT, R.rhst), (m.v.VAR_UCTS, R.rhsts))
        for (k, x) in var.x
            haskey(var.bounds, k) || continue                      # not bounded by bnd_ucw.mod in this step
            set_bounds!(x, get(rhs, (k..., LO), -Inf), get(rhs, (k..., UP), Inf))
        end
    end
    return m
end

"""bndmain.mod after the solve: CAP_BND LO = MIN(LO, UP), and the capacity bounds the next step starts from."""
function reset_capacity!(R::Relax, m::Model)
    (; UP, LO) = m.K
    for (r, t, p) in m.d.RTP_VARP
        haskey(R.cap, (r, t, p, UP)) || continue
        lo = min(get(R.cap, (r, t, p, LO), 0.0), R.cap[(r, t, p, UP)])
        lo == 0 ? delete!(R.cap, (r, t, p, LO)) : (R.cap[(r, t, p, LO)] = lo)
    end
    reset = Dict{NTuple{3,Id},NTuple{2,Float64}}()
    for ((r, t, p, bd), v) in R.cap
        (r, t, p) in m.d.RTP || continue
        lo, up = get(reset, (r, t, p), (0.0, Inf))
        bd == LO && v != 0 && (lo = v)
        bd == UP && v != 0 && (up = v)
        reset[(r, t, p)] = (lo, up)
    end
    R.capreset = reset
    return R
end

"""
    solve_steps(d, optimizer; configure, progress, reference, check) -> (solution, last model)

Solve the steps of a myopic run one after the other: each is built (`make`, `build` unless a caller
substitutes its own), fixed outside its window at the solution
of the steps before (`fix_window!`), its relaxed bounds applied (`Relax`), solved, and merged into the solution.
`configure(jump_model)` sets the solver options; `progress(info, m)` is called after each step. Stops at a step
without a solution: `accept(jump_model)` says whether the solver left one (by default only a proved optimum; an
interior point solve without crossover can end "imprecise" with a feasible point, which the caller may take).
`retry(jump_model)`, called when a step has no solution, may change the solver settings and return true to solve the
step once more (the caller's fallback from one interior point code to another). `reference(k)`, when given, returns the levels to fix step k at instead of the
solution of the steps before (the GAMS levels of the step before, for a check); `check(k, year, m)` is called
with the built model before the solve, `starting(k, year)` before the step is built, and `say(message)` with what
is being done (for a log with time stamps).
"""
function solve_steps(d::Data, optimizer; configure = jm -> nothing, progress = (info, m) -> nothing, reference = nothing, check = nothing,
                     starting = (k, yr) -> nothing, say = msg -> nothing, accept = jm -> JuMP.termination_status(jm) == JuMP.OPTIMAL,
                     retry = jm -> false, make = build)
    sol = Solution(d.L)
    last = nothing
    R = nothing
    for (k, yr) in steps(d.source)
        starting(k, yr)
        t0 = time()
        say("step $k: reading the data of the step")
        ds = load_step(d, k)
        R === nothing && (R = Relax(ds))
        say("step $k: data read ($(round(time() - t0; digits = 1)) s); writing the equations")
        family(name, sec, m) = sec >= 0.5 && say("step $k:   $(rpad(name, 14)) $(lpad(round(sec; digits = 1), 7)) s   rows so far $(sum(length(r.refs) for r in values(m.rows); init = 0))")
        tb = time()
        m = make(ds; progress = family)
        say("step $k: equations written ($(round(time() - tb; digits = 1)) s): rows $(sum(values(row_counts(m)); init = 0)), columns $(JuMP.num_variables(m.jump))")
        tf = time()
        pt = load_point(d, k)                       # FIXBOH: the loaded solution point (spoint.mod)
        lev = reference !== nothing ? reference(k) : isempty(pt) ? sol : pt
        fix_window!(m, lev)
        relax!(R, m, lev)
        apply_relax!(R, m)
        say("step $k: periods outside the window fixed, bounds relaxed ($(round(time() - tf; digits = 1)) s)")
        t1 = time()
        check === nothing || check(k, yr, m)
        optimizer === HiGHS.Optimizer ? use_highs!(m.jump) : JuMP.set_optimizer(m.jump, optimizer)
        configure(m.jump)
        attach_highs!(m.jump)                       # the copy into HiGHS in one call (highs.jl)
        say("step $k: solving")
        JuMP.optimize!(m.jump)
        if !accept(m.jump) && retry(m.jump)
            say("step $k: solving again")
            JuMP.optimize!(m.jump)
        end
        status = JuMP.termination_status(m.jump)
        ok = accept(m.jump)
        say("step $k: solver finished: $status ($(round(time() - t1; digits = 1)) s)" *
            (ok ? (status == JuMP.OPTIMAL ? "" : "; a feasible point, taken as the solution of the step") : "; no solution, the run stops here"))
        info = Dict{String,Any}("step" => k, "year" => yr, "window" => join((label(m.L, t) for t in m.T if t in m.sub), " "),
            "rows" => sum(values(row_counts(m)); init = 0), "columns" => JuMP.num_variables(m.jump), "nonzeros" => nonzeros(m),
            "status" => string(status), "objective" => ok ? JuMP.objective_value(m.jump) : nothing, "seconds" => round(time() - t0; digits = 1),
            "build_seconds" => round(t1 - t0; digits = 1), "solve_seconds" => round(time() - t1; digits = 1))
        say("step $k: merging the solution")
        tr = time()
        ok && record!(sol, m; info)
        ok || push!(sol.steps, info)
        reset_capacity!(R, m)
        ok && say("step $k: solution merged ($(round(time() - tr; digits = 1)) s)")
        progress(info, m)
        last = m
        ok || break
    end
    last === nothing || clear_fixed_marginals!(sol, last)
    return sol, last
end
