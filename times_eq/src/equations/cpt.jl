# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQE_CPT / EQL_CPT / EQG_CPT (r,t,p)                                         eqcpt.mod

Capacity transfer: the capacity in period t is what earlier investments have left.

    VAR_CAP(r,t,p)  =  SUM(v, COEF_CPT(r,v,t,p) * standing(r,v,t,p))

The capacity variable exists only where something refers to it (RTP_VARP). Where it does not,
bounds on the capacity (CAP_BND) are applied to the right-hand side directly.
"""
function eq_cpt!(m::Model)
    (; RTP, MILESTONYR, RTP_VARP, CAP_BND, COEF_CPT) = m.d
    (; cpt_v) = m.ix
    (; VAR_CAP) = m.v
    (; LO, UP, FX) = m.K
    sow_w1(m) || return                     # SPINES: QE_CPT, QL_CPT, QG_CPT of SOW('1') only (recurrin.stc 80-82)

    for (r, t, p) in RTP
        t in MILESTONYR || continue

        # (SUM over V: in a myopic step not the vintages after the window)
        capacity() = JuMP.@expression(m.jump, sum(COEF_CPT(r, v, t, p) * standing(m, r, v, t, p) for v in cpt_v[r, t, p] if !(v in m.fwd)))

        if (r, t, p) in RTP_VARP
            row!(m, :EQE_CPT, (r, t, p), VAR_CAP(r, t, p), ==, capacity())
        else
            has(CAP_BND, r, t, p, FX) && row!(m, :EQE_CPT, (r, t, p), CAP_BND(r, t, p, FX), ==, capacity())
            has(CAP_BND, r, t, p, LO) && row!(m, :EQL_CPT, (r, t, p), CAP_BND(r, t, p, LO), <=, capacity())
            has(CAP_BND, r, t, p, UP) && row!(m, :EQG_CPT, (r, t, p), CAP_BND(r, t, p, UP), >=, capacity())
        end
    end
end
