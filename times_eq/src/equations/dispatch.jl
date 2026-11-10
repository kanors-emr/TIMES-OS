# SPDX-License-Identifier: GPL-3.0-or-later
# Dispatchable processes (eqactups.vda): a minimum stable load (ACT_MINLD, ACT_UPS FX) and ramp rates (ACT_UPS LO / UP).
#
# Part of the capacity of such a process may be off line in a season (or in the year, for a process working on
# seasons): VAR_UPS(r,v,t,p,s,N), on the timeslices s directly above those of the process (RPS_UPS). What is on
# line must run between the minimum load and the availability, and may change its load from one timeslice to the
# next by no more than the ramp rate allows.
#
# With a start-up cost (ACT_CSTUP) on a level above ANNUAL, the capacity started up and shut down is counted on that
# level (EQE/EQL_ACTUPS), minimum on-line and off-line times apply (EQL_ACTUPC), and the start-ups cost money (EQ_OBJVAR).
# Not written: partial-load efficiencies (EQ_ACTPL) and start-up types (eqlducs.vda). `build` stops when the input has them.

"""
Capacity of (v, p) installed in year k and still standing in t, as eqactups.vda writes it:

    VAR_NCAP(r,k,p) [k a milestone year]  +  NCAP_PASTI(r,k,p)  -  VAR_SCAP(r,k,t,p) [retirable, k before t]
"""
function dispatch_standing(m::Model, r, k, t, p)
    e = AE(plain(m.d.NCAP_PASTI(r, k, p)))
    new_capacity(m, k) && JuMP.add_to_expression!(e, 1.0, m.v.VAR_NCAP(r, k, p))
    ((r, p) in m.d.PRC_RCAP && (k, t) in m.d.VNTRT) && JuMP.add_to_expression!(e, -1.0, m.v.VAR_SCAP(r, k, t, p))
    return e
end

"""
Capacity off line in timeslice s: that of the timeslices at or above s which carry it.

    SUM(ts at or above s [RPS_UPS(r,p,ts)], VAR_UPS(r,v,t,p,ts,N))
"""
function offline(m::Model, r, v, t, p, s)
    e = AE()
    for ts in onbranch(m.ix.ups_ts[r, p], m.ix.ts_above[r, s])
        (r, ts, s) in m.d.TS_MAP && add!(e, 1.0, m.v.VAR_UPS(r, v, t, p, ts, m.K.N))
    end
    return e
end

"""
Capacity of (v, p) in t as the on-line balance sees it (%CAPON%): `COEF_CPT * standing(v)` for a vintaged process,
`VAR_CAP(r,t,p)` otherwise.
"""
function capon(m::Model, r, v, t, p)
    e = AE()
    (r, p) in m.d.PRC_VINT && add!(e, m.d.COEF_CPT(r, v, t, p), dispatch_standing(m, r, v, t, p))
    (r, p) in m.d.RP_UX && add!(e, 1.0, m.v.VAR_CAP(r, t, p))
    return e
end

"""
Capacity behind (v, p) in t for the ramp and start-up rows (%MX%%TMP%): all vintages k of RVP_KMAP weighted by
COEF_VNT for a vintaged process, `VAR_CAP(r,t,p)` otherwise.
"""
function capacity_mx(m::Model, r, v, t, p)
    e = AE()
    if (r, p) in m.d.RP_UX
        add!(e, 1.0, m.v.VAR_CAP(r, t, p))
    else
        for k in m.ix.kmap[r, v, p]
            w = m.d.COEF_VNT(r, t, p, k)
            iszero(w) || add!(e, w, dispatch_standing(m, r, k, t, p))
        end
    end
    return e
end

"""
    EQ_CAPLOAD(r,v,t,p,s,bd)                                                     eqactups.vda

Load of a dispatchable process, in the timeslices where it takes the place of the availability row (AFUPS):

    LO:  VAR_ACT(r,v,t,p,s)  >=  on line * MIN(COEF_AF(UP), minimum load) * PRC_CAPACT * G_YRFR(r,s)
    UP:  VAR_ACT(r,v,t,p,s)  <=  on line * COEF_AF(r,v,t,p,s,UP)          * PRC_CAPACT * G_YRFR(r,s)

    on line  =  capacity - capacity off line in s
    capacity =  COEF_CPT(r,v,t,p) * standing(v)  for a vintaged process,  VAR_CAP(r,t,p)  otherwise (RP_UX)

The minimum load is ACT_UPS(r,v,p,s,FX) + ACT_UPS(r,v,p,ANNUAL,FX). Both rows are written as `>=`, the upper one
with the signs reversed, as TIMES does.
"""
function eq_capload!(m::Model)
    (; RTP_VINTYR, AFUPS, PRC_VINT, RP_UX, COEF_AF, COEF_CPT, ACT_UPS, PRC_CAPACT, G_YRFR, RTP_PL) = m.d
    (; afups, ts_ann) = m.ix
    (; VAR_ACT, VAR_CAP, VAR_UPS) = m.v
    (; LO, UP, FX) = m.K
    isempty(AFUPS) && return
    # (availability by commodity on a dispatchable process: the off-line term is in EQ_CAFLAC / EQL_CAPFLO, caflac.jl)

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        isempty(afups[r, t, p]) && continue
        for s in afups[r, t, p]
            online = capon(m, r, v, t, p)
            add!(online, -1.0, offline(m, r, v, t, p, s))
            unit = PRC_CAPACT[r, p] * G_YRFR[r, s]
            af = plain(afmx(m, COEF_AF(r, v, t, p, s, UP), r, t, p, s))      # COEF_AF%1: COEF_AFMX (equ_ext.vda 90)
            # a partial-load vintage whose losses start at the minimum load (RTP_PL): the minimum load is in VAR_UPS(s,FX)
            # instead (eqactups.vda 42-45: VAR_UPS(..,'FX')$RTP_PL, and SUM(TS_ANN(S,TS)$(NOT RTP_PL),ACT_UPS(..,'FX')))
            pl = (r, v, p) in RTP_PL
            minld = pl ? 0.0 : sum(plain(ACT_UPS(r, v, p, ts, FX)) for ts in ts_ann[s]; init = 0.0)
            # MIN(COEF_AF(..,'UP')*BDSIG(BD),SUM(TS_ANN(S,TS),ACT_UPS(R,V,P,TS,'FX'))$BDLOX(BD)) with the EPS of GAMS: a MIN
            # that comes out 0 is EPS when COEF_AF is EPS (an availability given as 0, e.g. NCAP_AF 0; -EPS is EPS, and
            # MIN(EPS,0) is EPS), or when COEF_AF is positive and the minimum load is EPS (ACT_MINLD 0 under $ONEPS); the row
            # then keeps an EPS coefficient on every capacity term, the values themselves are those of before (x + EPS is x).
            # Not for RTP_PL on LO: its SUM is empty.
            af_eps = iseps(COEF_AF(r, v, t, p, s, UP))
            lo = min(af, minld)
            if !pl && iszero(lo)
                ld_eps = iszero(minld) && any(ts -> iseps(ACT_UPS(r, v, p, ts, FX)), ts_ann[s])
                (af_eps || (af > 0 && ld_eps)) && (lo = EPS)
            end
            up = af_eps ? EPS : min(-af, 0.0)
            lower = lo * unit * online
            pl && add!(lower, 1.0, VAR_UPS(r, v, t, p, s, FX))
            row!(m, :EQ_CAPLOAD, (r, v, t, p, s, LO), VAR_ACT(r, v, t, p, s), >=, lower)
            row!(m, :EQ_CAPLOAD, (r, v, t, p, s, UP), -1.0 * VAR_ACT(r, v, t, p, s), >=, up * unit * online)
        end
    end
end

"""
    EQ_ACTRAMP(r,v,t,p,s,bd)                                                     eqactups.vda

Ramp limits between a timeslice s of the process and the one before it in the cycle (ts), for bd = LO (down)
and UP (up), where a ramp rate is given (ACT_UPS(r,v,p,s,bd) + ACT_UPS(r,v,p,ANNUAL,bd), share of capacity per hour):

    PRC_CAPACT * rate * (on line in s  [+ off line(s) - off line(ts), bd = LO, s carrying off-line capacity])
      + sig(bd) * RS_STGPRD(r,s) * 2 / (G_YRFR(r,s) + G_YRFR(r,ts)) / 8760
          * (VAR_ACT(s) / G_YRFR(r,s) - VAR_ACT(ts) / G_YRFR(r,ts)
             [+ (off line(s) - off line(ts)) * PRC_CAPACT * ACT_MINLD, s carrying off-line capacity])   >=  0

sig = +1 for LO, -1 for UP. The second factor is the hours between the mid-points of the two timeslices in one
cycle; the load is VAR_ACT / G_YRFR. On line: all vintages behind (v, p) for a vintaged process (RVP_KMAP),
VAR_CAP otherwise, less the capacity off line in s. The row is written for every period of the vintage,
also where the activity is switched off.
"""
function eq_actramp!(m::Model)
    (; RTP_VINTYR, RP_UPL, RP_UX, RPS_UPS, PRC_TS, ACT_UPS, ACT_MINLD, PRC_CAPACT, G_YRFR, RS_STGPRD, COEF_VNT) = m.d
    (; prc_ts, ts_ann, ts_prev, kmap) = m.ix
    (; VAR_ACT, VAR_CAP, VAR_UPS) = m.v
    (; LO, UP, N) = m.K
    isempty(RP_UPL) && return

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        ((r, p, LO) in RP_UPL || (r, p, UP) in RP_UPL) || continue
        for s in prc_ts[r, p], (bd, sig) in ((LO, 1.0), (UP, -1.0))
            ((r, p, bd) in RP_UPL && any(ts -> has(ACT_UPS, r, v, p, ts, bd), ts_ann[s])) || continue
            # PRC_CAPACT(R,P)*SUM(TS_ANN(S,SL),ACT_UPS(R,V,P,SL,BD)) * (%MX%%TMP% + ...): an ACT_UPS given as EPS makes the
            # rate EPS, and GAMS keeps an EPS entry on each column of the on-line capacity (EPS + x is x: a value stays)
            rate = PRC_CAPACT[r, p] * sum(ACT_UPS(r, v, p, sl, bd) for sl in ts_ann[s]; init = 0.0)
            carries = (r, p, s) in RPS_UPS
            e = AE()
            for ts in ts_prev[r, s]
                (r, p, ts) in PRC_TS || continue
                add!(e, rate, capacity_mx(m, r, v, t, p))
                add!(e, -rate, offline(m, r, v, t, p, s))
                hours = RS_STGPRD[r, s] * 2 / (G_YRFR[r, s] + G_YRFR[r, ts]) / 8760 * sig
                add!(e, hours / G_YRFR[r, s], VAR_ACT(r, v, t, p, s))
                add!(e, -hours / G_YRFR[r, ts], VAR_ACT(r, v, t, p, ts))
                if carries
                    k = (bd == LO ? rate : 0.0) + hours * PRC_CAPACT[r, p] * plain(ACT_MINLD(r, v, p))
                    add!(e, k, VAR_UPS(r, v, t, p, s, N))
                    add!(e, -k, VAR_UPS(r, v, t, p, ts, N))
                    # ((VAR_UPS(S,'N')-VAR_UPS(TS,'N'))*PRC_CAPACT*ACT_MINLD)$RPS_UPS with ACT_MINLD EPS (a minimum load given
                    # as 0 under $ONEPS): the term is EPS, and GAMS keeps an EPS entry on both columns where the rest of the
                    # row cancels (rate*VAR_UPS(S,'N') against the off-line capacity of %MX%); a value is not changed by it
                    if iseps(ACT_MINLD(r, v, p))
                        add!(e, hours * PRC_CAPACT[r, p] * EPS, VAR_UPS(r, v, t, p, s, N))
                        add!(e, -hours * PRC_CAPACT[r, p] * EPS, VAR_UPS(r, v, t, p, ts, N))
                    end
                end
            end
            row!(m, :EQ_ACTRAMP, (r, v, t, p, s, bd), e, >=, 0.0)
        end
    end
end

"""
    EQ_ACTRMPC(r,v,t,p,ts)                                                       eqactups.vda 113-117

The change of load of a standard process with ramping costs (RP_UPR, from ACT_CSTRMP) between a timeslice s of the
process and the one before it in the cycle, ts (the row is filed under ts: TS(S--RS_STG(R,S))), split into ramping
up and down, which the objective charges (eqobjvar.mod 39):

    (VAR_ACT(ts) / G_YRFR(r,ts) - VAR_ACT(s) / G_YRFR(r,s)) / PRC_CAPACT
        =  VAR_UDP(s,LO) - VAR_UDP(s,UP)  -  ACT_MINLD * (off line(ts) - off line(s))   [s carrying off-line capacity]
"""
function eq_actrmpc!(m::Model)
    (; RTP_VINTYR, RP_UPR, RP_STD, RPS_UPS, ACT_MINLD, PRC_CAPACT, G_YRFR) = m.d
    (; prc_ts, ts_prev) = m.ix
    (; VAR_ACT, VAR_UDP, VAR_UPS) = m.v
    (; LO, UP, N) = m.K
    isempty(RP_UPR) && return
    costed = Set((r, p) for (r, p, _) in RP_UPR)

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        ((r, p) in costed && (r, p) in RP_STD) || continue
        cap = plain(PRC_CAPACT[r, p])
        for s in prc_ts[r, p], ts in ts_prev[r, s]
            change = AE()
            add!(change, 1 / G_YRFR[r, ts] / cap, VAR_ACT(r, v, t, p, ts))
            add!(change, -1 / G_YRFR[r, s] / cap, VAR_ACT(r, v, t, p, s))
            ramps = AE()
            add!(ramps, 1.0, VAR_UDP(r, v, t, p, s, LO))       # BDSIG(LO) = 1
            add!(ramps, -1.0, VAR_UDP(r, v, t, p, s, UP))      # BDSIG(UP) = -1
            if (r, p, s) in RPS_UPS
                # -ACT_MINLD(R,V,P)*(%VAR%_UPS(R,V,T,P,TS,'N'%SOW%)-%VAR%_UPS(R,V,T,P,S,'N'%SOW%))$RPS_UPS(R,P,S):
                # a minimum load given as EPS leaves an EPS entry on both columns
                k = ACT_MINLD(r, v, p)
                add!(ramps, -k, VAR_UPS(r, v, t, p, ts, N))
                add!(ramps, k, VAR_UPS(r, v, t, p, s, N))
            end
            row!(m, :EQ_ACTRMPC, (r, v, t, p, ts), change, ==, ramps)
        end
    end
end

"""
    EQ_ACTPL(r,v,t,p,s)                                                          eqactups.vda 99-109

The load below which a process with partial loads (RP_PL N) runs with losses, in VAR_UPS(s,FX), from the capacity on
line and the activity (LO, UP: the loads at which the losses start and end, ACT_LOSPL):

    VAR_UPS(s,FX)  >=  (on line * PRC_CAPACT * G_YRFR(s) * (UP + LO*(1-UP)) - VAR_ACT(s)) / (UP * (1/LO - 1))

On line as in EQ_ACTRAMP (%MX%%TMP%). (The shut-down part of the row, DP_UNS with ACT_CSTSD, is not written: the
port stops on ACT_CSTSD.)
"""
function eq_actpl!(m::Model)
    (; RTP_VINTYR, RP_PL, ACT_LOSPL, PRC_CAPACT, G_YRFR) = m.d
    (; prc_ts) = m.ix
    (; VAR_ACT, VAR_UPS) = m.v
    (; LO, UP, FX, N) = m.K
    any(k -> k[3] == N, RP_PL) || return

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        (r, p, N) in RP_PL || continue
        up, lo = plain(ACT_LOSPL(r, v, p, UP)), plain(ACT_LOSPL(r, v, p, LO))
        d = up * (1 / lo - 1)
        for s in prc_ts[r, p]
            k = PRC_CAPACT[r, p] * G_YRFR[r, s] * (up + lo * (1 - up)) / d
            losses = AE()
            add!(losses, k, capacity_mx(m, r, v, t, p))
            add!(losses, -k, offline(m, r, v, t, p, s))
            add!(losses, -1 / d, VAR_ACT(r, v, t, p, s))
            row!(m, :EQ_ACTPL, (r, v, t, p, s), VAR_UPS(r, v, t, p, s, FX), >=, losses)
        end
    end
end

"""
    EQE_ACTUPS / EQL_ACTUPS(r,v,t,p,tsl,l,s)                                     eqactups.vda

The balance of on-line capacity, for the levels and kinds that RP_UPS names (s a timeslice of level tsl):

    EQE, l = UP (the start-up level):  off line(s) - off line(ts) = shut down(s) - started up(s)
             VAR_UPS(s,N) - VAR_UPS(ts,N) - VAR_UPS(s,LO) + VAR_UPS(s,UP) = 0          (ts the timeslice before s)
    EQE, l = FX (the level above):     VAR_UPS(s,FX) + VAR_UDP(s,FX) = capacity - off line(s)
    EQL, l = FX:                       VAR_UPS(s,FX) <= SUM(ts directly below s, VAR_UPS(ts,UP))
    EQL, l = N:                        VAR_UPS(s,N)  <= VAR_UPS(parent of s, FX)

Capacity as in EQ_ACTRAMP (%MX%%TMP%).
"""
function eq_actups!(m::Model)
    (; RTP_VINTYR, RP_UPL, RP_UPS, RP_PL) = m.d
    (; ups_lv, ts_group, ts_prev, children, parent, prc_ts) = m.ix
    (; VAR_UPS, VAR_UDP) = m.v
    (; ANNUAL, LO, UP, FX, N) = m.K
    isempty(RP_UPS) && return

    for (r, v, t, p) in RTP_VINTYR, (tsl, l) in ups_lv[r, p], s in ts_group[r, tsl]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        key = (r, v, t, p, tsl, l, s)
        e = AE()
        if l == UP && s != ANNUAL
            for ts in ts_prev[r, s]
                add!(e, 1.0, VAR_UPS(r, v, t, p, s, N))
                add!(e, -1.0, VAR_UPS(r, v, t, p, ts, N))
                add!(e, -1.0, VAR_UPS(r, v, t, p, s, LO))
                add!(e, 1.0, VAR_UPS(r, v, t, p, s, UP))
            end
        end
        if l == UP && s == ANNUAL && (r, p, N) in RP_PL
            # start-up costs on ANNUAL with partial loads (eqactups.vda 69):
            #   SUM(ANNUAL(S)$RP_PL(R,P,'N'),VAR_UPS(S,L)-SUM(PRC_TS(R,P,TS),VAR_UPS(TS,'FX')))
            add!(e, 1.0, VAR_UPS(r, v, t, p, s, UP))
            for ts in prc_ts[r, p]
                add!(e, -1.0, VAR_UPS(r, v, t, p, ts, FX))
            end
        end
        if l == LO || l == FX
            add!(e, 1.0, capacity_mx(m, r, v, t, p))
            add!(e, -1.0, offline(m, r, v, t, p, s))
            add!(e, -1.0, VAR_UDP(r, v, t, p, s, FX))
            (r, p, FX) in RP_UPL && add!(e, -1.0, VAR_UPS(r, v, t, p, s, FX))
        end
        row!(m, :EQE_ACTUPS, key, e, ==, 0.0)

        if l == N || l == FX
            e = AE()
            add!(e, 1.0, VAR_UPS(r, v, t, p, s, l))
            if l == N
                for ts in parent[r, s]
                    add!(e, -1.0, VAR_UPS(r, v, t, p, ts, FX))
                end
            else
                for ts in children[r, s]
                    add!(e, -1.0, VAR_UPS(r, v, t, p, ts, UP))
                end
            end
            row!(m, :EQL_ACTUPS, key, e, <=, 0.0)
        end
    end
end

"""
    EQL_ACTUPC(r,v,t,p,tsl,l,s)                                                  eqactups.vda

Minimum on-line and off-line times (ACT_TIME(r,t,p,l), hours), on the timeslices s of the process level:

    l = UP:  capacity started up in the timeslices of the cycle that began less than ACT_TIME(UP) before s
             + VAR_UPS(s,N)  <=  VAR_UPS(parent of s, FX)
    l = LO:  capacity shut down in the timeslices that began less than ACT_TIME(LO) before s  <=  VAR_UPS(s,N)
    l = N:   SUM(ts directly below s, VAR_UPS(ts,UP))  <=  (capacity - off line(s)) * ACT_TIME(r,t,p,N)    (cycles)

"Began less than ... before s" is RS_MODUS(r,s,j,up,sl) < ACT_TIME / 8760; the capacity is that of EQ_CAPLOAD.
"""
function eq_actupc!(m::Model)
    (; RTP_VINTYR, RP_UPC, ACT_TIME, RS_MODUS) = m.d
    (; upc_lv, ts_group, children, cycle_of, cycle_ts) = m.ix
    (; VAR_UPS) = m.v
    (; LO, UP, FX, N) = m.K
    isempty(RP_UPC) && return

    for (r, v, t, p) in RTP_VINTYR, (tsl, l) in upc_lv[r, p], s in ts_group[r, tsl]
        sow_skip(m, t) && continue                    # a period this SOW shares with an earlier one (stochastic.jl)
        e = AE()
        if l == N
            for sl in children[r, s]
                add!(e, 1.0, VAR_UPS(r, v, t, p, sl, UP))
            end
            k = plain(ACT_TIME(r, t, p, N))
            online = capon(m, r, v, t, p)
            add!(online, -1.0, offline(m, r, v, t, p, s))
            add!(e, -k, online)
        else
            window = plain(ACT_TIME(r, t, p, l)) / 8760
            for (j, up) in cycle_of[r, s], sl in cycle_ts[r, j, up]
                plain(RS_MODUS(r, s, j, up, sl)) < window && add!(e, 1.0, VAR_UPS(r, v, t, p, sl, l))
            end
            if l == UP || l == FX
                for (j, up) in cycle_of[r, s]
                    add!(e, -1.0, VAR_UPS(r, v, t, p, up, FX))
                end
            end
            sig = l == LO ? 1.0 : l == UP ? -1.0 : 0.0
            iszero(sig) || add!(e, -sig, VAR_UPS(r, v, t, p, s, N))
        end
        row!(m, :EQL_ACTUPC, (r, v, t, p, tsl, l, s), e, <=, 0.0)
    end
end
