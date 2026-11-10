# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_SLSIFT(r,t,p,com,s,lnx,l)                                                 eqactups.vda

Load shifting. A load-shifting process is a storage without a level: it takes the demand commodity
in (VAR_SIN) when the load is served and gives it out (VAR_SOUT) when the load would have occurred.
`com` is the shifted input (RPC_LS), or ACT when the process has several. VAR_ACT(s) is the load
moved out of timeslice s. Four rows per process, period and timeslice, named by the last two keys:

    (FX,N)   how much can be shifted (STG_SIFT, a share of the production of the commodity delivered):
                 load moved out of s [+ that of the timeslices below s] [+ all deliveries, s = ANNUAL, com = ACT]
                 + VAR_SIN(com,s) + VAR_SOUT(ACT,s)   =   SUM(c delivered, STG_SIFT * VAR_COMPRD(c) / COM_IE)
    (FX,FX)  balance in s:        deliveries in s  =  what is taken in in s  +  load moved out  -  VAR_SIN(com,s)
             and, on the timeslices above with no time window given (ACT_TIME), zero net shifting below s
    (N,UP)   delay (ACT_TIME UP): the load moved out of s less what is served in s is what the shifted load
             (VAR_UDP, in capacity units) gains from the timeslice before
    (N,FX)   time window (ACT_TIME FX, hours): the shifted load at s is covered by what is served in the
             timeslices of the cycle that start within the window after s
    (N,N)    balancing window (ACT_TIME N, hours): the shifted load at s (VAR_UDP N) is balanced by the activity
             less what is taken in, over the timeslices of the cycle within the window after s
    (FX,LO), (FX,UP), (N,LO)   advance window (ACT_TIME LO, given with UP): the load moved earlier / later in s, of
             the vintage and of the vintage '0', is what starts within the window (VAR_UPS(sl,LO / UP), sl before /
             after s); VAR_UPS(s,LO) + VAR_UPS(s,UP) is what is taken in in s

The shifted load is  VAR_UDP(r,v,t,p,s,bd) * PRC_CAPACT(r,p) * RS_STGPRD(r,s) / 8760  (the macro VAR_SIFT of TIMES).
"""
function eq_slsift!(m::Model)
    (; RTP, RPC_LS, RPC_STG, RPCS_VAR, PRC_TS, TOP, RTC, RS_FR, STG_SIFT, ACT_TIME, COM_IE, PRC_CAPACT, RS_STGPRD, RS_HR, G_YRFR, JS_CCL, RTCS_VARC) = m.d
    (; ls_c, prcts_up, vintages, children, stg_c, rpcs_s, varc_ts, ts_prev, cycle_of, cycle_ts, rtp_p, ts_frac) = m.ix
    (; VAR_ACT, VAR_SIN, VAR_SOUT, VAR_COMPRD, VAR_UDP, VAR_UPS) = m.v
    (; ANNUAL, ACT, IN, OUT, LO, UP, FX, N) = m.K
    isempty(RPC_LS) && return
    v0 = id!(m.L, "0")                          # VAR_SIFT('0',S,L): the shifted load of no vintage

    for t in m.T, (r, t2, p) in RTP
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (t2 == t && !isempty(ls_c[r, p])) || continue
        windowed = any(bd -> has(ACT_TIME, r, t, p, bd), (LO, UP, FX, N))
        sift(v, s, bd) = (PRC_CAPACT[r, p] * RS_STGPRD[r, s] / 8760) * VAR_UDP(r, v, t, p, s, bd)
        delivered = [c for c in stg_c[r, p] if (r, p, c, OUT) in TOP]

        for com in ls_c[r, p], s in prcts_up[r, p]
            at_level = (r, p, s) in PRC_TS
            act_limit = STG_SIFT(r, t, p, ACT, s)

            # (FX,N): limit on the shifted quantity
            if at_level || !iszero(act_limit) || (s == ANNUAL && com == ACT)
                e = AE()
                for v in vintages[r, t, p]
                    if !iszero(act_limit)
                        for ts in children[r, s]
                            (r, p, ts) in PRC_TS && add!(e, 1.0, VAR_ACT(r, v, t, p, ts))
                        end
                    end
                    if s == ANNUAL && com == ACT
                        for c in delivered, ts in rpcs_s[r, p, c]
                            add!(e, 1.0, VAR_SOUT(r, v, t, p, c, ts))
                        end
                    end
                    if at_level
                        add!(e, 1.0, VAR_SIN(r, v, t, p, com, s))
                        add!(e, 1.0, VAR_ACT(r, v, t, p, s))
                    end
                    add!(e, 1.0, VAR_SOUT(r, t, t, p, ACT, s))
                    for c in delivered
                        (r, t, c) in RTC || continue
                        for ts in onbranch(varc_ts[r, t, c], ts_frac[r, s])
                            has(RS_FR, r, s, ts) || continue
                            # (an STG_SIFT of EPS keeps its entry: EPS, as in GAMS)
                            share = ((at_level || (s == ANNUAL && com == ACT)) ? STG_SIFT(r, t, p, c, ts) : 0.0) + act_limit
                            add!(e, -share / COM_IE[r, t, c, ts] * frac(m, r, t, c, s, ts), VAR_COMPRD(r, t, c, ts))
                        end
                    end
                end
                row!(m, :EQ_SLSIFT, (r, t, p, com, s, FX, N), e, ==, 0.0)
            end

            # (FX,FX): balance of the timeslice
            e = AE()
            for v in vintages[r, t, p]
                if at_level
                    for c in delivered, ts in onbranch(rpcs_s[r, p, c], ts_frac[r, s])
                        has(RS_FR, r, s, ts) && add!(e, -frac(m, r, t, c, s, ts), VAR_SOUT(r, v, t, p, c, ts))
                    end
                    for c in stg_c[r, p]
                        (r, p, c, IN) in TOP && add!(e, 1.0, VAR_SIN(r, v, t, p, c, s))
                    end
                    add!(e, 1.0, VAR_ACT(r, v, t, p, s))
                    add!(e, -1.0, VAR_SIN(r, v, t, p, com, s))
                end
                if !windowed
                    for ts in children[r, s]
                        (r, p, ts) in PRC_TS || continue
                        add!(e, -1.0, VAR_SIN(r, v, t, p, com, ts))
                        add!(e, 1.0, VAR_ACT(r, v, t, p, ts))
                    end
                end
            end
            row!(m, :EQ_SLSIFT, (r, t, p, com, s, FX, FX), e, ==, 0.0)

            at_level || continue
            # (N,UP): delay
            if has(ACT_TIME, r, t, p, UP)
                e = AE()
                for v in vintages[r, t, p], ts in ts_prev[r, s]
                    for (bd, sig) in ((LO, 1.0), (UP, -1.0))
                        add!(e, sig, sift(v, ts, bd))
                        add!(e, -sig, sift(v, s, bd))
                    end
                    add!(e, 1.0, VAR_SIN(r, v, t, p, com, s))
                    add!(e, -1.0, VAR_ACT(r, v, t, p, s))
                end
                row!(m, :EQ_SLSIFT, (r, t, p, com, s, N, UP), 0.0, ==, e)
            end
            # (N,FX): time window
            if has(ACT_TIME, r, t, p, FX)
                window = plain(ACT_TIME(r, t, p, FX)) / 8760
                e = AE()
                for v in vintages[r, t, p]
                    for bd in (LO, UP, FX)
                        add!(e, 1.0, sift(v, s, bd))
                    end
                    for (j, up) in cycle_of[r, s], sl in cycle_ts[r, j, up]
                        cycle = 1 / JS_CCL[r, j, up]
                        rem(RS_HR(r, s) - RS_HR(r, sl) + G_YRFR[r, s] / RS_STGPRD[r, s] / 9 + cycle, cycle) < window || continue
                        add!(e, -1.0, VAR_SIN(r, v, t, p, com, sl))
                        for ts in ts_prev[r, sl]
                            add!(e, -1.0, sift(v, sl, UP))
                            add!(e, 1.0, sift(v, ts, UP))
                        end
                    end
                end
                row!(m, :EQ_SLSIFT, (r, t, p, com, s, N, FX), 0.0, ==, e)
            end
            # timeslices sl of the cycle of s whose start lies within `window` (in years) after s (sig 1) or before (-1):
            # MOD((RS_HR(s)-RS_HR(sl)+G_YRFR(s)/RS_STGPRD(s)/9)*sig+1/JS_CCL,1/JS_CCL) < window
            within(window, sig) = (sl for (j, up) in cycle_of[r, s] for sl in cycle_ts[r, j, up]
                                   if rem((RS_HR(r, s) - RS_HR(r, sl) + G_YRFR[r, s] / RS_STGPRD[r, s] / 9) * sig + 1 / JS_CCL[r, j, up],
                                          1 / JS_CCL[r, j, up]) < window)
            # (N,N): balancing window
            if has(ACT_TIME, r, t, p, N)
                e = AE()
                for v in vintages[r, t, p]
                    add!(e, 1.0, sift(v, s, N))
                    for sl in within(plain(ACT_TIME(r, t, p, N)) / 8760, 1.0)
                        add!(e, 1.0, VAR_ACT(r, v, t, p, sl))
                        add!(e, -1.0, VAR_SIN(r, v, t, p, com, sl))
                    end
                end
                row!(m, :EQ_SLSIFT, (r, t, p, com, s, N, N), 0.0, ==, e)
            end
            # (FX,LO), (FX,UP), (N,LO): advance window (ACT_TIME LO; the preprocessor drops it without UP)
            if has(ACT_TIME, r, t, p, LO)
                for (l, sig) in ((LO, 1.0), (UP, -1.0))
                    e = AE()
                    for v in vintages[r, t, p]
                        add!(e, 1.0, sift(v, s, l))
                        add!(e, 1.0, sift(v0, s, l))
                        for sl in within(plain(ACT_TIME(r, t, p, l)) / 8760, sig)
                            add!(e, -1.0, VAR_UPS(r, v, t, p, sl, l))
                        end
                    end
                    row!(m, :EQ_SLSIFT, (r, t, p, com, s, FX, l), e, ==, 0.0)
                end
                e = AE()
                for v in vintages[r, t, p]
                    add!(e, 1.0, VAR_UPS(r, v, t, p, s, LO))
                    add!(e, 1.0, VAR_UPS(r, v, t, p, s, UP))
                    add!(e, -1.0, VAR_SIN(r, v, t, p, com, s))
                end
                row!(m, :EQ_SLSIFT, (r, t, p, com, s, N, LO), 0.0, ==, e)
            end
        end
    end
end
