# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_PTRANS(r,v,t,p,cg1,cg2,s)                                                eqptrans.mod

Transformation: the flows of commodity group cg2 follow from the flows of group cg1.

    SUM(c in cg2, flow(c) at s)  =  SUM(c in cg1, COEF_PTRAN(r,v,p,cg1,c,cg2,ts) * flow(c) at s)

"flow(c) at s" is the flow at its own timeslice ts times frac(c,s,ts). COEF_PTRAN holds the
efficiency (FLO_FUNC, FLO_SUM) after interpolation and levelling by the preprocessor. Where the flows
of cg2 are given per unit of activity on finer timeslices than those of the process, the right-hand
side is multiplied by that coefficient, ACT_FLO(r,v,p,cg2,s).
"""
eq_ptrans!(m::Model) = _eq_ptrans!(m, exprtype())
# in pieces (`PIECES`): contiguous blocks of RTP_VINTYR (a row is of one entry and reads no other)
ptrans_pieces(m::Model, n::Int) = Function[rm -> _eq_ptrans!(rm, exprtype(), b) for b in blocks(m.d.RTP_VINTYR.rows, n)]

function _eq_ptrans!(m::Model, ::Type{E}, vintyr = m.d.RTP_VINTYR) where {E}
    (; RTP_VINTYR, RP_STD, RS_TREE, COEF_PTRAN, ACT_FLO, PRC_CG) = m.d
    (; ffunc, rps_s1, flow_cs, flow_s, group_c, rpc_c, ts_tree) = m.ix

    for (r, v, t, p) in vintyr, (cg1, cg2) in ffunc[r, p], s in rps_s1[r, p]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (r, p) in RP_STD || continue
        any(has(COEF_PTRAN, r, v, p, cg1, c, cg2, ts) for c in rpc_c[r, p] for ts in ts_tree[r, s]) || continue

        driven = @esum(E, m.jump, sum(frac(m, r, t, c, s, ts) * flow(E, m, r, v, t, p, c, ts)
            for c in group_c[r, cg2] for ts in onbranch(flow_s[r, t, p, c], ts_tree[r, s]) if (r, s, ts) in RS_TREE))

        driving = @esum(E, m.jump, sum(COEF_PTRAN(r, v, p, cg1, c, cg2, ts) * frac(m, r, t, c, s, ts) * flow(E, m, r, v, t, p, c, ts)
            for (c, ts) in onbranch(flow_cs[r, t, p], ts_tree[r, s], 2) if (r, s, ts) in RS_TREE && has(COEF_PTRAN, r, v, p, cg1, c, cg2, ts)))

        # an age shape on the factors of the vintage (FLO_FUNCX: 1 + RTP_FFCX) scales the whole right-hand side
        f = ffcx(m, r, v, t, p, cg1, cg2)
        f == 1.0 || (driving = f * driving)
        # a flow given per unit of activity below the timeslices of the process (ACT_FLO) scales the whole right-hand side
        if (r, p, cg1) in PRC_CG && has(ACT_FLO, r, v, p, cg2, s)
            driving = plain(ACT_FLO(r, v, p, cg2, s)) * driving
        end
        row!(m, :EQ_PTRANS, (r, v, t, p, cg1, cg2, s), driven, ==, driving)
    end
end
