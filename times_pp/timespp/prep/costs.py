# SPDX-License-Identifier: GPL-3.0-or-later
"""coefmain.mod, the cost part: cost series over the years (fillcost.gms), discounting and the cost coefficients
of coef_obj.mod, period pulse weights (coef_alt.lin)."""
import time
from ..controls import unsupported
from .. import kernels
from ..engine import DB
from .common import require_empty


# ---------------------------------------------------------------------------
def fillcost(db: DB, src, dst, fil, take="true", bext=False, fext=False, mode2=False):
    """fillcost.gms: cost series over the years in `fil` (interpolated between data years, extrapolated outside).

    src   parameter with the data, indexed (R,year,rest..)
    dst   mode2: target OB_X(R,rest..,year);  otherwise the result is written back to `src` on the years in `fil`
    take  SQL condition on a row `a` of src
    bext / fext   limit backward / forward extrapolation to the process years PRC_YMIN / PRC_YMAX (temp table t_yrng)
    """
    if not db.card(src):
        return
    if kernels.mode("fillcost") == "off":
        return _fillcost(db, src, dst, fil, take, bext, fext, mode2)
    kernels.run("fillcost", db, [dst if mode2 else src], lambda: _fillcost(db, src, dst, fil, take, bext, fext, mode2),
                lambda: _fillcost_kernel(db, src, dst, fil, take, bext, fext, mode2))


def _fillcost_kernel(db: DB, src, dst, fil, take, bext, fext, mode2):
    """fillcost in Julia (jlkernels/src/fillcost.jl): the rows _fillcost writes, to the bit."""
    import numpy as np
    K = "fillcost"
    key = [c for c in db.cols(src) if c != "y"]
    years = [int(y) for (y,) in db.q(f"select y from ({fil}) order by yv(y)")]
    on_dm = f"({take}) and a.y in (select y from DM_YEAR) and a.y <> '0'"
    if key and db.q1(f'select count(*) from "{src}" a where {on_dm} and ({" or ".join(f"a.{c} is null" for c in key)})'):
        raise kernels.Decline("a NULL label")
    yint = "try_cast(f.y as INTEGER)"
    # the records on DM_YEAR (the others count for nothing): an EPS (0) or NULL value carried as 1e-300, as fillcost does
    r = kernels.to_julia(db, K, src, key, f"""coalesce({yint}, 0) as yint,
        case when f.value is null or f.value = 0 then 1e-300 else f.value end as value,
        coalesce(cast({yint} as varchar) <> f.y, true) as bad""", where=on_dm, alias="a")
    if r["bad"].any():
        raise kernels.Decline("a year of DM_YEAR that is not the text of an integer")
    ri = key.index("r") + 1 if (bext or fext) else 0
    pi = key.index("p") + 1 if (bext or fext) else 0
    if bext or fext:
        g = kernels.to_julia(db, K, "t_yrng", ["r", "p"], "f.lo, f.hi")
        rng = [np.asarray(g["c0"], np.int32), np.asarray(g["c1"], np.int32), np.asarray(g["lo"], np.float64),
               np.asarray(g["hi"], np.float64)]
    else:
        rng = [np.empty(0, np.int32), np.empty(0, np.int32), np.empty(0), np.empty(0)]
    par = np.array([len(key), mode2, bext, fext, ri, pi], np.float64)
    out = kernels.call(K, [par] + [np.asarray(r[f"c{i}"], np.int32) for i in range(len(key))]
                       + [np.asarray(r["yint"], np.int32), np.asarray(r["value"], np.float64),
                          np.array(years, np.int32)] + rng)
    t = time.perf_counter()
    nk = len(key)
    if len(out[nk]):
        target = dst if mode2 else src
        rel = kernels.from_julia(db, "u_", key, out[:nk], {"y": out[nk], "value": out[nk + 1]},
                                 "cast(f.y as VARCHAR) as y, f.value")
        db.put(target, f"select {', '.join(db.cols(target))}, value from {rel} u_", zero="eps")   # a zero is EPS
        db.con.unregister("u_")
    kernels.tally(K, "julia -> duckdb", time.perf_counter() - t, len(out[nk]))


def _fillcost(db: DB, src, dst, fil, take, bext, fext, mode2):
    cols = db.cols(src)
    key = [c for c in cols if c != "y"]
    ks = ", ".join(f"a.{c}" for c in key)
    years = [int(y) for (y,) in db.q(f"select y from ({fil}) order by yv(y)")]
    dm = {y for (y,) in db.q("select y from DM_YEAR")}
    series = {}
    for row in db.q(f'select {ks}, a.y, a.value from "{src}" a where ({take})'):
        series.setdefault(row[:-2], {})[row[-2]] = row[-1] if row[-1] else 1e-300          # EPS carried as a tiny number
    rng = {}
    if bext or fext:
        rng = {(r, p): (lo, hi) for r, p, lo, hi in db.q("select r, p, lo, hi from t_yrng")}
        ri, pi = key.index("r"), key.index("p")
    out = []
    for k, d in series.items():
        pts = sorted((int(y), v) for y, v in d.items() if y in dm and y != "0")
        f, first, last, lasty, mid = 0, None, 0.0, None, {}
        for z, v in pts:
            if last:                                   # IF(LAST_VAL, ... linear interpolation
                slope = (v - last) / (z - lasty)
                for y in range(lasty + 1, z):
                    mid[y] = v + slope * (y - z)
            else:
                f, first = z, v
            last, lasty = v, z
        if lasty is None:
            continue
        if mode2:
            mid.update({z: v for z, v in pts})
        # a process outside RP(R,P) has no PRC_YMIN / PRC_YMAX: 0 for both, so YEARVAL GE 0 extrapolates backward and
        # YEARVAL LE 0 never forward (coef_obj.mod 116-117; a cost given where the process has no topology)
        lo, hi = rng.get((k[ri], k[pi]), (0.0, 0.0)) if (bext or fext) else (-1e9, 1e9)
        for y in years:
            v = mid.get(y, 0.0)
            if y < f and (not bext or y >= lo):
                v += first
            if y > lasty and (not fext or y <= hi):
                v += last
            if v:
                out.append(k + (str(y), v if abs(v) > 1e-200 else 0.0))
    target = dst if mode2 else src
    tcols = db.cols(target)
    db.x(f"create or replace temp table fc_out ({', '.join(c + ' VARCHAR' for c in key)}, y VARCHAR, value DOUBLE)")
    if out:
        import pandas as pd
        df = pd.DataFrame(out, columns=key + ["y", "value"])
        db.con.register("fc_df", df); db.x("insert into fc_out select * from fc_df"); db.con.unregister("fc_df")
    db.put(target, f"select {', '.join(tcols)}, value from fc_out", zero="eps")           # a zero left here is EPS


def coef_obj(db: DB):
    s = db.s
    # --- TS_ANN(S,S) = YES; TS_ANN(S,ANNUAL) = YES;
    db.assign("TS_ANN", "select s, s as s2 from ALL_TS union select s, 'ANNUAL' from ALL_TS")
    # --- YR_VL = MIYR_VL+DUR_MAX;  LOOP(RTP(R,PASTMILE(LL),P)$NCAP_ILED(RTP), K(LL+NCAP_ILED(RTP)) = YES);
    s["YR_VL"] = s["MIYR_VL"] + s["DUR_MAX"]
    db.add("EACHYEAR", """select distinct ys(yv(y) + v_NCAP_ILED(r,y,p)) as y from RTP where in_PASTMILE(y)
                          and v_NCAP_ILED(r,y,p) <> 0 and in_ALLYEAR(ys(yv(y) + v_NCAP_ILED(r,y,p)))""")
    # --- Y(K)$((YEARVAL(K) >= MINYR) * (YEARVAL(K) <= YR_VL)) = YES;  YK(Y,K)$(YEARVAL(K)<=YEARVAL(Y)) = YES;
    db.assign("Y", "select y from EACHYEAR where yv(y) >= {MINYR} and yv(y) <= {YR_VL}")
    db.assign("YK", "select a.y, k.y as y2 from Y a, EACHYEAR k where yv(k.y) <= yv(a.y)")
    if str(db.env.get("ANNCOST", "")).strip().strip("'\"").upper() == "LEV":
        # --- coef_obj.mod 31: $IFI '%ANNCOST%'==LEV ACL=MINYR; MINYR=MIYR_V1; RPT_OPT('OBJ','2')=1;
        s["ACL"] = s["MINYR"]
        s["MINYR"] = s["MIYR_V1"]
        i, j = db.cols("RPT_OPT")
        db.put("RPT_OPT", f"select 'OBJ' as {i}, '2' as {j}, 1.0 as value")
        # --- coef_obj.mod 32: $IFI '%ANNCOST%%CTST%'==LEV MINYR=ACL;
        #     only with CTST '' (no OBLONG, OBJ not ALT/LIN). With OBLONG (CTST '**0') MINYR stays at MIYR_V1 for the
        #     rest of the run: Y_EOH below, OBJ_PASTI (eqobjinv.mod 86), OBJ_LIFE (eqobjfix.mod 162) and solve.stp 119.
        if db.ctl["CTST"] == "":
            s["MINYR"] = s["ACL"]
    # --- Y_EOH(EOHYEARS)$(YEARVAL(EOHYEARS) >= MINYR) = YES;
    db.assign("Y_EOH", "select y from EOHYEARS where yv(y) >= {MINYR}")
    # --- YR_V1 = MIN(SMIN(DATAYEAR,YEARVAL),PYR_V1);  YR_VL = MAX(SMAX(DATAYEAR,YEARVAL),YR_VL);  FIL(LL) = YR_V1 <= YEARVAL(LL) <= YR_VL
    s["YR_V1"] = min(db.q1("select min(yv(y)) from DATAYEAR"), s["PYR_V1"])
    s["YR_VL"] = max(db.q1("select max(yv(y)) from DATAYEAR"), s["YR_VL"])
    y1, yl = int(s["YR_V1"]), int(s["YR_VL"])
    #     the year set ends with EOTIME: FIL cannot go beyond it, and the element that follows it in LL is '0'
    eot = int(db.ctl["EOTIME"])
    spill = yl >= eot
    yl = min(yl, eot)
    # --- filparam G_DRATE 'R,' CUR ... ALLYEAR LL FIL(LL)$ FIL(LL)$     (discount rates for every year)
    #     EPS is a value here (LOOP(LL$MY_ARRAY(LL)) takes it, `$= FIRST_VAL$(..)` assigns it): it is carried as
    #     interp.EPS, as in interp.filparam, and stored as EPS (a rate given as 0 under $ONEPS: GAMS, objective_*_gdrate_0)
    from ..interp import EPS, TINY
    ser = {}
    for r, y, cur, v in db.q("select r, y, cur, value from G_DRATE where in_REG(r)"):
        ser.setdefault((r, cur), {})[y] = v if v != 0 else EPS
    rows = []
    for (r, cur), d in ser.items():
        dfunc = round(d.get("0", 0.0))
        if dfunc < 0:
            continue
        pts = sorted((int(y), v) for y, v in d.items() if y != "0")
        if not pts:
            continue
        for (z0, v0), (z1, v1) in zip(pts, pts[1:]):
            rows += [(r, str(y), cur, v0 + (v1 - v0) / (z1 - z0) * (y - z0)) for y in range(z0 + 1, z1)]
        f, z, first, last = pts[0][0], pts[-1][0], pts[0][1], pts[-1][1]
        if dfunc > 1:
            m = dfunc % 10
            if m == 2:
                first = last = EPS
            elif m == 4:
                z = float("inf")
            elif m == 5:
                f = 0
        if dfunc != 1:
            rows += [(r, str(y), cur, first) for y in range(y1, yl + 1) if y < f and first]
            rows += [(r, str(y), cur, last) for y in range(y1, yl + 1) if y > z and last]
    rows = [(r, y, cur, 0.0 if abs(v) < TINY else v) for (r, y, cur, v) in rows if v != 0]
    if rows:
        db.x("create or replace temp table t_dr (r VARCHAR, y VARCHAR, cur VARCHAR, value DOUBLE)")
        db.insert_rows("t_dr", rows)
        db.put("G_DRATE", "select r, y, cur, value from t_dr", zero="eps")
    # --- OBJ_DISC(R,LL,CUR)$(RDCUR(R,CUR)$(YEARVAL(LL)=YR_V1)) = 1;
    #     LOOP(FIL(LL-1), OBJ_DISC(R,LL,CUR) = OBJ_DISC(R,FIL,CUR) / (1+G_DRATE(R,LL,CUR)));
    #     normalised to the base year G_DYEAR for the years in FIL (the year after FIL keeps its raw value, as in GAMS)
    if s["G_DYEAR"] == 0:
        s["G_DYEAR"] = db.q1("select yv(y) from MIYR_1")
    gd = s["G_DYEAR"]
    yd = int(max(min(yl, gd), y1))
    rate = {(r, int(y), cur): v for r, y, cur, v in db.q("select r, y, cur, value from G_DRATE where y <> '0'")}
    rows = []
    for r, cur in db.q("select r, cur from RDCUR"):
        disc = {y1: 1.0}
        for y in range(y1 + 1, yl + 2):
            disc[y] = disc[y - 1] / (1 + rate.get((r, y, cur), 0.0))
        z = disc[yd] * (1 + rate.get((r, yd, cur), 0.0)) ** (-(gd - yd))
        rows += [(r, str(y), cur, (v / z if y <= yl else v)) for y, v in disc.items() if y <= yl or not spill]
        if spill:                               # LOOP(FIL(LL-1), ..) reaches the label '0' after the last year
            opt = db.q1(f"select value from G_DRATE where r='{r}' and y='0' and cur='{cur}'") or 0.0
            rows.append((r, "0", cur, disc[yl] / (1 + opt)))
    db.clear("OBJ_DISC")
    db.load_rows("OBJ_DISC", [x for x in rows if x[1] == "0" or db_has_year(db, x[1])])
    # --- G_DRATE(R,V,CUR)$((G_DRATE(R,V,CUR) LE 0)$RDCUR(R,CUR)) = 1E-11;
    db.put("G_DRATE", "select d.r, v.y, d.cur, 1e-11 as value from RDCUR d, MODLYEAR v where v_G_DRATE(d.r,v.y,d.cur) <= 0")
    # --- G_RCUR: the discounted currency of each region with the largest present value of the horizon
    db.add("G_RCUR", """
        with pv as (select d.r, d.cur, (select sum(v_D(t.y) * v_OBJ_DISC(d.r,t.y,d.cur) order by yv(t.y)) from MILESTONYR t) as f,
                           (select u.ord from __uel u where u.label=d.cur) as o from RDCUR d)
        select r, arg_min(cur, o) as cur from pv a where f > 0 and abs(f - (select max(b.f) from pv b where b.r=a.r)) < 1e-7
          and not exists(select 1 from G_RCUR g join RDCUR q on q.r=g.r and q.cur=g.cur where g.r=a.r) group by r""")
    # --- OBJ_PVT(R,T,CUR)$RDCUR(R,CUR) = SUM(PERIODYR(T,Y_EOH),OBJ_DISC(R,Y_EOH,CUR));  COEF_PVT(R,T) = SUM(G_RCUR(R,CUR),OBJ_PVT(R,T,CUR));
    db.put("OBJ_PVT", """select d.r, t.y, d.cur, (select sum(v_OBJ_DISC(d.r,p.y2,d.cur) order by yv(p.y2)) from PERIODYR p where p.y=t.y and in_Y_EOH(p.y2)) as value
                         from RDCUR d, MILESTONYR t""")
    db.put("COEF_PVT", "select g.r, t.y, sum(v_OBJ_PVT(g.r,t.y,g.cur) order by g.cur) as value from G_RCUR g, MILESTONYR t group by g.r, t.y")
    # COEF_PVT for the equations, as UC_PVT (port-only), in the regions of user constraints with PERDISC
    # (uc_flo.mod line 22, uc_ire.mod 21, uc_act.mod 22, uc_com.mod 25); no table when no model constraint has it
    if db.q1("select count(*) from UC_ATTR where ucn='PERDISC'"):
        db.declare("UC_PVT", "par", ["R", "T"])
        db.put("UC_PVT", "select p.r, p.y, p.value from COEF_PVT p where p.r in (select r from UC_ATTR where ucn='PERDISC')")
    # --- OBJ_RFR(R,V,CUR) $= G_DRATE(R,V,CUR);
    #     OBJ_RFR(R,V,CUR)$((G_RFRIR(R,V)>0)$RDCUR(R,CUR)) $= G_RFRIR(R,V);
    #     (a risk-free rate of 0, EPS or below 0 is not taken: the discount rate stays)
    db.put("OBJ_RFR", "select r, y, cur, value from G_DRATE where in_MODLYEAR(y) and in_REG(r)", zero="eps")
    db.put("OBJ_RFR", "select g.r, g.y, d.cur, g.value from G_RFRIR g join RDCUR d on d.r=g.r where in_MODLYEAR(g.y) and g.value > 0")
    # --- OBJ_COMNT(R,DATAYEAR,C,S,COSTYPE,CUR)$(NOT COM_TS(R,C,S)) = 0;  same for OBJ_COMPD
    for n in ("OBJ_COMNT", "OBJ_COMPD"):
        db.zap(n, "in_DATAYEAR(y) and in_REG(r) and not in_COM_TS(r,c,s)")
    # --- LOOP(ALL_R$(NOT REG(ALL_R)),OBJ_IPRIC(R,DATAYEAR,P,C,S,IE,CUR)$RPC_IREIO(R,P,C,IE,'OUT') $=
    #        IRE_PRICE(R,DATAYEAR,P,C,S,ALL_R,IE,CUR)*(1-2$XPT(IE)));   then the same with the region itself as partner
    for part in ("not in_REG(a.r2)", "a.r2 = a.r"):
        db.put("OBJ_IPRIC", f"""select a.r, a.y, a.p, a.c, a.s, a.ie, a.cur,
                                       arg_max(a.value * (case when a.ie='EXP' then -1 else 1 end), (select u.ord from __uel u where u.label=a.r2)) as value
                                from IRE_PRICE a where in_DATAYEAR(a.y) and in_REG(a.r) and in_RPC_IREIO(a.r,a.p,a.c,a.ie,'OUT')
                                  and {part} group by all""", zero="eps")
        #     ($= copies an EPS price: IRE_PRICE given as 0 under $ONEPS stays EPS, and fillcost keeps it as a data point,
        #      so the years before the next price are not extrapolated backward from it; EQ_OBJVAR x VAR_IRE)
    # --- FLO_COST(R,LL,P,C,S,CUR)$((NOT TOP(R,P,C,'IN'))$RPC_STG(R,P,C)) = 0;  FLO_DELIV(...)$((NOT TOP(R,P,C,'OUT'))$RPC_STG(R,P,C)) = 0;
    db.zap("FLO_COST", "in_RPC_STG(r,p,c) and not in_TOP(r,p,c,'IN')")
    db.zap("FLO_DELIV", "in_RPC_STG(r,p,c) and not in_TOP(r,p,c,'OUT')")
    # --- * remove proportional subsidy if absolute defined
    #     IF(CARD(NCAP_ISPCT),OPTION PRC_YMAX<NCAP_ISUB; NCAP_ISPCT(R,LL,P)$PRC_YMAX(R,P)=0);
    #     (PRC_YMAX is only borrowed as a work set here; it is assigned again below, t_yrng)
    if db.card("NCAP_ISPCT"):
        db.x("delete from NCAP_ISPCT a where exists(select 1 from NCAP_ISUB b where b.r=a.r and b.p=a.p)")
    # --- OBJ_BLNDV(R,Y_EOH,BLE,OPR,CUR)$(RDCUR(R,CUR)$BLE_OPR(R,BLE,OPR)) = BL_VAROMC(R,BLE,CUR) +
    #               SUM(COM$BL_DELIVC(R,BLE,COM,CUR), BL_INP(R,BLE,COM) * BL_DELIVC(R,BLE,COM,CUR));
    if db.card("BLE_OPR"):
        db.put("OBJ_BLNDV", """select o.r, y.y, o.c, o.c2, d.cur,
                                      v_BL_VAROMC(o.r,o.c,d.cur) + coalesce((select sum(v_BL_INP(b.r,b.c,b.c2) * b.value) from BL_DELIVC b
                                                                             where b.r=o.r and b.c=o.c and b.cur=d.cur), 0.0) as value
                               from BLE_OPR o join RDCUR d on d.r=o.r, Y_EOH y""")
        # a cost given as EPS with no value beside it: the sum is EPS, a record (BL_VAROMC EPS; BL_INP * BL_DELIVC with
        # one factor EPS and the other on record)
        db.put("OBJ_BLNDV", """select o.r, y.y, o.c, o.c2, d.cur, 0.0 as value
                               from BLE_OPR o join RDCUR d on d.r=o.r, Y_EOH y
                               where not in_OBJ_BLNDV(o.r,y.y,o.c,o.c2,d.cur)
                                 and v_BL_VAROMC(o.r,o.c,d.cur) = 0
                                 and coalesce((select sum(v_BL_INP(b.r,b.c,b.c2) * b.value) from BL_DELIVC b
                                               where b.r=o.r and b.c=o.c and b.cur=d.cur), 0.0) = 0
                                 and (in_BL_VAROMC(o.r,o.c,d.cur)
                                      or exists(select 1 from BL_DELIVC b where b.r=o.r and b.c=o.c and b.cur=d.cur
                                                and in_BL_INP(b.r,b.c,b.c2) and v_BL_INP(b.r,b.c,b.c2) * b.value = 0))""", zero="eps")
    # --- OBJ_FSUB(R,LL,P,C,S,CUR) $= FLO_TAX(R,LL,P,C,S,CUR);
    #     OBJ_FSUB(R,LL,P,C,S,CUR)$FLO_SUB(R,LL,P,C,S,CUR) = OBJ_FSUB(R,LL,P,C,S,CUR)-FLO_SUB(R,LL,P,C,S,CUR);
    #     OBJ_FSUB(R,LL,P,C,S,CUR)$((NOT V(LL))$OBJ_VFLO(R,P,C,CUR,'SUB')) = 0;
    #     (net tax = tax less subsidy; OBJ_VFLO 'SUB' is at this point the flag "has both", set in preppm.mod)
    db.clear("OBJ_FSUB")
    db.put("OBJ_FSUB", "select r, y, p, c, s, cur, value from FLO_TAX", zero="eps")
    db.put("OBJ_FSUB", """select b.r, b.y, b.p, b.c, b.s, b.cur, v_OBJ_FSUB(b.r,b.y,b.p,b.c,b.s,b.cur) - b.value as value
                          from FLO_SUB b where b.value <> 0""")
    # an EPS subsidy with no tax leaves EPS (0 - EPS = EPS): the year is then a data point of the series, not a gap
    db.put("OBJ_FSUB", """select b.r, b.y, b.p, b.c, b.s, b.cur, 0.0 as value from FLO_SUB b
                          where b.value = 0 and not in_OBJ_FSUB(b.r,b.y,b.p,b.c,b.s,b.cur)""", zero="eps")
    db.zap("OBJ_FSUB", "in_OBJ_VFLO(r,p,c,cur,'SUB') and not in_MODLYEAR(y)")
    # --- OPTION RPC_CUR <= FLO_COST; OBJ_VFLO(RPC_CUR,'COST') = YES;  OPTION RPC_CUR <= FLO_DELIV; OBJ_VFLO(RPC_CUR,'COST') = YES;
    db.add("OBJ_VFLO", """select distinct r, p, c, cur, 'COST' as ucn from FLO_COST where in_REG(r) union
                          select distinct r, p, c, cur, 'COST' from FLO_DELIV where in_REG(r)""")
    # --- OPTION RPC_CUR <= FLO_TAX; OBJ_VFLO(RPC_CUR,'TAX') = YES;  OPTION RPC_CUR <= FLO_SUB; OBJ_VFLO(RPC_CUR,'SUB') = YES;
    db.add("OBJ_VFLO", """select distinct r, p, c, cur, 'TAX' as ucn from FLO_TAX where in_REG(r) union
                          select distinct r, p, c, cur, 'SUB' from FLO_SUB where in_REG(r)""")
    # --- MY_ARRAY(V) = MIN(B(V),M(V)-IPD(V));  PRC_YMIN(RP(R,P)) = SMIN(RTP(R,V,P),MY_ARRAY(V));
    #     PRC_YMAX(RP(R,P)) = SMAX(RTP(R,PYR,P),YEARVAL(PYR));
    #     LOOP(T, Z = M(T)-E(T)+LAGT(T); PRC_YMAX(RP(R,P))$RTP(R,T,P) = MAX(PRC_YMAX(R,P),E(T)+NCAP_ILED(R,T,P)+MAX(Z,NCAP_TLIFE(R,T,P))$(COEF_RPTI(R,T,P)>1)));
    db.tmp("t_yrng", """
        select k.r, k.p,
               coalesce((select min(least(v_B(t.y), v_M(t.y) - v_IPD(t.y))) from RTP t where t.r=k.r and t.p=k.p), 'inf'::double) as lo,
               greatest(coalesce((select max(yv(t.y)) from RTP t where t.r=k.r and t.p=k.p and in_PASTYEAR(t.y)), '-inf'::double),
                        coalesce((select max(v_E(t.y) + v_NCAP_ILED(t.r,t.y,t.p)
                                             + (case when v_COEF_RPTI(t.r,t.y,t.p) > 1
                                                     then greatest(v_M(t.y)-v_E(t.y)+v_LAGT(t.y), v_NCAP_TLIFE(t.r,t.y,t.p)) else 0 end))
                                  from RTP t where t.r=k.r and t.p=k.p and in_MILESTONYR(t.y)), '-inf'::double)) as hi
        from RP k""")
    # --- Z = SMAX(RP,PRC_YMAX(RP));  FIL(K)$(YEARVAL(K) LE Z) = YES;
    fil = "select y from EACHYEAR where yv(y) <= (select max(hi) from t_yrng)"
    take = "in_RDCUR(a.r,a.cur)"
    for src, dst in (("NCAP_COST", "OB_ICOST"), ("NCAP_ISUB", "OB_ISUB"), ("NCAP_ITAX", "OB_ITAX")):
        fillcost(db, src, dst, fil, take, bext=True, fext=True, mode2=True)
    # --- fillcost NCAP_ISPCT R P ",'0','0','0','0'" FIL 1 %BEXT% %FEXT% NCAP_ISPCT X_RP
    #     IF(CARD(X_RP),OB_ISUB(RP,CUR,YEAR)$X_RP(RP,YEAR) $= OB_ICOST(RP,CUR,YEAR)*X_RP(RP,YEAR); OPTION CLEAR=X_RP);
    #     (the subsidy as a share of the investment cost; where it is given it replaces OB_ISUB, which the rule above
    #      leaves empty for those processes)
    if db.card("NCAP_ISPCT"):
        fillcost(db, "NCAP_ISPCT", "X_RP", fil, "true", bext=True, fext=True, mode2=True)
        db.put("OB_ISUB", """select i.r, i.p, i.cur, i.y, i.value * x.value as value from OB_ICOST i
                              join X_RP x on x.r=i.r and x.p=i.p and x.y=i.y where in_RP(i.r,i.p)""", zero="eps")
        #     (an EPS share - NCAP_ISPCT before its first year under option 5 - gives an EPS subsidy: EPS*x is EPS in GAMS)
        db.clear("X_RP")
    for src, dst in (("NCAP_FOM", "OB_FOM"), ("NCAP_FSUB", "OB_FSB"), ("NCAP_FTAX", "OB_FTX"), ("NCAP_DCOST", "OB_DCC"),
                     ("NCAP_DLAGC", "OB_DLC")):
        fillcost(db, src, dst, fil, take, bext=True, fext=True, mode2=True)
    # --- FIL = Y_EOH from MIYR_V1 on;  %VARCOST%==LIN: FIL(T) = YES
    fil = "select y from MILESTONYR" if db.ctl["VARCOST"] == "LIN" else "select y from Y_EOH where yv(y) >= {MIYR_V1}"
    fil = db.fmt(fil)
    fillcost(db, "ACT_COST", "OB_ACT", fil, "in_RP(a.r,a.p)", mode2=True)
    fillcost(db, "OBJ_COMNT", None, fil, "in_COM_TS(a.r,a.c,a.s)")
    fillcost(db, "OBJ_COMPD", None, fil, "in_COM_TS(a.r,a.c,a.s)")
    fillcost(db, "OBJ_IPRIC", None, fil, "in_RPCS_VAR(a.r,a.p,a.c,a.s)")
    # --- $set take (RPCS_VAR(R,P,C,S)+ANNUAL(S));  fillcost OBJ_FCOST ... FLO_COST OB_FCOS;  fillcost OBJ_FDELV ... FLO_DELIV OB_FDEL
    take = "(in_RPCS_VAR(a.r,a.p,a.c,a.s) or a.s = 'ANNUAL')"
    fillcost(db, "FLO_COST", "OB_FCOS", fil, take, mode2=True)
    fillcost(db, "FLO_DELIV", "OB_FDEL", fil, take, mode2=True)
    # --- fillcost OBJ_FTAX ... OBJ_FSUB OB_FTAX;   OPTION CLEAR=RPC_CUR,CLEAR=OBJ_FSUB;
    fillcost(db, "OBJ_FSUB", "OB_FTAX", fil, take, mode2=True)
    db.clear("OBJ_FSUB", "RPC_CUR")
    # --- coef_obj.mod 180-185 ($IF %TIMESED%==YES): SHEDJ(BD,J) $= SUM(RTC_SHED(R,T,C,BD,J),1); SHEDJ(BDNEQ,'1') = YES;
    #     (RTC_SHED and SHAPED come from COM_ELASTX, which is refused: the set has the first step of LO and UP)
    if db.ctl.get("TIMESED"):
        db.add("SHEDJ", "select l, '1' as j from BDNEQ")


def db_has_year(db, y):
    if not hasattr(db, "_years"):
        db._years = {v for (v,) in db.q("select y from ALLYEAR")}
    return y in db._years


def pulse(db: DB):
    """coef_alt.lin, first part: period pulse weights and OBJ_LINT over the horizon Y_EOH (again for each step of a
    myopic run: coef_alt.lin STP, after OPTION CLEAR=PERDINV,CLEAR=TPULSE,CLEAR=TPULSEYR)."""
    # --- PERDINV(YK(T,K))$(YEARVAL(K) > M(T)-LEAD(T)) = YES;
    db.assign("PERDINV", "select y, y2 from YK where in_MILESTONYR(y) and yv(y2) > v_M(y) - v_LEAD(y)")
    # --- TPULSEYR(PERDINV(T,Y_EOH)) = YES;  TPULSE(TPULSEYR(T,Y_EOH)) = 1-((M(T)-YEARVAL(Y_EOH))/LEAD(T))$(NOT MIYR_1(T));
    db.assign("TPULSEYR", "select y, y2 from PERDINV where in_Y_EOH(y2)")
    db.clear("TPULSE")
    db.put("TPULSE", """select y, y2, 1 - (case when in_MIYR_1(y) then 0 else (v_M(y) - yv(y2)) / v_LEAD(y) end) as value from TPULSEYR""")
    # --- YK1(T,Y_EOH)$(YEARVAL(T)<=YEARVAL(Y_EOH)) = YES;  TPULSEYR(YK1(T,Y_EOH))$(YEARVAL(Y_EOH) < M(T)+LAGT(T)) = YES;
    #     TPULSE(TPULSEYR(YK1(T,LL))) = 1-TPULSE(T+1,LL);
    db.tmp("t_fwd", """select t.y, e.y as y2 from MILESTONYR t, Y_EOH e where yv(t.y) <= yv(e.y) and yv(e.y) < v_M(t.y) + v_LAGT(t.y)""")
    db.add("TPULSEYR", "select y, y2 from t_fwd")
    db.tmp("t_next", "select y, lead(y) over (order by yv(y)) as nxt from MILESTONYR")
    db.put("TPULSE", """select f.y, f.y2, 1 - coalesce((select p.value from TPULSE p join t_next n on n.nxt=p.y where n.y=f.y and p.y2=f.y2), 0) as value
                        from t_fwd f""")
    # --- OBJ_LINT(R,T,TT,CUR)$RDCUR(R,CUR) = SUM(PERIODYR(T,Y_EOH)$TPULSEYR(TT,Y_EOH),TPULSE(TT,Y_EOH)*OBJ_DISC(R,Y_EOH,CUR));
    db.zap("OBJ_LINT", "in_RDCUR(r,cur)")       # (assigned over the whole domain: zeros remove)
    db.put("OBJ_LINT", """select d.r, p.y, q.y as y2, d.cur, sum(v_TPULSE(q.y,p.y2) * v_OBJ_DISC(d.r,p.y2,d.cur) order by yv(p.y2)) as value
                          from RDCUR d, PERIODYR p join TPULSEYR q on q.y2=p.y2
                          where in_MILESTONYR(p.y) and in_Y_EOH(p.y2) group by d.r, p.y, q.y, d.cur""")


# ---------------------------------------------------------------------------
def coef_alt(db: DB):
    """coef_alt.lin VAR%CTST%: period pulse weights, OBJ_LINT, and (OBLONG) discounted capacity transfer COEF_CPT."""
    ctl = db.ctl
    if ctl["CTST"] == "":
        pulse(db)                               # argument VAR: the pulse weights and OBJ_LINT, then $IFI %1==VAR $EXIT
        return
    if not ctl["OBLONG"] or ctl["CTST"] != "zero" or ctl["OBJ"] in ("LIN", "ALT"):
        unsupported(db, "objective variants other than OBLONG with OBJ=AUTO/STD/MOD (coef_alt.lin)")
    pulse(db)
    # --- LOOP(G_RCUR(R,CUR), R_DF(R,V) = 1/(1+G_DRATE(R,V,CUR)));  RB(R,T) = B(T);
    db.put("R_DF", "select g.r, v.y, 1 / (1 + v_G_DRATE(g.r,v.y,g.cur)) as value from G_RCUR g, MODLYEAR v")
    # --- PASTSUM(RTP(R,V,P))$PRC_CAP(R,P) = B(V)+NCAP_ILED(R,V,P)+COEF_RPTI(R,V,P)*NCAP_TLIFE(R,V,P);     (before the lead times below change)
    db.tmp("t_pastsum", """select r, y, p, v_B(y)+v_NCAP_ILED(r,y,p)+v_COEF_RPTI(r,y,p)*v_NCAP_TLIFE(r,y,p) as value
                           from RTP where in_PRC_CAP(r,p)""")
    # --- IF(INT_DEFAULT('PASTI'), NCAP_ILED(R,PHYR(V),P)$(NCAP_ILED(R,V,P)>COEF_ILED(R,V,P)) =
    #        LOG(1-(1-R_DF(R,V))*(NCAP_ILED(R,V,P)-COEF_ILED(R,V,P)))/LOG(R_DF(R,V)));
    if db.q1("select count(*) from INT_DEFAULT where u='PASTI'"):
        db.put("NCAP_ILED", """select r, y, p, ln(1 - (1 - v_R_DF(r,y)) * (value - v_COEF_ILED(r,y,p))) / ln(v_R_DF(r,y)) as value
                               from NCAP_ILED where in_PHYR(y) and in_MODLYEAR(y) and value > v_COEF_ILED(r,y,p)""")
    db.put("RB", "select r, y, v_B(y) as value from REG, MILESTONYR")
    # --- PASTSUM(RTP(R,V,P))$PRC_CAP(R,P) = B(V)+NCAP_ILED(R,V,P)+COEF_RPTI(R,V,P)*NCAP_TLIFE(R,V,P);
    #     LOOP(G_RCUR(R,CUR), FIL2(T) = R_DF(R,T);
    #       MY_ARRAY(T) = E(T)+1; MY_ARRAY(TT(T-1)) = RB(R,T);  MY_ARRAY(T) = 1-FIL2(T)**(MY_ARRAY(T)-RB(R,T)-1e-8);
    #       COEF_CPT(RTP_CPTYR(R,V,T,P))$PASTSUM(R,V,P) =
    #         MIN(1,(1-FIL2(T)**(PASTSUM(R,V,P)-RB(R,T)))/MY_ARRAY(T)) - ((1-FIL2(T)**MAX(0,B(V)+NCAP_ILED(R,V,P)-RB(R,T))) / MY_ARRAY(T))$NCAP_ILED(R,V,P));
    db.tmp("t_per", """select g.r, t.y, v_R_DF(g.r,t.y) as df, v_RB(g.r,t.y) as rb,
                              1 - pow(v_R_DF(g.r,t.y), coalesce((select v_RB(g.r,n.nxt) from t_next n where n.y=t.y and n.nxt is not null),
                                                                 v_E(t.y) + 1) - v_RB(g.r,t.y) - 1e-8) as arr
                       from G_RCUR g, MILESTONYR t""")
    db.put("COEF_CPT", """
        select c.r, c.y, c.y2, c.p,
               least(1, (1 - pow(k.df, ps.value - k.rb)) / k.arr)
               - (case when in_NCAP_ILED(c.r,c.y,c.p)
                       then (1 - pow(k.df, greatest(0, v_B(c.y)+v_NCAP_ILED(c.r,c.y,c.p) - k.rb))) / k.arr else 0 end) as value
        from RTP_CPTYR c join t_per k on k.r=c.r and k.y=c.y2 join t_pastsum ps on ps.r=c.r and ps.y=c.y and ps.p=c.p
        where ps.value <> 0""")
    # --- COEF_CPT(R,T,TT,P)$((COEF_CPT(R,T,TT,P) LT 1/512)$COEF_CPT(R,T,TT,P)) = 0;
    db.zap("COEF_CPT", "in_MILESTONYR(y) and in_MILESTONYR(y2) and value < 1.0/512")
