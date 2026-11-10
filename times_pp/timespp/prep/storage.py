# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod: storage processes (which commodities they store, load shifting, the controls of flexible
storages, levelling of storage attributes)."""
from ..engine import DB


def storage_classification(db: DB):
    """ppmain.mod, 'Establish missing sets for storage processes' (stored commodities should be members of the PG)."""
    x = db.x
    # --- TRACKC(R,C)$COM_LIM(R,C,'N') = YES; TRACKC(R,%PGPRIM%) = YES;
    db.tmp("TRACKC", "select r, c from COM_LIM where l='N' and in_REG(r) union select r, 'ACT' as c from REG")
    # --- RP_STS(R,P)$PRC_MAP(R,'STS',P)=YES;
    db.add("RP_STS", "select r, p from PRC_MAP where prc_grp='STS' and in_REG(r)")
    # --- TRACKP(R,P)$(PRC_MAP(R,'STG',P)+PRC_MAP(R,'STK',P)+RP_STS(R,P)) = YES;
    # --- TRACKP(R,P)$SUM(PRC_STGTSS(R,P,C),1) = NO;  TRACKP(R,P)$SUM(PRC_NSTTS(R,P,S),1) = NO;
    db.tmp("TRACKP", """select distinct r, p from PRC_MAP m where prc_grp in ('STG','STK','STS') and in_REG(r)
                        and not exists(select 1 from PRC_STGTSS g where g.r=m.r and g.p=m.p)
                        and not exists(select 1 from PRC_NSTTS g where g.r=m.r and g.p=m.p)""")
    # --- TRACKPC(TRACKP(R,P),C)$SUM((TOP(R,P,C,IO),RP_PG(R,P,CG))$COM_GMAP(R,CG,C),1) = YES;
    # --- TRACKPC(TRACKP(R,P),C)$SUM(RP_PG(R,P,C)$(NOT TRACKC(R,C)),1) = YES;
    db.tmp("TRACKPC", """select distinct k.r, k.p, t.c from TRACKP k join TOP t on t.r=k.r and t.p=k.p
                           join RP_PG g on g.r=k.r and g.p=k.p where in_COM_GMAP(k.r, g.cg, t.c)
                         union
                         select k.r, k.p, g.cg as c from TRACKP k join RP_PG g on g.r=k.r and g.p=k.p
                         where in_COM(g.cg) and not exists(select 1 from TRACKC n where n.r=k.r and n.c=g.cg)""")
    # Auto-generate missing charge/discharge flow
    # --- RPC_STGN(TOP(TRACKP(R,P),C,IO))$SUM((COM_GMAP(R,COM_TYPE(CG),C),TRACKPC(R,P,COM))$COM_GMAP(R,CG,COM),1)=YES;
    db.add("RPC_STGN", """select distinct t.r, t.p, t.c, t.io from TOP t join TRACKP k on k.r=t.r and k.p=t.p
                          join COM_GMAP g on g.r=t.r and g.c=t.c and in_COM_TYPE(g.cg)
                          join TRACKPC k2 on k2.r=t.r and k2.p=t.p and in_COM_GMAP(t.r, g.cg, k2.c)""")
    # --- OPTION CG_GRP < FLO_FUNC; RPC_STGN(RP,C,IO)$SUM(RPC_STGN(TRACKPC(RP,COM),IO),1)=NO;
    #     The condition is taken on the set as it was before the statement: every flow in a direction in which a stored
    #     commodity has a flow goes, also one entered after it (e.g. pumped storage with an auxiliary input).
    db.tmp("t_stgn_io", """select distinct n.r, n.p, n.io from RPC_STGN n join TRACKPC k on k.r=n.r and k.p=n.p and k.c=n.c""")
    db.remove("RPC_STGN", where="exists(select 1 from t_stgn_io x where x.r=RPC_STGN.r and x.p=RPC_STGN.p and x.io=RPC_STGN.io)")
    #     (OPTION A < B takes same-named domains from the right: CG_GRP holds the FLO_FUNC group pair reversed)
    # --- LOOP(CG_GRP(TRACKP(RP),C,COM),IF(TRACKPC(RP,C),RPC_STGN(RP,COM,IO)=NO ELSEIF TRACKPC(RP,COM),RPC_STGN(RP,C,IO)=NO));
    db.tmp("t_ff", """select distinct f.r, f.p, f.cg2 as c, f.cg as com from FLO_FUNC f join TRACKP k on k.r=f.r and k.p=f.p
                      where in_COM(f.cg) and in_COM(f.cg2)""")
    db.remove("RPC_STGN", where="""exists(select 1 from t_ff f where f.r=RPC_STGN.r and f.p=RPC_STGN.p and
        ((f.com=RPC_STGN.c and exists(select 1 from TRACKPC k where k.r=f.r and k.p=f.p and k.c=f.c)) or
         (f.c=RPC_STGN.c and not exists(select 1 from TRACKPC k where k.r=f.r and k.p=f.p and k.c=f.c)
                         and exists(select 1 from TRACKPC k where k.r=f.r and k.p=f.p and k.c=f.com))))""")
    # --- TRACKPC(RPC) $= SUM(RPC_STGN(RPC,IO),1);
    x("insert into TRACKPC select distinct n.r, n.p, n.c from RPC_STGN n where in_RPC(n.r,n.p,n.c) "
      "and not exists(select 1 from TRACKPC k where k.r=n.r and k.p=n.p and k.c=n.c)")
    # --- LOOP(PRC_NSTTS(R,P,S), PRC_MAP(R,'STG',P) = YES; PRC_MAP(R,'NST',P) = YES; PRC_MAP(R,'STK',P) = NO);
    db.add("PRC_MAP", "select distinct r, g.prc_grp, p from PRC_NSTTS, (values ('STG'),('NST')) g(prc_grp) where in_REG(r)")
    db.remove("PRC_MAP", where="prc_grp='STK' and exists(select 1 from PRC_NSTTS n where n.r=PRC_MAP.r and n.p=PRC_MAP.p)")
    # --- PRC_STGIPS(TRACKPC(R,P,C))$PRC_MAP(R,'STK',P) = YES;
    db.add("PRC_STGIPS", "select r, p, c from TRACKPC where in_PRC_MAP(r,'STK',p)")
    # --- LOOP(PRC_STGIPS(R,P,C), PRC_MAP(R,'STG',P) = YES; PRC_MAP(R,'STK',P) = YES; PRC_MAP(R,'NST',P) = NO;
    #       IF(NOT SUM(TOP(R,P,C,IO),1),TOP(R,P,C,IO)=YES); IF(NOT RP_STS(R,P),PRC_TSL(R,P,TSLVL) = SAMEAS(TSLVL,'ANNUAL')));
    db.add("PRC_MAP", "select distinct r, g.prc_grp, p from PRC_STGIPS, (values ('STG'),('STK')) g(prc_grp) where in_REG(r)")
    db.remove("PRC_MAP", where="prc_grp='NST' and exists(select 1 from PRC_STGIPS n where n.r=PRC_MAP.r and n.p=PRC_MAP.p)")
    db.add("TOP", """select distinct n.r, n.p, n.c, i.io from PRC_STGIPS n, (values ('IN'),('OUT')) i(io) where in_REG(n.r)
                     and not exists(select 1 from TOP t where t.r=n.r and t.p=n.p and t.c=n.c)""")
    db.remove("PRC_TSL", where="""tsl<>'ANNUAL' and not in_RP_STS(r,p)
                                  and exists(select 1 from PRC_STGIPS n where n.r=PRC_TSL.r and n.p=PRC_TSL.p)""")
    db.add("PRC_TSL", "select distinct r, p, 'ANNUAL' as tsl from PRC_STGIPS n where in_REG(r) and not in_RP_STS(r,p)")
    # --- PRC_STGTSS(TRACKPC(R,P,C))$(NOT PRC_MAP(R,'STK',P)) = YES;
    db.add("PRC_STGTSS", "select r, p, c from TRACKPC where not in_PRC_MAP(r,'STK',p)")
    # --- LOOP(PRC_STGTSS(R,P,C), PRC_MAP(R,'STG',P) = YES; PRC_MAP(R,'STS',P) = YES; PRC_MAP(R,'NST',P) = NO; PRC_MAP(R,'STK',P) = NO;
    #       IF(NOT SUM(TOP(R,P,C,IO),1),TOP(R,P,C,IO)=YES));
    db.add("PRC_MAP", "select distinct r, g.prc_grp, p from PRC_STGTSS, (values ('STG'),('STS')) g(prc_grp) where in_REG(r)")
    db.remove("PRC_MAP", where="prc_grp in ('NST','STK') and exists(select 1 from PRC_STGTSS n where n.r=PRC_MAP.r and n.p=PRC_MAP.p)")
    db.add("TOP", """select distinct n.r, n.p, n.c, i.io from PRC_STGTSS n, (values ('IN'),('OUT')) i(io) where in_REG(n.r)
                     and not exists(select 1 from TOP t where t.r=n.r and t.p=n.p and t.c=n.c)""")
    # --- OPTION CLEAR=TRACKC,CLEAR=TRACKP,CLEAR=TRACKPC,CLEAR=CG_GRP,CLEAR=RPC_STGN;
    db.clear("RPC_STGN")
    # If storage is input- or output-based, define it such
    # --- RPC_STGN(PRC_STGTSS(R,P,C),IO)$(NOT SUM(TOP(R,P,COM,IO)$PRC_STGTSS(R,P,COM),1)) = YES;   (same for PRC_STGIPS)
    for n in ("PRC_STGTSS", "PRC_STGIPS"):
        db.add("RPC_STGN", f"""select g.r, g.p, g.c, i.io from {n} g, (values ('IN'),('OUT')) i(io) where in_REG(g.r)
                               and not exists(select 1 from TOP t join {n} g2 on g2.r=t.r and g2.p=t.p and g2.c=t.c
                                              where t.r=g.r and t.p=g.p and t.io=i.io)""")
    # --- TOP(RPC_STGN) = YES;
    db.add("TOP", "select r, p, c, io from RPC_STGN")


def storage_controls(db: DB):
    """Storage: load-shifting storages (STG_SIFT), controls of the flexible storages, levelling of STG_LOSS / STG_SIFT."""
    from ..lvl import lvlfc, trees
    # --- RTPCS_OUT(RTP(R,T,P),C,S)$(RPCS_VAR(R,P,C,S)$RPC_STG(R,P,C)) = YES;
    db.add("RTPCS_OUT", """select k.r, k.y, k.p, v.c, v.s from RTP k join RPCS_VAR v on v.r=k.r and v.p=k.p
                           where in_MILESTONYR(k.y) and in_RPC_STG(v.r,v.p,v.c)""")
    # ---- demand sifting storages
    # --- OPTION TRACKPC < STG_SIFT; TRACKPC(RP,C)$(NOT (TOP(RP,C,'OUT')$RPC_STG(RP,C)+ACTCG(C))$RP_STG(RP))=NO;
    #     TRACKPC(RP,C)$PRC_NSTTS(RP,'ANNUAL')=NO;
    #     (kept: a shifted output of a storage process, or its activity; not for night storages that store at ANNUAL)
    db.tmp("t_sift", """select distinct r, p, c from STG_SIFT a where in_REG(r) and (not in_RP(r,p) or
                          (in_RP_STG(r,p) and ((in_TOP(r,p,c,'OUT') and in_RPC_STG(r,p,c)) or c='ACT')
                           and not in_PRC_NSTTS(r,p,'ANNUAL')))""")
    # --- LOOP(TRACKPC(R,P,C),TRACKP(R,P)=YES; RPC_PKC(R,P,C)=NO; RHS_COMPRD(RTCS_VARC(R,T,C,S))=YES);
    db.tmp("t_trackp", "select distinct r, p from t_sift")
    db.remove("RPC_PKC", where="exists(select 1 from t_sift k where k.r=RPC_PKC.r and k.p=RPC_PKC.p and k.c=RPC_PKC.c)")
    db.add("RHS_COMPRD", "select v.r, v.y, v.c, v.s from RTCS_VARC v where exists(select 1 from t_sift k where k.r=v.r and k.c=v.c)")
    # --- RPC_SPG(RPC_STG(TRACKP,C))=YES;
    db.add("RPC_SPG", "select g.r, g.p, g.c from RPC_STG g join t_trackp k on k.r=g.r and k.p=g.p")
    # --- RPC_STGN(TOP(RPC_STG(RPC_SPG(RP,C)),IO))$TOP(RP,C,'IN') = (TRACKPC(RP,C) EQV IPS(IO));
    #     (a stored commodity of the shadow group that the process also takes in: the input is the auxiliary flow when the
    #      commodity is shifted, the output otherwise)
    db.tmp("t_stgn", """select t.r, t.p, t.c, t.io,
                               (exists(select 1 from t_sift k where k.r=t.r and k.p=t.p and k.c=t.c)) = in_IPS(t.io) as yes
                        from TOP t where in_RP(t.r,t.p) and in_RPC_SPG(t.r,t.p,t.c) and in_RPC_STG(t.r,t.p,t.c) and in_TOP(t.r,t.p,t.c,'IN')""")
    db.remove("RPC_STGN", select="select r, p, c, io from t_stgn where not yes")
    db.add("RPC_STGN", "select r, p, c, io from t_stgn where yes")
    # --- LOOP(PRC_TSL(TRACKP(RP(R,P)),TSLVL), RP_STS(RP)=NO; RP_STG(RP)=NO;
    #       Z=1-SUM(RPCS_VAR(RP,C,ANNUAL),2); LOOP(TOP(RPC_STG(RP,C),'IN'),IF(Z>0,RPC_LS(RP,C)=YES);Z=Z-1); RPC_LS(RP,C(ACTCG))$Z=YES;
    #       LOOP(TRACKPC(RP,C(ACTCG)),F=SUM(RLUP(R,TSLVL,TSL),ORD(TSL)-1); IF(F=0,F=Z);
    #         LOOP(RJLVL(J,R,TSL)$(F>=ORD(TSL)),
    #           LOOP(TS_GROUP(R,TSL,TS),STG_SIFT(R,T,P,C,S)$(NOT STG_SIFT(R,T,P,C,S)) $= STG_SIFT(R,T,P,C,TS)$(STOAL(R,S)=F)$RS_BELOW(R,TS,S)));
    #         STG_SIFT(R,T,P,C,S)$(STOAL(R,S) NE F)=0);
    #       ACT_TIME(RTP(R,T,P),'LO')$(ACT_TIME(RTP,'UP')=0)=0;
    #       ACT_TIME(RTP(R,T,P),BD)$ACT_TIME(RTP,'FX')=ACT_TIME(RTP,'FX')$BDUPX(BD));
    sifters = db.q("""select k.r, k.p, l.tsl, (select count(*) from RPCS_VAR v where v.r=k.r and v.p=k.p and v.s='ANNUAL') as nann,
                             coalesce((select max(ord_tsl(u.tsl2)) - 1 from RLUP u where u.r=k.r and u.tsl=l.tsl), 0) as f0,
                             exists(select 1 from t_sift x where x.r=k.r and x.p=k.p and x.c='ACT') as act
                      from t_trackp k join PRC_TSL l on l.r=k.r and l.p=k.p where in_RP(k.r,k.p) order by all""")
    T = trees(db)
    stoal = {(r, s): v for r, s, v in db.q("select r, s, value from STOAL")}
    for r, p, tslvl, nann, f0, act in sifters:
        rp = f"r='{r}' and p='{p}'"
        db.remove("RP_STS", where=rp); db.remove("RP_STG", where=rp)
        # (which input comes first does not matter: with more than one, Z ends non-zero and the activity takes over below)
        ins = [c for (c,) in db.q(f"select c from RPC_STG where {rp} and in_TOP(r,p,c,'IN') order by c")]
        z = 1 - 2 * nann
        if z > 0 and ins:
            db.add("RPC_LS", f"select '{r}' as r, '{p}' as p, '{ins[0]}' as c")
        z -= len(ins)
        if z:
            db.add("RPC_LS", f"select '{r}' as r, '{p}' as p, 'ACT' as c")
        if act:
            # the shifting limits on the activity are moved to the timeslice level above that of the process
            F = f0 if f0 else z
            tr = T[r]
            rows = db.q(f"select y, s, value from STG_SIFT where {rp} and c='ACT' and in_MILESTONYR(y)")
            by = {}
            for y, s_, v in rows:
                by.setdefault(y, {})[s_] = v
            new, drop = [], []
            for y, arr in by.items():
                for s_ in tr.all:
                    if stoal.get((r, s_), 0) != F or s_ in arr:
                        continue
                    for u in tr.anc[s_]:                      # nearest coarser timeslice first (RJLVL order)
                        if u in arr and arr[u] != 0:
                            new.append((y, s_, arr[u])); break
                drop += [(y, s_) for s_ in arr if stoal.get((r, s_), 0) != F]
            for y, s_ in drop:
                db.x(f"delete from STG_SIFT where {rp} and c='ACT' and y='{y}' and s='{s_}'")
            for y, s_, v in new:
                db.x(f"insert into STG_SIFT values ('{r}','{y}','{p}','ACT','{s_}',{v!r})")
        rtp = f"{rp} and in_MILESTONYR(y) and in_RTP(r,y,p)"
        db.zap("ACT_TIME", f"{rtp} and l='LO' and v_ACT_TIME(r,y,p,'UP') = 0")
        db.put("ACT_TIME", f"select r, y, p, 'UP' as l, value from ACT_TIME where {rtp} and l='FX'", zero="eps")
        db.zap("ACT_TIME", f"{rtp} and l not in ('UP','FX') and in_ACT_TIME(r,y,p,'FX')")
    # --- RPC_LS(RPC(RP,C))$RPC_LS(RP,%PGPRIM%)=NO;
    db.remove("RPC_LS", where="in_RPC(r,p,c) and in_RPC_LS(r,p,'ACT')")
    # ---- controls for flexible general storage
    # --- RPS_STG(PRC_TS(RP_STG,TS)) = YES;  RPS_STG(R,P,ANNUAL)$PRC_MAP(R,'STK',P) = NO;
    db.add("RPS_STG", "select r, p, s from PRC_TS where in_RP_STG(r,p) and not (s='ANNUAL' and in_PRC_MAP(r,'STK',p))")
    # --- RP_STS(R,P)$PRC_TSL(R,P,'ANNUAL') = NO;
    db.remove("RP_STS", where="in_PRC_TSL(r,p,'ANNUAL')")
    # --- LOOP(RP_STS(R,P), PRC_TS(RPS_PRCTS(R,P,S))$STOA(S) = YES; PRC_TS(R,P,ANNUAL)$PRC_MAP(R,'STK',P) = YES;
    #       PRC_STGTSS(PRC_STGIPS(R,P,C)) = YES; STG_LOSS(R,V,P,S)$STG_LOSS(R,V,P,S) = -ABS(STG_LOSS(R,V,P,S)));
    db.add("PRC_TS", "select x.r, x.p, x.s from RPS_PRCTS x where in_RP_STS(x.r,x.p) and x.s <> 'ANNUAL'")
    db.add("PRC_TS", "select r, p, 'ANNUAL' as s from RP_STS where in_PRC_MAP(r,'STK',p)")
    db.add("PRC_STGTSS", "select r, p, c from PRC_STGIPS where in_RP_STS(r,p)")
    #     (the losses of a flexible storage are flagged by a negative sign; an EPS stays EPS)
    db.put("STG_LOSS", "select r, y, p, s, -abs(value) as value from STG_LOSS where in_RP_STS(r,p) and in_MODLYEAR(y)", zero="eps")
    # --- RP_STL(RP_STS(RP),TSL+1,'N')$(PRC_SGL(RP)>=ORD(TSL)) = YES;
    db.add("RP_STL", """select k.r, k.p, n.tsl, 'N' as l from RP_STS k, TSL_ORD t, TSL_ORD n
                        where n.ord = t.ord + 1 and v_PRC_SGL(k.r,k.p) >= t.ord""")
    # --- NCAP_AF(RTP(R,V,P),S,BD)$((NOT RPS_STG(R,P,S))$RP_STS(R,P)) = NCAP_AFS(RTP,S,BD);
    db.zap("NCAP_AF", "in_RP_STS(r,p) and in_RTP(r,y,p) and l in ('LO','UP','FX') and not in_RPS_STG(r,p,s)")
    db.put("NCAP_AF", """select r, y, p, s, l, value from NCAP_AFS where in_RP_STS(r,p) and in_RTP(r,y,p) and l in ('LO','UP','FX')
                         and not in_RPS_STG(r,p,s)""", zero="eps")
    # ---- levelling of STG_LOSS and STG_SIFT
    # --- TRACKP(RP_STG)$(NOT RP_STS(RP_STG)) = YES;        (TRACKP still holds the load-shifting processes)
    db.x("insert into t_trackp select r, p from RP_STG g where not in_RP_STS(r,p) and not exists(select 1 from t_trackp k where k.r=g.r and k.p=g.p)")
    # --- $BATINCLUDE pp_lvlfc.mod STG_LOSS P PRC_TS '' ",'0','0','0','0'" S2 V 'RTP(R,V,P)$(NOT RPS_STG(R,P,S)$TRACKP(R,P))'
    lvlfc(db, "STG_LOSS", ["p"], "PRC_TS", "MODLYEAR",
          "in_RTP(a.r,a.y,a.p) and not (in_RPS_STG(a.r,a.p,a.s) and exists(select 1 from t_trackp k where k.r=a.r and k.p=a.p))", all_ts=True)
    # --- $BATINCLUDE pp_lvlfc.mod STG_SIFT 'P,C' RPCS_VAR '' ",'0','0','0'" ALL_TS T RTP(R,T,P)
    lvlfc(db, "STG_SIFT", ["p", "c"], "RPCS_VAR", "MILESTONYR", "in_RTP(a.r,a.y,a.p)")
    # --- STG_LOSS(RTP(R,V,P),S(TSL))$((ABS(STG_LOSS(RTP,S)*2-1)>=1)$PRC_MAP(R,'STK',P)) = 1-EXP(-ABS(STG_LOSS(RTP,S)));
    #     (inter-period storage: an equilibrium loss, given as >= 1 or negative, becomes a standard annual loss)
    db.put("STG_LOSS", """select r, y, p, s, 1 - exp(-abs(value)) as value from STG_LOSS
                          where s='ANNUAL' and in_RTP(r,y,p) and in_PRC_MAP(r,'STK',p) and abs(value * 2 - 1) >= 1""")
    # --- STG_LOSS(RTP(R,V,P),S)$(STOA(S)$STG_LOSS(RTP,S)) = LOG(EXP(STG_LOSS(RTP,S)*G_YRFR(R,S)/RS_STGPRD(R,S)));
    #     (losses below ANNUAL: per storage cycle of the timeslice; a loss given as EPS gives LOG(EXP(EPS)) = LOG(1) = 0,
    #     and the assignment of 0 removes the record)
    db.put("STG_LOSS", """select r, y, p, s, ln(exp(value * v_G_YRFR(r,s) / v_RS_STGPRD(r,s))) as value from STG_LOSS
                          where s <> 'ANNUAL' and in_RTP(r,y,p)""")
