# SPDX-License-Identifier: GPL-3.0-or-later
"""Simulated vintages (PRC_SIMV): fillvint.gms (initialisation), ppmain.mod 590, coef_csv.mod.

A process of PRC_SIMV is vintaged with few vintages: in each period its capacity is that of a simulated vintage built
from the real ones (COEF_CSV(r,k,t,p,v): the share of the capacity of vintage k counted in simulated vintage v), and its
activity is limited by EQ_CAPVAC (times_eq equations/capvac.jl) instead of EQ_CAPACT.

  fillvint(db)       fillvint.gms (no arguments): PRC_SIMV leaves out storage, joins PRC_VINT; RTP gets the leading vintages
  leading(db)        ppmain.mod 590: the milestone before each vintage of a period joins RTP
  coef_csv(db)       coef_csv.mod (eqmain.mod, after eqcapact.mod): COEF_CSV, RTP_VINTYR, AFSV

TIMES includes these when PRC_SIMV is DEFINED (the DD files give it).
"""
import math
from ..engine import DB
from .grids import _rows, _set, _par

INF = float("inf")
TRIVINT = 6                 # $IF NOT SET TRIVINT $SET TRIVINT 6


def active(db: DB):
    return db.ctl.get("SIMV", False)


def fillvint(db: DB):
    """fillvint.gms, initialisation part (before the RVP loop of the caller)."""
    db.ctl["SIMV"] = bool(db.card("PRC_SIMV"))
    if not active(db):
        return
    # --- $IF DEFINED PRC_SIMV PRC_SIMV(R,P)$PRC_MAP(R,'STG',P) = NO; PRC_VINT(PRC_SIMV) = YES;
    db.remove("PRC_SIMV", where="in_PRC_MAP(r,'STG',p)")
    db.add("PRC_VINT", "select r, p from PRC_SIMV")


def fillvint_rtp(db: DB):
    """fillvint.gms, after the RVP loop: $IF DEFINED PRC_SIMV RTP(RVP(R,V,P)) $= PRC_SIMV(R,P);"""
    if active(db):
        db.add("RTP", "select r, y, p from RVP where in_PRC_SIMV(r,p)")


def leading(db: DB):
    """ppmain.mod 590: LOOP(T,NO_RVP(R,TT-1,P)$(RTP_CPTYR(R,TT,T,P)$PRC_SIMV(R,P))=YES); NO_RVP(RTP(R,T,P))=NO; RTP(NO_RVP)=YES;
    (NO_RVP holds nothing else by then)"""
    if not active(db):
        return
    T = [y for (y,) in db.q("select y from MILESTONYR order by yv(y)")]
    prev = {T[i]: T[i - 1] for i in range(1, len(T))}
    rows = set()
    for r, tt, t, p in db.q("select r, y, y2, p from RTP_CPTYR where in_PRC_SIMV(r,p) and in_MILESTONYR(y) and in_MILESTONYR(y2)"):
        if tt in prev:
            rows.add((r, prev[tt], p))
    rtp = set(db.q("select r, y, p from RTP"))
    add = sorted(k for k in rows if k not in rtp)
    if add:
        db.x("create or replace temp table t_simv_rtp (r VARCHAR, y VARCHAR, p VARCHAR)")
        db.insert_rows("t_simv_rtp", add)
        db.add("RTP", "select * from t_simv_rtp")
        # (they stay in NO_RVP, and pp_qack.mod takes them out of RTP again: RTP(NO_RVP) = NO)
        db.add("NO_RVP", "select * from t_simv_rtp")


def coef_csv(db: DB):
    """coef_csv.mod."""
    if not active(db):
        return
    q = db.q
    for name, kind, dom in [("COEF_CSV", "par", ["R", "ALLYEAR", "LL", "P", "ALLYEAR"]), ("AFSV", "set", ["R", "T", "P", "S", "BD"])]:
        db.declare(name, kind, dom)
    yv = {y: float(v) for y, v in q("select y, value from YEARVAL")}
    years = {int(v): y for y, v in yv.items()}                    # ALLYEAR by value: LL+k is the year k after LL
    at = lambda v: years.get(int(round(v))) if v == v and abs(v) != INF else None
    T = [y for (y,) in q("select y from MILESTONYR order by yv(y)")]
    val = lambda n: {k[0] if len(k) == 1 else k: v for *k, v in _rows(db, n)}
    LEAD, B, M, D = val("LEAD"), val("B"), val("M"), val("D")
    TLIFE = {(r, y, p): v for r, y, p, v in _rows(db, "NCAP_TLIFE")}
    ILED = {(r, y, p): v for r, y, p, v in _rows(db, "NCAP_ILED")}
    rtp = set(q("select r, y, p from RTP"))
    vara = set(q("select r, y, p from RTP_VARA"))
    cptyr = {}
    for r, v, t, p in q("select r, y, y2, p from RTP_CPTYR"):
        cptyr.setdefault((r, t, p), []).append(v)
    # --- MY_ARRAY(T) = YEARVAL(T)-LEAD(T);
    my_array = {t: yv[t] - LEAD.get(t, 0.0) for t in T}
    # --- OPTION CLEAR=PRC_YMIN;  PRC_SIMV(RP)$RP_UPL(RP,'FX')=NO;
    db.remove("PRC_SIMV", where="in_RP_UPL(r,p,'FX')")
    simv = sorted(set(q("select r, p from PRC_SIMV")))
    ymin, cap = {}, {}
    first_val = (TRIVINT - 0.5) * (TRIVINT + 0.5)
    for t in T:
        # --- LOOP(T(LL), MY_F = YEARVAL(T); Z = MIN(B(T),YEARVAL(T)-FLOOR(LEAD(T)/2));
        my_f = yv[t]
        z = min(B.get(t, 0.0), yv[t] - math.floor(LEAD.get(t, 0.0) / 2))
        # --- PRC_YMIN(PRC_SIMV(R,P))$RTP_VARA(R,T,P) = SMIN(RTP_CPTYR(R,TT,T,P)$(MY_ARRAY(TT)+NCAP_TLIFE(R,TT,P)>Z),MY_ARRAY(TT));
        for r, p in simv:
            if (r, t, p) in vara:
                ys = [my_array.get(tt, 0.0) for tt in cptyr.get((r, t, p), []) if my_array.get(tt, 0.0) + TLIFE.get((r, tt, p), 0.0) > z]
                ymin[(r, p)] = min(ys) if ys else INF
        # --- LOOP(PRC_SIMV(R,P)$RTP_VARA(R,T,P), MY_FYEAR = PRC_YMIN(R,P); IF(MY_FYEAR NE INF, ...
        for r, p in simv:
            if (r, t, p) not in vara:
                continue
            fy = ymin.get((r, p), 0.0)
            if fy == INF:
                continue
            f, zz = fy - 0.5, my_f - 0.5
            # MY_FIL2(TT)= (YEARVAL(TT)-F)*(Z-YEARVAL(TT))$RTP(R,TT,P); Z = SMAX(TT,MY_FIL2(TT));
            fil2 = {tt: ((yv[tt] - f) * (zz - yv[tt]) if (r, tt, p) in rtp else 0.0) for tt in T}
            zmax = max(fil2.values())
            if zmax > first_val:
                zy = min(yv[tt] for tt in T if fil2[tt] == zmax)
                for y, s in ((zy, -1.0), (fy, 1.0)):
                    k = at(y)
                    if k is not None:
                        cap[(r, k, t, p)] = s
            else:
                k = at(fy)
                if k is not None:
                    cap[(r, k, t, p)] = -1.0
    # --- COEF_CAP(R,T,T,P)$(RTP_VARA(R,T,P)$PRC_SIMV(R,P)) = 1;
    for r, p in simv:
        for t in T:
            if (r, t, p) in vara:
                cap[(r, t, t, p)] = 1.0
    # --- COEF_CSV(RTP_CPTYR(R,TT,T,P),TT)$COEF_CAP(R,TT,T,P) = 1;
    csv = {}
    for (r, t, p), vs in cptyr.items():
        for tt in vs:
            if cap.get((r, tt, t, p)):
                csv[(r, tt, t, p, tt)] = 1.0
    psum = {}
    if simv:
        simvs = set(simv)
        # --- LOOP(MIYR_1(LL), Z = LEAD(LL); OPTION FIL < T; FIL(LL-Z) = YES;
        #       COEF_CSV(RTP_CPTYR(R,PASTMILE,T,P),LL-Z)$(PRC_SIMV(R,P)*NCAP_PASTI(R,PASTMILE,P)) = 1);
        #     (OPTION FIL < T inside the LOOP leaves FIL empty in GAMS: FIL holds only the year LL-Z, so YK1 and VTV
        #      below are empty and no simulated vintage is interpolated, in TIMES as here)
        t1 = T[0]
        lag = at(yv[t1] - LEAD.get(t1, 0.0))
        fil = [lag] if lag is not None else []
        pastmile = {y for (y,) in q("select y from PASTMILE")}
        pasti = {(r, y, p) for r, y, p, v in _rows(db, "NCAP_PASTI") if v != 0}
        if lag is not None:
            for (r, t, p), vs in cptyr.items():
                if (r, p) in simvs:
                    for v in vs:
                        if v in pastmile and (r, v, p) in pasti:
                            csv[(r, v, t, p, lag)] = 1.0
        # --- YK1(FIL,V)$((NOT SAMEAS(FIL,V))$FIL(V)) = YES;
        #     VTV(YK1(FIL,V),T)$((YEARVAL(T)-YEARVAL(FIL)-.5)*(YEARVAL(V)-YEARVAL(T)+.5) > 0) = YES;
        modl = {y for (y,) in q("select y from MODLYEAR")}
        yk1 = [(a, b) for a in fil for b in fil if a != b and b in modl]
        vtv = {(a, b, t) for a, b in yk1 for t in T if (yv[t] - yv[a] - .5) * (yv[b] - yv[t] + .5) > 0}
        # --- PASTSUM(RTP(R,T,P))$PRC_SIMV(R,P) = MIN(M(T),FLOOR(MAX(YEARVAL(T)-(LEAD(T)-1)/2,
        #        B(T)+MAX(NCAP_ILED(RTP),(D(T)+NCAP_ILED(RTP)-NCAP_TLIFE(RTP))/2))+0.5));
        for r, t, p in rtp:
            if (r, p) in simvs and t in yv and t in my_array:
                il, tl = ILED.get((r, t, p), 0.0), TLIFE.get((r, t, p), 0.0)
                v = min(M.get(t, 0.0), math.floor(max(yv[t] - (LEAD.get(t, 0.0) - 1) / 2,
                                                       B.get(t, 0.0) + max(il, (D.get(t, 0.0) + il - tl) / 2)) + 0.5))
                if v != 0:
                    psum[(r, t, p)] = v
        # --- LOOP(YK1(LL,FIL), Z = YEARVAL(LL); F = YEARVAL(FIL);
        #       COEF_CSV(RTP_CPTYR(R,TT,T,P),FIL)$((COEF_CAP(R,LL,T,P)*COEF_CAP(R,FIL,T,P) < 0)$VTV(LL,FIL,TT)) = (PASTSUM(R,TT,P)-Z)/(F-Z));
        for a, b in yk1:
            z, f = yv[a], yv[b]
            for (r, t, p), vs in cptyr.items():
                if cap.get((r, a, t, p), 0.0) * cap.get((r, b, t, p), 0.0) >= 0:
                    continue
                for tt in vs:
                    if (a, b, tt) in vtv:
                        x = (psum.get((r, tt, p), 0.0) - z) / (f - z)
                        if x != 0:
                            csv[(r, tt, t, p, b)] = x
                        else:
                            csv.pop((r, tt, t, p, b), None)
    # --- COEF_CSV(RTP_CPTYR(R,V,T,P),FIL)$PRC_SIMV(R,P) = COEF_CSV(R,V,T,P,FIL)*COEF_CPT(R,V,T,P);
    cpt = {(r, v, t, p): x for r, v, t, p, x in _rows(db, "COEF_CPT")}
    simvs = set(simv)
    for k in list(csv):
        r, v, t, p, f = k
        if (r, p) in simvs and v in cptyr_v(cptyr, r, t, p):
            x = csv[k] * cpt.get((r, v, t, p), 0.0)
            if x != 0:
                csv[k] = x
            else:
                del csv[k]
    _par(db, "COEF_CSV", csv)
    _par(db, "PRC_YMIN", {k: v for k, v in ymin.items()})
    # --- OPTION COEF_CAP < COEF_CSV; RTP_VINTYR(R,V,T,P)$PRC_SIMV(R,P) = NO; RTP_VINTYR(R,V,T,P)$COEF_CAP(R,V,T,P) = YES;
    db.remove("RTP_VINTYR", where="in_PRC_SIMV(r,p)")
    vint = sorted({(r, v, t, p) for (r, v, t, p, f) in csv})
    if vint:
        db.x("create or replace temp table t_simv_vy (r VARCHAR, y VARCHAR, y2 VARCHAR, p VARCHAR)")
        db.insert_rows("t_simv_vy", vint)
        db.add("RTP_VINTYR", "select * from t_simv_vy")
    # --- AFSV(AFS(R,T,P,S,BD))$=PRC_SIMV(R,P); AFS(AFSV)=NO;
    db.assign("AFSV", "select r, y, p, s, l from AFS where in_PRC_SIMV(r,p)")
    db.remove("AFS", where="in_PRC_SIMV(r,p)")


def cptyr_v(cptyr, r, t, p):
    return cptyr.get((r, t, p), ())
