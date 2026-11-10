# SPDX-License-Identifier: GPL-3.0-or-later
# A built model against what GAMS generated and solved for the same case, with a verdict.

function gams_records(db, L::Labels, kind::String; field::Int = 1)
    out = Dict{Symbol,Dict{Tuple,Float64}}()
    for row in SQLite.DBInterface.execute(db, "select name, kind, dim from __symbols")
        String(row[2]) == kind || continue
        name, dim = Symbol(uppercase(String(row[1]))), Int(row[3])
        x = out[name] = Dict{Tuple,Float64}()
        for r in SQLite.DBInterface.execute(db, "select * from \"$(row[1])\"")
            v = r[dim+field]
            ismissing(v) && continue                # not available: the marginals after a MIP
            x[ntuple(i -> id!(L, string(r[i])), dim)] = Float64(v)
        end
    end
    # rptmisc.rpt copies the marginals of EQE_UCRTP into EQN_UCRTP(..,'FX') for the report: those records are not rows
    if kind == "equation" && haskey(out, :EQN_UCRTP) && haskey(out, :EQE_UCRTP)
        foreach(k -> delete!(out[:EQN_UCRTP], k), keys(out[:EQE_UCRTP]))
    end
    # A stochastic run (rows ES_*) copies the marginals of its rows into the deterministic families for the report, which
    # are then not rows of the model (rptmain.stc 64-69, 92):
    #     EQG_COMBAL.M(R,T,C,S)  $= SUM(SW_TSW(SOW,T,W),%EQ%G_COMBAL.M(R,T,C,S,T,W)*SW_UNPB(T,W));
    #     ... EQE_COMBAL, EQE_COMPRD, EQ_PEAK, EQ_IRE, EQE_CPT; EQN_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD('FX')) from ESE_UCRTP
    if kind == "equation" && any(k -> startswith(String(k), "ES"), keys(out))
        foreach(k -> delete!(out, k), (:EQG_COMBAL, :EQE_COMBAL, :EQE_COMPRD, :EQ_PEAK, :EQ_IRE, :EQE_CPT, :EQN_UCRTP))
    end
    return out
end

"""
    compare_gams(m, d, solution; io = stdout, tol = 1e-6, show = 3, only = nothing) -> NamedTuple

Compare the model `m` (built from `d`) with the solution file of the GAMS run of the same case: the
GDX that TIMES writes after the solve, converted to SQLite. It holds every
generated row with its level and marginal, and the columns with theirs. The GAMS run must be one
with `REDUCE NO`: otherwise GAMS has removed rows and columns that this model keeps.

Checked, and reported in the result:

- `rows`: the rows of every equation family, key by key (`row_families_differ`, `rows_missing`,
  `rows_extra`: in GAMS and not here, here and not in GAMS).
- `columns`: for every variable family the columns here and the records in the GAMS file. A
  column without a record in the file is normal (GAMS does not store a column at its defaults).
  A record in the file for a column that does not exist here is a difference when its level or
  marginal is not zero (`columns_missing_active`).
- `activity`: every row evaluated at the GAMS levels against the level GAMS reports for that row
  (`activity_worst` relative, `activity_rows_off` above `tol`). The difference is taken relative to
  the size of the row, the sum of the absolute terms: a GAMS solution from an interior point method
  without crossover satisfies its own rows only to that accuracy, while a wrong coefficient shifts
  the row by a share of one of its terms.
- `reduced cost`: for every column, computed from the coefficients here and the GAMS row
  marginals, against the marginal GAMS reports: a test of the coefficients column by column
  (`reduced_cost_worst`, `reduced_cost_columns_off`). Two things the TIMES reports do to the
  marginals after the solve are allowed for: `VAR_CAP.M` that is zero is replaced by `EQE_CPT.M`
  (rptmisc.rpt), and `VAR_NCAP.M` of investments that are switched off is cleared (rpt_objc.rpt;
  these columns are not compared).

When the GAMS solution is not a vertex (`gams_interior`: more than 1% of its columns are off their
bounds and have a reduced cost, the mark of an interior point method without crossover), its own
rows and reduced costs hold only to the convergence tolerance of that method, and the two checks
use 1e-3 and 1e-5 instead of `tol` (`tolerance_rows`, `tolerance_reduced_cost`).

`same_rows`, `same_solution` and `same_duals` are the three verdicts; `gams_objective` is the
level of `OBJZ` in the file.
"""
function compare_gams(m::Model, d::Data, solution::AbstractString; io::IO = stdout, tol::Float64 = 1e-6, show::Int = 3, only = nothing)
    db = SQLite.DB(solution)
    try
        eqs = gams_records(db, d.L, "equation")
        vars = gams_records(db, d.L, "variable")
        lab(k) = join(label(m.L, k), ",")
        families = Any[]

        println(io, "\nEquation        Julia    GAMS")
        rows = row_counts(m)
        names = sort(collect(union(keys(rows), (k for (k, v) in eqs if !isempty(v)))); by = k -> (-length(get(eqs, k, ())), String(k)))
        bad = nmiss = nextra = 0
        for k in names
            a, b = get(rows, k, 0), length(get(eqs, k, ()))
            mine = haskey(m.rows, k) ? Set{Tuple}(m.rows[k].keys) : Set{Tuple}()
            theirs = Set{Tuple}(keys(get(eqs, k, Dict{Tuple,Float64}())))
            miss, extra = setdiff(theirs, mine), setdiff(mine, theirs)
            differs = !(isempty(miss) && isempty(extra))
            bad += differs
            nmiss += length(miss)
            nextra += length(extra)
            println(io, rpad(k, 14), lpad(a, 7), lpad(b, 8), differs ? "   <-- missing $(length(miss)), extra $(length(extra))" : "")
            n = (only === nothing || only == k) ? show : 0
            for x in Iterators.take(miss, n); println(io, "      missing: ", lab(x)); end
            for x in Iterators.take(extra, n); println(io, "      extra:   ", lab(x)); end
            push!(families, (name = String(k), julia = a, gams = b, missing = length(miss), extra = length(extra),
                missing_examples = [lab(x) for x in Iterators.take(miss, show)], extra_examples = [lab(x) for x in Iterators.take(extra, show)]))
        end
        gams_rows = sum(length(v) for v in values(eqs); init = 0)
        println(io, "rows      ", sum(values(rows); init = 0), "   (GAMS ", gams_rows, ")   families that differ: ", bad)

        println(io, "\nVariable        Julia    GAMS (records in the solution file)")
        marg = gams_records(db, d.L, "variable"; field = 2)
        columns = Any[]
        active = 0
        known = Set{Symbol}()
        for v in m.v
            push!(known, v.name)
            g = get(vars, v.name, Dict{Tuple,Float64}())
            (isempty(v.x) && isempty(g)) && continue
            gm = get(marg, v.name, Dict{Tuple,Float64}())
            miss = [k for k in keys(g) if !haskey(v.x, k)]
            act = [k for k in miss if g[k] != 0 || get(gm, k, 0.0) != 0]
            norec = count(k -> !haskey(g, k), keys(v.x))
            active += length(act)
            println(io, rpad(v.name, 14), lpad(length(v.x), 7), lpad(length(g), 8),
                isempty(miss) ? "" : "   <-- $(length(miss)) records for columns that are not in this model, $(length(act)) of them not zero")
            n = (only === nothing || only == v.name) ? show : 0
            for x in Iterators.take(act, n); println(io, "      not zero in GAMS, no column here: ", lab(x), "  level ", g[x]); end
            push!(columns, (name = String(v.name), julia = length(v.x), gams_records = length(g), not_here = length(miss), not_here_active = length(act),
                no_record = norec, examples = [lab(x) for x in Iterators.take(act, show)]))
        end
        # variable families of the GAMS model that this package does not have at all
        for (name, g) in vars
            (name in known || name == :OBJZ) && continue
            gm = get(marg, name, Dict{Tuple,Float64}())
            act = count(k -> g[k] != 0 || get(gm, k, 0.0) != 0, keys(g))
            act == 0 && continue
            active += act
            println(io, rpad(name, 14), lpad(0, 7), lpad(length(g), 8), "   <-- a variable family this package does not have, $act records not zero")
            push!(columns, (name = String(name), julia = 0, gams_records = length(g), not_here = length(g), not_here_active = act, no_record = 0, examples = String[]))
        end
        println(io, "columns   ", JuMP.num_variables(m.jump), "     nonzeros  ", nonzeros(m))

        # Is the GAMS solution a vertex? At a vertex a column off its bounds has no reduced cost. An interior point
        # method without crossover leaves thousands of columns slightly off their bounds with one, and its rows hold
        # only to its convergence tolerance: the two checks below then use a wider tolerance, and say so.
        lo, up = gams_records(db, d.L, "variable"; field = 3), gams_records(db, d.L, "variable"; field = 4)
        nrec = noff = 0
        for (name, g) in vars
            name == :VAR_CAP && continue               # its marginal is rewritten by the reports
            gm, glo, gup = get(marg, name, g), get(lo, name, g), get(up, name, g)
            for (k, x) in g
                nrec += 1
                w = 1e-7 * max(1.0, abs(x))
                noff += abs(get(gm, k, 0.0)) > 1e-7 && x - get(glo, k, 0.0) > w && get(gup, k, Inf) - x > w
            end
        end
        interior = noff > 0.01 * nrec
        tol_rows, tol_cols = interior ? max(tol, 1e-3) : tol, interior ? max(tol, 1e-5) : tol
        interior && println(io, "\nThe GAMS solution is not a vertex (", noff, " of ", nrec, " columns are off their bounds and have a reduced cost): ",
            "an interior point method without crossover. Tolerances: rows ", tol_rows, ", reduced costs ", tol_cols, ".")

        # activity of every row at the GAMS levels against the GAMS equation level
        lev = Dict{JuMP.VariableRef,Float64}()
        for v in m.v
            l = get(vars, v.name, Dict{Tuple,Float64}())
            for (k, x) in v.x
                lev[x] = get(l, k, 0.0)
            end
        end
        println(io, "\nRow activity at the GAMS solution against the GAMS equation level (largest relative difference)")
        act_worst, act_off = 0.0, 0
        activity = Any[]
        for k in names
            haskey(m.rows, k) || continue
            g = get(eqs, k, Dict{Tuple,Float64}())
            worst, at, n = 0.0, nothing, 0
            for (key, c) in zip(m.rows[k].keys, m.rows[k].refs)
                haskey(g, key) || continue
                f = JuMP.constraint_object(c).func
                a, size = f.constant, 0.0
                for (x, coef) in f.terms
                    a += coef * lev[x]
                    size += abs(coef * lev[x])
                end
                dlt = abs(a - g[key]) / max(1.0, size, abs(g[key]))
                n += dlt > tol_rows
                dlt > worst && ((worst, at) = (dlt, (key, a, g[key])))
            end
            act_worst = max(act_worst, worst)
            act_off += n
            note = worst > tol_rows ? "$(lab(at[1])): julia $(at[2]) gams $(at[3])" : ""
            println(io, rpad(k, 14), lpad(string(round(worst; sigdigits = 3)), 12), worst > tol_rows ? "   <-- $n rows; e.g. $note" : "")
            n > 0 && push!(activity, (name = String(k), rows_off = n, worst = worst, example = note))
        end
        println(io, "largest difference: ", act_worst, "   rows above ", tol_rows, ": ", act_off)

        # reduced cost of every column: (1 for OBJZ) - SUM(rows, GAMS marginal of the row * coefficient here)
        pi = gams_records(db, d.L, "equation"; field = 2)
        acc = Dict{JuMP.VariableRef,Float64}()
        mag = Dict{JuMP.VariableRef,Float64}()
        cpt = get(pi, :EQE_CPT, Dict{Tuple,Float64}())
        for (name, r) in m.rows
            g = get(pi, name, Dict{Tuple,Float64}())
            for (key, c) in zip(r.keys, r.refs)
                y = get(g, key, 0.0)
                y == 0 && continue
                for (x, a) in JuMP.constraint_object(c).func.terms
                    acc[x] = get(acc, x, 0.0) + y * a
                    mag[x] = max(get(mag, x, 0.0), abs(y * a))
                end
            end
        end
        println(io, "\nReduced cost of every column from the GAMS row marginals against the GAMS column marginal (largest relative difference)")
        rc_worst, rc_off = 0.0, 0
        reduced = Any[]
        for v in m.v
            isempty(v.x) && continue
            g = get(marg, v.name, Dict{Tuple,Float64}())
            worst, at, n, fixed = 0.0, nothing, 0, 0
            glo, gup = get(lo, v.name, Dict{Tuple,Float64}()), get(up, v.name, Dict{Tuple,Float64}())
            for (k, x) in v.x
                theirs = get(g, k, 0.0)
                if v.name == :VAR_NCAP && theirs == 0 && get(glo, k, 0.0) == get(gup, k, Inf)
                    fixed += 1
                    continue
                end
                mine = (v.name == :OBJZ ? 1.0 : 0.0) - get(acc, x, 0.0)
                scale = max(1.0, get(mag, x, 0.0), abs(theirs))
                dlt = abs(mine - theirs) / scale
                # (with an interior solution the marginal is small but not zero, and the report leaves it: either form is accepted)
                (v.name == :VAR_CAP && abs(mine) < 1e-9 * scale) && (dlt = min(dlt, abs(get(cpt, k, 0.0) - theirs) / scale))
                n += dlt > tol_cols
                dlt > worst && ((worst, at) = (dlt, (k, mine, theirs)))
            end
            rc_worst = max(rc_worst, worst)
            rc_off += n
            note = worst > tol_cols ? "$(lab(at[1])): julia $(at[2]) gams $(at[3])" : ""
            println(io, rpad(v.name, 14), lpad(string(round(worst; sigdigits = 3)), 12), fixed > 0 ? "   ($fixed columns not compared)" : "",
                worst > tol_cols ? "   <-- $n columns; e.g. $note" : "")
            n > 0 && push!(reduced, (name = String(v.name), columns_off = n, worst = worst, example = note))
        end
        println(io, "largest difference: ", rc_worst, "   columns above ", tol_cols, ": ", rc_off)

        # right-hand side and sense of every row against the bounds GAMS reports for the equation, and the bounds of
        # every column: a row or a bound that is looser here leaves the GAMS solution feasible and its reduced costs
        # the same, and is only seen in this comparison (or in a lower optimum)
        near(a, b) = (a == b) || (isfinite(a) && isfinite(b) && abs(a - b) <= tol * max(1.0, abs(a), abs(b)))
        bounds_of(set) = set isa MOI.EqualTo ? (set.value, set.value) : set isa MOI.GreaterThan ? (set.lower, Inf) :
                         set isa MOI.LessThan ? (-Inf, set.upper) : (set.lower, set.upper)
        elo, eup = gams_records(db, d.L, "equation"; field = 3), gams_records(db, d.L, "equation"; field = 4)
        println(io, "\nRight-hand side and sense of every row against GAMS (rows that differ)")
        rhs_off, rhs = 0, Any[]
        for k in names
            haskey(m.rows, k) || continue
            glo, gup = get(elo, k, Dict{Tuple,Float64}()), get(eup, k, Dict{Tuple,Float64}())
            n, at = 0, nothing
            for (key, c) in zip(m.rows[k].keys, m.rows[k].refs)
                haskey(glo, key) || continue
                lo_, up_ = bounds_of(JuMP.constraint_object(c).set)
                a, b = fix_inf(glo[key]), fix_inf(gup[key])
                (near(lo_, a) && near(up_, b)) && continue
                n += 1
                at === nothing && (at = "$(lab(key)): julia [$lo_, $up_] gams [$a, $b]")
            end
            n > 0 && (println(io, rpad(k, 14), lpad(n, 9), " rows; e.g. ", at); push!(rhs, (name = String(k), rows_off = n, example = at)))
            rhs_off += n
        end
        println(io, "rows with another right-hand side or sense: ", rhs_off)
        println(io, "\nBounds of every column against GAMS (columns that differ)")
        bnd_off, bnd = 0, Any[]
        for v in m.v
            isempty(v.x) && continue
            glo, gup = get(lo, v.name, Dict{Tuple,Float64}()), get(up, v.name, Dict{Tuple,Float64}())
            n, at = 0, nothing
            for (k, x) in v.x
                haskey(glo, k) || continue                 # no record: the column is at its defaults in GAMS, or is not reported
                lo_ = JuMP.is_fixed(x) ? JuMP.fix_value(x) : JuMP.has_lower_bound(x) ? JuMP.lower_bound(x) : -Inf
                up_ = JuMP.is_fixed(x) ? JuMP.fix_value(x) : JuMP.has_upper_bound(x) ? JuMP.upper_bound(x) : Inf
                a, b = fix_inf(glo[k]), fix_inf(gup[k])
                (near(lo_, a) && near(up_, b)) && continue
                n += 1
                at === nothing && (at = "$(lab(k)): julia [$lo_, $up_] gams [$a, $b]")
            end
            n > 0 && (println(io, rpad(v.name, 14), lpad(n, 9), " columns; e.g. ", at); push!(bnd, (name = String(v.name), columns_off = n, example = at)))
            bnd_off += n
        end
        println(io, "columns with other bounds: ", bnd_off)

        has_duals = any(any(!=(0.0), values(g)) for g in values(pi))
        return (rows_julia = sum(values(rows); init = 0), rows_gams = gams_rows, row_families = length(names), row_families_differ = bad,
            rows_missing = nmiss, rows_extra = nextra, families, columns_julia = JuMP.num_variables(m.jump), columns, columns_missing_active = active,
            nonzeros = nonzeros(m), tolerance = tol, gams_interior = interior, gams_columns_off_vertex = noff, tolerance_rows = tol_rows, tolerance_reduced_cost = tol_cols,
            activity_worst = act_worst, activity_rows_off = act_off, activity,
            reduced_cost_worst = rc_worst, reduced_cost_columns_off = rc_off, reduced_cost = reduced, gams_has_duals = has_duals,
            rhs_rows_off = rhs_off, rhs, bounds_columns_off = bnd_off, bounds = bnd, same_rhs = rhs_off == 0, same_bounds = bnd_off == 0,
            gams_objective = get(get(vars, :OBJZ, Dict{Tuple,Float64}()), (), NaN),
            same_rows = bad == 0, same_solution = act_off == 0, same_duals = has_duals && rc_off == 0)
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

"""
    compare_matrix(m, d, file; io = stdout, tol = 1e-9, show = 3) -> NamedTuple

Compare the model `m` with the matrix GAMS generated for the same case, entry by entry. `file` is the
matrix that the GAMS solver CONVERT writes (option file `jacobian jacobian.gdx`; run with
`REDUCE NO`), converted to SQLite. It holds every
row and column by name, every coefficient (explicit zeros included), the right-hand side bounds
of every row and the bounds of every column.

Rows and columns are matched by equation or variable name and labels. Then

- every coefficient must be there on both sides and equal (relative difference at most `tol`),
- every row must have the same right-hand side and sense, every column the same bounds.

When all of this holds (`same_model`), the two are the same linear program: they have the same
optimum, whatever a solver makes of it. No solution of either side is used.
"""
function compare_matrix(m::Model, d::Data, file::AbstractString; io::IO = stdout, tol::Float64 = 1e-9, show::Int = 3)
    db = SQLite.DB(file)
    tm = [time()]                                   # the clock at the end of each part (seconds: in the result)
    try
        # the labels of a key are joined by the separator in table meta (chr(31), gdx2sqlite KEYSEP); files written before
        # 2026-10-10 have no meta table and joined them by '|', which a label may contain (e.g. 'A||B')
        newsep = !isempty(SQLite.DBInterface.execute(db, "select name from sqlite_master where name = 'meta'") |> collect)
        sep = newsep ? only(r[1] for r in SQLite.DBInterface.execute(db, "select value from meta where name = 'keysep'"))[1] : '|'
        key(s) = (t = String(s); isempty(t) ? () : Tuple(id!(d.L, x) for x in split(t, sep)))
        lab(k) = join(label(m.L, k), ",")
        near(a, b) = (a == b) || (isfinite(a) && isfinite(b) && abs(a - b) <= tol * max(abs(a), abs(b)) + 1e-12)

        # rows and columns of GAMS by name
        grow = Dict{Tuple{Symbol,Tuple},Int}()
        rname, rlo, rup = Dict{Int,Tuple{Symbol,Tuple}}(), Dict{Int,Float64}(), Dict{Int,Float64}()
        for r in SQLite.DBInterface.execute(db, "select i, name, key, lower, upper from rows")
            k = (Symbol(String(r[2])), key(r[3]))
            grow[k] = r[1]; rname[r[1]] = k; rlo[r[1]] = fix_inf(Float64(r[4])); rup[r[1]] = fix_inf(Float64(r[5]))
        end
        gcol = Dict{Tuple{Symbol,Tuple},Int}()
        cname, clo, cup = Dict{Int,Tuple{Symbol,Tuple}}(), Dict{Int,Float64}(), Dict{Int,Float64}()
        for r in SQLite.DBInterface.execute(db, "select j, name, key, lower, upper from cols")
            k = (Symbol(String(r[2])), key(r[3]))
            gcol[k] = r[1]; cname[r[1]] = k; clo[r[1]] = fix_inf(Float64(r[4])); cup[r[1]] = fix_inf(Float64(r[5]))
        end

        push!(tm, time())                            # GAMS's rows and columns read
        # columns here -> column number of GAMS; bounds on the way
        col = Dict{JuMP.VariableRef,Int}()
        cols_only_here, bnd_off, bnd = 0, 0, String[]
        here_by = Dict{String,Int}()                 # rows / columns only here, counted by equation / variable
        seen_cols = Set{Int}()
        for v in m.v, (k, x) in v.x
            j = get(gcol, (v.name, k), 0)
            j == 0 && (cols_only_here += 1; here_by["column " * string(v.name)] = get(here_by, "column " * string(v.name), 0) + 1;
                       length(bnd) < show && push!(bnd, "column only here: $(v.name)($(lab(k)))"); continue)
            col[x] = j
            push!(seen_cols, j)
            lo_ = JuMP.is_fixed(x) ? JuMP.fix_value(x) : JuMP.has_lower_bound(x) ? JuMP.lower_bound(x) : -Inf
            up_ = JuMP.is_fixed(x) ? JuMP.fix_value(x) : JuMP.has_upper_bound(x) ? JuMP.upper_bound(x) : Inf
            if !(near(lo_, clo[j]) && near(up_, cup[j]))
                bnd_off += 1
                length(bnd) < show && push!(bnd, "$(v.name)($(lab(k))): bounds here [$lo_, $up_], GAMS [$(clo[j]), $(cup[j])]")
            end
        end
        cols_only_gams = length(gcol) - length(seen_cols)

        # entries here, as (row number of GAMS, column number of GAMS) => coefficient; right-hand sides on the way
        mine = Tuple{UInt64,Float64}[]
        sizehint!(mine, nonzeros(m))
        rows_only_here, rhs_off, rhs, rhs_rounding = 0, 0, String[], 0
        # a right-hand side made of constants that cancel is equal to GAMS's when the two differ by
        # no more than the rounding of that arithmetic, 64 machine epsilons of the size of the cancelled constants
        within(a, b, sz) = a == b || (isfinite(a) && isfinite(b) && abs(a - b) <= 64 * eps(Float64) * sz)
        seen_rows = Set{Int}()
        pack(i, j) = (UInt64(i) << 32) | UInt64(j)
        for (name, r) in m.rows, (n, (k, c)) in enumerate(zip(r.keys, r.refs))
            i = get(grow, (name, k), 0)
            i == 0 && (rows_only_here += 1; here_by["row " * string(name)] = get(here_by, "row " * string(name), 0) + 1;
                       length(rhs) < show && push!(rhs, "row only here: $name($(lab(k)))"); continue)
            push!(seen_rows, i)
            o = JuMP.constraint_object(c)
            set = o.set
            lo_, up_ = set isa MOI.EqualTo ? (set.value, set.value) : set isa MOI.GreaterThan ? (set.lower, Inf) :
                       set isa MOI.LessThan ? (-Inf, set.upper) : (set.lower, set.upper)
            if !(near(lo_, rlo[i]) && near(up_, rup[i]))
                csz = get(r.cancel, n, 0.0)
                if csz > 0 && within(lo_, rlo[i], csz) && within(up_, rup[i], csz)
                    rhs_rounding += 1
                    length(rhs) < show && push!(rhs, "$name($(lab(k))): right-hand side here [$lo_, $up_], GAMS [$(rlo[i]), $(rup[i])]: " *
                        "equal within the rounding of constants of size $(round(csz; sigdigits = 3)) that cancel (decision 0007)")
                else
                    rhs_off += 1
                    length(rhs) < show && push!(rhs, "$name($(lab(k))): right-hand side here [$lo_, $up_], GAMS [$(rlo[i]), $(rup[i])]")
                end
            end
            for (x, a) in o.func.terms
                j = get(col, x, 0)
                j == 0 || push!(mine, (pack(i, j), a))
            end
            for x in get(r.zeros, n, ())
                j = get(col, x, 0)
                j == 0 || push!(mine, (pack(i, j), 0.0))
            end
        end
        rows_only_gams = length(grow) - length(seen_rows)
        # how many rows and columns only here, by equation and variable: the examples above are only the first few
        isempty(here_by) || pushfirst!(rhs, "only here, by name: " * join(("$k $n" for (k, n) in sort!(collect(here_by))), ", "))

        push!(tm, time())                            # this model's columns, rows and entries
        theirs = Tuple{UInt64,Float64}[]
        for r in SQLite.DBInterface.execute(db, "select i, j, value from a")
            push!(theirs, (pack(r[1], r[2]), Float64(r[3])))
        end
        push!(tm, time())                            # GAMS's entries read
        sort!(mine; by = first)
        sort!(theirs; by = first)
        push!(tm, time())                            # both sorted

        # merge: entries only in GAMS, only here, and with another value; counted by (equation, variable)
        place(k) = (i = Int(k >> 32); j = Int(k & 0xffffffff); (rname[i], cname[j]))
        tally = Dict{Tuple{Symbol,Symbol,Symbol},Int}()
        example = Dict{Tuple{Symbol,Symbol,Symbol},String}()
        function note(kind, k, text)
            (rn, cn) = place(k)
            t = (kind, rn[1], cn[1])
            tally[t] = get(tally, t, 0) + 1
            haskey(example, t) || (example[t] = "$(rn[1])($(lab(rn[2]))) x $(cn[1])($(lab(cn[2]))): $text")
        end
        a, b, missing_, extra, different, worst = 1, 1, 0, 0, 0, 0.0
        # per equation: [entries in GAMS, entries here, equal, other value, only here, only in GAMS], largest relative difference of an equal pair
        byeq = Dict{Symbol,Vector{Int}}()
        eqworst = Dict{Symbol,Float64}()
        eqof(k) = rname[Int(k >> 32)][1]
        function cnt!(key, slot)
            cntv = get!(() -> zeros(Int, 6), byeq, eqof(key))
            cntv[slot] += 1
        end
        largest, zeros_both = 0.0, 0
        while a <= length(mine) || b <= length(theirs)
            ka = a <= length(mine) ? mine[a][1] : typemax(UInt64)
            kb = b <= length(theirs) ? theirs[b][1] : typemax(UInt64)
            if ka == kb
                x, y = mine[a][2], theirs[b][2]
                cnt!(ka, 1); cnt!(ka, 2)
                if !near(x, y)
                    different += 1
                    worst = max(worst, abs(x - y) / max(abs(x), abs(y)))
                    note(:different, ka, "here $x, GAMS $y")
                    cnt!(ka, 4)
                else
                    cnt!(ka, 3)
                    if x == 0 && y == 0
                        zeros_both += 1
                    elseif x != y
                        reld = abs(x - y) / max(abs(x), abs(y))
                        largest = max(largest, reld)
                        eqn = eqof(ka); eqworst[eqn] = max(get(eqworst, eqn, 0.0), reld)
                    end
                end
                a += 1; b += 1
            elseif ka < kb
                extra += 1; note(:only_here, ka, "here $(mine[a][2])"); cnt!(ka, 2); cnt!(ka, 5); a += 1
            else
                missing_ += 1; note(:only_gams, kb, "GAMS $(theirs[b][2])"); cnt!(kb, 1); cnt!(kb, 6); b += 1
            end
        end

        push!(tm, time())                            # merged
        println(io, "\nMatrix against GAMS, entry by entry")
        println(io, "rows       here ", sum(length(r.refs) for r in values(m.rows); init = 0), "   GAMS ", length(grow), "   only here ", rows_only_here, "   only in GAMS ", rows_only_gams)
        println(io, "columns    here ", JuMP.num_variables(m.jump), "   GAMS ", length(gcol), "   only here ", cols_only_here, "   only in GAMS ", cols_only_gams)
        println(io, "entries    here ", length(mine), "   GAMS ", length(theirs), "   only here ", extra, "   only in GAMS ", missing_, "   other value ", different,
            different > 0 ? "   (largest relative difference $(round(worst; sigdigits = 3)))" : "")
        println(io, "right-hand sides that differ ", rhs_off, "   column bounds that differ ", bnd_off,
            rhs_rounding > 0 ? "   right-hand sides equal within rounding of cancelled constants $rhs_rounding" : "")
        println(io, "equal entries: largest relative difference ", round(largest; sigdigits = 3), " (tolerance ", tol, "); ", zeros_both, " are zero on both sides (EPS in GAMS)")
        nrows = Dict{Symbol,Int}()
        for rn in values(rname)
            nrows[rn[1]] = get(nrows, rn[1], 0) + 1
        end
        equations = Any[]
        println(io, "\n", rpad("equation", 16), lpad("rows", 10), lpad("entries GAMS", 14), lpad("here", 12), lpad("equal", 12), lpad("other", 8), lpad("only here", 11), lpad("only GAMS", 11), "   largest rel. diff. of equal entries")
        for eqn in sort!(collect(keys(byeq)); by = q -> -byeq[q][1])
            c6 = byeq[eqn]
            println(io, rpad(eqn, 16), lpad(get(nrows, eqn, 0), 10), lpad(c6[1], 14), lpad(c6[2], 12), lpad(c6[3], 12), lpad(c6[4], 8), lpad(c6[5], 11), lpad(c6[6], 11), "   ", round(get(eqworst, eqn, 0.0); sigdigits = 3))
            push!(equations, (name = String(eqn), rows = get(nrows, eqn, 0), entries_gams = c6[1], entries_here = c6[2], equal = c6[3], different = c6[4],
                only_here = c6[5], only_gams = c6[6], largest_relative_difference = get(eqworst, eqn, 0.0)))
        end
        details = Any[]
        for (t, n) in sort!(collect(tally); by = x -> -x[2])
            what = t[1] == :different ? "other value" : t[1] == :only_here ? "only here" : "only in GAMS"
            println(io, "  ", rpad(what, 13), rpad(t[2], 14), " x ", rpad(t[3], 12), lpad(n, 9), "   e.g. ", example[t])
            push!(details, (kind = what, equation = String(t[2]), variable = String(t[3]), entries = n, example = example[t]))
        end
        foreach(x -> println(io, "  ", x), rhs)
        foreach(x -> println(io, "  ", x), bnd)
        same = rows_only_here + rows_only_gams + cols_only_here + cols_only_gams + extra + missing_ + different + rhs_off + bnd_off == 0
        println(io, same ? "the same linear program as GAMS" : "NOT the same linear program as GAMS")
        return (rows_gams = length(grow), columns_gams = length(gcol), entries_here = length(mine), entries_gams = length(theirs),
            rows_only_here, rows_only_gams, columns_only_here = cols_only_here, columns_only_gams = cols_only_gams,
            entries_only_here = extra, entries_only_gams = missing_, entries_different = different, worst_relative_difference = worst,
            rhs_different = rhs_off, rhs_rounding, bounds_different = bnd_off, details, examples = vcat(rhs, bnd), tolerance = tol, same_model = same,
            largest_relative_difference_equal = largest, entries_zero_both = zeros_both, equations,
            seconds = (gams_rows_columns = round(tm[2] - tm[1]; digits = 1), here = round(tm[3] - tm[2]; digits = 1),
                       gams_entries = round(tm[4] - tm[3]; digits = 1), sort = round(tm[5] - tm[4]; digits = 1),
                       merge = round(tm[6] - tm[5]; digits = 1)))
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

# One of write_matrix's files: the numbers gathered in a buffer and written a block at a time (one write per 1 M
# numbers instead of one per number), in the same order, so the file is the same.
mutable struct Block{T}
    io::IOStream
    buf::Vector{T}
    n::Int
end
Block{T}(path::AbstractString) where {T} = Block{T}(open(path, "w"), Vector{T}(undef, 1 << 20), 0)
@inline function put_block!(b::Block{T}, x::T) where {T}
    b.n == length(b.buf) && flush_block!(b)
    @inbounds b.buf[b.n += 1] = x
    return b
end
flush_block!(b::Block) = (b.n > 0 && write(b.io, view(b.buf, 1:b.n)); b.n = 0; b)
done!(b::Block) = (flush_block!(b); close(b.io))

# The model's own store of the rows and bounds (MOI's model under JuMP: the cache of the caching optimizer), read
# without building JuMP's objects, as attach_highs! reads it for HiGHS
matrix_source(jm::JuMP.Model) = (b = JuMP.backend(jm); b isa MOI.Utilities.CachingOptimizer ? b.model_cache : b)

# The bounds of all columns by JuMP index, read at once, as JuMP.is_fixed / has_lower_bound / lower_bound / ... read
# them one by one: a fixed column its value on both sides (before its other bounds), a side without a bound +-Inf
function column_bounds(src)
    n = maximum((x.value for x in MOI.get(src, MOI.ListOfVariableIndices())); init = 0)
    lo, up = fill(-Inf, n), fill(Inf, n)
    for ci in MOI.get(src, MOI.ListOfConstraintIndices{MOI.VariableIndex,MOI.GreaterThan{Float64}}())
        lo[ci.value] = MOI.get(src, MOI.ConstraintSet(), ci).lower
    end
    for ci in MOI.get(src, MOI.ListOfConstraintIndices{MOI.VariableIndex,MOI.LessThan{Float64}}())
        up[ci.value] = MOI.get(src, MOI.ConstraintSet(), ci).upper
    end
    for ci in MOI.get(src, MOI.ListOfConstraintIndices{MOI.VariableIndex,MOI.EqualTo{Float64}}())
        lo[ci.value] = up[ci.value] = MOI.get(src, MOI.ConstraintSet(), ci).value
    end
    return lo, up
end

# One row from MOI's model: its right-hand side, and its terms as JuMP.constraint_object gives them. That drops the
# terms with a zero coefficient and adds up the terms of a variable that comes twice; a row with either (seen: the
# row that last met each column) is read through constraint_object itself, so the terms are the same either way.
function matrix_row!(src, ci::MOI.ConstraintIndex{MOI.ScalarAffineFunction{Float64},S}, c, i::Int32, seen::Vector{Int32},
                     rlo, rup, ai, aj, av) where {S}
    set = MOI.get(src, MOI.ConstraintSet(), ci)
    lo_, up_ = set isa MOI.EqualTo ? (set.value, set.value) : set isa MOI.GreaterThan ? (set.lower, Inf) :
               set isa MOI.LessThan ? (-Inf, set.upper) : (set.lower, set.upper)
    put_block!(rlo, Float64(lo_)); put_block!(rup, Float64(up_))
    f = MOI.get(src, MOI.ConstraintFunction(), ci)
    plain = true
    @inbounds for t in f.terms
        j = t.variable.value
        (iszero(t.coefficient) || seen[j] == i) && (plain = false; break)
        seen[j] = i
    end
    if plain
        for t in f.terms
            put_block!(ai, i); put_block!(aj, Int32(t.variable.value)); put_block!(av, Float64(t.coefficient))
        end
        return length(f.terms)
    end
    nt = 0
    for (x, a) in JuMP.constraint_object(c).func.terms
        put_block!(ai, i); put_block!(aj, Int32(JuMP.index(x).value)); put_block!(av, Float64(a)); nt += 1
    end
    return nt
end

# The columns of one variable (a function of its own, so that the loop is compiled for its key type)
function matrix_cols!(v::Var, name::Int32, cdim::Int, lo::Vector{Float64}, up::Vector{Float64}, cj, cn, clo, cup, ck)
    ncol = 0
    for (k, x) in v.x
        j = JuMP.index(x).value
        t = k isa Tuple ? k : (k,)
        put_block!(cj, Int32(j)); put_block!(cn, name); put_block!(clo, lo[j]); put_block!(cup, up[j])
        for n in 1:cdim
            put_block!(ck[n], n <= length(t) ? Int32(t[n]) : Int32(0))
        end
        ncol += 1
    end
    return ncol
end

"""
    write_matrix(m, dir) -> (rows, columns, entries)

The model's matrix for the matrix check without a second build (the files can be compared with GAMS's matrix
outside Julia): what `compare_matrix` takes from the model, written as it takes it. In `dir`:

- `names.txt`, `labels.txt`: equation and variable names, and the labels (`m.L`), one per line, numbered from 0 / 1;
- rows: `rows_name.i32` (number in names.txt), `rows_k<n>.i32` for n = 1..row_dims (label numbers, 0 past the
  row's arity), `rows_lower.f64`, `rows_upper.f64` (the right-hand side as compare_matrix reads the set),
  `rows_cancel.f64` (the size of constants that cancelled, 0.0 if none);
- columns (the variables of `m.v`): `cols_j.i32` (JuMP's index of the variable), `cols_name.i32`, `cols_k<n>.i32`,
  `cols_lower.f64`, `cols_upper.f64` (a fixed variable: its value on both);
- entries: `a_i.i32` (the row's position in rows, from 1), `a_j.i32` (the column's JuMP index), `a_value.f64`: every
  term, and every explicit zero (a coefficient of EPS);
- `meta.json`: counts, dimensions, the columns of the JuMP model (JuMP.num_variables, as compare_matrix reports).
Little-endian numbers, no header: numpy reads each file with fromfile.
"""
function write_matrix(m::Model, dir::AbstractString)
    mkpath(dir)
    names = String[]; nid = Dict{Symbol,Int32}()
    nm(s) = get!(() -> (push!(names, String(s)); Int32(length(names) - 1)), nid, s)
    tup(k) = k isa Tuple ? k : (k,)
    rdim = maximum((length(tup(k)) for r in values(m.rows) for k in r.keys); init = 0)
    cdim = maximum((length(tup(k)) for v in m.v for k in keys(v.x)); init = 0)
    f(T, n) = Block{T}(joinpath(dir, n))
    # columns
    cj, cn, clo, cup = f(Int32, "cols_j.i32"), f(Int32, "cols_name.i32"), f(Float64, "cols_lower.f64"), f(Float64, "cols_upper.f64")
    ck = [f(Int32, "cols_k$n.i32") for n in 1:cdim]
    ncol = 0
    src = matrix_source(m.jump)
    lo, up = column_bounds(src)
    for v in m.v
        isempty(v.x) || (ncol += matrix_cols!(v, nm(v.name), cdim, lo, up, cj, cn, clo, cup, ck))   # (a name only for a variable with columns, as before)
    end
    foreach(done!, (cj, cn, clo, cup)); foreach(done!, ck)
    seen = zeros(Int32, length(lo))
    lo = up = nothing
    # rows and entries
    rn, rlo, rup, rc = f(Int32, "rows_name.i32"), f(Float64, "rows_lower.f64"), f(Float64, "rows_upper.f64"), f(Float64, "rows_cancel.f64")
    rk = [f(Int32, "rows_k$n.i32") for n in 1:rdim]
    ai, aj, av = f(Int32, "a_i.i32"), f(Int32, "a_j.i32"), f(Float64, "a_value.f64")
    i, nent = 0, 0
    for (name, r) in sort!(collect(m.rows); by = first), (n, (k, c)) in enumerate(zip(r.keys, r.refs))
        i += 1
        t = tup(k)
        put_block!(rn, nm(name)); put_block!(rc, Float64(get(r.cancel, n, 0.0)))
        for q in 1:rdim
            put_block!(rk[q], q <= length(t) ? Int32(t[q]) : Int32(0))
        end
        nent += matrix_row!(src, JuMP.index(c), c, Int32(i), seen, rlo, rup, ai, aj, av)
        for x in get(r.zeros, n, ())
            put_block!(ai, Int32(i)); put_block!(aj, Int32(JuMP.index(x).value)); put_block!(av, 0.0); nent += 1
        end
    end
    foreach(done!, (rn, rlo, rup, rc, ai, aj, av)); foreach(done!, rk)
    open(io -> foreach(s -> println(io, s), names), joinpath(dir, "names.txt"), "w")
    open(io -> foreach(s -> println(io, s), m.L.names), joinpath(dir, "labels.txt"), "w")
    open(joinpath(dir, "meta.json"), "w") do io
        print(io, "{\"format\": 1, \"rows\": $i, \"columns\": $ncol, \"entries\": $nent, \"row_dims\": $rdim, \"col_dims\": $cdim, ",
              "\"jump_columns\": $(JuMP.num_variables(m.jump))}")
    end
    return (rows = i, columns = ncol, entries = nent)
end

"""
    matrix_rows(m) -> Vector{MOI.ConstraintIndex}

The constraint of each row of `write_matrix`, in its order (rows sorted by name, then as built): what lets the LP
solver through GAMS (GamsLP, `names`) find the TIMES name of each of its rows.
"""
matrix_rows(m::Model) = MOI.ConstraintIndex[JuMP.index(c) for (_, r) in sort!(collect(m.rows); by = first) for c in r.refs]
