# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_RL_LOAD, EQ_RL_NDIS, EQ_RL_STCAP, EQ_RL_PKCAP, EQ_RL_THMIN                 resloadc.vda EQUA

The residual load curve, in the regions and periods of GR_RLDC (every period but the first), on the finest
timeslices s. VAR_RLD(r,t,s,item) is the load of a type of generation (RL-DISP: the dispatchable residual load, free).
gen(item) is the electricity produced by the processes of the type, brought to s (cal_red with RS_FR * (1+RTCS_FR)).

    EQ_RL_LOAD:   gen(GR_GENMAP RL-DISP) + VAR_RLD(RL-THMIN) * G_YRFR [RL-THMIN given]
                  - storage input + storage output * STG_EFF - curtailment (VAR_COMNET / COM_IE) [GR_RLDC(r,'0')]
                  =  VAR_RLD(RL-DISP) * G_YRFR(r,s)
    EQ_RL_NDIS:   gen(GR_RLGT item)  =  VAR_RLD(item) * G_YRFR(r,s)                     (items with GR_VARGEN ANNUAL FX)
    EQ_RL_STCAP:  storage capacity  >=  VAR_RLD('RL_THMIN') - VAR_RLD(RL-DISP)
                                        + VAR_RLD(RL-DISP) * GR_VARGEN(LO) + SUM(other items, VAR_RLD * GR_VARGEN(UP))
    EQ_RL_PKCAP:  dispatchable and storage output capacity  >=  VAR_RLD(RL-DISP) * (1 + GR_VARGEN(UP))
                                        + SUM(other items, VAR_RLD * GR_VARGEN(LO))
    EQ_RL_THMIN:  LO: VAR_RLD('RL_THMIN')  >=  SUM(p of RL-THMIN, PRC_CAPACT * (GR_THBND FX + online capacity * level))
                  UP: VAR_RLD(RL-THMIN) - VAR_RLD('RL_THMIN')  >=  0                     [RL-THMIN given]

'RL_THMIN' (underscore) is the item TIMES writes in EQ_RL_STCAP and EQ_RL_THMIN, where the rest of the file has
'RL-THMIN': a variable of its own, as in GAMS (a suspected defect of TIMES, reproduced).
"""
function eq_rl!(m::Model)
    (; GR_RLDC, GR_RLGT, GR_GENMAP, GR_VARGEN, GR_THBND, GR_THMIN, RLDC, NRG_TMAP, PRC_CAP, FINEST, TOP, RS_FR, G_YRFR,
       COM_IE, RHS_COMBAL, STG_EFF, PRC_CAPACT, RS_STGPRD, COEF_CPT, COEF_AF, PRC_ACTFLO, NCAP_AFCS, RPS_CAFLAC, PRC_TS,
       PRC_VINT, ACT_UPS) = m.d
    (; vintages, flow_s, rpcs_s, top_c, stg_p, agg_into, ts_above, retirable, cpt_v, pcg, prc_ts, ts_ann, type_of) = m.ix
    (; VAR_RLD, VAR_SIN, VAR_SOUT, VAR_COMNET) = m.v
    (; IN, OUT, LO, UP, FX, ANNUAL) = m.K
    isempty(GR_RLDC) && return
    ELC = id!(m.L, "ELC")
    DISP, THMIN, THMIN_ = id!(m.L, "RL-DISP"), id!(m.L, "RL-THMIN"), id!(m.L, "RL_THMIN")
    items = [u for (u,) in RLDC]
    elc(r, c) = (r, ELC, c) in NRG_TMAP
    zero = year0(m)
    finest = Dict{Id,Vector{Id}}()
    for (r, s) in FINEST
        push!(get!(finest, r, Id[]), s)
    end
    combal = Dict{Tuple{Id,Id},Vector{Tuple{Id,Id}}}()
    for (r, t, c, s) in RHS_COMBAL
        push!(get!(combal, (r, t), Tuple{Id,Id}[]), (c, s))
    end
    rlgt = Dict{Tuple{Id,Id},Vector{Id}}()
    for (r, p, u) in GR_RLGT
        push!(get!(rlgt, (r, u), Id[]), p)
    end
    disp = Dict{Id,Vector{Id}}()
    for ((r, p, u), _) in GR_GENMAP
        u == DISP && push!(get!(disp, r, Id[]), p)
    end

    # electricity produced by the processes ps, brought to s
    function gen(r, t, s, ps)
        e = AE()
        for p in ps, c in top_c[r, p, OUT]
            elc(r, c) || continue
            for v in vintages[r, t, p], ts in flow_s[r, t, p, c]
                f = RS_FR(r, s, ts)
                iszero(f) && continue
                add!(e, frac(m, r, t, c, s, ts), flow(m, r, v, t, p, c, ts))
            end
        end
        return e
    end
    # the availability of storage flows by commodity (RPS_CAFLAC): 1 / RS_STGPRD / STG_EFF * NCAP_AFCS of c, or the product
    # of those of its types when c has none
    function caflac(r, v, p, c, s, ts)
        (r, p, ts, UP) in RPS_CAFLAC || return 1.0
        own = NCAP_AFCS(r, v, p, c, ts)
        af = has(NCAP_AFCS, r, v, p, c, ts) ? own : prod((NCAP_AFCS(r, v, p, cg, ts) for cg in type_of[r, c] if has(NCAP_AFCS, r, v, p, cg, ts)); init = 1.0)
        return 1 / RS_STGPRD(r, s) / STG_EFF(r, v, p) * af
    end
    elc_stg(r) = [(p, c) for (p, c) in stg_p[r] if elc(r, c)]
    vargen(r, s, u, bd) = GR_VARGEN(r, s, u, bd)

    for (r, t) in GR_RLDC
        t in m.T || continue
        (m.stepped && !(t in m.sub)) && continue
        curtail = (r, zero) in GR_RLDC
        for s in get(finest, r, Id[])
            yr = G_YRFR(r, s)
            # --- EQ_RL_LOAD
            e = gen(r, t, s, get(disp, r, Id[]))
            THMIN in items && add!(e, yr, VAR_RLD(r, t, s, THMIN))
            for (p, c) in elc_stg(r), io in (IN, OUT)
                (r, p, c, io) in TOP || continue
                for v in vintages[r, t, p], ts in rpcs_s[r, p, c]
                    f = RS_FR(r, s, ts)
                    iszero(f) && continue
                    io == IN ? add!(e, -f, VAR_SIN(r, v, t, p, c, ts)) : add!(e, f * STG_EFF(r, v, p), VAR_SOUT(r, v, t, p, c, ts))
                end
            end
            if curtail
                for (c, ts) in get(combal, (r, t), Tuple{Id,Id}[])
                    (elc(r, c) && isempty(agg_into[r, t, c])) || continue
                    f = RS_FR(r, s, ts)
                    iszero(f) && continue
                    add!(e, -frac(m, r, t, c, s, ts) / COM_IE(r, t, c, ts), VAR_COMNET(r, t, c, ts))
                end
            end
            row!(m, :EQ_RL_LOAD, (r, t, s), e, ==, yr * VAR_RLD(r, t, s, DISP))
            # --- EQ_RL_NDIS
            for u in items
                has(GR_VARGEN, r, ANNUAL, u, FX) || continue
                row!(m, :EQ_RL_NDIS, (r, t, s, u), gen(r, t, s, get(rlgt, (r, u), Id[])), ==, yr * VAR_RLD(r, t, s, u))
            end
            # --- EQ_RL_STCAP
            cap = AE()
            for (p, c) in elc_stg(r)
                ((r, p, c, OUT) in TOP && (r, p) in PRC_CAP && (r, p, s) in PRC_TS) || continue
                for v in retirable[r, t, p]
                    k = COEF_CPT(r, v, t, p) * PRC_ACTFLO(r, v, p, c)
                    ks = [plain(COEF_AF(r, v, t, p, ts, UP)) / RS_FR(r, s, ts) * caflac(r, v, p, c, s, ts)
                          for ts in ts_above[r, s] if has(COEF_AF, r, v, t, p, ts, UP)]
                    isempty(ks) && continue
                    w = PRC_CAPACT(r, p) * RS_STGPRD(r, s) * k * minimum(ks)
                    iszero(w) || add!(cap, w, standing(m, r, v, t, p))
                end
            end
            need = AE()
            add!(need, 1.0, VAR_RLD(r, t, s, THMIN_))
            add!(need, -1.0, VAR_RLD(r, t, s, DISP))
            for u in items
                w = vargen(r, s, u, u == DISP ? LO : UP)
                iszero(w) || add!(need, w, VAR_RLD(r, t, s, u))
            end
            row!(m, :EQ_RL_STCAP, (r, t, s), cap, >=, need)
            # --- EQ_RL_PKCAP
            cap = AE()
            for p in get(rlgt, (r, DISP), Id[])
                (r, p) in PRC_CAP || continue
                n = count(ts -> !iszero(RS_FR(r, s, ts)), prc_ts[r, p])
                for v in cpt_v[r, t, p]
                    af = maximum((PRC_ACTFLO(r, v, p, c) for c in pcg[r, p] if elc(r, c)); init = -Inf)
                    w = PRC_CAPACT(r, p) * COEF_CPT(r, v, t, p) * af * n * plain(COEF_AF(r, v, t, p, s, UP))
                    iszero(w) || add!(cap, w, standing(m, r, v, t, p))
                end
            end
            for (p, c) in elc_stg(r)
                ((r, p, c, OUT) in TOP && (r, p) in PRC_CAP && (r, p, s) in PRC_TS) || continue
                for v in retirable[r, t, p]
                    w = PRC_CAPACT(r, p) * RS_STGPRD(r, s) * COEF_CPT(r, v, t, p) * plain(COEF_AF(r, v, t, p, s, UP)) *
                        PRC_ACTFLO(r, v, p, c) * STG_EFF(r, v, p) * caflac(r, v, p, c, s, s)
                    iszero(w) || add!(cap, w, standing(m, r, v, t, p))
                end
            end
            need = AE()
            add!(need, 1.0, VAR_RLD(r, t, s, DISP))
            for u in items
                w = vargen(r, s, u, u == DISP ? UP : LO)
                iszero(w) || add!(need, w, VAR_RLD(r, t, s, u))
            end
            row!(m, :EQ_RL_PKCAP, (r, t, s), cap, >=, need)
            # --- EQ_RL_THMIN
            level = AE()
            for p in get(rlgt, (r, THMIN), Id[])
                (r, p) in PRC_CAP || continue
                add!(level, 1.0, PRC_CAPACT(r, p) * GR_THBND(r, t, p, FX))
                vint = (r, p) in PRC_VINT
                for v in vintages[r, t, p], s2 in prc_ts[r, p]
                    iszero(RS_FR(r, s, s2)) && continue
                    af = maximum((PRC_ACTFLO(r, v, p, c) for c in pcg[r, p] if elc(r, c)); init = -Inf)
                    lv = GR_THBND(r, t, p, LO) + GR_THBND(r, t, p, UP)
                    has(GR_THMIN, r, t, p) || (lv += sum(plain(ACT_UPS(r, v, p, sl, FX)) for sl in ts_ann[s2]; init = 0.0))
                    w = PRC_CAPACT(r, p) * af * lv
                    iszero(w) && continue
                    online = AE()
                    for k in cpt_v[r, t, p]
                        (vint && k != v) && continue
                        add!(online, COEF_CPT(r, k, t, p), standing(m, r, k, t, p))
                    end
                    add!(online, -1.0, offline(m, r, v, t, p, s2))
                    add!(level, w, online)
                end
            end
            row!(m, :EQ_RL_THMIN, (r, t, s, LO), 1.0 * VAR_RLD(r, t, s, THMIN_), >=, level)
            THMIN in items && row!(m, :EQ_RL_THMIN, (r, t, s, UP), VAR_RLD(r, t, s, THMIN) - VAR_RLD(r, t, s, THMIN_), >=, 0.0)
        end
    end
end
