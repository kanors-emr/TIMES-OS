# SPDX-License-Identifier: GPL-3.0-or-later
"""coefmain.mod: capacity transfer, availability and flow transformation coefficients, shapes.

coef_cpt.mod, coef_nio.mod, coef_ptr.mod, coef_shp.mod; the cost coefficients of coef_obj.mod and
coef_alt.lin are in costs.py."""
import math, time
from ..controls import unsupported
from ..engine import DB
from .common import require_empty
from .costs import coef_alt, coef_obj
from .. import side, kernels


def coefmain(db: DB):
    # --- $IFI NOT %STAGES%==YES SOW(ALLSOW)=DIAG(ALLSOW,'1'); SW_T(T,ALLSOW)=SOW(ALLSOW);
    if not db.ctl.get("STAGES"):
        db.assign("SOW", "select '1' as w")
        db.assign("SW_T", "select y, '1' as w from MILESTONYR")
    # coef_ptr shares no table and no Python state with the other parts of coefmain: with TIMESPP_PAR_STAGES=1 it runs
    # beside them on a connection of its own (side.py). Its scratch tables (t_test, t_grp, t_tes2, n_tmp) are temp
    # tables, private to that connection.
    beside = side.enabled()
    if beside and kernels.mode("coef_ptr") != "off":
        kernels.start()                     # Julia starts in this thread, before coef_ptr's thread calls it
    join = side.beside(db, coef_ptr) if beside else None
    coef_cpt(db)
    coef_nio(db)
    if join is None:
        coef_ptr(db)
    coef_obj(db)
    coef_alt(db)
    coef_shp(db)
    if join is not None:
        join()


# ---------------------------------------------------------------------------
def coef_nio(db: DB):
    """coef_nio.mod : commodity flows tied to investment (NCAP_ICOM -> COEF_ICOM) and decommissioning (NCAP_OCOM ->
    COEF_OCOM), per unit of new capacity of vintage v, in period t, and of capacity retired early (RCAP_OCAP ->
    COEF_RCOM).  Flows tied to installed capacity (NCAP_COM) need no coefficients here."""
    q = db.q
    # --- NCAP_OCOM(RTP,C)$((NOT NCAP_OCOM(RTP,C))$RCAP_OCAP(RTP,C)) = 1;      (NOT EPS is false: an EPS stays)
    if db.card("RCAP_OCAP"):
        db.put("NCAP_OCOM", "select r, y, p, c, 1 as value from RCAP_OCAP where in_RTP(r,y,p) and not in_NCAP_OCOM(r,y,p,c)")
    # --- RPC_CAPFLO(R,V,P,C)$(NOT RTP(R,V,P)) = 0;
    db.remove("RPC_CAPFLO", where="in_MODLYEAR(y) and in_REG(r) and not in_RTP(r,y,p)")
    capflo = q("select r, y, p, c from RPC_CAPFLO")
    icom = {(r, y, p, c): v for r, y, p, c, v in q("select r, y, p, c, value from NCAP_ICOM")}
    ocom = {(r, y, p, c): v for r, y, p, c, v in q("select r, y, p, c, value from NCAP_OCOM")}
    if capflo and (icom or ocom):
        p3 = lambda n: {(r, y, p): v for r, y, p, v in q(f"select r, y, p, value from {n}")}
        RPTI, ILED, CILED, DLAG, TLIFE, DLIFE = (p3(n) for n in ("COEF_RPTI", "NCAP_ILED", "COEF_ILED", "NCAP_DLAG", "NCAP_TLIFE", "NCAP_DLIFE"))
        CLED = {(r, y, p, c): v for r, y, p, c, v in q("select r, y, p, c, value from NCAP_CLED")}
        B = {y: v for y, v in q("select y, value from B")}
        E = {y: v for y, v in q("select y, value from E")}
        FPD = {y: v for y, v in q("select y, value from FPD")}
        D = {y: v for y, v in q("select y, value from D")}
        T = sorted((y for (y,) in q("select y from MILESTONYR")), key=int)
        Tset = set(T)
        VNT = {}
        for v, t in q("select y, y2 from VNT order by yv(y2)"):
            VNT.setdefault(v, []).append(t)
        BV = lambda v: B.get(v, float(int(v)))           # B(V): the first year of a period, the year itself otherwise
        miyr_v1 = db.s["MIYR_V1"]
        ci, co = {}, {}
        # an input of EPS (an entry of 0) gives EPS where its factor (fac) is not 0: kept on record as a zero, as in GAMS
        eps = set()
        mark = lambda key, src, factor: (src == 0 and factor != 0) and eps.add(key)
        # --- FIL(V) = YEARVAL(V) GE MIYR_V1;
        #     LOOP(RPC_CAPFLO(R,FIL(V),P,C)$NCAP_ICOM(R,V,P,C), DFUNC = COEF_RPTI(R,V,P);
        #       MY_F = NCAP_ILED(R,V,P); F = COEF_ILED(R,V,P); CNT = ABS(NCAP_CLED(R,V,P,C));
        #       Z = B(V)+MAX(1$(CNT$MY_F=0),MY_F); F = Z-MAX(1,MIN(CNT,F));
        #       IF(DFUNC > 1, COEF_ICOM(R,T(V),T,P,C) = (DFUNC * NCAP_ICOM(R,V,P,C) / FPD(T))
        #       ELSE LOOP(T$((E(T) >= F) * (B(T) < Z)), COEF_ICOM(R,V,T,P,C) =
        #              MAX(0,((MIN(Z-1,E(T))-MAX(F,B(T)) + 1) / FPD(T))) * NCAP_ICOM(R,V,P,C) / (Z-F)));
        for (r, v, p, c) in capflo:
            k = (r, v, p, c)
            if k not in icom or int(v) < miyr_v1:
                continue
            dfunc, my_f, f, cnt = RPTI.get((r, v, p), 0.0), ILED.get((r, v, p), 0.0), CILED.get((r, v, p), 0.0), abs(CLED.get(k, 0.0))
            # (CNT$MY_F: NCAP_ILED given as EPS is a record, and so true here; its value reads 0.0)
            z = BV(v) + max(1.0 if (cnt if (r, v, p) in ILED else 0.0) == 0 else 0.0, my_f)
            f = z - max(1.0, min(cnt, f))
            if dfunc > 1:
                # COEF_ICOM(R,T(V),T,P,C): inside the loop over V, T(V) makes the second T the element V itself - the
                # consumption is in the period of the investment only (GAMS gives t = v only)
                if v in Tset:
                    ci[(r, v, v, p, c)] = dfunc * icom[k] / FPD[v]
                    mark((r, v, v, p, c), icom[k], dfunc / FPD[v])
            else:
                for t in T:
                    if E[t] >= f and B[t] < z:
                        fac = max(0.0, (min(z - 1, E[t]) - max(f, B[t]) + 1) / FPD[t]) / (z - f)
                        ci[(r, v, t, p, c)] = max(0.0, (min(z - 1, E[t]) - max(f, B[t]) + 1) / FPD[t]) * icom[k] / (z - f)
                        mark((r, v, t, p, c), icom[k], fac)
        # --- FIL2(T) = E(T)+(1+MAX(1,D(T+1))-B(T)-E(T))/2;
        fil2 = {t: E[t] + (1 + max(1.0, D.get(T[i + 1], 0.0) if i + 1 < len(T) else 1.0) - B[t] - E[t]) / 2 for i, t in enumerate(T)}
        # --- LOOP(RPC_CAPFLO(R,V,P,C)$NCAP_OCOM(R,V,P,C),
        #       F = NCAP_ILED(R,V,P)+NCAP_DLAG(R,V,P); MY_F = NCAP_TLIFE(R,V,P); DFUNC = COEF_RPTI(R,V,P);
        #       Z = B(V)+F+DFUNC*MY_F;
        #       Z = MAX(1,NCAP_DLIFE(R,V,P),SUM(VNT(V,T)$((Z>=B(T))*(E(T)+1>Z)),(E(T)-Z+1)/(1-(Z-(B(T)+E(T))/2)/FIL2(T))));
        #       IF(DFUNC > 1, FOR(CNT = 1 TO CEIL(DFUNC), COEF_OCOM(R,VNT(V,T),P,C) = COEF_OCOM(R,V,T,P,C) + MIN(1,DFUNC-CNT+1) *
        #            MAX(0,(MIN(B(V)+F+(CNT*MY_F)+Z,E(T)+1) - MAX(B(V)+F+(CNT*MY_F),B(T))) / FPD(T)) * (NCAP_OCOM(R,V,P,C) / Z))
        #       ELSE MY_F = B(V)+F+MY_F; COEF_OCOM(R,V,T,P,C)$(E(T)+1 > MY_F) =
        #            MAX(0,(MIN(MY_F+Z,E(T)+1) - MAX(MY_F,B(T))) / FPD(T)) * (NCAP_OCOM(R,V,P,C) / Z)));
        for (r, v, p, c) in capflo:
            k = (r, v, p, c)
            if k not in ocom:
                continue
            f = ILED.get((r, v, p), 0.0) + DLAG.get((r, v, p), 0.0)
            my_f, dfunc = TLIFE.get((r, v, p), 0.0), RPTI.get((r, v, p), 0.0)
            z = BV(v) + f + dfunc * my_f
            adj = sum((E[t] - z + 1) / (1 - (z - (B[t] + E[t]) / 2) / fil2[t]) for t in VNT.get(v, []) if z >= B[t] and E[t] + 1 > z)
            z = max(1.0, DLIFE.get((r, v, p), 0.0), adj)
            if dfunc > 1:
                for n in range(1, math.ceil(dfunc) + 1):
                    for t in VNT.get(v, []):
                        fac = min(1.0, dfunc - n + 1) * max(0.0, (min(BV(v) + f + n * my_f + z, E[t] + 1) - max(BV(v) + f + n * my_f, B[t])) / FPD[t]) / z
                        co[(r, v, t, p, c)] = co.get((r, v, t, p, c), 0.0) + min(1.0, dfunc - n + 1) * max(0.0, (min(BV(v) + f + n * my_f + z, E[t] + 1) - max(BV(v) + f + n * my_f, B[t])) / FPD[t]) * (ocom[k] / z)
                        mark((r, v, t, p, c), ocom[k], fac)
            else:
                start = BV(v) + f + my_f
                for t in T:
                    if E[t] + 1 > start:
                        fac = max(0.0, (min(start + z, E[t] + 1) - max(start, B[t])) / FPD[t]) / z
                        co[(r, v, t, p, c)] = max(0.0, (min(start + z, E[t] + 1) - max(start, B[t])) / FPD[t]) * (ocom[k] / z)
                        mark((r, v, t, p, c), ocom[k], fac)
        # --- COEF_OCOM$((COEF_ICOM LT 0)$COEF_ICOM) = COEF_OCOM-COEF_ICOM;  COEF_ICOM$((COEF_ICOM LT 0)$COEF_ICOM) = 0;
        #     COEF_ICOM$((COEF_OCOM LT 0)$COEF_OCOM) = COEF_ICOM-COEF_OCOM;  COEF_OCOM$((COEF_OCOM LT 0)$COEF_OCOM) = 0;
        for key in [k for k, x in ci.items() if x < 0]:
            co[key] = co.get(key, 0.0) - ci[key]; ci[key] = 0.0
        for key in [k for k, x in co.items() if x < 0]:
            ci[key] = ci.get(key, 0.0) - co[key]; co[key] = 0.0
        db.insert_rows("COEF_ICOM", [(*k, x) for k, x in ci.items() if x != 0 or k in eps])
        db.insert_rows("COEF_OCOM", [(*k, x) for k, x in co.items() if x != 0 or k in eps])
    # --- COEF_RCOM(RTP_CPTYR(R,V,T,P),C)$RCAP_OCAP(R,V,P,C) = COEF_CPT(R,V,T,P) * NCAP_OCOM(R,V,P,C) / FPD(T);
    if db.card("RCAP_OCAP"):
        db.put("COEF_RCOM", """select c.r, c.y, c.y2, c.p, o.c, v_COEF_CPT(c.r,c.y,c.y2,c.p) * v_NCAP_OCOM(c.r,c.y,c.p,o.c) / v_FPD(c.y2) as value
                               from RTP_CPTYR c join RCAP_OCAP o on o.r=c.r and o.y=c.y and o.p=c.p""")
    # --- NCAP_CLAG(RTP,C,IO)$((NOT NCAP_ICOM(RTP,C))$NCAP_COM(RTP,C,IO)) $= NCAP_CLED(RTP,C);
    #     ($= copies an EPS: a lead time given as 0 is an EPS lag, and no COEF_CIO)
    db.put("NCAP_CLAG", """select m.r, m.y, m.p, m.c, m.io, l.value from NCAP_COM m join NCAP_CLED l on l.r=m.r and l.y=m.y and l.p=m.p and l.c=m.c
                           where in_RTP(m.r,m.y,m.p) and not in_NCAP_ICOM(m.r,m.y,m.p,m.c)""", zero="eps")
    # --- NCAP_CLED(R,V,P,C)$(NOT NCAP_ICOM(R,V,P,C)) = 0;
    db.zap("NCAP_CLED", "not in_NCAP_ICOM(r,y,p,c)")


# ---------------------------------------------------------------------------
def shape_average(db: DB, pointer, multi=None):
    """pp_shapr.mod: the average of a SHAPE curve over the years of each period in which a vintage operates.

    pointer: (r, v, p, bd) -> curve index.  A process and vintage takes part when one of its pointers is at least 1.5
    (RTP_ISHPR); its other bounds then use curve 1.  A pointer is dropped when the plant does not outlast its period.
    multi: (r, v, p) -> index of a MULTI curve (%5: NCAP_AFM, NCAP_AFSM), a vintage with one at least 1.5 takes part
    too, and the factor is MULTI(JJ,T) times the average (curve 1 is 1 in every year, ppmain.mod 637).
    -> {(r, v, p, bd, t): factor}   (0 = EPS: the vintage does not operate in the period)"""
    from .common import rnd
    q = db.q
    B = {y: v for y, v in q("select y, value from B")}
    E = {y: v for y, v in q("select y, value from E")}
    D = {y: v for y, v in q("select y, value from D")}
    T = [y for (y,) in q("select y from MILESTONYR")]
    shape = {(int(j), int(a)): v for j, a, v in q("select j, age, value from SHAPE")}
    eoh = {int(y) for (y,) in q("select y from EOHYEARS")}
    years = {t: [y for y in range(int(B[t]), int(E[t]) + 1) if y in eoh] for t in T}
    multi = multi or {}
    ishpr = {k[:3] for k, v in pointer.items() if v >= 1.5} | {k for k, v in multi.items() if v >= 1.5}
    if not ishpr:
        return {}
    iled = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from NCAP_ILED")}
    tlife = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from NCAP_TLIFE")}
    mcurve = {(int(j), y): v for j, y, v in q("select j, y, value from MULTI")} if multi else {}
    out = {}
    for (r, v, p) in ishpr:
        jj = 1 + max(0, rnd(multi.get((r, v, p), 0.0)) - 1)
        # --- FIL2(V) = B(V)-YEARVAL(V);  PASTSUM(RTP_ISHPR(R,V,P)) = FIL2(V)+NCAP_ILED(R,V,P)+NCAP_TLIFE(R,V,P)-1;
        fil2 = B[v] - int(v)
        il, tl = iled.get((r, v, p), 0.0), tlife.get((r, v, p), 0.0)
        pastsum = fil2 + il + tl - 1
        start, end = int(v) + rnd(fil2 + il), int(v) + rnd(pastsum)
        for bd in ("LO", "UP", "FX"):
            x = pointer.get((r, v, p, bd), 0.0)
            # --- %1X(RTP_ISHPR(R,V,P),BD)$(PASTSUM(R,V,P)-FIL2(V)+1 < D(V)) = 0;
            if pastsum - fil2 + 1 < D[v]:
                x = 0.0
            j = 1 + max(0, rnd(x) - 1)
            for t in T:
                # --- SUM(PERIODYR(T,EOHYEARS)$(YEARVAL(EOHYEARS) LE MAX(B(T),YEARVAL(YEAR))),
                #        SHAPE(J,AGE+(MIN(YEARVAL(EOHYEARS),YEARVAL(YEAR))-YEARVAL(LL)))) / (MAX(1,MIN(E(T),YEARVAL(YEAR))-MAX(B(T),YEARVAL(LL))+1))
                tot = sum(shape.get((j, 1 + min(y, end) - start), 0.0) for y in years[t] if y <= max(B[t], end))
                if multi:
                    # --- EPS+MULTI(JJ,T)*SUM(..)/(..)
                    tot = mcurve.get((jj, t), 0.0) * tot
                out[r, v, p, bd, t] = tot / max(1, min(E[t], end) - max(B[t], start) + 1)
    return out


def _shaped(db: DB, fac, select):
    """COEF_AF = the availabilities of `select` (r, y, y2, p, s, l, value) times their SHAPE average fac[r, v, p, bd, t]
    (shape_average), for the rows that have one; with EPS rows. The factors go to DuckDB as a frame and the product is
    made there: the same products as multiplying the fetched rows in Python, without fetching them (3 s of
    coefmain on a large model)."""
    if not fac:
        return
    import pandas as pd
    db.con.register("fac_", pd.DataFrame([(*k, f) for k, f in fac.items()], columns=["r", "y", "p", "l", "y2", "f"]))
    db.put("COEF_AF", f"""select q.r, q.y, q.y2, q.p, q.s, q.l, q.value * f.f as value from ({select}) q
                         join fac_ f on f.r=q.r and f.y=q.y and f.p=q.p and f.l=q.l and f.y2=q.y2""", zero="eps")
    db.con.unregister("fac_")


# ---------------------------------------------------------------------------
def coef_cpt(db: DB):
    # --- LOOP(PERIODYR(T,V)$((NOT PHYR(V))$VNT(V,T)), B(V) = B(T); E(V) = E(T); M(V) = M(T); D(V) = D(T));
    db.tmp("t_pv", """select p.y as t, p.y2 as v from PERIODYR p where in_MILESTONYR(p.y) and in_MODLYEAR(p.y2)
                      and in_VNT(p.y2,p.y) and p.y <> p.y2 and not in_PHYR(p.y2)""")
    for n in ("B", "E", "M", "D"):
        db.put(n, f"select v as y, v_{n}(t) as value from t_pv")
    if db.ctl["CTST"] == "":
        # --- PASTSUM(RTP(R,V,P))$PRC_CAP(R,P) = B(V)+NCAP_ILED(RTP)+COEF_RPTI(RTP)*NCAP_TLIFE(RTP);
        #     COEF_CPT(RTP_CPTYR(R,V,T,P))$PASTSUM(R,V,P) = MAX(0,(MIN(E(T)+1,PASTSUM(R,V,P))-MAX(B(V)+NCAP_ILED(R,V,P),B(T)))/D(T));
        db.put("COEF_CPT", """
            select c.r, c.y, c.y2, c.p,
                   greatest(0, (least(v_E(c.y2)+1, v_B(c.y)+v_NCAP_ILED(c.r,c.y,c.p)+v_COEF_RPTI(c.r,c.y,c.p)*v_NCAP_TLIFE(c.r,c.y,c.p))
                                - greatest(v_B(c.y)+v_NCAP_ILED(c.r,c.y,c.p), v_B(c.y2))) / v_D(c.y2)) as value
            from RTP_CPTYR c where in_PRC_CAP(c.r,c.p) and in_RTP(c.r,c.y,c.p)""")
    # --- NCAP_AFX(R,LL--ORD(LL),P) $= NCAP_AFM(R,LL,P);
    #     (LL--ORD(LL) is '0', the last element of ALLYEAR: the last pointer in year order, '0' included, marks the
    #      process for the availabilities by vintage below)
    db.put("NCAP_AFX", """select r, '0' as y, p, arg_max(value, case when y = '0' then 1e9 else yv(y) end) as value
                          from NCAP_AFM group by r, p""", zero="eps")
    bd = "l in ('LO','UP','FX')"
    # --- MY_TS(S)=NOT ANNUAL(S);
    #     NCAP_AF(RTP(R,V,P),MY_TS(S),BD)$(PRC_TS(R,P,S)$NCAP_AFS(RTP,S,BD)) = MIN(NCAP_AF(RTP,S,BD)+INF$(NOT NCAP_AF(RTP,S,BD)),NCAP_AFS(RTP,S,BD));
    db.put("NCAP_AF", f"""select r, y, p, s, l, least(case when in_NCAP_AF(r,y,p,s,l) then v_NCAP_AF(r,y,p,s,l) else 'inf'::double end, value) as value
                          from NCAP_AFS where s <> 'ANNUAL' and {bd} and in_RTP(r,y,p) and in_PRC_TS(r,p,s)""", zero="eps")
    # --- NCAP_AF(RTP(R,V,P),S,BDNEQ)$(PRC_TS(R,P,S)$NCAP_AFS(RTP,S,'FX')) = 0;
    db.zap("NCAP_AF", "l in ('LO','UP') and in_RTP(r,y,p) and in_PRC_TS(r,p,s) and in_NCAP_AFS(r,y,p,s,'FX')")
    # --- NCAP_AFS(RTP(R,V,P),MY_TS(S),BD)$(PRC_TS(R,P,S) OR (NOT RPS_PRCTS(R,P,S))) = 0;
    db.zap("NCAP_AFS", f"s <> 'ANNUAL' and {bd} and in_RTP(r,y,p) and (in_PRC_TS(r,p,s) or not in_RPS_PRCTS(r,p,s))")
    # --- OPTION TRACKP < NCAP_AFX;  TRACKP(RP)$(NOT PRC_CAP(RP)) = NO;  TRACKP(RP)$RP_UPL(RP,'FX') = NO;  TRACKP(PRC_CAP(PRC_VINT)) = YES;
    #     (availabilities by vintage: vintaged processes, and those with a shape unless they are dispatchable)
    db.tmp("t_afv", """select r, p from PRC_CAP k where in_PRC_VINT(r,p)
                          or (exists(select 1 from NCAP_AFX x where x.r=k.r and x.p=k.p) and not in_RP_UPL(r,p,'FX'))""")
    # --- NCAP_AFBX(RTP(R,V,P),BD)$(RP_AFB(R,P,BD)>0) $= NCAP_AFX(RTP);
    #     pp_shapr NCAP_AF: COEF_AF(RTP_CPTYR(R,V,T,P),S,BD)$(TRACKP(R,P)*RP_AFB(R,P,BD)*PRC_TS(R,P,S)) = NCAP_AF(R,V,P,S,BD) [* average SHAPE]
    db.put("COEF_AF", """select c.r, c.y, c.y2, c.p, a.s, a.l, a.value from RTP_CPTYR c join NCAP_AF a on a.r=c.r and a.y=c.y and a.p=c.p
                         where exists(select 1 from t_afv v where v.r=c.r and v.p=c.p) and in_RTP(c.r,c.y,c.p)
                           and in_RP_AFB(c.r,c.p,a.l) and in_PRC_TS(c.r,c.p,a.s)""", zero="eps")
    if db.card("NCAP_AFX"):
        # --- pp_shapr NCAP_AF ... NCAP_AFM(R,V,P) B: the AF pointers NCAP_AFBX and the MULTI pointer NCAP_AFM
        fac = shape_average(db, {(r, y, p, l): v for r, y, p, l, v in db.q(
            """select x.r, x.y, x.p, b.l, x.value from NCAP_AFX x join RP_AFB b on b.r=x.r and b.p=x.p
               where b.value > 0 and x.value <> 0 and in_RTP(x.r,x.y,x.p)""")},
            {(r, y, p): v for r, y, p, v in db.q("select r, y, p, value from NCAP_AFM where in_RTP(r,y,p) and value <> 0")})
        _shaped(db, fac, """select c.r, c.y, c.y2, c.p, a.s, a.l, a.value from RTP_CPTYR c join NCAP_AF a on a.r=c.r and a.y=c.y and a.p=c.p
               where exists(select 1 from t_afv v where v.r=c.r and v.p=c.p) and in_RTP(c.r,c.y,c.p)
                 and in_RP_AFB(c.r,c.p,a.l) and in_PRC_TS(c.r,c.p,a.s)""")
    # --- TRACKP(PRC_CAP(R,P)) = (NOT TRACKP(R,P));
    #     COEF_AF(RTP_CPTYR(R,V,T,P),S,BD)$(PRC_TS(R,P,S)$TRACKP(R,P)) $= NCAP_AF(R,T,P,S,BD);                              not by vintage
    db.put("COEF_AF", """select c.r, c.y, c.y2, c.p, a.s, a.l, a.value from RTP_CPTYR c join NCAP_AF a on a.r=c.r and a.y=c.y2 and a.p=c.p
                         where in_PRC_CAP(c.r,c.p) and not exists(select 1 from t_afv v where v.r=c.r and v.p=c.p)
                           and in_PRC_TS(c.r,c.p,a.s)""", zero="eps")
    # --- COEF_AF(RTP_CPTYR(R,V,T,P),ANNUAL,BD)$PRC_CAP(R,P) $= NCAP_AFA(R,T,P,BD);
    db.put("COEF_AF", """select c.r, c.y, c.y2, c.p, 'ANNUAL' as s, a.l, a.value from RTP_CPTYR c
                         join NCAP_AFA a on a.r=c.r and a.y=c.y2 and a.p=c.p where in_PRC_CAP(c.r,c.p)""", zero="eps")
    # --- OPTION RP_PRC < NCAP_AFSM; NCAP_AFSM(R,V,P)$(NOT RP_PRC(R,P)) $= NCAP_AFM(R,V,P);
    #     NCAP_AFSX(RTP,BD)$NCAP_AFSM(RTP) = NCAP_AFSX(RTP,BD)+EPS;
    if db.card("NCAP_AFM") or db.card("NCAP_AFSM"):
        db.put("NCAP_AFSM", """select r, y, p, value from NCAP_AFM a
                               where not exists(select 1 from NCAP_AFSM m where m.r=a.r and m.p=a.p)""", zero="eps")
        db.put("NCAP_AFSX", """select k.r, k.y, k.p, b.l, v_NCAP_AFSX(k.r,k.y,k.p,b.l) as value from NCAP_AFSM k,
                               (values ('LO'),('UP'),('FX')) b(l) where in_RTP(k.r,k.y,k.p)""", zero="eps")
    # --- RTPS_BD(RTP(R,V,P),S,BD)$((PRC_VINT(R,P)+ANNUAL(S)+YES$NCAP_AFSX(RTP,BD))$NCAP_AFS(RTP,S,BD)) = YES;
    #     (a seasonal availability is by vintage on a vintaged process, at ANNUAL, or with a shape index of its own)
    db.tmp("t_bd", f"""select r, y, p, s, l from NCAP_AFS a where {bd} and in_RTP(r,y,p) and in_MODLYEAR(y)
                       and (in_PRC_VINT(r,p) or s = 'ANNUAL' or in_NCAP_AFSX(r,y,p,l))""")
    # --- OPTION RP_PRC<NCAP_AFSX; NCAP_AFSX(R,V,P,BD)$SUM(RTPS_BD(R,V,P,S,BD),1) $= NCAP_AFX(R,V,P)$(NOT RP_PRC(R,P));
    #     (a process without NCAP_AFSX takes the age shape of NCAP_AF for these; RP_PRC keeps the processes with one)
    db.assign("RP_PRC", "select distinct r, p from NCAP_AFSX")
    db.put("NCAP_AFSX", """select distinct b.r, b.y, b.p, b.l, x.value from t_bd b join NCAP_AFX x on x.r=b.r and x.y=b.y and x.p=b.p
                           where not exists(select 1 from NCAP_AFSX z where z.r=b.r and z.p=b.p)""", zero="eps")
    # --- pp_shapr NCAP_AFS: COEF_AF(RTP_CPTYR(R,V,T,P),S,BD)$RTPS_BD(R,V,P,S,BD) = NCAP_AFS(R,V,P,S,BD) [* average SHAPE];   vintaged
    db.put("COEF_AF", """select c.r, c.y, c.y2, c.p, b.s, b.l, v_NCAP_AFS(c.r,c.y,c.p,b.s,b.l) as value
                         from RTP_CPTYR c join t_bd b on b.r=c.r and b.y=c.y and b.p=c.p""", zero="eps")
    if db.card("NCAP_AFSX"):
        # --- pp_shapr NCAP_AFS ... NCAP_AFSM(R,V,P): the MULTI pointer NCAP_AFSM
        fac = shape_average(db, {(r, y, p, l): v for r, y, p, l, v in db.q(
            "select r, y, p, l, value from NCAP_AFSX where in_RTP(r,y,p) and value <> 0")},
            {(r, y, p): v for r, y, p, v in db.q("select r, y, p, value from NCAP_AFSM where in_RTP(r,y,p) and value <> 0")})
        _shaped(db, fac, """select c.r, c.y, c.y2, c.p, b.s, b.l, v_NCAP_AFS(c.r,c.y,c.p,b.s,b.l) as value
               from RTP_CPTYR c join t_bd b on b.r=c.r and b.y=c.y and b.p=c.p""")
    # --- COEF_AF(RTP_CPTYR(R,V,T,P),S,BD)$(NOT RTPS_BD(R,V,P,S,BD)) $= NCAP_AFS(R,T,P,S,BD)$PRC_CAP(R,P);
    db.put("COEF_AF", f"""select c.r, c.y, c.y2, c.p, a.s, a.l, a.value from RTP_CPTYR c join NCAP_AFS a on a.r=c.r and a.y=c.y2 and a.p=c.p
                          where in_PRC_CAP(c.r,c.p) and a.{bd} and in_MODLYEAR(c.y)
                            and not exists(select 1 from t_bd b where b.r=c.r and b.y=c.y and b.p=c.p and b.s=a.s and b.l=a.l)""", zero="eps")
    # --- COEF_AF(RTP_CPTYR(R,V,T,P),ANNUAL,BDNEQ)$NCAP_AFA(R,T,P,'FX') = 0;
    db.zap("COEF_AF", "s='ANNUAL' and l in ('LO','UP') and in_RTP_CPTYR(r,y,y2,p) and in_NCAP_AFA(r,y2,p,'FX')")


# ---------------------------------------------------------------------------
def coef_ptr(db: DB):
    """COEF_PTRAN from FLO_FUNC / FLO_SUM. With TIMESPP_KERNELS=coef_ptr the Julia kernel (jlkernels/src/coef_ptr.jl)
    computes the same tables; the SQL below is its reference."""
    if kernels.mode("coef_ptr") == "off":
        return _coef_ptr(db)
    kernels.run("coef_ptr", db, ["COEF_PTRAN", "RPCC_FFUNC", "PRC_CG"], lambda: _coef_ptr(db),
                lambda: _coef_ptr_kernel(db))


# the tables coef_ptr reads, with their columns in the order the kernel takes them (value: the table's values too)
_PTR_IN = [("FLO_SUM", True), ("FLO_FUNC", True), ("RPC", False), ("RTP", False), ("MODLYEAR", False), ("COM", False),
           ("COM_GMAP", False), ("PRC_TSL", False), ("TS_GROUP", False), ("TS_MAP", False), ("RPCS_VAR", False),
           ("RPCC_FFUNC", False), ("PRC_CG", False), ("RC", False)]


def _coef_ptr_kernel(db: DB):
    """coef_ptr in Julia: the same COEF_PTRAN, RPCC_FFUNC and PRC_CG as _coef_ptr, to the bit."""
    import numpy as np
    K = "coef_ptr"
    if db.card("COEF_PTRAN"):
        raise kernels.Decline("COEF_PTRAN has records before coef_ptr")
    if db.card("KEEP_FLOF") or db.card("RPCG_PTRAN"):
        raise kernels.Decline("KEEP_FLOF / RPCG_PTRAN given (the reference stops the run)")
    if db.q1("select count(*) from FLO_SUM where value is null") or db.q1("select count(*) from FLO_FUNC where value is null"):
        raise kernels.Decline("a NULL value")
    cols = []
    for name, val in _PTR_IN:
        c = db.cols(name)
        r = kernels.to_julia(db, K, name, c, "f.value" if val else "")
        if c and len(r["c0"]) != db.card(name):
            raise kernels.Decline(f"a NULL label in {name}")
        cols += [np.asarray(r[f"c{i}"], np.int32) for i in range(len(c))]
        if val:
            cols.append(np.asarray(r["value"], np.float64))
    # the rank of every label in DuckDB's VARCHAR order (the sum over the timeslices is `order by g.s`)
    t = time.perf_counter()
    rank = np.zeros(kernels.labels(db).n, np.int32)
    rk = db.con.execute("select code, cast(row_number() over (order by label) as INTEGER) from __klab").fetchnumpy()
    rank[np.asarray(rk["code"])] = np.asarray(rk[list(rk)[1]], np.int32)
    kernels.tally(K, "duckdb -> julia", time.perf_counter() - t)
    out = kernels.call(K, cols + [rank])
    # --- the two puts into the empty COEF_PTRAN (the first without zeros, the second with its EPS rows: the kernel
    #     made that choice), RPCC_FFUNC as the statement leaves it, PRC_CG's new records
    t = time.perf_counter()
    pc = ["r", "y", "p", "cg", "c", "cg2", "s"]
    if len(out[7]):
        rel = kernels.from_julia(db, "u_", pc, out[:7], {"value": out[7]})
        db.x(f'insert into COEF_PTRAN ({", ".join(pc)}, value) select {", ".join(pc)}, value from {rel} u_')
        db.con.unregister("u_")
    db.x("delete from RPCC_FFUNC")
    if len(out[8]):
        rel = kernels.from_julia(db, "u_", ["r", "p", "cg", "cg2"], out[8:12])
        db.x(f"insert into RPCC_FFUNC (r, p, cg, cg2) select r, p, cg, cg2 from {rel} u_")
        db.con.unregister("u_")
    if len(out[12]):
        rel = kernels.from_julia(db, "u_", ["r", "p", "cg"], out[12:15])
        db.x(f"insert into PRC_CG (r, p, cg) select r, p, cg from {rel} u_")
        db.con.unregister("u_")
    kernels.tally(K, "julia -> duckdb", time.perf_counter() - t, len(out[7]) + len(out[8]) + len(out[12]))


def _coef_ptr(db: DB):
    was_empty = db._empty("COEF_PTRAN")
    # --- OPTION CGTEST <= FLO_SUM; CGTEST(R,V,P,COM_GRP,C,CG)$(NOT RPC(R,P,C)) = NO;
    db.tmp("t_test", "select distinct r, y, p, cg, c, cg2 from FLO_SUM where in_RPC(r,p,c)")
    # --- LOOP((CGTEST(R,V,P,COM_GRP,C,CG),S)$FLO_FUNC(R,V,P,CG,COM_GRP,S),CG_GRP(R,P,COM_GRP,CG) = YES);
    #     CGTES2(RTP(R,V,P),COM_GRP,C,CG)$((COM_GMAP(R,COM_GRP,C)*RPC(R,P,C))$CG_GRP(R,P,COM_GRP,CG)) = YES;
    db.tmp("t_grp", """select distinct k.r, k.p, k.cg, k.cg2 from t_test k where in_MODLYEAR(k.y)
                       and exists(select 1 from FLO_FUNC f where f.r=k.r and f.y=k.y and f.p=k.p and f.cg=k.cg2 and f.cg2=k.cg)""")
    db.tmp("t_tes2", """select k.r, k.y, k.p, g.cg, m.c, g.cg2 from RTP k join t_grp g on g.r=k.r and g.p=k.p
                        join COM_GMAP m on m.r=g.r and m.cg=g.cg where in_RPC(k.r,k.p,m.c)""")
    # --- OPTION CG_GRP <= FLO_FUNC;
    #     CGTES2(RTP(R,V,P),COM_GRP,C,CG)$(COM_GMAP(R,COM_GRP,C)$RPC(R,P,C)$CG_GRP(R,P,COM_GRP,CG)) $= SUM(S$FLO_FUNC(RTP,COM_GRP,CG,S),1);
    db.x("""insert into t_tes2 select distinct f.r, f.y, f.p, f.cg, m.c, f.cg2 from FLO_FUNC f join COM_GMAP m on m.r=f.r and m.cg=f.cg
            where in_RTP(f.r,f.y,f.p) and in_RPC(f.r,f.p,m.c)
              and not exists(select 1 from t_tes2 z where z.r=f.r and z.y=f.y and z.p=f.p and z.cg=f.cg and z.c=m.c and z.cg2=f.cg2)""")
    # --- CGTES2(CGTEST(RTP,C,COM,CG)) $= CGTES2(RTP,C,C,CG);
    db.x("""insert into t_tes2 select k.r, k.y, k.p, k.cg, k.c, k.cg2 from t_test k where in_RTP(k.r,k.y,k.p) and in_COM(k.cg)
              and exists(select 1 from t_tes2 z where z.r=k.r and z.y=k.y and z.p=k.p and z.cg=k.cg and z.c=k.cg and z.cg2=k.cg2)
              and not exists(select 1 from t_tes2 z where z.r=k.r and z.y=k.y and z.p=k.p and z.cg=k.cg and z.c=k.c and z.cg2=k.cg2)""")
    # --- OPTION CG_GRP <= CGTEST;
    db.tmp("t_grp", "select distinct r, p, cg, cg2 from t_test")
    # --- COEF_PTRAN(CGTES2(R,V,P,COM_GRP,C,CG),S)$((YES$FLO_SUM(CGTES2,S)+(NOT CG_GRP(R,P,CG,COM_GRP)))$RPCS_VAR(R,P,C,S)) =
    #       SUM((PRC_TSL(R,P,TSL),TS_GROUP(R,TSL,TS))$TS_MAP(R,TS,S),
    #         ((1+(1/FLO_FUNC(R,V,P,CG,COM_GRP,TS)-1)$FLO_FUNC(R,V,P,CG,COM_GRP,TS))$(NOT FLO_FUNC(R,V,P,COM_GRP,CG,TS)) +
    #          FLO_FUNC(R,V,P,COM_GRP,CG,TS)) * (1$(NOT FLO_SUM(CGTES2,S)) + FLO_SUM(CGTES2,S)));
    #     (a term with a forward FLO_FUNC or a FLO_SUM given as 0 is EPS (EPS*x, 0+EPS): a sum of 0 with such a term is an
    #      EPS record, not a deleted one, as in GAMS)
    if db.q1("select count(*) from t_tes2"):
        db.put("COEF_PTRAN", """
            select r, y, p, cg, c, cg2, s, value from (
            select k.r, k.y, k.p, k.cg, k.c, k.cg2, v.s,
                   (select sum(((case when in_FLO_FUNC(k.r,k.y,k.p,k.cg,k.cg2,g.s) then 0
                                      when in_FLO_FUNC(k.r,k.y,k.p,k.cg2,k.cg,g.s) then 1 / v_FLO_FUNC(k.r,k.y,k.p,k.cg2,k.cg,g.s) else 1 end)
                                + v_FLO_FUNC(k.r,k.y,k.p,k.cg,k.cg2,g.s))
                               * (case when in_FLO_SUM(k.r,k.y,k.p,k.cg,k.c,k.cg2,v.s) then v_FLO_SUM(k.r,k.y,k.p,k.cg,k.c,k.cg2,v.s) else 1 end)
                        order by g.s)
                    from PRC_TSL l join TS_GROUP g on g.r=l.r and g.tsl=l.tsl
                    where l.r=k.r and l.p=k.p and in_TS_MAP(k.r,g.s,v.s)) as value,
                   (select bool_or((in_FLO_FUNC(k.r,k.y,k.p,k.cg,k.cg2,g.s) and v_FLO_FUNC(k.r,k.y,k.p,k.cg,k.cg2,g.s) = 0)
                                   or (in_FLO_SUM(k.r,k.y,k.p,k.cg,k.c,k.cg2,v.s) and v_FLO_SUM(k.r,k.y,k.p,k.cg,k.c,k.cg2,v.s) = 0))
                    from PRC_TSL l join TS_GROUP g on g.r=l.r and g.tsl=l.tsl
                    where l.r=k.r and l.p=k.p and in_TS_MAP(k.r,g.s,v.s)) as eps
            from t_tes2 k join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=k.c
            where in_FLO_SUM(k.r,k.y,k.p,k.cg,k.c,k.cg2,v.s)
               or not exists(select 1 from t_grp g where g.r=k.r and g.p=k.p and g.cg=k.cg2 and g.cg2=k.cg))
            where value <> 0 or eps""", zero="eps")
    # --- COEF_PTRAN(CGTEST(R,V,P,CG,C,CG2),S)$((NOT CGTES2(CGTEST))$RPCS_VAR(R,P,C,S)) $= FLO_SUM(CGTEST,S);
    # (RPC, RPCS_VAR and NOT CGTES2 as semi and anti joins: the same rows as the exists tests of the lookup macros, a
    #  third of the time on a FLO_SUM of 26 M rows)
    sel = """select f.r, f.y, f.p, f.cg, f.c, f.cg2, f.s, f.value from FLO_SUM f
             semi join RPC k on k.r=f.r and k.p=f.p and k.c=f.c
             semi join RPCS_VAR v on v.r=f.r and v.p=f.p and v.c=f.c and v.s=f.s
             anti join t_tes2 z on z.r=f.r and z.y=f.y and z.p=f.p and z.cg=f.cg and z.c=f.c and z.cg2=f.cg2"""
    if was_empty:
        # COEF_PTRAN holds only the records of the statement above, all of keys in CGTES2; these are of keys not in
        # CGTES2: no record to replace, so the rows go straight in (put's copy of them and its delete of old keys
        # did nothing but cost: 26 M rows on a large model); $= skips a NULL, keeps a zero (EPS)
        r = db.x(f'insert into COEF_PTRAN (r, y, p, cg, c, cg2, s, value) select * from ({sel}) where value is not null', kind="put.insert direct")
        db.hand["put.insert direct"][2] += r.fetchone()[0]
    else:
        db.put("COEF_PTRAN", sel, zero="eps")
    # --- * Convert reduced flows      (KEEP_FLOF and RPCG_PTRAN: REDUCE YES, flows tied to the activity by FLO_FUNC / FLO_SUM)
    #     KEEP_FLOF(RPC_AFLO(R,P,C)) = NO;
    #     ACT_FLO(RTP(R,V,P),C,S)$(RPCS_VAR(R,P,C,S)$KEEP_FLOF(R,P,C)) =
    #       SUM((RPCG_PTRAN(RPC_ACT(R,P,COM),C,CG,CG4),PRC_TS(R,P,TS))$TS_MAP(R,TS,S),PRC_ACTFLO(RTP,COM)*COEF_PTRAN(RTP,CG,COM,CG4,TS)) +
    #       SUM(RPCG_PTRAN(R,P,C,COM,CG,CG4)$COEF_PTRAN(RTP,CG,C,CG4,S),PRC_ACTFLO(RTP,COM)/COEF_PTRAN(RTP,CG,C,CG4,S));
    #     CGTEST(CGTES2) = YES;
    #     COEF_PTRAN(CGTEST(R,V,P,CG,C,COM),S)$RPCG_PTRAN(R,P,C,COM,CG,COM) = 0;
    if db.card("RPCG_PTRAN"):
        db.remove("KEEP_FLOF", where="in_RPC_AFLO(r,p,c)")
        db.x("""create or replace temp table t_af as
                select k.r, k.y, k.p, v.c, v.s, sum(x.value order by x.part, x.cg, x.cg2, x.ts) as value,
                       coalesce(bool_or(x.e), false) as rec from RTP k
                join KEEP_FLOF f on f.r=k.r and f.p=k.p join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=f.c
                left join (select 1 as part, g.r, g.p, g.c2 as c, t.s2 as s, k2.y,
                                  v_PRC_ACTFLO(g.r,k2.y,g.p,g.c) * a.value as value, g.cg, g.cg2, a.s as ts,
                                  in_PRC_ACTFLO(g.r,k2.y,g.p,g.c) as e
                           from RPCG_PTRAN g join RTP k2 on k2.r=g.r and k2.p=g.p
                           join COEF_PTRAN a on a.r=g.r and a.y=k2.y and a.p=g.p and a.cg=g.cg and a.c=g.c and a.cg2=g.cg2
                           join PRC_TS t0 on t0.r=g.r and t0.p=g.p and t0.s=a.s
                           join TS_MAP t on t.r=g.r and t.s=a.s
                           where in_RPC_ACT(g.r,g.p,g.c)
                           union all
                           select 2, g.r, g.p, g.c, a.s, k2.y, v_PRC_ACTFLO(g.r,k2.y,g.p,g.c2) / a.value as value, g.cg, g.cg2, a.s as ts,
                                  in_PRC_ACTFLO(g.r,k2.y,g.p,g.c2)
                           from RPCG_PTRAN g join RTP k2 on k2.r=g.r and k2.p=g.p
                           join COEF_PTRAN a on a.r=g.r and a.y=k2.y and a.p=g.p and a.cg=g.cg and a.c=g.c and a.cg2=g.cg2
                           where a.value <> 0) x
                  on x.r=k.r and x.y=k.y and x.p=k.p and x.c=v.c and x.s=v.s
                group by k.r, k.y, k.p, v.c, v.s""")
        db.zap("ACT_FLO", "exists(select 1 from t_af a where a.r=ACT_FLO.r and a.y=ACT_FLO.y and a.p=ACT_FLO.p and a.c=ACT_FLO.cg and a.s=ACT_FLO.s)")
        #     (a term with an EPS factor (a FLO_SUM given as 0) and a PRC_ACTFLO on record is EPS: a sum of 0 with such a
        #      term is an EPS record)
        db.put("ACT_FLO", "select r, y, p, c as cg, s, value from t_af where value <> 0 or rec", zero="eps")
        db.x("""delete from COEF_PTRAN a where exists(select 1 from RPCG_PTRAN g where g.r=a.r and g.p=a.p and g.c=a.c
                  and g.c2=a.cg2 and g.cg=a.cg and g.cg2=a.cg2)
                and (exists(select 1 from t_test z where z.r=a.r and z.y=a.y and z.p=a.p and z.cg=a.cg and z.c=a.c and z.cg2=a.cg2)
                     or exists(select 1 from t_tes2 z where z.r=a.r and z.y=a.y and z.p=a.p and z.cg=a.cg and z.c=a.c and z.cg2=a.cg2))""")
    # --- CGTEST(CGTES2) = YES;  OPTION CG_GRP <= CGTEST;  CG_GRP(RPCC_FFUNC) = NO;  OPTION RPCC_FFUNC <= CG_GRP;
    db.tmp("t_grp", "select distinct r, p, cg, cg2 from (select r, p, cg, cg2 from t_test union select r, p, cg, cg2 from t_tes2)")
    db.x("delete from t_grp where in_RPCC_FFUNC(r,p,cg,cg2)")
    db.assign("RPCC_FFUNC", "select r, p, cg, cg2 from t_grp")
    # --- OPTION RP_GRP <= CG_GRP; PRC_CG(RP_GRP)=YES; OPTION RP_GRP < CG_GRP; PRC_CG(RP_GRP)=YES;
    db.add("PRC_CG", "select r, p, cg from t_grp union select r, p, cg2 from t_grp")
    # --- RPCC_FFUNC(R,P,CG,C)$(RC(R,C)$(NOT RPC(R,P,C))) = NO;
    db.remove("RPCC_FFUNC", where="in_RC(r,cg2) and not in_RPC(r,p,cg2)")


# ---------------------------------------------------------------------------
def coef_shp(db: DB):
    # --- Z=SMAX(T,MAX(IPD(T),D(T))); OPYEAR(LIFE,AGE)$((ORD(AGE)<=ORD(LIFE))$(ORD(LIFE)<=Z)) = YES;
    z = db.q1("select max(greatest(v_IPD(y), v_D(y))) from MILESTONYR")
    db.add("OPYEAR", f"""select a.age, b.age as age2 from AGE a, AGE b
                         where cast(b.age as INTEGER) <= cast(a.age as INTEGER) and cast(a.age as INTEGER) <= {z}""")
    if db.card("FLO_FUNCX"):
        flo_shape(db)
    clag_shape(db)
    cpx_shape(db, z)
    # (the overriding COEF_OCOM / COEF_RCOM of RPC_CONLY need FLO_FUNCX(R,'0',P,'CAPFLO',C) = 3, which stops in flo_shape)
    # --- Filter off RCOMs by age:
    #     COEF_OCOM(R,VNT(V,T),P,C)$RCAP_OCAP(R,V,P,C) = (COEF_OCOM(R,V,T,P,C)+EPS$COEF_RCOM(R,V,T,P,C))$
    #       (SIGN(RCAP_OCAP(R,V,P,C))*(B(T)-(B(V)+NCAP_ILED(R,V,P)+1/PI**9))<RCAP_OCAP(R,V,P,C));
    #     (B(V) of a past vintage is its year; an RCAP_OCAP of EPS: SIGN 0 < 0 is false, the flow is dropped)
    if db.card("RCAP_OCAP"):
        db.x("""create or replace temp table n_ocom as
                select o.r, n.y, n.y2, o.p, o.c,
                       case when sign(o.value) * (v_B(n.y2) - (coalesce((select b.value from B b where b.y=n.y), yv(n.y))
                                                              + v_NCAP_ILED(o.r,n.y,o.p) + 1 / pow(pi(), 9))) < o.value
                            then (case when in_COEF_OCOM(o.r,n.y,n.y2,o.p,o.c) then v_COEF_OCOM(o.r,n.y,n.y2,o.p,o.c) else 0 end)
                            else null end as value,
                       in_COEF_OCOM(o.r,n.y,n.y2,o.p,o.c) or in_COEF_RCOM(o.r,n.y,n.y2,o.p,o.c) as rec
                from RCAP_OCAP o join VNT n on n.y=o.y""")
        db.x("delete from COEF_OCOM where exists(select 1 from n_ocom n where n.r=COEF_OCOM.r and n.y=COEF_OCOM.y and n.y2=COEF_OCOM.y2 and n.p=COEF_OCOM.p and n.c=COEF_OCOM.c)")
        # a value of 0 stays on record (EPS) where COEF_RCOM gives one, or where COEF_OCOM was EPS
        db.put("COEF_OCOM", "select r, y, y2, p, c, value from n_ocom where value is not null and (value <> 0 or rec)", zero="eps")


def clag_shape(db: DB):
    """coef_shp.mod, 'Shapes for capacity-related commodity flows': NCAP_CLAG delays (> 0) or ends early (< 0) the flow
    NCAP_COM of a vintage.  COEF_CIO is the share of the period in which the flow runs, less 1; cal_cap.mod multiplies the
    NCAP_COM term of the commodity balance by 1 + COEF_CIO.  (The CAPFLO shapes of FLO_FUNCX, the other source of COEF_CIO,
    stop in flo_shape.)"""
    # --- COEF_CIO(RTP_CPTYR(R,V,T,P),C,IO)$NCAP_CLAG(R,V,P,C,IO) = SIGN(NCAP_CLAG(R,V,P,C,IO)) *
    #       (MAX(0, E(T)+1-MAX(B(V)+NCAP_ILED(R,V,P)+ABS(NCAP_CLAG(R,V,P,C,IO)),B(T))) /
    #        MAX(.1,E(T)+1-MAX(B(V)+NCAP_ILED(R,V,P),B(T)))-1)-1$(NCAP_CLAG(R,V,P,C,IO)<0);
    #     (NCAP_ILED is not rounded here; B(V) of a past vintage is its year)
    db.put("COEF_CIO", """
        select c.r, c.y, c.y2, c.p, l.c, l.io,
               sign(l.value) * (greatest(0, v_E(c.y2) + 1 - greatest(v_B(c.y) + v_NCAP_ILED(c.r,c.y,c.p) + abs(l.value), v_B(c.y2)))
                                / greatest(0.1, v_E(c.y2) + 1 - greatest(v_B(c.y) + v_NCAP_ILED(c.r,c.y,c.p), v_B(c.y2))) - 1)
               - (case when l.value < 0 then 1 else 0 end) as value
        from RTP_CPTYR c join NCAP_CLAG l on l.r=c.r and l.y=c.y and l.p=c.p
        where l.value <> 0""")
    db.zap("COEF_CIO", "value = 0")


def flo_shape(db: DB):
    """coef_shp.mod, 'Shaping of COEF_PTRAN': FLO_FUNCX points to a SHAPE curve by age that multiplies the transformation
    and emission factors of a vintage (FLO_FUNC / FLO_SUM).  Per period the curve is averaged over the years of the period
    in which the vintage operates; RTP_FFCX holds that average less 1, and the equations multiply by 1 + RTP_FFCX."""
    q = db.q
    # --- RTP_CGC(RTP(R,V,P),CG,CG2)$((FLO_FUNCX(RTP,CG,CG2)<=0)$FLO_FUNCX(RTP,CG,CG2))=PRC_VINT(R,P);
    db.tmp("t_cgc", """select r, y, p, cg, cg2 from FLO_FUNCX where value <= 0 and in_RTP(r,y,p) and in_PRC_VINT(r,p)""")
    # --- Z=CARD(J)/2+1;  FLO_FUNCX(RTP,CG,CG2)$(ABS(FLO_FUNCX(RTP,CG,CG2)-Z)>Z-1.5-INF$ACTCG(CG)) = 0;
    #     (the ACT forms were moved to the shadow group in ppm_ext.vda; curve 1 is the constant 1; 0 and EPS are no curve)
    zj = db.card("J") / 2 + 1
    db.zap("FLO_FUNCX", f"in_RTP(r,y,p) and (in_ACTCG(cg) or abs(value - {zj}) > {zj} - 1.5)")
    # --- OPTION RP_GRP <= FLO_FUNCX, PRC_YMIN < RP_GRP, CLEAR=PRC_YMAX;
    #     TRACKP(RP)$PRC_YMIN(RP) $= PRC_VINT(RP)+RP_GRP(RP,'CAPFLO');   RTP_CAPYR(RTP_CPTYR(R,V,T,P)) $= TRACKP(R,P);
    db.tmp("t_trk", "select distinct r, p from FLO_FUNCX where in_PRC_VINT(r,p) or cg = 'CAPFLO'")
    if db.q1("select count(*) from FLO_FUNCX where cg = 'CAPFLO'"):
        unsupported(db, "FLO_FUNCX on capacity-related flows (CAPFLO: COEF_CIO, coef_shp.mod)")
    db.add("RTP_CAPYR", "select c.r, c.y, c.y2, c.p from RTP_CPTYR c join t_trk k on k.r=c.r and k.p=c.p")
    # --- RVPRL(RTP(R,T,P))$((COEF_RPTI(RTP)>1)$TRACKP(R,P)) = ...   (repeated investments: the average over the lifetime)
    if db.q1("select count(*) from COEF_RPTI a join t_trk k on k.r=a.r and k.p=a.p where a.value > 1"):
        unsupported(db, "FLO_FUNCX on a process with repeated investments within a period (COEF_RPTI > 1, coef_shp.mod)")
    # --- LOOP(AGEJ(J,AGE) = (1,1), LOOP(V,
    #       PRC_YMIN(TRACKP(R,P)) = B(V)+ROUND(NCAP_ILED(R,V,P));  PRC_YMAX(TRACKP(R,P)) = PRC_YMIN(R,P)+ROUND(NCAP_TLIFE(R,V,P))-1;
    #       RTP_FFCX(RTP_CAPYR(R,V,T,P),CG1,CG2)$FLO_FUNCX(R,V,P,CG1,CG2) =
    #         SUM(PERIODYR(T,EOHYEARS)$(YEARVAL(EOHYEARS) LE MAX(B(T),PRC_YMAX(R,P))),
    #           SHAPE(J+(FLO_FUNCX(R,V,P,CG1,CG2)-1),AGE+(MIN(YEARVAL(EOHYEARS),PRC_YMAX(R,P))-PRC_YMIN(R,P))))
    #         / (MAX(1,MIN(E(T),PRC_YMAX(R,P))-MAX(B(T),PRC_YMIN(R,P))+1)) -1;))
    #     (an age below 1 is outside the set AGE: the years before the vintage starts count 0)
    from .common import rnd
    B = {y: v for y, v in q("select y, value from B")}
    E = {y: v for y, v in q("select y, value from E")}
    ages = {int(a) for (a,) in q("select age from AGE")}
    shp = {(int(j), int(a)): x for j, a, x in q("select j, age, value from SHAPE")}
    eoh = {}
    for t, y in q("select p.y, p.y2 from PERIODYR p where in_EOHYEARS(p.y2) and in_MILESTONYR(p.y) order by yv(p.y2)"):
        eoh.setdefault(t, []).append(int(y))
    rows = []
    for r, v, t, p, cg1, cg2, fx, iled, tlife in q("""
            select c.r, c.y, c.y2, c.p, f.cg, f.cg2, f.value, v_NCAP_ILED(c.r,c.y,c.p), v_NCAP_TLIFE(c.r,c.y,c.p)
            from RTP_CAPYR c join FLO_FUNCX f on f.r=c.r and f.y=c.y and f.p=c.p"""):
        ymin = B.get(v, 0.0) + rnd(iled)
        ymax = ymin + rnd(tlife) - 1
        j = rnd(fx)
        tot = 0.0
        for y in eoh.get(t, ()):
            if y <= max(B[t], ymax):
                age = 1 + min(y, ymax) - ymin
                if age >= 1 and int(age) in ages:
                    tot += shp.get((j, int(age)), 0.0)
        val = tot / max(1, min(E[t], ymax) - max(B[t], ymin) + 1) - 1
        if val:
            rows.append((r, v, t, p, cg1, cg2, val))
    # --- Option for non-vintaged FLO_FUNC multipliers:
    #     RTP_FFCX(RTP_VINTYR(R,V,T,P),CG,CG2)$((FLO_FUNC(R,V,P,CG,CG2,'ANNUAL')>0)$RTP_CGC(R,V,P,CG,CG2)) =
    #       FLO_FUNC(R,T,P,CG,CG2,'ANNUAL')/FLO_FUNC(R,V,P,CG,CG2,'ANNUAL')-1;
    db.x("create or replace temp table t_ffcx (r VARCHAR, y VARCHAR, y2 VARCHAR, p VARCHAR, cg VARCHAR, cg2 VARCHAR, value DOUBLE)")
    db.insert_rows("t_ffcx", rows)
    db.put("RTP_FFCX", "select r, y, y2, p, cg, cg2, value from t_ffcx")
    db.put("RTP_FFCX", """select k.r, k.y, k.y2, k.p, g.cg, g.cg2,
                                 v_FLO_FUNC(k.r,k.y2,k.p,g.cg,g.cg2,'ANNUAL') / v_FLO_FUNC(k.r,k.y,k.p,g.cg,g.cg2,'ANNUAL') - 1 as value
                          from RTP_VINTYR k join t_cgc g on g.r=k.r and g.y=k.y and g.p=k.p
                          where v_FLO_FUNC(k.r,k.y,k.p,g.cg,g.cg2,'ANNUAL') > 0""")


def cpx_shape(db: DB, z):
    """coef_shp.mod, 'Shaping of COEF_CPT': NCAP_CPX points to a SHAPE curve by age that scales the capacity available
    from a vintage.  Per period the curve is averaged over the years of the period, weighted with the discount factors,
    and the result may only lower COEF_CPT:   COEF_CPT = MIN(COEF_CPT, average shape).   RTP_CPX keeps the relative
    change (it is applied to the fixed costs and the salvage value as well)."""
    from .common import rnd
    # --- Z=CARD(J)/2+1;  NCAP_CPX(RTP)$(ABS(NCAP_CPX(RTP)-Z)>Z-1.5) = 0;                   (indexes 2 .. CARD(J) are curves)
    zz = db.card("J") / 2 + 1
    db.zap("NCAP_CPX", f"in_RTP(r,y,p) and abs(value - {zz}) > {zz} - 1.5")
    if not db.card("NCAP_CPX"):
        db.clear("RTP_CPX")
        return
    q = db.q
    # --- OPTION PRC_YMIN < NCAP_CPX;  LOOP(AGEJ(J,AGE)$CARD(NCAP_CPX), TRACKP(RP) $= PRC_YMIN(RP);          (AGEJ = 1.1)
    track = {(r, p) for r, p in q("select distinct r, p from NCAP_CPX where in_RP(r,p)")}
    V = {int(y) for (y,) in q("select y from MODLYEAR")}
    T = {int(y) for (y,) in q("select y from MILESTONYR")}
    B = {int(y): v for y, v in q("select y, value from B")}
    yeoh = {int(y) for (y,) in q("select y from Y_EOH")}
    peryr = {}
    for t, y in q("select y, y2 from PERIODYR where in_MILESTONYR(y) order by yv(y2)"):
        if int(y) in yeoh:
            peryr.setdefault(int(t), []).append(int(y))
    shape = {(int(j), int(a)): v for j, a, v in q("select j, age, value from SHAPE")}
    p3 = lambda n: {(r, int(y), p): v for r, y, p, v in q(f'select r, y, p, value from "{n}" where y <> \'0\'')}
    cpx, iled, tlife, rpti = p3("NCAP_CPX"), p3("NCAP_ILED"), p3("NCAP_TLIFE"), p3("COEF_RPTI")
    disc = {(r, int(y)): v for r, y, v in q("select d.r, d.y, d.value from OBJ_DISC d join G_RCUR g on g.r=d.r and g.cur=d.cur")}
    pvt = {(r, int(y)): v for r, y, v in q("select r, y, value from COEF_PVT")}
    cptyr = [(r, int(v), int(t), p, val) for r, v, t, p, val in q("""select c.r, c.y, c.y2, c.p, v_COEF_CPT(c.r,c.y,c.y2,c.p) from RTP_CPTYR c
                                                                   where exists(select 1 from NCAP_CPX n where n.r=c.r and n.p=c.p)""")]
    rtp = {(r, int(y), p) for r, y, p in q("select r, y, p from RTP")}
    cap = {}
    for r, v, t, p, cpt in cptyr:
        k = (r, v, p)
        if (r, p) not in track or v not in V or not cpx.get(k):
            continue
        # --- PRC_YMIN = B(V)+ROUND(NCAP_ILED(R,V,P));  PRC_YMAX = PRC_YMIN+NCAP_TLIFE(R,V,P);
        #     COEF_CAP(RTP_CPTYR(R,V,T,P))$NCAP_CPX(R,V,P) = SUM(PERIODYR(T,Y_EOH)$(YEARVAL(Y_EOH)<PRC_YMAX),
        #        MIN(1,PRC_YMAX-YEARVAL(Y_EOH))*OBJ_DISC(R,Y_EOH,CUR)*SHAPE(J+(NCAP_CPX(R,V,P)-1),AGE+(YEARVAL(Y_EOH)-PRC_YMIN))) / COEF_PVT(R,T)
        ymin = B[v] + rnd(iled.get(k, 0.0))
        ymax = ymin + tlife.get(k, 0.0)
        j = int(rnd(cpx[k]))
        x = sum(min(1.0, ymax - y) * disc.get((r, y), 0.0) * shape.get((j, 1 + int(y - ymin)), 0.0)
                for y in peryr.get(t, ()) if y < ymax and y >= ymin) / pvt[(r, t)]
        # --- RVPRL(RTP)$((COEF_RPTI(RTP)>1)$NCAP_CPX(RTP)) = ROUND(NCAP_TLIFE(RTP)-1)+EPS;       repeated investments: average over the lifetime
        #     COEF_CAP(RTP_CPTYR(R,V(TT),T,P))$RVPRL(R,V,P) = SUM(OPYEAR(AGE+RVPRL(R,V,P),LIFE),SHAPE(J+(NCAP_CPX(R,V,P)-1),LIFE)) / (RVPRL(R,V,P)+1);
        if rpti.get(k, 0.0) > 1 and k in rtp and v in T:
            n = rnd(tlife.get(k, 0.0) - 1)
            x = (sum(shape.get((j, a), 0.0) for a in range(1, int(n) + 2)) if n + 1 <= z else 0.0) / (n + 1)
        # --- COEF_CAP(RTP_CPTYR(R,V,T,P))$NCAP_CPX(R,V,P) = (1/MAX(1,COEF_CPT(R,V,T,P)/COEF_CAP(R,V,T,P)))$COEF_CAP(R,V,T,P)-1;
        c = (1 / max(1.0, cpt / x) if x else 0.0) - 1
        if c:
            cap[(r, v, t, p)] = c
    # --- COEF_CPT(R,V,T,P)$COEF_CAP(R,V,T,P) = COEF_CPT(R,V,T,P)*(COEF_CAP(R,V,T,P)+1);
    #     OPTION ..., RTP_CPX <= COEF_CAP, CLEAR=COEF_CAP;
    db.x("create or replace temp table t_cap (r VARCHAR, y VARCHAR, y2 VARCHAR, p VARCHAR, value DOUBLE)")
    if cap:
        db.insert_rows("t_cap", [(r, str(v), str(t), p, c) for (r, v, t, p), c in cap.items()])
    db.put("COEF_CPT", "select c.r, c.y, c.y2, c.p, v_COEF_CPT(c.r,c.y,c.y2,c.p) * (c.value + 1) as value from t_cap c")
    db.clear("RTP_CPX")
    db.put("RTP_CPX", "select r, y, p, y2, value from t_cap")
