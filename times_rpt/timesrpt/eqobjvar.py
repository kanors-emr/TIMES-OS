# SPDX-License-Identifier: GPL-3.0-or-later
"""eqobjvar.rpt, the call rpt_obj.rpt line 128 makes. The legacy block is past $EXIT.

    $BATINCLUDE eqobjvar.rpt PAR J(UNCD1), "J('2')," Y_EOH SUM

UNCD1('1') is MY_F+ACL. Both are 0 in a Veda run, so the cost column J('1') matches
nothing and is not written. J('2') is the tax and subsidy column, and it is what
REG_WOBJ(...,'VARX') sums.

VARCOST is LIN, so the pulse set at rpt_obj.rpt lines 121-125 is

    SUM(Y_EOH$OBJ_LINT(R,T,Y_EOH,CUR), OBJ_LINT(R,T,Y_EOH,CUR) * ...)

OBJ_FCOST / OBJ_FTAX are the filled caches OB_FCOS / OB_FTAX (fillcost.gms). A missing
cache reads as 0. %PGPRIM% is 'ACT'.
"""
from __future__ import annotations


def annual(db):
    """The cost_ann.rpt line 167 call. %5 is empty, so there is no Y_EOH pulse, and the
    cost is the one at period T. Both columns are written. Line 17 clears the three
    parameters first.

        $BATINCLUDE eqobjvar.rpt PAR J('1'), J('2'), T
    """
    for name, dom in (("PAR_ACTC", ["J", "R", "LL", "T", "P", "C", "CUR"]),
                      ("PAR_COMC", ["J", "R", "T", "C", "CUR"]),
                      ("PAR_FLOC", ["J", "R", "LL", "T", "P", "C", "CUR"])):
        db.declare(name, "par", dom)
        db.clear(name)
    _annual_activity(db)
    _annual_startup(db)
    _annual_commodity(db)
    if getattr(db, "stages", None):                # a run with STAGES: the uncertain commodity tax (lines 39-40)
        from . import stochastic
        stochastic.com_tax(db, pulse=False)
    _annual_flow(db)


def _annual_activity(db):
    """Column '1': the activity cost at the period. The stage exponent is 0 when the
    process is not in RP_STG, and POWER(x, 0) is 1.

        PAR_ACTC('1', RTP_VINTYR, 'ACT', CUR)$(RDCUR $ OBJ_ACOST(R,T,P,CUR))
            = OBJ_ACOST(R,T,P,CUR) * SUM(PRC_TS, VAR_ACT.L * POWER(RS_STGAV, 1$RP_STG));
    """
    if not all(n in db.sym for n in ("RTP_VINTYR", "PRC_TS", "L_VAR_ACT", "OB_ACT", "RDCUR")):
        return
    staged = "in_RP_STG(v.r, v.p)" if "RP_STG" in db.sym else "false"
    shape = f"case when {staged} then v_RS_STGAV(v.r, ts.s) else 1 end" if "RS_STGAV" in db.sym else "1"
    db.put("PAR_ACTC", f"""
        select '1' as j, v.r, v.y, v.y2, v.p, 'ACT' as c, d.cur,
               v_OB_ACT(v.r, v.p, d.cur, v.y2)
               * sum(v_L_VAR_ACT(v.r, v.y, v.y2, v.p, ts.s) * ({shape})) as value
        from RTP_VINTYR v
        join PRC_TS ts on ts.r = v.r and ts.p = v.p
        join RDCUR d on d.r = v.r
        where in_OB_ACT(v.r, v.p, d.cur, v.y2) or v_OB_ACT(v.r, v.p, d.cur, v.y2) <> 0
        group by v.r, v.y, v.y2, v.p, d.cur
    """)


def _annual_startup(db):
    """Column '2'. The three sums are added. With the pulse empty, each cost is the
    vintage value itself.

        PAR_ACTC('2', RTP_VINTYR, 'ACT', CUR)$RPC_CUR =
            SUM(RP_UPS(...,'UP'), ACT_CSTUP * SUM(TS_GROUP, RS_STGPRD * VAR_UPS.L))
          + SUM(RP_UPT(...,'UP'), ACT_CSTSD(...,'FX',CUR) * SUM(TS_GROUP$RP_DPL, RS_STGPRD * VAR_UPT.L))
          + SUM(RP_UPR(BDNEQ), ACT_CSTRMP * SUM(PRC_TS, RS_STGPRD * VAR_UDP.L));
    """
    if "RTP_VINTYR" not in db.sym or "RPC_CUR" not in db.sym:
        return
    parts = []
    if all(n in db.sym for n in ("RP_UPS", "ACT_CSTUP", "TS_GROUP", "RS_STGPRD", "L_VAR_UPS")) \
            and db.card("RP_UPS"):
        parts.append("""
            select v.r, v.y, v.y2, v.p, cu.cur,
                   v_ACT_CSTUP(v.r, v.y, v.p, ups.tsl, cu.cur)
                   * v_RS_STGPRD(v.r, g.s)
                   * v_L_VAR_UPS(v.r, v.y, v.y2, v.p, g.s, ups.l) as value
            from RTP_VINTYR v
            join RP_UPS ups on ups.r = v.r and ups.p = v.p and ups.l = 'UP'
            join TS_GROUP g on g.r = v.r and g.tsl = ups.tsl
            join RPC_CUR cu on cu.r = v.r and cu.p = v.p and cu.c = 'ACT'
        """)
    if all(n in db.sym for n in ("RP_UPT", "ACT_CSTSD", "TS_GROUP", "RP_DPL", "RS_STGPRD", "L_VAR_UPT")) \
            and db.card("RP_UPT"):
        parts.append("""
            select v.r, v.y, v.y2, v.p, cu.cur,
                   v_ACT_CSTSD(v.r, v.y, v.p, upt.upt, 'FX', cu.cur)
                   * v_RS_STGPRD(v.r, g.s)
                   * v_L_VAR_UPT(v.r, v.y, v.y2, v.p, g.s, upt.upt) as value
            from RTP_VINTYR v
            join RP_UPT upt on upt.r = v.r and upt.p = v.p and upt.l = 'UP'
            join TS_GROUP g on g.r = v.r
            join RP_DPL dpl on dpl.r = v.r and dpl.p = v.p and dpl.tsl = g.tsl
            join RPC_CUR cu on cu.r = v.r and cu.p = v.p and cu.c = 'ACT'
        """)
    if all(n in db.sym for n in ("RP_UPR", "ACT_CSTRMP", "PRC_TS", "RS_STGPRD", "L_VAR_UDP", "BDNEQ")) \
            and db.card("RP_UPR"):
        parts.append("""
            select v.r, v.y, v.y2, v.p, cu.cur,
                   v_ACT_CSTRMP(v.r, v.y, v.p, upr.l, cu.cur)
                   * v_RS_STGPRD(v.r, ts.s)
                   * v_L_VAR_UDP(v.r, v.y, v.y2, v.p, ts.s, upr.l) as value
            from RTP_VINTYR v
            join RP_UPR upr on upr.r = v.r and upr.p = v.p and in_BDNEQ(upr.l)
            join PRC_TS ts on ts.r = v.r and ts.p = v.p
            join RPC_CUR cu on cu.r = v.r and cu.p = v.p and cu.c = 'ACT'
        """)
    if not parts:
        return
    db.put("PAR_ACTC", f"""
        select '2' as j, r, y, y2, p, 'ACT' as c, cur, sum(value) as value
        from ({' union all '.join(parts)}) s
        group by r, y, y2, p, cur
    """)


def _annual_commodity(db):
    """Columns '1' and '2' at period T, with no pulse. $= keeps a zero sum out.

        PAR_COMC('1', R, T, C, CUR)$RDCUR $= SUM(RHS_COMBAL, VAR_COMNET.L * OBJ_COMNT(...,'COST'))
                                     + SUM(RHS_COMPRD, VAR_COMPRD.L * OBJ_COMPD(...,'COST'));
        PAR_COMC('2', ...) $= the same with TAX+SUB.
    """
    if "RDCUR" not in db.sym:
        return
    for j, kind in (("1", "cost"), ("2", "tax")):
        parts = []
        if all(n in db.sym for n in ("RHS_COMBAL", "L_VAR_COMNET", "OBJ_COMNT")):
            parts.append(_com_part("OBJ_COMNT", "L_VAR_COMNET", "RHS_COMBAL", kind))
        if all(n in db.sym for n in ("RHS_COMPRD", "L_VAR_COMPRD", "OBJ_COMPD")):
            parts.append(_com_part("OBJ_COMPD", "L_VAR_COMPRD", "RHS_COMPRD", kind))
        if not parts:
            continue
        if kind == "cost":
            db.put("PAR_COMC", f"""
                select '{j}' as j, r, y, c, cur, sum(value) as value
                from ({' union all '.join(parts)}) s
                group by r, y, c, cur
            """, zero="skip")
            continue
        # An EPS tax times a real quantity is EPS, and $= stores it. A real tax absorbs an EPS one.
        db.x(f"""
            create or replace temp table com_tax as
            select r, y, c, cur, sum(value) as value,
                   case when sum(value) <> 0 then 0 when sum(neps) > 0 then 1 else 0 end as is_eps
            from ({' union all '.join(parts)}) s
            group by r, y, c, cur
        """)
        db.put("PAR_COMC", f"""
            select '{j}' as j, r, y, c, cur, value from com_tax where is_eps = 0
        """, zero="skip")
        db.put("PAR_COMC", f"""
            select '{j}' as j, r, y, c, cur, 0 as value from com_tax where is_eps = 1
        """, zero="eps")
    if all(n in db.sym for n in ("BLE_OPR", "OBJ_BLNDV", "L_VAR_BLND")) and db.card("BLE_OPR"):
        # Line 103 adds the blending cost onto column '1'. Plain '='.
        db.x("""
            create or replace temp table blnd as
            select b.r, lv.y, b.c, d.cur,
                   sum(v_OBJ_BLNDV(b.r, lv.y, b.c, b.c2, d.cur) * lv.value) as value
            from BLE_OPR b
            join L_VAR_BLND lv on lv.r = b.r and lv.c = b.c and lv.c2 = b.c2
            join RDCUR d on d.r = b.r
            group by b.r, lv.y, b.c, d.cur
        """)
        db.put("PAR_COMC", """
            select '1' as j, r, y, c, cur,
                   v_PAR_COMC('1', r, y, c, cur) + value as value
            from blnd
        """)


def _com_part(cost, level, rhs, kind):
    """One commodity balance or production term. The tax column also reports an EPS product."""
    lvl = f"v_{level}(b.r, b.y, b.c, b.s)"
    if kind == "cost":
        expr = f"v_{cost}(b.r, b.y, b.c, b.s, 'COST', d.cur)"
        return f"""
            select b.r, b.y, b.c, d.cur, ({lvl}) * ({expr}) as value
            from {rhs} b
            join RDCUR d on d.r = b.r
        """
    tax = f"v_{cost}(b.r, b.y, b.c, b.s, 'TAX', d.cur)"
    sub = f"v_{cost}(b.r, b.y, b.c, b.s, 'SUB', d.cur)"
    tax_eps = f"in_{cost}(b.r, b.y, b.c, b.s, 'TAX', d.cur) and {tax} = 0"
    sub_eps = f"in_{cost}(b.r, b.y, b.c, b.s, 'SUB', d.cur) and {sub} = 0"
    num = f"(case when {tax_eps} then 0 else {tax} end + case when {sub_eps} then 0 else {sub} end)"
    ceps = f"(({tax_eps}) or ({sub_eps})) and ({num}) = 0"
    leps = f"in_{level}(b.r, b.y, b.c, b.s) and {lvl} = 0"
    return f"""
        select b.r, b.y, b.c, d.cur,
               case when {lvl} <> 0 and ({num}) <> 0 then ({lvl}) * ({num}) else 0 end as value,
               case when ({lvl} <> 0 and ({num}) = 0 and ({ceps}))
                      or ({leps} and (({num}) <> 0 or ({ceps}))) then 1 else 0 end as neps
        from {rhs} b
        join RDCUR d on d.r = b.r
    """


def _annual_flow(db):
    """Flow costs at period T. The cost column adds the trade quantity; the tax column
    replaces it. cal_caps.mod (eqobjvar.rpt 70-74) is not included; see UNTESTED.

        PAR_FLOC('1', RTP_VINTYR, C, CUR)$(OBJ_VFLO(...,'COST')$TRACKPC)
            = SUM(RTPCS_VARF, SUM(TS_ANN, OBJ_FCOST(R,T,...)+OBJ_FDELV(R,T,...)) * PAR_FLO);
        PAR_FLOC('1', ...)$RPC_STG: the storage levels (lines 56-58), _storage_flow
        PAR_FLOC('1', ...)$RP_IRE = PAR_FLOC + SUM(..., (FCOST+FDELV) * (SUM(PAR_IRE)+SUM(F_INOUTS)));
        PAR_FLOC('2', ...)$TRACKPC = SUM(..., OBJ_FTAX(R,T,...) * PAR_FLO);
        PAR_FLOC('2', ...)$RP_IRE = SUM(..., OBJ_FTAX * (SUM(PAR_IRE)+SUM(F_INOUTS)));
    """
    if not all(n in db.sym for n in ("RTP_VINTYR", "RTPCS_VARF", "OBJ_VFLO", "TS_ANN")):
        return
    inout = "0"
    if "F_INOUTS" in db.sym and db.card("F_INOUTS"):
        inout = """coalesce((select sum(fi.value) from F_INOUTS fi
                   where fi.r = v.r and fi.y = v.y and fi.y2 = v.y2 and fi.p = v.p
                     and fi.c = f.c and fi.s = f.s), 0)"""
    ire = "0"
    if all(n in db.sym for n in ("RP_IRE", "PAR_IRE", "RPC_IRE")):
        ire = f"""case when in_RP_IRE(v.r, v.p) then
                    coalesce((select sum(pi.value) from PAR_IRE pi
                              where pi.r = v.r and pi.y = v.y and pi.y2 = v.y2 and pi.p = v.p
                                and pi.c = f.c and pi.s = f.s and in_RPC_IRE(v.r, v.p, f.c, pi.ie)), 0)
                    + ({inout}) else 0 end"""
    flo = "coalesce(pf.value, 0)" if "PAR_FLO" in db.sym else "0"
    flo_join = ("left join PAR_FLO pf on pf.r = v.r and pf.y = v.y and pf.y2 = v.y2 "
                "and pf.p = v.p and pf.c = f.c and pf.s = f.s") if "PAR_FLO" in db.sym else ""
    specs = []
    if "OB_FCOS" in db.sym or "OB_FDEL" in db.sym:
        fcost = "v_OB_FCOS(v.r, v.p, f.c, ann.s2, vf.cur, v.y2)" if "OB_FCOS" in db.sym else "0"
        fdel = "v_OB_FDEL(v.r, v.p, f.c, ann.s2, vf.cur, v.y2)" if "OB_FDEL" in db.sym else "0"
        specs.append(("1", "COST", f"{fcost} + {fdel}", True))
    if "OB_FTAX" in db.sym:
        specs.append(("2", "TAX", "v_OB_FTAX(v.r, v.p, f.c, ann.s2, vf.cur, v.y2)", False))
    for j, ucn, cost, add_ire in specs:
        extra = f"({flo}) + ({ire})" if add_ire else f"case when in_RP_IRE(v.r, v.p) then ({ire}) else ({flo}) end"
        if "RP_IRE" not in db.sym:
            extra = flo
        eps = ""
        if j == "2":
            # An EPS flow tax times a real quantity is EPS, and the '=' stores it.
            eps = f""",
                   sum(case when in_OB_FTAX(v.r, v.p, f.c, ann.s2, vf.cur, v.y2)
                                 and ({cost}) = 0 and ({extra}) <> 0 then 1 else 0 end) as neps"""
            value = f"sum(case when ({cost}) = 0 or ({extra}) = 0 then 0 else ({cost}) * ({extra}) end)"
        else:
            value = f"sum(({cost}) * ({extra}))"
        db.x(f"""
            create or replace temp table flo_raw as
            select v.r, v.y, v.y2, v.p, f.c, vf.cur, {value} as value{eps}
            from RTP_VINTYR v
            join RTPCS_VARF f on f.r = v.r and f.y = v.y2 and f.p = v.p
            join TS_ANN ann on ann.s = f.s
            join OBJ_VFLO vf on vf.r = v.r and vf.p = v.p and vf.c = f.c and vf.ucn = '{ucn}'
            {flo_join}
            group by v.r, v.y, v.y2, v.p, f.c, vf.cur
        """)
        if j == "2":
            db.put("PAR_FLOC", f"""
                select '{j}' as j, r, y, y2, p, c, cur, value from flo_raw where value <> 0
            """)
            db.put("PAR_FLOC", f"""
                select '{j}' as j, r, y, y2, p, c, cur, 0 as value
                from flo_raw where value = 0 and neps > 0
            """, zero="eps")
        else:
            db.put("PAR_FLOC", f"""
                select '{j}' as j, r, y, y2, p, c, cur, value from flo_raw
            """)
    _storage_flow(db)
    # Line 45. Import prices from outside the study, column '1' only. $= adds nothing
    # where the product is zero, and a later flow statement adds to whatever this stored.
    if all(n in db.sym for n in ("OBJ_IPRIC", "RPC_IREIO", "PAR_IRE", "RPC", "RP_IRE", "RDCUR")):
        db.put("PAR_FLOC", """
            select '1' as j, v.r, v.y, v.y2, v.p, f.c, d.cur,
                   v_PAR_FLOC('1', v.r, v.y, v.y2, v.p, f.c, d.cur)
                   + sum(v_OBJ_IPRIC(v.r, v.y2, v.p, f.c, f.s, io.ie, d.cur) * pi.value) as value
            from RTP_VINTYR v
            join RTPCS_VARF f on f.r = v.r and f.y = v.y2 and f.p = v.p
            join RPC_IREIO io on io.r = v.r and io.p = v.p and io.c = f.c and io.io = 'OUT'
            join PAR_IRE pi on pi.r = v.r and pi.y = v.y and pi.y2 = v.y2 and pi.p = v.p
                            and pi.c = f.c and pi.s = f.s and pi.ie = io.ie
            join RDCUR d on d.r = v.r
            where in_RPC(v.r, v.p, f.c) and in_RP_IRE(v.r, v.p)
            group by v.r, v.y, v.y2, v.p, f.c, d.cur
        """, zero="skip")


def _storage_flow(db, lint=None):
    """The flow costs of a storage process, column '1' (eqobjvar.rpt lines 56-58). The statement follows the one of
    TRACKPC and replaces it ('='), for every key of its domain: the cost is that of the storage levels, the input
    priced by OBJ_FCOST and the output, times STG_EFF, by OBJ_FDELV.

        PAR_FLOC('1',RTP_VINTYR(R,V,T,P),C,CUR)$(OBJ_VFLO(R,P,C,CUR,'COST')$RPC_STG(R,P,C)) =
           SUM(RPCS_VAR(R,P,C,S),
               SUM(TS_ANN(S,TS),%5(%TPULSE% (VAR_SIN.L(R,V,T,P,C,S)*OBJ_FCOST(R,%4,P,C,TS,CUR)+
                                             VAR_SOUT.L(R,V,T,P,C,S)*STG_EFF(R,V,P)*OBJ_FDELV(R,%4,P,C,TS,CUR)))));

    `lint`: None for the call at period T (cost_ann.rpt 167: %4 is T, no pulse); the name of OBJ_LINT for the call
    with the pulse of VARCOST LIN (rpt_obj.rpt 128: the cost at each Y_EOH weighted by OBJ_LINT(R,T,Y_EOH,CUR)).
    """
    need = ("RPC_STG", "OBJ_VFLO", "RTP_VINTYR", "RPCS_VAR", "TS_ANN")
    if not all(n in db.sym for n in need) or not db.card("RPC_STG"):
        return
    fcos = "OB_FCOS" in db.sym
    fdel = "OB_FDEL" in db.sym
    if not (fcos or fdel):
        return
    sin = "v_L_VAR_SIN(v.r, v.y, v.y2, v.p, g.c, rs.s)" if "L_VAR_SIN" in db.sym else "0"
    sout = "v_L_VAR_SOUT(v.r, v.y, v.y2, v.p, g.c, rs.s)" if "L_VAR_SOUT" in db.sym else "0"
    eff = "v_STG_EFF(v.r, v.y, v.p)" if "STG_EFF" in db.sym else "1"
    yr = "v.y2" if lint is None else "l.y2"
    fc = f"v_OB_FCOS(v.r, v.p, g.c, ann.s2, vf.cur, {yr})" if fcos else "0"
    fd = f"v_OB_FDEL(v.r, v.p, g.c, ann.s2, vf.cur, {yr})" if fdel else "0"
    term = f"({sin}) * ({fc}) + ({sout}) * ({eff}) * ({fd})"
    if lint is None:
        value, pulse = f"sum({term})", ""
    else:
        value = f"sum(l.value * ({term}))"
        pulse = f"join {lint} l on l.r = v.r and l.y = v.y2 and l.cur = vf.cur"
    # every key of the domain is assigned, so a key whose cost is 0 loses the record TRACKPC's statement gave it
    db.put("PAR_FLOC", f"""
        select '1' as j, k.r, k.y, k.y2, k.p, k.c, k.cur, coalesce(c.value, 0) as value
        from (select distinct v.r, v.y, v.y2, v.p, g.c, vf.cur
              from RTP_VINTYR v
              join RPC_STG g on g.r = v.r and g.p = v.p
              join OBJ_VFLO vf on vf.r = v.r and vf.p = v.p and vf.c = g.c and vf.ucn = 'COST') k
        left join (select v.r, v.y, v.y2, v.p, g.c, vf.cur, {value} as value
                   from RTP_VINTYR v
                   join RPC_STG g on g.r = v.r and g.p = v.p
                   join OBJ_VFLO vf on vf.r = v.r and vf.p = v.p and vf.c = g.c and vf.ucn = 'COST'
                   join RPCS_VAR rs on rs.r = v.r and rs.p = v.p and rs.c = g.c
                   join TS_ANN ann on ann.s = rs.s
                   {pulse}
                   group by v.r, v.y, v.y2, v.p, g.c, vf.cur) c
          on c.r = k.r and c.y = k.y and c.y2 = k.y2 and c.p = k.p and c.c = k.c and c.cur = k.cur
    """)


def cost_column(db):
    """The cost column J('1') of the rpt_obj.rpt line 128 call, taken when UNCD1('1') = MY_F+ACL is not 0
    (RPT_OPT('OBJ','1') set, here). The pulse is that of VARCOST LIN: each cost is read at the years Y_EOH of
    the period and weighted by OBJ_LINT(R,T,Y_EOH,CUR), so the column is discounted to the base year.
    rpt_obj.rpt lines 129-135 sum it, with the tax column, into CST_PVP / CST_PVC.

        PAR_ACTC('1',RTP_VINTYR,'ACT',CUR)$(RDCUR$OBJ_ACOST(R,T,P,CUR)) =
            pulse(OBJ_ACOST(R,Y_EOH,P,CUR)) * SUM(PRC_TS, VAR_ACT.L * POWER(RS_STGAV,1$RP_STG));
        PAR_COMC('1',R,T,C,CUR)$RDCUR $= SUM(RHS_COMBAL, VAR_COMNET.L*pulse(OBJ_COMNT(..'COST'..)))
                                       + SUM(RHS_COMPRD, VAR_COMPRD.L*pulse(OBJ_COMPD(..'COST'..)));
        PAR_FLOC('1',RTP_VINTYR,C,CUR)$(RDCUR$RPC$RP_IRE) $= SUM(RTPCS_VARF*RPC_IREIO OUT, pulse(OBJ_IPRIC)*PAR_IRE);
        PAR_FLOC('1',...)$(OBJ_VFLO COST$TRACKPC) = SUM(RTPCS_VARF, SUM(TS_ANN, pulse(FCOST+FDELV))*PAR_FLO);
        PAR_FLOC('1',...)$(OBJ_VFLO COST$RP_IRE) = PAR_FLOC + SUM(.., pulse(FCOST+FDELV)*(SUM(PAR_IRE)+SUM(F_INOUTS)));
        PAR_COMC('1',R,T,BLE,CUR)$RDCUR = PAR_COMC + SUM(BLE_OPR, pulse(OBJ_BLNDV)*VAR_BLND.L);
        PAR_FLOC('1',...)$(OBJ_VFLO COST$RPC_STG) = SUM(RPCS_VAR, SUM(TS_ANN, pulse(VAR_SIN.L*FCOST+VAR_SOUT.L*STG_EFF*FDELV)));
    The storage statement is _storage_flow. Not taken, as in the tax column and the annual report: cal_caps.mod
    (lines 70-74)."""
    if "OBJ_LINT" not in db.sym or "RDCUR" not in db.sym:
        return
    lint = "OBJ_LINT"
    # activity costs
    if all(n in db.sym for n in ("RTP_VINTYR", "PRC_TS", "L_VAR_ACT", "OB_ACT")):
        staged = "in_RP_STG(v.r, v.p)" if "RP_STG" in db.sym else "false"
        shape = f"case when {staged} then v_RS_STGAV(v.r, ts.s) else 1 end" if "RS_STGAV" in db.sym else "1"
        db.x(f"""create or replace temp table actc_w as
                 select l.r, l.y, l.cur, a.p, sum(l.value * a.value) as wgt
                 from {lint} l join OB_ACT a on a.r = l.r and a.cur = l.cur and a.y = l.y2
                 where in_RDCUR(l.r, l.cur) and exists (select 1 from OB_ACT b where b.r = l.r and b.p = a.p and b.cur = l.cur and b.y = l.y)
                 group by l.r, l.y, l.cur, a.p""")
        db.put("PAR_ACTC", f"""
            select '1' as j, v.r, v.y, v.y2, v.p, 'ACT' as c, w.cur,
                   w.wgt * sum(v_L_VAR_ACT(v.r, v.y, v.y2, v.p, ts.s) * ({shape})) as value
            from RTP_VINTYR v
            join actc_w w on w.r = v.r and w.y = v.y2 and w.p = v.p
            join PRC_TS ts on ts.r = v.r and ts.p = v.p
            group by v.r, v.y, v.y2, v.p, w.cur, w.wgt
        """)
    # commodity costs
    parts = []
    for cost, level, rhs in (("OBJ_COMNT", "L_VAR_COMNET", "RHS_COMBAL"), ("OBJ_COMPD", "L_VAR_COMPRD", "RHS_COMPRD")):
        if all(n in db.sym for n in (cost, level, rhs)):
            parts.append(f"""
                select b.r, b.y, b.c, l.cur, v_{level}(b.r, b.y, b.c, b.s) * l.value
                       * v_{cost}(b.r, l.y2, b.c, b.s, 'COST', l.cur) as value
                from {rhs} b join {lint} l on l.r = b.r and l.y = b.y
                where in_RDCUR(b.r, l.cur)""")
    if parts:
        db.put("PAR_COMC", f"""
            select '1' as j, r, y, c, cur, sum(value) as value
            from ({' union all '.join(parts)}) s group by r, y, c, cur
        """, zero="skip")
    if all(n in db.sym for n in ("BLE_OPR", "OBJ_BLNDV", "L_VAR_BLND")) and db.card("BLE_OPR"):
        db.x(f"""create or replace temp table blnd as
                 select b.r, lv.y, b.c, l.cur, sum(l.value * v_OBJ_BLNDV(b.r, l.y2, b.c, b.c2, l.cur) * lv.value) as value
                 from BLE_OPR b
                 join L_VAR_BLND lv on lv.r = b.r and lv.c = b.c and lv.c2 = b.c2
                 join {lint} l on l.r = b.r and l.y = lv.y
                 where in_RDCUR(b.r, l.cur)
                 group by b.r, lv.y, b.c, l.cur""")
        db.put("PAR_COMC", "select '1' as j, r, y, c, cur, v_PAR_COMC('1', r, y, c, cur) + value as value from blnd")
    # import prices from outside the study area ($=)
    if all(n in db.sym for n in ("OBJ_IPRIC", "RPC_IREIO", "PAR_IRE", "RPC", "RP_IRE", "RTP_VINTYR", "RTPCS_VARF")):
        db.put("PAR_FLOC", f"""
            select '1' as j, v.r, v.y, v.y2, v.p, f.c, l.cur,
                   sum(l.value * v_OBJ_IPRIC(v.r, l.y2, v.p, f.c, f.s, io.ie, l.cur) * pi.value) as value
            from RTP_VINTYR v
            join RTPCS_VARF f on f.r = v.r and f.y = v.y2 and f.p = v.p
            join RPC_IREIO io on io.r = v.r and io.p = v.p and io.c = f.c and io.io = 'OUT'
            join PAR_IRE pi on pi.r = v.r and pi.y = v.y and pi.y2 = v.y2 and pi.p = v.p
                            and pi.c = f.c and pi.s = f.s and pi.ie = io.ie
            join {lint} l on l.r = v.r and l.y = v.y2
            where in_RPC(v.r, v.p, f.c) and in_RP_IRE(v.r, v.p) and in_RDCUR(v.r, l.cur)
            group by v.r, v.y, v.y2, v.p, f.c, l.cur
        """, zero="skip")
    # flow costs and delivery costs
    have = [n for n in ("OB_FCOS", "OB_FDEL") if n in db.sym and db.card(n)]
    if have and all(n in db.sym for n in ("RTP_VINTYR", "RTPCS_VARF", "OBJ_VFLO", "TS_ANN")):
        cost = " + ".join(f"v_{n}(v.r, v.p, f.c, ann.s2, l.cur, l.y2)" for n in have)
        db.x(f"""create or replace temp table floc_w as
                 select v.r, v.y, v.y2, v.p, f.c, f.s, l.cur, sum(l.value * ({cost})) as wgt
                 from RTP_VINTYR v
                 join RTPCS_VARF f on f.r = v.r and f.y = v.y2 and f.p = v.p
                 join TS_ANN ann on ann.s = f.s
                 join {lint} l on l.r = v.r and l.y = v.y2
                 where in_OBJ_VFLO(v.r, v.p, f.c, l.cur, 'COST')
                 group by v.r, v.y, v.y2, v.p, f.c, f.s, l.cur""")
        if "PAR_FLO" in db.sym:
            db.put("PAR_FLOC", """
                select '1' as j, w.r, w.y, w.y2, w.p, w.c, w.cur, sum(w.wgt * pf.value) as value
                from floc_w w
                join PAR_FLO pf on pf.r = w.r and pf.y = w.y and pf.y2 = w.y2 and pf.p = w.p
                                and pf.c = w.c and pf.s = w.s
                where exists (select 1 from PAR_FLO t where t.r = w.r and t.p = w.p and t.c = w.c)
                group by w.r, w.y, w.y2, w.p, w.c, w.cur
            """)
        _storage_flow(db, lint)
        if all(n in db.sym for n in ("RP_IRE", "PAR_IRE", "RPC_IRE")):
            inout = ""
            if "F_INOUTS" in db.sym and db.card("F_INOUTS"):
                inout = """union all select fi.r, fi.y, fi.y2, fi.p, fi.c, fi.s, fi.value from F_INOUTS fi"""
            db.put("PAR_FLOC", f"""
                select '1' as j, w.r, w.y, w.y2, w.p, w.c, w.cur,
                       v_PAR_FLOC('1', w.r, w.y, w.y2, w.p, w.c, w.cur) + sum(w.wgt * q.value) as value
                from floc_w w
                join (select pi.r, pi.y, pi.y2, pi.p, pi.c, pi.s, pi.value from PAR_IRE pi
                      where in_RPC_IRE(pi.r, pi.p, pi.c, pi.ie) {inout}) q
                  on q.r = w.r and q.y = w.y and q.y2 = w.y2 and q.p = w.p and q.c = w.c and q.s = w.s
                where in_RP_IRE(w.r, w.p)
                group by w.r, w.y, w.y2, w.p, w.c, w.cur
            """)


def variable_costs(db):
    """PAR_COMC, PAR_FLOC and PAR_ACTC for the tax column. Returns the names declared."""
    _commodity_tax(db)
    if getattr(db, "stages", None):                # a run with STAGES: the uncertain commodity tax (lines 39-40)
        from . import stochastic
        stochastic.com_tax(db, pulse=True)
    _flow_tax(db)
    _startup(db)
    return ["PAR_COMC", "PAR_FLOC", "PAR_ACTC"]


def _commodity_tax(db):
    """PAR_COMC('2',R,T,C,CUR) $= comnet and comprd tax plus subsidy."""
    db.declare("PAR_COMC", "par", ["J", "R", "T", "C", "CUR"])
    db.clear("PAR_COMC")
    if "OBJ_LINT" not in db.sym:
        return
    parts = []
    for cost, level, rhs in (("OBJ_COMNT", "L_VAR_COMNET", "RHS_COMBAL"), ("OBJ_COMPD", "L_VAR_COMPRD", "RHS_COMPRD")):
        if all(n in db.sym for n in (rhs, level, cost)):
            parts.append(_com_tax_part(cost, level, rhs))
    if not parts:
        return
    # $= : a zero sum leaves the (empty) target. An EPS tax times a real quantity is EPS, and $= stores it.
    db.x(f"""
        create or replace temp table com_tax as
        select r, y, c, cur, sum(value) as value,
               case when sum(value) <> 0 then 0 when sum(neps) > 0 then 1 else 0 end as is_eps
        from ({' union all '.join(parts)}) s
        group by r, y, c, cur
    """)
    db.put("PAR_COMC", "select '2' as j, r, y, c, cur, value from com_tax where is_eps = 0", zero="skip")
    db.put("PAR_COMC", "select '2' as j, r, y, c, cur, 0 as value from com_tax where is_eps = 1", zero="eps")


def _com_tax_part(cost, level, rhs):
    """One commodity balance or production term of the tax column, at the years Y_EOH of the period (OBJ_LINT).
    As in the annual call (_com_part): a tax or subsidy record of value 0 is EPS, and so is a level of 0."""
    lvl = f"v_{level}(b.r, b.y, b.c, b.s)"
    tax = f"v_{cost}(b.r, lint.y2, b.c, b.s, 'TAX', lint.cur)"
    sub = f"v_{cost}(b.r, lint.y2, b.c, b.s, 'SUB', lint.cur)"
    tax_eps = f"in_{cost}(b.r, lint.y2, b.c, b.s, 'TAX', lint.cur) and {tax} = 0"
    sub_eps = f"in_{cost}(b.r, lint.y2, b.c, b.s, 'SUB', lint.cur) and {sub} = 0"
    num = f"({tax} + {sub})"
    ceps = f"(({tax_eps}) or ({sub_eps})) and ({num}) = 0"
    leps = f"in_{level}(b.r, b.y, b.c, b.s) and {lvl} = 0"
    return f"""
        select b.r, b.y, b.c, lint.cur, ({lvl}) * lint.value * ({num}) as value,
               case when lint.value <> 0 and (({lvl} <> 0 and ({ceps})) or ({leps} and (({num}) <> 0 or ({ceps}))))
                    then 1 else 0 end as neps
        from {rhs} b
        join OBJ_LINT lint on lint.r = b.r and lint.y = b.y
        where in_RDCUR(b.r, lint.cur)
    """


def _flow_tax(db):
    """PAR_FLOC('2') from flow tax. An IRE process is replaced, not added to.

    The two statements (eqobjvar.rpt 80-90):

        PAR_FLOC('2', RTP_VINTYR, C, CUR)$(OBJ_VFLO(...,'TAX')$TRACKPC)
            = SUM(RTPCS_VARF, SUM(TS_ANN, pulse(OBJ_FTAX)) * PAR_FLO);
        PAR_FLOC('2', RTP_VINTYR, C, CUR)$(OBJ_VFLO(...,'TAX')$RP_IRE)
            = SUM(RTPCS_VARF, SUM(TS_ANN, pulse(OBJ_FTAX)) * SUM(RPC_IRE, PAR_IRE));

    TRACKPC is the (R,P,C) projection of PAR_FLO. cal_caps.mod (eqobjvar.rpt 93-97)
    adds the capacity-tied flows; that sum is not included. See UNTESTED.
    """
    db.declare("PAR_FLOC", "par", ["J", "R", "LL", "T", "P", "C", "CUR"])
    db.clear("PAR_FLOC")
    if not all(n in db.sym for n in ("RTP_VINTYR", "RTPCS_VARF", "OBJ_LINT", "OBJ_VFLO", "TS_ANN", "OB_FTAX")):
        return
    # An EPS flow tax (a record of value 0) times a real quantity is EPS, and the '=' stores it.
    weight = """
        select v.r, v.y as vint, v.y2 as per, v.p, f.c, f.s, lint.cur,
               sum(lint.value * v_OB_FTAX(v.r, v.p, f.c, ann.s2, lint.cur, lint.y2)) as wgt,
               max(case when lint.value <> 0 and in_OB_FTAX(v.r, v.p, f.c, ann.s2, lint.cur, lint.y2)
                             and v_OB_FTAX(v.r, v.p, f.c, ann.s2, lint.cur, lint.y2) = 0 then 1 else 0 end) as eps
        from RTP_VINTYR v
        join RTPCS_VARF f on f.r = v.r and f.y = v.y2 and f.p = v.p
        join TS_ANN ann on ann.s = f.s
        join OBJ_LINT lint on lint.r = v.r and lint.y = v.y2
        where in_OBJ_VFLO(v.r, v.p, f.c, lint.cur, 'TAX')
        group by v.r, v.y, v.y2, v.p, f.c, f.s, lint.cur
    """
    db.x(f"create or replace temp table flo_wgt as {weight}")
    if "PAR_FLO" in db.sym:
        db.put("PAR_FLOC", """
            select '2' as j, w.r, w.vint as y, w.per as y2, w.p, w.c, w.cur,
                   sum(w.wgt * pf.value) as value
            from flo_wgt w
            join PAR_FLO pf on pf.r = w.r and pf.y = w.vint and pf.y2 = w.per
                            and pf.p = w.p and pf.c = w.c and pf.s = w.s
            group by w.r, w.vint, w.per, w.p, w.c, w.cur
            having sum(w.wgt * pf.value) <> 0
                or max(case when w.eps = 1 and w.wgt = 0 and pf.value <> 0 then 1 else 0 end) = 1
        """, zero="eps")
    if "RP_IRE" in db.sym and "PAR_IRE" in db.sym and "RPC_IRE" in db.sym:
        # Plain '=' replaces the PAR_FLO value on import/export processes.
        db.put("PAR_FLOC", """
            select '2' as j, w.r, w.vint as y, w.per as y2, w.p, w.c, w.cur,
                   sum(w.wgt * pi.value) as value
            from flo_wgt w
            join RP_IRE ip on ip.r = w.r and ip.p = w.p
            join PAR_IRE pi on pi.r = w.r and pi.y = w.vint and pi.y2 = w.per
                            and pi.p = w.p and pi.c = w.c and pi.s = w.s
            where in_RPC_IRE(w.r, w.p, w.c, pi.ie)
            group by w.r, w.vint, w.per, w.p, w.c, w.cur
            having sum(w.wgt * pi.value) <> 0
                or max(case when w.eps = 1 and w.wgt = 0 and pi.value <> 0 then 1 else 0 end) = 1
        """, zero="eps")


def _startup(db):
    """PAR_ACTC('2') start-up cost. The UPT and UPR sums are empty when those sets are.

        PAR_ACTC('2', RTP_VINTYR, 'ACT', CUR)$RPC_CUR
            = SUM(RP_UPS(...,'UP'), pulse(ACT_CSTUP) * SUM(TS_GROUP, RS_STGPRD * VAR_UPS.L))
    """
    db.declare("PAR_ACTC", "par", ["J", "R", "LL", "T", "P", "C", "CUR"])
    db.clear("PAR_ACTC")
    need = ("RTP_VINTYR", "RP_UPS", "ACT_CSTUP", "TS_GROUP", "RS_STGPRD", "L_VAR_UPS", "OBJ_LINT", "RPC_CUR")
    if not all(n in db.sym for n in need) or db.card("RP_UPS") == 0:
        return
    db.put("PAR_ACTC", """
        select '2' as j, v.r, v.y, v.y2, v.p, 'ACT' as c, w.cur,
               sum(v_ACT_CSTUP(v.r, v.y, v.p, ups.tsl, w.cur) * w.wgt
                   * v_RS_STGPRD(v.r, g.s) * v_L_VAR_UPS(v.r, v.y, v.y2, v.p, g.s, ups.l)) as value
        from RTP_VINTYR v
        join RP_UPS ups on ups.r = v.r and ups.p = v.p and ups.l = 'UP'
        join TS_GROUP g on g.r = v.r and g.tsl = ups.tsl
        join (
            select r, y, cur, sum(value) as wgt from OBJ_LINT group by r, y, cur
        ) w on w.r = v.r and w.y = v.y2
        where in_RPC_CUR(v.r, v.p, 'ACT', w.cur) and in_RDCUR(v.r, w.cur)
        group by v.r, v.y, v.y2, v.p, w.cur
    """)
