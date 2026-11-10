# SPDX-License-Identifier: GPL-3.0-or-later
# Unit commitment by start-up type (eqlducs.vda): a dispatchable process with start-up costs by type (ACT_CSTSD,
# RP_DP), dispatched on the levels RP_DPL (its own and, for a DAYNITE process, those above it but ANNUAL).
#
# In each timeslice s of those levels the capacity is on line (VAR_UDP(s,N)), off line (VAR_UPS(s,N)), started up
# (VAR_UPS(s,UP), split by type into VAR_UPT(s,upt)) or shut down (VAR_UPS(s,LO)). A unit off line for longer than
# the longest non-operational time of a type (ACT_MAXNON, DP_NON) cannot start up as that type; start-up and shut-down
# take time (ACT_SDTIME), during which the load ramps (EQ_SDSLANT) and losses may arise (ACT_LOSSD, EQ_SUDPLL).
# The discrete variant (DUC = YES, binary indicators) is not written: the preprocessor stops on it.

const SDTOL = 0.001                                  # sdtol (eqlducs.vda)

on_line(m, r, v, t, p, s) = m.v.VAR_UDP(r, v, t, p, s, m.K.N)        # var_on
off_line(m, r, v, t, p, s) = m.v.VAR_UPS(r, v, t, p, s, m.K.N)       # var_off
load_gap(m, r, v, t, p, s) = m.v.VAR_UDP(r, v, t, p, s, m.K.FX)      # var_gap

"""Start-up / shut-down time of type upt as a fraction of the year: ACT_SDTIME(r,v,p,upt,bd)/8760."""
sdtime(m, r, v, p, upt, bd) = plain(m.d.ACT_SDTIME(r, v, p, upt, bd)) / 8760

"""
%CAPUPS%: the capacity of (v, p) in t less what is off line strictly above s (RS_BELOW(r,ts,s), RPS_UPS(r,p,ts)).
"""
function capups(m::Model, r, v, t, p, s)
    e = capon(m, r, v, t, p)
    for ts in onbranch(m.ix.ups_ts[r, p], m.ix.ts_above[r, s])
        (ts != s && (r, ts, s) in m.d.TS_MAP) && add!(e, -1.0, off_line(m, r, v, t, p, ts))
    end
    return e
end

"""The timeslices sl of the cycles of s (RS_UP(r,s,js), RJ_SL(r,js,sl)), with the cycle (j, up) and JS_CCL."""
function cycle_slices(m::Model, r, s)
    out = Tuple{Id,Id,Id,Float64}[]
    for (j, up) in m.ix.cycle_of[r, s], sl in m.ix.cycle_ts[r, j, up]
        push!(out, (j, up, sl, m.d.JS_CCL[r, j, up]))
    end
    return out
end

"""
    EQ_SDLOGIC(r,v,t,p,tsl,s,l)                                                  eqlducs.vda

On the dispatch levels (RP_DPL), l = N: the change of the capacity on line is what is started up less what is shut down,

    VAR_UDP(ts,N) - VAR_UDP(s,N) - VAR_UPS(s,LO) + VAR_UPS(s,UP) = 0      (ts the timeslice before s)

and l = FX: what is started up is split by type, VAR_UPS(s,UP) = SUM(upt in RP_UPT(r,p,upt,UP), VAR_UPT(s,upt)).
"""
function eq_sdlogic!(m::Model)
    (; RTP_VINTYR, RP_DP) = m.d
    (; dpl, ts_group, ts_prev, upt_of) = m.ix
    (; VAR_UPS, VAR_UPT) = m.v
    (; LO, UP, FX, N) = m.K
    one = id!(m.L, "1")                      # %SWX%: the state of the world '1' (eqlducs.vda)
    isempty(RP_DP) && return

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue
        (r, p) in RP_DP || continue
        for tsl in dpl[r, p], s in ts_group[r, tsl]
            e = AE()
            for ts in ts_prev[r, s]
                add!(e, 1.0, on_line(m, r, v, t, p, ts))
                add!(e, -1.0, on_line(m, r, v, t, p, s))
            end
            add!(e, -1.0, VAR_UPS(r, v, t, p, s, LO))         # BDSIG(LO) = 1
            add!(e, 1.0, VAR_UPS(r, v, t, p, s, UP))          # BDSIG(UP) = -1
            row!(m, :EQ_SDLOGIC, (r, v, t, p, tsl, s, N, one), e, ==, 0.0)
            e = AE()
            add!(e, 1.0, VAR_UPS(r, v, t, p, s, UP))
            for (upt, bd) in upt_of[r, p]
                bd == UP && add!(e, -1.0, VAR_UPT(r, v, t, p, s, upt))
            end
            row!(m, :EQ_SDLOGIC, (r, v, t, p, tsl, s, FX, one), e, ==, 0.0)
        end
    end
end

"""
    EQ_SUDUPT(r,v,t,p,tsl,s,upt)                                                 eqlducs.vda

A start-up of type upt in s needs a shut-down in a timeslice sl of the same cycle that ended within the window of
non-operational time of that type (DP_NON: LO its start, UP its width, fractions of the year):

    VAR_UPT(s,upt)  <=  SUM(sl /= s, VAR_UPS(sl,LO))   where
      MOD(RS_HR(s) - RS_HR(sl) - DP_NON(LO) + (G_YRFR(sl)/4 + G_YRFR(s))/RS_STGPRD(s) + 2/JS_CCL, 1/JS_CCL)
        < DP_NON(UP) * (1 + sdtol) + G_YRFR(s)/RS_STGPRD(s)/2
"""
function eq_sudupt!(m::Model)
    (; RTP_VINTYR, RP_DP, DP_NON, RS_HR, G_YRFR, RS_STGPRD) = m.d
    (; dpl, ts_group) = m.ix
    (; VAR_UPS, VAR_UPT) = m.v
    (; LO, UP) = m.K
    one = id!(m.L, "1")                      # %SWX%: the state of the world '1' (eqlducs.vda)
    (isempty(RP_DP) || isempty(DP_NON)) && return
    upts = [id!(m.L, u) for u in ("COLD", "WARM", "HOT")]

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue
        (r, p) in RP_DP || continue
        for tsl in dpl[r, p], s in ts_group[r, tsl], upt in upts
            has(DP_NON, r, v, p, upt, tsl, UP) || continue
            lo, width = plain(DP_NON(r, v, p, upt, tsl, LO)), plain(DP_NON(r, v, p, upt, tsl, UP))
            half = G_YRFR[r, s] / RS_STGPRD[r, s] / 2
            e = AE()
            for (_, _, sl, ccl) in cycle_slices(m, r, s)
                sl == s && continue
                x = rem(plain(RS_HR(r, s)) - plain(RS_HR(r, sl)) - lo + (G_YRFR[r, sl] / 4 + G_YRFR[r, s]) / RS_STGPRD[r, s] + 2 / ccl, 1 / ccl)
                x < width * (1 + SDTOL) + half && add!(e, 1.0, VAR_UPS(r, v, t, p, sl, LO))
            end
            row!(m, :EQ_SUDUPT, (r, v, t, p, tsl, s, upt, one), VAR_UPT(r, v, t, p, s, upt), <=, e)
        end
    end
end

"""
    EQ_SDSLANT(r,v,t,p,tsl,s)                                                    eqlducs.vda

The capacity on line in s: the capacity less what is off line (above s, and in s), less what is still starting up
or already shutting down in s (a share of what started up / shuts down in the timeslices sl of the cycle within the
start-up / shut-down time ACT_SDTIME):

    VAR_UDP(s,N) = [VAR_UPS(parent,FX) - CAPUPS]\$PRC_TS(r,p,s) + CAPUPS - VAR_UPS(s,N)
                   - SUM(upt, UP: VAR_UPT(sl,upt) * MAX(0, 1 - MOD(RS_HR(sl)-RS_HR(s)+SUDHFR+2/JS_CCL, 1/JS_CCL)/sdt), sl /= s,
                                  RS_MODUS(r,sl,js,s) < sdt*(1+sdtol))
                   - SUM(HOT, LO: VAR_UPS(sl,LO) * (1 for sl = s, else MAX(0, 1 - MOD(RS_HR(s)-RS_HR(sl)+SUDHFR+2/JS_CCL, 1/JS_CCL)/sdt)),
                                  RS_MODUS(r,s,js,sl) < sdt*(1+sdtol))

with CAPUPS the capacity less what is off line strictly above s, sdt = ACT_SDTIME/8760 and
SUDHFR = (G_YRFR(sl) - G_YRFR(s))/2/RS_STGPRD(sl).
"""
function eq_sdslant!(m::Model)
    (; RTP_VINTYR, RP_DP, PRC_TS, RS_HR, RS_MODUS, G_YRFR, RS_STGPRD) = m.d
    (; dpl, ts_group, parent, upt_of) = m.ix
    (; VAR_UPS, VAR_UPT) = m.v
    (; LO, UP, FX) = m.K
    one = id!(m.L, "1")                      # %SWX%: the state of the world '1' (eqlducs.vda)
    isempty(RP_DP) && return

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue
        (r, p) in RP_DP || continue
        for tsl in dpl[r, p], s in ts_group[r, tsl]
            cu = capups(m, r, v, t, p, s)
            e = AE()
            if (r, p, s) in PRC_TS
                for ts in parent[r, s]
                    add!(e, 1.0, VAR_UPS(r, v, t, p, ts, FX))
                    add!(e, -1.0, cu)
                end
            end
            add!(e, 1.0, cu)
            add!(e, -1.0, off_line(m, r, v, t, p, s))
            for (upt, bd) in upt_of[r, p]
                sdt = sdtime(m, r, v, p, upt, bd)
                for (j, up, sl, ccl) in cycle_slices(m, r, s)
                    hfr = (G_YRFR[r, sl] - G_YRFR[r, s]) / 2 / RS_STGPRD[r, sl]
                    if bd == UP
                        plain(RS_MODUS(r, sl, j, up, s)) < sdt * (1 + SDTOL) || continue
                        sl == s && continue
                        k = max(0.0, 1 - rem(plain(RS_HR(r, sl)) - plain(RS_HR(r, s)) + hfr + 2 / ccl, 1 / ccl) / sdt)
                        add!(e, -k, VAR_UPT(r, v, t, p, sl, upt))
                    elseif bd == LO
                        plain(RS_MODUS(r, s, j, up, sl)) < sdt * (1 + SDTOL) || continue
                        k = sl == s ? 1.0 : max(0.0, 1 - rem(plain(RS_HR(r, s)) - plain(RS_HR(r, sl)) + hfr + 2 / ccl, 1 / ccl) / sdt)
                        add!(e, -k, VAR_UPS(r, v, t, p, sl, bd))
                    end
                end
            end
            row!(m, :EQ_SDSLANT, (r, v, t, p, tsl, s, one), on_line(m, r, v, t, p, s), ==, e)
        end
    end
end

"""
    EQ_SDMINON(r,v,t,p,s)                                                        eqlducs.vda

On the timeslices of the process, the capacity on line and the load gap of the level above cover the load gap and
the start-ups of s; where some start-up type takes less than half the timeslice, the start-ups of the types that
take at least half of it count instead of all start-ups:

    VAR_UDP(s,N) + VAR_UDP(parent,FX)  >=  VAR_UDP(s,FX) + VAR_UPS(s,UP)
        [+ SUM(upt: G_YRFR(s)/RS_STGPRD(s)/2 <= sdt(upt), VAR_UPT(s,upt)) - VAR_UPS(s,UP),  SMIN(upt, sdt(upt)) < G_YRFR(s)/RS_STGPRD(s)/2]
"""
function eq_sdminon!(m::Model)
    (; RTP_VINTYR, RP_DP, G_YRFR, RS_STGPRD) = m.d
    (; prc_ts, parent, upt_of) = m.ix
    (; VAR_UPS, VAR_UPT) = m.v
    (; UP) = m.K
    one = id!(m.L, "1")                      # %SWX%: the state of the world '1' (eqlducs.vda)
    isempty(RP_DP) && return

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue
        (r, p) in RP_DP || continue
        ups = [upt for (upt, bd) in upt_of[r, p] if bd == UP]
        shortest = isempty(ups) ? Inf : minimum(sdtime(m, r, v, p, upt, UP) for upt in ups)
        for s in prc_ts[r, p]
            half = G_YRFR[r, s] / RS_STGPRD[r, s] / 2
            lhs = AE()
            add!(lhs, 1.0, on_line(m, r, v, t, p, s))
            for ts in parent[r, s]
                add!(lhs, 1.0, load_gap(m, r, v, t, p, ts))
            end
            rhs = AE()
            add!(rhs, 1.0, load_gap(m, r, v, t, p, s))
            add!(rhs, 1.0, VAR_UPS(r, v, t, p, s, UP))
            if shortest < half
                for upt in ups
                    half <= sdtime(m, r, v, p, upt, UP) && add!(rhs, 1.0, VAR_UPT(r, v, t, p, s, upt))
                end
                add!(rhs, -1.0, VAR_UPS(r, v, t, p, s, UP))
            end
            row!(m, :EQ_SDMINON, (r, v, t, p, s, one), lhs, >=, rhs)
        end
    end
end

"""
    EQ_SUDLOAD(r,v,t,p,s)                                                        eqlducs.vda

The load of the process in its timeslices: the minimum load of the capacity on line, and the load gap up to the
availability:

    VAR_ACT(s) / G_YRFR(s) / PRC_CAPACT  =  (capacity - off line(s)) * ACT_MINLD + VAR_UDP(s,FX) * (COEF_AF(s,UP) - ACT_MINLD)
"""
function eq_sudload!(m::Model)
    (; RTP_VINTYR, RP_DP, ACT_MINLD, COEF_AF, G_YRFR, PRC_CAPACT, BS_SUPP, BS_COMTS, BS_APOS, BS_BSC) = m.d
    (; prc_ts) = m.ix
    (; VAR_ACT) = m.v
    (; UP) = m.K
    one = id!(m.L, "1")                      # %SWX%: the state of the world '1' (eqlducs.vda)
    isempty(RP_DP) && return

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue
        (r, p) in RP_DP || continue
        minld = ACT_MINLD(r, v, p)
        for s in prc_ts[r, p]
            online = capon(m, r, v, t, p)
            add!(online, -1.0, offline(m, r, v, t, p, s))
            e = AE()
            add!(e, minld, online)
            add!(e, COEF_AF(r, v, t, p, s, UP) - minld, load_gap(m, r, v, t, p, s))
            # SPRSV (ABS=YES): -sum(bs_comts(bs_apos(r,c),s)$bs_bsc(r,p,c),%var%_bsprs(r,v,t,p,c,s,'N'))$bs_supp(r,p)
            if (r, p) in BS_SUPP
                for (rr, c, ss) in BS_COMTS
                    (rr == r && ss == s && (r, c) in BS_APOS && (r, p, c) in BS_BSC) || continue
                    add!(e, -1.0, m.v.VAR_BSPRS(r, v, t, p, c, s, m.K.N))
                end
            end
            row!(m, :EQ_SUDLOAD, (r, v, t, p, s, one), (1 / G_YRFR[r, s] / PRC_CAPACT[r, p]) * VAR_ACT(r, v, t, p, s), ==, e)
        end
    end
end

"""
    EQ_SUDTIME(r,v,t,p,tsl,s,bd)                                                 eqlducs.vda

Minimum off-line (LO) and on-line (UP) times ACT_TIME, on the timeslices of the process level:

    LO:  VAR_UPS(s,N)  >=  SUM(sl, VAR_UPS(sl,LO))      shut down within ACT_TIME(LO) (after the shut-down time) before s
    UP:  VAR_UDP(s,N)  >=  SUM(sl, upt, VAR_UPT(sl,upt))  started up within ACT_TIME(UP) less the shut-down and start-up times
"""
function eq_sudtime!(m::Model)
    (; RTP_VINTYR, RP_DP, ACT_TIME, RS_HR, G_YRFR, RS_STGPRD) = m.d
    (; prc_tsl, ts_group, upt_of) = m.ix
    (; VAR_UPS, VAR_UPT) = m.v
    (; LO, UP, FX) = m.K
    one = id!(m.L, "1")                      # %SWX%: the state of the world '1' (eqlducs.vda)
    (isempty(RP_DP) || isempty(ACT_TIME)) && return
    hot = id!(m.L, "HOT")

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue
        (r, p) in RP_DP || continue
        for bd in (LO, UP, FX)
            has(ACT_TIME, r, v, p, bd) || continue
            time = plain(ACT_TIME(r, v, p, bd))
            for tsl in prc_tsl[r, p], s in ts_group[r, tsl]
                e = AE()
                if bd == LO || bd == FX                                  # BDLOX
                    add!(e, 1.0, off_line(m, r, v, t, p, s))
                    for (_, _, sl, ccl) in cycle_slices(m, r, s)
                        x = rem(plain(RS_HR(r, s)) - plain(RS_HR(r, sl)) - sdtime(m, r, v, p, hot, LO) + G_YRFR[r, s] / RS_STGPRD[r, s] / 2 + 2 / ccl, 1 / ccl)
                        x < time / 8760 && add!(e, -1.0, VAR_UPS(r, v, t, p, sl, bd))
                    end
                end
                if bd == UP || bd == FX                                  # BDUPX
                    add!(e, 1.0, on_line(m, r, v, t, p, s))
                    for (_, _, sl, ccl) in cycle_slices(m, r, s), (upt, b) in upt_of[r, p]
                        b == bd || continue
                        x = rem(plain(RS_HR(r, s)) - plain(RS_HR(r, sl)) + 1 / ccl, 1 / ccl)
                        lim = (time - plain(m.d.ACT_SDTIME(r, v, p, hot, LO)) - plain(m.d.ACT_SDTIME(r, v, p, upt, bd))) / 8760 + G_YRFR[r, sl] / RS_STGPRD[r, s] / 2
                        x < lim && add!(e, -1.0, VAR_UPT(r, v, t, p, sl, upt))
                    end
                end
                row!(m, :EQ_SUDTIME, (r, v, t, p, tsl, s, bd, one), e, >=, 0.0)
            end
        end
    end
end

"""
    EQ_SUDPLL(r,v,t,p,tsl,s)                                                     eqlducs.vda

The partial-load losses of starting up and shutting down (DP_LOSD): in the timeslices of the process level,

    VAR_UPS(s,FX)  >=  SUM(upt, bd, sl within ACT_SDTIME(upt,bd) of s,
                           (1 + MIN(1, MOD((RS_HR(s)-RS_HR(sl))*BDSIG(bd) + SUDHFR + 2/JS_CCL, 1/JS_CCL)/sdt) * (DP_PSUD(upt,bd) - 1))
                           * (VAR_UPT(sl,upt) [UP] + VAR_UPS(sl,LO) [LO]))  * PRC_CAPACT * G_YRFR(s) * ACT_MINLD
"""
function eq_sudpll!(m::Model)
    (; RTP_VINTYR, RP_DP, DP_LOSD, DP_PSUD, RS_HR, G_YRFR, RS_STGPRD, PRC_CAPACT, ACT_MINLD) = m.d
    (; prc_tsl, ts_group, upt_of) = m.ix
    (; VAR_UPS, VAR_UPT) = m.v
    (; LO, UP, FX) = m.K
    one = id!(m.L, "1")                      # %SWX%: the state of the world '1' (eqlducs.vda)
    (isempty(RP_DP) || isempty(DP_LOSD)) && return

    for (r, v, t, p) in RTP_VINTYR
        (m.stepped && !(t in m.sub)) && continue
        ((r, p) in RP_DP && (r, v, p) in DP_LOSD) || continue
        for tsl in prc_tsl[r, p], s in ts_group[r, tsl]
            unit = PRC_CAPACT[r, p] * G_YRFR[r, s] * ACT_MINLD(r, v, p)
            e = AE()
            for (upt, bd) in upt_of[r, p]
                sig = bd == LO ? 1.0 : bd == UP ? -1.0 : 0.0
                sdt = sdtime(m, r, v, p, upt, bd)
                psud = plain(DP_PSUD(r, v, p, upt, bd))
                for (_, _, sl, ccl) in cycle_slices(m, r, s)
                    d = (plain(RS_HR(r, s)) - plain(RS_HR(r, sl))) * sig
                    rem(d + G_YRFR[r, sl] / RS_STGPRD[r, s] / 2 + 2 / ccl, 1 / ccl) < sdt * (1 + SDTOL) || continue
                    hfr = (G_YRFR[r, sl] - G_YRFR[r, s]) / 2 / RS_STGPRD[r, sl]
                    k = (1 + min(1.0, rem(d + hfr + 2 / ccl, 1 / ccl) / sdt) * (psud - 1)) * unit
                    (bd == UP || bd == FX) && add!(e, k, VAR_UPT(r, v, t, p, sl, upt))
                    (bd == LO || bd == FX) && add!(e, k, VAR_UPS(r, v, t, p, sl, bd))
                end
            end
            row!(m, :EQ_SUDPLL, (r, v, t, p, tsl, s, one), VAR_UPS(r, v, t, p, s, FX), >=, e)
        end
    end
end
