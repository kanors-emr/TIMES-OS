# SPDX-License-Identifier: GPL-3.0-or-later
"""resloadc.vda: the residual load curve (GR_VARGEN, GR_THMIN, GR_GENMAP).

The variation of each type of generation (GR_VARGEN by timeslice: RL-DISP the dispatchable residual load, RL-WIND,
RL-SOL, ... the variable types, RL-THMIN the aggregate thermal minimum, RL-TP the years) and the thermal minimum of
the dispatchable processes (GR_THMIN: a level below 1, an amount when negative, 1/x of the online capacity from 1 up),
for the equations EQ_RL_LOAD, EQ_RL_NDIS, EQ_RL_STCAP, EQ_RL_PKCAP and EQ_RL_THMIN (times_eq equations/resloadc.jl).

  prep(db, interp)   the main block, from prep_ext.vda ($IF DEFINED GR_VARGEN)
  coef(db)           the COEF block, first thing of ppm_ext.vda
  equa(db)           the EQUA block (equ_ext.vda, after eqactups.vda): RPS_UPS and the bounds of VAR_RLD

TIMES includes the file when the DD files give GR_VARGEN (DEFINED: a data statement, here: any record).
"""
from ..engine import DB
from .grids import _rows, _set, _par

INF = float("inf")

# sets and parameters declared in resloadc.vda (names of the GAMS domains)
INTERNAL = [
    ("RLDC", "set", ["ITEM"]), ("RLDBD", "set", ["LIM"]), ("GR_RLDC", "set", ["R", "LL"]),
    ("GR_RLGT", "set", ["R", "P", "ITEM"]), ("GR_THBND", "par", ["R", "LL", "P", "LIM"]), ("GR_TP", "par", ["R", "BD"]),
]


def active(db: DB):
    return db.ctl.get("RESLOADC", False)


def _yv(db):
    return {y: float(v) for y, v in db.q("select y, value from YEARVAL")}


def prep(db: DB, interp):
    """resloadc.vda main block (prep_ext.vda)."""
    db.ctl["RESLOADC"] = bool(db.card("GR_VARGEN"))
    if not active(db):
        return
    for name, kind, dom in INTERNAL:
        db.declare(name, kind, dom)
    regs = [r for (r,) in db.q("select r from REG")]
    vg = {(r, s, u, l): v for r, s, u, l, v in _rows(db, "GR_VARGEN")}
    # --- SET RLDC / RL-DISP /;  SET RLDBD(LIM) / UP /;  PARAMETER GR_TP(R,BD) / (SET.R).UP INF /;
    rldc = {"RL-DISP"}
    tp = {(r, "UP"): INF for r in regs}
    # --- GR_RLDC(R,'0') $= SUM((S,RLDC,BD)$GR_VARGEN(R,S,RLDC,BD),1);
    on = {r for (r, s, u, l) in vg if u in rldc}
    # --- GR_TP(R,BD)$=GR_VARGEN(R,'ANNUAL','RL-TP',BD); GR_TP(R,BD)$=GR_TP(R,'FX'); GR_VARGEN(R,S,'RL-TP',BD)=0;
    #     ($= assigns a record given as EPS: GR_TP is then EPS, a record)
    for (r, s, u, l), v in vg.items():
        if s == "ANNUAL" and u == "RL-TP":
            tp[(r, l)] = v
    for r in regs:
        if (r, "FX") in tp:
            for l in ("LO", "UP", "FX"):
                tp[(r, l)] = tp[(r, "FX")]
    vg = {k: v for k, v in vg.items() if k[2] != "RL-TP"}
    # --- GR_RLDC(R,T(TT+1))$((YEARVAL(T)>=GR_TP(R,'LO'))$(YEARVAL(T)<=GR_TP(R,'UP'))) $= GR_RLDC(R,'0');
    #     (TT+1: every period but the first)
    yv = _yv(db)
    T = [y for (y,) in db.q("select y from MILESTONYR order by yv(y)")]
    rl = {(r, "0") for r in on}
    for r in on:
        for t in T[1:]:
            if yv[t] >= tp.get((r, "LO"), 0.0) and yv[t] <= tp.get((r, "UP"), 0.0):
                rl.add((r, t))
    # --- LOOP((R,S,ITEM,BD)$GR_VARGEN(R,S,ITEM,BD),UNCD1(ITEM)=YES); RLDC(UNCD1) = YES;
    rldc |= {u for (r, s, u, l) in vg}
    # --- RLDBD(BD)$=NOT RLDC('RL-THMIN'); GR_VARGEN(R,S,'RL-THMIN',BD) = 0;
    rldbd = {"UP"} | ({"LO", "UP", "FX"} if "RL-THMIN" not in rldc else set())
    vg = {k: v for k, v in vg.items() if k[2] != "RL-THMIN"}
    _set(db, "RLDC", [(u,) for u in rldc])
    _set(db, "RLDBD", [(l,) for l in rldbd])
    _set(db, "GR_RLDC", rl)
    _par(db, "GR_TP", tp)
    _par(db, "GR_VARGEN", vg)
    # --- $BATINCLUDE fillparm GR_THMIN R P ",'0','0','0','0','0'" T RTP(R,T,P) 'GE 0'
    interp.fillparm(db, "GR_THMIN", "T", ("RTP", ("r", "p")))


def coef(db: DB):
    """resloadc.vda COEF (ppm_ext.vda)."""
    if not active(db):
        return
    q = db.q
    rldc = {u for (u,) in q("select u from RLDC")}
    rldbd = {l for (l,) in q("select l from RLDBD")}
    elc = {(r, c) for r, c in q("select r, c from NRG_TMAP where nrg_type='ELC'")}
    # --- TRACKPC(RPC_PG(RP_STD(R,P),C))$(TOP(R,P,C,'OUT')$NRG_TMAP(R,'ELC',C)) = YES;  OPTION TRACKP<TRACKPC;
    trackp = {(r, p) for r, p, c in q("""select g.r, g.p, g.c from RPC_PG g where in_RP_STD(g.r,g.p)
                                           and in_TOP(g.r,g.p,g.c,'OUT')""") if (r, c) in elc}
    # --- GR_THMIN(R,LL,P)$(NOT TRACKP(R,P))=0;
    th = {(r, y, p): v for r, y, p, v in _rows(db, "GR_THMIN") if (r, p) in trackp}
    # --- GR_RLGT(TRACKP(RP),RLDC)$=GR_GENMAP(RP,RLDC);
    gm = {(r, p, u): v for r, p, u, v in _rows(db, "GR_GENMAP")}
    rlgt = {(r, p, u) for (r, p, u), v in gm.items() if (r, p) in trackp and u in rldc}
    # --- OPTION RP_UPL < ACT_UPS, RP_PRC < GR_THMIN;  GR_RLGT(RP_PRC(RP),'RL-DISP')=YES;
    upl = {(r, p, l) for r, p, l in q("select distinct r, p, l from ACT_UPS")}
    prc = {(r, p) for (r, y, p) in th}
    rlgt |= {(r, p, "RL-DISP") for r, p in prc}
    # --- LOOP(RLDC$(NOT SAMEAS('RL-NDIS',RLDC)),GR_RLGT(RP,'RL-NDIS')$GR_RLGT(RP,RLDC)=NO);
    typed = {(r, p) for (r, p, u) in rlgt if u != "RL-NDIS" and u in rldc}
    rlgt -= {(r, p, "RL-NDIS") for r, p in typed}
    # --- RP_PRC(RP)$GR_RLGT(RP,'RL-DISP')$=RP_UPL(RP,'FX');  GR_RLGT(RP_PRC(RP),'RL-THMIN')=YES;
    prc |= {(r, p) for (r, p, u) in rlgt if u == "RL-DISP" and (r, p, "FX") in upl}
    rlgt |= {(r, p, "RL-THMIN") for r, p in prc}
    # --- GR_GENMAP(RP_PRC,'RL-DISP')=NOT RLDC('RL-THMIN');
    for r, p in prc:
        if "RL-THMIN" in rldc:
            gm.pop((r, p, "RL-DISP"), None)
        else:
            gm[(r, p, "RL-DISP")] = 1.0
    # --- RP_PRC(TRACKP(R,P))$SUM(TOP(R,P,C,'IN')$NRG_TMAP(R,'ELC',C),1) = YES;  RP_PRC(CHP)=NO;  TRACKP(RP_PRC)=NO;
    #     GR_RLGT(TRACKP(RP),'RL-NDIS')$(NOT SUM(RLDC$GR_RLGT(RP,RLDC),1)) = YES;
    chp = {(r, p) for r, p in q("select r, p from CHP")}
    cons = {(r, p) for r, p, c in q("select r, p, c from TOP where io='IN'") if (r, c) in elc and (r, p) in trackp}
    gen = trackp - (cons - chp)
    has_type = {(r, p) for (r, p, u) in rlgt if u in rldc}
    rlgt |= {(r, p, "RL-NDIS") for r, p in gen if (r, p) not in has_type}
    # --- GR_THBND(RTP,'FX')$((GR_THMIN(RTP)<0)$GR_THMIN(RTP)) = -GR_THMIN(RTP);
    #     GR_THBND(RTP,'LO')$((GR_THMIN(RTP)<1)$GR_THMIN(RTP)) = MAX(0,GR_THMIN(RTP)+1-1);
    #     GR_THBND(RTP,'UP')$((GR_THMIN(RTP)>=1)$GR_THMIN(RTP)) = 1/GR_THMIN(RTP);
    #     (an EPS GR_THMIN is a LO of EPS+1-1 = 0: no bound)
    rtp = {(r, y, p) for r, y, p in q("select r, y, p from RTP")}
    thb = {}
    for (r, y, p), v in th.items():
        if (r, y, p) not in rtp:
            continue
        if v < 0:
            thb[(r, y, p, "FX")] = -v
        if v < 1 and max(0.0, v + 1 - 1) != 0:
            thb[(r, y, p, "LO")] = max(0.0, v + 1 - 1)
        if v >= 1:
            thb[(r, y, p, "UP")] = 1 / v
    # --- levelling: FOR(Z=CARD(TSLVL)-2 DOWNTO 0, LOOP((ANNUAL(TS(TSL-Z)),TS_GROUP(R,TSL,SL)),
    #       GR_VARGEN(FINEST(R,S),RLDC,BDNEQ(BD))$((NOT GR_VARGEN(R,S,RLDC,BD))$RS_BELOW(R,SL,S)) $= GR_VARGEN(R,SL,RLDC,BD)));
    #     (the levels WEEKLY, SEASON, ANNUAL in turn: a finer level's value is kept)
    vg = {(r, s, u, l): v for r, s, u, l, v in _rows(db, "GR_VARGEN")}
    finest = {(r, s) for r, s in q("select r, s from FINEST")}
    below = {}
    for r, s, s2 in q("select r, s, s2 from RS_BELOW"):
        below.setdefault((r, s), []).append(s2)
    groups = q("select r, tsl, s from TS_GROUP")
    for tsl in ("WEEKLY", "SEASON", "ANNUAL"):
        for r, g, sl in groups:
            if g != tsl:
                continue
            for u in rldc:
                for l in ("LO", "UP"):
                    v = vg.get((r, sl, u, l))
                    if v is None:
                        continue
                    for s in below.get((r, sl), []):
                        if (r, s) in finest and (r, s, u, l) not in vg:
                            vg[(r, s, u, l)] = v
    # --- GR_RLDC(R,'0')$GR_VARGEN(R,'ANNUAL','RL-DISP','FX') = NO;
    rl = {(r, y) for r, y in q("select r, y from GR_RLDC")}
    rl -= {(r, "0") for (r, s, u, l) in vg if s == "ANNUAL" and u == "RL-DISP" and l == "FX"}
    # --- LOOP(R$GR_RLDC(R,'0'), RHS_COMBAL(RTCS_VARC(GR_RLDC(R,T),C,S))$(COM_LIM(R,C,'LO')$NRG_TMAP(R,'ELC',C)) = YES;
    #                            RCS_COMBAL(RHS_COMBAL(GR_RLDC(R,T),C,S),'FX')$NRG_TMAP(R,'ELC',C) = YES);
    #     (the electricity balances become equalities with VAR_COMNET: curtailment)
    _set(db, "GR_RLDC", rl)
    curt = {r for (r, y) in rl if y == "0"}
    if curt:
        lo = {(r, c) for r, c in q("select r, c from COM_LIM where l='LO'")}
        add = [(r, y, c, s) for r, y, c, s in q("select r, y, c, s from RTCS_VARC")
               if r in curt and (r, y) in rl and (r, c) in lo and (r, c) in elc]
        if add:
            db.x("create or replace temp table t_rlhs (r VARCHAR, y VARCHAR, c VARCHAR, s VARCHAR)")
            db.insert_rows("t_rlhs", sorted(set(add)))
            db.add("RHS_COMBAL", "select * from t_rlhs")
        db.add("RCS_COMBAL", """select h.r, h.y, h.c, h.s, 'FX' as l from RHS_COMBAL h
                                where in_GR_RLDC(h.r,h.y) and in_GR_RLDC(h.r,'0') and in_NRG_TMAP(h.r,'ELC',h.c)""")
    # --- GR_VARGEN(R,ANNUAL,RLDC,'FX') = 1-DIAG('RL-DISP',RLDC);
    for r in [r for (r,) in q("select r from REG")]:
        for u in rldc:
            if u == "RL-DISP":
                vg.pop((r, "ANNUAL", u, "FX"), None)
            else:
                vg[(r, "ANNUAL", u, "FX")] = 1.0
    # --- LOOP(RLDBD(BDNEQ(BD)),ACT_UPS(RTP,ANNUAL(S),'FX')$GR_THBND(RTP,BD)=MAX(GR_THBND(RTP,BD),ACT_UPS(RTP,S,'FX'));
    #       GR_THBND(R,LL,P,BD)$RP_UPL(R,P,'FX')=0)
    ups = {(r, y, p, s, l): v for r, y, p, s, l, v in _rows(db, "ACT_UPS")}
    for bd in ("LO", "UP"):
        if bd not in rldbd:
            continue
        for (r, y, p, b), v in list(thb.items()):
            if b == bd:
                ups[(r, y, p, "ANNUAL", "FX")] = max(v, ups.get((r, y, p, "ANNUAL", "FX"), 0.0))
        for k in [k for k in thb if k[3] == bd and (k[0], k[2], "FX") in upl]:
            del thb[k]
    # --- IF(RLDBD('FX'),FLO_BND(RTP(R,T,P),C,S,'LO')$(RPC_PG(R,P,C)$NRG_TMAP(R,'ELC',C)$PRC_TS(R,P,S)$GR_THBND(RTP,'FX')) =
    #        MAX(FLO_BND(RTP,C,S,'LO'),GR_THBND(RTP,'FX')*PRC_CAPACT(R,P)*G_YRFR(R,S)));
    if "FX" in rldbd and any(k[3] == "FX" for k in thb):
        pg = {}
        for r, p, c in q("select r, p, c from RPC_PG"):
            if (r, c) in elc:
                pg.setdefault((r, p), []).append(c)
        pts = {}
        for r, p, s in q("select r, p, s from PRC_TS"):
            pts.setdefault((r, p), []).append(s)
        capact = {(r, p): v for r, p, v in _rows(db, "PRC_CAPACT")}
        yrfr = {(r, s): v for r, s, v in _rows(db, "G_YRFR")}
        fb = {(r, y, p, c, s, l): v for r, y, p, c, s, l, v in _rows(db, "FLO_BND")}
        for (r, y, p, b), v in thb.items():
            if b != "FX":
                continue
            for c in pg.get((r, p), []):
                for s in pts.get((r, p), []):
                    fb[(r, y, p, c, s, "LO")] = max(fb.get((r, y, p, c, s, "LO"), 0.0),
                                                    v * capact.get((r, p), 0.0) * yrfr.get((r, s), 0.0))
        _par(db, "FLO_BND", fb)
    # --- OPTION GR_THMIN < GR_THBND;
    th = {(r, y, p): 1.0 for (r, y, p, b) in thb}
    _set(db, "GR_RLGT", rlgt)
    _par(db, "GR_GENMAP", gm)
    _par(db, "GR_THBND", thb)
    _par(db, "GR_VARGEN", vg)
    if ups != {(r, y, p, s, l): v for r, y, p, s, l, v in _rows(db, "ACT_UPS")}:
        _par(db, "ACT_UPS", ups)
    _par(db, "GR_THMIN", th)


def equa(db: DB):
    """resloadc.vda EQUA (equ_ext.vda): RPS_UPS of processes with a thermal minimum per capacity, the bounds of VAR_RLD."""
    if not active(db):
        return
    # --- RPS_UPS(R,P,S)$SUM(RTP(R,V,P)$GR_THBND(RTP,'LO'),1)=NO;
    db.remove("RPS_UPS", where="exists(select 1 from GR_THBND b where b.r=RPS_UPS.r and b.p=RPS_UPS.p and b.l='LO' and in_RTP(b.r,b.y,b.p))")
    # --- %VAS%_RLD.LO(R,T,S,'RL-DISP'%SOW%)=-INF;
    db.x('create or replace table "B_VAR_RLD" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, lower DOUBLE, upper DOUBLE)')
    rows = [(r, t, s, "RL-DISP", -INF, INF)
            for (r,) in db.q("select r from REG") for (t,) in db.q("select y from MILESTONYR")
            for (s,) in db.q("select * from ALL_TS")]
    if rows:
        db.insert_rows('"B_VAR_RLD"', sorted(rows))
    db.bounds.add("VAR_RLD")
