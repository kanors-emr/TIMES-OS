# SPDX-License-Identifier: GPL-3.0-or-later
"""Elastic demands (TIMESED): the base prices of an earlier run, and the data of the demand steps.

    $SET TIMESED YES       the base prices of com_bprice (the run folder), written by the last run with TIMESED NO
    $SET TIMESED <name>    those of <GDXPATH><name>_DP (or <name>): the run <name>, as Veda writes it
    $SET TIMESED NO        no elastic demands; this run's prices are written for later runs (wrtbprice.mod)

With the base prices loaded, TIMES runs with TIMESED YES: each demand with an elasticity COM_ELAST, a variation
COM_VOC and a number of steps COM_STEP can move away from its projection in steps (VAR_ELAST), at the cost of the
consumer surplus lost (EQ_OBJELS), which the objective adds (eqobj.mod).

maindrv.mod 25-29:
    $IFI %MICRO%%TIMESED%==YES0 $SET TIMESED YES
    $IFI %MACRO%==YES $SET MACRO 'YES' SET TIMESED 0
    $IFI NOT %TIMESED%==NO
    $IF NOT %TIMESED%==0 $BATINCLUDE readbprice.mod
"""
import os
from ..engine import DB
from ..controls import given, unsupported
from .. import refpoint


def readbprice(db: DB):
    """readbprice.mod: SOL_BPRICE of the earlier run into COM_BPRICE of the demands; TIMESED becomes YES.

    readbprice.mod 12-27:
        $SET TMP com_bprice
        $IFI %TIMESED%==YES $GOTO LOAD
        $SETLOCAL TMP %GDXPATH%%TIMESED%
        $IF EXIST %TMP%_DP.gdx $SETLOCAL TMP %TMP%_DP
        $IF NOT EXIST %TMP%.gdx $DROPLOCAL TMP
        $LABEL LOAD
        $GDXIN %TMP%
        $IF NOT ERRORFREE $GOTO FINISH
        $LOAD sol_bprice
        $IF NOT ERRORFREE $GOTO FINISH
        $SETGLOBAL MX %MX% SET TIMESED 'YES'
    (a name with neither file falls back to com_bprice; when no file loads, $CLEARERROR: the run goes on without
    elastic demands, and writes its own prices at the end, as with NO)."""
    ed = given(db.env, "TIMESED")
    db.ctl["TIMESED"] = False
    if ed.upper() in ("", "NO", "0"):
        return
    folder = refpoint.run_folder(db)
    # readbprice.mod 13-16: $SET TMP com_bprice;  $IFI %TIMESED%==YES $GOTO LOAD;  $SETLOCAL TMP %GDXPATH%%TIMESED%;
    #   $IF EXIST %TMP%_DP.gdx $SETLOCAL TMP %TMP%_DP;  $IF NOT EXIST %TMP%.gdx $DROPLOCAL TMP   (back to com_bprice)
    cands = []
    if ed.upper() != "YES":
        cands = [refpoint.locate(folder, ed + "_DP"), refpoint.locate(folder, ed)]
    cands.append(refpoint.locate(folder, "com_bprice", in_gdxpath=False))
    path, looked = refpoint.find(cands)
    mlf = given(db.env, "MACRO").upper() == "MLF"
    if path is None:
        db.base_prices_from = None
        if mlf:
            # readbprice.mod 48: $IFI NOT %MACRO%==MLF $CLEARERROR   (with MLF the failed load stops the run)
            unsupported(db, f"MACRO MLF without the base prices of a reference run (TIMESED {ed}): none found. Looked "
                            f"for: {'; '.join(looked)}. TIMES needs them for MLF; a run of this implementation writes "
                            "them (com_bprice.parquet, <run>_DP.parquet) when it solves with TIMESED NO; --points "
                            "<folder> says where they are")
            return
        db.base_prices_note = (f"TIMESED {ed}: no base prices found (looked for: {'; '.join(looked)}): the demands "
                               "are not elastic (readbprice.mod: $CLEARERROR)")
        return
    got = refpoint.read(path, ["SOL_BPRICE", "SOL_ACFR"])
    sol = got.get("SOL_BPRICE", ("parameter", []))[1]
    db.base_prices_from = path
    refpoint.note_read(db, path, f"TIMESED {ed}: the base prices of the demands (readbprice.mod)")
    db.ctl["TIMESED"] = True
    db.env["TIMESED"] = "YES"
    # readbprice.mod 20: $IFI %MACRO%==MLF $SET MX SET MACRO 'Yes'  (the MLF equations: mod_equa.tm 34)
    # readbprice.mod 26: $IFI %MACRO%==MLF $LOAD SOL_ACFR   (the annual cost shares; DAM_COEF, DAM_TVOC: refused)
    db.ctl["MLF"] = mlf
    if mlf:
        acfr = got.get("SOL_ACFR", ("parameter", []))[1]
        db.declare("SOL_ACFR", "par", ["R", "UC_COST", "T"])
        db.clear("SOL_ACFR")
        db.insert_rows("SOL_ACFR", sorted((r.upper(), u.upper(), y.upper(), float(v)) for r, u, y, v, _ in acfr))
        if not acfr:
            db.base_prices_note = (f"MACRO MLF: the reference {os.path.basename(path)} has no SOL_ACFR (its run did not "
                                   "set ANNCOST LEV): the annual costs of MACRO are 0 (TM_ANNC, ppm_ext.mlf 33)")
    U = str.upper
    sol = [(U(r), U(y), U(c), U(s), U(cur), float(v)) for r, y, c, s, cur, v, _ in sol]
    # --- OPTION DEM < COM_PROJ;  DEM(R,C)$COM_TMAP(R,'DEM',C) = YES;   (the input as given, before interpolation)
    dem = {(U(r), U(c)) for r, c in db.q("select distinct r, c from COM_PROJ")}
    if "COM_TMAP" in db.sym:
        cm = db.cols("COM_TMAP")
        dem |= {(U(r), U(c)) for r, c in db.q(f"select distinct {cm[0]}, {cm[2]} from COM_TMAP where upper({cm[1]}) = 'DEM'")}
    # --- Fill in missing tail milestoneyrs to reduce abruption
    #     OPTION FORWARD < SOL_BPRICE; FIL(T) = PROD(FORWARD(TT),ORD(TT)<ORD(T));
    #     LOOP(FIL(TT(T+1)),COM_BPRICE(R,TT,C,S,CUR) $= SOL_BPRICE(R,T,C,S,CUR));
    #     COM_BPRICE(R,T,C,S,CUR)$DEM(R,C) $= SOL_BPRICE(R,T,C,S,CUR);
    T = [U(y) for (y,) in db.q("select y from MILESTONYR order by try_cast(y as double)")]
    years = {y for _, y, *_ in sol}
    fwd = [i for i, t in enumerate(T) if t in years]
    fil = [i for i in range(len(T)) if all(j < i for j in fwd)]
    by_year = {}
    for row in sol:
        by_year.setdefault(row[1], []).append(row)
    new = {}
    for i in fil:
        if i == 0:
            continue
        for r, _, c, s, cur, v in by_year.get(T[i - 1], []):
            new[(r, T[i], c, s, cur)] = v                     # ($=: a price of 0 is EPS, and is assigned)
    for r, y, c, s, cur, v in sol:
        if y in T and (r, c) in dem:
            new[(r, y, c, s, cur)] = v
    # SOL_BPRICE itself (readbprice.mod 8: PARAMETER SOL_BPRICE(R,YEAR,C,TS,CUR)), read again by pp_micro.mod (DDF_PREF);
    # and FORWARD, which OPTION FORWARD < SOL_BPRICE leaves set to the years of the prices (solve.stp clears it)
    db.declare("SOL_BPRICE", "par", ["R", "YEAR", "C", "TS", "CUR"])
    db.clear("SOL_BPRICE")
    db.insert_rows("SOL_BPRICE", sorted(sol))
    db.clear("FORWARD")
    db.insert_rows("FORWARD", sorted({(y,) for y in years}))
    cols = db.cols("COM_BPRICE")
    db.x('create or replace temp table t_bp as select * from "COM_BPRICE" limit 0')
    db.insert_rows("t_bp", [k + (v,) for k, v in sorted(new.items())])
    db.put("COM_BPRICE", f"select {', '.join(cols)}, value from t_bp", zero="eps")


def micro_pre(db: DB):
    """pp_micro.mod PRE (ppmain.mod 749, with TIMESED YES), for demands without aggregation:

        OPTION MI_DMAS<COM_AGG, OBJ_PVT<SOL_BPRICE;
        RD_AGG(RC(R,C))$(DEM(RC)+COM_TMAP(R,'DEM',C))=YES;
        MI_DMAS(R,C,COM)$(NOT RD_AGG(R,C)*RD_AGG(R,COM)*COM_TSL(R,C,'ANNUAL'))=NO;
        MI_DMAS(R,C,COM)$SUM(RPC(RP_FLO(R,P),C),1)=NO;
        OPTION RD_AGG<=MI_DMAS; RD_AGG(DEM)=NO; ...
        COM_ELAST(RTC,S,BDNEQ)$(NOT COM_ELAST(RTC,S,BDNEQ)) $= COM_ELAST(RTC,S,'FX');
        DDF_QREF(R,T,C) $= COM_PROJ(R,T,C);
    Demands aggregated into other demands (CES aggregation: COM_AGG between demands, MI_DMAS) are not supported."""
    cm = db.cols("COM_TMAP")
    db.x(f"""create or replace temp table t_rdagg as select distinct r, c from RC k
             where in_DEM(k.r,k.c) or exists(select 1 from COM_TMAP m where m.{cm[0]}=k.r and m.{cm[2]}=k.c and upper(m.{cm[1]})='DEM')""")
    ca = db.cols("COM_AGG")
    agg = db.q(f"""select distinct a.{ca[0]}, a.{ca[2]}, a.{ca[3]} from COM_AGG a
                   where exists(select 1 from t_rdagg x where x.r=a.{ca[0]} and x.c=a.{ca[2]})
                     and exists(select 1 from t_rdagg x where x.r=a.{ca[0]} and x.c=a.{ca[3]})
                     and in_COM_TSL(a.{ca[0]},a.{ca[2]},'ANNUAL')
                     and not exists(select 1 from RPC p where p.r=a.{ca[0]} and p.c=a.{ca[2]} and in_RP_FLO(p.r,p.p))""")
    if agg:
        unsupported(db, "elastic demands aggregated into other demands (CES demand aggregation with TIMESED: COM_AGG between "
                        "demands, pp_micro.mod)", {"COM_AGG": len(agg)})
    # --- COM_ELAST(RTC,S,BDNEQ)$(NOT COM_ELAST(RTC,S,BDNEQ)) $= COM_ELAST(RTC,S,'FX');

    db.x("""insert into COM_ELAST select a.r, a.y, a.c, a.s, b.l, a.value from COM_ELAST a, BDNEQ b
            where a.l = 'FX' and in_RTC(a.r,a.y,a.c) and not in_COM_ELAST(a.r,a.y,a.c,a.s,b.l)""")
    # --- DDF_PREF(R,T,C)$DEM(R,C) = SUM((COM_TS(R,C,S),RDCUR(R,CUR)),SOL_BPRICE(R,T,C,S,CUR)*COM_FR(R,T,C,S));
    #     (read only by the aggregation, which is refused; kept as TIMES has it)
    db.declare("DDF_PREF", "par", ["R", "T", "C"])
    db.put("DDF_PREF", """select d.r, t.y, d.c, sum(b.value * v_COM_FR(d.r, t.y, d.c, k.s) order by k.s, c.cur) as value
                          from DEM d join MILESTONYR t on true join COM_TS k on k.r = d.r and k.c = d.c join RDCUR c on c.r = d.r
                          join SOL_BPRICE b on b.r = d.r and b.y = t.y and b.c = d.c and b.s = k.s and b.cur = c.cur
                          group by d.r, t.y, d.c""")
    # --- DDF_QREF(R,T,C) $= COM_PROJ(R,T,C);
    db.declare("DDF_QREF", "par", ["R", "T", "C"])
    db.put("DDF_QREF", "select r, y, c, value from COM_PROJ where in_MILESTONYR(y)", zero="skip")


def bnd_elas(db: DB):
    """bndmain.mod 20-21 and bnd_elas.mod (TIMESED YES), without the aggregated demands (MI_DOPE empty):
        %VAR%_ELAST.UP(R,T,C,S,J,BD) = INF;
        %VAR%_ELAST.UP(RTCS_VARC(R,T,C,S),J,BDNEQ(BD))$RCJ(R,C,J,BD) = INF$MI_DOPE(R,T,C) +
          (MAX(DDF_QREF(R,T,C) * COM_FR(R,T,C,S), COM_BQTY(R,C,S)) * COM_VOC(R,T,C,BD)) / COM_STEP(R,C,BD);"""
    db.x('create table if not exists "B_VAR_ELAST" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, d5 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x("""insert into "B_VAR_ELAST" select v.r, v.y, v.c, v.s, j.j, j.bd, 0,
                greatest(v_DDF_QREF(v.r,v.y,v.c) * v_COM_FR(v.r,v.y,v.c,v.s), v_COM_BQTY(v.r,v.c,v.s)) * v_COM_VOC(v.r,v.y,v.c,j.bd)
                  / v_COM_STEP(v.r,v.c,j.bd)
            from RTCS_VARC v join (select r, c, j, l as bd from RCJ where l in ('LO','UP')) j on j.r=v.r and j.c=v.c""")
    db.bounds.add("VAR_ELAST")
    # eqobj.mod 28: SUM_OBJ(R,'OBJELS') = 1$SUM(RCJ(R,C,J,BD),1)   (the regions with elastic demands: EQ_OBJELS, EQ_OBJ)
    db.declare("OBJELS_R", "set", ["R"])
    db.assign("OBJELS_R", "select distinct r from RCJ")
    # eqcombal.mod 67: + SUM(RCJ(R,C,J,BDNEQ(BD))$COM_ELAST(R,T,C,S,BD),BDSIG(BD)*%VAR%_ELAST(R,T,C,S,J,BD))
    db.declare("ELS_BAL", "set", ["R", "T", "C", "S", "J", "BD"])
    db.assign("ELS_BAL", """select e.r, e.y, e.c, e.s, k.j, e.l from COM_ELAST e join RCJ k on k.r=e.r and k.c=e.c and k.l=e.l
                            where e.l in ('LO','UP') and in_MILESTONYR(e.y)""")
    # eqobjels.mod 18-21: the coefficient of VAR_ELAST(R,T,C,S,J,BD) in EQ_OBJELS(R,BD,CUR):
    #   SUM(RTCS_VARC(R,T,C,S)$(COM_ELAST(R,T,C,S,BD)$COM_STEP(R,C,BD)), COEF_PVT(R,T) * COM_BPRICE(R,T,C,S,CUR) *
    #     (SUM(RCJ(R,C,J,BD), %VART%_ELAST(R,T,C,S,J,BD) *
    #       (1-BDSIG(BD)*(ORD(J)-.5)*COM_VOC(R,T,C,BD)/COM_STEP(R,C,BD))**(1/COM_ELAST(R,T,C,S,BD)))$(NOT COM_ELASTX(R,T,C,BD)) ...))$BDNEQ(BD)
    #   (EQ_OBJELS(R,BD,CUR)$(RDCUR(R,CUR)$SUM_OBJ(R,'OBJELS'));  a price given as EPS gives an EPS coefficient)
    db.declare("ELS_COEF", "par", ["R", "T", "C", "S", "J", "BD", "CUR"])
    db.put("ELS_COEF", """select v.r, v.y, v.c, v.s, k.j, e.l, d.cur,
                              v_COEF_PVT(v.r,v.y) * b.value *
                              power(1 - (case when e.l = 'LO' then 1 else -1 end) * (cast(k.j as DOUBLE) - .5) * v_COM_VOC(v.r,v.y,v.c,e.l)
                                        / v_COM_STEP(v.r,v.c,e.l), 1 / e.value) as value
                          from RTCS_VARC v join COM_ELAST e on e.r=v.r and e.y=v.y and e.c=v.c and e.s=v.s
                          join RCJ k on k.r=v.r and k.c=v.c and k.l=e.l
                          join RDCUR d on d.r=v.r
                          join COM_BPRICE b on b.r=v.r and b.y=v.y and b.c=v.c and b.s=v.s and b.cur=d.cur
                          where e.l in ('LO','UP') and v_COM_STEP(v.r,v.c,e.l) <> 0""", zero="eps")

