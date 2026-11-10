# SPDX-License-Identifier: GPL-3.0-or-later
"""pp_reduce.red: the reduction of the model size, at the level the run file's REDUCE asks for.

TIMES has three levels, by the text of %REDUCE% (compared as GAMS compares it, case and all):

  NO            no reduction: every process has a capacity variable, PRC_ACT = RP_STD + RP_IRE (sets.py)
  YES           the whole reduction: also flows replaced by the activity (RPC_ACT, RPC_AIRE, RPC_FFUNC), processes
                without an activity variable (NO_ACT), processes turned off by a zero activity bound (RTPS_OFF)
  anything else the capacity variables only of the processes that need one (PRC_CAP), and the emissions that FLO_SUM
                defines on input flows substituted by source flow x emission factor (FS_EMIS, RPC_EMIS); this is also
                the level of a run file without a $SET REDUCE line (%REDUCE% then stays as text)
"""
from ..engine import DB


def level(db: DB):
    """'NO', 'YES' or 'PART' (any other value of REDUCE, or none)."""
    v = db.ctl.get("REDUCE")
    return v if v in ("NO", "YES") else "PART"


def reduce(db: DB):
    """pp_reduce.red lines 17-174 (what follows $IF %REDUCE% == NO $GOTO REDDONE), after PRC_CAP, PRC_ACT and RP_AFB
    are set for no reduction."""
    lv = level(db)
    # (for the equations: the flow term of cal_red.red, $SETGLOBAL CAL_RED 'cal_red.red' with REDUCE YES; a table only
    #  then, so that the tables of a run at the other levels are as they were)
    if lv == "YES":
        db.declare("REDUCE_YES", "set", ["UC_NAME"])
        db.clear("REDUCE_YES")
        db.load_rows("REDUCE_YES", [("YES",)])
    if lv == "NO":
        return
    capacity_variables(db)
    emissions(db)
    if lv == "YES":
        activity_flows(db)
        no_activity(db)
        flow_functions(db)
        turned_off(db)


def reddone(db: DB):
    """pp_reduce.red after $LABEL REDDONE, before PRC_TS2: the emissions marked for substitution."""
    # --- LOOP(FS_EMIS(R,P,CG,C,COM), RPCC_FFUNC(R,P,CG,COM) = YES);
    db.add("RPCC_FFUNC", "select r, p, cg, c2 as cg2 from FS_EMIS")
    # --- OPTION CLEAR=TRACKPC,CLEAR=FSCK;
    db.clear("FSCK")


# ---------------------------------------------------------------------------
def capacity_variables(db: DB):
    """The processes that need capacity variables."""
    # --- PRC_CAP(RP) = NO;
    db.clear("PRC_CAP")
    # --- $IF DEFINED PRC_DSCNCAP PRC_CAP(PRC_DSCNCAP) = YES;
    if "PRC_DSCNCAP" in db.sym:
        db.add("PRC_CAP", "select r, p from PRC_DSCNCAP")
    # --- LOOP((R,UC_N,P)$UC_GMAP_P(R,UC_N,'CAP',P),  PRC_CAP(R,P) = YES);
    #     LOOP((R,UC_N,P)$UC_GMAP_P(R,UC_N,'NCAP',P), PRC_CAP(R,P) = YES);
    db.add("PRC_CAP", "select r, p from UC_GMAP_P where grp in ('CAP','NCAP') and in_UC_N(uc)")
    # --- LOOP((RTP(R,PYR,P))$NCAP_PASTI(R,PYR,P),    PRC_CAP(R,P) = YES);
    db.add("PRC_CAP", "select r, p from NCAP_PASTI where in_PASTYEAR(y) and in_RTP(r,y,p)")      # (PYR: an alias of PASTYEAR)
    # --- LOOP((RTP(R,T,P),BD)$CAP_BND(R,T,P,BD),     PRC_CAP(R,P) = YES);
    #     LOOP((RTP(R,T,P),BD)$NCAP_BND(R,T,P,BD),    PRC_CAP(R,P) = YES);
    for n in ("CAP_BND", "NCAP_BND"):
        db.add("PRC_CAP", f"select r, p from {n} where in_MILESTONYR(y) and in_RTP(r,y,p) and l in ('LO','UP','FX')")
    # --- OBJ_ICUR(R,LL--ORD(LL),P,CUR)$DM_YEAR(LL) $= (NCAP_COST(R,LL,P,CUR) NE 0);  ... NCAP_FOM, NCAP_ISUB, NCAP_ITAX,
    #     NCAP_FSUB, NCAP_FTAX, NCAP_DCOST, NCAP_DLAGC;   LOOP(OBJ_ICUR(R,LL,P,CUR), PRC_CAP(R,P) = YES);
    #     (EPS NE 0 is false: a cost given as EPS does not count)
    for n in ("NCAP_COST", "NCAP_FOM", "NCAP_ISUB", "NCAP_ITAX", "NCAP_FSUB", "NCAP_FTAX", "NCAP_DCOST", "NCAP_DLAGC"):
        db.add("PRC_CAP", f"select r, p from {n} where in_DM_YEAR(y) and value <> 0")
    # --- PRC_CAP(RP(R,P)) $= RP_AFB(RP,'FX');
    db.add("PRC_CAP", "select r, p from RP_AFB where l='FX' and value <> 0 and in_RP(r,p)")
    # --- RTPS_BD(R,T--ORD(T),P,S--ORD(S),'FX') $= NCAP_AFS(R,T,P,S,'FX');
    #     RTPS_BD(R,T--ORD(T),P,ANNUAL,'FX')    $= NCAP_AFA(R,T,P,'FX');
    #     LOOP(RTPS_BD(R,T,P,S,BD), PRC_CAP(R,P) = YES);
    #     ($= of a set from a value: a record, EPS too, sets the member)
    db.add("PRC_CAP", "select r, p from NCAP_AFS where l='FX' and in_MILESTONYR(y)")
    db.add("PRC_CAP", "select r, p from NCAP_AFA where l='FX' and in_MILESTONYR(y)")
    # --- $IF '%ETL%'==YES PRC_CAP(R,P)$SEG(R,P) = YES;          (ETL is not in this implementation: controls.py stops it)


def emissions(db: DB):
    """Emission flows that can be replaced by source flow x emission factor."""
    # --- OPTION CLEAR=TRACKPC;
    #     TRACKPC(RP_STD(R,P),C)$(TOP(R,P,C,'OUT')$ENV(R,C)) = YES;
    #     TRACKPC(R,P,C)$(RPC_PG(R,P,C)+RPC_AFLO(R,P,C)) = NO;
    db.tmp("t_red_pc", """select distinct t.r, t.p, t.c from TOP t where t.io='OUT' and in_RP_STD(t.r,t.p) and in_ENV(t.r,t.c)
                          and not in_RPC_PG(t.r,t.p,t.c) and not in_RPC_AFLO(t.r,t.p,t.c)""")
    # --- OPTION FSCK <= FLO_SUM;
    db.assign("FSCK", "select distinct r, p, cg, c, cg2 from FLO_SUM")
    # --- FS_EMIS(FSCK(R,P,CG,C,COM))$((COM_GMAP(R,CG,C)$TOP(R,P,C,'IN'))$TRACKPC(R,P,COM)) = YES;
    db.add("FS_EMIS", """select f.r, f.p, f.cg, f.c, f.cg2 as c2 from FSCK f
                         join t_red_pc k on k.r=f.r and k.p=f.p and k.c=f.cg2
                         where in_COM_GMAP(f.r,f.cg,f.c) and in_TOP(f.r,f.p,f.c,'IN')""")
    # --- LOOP(FS_EMIS(R,P,CG,C,COM), RPC_EMIS(R,P,COM) = YES);
    db.add("RPC_EMIS", "select r, p, c2 as cg from FS_EMIS")


# ---------------------------------------------------------------------------
def activity_flows(db: DB):
    """Flows that are the activity: the only commodity of the primary group."""
    # --- RPC_ACT(RPC_PG(RP_PGACT(RP_STD),C)) = YES;
    db.add("RPC_ACT", "select r, p, c as cg from RPC_PG where in_RP_PGACT(r,p) and in_RP_STD(r,p)")
    # --- RPC_AIRE(RPC_PG(RP_IRE(RP_PGACT),C)) = YES;
    db.add("RPC_AIRE", "select r, p, c from RPC_PG where in_RP_IRE(r,p) and in_RP_PGACT(r,p)")
    # --- PRC_ACT(RP_PGACT) = NO;
    db.remove("PRC_ACT", where="in_RP_PGACT(r,p)")


def no_activity(db: DB):
    """Processes without capacity variable and without activity attributes: no activity equation."""
    # --- NO_ACT(PRC_ACT(R,P))$(NOT PRC_CAP(R,P)) = YES;
    db.add("NO_ACT", "select r, p from PRC_ACT where not in_PRC_CAP(r,p)")
    # --- LOOP((RTP(R,T,P),S,BD)$((ACT_BND(RTP,S,BD)>-INF$BDUPX(BD))$ACT_BND(RTP,S,BD)), NO_ACT(R,P) = NO);
    #     (an upper or fixed bound above -INF, EPS too; a lower bound above 0)
    db.remove("NO_ACT", select="""select r, p from ACT_BND where in_MILESTONYR(y) and in_RTP(r,y,p)
                                  and ((l in ('UP','FX') and value > '-inf'::double) or (l = 'LO' and value > 0))""")
    # --- LOOP((R,DM_YEAR,P,CUR)$ACT_COST(R,DM_YEAR,P,CUR), NO_ACT(R,P) = NO);
    db.remove("NO_ACT", select="select r, p from ACT_COST where in_DM_YEAR(y)")
    # --- LOOP((R,UC_N,P)$UC_GMAP_P(R,UC_N,'ACT',P), NO_ACT(R,P) = NO);
    db.remove("NO_ACT", select="select r, p from UC_GMAP_P where grp='ACT' and in_UC_N(uc)")
    # --- NO_ACT(R,P)$SUM(RPC_CUMFLO(R,P,%PGPRIM%,YEAR,LL),1) = NO;
    db.remove("NO_ACT", select="select r, p from RPC_CUMFLO where c='ACT'")
    # --- PRC_ACT(NO_ACT) = NO;
    db.remove("PRC_ACT", where="in_NO_ACT(r,p)")
    # --- RP_XRED(RP_PGFLO) = NO;
    db.remove("RP_XRED", where="in_RP_PGFLO(r,p)")
    # --- RPC_ACT(RP_XRED(RP_STD(PRC_ACT)),ACTCG) = YES;
    db.add("RPC_ACT", """select x.r, x.p, a.cg from RP_XRED x, ACTCG a
                         where in_RP_STD(x.r,x.p) and in_PRC_ACT(x.r,x.p)""")


def flow_functions(db: DB):
    """Flows tied by FLO_FUNC / FLO_SUM to the flow of the activity: expressed by the activity variable."""
    # --- OPTION CG_GRP <= FLO_FUNC, RP_XRED < CG_GRP; CG_GRP(R,P,CG,CG) = NO;
    db.tmp("t_red_grp", "select distinct r, p, cg, cg2 from FLO_FUNC")
    db.assign("RP_XRED", "select distinct r, p from t_red_grp")
    db.x("delete from t_red_grp where cg = cg2")
    # --- CG_GRP(R,P,CG,CG2)$(SUM(RPC(R,P,C)$COM_GMAP(R,CG,C),1) NE 1) = NO;
    #     CG_GRP(R,P,CG1,CG)$(SUM(RPC(RP_PGACT(R,P),C)$COM_GMAP(R,CG,C),1) NE 1) = NO;
    db.tmp("t_red_n", """select g.r, g.p, g.cg, count(*) as n from (select distinct r, p, cg from t_red_grp
                                                                  union select distinct r, p, cg2 from t_red_grp) g
                         join COM_GMAP m on m.r=g.r and m.cg=g.cg join RPC k on k.r=g.r and k.p=g.p and k.c=m.c
                         group by g.r, g.p, g.cg""")
    one = "exists(select 1 from t_red_n n where n.r={a}.r and n.p={a}.p and n.cg={a}.{c} and n.n = 1)"
    db.x(f"delete from t_red_grp g where not {one.format(a='g', c='cg')}")
    db.x(f"delete from t_red_grp g where not ({one.format(a='g', c='cg2')} and in_RP_PGACT(g.r,g.p))")
    # --- RPCG_PTRAN(RPC(R,P,C),COM,CG1,CG2)$((COM_GMAP(R,CG1,C)*RPC(R,P,COM)*COM_GMAP(R,CG2,COM))$CG_GRP(R,P,CG1,CG2)) = YES;
    db.add("RPCG_PTRAN", """select g.r, g.p, a.c, b.c as c2, g.cg, g.cg2 from t_red_grp g
                            join COM_GMAP a on a.r=g.r and a.cg=g.cg join RPC x on x.r=g.r and x.p=g.p and x.c=a.c
                            join COM_GMAP b on b.r=g.r and b.cg=g.cg2 join RPC y on y.r=g.r and y.p=g.p and y.c=b.c""")
    # --- LOOP(FSCK(R,P,CG1,C,CG2)$CG_GRP(R,P,CG2,CG1),RPCG_PTRAN(R,P,C,COM,CG1,CG2)$COM_GMAP(R,CG2,COM) = YES);
    db.add("RPCG_PTRAN", """select f.r, f.p, f.c, m.c as c2, f.cg, f.cg2 from FSCK f
                            join t_red_grp g on g.r=f.r and g.p=f.p and g.cg=f.cg2 and g.cg2=f.cg
                            join COM_GMAP m on m.r=f.r and m.cg=f.cg2
                            where in_COM(f.c)""")
    # --- RPCG_PTRAN(R,P,C,COM,CG1,CG2)$(NOT (RPC_ACT(R,P,C)+RPC_ACT(R,P,COM))) = NO;
    db.remove("RPCG_PTRAN", where="not (in_RPC_ACT(r,p,c) or in_RPC_ACT(r,p,c2))")
    # --- OPTION TRACKPC < RPCG_PTRAN;        (TRACKPC(R,P,C) from RPCG_PTRAN(R,P,COM,C,CG,CG): its index in C, the fourth)
    db.tmp("t_red_pc", "select distinct r, p, c2 as c from RPCG_PTRAN")
    # --- OPTION RP_CGG < FSCK;               (RP_CGG(REG,PRC,C,CG,CG) from FSCK(REG,PRC,CG,C,CG); a projection with `<`
    #                                         matches a repeated domain from the right: RP_CGG(R,P,C,CG2,CG1))
    db.tmp("t_red_cgg", "select distinct r, p, c, cg2 as cg, cg as cg2 from FSCK")
    # --- RPCG_PTRAN(RP_CGG(RPC_ACT(R,P,COM),C,CG),C)$(RP_PG(R,P,CG)+RPC_ACT(R,P,CG)) = YES;
    db.add("RPCG_PTRAN", """select k.r, k.p, k.c, k.cg as c2, k.cg2 as cg, k.cg as cg2 from t_red_cgg k
                            where in_RPC_ACT(k.r,k.p,k.c) and in_COM(k.cg)
                              and (in_RP_PG(k.r,k.p,k.cg2) or in_RPC_ACT(k.r,k.p,k.cg2))""")
    # --- RPCG_PTRAN(RP_CGG(RPC(R,P,COM),C,COM),C)$RPC_ACT(R,P,C) = YES;
    db.add("RPCG_PTRAN", """select k.r, k.p, k.c, k.cg as c2, k.c as cg, k.cg as cg2 from t_red_cgg k
                            where k.cg2 = k.c and in_RPC(k.r,k.p,k.c) and in_COM(k.cg) and in_RPC_ACT(k.r,k.p,k.cg)""")
    # --- RPCG_PTRAN(RPC_ACT(RP,%PGPRIM%),C,CG,C)$(RP_PG(RP,CG)$RPC_AFLO(RP,C)) = YES;
    db.add("RPCG_PTRAN", """select a.r, a.p, a.cg as c, f.cg as c2, g.cg, f.cg as cg2 from RPC_ACT a
                            join RP_PG g on g.r=a.r and g.p=a.p join RPC_AFLO f on f.r=a.r and f.p=a.p
                            where a.cg='ACT' and in_COM(f.cg)""")
    # --- RPCG_PTRAN(RP_SGS,C,COM,CG,CG2) = NO;
    db.remove("RPCG_PTRAN", where="in_RP_SGS(r,p)")
    # --- LOOP(RPCG_PTRAN(RP_FLO(R,P),C,COM,CG,CG2), IF(RPC_ACT(R,P,C), RPC_FFUNC(R,P,COM) = YES; ELSE RPC_FFUNC(R,P,C) = YES));
    db.add("RPC_FFUNC", """select r, p, case when in_RPC_ACT(r,p,c) then c2 else c end as c from RPCG_PTRAN
                           where in_RP_FLO(r,p)""")
    # --- RPC_FFUNC(RPC)$(RPC_ACT(RPC)+RPC_EMIS(RPC)) = NO;
    db.remove("RPC_FFUNC", where="in_RPC(r,p,c) and (in_RPC_ACT(r,p,c) or in_RPC_EMIS(r,p,c))")
    # --- RPC_FFUNC(RPC_AFLO(RP_XRED(RP),C))$(RP_PGACT(RP)->TRACKPC(RP,C)) = NO;
    db.remove("RPC_FFUNC", where="""in_RPC_AFLO(r,p,c) and in_RP_XRED(r,p)
                                   and (not in_RP_PGACT(r,p) or exists(select 1 from t_red_pc k where k.r=RPC_FFUNC.r and k.p=RPC_FFUNC.p and k.c=RPC_FFUNC.c))""")
    # --- RPCG_PTRAN(R,P,C,COM,CG,CG2)$(NOT RPC_FFUNC(R,P,C)+RPC_FFUNC(R,P,COM)) = NO;
    db.remove("RPCG_PTRAN", where="not (in_RPC_FFUNC(r,p,c) or in_RPC_FFUNC(r,p,c2))")
    # --- LOOP(RPCG_PTRAN(R,P,C,COM,CG,CG2), RPCC_FFUNC(R,P,CG,CG2) = YES);
    db.add("RPCC_FFUNC", "select r, p, cg, cg2 from RPCG_PTRAN")
    # --- OPTION CLEAR=CG_GRP,RP_XRED<RPC_ACT,CLEAR=RP_CGG;
    db.assign("RP_XRED", "select distinct r, p from RPC_ACT")


def turned_off(db: DB):
    """An upper or fixed activity bound of zero turns the process off in that period and timeslice."""
    # --- LOOP((R,T,P,S,BDUPX)$((ACT_BND(R,T,P,S,BDUPX) EQ 0)$ACT_BND(R,T,P,S,BDUPX)),
    #       RTPS_OFF(R,T,P,S)$RPS_PRCTS(R,P,S) = YES);
    db.add("RTPS_OFF", """select a.r, a.y, a.p, a.s from ACT_BND a where a.l in ('UP','FX') and a.value = 0
                          and in_MILESTONYR(a.y) and in_RPS_PRCTS(a.r,a.p,a.s)""")
    # --- LOOP((RTPCS_OUT(R,T,P,C,S),RPCS_VAR(RP_STD(R,P),C,S)),
    #       IF(RPC_FFUNC(R,P,C), RTPS_OFF(R,T,P,TS)$(PRC_TS(R,P,TS)*RS_TREE(R,S,TS)) = YES;
    #       ELSEIF RPC_ACT(R,P,C), RTPS_OFF(R,T,P,S) = YES));
    db.tmp("t_red_out", """select o.r, o.y, o.p, o.c, o.s from RTPCS_OUT o
                           where in_RPCS_VAR(o.r,o.p,o.c,o.s) and in_RP_STD(o.r,o.p) and in_MILESTONYR(o.y)""")
    db.add("RTPS_OFF", """select o.r, o.y, o.p, t.s from t_red_out o join PRC_TS t on t.r=o.r and t.p=o.p
                          where in_RPC_FFUNC(o.r,o.p,o.c) and in_RS_TREE(o.r,o.s,t.s)""")
    db.add("RTPS_OFF", """select o.r, o.y, o.p, o.s from t_red_out o
                          where not in_RPC_FFUNC(o.r,o.p,o.c) and in_RPC_ACT(o.r,o.p,o.c)""")
    # --- OPTION CLEAR=RXX;
    #     LOOP(RTPS_OFF(R,T,P,S),IF(RP_STD(R,P),RTCS_SING(R,T,C,S,IO)$TOP(R,P,C,IO) = YES;
    #                                     ELSE RTCS_SING(R,T,C,S,'OUT')$RPC_IRE(R,P,C,'IMP') = YES));
    db.add("RTCS_SING", """select o.r, o.y, t.c, o.s, t.io from RTPS_OFF o join TOP t on t.r=o.r and t.p=o.p
                           where in_RP_STD(o.r,o.p)
                           union
                           select o.r, o.y, i.c, o.s, 'OUT' as io from RTPS_OFF o join RPC_IRE i on i.r=o.r and i.p=o.p
                           where i.ie='IMP' and not in_RP_STD(o.r,o.p)""")
    # --- LOOP(RTCS_SING(R,T,C,S,IO),RXX(R,C,IO) = YES);
    #     RXX(ENV,'IN') = NO; RXX(DEM,'IN') = NO; RXX(R,C,'IN')$RC_AGP(R,C,'LO') = NO;
    db.tmp("t_red_x", """select distinct r, c, io from RTCS_SING
                         where not (io = 'IN' and (in_ENV(r,c) or in_DEM(r,c) or in_RC_AGP(r,c,'LO')))""")
    # --- LOOP((R,T,COM,C)$(RXX(R,C,'OUT')$COM_AGG(R,T,COM,C)),TRACKC(R,C) = YES);
    #     RXX(TRACKC,'OUT') = NO;
    db.x("""delete from t_red_x x where x.io = 'OUT'
            and exists(select 1 from COM_AGG a where a.r=x.r and a.c2=x.c and in_MILESTONYR(a.y))""")
    # --- RC_IOP(RXX(R,C,IO),P)$TOP(R,P,C,IO) = YES;
    #     RC_IOP(RXX(R,C,'IN'),P)$RPC_IRE(R,P,C,'EXP') = YES;
    #     RC_IOP(RXX(R,C,'OUT'),P)$RPC_IRE(R,P,C,'IMP') = YES;
    db.tmp("t_red_iop", """select x.r, x.c, x.io, t.p from t_red_x x join TOP t on t.r=x.r and t.c=x.c and t.io=x.io
                           union
                           select x.r, x.c, x.io, i.p from t_red_x x join RPC_IRE i on i.r=x.r and i.c=x.c
                           where (x.io = 'IN' and i.ie = 'EXP') or (x.io = 'OUT' and i.ie = 'IMP')""")
    # --- RXX(RXX(R,C,IO))$(SUM(RC_IOP(R,C,IO,P),1) NE 1) = NO;
    db.x("""delete from t_red_x x where (select count(*) from t_red_iop k where k.r=x.r and k.c=x.c and k.io=x.io) <> 1""")
    # --- RTCS_SING(R,T,C,S,IO)$(NOT RXX(R,C,IO)) = NO;
    db.remove("RTCS_SING", where="not exists(select 1 from t_red_x x where x.r=RTCS_SING.r and x.c=RTCS_SING.c and x.io=RTCS_SING.io)")
    # --- LOOP(RTCS_SING(R,T,C,S,IO--1),
    #       LOOP(TOP(R,P,C,IO)$(SUM(COM$TOP(R,P,COM,IO),1)=1), RTPS_OFF(R,T,P,S)$RPS_PRCTS(R,P,S) = YES));
    #     (IO--1: the other side; a consumer whose only input, or a producer whose only output, is the commodity)
    db.add("RTPS_OFF", """select g.r, g.y, t.p, g.s from RTCS_SING g
                          join TOP t on t.r=g.r and t.c=g.c and t.io = case g.io when 'IN' then 'OUT' else 'IN' end
                          where (select count(*) from TOP u where u.r=t.r and u.p=t.p and u.io=t.io) = 1
                            and in_RPS_PRCTS(g.r,t.p,g.s)""")
    # --- RHS_COMPRD(R,T,C,S)$RTCS_SING(R,T,C,S,'OUT') = NO;
    db.remove("RHS_COMPRD", where="in_RTCS_SING(r,y,c,s,'OUT')")
    # --- OPTION CLEAR=TRACKC,CLEAR=RC_IOP;
    #     RTPS_OFF(RTPS_OFF(R,T,P,S))$PRC_MAP(R,'STG',P) = NO;
    db.remove("RTPS_OFF", where="in_PRC_MAP(r,'STG',p)")
    # --- RTPS_OFF(R,T,P,TS) $= SUM(RS_BELOW(R,S,TS)$RTPS_OFF(R,T,P,S),YES);
    db.add("RTPS_OFF", "select o.r, o.y, o.p, b.s2 as s from RTPS_OFF o join RS_BELOW b on b.r=o.r and b.s=o.s")
    # --- ACT_BND(RTPS_OFF(RTP_VARA(R,T,P),S),'UP')$PRC_TS(R,P,S) = EPS;
    db.put("ACT_BND", """select o.r, o.y, o.p, o.s, 'UP' as l, 0.0 as value from RTPS_OFF o
                         where in_RTP_VARA(o.r,o.y,o.p) and in_PRC_TS(o.r,o.p,o.s)""", zero="eps")
    # --- ACT_BND(RTPS_OFF(R,T,P,S),BD)$(NOT PRC_TS(R,P,S)) = 0;
    db.remove("ACT_BND", where="l in ('LO','UP','FX') and in_RTPS_OFF(r,y,p,s) and not in_PRC_TS(r,p,s)")
    # --- RTPCS_OUT(RTPC(RTP(R,T,P),C),S)$RTPS_OFF(R,T,P,S) = YES;
    db.add("RTPCS_OUT", """select k.r, k.y, k.p, k.c, o.s from RTPC k join RTPS_OFF o on o.r=k.r and o.y=k.y and o.p=k.p
                           where in_RTP(k.r,k.y,k.p)""")
    # --- RTP_VARA(R,T,P)$(SUM(PRC_TS(R,P,TS)$(NOT RTPS_OFF(R,T,P,TS)),1) EQ 0) = NO;
    db.remove("RTP_VARA", where="""in_MILESTONYR(y) and not exists(select 1 from PRC_TS t where t.r=RTP_VARA.r and t.p=RTP_VARA.p
                                                                 and not in_RTPS_OFF(RTP_VARA.r,RTP_VARA.y,RTP_VARA.p,t.s))""")


# ---------------------------------------------------------------------------
def set_bound(db: DB, rel, side, value):
    """VAR_ACT.LO or .UP (side 'lower' / 'upper') = value (an SQL expression on the row `k` of `rel`, which has the
    columns r, y, y2, p, s of VAR_ACT): the row of B_VAR_ACT changed, or added with the default of the other side."""
    db.x(f"""update "B_VAR_ACT" b set {side} = {value} from {rel} k
             where b.d0=k.r and b.d1=k.y and b.d2=k.y2 and b.d3=k.p and b.d4=k.s""")
    lo, up = ("0.0", value) if side == "upper" else (value, "'inf'::double")
    db.x(f"""insert into "B_VAR_ACT" select k.r, k.y, k.y2, k.p, k.s, {lo}, {up} from {rel} k
             where not exists(select 1 from "B_VAR_ACT" b where b.d0=k.r and b.d1=k.y and b.d2=k.y2 and b.d3=k.p and b.d4=k.s)""")


def flow_bounds(db: DB):
    """bnd_flo.mod 34-40, REDUCE YES: a bound on a flow replaced by the activity is a bound on the activity.
    As BND_ACT has been set before this, MAX/MIN can be used; FX bound consistency cannot be guaranteed."""
    if level(db) != "YES":
        return
    db.x('create table if not exists "B_VAR_ACT" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.bounds.add("VAR_ACT")
    # --- LOOP(RTPCS_VARF(R,T,P,C,S)$(((NOT PRC_VINT(R,P))*RPC_ACT(R,P,C))$FLO_BND(R,T,P,C,S,'LO')),
    #       %VAR%_ACT.LO(R,T,T,P,S) = MAX(%VAR%_ACT.LO(R,T,T,P,S),FLO_BND(R,T,P,C,S,'LO')/PRC_ACTFLO(R,T,P,C)));
    #     ... 'UP': %VAR%_ACT.UP(R,T,T,P,S) = MIN(%VAR%_ACT.UP(R,T,T,P,S),FLO_BND(R,T,P,C,S,'UP')/PRC_ACTFLO(R,T,P,C)));
    #     ... 'FX': %VAR%_ACT.FX(R,T,T,P,S) = FLO_BND(R,T,P,C,S,'FX')/PRC_ACTFLO(R,T,P,C));
    db.tmp("t_red_fb", """select f.r, f.y, f.y as y2, f.p, f.s, f.l, f.cg, f.value / v_PRC_ACTFLO(f.r,f.y,f.p,f.cg) as b from FLO_BND f
                          where f.l in ('LO','UP','FX') and in_MILESTONYR(f.y) and in_RTPCS_VARF(f.r,f.y,f.p,f.cg,f.s)
                            and not in_PRC_VINT(f.r,f.p) and in_RPC_ACT(f.r,f.p,f.cg)""")
    for l, side, agg, fn in (("LO", "lower", "max", "greatest"), ("UP", "upper", "min", "least")):
        db.tmp("t_red_b", f"select r, y, y2, p, s, {agg}(b) as b from t_red_fb where l = '{l}' group by r, y, y2, p, s")
        db.x(f"""insert into "B_VAR_ACT" select k.r, k.y, k.y2, k.p, k.s, 0.0, 'inf'::double from t_red_b k
                 where not exists(select 1 from "B_VAR_ACT" b where b.d0=k.r and b.d1=k.y and b.d2=k.y2 and b.d3=k.p and b.d4=k.s)""")
        db.x(f"""update "B_VAR_ACT" b set {side} = {fn}(b.{side}, k.b) from t_red_b k
                 where b.d0=k.r and b.d1=k.y and b.d2=k.y2 and b.d3=k.p and b.d4=k.s""")
    db.tmp("t_red_b", """select r, y, y2, p, s, arg_max(b, cg) as b from t_red_fb where l = 'FX' group by r, y, y2, p, s""")
    set_bound(db, "t_red_b", "lower", "k.b")
    set_bound(db, "t_red_b", "upper", "k.b")
