# SPDX-License-Identifier: GPL-3.0-or-later
"""rpt_obj.rpt — the objective report rptlite.rpt line 149 calls, then rpt_objc.rpt.

Veda sets SOLVEDA locally to 1 and calls rptlite with a prefix, but inside rptlite the
global SOLVEDA is still 'YES', so line 10 shifts the prefix and the sow index off.
The parameters are CAP_NEW(R,T,P,TT,SYSUC) and REG_WOBJ(R,ITEM,CUR).

DISCSHIFT is 0.5 when MID_YEAR is YES (maindrv.mod), else 0 (eqobjinv.mod).
OBJ_ICOST and the other filled costs are the OB_* caches from fillcost.gms:
OBJ_ICOST(R,K,P,CUR) = OB_ICOST(R,P,CUR,K). A missing cache reads as 0.
%CAPJD% and %CAPWD% are OBJ_JD and OBJ_WD when CTST is not '' (coef_alt.lin). With the
classic objective the tokens are empty, so the factor is 1. A missing OBLONG factor reads as 0.
Set T is MILESTONYR. STAGES, ETL and TIMESED are not set; VNRET (early retirement) is, on
a model with early retirement: lines 66-72, _vnret.
"""
from __future__ import annotations

from . import cost_ann, eqobjvar, rptobjc


def run(db, coef=True):
    """NCAP_YES, CAP_NEW, REG_WOBJ, then the investment coefficient (coef=False: rpt_obj.rpt called with 0 as its
    fifth argument, line 148 `$IFI %5==0 $EXIT`, as rpt_ext.mlf does). Returns names written."""
    _hold_currencies(db)
    _empty_veda(db)
    _ncap_yes(db)
    _cap_new(db)
    _investment_rest(db)
    _pv_investment(db)
    _fixed(db)
    _pv_fixed(db)
    eqobjvar.variable_costs(db)
    # Line 127: UNCD1('1') = MY_F+ACL.
    if my_f(db) or cost_ann.levelized(db)[1]:
        eqobjvar.cost_column(db)
    _pv_variable(db)
    _variable_rest(db)
    db.no_objc = not coef
    if coef:
        rptobjc.coef_objinv(db)
    _restore_ncap_yes(db)
    return ["NCAP_YES", "CAP_NEW", "REG_WOBJ", "CST_PVP", "CST_PVC", "PAR_NCAPR",
            "RTP_OBJ", "RTP_NPV", "COEF_CRF", "PAR_ACTC", "PAR_FLOC", "PAR_COMC", "COEF_OBJINV"]


def my_f(db):
    """MY_F = ROUND(RPT_OPT('OBJ','1')) (rpt_obj.rpt line 15): the discounted costs by process."""
    if "RPT_OPT" not in db.sym:
        return 0
    v = db.q1("select value from RPT_OPT where u = 'OBJ' and j = '1'")
    return round(v) if v else 0


def objective_gap(db):
    """(sum of REG_WOBJ, OBJZ level, relative gap). A test, not a correction."""
    if "REG_WOBJ" not in db.sym or "L_OBJZ" not in db.s:
        return None
    total = db.q1('select coalesce(sum(value), 0) from "REG_WOBJ"') or 0.0
    objz = db.s["L_OBJZ"]
    scale = max(abs(total), abs(objz), 1.0)
    return total, objz, abs(total - objz) / scale


def sic(db, r, y, p):
    """The investment cost multiplier of the SOW being reported, stochastic TIMES with S_NCAP_COST (rpt_obj.rpt 17,
    cost_ann.rpt 40): %SIC% is *(1+PASTSUM(R,V,P)), PASTSUM(R,T,P) = SUM(SW_TSW(SOW,T,WW),OBJ_SIC(R,T,P,WW)) held as
    OBJ_SICW. Without it, 1."""
    if "OBJ_SICW" not in db.sym:
        return "1"
    return f"(1 + v_OBJ_SICW({r}, {y}, {p}))"


def _restore_ncap_yes(db):
    """cost_ann.rpt lines 15 and 121. The report's state is that after this restore.

        OBJ_YES(NCAP_YES) = YES;
        NCAP_YES(OBJ_YES) = YES;

    OBJ_YES starts as the fixed-cost set (eqobjfix.mod, OPTION OBJ_YES < OBJ_FCUR).
    Line 42 drops residual vintages from NCAP_YES; line 121 puts them back.
    """
    if "OBJ_YES" not in db.sym:
        return
    db.add("NCAP_YES", "select r, y, p from OBJ_YES")


def _discshift(db):
    return 0.5 if db.ctl.get("MID_YEAR") else 0.0


def _hold_currencies(db):
    """rptlite.rpt 126-127. Drop costs in a non-reporting currency, and copy SUB onto TAX."""
    if "OBJ_VFLO" not in db.sym:
        return
    db.remove("OBJ_VFLO", where="not in_RDCUR(r, cur)")
    db.add("OBJ_VFLO", """
        select r, p, c, cur, 'TAX' as ucn from OBJ_VFLO where ucn = 'SUB'
    """)


def _ncap_yes(db):
    """Lines 11-14. Z is 0 when RPT_OPT is unset, so the test is RTP_CAPVL > 0.

        RTP_CAPVL(RTP) = VAR_NCAP.L + NCAP_PASTI;
        NCAP_YES(RTP)$(RTP_CAPVL > 0) $= RTP_CAPVL;

    The index is the whole RTP set, not RTP(R,T,P). Past investment years are in RTP
    and not in T (MILESTONYR). COEF_RTP on line 29 is the one restricted to T.
    """
    db.declare("NCAP_YES", "set", ["R", "ALLYEAR", "P"])
    db.clear("NCAP_YES")
    # Z=MAX(0,RPT_OPT('NCAP','9')$RPT_OPT('CAP','9')/8); the test is RTP_CAPVL > Z-Z$NCAP_PASTI:
    # new capacity below Z/8 is not reported, past investments are whatever their size.
    z = 0.0
    if "RPT_OPT" in db.sym and (db.q1("select value from RPT_OPT where u = 'CAP' and j = '9'") or 0):
        z = max(0.0, (db.q1("select value from RPT_OPT where u = 'NCAP' and j = '9'") or 0) / 8)
    db.add("NCAP_YES", f"""
        select t.r, t.y, t.p from RTP t
        where v_L_VAR_NCAP(t.r, t.y, t.p) + v_NCAP_PASTI(t.r, t.y, t.p)
              > case when in_NCAP_PASTI(t.r, t.y, t.p) then 0 else {z} end
    """)


def _cap_new(db):
    """Lines 20-45. New capacity, the hurdle rate, then the lump-sum cost.

    The clear of COEF_CRF is inside the J loop (line 44). J is ordered '1' then '2',
    so the tax column (J='1', LUMPIX) still sees the hurdle rate and the investment
    column (J='2', LUMPINV) sees it already cleared.
    """
    db.declare("CAP_NEW", "par", ["R", "ALLYEAR", "P", "T", "SYSUC"])
    db.clear("CAP_NEW")
    db.x("""
        create or replace temp table coef_rtp as
        select t.r, t.y, t.p, v_L_VAR_NCAP(t.r, t.y, t.p) as value
        from RTP t
        where in_PRC_CAP(t.r, t.p) and in_NCAP_YES(t.r, t.y, t.p)
          and in_MILESTONYR(t.y) and in_L_VAR_NCAP(t.r, t.y, t.p)
    """)
    # CAP_NEW(RVPT, INSTCAP) $= COEF_RTP;  then the non-OBJ_2A row replaces year T.
    db.put("CAP_NEW", """
        select v.r, v.y, v.p, v.y2, 'INSTCAP' as sysuc, c.value as value
        from RVPT v
        join coef_rtp c on c.r = v.r and c.y = v.y and c.p = v.p
    """, zero="skip")
    # Line 32 is a plain '='. COEF_RPTI is EPS on some processes, and an EPS factor times
    # the level is stored. A missing COEF_RPTI is a true zero and the '=' deletes it.
    db.put("CAP_NEW", """
        select c.r, c.y, c.p, c.y as y2, 'INSTCAP' as sysuc, v_COEF_RPTI(c.r, c.y, c.p) * c.value as value
        from coef_rtp c
        where not in_OBJ_2A(c.r, c.y, c.p) and in_COEF_RPTI(c.r, c.y, c.p)
    """, zero="eps")
    _hurdle(db)
    _lump_table(db)
    _sysplit(db)
    _lump_column(db, "1")
    # IF(NOT MY_F, OPTION CLEAR=COEF_CRF). MY_F = ROUND(RPT_OPT('OBJ','1')).
    if not my_f(db):
        db.clear("COEF_CRF")
    _lump_column(db, "2")


def _hurdle(db):
    """Lines 21-23. Only where NCAP_DRATE > 0. -0.5$NCAP_ILED is -0.5 when the record exists."""
    db.declare("COEF_CRF", "par", ["R", "ALLYEAR", "P", "CUR"])
    db.clear("COEF_CRF")
    z = _discshift(db)
    db.put("COEF_CRF", f"""
        select i.r, i.y, i.p, i.cur,
               greatest(0, 1 - (
                   ((1 - power(1 + dr, -life)) / nullif(1 - power(1 + rfr, -life), 0))
                   / nullif(dr / rfr * power((1 + dr) / (1 + rfr),
                        least({z} - 1, case when in_NCAP_ILED(i.r, i.y, i.p) then -0.5 else 0 end)), 0)
               )) as value
        from (
            select i.r, i.y, i.p, i.cur,
                   v_NCAP_DRATE(i.r, i.y, i.p) as dr,
                   v_OBJ_RFR(i.r, i.y, i.cur) as rfr,
                   v_NCAP_ELIFE(i.r, i.y, i.p) as life
            from OBJ_ICUR i
            where in_NCAP_YES(i.r, i.y, i.p) and v_NCAP_DRATE(i.r, i.y, i.p) > 0
        ) i
        where rfr <> 0 and life <> 0 and (1 + dr) > 0 and (1 + rfr) > 0
    """)


def _lump_table(db):
    """Lines 36-41, the undiscounted lump, for J='1' (tax-subsidy) and J='2' (investment).

    The exponent is DISCSHIFT, and when COEF_ILED exists it collapses to
    MAX(0, -LOG(OBJ_DIVI)/LOG(1+G_DRATE) - COEF_ILED). The ETL term on line 37 is not used.
    """
    z = _discshift(db)
    den = f"""
        case
            when in_COEF_ILED(i.r, i.y, i.p) and v_OBJ_DIVI(i.r, i.y, i.p) > 0
                 and (1 + v_G_DRATE(i.r, i.y, i.cur)) > 0
                 and ln(1 + v_G_DRATE(i.r, i.y, i.cur)) <> 0
            then power(1 + v_G_DRATE(i.r, i.y, i.cur),
                       greatest(0, -ln(v_OBJ_DIVI(i.r, i.y, i.p)) / ln(1 + v_G_DRATE(i.r, i.y, i.cur))
                                   - v_COEF_ILED(i.r, i.y, i.p)))
            when (1 + v_G_DRATE(i.r, i.y, i.cur)) > 0
            then power(1 + v_G_DRATE(i.r, i.y, i.cur), {z})
            else null
        end
    """
    base = f"""
        from OBJ_ICUR i
        join coef_rtp c on c.r = i.r and c.y = i.y and c.p = i.p
        join OBJ_SUMII u on u.r = i.r and u.y = i.y and u.p = i.p
        join INVSPRED sp on sp.y = u.y2 and sp.age = u.age2
        where in_NCAP_YES(i.r, i.y, i.p) and v_OBJ_DIVI(i.r, i.y, i.p) <> 0
    """
    db.x(f"""
        create or replace temp table lump_obj as
        select j, r, y, p, cur, sum(value) as value from (
            select '1' as j, i.r, i.y, i.p, i.cur,
                   (v_OB_ITAX(i.r, i.p, i.cur, sp.y3) - v_OB_ISUB(i.r, i.p, i.cur, sp.y3))
                   * c.value * v_COR_SALVI(i.r, i.y, i.p, i.cur) / v_OBJ_DIVI(i.r, i.y, i.p) / ({den}) as value
            {base}
            union all
            select '2' as j, i.r, i.y, i.p, i.cur,
                   v_OB_ICOST(i.r, i.p, i.cur, sp.y3) * {sic(db, "i.r", "i.y", "i.p")}
                   * c.value * v_COR_SALVI(i.r, i.y, i.p, i.cur) / v_OBJ_DIVI(i.r, i.y, i.p) / ({den}) as value
            {base}
        ) s
        where value is not null
        group by j, r, y, p, cur
    """)


def _sucmap(db):
    """rptlite.rpt lines 12 and 55. The prefix is empty.

    solsysd.v3 maps each system label to itself:
        SYSUCMAP(SYSUC,ITEM) / VAR.VAR, INV+.INV+, ... /;
    and the lump columns are
        SUCMAP(J,SYSUC) / 2.LUMPINV, 2.INV+, 1.LUMPIX, 1.INVX+ /;
    """
    labels = ("VAR", "VARX", "INV", "INVX", "INV+", "INVX+", "FIX", "FIXX",
              "IRE", "COM", "ACT", "FLO", "ELS", "DAM", "DAS", "DAM-EXT+")
    db.declare("SYSUCMAP", "set", ["SYSUC", "*"])
    listed = ", ".join(f"('{lab}')" for lab in labels)
    db.add("SYSUCMAP", f"select u as sysuc, u from (values {listed}) t(u)")
    if "SUCMAP" in db.sym and db.card("SUCMAP"):
        return
    db.declare("SUCMAP", "set", ["J", "SYSUC"])
    db.add("SUCMAP", """
        select j, sysuc from (values
            ('2', 'LUMPINV'), ('2', 'INV+'), ('1', 'LUMPIX'), ('1', 'INVX+')
        ) t(j, sysuc)
    """)


def _sysplit(db):
    """SYSPLIT(SYSUC) = 1 - SUM(SYSUCMAP(SYSUC,ITEM), 1). A label with no map row is 1."""
    _sucmap(db)
    db.x("""
        create or replace temp table sysplit as
        select m.sysuc, 1 - count(s.sysuc) as spl
        from (select distinct sysuc from SUCMAP) m
        left join SYSUCMAP s on s.sysuc = m.sysuc
        group by m.sysuc
    """)


def _lump_column(db, j):
    """CAP_NEW(R,T,P,TT,SYSUC)$(CAP_NEW INSTCAP $ SUCMAP(J)) = SUM(RDCUR, RTP_OBJ * ABS(SYSPLIT-COEF_CRF)).

    An EPS new capacity makes that product EPS, and the plain '=' stores it. INV+ and INVX+
    have SYSPLIT 0, so with the hurdle rate cleared the product is a true zero and is deleted.
    """
    db.put("CAP_NEW", f"""
        select a.r, a.y, a.p, a.y2, m.sysuc,
               sum(o.value * abs(coalesce(sp.spl, 1) - v_COEF_CRF(a.r, a.y, a.p, o.cur))) as value
        from CAP_NEW a
        join SUCMAP m on m.j = '{j}'
        join lump_obj o on o.j = '{j}' and o.r = a.r and o.y = a.y and o.p = a.p
        left join sysplit sp on sp.sysuc = m.sysuc
        where a.sysuc = 'INSTCAP' and in_RDCUR(o.r, o.cur)
        group by a.r, a.y, a.p, a.y2, m.sysuc
    """)
    # ITAX - ISUB, or ICOST, is EPS when the record exists and its value is 0.
    # EPS times a nonzero factor is stored; a missing cost is a true zero and is deleted.
    if j == "1":
        cost_eps = ("(in_OB_ITAX(i.r, i.p, i.cur, sp.y3) or in_OB_ISUB(i.r, i.p, i.cur, sp.y3))"
                    " and v_OB_ITAX(i.r, i.p, i.cur, sp.y3) - v_OB_ISUB(i.r, i.p, i.cur, sp.y3) = 0")
        cost_real = "v_OB_ITAX(i.r, i.p, i.cur, sp.y3) - v_OB_ISUB(i.r, i.p, i.cur, sp.y3) <> 0"
    else:
        cost_eps = "in_OB_ICOST(i.r, i.p, i.cur, sp.y3) and v_OB_ICOST(i.r, i.p, i.cur, sp.y3) = 0"
        cost_real = "v_OB_ICOST(i.r, i.p, i.cur, sp.y3) <> 0"
    db.put("CAP_NEW", f"""
        select a.r, a.y, a.p, a.y2, m.sysuc, 0 as value
        from CAP_NEW a
        join SUCMAP m on m.j = '{j}'
        join coef_rtp c on c.r = a.r and c.y = a.y and c.p = a.p
        join sysplit sp on sp.sysuc = m.sysuc and sp.spl = 1
        where a.sysuc = 'INSTCAP'
          and not exists (
              select 1 from CAP_NEW b
              where b.r = a.r and b.y = a.y and b.p = a.p and b.y2 = a.y2 and b.sysuc = m.sysuc
          )
          and exists (
              select 1 from OBJ_ICUR i
              join OBJ_SUMII u on u.r = i.r and u.y = i.y and u.p = i.p
              join INVSPRED sp on sp.y = u.y2 and sp.age = u.age2
              where i.r = a.r and i.y = a.y and i.p = a.p and in_RDCUR(i.r, i.cur)
                and v_OBJ_DIVI(i.r, i.y, i.p) <> 0
                and ((c.value = 0 and ({cost_eps} or {cost_real}))
                     or (c.value <> 0 and {cost_eps}))
          )
    """, zero="eps")


def _investment_rest(db):
    """Lines 50-64 and 75. Discounted tax is RTP_OBJ('2'); INVX is its sum. The investment
    column RTP_OBJ('1') is kept for the annual-cost step and is not part of INVX.
    """
    db.declare("RTP_OBJ", "par", ["J", "R", "ALLYEAR", "P", "CUR"])
    db.clear("RTP_OBJ")
    cap = "(v_L_VAR_NCAP(i.r, i.y, i.p) + v_OBJ_PASTI(i.r, i.y, i.p, i.cur))"
    salv = "(1 - v_SALV_INV(i.r, i.y, i.p, sp.y2))"
    common = f"""
        from OBJ_ICUR i
        join OBJ_SUMII u on u.r = i.r and u.y = i.y and u.p = i.p
        join INVSPRED sp on sp.y = u.y2 and sp.age = u.age2
        where in_NCAP_YES(i.r, i.y, i.p) and v_OBJ_DIVI(i.r, i.y, i.p) <> 0
    """
    jd = rptobjc.spread_factor(db, "v_OBJ_JD(i.r, i.cur, u.y2, u.age2)")
    # A tax and a subsidy that are EPS or missing (at least one EPS) give an EPS term; a sum with no nonzero
    # term and an EPS one is EPS, and the '=' stores it.
    rec = [f"in_{n}(i.r, i.p, i.cur, sp.y3)" for n in ("OB_ITAX", "OB_ISUB") if n in db.sym]
    eps = (f"({' or '.join(rec)}) and v_OB_ITAX(i.r, i.p, i.cur, sp.y3) = 0 and v_OB_ISUB(i.r, i.p, i.cur, sp.y3) = 0"
           if rec else "false")
    other = (f"{jd} * v_OBJ_DISC(i.r, sp.y3, i.cur) * {salv} * {cap} * v_COR_SALVI(i.r, i.y, i.p, i.cur)"
             f" / v_OBJ_DIVI(i.r, i.y, i.p)")
    db.x(f"""
        create or replace temp table obj_tax as
        select '2' as j, i.r, i.y, i.p, i.cur,
               sum({other} * (v_OB_ITAX(i.r, i.p, i.cur, sp.y3) - v_OB_ISUB(i.r, i.p, i.cur, sp.y3))) as value,
               max(case when ({eps}) and ({other}) <> 0 then 1 else 0 end) as eps
        {common}
        group by i.r, i.y, i.p, i.cur
    """)
    db.put("RTP_OBJ", "select j, r, y, p, cur, value from obj_tax where value <> 0 or eps = 1", zero="eps")
    # The decommissioning add is on column '1' only (lines 54-56). NCAP_OCOM is empty, and so is the
    # OBJ_SUMIVS term of line 57 (NCAP_DLAGC is refused by the preprocessor).
    decom = ""
    if "OBJ_SUMIII" in db.sym and db.card("OBJ_SUMIII"):
        decom = f"""
                union all
                select i.r, i.y, i.p, i.cur, 0.0,
                       v_OBJ_DISC(i.r, u.y4, i.cur) * (1 - v_SALV_INV(i.r, i.y, i.p, u.y2))
                       * {cap} / v_OBJ_DIVIII(i.r, i.y, i.p)
                       * v_COR_SALVD(i.r, i.y, i.p, i.cur) * v_OB_DCC(i.r, i.p, i.cur, u.y3)
                from OBJ_ICUR i
                join OBJ_SUMIII u on u.r = i.r and u.y = i.y and u.p = i.p
                where in_NCAP_YES(i.r, i.y, i.p) and v_OBJ_DIVIII(i.r, i.y, i.p) <> 0"""
    db.put("RTP_OBJ", f"""
        select '1' as j, i.r, i.y, i.p, i.cur, sum(spread) + sum(decom) as value
        from (
            select i.r, i.y, i.p, i.cur,
                   {jd} * v_OBJ_DISC(i.r, sp.y3, i.cur) * {salv}
                   * v_OB_ICOST(i.r, i.p, i.cur, sp.y3)
                   * {cap} * {sic(db, "i.r", "i.y", "i.p")} * v_COR_SALVI(i.r, i.y, i.p, i.cur) / v_OBJ_DIVI(i.r, i.y, i.p) as spread,
                   0.0 as decom
            {common}{decom}
        ) i
        group by i.r, i.y, i.p, i.cur
    """)
    _vnret(db)
    db.declare("REG_WOBJ", "par", ["REG", "ITEM", "CUR"])
    db.clear("REG_WOBJ")
    db.put("REG_WOBJ", """
        select r, 'INVX' as u, cur, sum(value) as value
        from RTP_OBJ where j = '2'
        group by r, cur
    """)


def vnret(db):
    """True when the model has early retirement (VNRET defined: the preprocessor's switch)."""
    return bool(getattr(db, "s", {}).get("VNRET"))


def _vnret(db):
    """Lines 66-72, taken when VNRET is defined (a model with early retirement):
      VAR_SCAP.L(R,T,'0',P)$(NCAP_FDR(R,T,P)$RVPRL(R,'0',P)$RVPRL(R,T,P)) = RTP_CAPVL(R,T,P);
      PAR_OBJCAP(OBJ_ICUR(NCAP_YES(R,V,P),CUR))$RVPRL(R,V,P)=OBJSCC*OBJ_DCEOH*(RTP_CAPVL-VAR_SCAP.L(R,V,'0',P))$OBJ_SUMS;
      RTP_OBJ('1',..)$PAR_OBJCAP = RTP_OBJ('1')+PAR_OBJCAP*(1-(1/(1+RTP_OBJ('1')/RTP_OBJ('2')))$(RTP_OBJ('2')>0));
      RTP_OBJ('2',..)$((RTP_OBJ('2')>0)$PAR_OBJCAP) = RTP_OBJ('2')+PAR_OBJCAP/(1+RTP_OBJ('1')/RTP_OBJ('2'));
      RTP_ISHPR(RTP(R,V,P))$PRC_RCAP(R,P)=YES;
    and %TMP% becomes the retired share, (1-(VAR_SCAP.L(R,V,Y,P)/PASTSUM/OBJ_DIVIV)$PRC_RCAP), in the fixed costs.
    Line 69 reads RTP_OBJ('1') as line 68 left it. RTP_ISHPR stays extended: rpt_objc.rpt reads it too."""
    if not vnret(db):
        return
    capvl = "(v_L_VAR_NCAP(r, y, p) + v_NCAP_PASTI(r, y, p))"
    if all(n in db.sym for n in ("NCAP_FDR", "RVPRL", "L_VAR_SCAP")) and db.card("NCAP_FDR"):
        db.put("L_VAR_SCAP", f"""
            select r, y, '0' as y2, p, {capvl} as value from NCAP_FDR
            where v_RVPRL(r, '0', p) <> 0 and v_RVPRL(r, y, p) <> 0
        """)
    if all(n in db.sym for n in ("OBJSCC", "OBJ_DCEOH", "OBJ_SUMS", "RVPRL", "OBJ_ICUR")):
        scap0 = "v_L_VAR_SCAP(i.r, i.y, '0', i.p)" if "L_VAR_SCAP" in db.sym else "0"
        db.x(f"""create or replace temp table vn_objcap as
                 select i.r, i.y, i.p, i.cur,
                        v_OBJSCC(i.r, i.y, i.p, i.cur) * v_OBJ_DCEOH(i.r, i.cur)
                        * case when in_OBJ_SUMS(i.r, i.y, i.p)
                               then v_L_VAR_NCAP(i.r, i.y, i.p) + v_NCAP_PASTI(i.r, i.y, i.p) - {scap0} else 0 end as value
                 from OBJ_ICUR i
                 where in_NCAP_YES(i.r, i.y, i.p) and v_RVPRL(i.r, i.y, i.p) <> 0""")
        db.x("delete from vn_objcap where value = 0")
        db.put("RTP_OBJ", """
            select '1' as j, c.r, c.y, c.p, c.cur,
                   v_RTP_OBJ('1', c.r, c.y, c.p, c.cur) + c.value * case when v_RTP_OBJ('2', c.r, c.y, c.p, c.cur) > 0
                       then 1 - 1 / (1 + v_RTP_OBJ('1', c.r, c.y, c.p, c.cur) / v_RTP_OBJ('2', c.r, c.y, c.p, c.cur))
                       else 1 end as value
            from vn_objcap c""")
        db.put("RTP_OBJ", """
            select '2' as j, c.r, c.y, c.p, c.cur,
                   v_RTP_OBJ('2', c.r, c.y, c.p, c.cur)
                   + c.value / (1 + v_RTP_OBJ('1', c.r, c.y, c.p, c.cur) / v_RTP_OBJ('2', c.r, c.y, c.p, c.cur)) as value
            from vn_objcap c where v_RTP_OBJ('2', c.r, c.y, c.p, c.cur) > 0""")
    if "PRC_RCAP" in db.sym and "RTP_ISHPR" in db.sym:
        db.add("RTP_ISHPR", "select t.r, t.y, t.p from RTP t where in_PRC_RCAP(t.r, t.p)")


def _fixed(db):
    """Lines 87-112. PASTSUM = RTP_CAPVL/OBJ_DIVIV. FIXX is the sum of the tax column.

    The shaped branch is the processes in RTP_ISHPR (with VNRET, also every PRC_RCAP process, and %TMP%
    is the share not yet retired: _vnret). KTYAGE is built here (eqobj.mod 20-23). OBJ_SUMIVS (NCAP_DLAGC)
    is refused by the preprocessor.
    """
    db.declare("RTP_NPV", "par", ["J", "R", "ALLYEAR", "P", "CUR"])
    db.clear("RTP_NPV")
    _ktyage(db)
    _shape_extra(db)
    for j, cost, grp, present in (
            ("1", "v_OB_FOM(i.r, i.p, i.cur, sp.y3)", "1", "in_OB_FOM(i.r, i.p, i.cur, sp.y3)"),
            ("2", "(v_OB_FTX(i.r, i.p, i.cur, sp.y3) - v_OB_FSB(i.r, i.p, i.cur, sp.y3))", None,
             "(in_OB_FTX(i.r, i.p, i.cur, sp.y3) or in_OB_FSB(i.r, i.p, i.cur, sp.y3))")):
        _fixed_column(db, j, cost, grp, present)
    db.put("REG_WOBJ", """
        select r, 'FIXX' as u, cur, sum(value) as value from RTP_NPV where j = '2'
        group by r, cur
    """)


def _ktyage(db):
    """eqobj.mod lines 20-23, which the preprocessor does not run (it is model generation):
        LOOP(SAMEAS('1',AGE),
          KTYAGE(K(LL),PERIODYR(T,Y_EOH(YEAR)),AGE+(ORD(YEAR)-ORD(LL)))$YK(YEAR,LL)=YES;
          KTYAGE(K(LL),YK(PYR_S,Y_EOH(YEAR)),AGE+(ORD(YEAR)-ORD(LL)))$YK(YEAR,LL)=YES);
    (cost year LL, period T, year Y_EOH, age of LL in that year). Only the LL of INVSPRED are needed here.
    An age past the last AGE element has no member and is not written."""
    if "KTYAGE" in db.sym and db.card("KTYAGE"):
        return
    if not all(n in db.sym for n in ("PERIODYR", "Y_EOH", "YK", "INVSPRED", "AGE")):
        return
    db.declare("KTYAGE", "set", ["LL", "YEAR", "LL", "AGE"])
    pyr = "union all select p.y as t, y.y as y from PYR_S p join Y_EOH y on in_YK(p.y, y.y)" if "PYR_S" in db.sym else ""
    db.add("KTYAGE", f"""
        select ll.y as y, ty.t as y2, ty.y as y3, a.age
        from (select q.y as t, q.y2 as y from PERIODYR q where in_Y_EOH(q.y2) {pyr}) ty
        join (select distinct y2 as y from INVSPRED) ll on in_YK(ty.y, ll.y)
        join AGE a on try_cast(a.age as integer) = 1 + try_cast(ty.y as integer) - try_cast(ll.y as integer)
    """)


def _shape_extra(db):
    """1+SUM(RTP_SHAPE, SHAPE*MULTI-1) is 1 when the process has no shape row of that group."""
    if "RTP_SHAPE" not in db.sym or db.card("RTP_SHAPE") == 0:
        db.x("create or replace temp table shp as select '' r, '' v, '' p, '' grp, '' age, '' yeoh, 0.0 extra where false")
        return
    db.x("""
        create or replace temp table shp as
        select sh.r, sh.y as v, sh.p, sh.j as grp, kt.age, kt.y3 as yeoh,
               sum(v_SHAPE(sh.j2, kt.age) * v_MULTI(sh.j3, kt.y3) - 1) as extra
        from RTP_SHAPE sh
        join (select distinct age, y3 from KTYAGE) kt on true
        group by sh.r, sh.y, sh.p, sh.j, kt.age, kt.y3
    """)


def _fixed_column(db, j, cost, grp, present="false"):
    """One RTP_NPV column. grp None means the tax column, which has a shape on tax and one on subsidy.
    A cost record of value 0 is EPS: its terms are EPS, and a sum with no nonzero term is stored as EPS
    (a process whose fixed cost is EPS gets an EPS RTP_NPV, and then an EPS CST_PVP('FIX'))."""
    past = "((v_L_VAR_NCAP(i.r, i.y, i.p) + v_NCAP_PASTI(i.r, i.y, i.p)) / v_OBJ_DIVIV(i.r, i.y, i.p))"
    wd = rptobjc.spread_factor(db, "v_OBJ_WD(i.r, i.cur, u.y, u.age, sp.y3)")
    plain = f"""
        select '{j}' as j, i.r, i.y, i.p, i.cur,
               sum(v_OBJ_LIFE(sp.y2, i.r, u.age, u.age2, i.cur)
                   * {wd} * {cost} * {past}) as value,
               max(case when {present} and ({cost}) = 0 then 1 else 0 end) as eps
        from OBJ_FCUR i
        join OBJ_SUMIV u on u.r = i.r and u.y2 = i.y and u.p = i.p
        join INVSPRED sp on sp.y = u.y and sp.age = u.age
        where in_NCAP_YES(i.r, i.y, i.p) and not in_RTP_ISHPR(i.r, i.y, i.p)
          and v_OBJ_DIVIV(i.r, i.y, i.p) <> 0
        group by i.r, i.y, i.p, i.cur
    """
    if grp is not None:
        shaped_cost = f"{cost} * (1 + coalesce(sx.extra, 0))"
        shape_join = f"""
            left join shp sx on sx.r = i.r and sx.v = i.y and sx.p = i.p and sx.grp = '{grp}'
                             and sx.age = kt.age and sx.yeoh = kt.y3
        """
    else:
        shaped_cost = """(
            v_OB_FTX(i.r, i.p, i.cur, sp.y3) * (1 + coalesce(tx.extra, 0))
            - v_OB_FSB(i.r, i.p, i.cur, sp.y3) * (1 + coalesce(sb.extra, 0))
        )"""
        shape_join = """
            left join shp tx on tx.r = i.r and tx.v = i.y and tx.p = i.p and tx.grp = '2'
                             and tx.age = kt.age and tx.yeoh = kt.y3
            left join shp sb on sb.r = i.r and sb.v = i.y and sb.p = i.p and sb.grp = '3'
                             and sb.age = kt.age and sb.yeoh = kt.y3
        """
    cpx = ("(1 + case when in_NCAP_CPX(i.r, i.y, i.p) then v_RTP_CPX(i.r, i.y, i.p, kt.y2) else 0 end)"
           if "NCAP_CPX" in db.sym and "RTP_CPX" in db.sym else "1")
    if vnret(db) and "PRC_RCAP" in db.sym and "L_VAR_SCAP" in db.sym:
        # %TMP%: the share not yet retired in period Y; VAR_SCAP.L/PASTSUM/OBJ_DIVIV is VAR_SCAP.L/RTP_CAPVL
        cpx += """ * (1 - case when in_PRC_RCAP(i.r, i.p)
                          then v_L_VAR_SCAP(i.r, i.y, kt.y2, i.p) / (v_L_VAR_NCAP(i.r, i.y, i.p) + v_NCAP_PASTI(i.r, i.y, i.p))
                          else 0 end)"""
    shaped = f"""
        select '{j}' as j, i.r, i.y, i.p, i.cur,
               sum({wd} * v_OBJ_DISC(i.r, kt.y3, i.cur) * {cpx}
                   * {shaped_cost} * {past}) as value,
               max(case when {present} and ({cost}) = 0 then 1 else 0 end) as eps
        from OBJ_FCUR i
        join OBJ_SUMIV u on u.r = i.r and u.y2 = i.y and u.p = i.p
        join INVSPRED sp on sp.y = u.y and sp.age = u.age
        join KTYAGE kt on kt.y = sp.y2
        join OPYEAR op on op.age = u.age2 and op.age2 = kt.age
        {shape_join}
        where in_NCAP_YES(i.r, i.y, i.p) and in_RTP_ISHPR(i.r, i.y, i.p)
          and v_OBJ_DIVIV(i.r, i.y, i.p) <> 0
        group by i.r, i.y, i.p, i.cur
    """
    db.x(f"create or replace temp table npv_col as select j, r, y, p, cur, sum(value) as value, max(eps) as eps "
         f"from ({plain} union all {shaped}) t group by j, r, y, p, cur")
    db.put("RTP_NPV", "select j, r, y, p, cur, value from npv_col where value <> 0 or eps = 1", zero="eps")


def _variable_rest(db):
    """Lines 137-147. VARX is the tax column of PAR_FLOC and PAR_COMC. Then, for every
    reporting currency:

        REG_WOBJ(R,'INV',CUR) = SUM(SUM_OBJ('OBJINV') * VAR_OBJ.L) - VAR_OBJ.L(OBJSAL) - INVX + EPS;
        REG_WOBJ(R,'FIX',CUR) = SUM(SUM_OBJ('OBJFIX') * VAR_OBJ.L) - FIXX + EPS;
        REG_WOBJ(R,'VAR',CUR) = SUM(SUM_OBJ('OBJVAR') * VAR_OBJ.L) - VARX + EPS;
        REG_WOBJ(R,'ELS',CUR) = EPS
        $IF %TIMESED% == YES  +SUM(BD,%VAR%_OBJELS.L(R,BD,CUR%3)*(BDSIG(BD)-1$LNX(BD)))

    BDSIG(BD)-1$LNX(BD) (LNX: N, FX) is 1 for LO, -1 for UP and FX; VAR_OBJELS is there only with TIMESED YES.
    """
    _sum_obj(db)
    db.put("REG_WOBJ", """
        select r, 'VARX' as u, cur, sum(value) as value from (
            select r, cur, sum(value) as value from PAR_FLOC where j = '2' group by r, cur
            union all
            select r, cur, sum(value) as value from PAR_COMC where j = '2' group by r, cur
        ) s
        group by r, cur
    """)
    for item, group, minus in (
        ("INV", "OBJINV", "v_L_VAR_OBJ(d.r, 'OBJSAL', d.cur) + v_REG_WOBJ(d.r, 'INVX', d.cur)"),
        ("FIX", "OBJFIX", "v_REG_WOBJ(d.r, 'FIXX', d.cur)"),
        ("VAR", "OBJVAR", "v_REG_WOBJ(d.r, 'VARX', d.cur)"),
    ):
        # +EPS stores a zero sum. A reporting currency with no variable row is still written.
        db.put("REG_WOBJ", f"""
            select d.r, '{item}' as u, d.cur,
                   coalesce(sum(s.value * v_L_VAR_OBJ(d.r, s.u2, d.cur)), 0) - ({minus}) as value
            from RDCUR d
            left join SUM_OBJ s on s.u = '{group}'
            group by d.r, d.cur
        """, zero="eps")
    els = ("coalesce((select sum(case when o.l = 'LO' then 1 else -1 end * o.value) from L_VAR_OBJELS o "
           "where o.r = d.r and o.cur = d.cur), 0)") if "L_VAR_OBJELS" in db.sym else "0"
    db.put("REG_WOBJ", f"""
        select d.r, 'ELS' as u, d.cur, {els} as value from RDCUR d
    """, zero="eps")


def _sum_obj(db):
    """eqobj.mod 26-27, when the preprocessor left the parameter empty.

        SUM_OBJ(OBV,ITEM) = DIAG(OBV,ITEM);
        SUM_OBJ(OBV('OBJSAL'),OBV) = -1;

    OBV is OBJINV, OBJFIX, OBJSAL, OBJVAR (mod_vars.mod). The solved parameter keeps
    the diagonal, and the OBJSAL diagonal is -1. The report sums SUM_OBJ('OBJINV',OBV)
    and the same for OBJFIX and OBJVAR, which is that diagonal.
    """
    if "SUM_OBJ" in db.sym and db.card("SUM_OBJ"):
        return
    db.declare("SUM_OBJ", "par", ["ITEM", "ITEM"])
    db.put("SUM_OBJ", """
        select u, u as u2, case when u = 'OBJSAL' then -1 else 1 end as value
        from (values ('OBJINV'), ('OBJFIX'), ('OBJSAL'), ('OBJVAR')) t(u)
    """)


def _pv_put(db, name, label, select, keys, mode):
    """CST_PVP / CST_PVC rows from `select` (keys, value): a GAMS SUM where a 0 row is an EPS term.
    mode '=' : the total, EPS when every term is EPS, nothing when it cancels; '$=' the same here,
    since the target starts empty for each label."""
    k = ", ".join(keys)
    db.x(f"""create or replace temp table pv_sum as
             select {k}, sum(value) as value, bool_and(value = 0) as all_eps
             from ({select}) t group by {k}""")
    db.put(name, f"select '{label}' as sysuc, {k}, value from pv_sum where value <> 0 or all_eps", zero="eps")


def _pv_investment(db):
    """rpt_obj.rpt lines 80-81, MY_F > 0: the discounted investment of each process, split like CAP_NEW
    into the part outside the hurdle rate (INV, SYSONE 1) and the hurdle-rate part (INV+, SYSONE 0):
        IF(MY_F, SYSINV('INV+')=YES);
        IF(MY_F>0, OPTION TRACKP<RTP_OBJ;
          CST_PVP(SYSINV,TRACKP(R,P)) = SUM((J,V,CUR)$RTP_OBJ, RTP_OBJ*ABS(SYSONE(SYSINV)-COEF_CRF(R,V,P,CUR))));
    Both columns of RTP_OBJ count: investment ('1') and taxes less subsidies ('2')."""
    if my_f(db) <= 0 or "RTP_OBJ" not in db.sym:
        return
    for label, one in (("INV", 1), ("INV+", 0)):
        _pv_put(db, "CST_PVP", label, f"""
            select o.r, o.p, o.value * abs({one} - v_COEF_CRF(o.r, o.y, o.p, o.cur)) as value
            from RTP_OBJ o""", ["r", "p"], "=")
    # INV+ is a true zero without a hurdle rate; such a total is not an EPS and is not kept
    db.x("""delete from CST_PVP c where c.sysuc = 'INV+' and c.value = 0
              and not exists (select 1 from COEF_CRF k where k.r = c.r and k.p = c.p)""")


def _pv_fixed(db):
    """rpt_obj.rpt line 105: IF(MY_F>0, OPTION TRACKP<RTP_NPV; CST_PVP('FIX',TRACKP(R,P))=SUM((J,V,CUR)$RTP_NPV,RTP_NPV));"""
    if my_f(db) <= 0 or "RTP_NPV" not in db.sym:
        return
    _pv_put(db, "CST_PVP", "FIX", "select r, p, value from RTP_NPV", ["r", "p"], "=")


def _pv_variable(db):
    """rpt_obj.rpt lines 129-135, MY_F > 0, both columns of the eqobjvar call:
        CST_PVP('ACT',RP) $= SUM(PAR_ACTC);  CST_PVP('FLO',RP) $= SUM(PAR_FLOC);  CST_PVC('COM',RC) $= SUM(PAR_COMC);"""
    if my_f(db) <= 0:
        return
    if "PAR_ACTC" in db.sym:
        _pv_put(db, "CST_PVP", "ACT", "select r, p, value from PAR_ACTC", ["r", "p"], "$=")
    if "PAR_FLOC" in db.sym:
        _pv_put(db, "CST_PVP", "FLO", "select r, p, value from PAR_FLOC", ["r", "p"], "$=")
    if "PAR_COMC" in db.sym:
        _pv_put(db, "CST_PVC", "COM", "select r, c, value from PAR_COMC", ["r", "c"], "$=")


def _empty_veda(db):
    """Declared empty at the start. CST_PVP / CST_PVC are written when RPT_OPT('OBJ','1') is set;
    PAR_NCAPR when RPT_OPT('NCAP','1') is set (rptmisc) or BENCOST is YES (not ported)."""
    db.declare("CST_PVP", "par", ["SYSUC", "R", "P"])
    db.declare("CST_PVC", "par", ["SYSUC", "R", "C"])
    db.declare("PAR_NCAPR", "par", ["R", "ALLYEAR", "P", "ITEM"])
    db.clear("CST_PVP", "CST_PVC", "PAR_NCAPR")
