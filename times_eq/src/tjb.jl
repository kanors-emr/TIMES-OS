# SPDX-License-Identifier: GPL-3.0-or-later
# model.tjb: the binary copy of the tables that times_pp writes next to model.db3 (version 1: times_pp/timespp/export.py,
# to_bin, describes the layout; version 2, in pieces: times_pp/timespp/tjb.py). It holds the same rows in the same
# order, with the labels numbered: reading it gives the same Data as reading model.db3 (the same labels in the same
# order, so the same numbers), without parsing text.
# `load("model.db3")` reads model.tjb instead when it is of the same run: model.db3 is not there yet (times_pp
# writes model.tjb first and model.db3 under its final name only when complete), or its table __tjb has the token
# of model.tjb. TIMESEQ_TJB=0 always reads model.db3.

tjb_path(path::AbstractString) = string(first(splitext(path)), ".tjb")

"""The token of a model.tjb, or `nothing` if the file is not one."""
function tjb_token(path::AbstractString)
    isfile(path) || return nothing
    open(path) do io
        String(read(io, 4)) in ("TJB1", "TJB2") || return nothing
        return read(io, UInt64)
    end
end

"""The token written into model.db3 with its model.tjb (none in a file of an older times_pp)."""
function db3_token(path::AbstractString)
    db = SQLite.DB(path)
    try
        isempty(SQLite.DBInterface.execute(db, "select name from sqlite_master where name = '__tjb'") |> collect) && return nothing
        return UInt64(only(r[1] for r in SQLite.DBInterface.execute(db, "select token from __tjb")))
    finally
        SQLite.close(db)
    end
end

"""Use the model.tjb next to `path` rather than `path` itself?"""
function use_tjb(path::AbstractString)
    get(ENV, "TIMESEQ_TJB", "1") == "0" && return false
    endswith(lowercase(path), ".db3") || return false
    tok = tjb_token(tjb_path(path))
    tok === nothing && return false
    if !isfile(path)
        f = folder_token(path)                 # times_pp wrote the Parquet folder in place of model.db3
        return f === nothing || f == tok
    end
    return db3_token(path) == tok
end

"""The Parquet folder times_pp writes in place of model.db3 (TIMESPP_DB3_STREAM: model.db3 -> model_parquet)."""
parquet_path(path::AbstractString) = string(first(splitext(path)), "_parquet")

"""The token of the Parquet folder in place of model.db3 (its __tjb.txt), or `nothing` if there is none."""
function folder_token(path::AbstractString)
    f = joinpath(parquet_path(path), "__tjb.txt")
    isfile(f) || return nothing
    return tryparse(UInt64, strip(read(f, String)))
end

"""The file of a myopic run's steps that times_pp writes beside the Parquet folder (model.db3 is not written then)."""
steps_path(path::AbstractString) = joinpath(dirname(abspath(path)), "model_steps.db3")

"""Where the steps of a myopic run are: model.db3 when it is there (it holds them), else model_steps.db3."""
steps_file(path::AbstractString) = isfile(path) ? path : steps_path(path)

"""Wait for the steps of a myopic run: model_steps.db3 of the token of the model.tjb beside `path` (times_pp writes it
after model.tjb, under its name only when complete), or model.db3 (at most an hour)."""
function wait_steps(path::AbstractString)
    tok, p, t = tjb_token(tjb_path(path)), steps_path(path), time()
    isfile(p) || release_db3()
    while time() - t < 3600
        isfile(path) && return
        isfile(p) && db3_token(p) == tok && return
        sleep(0.2)
    end
    error("the steps of this run ($p, or $path) did not come in an hour")
end

function load_tjb(path::AbstractString, source::AbstractString)
    open(path) do io
        magic = String(read(io, 4))
        magic == "TJB2" && return load_tjb2(io, path, source)
        magic == "TJB1" || error("$path is not a model.tjb")
        read(io, UInt64); read(io, UInt8)                              # token, myopic steps (in model.db3 or model_steps.db3)
        nl = Int(read(io, UInt64))
        lens = read!(io, Vector{UInt32}(undef, nl))
        bytes = read(io, Int(sum(UInt64, lens; init = UInt64(0))))
        names = Vector{String}(undef, nl)
        o = 0
        for i in 1:nl
            names[i] = String(bytes[o+1:o+lens[i]])
            o += Int(lens[i])
        end
        L = Labels()
        ids = zeros(Id, nl)
        # the number of label c (0-based in the file): given on first sight, in the order model.db3 would give them
        lab(c::Int32) = (i = ids[c+1]; i != 0 ? i : (s = names[c+1]; ids[c+1] = get(L.raw, s) do
            L.raw[s] = id!(L, s)
        end))
        sets = Dict{Symbol,Any}(); pars = Dict{Symbol,Any}(); bounds = Dict{Symbol,Any}(); other = Dict{Symbol,Int}()
        nt = Int(read(io, UInt64))
        for _ in 1:nt
            name = Symbol(uppercase(String(read(io, Int(read(io, UInt16))))))
            kind = read(io, UInt8); dim = Int(read(io, UInt8)); n = Int(read(io, UInt64)); data = read(io, UInt8) == 0x01
            nv = kind == 0x00 ? 0 : kind == 0x01 ? 1 : 2
            used = (kind == 0x00 && haskey(SETS, name)) || (kind == 0x01 && haskey(PARS, name)) || (kind == 0x02 && (haskey(VARS, name) || is_vas(name)))
            used && !data && return nothing          # a table these equations read that the writer left out: model.db3
            if !used
                data && skip(io, n * (4dim + 8nv))
                kind != 0x02 && n > 0 && (other[name] = n)
                continue
            end
            kind == 0x02 && is_vas(name) ? check_vas(name, dim) : check_dim(name, dim, kind == 0x00 ? SETS[name] : kind == 0x01 ? PARS[name] : VARS[name])
            cols = [read!(io, Vector{Int32}(undef, n)) for _ in 1:dim]
            vals = [read!(io, Vector{Float64}(undef, n)) for _ in 1:nv]
            if kind == 0x00
                sets[name] = tjb_set(cols, lab, n, Val(dim))
            elseif kind == 0x01
                pars[name] = tjb_par(name, cols, vals[1], lab, n, Val(dim))
            else
                bounds[name] = tjb_bounds(cols, vals[1], vals[2], lab, n, Val(dim))
            end
        end
        return Data(String(source), L, sets, pars, bounds, other)
    end
end

# Version 2 (times_pp/timespp/tjb.py): the tables in pieces, each with its own labels, written in any order; the index at
# the end lists them in the order of model.db3. The pieces are read in parallel; the labels are numbered on first sight,
# table by table in the index's order and row by row, as from version 1 (the same numbers); then each table is built in
# a task of its own (largest first), from those numbers: the same Data as from version 1, in a fraction of the time.
function load_tjb2(io::IO, path::AbstractString, source::AbstractString)
    seekend(io); skip(io, -12)
    at = read(io, UInt64)
    String(read(io, 4)) == "TJB2" || error("$path is not complete")
    seek(io, at)
    other = Dict{Symbol,Int}()
    todo = Tuple{Symbol,UInt8,Int,Int,UInt64}[]             # the tables these equations read: name, kind, dim, rows, offset
    for _ in 1:Int(read(io, UInt64))
        name = Symbol(uppercase(String(read(io, Int(read(io, UInt16))))))
        kind = read(io, UInt8); dim = Int(read(io, UInt8)); n = Int(read(io, UInt64)); data = read(io, UInt8) == 0x01
        off = read(io, UInt64)
        used = (kind == 0x00 && haskey(SETS, name)) || (kind == 0x01 && haskey(PARS, name)) || (kind == 0x02 && (haskey(VARS, name) || is_vas(name)))
        used && !data && return nothing          # a table these equations read that the writer left out: model.db3
        if !used
            kind != 0x02 && n > 0 && (other[name] = n)
            continue
        end
        kind == 0x02 && is_vas(name) ? check_vas(name, dim) : check_dim(name, dim, kind == 0x00 ? SETS[name] : kind == 0x01 ? PARS[name] : VARS[name])
        push!(todo, (name, kind, dim, n, off))
    end
    pieces = Vector{Tuple{Vector{String},Vector{Vector{Int32}},Vector{Vector{Float64}}}}(undef, length(todo))
    @sync for (i, (_, kind, dim, n, off)) in enumerate(todo)
        Threads.@spawn pieces[i] = tjb2_piece(path, off, dim, n, kind == 0x00 ? 0 : kind == 0x01 ? 1 : 2)
    end
    L = Labels()
    ids = [tjb2_ids!(L, p[1], p[2], t[4]) for (t, p) in zip(todo, pieces)]
    built = Vector{Any}(undef, length(todo))
    @sync for i in sortperm([t[4] for t in todo]; rev = true)
        Threads.@spawn begin
            name, kind, dim, n, _ = todo[i]
            _, cols, vals = pieces[i]
            idv = ids[i]
            lab = c -> idv[c+1]
            built[i] = kind == 0x00 ? tjb_set(cols, lab, n, Val(dim)) :
                       kind == 0x01 ? tjb_par(name, cols, vals[1], lab, n, Val(dim)) :
                                      tjb_bounds(cols, vals[1], vals[2], lab, n, Val(dim))
        end
    end
    sets = Dict{Symbol,Any}(); pars = Dict{Symbol,Any}(); bounds = Dict{Symbol,Any}()
    for (i, (name, kind, _, _, _)) in enumerate(todo)
        (kind == 0x00 ? sets : kind == 0x01 ? pars : bounds)[name] = built[i]
    end
    return Data(String(source), L, sets, pars, bounds, other)
end

"""A piece of a model.tjb of version 2: its labels, its columns of label numbers (0-based), its value columns."""
function tjb2_piece(path, off, dim, n, nv)
    open(path) do io
        seek(io, off)
        nl = Int(read(io, UInt32))
        lens = read!(io, Vector{UInt32}(undef, nl))
        bytes = read(io, Int(sum(UInt64, lens; init = UInt64(0))))
        names = Vector{String}(undef, nl)
        o = 0
        for i in 1:nl
            names[i] = String(bytes[o+1:o+lens[i]])
            o += Int(lens[i])
        end
        cols = [read!(io, Vector{Int32}(undef, n)) for _ in 1:dim]
        vals = [read!(io, Vector{Float64}(undef, n)) for _ in 1:nv]
        return (names, cols, vals)
    end
end

"""The number of each label of a piece, given on first sight (row by row, column by column, as version 1 reads)."""
function tjb2_ids!(L::Labels, names::Vector{String}, cols::Vector{Vector{Int32}}, n::Int)
    ids = zeros(Id, length(names))
    left = length(names)
    left == 0 && return ids
    for r in 1:n, col in cols
        c = col[r] + 1
        if ids[c] == 0
            s = names[c]
            ids[c] = get(L.raw, s) do
                L.raw[s] = id!(L, s)
            end
            (left -= 1) == 0 && return ids
        end
    end
    return ids
end

tjb_key(cols, lab, r, ::Val{N}) where {N} = ntuple(j -> lab(cols[j][r]), N)

function tjb_set(cols, lab, n, v::Val{N}) where {N}
    t = Table{keytype_of(N)}()
    for r in 1:n
        k = N == 1 ? lab(cols[1][r]) : tjb_key(cols, lab, r, v)
        m = length(t.set)
        push!(t.set, k)                          # one lookup: a key seen before leaves the set as it was
        length(t.set) > m && push!(t.rows, k)
    end
    return t
end

tjb_value(x::Float64) = (isnan(x) && error("a value is NULL in the input"); fix_inf(x))

function tjb_par(name, cols, vals, lab, n, v::Val{N}) where {N}
    p = Par{N}(name)
    for r in 1:n
        k = tjb_key(cols, lab, r, v)
        x = tjb_value(vals[r])
        m = length(p.d)
        p.d[k] = x == 0 ? EPS : x                # one lookup: the same Dict as haskey, then setindex!
        length(p.d) > m && push!(p.keys, k)
    end
    return p
end

function tjb_bounds(cols, lo, up, lab, n, v::Val{N}) where {N}
    b = Dict{NTuple{N,Id},NTuple{2,Float64}}()
    for r in 1:n
        b[tjb_key(cols, lab, r, v)] = (tjb_value(lo[r]), tjb_value(up[r]))
    end
    return b
end

"""
Say that model.db3 may be written now. TIMES.py holds the write back while the model is built (it would slow the
build), until this file (TIMESEQ_DB3_GO) exists: after the copy into HiGHS, when model.db3 itself is needed, and at the
end of the run.
"""
function release_db3()
    go = get(ENV, "TIMESEQ_DB3_GO", "")
    go == "" || isfile(go) || try
        touch(go)
    catch
    end
    return nothing
end

"""Wait for model.db3, which times_pp may still be writing after model.tjb (at most an hour); not when times_pp wrote
the Parquet folder in its place (it is not coming: it can be made from the folder)."""
function wait_db3(path::AbstractString)
    if !isfile(path) && isdir(parquet_path(path))
        error("$path is not there: times_pp wrote $(parquet_path(path)) in its place; make it with " *
              "python times_pp/tools/pq2db3.py $(parquet_path(path))")
    end
    isfile(path) || release_db3()
    t = time()
    while !isfile(path) && time() - t < 3600
        sleep(0.5)
    end
end

"""Is the model.tjb of a myopic run (its steps are in model.db3 or model_steps.db3 only)?"""
tjb_steps(path::AbstractString) = open(io -> (read(io, 4); read(io, UInt64); read(io, UInt8) == 0x01), path)
