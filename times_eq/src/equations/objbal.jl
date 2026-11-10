# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_OBJBAL(r,cur,'1')                                                         powerflo.vda OBJBAL

Costs on the components of a commodity's balance (COM_CSTBAL; the preprocessor's OBJ_COMBAL by item), the objective
component VAR_OBJ(r,'OBJBAL',cur). Each cost is weighted over the periods by OBJ_LINT (the %TPULSE% of the file):

    VAR_OBJ(r,OBJBAL,cur) =
        SUM(RHS_COMPRD(r,t,c,s), VAR_COMPRD * pulse(PRD))                                    production
      + SUM(grid node c, s with GEN: (SUM(GR_ALGMAP(r,cg,com), GR_ALLMAP(r,c,com)), VAR_GRIDIO(com,c,s,OUT)
                                       + VAR_GRIDIO(com,c,s,IN) where GR_ALGMAP(r,com,com))
                                     + SUM(GR_PRCMAP(p std,com,item), GR_ENDC(r,grid,com)), GR_GENMAP * GR_GENFR(c,item)
                                       * SUM(v, ts, flow(v,t,p,com,ts) * RS_FR(s,ts))) * pulse(GEN))   generation
      + SUM(grid node c, s with NTX: SUM(GR_DEMMAP(r,c,com), VAR_GRIDIO(com,c,s,IN) where GR_ALGMAP(r,NRG,com)
                                       - VAR_GRIDIO(com,c,s,OUT)) * pulse(NTX))                 net imports
      + SUM(grid node c, s with NPG: VAR_GRIDIO(c,c,s,OUT) * pulse(MAX(0,NPG)))              net positive generation
      + SUM(RTPCS_VARF(r,t,p,c,s), RPC_IRE(r,p,c,ie) with ie: SUM(v, trade) * pulse(ie))     imports / exports

    pulse(item) = SUM(tt, OBJ_LINT(r,t,tt,cur) * OBJ_COMBAL(r,tt,c,s,item,cur))
"""
function eq_objbal!(m::Model)
    (; OBJ_COMBAL, RDCUR, RHS_COMPRD, RTCS_VARC, RC_GRID, GR_ALGMAP, GR_ALLMAP, GR_PRCMAP, GR_ENDC, GR_GENMAP, GR_GENFR,
       GR_DEMMAP, RP_STD, RTPCS_VARF, RPC_IRE, RS_FR, OBJ_LINT) = m.d
    (; lint, vintages) = m.ix
    (; VAR_OBJ, VAR_COMPRD, VAR_GRIDIO) = m.v
    (; IN, OUT, NRG, IMP, EXP) = m.K
    isempty(OBJ_COMBAL) && return
    PRD, GEN, NTX, NPG, OBJBAL = (id!(m.L, x) for x in ("PRD", "GEN", "NTX", "NPG", "OBJBAL"))
    one = id!(m.L, "1")
    rcg = Set((r, t, c) for (r, t, c) in RC_GRID)
    for (r, cur) in RDCUR
        pulse(t, c, s, item; pos = false) = sum(OBJ_LINT[r, t, tt, cur] * (pos ? max(0.0, OBJ_COMBAL(r, tt, c, s, item, cur)) :
                                                                      OBJ_COMBAL(r, tt, c, s, item, cur))
                                                for tt in lint[r, t, cur]; init = 0.0)
        e = AE()
        # production of a commodity
        for (r2, t, c, s) in RHS_COMPRD
            r2 == r || continue
            add!(e, pulse(t, c, s, PRD), VAR_COMPRD(r, t, c, s))
        end
        for (r2, t, c, s) in RTCS_VARC
            (r2 == r && (r, t, c) in rcg) || continue
            # generation to a grid node
            if has(OBJ_COMBAL, r, t, c, s, GEN, cur)
                g = AE()
                for (r3, cg, com) in GR_ALGMAP
                    (r3 == r && (r, c, com) in GR_ALLMAP) || continue
                    add!(g, 1.0, VAR_GRIDIO(r, t, com, c, s, OUT))
                    (r, com, com) in GR_ALGMAP && add!(g, 1.0, VAR_GRIDIO(r, t, com, c, s, IN))
                end
                for (p, com, item) in m.ix.gr_prcmap[r]
                    (r, p) in RP_STD || continue
                    w = GR_GENMAP(r, p, item) * GR_GENFR(r, t, c, item)
                    for (r3, grid, cg) in GR_ENDC
                        (r3 == r && cg == com) || continue
                        for v in vintages[r, t, p], ts in m.ix.flow_s[r, t, p, com]
                            has(RS_FR, r, s, ts) || continue
                            add!(g, w * RS_FR(r, s, ts), flow(m, r, v, t, p, com, ts))
                        end
                    end
                end
                add!(e, pulse(t, c, s, GEN), g)
            end
            # net imports to a grid node
            if has(OBJ_COMBAL, r, t, c, s, NTX, cur)
                g = AE()
                for (r3, c3, com) in GR_DEMMAP
                    (r3 == r && c3 == c) || continue
                    (r, NRG, com) in GR_ALGMAP && add!(g, 1.0, VAR_GRIDIO(r, t, com, c, s, IN))
                    add!(g, -1.0, VAR_GRIDIO(r, t, com, c, s, OUT))
                end
                add!(e, pulse(t, c, s, NTX), g)
            end
            # net positive generation (the balancer)
            if has(OBJ_COMBAL, r, t, c, s, NPG, cur)
                add!(e, pulse(t, c, s, NPG; pos = true), VAR_GRIDIO(r, t, c, c, s, OUT))
            end
        end
        # imports / exports
        for (r2, t, p, c, s) in RTPCS_VARF
            r2 == r || continue
            for ie in m.ix.rpc_ire[r, p, c]
                has(OBJ_COMBAL, r, t, c, s, ie, cur) || continue
                k = pulse(t, c, s, ie)
                for v in vintages[r, t, p]
                    add!(e, k, trade(m, r, v, t, p, c, s, ie))
                end
            end
        end
        row!(m, :EQ_OBJBAL, (r, cur, one), VAR_OBJ(r, OBJBAL, cur), ==, e)
    end
end
