# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_CUMFLO(r,p,c,y1,y2)                                                      eqcumflo.mod

Cumulative flow (or activity, c = ACT) of a process between the years y1 and y2. Each period
counts with the number of its years that fall in the interval.

    SUM(t, years(t in [y1,y2]) * SUM((v,s), flow(r,v,t,p,c,s)))  =  VAR_CUMFLO(r,p,c,y1,y2) * CUFSCAL

The bound (FLO_CUM) is on the variable. An upper bound of zero removes the variable.
"""
function eq_cumflo!(m::Model)
    (; RPC_CUMFLO, RP, RPC, RP_STD, RP_IRE, RPC_IRE, RTP_VARA, B, E, FLO_CUM) = m.d
    (; vintages, flow_s, prc_ts) = m.ix
    (; VAR_ACT, VAR_CUMFLO) = m.v
    (; ACT, IMP, EXP, UP) = m.K
    sow_w1_scum(m) || return                # SPINES, %SCUM%: Q_CUMFLO of SOW '1' only (recurrin.stc 115)

    for (r, p, c, y1, y2) in RPC_CUMFLO
        (r, p) in RP || continue
        first_year, last_year = year(m.L, y1), year(m.L, y2)

        # (%SCUM%: SUM(SW_TSW(SOW(WW),T,WW),SW_TPROB(T,WW)*(..)) and %VARTT%_ACT: the expected value, sow_expected)
        total = sow_expected(m) do
            e = AE()
            for t in m.T
                years = min(E[t], last_year) - max(B[t], first_year) + 1
                years > 0 || continue
                w = years / m.cufscal
                if (r, p, c) in RPC
                    for v in vintages[r, t, p], s in flow_s[r, t, p, c]
                        (r, p) in RP_STD && add!(e, w, flow(m, r, v, t, p, c, s))
                        if (r, p) in RP_IRE
                            for ie in (IMP, EXP)
                                (r, p, c, ie) in RPC_IRE && add!(e, w, trade(m, r, v, t, p, c, s, ie))
                            end
                        end
                    end
                end
                if c == ACT && (r, t, p) in RTP_VARA
                    for v in vintages[r, t, p], s in prc_ts[r, p]
                        add!(e, w, VAR_ACT(r, v, t, p, s))
                    end
                end
            end
            e
        end

        # VAR_CUMFLO(R,P,C,ALLYEAR,LL %SWT%)$(MAPVAL(%SW1%FLO_CUM(R,P,C,ALLYEAR,LL,'UP'%SW2%)) NE 8): with STAGES too the
        # deterministic FLO_CUM (eqcumflo.mod 15-16: $SETLOCAL SW1 '' shadows the $SET SW1 'S_' that follows it)
        excluded = has(FLO_CUM, r, p, c, y1, y2, UP) && plain(FLO_CUM(r, p, c, y1, y2, UP)) == 0
        row!(m, :EQ_CUMFLO, (r, p, c, y1, y2), total, ==, excluded ? 0.0 : VAR_CUMFLO(r, p, c, y1, y2))
    end
end
