# SPDX-License-Identifier: GPL-3.0-or-later
"""
`POWER(x, n)` as GAMS takes it: a growth multiplier given as 0 under `\$ONEPS` is EPS, and EPS to a positive power stays
EPS, so the term of the period before keeps an EPS entry in the row (the number to the power would underflow to 0).
"""
epspower(x, n) = iseps(x) ? (iszero(n) ? 1.0 : EPS) : plain(x)^n

"""
    EQN_UCRTP / EQE_UCRTP (uc, r, t, p, grp, bd)                               equcrtp.vda

Process-wise dynamic bound (UC_DYNBND): the capacity, new capacity or annual activity of a
process in period t against the period before, with a growth multiplier per year on the left and a
constant per year on the right.

    X(t)  {<=, =, >=}  LHS(uc,r,t,p,grp,bd)^LEAD(t) * X(t-1)  +  RHS(uc,r,t,p,grp,bd) * LEAD(t)

X is VAR_CAP, VAR_NCAP or the activity summed over vintages and timeslices. TIMES writes LO and
UP both as a `<=` row (EQN_UCRTP) with the sign of the terms flipped for UP, and FX as EQE_UCRTP.
A row is written for every record of PRC_DYNUC on the RHS side; the term of the period before is
absent when the process does not exist then.
"""
function eq_ucrtp!(m::Model)
    (; PRC_DYNUC, RTP, RTP_VARA, LEAD) = m.d
    (; vintages, prc_ts) = m.ix
    (; VAR_CAP, VAR_NCAP, VAR_ACT) = m.v
    (; LHS, RHS, CAP, NCAP, ACT, UP, FX) = m.K

    for ((uc, side, r, t, p, grp, bd), constant) in PRC_DYNUC
        side == RHS || continue
        # equcrtp.vda line 75: RTP(%R_T%,P), T the periods: a value given in a past year (with past investments RTP holds
        # there too) gives no row
        t in m.T || continue
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (r, t, p) in RTP || continue
        lead = plain(LEAD(t))
        sign = (bd == UP || bd == FX) ? -1.0 : 1.0          # (1-2$BDUPX(BD))
        # POWER(PRC_DYNUC(UC_N,'LHS',R,T,P,UC_GRPTYPE,BD),LEAD(T)) * %VARV%_CAP(R,V,P %SWS%)
        coef = epspower(PRC_DYNUC(uc, LHS, r, t, p, grp, bd), lead)
        tp = previous(m, t)
        e = AE()
        if grp == CAP
            (tp !== nothing && (r, tp, p) in RTP) && add!(e, sign * coef, VAR_CAP(r, tp, p))
            add!(e, -sign, VAR_CAP(r, t, p))
        elseif grp == NCAP
            (tp !== nothing && (r, tp, p) in RTP) && add!(e, sign * coef, VAR_NCAP(r, tp, p))
            add!(e, -sign, VAR_NCAP(r, t, p))
        elseif grp == ACT
            if tp !== nothing && (r, tp, p) in RTP_VARA
                for v in vintages[r, tp, p], s in prc_ts[r, p]
                    add!(e, sign * coef, VAR_ACT(r, v, tp, p, s))
                end
            end
            for v in vintages[r, t, p], s in prc_ts[r, p]
                add!(e, -sign, VAR_ACT(r, v, t, p, s))
            end
        else
            error("EQ_UCRTP: unknown group type")
        end
        rhs = plain(constant) * lead * (-sign)               # RHS * LEAD(T) * (-1+2$BDUPX(BD))
        bd == FX ? row!(m, :EQE_UCRTP, (uc, r, t, p, grp, bd), e, EQ, rhs) :
                   row!(m, :EQN_UCRTP, (uc, r, t, p, grp, bd), e, LE, rhs)
    end
end

"""
    EQN_UCRTC (uc, kind, r, t, c, s, bd)                                         equcrtp.vda 103-121

Commodity-wise dynamic bound (UC_DYNBND with UC_COMNET / UC_COMPRD, moved by the preprocessor to
UC_COM(uc, NET/PRD, side, r, t, c, 'ANNUAL', 'UCN')): the annual net or gross production of c in
period t against the period before.

    Y(t)  {<=, >=}  LHS(uc,kind,r,t,c)^LEAD(t) * Y(t-1)  +  RHS(uc,kind,r,t,c) * LEAD(t)

Y is VAR_COMNET (kind NET) or VAR_COMPRD (PRD) at ANNUAL, where it exists (RHS_COMBAL / RHS_COMPRD);
the term of the period before needs RTC(r, t-1, c). Both LO and UP are `<=` rows with the terms of UP
flipped. There is no FX row: equ_ext.vda calls the block with FX as the second, `E`, pass, and
equcrtp.vda leaves it (`\$IFI %2==E \$GOTO FINISH`) before EQ_UCRTC.
"""
function eq_ucrtc!(m::Model)
    (; UC_COM, UC_DYNBND, RTC, RHS_COMBAL, RHS_COMPRD, LEAD) = m.d
    (; VAR_COMNET, VAR_COMPRD) = m.v
    (; LHS, RHS, UCN, ANNUAL, NET, PRD, LO, UP) = m.K
    isempty(UC_DYNBND) && return

    for ((uc, kind, side, r, t, c, s, grp), constant) in UC_COM
        (side == RHS && grp == UCN && s == ANNUAL) || continue
        (kind == NET || kind == PRD) || continue
        t in m.T || continue
        (m.stepped && !(t in m.sub)) && continue
        (m.rt !== nothing && !((r, t) in m.rt)) && continue      # FIXBOH: RTC(%R_T%,C), RT_PP of the region
        (r, t, c) in RTC || continue
        defined, var = kind == NET ? (RHS_COMBAL, VAR_COMNET) : (RHS_COMPRD, VAR_COMPRD)
        lead = plain(LEAD(t))
        # POWER(UC_COM(UC_N,COM_VAR,'LHS',RTC,S,'UCN'),LEAD(T)) * SUM(RHS_COMBAL(R,Y,C,S),%VARTT%_COMNET(R,Y,C,S %SWS%))
        coef = epspower(UC_COM(uc, kind, LHS, r, t, c, s, UCN), lead)
        tp = previous(m, t)
        for bd in (LO, UP)
            (uc, bd) in UC_DYNBND || continue
            sign = bd == UP ? -1.0 : 1.0                          # (1-2$BDUPX(BD))
            e = AE()
            if tp !== nothing && (r, tp, c) in RTC && (r, tp, c, s) in defined
                add!(e, sign * coef, var(r, tp, c, s))
            end
            (r, t, c, s) in defined && add!(e, -sign, var(r, t, c, s))
            rhs = plain(constant) * lead * (-sign)                # UC_COM('RHS') * LEAD(T) * (-1+2$BDUPX(BD))
            row!(m, :EQN_UCRTC, (uc, kind, r, t, c, s, bd), e, LE, rhs)
        end
    end
end
