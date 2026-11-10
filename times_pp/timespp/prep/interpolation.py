# SPDX-License-Identifier: GPL-3.0-or-later
"""preppm.mod: inter-/extrapolation of the input over the years (fillparm.gms / prepparm.gms through interp.py),
currency conversion (curex.gms), retirement controls (prepret.dsc PREP), shape pointers (preshape.gms)."""
from ..engine import DB
from .extensions import _need_empty
from . import extensions, simv, stochastic
from .. import interp


RTP = ("RTP", ("r", "p"))


RVP = ("RVP", ("r", "p"))


def _ire_flo_ctrl(db, cols):
    # '(RVP(R,V,P) OR RTP(REG,V,P))'
    rvp = set(db.q("select r, y, p from RVP")); rtp = set(db.q("select r, y, p from RTP"))
    ir, ip, ir2 = cols.index("r"), cols.index("p"), cols.index("r2")
    return lambda k, y: (k[ir], str(y), k[ip]) in rvp or (k[ir2], str(y), k[ip]) in rtp


_ire_flo_ctrl.kernel_alts = [("RVP", "r", "p"), ("RTP", "r2", "p")]    # the same test for the kernel (interp)


def _stg_chrg_ctrl(db, cols):
    # '(M(V) GE MIYR_V1-1)'
    m = {int(y): v for y, v in db.q("select y, value from M where y <> '0'")}
    lim = db.s["MIYR_V1"] - 1
    return lambda k, y: m.get(y, 0.0) >= lim


_stg_chrg_ctrl.key_free = True              # the same years for every series (the kernel asks it once per year)


CUREX_ATTR = ["NCAP_COST", "NCAP_ITAX", "NCAP_ISUB", "NCAP_DCOST", "NCAP_DLAGC", "NCAP_FOM", "NCAP_FSUB", "NCAP_FTAX", "ACT_COST",
              "FLO_COST", "FLO_DELIV", "FLO_TAX", "FLO_SUB", "NCAP_VALU", "IRE_PRICE", "COM_BPRICE", "COM_CSTNET", "COM_TAXNET",
              "COM_SUBNET", "COM_CSTPRD", "COM_TAXPRD", "COM_SUBPRD", "REG_BNDCST", "REG_CUMCST", "BL_VAROMC", "BL_DELIVC",
              "ACT_CSTUP", "ACT_CSTSD", "ACT_CSTRMP", "ACT_CSTPL"]


CUREX_INPLACE = {"REG_BNDCST", "REG_CUMCST", "BL_VAROMC", "BL_DELIVC", "ACT_CSTUP", "ACT_CSTSD", "ACT_CSTRMP"}


def curex(db: DB):
    """curex.gms : convert cost attributes to the main currency of each region."""
    _need_empty(db, ["DAM_COST", "TL_CT_COST"], "currency conversion of damage / ETL costs")
    # --- R_CUREX(R,CUR,CUR) = 0;
    db.zap("R_CUREX", "in_REG(r) and cur = cur2")
    rate = {(r, a, b): v for r, a, b, v in db.q("select r, cur, cur2, value from R_CUREX where in_REG(r)")}
    rdcur = set(db.q("select r, cur from RDCUR"))
    curs = [c for (c,) in db.q("select cur from CUR")]
    # --- LOOP((R,CURR), IF((SUM(RDCUR(R,CUR)$R_CUREX(R,CURR,CUR),1) EQ 1), CURMAP(RDCUR(R,CUR),CURR)$R_CUREX(R,CURR,CUR) = YES;
    #                    ELSE CURMAP(RDCUR(R,CURR),CURR) = YES));
    curmap = set()                                   # (r, target, source)
    for (r,) in db.q("select r from REG"):
        for curr in curs:
            tg = [c for c in curs if (r, c) in rdcur and (r, curr, c) in rate]
            if len(tg) == 1:
                curmap.add((r, tg[0], curr))
            elif (r, curr) in rdcur:
                curmap.add((r, curr, curr))
    # --- LOOP(CURMAP(R,CUR,CURR)$(NOT SAMEAS(CUR,CURR)), RDCUR(R,CURR) = NO);  R_CUREX(RDCUR(R,CUR),CUR) = 1;
    for r, cur, curr in curmap:
        if cur != curr:
            rdcur.discard((r, curr))
    for r, cur in rdcur:
        rate[(r, cur, cur)] = 1.0
    # --- two-step chained conversion:
    #     LOOP((CURMAP(RDCUR(R,CUR),CURR),CRU)$((NOT RDCUR(R,CURR))$CURMAP(R,CURR,CRU)),RXX(R,CURR,CRU)$(NOT R_CUREX(R,CRU,CUR))=YES);
    rxx = {(r, curr, cru) for r, cur, curr in curmap if (r, cur) in rdcur and (r, curr) not in rdcur
           for r2, c2, cru in curmap if r2 == r and c2 == curr and (r, cru, cur) not in rate}
    # --- LOOP(RXX(R,CURR,CRU),R_CUREX(R,CRU,CUR)$CURMAP(R,CUR,CURR)=R_CUREX(R,CRU,CURR)*R_CUREX(R,CURR,CUR));
    # --- LOOP(RXX(R,CURR,CRU),CURMAP(R,CURR,CRU)=NO; CURMAP(R,CUR,CRU)$CURMAP(R,CUR,CURR)=YES);
    #     (a rate given as 0 under $ONEPS is EPS, a record: EPS times a rate is EPS; a rate not given makes the product 0,
    #     no record)
    for r, curr, cru in sorted(rxx):
        for r2, cur, c3 in list(curmap):
            if r2 == r and c3 == curr:
                a, b = rate.get((r, cru, curr)), rate.get((r, curr, cur))
                if a is None or b is None:
                    rate.pop((r, cru, cur), None)
                else:
                    rate[(r, cru, cur)] = a * b if a and b else 0.0
    for r, curr, cru in sorted(rxx):
        curmap.discard((r, curr, cru))
        for r2, cur, c3 in list(curmap):
            if r2 == r and c3 == curr:
                curmap.add((r, cur, cru))
    db.zap("R_CUREX", "in_REG(r)")
    db.load_rows("R_CUREX", [k + (v,) for k, v in rate.items()])     # (an EPS rate stays: $R_CUREX is true for it)
    db.assign("RDCUR", "select r, cur from RDCUR where false")
    db.load_rows("RDCUR", sorted(rdcur))
    import pandas as pd
    db.con.register("cm_", pd.DataFrame(sorted(curmap), columns=["r", "cur", "curr"]))
    db.x("create or replace temp table CURMAP as select * from cm_")
    db.con.unregister("cm_")
    # --- per attribute (label SUBR):
    #     %1(R,LL..,CUR..)$((%1(R,'0'..,CUR..)<-12)$%1(R,'0'..,CUR..)) = 0;        series filtered out by their option
    #     %2(..) $= %1(..); OPTION CLEAR=%1;                                        (only when a temporary table is used)
    #     %1(R,LL..,CUR..) $= SUM(CURMAP(R,CUR,CURR)$%2(..CURR..),%2(..CURR..)*POWER(R_CUREX(R,CURR,CUR),1$YEARVAL(LL)));
    #     %1(R,LL..,CUR..)$(NOT RDCUR(R,CUR)) = 0;                                  (only when converted in place)
    for n in CUREX_ATTR:
        if n not in db.sym or db.sym[n].kind != "par" or db.card(n) == 0:
            continue
        cols = db.cols(n)
        oth = [c for c in cols if c != "cur"]
        hasy = "y" in cols
        if hasy:
            on = " and ".join(f"o.{c}=a.{c}" for c in cols if c != "y")
            db.x(f'delete from "{n}" a where in_REG(a.r) and exists(select 1 from "{n}" o where {on} and o.y=\'0\' and o.value < -12)')
        pw = "case when a.y='0' then 1 else x.value end" if hasy else "x.value"
        sel = ", ".join(f"a.{c}" if c != "cur" else "m.cur" for c in cols)
        new = f"""select {sel}, sum(a.value * {pw}) as value from "{n}" a
                  join CURMAP m on m.r=a.r and m.curr=a.cur join R_CUREX x on x.r=a.r and x.cur=a.cur and x.cur2=m.cur
                  group by {", ".join(f"a.{c}" for c in oth)}, m.cur"""
        db.x(f"create or replace temp table cx_new as {new}")
        if n in CUREX_INPLACE:
            db.put(n, "select * from cx_new", zero="eps")
            db.zap(n, "in_REG(r) and not in_RDCUR(r,cur)")
        else:
            db.zap(n)
            db.put(n, "select * from cx_new", zero="eps")


def prepret(db: DB):
    """prepret.dsc, label PREP (preppm.mod: $IF SET RETIRE $BATINCLUDE prepret.dsc PREP PRC_RCAP RCAP_BND)."""
    F, P = interp.fillparm, interp.prepparm
    # --- $IF DEFINED PRC_RCAP RCAP_BND(R,'0',P,'N')$(RCAP_BND(R,'0',P,'N')=0)$=PRC_RCAP(R,P);
    db.put("RCAP_BND", "select r, '0' as y, p, 'N' as l, 1 as value from PRC_RCAP where in_REG(r) and v_RCAP_BND(r,'0',p,'N') = 0")
    # --- $IF NOT DEFINED RCAP_BND $EXIT
    if not (db.card("RCAP_BND") or db.card("PRC_REFIT") or db.card("PRC_RCAP")):
        return
    db.s["VNRET"] = 1.0                    # $MACRO VNRET(V,T,P) is defined from here on: retirement variables and equations exist
    # --- OPTION PRC_RCAP < RCAP_BND;
    db.assign("PRC_RCAP", "select distinct r, p from RCAP_BND")
    # --- $BATINCLUDE fillparm RCAP_BLK R 'P' ",'','','','',''" V 'RTP(R,V,P)' '>=0'
    if db.card("RCAP_BLK"):
        F(db, "RCAP_BLK", "V", RTP)
    # --- $BATINCLUDE fillparm RCAP_OCAP R 'P,C' ",'0','0','0','0'" V 'RTP(R,V,P)' '>=0'
    if db.card("RCAP_OCAP"):
        F(db, "RCAP_OCAP", "V", RTP)
    # --- $BATINCLUDE prepparm RCAP_BND R 'P,L' ",'','',''" V 'RTP(R,V,P)' 1
    P(db, "RCAP_BND", "V", RTP, 1)
    # --- $IF DEFINED NCAP_OLIFE $BATINCLUDE fillparm NCAP_OLIFE R P ",'','','','',''" V 'RTP(R,V,P)' '>=0'
    # --- $IF DEFINED NCAP_OLIFE OPTION PRC_CAP < NCAP_ELIFE; NCAP_ELIFE(R,V,P)$(NOT PRC_CAP(R,P)) $= NCAP_OLIFE(R,V,P); PRC_CAP(R,P)=0;
    #     (the operating life is the economic life of a process that has none)
    if db.card("NCAP_OLIFE"):
        F(db, "NCAP_OLIFE", "V", RTP)
        db.put("NCAP_ELIFE", """select o.r, o.y, o.p, o.value from NCAP_OLIFE o
                                where not exists(select 1 from NCAP_ELIFE e where e.r=o.r and e.p=o.p)""", zero="eps")
    # --- LOOP((RP(R,PRC),P)$(RP(R,P)$PRC_REFIT(RP,P)), NCAP_ILED(RTP(R,V,P)) = -ABS(NCAP_ILED(RTP));
    #       PRC_RCAP(RP)=YES; TRACKP(R,P)$(PRC_REFIT(RP,P)<0)=YES);
    db.tmp("t_refit", "select r, p, p2, value from PRC_REFIT where in_RP(r,p) and in_RP(r,p2)")
    db.x("""update NCAP_ILED set value = -abs(value) where in_MODLYEAR(y) and in_RTP(r,y,p)
            and exists(select 1 from t_refit f where f.r=NCAP_ILED.r and f.p2=NCAP_ILED.p)""")
    db.add("PRC_RCAP", "select distinct r, p from t_refit")
    # --- RTP_VARP(RTP(R,T,P)) $= PRC_RCAP(R,P);
    db.add("RTP_VARP", "select r, y, p from RTP where in_MILESTONYR(y) and in_PRC_RCAP(r,p)")
    # --- PRC_RCAP(TRACKP)=YES; OPTION CLEAR=TRACKP;
    db.add("PRC_RCAP", "select distinct r, p2 as p from t_refit where value < 0")
    # --- RCAP_OCAP(RTP(R,V,P),C)$(PRC_RCAP(R,P)->0) = 0;          (flows of retired capacity: retirable processes only)
    db.zap("RCAP_OCAP", "in_RTP(r,y,p) and not in_PRC_RCAP(r,p)")


def year_sets_and_costs(db: DB):
    """preppm.mod up to the interpolation: MODLYEAR, DATAYEAR, DM_YEAR, currency conversion, market shares, commodity
    costs and taxes into OBJ_COMNT / OBJ_COMPD, flow tax and subsidy flags, UC_COM, IE_DEFAULT, prepret.dsc PREP, the
    vintages of RVP (fillvint)."""
    # --- MODLYEAR(LL) = MILESTONYR(LL)+PASTYEAR(LL);
    db.assign("MODLYEAR", "select y from MILESTONYR union select y from PASTYEAR")
    # --- DATAYEAR(PASTYEAR) = YES;  DATAYEAR('%DFLBL%') = YES;
    db.add("DATAYEAR", "select y from PASTYEAR union select '0'")
    # --- DM_YEAR(MILESTONYR) = YES;  DM_YEAR(DATAYEAR) = (YEARVAL(DATAYEAR)>0);
    db.add("DM_YEAR", "select y from MILESTONYR")
    db.remove("DM_YEAR", where="in_DATAYEAR(y) and yv(y) <= 0")
    db.add("DM_YEAR", "select y from DATAYEAR where yv(y) > 0")
    # --- LOOP(T,FIL2(DM_YEAR)$((YEARVAL(DM_YEAR) >= B(T)) * (YEARVAL(DM_YEAR) <= E(T))) = YEARVAL(T));
    db.put("FIL2", "select d.y, yv(t.y) as value from DM_YEAR d, MILESTONYR t where yv(d.y) >= v_B(t.y) and yv(d.y) <= v_E(t.y)")
    # --- MY_FIL(DM_YEAR)$(FIL2(DM_YEAR)*(NOT T(DM_YEAR))) = YES;
    db.add("MY_FIL", "select y from DM_YEAR where in_FIL2(y) and not in_MILESTONYR(y)")
    # --- $IF DEFINED G_CUREX R_CUREX(R,CURR,CUR)$(NOT R_CUREX(R,CURR,CUR))$=G_CUREX(CURR,CUR);  $IF DEFINED R_CUREX $INCLUDE curex
    if db.card("G_CUREX") or db.card("R_CUREX"):
        db.put("R_CUREX", """select g.r, x.cur, x.cur2, x.value from REG g, G_CUREX x
                             where not in_R_CUREX(g.r, x.cur, x.cur2)""", zero="eps")
        curex(db)
    # --- FLO_MARK(R,LL,P,C,BD)$((NOT RPC(R,P,C))$RC(R,C)$FLO_MARK(R,LL,P,C,BD)) = 0;
    db.zap("FLO_MARK", "in_RC(r,c) and not in_RPC(r,p,c)")
    # --- PRC_MARK(R,LL,P,P,C,BD)$((RPC(R,P,C)->(FLO_MARK(R,'0',P,C,BD)>1))$RC(R,C)$PRC_MARK(R,LL,P,P,C,BD)) = 0;
    db.zap("PRC_MARK", """u = p and in_RC(r,c) and (not in_RPC(r,p,c) or exists(select 1 from FLO_MARK f
              where f.r=PRC_MARK.r and f.y='0' and f.p=PRC_MARK.p and f.c=PRC_MARK.c and f.l=PRC_MARK.l and f.value > 1))""")
    # --- Integration of COM costs
    #     OBJ_COMNT(R,DATAYEAR,C,S,'COST',CUR) $= COM_CSTNET(R,DATAYEAR,C,S,CUR);   'TAX' $= COM_TAXNET;   'SUB' $= COM_SUBNET*(-1);
    #     OBJ_COMPD(R,DATAYEAR,C,S,'COST',CUR) $= COM_CSTPRD(R,DATAYEAR,C,S,CUR);   'TAX' $= COM_TAXPRD;   'SUB' $= COM_SUBPRD*(-1);
    for dst, kind, src, sign in (("OBJ_COMNT", "COST", "COM_CSTNET", 1), ("OBJ_COMNT", "TAX", "COM_TAXNET", 1), ("OBJ_COMNT", "SUB", "COM_SUBNET", -1),
                                 ("OBJ_COMPD", "COST", "COM_CSTPRD", 1), ("OBJ_COMPD", "TAX", "COM_TAXPRD", 1), ("OBJ_COMPD", "SUB", "COM_SUBPRD", -1)):
        if db.card(src):
            c = db.cols(dst)                        # r, y, c, s, <cost type>, cur
            db.put(dst, f"""select a.r as {c[0]}, a.y as {c[1]}, a.c as {c[2]}, a.s as {c[3]}, '{kind}' as {c[4]}, a.cur as {c[5]},
                                   a.value * ({sign}) as value from "{src}" a where in_DATAYEAR(a.y)""", zero="eps")
    # --- Prepare flags for flow tax/sub
    #     OPTION RPC_CUR <= FLO_TAX; OBJ_VFLO(RPC_CUR,'TAX') = YES;
    #     OPTION RPC_CUR <= FLO_SUB; OBJ_VFLO(RPC_CUR,'SUB') $= OBJ_VFLO(RPC_CUR,'TAX');
    db.add("OBJ_VFLO", "select distinct r, p, c, cur, 'TAX' as ucn from FLO_TAX where in_REG(r)")
    db.add("OBJ_VFLO", """select distinct r, p, c, cur, 'SUB' as ucn from FLO_SUB
                          where in_REG(r) and in_OBJ_VFLO(r,p,c,cur,'TAX')""")
    db.assign("RPC_CUR", "select distinct r, p, c, cur from FLO_SUB where in_REG(r)")      # what the projection leaves behind
    # --- FLO_TAX(R,LL--ORD(LL),P,C,S,CUR)$((NOT FLO_TAX(R,'%DFLBL%',P,C,S,CUR))$FLO_TAX(R,LL,P,C,S,CUR)$OBJ_VFLO(R,P,C,CUR,'SUB')) = 3;
    #     FLO_SUB(R,LL--ORD(LL),P,C,S,CUR)$((NOT FLO_SUB(R,'%DFLBL%',P,C,S,CUR))$FLO_SUB(R,LL,P,C,S,CUR)$OBJ_VFLO(R,P,C,CUR,'SUB')) = 3;
    #     (a flow with both a tax and a subsidy: both series get interpolation option 3 unless one is given)
    for n in ("FLO_TAX", "FLO_SUB"):
        db.put(n, f"""select distinct a.r, '0' as y, a.p, a.c, a.s, a.cur, 3.0 as value from "{n}" a
                      where in_OBJ_VFLO(a.r,a.p,a.c,a.cur,'SUB') and not in_{n}(a.r,'0',a.p,a.c,a.s,a.cur)""")
    # --- UC_COM(UC_N,'PRD',SIDE,R,DATAYEAR,C,S,'COMPRD')$(NOT UC_ATTR(R,UC_N,SIDE,'COMPRD','NET')) $= UC_COMPRD(UC_N,SIDE,R,DATAYEAR,C,S);
    db.put("UC_COM", """select uc, 'PRD' as cv, side, r, y, c, s, 'COMPRD' as grp, value from UC_COMPRD
                        where in_DATAYEAR(y) and not in_UC_ATTR(r, uc, side, 'COMPRD', 'NET')""", zero="eps")
    # --- UC_COM(UC_N,'NET',SIDE,R,DATAYEAR,C,S,'COMPRD')$UC_ATTR(R,UC_N,SIDE,'COMPRD','NET') $= UC_COMPRD(...)
    db.put("UC_COM", """select uc, 'NET' as cv, side, r, y, c, s, 'COMPRD' as grp, value from UC_COMPRD
                        where in_DATAYEAR(y) and in_UC_ATTR(r, uc, side, 'COMPRD', 'NET')""", zero="eps")
    # --- UC_COM(UC_N,'PRD',SIDE,R,DATAYEAR,C,S,'COMCON')$(NOT UC_ATTR(R,UC_N,SIDE,'COMCON','NET')) $= UC_COMCON(UC_N,SIDE,R,DATAYEAR,C,S);
    #     UC_COM(UC_N,'NET',SIDE,R,DATAYEAR,C,S,'COMCON')$UC_COMCON(UC_N,SIDE,R,DATAYEAR,C,S) = UC_COMCON(..)*(-1);
    #     (consumption = production - net; with the NET attribute only the net term, for a commodity without production)
    db.put("UC_COM", """select uc, 'PRD' as cv, side, r, y, c, s, 'COMCON' as grp, value from UC_COMCON
                        where in_DATAYEAR(y) and not in_UC_ATTR(r, uc, side, 'COMCON', 'NET')""", zero="eps")
    db.put("UC_COM", """select uc, 'NET' as cv, side, r, y, c, s, 'COMCON' as grp, -value as value from UC_COMCON
                        where in_DATAYEAR(y)""", zero="eps")
    # --- UC_COM(UC_N,'NET',SIDE,R,DATAYEAR,C,S,'COMNET') $= UC_COMNET(UC_N,SIDE,R,DATAYEAR,C,S);
    db.put("UC_COM", """select uc, 'NET' as cv, side, r, y, c, s, 'COMNET' as grp, value from UC_COMNET
                        where in_DATAYEAR(y)""", zero="eps")
    # --- IE_DEFAULT(INT_DEFAULT) = 3;
    db.put("IE_DEFAULT", "select u, 3 as value from INT_DEFAULT")
    prepret(db)
    # --- fillvint (no arguments): LOOP(T(LL),RVP(R,V(LL-LEAD(T)),P)$((NOT RVP(R,V,P))$RVP(R,T,P)$PRC_VINT(R,P)) = YES);
    #     (before it: PRC_SIMV leaves out storage and joins PRC_VINT; after it: RTP(RVP(R,V,P)) $= PRC_SIMV(R,P))
    simv.fillvint(db)
    for (t,) in db.q("select y from MILESTONYR order by yv(y)"):
        db.add("RVP", f"""select r, ys(yv('{t}') - v_LEAD('{t}')) as y, p from RVP
                          where y='{t}' and in_PRC_VINT(r,p) and in_MODLYEAR(ys(yv('{t}') - v_LEAD('{t}')))""")
    simv.fillvint_rtp(db)
    # --- RVP(RTP(R,V,P))$PRC_VINT(R,P) = YES;
    db.add("RVP", "select r, y, p from RTP where in_MODLYEAR(y) and in_PRC_VINT(r,p)")


def interpolate_costs(db: DB):
    """preppm.mod: the cost parameters, inter-/extrapolated here only when an option is given (prepparm ... 0)."""
    P = interp.prepparm
    # --- $BATINCLUDE filparam G_RFRIR 'R,' '' ",'0','0','0','0','0'" YEAR V      (the risk-free rate of the hurdle rates)
    interp.filparam(db, "G_RFRIR", "V")
    # ---- cost parameters: inter-/extrapolated here only when an option is given (prepparm ... 0)
    for n in ("NCAP_COST", "NCAP_DCOST", "NCAP_DLAGC", "NCAP_FOM", "NCAP_FSUB", "NCAP_FTAX", "NCAP_ISUB", "NCAP_ITAX",
              "NCAP_VALU", "NCAP_ISPCT"):
        P(db, n, "V", RTP, 0)
    P(db, "OBJ_COMNT", "T", None, 0)
    P(db, "OBJ_COMPD", "T", None, 0)
    for n in ("ACT_COST", "FLO_COST", "FLO_DELIV", "FLO_SUB", "FLO_TAX", "IRE_PRICE"):
        P(db, n, "V", RTP, 0)
    _need_empty(db, ["DAM_COST"], "damage costs")


def interpolate_attributes(db: DB):
    """preppm.mod: the standard parameters (fillparm), FLO_MARK / PRC_MARK, IRE_FLO, UC_TIME."""
    F, P = interp.fillparm, interp.prepparm
    # ---- standard parameters (fillparm)
    F(db, "NCAP_AF", "V", RTP, x=True)
    F(db, "NCAP_AFA", "V", RTP, x=True)
    F(db, "NCAP_AFS", "V", RTP, x=True)
    F(db, "NCAP_BPME", "V", RTP)
    F(db, "NCAP_CDME", "V", RVP)
    F(db, "NCAP_CEH", "V", RVP, x=True)
    F(db, "NCAP_CHPR", "V", RVP, x=True)
    F(db, "NCAP_CLED", "V", RTP)
    F(db, "NCAP_CLAG", "V", RTP)
    F(db, "NCAP_COM", "V", RTP)
    for n in ("NCAP_DELIF", "NCAP_DLAG", "NCAP_DLIFE", "NCAP_DRATE", "NCAP_FDR", "NCAP_ELIFE"):
        F(db, n, "V", RTP, x=True)
    F(db, "NCAP_ICOM", "V", RTP)
    F(db, "NCAP_ILED", "V", RTP, x=True)
    F(db, "NCAP_OCOM", "V", RTP)
    F(db, "NCAP_PKCNT", "V", RTP)
    F(db, "NCAP_TLIFE", "V", RTP, x=True)
    F(db, "COM_AGG", "T", None)
    F(db, "COM_ELAST", "T", None)
    F(db, "COM_FR", "T", None, x=True)
    for n in ("COM_IE", "COM_PKFLX", "COM_PKRSV", "COM_PROJ", "COM_VOC"):
        F(db, n, "T", None)
    for n in ("ACT_CSTUP", "ACT_CSTSD", "ACT_CSTRMP", "ACT_TIME"):
        F(db, n, "V", RTP)
    F(db, "FLO_FUNC", "V", RVP, x=True)
    F(db, "FLO_PKCOI", "V", RVP)
    F(db, "FLO_SUM", "V", RVP, x=True)
    F(db, "PRC_ACTFLO", "V", RTP, x=True)
    # --- $BATINCLUDE prepparm FLO_MARK R 'P,C,BD' ",'0','0'"  T 1 1  3 X_RPCL
    #     $BATINCLUDE prepparm PRC_MARK R 'P,ITEM,C,BD' ",'0'" T 1 1 11 X_MARK
    P(db, "FLO_MARK", "T", None, 1, def_iebd=3, x=True)
    P(db, "PRC_MARK", "T", None, 1, def_iebd=11, x=True)
    # --- fillparm IRE_FLO R 'P,C,REG,COM,TS': the partner region is REG, so a series towards an external region is not touched
    reg = {r for (r,) in db.q("select r from REG")}
    F(db, "IRE_FLO", "V", _ire_flo_ctrl, cond=interp.KeyCond(0, "r2", reg, "r2 in (select r from REG)"), keycond=True)
    F(db, "IRE_FLOSUM", "V", RVP)
    F(db, "STG_CHRG", "V", _stg_chrg_ctrl)
    F(db, "STG_EFF", "V", RTP)
    F(db, "STG_LOSS", "V", RTP)
    F(db, "STG_SIFT", "T", RTP)
    F(db, "UC_ACT", "T", RTP)
    F(db, "UC_CAP", "T", None)
    F(db, "UC_COM", "T", None)
    F(db, "UC_FLO", "T", None, x=True)
    F(db, "UC_IRE", "T", RTP)
    F(db, "UC_NCAP", "T", RTP)
    F(db, "UC_UCN", "T", None)
    # --- $BATINCLUDE filparam UC_TIME 'UC_N,R,' '' ",'0','0','0'" DATAYEAR T '' '' '' "YEAR,"
    interp.filparam(db, "UC_TIME", "T")


def interpolate_bounds(db: DB):
    """preppm.mod: the bounds (prepparm ... 1), by default only migrated to the milestone year of their period."""
    P = interp.prepparm
    # ---- bounds (prepparm ... 1): by default only migrated to the milestone year of their period
    P(db, "CAP_BND", "T", RTP, 1, x=True)
    P(db, "NCAP_BND", "T", RTP, 1, x=True)
    P(db, "COM_BNDNET", "T", None, 1)
    P(db, "COM_BNDPRD", "T", None, 1)
    P(db, "ACT_BND", "T", RTP, 1, x=True)
    P(db, "FLO_BND", "T", RTP, 1, x=True)
    P(db, "FLO_BDLVL", "T", RTP, 1, x=True)
    P(db, "FLO_FR", "T", RTP, 1, x=True)
    P(db, "FLO_SHAR", "V", RVP, 1, x=True, plus=True)
    P(db, "IRE_BND", "T", None, 1)
    P(db, "IRE_XBND", "T", None, 1)
    P(db, "STGIN_BND", "T", RTP, 1)
    P(db, "STGOUT_BND", "T", RTP, 1)
    P(db, "UC_RHSRT", "T", None, 1, x=True)
    P(db, "UC_RHSRTS", "T", None, 1, x=True)
    P(db, "UC_RHST", "T", None, 1)
    P(db, "UC_RHSTS", "T", None, 1)
    P(db, "REG_BNDCST", "T", None, 1)
    # --- prepparm FLO_SHAR ... PASTMILE 'RVP(R,PASTMILE,P)' 1 3 X_RPCGSB -ABS
    P(db, "FLO_SHAR", "PASTMILE", RVP, 1, def_iebd=3, x=True, fn=lambda o: -abs(o))


def extension_attributes(db: DB):
    """preppm.mod: the extensions (prep_ext.stc; main_ext.mod prep_ext: DSC, VDA; prep_ext.vda)."""
    # ---- preppm.mod 216: $IFI %STAGES% == YES $BATINCLUDE prep_ext.stc
    stochastic.prep_ext(db, interp)
    # ---- extensions (main_ext.mod prep_ext: DSC, VDA)
    extensions.prep_ext(db, interp)


def shape_pointers(db: DB):
    """preppm.mod after the extensions: the SHAPE / MULTI pointers (preshape.gms), PRC_MARK from FLO_MARK, DATAYEAR.
    The end of preppm.mod."""
    _need_empty(db, ["COM_ELASTX"], "SHAPE / MULTI pointers (preshape.gms)")
    # --- $BATINCLUDE preshape NCAP_AFX R P "" V RXX RTP(R,V,P);   ... NCAP_FOMX ...
    preshape(db, "NCAP_AFX")
    # --- $BATINCLUDE preshape NCAP_AFSX R 'P,BD' ",'0','0','0'" V UNCD7 RTP(R,V,P)
    preshape(db, "NCAP_AFSX")
    # --- $BATINCLUDE preshape NCAP_AFM R P "" V RXX RTP(R,V,P)
    preshape(db, "NCAP_AFM")
    preshape(db, "NCAP_FOMX")
    # --- $BATINCLUDE preshape NCAP_FSUBX R P "" V RXX RTP(R,V,P);  ... NCAP_FTAXX ...
    preshape(db, "NCAP_FSUBX")
    preshape(db, "NCAP_FTAXX")
    # --- $BATINCLUDE preshape FLO_FUNCX R 'P,CG1,CG2' ",'0','0'" V UNCD7 RTP(R,V,P)
    preshape(db, "FLO_FUNCX")
    # --- $BATINCLUDE preshape NCAP_FOMM R P "" V RXX RTP(R,V,P);  ... NCAP_FSUBM ...;  ... NCAP_FTAXM ...
    preshape(db, "NCAP_FOMM")
    preshape(db, "NCAP_FSUBM")
    preshape(db, "NCAP_FTAXM")
    # --- $BATINCLUDE preshape NCAP_CPX R P "" V RXX RTP(R,V,P)
    preshape(db, "NCAP_CPX")
    # --- PRC_MARK(R,T,P,P,C,BD) $= FLO_MARK(R,T,P,C,BD);
    db.put("PRC_MARK", "select r, y, p, p as u, c, l, value from FLO_MARK where in_REG(r) and in_MILESTONYR(y)", zero="eps")
    # --- DATAYEAR(MILESTONYR) = YES;  DATAYEAR('%DFLBL%') = NO;
    db.add("DATAYEAR", "select y from MILESTONYR")
    db.remove("DATAYEAR", where="y='0'")


# ---------------------------------------------------------------------------
def preshape(db: DB, name):
    """preshape.gms for a pointer parameter indexed (R,year,P): the index of a SHAPE / MULTI curve is not interpolated
    but carried, as a step function, to the vintages V of the process.

    DFUNC is the year-0 option (default 10: only move a value given inside a period to its milestone year).
      interpolation (any option but 10): a vintage between two data years takes the (rounded) value of the earlier one
      options 11-19: also the periods that contain the first / the last data year; then the option less 10 applies
      2 with no data: EPS for every vintage;  3: before the first and after the last data year;  4: before;  5: after
    Extrapolation only reaches the years in RTP(R,V,P)."""
    from .common import rnd
    if not db.card(name):
        return
    V = [int(y) for (y,) in db.q("select y from MODLYEAR")]
    dm = sorted(int(y) for (y,) in db.q("select y from DM_YEAR"))
    fil2 = {int(y): v for y, v in db.q("select y, value from FIL2")}
    myfil = sorted(int(y) for (y,) in db.q("select y from MY_FIL"))
    B = {int(y): v for y, v in db.q("select y, value from B")}
    E = {int(y): v for y, v in db.q("select y, value from E")}
    rtp = {(r, int(y), p) for r, y, p in db.q("select r, y, p from RTP")}
    cols = db.cols(name)                       # (r, y, p[, cg, cg2 ..]): the series is everything but the year
    key = [c for c in cols if c != "y"]
    series = {}
    for row in db.q(f'select {", ".join(key)}, y, value from "{name}" where in_REG(r)'):
        series.setdefault(tuple(row[:-2]), {})[int(row[-2])] = row[-1]
    out = []                                   # (key.., y, value); a value of 0 is EPS
    for k, rec in series.items():
        r, p = k[0], k[key.index("p")]
        dfunc = 10
        if 0 in rec and rnd(rec[0]) % 1000:
            dfunc = rnd(rec[0]) % 1000
        arr = {y: rec[y] for y in dm if y in rec}
        new = {}
        F = Z = 0
        first = last = 0.0
        fyear = 0
        if dfunc != 10:
            for y in dm:
                if y not in arr:
                    continue
                if last:
                    for v in V:
                        if fyear < v < y:
                            new[v] = last
                else:
                    F, first = y, arr[y]
                last, fyear, Z = rnd(arr[y]), y, y
        else:
            for y in myfil:
                if y not in arr:
                    continue
                Z, F = y, fil2[y]
                if fyear < F:
                    if F > min(first, Z):
                        last, first = arr[y], F
                    if F in V and F not in arr:
                        new[int(F)] = last
                last, fyear = arr[y], y
            dfunc = 0
        cur = lambda v: new.get(v, rec.get(v))
        def extend(lo_ok, hi_ok):
            for v in V:
                if (r, v, p) not in rtp:
                    continue
                x = (first if lo_ok(v) else 0.0) + (last if hi_ok(v) else 0.0)
                if x or (lo_ok(v) and first == 0 and eps_first) or (hi_ok(v) and eps_last):
                    new[v] = x
        eps_first = eps_last = False
        if rnd((dfunc - 5) / 10.0) * 10 == 10:
            extend(lambda v: v < F and E.get(v, v) >= F, lambda v: v > Z and B.get(v, v) <= Z)
            dfunc -= 10
        if dfunc >= 2:
            if dfunc == 4:
                Z = float("inf")
            elif dfunc == 5:
                F = 0
            elif dfunc == 2 - F:
                last, Z, eps_last = 0.0, 0, True
            extend(lambda v: v < F, lambda v: v > Z)
        out += [k + (str(v), x) for v, x in new.items()]
    if out:
        db.x(f"create or replace temp table t_shp ({', '.join(c + ' VARCHAR' for c in key)}, y VARCHAR, value DOUBLE)")
        db.insert_rows("t_shp", out)
        db.put(name, f"select {', '.join(cols)}, value from t_shp", zero="eps")
