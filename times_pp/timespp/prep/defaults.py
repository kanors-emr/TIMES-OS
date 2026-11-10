# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod: SHAPE / MULTI curves and the defaults of the attributes that are not by timeslice."""
from ..engine import DB
from .common import require_empty


# ---------------------------------------------------------------------------
def shapes_and_defaults(db: DB):
    """SHAPE / MULTI, defaults of non-timeslice attributes, capacity-only flows."""
    s = db.s
    # --- MAXLIFE = SMAX(RTP,NCAP_TLIFE(RTP));
    s["MAXLIFE"] = db.q1("select coalesce(max(v_NCAP_TLIFE(r,y,p)), '-inf'::double) from RTP")
    require_empty(db, ["COM_ELASTX"], "demand elasticity shape curves (COM_ELASTX)")
    # --- STARTOFF = CEIL(MAX(MAXLIFE,SMAX(RTC_SHED(R,T,C,BD,J),COM_VOC(R,T,C,BD))*100))+1;
    import math
    s["STARTOFF"] = math.ceil(s["MAXLIFE"]) + 1
    # --- filshape.gms: inter-/extrapolation of the user SHAPE curves over AGE
    shp = {}
    for j, age, v in db.q("select j, cast(age as INTEGER), value from SHAPE"):
        shp.setdefault(j, {})[age] = v
    rows, nage = [], db.card("AGE")
    f = 0
    for j, d in shp.items():
        ages = sorted(d)
        f = ages[0]
        for a0, a1 in zip(ages, ages[1:]):
            for a in range(a0 + 1, a1):
                rows.append((j, str(a), d[a0] + (d[a1] - d[a0]) / (a1 - a0) * (a - a0)))
        rows += [(j, str(a), 1.0) for a in range(1, f)]
        rows += [(j, str(a), d[ages[-1]]) for a in range(ages[-1] + 1, min(nage, int(s["STARTOFF"])) + 1)]
    if rows:
        db.x("create or replace temp table t_shp (j VARCHAR, age VARCHAR, value DOUBLE)")
        db.insert_rows("t_shp", rows)
        db.put("SHAPE", "select j, age, value from t_shp", zero="eps")
    # --- SHAPE('1',AGE)$(ORD(AGE) LE STARTOFF) = 1.;  SHAPE(J,AGE)$((SHAPE(J,AGE) EQ 0)$SHAPE(J,AGE)) = 0;
    db.put("SHAPE", "select '1' as j, age, 1 as value from AGE where cast(age as INTEGER) <= {STARTOFF}")
    db.zap("SHAPE", "value = 0")
    # --- $BATINCLUDE filparam MULTI 'J,' '' ",'','','','',''" LL EOHYEARS 'NO$' ''      (no backward extrapolation)
    if db.card("MULTI"):
        from ..interp import filparam
        filparam(db, "MULTI", "EOHYEARS", bext=False)
        # --- LOOP(J, Z=1; LOOP(LL$(MULTI(J,LL)*Z), Z=0; F=MIN(1,MULTI(J,LL)));
        #       IF(NOT Z, MULTI(J,EOHYEARS)$(NOT MULTI(J,EOHYEARS)) = F));
        #     F: the first year of LL with a record, EPS (stored 0) included; LL ends with '0'
        first = {}
        for j, v in db.q("select j, value from MULTI order by j, y = '0', yv(y)"):
            first.setdefault(j, min(1.0, v))
        db.x("create or replace temp table t_mf (j VARCHAR, value DOUBLE)")
        db.insert_rows("t_mf", list(first.items()))
        db.put("MULTI", "select f.j, e.y, f.value from t_mf f, EOHYEARS e where not in_MULTI(f.j, e.y)", zero="eps")
    # --- MULTI('1',EACHYEAR) = 1;
    db.put("MULTI", "select '1' as j, y, 1 as value from EACHYEAR")
    # --- NCAP_ELIFE(RTP)$(NOT NCAP_ELIFE(RTP)) = NCAP_TLIFE(RTP);
    #     NOT EPS is false: an economic life given as 0 (EPS under $ONEPS) stays, as in GAMS; a
    #     life of EPS is assigned as EPS
    db.put("NCAP_ELIFE", "select r, y, p, v_NCAP_TLIFE(r,y,p) as value from RTP where not in_NCAP_ELIFE(r,y,p) and in_NCAP_TLIFE(r,y,p)",
           zero="eps")
    # --- NCAP_DLIFE(RTP(R,T,P))$((NOT NCAP_DLIFE(RTP))$SUM(RPC(R,P,C)$NCAP_OCOM(RTP,C),1)) = 1;
    db.put("NCAP_DLIFE", """select r, y, p, 1 as value from RTP k where in_MILESTONYR(y) and v_NCAP_DLIFE(r,y,p) = 0
                            and exists(select 1 from NCAP_OCOM o where o.r=k.r and o.y=k.y and o.p=k.p and in_RPC(o.r,o.p,o.c))""")
    # --- NCAP_DELIF(RTP(R,T,P))$(NOT NCAP_DELIF(RTP))$= NCAP_DLIFE(RTP);
    #     (NOT EPS is false: a value given as 0 (EPS under $ONEPS) stays)
    db.put("NCAP_DELIF", """select r, y, p, v_NCAP_DLIFE(r,y,p) as value from RTP where in_MILESTONYR(y)
                            and not in_NCAP_DELIF(r,y,p) and in_NCAP_DLIFE(r,y,p)""", zero="eps")
    # --- NCAP_CLED(RTP(R,T,P),C)$((NOT NCAP_CLED(RTP,C))$NCAP_ICOM(RTP,C)) = COEF_ILED(RTP);
    #     (NOT EPS is false: a value given as 0 (EPS under $ONEPS) stays)
    #     (a lead time given as EPS: COEF_ILED is EPS, and the copy is EPS, a record)
    db.put("NCAP_CLED", """select o.r, o.y, o.p, o.c, v_COEF_ILED(o.r,o.y,o.p) as value from NCAP_ICOM o
                           where in_MILESTONYR(o.y) and in_RTP(o.r,o.y,o.p) and not in_NCAP_CLED(o.r,o.y,o.p,o.c)
                             and (v_COEF_ILED(o.r,o.y,o.p) <> 0 or in_COEF_ILED(o.r,o.y,o.p))""", zero="eps")
    # --- NCAP_BPME(RTP(R,V,P))$((NOT NCAP_BPME(RTP))$NCAP_CDME(RTP)$CHP(R,P)) = 1;
    #     (NOT EPS is false: a value given as 0 stays EPS; pp_chp.mod 17 then takes MAX(NCAP_CDME,NCAP_BPME))
    db.put("NCAP_BPME", """select r, y, p, 1 as value from RTP where not in_NCAP_BPME(r,y,p) and in_NCAP_CDME(r,y,p) and in_CHP(r,p)""")
    # --- NCAP_CHPR(RTP(R,V,P),'UP')$((NOT SUM(LIM$NCAP_CHPR(RTP,LIM),1))$CHP(R,P)) = 1;
    db.put("NCAP_CHPR", """select r, y, p, 'UP' as l, 1 as value from RTP k where in_CHP(r,p)
                           and not exists(select 1 from NCAP_CHPR n where n.r=k.r and n.y=k.y and n.p=k.p)""")
    # --- LOOP(RP_STG(R,P)$(NOT SUM(RTP(R,T,P)$STG_EFF(RTP),1)), STG_EFF(RTP(R,V,P)) = 1);       default storage efficiency
    db.put("STG_EFF", """select k.r, k.y, k.p, 1 as value from RTP k where in_RP_STG(k.r,k.p)
                         and not exists(select 1 from STG_EFF e where e.r=k.r and e.p=k.p and in_MILESTONYR(e.y) and in_RTP(e.r,e.y,e.p))""")
    # --- UC_CAPFLO(UC_N,SIDE,RPC_NOFLO(R,P,C))$UC_ATTR(R,UC_N,SIDE,'FLO','CAPFLO') = YES;
    db.add("UC_CAPFLO", """select a.uc, a.side, n.r, n.p, n.c from RPC_NOFLO n join UC_ATTR a on a.r=n.r
                           where a.grp='FLO' and a.ucn='CAPFLO'""")
    # the equations read it as UC_CFLOW (port-only, a copy): declared only when a model has CAPFLO, so that the tables
    # of the other models stay as they are
    if db.q1("select count(*) from UC_CAPFLO"):
        db.declare("UC_CFLOW", "set", ["UC_N", "SIDE", "R", "P", "C"])
        db.add("UC_CFLOW", "select * from UC_CAPFLO")
    # --- RPC_NOFLO(RPC_PG) = NO;  RPCS_VAR(RPC_NOFLO(R,P,C),ANNUAL)$(NOT RPC(R,P,C)) = YES;
    db.remove("RPC_NOFLO", where="in_RPC_PG(r,p,c)")
    db.add("RPCS_VAR", "select r, p, c, 'ANNUAL' as s from RPC_NOFLO where not in_RPC(r,p,c)")
    # --- LOOP(TRACKPC(R,P,C), ... IF(NOT Z, RPC_NOFLO(R,P,C) = NO));     keep only commodities without any flow
    db.remove("RPC_NOFLO", where="""
        case when in_RP_IRE(r,p) then
            exists(select 1 from RPC_IRE i where i.r=RPC_NOFLO.r and i.p=RPC_NOFLO.p and i.c=RPC_NOFLO.c)
            or exists(select 1 from IRE_FLOSUM f where f.r=RPC_NOFLO.r and f.p=RPC_NOFLO.p and f.c2=RPC_NOFLO.c
                      and in_RTPC(f.r,f.y,f.p,f.c) and in_MILESTONYR(f.y) and in_RPC_IRE(f.r,f.p,f.c,f.ie))
        else
            exists(select 1 from PRC_ACTFLO a where a.r=RPC_NOFLO.r and a.p=RPC_NOFLO.p and a.cg=RPC_NOFLO.c
                   and in_MILESTONYR(a.y) and in_RTPC(a.r,a.y,a.p,a.cg))
            or exists(select 1 from FLO_FUNC f where f.r=RPC_NOFLO.r and f.p=RPC_NOFLO.p and in_MILESTONYR(f.y)
                      and (in_COM_GMAP(f.r,f.cg,RPC_NOFLO.c) or in_COM_GMAP(f.r,f.cg2,RPC_NOFLO.c)))
            or exists(select 1 from FLO_SUM f where f.r=RPC_NOFLO.r and f.p=RPC_NOFLO.p and in_MILESTONYR(f.y)
                      and (in_COM_GMAP(f.r,f.c,RPC_NOFLO.c) or in_COM_GMAP(f.r,f.cg2,RPC_NOFLO.c)))
            or exists(select 1 from FLO_SHAR f where f.r=RPC_NOFLO.r and f.p=RPC_NOFLO.p and f.c=RPC_NOFLO.c and in_MILESTONYR(f.y))
        end""")
