# SPDX-License-Identifier: GPL-3.0-or-later
"""rpt_ext.mlf: the report of TIMES-MACRO in its linearised form (MLF).

In an MLF run TIMES skips the standard report (rptmain.mod 20: `$IFI %MACRO% == YES $GOTO OTHER_REP`, rptlite.rpt
stops after its declarations with SOLVEDA 1) and writes its own in rpt_ext.mlf, in this order:
  - the flows and trade of the solution, the objective report (rpt_obj.rpt with TIMESED NO and its fifth argument 0:
    no rpt_objc.rpt, so no COEF_OBJINV) and the annual costs (cost_ann.rpt), within the Negishi iterations (the
    iterations themselves are made after the solve, times_eq/src/negishi.jl);
  - the shadow prices undiscounted by the marginals of EQ_ENSCST (VDA_DISC), the trade prices and costs with them;
  - rptmisc.rpt with COEF_PVT(MR,T) = -VDA_DISC: every shadow price of the maximisation is undiscounted that way
    (the sign makes them those of a cost minimisation);
  - the objective by cost type from the annual costs (REG_WOBJ, REG_OBJ, OBJz), and TM_RESULT.
"""
from __future__ import annotations

from . import cost_ann, rptobj, solflo


def on(db):
    return "MLF" in db.sym and db.card("MLF") > 0


# the tables of an MLF run the report reads beyond TIMES's declarations (declared by initmty.tm, prep_ext.mlf and the
# preprocessor), with their domains
TABLES = {"MLF": ("set", ["UC_NAME"]), "MR": ("set", ["R"]), "PP": ("set", ["T"]), "TM_GDPGOAL": ("par", ["R", "T"]),
          "TM_HDF": ("par", ["R", "T"]), "TM_Y0": ("par", ["R"]), "TM_GDP0": ("par", ["R"]), "TM_SCALE_CST": ("par", [])}


def load(db, have):
    """The tables of TABLES from model.db3 (attached as mdl), when the run is MLF."""
    if "MLF" not in have:
        return
    for name, (kind, dom) in TABLES.items():
        if name not in have:
            continue
        if kind == "par" and not dom:
            db.declare(name, "par", [])
            val = db.con.execute(f'select value from mdl."{name}"').fetchone()
            db.s[name] = float(val[0]) if val and val[0] is not None else 0.0
            continue
        db.declare(name, kind, dom)
        db.clear(name)
        db.x(f'insert into "{name}" select * from mdl."{name}"')


def run(db, misc):
    """rpt_ext.mlf after the solve. misc: rptmisc's blocks of rptmisc.rpt (a function of db). Returns the names
    written."""
    s = db.s
    names = solflo.run(db)
    # rpt_ext.mlf 23: $ SET TIMESED NO  BATINCLUDE rpt_obj.rpt '' "" '' '%SYSPREFIX%' 0
    for v in ("L_VAR_OBJ", "L_VAR_OBJELS"):
        if v not in db.sym:
            db.declare(v, "par", ["R", "OBV", "CUR"] if v == "L_VAR_OBJ" else ["R", "BD", "CUR"])
    obj_names = rptobj.run(db, coef=False)
    cost_names = cost_ann.run(db)
    cst = s.get("TM_SCALE_CST", 0.0)
    # --- Calculation of undiscounted shadow prices in MACRO
    #     VDA_DISC(MR,T) = ABS(-EQ_ENSCST.M(MR,T) * TM_SCALE_CST);
    #     VDA_DISC(MR,T)$(NOT RT_PP(MR,T)) = COEF_PVT(MR,T);          (RT_PP: every period of a run that is not myopic)
    #     LOOP(MIYR_1(TT(T-1)),VDA_DISC(R,TT)$(VDA_DISC(R,TT) LE 0) = COEF_PVT(R,TT)/COEF_PVT(R,T)*VDA_DISC(R,T));
    db.declare("VDA_DISC", "par", ["R", "ALLYEAR"])
    db.clear("VDA_DISC")
    db.put("VDA_DISC", f"""select m.r, t.y, abs(-v_M_EQ_ENSCST(m.r, t.y) * {cst!r}) as value
                           from MR m, MILESTONYR t""")
    per = [y for (y,) in db.q("select y from MILESTONYR order by cast(y as integer)")]
    if len(per) > 1:
        tb, t2 = per[0], per[1]
        db.put("VDA_DISC", f"""select g.r, '{tb}' as y,
                                      v_COEF_PVT(g.r, '{tb}') / v_COEF_PVT(g.r, '{t2}') * v_VDA_DISC(g.r, '{t2}') as value
                               from REG g where v_VDA_DISC(g.r, '{tb}') <= 0""")
    # --- VAR_OBJ.L(R,OBV(OBVANN),CUR) = 0;   (no records: VAR_OBJ is not in TIMES_MACRO)
    # --- Trade prices and implied costs/revenues
    #     PAR_IPRIC(MR(R),PP(T),P,C,TS,IE)$PAR_IPRIC(R,T,P,C,TS,IE) = -PAR_IPRIC(R,T,P,C,TS,IE)*COEF_PVT(R,T)/VDA_DISC(R,T);
    if "PAR_IPRIC" in db.sym:
        db.x("""update "PAR_IPRIC" set value = -value * v_COEF_PVT(r, y) / v_VDA_DISC(r, y)
                where in_MR(r) and in_PP(y) and value <> 0""")
    #     CST_IREC(RTP_VINTYR(MR(R),V,PP(T),P),C)$(RPC(R,P,C)$RP_IRE(R,P)) $=
    #        SUM((RTPCS_VARF(R,T,P,C,S),RPC_IREIO(R,P,C,IE,'IN')),PAR_IPRIC(R,T,P,C,S,IE)*PAR_IRE(R,V,T,P,C,S,IE));
    #     REG_ACOST(MR(R),PP(T),'IRE') = SUM((VNT(V,T),P,C)$CST_IREC(R,V,T,P,C),CST_IREC(R,V,T,P,C));
    if "CST_IREC" in db.sym and "PAR_IRE" in db.sym:
        db.put("CST_IREC", """
            select v.r, v.y, v.y2, v.p, f.c,
                   sum(i.value * x.value) as value
            from RTP_VINTYR v
            join RTPCS_VARF f on f.r = v.r and f.y = v.y2 and f.p = v.p
            join RPC_IREIO o on o.r = v.r and o.p = v.p and o.c = f.c and o.io = 'IN'
            join PAR_IPRIC i on i.r = v.r and i.y = v.y2 and i.p = v.p and i.c = f.c and i.s = f.s and i.ie = o.ie
            join PAR_IRE x on x.r = v.r and x.y = v.y and x.y2 = v.y2 and x.p = v.p and x.c = f.c and x.s = f.s and x.ie = o.ie
            where in_MR(v.r) and in_PP(v.y2) and in_RPC(v.r, v.p, f.c) and in_RP_IRE(v.r, v.p)
            group by v.r, v.y, v.y2, v.p, f.c""", zero="skip")
        db.put("REG_ACOST", """
            select m.r, p.y, 'IRE' as u,
                   coalesce((select sum(c.value) from CST_IREC c where c.r = m.r and c.y2 = p.y and in_VNT(c.y, c.y2)), 0) as value
            from MR m, PP p""")
    # --- Miscellaneous reportings
    #     TM_UDF(R,T)=COEF_PVT(R,T);  COEF_PVT(RT_PP(MR,T)) = -VDA_DISC(MR,T);
    db.declare("TM_UDF", "par", ["R", "T"])
    db.clear("TM_UDF")
    db.put("TM_UDF", "select r, y, value from COEF_PVT")
    db.x('update "COEF_PVT" set value = -v_VDA_DISC(r, y) where in_MR(r) and in_MILESTONYR(y)')
    misc_names = misc(db)
    # --- PAR_NCAPM(RTP(R,T,P))$(VAR_NCAP.M(RTP)*COEF_OBJINV(RTP)) = VAR_NCAP.M(RTP)*TM_UDF(R,T)/COEF_PVT(R,T)/COEF_OBJINV(RTP);
    #     (COEF_OBJINV is empty: rpt_obj.rpt was called without rpt_objc.rpt)
    # --- Discounted objective values by cost type
    #     REG_WOBJ(R,'INV',CUR) = SUM(T, OBJ_PVT(R,T,CUR)*REG_ACOST(R,T,'INV'));  ... INVX, FIX, FIXX, VAR, VARX, ELS
    #     REG_IREC(R) = SUM(T,TM_UDF(R,T)*REG_ACOST(R,T,'IRE'));
    #     REG_OBJ(R) = SUM((ITEM,RDCUR(R,CUR))$REG_WOBJ(R,ITEM,CUR), REG_WOBJ(R,ITEM,CUR));  OBJz.L = SUM(R,REG_OBJ(R));
    for item in ("INV", "INVX", "FIX", "FIXX", "VAR", "VARX", "ELS"):
        db.zap("REG_WOBJ", f"u = '{item}'")
        db.put("REG_WOBJ", f"""
            select d.r, '{item}' as u, d.cur,
                   coalesce((select sum(o.value * v_REG_ACOST(o.r, o.y, '{item}')) from OBJ_PVT o
                             where o.r = d.r and o.cur = d.cur and in_MILESTONYR(o.y)), 0) as value
            from RDCUR d""")
    for name, dom in (("REG_IREC", ["R"]), ("REG_OBJ", ["R"])):
        db.declare(name, "par", dom)
        db.clear(name)
    db.put("REG_IREC", """select g.r, coalesce((select sum(u.value * v_REG_ACOST(u.r, u.y, 'IRE')) from TM_UDF u
                                                  where u.r = g.r), 0) as value from REG g""")
    db.put("REG_OBJ", """select w.r, sum(w.value) as value from REG_WOBJ w
                         where in_RDCUR(w.r, w.cur) and w.value <> 0 group by w.r""")
    db.s["L_OBJZ"] = db.q1("select coalesce(sum(value), 0) from REG_OBJ") or 0.0
    # --- Report parameters for TIMES-MACRO
    #     PAR_Y(MR(R),T(TB)) = TM_Y0(R);  PAR_Y(MR(R),PP(T)) = VAR_C.L(R,T) + VAR_INV.L(R,T) + VAR_EC.L(R,T) + VAR_NTX.L(R,T);
    #     TM_GDP(MR(R),T(TB)) = TM_GDP0(R); TM_GDP(MR(R),PP(T)) = VAR_C.L(R,T) + VAR_INV.L(R,T) + VAR_NTX.L(R,T);
    L = lambda v: f"coalesce((select x.value from L_{v} x where x.r = m.r and x.y = t.y), 0)" if f"L_{v}" in db.sym else "0"
    for name in ("PAR_Y", "TM_GDP"):
        db.declare(name, "par", ["R", "T"])
    db.put("PAR_Y", f"select m.r, '{per[0]}' as y, v_TM_Y0(m.r) as value from MR m")
    db.put("PAR_Y", f"""select m.r, t.y, {L('VAR_C')} + {L('VAR_INV')} + {L('VAR_EC')} + {L('VAR_NTX')} as value
                        from MR m, PP t""")
    db.put("TM_GDP", f"select m.r, '{per[0]}' as y, v_TM_GDP0(m.r) as value from MR m")
    db.put("TM_GDP", f"""select m.r, t.y, {L('VAR_C')} + {L('VAR_INV')} + {L('VAR_NTX')} as value from MR m, PP t""")
    #     TM_RESULT('TM_GDP-REF',MR,T) = TM_GDPGOAL(MR,T);  TM_RESULT('TM_GDP-ACT',MR,T) = TM_GDP(MR,T);
    #     TM_RESULT('TM_PRD-Y',MR,T) = PAR_Y(MR,T);  TM_RESULT('TM_CON-C',MR,T) = VAR_C.L(MR,T);
    #     TM_RESULT('TM_CAP-K',MR,T) = VAR_K.L(MR,T);  TM_RESULT('TM_INV-I',MR,T) = VAR_INV.L(MR,T);
    #     TM_RESULT('TM_ESCOST',MR,T) = VAR_EC.L(MR,T)*TM_HDF(MR,T);
    #     TM_RESULT('TM_GDPLOS',MR,T) = 100*(TM_GDPGOAL(MR,T)-TM_GDP(MR,T))/TM_GDPGOAL(MR,T);
    db.declare("TM_RESULT", "par", ["ITEM", "R", "T"])
    db.clear("TM_RESULT")
    for item, expr in (("TM_GDP-REF", "v_TM_GDPGOAL(m.r, t.y)"), ("TM_GDP-ACT", "v_TM_GDP(m.r, t.y)"),
                       ("TM_PRD-Y", "v_PAR_Y(m.r, t.y)"), ("TM_CON-C", L("VAR_C")), ("TM_CAP-K", L("VAR_K")),
                       ("TM_INV-I", L("VAR_INV")), ("TM_ESCOST", f"{L('VAR_EC')} * v_TM_HDF(m.r, t.y)"),
                       ("TM_GDPLOS", "100 * (v_TM_GDPGOAL(m.r, t.y) - v_TM_GDP(m.r, t.y)) / v_TM_GDPGOAL(m.r, t.y)")):
        db.put("TM_RESULT", f"select '{item}' as u, m.r, t.y, {expr} as value from MR m, MILESTONYR t")
    return names + obj_names + cost_names + misc_names + ["VDA_DISC", "REG_IREC", "REG_OBJ", "PAR_Y", "TM_GDP", "TM_RESULT"]
