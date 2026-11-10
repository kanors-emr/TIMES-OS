# SPDX-License-Identifier: GPL-3.0-or-later
"""rpt_objc.rpt lines 9-18 — the investment coefficient of new capacity.

rptlite clears COEF_OBJINV and rpt_obj.rpt rebuilds it here, before rptmisc reads
it for PAR_NCAPM and for the capacity groups of PAR_UCRTP.

%CAPJD% is OBJ_JD(R,CUR,K_EOH,JOT)* when coef_alt.lin runs (line 91), and empty when
CTST is ''. An empty token is a factor of 1. A missing OBJ_JD on the OBLONG path reads as 0.

The two statements:

    PAR_OBJCAP(OBJ_ICUR) = COR_SALVI/OBJ_DIVI *
        SUM(OBJ_SUMII, OBJ_JD * SUM(INVSPRED, (1-SALV_INV$OBJ_SUMS)*OBJ_DISC));
    COEF_OBJINV(RTP)$PRC_CAP = SUM(PERDINV, OBJ_DISC)/LEAD;
    COEF_OBJINV(RTP) $= SUM(RDCUR$PAR_OBJCAP, PAR_OBJCAP);

A currency loop that would write one period two different defaults stops here.
"""
from __future__ import annotations


def spread_factor(db, expr):
    """The %CAPJD% / %CAPWD% token. Empty with the classic objective (CTST ''), so the factor is 1.

    coef_alt.lin line 91 sets CAPJD and line 107 sets CAPWD, and eqobjinv.mod / eqobjfix.mod
    include that file only when CTST is not ''.
    """
    if db.ctl.get("CTST") == "":
        return "1"
    return expr


def coef_objinv(db):
    """COEF_OBJINV(R,T,P). Also drops marginals of technologies that are off."""
    if "M_VAR_NCAP" in db.sym and "RTP_OFF" in db.sym:
        # VAR_NCAP.M(RTP_OFF) = 0. A plain zero removes the record.
        db.zap("M_VAR_NCAP", "in_RTP_OFF(r, y, p)")
    db.declare("COEF_OBJINV", "par", ["R", "ALLYEAR", "PRC"])
    db.clear("COEF_OBJINV")
    _default(db)
    _from_investment(db)
    db.x("create or replace temp table coef_rtp_cnt as select '' as r, '' as y, '' as p, 0.0 as value where false")
    if cnt(db):
        _cost_coefficient(db)


def cnt(db):
    """CNT = RPT_OPT('NCAP','1') (line 9); BENCOST YES would also set it, and is refused (switches.py)."""
    if "RPT_OPT" not in db.sym:
        return 0
    return db.q1("select value from RPT_OPT where u = 'NCAP' and j = '1'") or 0


def _cost_coefficient(db):
    """Lines 20-75 with CNT: the cost of one unit of new capacity (R,T,P) in the objective, net of its
    salvage, into the work table coef_rtp_cnt (GAMS COEF_RTP), which the levelized cost (rptmisc NCAP.1) reads.

      PAR_OBJCAP(OBJ_ICUR(R,T,P,CUR)) = COR_SALVI/OBJ_DIVI * SUM(OBJ_SUMII, %CAPJD%
            SUM(INVSPRED(K_EOH,JOT,Y,K), OBJ_DISC(R,K,CUR)*(OBJ_ICOST+OBJ_ITAX-OBJ_ISUB)(R,K,P,CUR)));
      PAR_OBJSAL(RTP(R,T,P),CUR)$RDCUR = COR_SALVD/OBJ_DIVIII * SUM(OBJ_SUMIII$OBJ_DCOST(R,T,P,CUR), OBJ_DISC(R,Y)*OBJ_DCOST(R,K));
      PAR_OBJCAP$PAR_OBJSAL += PAR_OBJSAL;                                       (decommissioning)
      PAR_OBJSAL(OBJ_FCUR(R,T,P,CUR)) = fixed costs per unit (OBJ_LIFE spread, or by age when RTP_ISHPR) / OBJ_DIVIV;
      PAR_OBJCAP$PAR_OBJSAL += PAR_OBJSAL;                                       (fixed O&M, taxes, subsidies)
      PAR_OBJSAL(RTP(R,T,P),CUR)$RDCUR = OBJSCC$OBJ_SUMS*OBJ_DCEOH*(1+(VAR_SCAP.L(R,T,'0',P)/RTP_CAPVL-1)$(NCAP_YES$RVPRL))
                                        + SALV_DEC$OBJ_SUMS3*OBJ_DCEOH + (decommissioning surveillance);
      COEF_RTP(R,T,P) $= SUM(CUR$PAR_OBJCAP, ROUND(PAR_OBJCAP-PAR_OBJSAL,7));
    T is MILESTONYR. NCAP_DLAGC (OBJ_DLAGC, the surveillance terms) is refused by the preprocessor, so those
    terms are 0. PASTSUM of the capacity-related flows (lines 63-73) feeds BENCOST only and is cleared at
    FINISH, so it is not computed. RTP_ISHPR is the set rpt_obj.rpt line 70 extended (VNRET)."""
    jd = spread_factor(db, "v_OBJ_JD(i.r, i.cur, u.y2, u.age2)")
    wd = spread_factor(db, "v_OBJ_WD(i.r, i.cur, u.y, u.age, sp.y3)")
    keoh = "and in_K_EOH(u.y2)" if "K_EOH" in db.sym else ""
    parts = []
    # investment
    if all(n in db.sym for n in ("OBJ_ICUR", "COR_SALVI", "OBJ_DIVI", "OBJ_SUMII", "INVSPRED", "OBJ_DISC")):
        cost = " + ".join(f"v_{n}(i.r, i.p, i.cur, sp.y3)" for n in ("OB_ICOST", "OB_ITAX") if n in db.sym) or "0"
        if "OB_ISUB" in db.sym:
            cost += " - v_OB_ISUB(i.r, i.p, i.cur, sp.y3)"
        if "OBJ_SICW" in db.sym and "OB_ICOST" in db.sym:
            # line 30, stochastic TIMES with S_NCAP_COST (OBJ_SICW: rptobj.sic):
            #   +SUM(SW_TSW(SOW,T,WW)$OBJ_SIC(R,T,P,WW),OBJ_SIC(R,T,P,WW)*OBJ_ICOST(R,K,P,CUR)*(1-SALV_INV(R,T,P,Y)))
            cost += (" + v_OBJ_SICW(i.r, i.y, i.p) * v_OB_ICOST(i.r, i.p, i.cur, sp.y3)"
                     " * (1 - v_SALV_INV(i.r, i.y, i.p, sp.y2))")
        parts.append(f"""
            select i.r, i.y, i.p, i.cur, 'cap' as k,
                   (v_COR_SALVI(i.r, i.y, i.p, i.cur) / v_OBJ_DIVI(i.r, i.y, i.p))
                   * sum({jd} * v_OBJ_DISC(i.r, sp.y3, i.cur) * ({cost})) as value
            from OBJ_ICUR i
            join OBJ_SUMII u on u.r = i.r and u.y = i.y and u.p = i.p
            join INVSPRED sp on sp.y = u.y2 and sp.age = u.age2
            where in_MILESTONYR(i.y) and v_OBJ_DIVI(i.r, i.y, i.p) <> 0 {keoh}
            group by i.r, i.y, i.p, i.cur""")
    # decommissioning
    if all(n in db.sym for n in ("OBJ_SUMIII", "OB_DCC", "COR_SALVD", "OBJ_DIVIII", "RDCUR")) and db.card("OBJ_SUMIII"):
        parts.append("""
            select t.r, t.y, t.p, d.cur, 'add' as k,
                   (v_COR_SALVD(t.r, t.y, t.p, d.cur) / v_OBJ_DIVIII(t.r, t.y, t.p))
                   * sum(v_OBJ_DISC(t.r, u.y4, d.cur) * v_OB_DCC(t.r, t.p, d.cur, u.y3)) as value
            from RTP t
            join RDCUR d on d.r = t.r
            join OBJ_SUMIII u on u.r = t.r and u.y = t.y and u.p = t.p
            where in_MILESTONYR(t.y) and v_OBJ_DIVIII(t.r, t.y, t.p) <> 0
              and (in_OB_DCC(t.r, t.p, d.cur, t.y) or v_OB_DCC(t.r, t.p, d.cur, t.y) <> 0)
            group by t.r, t.y, t.p, d.cur""")
    # fixed O&M, fixed taxes and subsidies
    if all(n in db.sym for n in ("OBJ_FCUR", "OBJ_SUMIV", "INVSPRED", "OBJ_DIVIV")):
        fom = " + ".join(f"v_{n}(i.r, i.p, i.cur, sp.y3)" for n in ("OB_FOM", "OB_FTX") if n in db.sym) or "0"
        if "OB_FSB" in db.sym:
            fom += " - v_OB_FSB(i.r, i.p, i.cur, sp.y3)"
        ishpr = "in_RTP_ISHPR(i.r, i.y, i.p)" if "RTP_ISHPR" in db.sym else "false"
        parts.append(f"""
            select i.r, i.y, i.p, i.cur, 'add' as k,
                   sum(v_OBJ_LIFE(sp.y2, i.r, u.age, u.age2, i.cur) * {wd} * ({fom})) / v_OBJ_DIVIV(i.r, i.y, i.p) as value
            from OBJ_FCUR i
            join OBJ_SUMIV u on u.r = i.r and u.y2 = i.y and u.p = i.p
            join INVSPRED sp on sp.y = u.y and sp.age = u.age
            where in_MILESTONYR(i.y) and not {ishpr} and v_OBJ_DIVIV(i.r, i.y, i.p) <> 0
            group by i.r, i.y, i.p, i.cur""")
        if "RTP_ISHPR" in db.sym and db.card("RTP_ISHPR"):
            def shaped(cost, grp):
                if cost not in db.sym:
                    return "0"
                extra = "0"
                if "RTP_SHAPE" in db.sym and db.card("RTP_SHAPE"):
                    extra = f"""coalesce((select sum(v_SHAPE(sh.j2, op.age2) * v_MULTI(sh.j3, ye.y) - 1) from RTP_SHAPE sh
                                 where sh.r = i.r and sh.y = i.y and sh.p = i.p and sh.j = '{grp}'), 0)"""
                return f"v_{cost}(i.r, i.p, i.cur, sp.y3) * (1 + {extra})"
            parts.append(f"""
                select i.r, i.y, i.p, i.cur, 'add' as k,
                       sum(v_OBJ_DISC(i.r, ye.y, i.cur) * {wd}
                           * ({shaped('OB_FOM', '1')} + {shaped('OB_FTX', '2')} - {shaped('OB_FSB', '3')}))
                       / v_OBJ_DIVIV(i.r, i.y, i.p) as value
                from OBJ_FCUR i
                join OBJ_SUMIV u on u.r = i.r and u.y2 = i.y and u.p = i.p
                join INVSPRED sp on sp.y = u.y and sp.age = u.age
                join OPYEAR op on op.age = u.age2
                join Y_EOH ye on try_cast(ye.y as integer) = try_cast(sp.y2 as integer) + try_cast(op.age2 as integer) - 1
                where in_MILESTONYR(i.y) and in_RTP_ISHPR(i.r, i.y, i.p) and v_OBJ_DIVIV(i.r, i.y, i.p) <> 0
                group by i.r, i.y, i.p, i.cur""")
    if not parts:
        return
    # PAR_OBJCAP: the investment term, then the additions where they are not zero
    db.x(f"""create or replace temp table objcap_cnt as
             select r, y, p, cur, sum(value) as value from ({' union all '.join(parts)}) t
             group by r, y, p, cur""")
    # salvage
    sal = []
    if all(n in db.sym for n in ("OBJSCC", "OBJ_SUMS", "OBJ_DCEOH")):
        share = "1"
        if all(n in db.sym for n in ("RVPRL", "L_VAR_SCAP", "NCAP_YES")):
            share = """(1 + case when in_NCAP_YES(t.r, t.y, t.p) and v_RVPRL(t.r, t.y, t.p) <> 0
                             then v_L_VAR_SCAP(t.r, t.y, '0', t.p) / (v_L_VAR_NCAP(t.r, t.y, t.p) + v_NCAP_PASTI(t.r, t.y, t.p)) - 1
                             else 0 end)"""
        sal.append(f"""select t.r, t.y, t.p, t.cur, v_OBJSCC(t.r, t.y, t.p, t.cur) * v_OBJ_DCEOH(t.r, t.cur) * {share} as value
                       from OBJSCC t where in_OBJ_SUMS(t.r, t.y, t.p) and in_RDCUR(t.r, t.cur)""")
    if all(n in db.sym for n in ("SALV_DEC", "OBJ_SUMS3", "OBJ_DCEOH")):
        sal.append("""select t.r, t.y, t.p, t.cur, t.value * v_OBJ_DCEOH(t.r, t.cur) as value
                      from SALV_DEC t where in_OBJ_SUMS3(t.r, t.y, t.p) and in_RDCUR(t.r, t.cur)""")
    salq = f"select r, y, p, cur, sum(value) as value from ({' union all '.join(sal)}) s group by r, y, p, cur" if sal else \
        "select '' r, '' y, '' p, '' cur, 0.0 as value where false"
    db.x(f"""create or replace temp table coef_rtp_cnt as
             select c.r, c.y, c.p, sum(round(c.value - coalesce(s.value, 0), 7)) as value
             from objcap_cnt c
             left join ({salq}) s on s.r = c.r and s.y = c.y and s.p = c.p and s.cur = c.cur
             where c.value <> 0 and in_RTP(c.r, c.y, c.p)
             group by c.r, c.y, c.p""")
    db.x("delete from coef_rtp_cnt where value = 0")


def _default(db):
    """COEF_OBJINV(RTP(R,T,P))$PRC_CAP = SUM(PERDINV(T,Y), OBJ_DISC)/LEAD(T), per currency."""
    if not all(n in db.sym for n in ("RTP", "MILESTONYR", "PRC_CAP", "G_RCUR", "LEAD", "PERDINV", "OBJ_DISC")):
        return
    db.x("""
        create or replace temp table coef_base as
        select t.r, t.y, t.p, g.cur,
               sum(v_OBJ_DISC(t.r, pv.y2, g.cur) order by pv.y2) / v_LEAD(t.y) as value
        from RTP t
        join PRC_CAP c on c.r = t.r and c.p = t.p
        join G_RCUR g on g.r = t.r
        join PERDINV pv on pv.y = t.y
        where in_MILESTONYR(t.y) and v_LEAD(t.y) <> 0
        group by t.r, t.y, t.p, g.cur
    """)
    clash = db.q("""
        select r, y, p, min(value), max(value) from coef_base
        group by r, y, p
        having min(value) <> max(value)
        limit 3
    """)
    if clash:
        raise RuntimeError(
            "G_RCUR writes one COEF_OBJINV default from two currencies; "
            f"GAMS keeps the last. First keys: {clash}")
    db.put("COEF_OBJINV", """
        select r, y, p, any_value(value) as value from coef_base
        where value <> 0
        group by r, y, p
    """)


def _from_investment(db):
    """The $= overwrite from the discounted investment spread.

    The sum is OBJ_SUMII(R,T,P,LIFE,K_EOH,JOT), so the commissioning year has to
    belong to K_EOH. A lead time that lands past the last year of that set
    (REG1 ELCNNNUC01 in 2050 commissions in 2054; K_EOH ends at 2052) adds
    nothing, and the default discount stays.
    """
    need = ("OBJ_ICUR", "COR_SALVI", "OBJ_DIVI", "OBJ_SUMII", "INVSPRED", "OBJ_DISC", "RDCUR", "RTP", "MILESTONYR")
    if not all(n in db.sym for n in need):
        return
    jd = spread_factor(db, "v_OBJ_JD(i.r, i.cur, u.y2, u.age2)")
    salv = "coalesce(v_SALV_INV(i.r, i.y, i.p, sp.y2), 0)" if "SALV_INV" in db.sym else "0"
    sums = "in_OBJ_SUMS(i.r, i.y, i.p)" if "OBJ_SUMS" in db.sym else "false"
    keoh = "and in_K_EOH(u.y2)" if "K_EOH" in db.sym else ""
    db.x(f"""
        create or replace temp table par_objcap_w as
        select i.r, i.y, i.p, i.cur,
               (v_COR_SALVI(i.r, i.y, i.p, i.cur) / v_OBJ_DIVI(i.r, i.y, i.p)) * coalesce(sum(
                   {jd} * (1 - case when {sums} then {salv} else 0 end)
                   * v_OBJ_DISC(i.r, sp.y3, i.cur)
                   order by sp.y3
               ), 0) as value
        from OBJ_ICUR i
        join OBJ_SUMII u on u.r = i.r and u.y = i.y and u.p = i.p
        join INVSPRED sp on sp.y = u.y2 and sp.age = u.age2
        where v_OBJ_DIVI(i.r, i.y, i.p) <> 0
          {keoh}
        group by i.r, i.y, i.p, i.cur
    """)
    # $= : a zero sum leaves the default in place.
    db.put("COEF_OBJINV", """
        select w.r, w.y, w.p, sum(w.value) as value
        from par_objcap_w w
        where in_RTP(w.r, w.y, w.p) and in_MILESTONYR(w.y)
          and in_RDCUR(w.r, w.cur) and w.value <> 0
        group by w.r, w.y, w.p
    """, zero="skip")
