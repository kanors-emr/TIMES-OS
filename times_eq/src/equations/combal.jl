# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQG_COMBAL / EQE_COMBAL (r,t,c,s)                                           eqcombal.mod

Commodity balance: what is produced and imported, after losses, covers what is consumed,
exported and demanded.

    COM_IE(r,t,c,s) * (flows(OUT) + trades(IMP) + trade_aux(OUT) + storage(OUT) + capacity_flows(OUT) + aggregated commodities)
        >=  flows(IN) + trades(EXP) + trade_aux(IN) + storage(IN) + capacity_flows(IN) + COM_IE(r,t,c,s) * grid_io
            + COM_PROJ(r,t,c) * COM_FR(r,t,c,s)

(grid_io: flows between a grid commodity and its nodes, see grids.jl. In TIMES-MACRO, RD_NLP: VAR_DEM(r,t,c) *
COM_FR(r,t,c,s) instead of the projection.)

`=` for commodities balanced with equality (then with VAR_COMNET on the right-hand side when the
net production is bounded, costed or used elsewhere). When the production of c is itself
referred to (RHS_COMPRD), the left-hand side is VAR_COMPRD, which is defined by

    EQE_COMPRD(r,t,c,s):   COM_IE * (flows(OUT) + trades(IMP) + storage(OUT) + ...)  =  VAR_COMPRD(r,t,c,s)
"""
eq_combal!(m::Model) = (combal_rows!(m, exprtype(), m.d.RCS_COMBAL); comprd_rows!(m, exprtype()))
# in pieces (`PIECES`): contiguous blocks of RCS_COMBAL (a row is of one entry and reads no other), then EQE_COMPRD
combal_pieces(m::Model, n::Int) =
    push!(Function[rm -> combal_rows!(rm, exprtype(), b) for b in blocks(m.d.RCS_COMBAL.rows, n - 1)],
          rm -> comprd_rows!(rm, exprtype()))

"""EQG_COMBAL / EQE_COMBAL for the entries `combal` of RCS_COMBAL."""
function combal_rows!(m::Model, ::Type{E}, combal) where {E}
    (; RHS_COMPRD, RHS_COMBAL, DEM, COM_PROJ, COM_FR, BLE_TP, RD_NLP) = m.d
    (; opr_ble, els_bal) = m.ix
    (; VAR_COMPRD, VAR_COMNET, VAR_BLND, VAR_ELAST) = m.v
    (; LO, UP, FX, IN, EXP, ANNUAL) = m.K

    grids = !isempty(m.d.GR_DEMMAP)
    for (r, t, c, s, bd) in combal
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (bd == LO || bd == FX) || continue

        available = (r, t, c, s) in RHS_COMPRD ? VAR_COMPRD(r, t, c, s) : supply(E, m, r, t, c, s)
        # elastic demands (eqcombal.mod 67): $IF %TIMESED%==YES + SUM(RCJ(R,C,J,BDNEQ(BD))$COM_ELAST(R,T,C,S,BD),BDSIG(BD)*%VAR%_ELAST(R,T,C,S,J,BD))
        for (j, bd) in els_bal[r, t, c, s]
            available = available + (bd == LO ? 1.0 : -1.0) * VAR_ELAST(r, t, c, s, j, bd)
        end
        consumed = flows(E, m, r, t, c, s, IN) + trades(E, m, r, t, c, s, EXP) + trade_aux(E, m, r, t, c, s, IN) + storage(E, m, r, t, c, s, IN) + capacity_flows(E, m, r, t, c, s, IN)
        grids && add!(consumed, m.d.COM_IE(r, t, c, s), grid_io(m, r, t, c, s))
        # streams blended (eqcombal.mod 75-77): SUM(BLE_TP(R,T,BLE)$BLE_OPR(R,BLE,C), RS_FR(R,S,'ANNUAL')*(1+RTCS_FR(R,T,C,S,'ANNUAL')) * VAR_BLND(R,T,BLE,C))
        # (78-80, the inputs BL_INP of BLE_INP: BLE_INP is always empty, ppmain.mod 1240)
        for ble in opr_ble[r, c]
            (r, t, ble) in BLE_TP && add!(consumed, frac(m, r, t, c, s, ANNUAL), VAR_BLND(r, t, ble, c))
        end
        # ((COM_PROJ(R,T,C)$(NOT RD_NLP(R,C)) + VAR_DEM(R,T,C)$RD_NLP(R,C)) * COM_FR(R,T,C,S))$DEM(R,C)   (TIMES-MACRO: RD_NLP)
        demand = !((r, c) in DEM) ? 0.0 : iszero(RD_NLP(r, c)) ? sow_com_proj(m, r, t, c) * com_frmx(m, r, t, c, s) :
                 com_frmx(m, r, t, c, s) * m.v.VAR_DEM(r, t, c)
        net = (bd == FX && (r, t, c, s) in RHS_COMBAL) ? VAR_COMNET(r, t, c, s) : 0.0

        if bd == LO
            row!(m, :EQG_COMBAL, (r, t, c, s), available - consumed, >=, demand)
        else
            row!(m, :EQE_COMBAL, (r, t, c, s), available - consumed, ==, demand + net)
        end
    end
end

"""EQE_COMPRD: the production of c, where it is referred to (RHS_COMPRD)."""
function comprd_rows!(m::Model, ::Type{E}) where {E}
    (; RCS_COMPRD, RHS_COMPRD) = m.d
    (; VAR_COMPRD) = m.v
    (; FX) = m.K
    for (r, t, c, s, bd) in RCS_COMPRD
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (bd == FX && (r, t, c, s) in RHS_COMPRD) || continue
        row!(m, :EQE_COMPRD, (r, t, c, s), supply(E, m, r, t, c, s), ==, VAR_COMPRD(r, t, c, s))
    end
end

"""
Supply of commodity c in timeslice s after losses: process outputs, imports, discharge of storage,
flows that come with capacity, and other commodities aggregated into c (COM_AGG, through their
net or gross production).
"""
function supply(::Type{E}, m::Model, r, t, c, s) where {E}
    (; RS_TREE, RC_AGP, COM_AGG, COM_IE, RS_FR, BLE_BAL, ENV_BL) = m.d
    (; agg_into, varc_ts, ts_tree, ble_opr, ble_env) = m.ix
    (; VAR_COMNET, VAR_COMPRD, VAR_BLND) = m.v
    (; LO, FX, OUT, IMP, ANNUAL) = m.K

    aggregated = E()
    for com in agg_into[r, t, c], ts in onbranch(varc_ts[r, t, com], ts_tree[r, s])
        (r, s, ts) in RS_TREE || continue
        k = COM_AGG(r, t, com, c) * frac(m, r, t, com, s, ts)
        (r, com, LO) in RC_AGP && add!(aggregated, k, VAR_COMNET(r, t, com, ts))
        (r, com, FX) in RC_AGP && add!(aggregated, k, VAR_COMPRD(r, t, com, ts))
    end
    # blending (eqcombal.mod 30-35): the blend made, SUM(BLE_OPR(R,C,OPR), RS_FR(R,S,'ANNUAL')*(1+RTCS_FR(R,T,C,S,'ANNUAL')) *
    # BLE_BAL(R,T,C,OPR) * VAR_BLND(R,T,C,OPR)), and the emissions of blending, SUM(BLE_ENV(R,C,BLE,OPR), RS_FR(R,S,'ANNUAL') *
    # ENV_BL(R,C,BLE,OPR,T) * VAR_BLND(R,T,BLE,OPR)); BLE_BAL is there in the periods of BLE_TP only
    for opr in ble_opr[r, c]
        k = BLE_BAL(r, t, c, opr)
        iszero(k) || add!(aggregated, frac(m, r, t, c, s, ANNUAL) * k, VAR_BLND(r, t, c, opr))
    end
    for (ble, opr) in ble_env[r, c]
        k = ENV_BL(r, c, ble, opr, t)
        iszero(k) || add!(aggregated, RS_FR(r, s, ANNUAL) * k, VAR_BLND(r, t, ble, opr))
    end
    return COM_IE(r, t, c, s) * (flows(E, m, r, t, c, s, OUT) + trades(E, m, r, t, c, s, IMP) + trade_aux(E, m, r, t, c, s, OUT) + storage(E, m, r, t, c, s, OUT) +
                                 capacity_flows(E, m, r, t, c, s, OUT) + aggregated)
end
