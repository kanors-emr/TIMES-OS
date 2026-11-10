# SPDX-License-Identifier: GPL-3.0-or-later
"""
Stochastic TIMES (`\$SET STAGES YES`, stages.stc): the model of every state of the world (SOW) of a scenario tree.

TIMES writes every equation as `ES_*` instead of `EQ_*` and every variable as `VAS_*` instead of `VAR_*`, with a SOW
index (maindrv.mod 66, stages.stc 12: `%SW_TAGS%`). A row of period T is written for the SOWs distinct in T,
`SW_T(T,SOW)` (`%SWT%` appends `T,SOW` to its key); a row without a period for every SOW (`%SOW%`). A variable of
period T named in a row of SOW w is that of the SOW that represents w in T, `SW_TSW(w,T,W)` (`%VART%`, `%VARV%`,
`%VARM%`; `%SOW%` where the period is the row's own); a variable without a period is that of w.

Here a family is built once for each SOW w, in order (`build`): `sow_row` keeps a row of period t when `SW_T(t,w)` (w
is the first SOW of its group in t) and gives it its tag; a variable family has the SOW as its last index, and a call
with the deterministic key takes the SOW from `SW_TSW` (`(v::Var)(k...)` below). Without STAGES none of this runs.
"""

"""The SOW context of a stochastic run (SW_TSW has records only with STAGES), else `nothing`."""
function sow_context(d::Data)
    t = d.tables
    isempty(t.SW_TSW) && return nothing
    iszero(plain(t.SW_SENSIS())) || return sensis_context(d)
    tsw = Dict{NTuple{2,Id},Id}()
    for (w, y, w2) in t.SW_TSW.rows
        tsw[(w, y)] = w2
    end
    sows = sort([w for w in t.SOW.rows]; by = w -> parse(Int, label(d.L, w)))
    DEAD[] = id!(d.L, "*")                               # (no label of a TIMES set)
    empty!(SOW_PERIODS)
    foreach(((y, w),) -> push!(SOW_PERIODS, y), t.SW_T.rows)
    reps = Dict{Id,Dict{Id,Id}}(w => Dict{Id,Id}() for w in sows)
    for ((w, y), w2) in tsw
        get!(Dict{Id,Id}, reps, w)[y] = w2
    end
    maps = Dict{Id,Dict{Id,Vector{NTuple{2,Id}}}}(w => Dict{Id,Vector{NTuple{2,Id}}}() for w in sows)
    for (y, w, j, ww) in t.SW_MAP.rows
        push!(get!(Vector{NTuple{2,Id}}, get!(Dict{Id,Vector{NTuple{2,Id}}}, maps, w), y), (j, ww))
    end
    w = first(sows)
    # SPINES (recurrin.stc 52-179): OBJSW1 is set only then; %SCUM% with SOLVEDA 1 (SW_SCUM, port-only)
    spines = !isempty(t.OBJSW1)
    scum = spines && !iszero(plain(t.SW_SCUM()))
    spines && !isempty(t.PRC_DYNUC) &&
        error("TIMES feature not supported yet with SPINES: the dynamic process bounds by SOW (PRC_DYNUC, UCRTPSW1)")
    return SowCtx(w, sows, Set{NTuple{2,Id}}(t.SW_T.rows), tsw, reps, reps[w], maps, maps[w], Set{Int64}(), Id(0),
                  spines, scum, id!(d.L, "1"), false, 1.0, Id[])
end

"""
SENSIS (`\$SET SENSIS YES`; maindrv.mod 34 sets STAGES to `Yes`): TIMES solves one deterministic model for each SOW
distinct in the first period (solve.stc 35-52, DOITER), under the names of the deterministic model (SW_NOTAGS);
the statements of `\$IFI %STAGES%` read the data of the SOWs of that solve:

    LOOP(MIYR_1(T),SOW(WW) = SW_TSW(WW,T,ALLSOW); SW_NORM = SW_TPROB(T,ALLSOW));

The SOW of the build is SENS_W[] (set by the caller for each solve, `sensis_sows`): every period is represented by
it, its SW_MAP rows are those of the demand projections and taxes.
"""
const SENS_W = Ref{Id}(Id(0))

"""A SENSIS run: the solves of `sensis_sows`, one deterministic model each (port-only SW_SENSIS)."""
sensis(d::Data) = !isempty(d.tables.SW_TSW) && !iszero(plain(d.tables.SW_SENSIS()))

"""The SOWs of the solves of a SENSIS run, in order: those distinct in the first milestone year (SW_T(MIYR_1,ALLSOW))."""
function sensis_sows(d::Data)
    t = d.tables
    ms = sort([y for y in t.MILESTONYR.rows]; by = y -> year(d.L, y))
    y1 = first(ms)
    return sort([w for (y, w) in t.SW_T.rows if y == y1]; by = w -> parse(Int, label(d.L, w)))
end

function sensis_context(d::Data)
    t = d.tables
    w = SENS_W[]
    w == Id(0) && error("SENSIS: the SOW of the solve is not set (sensis_sows, SENS_W)")
    ms = sort([y for y in t.MILESTONYR.rows]; by = y -> year(d.L, y))
    y1 = first(ms)
    members = sort([ww for (ww, y, w2) in t.SW_TSW.rows if y == y1 && w2 == w]; by = x -> parse(Int, label(d.L, x)))
    norm = plain(t.SW_TPROB(y1, w))
    rep = Dict{Id,Id}(y => w for y in ms)
    map = Dict{Id,Vector{NTuple{2,Id}}}()
    for (y, ww, j, w2) in t.SW_MAP.rows
        ww == w && push!(get!(Vector{NTuple{2,Id}}, map, y), (j, w2))
    end
    empty!(SOW_PERIODS)
    foreach(y -> push!(SOW_PERIODS, y), ms)
    DEAD[] = id!(d.L, "*")
    return SowCtx(w, [w], Set{NTuple{2,Id}}((y, w) for y in ms), Dict{NTuple{2,Id},Id}(), Dict(w => rep), rep,
                  Dict(w => map), map, Set{Int64}(), Id(0), false, false, id!(d.L, "1"), true, norm, members)
end

"""The labels the families of a stochastic run name (sow_objective!, eqobjvar.mod 48), added before the build: a
family built in a thread only looks labels up."""
sow_labels!(m::Model) = foreach(n -> id!(m.L, n), ("OBJZ", "N", "1", "NET"))

"""The SOW context set to build the rows of SOW w."""
sow!(c::SowCtx, w::Id) = (c.w = w; c.rep = c.reps[w]; c.map = c.maps[w]; c)

"""A context of its own for the rows of SOW w built in a thread (build_parallel!): the maps shared, its own DEAD
columns (numbered as the thread's variables) and ROW_T."""
sow_copy(c::SowCtx, w::Id) = sow!(SowCtx(w, c.sows, c.swt, c.tsw, c.reps, c.rep, c.maps, c.map, Set{Int64}(), Id(0),
                                         c.spines, c.scum, c.w1, c.sensis, c.norm, c.members), w)

# SPINES (recurrin.stc 147-171): the capacity variables are those of SOW '1' in every SOW (Z_CAP(r,t,p,sow) is
# VAS_CAP(r,t,p,'1'), ...), and with %SCUM% the cumulative ones (Z_CUMCOM(r,c,cv,y1,y2,w) is VAS_CUMCOM(..,'1'), ...).
const SPINE_VARS = (:VAR_CAP, :VAR_NCAP, :VAR_RCAP, :VAR_SCAP, :VAR_DRCAP, :VAR_DNCAP, :VAR_SNCAP, :VAR_XCAP)
const SCUM_VARS = (:VAR_CUMCOM, :VAR_CUMFLO, :VAR_CUMCST)
# SPINES (recurrin.stc 72-123): the rows written for SOW '1' only (Q_OBJINV(rc,sow) is ES_OBJINV(rc,SOW('1')), ...)
const SPINE_ROWS = (:EQ_OBJINV, :EQ_OBJFIX, :EQ_OBJSALV, :EQE_CPT, :EQG_CPT, :EQL_CPT)
const SCUM_ROWS = (:EQ_CUMNET, :EQ_CUMPRD, :EQ_CUMFLO, :EQE_UC, :EQE_UCR)
# ... and those not ported yet: Q_CUMRET, Q_DSCRET, QL_REFIT, Q_DSCNCAP, Q_DSCONE; with %SCUM% Q_BNDCST, QL_SCAP and
# the cumulative user constraints by period or timeslice (QE_UCSU, QE_UCSUS, QE_UCRSU, QE_UCRSUS)
const SPINE_NOT = (:EQ_CUMRET, :EQ_DSCRET, :EQL_REFIT, :EQ_DSCNCAP, :EQ_DSCONE)
const SCUM_NOT = (:EQ_BNDCST, :EQL_SCAP, :EQE_UCSU, :EQE_UCSUS, :EQE_UCRSU, :EQE_UCRSUS)

"""SPINES: false while a SOW other than '1' is built, for a family of SOW '1' only (SPINE_ROWS) to skip its rows before
it names their variables: in GAMS they are rows of SOW('1') alone, and the variables of the other SOWs they would name
are in no other row."""
sow_w1(m::Model) = m.sw === nothing || !m.sw.spines || m.sw.w == m.sw.w1
"""The same for the cumulative rows with %SCUM% (SCUM_ROWS)."""
sow_w1_scum(m::Model) = m.sw === nothing || !m.sw.scum || m.sw.w == m.sw.w1

"""
With %SCUM% (SPINES, SOLVEDA 1), the terms of the periods of a cumulative row (SOW '1'), `f()` built as the row of a
SOW: their expected value over the SOWs. GAMS sums each variable of period T over the SOWs W distinct in T, weighted by
their probability (%VARTT%: SUM(SW_TSW(W,TT,W),SW_TPROB(TT,W)*Z_..(..,W)); equcwrap.mod 17 TSUM); SW_TPROB(T,W) is the
sum of SW_PROB over the SOWs that W represents in T, so this is SUM(w, SW_PROB(w) * (the terms as SOW w)).
Without %SCUM%, `f()`. E: the type of the expression `f` returns.
"""
function sow_expected(f, m::Model, ::Type{E} = AE) where {E}
    c = m.sw
    (c === nothing || !c.scum) && return f()
    w0 = c.w
    total = E()
    try
        for w in c.sows
            p = plain(m.d.SW_PROB(w))
            iszero(p) && continue
            sow!(c, w)
            add!(total, p, f())
        end
    finally
        sow!(c, w0)
    end
    return total
end

# The position of the period in the deterministic key of each variable family (%VART%: T; %VARV% / %VARM%: the vintage
# of VAR_NCAP); 0: the family has no period and takes the row's SOW (%SOW%).
const VAR_TPOS = Dict{Symbol,Int}(:VAR_ACT => 3, :VAR_FLO => 3, :VAR_IRE => 3, :VAR_NCAP => 2, :VAR_CAP => 2, :VAR_COMNET => 2,
    :VAR_COMPRD => 2, :VAR_SIN => 3, :VAR_SOUT => 3, :VAR_UDP => 3, :VAR_UPS => 3, :VAR_RCAP => 3, :VAR_SCAP => 3,
    :VAR_DRCAP => 3, :VAR_UCT => 2, :VAR_UCTS => 2, :VAR_UCRT => 3, :VAR_UCRTS => 3, :VAR_ELAST => 2, :VAR_BLND => 2,
    :VAR_UPT => 3, :VAR_DNCAP => 2, :VAR_SNCAP => 2)

"""The variable families of a stochastic run: VAS_<X>, the SOW their last index (OBJZ and VAS_EXPOBJ have none)."""
function sow_vars(d::Data, jump::JuMP.Model, sw::SowCtx)
    return VarsST(map(keys(VARS)) do n
        N = vas_arity(n)
        nm = n == :OBJZ ? n : Symbol("VAS_", String(n)[5:end])
        b = Dict{NTuple{N,Id},NTuple{2,Float64}}()
        src = get(d.sbounds, nm, nothing)
        src === nothing || for (k, lohi) in src
            b[k] = lohi
        end
        w1 = (sw.spines && n in SPINE_VARS) || (sw.scum && n in SCUM_VARS)
        Var{N}(nm, jump, Dict{NTuple{N,Id},JuMP.VariableRef}(), b, n in FREE, nothing, NTuple{N,Id}[], Int16(0),
               N == length(VARS[n]) ? nothing : sw, w1 ? -1 : get(VAR_TPOS, n, 0))
    end)
end
const VarsST = NamedTuple{keys(VARS),Tuple{(Var{vas_arity(n)} for n in keys(VARS))...}}

"""
A variable of a stochastic run named with its deterministic key: that of the SOW `W` with `SW_TSW(w, t, W)`, w the SOW of
the row being built and t the variable's period (%VART%, %VARV%, %VARM%); without a period (or a period that is not a
milestone year), that of w (%SOW%).
"""
function (v::Var{M})(k::Vararg{Id,N}) where {M,N}
    c = v.sw
    (c === nothing || N != M - 1) && throw(MethodError(v, k))
    v.tpos == 0 && return v(k..., c.w)
    v.tpos < 0 && return v(k..., c.w1)                   # SPINES: SOW '1' (SPINE_VARS, SCUM_VARS)
    t = k[v.tpos]
    w = get(c.rep, t, nothing)
    w === nothing || return v(k..., w)
    t in SOW_PERIODS || return v(k..., c.w)             # not a milestone year (VAR_SCAP(r,v,'0',p)): the row's SOW
    x = v(k..., DEAD[])
    push!(c.dead, JuMP.index(x).value)
    return x
end

"""Drop from a row the terms of the variables of a SOW without a representative (DEAD; `dead`: their columns)."""
function sow_dead!(dead::Set{Int64}, e)
    isempty(dead) && return e
    e isa JuMP.VariableRef && return JuMP.index(e).value in dead ? AE() : e
    e isa AE || return e
    for x in collect(keys(e.terms))
        JuMP.index(x).value in dead && delete!(e.terms, x)
    end
    return e
end

"""The variable of the row's own SOW, whatever its period (`%SOW%` on a variable of another period than the row's,
or a row restricted to SW_UCT: equcwrap.mod 16, `SW1` = `%SOW%`)."""
sow_own(m::Model, v, k...) = (m.sw === nothing || m.sw.sensis) ? v(k...) : v(k..., v.tpos < 0 ? m.sw.w1 : m.sw.w)

"""The rows of a dynamic user constraint between periods are written for (t, w) of SW_UCT only (equcwrap.mod 16:
SWS '(SW_UCT(UC_N,T,SOW)*')."""
sow_ucsucc(m::Model, uc, t) = m.sw === nothing || m.sw.sensis || (uc, t, m.sw.w) in m.d.SW_UCT

"""
A SOW without a representative in a period (SW_TSW removed with the SOWs of probability 0, stages.stc 167-168): a
variable of that period named in its rows is in no sum over SW_TSW in GAMS, so the term is not there. It gets a column
under the label DEAD[] that `row!` drops from the row (sow_dead!), and that no row keeps.
"""
const DEAD = Ref{Id}(0)
const SOW_PERIODS = Set{Id}()

"""The SOW that represents the SOW of the row being built in period t (SW_TSW)."""
sow_at(m::Model, t::Id) = get(m.sw.rep, t, m.sw.w)

# Rows by SOW (eqdeclr.mod): the families declared with %SWTD% (`T,WW` appended) and the position of their period T in
# the port's key; 0: declared with %SWD% (the SOW appended), written for every SOW.
const ROW_SOW = Dict{Symbol,Int}(
    WINDOW_T...,
    :EQE_CPT => 2, :EQG_CPT => 2, :EQL_CPT => 2, :EQE_UCT => 2, :EQE_UCTS => 2, :EQN_UCRTC => 4,
    :EQ_DSCNCAP => 2, :EQ_DSCONE => 2, :EQ_STSBAL => 3, :EQ_GR_PTDFLO => 2, :EQ_GR_VIRTCAP => 2, :EQ_GR_VIRTBND => 2,
    :EQ_GR_XBND => 2, :EQ_RL_LOAD => 2, :EQ_RL_NDIS => 2, :EQ_RL_PKCAP => 2, :EQ_RL_STCAP => 2, :EQ_RL_THMIN => 2,
    (n => 0 for n in (:EQ_OBJINV, :EQ_OBJFIX, :EQ_OBJVAR, :EQ_OBJSALV, :EQ_OBJELS, :EQ_CUMFLO, :EQ_CUMNET, :EQ_CUMPRD,
        :EQ_BNDCST, :EQL_SCAP, :EQE_UC, :EQE_UCR, :EQE_UCSU, :EQE_UCSUS, :EQE_UCRSU, :EQE_UCRSUS, :EQG_UCMAX, :EQG_UCSUMAX,
        :EQ_ROBJ, :EQ_SOBJ, :EQ_OBW1, :EQ_CLITOT, :EQ_CLICONC, :EQ_CLITEMP, :EQ_CLIBEOH, :EQ_CLIMAX))...,
    :EQ_CUMRET => -1)
# Rows written once, not by SOW (eqobj.mod 105-125): their names are not changed.
const ROW_ONCE = (:EQ_OBJ, :EQ_EXPOBJ)
# Rows whose %SWT% period is not in their key: the family sets it with sow_rowt! before row! (-1 in ROW_SOW).
# EQ_CUMRET(R,VNTRT(V,K(T-(1-1$RP_RTF(R,P)))),P,SW_T(T,SOW)): the key holds K, the tag T (prepret.dsc 98).
sow_rowt!(m::Model, t::Id) = (m.sw === nothing || (m.sw.rowt = t); nothing)

"""
The rows of period t that the SOW being built does not write (not SW_T(t,w): `sow_row` drops them), for a family to skip
before it computes them. Only for a family whose row of period t names variables of t or of earlier periods, each with
its period (%VART%, %VARV%): the SOWs of a group in t are in one group in every earlier period, so such a row names the
columns of the row of the same key that the first SOW of the group wrote before it, and skipping it creates no column
and changes no order.
"""
sow_skip(m::Model, t::Id) = m.sw !== nothing && !((t, m.sw.w) in m.sw.swt)

"""ES_ for EQ_ (EQ_ACTFLO -> ES_ACTFLO, EQL_CAPACT -> ESL_CAPACT): stages.stc 12, SET EQ 'ES'."""
es_name(name::Symbol) = Symbol("ES", String(name)[3:end])

"""
The name and key of a row of the SOW being built, as GAMS gives them (`%SWT%`: the period and the SOW appended;
`%SOW%`: the SOW appended); `nothing` for a row of period t that this SOW does not write (not SW_T(t,w)).
"""
function sow_row(m::Model, name::Symbol, key::Tuple)
    (name in ROW_ONCE || m.sw.sensis) && return name, key          # (SENSIS: the names of the deterministic model)
    i = get(ROW_SOW, name, nothing)
    i === nothing && error("TIMES feature not supported yet with STAGES: the rows of $name by state of the world")
    c = m.sw
    w = c.w
    if c.spines
        (name in SPINE_NOT || (c.scum && name in SCUM_NOT)) &&
            error("TIMES feature not supported yet with SPINES: the rows of $name of SOW '1'")
        (name in SPINE_ROWS || (c.scum && name in SCUM_ROWS)) && w != c.w1 && return nothing, key
    end
    i == 0 && return es_name(name), (key..., w)
    t = i < 0 ? c.rowt : key[i]
    (t, w) in c.swt || return nothing, key
    return es_name(name), (key..., t, w)
end

"""
The rows of the objective of a stochastic run (eqobj.mod 75-125, SW_PHASE 0, SW_LAMBDA 0), written by eq_obj! for each
SOW w in place of EQ_OBJ:

    ES_ROBJ(r,w)    SUM(cur, VAS_OBJ(r,OBJINV,cur,w) + .. + .. - VAS_OBJ(r,OBJSAL,cur,w))  =  VAS_UCR('OBJZ',r,w)
    ES_SOBJ('N',w)  SUM(r, VAS_UCR('OBJZ',r,w))  =  VAS_UC('OBJZ',w)

and after the last SOW

    EQ_EXPOBJ('1')  SUM(w, SW_PROB(w) * VAS_UC('OBJZ',w))  =  VAS_EXPOBJ     (SW_NORM = 1)
    EQ_OBJ          OBJZ        =  VAS_EXPOBJ
"""
function sow_objective!(m::Model, regional::Dict{Id,AE})
    objz, n = id!(m.L, "OBJZ"), id!(m.L, "N")
    (; VAR_UCR, VAR_UC) = m.v
    total = AE()
    for r in m.d.REG.rows
        rr = r isa Tuple ? r[1] : r
        row!(m, :EQ_ROBJ, (rr,), get(regional, rr, AE()), ==, VAR_UCR(objz, rr))
        add!(total, 1.0, VAR_UCR(objz, rr))
    end
    row!(m, :EQ_SOBJ, (n,), total, ==, VAR_UC(objz))
    if m.sw.sensis
        # EQ_EXPOBJ(AUXSOW(WW)).. SUM(SOW, SW_PROB(SOW) * VAR_UC('OBJZ'))/SW_NORM - VAS_EXPOBJ =E= 0   (%SOW% empty)
        p = sum(plain(m.d.SW_PROB(w)) for w in m.sw.members; init = 0.0) / m.sw.norm
        e = AE()
        add!(e, p, VAR_UC(objz))
        row!(m, :EQ_EXPOBJ, (id!(m.L, "1"),), e, ==, m.v.VAR_EXPOBJ())
        row!(m, :EQ_OBJ, (), m.v.VAR_EXPOBJ(), ==, m.v.OBJZ())
        return
    end
    # SPINES (recurrin.stc 178-179): the components of OBJSW1 of every SOW are those of SOW '1'
    #   %EQ%_OBW1(OBJSW1(OBV),RDCUR(R,CUR),SOW) .. %VAR%_OBJ(R,OBV,CUR,SOW) =E= %VAR%_OBJ(R,OBV,CUR,'1');
    # (in SOW '1' the two sides are one variable: a row without terms, which GAMS does not write)
    c = m.sw
    if c.spines && c.w != c.w1
        VAR_OBJ = m.v.VAR_OBJ
        for o in m.d.OBJSW1.rows, (r, cur) in m.d.RDCUR.rows
            obv = o isa Tuple ? o[1] : o
            row!(m, :EQ_OBW1, (obv, r, cur), VAR_OBJ(r, obv, cur), ==, VAR_OBJ(r, obv, cur, c.w1))
        end
    end
    m.sw.w == last(m.sw.sows) || return
    expected = AE()
    for w in m.sw.sows
        p = m.d.SW_PROB(w)
        iszero(p) || add!(expected, p, VAR_UC(objz, w))
    end
    row!(m, :EQ_EXPOBJ, (id!(m.L, "1"),), expected, ==, m.v.VAR_EXPOBJ())
    row!(m, :EQ_OBJ, (), m.v.VAR_EXPOBJ(), ==, m.v.OBJZ())
end

"""
The demand projection of SOW w in period t (eqcombal.mod 109, eqpeak.mod 81):
`PROD(SW_MAP(T,SOW,J,WW)\$S_COM_PROJ(R,T,C,J,WW),S_COM_PROJ(R,T,C,J,WW)) * COM_PROJ(R,T,C)`.
"""
function sow_com_proj(m::Model, r, t, c)
    x = m.d.COM_PROJ(r, t, c)
    (m.sw === nothing || isempty(m.d.S_COM_PROJ)) && return x
    f = 1.0
    for (j, ww) in get(m.sw.map, t, ())                 # SW_MAP(t,w,j,ww) of the row's SOW, in order
        has(m.d.S_COM_PROJ, r, t, c, j, ww) && (f *= m.d.S_COM_PROJ(r, t, c, j, ww))
    end
    return f * x
end
