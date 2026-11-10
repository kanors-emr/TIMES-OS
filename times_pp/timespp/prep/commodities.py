# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod: commodity attributes by timeslice, the balance type of each commodity, and where the balance
needs VAR_COMNET / VAR_COMPRD."""
from ..engine import DB
from .common import require_empty


# ---------------------------------------------------------------------------
def commodity_attributes(db: DB):
    """Commodity attributes by timeslice: COM_IE, COM_FR, costs."""
    from ..lvl import lvlfc
    # --- RTC_NET(RTC(R,T,C))$(NOT COM_TSL(R,C,'ANNUAL')) = YES;
    db.add("RTC_NET", "select r, y, c from RTC where not in_COM_TSL(r,c,'ANNUAL')")
    lvlfc(db, "COM_IE", ["c"], "COM_TS", "MILESTONYR", "in_RTC(a.r,a.y,a.c)")
    lvlfc(db, "COM_FR", ["c"], "COM_TS", "MILESTONYR", "in_RTC_NET(a.r,a.y,a.c)", weighted=True)
    lvlfc(db, "COM_PKFLX", ["c"], "COM_TS", "MILESTONYR")
    for n in ("OBJ_COMNT", "OBJ_COMPD", "COM_ELAST", "COM_BPRICE"):
        lvlfc(db, n, ["c"], "COM_TS", "DATAYEAR", "in_RC(a.r,a.c)")
    lvlfc(db, "COM_BQTY", ["c"], "COM_TS", None, "in_RC(a.r,a.c)", weighted=True)
    # --- OPTION RCS < COM_IE, CLEAR=RTC_NET,CLEAR=RP_PGFLO;   COM_IE(RTCS_VARC(R,T,C,S))$(NOT RCS(R,C,S)) = 1;
    db.clear("RTC_NET", "RP_PGFLO")
    db.put("COM_IE", """select r, y, c, s, 1 as value from RTCS_VARC k
                        where not exists(select 1 from COM_IE e where e.r=k.r and e.c=k.c and e.s=k.s)""")
    # --- COM_FR(R,LL,C,ANNUAL)=0; OPTION RCS<COM_FR;  TRACKC(R,C) $= SUM(RCS(R,C,S),1);
    db.zap("COM_FR", "s='ANNUAL' and in_REG(r)")
    db.tmp("t_given", "select distinct r, c, s from COM_FR")
    db.tmp("t_trackc", "select distinct r, c from t_given where in_REG(r) and in_COM(c)")
    # --- RCS(TRACKC(R,C),S)$G_YRFR(R,S) = (NOT RCS(R,C,S));       timeslices without a given fraction
    db.tmp("t_rcs", """select k.r, k.c, g.s from t_trackc k join G_YRFR g on g.r=k.r
                       where not exists(select 1 from t_given x where x.r=k.r and x.c=k.c and x.s=g.s)""")
    # --- COM_FR(RTC(R,T,C),S)$(RCS(R,C,S)*COM_TS(R,C,S)) = G_YRFR(R,S);
    db.put("COM_FR", """select k.r, k.y, k.c, x.s, v_G_YRFR(k.r,x.s) as value from RTC k join t_rcs x on x.r=k.r and x.c=k.c
                        where in_COM_TS(k.r,k.c,x.s)""")
    # --- COM_FR(RTC(R,T,C),TS)$(RCS(R,C,TS)*TS_GROUP(R,'WEEKLY',TS)) $= SUM(RS_BELOW1(R,S,TS),COM_FR(R,T,C,S)*(G_YRFR(R,TS)/G_YRFR(R,S)));  then DAYNITE
    for lvl in ("WEEKLY", "DAYNITE"):
        db.put("COM_FR", f"""select k.r, k.y, k.c, x.s, v_COM_FR(k.r,k.y,k.c,b.s) * (v_G_YRFR(k.r,x.s) / v_G_YRFR(k.r,b.s)) as value
                             from RTC k join t_rcs x on x.r=k.r and x.c=k.c join RS_BELOW1 b on b.r=k.r and b.s2=x.s
                             where in_TS_GROUP(k.r,'{lvl}',x.s) and in_COM_FR(k.r,k.y,k.c,b.s)""", zero="eps")
    # --- COM_FR(R,T,C,TS)$(TRACKC(R,C)$TS_GROUP(R,'WEEKLY',TS)) $= SUM(RS_BELOW1(R,TS,S),COM_FR(R,T,C,S));  then SEASON
    for lvl in ("WEEKLY", "SEASON"):
        db.put("COM_FR", f"""select f.r, f.y, f.c, b.s, sum(f.value order by ord_s(f.s)) as value from COM_FR f join RS_BELOW1 b on b.r=f.r and b.s2=f.s
                             where in_MILESTONYR(f.y) and in_TS_GROUP(f.r,'{lvl}',b.s)
                               and exists(select 1 from t_trackc k where k.r=f.r and k.c=f.c)
                             group by f.r, f.y, f.c, b.s""", zero="eps")
    # --- COM_FR(R,T,C,S)$NORTS(R,T,S)=0;     (dynamic timeslices)
    if db.card("NORTS"):
        db.zap("COM_FR", "in_NORTS(r, y, s)")
    # --- COM_FR(R,T,C,ANNUAL)$TRACKC(R,C) = SUM(RS_BELOW1(R,ANNUAL,S),COM_FR(R,T,C,S));
    db.put("COM_FR", """select k.r, t.y, k.c, 'ANNUAL' as s,
                               coalesce((select sum(f.value order by ord_s(f.s)) from COM_FR f join RS_BELOW1 b on b.r=f.r and b.s2=f.s and b.s='ANNUAL'
                                         where f.r=k.r and f.y=t.y and f.c=k.c), 0) as value
                        from t_trackc k, MILESTONYR t""")
    # --- Normalize COM_FR
    for r, c, y in db.q("""select k.r, k.c, min(f.y) from t_trackc k join COM_FR f on f.r=k.r and f.c=k.c and f.s='ANNUAL'
                           where in_RTC(f.r,f.y,f.c) and abs(f.value - 1) > 1e-5 group by k.r, k.c"""):
        db.log.append(f"*01 WARNING - COM_FR does not sum to unity (T=first year); normalized to 1, R={r} C={c} (T={y})")
    # --- COM_FR(RTC(R,T,C),S)$((COM_FR(RTC,'ANNUAL') NE 1)$TRACKC(R,C)) = COM_FR(RTC,S) / COM_FR(RTC,'ANNUAL');
    db.put("COM_FR", """select f.r, f.y, f.c, f.s, f.value / v_COM_FR(f.r,f.y,f.c,'ANNUAL') as value from COM_FR f
                        where in_RTC(f.r,f.y,f.c) and exists(select 1 from t_trackc k where k.r=f.r and k.c=f.c)
                          and v_COM_FR(f.r,f.y,f.c,'ANNUAL') <> 1""", zero="eps")          # EPS/x stays EPS
    # --- RP_PGFLO(RP(R,P))$=SUM(RPC_PG(RP,C)$TRACKC(R,C),1);  RP_PGFLO(RP)$SUM(RPS_S1(PRC_TS(RP,S)),1)=NO;
    db.add("RP_PGFLO", """select distinct g.r, g.p from RPC_PG g join t_trackc k on k.r=g.r and k.c=g.c where in_RP(g.r,g.p)""")
    db.remove("RP_PGFLO", where="exists(select 1 from RPS_S1 x where x.r=RP_PGFLO.r and x.p=RP_PGFLO.p and in_PRC_TS(x.r,x.p,x.s))")
    db.clear("RCS")


# ---------------------------------------------------------------------------
def balance_types(db: DB):
    """Commodity balance types (COM_LIM); conversion factors between trading regions."""
    # --- NRG(RC(R,C))$COM_TMAP(R,'NRG',C) = YES;  ... MAT, DEM, ENV, FIN
    for t in ("NRG", "MAT", "DEM", "ENV", "FIN"):
        db.add(t, f"select r, c from RC where in_COM_TMAP(r,'{t}',c)")
    # --- TRACKC(RC) = YES; LOOP(LIM,TRACKC(R,C)$COM_LIM(R,C,LIM) = NO);
    #     COM_LIM(TRACKC(NRG(R,C)),'UP')$(NRG_TMAP(R,'CONSRV',C) + NRG_TMAP(R,'FRERENEW',C)) = YES;
    #     COM_LIM(MAT(TRACKC),'FX') = YES; COM_LIM(FIN(TRACKC),'FX') = YES;  COM_LIM(TRACKC,'LO') = YES;   (first that applies)
    db.add("COM_LIM", """select r, c, case
                 when in_NRG(r,c) and (in_NRG_TMAP(r,'CONSRV',c) or in_NRG_TMAP(r,'FRERENEW',c)) then 'UP'
                 when in_MAT(r,c) or in_FIN(r,c) then 'FX' else 'LO' end as l
               from RC k where not exists(select 1 from COM_LIM m where m.r=k.r and m.c=k.c)""")
    # --- handle TIMES-MACRO:  $IFI %MACRO%==YES COM_LIM(RC(DEM),BD)$(NOT COM_LIM(RC,'N')) = NOT BDNEQ(BD);
    #     (taken with MLF: readbprice.mod 20 sets MACRO to 'Yes', and $IFI compares without case)
    if db.ctl.get("MLF"):
        db.tmp("t_macdem", "select r, c from RC k where in_DEM(r,c) and not exists(select 1 from COM_LIM m where m.r=k.r and m.c=k.c and m.l='N')")
        db.remove("COM_LIM", where="l in ('LO','UP','FX') and exists(select 1 from t_macdem t where t.r=COM_LIM.r and t.c=COM_LIM.c)")
        db.add("COM_LIM", "select r, c, 'FX' as l from t_macdem")
    # --- OPTION RREG <= TOP_IRE;
    db.assign("RREG", "select distinct r, r2 from TOP_IRE")
    # --- LOOP(RREG(ALL_R,ALL_REG), Z=1; LOOP(TSLVL$Z, Z = both regions have the same timeslices on the level;
    #        IF(Z, RXX(ALL_R,S,ALL_REG)$TS_GROUP(ALL_R,TSLVL,S) = YES)));   RXX(ALL_R,S,ALL_REG)$RXX(ALL_REG,S,ALL_R) = YES;
    pairs = []
    grp = {}
    for r, tsl, s in db.q("select r, tsl, s from TS_GROUP"):
        grp.setdefault((r, tsl), set()).add(s)
    for a, b in db.q("select r, r2 from RREG"):
        for tsl in ("ANNUAL", "SEASON", "WEEKLY", "DAYNITE"):
            sa, sb = grp.get((a, tsl), set()), grp.get((b, tsl), set())
            if sa != sb:
                break
            pairs += [(a, s, b) for s in sa]
    pairs = set(pairs) | {(b, s, a) for a, s, b in pairs}
    db.clear("RXX")
    db.load_rows("RXX", list(pairs))
    # --- IRE_TSCVT(RXX(ALL_R,S,ALL_REG),S)$(NOT IRE_TSCVT(ALL_R,S,ALL_REG,S)) = 1;
    #     (NOT EPS is false: a value given as 0 (EPS under $ONEPS) stays)
    db.put("IRE_TSCVT", "select r, u as s, u2 as r2, u as s2, 1 as value from RXX where not in_IRE_TSCVT(r,u,u2,u)")
    # --- OPTION RC_RC < IRE_CCVT;  IRE_CCVT(RC_RC(RC,R,C))$(NOT IRE_CCVT(RC_RC)) = 1/IRE_CCVT(R,C,RC);     reverse direction
    #     (NOT EPS is false: a value given as 0 (EPS under $ONEPS) stays, in all three)
    db.put("IRE_CCVT", """select r2 as r, c2 as c, r as r2, c as c2, 1 / value as value from IRE_CCVT a
                          where in_RC(a.r2,a.c2) and in_REG(a.r) and in_COM(a.c) and not in_IRE_CCVT(a.r2,a.c2,a.r,a.c)""")
    # --- OPTION RC_RC <= TOP_IRE; IRE_CCVT(RC_RC)$(NOT IRE_CCVT(RC_RC)) = 1;   OPTION RC_RC <  TOP_IRE; ... = 1;
    db.put("IRE_CCVT", "select distinct r, c, r2, c2, 1 as value from TOP_IRE where not in_IRE_CCVT(r,c,r2,c2)")
    db.put("IRE_CCVT", "select distinct r2 as r, c2 as c, r as r2, c as c2, 1 as value from TOP_IRE where not in_IRE_CCVT(r2,c2,r,c)")
    db.assign("RC_RC", "select distinct r2 as r, c2 as c, r as r2, c as c2 from TOP_IRE")


# ---------------------------------------------------------------------------
def balance_variables(db: DB):
    """Where VAR_COMNET / VAR_COMPRD are needed on the commodity balance."""
    # --- LOOP((R,T,C,COM)$COM_AGG(R,T,C,COM),RC_AGP(COM_LIM(R,C,LIM)) = YES);
    db.add("RC_AGP", """select distinct m.r, m.c, m.l from COM_AGG a join COM_LIM m on m.r=a.r and m.c=a.c
                        where in_MILESTONYR(a.y) and in_REG(a.r)""")
    # --- RC_AGP(R,C,BD)$(COM_TMAP(R,'DEM',C)$RC_AGP(R,C,'LO')) = NOT BDNEQ(BD);
    db.tmp("t_dem", "select r, c from RC_AGP where l='LO' and in_COM_TMAP(r,'DEM',c)")
    db.remove("RC_AGP", where="l in ('LO','UP') and exists(select 1 from t_dem d where d.r=RC_AGP.r and d.c=RC_AGP.c)")
    db.add("RC_AGP", "select r, c, 'FX' as l from t_dem")
    # --- RC_AGP(RC,'FX')$RC_AGP(RC,'N') = YES;
    db.add("RC_AGP", "select r, c, 'FX' as l from RC_AGP where l='N' and in_RC(r,c)")
    # --- RHS_COMBAL(RTCS_VARC(R,T,C,S))$RC_AGP(R,C,'LO') = YES;  RHS_COMPRD(RTCS_VARC(R,T,C,S))$RC_AGP(R,C,'FX') = YES;
    db.add("RHS_COMBAL", "select r, y, c, s from RTCS_VARC where in_RC_AGP(r,c,'LO')")
    db.add("RHS_COMPRD", "select r, y, c, s from RTCS_VARC where in_RC_AGP(r,c,'FX')")
    require_empty(db, ["DAM_ELAST"], "damage functions")
    # --- LOOP(RC_CUMCOM(R,'NET',ALLYEAR,LL,C), RTC_NET(R,T,C)$((E(T) >= YEARVAL(ALLYEAR)) * (B(T) <= YEARVAL(LL))) = YES);   'PRD' -> RTC_PRD
    for cv, dst in (("NET", "RTC_NET"), ("PRD", "RTC_PRD")):
        db.add(dst, f"""select distinct k.r, t.y, k.c from RC_CUMCOM k, MILESTONYR t
                        where k.cv='{cv}' and v_E(t.y) >= yv(k.y) and v_B(t.y) <= yv(k.y2)""")
    # --- RHS_COMBAL(RTCS_VARC(RTC_NET,S)) = YES;  RHS_COMPRD(RTCS_VARC(RTC_PRD,S)) = YES;
    db.add("RHS_COMBAL", "select r, y, c, s from RTCS_VARC where in_RTC_NET(r,y,c)")
    db.add("RHS_COMPRD", "select r, y, c, s from RTCS_VARC where in_RTC_PRD(r,y,c)")
    # --- COM_CSTNET(R,LL--ORD(LL),C,S--ORD(S),CUR)$(COM_CSTNET(R,LL,C,S,CUR)+COM_SUBNET(R,LL,C,S,CUR)+COM_TAXNET(R,LL,C,S,CUR)) = EPS;
    #     LOOP((R,C,S,RDCUR(R,CUR))$COM_CSTNET(R,'0',C,S,CUR),RHS_COMBAL(RTCS_VARC(R,T,C,TS)) = YES);
    #     ... the same with COM_CSTPRD / COM_SUBPRD / COM_TAXPRD and RHS_COMPRD
    #     (a commodity with a cost, tax or subsidy on its net or gross production gets its VAR_COMNET / VAR_COMPRD in all
    #      periods and timeslices; the flag is an EPS under year '0' and the last timeslice, S--ORD(S))
    s_last = db.q1("select t.s from ALL_TS t join __uel u on u.label = t.s order by u.ord desc limit 1")
    for trio, rhs in ((("COM_CSTNET", "COM_SUBNET", "COM_TAXNET"), "RHS_COMBAL"), (("COM_CSTPRD", "COM_SUBPRD", "COM_TAXPRD"), "RHS_COMPRD")):
        if not any(db.card(n) for n in trio):
            continue
        src = " union ".join(f'select r, c, cur from "{n}"' for n in trio)
        db.put(trio[0], f"select distinct r, '0' as y, c, '{s_last}' as s, cur, 0.0 as value from ({src})", zero="eps")
        db.add(rhs, f"""select distinct k.r, k.y, k.c, k.s from RTCS_VARC k
                        where exists(select 1 from "{trio[0]}" a where a.r=k.r and a.c=k.c and a.y='0' and in_RDCUR(a.r,a.cur))""")
    # --- RHS_COMBAL(RTCS_VARC(R,T,C,S))$SUM((TS_MAP(R,TS,S),BD)$COM_BNDNET(R,T,C,TS,BD),ABS(COM_BNDNET(R,T,C,TS,BD)) NE INF$BDUPX(BD)) = YES;
    db.add("RHS_COMBAL", """select distinct k.r, k.y, k.c, k.s from RTCS_VARC k join COM_BNDNET b on b.r=k.r and b.y=k.y and b.c=k.c
                            where in_TS_MAP(k.r,b.s,k.s) and (case when in_BDUPX(b.l) then not isinf(b.value) else b.value <> 0 end)""")
    # --- RHS_COMPRD(RTCS_VARC(R,T,C,S))$SUM((TS_MAP(R,TS,S),BD)$COM_BNDPRD(R,T,C,TS,BD),
    #        (ABS(COM_BNDPRD(..)) NE INF) AND (COM_BNDPRD(..) NE NA$BDUPX(BD))) = YES;
    db.add("RHS_COMPRD", """select distinct k.r, k.y, k.c, k.s from RTCS_VARC k join COM_BNDPRD b on b.r=k.r and b.y=k.y and b.c=k.c
                            where in_TS_MAP(k.r,b.s,k.s) and not isinf(b.value)
                              and (case when in_BDUPX(b.l) then not isnan(b.value) else b.value <> 0 end)""")
