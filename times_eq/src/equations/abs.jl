# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_BS00 .. EQ_BS28                                                           equ_ext.abs

The ancillary balancing services (run-file switch ABS=YES): reserve commodities c (BS_RTYPE: FCR 1, aFRR 2, mFRR 3,
RR 4, negative for downward reserves), their demand and their provision by processes.

The demand of a reserve is the net production VAR_COMNET of its commodity, at least the deterministic level
VAR_COMLV('DET') (exogenous, or tied to the largest unit of the SI processes) and the probabilistic one
VAR_COMLV('PRB') (three standard deviations of the imbalance of demand, wind and solar, VAR_RLD by source).
The provision VAR_BSPRS(r,v,t,p,c,s,l) is spinning (l = N) or non-spinning (l = FX, reserve types above 2); with
c = ACT it is the capacity started up or shut down (l = LO, UP) and the capacity in maintenance (l = N); with
v = t and l = UP it is the slack of a bound on the provision (EQ_BS26).

The on-line capacity of a process at s (var_bson) is the gap variable VAR_UDP(..,FX) of the timeslice directly above
s, plus the started-up capacity VAR_UPS(..,FX) less what is off line in s, where s carries off-line capacity.
"""

"""
var_bson(r,v,t,p,s):  SUM(ts_map(r,all_ts,s)\$(rs_below1(r,all_ts,s)+annual(s)),
                          var_gap(r,v,t,p,all_ts)+(VAR_UPS(r,v,t,p,all_ts,'FX')-var_off(r,v,t,p,s))\$rps_ups(r,p,s))
"""
function bs_on(m::Model, r, v, t, p, s)
    (; RPS_UPS, RS_BELOW1) = m.d
    (; VAR_UDP, VAR_UPS) = m.v
    (; FX, N, ANNUAL) = m.K
    e = AE()
    ups = (r, p, s) in RPS_UPS
    for ts in m.ix.ts_above[r, s]
        ((r, ts, s) in RS_BELOW1 || s == ANNUAL) || continue
        add!(e, 1.0, VAR_UDP(r, v, t, p, ts, FX))
        if ups
            add!(e, 1.0, VAR_UPS(r, v, t, p, ts, FX))
            add!(e, -1.0, VAR_UPS(r, v, t, p, s, N))
        end
    end
    return e
end

"""
%TMP% of equ_ext.abs: SUM(MODLYEAR(K)\$(COEF_VNT(R,T,P,K)\$(PRC_VINT(R,P)->DIAG(V,K))),
                          COEF_VNT(R,T,P,K)*(VAR_NCAP(R,K,P)\$T(K)+NCAP_PASTI(R,K,P)%RCAPSBM%))
"""
function bs_cap(m::Model, r, v, t, p)
    (; COEF_VNT, PRC_VINT) = m.d
    vint = (r, p) in PRC_VINT
    e = AE()
    for k in m.ix.cpt_v[r, t, p]
        (vint && k != v) && continue
        has(COEF_VNT, r, t, p, k) || continue
        add!(e, COEF_VNT(r, t, p, k), dispatch_standing(m, r, k, t, p))
    end
    return e
end

function eq_bs!(m::Model)
    (; BS_RTYPE, BS_MAINT) = m.d
    # EQ_BS27 / EQ_BS28 (maintenance) need BS_MAINT only: with no reserve commodity left (BS_RTYPE given as 0 under
    # \$ONEPS: BS_RTYPE(R,C)\$BS_RTYPE(R,C) = SIGN(BS_RTYPE(R,C))*..., and SIGN(EPS) is 0) they are still written
    isempty(BS_RTYPE) && isempty(BS_MAINT) && return
    (; RTP_VINTYR, RTP, RTC, RHS_COMBAL, RTCS_VARC, FINEST, PRC_TS, RPS_UPS, RPS_STG, RP_STD, RP_STG, RP_DP, TOP, RPC_STG,
       RPC_IRE, RPC_AIRE, NRG_TMAP, RS_FR, TS_MAP, G_YRFR, PRC_CAPACT, PRC_VINT, COEF_AF, COEF_AFUPS, ACT_UPS, ACT_MINLD,
       ACT_SDTIME, ACT_TIME, RS_STGPRD, RS_MODUS, STG_EFF, PRC_SC, AFS, PRC_NSTTS, PRC_STGTSS, GR_GENMAP, RTCS_FR,
       BS_LAMBDA, BS_DETWT, BS_OMEGA, BS_DELTA, BS_SIGMA, BS_SHARE, BS_RTCS, BS_CAPACT, BS_STIME, BS_RMAX, BS_MAINT,
       BS_BNDPRS, BS_TSCYC, BS_EUCAP, BS_K, BS_RTK, BS_COMTS, BS_APOS, BS_ANEG, BS_ABD, BS_BSC, BS_UPL, BS_UPC, BS_TOP,
       BS_ENDP, BS_SUPP, BS_STGP, BS_NEGP, BS_PRS, BS_SBD, BS_RVT, BS_CONLY, COEF_VNT) = m.d
    (; vintages, ts_above, ts_below, ts_ann, ts_prev, prc_ts, flow_s, rpcs_s, top_c, stg_c, cycle_of, cycle_ts, ts_group,
       cpt_v) = m.ix
    (; VAR_COMLV, VAR_BSPRS, VAR_COMNET, VAR_COMPRD, VAR_RLD, VAR_ACT, VAR_SOUT, VAR_SIN, VAR_UPS) = m.v
    (; LO, UP, FX, N, IN, OUT, EXP, ACT, ANNUAL) = m.K
    L = m.L
    DET, PRB, SI = id!(L, "DET"), id!(L, "PRB"), id!(L, "SI")
    EXOGEN, WMAXSI, HOT, ELC = id!(L, "EXOGEN"), id!(L, "WMAXSI"), id!(L, "HOT"), id!(L, "ELC")
    zero = year0(m)
    one = id!(L, "1")                         # %SWX%: the state of the world '1' (the ALLSOW index of the EQ_BS rows)
    bdsig(bd) = bd == LO ? 1.0 : bd == UP ? -1.0 : 0.0          # BDSIG: LO 1, UP -1
    rtype(r, c) = plain(BS_RTYPE(r, c))
    T = Set(m.T)

    # lookups
    group(pairs) = (d = Dict{Any,Vector{Any}}(); for (k, x) in pairs; push!(get!(d, k, Any[]), x); end; d)
    get0(d, k) = get(d, k, Id[])
    bsc_c = group(((r, p), c) for (r, p, c) in BS_BSC)
    abd_c = group(((r, bd), c) for (r, c, bd) in BS_ABD)
    abd_of = group(((r, c), bd) for (r, c, bd) in BS_ABD)
    comts_c = group(((r, s), c) for (r, c, s) in BS_COMTS)
    prs_s = group(((r, p), s) for (r, p, s) in BS_PRS)
    rtk_k = group(((r, t), k) for (r, t, k) in BS_RTK)
    genmap_p = group(((r, k), p) for ((r, p, k), _) in GR_GENMAP)
    bstop = Dict{Any,Vector{Tuple{Id,Id}}}()
    for (r, p, c, io) in BS_TOP
        push!(get!(bstop, (r, p), Tuple{Id,Id}[]), (c, io))
    end
    stime_p = group(((r, c), p) for ((r, p, c, bd), _) in BS_STIME if bd == UP)
    # processes that provide reserve c: BS_BSC(R,P,C)+YES$BS_STIME(R,P,C,'UP')
    providers = Dict{Any,Vector{Id}}()
    for (r, p, c) in BS_BSC
        push!(get!(providers, (r, c), Id[]), p)
    end
    for ((r, c), ps) in stime_p, p in ps
        v = get!(providers, (r, c), Id[])
        p in v || push!(v, p)
    end
    provides(r, p, c) = (r, p, c) in BS_BSC || has(BS_STIME, r, p, c, UP)
    omega0 = group(((r, c), s) for ((r, t, c, s), _) in BS_OMEGA if t == zero)
    upc = Dict{Any,Vector{Tuple{Id,Id}}}()
    for (r, p, tsl, l) in BS_UPC
        push!(get!(upc, (r, p), Tuple{Id,Id}[]), (tsl, l))
    end
    conly = group(((r, v, p), c) for (r, v, p, c) in BS_CONLY)

    # the variables of the macros of equ_ext.abs
    rvt(r, v, t) = (r, v, t) in BS_RVT
    fsp(r, v, t, p, c, s) = rvt(r, v, t) ? 1.0 * VAR_BSPRS(r, v, t, p, c, s, N) : AE()          # var_bsfsp
    fnsp(r, v, t, p, c, s) = rvt(r, v, t) ? 1.0 * VAR_BSPRS(r, v, t, p, c, s, FX) : AE()        # var_bsfnsp
    upsr(r, v, t, p, s, bd) = rvt(r, v, t) ? 1.0 * VAR_BSPRS(r, v, t, p, ACT, s, bd) : AE()     # var_bsupsr
    mup(r, v, t, p, s) = VAR_BSPRS(r, v, t, p, ACT, s, N)                                       # var_bsmup
    off(r, v, t, p, s) = VAR_UPS(r, v, t, p, s, N)                                              # var_off
    bsd(typ, r, t, c, s) = VAR_COMLV(typ, r, t, c, s)                                           # var_bsd
    # the provision of reserve c by (v, p) at the row's timeslice s (EQ_BS00, EQ_BS01, EQ_BS26):
    #   SUM(BS_PRS(R,P,TS)$RS_FR(R,S,TS),(VAR_BSFSP(..,TS)+SUM(BS_SUPP(R,P)$(ABS(BS_RTYPE(R,C))>2),VAR_BSFNSP(..,TS)))*RS_FR(R,TS,S))
    function provision!(e, k, r, v, t, p, c, s)
        nsp = (r, p) in BS_SUPP && abs(rtype(r, c)) > 2
        for ts in get0(prs_s, (r, p))
            has(RS_FR, r, s, ts) || continue
            f = k * RS_FR(r, ts, s)
            add!(e, f, fsp(r, v, t, p, c, ts))
            nsp && add!(e, f, fnsp(r, v, t, p, c, ts))
        end
        return e
    end
    # STG time factor of EQ_BS22 / EQ_BS23:
    #   BS_STIME(R,P,C,'LO')/2 +(BS_STIME(R,P,C,'UP')-BS_STIME(R,P,C,'LO'))*MAX(1,G_YRFR(R,S)/RS_STGPRD(R,S)*8760/(1+BS_STIME(R,P,C,'UP'))**0.5)
    stfac(r, p, c, s) = BS_STIME(r, p, c, LO) / 2 + (BS_STIME(r, p, c, UP) - BS_STIME(r, p, c, LO)) *
                        max(1.0, G_YRFR(r, s) / RS_STGPRD(r, s) * 8760 / sqrt(1 + BS_STIME(r, p, c, UP)))
    stgout(r, v, t, p, s) = begin                # SUM(TOP(RPC_STG(R,P,C),'OUT'),V_U(SOUT,R,V,T,P,C,S)*STG_EFF(R,V,P))
        e = AE()
        for c in stg_c[r, p]
            (r, p, c, OUT) in TOP && add!(e, STG_EFF(r, v, p), VAR_SOUT(r, v, t, p, c, s))
        end
        e
    end
    # (VAR_ACT(R,V,T,P,S)$RP_STD(R,P)+SUM(TOP(RPC_STG(R,P,C),'OUT'),V_U(SOUT,R,V,T,P,C,S)*STG_EFF(R,V,P))$RP_STG(R,P))/G_YRFR(R,S)
    function output(r, v, t, p, s)
        e = AE()
        (r, p) in RP_STD && add!(e, 1 / G_YRFR(r, s), VAR_ACT(r, v, t, p, s))
        (r, p) in RP_STG && add!(e, 1 / G_YRFR(r, s), stgout(r, v, t, p, s))
        return e
    end

    # ---- ABSEQ1 : Demands for reserves
    #  EQ_BS00(RTC(%R_T%,C),RTS(S))$(BS_OMEGA(R,'0',C,S)$BS_LAMBDA(RTC))..
    #  SUM(RHS_COMBAL(RTC,TS)$TS_MAP(R,TS,S),%VAR%_COMPRD(RTC,TS)/G_YRFR(R,TS))  =L=
    #  SUM((RHS_COMBAL(RTC,SL),TS_MAP(R,SL,S))$BS_OMEGA(RTC,SL),
    #    SUM(RTP_VINTYR(R,V,T,P)$(BS_BSC(R,P,C)+YES$BS_STIME(R,P,C,'UP')),PRC_CAPACT(R,P) * <provision>));
    for ((r, t, c), _) in BS_LAMBDA
        (t in T && (r, t, c) in RTC) || continue
        for s in get0(omega0, (r, c))
            lhs = AE()
            for ts in ts_above[r, s]
                (r, t, c, ts) in RHS_COMBAL && add!(lhs, 1 / G_YRFR(r, ts), VAR_COMPRD(r, t, c, ts))
            end
            rhs = AE()
            for sl in ts_above[r, s]
                ((r, t, c, sl) in RHS_COMBAL && has(BS_OMEGA, r, t, c, sl)) || continue
                for p in get0(providers, (r, c)), v in vintages[r, t, p]
                    provision!(rhs, PRC_CAPACT(r, p), r, v, t, p, c, s)
                end
            end
            row!(m, :EQ_BS00, (r, t, c, s, one), lhs, <=, rhs)
        end
    end

    # ---- ABSEQ1+: Max and ABS(diff) and Share equations
    #  EQ_BS01(RHS_COMBAL(RTC(%R_T%,C),RTS(S)),BS_K,L)$((BS_OMEGA(RTC,S)<>2$IPS(L))$BS_SHARE(RTC,BS_K,L)$BS_OMEGA(RTC,S))..
    #  SUM(BD(LIM(BS_K)),%VAR%_COMNET(RTC,S)/G_YRFR(R,S) - BS_LAMBDA(RTC) *
    #    (VAR_BSD('PRB',RTC,S)$BDUPX(BD)-VAR_BSD('DET',RTC,S)$BDLOX(BD))$(BS_OMEGA(RTC,S)<2) -
    #    ((VAR_BSD('PRB',RTC,S)-VAR_BSD('DET',RTC,S))*BDSIG(BD))$(BS_OMEGA(RTC,S)>2))$IPS(L) +
    #  SUM(BD(L), SUM(RTP_VINTYR(R,V,T,P)$((BS_BSC(R,P,C)+YES$BS_STIME(R,P,C,'UP'))$GR_GENMAP(R,P,BS_K)),PRC_CAPACT(R,P) * <provision>) -
    #    BS_SHARE(RTC,BS_K,L)*%VAR%_COMNET(RTC,S)/G_YRFR(R,S))*BDSIG(L)  =G= 0;
    shares = Dict{Any,Vector{Tuple{Id,Id}}}()
    for ((r, t, c, k, l), _) in BS_SHARE
        k in BS_K && push!(get!(shares, (r, t, c), Tuple{Id,Id}[]), (k, l))
    end
    for (r, t, c, s) in RHS_COMBAL
        (t in T && (r, t, c) in RTC && has(BS_OMEGA, r, t, c, s)) || continue
        om = plain(BS_OMEGA(r, t, c, s))
        lam = BS_LAMBDA(r, t, c)
        for (k, l) in get(shares, (r, t, c), Tuple{Id,Id}[])
            om != (l == N ? 2.0 : 0.0) || continue
            e = AE()
            if l == N && (k == LO || k == UP)
                g = 1 / G_YRFR(r, s)
                add!(e, g, VAR_COMNET(r, t, c, s))
                if om < 2
                    k == UP && add!(e, -lam, bsd(PRB, r, t, c, s))
                    k == LO && add!(e, lam, bsd(DET, r, t, c, s))
                end
                if om > 2
                    add!(e, -bdsig(k), bsd(PRB, r, t, c, s))
                    add!(e, bdsig(k), bsd(DET, r, t, c, s))
                end
            end
            if l == LO || l == UP || l == FX
                sg = bdsig(l)
                for p in get0(providers, (r, c))
                    has(GR_GENMAP, r, p, k) || continue
                    for v in vintages[r, t, p]
                        provision!(e, sg * PRC_CAPACT(r, p), r, v, t, p, c, s)
                    end
                end
                add!(e, -sg * BS_SHARE(r, t, c, k, l) / G_YRFR(r, s), VAR_COMNET(r, t, c, s))
            end
            row!(m, :EQ_BS01, (r, t, c, s, k, l, one), e, >=, 0.0)
        end
    end

    # ---- ABSEQ2 : Loads by source of imbalance for each user category k
    #  EQ_BS02(%R_T%,RTS(S),BS_K)$(SUM(BS_SBD(FINEST(R,S),BD),1)$BS_RTK(R,T,BS_K))..
    #  SUM(BS_TOP(RP_STD(R,P),C,IO)$GR_GENMAP(R,P,BS_K), SUM((RTP_VINTYR(R,V,T,P),RTPCS_VARF(R,T,P,C,TS))$RS_FR(R,S,TS),
    #      %cal_red% * RS_FR(R,S,TS)*(1+RTCS_FR(R,T,C,S,TS)))) +
    #  SUM(RPC_STG(R,P,C)$GR_GENMAP(R,P,BS_K),SIGN(GR_GENMAP(R,P,BS_K))*
    #    SUM((RTP_VINTYR(R,V,T,P),RPCS_VAR(R,P,C,TS))$RS_FR(R,S,TS),RS_FR(R,S,TS)*(1+RTCS_FR(R,T,C,S,TS))*
    #       SUM(BS_TOP(R,P,C,'OUT'),V_U(SOUT,R,V,T,P,C,TS)*STG_EFF(R,V,P))-SUM(BS_TOP(R,P,C,'IN'),V_U(SIN,R,V,T,P,C,TS)))) +
    #  SUM(RPC_IRE(R,P,C,IE)$(NRG_TMAP(R,'ELC',C)$GR_GENMAP(R,P,BS_K)),SIGN(GR_GENMAP(R,P,BS_K))*
    #    SUM((RTP_VINTYR(R,V,T,P),RTPCS_VARF(R,T,P,C,TS))$RS_FR(R,S,TS),
    #       (%VAR%_IRE(R,V,T,P,C,TS,IE)$(NOT RPC_AIRE(R,P,C))+(%VAR%_ACT(R,V,T,P,TS)*PRC_ACTFLO(R,V,P,C))$RPC_AIRE(R,P,C))*
    #       (1-2$XPT(IE)) * RS_FR(R,S,TS)*(1+RTCS_FR(R,T,C,S,TS))))
    #  =E=  %VAR%_RLD(R,T,S,BS_K)*G_YRFR(R,S);
    sbd_r = Set((r, s) for (r, s, bd) in BS_SBD if bd == LO || bd == UP || bd == FX)
    ire_c = group(((r, p), (c, ie)) for (r, p, c, ie) in RPC_IRE)
    for (r, t, k) in BS_RTK
        t in T || continue
        for (rr, s) in FINEST
            (rr == r && (r, s) in sbd_r) || continue
            e = AE()
            for p in get0(genmap_p, (r, k))
                g = GR_GENMAP(r, p, k)
                if (r, p) in RP_STD
                    for (c, io) in get(bstop, (r, p), Tuple{Id,Id}[]), v in vintages[r, t, p], ts in flow_s[r, t, p, c]
                        has(RS_FR, r, s, ts) || continue
                        add!(e, frac(m, r, t, c, s, ts), flow(m, r, v, t, p, c, ts))
                    end
                end
                sg = sign(plain(g))
                for c in stg_c[r, p], v in vintages[r, t, p], ts in rpcs_s[r, p, c]
                    has(RS_FR, r, s, ts) || continue
                    f = sg * frac(m, r, t, c, s, ts)
                    (r, p, c, OUT) in BS_TOP && add!(e, f * STG_EFF(r, v, p), VAR_SOUT(r, v, t, p, c, ts))
                    (r, p, c, IN) in BS_TOP && add!(e, -f, VAR_SIN(r, v, t, p, c, ts))
                end
                for (c, ie) in get(ire_c, (r, p), ())
                    (r, ELC, c) in NRG_TMAP || continue
                    for v in vintages[r, t, p], ts in flow_s[r, t, p, c]
                        has(RS_FR, r, s, ts) || continue
                        add!(e, sg * (ie == EXP ? -1.0 : 1.0) * frac(m, r, t, c, s, ts), trade(m, r, v, t, p, c, ts, ie))
                    end
                end
            end
            row!(m, :EQ_BS02, (r, t, s, k, one), e, ==, G_YRFR(r, s) * VAR_RLD(r, t, s, k))
        end
    end

    # ---- ABSEQ3 : Stochastic or combined demand with variances
    #  EQ_BS03(RTC(%R_T%,C),RTS(S))$(FINEST(R,S)$BS_LAMBDA(RTC))..
    #  SUM((RTCS_VARC(RTC,TS),TS_MAP(R,TS,S))$BS_OMEGA(RTC,TS),
    #    (BS_LAMBDA(RTC)*VAR_BSD('PRB',RTC,TS))$(BS_OMEGA(RTC,TS)<>2) +
    #    (%VAR%_COMNET(RTC,TS)/G_YRFR(R,TS)-BS_LAMBDA(RTC)*VAR_BSD('DET',RTC,TS)*BS_DETWT(RTC))$(BS_OMEGA(RTC,TS)=2) -
    #    BS_LAMBDA(RTC)*(1-BS_DETWT(RTC)$(BS_OMEGA(RTC,TS)=2))*BS_DELTA(RTC,TS)*3*SUM(BS_RTK(R,T,BS_K),BS_SIGMA(RTC,BS_K,S)*%VAR%_RLD(R,T,S,BS_K)))
    #  =G= 0;
    for ((r, t, c), lam) in BS_LAMBDA
        (t in T && (r, t, c) in RTC) || continue
        for (rr, s) in FINEST
            rr == r || continue
            e = AE()
            for ts in ts_above[r, s]
                ((r, t, c, ts) in RTCS_VARC && has(BS_OMEGA, r, t, c, ts)) || continue
                om = plain(BS_OMEGA(r, t, c, ts))
                om != 2 && add!(e, lam, bsd(PRB, r, t, c, ts))
                if om == 2
                    add!(e, 1 / G_YRFR(r, ts), VAR_COMNET(r, t, c, ts))
                    add!(e, -lam * BS_DETWT(r, t, c), bsd(DET, r, t, c, ts))
                end
                w = lam * (1 - (om == 2 ? BS_DETWT(r, t, c) : 0.0)) * BS_DELTA(r, t, c, ts) * 3
                for k in get0(rtk_k, (r, t))
                    add!(e, -w * BS_SIGMA(r, t, c, k, s), VAR_RLD(r, t, s, k))
                end
            end
            row!(m, :EQ_BS03, (r, t, c, s, one), e, >=, 0.0)
        end
    end

    # ---- ABSEQ4 : Deterministic demand
    #  EQ_BS04(RHS_COMBAL(RTC(%R_T%,C),RTS(S)),P)$(RTP(R,T,P)$GR_GENMAP(R,P,'SI')$BS_OMEGA(RTC,S))..
    #  VAR_BSD('DET',RTC,S)  =G=  BS_RTCS('EXOGEN',RTC,S)*BS_CAPACT(R) + PRC_CAPACT(R,P) *
    #  BS_RTCS('WMAXSI',RTC,S)*SUM(RTP_VINTYR(R,V,T,P),(%TMP%)*SUM(PRC_TS(R,P,TS)$RS_FR(R,TS,S),SUM(BDUPX(BD),COEF_AF%MX%(R,V,T,P,TS,BD))*RS_FR(R,TS,S)));
    si_p = group((r, p) for ((r, p, k), _) in GR_GENMAP if k == SI)
    for (r, t, c, s) in RHS_COMBAL
        (t in T && (r, t, c) in RTC && has(BS_OMEGA, r, t, c, s)) || continue
        for p in get0(si_p, r)
            (r, t, p) in RTP || continue
            rhs = AE()
            add!(rhs, 1.0, BS_RTCS(EXOGEN, r, t, c, s) * BS_CAPACT(r))
            w = PRC_CAPACT(r, p) * BS_RTCS(WMAXSI, r, t, c, s)
            if !iszero(w)
                for v in vintages[r, t, p]
                    af = 0.0
                    for ts in prc_ts[r, p]
                        has(RS_FR, r, ts, s) || continue
                        af += (COEF_AF(r, v, t, p, ts, UP) + COEF_AF(r, v, t, p, ts, FX)) * RS_FR(r, ts, s)
                    end
                    add!(rhs, w * af, bs_cap(m, r, v, t, p))
                end
            end
            row!(m, :EQ_BS04, (r, t, c, s, p, one), 1.0 * bsd(DET, r, t, c, s), >=, rhs)
        end
    end

    # ---- ABSEQ5-6 : Minimum online and offline times (adjusted)
    #  EQ_BS05(RTP_VINTYR(%R_V_T%,P),TSL,BD(L),RTS(S))$(TS_GROUP(R,TSL,S)$BS_UPC(R,P,TSL,L))..
    #  SUM((RS_UP(R,S,JS),RJ_SL(R,JS,SL)),V_U(UPS,R,V,T,P,SL,L)$(RS_MODUS(R,S,JS,SL)<ACT_TIME(R,T,P,L)/8760)) +
    #  SUM(LIM(BDNEQ)$(BDSIG(LIM)*BDSIG(L)<0),VAR_BSUPSR(R,V,T,P,S,LIM)$BS_SBD(R,S,LIM) -
    #    (SUM(RS_UP(R,S,J,TS),V_U(UPS,R,V,T,P,TS,'FX'))$BDUPX(BD)+VAR_OFF(R,V,T,P,S)*BDSIG(BD))$(BS_SBD(R,S,LIM)+YES$ACT_TIME(R,T,P,L)))
    #  =L= 0;
    if !isempty(BS_UPC)
        for (r, v, t, p) in RTP_VINTYR
            t in T || continue
            for (tsl, l) in get(upc, (r, p), Tuple{Id,Id}[])
                (l == LO || l == UP || l == FX) || continue
                window = plain(ACT_TIME(r, t, p, l)) / 8760
                for s in ts_group[r, tsl]
                    e = AE()
                    for (j, up) in cycle_of[r, s], sl in cycle_ts[r, j, up]
                        plain(RS_MODUS(r, s, j, up, sl)) < window && add!(e, 1.0, VAR_UPS(r, v, t, p, sl, l))
                    end
                    for lim in (LO, UP)
                        bdsig(lim) * bdsig(l) < 0 || continue
                        sbd = (r, s, lim) in BS_SBD
                        sbd && add!(e, 1.0, upsr(r, v, t, p, s, lim))
                        if sbd || has(ACT_TIME, r, t, p, l)
                            if l == UP || l == FX
                                for (j, up) in cycle_of[r, s]
                                    add!(e, -1.0, VAR_UPS(r, v, t, p, up, FX))
                                end
                            end
                            add!(e, -bdsig(l), off(r, v, t, p, s))
                        end
                    end
                    row!(m, :EQ_BS05, (r, v, t, p, tsl, l, s, one), e, <=, 0.0)
                end
            end
        end
    end

    # ---- ABSEQ7-8 : Ramping rates (adjusted)
    #  EQ_BS07(RTP_VINTYR(%R_V_T%,P),RTS(S),BDNEQ(BD))$(SUM(TS_ANN(S,TS)$ACT_UPS(R,V,P,TS,BD),1)$PRC_TS(R,P,S)$BS_UPL(R,P,BD))..
    #   SUM(PRC_TS(R,P,TS(S--RS_STG(R,S))),PRC_CAPACT(R,P)*SUM(TS_ANN(S,SL),ACT_UPS(R,V,P,SL,BD)) *
    #     (VAR_BSON(R,V,T,P,S) + ((VAR_OFF(R,V,T,P,S)-VAR_OFF(R,V,T,P,TS) - (VAR_BSUPSR(R,V,T,P,S,BD)$SUM(BS_COMTS(BS_ANEG(R,C),S),1)))$BDLOX(BD))$RPS_UPS(R,P,S)) +
    #     RS_STGPRD(R,S)*2/(G_YRFR(R,S)+G_YRFR(R,TS))/8760 *
    #     (%VAR%_ACT(R,V,T,P,S)/G_YRFR(R,S)-%VAR%_ACT(R,V,T,P,TS)/G_YRFR(R,TS) +
    #      ((VAR_OFF(R,V,T,P,S)-VAR_OFF(R,V,T,P,TS))*PRC_CAPACT(R,P)*ACT_MINLD(R,V,P))$RPS_UPS(R,P,S))*BDSIG(BD) -
    #     PRC_CAPACT(R,P)*SUM(BS_BSC(R,P,C)$BS_ABD(R,C,BD),VAR_BSFSP(R,V,T,P,C,S)$BS_COMTS(R,C,S)))
    #  =G= 0;
    aneg_at(r, s) = any(c -> (r, c) in BS_ANEG, get0(comts_c, (r, s)))
    if !isempty(BS_UPL)
        for (r, v, t, p) in RTP_VINTYR
            t in T || continue
            for bd in (LO, UP)
                (r, p, bd) in BS_UPL || continue
                for s in prc_ts[r, p]
                    any(ts -> has(ACT_UPS, r, v, p, ts, bd), ts_ann[s]) || continue
                    e = AE()
                    ups = (r, p, s) in RPS_UPS
                    for ts in ts_prev[r, s]
                        (r, p, ts) in PRC_TS || continue
                        k = PRC_CAPACT(r, p) * sum(ACT_UPS(r, v, p, sl, bd) for sl in ts_ann[s]; init = 0.0)
                        inner = bs_on(m, r, v, t, p, s)
                        if ups && bd == LO
                            add!(inner, 1.0, off(r, v, t, p, s)); add!(inner, -1.0, off(r, v, t, p, ts))
                            aneg_at(r, s) && add!(inner, -1.0, upsr(r, v, t, p, s, bd))
                        end
                        add!(e, k, inner)
                        dyn = RS_STGPRD(r, s) * 2 / (G_YRFR(r, s) + G_YRFR(r, ts)) / 8760 * bdsig(bd)
                        add!(e, dyn / G_YRFR(r, s), VAR_ACT(r, v, t, p, s))
                        add!(e, -dyn / G_YRFR(r, ts), VAR_ACT(r, v, t, p, ts))
                        if ups
                            w = dyn * PRC_CAPACT(r, p) * ACT_MINLD(r, v, p)
                            add!(e, w, off(r, v, t, p, s)); add!(e, -w, off(r, v, t, p, ts))
                        end
                        for c in get0(bsc_c, (r, p))
                            ((r, c, bd) in BS_ABD && (r, c, s) in BS_COMTS) || continue
                            add!(e, -PRC_CAPACT(r, p), fsp(r, v, t, p, c, s))
                        end
                    end
                    row!(m, :EQ_BS07, (r, v, t, p, s, bd, one), e, >=, 0.0)
                end
            end
        end
    end

    # ---- ABSEQ9 : Capacity margin constraints - positive
    #  EQ_BS09(RTP_VINTYR(%R_V_T%,P),RTS(S),L('UP'))$(BS_PRS(R,P,S)$(NOT RP_DP(R,P))$BS_SUPP(R,P))..
    #  SUM(BS_COMTS(BS_APOS(R,C),S)$BS_BSC(R,P,C),VAR_BSFSP(R,V,T,P,C,S))*PRC_CAPACT(R,P) +
    #  (PRC_CAPACT(R,P)*(COEF_AF%MX%(R,V,T,P,S,L)-ACT_MINLD(R,V,P))*V_U(UPS,R,V,T,P,S,L)*MIN(1,ACT_SDTIME(R,V,P,'HOT',L)/8760/(G_YRFR(R,S)/RS_STGPRD(R,S))))$RPS_UPS(R,P,S)
    #  =L=
    #  PRC_CAPACT(R,P)*COEF_AF%MX%(R,V,T,P,S,L)*VAR_BSON(R,V,T,P,S) -
    #  (%VAR%_ACT(R,V,T,P,S)$RP_STD(R,P)+SUM(TOP(RPC_STG(R,P,C),'OUT'),V_U(SOUT,R,V,T,P,C,S)*STG_EFF(R,V,P))$RP_STG(R,P))/G_YRFR(R,S);
    # ---- ABSEQ10 : Capacity margin constraints - negative
    #  EQ_BS10(RTP_VINTYR(%R_V_T%,P),RTS(S))$(BS_PRS(R,P,S)$BS_NEGP(R,P)$BS_SUPP(R,P))..
    #  SUM(BS_COMTS(BS_ANEG(R,C),S)$BS_BSC(R,P,C),VAR_BSFSP(R,V,T,P,C,S)+VAR_BSFNSP(R,V,T,P,C,S)$RP_STD(R,P))*PRC_CAPACT(R,P)
    #  =L=
    #  (%VAR%_ACT(R,V,T,P,S)$RP_STD(R,P)+SUM(TOP(RPC_STG(R,P,C),'OUT'),V_U(SOUT,R,V,T,P,C,S)*STG_EFF(R,V,P))$RP_STG(R,P))/G_YRFR(R,S) -
    #  PRC_CAPACT(R,P)*ACT_MINLD(R,V,P)*(VAR_BSON(R,V,T,P,S)-SUM(RPS_UPS(R,P,S),VAR_BSUPSR(R,V,T,P,S,'LO')$SUM(BS_COMTS(BS_ANEG(R,C),S),1)));
    for (r, v, t, p) in RTP_VINTYR
        (t in T && (r, p) in BS_SUPP) || continue
        cap = PRC_CAPACT(r, p)
        for s in get0(prs_s, (r, p))
            if !((r, p) in RP_DP)
                lhs = AE()
                for c in get0(comts_c, (r, s))
                    ((r, c) in BS_APOS && (r, p, c) in BS_BSC) && add!(lhs, cap, fsp(r, v, t, p, c, s))
                end
                if (r, p, s) in RPS_UPS
                    k = cap * (COEF_AF(r, v, t, p, s, UP) - ACT_MINLD(r, v, p)) *
                        min(1.0, ACT_SDTIME(r, v, p, HOT, UP) / 8760 / (G_YRFR(r, s) / RS_STGPRD(r, s)))
                    add!(lhs, k, VAR_UPS(r, v, t, p, s, UP))
                end
                rhs = AE()
                add!(rhs, cap * COEF_AF(r, v, t, p, s, UP), bs_on(m, r, v, t, p, s))
                add!(rhs, -1.0, output(r, v, t, p, s))
                row!(m, :EQ_BS09, (r, v, t, p, s, UP, one), lhs, <=, rhs)
            end
            if (r, p) in BS_NEGP
                lhs = AE()
                for c in get0(comts_c, (r, s))
                    ((r, c) in BS_ANEG && (r, p, c) in BS_BSC) || continue
                    add!(lhs, cap, fsp(r, v, t, p, c, s))
                    (r, p) in RP_STD && add!(lhs, cap, fnsp(r, v, t, p, c, s))
                end
                rhs = output(r, v, t, p, s)
                on = bs_on(m, r, v, t, p, s)
                ((r, p, s) in RPS_UPS && aneg_at(r, s)) && add!(on, -1.0, upsr(r, v, t, p, s, LO))
                add!(rhs, -cap * ACT_MINLD(r, v, p), on)
                row!(m, :EQ_BS10, (r, v, t, p, s, one), lhs, <=, rhs)
            end
        end
    end

    # ---- ABSEQ11-17 : Limit reserve by type and sign according to BS_RMAX
    #  EQ_BS11(RTP_VINTYR(%R_W_T%,P),C,RTS(S),BD)$(BS_PRS(R,P,S)$BS_COMTS(R,C,S)$RPC_CONLY(R,V,P,C)$BS_ABD(R,C,BD))..
    #  SUM(BS_ABD(R,COM,BD)$(ABS(BS_RTYPE(R,COM))<=ABS(BS_RTYPE(R,C))),VAR_BSFSP(R,V,T,P,COM,S)$BS_BSC(R,P,COM)$BS_COMTS(R,COM,S))
    #  =L=  (VAR_BSON(R,V,T,P,S)-SUM(RPS_UPS(R,P,S)$BDLOX(BD),VAR_BSUPSR(R,V,T,P,S,BD))) * SUM(TS_ANN(S,TS),BS_RMAX(R,V,P,C,TS));
    rmax_ann(r, v, p, c, s) = sum(BS_RMAX(r, v, p, c, ts) for ts in ts_ann[s]; init = 0.0)
    for (r, v, t, p) in RTP_VINTYR
        (t in T && rvt(r, v, t)) || continue
        cs = get0(conly, (r, v, p))
        isempty(cs) && continue
        for c in cs, bd in get0(abd_of, (r, c)), s in get0(prs_s, (r, p))
            (r, c, s) in BS_COMTS || continue
            lhs = AE()
            for com in get0(abd_c, (r, bd))
                (abs(rtype(r, com)) <= abs(rtype(r, c)) && (r, p, com) in BS_BSC && (r, com, s) in BS_COMTS) || continue
                add!(lhs, 1.0, fsp(r, v, t, p, com, s))
            end
            on = bs_on(m, r, v, t, p, s)
            ((r, p, s) in RPS_UPS && (bd == LO || bd == FX)) && add!(on, -1.0, upsr(r, v, t, p, s, bd))
            row!(m, :EQ_BS11, (r, v, t, p, c, s, bd, one), lhs, <=, rmax_ann(r, v, p, c, s) * on)
        end
    end

    # ---- ABSEQ18,20 : Limit the provision of TRT & RRR reserves according to quick start-up / shut-down capacity
    #  EQ_BS18(RTP_VINTYR(%R_W_T%,P),RTS(S),BDNEQ(BD))$(BS_PRS(R,P,S)$RPS_UPS(R,P,S)$ACT_MINLD(R,V,P)$BS_SUPP(R,P))..
    #  VAR_BSUPSR(R,V,T,P,S,BD)*ACT_MINLD(R,V,P)$BS_SBD(R,S,BD)
    #  =L=  SUM(BS_ABD(R,C,BD)$(ABS(BS_RTYPE(R,C))>2),VAR_BSFNSP(R,V,T,P,C,S)$BS_BSC(R,P,C)$BS_COMTS(R,C,S));
    # ---- ABSEQ19,21
    #  EQ_BS19(RTP_VINTYR(%R_W_T%,P),C,RTS(S),BD)$((ABS(BS_RTYPE(R,C))>2)$BS_PRS(R,P,S)$BS_SUPP(R,P)$BS_BSC(R,P,C)$BS_ABD(R,C,BD))..
    #  SUM(BS_ABD(R,COM,BD)$(MOD(ABS(BS_RTYPE(R,COM))-1,BS_RTYPE(R,C))>1),VAR_BSFNSP(R,V,T,P,COM,S)$BS_BSC(R,P,COM)$BS_COMTS(R,COM,S))
    #  =L=  VAR_BSUPSR(R,V,T,P,S,BD)$RPS_UPS(R,P,S) * SUM(TS_ANN(S,TS),BS_RMAX(R,V,P,C,TS))$BS_COMTS(R,C,S);
    for (r, v, t, p) in RTP_VINTYR
        (t in T && rvt(r, v, t) && (r, p) in BS_SUPP) || continue
        for s in get0(prs_s, (r, p))
            if (r, p, s) in RPS_UPS && has(ACT_MINLD, r, v, p)
                for bd in (LO, UP)
                    lhs = AE()
                    (r, s, bd) in BS_SBD && add!(lhs, ACT_MINLD(r, v, p), upsr(r, v, t, p, s, bd))
                    rhs = AE()
                    for c in get0(abd_c, (r, bd))
                        (abs(rtype(r, c)) > 2 && (r, p, c) in BS_BSC && (r, c, s) in BS_COMTS) || continue
                        add!(rhs, 1.0, fnsp(r, v, t, p, c, s))
                    end
                    row!(m, :EQ_BS18, (r, v, t, p, s, bd, one), lhs, <=, rhs)
                end
            end
        end
        for c in get0(bsc_c, (r, p))
            abs(rtype(r, c)) > 2 || continue
            for bd in get0(abd_of, (r, c)), s in get0(prs_s, (r, p))
                lhs = AE()
                for com in get0(abd_c, (r, bd))
                    (rem(abs(rtype(r, com)) - 1, rtype(r, c)) > 1 && (r, p, com) in BS_BSC && (r, com, s) in BS_COMTS) || continue
                    add!(lhs, 1.0, fnsp(r, v, t, p, com, s))
                end
                rhs = AE()
                ((r, p, s) in RPS_UPS && (r, c, s) in BS_COMTS) && add!(rhs, rmax_ann(r, v, p, c, s), upsr(r, v, t, p, s, bd))
                row!(m, :EQ_BS19, (r, v, t, p, c, s, bd, one), lhs, <=, rhs)
            end
        end
    end

    # ---- ABSEQ22 : Ensure sufficient storage level when contracted to reserve
    #  EQ_BS22(RTP_VINTYR(%R_W_T%,P),RTS(S))$(BS_STGP(R,P)$COEF_AFUPS(R,V,P,S)$RPS_STG(R,P,S))..
    #  SUM(PRC_TS(R,P,TS)$RS_FR(R,TS,S),%VAR%_ACT(R,V,T,P,TS)*RS_FR(R,TS,S)/RS_STGPRD(R,TS))$BS_SBD(R,S,'UP')
    #  =G=
    #  SUM(BS_COMTS(BS_APOS(R,C),S),PRC_CAPACT(R,P)/SQRT(STG_EFF(R,V,P)) / 8760 * VAR_BSFSP(R,V,T,P,C,S)*<stfac>);
    # ---- ABSEQ23 : Limit storage level by capacity and contracted reserve
    #  EQ_BS23(RTP_VINTYR(%R_V_T%,P),RTS(S))$(BS_STGP(R,P)$COEF_AFUPS(R,V,P,S)$RPS_STG(R,P,S))..
    #  SUM(PRC_TS(R,P,TS)$RS_FR(R,TS,S),%VAR%_ACT(R,V,T,P,TS)*RS_FR(R,TS,S)/RS_STGPRD(R,TS))
    #  =L=
    #  ((%TMP%)*COEF_AFUPS(R,V,P,S) / EXP(PRC_SC(R,P)) * PRC_CAPACT(R,P)) -
    #  SUM(BS_COMTS(BS_ANEG(R,C),S),PRC_CAPACT(R,P)*SQRT(STG_EFF(R,V,P)) / 8760 * VAR_BSFSP(R,V,T,P,C,S)*<stfac>);
    for (r, v, t, p) in RTP_VINTYR
        (t in T && (r, p) in BS_STGP) || continue
        cap = PRC_CAPACT(r, p)
        for s in m.ix.rps_stg[r, p]
            has(COEF_AFUPS, r, v, p, s) || continue
            level = AE()
            for ts in prc_ts[r, p]
                has(RS_FR, r, ts, s) || continue
                add!(level, RS_FR(r, ts, s) / RS_STGPRD(r, ts), VAR_ACT(r, v, t, p, ts))
            end
            if rvt(r, v, t)
                rhs = AE()
                for c in get0(comts_c, (r, s))
                    (r, c) in BS_APOS || continue
                    add!(rhs, cap / sqrt(STG_EFF(r, v, p)) / 8760 * stfac(r, p, c, s), fsp(r, v, t, p, c, s))
                end
                row!(m, :EQ_BS22, (r, v, t, p, s, one), (r, s, UP) in BS_SBD ? level : AE(), >=, rhs)
            end
            rhs = AE()
            add!(rhs, COEF_AFUPS(r, v, p, s) / exp(PRC_SC(r, p)) * cap, bs_cap(m, r, v, t, p))
            for c in get0(comts_c, (r, s))
                (r, c) in BS_ANEG || continue
                add!(rhs, -cap * sqrt(STG_EFF(r, v, p)) / 8760 * stfac(r, p, c, s), fsp(r, v, t, p, c, s))
            end
            row!(m, :EQ_BS23, (r, v, t, p, s, one), level, <=, rhs)
        end
    end

    # ---- ABSEQ24 : End-use - negative
    #  EQ_BS24(RTP_VINTYR(%R_W_T%,P),RTS(S))$(BS_PRS(R,P,S)$AFS(R,T,P,S,'UP')$BS_SBD(R,S,'LO')$BS_NEGP(R,P)$BS_ENDP(R,P))..
    #  SUM(BS_COMTS(BS_ANEG(R,C),S)$BS_BSC(R,P,C),VAR_BSFSP(R,V,T,P,C,S))
    #  =L=
    #  (VAR_BSON(R,V,T,P,S)*COEF_AF%MX%(R,V,T,P,S,'UP') - %VAR%_ACT(R,V,T,P,S)/PRC_CAPACT(R,P)/G_YRFR(R,S)) * <BS_EUCAP>;
    # ---- ABSEQ25 : End-use - positive
    #  EQ_BS25(RTP_VINTYR(%R_W_T%,P),RTS(S))$(BS_PRS(R,P,S)$BS_SBD(R,S,'UP')$BS_ENDP(R,P))..
    #  SUM(BS_COMTS(BS_APOS(R,C),S)$BS_BSC(R,P,C),VAR_BSFSP(R,V,T,P,C,S))*PRC_CAPACT(R,P)*G_YRFR(R,S)
    #  =L=
    #  SUM(TOP(R,P,C,'IN')$NRG_TMAP(R,'ELC',C),
    #    SUM(RTPCS_VARF(R,T,P,C,TS)$TS_MAP(R,S,TS),%cal_red%)$RP_STD(R,P)+
    #    SUM(RPCS_VAR(RPC_STG(R,P,C),TS)$TS_MAP(R,S,TS),V_U(SIN,R,V,T,P,C,TS)$(PRC_NSTTS(R,P,TS)+PRC_STGTSS(R,P,C))));
    for (r, v, t, p) in RTP_VINTYR
        (t in T && rvt(r, v, t) && (r, p) in BS_ENDP) || continue
        cap = PRC_CAPACT(r, p)
        for s in get0(prs_s, (r, p))
            if (r, t, p, s, UP) in AFS && (r, s, LO) in BS_SBD && (r, p) in BS_NEGP
                lhs = AE()
                for c in get0(comts_c, (r, s))
                    ((r, c) in BS_ANEG && (r, p, c) in BS_BSC) && add!(lhs, 1.0, fsp(r, v, t, p, c, s))
                end
                k = BS_EUCAP(r, v, t, p, s)
                rhs = AE()
                add!(rhs, k * COEF_AF(r, v, t, p, s, UP), bs_on(m, r, v, t, p, s))
                add!(rhs, -k / cap / G_YRFR(r, s), VAR_ACT(r, v, t, p, s))
                row!(m, :EQ_BS24, (r, v, t, p, s, one), lhs, <=, rhs)
            end
            if (r, s, UP) in BS_SBD
                lhs = AE()
                for c in get0(comts_c, (r, s))
                    ((r, c) in BS_APOS && (r, p, c) in BS_BSC) && add!(lhs, cap * G_YRFR(r, s), fsp(r, v, t, p, c, s))
                end
                rhs = AE()
                for c in top_c[r, p, IN]
                    (r, ELC, c) in NRG_TMAP || continue
                    if (r, p) in RP_STD
                        for ts in flow_s[r, t, p, c]
                            (r, s, ts) in TS_MAP && add!(rhs, 1.0, flow(m, r, v, t, p, c, ts))
                        end
                    end
                    if (r, p, c) in RPC_STG
                        for ts in rpcs_s[r, p, c]
                            ((r, s, ts) in TS_MAP && ((r, p, ts) in PRC_NSTTS || (r, p, c) in PRC_STGTSS)) || continue
                            add!(rhs, 1.0, VAR_SIN(r, v, t, p, c, ts))
                        end
                    end
                end
                row!(m, :EQ_BS25, (r, v, t, p, s, one), lhs, <=, rhs)
            end
        end
    end

    # ---- ABSEQ26 : Bound on process reserve provision
    #  EQ_BS26(RTP(%R_T%,P),C,RTS(S))$(BS_COMTS(R,C,S)$(BS_BSC(R,P,C)+YES$BS_STIME(R,P,C,'UP'))$BS_BNDPRS(RTP,C,S,'N'))..
    #  SUM((RTP_VINTYR(R,V,T,P),BS_PRS(R,P,TS))$RS_FR(R,TS,S),
    #    (VAR_BSFSP(R,V,T,P,C,TS)+VAR_BSFNSP(R,V,T,P,C,TS)$(ABS(BS_RTYPE(R,C))>2)$BS_SUPP(R,P))*RS_FR(R,TS,S))
    #  =E=  VAR_BSLACK(R,T,P,C,S);
    for ((r, t, p, c, s, l), _) in BS_BNDPRS
        (l == N && t in T && (r, t, p) in RTP && (r, c, s) in BS_COMTS && provides(r, p, c)) || continue
        nsp = abs(rtype(r, c)) > 2 && (r, p) in BS_SUPP
        e = AE()
        for v in vintages[r, t, p], ts in get0(prs_s, (r, p))
            has(RS_FR, r, ts, s) || continue
            f = RS_FR(r, ts, s)
            add!(e, f, fsp(r, v, t, p, c, ts))
            nsp && add!(e, f, fnsp(r, v, t, p, c, ts))
        end
        row!(m, :EQ_BS26, (r, t, p, c, s, one), e, ==, 1.0 * VAR_BSPRS(r, t, t, p, c, s, UP))
    end

    # ---- ABSEQ27 : Maintenence 1 - entrance to maintenance
    #  EQ_BS27(RTP_VINTYR(%R_V_T%,P),RTS(S))$((BS_MAINT(R,V,P,S)>=0)$BS_MAINT(R,V,P,S))..
    #  SUM(TS_MAP(R,S,TS)$RPS_UPS(R,P,TS),
    #    (VAR_BSMUP(R,V,T,P,TS)*MIN(1,ROUND(BS_MAINT(R,V,P,S),1)/8760*RS_STGPRD(R,TS)/G_YRFR(R,S)))$PRC_TS(R,P,TS) +
    #    (VAR_OFF(R,V,T,P,TS)*RS_FR(R,TS,S)$(BS_MAINT(R,V,P,S)=0))$TS_CYCLE(R,TS))
    #  =G=
    #  SUM(MODLYEAR(K)$(COEF_VNT(R,T,P,K)$(PRC_VINT(R,P)->DIAG(V,K))),COEF_VNT(R,T,P,K)*(%VARM%_NCAP(R,K,P)$T(K)+NCAP_PASTI(R,K,P)%RCAPSBM%)*
    #    ((1-COEF_AF%MX%(R,K,T,P,S,'UP'))$(ACT_UPS(R,T,P,S,'N')=0)+ACT_UPS(R,T,P,S,'N')));
    # ---- ABSEQ28 : Maintenence 2 - continuous duration
    #  EQ_BS28(RTP_VINTYR(%R_V_T%,P),RTS(S))$(PRC_TS(R,P,S)$BS_MAINT(R,V,P,S))..
    #  SUM((RS_UP(R,S,JS),RJ_SL(R,JS,SL)),VAR_BSMUP(R,V,T,P,SL)$(RS_MODUS(R,S,JS,SL)<ABS(BS_MAINT(R,V,P,S))/8760))
    #  =L=  %TMP%*(1-COEF_AF%MX%(R,V,T,P,S,'UP'))-(%UPSCAPS%*COEF_AF%MX%(R,V,T,P,S,'UP'));
    gams_round1(x) = (x >= 0 ? floor(x * 10 + 0.5) : -floor(-x * 10 + 0.5)) / 10
    vint_t = group(((r, v, p), t) for (r, v, t, p) in RTP_VINTYR)
    for ((r, v, p, s), mt) in BS_MAINT
        for t in get0(vint_t, (r, v, p))
            t in T || continue
            mtp = plain(mt)
            if mtp >= 0
                lhs = AE()
                for ts in ts_below[r, s]
                    (r, p, ts) in RPS_UPS || continue
                    if (r, p, ts) in PRC_TS
                        k = min(1.0, gams_round1(mtp) / 8760 * RS_STGPRD(r, ts) / G_YRFR(r, s))
                        add!(lhs, k, mup(r, v, t, p, ts))
                    end
                    if mtp == 0 && has(BS_TSCYC, r, ts) && !iszero(BS_TSCYC(r, ts))
                        add!(lhs, RS_FR(r, ts, s), off(r, v, t, p, ts))
                    end
                end
                rhs = AE()
                ups_n = ACT_UPS(r, t, p, s, N)
                vint = (r, p) in PRC_VINT
                for k in cpt_v[r, t, p]
                    (vint && k != v) && continue
                    has(COEF_VNT, r, t, p, k) || continue
                    w = (plain(ups_n) == 0 ? 1 - COEF_AF(r, k, t, p, s, UP) : 0.0) + ups_n
                    add!(rhs, COEF_VNT(r, t, p, k) * w, dispatch_standing(m, r, k, t, p))
                end
                row!(m, :EQ_BS27, (r, v, t, p, s, one), lhs, >=, rhs)
            end
            if (r, p, s) in PRC_TS
                lhs = AE()
                for (j, up) in cycle_of[r, s], sl in cycle_ts[r, j, up]
                    plain(RS_MODUS(r, s, j, up, sl)) < abs(mtp) / 8760 && add!(lhs, 1.0, mup(r, v, t, p, sl))
                end
                af = COEF_AF(r, v, t, p, s, UP)
                rhs = AE()
                add!(rhs, 1 - af, bs_cap(m, r, v, t, p))
                add!(rhs, af, offline(m, r, v, t, p, s))
                row!(m, :EQ_BS28, (r, v, t, p, s, one), lhs, <=, rhs)
            end
        end
    end
end
