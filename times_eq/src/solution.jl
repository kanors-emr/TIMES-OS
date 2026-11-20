# SPDX-License-Identifier: GPL-3.0-or-later
"""
The solution of a run, by GAMS name: for every column its level, marginal (reduced cost), lower and
upper bound; for every row its level (the value of its terms), marginal (dual) and the bounds that the
right-hand side gives it, as TIMES keeps them (GAMS sign conventions: the marginal of a row is the change
of the objective per unit of its right-hand side, that of a column its reduced cost).

A myopic run merges the steps as TIMES does (SOLVEOPT=MERGE): a row or column takes the values of the last
step that had it. `write_solution` stores the result in SQLite, in the layout of a GAMS GDX converted to
SQLite (one table per symbol: index columns, level, marginal, lower, upper), so that
whatever reads a GAMS solution reads this one too.
"""
struct Solution
    L::Labels
    vars::Dict{Symbol,Dict{Tuple,NTuple{4,Float64}}}
    eqs::Dict{Symbol,Dict{Tuple,NTuple{4,Float64}}}
    steps::Vector{Dict{String,Any}}
end
Solution(L::Labels) = Solution(L, Dict{Symbol,Dict{Tuple,NTuple{4,Float64}}}(), Dict{Symbol,Dict{Tuple,NTuple{4,Float64}}}(), Dict{String,Any}[])

function row_bounds(ref)
    s = JuMP.constraint_object(ref).set
    s isa MOI.EqualTo && return (s.value, s.value)
    s isa MOI.LessThan && return (-Inf, s.upper)
    s isa MOI.Interval && return (s.lower, s.upper)          # a non-binding row (=N=)
    return (s.lower, Inf)
end

"""
    record!(sol, m; step = nothing) -> sol

Merge the solution of the solved model `m` into `sol`. Duals are taken when the solver has them (an LP).
"""
function record!(sol::Solution, m::Model; info = nothing)
    duals = JuMP.has_duals(m.jump)
    # GAMS's marginal of a row is the change of the objective per unit of its right-hand side: JuMP's dual in a
    # minimisation, its negative in a maximisation (TIMES-MACRO: MAXIMIZING VAR_UTIL); a column's is its reduced cost
    sgn = JuMP.objective_sense(m.jump) == JuMP.MAX_SENSE ? -1.0 : 1.0
    for var in m.v
        isempty(var.x) && continue
        d = get!(Dict{Tuple,NTuple{4,Float64}}, sol.vars, var.name)
        for (k, x) in var.x
            d[k] = (JuMP.value(x), duals ? JuMP.reduced_cost(x) : NaN, lower(x), upper(x))
        end
    end
    for (name, r) in m.rows
        d = get!(Dict{Tuple,NTuple{4,Float64}}, sol.eqs, name)
        for (i, k) in enumerate(r.keys)
            ref = r.refs[i]
            lo, up = row_bounds(ref)
            d[k] = (JuMP.value(ref), duals ? sgn * JuMP.dual(ref) : NaN, lo, up)
        end
    end
    info === nothing || push!(sol.steps, info)
    return sol
end

"""
    Handed(m) -> what the solution needs of the JuMP model `m.jump`, kept before its copy is emptied

A solver given the model directly (`solve_mosek_direct!`), without JuMP's copy of it beside the solver's: the bounds of every
column and row, and which bounds a column has (for its reduced cost), are read from JuMP's copy first. Columns by
MOI index: `lo`, `up`, `has` (bit 1 lower bound, 2 upper, 4 fixed); rows in the order of `m.rows` and their refs.
"""
struct Handed
    lo::Vector{Float64}
    up::Vector{Float64}
    has::Vector{UInt8}
    rows::Dict{Symbol,Vector{NTuple{2,Float64}}}
    sense::MOI.OptimizationSense
end

function Handed(m::Model)
    jm = m.jump
    n = JuMP.num_variables(jm)
    lo, up, has = fill(-Inf, n), fill(Inf, n), zeros(UInt8, n)
    for x in JuMP.all_variables(jm)
        i = JuMP.index(x).value
        if JuMP.is_fixed(x)
            lo[i] = up[i] = JuMP.fix_value(x); has[i] = 0x04
        else
            JuMP.has_lower_bound(x) && (lo[i] = JuMP.lower_bound(x); has[i] |= 0x01)
            JuMP.has_upper_bound(x) && (up[i] = JuMP.upper_bound(x); has[i] |= 0x02)
        end
    end
    b = JuMP.backend(jm)
    rows = Dict{Symbol,Vector{NTuple{2,Float64}}}()
    for (name, r) in m.rows
        rows[name] = [set_bounds(MOI.get(b, MOI.ConstraintSet(), JuMP.index(ref))) for ref in r.refs]
    end
    return Handed(lo, up, has, rows, MOI.get(b, MOI.ObjectiveSense()))
end

"""The bounds of a row from its set, as `row_bounds`."""
set_bounds(s::MOI.EqualTo) = (s.value, s.value)
set_bounds(s::MOI.LessThan) = (-Inf, s.upper)
set_bounds(s::MOI.Interval) = (s.lower, s.upper)
set_bounds(s::MOI.GreaterThan) = (s.lower, Inf)

"""
    record_direct!(sol, m, h, o, map) -> sol

`record!` for a model handed to the solver `o` directly (`h`: `Handed(m)`, kept before JuMP's copy was emptied; `map`:
the index map of the copy). The same values as `record!`: levels and marginals from the solver, the reduced cost of a
column as JuMP's `reduced_cost` makes it (the duals of its bounds, the sign of a maximisation turned), a row's
marginal with that sign too, the bounds as they were given.
"""
function record_direct!(sol::Solution, m::Model, h::Handed, o, map; info = nothing)
    duals = MOI.get(o, MOI.DualStatus()) != MOI.NO_SOLUTION
    sgn = h.sense == MOI.MAX_SENSE ? -1.0 : 1.0
    F = MOI.VariableIndex
    for var in m.v
        isempty(var.x) && continue
        d = get!(Dict{Tuple,NTuple{4,Float64}}, sol.vars, var.name)
        ks = collect(keys(var.x))
        src = [JuMP.index(var.x[k]) for k in ks]
        vals = MOI.get(o, MOI.VariablePrimal(), [map[v] for v in src])
        for (j, k) in enumerate(ks)
            i = src[j].value
            rc = NaN
            if duals
                f = h.has[i]
                rc = if f & 0x04 != 0
                    MOI.get(o, MOI.ConstraintDual(), map[MOI.ConstraintIndex{F,MOI.EqualTo{Float64}}(i)])
                else
                    (f & 0x02 != 0 ? MOI.get(o, MOI.ConstraintDual(), map[MOI.ConstraintIndex{F,MOI.LessThan{Float64}}(i)]) : 0.0) +
                    (f & 0x01 != 0 ? MOI.get(o, MOI.ConstraintDual(), map[MOI.ConstraintIndex{F,MOI.GreaterThan{Float64}}(i)]) : 0.0)
                end
                rc *= sgn
            end
            d[k] = (vals[j], rc, h.lo[i], h.up[i])
        end
    end
    for (name, r) in m.rows
        d = get!(Dict{Tuple,NTuple{4,Float64}}, sol.eqs, name)
        bds = h.rows[name]
        for (i, k) in enumerate(r.keys)
            c = map[JuMP.index(r.refs[i])]
            lo, up = bds[i]
            d[k] = (MOI.get(o, MOI.ConstraintPrimal(), c), duals ? sgn * MOI.get(o, MOI.ConstraintDual(), c) : NaN, lo, up)
        end
    end
    info === nothing || push!(sol.steps, info)
    return sol
end

"""Levels of all columns in `sol` (to fix the periods before the window of the next step)."""
function levels(sol::Solution)
    out = Levels()
    for (name, d) in sol.vars
        out[name] = Dict{Tuple,Float64}(k => v[1] for (k, v) in d)
    end
    return out
end

"""
After the last step of a myopic run (solve.stp, ENDSTEP): the marginals of new capacity, activities, flows
and trade in the periods fixed before the last window are cleared, as TIMES clears them.
"""
function clear_fixed_marginals!(sol::Solution, m::Model)
    isback = fixed_periods(m)                         # (FIXBOH: NO_RT, by region)
    for (name, tpos) in ((:VAR_NCAP, 2), (:VAR_ACT, 3), (:VAR_FLO, 3), (:VAR_IRE, 3))
        d = get(sol.vars, name, nothing)
        d === nothing && continue
        for (k, v) in d
            isback(k[1], k[tpos]) && (d[k] = (v[1], 0.0, v[3], v[4]))
        end
    end
    return sol
end

num(x) = isnan(x) ? missing : x >= 1e299 || x == Inf ? 1e300 : x <= -1e299 || x == -Inf ? -1e300 : x

"""
    write_solution(path, sol)

The solution in SQLite (see `Solution`): a table per variable and equation, `__symbols(name, kind, dim)`, and
`__steps` with what each step of a myopic run did (one row for a run without steps).
"""
function write_solution(path::AbstractString, sol::Solution)
    isfile(path) && rm(path)
    db = SQLite.DB(path)
    try
        meta = Tuple{String,String,Int}[]
        SQLite.DBInterface.execute(db, "begin")
        for (kind, group) in (("variable", sol.vars), ("equation", sol.eqs))
            for name in sort!(collect(keys(group)))
                d = group[name]
                n = isempty(d) ? 0 : length(first(keys(d)))
                cols = join(("\"d$i\" TEXT" for i in 0:n-1), ", ")
                SQLite.DBInterface.execute(db, "create table \"$name\" ($(cols)$(n > 0 ? ", " : "")level REAL, marginal REAL, lower REAL, upper REAL)")
                st = SQLite.Stmt(db, "insert into \"$name\" values ($(join(fill("?", n + 4), ",")))")
                for (k, v) in d
                    SQLite.DBInterface.execute(st, (label(sol.L, k)..., num(v[1]), num(v[2]), num(v[3]), num(v[4])))
                end
                push!(meta, (String(name), kind, n))
            end
        end
        SQLite.DBInterface.execute(db, "create table __symbols (name TEXT, kind TEXT, dim INTEGER)")
        for x in meta
            SQLite.DBInterface.execute(db, "insert into __symbols values (?,?,?)", x)
        end
        SQLite.DBInterface.execute(db, "create table __steps (step INTEGER, year INTEGER, window TEXT, rows INTEGER, columns INTEGER, nonzeros INTEGER, status TEXT, objective REAL, seconds REAL)")
        for s in sol.steps
            SQLite.DBInterface.execute(db, "insert into __steps values (?,?,?,?,?,?,?,?,?)",
                (s["step"], s["year"], s["window"], s["rows"], s["columns"], s["nonzeros"], s["status"], something(s["objective"], missing), s["seconds"]))
        end
        SQLite.DBInterface.execute(db, "commit")
        return path
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

"""
    compare_solution(sol, gams; io = stdout, tol = 1e-6, show = 3) -> NamedTuple

The merged solution of a myopic run against the solution file of the GAMS run (converted to
SQLite), which TIMES writes after the last step:

- `rows`: the rows of every equation over all steps, key by key (rows that GAMS generated in some step, and
  rows here);
- `levels`: the level of every column here against the GAMS level (`level_worst`, relative to the size of the
  level and at least 1; `levels_off` above `tol`). Levels can differ where a step has several optimal
  solutions: the next steps are then fixed at another point.
"""
function compare_solution(sol::Solution, gams::AbstractString; io::IO = stdout, tol::Float64 = 1e-6, show::Int = 3)
    db = SQLite.DB(gams)
    try
        eqs = gams_records(db, sol.L, "equation")
        vars = gams_records(db, sol.L, "variable")
        lab(k) = join(label(sol.L, k), ",")
        println(io, "\nEquation (all steps)  Julia    GAMS")
        bad = nmiss = nextra = 0
        names = sort(collect(union(keys(sol.eqs), (k for (k, v) in eqs if !isempty(v)))); by = String)
        for k in names
            mine = Set{Tuple}(keys(get(sol.eqs, k, Dict{Tuple,NTuple{4,Float64}}())))
            theirs = Set{Tuple}(keys(get(eqs, k, Dict{Tuple,Float64}())))
            miss, extra = setdiff(theirs, mine), setdiff(mine, theirs)
            differs = !(isempty(miss) && isempty(extra))
            bad += differs; nmiss += length(miss); nextra += length(extra)
            println(io, rpad(k, 20), lpad(length(mine), 7), lpad(length(theirs), 8), differs ? "   <-- missing $(length(miss)), extra $(length(extra))" : "")
            for x in Iterators.take(miss, show); println(io, "      missing: ", lab(x)); end
            for x in Iterators.take(extra, show); println(io, "      extra:   ", lab(x)); end
        end
        println(io, "\nVariable (all steps)  columns  largest level difference")
        worst, off, n = 0.0, 0, 0
        for name in sort(collect(keys(sol.vars)); by = String)
            isempty(sol.vars[name]) && continue
            g = get(vars, name, Dict{Tuple,Float64}())
            w, o = 0.0, 0
            ex = nothing
            for (k, v) in sol.vars[name]
                a, b = v[1], get(g, k, 0.0)
                r = abs(a - b) / max(1.0, abs(b))
                n += 1
                r > tol && (o += 1)
                r > w && (w = r; ex = (k, a, b))
            end
            worst = max(worst, w); off += o
            println(io, rpad(name, 20), lpad(length(sol.vars[name]), 8), "  ", round(w; sigdigits = 3), o > 0 ? "   <-- $o columns; e.g. $(lab(ex[1])): julia $(ex[2]) gams $(ex[3])" : "")
        end
        gobj = haskey(vars, :OBJZ) && !isempty(vars[:OBJZ]) ? first(values(vars[:OBJZ])) : nothing
        return (row_families = length(names), row_families_differ = bad, rows_missing = nmiss, rows_extra = nextra, same_rows = bad == 0,
                columns_compared = n, level_worst = worst, levels_off = off, tolerance = tol, same_levels = off == 0, gams_objective = gobj)
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end
