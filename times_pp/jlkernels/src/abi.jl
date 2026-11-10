# SPDX-License-Identifier: GPL-3.0-or-later
# The calls from the preprocessor (timespp/kernels.py) into Julia: columns in, columns out, through C pointers.
#
# Python loads libjulia into its own process (ctypes) and calls the C functions below, whose pointers __init__ makes
# with @cfunction. A column is a pointer, an element type and a length; Julia wraps the caller's memory (no copy) and
# the kernel returns new Julia vectors, kept in RESULTS under a handle until the caller has copied them and calls
# tpk_free. Nothing crosses as a Julia or Python object, so the kernels are compiled for plain Vector{Int32} /
# Vector{Float64} ... and the precompile workload covers exactly what a run calls.
#
# An error inside a kernel never unwinds into Python (which would end the process): tpk_call catches it and returns
# 1; tpk_error gives the message.

"""for i in r; f(i); end, in Julia's threads when it has more than one (TIMESPP_KERNELS_THREADS). With one thread the
loop runs in the caller: `Threads.@threads` would queue its tasks on thread 1, which is Python's main thread, and a
kernel called from another Python thread (side.py) would wait for them for ever."""
function pfor(f, r)
    if Threads.nthreads() == 1
        for i in r
            f(i)
        end
    else
        Threads.@threads :dynamic for i in r
            f(i)
        end
    end
    nothing
end

const ELTYPES = (Int32, Int64, Float64, UInt8)          # type codes 1, 2, 3, 4 (kernels.py: _TYPES)
typecode(::Type{T}) where {T} = Int32(findfirst(==(T), ELTYPES))

const KERNELS = Dict{String,Function}()              # name -> f(cols::Vector{Any})::Vector{Any}
const RESULTS = Dict{Int64,Vector{Any}}()
const NEXT = Ref{Int64}(0)
const LAST_ERROR = Ref{String}("")
const ERROR_BUF = Ref{Vector{UInt8}}(UInt8[0])
const TIMES = Dict{String,Vector{Float64}}()         # name -> [calls, seconds, compile seconds] (kernels.py: report)

function wrap(p::Ptr{Cvoid}, t::Int32, n::Int64)
    T = ELTYPES[t]
    n == 0 && return T[]
    unsafe_wrap(Array, Ptr{T}(p), n; own = false)
end

"""Run kernel `name` on the columns: the same as tpk_call, for Julia (tests, the precompile workload)."""
function call_kernel(name::String, cols::Vector{Any})
    f = KERNELS[name]
    t0 = time_ns()
    c0 = Base.cumulative_compile_time_ns()[1]
    out = f(cols)::Vector{Any}
    c1 = Base.cumulative_compile_time_ns()[1]
    tm = get!(() -> zeros(3), TIMES, name)
    tm[1] += 1; tm[2] += (time_ns() - t0) / 1e9; tm[3] += (c1 - c0) / 1e9
    out
end

function tpk_call(name::Cstring, nin::Int32, ptrs::Ptr{Ptr{Cvoid}}, types::Ptr{Int32}, lens::Ptr{Int64},
                  handle::Ptr{Int64})::Int32
    try
        cols = Any[wrap(unsafe_load(ptrs, i), unsafe_load(types, i), unsafe_load(lens, i)) for i in 1:nin]
        out = call_kernel(unsafe_string(name), cols)
        h = (NEXT[] += 1)
        RESULTS[h] = out
        unsafe_store!(handle, h)
        return Int32(0)
    catch e
        LAST_ERROR[] = sprint(showerror, e, catch_backtrace())
        return Int32(1)
    end
end

tpk_ncols(h::Int64)::Int32 = Int32(length(RESULTS[h]))

function tpk_col(h::Int64, i::Int32, ptr::Ptr{Ptr{Cvoid}}, typ::Ptr{Int32}, len::Ptr{Int64})::Int32
    v = RESULTS[h][i]
    unsafe_store!(ptr, Ptr{Cvoid}(pointer(v)))
    unsafe_store!(typ, typecode(eltype(v)))
    unsafe_store!(len, Int64(length(v)))
    Int32(0)
end

function tpk_free(h::Int64)::Int32
    delete!(RESULTS, h)
    Int32(0)
end

function tpk_error()::Ptr{UInt8}
    ERROR_BUF[] = Vector{UInt8}(LAST_ERROR[] * "\0")
    pointer(ERROR_BUF[])
end

"""Compile and run seconds of each kernel since the start, as text (name calls seconds compile)."""
function tpk_times()::Ptr{UInt8}
    s = join(("$k $(Int(v[1])) $(v[2]) $(v[3])" for (k, v) in TIMES), "\n")
    ERROR_BUF[] = Vector{UInt8}(s * "\0")
    pointer(ERROR_BUF[])
end

const CPTR = Dict{Symbol,Ptr{Cvoid}}()

function make_cfunctions()
    CPTR[:call] = @cfunction(tpk_call, Int32, (Cstring, Int32, Ptr{Ptr{Cvoid}}, Ptr{Int32}, Ptr{Int64}, Ptr{Int64}))
    CPTR[:ncols] = @cfunction(tpk_ncols, Int32, (Int64,))
    CPTR[:col] = @cfunction(tpk_col, Int32, (Int64, Int32, Ptr{Ptr{Cvoid}}, Ptr{Int32}, Ptr{Int64}))
    CPTR[:free] = @cfunction(tpk_free, Int32, (Int64,))
    CPTR[:error] = @cfunction(tpk_error, Ptr{UInt8}, ())
    CPTR[:times] = @cfunction(tpk_times, Ptr{UInt8}, ())
end

"""The C pointers, as one text line `name=address ...` (kernels.py reads it once at the start)."""
cpointers() = join(("$k=$(UInt(v))" for (k, v) in CPTR), " ")
