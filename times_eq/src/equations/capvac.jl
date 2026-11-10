# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQE_CAPVAC / EQL_CAPVAC / EQG_CAPVAC (r,v,t,p,s,'1')                             eqcapvac.mod

Use of capacity of a process with simulated vintages (PRC_SIMV), in place of EQ_CAPACT (its AFS moved to AFSV by
coef_csv.mod): the activity of simulated vintage v in timeslice s, or with availability by commodity (RPS_CAFLAC) the
flows of its primary group each divided by its availability, against the capacity of the real vintages k that make up
v (COEF_CSV):

    SUM(ts below s, VAR_ACT(r,v,t,p,ts))                                               [not RPS_CAFLAC(r,p,s,bd)]
  + SUM(c in PG, cg the type of c, 1/PRC_ACTFLO(r,v,p,c) / af(c) * SUM(ts below s, VAR_FLO / VAR_IRE))   [RPS_CAFLAC]
        =E= / =L= / =G=
    SUM(k with COEF_CSV(r,k,t,p,v), COEF_CSV * COEF_AF(r,k,t,p,s,bd) * VAR_NCAP(r,k,p) [k a period] + NCAP_PASTI(r,k,p))
        * PRC_CAPACT(r,p) * G_YRFR(r,s)

af(c) is NCAP_AFCS(r,v,p,c,s), or that of the type cg when c has none (PROD(XPT\$NCAP_AFCS(cg,s),..): 1 when neither).
NCAP_PASTI stands outside the product with COEF_CSV and COEF_AF in eqcapvac.mod: a past vintage counts in full, as there.
"""
function eq_capvac!(m::Model)
    (; AFSV, COEF_CSV, RPS_CAFLAC, RP_STD, COEF_AF, NCAP_PASTI, PRC_CAPACT, G_YRFR, PRC_ACTFLO, NCAP_AFCS, TS_MAP) = m.d
    (; vintages, prc_ts, rpcs_s, pcg, type_of, rpc_ire) = m.ix
    (; VAR_ACT, VAR_FLO, VAR_IRE, VAR_NCAP) = m.v
    (; FX, UP, LO) = m.K
    isempty(AFSV) && return
    one = id!(m.L, "1")                     # the state of the world of the declaration EQx_CAPVAC(R,ALLYEAR,T,P,S,ALLSOW)
    csv = Dict{NTuple{4,Id},Vector{Tuple{Id,Float64}}}()          # (r, t, p, v) -> [(k, share)]
    for ((r, k, t, p, v), x) in COEF_CSV
        push!(get!(csv, (r, t, p, v), Tuple{Id,Float64}[]), (k, x))
    end
    for (bd, name, sense) in ((FX, :EQE_CAPVAC, ==), (UP, :EQL_CAPVAC, <=), (LO, :EQG_CAPVAC, >=))
        for (r, t, p, s, b) in AFSV
            b == bd || continue
            (m.stepped && !(t in m.sub)) && continue
            for v in vintages[r, t, p]
                lhs = AE()
                if !((r, p, s, bd) in RPS_CAFLAC)
                    for ts in prc_ts[r, p]
                        (r, s, ts) in TS_MAP && add!(lhs, 1.0, VAR_ACT(r, v, t, p, ts))
                    end
                else
                    for c in pcg[r, p], cg in type_of[r, c]
                        own = NCAP_AFCS(r, v, p, c, s)
                        af = has(NCAP_AFCS, r, v, p, c, s) ? own : (has(NCAP_AFCS, r, v, p, cg, s) ? NCAP_AFCS(r, v, p, cg, s) : 1.0)
                        k = 1 / PRC_ACTFLO(r, v, p, c) / af
                        for ts in rpcs_s[r, p, c]
                            (r, s, ts) in TS_MAP || continue
                            (r, p) in RP_STD && add!(lhs, k, VAR_FLO(r, v, t, p, c, ts))
                            for ie in rpc_ire[r, p, c]
                                add!(lhs, k, VAR_IRE(r, v, t, p, c, ts, ie))
                            end
                        end
                    end
                end
                cap = AE()
                for (kk, x) in get(csv, (r, t, p, v), Tuple{Id,Float64}[])
                    new_capacity(m, kk) && add!(cap, x * COEF_AF(r, kk, t, p, s, bd), VAR_NCAP(r, kk, p))
                    add!(cap, 1.0, NCAP_PASTI(r, kk, p))
                end
                row!(m, name, (r, v, t, p, s, one), lhs, sense, PRC_CAPACT(r, p) * G_YRFR(r, s) * cap)
            end
        end
    end
end
