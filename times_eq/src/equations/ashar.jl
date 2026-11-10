# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_ASHAR / EQE_ASHAR / EQG_ASHAR (r,v,t,p,cg,cg2,s)                        eqashar.vda

Share of the flows of group cg in the flows of a reference group cg2 of the same process, over
timeslice s (FLO_ASHAR; unlike FLO_SHAR the two groups may lie on different sides, and the
reference may be the activity, cg2 = ACT).

    SUM(sl below s, FLO_ASHAR(r,v,p,cg,cg2,sl,LO) * (flows of cg2 at sl))  <=  flows of cg at s

`>=` for an upper and `=` for a fixed share. The share is given at sl or for the year.
When cg2 is a commodity type, only the flows on the side of cg count (RPCG_ASHAR = -1).
"""
eq_ashar!(m::Model) = _eq_ashar!(m, exprtype())

function _eq_ashar!(m::Model, ::Type{E}) where {E}
    (; FLO_ASHAR, RPCG_ASHAR, RTP_VINTYR, RS_TREE, TS_MAP, RP_FLO, RP_IRE, RP_STG, RPC_STG, RP_STD, RP_PGFLO, RP_PGACT, RTP_VARA,
        COM, COM_TYPE, COM_GMAP, TOP, RS_FR, PRC_ACTFLO, RPC_IRE, REG) = m.d
    (; ts_tree, rps_s2, ts_ann, flow_cs, flow_s, prc_ts, pcg, rpcs_s, vintages, ts_below, ts_frac) = m.ix
    (; VAR_ACT, VAR_FLO, VAR_SOUT) = m.v
    (; IN, OUT, ACT, LO, UP, FX, IMP, EXP, ANNUAL) = m.K
    kind = by_bound(m, "ASHAR"; share = true)
    walked = Set{NTuple{5,Id}}()        # (r, v, t, p, cg) whose storage output has been walked over all its timeslices

    for ((r, p, cg, cg2, s), mode) in RPCG_ASHAR
        # the side(s) of the process on which cg lies, when the reference is a commodity type
        sides = (cg in COM && cg2 in COM_TYPE) ? Tuple(io for io in (IN, OUT) if (r, p, cg, io) in TOP) : ()

        for t in m.T, v in vintages[r, t, p], bd in (LO, UP, FX)
            (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
            any(has(FLO_ASHAR, r, v, p, cg, cg2, ts, bd) for ts in ts_tree[r, s]) || continue

            reference = E()
            if (r, p) in RP_FLO
                for sl in onbranch(rps_s2[r, p], ts_below[r, s])
                    (r, s, sl) in TS_MAP || continue
                    share = sum(FLO_ASHAR(r, v, p, cg, cg2, ts, bd) for ts in ts_ann[sl]; init = 0.0)
                    iszero(share) && continue
                    for (com, ts) in onbranch(flow_cs[r, t, p], ts_tree[r, sl], 2)
                        ((r, cg2, com) in COM_GMAP && (r, sl, ts) in RS_TREE) || continue
                        w = max(mode, any((r, p, com, io) in TOP for io in sides) ? 1.0 : 0.0)
                        add!(reference, share * w * frac(m, r, t, com, sl, ts), flow(E, m, r, v, t, p, com, ts))
                    end
                    if cg2 == ACT && (r, t, p) in RTP_VARA
                        for ts in onbranch(prc_ts[r, p], ts_frac[r, sl])
                            fr = RS_FR(r, sl, ts)
                            iszero(fr) && continue
                            if !((r, p) in RP_PGFLO)
                                # the activity of a storage counts less its losses over half a cycle (eqashar.vda line 51:
                                #   VAR_ACT*EXP((-ABS(STG_LOSS(R,V,P,TS))/2)$RP_STG(R,P)))
                                loss = (r, p) in RP_STG ? exp(-abs(plain(m.d.STG_LOSS(r, v, p, ts))) / 2) : 1.0
                                add!(reference, share * fr * loss, VAR_ACT(r, v, t, p, ts))
                            elseif (r, p) in RP_STD
                                # the outer RS_FR of line 50 multiplies only the term above: this one, after the `+` of
                                # line 51, carries its own RS_FR*(1+RTCS_FR) (line 53) and nothing more (as GAMS has
                                # it on a model of 19 M rows)
                                for com in pcg[r, p]
                                    k = share * frac(m, r, t, com, sl, ts)
                                    (r, p) in RP_PGACT ? add!(reference, k, VAR_ACT(r, v, t, p, ts)) :
                                                         add!(reference, k / PRC_ACTFLO[r, v, p, com], VAR_FLO(r, v, t, p, com, ts))
                                end
                            end
                        end
                    end
                end
            end
            if (r, p) in RP_IRE && s == ANNUAL
                # eqashar.vda 57-65, a trade process (ANNUAL only): for each trade flow (com, ie) of cg (in the direction
                # cg2 names, when cg2 is IMP or EXP), FLO_ASHAR times the process's flows of cg2 in that direction in
                # every region (REG is free in line 60), plus its activity when cg2 is ACT, less the flow itself
                share = FLO_ASHAR(r, v, p, cg, cg2, s, bd)
                for (r1, p1, com, ie) in RPC_IRE
                    (r1 == r && p1 == p && (r, cg, com) in COM_GMAP && (!(cg2 == IMP || cg2 == EXP) || ie == cg2)) || continue
                    if !iszero(share)
                        for (r2, p2, c2, ie2) in RPC_IRE
                            (p2 == p && ie2 == ie && r2 in REG && ((r2, cg2, c2) in COM_GMAP || cg2 == IMP || cg2 == EXP)) || continue
                            for ts in flow_s[r2, t, p, c2]
                                add!(reference, share, trade(m, r2, v, t, p, c2, ts, ie))
                            end
                        end
                        if cg2 == ACT
                            for ts in prc_ts[r, p]
                                add!(reference, share, VAR_ACT(r, v, t, p, ts))
                            end
                        end
                    end
                    for ts in flow_s[r, t, p, com]
                        add!(reference, -1.0, trade(m, r, v, t, p, com, ts, ie))
                    end
                end
            end

            flows = E()
            if (r, p) in RP_FLO
                for (com, ts) in onbranch(flow_cs[r, t, p], ts_below[r, s], 2)
                    ((r, cg, com) in COM_GMAP && (r, s, ts) in TS_MAP) && add!(flows, 1.0, flow(E, m, r, v, t, p, com, ts))
                end
            end
            if cg == ACT
                # SUM(PRC_TS(R,P,TS)$TS_MAP(R,S,TS),VAR_ACT(R,V,T,P,TS)$(NOT NO_ACT(R,P))+
                #   SUM(RPC_PG(NO_ACT(R,P),C),VAR_FLO(R,V,T,P,C,TS)/PRC_ACTFLO(R,V,P,C)))   (NO_ACT: REDUCE YES)
                noact = (r, p) in m.d.NO_ACT
                for ts in onbranch(prc_ts[r, p], ts_below[r, s])
                    (r, s, ts) in TS_MAP || continue
                    if !noact
                        add!(flows, 1.0, VAR_ACT(r, v, t, p, ts))
                    else
                        for c in m.ix.pcg[r, p]
                            add!(flows, 1.0 / PRC_ACTFLO[r, v, p, c], VAR_FLO(r, v, t, p, c, ts))
                        end
                    end
                end
            end
            if cg2 == ACT && (r, p) in RP_STG && cg in COM && (r, p, cg) in RPC_STG && (r, p, cg, OUT) in TOP
                # every timeslice the first time (the variables are created in that order, as before; a term of a
                # timeslice off the branch of s has a coefficient of zero and is dropped by row!), then those on the branch
                first = !((r, v, t, p, cg) in walked)
                first && push!(walked, (r, v, t, p, cg))
                for ts in (first ? rpcs_s[r, p, cg] : onbranch(rpcs_s[r, p, cg], ts_frac[r, s]))
                    add!(flows, frac(m, r, t, cg, s, ts) / PRC_ACTFLO[r, v, p, cg], VAR_SOUT(r, v, t, p, cg, ts))
                end
            end

            name, sense = kind(bd)
            row!(m, name, (r, v, t, p, cg, cg2, s), reference, sense, flows)
        end
    end
end
