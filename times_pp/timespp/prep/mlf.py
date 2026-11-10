# SPDX-License-Identifier: GPL-3.0-or-later
"""The linearised TIMES-MACRO, MLF ($SET MACRO MLF with $SET TIMESED <reference>): the preprocessing.

    prep_ext(db, interp)   prep_ext.mlf (preppm.mod, main_ext.mod prep_ext: MLF comes before DSC and VDA in EXTEND)
    ppm_ext(db)            ppm_ext.mlf (maindrv.mod 58, main_ext.mod ppm_ext: before ppm_ext.dsc and ppm_ext.vda)

The declarations and defaults are those of initmty.tm and initmty.mlf (load.py reads them). The reference run's base
prices COM_BPRICE and annual cost shares SOL_ACFR come from readbprice.mod (elastic.py). These parts are shared with
the other forms of TIMES-MACRO (MACRO YES, MSA/CSA): the calibration inputs of ppm_ext.mlf 43-95 follow initmty.tm.
"""
from __future__ import annotations
import math
from ..engine import DB
from ..controls import given


def on(db: DB):
    """initmty.mod 464: $IFI '%MACRO%'==MLF $SETGLOBAL EXTEND '%EXTEND% MLF'"""
    return given(db.env, "MACRO").upper() == "MLF"


def _uo(col):
    """the GAMS order of a label column (the order of the universe)"""
    return f"(select u_.ord from __uel u_ where u_.label = {col})"


def _assign_ordered(db: DB, name, select):
    """A one-column set = the labels of `select`, in the order of the labels (GAMS's order of the universe): the export
    keeps a one-column set in its table order, and a SELECT DISTINCT has none."""
    col = db.cols(name)[0]
    rows = db.q(f"select distinct x_ from (select {col} as x_ from ({select}) s_) order by {_uo('x_')}")
    db.clear(name)
    db.insert_rows(f'"{name}"', [tuple(r) for r in rows])


def _periods(db: DB):
    """The milestones in order: [(year, LAGT)]."""
    return [(y, float(v or 0)) for y, v in db.q("select y, v_LAGT(y) from MILESTONYR order by yv(y)")]


def init(db: DB):
    """rpt_ext.mlf 12: SET SOW / 1 /;  (a declaration with data, so the element is there from the start)"""
    if on(db) and "SOW" in db.sym:
        db.add("SOW", "select '1' as w")


def prep_ext(db: DB, interp):
    """prep_ext.mlf"""
    if not on(db):
        return
    # x ** y of GAMS in SQL (see _pow)
    db.x("create or replace macro gpow(x, y) as case when x > 0 then exp(y * ln(x)) when x = 0 and y > 0 then 0 else power(x, y) end")
    # --- Interpolate MACRO-specific parameters
    #     $ BATINCLUDE filparam TM_EXPBND 'R,' 'P' ",'','','','',''" DATAYEAR T
    #     $ BATINCLUDE filparam TM_EXPF 'R,' '' ",'','','','',''" DATAYEAR T
    #     $ BATINCLUDE filparam TM_VOC 'R,' 'C,BD' ",'','','',''" YEAR T
    #     $ BATINCLUDE filparam TM_GR 'R,' '' ",'','','','',''" YEAR T
    for n in ("TM_EXPBND", "TM_EXPF"):
        if n in db.sym and db.card(n) and db.q1(f'select count(*) from "{n}" where not in_DATAYEAR(y)'):
            from ..controls import unsupported
            unsupported(db, f"{n} given for a year outside DATAYEAR (filparam from DATAYEAR, prep_ext.mlf 12-13)", [n])
    for n in ("TM_EXPBND", "TM_EXPF", "TM_VOC", "TM_GR"):
        if n in db.sym:
            interp.filparam(db, n, "T")
    # --- Additions to support MACRO linear formulation
    #     SET MAG(CG) / ACT, AKL, LAB, KN, YN /;  SET MR(R), PP(T), TLAST(T), DM(C), XCP(J) /1, 6, 12/;  SET TM_DM(REG,COM);
    #     SET XTP(LL);  ALIAS (MIYR_1,T_1,TB);  ALIAS (T,TP);  PARAMETER NYPER(ALLYEAR);  PARAMETER CM_LED(LL);
    #     PARAMETER TM_TAXREV(R,T) //;  PARAMETER TM_HDF(R,T) //;
    for name, kind, dom in (("MAG", "set", ["CG"]), ("MR", "set", ["R"]), ("PP", "set", ["T"]), ("TLAST", "set", ["T"]),
                            ("DM", "set", ["C"]), ("XCP", "set", ["J"]), ("TM_DM", "set", ["REG", "COM"]),
                            ("XTP", "set", ["LL"]), ("NYPER", "par", ["ALLYEAR"]), ("CM_LED", "par", ["LL"]),
                            ("TM_TAXREV", "par", ["R", "T"]), ("TM_HDF", "par", ["R", "T"])):
        db.declare(name, kind, dom)
    _assign_ordered(db, "MAG", "select cg from (values ('ACT'), ('AKL'), ('LAB'), ('KN'), ('YN')) t(cg)")
    db.assign("XCP", "select j from (values ('1'), ('6'), ('12')) t(j)")
    per = _periods(db)
    ys = [y for y, _ in per]
    lagt = dict(per)
    # --- PP(T+1) = YES;  TLAST(T--ORD(T)) = YES;   (every milestone but the first; the last milestone)
    db.assign("PP", "select y from MILESTONYR where yv(y) > (select min(yv(y)) from MILESTONYR)")
    db.assign("TLAST", "select y from MILESTONYR where yv(y) = (select max(yv(y)) from MILESTONYR)")
    # --- NYPER(T) = LAGT(T);  NYPER(TLAST(T+1)) = NYPER(T);
    nyper = {y: lagt[y] for y in ys}
    if len(ys) > 1:
        nyper[ys[-1]] = nyper[ys[-2]]
    db.clear("NYPER")
    db.insert_rows("NYPER", [(y, v) for y, v in nyper.items() if v])
    # --- CM_LED(T+1)=LAGT(T);  XTP(LL)$=CM_LED(LL);  XTP(T) = YES;
    db.clear("CM_LED")
    db.insert_rows("CM_LED", [(ys[k + 1], lagt[ys[k]]) for k in range(len(ys) - 1) if lagt[ys[k]]])
    db.assign("XTP", "select y from CM_LED union select y from MILESTONYR")
    # --- TM_PP(R,PP)=YES;
    db.assign("TM_PP", "select g.r, p.y from REG g, PP p")
    # --- MR(R) $= SUM(T$TM_GR(R,T),YES);
    _assign_ordered(db, "MR", "select distinct r from TM_GR where in_REG(r) and in_MILESTONYR(y) and value <> 0" if "TM_GR" in db.sym
              else "select r from REG where false")
    # --- TM_GDPGOAL(R,TB) = TM_GDP0(R);
    # --- LOOP(PP(T+1),TM_GDPGOAL(R,PP) = TM_GDPGOAL(R,T)*(1+TM_GR(R,T)/100)**NYPER(T));
    gdp0 = {r: float(v) for r, v in db.q("select r, value from TM_GDP0 where in_REG(r)")} if "TM_GDP0" in db.sym else {}
    gr = {}
    if "TM_GR" in db.sym:
        for r, y, v in db.q("select r, y, value from TM_GR"):
            gr[(r, y)] = float(v)
    rows = []
    for (r,) in db.q("select r from REG"):
        g = gdp0.get(r, 0.0)
        out = {ys[0]: g} if ys else {}
        for k in range(len(ys) - 1):
            g = g * _pow(1 + gr.get((r, ys[k]), 0.0) / 100, nyper[ys[k]])
            out[ys[k + 1]] = g
        rows += [(r, y, v) for y, v in out.items() if v]
    db.clear("TM_GDPGOAL")
    db.insert_rows("TM_GDPGOAL", rows)
    # --- Save demand LIM for non-MR
    #     OPTION TM_DM < COM_PROJ;  TM_STEP(TM_DM(R,C),'N') = NOT COM_LIM(R,C,'FX');
    db.assign("TM_DM", "select distinct r, c from COM_PROJ")
    db.put("TM_STEP", """select t.r, t.c as cg, 'N' as l, 1.0 as value from TM_DM t
                         where not in_COM_LIM(t.r, t.c, 'FX')""")
    db.zap("TM_STEP", "l = 'N' and in_TM_DM(r, cg) and in_COM_LIM(r, cg, 'FX')")


def ppm_ext(db: DB):
    """ppm_ext.mlf"""
    if not on(db):
        return
    s = db.s
    # --- $ IF NOT '%CTST%'=='' MINYR = MIYR_V1;
    if db.ctl.get("CTST", "") != "":
        s["MINYR"] = s["MIYR_V1"]
    # --- OPTION TM_DM < DEM, CLEAR=TM_DMC;  LOOP(MI_DMAS(R,COM,C),TM_DM(R,C)=NO);
    db.assign("TM_DM", "select distinct r, c from DEM")
    if "MI_DMAS" in db.sym:
        db.remove("TM_DM", where="exists (select 1 from MI_DMAS m where m.r = TM_DM.r and m.c2 = TM_DM.c)")
    db.clear("TM_DMC")
    # --- Marginal costs of demands
    #     TM_DMC(RTC(R,T,C))$DEM(R,C) = SUM((COM_TS(R,C,S),RDCUR(R,CUR)),COM_BPRICE(RTC,S,CUR)*COM_FR(RTC,S));
    #     TM_DMC(R,T,C)$(TM_DMC(R,T,C)=0) = 0;     (no EPS is kept)
    db.put("TM_DMC", f"""
        select a.r, a.y, a.c,
               sum(v_COM_BPRICE(a.r, a.y, a.c, t.s, d.cur) * v_COM_FR(a.r, a.y, a.c, t.s)
                   order by {_uo('t.s')}, {_uo('d.cur')}) as value
        from RTC a
        join COM_TS t on t.r = a.r and t.c = a.c
        join RDCUR d on d.r = a.r
        where in_DEM(a.r, a.c)
        group by a.r, a.y, a.c""")
    # --- TM_AMP(R,T) = SOL_ACFR(R,'COST',T)*SUM(DEM(R,C),TM_DMC(R,T,C)*COM_PROJ(R,T,C))+1-1;
    db.clear("TM_AMP")
    db.put("TM_AMP", f"""
        select g.r, t.y,
               (v_SOL_ACFR(g.r, 'COST', t.y)
                * coalesce((select sum(v_TM_DMC(g.r, t.y, d.c) * v_COM_PROJ(g.r, t.y, d.c) order by {_uo('d.c')})
                            from DEM d where d.r = g.r), 0) + 1) - 1 as value
        from REG g, MILESTONYR t""")
    # --- TM_AMP(MR,T)$((M(T)>MIYR_V1+9)$PP(T)) = 0;
    db.zap("TM_AMP", f"in_MR(r) and v_M(y) > {s['MIYR_V1'] + 9} and in_PP(y)")
    # --- $ BATINCLUDE filparam TM_DMC 'R,' C ",'','','','',''" DATAYEAR T
    from .. import interp
    interp.filparam(db, "TM_DMC", "T")
    # --- Demand levels audit
    #     TM_DEM(MR(R),T,C)$((COM_PROJ(R,T,C)>0)$DEM(R,C)) = COM_PROJ(R,T,C);
    db.clear("TM_DEM")
    db.put("TM_DEM", """select p.r, p.y, p.c, p.value from COM_PROJ p
                        where in_MR(p.r) and in_MILESTONYR(p.y) and p.value > 0 and in_DEM(p.r, p.c)""")
    #     LOOP(PP(T),TM_DM(DEM(R,C))$(TM_DMC(R,T,C)=0)=NO; TM_DM(DEM(R,C))$(TM_DEM(R,T,C)=0)=NO);
    db.remove("TM_DM", where="""in_DEM(r, c) and exists (select 1 from PP p
                                 where v_TM_DMC(TM_DM.r, p.y, TM_DM.c) = 0 or v_TM_DEM(TM_DM.r, p.y, TM_DM.c) = 0)""")
    # --- remove elasticity steps from demands, keeping aggregates elastic
    #     RCJ(TM_DM(MR,C),J,BD)=NO;
    db.remove("RCJ", where="in_TM_DM(r, c) and in_MR(r)")
    #     COM_ELAST(MR(R),PP,C,ANNUAL,BDNEQ)$TM_DM(R,C) $= RD_AGG(R,C);
    db.put("COM_ELAST", """select a.r, p.y, a.c, 'ANNUAL' as s, b.l, 1.0 as value
                           from RD_AGG a, PP p, (values ('LO'), ('UP')) b(l)
                           where in_MR(a.r) and in_TM_DM(a.r, a.c)""", zero="skip")
    #     RHS_COMBAL(RTCS_VARC(R,T,C,S))$((NOT TM_DM(R,C)$PP(T))$TM_STEP(R,C,'N')) $= RCS_COMBAL(R,T,C,S,'FX');
    db.add("RHS_COMBAL", """select v.r, v.y, v.c, v.s from RTCS_VARC v
                            where not (in_TM_DM(v.r, v.c) and in_PP(v.y)) and v_TM_STEP(v.r, v.c, 'N') <> 0
                              and in_RCS_COMBAL(v.r, v.y, v.c, v.s, 'FX')""")
    # --- Aggregate demand, expenditures and price
    #     OPTION CLEAR=DM;  DM('ACT')=YES;
    db.assign("DM", "select 'ACT' as c")
    #     TM_ANNC(MR(R),T) = SUM(DEM(R,C),TM_DMC(R,T,C)*TM_DEM(R,T,C));
    #     TM_DEM(MR(R),T,DM) = SUM(DEM(R,C),TM_DEM(R,T,C));
    #     TM_DMC(MR(R),T,DM) = TM_ANNC(R,T)/TM_DEM(R,T,DM);
    db.clear("TM_ANNC")
    db.put("TM_ANNC", f"""
        select m.r, t.y, sum(v_TM_DMC(m.r, t.y, d.c) * v_TM_DEM(m.r, t.y, d.c) order by {_uo('d.c')}) as value
        from MR m join DEM d on d.r = m.r, MILESTONYR t
        group by m.r, t.y""")
    db.put("TM_DEM", f"""
        select m.r, t.y, 'ACT' as c, sum(v_TM_DEM(m.r, t.y, d.c) order by {_uo('d.c')}) as value
        from MR m join DEM d on d.r = m.r, MILESTONYR t
        group by m.r, t.y""")
    db.put("TM_DMC", """select m.r, t.y, 'ACT' as c, v_TM_ANNC(m.r, t.y) / v_TM_DEM(m.r, t.y, 'ACT') as value
                        from MR m, MILESTONYR t where v_TM_DEM(m.r, t.y, 'ACT') <> 0""")
    #     LOOP(TB(TT(T-1)),TM_DMC(R,TT,DM) = MAX(TM_DMC(R,TT,DM),TM_DMC(R,T,DM)*0.7));
    per = [y for y, _ in _periods(db)]
    if len(per) > 1:
        db.put("TM_DMC", f"""select g.r, '{per[0]}' as y, 'ACT' as c,
                                    greatest(v_TM_DMC(g.r, '{per[0]}', 'ACT'), v_TM_DMC(g.r, '{per[1]}', 'ACT') * 0.7) as value
                             from REG g""")
    # --- Annual costs and net taxes for MACRO
    #     TM_ANNC(MR(R),T) = SOL_ACFR(R,'COST',T)*TM_ANNC(R,T);
    #     TM_ANNC(R,T) $= TM_AMP(R,T);
    #     TM_TAXREV(MR(R),T) = SOL_ACFR(R,'TAX',T)*TM_ANNC(R,T);
    db.put("TM_ANNC", """select m.r, t.y, v_SOL_ACFR(m.r, 'COST', t.y) * v_TM_ANNC(m.r, t.y) as value
                         from MR m, MILESTONYR t""")
    db.put("TM_ANNC", "select r, y, value from TM_AMP", zero="skip")
    db.clear("TM_TAXREV")
    db.put("TM_TAXREV", """select m.r, t.y, v_SOL_ACFR(m.r, 'TAX', t.y) * v_TM_ANNC(m.r, t.y) as value
                           from MR m, MILESTONYR t""")
    # --- Quadratic supply function
    #     TM_ANNC(R,T) = TM_ANNC(R,T) * TM_SCALE_CST;
    #     LOOP(TB, TM_EC0(R) = TM_ANNC(R,TB); TM_DDATPREF(R,DM) = TM_DMC(R,TB,DM));
    #     TM_QSFB(R,T,DM)$TM_DEM(R,T,DM) = 0.5*TM_DMC(R,T,DM)*TM_SCALE_CST/TM_DEM(R,T,DM);
    #     TM_QSFA(R,T) = TM_ANNC(R,T)- SUM(DM, TM_QSFB(R,T,DM)*TM_DEM(R,T,DM)**2);
    cst = s.get("TM_SCALE_CST", 0.0)
    db.put("TM_ANNC", f"select r, y, value * {cst!r} as value from TM_ANNC")
    tb = per[0] if per else None
    db.clear("TM_EC0")
    db.clear("TM_DDATPREF")
    if tb:
        db.put("TM_EC0", f"select r, v_TM_ANNC(r, '{tb}') as value from REG")
        db.put("TM_DDATPREF", f"select r, 'ACT' as c, v_TM_DMC(r, '{tb}', 'ACT') as value from REG")
    db.clear("TM_QSFB")
    db.put("TM_QSFB", f"""select r, y, c, 0.5 * v_TM_DMC(r, y, c) * {cst!r} / value as value
                          from TM_DEM where c = 'ACT' and in_MILESTONYR(y) and value <> 0""")
    db.clear("TM_QSFA")
    db.put("TM_QSFA", """select g.r, t.y, v_TM_ANNC(g.r, t.y) - v_TM_QSFB(g.r, t.y, 'ACT') * gpow(v_TM_DEM(g.r, t.y, 'ACT'), 2)
                         as value from REG g, MILESTONYR t""")
    # --- Process macro parameters
    #     TM_DEPR(R)$(NOT TM_DEPR(R)) = TM_DEFVAL('DEPR');  ... ESUB, KGDP, KPVS, DMTOL, IVETOL;
    #     TM_DESUB(R)$(NOT TM_DESUB(R)) = TM_ESUB(R);
    #     (an input given as EPS is a record: NOT of it is false, and it stays EPS)
    dv = {u: float(v) for u, v in db.q("select u, value from TM_DEFVAL")}
    for n, k in (("TM_DEPR", "DEPR"), ("TM_ESUB", "ESUB")):
        db.put(n, f"select r, {dv.get(k, 0.0)!r} as value from REG where not in_{n}(r)")
    db.put("TM_DESUB", "select r, v_TM_ESUB(r) as value from REG where not in_TM_DESUB(r)")
    for n, k in (("TM_KGDP", "KGDP"), ("TM_KPVS", "KPVS"), ("TM_DMTOL", "DMTOL"), ("TM_IVETOL", "IVETOL")):
        db.put(n, f"select r, {dv.get(k, 0.0)!r} as value from REG where not in_{n}(r)")
    # --- Calculate cost amplifier
    #     TM_AMP(MR,T) = MAX(0,SMAX(PP(TT)$(ORD(TT)>ORD(T)),TM_ANNC(MR,TT)/(TM_GDPGOAL(MR,TT)/TM_GDPGOAL(MR,T))*
    #                    POWER(TM_DEFVAL('ESC'),YEARVAL(T)-YEARVAL(TT)))-TM_ANNC(MR,T));
    #     (SMAX over no period is -INF: MAX(0,...) is 0 in the last period)
    esc = dv.get("ESC", 0.0)
    db.put("TM_AMP", f"""
        select m.r, t.y,
               greatest(0, coalesce((select max(v_TM_ANNC(m.r, tt.y) / (v_TM_GDPGOAL(m.r, tt.y) / v_TM_GDPGOAL(m.r, t.y))
                                                * power({esc!r}, yv(t.y) - yv(tt.y)))
                                     from PP tt where yv(tt.y) > yv(t.y)), '-inf'::double) - v_TM_ANNC(m.r, t.y)) as value
        from MR m, MILESTONYR t""")
    _economics(db, dv, per)


def _economics(db: DB, dv, per):
    """ppm_ext.mlf 54-95: the economic parameters of the first period and the intermediate values."""
    s = db.s
    tb = per[0] if per else None
    nyper = {y: float(v) for y, v in db.q("select y, value from NYPER")}
    # --- TM_DDF(MR,T,DM) = EPS;  TM_AEEIV(MR,T,DM) = EPS;
    db.put("TM_DDF", "select m.r, t.y, 'ACT' as c, 0 as value from MR m, MILESTONYR t", zero="eps")
    db.put("TM_AEEIV", "select m.r, t.y, 'ACT' as c, 0 as value from MR m, MILESTONYR t", zero="eps")
    # --- TM_ASRV(R) = 1 - TM_DEPR(R) / 100;  TM_GROWV(MR,T) = TM_GR(MR,T);
    db.put("TM_ASRV", "select r, 1 - v_TM_DEPR(r) / 100 as value from REG")
    db.put("TM_GROWV", "select m.r, t.y, v_TM_GR(m.r, t.y) as value from MR m, MILESTONYR t")
    # --- TM_DFACTCURR(R,XTP) = 1 - (TM_KPVS(R) / TM_KGDP(R) - TM_DEPR(R)/100 - TM_GROWV(R,XTP)/100);
    db.put("TM_DFACTCURR", """select g.r, x.y, 1 - (v_TM_KPVS(g.r) / v_TM_KGDP(g.r) - v_TM_DEPR(g.r) / 100
                                                  - v_TM_GROWV(g.r, x.y) / 100) as value
                              from REG g, XTP x""")
    # --- TM_RHO(R) = 1 - 1 / TM_ESUB(R);
    db.put("TM_RHO", "select r, 1 - 1 / v_TM_ESUB(r) as value from REG")
    # --- TM_TSRV(R,T) = TM_ASRV(R) ** NYPER(T);
    db.put("TM_TSRV", "select g.r, t.y, gpow(v_TM_ASRV(g.r), v_NYPER(t.y)) as value from REG g, MILESTONYR t")
    # --- TM_K0(R) = TM_KGDP(R) * TM_GDP0(R);  TM_IV0(R) = TM_K0(R) * (TM_DEPR(R) + SUM(TB,TM_GROWV(R,TB))) / 100;
    #     TM_C0(R) = TM_GDP0(R) - TM_IV0(R);  TM_Y0(R) = TM_GDP0(R) + TM_EC0(R) + SUM(TB,TM_AMP(R,TB));
    db.put("TM_K0", "select r, v_TM_KGDP(r) * v_TM_GDP0(r) as value from REG")
    db.put("TM_IV0", f"select r, v_TM_K0(r) * (v_TM_DEPR(r) + v_TM_GROWV(r, '{tb}')) / 100 as value from REG")
    db.put("TM_C0", "select r, v_TM_GDP0(r) - v_TM_IV0(r) as value from REG")
    db.put("TM_Y0", f"select r, v_TM_GDP0(r) + v_TM_EC0(r) + v_TM_AMP(r, '{tb}') as value from REG")
    # --- TM_AEEIFAC(MR,T,DM) = 1;  TM_DFACT(MR,TB) = 1;  TM_L(MR,TB) = 1;
    db.put("TM_AEEIFAC", "select m.r, t.y, 'ACT' as c, 1.0 as value from MR m, MILESTONYR t")
    db.put("TM_DFACT", f"select r, '{tb}' as y, 1.0 as value from MR")
    db.put("TM_L", f"select r, '{tb}' as y, 1.0 as value from MR")
    # --- LOOP(PP(T+1), TM_DFACT(R,PP) = TM_DFACT(R,T) * TM_DFACTCURR(R,T) ** NYPER(T);
    #                   TM_L(R,PP) = TM_L(R,T) * (1 + TM_GROWV(R,T) / 100) ** NYPER(T));   (all regions R)
    dfc = {(r, y): float(v) for r, y, v in db.q("select r, y, value from TM_DFACTCURR")}
    grow = {(r, y): float(v) for r, y, v in db.q("select r, y, value from TM_GROWV")}
    df = {(r, y): float(v) for r, y, v in db.q("select r, y, value from TM_DFACT")}
    lab = {(r, y): float(v) for r, y, v in db.q("select r, y, value from TM_L")}
    regs = [r for (r,) in db.q("select r from REG")]
    for r in regs:
        for k in range(len(per) - 1):
            t, pp = per[k], per[k + 1]
            df[(r, pp)] = df.get((r, t), 0.0) * _pow(dfc.get((r, t), 0.0), nyper.get(t, 0.0))
            lab[(r, pp)] = lab.get((r, t), 0.0) * _pow(1 + grow.get((r, t), 0.0) / 100, nyper.get(t, 0.0))
    # --- Arbitrary multiplier on utility in last time period
    #     TM_DFACT(MR(R),TLAST)$(TM_ARBM > 1) = TM_DFACT(R,TLAST) *
    #         (1-MIN(.999,TM_DFACTCURR(R,TLAST))**(NYPER(TLAST)*TM_ARBM)) / (1-MIN(.999,TM_DFACTCURR(R,TLAST))**(NYPER(TLAST) * 1 ));
    arbm = s.get("TM_ARBM", 0.0)
    mr = {r for (r,) in db.q("select r from MR")}
    if arbm > 1 and per:
        tl = per[-1]
        for r in mr:
            b = min(.999, dfc.get((r, tl), 0.0))
            df[(r, tl)] = df.get((r, tl), 0.0) * (1 - _pow(b, nyper.get(tl, 0.0) * arbm)) / (1 - _pow(b, nyper.get(tl, 0.0) * 1))
    db.clear("TM_DFACT")
    db.insert_rows("TM_DFACT", sorted((r, y, v) for (r, y), v in df.items() if v))
    db.clear("TM_L")
    db.insert_rows("TM_L", sorted((r, y, v) for (r, y), v in lab.items() if v))
    # --- Weights for periods:  Z=MAX(1,SMAX(T,D(T))); TM_PWT(T) = D(T)/Z;
    z = max(1.0, db.q1("select max(value) from D where in_MILESTONYR(y)") or 0.0)
    db.put("TM_PWT", f"select y, v_D(y) / {z!r} as value from MILESTONYR")
    # --- TM_D0(MR(R),DM) = SUM(TB,TM_DEM(R,TB,DM))*TM_SCALE_NRG;
    #     TM_B(MR(R),DM)  = (TM_D0(R,DM) / TM_Y0(R)) ** (1 - TM_RHO(R));
    #     TM_B(MR(R),DM)  = TM_SCALE_CST / TM_SCALE_NRG * TM_DDATPREF(R,DM) * TM_B(R,DM);
    nrg, cst = s.get("TM_SCALE_NRG", 0.0), s.get("TM_SCALE_CST", 0.0)
    db.put("TM_D0", f"select r, 'ACT' as c, v_TM_DEM(r, '{tb}', 'ACT') * {nrg!r} as value from MR")
    db.put("TM_B", "select r, 'ACT' as c, gpow(v_TM_D0(r, 'ACT') / v_TM_Y0(r), 1 - v_TM_RHO(r)) as value from MR")
    db.put("TM_B", f"select r, 'ACT' as c, {cst!r} / {nrg!r} * v_TM_DDATPREF(r, 'ACT') * v_TM_B(r, 'ACT') as value from MR")
    # --- TM_AKL(MR(R)) = TM_Y0(R) ** TM_RHO(R) - SUM(DM, TM_B(R,DM) * (TM_D0(R,DM) ** TM_RHO(R)));
    #     TM_AKL(MR(R)) = TM_AKL(R) / (TM_K0(R) ** (TM_KPVS(R) * TM_RHO(R)));
    db.put("TM_AKL", """select r, gpow(v_TM_Y0(r), v_TM_RHO(r)) - v_TM_B(r, 'ACT') * gpow(v_TM_D0(r, 'ACT'), v_TM_RHO(r))
                        as value from MR""")
    db.put("TM_AKL", "select r, v_TM_AKL(r) / gpow(v_TM_K0(r), v_TM_KPVS(r) * v_TM_RHO(r)) as value from MR")


# ------------------------------------------------------------------------------------------------------------------
# equ_ext.mlf: the bounds of the MACRO variables, the calibration (calibase.mlf) and presolve.mlf, which prepares the
# coefficients of the linearised model from the calibration's solution. The equations themselves are stated by the
# equation package (times_eq, equations/mlf.jl).

INF = float("inf")
# VARIABLES VAR_UTIL, VAR_NTX(R,T) (mod_vars.tm): free; the other MACRO variables are POSITIVE VARIABLES
FREE = {"VAR_UTIL", "VAR_NTX"}
# the MACRO variables whose bounds equ_ext.mlf and presolve.mlf set, with their index columns
VARIABLES = {"VAR_D": ("r", "y", "cg"), "VAR_DEM": ("r", "y", "c"), "VAR_INV": ("r", "y"), "VAR_K": ("r", "y"),
             "VAR_C": ("r", "y"), "VAR_SP": ("r", "y", "cg"), "VAR_EC": ("r", "y"), "VAR_NTX": ("r", "y"),
             "VAR_XCAPP": ("r", "y", "p", "j")}

# Another calibration in place of the port's (_calibrate): a function (db) -> the solution of the last calibration NLP,
# {"VAR_C.L": {(r, t): level}, "EQ_DD.M": {(r, t, c): marginal}, ...}, which also leaves in `db` the parameters
# calibase.mlf and ddfupd.msa assign (TM_NWT, TM_DDF, TM_GROWV, TM_AEEIFAC, TM_DFACT, TM_L, TM_IV0, PAR_Y, ...).
CALIBRATION = None

# the taxes and subsidies of the objective (their annual revenues are rebated in the Negishi iterations)
TAX_INPUTS = ("NCAP_ITAX", "NCAP_ISUB", "NCAP_FTAX", "NCAP_FSUB", "FLO_TAX", "FLO_SUB", "COM_TAXNET", "COM_SUBNET",
              "COM_TAXPRD", "COM_SUBPRD")

# declared by calibase.mlf
CALIBASE_DECL = (("LOOPS", "set", ["u"]), ("GDPLOSS", "par", ["REG", "T"]), ("MSA_ERR", "par", ["NITER", "LOOPS", "REG"]),
                 ("TM_TOL", "par", ["ITEM"]), ("ERRDEM", "par", []), ("ERRGDP", "par", []), ("DOITER", "par", []))
# declared by presolve.mlf
PRESOLVE_DECL = (("TM_DMAS", "set", ["CG", "CG"]), ("TM_CES", "set", ["CG"]), ("TM_RCJ", "set", ["R", "CG", "J", "BD"]),
                 ("LOGJ", "set", ["J", "BD"]), ("TM_LOGJOT", "par", []), ("TM_LSC", "par", []),
                 ("TM_BASEPRI", "par", ["R", "T", "CG"]), ("TM_BASELEV", "par", ["R", "T", "CG"]),
                 ("TM_PREF", "par", ["R", "T", "CG"]), ("TM_QREF", "par", ["R", "T", "CG"]),
                 ("TM_SHAR", "par", ["R", "T", "CG", "CG"]), ("TM_AGG", "par", ["R", "T", "CG", "CG"]),
                 ("TM_CESLEV", "par", ["R", "T", "CG"]), ("TM_AGC", "par", ["R", "T", "CG", "CG", "J", "BD"]),
                 ("TM_MIDCON", "par", ["R", "T"]), ("TM_LOGVAL", "par", ["J", "BD"]))


class _Bounds:
    """The bounds of the MACRO variables as GAMS holds them (.LO, .UP; .FX sets both and the level), written at the end
    as the tables B_<variable> of the port (non-default records only), and their levels (.L: the starting point of the
    calibration)."""

    def __init__(self):
        self.b = {v: {} for v in VARIABLES}
        self.l = {v: {} for v in VARIABLES}

    def _get(self, var, k):
        return self.b[var].setdefault(k, [-INF if var in FREE else 0.0, INF])

    def lo(self, var, k, x):
        self._get(var, k)[0] = x

    def up(self, var, k, x):
        self._get(var, k)[1] = x

    def fx(self, var, k, x):
        self._get(var, k)[:] = [x, x]
        self.l[var][k] = x

    def level(self, var, k, x):
        self.l[var][k] = x

    def write(self, db: DB):
        for var, cols in VARIABLES.items():
            lo0 = -INF if var in FREE else 0.0
            rows = [k + (lo, up) for k, (lo, up) in sorted(self.b[var].items()) if (lo, up) != (lo0, INF)]
            db.x(f'drop table if exists "B_{var}"')
            db.x(f'create table "B_{var}" ({", ".join(f"d{i} VARCHAR" for i in range(len(cols)))}, lower DOUBLE, upper DOUBLE)')
            db.insert_rows(f'"B_{var}"', rows)
            db.bounds.add(var)


def _par(db: DB, name):
    """A parameter as a dict {key: value} (a scalar: {(): value})."""
    if db.sym[name].kind == "scalar":
        return {(): db.s[name]}
    return {tuple(r[:-1]): float(r[-1]) for r in db.q(f'select * from "{name}"')}


def _set(db: DB, name):
    return [tuple(r) for r in db.q(f'select * from "{name}"')]


def _store(db: DB, name, d, eps=()):
    """name = d: the whole content of a parameter (zeros are no records, but for the keys of `eps`: EPS records)"""
    db.clear(name)
    db.insert_rows(f'"{name}"', [k + (v,) for k, v in d.items() if v or k in eps])


def _gams_round(x, n=0):
    """GAMS ROUND(x,n): half away from zero, at 10**-n"""
    if n >= 0:
        f = 10.0 ** n
        return math.copysign(math.floor(abs(x) * f + 0.5), x) / f
    f = 10.0 ** -n
    return math.copysign(math.floor(abs(x) / f + 0.5), x) * f


def equ_ext(db: DB):
    """equ_ext.mlf after the equations: the bounds, calibase.mlf, the periods MACRO leaves fixed, presolve.mlf and the
    bounds of the full model (maindrv.mod 80: main_ext.mod equ_ext, before bndmain.mod)."""
    if not on(db):
        return
    db.bounds = getattr(db, "bounds", set())
    _mod_vars(db)
    # rpt_ext.mlf 37-40: the Negishi iterations rebate the tax revenues of the solution (TM_TAXREV from REG_ACOST's
    # INVX, FIXX, VARX), which needs the annual taxes of each solve: not in the port yet
    # eqmain.mod 75 (taken in an MLF run): $IFI %MACRO%==YES RTP_VARP(RTP(R,T,P))$((TM_QFAC(R) NE 0)$TM_CAPTB(R,P)) = YES;
    if "TM_QFAC" in db.sym and db.card("TM_QFAC") and "TM_CAPTB" in db.sym and db.card("TM_CAPTB"):
        from ..controls import unsupported
        unsupported(db, "MACRO MLF with TM_QFAC and TM_CAPTB (the capacity variables of eqmain.mod 75)", ["TM_QFAC", "TM_CAPTB"])
    taxes = {n: int(db.card(n)) for n in TAX_INPUTS if n in db.sym and db.card(n)}
    if taxes or (db.card("TM_TAXREV") if "TM_TAXREV" in db.sym else 0):
        from ..controls import unsupported
        unsupported(db, "MACRO MLF with taxes or subsidies in the objective: the rebate of tax revenues in the Negishi "
                        "iterations (rpt_ext.mlf 37-40, TM_TAXREV)", taxes or ["TM_TAXREV"])
    B = _Bounds()
    _bounds_before(db, B)
    nlp = calibase(db, B)
    if nlp is None:
        return
    _fixed_periods(db)
    presolve(db, B, nlp)
    _full_model_bounds(db, B, nlp)
    B.write(db)


def _mod_vars(db: DB):
    """mod_vars.tm (maindrv.mod 77, SRC tm in a MACRO run)
    SET OBVANN(OBV) / OBJINV, OBJFIX, OBJVAR /;
    RD_NLP(DEM) = 1;   (the demands are the variables VAR_DEM in the commodity balances and the peaks)
    VAR_ANNCST.LO(OBV(UCN),R,T,CUR)$(RDCUR(R,CUR)$UC_RHS(UCN,'N')) = INF;   (and UC_RHSR)"""
    db.declare("MLF", "set", ["UC_NAME"])                 # the equations state TIMES_MACRO (times_eq: equations/mlf.jl)
    db.clear("MLF")
    db.insert_rows('"MLF"', [("YES",)])
    db.declare("OBVANN", "set", ["OBV"])
    db.clear("OBVANN")
    db.insert_rows('"OBVANN"', [("OBJINV",), ("OBJFIX",), ("OBJVAR",)])
    db.declare("RD_NLP", "par", ["R", "C"])
    db.put("RD_NLP", "select r, c, 1.0 as value from DEM")
    from .bounds import OBV
    obv = ", ".join(f"'{o}'" for o in OBV)
    db.x('create table if not exists "B_VAR_ANNCST" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x(f"""insert into "B_VAR_ANNCST"
             select distinct u.uc, d.r, t.y, d.cur, 'inf'::double, 'inf'::double
             from (select uc, null as r from UC_RHS where l = 'N' union select uc, r from UC_RHSR where l = 'N') u,
                  RDCUR d, MILESTONYR t
             where u.uc in ({obv}) and (u.r is null or u.r = d.r)""")
    db.bounds.add("VAR_ANNCST")


def _milestones(db: DB):
    per = [y for y, _ in _periods(db)]
    return per, per[0] if per else None


def _bounds_before(db: DB, B: _Bounds):
    """equ_ext.mlf 69-96: the bounds of the calibration model"""
    per, tb = _milestones(db)
    mr = [r for (r,) in _set(db, "MR")]
    pp = {y for (y,) in _set(db, "PP")}
    dm = [c for (c,) in _set(db, "DM")]
    D0, DEM, DMTOL = _par(db, "TM_D0"), _par(db, "TM_DEM"), _par(db, "TM_DMTOL")
    K0, DEPR, TSRV, IV0, L = _par(db, "TM_K0"), _par(db, "TM_DEPR"), _par(db, "TM_TSRV"), _par(db, "TM_IV0"), _par(db, "TM_L")
    GDP0, ANNC, EC0, AMP = _par(db, "TM_GDP0"), _par(db, "TM_ANNC"), _par(db, "TM_EC0"), _par(db, "TM_AMP")
    g = lambda d, *k: d.get(k, 0.0)
    for r in mr:
        for c in dm:
            # VAR_D.LO(MR(R),T,DM) = TM_DMTOL(R) * TM_D0(R,DM);
            for t in per:
                B.lo("VAR_D", (r, t, c), g(DMTOL, r) * g(D0, r, c))
            # VAR_D.L(MR(R),PP,DM) = TM_D0(R,DM);
            for t in per:
                if t in pp:
                    B.level("VAR_D", (r, t, c), g(D0, r, c))
            # VAR_D.FX(MR(R),T(TB),DM) = TM_D0(R,DM);  VAR_DEM.FX(MR,T(TB),DM) = TM_DEM(MR,T,DM);
            B.fx("VAR_D", (r, tb, c), g(D0, r, c))
            B.fx("VAR_DEM", (r, tb, c), g(DEM, r, tb, c))
        # LOOP(MR(R), Z=TM_K0(R)*TM_DEPR(R)/100; LOOP(PP(T+1), Z=Z*TM_TSRV(R,T); VAR_INV.LO(R,PP) = Z));
        z = g(K0, r) * g(DEPR, r) / 100
        for k in range(len(per) - 1):
            z = z * g(TSRV, r, per[k])
            B.lo("VAR_INV", (r, per[k + 1]), z)
        # VAR_INV.L(MR,PP) = TM_IV0(MR) * TM_L(MR,PP);  VAR_INV.FX(MR,T(TB)) = TM_IV0(MR);
        for t in per:
            if t in pp:
                B.level("VAR_INV", (r, t), g(IV0, r) * g(L, r, t))
        B.fx("VAR_INV", (r, tb), g(IV0, r))
        for t in per:
            # VAR_D.LO(MR,T,'AKL') = MIN(1,TM_K0(MR))/2;  VAR_D.LO(MR,T,'KN') = TM_K0(MR) * 0.33;
            # VAR_D.LO(MR,T,'LAB') = TM_L(MR,T)/2;
            B.lo("VAR_D", (r, t, "AKL"), min(1, g(K0, r)) / 2)
            B.lo("VAR_D", (r, t, "KN"), g(K0, r) * 0.33)
            B.lo("VAR_D", (r, t, "LAB"), g(L, r, t) / 2)
        # VAR_K.FX(MR,T(TB)) = TM_K0(MR);
        B.fx("VAR_K", (r, tb), g(K0, r))
        for t in per:
            # VAR_C.L(MR,TP) = TM_GDP0(MR) - TM_IV0(MR);  VAR_C.LO(MR,TP) = TM_GDP0(MR) * 0.33;  VAR_SP.FX(MR,TP,DM) = 0;
            B.level("VAR_C", (r, t), g(GDP0, r) - g(IV0, r))
            B.lo("VAR_C", (r, t), g(GDP0, r) * 0.33)
            for c in dm:
                B.fx("VAR_SP", (r, t, c), 0.0)
        # VAR_EC.LO(MR,PP) = TM_ANNC(MR,PP) * 0.33;  VAR_EC.LO(MR,T(TB)) = TM_EC0(MR) + TM_AMP(MR,TB);
        for t in per:
            if t in pp:
                B.lo("VAR_EC", (r, t), g(ANNC, r, t) * 0.33)
        B.lo("VAR_EC", (r, tb), g(EC0, r) + g(AMP, r, tb))
    # VAR_XCAPP.UP(RTP,J) = INF;  VAR_XCAPP.UP(RTP,XCP(J))$(ORD(J)<7) $= TM_EXPBND(RTP);
    xcp = [j for (j,) in _set(db, "XCP") if int(j) < 7]
    rtp = set(_set(db, "RTP"))
    for (r, t, p), x in _par(db, "TM_EXPBND").items():
        if x and (r, t, p) in rtp:
            for j in xcp:
                B.up("VAR_XCAPP", (r, t, p, j), x)


def calibase(db: DB, B: _Bounds):
    """calibase.mlf (equ_ext.mlf 98): the calibration of MACRO, NLP model MCE solved in a loop with ddfupd.msa, then the
    Negishi weights. -> the solution of its last NLP (levels and marginals)."""
    for name, kind, dom in CALIBASE_DECL:
        db.declare(name, kind, dom)
    nlp = CALIBRATION(db) if CALIBRATION is not None else _calibrate(db, B)
    if nlp is None:
        return None
    # the bounds calibase.mlf and ddfupd.msa leave:
    #   VAR_NTX.FX(MR,PP)=0; ... VAR_NTX.UP(MR,PP) = INF; VAR_NTX.LO(MR,PP) =-INF;   (free again: no record)
    #   ddfupd.msa: VAR_INV.FX(MR,T(T_1)) = TM_IV0(MR);
    _, tb = _milestones(db)
    iv0 = _par(db, "TM_IV0")
    mr = [r for (r,) in _set(db, "MR")]
    for r in mr:
        B.fx("VAR_INV", (r, tb), iv0.get((r,), 0.0))
    # The last NLP is solved with SOLVEOPT=REPLACE: the records of its variables that are not columns of the model lose
    # their bounds. VAR_DEM and VAR_SP are columns only through EQ_DD(MR(R),PP(T),C('ACT')) and EQ_ESCOST(MR(R),PP(T)):
    # their bounds of VAR_DEM.FX(MR,T(TB),DM) and VAR_SP.FX(MR,TP,DM) above stay only on (MR,PP,'ACT'). (The other
    # variables of MCE are columns on every record that has bounds here.)
    mcols = {(r, t, "ACT") for r in mr for (t,) in _set(db, "PP")}
    for var in ("VAR_DEM", "VAR_SP"):
        for k in [k for k in B.b[var] if k not in mcols]:
            del B.b[var][k]
    return nlp


# What the calibration reads (calibase.mlf, ddfupd.msa, the model MCE) and what it assigns (written back to `db`)
CALIBRATION_READS = """MR TM_PWT TM_DFACT TM_AKL TM_RHO TM_B TM_KPVS TM_L TM_TSRV D TM_GROWV TM_DEPR TM_AEEIFAC TM_Y0 TM_IVETOL
  TM_QSFA TM_QSFB TM_AMP TM_HDF TM_SCALE_NRG TM_SCALE_UTIL TM_SCALE_CST TM_GDPGOAL TM_GDP PAR_Y TM_DEM PAR_MC TM_ESUB NYPER
  TM_GR PAR_GRGDP TM_KGDP TM_K0 TM_IV0 TM_C0 TM_GDP0 TM_ARBM TM_DDF_Y TM_DDF_DM TM_DDF_SP TM_DDF TM_F2 TM_AEEIV TM_DFACTCURR
  TM_DMC TM_YCHECK COEF_PVT TM_DEFVAL TM_NWT TM_NWTIT TM_UDF GDPLOSS""".split()
CALIBRATION_WRITES = """TM_YCHECK TM_IVETOL TM_GDP PAR_Y TM_GROWV PAR_GRGDP PAR_MC MREG TM_NWT TM_HDF TM_UDF TM_DDF_Y TM_DDF_DM
  TM_DDF_SP TM_DDF TM_F2 TM_AEEIV TM_DFACTCURR TM_IV0 TM_C0 TM_AEEIFAC TM_DFACT TM_L TM_NWTIT GDPLOSS MSA_ERR TM_TOL ERRDEM
  ERRGDP DOITER LOOPS""".split()


def _calibrate(db: DB, B: _Bounds):
    """The calibration of MACRO, in Julia (times_eq/tools/mlf_calibrate.jl: calibase.mlf and ddfupd.msa, the NLP MCE
    with Ipopt): its input written from `db` and the levels and bounds of `B`, what it assigns read back into `db`.
    -> the levels and marginals of its last NLP."""
    import os, subprocess, tempfile, time
    from .. import kernels
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    script = os.path.join(root, "times_eq", "tools", "mlf_calibrate.jl")
    project = os.environ.get("TIMESPP_KERNELS_PROJECT") or os.path.join(root, ".julia_env")
    bindir = kernels.julia_bindir()
    julia = os.path.join(bindir, "julia.exe" if os.name == "nt" else "julia") if bindir else "julia"
    per, _ = _milestones(db)
    work = tempfile.mkdtemp(prefix="mlf_calibration_")
    fin, fout = os.path.join(work, "in.tsv"), os.path.join(work, "out.tsv")
    fmt = lambda name, k, x: "\t".join((name,) + tuple(str(a) for a in k) + (repr(float(x)),))
    with open(fin, "w", encoding="utf-8", newline="\n") as f:
        f.write("@T\t" + "\t".join(per) + "\n")
        f.write("@NITER\t" + "\t".join(u for (u,) in db.q("select * from NITER")) + "\n")
        f.write("@REG\t" + "\t".join(r for (r,) in db.q("select * from REG")) + "\n")
        for name in CALIBRATION_READS:
            if name not in db.sym:
                continue
            if db.sym[name].kind == "set":
                f.writelines(fmt(name, k, 1.0) + "\n" for k in _set(db, name))
            else:
                f.writelines(fmt(name, k, x) + "\n" for k, x in _par(db, name).items())
        for var in VARIABLES:
            f.writelines(fmt("L:" + var, k, x) + "\n" for k, x in B.l[var].items())
            for k, (lo, up) in B.b[var].items():
                f.write(fmt("LO:" + var, k, lo) + "\n")
                f.write(fmt("UP:" + var, k, up) + "\n")
    t0 = time.time()
    p = subprocess.run([julia, "--startup-file=no", f"--project={project}", script, fin, fout], capture_output=True, text=True)
    stops = [l.split("TIMES STOPS: ", 1)[1] for l in (p.stdout + p.stderr).splitlines() if "TIMES STOPS: " in l]
    if p.returncode != 0 and stops:
        # a statement on which TIMES itself ends the run with an execution error: the run stops the same way
        from ..controls import unsupported
        unsupported(db, "MACRO MLF: TIMES stops on this input: " + stops[0])
        return None
    if p.returncode != 0 or not os.path.exists(fout):
        raise RuntimeError("the calibration of MACRO (times_eq/tools/mlf_calibrate.jl) failed:\n" + (p.stdout + p.stderr)[-3000:])
    out, nlp = {}, {}
    for line in open(fout, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if f[0].startswith("#"):
            db.log.append("MACRO calibration " + f[0][1:].strip())
            continue
        name, k, x = f[0], tuple(f[1:-1]), float(f[-1])
        if name.startswith(("L:", "M:")):
            nlp.setdefault(f"{name[2:]}.{name[0]}", {})[k] = x
        else:
            out.setdefault(name, {})[k] = x
    for name in CALIBRATION_WRITES:
        d = out.get(name, {})
        if db.sym[name].kind == "scalar":
            db.s[name] = d.get((), 0.0)
        elif db.sym[name].kind == "set":
            db.clear(name)
            db.insert_rows(f'"{name}"', sorted(d))
        else:
            _store(db, name, d)
    msgs = [l for l in db.log if l.startswith("MACRO calibration")]
    opts = next((l.split("options ", 1)[1] for l in msgs if "options " in l), "")
    db.mlf_calibration = {"nlps": sum("NLP MCE" in l for l in msgs), "iterations": sum("calibration iteration" in l for l in msgs),
                          "negishi": sum("Negishi iteration" in l for l in msgs), "ipopt": opts,
                          "last": next((l.split(": ", 1)[1] for l in reversed(msgs) if "Negishi iteration" in l), ""),
                          "seconds": round(time.time() - t0, 1)}
    print(f"  the calibration of MACRO (Ipopt): {time.time() - t0:.1f} s, " +
          next((l for l in reversed(db.log) if "Negishi iteration" in l), "").replace("MACRO calibration ", ""))
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return nlp


def _fixed_periods(db: DB):
    """equ_ext.mlf 100-101: the periods fixed by FIXBOH or REG_BDNCAP are not linearised
    $ IF SET FIXBOH LOOP(R, Z=REG_FIXT(R); IF(Z=0,Z=ABS(%FIXBOH%)); TM_PP(R,T)$(M(T) LE Z)=NO);
    $ IF DEFINED REG_BDNCAP LOOP(BD,TM_PP(R,T)$((M(T)<=REG_BDNCAP(R,BD))$REG_BDNCAP(R,BD))=NO);"""
    if db.ctl.get("FIXBOH") is not None:
        fb = db.ctl["FIXBOH"]
        db.remove("TM_PP", where=f"v_M(y) <= (case when v_REG_FIXT(r) = 0 then {fb!r} else v_REG_FIXT(r) end)")
    if "REG_BDNCAP" in db.sym and db.card("REG_BDNCAP"):
        db.remove("TM_PP", where="""exists (select 1 from REG_BDNCAP b where b.r = TM_PP.r and b.value <> 0
                                             and v_M(TM_PP.y) <= b.value)""")


def presolve(db: DB, B: _Bounds, nlp):
    """presolve.mlf: the coefficients of the linearised model (the CES functions in steps, the logarithm of the
    utility in steps) from the prices and levels of the calibration's solution."""
    for name, kind, dom in PRESOLVE_DECL:
        db.declare(name, kind, dom)
    s = db.s
    per, tb = _milestones(db)
    mr = [r for (r,) in _set(db, "MR")]
    regs = [r for (r,) in _set(db, "REG")]
    M = {y: v for (y,), v in _par(db, "M").items()}
    BDSIG = {l: v for (l,), v in _par(db, "BDSIG").items()}
    bdneq = [l for (l,) in _set(db, "BDNEQ")]
    tm_dm = set(_set(db, "TM_DM"))
    tm_pp = set(_set(db, "TM_PP"))
    dv = {u: v for (u,), v in _par(db, "TM_DEFVAL").items()}
    g = lambda d, *k: d.get(k, 0.0)
    L = lambda name: nlp.get(name, {})
    # --- Reset demand indicators:  OPTION CLEAR=DM; DM(C)$=SUM(TM_DM(MR,C),1);
    _assign_ordered(db, "DM", "select distinct c from TM_DM where in_MR(r)")
    dm = [c for (c,) in _set(db, "DM")]
    AEEIFAC, DFACT, PAR_Y = _par(db, "TM_AEEIFAC"), _par(db, "TM_DFACT"), _par(db, "PAR_Y")
    nrg = s.get("TM_SCALE_NRG", 0.0)
    MAG = [c for (c,) in _set(db, "MAG")]
    # --- TM_BASEPRI(MR,T,MAG(C))= ABS(EQ_DD.M(MR,T,C)*TM_AEEIFAC(MR,T,C)/TM_SCALE_NRG)/TM_DFACT(MR,T);
    #     TM_BASEPRI(MR,T,'LAB') = ABS(EQ_LABOR.M(MR,T))/TM_DFACT(MR,T);
    #     TM_BASEPRI(MR,T,'KN')  = ABS(EQ_KNCAP.M(MR,T))/TM_DFACT(MR,T);
    #     TM_BASEPRI(MR,T,'AKL') = ABS(EQ_AKL.M(MR,T))/TM_DFACT(MR,T);
    #     TM_BASEPRI(MR,T,'YN')  = ABS(EQ_PROD_Y.M(MR,T))/TM_DFACT(MR,T);
    #     TM_BASELEV(MR,T,MAG)   = VAR_D.L(MR,T,MAG);  TM_BASELEV(MR,T,'YN') = PAR_Y(MR,T);  TM_BASELEV(MR,T,'CON') = VAR_C.L(MR,T);
    BASEPRI, BASELEV = {}, {}
    for r in mr:
        for t in per:
            for c in MAG:
                BASEPRI[(r, t, c)] = abs(g(L("EQ_DD.M"), r, t, c) * g(AEEIFAC, r, t, c) / nrg) / g(DFACT, r, t)
            for c, eq in (("LAB", "EQ_LABOR.M"), ("KN", "EQ_KNCAP.M"), ("AKL", "EQ_AKL.M"), ("YN", "EQ_PROD_Y.M")):
                BASEPRI[(r, t, c)] = abs(g(L(eq), r, t)) / g(DFACT, r, t)
            for c in MAG:
                BASELEV[(r, t, c)] = g(L("VAR_D.L"), r, t, c)
            BASELEV[(r, t, "YN")] = g(PAR_Y, r, t)
            BASELEV[(r, t, "CON")] = g(L("VAR_C.L"), r, t)
    # --- TM_DMAS('AKL','KN')=YES; TM_DMAS('AKL','LAB')=YES; TM_DMAS('YN','AKL')=YES; TM_DMAS('YN','ACT')=YES;
    DMAS = [("AKL", "KN"), ("AKL", "LAB"), ("YN", "AKL"), ("YN", "ACT")]
    CES = ["AKL", "YN"]                                     # SET TM_CES(CG) / AKL, YN /;
    members = lambda cg: [c1 for c0, c1 in DMAS if c0 == cg]
    PREF, QREF, CESLEV, AGG, SHAR, CIE = {}, {}, {}, {}, {}, {}
    for r in mr:
        for t in per:
            # --- TM_PREF(MR(R),T,CG) $= TM_BASEPRI(R,T,CG);
            for (r2, t2, c), v in BASEPRI.items():
                if (r2, t2) == (r, t) and v:
                    PREF[(r, t, c)] = v
            for cg in CES:
                # --- TM_CESLEV(MR(R),T,TM_CES(CG)) = SUM(TM_DMAS(CG,CG1),TM_BASELEV(R,T,CG1));
                CESLEV[(r, t, cg)] = _sum(g(BASELEV, r, t, c1) for c1 in members(cg))
            # --- TM_PREF(MR(R),T,TM_CES(CG)) = SUM(TM_DMAS(CG,CG1),TM_BASELEV(R,T,CG1)*TM_PREF(R,T,CG1))/TM_CESLEV(R,T,CG);
            #     (the right-hand side is that of TM_PREF before the statement: TM_PREF(YN) takes TM_PREF(AKL) of the line above)
            new = {cg: _sum(g(BASELEV, r, t, c1) * g(PREF, r, t, c1) for c1 in members(cg)) / CESLEV[(r, t, cg)] for cg in CES}
            for cg in CES:
                PREF[(r, t, cg)] = new[cg]
            for cg in CES:
                # --- TM_AGG(MR(R),T,CG1,TM_CES(CG))$TM_DMAS(CG,CG1)=1+(TM_BASEPRI(R,T,CG1)/TM_PREF(R,T,CG)-1)$TM_PREF(R,T,CG);
                for c1 in members(cg):
                    pr = g(PREF, r, t, cg)
                    AGG[(r, t, c1, cg)] = 1 + ((g(BASEPRI, r, t, c1) / pr - 1) if pr else 0.0)
                # --- Normalize TM_AGG
                #     TM_QREF(MR(R),T,TM_CES(CG)) = SUM(TM_DMAS(CG,CG1),TM_AGG(R,T,CG1,CG)*TM_BASELEV(R,T,CG1));
                QREF[(r, t, cg)] = _sum(g(AGG, r, t, c1, cg) * g(BASELEV, r, t, c1) for c1 in members(cg))
                #     TM_AGG(MR(R),T,CG1,TM_CES(CG))$TM_AGG(R,T,CG1,CG)=TM_AGG(R,T,CG1,CG)*TM_CESLEV(R,T,CG)/TM_QREF(R,T,CG);
                for c1 in members(cg):
                    if g(AGG, r, t, c1, cg):
                        AGG[(r, t, c1, cg)] = AGG[(r, t, c1, cg)] * CESLEV[(r, t, cg)] / QREF[(r, t, cg)]
            # --- Reset QREF and determine shares
            #     TM_QREF(MR(R),T,CG) $= TM_BASELEV(R,T,CG);
            for (r2, t2, c), v in BASELEV.items():
                if (r2, t2) == (r, t) and v:
                    QREF[(r, t, c)] = v
            for cg, c1 in DMAS:
                # TM_SHAR(MR(R),T,CG,CG1)$TM_DMAS(CG,CG1) = TM_BASELEV(R,T,CG1) / TM_CESLEV(R,T,CG);
                SHAR[(r, t, cg, c1)] = g(BASELEV, r, t, c1) / CESLEV[(r, t, cg)]
            for cg in CES:
                # TM_CIE(MR(R),T,TM_CES(CG))$TM_CESLEV(R,T,CG)= TM_QREF(R,T,CG) / TM_CESLEV(R,T,CG);
                if CESLEV[(r, t, cg)]:
                    CIE[(r, t, cg)] = g(QREF, r, t, cg) / CESLEV[(r, t, cg)]
            # --- Reverse RD_SHAR for CES aggregation
            #     TM_SHAR(MR(R),T,CG1,CG)$TM_AGG(R,T,CG1,CG)=TM_AGG(R,T,CG1,CG)*TM_PREF(R,T,CG);
            for cg, c1 in DMAS:
                if g(AGG, r, t, c1, cg):
                    SHAR[(r, t, c1, cg)] = AGG[(r, t, c1, cg)] * g(PREF, r, t, cg)
    # (TM_CIE keeps the demands' records of the calibration: equ_ext.mlf assigns them only with NONLP=NL)
    CIE = {**_par(db, "TM_CIE"), **CIE}
    # --- Prepare elasticity steps
    #     LOOP(TM_DMAS(CG,CG1),Z=TM_DEFVAL('MACVOC');
    #      TM_STEP(R,CG1,BDNEQ)=TM_DEFVAL('MACSTEP');
    #      TM_VOC(MR(R),T,CG1,BDNEQ)=MIN(Z,Z/2+(M(T)-MIYR_V1)*0.01);
    #      TM_RCJ(MR(R),CG1,J,BDNEQ)$(ORD(J)<=TM_STEP(R,CG1,BDNEQ))=YES);
    STEP, VOC = _par(db, "TM_STEP"), _par(db, "TM_VOC")
    given_eps = {n: {k for k, v in P.items() if v == 0} for n, P in (("TM_STEP", STEP), ("TM_VOC", VOC))}   # EPS inputs
    RCJ = set()
    jmax = int(db.q1("select max(cast(j as integer)) from J") or 0)
    miyr = s["MIYR_V1"]
    for cg, c1 in DMAS:
        z = dv.get("MACVOC", 0.0)
        for r in regs:
            for bd in bdneq:
                STEP[(r, c1, bd)] = dv.get("MACSTEP", 0.0)
        for r in mr:
            for t in per:
                for bd in bdneq:
                    VOC[(r, t, c1, bd)] = min(z, z / 2 + (M[t] - miyr) * 0.01)
            for bd in bdneq:
                for j in range(1, min(jmax, math.floor(g(STEP, r, c1, bd))) + 1):
                    RCJ.add((r, c1, j, bd))
    AGC = {}
    ESUB, DESUB = _par(db, "TM_ESUB"), _par(db, "TM_DESUB")
    for r in mr:
        for t in per:
            for cg, c1 in DMAS:
                for bd in bdneq:
                    voc = g(VOC, r, t, c1, bd)
                    if not voc > 0:
                        continue
                    sg, st = BDSIG[bd], g(STEP, r, c1, bd)
                    for j in range(1, jmax + 1):
                        if (r, c1, j, bd) not in RCJ:
                            continue
                        if cg == "AKL":
                            # --- Cobb-Douglas function
                            # TM_AGC(MR(R),T,CG('AKL'),CG1,J,BD)$((TM_VOC(R,T,CG1,BD)>0)$TM_RCJ(R,CG1,J,BD)$TM_DMAS(CG,CG1)) = -BDSIG(BD)*
                            #   LOG(1-BDSIG(BD)*ORD(J)*TM_VOC(R,T,CG1,BD)/TM_STEP(R,CG1,BD))/(ORD(J)*TM_VOC(R,T,CG1,BD)/TM_STEP(R,CG1,BD));
                            AGC[(r, t, cg, c1, j, bd)] = -sg * math.log(1 - sg * j * voc / st) / (j * voc / st)
                        else:
                            # --- CES Production function
                            # TM_AGC(MR(R),T,CG('YN'),CG1,J,BD)$(...) = BDSIG(BD)*
                            #   (1-(1-BDSIG(BD)*ORD(J)*TM_VOC(R,T,CG1,BD)/TM_STEP(R,CG1,BD))**(1-1/TM_ESUB(R)))
                            #   /(ORD(J)*TM_VOC(R,T,CG1,BD)/TM_STEP(R,CG1,BD))/(1-1/TM_ESUB(R));
                            e = 1 - 1 / g(ESUB, r)
                            AGC[(r, t, cg, c1, j, bd)] = sg * (1 - _pow(1 - sg * j * voc / st, e)) / (j * voc / st) / e
    # --- Restore PREF to BASEPRI:  TM_PREF(MR(R),T,CG) $= TM_BASEPRI(R,T,CG);
    for k, v in BASEPRI.items():
        if v:
            PREF[k] = v
    # --- Calculate demand parameters
    #     TM_PREF(MR(R),T,C)$TM_DM(R,C) = DDF_PREF(R,T,C);
    #     TM_QREF(MR(R),T,C)$TM_DM(R,C) = COM_PROJ(R,T,C);
    #     TM_AGG(MR(R),T,DM(C),CG('ACT')) = TM_PREF(R,T,C)/TM_DMC(R,T,CG);
    #     TM_SHAR(MR(R),T,CG('ACT'),C)$TM_DM(R,C) = TM_QREF(R,T,C) / TM_DEM(R,T,CG);
    #     TM_SHAR(MR(R),T,C,CG('ACT'))$TM_DM(R,C) = TM_AGG(R,T,C,CG)*TM_DMC(R,T,CG);
    DDF_PREF, PROJ, DMC, TDEM = _par(db, "DDF_PREF"), _par(db, "COM_PROJ"), _par(db, "TM_DMC"), _par(db, "TM_DEM")
    for r in mr:
        for t in per:
            for c in dm:
                if (r, c) in tm_dm:
                    PREF[(r, t, c)] = g(DDF_PREF, r, t, c)
                    QREF[(r, t, c)] = g(PROJ, r, t, c)
            for c in dm:
                AGG[(r, t, c, "ACT")] = g(PREF, r, t, c) / g(DMC, r, t, "ACT")
            for c in dm:
                if (r, c) in tm_dm:
                    SHAR[(r, t, "ACT", c)] = g(QREF, r, t, c) / g(TDEM, r, t, "ACT")
                    SHAR[(r, t, c, "ACT")] = g(AGG, r, t, c, "ACT") * g(DMC, r, t, "ACT")
    # --- Prepare elasticity steps
    #     Z=SMIN(PP(T),M(T));
    #     TM_STEP(TM_DM(RC),BDNEQ(BD))$(NOT TM_STEP(RC,BD))=55-5*BDSIG(BD);
    #     TM_VOC(MR(R),T,C,'LO')$((NOT TM_VOC(R,T,C,'LO'))$TM_DM(R,C)) = MIN(0.45,0.15+(M(T)-Z)*.015);
    #     TM_VOC(MR(R),T,C,'UP')$((NOT TM_VOC(R,T,C,'UP'))$TM_DM(R,C)) = 0.3/(1-TM_VOC(R,T,C,'LO'))+TM_VOC(R,T,C,'LO')-0.3;
    #     TM_RCJ(TM_DM(MR,C),J,BDNEQ(BD))$(ORD(J)<=TM_STEP(MR,C,BD)) = YES;
    z = min(M[y] for (y,) in _set(db, "PP"))
    for (r, c) in sorted(tm_dm):
        for bd in bdneq:
            if (r, c, bd) not in STEP:
                STEP[(r, c, bd)] = 55 - 5 * BDSIG[bd]
    for r in mr:
        for t in per:
            for c in dm:
                if (r, c) in tm_dm and (r, t, c, "LO") not in VOC:
                    VOC[(r, t, c, "LO")] = min(0.45, 0.15 + (M[t] - z) * .015)
            for c in dm:
                if (r, c) in tm_dm and (r, t, c, "UP") not in VOC:
                    VOC[(r, t, c, "UP")] = 0.3 / (1 - g(VOC, r, t, c, "LO")) + g(VOC, r, t, c, "LO") - 0.3
    for (r, c) in tm_dm:
        if r in mr:
            for bd in bdneq:
                for j in range(1, min(jmax, math.floor(g(STEP, r, c, bd))) + 1):
                    RCJ.add((r, c, j, bd))
    # --- Demand CES aggregation
    #     TM_AGC(MR(R),T,CG('ACT'),C,J,BD)$((TM_VOC(R,T,C,BD)>0)$TM_RCJ(R,C,J,BD)$TM_DM(R,C)) = BDSIG(BD)*
    #       (1-(1-BDSIG(BD)*ORD(J)*TM_VOC(R,T,C,BD)/TM_STEP(R,C,BD))**(1-1/TM_DESUB(R)))/(ORD(J)*TM_VOC(R,T,C,BD)/TM_STEP(R,C,BD))/(1-1/TM_DESUB(R));
    for r in mr:
        e = 1 - 1 / g(DESUB, r) if g(DESUB, r) else 0.0
        for t in per:
            for c in dm:
                if (r, c) not in tm_dm:
                    continue
                for bd in bdneq:
                    voc = g(VOC, r, t, c, bd)
                    if not voc > 0:
                        continue
                    sg, st = BDSIG[bd], g(STEP, r, c, bd)
                    for j in range(1, jmax + 1):
                        if (r, c, j, bd) in RCJ:
                            AGC[(r, t, "ACT", c, j, bd)] = sg * (1 - _pow(1 - sg * j * voc / st, e)) / (j * voc / st) / e
    # --- Logarithmic utility from consumption
    #     Z=TM_DEFVAL('LOGSTEP');
    #     LOGJ(J,BDNEQ(BD))$(ORD(J)<=ROUND(Z/2)) = YES;
    #     TM_MIDCON(R,T) = TM_BASELEV(R,T,'CON')*0.5*SQRT(EXP(LOG(2)*1.1));
    #     TM_LOGJOT=LOG(2)/ROUND(Z/1.1);
    #     TM_LOGVAL(LOGJ(J,BDNEQ(BD))) = (1-EXP(-BDSIG(BD)*ORD(J)*TM_LOGJOT))/(TM_LOGJOT*ORD(J));
    #     TM_LSC=ROUND(Z**.7,-1);
    z = dv.get("LOGSTEP", 0.0)
    logj = [(j, bd) for j in range(1, jmax + 1) if j <= _gams_round(z / 2) for bd in bdneq]
    MIDCON = {(r, t): g(BASELEV, r, t, "CON") * 0.5 * math.sqrt(math.exp(math.log(2) * 1.1)) for r in regs for t in per}
    jot = math.log(2) / _gams_round(z / 1.1)
    LOGVAL = {(j, bd): (1 - math.exp(-BDSIG[bd] * j * jot)) / (jot * j) for j, bd in logj}
    s["TM_LOGJOT"] = jot
    s["TM_LSC"] = _gams_round(_pow(z, .7), -1)
    # --- the parameters and sets of presolve.mlf
    for name, d in (("TM_BASEPRI", BASEPRI), ("TM_BASELEV", BASELEV), ("TM_PREF", PREF), ("TM_QREF", QREF),
                    ("TM_CESLEV", CESLEV), ("TM_AGG", AGG), ("TM_SHAR", SHAR), ("TM_CIE", CIE), ("TM_STEP", STEP),
                    ("TM_VOC", VOC), ("TM_AGC", AGC), ("TM_MIDCON", MIDCON)):
        _store(db, name, d, given_eps.get(name, ()))
    _store(db, "TM_LOGVAL", {(str(j), bd): v for (j, bd), v in LOGVAL.items()})
    db.clear("TM_DMAS", "TM_CES", "TM_RCJ", "LOGJ")
    db.insert_rows('"TM_DMAS"', DMAS)
    db.insert_rows('"TM_CES"', [(c,) for c in CES])
    db.insert_rows('"TM_RCJ"', sorted((r, c, str(j), bd) for (r, c, j, bd) in RCJ))
    db.insert_rows('"LOGJ"', [(str(j), bd) for j, bd in logj])
    # --- Reset bounds
    #     VAR_K.UP(MR,T) = INF;  VAR_K.LO(MR,T) = 0;
    #     VAR_D.UP(MR,T,MAG) = INF;  VAR_D.LO(MR,T,MAG) = 0;
    #     VAR_D.FX(MR,T,'LAB') = TM_L(MR,T);
    #     VAR_C.UP(MR(R),T)$(NOT TM_PP(R,T)) = VAR_C.L(R,T);
    TL = _par(db, "TM_L")
    for r in mr:
        for t in per:
            B.up("VAR_K", (r, t), INF)
            B.lo("VAR_K", (r, t), 0.0)
            for c in MAG:
                B.up("VAR_D", (r, t, c), INF)
                B.lo("VAR_D", (r, t, c), 0.0)
            B.fx("VAR_D", (r, t, "LAB"), g(TL, r, t))
            if (r, t) not in tm_pp:
                B.up("VAR_C", (r, t), g(L("VAR_C.L"), r, t))


def _full_model_bounds(db: DB, B: _Bounds, nlp):
    """equ_ext.mlf 168-177: the bounds of the full model and the utility weights of the regions without MACRO"""
    per, tb = _milestones(db)
    mr = [r for (r,) in _set(db, "MR")]
    tm_dm, tm_pp = set(_set(db, "TM_DM")), set(_set(db, "TM_PP"))
    PROJ, TDEM, ANNC, AMP, HDF = _par(db, "COM_PROJ"), _par(db, "TM_DEM"), _par(db, "TM_ANNC"), _par(db, "TM_AMP"), _par(db, "TM_HDF")
    g = lambda d, *k: d.get(k, 0.0)
    L = lambda name: nlp.get(name, {})
    # --- VAR_DEM.FX(R,T,C)$((NOT TM_DM(R,C)$MR(R))$DEM(R,C))=COM_PROJ(R,T,C);
    for (r, c) in _set(db, "DEM"):
        if not ((r, c) in tm_dm and r in mr):
            for t in per:
                B.fx("VAR_DEM", (r, t, c), g(PROJ, r, t, c))
    for r in mr:
        # --- VAR_DEM.FX(MR(R),T(TB),C)$TM_DM(R,C) = TM_DEM(R,T,C);
        for (r2, c) in sorted(tm_dm):
            if r2 == r:
                B.fx("VAR_DEM", (r, tb, c), g(TDEM, r, tb, c))
        for t in per:
            # --- VAR_EC.UP(MR,T) = INF;
            #     VAR_EC.LO(MR(R),T) = ((TM_ANNC(R,T) + TM_AMP(R,T))/TM_HDF(R,T))$(NOT TM_PP(R,T));
            #     VAR_INV.FX(MR(R),T)$(NOT TM_PP(R,T)) = VAR_INV.L(R,T);
            B.up("VAR_EC", (r, t), INF)
            B.lo("VAR_EC", (r, t), 0.0 if (r, t) in tm_pp else (g(ANNC, r, t) + g(AMP, r, t)) / g(HDF, r, t))
            if (r, t) not in tm_pp:
                B.fx("VAR_INV", (r, t), g(L("VAR_INV.L"), r, t))
    # --- Treat non-MR regions gracefully
    #     IF(CARD(MR),Z=SUM(TB(T-1),SMAX(MR,EQ_ESCOST.M(MR,T)/COEF_PVT(MR,T))); ELSE Z=0.5);
    #     TM_UDF(R,T) = COEF_PVT(R,T)*Z;
    PVT = _par(db, "COEF_PVT")
    if mr:
        t2 = per[1] if len(per) > 1 else None
        z = max(g(L("EQ_ESCOST.M"), r, t2) / g(PVT, r, t2) for r in mr) if t2 else 0.0
    else:
        z = 0.5
    _store(db, "TM_UDF", {(r, t): g(PVT, r, t) * z for (r,) in _set(db, "REG") for t in per})


def _sum(xs):
    """SUM in GAMS's order of the members (left to right)"""
    t = 0.0
    for x in xs:
        t += x
    return t


def _pow(x, y):
    """x ** y of GAMS: exp(y*log(x)) (not the C library's pow, which differs in the last bit on some values)"""
    return math.exp(y * math.log(x)) if x > 0 else (0.0 if x == 0 and y > 0 else math.pow(x, y))
