# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_IRE(r,t,p,c,ie,s)                                                        eqire.mod

Trade between regions through process p: what one region exports the others import.
Written for region r and its commodity c,

    for exports:   SUM(importing regions, their imports converted to c and s of r / IRE_FLO)  =  exports of r
                   (written so in TIMES: - exports + imports = 0, eqire.mod line 18)
    for imports:   imports of r  =  SUM(exporting regions, their exports converted to c and s of r * IRE_FLO)

IRE_CCVT converts commodity units and IRE_TSCVT timeslices between the two regions; IRE_FLO is
the efficiency of the exchange.

A marketplace (RPC_MARKET) is a region that exports a commodity through p to several regions. Their
imports have no equation of their own: they are taken out of the market in its import equation,

    imports of the market + SUM(regions it serves, their imports)  =  SUM(exporting regions, their exports ...)

where the exports of the market itself count on the right (TIMES adds a trade link of the market with itself).
"""
function eq_ire!(m::Model)
    (; RPC_EQIRE, RPC_MARKET, TOP_IRE, RTP, RTPCS_VARF, RS_TREE, RS_FR, IRE_TSCVT, IRE_CCVT, IRE_FLO) = m.d
    (; rpcs_s, vintages, importers, exporters, tscvt, flow_s, ts_tree, ts_frac) = m.ix
    (; IMP, EXP) = m.K

    # the regions a marketplace serves: (market, p) -> (its export commodity, importing region, import commodity)
    served = Dict{Any,Vector{Any}}()
    for (r, c1, r2, c2, p) in TOP_IRE
        r != r2 && (r, p, c1, EXP) in RPC_MARKET && push!(get!(served, (r, p), Any[]), (c1, r2, c2))
    end

    for (r, p, c, ie) in RPC_EQIRE, t in m.T, s in rpcs_s[r, p, c]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        (r, t, p) in RTP || continue

        own = (r, t, p, c, s) in RTPCS_VARF ?
              JuMP.@expression(m.jump, sum(trade(m, r, v, t, p, c, s, ie) for v in vintages[r, t, p])) : 0.0

        partners = if ie == EXP
            JuMP.@expression(m.jump, sum(
                IRE_TSCVT[r2, s2, r, s] * frac(m, r2, t, c2, s2, ts) * IRE_CCVT(r2, c2, r, c) / IRE_FLO[r, v, p, c, r2, c2, ts] *
                trade(m, r2, v, t, p, c2, ts, IMP)
                for (r2, c2) in importers[r, c, p] for s2 in tscvt[r2, r, s]
                for ts in onbranch(flow_s[r2, t, p, c2], ts_tree[r2, s2]) if (r2, s2, ts) in RS_TREE
                for v in vintages[r2, t, p]))
        else
            JuMP.@expression(m.jump, sum(
                IRE_TSCVT[r2, s2, r, s] * frac(m, r2, t, c2, s2, ts) * IRE_CCVT(r2, c2, r, c) * IRE_FLO(r2, v, p, c2, r, c, s) *
                trade(m, r2, v, t, p, c2, ts, EXP)
                for (r2, c2) in exporters[r, c, p] for s2 in tscvt[r2, r, s]
                for ts in onbranch(flow_s[r2, t, p, c2], ts_frac[r2, s2]) if has(RS_FR, r2, s2, ts)
                for v in vintages[r2, t, p]))
        end

        if (r, p, c, IMP) in RPC_MARKET && haskey(served, (r, p))
            own += JuMP.@expression(m.jump, sum(
                IRE_TSCVT[r2, s2, r, s] * frac(m, r2, t, c2, s2, ts) * IRE_CCVT(r2, c2, r, c1) * IRE_CCVT(r, c1, r, c) *
                trade(m, r2, v, t, p, c2, ts, IMP)
                for (c1, r2, c2) in served[r, p] for s2 in tscvt[r2, r, s]
                for ts in onbranch(flow_s[r2, t, p, c2], ts_tree[r2, s2]) if (r2, s2, ts) in RS_TREE
                for v in vintages[r2, t, p]))
        end

        # eqire.mod line 18: the own trade times (1-2*XPT(IE)); an export equation is  - exports + SUM(imports / IRE_FLO) = 0
        # (the same equation as exports = imports, but its dual has the other sign)
        ie == EXP ? row!(m, :EQ_IRE, (r, t, p, c, ie, s), partners, ==, own) :
                    row!(m, :EQ_IRE, (r, t, p, c, ie, s), own, ==, partners)
    end
end
