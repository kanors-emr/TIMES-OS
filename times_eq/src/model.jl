# SPDX-License-Identifier: GPL-3.0-or-later
# The model under construction: variables, rows, and what happens when an equation is added.

const AE = JuMP.AffExpr

"""
Stochastic TIMES (STAGES): the state of the world (SOW) of the row being built, and the maps of stages.stc that give a
variable its SOW (see stochastic.jl). `nothing` in a deterministic run.
"""
mutable struct SowCtx
    w::Id                                   # the SOW of the row being built (a SOW of the last stage)
    sows::Vector{Id}                        # SOW, in order
    swt::Set{NTuple{2,Id}}                  # SW_T(t,w): w is distinct in period t
    tsw::Dict{NTuple{2,Id},Id}              # SW_TSW(w,t,W): (w, t) => W, the SOW that represents w in period t
    reps::Dict{Id,Dict{Id,Id}}              # the same by SOW: w => (t => W)
    rep::Dict{Id,Id}                        # reps[w] (set with w by sow!)
    maps::Dict{Id,Dict{Id,Vector{NTuple{2,Id}}}}   # SW_MAP(t,w,j,ww) by SOW: w => (t => [(j, ww)] in the order of SW_MAP)
    map::Dict{Id,Vector{NTuple{2,Id}}}      # maps[w]
    dead::Set{Int64}                        # the columns of the variables of a SOW without a representative (DEAD)
    rowt::Id                                # the %SWT% period of a row whose key does not hold it (ROW_SOW -1)
    spines::Bool                            # SPINES: the capacity and its costs those of SOW '1' (w1) in every SOW
    scum::Bool                              # SPINES with %SCUM%: the cumulative rows written once, as expected values
    w1::Id                                  # SOW '1'
    sensis::Bool                            # SENSIS: one deterministic model of the SOW w (names and variables of TIMES)
    norm::Float64                           # SENSIS: SW_NORM, the probability of w in the first period
    members::Vector{Id}                     # SENSIS: the SOWs w represents in the first period (SOW of the solve)
end

"""
The variables a family asks for while it is built in a thread (`build_parallel!`): numbered 1, 2, ... in the order
they are first asked for (provisional numbers, the family's own), with the variable family of each. The commit
(`stage_vars!`) then asks the real variable families for them in that order, so that the variables are created exactly
as a build of one family after another creates them.
"""
mutable struct Rec
    n::Int
    owner::Vector{Int16}
end

"""
A variable family. `VAR_FLO(r, v, t, p, c, s)` returns the variable, creating it on first use
with the bounds given in the input. Only variables that an equation asks for exist.

Mutable on purpose, though no field is reassigned: an immutable `Var` is stored inline in the tuple
of families of a `Model`, so each staged model of a threaded build carries a copy of all of them,
and sweeping those copies takes most of the build's garbage collection.
"""
mutable struct Var{N}
    name::Symbol
    jump::JuMP.Model
    x::Dict{NTuple{N,Id},JuMP.VariableRef}
    bounds::Dict{NTuple{N,Id},NTuple{2,Float64}}
    free::Bool
    rec::Union{Nothing,Rec}                 # a family built in a thread: provisional variables (see Rec)
    log::Vector{NTuple{N,Id}}               # with rec: the keys in the order asked for
    vid::Int16                              # with rec: the position of the family in VARS
    sw::Union{Nothing,SowCtx}               # stochastic TIMES: the SOW is the last index (see the call without it)
    tpos::Int                               # stochastic TIMES: the position of the period in the key (0: none)
end
Var(name::Symbol, jump::JuMP.Model, x::Dict{NTuple{N,Id},JuMP.VariableRef}, bounds, free::Bool) where {N} =
    Var{N}(name, jump, x, bounds, free, nothing, NTuple{N,Id}[], Int16(0), nothing, 0)

function (v::Var{N})(k::Vararg{Id,N}) where {N}
    get!(v.x, k) do
        rec = v.rec
        if rec !== nothing
            rec.n += 1
            push!(rec.owner, v.vid); push!(v.log, k)
            return JuMP.VariableRef(v.jump, MOI.VariableIndex(rec.n))
        end
        JuMP.VariableRef(v.jump, add_column!(JuMP.backend(v.jump), var_bounds(v, k)...))
    end
end

"""The bounds of a variable of family `v`: those of the input, else 0 to +Inf (a free family: -Inf to +Inf)."""
var_bounds(v::Var{N}, k::NTuple{N,Id}) where {N} = get(v.bounds, k, (v.free ? -Inf : 0.0, Inf))

"""
A new column of the model (`back`, the JuMP model's backend) with the bounds `lo`, `up`: fixed where they are equal,
else the finite ones. Every variable of the model is added by it (`Var`, and `stage_rows!` for a family built in a
thread), so that the two cannot add them differently.
"""
function add_column!(back::MOI.ModelLike, lo::Float64, up::Float64)
    x = MOI.add_variable(back)
    if lo == up
        MOI.add_constraint(back, x, MOI.EqualTo(lo))
    else
        isfinite(lo) && MOI.add_constraint(back, x, MOI.GreaterThan(lo))
        isfinite(up) && MOI.add_constraint(back, x, MOI.LessThan(up))
    end
    return x
end

const VarsT = NamedTuple{keys(VARS),Tuple{(Var{length(c)} for c in VARS)...}}

@enum Sense LE EQ GE NB             # NB: a non-binding row (GAMS =N=), free

struct Rows
    keys::Vector{Any}                       # tuples of labels numbers; arity depends on the equation
    refs::Vector{JuMP.ConstraintRef}
    zeros::Dict{Int,Vector{JuMP.VariableRef}}   # row number => variables with a coefficient of EPS
    cancel::Dict{Int,Float64}               # row number => size of the constants that cancelled in its right-hand side
end
Rows() = Rows(Any[], JuMP.ConstraintRef[], Dict{Int,Vector{JuMP.VariableRef}}(), Dict{Int,Float64}())

"""The rows of a family built in a thread, over its provisional variables, until `stage_rows!` adds them to the model."""
struct Buf
    rec::Rec
    names::Vector{Symbol}
    keys::Vector{Any}
    stop::Vector{Int}                       # end of each row's terms in cols / vals
    cols::Vector{Int64}
    vals::Vector{Float64}
    sense::Vector{Sense}
    rhs::Vector{Float64}
    zeros::Vector{Pair{Int,Vector{Int64}}}  # row => variables with a coefficient of EPS
    cancel::Vector{Pair{Int,Float64}}       # row => size of the constants that cancelled
end
Buf(rec::Rec) = Buf(rec, Symbol[], Any[], Int[], Int64[], Float64[], Sense[], Float64[], Pair{Int,Vector{Int64}}[], Pair{Int,Float64}[])

# The size of the constant part of an expression: the sum of the absolute values of the numbers added to it with add!.
# Where they cancel, the right-hand side is a rounding remainder whose value depends on the order of the arithmetic;
# row! keeps the size for those rows, and the comparison with GAMS uses it.
# One dictionary per task: a family built in a thread has its own (task-local storage, :cmag).
const CMAG = IdDict{AE,Float64}()
@inline function cmagd()
    s = current_task().storage
    s === nothing && return CMAG
    return get(s, :cmag, CMAG)::IdDict{AE,Float64}
end
cmag(x::AE) = get(cmagd(), x, abs(x.constant))
cmag(x::Real) = abs(x)
cmag(x) = 0.0

struct Model{V}
    jump::JuMP.Model
    d::DataT                                # sets and parameters:   m.d.COEF_CPT(r, v, t, p)
    ix::IndexT                              # lookups:               m.ix.vintages[r, t, p]
    v::V                                    # variables:             m.v.VAR_NCAP(r, v, p)   (VarsT; VarsST with STAGES)
    K::KeywordsT                            # labels used by name:   m.K.ANNUAL
    L::Labels
    T::Vector{Id}                           # milestone years in ascending order
    rows::Dict{Symbol,Rows}
    used::BitSet                            # variables with a non-zero coefficient in some row
    cufscal::Float64                        # scaling of cumulative flow variables
    names::Bool
    sub::Set{Id}                            # periods of the window (myopic run); all periods otherwise
    fwd::Set{Id}                            # periods after the window: their vintages are left out
    stepped::Bool                           # a step of a myopic run
    rt::Union{Nothing,Set{NTuple{2,Id}}}    # FIXBOH: RT_PP, the periods of each region in the window (nothing otherwise)
    rtpx::Union{Nothing,Set{NTuple{3,Id}}}  # FIXBOH: RTPX, the trade processes whose EQ_IRE rows are written
    buf::Union{Nothing,Buf}                 # a family built in a thread: its rows go here (see build_parallel!)
    sw::Union{Nothing,SowCtx}               # stochastic TIMES (STAGES): the SOW of the rows being built
end

function Model(d::Data; cufscal::Float64 = 10.0, names::Bool = false)
    jump = JuMP.Model()
    JuMP.set_string_names_on_creation(jump, false)
    t = d.tables
    ix = IndexT(map(INDEXES) do (table, by)
        src = getfield(t, table)
        Index(src isa Par ? src.keys : src.rows, index_columns(table, by)...)
    end)
    empty!(CMAG)
    sw = sow_context(d)
    # (SENSIS: the variables of the deterministic model; VAS_EXPOBJ keeps its name, eqobj.mod 107)
    vname(n) = (sw !== nothing && sw.sensis && n == :VAR_EXPOBJ) ? :VAS_EXPOBJ : n
    v = (sw === nothing || sw.sensis) ?
        VarsT(map(n -> Var(vname(n), jump, Dict{NTuple{length(VARS[n]),Id},JuMP.VariableRef}(), d.bounds[n], n in FREE), keys(VARS))) :
        sow_vars(d, jump, sw)
    T = sort(t.MILESTONYR.rows; by = y -> year(d.L, y))
    sub = d.step > 0 ? Set{Id}(t.SUBT.rows) : Set{Id}(T)
    fwd = d.step > 0 ? Set{Id}(t.FORWARD.rows) : Set{Id}()
    fixb = d.step > 0 && !isempty(t.FIXB_RT)
    rt = fixb ? Set{NTuple{2,Id}}(t.FIXB_RT.rows) : nothing
    rtpx = fixb ? Set{NTuple{3,Id}}(t.FIXB_RTPX.rows) : nothing
    return Model(jump, t, ix, v, d.K, d.L, T, Dict{Symbol,Rows}(), BitSet(), cufscal, names, sub, fwd, d.step > 0, rt, rtpx, nothing, sw)
end

_recvar(x::Var{N}, rec::Rec, i::Int, sw) where {N} =
    Var{N}(x.name, x.jump, Dict{NTuple{N,Id},JuMP.VariableRef}(), x.bounds, x.free, rec, NTuple{N,Id}[], Int16(i),
           x.sw === nothing ? nothing : sw, x.tpos)

# The variable families of a recording view, one statement each: an `ntuple` over the families compiles for seconds,
# again in every task that inlines it.
@generated recvars(v::V, rec::Rec, sw) where {V<:NamedTuple} =
    :(V(($((:(_recvar(getfield(v, $i), rec, $i, sw)) for i in 1:fieldcount(V))...),)))

"""A view of `m` for one family built in a thread: the same data, its own variables (provisional), rows and `used`;
in a stochastic run (STAGES) the rows of SOW `w`, with a SOW context of its own (sow_copy)."""
@noinline function recording(m::Model, w::Union{Nothing,Id} = nothing)
    rec = Rec(0, Int16[])
    sw = m.sw === nothing ? nothing : sow_copy(m.sw, something(w, m.sw.w)::Id)
    v = recvars(m.v, rec, sw)
    return Model(m.jump, m.d, m.ix, v, m.K, m.L, m.T, Dict{Symbol,Rows}(), BitSet(), m.cufscal, m.names, m.sub, m.fwd,
                 m.stepped, m.rt, m.rtpx, Buf(rec), sw)
end

# A row left with no column is not in the model, in GAMS as here; one whose constant does not satisfy it makes GAMS
# list it under INFEASIBLE EQUATIONS and stop at the end of the generation ("equation infeasible due to rhs value").
# The port lists such rows as the families find them (`norow!`, from threads too) and stops at finish!, with all of
# them. GAMS takes a constant of at most 1e-15 as zero (2e-15 stops it); a constant left by constants that cancelled
# (at most 1e-9 of their size, as `cancel` on a row with columns) is zero here too.
const NOROW_INFES = Tuple{String,Sense,Float64}[]
const NOROW_LOCK = ReentrantLock()

function norow!(m::Model, name::Symbol, key::Tuple, sense::Sense, c::Float64, csize::Float64)
    (abs(c) <= 1e-15 || (csize > 0 && abs(c) <= 1e-9 * csize)) && return
    ok = sense == EQ ? false : sense == LE ? 0.0 <= c : sense == GE ? 0.0 >= c : true
    ok && return
    t = text(m, name, key)
    lock(() -> push!(NOROW_INFES, (t, sense, c)), NOROW_LOCK)
    return
end

"""Stop when a row with no column was left that its constant does not satisfy (`norow!`): every one is printed
(`  infeasible: <row>..  0 =E= <constant>`), and the error names the number and the first five."""
function check_norows()
    isempty(NOROW_INFES) && return
    rows = sort(NOROW_INFES; by = first)
    empty!(NOROW_INFES)
    sym = Dict(EQ => "=E=", LE => "=L=", GE => "=G=", NB => "=N=")
    lines = [string(t, "..  0 ", sym[s], " ", c) for (t, s, c) in rows]
    println("rows with no column whose constant does not satisfy them (INFEASIBLE EQUATIONS, as GAMS lists them):")
    foreach(l -> println("  infeasible: ", l), lines)
    flush(stdout)
    error("equation infeasible due to rhs value: ", length(rows), " row", length(rows) == 1 ? "" : "s",
          " with no column whose constant does not satisfy it, as GAMS stops on them; the first: ",
          join(first(lines, 5), "; "))
end

"""A row of a family built in a thread, as row! / row_lx! would add it: zero coefficients dropped, EPS ones listed."""
function rec_row!(m::Model, name::Symbol, key::Tuple, cols, vals, sense::Sense, negconst::Float64, csize::Float64)
    b = m.buf::Buf
    n0 = length(b.cols)
    zs = nothing
    nz = 0
    @inbounds for j in eachindex(cols)
        a = vals[j]
        iszero(a) && continue
        nz += 1
        c = cols[j]
        push!(m.used, c)
        if iseps(a)
            zs === nothing && (zs = Int64[])
            push!(zs, c)
        else
            push!(b.cols, c); push!(b.vals, a)
        end
    end
    nz == 0 && return norow!(m, name, key, sense, plain(negconst), csize)
    c = plain(negconst)
    push!(b.names, name); push!(b.keys, key); push!(b.stop, length(b.cols)); push!(b.sense, sense); push!(b.rhs, c)
    i = length(b.names)
    zs === nothing || push!(b.zeros, i => zs)
    (csize > 0 && abs(c) <= 1e-9 * csize) && push!(b.cancel, i => csize)
    push!(get!(Rows, m.rows, name).keys, key)       # the family's own rows, for a family that reads them (userco)
    return
end

"""
The commit of a family built in a thread, in two stages, so that the first stage of one family can run in a task
beside the second of the family before it (build_parallel!): `stage_vars!` looks up the real variable of each variable
of the recording, in the order it asked for them; one not in the model yet is entered in its family's table with the
number the model will give it (the numbers are consecutive: `Staged.next`) and listed with its bounds, but not added
to the model. `stage_rows!` adds the listed variables to the model in that order, with their bounds as a variable
family adds them (`Var`), checking that each gets the number it was given, then the rows in order (`commit_rows!`).
The first stage touches only the tables of the variable families, the second only the JuMP model, `rows` and `used`.
"""
mutable struct Staged
    next::Int64                                 # the number of the last variable entered
    new::Vector{Tuple{Float64,Float64,Int64}}   # the variables entered for one recording, in order: (lo, up, number)
end

function _stage1(v::Var{N}, k::NTuple{N,Id}, st::Staged) where {N}
    x = get!(v.x, k) do
        st.next += 1
        lo, up = var_bounds(v, k)
        push!(st.new, (lo, up, st.next))
        JuMP.VariableRef(v.jump, MOI.VariableIndex(st.next))
    end
    return JuMP.index(x).value
end
@generated function _stage1(vs::NamedTuple{K}, rvs::NamedTuple{K}, vid::Int, p::Int, st::Staged) where {K}
    ex = :(error("unknown variable family"))
    for i in length(K):-1:1
        ex = :(vid == $i ? _stage1(getfield(vs, $i), getfield(rvs, $i).log[p], st) : $ex)
    end
    return ex
end

function stage_vars!(m::Model, rm::Model, st::Staged)
    rec = (rm.buf::Buf).rec
    pmap = Vector{Int64}(undef, rec.n)
    pos = zeros(Int, length(m.v))
    @inbounds for s in 1:rec.n
        vid = Int(rec.owner[s])
        p = (pos[vid] += 1)
        pmap[s] = _stage1(m.v, rm.v, vid, p, st)
    end
    return pmap
end

function stage_rows!(m::Model, rm::Model, pmap::Vector{Int64}, new::Vector{Tuple{Float64,Float64,Int64}})
    back = JuMP.backend(m.jump)
    for (lo, up, k) in new                      # as Var adds a variable
        x = add_column!(back, lo, up)
        x.value == k || error("build_parallel!: variable numbered $(x.value), staged as $k")
    end
    commit_rows!(m, rm, pmap)
    return m
end

function commit_rows!(m::Model, rm::Model, pmap::Vector{Int64})
    b = rm.buf::Buf
    for c in rm.used
        push!(m.used, pmap[c])
    end
    back = JuMP.backend(m.jump)
    zi, ci, start = 1, 1, 1
    @inbounds for i in eachindex(b.names)
        stop = b.stop[i]
        terms = Vector{MOI.ScalarAffineTerm{Float64}}(undef, stop - start + 1)
        for j in start:stop
            terms[j-start+1] = MOI.ScalarAffineTerm(b.vals[j], MOI.VariableIndex(pmap[b.cols[j]]))
        end
        start = stop + 1
        f = MOI.ScalarAffineFunction(terms, 0.0)
        c, sense = b.rhs[i], b.sense[i]
        idx = sense == EQ ? MOI.add_constraint(back, f, MOI.EqualTo(c)) :
              sense == LE ? MOI.add_constraint(back, f, MOI.LessThan(c)) :
              sense == GE ? MOI.add_constraint(back, f, MOI.GreaterThan(c)) : MOI.add_constraint(back, f, MOI.Interval(-Inf, Inf))
        r = get!(Rows, m.rows, b.names[i])
        push!(r.keys, b.keys[i])
        push!(r.refs, JuMP.ConstraintRef(m.jump, idx, JuMP.ScalarShape()))
        if zi <= length(b.zeros) && b.zeros[zi].first == i
            r.zeros[length(r.refs)] = [JuMP.VariableRef(m.jump, MOI.VariableIndex(pmap[c])) for c in b.zeros[zi].second]
            zi += 1
        end
        if ci <= length(b.cancel) && b.cancel[ci].first == i
            r.cancel[length(r.refs)] = b.cancel[ci].second
            ci += 1
        end
    end
    return m
end

"""`add!(e, k, x)`: e += k*x, for x a number, a variable or an expression."""
function add!(e::AE, k::Real, x::Real)
    e.constant += k * x
    iszero(k * x) || (cmagd()[e] = cmag(e) + abs(k * x))
    return e
end
add!(e::AE, k::Real, x::JuMP.VariableRef) = (iszero(k) || JuMP.add_to_expression!(e, Float64(k), x); e)
function add!(e::AE, k::Real, x::AE)
    iszero(k) && return e
    c = cmag(x)
    iszero(c) || (cmagd()[e] = cmag(e) + abs(k) * c)
    JuMP.add_to_expression!(e, Float64(k), x)
    return e
end

"""
    row!(m, :EQ_NAME, key, lhs, ==, rhs)        # or <=, >=

Add one row of an equation family. As in GAMS, zero coefficients are dropped and a row that is
left without any variable is not generated. Also as in GAMS, a coefficient of EPS (a number
multiplied by a parameter entry of 0) keeps its place: the variable belongs to the row and to the
model, with a coefficient of zero. Such entries are counted and listed (`nonzeros`, `triplets`)
but not handed to the solver.
"""
# Equations that TIMES writes for the periods of the window only in a myopic run (%R_T%, %R_V_T%, %TX% in the
# GAMS code): the position of the period in the row key. The others (EQ_CPT, the objective, cumulative and
# global user constraints) are written for all periods.
const WINDOW_T = Dict{Symbol,Int}(
    (n => 3 for n in (:EQ_ACTFLO, :EQL_CAPACT, :EQE_CAPACT, :EQG_CAPACT, :EQE_ACTEFF, :EQL_CAFLAC, :EQE_CAFLAC, :EQG_CAFLAC, :EQL_CAPFLO,
        :EQL_INSHR, :EQE_INSHR, :EQG_INSHR, :EQL_OUTSHR, :EQE_OUTSHR, :EQG_OUTSHR, :EQL_ASHAR, :EQE_ASHAR, :EQG_ASHAR, :EQ_PTRANS,
        :EQ_CAPLOAD, :EQ_ACTRAMP, :EQ_ACTRMPC, :EQ_ACTPL, :EQE_ACTUPS, :EQL_ACTUPS, :EQL_ACTUPC, :EQ_SDLOGIC, :EQ_SUDUPT, :EQ_SDSLANT, :EQ_SDMINON, :EQ_SUDLOAD, :EQ_SUDTIME, :EQ_SUDPLL, :EQ_STGTSS, :EQ_STGIPS, :EQ_STGAUX, :EQL_REFIT, :EQN_UCRTP, :EQE_UCRTP, :EQL_STGCCL,
        :EQE_CAPVAC, :EQL_CAPVAC, :EQG_CAPVAC,
        # the ancillary balancing services over RTP_VINTYR(%R_V_T%,P) or RTP_VINTYR(%R_W_T%,P), %R_W_T% = BS_RVT(%R_V_T%) (equ_ext.abs)
        :EQ_BS05, :EQ_BS07, :EQ_BS09, :EQ_BS10, :EQ_BS11, :EQ_BS18, :EQ_BS19, :EQ_BS22, :EQ_BS23, :EQ_BS24, :EQ_BS25, :EQ_BS27, :EQ_BS28))...,
    (n => 2 for n in (:EQE_COMBAL, :EQG_COMBAL, :EQL_COMBAL, :EQE_COMPRD, :EQL_ACTBND, :EQE_ACTBND, :EQG_ACTBND,
        :EQL_BNDNET, :EQE_BNDNET, :EQG_BNDNET, :EQL_BNDPRD, :EQE_BNDPRD, :EQG_BNDPRD,
        :EQL_FLOBND, :EQE_FLOBND, :EQG_FLOBND, :EQL_BLND, :EQG_BLND, :EQE_BLND, :EQN_BLND, :EQL_FLOFR, :EQE_FLOFR, :EQG_FLOFR, :EQL_FLOMRK, :EQE_FLOMRK, :EQG_FLOMRK, :EQ_IRE, :EQ_PEAK,
        :EQL_STGIN, :EQE_STGIN, :EQG_STGIN, :EQL_STGOUT, :EQE_STGOUT, :EQG_STGOUT, :EQ_SLSIFT,
        :EQE_UCRT, :EQE_UCRTS, :EQE_UCRS, :EQ_GR_GENALL, :EQ_GR_DEMALL, :EQ_GR_POWFLO, :EQ_GG_MFLO, :EQ_GG_GAMA, :EQ_GG_MBND, :EQ_GG_WEYMTX,
        :EQL_IREBND, :EQE_IREBND, :EQG_IREBND, :EQL_XBND, :EQE_XBND, :EQG_XBND,
        :EQ_GG_HLIP, :EQ_GG_HLEV, :EQ_GG_PDIF1, :EQ_GG_PDIF2, :EQ_GG_STEP, :EQ_GG_PRIO, :EQ_GG_WEYMST,
        # the ancillary balancing services over RTC(%R_T%,C), %R_T% or RTP(%R_T%,P) (equ_ext.abs)
        :EQ_BS00, :EQ_BS01, :EQ_BS02, :EQ_BS03, :EQ_BS04, :EQ_BS26))...)
# Equations over vintages (index V): no row for a vintage after the window.
const WINDOW_V = Dict{Symbol,Int}(:EQL_SCAP => 2, :EQ_CUMRET => 2)
# In a run with FIXBOH the window is by region (maindrv.mod 41: %R_T% = RT_PP(R,SUBT(T)), %R_V_T% = RVT(R,V,SUBT(T)),
# RVT(R,VNT(V,T))$RT_PP(R,T), clearsol.stp 9): the rows of WINDOW_T are written for the periods of their region in
# RT_PP, except those over %TX% (SUBT(T) of all regions) and EQ_IRE (eqire.mod: RTP%RTPX%(REG,%TX%,P), RTPX).
# The position of the region in the key of a family of WINDOW_T whose key does not start with it (equcrtp.vda:
# RTP(%R_T%,P) after UC_N).
const WINDOW_R = Dict{Symbol,Int}(:EQN_UCRTP => 2, :EQE_UCRTP => 2)
const WINDOW_TX = (:EQL_IREBND, :EQE_IREBND, :EQG_IREBND, :EQL_XBND, :EQE_XBND, :EQG_XBND)
# Families over %R_T% / %R_V_T% that check the window themselves in a run with TIMESTEP: the position of the period.
const WINDOW_RT = Dict{Symbol,Int}(:EQ_STSBAL => 3, :EQ_DSCNCAP => 2, :EQ_DSCONE => 2, :EQ_GR_PTDFLO => 2, :EQ_GR_VIRTCAP => 2,
    :EQ_GR_VIRTBND => 2, :EQ_GR_XBND => 2, :EQ_RL_LOAD => 2, :EQ_RL_NDIS => 2, :EQ_RL_STCAP => 2, :EQ_RL_PKCAP => 2, :EQ_RL_THMIN => 2)
# Equations over RTS(S), the macro of dynamic timeslice trees (timslice.mod: S+NORTS(R,T,S)): no row on a timeslice off
# in the row's period. The positions of R, T and S in the row's key.
const RTS = Dict{Symbol,NTuple{3,Int}}(
    (n => (1, 3, 5) for n in (:EQ_ACTRAMP, :EQ_ACTPL, :EQ_SDMINON, :EQ_SUDLOAD, :EQ_STGTSS))...,
    (n => (1, 3, 6) for n in (:EQ_SDLOGIC, :EQ_SUDUPT, :EQ_SDSLANT, :EQ_SUDTIME, :EQ_SUDPLL, :EQ_STGAUX, :EQ_STSBAL))...,
    (n => (1, 3, 7) for n in (:EQE_ACTUPS, :EQL_ACTUPS, :EQL_ACTUPC, :EQL_ASHAR, :EQE_ASHAR, :EQG_ASHAR, :EQ_PTRANS, :EQE_ACTEFF))...,
    (n => (1, 2, 3) for n in (:EQ_RL_LOAD, :EQ_RL_NDIS, :EQ_RL_STCAP, :EQ_RL_PKCAP, :EQ_RL_THMIN))...,
    (n => (1, 2, 4) for n in (:EQ_PEAK, :EQE_UCRTS, :EQE_UCRSUS, :EQ_GR_POWFLO, :EQ_GR_GENALL, :EQ_GR_DEMALL))...,
    (n => (1, 2, 5) for n in (:EQ_SLSIFT, :EQE_UCRS, :EQ_GR_PTDFLO, :EQ_GR_VIRTCAP, :EQ_GR_XBND))...,
    (n => (1, 2, 7) for n in (:EQ_GG_MFLO, :EQ_GG_GAMA, :EQ_GG_WEYMTX, :EQ_GG_HLIP, :EQ_GG_HLEV, :EQ_GG_PDIF2, :EQ_GG_STEP))...,
    (n => (1, 2, 8) for n in (:EQ_GG_MBND, :EQ_GG_PDIF1, :EQ_GG_PRIO, :EQ_GG_WEYMST))...,
    # the ancillary balancing services (equ_ext.abs: every EQ_BS row is over RTS(S))
    (n => (1, 2, 3) for n in (:EQ_BS02,))...,
    (n => (1, 2, 4) for n in (:EQ_BS00, :EQ_BS01, :EQ_BS03, :EQ_BS04))...,
    (n => (1, 2, 5) for n in (:EQ_BS26,))...,
    (n => (1, 3, 5) for n in (:EQ_BS07, :EQ_BS09, :EQ_BS10, :EQ_BS18, :EQ_BS22, :EQ_BS23, :EQ_BS24, :EQ_BS25, :EQ_BS27, :EQ_BS28))...,
    (n => (1, 3, 6) for n in (:EQ_BS11, :EQ_BS19))...,
    (n => (1, 3, 7) for n in (:EQ_BS05,))...)

"""A milestone vintage whose new capacity is a variable of the model (not one after the window of a myopic step)."""
new_capacity(m::Model, v) = v in m.d.MILESTONYR && !(v in m.fwd)

function row!(m::Model, name::Symbol, key::Tuple, lhs, sense::Sense, rhs)
    if !isempty(m.d.NORTS)
        i = get(RTS, name, nothing)
        i === nothing || !has(m.d.NORTS, key[i[1]], key[i[2]], key[i[3]]) || return
    end
    if m.stepped
        i = get(WINDOW_T, name, 0)
        i > 0 && !(key[i] in m.sub) && return
        if m.rt !== nothing                             # FIXBOH: the periods of the row's region
            i > 0 || (i = get(WINDOW_RT, name, 0))
            if name == :EQ_IRE
                (key[1], key[2], key[3]) in m.rtpx || return
            elseif i > 0 && !(name in WINDOW_TX)
                (key[get(WINDOW_R, name, 1)], key[i]) in m.rt || return
            end
        end
        i = get(WINDOW_V, name, 0)
        i > 0 && key[i] in m.fwd && return
    end
    if m.sw !== nothing                                 # stochastic TIMES: the row of the SOW being built (stochastic.jl)
        name, key = sow_row(m, name, key)
        name === nothing && return
        lhs, rhs = sow_dead!(m.sw.dead, lhs), sow_dead!(m.sw.dead, rhs)
    end
    (lhs isa LX || rhs isa LX || lhs isa Scaled) && return row_lx!(m, name, key, lhs, sense, rhs)   # a row built in arrays (lx.jl)
    csize = cmag(lhs) + cmag(rhs)
    lhs isa AE && delete!(cmagd(), lhs); rhs isa AE && delete!(cmagd(), rhs)
    e = lhs - rhs
    e isa JuMP.VariableRef && (e = 1.0 * e)
    e isa Real && return norow!(m, name, key, sense, plain(-e), csize)
    e isa AE || return
    JuMP.drop_zeros!(e)
    isempty(e.terms) && return norow!(m, name, key, sense, plain(-e.constant), csize)
    if m.buf !== nothing                                # a family built in a thread: recorded, added by its commit
        cols = Int64[JuMP.index(x).value for x in keys(e.terms)]
        return rec_row!(m, name, key, cols, collect(values(e.terms)), sense, -e.constant, csize)
    end
    zeros = JuMP.VariableRef[]
    for (x, a) in e.terms
        push!(m.used, JuMP.index(x).value)
        iseps(a) && push!(zeros, x)
    end
    foreach(x -> delete!(e.terms, x), zeros)
    c = plain(-e.constant)
    e.constant = 0.0
    ref = sense == EQ ? JuMP.add_constraint(m.jump, JuMP.ScalarConstraint(e, MOI.EqualTo(c))) :
          sense == LE ? JuMP.add_constraint(m.jump, JuMP.ScalarConstraint(e, MOI.LessThan(c))) :
          sense == GE ? JuMP.add_constraint(m.jump, JuMP.ScalarConstraint(e, MOI.GreaterThan(c))) :
                        JuMP.add_constraint(m.jump, JuMP.ScalarConstraint(e, MOI.Interval(-Inf, Inf)))
    r = get!(Rows, m.rows, name)
    push!(r.keys, key)
    push!(r.refs, ref)
    isempty(zeros) || (r.zeros[length(r.refs)] = zeros)
    # constants that cancelled: the right-hand side is less than 1e-9 of the numbers that made it
    (csize > 0 && abs(c) <= 1e-9 * csize) && (r.cancel[length(r.refs)] = csize)
    return
end
row!(m::Model, name::Symbol, key::Tuple, lhs, ::typeof(==), rhs) = row!(m, name, key, lhs, EQ, rhs)
row!(m::Model, name::Symbol, key::Tuple, lhs, ::typeof(<=), rhs) = row!(m, name, key, lhs, LE, rhs)
row!(m::Model, name::Symbol, key::Tuple, lhs, ::typeof(>=), rhs) = row!(m, name, key, lhs, GE, rhs)

"""
Row name and sense of an equation generated per bound type, e.g. for `stem = "CAPACT"`:
UP -> (:EQL_CAPACT, <=), LO -> (:EQG_CAPACT, >=), FX -> (:EQE_CAPACT, ==).
With `share = true` the row is written as `share * group  (sense)  flow`, where a lower bound
on the share is the `<=` row: LO -> EQL, UP -> EQG.
"""
function by_bound(m::Model, stem::String; share::Bool = false)
    l, e, g = Symbol("EQL_", stem), Symbol("EQE_", stem), Symbol("EQG_", stem)
    (; LO, UP, FX) = m.K
    le = share ? LO : UP
    return function (bd::Id)
        bd == FX ? (e, EQ) : bd == le ? (l, LE) : (bd == LO || bd == UP) ? (g, GE) : error("EQ(l)_$stem: unknown bound type")
    end
end

"""Remove variables that ended up without a non-zero coefficient, set the objective, name rows and columns."""
function finish!(m::Model)
    check_norows()
    holdfixed!(m)
    drop_unused!(m)
    check_bounds(m)
    # (also marks the JuMP model as changed since its last solve, which the columns and rows added through its backend
    # (add_column!, commit_rows!, row_lx!) do not)
    # TIMES-MACRO (solve.mod 34): SOLVE TIMES_MACRO MAXIMIZING VAR_UTIL
    isempty(m.d.MLF) ? JuMP.@objective(m.jump, Min, m.v.OBJZ()) : JuMP.@objective(m.jump, Max, m.v.VAR_UTIL())
    m.names && name_all!(m)
    return m
end

# dynslite.vda BOUNDS, with dynamic timeslice trees (NORTS has records): %MODEL_NAME%.HOLDFIXED=1. GAMS takes a fixed
# column as a constant: its terms (an EPS coefficient too) go to the right-hand side, and a row left with no column is
# not in the model (a column then in no row leaves it too, drop_unused!). A row left with no column that its constant
# does not satisfy makes GAMS stop ("equation infeasible due to rhs value"); so does the port.
function holdfixed!(m::Model)
    isempty(m.d.NORTS) && return
    # A bound of 0 from an attribute is EPS in GAMS (a 0 is not stored), and LO 0 with UP EPS is not fixed there: of the
    # columns fixed at 0, only those dynslite.vda fixes (.FX = 0 on a timeslice off in the period: NORTS(R,T,S)) are.
    dyn = (VAR_ACT = (3, 5), VAR_FLO = (3, 6), VAR_IRE = (3, 6), VAR_SIN = (3, 6), VAR_SOUT = (3, 6), VAR_UPS = (3, 5),
           VAR_UPT = (3, 5), VAR_UDP = (3, 5), VAR_COMNET = (2, 4), VAR_COMPRD = (2, 4))
    fixed = Dict{Int64,Float64}()
    for (name, var) in pairs(m.v)
        ts = get(dyn, name, nothing)
        for (k, x) in var.x
            JuMP.is_fixed(x) || continue
            v = JuMP.fix_value(x)
            v == 0.0 && (ts === nothing || !has(m.d.NORTS, k[1], k[ts[1]], k[ts[2]])) && continue
            fixed[JuMP.index(x).value] = v
        end
    end
    isempty(fixed) && return
    isfx(x) = haskey(fixed, JuMP.index(x).value)
    gone = JuMP.ConstraintRef[]
    empty!(m.used)
    for (name, r) in m.rows
        keep = Int[]
        for (i, c) in enumerate(r.refs)
            f = JuMP.constraint_object(c).func
            zs = get(r.zeros, i, JuMP.VariableRef[])
            if any(isfx, keys(f.terms)) || any(isfx, zs)
                shift = 0.0
                for (x, a) in collect(f.terms)
                    isfx(x) || continue
                    shift += a * fixed[JuMP.index(x).value]
                    JuMP.set_normalized_coefficient(c, x, 0.0)
                end
                filter!(!isfx, zs)
                set = JuMP.constraint_object(c).set
                if !(set isa MOI.Interval) && shift != 0.0
                    JuMP.set_normalized_rhs(c, JuMP.normalized_rhs(c) - shift)
                end
                f = JuMP.constraint_object(c).func
                if isempty(f.terms) && isempty(zs)
                    set = JuMP.constraint_object(c).set
                    ok = set isa MOI.EqualTo ? set.value == 0.0 : set isa MOI.LessThan ? 0.0 <= set.upper :
                         set isa MOI.GreaterThan ? 0.0 >= set.lower : true
                    ok || error("equation infeasible due to rhs value: ", text(m, name, r.keys[i]), " (HOLDFIXED, dynamic timeslices)")
                    push!(gone, c)
                    continue
                end
            end
            push!(keep, i)
            foreach(x -> push!(m.used, JuMP.index(x).value), keys(f.terms))
            foreach(x -> push!(m.used, JuMP.index(x).value), zs)
            isempty(zs) || (r.zeros[i] = zs)
        end
        length(keep) == length(r.refs) && continue
        pos = Dict(i => n for (n, i) in enumerate(keep))
        zeros = Dict(pos[i] => z for (i, z) in r.zeros if haskey(pos, i))
        cancel = Dict(pos[i] => s for (i, s) in r.cancel if haskey(pos, i))
        keys_, refs = r.keys[keep], r.refs[keep]
        empty!(r.keys); append!(r.keys, keys_); empty!(r.refs); append!(r.refs, refs)
        empty!(r.zeros); merge!(r.zeros, zeros); empty!(r.cancel); merge!(r.cancel, cancel)
    end
    isempty(gone) || JuMP.delete(m.jump, gone)
end

# GAMS does not solve a model with a column whose lower bound is above its upper bound ("**** Matrix error - lower
# bound > upper bound", "SOLVE ... ABORTED"); TIMES passes such bounds through, e.g. ACT_BND given with LO above UP
# (bnd_act.mod 20-21: nothing like the SMIN of NCAP_BND and CAP_BND, bndmain.mod 45 and 51). The port stops in the
# same way. Only the columns in the model count, as for GAMS.
function check_bounds(m::Model)
    bad = String[]
    foreach(m.v) do var
        for (k, (lo, up)) in var.bounds
            lo > up && haskey(var.x, k) && push!(bad, string(text(m, var.name, k), "   (.LO, .UP = ", lo, ", ", up, ")"))
        end
    end
    isempty(bad) || error("Matrix error - lower bound > upper bound: ", first(sort!(bad)),
                          length(bad) > 1 ? " and $(length(bad) - 1) more" : "", "; GAMS does not solve such a model")
end

# One call for all of them, of all variable families: each call walks every row of the model (MOI rebuilds every
# row's function without the deleted variables), so deleting variables one at a time is far too slow on a myopic step
# (many variables touched outside the window, 700,000 rows), and one call per family was still slow on a model of
# 10 M rows (3,720 variables to delete).
function drop_unused!(m::Model)
    refs = JuMP.VariableRef[]
    foreach(var -> drop_unused!(var, m.used, refs), m.v)
    isempty(refs) || JuMP.delete(m.jump, refs)
end

function drop_unused!(var::Var, used::BitSet, refs::Vector{JuMP.VariableRef})
    unused = [k for (k, x) in var.x if !(JuMP.index(x).value in used)]
    foreach(k -> push!(refs, pop!(var.x, k)), unused)
end

text(m::Model, name::Symbol, k::Tuple) = isempty(k) ? String(name) : string(name, "(", join(label(m.L, k), ","), ")")

function name_all!(m::Model)
    foreach(m.v) do var
        for (k, x) in var.x
            JuMP.set_name(x, text(m, var.name, k))
        end
    end
    for (name, r) in m.rows, i in eachindex(r.keys)
        JuMP.set_name(r.refs[i], text(m, name, r.keys[i]))
    end
end
