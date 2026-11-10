# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQG_FLOMRK / EQE_FLOMRK / EQL_FLOMRK (r,t,item,com,s)                       eqflomrk.mod

Market share: the contribution of a group of processes (item) to the production of commodity
(group) com, over timeslice s.

    SUM(p in item, contribution(p) / PRC_MARK(r,t,p,item,com,LO))  >=  SUM(c in com, VAR_COMPRD(r,t,c,sl))

`<=` for an upper and `=` for a fixed share. The contribution of p is its flows of c in com,
after commodity losses for an output; for a trade process its imports (share >= 0) less its
exports (share <= 0), each times 1 + IRE_FLOSUM of its own commodity; for a storage its discharge less its charge in the same way.
When the share is given for a single process (FLO_MARK; RX_MARK under year 0), the row reads

    contribution(p)  >=  PRC_MARK(r,t,p,p,com,LO) * SUM(c in com, VAR_COMPRD(r,t,c,sl))
"""
function eq_flomrk!(m::Model)
    (; RTX_MARK, PRC_MARK, RHS_COMPRD, RP_STD, RP_IRE, RPC_STG, RPC_IRE, PRC_MAP, TOP, RS_FR, COM_IE, STG_EFF, IRE_FLOSUM) = m.d
    (; group_c, rpc_p, comprd_s, flow_s, rpcs_s, vintages, rx_mark, ts_frac) = m.ix
    (; VAR_COMPRD, VAR_IRE, VAR_SIN, VAR_SOUT) = m.v
    (; IN, OUT, IMP, EXP, STG) = m.K
    kind = by_bound(m, "FLOMRK")
    y0 = year0(m)

    for (r, t, item, com, bd, s) in RTX_MARK
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        flags = rx_mark[r, item, com, bd]
        single = y0 in flags
        # share of the item itself; a flag under another year than 0 makes the right-hand side vanish
        own = isempty(flags) ? 1.0 : single ? PRC_MARK(r, t, item, item, com, bd) : 0.0

        contribution, production = AE(), AE()
        for c in group_c[r, com], sl in onbranch(comprd_s[r, t, c], ts_frac[r, s])
            has(RS_FR, r, s, sl) || continue
            add!(production, own, VAR_COMPRD(r, t, c, sl))
            ie_c = COM_IE(r, t, c, sl)
            for p in rpc_p[r, c]
                has(PRC_MARK, r, t, p, item, com, bd) || continue
                share = plain(PRC_MARK(r, t, p, item, com, bd))
                k = single ? 1.0 : 1 / share
                if (r, p) in RP_STD
                    loss = (r, p, c, OUT) in TOP ? ie_c : 1.0
                    for ts in onbranch(flow_s[r, t, p, c], ts_frac[r, sl]), v in vintages[r, t, p]
                        has(RS_FR, r, sl, ts) && add!(contribution, k * loss * frac(m, r, t, c, sl, ts), flow(m, r, v, t, p, c, ts))
                    end
                end
                if (r, p) in RP_IRE
                    # an auxiliary flow of the traded commodity itself counts with the trade: 1 + IRE_FLOSUM, taken at the
                    # timeslice s of the row, not of the flow (eqflomrk.mod)
                    aux_imp = 1 + IRE_FLOSUM(r, t, p, c, s, IMP, c, OUT)
                    aux_exp = 1 + IRE_FLOSUM(r, t, p, c, s, EXP, c, IN)
                    for ts in onbranch(flow_s[r, t, p, c], ts_frac[r, sl]), v in vintages[r, t, p]
                        has(RS_FR, r, sl, ts) || continue
                        fr = frac(m, r, t, c, sl, ts)
                        (share >= 0 && (r, p, c, IMP) in RPC_IRE) && add!(contribution, k * fr * aux_imp * ie_c, trade(m, r, v, t, p, c, ts, IMP))
                        (share <= 0 && (r, p, c, EXP) in RPC_IRE) && add!(contribution, -k * fr * aux_exp, trade(m, r, v, t, p, c, ts, EXP))
                    end
                end
                if (r, STG, p) in PRC_MAP && (r, p, c) in RPC_STG
                    for ts in onbranch(rpcs_s[r, p, c], ts_frac[r, sl]), v in vintages[r, t, p]
                        has(RS_FR, r, sl, ts) || continue
                        fr = frac(m, r, t, c, sl, ts)
                        share >= 0 && add!(contribution, k * fr * STG_EFF(r, v, p) * ie_c, VAR_SOUT(r, v, t, p, c, ts))
                        share <= 0 && add!(contribution, -k * fr, VAR_SIN(r, v, t, p, c, ts))
                    end
                end
            end
        end

        name, sense = kind(bd)
        row!(m, name, (r, t, item, com, s), contribution, sense, production)
    end
end
