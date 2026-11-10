# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_PEAK(r,t,cg,s)                                                           eqpeak.mod

Peak reserve: in the peak timeslice s of commodity (group) cg, the capacity that can be counted
on, with the reserve margin taken off, covers consumption.

    SUM(c in cg,  COM_IE / (1 + COM_PKRSV) *
            ( SUM((p,v), NCAP_PKCNT * COEF_CPT * PRC_CAPACT * G_YRFR * PRC_ACTFLO * standing(r,v,t,p))
              + (imports + auxiliary trade outputs of c (IRE_FLOSUM OUT)) * NCAP_PKCNT  -  grid_io (flows to grid nodes)
              + output flows and storage discharge of the processes that contribute by production (RPC_PKF) ) )
    >=
    SUM(c in cg,  (1 + COM_PKFLX) * ( (flows(IN) + trades(EXP) + auxiliary trade inputs of c) * FLO_PKCOI + capacity_flows(IN)
                                      + storage charge (RPC_PKF) + COM_PROJ * COM_FR ) )

Every term is brought from the timeslice of the commodity to the peak timeslice with RS_FR.
"""
function eq_peak!(m::Model)
    (; COM_PKTS, RTC, COM, DEM, RS_FR, COM_PKRSV, COM_IE, G_YRFR, PRC_CAPACT, COEF_CPT, PRC_ACTFLO,
        NCAP_PKCNT, RPC_PKF, FLO_PKCOI, COM_PKFLX, COM_PROJ, COM_FR, PRC_PKNO) = m.d
    (; group_c, com_ts, pkc_p, cpt_v) = m.ix
    (; IN, OUT, IMP, EXP) = m.K
    grids = !isempty(m.d.GR_DEMMAP)

    for (r, cg, sl) in COM_PKTS, t in m.T
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        any((r, t, c) in RTC for c in group_c[r, cg]) || continue

        firm, load = AE(), AE()
        for c in group_c[r, cg], s in com_ts[r, c]
            fr = RS_FR(r, sl, s)
            iszero(fr) && continue
            reserve = max(cg in COM ? COM_PKRSV(r, t, cg) : 0.0, COM_PKRSV(r, t, c))
            credit = fr * COM_IE(r, t, c, s) / (1 + reserve)

            capacity = JuMP.@expression(m.jump, sum(
                G_YRFR[r, s] * PRC_CAPACT[r, p] * COEF_CPT(r, v, t, p) * PRC_ACTFLO(r, v, p, c) * NCAP_PKCNT(r, v, p, s) *
                standing(m, r, v, t, p) for p in pkc_p[r, c] for v in cpt_v[r, t, p]))
            imports = trades(m, r, t, c, s, IMP; weight = (p, v, ts) -> NCAP_PKCNT(r, v, p, s))
            production = flows(m, r, t, c, s, OUT;
                weight = (p, v, ts) -> NCAP_PKCNT(r, v, p, s)^RPC_PKF(r, p, c), only = p -> has(RPC_PKF, r, p, c))
            add!(firm, credit, capacity)
            add!(firm, credit, imports)
            # flows between c and its grid nodes (powerflo.vda IREAUX through cal_ire.mod IMP OUT .. '-': the label
            # IREAUXOUT-, the terms with a minus sign on the supply side)
            grids && add!(firm, -credit, grid_io(m, r, t, c, s))
            # auxiliary flows of c released by trade of any commodity, imports and exports (cal_ire.mod AUXONLY, IE = IE)
            add!(firm, credit, trade_aux(m, r, t, c, s, OUT; weight = (p, v, ts) -> NCAP_PKCNT(r, v, p, s)))
            # trade processes flagged PRC_PKNO count by their net imports: their exports are taken off
            if !isempty(PRC_PKNO) && plain(COM_IE(r, t, c, s)) > 0
                add!(firm, credit, trades(m, r, t, c, s, EXP; weight = (p, v, ts) -> -NCAP_PKCNT(r, v, p, s) / COM_IE(r, t, c, s),
                    only = p -> (r, p) in PRC_PKNO))
                add!(firm, credit, trade_aux(m, r, t, c, s, IN; weight = (p, v, ts) -> -NCAP_PKCNT(r, v, p, s) / COM_IE(r, t, c, s),
                    only = p -> (r, p) in PRC_PKNO))
            end
            by_production(p, v, ts) = NCAP_PKCNT(r, v, p, s)^RPC_PKF(r, p, c)
            listed(p) = has(RPC_PKF, r, p, c)
            add!(firm, credit, production)
            add!(firm, credit, storage(m, r, t, c, s, OUT; weight = by_production, only = listed))

            flex = fr * (1 + max(cg in COM ? COM_PKFLX(r, t, cg, sl) : 0.0, COM_PKFLX(r, t, c, s)))
            coincident(p, v, ts) = FLO_PKCOI(r, t, p, c, ts)
            add!(load, flex, flows(m, r, t, c, s, IN; weight = coincident))
            add!(load, flex, trades(m, r, t, c, s, EXP; weight = coincident))
            add!(load, flex, trade_aux(m, r, t, c, s, IN; weight = coincident))
            add!(load, flex, capacity_flows(m, r, t, c, s, IN; only = p -> !((r, p) in PRC_PKNO)))
            add!(load, flex, storage(m, r, t, c, s, IN; weight = by_production, only = listed))
            # (COM_PROJ(R,T,C)$(NOT RD_NLP(R,C)) + VAR_DEM(R,T,C)$RD_NLP(R,C)) * COM_FR(R,T,C,S)   (TIMES-MACRO: RD_NLP)
            if (r, c) in DEM
                iszero(m.d.RD_NLP(r, c)) ? add!(load, flex, sow_com_proj(m, r, t, c) * com_frmx(m, r, t, c, s)) :
                                           add!(load, flex * com_frmx(m, r, t, c, s), m.v.VAR_DEM(r, t, c))
            end
        end

        row!(m, :EQ_PEAK, (r, t, cg, sl), firm, >=, load)
    end
end
