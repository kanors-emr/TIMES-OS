# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_OBJ, EQ_OBJANN(obv,r,cur), EQ_ANNINV / EQ_ANNFIX / EQ_ANNVAR (r,t,cur)    eqobjann.tm, eqobjcst.tm, eqobjvar.mod

Objective in annualised form (OBJANN): total discounted cost, built from the annual cost of each
period t for investment, fixed and variable costs.

    OBJZ                     =  SUM((r,obv,cur), VAR_OBJ(r,obv,cur))
    VAR_OBJ(r,obv,cur)       =  SUM(t, OBJ_PVT(r,t,cur) * VAR_ANNCST(obv,r,t,cur))

    VAR_ANNCST(OBJINV,r,t,cur)  =  SUM((v,p), COEF_CPT(r,v,t,p) * COEF_OBINV(r,v,p,cur) * installed(r,v,p))
    VAR_ANNCST(OBJFIX,r,t,cur)  =  SUM((v,p), COEF_CPT(r,v,t,p) * COEF_OBFIX(r,v,p,cur) * installed(r,v,p))
    VAR_ANNCST(OBJVAR,r,t,cur)  =  SUM((p,v,s), activity cost * VAR_ACT) + SUM(trade, price * trade)
                                   + SUM(flows, flow cost * flow)

OBJ_PVT is the present value of one unit of cost in every year of period t. COEF_OBINV is the
annuity of the investment cost and COEF_OBFIX the fixed cost per unit of capacity, both prepared
by the preprocessor. Unit costs of the period are the yearly costs weighted with OBJ_LINT.
The activity of a storage is costed for its average residence time (RS_STGAV); a cost on a
storage flow is FLO_COST on what is charged and FLO_DELIV on what is delivered. A flow tax less
subsidy (OB_FTAX, from FLO_TAX and FLO_SUB) is added to the flow cost of ordinary and trade flows;
GAMS does not apply it to storage flows.
A cost, tax or subsidy on the net or gross production of a commodity (OBJ_COMNT, OBJ_COMPD, from
COM_CSTNET / COM_TAXNET / COM_SUBNET and the ...PRD ones) is charged on VAR_COMNET / VAR_COMPRD.

With early retirement (prepret.dsc), retired capacity is credited with the fixed cost it no
longer incurs (COEF_OBFIXR, per unit of VAR_SCAP), and VAR_OBJ(OBJINV) carries the salvage term

    SUM((v,p), OBJSCC(r,v,p,cur) * OBJ_DCEOH(r,cur) * (installed(r,v,p) - VAR_SCAP(r,v,0,p)))


    EQ_OBJ, EQ_OBJINV / EQ_OBJFIX / EQ_OBJVAR / EQ_OBJSALV (r,cur)               eqobj.mod, eqobjinv.mod, eqobjfix.mod, eqobjvar.mod, eqobsalv.mod

The standard form (a run without OBJANN): one row per cost component, region and currency.

    OBJZ                     =  SUM((r,cur), VAR_OBJ(r,OBJINV,cur) + VAR_OBJ(r,OBJFIX,cur) + VAR_OBJ(r,OBJVAR,cur) - VAR_OBJ(r,OBJSAL,cur))

    VAR_OBJ(r,OBJINV,cur)  =  SUM((t,p), OBJ_CINV(r,t,p,cur) * VAR_NCAP(r,t,p)) + SUM((v past,p), OBJ_CINV * OBJ_PASTI(r,v,p,cur)) + OBJ_IAD(r,cur)
                              + SUM((v,p), OBJ_CDEC(r,v,p,cur) * (VAR_NCAP(r,v,p) [v milestone] + OBJ_PASTI(r,v,p,cur) [v past]))   decommissioning
    VAR_OBJ(r,OBJFIX,cur)  =  SUM((v,p), OBJ_CFIX(r,v,p,cur) * installed(r,v,p)) - the credit for retired capacity
    VAR_OBJ(r,OBJVAR,cur)  =  SUM(t, the variable costs of period t as above, already discounted)
    VAR_OBJ(r,OBJSAL,cur)  =  SUM((v,p), OBJSCC(r,v,p,cur) * OBJ_DCEOH(r,cur) * installed(r,v,p))
                              + SUM((v,p), SALV_DEC(r,v,p,cur) * OBJ_DCEOH(r,cur) * installed(r,v,p))           decommissioning
                              + SUM((v,p), OBJ_SALVS(r,v,p,cur) * installed(r,v,p))                          surveillance (NCAP_DLAGC)
                              [where capacity can be retired: * VAR_SCAP(r,v,0,p) instead of installed]

OBJ_CINV and OBJ_CFIX are the sums over the years of payment and of operation that TIMES writes
inside the two equations; the preprocessor prepares them per unit of capacity. The investment
cost is charged in full and the salvage value is a row of its own; in the annualised form the
salvage value is taken off the annuity. The two forms give the same optimum; their objective
values can differ by a constant (fixed costs of capacity installed before the horizon).
"""
function eq_obj!(m::Model)
    (; Y_EOH, RDCUR, OBJ_PVT, OBJ_ICUR, COEF_CPT, COEF_OBINV, COEF_OBFIX, COEF_OBFIXR, OBJ_LINT, OB_ACT, OBJ_IPRIC, OB_FCOS, OB_FDEL, OB_FTAX, OBJ_COMNT, OBJ_COMPD, RHS_COMBAL, RHS_COMPRD,
        OBJ_VFLO, OBJ_SUMS, OBJSCC, OBJ_DCEOH, RVPRL, RP_STG, RP_FLO, RP_IRE, RPC_STG, RS_STGAV, STG_EFF, NCAP_COM, RPC_CUR, RP_UPR, ACT_CSTRMP, RS_STGPRD,
        OBJANN, VARCOST_LIN, OBJ_DISC, OBJ_CINV, OBJ_CFIX, OBJ_PASTI, OBJ_IAD, NCAP_FDR, MILESTONYR, NCAP_PASTI, PASTYEAR, OBJ_CDEC, OBJ_SUMS3, SALV_DEC, OBJ_SALVS,
        COEF_ICOM, COEF_OCOM, COEF_CIO, RTP_CPTYR, RS_FR, M) = m.d
    (; cptyr, lint, period_y, vara_p, vintages, prc_ts, ireio, flow_s, ts_ann, rpc_ire, rpcs_s, icom_at, ocom_at, ncap_com) = m.ix
    (; VAR_OBJ, VAR_ANNCST, VAR_ACT, VAR_SCAP, VAR_SIN, VAR_SOUT, VAR_COMNET, VAR_COMPRD, VAR_UDP, VAR_NCAP, OBJZ) = m.v
    (; OBJINV, OBJFIX, OBJVAR, OBJSAL, IN, OUT, COST, ACT, LO, UP, FX, ANNUAL) = m.K
    # TIMES-MACRO (eqobj.tm): the annualised costs of eqobjann.tm / eqobjcst.tm, summed by region and period into
    # VAR_OBJCOST (EQ_OBJ(R,T)), which the MACRO equations read; no EQ_OBJANN and no OBJZ
    tmacro = !isempty(m.d.MLF)
    annual = !isempty(OBJANN) || tmacro
    (annual && !isempty(m.d.OBJ_CSIC)) && error("TIMES feature not supported yet: S_NCAP_COST in the annualised objective")
    lin = !isempty(VARCOST_LIN)
    y0 = year0(m)
    # commodities with a cost, tax or subsidy on their net or gross production: (r, c, s, cur) -> cost types given
    function cost_types(P)
        d = Dict{NTuple{4,Id},Vector{Id}}()
        for (r, _, c, s, kind, cur) in P.keys
            v = get!(d, (r, c, s, cur), Id[])
            kind in v || push!(v, kind)
        end
        return d
    end
    net_types, prd_types = cost_types(OBJ_COMNT), cost_types(OBJ_COMPD)
    costed = unique((r, p, c, cur) for (r, p, c, cur, _) in OBJ_VFLO)
    any(((r, _, p, _, _, _, c, _),) -> any(k -> k[1:3] == (r, p, c), costed), m.d.IRE_FLOSUM.keys) &&
        error("TIMES feature not supported yet: cost on an auxiliary flow of a trade process (FLO_COST on a commodity of IRE_FLOSUM)")

    # the credits of COEF_OBFIXR on a (v, t) that is not in RTP_CPTYR (written after those that are, below)
    credit_extra = Dict{NTuple{3,Id},Vector{NTuple{2,Id}}}()
    for (r, v, t, p, cur) in COEF_OBFIXR.keys
        (r, v, t, p) in RTP_CPTYR || push!(get!(Vector{NTuple{2,Id}}, credit_extra, (r, t, cur)), (v, p))
    end
    for (r, cur) in RDCUR
        credits, variables = AE(), AE()             # standard form: the terms of all periods together
        for obv in (annual && !tmacro ? (OBJINV, OBJFIX, OBJVAR) : ())
            total = JuMP.@expression(m.jump, sum(OBJ_PVT(r, t, cur) * VAR_ANNCST(obv, r, t, cur) for t in m.T))
            if obv == OBJINV
                for (r2, v, p) in OBJ_SUMS
                    (r2 == r && has(RVPRL, r, v, p)) || continue
                    k = OBJSCC(r, v, p, cur) * OBJ_DCEOH(r, cur)
                    iszero(k) && continue
                    add!(total, k, installed(m, r, v, p))
                    add!(total, -k, VAR_SCAP(r, v, y0, p))
                end
            end
            row!(m, :EQ_OBJANN, (obv, r, cur), VAR_OBJ(r, obv, cur), ==, total)
        end

        for t in m.T
            pvt = OBJ_PVT(r, t, cur)

            credit = AE()
            for (v, p) in cptyr[r, t]
                has(COEF_OBFIXR, r, v, t, p, cur) && add!(credit, COEF_OBFIXR(r, v, t, p, cur), VAR_SCAP(r, v, t, p))
            end
            # prepret.dsc 136: SUM((OBJ_SUMIV(..),VNTRT(V,T))$RVPRL(R,V,P), ..): the credit runs over VNTRT, not RTP_CPTYR
            # (with STAGES the residual capacity is in RVPRL again at the solve, and a residual vintage can be retired in a
            # period of VNTRT where it is not in RTP_CPTYR)
            for (v, p) in get(credit_extra, (r, t, cur), ())
                add!(credit, COEF_OBFIXR(r, v, t, p, cur), VAR_SCAP(r, v, t, p))
            end
            if annual
                investment = JuMP.@expression(m.jump, sum(COEF_CPT(r, v, t, p) * COEF_OBINV(r, v, p, cur) * installed(m, r, v, p)
                    for (v, p) in cptyr[r, t] if (r, v, p, cur) in OBJ_ICUR))
                row!(m, :EQ_ANNINV, (r, t, cur), VAR_ANNCST(OBJINV, r, t, cur), ==, investment)

                fixed = JuMP.@expression(m.jump, sum(COEF_CPT(r, v, t, p) * COEF_OBFIX(r, v, p, cur) * installed(m, r, v, p)
                    for (v, p) in cptyr[r, t] if has(COEF_OBFIX, r, v, p, cur)))
                fixed = pvt * fixed + credit
                row!(m, :EQ_ANNFIX, (r, t, cur), pvt * VAR_ANNCST(OBJFIX, r, t, cur), ==, fixed)
            else
                add!(credits, 1.0, credit)
            end

            # unit cost in period t from the yearly values
            # (Y_EOH$OBJ_LINT(R,T,Y_EOH,CUR): the period whose costs are interpolated lies within the horizon; in a
            #  myopic step the horizon ends with the window)
            # eqobjvar.mod: %VARCOST%==LIN -> Y_EOH$OBJ_LINT(R,T,Y_EOH,CUR),OBJ_LINT(R,T,Y_EOH,CUR); otherwise PERIODYR(T,Y_EOH),OBJ_DISC(R,Y_EOH,CUR)
            in_period(cost) = lin ? sum(OBJ_LINT[r, t, y, cur] * cost(y) for y in lint[r, t, cur] if y in Y_EOH; init = 0.0) :
                                    sum(OBJ_DISC(r, y, cur) * cost(y) for y in period_y[t] if y in Y_EOH; init = 0.0)

            variable = AE()
            for p in vara_p[r, t]
                has(OB_ACT, r, p, cur, t) || continue
                cost = in_period(y -> OB_ACT(r, p, cur, y))
                stg = (r, p) in RP_STG
                for v in vintages[r, t, p], s in prc_ts[r, p]
                    add!(variable, stg ? cost * RS_STGAV(r, s) : cost, VAR_ACT(r, v, t, p, s))
                end
            end
            for (p, c, ie) in ireio[r, OUT], s in flow_s[r, t, p, c]
                price = in_period(y -> OBJ_IPRIC(r, y, p, c, s, ie, cur))
                iszero(price) && continue
                for v in vintages[r, t, p]
                    add!(variable, price, trade(m, r, v, t, p, c, s, ie))
                end
            end
            # ramping costs (ACT_CSTRMP, by vintage): on the load changes VAR_UDP, per storage cycle of the timeslice
            for (r2, p, c, cur2) in RPC_CUR
                (r2 == r && cur2 == cur && c == ACT) || continue
                for v in vintages[r, t, p], bd in (LO, UP)
                    ((r, p, bd) in RP_UPR && has(ACT_CSTRMP, r, v, p, bd, cur)) || continue
                    for s in prc_ts[r, p]
                        add!(variable, ACT_CSTRMP(r, v, p, bd, cur) * pvt * RS_STGPRD(r, s), VAR_UDP(r, v, t, p, s, bd))
                    end
                end
            end
            # start-up costs (ACT_CSTUP, by vintage): on the capacity started up on the start-up level, per cycle of its timeslices
            for (r2, p, c, cur2) in RPC_CUR
                (r2 == r && cur2 == cur && c == ACT) || continue
                for v in vintages[r, t, p], (tsl, l) in m.ix.ups_lv[r, p]
                    (l == UP && has(m.d.ACT_CSTUP, r, v, p, tsl, cur)) || continue
                    for s in m.ix.ts_group[r, tsl]
                        add!(variable, m.d.ACT_CSTUP(r, v, p, tsl, cur) * pvt * RS_STGPRD(r, s), m.v.VAR_UPS(r, v, t, p, s, UP))
                    end
                end
                # start-up costs by type (eqobjvar.mod 38): SUM(RP_UPT(R,P,UPT,'UP'),ACT_CSTSD(R,V,P,UPT,'FX',CUR)*OBJ_PVT *
                #   SUM(TS_GROUP(R,TSL,S)$RP_DPL(R,P,TSL),RS_STGPRD(R,S)*VAR_UPT(R,V,T,P,S,UPT)))
                for v in vintages[r, t, p], (upt, bd) in m.ix.upt_of[r, p]
                    (bd == UP && has(m.d.ACT_CSTSD, r, v, p, upt, FX, cur)) || continue
                    for tsl in m.ix.dpl[r, p], s in m.ix.ts_group[r, tsl]
                        add!(variable, m.d.ACT_CSTSD(r, v, p, upt, FX, cur) * pvt * RS_STGPRD(r, s), m.v.VAR_UPT(r, v, t, p, s, upt))
                    end
                end
            end
            # blending costs (eqobjvar.mod 105-106): SUM((BLE_OPR(R,BLE,OPR),TT(T)), SUM(TPULSE * OBJ_BLNDV(R,Y_EOH,BLE,OPR,CUR)) * VAR_BLND(R,T,BLE,OPR))
            for (r2, ble, opr) in m.d.BLE_OPR
                r2 == r || continue
                cost = in_period(y -> m.d.OBJ_BLNDV(r, y, ble, opr, cur))
                iszero(cost) || add!(variable, cost, m.v.VAR_BLND(r, t, ble, opr))
            end
            # costs on flows; the cost is given for the timeslice of the flow or for the year
            charged(p, c, s) = sum(in_period(y -> OB_FCOS(r, p, c, ts, cur, y)) for ts in ts_ann[s]; init = 0.0)
            delivered(p, c, s) = sum(in_period(y -> OB_FDEL(r, p, c, ts, cur, y)) for ts in ts_ann[s]; init = 0.0)
            taxed(p, c, s) = sum(in_period(y -> OB_FTAX(r, p, c, ts, cur, y)) for ts in ts_ann[s]; init = 0.0)
            for (r2, p, c, cur2) in costed
                (r2 == r && cur2 == cur) || continue
                if (r, p, c) in RPC_STG
                    (r, p, c, cur, COST) in OBJ_VFLO || continue
                    for v in vintages[r, t, p], s in rpcs_s[r, p, c]
                        add!(variable, charged(p, c, s), VAR_SIN(r, v, t, p, c, s))
                        add!(variable, delivered(p, c, s) * STG_EFF(r, v, p), VAR_SOUT(r, v, t, p, c, s))
                    end
                    continue
                end
                for s in flow_s[r, t, p, c]
                    cost = charged(p, c, s) + delivered(p, c, s) + taxed(p, c, s)
                    iszero(cost) && continue
                    for v in vintages[r, t, p]
                        (r, p) in RP_FLO && add!(variable, cost, flow(m, r, v, t, p, c, s))
                        if (r, p) in RP_IRE
                            for ie in rpc_ire[r, p, c]
                                add!(variable, cost, trade(m, r, v, t, p, c, s, ie))
                            end
                        end
                    end
                end
            end
            # the same costs on the flows tied to capacity (cal_caps.mod, from eqobjvar.mod 96-100 with S = ANNUAL):
            # SUM((VNT(V,T),RPC_CAPFLO(R,V,P,C)), ...) with the price SUM(RPCS_VAR(R,P,C,TS), RS_FR(R,TS,ANNUAL) * cost):
            #   (COEF_ICOM+COEF_OCOM)(r,v,t,p,c) * (VAR_NCAP(r,v,p) + NCAP_PASTI(r,v,p))
            #   COEF_CPT(r,v,t,p) * NCAP_COM(r,v,p,c,io) * standing(r,v,t,p) * (1+COEF_CIO(r,v,t,p,c,io))   (RTP_CPTYR)
            # VNT(V,T) is M(T) >= M(V) (ppmain.mod 505): investment flows in a period before the vintage's (a lead time)
            # are not charged. (VNT's entries from ppmain.mod 200-206, past vintages under INT_DEFAULT('PASTI'), are
            # taken by the same test.)
            for (r2, p, c, cur2) in costed
                (r2 == r && cur2 == cur) || continue
                price = sum(RS_FR(r, ts, ANNUAL) * (charged(p, c, ts) + delivered(p, c, ts) + taxed(p, c, ts)) for ts in rpcs_s[r, p, c]; init = 0.0)
                iszero(price) && continue
                vnt(v) = M(t) >= M(v)
                for v in unique(v for (v, p2) in Iterators.flatten((icom_at[r, t, c], ocom_at[r, t, c])) if p2 == p)
                    vnt(v) || continue
                    k = (COEF_ICOM(r, v, t, p, c) + COEF_OCOM(r, v, t, p, c)) * price
                    iszero(k) || add!(variable, k, installed(m, r, v, p))
                end
                for io in (IN, OUT), (v, p2) in ncap_com[r, c, io]
                    (p2 == p && (r, v, t, p) in RTP_CPTYR && vnt(v)) || continue
                    k = COEF_CPT(r, v, t, p) * NCAP_COM(r, v, p, c, io) * price * (1 + COEF_CIO(r, v, t, p, c, io))
                    iszero(k) || add!(variable, k, standing(m, r, v, t, p))
                end
            end
            # costs, taxes and subsidies on the net and on the gross production of a commodity
            for (P, types, RHS, VAR) in ((OBJ_COMNT, net_types, RHS_COMBAL, VAR_COMNET), (OBJ_COMPD, prd_types, RHS_COMPRD, VAR_COMPRD))
                isempty(types) && continue
                for (r2, t2, c, s) in RHS
                    (r2 == r && t2 == t) || continue
                    kinds = get(types, (r, c, s, cur), nothing)
                    kinds === nothing && continue
                    cost = sum(in_period(y -> P(r, y, c, s, kind, cur)) for kind in kinds; init = 0.0)
                    add!(variable, cost, VAR(r, t, c, s))
                end
            end
            # stochastic TIMES (eqobjvar.mod 48), the uncertain tax of the SOW W that represents the row's SOW in t:
            #   SUM((RTCS_VARC(R,T,C,S),COM_VAR,W(WW))$S_COM_TAX(R,T,C,S,COM_VAR,CUR,'1',W),
            #       SUM(Y_EOH(Y)$OBJ_LINT(R,T,Y,CUR),OBJ_LINT(R,T,Y,CUR)*S_COM_TAX(R,Y,C,S,COM_VAR,CUR,'1',W))*
            #       (%VAR%_COMPRD(R,T,C,S%SOW%)$DIAG('PRD',COM_VAR)+%VAR%_COMNET(R,T,C,S%SOW%)$DIAG('NET',COM_VAR)))
            if m.sw !== nothing && !isempty(m.d.S_COM_TAX)
                W, one, net = sow_at(m, t), id!(m.L, "1"), id!(m.L, "NET")
                for (r2, t2, c, s, cv, cur2, j, w2) in m.d.S_COM_TAX.keys
                    (r2 == r && t2 == t && cur2 == cur && j == one && w2 == W && (r, t, c, s) in m.d.RTCS_VARC) || continue
                    k = sum(OBJ_LINT[r, t, y, cur] * m.d.S_COM_TAX(r, y, c, s, cv, cur, one, W) for y in lint[r, t, cur] if y in Y_EOH; init = 0.0)
                    add!(variable, k, cv == net ? VAR_COMNET(r, t, c, s) : VAR_COMPRD(r, t, c, s))
                end
            end
            if annual
                row!(m, :EQ_ANNVAR, (r, t, cur), variable, ==, pvt * VAR_ANNCST(OBJVAR, r, t, cur))
            else
                add!(variables, 1.0, variable)
            end
        end
        annual && continue

        # ---- standard form: one row per cost component
        investment = AE(plain(OBJ_IAD(r, cur)))
        fixed = credits
        for (r2, v, p, cur2) in OBJ_CINV.keys
            (r2 == r && cur2 == cur) || continue
            # (EQ_OBJINV sums OBJ_SUMII(R,T,P,..): T, not V, so in a myopic step the vintages after the window as well)
            v in MILESTONYR && add!(investment, OBJ_CINV(r, v, p, cur), VAR_NCAP(r, v, p))
            # a past investment can be given on a milestone year (the first one, typically): it is paid for as well
            has(OBJ_PASTI, r, v, p, cur) && add!(investment, plain(OBJ_CINV(r, v, p, cur)), plain(OBJ_PASTI(r, v, p, cur)))
        end
        # stochastic TIMES (eqobjinv.mod 297-299), the uncertain investment cost of the SOW WW that represents the row's SOW in T:
        #   SUM((OBJ_SUMII(R,T,P,LIFE,K_EOH,JOT),SW_TSW(SOW,T,WW))$OBJ_SIC(R,T,P,WW), %CAPJD%
        #     SUM(INVSPRED(K_EOH,JOT,Y,K), OBJ_DISC(R,K,CUR) * OBJ_ICOST(R,K,P,CUR) * (1-SALV_INV(R,T,P,Y))) *
        #     OBJ_SIC(R,T,P,WW) * COR_SALVI(R,T,P,CUR) / OBJ_DIVI(R,T,P) * %VAR%_NCAP(R,T,P %SWD%))
        if m.sw !== nothing && !isempty(m.d.OBJ_CSIC)
            for (r2, v, p, cur2) in m.d.OBJ_CSIC.keys
                (r2 == r && cur2 == cur) || continue
                x = m.d.OBJ_SIC(r, v, p, sow_at(m, v))
                iszero(x) || add!(investment, m.d.OBJ_CSIC(r, v, p, cur) * x, VAR_NCAP(r, v, p))
            end
        end
        # decommissioning (Cases III): VAR_NCAP for a milestone vintage, OBJ_PASTI for a past one
        for (r2, v, p, cur2) in OBJ_CDEC.keys
            (r2 == r && cur2 == cur) || continue
            new_capacity(m, v) && add!(investment, OBJ_CDEC(r, v, p, cur), VAR_NCAP(r, v, p))
            (v in PASTYEAR && has(OBJ_PASTI, r, v, p, cur)) && add!(investment, plain(OBJ_CDEC(r, v, p, cur)), plain(OBJ_PASTI(r, v, p, cur)))
        end
        for (r2, v, p, cur2) in OBJ_CFIX.keys
            (r2 == r && cur2 == cur) || continue
            add!(fixed, OBJ_CFIX(r, v, p, cur), installed(m, r, v, p))
        end
        salvage = AE()
        for (r2, v, p) in OBJ_SUMS
            r2 == r || continue
            k = OBJSCC(r, v, p, cur) * OBJ_DCEOH(r, cur)
            iszero(k) && continue
            add!(salvage, k, installed(m, r, v, p))
            # prepret.dsc OBSALV: where capacity can be retired the salvage value is that of what is kept (VAR_SCAP of year 0)
            if has(RVPRL, r, v, p) && !(has(NCAP_FDR, r, v, p) && has(RVPRL, r, y0, p))
                add!(salvage, k, VAR_SCAP(r, v, y0, p))
                add!(salvage, -k, installed(m, r, v, p))
                # on VAR_NCAP the two cancel (eqobsalv.mod line 99, prepret.dsc line 162). A number cancelled is a zero and
                # GAMS drops it; an EPS salvage value (an investment cost given as 0) stays EPS (EPS - EPS = EPS), and
                # GAMS keeps that entry, at 0 (on a model of 19 M rows, 120 such, of some 40,800 retirable vintages)
                (iseps(k) && new_capacity(m, v)) && add!(salvage, EPS, VAR_NCAP(r, v, p))
            end
        end
        # salvage value of the decommissioning costs
        for (r2, v, p) in OBJ_SUMS3
            r2 == r || continue
            k = SALV_DEC(r, v, p, cur) * OBJ_DCEOH(r, cur)
            iszero(k) || add!(salvage, k, installed(m, r, v, p))
        end
        # salvage of the decommissioning surveillance costs (eqobsalv.mod, Cases IV), discounted to their years:
        # SUM(OBJ_SUMIVS(R,V,P,K,Y)$SALV_INV(R,V,P,K), OBJ_DISC(R,Y,CUR) * OBJ_DLAGC(R,K,P,CUR) * SALV_INV(R,V,P,K) * (VAR_NCAP + NCAP_PASTI))
        for (r2, v, p, cur2) in OBJ_SALVS.keys
            (r2 == r && cur2 == cur) || continue
            add!(salvage, OBJ_SALVS(r, v, p, cur), installed(m, r, v, p))
        end
        # SPINES: Q_OBJINV, Q_OBJFIX, Q_OBJSALV are the rows of SOW('1') only (recurrin.stc 73-75)
        w1 = sow_w1(m)
        w1 && row!(m, :EQ_OBJINV, (r, cur), investment, ==, VAR_OBJ(r, OBJINV, cur))
        w1 && row!(m, :EQ_OBJFIX, (r, cur), fixed, ==, VAR_OBJ(r, OBJFIX, cur))
        row!(m, :EQ_OBJVAR, (r, cur), variables, ==, VAR_OBJ(r, OBJVAR, cur))
        w1 && row!(m, :EQ_OBJSALV, (r, cur), salvage, ==, VAR_OBJ(r, OBJSAL, cur))
    end

    if tmacro
        isempty(m.d.OBJ_COMBAL) || error("TIMES feature not supported yet: costs on the components of a commodity balance (COM_CSTBAL) in TIMES-MACRO")
        # eqobj.tm:  EQ_OBJ(R,T) .. SUM(RDCUR(R,CUR), SUM(OBVANN,VAR_ANNCST(OBVANN,R,T,CUR))) =E= VAR_OBJCOST(R,T);
        for r in m.d.REG, t in m.T
            e = AE()
            for (r2, cur) in RDCUR, obv in (OBJINV, OBJFIX, OBJVAR)
                r2 == r && add!(e, 1.0, VAR_ANNCST(obv, r, t, cur))
            end
            row!(m, :EQ_OBJ, (r, t), e, ==, m.v.VAR_OBJCOST(r, t))
        end
        return
    end
    if m.sw !== nothing
        # stochastic TIMES: the objective of each SOW by region (ES_ROBJ, eqobj.mod 76), its expected value (EQ_EXPOBJ)
        regional = Dict{Id,AE}()
        for (r, cur) in RDCUR
            e = get!(AE, regional, r)
            foreach(obv -> add!(e, 1.0, VAR_OBJ(r, obv, cur)), (OBJINV, OBJFIX, OBJVAR))
            annual || add!(e, -1.0, VAR_OBJ(r, OBJSAL, cur))
        end
        (isempty(m.d.OBJ_COMBAL) && isempty(m.d.OBJELS_R)) ||
            error("TIMES feature not supported yet with STAGES: COM_CSTBAL or elastic demands in the objective")
        return sow_objective!(m, regional)
    end
    total = AE()
    for (r, cur) in RDCUR, obv in (OBJINV, OBJFIX, OBJVAR)
        add!(total, 1.0, VAR_OBJ(r, obv, cur))
    end
    # the costs on the components of a commodity balance (COM_CSTBAL: SET OBV / OBJBAL /, eq_objbal!)
    if !isempty(m.d.OBJ_COMBAL)
        objbal = id!(m.L, "OBJBAL")
        for (r, cur) in RDCUR
            add!(total, 1.0, VAR_OBJ(r, objbal, cur))
        end
    end
    if !annual
        for (r, cur) in RDCUR
            add!(total, -1.0, VAR_OBJ(r, OBJSAL, cur))
        end
    end
    # elastic demands (eqobj.mod 89): $IF %TIMESED% == YES +SUM(BD,%VAR%_OBJELS(R,BD,CUR)*BDSIG(BD))$SUM_OBJ(R,'OBJELS')
    for (r, cur) in RDCUR
        r in m.d.OBJELS_R || continue
        add!(total, 1.0, m.v.VAR_OBJELS(r, m.K.LO, cur))
        add!(total, -1.0, m.v.VAR_OBJELS(r, m.K.UP, cur))
    end
    row!(m, :EQ_OBJ, (), total, ==, OBJZ())
end
