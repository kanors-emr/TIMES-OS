# SPDX-License-Identifier: GPL-3.0-or-later
# Table types and loading.

"""Labels (regions, processes, years, ...) are numbered once at load; the equations work on the numbers."""
const Id = Int32

struct Labels
    names::Vector{String}
    ids::Dict{String,Id}
    years::Vector{Int}                # year of the label, or typemin(Int) when it is not a year
    raw::Dict{String,Id}              # the labels as spelled in the input file (load): skips uppercase on a repeat
end
Labels() = Labels(String[], Dict{String,Id}(), Int[], Dict{String,Id}())

"""Number of label `s` (added when new). TIMES labels are not case-sensitive."""
function id!(L::Labels, s::AbstractString)
    u = uppercase(s)
    get!(L.ids, u) do
        push!(L.names, u)
        push!(L.years, something(tryparse(Int, u), typemin(Int)))
        Id(length(L.names))
    end
end
label(L::Labels, i::Id) = L.names[i]
label(L::Labels, k::Tuple) = map(i -> L.names[i], k)
year(L::Labels, i::Id) = L.years[i]

keytype_of(n::Int) = n == 1 ? Id : NTuple{n,Id}

"""A set: `key in table`, and iteration in input order."""
struct Table{K}
    rows::Vector{K}
    set::Set{K}
end
Table{K}() where {K} = Table{K}(K[], Set{K}())
Base.in(k::K, t::Table{K}) where {K} = k in t.set
Base.in(k, t::Table{K}) where {K} = error("a key of this table has the form $K, got $(typeof(k))")
Base.iterate(t::Table, st...) = iterate(t.rows, st...)
Base.length(t::Table) = length(t.rows)
Base.isempty(t::Table) = isempty(t.rows)
Base.eltype(::Type{Table{K}}) where {K} = K

"""
GAMS' EPS: a zero that is on record. An entry that the input gives as 0 reads as `EPS`. Like EPS
in GAMS it tests as non-zero, vanishes when added to a number, and stays EPS when multiplied by
one; a coefficient that comes out as EPS is kept in the row as a zero (see `row!`).
`plain(x)` is the number to compare: 0 for EPS.
"""
const EPS = 1e-200
iseps(x::Real) = x != 0 && abs(x) < 1e-100
plain(x::Real) = abs(x) < 1e-100 ? 0.0 : Float64(x)
"""`a * b` where both may be EPS: EPS times EPS is EPS, and the product of the two small numbers would be 0."""
emul(a::Real, b::Real) = (x = a * b; (iszero(x) && !iszero(a) && !iszero(b)) ? EPS : x)

"""
A parameter. `P(r, t, p)` is the value, 0 when there is no entry and `EPS` for an entry of 0;
`has(P, r, t, p)` tells whether there is an entry; `P[r, t, p]` insists on one.
Iteration gives `(key, value)` in input order.
"""
struct Par{N}
    name::Symbol
    keys::Vector{NTuple{N,Id}}
    d::Dict{NTuple{N,Id},Float64}
end
Par{N}(name::Symbol) where {N} = Par{N}(name, NTuple{N,Id}[], Dict{NTuple{N,Id},Float64}())
(p::Par{N})(k::Vararg{Id,N}) where {N} = get(p.d, k, 0.0)
has(p::Par{N}, k::Vararg{Id,N}) where {N} = haskey(p.d, k)
function Base.getindex(p::Par{N}, k::Vararg{Id,N}) where {N}
    x = get(p.d, k, NaN)
    isnan(x) && error("$(p.name) has no entry for a key the equations need")
    return x
end
Base.iterate(p::Par, i::Int = 1) = i > length(p.keys) ? nothing : ((p.keys[i], p.d[p.keys[i]]), i + 1)
Base.length(p::Par) = length(p.keys)
Base.isempty(p::Par) = isempty(p.keys)

"""The entries `rng` of a parameter (positions in input order), iterated as the parameter is: for a family computed in
pieces (`PIECES`)."""
struct ParPart{N}
    p::Par{N}
    rng::UnitRange{Int}
end
Base.iterate(q::ParPart, i::Int = first(q.rng)) = i > last(q.rng) ? nothing : ((q.p.keys[i], q.p.d[q.p.keys[i]]), i + 1)
Base.length(q::ParPart) = length(q.rng)

"""Rows of a table grouped by some of its columns (see `INDEXES`)."""
struct Index{N,V}
    d::Dict{NTuple{N,Id},Vector{V}}
    none::Vector{V}
end
Base.getindex(ix::Index{N}, k::Vararg{Id,N}) where {N} = get(ix.d, k, ix.none)

function Index(rows, kpos::NTuple{N,Int}, vpos::NTuple{M,Int}) where {N,M}
    V = keytype_of(M)
    d = Dict{NTuple{N,Id},Vector{V}}()
    for k in rows
        val = M == 1 ? k[vpos[1]] : ntuple(i -> k[vpos[i]], M)
        push!(get!(() -> V[], d, ntuple(i -> k[kpos[i]], N)), val)
    end
    return Index{N,V}(d, V[])
end

# Concrete container types follow from the declarations in schema.jl.
const TABLES = merge(SETS, PARS)
const DataT = NamedTuple{keys(TABLES),
    Tuple{(Table{keytype_of(length(c))} for c in SETS)..., (Par{length(c)} for c in PARS)...}}
const BoundsT = NamedTuple{keys(VARS), Tuple{(Dict{NTuple{length(c),Id},NTuple{2,Float64}} for c in VARS)...}}
const KeywordsT = NamedTuple{KEYWORDS,NTuple{length(KEYWORDS),Id}}

function index_columns(table::Symbol, by)
    cols = TABLES[table]
    kpos = map(c -> something(findfirst(==(c), cols), 0), by)
    all(>(0), kpos) || error("index on $table: unknown column in $by")
    return kpos, Tuple(i for i in eachindex(cols) if !(i in kpos))
end
const IndexT = NamedTuple{keys(INDEXES), Tuple{(begin
        kpos, vpos = index_columns(spec...)
        Index{length(kpos),keytype_of(length(vpos))}
    end for spec in INDEXES)...}}

"""A preprocessed model, as read from a file."""
struct Data
    source::String
    L::Labels
    K::KeywordsT
    tables::DataT
    bounds::BoundsT
    other::Dict{Symbol,Int}           # row counts of the sets and parameters that are not read
    step::Int                         # step of a myopic run (0: the whole horizon at once)
    sbounds::Dict{Symbol,Any}         # stochastic TIMES: the bounds by SOW (VAS_<X> -> key with the SOW last => (lo, up))
end
Data(source::String, L::Labels, K::KeywordsT, tables::DataT, bounds::BoundsT, other::Dict{Symbol,Int}) =
    Data(source, L, K, tables, bounds, other, 0, Dict{Symbol,Any}())
Data(source::String, L::Labels, K::KeywordsT, tables::DataT, bounds::BoundsT, other::Dict{Symbol,Int}, step::Int) =
    Data(source, L, K, tables, bounds, other, step, Dict{Symbol,Any}())

"""Stochastic TIMES (stages.stc 12: SET VAR 'VAS'): the bounds of VAS_<X> are those of the variable family VAR_<X>
with the SOW as one more index (OBJZ and VAS_EXPOBJ have none)."""
is_vas(name::Symbol) = startswith(String(name), "VAS_") && haskey(VARS, vas_var(name))
vas_var(name::Symbol) = Symbol("VAR_", String(name)[5:end])
vas_arity(var::Symbol) = length(VARS[var]) + (var in (:OBJZ, :VAR_EXPOBJ) ? 0 : 1)
check_vas(name::Symbol, dim::Int) = dim == vas_arity(vas_var(name)) ||
    error("$name has $dim columns in the input, the equations expect $(vas_arity(vas_var(name)))")

fix_inf(x::Float64) = x >= 1e299 ? Inf : (x <= -1e299 ? -Inf : x)

"""
    load(path) -> Data

Read a preprocessed model from SQLite: one table per symbol (label columns, then the value for a
parameter, or level, marginal, lower, upper for a variable) and `__symbols(name, kind, dim)`.
`timespp` writes this layout; a GAMS GDX converted to SQLite has it too.
"""
function load(path::AbstractString)
    if use_tjb(path)                                               # the binary copy of the same tables (tjb.jl)
        d = load_tjb(tjb_path(path), path)
        d === nothing || return d
        wait_db3(path)                                             # it lacks a table these equations read
    end
    isfile(path) || error("no such file: $path")
    db = SQLite.DB(path)
    try
        L = Labels()
        sets = Dict{Symbol,Any}()
        pars = Dict{Symbol,Any}()
        bounds = Dict{Symbol,Any}()
        other = Dict{Symbol,Int}()
        for row in SQLite.DBInterface.execute(db, "select name, kind, dim from __symbols")
            name, kind, dim = Symbol(uppercase(String(row[1]))), String(row[2]), Int(row[3])
            sql = "select * from \"$(row[1])\""
            if kind == "set" && haskey(SETS, name)
                check_dim(name, dim, SETS[name])
                sets[name] = read_set(db, sql, L, Val(dim))
            elseif kind == "parameter" && haskey(PARS, name)
                check_dim(name, dim, PARS[name])
                pars[name] = read_par(db, sql, L, name, Val(dim))
            elseif kind == "variable" && haskey(VARS, name)
                check_dim(name, dim, VARS[name])
                bounds[name] = read_bounds(db, sql, L, Val(dim))
            elseif kind == "variable" && is_vas(name)
                check_vas(name, dim)
                bounds[name] = read_bounds(db, sql, L, Val(dim))
            elseif kind == "set" || kind == "parameter"
                n = first(SQLite.DBInterface.execute(db, "select count(*) from \"$(row[1])\""))[1]
                n > 0 && (other[name] = n)
            end
        end
        return Data(String(path), L, sets, pars, bounds, other)
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

function Data(source::String, L::Labels, sets::Dict{Symbol,Any}, pars::Dict{Symbol,Any}, bounds::Dict{Symbol,Any}, other::Dict{Symbol,Int})
    tables = DataT((
        (get(() -> Table{keytype_of(length(c))}(), sets, n) for (n, c) in pairs(SETS))...,
        (get(() -> Par{length(c)}(n), pars, n) for (n, c) in pairs(PARS))...))
    bnds = BoundsT(Tuple(get(() -> Dict{NTuple{length(c),Id},NTuple{2,Float64}}(), bounds, n) for (n, c) in pairs(VARS)))
    K = KeywordsT(map(k -> id!(L, String(k)), KEYWORDS))
    return Data(source, L, K, tables, bnds, other, 0, Dict{Symbol,Any}(n => b for (n, b) in bounds if is_vas(n)))
end

check_dim(name, dim, cols) = dim == length(cols) ||
    error("$name has $dim columns in the input, the equations expect $(length(cols)): $(join(cols, ", "))")

# The tables are read through the SQLite C interface with typed access: much faster than the rows of
# SQLite.jl on a large model, where each cell goes through a dynamic lookup of its type.
const SQ = SQLite.C

"""Call `f(handle)` for each row of `sql`."""
function each_row(f, db, sql)
    stmt = SQLite.Stmt(db, sql; register = false)
    h = SQLite._get_stmt_handle(stmt)
    try
        while true
            st = SQ.sqlite3_step(h)
            st == SQ.SQLITE_DONE && break
            st == SQ.SQLITE_ROW || SQLite.sqliteerror(db)
            f(h)
        end
    finally
        SQLite._close_stmt!(stmt)
    end
end

"""Column `i` (1-based) of the current row as text, as `string(row[i])` gives it."""
function cell_text(h, i)
    t = SQ.sqlite3_column_type(h, i - 1)
    t == SQ.SQLITE_TEXT && return unsafe_string(SQ.sqlite3_column_text(h, i - 1), SQ.sqlite3_column_bytes(h, i - 1))
    t == SQ.SQLITE_INTEGER && return string(SQ.sqlite3_column_int64(h, i - 1))
    t == SQ.SQLITE_FLOAT && return string(SQ.sqlite3_column_double(h, i - 1))
    return "missing"
end

"""Column `i` of the current row as a number."""
function cell_value(h, i)
    SQ.sqlite3_column_type(h, i - 1) == SQ.SQLITE_NULL && error("a value is NULL in the input")
    return SQ.sqlite3_column_double(h, i - 1)
end

"""The label in column `i`, numbered (the raw spelling is looked up first: no uppercase on a repeat)."""
function cell_id!(L::Labels, h, i)
    s = cell_text(h, i)
    get(L.raw, s) do
        L.raw[s] = id!(L, s)
    end
end

key(L::Labels, r, ::Val{N}) where {N} = ntuple(i -> id!(L, string(r[i])), N)
row_key(L::Labels, h, ::Val{N}) where {N} = ntuple(i -> cell_id!(L, h, i), N)

function read_set(db, sql, L, v::Val{N}) where {N}
    K = keytype_of(N)
    t = Table{K}()
    each_row(db, sql) do h
        k = N == 1 ? cell_id!(L, h, 1) : row_key(L, h, v)
        k in t.set && return
        push!(t.rows, k)
        push!(t.set, k)
    end
    return t
end

function read_par(db, sql, L, name, v::Val{N}) where {N}
    p = Par{N}(name)
    each_row(db, sql) do h
        k = row_key(L, h, v)
        haskey(p.d, k) || push!(p.keys, k)
        x = fix_inf(cell_value(h, N + 1))
        p.d[k] = x == 0 ? EPS : x
    end
    return p
end

function read_bounds(db, sql, L, v::Val{N}) where {N}
    b = Dict{NTuple{N,Id},NTuple{2,Float64}}()
    each_row(db, sql) do h
        b[row_key(L, h, v)] = (fix_inf(cell_value(h, N + 3)), fix_inf(cell_value(h, N + 4)))
    end
    return b
end

"""
    steps(path) -> Vector{Tuple{Int,Int}}

The steps of a myopic run (TIMESTEP) in a preprocessed model: (step, first year of its window). Empty
for a model solved over the whole horizon at once.
"""
function steps(path::AbstractString)
    if !isfile(path) && use_tjb(path)          # no model.db3 (yet): a myopic run's steps come after model.tjb (tjb.jl, wait_steps)
        tjb_steps(tjb_path(path)) || return Tuple{Int,Int}[]
        wait_steps(path)
    end
    f = steps_file(path)
    isfile(f) || error("no such file: $path")
    db = SQLite.DB(f)
    try
        has = !isempty(SQLite.DBInterface.execute(db, "select name from sqlite_master where name = '__steps'") |> collect)
        has || return Tuple{Int,Int}[]
        return [(Int(r[1]), Int(r[2])) for r in SQLite.DBInterface.execute(db, "select distinct step, year from __steps order by step")]
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

"""
    load_step(d, k) -> Data

The model of step k of a myopic run: the tables the preprocessor wrote for that step (`__step<k>_<name>`)
replace those of `d`. The vintages after the window are taken out of the vintage tables (solve.stp:
V(FORWARD) = NO), so that no row or cost refers to the new capacity of the periods after the window.
"""
function load_step(d::Data, k::Int)
    db = SQLite.DB(steps_file(d.source))
    try
        sets, pars, bounds = Dict{Symbol,Any}(), Dict{Symbol,Any}(), Dict{Symbol,Any}()
        for row in SQLite.DBInterface.execute(db, "select name, kind, dim from __steps where step = $k")
            name, kind, dim = Symbol(uppercase(String(row[1]))), String(row[2]), Int(row[3])
            sql = "select * from \"__step$(k)_$(row[1])\""
            if kind == "set" && haskey(SETS, name)
                sets[name] = read_set(db, sql, d.L, Val(dim))
            elseif kind == "parameter" && haskey(PARS, name)
                pars[name] = read_par(db, sql, d.L, name, Val(dim))
            elseif kind == "variable" && haskey(VARS, name)
                bounds[name] = read_bounds(db, sql, d.L, Val(dim))
            end
        end
        isempty(sets) && isempty(pars) && error("no step $k in $(d.source)")
        fwd = Set(get(sets, :FORWARD, d.tables.FORWARD).rows)
        for name in (:RTP_VINTYR, :RTP_CPTYR)
            src = get(sets, name, getfield(d.tables, name))
            t = Table{NTuple{4,Id}}()
            for key in src.rows
                key[2] in fwd && continue
                push!(t.rows, key); push!(t.set, key)
            end
            sets[name] = t
        end
        tables = DataT(map(keys(TABLES)) do n
            haskey(sets, n) ? sets[n] : haskey(pars, n) ? pars[n] : getfield(d.tables, n)
        end)
        bnds = BoundsT(map(n -> get(bounds, n, getfield(d.bounds, n)), keys(VARS)))
        return Data(d.source, d.L, d.K, tables, bnds, d.other, k, d.sbounds)
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

"""
    load_point(d, k) -> Dict{Symbol,Dict{Tuple,Float64}}

The levels of the solution point that step k of a run with FIXBOH loads (spoint.mod 43-47: execute_loadpoint of an
earlier run's results), as the preprocessor wrote them for the periods it fixes (`__step<k>_<VAR>`, kind "level" in
__steps). Empty for a step without one.
"""
function load_point(d::Data, k::Int)
    lev = Dict{Symbol,Dict{Tuple,Float64}}()
    f = steps_file(d.source)
    isfile(f) || return lev
    db = SQLite.DB(f)
    try
        has = !isempty(SQLite.DBInterface.execute(db, "select name from sqlite_master where name = '__steps'") |> collect)
        has || return lev
        tabs = [(String(r[1]), Int(r[2])) for r in SQLite.DBInterface.execute(db, "select name, dim from __steps where step = $k and kind = 'level'")]
        for (tab, dim) in tabs
            name = Symbol(uppercase(tab))
            haskey(VARS, name) || continue
            x = lev[name] = Dict{Tuple,Float64}()
            each_row(db, "select * from \"__step$(k)_L_$(tab)\"") do h
                x[row_key(d.L, h, Val(dim))] = Float64(cell_value(h, dim + 1))
            end
        end
        return lev
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

"""Variable levels of a GAMS solution file, with the labels of `d` (for `check_solution`)."""
function load_levels(d::Data, path::AbstractString)
    db = SQLite.DB(path)
    try
        lev = Dict{Symbol,Dict{Tuple,Float64}}()
        for row in SQLite.DBInterface.execute(db, "select name, kind, dim from __symbols")
            name, dim = Symbol(uppercase(String(row[1]))), Int(row[3])
            (String(row[2]) == "variable" && haskey(VARS, name)) || continue
            x = lev[name] = Dict{Tuple,Float64}()
            for r in SQLite.DBInterface.execute(db, "select * from \"$(row[1])\"")
                x[key(d.L, r, Val(dim))] = Float64(r[dim+1])
            end
        end
        return lev
    finally
        SQLite.close(db)   # Windows keeps an open file locked (a run that removes it fails)
    end
end

"""Features the input uses whose equations are not written yet: `what => tables of the input that need it`."""
unsupported(d::Data) = [what => [n for n in names if get(d.other, n, 0) > 0] for (what, names) in UNSUPPORTED
                        if any(get(d.other, n, 0) > 0 for n in names)]

"""Stop when the input uses a feature whose equations are not written yet (all of them are named)."""
function check_supported(d::Data; strict::Bool = true)
    u = unsupported(d)
    isempty(u) && return
    msg = "TIMES features not supported yet: " * join(("$what (the model has $(join(used, ", ")))" for (what, used) in u), "; ")
    strict ? error(msg) : @warn msg
end

"""Non-empty sets and parameters of the input that the equations do not read (name => rows)."""
unread(d::Data) = sort!(collect(d.other); by = first)
