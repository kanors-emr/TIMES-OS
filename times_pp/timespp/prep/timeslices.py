# SPDX-License-Identifier: GPL-3.0-or-later
"""timslice.mod and the timeslice levels of ppmain.mod: the timeslices of commodities, processes and flow
variables, and the fractions of the year."""
from ..controls import unsupported
from ..engine import DB
from .common import off_years
from . import elastic


def timeslices(db: DB):
    """timslice.mod"""
    x, s = db.x, db.s
    # --- TS_GROUP(ALL_R,'ANNUAL',S) = ANNUAL(S);
    db.remove("TS_GROUP", where="tsl='ANNUAL' and s<>'ANNUAL'")
    db.add("TS_GROUP", "select r, 'ANNUAL' as tsl, 'ANNUAL' as s from ALL_REG")
    # --- OPTION STOAL < TS_GROUP;     (count of levels each timeslice is on)
    db.clear("STOAL")
    db.put("STOAL", "select r, s, count(*) as value from TS_GROUP group by r, s")
    # --- TS_MAP(R,ANNUAL,S) = STOAL(R,S);
    db.remove("TS_MAP", where="in_REG(r) and s='ANNUAL' and not in_STOAL(r,s2)")
    db.add("TS_MAP", "select r, 'ANNUAL' as s, s as s2 from STOAL where in_REG(r)")
    # --- TS_MAP(R,ALL_TS,TS)$SUM(TS_MAP(R,ALL_TS,S),TS_MAP(R,S,TS)) = YES;
    db.add("TS_MAP", "select a.r, a.s, b.s2 from TS_MAP a join TS_MAP b on b.r=a.r and b.s=a.s2 where in_REG(a.r)")
    # --- TS_MAP(R,S,S) = STOAL(R,S);
    db.remove("TS_MAP", where="in_REG(r) and s=s2 and not in_STOAL(r,s)")
    db.add("TS_MAP", "select r, s, s as s2 from STOAL where in_REG(r)")
    # --- STOAL(ALL_R,S)$STOAL(ALL_R,S) = STOAL(ALL_R,S)-1;  IF(CARD(STOAL),ABORT "Error: Timeslice on several levels.");
    db.put("STOAL", "select r, s, value-1 as value from STOAL")
    if db.card("STOAL"):
        raise ValueError("Error: Timeslice on several levels.")
    # --- RS_BELOW(TS_MAP(R,S,TS))$(NOT TS_MAP(R,TS,S)) = YES;
    db.add("RS_BELOW", "select r, s, s2 from TS_MAP m where in_REG(r) and not in_TS_MAP(r, s2, s)")
    # --- RS_BELOW1(RS_BELOW(R,S,TS))$(SUM(TS_MAP(R,S,ALL_TS)$RS_BELOW(R,ALL_TS,TS),1)=1) = YES;
    db.add("RS_BELOW1", """select r, s, s2 from RS_BELOW b
                           where (select count(*) from TS_MAP m where m.r=b.r and m.s=b.s and in_RS_BELOW(b.r, m.s2, b.s2)) = 1""")
    # --- $SET MX '(MIYR_1)' SETGLOBAL RTS S   ($IFI %OBMAC%%DYNTS%==YESYES  dynamic trees: MX '', RTS S+NORTS(R,T,S))
    #     LOOP(RS_BELOW1(R,ANNUAL,S)$SUM(TS_OFF(R,S,BOHYEAR,EOHYEAR),1), pp_off.mod TS_OFF S "" "NORTS(R,T%MX%,S)$(" 1
    #       IF(PROD(T%MX%,FIL(T)),G_YRFR(R,TS)$TS_MAP(R,S,TS) = 0;
    #       ELSE NORTS(R,T(FIL%MX%),TS)$TS_MAP(R,S,TS) = -INF));
    #     Without DYNTS: a season off in the first period (FIL: the years of its OFF ranges) has no year fraction, it and
    #     the timeslices below it go with the others of none; an OFF range after the first period does nothing (the
    #     ELSE needs FIL(MIYR_1), and NORTS of the first period is cleared below with the timeslices of no fraction).
    #     With DYNTS (MX ''): a season off in every period has no year fraction; otherwise NORTS is -INF for it and the
    #     timeslices below it in each milestone year of its OFF ranges (the threshold G_OFFTHD of pp_off.mod gives only
    #     the NORTS 1 of the season itself, overwritten by the -INF or cleared with the timeslices of no fraction).
    if db.card("TS_OFF"):
        yr = lambda c, e, d: f"(case when o.{c}='{e}' then {d} else yv(o.{c}) end)"
        if dynts(db):
            x(f"""create or replace temp table dyn_fil as
                  select distinct o.r, o.s, t.y from TS_OFF o join RS_BELOW1 b on b.r=o.r and b.s='ANNUAL' and b.s2=o.s, MILESTONYR t
                  where yv(t.y) >= {yr('y', 'BOH', -1e9)} and yv(t.y) <= {yr('y2', 'EOH', 1e9)}""")
            x("""create or replace temp table dyn_all as
                 select r, s from dyn_fil group by r, s having count(*) = (select count(*) from MILESTONYR)""")
            db.zap("G_YRFR", "(r, s) in (select m.r, m.s2 from dyn_all a join TS_MAP m on m.r=a.r and m.s=a.s)")
            db.put("NORTS", """select f.r, f.y, m.s2 as s, cast('-inf' as DOUBLE) as value from dyn_fil f join TS_MAP m on m.r=f.r and m.s=f.s
                               where not exists(select 1 from dyn_all a where a.r=f.r and a.s=f.s)""")
        else:
            db.zap("G_YRFR", f"""(r, s) in (select m.r, m.s2 from TS_OFF o join RS_BELOW1 b on b.r=o.r and b.s='ANNUAL' and b.s2=o.s
                                            join TS_MAP m on m.r=o.r and m.s=o.s, MIYR_1 t
                                            where yv(t.y) >= {yr('y', 'BOH', -1e9)} and yv(t.y) <= {yr('y2', 'EOH', 1e9)})""")
    # --- G_YRFR(ALL_R,ANNUAL) = 1;
    db.put("G_YRFR", "select r, 'ANNUAL' as s, 1 as value from ALL_REG")
    # --- G_YRFR(R,S)$((G_YRFR(R,S)<=0)$TS_GROUP(R,'WEEKLY',S)) $= SUM(RS_BELOW1(R,S,TS),G_YRFR(R,TS));   then SEASON
    for lvl in ("WEEKLY", "SEASON"):
        db.put("G_YRFR", f"""select g.r, g.s, (select sum(v_G_YRFR(b.r,b.s2) order by ord_s(b.s2)) from RS_BELOW1 b where b.r=g.r and b.s=g.s) as value
                             from TS_GROUP g where g.tsl='{lvl}' and in_REG(g.r) and v_G_YRFR(g.r,g.s) <= 0""", zero="skip")
    # --- LOOP(TSL,FINEST(R,S)$((G_YRFR(R,S)<=0)$TS_GROUP(R,TSL,S)) = YES);  -> drop timeslices without a year fraction
    db.assign("FINEST", "select distinct r, s from TS_GROUP where in_REG(r) and v_G_YRFR(r,s) <= 0")
    db.remove("TS_GROUP", where="in_FINEST(r,s)")
    db.remove("TS_MAP", where="in_FINEST(r,s2)")
    db.remove("RS_BELOW", where="in_FINEST(r,s2)")
    db.remove("RS_BELOW1", where="in_FINEST(r,s2)")
    db.zap("NORTS", "in_FINEST(r,s)")
    db.clear("FINEST")
    # --- RS_TREE(R,S,TS)$(TS_MAP(R,TS,S) OR RS_BELOW(R,S,TS)) = YES;
    db.add("RS_TREE", "select r, s2 as s, s as s2 from TS_MAP where in_REG(r) union select r, s, s2 from RS_BELOW")
    # --- FINEST(R,S)$(SUM(TS_MAP(R,S,TS),1)=1) = YES;
    db.add("FINEST", "select r, s from TS_MAP where in_REG(r) group by r, s having count(*) = 1")
    # --- LOOP(SAMEAS('5',J),RJLVL(J-ORD(TSL),R,TSL)=SUM(TS_GROUP(R,TSL,S),1));
    db.add("RJLVL", "select distinct cast(5 - ord_tsl(tsl) as VARCHAR) as j, r, tsl from TS_GROUP where in_REG(r)")
    # --- RLUP(R,TSL,TSLVL): TSLVL is the next coarser level present in the region
    db.add("RLUP", """select a.r, a.tsl, (select b.tsl from RJLVL b where b.r=a.r and ord_tsl(b.tsl) < ord_tsl(a.tsl)
                                           order by ord_tsl(b.tsl) desc limit 1) as tsl2
                      from RJLVL a where ord_tsl(a.tsl) > 1""")
    db.remove("RLUP", where="tsl2 is null")
    # --- normalise year fractions, top-down:
    #     LOOP(TS_GROUP(R,TSL,S)$(NOT FINEST(R,S)), MY_F=G_YRFR(R,S); MY_SUM=SUM(RS_BELOW1(R,S,TS),G_YRFR(R,TS));
    #       F=ABS(MY_F-MY_SUM); IF(F*Z>1,G_YRFR(R,TS)$RS_BELOW1(R,S,TS)=MY_F/MY_SUM*G_YRFR(R,TS)))
    #     ANNUAL with dynamic trees (IF(ANNUAL(S)$CARD(NORTS)): in each milestone year in order, the seasons on in it
    #     that have no RS_HR yet share what those with one leave of the year, in proportion to G_YRFR; G_YRFR $= RS_HR.
    Z = 8760 * 3600
    if db.card("NORTS"):
        if not dynts(db):
            unsupported(db, "dynamic timeslices (NORTS)")
        dyn_annual(db, Z)
    for lvl in ("ANNUAL", "SEASON", "WEEKLY", "DAYNITE"):
        if lvl == "ANNUAL" and db.card("NORTS"):
            continue
        x(f"""create or replace temp table ts_fix as
              select g.r, g.s, v_G_YRFR(g.r,g.s) as f, (select sum(v_G_YRFR(b.r,b.s2) order by ord_s(b.s2)) from RS_BELOW1 b where b.r=g.r and b.s=g.s) as sm
              from TS_GROUP g where g.tsl='{lvl}' and in_REG(g.r) and not in_FINEST(g.r,g.s)""")
        bad = db.q(f"select r, s from ts_fix where abs(f - sm) * {Z} > 1")
        if bad:
            db.put("G_YRFR", f"""select b.r, b.s2 as s, k.f / k.sm * v_G_YRFR(b.r,b.s2) as value
                                 from ts_fix k join RS_BELOW1 b on b.r=k.r and b.s=k.s where abs(k.f - k.sm) * {Z} > 1""")
            for r, ts in bad:
                db.log.append(f"*01 WARNING - User-provided G_YRFR values are not valid year fractions; TS fractions normalized, (R.TSL.S)={r}.{lvl}.{ts}")
    # --- G_CYCLE(TSL('WEEKLY'))$(G_CYCLE(TSL)=0)=8760/(24*7); TS_CYCLE(FINEST)=0;
    db.put("G_CYCLE", "select 'WEEKLY' as tsl, 8760/(24*7.0) as value where not in_G_CYCLE('WEEKLY')")
    db.zap("TS_CYCLE", "in_FINEST(r,s)")
    # --- LOOP(RLUP(R,TSLVL,TSL),TS_CYCLE(R,S)$((TS_CYCLE(R,S)<1)$TS_GROUP(R,TSL,S)) = 365/G_CYCLE(TSLVL));
    db.put("TS_CYCLE", """select g.r, g.s, 365 / v_G_CYCLE(u.tsl) as value from RLUP u join TS_GROUP g on g.r=u.r and g.tsl=u.tsl2
                          where v_TS_CYCLE(g.r,g.s) < 1""")
    # --- LOOP(TSL,RS_STGPRD(R,S)$TS_GROUP(R,TSL,S) = MAX(1,SUM(RS_BELOW1(R,TS,S),G_YRFR(R,TS)*365/TS_CYCLE(R,TS))));
    db.put("RS_STGPRD", """select g.r, g.s, greatest(1, coalesce((select sum(v_G_YRFR(b.r,b.s)*365/v_TS_CYCLE(b.r,b.s) order by ord_s(b.s))
                                                     from RS_BELOW1 b where b.r=g.r and b.s2=g.s), 0)) as value
                           from TS_GROUP g where in_REG(g.r)""")
    # --- LOOP(TSL, RS_TSLVL(R,S)$TS_GROUP(R,TSL,S) = TSLVLNUM(TSL));
    db.put("RS_TSLVL", "select r, s, v_TSLVLNUM(tsl) as value from TS_GROUP where in_REG(r)")
    # --- RS_STG(R,TS) = ORD(TS) - ORD(previous sibling), cyclic within the parent
    db.put("RS_STG", """
        with sib as (select b.r, b.s as parent, b.s2 as ts, ord_s(b.s2) as o from RS_BELOW1 b
                     where in_TS_MAP(b.r,'ANNUAL',b.s)),
             w as (select *, lag(o) over (partition by r, parent order by o) as prev,
                             max(o) over (partition by r, parent) as last from sib)
        select r, ts as s, o - coalesce(prev, last) as value from w""")
    # --- LOOP((R,S,TS(S--RS_STG(R,S)))$RS_STGPRD(R,S),RS_STGAV(R,S) = (G_YRFR(R,S)+G_YRFR(R,TS))/2/RS_STGPRD(R,S));
    db.put("RS_STGAV", """select p.r, p.s, (v_G_YRFR(p.r,p.s) + v_G_YRFR(p.r, o2.s)) / 2 / p.value as value
                          from RS_STGPRD p join ORD_S o1 on o1.s=p.s
                          join ORD_S o2 on o2.ord = 1 + ((o1.ord - 1 - cast(v_RS_STG(p.r,p.s) as INTEGER)) % (select count(*) from ORD_S)
                                                         + (select count(*) from ORD_S)) % (select count(*) from ORD_S)""")
    # --- RS_STGAV(R,ANNUAL) = 1;
    db.put("RS_STGAV", "select r, 'ANNUAL' as s, 1 as value from REG")
    # --- OPTION STOAL<RS_BELOW1; STOAL(R,S)$(STOAL(R,S)=1)=0;  -> any remaining = duplicate parents (fatal)
    dup = db.q("select r, s2 from RS_BELOW1 group by r, s2 having count(*) > 1")
    if dup:
        raise ValueError(f"Duplicate parent timeslices - Fatal: {dup}")
    db.clear("STOAL")
    # --- LOOP(ANNUAL(TS), STOA(S) = ORD(TS)-ORD(S));
    db.put("STOA", "select s, ord_s('ANNUAL') - ord as value from ORD_S")
    # --- LOOP(TSL,STOAL(R,S)$TS_GROUP(R,TSL,S) = ORD(TSL)-1);
    db.put("STOAL", "select r, s, ord_tsl(tsl) - 1 as value from TS_GROUP where in_REG(r)")
    if db.card("RP_UPR") + db.card("RP_UPT"):
        ts_cycle_maps(db)


def dynts(db: DB):
    """$IFI %OBMAC%%DYNTS%==YESYES: dynamic timeslice trees (OBMAC is YES on every GAMS this runs with)."""
    return str(db.env.get("DYNTS", "")).strip("'\"").upper() == "YES"


def dyn_annual(db: DB, Z):
    """timslice.mod, the normalisation of the seasons with dynamic trees:
       F=0; LOOP(T,MY_F=1-SUM(RS_BELOW1(R,S,TS)$(RS_HR(R,TS)$(NORTS(R,T,TS)=0)),RS_HR(R,TS));
         MY_SUM = SUM(RS_BELOW1(R,S,TS)$((NOT RS_HR(R,TS))$(NORTS(R,T,TS)=0)),G_YRFR(R,TS));
         IF(MY_SUM*MY_F>0,RS_HR(R,TS)$((NORTS(R,T,TS)=0)$(NOT RS_HR(R,TS))$RS_BELOW1(R,S,TS))=MY_F/MY_SUM*G_YRFR(R,TS);
         ELSEIF ABS(MY_F)>99/Z,ABORT 'Invalid dynamic Timeslice configuration'); F=MAX(F,ABS(MY_F-MY_SUM)));
       G_YRFR(R,TS) $= RS_HR(R,TS);   and the warning when F*Z > 1 (RS_HR is cleared after)."""
    ts = [t for (t,) in db.q("select y from MILESTONYR order by yv(y)")]
    off = {(r, t, s) for r, t, s in db.q("select r, y, s from NORTS where value <> 0")}
    g = {(r, s): v for r, s, v in db.q("select r, s, value from G_YRFR")}
    for (r,) in db.q("select distinct r from TS_GROUP where tsl='ANNUAL' and in_REG(r) and not in_FINEST(r, s) order by r"):
        kids = [s for (s,) in db.q(f"select s2 from RS_BELOW1 where r='{r}' and s='ANNUAL' order by ord_s(s2)")]
        hr, F = {}, 0.0
        for t in ts:
            on = [s for s in kids if (r, t, s) not in off]
            my_f = 1 - sum(hr[s] for s in on if hr.get(s))
            my_sum = sum(g.get((r, s), 0.0) for s in on if not hr.get(s))
            if my_sum * my_f > 0:
                for s in on:
                    if not hr.get(s):
                        hr[s] = my_f / my_sum * g.get((r, s), 0.0)
            elif abs(my_f) > 99 / Z:
                raise ValueError("Invalid dynamic Timeslice configuration")
            F = max(F, abs(my_f - my_sum))
        if any(hr.values()):
            db.put("G_YRFR", " union all ".join(f"select '{r}' as r, '{s}' as s, cast({v!r} as DOUBLE) as value"
                                                for s, v in hr.items() if v))
        if F * Z > 1:
            db.log.append(f"*01 WARNING - User-provided G_YRFR values are not valid year fractions; TS fractions normalized, (R.TSL.S)={r}.ANNUAL.ANNUAL")


def ts_cycle_maps(db: DB):
    """timslice.mod, 'Define TS hours and map for TS within same cycle' (used by the dispatching equations)."""
    import math
    import pandas as pd
    rnd = lambda v: math.floor(abs(v) + 0.5) * (1 if v >= 0 else -1)
    yrfr = {(r, s): v for r, s, v in db.q("select r, s, value from G_YRFR")}
    sprd = {(r, s): v for r, s, v in db.q("select r, s, value from RS_STGPRD")}
    cyc = {(r, s): v for r, s, v in db.q("select r, s, value from TS_CYCLE")}
    kids = {}
    for r, s, c in db.q("select b.r, b.s, b.s2 from RS_BELOW1 b order by b.r, ord_s(b.s), ord_s(b.s2)"):
        kids.setdefault((r, s), []).append(c)
    # --- LOOP(TS_MAP(R,ANNUAL,TS),F=0;Z=0;LOOP(RS_BELOW1(R,TS,S),F=G_YRFR(R,S)/RS_STGPRD(R,S);RS_HR(R,S)=MOD(Z+F/2,1);Z=Z+F));
    hr = {}
    for (r, par), ch in kids.items():
        Z = 0.0
        for c in ch:
            F = yrfr.get((r, c), 0.0) / sprd[(r, c)]
            hr[(r, c)] = math.fmod(Z + F / 2, 1)
            Z += F
    # --- LOOP(JS(J,ANNUAL),
    #       RJ_SL(R,J+(MOD(ROUND((RS_HR(R,TS)*8760)/146,0),60)*2),S,TS)$RS_BELOW1(R,S,TS) = YES;
    #       RJ_SL(R,J+(MOD(ROUND((RS_HR(R,TS)*8760-73)/146+60,0),60)*2+1),S,TS)$RS_BELOW1(R,S,TS) = YES;
    #       OPTION RS_UP < RJ_SL);                                   -> RS_UP(R,child,J,parent)
    rjsl = set()
    for (j0,) in db.q("select j from JS where s='ANNUAL'"):
        for (r, par), ch in kids.items():
            for c in ch:
                h = hr.get((r, c), 0.0)
                rjsl.add((r, int(j0) + int(math.fmod(rnd(h * 8760 / 146), 60)) * 2, par, c))
                rjsl.add((r, int(j0) + int(math.fmod(rnd((h * 8760 - 73) / 146 + 60), 60)) * 2 + 1, par, c))
    rsup = {(r, c, j, par) for r, j, par, c in rjsl}
    if rsup:
        # --- RS_UP(R,TS,J,S)$((MOD(RS_HR(R,TS)-(ORD(J)-2)*73/8760+1,1)<48/8760) OR (MOD(ORD(J)*73/8760-RS_HR(R,TS)+1,1)<25/8760)) = NO;
        rsup = {(r, c, j, par) for r, c, j, par in rsup
                if not (math.fmod(hr.get((r, c), 0.0) - (j - 2) * 73 / 8760 + 1, 1) < 48 / 8760
                        or math.fmod(j * 73 / 8760 - hr.get((r, c), 0.0) + 1, 1) < 25 / 8760)}
        # --- OPTION JS < RS_UP; RJ_SL(R,J,S,TS)$(NOT JS(J,S)) = NO;
        js = {(j, par) for r, c, j, par in rsup}
        rjsl = {k for k in rjsl if (k[1], k[2]) in js}
        # --- JS_CCL(R,JS(J,S)) = MAX(1/G_YRFR(R,S),365/TS_CYCLE(R,S));
        regs = [r for (r,) in db.q("select r from REG")]
        ccl = {(r, j, par): max(1 / yrfr[(r, par)], 365 / cyc[(r, par)]) for r in regs for j, par in js if (r, par) in yrfr}
        # --- RS_MODUS(RS_UP(R,S,JS),SL)$RJ_SL(R,JS,SL) = MOD(RS_HR(R,S)-RS_HR(R,SL)+G_YRFR(R,S)/RS_STGPRD(R,S)/2+2/JS_CCL(R,JS),1/JS_CCL(R,JS));
        slot = {}
        for r, j, par, c in rjsl:
            slot.setdefault((r, j, par), []).append(c)
        modus = []
        for r, c, j, par in rsup:
            k = ccl[(r, j, par)]
            for sl in slot.get((r, j, par), []):
                v = math.fmod(hr.get((r, c), 0.0) - hr.get((r, sl), 0.0) + yrfr[(r, c)] / sprd[(r, c)] / 2 + 2 / k, 1 / k)
                if v:
                    modus.append((r, c, str(j), par, sl, v))
        db.clear("JS", "JS_CCL", "RS_MODUS")
        db.load_rows("JS", [(str(j), par) for j, par in js])
        db.load_rows("JS_CCL", [(r, str(j), par, v) for (r, j, par), v in ccl.items()])
        db.load_rows("RS_MODUS", modus)
    db.clear("RS_HR", "RJ_SL", "RS_UP")
    db.load_rows("RS_HR", [(r, c, v) for (r, c), v in hr.items() if v])
    db.load_rows("RJ_SL", [(r, str(j), par, c) for r, j, par, c in rjsl])
    db.load_rows("RS_UP", [(r, c, str(j), par) for r, c, j, par in rsup])


# ---------------------------------------------------------------------------
def _levels_from_ts(db, tsl_tab, ts_tab, rk, key):
    """LOOP(X_TS(RK,S)$(NOT SUM(X_TSL(RK,TSL),1)),X_TSL(RK,TSL)$TS_GROUP(R,TSL,S) = YES);
    sequential loop: the level of the first timeslice given (entry order) is taken."""
    db.add(tsl_tab, f"""select k.r, k.{key}, g.tsl from
                        (select r, {key}, arg_min(s, ord_s(s)) as s from "{ts_tab}" t where in_{rk}(r,{key})
                           and not exists(select 1 from "{tsl_tab}" l where l.r=t.r and l.{key}=t.{key}) group by r, {key}) k
                        join TS_GROUP g on g.r=k.r and g.s=k.s""")


def _drop_missing_levels(db, tab, key):
    """X_TSL(R,K,TSL-1)$RXX(R,TSL,R) $= X_TSL(R,K,TSL); F=CARD(X_TSL)-F; X_TSL(R,K,TSL)$(RXX(R,TSL,R)$F)=NO;"""
    before = db.card(tab)
    db.add(tab, f"""select t.r, t.{key}, (select o.tsl from TSL_ORD o where o.ord = ord_tsl(t.tsl) - 1) as tsl
                    from "{tab}" t where exists(select 1 from t_rxx x where x.r=t.r and x.tsl=t.tsl) and ord_tsl(t.tsl) > 1""")
    f = db.card(tab) - before
    if f:
        db.remove(tab, where=f'exists(select 1 from t_rxx x where x.r="{tab}".r and x.tsl="{tab}".tsl)')
    return f


def commodity_timeslices(db: DB):
    """Timeslice level and timeslices of each commodity; peak timeslices."""
    # --- OPTION CLEAR=RXX; RXX(R,TSL,R)$(NOT SUM(RJLVL(J,R,TSL),1))=YES;
    db.tmp("t_rxx", "select r.r, o.tsl from REG r, TSL_ORD o where not exists(select 1 from RJLVL j where j.r=r.r and j.tsl=o.tsl)")
    db.assign("RXX", "select r, tsl as u, r as u2 from t_rxx")
    f = _drop_missing_levels(db, "COM_TSL", "c")
    z = _drop_missing_levels(db, "PRC_TSL", "p")
    if f + z:
        db.log.append(f"*01 WARNING - Commodities/processes defined at non-existing TSLVL; number of COM/PRC resetted to coarser level: {f}/{z}")
    # --- TRACKC(RC) $= SUM(COM_TS(RC,S),1);
    db.tmp("t_trackc", "select distinct r, c from COM_TS where in_RC(r,c)")
    # --- LOOP(COM_TS(RC(R,C),S)$(NOT SUM(COM_TSL(RC,TSL),1)),COM_TSL(RC,TSL)$TS_GROUP(R,TSL,S) = YES);
    _levels_from_ts(db, "COM_TSL", "COM_TS", "RC", "c")
    # --- LOOP(COM_TSL(TRACKC(R,C),TSLVL)$(SUM(TS_GROUP(R,TSLVL,S),1) NE SUM(COM_TS(R,C,S),1)),
    #       COM_TS(R,C,S)$(NOT TS_GROUP(R,TSLVL,S)) = NO;
    #       RCS(R,C,S)$((NOT SUM(COM_TS(R,C,TS)$RS_TREE(R,S,TS),1))$G_YRFR(R,S))=YES);
    db.clear("RCS")
    n = db.tmp("t_fix", """select l.r, l.c, l.tsl from COM_TSL l join t_trackc k on k.r=l.r and k.c=l.c
                           where (select count(*) from TS_GROUP g where g.r=l.r and g.tsl=l.tsl)
                              <> (select count(*) from COM_TS t where t.r=l.r and t.c=l.c)""")
    if n:
        db.remove("COM_TS", where="""exists(select 1 from t_fix f where f.r=COM_TS.r and f.c=COM_TS.c)
                                     and not exists(select 1 from t_fix f where f.r=COM_TS.r and f.c=COM_TS.c and in_TS_GROUP(f.r,f.tsl,COM_TS.s))""")
        db.add("RCS", """select distinct f.r, f.c, g.s from t_fix f join G_YRFR g on g.r=f.r
                         where not exists(select 1 from COM_TS t where t.r=f.r and t.c=f.c and in_RS_TREE(f.r,g.s,t.s))""")
    # --- COM_TSL(RC,'ANNUAL')$(NOT SUM(COM_TSL(RC,TSL),1)) = YES;
    db.add("COM_TSL", "select r, c, 'ANNUAL' as tsl from RC k where not exists(select 1 from COM_TSL l where l.r=k.r and l.c=k.c)")
    # --- LOOP(COM_TSL(RC(R,C),TSL)$(NOT TRACKC(RC)),COM_TS(RC,S)$TS_GROUP(R,TSL,S) = YES);
    db.add("COM_TS", """select l.r, l.c, g.s from COM_TSL l join TS_GROUP g on g.r=l.r and g.tsl=l.tsl
                        where in_RC(l.r,l.c) and not exists(select 1 from t_trackc k where k.r=l.r and k.c=l.c)""")
    # --- RCS_COMTS(RC(R,C),S)$SUM(TS_MAP(R,S,TS)$COM_TS(RC,TS),1) = YES;
    db.add("RCS_COMTS", "select distinct t.r, t.c, m.s from COM_TS t join TS_MAP m on m.r=t.r and m.s2=t.s where in_RC(t.r,t.c)")
    # --- RTC(R,T,C)$RC(R,C) = YES;  LOOP(TRACKC(R,C) with COM_OFF: pp_off -> RTC = NO;
    #       COM_BNDPRD(R,T,C,S,'FX')$(COM_TS(R,C,S)$(NOT RTC(R,T,C))) = EPS);
    db.add("RTC", "select r, t.y, c from RC, MILESTONYR t")
    if db.card("COM_OFF"):
        db.tmp("t_off", off_years(db, "COM_OFF", ["c"], "and in_RC(n.r,n.c)"))
        db.remove("RTC", select="select r, y, c from t_off")
        db.put("COM_BNDPRD", """select o.r, o.y, o.c, t.s, 'FX' as l, 0 as value from t_off o join COM_TS t on t.r=o.r and t.c=o.c""",
               zero="eps")
    # --- RTCS_VARC(RTC(R,T,C),S)$COM_TS(R,C,S) = YES;
    db.add("RTCS_VARC", "select k.r, k.y, k.c, t.s from RTC k join COM_TS t on t.r=k.r and t.c=k.c")

    # ---- peaking
    # --- COM_PEAK(R,CG)$SUM(COM_PKTS(R,CG,S),1) = 1;
    db.add("COM_PEAK", "select distinct r, cg from COM_PKTS where in_REG(r)")
    # --- TRACKC(COM_PEAK(R,C))$(NOT SUM(COM_TSL(R,C,TSL),1)) = YES;
    #     LOOP(ANNUAL(TS(TSL)),COM_TSL(TRACKC(R,C),TSL+SMAX(COM_PKTS(R,C,S),STOAL(R,S)))=YES);
    db.add("COM_TSL", """select k.r, k.cg as c, (select o.tsl from TSL_ORD o where o.ord = 1 +
                                (select max(v_STOAL(t.r,t.s)) from COM_PKTS t where t.r=k.r and t.cg=k.cg)) as tsl
                         from COM_PEAK k where in_COM(k.cg) and in_REG(k.r)
                           and not exists(select 1 from COM_TSL l where l.r=k.r and l.c=k.cg)
                           and exists(select 1 from COM_PKTS t where t.r=k.r and t.cg=k.cg)""")
    # --- COM_PKTS(COM_PEAK(R,C),S)$SUM(COM_PKTS(R,C,TS)$RS_TREE(R,S,TS),1) = SUM(COM_TSL(R,C,TSL),ORD(TSL)=STOAL(R,S)+1);
    db.tmp("t_pk", """select k.r, k.cg, g.s, exists(select 1 from COM_TSL l where l.r=k.r and l.c=k.cg
                                                     and ord_tsl(l.tsl) = v_STOAL(k.r,g.s)+1) as keep
                      from COM_PEAK k join TS_GROUP g on g.r=k.r
                      where in_COM(k.cg) and exists(select 1 from COM_PKTS t where t.r=k.r and t.cg=k.cg and in_RS_TREE(k.r,g.s,t.s))""")
    db.remove("COM_PKTS", select="select r, cg, s from t_pk where not keep")
    db.add("COM_PKTS", "select r, cg, s from t_pk where keep")
    # --- LOOP(COM_PEAK(R,CG)$(NOT SUM(COM_PKTS(R,CG,S),1)), Z = SMAX(COM_TSL(R,C,TSL)$COM_GMAP(R,CG,C),TSLVLNUM(TSL));
    #       LOOP(TSL$(TSLVLNUM(TSL)=Z),COM_PKTS(R,CG,S)$TS_GROUP(R,TSL,S) = YES));
    db.add("COM_PKTS", """
        with z as (select k.r, k.cg, (select max(v_TSLVLNUM(l.tsl)) from COM_TSL l where l.r=k.r and in_COM_GMAP(k.r,k.cg,l.c)) as z
                   from COM_PEAK k where in_REG(k.r) and not exists(select 1 from COM_PKTS t where t.r=k.r and t.cg=k.cg))
        select z.r, z.cg, g.s from z join TS_GROUP g on g.r=z.r where v_TSLVLNUM(g.tsl) = z.z""")


# ---------------------------------------------------------------------------
def process_timeslices(db: DB):
    """Timeslice level and timeslices of each process; S1/S2 levels."""
    # --- LOOP(PRC_TS(RP(R,P),S)$(NOT SUM(PRC_TSL(RP,TSL),1)),PRC_TSL(RP,TSL)$TS_GROUP(R,TSL,S) = YES);
    _levels_from_ts(db, "PRC_TSL", "PRC_TS", "RP", "p")
    # --- PRC_TSL(RP,'ANNUAL')$(NOT SUM(PRC_TSL(RP,TSL),1)) = YES;
    db.add("PRC_TSL", "select r, p, 'ANNUAL' as tsl from RP k where not exists(select 1 from PRC_TSL l where l.r=k.r and l.p=k.p)")
    # --- TRACKP(RP)$(NOT SUM(PRC_TS(RP,S),1)) = YES; LOOP(TSL,PRC_TS(TRACKP(R,P),S)$(TS_GROUP(R,TSL,S)$PRC_TSL(R,P,TSL)) = YES);
    db.add("PRC_TS", """select l.r, l.p, g.s from PRC_TSL l join TS_GROUP g on g.r=l.r and g.tsl=l.tsl
                        where in_RP(l.r,l.p) and not exists(select 1 from PRC_TS t where t.r=l.r and t.p=l.p)""")
    # --- RP_SGS(RP_FLO(R,P))$(PRC_TSL(R,P,'ANNUAL')$(PRC_MAP(R,'STS',P)+PRC_MAP(R,'NST',P))) = YES;  RP_SGS(RP_FLO(R,P))$=PRC_MAP(R,'SGS',P);
    db.add("RP_SGS", """select r, p from RP_FLO f where (in_PRC_TSL(r,p,'ANNUAL') and (in_PRC_MAP(r,'STS',p) or in_PRC_MAP(r,'NST',p)))
                        or in_PRC_MAP(r,'SGS',p)""")
    # --- PRC_MAP(R,'STG',P)$((NOT SUM(TOP(RPC_PG(R,P,C),'IN'),1))$RP_SGS(R,P)) = NO;
    db.remove("PRC_MAP", where="""prc_grp='STG' and in_RP_SGS(r,p) and not exists(
        select 1 from TOP t where t.r=PRC_MAP.r and t.p=PRC_MAP.p and t.io='IN' and in_RPC_PG(t.r,t.p,t.c))""")
    # --- PRC_MAP(R,'STG',P)$((NOT PRC_TSL(R,P,'ANNUAL'))$PRC_MAP(R,'NST',P)) = YES;
    db.add("PRC_MAP", "select r, 'STG' as prc_grp, p from PRC_MAP where prc_grp='NST' and in_REG(r) and not in_PRC_TSL(r,p,'ANNUAL')")
    # --- RP_STG(RP(R,P)) $= PRC_MAP(R,'STG',P);
    db.add("RP_STG", "select r, p from RP where in_PRC_MAP(r,'STG',p)")
    # --- OPTION DEM < COM_FR;  LOOP(COM_TSL(DEM(R,C),'ANNUAL'),TRACKP(RP_FLO(R,P))$RPC_PG(R,P,C) = YES);
    db.assign("DEM", "select distinct r, c from COM_FR")
    db.tmp("t_trackp", """select distinct g.r, g.p from RPC_PG g where in_RP_FLO(g.r,g.p)
                          and in_DEM(g.r,g.c) and in_COM_TSL(g.r,g.c,'ANNUAL')""")
    # --- PRC_YMAX(RP(R,P)) = SMAX((RPC_SPG(R,P,C),COM_TSL(R,C,TSL)),TSLVLNUM(TSL));
    #     PRC_YMAX(TRACKP(R,P)) = SMAX((RPC(R,P,C),COM_TSL(R,C,TSL)),TSLVLNUM(TSL));
    #     PRC_YMAX(RP_STG) = 0;  PRC_YMAX(RP) = MAX(PRC_YMAX(RP),SMAX(PRC_TSL(RP,TSL),TSLVLNUM(TSL)));
    db.clear("PRC_YMAX")
    db.put("PRC_YMAX", """
        select k.r, k.p, greatest(
            case when in_RP_STG(k.r,k.p) then 0
                 when exists(select 1 from t_trackp t where t.r=k.r and t.p=k.p)
                 then coalesce((select max(v_TSLVLNUM(l.tsl)) from RPC c join COM_TSL l on l.r=c.r and l.c=c.c where c.r=k.r and c.p=k.p), '-inf'::double)
                 else coalesce((select max(v_TSLVLNUM(l.tsl)) from RPC_SPG c join COM_TSL l on l.r=c.r and l.c=c.c where c.r=k.r and c.p=k.p), '-inf'::double) end,
            coalesce((select max(v_TSLVLNUM(l.tsl)) from PRC_TSL l where l.r=k.r and l.p=k.p), '-inf'::double)) as value
        from RP k""")
    # --- LOOP(R, TS_ARRAY(S) $= RS_TSLVL(R,S); Z = MAX(1,SMAX(RLUP(R,TSLVL,TSL),TSLVLNUM(TSL)));
    #       PRC_SGL(RP_FLO(R,P)) = MIN(PRC_YMAX(R,P)-1$RP_STG(R,P),Z)-1;
    #       RPS_S1(RP(R,P),S)$(TS_ARRAY(S) = PRC_YMAX(R,P)) = YES;  RPS_S2(RPS_S1(R,P,S))$(NOT RP_SGS(R,P)) = YES; );
    #       RPS_S2(RP_SGS(R,P),S)$(TS_ARRAY(S) = PRC_YMAX(R,P)) = YES;
    db.add("RPS_S2", "select k.r, k.p, t.s from RP_SGS k join RS_TSLVL t on t.r=k.r where t.value = v_PRC_YMAX(k.r,k.p)")
    db.clear("PRC_SGL")
    db.put("PRC_SGL", """select f.r, f.p, least(v_PRC_YMAX(f.r,f.p) - (case when in_RP_STG(f.r,f.p) then 1 else 0 end),
                                greatest(1, coalesce((select max(v_TSLVLNUM(u.tsl2)) from RLUP u where u.r=f.r), '-inf'::double))) - 1 as value
                         from RP_FLO f""")
    #       PRC_YMAX(RP_SGS(R,P)) = PRC_SGL(R,P)+1;
    db.put("PRC_YMAX", "select r, p, v_PRC_SGL(r,p) + 1 as value from RP_SGS")
    db.add("RPS_S1", "select k.r, k.p, t.s from RP k join RS_TSLVL t on t.r=k.r where t.value = v_PRC_YMAX(k.r,k.p)")
    db.add("RPS_S2", "select r, p, s from RPS_S1 where not in_RP_SGS(r,p)")
    # --- LOOP((TSLVL,TSL)$(ORD(TSL)>ORD(TSLVL)),IF(ORD(TSL)=2,RPS_PRCTS(PRC_TS(RP,S))=1);
    #       RPS_PRCTS(RP(R,P),S)$(TS_GROUP(R,TSLVL,S)$PRC_TSL(RP,TSL))=YES);
    db.add("RPS_PRCTS", "select r, p, s from PRC_TS where in_RP(r,p)")
    db.add("RPS_PRCTS", """select l.r, l.p, g.s from PRC_TSL l join TS_GROUP g on g.r=l.r
                           where in_RP(l.r,l.p) and ord_tsl(l.tsl) > ord_tsl(g.tsl)""")
    # --- RP_PGFLO(TRACKP)$(PRC_YMAX(TRACKP)>1) = YES;
    db.add("RP_PGFLO", "select r, p from t_trackp where v_PRC_YMAX(r,p) > 1")


# ---------------------------------------------------------------------------
def flow_variable_timeslices(db: DB):
    """RPCS_VAR: timeslices of the flow variables of each process/commodity."""
    # --- RPC_STG(RPC(RP_STG(R,P),C))$(PRC_STGTSS(RPC)+PRC_STGIPS(RPC)+(RPC_PG(RPC)+RPC_SPG(RPC))$PRC_MAP(R,'NST',P)) = YES;
    db.add("RPC_STG", """select k.r, k.p, k.c from RPC k where in_RP_STG(k.r,k.p)
                         and (in_PRC_STGTSS(k.r,k.p,k.c) or in_PRC_STGIPS(k.r,k.p,k.c)
                              or ((in_RPC_PG(k.r,k.p,k.c) or in_RPC_SPG(k.r,k.p,k.c)) and in_PRC_MAP(k.r,'NST',k.p)))""")
    # --- TRACKPC(RPC_STG(R,P,C))$((TOP(R,P,C,'OUT')+PRC_NSTTS(R,P,'ANNUAL'))$COM_TS(R,C,'ANNUAL')$PRC_MAP(R,'NST',P)) = YES;
    #     (night storage: the flows of an ANNUAL commodity that leave the storage, or all of them when it stores at ANNUAL)
    db.tmp("t_nstann", """select k.r, k.p, k.c from RPC_STG k where in_PRC_MAP(k.r,'NST',k.p) and in_COM_TS(k.r,k.c,'ANNUAL')
                          and (in_TOP(k.r,k.p,k.c,'OUT') or in_PRC_NSTTS(k.r,k.p,'ANNUAL'))""")
    # --- RPCS_VAR(RPC(RP_STG(R,P),C),S)$(PRC_TS(R,P,S)$(NOT TRACKPC(RPC))+ANNUAL(S)$TRACKPC(RPC)) = YES;
    db.add("RPCS_VAR", """select k.r, k.p, k.c, t.s from RPC k join PRC_TS t on t.r=k.r and t.p=k.p where in_RP_STG(k.r,k.p)
                          and not exists(select 1 from t_nstann n where n.r=k.r and n.p=k.p and n.c=k.c)""")
    db.add("RPCS_VAR", "select k.r, k.p, k.c, 'ANNUAL' as s from RPC k join t_nstann n on n.r=k.r and n.p=k.p and n.c=k.c where in_RP_STG(k.r,k.p)")
    # --- PRC_NSTTS(RP_STG(R,P),ANNUAL)$(NOT SUM(TOP(TRACKPC(R,P,C),'IN'),1))=NO; OPTION PRC_ACT<PRC_NSTTS;
    db.remove("PRC_NSTTS", where="""s='ANNUAL' and in_RP_STG(r,p) and not exists(
                  select 1 from t_nstann n where n.r=PRC_NSTTS.r and n.p=PRC_NSTTS.p and in_TOP(n.r,n.p,n.c,'IN'))""")
    # --- PRC_NSTTS(RPS_S2(R,P,S))$(NOT PRC_ACT(R,P)) $= PRC_MAP(R,'NST',P);
    #     (no storing timeslice given, or ANNUAL given without an ANNUAL input: every timeslice of the shadow level)
    db.add("PRC_NSTTS", """select k.r, k.p, k.s from RPS_S2 k where in_PRC_MAP(k.r,'NST',k.p)
                           and not exists(select 1 from PRC_NSTTS n where n.r=k.r and n.p=k.p)""")
    # --- TRACKP(RP) = NOT RP_STG(RP);
    # --- RPCS_VAR(RPC_PG(TRACKP(R,P),C),S)$PRC_TS(R,P,S) = YES;
    db.add("RPCS_VAR", """select g.r, g.p, g.c, t.s from RPC_PG g join PRC_TS t on t.r=g.r and t.p=g.p
                          where in_RP(g.r,g.p) and not in_RP_STG(g.r,g.p)""")
    # --- RPCS_VAR(RPC_SPG(TRACKP(R,P),C),S)$RPS_S2(R,P,S) = YES;
    db.add("RPCS_VAR", """select g.r, g.p, g.c, t.s from RPC_SPG g join RPS_S2 t on t.r=g.r and t.p=g.p
                          where in_RP(g.r,g.p) and not in_RP_STG(g.r,g.p)""")
    # --- RPCS_VAR(RPC(TRACKP(R,P),C),S)$(RPS_S1(R,P,S)$(NOT RPC_PG(R,P,C)+RPC_SPG(R,P,C))) = YES;
    db.add("RPCS_VAR", """select g.r, g.p, g.c, t.s from RPC g join RPS_S1 t on t.r=g.r and t.p=g.p
                          where in_RP(g.r,g.p) and not in_RP_STG(g.r,g.p)
                            and not (in_RPC_PG(g.r,g.p,g.c) or in_RPC_SPG(g.r,g.p,g.c))""")
    # --- RPCS_VAR(R,P,C,S)$RCS(R,C,S) = NO;  OPTION CLEAR=PRC_YMAX,CLEAR=RCS,...
    db.remove("RPCS_VAR", where="in_RCS(r,c,s)")
    db.clear("PRC_YMAX", "RCS")


# ---------------------------------------------------------------------------
def timeslice_fractions(db: DB):
    """Timeslice split fractions RS_FR / RTCS_FR; elastic demands."""
    # --- RS_FR(RS_TREE(R,S,TS)) = 1$TS_MAP(R,S,TS) + (G_YRFR(R,S)/G_YRFR(R,TS))$RS_BELOW(R,TS,S);
    db.put("RS_FR", """select r, s, s2, (case when in_TS_MAP(r,s,s2) then 1 else 0 end) +
                              (case when in_RS_BELOW(r,s2,s) then v_G_YRFR(r,s)/v_G_YRFR(r,s2) else 0 end) as value from RS_TREE""")
    # --- RTCS_FR(RTC(R,T,C),S,TS)$(RS_BELOW(R,TS,S)$COM_FR(RTC,TS)) = ((COM_FR(RTC,S)/COM_FR(RTC,TS))$(COM_FR(RTC,TS)>0))/RS_FR(R,S,TS)-1;
    db.put("RTCS_FR", """select f.r, f.y, f.c, b.s2 as s, b.s as s2,
                                (case when f.value > 0 then v_COM_FR(f.r,f.y,f.c,b.s2) / f.value else 0 end) / v_RS_FR(f.r,b.s2,b.s) - 1 as value
                         from COM_FR f join RS_BELOW b on b.r=f.r and b.s=f.s where in_RTC(f.r,f.y,f.c)""")
    # --- COM_FR(RTC(R,T,C),RTS(S))$((NOT COM_FR(RTC,S))$RCS_COMTS(R,C,S)) = G_YRFR(R,S);
    db.put("COM_FR", """select k.r, k.y, k.c, x.s, v_G_YRFR(k.r,x.s) as value from RTC k join RCS_COMTS x on x.r=k.r and x.c=k.c
                        where not in_COM_FR(k.r,k.y,k.c,x.s) and not in_NORTS(k.r,k.y,x.s)""")   # NOT EPS is false; RTS(S)
    # --- OPTION DEM < COM_PROJ;
    db.assign("DEM", "select distinct r, c from COM_PROJ")
    # ---- elastic demands
    # --- $IF %TIMESED%==YES $BATINCLUDE pp_micro.mod PRE
    if db.ctl.get("TIMESED"):
        elastic.micro_pre(db)
    # --- COM_ELAST(R,T,C,S,BDNEQ(BD))$COM_ELAST(R,T,C,S,BD) =
    #        -ABS(COM_ELAST(R,T,C,S,BD)-1+1)$SUM(RDCUR(R,CUR),COM_BPRICE(R,T,C,S,CUR)*COM_VOC(R,T,C,BD)>0);
    #     (an elasticity is kept, with a negative sign, only where there is a base price and an allowed variation; without
    #      base prices the demands are not elastic.  The sum counts the currencies for which the product is positive.)
    db.put("COM_ELAST", """select a.r, a.y, a.c, a.s, a.l,
                                  case when exists(select 1 from RDCUR d where d.r=a.r and v_COM_BPRICE(a.r,a.y,a.c,a.s,d.cur) * v_COM_VOC(a.r,a.y,a.c,a.l) > 0)
                                       then -abs((a.value - 1) + 1) else 0 end as value
                           from COM_ELAST a where in_REG(a.r) and in_MILESTONYR(a.y) and in_BDNEQ(a.l)""")
    # --- OPTION RC_AGP < COM_ELAST; COM_STEP(RC_AGP(RC,BDNEQ))$(NOT COM_STEP(RC,BDNEQ)) = MAX(1,COM_STEP(RC,'FX'));
    #     (the projection takes every year that is left, data years included)
    db.assign("RC_AGP", "select distinct r, c, l from COM_ELAST")
    db.put("COM_STEP", """select k.r, k.c, k.l, greatest(1, v_COM_STEP(k.r,k.c,'FX')) as value from RC_AGP k
                          where in_RC(k.r,k.c) and in_BDNEQ(k.l) and not in_COM_STEP(k.r,k.c,k.l)""")
    # --- RCJ(RC,J,BD)$((ORD(J) <= COM_STEP(RC,BD))$RC_AGP(RC,BD)) = 1; OPTION CLEAR=RC_AGP;
    db.add("RCJ", """select k.r, k.c, j.j, k.l from RC_AGP k, J j where in_RC(k.r,k.c) and k.l in ('LO','UP','FX')
                     and cast(j.j as INTEGER) <= v_COM_STEP(k.r,k.c,k.l)""")
    db.clear("RC_AGP")
