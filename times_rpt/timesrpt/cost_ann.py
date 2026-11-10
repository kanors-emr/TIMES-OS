# SPDX-License-Identifier: GPL-3.0-or-later
"""cost_ann.rpt — annual costs. rptlite.rpt line 153 calls it after rpt_obj.

The prefix and the SOW index are empty. CNT is 1$ROUND(RPT_OPT('OBJ','2')) and ACL is
not 0 with ANNCOST LEV (coef_obj.mod 31: ACL=MINYR, RPT_OPT('OBJ','2')=1). With CNT the
levelized investment of lines 19-25 replaces the annual one, with ACL also the levelized
fixed costs of lines 26-31, and line 32 clears NCAP_YES for the rest of the costs.
STAGES and ETL are not set, so %SIC% is 1 and the ETL block is not taken.

SYSONE is the parameter rptlite.rpt line 59 declares, / INV 1 /. SYSINV is that
label (line 128), plus INV+ when RPT_OPT('OBJ','1') is set (rpt_obj.rpt line 80, _sysinv).
Without OBJ.1, rpt_obj.rpt line 44 clears COEF_CRF and ABS(SYSONE-COEF_CRF) is 1.
"""
from __future__ import annotations

from . import eqobjvar


def run(db):
    """Investment costs. Returns the names written."""
    _rtp_capvl(db)
    # rptobj puts OBJ_YES back into NCAP_YES early, so the result is that of line 121.
    # These loops run before that restore: NCAP_YES is only where RTP_CAPVL > 0.
    # An EPS capacity fails the test, so it is not costed here.
    saved = _ncap_positive(db)
    # cost_ann.rpt line 17, while NCAP_YES still contains the residual vintages.
    _ann_share(db)
    cnt, acl = levelized(db)
    try:
        if cnt:
            # Line 15: OBJ_YES(NCAP_YES)=YES, which line 91 restores after line 32 cleared NCAP_YES.
            db.x("create or replace temp table ann_objyes as select r, y, p from NCAP_YES")
            _levelized(db, acl)
        else:
            _drop_residual(db)
            _investment(db)
        _decommission(db)
        if not acl:
            _fixed(db, cnt)
    finally:
        if saved:
            db.assign("NCAP_YES", "select r, y, p from ncap_held")
    # Line 205 is after line 121 has put OBJ_YES back into NCAP_YES.
    _salvage(db)
    _time(db)
    _trade(db)
    _variable(db)
    _cst_come(db)
    _pv_ire(db)
    _regional(db)
    _clear_worked(db)
    return ["CST_INVC", "CST_INVX", "CST_DECC", "CST_SALV", "CST_FIXC", "CST_FIXX",
            "CST_TIME", "CST_ACTC", "CST_FLOC", "CST_FLOX", "CST_COMC", "CST_COMX", "CST_COME",
            "CST_IREC", "PAR_IPRIC", "REG_IREC", "REG_ACOST", "REG_OBJ"]


def levelized(db):
    """(CNT, ACL). cost_ann.rpt line 16: CNT=1$ROUND(RPT_OPT('OBJ','2')); ACL is MINYR with ANNCOST LEV
    (coef_obj.mod 31, which also sets RPT_OPT('OBJ','2')=1), else 0."""
    acl = str(db.env.get("ANNCOST", "")).strip().strip("'\"").upper() == "LEV"
    obj2 = db.q1("select value from RPT_OPT where u = 'OBJ' and j = '2'") if "RPT_OPT" in db.sym else None
    return bool(acl or (obj2 and round(obj2) != 0)), acl


def _levelized(db, acl):
    """Lines 19-32. The discounted investment (and with ACL the discounted fixed cost) of a vintage spread
    over its periods in proportion to its capacity and the present value of the period.

        PAR_OBJCAP(OBJ_ICUR(NCAP_YES(R,V,P),CUR)) = SUM(RTP_CPTYR(R,V,T,P),COEF_CPT(R,V,T,P)*OBJ_PVT(R,T,CUR));
        RTP_OBJ(J,R,V,P,CUR)$RTP_OBJ(J,R,V,P,CUR) = (RTP_OBJ(J,R,V,P,CUR)/PAR_OBJCAP(R,V,P,CUR))$PAR_OBJCAP(R,V,P,CUR);
        CST_INVC(RTP_CPTYR(R,V,T,P),SYSINV)$NCAP_YES(R,V,P) =
           SUM(RDCUR(R,CUR),RTP_OBJ('1',R,V,P,CUR)*COEF_CPT(R,V,T,P)*ABS(SYSONE(SYSINV)-COEF_CRF(R,V,P,CUR)));
        CST_INVX: the same with RTP_OBJ('2');
      IF(ACL,
        PAR_OBJCAP(OBJ_FCUR(NCAP_YES(R,V,P),CUR)) = SUM(RTP_CPTYR(R,V,T,P),COEF_CPT*(1-COEF_CAP(R,V,T,P))*OBJ_PVT(R,T,CUR));
        RTP_NPV(J,R,V,P,CUR)$RTP_NPV(J,R,V,P,CUR) = (RTP_NPV(J,R,V,P,CUR)/PAR_OBJCAP(R,V,P,CUR))$PAR_OBJCAP(R,V,P,CUR);
        CST_FIXC(RTP_CPTYR(R,V,T,P))$NCAP_YES(R,V,P) = SUM(RDCUR(R,CUR),RTP_NPV('1',R,V,P,CUR)*COEF_CPT*(1-COEF_CAP));
        CST_FIXX: the same with RTP_NPV('2');
        OPTION CLEAR=COEF_CAP);
      OPTION CLEAR=NCAP_YES;

    COEF_CAP is line 17's retired share (ann_share). With NCAP_YES cleared, lines 42-120 write no investment,
    residual, decommissioning or fixed rows, and with ACL COEF_CAP is cleared before lines 116-119."""
    for name in ("CST_INVC", "CST_INVX"):
        db.declare(name, "par", ["R", "ALLYEAR", "T", "P", "SYSUC"])
        db.clear(name)
    for name in ("CST_FIXC", "CST_FIXX"):
        db.declare(name, "par", ["R", "ALLYEAR", "T", "P"])
        db.clear(name)
    need = ("RTP_CPTYR", "COEF_CPT", "OBJ_PVT", "RDCUR", "NCAP_YES")
    if all(n in db.sym for n in need):
        parts = [("OBJ_ICUR", "RTP_OBJ", "1")]
        if acl:
            parts.append(("OBJ_FCUR", "RTP_NPV", "(1 - coalesce(a.value, 0))"))
        for cur_set, npv, share in parts:
            if cur_set not in db.sym or npv not in db.sym:
                continue
            db.x(f"""
                create or replace temp table lev_cap as
                select i.r, i.y, i.p, i.cur, sum(c.value * {share} * v_OBJ_PVT(i.r, c.y2, i.cur)) as value
                from {cur_set} i
                join RTP_CPTYR t on t.r = i.r and t.y = i.y and t.p = i.p
                join COEF_CPT c on c.r = t.r and c.y = t.y and c.y2 = t.y2 and c.p = t.p
                left join ann_share a on a.r = t.r and a.v = t.y and a.per = t.y2 and a.p = t.p
                where in_NCAP_YES(i.r, i.y, i.p)
                group by i.r, i.y, i.p, i.cur
            """)
            db.x(f"""
                create or replace temp table lev_npv as
                select o.j, o.r, o.y, o.p, o.cur, o.value / k.value as value
                from "{npv}" o join lev_cap k on k.r = o.r and k.y = o.y and k.p = o.p and k.cur = o.cur
                where k.value <> 0
            """)
            # The plain '=' over RTP_CPTYR stores no zero. An EPS RTP_OBJ / RTP_NPV (a row of value 0) times a
            # nonzero factor is EPS, and a sum with no nonzero term and an EPS one is EPS, which it stores.
            if npv == "RTP_OBJ":
                labels = [(label, one) for label, one, _only in _sysinv(db)]
                cols = [("1", "CST_INVC"), ("2", "CST_INVX")]
                factor = "c.value * abs({one} - v_COEF_CRF(o.r, o.y, o.p, o.cur))"
            else:
                labels = [(None, None)]
                cols = [("1", "CST_FIXC"), ("2", "CST_FIXX")]
                factor = "c.value * (1 - coalesce(a.value, 0))"
            for label, one in labels:
                f = factor.format(one=one)
                for j, name in cols:
                    db.x(f"""
                        create or replace temp table lev_put as
                        select t.r, t.y, t.y2, t.p, sum(o.value * {f}) as value,
                               max(case when o.value = 0 and ({f}) <> 0 then 1 else 0 end) as eps
                        from RTP_CPTYR t
                        join COEF_CPT c on c.r = t.r and c.y = t.y and c.y2 = t.y2 and c.p = t.p
                        join lev_npv o on o.j = '{j}' and o.r = t.r and o.y = t.y and o.p = t.p
                        left join ann_share a on a.r = t.r and a.v = t.y and a.per = t.y2 and a.p = t.p
                        where in_NCAP_YES(t.r, t.y, t.p) and in_RDCUR(o.r, o.cur)
                        group by t.r, t.y, t.y2, t.p
                    """)
                    sysuc = f", '{label}' as sysuc" if label else ""
                    db.put(name, f"select r, y, y2, p{sysuc}, value from lev_put where value <> 0 or eps = 1",
                           zero="eps")
    if acl:
        db.x("delete from ann_share")
    db.clear("NCAP_YES")


def _sysinv(db):
    """(label, SYSONE) of each SYSINV label. rptlite.rpt 59 and 128: SYSINV(SYSUC)$=SYSONE(SYSUC), which is
    INV with SYSONE 1; rpt_obj.rpt line 80 adds INV+ (SYSONE 0) when MY_F = ROUND(RPT_OPT('OBJ','1')) is not 0.
    ABS(SYSONE-COEF_CRF) then splits the cost: INV carries 1-CRF, INV+ the hurdle-rate share CRF. Without
    a COEF_CRF record the INV+ factor is a true zero, so its rows are taken only where the hurdle rate exists."""
    labels = [("INV", 1, "true")]
    obj1 = db.q1("select value from RPT_OPT where u = 'OBJ' and j = '1'") if "RPT_OPT" in db.sym else None
    if obj1 and round(obj1) != 0:
        labels.append(("INV+", 0, "in_COEF_CRF(i.r, i.y, i.p, i.cur)"))
    return labels


def _ncap_positive(db):
    """Keep NCAP_YES where the capacity is strictly positive, and remember the set to restore."""
    if "NCAP_YES" not in db.sym:
        return False
    db.x("create or replace temp table ncap_held as select r, y, p from NCAP_YES")
    db.remove("NCAP_YES", where="""
        v_L_VAR_NCAP(r, y, p) + v_NCAP_PASTI(r, y, p) <= 0
    """)
    return True


def _rtp_capvl(db):
    """rpt_obj.rpt line 12, still in place when cost_ann runs.

        RTP_CAPVL(RTP) = VAR_NCAP.L(RTP) + NCAP_PASTI(RTP);
    """
    db.x("""
        create or replace temp table rtp_capvl as
        select t.r, t.y, t.p,
               v_L_VAR_NCAP(t.r, t.y, t.p) + v_NCAP_PASTI(t.r, t.y, t.p) as value
        from RTP t
        where v_L_VAR_NCAP(t.r, t.y, t.p) + v_NCAP_PASTI(t.r, t.y, t.p) <> 0
           or in_L_VAR_NCAP(t.r, t.y, t.p) or in_NCAP_PASTI(t.r, t.y, t.p)
    """)


def _ann_share(db):
    """Line 17. The retired share of the available capacity.

        COEF_CAP(RTP_CPTYR(R,V,T,P))$(NCAP_YES(R,V,P)$PRC_RCAP(R,P))
            = VAR_SCAP.L(R,V,T,P) / RTP_CAPVL(R,V,P);

    A true zero share is not stored. The scaling itself is lines 116-119, after the
    fixed costs exist.
    """
    db.x("""
        create or replace temp table ann_share as
        select '' as r, '' as v, '' as per, '' as p, 0.0 as value where false
    """)
    if not all(n in db.sym for n in ("PRC_RCAP", "L_VAR_SCAP", "RTP_CPTYR")) or not db.card("PRC_RCAP"):
        return
    db.x("""
        create or replace temp table ann_share as
        select a.r, a.y as v, a.y2 as per, a.p,
               v_L_VAR_SCAP(a.r, a.y, a.y2, a.p) / c.value as value
        from RTP_CPTYR a
        join rtp_capvl c on c.r = a.r and c.y = a.y and c.p = a.p
        where in_NCAP_YES(a.r, a.y, a.p) and in_PRC_RCAP(a.r, a.p)
          and v_L_VAR_SCAP(a.r, a.y, a.y2, a.p) <> 0 and c.value <> 0
    """)


def _drop_residual(db):
    """cost_ann.rpt line 42, the NOT CNT branch.

        NCAP_YES(R,PYR_S,P)$PRC_RESID(R,'0',P) = NO;
    """
    if "PYR_S" not in db.sym or "PRC_RESID" not in db.sym:
        return False
    db.remove("NCAP_YES", where="in_PYR_S(y) and in_PRC_RESID(r, '0', p)")
    return "OBJ_YES" in db.sym


def _investment(db):
    """Lines 44-63. Annual undiscounted investment, then the residual vintages.

        F = RTP_CAPVL * OBJ_CRF / OBJ_DIVI;
        LOOP(OBJ_SUMII(R,V,P,LIFE,K_EOH,JOT), Z=ORD(LIFE);
          FIL(T) = VNT(V,T)$(M(T) < YEARVAL(K_EOH)+ORD(JOT)+Z);
          YKK(YK(FIL(YEAR),LL),K)$((ORD(YEAR) < ORD(LL)+Z)$INVSPRED(K_EOH,JOT,LL,K)) = YES);
        CSTVPJ(R,V,P,'1',INV,T(FIL)) = SUM(YKK(T,LL,K), F * MY_F * OBJ_ICOST(R,K,P,CUR)) * SYSPLIT(INV);

    MY_F is %SIC%: 1, or 1+PASTSUM(R,V,P) in stochastic TIMES with S_NCAP_COST (lines 38-40, rptobj.sic).

    FIL is replaced on every OBJ_SUMII tuple and YKK accumulates, so the sum uses
    every tuple's YKK but only the periods in the last tuple's FIL. GAMS keeps the
    last currency when two of them write the same key.
    OBJ_ICOST(R,K,P,CUR) is OB_ICOST(R,P,CUR,K). ORD of a year label and ORD of an
    age are their numeric values: ALLYEAR after '0' is contiguous, and AGE is 1..N.
    """
    db.declare("CST_INVC", "par", ["R", "ALLYEAR", "T", "P", "SYSUC"])
    db.declare("CST_INVX", "par", ["R", "ALLYEAR", "T", "P", "SYSUC"])
    db.clear("CST_INVC")
    db.clear("CST_INVX")
    need = ("OBJ_ICUR", "OBJ_SUMII", "INVSPRED", "VNT", "YK", "OB_ICOST", "OBJ_CRF", "OBJ_DIVI", "NCAP_YES")
    if not all(n in db.sym for n in need):
        return
    from . import rptobj
    db.x("""
        create or replace temp table sumii_ord as
        select u.r, u.y as v, u.p, u.age as life, u.y2 as k_eoh, u.age2 as jot,
               try_cast(u.age as integer) as z,
               row_number() over (
                   partition by u.r, u.y, u.p
                   order by try_cast(u.age as integer), try_cast(u.y2 as integer),
                            try_cast(u.age2 as integer)) as seq
        from OBJ_SUMII u
        where in_NCAP_YES(u.r, u.y, u.p)
    """)
    db.x("""
        create or replace temp table inv_fil as
        select s.r, s.v, s.p, s.seq, s.z, s.k_eoh, s.jot, vn.y2 as per
        from sumii_ord s
        join VNT vn on vn.y = s.v
        where in_MILESTONYR(vn.y2)
          and v_M(vn.y2) < try_cast(s.k_eoh as integer) + try_cast(s.jot as integer) + s.z
    """)
    # YKK is a set, so the same (period, payment year, cost year) from two tuples counts once.
    db.x("""
        create or replace temp table inv_ykk as
        select distinct y.r, y.v, y.p, y.per, y.ll, y.k
        from (
            select f.r, f.v, f.p, f.per, sp.y2 as ll, sp.y3 as k
            from inv_fil f
            join INVSPRED sp on sp.y = f.k_eoh and sp.age = f.jot
            where in_YK(f.per, sp.y2)
              and try_cast(f.per as integer) < try_cast(sp.y2 as integer) + f.z
        ) y
        where exists (
            select 1 from inv_fil fin
            join (select r, v, p, max(seq) as seq from sumii_ord group by r, v, p) last
              on last.r = fin.r and last.v = fin.v and last.p = fin.p and last.seq = fin.seq
            where fin.r = y.r and fin.v = y.v and fin.p = y.p and fin.per = y.per)
    """)
    for label, one, only in _sysinv(db):
        # F * SYSPLIT, one currency at a time. A second currency that writes a different value stops.
        db.x(f"""
            create or replace temp table inv_bycur as
            select i.r, i.y as v, y.per, i.p, i.cur,
                   (c.value * v_OBJ_CRF(i.r, i.y, i.p, i.cur) / v_OBJ_DIVI(i.r, i.y, i.p))
                   * abs({one} - v_COEF_CRF(i.r, i.y, i.p, i.cur))
                   * {rptobj.sic(db, "i.r", "i.y", "i.p")} * sum(v_OB_ICOST(i.r, i.p, i.cur, y.k)) as value
            from OBJ_ICUR i
            join rtp_capvl c on c.r = i.r and c.y = i.y and c.p = i.p
            join inv_ykk y on y.r = i.r and y.v = i.y and y.p = i.p
            where in_NCAP_YES(i.r, i.y, i.p) and v_OBJ_DIVI(i.r, i.y, i.p) <> 0 and {only}
            group by i.r, i.y, y.per, i.p, i.cur, c.value
        """)
        _one_currency(db, "inv_bycur")
        # $= : a zero sum is not stored. The column is '1'.
        db.put("CST_INVC", f"""
            select r, v as y, per as y2, p, '{label}' as sysuc, value
            from inv_bycur
        """, zero="skip")
        _investment_tax(db, label, one, only)
    for label, one, only in _sysinv(db):
        _residual(db, label, one, only)


def _investment_tax(db, label="INV", one=1, only="true"):
    """The '2' column. Written only where the vintage itself carries a tax or a subsidy.

        CSTVPJ(R,V,P,'2',INV,T)$ (OBJ_ITAX(R,V,P,CUR)+OBJ_ISUB(R,V,P,CUR))
            = SUM(YKK, F * (OBJ_ITAX(R,K,P,CUR)-OBJ_ISUB(R,K,P,CUR))) * SYSPLIT;
    """
    db.x(f"""
        create or replace temp table invx_bycur as
        select i.r, i.y as v, y.per, i.p, i.cur,
               (c.value * v_OBJ_CRF(i.r, i.y, i.p, i.cur) / v_OBJ_DIVI(i.r, i.y, i.p))
               * abs({one} - v_COEF_CRF(i.r, i.y, i.p, i.cur))
               * sum(v_OB_ITAX(i.r, i.p, i.cur, y.k) - v_OB_ISUB(i.r, i.p, i.cur, y.k)) as value
        from OBJ_ICUR i
        join rtp_capvl c on c.r = i.r and c.y = i.y and c.p = i.p
        join inv_ykk y on y.r = i.r and y.v = i.y and y.p = i.p
        where in_NCAP_YES(i.r, i.y, i.p) and v_OBJ_DIVI(i.r, i.y, i.p) <> 0 and {only}
          and (in_OB_ITAX(i.r, i.p, i.cur, i.y) or in_OB_ISUB(i.r, i.p, i.cur, i.y))
        group by i.r, i.y, y.per, i.p, i.cur, c.value
    """)
    _one_currency(db, "invx_bycur")
    # The '=' into CSTVPJ stores an EPS tax difference, and the '$=' copy keeps it.
    # A true zero is not among these rows: the zero rows are EPS.
    db.put("CST_INVX", f"""
        select r, v as y, per as y2, p, '{label}' as sysuc, value from invx_bycur
    """, zero="eps")


def _residual(db, label="INV", one=1, only="true"):
    """Lines 54 and 59-63. A plain '=' replaces the value for a past residual vintage.

        FIL(V) = PYR_S(V);
        FIL2(T) = (NCAP_PASTI*COEF_RVPT(R,V,P,T) - RTFORC) * OBJ_CRF;
        CST_INVC(RTP_CPTYR, INV) = ABS(SYSONE-COEF_CRF) * FIL2(T) * OBJ_ICOST(R,V,P,CUR);

    COEF_RVPT(R,ALLYEAR,PRC,T) <= COEF_CPT(R,ALLYEAR,T,PRC), so the period and the
    process change places.
    """
    if "RTP_CPTYR" not in db.sym or "PYR_S" not in db.sym:
        return
    rt = "v_RTFORC(a.r, a.y, a.y2, a.p)" if "RTFORC" in db.sym else "0"
    base = f"""
        from OBJ_ICUR i
        join RTP_CPTYR a on a.r = i.r and a.y = i.y and a.p = i.p
        where in_PYR_S(i.y) and in_PRC_RESID(i.r, '0', i.p) and {only}
    """
    fil2 = f"""abs({one} - v_COEF_CRF(i.r, i.y, i.p, i.cur))
               * (v_NCAP_PASTI(i.r, i.y, i.p) * v_COEF_CPT(i.r, i.y, a.y2, i.p) - ({rt}))
               * v_OBJ_CRF(i.r, i.y, i.p, i.cur)"""
    db.x(f"""
        create or replace temp table resid_inv as
        select i.r, i.y as v, a.y2 as per, i.p, i.cur,
               {fil2} * v_OB_ICOST(i.r, i.p, i.cur, i.y) as value
        {base}
    """)
    _one_currency(db, "resid_inv")
    db.put("CST_INVC", f"""
        select r, v as y, per as y2, p, '{label}' as sysuc, value from resid_inv
    """)
    db.x(f"""
        create or replace temp table resid_invx as
        select i.r, i.y as v, a.y2 as per, i.p, i.cur,
               {fil2} * (v_OB_ITAX(i.r, i.p, i.cur, i.y) - v_OB_ISUB(i.r, i.p, i.cur, i.y)) as value
        {base}
          and (in_OB_ITAX(i.r, i.p, i.cur, i.y) or in_OB_ISUB(i.r, i.p, i.cur, i.y))
    """)
    _one_currency(db, "resid_invx")
    db.put("CST_INVX", f"""
        select r, v as y, per as y2, p, '{label}' as sysuc, value from resid_invx
    """)


def _decommission(db):
    """Lines 78-85. Annual decommissioning over the operating years.

        OPTION OBJ_SUMSI <= OBJ_SUMIII;
        F = RTP_CAPVL * OBJ_CRF / OBJ_DIVIII; Z = ROUND(NCAP_ELIFE);
        CST_DECC(R,VNT(V,T),P) = SUM(OBJ_SUMSI(R,V,P,LL)$((YEARVAL(T) < YEARVAL(LL)+Z)$YK(T,LL)),
            (SUM(OBJ_SUMIII(R,V,P,LL,K,Y), OBJ_DISC(R,Y,CUR)*OBJ_DCOST(R,K,P,CUR))*COR_SALVD
             + SUM(OBJ_SUMIVS(R,V,P,K(LL),Y), OBJ_DISC(R,Y,CUR))*OBJ_DLAGC(R,LL,P,CUR))
            * F / OBJ_DISC(R,LL,CUR));

    OBJ_DCOST(R,K,P,CUR) is OB_DCC(R,P,CUR,K). The loop runs only where that cost exists at
    the vintage. OBJ_SUMSI is the first four indexes of OBJ_SUMIII, so (R,V,P,LL).
    %INVLIF% is ELIFE. YK(T,LL) is YEARVAL(LL) <= YEARVAL(T).
    """
    db.declare("CST_DECC", "par", ["R", "ALLYEAR", "T", "P"])
    db.clear("CST_DECC")
    need = ("OBJ_ICUR", "OBJ_SUMIII", "VNT", "YK", "OB_DCC", "OBJ_CRF", "OBJ_DIVIII",
            "OBJ_DISC", "COR_SALVD", "NCAP_YES")
    if not all(n in db.sym for n in need) or not db.card("OBJ_SUMIII"):
        return
    db.x("""
        create or replace temp table dec_spread as
        select u.r, u.y as v, u.p, u.y2 as ll, i.cur,
               sum(v_OBJ_DISC(u.r, u.y4, i.cur) * v_OB_DCC(u.r, u.p, i.cur, u.y3)) as value
        from OBJ_SUMIII u
        join OBJ_ICUR i on i.r = u.r and i.y = u.y and i.p = u.p
        group by u.r, u.y, u.p, u.y2, i.cur
    """)
    lag = "0"
    if "OBJ_SUMIVS" in db.sym and db.card("OBJ_SUMIVS") and "OB_DLC" in db.sym:
        db.x("""
            create or replace temp table dec_lag as
            select u.r, u.y as v, u.p, u.y2 as ll, i.cur,
                   sum(v_OBJ_DISC(u.r, u.y3, i.cur)) as value
            from OBJ_SUMIVS u
            join OBJ_ICUR i on i.r = u.r and i.y = u.y and i.p = u.p
            group by u.r, u.y, u.p, u.y2, i.cur
        """)
        lag = "coalesce(g.value, 0) * v_OB_DLC(i.r, i.p, i.cur, s.ll)"
    join_lag = "left join dec_lag g on g.r = i.r and g.v = i.y and g.p = i.p and g.ll = s.ll and g.cur = i.cur" \
        if lag != "0" else ""
    db.x(f"""
        create or replace temp table dec_bycur as
        select i.r, i.y as v, vn.y2 as per, i.p, i.cur,
               (c.value * v_OBJ_CRF(i.r, i.y, i.p, i.cur) / v_OBJ_DIVIII(i.r, i.y, i.p))
               * sum((s.value * v_COR_SALVD(i.r, i.y, i.p, i.cur) + ({lag}))
                     / v_OBJ_DISC(i.r, s.ll, i.cur)) as value
        from OBJ_ICUR i
        join rtp_capvl c on c.r = i.r and c.y = i.y and c.p = i.p
        join VNT vn on vn.y = i.y
        join dec_spread s on s.r = i.r and s.v = i.y and s.p = i.p and s.cur = i.cur
        {join_lag}
        where in_NCAP_YES(i.r, i.y, i.p) and v_OBJ_DIVIII(i.r, i.y, i.p) <> 0
          and (in_OB_DCC(i.r, i.p, i.cur, i.y) or v_OB_DCC(i.r, i.p, i.cur, i.y) <> 0)
          and v_OBJ_DISC(i.r, s.ll, i.cur) <> 0
          and in_YK(vn.y2, s.ll)
          and try_cast(vn.y2 as integer)
              < try_cast(s.ll as integer) + round(v_NCAP_ELIFE(i.r, i.y, i.p))
        group by i.r, i.y, vn.y2, i.p, i.cur, c.value
    """)
    _one_currency(db, "dec_bycur")
    db.put("CST_DECC", "select r, v as y, per as y2, p, value from dec_bycur")


def _fixed(db, cnt=False):
    """Lines 90-114, without ACL. With CNT 0 the capacity weight is replaced and the
    age spread does not shift:

        COEF_RVPT(NCAP_YES(RTP),T)$COEF_RVPT(RTP,T) = (1+RTP_CPX$NCAP_CPX)/MAX(1,OBJ_DIVIV);
        FIL2(T) = ORD(T);                         -- the $CNT term is 0
        YKAGE(T,LL,AGE(ORD(T)-ORD(LL)+1))$
            (INVSTEP(K_EOH,JOT,LL,JOT)$OPYEAR(LIFE,AGE)$COEF_RVPT) = YES;
        FIL2(T) = RTP_CAPVL * COEF_RVPT;          -- SUM(YKAGE)$CNT is 0
        CST_FIXC(R,V,T,P) $= CSTVPJ('1', ..., 'FIX');

    INVSTEP comes from eqobjfix.mod line 160. With AGE numbered 1..N, ORD(AGE) is the
    number, so the fourth index equals JOT and the payment year is K_EOH+AGE-1 for
    each AGE in OPYEAR(JOT,AGE). The age in the period is YEARVAL(T)-YEARVAL(LL)+1.

    With CNT (RPT_OPT('OBJ','2') without ANNCOST LEV) lines 91-98 restore NCAP_YES without the residual
    vintages, keep the weight COEF_RVPT that line 42 copied from COEF_CPT, shift the age to the start of the
    vintage and divide the weight by the number of (payment year, age) pairs of the period:

        NCAP_YES(OBJ_YES)=YES; NCAP_YES(R,PYR_S,P)$PRC_RESID(R,'0',P)=NO; FIL(PYR_S)=1;
        MY_FIL2(T)=COEF_RVPT(R,V,P,T); MY_F = B(V)+NCAP_ILED(R,V,P);
        LOOP(OBJ_SUMIV(K_EOH,R,V,P,JOT,LIFE), Z=ORD(LIFE)-1;
          FIL2(T(YEAR))=ORD(YEAR)+(MAX(0,MY_F-M(T))-MAX(0,M(T)-MY_F-Z))$CNT;
          YKAGE(T,LL,AGE(LIFE+(FIL2(T)-ORD(LL)-Z)))$(INVSTEP(K_EOH,JOT,LL,JOT)$OPYEAR(LIFE,AGE)$MY_FIL2(T)) = YES);
        FIL2(T)=F*MY_FIL2(T)/MAX(1,SUM(YKAGE(T,LL,AGE),1)$CNT);

    so the age is FIL2(T)-YEARVAL(LL)+1.
    """
    db.declare("CST_FIXC", "par", ["R", "ALLYEAR", "T", "P"])
    db.declare("CST_FIXX", "par", ["R", "ALLYEAR", "T", "P"])
    db.clear("CST_FIXC")
    db.clear("CST_FIXX")
    if cnt:
        db.assign("NCAP_YES", "select r, y, p from ann_objyes")
        _drop_residual(db)
    if not all(n in db.sym for n in ("OBJ_FCUR", "OBJ_SUMIV", "OPYEAR", "COEF_CPT", "OB_FOM")):
        return
    cpx = "case when in_NCAP_CPX(c.r, c.y, c.p) then v_RTP_CPX(c.r, c.y, c.p, c.y2) else 0 end" \
        if "NCAP_CPX" in db.sym else "0"
    weight = "c.value" if cnt else f"(1 + ({cpx})) / greatest(1, v_OBJ_DIVIV(c.r, c.y, c.p))"
    db.x(f"""
        create or replace temp table ann_weight as
        select c.r, c.y as v, c.p, c.y2 as per, {weight} as value
        from COEF_CPT c
        where in_NCAP_YES(c.r, c.y, c.p) and in_COEF_CPT(c.r, c.y, c.y2, c.p)
    """)
    # Payment years of INVSTEP(K_EOH, JOT, LL, JOT).
    db.x("""
        create or replace temp table inv_step as
        select distinct u.y as k_eoh, u.age as jot, ay.y as ll
        from OBJ_SUMIV u
        join OPYEAR op on op.age = u.age
        join ALLYEAR ay
          on try_cast(ay.y as integer) = try_cast(u.y as integer) + try_cast(op.age2 as integer) - 1
    """)
    fil2 = "try_cast(w.per as integer)"
    if cnt:
        my_f = "(v_B(u.y2) + v_NCAP_ILED(u.r, u.y2, u.p))"
        fil2 = (f"({fil2} + greatest(0, {my_f} - v_M(w.per))"
                f" - greatest(0, v_M(w.per) - {my_f} - (try_cast(u.age2 as integer) - 1)))")
    age = f"cast(cast({fil2} - try_cast(s.ll as integer) + 1 as bigint) as varchar)"
    db.x(f"""
        create or replace temp table ykage as
        select distinct u.r, u.y2 as v, u.p, s.ll, w.per, {age} as age
        from OBJ_SUMIV u
        join inv_step s on s.k_eoh = u.y and s.jot = u.age
        join ann_weight w on w.r = u.r and w.v = u.y2 and w.p = u.p
        where in_NCAP_YES(u.r, u.y2, u.p) and in_OPYEAR(u.age2, {age})
    """)
    if cnt:
        db.x("""
            create or replace temp table ann_weight as
            select w.r, w.v, w.p, w.per,
                   w.value / greatest(1, (select count(*) from ykage g
                                          where g.r = w.r and g.v = w.v and g.p = w.p and g.per = w.per)) as value
            from ann_weight w
        """)
    shape = _shape_factor(db, "'1'")
    # An EPS fixed cost times a real shape is EPS, and a real cost absorbs an EPS year as zero.
    # EPS capacity times a hard zero is a hard zero, which the plain '=' does not store.
    fom_eps = "in_OB_FOM(f.r, f.p, f.cur, g.ll) and v_OB_FOM(f.r, f.p, f.cur, g.ll) = 0"
    fom_num = (f"sum(case when {fom_eps} or v_OB_FOM(f.r, f.p, f.cur, g.ll) = 0 then 0 "
               f"else v_OB_FOM(f.r, f.p, f.cur, g.ll) * ({shape}) end)")
    fom_neps = f"sum(case when {fom_eps} and ({shape}) <> 0 then 1 else 0 end)"
    db.x(f"""
        create or replace temp table fix_bycur as
        select f.r, f.y as v, g.per, f.p, f.cur,
               case when c.value <> 0 and {fom_num} <> 0
                    then c.value * w.value * {fom_num} else 0 end as value,
               case when {fom_num} <> 0 and c.value <> 0 then 0
                    when {fom_num} = 0 and {fom_neps} = 0 then 0
                    else 1 end as is_eps
        from OBJ_FCUR f
        join rtp_capvl c on c.r = f.r and c.y = f.y and c.p = f.p
        join ykage g on g.r = f.r and g.v = f.y and g.p = f.p
        join ann_weight w on w.r = f.r and w.v = f.y and w.p = f.p and w.per = g.per
        where in_NCAP_YES(f.r, f.y, f.p)
        group by f.r, f.y, g.per, f.p, f.cur, c.value, w.value
    """)
    _one_currency(db, "fix_bycur", eps=True)
    db.put("CST_FIXC", """
        select r, v as y, per as y2, p, value from fix_bycur where is_eps = 0
    """, zero="skip")
    db.put("CST_FIXC", """
        select r, v as y, per as y2, p, 0 as value from fix_bycur where is_eps = 1
    """, zero="eps")
    _fixed_tax(db)
    _fixed_residual(db)
    _scale_retired(db)


def _shape_factor(db, group):
    """1+SUM(RTP_SHAPE(R,V,P,group,J,JJ), SHAPE(J,AGE)*MULTI(JJ,T)-1). No row gives 1."""
    if "RTP_SHAPE" not in db.sym or db.card("RTP_SHAPE") == 0:
        return "1"
    return f"""1 + coalesce((
        select sum(v_SHAPE(sh.j2, g.age) * v_MULTI(sh.j3, g.per) - 1)
        from RTP_SHAPE sh
        where sh.r = g.r and sh.y = g.v and sh.p = g.p and sh.j = {group}
    ), 0)"""


def _fixed_tax(db):
    """Column '2', where the vintage has a fixed tax or a subsidy."""
    if "OB_FTX" not in db.sym and "OB_FSB" not in db.sym:
        return
    shape_tx = _shape_factor(db, "'2'")
    shape_sb = _shape_factor(db, "'3'")
    db.x(f"""
        create or replace temp table fixx_bycur as
        select f.r, f.y as v, g.per, f.p, f.cur,
               c.value * w.value * sum(
                   v_OB_FTX(f.r, f.p, f.cur, g.ll) * ({shape_tx})
                   - v_OB_FSB(f.r, f.p, f.cur, g.ll) * ({shape_sb})
               ) as value
        from OBJ_FCUR f
        join rtp_capvl c on c.r = f.r and c.y = f.y and c.p = f.p
        join ykage g on g.r = f.r and g.v = f.y and g.p = f.p
        join ann_weight w on w.r = f.r and w.v = f.y and w.p = f.p and w.per = g.per
        where in_NCAP_YES(f.r, f.y, f.p)
          and (in_OB_FTX(f.r, f.p, f.cur, f.y) or in_OB_FSB(f.r, f.p, f.cur, f.y))
        group by f.r, f.y, g.per, f.p, f.cur, c.value, w.value
    """)
    _one_currency(db, "fixx_bycur")
    db.put("CST_FIXX", """
        select r, v as y, per as y2, p, value from fixx_bycur
    """, zero="eps")


def _fixed_residual(db):
    """Lines 110-114. The residual vintages kept the capacity fraction, not 1/OBJ_DIVIV.

        CST_FIXC(RTP_CPTYR) = NCAP_PASTI*COEF_RVPT * OBJ_FOM(R,V,P,CUR)
                              * (1+SUM(RTP_SHAPE(...,'1',J,JJ), MULTI(JJ,T)-1));
    """
    if "RTP_CPTYR" not in db.sym or "PYR_S" not in db.sym:
        return
    multi = "1"
    if "RTP_SHAPE" in db.sym and db.card("RTP_SHAPE"):
        multi = """1 + coalesce((
            select sum(v_MULTI(sh.j3, a.y2) - 1) from RTP_SHAPE sh
            where sh.r = i.r and sh.y = i.y and sh.p = i.p and sh.j = '1'
        ), 0)"""
    db.x(f"""
        create or replace temp table resid_fix as
        select i.r, i.y as v, a.y2 as per, i.p, i.cur,
               v_NCAP_PASTI(i.r, i.y, i.p) * v_COEF_CPT(i.r, i.y, a.y2, i.p)
               * v_OB_FOM(i.r, i.p, i.cur, i.y) * ({multi}) as value
        from OBJ_FCUR i
        join RTP_CPTYR a on a.r = i.r and a.y = i.y and a.p = i.p
        where in_PYR_S(i.y) and in_PRC_RESID(i.r, '0', i.p)
    """)
    _one_currency(db, "resid_fix")
    db.put("CST_FIXC", "select r, v as y, per as y2, p, value from resid_fix")
    if "OB_FTX" not in db.sym and "OB_FSB" not in db.sym:
        return
    multi2 = multi.replace("sh.j = '1'", "sh.j = '2'")
    multi3 = multi.replace("sh.j = '1'", "sh.j = '3'")
    db.x(f"""
        create or replace temp table resid_fixx as
        select i.r, i.y as v, a.y2 as per, i.p, i.cur,
               v_NCAP_PASTI(i.r, i.y, i.p) * v_COEF_CPT(i.r, i.y, a.y2, i.p)
               * (v_OB_FTX(i.r, i.p, i.cur, i.y) * ({multi2})
                  - v_OB_FSB(i.r, i.p, i.cur, i.y) * ({multi3})) as value
        from OBJ_FCUR i
        join RTP_CPTYR a on a.r = i.r and a.y = i.y and a.p = i.p
        where in_PYR_S(i.y) and in_PRC_RESID(i.r, '0', i.p)
          and (in_OB_FTX(i.r, i.p, i.cur, i.y) or in_OB_FSB(i.r, i.p, i.cur, i.y))
    """)
    _one_currency(db, "resid_fixx")
    db.put("CST_FIXX", "select r, v as y, per as y2, p, value from resid_fixx", zero="eps")


def _scale_retired(db):
    """Lines 116-119. The share from line 17 becomes the capacity still online.

        COEF_CAP(RTP_CPTYR)$COEF_CAP = 1 - COEF_CAP + EPS;
        CST_FIXC(RTP_CPTYR) $= COEF_CAP * CST_FIXC;
        CST_FIXX(RTP_CPTYR) $= COEF_CAP * CST_FIXX;

    A full retirement (share 1) becomes EPS, so a cost that was there is stored as EPS.
    Adding EPS to any other share leaves the share, and a true zero share was never stored.
    """
    if db.q1("select count(*) from ann_share") == 0:
        return
    db.x("""
        create or replace temp table cap_remain as
        select r, v, per, p,
               case when value = 1 then 0 else 1 - value end as value,
               case when value = 1 then 1 else 0 end as eps
        from ann_share
    """)
    for name in ("CST_FIXC", "CST_FIXX"):
        if name not in db.sym or db.card(name) == 0:
            continue
        db.x(f"""
            create or replace temp table scaled as
            select f.r, f.y, f.y2, f.p,
                   case when m.eps = 1 or f.value = 0 then 0 else f.value * m.value end as value,
                   case when m.eps = 1 or f.value = 0 then 1 else 0 end as is_eps
            from "{name}" f
            join cap_remain m on m.r = f.r and m.v = f.y and m.per = f.y2 and m.p = f.p
        """)
        db.put(name, "select r, y, y2, p, value from scaled where is_eps = 0")
        db.put(name, "select r, y, y2, p, 0 as value from scaled where is_eps = 1", zero="eps")


def _salvage(db):
    """rpt_objc.rpt lines 80-87 write the coefficient; cost_ann.rpt lines 205-208 scale it.

        PAR_OBJSAL(RTP,CUR)$RDCUR =
            SUM(OBJ_SUMS, OBJSCC) * OBJ_DCEOH
                * (1+SUM(NCAP_YES, VAR_SCAP.L(R,T,'0',P)/RTP_CAPVL-1)$RVPRL)
            + SUM(OBJ_SUMS3, SALV_DEC) * OBJ_DCEOH
            + SUM(OBJ_SUMIVS(K,Y)$SALV_INV, OBJ_DISC(Y)*OBJ_DLAGC(K)*SALV_INV);
        PAR_OBJSAL(OBJ_ICUR) = PAR_OBJSAL * VAR_NCAP.L $ NCAP_YES;
        CST_SALV(R,T,P) $= SUM(RDCUR, PAR_OBJSAL);

    The $RVPRL sum is the retired share at period '0' when that vintage is still in
    NCAP_YES, and 1 otherwise. Records outside OBJ_ICUR are not rescaled.
    """
    db.declare("CST_SALV", "par", ["R", "ALLYEAR", "P"])
    db.clear("CST_SALV")
    if not all(n in db.sym for n in ("RTP", "RDCUR", "OBJ_DCEOH", "OBJSCC", "OBJ_SUMS")):
        return
    # rpt_obj.rpt called without rpt_objc.rpt (TIMES-MACRO, rpt_ext.mlf): PAR_OBJSAL has no coefficient to scale
    if getattr(db, "no_objc", False):
        return
    retired = "1"
    if "RVPRL" in db.sym and "L_VAR_SCAP" in db.sym:
        retired = """case when (in_RVPRL(t.r, t.y, t.p) or v_RVPRL(t.r, t.y, t.p) <> 0)
                          and in_NCAP_YES(t.r, t.y, t.p) and c.value <> 0
                     then v_L_VAR_SCAP(t.r, t.y, '0', t.p) / c.value else 1 end"""
    dec = "0"
    if "SALV_DEC" in db.sym and "OBJ_SUMS3" in db.sym:
        dec = "case when in_OBJ_SUMS3(t.r, t.y, t.p) then v_SALV_DEC(t.r, t.y, t.p, d.cur) else 0 end"
    db.x(f"""
        create or replace temp table par_objsal as
        select t.r, t.y, t.p, d.cur,
               (case when in_OBJ_SUMS(t.r, t.y, t.p) then v_OBJSCC(t.r, t.y, t.p, d.cur) else 0 end
                * v_OBJ_DCEOH(t.r, d.cur) * ({retired})
                + ({dec}) * v_OBJ_DCEOH(t.r, d.cur)) as value
        from RTP t
        left join rtp_capvl c on c.r = t.r and c.y = t.y and c.p = t.p
        join RDCUR d on d.r = t.r
    """)
    if "OBJ_SUMIVS" in db.sym and db.card("OBJ_SUMIVS") and "SALV_INV" in db.sym and "OB_DLC" in db.sym:
        db.x("""
            create or replace temp table sal_lag as
            select u.r, u.y, u.p, i.cur,
                   sum(v_OBJ_DISC(u.r, u.y3, i.cur) * v_OB_DLC(u.r, u.p, i.cur, u.y2)
                       * v_SALV_INV(u.r, u.y, u.p, u.y2)) as value
            from OBJ_SUMIVS u
            join RDCUR i on i.r = u.r
            where v_SALV_INV(u.r, u.y, u.p, u.y2) <> 0 or in_SALV_INV(u.r, u.y, u.p, u.y2)
            group by u.r, u.y, u.p, i.cur
        """)
        db.x("""
            update par_objsal s set value = s.value + g.value
            from sal_lag g
            where g.r = s.r and g.y = s.y and g.p = s.p and g.cur = s.cur
        """)
    # Line 205. A vintage in OBJ_ICUR is multiplied by its new-capacity level.
    # An EPS level times a real coefficient is EPS, and $= stores it
    # (elc_grid CH 2010 ENGA).
    level = "v_L_VAR_NCAP(s.r, s.y, s.p)" if "L_VAR_NCAP" in db.sym else "0"
    level_eps = (f"in_L_VAR_NCAP(s.r, s.y, s.p) and ({level}) = 0"
                 if "L_VAR_NCAP" in db.sym else "false")
    ncap = "in_NCAP_YES(s.r, s.y, s.p)" if "NCAP_YES" in db.sym else "false"
    icur = "in_OBJ_ICUR(s.r, s.y, s.p, s.cur)" if "OBJ_ICUR" in db.sym else "false"
    db.x(f"""
        create or replace temp table sal_scaled as
        select s.r, s.y, s.p, s.cur,
               case when {icur} and {ncap} and ({level}) <> 0 then s.value * ({level})
                    when not ({icur}) then s.value
                    else 0 end as value,
               case when {icur} and {ncap} and ({level_eps}) then 1 else 0 end as is_eps
        from par_objsal s
        where s.value <> 0
    """)
    db.x("""
        create or replace temp table sal_sum as
        select r, y, p,
               sum(case when is_eps = 0 then value else 0 end order by cur) as value,
               case when sum(case when is_eps = 0 then value else 0 end order by cur) = 0
                     and sum(is_eps) > 0 then 1 else 0 end as is_eps
        from sal_scaled
        where in_RDCUR(r, cur)
        group by r, y, p
    """)
    db.put("CST_SALV", "select r, y, p, value from sal_sum where is_eps = 0", zero="skip")
    db.put("CST_SALV", "select r, y, p, 0 as value from sal_sum where is_eps = 1", zero="eps")


def _time(db):
    """Line 166. The label is LEVCOST with ANNCOST LEV (line 165), else COST.

        CST_TIME(R,T,ANNUAL,'%X1%COST') = COEF_PVT(R,T);
    """
    db.declare("CST_TIME", "par", ["R", "ALLYEAR", "S", "SYSUC"])
    db.clear("CST_TIME")
    if "COEF_PVT" not in db.sym:
        return
    db.put("CST_TIME", """
        select r, y, 'ANNUAL' as s, '{label}' as sysuc, value from COEF_PVT
    """.format(label="LEVCOST" if levelized(db)[1] else "COST"))


def _variable(db):
    """Lines 167-169. The second eqobjvar call rewrites both columns at period T, and the
    two activity columns are summed over the reporting currencies.

        CST_ACTC(R,V,T,P,'-') $= SUM(CUR$PAR_ACTC('1',...,'ACT',CUR), PAR_ACTC('1',...));
        CST_ACTC(R,V,T,P,'+') $= SUM(CUR$PAR_ACTC('2',...,'ACT',CUR), PAR_ACTC('2',...));

    With ANNCOST LEV line 167 is not taken: the two columns are those of the rpt_obj.rpt line 128 call
    (discounted to the base year), and line 165 divides each by OBJ_PVT(R,T,CUR) (%TMP%).
    """
    lev = levelized(db)[1]
    if not lev:
        eqobjvar.annual(db)
    per = "/ v_OBJ_PVT(r, y2, cur)" if lev else ""
    ann = "/ v_OBJ_PVT(r, y, cur)" if lev else ""
    db.declare("CST_ACTC", "par", ["R", "ALLYEAR", "T", "P", "RPM"])
    db.clear("CST_ACTC")
    if "PAR_ACTC" not in db.sym:
        return
    for j, sign in (("1", "-"), ("2", "+")):
        db.put("CST_ACTC", f"""
            select r, y, y2, p, '{sign}' as rpm, sum(value {per}) as value
            from PAR_ACTC
            where j = '{j}' and c = 'ACT' and in_RDCUR(r, cur)
            group by r, y, y2, p
        """, zero="skip")
    # Lines 170-173. $= drops a zero sum.
    db.declare("CST_FLOC", "par", ["R", "ALLYEAR", "T", "P", "C"])
    db.declare("CST_FLOX", "par", ["R", "ALLYEAR", "T", "P", "C"])
    db.declare("CST_COMC", "par", ["R", "ALLYEAR", "C"])
    db.declare("CST_COMX", "par", ["R", "ALLYEAR", "C"])
    db.clear("CST_FLOC", "CST_FLOX", "CST_COMC", "CST_COMX")
    if "PAR_FLOC" in db.sym:
        db.put("CST_FLOC", f"""
            select r, y, y2, p, c, sum(value {per}) as value from PAR_FLOC
            where j = '1'
            group by r, y, y2, p, c
        """, zero="skip")
        _sum_eps(db, "CST_FLOX", "PAR_FLOC", "j = '2'", "r, y, y2, p, c", f"value {per}")
    if "PAR_COMC" in db.sym:
        db.put("CST_COMC", f"""
            select r, y, c, sum(value {ann}) as value from PAR_COMC
            where j = '1'
            group by r, y, c
        """, zero="skip")
        _sum_eps(db, "CST_COMX", "PAR_COMC", "j = '2'", "r, y, c", f"value {ann}")


def _trade(db):
    """Lines 126-160. Import and export marginals, then the trade cost.

    The group and export loops replace the direct marginal. REG_IREC sums the price
    before line 151 divides it by COEF_PVT; CST_IREC uses the divided price.

        PAR_IPRIC(RTP,C,TS,'IMP') $= -EQ_IRE.M(R,T,P,C,'IMP',TS);
        PAR_IPRIC(RTP,C,TS,'EXP') $= EQ_IRE.M(R,T,P,C,'EXP',TS);
        PAR_IPRIC(...) = PAR_IPRIC / COEF_PVT(R,T);
        CST_IREC(RTP_VINTYR,C) $= SUM((RTPCS_VARF,RPC_IREIO(...,'IN')), PAR_IPRIC*PAR_IRE);
        REG_IREC(R) $= SUM(P, PRC_YMAX(R,P));
    """
    db.declare("PAR_IPRIC", "par", ["R", "ALLYEAR", "P", "C", "TS", "IE"])
    db.declare("CST_IREC", "par", ["R", "ALLYEAR", "T", "P", "C"])
    db.declare("REG_IREC", "par", ["REG"])
    db.clear("PAR_IPRIC", "CST_IREC", "REG_IREC")
    # OPTION CLEAR=OBJ_YES. The capacity set was already restored from it.
    if "OBJ_YES" in db.sym:
        db.clear("OBJ_YES")
    if "M_EQ_IRE" not in db.sym:
        return
    # $= : a zero marginal is not stored. An EPS marginal is.
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'IMP' as ie, -value as value from M_EQ_IRE
        where ie = 'IMP' and in_RTP(r, y, p) and value <> 0
    """)
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'IMP' as ie, 0 as value from M_EQ_IRE
        where ie = 'IMP' and in_RTP(r, y, p) and value = 0
    """, zero="eps")
    _trade_groups(db)
    _trade_export(db)
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'EXP' as ie, value from M_EQ_IRE
        where ie = 'EXP' and in_RTP(r, y, p) and value <> 0
    """)
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'EXP' as ie, 0 as value from M_EQ_IRE
        where ie = 'EXP' and in_RTP(r, y, p) and value = 0
    """, zero="eps")
    _trade_from_export(db)
    _reg_irec(db)
    if "COEF_PVT" in db.sym and db.card("PAR_IPRIC"):
        db.x("""
            create or replace temp table ipric_scaled as
            select r, y, p, c, s, ie,
                   case when value = 0 or v_COEF_PVT(r, y) = 0 then 0
                        else value / v_COEF_PVT(r, y) end as value,
                   case when value = 0 and v_COEF_PVT(r, y) <> 0 then 1 else 0 end as is_eps
            from PAR_IPRIC
            where v_COEF_PVT(r, y) <> 0 or value = 0
        """)
        db.clear("PAR_IPRIC")
        db.put("PAR_IPRIC", "select r, y, p, c, s, ie, value from ipric_scaled where is_eps = 0")
        db.put("PAR_IPRIC", "select r, y, p, c, s, ie, 0 as value from ipric_scaled where is_eps = 1",
               zero="eps")
    _cst_irec(db)


def _trade_groups(db):
    """The same-region commodity group. A plain '=' replaces the import marginal, and a
    zero sum removes it.

        CG_GRP(R,P,C,COM)$TOP_IRE(R,C,R,COM,P) = YES;
        PAR_IPRIC(RTPCS_VARF,'IMP')$TOP_IRE(REG,COM1,R,C,P) = -SUM(...);
    """
    need = ("TOP_IRE", "RPC_MARKET", "RTPCS_VARF", "RS_TREE", "IRE_TSCVT", "IRE_CCVT", "RS_FR")
    if not all(n in db.sym for n in need):
        return
    db.x("""
        create or replace temp table ire_grp as
        select t.r, t.y, t.p, t.c, t.s, t.reg, t.com1, t.com,
               -coalesce(sum(m.value * cv.value
                   * v_IRE_CCVT(t.reg, t.com1, t.reg, t.com)
                   * v_IRE_CCVT(t.r, t.c, t.reg, t.com1)
                   * v_RS_FR(t.r, tree.s, tree.s2)), 0) as value
        from (
            select d.r as reg, d.c as com1, d.c2 as com, f.r, f.y, f.p, f.c, f.s
            from TOP_IRE d
            join TOP_IRE k on k.r = d.r and k.c = d.c and k.p = d.p
            join RTPCS_VARF f on f.r = k.r2 and f.p = k.p and f.c = k.c2
            where d.r = d.r2 and in_RPC_MARKET(d.r, d.p, d.c2, 'IMP')
        ) t
        left join RS_TREE tree on tree.r = t.r and tree.s2 = t.s
        left join IRE_TSCVT cv on cv.r = t.r and cv.s = tree.s and cv.r2 = t.reg
        left join M_EQ_IRE m on m.r = t.reg and m.y = t.y and m.p = t.p and m.c = t.com
                            and m.ie = 'IMP' and m.s = cv.s2
        group by t.r, t.y, t.p, t.c, t.s, t.reg, t.com1, t.com
    """)
    # The loop assigns with '='. The last CG_GRP tuple in label order is the one kept.
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'IMP' as ie, value from (
            select r, y, p, c, s, value,
                   row_number() over (partition by r, y, p, c, s
                                      order by reg desc, com1 desc, com desc) as rn
            from ire_grp
        ) q where rn = 1
    """)


def _trade_export(db):
    """Export price is the largest partner price. $= leaves a zero maximum unstored.

        PAR_XPRI(RTPCS_VARF,REG,COM)$(...'EXP','IN') = SUM(... EQ_IRE.M(...,'IMP',S) ...);
        PAR_IPRIC(RTPCS_VARF,'EXP') $= SMAX(TOP_IRE, PAR_XPRI);
    """
    need = ("TOP_IRE", "RPC_IREIO", "RTPCS_VARF", "RS_TREE", "IRE_TSCVT", "IRE_FLO", "IRE_CCVT", "RS_FR")
    if not all(n in db.sym for n in need):
        return
    # A partner price is the sum. An EPS marginal times nonzero factors is EPS, and a
    # plain '=' keeps that explicit zero. A numeric zero is deleted, so it is not a
    # candidate for SMAX. SMAX of only EPS is EPS, and $= stores it. A positive beats EPS.
    db.x("""
        create or replace temp table ire_xpri as
        with term as (
            select t.r, t.y, t.p, t.c, t.s, t.reg, t.com,
                   m.r is not null and cv.r is not null as onn,
                   m.value as mv,
                   v_IRE_FLO(t.r, t.y, t.p, t.c, t.reg, t.com, cv.s2) as flo,
                   v_IRE_CCVT(t.r, t.c, t.reg, t.com) as ccvt,
                   v_RS_FR(t.r, tree.s2, tree.s) as fr,
                   cv.value as tsc,
                   in_IRE_FLO(t.r, t.y, t.p, t.c, t.reg, t.com, cv.s2)
                       and in_IRE_CCVT(t.r, t.c, t.reg, t.com)
                       and in_RS_FR(t.r, tree.s2, tree.s) as hasf
            from (
                select f.r, f.y, f.p, f.c, f.s, k.r2 as reg, k.c2 as com
                from RTPCS_VARF f
                join RPC_IREIO io on io.r = f.r and io.p = f.p and io.c = f.c
                                  and io.ie = 'EXP' and io.io = 'IN'
                join TOP_IRE k on k.r = f.r and k.c = f.c and k.p = f.p
            ) t
            left join RS_TREE tree on tree.r = t.r and tree.s = t.s
            left join IRE_TSCVT cv on cv.r = t.r and cv.s = tree.s2 and cv.r2 = t.reg
            left join M_EQ_IRE m on m.r = t.reg and m.y = t.y and m.p = t.p and m.c = t.com
                                and m.ie = 'IMP' and m.s = cv.s2
        )
        select r, y, p, c, s, reg, com,
               sum(case when onn and hasf and mv <> 0 and flo <> 0 and ccvt <> 0
                             and fr <> 0 and tsc <> 0
                        then mv * flo * ccvt * fr * tsc else 0 end) as value,
               case when sum(case when onn and hasf and mv <> 0 and flo <> 0 and ccvt <> 0
                                       and fr <> 0 and tsc <> 0 then 1 else 0 end) = 0
                     and sum(case when onn and hasf and (mv = 0 or flo = 0 or ccvt = 0
                                                         or fr = 0 or tsc = 0) then 1 else 0 end) > 0
                     and sum(case when onn and not hasf then 1 else 0 end) = 0
                    then 1 else 0 end as is_eps
        from term
        group by r, y, p, c, s, reg, com
    """)
    # SMAX reads a missing partner price as a numeric zero, so a negative price loses to it
    # and $= then stores nothing. The maximum is EPS only when every partner price is EPS.
    db.x("""
        create or replace temp table ire_smax as
        select f.r, f.y, f.p, f.c, f.s, q.mx as value,
               case when q.all_eps = 1 then 1 else 0 end as is_eps
        from (
            select f.r, f.y, f.p, f.c, f.s,
                   max(case when x.is_eps = 1 then 0 else coalesce(x.value, 0) end) as mx,
                   min(case when x.is_eps = 1 then 1 else 0 end) as all_eps
            from RTPCS_VARF f
            join RPC_IREIO io on io.r = f.r and io.p = f.p and io.c = f.c
                              and io.ie = 'EXP' and io.io = 'IN'
            join TOP_IRE k on k.r = f.r and k.c = f.c and k.p = f.p
            left join ire_xpri x on x.r = f.r and x.y = f.y and x.p = f.p and x.c = f.c
                                and x.s = f.s and x.reg = k.r2 and x.com = k.c2
            group by f.r, f.y, f.p, f.c, f.s
        ) q
        join RTPCS_VARF f on f.r = q.r and f.y = q.y and f.p = q.p and f.c = q.c and f.s = q.s
        where q.mx <> 0 or q.all_eps = 1
    """)
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'EXP' as ie, value from ire_smax where is_eps = 0
    """, zero="skip")
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'EXP' as ie, 0 as value from ire_smax where is_eps = 1
    """, zero="eps")


def _trade_from_export(db):
    """An exporting market overwrites the import marginal in the linked region.

        PAR_IPRIC(RTPCS_VARF,'IMP')$TOP_IRE(REG,COM,R,C,P) =
            -SUM(..., EQ_IRE.M(REG,...,'EXP',S) / IRE_FLO(REG,...,TS) ...);
    """
    need = ("RPC_EQIRE", "TOP_IRE", "RTPCS_VARF", "RS_TREE", "IRE_TSCVT", "IRE_FLO", "IRE_CCVT", "RS_FR")
    if not all(n in db.sym for n in need):
        return
    db.x("""
        create or replace temp table ire_expimp as
        select t.r, t.y, t.p, t.c, t.s, t.reg, t.com,
               -coalesce(sum(case when v_IRE_FLO(t.reg, t.y, t.p, t.com, t.r, t.c, t.s) = 0 then null
                             else m.value / v_IRE_FLO(t.reg, t.y, t.p, t.com, t.r, t.c, t.s)
                                  * v_IRE_CCVT(t.r, t.c, t.reg, t.com)
                                  * v_RS_FR(t.r, tree.s, tree.s2) * cv.value end), 0) as value
        from (
            select e.r as reg, e.c as com, f.r, f.y, f.p, f.c, f.s
            from RPC_EQIRE e
            join TOP_IRE k on k.r = e.r and k.c = e.c and k.p = e.p
            join RTPCS_VARF f on f.r = k.r2 and f.p = k.p and f.c = k.c2
            where e.ie = 'EXP'
        ) t
        left join RS_TREE tree on tree.r = t.r and tree.s2 = t.s
        left join IRE_TSCVT cv on cv.r = t.r and cv.s = tree.s and cv.r2 = t.reg
        left join M_EQ_IRE m on m.r = t.reg and m.y = t.y and m.p = t.p and m.c = t.com
                            and m.ie = 'EXP' and m.s = cv.s2
        group by t.r, t.y, t.p, t.c, t.s, t.reg, t.com
    """)
    db.put("PAR_IPRIC", """
        select r, y, p, c, s, 'IMP' as ie, value from (
            select r, y, p, c, s, value,
                   row_number() over (partition by r, y, p, c, s
                                      order by reg desc, com desc) as rn
            from ire_expimp
        ) q where rn = 1
    """)


def _reg_irec(db):
    """PRC_YMAX and REG_IREC, while PAR_IPRIC is still undiscounted.

    $= of the sum. An EPS price times a real flow is EPS. A sum of only those,
    or of real terms that cancel plus an EPS term, is stored (elc_grid CH).
    A missing price is a numeric zero, not EPS.
    """
    need = ("RP_IRE", "RPC_IREIO", "RTP_VINTYR", "RPCS_VAR", "PAR_IRE")
    if not all(n in db.sym for n in need) or not db.card("PAR_IPRIC"):
        return
    db.x("""
        create or replace temp table ire_ymax as
        select i.r, i.p,
               sum(case when p.value <> 0 and pi.value <> 0 then p.value * pi.value else 0 end
                   order by io.c, io.ie, v.y, v.y2, sv.s) as value,
               case when sum(case when p.value <> 0 and pi.value <> 0 then 1 else 0 end) = 0
                     and sum(case when p.r is not null and (p.value = 0 or pi.value = 0)
                                  then 1 else 0 end) > 0
                    then 1 else 0 end as is_eps
        from RP_IRE i
        join RPC_IREIO io on io.r = i.r and io.p = i.p and io.io = 'IN'
        join RTP_VINTYR v on v.r = i.r and v.p = i.p
        join RPCS_VAR sv on sv.r = i.r and sv.p = i.p and sv.c = io.c
        join PAR_IRE pi on pi.r = i.r and pi.y = v.y and pi.y2 = v.y2 and pi.p = i.p
                       and pi.c = io.c and pi.s = sv.s and pi.ie = io.ie
        left join PAR_IPRIC p on p.r = i.r and p.y = v.y2 and p.p = i.p and p.c = io.c
                             and p.s = sv.s and p.ie = io.ie
        group by i.r, i.p
    """)
    db.x("""
        create or replace temp table ire_reg as
        select r,
               sum(case when is_eps = 0 then value else 0 end order by p) as value,
               case when sum(case when is_eps = 0 then value else 0 end order by p) = 0
                     and sum(is_eps) > 0 then 1 else 0 end as is_eps
        from ire_ymax
        group by r
    """)
    db.put("REG_IREC", "select r, value from ire_reg where is_eps = 0", zero="skip")
    db.put("REG_IREC", "select r, 0 as value from ire_reg where is_eps = 1", zero="eps")


def _cst_come(db):
    """Line 179: $BATINCLUDE eqobjels.rpt CST_COME(R,TT,C) TT, the cost of elastic demands (TIMESED YES):
        CST_COME(R,TT,C)$SUM(RCJ(R,C,'1',BDNEQ),1) =
          SUM((RDCUR(R,CUR),BDNEQ(BD)), BDSIG(BD) *
            SUM((PERIODYR(T,TT),COM_TS(R,C,S))$COM_ELAST(R,T,C,S,BD), COM_BPRICE(R,T,C,S,CUR) *
              (SUM(RCJ(R,C,J,BD), VAR_ELAST.L(R,T,C,S,J,BD) *
                ((1-BDSIG(BD)*(ORD(J)-.5)*COM_VOC(R,T,C,BD)/COM_STEP(R,C,BD))**(1/COM_ELAST(R,T,C,S,BD))))$(NOT COM_ELASTX(R,T,C,BD)))));
    (TT: the milestone years, so PERIODYR(T,TT) is T itself; shaped elasticities are not supported.)"""
    db.declare("CST_COME", "par", ["R", "ALLYEAR", "C"])
    db.clear("CST_COME")
    if "L_VAR_ELAST" not in db.sym or not db.card("RCJ"):
        return
    db.put("CST_COME", """
        select e.r, e.y, e.c, sum((case when e.l = 'LO' then 1 else -1 end) * b.value *
               v.value * power(1 - (case when e.l = 'LO' then 1 else -1 end) * (cast(k.j as DOUBLE) - .5) * v_COM_VOC(e.r, e.y, e.c, e.l)
                               / v_COM_STEP(e.r, e.c, e.l), 1 / e.value)) as value
        from COM_ELAST e
        join COM_TS t on t.r = e.r and t.c = e.c and t.s = e.s
        join RCJ k on k.r = e.r and k.c = e.c and k.l = e.l
        join RDCUR d on d.r = e.r
        join COM_BPRICE b on b.r = e.r and b.y = e.y and b.c = e.c and b.s = e.s and b.cur = d.cur
        join L_VAR_ELAST v on v.r = e.r and v.y = e.y and v.c = e.c and v.s = e.s and v.j = k.j and v.l = e.l
        where e.l in ('LO', 'UP') and in_MILESTONYR(e.y) and e.value <> 0
          and exists(select 1 from RCJ k1 where k1.r = e.r and k1.c = e.c and k1.j = '1' and k1.l in ('LO', 'UP'))
        group by e.r, e.y, e.c
    """)
    # Lines 180-181: IF(CARD(CST_PVP), CST_PVC('ELS',R,C)$SUM(RCJ(R,C,'1',BDNEQ),1) = SUM(T,CST_COME(R,T,C)*COEF_PVT(R,T)); ...)
    if "CST_PVP" in db.sym and db.card("CST_PVP") and "CST_PVC" in db.sym:
        db.put("CST_PVC", """select 'ELS' as sysuc, r, c, sum(value * v_COEF_PVT(r, y)) as value from CST_COME group by r, c""")


def _pv_ire(db):
    """Lines 180-182, when rpt_obj wrote discounted costs (RPT_OPT('OBJ','1')):
        IF(CARD(CST_PVP), CST_PVC('ELS',R,C)$SUM(RCJ(R,C,'1',BDNEQ),1) = SUM(T,CST_COME*COEF_PVT);
                          CST_PVP('IRE',RP_IRE(RP)) $= PRC_YMAX(RP));
    PRC_YMAX is the trade value _reg_irec summed ($=, EPS kept). The ELS line needs elastic demands (TIMESED),
    which the port refuses."""
    if "CST_PVP" not in db.sym or not db.card("CST_PVP"):
        return
    if not db.q1("select count(*) from information_schema.tables where table_name = 'ire_ymax'"):
        return
    db.put("CST_PVP", "select 'IRE' as sysuc, r, p, value from ire_ymax where value <> 0 or is_eps = 1", zero="eps")


def _cst_irec(db):
    """Line 159, after the price has been divided by COEF_PVT."""
    need = ("RTP_VINTYR", "RTPCS_VARF", "RPC_IREIO", "PAR_IRE", "RPC", "RP_IRE")
    if not all(n in db.sym for n in need) or not db.card("PAR_IPRIC"):
        return
    # $= of the sum. The timeslices are added in label order: an unordered sum of these
    # products does not cancel the way the ordered one does, and a plain '=' later
    # deletes the regional total only when the cancellation is exact. An EPS price
    # times a real flow is EPS, and a sum of only those is stored.
    db.x("""
        create or replace temp table ire_cost as
        select v.r, v.y, v.y2, v.p, f.c,
               sum(case when p.value <> 0 and pi.value <> 0 then p.value * pi.value else 0 end
                   order by f.s, io.ie) as value,
               case when sum(case when p.value <> 0 and pi.value <> 0 then 1 else 0 end) = 0
                     and sum(case when p.r is not null and (p.value = 0 or pi.value = 0)
                                  then 1 else 0 end) > 0
                    then 1 else 0 end as is_eps
        from RTP_VINTYR v
        join RTPCS_VARF f on f.r = v.r and f.y = v.y2 and f.p = v.p
        join RPC_IREIO io on io.r = v.r and io.p = v.p and io.c = f.c and io.io = 'IN'
        join PAR_IRE pi on pi.r = v.r and pi.y = v.y and pi.y2 = v.y2 and pi.p = v.p
                       and pi.c = f.c and pi.s = f.s and pi.ie = io.ie
        left join PAR_IPRIC p on p.r = v.r and p.y = v.y2 and p.p = v.p and p.c = f.c
                             and p.s = f.s and p.ie = io.ie
        where in_RPC(v.r, v.p, f.c) and in_RP_IRE(v.r, v.p)
        group by v.r, v.y, v.y2, v.p, f.c
    """)
    db.put("CST_IREC", "select r, y, y2, p, c, value from ire_cost where is_eps = 0", zero="skip")
    db.put("CST_IREC", "select r, y, y2, p, c, 0 as value from ire_cost where is_eps = 1",
           zero="eps")


def _regional(db):
    """Lines 186-196 and 209. Each item sums the costs already written. The $ on a cost
    drops a zero. Adding a nonzero absorbs EPS. Adding EPS to an exact zero stores
    EPS, which is the case only when the last term of the ordered sum is EPS.

        REG_ACOST(R,T,'INV') = SUM((VNT(V,T),P)$CST_INVC, CST_INVC);
        REG_OBJ(R) = SUM((RDCUR,ITEM,OBV)$SUM_OBJ, VAR_OBJ.L * SUM_OBJ);
    """
    db.declare("REG_ACOST", "par", ["R", "ALLYEAR", "ITEM"])
    db.clear("REG_ACOST")
    parts = []
    for item, src, cols, s1, s2 in (
        ("INV", "CST_INVC", "r, y2 as y", "p", "''"),
        ("INVX", "CST_INVX", "r, y2 as y", "p", "''"),
        ("FIX", "CST_FIXC", "r, y2 as y", "p", "''"),
        ("FIXX", "CST_FIXX", "r, y2 as y", "p", "''"),
        ("VAR", "CST_ACTC", "r, y2 as y", "p", "rpm"),
        ("VAR", "CST_FLOC", "r, y2 as y", "p", "c"),
        ("VAR", "CST_COMC", "r, y as y", "''", "c"),
        ("VARX", "CST_FLOX", "r, y2 as y", "p", "c"),
        ("VARX", "CST_COMX", "r, y as y", "''", "c"),
        ("IRE", "CST_IREC", "r, y2 as y", "p", "c"),
        ("ELS", "CST_COME", "r, y as y", "''", "c"),
    ):
        if src not in db.sym or db.card(src) == 0:
            continue
        parts.append(f"select {cols}, '{item}' as u, {s1} as s1, {s2} as s2, value from \"{src}\"")
    if parts:
        # The sum follows process then commodity, so cancelling trade costs meet as a pair.
        # An unordered sum of those pairs is a few ulps off zero, and the plain '=' keeps it.
        # EPS arithmetic, in that same order: a nonzero absorbs an earlier EPS, and an EPS
        # added to an exact zero is stored. So a zero sum is EPS only when the last term
        # is EPS (elc_grid CH 2012 IRE ends on GN23). GasGrid CH 2020 ends on a cancelling
        # pair, the earlier EPS is absorbed, and the plain '=' deletes the row.
        db.x(f"""
            create or replace temp table reg_raw as
            select r, y, u, sum(value order by s1, s2) as value,
                   case when sum(value order by s1, s2) = 0
                         and arg_max(value, (s1, s2)) = 0 then 1 else 0 end as is_eps
            from ({' union all '.join(parts)}) s
            group by r, y, u
        """)
        db.put("REG_ACOST", "select r, y, u, value from reg_raw where is_eps = 0", zero="skip")
        db.put("REG_ACOST", "select r, y, u, 0 as value from reg_raw where is_eps = 1", zero="eps")
    db.declare("REG_OBJ", "par", ["REG"])
    db.clear("REG_OBJ")
    if all(n in db.sym for n in ("L_VAR_OBJ", "SUM_OBJ", "RDCUR")):
        db.put("REG_OBJ", """
            select o.r, sum(o.value * s.value) as value
            from L_VAR_OBJ o
            join SUM_OBJ s on s.u2 = o.obv
            where in_RDCUR(o.r, o.cur)
            group by o.r
        """)


def _clear_worked(db):
    """Line 153 clears the objective work parameters, and line 198 clears the three
    eqobjvar parameters, both before the end of the report."""
    for name in ("RTP_OBJ", "RTP_NPV", "COEF_CRF", "COEF_RVPT", "PAR_ACTC", "PAR_COMC", "PAR_FLOC"):
        if name in db.sym:
            db.clear(name)


def _sum_eps(db, name, src, where, cols, value="value"):
    """$= of a sum. A stored 0 in the source is EPS. EPS plus a number is the number;
    a sum of only EPS is EPS and is stored."""
    db.x(f"""
        create or replace temp table sum_eps as
        select {cols}, sum({value}) as value,
               case when sum(case when value <> 0 then 1 else 0 end) = 0
                     and sum(case when value = 0 then 1 else 0 end) > 0 then 1 else 0 end as is_eps
        from "{src}"
        where {where}
        group by {cols}
    """)
    db.put(name, f"select {cols}, value from sum_eps where is_eps = 0", zero="skip")
    db.put(name, f"select {cols}, 0 as value from sum_eps where is_eps = 1", zero="eps")


def _one_currency(db, table, eps=False):
    """The currency loop assigns with '='. Two currencies writing one key is a clash."""
    clash = db.q(f"""
        select r, v, per, p, count(*), min(value), max(value) from {table}
        group by r, v, per, p
        having count(*) > 1 and min(value) <> max(value)
        limit 3
    """)
    if clash:
        raise SystemExit(f"cost_ann currency clash in {table}: {clash}")
    keep = ", max(is_eps) as is_eps" if eps else ""
    db.x(f"""
        create or replace temp table {table}_1 as
        select r, v, per, p, any_value(value) as value{keep} from {table} group by r, v, per, p
    """)
    db.x(f"create or replace temp table {table} as select * from {table}_1")
