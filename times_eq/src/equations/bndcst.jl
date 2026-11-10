# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_BNDCST(r,y1,tt,y2,agg,cur)                                                eqbndcst.mod

The undiscounted costs of category agg (investment, decommissioning, fixed costs, commodity and flow taxes and
subsidies) in the years y1..y2 (REG_BNDCST of one milestone year, REG_CUMCST of a range; tt: the period of y2). The
preprocessor prepares the coefficients (prep/bndcst.py); an aggregate category sums its components' VAR_CUMCST
(BC_AGG: 1, a subsidy -1):

    SUM((t,p), BC_NCAP * VAR_NCAP(r,t,p))
      + SUM((t,c,s), BC_COMNET * VAR_COMNET(r,t,c,s) + BC_COMPRD * VAR_COMPRD(r,t,c,s))
      + SUM((t,p,c,s), BC_FLO * SUM(v in RTP_VINTYR, the flow of (v,t,p,c,s): VAR_FLO (cal_red), or the trade VAR_IRE))
      + SUM(agg2, BC_AGG * VAR_CUMCST(r,y1,y2,agg2,cur))
    = VAR_CUMCST(r,y1,y2,agg,cur)

The bounds (bnd_cum.mod) are on VAR_CUMCST.
"""
function eq_bndcst!(m::Model)
    (; BC_ROW, BC_NCAP, BC_COMNET, BC_COMPRD, BC_FLO, BC_AGG, RP_IRE) = m.d
    (; vintages, rpc_ire) = m.ix
    (; VAR_NCAP, VAR_COMNET, VAR_COMPRD, VAR_CUMCST) = m.v
    isempty(BC_ROW) && return
    # the terms of each row (r,y1,y2,agg,cur), in input order
    terms = Dict{NTuple{5,Id},Vector{Tuple{Symbol,Any,Float64}}}()
    term!(k, kind, rest, x) = push!(get!(terms, k[1:5], Tuple{Symbol,Any,Float64}[]), (kind, rest, x))
    for (k, x) in BC_NCAP;   term!(k, :ncap, k[6:7], x);  end
    for (k, x) in BC_COMNET; term!(k, :net, k[6:8], x);   end
    for (k, x) in BC_COMPRD; term!(k, :prd, k[6:8], x);   end
    for (k, x) in BC_FLO;    term!(k, :flo, k[6:9], x);   end
    for (k, x) in BC_AGG;    term!(k, :agg, k[6], x);     end

    for (r, y1, y2, agg, cur, tt) in BC_ROW
        e = AE()
        for (kind, rest, x) in get(terms, (r, y1, y2, agg, cur), ())
            if kind === :ncap
                t, p = rest
                add!(e, x, VAR_NCAP(r, t, p))
            elseif kind === :net
                add!(e, x, VAR_COMNET(r, rest...))
            elseif kind === :prd
                add!(e, x, VAR_COMPRD(r, rest...))
            elseif kind === :flo
                t, p, c, s = rest
                for v in vintages[r, t, p]
                    if (r, p) in RP_IRE
                        for ie in rpc_ire[r, p, c]
                            add!(e, x, trade(m, r, v, t, p, c, s, ie))
                        end
                    else
                        add!(e, x, flow(m, r, v, t, p, c, s))
                    end
                end
            else
                add!(e, x, VAR_CUMCST(r, y1, y2, rest, cur))
            end
        end
        row!(m, :EQ_BNDCST, (r, y1, tt, y2, agg, cur), e, ==, VAR_CUMCST(r, y1, y2, agg, cur))
    end
end
