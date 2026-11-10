# SPDX-License-Identifier: GPL-3.0-or-later
"""Myopic runs (run-file switch TIMESTEP): the windows of solve.stp and the data of each step.

TIMES solves a myopic run as a sequence of models, one per window of periods SUBT: the periods before the window
(BACKWARD) are fixed at the solution of the previous step, those after it (FORWARD) are fixed at zero, and the end of
the horizon moves to the end of the window, which changes the discounting of salvage values, fixed costs and
variable costs.  solve.stp changes the data between the steps in place.  This module runs the same sequence on the
database, takes the tables of each step as they are when that step is solved, and puts the database back as it was:
db.steps holds, for each step, the tables that differ from the main pass and the bound tables of the step.

What depends on the solution of the previous step is not here: the fixing of the BACKWARD periods at the levels
of the previous step is done by the equation module, which solves the steps one after the other.  The relaxations of
solve.stp that use levels (bounds on capacity, RHS of global user constraints) are guarded.
"""
import math
from ..engine import DB
from .common import require_empty
from . import bounds, costs, objective


# Tables of a step that the equations or the checks read, with their kind (set / par)
TABLES = ["SUBT", "BACKWARD", "FORWARD", "RT_PP", "NO_RT", "MODLYEAR", "Y_EOH", "MIYR_L",
          "PERDINV", "TPULSEYR", "TPULSE", "OBJ_LINT", "RVPRL",
          "UC_T_SUM", "UC_T_EACH", "UC_T_SUCC", "UC_RTSUC", "UC_T", "R_UCT", "UC_RN", "R_UC",
          "UC_RHSR", "UC_RHSRT", "UC_RHSRTS", "UC_RHST", "UC_RHSTS", "CAP_BND", "RTC_NET", "RTC_PRD", "RTP_VARP", "NO_RVP", "FIL", "RC_CUMCOM", "COM_CUM"]


OBJ_TABLES = ["COEF_OBFIXR", "OBJ_CFIX", "SALV_INV", "OBJ_SUMS", "OBJSCC", "OBJ_DCEOH", "OBJ_IAD", "OBJ_SUMS3",
              "COR_SALVD", "OBJ_CRFD", "SALV_DEC", "OBJ_LIFE"]


BOUNDS = ["VAR_NCAP", "VAR_CAP", "VAR_COMNET", "VAR_COMPRD", "VAR_UCR", "VAR_UCT", "VAR_UCRT", "VAR_UCTS", "VAR_UCRTS", "VAR_CUMFLO", "VAR_CUMCOM"]


INF = float("inf")


def _snapshot(db: DB, names):
    for n in names:
        db.x(f'create or replace table "__bak_{n}" as select * from "{n}"')


def _restore(db: DB, names):
    for n in names:
        db.x(f'delete from "{n}"')
        db.x(f'insert into "{n}" select * from "__bak_{n}"')
        db.x(f'drop table "__bak_{n}"')


def _years(db, sql):
    return [y for (y,) in db.q(sql)]


def myopic_steps(db: DB, hook=None):
    """Prepare the steps of a myopic run (nothing without TIMESTEP).  hook(db, step) is called with the database
    in the state of each step, before its solve."""
    ts = db.ctl.get("TIMESTEP")
    db.steps = []
    # spoint.mod 1 (maindrv.mod 104, after bndmain.mod): a loaded solution point and REG_BDNCAP (prep/spoint.py)
    from . import spoint
    spoint.reg_bdncap(db)
    if db.ctl.get("FIXBOH") is not None and not ts:
        # a run with FIXBOH: one step, its periods up to REG_FIXT fixed at a loaded solution (prep/fixboh.py)
        from .fixboh import fixboh_step
        return fixboh_step(db, hook)
    if not ts:
        return
    s, q = db.s, db.q
    # what solve.stp would relax with the levels of the previous step, and what the steps here do not handle
    # (CAP_BND and the RHS of global user constraints by period are relaxed with the levels of the previous step:
    #  that is done by the equation module, which has the levels; here they are only prepared)
    require_empty(db, ["UC_RHS"], "cumulative global user constraints in a myopic run (solve.stp relaxes their RHS with the levels of the previous step)")
    require_empty(db, ["PRC_DYNUC", "REG_CUMCST", "BLE_OPR", "UC_DYNBND"],
                  "dynamic process bounds, cumulative cost bounds, blending or dynamic UC bounds in a myopic run (solve.stp)")
    for n in ("UC_RN", ):
        if n not in db.sym:
            db.declare(n, "set", ["UC_N", "ALL_R"])
    db.declare("MIYR_VL", "par", [])
    names = sorted(set(TABLES + OBJ_TABLES) | {"B_" + v for v in BOUNDS if f"B_{v}" in {t for (t,) in q("select table_name from information_schema.tables")}}
                   | {"FLO_CUM", "UC_RHSRT", "UC_RHSRTS", "UC_RHSR", "UC_RHST", "UC_RHSTS", "CAP_BND", "RTP_VARP"})
    names = [n for n in names if n.startswith("B_") or n in db.sym]
    for v in BOUNDS:                                # every bound table of a step exists, empty when the variable has no bounds
        if f"B_{v}" not in names:
            ncol = {"VAR_NCAP": 3, "VAR_CAP": 3, "VAR_COMNET": 4, "VAR_COMPRD": 4, "VAR_UCR": 2, "VAR_UCT": 2, "VAR_UCRT": 3,
                    "VAR_UCTS": 3, "VAR_UCRTS": 4, "VAR_CUMFLO": 5, "VAR_CUMCOM": 5}[v]
            cols = ", ".join(f"d{i} VARCHAR" for i in range(ncol))
            db.x(f'create table "B_{v}" ({cols}, lower DOUBLE, upper DOUBLE)')
            names.append(f"B_{v}")
    scal = {k: s.get(k, 0.0) for k in ("MIYR_VL",)}
    _snapshot(db, names)
    try:
        _steps(db, ts, hook)
    finally:
        _restore(db, names)
        s.update(scal)


def _take(db, step, more=()):
    """The tables of the step as they are now (more: other tables the step changed)."""
    out = {}
    for n in TABLES + OBJ_TABLES + list(more):
        if n in db.sym:
            out[n] = db.q(f'select * from "{n}"')
    bnds = {v: db.q(f'select * from "B_{v}"') for v in BOUNDS}
    step.update(tables=out, bounds=bnds, scalars={"MIYR_VL": db.s["MIYR_VL"]})


def _steps(db: DB, ts, hook):
    s, q, x = db.s, db.q, db.x
    T = _years(db, "select y from MILESTONYR order by yv(y)")
    M = {t: v for t, v in q("select y, value from M")}
    B = {t: v for t, v in q("select y, value from B")}
    E = {t: v for t, v in q("select y, value from E")}
    regs = _years(db, "select r from REG")
    # --- YR_V1 = 0; YR_VL = %TIMESTEP%; MY_FYEAR = 0; REG_FIXT(R)$NO = 0;
    #     IF(G_OVERLAP, G_OVERLAP = MAX(EPS,G_OVERLAP); ELSE G_OVERLAP = FLOOR(YR_VL/2));
    yr_vl = ts
    s["G_OVERLAP"] = max(0.0, s.get("G_OVERLAP", 0.0)) if s.get("G_OVERLAP", 0.0) else math.floor(yr_vl / 2)
    overlap = s["G_OVERLAP"]
    # --- YR_V1 = SMIN((R,T)$(M(T) > REG_FIXT(R)),M(T));  Z = YR_V1 + YR_VL;  SUBT(T)$(M(T) < YR_V1) = NO;  SUBT(T)$(M(T) GE Z) = NO;
    yr_v1 = min(M[t] for t in T)
    subt = [t for t in _years(db, "select y from SUBT") if yr_v1 <= M[t] < yr_v1 + yr_vl]
    # --- BACKWARD(T)$(M(T) < YR_V1) = YES;  FORWARD(T) = TT(T)-BACKWARD(T)-SUBT(T);
    backward = [t for t in T if M[t] < yr_v1]
    forward = [t for t in T if t not in backward and t not in subt]
    # --- RT_PP(R,T) = (M(T) > REG_FIXT(R));  NO_RT(R,T) = NOT RT_PP(R,T);
    no_rt = set()
    # --- OPTION RTC_NET<RHS_COMBAL, RTC_PRD<RHS_COMPRD;
    db.assign("RTC_NET", "select distinct r, y, c from RHS_COMBAL")
    db.assign("RTC_PRD", "select distinct r, y, c from RHS_COMPRD")
    # --- UC_RHSR(R,UC_N,BD)$UC_RHSR(R,UC_N,'FX') = UC_RHSR(R,UC_N,'FX')$BDNEQ(BD);   (likewise UC_RHSRT, UC_RHSRTS)
    #     (fixed RHS become lower and upper bounds, so that they can be relaxed)
    # --- CAP_BND(R,T,P,BD)$CAP_BND(R,T,P,'FX') = CAP_BND(R,T,P,'FX')$BDNEQ(BD);  UC_RHST, UC_RHSTS likewise
    for n in ("UC_RHSR", "UC_RHSRT", "UC_RHSRTS", "UC_RHST", "UC_RHSTS", "CAP_BND"):
        c = [k for k in db.cols(n) if k != "l"]
        cs = ", ".join(c)
        # (over the model periods T only: an FX record of another year stays as it is)
        per = " and in_MILESTONYR(y)" if "y" in c else ""
        db.put(n, f"select {cs}, b.l, a.value from {n} a, (select 'LO' as l union all select 'UP') b where a.l = 'FX'{per.replace('(y)', '(a.y)')}", zero="eps")
        db.zap(n, "l = 'FX'" + per)
    # --- Find UC equations with negative coefficients:  UC_RN(UC_N,R) if any UC_xxx(UC_N,SIDE,R,..)*UC_SIGN(SIDE) < 0;
    #     LOOP(UC_MAP_IRE(UC_N,R,P,C,'IMP')$COM_UNIT(R,C,'UCU'),UC_RN(UC_N,R)=YES);  UC_RN(UC_N,'IMPEXP') $= SUM(UC_RN(UC_N,R),1);
    db.assign("UC_RN", """select distinct uc, r from (
          select uc, r from UC_CAP a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_NCAP a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_ACT a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_FLO a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_IRE a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_COM a where a.value * v_UC_SIGN(a.side) < 0 union all
          select uc, r from UC_MAP_IRE m where m.ie = 'IMP' and in_COM_UNIT(m.r, m.c, 'UCU'))""")
    db.add("UC_RN", "select distinct uc, 'IMPEXP' as r from UC_RN")
    # --- LOOP((UC_N,SIDE,R,T,P)$UC_CAP(UC_N,SIDE,R,T,P),R_UC(R,UC_N) = YES);       (capacity-related UCs)
    db.assign("R_UC", "select distinct r, uc from UC_CAP")
    # --- RTP_VARP(RTP(R,T,P))$(CAP_BND(RTP,'UP')+CAP_BND(RTP,'LO')) = YES;        (a capacity variable for every capacity bound)
    db.add("RTP_VARP", "select distinct r, y, p from CAP_BND where l in ('LO','UP') and in_RTP(r,y,p)")
    # --- STP_UCT('1',UC_T_SUM) = YES; STP_UCT('2',UC_T_SUCC) = YES; STP_UCT('3',UC_T_EACH) = YES;
    stp_uct = {n: q(f"select * from {n}") for n in ("UC_T_SUM", "UC_T_SUCC", "UC_T_EACH")}
    modl = _years(db, "select y from MODLYEAR")
    k = 0
    while subt:
        k += 1
        # --- BACKWARD(T) = (M(T) < YR_V1);  FORWARD(SUBT) = NO;  NO_RT(R,T(BACKWARD)) = 1;  RT_PP(R,T) = SUBT(T)$(NOT NO_RT(R,T));
        backward = [t for t in T if M[t] < yr_v1]
        forward = [t for t in forward if t not in subt]
        no_rt |= {(r, t) for r in regs for t in backward}
        rt_pp = [(r, t) for r in regs for t in T if t in subt and (r, t) not in no_rt]
        _set(db, "SUBT", [(t,) for t in subt])
        _set(db, "BACKWARD", [(t,) for t in backward])
        _set(db, "FORWARD", [(t,) for t in forward])
        _set(db, "RT_PP", rt_pp)
        _set(db, "NO_RT", [(r, t, 1.0) for (r, t) in sorted(no_rt)])
        # --- V(FORWARD) = NO;
        _set(db, "MODLYEAR", [(y,) for y in modl if y not in forward])
        # --- IF(CARD(SUBT), MIYR_VL = SMAX(SUBT(T),E(T)));
        #     Y_EOH(EOHYEARS)$((YEARVAL(EOHYEARS) <= MIYR_VL)$(YEARVAL(EOHYEARS) >= MINYR)) = YES;  MIYR_L(YEAR+Z) = YES (the year MIYR_VL)
        miyr = max(E[t] for t in subt)
        s["MIYR_VL"] = miyr
        db.assign("Y_EOH", f"select y from EOHYEARS where yv(y) <= {miyr} and yv(y) >= {s['MINYR']}")
        db.assign("MIYR_L", f"select y from ALLYEAR where y = '{int(miyr)}'")
        # --- coef_alt.lin STP: OPTION CLEAR=PERDINV,CLEAR=TPULSE,CLEAR=TPULSEYR; ... OBJ_LINT;   (OBLONG: nothing else)
        db.clear("PERDINV", "TPULSEYR", "TPULSE")
        costs.pulse(db)
        # --- OBJ_LIFE recomputed; $BATINCLUDE eqobsalv.mod STP EXIT  (salvage at the end of the window)
        fwd = {int(t) for t in forward}
        _, tabs = objective.step_tables(db, db.obj_steps, miyr, fwd)
        for n, rows in tabs.items():
            if n == "SALV_DEC":
                # --- SALV_DEC(OBJ_SUMS3(R,V,P),CUR)$COR_SALVD(R,V,P,CUR) = ...   (not cleared: values outside OBJ_SUMS3 stay)
                db.zap(n, "in_OBJ_SUMS3(r,y,p) and in_COR_SALVD(r,y,p,cur)")
            else:
                db.clear(n)
            db.load_rows(n, rows)
        # --- RVPRL(R,K,P)$RVPRL(R,K,P)=MAX(1,SMAX(RTP_CPTYR(R,VNT(K,V(T)),P),YEARVAL(V))-YEARVAL(K));
        db.put("RVPRL", """select a.r, a.y, a.p, greatest(1, coalesce((select max(yv(c.y2)) from RTP_CPTYR c
                                 where c.r=a.r and c.y=a.y and c.p=a.p and in_VNT(a.y,c.y2) and in_MILESTONYR(c.y2) and in_MODLYEAR(c.y2)),
                                 '-inf'::double) - yv(a.y)) as value from RVPRL a""")
        # ---- user constraints: remove UC_T_SUM if it does not overlap with SUBT, UC_T_EACH for all but SUBT, UC_T_SUCC
        #      until not completely fixed or if even partly pending
        x("create or replace temp table t_rxx as select distinct e.r, e.uc from UC_R_EACH e join UC_T_SUM u on u.r=e.r and u.uc=e.uc where in_RT_PP(u.r,u.y)")
        x("create or replace temp table t_uncd1 as select distinct u.uc from UC_R_SUM s join UC_T_SUM u on u.r=s.r and u.uc=s.uc where in_RT_PP(u.r,u.y)")
        db.zap("UC_T_SUM", "in_FORWARD(y)")
        db.zap("UC_T_SUM", """uc not in (select uc from t_uncd1) and not exists(select 1 from t_rxx x where x.r="UC_T_SUM".r and x.uc="UC_T_SUM".uc)""")
        db.assign("UC_T", """select distinct e.uc, e.y from UC_T_EACH e where in_UC_R_SUM(e.r,e.uc) and in_RT_PP(e.r,e.y)
                             union select distinct e.uc, e.y from UC_T_SUCC e where in_UC_R_SUM(e.r,e.uc) and in_RT_PP(e.r,e.y)""")
        db.zap("UC_T_EACH", "in_UC_R_SUM(r,uc) and not in_UC_T(uc,y)")
        db.zap("UC_T_SUCC", "in_UC_R_SUM(r,uc) and in_UC_DYNDIR(r,uc,'RHS') and not in_UC_T(uc,y)")
        db.zap("UC_T_EACH", "in_UC_R_EACH(r,uc) and not in_RT_PP(r,y)")
        db.zap("UC_T_SUCC", "in_UC_R_EACH(r,uc) and in_UC_DYNDIR(r,uc,'RHS') and not in_RT_PP(r,y)")
        # --- UC_T_SUCC(UC_T_SUCC(R,UC_N,T-1)) = UC_DYNDIR(R,UC_N,'RHS')+RT_PP(R,T);
        #     (the element of the period before T: it stays when the constraint is dynamic on the RHS or T is in the window)
        x("create or replace temp table t_ord as select y, row_number() over (order by yv(y)) as o from MILESTONYR")
        x("""create or replace temp table t_succ as select u.r, u.uc, u.y,
                 (in_UC_DYNDIR(u.r,u.uc,'RHS') or in_RT_PP(u.r,n.y)) as yes_
             from UC_T_SUCC u join t_ord o on o.y=u.y join t_ord n on n.o=o.o+1""")
        db.remove("UC_T_SUCC", select="select r, uc, y from t_succ where not yes_")
        db.add("UC_T_SUCC", "select r, uc, y from t_succ where yes_")
        # --- UC_T(UC_N,T)$(NOT SUM(R$NO_RT(R,T),1)) = NO;
        db.zap("UC_T", "not exists(select 1 from NO_RT n where n.y=\"UC_T\".y)")
        # --- RHS and bounds relaxation: IF(CARD(BACKWARD) OR MY_FYEAR, ...)
        #     R_UCT(R_UC(R,UC_N),T)$(UC_T_EACH(R,UC_N,T)+UC_T_SUCC(R,UC_N,T)) = YES; LOOP(UC_R_SUM(R_UC(R,UC_N)),UC_T(UC_N,T)$R_UCT(R,UC_N,T) = YES);
        #     R_UCT(R,UC_N,T)$(NOT REG_FIXT(R)) = NO;
        #     (without FIXBOH, REG_FIXT is 0: nothing regional is relaxed, and the global RHS are guarded)
        db.clear("R_UCT")
        if backward:
            db.add("UC_T", """select distinct u.uc, u.y from (select r, uc, y from UC_T_EACH union select r, uc, y from UC_T_SUCC) u
                              where in_R_UC(u.r,u.uc) and in_UC_R_SUM(u.r,u.uc)""")
        # --- $BATINCLUDE bnd_ucw.mod
        _bnd_ucw(db)
        # --- OPTION UC_RTSUC < UC_T_SUCC;
        db.assign("UC_RTSUC", "select distinct r, y, uc from UC_T_SUCC")
        # ---- capacities: VAR_CAP.UP(RTP(R,BACKWARD(T),P)) = INF; VAR_CAP.LO(..) = 0;
        #      NO_RVP(RTP_VARP(R,SUBT(T),P))$SUM(RTP_CPTYR(R,BACKWARD(TT),T,P),1) = YES;  VAR_CAP.UP/LO(NO_RVP) $= CAP_BND  (empty)
        db.assign("NO_RVP", """select distinct v.r, v.y, v.p from RTP_VARP v join RTP_CPTYR c on c.r=v.r and c.y2=v.y and c.p=v.p
                               where in_SUBT(v.y) and in_BACKWARD(c.y)""")
        db.zap("B_VAR_CAP", "in_BACKWARD(d1) or in_FORWARD(d1)")
        # ---- cumulative variables: $BATINCLUDE bnd_cum.mod COM_VAR (no change without bounds of type N);
        #      Z = (SMAX(T,M(T)) > MIYR_VL);  FIL(LL) = Z*(MIYR_VL < YEARVAL(LL));
        #      VAR_CUMFLO.LO(R,P,C,YEAR,FIL)$(NOT FLO_CUM(R,P,C,YEAR,FIL,'N')) = 0;
        #      VAR_CUMCOM.LO(R,C,COM_VAR,YEAR,FIL)$(NOT COM_CUM(R,COM_VAR,YEAR,FIL,C,'N')) = 0;   (solve.stp line 230)
        #      bnd_cum.mod drops for good a cumulative commodity bound whose first year lies after the window (RC_CUMCOM = NO,
        #      COM_CUM = EPS): RC_CUMCOM and COM_CUM are not restored between steps, as in GAMS.
        z = max(M.values()) > miyr
        db.assign("FIL", f"select y from ALLYEAR where y <> '0' and {'true' if z else 'false'} and yv(y) > {miyr}")
        _bnd_cum(db)
        x("""update "B_VAR_CUMFLO" set lower = 0 where in_FIL(d4) and not in_FLO_CUM(d0,d1,d2,d3,d4,'N')""")
        x("""update "B_VAR_CUMCOM" set lower = 0 where in_FIL(d4) and not in_COM_CUM(d0,d2,d3,d4,d1,'N')""")
        step = dict(step=k, year=int(yr_v1), subt=list(subt), backward=list(backward), forward=list(forward))
        if hook:
            hook(db, step)
        _take(db, step)
        db.steps.append(step)
        # ---------------------------------------------------------------- after the solve: the next window
        # --- SUBT(T) = SUBT(T-1);  Z = SMIN(FORWARD(T),B(T));  YR_V1 = SMIN(SUBT(T)$(M(T) GE Z-G_OVERLAP),M(T));
        #     Z = YR_V1 + YR_VL;  SUBT(T)$(M(T) < Z) = YES;  SUBT(T)$(M(T) < YR_V1) = NO;
        shifted = [T[i + 1] for i, t in enumerate(T[:-1]) if t in subt]
        z = min((B[t] for t in forward), default=INF)
        yr_v1 = min((M[t] for t in shifted if M[t] >= z - overlap), default=INF)
        z = yr_v1 + yr_vl
        subt = [t for t in T if (t in shifted or M[t] < z) and not M[t] < yr_v1]
        _set(db, "SUBT", [(t,) for t in subt])
        # --- restore: V(T) = YES; UC_T_SUM(R,UC_N,T) $= STP_UCT('1',R,UC_N,T); ... (added back, not replaced)
        for n, rows in stp_uct.items():
            db.x(f"create or replace temp table t_back as select * from \"{n}\" limit 0")
            if rows:
                db.insert_rows("t_back", rows)
            db.add(n, "select * from t_back")
        # --- $BATINCLUDE bndmain.mod mod 1   (bounds reset for the next window)
        _bndmain1(db)


def _set(db, name, rows):
    db.clear(name)
    db.load_rows(name, rows)


def _bnd_ucw(db):
    """bnd_ucw.mod: the slack variables of the user constraints take the RHS as bounds (UC_T_EACH(UC_T_SUCC) = YES
    while the bounds are set, = NO afterwards: a constraint that is both loses its UC_T_EACH)."""
    for v in ("VAR_UCR", "VAR_UCT", "VAR_UCRT", "VAR_UCTS", "VAR_UCRTS"):
        db.zap(f"B_{v}")
    bounds.uc_bounds(db)
    db.remove("UC_T_EACH", select="select r, uc, y from UC_T_SUCC")


def _bnd_cum(db):
    """bnd_cum.mod: VAR_CUMFLO.LO/UP from FLO_CUM, VAR_CUMCOM.LO/UP from COM_CUM (with MIYR_VL of the step)."""
    db.zap("B_VAR_CUMFLO")
    db.zap("B_VAR_CUMCOM")
    bounds.cum_bounds(db)


def _bndmain1(db):
    """bndmain.mod with argument 1, as far as it changes the bounds kept here: the bounds of new capacity and of the
    net / gross production of commodities are set for the periods of the (new) window only; then bnd_ucw.mod."""
    for v in ("VAR_NCAP", "VAR_COMNET", "VAR_COMPRD", "VAR_CAP"):
        db.zap(f"B_{v}")
    bounds.ncap_bounds(db, window=True)
    bounds.com_bounds(db, window=True)
    bounds.cap_bounds(db)
    _bnd_ucw(db)
