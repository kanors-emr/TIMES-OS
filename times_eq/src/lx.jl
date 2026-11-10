# SPDX-License-Identifier: GPL-3.0-or-later
# Rows built in plain arrays (LX) for the equation families that cost the most to build, added to the JuMP model
# directly as MOI constraints. The variables, the model and everything that reads it stay JuMP's.
#
# An LX is the list of terms of an affine expression: JuMP variable indices and coefficients, appended as they come,
# and a constant. The arithmetic is JuMP's, in JuMP's order, so that every coefficient is the same to the last bit:
# where JuMP's ordered dictionary sums a variable's coefficients (each sub-expression before it is scaled or added into
# another one) an LX is collapsed (`flat!`), summing a column's terms in the order they came. The rows of a family come
# out the same, entry for entry and in the same order, as through JuMP expressions.
#
# TIMESEQ_ARRAY_ROWS=0 builds every row through JuMP expressions, as before.

const ARRAY_ROWS = Ref(true)
array_rows() = ARRAY_ROWS[]

"""The expression type a family builds its rows with: LX, or JuMP's AffExpr (TIMESEQ_ARRAY_ROWS=0)."""
exprtype() = array_rows() ? LX : AE

mutable struct LX
    cols::Vector{Int64}         # JuMP variable index values
    vals::Vector{Float64}
    constant::Float64
    cm::Float64                 # size of the constants added with add! (NaN: none recorded, see cmag)
    flat::Bool                  # no column twice
end
# an expression without terms shares these two empty vectors until its first term (many partial sums stay empty)
const NOC = Int64[]
const NOV = Float64[]
LX() = LX(NOC, NOV, 0.0, NaN, true)
LX(c::Real) = LX(NOC, NOV, Float64(c), NaN, true)
@inline own!(e::LX) = (e.cols === NOC && (e.cols = Int64[]; e.vals = Float64[]); e)
@inline col(x::JuMP.VariableRef) = JuMP.index(x).value

# Scratch, one set per thread (families are built side by side in threads, see build_parallel!): for collapsing, the
# position of a column in the expression being collapsed and a stamp of that expression; and the row being assembled.
# A function using it never yields, so no other task runs on its thread meanwhile.
mutable struct Scratch
    pos::Vector{Int32}
    stamp::Vector{Int32}
    cur::Int32
    row::LX
end
Scratch() = Scratch(Int32[], Int32[], Int32(0), LX(Int64[], Float64[], 0.0, NaN, true))
const SCRATCH = Scratch[]
function ensure_scratch!()
    while length(SCRATCH) < Threads.maxthreadid()
        push!(SCRATCH, Scratch())
    end
end
@inline scratch() = @inbounds SCRATCH[Threads.threadid()]

function flat!(e::LX)
    e.flat && return e
    cols, vals = e.cols, e.vals
    n = length(cols)
    n == 0 && (e.flat = true; return e)
    S = scratch()
    POS, STAMP = S.pos, S.stamp
    mx = maximum(cols)
    if length(STAMP) < mx
        old = length(STAMP)
        resize!(POS, mx); resize!(STAMP, mx)
        fill!(view(STAMP, old+1:mx), Int32(0))
    end
    if S.cur == typemax(Int32)
        fill!(STAMP, Int32(0)); S.cur = 0
    end
    st = (S.cur += Int32(1))
    k = 0
    @inbounds for j in 1:n
        c = cols[j]
        if STAMP[c] == st
            vals[POS[c]] += vals[j]
        else
            STAMP[c] = st
            k += 1
            POS[c] = k
            cols[k] = c
            vals[k] = vals[j]
        end
    end
    resize!(cols, k); resize!(vals, k)
    e.flat = true
    return e
end

cmag(x::LX) = isnan(x.cm) ? abs(x.constant) : x.cm

@inline function push_term!(e::LX, c::Int64, v::Float64)
    own!(e)
    push!(e.cols, c); push!(e.vals, v)
    e.flat = false
    return e
end

"""An AffExpr (already collapsed: a dictionary) as an LX, its terms in the dictionary's order."""
function lx(x::AE)
    n = length(x.terms)
    n == 0 && return LX(x.constant)
    cols = Vector{Int64}(undef, n); vals = Vector{Float64}(undef, n)
    i = 0
    for (v, a) in x.terms
        i += 1; cols[i] = col(v); vals[i] = a
    end
    return LX(cols, vals, x.constant, NaN, true)
end
lx(x::LX) = x
lx(x::JuMP.VariableRef) = LX(Int64[col(x)], Float64[1.0], 0.0, NaN, true)
lx(x::Real) = LX(x)

# e += k*x as JuMP's add_to_expression!: every term of x (collapsed) times k, and the constant; no zero test
function _addto!(e::LX, k::Float64, x::LX)
    flat!(x)
    if !isempty(x.cols)
        own!(e)
        for j in eachindex(x.cols)
            push!(e.cols, x.cols[j]); push!(e.vals, k * x.vals[j])
        end
        e.flat = false
    end
    e.constant += k * x.constant
    return e
end
# e += x (JuMP's add_to_expression!(e, x) merges the terms with +, without multiplying)
function _addto1!(e::LX, x::LX)
    flat!(x)
    if !isempty(x.cols)
        own!(e); append!(e.cols, x.cols); append!(e.vals, x.vals); e.flat = false
    end
    e.constant += x.constant
    return e
end

# ---------------------------------------------------------------- add! and addto!, as model.jl has them for AffExpr
function add!(e::LX, k::Real, x::Real)
    e.constant += k * x
    iszero(k * x) || (e.cm = cmag(e) + abs(k * x))
    return e
end
add!(e::LX, k::Real, x::JuMP.VariableRef) = (iszero(k) || push_term!(e, col(x), Float64(k)); e)
function add!(e::LX, k::Real, x::Union{LX,AE})
    iszero(k) && return e
    c = cmag(x)
    iszero(c) || (e.cm = cmag(e) + abs(k) * c)
    _addto!(e, Float64(k), lx(x))
    return e
end

"""`addto!(e, k, x)`: JuMP's add_to_expression!(e, k, x) for either expression type (no zero test, no record of constants)."""
addto!(e::AE, k::Real, x) = JuMP.add_to_expression!(e, k, x)
addto!(e::LX, k::Real, x::JuMP.VariableRef) = push_term!(e, col(x), Float64(k))
addto!(e::LX, k::Real, x::Union{LX,AE}) = _addto!(e, Float64(k), lx(x))
addto!(e::LX, k::Real, x::Real) = (e.constant += k * x; e)

# ---------------------------------------------------------------- operators: a new expression, as JuMP's
Base.copy(e::LX) = isempty(e.cols) ? LX(NOC, NOV, e.constant, NaN, true) : LX(copy(e.cols), copy(e.vals), e.constant, NaN, e.flat)
# a copy with room for `extra` more terms (the copies below always grow)
function _copy(e::LX, extra::Int)
    isempty(e.cols) && extra == 0 && return LX(NOC, NOV, e.constant, NaN, true)
    n = length(e.cols)
    cols = Vector{Int64}(undef, n); vals = Vector{Float64}(undef, n)
    sizehint!(cols, n + extra); sizehint!(vals, n + extra)
    copyto!(cols, e.cols); copyto!(vals, e.vals)
    return LX(cols, vals, e.constant, NaN, e.flat)
end
Base.:+(a::LX, b::LX) = _addto1!(_copy(flat!(a), length(flat!(b).cols)), b)
Base.:-(a::LX, b::LX) = _addto!(_copy(flat!(a), length(flat!(b).cols)), -1.0, b)
# expression -/+ variable: JuMP's add_to_expression!(copy, -1.0 / 1.0, x)
Base.:-(a::LX, x::JuMP.VariableRef) = push_term!(_copy(flat!(a), 1), col(x), -1.0)
Base.:+(a::LX, x::JuMP.VariableRef) = push_term!(_copy(flat!(a), 1), col(x), 1.0)
Base.:+(a::LX, b::AE) = a + lx(b)
Base.:-(a::LX, b::AE) = a - lx(b)
Base.:+(a::Union{AE,JuMP.VariableRef}, b::LX) = lx(a) + b
Base.:-(a::Union{AE,JuMP.VariableRef}, b::LX) = lx(a) - b
Base.:+(a::LX, b::Real) = (e = copy(flat!(a)); e.constant += b; e)
Base.:+(a::Real, b::LX) = b + a
Base.:-(a::LX, b::Real) = (e = copy(flat!(a)); e.constant -= b; e)
Base.:-(a::Real, b::LX) = (e = _addto!(LX(), -1.0, b); e.constant += a; e)
Base.:-(a::LX) = -1.0 * a
function Base.:*(k::Real, a::LX)
    flat!(a)
    isempty(a.cols) && return LX(NOC, NOV, Float64(k) * a.constant, NaN, true)
    LX(copy(a.cols), Float64(k) .* a.vals, Float64(k) * a.constant, NaN, true)
end
Base.:*(a::LX, k::Real) = k * a
function Base.:/(a::LX, k::Real)                     # JuMP divides each coefficient (map_coefficients(c -> c / k))
    flat!(a)
    isempty(a.cols) && return LX(NOC, NOV, a.constant / k, NaN, true)
    LX(copy(a.cols), a.vals ./ k, a.constant / k, NaN, true)
end
Base.zero(::Type{LX}) = LX()
Base.iszero(a::LX) = isempty(flat!(a).cols) && iszero(a.constant)

# ---------------------------------------------------------------- sums: JuMP.@expression(model, sum(...)) for LX
# MutableArithmetics evaluates sum(a * b * ... * x for ...) as add_mul(acc, a, b, ..., x): the factors before the last
# are multiplied from the left, then acc += product * x without a zero test.
_addmul!(acc::LX, a::Real, b::Real, c, rest...) = _addmul!(acc, a * b, c, rest...)
_addmul!(acc::LX, k::Real, x::JuMP.VariableRef) = push_term!(acc, col(x), Float64(k))
_addmul!(acc::LX, k::Real, x::Union{LX,AE}) = _addto!(acc, Float64(k), lx(x))
_addmul!(acc::LX, k::Real, x::Real) = (acc.constant += k * x; acc)
_addmul!(acc::LX, x::JuMP.VariableRef) = push_term!(acc, col(x), 1.0)
_addmul!(acc::LX, x::Union{LX,AE}) = _addto1!(acc, lx(x))
_addmul!(acc::LX, x::Real) = (acc.constant += x; acc)

# The generator as nested loops (as MutableArithmetics writes it for JuMP.@expression): `for a in A if c for b in B`
# becomes for a in A; c || continue; for b in B; acc += term; end; end. The term `f1 * f2 * ... * x` is added as
# _addmul!(acc, f1, f2, ..., x).
# a term x / k: JuMP multiplies a variable by inv(k) and divides each coefficient of an expression by k
_adddiv!(acc::LX, x::JuMP.VariableRef, k::Real) = push_term!(acc, col(x), inv(Float64(k)))
_adddiv!(acc::LX, x, k::Real) = _addmul!(acc, x / k)

function _lx_loops(ex, acc)
    ex isa Expr || error("@esum: a generator is expected")
    ex.head == :flatten && return _lx_loops(ex.args[1], acc)
    ex.head == :generator || error("@esum: a generator is expected")
    body = ex.args[1]
    inner = if body isa Expr && body.head in (:generator, :flatten)
        _lx_loops(body, acc)
    elseif body isa Expr && body.head == :call && body.args[1] == :*
        Expr(:call, :_addmul!, acc, body.args[2:end]...)
    elseif body isa Expr && body.head == :call && body.args[1] == :/ && length(body.args) == 3
        Expr(:call, :_adddiv!, acc, body.args[2], body.args[3])
    else
        Expr(:call, :_addmul!, acc, body)
    end
    return _lx_wrap(ex.args[2:end], inner)
end
function _lx_wrap(specs, inner)
    if length(specs) == 1 && specs[1] isa Expr && specs[1].head == :filter
        cond, sp = specs[1].args[1], specs[1].args[2:end]
        return Expr(:for, Expr(:block, sp...), Expr(:block, :($cond || continue), inner))
    end
    return Expr(:for, Expr(:block, specs...), inner)
end

"""
    @esum E model sum(term for ...)

`JuMP.@expression(model, sum(...))` when E is AffExpr; with E = LX the same sum into an LX, as nested loops, term by
term in the same order and with the same arithmetic.
"""
macro esum(E, model, ex)
    (ex isa Expr && ex.head == :call && ex.args[1] == :sum && length(ex.args) == 2) || error("@esum: sum(generator) expected")
    acc = gensym("acc")
    loops = _lx_loops(ex.args[2], acc)
    return esc(quote
        if $E === LX
            let $acc = LX()
                $loops
                $acc
            end
        else
            JuMP.@expression($model, $ex)
        end
    end)
end

# ---------------------------------------------------------------- a row from LX
"""`Scaled(k, e)`: k * e for a row, without making the product (row_lx! applies k while it copies e)."""
struct Scaled
    k::Float64
    e::LX
end
cmag(x::Scaled) = abs(x.k * x.e.constant)       # k * e is a new expression: no constants recorded on it

# The row as the JuMP expression lhs - rhs would be: the left-hand side copied (times k for a product; its constant
# taken as it is, not added to zero, so that a -0.0 stays), then add_to_expression!(e, -1.0, rhs). The terms of a row
# are collected in ROW (the thread's scratch row, one row at a time), then collapsed.
function _lhs!(ROW::LX, x::LX, k::Float64, mult::Bool)
    flat!(x)
    for j in eachindex(x.cols)
        push!(ROW.cols, x.cols[j]); push!(ROW.vals, mult ? k * x.vals[j] : x.vals[j])
    end
    ROW.constant = mult ? k * x.constant : x.constant
end
_lhs!(ROW::LX, x::Scaled) = _lhs!(ROW, x.e, x.k, true)
_lhs!(ROW::LX, x::LX) = _lhs!(ROW, x, 1.0, false)
_lhs!(ROW::LX, x::AE) = _lhs!(ROW, lx(x), 1.0, false)
_lhs!(ROW::LX, x::JuMP.VariableRef) = (push!(ROW.cols, col(x)); push!(ROW.vals, 1.0); ROW.constant = 0.0)
function _minus!(ROW::LX, x::LX)
    flat!(x)
    for j in eachindex(x.cols)
        push!(ROW.cols, x.cols[j]); push!(ROW.vals, -1.0 * x.vals[j])
    end
    ROW.constant += -1.0 * x.constant
end
_minus!(ROW::LX, x::AE) = _minus!(ROW, lx(x))
_minus!(ROW::LX, x::JuMP.VariableRef) = (push!(ROW.cols, col(x)); push!(ROW.vals, -1.0))
_minus!(ROW::LX, x::Real) = (ROW.constant -= x)

function row_lx!(m, name::Symbol, key::Tuple, lhs, sense, rhs)
    csize = cmag(lhs) + cmag(rhs)
    lhs isa AE && delete!(cmagd(), lhs); rhs isa AE && delete!(cmagd(), rhs)
    e = scratch().row
    empty!(e.cols); empty!(e.vals)
    if lhs isa Real
        # a number minus an expression: JuMP negates the expression into a new one, then adds the number
        e.constant = 0.0
        _minus!(e, rhs)
        e.constant += lhs
    else
        _lhs!(e, lhs)
        _minus!(e, rhs)
    end
    e.flat = false
    flat!(e)
    m.buf === nothing || return rec_row!(m, name, key, e.cols, e.vals, sense, -e.constant, csize)
    terms = MOI.ScalarAffineTerm{Float64}[]
    zeros = JuMP.VariableRef[]
    nz = 0
    @inbounds for j in eachindex(e.cols)
        a = e.vals[j]
        iszero(a) && continue                           # JuMP.drop_zeros!
        nz += 1
        c = e.cols[j]
        push!(m.used, c)
        if iseps(a)                                     # a coefficient of EPS: listed, not in the row
            push!(zeros, JuMP.VariableRef(m.jump, MOI.VariableIndex(c)))
        else
            push!(terms, MOI.ScalarAffineTerm(a, MOI.VariableIndex(c)))
        end
    end
    nz == 0 && return norow!(m, name, key, sense, plain(-e.constant), csize)
    c = plain(-e.constant)
    f = MOI.ScalarAffineFunction(terms, 0.0)
    set = sense == EQ ? MOI.EqualTo(c) : sense == LE ? MOI.LessThan(c) : sense == GE ? MOI.GreaterThan(c) : MOI.Interval(-Inf, Inf)
    ref = JuMP.ConstraintRef(m.jump, MOI.add_constraint(JuMP.backend(m.jump), f, set), JuMP.ScalarShape())
    r = get!(Rows, m.rows, name)
    push!(r.keys, key)
    push!(r.refs, ref)
    isempty(zeros) || (r.zeros[length(r.refs)] = zeros)
    (csize > 0 && abs(c) <= 1e-9 * csize) && (r.cancel[length(r.refs)] = csize)
    return
end
