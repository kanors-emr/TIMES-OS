# SPDX-License-Identifier: GPL-3.0-or-later
"""VEDA extension hooks: init_ext.vda (before ppmain) and prep_ext.vda (inside preppm)."""
import math
from ..controls import unsupported
from ..engine import DB
from .common import rnd, require_empty as _need_empty, _values
from . import abs as abs_ext, cli, dsc, dynamic_bounds, grids, mlf, resloadc, ucbet


def drop_zero_series(db: DB, name, key_cols):
    """UNCD7(key,'0') $= (X(key,LL) NE 0);  X(key,DATAYEAR)$(NOT UNCD7(key,'0')) = 0;
    -> series whose values are all zero/EPS lose their DATAYEAR records."""
    k = ", ".join(key_cols)
    on = " and ".join(f"a.{c}=b.{c}" for c in key_cols)
    db.x(f"""delete from "{name}" a where in_DATAYEAR(a.y)
             and not exists(select 1 from "{name}" b where {on} and b.value <> 0)""")


def init_ext(db: DB):
    x, s = db.x, db.s
    # ---- MLF: rpt_ext.mlf 12  SET SOW / 1 /;   (data of a declaration: there from the start of the run)
    mlf.init(db)
    # ---- CLI: ppm_ext.cli 8-10, the sets it declares with data (there from the start of the run)
    cli.init(db)
    # ---- init_ext.dsc
    dsc.init(db)
    # --- $IFI %DSCAUTO%==YES ... $IF DEFINED RCAP_BLK $SETGLOBAL SOLMIP YES    (retirement in blocks: a MIP)
    if db.card("RCAP_BLK"):
        db.ctl["SOLMIP"] = True
    # ---- init_ext.vda
    # --- IF(CARD(DATAYEAR)=0, DATAYEAR(T)=YES; DATAYEAR(LL)$(MOD(MAX(1999,MIN(2051,YEARVAL(LL))),5)=0)=YES);
    if db.card("DATAYEAR") == 0:
        db.add("DATAYEAR", "select y from MILESTONYR")
        db.add("DATAYEAR", "select y from ALLYEAR where greatest(1999, least(2051, yv(y))) % 5 = 0")
    # --- DATAYEAR(PASTYEAR) = YES; DATAYEAR('%DFLBL%') = NO;
    db.add("DATAYEAR", "select y from PASTYEAR")
    db.remove("DATAYEAR", where="y='0'")
    # --- LOOP(T$(ORD(T)=1),IF(ABS(B(T)-YEARVAL(T)+5)>5,B(T)=YEARVAL(T)); MIYR_1(T)=YES; MIYR_BOH=B(T)-1);
    t1 = db.q1("select y from MILESTONYR order by try_cast(y as INTEGER) limit 1")
    b1 = db.q1(f"select v_B('{t1}')")
    if abs(b1 - int(t1) + 5) > 5:
        db.put("B", f"select '{t1}' as y, {int(t1)} as value")
        b1 = int(t1)
    db.add("MIYR_1", f"select '{t1}' as y")
    s["MIYR_BOH"] = b1 - 1
    # --- PYR_S(LL) = YEARVAL(LL)=MIYR_BOH;
    db.assign("PYR_S", "select y from ALLYEAR where try_cast(y as INTEGER) = {MIYR_BOH}")
    # --- PRC_PKNO(R,P)$((NCAP_PKCNT(R,'0',P,'ANNUAL')>=10)$NCAP_PKCNT(R,'0',P,'ANNUAL')) = YES;  PRC_PKAF ... <= 0
    db.add("PRC_PKNO", "select r, p from NCAP_PKCNT where y='0' and s='ANNUAL' and value >= 10")
    db.add("PRC_PKAF", "select r, p from NCAP_PKCNT where y='0' and s='ANNUAL' and value <= 0")
    # --- PRC_STGIPS(R,P,C)$(NOT SUM(PRC_ACTUNT(R,P,CG,UNITS_ACT)$(COM_GMAP(R,CG,C)+SAMEAS(CG,C)),1)) = NO;
    db.remove("PRC_STGIPS", where="""in_REG(r) and not exists(select 1 from PRC_ACTUNT a where a.r=PRC_STGIPS.r and a.p=PRC_STGIPS.p
                                       and (in_COM_GMAP(a.r,a.cg,PRC_STGIPS.c) or a.cg=PRC_STGIPS.c))""")
    # --- OPTION TRACKP<STG_MAXCYC; RP_PL(TRACKP,'UP')=YES;        (storage cycle limits: the excess-cycling penalty is priced below)
    db.add("RP_PL", "select distinct r, p, 'UP' as l from STG_MAXCYC where in_REG(r)")
    # --- LOOP(TSL(S(ANNUAL)), ACT_CSTUP(R,LL,P,TSL,CUR)=0; ACT_CSTUP(..)$=ACT_CSTPL(..); ACT_CSTUP(..)$TRACKP $= NCAP_COST(..);
    #       ACT_UPS(R,LL,P,S,'FX') $= ACT_MINLD(R,LL,P));
    #     (the partial-load cost ACT_CSTPL is the start-up cost on the ANNUAL level; a cycle limit's NCAP_COST overrides it)
    db.zap("ACT_CSTUP", "tsl='ANNUAL' and in_REG(r)")
    db.put("ACT_CSTUP", "select r, y, p, 'ANNUAL' as tsl, cur, value from ACT_CSTPL where in_REG(r)", zero="eps")
    db.put("ACT_CSTUP", """select n.r, n.y, n.p, 'ANNUAL' as tsl, n.cur, n.value from NCAP_COST n
                           where in_REG(n.r) and exists(select 1 from STG_MAXCYC m where m.r=n.r and m.p=n.p)""", zero="eps")
    db.put("ACT_UPS", "select r, y, p, 'ANNUAL' as s, 'FX' as l, value from ACT_MINLD where in_REG(r)", zero="eps")
    # --- OPTION CLEAR=TRACKP, RP_UPR<ACT_TIME, RP_UPT<ACT_CSTSD;
    db.assign("RP_UPR", "select distinct r, p, l from ACT_TIME")
    db.assign("RP_UPT", "select distinct r, p, upt, l from ACT_CSTSD")
    # --- remove series that contain only zeros (VDA_EMCB, IRE_PRICE, ACT_COST, FLO_DELIV, FLO_COST)
    drop_zero_series(db, "VDA_EMCB", ["r", "c", "c2"])
    drop_zero_series(db, "IRE_PRICE", ["r", "p", "c", "s", "r2", "cur"])      # tested over both IE
    drop_zero_series(db, "ACT_COST", ["r", "p", "cur"])
    drop_zero_series(db, "FLO_DELIV", ["r", "p", "c", "s", "cur"])
    drop_zero_series(db, "FLO_COST", ["r", "p", "c", "s", "cur"])
    # --- NCAP_CEH(R,LL,P) $= VDA_CEH(R,LL,P);
    db.put("NCAP_CEH", "select r, y, p, value from VDA_CEH", zero="eps")
    # --- PRC_RESID(R,LL--ORD(LL),P)$((PRC_RESID(R,LL,P)>0)$PRC_RESID(R,LL,P)) = PRC_RESID(R,'0',P)+EPS;
    db.put("PRC_RESID", """select distinct r, '0' as y, p, v_PRC_RESID(r,'0',p) as value from PRC_RESID
                           where value > 0""", zero="eps")
    # --- NCAP_PASTI(R,PYR_S,P)$PRC_RESID(R,'0',P) = 1;
    db.put("NCAP_PASTI", "select a.r, s.y, a.p, 1 as value from PRC_RESID a, PYR_S s where a.y='0'")
    # --- FLO_EMIS(R,LL,P,CG,C,S) $= FLO_EFF(R,LL,P,CG,C,S);  OPTION CLEAR=FLO_EFF;
    #     (FLO_EFF is another name for FLO_EMIS in the input; pp_prelv.vda makes it again for CHP processes, flows.py)
    if db.card("FLO_EFF"):
        db.put("FLO_EMIS", "select r, y, p, cg, c, s, value from FLO_EFF", zero="eps")
        db.clear("FLO_EFF")
    # --- VDA_EMCB(R,YEAR,C,COM)$COM_TMAP(R,'ENV',C) = 0;
    db.zap("VDA_EMCB", "in_COM_TMAP(r,'ENV',c)")
    # --- LOOP((R,DATAYEAR,C,COM)$VDA_EMCB(R,DATAYEAR,C,COM),RXX(R,C,COM) = YES); RXX(R,C,COM)$(NOT COM_TMAP(R,'ENV',COM)) = NO;
    # --- LOOP((TOP(R,P,C,'IN'),RXX(R,C,COM)),FS_EMCB(R,P,COM,C)=YES);  FS_EMCB(R,P,COM,C)$TOP(R,P,COM,'IN') = NO;
    db.add("FS_EMCB", """select distinct t.r, t.p, e.c2 as c, t.c as c2
                         from TOP t join VDA_EMCB e on e.r=t.r and e.c=t.c
                         where t.io='IN' and in_DATAYEAR(e.y) and in_COM_TMAP(e.r,'ENV',e.c2)
                           and not in_TOP(t.r, t.p, e.c2, 'IN')""")
    # --- OPTION TRACKPC <= FS_EMCB; TOP(TRACKPC,'OUT') = YES;
    db.add("TOP", "select distinct r, p, c, 'OUT' as io from FS_EMCB")
    # --- LOOP((R,DATAYEAR,P,CG,C,S)$FLO_EMIS(R,DATAYEAR,P,CG,C,S),RPC_EMIS(R,P,C) = YES);
    db.add("RPC_EMIS", "select distinct r, p, c as cg from FLO_EMIS where in_REG(r) and in_DATAYEAR(y)")
    # --- RPG_RED(RPC_EMIS(R,P,C),'OUT')$(NOT TOP(R,P,C,'IN')) = YES;
    db.add("RPG_RED", "select r, p, cg, 'OUT' as io from RPC_EMIS where in_COM(cg) and not in_TOP(r,p,cg,'IN')")
    # --- LOOP((R,DATAYEAR,P,C,S,IE,COM,IO)$(PRC_MAP(R,'IRE',P)$IRE_FLOSUM(R,DATAYEAR,P,C,S,IE,COM,IO)),RPG_RED(R,P,COM,IO) = YES);
    db.add("RPG_RED", "select distinct r, p, c2 as cg, io from IRE_FLOSUM where in_REG(r) and in_DATAYEAR(y) and in_PRC_MAP(r,'IRE',p)")
    # --- COM_AGG(R,LL,C,C)$COM_AGG(R,LL,C,C) = 0;
    db.zap("COM_AGG", "c = c2")
    # --- VDA_FLOP(R,LL,P,CG,S) $= ACT_FLO(R,LL,P,CG,S);  KEEP_FLOF(R,P,C)$VDA_FLOP(R,'0',P,C,'ANNUAL') = YES;
    #     OPTION RP_XRED<ACT_FLO, CLEAR=ACT_FLO;
    # --- VDA_FLOP(R,LL,P,CG,S) $= ACT_FLO(R,LL,P,CG,S);         (ACT_FLO given by the user is read as VDA_FLOP)
    db.put("VDA_FLOP", "select r, y, p, cg, s, value from ACT_FLO", zero="eps")
    # --- KEEP_FLOF(R,P,C)$VDA_FLOP(R,'%DFLBL%',P,C,'ANNUAL') = YES;
    db.add("KEEP_FLOF", "select distinct r, p, cg as c from VDA_FLOP where y='0' and s='ANNUAL' and in_COM(cg)")
    # --- OPTION RP_XRED<ACT_FLO, CLEAR=ACT_FLO;                 (read by pp_prelv.vda line 23 for CHP processes only)
    db.assign("RP_XRED", "select distinct r, p from ACT_FLO")
    db.clear("ACT_FLO")
    # --- NCAP_START(R,P)$(NCAP_START(R,P)<=MIYR_BOH)=0;
    db.zap("NCAP_START", "value <= {MIYR_BOH}")
    ncap_bnd_n(db)
    # --- $BATINCLUDE equcrtp.vda INIT_EXT   (dynamic bounds by process, UC_DYNBND)
    dynamic_bounds.init_ext(db)
    # --- $ IF %CLI%==YES LOOP((UC_N,SIDE,R,LL,CM_VAR)$UC_CLI(UC_N,SIDE,R,LL,CM_VAR),UC_ATTR(R,UC_N,'RHS','CLI','YES')=YES);
    cli.uc_attr(db)
    # --- $IF DEFINED UC_ACTBET  UC_FLOBET(..,%PGPRIM%) $= UC_ACTBET(..); UC_GMAP_P(R,UC_N,'ACT',P)=YES   (ucbet.vda)
    ucbet.init(db)
    # --- LOOP(UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,UC_NAME(TSL)),UC_TSL(R,UC_N,SIDE,TSL)=YES);
    db.add("UC_TSL", "select distinct r, uc, side, ucn as tsl from UC_ATTR where in_TSLVL(ucn)")
    # --- $IF DEFINED PRC_REACT $SETGLOBAL POWERFLO YES;  $IFE CARD(GR_PTDF)+CARD(GG_KGF) $SETGLOBAL POWERFLO YES
    grids.init(db)
    # ---- init_ext.abs     (main_ext.mod: the extensions in the order of EXTEND, VDA before ABS)
    abs_ext.init_ext(db)


def _gmod(a, b):
    """GAMS MOD(a, b): the sign of the result is that of a"""
    return math.fmod(a, b)


def ncap_bnd_n(db: DB):
    """init_ext.vda: updatable OFF ranges and start years given by NCAP_BND(R,LL,P,'N')."""
    eot = int(db.ctl["EOTIME"])
    # --- RVP(R,LL,P) $= NCAP_BND(R,LL,P,'N');
    recs = db.q("select r, y, p, value from NCAP_BND where l='N' and value <> 0 and in_REG(r)")
    if not recs:
        return
    # --- IF(CARD(RVP), NCAP_BND(RVP,'N')$(NCAP_BND(RVP,'N')>%EOTIME%) = %EOTIME%;
    recs = [(r, y, p, min(v, eot) if v > eot else v) for r, y, p, v in recs]
    db.put("NCAP_BND", _values([(r, y, p, "N", v) for r, y, p, v in recs], ["r", "y", "p", "l", "value"]))
    #       NCAP_START(R,P)$((ABS(NCAP_BND(R,'0',P,'N'))>999)$RVP(R,'0',P)) = ABS(NCAP_BND(R,'0',P,'N'))+1;
    start = [(r, p, abs(v) + 1) for r, y, p, v in recs if y == "0" and abs(v) > 999]
    if start:
        db.put("NCAP_START", _values(start, ["r", "p", "value"]))
    #       PRC_NOFF(R,P,LL,EOHYEAR)$RVP(R,LL,P) = NO;
    db.tmp("t_rvp", _values([(r, y, p) for r, y, p, v in recs], ["r", "y", "p"]))
    db.remove("PRC_NOFF", where="exists(select 1 from t_rvp t where t.r=PRC_NOFF.r and t.p=PRC_NOFF.p and t.y=PRC_NOFF.u)")
    #       PRC_NOFF(R,P,BOHYEAR(LL),LL+(NCAP_BND(R,LL,P,'N')-YEARVAL(LL)))$RVP(R,LL,P) = YES);
    #       (the end is the year label N; a range is set even when N is before LL)
    bohyear = {y for (y,) in db.q("select y from BOHYEAR")}
    eoh = {y for (y,) in db.q("select y from EOHYEAR")}
    noff = [(r, p, y, str(int(v))) for r, y, p, v in recs
            if y in bohyear and float(v).is_integer() and str(int(v)) in eoh]
    if len(noff) != sum(1 for r, y, p, v in recs if y in bohyear):
        unsupported(db, "NCAP_BND(...,'N') with a value that is not a year of the model")
    if noff:
        db.add("PRC_NOFF", _values(noff, ["r", "p", "u", "u2"]))
    # --- NCAP_BND(RVP(R,LL,P),L('N')) = MOD(MIN(2,ROUND(MAX(NCAP_BND(RVP,L),-1))),2)$LASTLL(LL)
    #                                   + (YEARVAL(LL)-1)$(ROUND(MOD(NCAP_BND(RVP,L)-YEARVAL(LL),MAX(1,YEARVAL(LL))))=-1);
    #     LASTLL is '0' (the interpolation label is the last element of LL): what remains is -1/0/+1 on year 0 (for
    #     REG_BDNCAP) and, on a year y, y-1 when N was y-1 (an exact start year, prep_ext.vda); every other value is removed
    out = []
    for r, y, p, v in recs:
        yv = 0 if y == "0" else int(y)
        val = (_gmod(min(2, rnd(max(v, -1))), 2) if y == "0" else 0) + ((yv - 1) if rnd(_gmod(v - yv, max(1, yv))) == -1 else 0)
        out.append((r, y, p, "N", val))
    db.put("NCAP_BND", _values(out, ["r", "y", "p", "l", "value"]))
    # --- OPTION CLEAR=RVP;


def exact_start(db: DB):
    """prep_ext.vda: process cost-neutral ILEDs - an exact start year y given by NCAP_BND(R,y,P,'N') = y-1."""
    # --- RVPRL(RTP(R,T,P)) $= SUM(PERIODYR(T,YEAR)$NCAP_BND(R,YEAR,P,'N'),NCAP_BND(R,YEAR,P,'N'));
    rows = db.q("""select k.r, k.y, k.p, sum(n.value) as z from RTP k join PERIODYR q on q.y=k.y
                   join NCAP_BND n on n.r=k.r and n.p=k.p and n.y=q.y2 and n.l='N' and n.value <> 0
                   group by k.r, k.y, k.p having sum(n.value) <> 0""")
    if not rows:
        return
    # --- LOOP(RTP(R,T,P)$RVPRL(RTP), Z=RVPRL(RTP); Z=Z/ROUND(Z/M(T)); NCAP_BND(RTP,'N')=Z;
    #       COEF_ILED(RTP) = ABS(NCAP_ILED(RTP))+1000; NCAP_ILED(RTP) = MAX(EPS,Z+1-B(T)));
    m = {y: v for y, v in db.q("select y, v_M(y) from MILESTONYR")}
    b = {y: v for y, v in db.q("select y, v_B(y) from MILESTONYR")}
    iled = {(r, y, p): v for r, y, p, v in db.q("select r, y, p, value from NCAP_ILED")}
    nb, ci, il = [], [], []
    for r, t, p, z in rows:
        z = z / rnd(z / m[t])
        nb.append((r, t, p, "N", z))
        ci.append((r, t, p, abs(iled.get((r, t, p), 0.0)) + 1000))
        il.append((r, t, p, max(0.0, z + 1 - b[t])))
    db.put("NCAP_BND", _values(nb, ["r", "y", "p", "l", "value"]))
    db.put("COEF_ILED", _values(ci, ["r", "y", "p", "value"]))
    db.put("NCAP_ILED", _values(il, ["r", "y", "p", "value"]), zero="eps")
    # --- NCAP_BND(RTP,BDUPX)$(MAPVAL(NCAP_BND(RTP,BDUPX))$RVPRL(RTP))=0;   (MAPVAL: EPS or infinite)
    db.tmp("t_rvprl", _values([(r, t, p) for r, t, p, z in rows], ["r", "y", "p"]))
    db.zap("NCAP_BND", """l in ('UP','FX') and (value = 0 or isinf(value))
                          and exists(select 1 from t_rvprl t where t.r=NCAP_BND.r and t.y=NCAP_BND.y and t.p=NCAP_BND.p)""")


def prep_ext(db: DB, interp):
    """prep_ext.mlf + prep_ext.dsc + prep_ext.vda  (called from preppm after the core registrations; EXTEND lists MLF
    before DSC and VDA, initmty.mod 464-468)."""
    x, s = db.x, db.s
    # ---- prep_ext.mlf
    mlf.prep_ext(db, interp)
    # ---- prep_ext.dsc
    dsc.prep(db, interp)
    # ---- prep_ext.vda
    # --- OPTION RP_GRP < NCAP_AFAC;  NCAP_AFC(R,DATAYEAR,P,CG,'ANNUAL')$RP_GRP(R,P,CG) = NCAP_AFAC(R,DATAYEAR,P,CG);
    db.x("""delete from NCAP_AFC a where stl='ANNUAL' and in_REG(r) and in_DATAYEAR(y)
            and exists(select 1 from NCAP_AFAC b where b.r=a.r and b.p=a.p and b.cg=a.cg)""")
    db.put("NCAP_AFC", "select r, y, p, cg, 'ANNUAL' as stl, value from NCAP_AFAC where in_REG(r) and in_DATAYEAR(y)", zero="eps")
    # --- NCAP_AFC(R,LL,P,CG,STL(S)) $= NCAP_AFCS(R,LL,P,CG,S); OPTION CLEAR=NCAP_AFCS;
    #     (the last index of NCAP_AFC holds a timeslice level or a timeslice)
    db.put("NCAP_AFC", "select r, y, p, cg, s as stl, value from NCAP_AFCS", zero="eps")
    db.clear("NCAP_AFCS")
    # --- OPTION RP_GRP < ACT_EFF, CLEAR=UNCD7;
    db.assign("RP_GRP", "select distinct r, p, cg from ACT_EFF")
    # --- UNCD7(R,'0',P,CG,..)$BOHYEAR(LL) $= (ACT_EFF(R,LL,P,CG,S) GT 0)$ACT_EFF;  LOOP(UNCD7, RPC_ACE(R,P,CG) = YES);
    db.add("RPC_ACE", "select distinct r, p, cg from ACT_EFF where in_BOHYEAR(y) and value > 0")
    # --- RPG_1ACE(RP_GRP(RPC(R,P,C)),C)$(NOT RPC_ACE(RPC)) = YES;
    db.add("RPG_1ACE", "select r, p, cg, cg as c from RP_GRP where in_RPC(r,p,cg) and not in_RPC_ACE(r,p,cg)")
    db.clear("RP_GRP")
    # --- ACT_FLO(R,LL--ORD(LL),P,C,S)$STOA(S) $= VDA_FLOP(R,LL,P,C,S);
    #     a flag on year 0 for every flow given per unit of activity below ANNUAL; the value is that of the last year
    #     with data ('0' is the last element of the year set)
    db.put("ACT_FLO", """select r, '0' as y, p, cg, s, arg_max(value, case when y='0' then 99999 else cast(y as integer) end) as value
                         from VDA_FLOP where s <> 'ANNUAL' and in_COM(cg) and in_REG(r) group by r, p, cg, s""", zero="eps")
    F = interp.fillparm
    F(db, "VDA_EMCB", "V", None)
    # --- $BATINCLUDE fillparm NCAP_AFC R 'P,CG,STL' ",'0','0','0'" V 'RTP(R,V,P)' 'GE -1$ACTCG(CG)'
    F(db, "NCAP_AFC", "V", ("RTP", ("r", "p")), cond=interp.KeyThr(0, -1, "cg", {"ACT"}, "cg = 'ACT'"), keycond=True)
    F(db, "ACT_EFF", "V", ("RVP", ("r", "p")), x=True)
    F(db, "VDA_FLOP", "V", ("RVP", ("r", "p")), x=True)
    F(db, "FLO_EMIS", "V", ("RVP", ("r", "p")), x=True)
    for n in ("ACT_UPS", "ACT_LOSPL", "ACT_LOSSD", "ACT_SDTIME", "ACT_MAXNON"):
        F(db, n, "V", ("RVP", ("r", "p")))
    F(db, "STG_MAXCYC", "V", ("RTP", ("r", "p")))
    # --- $IF DEFINED UC_FLOBET $BATINCLUDE fillparm UC_FLOBET 'UC_N,R' 'P,C' ",'0','0','0'" T 1 'GE 0'
    ucbet.prep(db, interp)
    # --- $IF DEFINED COM_CSTBAL $BATINCLUDE fillparm COM_CSTBAL R 'C,S,ITEM,CUR' ",'0','0'" T 1 'GE 0'
    if db.card("COM_CSTBAL"):
        F(db, "COM_CSTBAL", "T", None)
    # --- $IFI %POWERFLO%==YES $BATINCLUDE powerflo.vda PREP
    grids.prep(db, interp)
    # --- $IF DEFINED GR_VARGEN $BATINCLUDE resloadc.vda      (the residual load curve)
    resloadc.prep(db, interp)
    # --- $BATINCLUDE equcrtp.vda PREP_EXT   (dynamic bounds by process)
    dynamic_bounds.prep_ext(db, interp)
    dynamic_bounds.t_succ(db)
    # --- FLO_FUNCX(R,LL,P,C,CG)$(NOT PRC_VINT(R,P)) = 0;
    #     (the first group a commodity only: a group such as CAPFLO or ACT stays for a process that is not vintaged)
    db.zap("FLO_FUNCX", "not in_PRC_VINT(r,p) and in_COM(cg)")
    residual_capacity(db)
    # --- COM_LIM(RC,BDNEQ)$COM_LIM(RC,'FX')=NO;
    db.remove("COM_LIM", where="l in ('LO','UP') and in_RC(r,c) and in_COM_LIM(r,c,'FX')")
    # --- ACT_MINLD(RTP) $= ACT_UPS(RTP,'ANNUAL','FX');   RPC_CAPFLO(RTP,C) $= RCAP_OCAP(RTP,C);
    db.put("ACT_MINLD", "select r, y, p, value from ACT_UPS where s='ANNUAL' and l='FX' and in_RTP(r,y,p)", zero="eps")
    if db.card("RCAP_OCAP"):
        if not db.s.get("VNRET"):
            unsupported(db, "flows of retired capacity (RCAP_OCAP) in a model without retirements (no RCAP_BND / PRC_REFIT)", ["RCAP_OCAP"])
        db.add("RPC_CAPFLO", "select distinct r, y, p, c from RCAP_OCAP where in_RTP(r,y,p) and not in_RPC_CAPFLO(r,y,p,c)")
    # --- FLO_ASHAR(R,DM_YEAR,P,C,CG,S,BD) $= FLO_SHAR(R,DM_YEAR,P,C,CG,S,BD)$(NOT COM_GMAP(R,CG,C)*RPC(R,P,C));
    db.put("FLO_ASHAR", """select r, y, p, c as cg, cg as cg2, s, l, value from FLO_SHAR
                           where in_DM_YEAR(y) and not (in_COM_GMAP(r,cg,c) and in_RPC(r,p,c))""", zero="eps")
    exact_start(db)
    # ---- prep_ext.abs     (main_ext.mod: VDA before ABS)
    abs_ext.prep_ext(db, interp)


def residual_capacity(db: DB):
    """prep_ext.vda: PRC_RESID -> stock profile at milestone years (as one past investment)."""
    s = db.s
    # --- TRACKP(R,P)$=PRC_RESID(R,'0',P); PRC_YMAX(TRACKP(R,P))=ROUND(PRC_RESID(R,'0',P));
    db.clear("PRC_YMAX")
    track = db.q("select r, p, value from PRC_RESID where y='0'")
    if not track:
        return
    pyr = db.q("select y from PYR_S where in_PASTYEAR(y)")
    if not pyr:
        return
    ll = pyr[0][0]
    boh = s["MIYR_BOH"]
    EPS = 1e-300
    Tm = [(y, m) for y, m in db.q("select y, v_M(y) from MILESTONYR order by yv(y)")]
    dm = set(y for (y,) in db.q("select y from DM_YEAR"))
    rows = db.q("select r, p, y, value from PRC_RESID where y <> '0'")
    data = {}
    for r, p, y, v in rows:
        if y in dm:
            data.setdefault((r, p), []).append((int(y), EPS if v == 0 else v))
    tlife = {(r, p): v for r, p, v in db.q(f"select r, p, value from NCAP_TLIFE where y='{ll}'")}
    gt = s["G_TLIFE"]
    out, opt0, ymax = [], [], []
    waver = str(db.env.get("WAVER", "")).strip().strip("'\"").upper() == "YES"
    CNT = 0.0
    for r, p, o in track:
        dfunc = round(o)
        if dfunc:
            ymax.append((r, p, float(dfunc)))
        # PRC_RESID(R,'0',P) = MAX(1,NCAP_TLIFE(R,LL,P)+G_TLIFE$(NOT NCAP_TLIFE(R,LL,P)));
        life = max(1.0, tlife.get((r, p), 0.0) + (gt if (r, p) not in tlife else 0.0))
        opt0.append((r, "0", p, life))
        res = {}
        MY_F = 0.0; F = 0.0; Z = 0.0; MYFY = 0.0
        for Zy, val in sorted(data.get((r, p), [])):
            LAST = MY_F; MY_F = val; Z = Zy
            if LAST != 0:
                for ty, m in Tm:
                    if Z > m > MYFY:
                        res[ty] = MY_F - (MY_F - LAST) / (Z - MYFY) * (Z - m)
            else:
                F = Z
            MYFY = Z
            if LAST + MY_F > 1e-200:
                CNT = Z
        if abs(dfunc - 10) == 5:
            dfunc = F; F = Z
        elif dfunc:
            F = 0
        if Z == F:
            CNT = life; Z = F + CNT; dfunc = dfunc + CNT
            for ty, m in Tm:
                if m > F:
                    res[ty] = MY_F * max(0.0, 1 - ((m - F) if m >= dfunc else 0.0) / CNT)
            MY_F = 0.0
        else:
            Z = CNT
        # $IFI %WAVER%==YES PRC_YMAX(R,P)=Z+1$(MY_F>0); IF(MY_F=0, PRC_RESID(R,LL+(Z-MIYR_BOH),P)=EPS);
        # the $IFI governs the whole line: without WAVER neither statement is compiled
        if waver and abs(MY_F) < 1e-200:            # MY_F = 0 (numerically)
            res[str(int(Z))] = EPS
        for y, v in res.items():
            out.append((r, y, p, v))
    import pandas as pd
    df = pd.DataFrame(out, columns=["r", "y", "p", "value"])
    df["value"] = df["value"].where(df["value"].abs() > 1e-200, 0.0).where(df["value"] != 0, float("nan"))
    # '=' assignment: exact zero deletes, EPS (tiny) is stored as 0
    df_del = df[df["value"].isna()][["r", "y", "p"]]
    df_put = df[~df["value"].isna()]
    db.con.register("d_", df_del); db.x('delete from PRC_RESID a where exists(select 1 from d_ where d_.r=a.r and d_.y=a.y and d_.p=a.p)'); db.con.unregister("d_")
    db.con.register("p_", df_put); db.put("PRC_RESID", "select * from p_ where in_ALLYEAR(y)", zero="eps"); db.con.unregister("p_")
    o = pd.DataFrame(opt0, columns=["r", "y", "p", "value"])
    db.con.register("o_", o); db.put("PRC_RESID", "select * from o_"); db.con.unregister("o_")
    ym = pd.DataFrame(ymax, columns=["r", "p", "value"])
    db.con.register("y_", ym); db.put("PRC_YMAX", "select * from y_"); db.con.unregister("y_")
    # --- NCAP_TLIFE(R,LL,P)$TRACKP(R,P) = 1;  NCAP_ILED(R,LL,P)$TRACKP(R,P) = 0;
    db.put("NCAP_TLIFE", f"select r, '{ll}' as y, p, 1 as value from PRC_RESID where y='0'")
    db.zap("NCAP_ILED", f"y='{ll}' and in_PRC_RESID(r,'0',p)")
    # --- RTP_CPTYR(R,LL,T,P)$(((PRC_RESID(R,T,P)>0)+(B(T)<PRC_YMAX(R,P)))$TRACKP(R,P))=YES);
    db.add("RTP_CPTYR", f"""select k.r, '{ll}' as y, t.y as y2, k.p from PRC_RESID k, MILESTONYR t
                            where k.y='0' and (v_PRC_RESID(k.r,t.y,k.p) > 0 or v_B(t.y) < v_PRC_YMAX(k.r,k.p))""")
