# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_CAPACT / EQE_CAPACT / EQG_CAPACT (r,v,t,p,s)                            eqcapact.mod

Use of capacity: the activity in timeslice s (summed over the process timeslices below s) is
limited by the available capacity.

    SUM(ts, VAR_ACT(r,v,t,p,ts))  <=  COEF_AF(r,v,t,p,s,UP) * COEF_CPT(r,v,t,p) * standing(r,v,t,p)
                                      * PRC_CAPACT(r,p) * G_YRFR(r,s)

A vintaged process has one row per vintage; otherwise the right-hand side is summed over all
vintages k that are still available in t, and the row is written for v = t only.
`>=` for a lower and `=` for a fixed availability.

The activity of a storage is its level. The level in the timeslices ts of the process that
contain s counts, divided by the number of storage cycles of ts in a year, and the capacity is
available in full in every timeslice:

    SUM(ts, VAR_ACT(r,v,t,p,ts) * RS_FR(r,ts,s) * EXP(PRC_SC(r,p)) / RS_STGPRD(r,ts))
        <=  COEF_AF * COEF_CPT * standing(r,v,t,p) * PRC_CAPACT(r,p)

Where the availability is given by commodity (RPS_CAFLAC), EQ(l)_CAFLAC takes the place of this row.
"""
eq_capact!(m::Model) = _eq_capact!(m, exprtype())
# in pieces (`PIECES`): contiguous blocks of RTP_VINTYR (a row is of one entry and reads no other)
capact_pieces(m::Model, n::Int) = Function[rm -> _eq_capact!(rm, exprtype(), b) for b in blocks(m.d.RTP_VINTYR.rows, n)]

function _eq_capact!(m::Model, ::Type{E}, vintyr = m.d.RTP_VINTYR) where {E}
    (; RTP_VINTYR, TS_MAP, PRC_VINT, RP_STG, RPS_CAFLAC, PRC_CAPACT, G_YRFR, RS_FR, PRC_SC, RS_STGPRD, COEF_AF, COEF_CPT) = m.d
    (; afs, prc_ts, cpt_v, ts_below, ts_frac_in) = m.ix
    (; VAR_ACT) = m.v
    kind = by_bound(m, "CAPACT")

    for (r, v, t, p) in vintyr, (s, bd) in afs[r, t, p]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        (r, p, s, bd) in RPS_CAFLAC && continue

        stg = (r, p) in RP_STG
        activity = if stg
            @esum(E, m.jump, sum(RS_FR(r, ts, s) * exp(PRC_SC(r, p)) / RS_STGPRD[r, ts] * VAR_ACT(r, v, t, p, ts)
                for ts in onbranch(prc_ts[r, p], ts_frac_in[r, s]) if has(RS_FR, r, ts, s)))
        else
            @esum(E, m.jump, sum(VAR_ACT(r, v, t, p, ts) for ts in onbranch(prc_ts[r, p], ts_below[r, s]) if (r, s, ts) in TS_MAP))
        end

        unit = PRC_CAPACT[r, p] * (stg ? 1.0 : G_YRFR[r, s])
        # COEF_AF%3: COEF_AFMX for FX and UP (eqmain.mod 64-65), stochastic TIMES with S_NCAP_AFS (afmx)
        af(k) = bd == m.K.LO ? COEF_AF(r, k, t, p, s, bd) : afmx(m, COEF_AF(r, k, t, p, s, bd), r, t, p, s)
        available = if (r, p) in PRC_VINT
            emul(af(v) * COEF_CPT(r, v, t, p), unit) * standing(E, m, r, v, t, p)
        else
            @esum(E, m.jump, sum(emul(af(k) * COEF_CPT(r, k, t, p), unit) * standing(E, m, r, k, t, p)
                for k in cpt_v[r, t, p]))
        end

        name, sense = kind(bd)
        row!(m, name, (r, v, t, p, s), activity, sense, available)
    end
end
