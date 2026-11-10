# SPDX-License-Identifier: GPL-3.0-or-later
"""coef_ext.vda: VEDA coefficient extensions (residual capacity, unused commodities, ACT_EFF -> COEF_PTRAN)."""
from ..controls import unsupported
from ..engine import DB
from . import abs as abs_ext, cli, grids
from .common import require_empty


def eqashar_prep(db: DB):
    """eqashar.vda, preprocessing part: shares of flows in a group that is not the group of the commodity (FLO_ASHAR)."""
    x = db.x
    # --- OPTION CG_GRP <= FLO_ASHAR;  FLO_SHAR(R,'0',P,C,CG,ANNUAL,'LO')$CG_GRP(R,P,C,CG) = EPS;
    db.tmp("t_cg", "select distinct r, p, cg, cg2 from FLO_ASHAR where in_REG(r)")
    db.put("FLO_SHAR", "select r, '0' as y, p, cg as c, cg2 as cg, 'ANNUAL' as s, 'LO' as l, 0 as value from t_cg where in_COM(cg)", zero="eps")
    if not db.q1("select count(*) from t_cg"):
        return
    # --- LOOP((CG_GRP(RPC(R,P,C),C),COM_TMAP(R,COM_TYPE(CG),C)),RPCG_ASHAR(R,P,C,CG,S)$(PRC_SGL(R,P)=STOAL(R,S))=-1);
    db.put("RPCG_ASHAR", """select g.r, g.p, g.cg, m.cg as cg2, l.s, -1 as value from t_cg g join COM_TMAP m on m.r=g.r and m.c=g.cg
                            join STOAL l on l.r=g.r where g.cg=g.cg2 and in_RPC(g.r,g.p,g.cg) and v_PRC_SGL(g.r,g.p) = l.value
                            union all
                            select g.r, g.p, g.cg, m.cg as cg2, 'ANNUAL' as s, -1 as value from t_cg g join COM_TMAP m on m.r=g.r and m.c=g.cg
                            where g.cg=g.cg2 and in_RPC(g.r,g.p,g.cg) and v_PRC_SGL(g.r,g.p) = 0""")
    # --- FLO_ASHAR(RTP(R,V,P),C,COM_TYPE(CG),S,BD)$COM_TMAP(R,COM_TYPE,C) $= FLO_ASHAR(R,V,P,C,C,S,BD);  FLO_ASHAR(R,LL,P,C,C,S,BD) = 0;
    db.put("FLO_ASHAR", """select a.r, a.y, a.p, a.cg, m.cg as cg2, a.s, a.l, a.value from FLO_ASHAR a join COM_TMAP m on m.r=a.r and m.c=a.cg
                           where a.cg=a.cg2 and in_RTP(a.r,a.y,a.p) and a.l in ('LO','UP','FX')""", zero="eps")
    db.zap("FLO_ASHAR", "cg=cg2 and in_REG(r) and in_COM(cg) and l in ('LO','UP','FX')")
    # --- CG_GRP(RPC(RP,C),C) = NO;
    x("delete from t_cg where cg=cg2 and in_RPC(r,p,cg)")
    # --- RP_PGFLO(RP_FLO(RP)) $= SUM(CG_GRP(NO_ACT(RP),C,ACTCG),1);
    db.add("RP_PGFLO", "select distinct r, p from t_cg where cg2='ACT' and in_COM(cg) and in_NO_ACT(r,p) and in_RP_FLO(r,p)")
    # --- RPCG_ASHAR(CG_GRP(RPC,CG),S)$=RPCS_VAR(RPC,S);
    db.put("RPCG_ASHAR", """select g.r, g.p, g.cg, g.cg2, v.s, 1 as value from t_cg g join RPCS_VAR v on v.r=g.r and v.p=g.p and v.c=g.cg""")
    # --- RPCG_ASHAR(CG_GRP(RPC_STG(RP,C),ACTCG),S)=RPS_STG(RP,S)+PRC_TSL(RP,'ANNUAL')$ANNUAL(S);
    db.zap("RPCG_ASHAR", "cg2='ACT' and in_RPC_STG(r,p,cg) and exists(select 1 from t_cg g where g.r=RPCG_ASHAR.r and g.p=RPCG_ASHAR.p "
                         "and g.cg=RPCG_ASHAR.cg and g.cg2='ACT')")
    db.put("RPCG_ASHAR", """select g.r, g.p, g.cg, g.cg2, t.s,
                                   (case when in_RPS_STG(g.r,g.p,t.s) then 1 else 0 end)
                                   + (case when t.s='ANNUAL' and in_PRC_TSL(g.r,g.p,'ANNUAL') then 1 else 0 end) as value
                            from t_cg g join (select distinct r, s from TS_GROUP) t on t.r=g.r
                            where g.cg2='ACT' and in_RPC_STG(g.r,g.p,g.cg)""")
    # --- CG_GRP(RPC,CG)=NO;
    x("delete from t_cg where in_RPC(r,p,cg)")
    # --- LOOP(CG_GRP(R,P,CG,CG2), Z=1; LOOP(COM_TSL(R,C(CG),TSL), Z=0; RPCG_ASHAR(R,P,CG,CG2,S)$TS_GROUP(R,TSL,S) = 1);
    #       IF(Z, RPCG_ASHAR(R,P,CG,CG2,ANNUAL) = YES));
    db.put("RPCG_ASHAR", """select g.r, g.p, g.cg, g.cg2, t.s, 1 as value from t_cg g join COM_TSL l on l.r=g.r and l.c=g.cg
                            join TS_GROUP t on t.r=g.r and t.tsl=l.tsl where in_COM(g.cg)
                            union all
                            select g.r, g.p, g.cg, g.cg2, 'ANNUAL' as s, 1 as value from t_cg g
                            where not (in_COM(g.cg) and exists(select 1 from COM_TSL l where l.r=g.r and l.c=g.cg))""")
    # --- $BATINCLUDE pp_lvlfc.mod FLO_ASHAR P RPS_S2 ',BD' ",''" ALL_TS V 1 0 ',C,CG' N
    from ..lvl import lvlfc
    lvlfc(db, "FLO_ASHAR", ["p"], "RPS_S2", "MODLYEAR", fill="N")


def eqlducs_prep(db: DB):
    """eqlducs.vda, the part before EQU: unit commitment by start-up type (ACT_CSTSD: start-up costs by type HOT /
    WARM / COLD (UP) and the shut-down cost (HOT, LO); ACT_SDTIME start-up / shut-down times, ACT_MAXNON the longest
    non-operational time of a type, ACT_LOSSD the losses while starting up / shutting down), and the partial loads."""
    # --- OPTION RP_UPT<ACT_CSTSD, TRACKP<RP_UPT;  RP_DP(TRACKP(RP))$=RP_UPL(RP,'FX');
    #     RP_DP(RP)$SUM(RPS_CAFLAC(PRC_TS(RP,S),BD),1)=NO;
    db.assign("RP_UPT", "select distinct r, p, upt, l from ACT_CSTSD")
    db.assign("RP_DP", """select distinct u.r, u.p from RP_UPT u where in_RP_UPL(u.r,u.p,'FX')
                          and not exists(select 1 from RPS_CAFLAC c where c.r=u.r and c.p=u.p and in_PRC_TS(c.r,c.p,c.s))""")
    if db.card("RP_DP") and str(db.env.get("DUC", "")).upper() == "YES":
        unsupported(db, "discrete unit commitment (DUC=YES: binary on-line indicators, eqlducs.vda)", ["ACT_CSTSD"])
    if db.card("RP_DP"):
        # --- RP_DPL(PRC_TSL(RP_DP,TSL)) = YES;
        #     RP_DPL(RP_DP(R,P),TSL)$(RLUP(R,'DAYNITE',TSL)$PRC_TSL(R,P,'DAYNITE')) = ORD(TSL)>1;
        #     (a DAYNITE process is dispatched on the levels above it too, ANNUAL left out)
        db.assign("RP_DPL", "select r, p, tsl from PRC_TSL where in_RP_DP(r,p)")
        db.tmp("t_dpl", """select d.r, d.p, u.tsl2 as tsl, ord_tsl(u.tsl2) > 1 as yes_ from RP_DP d
                           join RLUP u on u.r=d.r and u.tsl='DAYNITE' where in_PRC_TSL(d.r,d.p,'DAYNITE')""")
        db.remove("RP_DPL", select="select r, p, tsl from t_dpl where not yes_")
        db.add("RP_DPL", "select r, p, tsl from t_dpl where yes_")
        # --- ACT_CSTUP(RTP(R,V,P),TSL,CUR)$RP_DP(R,P) = 0;
        db.zap("ACT_CSTUP", "in_RTP(r,y,p) and in_RP_DP(r,p)")
        # --- ACT_CSTSD(RTP(R,V,P),UPT,'FX',CUR)$(RDCUR(R,CUR)$RP_DP(R,P)) = ACT_CSTSD(RTP,UPT,'UP',CUR)+ACT_CSTSD(RTP,'HOT','LO',CUR);
        #     (the cost of a start-up of type UPT and of the shut-down before it; EPS + EPS stays EPS)
        db.zap("ACT_CSTSD", "l='FX' and in_RTP(r,y,p) and in_RP_DP(r,p) and in_RDCUR(r,cur)")
        db.put("ACT_CSTSD", """select k.r, k.y, k.p, u.u as upt, 'FX' as l, c.cur,
                                 case when in_ACT_CSTSD(k.r,k.y,k.p,u.u,'UP',c.cur) or in_ACT_CSTSD(k.r,k.y,k.p,'HOT','LO',c.cur)
                                      then coalesce(v_ACT_CSTSD(k.r,k.y,k.p,u.u,'UP',c.cur), 0) + coalesce(v_ACT_CSTSD(k.r,k.y,k.p,'HOT','LO',c.cur), 0)
                                 end as value
                               from RTP k join RP_DP d on d.r=k.r and d.p=k.p join RDCUR c on c.r=k.r, UPT u""", zero="eps")
        # --- ACT_CSTUP(RTP(R,V,P),TSL,CUR)$RP_DPL(R,P,TSL) $= SUM(UPT$ACT_CSTSD(RTP,UPT,'FX',CUR),EPS);
        db.put("ACT_CSTUP", """select distinct a.r, a.y, a.p, l.tsl, a.cur, 0 as value from ACT_CSTSD a
                               join RP_DPL l on l.r=a.r and l.p=a.p where a.l='FX' and in_RTP(a.r,a.y,a.p)""", zero="eps")
        # --- RP_UPT(RP_DP,UPT,'LO')=DIAG('HOT',UPT);    (the shut-down: of type HOT only)
        db.remove("RP_UPT", where="l='LO' and upt <> 'HOT' and in_RP_DP(r,p)")
        db.add("RP_UPT", "select r, p, 'HOT' as upt, 'LO' as l from RP_DP")
    # --- LOOP(V,RP_UPT(R,P,UPT,BD('UP'))$ACT_SDTIME(R,V,P,UPT,BD)=YES);
    db.add("RP_UPT", "select distinct r, p, upt, l from ACT_SDTIME where l='UP' and in_MODLYEAR(y)")
    if db.card("RP_DP"):
        # --- ACT_MAXNON(R,V,P,UPT)$((NOT ACT_MAXNON(R,V,P,UPT))$RP_DP(R,P)) = EPS;
        db.put("ACT_MAXNON", """select d.r, y.y, d.p, u.u as upt, 0 as value from RP_DP d, MODLYEAR y, UPT u
                                where not in_ACT_MAXNON(d.r,y.y,d.p,u.u)""", zero="eps")
        # --- DP_NON(RTP(R,V,P),UPT,TSL,'UP')$((ACT_MAXNON(RTP,UPT)<8760/G_CYCLE(TSL))$RP_DPL(R,P,TSL)) = ACT_MAXNON(RTP,UPT)/8760;
        #     (the longest time a unit may be off line and still start up as UPT, as a fraction of the year)
        db.put("DP_NON", """select a.r, a.y, a.p, a.upt, l.tsl, 'UP' as l, a.value / 8760 as value from ACT_MAXNON a
                            join RP_DPL l on l.r=a.r and l.p=a.p
                            where in_RTP(a.r,a.y,a.p) and a.value < 8760 / v_G_CYCLE(l.tsl)""", zero="eps")
        # --- DP_NON(RTP(R,V,P),'WARM',TSL,'LO')$RP_DP(R,P) = DP_NON(RTP,'HOT',TSL,'UP');
        db.zap("DP_NON", "upt='WARM' and l='LO' and in_RTP(r,y,p) and in_RP_DP(r,p)")
        db.put("DP_NON", """select r, y, p, 'WARM' as upt, tsl, 'LO' as l, value from DP_NON
                            where upt='HOT' and l='UP' and in_RTP(r,y,p) and in_RP_DP(r,p)""", zero="eps")
        # --- DP_NON(RTP(R,V,P),UPT,TSL,'LO')$RP_DP(R,P) = MAX(DP_NON(RTP,UPT,TSL,'LO'),ACT_TIME(RTP,'LO')/8760);
        #     (the least time off line: the minimum off-line time)
        db.tmp("t_non", """select n.r, n.y, n.p, n.upt, n.tsl from DP_NON n where n.l='LO' and in_RTP(n.r,n.y,n.p) and in_RP_DP(n.r,n.p)
                           union select k.r, k.y, k.p, u.u, s.tsl from RTP k join RP_DP d on d.r=k.r and d.p=k.p, UPT u, TSLVL s
                           where in_ACT_TIME(k.r,k.y,k.p,'LO')""")
        db.put("DP_NON", """select r, y, p, upt, tsl, 'LO' as l,
                              greatest(coalesce(v_DP_NON(r,y,p,upt,tsl,'LO'), 0), coalesce(v_ACT_TIME(r,y,p,'LO'), 0) / 8760) as value
                            from t_non""", zero="eps")
        # --- DP_NON(RTP(R,V,P),UPT,TSL,BDNEQ(BD))$RP_DP(R,P) = DP_NON(RTP,UPT,TSL,BD)+(ACT_SDTIME(RTP,UPT,'UP')+ACT_SDTIME(RTP,'HOT','LO'))/8760;
        #     (both ends of the time off line move by the start-up and shut-down times)
        db.tmp("t_non", """select n.r, n.y, n.p, n.upt, n.tsl, n.l from DP_NON n where n.l in ('LO','UP') and in_RTP(n.r,n.y,n.p) and in_RP_DP(n.r,n.p)
                           union select k.r, k.y, k.p, u.u, s.tsl, b.l from RTP k join RP_DP d on d.r=k.r and d.p=k.p, UPT u, TSLVL s,
                             (select 'LO' as l union all select 'UP') b
                           where in_ACT_SDTIME(k.r,k.y,k.p,u.u,'UP') or in_ACT_SDTIME(k.r,k.y,k.p,'HOT','LO')""")
        db.put("DP_NON", """select r, y, p, upt, tsl, l, coalesce(v_DP_NON(r,y,p,upt,tsl,l), 0)
                              + (coalesce(v_ACT_SDTIME(r,y,p,upt,'UP'), 0) + coalesce(v_ACT_SDTIME(r,y,p,'HOT','LO'), 0)) / 8760 as value
                            from t_non""", zero="eps")
        # --- DP_NON(RTP(R,V,P),UPT,TSL,'UP')$(DP_NON(RTP,UPT,TSL,'UP')$RP_DP(R,P)) = DP_NON(RTP,UPT,TSL,'UP')-DP_NON(RTP,UPT,TSL,'LO');
        #     (UP becomes the width of the window; a difference of exactly 0 removes the record, EPS - 0 stays EPS)
        db.tmp("t_non", """select r, y, p, upt, tsl, value as up, coalesce(v_DP_NON(r,y,p,upt,tsl,'LO'), 0) as lo from DP_NON
                           where l='UP' and in_RTP(r,y,p) and in_RP_DP(r,p)""")
        db.zap("DP_NON", "l='UP' and in_RTP(r,y,p) and in_RP_DP(r,p)")
        db.put("DP_NON", """select r, y, p, upt, tsl, 'UP' as l, up - lo as value from t_non
                            where up - lo <> 0 or (up = 0 and lo = 0)""", zero="eps")
    # --- DP_NON(RTP,'COLD',TSL,'UP') = 0;
    db.zap("DP_NON", "upt='COLD' and l='UP' and in_RTP(r,y,p)")
    # --- ACT_SDTIME(RTP(R,V,P),UPT,BD)$(NOT RP_UPT(R,P,UPT,BD)) = 0;
    db.zap("ACT_SDTIME", "in_RTP(r,y,p) and not in_RP_UPT(r,p,upt,l)")
    # --- DP_PSUD(RTP,UPT,BDNEQ(BD))$((ACT_SDTIME(RTP,UPT,BD)>0)$ACT_SDTIME(RTP,UPT,BD)) = ACT_MINLD(RTP)/ACT_SDTIME(RTP,UPT,BD);
    #     (the load reached in an hour of starting up / shutting down)
    db.put("DP_PSUD", """select r, y, p, upt, l, case when in_ACT_MINLD(r,y,p) then coalesce(v_ACT_MINLD(r,y,p), 0) / value end as value
                         from ACT_SDTIME where l in ('LO','UP') and value > 0 and in_RTP(r,y,p)""", zero="eps")
    # --- ACT_LOSSD(RTP,UPT,BD)$(ACT_MINLD(RTP)$DP_PSUD(RTP,UPT,BD)<=DP_PSUD(RTP,UPT,BD)) = 0;
    #     (losses only where the start-up / shut-down takes more than an hour)
    db.zap("ACT_LOSSD", """in_RTP(r,y,p) and not (in_DP_PSUD(r,y,p,upt,l)
                                                  and coalesce(v_ACT_MINLD(r,y,p), 0) > coalesce(v_DP_PSUD(r,y,p,upt,l), 0))""")
    # --- OPTION CLEAR=TRACKP,DP_LOSD<ACT_LOSSD; DP_LOSD(RTP(R,V,P))$RP_PL(R,P,'N')$=RP_PL(R,P,'FX');
    db.assign("DP_LOSD", """select distinct r, y, p from ACT_LOSSD
                            union select r, y, p from RTP where in_RP_PL(r,p,'N') and in_RP_PL(r,p,'FX')""")
    if db.card("DP_LOSD"):
        # --- ACT_LOSPL(DP_LOSD(RTP(R,V,P)),'FX')$(ACT_LOSPL(RTP,'FX')=0) = .01**(1$RP_PL(R,P,'N'));
        db.put("ACT_LOSPL", """select d.r, d.y, d.p, 'FX' as l, case when in_RP_PL(d.r,d.p,'N') then 0.01 else 1 end as value
                               from DP_LOSD d where in_RTP(d.r,d.y,d.p) and coalesce(v_ACT_LOSPL(d.r,d.y,d.p,'FX'), 0) = 0""")
    if db.card("ACT_LOSSD"):
        # --- ACT_LOSSD(RTP,UPT,BD)$((ACT_LOSSD(RTP,UPT,BD)<ACT_LOSPL(RTP,'FX'))$ACT_LOSSD(RTP,UPT,BD)) = 0;
        db.zap("ACT_LOSSD", "in_RTP(r,y,p) and value < coalesce(v_ACT_LOSPL(r,y,p,'FX'), 0)")
        # --- DP_PSUD(DP_LOSD(RTP(R,V,P)),UPT,BDNEQ(BD)) =
        #       (DP_PSUD(RTP,UPT,BD)*(ACT_LOSSD(RTP,UPT,BD)/ACT_LOSPL(RTP,'FX')-1$RP_PL(R,P,'N'))/(ACT_MINLD(RTP)-DP_PSUD(RTP,UPT,BD)))$ACT_LOSSD(RTP,UPT,BD);
        #     (the vintages with losses keep DP_PSUD only where ACT_LOSSD is left, as the share of the losses)
        db.tmp("t_psud", """select s.r, s.y, s.p, s.upt, s.l, s.value as psud, a.value as lossd from DP_PSUD s
                            join DP_LOSD d on d.r=s.r and d.y=s.y and d.p=s.p
                            left join ACT_LOSSD a on a.r=s.r and a.y=s.y and a.p=s.p and a.upt=s.upt and a.l=s.l
                            where s.l in ('LO','UP') and in_RTP(s.r,s.y,s.p)""")
        db.zap("DP_PSUD", "l in ('LO','UP') and in_RTP(r,y,p) and in_DP_LOSD(r,y,p)")
        db.put("DP_PSUD", """select r, y, p, upt, l,
                               psud * (lossd / coalesce(v_ACT_LOSPL(r,y,p,'FX'), 0) - case when in_RP_PL(r,p,'N') then 1 else 0 end)
                                 / (coalesce(v_ACT_MINLD(r,y,p), 0) - psud) as value
                             from t_psud where lossd is not null""")


def coef_ext(db: DB):
    # ---- coef_ext.cli   (main_ext.mod: CLI before VDA and ABS)
    cli.coef_ext(db)
    # ---- coef_ext.vda
    if str(db.env.get("WAVER", "")).upper() == "YES":
        unsupported(db, "WAVER=YES (fillwave)")
    # --- $BATINCLUDE eqlducs.vda (coef_ext.vda 78): start-up types and partial loads
    eqlducs_prep(db)
    # --- $IF DEFINED COM_CSTBAL $BATINCLUDE powerflo.vda CSTBAL (coef_ext.vda 80): costs on the components of a node balance
    grids.cstbal(db)
    # --- LOOP(T, TRACKP(R,P)$((PRC_RESID(R,T,P)>0)$PRC_RESID(R,T,P)) = YES);
    db.tmp("t_p", "select distinct r, p from PRC_RESID where in_MILESTONYR(y) and value > 0 and in_REG(r)")
    # --- LOOP(PYR_S(V), LOOP(PRC_RCAP(TRACKP(R,P)),Z=SMAX(T,PRC_RESID(R,T,P));
    #       RTFORC(RTP_CPTYR(R,V,T,P))=Z-PRC_RESID(R,T,P)+EPS; PRC_RESID(R,T,P)$RTFORC(R,V,T,P)=Z);       retirable residual capacity:
    #     the stock is held at its maximum and the decline becomes a forced retirement
    db.x("""create or replace temp table n_forc as
            select c.r, c.y, c.y2, c.p, z.z - v_PRC_RESID(c.r,c.y2,c.p) as value, z.z
            from RTP_CPTYR c join t_p k on k.r=c.r and k.p=c.p
            join (select r, p, max(value) as z from PRC_RESID where in_MILESTONYR(y) group by r, p) z on z.r=c.r and z.p=c.p
            where in_PYR_S(c.y) and in_MILESTONYR(c.y2) and in_PRC_RCAP(c.r,c.p)""")
    db.put("RTFORC", "select r, y, y2, p, value from n_forc", zero="eps")
    db.put("PRC_RESID", "select distinct r, y2 as y, p, z as value from n_forc")
    # --- LOOP(PYR_S(V), NCAP_PASTI(R,V,P)$PRC_RESID(R,'0',P) = (SUM(T,PRC_RESID(R,T,P)*D(T))/SUM(T$(PRC_RESID(R,T,P)>0),D(T)))$TRACKP(R,P));
    db.x("""create or replace temp table n_pasti as
            select a.r, v.y, a.p, exists(select 1 from t_p k where k.r=a.r and k.p=a.p) as trk,
                   (select sum(b.value * v_D(b.y) order by yv(b.y)) from PRC_RESID b where b.r=a.r and b.p=a.p and in_MILESTONYR(b.y)) /
                   (select sum(v_D(b.y) order by yv(b.y)) from PRC_RESID b where b.r=a.r and b.p=a.p and in_MILESTONYR(b.y) and b.value > 0) as value
            from PRC_RESID a, PYR_S v where a.y='0' and in_REG(a.r)""")
    db.zap("NCAP_PASTI", "exists(select 1 from n_pasti n where n.r=NCAP_PASTI.r and n.y=NCAP_PASTI.y and n.p=NCAP_PASTI.p and not n.trk)")
    db.put("NCAP_PASTI", "select r, y, p, value from n_pasti where trk")
    # --- PRC_RESID(R,'0',P)$(NOT TRACKP(R,P)) = 0;
    db.zap("PRC_RESID", "y='0' and in_REG(r) and not exists(select 1 from t_p k where k.r=PRC_RESID.r and k.p=PRC_RESID.p)")
    # --- COEF_CPT(RTP_CPTYR(R,PYR_S(V),T,P))$TRACKP(R,P) = PRC_RESID(R,T,P)/NCAP_PASTI(R,V,P);
    db.x("""create or replace temp table n_cpt as
            select c.r, c.y, c.y2, c.p, v_PRC_RESID(c.r,c.y2,c.p) / v_NCAP_PASTI(c.r,c.y,c.p) as value
            from RTP_CPTYR c join t_p k on k.r=c.r and k.p=c.p where in_PYR_S(c.y)""")
    db.zap("COEF_CPT", "exists(select 1 from n_cpt n where n.r=COEF_CPT.r and n.y=COEF_CPT.y and n.y2=COEF_CPT.y2 and n.p=COEF_CPT.p)")
    db.put("COEF_CPT", "select r, y, y2, p, value from n_cpt")
    # --- $IFI NOT %STSFLX%==YES RP_STL(RP_STS,TSL,BD)=0;
    if str(db.env.get("STSFLX", "")).strip("'\"").upper() == "YES":
        unsupported(db, "run-file switch STSFLX=YES (flexible timeslice storage levels)")
    db.remove("RP_STL", where="in_RP_STS(r,p) and l in ('LO','UP','FX')")
    # --- COEF_AFUPS(RTP(R,V,P),S)$(NOT RPS_CAFLAC(R,P,S,'UP')) $= NCAP_AF(RTP,S,'UP')$RPS_STG(R,P,S);
    db.put("COEF_AFUPS", """select r, y, p, s, value from NCAP_AF where l='UP' and in_RTP(r,y,p) and in_RPS_STG(r,p,s)
                            and not in_RPS_CAFLAC(r,p,s,'UP')""", zero="eps")
    # --- COEF_AFUPS(RTP(R,V,P),S(STL))$RPS_STG(R,P,S) $= NCAP_AFC(RTP,%PGPRIM%,STL);
    db.put("COEF_AFUPS", """select r, y, p, stl as s, value from NCAP_AFC where cg='ACT' and in_RTP(r,y,p) and in_RPS_STG(r,p,stl)""",
           zero="eps")
    # --- COEF_AFUPS(R,V,P,S)$(NOT PRC_CAP(R,P)) = NO;
    db.zap("COEF_AFUPS", "in_REG(r) and not in_PRC_CAP(r,p)")
    # --- ACT_CSTUP(RTP(R,V,P),TSL(S),CUR)$(RDCUR(R,CUR)$STG_MAXCYC(RTP)) = ACT_CSTUP(RTP,TSL,CUR)*G_DRATE(R,V,CUR)/(1-(1+G_DRATE(R,V,CUR))**(-NCAP_TLIFE(RTP)));
    #     (the cycling penalty is the investment annuity)
    db.put("ACT_CSTUP", """select a.r, a.y, a.p, a.tsl, a.cur,
                                  a.value * v_G_DRATE(a.r,a.y,a.cur) / (1 - power(1 + v_G_DRATE(a.r,a.y,a.cur), -v_NCAP_TLIFE(a.r,a.y,a.p))) as value
                           from ACT_CSTUP a where in_RTP(a.r,a.y,a.p) and in_RDCUR(a.r,a.cur) and in_TSLVL(a.tsl)
                           and in_STG_MAXCYC(a.r,a.y,a.p)""", zero="eps")
    # --- OPTION TRACKP < RTP, TRACKC < RHS_COMBAL, RCS < IRE_FLOSUM;
    #     LOOP(TRACKP(R,P),TRACKC(R,C)$TOP(R,P,C,'IN') = YES);  TRACKC(R,C) $= SUM(RPC_IRE(TRACKP(R,P),C,'EXP'),1);
    #     TRACKC(RC) $= SUM(RCS(RC,S),1); TRACKC(DEM)=YES;  TRACKC(R,C) $= SUM(RPC_NOFLO(TRACKP(R,P),C),1);
    db.tmp("t_p", "select distinct r, p from RTP")
    db.tmp("t_c", """select distinct r, c from RHS_COMBAL union
                     select t.r, t.c from TOP t join t_p k on k.r=t.r and k.p=t.p where t.io='IN' union
                     select i.r, i.c from RPC_IRE i join t_p k on k.r=i.r and k.p=i.p where i.ie='EXP' union
                     select distinct r, c2 as c from IRE_FLOSUM where in_RC(r,c2) union
                     select r, c from DEM union
                     select n.r, n.c from RPC_NOFLO n join t_p k on k.r=n.r and k.p=n.p""")
    # --- RCS_COMBAL(RTCS_VARC(R,T,C,S),L)$(NOT TRACKC(R,C)) = NO;                     commodities nobody consumes: no balance
    db.remove("RCS_COMBAL", where="""in_RTCS_VARC(r,y,c,s) and not exists(select 1 from t_c k where k.r=RCS_COMBAL.r and k.c=RCS_COMBAL.c)""")
    # --- TRACKC(RC) = COM_UNIT(RC,'UCU')$(NOT TRACKC(RC));
    db.tmp("t_u", "select r, c from RC k where in_COM_UNIT(r,c,'UCU') and not exists(select 1 from t_c z where z.r=k.r and z.c=k.c)")
    # --- RTCS_VARC(R,T,C,S)$((NOT RHS_COMPRD(R,T,C,S))$TRACKC(R,C)) = NO;
    db.remove("RTCS_VARC", where="""not in_RHS_COMPRD(r,y,c,s) and exists(select 1 from t_u k where k.r=RTCS_VARC.r and k.c=RTCS_VARC.c)""")
    # --- RPC_CONLY(RTPC(R,T,P,C))$(NOT RTC(R,T,C)) $= TRACKC(R,C);
    db.add("RPC_CONLY", """select k.r, k.y, k.p, k.c from RTPC k join t_u u on u.r=k.r and u.c=k.c where not in_RTC(k.r,k.y,k.c)""")
    # --- TOP_IRE('IMPEXP',C,TRACKC,P) = NO;
    db.remove("TOP_IRE", where="r='IMPEXP' and exists(select 1 from t_u u where u.r=TOP_IRE.r2 and u.c=TOP_IRE.c2)")
    # --- UC_TIME with option -13 on year 0
    if db.q1("select count(*) from UC_TIME where y='0' and round(value) = -13"):
        unsupported(db, "UC_TIME option -13")
    # --- RP_CGC(RPG_1ACE) = YES; OPTION TRACKPC < RPG_1ACE, RP_GRP < RP_CGC;
    #     TRACKPC(TRACKPC) = RPC_FFUNC(TRACKPC);                     (the single flows replaced by the activity: REDUCE YES)
    #     ACT_FLO(RTP(R,V,P),C,S)$(RPCS_VAR(R,P,C,S)$TRACKPC(R,P,C)) =
    #        1/SUM(RP_CGC(R,P,CG,C),MAX(MICRO,ACT_EFF(RTP,CG,S)*(1+(ACT_EFF(RTP,C,S)-1)$ACT_EFF(RTP,C,S))));
    db.tmp("t_1ace", "select r, p, cg, c, in_RPC_FFUNC(r,p,c) as red from RPG_1ACE")
    if db.q1("select count(*) from t_1ace where red"):
        db.put("ACT_FLO", """select k.r, k.y, k.p, g.c as cg, v.s,
                                    1 / sum(greatest(1e-6, v_ACT_EFF(k.r,k.y,k.p,g.cg,v.s)
                                        * (case when in_ACT_EFF(k.r,k.y,k.p,g.c,v.s) then v_ACT_EFF(k.r,k.y,k.p,g.c,v.s) else 1 end))
                                        order by g.cg) as value
                             from RTP k join t_1ace g on g.r=k.r and g.p=k.p and g.red
                             join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=g.c
                             group by k.r, k.y, k.p, g.c, v.s""")
    # --- OPTION CG_GRP <= RTP_FFCX;
    #     LOOP(RPCG_PTRAN(RP,C,COM,CG,CG2)$CG_GRP(RP,CG,CG2),IF(RPC_FFUNC(RP,C),RP_DCGG(RP,C,CG,CG2,'UP')=YES; ELSE RP_DCGG(RP,COM,CG,CG2,'LO')=YES));
    #     RP_DCGG(TRACKPC(RP,COM),CG,C,'UP')$(RP_CGC(RP,CG,COM)$RPC_ACT(RP,C)) $= CG_GRP(RP,CG,C);
    #     RTP_FFCX(RTP_CAPYR(R,V,T,P),ACTCG,C)$RPC_FFUNC(R,P,C) $= SUM(RP_DCGG(R,P,C,CG,CG2,L),...);
    #     LOOP(RP_DCGG(R,P,C,CG,CG2,L),RTP_FFCX(R,V,T,P,CG,CG2)=0);
    #     (BDSIG: LO 1, UP -1: a shape of the flow that drives the activity is inverted)
    if db.card("RTP_FFCX") and db.card("RPC_FFUNC"):
        db.tmp("t_cgg", "select distinct r, p, cg, cg2 from RTP_FFCX")
        db.tmp("t_dcgg", """select distinct g.r, g.p, case when in_RPC_FFUNC(g.r,g.p,g.c) then g.c else g.c2 end as c, g.cg, g.cg2,
                                   case when in_RPC_FFUNC(g.r,g.p,g.c) then 'UP' else 'LO' end as l
                            from RPCG_PTRAN g join t_cgg k on k.r=g.r and k.p=g.p and k.cg=g.cg and k.cg2=g.cg2
                            union
                            select a.r, a.p, a.c, a.cg, x.cg as cg2, 'UP' as l from t_1ace a
                            join RPC_ACT x on x.r=a.r and x.p=a.p join t_cgg k on k.r=a.r and k.p=a.p and k.cg=a.cg and k.cg2=x.cg
                            where a.red""")
        db.put("RTP_FFCX", """select k.r, k.y, k.y2, k.p, 'ACT' as cg, d.c as cg2,
                                     sum(case when d.l = 'LO' then coalesce(f.value, 0)
                                              when coalesce(f.value, 0) + 1 <> 0 then 1 / (coalesce(f.value, 0) + 1) - 1 else 0 end
                                         order by d.cg, d.cg2, d.l) as value
                              from RTP_CAPYR k join t_dcgg d on d.r=k.r and d.p=k.p
                              left join RTP_FFCX f on f.r=k.r and f.y=k.y and f.y2=k.y2 and f.p=k.p and f.cg=d.cg and f.cg2=d.cg2
                              where in_RPC_FFUNC(k.r,k.p,d.c)
                              group by k.r, k.y, k.y2, k.p, d.c""", zero="skip")
        db.remove("RTP_FFCX", where="exists(select 1 from t_dcgg d where d.r=RTP_FFCX.r and d.p=RTP_FFCX.p and d.cg=RTP_FFCX.cg and d.cg2=RTP_FFCX.cg2)")
    # --- RP_CGC(R,P,CG,C)$TRACKPC(R,P,C) = NO;
    #     COEF_PTRAN(RTP(R,V,P),CG,C,COM,S)$(RPCS_VAR(R,P,C,S)$RPC_PG(R,P,COM)$RP_CGC(R,P,CG,C)) =
    #        ACT_EFF(RTP,CG,S)*PRC_ACTFLO(RTP,COM)*(1+(ACT_EFF(RTP,C,S)-1)$ACT_EFF(RTP,C,S));
    db.x("""create or replace temp table n_ptr as
            select k.r, k.y, k.p, g.cg, g.c, q.c as cg2, v.s,
                   v_ACT_EFF(k.r,k.y,k.p,g.cg,v.s) * v_PRC_ACTFLO(k.r,k.y,k.p,q.c)
                   * (case when in_ACT_EFF(k.r,k.y,k.p,g.c,v.s) then v_ACT_EFF(k.r,k.y,k.p,g.c,v.s) else 1 end) as value,
                   -- EPS*x is EPS, 0*EPS is no record (as in GAMS): the product is EPS when both records exist
                   -- and the last factor is not 0 (1+(EPS-1)$EPS is 0)
                   in_ACT_EFF(k.r,k.y,k.p,g.cg,v.s) and in_PRC_ACTFLO(k.r,k.y,k.p,q.c)
                   and (not in_ACT_EFF(k.r,k.y,k.p,g.c,v.s) or v_ACT_EFF(k.r,k.y,k.p,g.c,v.s) <> 0) as eps_
            from RTP k join t_1ace g on g.r=k.r and g.p=k.p and not g.red join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=g.c
            join RPC_PG q on q.r=k.r and q.p=k.p""")
    db.zap("COEF_PTRAN", """exists(select 1 from n_ptr n where n.r=COEF_PTRAN.r and n.y=COEF_PTRAN.y and n.p=COEF_PTRAN.p and n.cg=COEF_PTRAN.cg
                                   and n.c=COEF_PTRAN.c and n.cg2=COEF_PTRAN.cg2 and n.s=COEF_PTRAN.s)""")
    #     (an EPS factor, PRC_ACTFLO given as 0: GAMS keeps the EPS product)
    db.put("COEF_PTRAN", "select r, y, p, cg, c, cg2, s, value from n_ptr where value <> 0 or eps_", zero="eps")
    # --- ACT_EFF(R,LL,P,CG,S)$RP_GRP(R,P,CG) = 0;         (RP_GRP < RP_CGC: the groups of RPG_1ACE)
    db.zap("ACT_EFF", "exists(select 1 from RPG_1ACE g where g.r=ACT_EFF.r and g.p=ACT_EFF.p and g.cg=ACT_EFF.cg)")
    # --- OPTION RP_GRP < RP_CGC; RPCC_FFUNC(RP_GRP(R,P,CG),COM)$RPC_PG(R,P,COM) = YES;
    db.add("RPCC_FFUNC", "select distinct g.r, g.p, g.cg, q.c as cg2 from t_1ace g join RPC_PG q on q.r=g.r and q.p=g.p where not g.red")
    # --- $IFI NOT %SENSIS%==YES OPTION CLEAR=RPCG_PTRAN;
    #     OPTION CLEAR=TRACKPC,CLEAR=RP_GRP,CLEAR=CG_GRP,CLEAR=RP_DCGG,CLEAR=RTP_CAPYR,CLEAR=RP_CGC;
    if db.ctl.get("SENSIS"):
        db.clear("RTP_CAPYR")              # (RPCG_PTRAN kept: sensis.stc 33 remaps the reduced FUNC flows by it)
    else:
        db.clear("RPCG_PTRAN", "RTP_CAPYR")
    eqashar_prep(db)
    # --- COEF_PVT(R,T)$(NOT COEF_PVT(R,T)) = FPD(T);  VDA_DISC(R,T) $= COEF_PVT(R,T);
    db.put("COEF_PVT", "select r, y, v_FPD(y) as value from REG, MILESTONYR where v_COEF_PVT(r,y) = 0")
    db.put("VDA_DISC", "select r, y, value from COEF_PVT where in_MILESTONYR(y)", zero="eps")
    # --- COEF_ILED(RTP(R,T,P))$NCAP_BND(RTP,'N') = MOD(COEF_ILED(RTP),1000)+EPS$NCAP_ILED(RTP);
    #     (an exact start year, prep_ext.vda: the lead time no longer moves the investment costs)
    q = """select k.r, k.y, k.p, fmod(v_COEF_ILED(k.r,k.y,k.p), 1000) as value from RTP k
            join NCAP_BND n on n.r=k.r and n.y=k.y and n.p=k.p and n.l='N' and n.value <> 0 where in_MILESTONYR(k.y)"""
    db.put("COEF_ILED", f"select r, y, p, value from ({q}) where in_NCAP_ILED(r,y,p)", zero="eps")
    db.put("COEF_ILED", f"select r, y, p, value from ({q}) where not in_NCAP_ILED(r,y,p)")
    # ---- coef_ext.abs     (main_ext.mod: VDA before ABS)
    abs_ext.coef_ext(db)
