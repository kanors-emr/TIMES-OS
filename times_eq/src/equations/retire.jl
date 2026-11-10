# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_CUMRET(r,v,t,p)                                                          prepret.dsc

Early retirement of capacity: what has been retired of vintage v by period t is what had been
retired by the period before, plus what is retired in t.

    VAR_SCAP(r,v,t,p)  =  VAR_SCAP(r,v,t-1,p) + VAR_RCAP(r,v,t,p)

For a process without refits the row is filed under the period before t.
"""
function eq_cumret!(m::Model)
    (; PRC_RCAP, RTP_CPTYR, VNTRT, RP_RTF) = m.d
    (; retirable) = m.ix
    (; VAR_SCAP, VAR_RCAP) = m.v

    for (r, p) in PRC_RCAP, t in m.T
        before = previous(m, t)
        k = has(RP_RTF, r, p) ? t : before
        k === nothing && continue
        for v in retirable[r, t, p]
            (v, k) in VNTRT || continue
            e = AE()
            if (r, v, k, p) in RTP_CPTYR
                add!(e, 1.0, VAR_SCAP(r, v, t, p))
                add!(e, -1.0, VAR_RCAP(r, v, t, p))
            end
            # (MODLYEAR(Y(T-1)): in a myopic step not a period after the window)
            (before !== nothing && !(before in m.fwd) && (r, v, before, p) in RTP_CPTYR && (v, before) in VNTRT) &&
                add!(e, -1.0, VAR_SCAP(r, v, before, p))
            sow_rowt!(m, t)                 # stochastic TIMES: the row's SOW tag is of T, not of its key's K
            row!(m, :EQ_CUMRET, (r, v, k, p), e, ==, 0.0)
        end
    end
end

"""
    EQL_SCAP(r,v,p,N) / EQL_SCAP(r,v,p,IN)                                      prepret.dsc

N: the capacity retired by the last period in which vintage v can be retired cannot exceed what was
installed, less the capacity that has lost its salvage value (VAR_SCAP under period 0).
IN: the operating life (NCAP_OLIFE): the activity of the vintage over the periods, in years at full
capacity, cannot exceed its operating life times what was installed (less the same).

    VAR_SCAP(r,v,t,p)                                              <=  installed(r,v,p) - VAR_SCAP(r,v,0,p)
    SUM((t,s), VAR_ACT(r,v,t,p,s) * FPD(t)) / PRC_CAPACT / MAX(1,NCAP_OLIFE)   <=  installed(r,v,p) - VAR_SCAP(r,v,0,p)\$RVPRL
"""
function eq_scap!(m::Model)
    (; PRC_RCAP, RVPRL, OBJ_SUMS, PRC_VINT, MILESTONYR, PASTYEAR, NCAP_PASTI, VNTRT, NCAP_OLIFE, RTP, RTP_CPTYR, PRC_TS, FPD, PRC_CAPACT) = m.d
    (; VAR_SCAP, VAR_NCAP, VAR_ACT) = m.v
    (; N, IN) = m.K
    y0 = year0(m)
    at = Dict(year(m.L, t) => t for t in m.T)

    for ((r, v, p), span) in RVPRL
        ((r, p) in PRC_RCAP && v != y0) || continue
        ((r, v, p) in OBJ_SUMS || (!((r, p) in PRC_VINT) && v in MILESTONYR)) || continue

        retired = AE()
        t = get(at, year(m.L, v) + round(Int, span), nothing)
        (t !== nothing && (v, t) in VNTRT) && add!(retired, 1.0, VAR_SCAP(r, v, t, p))

        limit = AE(NCAP_PASTI(r, v, p))
        new_capacity(m, v) && add!(limit, 1.0, VAR_NCAP(r, v, p))
        add!(limit, -1.0, VAR_SCAP(r, v, y0, p))
        row!(m, :EQL_SCAP, (r, v, p, N), retired, <=, limit)
    end
    # IN: SUM(IO(IPS),SUM((RTP_CPTYR(R,V,TT,P),PRC_TS(R,P,S)),VAR_ACT(R,V,TT,P,S)*FPD(TT))/PRC_CAPACT(R,P)/MAX(1,NCAP_OLIFE(RTP)))
    #       =L= VAR_NCAP(R,V,P)$T(V) + NCAP_PASTI(R,V,P) - VAR_SCAP(R,V,'0',P)$RVPRL(RTP)
    isempty(NCAP_OLIFE) && return
    periods = Dict{Tuple{Id,Id,Id},Vector{Id}}()
    for (r, v, t, p) in RTP_CPTYR
        push!(get!(periods, (r, v, p), Id[]), t)
    end
    slices = Dict{Tuple{Id,Id},Vector{Id}}()
    for (r, p, s) in PRC_TS
        push!(get!(slices, (r, p), Id[]), s)
    end
    for ((r, v, p), olife) in NCAP_OLIFE
        ((r, p) in PRC_RCAP && (r, v, p) in RTP) || continue
        # (an operating life given as 0 is EPS: the row's $NCAP_OLIFE is true and it divides by MAX(1,EPS) = 1;
        #  a life between 0 and 1 divides by 1 as well)
        life = max(1.0, plain(olife))
        used = AE()
        for t in get(periods, (r, v, p), Id[]), s in get(slices, (r, p), Id[])
            add!(used, FPD[t] / PRC_CAPACT[r, p] / life, VAR_ACT(r, v, t, p, s))
        end
        limit = AE(NCAP_PASTI(r, v, p))
        new_capacity(m, v) && add!(limit, 1.0, VAR_NCAP(r, v, p))
        has(RVPRL, r, v, p) && add!(limit, -1.0, VAR_SCAP(r, v, y0, p))
        row!(m, :EQL_SCAP, (r, v, p, IN), used, <=, limit)
    end
end

"""
    EQ_DSCRET(r,v,t,p)                                                          prepret.dsc

Retirement in blocks (RCAP_BLK, a MIP): what is retired of vintage v by period t, beyond the forced retirement, is
a whole number of blocks or all that is left:

    VAR_SCAP(r,v,t,p) - RTFORC(r,v,t,p)  =  RCAP_BLK * VAR_DRCAP(r,v,t,p,2) + (NCAP_PASTI - RTFORC) * VAR_DRCAP(r,v,t,p,1)

VAR_DRCAP is integer (prepret.dsc declares it INTEGER under %MIP%; its bounds come with the input).
"""
function eq_dscret!(m::Model)
    (; RCAP_BLK, RTP_CPTYR, VNTRT, RTFORC, NCAP_PASTI) = m.d
    (; VAR_SCAP, VAR_DRCAP) = m.v
    isempty(RCAP_BLK) && return
    j1, j2 = id!(m.L, "1"), id!(m.L, "2")
    for (r, v, t, p) in RTP_CPTYR
        (has(RCAP_BLK, r, v, p) && (v, t) in VNTRT) || continue
        forced = plain(RTFORC(r, v, t, p))
        e = AE()
        add!(e, RCAP_BLK(r, v, p), VAR_DRCAP(r, v, t, p, j2))
        add!(e, plain(NCAP_PASTI(r, v, p)) - forced, VAR_DRCAP(r, v, t, p, j1))
        row!(m, :EQ_DSCRET, (r, v, t, p), VAR_SCAP(r, v, t, p) - forced, ==, e)
    end
    # the block counts are integers in the MIP
    for x in values(VAR_DRCAP.x)
        JuMP.set_integer(x)
    end
end

"""
    EQL_REFIT(r,tt,t,prc,FX)                                                    prepret.dsc

Retrofit and life extension: capacity of the refit processes p of host prc, commissioned in tt,
replaces capacity of the host that is retired in tt.

    SUM(p, COEF_CPT(r,tt,t,p) * (VAR_NCAP(r,tt,p) - retired))  +  VAR_RCAP(r,t,tt,prc)
        =  SUM(v, COEF_CPT(r,v,t,prc) * (VAR_RCAP(r,v,tt,prc) - forced retirement))  +  VAR_RCAP(r,t,tt-1,prc)

VAR_RCAP(r,t,tt,prc), with the period in the place of the vintage, is the capacity retired in tt
that is not refitted. PRC_REFIT < 0 marks a retrofit, which may be done to any earlier vintage.
"""
function eq_refit!(m::Model)
    (; RTP_TT, RP_RTF, PRC_REFIT, PRC_RCAP, VNTRT, RTP_CPTYR, COEF_CPT, RTFORC) = m.d
    (; refits, retirable) = m.ix
    (; VAR_NCAP, VAR_RCAP, VAR_SCAP) = m.v
    (; FX, N) = m.K
    later(a, b) = year(m.L, a) >= year(m.L, b)                  # VNT(b, a): a is b or lies after it

    for (r, tt, t, prc) in RTP_TT
        t in m.d.MILESTONYR || continue
        rtf = plain(RP_RTF(r, prc))
        before = previous(m, tt)
        for l in (N, FX)
            (l == FX || (rtf == 3 && later(tt, t))) || continue

            refitted = AE()
            for p in refits[r, prc]
                kind = plain(PRC_REFIT(r, prc, p))
                (later(tt, t) || kind < 0) || continue
                k = COEF_CPT(r, tt, t, p)
                iszero(k) && continue
                add!(refitted, k, VAR_NCAP(r, tt, p))
                ((r, p) in PRC_RCAP && (tt, t) in VNTRT) && add!(refitted, -k, VAR_SCAP(r, tt, t, p))
            end
            # VAR_RCAP(r,t,tt,prc) $ (RP_RTF $ VNT(t,tt) $ BD(l) < 3)
            ((later(tt, t) && l == FX ? rtf : 0.0) < 3) && add!(refitted, 1.0, VAR_RCAP(r, t, tt, prc))

            retired = AE()
            for v in retirable[r, tt, prc]
                (v, tt) in VNTRT || continue
                k = COEF_CPT(r, v, t, prc)
                iszero(k) && continue
                add!(retired, k, VAR_RCAP(r, v, tt, prc))
                if before !== nothing && later(before, v)
                    forced = RTFORC(r, v, tt, prc) - RTFORC(r, v, before, prc)
                    add!(retired, -k, isodd(round(Int, rtf)) ? forced : min(0.0, forced))
                end
            end
            (before !== nothing && (r, before, t, prc) in RTP_TT && (l == FX ? rtf : 0.0) > 0) &&
                add!(retired, 1.0, VAR_RCAP(r, t, before, prc))

            row!(m, :EQL_REFIT, (r, tt, t, prc, l), refitted, ==, retired)
        end
    end
end
