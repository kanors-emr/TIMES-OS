# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounds: pp_lvlbd.mod (bounds below the level of their variable), the bounds by timeslice of ppmain.mod, and
the last preprocessing before the equations: AFS, UC_RHSMAP (eqmain.mod / eqcapact.mod) and the variable
bounds of bndmain.mod, kept as tables  B_<variable>(d0..dn, lower, upper).

A bound table holds a row for every variable that has a bound different from the default
(0 .. +INF, or -INF .. +INF for the user-constraint slack variables)."""
from ..controls import unsupported
from ..engine import DB
from .common import require_empty, _values
from . import bndcst
from . import abs as abs_ext, dsc, dynslite, elastic, grids, reduce, resloadc, simv, stochastic, ucbet


# ---------------------------------------------------------------------------
def _lvlbd(db, name, item, level, rt, neg):
    """pp_lvlbd.mod: bounds given on timeslices below the level of their variable are aggregated to the level.

    name: the bound parameter (columns: r, y, item..., s, [extra...], l); item: its process / commodity columns;
    level: the set (r, item..., ts) of the timeslices the variable exists at (%6: PRC_TS, RPCS_VAR, COM_TS);
    rt: the (r, y, item) domain (RTP or RTC); neg: what a negative bound below the level becomes (%9): "eps",
    0 (removed) or None (kept).  Records at a level timeslice of the item, or above it, are not aggregated.
    The records below the level stay in the table, as in GAMS; only the aggregated values are added."""
    if not db.card(name):
        return
    cols = db.cols(name)
    nit = len(item)
    extra = [c for c in cols[2 + nit:] if c not in ("s", "l")]
    # RT%2(R,T,%2): the domain is (r, t, first item) - RTP(R,T,P) also for FLO_FR, whose item is (p, c)
    rows = db.q(f'select * from "{name}" a where in_MILESTONYR(a.y) and in_{rt}(a.r, a.y, a.{item[0]})')
    # ---- %8(RT(R,T,P),S--ORD(S),'FX') $= SUM(BD$%1(RT,S,BD),1)$(NOT %7(R,P,S)):  the (r, t, item) with a bound off level
    # %7: timeslices at or above the level, per (r, item) - all items in one query (the same join as _level_sql per item)
    # (the level set is read for the (r, item) of the bound's records only: no other is looked up)
    lc = db.cols(level)
    bound = 'exists(select 1 from "{}" b where {})'.format(
        name, " and ".join([f"b.r = l.{lc[0]}"] + [f"b.{c} = l.{lv}" for c, lv in zip(item, lc[1:-1])]))
    above = {}
    for row in db.q(f"""select distinct l.{lc[0]}, {", ".join(f"l.{c}" for c in lc[1:-1])}{"," if lc[1:-1] else ""} m.s
                        from "{level}" l join TS_MAP m on m.r = l.{lc[0]} and m.s2 = l.{lc[-1]} where {bound}"""):
        above.setdefault(tuple(row[:-1]), set()).add(row[-1])
    none = frozenset()

    def at_or_above(r, it):
        return above.get((r,) + it, none)
    groups = {}                                 # (r, t, item..., extra...) -> {(s, bd): value}
    marked = set()
    for row in rows:
        rec = dict(zip(cols + ["value"], row))
        it = tuple(rec[c] for c in item)
        g = (rec["r"], rec["y"]) + it + tuple(rec[c] for c in extra)
        groups.setdefault(g, {})[(rec["s"], rec["l"])] = rec["value"]
        if rec["s"] not in at_or_above(rec["r"], it):
            marked.add(g)
    if not marked:
        return
    tsmap, below, yrfr = {}, {}, {}
    for r in {g[0] for g in marked}:
        tsmap[r] = {}
        for s, s2 in db.q(f"select s, s2 from TS_MAP where r='{r}'"):
            tsmap[r].setdefault(s, set()).add(s2)
        below[r] = {}
        for s, s2 in db.q(f"select s, s2 from RS_BELOW where r='{r}'"):
            below[r].setdefault(s, set()).add(s2)
        yrfr[r] = {s: v for s, v in db.q(f"select s, value from G_YRFR where r='{r}'")}
    # the level timeslices of every (r, item) and the order of the timeslices, each read once (in the order of the
    # tables, as the query per item and the lookup per timeslice gave them: a large model has thousands of marked items)
    lev = {}
    for row in db.q(f'select {", ".join(f"l.{c}" for c in lc)} from "{level}" l where {bound}'):
        lev.setdefault(tuple(row[:-1]), []).append(row[-1])
    ords = {}
    for s, o in db.q("select s, ord from ORD_S"):
        ords.setdefault(s, o)
    out, warned = [], False
    for g in sorted(marked):
        r, t, it = g[0], g[1], g[2:2 + nit]
        recs = groups[g]
        levels = lev.get((r,) + it, [])
        for ts in sorted(levels, key=lambda x: ords.get(x) or 0):
            # ---- TS_BD(S,BD) = %1(R,T,P,S,BD)$TS_MAP(R,TS,S);  TS_BD(S,BDNEQ) $= TS_BD(S,'FX');
            tsbd = {k: v for k, v in recs.items() if k[0] in tsmap[r].get(ts, ())}
            for (s, bd), v in list(tsbd.items()):
                if bd == "FX":
                    tsbd[(s, "LO")] = v; tsbd[(s, "UP")] = v
            # ---- Z = number of bound types at TS itself;  F = number of entries below
            z = sum(1 for (s, bd) in tsbd if s == ts)
            f = len(tsbd) - z
            if z > 1:
                z = f
            else:
                z = sum(1 for (s, bd) in tsbd if s != ts and bd in ("LO", "UP") and (ts, bd) in tsbd) if f else 0
            if z:
                f = 1 if f > z else 0
                db.log.append(f"*01 WARNING - {name} Bounds conflict: Value at level and below, latter ignored: R={r} Y={t} "
                              + " ".join(f"{c.upper()}={v}" for c, v in zip(item, it)) + f" S={ts}")
            if not f:
                continue
            # ---- BDVAL(BD) = (NOT TS_BD(TS,BD))$BDNEQ(BD)
            bdval = {bd for bd in ("LO", "UP") if (ts, bd) not in tsbd}
            # ---- negative bounds (below the level) -> %9
            if neg is not None:
                for (s, bd), v in list(tsbd.items()):
                    if bd in ("LO", "UP") and v < 0:
                        if neg == "eps":
                            tsbd[(s, bd)] = 0.0
                        else:
                            del tsbd[(s, bd)]
            # ---- TS_BD(S,BDVAL(BD))$SUM(RS_BELOW(R,SL,S)$TS_BD(SL,BD),1) = 0:  only the topmost below the level counts
            for (s, bd) in list(tsbd):
                if bd in bdval and any((sl, bd) in tsbd for sl in tsmap[r] if s in below[r].get(sl, ())):
                    del tsbd[(s, bd)]
            # ---- BDVAL('UP') only when the UP bounds below cover the whole of TS
            if "UP" in bdval:
                cover = yrfr[r].get(ts, 0.0) - sum(yrfr[r].get(s, 0.0) for s in below[r].get(ts, ()) if (s, "UP") in tsbd)
                if not cover < 1e-5:
                    bdval.discard("UP")
            # ---- TS_BD(TS,BDVAL) = SUM(RS_BELOW(R,TS,S), TS_BD(S,BDVAL))
            agg = {}
            for bd in bdval:
                parts = [tsbd[(s, bd)] for s in below[r].get(ts, ()) if (s, bd) in tsbd]
                if parts:
                    tot = sum(parts)
                    if tot != 0 or all(p == 0 for p in parts):   # an all-EPS sum is EPS
                        agg[bd] = tot
            for bd, v in agg.items():
                tsbd[(ts, bd)] = v
            # ---- a summed UP equal to the summed LO is a fixed bound; otherwise %1(...,TS,BDVAL) $= TS_BD(TS,BDVAL)
            at_ts = {bd for (s, bd) in tsbd if s == ts}
            if len(at_ts) == 2 and tsbd.get((ts, "UP"), 0.0) - tsbd.get((ts, "LO"), 0.0) < 1e-7:
                out.append(g[:2] + it + (ts,) + g[2 + nit:] + ("FX", tsbd[(ts, "LO")]))
            else:
                for bd, v in agg.items():
                    out.append(g[:2] + it + (ts,) + g[2 + nit:] + (bd, v))
    if out:
        db.put(name, _values(out, cols + ["value"]), zero="eps")


def _level_sql(db, level, r, it):
    """The level timeslices of one item: select ts from the %6 set."""
    lc = db.cols(level)
    cond = " and ".join([f"r='{r}'"] + [f"{c}='{v}'" for c, v in zip(lc[1:-1], it)])
    return f'select {lc[-1]} as ts from "{level}" where {cond}'


def _bd_guard(db, name, item, level, rt, neg):
    """pp_lvlbd.mod for one bound parameter, then %1(R,T,...,S,BDNEQ)$%1(R,T,...,S,'FX') = 0."""
    if not db.card(name):
        return
    _lvlbd(db, name, item, level, rt, neg)
    same = " and ".join(f'b.{c}="{name}".{c}' for c in db.cols(name) if c != "l")
    db.zap(name, f"l in ('LO','UP') and in_MILESTONYR(y) and exists(select 1 from \"{name}\" b where {same} and b.l='FX')")


def _eoh(col):
    return f"(case when {col}='BOH' then '{{BOT}}' when {col}='EOH' then '{{EOT}}' else {col} end)"


def bounds_by_timeslice(db: DB):
    """Bounds by timeslice; cumulative bounds."""
    # --- $BATINCLUDE pp_lvlbd.mod ACT_BND P ... PRC_TS RPS_PRCTS RTPS_BD EPS;  FLO_FR ... RPCS_VAR RPCS_VAR UNCD7 0;
    #     COM_BNDNET / COM_BNDPRD ... COM_TS RCS_COMTS UNCD7;  IRE_BND ... 'ALL_R,IE,' ... COM_TS RCS_COMTS UNCD7 EPS
    _bd_guard(db, "ACT_BND", ["p"], "PRC_TS", "RTP", "eps")
    _bd_guard(db, "FLO_FR", ["p", "c"], "RPCS_VAR", "RTP", 0)
    _bd_guard(db, "COM_BNDNET", ["c"], "COM_TS", "RTC", None)
    _bd_guard(db, "COM_BNDPRD", ["c"], "COM_TS", "RTC", None)
    _bd_guard(db, "IRE_BND", ["c"], "COM_TS", "RTC", "eps")
    # --- Add bounds based on rate levels (per hour: times G_YRFR*8760)
    if db.card("FLO_BDLVL"):
        # --- FLO_BDLVL(RTP,CG,S,BD)$FLO_BND(RTP,CG,S,BD) = 0;
        db.x("delete from FLO_BDLVL a where in_RTP(a.r,a.y,a.p) and in_FLO_BND(a.r,a.y,a.p,a.cg,a.s,a.l)")
        lvl = "a.value * v_G_YRFR(a.r,a.s) * 8760"
        # --- FLO_BND(RTPC(R,T,P,C),S,BD)$(RPCS_VAR(R,P,C,S)$FLO_BDLVL(RTPC,S,BD)) = FLO_BDLVL(RTPC,S,BD)*G_YRFR(R,S)*8760;
        db.put("FLO_BND", f"""select a.r, a.y, a.p, a.cg, a.s, a.l, {lvl} as value from FLO_BDLVL a
                              where in_RTPC(a.r,a.y,a.p,a.cg) and in_RPCS_VAR(a.r,a.p,a.cg,a.s)""", zero="eps")
        # --- FLO_BND(RTP(R,T,P),CG(COM_TYPE),S,BD)$(PRC_TS(R,P,S)$RP_IRE(R,P)$FLO_BDLVL(RTP,CG,S,BD)) = FLO_BDLVL(RTP,CG,S,BD)*G_YRFR(R,S)*8760;
        db.put("FLO_BND", f"""select a.r, a.y, a.p, a.cg, a.s, a.l, {lvl} as value from FLO_BDLVL a
                              where in_RTP(a.r,a.y,a.p) and in_COM_TYPE(a.cg) and in_PRC_TS(a.r,a.p,a.s) and in_RP_IRE(a.r,a.p)""", zero="eps")
        # --- ACT_BND(RTP(R,T,P),S,BD)$((RP_STG(R,P)->0)$PRC_TS(R,P,S)$FLO_BDLVL(RTP,%PGPRIM%,S,BD)) = FLO_BDLVL(RTP,%PGPRIM%,S,BD)*G_YRFR(R,S)*8760;
        db.put("ACT_BND", f"""select a.r, a.y, a.p, a.s, a.l, {lvl} as value from FLO_BDLVL a
                              where a.cg = 'ACT' and in_RTP(a.r,a.y,a.p) and not in_RP_STG(a.r,a.p) and in_PRC_TS(a.r,a.p,a.s)""", zero="eps")
    bot, eot = str(db.ctl["BOTIME"]), str(db.ctl["EOTIME"])
    f = lambda c: _eoh(c).replace("{BOT}", bot).replace("{EOT}", eot)
    yr = lambda c: f"in_ALLYEAR({c}) and {c} <> '0'"
    # --- UC_CUMFLO(UC_N,R,P,C,BOHYEAR+BEOH(BOHYEAR),EOHYEAR+BEOH(EOHYEAR)) $= UC_CUMFLO(UC_N,R,P,C,BOHYEAR,EOHYEAR);
    #     UC_CUMFLO(..,BOHYEAR,EOHYEAR)$(NOT LL(BOHYEAR)*LL(EOHYEAR)) = 0;
    #     UC_CUMFLO(UC_N,R,P,%PGPRIM%,..) $= UC_CUMACT(UC_N,R,P,BOHYEAR,EOHYEAR);
    db.put("UC_CUMFLO", f"select uc, r, p, c, {f('u')} as u, {f('u2')} as u2, value from UC_CUMFLO where in_REG(r)", zero="eps")
    db.zap("UC_CUMFLO", f"not ({yr('u')} and {yr('u2')})")
    db.put("UC_CUMFLO", f"select uc, r, p, 'ACT' as c, {f('u')} as u, {f('u2')} as u2, value from UC_CUMACT where in_REG(r)", zero="eps")
    # --- LOOP((UC_N,RP,C,YEAR,LL)$UC_CUMFLO(UC_N,RP,C,YEAR,LL),RPC_CUMFLO(RP,C,YEAR,LL)=YES);
    db.add("RPC_CUMFLO", "select distinct r, p, c, u as y, u2 as y2 from UC_CUMFLO where in_RP(r,p)")
    # --- FLO_CUM(R,P,C,BOHYEAR+BEOH(BOHYEAR),EOHYEAR+BEOH(EOHYEAR),L) $= FLO_CUM(R,P,C,BOHYEAR,EOHYEAR,L);  ... ACT_CUM
    db.put("FLO_CUM", f"select r, p, c, {f('u')} as u, {f('u2')} as u2, l, value from FLO_CUM where in_REG(r)", zero="eps")
    db.zap("FLO_CUM", f"not ({yr('u')} and {yr('u2')})")
    db.put("FLO_CUM", f"select r, p, 'ACT' as c, {f('u')} as u, {f('u2')} as u2, l, value from ACT_CUM where in_REG(r)", zero="eps")
    # --- RPC_CUMFLO(RP,C,YEAR,LL) $= SUM(L$FLO_CUM(RP,C,YEAR,LL,L),YES);  OPTION CLEAR=UC_CUMACT,CLEAR=ACT_CUM;
    db.add("RPC_CUMFLO", "select distinct r, p, c, u as y, u2 as y2 from FLO_CUM where in_RP(r,p)")
    db.clear("UC_CUMACT", "ACT_CUM")
    # --- UC_CUMCOM(UC_N,R,COM_VAR,C,..) ...;  LOOP(.., RC_CUMCOM(R,COM_VAR,YEAR,LL,C)=YES);
    db.put("UC_CUMCOM", f"select uc, r, cv, c, {f('u')} as u, {f('u2')} as u2, value from UC_CUMCOM where in_REG(r)", zero="eps")
    db.zap("UC_CUMCOM", f"not ({yr('u')} and {yr('u2')} and in_RC(r,c))")
    db.add("RC_CUMCOM", "select distinct r, cv, u as y, u2 as y2, c from UC_CUMCOM")
    # --- COM_CUM(R,'NET',YEAR(..),LL(..),C,L) $= COM_CUMNET(R,BOHYEAR,EOHYEAR,C,L);  ... 'PRD' ... COM_CUMPRD
    for cv, src in (("NET", "COM_CUMNET"), ("PRD", "COM_CUMPRD")):
        db.put("COM_CUM", f"""select r, '{cv}' as cv, {f('y')} as y, {f('y2')} as y2, c, l, value from "{src}"
                              where in_REG(r) and {yr(f('y'))} and {yr(f('y2'))}""", zero="eps")
    db.clear("COM_CUMNET", "COM_CUMPRD")
    # --- RC_CUMCOM(R,COM_VAR,YEAR,LL(EOHYEAR),C) $= SUM(L$COM_CUM(R,COM_VAR,YEAR,LL,C,L),YES);
    db.add("RC_CUMCOM", "select distinct r, cv, y, y2, c from COM_CUM where in_REG(r)")


INF = float("inf")


FREE = {"VAR_UC", "VAR_UCR", "VAR_UCT", "VAR_UCRT", "VAR_UCTS", "VAR_UCRTS"}


def _bounds(db: DB, var, keysel, par, parkey, cond="true"):
    """bnd_set.mod / bnd_ucv.mod:  V.LO $= P(..,'LO');  V.UP $= P(..,'UP');  V.FX $= P(..,'FX');
    keysel  SQL expressions (on a row `a` of the bound parameter) giving the variable indexes
    parkey  the columns of the parameter other than the bound type that identify the variable"""
    n = len(keysel)
    cols = ", ".join(f"d{i} VARCHAR" for i in range(n))
    db.x(f'create table if not exists "B_{var}" ({cols}, lower DOUBLE, upper DOUBLE)')
    lo0 = "'-inf'::double" if var in FREE else "0"
    sel = ", ".join(f"{e} as d{i}" for i, e in enumerate(keysel))
    grp = ", ".join(f"a.{c}" for c in parkey)
    db.x(f"""insert into "B_{var}"
             select {sel},
                    coalesce(max(case when a.l='FX' then a.value end), max(case when a.l='LO' then a.value end), {lo0}) as lower,
                    coalesce(max(case when a.l='FX' then a.value end), max(case when a.l='UP' then a.value end), 'inf'::double) as upper
             from "{par}" a where a.l in ('LO','UP','FX') and ({cond}) group by {grp}""")
    db.bounds.add(var)


def variable_bounds(db: DB):
    db.bounds = getattr(db, "bounds", set())
    # ---- mod_vars.mod (before bndmain.mod): $BATINCLUDE powerflo.vda DECL       (grid control sets and bounds)
    grids.decl(db)
    # ---- mod_vars.dsc: the bounds of the semi-continuous VAR_SNCAP
    dsc.bounds(db)
    # ---- mod_vars.abs: default BS_CAPACT, the bounds of VAR_COMLV and VAR_BSPRS   (main_ext.mod: VDA before ABS)
    abs_ext.mod_vars(db)
    # ---- bndmain.mod 20-21: $IF %TIMESED%==YES $BATINCLUDE bnd_elas.mod   (the steps of the elastic demands)
    if db.ctl.get("TIMESED"):
        elastic.bnd_elas(db)
    # ---- eqmain.mod
    if db.card("UC_TIME") or db.card("UC_UCN"):
        db.ctl["VAR_UC"] = True
    if not db.ctl["VAR_UC"]:
        unsupported(db, "user constraints without slack variables (VAR_UC not YES)")
    # --- LOOP(OBJ_2A(R,T,P)$(NOT RTP_OFF(R,T,P)),F=B(T)+NCAP_ILED(R,T,P); Z=SUM(VNT(T,TT)$(F>E(TT)+0.5),1); RVPT(R,T,P,T+Z) = YES);
    #     RTP_OFF(OBJ_2A(R,T,P))$(NOT SUM(RVPT(R,T,P,TT),1)) = YES;               commissioned after the horizon: no investment
    db.x("""create or replace temp table t_rvpt as
            select a.r, a.y, a.p, (select count(*) from VNT n where n.y=a.y and v_B(a.y) + v_NCAP_ILED(a.r,a.y,a.p) > v_E(n.y2) + 0.5) as z
            from OBJ_2A a where in_MILESTONYR(a.y) and not in_RTP_OFF(a.r,a.y,a.p)""")
    db.x("""create or replace temp table t_ord as select y, row_number() over (order by yv(y)) as o from MILESTONYR""")
    db.assign("RVPT", """select k.r, k.y, k.p, n.y as y2 from t_rvpt k join t_ord o on o.y=k.y join t_ord n on n.o = o.o + k.z""")
    db.add("RTP_OFF", """select a.r, a.y, a.p from OBJ_2A a where in_MILESTONYR(a.y)
                         and not exists(select 1 from RVPT v where v.r=a.r and v.y=a.y and v.p=a.p)""")
    # --- OPTION UC_RTSUC < UC_T_SUCC, UC_RHSMAP < UC_RHSTMP, UC_UT < UC_RHST, UC_UTS < UC_RHSTS;
    db.assign("UC_RTSUC", "select distinct r, y, uc from UC_T_SUCC")
    db.assign("UC_UT", "select distinct uc, y from UC_RHST")
    db.assign("UC_UTS", "select distinct uc, y, s from UC_RHSTS")
    # --- UC_RHSTMP(R_UCT(R_UC(R,UC_N),T),ANNUAL,'SEVERAL')$UC_T_EACH(R,UC_N,T) = YES;   ('DYNAMIC' with UC_T_SUCC)
    #     UC_RHSTMP(RUCTS(UC_T_EACH(UC_R_EACH(R,UC_N),T),S),'EACH')$UC_TS_EACH(R,UC_N,S) = YES;   ('SUCC' with UC_T_SUCC)
    #     OPTION UC_RHSMAP < UC_RHSTMP;
    #     UC_RHSTMP(RUCTS(UC_T_EACH(..)),UC_NUMBER(TSL))$(TS_GROUP(R,TSL,S)$UC_DS(R,UC_N,TSL)) = YES;      (constraints on a timeslice level)
    db.assign("UC_RHSMAP", """
        select distinct h.r, h.y, h.uc, case when in_UC_T_SUCC(h.r,h.uc,h.y) then 'DYNAMIC' else 'SEVERAL' end as uc_number, 'ANNUAL' as s
        from UC_RHSRT h
        where in_REG(h.r) and in_MILESTONYR(h.y) and (in_UC_T_EACH(h.r,h.uc,h.y) or in_UC_T_SUCC(h.r,h.uc,h.y))
          and exists(select 1 from UC_TS_SUM x where x.r=h.r and x.uc=h.uc)
        union
        select distinct h.r, h.y, h.uc, case when in_UC_T_SUCC(h.r,h.uc,h.y) then 'SUCC' else 'EACH' end, h.s from UC_RHSRTS h
        where in_REG(h.r) and in_MILESTONYR(h.y) and (in_UC_T_EACH(h.r,h.uc,h.y) or in_UC_T_SUCC(h.r,h.uc,h.y)) and in_UC_R_EACH(h.r,h.uc)
          and in_UC_TS_EACH(h.r,h.uc,h.s)
        union
        select distinct h.r, h.y, h.uc, g.tsl, h.s from UC_RHSRTS h join TS_GROUP g on g.r=h.r and g.s=h.s
        where in_REG(h.r) and in_MILESTONYR(h.y) and in_UC_T_EACH(h.r,h.uc,h.y) and in_UC_R_EACH(h.r,h.uc) and in_UC_DS(h.r,h.uc,g.tsl)""")
    # ---- eqcapact.mod:  LOOP(V,AFS(RTP_VARA(R,T,P),S,BD)$COEF_AF(R,V,T,P,S,BD)=YES); AFS(RTPS_OFF,BD) = NO;
    db.assign("AFS", "select distinct r, y2 as y, p, s, l from COEF_AF where in_RTP_VARA(r,y2,p)")
    db.remove("AFS", where="in_RTPS_OFF(r,y,p,s)")
    # ---- eqmain.mod: $IF DEFINED PRC_SIMV $INCLUDE coef_csv.mod      (simulated vintages: COEF_CSV, RTP_VINTYR, AFSV)
    simv.coef_csv(db)

    # ---- equ_ext.vda:  AFS(RTP(R,T,P),S,BDUPX)$NCAP_AFCS(RTP,'ACT',S) = NO;
    db.remove("AFS", where="l in ('FX','UP') and in_RTP(r,y,p) and in_NCAP_AFCS(r,y,p,'ACT',s)")
    # ---- equ_ext.vda:  RP_PL(RP,BD)$SUM(RPG_PACE(RP,CG),1) = NO;       (BD: LO, UP, FX; the N of partial loads stays)
    db.remove("RP_PL", where="l in ('LO','UP','FX') and exists(select 1 from RPG_PACE g where g.r=RP_PL.r and g.p=RP_PL.p)")
    # ---- eqactups.vda:  IF(CARD(RP_UPL)+CARD(RP_PL)+CARD(ACT_CSTRMP), ...);  OPTION RP_UPR < ACT_CSTRMP;
    #     (RP_PL(R,P,'UP') marks a storage with a cycle limit; N and FX partial loads, from ACT_LOSPL (ppm_ext.vda) or
    #      from a start-up cost on ANNUAL (below))
    #     (the whole block runs only when CARD(RP_UPL)+CARD(RP_PL)+CARD(ACT_CSTRMP): a start-up or partial-load cost
    #      (ACT_CSTPL) on a process without a minimum load or partial loads sets nothing)
    ups_block = db.card("RP_UPL") + db.card("RP_PL") + db.card("ACT_CSTRMP") > 0
    if db.card("RP_UPL"):
        # --- AFUPS(R,T,P,S)$((NOT RPS_CAFLAC(R,P,S,'UP'))$PRC_TS(R,P,S)) $= AFS(R,T,P,S,'UP')$RP_UPL(R,P,'FX'); AFS(AFUPS,BD)=NO;
        #     (a dispatchable process: the availability rows give way to the load rows EQ_CAPLOAD)
        db.add("AFUPS", """select r, y, p, s from AFS where l = 'UP' and in_RP_UPL(r,p,'FX') and in_PRC_TS(r,p,s)
                           and not in_RPS_CAFLAC(r,p,s,'UP')""")
        db.remove("AFS", where="in_AFUPS(r,y,p,s)")
        # --- RPS_UPS(R,P,S)$((STOAL(R,S)<2+1$RP_UPR(R,P,'N'))$RP_UPL(R,P,'FX')) =
        #        SUM(PRC_TS(R,P,TS)$RS_BELOW(R,S,TS),RS_BELOW1(R,S,TS) OR STOA(S));
        #     (the timeslices that carry the off-line capacity: those directly above the process timeslices)
        cond = "u.l = 'FX' and v_STOAL(u.r,t.s) < 2 + (case when in_RP_UPR(u.r,u.p,'N') then 1 else 0 end)"
        db.remove("RPS_UPS", select=f"select u.r, u.p, t.s from RP_UPL u, ALL_TS t where {cond}")
        db.add("RPS_UPS", f"""select u.r, u.p, t.s from RP_UPL u, ALL_TS t where {cond}
                              and exists(select 1 from PRC_TS k where k.r=u.r and k.p=u.p and in_RS_BELOW(u.r,t.s,k.s)
                                         and (in_RS_BELOW1(u.r,t.s,k.s) or v_STOA(t.s) <> 0))""")
        # --- RP_UX(RP)$(NOT PRC_VINT(RP))$=RP_UPL(RP,'FX'); RTP_VARP(RTP(R,T,P))$RP_UX(R,P)=YES;
        db.add("RP_UX", "select r, p from RP_UPL where l = 'FX' and not in_PRC_VINT(r,p)")
        db.add("RTP_VARP", "select r, y, p from RTP where in_MILESTONYR(y) and in_RP_UX(r,p)")
        # --- COEF_AF(R,T,T,P,S,'UP')$AFUPS(R,T,P,S) $= NCAP_AF(R,T,P,S,'UP')$RP_UX(R,P);
        db.put("COEF_AF", """select a.r, a.y, a.y as y2, a.p, a.s, 'UP' as l, n.value from AFUPS a
                             join NCAP_AF n on n.r=a.r and n.y=a.y and n.p=a.p and n.s=a.s and n.l='UP'
                             where in_RP_UX(a.r,a.p)""", zero="eps")
        # --- $ BATINCLUDE pp_lvlfc.mod ACT_UPS P PRC_TS ',BD' ",'','',''" ALL_TS V RTP(R,V,P) 0 '' N
        #     (ramp rates given by timeslice brought to the process's timeslices, as FLO_ASHAR is; a year-0 record
        #      left at this point would mix with the flags the levelling writes on year 0, and stops; the tail index
        #      is BD, so the rows of 'N' are left as they are)
        if db.q1("select count(*) from ACT_UPS where y = '0'"):
            unsupported(db, "ramp rates or minimum loads with a year-0 record left after interpolation (ACT_UPS levelling, eqactups.vda)", ["ACT_UPS"])
        from ..lvl import lvlfc
        lvlfc(db, "ACT_UPS", ["p"], "PRC_TS", "MODLYEAR", "in_RTP(a.r,a.y,a.p)", fill="N", dom="a.l in ('LO','UP','FX')")
    if ups_block and db.card("ACT_CSTUP"):
        # --- UNCD7(R,LL--ORD(LL),P,TSL,RDCUR(R,CUR),'UP') $= ACT_CSTUP(R,LL,P,TSL,CUR);
        #     LOOP(UNCD7(R,LL,P,ITEM,R,CUR,L),RP_UPS(R,P,TSL(ITEM),L)$(TSLVLNUM(TSL)$RP_UPL(R,P,'FX')>1)=YES; RPC_CUR(R,P,%PGPRIM%,CUR)=YES);
        #     (a start-up cost on a level above ANNUAL: start-ups are counted on that level)
        db.tmp("t_up", "select distinct r, p, tsl, cur from ACT_CSTUP where in_RDCUR(r,cur)")
        db.add("RP_UPS", "select r, p, tsl, 'UP' as l from t_up where in_TSLVL(tsl) and in_RP_UPL(r,p,'FX') and v_TSLVLNUM(tsl) > 1")
        db.add("RPC_CUR", "select r, p, 'ACT' as c, cur from t_up")
        # --- RP_UPS(RP,TSL,L)$SUM(PRC_TSL(RP,TSLVL)$(ORD(TSL)>ORD(TSLVL)),1)=NO;        (not on a level finer than the process)
        db.remove("RP_UPS", where="""exists(select 1 from PRC_TSL k where k.r="RP_UPS".r and k.p="RP_UPS".p
                                            and ord_tsl("RP_UPS".tsl) > ord_tsl(k.tsl))""")
        # --- RPS_UPS(RP,S)$SUM(RP_UPS(PRC_TSL(RP,TSL),L),1)=NO;  RPS_UPS(R,P,S) $= SUM(RP_UPS(R,P,TSL,L)$TS_GROUP(R,TSL,S),1);
        #     (started capacity is carried on the timeslices of the start-up level instead of those above the process)
        db.remove("RPS_UPS", where="""exists(select 1 from RP_UPS u join PRC_TSL k on k.r=u.r and k.p=u.p and k.tsl=u.tsl
                                             where u.r="RPS_UPS".r and u.p="RPS_UPS".p)""")
        db.add("RPS_UPS", "select u.r, u.p, g.s from RP_UPS u join TS_GROUP g on g.r=u.r and g.tsl=u.tsl")
        # --- RP_UPS(R,P,TSL,LNX(L))$RP_UPS(R,P,TSL,'UP') = SUM(RP_UPS(R,P,TSLVL,BD),RLUP(R,TSLVL,TSL)$BD(L)+RLUP(R,TSL,TSLVL)$IPS(L));
        #     (FX on a level with start-ups on the level below, N with start-ups on the level above; evaluated on the set
        #      as it was before the statement)
        db.tmp("t_ups", "select * from RP_UPS")
        db.tmp("t_lnx", """select u.r, u.p, u.tsl, x.l,
                 exists(select 1 from t_ups w where w.r=u.r and w.p=u.p and w.l in ('LO','UP','FX') and
                        ((x.l='FX' and in_RLUP(u.r,w.tsl,u.tsl)) or (x.l='N' and in_RLUP(u.r,u.tsl,w.tsl)))) as yes_
                 from t_ups u, (select 'FX' as l union all select 'N') x where u.l = 'UP'""")
        db.remove("RP_UPS", select="select r, p, tsl, l from t_lnx")
        db.add("RP_UPS", "select r, p, tsl, l from t_lnx where yes_")
        # --- RP_UPS(R,P,TSL,'FX')$(SUM(RP_UPS(PRC_TSL(R,P,TSLVL),L),RLUP(R,TSLVL,TSL))$RP_UPR(R,P,'UP'))=YES;
        #     (with a minimum on-line time: the level above the process carries the balance of on-line capacity)
        db.add("RP_UPS", """select distinct u.r, u.p, l.tsl2 as tsl, 'FX' as l from RP_UPS u
                            join PRC_TSL k on k.r=u.r and k.p=u.p and k.tsl=u.tsl
                            join RLUP l on l.r=u.r and l.tsl=u.tsl where in_RP_UPR(u.r,u.p,'UP')""")
        # --- LOOP(UNCD7(R,LL,P,TSL(ANNUAL),R,CUR,L),RP_UPS(R,P,TSL,L)=YES; RP_PL(R,P,'N')=NOT RP_PL(R,P,L));
        #     (a start-up cost on ANNUAL: the cycling penalty of a storage with a cycle limit (RP_PL UP); otherwise partial
        #      loads, RP_PL N)
        db.add("RP_UPS", "select distinct r, p, tsl, 'UP' as l from t_up where tsl='ANNUAL'")
        db.remove("RP_PL", where="l='N' and exists(select 1 from t_up u where u.r=RP_PL.r and u.p=RP_PL.p and u.tsl='ANNUAL') and in_RP_PL(r,p,'UP')")
        db.add("RP_PL", "select distinct r, p, 'N' as l from t_up where tsl='ANNUAL' and not in_RP_PL(r,p,'UP')")
        # --- RP_UPC(R,P,TSL,'N')$RP_UPR(R,P,'N') $= SUM(RP_UPS(PRC_TSL(R,P,TSLVL),L),RLUP(R,TSLVL,TSL));
        #     RP_UPC(PRC_TSL(RP,TSL),BDNEQ(BD))$RP_UPS(RP,TSL,'UP') $= RP_UPR(RP,BD));
        #     (cycle limits, and minimum on-line (UP) / off-line (LO) times)
        db.add("RP_UPC", """select distinct u.r, u.p, l.tsl2 as tsl, 'N' as l from RP_UPS u
                            join PRC_TSL k on k.r=u.r and k.p=u.p and k.tsl=u.tsl
                            join RLUP l on l.r=u.r and l.tsl=u.tsl where in_RP_UPR(u.r,u.p,'N')""")
        db.add("RP_UPC", """select k.r, k.p, k.tsl, b.l from PRC_TSL k, (select 'LO' as l union all select 'UP') b
                            where in_RP_UPS(k.r,k.p,k.tsl,'UP') and in_RP_UPR(k.r,k.p,b.l)""")
    if db.q1("select count(*) from RP_PL where l='N'"):
        # --- ACT_LOSPL(RTP(R,V,P),BDNEQ(BD))$((ACT_LOSPL(RTP,BD)<=0)$RP_PL(R,P,'N')) = MAX(.1+.5$BDUPX(BD),ACT_MINLD(RTP));
        #     (the loads at which the partial-load losses start (LO) and end (UP), when not given or not positive)
        db.put("ACT_LOSPL", """select k.r, k.y, k.p, b.l, greatest(b.d, coalesce(v_ACT_MINLD(k.r,k.y,k.p), 0)) as value
                               from RTP k, (select 'LO' as l, 0.1 as d union all select 'UP', 0.6) b
                               where in_RP_PL(k.r,k.p,'N') and coalesce(v_ACT_LOSPL(k.r,k.y,k.p,b.l), 0) <= 0""")
        # --- RTP_PL(RTP(R,V,P))$((ACT_LOSPL(RTP,'LO')=ACT_MINLD(RTP))$RP_UPL(R,P,'FX')) $= RP_PL(R,P,'N');
        #     (the vintages whose losses start at the minimum load: EQ_CAPLOAD takes the partial-load variable)
        db.add("RTP_PL", """select k.r, k.y, k.p from RTP k where in_RP_UPL(k.r,k.p,'FX') and in_RP_PL(k.r,k.p,'N')
                            and coalesce(v_ACT_LOSPL(k.r,k.y,k.p,'LO'), 0) = coalesce(v_ACT_MINLD(k.r,k.y,k.p), 0)""")
    if db.card("ACT_CSTRMP"):
        # (with RP_UPL, RP_PL and ACT_CSTUP empty, what is left of the block is the ramping costs)
        # --- UNCD7(R,LL--ORD(LL),P,BD,RDCUR(R,CUR),'N') $= ACT_CSTRMP(R,LL,P,BD,CUR);
        #     LOOP(UNCD7(R,LL,P,ITEM,R,CUR,L), ...; RPC_CUR(R,P,%PGPRIM%,CUR)=YES);
        db.add("RPC_CUR", "select distinct a.r, a.p, 'ACT' as c, a.cur from ACT_CSTRMP a where in_RDCUR(a.r,a.cur)")
    # --- OPTION RP_UPR < ACT_CSTRMP;       (after the IF block, so always: it replaces what init_ext.vda took from ACT_TIME)
    db.assign("RP_UPR", "select distinct r, p, l from ACT_CSTRMP")
    # ---- eqlducs.vda EQU: a process dispatched by start-up type (RP_DP) leaves the simple start-up controls
    if db.card("RP_DP"):
        # --- RP_UPS(RP_DP,TSL,L)=NO; RP_UPC(RP_DP,TSL,BD)=NO; AFUPS(R,T,P,S)$RP_DP(R,P)=NO; RPS_UPS(PRC_TS(RP_DP,S))=YES;
        db.remove("RP_UPS", where="in_RP_DP(r,p)")
        db.remove("RP_UPC", where="in_RP_DP(r,p) and l in ('LO','UP','FX')")
        db.remove("AFUPS", where="in_RP_DP(r,p)")
        db.add("RPS_UPS", "select r, p, s from PRC_TS where in_RP_DP(r,p)")
        # --- RP_UX(RP)$(NOT PRC_VINT(RP))$=RP_DP(RP); RTP_VARP(RTP(R,T,P))$RP_UX(R,P)=YES;
        db.add("RP_UX", "select r, p from RP_DP where not in_PRC_VINT(r,p)")
        db.add("RTP_VARP", "select r, y, p from RTP where in_MILESTONYR(y) and in_RP_UX(r,p)")
        # --- RP_UPS(RP_DP(R,P),TSL,'FX')$=SUM(RLUP(R,TSLVL,TSL)$PRC_TSL(R,P,TSLVL),1);   (the levels above the process)
        db.add("RP_UPS", """select distinct k.r, k.p, u.tsl2 as tsl, 'FX' as l from PRC_TSL k
                            join RLUP u on u.r=k.r and u.tsl=k.tsl where in_RP_DP(k.r,k.p)""")
    # ---- equ_ext.vda: $IF DEFINED UC_FLOBET $BATINCLUDE UCBET.vda   (maximum flows and activities of user constraints)
    ucbet.equa(db)
    # ---- equ_ext.vda: $IF DEFINED GR_VARGEN $BATINCLUDE resloadc.vda EQUA
    resloadc.equa(db)
    # ---- equ_ext.abs: the final preprocessing of the ancillary balancing services
    abs_ext.equ_ext(db)

    # ---- bndmain.mod
    # --- bnd_cum.mod 43-48: the bounds of VAR_CUMCST (REG_CUMCST as eqbndcst.mod left it: the objective step)
    bndcst.bounds(db, getattr(db, "bndcst", None))
    # --- bnd_act.mod: VAR_ACT.LO/UP/FX(RTP_VINTYR(R,T,T,P),S)$(PRC_TS(R,P,S)*(NOT PRC_VINT(R,P))) $= ACT_BND(R,T,P,S,bd);
    _bounds(db, "VAR_ACT", ["a.r", "a.y", "a.y", "a.p", "a.s"], "ACT_BND", ["r", "y", "p", "s"],
            "in_RTP_VINTYR(a.r,a.y,a.y,a.p) and in_MILESTONYR(a.y) and in_PRC_TS(a.r,a.p,a.s) and not in_PRC_VINT(a.r,a.p)")
    # --- VAR_ACT.UP(RTP_VINTYR(R,V,T,P),S)$(PRC_TS(R,P,S) * PRC_VINT(R,P)$RTPS_OFF(R,T,P,S)) = EPS;
    #     (a vintaged process turned off: RTPS_OFF, REDUCE YES or timeslices off by DYNTS; its rows have no ACT_BND bound)
    db.tmp("t_off", """select k.r, k.y, k.y2, k.p, o.s from RTP_VINTYR k join RTPS_OFF o on o.r=k.r and o.y=k.y2 and o.p=k.p
                       where in_PRC_TS(k.r,k.p,o.s) and in_PRC_VINT(k.r,k.p)""")
    reduce.set_bound(db, "t_off", "upper", "0.0")
    # --- bnd_flo.mod
    # --- FLO_BND(R,T,P,C,S,'LO')$((NOT RPC_EMIS(R,P,C))$(FLO_BND(R,T,P,C,S,'LO')=0)$RP_FLO(R,P))=0;
    db.zap("FLO_BND", "l='LO' and value = 0 and in_MILESTONYR(y) and in_COM(cg) and in_RP_FLO(r,p) and not in_RPC_EMIS(r,p,cg)")
    # --- LOOP((RTPC(R,T,P,C),S,BD)$FLO_BND(RTPC,S,BD),TRACKPC(RP_FLO(R,P),C)=YES);
    #     TRACKPC(PRC_VINT(R,P),C) = NO; TRACKPC(RPC_FFUNC(R,P,C))= NO; TRACKPC(RPC_EMIS(R,P,C)) = NO;
    bd = "l in ('LO','UP','FX')"
    db.tmp("t_pc", f"""select distinct r, p, cg as c from FLO_BND where {bd} and in_RTPC(r,y,p,cg) and in_RP_FLO(r,p)
                       and not in_PRC_VINT(r,p) and not in_RPC_FFUNC(r,p,cg) and not in_RPC_EMIS(r,p,cg)""")
    # --- LOOP(T,FLO_BND(R,'0',P,C,S,BD)$FLO_BND(R,T,P,C,S,BD) = EPS$(NOT TRACKPC(R,P,C));
    #            FLO_BND(R,'0',P,CG,S,BD)$((NOT C(CG))$FLO_BND(R,T,P,CG,S,BD)) = EPS);          bounds that need an equation are flagged on year 0
    db.x(f"""create or replace temp table t_flag as select distinct r, p, cg, s, l,
               (in_COM(cg) and exists(select 1 from t_pc k where k.r=f.r and k.p=f.p and k.c=f.cg)) as direct
             from FLO_BND f where {bd} and in_MILESTONYR(y) and in_REG(r)""")
    db.x("""delete from FLO_BND a where y='0' and exists(select 1 from t_flag f where f.r=a.r and f.p=a.p and f.cg=a.cg and f.s=a.s and f.l=a.l)""")
    db.put("FLO_BND", "select r, '0' as y, p, cg, s, l, 0 as value from t_flag where not direct", zero="eps")
    # --- TRACKPC(RPC_ACT(R,P,C)) = NO;
    db.x("delete from t_pc where in_RPC_ACT(r,p,c)")
    # --- VAR_FLO.LO/UP/FX(RTP_VINTYR(R,T,T,P),C,S)$((RTPCS_VARF(R,T,P,C,S)*TRACKPC(R,P,C))$FLO_BND(R,T,P,C,S,bd)) = FLO_BND(R,T,P,C,S,bd);
    _bounds(db, "VAR_FLO", ["a.r", "a.y", "a.y", "a.p", "a.cg", "a.s"], "FLO_BND", ["r", "y", "p", "cg", "s"],
            """in_MILESTONYR(a.y) and in_RTP_VINTYR(a.r,a.y,a.y,a.p) and in_RTPCS_VARF(a.r,a.y,a.p,a.cg,a.s)
               and exists(select 1 from t_pc k where k.r=a.r and k.p=a.p and k.c=a.cg)""")
    # --- $IF NOT '%REDUCE%' == 'YES' $EXIT     (the bounds of flows replaced by the activity)
    reduce.flow_bounds(db)
    # --- bnd_stg.mod  (SIN: STGIN_BND, IN, 0;  SOUT: STGOUT_BND, OUT, -INF)
    for var, par, io in (("VAR_SIN", "STGIN_BND", "IN"), ("VAR_SOUT", "STGOUT_BND", "OUT")):
        if var == "VAR_SOUT":
            # --- VAR_SOUT.LO(RTP_VINTYR(R,V,T,P),%PGPRIM%,S)$((RPS_STG(R,P,S)->0)$RP_STS(R,P)) = -INF;
            #     (flexible timeslice storage: the output "flow" of the activity on the timeslices that are not those of
            #      the process is a free variable, the balance carried between the storage levels)
            db.x('create table if not exists "B_VAR_SOUT" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, d5 VARCHAR, lower DOUBLE, upper DOUBLE)')
            db.x("""insert into "B_VAR_SOUT" select k.r, k.y, k.y2, k.p, 'ACT', t.s, '-inf'::double, 'inf'::double
                    from RTP_VINTYR k, ALL_TS t where in_RP_STS(k.r,k.p) and not in_RPS_STG(k.r,k.p,t.s)""")
        # --- STGxx_BND(R,T,P,C,S,BD)$((NOT TOP(R,P,C,'IN'/'OUT'))$RP_STG(R,P)) = 0;
        db.zap(par, f"in_MILESTONYR(y) and in_RP_STG(r,p) and in_COM(c) and {bd} and not in_TOP(r,p,c,'{io}')")
        # --- TRACKP(RP(R,P))$((NOT PRC_VINT(R,P))$PRC_MAP(R,'STG',P)) = YES;
        #     VAR_Sxx.LO/UP/FX(RTP_VINTYR(R,T,T,P),C,S)$(RPCS_VAR(R,P,C,S)$TRACKP(R,P)) $= STGxx_BND(R,T,P,C,S,bd);
        _bounds(db, var, ["a.r", "a.y", "a.y", "a.p", "a.c", "a.s"], par, ["r", "y", "p", "c", "s"],
                """in_MILESTONYR(a.y) and in_RTP_VINTYR(a.r,a.y,a.y,a.p) and in_RPCS_VAR(a.r,a.p,a.c,a.s)
                   and in_RP(a.r,a.p) and not in_PRC_VINT(a.r,a.p) and in_PRC_MAP(a.r,'STG',a.p)""")
    ncap_bounds(db)
    cap_bounds(db)
    com_bounds(db)
    cum_bounds(db)
    uc_bounds(db)
    obj_bounds(db)
    # --- $IF NOT %RTS%==S $BATINCLUDE dynslite.vda BOUNDS
    dynslite.bounds(db)
    # ---- with STAGES every bound above is by SOW (%SWD%, %SOW%, $SW_T(T,SOW)); S_CAP_BND (bnd_set.mod 28-33)
    stochastic.bounds(db)


def ncap_bounds(db: DB, window=False):
    """bndmain.mod: bounds on new capacity (window: in a step of a myopic run, %R_T% = R,SUBT(T))."""
    sub = " and in_SUBT(a.y)" if window else ""
    # --- NCAP_BND(RTP_OFF,'UP') = EPS;
    db.put("NCAP_BND", "select r, y, p, 'UP' as l, 0 as value from RTP_OFF", zero="eps")
    # --- NCAP_BND(RTP(R,T,P),'LO')$(NCAP_BND(RTP,'UP')$NCAP_BND(RTP,'LO')) = SMIN(BDNEQ,NCAP_BND(RTP,BDNEQ));
    db.put("NCAP_BND", """select r, y, p, 'LO' as l, least(v_NCAP_BND(r,y,p,'LO'), v_NCAP_BND(r,y,p,'UP')) as value from RTP
                          where in_MILESTONYR(y) and in_NCAP_BND(r,y,p,'UP') and in_NCAP_BND(r,y,p,'LO')""", zero="eps")
    _bounds(db, "VAR_NCAP", ["a.r", "a.y", "a.p"], "NCAP_BND", ["r", "y", "p"], "in_MILESTONYR(a.y) and in_RP(a.r,a.p)" + sub)


def cap_bounds(db: DB):
    """bndmain.mod: bounds on capacity."""
    # --- CAP_BND(RTP(RTP_VARP),'LO')$CAP_BND(RTP,'UP') = SMIN(BDNEQ,CAP_BND(RTP,BDNEQ));
    #     (SMIN of an absent LO (0) and an EPS UP, or of an EPS LO, is EPS: an EPS LO record)
    db.put("CAP_BND", """select r, y, p, l, value from (
                         select r, y, p, 'LO' as l, least(v_CAP_BND(r,y,p,'LO'), v_CAP_BND(r,y,p,'UP')) as value,
                                (in_CAP_BND(r,y,p,'LO') and v_CAP_BND(r,y,p,'LO') = 0) or v_CAP_BND(r,y,p,'UP') = 0 as eps
                         from RTP_VARP k where in_RTP(r,y,p) and in_CAP_BND(r,y,p,'UP'))
                         where value <> 0 or eps""", zero="eps")
    _bounds(db, "VAR_CAP", ["a.r", "a.y", "a.p"], "CAP_BND", ["r", "y", "p"], "in_MILESTONYR(a.y) and in_RTP(a.r,a.y,a.p)")


def com_bounds(db: DB, window=False):
    """bndmain.mod: bounds on the net and gross production of commodities (window: %R_T% = R,SUBT(T))."""
    sub = " and in_SUBT(a.y)" if window else ""
    _bounds(db, "VAR_COMNET", ["a.r", "a.y", "a.c", "a.s"], "COM_BNDNET", ["r", "y", "c", "s"], "in_RTCS_VARC(a.r,a.y,a.c,a.s)" + sub)
    _bounds(db, "VAR_COMPRD", ["a.r", "a.y", "a.c", "a.s"], "COM_BNDPRD", ["r", "y", "c", "s"], "in_RTCS_VARC(a.r,a.y,a.c,a.s)" + sub)


def cum_bounds(db: DB):
    """bnd_cum.mod: cumulative flow bounds."""
    # --- $IF %STAGES%==YES $SETLOCAL SW1 'S_' SETLOCAL SW2 ",'1'%SOW%"   (the bounds by SOW: prep/stochastic.py)
    if stochastic.tagged(db):
        return stochastic.cum_bounds(db)
    # --- bnd_cum.mod: FLO_CUM
    db.zap("FLO_CUM", "value < 0 and l in ('LO','UP','FX')")
    # --- FLO_CUM(R,P,C,YEAR,'EOH','N') $= FLO_CUM(R,P,C,YEAR,'%EOTIME%','N');
    eot = str(db.ctl["EOTIME"])
    db.put("FLO_CUM", f"select r, p, c, u, 'EOH' as u2, 'N' as l, value from FLO_CUM where l='N' and u2='{eot}'", zero="eps")
    # --- FLO_CUM(RPC_CUMFLO(R,P,C,YEAR,LL),'N') = 0;   (RPC_CUMFLO has every range with a FLO_CUM record, an N included)
    db.zap("FLO_CUM", "l='N' and in_RPC_CUMFLO(r,p,c,u,u2)")
    # --- (MULTI is guarded: the loop over UNCD7 for a flexible horizon gives N = MIN(0,ABS(MULTI(JJ,MIYR_L))-1), which
    #      is 0 with MULTI('1',..) = 1 and no other curve, so the N left on 'EOH' scales no bound)
    # --- FLO_CUM(R,P,C,YEAR,LL,BD)$FLO_CUM(R,P,C,YEAR,LL,'FX') = FLO_CUM(R,P,C,YEAR,LL,'FX')$BDNEQ(BD);
    db.put("FLO_CUM", "select f.r, f.p, f.c, f.u, f.u2, q.l, f.value from FLO_CUM f, BDNEQ q where f.l='FX'", zero="eps")
    db.zap("FLO_CUM", "l='FX'")
    # --- VAR_CUMFLO.LO/UP(R,P,C,YEAR,LL)$FLO_CUM(..,bd) = FLO_CUM(..,bd)*(1/%CUFSCAL%)*(FLO_CUM(..,'N')+1);
    scal = float(db.env.get("CUFSCAL", 10))
    db.x('create table if not exists "B_VAR_CUMFLO" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x(f"""insert into "B_VAR_CUMFLO" select r, p, c, u, u2,
                 coalesce(max(case when l='LO' then value / {scal} end), 0), coalesce(max(case when l='UP' then value / {scal} end), 'inf'::double)
             from FLO_CUM where l in ('LO','UP') group by r, p, c, u, u2""")
    db.bounds.add("VAR_CUMFLO")
    com_cum_bounds(db)


def com_cum_bounds(db: DB):
    """bnd_cum.mod: cumulative bounds on the net or gross production of commodities (COM_CUMNET, COM_CUMPRD)."""
    if not db.card("RC_CUMCOM"):
        return
    if db.ctl["OBJ"] == "LIN":
        unsupported(db, "cumulative commodity bounds with OBJ LIN (eqcumcom.mod weights periods with TPULSE)", ["COM_CUMNET", "COM_CUMPRD"])
    eot = str(db.ctl["EOTIME"])
    # --- COM_CUM(R,COM_VAR,YEAR,'0',C,'N') $= COM_CUM(R,COM_VAR,YEAR,'%EOTIME%',C,'N');
    #     ($= assigns where the source has a record: an N bound given as 0 is EPS and is copied)
    db.put("COM_CUM", f"select r, cv, y, '0' as y2, c, 'N' as l, value from COM_CUM where l='N' and y2='{eot}'", zero="eps")
    # --- COM_CUM(RC_CUMCOM(R,COM_VAR,YEAR,LL,C),'N') = 0;
    db.zap("COM_CUM", "l='N' and in_RC_CUMCOM(r,cv,y,y2,c)")
    # --- COM_CUM(R,COM_VAR,YEAR,LL,C,BD)$COM_CUM(R,COM_VAR,YEAR,LL,C,'FX') = COM_CUM(R,COM_VAR,YEAR,LL,C,'FX')$BDNEQ(BD);
    #     (an EPS FX counts: in a myopic step the EPS of a range dropped in an earlier step moves to LO/UP and the FX goes)
    db.put("COM_CUM", "select f.r, f.cv, f.y, f.y2, f.c, q.l, f.value from COM_CUM f, BDNEQ q where f.l='FX'", zero="eps")
    db.zap("COM_CUM", "l='FX'")
    # --- COM_CUM(RC_CUMCOM(R,COM_VAR,LL,YEAR,C),BD)$(YEARVAL(LL)>MIYR_VL) = EPS;  RC_CUMCOM(R,COM_VAR,LL,YEAR,C)$(YEARVAL(LL)>MIYR_VL) = NO;
    vl = db.s["MIYR_VL"]
    db.put("COM_CUM", f"""select k.r, k.cv, k.y, k.y2, k.c, b.l, 0 as value from RC_CUMCOM k,
                          (select 'LO' as l union all select 'UP' union all select 'FX') b where yv(k.y) > {vl}""", zero="eps")
    db.remove("RC_CUMCOM", where=f"yv(y) > {vl}")
    # --- LOOP((SAMEAS(J,'1'),MIYR_L), UNCD7(RC_CUMCOM(R,COM_VAR,YEAR,'%EOTIME%',C),J+(COM_CUM(R,COM_VAR,YEAR,'0',C,'N')-1),'')=YES;
    #       LOOP(UNCD7(R,COM_VAR,YEAR,LL,C,JJ,''), COM_CUM(R,COM_VAR,YEAR,LL,C,'N') = MIN(0,ABS(MULTI(JJ,MIYR_L))-1)$MULTI(JJ,MIYR_L)));
    #     with MULTI('1') = 1 alone this leaves every N at 0; a user MULTI curve on an N pointer is not ported
    if db.q1(f"""select count(*) from RC_CUMCOM k, COM_CUM n where k.y2 = '{eot}' and n.l = 'N' and n.y2 = '0'
                 and n.r=k.r and n.cv=k.cv and n.y=k.y and n.c=k.c""") and db.q1("select count(*) from MULTI where j <> '1'"):
        unsupported(db, "COM_CUM with bound type 'N' and user MULTI curves (flexible horizon, bnd_cum.mod)")
    # --- COM_CUM(RC_CUMCOM(R,COM_VAR,YEAR,LL,C),'LO')$(NOT COM_CUM(RC_CUMCOM,'LO')) =
    #         -INF$SUM((RTC(R,T,C),ANNUAL(S)),MIN(0,COM_BNDPRD(RTC,S,'LO')$DIAG(COM_VAR,'PRD')+COM_BNDNET(RTC,S,'LO')$DIAG(COM_VAR,'NET')+1-1));
    #     (no lower bound given: the cumulative variable is free when a period has a negative annual lower bound on it)
    db.put("COM_CUM", """select k.r, k.cv, k.y, k.y2, k.c, 'LO' as l, '-inf'::double as value from RC_CUMCOM k
                         where not exists(select 1 from COM_CUM f where f.r=k.r and f.cv=k.cv and f.y=k.y and f.y2=k.y2 and f.c=k.c and f.l='LO' and f.value <> 0)
                           and exists(select 1 from RTC t where t.r=k.r and t.c=k.c and
                                      least(0, case when k.cv='PRD' then coalesce(v_COM_BNDPRD(t.r,t.y,t.c,'ANNUAL','LO'),0)
                                                    else coalesce(v_COM_BNDNET(t.r,t.y,t.c,'ANNUAL','LO'),0) end) < 0)""")
    # --- VAR_CUMCOM.LO/UP(R,C,COM_VAR,YEAR,LL)$COM_CUM(R,COM_VAR,YEAR,LL,C,bd) = COM_CUM(..,bd)*(1/%CUCSCAL%)*(COM_CUM(..,'N')+1);
    scal = float(db.env.get("CUCSCAL", 1000))
    db.x('create table if not exists "B_VAR_CUMCOM" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x(f"""insert into "B_VAR_CUMCOM" select r, c, cv, y, y2,
                 coalesce(max(case when l='LO' then value / {scal} end), 0),
                 coalesce(max(case when l='UP' then value / {scal} end), 'inf'::double)
             from COM_CUM where l in ('LO','UP') group by r, c, cv, y, y2""")
    #     (an EPS entry counts in the $-condition: the bounds of a range after the horizon become 0)
    db.bounds.add("VAR_CUMCOM")


# the objective components (mod_vars.mod: SET OBV / OBJINV, OBJFIX, OBJSAL, OBJVAR /; OBJDAM and OBJBAL come with
# DAMAGE and the power-flow extension, neither of which the port has)
OBV = ("OBJINV", "OBJFIX", "OBJSAL", "OBJVAR")


def obj_bounds(db: DB):
    """bndmain.mod, "Bounds for OBJ components": a user constraint named after an objective component is not a
    constraint but bounds on VAR_OBJ (syssettings of Veda models carry UC_RHS('OBJVAR','N') = -1, a free OBJVAR)."""
    obv = ", ".join(f"'{o}'" for o in OBV)
    # --- UC_TS_SUM(R,UC_N(OBV),S) = NO;
    db.remove("UC_TS_SUM", where=f"uc in ({obv})")
    # --- VAR_OBJ.LO(R,OBV(UC_N),CUR)$UC_RHS(UC_N,'N') = -INF;   VAR_OBJ.LO(R,OBV(UC_N),CUR) $= UC_RHS(UC_N,'LO');
    #     VAR_OBJ.UP(R,OBV(UC_N),CUR) $= UC_RHS(UC_N,'UP');
    #     the same with UC_RHSR(R,UC_N,..), which therefore wins over UC_RHS          (on the currencies of the region)
    g = lambda l: f"(select max(value) from UC_RHS u where u.uc=o.uc and u.l='{l}')"
    rr = lambda l: f"(select max(value) from UC_RHSR u where u.r=d.r and u.uc=o.uc and u.l='{l}')"
    db.x("""create or replace temp table t_obv as select distinct uc from UC_RHS where uc in ({0})
            union select distinct uc from UC_RHSR where uc in ({0})""".format(obv))
    if not db.q1("select count(*) from t_obv"):
        return
    db.x('create table if not exists "B_VAR_OBJ" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x(f"""insert into "B_VAR_OBJ"
             select d.r, o.uc, d.cur,
                    coalesce({rr('LO')}, case when {rr('N')} is not null then '-inf'::double end,
                             {g('LO')}, case when {g('N')} is not null then '-inf'::double end, 0) as lower,
                    coalesce({rr('UP')}, {g('UP')}, 'inf'::double) as upper
             from RDCUR d, t_obv o where in_REG(d.r)""")
    db.bounds.add("VAR_OBJ")


def uc_bounds(db: DB):
    """bnd_ucw.mod: the RHS of the user constraints as bounds on their slack variables."""
    # --- bnd_ucw.mod (VAR_UC = YES): slack variables of the user constraints carry the RHS as bounds
    #     UC_T_EACH(UC_T_SUCC) = YES;  ... bounds ...  UC_T_EACH(UC_T_SUCC) = NO;        (the dynamic constraints are bounded the same way)
    on = "in_UC_ON(a.r,a.uc)"
    each = lambda r: f"(in_UC_T_EACH({r},a.uc,a.y) or in_UC_T_SUCC({r},a.uc,a.y))"
    # --- VAR_UC.LO/UP/FX(UC_N)$UC_ON(R,UC_N) $= UC_RHS(UC_N,bd);                       (LOOP(R, ..))
    _bounds(db, "VAR_UC", ["a.uc"], "UC_RHS", ["uc"], "exists(select 1 from UC_ON o where o.uc=a.uc)")
    _bounds(db, "VAR_UCR", ["a.uc", "a.r"], "UC_RHSR", ["uc", "r"], on)
    # --- VAR_UCT.LO/UP/FX(UC_N,TT)$(UC_ON(R,UC_N)*UC_T_EACH(R,UC_N,TT)) $= UC_RHST(UC_N,TT,bd);                       (LOOP(R, ..))
    _bounds(db, "VAR_UCT", ["a.uc", "a.y"], "UC_RHST", ["uc", "y"],
            f"in_MILESTONYR(a.y) and exists(select 1 from UC_ON o where o.uc=a.uc and {each('o.r')})")
    _bounds(db, "VAR_UCRT", ["a.uc", "a.r", "a.y"], "UC_RHSRT", ["uc", "r", "y"], f"{on} and in_MILESTONYR(a.y) and {each('a.r')}")
    # --- VAR_UCTS.LO/UP/FX(UC_N,TT,S)$(UC_ON(R,UC_N)*UC_T_EACH(R,UC_N,TT)) $= UC_RHSTS(UC_N,TT,S,bd);                 (LOOP(R, ..))
    _bounds(db, "VAR_UCTS", ["a.uc", "a.y", "a.s"], "UC_RHSTS", ["uc", "y", "s"],
            f"in_MILESTONYR(a.y) and exists(select 1 from UC_ON o where o.uc=a.uc and {each('o.r')})")
    _bounds(db, "VAR_UCRTS", ["a.uc", "a.r", "a.y", "a.s"], "UC_RHSRTS", ["uc", "r", "y", "s"],
            f"{on} and in_MILESTONYR(a.y) and {each('a.r')}")
    # --- %5(..,'UP')$((NOT %5(..,'UP'))$%5(..,'N')) = INF;   (bnd_ucv.mod: a free constraint, bound type N, gets an infinite UP)
    #     (the period index is TT, an alias of MILESTONYR: an N bound on another year gets no UP)
    for n in ("UC_RHS", "UC_RHSR", "UC_RHST", "UC_RHSTS", "UC_RHSRT", "UC_RHSRTS"):
        kc = [c for c in db.cols(n) if c != "l"]
        same = " and ".join(f"b.{c}=a.{c}" for c in kc)
        tt = " and in_MILESTONYR(a.y)" if "y" in kc else ""
        db.put(n, f"""select {", ".join("a." + c for c in kc)}, 'UP' as l, 'inf'::double as value from "{n}" a
                      where a.l='N'{tt} and not exists(select 1 from "{n}" b where {same} and b.l='UP')""")
