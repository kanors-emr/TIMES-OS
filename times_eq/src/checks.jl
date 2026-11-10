# SPDX-License-Identifier: GPL-3.0-or-later
# Looking at a built model: sizes, the coefficient table, and a test against a known solution.

"""Rows per equation family."""
row_counts(m::Model) = Dict(name => length(r.refs) for (name, r) in m.rows)

"""Columns per variable family."""
column_counts(m::Model) = Dict(v.name => length(v.x) for v in m.v if !isempty(v.x))

"""Entries of the matrix, as GAMS counts them: coefficients of EPS included. The rows are counted in threads, in
chunks of up to 200,000 rows of one family (`constraint_object` copies each row's function out of the model and only
reads it: on one thread a long wait on a model of 19 M rows, between the build and the copy into HiGHS)."""
function nonzeros(m::Model)
    rs = collect(values(m.rows))
    n = sum(r -> sum(length, values(r.zeros); init = 0), rs; init = 0)
    chunks = [(r.refs, a, min(a + 199_999, length(r.refs))) for r in rs for a in 1:200_000:length(r.refs)]
    counts = zeros(Int, length(chunks))
    Threads.@threads :dynamic for j in eachindex(chunks)
        refs, a, b = chunks[j]
        s = 0
        for k in a:b
            s += length(JuMP.constraint_object(refs[k]).func.terms)
        end
        counts[j] = s
    end
    return n + sum(counts; init = 0)
end

"""
    triplets(f, m)

Call `f(equation, row_key, variable, column_key, coefficient)` for every non-zero of the matrix,
and `f(equation, row_key, :RHS, (), value)` for every row, with keys as tuples of labels. This is
the solver-independent statement of the model: two implementations of TIMES agree when they
produce the same table.
"""
function triplets(f, m::Model)
    column = Dict{JuMP.VariableRef,Tuple{Symbol,Tuple}}()
    for v in m.v, (k, x) in v.x
        column[x] = (v.name, label(m.L, k))
    end
    for name in sort!(collect(keys(m.rows))), (i, (k, c)) in enumerate(zip(m.rows[name].keys, m.rows[name].refs))
        o = JuMP.constraint_object(c)
        rk = label(m.L, k)
        for (x, a) in o.func.terms
            f(name, rk, column[x]..., a)
        end
        for x in get(m.rows[name].zeros, i, ())
            f(name, rk, column[x]..., 0.0)
        end
        f(name, rk, :RHS, (), MOI.constant(o.set))
    end
end

"""Write the coefficient table as CSV: equation, row, variable, column, coefficient."""
function write_triplets(path::AbstractString, m::Model)
    open(path, "w") do io
        println(io, "equation,row,variable,column,coefficient")
        triplets(m) do eq, rk, var, ck, a
            println(io, eq, ',', join(rk, '|'), ',', var, ',', join(ck, '|'), ',', repr(a))
        end
    end
end

"""
    check_solution(m, levels) -> Dict(equation => largest relative violation)

Evaluate every row at the variable levels of another solution of the same model, typically the
one GAMS found (`load_levels`). Variables without a level count as 0.
"""
function check_solution(m::Model, levels::Dict{Symbol,Dict{Tuple,Float64}})
    lev = Dict{JuMP.VariableRef,Float64}()
    for v in m.v
        l = get(levels, v.name, Dict{Tuple,Float64}())
        for (k, x) in v.x
            lev[x] = get(l, k, 0.0)
        end
    end
    out = Dict{Symbol,Float64}()
    for (name, r) in m.rows
        worst = 0.0
        for c in r.refs
            o = JuMP.constraint_object(c)
            a = JuMP.value(x -> lev[x], o.func)
            viol = o.set isa MOI.EqualTo ? abs(a - o.set.value) :
                   o.set isa MOI.LessThan ? max(0.0, a - o.set.upper) : max(0.0, o.set.lower - a)
            worst = max(worst, viol / max(1.0, abs(a)))
        end
        out[name] = worst
    end
    return out
end
