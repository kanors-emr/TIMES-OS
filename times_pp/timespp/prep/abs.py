# SPDX-License-Identifier: GPL-3.0-or-later
"""The ancillary balancing services extension of TIMES (run-file switch ABS=YES): the reserve commodities, their
demands and their provision by processes.  TIMES v4.9.8 files: initmty.abs (declarations, read by load.py),
init_ext.abs, prep_ext.abs, coef_ext.abs, mod_vars.abs, equ_ext.abs; the equations are in times_eq (abs.jl).

  init_ext(db)          init_ext.abs, after init_ext.vda
  prep_ext(db, interp)  prep_ext.abs, after prep_ext.vda
  coef_ext(db)          coef_ext.abs, after coef_ext.vda
  mod_vars(db)          mod_vars.abs (before eqmain.mod)
  equ_ext(db)           equ_ext.abs, after equ_ext.vda

Each step runs only when the switch is on (db.ctl['ABS']).
"""
from ..engine import DB


def on(db: DB):
    return bool(db.ctl.get("ABS"))


def init_ext(db: DB):
    """init_ext.abs"""
    if not on(db):
        return
    # --- SET BS_RVT(R,YEAR,T);
    if "BS_RVT" not in db.sym:
        db.declare("BS_RVT", "set", ["R", "YEAR", "T"])
    # --- OPTION BS_BSC<BS_RMAX, TRACKP<BS_BSC; Z=CARD(TRACKP);
    db.assign("BS_BSC", "select distinct r, p, c from BS_RMAX")
    db.tmp("t_bs_trackp", "select distinct r, p from BS_BSC")
    z = db.q1("select count(*) from t_bs_trackp")
    # --- BS_RTYPE(R,C)$BS_RTYPE(R,C) = SIGN(BS_RTYPE(R,C))*ROUND(MIN(5,ABS(BS_RTYPE(R,C))));
    #     (GAMS ROUND: half away from zero)
    db.put("BS_RTYPE", """select r, c, sign(value) * round(least(5, abs(value))) as value from BS_RTYPE""")
    # --- Remove reserve commodities from topology
    # --- LOOP(TRACKP(R,P)$Z,RP_UPR(R,P,'FX')=Z; Z=0);
    #     (the first process of TRACKP in GAMS order, if there is one)
    if z:
        db.add("RP_UPR", """select t.r, t.p, 'FX' as l from t_bs_trackp t
                            order by (select u.ord from __uel u where u.label=t.r), (select u.ord from __uel u where u.label=t.p)
                            limit 1""")
    # --- TRACKP(R,P)$=SUM((C,BD)$BS_STIME(R,P,C,BD),1);
    db.x("""insert into t_bs_trackp select distinct r, p from BS_STIME s where l in ('LO','UP','FX')
            and not exists(select 1 from t_bs_trackp t where t.r=s.r and t.p=s.p)""")
    # --- TOP(TRACKP(R,P),C,IO)$BS_RTYPE(R,C) = NO;
    db.remove("TOP", where="""exists(select 1 from t_bs_trackp t where t.r=TOP.r and t.p=TOP.p) and in_BS_RTYPE(r,c)""")
    # --- NRG_TMAP(R,NRG_TYPE,C)$BS_RTYPE(R,C) = DIAG(NRG_TYPE,'RATE');
    db.remove("NRG_TMAP", where="in_BS_RTYPE(r,c)")
    db.add("NRG_TMAP", "select b.r, n.u as nrg_type, b.c from BS_RTYPE b, NRG_TYPE n where n.u = 'RATE'")
    # --- OPTION CLEAR=TRACKP;
    db.x("drop table if exists t_bs_trackp")
    # --- Make A-sets
    # --- BS_ABD(R,C,'LO')$(BS_RTYPE(R,C)<0) $=BS_RTYPE(R,C);  BS_ABD(R,C,'UP')$(BS_RTYPE(R,C)>0) $=BS_RTYPE(R,C);
    db.add("BS_ABD", "select r, c, case when value < 0 then 'LO' else 'UP' end as l from BS_RTYPE where value <> 0")
    # --- BS_ANEG(R,C) $= BS_ABD(R,C,'LO');  BS_APOS(R,C) $= BS_ABD(R,C,'UP');
    db.add("BS_ANEG", "select r, c from BS_ABD where l = 'LO'")
    db.add("BS_APOS", "select r, c from BS_ABD where l = 'UP'")
    # --- Remove invalid values: X(..,C,..)$(NOT BS_RTYPE(R,C))=0 for BS_DEMDET, BS_OMEGA, BS_DELTA, BS_LAMBDA, BS_DETWT,
    #     BS_SIGMA, BS_RMAX, BS_STIME
    for n in ("BS_DEMDET", "BS_OMEGA", "BS_DELTA", "BS_LAMBDA", "BS_DETWT", "BS_SIGMA", "BS_RMAX", "BS_STIME"):
        db.zap(n, "not in_BS_RTYPE(r, c)")


def prep_ext(db: DB, interp):
    """prep_ext.abs (preppm.mod, main_ext.mod prep_ext: after prep_ext.vda)"""
    if not on(db):
        return
    # --- Add reserve commodities to RC
    # --- RC(R,C) $= BS_RTYPE(R,C);
    db.add("RC", "select r, c from BS_RTYPE")
    # --- LOOP((RP,ITEM)$GR_GENMAP(RP,ITEM),BS_K(ITEM)=YES);
    db.add("BS_K", "select distinct g.u from GR_GENMAP g where in_RP(g.r, g.p)")
    # --- LOOP((R,T,C,P,BD)$BS_SHARE(R,T,C,P,BD),BS_K(P)=YES);
    #     (the loop runs over P: a group label of BS_SHARE becomes a source only when it is also a process)
    db.add("BS_K", "select distinct u from BS_SHARE where in_MILESTONYR(y) and in_PRC(u) and l in ('LO','UP','FX')")
    # --- Bulk processing
    # --- OPTION BS_RTCS < BS_DEMDET;
    db.clear("BS_RTCS")
    db.put("BS_RTCS", "select rsp, r, y, c, s, value from BS_DEMDET", zero="eps")
    # --- BS_RTCS('OMEGA',R,YEAR,C,S) $= BS_OMEGA(R,YEAR,C,S);  BS_RTCS('DELTA',R,YEAR,C,S) $= BS_DELTA(R,YEAR,C,S);
    db.put("BS_RTCS", "select 'OMEGA' as rsp, r, y, c, s, value from BS_OMEGA", zero="eps")
    db.put("BS_RTCS", "select 'DELTA' as rsp, r, y, c, s, value from BS_DELTA", zero="eps")
    # --- Interpolation/extrapolation
    F = interp.fillparm
    # --- $ BATINCLUDE fillparm BS_LAMBDA R C ",'0','0','0','0','0'" T YES '>=0'
    F(db, "BS_LAMBDA", "T", None)
    # --- $ BATINCLUDE fillparm BS_DETWT  R C ",'0','0','0','0','0'" T YES '>=0'
    F(db, "BS_DETWT", "T", None)
    # --- $ BATINCLUDE fillparm BS_SIGMA  R 'C,BS_K,S' ",'0','0','0'" T YES >=0
    F(db, "BS_SIGMA", "T", None)
    # --- $ BATINCLUDE fillparm BS_SHARE  R 'C,BS_K,BD' ",'0','0','0'" T YES >=0
    F(db, "BS_SHARE", "T", None)
    # --- $ BATINCLUDE fillparm BS_RTCS 'RSP,R' 'C,S' ",'0','0','0'" T YES >=0
    F(db, "BS_RTCS", "T", None)
    # --- $ BATINCLUDE fillparm BS_MAINT  R 'P,S' ",'0','0','0','0'" V 'RTP(R,V,P)' >=0
    F(db, "BS_MAINT", "V", ("RTP", ("r", "p")))
    # --- $ BATINCLUDE fillparm BS_RMAX   R 'P,C,S' ",'0','0','0'" V 'RTP(R,V,P)' >=0
    F(db, "BS_RMAX", "V", ("RTP", ("r", "p")))
    # --- $ BATINCLUDE prepparm BS_BNDPRS R 'P,C,S,BD' ",'0'" T 'RTP(R,T,P)' 1
    interp.prepparm(db, "BS_BNDPRS", "T", ("RTP", ("r", "p")), 1)
    # --- Intermediate QA clean-up
    # --- BS_RTCS(RSP('OMEGA'),R,T,C,S)$BS_RTCS(RSP,R,T,C,S) = ROUND(BS_RTCS(RSP,R,T,C,S));
    db.put("BS_RTCS", """select rsp, r, y, c, s, case when value >= 0 then floor(value + 0.5) else -floor(-value + 0.5) end as value
                         from BS_RTCS where rsp = 'OMEGA' and in_MILESTONYR(y)""")
    # --- BS_SIGMA(R,T,C,BS_K,S)$(BS_LAMBDA(R,T,C)=0)=0;
    db.zap("BS_SIGMA", "in_MILESTONYR(y) and in_BS_K(u) and v_BS_LAMBDA(r,y,c) = 0")
    # --- BS_RMAX(R,LL--ORD(LL),P,C,S+STOA(S)) $= (BS_RMAX(R,LL,P,C,S)>0);
    #     (a flag 1 on year 0, ANNUAL, for every process and reserve with a positive maximum)
    db.put("BS_RMAX", "select distinct r, '0' as y, p, c, 'ANNUAL' as s, 1 as value from BS_RMAX where value > 0", zero="skip")
    # --- BS_RMAX(R,LL,P,C,S)$(NOT BS_RMAX(R,'0',P,C,'ANNUAL'))=0;
    db.x("""delete from BS_RMAX a where not exists(select 1 from BS_RMAX b where b.r=a.r and b.y='0' and b.p=a.p and b.c=a.c
                                                       and b.s='ANNUAL')""")
    # --- BS_BNDPRS(R,T,P,C,S,BD)$((BS_LAMBDA(R,T,C)=0)$BS_BNDPRS(R,T,P,C,S,BD))=0;
    db.zap("BS_BNDPRS", "in_MILESTONYR(y) and l in ('LO','UP','FX') and v_BS_LAMBDA(r,y,c) = 0")
    # --- OPTION BS_BSC < BS_RMAX, CLEAR=BS_OMEGA;
    db.assign("BS_BSC", "select distinct r, p, c from BS_RMAX")
    db.clear("BS_OMEGA")


def mod_vars(db: DB):
    """mod_vars.abs (maindrv.mod, after mod_vars.mod; before eqmain.mod)"""
    if not on(db):
        return
    # --- Set minimum exogenous demand
    # --- BS_CAPACT(R)$(NOT BS_CAPACT(R)) = MAX(0,SMAX(RP_STD(R,P)$GR_GENMAP(R,P,'SI'),PRC_CAPACT(R,P)));
    # --- BS_CAPACT(R)$(NOT BS_CAPACT(R)) = MAX(0,SMAX(BS_SUPP(RP_STD(R,P)),PRC_CAPACT(R,P)));
    for cond in ("v_GR_GENMAP(k.r,k.p,'SI') <> 0", "in_BS_SUPP(k.r,k.p)"):
        db.put("BS_CAPACT", f"""select g.r, greatest(0, coalesce((select max(v_PRC_CAPACT(k.r,k.p)) from RP_STD k
                                                                  where k.r=g.r and {cond}), 0)) as value
                                from REG g where not in_BS_CAPACT(g.r)""")
    # --- %VAR%_COMLV.LO('DET',RTCS_VARC(R,T,C,S)%SOW%) $= BS_RTCS('EXOGEN',R,T,C,S)*BS_CAPACT(R);
    db.x('create table if not exists "B_VAR_COMLV" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x("""insert into "B_VAR_COMLV" select 'DET', k.r, k.y, k.c, k.s, b.value * v_BS_CAPACT(k.r), 'inf'::double
            from RTCS_VARC k join BS_RTCS b on b.rsp='EXOGEN' and b.r=k.r and b.y=k.y and b.c=k.c and b.s=k.s
            where b.value * v_BS_CAPACT(k.r) <> 0""")
    db.bounds.add("VAR_COMLV")
    # --- RPT_OPT('RATE','1')$(RPT_OPT('RATE','1')<=0)=SMAX(R,BS_CAPACT(R))$(RPT_OPT('RATE','1')=0);
    i, j = db.cols("RPT_OPT")
    rate = db.q1(f"select v_RPT_OPT('RATE','1')")
    if rate <= 0:
        z = db.q1("select coalesce(max(value), 0) from BS_CAPACT") if rate == 0 else 0
        db.zap("RPT_OPT", f"{i}='RATE' and {j}='1'")
        if z:
            db.put("RPT_OPT", f"select 'RATE' as {i}, '1' as {j}, {z} as value")
    # --- Set bounds on reserve flows
    # --- BS_BNDPRS(RTP,C,S,BDNEQ)$=BS_BNDPRS(RTP,C,S,'FX');
    db.put("BS_BNDPRS", """select b.r, b.y, b.p, b.c, b.s, x.l, b.value from BS_BNDPRS b, (select 'LO' as l union all select 'UP') x
                           where b.l = 'FX' and in_RTP(b.r,b.y,b.p)""", zero="eps")
    # --- BS_BNDPRS(RTP,C,S,'N')$SUM(BDNEQ$BS_BNDPRS(RTP,C,S,BDNEQ),1) = 1;
    db.put("BS_BNDPRS", """select distinct r, y, p, c, s, 'N' as l, 1 as value from BS_BNDPRS
                           where l in ('LO','UP') and in_RTP(r,y,p)""")
    # --- LOOP((L(BDUPX),BD)$(BDSIG(L)*BDSIG(BD)<0),
    #       %var%_bsprs.LO(r,t,t,p,c,s,l%SOW%)$(RTP(R,T,P)$BS_COMTS(R,C,S)) $= BS_BNDPRS(R,T,P,C,S,BD);
    #       %var%_bsprs.UP(r,t,t,p,c,s,l%SOW%)$(RTP(R,T,P)$BS_COMTS(R,C,S)) $= BS_BNDPRS(R,T,P,C,S,L));
    #     (L = UP, BD = LO: the bounds of the slack VAR_BSPRS(..,'UP') that EQ_BS26 ties to the provision)
    db.x('create table if not exists "B_VAR_BSPRS" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, d5 VARCHAR, d6 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x("""insert into "B_VAR_BSPRS"
            select r, y, y, p, c, s, 'UP',
                   coalesce(nullif(max(case when l='LO' then value end), 0), 0),
                   coalesce(max(case when l='UP' then value end), 'inf'::double)
            from BS_BNDPRS where l in ('LO','UP') and in_MILESTONYR(y) and in_RTP(r,y,p) and in_BS_COMTS(r,c,s)
            group by r, y, p, c, s""")
    db.bounds.add("VAR_BSPRS")


def _uo(col):
    """the GAMS order of a label column (the order of the universe)"""
    return f"(select u_.ord from __uel u_ where u_.label = {col})"


def coef_ext(db: DB):
    """coef_ext.abs (maindrv.mod, main_ext.mod coef_ext: after coef_ext.vda)"""
    if not on(db):
        return
    x = db.x
    # --- Get storage, end-use and supply processes
    # --- BS_BSC(RP,C)$(NOT PRC_CAP(RP))=NO;
    db.remove("BS_BSC", where="in_RP(r,p) and not in_PRC_CAP(r,p)")
    # --- OPTION TRACKP < BS_STIME, RP_PRC < COEF_AFUPS;
    db.tmp("t_bs_tp", "select distinct r, p from BS_STIME")
    db.assign("RP_PRC", "select distinct r, p from COEF_AFUPS")
    # --- RP_PRC(RP_PRC)=TRACKP(RP_PRC); OPTION TRACKP < BS_BSC;
    db.remove("RP_PRC", where="not exists(select 1 from t_bs_tp t where t.r=RP_PRC.r and t.p=RP_PRC.p)")
    db.tmp("t_bs_tp", "select distinct r, p from BS_BSC")
    # --- TRACKPC(RPC(R,P,C)) $= NRG_TMAP(R,'ELC',C);
    db.tmp("t_bs_tpc", "select r, p, c from RPC where in_NRG_TMAP(r,'ELC',c)")
    tpc = lambda r, p, c: f"exists(select 1 from t_bs_tpc q_ where q_.r={r} and q_.p={p} and q_.c={c})"
    tp = lambda r, p: f"exists(select 1 from t_bs_tp q_ where q_.r={r} and q_.p={p})"
    # --- Storage with inflow
    # --- BS_ENDP(RP_STG(RP))$SUM(TOP(TRACKPC(RPC_STG(RP,C)),'IN'),1)=YES;
    db.add("BS_ENDP", f"""select distinct t.r, t.p from TOP t where t.io='IN' and in_RP_STG(t.r,t.p) and {tpc('t.r','t.p','t.c')}
                          and in_RPC_STG(t.r,t.p,t.c)""")
    # --- Qualify as power storage
    # --- BS_STGP(RP_PRC(RP))$SUM(TOP(RPC_STG(TRACKPC(RP,C)),'OUT'),1)=YES;
    db.add("BS_STGP", f"""select distinct t.r, t.p from TOP t where t.io='OUT' and in_RP_PRC(t.r,t.p) and {tpc('t.r','t.p','t.c')}
                          and in_RPC_STG(t.r,t.p,t.c)""")
    # --- BS_STGP(RP_PRC(RP))$SUM(TOP(RPC_STG(RP,C),'OUT'),NOT TRACKPC(RP,C))=NO;
    db.remove("BS_STGP", where=f"""in_RP_PRC(r,p) and exists(select 1 from TOP t where t.r=BS_STGP.r and t.p=BS_STGP.p and t.io='OUT'
                                   and in_RPC_STG(t.r,t.p,t.c) and not {tpc('t.r','t.p','t.c')})""")
    # --- BS_STGP(RP_PRC(RP))$(((NOT BS_ENDP(RP))+TRACKP(RP))$PRC_SC(RP))=NO;
    db.remove("BS_STGP", where=f"in_RP_PRC(r,p) and v_PRC_SC(r,p) <> 0 and (not in_BS_ENDP(r,p) or {tp('BS_STGP.r','BS_STGP.p')})")
    # --- BS_STIME(BS_STGP(R,P),C,'UP')$BS_RTYPE(R,C)=SMAX(BD,BS_STIME(R,P,C,BD));
    #     (the maximum over LO, UP, FX, the absent ones as zero)
    db.tmp("t_bs_st", """select g.r, g.p, b.c, greatest(max(s.value), case when count(s.value) < 3 then 0 end) as value,
                                max(s.value) as mx
                         from BS_STGP g join BS_RTYPE b on b.r=g.r
                         left join BS_STIME s on s.r=g.r and s.p=g.p and s.c=b.c and s.l in ('LO','UP','FX')
                         group by g.r, g.p, b.c""")
    db.zap("BS_STIME", "l='UP' and in_BS_STGP(r,p) and in_BS_RTYPE(r,c)")
    db.put("BS_STIME", "select r, p, c, 'UP' as l, value from t_bs_st")
    #     (the maximum of EPS records, and 0 for the absent ones, is EPS: MAX(EPS,0) is EPS, a record)
    db.put("BS_STIME", "select r, p, c, 'UP' as l, 0.0 as value from t_bs_st where value = 0 and mx = 0", zero="eps")
    # --- BS_STIME(RP,C,BD)$((NOT BS_STGP(RP))$BS_STIME(RP,C,BD))=NO;
    db.zap("BS_STIME", "in_RP(r,p) and l in ('LO','UP','FX') and not in_BS_STGP(r,p)")
    # --- BS_BSC(BS_STGP,C)=NO;
    db.remove("BS_BSC", where="in_BS_STGP(r,p)")
    # --- Qualify as power supply
    # --- OPTION RP_GRP<NCAP_AFCS;
    db.assign("RP_GRP", "select distinct r, p, cg from NCAP_AFCS")
    # --- BS_SUPP(TRACKP(RP_STD(RP)))$SUM(TOP(RPC_PG(TRACKPC(RP,C)),'OUT'),1)=YES;
    db.add("BS_SUPP", f"""select distinct t.r, t.p from TOP t where t.io='OUT' and {tp('t.r','t.p')} and in_RP_STD(t.r,t.p)
                          and {tpc('t.r','t.p','t.c')} and in_RPC_PG(t.r,t.p,t.c)""")
    # --- BS_SUPP(TRACKP(RP_STG(RP)))$SUM(TOP(TRACKPC(RP_GRP(RP,C)),'OUT'),1)=YES;
    db.add("BS_SUPP", f"""select distinct t.r, t.p from TOP t where t.io='OUT' and {tp('t.r','t.p')} and in_RP_STG(t.r,t.p)
                          and {tpc('t.r','t.p','t.c')} and in_RP_GRP(t.r,t.p,t.c)""")
    # --- BS_SUPP(BS_ENDP(RP))$SUM(TOP(RPC_STG(RP,C),'OUT'),NOT TRACKPC(RP,C))=NO;
    db.remove("BS_SUPP", where=f"""in_BS_ENDP(r,p) and exists(select 1 from TOP t where t.r=BS_SUPP.r and t.p=BS_SUPP.p and t.io='OUT'
                                   and in_RPC_STG(t.r,t.p,t.c) and not {tpc('t.r','t.p','t.c')})""")
    # --- BS_SUPP(BS_SUPP(RP_STD(RP)))$PROD(RPC_SPG(RP,C),TRACKPC(RP,C))=NO;
    #     (PROD over no shadow commodity is 1: a process without RPC_SPG goes too)
    db.remove("BS_SUPP", where=f"""in_RP_STD(r,p) and not exists(select 1 from RPC_SPG g where g.r=BS_SUPP.r and g.p=BS_SUPP.p
                                   and not {tpc('g.r','g.p','g.c')})""")
    # --- BS_SUPP(BS_STGP)=NO;
    db.remove("BS_SUPP", where="in_BS_STGP(r,p)")
    # --- Qualify as end-user process
    # --- TRACKP(RP_STG)=YES;
    x("insert into t_bs_tp select r, p from RP_STG k where not exists(select 1 from t_bs_tp t where t.r=k.r and t.p=k.p)")
    # --- BS_ENDP(TRACKP(RP_FLO(RP)))=(NOT BS_SUPP(RP)+BS_STGP(RP));
    db.remove("BS_ENDP", where=f"in_RP_FLO(r,p) and {tp('BS_ENDP.r','BS_ENDP.p')}")
    db.add("BS_ENDP", "select r, p from t_bs_tp where in_RP_FLO(r,p) and not (in_BS_SUPP(r,p) or in_BS_STGP(r,p))")
    # --- BS_BSC(BS_ENDP(R,P),C)$((NOT RP_PGACT(R,P))$BS_ANEG(R,C))=NO;
    db.remove("BS_BSC", where="in_BS_ENDP(r,p) and not in_RP_PGACT(r,p) and in_BS_ANEG(r,c)")
    # --- BS_NEGP(TRACKP(R,P))=SUM(BS_BSC(R,P,C)$BS_ANEG(R,C),1);
    db.remove("BS_NEGP", where=tp("BS_NEGP.r", "BS_NEGP.p"))
    db.add("BS_NEGP", "select distinct t.r, t.p from t_bs_tp t join BS_BSC b on b.r=t.r and b.p=t.p where in_BS_ANEG(b.r,b.c)")
    # --- BS_NEGP(BS_SUPP(RP))$RP_UPL(RP,'FX')=YES;
    db.add("BS_NEGP", "select r, p from BS_SUPP where in_RP_UPL(r,p,'FX')")
    # --- Levelization
    # --- BS_PRS(PRC_TS(TRACKP(RP),S))$(RP_STD(RP)+RPS_STG(RP,S))=YES;
    db.add("BS_PRS", f"select r, p, s from PRC_TS where {tp('PRC_TS.r','PRC_TS.p')} and (in_RP_STD(r,p) or in_RPS_STG(r,p,s))")
    # --- Hold RMAX processes to be levelized
    # --- VDA_FLOP(R,LL--ORD(LL),P,C,S+STOA(S))$STOA(S) $=BS_RMAX(R,LL,P,C,S);
    # --- OPTION PRC_YMAX<VDA_FLOP,CLEAR=VDA_FLOP; PRC_YMAX(RP)$BS_PRS(RP,'ANNUAL')=NO;
    #     (PRC_YMAX: the processes with a maximum given below ANNUAL; only the records count, VDA_FLOP is empty before)
    db.clear("PRC_YMAX")
    db.put("PRC_YMAX", "select distinct r, p, 1 as value from BS_RMAX where s <> 'ANNUAL' and not in_BS_PRS(r,p,'ANNUAL')")
    # --- Reserve Commodity attributes
    # --- LOOP(COM_TSL(R,C,TSLVL)$BS_RTYPE(R,C),F=ORD(TSLVL)-1;
    #       LOOP(RJLVL(J,R,TSL)$(F>=ORD(TSL)),
    #         LOOP(TS_GROUP(R,TSL,TS),BS_RTCS(RSP,R,T,C,S)$(NOT BS_RTCS(RSP,R,T,C,S)) $= BS_RTCS(RSP,R,T,C,TS)$(STOAL(R,S)=F)$RS_BELOW(R,TS,S))));
    #     (the values given on a coarser level go down to the timeslices of the commodity's level, the nearest level first:
    #      RJLVL runs from the finest level up)
    for r, c, f in db.q("""select k.r, k.c, ord_tsl(k.tsl) - 1 from COM_TSL k where in_BS_RTYPE(k.r, k.c)
                           order by {r}, {c}""".format(r=_uo("k.r"), c=_uo("k.c"))):
        for (tsl,) in db.q(f"select tsl from RJLVL where r='{r}' and ord_tsl(tsl) <= {f} order by {_uo('j')}"):
            x(f"""insert into BS_RTCS select b.rsp, b.r, b.y, b.c, w.s2, b.value
                  from BS_RTCS b join TS_GROUP g on g.r=b.r and g.s=b.s and g.tsl='{tsl}'
                  join RS_BELOW w on w.r=b.r and w.s=b.s
                  where b.r='{r}' and b.c='{c}' and in_MILESTONYR(b.y) and v_STOAL(b.r, w.s2) = {f}
                    and not exists(select 1 from BS_RTCS o where o.rsp=b.rsp and o.r=b.r and o.y=b.y and o.c=b.c and o.s=w.s2)""")
    # --- Put-back
    # --- BS_OMEGA(RTC,S)$= BS_RTCS('OMEGA',RTC,S);  BS_DELTA(RTC,S)$= BS_RTCS('DELTA',RTC,S);
    db.put("BS_OMEGA", "select r, y, c, s, value from BS_RTCS where rsp='OMEGA' and in_RTC(r,y,c)", zero="eps")
    db.put("BS_DELTA", "select r, y, c, s, value from BS_RTCS where rsp='DELTA' and in_RTC(r,y,c)", zero="eps")
    # --- Reserve Process attributes
    # --- OPTION RP_PRC<BS_MAINT; RP_PRC(RP_PRC(RP))=PRC_CAP(RP)$RP_STD(RP)+SUM(RPS_CAFLAC(PRC_TS(RP_STG(RP),S),BD),YES);
    db.assign("RP_PRC", "select distinct r, p from BS_MAINT")
    db.remove("RP_PRC", where="""in_RP(r,p) and not ((in_PRC_CAP(r,p) and in_RP_STD(r,p)) or (in_RP_STG(r,p) and exists(
                                  select 1 from RPS_CAFLAC k where k.r=RP_PRC.r and k.p=RP_PRC.p and in_PRC_TS(k.r,k.p,k.s) and k.l in ('LO','UP','FX'))))""")
    # --- BS_MAINT(R,V,P,S)$(NOT RP_PRC(R,P))=0; RP_UPL(RP_PRC,'FX')=YES;
    db.zap("BS_MAINT", "not in_RP_PRC(r,p)")
    db.add("RP_UPL", "select r, p, 'FX' as l from RP_PRC")
    # --- ACT_UPS(RTP(R,T,P),S,'N')$BS_MAINT(RTP,S)=BS_MAINT(RTP,S)*
    #       MAX(1$(BS_MAINT(RTP,S)<=1),(1/G_YRFR(R,S)/8760)$(NOT COEF_AF(R,T,T,P,S,'UP')))$TS_CYCLE(R,S);
    db.tmp("t_bs_au", """select m.r, m.y, m.p, m.s, m.value * greatest(case when m.value <= 1 then 1 else 0 end,
                               case when not in_COEF_AF(m.r,m.y,m.y,m.p,m.s,'UP') then 1 / v_G_YRFR(m.r,m.s) / 8760 else 0 end)
                               * (case when v_TS_CYCLE(m.r,m.s) <> 0 then 1 else 0 end) as value
                         from BS_MAINT m where in_RTP(m.r,m.y,m.p) and in_MILESTONYR(m.y)""")
    db.zap("ACT_UPS", "l='N' and exists(select 1 from t_bs_au a where a.r=ACT_UPS.r and a.y=ACT_UPS.y and a.p=ACT_UPS.p and a.s=ACT_UPS.s)")
    db.put("ACT_UPS", """select a.r, a.y, a.p, a.s, 'N' as l, a.value from t_bs_au a
                         where a.value <> 0 or (v_TS_CYCLE(a.r,a.s) <> 0 and exists(select 1 from BS_MAINT m
                               where m.r=a.r and m.y=a.y and m.p=a.p and m.s=a.s and m.value = 0))""", zero="eps")
    # --- LOOP((RLUP(R,TSLVL,TSL),TS_GROUP(R,TSL,TS)),BS_MAINT(RTP(R,V,P),TS)$((NOT BS_MAINT(RTP,TS))$PRC_TSL(R,P,TSLVL)$RP_PRC(R,P))=
    #       -MAX(0,SMAX(RS_BELOW1(R,TS,S),BS_MAINT(RTP,S))));
    #     (a timeslice above those of the process, without a value of its own: minus the largest of the timeslices directly
    #      below it; in the order of RLUP, so that a level filled first is read by the next)
    for r, tsl, tsl2 in db.q(f"select r, tsl, tsl2 from RLUP order by {_uo('r')}, {_uo('tsl')}, {_uo('tsl2')}"):
        db.put("BS_MAINT", f"""select k.r, k.y, k.p, g.s, -greatest(0, (select max(m.value) from BS_MAINT m join RS_BELOW1 w
                                     on w.r=m.r and w.s2=m.s where m.r=k.r and m.y=k.y and m.p=k.p and w.s=g.s)) as value
                               from RTP k join PRC_TSL t on t.r=k.r and t.p=k.p and t.tsl='{tsl}'
                               join TS_GROUP g on g.r=k.r and g.tsl='{tsl2}'
                               where k.r='{r}' and in_RP_PRC(k.r,k.p) and not in_BS_MAINT(k.r,k.y,k.p,g.s)""")
    # --- LOOP((RJLVL(J,R,TSL),RLUP(R,TSLVL,TSL)),
    #       LOOP(TS_GROUP(R,TSL,TS),
    #         BS_MAINT(RTP(R,V,P),S)$((NOT BS_MAINT(RTP,S))$BS_MAINT(RTP,TS)) = -ABS(BS_MAINT(RTP,TS))$RS_BELOW(R,TS,S);
    #         BS_RMAX(RTP(R,V,P),C,S)$((NOT BS_RMAX(RTP,C,S))$BS_PRS(R,P,S)$PRC_YMAX(R,P)) $= BS_RMAX(RTP,C,TS)$RS_BELOW(R,TS,S)));
    for r, tsl, _ in db.q(f"""select distinct j.r, j.tsl, {_uo('j.j')} as o from RJLVL j join RLUP u on u.r=j.r and u.tsl2=j.tsl
                           order by {_uo('j.r')}, o"""):
        for (ts,) in db.q(f"select s from TS_GROUP where r='{r}' and tsl='{tsl}' order by {_uo('s')}"):
            db.put("BS_MAINT", f"""select m.r, m.y, m.p, w.s2 as s, -abs(m.value) as value from BS_MAINT m
                                   join RS_BELOW w on w.r=m.r and w.s=m.s
                                   where m.r='{r}' and m.s='{ts}' and in_RTP(m.r,m.y,m.p)
                                     and not in_BS_MAINT(m.r,m.y,m.p,w.s2)""", zero="eps")
            db.put("BS_RMAX", f"""select m.r, m.y, m.p, m.c, w.s2 as s, m.value from BS_RMAX m
                                  join RS_BELOW w on w.r=m.r and w.s=m.s
                                  where m.r='{r}' and m.s='{ts}' and in_RTP(m.r,m.y,m.p) and in_BS_PRS(m.r,m.p,w.s2)
                                    and v_PRC_YMAX(m.r,m.p) <> 0 and not in_BS_RMAX(m.r,m.y,m.p,m.c,w.s2)""", zero="eps")
    # --- Generation & load Variances
    # --- LOOP(RJLVL(J,R,TSL)$(ORD(TSL)<4),
    #       LOOP(TS_GROUP(R,TSL,TS),BS_SIGMA(R,T,C,BS_K,S)$((NOT BS_SIGMA(R,T,C,BS_K,S))$FINEST(R,S)) $= BS_SIGMA(R,T,C,BS_K,TS)$RS_BELOW(R,TS,S)));
    for r, tsl in db.q(f"select r, tsl from RJLVL where ord_tsl(tsl) < 4 order by {_uo('r')}, {_uo('j')}"):
        for (ts,) in db.q(f"select s from TS_GROUP where r='{r}' and tsl='{tsl}' order by {_uo('s')}"):
            db.put("BS_SIGMA", f"""select m.r, m.y, m.c, m.u, w.s2 as s, m.value from BS_SIGMA m
                                   join RS_BELOW w on w.r=m.r and w.s=m.s
                                   where m.r='{r}' and m.s='{ts}' and in_MILESTONYR(m.y) and in_BS_K(m.u) and in_FINEST(m.r,w.s2)
                                     and not in_BS_SIGMA(m.r,m.y,m.c,m.u,w.s2)""", zero="eps")
    # --- Default values
    # --- BS_SHARE(RTC,BDNEQ,'N') $= BS_LAMBDA(RTC);
    db.put("BS_SHARE", """select b.r, b.y, b.c, x.l as u, 'N' as l, b.value from BS_LAMBDA b, (select 'LO' as l union all select 'UP') x
                          where in_RTC(b.r,b.y,b.c)""", zero="eps")
    # --- OPTION CLEAR=RXX; RXX(BS_APOS(R,C),COM)$((BS_RTYPE(R,C)+BS_RTYPE(R,COM)=0)$BS_ANEG(R,COM)) = YES;
    # --- LOOP(RXX(R,C,COM),
    #       BS_SIGMA(R,T,C,BS_K,S)$(NOT BS_SIGMA(R,T,C,BS_K,S)) $=BS_SIGMA(R,T,COM,BS_K,S);
    #       BS_SIGMA(R,T,COM,BS_K,S)$(NOT BS_SIGMA(R,T,COM,BS_K,S)) $=BS_SIGMA(R,T,C,BS_K,S);
    #       BS_DELTA(R,T,C,S)$(NOT BS_DELTA(R,T,C,S)) $=BS_DELTA(R,T,COM,S);
    #       BS_DELTA(R,T,COM,S)$(NOT BS_DELTA(R,T,COM,S)) $=BS_DELTA(R,T,C,S));
    #     (each positive reserve and the negative one of the same type give each other the variances and calibrations
    #      missing; RXX itself is cleared again below)
    pairs = db.q(f"""select a.r, a.c, n.c from BS_APOS a join BS_ANEG n on n.r=a.r
                     where v_BS_RTYPE(a.r,a.c) + v_BS_RTYPE(n.r,n.c) = 0 order by {_uo('a.r')}, {_uo('a.c')}, {_uo('n.c')}""")
    db.clear("RXX")
    for r, c, com in pairs:
        for to, fr in ((c, com), (com, c)):
            db.put("BS_SIGMA", f"""select m.r, m.y, '{to}' as c, m.u, m.s, m.value from BS_SIGMA m
                                   where m.r='{r}' and m.c='{fr}' and in_MILESTONYR(m.y) and in_BS_K(m.u)
                                     and not in_BS_SIGMA(m.r,m.y,'{to}',m.u,m.s)""", zero="eps")
        for to, fr in ((c, com), (com, c)):
            db.put("BS_DELTA", f"""select m.r, m.y, '{to}' as c, m.s, m.value from BS_DELTA m
                                   where m.r='{r}' and m.c='{fr}' and in_MILESTONYR(m.y) and not in_BS_DELTA(m.r,m.y,'{to}',m.s)""",
                   zero="eps")
    # --- Imbalance topology
    # --- LOOP((TRACKPC(RP_FLO(R,P),C),BS_K)$GR_GENMAP(R,P,BS_K),
    #       IF(GR_GENMAP(R,P,BS_K)>0,BS_TOP(TOP(R,P,C,IO))$TOP(R,P,C,'OUT')=YES;
    #       ELSE BS_TOP(TOP(R,P,C,IO))$(IPS(IO)+PRC_MAP(R,'STG',P))=YES));
    #     (a source of imbalance by generation: its electricity outputs; by load (negative): its inputs, and for a storage
    #      both sides)
    db.add("BS_TOP", f"""select t.r, t.p, t.c, t.io from TOP t join GR_GENMAP g on g.r=t.r and g.p=t.p
                         where in_BS_K(g.u) and in_RP_FLO(t.r,t.p) and {tpc('t.r','t.p','t.c')} and (
                           (g.value > 0 and in_TOP(t.r,t.p,t.c,'OUT')) or
                           (not g.value > 0 and (in_IPS(t.io) or in_PRC_MAP(t.r,'STG',t.p))))""")
    # --- GR_GENMAP(R,P(BS_K),P)$PROD(PRC$GR_GENMAP(R,PRC,P),0)=1;
    #     (a process named as a source of imbalance, that no process is mapped to, is mapped to itself)
    db.put("GR_GENMAP", """select r.r, k.u as p, k.u, 1 as value from REG r, BS_K k
                           where in_PRC(k.u) and not exists(select 1 from GR_GENMAP g where g.r=r.r and g.u=k.u)""")
    # --- OPTION CLEAR=RXX,CLEAR=TRACKP,CLEAR=RP_PRC,CLEAR=RP_GRP,CLEAR=TRACKPC;
    db.clear("RXX", "RP_PRC", "RP_GRP")
    x("drop table if exists t_bs_tp"); x("drop table if exists t_bs_tpc")
    # --- Timeslices
    # --- OPTION RCS < BS_OMEGA;
    # --- LOOP(COM_TS(RCS(R,C,S)),BS_COMTS(R,C,TS)$RS_TREE(R,S,TS)=YES);
    db.add("BS_COMTS", """select distinct o.r, o.c, t.s2 as s from BS_OMEGA o join RS_TREE t on t.r=o.r and t.s=o.s
                          where in_COM_TS(o.r,o.c,o.s)""")
    # --- BS_DELTA(RTCS_VARC(RTC,S))$((NOT BS_DELTA(RTC,S))$BS_OMEGA(RTC,S)) = 1;
    db.put("BS_DELTA", """select k.r, k.y, k.c, k.s, 1 as value from RTCS_VARC k where in_RTC(k.r,k.y,k.c)
                          and not in_BS_DELTA(k.r,k.y,k.c,k.s) and in_BS_OMEGA(k.r,k.y,k.c,k.s)""")
    # --- BS_SIGMA(RTC(R,T,C),BS_K,S)$((BS_LAMBDA(RTC)$BS_COMTS(R,C,S)=0)$BS_SIGMA(RTC,BS_K,S))=0;
    db.zap("BS_SIGMA", "in_RTC(r,y,c) and in_BS_K(u) and (v_BS_LAMBDA(r,y,c) = 0 or not in_BS_COMTS(r,c,s))")
    # --- LOOP((R,T,C,BS_K,S)$BS_SIGMA(R,T,C,BS_K,S),BS_RTK(R,T,BS_K)=YES);
    db.add("BS_RTK", "select distinct r, y, u from BS_SIGMA where in_MILESTONYR(y) and in_BS_K(u)")
    # --- LOOP(COM_LIM(R,C,L)$BS_RTYPE(R,C),BS_OMEGA(R,'0',C,S)$BS_COMTS(R,C,S)=FINEST(R,S)$IPS(L)+COM_TS(R,C,S)$BD(L));
    #     (year 0 of BS_OMEGA: the timeslices of the balance, the finest ones (N) or those of the commodity (LO, UP, FX);
    #      the last type of COM_LIM in GAMS order counts)
    db.x(f"""create or replace temp table t_bs_lim as select r, c, l from (
               select r, c, l, row_number() over (partition by r, c order by {_uo('l')} desc) as k from COM_LIM where in_BS_RTYPE(r,c))
             where k = 1""")
    db.zap("BS_OMEGA", "y='0' and exists(select 1 from t_bs_lim m where m.r=BS_OMEGA.r and m.c=BS_OMEGA.c) and in_BS_COMTS(r,c,s)")
    db.put("BS_OMEGA", """select t.r, '0' as y, t.c, t.s, (case when in_IPS(m.l) and in_FINEST(t.r,t.s) then 1 else 0 end) +
                                 (case when m.l in ('LO','UP','FX') and in_COM_TS(t.r,t.c,t.s) then 1 else 0 end) as value
                          from BS_COMTS t join t_bs_lim m on m.r=t.r and m.c=t.c""")
    # --- Activate COMNET, disable COMPRD
    # --- RHS_COMBAL(RTCS_VARC(R,T,C,S))$BS_RTYPE(R,C)=BS_COMTS(R,C,S);
    db.remove("RHS_COMBAL", where="in_BS_RTYPE(r,c) and in_RTCS_VARC(r,y,c,s) and not in_BS_COMTS(r,c,s)")
    db.add("RHS_COMBAL", "select r, y, c, s from RTCS_VARC where in_BS_RTYPE(r,c) and in_BS_COMTS(r,c,s)")
    # --- RCS_COMBAL(RTCS_VARC(R,T,C,S),'FX') $= BS_RTYPE(R,C);
    db.add("RCS_COMBAL", "select r, y, c, s, 'FX' as l from RTCS_VARC where in_BS_RTYPE(r,c)")
    # --- RHS_COMPRD(RTCS_VARC(R,T,C,S))$BS_RTYPE(R,C) = NO;  RCS_COMPRD(RTCS_VARC(R,T,C,S),'FX')$BS_RTYPE(R,C) = NO;
    db.remove("RHS_COMPRD", where="in_BS_RTYPE(r,c) and in_RTCS_VARC(r,y,c,s)")
    db.remove("RCS_COMPRD", where="l='FX' and in_BS_RTYPE(r,c) and in_RTCS_VARC(r,y,c,s)")
    # --- COM_BNDPRD(RTCS_VARC(R,T,C,S),'UP')$((NOT BS_COMTS(R,C,S)$BS_LAMBDA(R,T,C))$BS_RTYPE(R,C)) = EPS;
    db.put("COM_BNDPRD", """select r, y, c, s, 'UP' as l, 0 as value from RTCS_VARC where in_BS_RTYPE(r,c)
                            and not (in_BS_COMTS(r,c,s) and in_BS_LAMBDA(r,y,c))""", zero="eps")
    # --- COM_AGG(R,T,C,C)$BS_RTYPE(R,C)=1;
    db.put("COM_AGG", "select b.r, t.y, b.c, b.c as c2, 1 as value from BS_RTYPE b, MILESTONYR t")
    # --- RC_AGP(RC,'FX')$=BS_RTYPE(RC);
    db.add("RC_AGP", "select r, c, 'FX' as l from BS_RTYPE where in_RC(r,c)")
    # --- Post-process RMAX; no reserve supply from multi-output AFC processes
    # --- BS_RMAX(R,V,P,C,S)$(BS_SUPP(R,P)$RP_STD(R,P)$RPS_CAFLAC(R,P,S,'UP'))=0;
    db.zap("BS_RMAX", "in_BS_SUPP(r,p) and in_RP_STD(r,p) and in_RPS_CAFLAC(r,p,s,'UP')")
    # --- LOOP((RC(R,C),BD)$BS_ABD(RC,BD),
    #       VDA_FLOP(RTP(R,V,P),C,S)$((BS_PRS(R,P,S)$PRC_YMAX(R,P)+ANNUAL(S))$BS_BSC(R,P,C)) =
    #         SMAX(BS_ABD(R,COM,BD)$((BS_RTYPE(RC)-BS_RTYPE(R,COM))*BDSIG(BD)<=0),BS_RMAX(RTP,COM,S)));
    #     (the maximum share of a reserve is at least that of every slower reserve of the same direction)
    db.tmp("t_bs_fl", """select k.r, k.y, k.p, b.c, s.s,
                           coalesce((select max(v_BS_RMAX(k.r,k.y,k.p,a.c,s.s)) from BS_ABD a where a.r=b.r and a.l=d.l
                                       and (v_BS_RTYPE(b.r,b.c) - v_BS_RTYPE(a.r,a.c)) * v_BDSIG(d.l) <= 0), 0) as value
                         from BS_BSC b join BS_ABD d on d.r=b.r and d.c=b.c join RTP k on k.r=b.r and k.p=b.p, ALL_TS s
                         where in_RC(b.r,b.c) and ((in_BS_PRS(b.r,b.p,s.s) and v_PRC_YMAX(b.r,b.p) <> 0) or s.s = 'ANNUAL')""")
    # --- VDA_FLOP(RTP,C,S)$((BS_RMAX(RTP,C,S)=VDA_FLOP(RTP,C,S))$BS_RMAX(RTP,C,S))=0;
    db.x("delete from t_bs_fl where value = 0 or (in_BS_RMAX(r,y,p,c,s) and v_BS_RMAX(r,y,p,c,s) = value)")
    # --- BS_RMAX(RTP,C,S) $= VDA_FLOP(RTP,C,S); OPTION NCAP_AFAC < VDA_FLOP;
    db.put("BS_RMAX", "select r, y, p, c, s, value from t_bs_fl where in_RTP(r,y,p)", zero="skip")
    # --- LOOP((RTP(R,V,P),C)$NCAP_AFAC(RTP,C), PUT QLOG ' WARNING ... BS_RMAX decreasing at slower reserve types - reset');
    _qa_warnings(db, "BS_RMAX decreasing at slower reserve types - reset",
                 "select distinct r, y, p, c from t_bs_fl where in_RTP(r,y,p)", "Kept at preceding value")
    # --- BS_RMAX(RTP(R,V,P),C,ANNUAL(S))$BS_BSC(R,P,C) = BS_RMAX(RTP,C,S)$(NOT PRC_YMAX(R,P));
    db.zap("BS_RMAX", "s='ANNUAL' and in_RTP(r,y,p) and in_BS_BSC(r,p,c) and v_PRC_YMAX(r,p) <> 0")
    # --- Controls for reserve limits
    # --- RPC_CONLY(RTP(R,V,P),C)$((BS_RMAX(RTP,C,'ANNUAL')$BS_SUPP(R,P)<1-ACT_MINLD(RTP)$BS_ABD(R,C,'UP'))$BS_BSC(R,P,C))=YES;
    db.add("RPC_CONLY", """select k.r, k.y, k.p, b.c from RTP k join BS_BSC b on b.r=k.r and b.p=k.p
                           where (case when in_BS_SUPP(k.r,k.p) then v_BS_RMAX(k.r,k.y,k.p,b.c,'ANNUAL') else 0 end)
                                 < 1 - (case when in_BS_ABD(b.r,b.c,'UP') then v_ACT_MINLD(k.r,k.y,k.p) else 0 end)""")
    # --- LOOP((BS_ABD(RC(R,COM),BD),C,ANNUAL(S))$BS_ABD(R,C,BD),
    #       IF((BS_RTYPE(RC)-BS_RTYPE(R,C))*BDSIG(BD)<0,
    #         RPC_CONLY(RTP(R,V,P),C)$((BS_RMAX(RTP,C,S)>=BS_RMAX(RTP,COM,S))$BS_RMAX(RTP,COM,S))=NO));
    #     (no limit of its own for a slower reserve whose share is not below that of a faster one)
    db.remove("RPC_CONLY", where="""in_RTP(r,y,p) and exists(select 1 from BS_ABD a join BS_ABD b on b.r=a.r and b.l=a.l
              where a.r=RPC_CONLY.r and b.c=RPC_CONLY.c and in_RC(a.r,a.c)
                and (v_BS_RTYPE(a.r,a.c) - v_BS_RTYPE(b.r,b.c)) * v_BDSIG(a.l) < 0
                and in_BS_RMAX(RPC_CONLY.r,RPC_CONLY.y,RPC_CONLY.p,a.c,'ANNUAL')
                and v_BS_RMAX(RPC_CONLY.r,RPC_CONLY.y,RPC_CONLY.p,b.c,'ANNUAL') >= v_BS_RMAX(RPC_CONLY.r,RPC_CONLY.y,RPC_CONLY.p,a.c,'ANNUAL'))""")
    # --- LOOP((BS_COMTS(R,C,S),BS_ABD(R,C,L)),BS_SBD(R,S,L)=YES);
    db.add("BS_SBD", "select distinct t.r, t.s, a.l from BS_COMTS t join BS_ABD a on a.r=t.r and a.c=t.c")
    # --- OPTION CLEAR=PRC_YMAX,CLEAR=VDA_FLOP,CLEAR=NCAP_AFAC,CLEAR=RCS;
    db.clear("PRC_YMAX", "VDA_FLOP", "NCAP_AFAC", "RCS")
    x("drop table if exists t_bs_fl")
    # --- Build UC map
    # --- BS_UCMAP(UC_MAP_FLO(UC_N,SIDE,R,P,C))$(BS_BSC(R,P,C)+BS_STGP(R,P)$BS_STIME(R,P,C,'UP'))$=BS_RTYPE(R,C);
    db.add("BS_UCMAP", """select uc, side, r, p, c from UC_MAP_FLO where in_BS_RTYPE(r,c)
                          and (in_BS_BSC(r,p,c) or (in_BS_STGP(r,p) and in_BS_STIME(r,p,c,'UP')))""")
    # --- Ensure existence of AF
    # --- COEF_AF(RTP_VINTYR(R,T,T,P),S,'UP')$(NOT RTP_CPTYR(R,T,T,P)) $= NCAP_AF(R,T,P,S,'UP')$BS_PRS(R,P,S);
    db.put("COEF_AF", """select n.r, n.y, n.y as y2, n.p, n.s, 'UP' as l, n.value from NCAP_AF n
                         where n.l='UP' and in_RTP_VINTYR(n.r,n.y,n.y,n.p) and in_MILESTONYR(n.y)
                           and not in_RTP_CPTYR(n.r,n.y,n.y,n.p) and in_BS_PRS(n.r,n.p,n.s)""", zero="eps")


def equ_ext(db: DB):
    """equ_ext.abs, ABS Final pre-processing (maindrv.mod, after eqmain.mod and equ_ext.vda)"""
    if not on(db):
        return
    x = db.x
    # --- Adjust equation controls
    # --- BS_UPL(RP_UPL(BS_SUPP,BDNEQ))=YES;
    db.add("BS_UPL", "select r, p, l from RP_UPL where l in ('LO','UP') and in_BS_SUPP(r,p)")
    # --- BS_UPC(PRC_TSL(BS_SUPP(R,P),TSL),BDNEQ)$SUM(BS_BSC(R,P,C)$(ABS(BS_RTYPE(R,C))>2),1)$=RP_UPS(R,P,TSL,'UP');
    #     (a supply process that provides non-spinning reserves: its minimum on-line and off-line times are those of ABS)
    db.add("BS_UPC", """select k.r, k.p, k.tsl, b.l from PRC_TSL k, (select 'LO' as l union all select 'UP') b
                        where in_BS_SUPP(k.r,k.p) and in_RP_UPS(k.r,k.p,k.tsl,'UP')
                          and exists(select 1 from BS_BSC c where c.r=k.r and c.p=k.p and abs(v_BS_RTYPE(c.r,c.c)) > 2)""")
    # --- RP_UPL(BS_UPL)=NO;  RP_UPC(BS_UPC)=NO;
    db.remove("RP_UPL", where="in_BS_UPL(r,p,l)")
    db.remove("RP_UPC", where="in_BS_UPC(r,p,tsl,l)")
    # --- Activate capacity equations
    # --- OPTION TRACKP<BS_BSC; RP_UPL(TRACKP,'N')=YES;
    db.tmp("t_bs_tp", "select distinct r, p from BS_BSC")
    db.add("RP_UPL", "select r, p, 'N' as l from t_bs_tp")
    # --- RP_UPS(TRACKP(R,P),TSL,'FX')$SUM(RP_UPS(PRC_TSL(R,P,TSLVL),L),RLUP(R,TSLVL,TSL))=YES;
    db.add("RP_UPS", """select distinct u.r, u.p, l.tsl2 as tsl, 'FX' as l from RP_UPS u join t_bs_tp t on t.r=u.r and t.p=u.p
                        join RLUP l on l.r=u.r and l.tsl=u.tsl where in_PRC_TSL(u.r,u.p,u.tsl)""")
    # --- RP_UPS(TRACKP(R,P),TSL,'LO')$SUM(PRC_TSL(R,P,TSLVL)$RLUP(R,TSLVL,TSL),NOT RP_UPS(R,P,TSL,'FX'))=YES;
    db.add("RP_UPS", """select distinct k.r, k.p, l.tsl2 as tsl, 'LO' as l from PRC_TSL k join t_bs_tp t on t.r=k.r and t.p=k.p
                        join RLUP l on l.r=k.r and l.tsl=k.tsl where not in_RP_UPS(k.r,k.p,l.tsl2,'FX')""")
    # --- RP_UPS(PRC_TSL(TRACKP,TSL(S)),'LO')=YES;       (TSL(S): the level that is also a timeslice, ANNUAL)
    db.add("RP_UPS", """select k.r, k.p, k.tsl, 'LO' as l from PRC_TSL k join t_bs_tp t on t.r=k.r and t.p=k.p
                        where in_ALL_TS(k.tsl)""")
    # --- Remove other basic Capact equations
    # --- OPTION TRACKP<AFUPS; BS_MAINT(R,V,P,S)$(NOT TRACKP(R,P)+RP_DP(R,P))=0;
    db.zap("BS_MAINT", "not (exists(select 1 from AFUPS a where a.r=BS_MAINT.r and a.p=BS_MAINT.p) or in_RP_DP(r,p))")
    # --- OPTION TRACKP<BS_SUPP, RP_PRC<NCAP_AFX; TRACKP(BS_STGP)=YES;
    db.tmp("t_bs_tp", "select r, p from BS_SUPP union select r, p from BS_STGP")
    db.assign("RP_PRC", "select distinct r, p from NCAP_AFX")
    # --- RP_PRC(RP_STD(RP))$RP_UPL(RP,'FX')=NO;
    db.remove("RP_PRC", where="in_RP_STD(r,p) and in_RP_UPL(r,p,'FX')")
    # --- AFS(R,T,P,S,L('UP'))$((NOT RPS_CAFLAC(R,P,S,L)+RP_PRC(R,P))$TRACKP(R,P)$BS_PRS(R,P,S))=NO;
    db.remove("AFS", where="""l='UP' and in_BS_PRS(r,p,s) and exists(select 1 from t_bs_tp t where t.r=AFS.r and t.p=AFS.p)
                              and not (in_RPS_CAFLAC(r,p,s,'UP') or in_RP_PRC(r,p))""")
    # --- AFUPS(R,T,P,S)$BS_SUPP(R,P)=NO;
    db.remove("AFUPS", where="in_BS_SUPP(r,p)")
    # --- NCAP_AFC(R,V,P,%PGPRIM%,STL(S))$(BS_PRS(R,P,S)$BS_STGP(R,P))=0;
    db.zap("NCAP_AFC", "cg='ACT' and in_BS_PRS(r,p,stl) and in_BS_STGP(r,p)")
    # --- OPTION CLEAR=UNCD7,CLEAR=TRACKP,CLEAR=RP_PRC;
    db.clear("RP_PRC")
    x("drop table if exists t_bs_tp")
    # --- LOOP((RTP(R,V,P),RPS_PRCTS(R,P,S))$((NOT PRC_TS(R,P,S))$BS_MAINT(RTP,S)),Z=BS_MAINT(RTP,S);
    #       F=ABS(Z); IF((F>=TS_CYCLE(R,S)*24$(F>1))$(RPS_UPS(R,P,S) OR (STOAL(R,S)*SIGN(Z)<2)),UNCD7(RTP,S,RTP)=YES));
    #     (maintenance given above the process timeslices, as long as a cycle of the timeslice or longer: started and
    #      stopped on the season level)
    db.tmp("t_bs_u7", """select m.r, m.y, m.p, m.s from BS_MAINT m join RPS_PRCTS k on k.r=m.r and k.p=m.p and k.s=m.s
                         where in_RTP(m.r,m.y,m.p) and not in_PRC_TS(m.r,m.p,m.s)
                           and abs(m.value) >= v_TS_CYCLE(m.r,m.s) * (case when abs(m.value) > 1 then 24 else 0 end)
                           and (in_RPS_UPS(m.r,m.p,m.s) or v_STOAL(m.r,m.s) * sign(m.value) < 2)""")
    # --- LOOP(UNCD7(RTP,S,R,T,P),RPS_UPS(R,P,TS)$(STOAL(R,TS)=1)=YES;
    #       BS_MAINT(RTP,TS)$RS_TREE(R,S,TS)=EPS$(BS_MAINT(RTP,TS)>=0)$BS_MAINT(RTP,TS));
    db.add("RPS_UPS", "select distinct u.r, u.p, t.s from t_bs_u7 u, ALL_TS t where v_STOAL(u.r,t.s) = 1")
    for r, y, p, s in db.q(f"select r, y, p, s from t_bs_u7 order by {_uo('r')}, {_uo('y')}, {_uo('p')}, {_uo('s')}"):
        db.zap("BS_MAINT", f"""r='{r}' and y='{y}' and p='{p}' and in_RS_TREE(r,'{s}',s) and value < 0""")
        db.x(f"""update BS_MAINT set value = 0 where r='{r}' and y='{y}' and p='{p}' and in_RS_TREE(r,'{s}',s)""")
    x("drop table if exists t_bs_u7")
    # --- BS_RVT(R,VNT(V,T)) $= SUM(RC(R,C)$BS_LAMBDA(R,T,C),1);
    db.add("BS_RVT", """select distinct k.r, n.y, n.y2 from VNT n, RC k where in_MILESTONYR(n.y2)
                        and in_BS_LAMBDA(k.r,n.y2,k.c)""")


def final(db: DB):
    """After pp_qack.mod: the tables that only the ABS equations read, as port-only copies (a model without ABS has none
    of them): BS_CONLY, RPC_CONLY of the reserve commodities (EQ_BS11); BS_TSCYC, TS_CYCLE (EQ_BS27); BS_EUCAP, the
    electricity input per unit of activity of an end-use process with negative reserves, the coefficient of EQ_BS24:

      SUM(TOP(R,P,C,'IN')$NRG_TMAP(R,'ELC',C),PRC_ACTFLO(R,V,P,C)$RPC_PG(R,P,C) +
        SUM(RTPCS_VARF(R,T,P,C,TS)$RS_FR(R,TS,S),RS_FR(R,TS,S) *
          SUM(RPC_PG(R,P,COM),ACT_FLO(R,V,P,C,TS)$RPC_FFUNC(R,P,C) + PRC_ACTFLO(R,V,P,COM) *
           (SUM(RPG_1ACE(R,P,CG,C)$COEF_PTRAN(R,V,P,CG,C,COM,TS),1/COEF_PTRAN(R,V,P,CG,C,COM,TS)) +
            SUM((RPCC_FFUNC(RP_PG(R,P,CG),C),TS_MAP(R,SL,TS))$RPS_S1(R,P,SL),(ACT_FLO(R,V,P,C,SL)**1$RPC_AFLO(R,P,C))*COEF_PTRAN(R,V,P,CG,COM,C,S)))))$(NOT RPC_PG(R,P,C)))
    """
    if not on(db):
        return
    for name, kind, dom in (("BS_CONLY", "set", ["R", "ALLYEAR", "P", "C"]), ("BS_TSCYC", "par", ["REG", "TS"]),
                            ("BS_EUCAP", "par", ["R", "ALLYEAR", "T", "P", "S"])):
        if name not in db.sym:
            db.declare(name, kind, dom)
    db.assign("BS_CONLY", "select r, y, p, c from RPC_CONLY where in_BS_RTYPE(r, c)")
    db.put("BS_TSCYC", "select r, s, value from TS_CYCLE", zero="eps")
    procs = db.q("select r, p from BS_ENDP where in_BS_NEGP(r, p)")
    if not procs:
        return
    q = lambda sql: db.q(sql)
    pl = ", ".join(f"('{r}','{p}')" for r, p in procs)
    inp = lambda a: f"(({a}.r, {a}.p) in ({pl}))"
    elc = q(f"select t.r, t.p, t.c, in_RPC_PG(t.r,t.p,t.c), in_RPC_FFUNC(t.r,t.p,t.c), in_RPC_AFLO(t.r,t.p,t.c) from TOP t "
            f"where t.io='IN' and in_NRG_TMAP(t.r,'ELC',t.c) and {inp('t')}")
    pg = {}
    for r, p, c in q(f"select g.r, g.p, g.c from RPC_PG g where {inp('g')}"):
        pg.setdefault((r, p), []).append(c)
    actflo = {(r, v, p, c): x for r, v, p, c, x in q(f"select a.r, a.y, a.p, a.cg, a.value from PRC_ACTFLO a where {inp('a')}")}
    aflo = {(r, v, p, c, s): x for r, v, p, c, s, x in q(f"select a.r, a.y, a.p, a.cg, a.s, a.value from ACT_FLO a where {inp('a')}")}
    ptran = {k[:7]: k[7] for k in q(f"select a.r, a.y, a.p, a.cg, a.c, a.cg2, a.s, a.value from COEF_PTRAN a where {inp('a')}")}
    ace = {}
    for r, p, cg, c in q(f"select a.r, a.p, a.cg, a.c from RPG_1ACE a where {inp('a')}"):
        ace.setdefault((r, p, c), []).append(cg)
    ffg = {}
    for r, p, cg, c in q(f"select a.r, a.p, a.cg, a.cg2 from RPCC_FFUNC a where {inp('a')} and in_RP_PG(a.r,a.p,a.cg)"):
        ffg.setdefault((r, p, c), []).append(cg)
    s1 = {}
    for r, p, s in q(f"select a.r, a.p, a.s from RPS_S1 a where {inp('a')}"):
        s1.setdefault((r, p), set()).add(s)
    above = {}
    for r, s, ts in q("select r, s, s2 from TS_MAP"):
        above.setdefault((r, ts), []).append(s)            # TS_MAP(R,SL,TS): the timeslices SL at or above TS
    varf = {}
    for r, y, p, c, s in q(f"select a.r, a.y, a.p, a.c, a.s from RTPCS_VARF a where {inp('a')}"):
        varf.setdefault((r, y, p, c), []).append(s)
    rsfr = {}
    for r, ts, s, x in q("select r, s, s2, value from RS_FR"):
        rsfr[(r, ts, s)] = x                                   # RS_FR(R,TS,S)
    dom = q(f"""select k.r, k.y, k.y2, k.p, b.s from RTP_VINTYR k join BS_PRS b on b.r=k.r and b.p=k.p
               where in_MILESTONYR(k.y2) and {inp('k')}""")
    rows = []
    for r, v, t, p, s in dom:
        tot = 0.0
        for rr, pp, c, is_pg, is_ff, is_af in elc:
            if (rr, pp) != (r, p):
                continue
            if is_pg:
                tot += actflo.get((r, v, p, c), 0.0)
                continue
            for ts in varf.get((r, t, p, c), ()):
                fr = rsfr.get((r, ts, s), 0.0)
                if not fr:
                    continue
                inner = 0.0
                for com in pg.get((r, p), ()):
                    a = aflo.get((r, v, p, c, ts), 0.0) if is_ff else 0.0
                    b = sum(1 / ptran[(r, v, p, cg, c, com, ts)] for cg in ace.get((r, p, c), ())
                            if (r, v, p, cg, c, com, ts) in ptran and ptran[(r, v, p, cg, c, com, ts)] != 0)
                    for cg in ffg.get((r, p, c), ()):
                        for sl in above.get((r, ts), ()):
                            if sl in s1.get((r, p), ()):
                                b += (aflo.get((r, v, p, c, sl), 0.0) if is_af else 1.0) * ptran.get((r, v, p, cg, com, c, s), 0.0)
                    inner += a + actflo.get((r, v, p, com), 0.0) * b
                tot += fr * inner
        if tot:
            rows.append((r, v, t, p, s, tot))
    if rows:
        from .common import _values
        db.put("BS_EUCAP", _values(rows, ["r", "y", "y2", "p", "s", "value"]))


def _qa_warnings(db, title, select, text):
    """pp_qaput.mod: one line of the QA log per record of `select` (r, y, p, c)."""
    log = getattr(db, "log", None)
    if log is None:
        return
    for r, y, p, c in db.q(f"select * from ({select}) order by 1, 3, 2, 4"):
        log.append(f"*01 WARNING - {title}: {text},  R={r} P={p} V={y} C={c}")
