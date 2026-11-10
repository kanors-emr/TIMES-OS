# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_ACTFLO(r,v,t,p,s)                                                        eqactflo.mod

Activity of a process: the sum of the flows of its primary commodity group, each in activity units.

    VAR_ACT(r,v,t,p,s)  =  SUM(c in PCG(p), VAR_FLO(r,v,t,p,c,s) / PRC_ACTFLO(r,v,p,c))

For a trade process the flows are its imports and/or exports.
"""
eq_actflo!(m::Model) = _eq_actflo!(m, exprtype())
# in pieces (`PIECES`): contiguous blocks of RTP_VINTYR (a row is of one entry and reads no other)
actflo_pieces(m::Model, n::Int) = Function[rm -> _eq_actflo!(rm, exprtype(), b) for b in blocks(m.d.RTP_VINTYR.rows, n)]

# eqactflo.mod 29 divides by PRC_ACTFLO. One given as 0 is EPS under $ONEPS and the defaults keep it (ppmain.mod 606-608,
# NOT EPS is false): GAMS stops with "division by eps" while generating the row, and so does the port
# (a suspected defect of TIMES, reproduced)
function actflo_divisor(m::Model, r, v, t, p, c, s)
    x = m.d.PRC_ACTFLO[r, v, p, c]
    iseps(x) && error("division by eps: EQ_ACTFLO(", join(label(m.L, (r, v, t, p, s)), ","), "): PRC_ACTFLO(",
                      join(label(m.L, (r, v, p, c)), ","), ") is EPS (given as 0); TIMES stops here too (eqactflo.mod 29)")
    return x
end

function _eq_actflo!(m::Model, ::Type{E}, vintyr = m.d.RTP_VINTYR) where {E}
    (; RTP_VINTYR, PRC_ACT, RTP_VARA, RTPCS_VARF, RP_FLO, RP_IRE, RPC_IRE, RP_AIRE, PRC_ACTFLO, RTPS_OFF) = m.d
    (; prc_ts, pcg) = m.ix
    red = reduced(m)
    (; VAR_ACT, VAR_FLO, VAR_IRE) = m.v
    (; IMP, EXP) = m.K

    for (r, v, t, p) in vintyr, s in prc_ts[r, p]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        (r, p) in PRC_ACT || continue
        # $IF %REDUCE% == 'YES' (NOT RTPS_OFF(R,T,P,S)) *
        (red && (r, t, p, s) in RTPS_OFF) && continue

        activity = (r, t, p) in RTP_VARA ? VAR_ACT(r, v, t, p, s) : 0.0
        pcg_flows = @esum(E, m.jump, sum(VAR_FLO(r, v, t, p, c, s) / actflo_divisor(m, r, v, t, p, c, s)
            for c in pcg[r, p] if (r, p) in RP_FLO && (r, t, p, c, s) in RTPCS_VARF))
        pcg_trade = @esum(E, m.jump, sum(VAR_IRE(r, v, t, p, c, s, ie) / actflo_divisor(m, r, v, t, p, c, s)
            for c in pcg[r, p] if (r, p) in RP_IRE && (r, t, p, c, s) in RTPCS_VARF
            for ie in (IMP, EXP) if (r, p, c, ie) in RPC_IRE && (r, p, ie) in RP_AIRE))

        row!(m, :EQ_ACTFLO, (r, v, t, p, s), activity, ==, pcg_flows + pcg_trade)
    end
end
