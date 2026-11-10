# SPDX-License-Identifier: GPL-3.0-or-later
"""A run with FIXBOH (solve.stp with REG_FIXT): the periods up to a year fixed at the solution of an earlier run.

    $SET FIXBOH <year>     the periods whose milestone year is not after <year> (REG_FIXT(R) by region, when given)
    $SET LPOINT <run>      the earlier run: its results, loaded by spoint.mod (execute_loadpoint)

TIMES runs solve.stp once (STEPPED is NO, TIMESTEP 999): the window is every period after REG_FIXT(R) of each region
(RT_PP); the periods before it (NO_RT) have their activities, flows, trade, capacities ... fixed at the loaded levels;
user constraints, cumulative bounds and capacity bounds are relaxed by small tolerances around the loaded levels; trade
fixed in a region whose partner is in the window is bounded around its level instead.  This module makes the data of
that step, from the loaded levels; the equation module fixes the columns (times_eq/src/steps.jl: fix_window!).

The loaded results (spoint.mod 40-49):

    $IF SET FIXBOH $SETLOCAL PNT1 '' SETLOCAL PNT2 '_p'
    $IF EXIST %PATH%%LPOINT%%PNT1%.gdx $SET LOAD 2   ... execute_loadpoint '%PATH%%LPOINT%%PNT1%.gdx';
    $IF EXIST %PATH%%LPOINT%%PNT2%.gdx $SET LOAD 2   ... execute_loadpoint '%PATH%%LPOINT%%PNT2%.gdx';
    $IF SET FIXBOH $ABORT Could not load gdx file %LPOINT%

execute_loadpoint merges the levels and marginals of the variables and equations in the file; a column the file does
not have keeps its level (0 here: the periods fixed are outside the bounds that bndmain.mod gave levels to).
"""
import math
from ..engine import DB
from ..controls import given
from .common import require_empty
from . import costs, spoint
from .myopic import (TABLES, BOUNDS, INF, _snapshot, _restore, _take, _set, _bnd_ucw, _bnd_cum)

# solve.stp 153-154: relaxation tolerances (relative, absolute; %TOLX% for trade)
TOLR, TOLA = 3e-6, 1e-4
TOLR_HSX, TOLA_HSX = 1e-7, 1e-6
TOLX = 1e-5

# The columns solve.stp 200-220 fixes in the periods NO_RT, with the position of the period (0-based) in the key
FIXED = {"VAR_ACT": 2, "VAR_FLO": 2, "VAR_IRE": 2, "VAR_SIN": 2, "VAR_SOUT": 2, "VAR_UPS": 2, "VAR_UPT": 2, "VAR_UDP": 2,
         "VAR_COMNET": 1, "VAR_COMPRD": 1, "VAR_ELAST": 1, "VAR_NCAP": 1, "VAR_SCAP": 2, "VAR_BLND": 1}
# the levels the relaxations read (solve.stp 97-98, 160-190)
RELAXED = ("VAR_UC", "VAR_UCR", "VAR_UCT", "VAR_UCTS", "VAR_UCRT", "VAR_UCRTS", "VAR_CUMCOM", "VAR_CUMFLO")
# tables the step changes beyond those of a myopic step
MORE = ["UC_RHS", "FLO_CUM", "IRE_BND", "IRE_XBND", "RPC_CUMFLO", "FIXB_RT", "FIXB_NORT", "FIXB_RTPX", "FIXB_IRE", "FIXB_IREACT"]


def loaded_point(db: DB):
    """The levels of the run LPOINT names, in the order spoint.mod looks for them with FIXBOH: {SYMBOL: {key: level}}
    with the keys in upper case, and the file read."""
    pt, path = spoint.loaded_point(db, set(FIXED) | set(RELAXED) | {"VAR_CAP"}, fixboh=True)
    return {n: {k: v[0] for k, v in d.items()} for n, d in pt.items()}, path


def fixboh_step(db: DB, hook=None):
    """The step of a run with FIXBOH (db.steps: one step); nothing without FIXBOH."""
    s, q = db.s, db.q
    require_empty(db, ["REG_CUMCST", "BLE_OPR"], "cumulative cost bounds or blending in a run with FIXBOH (solve.stp)")
    lev, path = loaded_point(db)
    db.fixboh_point = path
    for n, dom in (("UC_RN", ["UC_N", "ALL_R"]), ("FIXB_RT", ["R", "T"]), ("FIXB_NORT", ["R", "T"]), ("FIXB_RTPX", ["R", "T", "P"]),
                   ("FIXB_IRE", ["R", "T", "P", "IE"]), ("FIXB_IREACT", ["R", "T", "P", "IE"])):
        if n not in db.sym:
            db.declare(n, "set", dom)
    db.declare("MIYR_VL", "par", [])
    tabs = set(t for (t,) in q("select table_name from information_schema.tables"))
    names = sorted(set(TABLES + MORE) | {"B_" + v for v in BOUNDS if f"B_{v}" in tabs}
                   | {"FLO_CUM", "UC_RHSRT", "UC_RHSRTS", "UC_RHSR", "UC_RHST", "UC_RHSTS", "CAP_BND", "RTP_VARP"})
    if db.card("PRC_DYNUC"):
        names.append("PRC_DYNUC")
    names = [n for n in names if n.startswith("B_") or n in db.sym]
    for v in BOUNDS:
        if f"B_{v}" not in names:
            ncol = {"VAR_NCAP": 3, "VAR_CAP": 3, "VAR_COMNET": 4, "VAR_COMPRD": 4, "VAR_UCR": 2, "VAR_UCT": 2, "VAR_UCRT": 3,
                    "VAR_UCTS": 3, "VAR_UCRTS": 4, "VAR_CUMFLO": 5, "VAR_CUMCOM": 5}[v]
            cols = ", ".join(f"d{i} VARCHAR" for i in range(ncol))
            db.x(f'create table "B_{v}" ({cols}, lower DOUBLE, upper DOUBLE)')
            names.append(f"B_{v}")
    scal = {k: s.get(k, 0.0) for k in ("MIYR_VL",)}
    _snapshot(db, names)
    try:
        step = _step(db, lev, hook)
        _take(db, step, more=[n for n in MORE if n in db.sym] + (["PRC_DYNUC"] if "PRC_DYNUC" in names else []))
        db.steps.append(step)
    finally:
        _restore(db, names)
        s.update(scal)


def _rows(db, name):
    return db.q(f'select * from "{name}"') if name in db.sym else []


def _step(db: DB, lev, hook):
    s, q, x = db.s, db.q, db.x
    U = str.upper
    T = [y for (y,) in q("select y from MILESTONYR order by yv(y)")]
    M = {t: v for t, v in q("select y, value from M")}
    E = {t: v for t, v in q("select y, value from E")}
    regs = [r for (r,) in q("select r from REG")]
    tsl = (TOLR_HSX, TOLA_HSX) if "TM_HSX" in db.sym and db.card("TM_HSX") else (TOLR, TOLA)
    tolr, tola = tsl
    # --- YR_V1 = 0; YR_VL = %TIMESTEP% (999); MY_FYEAR = 0; REG_FIXT(R)$NO = 0;
    # --- $IF SET FIXBOH YR_V1 = ABS(%FIXBOH%); REG_FIXT(R)$(NOT REG_FIXT(R)) = YR_V1;
    # --- $IF '%RTPX%'==X MY_FYEAR = 1;
    yr_vl = 999
    fixt = {r: v for r, v in _rows(db, "REG_FIXT")}
    yr_v1 = abs(float(given(db.env, "FIXBOH")))
    for r in regs:
        if not fixt.get(r):
            fixt[r] = yr_v1
    # --- F = SUM(MIYR_1(T),M(T));  REG_FIXT(R)$(REG_FIXT(R) < F) = 0;
    f = M[T[0]]
    for r in regs:
        if fixt[r] < f:
            fixt[r] = 0.0
    # --- YR_V1 = SMIN((R,T)$(M(T) > REG_FIXT(R)),M(T));  Z = YR_V1 + YR_VL;  SUBT(T)$(M(T) < YR_V1) = NO;  SUBT(T)$(M(T) GE Z) = NO;
    yr_v1 = min((M[t] for r in regs for t in T if M[t] > fixt[r]), default=INF)
    subt = [t for (t,) in q("select y from SUBT order by yv(y)") if yr_v1 <= M[t] < yr_v1 + yr_vl]
    # --- BACKWARD(T)$(M(T) < YR_V1) = YES;  FORWARD(T) = TT(T)-BACKWARD(T)-SUBT(T);
    # --- RT_PP(R,T) = (M(T) > REG_FIXT(R));  NO_RT(R,T) = NOT RT_PP(R,T);
    backward = [t for t in T if M[t] < yr_v1]
    forward = [t for t in T if t not in backward and t not in subt]
    no_rt = {(r, t) for r in regs for t in T if not M[t] > fixt[r]}
    # --- (the body of the loop of solve.stp, run once)  BACKWARD(T) = (M(T) < YR_V1);  FORWARD(SUBT) = NO;
    #     NO_RT(R,T(BACKWARD)) = 1;  RT_PP(R,T) = SUBT(T)$(NOT NO_RT(R,T));
    no_rt |= {(r, t) for r in regs for t in backward}
    rt_pp = [(r, t) for r in regs for t in T if t in subt and (r, t) not in no_rt]
    rtpp_u = {(U(r), U(t)) for r, t in rt_pp}
    nort_u = {(U(r), U(t)) for r, t in no_rt}
    _set(db, "SUBT", [(t,) for t in subt])
    _set(db, "BACKWARD", [(t,) for t in backward])
    _set(db, "FORWARD", [(t,) for t in forward])
    _set(db, "RT_PP", rt_pp)
    _set(db, "NO_RT", [(r, t, 1.0) for (r, t) in sorted(no_rt)])
    _set(db, "FIXB_RT", rt_pp)
    _set(db, "FIXB_NORT", sorted(no_rt))
    _set(db, "MODLYEAR", [(y,) for (y,) in q("select y from MODLYEAR") if y not in forward])      # V(FORWARD) = NO

    # ---- clearsol.stp: levels of the window cleared (those the relaxations below read)
    #      VAR_NCAP.L(RT_PP,P) = 0;  VAR_UCT.L(UC_N,T(FIL)) = 0;  VAR_UCTS.L(UC_N,T(FIL),S) = 0;  (FIL: periods of no fixed region)
    #      VAR_UCRT.L(UC_N,RT_PP) = 0;  VAR_UCRTS.L(UC_N,RT_PP,S) = 0;
    def L(name):
        return lev.get(name, {})
    fil = {U(t) for t in T if not any((r, t) in no_rt for r in regs)}
    ncap = {k: v for k, v in L("VAR_NCAP").items() if (k[0], k[1]) not in rtpp_u}
    uct = {k: v for k, v in L("VAR_UCT").items() if k[1] not in fil}
    ucts = {k: v for k, v in L("VAR_UCTS").items() if k[1] not in fil}
    ucrt = {k: v for k, v in L("VAR_UCRT").items() if (k[1], k[2]) not in rtpp_u}
    ucrts = {k: v for k, v in L("VAR_UCRTS").items() if (k[1], k[2]) not in rtpp_u}
    uc, ucr = dict(L("VAR_UC")), dict(L("VAR_UCR"))

    # --- OPTION RTC_NET<RHS_COMBAL, RTC_PRD<RHS_COMPRD;
    db.assign("RTC_NET", "select distinct r, y, c from RHS_COMBAL")
    db.assign("RTC_PRD", "select distinct r, y, c from RHS_COMPRD")
    # --- Copy FX UC RHS and CAP_BND to UP/LO:  UC_RHS(UC_N,BD)$UC_RHS(UC_N,'FX') = UC_RHS(UC_N,'FX')$BDNEQ(BD); (and the others)
    for n in ("UC_RHS", "UC_RHSR", "UC_RHSRT", "UC_RHSRTS", "UC_RHST", "UC_RHSTS", "CAP_BND"):
        c = [k for k in db.cols(n) if k != "l"]
        cs = ", ".join(c)
        # (over the model periods T only: an FX record of another year stays as it is)
        per = " and in_MILESTONYR(y)" if "y" in c else ""
        db.put(n, f"select {cs}, b.l, a.value from {n} a, (select 'LO' as l union all select 'UP') b where a.l = 'FX'{per.replace('(y)', '(a.y)')}", zero="eps")
        db.zap(n, "l = 'FX'" + per)
    # --- PRC_DYNUC(UC_N,SIDE,R,LL,P,UC_GRPTYPE,BD)$PRC_DYNUC(UC_N,'RHS',R,LL,P,UC_GRPTYPE,'FX') = PRC_DYNUC(UC_N,SIDE,R,LL,P,UC_GRPTYPE,'FX')$BDNEQ(BD);
    #     (every year LL, both sides: an FX bound becomes LO and UP where its RHS is given, and the FX records go)
    if db.card("PRC_DYNUC"):
        db.tmp("t_dynfx", "select distinct uc, r, y, p, grp from PRC_DYNUC where side = 'RHS' and l = 'FX'")
        db.put("PRC_DYNUC", """select a.uc, a.side, a.r, a.y, a.p, a.grp, b.l, a.value
                               from PRC_DYNUC a join t_dynfx f on f.uc=a.uc and f.r=a.r and f.y=a.y and f.p=a.p and f.grp=a.grp,
                                    (select 'LO' as l union all select 'UP') b
                               where a.l = 'FX'""", zero="eps")
        db.remove("PRC_DYNUC", where="""l = 'FX' and exists(select 1 from t_dynfx f where f.uc=PRC_DYNUC.uc and f.r=PRC_DYNUC.r
                                         and f.y=PRC_DYNUC.y and f.p=PRC_DYNUC.p and f.grp=PRC_DYNUC.grp)""")
    # --- UC_RN (UC with coefficients of both signs), R_UC (capacity-related UCs), RTP_VARP: as in a myopic step
    db.assign("UC_RN", """select distinct uc, r from (
          select uc, r from UC_CAP a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_NCAP a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_ACT a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_FLO a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_IRE a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_COM a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_MAP_IRE m where m.ie = 'IMP' and in_COM_UNIT(m.r, m.c, 'UCU'))""")
    db.add("UC_RN", "select distinct uc, 'IMPEXP' as r from UC_RN")
    db.assign("R_UC", "select distinct r, uc from UC_CAP")
    db.add("RTP_VARP", "select distinct r, y, p from CAP_BND where l in ('LO','UP') and in_RTP(r,y,p)")
    # --- RTP_CAPYR(RTP_CPTYR(R,V,T,P))$(VAR_NCAP.L(R,V,P)+NCAP_PASTI(R,V,P)) = YES;
    #     VAR_CAP.L(RTP_VARP(RT_PP(R,T),P)) = SUM(RTP_CAPYR(R,V,T,P),COEF_CPT(R,V,T,P)*(VAR_NCAP.L(R,V,P)$TT(V)+NCAP_PASTI(R,V,P)));
    capl = dict(L("VAR_CAP"))
    if db.card("CAP_BND"):
        Tu = {U(t) for t in T}
        pasti = {(U(r), U(v), U(p)): val for r, v, p, val in q("select * from NCAP_PASTI")}
        cptyr = {}          # (in the order of the table: the sums below keep it)
        for r, t, p, v, cpt in q("""select c.r, c.y2, c.p, c.y, v_COEF_CPT(c.r,c.y,c.y2,c.p) from RTP_CPTYR c
                                    where (c.r, c.y2, c.p) in (select r, y, p from RTP_VARP) order by c.rowid"""):
            cptyr.setdefault((r, t, p), []).append((v, cpt))
        for r, t, p in q("select r, y, p from RTP_VARP"):
            if (U(r), U(t)) not in rtpp_u:
                continue
            tot = 0.0
            for v, cpt in cptyr.get((r, t, p), ()):
                k = (U(r), U(v), U(p))
                nl = ncap.get(k, 0.0) if U(v) in Tu else 0.0
                if ncap.get(k, 0.0) + pasti.get(k, 0.0):
                    tot += cpt * (nl + pasti.get(k, 0.0))
            capl[(U(r), U(t), U(p))] = tot
    # --- Re-define End-of-Horizon: MIYR_VL = SMAX(SUBT(T),E(T)); Y_EOH; MIYR_L
    miyr = max(E[t] for t in subt)
    s["MIYR_VL"] = miyr
    db.assign("Y_EOH", f"select y from EOHYEARS where yv(y) <= {miyr} and yv(y) >= {s['MINYR']}")
    db.assign("MIYR_L", f"select y from ALLYEAR where y = '{int(miyr)}'")
    # --- $IF NOT '%CTST%'=='' $BATINCLUDE coef_alt.lin STP  (OPTION CLEAR=PERDINV,CLEAR=TPULSE,CLEAR=TPULSEYR; ...)
    if db.ctl["CTST"]:
        db.clear("PERDINV", "TPULSEYR", "TPULSE")
        costs.pulse(db)
    # --- OBJ_LIFE is recomputed for the same horizon (MIYR_VL is the end of the last period), and eqobsalv.mod STP runs
    #     only with STEPPED YES: the objective is that of the run.
    # --- RVPRL(R,K,P)$RVPRL(R,K,P)=MAX(1,SMAX(RTP_CPTYR(R,VNT(K,V(T)),P),YEARVAL(V))-YEARVAL(K));
    db.put("RVPRL", """select a.r, a.y, a.p, greatest(1, coalesce((select max(yv(c.y2)) from RTP_CPTYR c
                             where c.r=a.r and c.y=a.y and c.p=a.p and in_VNT(a.y,c.y2) and in_MILESTONYR(c.y2) and in_MODLYEAR(c.y2)),
                             '-inf'::double) - yv(a.y)) as value from RVPRL a""")
    # ---- user constraints (solve.stp 131-151), as in a myopic step
    x("create or replace temp table t_rxx as select distinct e.r, e.uc from UC_R_EACH e join UC_T_SUM u on u.r=e.r and u.uc=e.uc where in_RT_PP(u.r,u.y)")
    x("create or replace temp table t_uncd1 as select distinct u.uc from UC_R_SUM s join UC_T_SUM u on u.r=s.r and u.uc=s.uc where in_RT_PP(u.r,u.y)")
    db.zap("UC_T_SUM", "in_FORWARD(y)")
    db.zap("UC_T_SUM", """uc not in (select uc from t_uncd1) and not exists(select 1 from t_rxx x where x.r="UC_T_SUM".r and x.uc="UC_T_SUM".uc)""")
    # --- IF(PRESOL, VAR_UC.L(UC_N(UNCD1)) = 0; VAR_UCR.L(UC_N,R)$RXX(R,UC_N,R) = 0);
    for (u,) in q("select uc from t_uncd1"):
        uc.pop((U(u),), None)
    for r, u in q("select r, uc from t_rxx"):
        ucr.pop((U(u), U(r)), None)
    db.assign("UC_T", """select distinct e.uc, e.y from UC_T_EACH e where in_UC_R_SUM(e.r,e.uc) and in_RT_PP(e.r,e.y)
                         union select distinct e.uc, e.y from UC_T_SUCC e where in_UC_R_SUM(e.r,e.uc) and in_RT_PP(e.r,e.y)""")
    db.zap("UC_T_EACH", "in_UC_R_SUM(r,uc) and not in_UC_T(uc,y)")
    db.zap("UC_T_SUCC", "in_UC_R_SUM(r,uc) and in_UC_DYNDIR(r,uc,'RHS') and not in_UC_T(uc,y)")
    db.zap("UC_T_EACH", "in_UC_R_EACH(r,uc) and not in_RT_PP(r,y)")
    db.zap("UC_T_SUCC", "in_UC_R_EACH(r,uc) and in_UC_DYNDIR(r,uc,'RHS') and not in_RT_PP(r,y)")
    # --- UC_T_SUCC(UC_T_SUCC(R,UC_N,T-1)) = UC_DYNDIR(R,UC_N,'RHS')+RT_PP(R,T);
    x("create or replace temp table t_ord as select y, row_number() over (order by yv(y)) as o from MILESTONYR")
    x("""create or replace temp table t_succ as select u.r, u.uc, u.y,
             (in_UC_DYNDIR(u.r,u.uc,'RHS') or in_RT_PP(u.r,n.y)) as yes_
         from UC_T_SUCC u join t_ord o on o.y=u.y join t_ord n on n.o=o.o+1""")
    db.remove("UC_T_SUCC", select="select r, uc, y from t_succ where not yes_")
    db.add("UC_T_SUCC", "select r, uc, y from t_succ where yes_")
    # --- UC_T(UC_N,T)$(NOT SUM(R$NO_RT(R,T),1)) = NO;
    db.zap("UC_T", "not exists(select 1 from NO_RT n where n.y=\"UC_T\".y)")
    # --- LOOP(BD,UC_T_SUCC(R,UC_N,T)$UC_DYNBND(UC_N,BD) = RT_PP(R,T));
    #     (the dynamic bounds by process: their periods are those of the window of each region)
    if db.card("UC_DYNBND"):
        db.tmp("t_dynuc", "select distinct uc from UC_DYNBND where l in ('LO','UP','FX')")
        db.remove("UC_T_SUCC", where="in_MILESTONYR(y) and in_REG(r) and exists(select 1 from t_dynuc d where d.uc=UC_T_SUCC.uc)")
        db.add("UC_T_SUCC", "select a.r, d.uc, a.y from RT_PP a, t_dynuc d")
    # --- RHS and bounds relaxation: IF(CARD(BACKWARD) OR MY_FYEAR, ...)   (MY_FYEAR is 1)
    #     R_UCT(R_UC(R,UC_N),T)$(UC_T_EACH(R,UC_N,T)+UC_T_SUCC(R,UC_N,T)) = YES;
    #     LOOP(UC_R_SUM(R_UC(R,UC_N)),UC_T(UC_N,T)$R_UCT(R,UC_N,T) = YES);
    #     R_UCT(R,UC_N,T)$(NOT REG_FIXT(R)) = NO;
    db.assign("R_UCT", """select distinct u.r, u.uc, u.y from (select r, uc, y from UC_T_EACH union select r, uc, y from UC_T_SUCC) u
                          where in_R_UC(u.r,u.uc)""")
    db.add("UC_T", "select distinct uc, y from R_UCT u where in_UC_R_SUM(u.r,u.uc)")
    fixed_regs = [r for r in regs if fixt[r]]
    db.zap("R_UCT", ("r not in (" + ", ".join(f"'{r}'" for r in fixed_regs) + ")") if fixed_regs else "true")
    rn = {(U(a), U(b)) for a, b in q("select uc, r from UC_RN")}

    def relax(rhs, key, level, ucn, reg):
        """UC_BND(..,'UP') = MAX(RHS,L-INF$(NOT L)), (..'LO') = MIN(RHS,L+INF$(NOT L)); then the tolerances
        UC_BND(..)$UC_BND = UC_BND +- ABS(UC_BND)*%TOLR% +- %TOLA%$UC_RN(UC_N,ALL_R): {bd: value} of what is copied back."""
        out = {}
        for bd in ("UP", "LO"):
            if (key, bd) not in rhs:
                continue
            v = rhs[(key, bd)]
            b = max(v, level if level else -INF) if bd == "UP" else min(v, level if level else INF)
            # --- solve.stp 173: UC_BND(J,ALL_R,UC_N,LL,S,'UP')$UC_BND(J,ALL_R,UC_N,LL,S,'UP') =
            # ---   UC_BND(J,ALL_R,UC_N,LL,S,'UP')+ABS(UC_BND(J,ALL_R,UC_N,LL,S,'UP'))*%TOLR%+%TOLA%$UC_RN(UC_N,ALL_R);
            # (a RHS given as 0 is EPS: MAX(EPS,-INF) is an EPS record of UC_BND, and $UC_BND holds for it, so it gets
            #  the tolerances too; a record of RHS exists here only for a value or EPS)
            if not math.isfinite(b):
                continue
            tol = abs(b) * tolr + (tola if (U(ucn), U(reg)) in rn else 0.0)
            out[bd] = b + tol if bd == "UP" else b - tol
        return out

    def relax_table(name, levelof, regof, ucof, keep):
        """name(key, l) relaxed where keep(key) (the $= of the copy back)."""
        rows = q(f'select * from "{name}"')
        rhs = {(r[:-2], r[-2]): r[-1] for r in rows}
        new = []
        for key in sorted({k for k, _ in rhs}):
            if not keep(key):
                continue
            for bd, v in relax(rhs, key, levelof(key), ucof(key), regof(key)).items():
                new.append(key + (bd, v))
        _put_rows(db, name, new)
    ucT = {(U(a), U(b)) for a, b in q("select uc, y from UC_T")}
    ruct = {(U(a), U(b), U(c)) for a, b, c in q("select r, uc, y from R_UCT")}
    fixed_u = {U(r) for r in fixed_regs}
    # UC_RHS(UC_N,BDNEQ(BD))                   $= UC_BND('1','IMPEXP',UC_N,'0','ANNUAL',BD);
    relax_table("UC_RHS", lambda k: uc.get((U(k[0]),), 0.0), lambda k: "IMPEXP", lambda k: k[0], lambda k: True)
    # UC_RHSR(R,UC_N,BDNEQ(BD))$REG_FIXT(R)    $= UC_BND('2',R,UC_N,'0','ANNUAL',BD);
    relax_table("UC_RHSR", lambda k: ucr.get((U(k[1]), U(k[0])), 0.0), lambda k: k[0], lambda k: k[1], lambda k: U(k[0]) in fixed_u)
    # UC_RHST(UC_T(UC_N,T),BDNEQ(BD))          $= UC_BND('3','IMPEXP',UC_N,T,'ANNUAL',BD);
    relax_table("UC_RHST", lambda k: uct.get((U(k[0]), U(k[1])), 0.0), lambda k: "IMPEXP", lambda k: k[0], lambda k: (U(k[0]), U(k[1])) in ucT)
    # UC_RHSTS(UC_T(UC_N,T),S,BDNEQ(BD))       $= UC_BND('4','IMPEXP',UC_N,T,S,BD);
    relax_table("UC_RHSTS", lambda k: ucts.get((U(k[0]), U(k[1]), U(k[2])), 0.0), lambda k: "IMPEXP", lambda k: k[0],
                lambda k: (U(k[0]), U(k[1])) in ucT)
    # UC_RHSRT(R_UCT(R,UC_N,T),BDNEQ(BD))      $= UC_BND('5',R,UC_N,T,'ANNUAL',BD);
    relax_table("UC_RHSRT", lambda k: ucrt.get((U(k[1]), U(k[0]), U(k[2])), 0.0), lambda k: k[0], lambda k: k[1],
                lambda k: (U(k[0]), U(k[1]), U(k[2])) in ruct)
    # UC_RHSRTS(R_UCT(R,UC_N,T),S,BDNEQ(BD))   $= UC_BND('6',R,UC_N,T,S,BD);
    relax_table("UC_RHSRTS", lambda k: ucrts.get((U(k[1]), U(k[0]), U(k[2]), U(k[3])), 0.0), lambda k: k[0], lambda k: k[1],
                lambda k: (U(k[0]), U(k[1]), U(k[2])) in ruct)
    # --- Handle other important dynamic constraints
    #     LOOP((R,T,SAMEAS(T+1,TT))$NO_RT(R,T),
    #      PRC_DYNUC(UC_N,'LHS',RTP(R,TT,P),UC_GRPTYPE,'UP')$PRC_DYNUC(UC_N,'RHS',R,'0',P,UC_GRPTYPE,'UP') = PRC_DYNUC(UC_N,'LHS',R,TT,P,UC_GRPTYPE,'UP')*(1+%TOLR%);
    #      PRC_DYNUC(UC_N,'LHS',RTP(R,TT,P),UC_GRPTYPE,'LO')$PRC_DYNUC(UC_N,'RHS',R,'0',P,UC_GRPTYPE,'LO') = PRC_DYNUC(UC_N,'LHS',R,TT,P,UC_GRPTYPE,'LO')*(1-%TOLX%));
    #     (the growth factor of the period after each fixed period; %TOLX% is 1E-5 in every run)
    if db.card("PRC_DYNUC"):
        nxt = dict(zip(T[:-1], T[1:]))
        db.tmp("t_dynrt", _values_rt(sorted({(r, nxt[t]) for r, t in no_rt if t in nxt})))
        db.put("PRC_DYNUC", f"""select a.uc, a.side, a.r, a.y, a.p, a.grp, a.l,
                                       a.value * case a.l when 'UP' then {1 + tolr:.17e} else {1 - TOLX:.17e} end as value
                                from PRC_DYNUC a join t_dynrt n on n.r=a.r and n.y=a.y
                                where a.side='LHS' and a.l in ('UP','LO') and in_RTP(a.r,a.y,a.p)
                                  and exists(select 1 from PRC_DYNUC b where b.uc=a.uc and b.side='RHS' and b.r=a.r and b.y='0'
                                             and b.p=a.p and b.grp=a.grp and b.l=a.l)""", zero="eps")
    # --- COM_CUM(R,COM_VAR,YEAR,LL,C,'UP')$(REG_FIXT(R)$COM_CUM(..,'UP')) = MAX(COM_CUM(..,'UP'),MIN(COM_CUM(..,'UP'),VAR_CUMCOM.L(R,C,COM_VAR,YEAR,LL)*%CUCSCAL%)*(1+%TOLR%));
    #     COM_CUM(R,COM_VAR,YEAR,LL,C,'LO')$REG_FIXT(R) $= COM_CUM(R,COM_VAR,YEAR,LL,C,'LO')*(1-%TOLR%);
    #     FLO_CUM(R,P,C,YEAR,LL,'UP')$(REG_FIXT(R)$FLO_CUM(..,'UP')) = MAX(FLO_CUM(..,'UP'),MIN(FLO_CUM(..,'UP'),VAR_CUMFLO.L(R,P,C,YEAR,LL)*%CUFSCAL%)*(1+%TOLR%));
    #     FLO_CUM(R,P,C,YEAR,LL,'LO')$REG_FIXT(R)       $= FLO_CUM(R,P,C,YEAR,LL,'LO')*(1-%TOLR%);
    cuc, cuf = float(db.env.get("CUCSCAL", 1000)), float(db.env.get("CUFSCAL", 10))
    cumcom, cumflo = L("VAR_CUMCOM"), L("VAR_CUMFLO")
    for name, lv, sc, lkey in (("COM_CUM", cumcom, cuc, lambda r: (r[0], r[4], r[1], r[2], r[3])),
                               ("FLO_CUM", cumflo, cuf, lambda r: (r[0], r[1], r[2], r[3], r[4]))):
        new = []
        for r in q(f'select * from "{name}" where l in (\'UP\', \'LO\')'):
            if U(r[0]) not in fixed_u:
                continue
            if r[-2] == "UP":
                v = max(r[-1], min(r[-1], lv.get(tuple(U(z) for z in lkey(r)), 0.0) * sc) * (1 + tolr))
            else:
                v = r[-1] * (1 - tolr)
            new.append(r[:-1] + (v,))
        _put_rows(db, name, new)
    # --- CAP_BND(R,T,P,'UP')$CAP_BND(R,T,P,'UP') = MAX(CAP_BND(R,T,P,'UP'),VAR_CAP.L(R,T,P)*(1+%TOLR%));
    #     CAP_BND(R,T,P,'LO')                       $= CAP_BND(R,T,P,'LO')*(1-%TOLR%);
    new = []
    for r in q('select * from "CAP_BND" where l in (\'UP\', \'LO\')'):
        if r[-2] == "UP":          # ($CAP_BND(..,'UP'): an EPS bound too)
            new.append(r[:-1] + (max(r[-1], capl.get((U(r[0]), U(r[1]), U(r[2])), 0.0) * (1 + tolr)),))
        else:
            new.append(r[:-1] + (r[-1] * (1 - tolr),))
    _put_rows(db, "CAP_BND", new)
    # --- $BATINCLUDE bnd_ucw.mod;  OPTION UC_RTSUC < UC_T_SUCC;
    _bnd_ucw(db)
    db.assign("UC_RTSUC", "select distinct r, y, uc from UC_T_SUCC")
    # ---- capacities (by region): NO_RVP(RTP_VARP(R,SUBT(T),P))$SUM(RTP_CPTYR(R,BACKWARD(TT),T,P),1) = YES;
    db.assign("NO_RVP", """select distinct v.r, v.y, v.p from RTP_VARP v join RTP_CPTYR c on c.r=v.r and c.y2=v.y and c.p=v.p
                           where in_RT_PP(v.r,v.y) and in_NO_RT(c.r,c.y)""")
    db.zap("B_VAR_CAP", "in_NO_RT(d0,d1) or in_FORWARD(d1)")
    # ---- cumulative variables: Z = SMAX(T,M(T)); LOOP(REG(R)$(REG_FIXT(R)>=Z), RPC_CUMFLO(R,P,C,YEAR,LL) = NO; RC_CUMCOM(R,COM_VAR,YEAR,LL,C) = NO);
    z = max(M.values())
    gone = [r for r in regs if fixt[r] >= z]
    if gone:
        lst = ", ".join(f"'{r}'" for r in gone)
        db.zap("RPC_CUMFLO", f"r in ({lst})")
        db.zap("RC_CUMCOM", f"r in ({lst})")
    #      Z = (Z > MIYR_VL);  FIL(LL) = Z*(MIYR_VL < YEARVAL(LL));  $BATINCLUDE bnd_cum.mod COM_VAR;
    #      VAR_CUMFLO.LO(R,P,C,YEAR,FIL)$(NOT FLO_CUM(R,P,C,YEAR,FIL,'N')) = 0;  VAR_CUMCOM.LO(...) likewise
    z = z > miyr
    db.assign("FIL", f"select y from ALLYEAR where y <> '0' and {'true' if z else 'false'} and yv(y) > {miyr}")
    _bnd_cum(db)
    x("""update "B_VAR_CUMFLO" set lower = 0 where in_FIL(d4) and not in_FLO_CUM(d0,d1,d2,d3,d4,'N')""")
    x("""update "B_VAR_CUMCOM" set lower = 0 where in_FIL(d4) and not in_COM_CUM(d0,d2,d3,d4,d1,'N')""")
    # ---- trade (IF(MY_FYEAR, ...), solve.stp 236-264)
    _trade(db, nort_u)
    step = dict(step=1, year=int(min((M[t] for t in subt), default=0)), subt=list(subt), backward=list(backward), forward=list(forward))
    # ---- the levels the equation module fixes the periods NO_RT at (solve.stp 200-220)
    step["levels"] = {}
    for name, tpos in FIXED.items():
        rows = [k + (v,) for k, v in L(name).items() if (k[0], k[tpos]) in nort_u]
        if rows:
            step["levels"][name] = sorted(rows)
    if hook:
        hook(db, step)
    return step


def _values_rt(rows):
    """SQL giving (r, y) for the pairs rows."""
    if not rows:
        return "select '' as r, '' as y where false"
    return " union all ".join(f"select '{r}' as r, '{y}' as y" for r, y in rows)


def _put_rows(db, name, rows):
    """name(key) = value for the rows (EPS kept)."""
    if not rows:
        return
    db.x(f'create or replace temp table t_put as select * from "{name}" limit 0')
    db.insert_rows("t_put", rows)
    db.put(name, f"select {', '.join(db.cols(name))}, value from t_put", zero="eps")


def _trade(db, nort_u):
    """solve.stp 236-264 (MY_FYEAR): the trade processes whose EQ_IRE rows are written (RTPX), and the fixed trade of a
    region whose partner is in the window, relaxed (RTP_IRE: by the equation module); IRE_BND, IRE_XBND of fixed regions."""
    x = db.x
    # --- TRACKPC(RPC)$(RPC_EQIRE(RPC,'EXP')+RPC_MARKET(RPC,'EXP')) = YES;
    #     LOOP((TRACKPC(R,P,C),TOP_IRE(R,C,REG,COM,P)),IRE_RPR(R,P,REG,'EXP') = YES);
    #     LOOP((TOP_IRE(R,C,REG,COM,P),RPC_EQIRE(REG,P,COM,'IMP')),IRE_RPR(REG,P,R,'IMP') = YES);
    x("""create or replace temp table t_irerpr as
         select distinct t.r1 as r, t.p as p, t.r2 as reg, 'EXP' as ie from (select * from TOP_IRE) t(r1, c1, r2, c2, p)
           where in_RPC_EQIRE(t.r1,t.p,t.c1,'EXP') or in_RPC_MARKET(t.r1,t.p,t.c1,'EXP')
         union
         select distinct t.r2, t.p, t.r1, 'IMP' from (select * from TOP_IRE) t(r1, c1, r2, c2, p)
           where in_RPC_EQIRE(t.r2,t.p,t.c2,'IMP')""")
    # --- OPTION CLEAR=RTPX; RTPX(RTP(R,T,P))$RP_IRE(R,P) = RT_PP(R,T);
    #     LOOP((REG,IE),RTPX(RTP(R,T,P))$(RT_PP(REG,T)$IRE_RPR(R,P,REG,IE)) = YES);
    db.assign("FIXB_RTPX", """select distinct a.r, a.y, a.p from RTP a where in_RP_IRE(a.r,a.p) and (in_RT_PP(a.r,a.y)
                                or exists(select 1 from t_irerpr i where i.r=a.r and i.p=a.p and in_RT_PP(i.reg,a.y)))""")
    # --- OPTION CLEAR=RTP_IRE; LOOP(REG,RTP_IRE(RTPX(R,T,P),IE)$(IRE_RPR(R,P,REG,IE)$NO_RT(R,T)) = YES);
    db.assign("FIXB_IRE", """select distinct a.r, a.y, a.p, i.ie from FIXB_RTPX a join t_irerpr i on i.r=a.r and i.p=a.p
                               where in_NO_RT(a.r,a.y)""")
    if db.ctl.get("REDUCE") == "YES":
        db.assign("FIXB_IREACT", "select * from FIXB_IRE")
    else:
        db.clear("FIXB_IREACT")
    # --- Remove IRE_BND from fixed regions with no related IRE equation, and all IRE_XBND from fixed regions
    #     LOOP((R,T,C,S,ALL_REG,IE,BD)$(NO_RT(R,T)$IRE_BND(R,T,C,S,ALL_REG,IE,BD)),
    #       IF(NOT SUM(RPC_EQIRE(R,P,C,IE)$RTPX(R,T,P),1), IF(NOT SUM(RPC_MARKET(R,P,C,IE)$RTPX(R,T,P),1),RXX(R,C,IE) = YES)));
    #     IRE_BND(R,T,C,S,ALL_REG,IE,BD)$(NO_RT(R,T)$RXX(R,C,IE)) = 0;  IRE_XBND(R,T,C,S,IE,BD)$NO_RT(R,T) = 0;
    b = db.cols("IRE_BND")
    x(f"""create or replace temp table t_rxx as select distinct a.{b[0]} as r, a.{b[2]} as c, a.{b[5]} as ie from IRE_BND a
          where in_NO_RT(a.{b[0]},a.{b[1]})
            and not exists(select 1 from RPC_EQIRE e join FIXB_RTPX x on x.r=e.r and x.p=e.p
                           where e.r=a.{b[0]} and e.c=a.{b[2]} and e.ie=a.{b[5]} and x.y=a.{b[1]})
            and not exists(select 1 from RPC_MARKET e join FIXB_RTPX x on x.r=e.r and x.p=e.p
                           where e.r=a.{b[0]} and e.c=a.{b[2]} and e.ie=a.{b[5]} and x.y=a.{b[1]})""")
    db.zap("IRE_BND", f"""in_NO_RT({b[0]},{b[1]}) and exists(select 1 from t_rxx t where t.r={b[0]} and t.c={b[2]} and t.ie={b[5]})""")
    xb = db.cols("IRE_XBND")
    db.zap("IRE_XBND", f"in_NO_RT({xb[0]},{xb[1]})")
