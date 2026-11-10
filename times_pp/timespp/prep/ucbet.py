# SPDX-License-Identifier: GPL-3.0-or-later
"""ucbet.vda: maximum activities and flows of user constraints (UC_FLOBET, UC_ACTBET).

The variable of a user constraint, VAR_UC (or VAR_UCR by region), is kept at least the weighted flows (UC_FLOBET) or
activities (UC_ACTBET) over its periods UC_T_SUM: EQG_UCMAX, and EQG_UCSUMAX that sums the regional ones (times_eq
equations/ucbet.jl). The constraint itself becomes a sum over all regions and loses its timeslice sum.

  init(db)           init_ext.vda: UC_ACTBET into UC_FLOBET on ACT, UC_GMAP_P
  prep(db, interp)   prep_ext.vda: fillparm UC_FLOBET
  equa(db)           the preprocessing of ucbet.vda (equ_ext.vda, before the solve: in the final sets)

TIMES includes the file when UC_FLOBET is DEFINED: the DD files give it, or UC_ACTBET.
"""
from ..engine import DB
from .grids import _rows, _set

INTERNAL = [("UC_GMAX", "set", ["UC_N", "ALL_R", "ITEM", "C", "ITEM"]), ("UC_GMAXR", "set", ["ALL_R", "UC_N"])]


def active(db: DB):
    return db.ctl.get("UCBET", False)


def init(db: DB):
    """init_ext.vda 131-132."""
    db.ctl["UCBET"] = bool(db.card("UC_FLOBET") or db.card("UC_ACTBET"))
    if not db.card("UC_ACTBET"):
        return
    # --- UC_FLOBET(UC_N,ALL_R,YEAR,P,%PGPRIM%) $= UC_ACTBET(UC_N,ALL_R,YEAR,P);
    #     LOOP((UC_N,R,YEAR,P)$UC_ACTBET(UC_N,R,YEAR,P),UC_GMAP_P(R,UC_N,'ACT',P)=YES);
    db.put("UC_FLOBET", "select uc, r, y, p, 'ACT' as cg, value from UC_ACTBET", zero="eps")
    db.add("UC_GMAP_P", "select distinct r, uc, 'ACT' as grp, p from UC_ACTBET where in_REG(r)")


def prep(db: DB, interp):
    """prep_ext.vda 35: $IF DEFINED UC_FLOBET $BATINCLUDE fillparm UC_FLOBET 'UC_N,R' 'P,C' ",'0','0','0'" T 1 'GE 0'"""
    if active(db):
        interp.fillparm(db, "UC_FLOBET", "T", None)


def equa(db: DB):
    """ucbet.vda, the preprocessing before the equations (equ_ext.vda 99)."""
    if not active(db):
        return
    for name, kind, dom in INTERNAL:
        db.declare(name, kind, dom)
    q = db.q
    regs = [r for (r,) in q("select r from REG")]
    T = {t for (t,) in q("select y from MILESTONYR")}
    bet = [(uc, r, y, p, c) for uc, r, y, p, c, v in _rows(db, "UC_FLOBET") if r in regs and y in T]
    # --- LOOP((UC_N,R,T,P,C)$UC_FLOBET(UC_N,R,T,P,C),UNCD1(UC_N)=YES);  UC_GMAXR(UC_R_EACH) = YES;  UC_R_SUM(R,UC_N(UNCD1)) = YES;
    ucs = sorted({b[0] for b in bet})
    gmaxr = {(r, uc) for r, uc in q("select r, uc from UC_R_EACH")}
    if ucs:
        db.x("create or replace temp table t_ucb (uc VARCHAR)")
        db.insert_rows("t_ucb", [(u,) for u in ucs])
        db.add("UC_R_SUM", "select g.r, u.uc from REG g, t_ucb u")
    # --- LOOP((UC_N,R,T,P,C)$UC_FLOBET(UC_N,R,T,P,C),
    #       IF(SAMEAS(%PGPRIM%,C), IF(UC_ATTR(R,UC_N,'LHS','ACT','N'), UC_GMAX(UC_N,'IMPEXP',P,C,'EACH') = YES;
    #                                                                  ELSE UC_GMAX(UC_N,R,P,C,'EACH') = YES);
    #       ELSE IF(UC_GMAXR(R,UC_N), UC_GMAX(UC_N,R,'N',C,'N') = YES; ELSE UC_GMAX(UC_N,'IMPEXP','N',C,'N') = YES)));
    attr_n = {(r, uc) for r, uc in q("select r, uc from UC_ATTR where side='LHS' and grp='ACT' and ucn='N'")}
    gmax = set()
    for uc, r, y, p, c in bet:
        if c == "ACT":
            gmax.add((uc, "IMPEXP", p, c, "EACH") if (r, uc) in attr_n else (uc, r, p, c, "EACH"))
        else:
            gmax.add((uc, r, "N", c, "N") if (r, uc) in gmaxr else (uc, "IMPEXP", "N", c, "N"))
    # --- LOOP(R,UC_GMAXR('IMPEXP',UC_N)$UC_GMAXR(R,UC_N) = YES);
    gmaxr |= {("IMPEXP", uc) for (r, uc) in gmaxr if r in regs}
    # --- LOOP(UC_GMAX(UC_N,ALL_R,ITEM,C,NAME),RXX('IMPEXP',UC_N,ALL_R) = YES);  UC_GMAXR(ALL_R,UC_N)$(NOT RXX('IMPEXP',UC_N,ALL_R)) = NO;
    used = {(r, uc) for (uc, r, i, c, n) in gmax}
    gmaxr &= used
    _set(db, "UC_GMAX", gmax)
    _set(db, "UC_GMAXR", gmaxr)
    # --- UC_TS_SUM(R,UC_N(UNCD1),S) = NO;
    if ucs:
        db.remove("UC_TS_SUM", where="in_REG(r) and uc in (select uc from t_ucb)")
