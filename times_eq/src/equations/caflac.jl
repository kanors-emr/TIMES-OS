# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_CAFLAC / EQE_CAFLAC (r,v,t,p,s)                                         eqcaflac.vda

Use of capacity when the availability is given by commodity (NCAP_AFC): the flows of the primary
group, each divided by its own availability and brought to activity units, are limited by the
capacity available in timeslice s.

    SUM(c in PG,  1 / (|PRC_ACTFLO(r,v,p,c)| * af(c)) * SUM(ts, RS_FR(r,s,ts) * flow of c in ts))
        <=  (SUM(k, COEF_VNT(r,t,p,k) * COEF_AF(r,k,t,p,s,UP) * standing(r,k,t,p)) - COEF_AF(r,v,t,p,s,UP) * offline)
            * PRC_CAPACT(r,p) * G_YRFR(r,s)

offline is the capacity off line (VAR_UPS N above s) of a dispatchable process (RP_UPL FX) on its own
timeslices (PRC_TS), and nothing otherwise (%UPSCAP0%, equ_ext.vda line 75); the same in EQL_CAPFLO.

af(c) is NCAP_AFCS(r,v,p,c,s), or that of the commodity type of c when c has none. The flow is
VAR_FLO for a standard process, VAR_SIN and STG_EFF * VAR_SOUT for a storage, VAR_IRE for trade.
RPG_AFCX marks flows whose own availability replaces that of the type instead of adding to it.

    EQL_CAPFLO (r,v,t,p,cg,s)

A second limit, on the flows of one group alone (NCAP_AFC by group and timeslice):

    SUM(c in cg, SUM(ts, frac(c,s,ts) * flow of c in ts))  <=  NCAP_AFC(r,v,p,cg,s) * capacity * PRC_CAPACT(r,p) * G_YRFR(r,s)

For cg = ACT of a storage the left-hand side is the storage level as in EQ(l)_CAPACT, times G_YRFR(r,s).
"""
function eq_caflac!(m::Model)
    (; RTP_VINTYR, RPS_CAFLAC, RPG_AFCX, RP_STD, RP_STG, RP_FLO, RPC_STG, RP_AIRE, TOP, COM_GMAP, RTPCS_VARF, RS_FR, RTCS_FR, RS_TSLVL,
        PRC_ACTFLO, NCAP_AFCS, NCAP_AFC, STG_EFF, COEF_AF, PRC_CAPACT, G_YRFR, PRC_SC, RS_STGPRD, RP_UPL, PRC_TS) = m.d
    (; afs, pcg, type_of, rpcs_s, rpc_ire, afcx, rpc_c, flow_s, stg_c, prc_ts, ts_frac, ts_frac_in) = m.ix
    (; VAR_FLO, VAR_SIN, VAR_SOUT, VAR_IRE, VAR_ACT) = m.v
    (; IN, OUT, ACT, FX) = m.K
    kind = by_bound(m, "CAFLAC")

    for (r, v, t, p) in RTP_VINTYR, (s, bd) in afs[r, t, p]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        (r, p, s, bd) in RPS_CAFLAC || continue
        std = (r, p) in RP_STD

        flows = AE()
        for c in pcg[r, p], cg in type_of[r, c]
            own, typ = NCAP_AFCS(r, v, p, c, s), NCAP_AFCS(r, v, p, cg, s)
            af = iszero(own) ? (iszero(typ) ? 1.0 : typ) : own
            k = 1 / abs(PRC_ACTFLO[r, v, p, c]) / af
            ratio = iszero(typ) ? 0.0 : own / typ            # own availability relative to that of the type
            for ts in onbranch(rpcs_s[r, p, c], ts_frac[r, s])
                fr = RS_FR(r, s, ts)
                iszero(fr) && continue
                if std
                    add!(flows, k * fr, VAR_FLO(r, v, t, p, c, ts))
                    continue
                end
                if (r, p, c) in RPC_STG && !(iszero(own) && iszero(typ))
                    if (r, p, c, IN) in TOP
                        w = iszero(own) ? 1.0 : ratio^length(afcx[r, p, c])
                        add!(flows, k * fr * w, VAR_SIN(r, v, t, p, c, ts))
                    end
                    (r, p, c, OUT) in TOP &&
                        add!(flows, k * fr * STG_EFF(r, v, p) * (1 + rtcs_fr(m, r, t, c, s, ts)), VAR_SOUT(r, v, t, p, c, ts))
                end
                for ie in rpc_ire[r, p, c]
                    relative = (r, p, c, ie) in RPG_AFCX && (!((r, p, ie) in RP_AIRE) || !(iszero(own) || iszero(typ)))
                    add!(flows, k * fr * (relative ? ratio : 1.0), VAR_IRE(r, v, t, p, c, ts, ie))
                end
            end
        end

        # COEF_AF%4: COEF_AFMX (equ_ext.vda 88-89), stochastic TIMES with S_NCAP_AFS (afmx)
        available = PRC_CAPACT[r, p] * G_YRFR[r, s] * capacity_of(m, r, v, t, p; weight = k -> afmx(m, COEF_AF(r, k, t, p, s, bd), r, t, p, s))
        # + COEF_AF(R,V,T,P,S,BD) * %UPSCAP0%: on a dispatchable process (RP_UPL FX) at its own timeslices, less the
        #   capacity off line (equ_ext.vda line 75, eqcaflac.vda line 32)
        if (r, p, FX) in RP_UPL && (r, p, s) in PRC_TS
            add!(available, -plain(afmx(m, COEF_AF(r, v, t, p, s, bd), r, t, p, s)) * PRC_CAPACT[r, p] * G_YRFR[r, s], offline(m, r, v, t, p, s))
        end
        name, sense = kind(bd)
        row!(m, name, (r, v, t, p, s), flows, sense, available)
    end

    for ((r, v, p, cg, s), af) in NCAP_AFC, t in m.T
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        ((r, v, t, p) in RTP_VINTYR && has(RS_TSLVL, r, s)) || continue

        flows = AE()
        if (r, p) in RP_FLO
            for c in rpc_c[r, p], ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s])
                ((r, cg, c) in COM_GMAP && has(RS_FR, r, s, ts)) || continue
                add!(flows, frac(m, r, t, c, s, ts), flow(m, r, v, t, p, c, ts))
            end
        end
        if (r, p) in RP_STG
            if cg == ACT
                for ts in onbranch(prc_ts[r, p], ts_frac_in[r, s])
                    has(RS_FR, r, ts, s) || continue
                    add!(flows, RS_FR(r, ts, s) * exp(PRC_SC(r, p)) / RS_STGPRD[r, ts] * G_YRFR[r, s], VAR_ACT(r, v, t, p, ts))
                end
            end
            for c in stg_c[r, p], ts in onbranch(rpcs_s[r, p, c], ts_frac[r, s])
                ((r, cg, c) in COM_GMAP && has(RS_FR, r, s, ts)) || continue
                fr = frac(m, r, t, c, s, ts)
                out = (r, p, c, OUT) in TOP
                ((r, p, c, IN) in TOP && !out) && add!(flows, fr, VAR_SIN(r, v, t, p, c, ts))
                out && add!(flows, fr * STG_EFF(r, v, p), VAR_SOUT(r, v, t, p, c, ts))
            end
        end

        available = af * PRC_CAPACT[r, p] * G_YRFR[r, s] * capacity_of(m, r, v, t, p)
        # + %UPSCAP0% * NCAP_AFC (eqcaflac.vda line 57)
        if (r, p, FX) in RP_UPL && (r, p, s) in PRC_TS
            add!(available, -plain(af) * PRC_CAPACT[r, p] * G_YRFR[r, s], offline(m, r, v, t, p, s))
        end
        row!(m, :EQL_CAPFLO, (r, v, t, p, cg, s), flows, <=, available)
    end
end
