# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_FLOBND / EQE_FLOBND / EQG_FLOBND (r,t,p,cg,s)                           eqflobnd.mod

Bound on the flows of commodity (group) cg of a process in timeslice s, all vintages together.

    SUM((c in cg, v, ts at or below s), flow(r,v,t,p,c,ts))  <=  FLO_BND(r,t,p,cg,s,UP)

A row is needed only when the bound does not apply to a single variable: flows lie below s, or
the preprocessor has flagged the bound (an entry under year 0: vintaged process, trade, group).
For a trade process the bound is on imports plus exports of a commodity, and on net imports of a group.
"""
function eq_flobnd!(m::Model)
    (; FLO_BND, RTP_VARA, RP_FLO, RP_IRE, COM, COM_GMAP, TS_MAP, RS_BELOW) = m.d
    (; flow_cs, vintages, rpc_ire, ts_below) = m.ix
    (; VAR_IRE) = m.v
    (; UP, EXP) = m.K
    kind = by_bound(m, "FLOBND")
    y0 = year0(m)

    for ((r, t, p, cg, s, bd), bound) in FLO_BND
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (r, t, p) in RTP_VARA || continue
        (bd == UP && bound == Inf) && continue
        flagged = has(FLO_BND, r, y0, p, cg, s, bd)
        net = !(cg in COM)

        needed = false
        flows = AE()
        for (c, ts) in onbranch(flow_cs[r, t, p], ts_below[r, s], 2)
            ((r, s, ts) in TS_MAP && (r, cg, c) in COM_GMAP) || continue
            needed |= flagged || (r, s, ts) in RS_BELOW
            for v in vintages[r, t, p]
                (r, p) in RP_FLO && add!(flows, 1.0, flow(m, r, v, t, p, c, ts))
                if (r, p) in RP_IRE
                    for ie in rpc_ire[r, p, c]
                        add!(flows, (net && ie == EXP) ? -1.0 : 1.0, trade(m, r, v, t, p, c, ts, ie))     # (RPC_AIRE: REDUCE YES)
                    end
                end
            end
        end
        needed || continue

        name, sense = kind(bd)
        row!(m, name, (r, t, p, cg, s), flows, sense, bound)
    end
end
