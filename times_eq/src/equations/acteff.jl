# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQE_ACTEFF(r,v,t,p,cg,io,s)                                                 pp_actef.vda, eqacteff

Activity efficiency (ACT_EFF): the flows of group cg, each weighted by its efficiency, give the activity.

    SUM(c in cg, ACT_EFF(r,v,p,c,ts) * ACT_EFF(r,v,p,cg,s) * VAR_FLO(r,v,t,p,c,ts)) * shape  =  activity at s

(shape: 1 + RTP_FFCX(r,v,t,p,cg,ACT) for a vintaged process with FLO_FUNCX(cg,ACT), else 1)

A commodity without its own ACT_EFF counts with 1. The activity is VAR_ACT, or, where the
process has no activity of its own in this sense (RP_PGFLO), the flows of the primary group.
Where the efficiency is given on the commodities of the primary group (RPG_PACE), the right-hand
side is the activity divided by that efficiency.
"""
eq_acteff!(m::Model) = _eq_acteff!(m, exprtype())
# in pieces (`PIECES`): contiguous blocks of RTP_VINTYR (a row is of one entry and reads no other)
acteff_pieces(m::Model, n::Int) = Function[rm -> _eq_acteff!(rm, exprtype(), b) for b in blocks(m.d.RTP_VINTYR.rows, n)]

function _eq_acteff!(m::Model, ::Type{E}, vintyr = m.d.RTP_VINTYR) where {E}
    (; RTP_VINTYR, ACT_EFF, COM_GMAP, RTPCS_VARF, RS_FR, RP_PGFLO, RP_PGACT, RPG_PACE, PRC_ACTFLO, RP_PL, ACT_LOSPL) = m.d
    (; rpg_ace, rps_s1, rpc_ace, ts_below, prc_ts, pcg, ts_frac) = m.ix
    (; VAR_ACT, VAR_FLO, VAR_UPS) = m.v
    (; ANNUAL, FX) = m.K

    for (r, v, t, p) in vintyr, (cg, io) in rpg_ace[r, p], s in rps_s1[r, p]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        group_eff = ACT_EFF(r, v, p, cg, s) + (s == ANNUAL ? 0.0 : ACT_EFF(r, v, p, cg, ANNUAL))
        # the age shape of the group efficiency of a vintage, FLO_FUNCX(cg,ACT): pp_actef.vda lines 51-62,
        #   SUM(TS_ANN(S,TS),ACT_EFF(R,V,P,CG,TS)) * (1+RTP_FFCX(R,V,T,P,CG,'ACT'))$PRC_VINT(R,P)
        group_eff *= ffcx(m, r, v, t, p, cg, m.K.ACT)
        eff(c, ts) = has(ACT_EFF, r, v, p, c, ts) ? ACT_EFF(r, v, p, c, ts) : 1.0

        weighted_flows = @esum(E, m.jump, sum(eff(c, ts) * group_eff * VAR_FLO(r, v, t, p, c, ts)
            for c in rpc_ace[r, p] if (r, cg, c) in COM_GMAP
            for ts in ts_below[r, s] if (r, t, p, c, ts) in RTPCS_VARF))

        activity = if (r, p, cg) in RPG_PACE
            # efficiency given on the commodities of the primary group: the activity, or each primary flow, is divided by it
            @esum(E, m.jump, sum(frac(m, r, t, c, s, ts) / eff(c, ts) *
                    ((r, p) in RP_PGACT ? 1.0 * VAR_ACT(r, v, t, p, ts) : VAR_FLO(r, v, t, p, c, ts) / PRC_ACTFLO[r, v, p, c])
                for ts in onbranch(prc_ts[r, p], ts_frac[r, s]) if has(RS_FR, r, s, ts) for c in pcg[r, p]))
        elseif !((r, p) in RP_PGFLO)
            @esum(E, m.jump, sum(RS_FR(r, s, ts) * VAR_ACT(r, v, t, p, ts)
                for ts in onbranch(prc_ts[r, p], ts_frac[r, s]) if has(RS_FR, r, s, ts)))
        elseif (r, p) in RP_PGACT
            @esum(E, m.jump, sum(frac(m, r, t, c, s, ts) * VAR_ACT(r, v, t, p, ts)
                for ts in onbranch(prc_ts[r, p], ts_frac[r, s]) if has(RS_FR, r, s, ts) for c in pcg[r, p]))
        else
            @esum(E, m.jump, sum(frac(m, r, t, c, s, ts) / PRC_ACTFLO[r, v, p, c] * VAR_FLO(r, v, t, p, c, ts)
                for ts in onbranch(prc_ts[r, p], ts_frac[r, s]) if has(RS_FR, r, s, ts) for c in pcg[r, p]))
        end

        if (r, p, FX) in RP_PL
            # partial loads (pp_actef.vda 79-80): the loss at part load, SUM(RP_PL(R,P,L('FX')),ACT_LOSPL(R,V,P,L) *
            #   SUM(PRC_TS(R,P,TS)$RS_FR(R,S,TS),VAR_UPS(R,V,T,P,TS,L)*RS_FR(R,S,TS)))
            loss = plain(ACT_LOSPL(r, v, p, FX))
            for ts in onbranch(prc_ts[r, p], ts_frac[r, s])
                has(RS_FR, r, s, ts) && add!(activity, loss * RS_FR(r, s, ts), VAR_UPS(r, v, t, p, ts, FX))
            end
        end
        row!(m, :EQE_ACTEFF, (r, v, t, p, cg, io, s), weighted_flows, ==, activity)
    end
end
