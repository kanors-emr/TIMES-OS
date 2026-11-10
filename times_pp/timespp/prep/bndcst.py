# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounds on undiscounted costs by region, category and currency (eqbndcst.mod, bnd_cum.mod 44-48).

REG_BNDCST(r,t,agg,cur,bd) bounds the costs of one milestone year, REG_CUMCST(r,y1,y2,agg,cur,bd) those of the years
y1..y2.  TIMES states for each (r,y1,y2,agg,cur) with an UP bound one row EQ_BNDCST(r,y1,tt,y2,agg,cur), tt the
period that holds y2 (SUPERYR), equating the undiscounted costs of the category to VAR_CUMCST(r,y1,y2,agg,cur); the
row of an aggregate category (COST_GMAP) sums the VAR_CUMCST of its components instead.  The coefficients are
prepared here, as port-only tables, so that the equations only multiply them by the variables:

    BC_ROW(r,y1,y2,agg,cur,tt)                     the rows
    BC_NCAP(r,y1,y2,agg,cur,t,p)                   of VAR_NCAP(r,t,p): investment, decommissioning and fixed costs
    BC_COMNET / BC_COMPRD(r,y1,y2,agg,cur,t,c,s)   of VAR_COMNET / VAR_COMPRD: commodity taxes and subsidies
    BC_FLO(r,y1,y2,agg,cur,t,p,c,s)                of the flows of (t,p,c,s), all vintages: flow taxes and subsidies
    BC_AGG(r,y1,y2,agg,cur,agg2)                   of a component's VAR_CUMCST in an aggregate's row (1; -1 a subsidy)

and the bounds of VAR_CUMCST in B_VAR_CUMCST.
"""
from ..engine import DB
from ..controls import unsupported
from .common import rnd

# --- SET COST_GMAP(COSTAGG,COSTAGG,COSTYPE) (eqbndcst.mod 19-33; FIXSUB and ALLSUB map their subsidies with TAX: the
#     sign of the component is then +1, as TIMES has it)
COST_GMAP = [
    ("INVTAXSUB", "INVTAX", "TAX"), ("INVTAXSUB", "INVSUB", "SUB"),
    ("INVALL", "INV", "COST"), ("INVALL", "INVTAX", "TAX"), ("INVALL", "INVSUB", "SUB"),
    ("FOMTAXSUB", "FOMTAX", "TAX"), ("FOMTAXSUB", "FOMSUB", "SUB"),
    ("FOMALL", "FOM", "COST"), ("FOMALL", "FOMTAX", "TAX"), ("FOMALL", "FOMSUB", "SUB"),
    ("FIX", "INV", "COST"), ("FIX", "FOM", "COST"),
    ("FIXTAX", "INVTAX", "TAX"), ("FIXTAX", "FOMTAX", "TAX"),
    ("FIXSUB", "INVSUB", "TAX"), ("FIXSUB", "FOMSUB", "TAX"),
    ("FIXTAXSUB", "INVTAX", "TAX"), ("FIXTAXSUB", "INVSUB", "SUB"), ("FIXTAXSUB", "FOMTAX", "TAX"), ("FIXTAXSUB", "FOMSUB", "SUB"),
    ("FIXALL", "INV", "COST"), ("FIXALL", "INVTAX", "TAX"), ("FIXALL", "INVSUB", "SUB"),
    ("FIXALL", "FOM", "COST"), ("FIXALL", "FOMTAX", "TAX"), ("FIXALL", "FOMSUB", "SUB"),
    ("COMTAXSUB", "COMTAX", "TAX"), ("COMTAXSUB", "COMSUB", "SUB"),
    ("FLOTAXSUB", "FLOTAX", "TAX"), ("FLOTAXSUB", "FLOSUB", "SUB"),
    ("ALLTAX", "INVTAX", "TAX"), ("ALLTAX", "FOMTAX", "TAX"), ("ALLTAX", "COMTAX", "TAX"), ("ALLTAX", "FLOTAX", "TAX"),
    ("ALLSUB", "INVSUB", "TAX"), ("ALLSUB", "FOMSUB", "TAX"), ("ALLSUB", "COMSUB", "TAX"), ("ALLSUB", "FLOSUB", "TAX"),
    ("ALLTAXSUB", "INVTAX", "TAX"), ("ALLTAXSUB", "INVSUB", "SUB"), ("ALLTAXSUB", "FOMTAX", "TAX"), ("ALLTAXSUB", "FOMSUB", "SUB"),
    ("ALLTAXSUB", "COMTAX", "TAX"), ("ALLTAXSUB", "COMSUB", "SUB"), ("ALLTAXSUB", "FLOTAX", "TAX"), ("ALLTAXSUB", "FLOSUB", "SUB"),
]
AGGREGATES = {a for a, _, _ in COST_GMAP}
INF = float("inf")


def declare(db: DB):
    db.declare("BC_ROW", "set", ["R", "ALLYEAR", "ALLYEAR", "COSTAGG", "CUR", "T"])
    db.declare("BC_NCAP", "par", ["R", "ALLYEAR", "ALLYEAR", "COSTAGG", "CUR", "T", "P"])
    db.declare("BC_COMNET", "par", ["R", "ALLYEAR", "ALLYEAR", "COSTAGG", "CUR", "T", "C", "S"])
    db.declare("BC_COMPRD", "par", ["R", "ALLYEAR", "ALLYEAR", "COSTAGG", "CUR", "T", "C", "S"])
    db.declare("BC_FLO", "par", ["R", "ALLYEAR", "ALLYEAR", "COSTAGG", "CUR", "T", "P", "C", "S"])
    db.declare("BC_AGG", "par", ["R", "ALLYEAR", "ALLYEAR", "COSTAGG", "CUR", "COSTAGG"])


def prepare(db: DB):
    """eqbndcst.mod 35-49: SUPERYR, REG_BNDCST into REG_CUMCST, the infinite UP bounds of the components; returns the
    bounded categories {(r,y1,y2,agg,cur): tt} and RT_IAN's single-year bounds {(r,t,cur): {'INV','INVTAXSUB'}},
    or None without cost bounds (and then no BC_ tables: model.db3 as before)."""
    if not (db.card("REG_CUMCST") or db.card("REG_BNDCST")):
        return None
    declare(db)
    if db.ctl.get("OBJ") == "LIN":
        unsupported(db, "cost bounds (REG_CUMCST, REG_BNDCST) with OBJ LIN (the pulses of eqbndcst.mod)", ["REG_CUMCST", "REG_BNDCST"])
    q = db.q
    # --- REG_CUMCST(R,T,T,COSTAGG,CUR,BD) $= REG_BNDCST(R,T,COSTAGG,CUR,BD);       (an EPS bound is a record)
    db.put("REG_CUMCST", "select r, y, y as y2, agg, cur, l, value from REG_BNDCST where in_MILESTONYR(y)", zero="eps")
    cum = {(r, y, y2, a, cur, l): v for r, y, y2, a, cur, l, v in q("select r, y, y2, agg, cur, l, value from REG_CUMCST")}
    # --- LOOP((COST_GMAP(COSTCAT,COSTAGG,COSTYPE),BD),
    #       REG_CUMCST(R,YEAR,LL,COSTAGG,CUR,'UP')$((NOT REG_CUMCST(R,YEAR,LL,COSTAGG,CUR,'UP'))$REG_CUMCST(R,YEAR,LL,COSTCAT,CUR,BD)) = INF);
    #     (EPS is a record: NOT EPS is false, $EPS true)
    keys = {k[:5] for k in cum}
    for agg, comp, _ in COST_GMAP:
        for (r, y, y2, a, cur) in sorted(keys):
            if a == agg and (r, y, y2, comp, cur, "UP") not in cum:
                cum[(r, y, y2, comp, cur, "UP")] = INF
    # --- LOOP(BDLOX(BD), REG_CUMCST(R,YEAR,LL,COSTCAT,CUR,'UP')$((NOT REG_CUMCST(..,'UP'))$REG_CUMCST(..,BD)) = INF);
    for (r, y, y2, a, cur, l) in list(cum):
        if l in ("LO", "FX") and (r, y, y2, a, cur, "UP") not in cum:
            cum[(r, y, y2, a, cur, "UP")] = INF
    db.clear("REG_CUMCST")
    db.load_rows("REG_CUMCST", [k + (v,) for k, v in sorted(cum.items())])
    # --- SUPERYR(PERIODYR(T,LL))$(YEARVAL(LL) LE YEARVAL(T)) = YES;
    #     SUPERYR(T+1,LL)$((YEARVAL(LL) GT YEARVAL(T))$PERIODYR(T,LL)) = YES;
    #     LOOP(MIYR_1(T++1),SUPERYR(T,LL)$(YEARVAL(LL) GT M(T)) = YES);       (T: the last period, for any later year)
    T = sorted(int(t) for (t,) in q("select y from MILESTONYR"))
    nxt = dict(zip(T, T[1:]))
    sup = {}
    for t, ll in q("select y, y2 from PERIODYR where in_MILESTONYR(y)"):
        t, ll = int(t), int(ll)
        if ll <= t:
            sup.setdefault(ll, set()).add(t)
        elif t in nxt:
            sup.setdefault(ll, set()).add(nxt[t])
    last = T[-1]
    mlast = db.q1(f"select value from M where y='{last}'")
    rows = {}
    for (r, y, y2, a, cur, l) in cum:
        if l != "UP":
            continue
        tts = set(sup.get(int(y2), ()))
        if int(y2) > mlast:
            tts.add(last)
        for tt in tts:
            rows.setdefault((r, y, y2, a, cur), set()).add(tt)
    # --- RT_IAN(R,T,T,CUR,'INV')$REG_CUMCST(R,T,T,'INV',CUR,'UP') = YES;
    #     RT_IAN(R,T,T,CUR,'INVTAXSUB')$(REG_CUMCST(R,T,T,'INVTAX',CUR,'UP')+REG_CUMCST(R,T,T,'INVSUB',CUR,'UP')) = YES;
    #     (a sum of EPS values is EPS: true)
    ian = {}
    Ts = {str(t) for t in T}
    for (r, y, y2, a, cur, l), v in cum.items():
        if l == "UP" and y == y2 and y in Ts:
            if a == "INV":
                ian.setdefault((r, int(y), cur), set()).add("INV")
            elif a in ("INVTAX", "INVSUB"):
                ian.setdefault((r, int(y), cur), set()).add("INVTAXSUB")
    db.clear("RT_IAN")
    db.load_rows("RT_IAN", sorted((r, str(y), str(y), cur, k) for (r, y, cur), kinds in ian.items() for k in kinds))
    db.load_rows("BC_ROW", sorted((r, y, y2, a, cur, str(tt)) for (r, y, y2, a, cur), tts in rows.items() for tt in tts))
    db.load_rows("BC_AGG", sorted((r, y, y2, agg, cur, comp, -1.0 if typ == "SUB" else 1.0)
                                  for (r, y, y2, a, cur) in rows for agg, comp, typ in COST_GMAP if a == agg))
    return dict(rows=rows, ian=ian, cum=cum)


def ncap_coefficients(db: DB, bc, T, K_EOH, sumii, invspred, crf, divi, sumiii, crfd_d, diviii, DELIF, sumiv, invstep,
                      diviv, ICO, ITX, ISU, FOM, FTX, FSB, DCC, shapes, SHP, MUL, cst_annc):
    """eqbndcst.mod 86-151: the coefficients of VAR_NCAP(r,t,p), vintages t <= tt (YK(TT,T))."""
    out = {}

    def put(key, x):
        if x:
            out[key] = out.get(key, 0.0) + x

    def eps(key, w=1.0):
        """a term that is EPS (a cost given as 0 under $ONEPS, times a weight that is not 0): an EPS coefficient, kept
        in the row unless a value comes to it (EPS + x is x)"""
        if w:
            out.setdefault(key, 0.0)

    byr = {}
    for k in set(sumii) | set(sumiv) | {(r, int(v), p) for (r, p, cur, v) in DCC}:
        byr.setdefault(k[0], []).append(k)
    for (r, y1s, y2s, cat, cur), tts in sorted(bc["rows"].items()):
        y1, A = int(y1s), int(y2s)
        for tt in tts:
            row = (r, y1s, y2s, cat, cur)
            ian = cat in ("INV", "INVTAX", "INVSUB") and \
                ("INV" if cat == "INV" else "INVTAXSUB") in bc["ian"].get((r, y1, cur), ()) and y1 == A
            if ian:
                # --- SUM((T,P)$CST_ANNC(R,T,P,TT,'INVCOST',CUR),CST_ANNC(R,T,P,TT,'INVCOST',CUR)*VAR_NCAP(R,T,P))  (INV)
                #     ... CST_ANNC(..,'INVTAX',CUR) (INVTAX);  - ... CST_ANNC(..,'INVSUB',CUR) (INVSUB)
                attr = {"INV": "INVCOST", "INVTAX": "INVTAX", "INVSUB": "INVSUB"}[cat]
                for (r2, t, p, tt2, a2, cur2), x in cst_annc.items():
                    if r2 == r and tt2 == tt and a2 == attr and cur2 == cur:
                        put(row + (t, p), -x if cat == "INVSUB" else x)
                        if x == 0.0:                       # CST_ANNC EPS (a tax or cost given as EPS)
                            eps(row + (t, p))
            for k in byr.get(r, ()):
                _, t, p = k
                if t not in T or t > tt:
                    continue
                if cat == "INV" and not ian:
                    # --- SUM((OBJ_SUMII(R,T,P,AGE,K_EOH(LL),JOT),SPAN(AGE+MIN(ORD(LL)+ORD(JOT)-ORD(YEAR)-1,0)))$YK(TT,T),
                    #       SUM(INVSPRED(K_EOH,JOT,Y,K)$YK(ALLYEAR,Y), OBJ_ICOST(R,K,P,CUR) *
                    #         MAX(0,MIN(YEARVAL(ALLYEAR)+1,YEARVAL(Y)+ORD(AGE))-MAX(YEARVAL(YEAR),YEARVAL(Y))))) *
                    #     VAR_NCAP(R,T,P) * OBJ_CRF(R,T,P,CUR) / OBJ_DIVI(R,T,P)
                    s, e = 0.0, False
                    for (life, y0, jot) in sumii.get(k, ()):
                        if y0 not in K_EOH or life + min(y0 + jot - y1 - 1, 0) < 1:
                            continue
                        s += sum(ICO.get((r, p, cur, kk), 0.0) * max(0, min(A + 1, mid + life) - max(y1, mid))
                                 for (mid, kk) in invspred.get((y0, jot), ()) if mid <= A)
                        e = e or any(ICO.get((r, p, cur, kk)) == 0.0 and max(0, min(A + 1, mid + life) - max(y1, mid))
                                     for (mid, kk) in invspred.get((y0, jot), ()) if mid <= A)
                    if s:
                        put(row + (t, p), s * crf.get((r, t, p, cur), 0.0) / divi[k])
                    elif e:
                        eps(row + (t, p), crf.get((r, t, p, cur), 0.0) / divi[k])
                if cat == "INV" and (r, p, cur, t) in DCC:
                    # --- SUM(RTP(R,T,P)$(YK(TT,T)$OBJ_DCOST(R,T,P,CUR)), SUM(OBJ_SUMIII(R,T,P,K_EOH,K,LL)$YK(ALLYEAR,LL),
                    #       OBJ_DCOST(R,K,P,CUR) * MAX(0,MIN(ORD(ALLYEAR)+1,ORD(LL)+ROUND(NCAP_DELIF(R,T,P)))-MAX(ORD(YEAR),ORD(LL)))) *
                    #     VAR_NCAP(R,T,P) * OBJ_CRFD(R,T,P,CUR) / OBJ_DIVIII(R,T,P))
                    s = sum(DCC.get((r, p, cur, kk), 0.0) * max(0, min(A + 1, ll + rnd(DELIF.get(k, 0.0))) - max(y1, ll))
                            for (_ke, kk, ll) in sumiii.get(k, ()) if ll <= A)
                    if s:
                        put(row + (t, p), s * crfd_d.get((r, t, p, cur), 0.0) / diviii[k])
                    elif any(DCC.get((r, p, cur, kk)) == 0.0 and max(0, min(A + 1, ll + rnd(DELIF.get(k, 0.0))) - max(y1, ll))
                             for (_ke, kk, ll) in sumiii.get(k, ()) if ll <= A):
                        eps(row + (t, p), crfd_d.get((r, t, p, cur), 0.0) / diviii[k])
                if cat in ("INVTAX", "INVSUB") and not ian:
                    # --- SUM(OBJ_SUMII(R,T,P,AGE,K_EOH,JOT)$(YK(TT,T)$OBJ_ITAX(R,T,P,CUR)),
                    #       SUM((INVSPRED(K_EOH,JOT,LL,K),SPAN(AGE+MIN(ORD(LL)-ORD(YEAR),0)))$YK(ALLYEAR,LL),
                    #         OBJ_ITAX(R,K,P,CUR) * (MIN(ORD(ALLYEAR)+1,ORD(LL)+ORD(AGE))-MAX(ORD(YEAR),ORD(LL))))) *
                    #     VAR_NCAP(R,T,P) * OBJ_CRF(R,T,P,CUR) / OBJ_DIVI(R,T,P)          (INVSUB: OBJ_ISUB)
                    X = ITX if cat == "INVTAX" else ISU
                    if (r, p, cur, t) not in X:
                        continue
                    s, e = 0.0, False
                    for (life, y0, jot) in sumii.get(k, ()):
                        if y0 not in K_EOH:
                            continue
                        s += sum(X.get((r, p, cur, kk), 0.0) * (min(A + 1, mid + life) - max(y1, mid))
                                 for (mid, kk) in invspred.get((y0, jot), ()) if mid <= A and life + min(mid - y1, 0) >= 1)
                        e = e or any(X.get((r, p, cur, kk)) == 0.0 and (min(A + 1, mid + life) - max(y1, mid))
                                     for (mid, kk) in invspred.get((y0, jot), ()) if mid <= A and life + min(mid - y1, 0) >= 1)
                    if s:
                        put(row + (t, p), s * crf.get((r, t, p, cur), 0.0) / divi[k])
                    elif e:
                        eps(row + (t, p), crf.get((r, t, p, cur), 0.0) / divi[k])
                if cat in ("FOM", "FOMTAX", "FOMSUB"):
                    X, shape = {"FOM": (FOM, shapes[0]), "FOMTAX": (FTX, shapes[1]), "FOMSUB": (FSB, shapes[2])}[cat]
                    if cat != "FOM" and (r, p, cur, t) not in X:
                        continue
                    # --- SUM((OBJ_SUMIV(LL,R,T,P,JOT,LIFE),SPAN(LIFE+MIN(ORD(LL)+ORD(JOT)-ORD(YEAR)-1,0)))$YK(TT,T),
                    #       SUM(INVSTEP(LL,JOT,K,JOT)$YK(ALLYEAR,K), OBJ_FOM(R,K,P,CUR) *
                    #         MAX(0,MIN(YEARVAL(ALLYEAR)+1,YEARVAL(K)+ORD(LIFE))-MAX(YEARVAL(YEAR),YEARVAL(K))))) *
                    #     VAR_NCAP(R,T,P) / OBJ_DIVIV(R,T,P)                         (FOMTAX: OBJ_FTX, FOMSUB: OBJ_FSB)
                    # (summed as GAMS generates the row: each element of the first SUM gives its own term of VAR_NCAP,
                    #  SUM(INVSTEP..) / OBJ_DIVIV, added in turn; the shaped SUM below is one more term. A FOM with SHAPE or
                    #  MULTI of EPS then cancels to 0 as in GAMS, where one division of the whole sum leaves 1e-17.)
                    c, e = 0.0, False
                    for (y0, jot, life) in sumiv.get(k, ()):
                        if life + min(y0 + jot - y1 - 1, 0) < 1:
                            continue
                        c += sum(X.get((r, p, cur, kk), 0.0) * max(0, min(A + 1, kk + life) - max(y1, kk))
                                 for kk in invstep.get((y0, jot), ()) if kk <= A) / diviv[k]
                        e = e or any(X.get((r, p, cur, kk)) == 0.0 and max(0, min(A + 1, kk + life) - max(y1, kk))
                                     for kk in invstep.get((y0, jot), ()) if kk <= A)
                    s = 0.0
                    # --- shaped: SUM(RTP_SHAPE(R,T,P,'1',J,JJ)$YK(TT,T), SUM((OBJ_SUMIV(K,R,T,P,JOT,LIFE),INVSTEP(K,JOT,LL,JOT),
                    #       SPAN(LIFE+MIN(ORD(LL)-ORD(YEAR),0)))$YK(ALLYEAR,LL),
                    #       SUM(OPYEAR(LIFE,AGE)$((ORD(LL)+ORD(AGE) > ORD(YEAR))$(ORD(LL)+ORD(AGE) < ORD(ALLYEAR)+2)),
                    #         SHAPE(J,AGE)*MULTI(JJ,LL+(ORD(AGE)-1))-1) * OBJ_FOM(R,LL,P,CUR)) * VAR_NCAP(R,T,P) / OBJ_DIVIV(R,T,P))
                    j = shape.get(k)
                    if j is not None:
                        for (y0, jot, life) in sumiv.get(k, ()):
                            for ll in invstep.get((y0, jot), ()):
                                if ll > A or life + min(ll - y1, 0) < 1:
                                    continue
                                f = X.get((r, p, cur, ll), 0.0)
                                if not f:
                                    # (EPS times a shape factor that is not 0 is EPS)
                                    e = e or (X.get((r, p, cur, ll)) == 0.0 and
                                              sum(SHP.get((j[0], a), 0.0) * MUL.get((j[1], ll + a - 1), 0.0) - 1
                                                  for a in range(1, life + 1) if y1 <= ll + a - 1 <= A) != 0)
                                    continue
                                s += f * sum(SHP.get((j[0], a), 0.0) * MUL.get((j[1], ll + a - 1), 0.0) - 1
                                             for a in range(1, life + 1) if y1 <= ll + a - 1 <= A)
                        c += s / diviv[k]
                    if c:
                        put(row + (t, p), c)
                    elif e:
                        eps(row + (t, p), 1.0 / diviv[k])
    db.load_rows("BC_NCAP", [(r, y1, y2, a, cur, str(t), p, x) for (r, y1, y2, a, cur, t, p), x in sorted(out.items())])


def variable_coefficients(db: DB, bc):
    """eqbndcst.mod 154-201: commodity taxes and subsidies (COMTAX, COMSUB) on VAR_COMNET / VAR_COMPRD, flow taxes and
    subsidies (FLOTAX, FLOSUB) on the flows.  The years of the range count with the pulse of %TPULSE%:
      VARCOST LIN:  (PERIODYR(T,Y),MILESTONYR(Y_EOH),YK(ALLYEAR,Y))$(YK(Y,YEAR)$TPULSE(Y_EOH,Y)), TPULSE(Y_EOH,Y)* cost(Y_EOH)
      otherwise:    (PERIODYR(T,Y_EOH),YK(ALLYEAR,Y_EOH))$YK(Y_EOH,YEAR), cost(Y_EOH)"""
    q = db.q
    lin = db.ctl["VARCOST"] == "LIN"
    py = {}
    for t, y in q("select y, y2 from PERIODYR where in_MILESTONYR(y)"):
        py.setdefault(int(t), []).append(int(y))
    yeoh = {int(y) for (y,) in q("select y from Y_EOH")}
    pulse = {}
    for t, y, v in q("select y, y2, value from TPULSE"):
        if v:
            pulse.setdefault(int(y), []).append((int(t), v))

    def weights(t, y1, A):
        """[(cost year, weight)] of period t within y1..A"""
        out = []
        for y in py.get(t, ()):
            if not (y1 <= y <= A):
                continue
            if lin:
                out += pulse.get(y, ())
            elif y in yeoh:
                out.append((y, 1.0))
        return out
    T = sorted(py)
    M = {int(y): v for y, v in q("select y, value from M")}
    LAGT = {int(y): v for y, v in q("select y, value from LAGT")}
    rows = bc["rows"]
    com = {}
    for tab, rhs, out in (("OBJ_COMNT", "RHS_COMBAL", "BC_COMNET"), ("OBJ_COMPD", "RHS_COMPRD", "BC_COMPRD")):
        vals = {}
        for r, y, c, s, kind, cur, v in q(f"select r, y, c, s, ucn, cur, value from {tab} where ucn in ('TAX','SUB')"):
            vals[(r, int(y), c, s, kind, cur)] = v
        if not vals:
            continue
        rhsk = {}
        for r, t, c, s in q(f"select r, y, c, s from {rhs}"):
            rhsk.setdefault(r, []).append((int(t), c, s))
        res = []
        for (r, y1s, y2s, cat, cur) in sorted(rows):
            if cat not in ("COMTAX", "COMSUB"):
                continue
            kind, sign = ("TAX", 1.0) if cat == "COMTAX" else ("SUB", -1.0)
            y1, A = int(y1s), int(y2s)
            acc = {}
            eps = set()
            for (t, c, s) in rhsk.get(r, ()):
                x = sum(w * vals.get((r, ye, c, s, kind, cur), 0.0) for (ye, w) in weights(t, y1, A))
                if x:
                    acc[(t, c, s)] = acc.get((t, c, s), 0.0) + sign * x
                elif any(w and vals.get((r, ye, c, s, kind, cur)) == 0.0 for (ye, w) in weights(t, y1, A)):
                    eps.add((t, c, s))                     # a tax or subsidy given as EPS: an EPS coefficient
            for k in eps:
                acc.setdefault(k, 0.0)
            res += [(r, y1s, y2s, cat, cur, str(t), c, s, x) for (t, c, s), x in sorted(acc.items()) if x or (t, c, s) in eps]
        db.load_rows(out, res)
    # --- SUM(T$(YK(TT,T)*(M(T)+LAGT(T) GT YEARVAL(YEAR))), SUM(RTPCS_VARF(R,T,P,C,S)$OBJ_VFLO(R,P,C,CUR,'TAX'),
    #       SUM(TS_ANN(S,TS), SUM(%TPULSE% MAX(0,OBJ_FTAX(R,Y_EOH,P,C,TS,CUR)))) * <the flow of (V,T,P,C,S), all vintages>))
    #     (FLOSUB: OBJ_VFLO(..,'SUB') and MAX(0,-OBJ_FTAX))
    if not any(cat in ("FLOTAX", "FLOSUB") for (_, _, _, cat, _) in rows):
        return
    ftax = {}
    for r, p, c, s, cur, y, v in q("select r, p, c, s, cur, y, value from OB_FTAX"):
        ftax[(r, p, c, s, cur, int(y))] = v
    vflo = {(r, p, c, cur, k) for r, p, c, cur, k in q("select r, p, c, cur, ucn from OBJ_VFLO")}
    tsann = {}
    for s, s2 in q("select s, s2 from TS_ANN"):
        tsann.setdefault(s, []).append(s2)
    varf = {}
    for r, t, p, c, s in q("select r, y, p, c, s from RTPCS_VARF"):
        varf.setdefault((r, int(t)), []).append((p, c, s))
    if db.card("IRE_FLOSUM"):
        aux = {(r, p, c) for r, p, c in q("select distinct r, p, c from IRE_FLOSUM")}
        if any((r, p, c, cur, k) in vflo for (r, p, c) in aux for (_, _, _, _, cur) in rows for k in ("TAX", "SUB")):
            unsupported(db, "flow tax bounds (REG_CUMCST FLOTAX / FLOSUB) on auxiliary flows of trade processes (IRE_FLOSUM)", ["IRE_FLOSUM"])
    res = []
    for (r, y1s, y2s, cat, cur), tts in sorted(rows.items()):
        if cat not in ("FLOTAX", "FLOSUB"):
            continue
        kind, sg = ("TAX", 1.0) if cat == "FLOTAX" else ("SUB", -1.0)
        y1, A = int(y1s), int(y2s)
        acc = {}
        for tt in tts:
            for t in T:
                if t > tt or not (M[t] + LAGT.get(t, 0.0) > y1):
                    continue
                w = weights(t, y1, A)
                for (p, c, s) in varf.get((r, t), ()):
                    if (r, p, c, cur, kind) not in vflo:
                        continue
                    x = sum(wt * max(0.0, sg * ftax.get((r, p, c, ts, cur, ye), 0.0)) for ts in tsann.get(s, ()) for (ye, wt) in w)
                    if x:
                        acc[(t, p, c, s)] = acc.get((t, p, c, s), 0.0) + x
                    elif any(wt and ftax.get((r, p, c, ts, cur, ye)) == 0.0 for ts in tsann.get(s, ()) for (ye, wt) in w):
                        acc.setdefault((t, p, c, s), 0.0)  # MAX(0,EPS) is EPS: a flow tax given as EPS, an EPS coefficient
        res += [(r, y1s, y2s, cat, cur, str(t), p, c, s, x) for (t, p, c, s), x in sorted(acc.items())]
    db.load_rows("BC_FLO", res)


def bounds(db: DB, bc):
    """bnd_cum.mod 43-48:  VAR_CUMCST.LO(..,COSTCAT,..)$REG_CUMCST(..,COSTCAT,..,'UP') = -INF  (an aggregate of COST_GMAP);
    VAR_CUMCST.UP $= REG_CUMCST(..,'UP');  .LO $= REG_CUMCST(..,'LO');  .FX $= REG_CUMCST(..,'FX')."""
    if bc is None:
        return
    db.x('create table if not exists "B_VAR_CUMCST" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, lower DOUBLE, upper DOUBLE)')
    cum = bc["cum"]
    rows = []
    for key in sorted({k[:5] for k in cum}):
        lo = -INF if (key[3] in AGGREGATES and key + ("UP",) in cum) else 0.0
        up = INF
        if key + ("UP",) in cum:
            up = cum[key + ("UP",)]
        if key + ("LO",) in cum:
            lo = cum[key + ("LO",)]
        if key + ("FX",) in cum:
            lo = up = cum[key + ("FX",)]
        rows.append(key + (lo, up))
    if rows:
        import pandas as pd
        db.con.register("bc_", pd.DataFrame(rows, columns=["d0", "d1", "d2", "d3", "d4", "lower", "upper"], dtype=object)
                        .astype({"lower": float, "upper": float}))
        db.x('insert into "B_VAR_CUMCST" select * from bc_')
        db.con.unregister("bc_")
    db.bounds.add("VAR_CUMCST")
