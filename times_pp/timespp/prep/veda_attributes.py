# SPDX-License-Identifier: GPL-3.0-or-later
"""ppm_ext.vda (+ pp_actef.vda LVL): VEDA attributes after the main preprocessor.

Emission factors by input commodity (VDA_EMCB) become FLO_SUM entries; process efficiencies
(ACT_EFF) are attached to the shadow group or its commodities and moved to the right timeslices."""
from ..controls import unsupported
from ..engine import DB
from .common import require_empty
from . import cli, dsc, dynamic_bounds, dynslite, mlf, resloadc


def afc(db: DB):
    """ppm_ext.vda, 'Prepare commodity-specific availability factors' (NCAP_AFC -> NCAP_AFCS by timeslice, RPS_CAFLAC)."""
    x = db.x
    V = "in_MODLYEAR(y)"
    # --- OPTION RP_GRP<NCAP_AFC, RP_XRED<RP_GRP;  RP_GRP(RP_PG(R,P,CG))$(NOT C(CG)+COM_TYPE(CG)) = NO;
    db.tmp("t_grp", "select distinct r, p, cg from NCAP_AFC where in_REG(r)")
    db.assign("RP_XRED", "select distinct r, p from t_grp")
    x("delete from t_grp where in_RP_PG(r,p,cg) and not (in_COM(cg) or in_COM_TYPE(cg))")
    # --- PRC_SC(RP_STG(RP_XRED(RP)))=SUM(PRC_TSL(RP,TSL),LOG(G_CYCLE(TSL)));
    db.clear("PRC_SC")
    db.put("PRC_SC", """select k.r, k.p, sum(ln(v_G_CYCLE(l.tsl))) as value from RP_XRED k join PRC_TSL l on l.r=k.r and l.p=k.p
                        where in_RP_STG(k.r,k.p) group by k.r, k.p""")
    # --- LOOP(TSL(STL),NCAP_AFCS(R,LL,P,CG,S)$TS_GROUP(R,TSL,S) $= NCAP_AFC(R,LL,P,CG,STL)$RP_GRP(R,P,CG));
    grp = "exists(select 1 from t_grp g where g.r=a.r and g.p=a.p and g.cg=a.cg)"
    db.put("NCAP_AFCS", f"""select a.r, a.y, a.p, a.cg, g.s, a.value from NCAP_AFC a join TS_GROUP g on g.r=a.r and g.tsl=a.stl
                            where {grp}""", zero="eps")
    # --- NCAP_AFCS(R,LL,P,CG,S(STL))$RP_GRP(R,P,CG) $= NCAP_AFC(R,LL,P,CG,STL); OPTION CLEAR=NCAP_AFC;
    db.put("NCAP_AFCS", f"""select a.r, a.y, a.p, a.cg, a.stl as s, a.value from NCAP_AFC a
                            where {grp} and exists(select 1 from TS_GROUP g where g.r=a.r and g.s=a.stl)""", zero="eps")
    db.clear("NCAP_AFC")
    # --- NCAP_AFCS(R,LL,P,CG,S)$(NOT PRC_CAP(R,P))=0;
    db.zap("NCAP_AFCS", "in_REG(r) and not in_PRC_CAP(r,p)")
    # --- independent AFCs:
    #     LOOP(RP_GRP(RP_FLO(R,P),CG),IF(SUM(RC(R,C(CG))$(NOT RPC_PG(R,P,C)),1)+1$(NOT RP_PGTYPE(R,P,CG)+C(CG)),TRACKPG(R,P,CG)=YES));
    #     TRACKPG(RP_GRP(RP_STG,%PGPRIM%))=YES;
    db.tmp("t_tpg", """select r, p, cg from t_grp where
                         (in_RP_FLO(r,p) and ((in_COM(cg) and in_RC(r,cg) and not in_RPC_PG(r,p,cg))
                                              or not (in_RP_PGTYPE(r,p,cg) or in_COM(cg))))
                         or (in_RP_STG(r,p) and cg='ACT')""")
    tpg = "exists(select 1 from t_tpg g where g.r=a.r and g.p=a.p and g.cg=a.cg)"
    # --- NCAP_AFC(R,V,P,CG,STL(S))$TRACKPG(R,P,CG) $= NCAP_AFCS(R,V,P,CG,S);
    db.put("NCAP_AFC", f"select r, y, p, cg, s as stl, value from NCAP_AFCS a where {V} and {tpg}", zero="eps")
    # --- NCAP_AFC(R,V,P,C,STL(S))$(RC(R,C)$NCAP_AFCS(R,'0',P,%PGPRIM%,S)) $= NCAP_AFCS(R,V,P,C,S);
    db.put("NCAP_AFC", f"""select r, y, p, cg, s as stl, value from NCAP_AFCS a where {V} and in_COM(cg) and in_RC(r,cg)
                           and in_NCAP_AFCS(r,'0',p,'ACT',s)""", zero="eps")
    # --- NCAP_AFCS(R,V,P,CG,S)$(RP_FLO(R,P)$TRACKPG(R,P,CG)) = 0;
    x(f"delete from NCAP_AFCS a where {V} and in_RP_FLO(r,p) and {tpg}")
    # --- NCAP_AFCS(R,V,P,CG,S)$(NCAP_AFCS(R,'0',P,%PGPRIM%,S)$RP_FLO(R,P)) = 0;
    db.tmp("t_opt", "select r, p, s from NCAP_AFCS where y='0' and cg='ACT'")
    x(f"delete from NCAP_AFCS a where {V} and in_RP_FLO(r,p) and exists(select 1 from t_opt o where o.r=a.r and o.p=a.p and o.s=a.s)")
    # --- NCAP_AFCS(R,V,P,CG,S)$((NOT RP_STG(R,P))$RP_PGTYPE(R,P,CG)) $= NCAP_AFCS(R,V,P,%PGPRIM%,S);
    db.put("NCAP_AFCS", f"""select a.r, a.y, a.p, t.cg, a.s, a.value from NCAP_AFCS a join RP_PGTYPE t on t.r=a.r and t.p=a.p
                            where a.cg='ACT' and in_MODLYEAR(a.y) and not in_RP_STG(a.r,a.p)""", zero="eps")
    # --- OPTION RVPS < NCAP_AFCS;                                               (all years that carry data, not only V)
    db.tmp("t_rvps", "select distinct r, y, p, s from NCAP_AFCS")
    # --- NCAP_AFCS(RTP(R,V,P),ACTCG,S(STL))$((NOT RVPS(RTP,S))$RP_STG(R,P)) $= NCAP_AFC(RTP,ACTCG,STL);
    db.put("NCAP_AFCS", """select a.r, a.y, a.p, a.cg, a.stl as s, a.value from NCAP_AFC a where a.cg='ACT' and in_RTP(a.r,a.y,a.p)
                           and in_RP_STG(a.r,a.p) and exists(select 1 from TS_GROUP g where g.r=a.r and g.s=a.stl)
                           and not exists(select 1 from t_rvps v where v.r=a.r and v.y=a.y and v.p=a.p and v.s=a.stl)""", zero="eps")
    # --- RVPS(R,V,P,S)$(RTP(R,V,P)->RP_STD(R,P)$RP_PGACT(R,P)) = NO;
    x(f"delete from t_rvps where {V} and in_REG(r) and (not in_RTP(r,y,p) or (in_RP_STD(r,p) and in_RP_PGACT(r,p)))")
    # --- RTPS_BD(RVPS(R,V,P,S),BDUPX(BD))$(PRC_TS(R,P,S)*NCAP_AF(R,V,P,S,BD)) = YES;   ... $NCAP_AFS(R,V,P,S,BD);   ... ANNUAL $NCAP_AFA(R,V,P,BD)
    db.tmp("t_bd", f"""select v.r, v.y, v.p, v.s, b.l from t_rvps v, (values ('FX'),('UP')) b(l) where {V} and in_REG(v.r)
                       and ((in_PRC_TS(v.r,v.p,v.s) and in_NCAP_AF(v.r,v.y,v.p,v.s,b.l)) or in_NCAP_AFS(v.r,v.y,v.p,v.s,b.l)
                            or (v.s='ANNUAL' and in_NCAP_AFA(v.r,v.y,v.p,b.l)))""")
    # --- LOOP(BDUPX,RVPS(R,V,P,S)$RTPS_BD(R,V,P,S,BDUPX) = NO);
    x("delete from t_rvps v where exists(select 1 from t_bd b where b.r=v.r and b.y=v.y and b.p=v.p and b.s=v.s)")
    # --- RTPS_BD(RVPS,'UP') = YES;  NCAP_AFS(RVPS,'UP') = 1;  OPTION RPS_CAFLAC < RTPS_BD;
    x("insert into t_bd select r, y, p, s, 'UP' from t_rvps")
    db.put("NCAP_AFS", "select r, y, p, s, 'UP' as l, 1 as value from t_rvps")
    db.assign("RPS_CAFLAC", "select distinct r, p, s, l from t_bd")
    # --- NCAP_AFC(RTP,C,STL(S))$(NCAP_AFCS(RTP,C,S)=0) $= NCAP_AFCS(RTP,C,S);
    db.put("NCAP_AFC", "select r, y, p, cg, s as stl, value from NCAP_AFCS where value = 0 and in_RTP(r,y,p) and in_COM(cg)", zero="eps")
    # --- NCAP_AFCS(R,V,P,CG,S)$((NCAP_AFCS(R,V,P,CG,S)<=0)$NCAP_AFCS(R,V,P,CG,S)) = 1+INF$(RP_STD(R,P) OR (NOT C(CG)));
    x(f"""update NCAP_AFCS set value = case when in_RP_STD(r,p) or not in_COM(cg) then 'inf'::double else 1 end
          where {V} and in_REG(r) and value <= 0""")
    # --- RPG_AFCX(RPC_STG,IE(XPT)) $= TOP(RPC_STG,'OUT');
    db.add("RPG_AFCX", "select r, p, c, 'EXP' as ie from RPC_STG where in_TOP(r,p,c,'OUT')")
    # --- Enable flexible STS only where AF on activity
    #     TRACKP(RP_STS(RP)) $= SUM(RPS_CAFLAC(RPS_STG(RP,S),BD),1); OPTION RP_GRP<NCAP_AFC;
    #     RP_STL(PRC_CAP(RP_STS(RP)),TSL,'UP')$(TRACKP(RP)->RP_GRP(RP,%PGPRIM%)) $= RP_STL(RP,TSL,'N');
    db.add("RP_STL", """select k.r, k.p, k.tsl, 'UP' as l from RP_STL k where k.l='N' and in_RP_STS(k.r,k.p) and in_PRC_CAP(k.r,k.p)
                        and (not exists(select 1 from RPS_CAFLAC c where c.r=k.r and c.p=k.p and in_RPS_STG(c.r,c.p,c.s))
                             or exists(select 1 from NCAP_AFC a where a.r=k.r and a.p=k.p and a.cg='ACT'))""")
    # --- automatic NCAP_AFC for extraction-condensing CHP:
    #     RVP(RTP(R,V,P))$((NOT RPS_CAFLAC(R,P,'ANNUAL','UP'))$(NCAP_CHPR(RTP,'UP')*NCAP_AFA(RTP,'UP')>0)$CHP(R,P))=YES;  RVP(RTP)$(NCAP_CEH(RTP)<1.5) = NO;
    db.tmp("t_ect", """select k.r, k.y, k.p from RTP k where in_CHP(k.r,k.p) and not in_RPS_CAFLAC(k.r,k.p,'ANNUAL','UP')
                       and v_NCAP_CHPR(k.r,k.y,k.p,'UP') * v_NCAP_AFA(k.r,k.y,k.p,'UP') > 0 and v_NCAP_CEH(k.r,k.y,k.p) >= 1.5""")
    if db.q1("select count(*) from t_ect"):
        # --- VDA_CEH(RVP(R,V,P)) = MAX(0,SMAX((PRC_TS(R,P,S),CHP_ELC(R,P,C)),NCAP_AF(RVP,S,'UP')*PRC_ACTFLO(RVP,C)));
        #     (the maximum technical availability for electricity, corrected with ACTFLO)
        #     RVP(RTP)$(VDA_CEH(RTP)<=0) = NO;
        db.tmp("t_ect2", """select e.r, e.y, e.p, greatest(0, max(coalesce(v_NCAP_AF(e.r,e.y,e.p,t.s,'UP'),0)
                                                                 * coalesce(v_PRC_ACTFLO(e.r,e.y,e.p,c.c),0))) as ceh
                            from t_ect e join PRC_TS t on t.r=e.r and t.p=e.p join CHP_ELC c on c.r=e.r and c.p=e.p
                            group by e.r, e.y, e.p having greatest(0, max(coalesce(v_NCAP_AF(e.r,e.y,e.p,t.s,'UP'),0)
                                                                      * coalesce(v_PRC_ACTFLO(e.r,e.y,e.p,c.c),0))) > 0""")
        # --- RPS_CAFLAC(R,P,ANNUAL,'UP') $= SUM(RVP(R,V,P)$VDA_CEH(RVP),1);
        db.add("RPS_CAFLAC", "select distinct r, p, 'ANNUAL' as s, 'UP' as l from t_ect2")
        # --- AFAC for heat = (heat share)/(1/AFA-(elec share)/AF):
        #     NCAP_AFCS(RVP(R,V,P),C,ANNUAL)$RPC_PG(R,P,C) =
        #       (1/(1+1/NCAP_CHPR(RVP,'UP'))) / NCAP_AFA(RVP,'UP') / PRC_ACTFLO(RVP,C) /
        #       (1/NCAP_AFA(RVP,'UP')-(1-1/(1+1/NCAP_CHPR(RVP,'UP')))/VDA_CEH(RVP));
        #     NCAP_AFCS(RVP(R,V,P),C,ANNUAL)$CHP_ELC(R,P,C) = VDA_CEH(RVP) / NCAP_AFA(RVP,'UP') / PRC_ACTFLO(RVP,C);
        db.put("NCAP_AFCS", """select e.r, e.y, e.p, g.c as cg, 'ANNUAL' as s,
                                      case when in_CHP_ELC(e.r,e.p,g.c) then e.ceh / v_NCAP_AFA(e.r,e.y,e.p,'UP') / v_PRC_ACTFLO(e.r,e.y,e.p,g.c)
                                      else (1/(1+1/v_NCAP_CHPR(e.r,e.y,e.p,'UP'))) / v_NCAP_AFA(e.r,e.y,e.p,'UP') / v_PRC_ACTFLO(e.r,e.y,e.p,g.c)
                                           / (1/v_NCAP_AFA(e.r,e.y,e.p,'UP') - (1-1/(1+1/v_NCAP_CHPR(e.r,e.y,e.p,'UP')))/e.ceh) end as value
                               from t_ect2 e join RPC_PG g on g.r=e.r and g.p=e.p""")
    # --- OPTION CLEAR=RVP,VDA_CEH<NCAP_CEH;                                     (same dimensions: the values are copied)
    db.clear("VDA_CEH")
    x("insert into VDA_CEH select * from NCAP_CEH")


def ppm_ext(db: DB):
    from ..lvl import trees, aggregate, read_series, _out, _write
    # ---- ppm_ext.mlf (EXTEND lists MLF before DSC and VDA, initmty.mod 464-468)
    mlf.ppm_ext(db)
    # ---- ppm_ext.cli (EXTEND lists CLI after MLF, before DSC and VDA)
    cli.ppm_ext(db)
    # ---- ppm_ext.dsc: NCAP_DISC(RTP(R,T,P),'0')$PRC_DSCNCAP(R,P) = EPS$(NOT NCAP_SEMI(R,T,P));
    dsc.ppm(db)
    # ---- ppm_ext.vda
    # --- $IF DEFINED GR_VARGEN $BATINCLUDE resloadc.vda COEF
    resloadc.coef(db)
    # (NCAP_AFSX given by the user passes through; ppm_ext.vda line 161 writes it only by the NCAP_AFX control option)
    # (NCAP_AFCS given in the input is NCAP_AFC by now: prep_ext.vda 14 moves it and clears it; it is made again below)
    require_empty(db, ["KEEP_FLOF"], "availability shapes / shape indexes / ACT_FLO (ppm_ext.vda)")
    # --- PRC_YMIN(R,P)$NCAP_AFX(R,'0',P) = FLOOR(NCAP_AFX(R,'0',P)/1000);  NCAP_AFSX ... $= NCAP_AFX;  RP_AFB = -1
    #     (control digits above 999 in the year-0 option of NCAP_AFX; an EPS option is EPS through FLOOR and MOD)
    if db.q1("select count(*) from NCAP_AFX where y='0'"):
        # ym: FLOOR(NCAP_AFX(R,'0',P)/1000); eps: the option given as 0 (then MOD(ym,k) is EPS, true, and 0 as a number)
        db.tmp("t_ym", "select r, p, floor(value/1000) as ym, value = 0 as eps from NCAP_AFX where y='0' and (value = 0 or floor(value/1000) <> 0)")
        # sign test of a bound: (MOD(PRC_YMIN,2)*2-1)*(1-2$BDUPX(BD)) < 0
        sgn = "((case when m.eps then 0 else mod(m.ym, 2) end) * 2 - 1) * (case when b.l in ('UP','FX') then -1 else 1 end) < 0"
        # --- NCAP_AFSX(R,FIL(LL),P,BD)$((NCAP_AFSX(R,LL,P,BD)=0)$(sign)$MOD(PRC_YMIN(R,P),7-4$V(LL))) $= NCAP_AFX(R,LL,P);
        db.put("NCAP_AFSX", f"""select x.r, x.y, x.p, b.l, x.value from NCAP_AFX x join t_ym m on m.r=x.r and m.p=x.p,
                                (values ('LO'),('UP'),('FX')) b(l)
                                where (in_MODLYEAR(x.y) or x.y = '0') and v_NCAP_AFSX(x.r,x.y,x.p,b.l) = 0 and {sgn}
                                  and (m.eps or mod(m.ym, case when in_MODLYEAR(x.y) then 3 else 7 end) <> 0)""", zero="eps")
        # --- RP_AFB(R,P,BD)$((MOD(PRC_YMIN(R,P)$(sign),5)=0)$PRC_YMIN(R,P)) = -1;
        #     (a bound failing the sign test takes MOD(0,5) = 0: -1 there too)
        db.put("RP_AFB", f"""select m.r, m.p, b.l, -1 as value from t_ym m, (values ('LO'),('UP'),('FX')) b(l)
                             where (not ({sgn}) or m.eps or mod(m.ym, 5) = 0)""")
    # --- FIL(LL)=V(LL)+LASTLL(LL);
    #     NCAP_AFSM(R,FIL(LL),P)$MOD(FLOOR(NCAP_AFM(R,LL,P)/1000),7-4$V(LL)) $= NCAP_AFM(R,LL,P);
    #     NCAP_AFM(RTP(R,V,P))$((MOD(MAX(1,FLOOR(NCAP_AFM(R,'0',P)/1000)),5)=0)$NCAP_AFM(RTP)) = 0;
    #     (the code above 999 of a pointer: on the vintages MOD 3, on year 0 MOD 7; code 5 leaves the curve to NCAP_AFSM)
    if db.card("NCAP_AFM"):
        db.put("NCAP_AFSM", """select r, y, p, value from NCAP_AFM
                               where (in_MODLYEAR(y) or y = '0')
                                 and (value = 0 or mod(floor(value/1000), case when in_MODLYEAR(y) then 3 else 7 end) <> 0)""", zero="eps")
        #     (EPS through FLOOR and MOD stays EPS, and $EPS is true: a pointer given as 0 is copied)
        db.zap("NCAP_AFM", """in_RTP(r,y,p) and mod(greatest(1, floor(v_NCAP_AFM(r,'0',p)/1000)), 5) = 0""")
    # --- OPTION RP_UPL < ACT_UPS;  RP_UPL(RP,L)$(NOT PRC_CAP(RP)*RP_STD(RP)) = NO;
    db.assign("RP_UPL", "select distinct r, p, l from ACT_UPS where in_PRC_CAP(r,p) and in_RP_STD(r,p)")
    # --- RP_PL(R,P,LNX) $= SUM(V$ACT_LOSPL(R,V,P,'FX'),1);       (partial loads: LNX = N, FX; an EPS record counts)
    db.add("RP_PL", """select distinct a.r, a.p, b.l from ACT_LOSPL a, (select 'N' as l union all select 'FX') b
                       where a.l = 'FX' and in_REG(a.r) and in_MODLYEAR(a.y)""")
    # --- $BATINCLUDE equcrtp.vda PPM_EXT   (the dynamic bounds by process are not user constraints)
    dynamic_bounds.ppm_ext(db)
    # --- FS_EMCB(RP_IRE(R,P),COM,C) = NO;
    db.remove("FS_EMCB", where="in_RP_IRE(r,p)")
    # --- OPTION FSCK <= FLO_SUM;
    db.tmp("t_fsck", "select distinct r, p, cg, c, cg2 from FLO_SUM")
    # --- FLO_SUM(RTP(R,V,P),COM,C,COM,S)$((NOT FLO_SUM(RTP,COM,C,COM,S))$RPCS_VAR(R,P,C,S)$FS_EMCB(R,P,COM,C)) = VDA_EMCB(R,V,C,COM);
    #     The same as put(..., zero="eps") of the candidates without a FLO_SUM (absent, or on record with no value: NOT EPS
    #     is false, so a FLO_SUM of 0 stays), in fewer and cheaper statements (on 20.7 M rows,
    #     5.4 -> 3.2 s): a candidate can be on record only if FLO_SUM has its (r, p, c, c2) at all (FSCK, just above), so
    #     FS_EMCB is split first: the candidates of the other pairs go in without a look at FLO_SUM; for these pairs, the
    #     keys on record with no value are deleted (as put deletes the old records of the keys it assigns), then the
    #     candidates not on record go in.
    cand = """from RTP k join {e} e on e.r=k.r and e.p=k.p join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=e.c2
              join VDA_EMCB m on m.r=k.r and m.y=k.y and m.c=e.c2 and m.c2=e.c where m.value is not null"""
    sel = "select k.r, k.y, k.p, e.c as cg, e.c2 as c, e.c as cg2, v.s, m.value"
    key = "f.r=k.r and f.y=k.y and f.p=k.p and f.cg=e.c and f.c=e.c2 and f.cg2=e.c and f.s=v.s"
    db.x("""create or replace temp table t_e1 as select e.* from FS_EMCB e
            where exists(select 1 from t_fsck q where q.r=e.r and q.p=e.p and q.cg=e.c and q.c=e.c2 and q.cg2=e.c)""")
    db.x("create or replace temp table t_e0 as select * from FS_EMCB except all select * from t_e1")
    db.x(f"delete from FLO_SUM f where f.value is null and exists(select 1 {cand.format(e='t_e1')} and {key})")
    db.x(f'insert into "FLO_SUM" {sel} {cand.format(e="t_e0")}')
    db.x(f'insert into "FLO_SUM" {sel} {cand.format(e="t_e1")} and not exists(select 1 from FLO_SUM f where {key})')
    # --- VDA_EMCB(R,ALLYEAR,C,COM) = 0;
    db.zap("VDA_EMCB", "in_REG(r)")
    # --- CG_GRP(R,P,C,COM)$FSCK(R,P,C,COM,C) = YES;  CG_GRP(FS_EMCB) = YES;           (r,p,emission,source)
    db.tmp("t_cg", """select r, p, cg as c, c as c2 from t_fsck where cg = cg2 and in_COM(cg) and in_REG(r)
                      union select r, p, c, c2 from FS_EMCB""")
    # --- TRACKPG(RPC(RP_FLO,C)) $= SUM(CG_GRP(RPC,COM),1);  TRACKPG(RPC_PG) = NO; TRACKPG(RPC_FFUNC) = NO; TRACKPG(RPC_EMIS) = NO;
    #     LOOP(CG_GRP(R,P,C,COM)$RPC_EMIS(R,P,COM),TRACKPG(R,P,C)=NO);
    db.tmp("t_pg", """select distinct g.r, g.p, g.c from t_cg g where in_RPC(g.r,g.p,g.c) and in_RP_FLO(g.r,g.p)
                      and not in_RPC_PG(g.r,g.p,g.c) and not in_RPC_FFUNC(g.r,g.p,g.c) and not in_RPC_EMIS(g.r,g.p,g.c)
                      and not exists(select 1 from t_cg h where h.r=g.r and h.p=g.p and h.c=g.c and in_RPC_EMIS(h.r,h.p,h.c2))""")
    # --- FS_EMIS(CG_GRP(TRACKPG(R,P,C),COM),C) = YES;  OPTION FS_EMIT < FS_EMIS, TRACKPC < FS_EMIS; TRACKPG(TRACKPC) = NO;
    #     (FS_EMIS holds those of pp_reduce.red, REDUCE not NO; FS_EMIT(R,P,COM,COM_GRP,C) < FS_EMIS(R,P,COM_GRP,C,COM))
    db.add("FS_EMIS", """select g.r, g.p, g.c as cg, g.c2 as c, g.c as c2 from t_cg g join t_pg k on k.r=g.r and k.p=g.p and k.c=g.c""")
    db.assign("FS_EMIT", "select distinct r, p, c2 as c, cg, c as c2 from FS_EMIS")
    db.x("delete from t_pg k where exists(select 1 from FS_EMIT e where e.r=k.r and e.p=k.p and e.c2=k.c)")
    # --- OPTION CLEAR=CG_GRP, CLEAR=TRACKPC, CLEAR=FS_EMIS, CLEAR=FS_EMCB, CLEAR=FSCK;
    db.clear("FS_EMIS", "FS_EMCB")

    # ---- ACT_EFF: which group or commodity each efficiency applies to
    # --- TRACKPC(RPC_ACE(RPC)) = YES;  TRACKPC(RPC_SPG(RP,C))$RPC_ACE(RP,%PGPRIM%) = YES;
    db.tmp("t_pc", """select r, p, cg as c from RPC_ACE where in_RPC(r,p,cg) union
                      select g.r, g.p, g.c from RPC_SPG g where in_RP(g.r,g.p) and in_RPC_ACE(g.r,g.p,'ACT')""")
    # --- RXX(RPC_ACE) = YES; RXX(TRACKPC) = NO;
    #     RPG_ACE(RXX(R,P,CG),IO)$(SUM(TOP(R,P,C,IO)$COM_GMAP(R,CG,C),1)$(NOT RP_INOUT(R,P,IO))) = YES;
    db.add("RPG_ACE", """select distinct a.r, a.p, a.cg, t.io from RPC_ACE a join TOP t on t.r=a.r and t.p=a.p
                         where not exists(select 1 from t_pc k where k.r=a.r and k.p=a.p and k.c=a.cg)
                           and in_COM_GMAP(a.r,a.cg,t.c) and not in_RP_INOUT(a.r,a.p,t.io)""")
    # --- LOOP(TRACKPC(RPC_PG(R,P,C)), TRACKP(R,P) = YES);
    db.tmp("t_p", "select distinct r, p from t_pc where in_RPC_PG(r,p,c)")
    # --- LOOP(RPG_ACE(TRACKP(R,P),CG,IO)$(NOT SUM(TOP(R,P,C,IO)$(COM_GMAP(R,CG,C)*(NOT RPC_SPG(R,P,C))),1)),RPG_PACE(R,P,CG) = YES);
    db.add("RPG_PACE", """select distinct a.r, a.p, a.cg from RPG_ACE a join t_p k on k.r=a.r and k.p=a.p
                          where not exists(select 1 from TOP t where t.r=a.r and t.p=a.p and t.io=a.io
                                           and in_COM_GMAP(a.r,a.cg,t.c) and not in_RPC_SPG(a.r,a.p,t.c))""")
    # --- LOOP(RPG_PACE(R,P,CG), TRACKP(R,P) = NO);  LOOP(RPG_ACE(R,P,CG,IO),TRACKPC(R,P,C)$COM_GMAP(R,CG,C) = NO);
    db.x("delete from t_p k where exists(select 1 from RPG_PACE g where g.r=k.r and g.p=k.p)")
    db.x("delete from t_pc k where exists(select 1 from RPG_ACE g where g.r=k.r and g.p=k.p and in_COM_GMAP(g.r,g.cg,k.c))")
    # --- RXX(PRC_SPG(R,P,CG))$(TRACKP(R,P)+SUM(TRACKPC(RPC_SPG(R,P,C)),YES)) = YES;  RPG_PACE(RXX(TRACKP,CG)) = YES;
    db.tmp("t_x", """select g.r, g.p, g.cg from PRC_SPG g where in_REG(g.r)
                     and (exists(select 1 from t_p k where k.r=g.r and k.p=g.p)
                          or exists(select 1 from t_pc k where k.r=g.r and k.p=g.p and in_RPC_SPG(k.r,k.p,k.c)))""")
    db.add("RPG_PACE", "select x.r, x.p, x.cg from t_x x join t_p k on k.r=x.r and k.p=x.p")
    # --- TRACKPC(RPC_SPG) = NO;
    db.x("delete from t_pc where in_RPC_SPG(r,p,c)")
    # --- ACT_EFF(RTP(R,V,P),CG,S)$RXX(R,P,CG) $= ACT_EFF(RTP,%PGPRIM%,S);  ACT_EFF(R,LL,P,%PGPRIM%,S) = 0;
    db.put("ACT_EFF", """select a.r, a.y, a.p, x.cg, a.s, a.value from ACT_EFF a join t_x x on x.r=a.r and x.p=a.p
                         where a.cg='ACT' and in_RTP(a.r,a.y,a.p)""", zero="eps")
    db.zap("ACT_EFF", "cg='ACT' and in_REG(r)")
    # --- LOOP((TOP(TRACKPC(R,P,C),IO),COM_TMAP(R,COM_TYPE,C))$(NOT RP_INOUT(R,P,IO)),RXX(R,P,COM_TYPE) = YES);
    db.x("""insert into t_x select distinct k.r, k.p, m.cg from t_pc k join TOP t on t.r=k.r and t.p=k.p and t.c=k.c
            join COM_TMAP m on m.r=k.r and m.c=k.c where not in_RP_INOUT(k.r,k.p,t.io)
              and not exists(select 1 from t_x z where z.r=k.r and z.p=k.p and z.cg=m.cg)""")
    # --- RPG_ACE(RXX(R,P,CG),IO--1)$RP_INOUT(R,P,IO) = YES;
    db.add("RPG_ACE", """select x.r, x.p, x.cg, case when i.io='IN' then 'OUT' else 'IN' end as io
                         from t_x x join RP_INOUT i on i.r=x.r and i.p=x.p""")
    # --- LOOP(IO,ACT_EFF(RTP(R,V,P),CG,ANNUAL)$((ACT_EFF(RTP,CG,ANNUAL)=0)$RPG_ACE(R,P,CG,IO)) = 1);
    #     (ACT_EFF(..) = 0: absent or zero; a left join on its keys, which are unique)
    db.put("ACT_EFF", """select distinct k.r, k.y, k.p, g.cg, 'ANNUAL' as s, 1 as value from RTP k join RPG_ACE g on g.r=k.r and g.p=k.p
                         left join ACT_EFF a on a.r=k.r and a.y=k.y and a.p=k.p and a.cg=g.cg and a.s='ANNUAL'
                         where coalesce(a.value, 0) = 0""")

    # ---- pp_actef.vda LVL
    # --- CG_GRP(RPC_ACE(RPC(R,P,C)),C) = YES;
    db.tmp("t_cg", "select r, p, cg, cg as c from RPC_ACE where in_RPC(r,p,cg)")
    # --- OPTION KEEP_FLOF<RPG_1ACE, CLEAR=RPG_1ACE;
    db.assign("KEEP_FLOF", "select distinct r, p, c from RPG_1ACE")
    db.clear("RPG_1ACE")
    # --- LOOP(RPG_ACE(RP_PGACT(R,P),CG,IO)$(SUM(TOP(R,P,C,IO)$COM_GMAP(R,CG,C),1) LE 1),
    #       IF(NOT RPG_PACE(R,P,CG)+RP_PL(R,P,'FX'),RP_GRP(R,P,CG)=YES; RPG_1ACE(RP_GRP(R,P,CG),C)$(TOP(R,P,C,IO)$COM_GMAP(R,CG,C)) = YES));
    db.tmp("t_grp", """select distinct a.r, a.p, a.cg, a.io from RPG_ACE a where in_RP_PGACT(a.r,a.p)
                       and (select count(*) from TOP t where t.r=a.r and t.p=a.p and t.io=a.io and in_COM_GMAP(a.r,a.cg,t.c)) <= 1
                       and not (in_RPG_PACE(a.r,a.p,a.cg) or in_RP_PL(a.r,a.p,'FX'))""")
    db.add("RPG_1ACE", """select g.r, g.p, g.cg, t.c from t_grp g join TOP t on t.r=g.r and t.p=g.p and t.io=g.io
                          where in_COM_GMAP(g.r,g.cg,t.c)""")
    # --- ACT_EFF(R,LL,P,C,S)$((RPC_PG(R,P,C)+KEEP_FLOF(R,P,C))$(ACT_EFF(R,LL,P,C,S)=0)$ACT_EFF(R,LL,P,C,S))=0;
    db.zap("ACT_EFF", "value = 0 and in_REG(r) and (in_RPC_PG(r,p,cg) or in_KEEP_FLOF(r,p,cg))")
    # --- LOOP(RPG_ACE(RPC_SPG(R,P,C),IO),ACT_EFF(RTP(R,V,P),C,S)$ACT_EFF(RTP,C,S)=SQRT(ABS(ACT_EFF(RTP,C,S))));
    if db.q1("select count(*) from RPG_ACE where in_RPC_SPG(r,p,cg)"):
        unsupported(db, "ACT_EFF on a single shadow-group commodity used as a group (pp_actef.vda)")
    # --- CG_GRP(RPG_1ACE) = YES;  RPG_ACE(RP_GRP,IO) = NO;
    db.x("insert into t_cg select r, p, cg, c from RPG_1ACE")
    db.remove("RPG_ACE", where="exists(select 1 from t_grp g where g.r=RPG_ACE.r and g.p=RPG_ACE.p and g.cg=RPG_ACE.cg)")
    # --- VDA_FLOP(R,'0',P,CG,.)$STOAL(R,S)$=ACT_EFF(R,LL,P,CG,S); OPTION RPC_ACE<VDA_FLOP, CLEAR=VDA_FLOP;     given below ANNUAL
    db.assign("RPC_ACE", "select distinct r, p, cg from ACT_EFF where v_STOAL(r,s) <> 0")
    # --- UNCD7('1',CG_GRP(RPC_ACE(R,P,CG),C),TSL,'ANNUAL')$TS_GROUP(R,TSL,S)$=RPCS_VAR(R,P,C,S);
    #     UNCD7('2',RPG_ACE(RPC_ACE(R,P,CG),IO),TSL,'ANNUAL')$TS_GROUP(R,TSL,S)$=RPS_S1(R,P,S);  CG_GRP(RPC_ACE,C)=NO;
    db.tmp("t_lv", """select distinct g.r, g.p, g.cg, t.tsl from t_cg g join RPCS_VAR v on v.r=g.r and v.p=g.p and v.c=g.c
                      join TS_GROUP t on t.r=v.r and t.s=v.s where in_RPC_ACE(g.r,g.p,g.cg)
                      union
                      select distinct g.r, g.p, g.cg, t.tsl from RPG_ACE g join RPS_S1 v on v.r=g.r and v.p=g.p
                      join TS_GROUP t on t.r=v.r and t.s=v.s where in_RPC_ACE(g.r,g.p,g.cg)""")
    # --- IF(CARD(NORTS),LOOP((MIYR_1(T),UNCD7(J,R,P,CG,ITEM,TS,TS)),ACT_EFF(RTP(R,V,P),CG,S)$(NORTS(R,V,S)+NORTS(R,T,S)$PASTMILE(V))=0));
    #     (UNCD7(..,TS,TS): the level ANNUAL, the label of S+STOA(S))
    if db.card("NORTS"):
        db.zap("ACT_EFF", """in_RTP(r, y, p) and exists(select 1 from t_lv l where l.r=ACT_EFF.r and l.p=ACT_EFF.p and l.cg=ACT_EFF.cg and l.tsl='ANNUAL')
                             and v_NORTS(r, y, s) + (case when in_PASTMILE(y) then v_NORTS(r, (select y from MIYR_1), s) else 0 end) <> 0""")
    db.x("delete from t_cg where in_RPC_ACE(r,p,cg)")
    # --- OPTION CLEAR=RPC_ACE; LOOP(RPG_ACE(R,P,CG,IO),RPC_ACE(R,P,C)$(TOP(R,P,C,IO)$COM_GMAP(R,CG,C)) = YES); RPC_ACE(KEEP_FLOF) = NO;
    db.assign("RPC_ACE", """select distinct g.r, g.p, t.c as cg from RPG_ACE g join TOP t on t.r=g.r and t.p=g.p and t.io=g.io
                            where in_COM_GMAP(g.r,g.cg,t.c) and not in_KEEP_FLOF(g.r,g.p,t.c)""")
    # --- LOOP(UNCD7(J,R,P,CG,ITEM,TSL,STL), MY_TS(S) = TS_GROUP(R,TSL,S);
    #       LOOP(RTP(R,V,P), ACT_EFF(R,V,P,CG,MY_TS)$(NOT TS_ARRAY(MY_TS)) = aggregate ...
    if db.q1("select count(*) from t_lv"):
        T = trees(db)
        want = {}
        for r, p, cg, s in db.q("select distinct l.r, l.p, l.cg, t.s from t_lv l join TS_GROUP t on t.r=l.r and t.tsl=l.tsl"):
            want.setdefault((r, p, cg), []).append(s)
        key, series = read_series(db, "ACT_EFF", "in_RTP(a.r,a.y,a.p) and exists(select 1 from t_lv l where l.r=a.r and l.p=a.p and l.cg=a.cg)")
        out = []
        ix = {c: key.index(c) for c in key}
        for k, arr in series.items():
            for ts in want[(k[ix["r"]], k[ix["p"]], k[ix["cg"]])]:
                if ts not in arr:
                    v = aggregate(T[k[ix["r"]]], arr, ts)
                    if v is not None:
                        arr[ts] = v
                        out.append(k + (ts, _out(v)))
        _write(db, "ACT_EFF", key, out)
    # --- FSCKS(CG_GRP(R,P,CG,C),CG,S)$RPCS_VAR(R,P,C,S) = YES; OPTION FFCKS <= FSCKS;
    db.tmp("t_ff", "select distinct g.r, g.p, g.cg, v.s from t_cg g join RPCS_VAR v on v.r=g.r and v.p=g.p and v.c=g.c")
    # --- ACT_EFF(RTP(R,V,P),CG,S+STOA(S))$(RPS_S1(R,P,S)$STOA(S)$ACT_EFF(RTP,CG,S)) = 0;
    db.zap("ACT_EFF", """s='ANNUAL' and in_RTP(r,y,p) and exists(select 1 from ACT_EFF b where b.r=ACT_EFF.r and b.y=ACT_EFF.y
                         and b.p=ACT_EFF.p and b.cg=ACT_EFF.cg and b.s <> 'ANNUAL' and in_RPS_S1(b.r,b.p,b.s))""")
    # --- ACT_EFF(RTP(R,V,P),CG,S)$(NOT ACT_EFF(RTP,CG,S)) $= SUM(FFCKS(R,P,CG,CG,S),ACT_EFF(R,V,P,CG,'ANNUAL'));
    #     (no record at all: then its value is 0 too; one anti-join rather than a lookup and a test per row)
    db.put("ACT_EFF", """select a.r, a.y, a.p, a.cg, f.s, a.value from ACT_EFF a join t_ff f on f.r=a.r and f.p=a.p and f.cg=a.cg
                         where a.s='ANNUAL' and in_RTP(a.r,a.y,a.p)
                           and not exists(select 1 from ACT_EFF b where b.r=a.r and b.y=a.y and b.p=a.p and b.cg=a.cg and b.s=f.s)""", zero="eps")

    # ---- back in ppm_ext.vda
    # --- * Catch shape indexes for shadow group
    #     IF(CARD(FLO_FUNCX),
    #     FLO_FUNCX(R,V,P,CG1,ACTCG(CG))$PRC_SPG(R,P,CG1) $= FLO_FUNCX(R,V,P,CG,CG);
    #     FLO_FUNCX(R,V,P,CG,COM)$(RPC_PG(R,P,COM)$RP_GRP(R,P,CG)) $= FLO_FUNCX(R,V,P,CG,%PGPRIM%);
    #     FLO_FUNCX(R,V,P,CG,ACTCG)$(ACTCG(CG)+RP_GRP(R,P,CG)) = 0;
    #     FLO_FUNCX(R,V,P,CG,CG2)$RP_PG(R,P,CG) $= FLO_FUNCX(R,V,P,%PGPRIM%,CG2));
    #     (RP_GRP: the groups pp_actef.vda LVL marked just above, t_grp)
    if db.card("FLO_FUNCX"):
        db.tmp("t_rg", "select distinct r, p, cg from t_grp union select r, p, cg from RP_GRP")
        db.put("FLO_FUNCX", """select f.r, f.y, f.p, g.cg, 'ACT' as cg2, f.value from FLO_FUNCX f join PRC_SPG g on g.r=f.r and g.p=f.p
                              where f.cg='ACT' and f.cg2='ACT' and in_MODLYEAR(f.y)""", zero="eps")
        db.put("FLO_FUNCX", """select f.r, f.y, f.p, f.cg, c.c as cg2, f.value from FLO_FUNCX f
                              join t_rg g on g.r=f.r and g.p=f.p and g.cg=f.cg join RPC_PG c on c.r=f.r and c.p=f.p
                              where f.cg2='ACT' and in_MODLYEAR(f.y)""", zero="eps")
        db.zap("FLO_FUNCX", "in_MODLYEAR(y) and cg2='ACT' and (cg='ACT' or exists(select 1 from t_rg g where g.r=FLO_FUNCX.r and g.p=FLO_FUNCX.p and g.cg=FLO_FUNCX.cg))")
        db.put("FLO_FUNCX", """select f.r, f.y, f.p, g.cg, f.cg2, f.value from FLO_FUNCX f join RP_PG g on g.r=f.r and g.p=f.p
                              where f.cg='ACT' and in_MODLYEAR(f.y)""", zero="eps")
    # --- * Ensure that ACT_EFF modeled flows are not reduced:
    #     OPTION TRACKP < RPG_ACE;
    #     LOOP(RPCG_PTRAN(TRACKP(R,P),C,COM,CG,CG2)$(RPC_ACE(R,P,C)+RPC_ACE(R,P,COM)),RPCC_FFUNC(R,P,CG,CG2) = NO);
    #     RPCG_PTRAN(TRACKP,C,COM,CG,CG2)$(NOT RPCC_FFUNC(TRACKP,CG,CG2)) = NO;
    #     (RPCG_PTRAN and NO_ACT are empty unless REDUCE is YES)
    db.tmp("t_ap", "select distinct r, p from RPG_ACE")
    if db.card("RPCG_PTRAN"):
        db.remove("RPCC_FFUNC", select="""select g.r, g.p, g.cg, g.cg2 from RPCG_PTRAN g join t_ap k on k.r=g.r and k.p=g.p
                                          where in_RPC_ACE(g.r,g.p,g.c) or in_RPC_ACE(g.r,g.p,g.c2)""")
        db.remove("RPCG_PTRAN", where="""exists(select 1 from t_ap k where k.r=RPCG_PTRAN.r and k.p=RPCG_PTRAN.p)
                                         and not in_RPCC_FFUNC(r,p,cg,cg2)""")
    # --- RPC_FFUNC(RPC_ACE(R,P,C)) = NO;  RPC_NOFLO(RPC_ACE(R,P,C)) = NO;
    db.remove("RPC_FFUNC", where="in_RPC_ACE(r,p,c)")
    db.remove("RPC_NOFLO", where="in_RPC_ACE(r,p,c)")
    # --- TRACKP(RP_PGFLO) = NO;  PRC_ACT(NO_ACT(TRACKP)) = YES;  NO_ACT(TRACKP) = NO;  OPTION CLEAR=TRACKP;
    if db.card("NO_ACT"):
        db.x("delete from t_ap where in_RP_PGFLO(r,p)")
        db.add("PRC_ACT", "select k.r, k.p from t_ap k where in_NO_ACT(k.r,k.p)")
        db.remove("NO_ACT", select="select r, p from t_ap")
    # --- OPTION TRACKPC < RPG_1ACE; RPC_NOFLO(TRACKPC) = NO;
    db.remove("RPC_NOFLO", where="exists(select 1 from RPG_1ACE g where g.r=RPC_NOFLO.r and g.p=RPC_NOFLO.p and g.c=RPC_NOFLO.c)")
    # --- TRACKPG(RPC_ACE) = NO; TRACKPG(TRACKPC) = NO;  RPC_EMIS(TRACKPG)=YES; RPCC_FFUNC(TRACKPG(RP,C),C) = YES;
    db.x("""delete from t_pg k where in_RPC_ACE(k.r,k.p,k.c)
            or exists(select 1 from RPG_1ACE g where g.r=k.r and g.p=k.p and g.c=k.c)""")
    db.add("RPC_EMIS", "select r, p, c as cg from t_pg")
    db.add("RPCC_FFUNC", "select r, p, c as cg, c as cg2 from t_pg where in_RP(r,p)")
    # --- $IF NOT %REDUCE%==YES OPTION CLEAR=TRACKPC;
    #     OPTION KEEP_FLOF < RPC_FFUNC; TRACKPC(RP_SGS,C) = NO;
    #     RPC_FFUNC(TRACKPC)$(NOT RPC_ACE(TRACKPC)) = YES;
    #     (TRACKPC: the commodities of RPG_1ACE that are not in KEEP_FLOF; with REDUCE YES the single flows of an
    #      ACT_EFF group are expressed by the activity)
    db.tmp("t_keep", "select r, p, c from KEEP_FLOF")              # (KEEP_FLOF of pp_actef.vda, TRACKPC(KEEP_FLOF) = NO)
    db.assign("KEEP_FLOF", "select r, p, c from RPC_FFUNC")
    if db.ctl.get("REDUCE") == "YES":
        db.add("RPC_FFUNC", """select distinct g.r, g.p, g.c from RPG_1ACE g
                               where not exists(select 1 from t_keep k where k.r=g.r and k.p=g.p and k.c=g.c)
                                 and not in_RP_SGS(g.r,g.p) and not in_RPC_ACE(g.r,g.p,g.c)""")
    # --- RPG_AFCX(RPC_IRE(RP,C,IE('EXP')))$(RPC_IRE(RP,C,'IMP')+(NOT RP_AIRE(RP,IE)))=YES;
    db.add("RPG_AFCX", """select r, p, c, ie from RPC_IRE where ie='EXP' and in_RP(r,p)
                          and (in_RPC_IRE(r,p,c,'IMP') or not in_RP_AIRE(r,p,'EXP'))""")
    afc(db)
    # --- $IF NOT %RTS%==S $BATINCLUDE dynslite.vda POSTLEV
    dynslite.postlev(db)
