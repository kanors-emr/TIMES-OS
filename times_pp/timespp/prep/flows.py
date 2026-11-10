# SPDX-License-Identifier: GPL-3.0-or-later
"""pp_prelv.vda, pp_qafs.mod and the flow part of ppmain.mod: VEDA flow attributes before levelling, checks of
FLO_SHAR, market shares, and the flow attributes by timeslice."""
from ..controls import unsupported
from ..engine import DB
from .chp import pp_chp

from . import dynslite, grids


# ---------------------------------------------------------------------------
def prelv_flop(db: DB):
    """pp_prelv.vda, VDA_FLOP: flows given per unit of activity become FLO_FUNC / FLO_SUM between the primary group
    and each other commodity or group.  Exercised so far: single commodities outside the primary group (the last
    FLO_SUM statement).  The branches for user-defined groups are written from the source and not yet exercised by a model; residual
    ACT_FLO groups (RPC_AFLO) stop."""
    x = db.x
    # --- TRACKPC(RPC_SPG(R,P,C))$((NOT RPG_1ACE(R,P,C,C))$RPC_ACE(R,P,%PGPRIM%)) = YES;
    #     VDA_FLOP(R,LL,P,C,S)$((NOT KEEP_FLOF(R,P,C))$TRACKPC(R,P,C)) = 0;
    db.tmp("t_tpc", "select r, p, c from RPC_SPG k where not in_RPG_1ACE(k.r,k.p,k.c,k.c) and in_RPC_ACE(k.r,k.p,'ACT')")
    x("""delete from VDA_FLOP a where not in_KEEP_FLOF(a.r,a.p,a.cg)
         and exists(select 1 from t_tpc k where k.r=a.r and k.p=a.p and k.c=a.cg)""")
    # --- OPTION RPC_AFLO < ACT_FLO, RP_GRP < VDA_FLOP, PRC_ACT < RP_GRP, CLEAR=ACT_FLO,CLEAR=KEEP_FLOF,CLEAR=TRACKPC;
    #     before that:  ACT_FLO(R,LL,P,C,S)$RPS_PRCTS(R,P,S) = 0;    (flows given below the timeslices of the process stay)
    db.tmp("t_aflo", "select distinct r, p, cg from ACT_FLO a where not in_RPS_PRCTS(a.r,a.p,a.s)")
    db.clear("ACT_FLO")
    db.tmp("t_grp", "select distinct r, p, cg from VDA_FLOP where in_REG(r) and in_PRC(p)")
    db.tmp("t_act", "select distinct r, p from t_grp")
    db.clear("KEEP_FLOF")
    # --- TRACKPC(RP_GRP(RPC)) = YES; RP_GRP(TRACKPC) = NO;
    db.tmp("t_tpc", "select r, p, cg as c from t_grp where in_RPC(r,p,cg)")
    x("delete from t_grp g where exists(select 1 from t_tpc k where k.r=g.r and k.p=g.p and k.c=g.cg)")
    # --- RP_XRED(PRC_ACT(R,P)) = (NOT RP_PGFLO(R,P)+RP_PGACT(R,P)+RP_SGS(R,P))$(CHP(R,P)->RP_XRED(R,P));
    #     (NOT has lower precedence than + in GAMS: the test is "none of the three")
    db.tmp("t_xr", """select r, p, (not (in_RP_PGFLO(r,p) or in_RP_PGACT(r,p) or in_RP_SGS(r,p)))
                                   and ((not in_CHP(r,p)) or in_RP_XRED(r,p)) as yes from t_act""")
    x("delete from RP_XRED a where exists(select 1 from t_xr k where k.r=a.r and k.p=a.p)")
    db.add("RP_XRED", "select r, p from t_xr where yes")
    # --- RPC_AFLO(TRACKPC(RP_STD(RP_XRED),C)) = YES;  RPC_AFLO(R,P,C)$(TRACKPC(R,P,C)->RPC_PG(R,P,C)) = NO;
    #     ACT_FLO(R,V,P,C,S)$RPC_AFLO(R,P,C) $= VDA_FLOP(R,V,P,C,S);  VDA_FLOP(RTP,C,S)$ACT_FLO(RTP,C,S) = 1;
    #     The flows of RPC_AFLO keep their coefficient as ACT_FLO (it multiplies the transformation equation, eqptrans.mod)
    #     and enter the FLO_SUM / FLO_FUNC below with 1.
    x("insert into t_aflo select r, p, c from t_tpc where in_RP_STD(r,p) and in_RP_XRED(r,p)")
    db.assign("RPC_AFLO", """select distinct a.r, a.p, a.cg from t_aflo a where not in_RPC_PG(a.r,a.p,a.cg)
                             and exists(select 1 from t_tpc k where k.r=a.r and k.p=a.p and k.c=a.cg)""")
    db.put("ACT_FLO", """select v.r, v.y, v.p, v.cg, v.s, v.value from VDA_FLOP v
                         where in_RPC_AFLO(v.r,v.p,v.cg) and in_MODLYEAR(v.y) and in_REG(v.r)""", zero="eps")
    x("""update VDA_FLOP set value = 1 where in_RTP(r,y,p) and exists(select 1 from ACT_FLO a
           where a.r=VDA_FLOP.r and a.y=VDA_FLOP.y and a.p=VDA_FLOP.p and a.cg=VDA_FLOP.cg and a.s=VDA_FLOP.s)""")
    # --- RP_GRP(R,P,CG)$(NOT SUM(RPC(R,P,C)$COM_GMAP(R,CG,C),1)) = NO;  PRC_CG(RP_GRP) = YES;
    x("""delete from t_grp g where not exists(select 1 from RPC k join COM_GMAP m on m.r=k.r and m.c=k.c
                                              where k.r=g.r and k.p=g.p and m.cg=g.cg)""")
    db.add("PRC_CG", "select r, p, cg from t_grp")
    # --- LOOP(TRACKPC(RPC_PG(R,P,C)),TRACKP(R,P)=YES);
    db.tmp("t_tp", "select distinct r, p from t_tpc where in_RPC_PG(r,p,c)")
    # --- VDA_FLOP(RTP(R,V,P),C,ANNUAL)$((RPC_PG(R,P,C)*(NOT TRACKPC(R,P,C)))$TRACKP(R,P)) = 1;
    db.put("VDA_FLOP", """select k.r, k.y, k.p, g.c as cg, 'ANNUAL' as s, 1.0 as value from RTP k join RPC_PG g on g.r=k.r and g.p=k.p
                          where exists(select 1 from t_tp t where t.r=k.r and t.p=k.p)
                            and not exists(select 1 from t_tpc q where q.r=g.r and q.p=g.p and q.c=g.c)""")
    # --- TRACKPC(RPC_PG) = NO;
    x("delete from t_tpc where in_RPC_PG(r,p,c)")
    # --- CG_GRP(RP_PG(R,P,CG2),CG)$RP_GRP(R,P,CG) = YES;
    #     RPCC_FFUNC(CG_GRP(TRACKP(R,P),CG2,CG))$SUM(RPC_SPG(R,P,C)$COM_GMAP(R,CG,C),1) = YES;  CG_GRP(RPCC_FFUNC) = NO;
    db.tmp("t_cg", "select g.r, g.p, q.cg as cg, g.cg as cg2 from t_grp g join RP_PG q on q.r=g.r and q.p=g.p")
    db.tmp("t_ff", """select * from t_cg g where exists(select 1 from t_tp t where t.r=g.r and t.p=g.p)
                        and exists(select 1 from RPC_SPG k join COM_GMAP m on m.r=k.r and m.c=k.c
                                   where k.r=g.r and k.p=g.p and m.cg=g.cg2)""")
    x("delete from t_cg g where exists(select 1 from t_ff f where f.r=g.r and f.p=g.p and f.cg=g.cg and f.cg2=g.cg2)")
    # --- LOOP(RPCC_FFUNC(R,P,CG2,CG),TRACKP(R,P) = NO);  TRACKP(RP)$(SUM(RPC_SPG(TRACKPC(RP,C)),1)<>1) = NO;
    x("delete from t_tp t where exists(select 1 from t_ff f where f.r=t.r and f.p=t.p)")
    x("""delete from t_tp t where (select count(*) from t_tpc k where k.r=t.r and k.p=t.p and in_RPC_SPG(k.r,k.p,k.c)) <> 1""")
    # --- RPCC_FFUNC(RP_PG(TRACKP(RP),CG),C) $= SUM(RPC_SPG(TRACKPC(RP,C)),1);  TRACKPC(RPC_SPG(TRACKP,C)) = NO;
    x("""insert into t_ff select q.r, q.p, q.cg, k.c as cg2 from RP_PG q join t_tp t on t.r=q.r and t.p=q.p
                         join t_tpc k on k.r=q.r and k.p=q.p where in_RPC_SPG(k.r,k.p,k.c)""")
    x("delete from t_tpc k where in_RPC_SPG(k.r,k.p,k.c) and exists(select 1 from t_tp t where t.r=k.r and t.p=k.p)")
    # --- FLO_FUNC(RTP(R,V,P),CG2,CG,S)$RPCC_FFUNC(R,P,CG2,CG) = VDA_FLOP(RTP,CG,S);
    x("""delete from FLO_FUNC a where in_RTP(a.r,a.y,a.p)
         and exists(select 1 from t_ff f where f.r=a.r and f.p=a.p and f.cg=a.cg and f.cg2=a.cg2)""")
    db.put("FLO_FUNC", """select v.r, v.y, v.p, f.cg, f.cg2, v.s, v.value from VDA_FLOP v join t_ff f on f.r=v.r and f.p=v.p and f.cg2=v.cg
                          where in_RTP(v.r,v.y,v.p)""", zero="eps")
    # --- FLO_SUM(RTP(R,V,P),CG2,C,CG,S)$(RPC_PG(R,P,C)$RPCC_FFUNC(R,P,CG2,CG)) = VDA_FLOP(RTP,C,S)*(1/PRC_ACTFLO(RTP,C));
    #     FLO_SUM(RTP(R,V,P),CG2,C,CG,S)$(RPC_PG(R,P,C)$CG_GRP(R,P,CG2,CG))     = VDA_FLOP(RTP,CG,S)*(1/PRC_ACTFLO(RTP,C));
    for tab, src in (("t_ff", "g.c"), ("t_cg", "f.cg2")):
        x(f"""delete from FLO_SUM a where in_RTP(a.r,a.y,a.p) and in_RPC_PG(a.r,a.p,a.c)
              and exists(select 1 from {tab} f where f.r=a.r and f.p=a.p and f.cg=a.cg and f.cg2=a.cg2)""")
        db.put("FLO_SUM", f"""select v.r, v.y, v.p, f.cg, g.c, f.cg2, v.s, v.value / v_PRC_ACTFLO(v.r,v.y,v.p,g.c) as value
                              from {tab} f join RPC_PG g on g.r=f.r and g.p=f.p
                              join VDA_FLOP v on v.r=f.r and v.p=f.p and v.cg={src} where in_RTP(v.r,v.y,v.p)""", zero="eps")
    # --- FLO_SUM(RTP(R,V,P),CG,C,COM,S)$(RP_PG(R,P,CG)*RPC_PG(R,P,C)*TRACKPC(R,P,COM)) $= VDA_FLOP(RTP,COM,S)*(1/PRC_ACTFLO(RTP,C));
    db.put("FLO_SUM", """select v.r, v.y, v.p, q.cg, g.c, k.c as cg2, v.s, v.value / v_PRC_ACTFLO(v.r,v.y,v.p,g.c) as value
                         from t_tpc k join RP_PG q on q.r=k.r and q.p=k.p join RPC_PG g on g.r=k.r and g.p=k.p
                         join VDA_FLOP v on v.r=k.r and v.p=k.p and v.cg=k.c where in_RTP(v.r,v.y,v.p)""", zero="eps")
    # --- OPTION CLEAR=TRACKP,CLEAR=TRACKPC,CLEAR=VDA_FLOP,CLEAR=CG_GRP,CLEAR=RPCC_FFUNC;
    db.clear("VDA_FLOP")


# ---------------------------------------------------------------------------
def veda_flow_attributes(db: DB):
    """pp_prelv.vda (VEDA attributes before levelling) and pp_qafs.mod (QA of FLO_SHAR)."""
    # ---- pp_prelv.vda
    # --- LOOP(PYR_S(V),NCAP_TLIFE(R,V,P)$PRC_RESID(R,'0',P) = PRC_RESID(R,'0',P));
    db.put("NCAP_TLIFE", "select a.r, v.y, a.p, a.value from PRC_RESID a, PYR_S v where a.y='0' and in_REG(a.r) and in_PRC(a.p)",
           zero="eps")
    # --- VDA_FLOP / ACT_FLO / KEEP_FLOF / FLO_EMIS / FLO_EFF blocks: all statements act only when one of these has data
    #     (FLO_EFF given in the input is FLO_EMIS by now: init_ext.vda copies it and clears it; this file makes it again
    #      for CHP processes below)
    # FLO_FUNCX enters pp_prelv.vda only through a negative value on ACT (FLO_FUNC from VDA_FLOP, the non-vintaged
    # multiplier option): not ported
    if db.q1("select count(*) from FLO_FUNCX where cg='ACT' and value < 0"):
        unsupported(db, "negative FLO_FUNCX on ACT (FLO_FUNC multipliers for non-vintaged processes, pp_prelv.vda)")
    if db.card("VDA_FLOP"):
        prelv_flop(db)
    if db.card("FLO_EMIS"):
        prelv_flo_emis(db)
    # --- OPTION NE<IRE_BND,...
    #     ('<' projects left to right: NE(ALL_R,COM) takes the first region index of IRE_BND(ALL_R,..,ALL_REG,..), the
    #      region of the bound, not the partner. Only that reading lets the line below keep a dummy import that has a
    #      bound: TOP_IRE('IMPEXP',C,R,C,P) has the region in R, as in GAMS.)
    db.assign("NE", "select distinct r, c from IRE_BND")
    # --- FLO_ASHAR(R,DM_YEAR,P,C,CG,S,BD) $= FLO_SHAR(R,DM_YEAR,P,C,CG,S,BD)$(NOT RP_STD(R,P)); FLO_SHAR(...)$FLO_ASHAR(...) = 0;
    db.put("FLO_ASHAR", "select r, y, p, c as cg, cg as cg2, s, l, value from FLO_SHAR where in_DM_YEAR(y) and in_REG(r) and not in_RP_STD(r,p)",
           zero="eps")
    db.zap("FLO_SHAR", "in_FLO_ASHAR(r,y,p,c,cg,s,l)")
    # --- NCAP_CHPR(RTP(R,V,P),'N') $= NCAP_CHPR(R,'0',P,'N');
    db.put("NCAP_CHPR", "select k.r, k.y, k.p, 'N' as l, n.value from RTP k join NCAP_CHPR n on n.r=k.r and n.p=k.p and n.y='0' and n.l='N'",
           zero="eps")
    if db.card("FLO_FR"):
        prelv_flo_fr(db)
    # --- TOP_IRE('IMPEXP',C,R,C,P(DUMIMP))$(NOT NE(R,C)) = NO;      dummy imports without an IRE_BND
    db.remove("TOP_IRE", where="r='IMPEXP' and c=c2 and in_DUMIMP(p) and in_REG(r2) and not in_NE(r2,c)")
    db.clear("NE")
    # --- $IFI %POWERFLO%==YES $include powerflo.vda      (grid nodes; with gasgrids.vda)
    grids.main(db)
    com_bnd_n(db)
    # --- $IF NOT %RTS%==S $BATINCLUDE dynslite.vda PRELEV
    dynslite.prelev(db)
    qafs(db)


def com_bnd_n(db: DB):
    """pp_prelv.vda lines 116-122, 'Set COM_VAR default bounds': COM_BNDNET / COM_BNDPRD of type N are switches.
    An N given under year 0 holds for every period without one; then, on every timeslice of the variable without a
    bound of that type: a negative N gives LO = -INF (a free variable), an N of EPS gives FX = EPS, a positive N nothing.
    (BD in BDLOX = LO, FX:  value (EPS-INF$BDNEQ(BD))$(-SIGN(N)=1$BDNEQ(BD)), i.e. LO: -INF if N < 0;  FX: EPS if N = 0.)"""
    for n in ("COM_BNDNET", "COM_BNDPRD"):
        if not db.q1(f"select count(*) from {n} where l='N'"):
            continue
        # --- COM_BNDNET(R,T,C,ANNUAL(S),'N')$(NOT COM_BNDNET(R,T,C,S,'N')) $= COM_BNDNET(R,'0',C,S,'N');
        db.put(n, f"""select o.r, t.y, o.c, o.s, 'N' as l, o.value from {n} o, MILESTONYR t
                      where o.y='0' and o.s='ANNUAL' and o.l='N' and in_REG(o.r)
                      and not exists(select 1 from {n} b where b.r=o.r and b.y=t.y and b.c=o.c and b.s=o.s and b.l='N')""", zero="eps")
        # --- COM_BNDNET(RTCS_VARC(RTC,S),BDLOX(BD))$((NOT COM_BNDNET(RTC,S,BD))$COM_BNDNET(RTC,'ANNUAL','N')) =
        #       (EPS-INF$BDNEQ(BD))$(-SIGN(COM_BNDNET(RTC,'ANNUAL','N'))=1$BDNEQ(BD));
        db.tmp("t_bndn", f"""select k.r, k.y, k.c, k.s, n.value as nv from RTCS_VARC k
                             join {n} n on n.r=k.r and n.y=k.y and n.c=k.c and n.s='ANNUAL' and n.l='N'""")
        for bd, cond, val in (("LO", "nv < 0", "-'inf'::DOUBLE"), ("FX", "nv = 0", "0.0")):
            db.put(n, f"""select a.r, a.y, a.c, a.s, '{bd}' as l, {val} as value from t_bndn a where {cond}
                          and not exists(select 1 from {n} b where b.r=a.r and b.y=a.y and b.c=a.c and b.s=a.s and b.l='{bd}')""",
                   zero="eps")


def prelv_flo_fr(db: DB):
    """pp_prelv.vda lines 99-109: levelised FLO_FR, and the aggregated ANNUAL variable for fractions.

    Clears RPC_CONLY and RVPCSL at the end, as line 112 does (OPTION CLEAR=NE,CLEAR=RVPCSL,CLEAR=RPC_CONLY).
    """
    from ..lvl import lvlfc
    bd = "l in ('LO','UP','FX')"
    # --- RPC_CONLY(RTP,C) $=SUM(L$FLO_FR(RTP,C,'ANNUAL',L),1);
    db.add("RPC_CONLY", "select r, y, p, c from FLO_FR where s='ANNUAL' and in_RTP(r,y,p)")
    # --- $BATINCLUDE pp_lvlfc.mod FLO_FR 'P,C' RPCS_VAR ',BD' ",'0','0'" ALL_TS T RPC_CONLY(R,T,P,C)
    lvlfc(db, "FLO_FR", ["p", "c"], "RPCS_VAR", "MILESTONYR", f"in_RPC_CONLY(a.r,a.y,a.p,a.c) and a.{bd}")
    # --- FLO_FR(RPC_CONLY(R,T,P,C),S,'N')=MIN(1,SUM(RS_BELOW1(R,S,TS)$RPCS_VAR(R,P,C,TS),G_YRFR(R,TS)))$TS_CYCLE(R,S);
    #     (T is MILESTONYR; '=' over every S: the 'N' entries of these flows are replaced)
    db.zap("FLO_FR", "l='N' and in_MILESTONYR(y) and in_RPC_CONLY(r,y,p,c)")
    db.put("FLO_FR", """select k.r, k.y, k.p, k.c, b.s, 'N' as l, least(1, sum(v_G_YRFR(b.r, b.s2) order by ord_s(b.s2))) as value
                        from RPC_CONLY k join RS_BELOW1 b on b.r=k.r
                        join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=k.c and v.s=b.s2
                        where in_MILESTONYR(k.y) and v_TS_CYCLE(k.r, b.s) <> 0
                        group by k.r, k.y, k.p, k.c, b.s""")
    # --- FLO_FR(RPC_CONLY(R,T,P,C),S,BD)$FLO_FR(R,T,P,C,S,BD)=FLO_FR(R,T,P,C,S,BD)*G_YRFR(R,S)$RPCS_VAR(R,P,C,S);
    #     (an EPS stays EPS on a flow timeslice)
    conly = f"{bd} and in_MILESTONYR(y) and in_RPC_CONLY(r,y,p,c)"
    db.zap("FLO_FR", f"{conly} and not in_RPCS_VAR(r,p,c,s)")
    db.x(f'update FLO_FR set value = value * v_G_YRFR(r, s) where {conly}')
    # --- IF(CARD(FLO_FR),
    #       RVPCSL(RTPC(R,T,P,C),TS(S+STOA(S)),BD)$(FLO_FR(R,'0',P,C,TS,BD)$FLO_FR(RTPC,S,BD)) = YES;
    #     (S+STOA(S) is ANNUAL)
    db.clear("RVPCSL")
    db.add("RVPCSL", """select distinct k.r, k.y, k.p, k.c, 'ANNUAL' as s, f.l from RTPC k
                        join FLO_FR f on f.r=k.r and f.y=k.y and f.p=k.p and f.c=k.c and f.l in ('LO','UP','FX')
                        where in_FLO_FR(k.r, '0', k.p, k.c, 'ANNUAL', f.l)""")
    #       RVPCSL(RTPC(R,T,P,C),S+STOA(S),BD)$FLO_FR(RTPC,S,'N') = NO;
    db.remove("RVPCSL", where="""exists(select 1 from FLO_FR f where f.r=RVPCSL.r and f.y=RVPCSL.y and f.p=RVPCSL.p
                                 and f.c=RVPCSL.c and f.l='N')""")
    #       RVPCSL(RTPC(R,T,P,C),S,'N')$TS_CYCLE(R,S) $= SUM(RVPCSL(RTPC,TS,BD),1));
    db.add("RVPCSL", """select distinct k.r, k.y, k.p, k.c, t.s, 'N' as l from RVPCSL k join TS_CYCLE t on t.r=k.r
                        where k.l in ('LO','UP','FX') and t.value <> 0""")
    # --- FLO_FR(RVPCSL(R,T,P,C,S,'N'))$(NOT RPCS_VAR(R,P,C,S)) = EPS+1$ANNUAL(S);
    db.put("FLO_FR", """select r, y, p, c, s, l, case when s='ANNUAL' then 1.0 else 0.0 end as value from RVPCSL
                        where l='N' and not in_RPCS_VAR(r,p,c,s)""", zero="eps")
    db.clear("RVPCSL", "RPC_CONLY")


def prelv_flo_emis(db: DB):
    """pp_prelv.vda, 'Preprocessing of FLO_EMIS': emission factors on flows and on activity become FLO_SUM entries."""
    x = db.x
    # --- PRC_ACTFLO(R,V,P,C) $= FLO_EMIS(R,V,P,%PGPRIM%,C,'ANNUAL')$PRC_MAP(R,'STG',P);
    db.put("PRC_ACTFLO", """select r, y, p, c as cg, value from FLO_EMIS where cg='ACT' and s='ANNUAL' and in_REG(r)
                            and in_MODLYEAR(y) and in_PRC_MAP(r,'STG',p)""", zero="eps")
    # --- IRE_FLOSUM(R,V,P,C(ACTCG),S,IE,COM,'OUT') $= FLO_EMIS(R,V,P,C,COM,S)$RP_AIRE(R,P,IE);
    db.put("IRE_FLOSUM", """select e.r, e.y, e.p, e.cg as c, e.s, a.ie, e.c as c2, 'OUT' as io, e.value
                            from FLO_EMIS e join RP_AIRE a on a.r=e.r and a.p=e.p
                            where e.cg='ACT' and in_COM(e.cg) and in_MODLYEAR(e.y)""", zero="eps")
    # --- OPTION RP_CGC <= FLO_EMIS;
    db.assign("RP_CGC", "select distinct r, p, cg, c from FLO_EMIS")
    # --- FLO_EMIS(RTP(R,V,P),C,C,S)$(RP_CGC(R,P,C,C)$RPC_PG(R,P,C)) = 1+(FLO_EMIS(RTP,C,C,S)-1)/PRC_ACTFLO(RTP,C);
    if db.q1("select count(*) from RP_CGC where cg=c and in_RPC_PG(r,p,c)"):
        unsupported(db, "FLO_EMIS of a primary-group commodity on itself")
    # --- RP_CGC(RP_IRE(R,P),CG,C)=NO; RP_CGC(RPC_STG,C)=NO;
    db.remove("RP_CGC", where="in_RP_IRE(r,p) or in_RPC_STG(r,p,cg)")
    # --- RPCC_FFUNC(RP_CGC(RPC,COM)) = YES;  RP_CGC(RPCC_FFUNC(RPC,COM)) = NO;
    db.tmp("t_ffunc", "select r, p, cg as src, c as tgt from RP_CGC where in_RPC(r,p,cg)")
    db.remove("RP_CGC", where="in_RPC(r,p,cg)")
    # --- RPC_EMIS(R,P,C)$SUM(RPCC_FFUNC(R,P,COM,C),1) = NO;
    db.remove("RPC_EMIS", where="exists(select 1 from t_ffunc f where f.r=RPC_EMIS.r and f.p=RPC_EMIS.p and f.tgt=RPC_EMIS.cg)")
    # --- FSCK(RP_CGC(R,P,CG,COM),C)$(COM_GMAP(R,CG,C)$RPC(R,P,C)) = YES;
    db.tmp("t_fsck", """select g.r, g.p, g.cg, g.c as com, k.c from RP_CGC g join RPC k on k.r=g.r and k.p=g.p
                        where in_COM_GMAP(g.r, g.cg, k.c)""")
    # --- LOOP(FSCK(R,P,CG,COM,C), FLO_SUM(R,V,P,COM,C,COM,S) $= FLO_EMIS(R,V,P,CG,COM,S));         (the last group in entry order wins)
    db.put("FLO_SUM", """select e.r, e.y, e.p, e.c as cg, f.c, e.c as cg2, e.s, arg_max(e.value, u.ord) as value
                         from t_fsck f join FLO_EMIS e on e.r=f.r and e.p=f.p and e.cg=f.cg and e.c=f.com
                         join __uel u on u.label=e.cg where in_REG(e.r) and in_MODLYEAR(e.y)
                         group by e.r, e.y, e.p, e.c, f.c, e.s""", zero="eps")
    # --- RPC_EMIS(R,P,COM)$SUM(FSCK(R,P,CG,COM,C),1) = NO;
    db.remove("RPC_EMIS", where="exists(select 1 from t_fsck f where f.r=RPC_EMIS.r and f.p=RPC_EMIS.p and f.com=RPC_EMIS.cg)")
    # --- FLO_SUM(RTP(R,V,P),COM,C,COM,S)$(RPC_PG(R,P,C)$RP_CGC(R,P,%PGPRIM%,COM)) = FLO_EMIS(RTP,%PGPRIM%,COM,S)/PRC_ACTFLO(RTP,C);
    db.tmp("t_act", "select g.r, g.p, g.c as com, k.c from RP_CGC g join RPC_PG k on k.r=g.r and k.p=g.p where g.cg='ACT'")
    x("""delete from FLO_SUM a where in_RTP(a.r,a.y,a.p) and a.cg=a.cg2
         and exists(select 1 from t_act t where t.r=a.r and t.p=a.p and t.com=a.cg and t.c=a.c)""")
    db.put("FLO_SUM", """select e.r, e.y, e.p, e.c as cg, t.c, e.c as cg2, e.s, e.value / v_PRC_ACTFLO(e.r,e.y,e.p,t.c) as value
                         from t_act t join FLO_EMIS e on e.r=t.r and e.p=t.p and e.cg='ACT' and e.c=t.com
                         where in_RTP(e.r,e.y,e.p)""", zero="eps")
    # --- RP_CGC(R,P,%PGPRIM%,C) = NO;
    db.remove("RP_CGC", where="cg='ACT' and in_REG(r)")
    # --- LOOP(RP_CGC(R,P,CG,COM)$RPC_EMIS(R,P,COM), 'FLO_EMIS with no members of source group in process - ignored')
    db.tmp("t_none", "select r, p, cg, c as com from RP_CGC where in_REG(r) and in_COM(c) and in_RPC_EMIS(r,p,c)")
    for r, p, cg, com in db.q("select * from t_none"):
        db.log.append(f"*01 WARNING - FLO_EMIS with no members of source group in process - ignored: R={r} P={p} CG={cg} COM={com}")
    # --- FLO_SUM(RTP(R,V,P),COM,C,COM,ANNUAL)$RPC_PG(R,P,C) $= SUM(RP_CGC(R,P,CG,COM)$RPC_EMIS(R,P,COM),EPS);
    db.put("FLO_SUM", """select distinct k.r, k.y, k.p, t.com as cg, g.c, t.com as cg2, 'ANNUAL' as s, 0 as value
                         from t_none t join RTP k on k.r=t.r and k.p=t.p join RPC_PG g on g.r=t.r and g.p=t.p""", zero="eps")
    # --- OPTION CLEAR=RP_CGC, CLEAR=FSCK, CLEAR=RPC_EMIS, CG_GRP < RPCC_FFUNC;                       CG_GRP(R,P,target,source)
    db.clear("RP_CGC", "RPC_EMIS")
    # --- FLO_SUM(RTP(R,V,P),C,COM,C,S)$CG_GRP(R,P,C,COM) = FLO_EMIS(RTP,COM,C,S);
    x("""delete from FLO_SUM a where in_RTP(a.r,a.y,a.p) and a.cg=a.cg2
         and exists(select 1 from t_ffunc f where f.r=a.r and f.p=a.p and f.tgt=a.cg and f.src=a.c)""")
    db.put("FLO_SUM", """select e.r, e.y, e.p, e.c as cg, e.cg as c, e.c as cg2, e.s, e.value
                         from t_ffunc f join FLO_EMIS e on e.r=f.r and e.p=f.p and e.cg=f.src and e.c=f.tgt
                         where in_RTP(e.r,e.y,e.p)""", zero="eps")
    # --- FLO_EFF(RTP(R,V,P),C,COM,S)$((NOT CG_GRP(R,P,C,COM))$RPC_PG(R,P,COM)$CHP(R,P)) $= FLO_EMIS(RTP,%PGPRIM%,C,S);
    db.put("FLO_EFF", """select e.r, e.y, e.p, e.c as cg, g.c, e.s, e.value from FLO_EMIS e join RPC_PG g on g.r=e.r and g.p=e.p
                         where e.cg='ACT' and in_RTP(e.r,e.y,e.p) and in_CHP(e.r,e.p)
                           and not exists(select 1 from t_ffunc f where f.r=e.r and f.p=e.p and f.tgt=e.c and f.src=g.c)""", zero="eps")
    # --- OPTION ...,CLEAR=CG_GRP,CLEAR=RPCC_FFUNC,CLEAR=FLO_EMIS;
    db.clear("FLO_EMIS")


def seqsum(xs):
    """Left-to-right float addition, as GAMS sums. Python's sum() is compensated (exact) since 3.12, and the
    QA tests of pp_qafs compare such sums with 1 +- SHARETOL, where the last bit decides which share is relaxed."""
    t = 0.0
    for x in xs:
        t += x
    return t


def qafs(db: DB, tol=9e-5):
    """pp_qafs.mod: checks FLO_SHAR and turns redundant ANNUAL share bounds of a whole group into fixed shares."""
    if not db.card("FLO_SHAR"):
        return
    # --- OPTION RP_CCG <= FLO_SHAR;  LOOP(RP_CCG(R,P,C,CG)$(NOT RPC(R,P,C)$COM_GMAP(R,CG,C)), severe error)
    db.tmp("t_ccg", "select distinct r, p, c, cg from FLO_SHAR where in_REG(r) and in_PRC(p) and in_COM(c)")
    bad = db.q("select r, p, c, cg from t_ccg where not (in_RPC(r,p,c) and in_COM_GMAP(r,cg,c))")
    for r, p, c, cg in bad:
        db.log.append(f"*07 SEVERE ERROR - Unsupported FLO_SHARE: C not in RPC or CG, R={r} P={p} C={c} CG={cg}")
    if bad:
        # --- IF(PUTGRP, RP_CCG(R,P,C,CG)$(NOT COM_GMAP(R,CG,C)) = NO);
        db.x("delete from t_ccg where not in_COM_GMAP(r,cg,c)")
    # --- RTPGIG(R,'0',P,C,IO,CG)$(TOP(R,P,C,IO)$RP_CCG(R,P,C,CG)) = YES; LOOP(RTPGIG(..),RPG_RED(R,P,CG,IO) = YES);
    db.add("RPG_RED", "select distinct k.r, k.p, k.cg, t.io from t_ccg k join TOP t on t.r=k.r and t.p=k.p and t.c=k.c")
    # --- RP_GIC(RPG_RED(R,P,CG,IO),C)$(TOP(R,P,C,IO)$COM_GMAP(R,CG,C)) = YES;      members of the group on that side
    gic = {}
    for r, p, cg, io, c in db.q("""select g.r, g.p, g.cg, g.io, t.c from RPG_RED g join TOP t on t.r=g.r and t.p=g.p and t.io=g.io
                                   join __uel u on u.label=t.c where in_COM_GMAP(g.r,g.cg,t.c) order by u.ord"""):
        gic.setdefault((r, p, cg, io), []).append(c)
    io_of = {}
    for (r, p, cg, io), cs in gic.items():
        for c in cs:
            io_of.setdefault((r, p, cg, c), []).append(io)
    V = {y for (y,) in db.q("select y from MODLYEAR")}
    # RTP and COM_GMAP are only looked up for the processes and groups of FLO_SHAR: read for those only
    RTP = set(db.q("select k.r, k.y, k.p from RTP k semi join (select distinct r, p from FLO_SHAR) f on f.r=k.r and f.p=k.p"))
    BDNEQ, BDUPX, BDLOX = ("LO", "UP"), ("FX", "UP"), ("LO", "FX")
    fs = {(r, y, p, c, cg, s, l): v for r, y, p, c, cg, s, l, v in db.q("select r, y, p, c, cg, s, l, value from FLO_SHAR")}

    def ann(r, v, p, c, cg, bd):
        return fs.get((r, v, p, c, cg, "ANNUAL", bd), 0.0)

    def has(r, v, p, c, cg, bd):
        return (r, v, p, c, cg, "ANNUAL", bd) in fs

    # --- RTP_CGC(R,V,P,C,CG) $= SUM(BD$FLO_SHAR(R,V,P,C,CG,'ANNUAL',BD),1);
    #     RTP_CG(RTP(R,V,P),CG,IO) $= SUM(RTP_CGC(R,V,P,C,CG)$RP_GIC(R,P,CG,IO,C),1);
    rtp_cg = set()
    for (r, y, p, c, cg, s, l) in fs:
        if s == "ANNUAL" and y in V and (r, y, p) in RTP:
            for io in io_of.get((r, p, cg, c), ()):
                rtp_cg.add((r, y, p, cg, io))
    # --- UNCD7(R,'0',P,C,CG,.,BD) $= FLO_SHAR(R,LL,P,C,CG,S,BD)$(NOT ANNUAL(S));
    #     LOOP((UNCD7(..),RP_GIC(R,P,CG,IO,C)), RTP_CG(R,V,P,CG,IO) = NO);       groups with shares below ANNUAL are left alone
    non_ann = set()
    for (r, y, p, c, cg, s, l) in fs:
        if s != "ANNUAL":
            for io in io_of.get((r, p, cg, c), ()):
                non_ann.add((r, p, cg, io))
    rtp_cg = {k for k in rtp_cg if (k[0], k[2], k[3], k[4]) not in non_ann}
    # --- RTP_CGC(R,V,P,C,CG) $= FLO_SHAR(R,V,P,C,CG,'ANNUAL','FX');
    #     LOOP(RTP_CGC$(LO+UP): warning; RTPGIG(R,V,P,C,'OUT',CG) = YES);  FLO_SHAR(R,V,P,C,CG,S,BDNEQ)$RTPGIG(..) = 0;
    cgc = {(r, y, p, c, cg) for (r, y, p, c, cg, s, l) in fs if s == "ANNUAL" and l == "FX" and y in V}
    # the LO / UP records of each (r, y, p, c, cg) of CGC: an index instead of a scan of FLO_SHAR per conflict
    # (the loop below only deletes records, so a key listed here and still in fs is one the scan would find)
    lohi = {}
    for k in fs:
        if k[6] in BDNEQ and k[:5] in cgc:
            lohi.setdefault(k[:5], []).append(k)
    for (r, y, p, c, cg) in sorted(cgc):
        # $(LO+UP) is true for an EPS sum too: an UP given as 0 in a DD file ($ONEPS) beside an FX filled with EPS by
        # interpolation option 2 is dropped)
        lu = ann(r, y, p, c, cg, "LO") + ann(r, y, p, c, cg, "UP")
        given = [fs[k] for k in ((r, y, p, c, cg, "ANNUAL", "LO"), (r, y, p, c, cg, "ANNUAL", "UP")) if k in fs]
        if lu or (given and all(v == 0 for v in given)):
            db.log.append(f"*01 WARNING - FLO_SHAR conflict: Both FX + LO/UP specified, latter ignored, R={r} Y={y} P={p} CG={cg} C={c}")
            for k in [k for k in lohi.get((r, y, p, c, cg), ()) if k in fs]:
                del fs[k]
    # --- FLO_SHAR(RTP(R,V,P),C,CG,S(TSL),BD('UP'))$((FLO_SHAR(..)$COM_GMAP(R,CG,C) GE 1)$FLO_SHAR(..)) = 0;
    gmap = set(db.q("select m.r, m.cg, m.c from COM_GMAP m semi join (select distinct r, cg from FLO_SHAR) f on f.r=m.r and f.cg=m.cg"))
    for k in [k for k, v in fs.items() if k[5] == "ANNUAL" and k[6] == "UP" and k[1] in V and k[:3] in RTP
              and (k[0], k[4], k[3]) in gmap and v >= 1]:
        del fs[k]
    # --- FLO_SHAR(R,V,P,C,CG,S,BDUPX(BD))$((FLO_SHAR LT tol)$FLO_SHAR) = EPS;   ..BDLOX..$((ABS(FLO_SHAR-1) LT tol)$FLO_SHAR) = 1;
    for k, v in fs.items():
        if k[1] in V and v != 0:
            if k[6] in BDUPX and v < tol:
                fs[k] = v = 0.0
            if v != 0 and k[6] in BDLOX and abs(v - 1) < tol:
                fs[k] = 1.0

    # --- groups in which every member has a fixed share: one of them is redundant
    marked = set()                      # RTPGIG(R,V,P,CG,IO,C)
    for (r, y, p, cg, io) in sorted(rtp_cg):
        mem = gic[(r, p, cg, io)]
        if any((r, y, p, c, cg) not in cgc for c in mem):
            continue
        z = seqsum(ann(r, y, p, c, cg, "FX") + 8 for c in mem)
        f = z % 8
        if abs(f - 1) > .001:
            db.log.append(f"*07 SEVERE ERROR - Inconsistent sum of fixed FLO_SHAREs in Group, R={r} P={p} V={y} CG={cg} SUM={f:.5f}")
        f = max(f - 1, f / z * 8 - tol)
        for c in mem:
            if ann(r, y, p, c, cg, "FX") > f:
                marked.add((r, y, p, cg, io, c))
                break
    # --- IF(CARD(RTPGIG), LOOP(IO,FLO_SHAR(R,V,P,C,CG,S,BD)$RTPGIG(R,V,P,CG,IO,C) = 0);
    if marked:
        drop = {(r, y, p, c, cg) for (r, y, p, cg, io, c) in marked}
        for k in [k for k in fs if k[:5] in drop]:
            del fs[k]

    # --- groups in which every member has FX or UP, and the bounds sum to at most 1: all are binding
    cgc |= {(r, y, p, c, cg) for (r, y, p, c, cg, s, l) in fs if s == "ANNUAL" and l == "UP" and y in V}
    lacking = {k[:5] for k in marked}
    out = set()                         # RTPGIG(R,V,P,CG,'OUT',C)
    for (r, y, p, cg, io) in sorted(rtp_cg):
        mem = gic[(r, p, cg, io)]
        if (r, y, p, cg, io) in lacking or any((r, y, p, c, cg) not in cgc for c in mem):
            continue
        f = seqsum(ann(r, y, p, c, cg, bd) for c in mem for bd in BDUPX)
        if f < 1 + tol:
            z = 1
            for c in mem:
                my = ann(r, y, p, c, cg, "UP")
                if my > f - 1 and has(r, y, p, c, cg, "UP"):       # $MY_F: EPS counts as given
                    z = 0
                    out.add((r, y, p, cg, c))
                    break
            if f < 1 - (0 if z else tol):
                db.log.append(f"*07 SEVERE ERROR - Defective sum of FX and UP FLO_SHAREs in Group, R={r} P={p} V={y} CG={cg} SUM={f:.5f}"
                              + ("" if z else " (Auto-relaxed)"))

    def members_of_marked(out):
        res = set()
        for (r, y, p, cg, c) in out:
            for io in io_of.get((r, p, cg, c), ()):
                for c2 in gic[(r, p, cg, io)]:
                    res.add((r, y, p, cg, c2))
        return res

    # --- FLO_SHAR(..,'ANNUAL','FX')$(NOT RTPGIG(R,V,P,CG,'OUT',C)) $= FLO_SHAR(..,'ANNUAL','UP')$RTP_CGC(R,V,P,CG,C);
    #     FLO_SHAR(..,'ANNUAL',BDNEQ)$RTP_CGC(R,V,P,CG,C) = 0;
    grp = members_of_marked(out)
    for (r, y, p, cg, c) in grp:
        if (r, y, p, cg, c) not in out and has(r, y, p, c, cg, "UP"):
            fs[(r, y, p, c, cg, "ANNUAL", "FX")] = ann(r, y, p, c, cg, "UP")
        for bd in BDNEQ:
            fs.pop((r, y, p, c, cg, "ANNUAL", bd), None)

    # --- groups whose LO/FX shares sum to (more than) 1: all are binding
    has_lo = {(r, y, p, c, cg) for (r, y, p, c, cg, s, l) in fs if s == "ANNUAL" and l in BDLOX and y in V}
    out = set()
    for (r, y, p, cg, io) in sorted(rtp_cg):
        mem = gic[(r, p, cg, io)]
        if not any((r, y, p, c, cg) in has_lo for c in mem):
            continue
        f = seqsum(ann(r, y, p, c, cg, bd) for c in mem for bd in BDLOX)
        if f > 1 - tol:
            over = f > 1 + tol
            if over:
                db.log.append(f"*07 SEVERE ERROR - Excessive sum of FX and LO FLO_SHAREs in Group, R={r} P={p} V={y} CG={cg} SUM={f:.5f} (Auto-relaxed)")
            f = max(0, f - 1)
            done = False
            for c in mem:
                for bd in BDLOX:
                    if ann(r, y, p, c, cg, bd) > f:
                        out.add((r, y, p, cg, c)); done = True
                        break
                if done:
                    break
    # --- FLO_SHAR(..,'ANNUAL','FX')$RTP_CGC(R,V,P,CG,C) = FLO_SHAR(..,'LO')+FLO_SHAR(..,'FX')+EPS;
    #     FLO_SHAR(..,'ANNUAL',BD)$((BDNEQ(BD)+RTPGIG(R,V,P,CG,'OUT',C))$RTP_CGC(R,V,P,CG,C)) = 0;
    grp = members_of_marked(out)
    for (r, y, p, cg, c) in grp:
        fs[(r, y, p, c, cg, "ANNUAL", "FX")] = ann(r, y, p, c, cg, "LO") + ann(r, y, p, c, cg, "FX")
        for bd in ("LO", "UP", "FX", "N") if (r, y, p, cg, c) in out else BDNEQ:
            fs.pop((r, y, p, c, cg, "ANNUAL", bd), None)
    db.clear("FLO_SHAR")
    db.load_rows("FLO_SHAR", [k + (v,) for k, v in fs.items()])


# ---------------------------------------------------------------------------
def flomrk_prep(db: DB):
    """eqflomrk.mod, preprocessing part: market shares PRC_MARK (FLO_MARK was merged into it in preppm)."""
    x = db.x
    bd = "l in ('LO','UP','FX')"
    # --- PRC_MARK(R,LL,P,ITEM,C,BDNEQ)$PRC_MARK(R,LL,P,ITEM,C,'FX') = NO;
    db.zap("PRC_MARK", "l in ('LO','UP') and in_REG(r) and in_PRC_MARK(r,y,p,u,c,'FX')")
    # --- PRC_MARK(R,LL,P,ITEM,C,BD)$((NOT RTP_VARA(R,LL,P))$(NOT SAMEAS(P,ITEM))$PRC_MARK(R,LL,P,ITEM,C,BD)) = NO;
    db.zap("PRC_MARK", f"p <> u and {bd} and in_REG(r) and not in_RTP_VARA(r,y,p)")
    # --- LOOP(T,RX_MARK(R,'0',P,C,BD)$((PRC_MARK(R,T,P,P,C,BD)$RP_STD(R,P)>=0)$PRC_MARK(R,T,P,P,C,BD)) = YES);
    db.add("RX_MARK", f"""select distinct r, '0' as y, p as u, c, l from PRC_MARK where p = u and {bd} and in_REG(r)
                          and in_MILESTONYR(y) and (not in_RP_STD(r,p) or value >= 0)""")
    # --- RX_MARK(R,T--ORD(T),P,C,BD) $= PRC_MARK(R,T,P,P,C,BD)$(NOT RX_MARK(R,'0',P,C,BD));       T--ORD(T) is the last period
    db.add("RX_MARK", f"""select distinct r, (select y from MILESTONYR order by yv(y) desc limit 1) as y, p as u, c, l from PRC_MARK
                          where p = u and {bd} and in_REG(r) and in_MILESTONYR(y) and not in_RX_MARK(r,'0',p,c,l)""")
    # --- RTP_MRK(RTP_VARA(R,T,P),ITEM,C,BD)$((PRC_MARK(R,T,P,ITEM,C,BD)=0)$PRC_MARK(R,T,P,ITEM,C,BD)) = YES;
    # --- RTP_MRK(RTP_VARA(R,T,P),PRC,C,BD)$(PRC_MARK(R,T,PRC,PRC,C,BD)$RX_MARK(R,'0',PRC,C,BD)) = NO;
    db.tmp("t_mrk", f"""select r, y, p, u, c, l from PRC_MARK m where value = 0 and {bd} and in_MILESTONYR(y) and in_RTP_VARA(r,y,p)
                        and not (in_PRC_MARK(r,y,u,u,c,l) and in_RX_MARK(r,'0',u,c,l))""")
    # --- LOOP(RTP_MRK(R,T,P,ITEM,C,BDUPX(BD))$RP_STD(R,P),FLO_BND(R,T,P,C,ANNUAL,BD) = EPS);  PRC_MARK(RTP_MRK) = 0;
    db.put("FLO_BND", "select distinct r, y, p, c as cg, 'ANNUAL' as s, l, 0 as value from t_mrk where l in ('FX','UP') and in_RP_STD(r,p)",
           zero="eps")
    x("""delete from PRC_MARK a where exists(select 1 from t_mrk m where m.r=a.r and m.y=a.y and m.p=a.p and m.u=a.u and m.c=a.c and m.l=a.l)""")
    # --- RTP_MRK(RTP_VARA(R,T,P),ITEM,C,BD)$PRC_MARK(R,T,P,ITEM,C,BD) = YES;
    db.tmp("t_mrk", f"select r, y, p, u, c, l from PRC_MARK where {bd} and in_MILESTONYR(y) and in_RTP_VARA(r,y,p)")
    # --- YK1(T,TT(T+1)) = YES;
    db.assign("YK1", "select y, lead(y) over (order by yv(y)) as y2 from MILESTONYR qualify y2 is not null")
    # --- LOOP(YK1(TT,T),PRC_MARK(RTP_VARA(R,T,P),ITEM,C,BD)$(NOT PRC_MARK(R,T,P,ITEM,C,BD)) $= PRC_MARK(R,TT,P,ITEM,C,BD));
    for tt, t in db.q("select y, y2 from YK1 order by yv(y)"):
        db.put("PRC_MARK", f"""select r, '{t}' as y, p, u, c, l, value from PRC_MARK m where y='{tt}' and {bd}
                               and in_RTP_VARA(r,'{t}',p) and not in_PRC_MARK(r,'{t}',p,u,c,l)""", zero="eps")
    # --- OPTION RTX_MRK <= RTP_MRK, RMKC <= RTX_MRK, FIN <= RMKC;
    db.tmp("t_rtx", "select distinct r, y, u, c, l from t_mrk")
    db.tmp("t_rmkc", "select distinct r, u, c from t_rtx")
    # --- PRC_MARK(R,T,P,ITEM,C,BD)$(NOT RTX_MRK(R,T,ITEM,C,BD)) = 0;
    x(f"""delete from PRC_MARK a where in_REG(r) and in_MILESTONYR(y) and {bd}
          and not exists(select 1 from t_rtx m where m.r=a.r and m.y=a.y and m.u=a.u and m.c=a.c and m.l=a.l)""")
    # --- FIN(RC) = NO; COM_TSL(FIN,'ANNUAL')$(NOT SUM(COM_TSL(FIN,TSL),1)) = YES;
    db.tmp("t_fin", "select distinct r, c from t_rmkc where not in_RC(r,c)")
    db.add("COM_TSL", "select r, c, 'ANNUAL' as tsl from t_fin f where not exists(select 1 from COM_TSL l where l.r=f.r and l.c=f.c)")
    # --- LOOP(RMKC(R,ITEM,C),TRACKC(RC(R,COM))$COM_GMAP(R,C,COM) = YES);  RHS_COMPRD(RTCS_VARC(R,T,C,S))$TRACKC(R,C) = YES;
    db.add("RHS_COMPRD", """select v.r, v.y, v.c, v.s from RTCS_VARC v where in_RC(v.r,v.c)
                            and exists(select 1 from t_rmkc k where k.r=v.r and in_COM_GMAP(k.r,k.c,v.c))""")
    # --- RXX(RMKC)=YES; OPTION CLEAR=TRACKC,CLEAR=RMKC;  RMKC(RXX(RPC)) = YES; RMKC(RXX(R,ITEM,C)) $= FIN(R,C);
    # --- RMKC(R,ITEM,C)$COM_TSL(R,C,'ANNUAL') = NO; OPTION FIN <= RMKC;
    db.tmp("t_fine", """select r, u, c from t_rmkc k where (in_RPC(r,u,c) or exists(select 1 from t_fin f where f.r=k.r and f.c=k.c))
                        and not in_COM_TSL(r,c,'ANNUAL')""")
    # --- LOOP(COM_TSL(FIN(R,C),TSL),RTX_MARK(RTX_MRK(R,T,ITEM,C,BD),S)$(RMKC(R,ITEM,C)$TS_GROUP(R,TSL,S)) = YES);
    db.add("RTX_MARK", """select m.r, m.y, m.u, m.c, m.l, g.s from t_rtx m join t_fine k on k.r=m.r and k.u=m.u and k.c=m.c
                          join COM_TSL l on l.r=m.r and l.c=m.c join TS_GROUP g on g.r=m.r and g.tsl=l.tsl""")
    # --- RTX_MARK(RTX_MRK(R,T,ITEM,C,BD),ANNUAL)$(NOT RMKC(R,ITEM,C))=YES;
    db.add("RTX_MARK", """select m.r, m.y, m.u, m.c, m.l, 'ANNUAL' as s from t_rtx m
                          where not exists(select 1 from t_fine k where k.r=m.r and k.u=m.u and k.c=m.c)""")
    # --- RMKC(RXX(R,ITEM,C))=YES;
    db.assign("RMKC", "select r, u, c from t_rmkc")


# ---------------------------------------------------------------------------
def flow_attributes_by_timeslice(db: DB):
    """Flow attributes by timeslice: costs, peak coincidence, FLO_FUNC / FLO_SUM / FLO_SHAR."""
    from ..lvl import lvlfc, lvlbr, trees, aggregate, read_series, _ctl_map, _out, _write
    for n in ("FLO_COST", "FLO_DELIV", "FLO_SUB", "FLO_TAX"):
        lvlfc(db, n, ["p", "c"], "RPCS_VAR", "DATAYEAR", "in_RPC(a.r,a.p,a.c)", fill="N")
    lvlfc(db, "FLO_PKCOI", ["p", "c"], "RPCS_VAR", "MILESTONYR", "in_RTP(a.r,a.y,a.p)")
    lvlfc(db, "FLO_BDLVL", ["p"], "PRC_TS", "MILESTONYR", "in_RTP(a.r,a.y,a.p)", fill="1",
          take="(not in_COM(a.cg)) or in_ACTCG(a.cg)")
    lvlfc(db, "FLO_BDLVL", ["p", "cg"], "RPCS_VAR", "MILESTONYR", "in_RTP(a.r,a.y,a.p)", fill="1", take="in_RPC(a.r,a.p,a.cg)")
    # --- pp_lvlfc.mod ACT_FLO 'P' RPS_S1 '' ",'0','0','0'" ALL_TS V RTP(R,V,P) 0 ',C' 0 $STOA(S)
    #     ACT_FLO (flows of RPC_AFLO given per unit of activity, prelv_flop) to the timeslices of the process equations:
    #     an ANNUAL value is copied to every RPS_S1 timeslice (fill 0), values below ANNUAL off RPS_S1 are dropped
    lvlfc(db, "ACT_FLO", ["p"], "RPS_S1", "MODLYEAR", "in_RTP(a.r,a.y,a.p)", fill="0", take="v_STOA(a.s) <> 0")
    # --- LOOP((RPC(R,P,C),COM_GMAP(COM_PEAK(R,CG),C))$(TOP(RPC,'IN')+RPC_IRE(RPC,'EXP')),
    #       IF(NOT SUM((RTP(R,T,P),RPCS_VAR(RPC,TS))$FLO_PKCOI(RTP,C,TS),1),TRACKPC(RPC)=YES));  TRACKPC(PRC_PKNO(R,P),C)=NO;
    #     FLO_PKCOI(RTP(R,T,P),C,S)$(RPCS_VAR(R,P,C,S)$TRACKPC(R,P,C)) = 1.0
    db.tmp("t_trackpc", """select distinct k.r, k.p, k.c from RPC k join COM_GMAP m on m.r=k.r and m.c=k.c
                           where in_COM_PEAK(k.r,m.cg) and (in_TOP(k.r,k.p,k.c,'IN') or in_RPC_IRE(k.r,k.p,k.c,'EXP'))
                             and not in_PRC_PKNO(k.r,k.p)
                             and not exists(select 1 from FLO_PKCOI f where f.r=k.r and f.p=k.p and f.c=k.c and in_MILESTONYR(f.y)
                                            and in_RTP(f.r,f.y,f.p) and in_RPCS_VAR(f.r,f.p,f.c,f.s))""")
    db.put("FLO_PKCOI", """select t.r, t.y, t.p, k.c, v.s, 1 as value from t_trackpc k join RTP t on t.r=k.r and t.p=k.p
                           join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=k.c where in_MILESTONYR(t.y)""")
    # ---- pp_chp.mod
    pp_chp(db)
    T = trees(db)
    # ---- pp_lvlff.mod: FLO_FUNC given below the process timeslice level -> aggregated; ANNUAL values inherited
    if db.card("FLO_FUNC"):
        prc_ts = _ctl_map(db, "PRC_TS", ["p"])
        # --- OPTION FFCKS <= FLO_FUNC; FFCKS(R,P,CG,CG2,S)$(PRC_TS(R,P,S)+ACTCG(CG))=NO;
        db.tmp("t_ffcks", "select distinct r, p, cg, cg2, s from FLO_FUNC where not (in_PRC_TS(r,p,s) or in_ACTCG(cg))")
        key, series = read_series(db, "FLO_FUNC", """in_RTP(a.r,a.y,a.p) and exists(select 1 from t_ffcks k where k.r=a.r and k.p=a.p
                                                     and k.cg=a.cg and k.cg2=a.cg2 and k.s <> 'ANNUAL')""")
        out = []
        for k, arr in series.items():
            r, p = k[key.index("r")], k[key.index("p")]
            for ts in prc_ts.get((r, p), ()):
                if ts not in arr:
                    v = aggregate(T[r], arr, ts)
                    out.append(k + (ts, _out(v) if v is not None else None))
        _write(db, "FLO_FUNC", key, [o for o in out if o[-1] is not None])
        # --- FLO_FUNC(R,V,P,CG,COM_GRP,TS)$(NOT FLO_FUNC(..,TS)) $= SUM(FFCKS(R,P,CG,COM_GRP,ANNUAL)$PRC_TS(R,P,TS),FLO_FUNC(..,ANNUAL));
        db.put("FLO_FUNC", """select f.r, f.y, f.p, f.cg, f.cg2, t.s, f.value from FLO_FUNC f join PRC_TS t on t.r=f.r and t.p=f.p
                              where f.s='ANNUAL' and in_MODLYEAR(f.y)
                                and exists(select 1 from t_ffcks k where k.r=f.r and k.p=f.p and k.cg=f.cg and k.cg2=f.cg2 and k.s='ANNUAL')
                                and not in_FLO_FUNC(f.r,f.y,f.p,f.cg,f.cg2,t.s)""", zero="eps")
    # ---- pp_lvlfs.mod: FLO_SUM moved to the timeslices of the flow variable of C
    if db.card("FLO_SUM"):
        key = [c for c in db.cols("FLO_SUM") if c != "s"]
        kc = ", ".join(key)
        # --- COEF_PTRAN(..) $= FLO_SUM(R,LL,P,CG,C,COM_GRP,S)$(NOT RPCS_VAR(R,P,C,S));       values off the variable level
        #     (kept as t_fsoff: the records the two passes below read, before the first of them changes FLO_SUM)
        if db.tmp("t_fsoff", 'select * from FLO_SUM a where not in_RPCS_VAR(a.r,a.p,a.c,a.s)'):
            # --- FSCK(R,P,CG,C,COM_GRP) $= SUM(FSCKS(..,S)$(NOT RPS_PRCTS(R,P,S)),1);      given below the process level
            db.tmp("t_fsck", """select distinct r, p, cg, c, cg2 from t_fsoff f where not in_RPS_PRCTS(f.r,f.p,f.s)""")
            # the series of FSCK aggregated to the timeslices of the variable (only those series, and their variables, are read)
            var = {}
            for r, p, c, ts in db.q("""select v.r, v.p, v.c, v.s from RPCS_VAR v
                                       where exists(select 1 from t_fsck k where k.r=v.r and k.p=v.p and k.c=v.c)"""):
                var.setdefault((r, p, c), set()).add(ts)
            _, full = read_series(db, "FLO_SUM", """in_RTP(a.r,a.y,a.p) and exists(select 1 from t_fsck k where k.r=a.r and k.p=a.p
                                                    and k.cg=a.cg and k.c=a.c and k.cg2=a.cg2)""")
            ix = {c: key.index(c) for c in key}
            out = []
            for k, arr in full.items():
                for ts in var.get((k[ix["r"]], k[ix["p"]], k[ix["c"]]), ()):
                    v = aggregate(T[k[ix["r"]]], arr, ts)
                    out.append(k + (ts, _out(v) if v is not None else float("nan")))
            if out:
                _write(db, "FLO_SUM", key, [o for o in out if o[-1] == o[-1]])
                gone = [o[:-1] for o in out if o[-1] != o[-1]]
                if gone:
                    unsupported(db, "pp_lvlfs: aggregated FLO_SUM with no value found")
            # --- FLO_SUM(..)$COEF_PTRAN(..) = 0;  FLO_SUM(R,LL,P,..)$(NOT RTP(R,LL,P)) = 0;
            db.zap("FLO_SUM", "not in_RPCS_VAR(r,p,c,s)")
            db.zap("FLO_SUM", "not in_RTP(r,y,p)")
            # --- FOR(Z=CARD(TSLVL)-2 DOWNTO 0, ... inherit from the nearest coarser level that had a value
            #     A variable timeslice without a record takes the value of the series on its nearest ancestor among the
            #     records off the variable level (t_anc: the ancestors of each timeslice, nearest first).
            db.x("create or replace temp table t_anc (r VARCHAR, s VARCHAR, u VARCHAR, k INTEGER)")
            db.insert_rows("t_anc", [(r, ts, u, i) for r, tr in T.items() for ts in tr.all for i, u in enumerate(tr.anc[ts])])
            fk = ", ".join(f"f.{c}" for c in key)
            same = " and ".join(f"h.{c}=f.{c}" for c in key)
            db.put("FLO_SUM", f"""
                select {kc}, s, value from (
                    select {fk}, v.s, case when abs(f.value) < 1e-200 then 0 else f.value end as value,
                           row_number() over (partition by {fk}, v.s order by a.k) as n_
                    from t_fsoff f join RPCS_VAR v on v.r=f.r and v.p=f.p and v.c=f.c
                    join t_anc a on a.r=f.r and a.s=v.s and a.u=f.s
                    where in_RTP(f.r,f.y,f.p)
                      and not exists(select 1 from FLO_SUM h where {same} and h.s=v.s))
                where n_ = 1""", zero="eps")
        else:
            db.zap("FLO_SUM", "not in_RTP(r,y,p)")
    # --- IRE_FLOSUM(RTP(R,V,P),C,S,IE,COM,IO)$(RPC_PG*RPC_IRE*RPCS_VAR*TOP(R,P,COM,IO)) $=
    #        SUM(RPC_ACT(RP_IRE(R,P),COM),PRC_ACTFLO(R,V,P,COM)*(1/PRC_ACTFLO(R,V,P,C)));
    db.put("IRE_FLOSUM", """select k.r, k.y, k.p, g.c, v.s, i.ie, a.cg as c2, t.io,
                                   v_PRC_ACTFLO(k.r,k.y,k.p,a.cg) * (1 / v_PRC_ACTFLO(k.r,k.y,k.p,g.c)) as value
                            from RTP k join RPC_ACT a on a.r=k.r and a.p=k.p join RPC_PG g on g.r=k.r and g.p=k.p
                            join RPC_IRE i on i.r=g.r and i.p=g.p and i.c=g.c join RPCS_VAR v on v.r=g.r and v.p=g.p and v.c=g.c
                            join TOP t on t.r=k.r and t.p=k.p and t.c=a.cg
                            where in_RP_IRE(k.r,k.p) and in_COM(a.cg) and in_PRC_ACTFLO(k.r,k.y,k.p,a.cg)""", zero="eps")
    # --- FLO_SUM(RTP(R,V,P),CG,C,COM,S)$(RP_PG(R,P,CG)*RPC_PG(R,P,C)*PRC_TS(R,P,S)) $=
    #        SUM(RPC_ACT(RP_FLO(R,P),COM),PRC_ACTFLO(R,V,P,COM)*(1/PRC_ACTFLO(R,V,P,C)));
    #     ($= assigns an EPS: a PRC_ACTFLO given as 0 gives an EPS FLO_SUM, and so its EQ_PTRANS)
    db.put("FLO_SUM", """select k.r, k.y, k.p, q.cg, g.c, a.cg as cg2, t.s,
                                v_PRC_ACTFLO(k.r,k.y,k.p,a.cg) * (1 / v_PRC_ACTFLO(k.r,k.y,k.p,g.c)) as value
                         from RTP k join RPC_ACT a on a.r=k.r and a.p=k.p join RP_PG q on q.r=k.r and q.p=k.p
                         join RPC_PG g on g.r=k.r and g.p=k.p join PRC_TS t on t.r=k.r and t.p=k.p
                         where in_RP_FLO(k.r,k.p) and in_COM(a.cg) and in_PRC_ACTFLO(k.r,k.y,k.p,a.cg)""", zero="eps")
    db.clear("RPC_ACT")
    # ---- FLO_SHAR levelling
    lvlbr(db, "FLO_SHAR", "RPCS_VAR", ["p", "c"], inherit_missing=True, fx_check=False)
    # ---- eqflomrk.mod (preprocessing part)
    flomrk_prep(db)
    # --- RPC_NOFLO(RMKC(RPC)) = NO;
    db.remove("RPC_NOFLO", where="in_RMKC(r,p,c)")
