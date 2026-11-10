# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_FLOFR / EQE_FLOFR / EQG_FLOFR (r,t,p,c,s,l)                              eqflofr.mod

Flow of commodity c of process p in timeslice s as a fraction of a larger flow (FLO_FR).
eqmain.mod lines 118-120 write l = LO as =L=, l in LNX (N, FX) as =E=, l = UP as =G=:

    |FLO_FR(s,l)| * [ VAR_FLO(s)                                   if l in IPS (IN, N)
                    + base(s)                                      if l in BD  ]
        =l=  SUM(ts at or below s, not ANNUAL, flow(ts))           unless FLO_FR(s,l) < 0 and l not in BD

base(s) uses the parent sl of s. When FLO_FR(sl,N) exists it is the aggregated flow variable of sl, or of
ANNUAL (TS_ANN(sl,ts)), whichever has a positive N. Otherwise it is the sum of the flows over every flow
timeslice when FLO_FR(s,l) > 0, and over those that share with sl (RS_FR(sl,ts) <> 0) when it is not.

The aggregated variables (VAR_FLO at a timeslice without flow variables) are tied to the flows by the
l = N rows, which pp_prelv.vda lines 102 and 109 prepare: |N| * VAR_FLO(s) = SUM(flows below s).
"""
function eq_flofr!(m::Model)
    (; FLO_FR, RTPC, RP_FLO, TS_MAP, RPCS_VAR, RS_FR) = m.d
    (; vintages, flow_s, parent, rpcs_s, ts_below, ts_frac) = m.ix
    (; VAR_FLO) = m.v
    (; ANNUAL, LO, UP, FX, N) = m.K
    IN = m.K.IN

    for ((r, t, p, c, s, l), fr) in FLO_FR
        t in m.sub || continue
        (r, t, p, c) in RTPC || continue
        name, sense = l == LO ? (:EQL_FLOFR, LE) : (l == N || l == FX) ? (:EQE_FLOFR, EQ) :
                      l == UP ? (:EQG_FLOFR, GE) : continue
        # $(SUM(RPCS_VAR(RP_FLO(R,P),C,TS)$TS_MAP(R,S,TS),1)$FLO_FR(R,T,P,C,S,L))
        (r, p) in RP_FLO || continue
        any(ts -> (r, p, c, ts) in RPCS_VAR && (r, s, ts) in TS_MAP, onbranch(rpcs_s[r, p, c], ts_below[r, s])) || continue
        bd = l == LO || l == UP || l == FX
        ips = l == IN || l == N
        a = abs(fr)
        pos = plain(fr) > 0

        lhs = AE()
        for v in vintages[r, t, p]
            ips && add!(lhs, a, VAR_FLO(r, v, t, p, c, s))
            bd || continue
            for sl in parent[r, s]
                if has(FLO_FR, r, t, p, c, sl, N)
                    # SUM(TS_ANN(SL,TS), VAR_FLO(TS) * (FLO_FR(TS,'N') > 0))
                    for ts in unique((sl, ANNUAL))
                        plain(FLO_FR(r, t, p, c, ts, N)) > 0 && add!(lhs, a, VAR_FLO(r, v, t, p, c, ts))
                    end
                else
                    # SUM(RTPCS_VARF(RTPC,TS)$(FLO_FR(RTPC,S,L) > -INF$RS_FR(R,SL,TS)), flow(TS))
                    for ts in (pos ? flow_s[r, t, p, c] : onbranch(flow_s[r, t, p, c], ts_frac[r, sl]))
                        (pos || !iszero(RS_FR(r, sl, ts))) && add!(lhs, a, flow(m, r, v, t, p, c, ts))
                    end
                end
            end
        end

        # $(MIN(0,FLO_FR(RTPC,S,L)) -> BD(L)): an EPS counts as a value here
        rhs = AE()
        if bd || !(plain(fr) < 0 || iseps(fr))
            for v in vintages[r, t, p], ts in onbranch(flow_s[r, t, p, c], ts_below[r, s])
                (ts != ANNUAL && (r, s, ts) in TS_MAP) && add!(rhs, 1.0, flow(m, r, v, t, p, c, ts))
            end
        end
        row!(m, name, (r, t, p, c, s, l), lhs, sense, rhs)
    end
end
