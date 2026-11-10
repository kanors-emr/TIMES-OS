# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_ACTBND / EQE_ACTBND / EQG_ACTBND (r,t,p,s)                              eqactbnd.mod

Bound on the activity of a process in timeslice s, all vintages together.

    SUM((v,ts), VAR_ACT(r,v,t,p,ts))  <=  ACT_BND(r,t,p,s,UP)

A row is needed only when the bound does not apply to a single variable: the process is vintaged,
or s lies above the timeslice level of the process. Otherwise it is a bound on VAR_ACT.
"""
function eq_actbnd!(m::Model)
    (; ACT_BND, RTP_VARA, RPS_PRCTS, PRC_VINT, PRC_TS, TS_MAP) = m.d
    (; prc_ts, vintages, ts_below) = m.ix
    (; VAR_ACT) = m.v
    (; LO, UP) = m.K
    kind = by_bound(m, "ACTBND")

    for ((r, t, p, s, bd), bound) in ACT_BND
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        ((r, t, p) in RTP_VARA && (r, p, s) in RPS_PRCTS) || continue
        ((r, p) in PRC_VINT || !((r, p, s) in PRC_TS)) || continue
        (bd == LO && plain(bound) == 0) && continue
        (bd == UP && bound == Inf) && continue

        activity = JuMP.@expression(m.jump, sum(VAR_ACT(r, v, t, p, ts)
            for ts in onbranch(prc_ts[r, p], ts_below[r, s]) if (r, s, ts) in TS_MAP for v in vintages[r, t, p]))

        name, sense = kind(bd)
        row!(m, name, (r, t, p, s), activity, sense, bound)
    end
end
