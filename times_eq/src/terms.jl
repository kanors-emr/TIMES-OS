# SPDX-License-Identifier: GPL-3.0-or-later
# Expressions that several equations share.

"""
Share of the quantity at timeslice `ts` that is attributed to timeslice `s`:

    RS_FR(r,s,ts) * (1 + RTCS_FR(r,t,c,s,ts))

1 when ts lies at or below s, the duration share of s within ts when ts lies above s, 0 otherwise.
"""
frac(m::Model, r, t, c, s, ts) = m.d.RS_FR(r, s, ts) * (1 + rtcs_fr(m, r, t, c, s, ts))

# RTCS_FR(r,t,c,s,ts); in stochastic TIMES with S_COM_FR (recurrin.stc 48) that of the row's SOW:
#   RTCS_FRMX(R,T,C,S,TS)+SUM(SW_T2W(SOW,T,W,T0),RCS_SSFR(R,C,S,TS,W,T0)), W the SOW that represents it in t
rtcs_fr(m::Model, r, t, c, s, ts) = (m.sw === nothing || isempty(m.d.RTCS_SFRW)) ? m.d.RTCS_FR(r, t, c, s, ts) :
    m.d.RTCS_FR(r, t, c, s, ts) + m.d.RTCS_SFRW(r, t, c, s, ts, sow_at(m, t))

# COM_FR(r,t,c,s); in stochastic TIMES with S_COM_FR (recurrin.stc 49) COM_FRMX(R,T,C,S) = COM_FR(R,T,C,S)*(1+S_COM_FR(R,T,C,S,'1',SOW))
com_frmx(m::Model, r, t, c, s) = (m.sw === nothing || isempty(m.d.S_COM_FR)) ? m.d.COM_FR(r, t, c, s) :
    m.d.COM_FR(r, t, c, s) * (1.0 + m.d.S_COM_FR(r, t, c, s, id!(m.L, "1"), m.sw.w))

"""
    onbranch(list, rel)

The elements of `list` (the timeslices of a variable: `flow_s[r, t, p, c]`, `rpcs_s[r, p, c]`, `prc_ts[r, p]`, ...; or
the (c, ts) pairs of `flow_cs`) whose timeslice is in `rel` (those related to a row's timeslice s: `ts_frac[r, s]`,
`ts_tree[r, s]`, `ts_below[r, s]`, ...), in the order of `list`. A loop

    for ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s]); has(RS_FR, r, s, ts) || continue; ...

visits the same timeslices, in the same order, as one over all of `flow_s[r, t, p, c]`, without walking it: a flow on
the lowest level has as many timeslices as the model, a row at one of them relates to a few (itself and those above
it), and the walk made the families quadratic in the number of timeslices.
GAMS reaches the same pairs through RS_FR / RS_TREE / TS_MAP. `rel` holds every timeslice that the loop's own test can
keep; the loop keeps its test. A short list is returned as it is.

The position of each element in a list is taken once per list, in a cache of the task (the families built in threads
have their own), dropped at the end of the build (`clear_branch!`).
"""
struct Branch
    one::IdDict{Vector{Id},Dict{Id,Int32}}                  # a list => the position of each of its timeslices
    oneval::Dict{Vector{Id},Dict{Id,Int32}}                 # lists with the same timeslices share their positions
    tup::IdDict{Any,Dict{Id,Vector{Int32}}}                 # a list of tuples => the positions of each timeslice
end
Branch() = Branch(IdDict{Vector{Id},Dict{Id,Int32}}(), Dict{Vector{Id},Dict{Id,Int32}}(), IdDict{Any,Dict{Id,Vector{Int32}}}())
function branch_cache()
    s = task_local_storage()
    b = get(s, :branch, nothing)
    b === nothing && (b = s[:branch] = Branch())
    return b::Branch
end
clear_branch!() = (delete!(task_local_storage(), :branch); nothing)

function onbranch(list::Vector{Id}, rel::Vector{Id})
    length(list) <= 2 * length(rel) + 8 && return list
    b = branch_cache()
    pos = get(b.one, list, nothing)
    if pos === nothing
        pos = get!(() -> Dict{Id,Int32}(ts => Int32(i) for (i, ts) in enumerate(list)), b.oneval, list)
        b.one[list] = pos
    end
    length(pos) == length(list) || return list                  # (a timeslice twice in the list: walked as it is)
    idx = Int32[]
    for ts in rel
        i = get(pos, ts, Int32(0))
        i > 0 && push!(idx, i)
    end
    return list[sort!(idx)]
end
# a list of tuples (flow_cs: (c, ts); ire_aux: (p, com, ts, ie)): by the timeslice at position k
function onbranch(list::Vector{T}, rel::Vector{Id}, k::Int) where {T<:Tuple}
    length(list) <= 2 * length(rel) + 8 && return list
    pos = get!(branch_cache().tup, list) do
        d = Dict{Id,Vector{Int32}}()
        for (i, x) in enumerate(list)
            push!(get!(Vector{Int32}, d, x[k]), Int32(i))
        end
        d
    end::Dict{Id,Vector{Int32}}
    idx = Int32[]
    for ts in rel
        v = get(pos, ts, nothing)
        v === nothing || append!(idx, v)
    end
    return list[sort!(idx)]
end

"""
Capacity installed in year v: the investment variable in a milestone year, the given past
investment in a year before the horizon.

    VAR_NCAP(r,v,p) [v a milestone year]  +  NCAP_PASTI(r,v,p) [v a past year]
"""
function installed(::Type{E}, m::Model, r, v, p) where {E}
    e = E(v in m.d.PASTYEAR ? m.d.NCAP_PASTI(r, v, p) : 0.0)
    new_capacity(m, v) && addto!(e, 1.0, m.v.VAR_NCAP(r, v, p))
    return e
end

"""
Age shape of the factor between groups cg1 and cg2 of vintage v in period t (FLO_FUNCX, coef_shp.mod): the
multiplier 1 + RTP_FFCX(r,v,t,p,cg1,cg2) for a vintaged process; 1 when there is none or the process is not vintaged
(`*(%SHFF%X(R,V,T%SHG%)\$PRC_VINT(R,P))` in eqptrans.mod, cal_fflo.mod and pp_actef.vda).
"""
ffcx(m::Model, r, v, t, p, cg1, cg2) = ((r, p) in m.d.PRC_VINT ? 1.0 + m.d.RTP_FFCX(r, v, t, p, cg1, cg2) : 1.0) * ffcs(m, r, v, p, cg1, cg2)

# stochastic TIMES: *(%SHFF%S(R,V,P,CG1,CG2%SOW%)), 1 + RTP_FFCS of the row's SOW (S_FLO_FUNC); 1 otherwise
ffcs(m::Model, r, v, p, cg1, cg2) = (m.sw === nothing || isempty(m.d.RTP_FFCS)) ? 1.0 : 1.0 + m.d.RTP_FFCS(r, v, p, cg1, cg2, m.sw.w)

# stochastic TIMES, recurrin.stc 46 (S_NCAP_AFS): COEF_AFMX(R,V,T,P,S,BD) = COEF_AF(R,V,T,P,S,BD)*(1+RTP_SAFS(R,T,P,S,SOW)),
# the availability x of the upper and fixed bounds in EQ_CAPACT, EQ_CAFLAC and EQ_CAPLOAD; x itself otherwise
afmx(m::Model, x, r, t, p, s) = (m.sw === nothing || isempty(m.d.RTP_SAFS)) ? x : x * (1.0 + m.d.RTP_SAFS(r, t, p, s, m.sw.w))

"""
Flow of commodity c of process p in timeslice ts (cal_nored.red).

An emission that is tied to another flow has no variable of its own:

    VAR_FLO(r,v,t,p,c,ts)                                                        ordinary flow
    SUM((cg,com,s), COEF_PTRAN(r,v,p,cg,com,c,s) * frac(com,ts,s) * VAR_FLO(r,v,t,p,com,s))   emission

No age shape (FLO_FUNCX) here, as in GAMS with REDUCE NO: cal_nored.red declares SHP3 with \$SETLOCAL, so
the \$SET SHP3 that should carry %SHFF%X is shadowed and the shape drops out of every %cal_red% caller
(objective, FLO_BND, UC_FLO, FLO_SHAR, ...). It is applied only by `flows` (cal_fflo.mod) and EQ_PTRANS.
"""
function flow(::Type{E}, m::Model, r, v, t, p, c, ts) where {E}
    (; RPC_EMIS, RTPCS_VARF, COEF_PTRAN) = m.d
    (; VAR_FLO) = m.v
    reduced(m) && return reduced_flow(E, m, r, v, t, p, c, ts)
    (r, p, c) in RPC_EMIS || return VAR_FLO(r, v, t, p, c, ts)
    e = E()
    for (cg, com) in m.ix.fs_emit[r, p, c], s in m.ix.ts_frac[r, ts]
        (r, t, p, com, s) in RTPCS_VARF || continue
        k = COEF_PTRAN(r, v, p, cg, com, c, s) * frac(m, r, t, com, ts, s)
        iszero(k) || add!(e, k, VAR_FLO(r, v, t, p, com, s))
    end
    return e
end

"""A run with REDUCE YES: flows replaced by the activity (cal_red.red in place of cal_nored.red)."""
reduced(m::Model) = !isempty(m.d.REDUCE_YES)

"""
Flow of commodity c of process p in timeslice ts with REDUCE YES (cal_red.red, called as %cal_red% with no 7th
argument: vintaged form, the FLO_FUNCX shapes kept). A flow that is the activity (RPC_ACT) or tied to the
activity flow (RPC_FFUNC) has no variable of its own:

    VAR_FLO(r,v,t,p,c,ts)                                            ordinary flow
    PRC_ACTFLO(r,v,p,c) * VAR_ACT(r,v,t,p,ts)                        RPC_ACT
    SUM(s2, ACT_FLO(r,v,p,c,ts) * shape(ACT,c) * RS_FR(r,ts,s2) * (1+RTCS_FR(r,t,com,ts,s2)) * VAR_ACT(r,v,t,p,s2))
                                                                     RPC_FFUNC (com: the activity commodity, RPC_ACT)
    SUM((cg,com,s), source(com,s) * COEF_PTRAN(r,v,p,cg,com,c,s) * shape(cg,c) * RS_FR(r,ts,s) * (1+RTCS_FR(r,t,com,ts,s)))
                                                                     emission (RPC_EMIS), source(com,s) one of the three
                                                                     above for the source flow com

shape(cg,c) = 1 + RTP_FFCX(r,v,t,p,cg,c) of a vintaged process (`ffcx`). `w` multiplies the flow (%10 of cal_red.red:
it stands next to each variable).
"""
function reduced_flow(::Type{E}, m::Model, r, v, t, p, c, ts; w = 1.0) where {E}
    (; RPC_EMIS, RPC_ACT, RPC_FFUNC, RTPCS_VARF, COEF_PTRAN, RS_FR, RTCS_FR) = m.d
    e = E()
    if !((r, p, c) in RPC_ACT || (r, p, c) in RPC_FFUNC)
        if !((r, p, c) in RPC_EMIS)
            add!(e, w, m.v.VAR_FLO(r, v, t, p, c, ts))
        else
            # SUM((FS_EMIT(R,P,C,CG1,COM2),ALL_TS)$(RTPCS_VARF(R,T,P,COM2,ALL_TS)$RS_FR(R,TS,ALL_TS)),
            #   (source flow) * COEF_PTRAN(R,V,P,CG1,COM2,C,ALL_TS)*SHP3 %10 * RS_FR(R,TS,ALL_TS)*(1+RTCS_FR(R,T,COM2,TS,ALL_TS)))
            for (cg, com) in m.ix.fs_emit[r, p, c], s in m.ix.ts_frac[r, ts]
                ((r, t, p, com, s) in RTPCS_VARF && has(RS_FR, r, ts, s)) || continue
                k = COEF_PTRAN(r, v, p, cg, com, c, s) * ffcx(m, r, v, t, p, cg, c) * w * RS_FR(r, ts, s) * (1 + rtcs_fr(m, r, t, com, ts, s))
                iszero(k) && continue
                src = source_flow(E, m, r, v, t, p, com, s)
                # an EPS factor (COEF_PTRAN given as 0) times a source through the activity: EPS in GAMS, also when the
                # source's coefficient is EPS (ACT_FLO given as 0), where the product of the two would vanish here
                (iseps(k) && !(src isa JuMP.VariableRef)) ? add!(e, 1.0, eps_terms(src)) : add!(e, k, src)
            end
        end
    end
    act_terms!(e, m, r, v, t, p, c, ts, w)
    return e
end

# The same terms, each with the coefficient EPS (GAMS: EPS times any non-zero number, EPS included, is EPS).
eps_terms(x::AE) = JuMP.map_coefficients(_ -> EPS, x)
eps_terms(x::LX) = (flat!(x); LX(copy(x.cols), fill(EPS, length(x.cols)), 0.0, NaN, true))

# The flow of c through the activity (RPC_ACT, RPC_FFUNC), times w, added to e (the last two terms of cal_red.red).
function act_terms!(e, m::Model, r, v, t, p, c, ts, w)
    (; RPC_ACT, RPC_FFUNC, PRC_ACTFLO, ACT_FLO, RS_FR, RTCS_FR) = m.d
    (; VAR_ACT) = m.v
    # %VAR%_ACT(R,V,T,P,TS)*PRC_ACTFLO(R,V,P,C) %10 $RPC_ACT(R,P,C)
    (r, p, c) in RPC_ACT && add!(e, PRC_ACTFLO(r, v, p, c) * w, VAR_ACT(r, v, t, p, ts))
    # SUM((RPC_ACT(R,P,COM),PRC_TS2(R,P,S2))$RS_FR(R,TS,S2),
    #   VAR_ACT(R,V,T,P,S2) %10 * ACT_FLO(R,V,P,C,TS)*SHP2 * RS_FR(R,TS,S2)*(1+RTCS_FR(R,T,COM,TS,S2)))$RPC_FFUNC(R,P,C)
    if (r, p, c) in RPC_FFUNC
        for com in m.ix.rpc_act[r, p], s2 in m.ix.prc_ts2[r, p]
            has(RS_FR, r, ts, s2) || continue
            k = w * ACT_FLO(r, v, p, c, ts) * ffcx(m, r, v, t, p, m.K.ACT, c) * RS_FR(r, ts, s2) * (1 + rtcs_fr(m, r, t, com, ts, s2))
            iszero(k) || add!(e, k, VAR_ACT(r, v, t, p, s2))
        end
    end
    return e
end

# The source flow of an emission (the inner part of cal_red.red's emission term): VAR_FLO, or through the activity.
function source_flow(::Type{E}, m::Model, r, v, t, p, com, s) where {E}
    (; RPC_ACT, RPC_FFUNC) = m.d
    ((r, p, com) in RPC_ACT || (r, p, com) in RPC_FFUNC) || return m.v.VAR_FLO(r, v, t, p, com, s)
    return act_terms!(E(), m, r, v, t, p, com, s, 1.0)
end

"""
Import or export of commodity c by trade process p. When the trade flow is the activity of the
process (RPC_AIRE) the activity variable stands in for it:

    VAR_IRE(r,v,t,p,c,ts,ie)       or       PRC_ACTFLO(r,v,p,c) * VAR_ACT(r,v,t,p,ts)
"""
function trade(m::Model, r, v, t, p, c, ts, ie)
    (r, p, c) in m.d.RPC_AIRE || return m.v.VAR_IRE(r, v, t, p, c, ts, ie)
    return m.d.PRC_ACTFLO(r, v, p, c) * m.v.VAR_ACT(r, v, t, p, ts)
end

unweighted(p, v, ts) = 1.0
any_process(p) = true

"""
All flows of commodity c into (io = IN) or out of (io = OUT) processes, brought to timeslice s
(cal_fflo.mod):

    SUM((p,v,ts), frac(c,s,ts) * weight(p,v,ts) * flow(r,v,t,p,c,ts))

`weight` multiplies each flow, `only` restricts the processes.
"""
function flows(::Type{E}, m::Model, r, t, c, s, io; weight = unweighted, only = any_process) where {E}
    (; RP_FLO, RPC_EMIS, RS_FR, COEF_PTRAN) = m.d
    (; top_p, flow_s, vintages, fs_emit, ts_frac) = m.ix
    (; VAR_FLO) = m.v
    e = E()
    red = reduced(m)
    for p in top_p[r, c, io]
        ((r, p) in RP_FLO && only(p)) || continue
        if red
            # $LABEL REDUCE: SUM(TOP(RP_FLO(R,P),C,'%1'), SUM(RTPCS_VARF(R,T,P,C,TS),
            #   cal_red.red(C,COM,TS,P,T) * RS_FR(R,S,TS)*(1+RTCS_FR(R,T,C,S,TS))))   (the weight %3 next to each
            #   variable, inside the sum over the vintages, for a vintaged process; after the term for another)
            vint = (r, p) in m.d.PRC_VINT
            for ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s])
                f = frac(m, r, t, c, s, ts)
                iszero(f) && continue
                for v in vintages[r, t, p]
                    if vint
                        add!(e, f, reduced_flow(E, m, r, v, t, p, c, ts; w = weight(p, v, ts)))
                    else
                        add!(e, f * weight(p, v, ts), reduced_flow(E, m, r, v, t, p, c, ts))
                    end
                end
            end
        elseif !((r, p, c) in RPC_EMIS)
            for ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s])
                f = frac(m, r, t, c, s, ts)
                iszero(f) && continue
                for v in vintages[r, t, p]
                    add!(e, f * weight(p, v, ts), VAR_FLO(r, v, t, p, c, ts))
                end
            end
        else
            for (cg, com) in fs_emit[r, p, c], ts in onbranch(flow_s[r, t, p, com], ts_frac[r, s])
                has(RS_FR, r, s, ts) || continue
                f = frac(m, r, t, com, s, ts)
                for v in vintages[r, t, p]
                    k = f * COEF_PTRAN(r, v, p, cg, com, c, ts) * ffcx(m, r, v, t, p, cg, c) * weight(p, v, ts)
                    iszero(k) || add!(e, k, VAR_FLO(r, v, t, p, com, ts))
                end
            end
        end
    end
    return e
end

"""
All imports (ie = IMP) or exports (ie = EXP) of commodity c, brought to timeslice s (cal_ire.mod):

    SUM((p,v,ts), frac(c,s,ts) * weight(p,v,ts) * trade(r,v,t,p,c,ts,ie))
"""
function trades(::Type{E}, m::Model, r, t, c, s, ie; weight = unweighted, only = any_process) where {E}
    (; RS_FR) = m.d
    (; ire_p, flow_s, vintages, ts_frac) = m.ix
    e = E()
    for p in ire_p[r, c, ie]
        only(p) || continue
        for ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s])
            has(RS_FR, r, s, ts) || continue
            f = frac(m, r, t, c, s, ts)
            for v in vintages[r, t, p]
                k = f * weight(p, v, ts)
                iszero(k) || add!(e, k, trade(m, r, v, t, p, c, ts, ie))
            end
        end
    end
    return e
end

"""
Auxiliary flows of commodity c that come with trade (IRE_FLOSUM; the second sum of cal_ire.mod): what
trade processes consume (io = IN) or release (io = OUT) of c per unit of a commodity com they import
or export, brought to timeslice s:

    SUM((p,com,ts,ie,v), IRE_FLOSUM(r,t,p,com,ts,ie,c,io) * frac(com,s,ts) * weight(p,v,ts) * trade(r,v,t,p,com,ts,ie))
"""
function trade_aux(::Type{E}, m::Model, r, t, c, s, io; weight = unweighted, only = any_process) where {E}
    (; RS_FR, RPC_IRE, RTPCS_VARF, IRE_FLOSUM) = m.d
    (; ire_aux, vintages, ts_frac) = m.ix
    e = E()
    for (p, com, ts, ie) in onbranch(ire_aux[r, t, c, io], ts_frac[r, s], 3)
        (only(p) && (r, p, com, ie) in RPC_IRE && (r, t, p, com, ts) in RTPCS_VARF && has(RS_FR, r, s, ts)) || continue
        k = IRE_FLOSUM(r, t, p, com, ts, ie, c, io) * frac(m, r, t, com, s, ts)
        for v in vintages[r, t, p]
            w = k * weight(p, v, ts)
            iszero(w) || add!(e, w, trade(m, r, v, t, p, com, ts, ie))
        end
    end
    return e
end

"""Label of the pseudo-year 0, under which TIMES files flags and totals."""
year0(m::Model) = id!(m.L, "0")          # the label is added when no table read so far has it

"""Milestone year before t, or `nothing` for the first one."""
function previous(m::Model, t)
    i = findfirst(==(t), m.T)
    return (i === nothing || i == 1) ? nothing : m.T[i-1]
end

"""
Capacity of vintage v that still stands in period t: what was installed, less what has been
retired by t (prepret.dsc, RCAPSUB).

    installed(r,v,p)  -  VAR_SCAP(r,v,t,p) [p can be retired early, v lies before t]
"""
function standing(::Type{E}, m::Model, r, v, t, p) where {E}
    e = installed(E, m, r, v, p)
    ((r, p) in m.d.PRC_RCAP && (v, t) in m.d.VNTRT) && addto!(e, -1.0, m.v.VAR_SCAP(r, v, t, p))
    return e
end

"""
Capacity behind the flows of (v, p) in period t (RVP_KMAP, COEF_VNT): the vintage itself for a
vintaged process, all vintages k available in t otherwise. `k -> weight` multiplies each vintage.

    SUM(k, COEF_VNT(r,t,p,k) * weight(k) * standing(r,k,t,p))
"""
function capacity_of(::Type{E}, m::Model, r, v, t, p; weight = k -> 1.0) where {E}
    e = E()
    for k in m.ix.kmap[r, v, p]
        w = m.d.COEF_VNT(r, t, p, k) * weight(k)
        iszero(w) || add!(e, w, standing(E, m, r, k, t, p))
    end
    return e
end

"""
Storage flows of commodity c at timeslice s, net (cal_stgn.mod). A commodity that a storage both
charges and discharges is booked on one side only (RPC_STGN names the side that is netted off):

    io = OUT:   SUM((p,v,ts), RS_FR(r,s,ts) * weight * (STG_EFF(r,v,p) * VAR_SOUT - VAR_SIN [netted]))
    io = IN:    SUM((p,v,ts), RS_FR(r,s,ts) * (VAR_SIN - weight * STG_EFF(r,v,p) * VAR_SOUT [netted]))

Night storage (PRC_NSTTS): the output side takes the timeslices in which the process does not
store, the input side those in which it does. `weight` and `only` are used by the peak equation.
"""
function storage(::Type{E}, m::Model, r, t, c, s, io; weight = unweighted, only = any_process) where {E}
    (; RPC_STG, RPC_STGN, RS_FR, STG_EFF, PRC_MAP, PRC_NSTTS) = m.d
    (; top_p, rpcs_s, vintages, ts_frac) = m.ix
    (; VAR_SIN, VAR_SOUT) = m.v
    (; IN, OUT, NST) = m.K
    e = E()
    for p in top_p[r, c, io]
        ((r, p, c) in RPC_STG && only(p) && !((r, p, c, io) in RPC_STGN)) || continue
        other = io == OUT ? IN : OUT
        netted = (r, p, c, other) in RPC_STGN
        nst = (r, NST, p) in PRC_MAP
        for ts in onbranch(rpcs_s[r, p, c], ts_frac[r, s])
            fr = RS_FR(r, s, ts)
            iszero(fr) && continue
            # night storage delivers outside its storing timeslices and takes in within them
            storing = (r, p, ts) in PRC_NSTTS
            (io == OUT ? !storing : (!nst || storing)) || continue
            for v in vintages[r, t, p]
                w = weight(p, v, ts)
                if io == OUT
                    add!(e, fr * w * STG_EFF(r, v, p), VAR_SOUT(r, v, t, p, c, ts))
                    netted && add!(e, -fr * w, VAR_SIN(r, v, t, p, c, ts))
                else
                    add!(e, fr, VAR_SIN(r, v, t, p, c, ts))
                    netted && add!(e, -fr * w * STG_EFF(r, v, p), VAR_SOUT(r, v, t, p, c, ts))
                end
            end
        end
    end
    return e
end

"""
Flows of commodity c that come with capacity (NCAP_COM), at timeslice s (cal_cap.mod):

    SUM((v,p), COEF_CPT(r,v,t,p) * NCAP_COM(r,v,p,c,io) * G_YRFR(r,s) * standing(r,v,t,p) * (1 + COEF_CIO(r,v,t,p,c,io)))

(COEF_CIO < 0 where NCAP_CLAG delays the flow or ends it early within the period)

and the flows tied to investment (IN: COEF_ICOM) and decommissioning (OUT: COEF_OCOM) of the new capacity of v
(CAL_NCOM in cal_cap.mod):

    SUM((v,p), COEF_ICOM / COEF_OCOM(r,v,t,p,c) * G_YRFR(r,s) * (VAR_NCAP(r,v,p) [v a period] + NCAP_PASTI(r,v,p) [v past]))

and, for the release (OUT) of a vintage with flows of retired capacity (RCAP_OCAP), in the periods t after v:

    SUM(v, COEF_OCOM(r,v,t,p,c) * G_YRFR(r,s) * -VAR_SCAP(r,v,v+MIN(t-v,RVPRL(r,v,p)),p)
           + COEF_RCOM(r,v,t,p,c) * G_YRFR(r,s) * VAR_RCAP(r,v,t,p))
"""
function capacity_flows(::Type{E}, m::Model, r, t, c, s, io; only = any_process) where {E}
    (; RTP_CPTYR, COEF_CPT, NCAP_COM, COEF_CIO, G_YRFR) = m.d
    e = E()
    for (v, p) in m.ix.ncap_com[r, c, io]
        ((r, v, t, p) in RTP_CPTYR && only(p)) || continue
        k = COEF_CPT(r, v, t, p) * NCAP_COM(r, v, p, c, io) * G_YRFR(r, s) * (1 + COEF_CIO(r, v, t, p, c, io))
        iszero(k) || add!(e, k, standing(E, m, r, v, t, p))
    end
    coef, at = io == m.K.IN ? (m.d.COEF_ICOM, m.ix.icom_at) : (m.d.COEF_OCOM, m.ix.ocom_at)
    for (v, p) in at[r, t, c]
        only(p) || continue
        k = coef(r, v, t, p, c) * G_YRFR(r, s)
        iszero(k) || add!(e, k, installed(E, m, r, v, p))
        # SUM(VNTRT(V,T),COEF_OCOM*SUM(TT(LL+MIN(VN2T(V,T),RVPRL(R,V,P))),-VAR_SCAP(R,V,TT,P)) + VAR_RCAP(R,V,T,P)*COEF_RCOM)
        #   $((IPS('OUT')->0)$RCAP_OCAP(R,V,P,C))
        (io == m.K.OUT && has(m.d.RCAP_OCAP, r, v, p, c) && (v, t) in m.d.VNTRT) || continue
        yv = year(m.L, v)
        target = yv + min(year(m.L, t) - yv, plain(m.d.RVPRL(r, v, p)))
        i = findfirst(x -> year(m.L, x) == target, m.T)
        i === nothing || add!(e, -k, m.v.VAR_SCAP(r, v, m.T[i], p))
        add!(e, m.d.COEF_RCOM(r, v, t, p, c) * G_YRFR(r, s), m.v.VAR_RCAP(r, v, t, p))
    end
    return e
end

# The same functions called without an expression type: JuMP's AffExpr (the families not built in arrays, lx.jl)
installed(m::Model, args...; kw...) = installed(AE, m, args...; kw...)
standing(m::Model, args...; kw...) = standing(AE, m, args...; kw...)
capacity_of(m::Model, args...; kw...) = capacity_of(AE, m, args...; kw...)
flow(m::Model, args...; kw...) = flow(AE, m, args...; kw...)
flows(m::Model, args...; kw...) = flows(AE, m, args...; kw...)
trades(m::Model, args...; kw...) = trades(AE, m, args...; kw...)
trade_aux(m::Model, args...; kw...) = trade_aux(AE, m, args...; kw...)
storage(m::Model, args...; kw...) = storage(AE, m, args...; kw...)
capacity_flows(m::Model, args...; kw...) = capacity_flows(AE, m, args...; kw...)
supply(m::Model, args...; kw...) = supply(AE, m, args...; kw...)
uc_terms(m::Model, args...; kw...) = uc_terms(AE, m, args...; kw...)
uc_dynamic(m::Model, args...; kw...) = uc_dynamic(AE, m, args...; kw...)
