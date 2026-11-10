# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod: the periods and years of the model, past investments, start years of new processes."""
from ..engine import DB
from .common import require_empty, setup_helpers, rnd, _values
from .storage import storage_classification


def topology_control_sets(db: DB):
    """ppmain.mod from the top: the SQL helpers, RDCUR, the control sets of regions, processes and commodities (RPC_IRE,
    TOP, RPC, RP, RP_PG), and the sets of the storage processes."""
    setup_helpers(db)

    # --- LOOP((R,LL(BOHYEAR),CUR)$G_DRATE(R,LL,CUR), RDCUR(R,CUR) = YES);
    db.add("RDCUR", "select r, cur from G_DRATE where in_BOHYEAR(y) and in_REG(r)")

    # ------------------------------------------------------------------
    # initial region/process/commodity control sets
    # --- PRC_ACTUNT(R,P,%PGPRIM%,UNITS_ACT) = NO;
    db.remove("PRC_ACTUNT", where="cg = 'ACT'")
    # --- OPTION RPC_AIRE <  TOP_IRE; RPC_IRE(RPC_AIRE,'IMP') = YES;   (right-most match: importing side)
    db.add("RPC_IRE", "select r2 as r, p, c2 as c, 'IMP' as ie from TOP_IRE")
    # --- OPTION RPC_AIRE <= TOP_IRE; RPC_IRE(RPC_AIRE,'EXP') = YES;   (left-most match: exporting side)
    db.add("RPC_IRE", "select r, p, c, 'EXP' as ie from TOP_IRE")
    # --- OPTION CLEAR=RPC_AIRE, PRC_ACT < PRC_ACTUNT;
    db.clear("RPC_AIRE")
    db.assign("PRC_ACT", "select distinct r, p from PRC_ACTUNT")
    # --- RP_IRE(ALL_R,P)$SUM(RPC_IRE(ALL_R,P,C,IE),1) = YES;
    db.add("RP_IRE", "select distinct r, p from RPC_IRE")
    # --- TOP(RP_IRE(R,P),C,'IN')$RPC_IRE(R,P,C,'EXP') = NO;  TOP(RP_IRE(R,P),C,'OUT')$RPC_IRE(R,P,C,'IMP') = NO;
    db.remove("TOP", where="io='IN'  and in_RP_IRE(r,p) and in_RPC_IRE(r,p,c,'EXP')")
    db.remove("TOP", where="io='OUT' and in_RP_IRE(r,p) and in_RPC_IRE(r,p,c,'IMP')")
    # --- TOP(RPG_RED(PRC_ACT(R,P),C,IO))$(COM_TMAP(R,'ENV',C)+RP_IRE(R,P)) = YES;
    db.add("TOP", """select r, p, cg as c, io from RPG_RED
                     where in_PRC_ACT(r,p) and in_COM(cg) and (in_COM_TMAP(r,'ENV',cg) or in_RP_IRE(r,p))""")
    # --- RPC(R,P,C)$(SUM(TOP(R,P,C,IO),1) + SUM(RPC_IRE(R,P,C,IE),1)) = YES;
    db.add("RPC", """select r,p,c from TOP union select r,p,c from RPC_IRE where in_REG(r)""")
    # --- RC(R,C)$SUM(RPC(R,P,C),1) = YES;  RP(R,P)$SUM(RPC(R,P,C),1) = YES;  RP_FLO(RP)$(NOT RP_IRE(RP)) = YES;
    db.add("RC", "select distinct r, c from RPC")
    db.add("RP", "select distinct r, p from RPC")
    db.add("RP_FLO", "select r, p from RP where not in_RP_IRE(r,p)")

    # establish PCG, checking for missing ones
    # --- OPTION RP_PG < PRC_ACTUNT, CLEAR=RPG_RED, CLEAR=PRC_ACT;
    db.assign("RP_PG", "select distinct r, p, cg from PRC_ACTUNT")
    db.clear("RPG_RED", "PRC_ACT")
    # --- PRC_ACT(RP)$(NOT SUM(RP_PG(RP,CG),1))=YES;
    db.add("PRC_ACT", "select r, p from RP where not exists(select 1 from RP_PG g where g.r=RP.r and g.p=RP.p)")
    if db.card("PRC_ACT"):
        # --- TRACKPC(PRC_ACT(R,P),C)$((NOT COM_TMAP(R,'ENV',C)+COM_TMAP(R,'FIN',C))$TOP(R,P,C,'OUT'))=YES;
        db.assign("TRACKPC", """select a.r, a.p, t.c from PRC_ACT a join TOP t on t.r=a.r and t.p=a.p and t.io='OUT'
                                where not (in_COM_TMAP(a.r,'ENV',t.c) or in_COM_TMAP(a.r,'FIN',t.c))""")
        # --- PRC_ACT(RP)$(SUM(TRACKPC(RP,C),1) NE 1)=NO; RP_PG(TRACKPC(PRC_ACT,C))=YES;
        db.remove("PRC_ACT", where="(select count(*) from TRACKPC k where k.r=PRC_ACT.r and k.p=PRC_ACT.p) <> 1")
        db.add("RP_PG", "select r, p, c as cg from TRACKPC k where in_PRC_ACT(r,p)")
        db.clear("PRC_ACT", "TRACKPC")
    # --- COM_GMAP(COM_TMAP) = YES;
    db.add("COM_GMAP", "select r, cg, c from COM_TMAP")

    storage_classification(db)


def periods_and_years(db: DB):
    """ppmain.mod: PASTYEAR, the periods (B, E, D, M, LEAD, LAGT, IPD), the year sets of the horizon, G_OFFTHD."""
    x, s = db.x, db.s
    # ------------------------------------------------------------------
    # spread NCAP_PASTI and determine PASTYEAR
    # --- OPTION PRC_CAP < NCAP_PASTY, PASTYEAR < NCAP_PASTY;
    # --- LOOP((PRC_CAP(RP(R,P)),PASTYEAR(LL))$(NCAP_PASTY(R,PASTYEAR,P) > 1),
    # ---      F = ROUND(NCAP_PASTY(R,LL,P)); MY_F = NCAP_PASTI(R,LL,P) / F;
    # ---      FOR(Z = F-1 DOWNTO 0, PASTSUM(R,ALLYEAR(LL-Z),P) = PASTSUM(R,ALLYEAR,P) + MY_F);
    # ---      NCAP_PASTI(R,LL,P) = 0);
    # PASTYEAR is here the years of NCAP_PASTY: every year with a spread is spread.  F is a whole number of years
    # (ROUND: 2.5 -> 3); a year before BOTIME is not in ALLYEAR and gets nothing.
    spread = db.q("""select y.r, y.y, y.p, y.value, i.value from NCAP_PASTY y join RP using (r, p)
                     left join NCAP_PASTI i using (r, y, p)
                     where y.value > 1 order by y.r, y.p, yv(y.y)""")
    if spread:
        years = {v for (v,) in db.q("select y from ALLYEAR")}
        pastsum = {}                                     # (r, y, p) -> value; a value of 0 is EPS
        for r, y, p, f, pasti in spread:
            f = rnd(f)
            my_f = None if pasti is None else pasti / f  # None: no record (0); 0.0: EPS
            z = f - 1
            while z >= 0:
                yl = str(int(y) - z)
                if yl in years and (my_f or (r, yl, p) in pastsum or my_f == 0.0):
                    pastsum[(r, yl, p)] = pastsum.get((r, yl, p), 0.0) + (my_f or 0.0)    # 0 + EPS = EPS
                z -= 1
        db.remove("NCAP_PASTI", select=_values([(r, y, p) for r, y, p, *_ in spread], ["r", "y", "p"]))
        # --- NCAP_PASTI(R,LL,P)$PASTSUM(R,LL,P) = NCAP_PASTI(R,LL,P) + PASTSUM(R,LL,P);
        old = {(r, y, p): v for r, y, p, v in db.q("select r, y, p, value from NCAP_PASTI")}
        new = [(r, y, p, old.get((r, y, p), 0.0) + v) for (r, y, p), v in pastsum.items()]
        if new:
            db.put("NCAP_PASTI", _values(new, ["r", "y", "p", "value"]), zero="eps")
    # --- OPTION PASTYEAR < NCAP_PASTI;
    db.assign("PASTYEAR", "select distinct y from NCAP_PASTI")
    # --- INT_DEFAULT('PASTI')$PYR('0')=1; PYR('0')=NO;
    pasti_migrate = bool(db.q1("select count(*) from PASTYEAR where y='0'"))
    db.pasti_migrate = pasti_migrate        # read by past_vintages_and_start_years, after the timeslices
    db.remove("PASTYEAR", where="y='0'")
    if pasti_migrate:
        db.add("INT_DEFAULT", "select 'PASTI' as u")

    # ------------------------------------------------------------------
    # determination of YEAR subsets and period B/E/D
    # --- D(MILESTONYR)=E-B+1;  M(MILESTONYR)=FLOOR(B+(D-1)/2);
    db.put("D", "select y, v_E(y) - v_B(y) + 1 as value from MILESTONYR")
    db.put("M", "select y, floor(v_B(y) + (v_D(y)-1)/2) as value from MILESTONYR")
    if db.ctl["OBJ"] == "MOD":
        db.zap("M", "in_MILESTONYR(y)")
    # --- IF(ALTOBJ=1,ALTOBJ=1$SUM(T,M(T) NE YEARVAL(T)));
    if s["ALTOBJ"] == 1:
        s["ALTOBJ"] = 1.0 if db.q1("select count(*) from MILESTONYR where v_M(y) <> yv(y)") else 0.0
    # --- MIYR_1(T)$(ORD(T) = 1) = YES;
    db.assign("MIYR_1", "select y from MILESTONYR order by yv(y) limit 1")
    if s["ALTOBJ"]:
        # --- IF(ALTOBJ, E(T(TT-1)) = FLOOR((YEARVAL(T)+YEARVAL(TT))/2); B(T(TT+1)) = E(TT)+1;
        x("create or replace temp table t_nx as select y, lead(y) over (order by yv(y)) as nxt, lag(y) over (order by yv(y)) as prv from MILESTONYR")
        db.put("E", "select y, floor((yv(y) + yv(nxt)) / 2) as value from t_nx where nxt is not null")
        db.put("B", "select y, v_E(prv) + 1 as value from t_nx where prv is not null")
        # ---   B(MIYR_1(T))$(ABS(B(T)-(YEARVAL(T)-5)) GT 5) = YEARVAL(T);
        db.put("B", "select y, yv(y) as value from MIYR_1 where abs(v_B(y) - (yv(y) - 5)) > 5")
        # ---   E(T)$((ABS(E(T)-(YEARVAL(T)+15)) GT 15)$(ORD(T)=CARD(T))) = 2*YEARVAL(T)-B(T)+1-1$MOD(YEARVAL(T)-B(T)+1,5);
        db.put("E", """select y, 2 * yv(y) - v_B(y) + 1 - (case when (yv(y) - v_B(y) + 1) % 5 <> 0 then 1 else 0 end) as value
                       from t_nx where nxt is null and abs(v_E(y) - (yv(y) + 15)) > 15""")
        # ---   D(T)=E(T)-B(T)+1; M(T) = YEARVAL(T));
        db.put("D", "select y, v_E(y) - v_B(y) + 1 as value from MILESTONYR")
        db.put("M", "select y, yv(y) as value from MILESTONYR")
    # --- MIYR_V1 = SMIN(MIYR_1, B(MIYR_1));  MIYR_VL = SMAX(T$(ORD(T) = CARD(T)), E(T));
    s["MIYR_V1"] = db.q1("select min(v_B(y)) from MIYR_1")
    s["MIYR_VL"] = db.q1("select v_E(y) from MILESTONYR order by yv(y) desc limit 1")
    # --- $IFI '%OBLONG%'==YES IF(MIYR_V1+SUM(T,E(T)+1-B(T))-MIYR_VL NE 1,ABORT ...
    if db.ctl["OBLONG"]:
        if s["MIYR_V1"] + db.q1("select sum(v_E(y)+1-v_B(y)) from MILESTONYR") - s["MIYR_VL"] != 1:
            raise ValueError("Inconsistent periods - cannot use OBLONG.")
    # --- LOOP(MIYR_1(LL),PASTYEAR(LL-(YEARVAL(LL)-MIYR_V1+1)) = YES);
    db.add("PASTYEAR", "select ys({MIYR_V1}-1) as y where in_ALLYEAR(ys({MIYR_V1}-1))")
    # --- LEAD(TT(T++1)) = MAX(M(TT)-M(T),M(TT)-B(TT)+1);   LAGT(TT(T--1)) = MAX(M(T)-M(TT),E(TT)-M(TT)+1);
    x("""create or replace temp table t_seq as
         select y, coalesce(lag(y) over w, last_value(y) over (order by yv(y) rows between unbounded preceding and unbounded following)) as prv,
                   coalesce(lead(y) over w, first_value(y) over (order by yv(y) rows between unbounded preceding and unbounded following)) as nxt
         from MILESTONYR window w as (order by yv(y))""")
    db.put("LEAD", "select y, greatest(v_M(y)-v_M(prv), v_M(y)-v_B(y)+1) as value from t_seq")
    db.put("LAGT", "select y, greatest(v_M(nxt)-v_M(y), v_E(y)-v_M(y)+1) as value from t_seq")
    # --- IF(ALTOBJ,IPD(T) = LEAD(T)+MIN(E(T)-M(T),LEAD(T)-1)$MIYR_1(T); ELSE IPD(T) = D(T)); FPD(T) = D(T);
    if s["ALTOBJ"]:
        db.put("IPD", "select y, v_LEAD(y) + (case when in_MIYR_1(y) then least(v_E(y) - v_M(y), v_LEAD(y) - 1) else 0 end) as value from MILESTONYR")
    else:
        db.put("IPD", "select y, v_D(y) as value from MILESTONYR")
    db.put("FPD", "select y, v_D(y) as value from MILESTONYR")
    # --- MINYR = MIN(MIYR_V1-1,SMIN(T,M(T)-IPD(T))+1);  PYR_V1 = MIN(SMIN(PASTYEAR,YEARVAL(PASTYEAR)),MINYR);
    s["MINYR"] = min(s["MIYR_V1"] - 1, db.q1("select min(v_M(y)-v_IPD(y)) from MILESTONYR") + 1)
    pmin = db.q1("select min(yv(y)) from PASTYEAR")
    s["PYR_V1"] = min(pmin, s["MINYR"]) if pmin is not None else s["MINYR"]
    # --- LOOP(MIYR_1(ALLYEAR), Z=MIYR_VL-YEARVAL(ALLYEAR); MIYR_L(ALLYEAR+Z) = YES);
    db.assign("MIYR_L", "select ys({MIYR_VL}) as y where in_ALLYEAR(ys({MIYR_VL}))")
    # --- PASTMILE(PASTYEAR)$((YEARVAL(PASTYEAR) LE MIYR_VL)$(NOT T(PASTYEAR))) = YES;  M/B/E = YEARVAL; D = 1
    db.add("PASTMILE", "select y from PASTYEAR where yv(y) <= {MIYR_VL} and not in_MILESTONYR(y)")
    for p in ("M", "B", "E"):
        db.put(p, "select y, yv(y) as value from PASTMILE")
    db.put("D", "select y, 1 as value from PASTMILE")
    # --- EOHYEARS(ALLYEAR)$((YEARVAL(ALLYEAR) >= MINYR) * (YEARVAL(ALLYEAR) <= MIYR_VL)) = YES;
    db.add("EOHYEARS", "select y from ALLYEAR where yv(y) >= {MINYR} and yv(y) <= {MIYR_VL}")
    # --- PERIODYR(T,EOHYEARS)$((YEARVAL(EOHYEARS) >= B(T)) * (YEARVAL(EOHYEARS) <= E(T))) = YES;
    db.add("PERIODYR", """select t.y as y, e.y as y2 from MILESTONYR t, EOHYEARS e
                          where yv(e.y) >= v_B(t.y) and yv(e.y) <= v_E(t.y)""")
    # --- $IF DEFINED G_OFFTHD $BATINCLUDE filparam G_OFFTHD '' '' ",'','','','','',''" YEAR T '' '' 5;  G_OFFTHD('0') = 0;
    from ..interp import filparam
    filparam(db, "G_OFFTHD", "T", default=5)
    db.zap("G_OFFTHD", "y='0'")


def past_vintages_and_start_years(db: DB):
    """ppmain.mod after timslice.mod: past investments on milestone years moved to past years (INT_DEFAULT('PASTI')),
    the start years of new investments (NCAP_START, PRC_NOFF -> RTP_OFF), RTP and RVP."""
    pasti_migrate = db.pasti_migrate        # set by periods_and_years
    # --- Migrate PASTIs defined on Milestonyr if requested: IF(INT_DEFAULT('PASTI'), ...   (guarded above)
    #     LOOP(PYR(T(LL))$(M(T)>B(T)), VNT(LL-1,T)=YES); ...
    #     Nothing moves unless a past investment sits on a milestone year that is not the first year of its period.
    if pasti_migrate:
        # --- LOOP(PYR(T(LL))$(M(T)>B(T)), VNT(LL-1,T)=YES);
        db.add("VNT", "select ys(yv(y)-1) as y, y as y2 from PASTYEAR where in_MILESTONYR(y) and v_M(y) > v_B(y)")
        # --- LOOP(VNT(LL,T), B(LL)=M(T)-1; E(LL)=M(T); M(LL)=B(LL); D(LL)=2; PASTYEAR(T)=NO;
        db.tmp("t_mig", "select y as ll, y2 as t from VNT")
        db.put("B", "select ll as y, v_M(t) - 1 as value from t_mig")
        db.put("E", "select ll as y, v_M(t) as value from t_mig")
        db.put("M", "select ll as y, v_B(ll) as value from t_mig")
        db.put("D", "select ll as y, 2 as value from t_mig")
        db.remove("PASTYEAR", where="y in (select t from t_mig)")
        # ---   PASTSUM(R,T,P)$NCAP_PASTI(R,T,P) = NCAP_PASTI(R,LL,P)+NCAP_PASTI(R,T,P)+1-1;
        #       COEF_RTP(R,LL,P)$PASTSUM(R,T,P)  = NCAP_PASTI(R,T,P) / PASTSUM(R,T,P);
        #       NCAP_PASTI(R,LL,P)$=PASTSUM(R,T,P); NCAP_PASTI(R,T,P)=0; OPTION CLEAR=PASTSUM);
        db.tmp("t_psum", """select n.r, m.ll, m.t, n.p, n.value as vt, ((v_NCAP_PASTI(n.r,m.ll,n.p) + n.value) + 1) - 1 as value
                            from NCAP_PASTI n join t_mig m on m.t = n.y""")
        #       "+1-1" is kept as GAMS evaluates it: 0.0009+1-1 is not 0.0009, and the share COEF_RTP of 1.0000000000001
        #       that follows makes NCAP_ILED of the migrated vintage exceed 1 - one more year of life
        #       an EPS past investment on the milestone year (a 0 in a DD file) gives an EPS share: COEF_RTP exists and
        #       NCAP_ILED of the migrated vintage becomes EPS (ppmain.mod 482)
        db.put("COEF_RTP", "select r, ll as y, p, vt / value as value from t_psum where value <> 0", zero="eps")
        db.put("NCAP_PASTI", "select r, ll as y, p, value from t_psum", zero="skip")
        db.zap("NCAP_PASTI", "y in (select t from t_mig)")
        # --- VNT(PASTMILE,T)$PERIODYR(T,PASTMILE)=YES;
        db.add("VNT", "select p.y2 as y, p.y as y2 from PERIODYR p where in_MILESTONYR(p.y) and in_PASTMILE(p.y2)")
        # --- OPTION PHYR<=VNT; PYR(PHYR)=YES; PASTMILE(PHYR)=YES);
        db.assign("PHYR", "select distinct y from VNT")
        db.add("PASTYEAR", "select y from PHYR")
        db.add("PASTMILE", "select y from PHYR")

    # ------------------------------------------------------------------
    # initialize start/end year for new investments
    # --- LOOP(LASTLL(LL)$CARD(NCAP_START), Z=CARD(LL)+%BOTIME%;
    #       PRC_NOFF(RP,'BOH',EOHYEAR)$NCAP_START(RP) = NO;
    #       PRC_NOFF(RP,'BOH',LL+MIN(-1,NCAP_START(RP)-Z))$NCAP_START(RP) = YES);
    db.assign("LASTLL", "select '0' as y")
    if db.card("NCAP_START"):
        db.remove("PRC_NOFF", where="u='BOH' and in_RP(r,p) and in_NCAP_START(r,p)")
        # position CARD(LL)+MIN(-1,START-Z) in ALLYEAR is the year START-1
        db.add("PRC_NOFF", """select r, p, 'BOH' as u, ys(value-1) as u2 from NCAP_START
                              where in_RP(r,p) and in_ALLYEAR(ys(value-1)) and value-1 >= {BOT}""".replace("{BOT}", str(db.ctl["BOTIME"])))
    # --- UNCD1('BOH') = YES; UNCD1(YEAR)$(YEARVAL(YEAR) LE MIYR_V1) = YES;
    # --- PRC_YMAX(RP(R,P)) = MAX(0,SMAX(PRC_NOFF(R,P,BOHYEAR(UNCD1),EOHYEAR),ORD(EOHYEAR)+%BOTIME%-2));
    eoh = db.ctl["EOTIME"] + 1          # ORD('EOH')+BOTIME-2
    db.clear("PRC_YMAX")
    db.put("PRC_YMAX", f"""select r, p, greatest(0, max(case when u2='EOH' then {eoh} else yv(u2) end)) as value
                           from PRC_NOFF where in_RP(r,p) and (u='BOH' or (in_ALLYEAR(u) and yv(u) <= {{MIYR_V1}}))
                           group by r, p""")
    # --- TRACKP(RP) $= PRC_YMAX(RP);
    db.assign("TRACKP", "select r, p from PRC_YMAX")
    # --- RTP_OFF(R,T,P)$((YEARVAL(T) LE PRC_YMAX(R,P))$TRACKP(R,P)) = ((PRC_YMAX(R,P)-B(T)+1)/D(T) GE G_OFFTHD(T));
    db.add("RTP_OFF", """select k.r, t.y, k.p from TRACKP k, MILESTONYR t
                         where yv(t.y) <= v_PRC_YMAX(k.r,k.p)
                           and (v_PRC_YMAX(k.r,k.p) - v_B(t.y) + 1) / v_D(t.y) >= v_G_OFFTHD(t.y)""")
    # --- PRC_YMAX(TRACKP(R,P)) = SMAX(RTP_OFF(R,T,P),E(T));
    db.put("PRC_YMAX", """select k.r, k.p, coalesce((select max(v_E(o.y)) from RTP_OFF o where o.r=k.r and o.p=k.p and in_MILESTONYR(o.y)),
                                                    '-inf'::double) as value from TRACKP k""")
    # --- Check NCAP_PASTI: delayed process with past investment -> delay ignored
    rows = db.q("""select k.r, k.p from TRACKP k where v_PRC_YMAX(k.r,k.p) > 0
                   and exists(select 1 from NCAP_PASTI n where n.r=k.r and n.p=k.p and in_PASTYEAR(n.y))""")
    for r, p in rows:
        db.log.append(f"*01 WARNING - Delayed Process but PASTInvestment; delay is ignored: R={r} P={p}")
    if rows:
        db.zap("PRC_YMAX", """exists(select 1 from NCAP_PASTI n where n.r=PRC_YMAX.r and n.p=PRC_YMAX.p and in_PASTYEAR(n.y))
                              and value > 0 and in_TRACKP(r,p)""")
    db.clear("TRACKP")
    # --- Set the RTP_OFF for all remaining PRC_NOFF ranges  (pp_off.mod)
    # FIL = EOHYEARS inside [BOHYEAR, EOHYEAR];  RTP_OFF(R,T,P)$((SUM(PERIODYR(T,FIL),1)/D(T) GE G_OFFTHD(T))$FIL(T)) = YES
    db.add("RTP_OFF", """
        with late as (select distinct r, p from PRC_NOFF where in_RP(r,p) and in_ALLYEAR(u) and yv(u) > {MIYR_V1}),
             rng as (select n.r, n.p, case when n.u='BOH' then -1e9 else yv(n.u) end as y0,
                            case when n.u2='EOH' then 1e9 else yv(n.u2) end as y1
                     from PRC_NOFF n join late l on l.r=n.r and l.p=n.p),
             fil as (select distinct g.r, g.p, e.y from rng g, EOHYEARS e where yv(e.y) >= g.y0 and yv(e.y) <= g.y1)
        select f.r, t.y, f.p from fil f join MILESTONYR t on t.y = f.y
        where (select count(*) from PERIODYR py join fil f2 on f2.r=f.r and f2.p=f.p and f2.y=py.y2 where py.y=t.y) / v_D(t.y)
              >= v_G_OFFTHD(t.y)""")
    # --- RTP(R,T,P)$RP(R,P) = YES$(YEARVAL(T) GT PRC_YMAX(R,P));
    db.add("RTP", "select k.r, t.y, k.p from RP k, MILESTONYR t where yv(t.y) > v_PRC_YMAX(k.r,k.p)")
    # --- RTP(R,PYR,P)$(RP(R,P)$(NCAP_PASTI(R,PYR,P)>0)$NCAP_PASTI(R,PYR,P)) = YES;
    db.add("RTP", "select r, y, p from NCAP_PASTI where in_PASTYEAR(y) and in_RP(r,p) and value > 0")
    # --- RVP(RTP(R,T,P)) = YES;
    db.add("RVP", "select r, y, p from RTP where in_MILESTONYR(y)")


# ---------------------------------------------------------------------------
def horizon_years(db: DB):
    s = db.s
    # --- SET SUBT(T) / SET.T /;  RT_PP(R,T) = YES;
    db.assign("SUBT", "select y from MILESTONYR")
    db.assign("RT_PP", "select r, y from REG, MILESTONYR")
    # --- DUR_MAX=MAX(G_TLIFE,SMAX(RVP(R,T,P),NCAP_ILED+NCAP_TLIFE+NCAP_DLAG+NCAP_DLIFE+NCAP_DELIF));
    m = db.q1("""select max(v_NCAP_ILED(r,y,p)+v_NCAP_TLIFE(r,y,p)+v_NCAP_DLAG(r,y,p)+v_NCAP_DLIFE(r,y,p)+v_NCAP_DELIF(r,y,p))
                 from RVP where in_MILESTONYR(y)""")
    s["DUR_MAX"] = max(s["G_TLIFE"], m if m is not None else float("-inf"))
    # --- EOHYEARS(PYR)$(YEARVAL(PYR)<MINYR) = YES;
    db.add("EOHYEARS", "select y from PASTYEAR where yv(y) < {MINYR}")
    # --- EACHYEAR(PASTYEAR) = YES;  EACHYEAR(ALLYEAR)$((YEARVAL >= MINYR) * (YEARVAL <= (MIYR_VL+DUR_MAX))) = YES;
    db.add("EACHYEAR", "select y from PASTYEAR")
    db.add("EACHYEAR", "select y from ALLYEAR where yv(y) >= {MINYR} and yv(y) <= {MIYR_VL} + {DUR_MAX}")
    # --- PERIODYR(T,EACHYEAR)$((E(T)=MIYR_VL)*(YEARVAL(EACHYEAR) >= MIYR_VL)) = YES;      (late costs)
    db.add("PERIODYR", """select t.y, e.y as y2 from MILESTONYR t, EACHYEAR e
                          where v_E(t.y) = {MIYR_VL} and yv(e.y) >= {MIYR_VL}""")
