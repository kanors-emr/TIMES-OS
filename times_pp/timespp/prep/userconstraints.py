# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod: user constraints (scope defaults, timeslice levels, group maps, UC_ATTR, dynamic constraints)."""
from ..engine import DB
from .. import side as par_side


# ---------------------------------------------------------------------------
def user_constraints(db: DB):
    """User constraints: defaults for the region / period / timeslice scope, group maps, levelling."""
    from ..lvl import lvlus
    # ---- prepxtra.mod UCINT: period ranges given with interpolation-style year entries
    # --- UC_DT(R,UC_N)$UC_T_SUM(R,UC_N,'0') = YES; UC_T_SUM(UC_DT,'0') = NO;
    #     LOOP(UC_DT, Z=SMAX(..ORD(LL)); F=SMIN(..); IF(Z NE F, milestone years strictly between; ELSE UC_T_SUM(UC_DT,T) = YES));
    db.tmp("t_dt", "select distinct r, uc from UC_T_SUM where y='0'")
    db.remove("UC_T_SUM", where="y='0'")
    db.add("UC_T_SUM", """
        with rng as (select d.r, d.uc, min(yv(s.y)) as f, max(yv(s.y)) as z from t_dt d left join UC_T_SUM s on s.r=d.r and s.uc=d.uc
                     group by d.r, d.uc)
        select g.r, g.uc, t.y from rng g, MILESTONYR t
        where g.z is null or g.z = g.f or (yv(t.y) > g.f and yv(t.y) < g.z)""")
    # --- UC_T_SUCC(R,UC_N,T)$UC_T_SUCC(R,UC_N,'0') = YES;  UC_T_EACH(R,UC_N,T)$UC_T_EACH(R,UC_N,'0') = YES;
    for n in ("UC_T_SUCC", "UC_T_EACH"):
        db.add(n, f"""select e.r, e.uc, t.y from "{n}" e, MILESTONYR t where e.y='0'""")
    # --- LOOP(T(YEAR), UC_T_EACH(R,UC_N,T)$(EOHYEARS(LL)$PERIODYR(T,LL)$UC_T_EACH(R,UC_N,LL)) = YES;  same for UC_T_SUCC, UC_T_SUM
    for n in ("UC_T_EACH", "UC_T_SUCC", "UC_T_SUM"):
        db.add(n, f"""select e.r, e.uc, p.y from "{n}" e join PERIODYR p on p.y2=e.y where in_EOHYEARS(e.y)""")
    uc_tsl(db)
    # ---- defaults
    # --- UC_RHS(UC_N,L)$(NOT UC_RHS(UC_N,L)) $= UC_RHSS(UC_N,'ANNUAL',L);   UC_RHSR ... UC_RHSRS
    #     (NOT EPS is false: a value given as 0 (EPS under $ONEPS) stays)
    db.put("UC_RHS", "select uc, l, value from UC_RHSS where s='ANNUAL' and not in_UC_RHS(uc,l)", zero="eps")
    db.put("UC_RHSR", "select r, uc, l, value from UC_RHSRS where s='ANNUAL' and in_REG(r) and not in_UC_RHSR(r,uc,l)", zero="eps")
    # --- UNCD1(UCN)$(NOT SUM(UC_R_EACH(ALL_R,UCN),1)) = YES;  UC_ON(R,UCN) = any regional RHS given
    #     UC_R_EACH(R,UCN)$(NOT UC_ON(R,UCN))=NO; UC_R_EACH(UC_ON(R,UCN))$=UNCD1(UCN);
    db.tmp("t_free", "select uc from UC_N n where not exists(select 1 from UC_R_EACH e where e.uc=n.uc)")
    db.tmp("t_on", """select r, uc from UC_RHSR where in_REG(r) union
                      select r, uc from UC_RHSRT where in_REG(r) and in_MILESTONYR(y) union
                      select r, uc from UC_RHSRTS where in_REG(r) and in_MILESTONYR(y)""")
    db.remove("UC_R_EACH", where="in_REG(r) and not exists(select 1 from t_on o where o.r=UC_R_EACH.r and o.uc=UC_R_EACH.uc)")
    db.add("UC_R_EACH", "select o.r, o.uc from t_on o join t_free f on f.uc=o.uc")
    # --- same for UC_R_SUM with the global RHS parameters
    db.tmp("t_free", "select uc from UC_N n where not exists(select 1 from UC_R_SUM e where e.uc=n.uc)")
    db.tmp("t_dt", """select g.r, u.uc from REG g, (select uc from UC_RHS union select uc from UC_RHST where in_MILESTONYR(y)
                                                    union select uc from UC_RHSTS where in_MILESTONYR(y)) u""")
    db.remove("UC_R_SUM", where="in_REG(r) and not exists(select 1 from t_dt o where o.r=UC_R_SUM.r and o.uc=UC_R_SUM.uc)")
    db.add("UC_R_SUM", "select o.r, o.uc from t_dt o join t_free f on f.uc=o.uc")
    # --- OPTION CLEAR=UC_DT,UC_ON<UC_R_EACH; UC_ON(UC_R_SUM)=YES;
    db.assign("UC_ON", "select r, uc from UC_R_EACH union select r, uc from UC_R_SUM")
    no_ts = "not exists(select 1 from UC_TS_SUM x where x.r=k.r and x.uc=k.uc) and not exists(select 1 from UC_TS_EACH x where x.r=k.r and x.uc=k.uc)"
    # --- UC_DT(UC_R_SUM(R,UC_N))$(no UC_TS_SUM and no UC_TS_EACH) = YES;
    db.tmp("t_dt", f"select r, uc from UC_R_SUM k where in_REG(r) and {no_ts}")
    # --- UC_TS_EACH(UC_DT(R,UC_N),ANNUAL)$SUM(L$UC_RHS(UC_N,L),1) = YES;   ..,S)$UC_RHSTS;   UC_TS_SUM(UC_DT,ANNUAL)$UC_RHST
    db.tmp("t_a", "select d.r, d.uc, 'ANNUAL' as s from t_dt d where exists(select 1 from UC_RHS h where h.uc=d.uc)")
    db.tmp("t_b", "select distinct d.r, d.uc, h.s from t_dt d join UC_RHSTS h on h.uc=d.uc where in_MILESTONYR(h.y)")
    db.tmp("t_c", "select d.r, d.uc, 'ANNUAL' as s from t_dt d where exists(select 1 from UC_RHST h where h.uc=d.uc and in_MILESTONYR(h.y))")
    db.add("UC_TS_EACH", "select * from t_a union select * from t_b")
    db.add("UC_TS_SUM", "select * from t_c")
    # --- UC_DT(UC_R_SUM)$(NOT UC_R_EACH(UC_R_SUM)) = NO;  UC_DT(UC_R_EACH(R,UC_N))$(no UC_TS_SUM and no UC_TS_EACH) = YES;
    db.x("delete from t_dt d where in_UC_R_SUM(d.r,d.uc) and not in_UC_R_EACH(d.r,d.uc)")
    db.x(f"""insert into t_dt select r, uc from UC_R_EACH k where in_REG(r) and {no_ts}
             and not exists(select 1 from t_dt d where d.r=k.r and d.uc=k.uc)""")
    # --- UC_TS_SUM(UC_DT,ANNUAL)$SUM((T,L)$UC_RHSRT(UC_DT,T,L),1) = YES;  UC_TS_EACH(UC_DT,ANNUAL)$SUM(L$UC_RHSR(UC_DT,L),1) = YES;
    #     UC_TS_EACH(UC_DT,S)$SUM((T,L)$UC_RHSRTS(UC_DT,T,S,L),1) = YES;
    db.tmp("t_a", "select d.r, d.uc, 'ANNUAL' as s from t_dt d where exists(select 1 from UC_RHSRT h where h.r=d.r and h.uc=d.uc and in_MILESTONYR(h.y))")
    db.tmp("t_b", "select d.r, d.uc, 'ANNUAL' as s from t_dt d where exists(select 1 from UC_RHSR h where h.r=d.r and h.uc=d.uc)")
    #     (between the two: UC_DT(R_UC) = NO, the constraints on a timeslice level take no default from UC_RHSRTS)
    db.x("delete from t_dt where in_R_UC(r,uc)")
    db.tmp("t_c", "select distinct d.r, d.uc, h.s from t_dt d join UC_RHSRTS h on h.r=d.r and h.uc=d.uc where in_MILESTONYR(h.y)")
    db.add("UC_TS_SUM", "select * from t_a")
    db.add("UC_TS_EACH", "select * from t_b union select * from t_c")
    # --- UC_T_EACH(UC_T_SUCC) = YES;             (T_SUCC overrides T_EACH; copied here so that the defaults need one test)
    db.add("UC_T_EACH", "select r, uc, y from UC_T_SUCC")
    # --- OPTION UC_DT < UC_ON;  UC_DT(UC_DT)$SUM(UC_T_EACH(UC_DT,T),1) = NO; UC_DT(UC_DT)$SUM(UC_T_SUM(UC_DT,T),1) = NO;
    db.tmp("t_dt", """select r, uc from UC_ON k where not exists(select 1 from UC_T_EACH x where x.r=k.r and x.uc=k.uc and in_MILESTONYR(x.y))
                      and not exists(select 1 from UC_T_SUM x where x.r=k.r and x.uc=k.uc and in_MILESTONYR(x.y))""")
    # --- UC_T_SUM(UC_R_SUM(UC_DT(R,UC_N)),T)$SUM(L$UC_RHS(UC_N,L),1) = YES;  UC_T_SUM(UC_R_EACH(UC_DT),T)$SUM(L$UC_RHSR(UC_DT,L),1) = YES;
    db.add("UC_T_SUM", """select d.r, d.uc, t.y from t_dt d, MILESTONYR t where in_UC_R_SUM(d.r,d.uc)
                          and exists(select 1 from UC_RHS h where h.uc=d.uc)""")
    db.add("UC_T_SUM", """select d.r, d.uc, t.y from t_dt d, MILESTONYR t where in_UC_R_EACH(d.r,d.uc)
                          and exists(select 1 from UC_RHSR h where h.r=d.r and h.uc=d.uc)""")
    # --- UC_T_EACH(UC_DT,T)$(NOT UC_T_SUM(UC_DT,T)) = YES;
    db.add("UC_T_EACH", "select d.r, d.uc, t.y from t_dt d, MILESTONYR t where not in_UC_T_SUM(d.r,d.uc,t.y)")
    # --- cumulative UCs: LOOP(T,UC_DT(R,UC_N)$(UC_TS_EACH(R,UC_N,'ANNUAL')$UC_T_SUM(R,UC_N,T)) = YES);
    #     UC_TS_SUM(UC_DT,ANNUAL) = YES; UC_TS_EACH(UC_TS_SUM(R,UC_N,ANNUAL)) = NO;
    db.tmp("t_dt", """select distinct e.r, e.uc from UC_TS_EACH e where e.s='ANNUAL'
                      and exists(select 1 from UC_T_SUM x where x.r=e.r and x.uc=e.uc and in_MILESTONYR(x.y))""")
    db.add("UC_TS_SUM", "select r, uc, 'ANNUAL' as s from t_dt")
    db.remove("UC_TS_EACH", where="s='ANNUAL' and in_UC_TS_SUM(r,uc,'ANNUAL')")
    uc_attributes(db)
    # --- RS_PREV(R,S,S--RS_STG(R,S)) $= RS_TSLVL(R,S); G_UDS(S,'LHS',S) = YES;
    db.add("RS_PREV", """select t.r, t.s, o2.s as s2 from RS_TSLVL t join ORD_S o1 on o1.s=t.s
                         join ORD_S o2 on o2.ord = 1 + ((o1.ord - 1 - cast(v_RS_STG(t.r,t.s) as INTEGER)) % (select count(*) from ORD_S)
                                                        + (select count(*) from ORD_S)) % (select count(*) from ORD_S)""")
    db.add("G_UDS", "select s, 'LHS' as side, s as s2 from ALL_TS")
    # --- LOOP(R$SUM(UC_TSL(R,UCN,'RHS',TSL),1),G_UDS(S,'RHS',TS)$RS_PREV(R,S,TS)=YES);
    db.add("G_UDS", "select distinct p.s, 'RHS' as side, p.s2 from RS_PREV p where exists(select 1 from UC_TSL u where u.r=p.r and u.side='RHS')")
    # ---- group maps
    # --- OPTION UC_MAP_FLO < UC_FLO;  UC_CAPFLO(..)$(NOT UC_MAP_FLO(..)) = NO;  UC_MAP_FLO(UC_N,SIDE,RP_IRE,C) = NO;
    db.assign("UC_MAP_FLO", "select distinct uc, side, r, p, c from UC_FLO")
    db.remove("UC_CAPFLO", where="not in_UC_MAP_FLO(uc,side,r,p,c)")
    for uc, side, r, p, c in db.q("select * from UC_MAP_FLO where in_RP_IRE(r,p) and in_REG(r)"):
        db.log.append(f"*01 WARNING - UC_FLO given for a trade process, ignored: UC={uc} R={r} P={p} C={c}")
    db.remove("UC_MAP_FLO", where="in_RP_IRE(r,p)")
    # --- OPTION UC_MAP_IRE < UC_IRE;  UC_MAP_IRE(UC_N,R,P,C,IE)$(NOT RPC_IRE(R,P,C,IE)) = NO;
    db.assign("UC_MAP_IRE", "select distinct uc, r, p, c, ie from UC_IRE")
    db.remove("UC_MAP_IRE", where="in_REG(r) and not in_RPC_IRE(r,p,c,ie)")
    # --- OPTION UC_GMAP_C < UC_COM;
    db.assign("UC_GMAP_C", "select distinct r, uc, cv, c, grp from UC_COM")
    # --- UC_ATTR(R,UCN,SIDE,UC_GRPTYPE,UC_DYNT)$UC_ATTR(R,UCN,SIDE,'COMCON',UC_DYNT)$=SUM(UC_GMAP_C(R,UCN,COM_VAR,C,'COMCON')$COV_MAP(COM_VAR,UC_GRPTYPE),1);
    #     (UC_DYNT = N, CUMSUM, CUM+, SYNC;  COV_MAP = NET.COMNET, PRD.COMPRD: the attribute of the consumption form goes to the group types used)
    db.add("UC_ATTR", """select a.r, a.uc, a.side, case when g.cv='NET' then 'COMNET' else 'COMPRD' end as grp, a.ucn
                         from UC_ATTR a join UC_GMAP_C g on g.r=a.r and g.uc=a.uc and g.grp='COMCON'
                         where a.grp='COMCON' and a.ucn in ('N','CUMSUM','CUM+','SYNC')""")
    # --- UC_JMAP('2',UCN,SIDE,R,'0',P,'ACT')$UC_ON(R,UCN) $= SUM(S$UC_ACT(UCN,SIDE,R,T,P,S),1); 'CAP' $= UC_CAP; 'NCAP' $= UC_NCAP;
    #     OPTION UC_GMAP_P < UC_JMAP;
    #     (UC_JMAP also holds the '1' entries of the dynamic bounds by process, set by prep_ext.vda)
    db.assign("UC_GMAP_P", """select distinct r, uc, 'ACT' as grp, p from UC_ACT where in_MILESTONYR(y) and in_UC_ON(r,uc) union
                              select distinct r, uc, 'CAP', p from UC_CAP where in_MILESTONYR(y) and in_UC_ON(r,uc) union
                              select distinct r, uc, 'NCAP', p from UC_NCAP where in_MILESTONYR(y) and in_UC_ON(r,uc) union
                              select distinct r, uc, grp, p from UC_JMAP""")
    # --- OPTION CLEAR=TRACKP,CLEAR=RXX,CLEAR=UC_JMAP;
    db.clear("UC_JMAP")
    # --- UC_ON(R,UCN) $= SUM(UC_DYNBND(UCN,L),1);
    db.add("UC_ON", "select g.r, d.uc from REG g, (select distinct uc from UC_DYNBND) d")
    # --- LOOP(UC_GMAP_P(R,UCN,'CAP',P),TRACKP(R,P)=YES);  RTP_VARP(RTP(R,T,P))$TRACKP(R,P) = YES;
    db.add("RTP_VARP", """select k.r, k.y, k.p from RTP k where in_MILESTONYR(k.y)
                          and exists(select 1 from UC_GMAP_P g where g.r=k.r and g.p=k.p and g.grp='CAP')""")
    # --- LOOP(UC_GMAP_C(UC_ON(R,UC_N),COM_VAR,C,UC_GRPTYPE),RXX(R,COM_VAR,C)=YES);
    db.assign("RXX", "select distinct r, cv as u, c as u2 from UC_GMAP_C where in_UC_ON(r,uc)")
    # --- RHS_COMPRD(RTCS_VARC(R,T,C,S))$RXX(R,'PRD',C) = YES;
    db.add("RHS_COMPRD", "select r, y, c, s from RTCS_VARC where in_RXX(r,'PRD',c)")
    # --- RXX(R,'NET',C)$COM_LIM(R,C,'FX')=NO;  RXX(R,'PRD',C)$(NOT COM_LIM(R,C,'LO'))=NO;
    db.remove("RXX", where="(u='NET' and in_COM_LIM(r,u2,'FX')) or (u='PRD' and not in_COM_LIM(r,u2,'LO'))")
    # --- LOOP(COM_VAR,RHS_COMBAL(RTCS_VARC(R,T,C,S))$RXX(R,COM_VAR,C) = YES);
    db.add("RHS_COMBAL", "select k.r, k.y, k.c, k.s from RTCS_VARC k where in_RXX(k.r,'NET',k.c) or in_RXX(k.r,'PRD',k.c)")
    # ---- levelling of the coefficients
    lvlus(db, "UC_ACT", "PRC_TS", ["p"], "PRC_TSL", "p")
    # (nothing after this stage reads UC_FLO, nor writes what its levelling reads: with TIMESPP_PAR_STAGES=1 it runs
    # beside the rest of the preprocessor, joined at the end of preprocess(); side.py)
    uc_flo = lambda d: lvlus(d, "UC_FLO", "RPCS_VAR", ["p", "c"], "PRC_TSL", "p", floor="max(v_PRC_SGL({a}.r,{a}.p))")
    if par_side.enabled(2):
        par_side.later(db, par_side.beside(db, uc_flo, "lvlus(UC_FLO)"))
    else:
        uc_flo(db)
    lvlus(db, "UC_IRE", "PRC_TS", ["p"], "PRC_TSL", "p")
    lvlus(db, "UC_COM", "COM_TS", ["c"], "COM_TSL", "c")


def uc_tsl(db: DB):
    """ppmain.mod, 'Levelized UC_RHSRTS': user constraints written for every timeslice of a level (UC_ATTR with a level
    name, UC_TSL).  The right-hand side given on a coarser timeslice is handed down to the timeslices of the level."""
    # --- LOOP(T,UC_TSL(R,UC_N,SIDE,TSL)$UC_T_SUCC(R,UC_N,T)=NO);
    db.remove("UC_TSL", where="exists(select 1 from UC_T_SUCC x where x.r=UC_TSL.r and x.uc=UC_TSL.uc and in_MILESTONYR(x.y))")
    # --- OPTION UC_DS < UC_TSL, R_UC < UC_DS, MREG < R_UC;   UC_TSL(R_UC,'LHS',TSL) $= UC_DS(R_UC,TSL);
    db.assign("UC_DS", "select distinct r, uc, tsl from UC_TSL")
    db.assign("R_UC", "select distinct r, uc from UC_DS")
    if not db.card("R_UC"):
        return
    db.add("UC_TSL", "select r, uc, 'LHS' as side, tsl from UC_DS")
    # --- LOOP((RJLVL(J,R(MREG),TSLVL),TSL)$(ORD(TSL)>ORD(TSLVL)), LOOP(TS_GROUP(R,TSLVL,TS),
    #       UC_RHSRTS(R_UC(R,UCN),T,S,L)$((NOT UC_RHSRTS(R_UC,T,S,L))$UC_DS(R_UC,TSL)) $= UC_RHSRTS(R_UC,T,TS,L)$RS_BELOW(R,TS,S)$TS_GROUP(R,TSL,S)));
    #     J counts the levels from the finest: the nearest timeslice above that has a value gives it
    lv = db.q("select distinct tsl, ord_tsl(tsl) from RJLVL order by 2 desc")
    for up, ou in lv:
        for tsl, o in sorted(lv, key=lambda k: k[1]):
            if o <= ou:
                continue
            db.put("UC_RHSRTS", f"""select h.r, h.uc, h.y, b.s2 as s, h.l, h.value from UC_RHSRTS h
                     join TS_GROUP g on g.r=h.r and g.tsl='{up}' and g.s=h.s
                     join RS_BELOW b on b.r=h.r and b.s=h.s
                     join TS_GROUP g2 on g2.r=h.r and g2.tsl='{tsl}' and g2.s=b.s2
                     where in_MILESTONYR(h.y) and in_UC_DS(h.r,h.uc,'{tsl}') and in_RJLVL(cast(5 - {ou} as VARCHAR), h.r, '{up}')
                       and not exists(select 1 from UC_RHSRTS q where q.r=h.r and q.uc=h.uc and q.y=h.y and q.s=b.s2 and q.l=h.l)""", zero="eps")
    # --- LOOP(UC_DS(R_UC(R,UCN),TSL)$SUM(UC_TS_EACH(R_UC,S),1),UC_RHSRTS(R_UC,T,S,L)$((NOT UC_TS_EACH(R_UC,S))$TS_GROUP(R,TSL,S))=0);
    db.x("""delete from UC_RHSRTS h where in_MILESTONYR(h.y) and not in_UC_TS_EACH(h.r,h.uc,h.s)
            and exists(select 1 from UC_TS_EACH e where e.r=h.r and e.uc=h.uc)
            and exists(select 1 from UC_DS d join TS_GROUP g on g.r=d.r and g.tsl=d.tsl where d.r=h.r and d.uc=h.uc and g.s=h.s)""")
    # --- UC_TS_EACH(R_UC,S) = NO; UC_ATTR(R_UC,SIDE,UC_GRPTYPE,UC_NAME(TSL)) = NO;
    db.remove("UC_TS_EACH", where="in_R_UC(r,uc)")
    db.remove("UC_ATTR", where="in_R_UC(r,uc) and in_TSLVL(ucn)")


def uc_attributes(db: DB):
    """ppmain.mod, user constraints: the UC_ATTR modifiers and the dynamic constraints (UC_DYNDIR, UC_T_SUCC).
    On entry the temp table t_dt holds the cumulative constraints (UC_DT)."""
    A = "UC_ATTR"
    # --- UC_DT(R_UC)$UC_DS(R_UC,'ANNUAL') = NO;
    db.x("delete from t_dt where in_R_UC(r,uc) and in_UC_DS(r,uc,'ANNUAL')")
    db.assign("UC_DT", "select r, uc from t_dt")           # the GAMS work set as it is left
    # --- UC_ATTR(UC_DT,SIDE,UC_GRPTYPE,'PERIOD')$(NOT SAMEAS(UC_GRPTYPE,'NCAP')) = NO;
    db.remove(A, where="ucn='PERIOD' and grp<>'NCAP' and exists(select 1 from t_dt d where d.r=UC_ATTR.r and d.uc=UC_ATTR.uc)")
    # --- UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,UC_COST) $= SUM(UC_MAPCOST(UC_COST,UC_NAME),UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,UC_NAME));
    db.add(A, "select a.r, a.uc, a.side, a.grp, m.ucn from UC_ATTR a join UC_MAPCOST m on m.ucn2=a.ucn")
    # --- If the GROWTH attribute is specified, substitute T_SUCC for T_EACH:
    #     LOOP(UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,'GROWTH'),UC_DYNDIR(R,UC_N,SIDE) = YES);
    db.add("UC_DYNDIR", "select distinct r, uc, side from UC_ATTR where ucn='GROWTH'")
    # --- CUMSUM (only for constraints dynamic on the RHS):
    #     UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,'PERIOD')$UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,'CUMSUM') = NOT UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,'ANNUL');
    has = lambda name, a="a": f"in_UC_ATTR({a}.r,{a}.uc,{a}.side,{a}.grp,'{name}')"
    db.tmp("t_cs", "select r, uc, side, grp, in_UC_ATTR(r,uc,side,grp,'ANNUL') as annul from UC_ATTR where ucn='CUMSUM'")
    db.remove(A, where="ucn='PERIOD' and exists(select 1 from t_cs c where c.annul and c.r=UC_ATTR.r and c.uc=UC_ATTR.uc and c.side=UC_ATTR.side and c.grp=UC_ATTR.grp)")
    db.add(A, "select r, uc, side, grp, 'PERIOD' as ucn from t_cs where not annul")
    # --- UC_ATTR(R,UC_N,SIDE,'NCAP','CUMSUM')$UC_ATTR(R,UC_N,SIDE,'NCAP','ANNUL') = YES;
    db.add(A, "select r, uc, side, grp, 'CUMSUM' as ucn from UC_ATTR where grp='NCAP' and ucn='ANNUL'")
    # --- UC_ATTR(R,UC_N,'RHS',UC_GRPTYPE,'CUM+')$(UC_ATTR(..,'SYNC')$UC_ATTR(..,'CUMSUM')) = YES;
    #     UC_ATTR(R,UC_N,'RHS',UC_GRPTYPE,'CUMSUM')$UC_ATTR(R,UC_N,'RHS',UC_GRPTYPE,'CUM+') = NO;
    db.add(A, f"select a.r, a.uc, a.side, a.grp, 'CUM+' as ucn from UC_ATTR a where a.side='RHS' and a.ucn='SYNC' and {has('CUMSUM')}")
    db.remove(A, where="side='RHS' and ucn='CUMSUM' and in_UC_ATTR(r,uc,side,grp,'CUM+')")
    # --- Set all UCs that have RHS attributes to be dynamic, if not already so defined
    #     OPTION CLEAR=RXX; LOOP(UC_ATTR(R,UC_N,'RHS',UC_GRPTYPE,UC_NAME),RXX(R,UC_N,'RHS') = YES);
    #     LOOP(T,RXX(R,UC_N,'RHS')$UC_T_SUCC(R,UC_N,T) = NO); UC_DYNDIR(RXX(R,UC_N,'RHS')) = YES;
    db.add("UC_DYNDIR", """select distinct a.r, a.uc, 'RHS' as side from UC_ATTR a where a.side='RHS'
                           and not exists(select 1 from UC_T_SUCC x where x.r=a.r and x.uc=a.uc and in_MILESTONYR(x.y))""")
    # --- LOOP(UC_ATTR(R,UC_N,SIDE,UC_GRPTYPE,UC_DYNT),UC_DYNDIR(R,UC_N,'RHS') = YES);
    db.add("UC_DYNDIR", "select distinct r, uc, 'RHS' as side from UC_ATTR where in_UC_DYNT(ucn)")
    # --- UC_ATTR(R,UC_N,'RHS',UC_GRPTYPE,'N')$UC_ATTR(R,UC_N,'RHS',UC_GRPTYPE,'SYNC') = YES;
    db.add(A, "select r, uc, side, grp, 'N' as ucn from UC_ATTR where side='RHS' and ucn='SYNC'")
    # --- Remove RHS from DYNDIR if LHS present:  UC_DYNDIR(R,UC_N,'RHS')$UC_DYNDIR(R,UC_N,'LHS') = NO;
    db.remove("UC_DYNDIR", where="side='RHS' and in_UC_DYNDIR(r,uc,'LHS')")
    # --- UC_TSL(UC_DYNDIR(R_UC,'RHS'),TSL)$UC_DS(R_UC,TSL)=YES; UC_DYNDIR(R_UC,SIDE)=NO;
    db.add("UC_TSL", """select d.r, d.uc, 'RHS' as side, s.tsl from UC_DYNDIR d join UC_DS s on s.r=d.r and s.uc=d.uc
                        where d.side='RHS' and in_R_UC(d.r,d.uc)""")
    db.remove("UC_DYNDIR", where="in_R_UC(r,uc)")
    # --- Add implicit T_SUCC and remove T_EACH whenever T_SUCC
    #     UC_T_SUCC(UC_T_EACH(R,UCN,T)) $= SUM(UC_DYNDIR(R,UCN,SIDE),1);
    db.add("UC_T_SUCC", """select e.r, e.uc, e.y from UC_T_EACH e where in_MILESTONYR(e.y)
                           and exists(select 1 from UC_DYNDIR d where d.r=e.r and d.uc=e.uc)""")
    # --- UC_T_SUCC(UC_T_EACH(R,UCN,T))$UC_R_SUM(R,UCN) $= SUM(UC_T_SUCC(UC_R_SUM(REG,UCN),T),1);
    #     (a constraint summed over regions is dynamic in all of them when it is in one)
    db.add("UC_T_SUCC", """select e.r, e.uc, e.y from UC_T_EACH e where in_MILESTONYR(e.y) and in_UC_R_SUM(e.r,e.uc)
                           and exists(select 1 from UC_T_SUCC x where x.uc=e.uc and x.y=e.y and in_REG(x.r) and in_UC_R_SUM(x.r,x.uc))""")
    # --- UC_T_EACH(UC_T_SUCC) = NO;
    db.remove("UC_T_EACH", where="in_UC_T_SUCC(r,uc,y)")
    # --- Remove last MILESTONYR from UC_T_SUCC unless RHS-based:
    #     UC_T_SUCC(UC_T_SUCC(R,UC_N,T))$(ORD(T) = CARD(T)) = UC_DYNDIR(R,UC_N,'RHS');
    db.remove("UC_T_SUCC", where="yv(y) = (select max(yv(y)) from MILESTONYR) and not in_UC_DYNDIR(r,uc,'RHS')")
