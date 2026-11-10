# SPDX-License-Identifier: GPL-3.0-or-later
# Storage: between timeslices (general and night storage), between periods, auxiliary flows, bounds on the storage flows.

"""
    EQ_STGTSS(r,v,t,p,s)                                                        eqstgtss.mod

Storage between timeslices: the level at the start of timeslice s is the level at the start of
the preceding timeslice ts, plus what was charged and less what was discharged in ts. The
timeslices of one parent form a cycle (RS_PREV), so no level has to be given.

    VAR_ACT(r,v,t,p,s)  =  VAR_ACT(r,v,t,p,ts)
                           + SUM(c charged,    VAR_SIN(r,v,t,p,c,ts)  / PRC_ACTFLO(r,v,p,c))
                           - SUM(c discharged, VAR_SOUT(r,v,t,p,c,ts) / PRC_ACTFLO(r,v,p,c))
                           - losses  +  STG_CHRG(r,t,p,ts)

Night storage (process type NST) is charged only in its storing timeslices (PRC_NSTTS) and
discharged only in the others; its flows may be defined above the timeslices of the level, and
then count with the share of ts:

                           + SUM((c, s2 at or above ts), frac(c,ts,s2) / PRC_ACTFLO *
                                 (VAR_SIN(r,v,t,p,c,s2) [s2 storing]  -  VAR_SOUT(r,v,t,p,c,s2) [s2 not storing]))

(for a commodity the storage both takes in and gives out, RPC_STGN reverses the rule for the output).

A storage working on several timeslice levels (RP_STS) passes a balance to the level above:

                           - RS_FR(r,ts,parent of s) * VAR_SOUT(r,v,t,p,ACT,parent of s)

Losses (STG_LOSS, per storage cycle of ts) are taken on the average of the two levels, L/2 of
each; a negative STG_LOSS is an equilibrium loss rate and gives the exact factors
1 + L/(1/EXP(L) - 1) on the level before and L/(EXP(L) - 1) - 1 on the level after.
"""
function eq_stgtss!(m::Model)
    (; RTP_VINTYR, RP_STG, RPS_STG, RPC_STG, RPC_STGN, RP_UPR, RP_STD, RP_STS, RTP, TOP, TS_MAP, PRC_TS, PRC_MAP, PRC_NSTTS, PRC_ACTFLO, RS_FR, STG_LOSS, STG_CHRG) = m.d
    (; rps_stg, ts_prev, stgtss_c, stg_c, rpcs_s, parent, ts_above) = m.ix
    (; VAR_ACT, VAR_SIN, VAR_SOUT) = m.v
    (; IN, OUT, NST, ACT) = m.K

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        (r, p) in RP_STG || continue
        nst = (r, NST, p) in PRC_MAP
        for s in rps_stg[r, p]
            before = AE()
            for ts in ts_prev[r, s]
                (r, p, ts) in RPS_STG || continue
                add!(before, 1.0, VAR_ACT(r, v, t, p, ts))
                if nst
                    for c in stg_c[r, p], s2 in onbranch(rpcs_s[r, p, c], ts_above[r, ts])
                        (r, s2, ts) in TS_MAP || continue
                        k = frac(m, r, t, c, ts, s2) / PRC_ACTFLO[r, v, p, c]
                        storing = (r, p, s2) in PRC_NSTTS
                        ((r, p, c, IN) in TOP && storing) && add!(before, k, VAR_SIN(r, v, t, p, c, s2))
                        ((r, p, c, OUT) in TOP && storing == ((r, p, c, OUT) in RPC_STGN)) && add!(before, -k, VAR_SOUT(r, v, t, p, c, s2))
                    end
                end
                for c in stgtss_c[r, p]
                    (r, p, c, IN) in TOP && add!(before, 1 / PRC_ACTFLO[r, v, p, c], VAR_SIN(r, v, t, p, c, ts))
                    (r, p, c, OUT) in TOP && add!(before, -1 / PRC_ACTFLO[r, v, p, c], VAR_SOUT(r, v, t, p, c, ts))
                end
                if (r, p) in RP_STS
                    for up in parent[r, s]
                        (r, p, up) in PRC_TS && add!(before, -RS_FR(r, ts, up), VAR_SOUT(r, v, t, p, ACT, up))
                    end
                end
                if has(STG_LOSS, r, v, p, ts)
                    l = plain(STG_LOSS(r, v, p, ts))
                    add!(before, -max(l / 2, l == 0 ? 0.0 : 1 + l / (1 / exp(l) - 1)), VAR_ACT(r, v, t, p, ts))
                    add!(before, -max(l / 2, l == 0 ? 0.0 : l / (exp(l) - 1) - 1), VAR_ACT(r, v, t, p, s))
                end
                add!(before, 1.0, plain(STG_CHRG(r, t, p, ts)))
            end
            row!(m, :EQ_STGTSS, (r, v, t, p, s), VAR_ACT(r, v, t, p, s), ==, before)
        end
    end
end

"""
    EQ_STGIPS(r,v,t,p,N)  and  EQ_STGIPS(r,t1,t1,p,IN)                           eqstgips.mod

Storage between periods (process type STK): the level at the end of period t is the level at the
end of the period before, less the losses of D(t) years, plus what was charged and less what was
discharged in the years of t, each year's flow carrying the losses to the end of the period.

    VAR_ACT(r,v,t,p,ANNUAL)  =  VAR_ACT(r,v,t-1,p,ANNUAL) * (1 - STG_LOSS)^D(t)
                                + SUM(c, (VAR_SIN(r,v,t,p,c,ANNUAL) - VAR_SOUT(r,v,t,p,c,ANNUAL)) / PRC_ACTFLO(r,v,p,c)
                                         * SUM(y in t and in the horizon, (1 - STG_LOSS)^(E(t) - y + 0.5)))

A process without vintages takes the level of the period before from the row v = t-1. The level
before the first period t1 is a variable filed under the year before t1; the row with the key IN
sets it to the exogenous charge:

    SUM(v, VAR_ACT(r,v,t1-1,p,ANNUAL))  =  STG_CHRG(r,t1-1,p,ANNUAL)
"""
function eq_stgips!(m::Model)
    (; RTP_VINTYR, PRC_MAP, PRC_VINT, MIYR_1, Y_EOH, TOP, STG_LOSS, STG_CHRG, PRC_ACTFLO, D, E, LEAD) = m.d
    (; stgips_c, vintages, period_y) = m.ix
    (; VAR_ACT, VAR_SIN, VAR_SOUT) = m.v
    (; IN, OUT, N, STK, ANNUAL) = m.K

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        ((r, STK, p) in PRC_MAP && !isempty(stgips_c[r, p])) || continue
        first = t in MIYR_1
        before_horizon = first ? id!(m.L, string(year(m.L, t) - round(Int, plain(LEAD(t))))) : t
        keep = 1 - plain(STG_LOSS(r, v, p, ANNUAL))

        e = AE()
        tt = previous(m, t)
        if tt !== nothing
            vv = (r, p) in PRC_VINT ? v : tt
            (r, vv, tt, p) in RTP_VINTYR && add!(e, keep^plain(D(t)), VAR_ACT(r, vv, tt, p, ANNUAL))
        else
            add!(e, keep^plain(D(t)), VAR_ACT(r, v, before_horizon, p, ANNUAL))
        end
        carried = sum(keep^(plain(E(t)) - year(m.L, y) + 0.5) for y in period_y[t] if y in Y_EOH; init = 0.0)
        for c in stgips_c[r, p]
            (r, p, c, IN) in TOP && add!(e, carried / PRC_ACTFLO[r, v, p, c], VAR_SIN(r, v, t, p, c, ANNUAL))
            (r, p, c, OUT) in TOP && add!(e, -carried / PRC_ACTFLO[r, v, p, c], VAR_SOUT(r, v, t, p, c, ANNUAL))
        end
        row!(m, :EQ_STGIPS, (r, v, t, p, N), VAR_ACT(r, v, t, p, ANNUAL), ==, e)

        if first && v in MIYR_1
            initial = AE()
            for k in vintages[r, t, p]
                add!(initial, 1.0, VAR_ACT(r, k, before_horizon, p, ANNUAL))
            end
            row!(m, :EQ_STGIPS, (r, v, t, p, IN), initial, ==, plain(STG_CHRG(r, before_horizon, p, ANNUAL)))
        end
    end
end

"""
    EQ_STGAUX(r,v,t,p,c,s)                                                      eqstgaux.mod

Auxiliary flows of a storage (commodities that are not stored themselves, such as emissions):
tied to the storage level through PRC_ACTFLO, and to what is charged or discharged through the
flow relations of the process (COEF_PTRAN).

    VAR_FLO(r,v,t,p,c,s)  =  PRC_ACTFLO(r,v,p,c) * G_YRFR(r,s) * SUM(ts at or above s, VAR_ACT(r,v,t,p,ts) / RS_STGPRD(r,ts))
                             + SUM((com charged, ts),    frac(c,s,ts) * COEF_PTRAN(com -> c) * VAR_SIN(r,v,t,p,com,ts))
                             + SUM((com discharged, ts), frac(c,s,ts) / COEF_PTRAN(c -> com) * VAR_SOUT(r,v,t,p,com,ts))

For a storage between periods the level meant is that of the middle of the period: the level at
its end, less the net charge of the second half of the period, and before the losses since then
(the two factors `late` and `mid` below). Night storage: only what is charged in the storing
timeslices and discharged in the others counts.
"""
function eq_stgaux!(m::Model)
    (; RTP_VINTYR, RP_STG, RPC_STG, RPC_EMIS, RPC_STGN, TOP, TS_MAP, COM_GMAP, RS_FR, PRC_ACTFLO, G_YRFR, RS_STGPRD, COEF_PTRAN,
        PRC_MAP, PRC_NSTTS, STG_LOSS, Y_EOH, M, D, E) = m.d
    (; rpc_c, rpcs_s, prc_ts, ptran, stgips_c, period_y, ts_above, ts_frac) = m.ix
    (; VAR_ACT, VAR_FLO, VAR_SIN, VAR_SOUT) = m.v
    (; IN, OUT, NST, STK, ANNUAL) = m.K
    # the commodities of each storage that have a flow variable (RPCS_VAR, the domain of eqstgaux.mod line 14): those of
    # its topology, and those tied only to its capacity (NCAP_ICOM / NCAP_OCOM / NCAP_COM, ppmain.mod line 663:
    # RPCS_VAR(RPC_NOFLO,ANNUAL) without an RPC entry)
    stg_c = Dict{Tuple{Id,Id},Vector{Id}}()
    for (r, p, c, s) in m.d.RPCS_VAR
        (r, p) in RP_STG || continue
        cs = get!(stg_c, (r, p), Id[])
        c in cs || push!(cs, c)
    end

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (r, p) in RP_STG || continue
        nst = (r, NST, p) in PRC_MAP
        stk = (r, STK, p) in PRC_MAP
        # storage between periods: from the level at the end of the period to the level at its middle
        keep = 1 - plain(STG_LOSS(r, v, p, ANNUAL))
        mt, dt, et = plain(M(t)), plain(D(t)), plain(E(t))
        tail = max(0.0, mt + dt / 2 - et)
        late = sum(min(1.0, year(m.L, y) - mt + tail) * keep^(et - year(m.L, y) + 0.5)
                   for y in period_y[t] if y in Y_EOH && year(m.L, y) >= mt; init = 0.0)
        mid = stk ? keep^(mt - et - min(0.5, tail)) : 1.0

        for c in get(stg_c, (r, p), Id[])
            # $(NOT RPC_STG(R,P,C)+RPC_EMIS(R,P,C)): NOT applies to the sum, so emissions tied to a flow are left out too
            ((r, p, c) in RPC_STG || (r, p, c) in RPC_EMIS) && continue
            for s in rpcs_s[r, p, c]
                e = AE()
                k = PRC_ACTFLO(r, v, p, c)
                if !iszero(k)
                    for ts in onbranch(prc_ts[r, p], ts_above[r, s])
                        (r, ts, s) in TS_MAP && add!(e, k * G_YRFR[r, s] / RS_STGPRD[r, ts] * mid, VAR_ACT(r, v, t, p, ts))
                    end
                    for com in stgips_c[r, p]
                        (r, p, com, IN) in TOP && add!(e, -k * late * mid / PRC_ACTFLO[r, v, p, com], VAR_SIN(r, v, t, p, com, ANNUAL))
                        (r, p, com, OUT) in TOP && add!(e, k * late * mid / PRC_ACTFLO[r, v, p, com], VAR_SOUT(r, v, t, p, com, ANNUAL))
                    end
                end
                # the entries at a timeslice on the branch of s (the charge: RS_FR(r,s,sl)) or at s itself (the discharge)
                rel = s in ts_frac[r, s] ? ts_frac[r, s] : push!(copy(ts_frac[r, s]), s)
                for (cg, a, b, sl) in onbranch(ptran[r, v, p], rel, 4)
                    coef = COEF_PTRAN(r, v, p, cg, a, b, sl)
                    iszero(coef) && continue
                    if b == c && (r, cg, a) in COM_GMAP && (r, p, a) in RPC_STG && (r, p, a, IN) in TOP          # a is charged; flow relation a -> c
                        ts = sl
                        ((r, p, a, ts) in m.d.RPCS_VAR && has(RS_FR, r, s, ts) && (!nst || (r, p, ts) in PRC_NSTTS)) &&
                            add!(e, coef * frac(m, r, t, c, s, ts), VAR_SIN(r, v, t, p, a, ts))
                    end
                    if a == c && sl == s && (r, cg, c) in COM_GMAP && (r, p, b) in RPC_STG && (r, p, b, OUT) in TOP    # c -> b discharged
                        for ts in onbranch(rpcs_s[r, p, b], ts_frac[r, s])
                            (has(RS_FR, r, s, ts) && ((r, p, ts) in PRC_NSTTS) == ((r, p, b, OUT) in RPC_STGN)) &&
                                add!(e, frac(m, r, t, c, s, ts) / coef, VAR_SOUT(r, v, t, p, b, ts))
                        end
                    end
                end
                row!(m, :EQ_STGAUX, (r, v, t, p, c, s), VAR_FLO(r, v, t, p, c, s), ==, e)
            end
        end
    end
end

"""
    EQG_STGIN / EQE_STGIN / EQL_STGIN (r,t,p,c,s)  and  ..._STGOUT              eqstgflo.mod

Bound on what a storage charges (STGIN_BND) or discharges (STGOUT_BND) of commodity c in timeslice
s, where the bound cannot be put on the variable: the process is vintaged, or the bound is given
above the timeslices of the flow.

    SUM((v, ts), frac(c,s,ts) * VAR_SIN(r,v,t,p,c,ts))  <=  STGIN_BND(r,t,p,c,s,UP)

Night storage: the charge counts in the storing timeslices only, the discharge in the others.
"""
function eq_stgflo!(m::Model)
    (; STGIN_BND, STGOUT_BND, RTPC, PRC_VINT, RPCS_VAR, RPS_PRCTS, RPC_STG, PRC_MAP, PRC_NSTTS, RS_FR) = m.d
    (; rpcs_s, vintages, ts_frac) = m.ix
    (; VAR_SIN, VAR_SOUT) = m.v
    (; LO, UP, FX, NST) = m.K

    for (stem, BND, VAR, charge) in (("STGIN", STGIN_BND, VAR_SIN, true), ("STGOUT", STGOUT_BND, VAR_SOUT, false))
        kind = by_bound(m, stem)
        for ((r, t, p, c, s, bd), bound) in BND
            ((r, t, p, c) in RTPC && (r, p, s) in RPS_PRCTS && (r, p, c) in RPC_STG) || continue
            ((r, p) in PRC_VINT || !((r, p, c, s) in RPCS_VAR)) || continue
            bd in (LO, UP, FX) || continue
            (bd == LO && plain(bound) == 0) && continue          # no row for a bound that does not bind
            (bd == UP && bound == Inf) && continue
            nst = (r, NST, p) in PRC_MAP
            e = AE()
            for ts in onbranch(rpcs_s[r, p, c], ts_frac[r, s])
                has(RS_FR, r, s, ts) || continue
                storing = (r, p, ts) in PRC_NSTTS
                (charge ? (!nst || storing) : !storing) || continue
                for v in vintages[r, t, p]
                    add!(e, frac(m, r, t, c, s, ts), VAR(r, v, t, p, c, ts))
                end
            end
            name, sense = kind(bd)
            row!(m, name, (r, t, p, c, s), e, sense, plain(bound))
        end
    end
end


"""
    EQL_STGCCL (r,v,t,p)                                                         eqactups.vda

Storage cycle limit (STG_MAXCYC): the discharge over the lifetime may not exceed the limit times
the storage capacity, unless replacement capacity is bought: VAR_UPS(r,v,t,p,ANNUAL,UP), which
costs the investment annuity (ACT_CSTUP on ANNUAL, set by the preprocessor).

    (capacity behind (v,p) in t  +  VAR_UPS(ANNUAL,UP)) / exp(PRC_SC) * max(s, COEF_AFUPS(r,v,p,s)) * PRC_CAPACT
        >=  SUM(c discharged, SUM(s, VAR_SOUT(r,v,t,p,c,s) / PRC_ACTFLO(r,v,p,c))) * NCAP_TLIFE / STG_MAXCYC
"""
function eq_stgccl!(m::Model)
    (; RTP_VINTYR, RP_STG, RPC_STG, RPS_STG, TOP, COEF_AFUPS, STG_MAXCYC, PRC_SC, PRC_CAPACT, PRC_ACTFLO, NCAP_TLIFE) = m.d
    (; rpcs_s, stg_c, rps_stg) = m.ix
    (; VAR_UPS, VAR_SOUT) = m.v
    (; ANNUAL, UP, OUT) = m.K
    one = id!(m.L, "1")

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        ((r, p) in RP_STG && has(STG_MAXCYC, r, v, p)) || continue
        af = maximum((plain(COEF_AFUPS(r, v, p, s)) for s in rps_stg[r, p] if has(COEF_AFUPS, r, v, p, s)); init = 0.0)
        af > 0 || continue
        # (%MX% + VAR_UPS(ANNUAL,UP)): the capacity behind (v, p) in t, all vintages k of RVP_KMAP weighted by COEF_VNT
        # (VAR_NCAP for a milestone vintage, NCAP_PASTI for a past one, less what is retired), plus the replacement capacity
        cap = AE()
        for k in m.ix.kmap[r, v, p]
            w = m.d.COEF_VNT(r, t, p, k)
            iszero(w) || add!(cap, w, dispatch_standing(m, r, k, t, p))
        end
        add!(cap, 1.0, VAR_UPS(r, v, t, p, ANNUAL, UP))
        lhs = AE()
        add!(lhs, af * PRC_CAPACT[r, p] / exp(plain(PRC_SC(r, p))), cap)
        k = plain(NCAP_TLIFE[r, v, p]) / plain(STG_MAXCYC[r, v, p])
        for c in stg_c[r, p]
            (r, p, c, OUT) in TOP || continue
            for s in rpcs_s[r, p, c]
                add!(lhs, -k / PRC_ACTFLO[r, v, p, c], VAR_SOUT(r, v, t, p, c, s))
            end
        end
        row!(m, :EQL_STGCCL, (r, v, t, p, one), lhs, GE, 0.0)   # the last index is the state of the world, '1' (%SWX%)
    end
end

"""
    EQ_STSBAL(r,v,t,p,tsl,s,N)                                                   eqstgtss.mod

General-level balance of a timeslice storage working on several timeslice levels (RP_STS), for
the levels tsl of RP_STL (those above the level of its PRC_TS: ppmain sets RP_STL(..,tsl,'N')
for every level up to PRC_SGL). In each timeslice s of tsl the level of the storage follows from
the level in the timeslice sl before s (RS_PREV), plus the balancer flow of s, minus the share of
sl in the balancer flow passed on to the parent of s, minus losses:

    VAR_ACT(r,v,t,p,s)  =  VAR_ACT(r,v,t,p,sl)  +  VAR_SOUT(r,v,t,p,ACT,sl)
                           - SUM(ts parent of s, PRC_TS(r,p,ts), VAR_SOUT(r,v,t,p,ACT,ts) * RS_FR(r,sl,ts))
                           - losses (as in EQ_STGTSS, STG_LOSS of sl, only when sl is not s)

and for s = ANNUAL (never reached by ppmain, which starts RP_STL one level below ANNUAL):

                        +  SUM(c in PRC_STGIPS, VAR_SIN(r,v,t,p,c,ANNUAL) / PRC_ACTFLO   [c an input]
                                                - VAR_SOUT(r,v,t,p,c,ANNUAL)              [c an output])
                           - VAR_SOUT(r,v,t,p,ACT,ANNUAL)

The terms on RP_STL(..,UP), VAR_UDP and the bound types LO/UP/FX belong to flexible storage levels
(run switch STSFLX), which the preprocessor does not accept: only N rows can be present.
"""
function eq_stsbal!(m::Model)
    (; RTP_VINTYR, RP_STS, PRC_TS, TS_GROUP, TOP, PRC_ACTFLO, RS_FR, STG_LOSS) = m.d
    (; stl_lv, ts_group, ts_prev, parent, stgips_c) = m.ix
    (; VAR_ACT, VAR_SIN, VAR_SOUT) = m.v
    (; IN, OUT, ACT, ANNUAL, N) = m.K

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (r, p) in RP_STS || continue
        for (tsl, l) in stl_lv[r, p]
            l == N || error("TIMES feature not supported yet: flexible storage levels (STSFLX), RP_STL bound type $(label(m.L, l)) on $(label(m.L, p))")
            for s in ts_group[r, tsl]
                (r, p, s) in PRC_TS || continue
                lhs = AE(); rhs = AE()
                if s == ANNUAL
                    for c in stgips_c[r, p]
                        (r, p, c, IN) in TOP && add!(rhs, 1 / PRC_ACTFLO[r, v, p, c], VAR_SIN(r, v, t, p, c, s))
                        (r, p, c, OUT) in TOP && add!(rhs, -1.0, VAR_SOUT(r, v, t, p, c, s))
                    end
                    add!(rhs, -1.0, VAR_SOUT(r, v, t, p, ACT, s))
                else
                    add!(lhs, 1.0, VAR_ACT(r, v, t, p, s))
                    for sl in ts_prev[r, s]
                        add!(rhs, 1.0, VAR_ACT(r, v, t, p, sl))
                        add!(rhs, 1.0, VAR_SOUT(r, v, t, p, ACT, sl))
                        for up in parent[r, s]
                            (r, p, up) in PRC_TS && add!(rhs, -RS_FR(r, sl, up), VAR_SOUT(r, v, t, p, ACT, up))
                        end
                        if sl != s && has(STG_LOSS, r, v, p, sl)     # RS_STG(r,s) is 0 only when s is alone in its cycle
                            x = plain(STG_LOSS(r, v, p, sl))
                            add!(rhs, -max(x / 2, x == 0 ? 0.0 : 1 + x / (1 / exp(x) - 1)), VAR_ACT(r, v, t, p, sl))
                            add!(rhs, -max(x / 2, x == 0 ? 0.0 : x / (exp(x) - 1) - 1), VAR_ACT(r, v, t, p, s))
                        end
                    end
                end
                row!(m, :EQ_STSBAL, (r, v, t, p, tsl, s, l), lhs, ==, rhs)
            end
        end
    end
end
