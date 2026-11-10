# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_BLND / EQG_BLND / EQE_BLND / EQN_BLND (r,t,ble,spe,'1')                   eqblnd.mod

Refinery blending: in the periods of the blend's specifications (BLE_TP, from BL_START on), the
qualities of the streams blended, against the specification, by its type BL_TYPE (1 at most,
2 at least, 3 equal, 4 not binding):

    SUM(opr in BLE_OPR(r,ble), (BL_COM(r,ble,opr,spe) - BL_SPEC(r,ble,spe)) * RU_CVT(r,ble,spe,opr) * VAR_BLND(r,t,ble,opr))  =L= / =G= / =E= / =N=  0

RU_CVT converts the specification's unit (BL_UNIT) to the unit of the refinery (REFUNIT); it is
defined for the streams that have a quality for spe, so the others have no term. VAR_BLND also
appears in the commodity balances (combal.jl) and the variable costs (objann.jl).
"""
function eq_blnd!(m::Model)
    (; BLE_TP, BL_TYPE, BL_COM, BL_SPEC, RU_CVT) = m.d
    (; ble_opr) = m.ix
    (; VAR_BLND) = m.v
    isempty(BL_TYPE) && return
    one = id!(m.L, "1")                      # SPE%SWX%: the state of the world '1' of a deterministic run (setglobs.gms 365)
    for ((r, ble, spe), type) in BL_TYPE
        # EQ%1_BLND(BLE_TP(R,T,BLE),SPE)$(BL_TYPE(R,BLE,SPE)=%2)
        name, sense = type == 1 ? (:EQL_BLND, LE) : type == 2 ? (:EQG_BLND, GE) : type == 3 ? (:EQE_BLND, EQ) :
                      type == 4 ? (:EQN_BLND, NB) : (:none, EQ)
        name == :none && continue
        for t in m.T
            (r, t, ble) in BLE_TP || continue
            e = AE()
            for opr in ble_opr[r, ble]
                k = (BL_COM(r, ble, opr, spe) - BL_SPEC(r, ble, spe)) * RU_CVT(r, ble, spe, opr)
                iszero(k) || add!(e, k, VAR_BLND(r, t, ble, opr))
            end
            row!(m, name, (r, t, ble, spe, one), e, sense, 0.0)
        end
    end
end
