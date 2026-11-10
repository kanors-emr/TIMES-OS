# SPDX-License-Identifier: GPL-3.0-or-later
# Python's arithmetic and iteration orders, for kernels whose reference sums floats in an order Python chooses.
#
# A float sum depends on the order of its terms, so a kernel that is to give the reference's result to the bit sums
# in the reference's order. Where the reference iterates a list, that is the list's order; where it iterates a
# Python set, it is the set's slot order, which `pyset_order` reproduces (CPython's setobject.c: open addressing,
# linear probing over 10 slots, then perturbation; resized when 3/5 full). Only sets of tuples of small non-negative
# integers are reproduced (their hash is tuplehash over the integers themselves); the caller checks the order it got
# against Python's own sets (objective.py does, for INVSPRED).
#
# `pysum` is the builtin sum() over floats: plain left-to-right addition up to Python 3.11, Neumaier's compensated
# sum from 3.12 (bltinmodule.c). `pydiv` and `pypow` stop where Python raises (a division by zero, a power that
# overflows): the kernel declines, and the reference raises as it would.

const XXPRIME_1 = 0x9e3779b185ebca87         # 11400714785074694791
const XXPRIME_2 = 0xc2b2ae3d27d4eb4f         # 14029467366897019727
const XXPRIME_5 = 0x27d4eb2f165667c5         # 2870177450012600261

"""hash() of a Python tuple of non-negative integers below 2^61 - 1 (tupleobject.c, tuplehash)."""
function pyhash(t::NTuple{N,Int}) where {N}
    acc = XXPRIME_5
    for x in t
        0 <= x < (1 << 61) - 1 || throw(Decline("a tuple element outside the integers whose hash is the integer"))
        acc += UInt64(x) * XXPRIME_2
        acc = (acc << 31) | (acc >> 33)
        acc *= XXPRIME_1
    end
    acc += UInt64(N) ⊻ (XXPRIME_5 ⊻ UInt64(3527539))
    acc == typemax(UInt64) ? UInt64(1546275796) : acc
end

const LINEAR_PROBES = 9
const PERTURB_SHIFT = 5

"""The order in which Python iterates `s = set(); s.update(elems)` (elems: the elements in the order they are added;
repeats are skipped, as by the set)."""
function pyset_order(elems::Vector{T}) where {T<:Tuple}
    mask = 7
    keys = Vector{Union{Nothing,T}}(nothing, 8)
    hashes = zeros(UInt64, 8)
    fill = 0
    for e in elems
        h = pyhash(e)
        # set_add_entry: the slot of e, or e itself already there
        i = h & UInt64(mask)
        perturb = h
        found = false
        slot = -1
        while slot < 0
            probes = (i + LINEAR_PROBES <= mask) ? LINEAR_PROBES : 0
            j = Int(i)
            while true
                k = keys[j+1]
                if k === nothing
                    slot = j
                    break
                elseif hashes[j+1] == h && k == e
                    found = true
                    slot = j
                    break
                end
                probes == 0 && break
                probes -= 1
                j += 1
            end
            slot >= 0 && break
            perturb >>= PERTURB_SHIFT
            i = (i * 5 + 1 + perturb) & UInt64(mask)
        end
        found && continue
        keys[slot+1] = e
        hashes[slot+1] = h
        fill += 1
        if fill * 5 >= mask * 3
            # set_table_resize(so, used > 50000 ? used*2 : used*4): the entries reinserted in slot order
            minused = fill > 50000 ? fill * 2 : fill * 4
            newsize = 8
            while newsize <= minused
                newsize <<= 1
            end
            oldk, oldh = keys, hashes
            mask = newsize - 1
            keys = Vector{Union{Nothing,T}}(nothing, newsize)
            hashes = zeros(UInt64, newsize)
            for s in eachindex(oldk)
                k = oldk[s]
                k === nothing && continue
                hh = oldh[s]
                # set_insert_clean
                ii = hh & UInt64(mask)
                pp = hh
                while true
                    if keys[ii+1] === nothing
                        keys[ii+1] = k; hashes[ii+1] = hh
                        break
                    end
                    done = false
                    if ii + LINEAR_PROBES <= mask
                        for jj in 1:LINEAR_PROBES
                            if keys[ii+jj+1] === nothing
                                keys[ii+jj+1] = k; hashes[ii+jj+1] = hh
                                done = true
                                break
                            end
                        end
                    end
                    done && break
                    pp >>= PERTURB_SHIFT
                    ii = (ii * 5 + 1 + pp) & UInt64(mask)
                end
            end
        end
    end
    T[k for k in keys if k !== nothing]
end

"""sum() over floats as the running Python does it (py312: Neumaier's compensation, Python 3.12 and later)."""
struct PySum
    py312::Bool
end
function (S::PySum)(itr)
    f = 0.0
    if !S.py312
        for x in itr
            f += Float64(x)
        end
        return f
    end
    c = 0.0
    for x in itr
        x = Float64(x)
        t = f + x
        if abs(f) >= abs(x)
            c += (f - t) + x
        else
            c += (x - t) + f
        end
        f = t
    end
    (c != 0 && isfinite(c)) ? f + c : f
end

"""a / b, declining where Python raises ZeroDivisionError."""
@inline pydiv(a::Real, b::Real) = iszero(b) ? throw(Decline("a division by zero (the reference raises)")) : a / b

@static if Sys.iswindows()
    cpow_(x::Float64, y::Float64) = ccall((:pow, "ucrtbase"), Float64, (Float64, Float64), x, y)
    cexp(x::Float64) = ccall((:exp, "ucrtbase"), Float64, (Float64,), x)
else
    cpow_(x::Float64, y::Float64) = ccall(:pow, Float64, (Float64, Float64), x, y)
    cexp(x::Float64) = ccall(:exp, Float64, (Float64,), x)
end

"""x ** y for floats, as Python: the C library's pow; declining where Python raises (0 to a negative power, a result
that overflows, a negative number to a fractional power)."""
function pypow(x::Real, y::Real)
    x, y = Float64(x), Float64(y)
    y == 0 && return 1.0
    x == 0 && y < 0 && throw(Decline("0 to a negative power (the reference raises)"))
    x < 0 && !isinteger(y) && isfinite(y) && throw(Decline("a negative number to a fractional power"))
    r = cpow_(x, y)
    isinf(r) && isfinite(x) && isfinite(y) && throw(Decline("a power that overflows (the reference raises)"))
    r
end

"""math.exp, declining where Python raises (OverflowError)."""
function pyexp(x::Real)
    r = cexp(Float64(x))
    isinf(r) && isfinite(x) && throw(Decline("exp overflows (the reference raises)"))
    r
end

"""max(a, b) and min(a, b) as Python's builtins: the first argument unless the second is strictly greater (smaller)."""
@inline pymax(a, b) = b > a ? b : a
@inline pymin(a, b) = b < a ? b : a

"""GAMS ROUND (prep/common.py rnd): half away from zero, an integer."""
@inline function rnd(x::Real)
    isfinite(x) || throw(Decline("ROUND of a value that is not finite (the reference raises)"))
    x >= 0 ? floor(Int, x + 0.5) : -floor(Int, -x + 0.5)
end
@inline rnd(x::Integer) = Int(x)

"""math.floor / math.ceil: an integer, declining where Python raises (a value that is NaN or infinite)."""
@inline pyfloor(x::Real) = isfinite(x) ? floor(Int, x) : throw(Decline("FLOOR of a value that is not finite (the reference raises)"))
@inline pyceil(x::Real) = isfinite(x) ? ceil(Int, x) : throw(Decline("CEIL of a value that is not finite (the reference raises)"))
@inline pyfloor(x::Integer) = Int(x)
@inline pyceil(x::Integer) = Int(x)
