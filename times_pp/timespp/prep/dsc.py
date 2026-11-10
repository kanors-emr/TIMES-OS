# SPDX-License-Identifier: GPL-3.0-or-later
"""The DSC extension: discrete and semi-continuous capacity additions (init_ext.dsc, prep_ext.dsc, ppm_ext.dsc,
mod_vars.dsc, equ_ext.dsc).

NCAP_DISC(r,t,p,unit) gives the sizes of the units of p that can be built in t (VAR_DNCAP, an SOS1 set over the units,
unit 0 the choice of none, EQ_DSCONE), NCAP_SEMI(r,t,p) the lower bound of a semi-continuous investment (VAR_SNCAP);
EQ_DSCNCAP ties VAR_NCAP to them (times_eq equations/dsc.jl). The model is a MIP.

  init(db)           init_ext.dsc
  prep(db, interp)   prep_ext.dsc
  ppm(db)            ppm_ext.dsc
  bounds(db)         mod_vars.dsc: the bounds of VAR_SNCAP

TIMES loads the extension when the run file sets DSC or DSCAUTO to YES (initmty.mod 453, 467); without it NCAP_DISC
is not even declared, and NCAP_SEMI / PRC_DSCNCAP are refused here.
"""
from ..controls import dsc_on, switch, unsupported
from ..engine import DB
from .grids import _rows, _par

INF = float("inf")


def on(db: DB):
    return dsc_on(db.env)


def active(db: DB):
    return db.ctl.get("DSC", False)


def init(db: DB):
    """init_ext.dsc."""
    given = [n for n in ("PRC_DSCNCAP", "NCAP_SEMI", "NCAP_DISC", "PRC_SEMI") if db.card(n)]
    db.ctl["DSC"] = False
    if not given:
        return
    if not on(db):
        if switch(db.env, "DSC"):                   # $SET DSC NO: the unit sizes are not used; PRC_DSCNCAP stays (pp_reduce)
            db.zap("NCAP_DISC")
            return
        unsupported(db, "discrete capacity without the DSC extension (the run file sets neither DSC nor DSCAUTO)", given)
        return
    defined_dsc = bool(db.card("PRC_DSCNCAP"))
    T = [y for (y,) in db.q("select y from MILESTONYR order by try_cast(y as double)")]
    disc = {(r, y, p, u): v for r, y, p, u, v in _rows(db, "NCAP_DISC")}
    # --- $IF DEFINED PRC_DSCNCAP NCAP_DISC(R,T--ORD(T),P,'0')$PRC_DSCNCAP(R,P) = EPS;    (T--ORD(T): the last period)
    if defined_dsc and T:
        for r, p in db.q("select r, p from PRC_DSCNCAP where in_REG(r)"):
            disc[(r, T[-1], p, "0")] = 0.0
    # --- OPTION PRC_SEMI<NCAP_SEMI; NCAP_SEMI(R,'0',P)$((NCAP_SEMI(R,'0',P)=0)$PRC_SEMI(R,P)) = 10;
    semi = {(r, y, p): v for r, y, p, v in _rows(db, "NCAP_SEMI")}
    psemi = {(r, p): 1.0 for (r, y, p) in semi}
    for (r, p) in psemi:
        if not semi.get((r, "0", p)):
            semi[(r, "0", p)] = 10.0
    # --- $IFE CARD(NCAP_SEMI) PRC_SEMI(R,P) $= NCAP_SEMI(R,'0',P); NCAP_DISC(R,LL,P,'0') $= NCAP_SEMI(R,LL,P);
    #     ($= copies every record, one given as EPS too: NCAP_DISC is then EPS, a record)
    if semi:
        for (r, y, p), v in semi.items():
            if y == "0":
                psemi[(r, p)] = v
        for (r, y, p), v in semi.items():
            disc[(r, y, p, "0")] = v
    _par(db, "NCAP_SEMI", semi)
    _par(db, "PRC_SEMI", psemi)
    _par(db, "NCAP_DISC", disc)
    # --- $IFI %DSCAUTO%==YES  $IF DEFINED NCAP_DISC OPTION PRC_DSCNCAP < NCAP_DISC;
    #     (DSCAUTO is set by initmty.mod 454 in every run that loads the extension)
    if disc:
        db.assign("PRC_DSCNCAP", "select distinct r, p from NCAP_DISC")
    # --- $IF %DSC%==YES $SETGLOBAL SOLMIP YES
    db.ctl["DSC"] = True
    db.ctl["SOLMIP"] = True


def prep(db: DB, interp):
    """prep_ext.dsc."""
    if not active(db):
        return
    # --- PRC_DSCNCAP(R,P) $= PRC_SEMI(R,P);
    db.add("PRC_DSCNCAP", "select r, p from PRC_SEMI where value <> 0")
    # --- $BATINCLUDE prepparm NCAP_DISC 'R' 'P,UNIT' ",'0','0','0'" MILESTONYR 'RTP(R,MILESTONYR,P)' 1
    interp.prepparm(db, "NCAP_DISC", "T", ("RTP", ("r", "p")), 1)
    # --- NCAP_SEMI(RTP(R,T,P))$PRC_DSCNCAP(R,P) = (NCAP_DISC(RTP,'0')+1)-1;
    #     NCAP_SEMI(RTP)$SUM(UNIT(J)$NCAP_DISC(RTP,UNIT),1) = 0;
    disc = {(r, y, p, u): v for r, y, p, u, v in _rows(db, "NCAP_DISC")}
    semi = {(r, y, p): v for r, y, p, v in _rows(db, "NCAP_SEMI")}
    dsc = {(r, p) for r, p in db.q("select r, p from PRC_DSCNCAP")}
    rtp = [(r, y, p) for r, y, p in db.q("select r, y, p from RTP where in_MILESTONYR(y)")]
    units = {}
    for (r, y, p, u) in disc:
        if u != "0":
            units[(r, y, p)] = True
    for (r, y, p) in rtp:
        if (r, p) in dsc:
            v = (disc.get((r, y, p, "0"), 0.0) + 1) - 1
            if v != 0:
                semi[(r, y, p)] = v
            else:
                semi.pop((r, y, p), None)
        if units.get((r, y, p)):
            semi.pop((r, y, p), None)
    _par(db, "NCAP_SEMI", semi)


def ppm(db: DB):
    """ppm_ext.dsc: NCAP_DISC(RTP(R,T,P),'0')$PRC_DSCNCAP(R,P) = EPS$(NOT NCAP_SEMI(R,T,P));"""
    if not active(db):
        return
    disc = {(r, y, p, u): v for r, y, p, u, v in _rows(db, "NCAP_DISC")}
    semi = {(r, y, p) for r, y, p, v in _rows(db, "NCAP_SEMI") if v != 0}
    dsc = {(r, p) for r, p in db.q("select r, p from PRC_DSCNCAP")}
    for r, y, p in db.q("select r, y, p from RTP where in_MILESTONYR(y)"):
        if (r, p) not in dsc:
            continue
        if (r, y, p) in semi:
            disc.pop((r, y, p, "0"), None)
        else:
            disc[(r, y, p, "0")] = 0.0
    _par(db, "NCAP_DISC", disc)


def bounds(db: DB):
    """mod_vars.dsc: VAR_SNCAP.LO(R,T,P) $= NCAP_SEMI(R,T,P);
    VAR_SNCAP.UP(R,T,P)$NCAP_SEMI(R,T,P) = MAX(NCAP_SEMI(R,T,P),NCAP_BND(R,T,P,'UP'));"""
    if not active(db):
        return
    up = {(r, y, p): v for r, y, p, l, v in _rows(db, "NCAP_BND") if l == "UP"}
    T = {y for (y,) in db.q("select y from MILESTONYR")}
    rows = [(r, y, p, v, max(v, up.get((r, y, p), 0.0))) for r, y, p, v in _rows(db, "NCAP_SEMI") if v != 0 and y in T]
    db.x('create or replace table "B_VAR_SNCAP" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, lower DOUBLE, upper DOUBLE)')
    if rows:
        db.insert_rows('"B_VAR_SNCAP"', sorted(rows))
    db.bounds.add("VAR_SNCAP")
