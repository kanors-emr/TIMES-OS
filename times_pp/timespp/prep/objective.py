# SPDX-License-Identifier: GPL-3.0-or-later
"""Objective preprocessing, for both forms of the objective:
eqobj.mod preamble, eqobjinv.mod, eqobjfix.mod, eqobsalv.mod (preprocessing parts), coef_alt.lin INV/FIX
and the COEF section of eqobjann.tm  ->  OBJ_ICUR, OBJ_FCUR, OBJSCC, ...; COEF_OBINV, COEF_OBFIX for the annualised form
(OBJANN=YES); OBJ_CINV, OBJ_CFIX for the standard form (the sums TIMES writes inside EQ_OBJINV and EQ_OBJFIX).

Written procedurally (years and ages as integers) because the GAMS code works with lags over the
year and age sets.  Covers the OBLONG objective (CTST = '**0') with investment lead times (cases 2a / 2b),
past investments, the salvage shares needed for early retirement, and decommissioning costs (NCAP_DCOST, with
NCAP_DLAG, NCAP_DLIFE, NCAP_DELIF) and the cost of the decommissioning delay (NCAP_DLAGC); shape curves on fixed
taxes and subsidies stop with NotPorted.
"""
import math
import sys
import time
from dataclasses import dataclass
from .. import kernels
from ..controls import unsupported
from ..engine import DB
from .common import require_empty, rnd
from . import bndcst, stochastic


def objann(db: DB):
    """$SET OBJANN YES: the annualised objective of eqobj.mod 70 (eqobjann.tm)"""
    return str(db.env.get("OBJANN", "")).strip("'\"").upper() == "YES"


def annualised(db: DB):
    """The coefficients of the annualised costs (eqobjann.tm, COEF_OBINV / COEF_OBFIX): with OBJANN YES (eqobj.mod 70)
    and in TIMES-MACRO, whose objective (eqobj.tm 44) always takes them; MLF opens it (readbprice.mod 20)."""
    from . import mlf
    return objann(db) or mlf.on(db)


def objective_coefficients(db: DB):
    """The objective's coefficients. The Julia kernel `objective` (jlkernels/src/objective.jl; a default kernel,
    kernels.py) computes the same tables; the Python below is its reference."""
    # Python's cyclic garbage collector paused for the step: it builds millions of small tuples that live to its end,
    # and each full collection walks all of them again (10% of the step on a large model); nothing here needs it (the few
    # reference cycles, the nested functions' closures, are collected after)
    import gc
    on = gc.isenabled()
    gc.disable()
    try:
        if kernels.mode("objective") == "off" or ("OBJ_SIC" in db.sym and db.card("OBJ_SIC")):
            _objective(db)                  # (OBJ_CSIC is made only here)
        else:
            _objective_switch(db)
    finally:
        if on:
            gc.enable()


def _objective(db: DB):
    I = _inputs(db)
    V = _investment(db, I)
    F = _fixed_costs(db, I, V)
    X = eoh(db, I, V, F, db.s["MIYR_VL"], I.Y_EOH, F.objlife)
    _write_tables(db, I, V, F, X)


@dataclass(frozen=True, slots=True)
class Inputs:
    """What the objective reads, loaded once (_inputs): the switches of its form, the years, the process vintages,
    lifetimes and rates, discounting, the cost attributes and the shape curves.  The record is frozen, the tables in
    it are not: the investment stage corrects NCAP_TLIFE, NCAP_ELIFE, NCAP_DLIFE and NCAP_DELIF in place
    (eqobjinv.mod lines 65-68), and every later stage reads the corrected values."""
    # the form of the objective (CTST '' or OBLONG), OBJANN=YES, ANNCOST=LEV, the discounting shift of MID_YEAR
    classic: bool
    annual: bool
    lev: bool
    DS: float
    # years: ALLYEAR, EACHYEAR, K_EOH, Y_EOH, MILESTONYR, PASTMILE, PYR_S; B, E, M, D, IPD by period
    ALL: set
    K: set
    K_EOH: set
    Y_EOH: set
    T: set
    PASTMILE: set
    PYR_S: set
    B: dict
    E: dict
    M: dict
    D: dict
    IPD: dict
    YEARS: set
    # the vintages: RTP (sorted by the labels), as a set, RTP_OFF
    rtp: list
    rtpset: set
    off: set
    # by (r, v, p): lifetimes, past investments, rates, lead times (iled: the vintages with NCAP_ILED)
    TLIFE: dict
    ELIFE: dict
    RPTI: dict
    PASTI: dict
    DLIFE: dict
    DELIF: dict
    DLAG: dict
    NDR: dict
    FDR: dict
    ILED: dict
    CILED: dict
    iled: set
    # by (r, y, cur): OBJ_DISC, G_DRATE, OBJ_RFR, OBJ_PVT; RDCUR by region
    DISC: dict
    GDR: dict
    RFR: dict
    PVT: dict
    rdcur: dict
    # by (r, p, cur, y): the OB_* cost tables, the net investment and fixed costs, and their lookups by (r, y, p, cur)
    ICO: dict
    ISU: dict
    ITX: dict
    FOM: dict
    FSB: dict
    FTX: dict
    DCC: dict
    ICOST: dict
    FOMC: dict
    dcost: object
    icost: object
    fom: object
    icost_rec: object
    fom_rec: object
    # PRC_RESID, COEF_CPT by vintage and its sum with OBJ_PVT (cptpv, kept by argument), VNT, CARD(AGE)
    resid0: set
    resid: dict
    cpt: object
    cptpv: object
    vnt: dict
    nage: int
    # the shapes (NCAP_CPX and RTP_CPX, NCAP_FOMX/FTAXX/FSUBX, NCAP_FOMM/FTAXM/FSUBM, SHAPE, MULTI), PERIODYR
    CPX: set
    RCPX: dict
    FOMX: dict
    TAXX: dict
    SUBX: dict
    FOMM: dict
    TAXM: dict
    SUBM: dict
    SHP: dict
    MUL: dict
    period_of: dict
    # the loaders of years and of OB_* tables, for the tables a later stage reads itself
    yr: object
    ob: object


def _inputs(db: DB) -> Inputs:
    """The objective's inputs: the checks for the forms that are not ported, two set changes of eqobjinv.mod (line 52,
    RTP of past vintages without NCAP_PASTI) and eqobj.mod (line 17, K_EOH), and the tables loaded into Python, once,
    for the stages that follow."""
    s, ctl = db.s, db.ctl
    # Two forms are ported: OBLONG (CTST '**0') and the classic objective of OBJ AUTO without OBLONG (CTST '', ALTOBJ 1).
    # With CTST '' TIMES skips coef_alt.lin INV and FIX: no OBJ_JD / OBJ_WD factors (%CAPJD% and %CAPWD% are empty),
    # INVSPRED is the plain INVSTEP, and the divisors are those of eqobjinv.mod / eqobjfix.mod.
    classic = ctl["CTST"] == ""
    if not ((ctl["OBLONG"] and ctl["CTST"] == "zero") or (classic and ctl["OBJ"] in ("AUTO", "") and s["ALTOBJ"] in (0, 1))):
        unsupported(db, "objective preprocessing for objective variants other than OBLONG and OBJ AUTO without OBLONG")
    if classic and db.ctl.get("TIMESTEP"):
        unsupported(db, "a myopic run (TIMESTEP) with the classic objective (OBJ AUTO without OBLONG)")
    # The coefficients of both forms of the objective are prepared: the annualised one (OBJANN=YES: COEF_OBINV,
    # COEF_OBFIX of eqobjann.tm) and the standard one, whose sums TIMES writes inside EQ_OBJINV and EQ_OBJFIX
    # (stored here as OBJ_CINV and OBJ_CFIX, per unit of capacity).  The set OBJANN tells the equations which to state.
    annual = annualised(db)
    lev = str(db.env.get("ANNCOST", "")).strip().strip("'\"").upper() == "LEV"
    require_empty(db, ["RTP_CAPVL"], "RTP_CAPVL (objective preprocessing)")
    DS = 0.5 if ctl["MID_YEAR"] else 0.0
    # --- RTP(R,PASTMILE,P)$(NCAP_PASTI(R,PASTMILE,P)=0) = NO;
    db.remove("RTP", where="in_PASTMILE(y) and v_NCAP_PASTI(r,y,p) = 0")
    # K_EOH includes the past years: it links to the past vintages (eqobj.mod line 16)
    # --- K_EOH(EACHYEAR)$((YEARVAL(EACHYEAR) >= PYR_V1) * (YEARVAL(EACHYEAR) <= MIYR_VL)) = YES;
    db.assign("K_EOH", "select y from EACHYEAR where yv(y) >= {PYR_V1} and yv(y) <= {MIYR_VL}")
    q = db.q
    yr = lambda sql: {int(y) for (y,) in q(sql)}
    ALL, K, K_EOH, Y_EOH = yr("select y from ALLYEAR where y<>'0'"), yr("select y from EACHYEAR"), yr("select y from K_EOH"), yr("select y from Y_EOH")
    T, PASTMILE, PYR_S = yr("select y from MILESTONYR"), yr("select y from PASTMILE"), yr("select y from PYR_S")
    par = lambda n: {int(y): v for y, v in q(f"select y, value from {n}")}
    ipar = lambda n: {y: (int(v) if float(v).is_integer() else v) for y, v in par(n).items()}
    B, E, M, D, IPD = ipar("B"), ipar("E"), ipar("M"), ipar("D"), ipar("IPD")
    # the large tables come as columns (_cols: half the time of q's tuples), the years as integers from DuckDB (sorted
    # as before, by the labels)
    rtp = list(zip(*_cols(db, "select t.r, cast(t.y as integer) as y, t.p from RTP t order by t.r, t.y, t.p", 3)))
    rtpset = set(rtp)
    p3 = lambda n: (lambda c: dict(zip(zip(*c[:3]), c[3])))(_cols(db, f"select r, cast(y as integer) as y, p, value from {n}", 4))
    TLIFE, ELIFE, RPTI, PASTI = p3("NCAP_TLIFE"), p3("NCAP_ELIFE"), p3("COEF_RPTI"), p3("NCAP_PASTI")
    DLIFE, DELIF, DLAG = p3("NCAP_DLIFE"), p3("NCAP_DELIF"), p3("NCAP_DLAG")
    NDR, FDR = p3("NCAP_DRATE"), p3("NCAP_FDR")
    ILED, CILED = p3("NCAP_ILED"), p3("COEF_ILED")          # an EPS lead time is a record with value 0
    iled = set(ILED)
    YEARS = ALL
    off = set(zip(*_cols(db, "select r, cast(y as integer) as y, p from RTP_OFF", 3)))
    rc = lambda n: {(r, int(y), cur): v for r, y, cur, v in q(f"select r, y, cur, value from {n}")}
    DISC, GDR, RFR, PVT = rc("OBJ_DISC"), rc("G_DRATE"), rc("OBJ_RFR"), rc("OBJ_PVT")
    rdcur = {}
    for r, cur in q("select r, cur from RDCUR order by all"):
        rdcur.setdefault(r, []).append(cur)
    ob = lambda n: (lambda c: dict(zip(zip(*c[:4]), c[4])))(_cols(db, f"select r, p, cur, cast(y as integer) as y, value from {n}", 5))
    ICO, ISU, ITX, FOM, FSB, FTX = (ob(n) for n in ("OB_ICOST", "OB_ISUB", "OB_ITAX", "OB_FOM", "OB_FSB", "OB_FTX"))
    DCC = ob("OB_DCC")                                          # OBJ_DCOST(r,y,p,cur) = OB_DCC(r,p,cur,y)
    dcost = lambda r, k, p, cur: DCC.get((r, p, cur, k), 0.0)
    # OBJ_ICOST+OBJ_ITAX-OBJ_ISUB and OBJ_FOM+OBJ_FTX-OBJ_FSB, once per record of any of the three (_net); a key in
    # neither is a cost of 0 with no record
    ICOST, FOMC = _net(ICO, ITX, ISU), _net(FOM, FTX, FSB)
    icost = lambda r, k, p, cur: ICOST.get((r, p, cur, k), 0.0)
    fom = lambda r, k, p, cur: FOMC.get((r, p, cur, k), 0.0)
    # a cost given as EPS keeps its record through the sums (EPS*x = EPS): the result is then stored as EPS
    # (OBJ_FOM(R,K,P,CUR)+OBJ_FTX(R,K,P,CUR)-OBJ_FSB(R,K,P,CUR)): a tax that cancels a cost leaves 0, no record (_on_record)
    icost_rec = lambda r, k, p, cur: _on_record(ICOST, ICO, ITX, ISU, (r, p, cur, k))
    fom_rec = lambda r, k, p, cur: _on_record(FOMC, FOM, FTX, FSB, (r, p, cur, k))
    resid0 = {(r, p) for r, p in q("select r, p from PRC_RESID where y='0'")}
    resid = {(r, int(y), p): v for r, y, p, v in q("select r, y, p, value from PRC_RESID where y<>'0'")}
    # COEF_CPT(r,v,t,p) by vintage: the periods and values of each (r, v, p) as slices of the columns, sorted by the
    # labels (r, v, p, then t: each vintage's periods in the order of COEF_CPT's sort by all)
    cr_, cv_, cp_, ct_, cx_ = _cols(db, """select t.r, cast(t.y as integer) as y, t.p, cast(t.y2 as integer) as y2, t.value
                                           from COEF_CPT t order by t.r, t.y, t.p, t.y2""", 5)
    cpt = _Slices(list(zip(cr_, cv_, cp_)), ct_, cx_)
    cr_ = cv_ = cp_ = None
    # --- SUM(T, COEF_CPT(R,V,T,P)*OBJ_PVT(R,T,CUR)) (the denominators of COEF_OBINV and COEF_OBFIX): once per vintage
    #     and currency, the periods in COEF_CPT's order
    pvt_rc = {}
    for (r, t, cur), x in PVT.items():
        pvt_rc.setdefault((r, cur), {})[t] = x
    cpv = {}

    def cptpv(r, v, p, cur):
        x = cpv.get((r, v, p, cur))
        if x is None:
            pv = pvt_rc.get((r, cur), {})
            x = cpv[(r, v, p, cur)] = sum(val * pv.get(t, 0.0) for t, val in cpt.get((r, v, p), ()))
        return x
    vnt = {}
    for v, t in q("select y, y2 from VNT order by all"):
        vnt.setdefault(int(v), []).append(int(t))
    nage = db.card("AGE")
    # shapes on capacity (NCAP_CPX, coef_shp.mod): RTP_CPX(r,v,p,t) is the relative change of COEF_CPT in period t
    CPX = {(r, int(y), p) for r, y, p, v in q("select r, y, p, value from NCAP_CPX where y <> '0'") if v}
    RCPX = {(r, int(v), p, int(t)): x for r, v, p, t, x in q("select r, y, p, y2, value from RTP_CPX")}
    # shapes on the fixed O&M cost by age (NCAP_FOMX); a value of 0 is an EPS record (pointer extrapolated without data)
    FOMX = {(r, int(y), p): v for r, y, p, v in q("select r, y, p, value from NCAP_FOMX where y <> '0'")}
    # and on the fixed taxes and subsidies (NCAP_FTAXX, NCAP_FSUBX)
    TAXX = {(r, int(y), p): v for r, y, p, v in q("select r, y, p, value from NCAP_FTAXX where y <> '0'")}
    SUBX = {(r, int(y), p): v for r, y, p, v in q("select r, y, p, value from NCAP_FSUBX where y <> '0'")}
    # the pointers to the MULTI curves by year of the same three (NCAP_FOMM, NCAP_FTAXM, NCAP_FSUBM)
    FOMM = {(r, int(y), p): v for r, y, p, v in q("select r, y, p, value from NCAP_FOMM where y <> '0'")}
    TAXM = {(r, int(y), p): v for r, y, p, v in q("select r, y, p, value from NCAP_FTAXM where y <> '0'")}
    SUBM = {(r, int(y), p): v for r, y, p, v in q("select r, y, p, value from NCAP_FSUBM where y <> '0'")}
    shapes = CPX or FOMX or TAXX or SUBX or FOMM or TAXM or SUBM
    SHP = {(int(j), int(a)): x for j, a, x in q("select j, age, value from SHAPE")} if shapes else {}
    MUL = {(int(j), int(y)): x for j, y, x in q("select j, y, value from MULTI")} if shapes else {}
    period_of = {int(y): int(t) for t, y in q("select y, y2 from PERIODYR where in_MILESTONYR(y)")}
    return Inputs(
        classic=classic, annual=annual, lev=lev, DS=DS, ALL=ALL, K=K, K_EOH=K_EOH, Y_EOH=Y_EOH, T=T,
        PASTMILE=PASTMILE, PYR_S=PYR_S, B=B, E=E, M=M, D=D, IPD=IPD, YEARS=YEARS, rtp=rtp, rtpset=rtpset, off=off,
        TLIFE=TLIFE, ELIFE=ELIFE, RPTI=RPTI, PASTI=PASTI, DLIFE=DLIFE, DELIF=DELIF, DLAG=DLAG, NDR=NDR, FDR=FDR,
        ILED=ILED, CILED=CILED, iled=iled, DISC=DISC, GDR=GDR, RFR=RFR, PVT=PVT, rdcur=rdcur, ICO=ICO, ISU=ISU,
        ITX=ITX, FOM=FOM, FSB=FSB, FTX=FTX, DCC=DCC, ICOST=ICOST, FOMC=FOMC, dcost=dcost, icost=icost, fom=fom,
        icost_rec=icost_rec, fom_rec=fom_rec, resid0=resid0, resid=resid, cpt=cpt, cptpv=cptpv, vnt=vnt, nage=nage, CPX=CPX, RCPX=RCPX,
        FOMX=FOMX, TAXX=TAXX, SUBX=SUBX, FOMM=FOMM, TAXM=TAXM, SUBM=SUBM, SHP=SHP, MUL=MUL, period_of=period_of,
        yr=yr, ob=ob)


@dataclass(frozen=True, slots=True)
class Investment:
    """The investment stage (_investment): the vintages with investment or decommissioning costs, their lives,
    discount corrections and divisors, and the years of their payments.  _dofix in the fixed-cost stage adds to
    invspred, jd and wd in place (coef_alt.lin DOFIX: the spreads and weights of the fixed-cost steps)."""
    # OBJ_ICUR (r, v, p, cur); OBJ_YES (r, v, p); OB_DLC (OBJ_DLAGC) and its vintages; OBJ_FCUR (eqobjfix.mod line 35)
    icur: list
    yes: set
    DLC: dict
    dlc_v: set
    fcur: list
    # COR_SALVI, OBJ_CRF, OBJ_PASTI by (r, v, p, cur); MAXLIFE
    cor: dict
    crf: dict
    opasti: dict
    maxlife: int
    # the cases OBJ_1A, OBJ_1B, OBJ_2A, OBJ_2B of a vintage, and the first year and years of a spread of OBJ_1A
    is1a: object
    is1b: object
    is2a: object
    is2b: object
    start: object
    # OBJ_SUMII by vintage, [(LIFE, K, JOT)]; INVSTEP of a set of (K, JOT); FIL (B of each period)
    sumii: dict
    steps: object
    FILB: set
    # INVSPRED by (K, JOT), OBJ_JD, OBJ_WD, and the factors as the sums read them (1 with CTST '')
    invspred: dict
    jd: dict
    wd: dict
    JDf: object
    WDf: object
    # OBJ_DIVI, OBJ_DIVIII by vintage; OBJ_SUMIII by vintage, [(LL, K, Y)]
    divi: dict
    diviii: dict
    sumiii: dict


def _investment(db: DB, I: Inputs) -> Investment:
    """The investment costs, eqobjinv.mod lines 53-272 with coef_alt.lin INV (DOINV, lines 89-103, then DOFIX to
    line 118): the vintages with costs (OBJ_ICUR, OBJ_SUMS3, OBJ_YES), the corrections of small lives, COR_SALVI,
    OBJ_CRF and OBJ_PASTI, OPYEAR, the cases 1a / 1b / 2a / 2b, the investment steps and their spreads (OBJ_SUMII,
    INVSTEP, INVSPRED, OBJ_JD), interest during construction and OBJ_DIVI, and the decommissioning spreads
    (OBJ_DIVIII, OBJ_SUMIII).  Also OBJ_FCUR (eqobjfix.mod line 35), whose records are read here."""
    s, q = db.s, db.q
    classic, DS, ALL, K, K_EOH, T, PASTMILE, PYR_S = I.classic, I.DS, I.ALL, I.K, I.K_EOH, I.T, I.PASTMILE, I.PYR_S
    B, E, M, D, IPD, YEARS, rtp, rtpset, off = I.B, I.E, I.M, I.D, I.IPD, I.YEARS, I.rtp, I.rtpset, I.off
    TLIFE, ELIFE, RPTI, PASTI, DLIFE, DELIF, DLAG = I.TLIFE, I.ELIFE, I.RPTI, I.PASTI, I.DLIFE, I.DELIF, I.DLAG
    NDR, ILED, CILED, iled, DISC, GDR, RFR, PVT = I.NDR, I.ILED, I.CILED, I.iled, I.DISC, I.GDR, I.RFR, I.PVT
    rdcur, DCC, ICOST, FOMC, resid, cpt, vnt, nage = I.rdcur, I.DCC, I.ICOST, I.FOMC, I.resid, I.cpt, I.vnt, I.nage
    yr, ob = I.yr, I.ob
    # ------------------------------------------------------------------ eqobjinv.mod
    # --- OBJ_ICUR(RTP(R,V,P),CUR)$(OBJ_ICOST + OBJ_ISUB + OBJ_ITAX) = YES;  OBJ_ICUR(RTP_OFF,CUR)$(NOT NCAP_PASTI(RTP_OFF)) = NO;
    #     (a cost of EPS counts: the test is on the record)
    # --- OBJ_ICUR(RTP(R,V,P),CUR)$OBJ_DCOST(R,V,P,CUR) = YES;                                      (decommissioning)
    #     LOOP(CUR,OBJ_SUMS3(RTP(R,V,P))$OBJ_DCOST(R,V,P,CUR) = YES);   OPTION OBJ_YES < OBJ_ICUR; OBJ_YES(OBJ_SUMS3) = YES;
    icrec = ICOST.keys() | DCC.keys()                          # the records of ICOST, ISUB, ITAX and DCOST
    icur = [(r, v, p, cur) for (r, v, p) in rtp for cur in rdcur.get(r, ())
            if (r, p, cur, v) in icrec and not ((r, v, p) in off and (r, v, p) not in PASTI)]
    sums3 = {(r, v, p) for (r, p, cur, v) in DCC if (r, v, p) in rtpset}
    # --- LOOP((RTP,COM)$NCAP_OCOM(RTP,COM),OBJ_SUMS3(RTP) = YES);
    sums3 |= {(r, int(v), p) for r, v, p in q("select distinct r, y, p from NCAP_OCOM") if (r, int(v), p) in rtpset}
    # eqobsalv.mod LATE REVENUES: NCAP_VALU on NCAP_OCOM flows (not ported)
    if db.q1("select count(*) from NCAP_VALU v where exists(select 1 from NCAP_OCOM o where o.r=v.r and o.p=v.p and o.c=v.c)"):
        unsupported(db, "late revenues of decommissioning flows (NCAP_VALU with NCAP_OCOM, eqobsalv.mod)", ["NCAP_VALU"])
    yes = {k[:3] for k in icur} | sums3
    # Small lives are corrected because their rounded values are used as divisors (eqobjinv.mod line 65)
    # --- NCAP_DLIFE(OBJ_SUMS3(R,V,P))$(ROUND(NCAP_DLIFE(R,V,P)) LE 0) = 1;  NCAP_DELIF(OBJ_SUMS3(R,V,P)) = MAX(1,NCAP_DELIF(R,V,P));
    for k in sums3:
        if rnd(DLIFE.get(k, 0.0)) <= 0:
            DLIFE[k] = 1.0
        DELIF[k] = max(1.0, DELIF.get(k, 0.0))
    if sums3:
        db.x("create or replace temp table t_dl (r VARCHAR, y VARCHAR, p VARCHAR, dl DOUBLE, de DOUBLE)")
        db.insert_rows("t_dl", [(r, str(v), p, DLIFE[(r, v, p)], DELIF[(r, v, p)]) for r, v, p in sums3])
        db.put("NCAP_DLIFE", "select r, y, p, dl as value from t_dl")
        db.put("NCAP_DELIF", "select r, y, p, de as value from t_dl")
    # --- NCAP_TLIFE(OBJ_YES(R,V,P))$(ROUND(NCAP_TLIFE(R,V,P)) LE 0) = 1;   same for NCAP_ELIFE
    for tab, d in (("NCAP_TLIFE", TLIFE), ("NCAP_ELIFE", ELIFE)):
        fix = [k for k in yes if rnd(d.get(k, 0.0)) <= 0]
        for k in fix:
            d[k] = 1.0
        if fix:
            db.x("create or replace temp table t_fix (r VARCHAR, y VARCHAR, p VARCHAR)")
            db.insert_rows("t_fix", [(r, str(v), p) for r, v, p in fix])
            db.put(tab, "select r, y, p, 1 as value from t_fix")
    # --- OBJ_I2(RTP)$NCAP_ILED(RTP) = YES;
    # --- OBJ_FCUR(RTP(R,V,P),CUR)$OBJ_DLAGC(R,V,P,CUR) = YES;                        (eqobjfix.mod 35, decommissioning)
    DLC = ob("OB_DLC")                                          # OBJ_DLAGC(r,y,p,cur) = OB_DLC(r,p,cur,y)
    dlc_v = {(r, v, p) for (r, p, cur, v) in DLC}
    fcur = [(r, v, p, cur) for (r, v, p) in rtp for cur in rdcur.get(r, ()) if (r, p, cur, v) in FOMC or (r, p, cur, v) in DLC]
    i2 = lambda k: k in iled
    # COR_SALVI corrects for a technology-specific discount rate (NCAP_DRATE) and the discounting shift, so OBJ_CRF
    # is based on G_DRATE (eqobjinv.mod lines 74-81)
    # --- COR_SALVI;  COR_SALVI(OBJ_ICUR(OBJ_I2(R,V,P),CUR)) = COR_SALVI(R,V,P,CUR) / ((1+G_DRATE(R,V,CUR))**%DISCSHIFT%);  OBJ_CRF
    cor, crf, opasti = {}, {}, {}
    PASTYEAR = yr("select y from PASTYEAR")
    # (the same rates and lives recur on most vintages: each factor below is computed once per distinct argument,
    #  by the same expression, so with the same rounding)
    corx = _memo(lambda ndr, rf, el: (((1 + ndr) / (1 + rf)) ** DS * ((1 - 1 / (1 + ndr)) * (1 - (1 + rf) ** (-el))) /
                                      ((1 - 1 / (1 + rf)) * (1 - (1 + ndr) ** (-el))) - 1))
    pds = _memo(lambda dr: (1 + dr) ** DS)
    crfa = _memo(lambda dr: (1 - 1 / (1 + dr)))
    crfb = _memo(lambda dr, el: (1 - (1 + dr) ** (-el)))
    for (r, v, p, cur) in icur:
        dr, ndr, rf, el = GDR.get((r, v, cur), 0.0), NDR.get((r, v, p), 0.0), RFR.get((r, v, cur), 0.0), ELIFE.get((r, v, p), 0.0)
        x = 0.0
        if ndr > 0:
            # (OBJ_RFR is positive here: the discount rate, at least 1E-11, unless a positive risk-free rate replaces it)
            x = corx(ndr, rf, el)
        c_ = (x + 1) * pds(dr)
        if i2((r, v, p)):
            c_ = c_ / pds(dr)
        cor[(r, v, p, cur)] = c_
        crf[(r, v, p, cur)] = c_ * crfa(dr) / crfb(dr, rnd(el))
        # --- OBJ_PASTI(OBJ_ICUR(RTP(R,PASTYEAR(V),P),CUR)) = NCAP_PASTI(R,V,P) *
        #        MAX(0,MIN(1,(((1+G_DRATE)**(YEARVAL(V)+ROUND(NCAP_ILED(R,V,P))-MINYR+NCAP_ELIFE(R,V,P))-1) / ((1+G_DRATE)**NCAP_ELIFE(R,V,P)-1))));
        if v in PASTYEAR:
            f = max(0.0, min(1.0, ((1 + dr) ** (v + rnd(ILED.get((r, v, p), 0.0)) - s["MINYR"] + el) - 1) / ((1 + dr) ** el - 1)))
            w = PASTI.get((r, v, p), 0.0) * f
            # nothing when the economic life ended before the horizon (factor 0); NCAP_PASTI = EPS gives EPS otherwise
            if w or (f and (r, v, p) in PASTI):
                opasti[(r, v, p, cur)] = w
    # --- MAXLIFE = MAX(SMAX(T,2*D(T)),Z,CEIL(MAXLIFE));  OPYEAR(LIFE,AGE)$((ORD(AGE) LE ORD(LIFE))$(ORD(LIFE) LE MAXLIFE)) = YES;
    z = max([E[t] for (r, v, p) in rtp if v in PYR_S for t in T if resid.get((r, t, p), 0.0)], default=float("-inf")) - s["MIYR_V1"] + 2
    s["MAXLIFE"] = maxlife = max(max(2 * D[t] for t in T), z, math.ceil(s["MAXLIFE"]))
    db.add("OPYEAR", f"""select a.age, b.age as age2 from AGE a, AGE b
                         where cast(b.age as INTEGER) <= cast(a.age as INTEGER) and cast(a.age as INTEGER) <= {maxlife}""")
    # --- OBJ_1A(RTP(R,V,P))$((NOT OBJ_I2(R,V,P))$(COEF_RPTI(R,V,P) LT 1.01)) = YES;   OBJ_1B: the other milestone vintages
    is1a = lambda k: (not i2(k)) and RPTI.get(k, 0.0) < 1.01
    is1b = lambda k: (not i2(k)) and not is1a(k) and k[1] in T
    is2a = lambda k: i2(k) and RPTI.get(k, 0.0) <= 1          # OBJ_2A(OBJ_I2(R,V,P))$(COEF_RPTI(R,V,P) LE 1) = YES;
    is2b = lambda k: i2(k) and not is2a(k) and k[1] in T        # OBJ_2B(OBJ_I2(R,T,P))$(NOT OBJ_2A(R,T,P)) = YES;
    db.assign("OBJ_1A", "select r, y, p from RTP where v_COEF_RPTI(r,y,p) < 1.01 and not in_NCAP_ILED(r,y,p)")
    db.assign("OBJ_1B", "select r, y, p from RTP where in_MILESTONYR(y) and not in_OBJ_1A(r,y,p) and not in_NCAP_ILED(r,y,p)")
    db.assign("OBJ_2A", "select r, y, p from RTP where in_NCAP_ILED(r,y,p) and v_COEF_RPTI(r,y,p) <= 1")
    db.assign("OBJ_2B", "select r, y, p from RTP where in_MILESTONYR(y) and in_NCAP_ILED(r,y,p) and not in_OBJ_2A(r,y,p)")
    start = lambda v: (M[v] - (IPD[v] - 1), int(IPD[v])) if v in T else (B[v], 1)       # first year and number of years of the investment spread

    def spreads(k):
        """(first year, number of years) of each investment step of a vintage (OBJ_SUMII without the LIFE index)."""
        r, v, p = k
        if i2(k):
            # Cases 2a / 2b: one payment in the commissioning year; the lead time enters through OBJ_DIVI (interest during construction)
            #   OBJ_IDC(R,V,P,LIFE,LL+MY_F,AGE+MAX(0,Z-1)) with Z = NCAP_ILED, MY_F = B(V)-YEARVAL(V)+Z            (2a)
            #   MY_F = ROUND(B(T)+(OBJ_C-1)*NCAP_TLIFE(R,T,P))-YEARVAL(T)+Z, OBJ_C = 1 TO COEF_RPTI                  (2b)
            #   OBJ_SUMII(R,V,P,LIFE,LL,JOT+(1-ORD(JOT)))$OBJ_IDC(R,V,P,LIFE,LL,JOT) = YES;
            return [(y0, 1) for (y0, _j) in idc(k)]
        if is1a(k):
            st = start(v)
            return [st] if st[0] in K else []
        if v not in T:
            return []
        zz = TLIFE[k]
        # --- IF((ROUND(Z)-IPD(T)%CTST%) LE 0, F = B(T) - %ZHALF% - YEARVAL(T); ...  ELSE CNT = %ISTEP%; ...
        #     ZHALF: CEIL(Z/2-.5) (CTST '') or FLOOR(ROUND(Z)/2); ISTEP: IPD(T) (CTST '') or MIN(IPD(T),ROUND(Z))
        if rnd(zz) - (IPD[v] if classic else 1) <= 0:
            out = [(B[v] - (math.ceil(zz / 2 - .5) if classic else rnd(zz) // 2), int(rnd(RPTI[k] * zz) - 1) + 1)]
        else:
            cnt = IPD[v] if classic else min(IPD[v], rnd(zz))
            #     F = B(T)-YEARVAL(T)-FLOOR(CNT/2); FOR(OBJ_C = 1 TO COEF_RPTI, OBJ_SUMII(R,T,P,LIFE,K(LL+F),AGE+CNT) = YES; F = F+Z)
            #     Z = NCAP_TLIFE is not rounded: F can be a half-integer, and GAMS rounds the lag F (half away from zero),
            #     so F = -0.5 points to the year before T (TLIFE 7.5 in a 10-year period: second step in 2029, not 2030)
            f, out = B[v] - int(v) - math.floor(cnt / 2), []
            for _ in range(int(math.floor(RPTI[k]))):
                out.append((int(v) + rnd(f), int(cnt)))
                f += zz
        return [(y0, jot) for (y0, jot) in out if y0 in K]

    def idc(k):
        """Commissioning years and construction spans (OBJ_IDC) of a vintage with a lead time."""
        r, v, p = k
        zl = ILED.get(k, 0.0)
        if is2a(k):
            #     LL+MY_F: GAMS rounds the non-integer lag MY_F itself (ROUND: half away from zero), not the year it points to
            out = [(int(v) + rnd(B[v] - int(v) + zl), int(1 + max(0, rnd(zl) - 1)))]
        elif is2b(k):
            out = [(int(v) + rnd(rnd(B[v] + (c - 1) * TLIFE[k]) - int(v) + zl), int(1 + max(0, rnd(zl) - 1)))
                   for c in range(1, int(math.floor(RPTI[k])) + 1)]
        else:
            out = []
        return [(y0, j) for (y0, j) in out if y0 in YEARS]

    sumii = {}
    for k in yes:
        life = 1 + max(0, rnd(min(nage, ELIFE.get(k, 0.0))) - 1)
        sumii[k] = [(life, y0, jot) for y0, jot in spreads(k) if 1 <= jot <= nage]
    # --- OPTION KAGE < OBJ_SUMII;  INVSTEP(KAGE(LL,JOT),LL+(ORD(AGE)-1),..)$OPYEAR(JOT,AGE) = YES;
    steps = lambda keys: {(k0, jot): [y for y in range(int(k0), int(k0) + jot) if y in ALL] for (k0, jot) in keys if jot <= maxlife}
    invstep = steps({(k0, jot) for lst in sumii.values() for (_, k0, jot) in lst})
    FILB = {B[t] for t in T}
    invspred, jd, wd = {}, {}, {}
    JDf = (lambda key: 1.0) if classic else (lambda key: jd.get(key, 0.0))     # %CAPJD% / %CAPWD% empty with CTST ''
    WDf = (lambda key: 1.0) if classic else (lambda key: wd.get(key, 0.0))

    # --- coef_alt.lin INV:  OBJ_JD(RDCUR(R,CUR),K,JOT)$KAGE(K,JOT) = 1;  OBJ_DIVI
    kage0 = {(k0, jot) for lst in sumii.values() for (_, k0, jot) in lst}
    for r, curs in (() if classic else rdcur.items()):
        for cur in curs:
            for (k0, jot) in kage0:
                if k0 in K:
                    jd[(r, cur, k0, jot)] = 1.0
    # --- interest during construction for any fractional ILED (eqobjinv.mod):
    #     LOOP(OBJ_ICUR(OBJ_I2(R,V,P),CUR), Z = COEF_ILED(R,V,P);
    #       IF(Z, OBJ_C=1+G_DRATE(R,V,CUR); MY_F=0; F=0;
    #         LOOP(OBJ_IDC(R,V,P,LIFE,LL,JOT), CNT=ORD(JOT);
    #           MY_F=MY_F+SUM((OPYEAR(JOT,AGE),YEAR(LL-ORD(AGE))),OBJ_DISC(R,YEAR,CUR)); F=F+OBJ_DISC(R,LL,CUR));
    #         MY_F = MY_F/F/CNT-1;  F = ((OBJ_C**CNT)-1)/(1-1/OBJ_C)/CNT-1;  CNT = MAX(1.E-5,Z);  Z = ((OBJ_C**CNT)-1)/(1-1/OBJ_C)/CNT-1;
    #       ELSE F=1); OBJ_DIVI(R,V,P) = 1/(1+Z*MY_F/F));
    divi = {}
    my_f = 0.0
    for (r, v, p, cur) in icur:
        k = (r, v, p)
        if not i2(k):
            continue
        z = CILED.get(k, 0.0)
        if k in CILED:                          # IF(Z, ...): an EPS COEF_ILED (exact start year, coef_ext.vda) is true
            c = 1 + GDR.get((r, v, cur), 0.0)
            my_f, f, cnt = 0.0, 0.0, 0.0
            for (y0, jot) in idc(k):
                cnt = jot
                if jot <= maxlife:
                    my_f += sum(DISC.get((r, y0 - a, cur), 0.0) for a in range(1, jot + 1) if (y0 - a) in YEARS)
                f += DISC.get((r, y0, cur), 0.0)
            my_f = my_f / f / cnt - 1
            f = ((c ** cnt) - 1) / (1 - 1 / c) / cnt - 1
            cnt = max(1e-5, z)
            z = ((c ** cnt) - 1) / (1 - 1 / c) / cnt - 1
        else:
            f = 1.0
        divi[k] = 1 / (1 + z * my_f / f)
    s["OBJ_C"] = 0.0
    # --- coef_alt.lin INV: OBJ_DIVI(OBJ_YES(R,V,P))$(NOT OBJ_I2(R,V,P)) = 1+MIN(IPD(V)-1,ROUND(NCAP_TLIFE(R,V,P))-1)$T(V);
    #     OBJ_DIVI(OBJ_YES(OBJ_1B(R,T,P)))$(ROUND(NCAP_TLIFE(R,T,P)) EQ 1) = NCAP_TLIFE(R,T,P);
    for k in yes:
        r, v, p = k
        if classic:
            # --- (eqobjinv.mod, CTST '') OBJ_DIVI(OBJ_YES(OBJ_1A(R,V,P))) = 1+(IPD(V)-1)$MILESTONYR(V);
            #     OBJ_DIVI(OBJ_YES(OBJ_1B(R,T,P))) = NCAP_TLIFE(R,T,P);
            #     IF(ALTOBJ,OBJ_DIVI(OBJ_YES(OBJ_1B(R,T,P)))$((ROUND(NCAP_TLIFE(R,T,P))-IPD(T)%CTST%) GT 0) = IPD(T)*MIN(1,NCAP_TLIFE(R,T,P)));
            if is1a(k):
                divi[k] = 1 + ((IPD[v] - 1) if v in T else 0)
            elif is1b(k):
                divi[k] = TLIFE[k]
                if s["ALTOBJ"] and rnd(TLIFE[k]) - IPD[v] > 0:
                    divi[k] = IPD[v] * min(1, TLIFE[k])
            continue
        if not i2(k):
            divi[k] = 1 + (min(IPD[v] - 1, rnd(TLIFE[k]) - 1) if v in T else 0)
        if is1b(k) and rnd(TLIFE[k]) == 1:
            divi[k] = TLIFE[k]
    # --- OBJ_DIVIII(OBJ_SUMS3(R,V,P)) = OBJ_DIVI(R,V,P);  OBJ_DIVIII(OBJ_SUMS3(OBJ_I2(R,V,P))) = ROUND(NCAP_DLIFE(R,V,P));
    diviii = {k: (rnd(DLIFE[k]) if i2(k) else divi[k]) for k in sums3}
    # --- OBJ_CRFD(R,PASTMILE(V),P,CUR)$OBJ_PASTI(R,V,P,CUR) = SUM(OBJ_SUMII(R,V,P,LIFE,K,JOT),NCAP_PASTI(R,V,P)*OBJ_CRF(R,V,P,CUR)/OBJ_DISC(R,K,CUR));
    #     OBJ_PASTI(R,PASTMILE(V),P,CUR)$OBJ_CRFD(R,V,P,CUR) = SUM(VNT(V,T),COEF_CPT(R,V,T,P)*OBJ_PVT(R,T,CUR))*OBJ_CRFD(R,V,P,CUR)/COR_SALVI(R,V,P,CUR);
    for (r, v, p, cur) in ([] if classic else list(opasti)):                 # coef_alt.lin INV only (not with CTST '')
        if v in PASTMILE:
            k = (r, v, p)
            crfd = sum(PASTI.get(k, 0.0) * crf[(r, v, p, cur)] / DISC[(r, y0, cur)] for (_l, y0, _j) in sumii.get(k, ()) if y0 in K)
            if crfd:
                w = sum(val * PVT.get((r, t, cur), 0.0) for t, val in cpt.get(k, ()) if t in vnt.get(v, ())) * crfd / cor[(r, v, p, cur)]
                if w:
                    opasti[(r, v, p, cur)] = w
                else:
                    del opasti[(r, v, p, cur)]
    _dofix(invstep, classic, K, FILB, rdcur, DISC, invspred, jd, wd, with_wd=False)
    # --- Decommissioning spreads (eqobjinv.mod, Cases III):
    #     UNCD7(OBJ_SUMS3(R,V,P),LIFE+(NCAP_DLIFE(R,V,P)-ORD(LIFE)),LL--(ORD(LL)$OBJ_I2(R,V,P)),LL,JOT)$OBJ_SUMII(R,V,P,LIFE,LL,JOT) = YES;
    #     LOOP(UNCD7(R,V,P,LIFE,LASTLL(LL),K,JOT),YKAGE(LL,K,LIFE) = YES);
    #     LOOP(YKAGE(YEAR,K(LL),JOT),INVSPRED(YEAR,AGE+(ORD(JOT)-ORD(AGE)),LL+(ORD(AGE)-1),K)$OPYEAR(JOT,AGE) = YES);
    #     LOOP(UNCD7(R,V,P,LIFE,YEAR,K_EOH,JOT), F = CEIL(NCAP_TLIFE(R,V,P)+NCAP_DLAG(R,V,P));
    #       IF(LASTLL(YEAR), OBJ_SUMIII(R,V,P,K(K_EOH),K,LL+F)$INVSPRED(YEAR,LIFE,LL,K_EOH) = YES;
    #       ELSE OBJ_SUMIII(R,V,P,LL,K,LL+F)$INVSPRED(K_EOH,JOT,LL,K) = YES));
    #     INVSPRED('0',JOT,YEAR,K) = NO;
    #     (with a lead time the decommissioning is spread over NCAP_DLIFE years from the commissioning year;
    #      otherwise it follows the investment spread, TLIFE + DLAG years later)
    sumiii = {}
    for k in sums3:
        dl = rnd(DLIFE[k])
        if dl > nage:
            continue
        f = math.ceil(TLIFE[k] + DLAG.get(k, 0.0))
        out = set()
        for (_life, y0, jot) in sumii.get(k, ()):
            if y0 not in K_EOH:
                continue
            if i2(k):
                if dl <= maxlife and y0 in K:
                    out |= {(y0, y0, y0 + a - 1 + f) for a in range(1, dl + 1) if (y0 + a - 1) in ALL and (y0 + a - 1 + f) in ALL}
            else:
                out |= {(mid, y, mid + f) for (mid, y) in invspred.get((y0, jot), ()) if (mid + f) in ALL}
        if out:
            sumiii[k] = sorted(out)
    return Investment(
        icur=icur, yes=yes, DLC=DLC, dlc_v=dlc_v, fcur=fcur, cor=cor, crf=crf, opasti=opasti, maxlife=maxlife,
        is1a=is1a, is1b=is1b, is2a=is2a, is2b=is2b, start=start, sumii=sumii, steps=steps, FILB=FILB,
        invspred=invspred, jd=jd, wd=wd, JDf=JDf, WDf=WDf, divi=divi, diviii=diviii, sumiii=sumiii)


def _dofix(invstep, classic, K, FILB, rdcur, DISC, invspred, jd, wd, with_wd):
    """coef_alt.lin DOFIX: investment spread around the period start; discount corrections OBJ_JD / OBJ_WD.
    With CTST '' the file is not called: INVSPRED(LL,JOT,K,K)$INVSTEP(LL,JOT,K,JOT) = YES, and no factors."""
    if classic:
        for (k0, jot), ys in invstep.items():
            invspred.setdefault((k0, jot), set()).update((y, y) for y in ys if y in K)
        return
    kage = {(k0, jot) for (k0, jot) in invstep if k0 not in FILB and k0 in K}
    kage |= {(k0, jot) for (k0, jot) in invstep if jot > 1 and k0 in FILB and (k0 + jot // 2) in FILB}
    for (k0, jot), ys in invstep.items():
        ys = [y for y in ys if y in K]
        if (k0, jot) in kage:
            invspred.setdefault((k0, jot), set()).update((k0 + jot // 2, y) for y in ys)
        else:
            invspred.setdefault((k0, jot), set()).update((y, y) for y in ys)
    for r, curs in rdcur.items():
        for cur in curs:
            for (k0, jot) in kage:
                den = sum(DISC.get((r, y, cur), 0.0) / DISC[(r, mid, cur)] for (mid, y) in invspred[(k0, jot)])
                jd[(r, cur, k0, jot)] = jot / den
            if with_wd:
                for (k0, jot), ys in invstep.items():
                    if (k0, jot) in kage:
                        for y in ys:
                            w = sum(DISC.get((r, y, cur), 0.0) / DISC[(r, mid, cur)] for (mid, yy) in invspred[(k0, jot)] if yy == y)
                            if w:
                                wd[(r, cur, k0, jot, y)] = w * jd[(r, cur, k0, jot)]
                    else:
                        for y in ys:
                            if y in K:
                                wd[(r, cur, k0, jot, y)] = 1.0


@dataclass(frozen=True, slots=True)
class FixedCosts:
    """The fixed-cost stage (_fixed_costs): the vintages with fixed costs, their divisors, shapes and years of
    operation, and the present value of those years within the horizon."""
    # OBJ_YES of eqobjfix.mod (r, v, p); OBJ_DIVIV by vintage
    yes2: set
    diviv: dict
    # RTP_ISHPR; RTP_SHAPE of '1', '2', '3' by vintage, (J, JJ); the shape factor and the multiplier alone
    ishpr: set
    rtp_shape: dict
    rtp_shape2: dict
    rtp_shape3: dict
    shp: object
    mul: object
    # OBJ_SUMIV by vintage, [(K, JOT, LIFE)]; OBJ_SUMIVS by vintage, [(K, Y)]
    sumiv: dict
    sumivs: dict
    # the (r, K, JOT, LIFE) of OBJ_LIFE before it is copied forward; INVSTEP of their (K, JOT); OBJ_LIFE by
    # (K, r, JOT, LIFE, cur)
    lifekeys: set
    invstep2: dict
    objlife: dict


def _fixed_costs(db: DB, I: Inputs, V: Investment) -> FixedCosts:
    """The fixed costs, eqobjfix.mod lines 36-175 with coef_alt.lin FIX (DOFIX, lines 105-131): the vintages with
    fixed costs (OBJ_YES), OBJ_DIVIV, the shapes (RTP_SHAPE, RTP_ISHPR), the years of operation of each investment
    step (OBJ_SUMIV) and of decommissioning surveillance (OBJ_SUMIVS), and OBJ_LIFE, their present value within
    the horizon, with the spreads and weights of these steps added to INVSPRED, OBJ_JD and OBJ_WD."""
    s, q = db.s, db.q
    classic, ALL, K, K_EOH, Y_EOH, T, PASTMILE = I.classic, I.ALL, I.K, I.K_EOH, I.Y_EOH, I.T, I.PASTMILE
    PYR_S, B, E, IPD, rtp, off, TLIFE, RPTI, PASTI = I.PYR_S, I.B, I.E, I.IPD, I.rtp, I.off, I.TLIFE, I.RPTI, I.PASTI
    DLAG, ILED, DISC, PVT, rdcur, resid0, resid = I.DLAG, I.ILED, I.DISC, I.PVT, I.rdcur, I.resid0, I.resid
    vnt, nage, CPX, FOMX, TAXX, SUBX, FOMM, TAXM = I.vnt, I.nage, I.CPX, I.FOMX, I.TAXX, I.SUBX, I.FOMM, I.TAXM
    SUBM, SHP, MUL = I.SUBM, I.SHP, I.MUL
    dlc_v, fcur, maxlife, is1a, is1b, is2a, is2b = V.dlc_v, V.fcur, V.maxlife, V.is1a, V.is1b, V.is2a, V.is2b
    start, steps, FILB, invspred, jd, wd = V.start, V.steps, V.FILB, V.invspred, V.jd, V.wd
    # ------------------------------------------------------------------ eqobjfix.mod
    # --- OBJ_FCUR;  OPTION OBJ_YES < OBJ_FCUR;  OBJ_YES(RTP_OFF(R,T,P))$(NOT NCAP_PASTI(R,T,P)) = NO;
    yes2 = {k[:3] for k in fcur}
    yes2 = {k for k in yes2 if not (k in off and k[1] in T and k not in PASTI)}
    # --- OBJ_DIVIV(OBJ_YES(R,V,P)) = MAX(1,MIN(CARD(AGE),CEIL(NCAP_TLIFE(R,V,P)-0.5)));
    #     OBJ_DIVIV(OBJ_YES(R,PYR_S(V),P))$PRC_RESID(R,'0',P)=MAX(2,SMAX(T$(PRC_RESID(R,T,P)>0),E(T))-MIYR_V1+2);
    diviv = {k: max(1, min(nage, math.ceil(TLIFE[k] - 0.5))) for k in yes2}
    for (r, v, p) in yes2:
        if v in PYR_S and (r, p) in resid0:
            diviv[(r, v, p)] = max(2, max([E[t] for t in T if resid.get((r, t, p), 0.0) > 0], default=float("-inf")) - s["MIYR_V1"] + 2)
    # --- Apply SHAPE to OBJ_YES:  RTP_SHAPE(OBJ_YES(RTP),'1',J+MAX(0,NCAP_FOMX(RTP)-1),J+MAX(0,NCAP_FOMM(RTP)-1))$(NCAP_FOMX+NCAP_FOMM+NCAP_CPX) = YES;
    #     RTP_SHAPE(OBJ_YES(RTP),'2',J+MAX(0,NCAP_FTAXX(RTP)-1),J+MAX(0,NCAP_FTAXM(RTP)-1))$(NCAP_FTAXX(RTP)+NCAP_FTAXM(RTP)) = YES;
    #     RTP_SHAPE(OBJ_YES(RTP),'3',J+MAX(0,NCAP_FSUBX(RTP)-1),J+MAX(0,NCAP_FSUBM(RTP)-1))$(NCAP_FSUBX(RTP)+NCAP_FSUBM(RTP)) = YES;
    #     OPTION RTP_ISHPR < RTP_SHAPE;  RTP_SHAPE(RTP_SHAPE(RTP,J,'1','1'))$(NOT NCAP_CPX(RTP)) = NO;
    #     (J, JJ): the SHAPE curve by age and the MULTI curve by year
    ix = lambda d, k: 1 + max(0, rnd(d.get(k, 0.0)) - 1)
    jfom = {k: (ix(FOMX, k), ix(FOMM, k)) for k in yes2 if k in CPX or k in FOMX or k in FOMM}
    jtax = {k: (ix(TAXX, k), ix(TAXM, k)) for k in yes2 if k in TAXX or k in TAXM}
    jsub = {k: (ix(SUBX, k), ix(SUBM, k)) for k in yes2 if k in SUBX or k in SUBM}
    ishpr = set(jfom) | set(jtax) | set(jsub)
    rtp_shape = {k: j for k, j in jfom.items() if j != (1, 1) or k in CPX}
    rtp_shape2 = {k: j for k, j in jtax.items() if j != (1, 1) or k in CPX}
    rtp_shape3 = {k: j for k, j in jsub.items() if j != (1, 1) or k in CPX}

    def shp(k, a, ye, shape=None):
        """1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),SHAPE(J,AGE)*MULTI(JJ,Y_EOH)-1) (shape: the curves of '2' or '3' instead)"""
        j = (rtp_shape if shape is None else shape).get(k)
        return 1.0 if j is None else SHP.get((j[0], a), 0.0) * MUL.get((j[1], ye), 0.0)

    def mul(k, ye, shape):
        """1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),MULTI(JJ,Y_EOH)-1): the multiplier curve alone (prepret.dsc, residual capacity)"""
        j = shape.get(k)
        return 1.0 if j is None else 1 + (MUL.get((j[1], ye), 0.0) - 1)

    sumiv = {}
    for k in yes2:
        r, v, p = k
        lst = []
        if is2a(k):
            # --- OBJ_SUMIV(LL+(B(LL)+NCAP_ILED(R,LL,P)-YEARVAL(LL)),OBJ_YES(OBJ_2A(R,V(LL),P)),'1',AGE+(OBJ_DIVIV(R,LL,P)-1)) = YES;
            #     the lag B(LL)+NCAP_ILED-YEARVAL(LL) is rounded by GAMS (half away from zero), not the year it points to
            lst.append((v + rnd(B[v] + ILED.get(k, 0.0) - v), 1, int(diviv[k])))
        elif is2b(k):
            # --- Z = NCAP_TLIFE(R,T,P); MY_F = ROUND(B(T)+NCAP_ILED(R,T,P))-YEARVAL(T);
            #     FOR(OBJ_C = 1 TO COEF_RPTI(R,T,P), F = MY_F; MY_F = F+Z; CNT = ROUND(MY_F)-ROUND(F)-1; OBJ_SUMIV(LL+F,R,T,P,'1',AGE+CNT) = YES);
            zz = TLIFE[k]
            my_f = rnd(B[v] + ILED.get(k, 0.0)) - v
            for _ in range(int(math.floor(RPTI[k]))):
                f, my_f = my_f, my_f + zz
                lst.append((v + rnd(f), 1, int(rnd(my_f) - rnd(f) - 1) + 1))
        elif is1a(k):
            y0, jot = start(v)
            lst.append((y0, jot, int(diviv[k])))
        elif v in T:
            zz = TLIFE[k]
            if rnd(zz) - (IPD[v] if classic else 1) <= 0:
                lst.append((B[v] - (math.ceil(zz / 2 - .5) if classic else rnd(zz) // 2), int(rnd(RPTI[k] * zz) - 1) + 1, int(diviv[k])))
            else:
                cnt = IPD[v] if classic else min(IPD[v], rnd(zz))
                # --- CNT = %ISTEP%; OBJ_D = CNT-1; MY_F = B(T)-YEARVAL(T)-FLOOR(CNT/2);
                #     FOR(OBJ_C = 1 TO COEF_RPTI(R,T,P), F = MY_F; MY_F = F+Z; CNT = ROUND(MY_F)-ROUND(F)-1;
                #       OBJ_SUMIV(LL+F,R,T,P,AGE+OBJ_D,AGE+CNT) = YES)
                #     F and MY_F are offsets from YEARVAL(T), rounded as offsets (F = -0.5 is the year before T)
                my_f = B[v] - v - math.floor(cnt / 2)
                for _ in range(int(math.floor(RPTI[k]))):
                    f, my_f = my_f, my_f + zz
                    lst.append((v + rnd(f), int(cnt), int(rnd(my_f) - rnd(f) - 1) + 1))
        # --- OBJ_SUMIV(OBJ_SUMIV(K_EOH,R,PASTMILE,P,JOT,AGE))$(NOT NCAP_PASTI(R,PASTMILE,P)) = NO;
        sumiv[k] = [(y0, jot, life) for (y0, jot, life) in lst if y0 in ALL and 1 <= jot <= nage and 1 <= life <= nage
                    and not (v in PASTMILE and y0 in K_EOH and k not in PASTI)]
    # --- Case IV.2.a: Surveillance (decommissioning delay, NCAP_DLAGC), only with a lead time:
    #     LOOP((OBJ_2A(R,V(LL),P),CUR)$OBJ_DLAGC(R,V,P,CUR),
    #       MY_F = B(V) + NCAP_ILED(R,V,P);
    #       F = ROUND(MY_F + NCAP_TLIFE(R,V,P)); Z = F + NCAP_DLAG(R,V,P); MY_F = MY_F-YEARVAL(V);
    #       OBJ_SUMIVS(R,V,P,LL+MY_F,Y)$((YEARVAL(Y) >= F) AND (YEARVAL(Y) < Z)) = YES);
    # --- Case IV.2.b:
    #     LOOP((OBJ_2B(R,T(LL),P),CUR)$OBJ_DLAGC(R,T,P,CUR),
    #       FOR(OBJ_C = 1 TO COEF_RPTI(R,T,P),
    #         MY_F = B(T) + NCAP_ILED(R,T,P) + (OBJ_C-1) * NCAP_TLIFE(R,T,P);
    #         F = ROUND(MY_F + NCAP_TLIFE(R,T,P)); Z = F + NCAP_DLAG(R,T,P); MY_F = MY_F-YEARVAL(T);
    #         OBJ_SUMIVS(R,T,P,LL+MY_F,Y)$((YEARVAL(Y) >= F) AND (YEARVAL(Y) < Z)) = YES));
    # --- OBJ_SUMIVS(OBJ_SUMIVS(R,PASTMILE,P,K,Y))$(NOT NCAP_PASTI(R,PASTMILE,P)) = NO;
    #     K is the commissioning year (the lag MY_F rounded as an offset), Y the years of surveillance after the life
    sumivs = {}
    for k in rtp:
        if k not in dlc_v or (k[1] in PASTMILE and k not in PASTI):
            continue
        r, v, p = k
        if is2a(k):
            starts = [B.get(v, 0) + ILED.get(k, 0.0)]
        elif is2b(k):
            starts = [B[v] + ILED.get(k, 0.0) + (c - 1) * TLIFE[k] for c in range(1, int(math.floor(RPTI[k])) + 1)]
        else:
            continue
        out = []
        for my_f in starts:
            f = rnd(my_f + TLIFE[k])
            z = f + DLAG.get(k, 0.0)
            kk = v + rnd(my_f - v)
            if kk in ALL:
                out += [(kk, y) for y in range(f, math.ceil(z)) if y in ALL and (kk, y) not in out]
        if out:
            sumivs[k] = sorted(out)
    # --- OBJ_LIFE(K,R,JOT,LIFE,CUR): present value of the years of operation that start in year K
    lifekeys = {(k[0], y0, jot, life) for k, lst in sumiv.items() for (y0, jot, life) in lst if y0 in K}
    invstep2 = steps({(y0, jot) for (_, y0, jot, _l) in lifekeys})
    # --- OPTION KAGE <= OBJ_LIFE;  INVSTEP(KAGE(LL,JOT),LL+(ORD(AGE)-1),..)$OPYEAR(JOT,AGE) = YES;
    #     LOOP(KAGE(K,JOT),OBJ_LIFE(LL,R,JOT,LIFE,CUR)$INVSTEP(K,JOT,LL,JOT) $= OBJ_LIFE(K,R,JOT,LIFE,CUR));
    #     KAGE ignores LIFE, and the LOOP runs over K in order, so a value copied forward from one K is copied on again
    #     from a later K of the same JOT that falls inside the first spread (chained, as GAMS does it)
    lifeyrs = set(lifekeys)
    by = {}
    for (r, y0, jot, life) in lifekeys:
        by.setdefault(jot, set()).add((r, life))
    for (k0, jot) in sorted({(y0, jot) for (_, y0, jot, _l) in lifekeys}, key=lambda kj: (int(kj[0]), kj[1])):
        for (r, life) in by[jot]:
            if (r, k0, jot, life) in lifeyrs:
                for y in invstep2.get((k0, jot), ()):
                    lifeyrs.add((r, y, jot, life))
    objlife = {}
    for (r, y, jot, life) in lifeyrs:
        for cur in rdcur.get(r, ()):
            if y in K and life <= maxlife:
                val = sum(DISC.get((r, yy, cur), 0.0) for yy in range(y, y + life) if yy in Y_EOH)
                if val:
                    objlife[(y, r, jot, life, cur)] = val
    _dofix(invstep2, classic, K, FILB, rdcur, DISC, invspred, jd, wd, with_wd=True)
    # --- OBJ_DIVIV(OBJ_YES(R,PASTMILE,P)) = 1;  OBJ_DIVIV(OBJ_YES(R,T,P)) = MAX(1,MIN(IPD(T),ROUND(NCAP_TLIFE(R,T,P)))$(OBJ_1B(R,T,P)+OBJ_1A(R,T,P)));
    for k in yes2:
        r, v, p = k
        if classic:
            # --- (eqobjfix.mod, CTST '') OBJ_DIVIV(OBJ_YES(R,PASTMILE,P)) = 1;
            #     OBJ_DIVIV(OBJ_YES(R,T,P))$(NOT OBJ_1B(R,T,P)) = 1+(IPD(T)-1)$OBJ_1A(R,T,P);
            #     IF(ALTOBJ, OBJ_DIVIV(OBJ_1B(OBJ_YES(R,T,P)))$((ROUND(NCAP_TLIFE(R,T,P))-IPD(T)%CTST%) GT 0) = IPD(T));
            if v in PASTMILE:
                diviv[k] = 1
            if v in T and not is1b(k):
                diviv[k] = 1 + ((IPD[v] - 1) if is1a(k) else 0)
            if v in T and is1b(k) and s["ALTOBJ"] and rnd(TLIFE[k]) - IPD[v] > 0:
                diviv[k] = IPD[v]
            continue
        if v in PASTMILE:
            diviv[k] = 1
        if v in T:
            diviv[k] = max(1, min(IPD[v], rnd(TLIFE[k])) if (is1a(k) or is1b(k)) else 0)
    # --- LOOP(PYR_S(V), LOOP((OBJ_SUMIV(V,R,V,P,JOT,LIFE),G_RCUR(R,CUR))$PRC_RESID(R,'0',P),
    #        OBJ_DIVIV(R,V,P) = NCAP_PASTI(R,V,P)*OBJ_LIFE(V,R,JOT,LIFE,CUR)/SUM(VNT(V,T)$PRC_RESID(R,T,P),PRC_RESID(R,T,P)*OBJ_PVT(R,T,CUR))));
    grcur = {r: cur for r, cur in q("select r, cur from G_RCUR")}
    for k in ([] if classic else yes2):                                    # coef_alt.lin DOFIX only
        r, v, p = k
        if v in PYR_S and (r, p) in resid0 and r in grcur:
            cur = grcur[r]
            for (y0, jot, life) in sumiv[k]:
                if y0 == v:
                    den = sum(resid[(r, t, p)] * PVT.get((r, t, cur), 0.0) for t in vnt.get(v, ()) if resid.get((r, t, p), 0.0))
                    diviv[k] = PASTI.get(k, 0.0) * objlife.get((v, r, jot, life, cur), 0.0) / den
    return FixedCosts(
        yes2=yes2, diviv=diviv, ishpr=ishpr, rtp_shape=rtp_shape, rtp_shape2=rtp_shape2, rtp_shape3=rtp_shape3,
        shp=shp, mul=mul, sumiv=sumiv, sumivs=sumivs, lifekeys=lifekeys, invstep2=invstep2,
        objlife=objlife)


@dataclass(frozen=True, slots=True)
class Steps:
    """What a myopic step needs to recompute the end of the horizon (step_tables): the three records of the main pass
    and the years of EOHYEARS from MINYR (db.obj_steps, set by objective_coefficients, read by prep/myopic.py)."""
    inputs: Inputs
    investment: Investment
    fixed: FixedCosts
    Y_EOH0: set


# Everything below depends on the end of the horizon (MIYR_VL, Y_EOH): salvage, the fixed costs within the
# horizon (OBJ_LIFE) and the credit for retired capacity.  A myopic run (TIMESTEP, solve.stp) recomputes it
# for the window of each step: prep/myopic.py calls eoh() again.
def eoh(db: DB, I: Inputs, V: Investment, F: FixedCosts, miyr, Y_EOH, objlife, fwd=frozenset()):
    """The terms that depend on the end of the horizon: the salvage of investments, decommissioning and
    surveillance (eqobsalv.mod lines 28-82), the sums TIMES writes inside EQ_OBJINV and EQ_OBJFIX (eqobjinv.mod
    lines 286-316, eqobjfix.mod lines 189-221), stored per unit of capacity, the coefficients of the annualised
    objective (eqobjann.tm, COEF, lines 34-97) and the credit for retired capacity (prepret.dsc OBJFIX, lines
    134-156).  For the horizon of the model, and again for the window of each step of a myopic run (step_tables).
    miyr: MIYR_VL; Y_EOH and objlife (OBJ_LIFE) of that horizon or window.
    fwd: the vintages of a myopic step that are taken out of V (MODLYEAR) because they come after the window."""
    s, q = db.s, db.q
    classic, lev, K, K_EOH, T, PASTMILE, B, rtpset = I.classic, I.lev, I.K, I.K_EOH, I.T, I.PASTMILE, I.B, I.rtpset
    TLIFE, PASTI, DELIF, NDR, FDR, ILED, DISC, GDR = I.TLIFE, I.PASTI, I.DELIF, I.NDR, I.FDR, I.ILED, I.DISC, I.GDR
    RFR, PVT, rdcur, FOM, FSB, FTX, DCC, ICOST = I.RFR, I.PVT, I.rdcur, I.FOM, I.FSB, I.FTX, I.DCC, I.ICOST
    FOMC, dcost, icost, fom, fom_rec, resid0, resid = I.FOMC, I.dcost, I.icost, I.fom, I.fom_rec, I.resid0, I.resid
    cptpv, vnt, CPX, RCPX, period_of, icost_rec = I.cptpv, I.vnt, I.CPX, I.RCPX, I.period_of, I.icost_rec
    ICO, ISU, ITX = I.ICO, I.ISU, I.ITX
    icur, yes, DLC, fcur, cor, crf, opasti, maxlife = V.icur, V.yes, V.DLC, V.fcur, V.cor, V.crf, V.opasti, V.maxlife
    sumii, invspred, JDf, WDf, divi, diviii, sumiii = V.sumii, V.invspred, V.JDf, V.WDf, V.divi, V.diviii, V.sumiii
    yes2, diviv, ishpr, rtp_shape, rtp_shape2 = F.yes2, F.diviv, F.ishpr, F.rtp_shape, F.rtp_shape2
    rtp_shape3, shp, mul, sumiv, sumivs = F.rtp_shape3, F.shp, F.mul, F.sumiv, F.sumivs
    # ------------------------------------------------------------------ eqobsalv.mod: salvage share of each investment step
    # --- $IF NOT DEFINED VNRET $IF NOT '%CTST%'=='' $SET PFT (T)          past vintages too once retirements are declared
    # (the -1: the lifetime starts at the beginning of the commissioning year K, eqobsalv.mod line 30)
    # --- OBJ_SALI(OBJ_SUMII(R,V%PFT%,P,AGE,K_EOH,JOT),K,LL--ORD(LL))$((YEARVAL(K)+NCAP_TLIFE(R,V,P)-1>MIYR_VL)$INVSPRED(K_EOH,JOT,K,LL))=YES;
    #     OPTION OBJ_SUMSI <= OBJ_SALI;  LOOP((RP(R,PRC),P)$PRC_REFIT(RP,P),IF(PRC_REFIT(RP,P)<0, OBJ_SUMSI(R,T,P,K)=NO));  OPTION OBJ_SUMS <= OBJ_SUMSI;
    all_v = bool(db.s.get("VNRET")) or classic          # PFT is '' with CTST '': every vintage, past ones too
    retro = {(r, p2) for r, p_, p2, val in q("select r, p, p2, value from PRC_REFIT where in_RP(r,p)") if val < 0}
    # --- SALV_INV(OBJ_SUMSI(R,V,P,K))$OBJ_ICUR(R,V,P,CUR) = MIN(1,(((1+G_DRATE)*EXP(NCAP_FDR))**(NCAP_TLIFE+YEARVAL(K)-MIYR_VL-1)-1) /
    #                                                              (((1+G_DRATE)*EXP(NCAP_FDR))**NCAP_TLIFE-1));
    #     (OBJ_SUMII holds the vintages with decommissioning costs too, also those without investment costs: they are
    #      salvaged vintages, OBJ_SUMS, with no SALV_INV)
    sumsi = set()
    for k in yes:
        r, v, p = k
        if v in fwd or not (all_v or v in T) or (v in T and (r, p) in retro):
            continue
        for (_, y0, jot) in sumii.get(k, ()):
            if y0 not in K_EOH:
                continue
            sumsi |= {(r, v, p, mid) for (mid, _y) in invspred.get((y0, jot), ()) if mid in K and mid + TLIFE[k] - 1 > miyr}
    sums = {kk[:3] for kk in sumsi}
    # --- Salvaging of Decommissioning surveillance (after OPTION OBJ_SUMS <= OBJ_SUMSI, before SALV_INV):
    #     LOOP(OBJ_SUMIVS(R,V,P,K,Y)$(YEARVAL(K)+NCAP_TLIFE(R,V,P)-1 GT MIYR_VL), OBJ_SUMS3(R,V,P) = YES; OBJ_SUMSI(R,V,P,K) = YES);
    survs3 = set()
    for k, lst in sumivs.items():
        if k[1] in fwd:
            continue
        for (kk, _y) in lst:
            if kk + TLIFE[k] - 1 > miyr:
                survs3.add(k)
                sumsi.add(k + (kk,))
    mids = {}
    for (r, v, p, mid) in sumsi:
        mids.setdefault((r, v, p), []).append(mid)
    salv = {}
    # (the share once per distinct rate, life and year: the same expression, so the same rounding)
    share = {}
    for (r, v, p, cur) in icur:
        k = (r, v, p)
        ms = mids.get(k)
        if ms:
            tl, dr, fd = TLIFE[k], GDR.get((r, v, cur), 0.0), FDR.get(k, 0.0)
            for mid in ms:
                x = share.get((dr, fd, tl, mid))
                if x is None:
                    g = (1 + dr) * math.exp(fd)
                    x = share[(dr, fd, tl, mid)] = min(1, (g ** (tl + mid - miyr - 1) - 1) / (g ** tl - 1))
                salv[(r, v, p, mid)] = x
    # --- Shape-reduced salvage at EOH+1:  Z = SMAX(T$(B(T)<=MIYR_VL+1),ORD(T)-1);
    #     LOOP(MIYR_1(T-Z), SALV_INV(OBJ_SUMSI(RTP,K))$NCAP_CPX(RTP) = SALV_INV(RTP,K)*(1+RTP_CPX(RTP,T)));
    if CPX:
        tl_ = max(t for t in T if B[t] <= miyr + 1)
        for (r, v, p, mid) in list(salv):
            if (r, v, p) in CPX:
                salv[(r, v, p, mid)] *= 1 + RCPX.get((r, v, p, tl_), 0.0)
    # --- LOOP(MIYR_1(LL), F = MIYR_VL+1-YEARVAL(MIYR_1); OBJ_DCEOH(RDCUR(R,CUR)) = OBJ_DISC(R,LL+F,CUR));
    dceoh = {(r, cur): DISC.get((r, int(miyr) + 1, cur), 0.0) for r, curs in rdcur.items() for cur in curs}
    # --- OBJSCC(OBJ_ICUR(OBJ_SUMS(R,V,P),CUR)) = COR_SALVI(R,V,P,CUR) / OBJ_DCEOH(R,CUR) / OBJ_DIVI(R,V,P) *
    #       SUM((OBJ_SUMII(R,V,P,AGE,K_EOH,JOT),INVSPRED(K_EOH,JOT,LL,K))$SALV_INV(R,V,P,LL),OBJ_JD(R,CUR,K_EOH,JOT)*
    #           (OBJ_ICOST(R,K,P,CUR)+OBJ_ITAX(R,K,P,CUR)-OBJ_ISUB(R,K,P,CUR)) * SALV_INV(R,V,P,LL) * OBJ_DISC(R,K,CUR));
    objscc, iad = {}, {}
    for (r, v, p, cur) in icur:
        k = (r, v, p)
        if k not in sums:
            continue
        tot, rec = 0.0, False
        for (_, y0, jot) in sumii[k]:
            if y0 not in K_EOH:
                continue
            jd_ = JDf((r, cur, y0, jot))
            sx = [(y, sv) for (mid, y) in invspred.get((y0, jot), ()) for sv in (salv.get((r, v, p, mid), 0.0),) if sv]
            tot += sum(jd_ * ICOST.get((r, p, cur, y), 0.0) * sv * DISC.get((r, y, cur), 0.0) for (y, sv) in sx)
            rec = rec or any(icost_rec(r, y, p, cur) for (y, sv) in sx)
        val = cor[(r, v, p, cur)] / dceoh[(r, cur)] / divi[k] * tot
        if val or rec:
            objscc[(r, v, p, cur)] = val
            # --- OBJ_IAD(RDCUR(R,CUR)) = SUM(OBJ_ICUR(OBJ_SUMS(R,PASTMILE(V),P),CUR)$((OBJ_PASTI(R,V,P,CUR)=0)+0%CTST%),
            #                                 OBJSCC(R,V,P,CUR)*NCAP_PASTI(R,V,P)*OBJ_DCEOH(R,CUR));          (0**0 = 1: every past vintage)
            if v in PASTMILE and (not classic or not opasti.get((r, v, p, cur), 0.0)):   # $((OBJ_PASTI=0)+0%CTST%)
                iad[(r, cur)] = iad.get((r, cur), 0.0) + val * PASTI.get(k, 0.0) * dceoh[(r, cur)]

    # ------------------------------------------------------------------ eqobsalv.mod: decommissioning
    # --- LOOP(OBJ_SUMIII(OBJ_SUMS(R,V,P),LL,K,Y), OBJ_SUMS3(R,V,P) = YES);
    sums3s = {k for k in sumiii if k in sums} | survs3
    # --- EQ_OBJSALV, Cases IV: SUM(OBJ_SUMIVS(R,V,P,K,Y)$SALV_INV(R,V,P,K),
    #       OBJ_DISC(R,Y,CUR) * OBJ_DLAGC(R,K,P,CUR) * SALV_INV(R,V,P,K) * (VAR_NCAP$MILESTONYR(V) + NCAP_PASTI$PASTYEAR(V)))
    #     not a GAMS symbol: stored per unit of capacity as OBJ_SALVS for the equation side
    salvs = {}
    for k, lst in sumivs.items():
        r, v, p = k
        if v in fwd:
            continue
        for cur in rdcur.get(r, ()):
            tm = [(kk, y) for (kk, y) in lst if salv.get((r, v, p, kk), 0.0)]
            if tm:
                salvs[(r, v, p, cur)] = sum(DISC.get((r, y, cur), 0.0) * DLC.get((r, p, cur, kk), 0.0) * salv[(r, v, p, kk)]
                                            for (kk, y) in tm)
    # --- COR_SALVD(RTP(R,V,P),CUR)$OBJ_DCOST(R,V,P,CUR) = (((1-1/(1+NCAP_DRATE))*(1-1/(1+OBJ_RFR)**NCAP_DELIF)) /
    #        ((1-1/(1+OBJ_RFR))*(1-1/(1+NCAP_DRATE)**NCAP_DELIF)))$(NCAP_DRATE GT 0) + 1$(NCAP_DRATE EQ 0);
    #     OBJ_CRFD(RTP(R,V,P),CUR)$OBJ_DCOST(R,V,P,CUR) = COR_SALVD * (1-(1/(1+G_DRATE))) / (1-(1+G_DRATE)**(-ROUND(NCAP_DELIF)));
    corsd, crfd_d = {}, {}
    for (r, p, cur, v) in DCC:
        k = (r, v, p)
        if k not in rtpset or cur not in rdcur.get(r, ()) or v in fwd:
            continue
        ndr, rf, de, dr = NDR.get(k, 0.0), RFR.get((r, v, cur), 0.0), DELIF.get(k, 0.0), GDR.get((r, v, cur), 0.0)
        x = (((1 - 1 / (1 + ndr)) * (1 - 1 / (1 + rf) ** de)) / ((1 - 1 / (1 + rf)) * (1 - 1 / (1 + ndr) ** de))) if ndr > 0 else 1.0
        corsd[(r, v, p, cur)] = x
        crfd_d[(r, v, p, cur)] = x * (1 - 1 / (1 + dr)) / (1 - (1 + dr) ** (-rnd(de)))
    # --- SALV_DEC(OBJ_SUMS3(R,V,P),CUR)$COR_SALVD(R,V,P,CUR) = COR_SALVD(R,V,P,CUR) / OBJ_DIVIII(R,V,P) / OBJ_DCEOH(R,CUR) *
    #       SUM(OBJ_SUMIII(R,V,P,LL,K,Y)$SALV_INV(R,V,P,LL),SALV_INV(R,V,P,LL)*OBJ_DCOST(R,K,P,CUR)*OBJ_DISC(R,Y,CUR));
    salvdec = {}
    for (r, v, p, cur), x in corsd.items():
        k = (r, v, p)
        if k not in sums3s:
            continue
        tot = sum(salv[(r, v, p, ll)] * dcost(r, kk, p, cur) * DISC.get((r, y, cur), 0.0)
                  for (ll, kk, y) in sumiii[k] if salv.get((r, v, p, ll), 0.0))
        f = x / diviii[k] / dceoh[(r, cur)]
        val = f * tot
        if val:
            salvdec[(r, v, p, cur)] = val
        elif f and any(DCC.get((r, p, cur, kk)) == 0.0 and DISC.get((r, y, cur), 0.0)
                       for (ll, kk, y) in sumiii[k] if salv.get((r, v, p, ll), 0.0)):
            salvdec[(r, v, p, cur)] = 0.0              # a decommissioning cost given as EPS: EPS, a record
    # --- EQ_OBJINV, Cases III: SUM(OBJ_SUMIII(R,V,P,LL,K,Y)$OBJ_DCOST(R,V,P,CUR),
    #       OBJ_DISC(R,Y,CUR) * COR_SALVD(R,V,P,CUR) * OBJ_DCOST(R,K,P,CUR) * (VAR_NCAP$MILESTONYR(V) + OBJ_PASTI$PASTYEAR(V)) / OBJ_DIVIII(R,V,P))
    #     (also the decommissioning part of COEF_OBINV in the annualised form); stored per unit as OBJ_CDEC
    cdec = {}
    for (r, v, p, cur), x in corsd.items():
        k = (r, v, p)
        if k not in sumiii or (r, p, cur, v) not in DCC:
            continue
        val = sum(DISC.get((r, y, cur), 0.0) * x * dcost(r, kk, p, cur) for (ll, kk, y) in sumiii[k]) / diviii[k]
        if val:
            cdec[(r, v, p, cur)] = val
        elif x and any(DCC.get((r, p, cur, kk)) == 0.0 and DISC.get((r, y, cur), 0.0) for (ll, kk, y) in sumiii[k]):
            cdec[(r, v, p, cur)] = 0.0                  # a decommissioning cost given as 0 (EPS): an EPS coefficient, a record

    # ------------------------------------------------------------------ eqobjann.tm, COEF section
    obinv, obfix, cinv, cfix = [], [], [], []
    for (r, v, p, cur) in icur:
        k = (r, v, p)
        dr = GDR.get((r, v, cur), 0.0)
        c = 0.0
        if v in T:
            c += cptpv(r, v, p, cur)
        kc = v + rnd(B[v] - v + ILED.get(k, 0.0))   # OBJ_SUMSI(RTP(R,V(LL),P),LL+(FIL2(V)+NCAP_ILED(R,V,P))): commissioning year (the lag is rounded)
        if v in PASTMILE and kc in K:
            c += DISC.get((r, kc, cur), 0.0) * (1 - (1 + dr) ** (-TLIFE[k])) / (1 - 1 / (1 + dr))
        val, rec, ann = 0.0, False, False
        tot = gross = 0.0
        cr, dv, inT = cor[(r, v, p, cur)], divi[k], v in T
        for (_, y0, jot) in sumii[k]:
            if y0 not in K_EOH:
                continue
            # (each year's discount factor and cost looked up once for both sums; the terms and their order as written)
            sp = invspred.get((y0, jot), ())
            dx = [(mid, DISC.get((r, y, cur), 0.0), ICOST.get((r, p, cur, y), 0.0)) for (mid, y) in sp]
            inner = sum(d * (1 - (salv.get((r, v, p, mid), 0.0) if inT else 0.0)) * x for (mid, d, x) in dx)
            whole = sum(d * x for (mid, d, x) in dx)
            rec = rec or any(icost_rec(r, y, p, cur) for (mid, y) in sp)
            # --- eqobjann.tm 54: (OBJ_ICOST(R,K,P,CUR) + (OBJ_ITAX(R,K,P,CUR) - OBJ_ISUB(R,K,P,CUR))%2)
            ann = ann or any(_eps_grouped(ICO, ITX, ISU, (r, p, cur, y)) for (mid, y) in sp)
            jd_ = JDf((r, cur, y0, jot))
            tot += jd_ * inner * cr / dv
            gross += jd_ * whole * cr / dv
        # --- EQ_OBJINV: SUM(OBJ_SUMII(..K_EOH,JOT), OBJ_JD * SUM(INVSPRED, OBJ_DISC*(OBJ_ICOST+OBJ_ITAX-OBJ_ISUB)) * COR_SALVI / OBJ_DIVI)
        if gross or rec:
            cinv.append((r, str(v), p, cur, gross))
        tot += cdec.get((r, v, p, cur), 0.0)            # Cases III: decommissioning
        if c:
            val = tot / c
        else:
            rec = ann = False
        if v in PASTMILE and (r, p) in resid0:
            val = crf[(r, v, p, cur)] * icost(r, v, p, cur)
        if val or rec or ann:                         # an EPS cost gives an EPS coefficient
            obinv.append((r, str(v), p, cur, val))
    for (r, v, p, cur) in fcur:
        k = (r, v, p)
        c = cptpv(r, v, p, cur)
        lst = sumiv.get(k, []) if k in yes2 else []
        # --- eqobjann.tm 68-69: COEF_CRF(OBJ_FCUR(R,V,P,CUR)) = SUM(RTP_CPTYR(R,V,T,P),COEF_CPT(R,V,T,P)*OBJ_PVT(R,T,CUR));
        #     $IFI NOT %ANNCOST%==LEV COEF_CRF(OBJ_FCUR(R,PASTMILE(V),P,CUR)) = SUM(OBJ_SUMIV(K_EOH,R,V,P,JOT,LIFE),OBJ_LIFE(K_EOH,R,JOT,LIFE,CUR));
        if v in PASTMILE and not lev:
            c = sum(objlife.get((y0, r, jot, life, cur), 0.0) for (y0, jot, life) in lst if y0 in K_EOH)
        val = 0.0
        rec = ann = False                             # an EPS cost gives an EPS coefficient (NCAP_FOM given as 0)
        tot = 0.0
        shaped = k in ishpr
        for (y0, jot, life) in lst:
            if y0 not in K_EOH:
                continue
            sp = invspred.get((y0, jot), ())
            # (EPS: a cost on record that is EPS; a cost with a value times a shape of 0 is 0, no record:
            #  OBJ_FOM * (1+SHAPE(J,AGE)*MULTI(JJ,Y_EOH)-1) with SHAPE or MULTI EPS)
            rec = rec or any(FOMC.get((r, p, cur, y)) == 0.0 and fom_rec(r, y, p, cur) for (mid, y) in sp)
            # --- eqobjann.tm 79: (OBJ_FOM(R,K,P,CUR)+(OBJ_FTX(R,K,P,CUR)-OBJ_FSB(R,K,P,CUR))%2)
            ann = ann or any(_eps_grouped(FOM, FTX, FSB, (r, p, cur, y)) for (mid, y) in sp)
            if not shaped:
                tot += sum(objlife.get((mid, r, jot, life, cur), 0.0) * WDf((r, cur, y0, jot, y)) * FOMC.get((r, p, cur, y), 0.0)
                           for (mid, y) in sp) / diviv[k]
            elif life <= maxlife:
                # --- SUM((INVSPRED(K_EOH,JOT,LL,K),OPYEAR(LIFE,AGE),Y_EOH(LL+(ORD(AGE)-1))),
                #       OBJ_DISC(R,Y_EOH,CUR) * (1+SUM(PERIODYR(T,Y_EOH),RTP_CPX(R,V,P,T))$NCAP_CPX(R,V,P)) * %CAPWD%
                #       (OBJ_FOM(R,K,P,CUR) * (1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),SHAPE(J,AGE)*MULTI(JJ,Y_EOH)-1)) + ...)) / OBJ_DIVIV(R,V,P)
                #     the fixed cost of every year of operation follows the capacity that is left
                for (mid, y) in invspred.get((y0, jot), ()):
                    ftx, fsb = FTX.get((r, p, cur, y), 0.0), FSB.get((r, p, cur, y), 0.0)
                    if (ftx or fsb) and (k in rtp_shape2 or k in rtp_shape3 or rtp_shape.get(k, (1, 1)) != (1, 1)):
                        # --- (OBJ_FOM * (1+..'1'..) + OBJ_FTX * (1+..'2'..) - OBJ_FSB * (1+..'3'..)): each by its curve
                        fo = FOM.get((r, p, cur, y), 0.0)
                        wd = WDf((r, cur, y0, jot, y))
                        tot += wd * sum(DISC.get((r, ye, cur), 0.0) * (1 + RCPX.get((r, v, p, period_of.get(ye)), 0.0))
                                        * (fo * shp(k, a, ye) + ftx * shp(k, a, ye, rtp_shape2) - fsb * shp(k, a, ye, rtp_shape3))
                                        for a, ye in ((a, mid + a - 1) for a in range(1, life + 1)) if ye in Y_EOH) / diviv[k]
                        continue
                    w = WDf((r, cur, y0, jot, y)) * fom(r, y, p, cur)
                    if w:
                        tot += w * sum(DISC.get((r, ye, cur), 0.0) * (1 + RCPX.get((r, v, p, period_of.get(ye)), 0.0))
                                       * shp(k, a, ye)
                                       for a, ye in ((a, mid + a - 1) for a in range(1, life + 1)) if ye in Y_EOH) / diviv[k]
        # --- Case V - Decommissioning Surveillance:  SUM(OBJ_SUMIVS(R,V,P,K,Y), OBJ_DISC(R,Y,CUR) * OBJ_DLAGC(R,K,P,CUR))
        #     (not divided by OBJ_DIVIV; in EQ_OBJFIX on VAR_NCAP, or on NCAP_PASTI of a past vintage of case 2a, which
        #      is the only kind of past vintage OBJ_SUMIVS has)
        if k in sumivs:
            rec = rec or any((r, p, cur, kk) in DLC for (kk, y) in sumivs[k])
            tot += sum(DISC.get((r, y, cur), 0.0) * DLC.get((r, p, cur, kk), 0.0) for (kk, y) in sumivs[k])
        # --- EQ_OBJFIX: the same sums, not divided by the capital recovery of the annualised form
        if tot or rec:
            cfix.append((r, str(v), p, cur, tot))
        if c:
            val = tot / c
        else:
            rec = ann = False
        if v in PASTMILE and (r, p) in resid0:
            den = sum(resid[(r, t, p)] / PASTI[k] * PVT.get((r, t, cur), 0.0) for t in vnt.get(v, ()) if resid.get((r, t, p), 0.0))
            val = val * c / den
        if val or rec or ann:
            obfix.append((r, str(v), p, cur, val))

    # ------------------------------------------------------------------ prepret.dsc, label OBJFIX (term of EQ_ANNFIX)
    # Credit retired capacity for the avoided fixed costs:
    # --- SUM((OBJ_SUMIV(K_EOH,R,V,P,JOT,LIFE),VNTRT(V,T))$RVPRL(R,V,P),
    #       SUM((INVSPRED(K_EOH,JOT,LL,K),KTYAGE(LL,T,Y_EOH,AGE))$OPYEAR(LIFE,AGE),
    #           -OBJ_DISC(R,Y_EOH,CUR) * %CAPWD% (OBJ_FOM(R,K,P,CUR)+OBJ_FTX(R,K,P,CUR)-OBJ_FSB(R,K,P,CUR))) *
    #       %VART%_SCAP(R,V,T,P) / OBJ_DIVIV(R,V,P))
    # The coefficient of VAR_SCAP(R,V,T,P) is not a GAMS symbol (GAMS evaluates it inside the equation);
    # it is stored as COEF_OBFIXR(R,V,T,P,CUR) for the equation side.
    # KTYAGE(K(LL),PERIODYR(T,Y_EOH(YEAR)),AGE+(ORD(YEAR)-ORD(LL)))$YK(YEAR,LL):  year of period T at age YEAR-LL+1
    obfixr = []
    if s.get("VNRET"):
        rvprl = {(r, int(y), p) for r, y, p in q(f"select r, y, p from ({stochastic.rvprl_at_solve_sql(db)}) where y<>'0'")}
        vntrt = {}
        for v, t in q("select * from VNTRT order by all"):
            vntrt.setdefault(int(v), []).append(int(t))
        peryr = {}
        for t, y in q("select * from PERIODYR order by all"):
            if int(y) in Y_EOH:
                peryr.setdefault(int(t), []).append(int(y))
        # --- SUM(RTP_CPTYR(R,PYR_S(V(K)),T,P)$((NOT RVPRL(R,V,P))$PRC_RCAP(R,P)), ... %VART%_SCAP(R,V,T,P))    'RESIDS require special handling'
        #     SUM(PERIODYR(T,Y_EOH), -OBJ_DISC(R,Y_EOH,CUR) * (OBJ_FOM(R,K,P,CUR) * (1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),MULTI(JJ,Y_EOH)-1)) + FTX - FSB))
        #     K = V = the residual pseudo-vintage PYR_S; no age shape; not divided by OBJ_DIVIV
        cptyr_res = {}
        for r, v, t, p in q("select r, y, y2, p from RTP_CPTYR where in_PYR_S(y) and in_PRC_RCAP(r,p) and not in_RVPRL(r,y,p) order by all"):
            if (r, int(v), p) not in rvprl:
                cptyr_res.setdefault((r, int(v), p), []).append(int(t))
        for (r, v, p, cur) in fcur:
            k = (r, v, p)
            for t in cptyr_res.get(k, ()):
                w = fom(r, v, p, cur)
                if any(sh.get(k, (1, 1))[1] != 1 for sh in (rtp_shape, rtp_shape2, rtp_shape3)):
                    # --- (OBJ_FOM * (1+..'1'..) + OBJ_FTX * (1+..'2'..) - OBJ_FSB * (1+..'3'..)): each by its MULTI curve
                    fo, ftx, fsb = FOM.get((r, p, cur, v), 0.0), FTX.get((r, p, cur, v), 0.0), FSB.get((r, p, cur, v), 0.0)
                    tot = -sum(DISC.get((r, ye, cur), 0.0) * (fo * mul(k, ye, rtp_shape) + ftx * mul(k, ye, rtp_shape2)
                                                              - fsb * mul(k, ye, rtp_shape3)) for ye in peryr.get(t, ()))
                else:
                    tot = -w * sum(DISC.get((r, ye, cur), 0.0) for ye in peryr.get(t, ()))
                rec = (not w) and fom_rec(r, v, p, cur) and bool(peryr.get(t))
                if tot or rec:
                    obfixr.append((r, str(v), str(t), p, cur, tot))
        for (r, v, p, cur) in fcur:
            k = (r, v, p)
            if k not in rvprl or k not in yes2:
                continue
            for t in vntrt.get(v, ()):
                tot = 0.0
                rec = False
                for (y0, jot, life) in sumiv[k]:
                    if y0 not in K_EOH or life > maxlife:
                        continue
                    for (mid, y) in invspred.get((y0, jot), ()):
                        w = WDf((r, cur, y0, jot, y)) * fom(r, y, p, cur)
                        # a fixed cost given as 0 (EPS) leaves an EPS coefficient on the retired capacity
                        if not w and not rec and fom_rec(r, y, p, cur) and WDf((r, cur, y0, jot, y)):
                            rec = any(0 <= ye - mid < life for ye in peryr.get(t, ()))
                        ftx, fsb = FTX.get((r, p, cur, y), 0.0), FSB.get((r, p, cur, y), 0.0)
                        if (ftx or fsb) and (k in rtp_shape2 or k in rtp_shape3 or rtp_shape.get(k, (1, 1)) != (1, 1)):
                            # ... (OBJ_FOM * (1+..'1'..) + OBJ_FTX * (1+..'2'..) - OBJ_FSB * (1+..'3'..)): each by its curve
                            fo, wd = FOM.get((r, p, cur, y), 0.0), WDf((r, cur, y0, jot, y))
                            tot -= wd * (1 + (RCPX.get((r, v, p, t), 0.0) if k in CPX else 0.0)) * sum(
                                DISC.get((r, ye, cur), 0.0) * (fo * shp(k, ye - mid + 1, ye) + ftx * shp(k, ye - mid + 1, ye, rtp_shape2)
                                                               - fsb * shp(k, ye - mid + 1, ye, rtp_shape3))
                                for ye in peryr.get(t, ()) if 0 <= ye - mid < life)
                            continue
                        if w:
                            # ... -OBJ_DISC(R,Y_EOH,CUR) * (1+RTP_CPX(R,V,P,T)$NCAP_CPX(R,V,P)) * %CAPWD% (OBJ_FOM * (1+SUM(RTP_SHAPE,SHAPE*MULTI-1)) ...)
                            shaped = k in ishpr
                            tot -= w * (1 + (RCPX.get((r, v, p, t), 0.0) if k in CPX else 0.0)) * sum(
                                DISC.get((r, ye, cur), 0.0) * (shp(k, ye - mid + 1, ye) if shaped else 1.0)
                                for ye in peryr.get(t, ()) if 0 <= ye - mid < life)
                if tot or rec:
                    obfixr.append((r, str(v), str(t), p, cur, tot / diviv[k]))
    return dict(salv=salv, sums=sums, dceoh=dceoh, objscc=objscc, iad=iad, sums3s=sums3s, corsd=corsd, crfd_d=crfd_d, salvs=salvs,
                salvdec=salvdec, cdec=cdec, obinv=obinv, obfix=obfix, cinv=cinv, cfix=cfix, obfixr=obfixr)


def eoh_tables(X, life, dlc_v):
    """The tables that depend on the end of the horizon, as rows."""
    return {
        "COEF_OBFIXR": X["obfixr"],
        "OBJ_CFIX": X["cfix"],
        "SALV_INV": [(r, str(v), p, str(y), x) for (r, v, p, y), x in X["salv"].items() if x],
        "OBJ_SUMS": [(r, str(v), p) for (r, v, p) in X["sums"]],
        "OBJSCC": [(r, str(v), p, cur, x) for (r, v, p, cur), x in X["objscc"].items()],
        "OBJ_DCEOH": [(r, cur, x) for (r, cur), x in X["dceoh"].items() if x],
        "OBJ_IAD": [(r, cur, x) for (r, cur), x in X["iad"].items() if x],
        "OBJ_SUMS3": [(r, str(v), p) for (r, v, p) in X["sums3s"]],
        "COR_SALVD": [(r, str(v), p, cur, x) for (r, v, p, cur), x in X["corsd"].items()],
        "OBJ_CRFD": [(r, str(v), p, cur, x) for (r, v, p, cur), x in X["crfd_d"].items() if x],
        "SALV_DEC": [(r, str(v), p, cur, x) for (r, v, p, cur), x in X["salvdec"].items()],
        "OBJ_LIFE": [(str(y), r, str(j), str(l), cur, x) for (y, r, j, l, cur), x in life.items()],
    } | ({"OBJ_SALVS": [(r, str(v), p, cur, x) for (r, v, p, cur), x in X["salvs"].items()]} if dlc_v else {})


def step_tables(db: DB, R: Steps, miyr, fwd):
    """solve.stp, for a window ending in MIYR_VL = miyr:
    Y_EOH(EOHYEARS)$((YEARVAL(EOHYEARS) <= MIYR_VL)$(YEARVAL(EOHYEARS) >= MINYR)) = YES;
    OBJ_LIFE(K(LL),R,JOT,LIFE,CUR)$OBJ_LIFE(K,R,JOT,LIFE,CUR) = SUM((OPYEAR(LIFE,AGE),Y_EOH(LL+(ORD(AGE)-1))),OBJ_DISC(R,Y_EOH,CUR))+EPS;
    $BATINCLUDE eqobsalv.mod STP EXIT"""
    I, V, F, Y_EOH0 = R.inputs, R.investment, R.fixed, R.Y_EOH0
    DISC, objlife, dlc_v = I.DISC, F.objlife, V.dlc_v
    Y = {y for y in Y_EOH0 if y <= miyr}
    life = {(y, r, jot, lf, cur): sum(DISC.get((r, yy, cur), 0.0) for yy in range(y, y + lf) if yy in Y)
            for (y, r, jot, lf, cur) in objlife}                    # (a value of 0 is stored: EPS)
    return Y, eoh_tables(eoh(db, I, V, F, miyr, Y, life, fwd), life, dlc_v)


def _write_tables(db: DB, I: Inputs, V: Investment, F: FixedCosts, X):
    """The objective's tables into the database: the end-of-horizon tables of eoh (in a myopic run the salvage is
    left to the steps), the sets and coefficients of investment and fixed costs, those of the annualised form with
    OBJANN=YES, the sets the report sums over, the cost coefficients of user constraints (CST_ANNC, UC_ICOST) and of
    the bounds on undiscounted costs (REG_BNDCST, REG_CUMCST: prep/bndcst.py). Also the records a myopic step needs,
    on db.obj_steps."""
    s, ctl = db.s, db.ctl
    classic, annual, K_EOH, T, DELIF, ICO, ISU, ITX = I.classic, I.annual, I.K_EOH, I.T, I.DELIF, I.ICO, I.ISU, I.ITX
    DCC, yr = I.DCC, I.yr
    icur, dlc_v, fcur, cor, crf, opasti, sumii = V.icur, V.dlc_v, V.fcur, V.cor, V.crf, V.opasti, V.sumii
    invspred, jd, wd, divi, diviii, sumiii = V.invspred, V.jd, V.wd, V.divi, V.diviii, V.sumiii
    yes2, diviv, ishpr, rtp_shape, rtp_shape2 = F.yes2, F.diviv, F.ishpr, F.rtp_shape, F.rtp_shape2
    rtp_shape3, sumiv, sumivs, lifekeys, objlife = F.rtp_shape3, F.sumiv, F.sumivs, F.lifekeys, F.objlife
    FOM, FTX, FSB, SHP, MUL, invstep2 = I.FOM, I.FTX, I.FSB, I.SHP, I.MUL, F.invstep2
    salv, sums, dceoh, objscc, iad, sums3s, corsd, crfd_d, salvdec, cdec, obinv, obfix, cinv, cfix, obfixr = (
        X[k] for k in ("salv", "sums", "dceoh", "objscc", "iad", "sums3s", "corsd", "crfd_d", "salvdec", "cdec", "obinv", "obfix", "cinv", "cfix", "obfixr"))
    SALVAGE = ("SALV_INV", "OBJ_SUMS", "OBJSCC", "OBJ_DCEOH", "OBJ_IAD", "OBJ_SUMS3", "COR_SALVD", "OBJ_CRFD", "SALV_DEC", "OBJ_SALVS")
    Y_EOH0 = yr("select y from EOHYEARS where yv(y) >= {MINYR}".format(MINYR=s["MINYR"]))
    db.obj_steps = Steps(I, V, F, Y_EOH0)

    def store(name, rows):
        db.clear(name)
        _load(db, name, rows)
    db.declare("COEF_OBFIXR", "par", ["R", "ALLYEAR", "T", "P", "CUR"])
    db.declare("OBJ_CINV", "par", ["R", "ALLYEAR", "P", "CUR"])
    db.declare("OBJ_CFIX", "par", ["R", "ALLYEAR", "P", "CUR"])
    if dlc_v:                       # port-only: salvage of the surveillance costs (a model without NCAP_DLAGC has no table)
        db.declare("OBJ_SALVS", "par", ["R", "ALLYEAR", "P", "CUR"])
    # a myopic run leaves salvage to the steps (eqobsalv.mod: $IF SET TIMESTEP OPTION CLEAR=OBJ_SUMS,...; $IF %STEPPED%==+ $GOTO EQUA)
    for name, rows in eoh_tables(X, objlife, dlc_v).items():
        store(name, [] if (db.ctl.get("TIMESTEP") and name in SALVAGE) else rows)
    store("OBJ_ICUR", [(r, str(v), p, cur) for (r, v, p, cur) in icur])
    store("OBJ_FCUR", [(r, str(v), p, cur) for (r, v, p, cur) in fcur])
    store("COEF_OBINV", obinv if annual else [])        # (TIMES has them only with OBJANN=YES or MACRO)
    store("COEF_OBFIX", obfix if annual else [])
    db.declare("OBJANN", "set", ["UC_NAME"])
    store("OBJ_CINV", cinv)
    if "OBJ_SIC" in db.sym and db.card("OBJ_SIC"):
        # --- eqobjinv.mod 297-299, the uncertain investment cost (stages.stc 235), per unit of OBJ_SIC:
        #     SUM((OBJ_SUMII(R,T,P,LIFE,K_EOH,JOT),SW_TSW(SOW,T,WW))$OBJ_SIC(R,T,P,WW), %CAPJD%
        #       SUM(INVSPRED(K_EOH,JOT,Y,K), OBJ_DISC(R,K,CUR) * OBJ_ICOST(R,K,P,CUR) * (1-SALV_INV(R,T,P,Y))) *
        #       OBJ_SIC(R,T,P,WW) * COR_SALVI(R,T,P,CUR) / OBJ_DIVI(R,T,P) * %VAR%_NCAP(R,T,P %SWD%))
        JDf = (lambda key: 1.0) if classic else (lambda key: jd.get(key, 0.0))     # %CAPJD% empty with CTST ''
        sic = {(r, int(v), p) for r, v, p in db.con.execute("select distinct r, y, p from OBJ_SIC").fetchall()}
        csic = []
        for (r, v, p, cur) in icur:
            k = (r, v, p)
            if k not in sic:
                continue
            x = sum(JDf((r, cur, y0, jot)) * sum(I.DISC.get((r, y, cur), 0.0) * ICO.get((r, p, cur, y), 0.0)
                                                 * (1 - salv.get((r, v, p, mid), 0.0))
                                                 for (mid, y) in invspred.get((y0, jot), ()))
                    for (_, y0, jot) in sumii[k] if y0 in K_EOH)
            if x:
                csic.append((r, str(v), p, cur, x * cor[(r, v, p, cur)] / divi[k]))
        db.declare("OBJ_CSIC", "par", ["R", "ALLYEAR", "P", "CUR"])     # port-only: a model without S_NCAP_COST has no table
        store("OBJ_CSIC", csic)
    store("OBJANN", [("YES",)] if objann(db) else [])
    db.declare("VARCOST_LIN", "set", ["UC_NAME"])                 # port-only: how the equations weight variable costs
    store("VARCOST_LIN", [("YES",)] if ctl["VARCOST"] == "LIN" else [])
    store("COR_SALVI", [(r, str(v), p, cur, x) for (r, v, p, cur), x in cor.items()])
    store("OBJ_CRF", [(r, str(v), p, cur, x) for (r, v, p, cur), x in crf.items()])
    store("OBJ_DIVI", [(r, str(v), p, float(x)) for (r, v, p), x in divi.items()])
    store("OBJ_DIVIV", [(r, str(v), p, float(x)) for (r, v, p), x in diviv.items()])
    store("RTP_ISHPR", [(r, str(v), p) for (r, v, p) in ishpr])
    store("RTP_SHAPE", [(r, str(v), p, t, str(j), str(jj)) for t, sh in (("1", rtp_shape), ("2", rtp_shape2), ("3", rtp_shape3))
                        for (r, v, p), (j, jj) in sh.items()])
    store("OBJ_PASTI", [(r, str(v), p, cur, x) for (r, v, p, cur), x in opasti.items()])
    # With CTST '' nothing clears the work set KAGE after eqobjfix.mod (coef_alt.lin DOFIX does it otherwise):
    # OPTION KAGE <= OBJ_LIFE, the (K, JOT) of the fixed-cost steps before they are copied forward.
    store("KAGE", sorted({(str(y0), str(jot)) for (_r, y0, jot, _l) in lifekeys}) if classic else [])
    store("OBJ_JD", [(r, cur, str(y), str(j), x) for (r, cur, y, j), x in jd.items()])
    store("OBJ_WD", [(r, cur, str(y), str(j), str(yy), x) for (r, cur, y, j, yy), x in wd.items()])
    store("INVSPRED", [(str(y0), str(j), str(mid), str(y)) for (y0, j), st in invspred.items() for (mid, y) in st])
    # The report's COEF_OBJINV sums over this set. The equations used the same rows in memory.
    store("OBJ_SUMII", [(r, str(v), p, str(life), str(y0), str(jot))
                        for (r, v, p), lst in sumii.items() for (life, y0, jot) in lst])
    # The report's fixed cost sums over OBJ_SUMIV (rpt_obj.rpt lines 90 and 101).
    store("OBJ_SUMIV", [(str(y0), r, str(v), p, str(jot), str(life))
                        for (r, v, p), lst in sumiv.items() for (y0, jot, life) in lst])
    # eqobjfix.mod: OPTION OBJ_YES < OBJ_FCUR, then drop offline vintages with no past capacity.
    # cost_ann.rpt line 121 writes this back onto NCAP_YES. With CTST '' eqobjfix.mod line 175
    # clears it (lines 169-175 run only then).
    store("OBJ_YES", [] if classic else [(r, str(v), p) for (r, v, p) in yes2])
    # decommissioning
    store("OBJ_DIVIII", [(r, str(v), p, float(x)) for (r, v, p), x in diviii.items()])
    store("OBJ_SUMIII", [(r, str(v), p, str(ll), str(kk), str(y)) for (r, v, p), lst in sumiii.items() for (ll, kk, y) in lst])
    store("OBJ_SUMIVS", [(r, str(v), p, str(kk), str(y)) for (r, v, p), lst in sumivs.items() for (kk, y) in lst])
    db.declare("OBJ_CDEC", "par", ["R", "ALLYEAR", "P", "CUR"])
    store("OBJ_CDEC", [(r, str(v), p, cur, x) for (r, v, p, cur), x in cdec.items()] if not annual else [])
    # --- eqbndcst.mod: the bounds on undiscounted costs (REG_BNDCST, REG_CUMCST): RT_IAN's single-year bounds take the
    #     annual payments CST_ANNC of their vintages (INV: INVCOST; INVTAX / INVSUB: INVTAXSUB)
    bc = bndcst.prepare(db)
    ian = bc["ian"] if bc else {}
    _cst_annc(db, T, K_EOH, icur, sumii, invspred, crf, divi, ICO, DCC, sumiii, crfd_d, diviii, DELIF, ITX, ISU,
              ian_inv={(r, t, cur) for (r, t, cur), kinds in ian.items() if "INV" in kinds},
              ian_ts={(r, t, cur) for (r, t, cur), kinds in ian.items() if "INVTAXSUB" in kinds})
    _uc_icost(db, T, ICO, ITX, ISU)
    if bc:
        cst = {(r, int(v), p, int(t), a, cur): x for r, v, p, t, a, cur, x in db.q("select * from CST_ANNC")}
        bndcst.ncap_coefficients(db, bc, T, K_EOH, sumii, invspred, crf, divi, sumiii, crfd_d, diviii, DELIF, sumiv,
                                 invstep2, diviv, ICO, ITX, ISU, FOM, FTX, FSB, DCC, (rtp_shape, rtp_shape2, rtp_shape3),
                                 SHP, MUL, cst)
        bndcst.variable_coefficients(db, bc)
    db.bndcst = bc


def _uc_icost(db, T, ICO, ITX, ISU):
    """uc_ncap.mod lines 37-42: the cost attributes COST, TAX and SUB on NCAP multiply the coefficient of new capacity
    in a user constraint by the investment cost, tax or subsidy of its period,
        SUM(RDCUR(R,CUR), ... + OBJ_ICOST(R,%3,P,CUR)$UC_ATTR(R,UC_N,%4,'NCAP','COST')
                              + OBJ_ITAX(R,%3,P,CUR)$UC_ATTR(R,UC_N,%4,'NCAP','TAX')
                              - OBJ_ISUB(R,%3,P,CUR)$UC_ATTR(R,UC_N,%4,'NCAP','SUB'))
    (OBJ_ICOST(r,y,p,cur) = OB_ICOST(r,p,cur,y), coef_obj.mod line 157).  Port-only table UC_ICOST(r,v,p,ucn,cur): those
    values at the milestone years, for the processes with UC_NCAP in a constraint with the attribute, by attribute
    (COST, TAX, SUB); the equations take the sum.  Declared only when a model has such a constraint."""
    q = db.q
    src = {"COST": ICO, "TAX": ITX, "SUB": ISU}
    pairs = q("""select distinct a.ucn, n.r, n.p from UC_NCAP n join UC_ATTR a
                   on a.r=n.r and a.uc=n.uc and a.side=n.side and a.grp='NCAP' and a.ucn in ('COST','TAX','SUB')""")
    if not pairs:
        return
    db.declare("UC_ICOST", "par", ["R", "ALLYEAR", "P", "UC_NAME", "CUR"])
    want = {}
    for ucn, r, p in pairs:
        want.setdefault(ucn, set()).add((r, p))
    rows = []
    for ucn in ("COST", "TAX", "SUB"):
        rp = want.get(ucn, ())
        for (r, p, cur, y), x in src[ucn].items():
            if (r, p) in rp and y in T:
                rows.append((r, str(y), p, ucn, cur, x))
    rows.sort()
    _load(db, "UC_ICOST", rows)


def _net(A, B, C):
    """A + B - C (dicts, a missing key 0.0) for every key of any of them, each value by the expression the sums used
    per lookup: A.get(k, 0.0) + B.get(k, 0.0) - C.get(k, 0.0)."""
    out = {k: a + B.get(k, 0.0) - C.get(k, 0.0) for k, a in A.items()}
    for d in (B, C):
        for k in d:
            if k not in out:
                out[k] = A.get(k, 0.0) + B.get(k, 0.0) - C.get(k, 0.0)
    return out


def _on_record(N, A, B, C, k):
    """Whether the sum N = A + B - C has a record at k: EPS-EPS is EPS (0.0 on record), x-x is 0 and has none."""
    return k in N and (N[k] != 0 or not (A.get(k, 0.0) or B.get(k, 0.0) or C.get(k, 0.0)))


def _eps_grouped(A, B, C, k):
    """Whether A + (B - C) is EPS at k: EPS+(x-x) is EPS, so the grouping of the annualised form keeps what A + B - C loses."""
    a, b, c = A.get(k, 0.0), B.get(k, 0.0), C.get(k, 0.0)
    return a == 0 and b - c == 0 and (k in A or (not (b or c) and (k in B or k in C)))


def _memo(f):
    """f with its results kept by argument (f pure: the same arguments give the same float)."""
    m = {}

    def g(*a):
        x = m.get(a)
        if x is None:
            x = m[a] = f(*a)
        return x
    return g


class _Slices:
    """{key: [(t, value), ...]} over sorted columns: the rows of one key are a slice, made into its list on demand."""
    __slots__ = ("at", "t", "x")

    def __init__(self, keys, t, x):
        self.at, self.t, self.x = {}, t, x
        i0, prev = 0, None
        for i, k in enumerate(keys):
            if k != prev:
                if prev is not None:
                    self.at[prev] = (i0, i)
                i0, prev = i, k
        if prev is not None:
            self.at[prev] = (i0, len(keys))

    def get(self, k, default=()):
        a = self.at.get(k)
        return default if a is None else list(zip(self.t[a[0]:a[1]], self.x[a[0]:a[1]]))


def _load(db, name, rows):
    """db.load_rows, with the label columns given to DuckDB as object columns: pandas 3 makes columns of Python strings
    'str' columns by default, which DuckDB reads three times slower (5 million rows in this step on a large model).  The
    values as load_rows gives them (float64: pandas' own type for a column of floats, ints or None)."""
    name = name.upper(); sy = db.sym[name]
    if not rows:
        return
    import pandas as pd
    cols = sy.cols + (["value"] if sy.kind == "par" else [])
    t = time.perf_counter()
    df = pd.DataFrame(rows, columns=cols, dtype=object)
    if sy.kind == "par":
        df["value"] = pd.DataFrame([r[-1:] for r in rows], columns=["value"])["value"]
    db.con.register("ld_", df)
    db.tally("load_rows: frame build", time.perf_counter() - t, len(df))
    db.x(f'insert into "{name}" select * from ld_', kind="load_rows: frame -> duckdb")
    db.hand["load_rows: frame -> duckdb"][2] += len(df)
    db.con.unregister("ld_")


def _cols(db, sql, n):
    """The n columns of a query's result as Python lists, in the order of its rows.  fetchnumpy and tolist take half
    the time of fetchall's tuples on the millions of cost and lifetime records read here (9 million on a large model), and
    give the same values (a NULL is None either way)."""
    r = db.x(sql)
    t = time.perf_counter()
    a = r.fetchnumpy()
    out = [a[k].tolist() for k in list(a)[:n]]
    db.tally("fetch", time.perf_counter() - t, len(out[0]) if out else 0)
    return out


def _gsum(terms):
    """SUM(x * w) as GAMS takes it, over the records x (EPS on record as 0.0) with their weights w: the sum when a term
    is not 0; 0.0 (EPS, on record) when every term is EPS times a weight that is not 0; None (no record) when there is
    no term, or the terms are numbers that cancel, or every EPS meets a weight of 0 (0 * EPS is 0)."""
    s, num, eps = 0.0, False, False
    for x, w in terms:
        if x and w:
            s += x * w
            num = True
        elif w:
            eps = True
    if num:
        return s if s else None
    return 0.0 if eps else None


def _cst_annc(db, T, K_EOH, icur, sumii, invspred, crf, divi, ICO, DCC, sumiii, crfd_d, diviii, DELIF, ITX, ISU,
              ian_inv=frozenset(), ian_ts=frozenset()):
    """eqbndcst.mod lines 51-65: the annual undiscounted investment payments CST_ANNC(r,tt,p,t,'INVCOST',cur) of the
    vintages of the processes in user constraints with the INVCOST attribute on NCAP (the ANNUL cost attribute of
    uc_ncap.mod line 39), and (lines 66-77) those of the investment taxes and subsidies, CST_ANNC(..,'INVTAX' / 'INVSUB',..),
    of the processes in constraints with INVTAX or INVSUB; with the vintages t of a single-year cost bound in t
    (RT_IAN(r,t,t,cur,'INV'): ian_inv, 'INVTAXSUB': ian_ts; prep/bndcst.py)."""
    q = db.q
    # --- LOOP(UC_ATTR(R,UC_N,SIDE,'NCAP','INVCOST'),LOOP(T,TRACKP(R,P)$UC_NCAP(UC_N,SIDE,R,T,P)=YES));
    trackp = {(r, p) for r, p in q("""select distinct n.r, n.p from UC_NCAP n join UC_ATTR a
                                        on a.r=n.r and a.uc=n.uc and a.side=n.side and a.grp='NCAP' and a.ucn='INVCOST'
                                      where in_MILESTONYR(n.y)""")}
    rows = []
    if trackp or ian_inv:
        # --- RTP_IAN(OBJ_ICUR(R,T,P,CUR))$(RT_IAN(R,T,T,CUR,'INV')+TRACKP(R,P)) = YES;   (T: the milestone vintages)
        ian = [(r, v, p, cur) for (r, v, p, cur) in icur if v in T and ((r, p) in trackp or (r, v, cur) in ian_inv)]
        for (r, tt, p, cur) in ian:
            k = (r, tt, p)
            # --- CST_ANNC(R,TT,P,T(YEAR),'INVCOST',CUR)$(YK1(TT,T)$RTP_IAN(R,TT,P,CUR)) =
            #       SUM(OBJ_SUMII(R,TT,P,AGE,K_EOH(LL),JOT)$((ORD(LL)+ORD(AGE)+ORD(JOT)-1 > ORD(YEAR))$YK(T,LL)),
            #         SUM(INVSPRED(K_EOH,JOT,ALLYEAR,K)$((ORD(ALLYEAR)+ORD(AGE) > ORD(YEAR))$YK(T,ALLYEAR)),
            #           OBJ_ICOST(R,K,P,CUR)) * OBJ_CRF(R,TT,P,CUR) / OBJ_DIVI(R,TT,P));
            # --- (decommissioning) CST_ANNC(..)$YK1(TT,T) += OBJ_CRFD(R,TT,P,CUR) / OBJ_DIVIII(R,TT,P) *
            #       SUM(OBJ_SUMIII(R,TT,P,K_EOH,K,LL)$((ORD(LL)+ROUND(NCAP_DELIF(R,TT,P)) > ORD(YEAR))$YK(T,LL)), OBJ_DCOST(R,K,P,CUR));
            #     (only for vintages with OBJ_DCOST(R,TT,P,CUR))
            for t in sorted(T):
                if t < tt:
                    continue
                # (a cost given as EPS: SUM(EPS) * OBJ_CRF / OBJ_DIVI is EPS, a record of CST_ANNC; EPS + x is x)
                inv = _gsum((ICO[kk4], 1.0) for (life, y0, jot) in sumii.get(k, ())
                            if y0 in K_EOH and y0 <= t and y0 + life + jot - 1 > t
                            for (mid, kk) in invspred.get((y0, jot), ()) if mid <= t and mid + life > t
                            for kk4 in [(r, p, cur, kk)] if kk4 in ICO)
                c = crf.get((r, tt, p, cur), 0.0)
                val = (inv * c / divi[k] or None) if inv else (0.0 if inv is not None and c else None)
                if (r, p, cur, tt) in DCC:
                    dec = _gsum((DCC[kk4], 1.0) for (_ke, kk, ll) in sumiii.get(k, ())
                                if ll <= t and ll + rnd(DELIF.get(k, 0.0)) > t for kk4 in [(r, p, cur, kk)] if kk4 in DCC)
                    cd = crfd_d.get((r, tt, p, cur), 0.0)
                    if dec:
                        val = ((val or 0.0) + cd / diviii[k] * dec) or None
                    elif dec is not None and cd and val is None:
                        val = 0.0
                if val is not None:
                    rows.append((r, str(tt), p, str(t), "INVCOST", cur, val))
    # --- OPTION CLEAR=TRACKP, CLEAR=RTP_IAN;
    #     LOOP(UC_ATTR(R,UC_N,SIDE,'NCAP',UC_ANNUL(UC_NAME(COSTCAT))),LOOP(T,TRACKP(R,P)$UC_NCAP(UC_N,SIDE,R,T,P)=YES));
    #     (UC_ANNUL in COSTCAT: INVTAX, INVSUB)
    trackp = {(r, p) for r, p in q("""select distinct n.r, n.p from UC_NCAP n join UC_ATTR a
                                        on a.r=n.r and a.uc=n.uc and a.side=n.side and a.grp='NCAP' and a.ucn in ('INVTAX','INVSUB')
                                      where in_MILESTONYR(n.y)""")}
    if trackp or ian_ts:
        # --- RTP_IAN(OBJ_ICUR(R,T,P,CUR))$(RT_IAN(R,T,T,CUR,'INVTAXSUB')+TRACKP(R,P)) = YES;
        ian = [(r, v, p, cur) for (r, v, p, cur) in icur if v in T and ((r, p) in trackp or (r, v, cur) in ian_ts)]
        # --- LOOP(RTP_IAN(R,TT,P,CUR)$(OBJ_ITAX(R,TT,P,CUR)+OBJ_ISUB(R,TT,P,CUR)),
        #       OPTION CLEAR=YKK; F = OBJ_CRF(R,TT,P,CUR)/OBJ_DIVI(R,TT,P);
        #       LOOP(OBJ_SUMII(R,TT,P,LIFE,K_EOH,JOT), Z=ORD(LIFE);
        #         YKK(YK(T(YEAR),LL),K)$((ORD(YEAR) < ORD(LL)+Z)$INVSPRED(K_EOH,JOT,LL,K)) = YES);
        #       CST_ANNC(R,TT,P,T,'INVTAX',CUR)$YK1(TT,T) = SUM(YKK(T,LL,K), F * OBJ_ITAX(R,K,P,CUR));
        #       CST_ANNC(R,TT,P,T,'INVSUB',CUR)$YK1(TT,T) = SUM(YKK(T,LL,K),-F * OBJ_ISUB(R,K,P,CUR));
        # the work set YKK as GAMS leaves it: that of the last pass of the loop, in the order of the labels (OPTION CLEAR=YKK
        # at each pass; YKK(T,LL,K) over every milestone T, before the YK1 condition of the assignments)
        uel = dict(q("select label, ord from __uel"))
        last = None
        for (r, tt, p, cur) in ian:
            # $(OBJ_ITAX(R,TT,P,CUR)+OBJ_ISUB(R,TT,P,CUR)): EPS + 0 is EPS, true
            if _gsum((X[(r, p, cur, tt)], 1.0) for X in (ITX, ISU) if (r, p, cur, tt) in X) is None:
                continue
            key = (uel.get(r, 0), uel.get(str(tt), 0), uel.get(p, 0), uel.get(cur, 0))
            if last is None or key > last[0]:
                last = (key, (r, tt, p))
            k = (r, tt, p)
            f = crf.get((r, tt, p, cur), 0.0) / divi[k]
            for t in sorted(T):
                if t < tt:
                    continue
                # YKK(T,LL,K) is a set: each (LL, K) once, however many investment steps give it
                ykk = sorted({(mid, kk) for (life, y0, jot) in sumii.get(k, ()) if y0 in K_EOH
                              for (mid, kk) in invspred.get((y0, jot), ()) if mid <= t and t < mid + life})
                # (a tax or subsidy given as EPS: F * EPS is EPS, a record)
                tax = _gsum((ITX[k4], f) for (_, kk) in ykk for k4 in [(r, p, cur, kk)] if k4 in ITX)
                sub = _gsum((ISU[k4], -f) for (_, kk) in ykk for k4 in [(r, p, cur, kk)] if k4 in ISU)
                if tax is not None:
                    rows.append((r, str(tt), p, str(t), "INVTAX", cur, tax))
                if sub is not None:
                    rows.append((r, str(tt), p, str(t), "INVSUB", cur, sub))
        if last is not None:
            k = last[1]
            ykk = sorted({(t, mid, kk) for t in T for (life, y0, jot) in sumii.get(k, ()) if y0 in K_EOH
                          for (mid, kk) in invspred.get((y0, jot), ()) if mid <= t and t < mid + life})
            db.clear("YKK")
            _load(db, "YKK", [(str(t), str(mid), str(kk)) for (t, mid, kk) in ykk])
    db.clear("CST_ANNC")
    _load(db, "CST_ANNC", rows)


# ---------------------------------------------------------------------------------------------- the Julia kernel
# the tables the step writes (compared in check mode, those the model has)
_WRITES = ("RTP", "K_EOH", "NCAP_DLIFE", "NCAP_DELIF", "NCAP_TLIFE", "NCAP_ELIFE", "OPYEAR", "OBJ_1A", "OBJ_1B",
           "OBJ_2A", "OBJ_2B", "COEF_OBFIXR", "OBJ_CFIX", "SALV_INV", "OBJ_SUMS", "OBJSCC", "OBJ_DCEOH", "OBJ_IAD",
           "OBJ_SUMS3", "COR_SALVD", "OBJ_CRFD", "SALV_DEC", "OBJ_LIFE", "OBJ_SALVS", "OBJ_ICUR", "OBJ_FCUR",
           "COEF_OBINV", "COEF_OBFIX", "OBJANN", "OBJ_CINV", "VARCOST_LIN", "COR_SALVI", "OBJ_CRF", "OBJ_DIVI",
           "OBJ_DIVIV", "RTP_ISHPR", "RTP_SHAPE", "OBJ_PASTI", "KAGE", "OBJ_JD", "OBJ_WD", "INVSPRED", "OBJ_SUMII",
           "OBJ_SUMIV", "OBJ_YES", "OBJ_DIVIII", "OBJ_SUMIII", "OBJ_SUMIVS", "OBJ_CDEC", "CST_ANNC", "YKK", "UC_ICOST")

# the kernel's tables, in the order objective.jl returns them (OBJ_OUT): per table its integer columns (L a label's
# code, Y an integer stored as its text) and the number of Float64 columns after them
_OBJ_OUT = [("SCAL", "", 1), ("FIXDL", "LYL", 2), ("FIXTL", "LYL", 0), ("FIXEL", "LYL", 0),
            ("COEF_OBFIXR", "LYYLL", 1), ("OBJ_CFIX", "LYLL", 1), ("SALV_INV", "LYLY", 1), ("OBJ_SUMS", "LYL", 0),
            ("OBJSCC", "LYLL", 1), ("OBJ_DCEOH", "LL", 1), ("OBJ_IAD", "LL", 1), ("OBJ_SUMS3", "LYL", 0),
            ("COR_SALVD", "LYLL", 1), ("OBJ_CRFD", "LYLL", 1), ("SALV_DEC", "LYLL", 1), ("OBJ_LIFE", "YLYYL", 1),
            ("OBJ_SALVS", "LYLL", 1), ("OBJ_ICUR", "LYLL", 0), ("OBJ_FCUR", "LYLL", 0), ("COEF_OBINV", "LYLL", 1),
            ("COEF_OBFIX", "LYLL", 1), ("OBJ_CINV", "LYLL", 1), ("COR_SALVI", "LYLL", 1), ("OBJ_CRF", "LYLL", 1),
            ("OBJ_DIVI", "LYL", 1), ("OBJ_DIVIV", "LYL", 1), ("RTP_ISHPR", "LYL", 0), ("RTP_SHAPE", "LYLYYY", 0),
            ("OBJ_PASTI", "LYLL", 1), ("KAGE", "YY", 0), ("OBJ_JD", "LLYY", 1), ("OBJ_WD", "LLYYY", 1),
            ("INVSPRED", "YYYY", 0), ("OBJ_SUMII", "LYLYYY", 0), ("OBJ_SUMIV", "YLYLYY", 0), ("OBJ_YES", "LYL", 0),
            ("OBJ_DIVIII", "LYL", 1), ("OBJ_SUMIII", "LYLYYY", 0), ("OBJ_SUMIVS", "LYLYY", 0), ("OBJ_CDEC", "LYLL", 1),
            ("DLC_V", "", 1)]


def _objective_switch(db: DB):
    """The kernel or the reference, as TIMESPP_KERNELS says (kernels.run). The tables _write_tables declares are
    declared first, in its order (so that check mode can copy them, and the model's tables keep their order)."""
    if getattr(db, "audit", None) is not None:
        return _objective(db)            # audit mode: the guards note and go on, as the reference's do
    db.declare("COEF_OBFIXR", "par", ["R", "ALLYEAR", "T", "P", "CUR"])
    db.declare("OBJ_CINV", "par", ["R", "ALLYEAR", "P", "CUR"])
    db.declare("OBJ_CFIX", "par", ["R", "ALLYEAR", "P", "CUR"])
    if db.card("OB_DLC"):
        db.declare("OBJ_SALVS", "par", ["R", "ALLYEAR", "P", "CUR"])
    db.declare("OBJANN", "set", ["UC_NAME"])
    db.declare("VARCOST_LIN", "set", ["UC_NAME"])
    db.declare("OBJ_CDEC", "par", ["R", "ALLYEAR", "P", "CUR"])
    if not (db.card("REG_CUMCST") or db.card("REG_BNDCST")) and db.q1(
            """select count(*) from UC_NCAP n join UC_ATTR a on a.r=n.r and a.uc=n.uc and a.side=n.side and a.grp='NCAP'
               and a.ucn in ('COST','TAX','SUB')"""):
        db.declare("UC_ICOST", "par", ["R", "ALLYEAR", "P", "UC_NAME", "CUR"])      # (_uc_icost's, after OBJ_CDEC)
    maxlife0 = db.s["MAXLIFE"]

    def ref():
        db.s["MAXLIFE"] = maxlife0
        _objective(db)

    def fast():
        db.s["MAXLIFE"] = maxlife0
        _objective_kernel(db)
    kernels.run("objective", db, [n for n in _WRITES if n in db.sym], ref, fast)


def _objective_kernel(db: DB):
    """The objective in Julia: the same tables as _objective, to the bit. It declines the forms whose records later
    Python reads (a myopic run, cost bounds) and those the reference stops on."""
    import numpy as np
    K = "objective"
    s, ctl, q = db.s, db.ctl, db.q
    classic = ctl["CTST"] == ""
    if not ((ctl["OBLONG"] and ctl["CTST"] == "zero") or (classic and ctl["OBJ"] in ("AUTO", "") and s["ALTOBJ"] in (0, 1))):
        raise kernels.Decline("an objective form that is not ported (the reference stops the run)")
    if ctl.get("TIMESTEP"):
        raise kernels.Decline("a myopic run (its steps read the reference's records, db.obj_steps)")
    if db.card("RTP_CAPVL"):
        raise kernels.Decline("RTP_CAPVL given (the reference stops the run)")
    if db.card("REG_CUMCST") or db.card("REG_BNDCST"):
        raise kernels.Decline("bounds on undiscounted costs (prep/bndcst.py reads the reference's records)")
    if db.q1("select count(*) from NCAP_VALU v where exists(select 1 from NCAP_OCOM o where o.r=v.r and o.p=v.p and o.c=v.c)"):
        raise kernels.Decline("NCAP_VALU with NCAP_OCOM (the reference stops the run)")
    # the processes in user constraints on investment costs (_cst_annc, _uc_icost: their records below)
    uc = db.tmp("t_objuc", """select distinct n.r, n.p from UC_NCAP n join UC_ATTR a on a.r=n.r and a.uc=n.uc and
                               a.side=n.side and a.grp='NCAP' and a.ucn in ('INVCOST','INVTAX','INVSUB','COST','TAX','SUB')""")
    annual = annualised(db)
    lev = str(db.env.get("ANNCOST", "")).strip().strip("'\"").upper() == "LEV"
    DS = 0.5 if ctl["MID_YEAR"] else 0.0
    vnret = bool(s.get("VNRET"))
    shapes = any(db.card(n) for n in ("NCAP_CPX", "NCAP_FOMX", "NCAP_FTAXX", "NCAP_FSUBX", "NCAP_FOMM", "NCAP_FTAXM",
                                     "NCAP_FSUBM"))
    # --- RTP(R,PASTMILE,P)$(NCAP_PASTI(R,PASTMILE,P)=0) = NO;
    db.remove("RTP", where="in_PASTMILE(y) and v_NCAP_PASTI(r,y,p) = 0")
    # --- K_EOH(EACHYEAR)$((YEARVAL(EACHYEAR) >= PYR_V1) * (YEARVAL(EACHYEAR) <= MIYR_VL)) = YES;
    db.assign("K_EOH", "select y from EACHYEAR where yv(y) >= {PYR_V1} and yv(y) <= {MIYR_VL}")
    # ---- the inputs, as _inputs and the stages read them, each in the order of its query
    cols = []

    def add(src, spec, where=None):
        cols.extend(kernels.rows_to_julia(db, K, src, spec, where))

    def empty(spec):
        cols.extend(np.empty(0, np.float64 if k == "V" else np.int32) for _c, k in spec)
    add("ALLYEAR", [("y", "Y")], "y<>'0'")
    for n in ("EACHYEAR", "K_EOH", "Y_EOH", "MILESTONYR", "PASTMILE", "PYR_S", "PASTYEAR"):
        add(n, [("y", "Y")])
    for n in ("B", "E", "M", "D", "IPD"):
        add(n, [("y", "Y"), ("value", "V")])
    rvp = [("r", "L"), ("y", "Y"), ("p", "L")]
    add("select t.r, cast(t.y as integer) as y, t.p from RTP t order by t.r, t.y, t.p", rvp)
    for n in ("NCAP_TLIFE", "NCAP_ELIFE", "COEF_RPTI", "NCAP_PASTI", "NCAP_DLIFE", "NCAP_DELIF", "NCAP_DLAG",
              "NCAP_DRATE", "NCAP_FDR", "NCAP_ILED", "COEF_ILED"):
        add(n, rvp + [("value", "V")])
    add("RTP_OFF", rvp)
    for n in ("OBJ_DISC", "G_DRATE", "OBJ_RFR", "OBJ_PVT"):
        add(n, [("r", "L"), ("y", "Y"), ("cur", "L"), ("value", "V")])
    add("select r, cur from RDCUR order by all", [("r", "L"), ("cur", "L")])
    for n in ("OB_ICOST", "OB_ISUB", "OB_ITAX", "OB_FOM", "OB_FSB", "OB_FTX", "OB_DCC", "OB_DLC"):
        add(n, [("r", "L"), ("p", "L"), ("cur", "L"), ("y", "Y"), ("value", "V")])
    add("PRC_RESID", [("r", "L"), ("p", "L")], "y='0'")
    add("PRC_RESID", rvp + [("value", "V")], "y<>'0'")
    add("""select t.r, cast(t.y as integer) as y, t.p, cast(t.y2 as integer) as y2, t.value
           from COEF_CPT t order by t.r, t.y, t.p, t.y2""", rvp + [("y2", "Y"), ("value", "V")])
    add("select y, y2 from VNT order by all", [("y", "Y"), ("y2", "Y")])
    add("NCAP_CPX", rvp, "y <> '0' and (value <> 0 or isnan(value))")
    add("RTP_CPX", rvp + [("y2", "Y"), ("value", "V")])
    for n in ("NCAP_FOMX", "NCAP_FTAXX", "NCAP_FSUBX", "NCAP_FOMM", "NCAP_FTAXM", "NCAP_FSUBM"):
        add(n, rvp + [("value", "V")], "y <> '0'")
    if shapes:
        add("SHAPE", [("j", "Y"), ("age", "Y"), ("value", "V")])
        add("MULTI", [("j", "Y"), ("y", "Y"), ("value", "V")])
    else:
        empty([("j", "Y"), ("age", "Y"), ("value", "V")] * 2)
    add("PERIODYR", [("y", "Y"), ("y2", "Y")], "in_MILESTONYR(y)")
    add("select distinct r, y, p from NCAP_OCOM", rvp)
    add("G_RCUR", [("r", "L"), ("cur", "L")])
    add("PRC_REFIT", [("r", "L"), ("p", "L"), ("p2", "L"), ("value", "V")], "in_RP(r,p)")
    if vnret:
        add(f"select r, y, p from ({stochastic.rvprl_at_solve_sql(db)}) where y<>'0' order by all", rvp)
        add(f"select {', '.join(db.cols('VNTRT'))} from VNTRT order by all", [(c, "Y") for c in db.cols("VNTRT")])
        add(f"select {', '.join(db.cols('PERIODYR'))} from PERIODYR order by all", [(c, "Y") for c in db.cols("PERIODYR")])
        add(f"""select r, y, y2, p from RTP_CPTYR c where in_PYR_S(y) and in_PRC_RCAP(r,p)
               and not exists(select 1 from ({stochastic.rvprl_at_solve_sql(db)}) k where k.r=c.r and k.y=c.y and k.p=c.p)
               order by all""", [("r", "L"), ("y", "Y"), ("y2", "Y"), ("p", "L")])
    else:
        empty(rvp + [("y", "Y"), ("y2", "Y")] * 2 + [("r", "L"), ("y", "Y"), ("y2", "Y"), ("p", "L")])
    par = np.array([classic, lev, DS, s["MINYR"], s["MIYR_V1"], s["MIYR_VL"], s["ALTOBJ"], vnret, db.card("AGE"),
                    sys.version_info >= (3, 12), s["MAXLIFE"]], np.float64)
    out = kernels.call(K, [par] + cols)
    # ---- the kernel's tables, by name
    T_, i = {}, 0
    for name, spec, nv in _OBJ_OUT:
        T_[name] = (spec, out[i:i + len(spec)], out[i + len(spec):i + len(spec) + nv])
        i += len(spec) + nv
    maxlife_k, max_e, has_e = T_["SCAL"][2][0]
    # INVSPRED's sets in the order the kernel summed over them: Python's own sets, made as _dofix makes them
    t = time.perf_counter()
    _, (y0s, jots, mids, ys), _ = T_["INVSPRED"]
    got = {}
    for k0, jot, mid, y in zip(y0s.tolist(), jots.tolist(), mids.tolist(), ys.tolist()):
        got.setdefault((k0, jot), []).append((mid, y))
    yr = lambda sql: {int(y) for (y,) in q(sql)}
    ALL, Kset, T = yr("select y from ALLYEAR where y<>'0'"), yr("select y from EACHYEAR"), yr("select y from MILESTONYR")
    B = {int(y): int(v) for y, v in q("select y, value from B")}
    D = {int(y): int(v) for y, v in q("select y, value from D")}
    py_sets = {}
    _dofix({(k0, jot): [y for y in range(k0, k0 + jot) if y in ALL] for (k0, jot) in got}, classic, Kset,
           {B[t] for t in T}, {}, {}, py_sets, {}, {}, with_wd=False)
    if any(list(py_sets[key]) != lst for key, lst in got.items()):
        raise kernels.Decline("INVSPRED's order differs from this Python's sets")
    # --- MAXLIFE = MAX(SMAX(T,2*D(T)),Z,CEIL(MAXLIFE)): as the reference has it (its type too: the text in OPYEAR's query)
    z = (int(max_e) if has_e else float("-inf")) - s["MIYR_V1"] + 2
    maxlife = max(max(2 * D[t] for t in T), z, math.ceil(s["MAXLIFE"]))
    if maxlife != maxlife_k:
        raise RuntimeError(f"objective kernel: MAXLIFE {maxlife_k} against {maxlife}")
    kernels.tally(K, "duckdb -> julia", time.perf_counter() - t)
    # ---- the writes, in the reference's order
    t = time.perf_counter()
    nrows = 0

    def nrow(name):
        spec, ints, vals = T_[name]
        return len(ints[0]) if ints else len(vals[0])

    def rel(name, cols_):
        """A select over the kernel's rows of `name` with the columns `cols_`, then its Float64 columns (value, or
        dl and de); the names of those."""
        spec, ints, vals = T_[name]
        lab = [c for c, k in zip(cols_, spec) if k == "L"]
        codes = [a for a, k in zip(ints, spec) if k == "L"]
        other = {f"i{j}": a for j, (a, k) in enumerate(zip(ints, spec)) if k == "Y"}
        sel = [f"cast(f.i{j} as VARCHAR) as {c}" for j, (c, k) in enumerate(zip(cols_, spec)) if k == "Y"]
        names = ["value"] if len(vals) == 1 else ["dl", "de"][:len(vals)]
        other.update(zip(names, vals))
        sel += [f"f.{n}" for n in names]
        return kernels.from_julia(db, "u_", lab, codes, other, ", ".join(sel)), names

    def store(name, keep=True):
        nonlocal nrows
        db.clear(name)
        if not keep or not nrow(name):
            return
        cs = db.cols(name)
        sql, names = rel(name, cs)
        db.x(f'insert into "{name}" select {", ".join(cs + (names if db.sym[name].kind == "par" else []))} from {sql} u_')
        db.con.unregister("u_")
        nrows += nrow(name)
    # --- NCAP_DLIFE(OBJ_SUMS3(R,V,P))$(ROUND(NCAP_DLIFE(R,V,P)) LE 0) = 1;  NCAP_DELIF(OBJ_SUMS3(R,V,P)) = MAX(1,NCAP_DELIF(R,V,P));
    if nrow("FIXDL"):
        sql, _ = rel("FIXDL", ["r", "y", "p"])
        db.x(f"create or replace temp table t_dl as select r, y, p, dl, de from {sql} u_")
        db.con.unregister("u_")
        db.put("NCAP_DLIFE", "select r, y, p, dl as value from t_dl")
        db.put("NCAP_DELIF", "select r, y, p, de as value from t_dl")
    # --- NCAP_TLIFE(OBJ_YES(R,V,P))$(ROUND(NCAP_TLIFE(R,V,P)) LE 0) = 1;   same for NCAP_ELIFE
    for tab, name in (("NCAP_TLIFE", "FIXTL"), ("NCAP_ELIFE", "FIXEL")):
        if nrow(name):
            sql, _ = rel(name, ["r", "y", "p"])
            db.x(f"create or replace temp table t_fix as select r, y, p from {sql} u_")
            db.con.unregister("u_")
            db.put(tab, "select r, y, p, 1 as value from t_fix")
    # --- OPYEAR(LIFE,AGE)$((ORD(AGE) LE ORD(LIFE))$(ORD(LIFE) LE MAXLIFE)) = YES;
    s["MAXLIFE"] = maxlife
    db.add("OPYEAR", f"""select a.age, b.age as age2 from AGE a, AGE b
                         where cast(b.age as INTEGER) <= cast(a.age as INTEGER) and cast(a.age as INTEGER) <= {maxlife}""")
    # --- OBJ_1A(RTP(R,V,P))$((NOT OBJ_I2(R,V,P))$(COEF_RPTI(R,V,P) LT 1.01)) = YES;   OBJ_1B, OBJ_2A, OBJ_2B
    db.assign("OBJ_1A", "select r, y, p from RTP where v_COEF_RPTI(r,y,p) < 1.01 and not in_NCAP_ILED(r,y,p)")
    db.assign("OBJ_1B", "select r, y, p from RTP where in_MILESTONYR(y) and not in_OBJ_1A(r,y,p) and not in_NCAP_ILED(r,y,p)")
    db.assign("OBJ_2A", "select r, y, p from RTP where in_NCAP_ILED(r,y,p) and v_COEF_RPTI(r,y,p) <= 1")
    db.assign("OBJ_2B", "select r, y, p from RTP where in_MILESTONYR(y) and in_NCAP_ILED(r,y,p) and not in_OBJ_2A(r,y,p)")
    s["OBJ_C"] = 0.0
    db.obj_steps = None                     # (a myopic run, which reads it, takes the reference)
    dlc = bool(T_["DLC_V"][2][0][0])
    for name in ("COEF_OBFIXR", "OBJ_CFIX", "SALV_INV", "OBJ_SUMS", "OBJSCC", "OBJ_DCEOH", "OBJ_IAD", "OBJ_SUMS3",
                 "COR_SALVD", "OBJ_CRFD", "SALV_DEC", "OBJ_LIFE") + (("OBJ_SALVS",) if dlc else ()):
        store(name)
    store("OBJ_ICUR")
    store("OBJ_FCUR")
    store("COEF_OBINV", annual)              # (TIMES has them only with OBJANN=YES or MACRO)
    store("COEF_OBFIX", annual)
    store("OBJ_CINV")
    db.clear("OBJANN")
    if objann(db):
        _load(db, "OBJANN", [("YES",)])
    db.clear("VARCOST_LIN")
    if ctl["VARCOST"] == "LIN":
        _load(db, "VARCOST_LIN", [("YES",)])
    for name in ("COR_SALVI", "OBJ_CRF", "OBJ_DIVI", "OBJ_DIVIV", "RTP_ISHPR", "RTP_SHAPE", "OBJ_PASTI", "KAGE",
                 "OBJ_JD", "OBJ_WD", "INVSPRED", "OBJ_SUMII", "OBJ_SUMIV", "OBJ_YES", "OBJ_DIVIII", "OBJ_SUMIII",
                 "OBJ_SUMIVS"):
        store(name)
    store("OBJ_CDEC", not annual)
    # --- eqbndcst.mod CST_ANNC and uc_ncap.mod UC_ICOST, by _cst_annc and _uc_icost, on the records they read, rebuilt
    #     from the kernel's rows in the reference's orders (no cost bounds: those are declined)
    if uc:
        lab = np.empty(kernels.labels(db).n, object)
        kl = db.con.execute("select code, label from __klab").fetchnumpy()
        lab[np.asarray(kl["code"])] = np.asarray(kl["label"], object)

        def rows(name):
            spec, ints, vals = T_[name]
            c_ = [lab[a].tolist() if k == "L" else a.tolist() for a, k in zip(ints, spec)] + [v.tolist() for v in vals]
            return list(zip(*c_))
        icur = rows("OBJ_ICUR")
        sumii, sumiii = {}, {}
        for r, v, p, life, y0, jot in rows("OBJ_SUMII"):
            sumii.setdefault((r, v, p), []).append((life, y0, jot))
        for r, v, p, ll, kk, y in rows("OBJ_SUMIII"):
            sumiii.setdefault((r, v, p), []).append((ll, kk, y))
        crf = {k[:4]: k[4] for k in rows("OBJ_CRF")}
        crfd_d = {k[:4]: k[4] for k in rows("OBJ_CRFD")}
        divi = {k[:3]: k[3] for k in rows("OBJ_DIVI")}
        diviii = {k[:3]: k[3] for k in rows("OBJ_DIVIII")}
        DELIF = {(r, int(y), p): x for r, y, p, x in q("select r, y, p, value from NCAP_DELIF")}
        ob = lambda n: {(r, p, cur, int(y)): x for r, p, cur, y, x in q(
            f"select r, p, cur, y, value from {n} o where exists(select 1 from t_objuc u where u.r=o.r and u.p=o.p)")}
        ICO, ITX, ISU, DCC = ob("OB_ICOST"), ob("OB_ITAX"), ob("OB_ISUB"), ob("OB_DCC")
        K_EOH = yr("select y from K_EOH")
        _cst_annc(db, T, K_EOH, icur, sumii, py_sets, crf, divi, ICO, DCC, sumiii, crfd_d, diviii, DELIF, ITX, ISU)
        _uc_icost(db, T, ICO, ITX, ISU)
    else:
        # --- eqbndcst.mod CST_ANNC: no constraint or bound asks for it
        db.clear("CST_ANNC")
    db.bndcst = None
    kernels.tally(K, "julia -> duckdb", time.perf_counter() - t, nrows)
