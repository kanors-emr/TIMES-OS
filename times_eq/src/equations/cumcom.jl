# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_CUMNET / EQ_CUMPRD (r,c,y1,y2)                                           eqcumcom.mod

Cumulative net (VAR_COMNET) or gross (VAR_COMPRD) production of commodity c between the years y1
and y2 (COM_CUMNET, COM_CUMPRD; ppmain.mod lines 1021-1025). Each period counts with the number of
its years that fall in the interval (the non-LIN objectives; OBJ LIN stops in the preprocessor):

    SUM(t in RTC_NET / RTC_PRD, E(t) >= y1, B(t) <= y2,
        years(t in [y1,y2]) * SUM(s in RTCS_VARC, VAR_COMNET / VAR_COMPRD(r,t,c,s))) / CUCSCAL
        =  VAR_CUMCOM(r,c,NET/PRD,y1,y2)

The bounds (bnd_cum.mod) are on the variable, scaled by 1/CUCSCAL.
"""
const CUCSCAL = 1000.0

function eq_cumcom!(m::Model)
    (; RC_CUMCOM, RC, RTC_NET, RTC_PRD, B, E) = m.d
    (; varc_ts) = m.ix
    (; VAR_COMNET, VAR_COMPRD, VAR_CUMCOM) = m.v
    (; NET, PRD) = m.K
    sow_w1_scum(m) || return                # SPINES, %SCUM%: Q_CUMNET, Q_CUMPRD of SOW '1' only (recurrin.stc 113-114)

    for cv in (NET, PRD), (r, cv_, y1, y2, c) in RC_CUMCOM
        cv_ == cv || continue
        (r, c) in RC || continue
        rtc, var, name = cv == NET ? (RTC_NET, VAR_COMNET, :EQ_CUMNET) : (RTC_PRD, VAR_COMPRD, :EQ_CUMPRD)
        first_year, last_year = year(m.L, y1), year(m.L, y2)
        # (%SCUM%: %VARTT%_COM%2(R,T,C,S %SWS%) is the expected value over the SOWs, sow_expected)
        total = sow_expected(m) do
            e = AE()
            for t in m.T
                (r, t, c) in rtc || continue
                (E[t] >= first_year && B[t] <= last_year) || continue
                w = max(0, min(E[t], last_year) - max(B[t], first_year) + 1) / CUCSCAL
                for s in varc_ts[r, t, c]
                    add!(e, w, var(r, t, c, s))
                end
            end
            e
        end
        row!(m, name, (r, c, y1, y2), total, ==, VAR_CUMCOM(r, c, cv, y1, y2))
    end
end
