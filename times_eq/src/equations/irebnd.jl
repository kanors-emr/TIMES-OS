# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQx_IREBND(r,t,c,s,r2,ie)                                                   eqirebnd.mod
    EQx_XBND(r,t,c,s,ie)                                                        eqxbnd.mod

Bounds on trade, written as rows (x = G for LO, E for FX, L for UP; no row for a LO of 0 or EPS or an infinite UP,
eqmain.mod lines 152-154 and 241-243).

IRE_BND(r,t,c,s,r2,ie): the trade of region r in commodity c with the partner r2, at timeslice s.

    imports (IMP)  from an internal partner r2 through p with an import equation in r (RPC_EQIRE): the exports of r2
                   that come to r, as in EQ_IRE (IRE_FLO, IRE_CCVT, IRE_TSCVT)
                   otherwise (an external partner, a marketplace): the imports of r through p
    exports (EXP)  of a marketplace r to an internal region r2: the imports of r2 from the market
                   otherwise: the exports of r through p (p trading c with r2)

A flow at timeslice ts of r counts in s fully when ts is s or below it, with G_YRFR(s)/G_YRFR(ts) when s lies below ts.

IRE_XBND(r,t,c,s,ie): all imports or all exports of c of the internal region r, at s (RS_FR share of each flow
timeslice); for an external region r (eqxbnd.mod 39-51), the trade of the internal regions with it in the other
direction, through IRE_TSCVT (an external region has RPC_IRE records of its own, so the row is written).
"""
function eq_irebnd!(m::Model)
    (; IRE_BND, IRE_XBND, RCS_COMTS, RPC_IRE, RPC_EQIRE, RPC_MARKET, RPC_AIRE, TOP_IRE, RTPCS_VARF, RS_TREE, RS_BELOW, TS_MAP,
       RS_FR, G_YRFR, IRE_TSCVT, IRE_CCVT, IRE_FLO, REG) = m.d
    (; ire_p, vintages, flow_s, ts_tree, tscvt) = m.ix
    # the timeslices of region r2 on the branch of any timeslice that a timeslice of r converts to (IRE_TSCVT)
    tree_of(r2, r, s) = unique!(reduce(vcat, (ts_tree[r2, als] for als in tscvt[r2, r, s]); init = Id[]))
    (; IMP, EXP, LO, UP, FX) = m.K

    # weight of a flow at ts of region r in a bound at s: 1 when ts is s or below it, G_YRFR(s)/G_YRFR(ts) when s is below ts
    level(r, s, ts) = (r, s, ts) in TS_MAP ? 1.0 : (r, ts, s) in RS_BELOW ? G_YRFR[r, s] / G_YRFR[r, ts] : 0.0
    sense = Dict(LO => (:EQG_IREBND, >=), FX => (:EQE_IREBND, ==), UP => (:EQL_IREBND, <=))
    xsense = Dict(LO => (:EQG_XBND, >=), FX => (:EQE_XBND, ==), UP => (:EQL_XBND, <=))
    nontrivial(bd, v) = bd == FX || (bd == LO && plain(v) != 0) || (bd == UP && plain(v) != Inf)

    for ((r, t, c, s, r2, ie, bd), value) in IRE_BND
        (t in m.T && haskey(sense, bd) && nontrivial(bd, value)) || continue
        (m.stepped && !(t in m.sub)) && continue
        ((r, c, s) in RCS_COMTS && !isempty(ire_p[r, c, ie])) || continue
        e = AE()
        if ie == IMP
            # exports of the internal partner r2 that come to r through p (p has an import equation in r)
            for (rx, com, ri, ci, p) in TOP_IRE
                (rx == r2 && ri == r && ci == c && r2 in REG && (r, p, c, IMP) in RPC_EQIRE) || continue
                for sl in onbranch(flow_s[r, t, p, c], ts_tree[r, s])
                    (r, s, sl) in RS_TREE || continue
                    w = level(r, s, sl)
                    iszero(w) && continue
                    for ts in onbranch(flow_s[r2, t, p, com], tree_of(r2, r, sl)), als in tscvt[r2, r, sl]
                        ((r2, als, ts) in RS_TREE) || continue
                        k = IRE_TSCVT[r2, als, r, sl] * frac(m, r2, t, com, als, ts) * IRE_CCVT(r2, com, r, c) * w
                        for v in vintages[r2, t, p]
                            add!(e, k * IRE_FLO(r2, v, p, com, r, c, sl), trade(m, r2, v, t, p, com, ts, EXP))
                        end
                    end
                end
            end
            # imports of r through p from an external partner or a marketplace (p trades c with r2)
            for p in ire_p[r, c, IMP]
                (r, p, c, IMP) in RPC_EQIRE && continue
                any(k -> k[1] == r2 && k[3] == r && k[4] == c && k[5] == p, TOP_IRE) || continue
                for ts in onbranch(flow_s[r, t, p, c], ts_tree[r, s])
                    (r, s, ts) in RS_TREE || continue
                    w = level(r, s, ts)
                    iszero(w) && continue
                    for v in vintages[r, t, p]
                        add!(e, w, trade(m, r, v, t, p, c, ts, IMP))
                    end
                end
            end
        else
            # exports of a marketplace r to the internal region r2: the imports of r2 from the market
            for (rx, cx, ri, com, p) in TOP_IRE
                (rx == r && cx == c && ri == r2 && r2 in REG && (r, p, c, EXP) in RPC_MARKET) || continue
                for ts in onbranch(flow_s[r2, t, p, com], tree_of(r2, r, s)), als in tscvt[r2, r, s]
                    (r2, als, ts) in RS_TREE || continue
                    k = IRE_CCVT(r2, com, r, c) * IRE_TSCVT[r2, als, r, s] * frac(m, r2, t, com, als, ts)
                    for v in vintages[r2, t, p]
                        add!(e, k, trade(m, r2, v, t, p, com, ts, IMP))
                    end
                end
            end
            # exports of r through p (p trades c with r2)
            for p in ire_p[r, c, EXP]
                (r, p, c, EXP) in RPC_MARKET && continue
                any(k -> k[1] == r && k[2] == c && k[3] == r2 && k[5] == p, TOP_IRE) || continue
                for ts in onbranch(flow_s[r, t, p, c], ts_tree[r, s])
                    (r, s, ts) in RS_TREE || continue
                    w = level(r, s, ts)
                    iszero(w) && continue
                    for v in vintages[r, t, p]
                        add!(e, w, trade(m, r, v, t, p, c, ts, EXP))
                    end
                end
            end
        end
        name, op = sense[bd]
        row!(m, name, (r, t, c, s, r2, ie), e, op, plain(value))
    end

    for ((r, t, c, s, ie, bd), value) in IRE_XBND
        (t in m.T && haskey(xsense, bd) && nontrivial(bd, value)) || continue
        (m.stepped && !(t in m.sub)) && continue
        isempty(ire_p[r, c, ie]) && continue                # SUM(RPC_IRE(ALL_REG,P,C,IE),1): external regions have them too
        e = AE()
        if r in REG
            for p in ire_p[r, c, ie], ts in onbranch(flow_s[r, t, p, c], ts_tree[r, s])
                (r, s, ts) in RS_TREE || continue
                k = RS_FR(r, s, ts)
                iszero(k) && continue
                for v in vintages[r, t, p]
                    add!(e, k, trade(m, r, v, t, p, c, ts, ie))
                end
            end
        else
            # eqxbnd.mod 39-51, an external region: the trade of the internal regions with it, in the other direction
            # (IMPEXP(IE--1)): their imports from it when it exports (TOP_IRE(ALL_REG,C,R,COM,P)), their exports to it
            # when it imports (TOP_IRE(R,COM,ALL_REG,C,P)); a flow at ts counts IRE_TSCVT(R,ALL_TS,ALL_REG,S) *
            # RS_FR(R,ALL_TS,TS) for each ALL_TS of R that converts to s
            ie2 = ie == EXP ? IMP : EXP
            for (rx, cx, ri, ci, p) in TOP_IRE
                r2, com = ie == EXP ? (ri, ci) : (rx, cx)
                (ie == EXP ? (rx == r && cx == c) : (ri == r && ci == c)) || continue
                (r2 in REG && (r2, p, com, ie2) in RPC_IRE) || continue
                for als in tscvt[r2, r, s], ts in onbranch(flow_s[r2, t, p, com], ts_tree[r2, als])
                    ((r2, als, ts) in RS_TREE) || continue
                    k = IRE_TSCVT[r2, als, r, s] * RS_FR(r2, als, ts)
                    iszero(k) && continue
                    for v in vintages[r2, t, p]
                        add!(e, k, trade(m, r2, v, t, p, com, ts, ie2))
                    end
                end
            end
        end
        name, op = xsense[bd]
        row!(m, name, (r, t, c, s, ie), e, op, plain(value))
    end
end
