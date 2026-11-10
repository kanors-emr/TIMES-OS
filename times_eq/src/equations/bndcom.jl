# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_BNDNET / EQE_BNDNET / EQG_BNDNET (r,t,c,s), and the same for BNDPRD          eqbndcom.mod

Bound on the net (VAR_COMNET) or gross (VAR_COMPRD) production of commodity c given on a timeslice s
above the timeslices of the commodity (RCS_COMTS, not COM_TS): the variables of the timeslices below
s summed. On a timeslice of the commodity the bound is a bound on the variable (bndmain.mod).

    SUM(ts in RTCS_VARC, TS_MAP(r,s,ts), VAR_COMNET(r,t,c,ts))  {>=, =, <=}  COM_BNDNET(r,t,c,s,bd)

eqmain.mod lines 54-59: LO only when not 0, UP only when not INF, FX always. Type N is not a bound
(pp_prelv.vda turns it into LO / FX on the variables).
"""
function eq_bndcom!(m::Model)
    (; COM_BNDNET, COM_BNDPRD, RTC, RCS_COMTS, COM_TS, TS_MAP) = m.d
    (; varc_ts, ts_below) = m.ix
    (; VAR_COMNET, VAR_COMPRD) = m.v
    (; LO, UP, FX) = m.K

    for (bounds, var, stem) in ((COM_BNDNET, VAR_COMNET, "BNDNET"), (COM_BNDPRD, VAR_COMPRD, "BNDPRD"))
        kind = by_bound(m, stem)
        for ((r, t, c, s, bd), bound) in bounds
            (bd == LO || bd == UP || bd == FX) || continue
            (m.stepped && !(t in m.sub)) && continue
            ((r, t, c) in RTC && (r, c, s) in RCS_COMTS && !((r, c, s) in COM_TS)) || continue
            (bd == LO && plain(bound) == 0) && continue
            (bd == UP && bound == Inf) && continue
            e = AE()
            for ts in onbranch(varc_ts[r, t, c], ts_below[r, s])
                (r, s, ts) in TS_MAP && add!(e, 1.0, var(r, t, c, ts))
            end
            name, sense = kind(bd)
            row!(m, name, (r, t, c, s), e, sense, plain(bound))
        end
    end
end
