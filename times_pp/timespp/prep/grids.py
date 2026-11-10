# SPDX-License-Identifier: GPL-3.0-or-later
"""Grid extension of VEDA-TIMES: powerflo.vda (grid nodes, generation and demand allocation to the nodes) and
gasgrids.vda (gas pipelines with pressures, Weymouth flows and linepack).

The extension is on (POWERFLO) when the DD files give PRC_REACT, GR_PTDF or GG_KGF (init_ext.vda).

  prep(db, interp)   powerflo.vda PREP      inter-/extrapolation, called from prep_ext.vda
  main(db)           powerflo.vda + gasgrids.vda main blocks, at the end of pp_prelv.vda
  decl(db)           powerflo.vda DECL + gasgrids.vda DECL (mod_vars.mod): control sets and variable bounds

Ported: the gas grids (nodes given by GG_DENS / GG_PRBD), the allocation of supply and demand by GR_GENFR,
GR_GENMAP and GR_ENDFR, the DC power flow by transfer factors (GR_PTDF, with candidate lines) and by phase angles
(line reactances PRC_REACT, GR_ADMIT), and the N-1 bound GR_XBND on lines within a region.  The nodal demand
fractions GR_DEMFR and the nodal balance costs COM_CSTBAL are not ported yet: they stop the run.
"""
import math
from dataclasses import dataclass
from ..controls import unsupported
from ..engine import DB


EPS = 0.0          # an EPS value in a parameter table: a row with value 0


# sets and parameters declared in powerflo.vda / gasgrids.vda (names of the GAMS domains; see engine.columns_for)
INTERNAL = [
    ("RP_GRID", "set", ["R", "P"]), ("RC_GRID", "set", ["R", "T", "C"]),
    ("GR_TOP", "set", ["ALL_REG", "C", "ALL_REG", "C", "P"]), ("GR_ARC", "set", ["ALL_REG", "C", "ALL_REG", "C"]),
    ("GR_GRID", "set", ["J", "R", "COM"]), ("GR_ALLMAP", "set", ["R", "CG", "C"]),
    ("GR_PRCMAP", "set", ["R", "P", "C", "ITEM"]), ("GR_CMAP", "set", ["R", "C", "ITEM"]),
    ("GR_DEMMAP", "set", ["R", "CG", "C"]), ("GR_ALGMAP", "set", ["R", "CG", "CG"]),
    ("GR_ENDC", "set", ["R", "NRG_GRID", "CG"]), ("GR_GENP", "set", ["R", "P"]),
    ("GR_CANDID", "set", ["R", "YEAR", "P"]), ("GR_GNALL", "set", ["R", "T", "C"]),
    ("GR_GMAPC", "set", ["R", "NRG_GRID", "C"]), ("GR_ADO", "set", ["R", "T", "C"]),
    ("GR_SUS", "par", ["ALL_REG", "T", "C", "ALL_REG", "C"]), ("GR_FLOW", "par", ["R", "P", "C"]),
    ("GR_GID", "par", ["R", "C"]), ("GR_ADMIT", "par", ["ALL_REG", "T", "C", "ALL_REG", "C"]),
    ("GR_UNITS", "par", ["R", "T", "ITEM"]), ("GR_CAPUP", "par", ["R", "YEAR", "P"]),
    ("GG_ARC", "set", ["ALL_REG", "C", "ALL_REG", "C"]), ("GG_TOP", "set", ["ALL_R", "C", "ALL_R", "C", "P"]),
    ("GG_LINK", "set", ["ALL_R", "P", "C", "ALL_R", "C"]), ("GG_EDGE", "set", ["ALL_R", "P", "ALL_R"]),
    ("GG_WINK", "set", ["ALL_R", "P", "C", "ALL_R", "C"]), ("GG_RTC", "set", ["R", "YEAR", "C"]),
    ("GG_RTPC", "set", ["R", "MILESTONYR", "P", "C"]), ("GG_WTX", "set", ["R", "P", "C"]),
    ("OMG", "set", ["J"]), ("GG_O", "set", ["J"]), ("GG_VI", "set", ["J"]), ("GG_M1", "par", []),
    ("GG_MM", "par", ["R", "T", "P", "C"]), ("GG_PPM", "par", ["R", "YEAR", "P", "C", "R", "C", "J"]),
    ("GG_PPW", "par", ["R", "YEAR", "P", "C", "R", "C", "J"]),
]


GG_WN = 19          # %GG_WN%: number of alternate Weymouth points


def active(db: DB):
    """init_ext.vda: $IF DEFINED PRC_REACT / $IFE CARD(GR_PTDF)+CARD(GG_KGF) -> $SETGLOBAL POWERFLO YES."""
    return bool(db.card("PRC_REACT") or db.card("GR_PTDF") or db.card("GG_KGF"))


def gas(db: DB):
    """gasgrids.vda is included when CARD(GG_KGF) (at compile time: the DD data)."""
    return db.ctl.get("GASGRID", False)


def init(db: DB):
    """Called from init_ext: the switches of the extension."""
    db.ctl["POWERFLO"] = active(db)
    db.ctl["GASGRID"] = db.ctl["POWERFLO"] and bool(db.card("GG_KGF"))
    db.ctl["SOLMIP"] = db.ctl.get("SOLMIP", False) or (db.ctl["GASGRID"] and bool(db.card("GG_PP")))          # $IFE CARD(GG_PP) $SETGLOBAL SOLMIP YES
    if not db.ctl["POWERFLO"]:
        return
    for name, kind, dom in INTERNAL:
        db.declare(name, kind, dom)
    db.load_rows("OMG", [(str(j),) for j in range(1, 52)])
    db.load_rows("GG_O", [(str(j),) for j in range(1, GG_WN + 1)])
    db.load_rows("GG_VI", [("1",), ("2",), ("99",)])
    db.s["GG_M1"] = 0.0


# ------------------------------------------------------------------------------------------------ CSTBAL
def cstbal(db: DB):
    """powerflo.vda CSTBAL (coef_ext.vda 80): the costs on the components of a commodity's balance (COM_CSTBAL by
    ITEM: PRD, CON, OUT, IMP, EXP, NTX, NPG) as OBJ_COMBAL(r,t,c,s,item,cur) for EQ_OBJBAL:
      a commodity outside the grids:  PRD = PRD+CON+OUT,  IMP = IMP+NTX-PRD,  EXP = EXP-NTX-CON  (and its VAR_COMPRD)
      a grid node (RC_GRID):          GEN = PRD+CON,  NTX = NTX+CON,  IMP / EXP as given,  NPG (the balancer 'FIN')
    each the sum over TS_ANN(TS,S) (the timeslice itself and ANNUAL)."""
    if not db.card("COM_CSTBAL"):
        return
    from ..lvl import lvlfc
    q = db.q
    db.declare("OBJ_COMBAL", "par", ["R", "T", "C", "S", "ITEM", "CUR"])
    # --- $BATINCLUDE pp_lvlfc.mod COM_CSTBAL C COM_TS ',ITEM,CUR' ",'0','0'" ALL_TS T RTC(R,T,C) '' '' N
    lvlfc(db, "COM_CSTBAL", ["c"], "COM_TS", "MILESTONYR", "in_RTC(a.r,a.y,a.c)", fill="N")
    cst = {}
    for r, y, c, s, u, cur, v in q("select r, y, c, s, u, cur, value from COM_CSTBAL"):
        cst[(r, y, c, s, u, cur)] = v
    curs = sorted({k[5] for k in cst})
    tsann = {}
    for ts, s in q("select s, s2 from TS_ANN"):
        tsann.setdefault(ts, []).append(s)
    allmap_c = {(r, c) for r, c, com in q("select r, cg, c from GR_ALLMAP")}
    rc_grid = set(q("select r, y, c from RC_GRID"))
    # --- OPTION TRACKC < COM_CSTBAL;  TRACKC(R,C)$SUM(GR_ALLMAP(R,C,COM),1)=NO;
    trackc = {(k[0], k[2]) for k in cst} - allmap_c
    out = {}

    def put(key, terms):
        """key = the sum of terms [(sign, item)] over TS_ANN; a zero of only EPS inputs is EPS (kept), a zero of
        values cancelling is no record (GAMS's =)."""
        r, t, c, ts, item, cur = key
        tot, rec, nz = 0.0, False, False
        for s in tsann.get(ts, ()):
            for sg, u in terms:
                k = (r, t, c, s, u, cur)
                if k in cst:
                    rec = True
                    nz = nz or cst[k] != 0
                    tot += sg * cst[k]
        if tot != 0 or (rec and not nz):
            out[key] = tot
        else:
            out.pop(key, None)
    varc = list(q("select r, y, c, s from RTCS_VARC"))
    # --- OBJ_COMBAL(RTCS_VARC(RTC(R,T,C),TS),'PRD',CUR)$TRACKC(R,C) = SUM(TS_ANN(TS,S),COM_CSTBAL(..'PRD'..)+(..'CON'..)+(..'OUT'..));
    #     ... 'IMP' = IMP+NTX-PRD;  'EXP' = EXP-NTX-CON
    for (r, t, c, ts) in varc:
        if (r, c) not in trackc:
            continue
        for cur in curs:
            put((r, t, c, ts, "PRD", cur), [(1, "PRD"), (1, "CON"), (1, "OUT")])
            put((r, t, c, ts, "IMP", cur), [(1, "IMP"), (1, "NTX"), (-1, "PRD")])
            put((r, t, c, ts, "EXP", cur), [(1, "EXP"), (-1, "NTX"), (-1, "CON")])
    # --- LOOP(RDCUR(R,CUR),RHS_COMPRD(RTCS_VARC(R,T,C,S))$OBJ_COMBAL(R,T,C,S,'PRD',CUR)=YES);
    #     RCS_COMPRD(RHS_COMPRD(R,T,C,S),'FX')$TRACKC(R,C) = YES;
    rdcur = set(q("select r, cur from RDCUR"))
    _add(db, "RHS_COMPRD", [(r, t, c, s) for (r, t, c, s, u, cur) in out if u == "PRD" and (r, cur) in rdcur])
    _add(db, "RCS_COMPRD", [(r, t, c, s, "FX") for (r, t, c, s) in q("select r, y, c, s from RHS_COMPRD") if (r, c) in trackc])
    # --- OBJ_COMBAL(RTCS_VARC(RTC(RC_GRID),TS),'GEN',CUR) = SUM(TS_ANN(TS,S),COM_CSTBAL(RTC,S,'PRD',CUR)+COM_CSTBAL(RTC,S,'CON',CUR));
    #     ... 'NTX' = NTX+CON;  OBJ_COMBAL(..,IE,CUR) = SUM(TS_ANN(TS,S),COM_CSTBAL(RTC,S,IE,CUR));
    for (r, t, c, ts) in varc:
        if (r, t, c) not in rc_grid:
            continue
        for cur in curs:
            put((r, t, c, ts, "GEN", cur), [(1, "PRD"), (1, "CON")])
            put((r, t, c, ts, "NTX", cur), [(1, "NTX"), (1, "CON")])
            put((r, t, c, ts, "IMP", cur), [(1, "IMP")])
            put((r, t, c, ts, "EXP", cur), [(1, "EXP")])
    # --- UNCD7(R,T--ORD(T),C,S--ORD(S),CUR,'','')$RC_GRID(R,T,C) $= COM_CSTBAL(R,T,C,S,'NPG',CUR);
    #     LOOP(UNCD7(R,TT,C,SL,CUR,'',''), GR_ALLMAP(R,'FIN',C) = YES; GR_ALGMAP(R,CG('FIN'),CG) = YES;
    #       OBJ_COMBAL(RC_GRID(R,T,C),TS,'NPG',CUR) $= SUM(TS_ANN(TS,S),COM_CSTBAL(R,T,C,S,'NPG',CUR)));
    npg = sorted({(r, c, cur) for (r, t, c, s, u, cur) in cst if u == "NPG" and (r, t, c) in rc_grid})
    if npg:
        _add(db, "GR_ALLMAP", [(r, "FIN", c) for (r, c, cur) in npg])
        _add(db, "GR_ALGMAP", [(r, "FIN", "FIN") for (r, c, cur) in npg])
        alts = [ts for (ts,) in q("select s from ALL_TS")]
        for (r, c, cur) in npg:
            for (r2, t, c2) in rc_grid:
                if (r2, c2) != (r, c):
                    continue
                for ts in alts:
                    vals = [cst[(r, t, c, s, "NPG", cur)] for s in tsann.get(ts, ()) if (r, t, c, s, "NPG", cur) in cst]
                    if vals:
                        out[(r, t, c, ts, "NPG", cur)] = sum(vals)
    db.clear("OBJ_COMBAL")
    db.load_rows("OBJ_COMBAL", [k + (v,) for k, v in sorted(out.items())])


# ------------------------------------------------------------------------------------------------ helpers
def _ordmap(db):
    return {lab: o for lab, o in db.q("select label, ord from __uel")}


def _sorted(db, rows):
    """GAMS loop order: tuples sorted by the entry order of their labels."""
    o = _ordmap(db)
    return sorted(rows, key=lambda t: tuple(o.get(x, 10 ** 9) for x in t))


def _rows(db, name, where="true"):
    return db.q(f'select * from "{name}" where {where}')


def _set(db, name, rows):
    db.clear(name)
    if rows:
        db.load_rows(name, sorted(set(rows)))


def _add(db, name, rows):
    """S(..) = YES for the tuples `rows`."""
    rows = sorted(set(rows))
    if rows:
        db.x("create or replace temp table t_add as select * from \"%s\" limit 0" % name)
        db.insert_rows("t_add", rows)                  # rows are distinct, so one insert equals one per row
        db.x(f'insert into "{name}" select * from t_add v where not exists(select 1 from "{name}" o where ' +
             " and ".join(f"o.{c} = v.{c}" for c in db.cols(name)) + ")")


def _tmp_rows(db, name, cols, rows):
    """A temp table of VARCHAR columns holding `rows`."""
    db.x(f'create or replace temp table {name} ({", ".join(f"{c} VARCHAR" for c in cols)})')
    if rows:
        db.insert_rows(name, sorted(set(rows)))


def _par(db, name, d):
    """Replace a parameter by the dict {key: value}; None values are dropped, 0.0 is EPS."""
    db.clear(name)
    rows = [k + (v,) for k, v in d.items() if v is not None]
    if rows:
        db.load_rows(name, sorted(rows))


# ------------------------------------------------------------------------------------------------ PREP
def prep(db: DB, interp):
    """powerflo.vda PREP (from prep_ext.vda)."""
    if not db.ctl.get("POWERFLO"):
        return
    F = interp.fillparm
    F(db, "PRC_REACT", "T", None)         # fillparm PRC_REACT R P ",'0','0','0','0','0'" T 1 'GE 0'
    F(db, "GR_DEMFR", "T", None)          # fillparm GR_DEMFR R 'C,S' ",'0','0','0','0'" T 1 'GE 0'
    F(db, "GR_PTDF", "T", None)           # fillparm GR_PTDF R 'P,C,REG,COM' ",'0','0'" T 1 'GE 0'
    F(db, "GR_ENDFR", "T", None)          # fillparm GR_ENDFR R 'C,COM' ",'0','0','0','0'" T 1 'GE 0'
    F(db, "GR_GENFR", "T", None)          # fillparm GR_GENFR R 'C,ITEM' ",'0','0','0','0'" T 1 'GE 0'
    interp.filparam(db, "GR_XBND", "T")   # filparam GR_XBND 'R,' '' ",'0','0','0','0','0'" DATAYEAR T
    if not gas(db):                       # $IFE CARD(GG_KGF)=0 $EXIT
        return
    for n in ("GG_GAMMA", "GG_KGF", "GG_KLP"):
        F(db, n, "T", ("RTP", ("r", "p")))  # fillparm GG_x R 'P,C' ",'0','0','0','0'" T 'RTP(R,T,P)' 'GE 0'
    # --- fillparm GG_PP R 'P,C,BD,J' ",'0','0'" T 'RTP(R,T,P)' 'GE 0':  over BD (LO, UP, FX) only, so that the
    #     numbers of pressure points (bound type N) are neither interpolated nor reset
    db.x("create or replace temp table t_ggpp_n as select * from GG_PP where l not in ('LO','UP','FX')")
    db.zap("GG_PP", "l not in ('LO','UP','FX')")
    F(db, "GG_PP", "T", ("RTP", ("r", "p")))
    db.x("insert into GG_PP select * from t_ggpp_n")
    F(db, "GG_PRBD", "T", None)           # fillparm GG_PRBD R 'C,L' ",'0','0','0','0'" T 1 'GE 0'


def _add_par(db, name, d):
    """Set the parameter entries {key: value} (0.0 is EPS), keeping the others."""
    if not d:
        return
    cols = db.sym[name.upper()].cols
    db.x(f'create or replace temp table t_addpar ({", ".join(f"{c} VARCHAR" for c in cols)}, value DOUBLE)')
    db.insert_rows("t_addpar", [k + (v,) for k, v in d.items()])
    db.put(name, "select * from t_addpar", zero="eps")


# ------------------------------------------------------------------------------------------------ main block
def main(db: DB):
    """powerflo.vda main block (included at the end of pp_prelv.vda), then gasgrids.vda."""
    if not db.ctl.get("POWERFLO"):
        return
    A = _topology(db)
    N = _grids_and_nodes(db, A)
    G = _allocation(db, N)
    U = _units(db, A, N, G)
    arc = _ptdf_lines(db, A, N, G)
    _write_powerflo(db, A, N, G, U, arc)
    if gas(db):
        gasgrids(db, A.T, G.trackp)


@dataclass(frozen=True, slots=True)
class Topology:
    """The lines of the grids (_topology): the milestone years, the electricity commodities, the lines and the default
    direction of each, the transfer factors and reactances of both ends, and the availability of the lines."""
    T: list                 # MILESTONYR
    nrgelc: set             # NRGELC (r, c)
    react: dict             # PRC_REACT (r, t, p), synchronised over the two ends of a line
    ptdf: dict              # GR_PTDF (r, t, p, c, r2, c2), set for both ends of a line within a region
    dfunc: int              # DFUNC: CARD(RP_PRC) of the processes with transfer factors
    top: set                # GR_TOP (r, c, r2, c2, p)
    flow: dict              # GR_FLOW (r, p, c)
    rp_prc: set             # RP_PRC: the far ends (REG, P) of the lines between regions
    vara: dict              # RTP_VARA of the processes of GR_TOP by (r, p): the years, after the deletes of the loop


def _topology(db: DB) -> Topology:
    """The lines of the grids, powerflo.vda lines 37-64: the electricity commodities (NRGELC), the trade processes
    that are lines (with a reactance, with transfer factors, or between nodes given fractions), the topology GR_TOP
    with the default direction of each line (GR_FLOW), the DISTR processes within a region, and the two ends of a
    line made consistent: availability (RTP_VARA), reactance (PRC_REACT) and transfer factors (GR_PTDF)."""
    q, s = db.q, db.s
    T = [y for (y,) in q("select y from MILESTONYR")]
    # --- NRGELC(RC(R,C))$COM_TMAP(R,'NRG',C) $= NRG_TMAP(R,'ELC',C);
    db.add("NRGELC", "select r, c from NRG_TMAP where nrg_type='ELC' and in_RC(r,c) and in_COM_TMAP(r,'NRG',c)")
    nrgelc = set(q("select r, c from NRGELC"))
    # --- TRACKP(R,P) $= SUM(RPC_IRE(R,P,C,IE)$NRGELC(R,C),1); PRC_REACT(R,LL,P)$(NOT TRACKP(R,P)) = 0;
    #     (a reactance only on a trade process of electricity)
    ire_elc = {(r, p) for r, p, c, ie in q("select r, p, c, ie from RPC_IRE") if (r, c) in nrgelc}
    react = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from PRC_REACT") if (r, p) in ire_elc}
    # --- OPTION TRACKC <= GR_DEMFR, GR_GID <= GR_ENDFR; GR_GID(TRACKC)=1; OPTION TRACKC < GG_PRBD; GR_GID(TRACKC)=1;
    #     LOOP((R,LL,C,ITEM)$GR_GENFR(R,LL,C,ITEM),GR_GID(R,C)=1);
    gid0 = set(q("select distinct r, c from GR_ENDFR")) | set(q("select distinct r, c from GR_DEMFR")) \
        | set(q("select distinct r, c from GG_PRBD")) | set(q("select distinct r, c from GR_GENFR"))
    # --- OPTION CLEAR=TRACKC, TRACKP < PRC_REACT, RP_PRC < GR_PTDF; DFUNC=CARD(RP_PRC); TRACKP(RP_PRC)=YES;
    ptdf = {k[:6]: k[6] for k in q("select r, y, p, c, r2, c2, value from GR_PTDF")}
    rp_prc0 = {(k[0], k[2]) for k in ptdf}
    dfunc = len(rp_prc0)
    trackp = {(k[0], k[2]) for k in react} | rp_prc0
    # --- TRACKC(R,C) $= SUM(NRG_GMAP(R,NRG_GRID,C),1);
    trackc = set(q("select distinct r, c from NRG_GMAP"))
    # the trade processes between add-on nodes (the nodes given fractions) are lines too (powerflo.vda line 47)
    # --- LOOP(RPC_IRE(R,P,C,IE)$GR_GID(R,C),TRACKP(R,P)=YES);
    trackp |= {(r, p) for r, p, c, ie in q("select r, p, c, ie from RPC_IRE") if (r, c) in gid0}
    # --- GR_TOP(TOP_IRE(R,C,TRACKC(REG,COM),P))$(TRACKC(R,C)$TRACKP(R,P)) = YES;
    #     GR_TOP(TOP_IRE(TRACKC(REG,COM),R,C,P))$(TRACKC(R,C)$TRACKP(R,P)) = YES;
    top = set()
    for r, c, r2, c2, p in q("select r, c, r2, c2, p from TOP_IRE"):
        if (r, c) in trackc and (r2, c2) in trackc and ((r, p) in trackp or (r2, p) in trackp):
            top.add((r, c, r2, c2, p))
    # --- LOOP(GR_TOP(R,C,REG,COM,P),GR_FLOW(R,P,C)=GR_FLOW(R,P,C)*2+1; GR_FLOW(REG,P,COM)=GR_FLOW(REG,P,COM)*2-1);
    flow = {}
    for r, c, r2, c2, p in _sorted(db, top):
        flow[(r, p, c)] = flow.get((r, p, c), 0) * 2 + 1
        flow[(r2, p, c2)] = flow.get((r2, p, c2), 0) * 2 - 1
    flow = {k: v for k, v in flow.items() if v != 0}
    # --- OPTION CLEAR=TRACKP, CLEAR=RP_PRC, RP_GRID < GR_FLOW;
    #     GR_TOP(R,C,REG,COM,P)$(GR_FLOW(R,P,C) < 0) = NO;  GR_TOP(R,C,R,C,P) = NO;
    top = {t for t in top if flow.get((t[0], t[4], t[1]), 0) >= 0 and not (t[0] == t[2] and t[1] == t[3])}
    # --- LOOP(GR_TOP(R,C,R,COM,P)$SUM(RPC_IRE(RPC_PG(R,P,C),IE),RPC_PG(R,P,COM)),PRC_MAP(R,'DISTR',P)=YES);
    pg = set(q("select r, p, c from RPC_PG"))
    ire = set(q("select r, p, c from RPC_IRE"))
    distr = {(r, "DISTR", p) for r, c, r2, c2, p in top if r == r2 and (r, p, c) in pg and (r, p, c) in ire and (r, p, c2) in pg}
    _add(db, "PRC_MAP", distr)
    # --- LOOP(GR_TOP(R,C,REG,COM,P),F=1;
    #       IF(NOT SAMEAS(R,REG),RP_PRC(REG,P)=YES; F=0;
    #         RTP_VARA(RTP(R,T,P))$(NOT RTP_VARA(REG,T,P)) = NO; PRC_REACT(R,T,P) = MAX(..));
    #       IF(NOT SAMEAS(C,COM)$F,
    #         GR_PTDF(R,T,P,C,ALL_R,COM2)$GR_PTDF(REG,T,P,COM,ALL_R,COM2) =
    #           MAX(ABS(GR_PTDF(R,T,P,C,ALL_R,COM2)),ABS(GR_PTDF(REG,T,P,COM,ALL_R,COM2)))*SIGN(2*SIGN(GR_PTDF(R,T,P,C,ALL_R,COM2)-SIGN(GR_PTDF(REG,T,P,COM,ALL_R,COM2))));
    #         GR_PTDF(REG,T,P,COM,ALL_R,COM2) = -GR_PTDF(R,T,P,C,ALL_R,COM2)));
    #     (the transfer factors of a line within a region, given for one end, are set for both ends with opposite signs)
    sign = lambda x: (x > 0) - (x < 0)
    rp_prc = set()
    # RTP_VARA of the processes of GR_TOP (the only ones the loop and GR_ADMIT look at); the deletes of the loop are
    # made on this copy in loop order, then in one statement
    _tmp_rows(db, "t_grp", ["p"], {(t[4],) for t in top})
    vara, in_rtp = {}, set()
    for r, y, p, b in q("select v.r, v.y, v.p, in_RTP(v.r,v.y,v.p) from RTP_VARA v where exists(select 1 from t_grp g where g.p=v.p)"):
        vara.setdefault((r, p), set()).add(y)
        if b:
            in_rtp.add((r, y, p))
    gone = []
    for r, c, r2, c2, p in _sorted(db, top):
        f = True
        if r != r2:
            rp_prc.add((r2, p))
            f = False
            # RTP_VARA(RTP(R,T,P))$(NOT RTP_VARA(REG,T,P)) = NO;
            ys, ys2 = vara.get((r, p), set()), vara.get((r2, p), set())
            out = {y for y in ys if (r, y, p) in in_rtp and y not in ys2}
            ys -= out
            gone += [(r, y, p) for y in out]
            for t in T:                    # PRC_REACT(R,T,P) = MAX(PRC_REACT(R,T,P),PRC_REACT(REG,T,P))
                v = max(react.get((r, t, p), 0.0), react.get((r2, t, p), 0.0))
                if v:
                    react[(r, t, p)] = v
                else:
                    react.pop((r, t, p), None)
        if c != c2 and f:
            for k, y in [(k, v) for k, v in ptdf.items() if (k[0], k[2], k[3]) == (r2, p, c2) and v != 0]:
                kx = (r, k[1], p, c, k[4], k[5])
                x = ptdf.get(kx, 0.0)
                v = max(abs(x), abs(y)) * sign(2 * sign(x - sign(y)))
                if v:
                    ptdf[kx] = v
                else:
                    ptdf.pop(kx, None)
            for k in [k for k in ptdf if (k[0], k[2], k[3]) == (r2, p, c2)]:
                del ptdf[k]
            for k, x in [(k, v) for k, v in ptdf.items() if (k[0], k[2], k[3]) == (r, p, c)]:
                if x:
                    ptdf[(r2, k[1], p, c2, k[4], k[5])] = -x
    if gone:
        _tmp_rows(db, "t_gone", ["r", "y", "p"], gone)
        db.x("delete from RTP_VARA v where exists(select 1 from t_gone g where g.r=v.r and g.y=v.y and g.p=v.p)")
    return Topology(
        T=T, nrgelc=nrgelc, react=react, ptdf=ptdf, dfunc=dfunc, top=top, flow=flow, rp_prc=rp_prc, vara=vara)


@dataclass(frozen=True, slots=True)
class Nodes:
    """The grids and their nodes (_grids_and_nodes)."""
    react: dict             # PRC_REACT, without the non-positive values and the lines of grids with transfer factors
    arc: set                # GR_ARC (r, c, r2, c2)
    trackc: set             # TRACKC: the grid nodes (r, c), less those that fail the timeslice check
    admit: dict             # GR_ADMIT (r, t, c, r2, c2)
    grgid: dict             # GR_GID: the reactance nodes (r, c), value 1
    rtc: set                # RTC (r, t, c)
    rc_grid: set            # RC_GRID (r, t, c)
    rp_grid: set            # RP_GRID of the grids with transfer factors (r, p)
    sus: dict               # GR_SUS (r, t, c, r2, c2)


def _grids_and_nodes(db: DB, A: Topology) -> Nodes:
    """The grids and their nodes, powerflo.vda lines 65-103: the reactances cleaned (PRC_REACT), the arcs (GR_ARC) and
    their admittance (GR_ADMIT), the disjoint grids numbered by their connected arcs (GR_GID, GR_GRID), the timeslice
    check of the reactance nodes, RC_GRID, RP_GRID of the grids with transfer factors, and the susceptance matrix
    GR_SUS."""
    q = db.q
    T, nrgelc, react, ptdf, top, flow, vara = A.T, A.nrgelc, A.react, A.ptdf, A.top, A.flow, A.vara
    # --- PRC_REACT(R,T,P)$((PRC_REACT(R,T,P) LE 0)$PRC_REACT(R,T,P)) = 0;
    Tset = set(T)
    react = {k: v for k, v in react.items() if not (k[1] in Tset and v <= 0)}
    # --- LOOP(GR_TOP(R,C,REG,COM,P), GR_ARC(R,C,REG,COM) = YES);  OPTION TRACKC < GR_FLOW;
    arc = {t[:4] for t in top}
    trackc = {(r, c) for r, p, c in flow}
    # --- OPTION GR_GID <= GR_PTDF; LOOP(RPC_IRE(R,P,C,IE)$GR_GID(R,C),PRC_REACT(R,T,P) = 0);
    #     (no reactance on a line of a grid with transfer factors; '<=' takes the line end, the first C of GR_PTDF)
    gid_p = {(k[0], k[3]) for k in ptdf}
    no_react = {(r, p) for r, p, c, ie in q("select r, p, c, ie from RPC_IRE") if (r, c) in gid_p}
    react = {k: v for k, v in react.items() if not (k[1] in Tset and (k[0], k[2]) in no_react)}
    # --- GR_ADMIT(R,T,C,REG,COM)$GR_ARC(R,C,REG,COM) = SUM(GR_TOP(R,C,REG,COM,P)$(PRC_REACT(R,T,P)$RTP_VARA(R,T,P)),1/PRC_REACT(R,T,P));
    admit = {}
    for r, c, r2, c2, p in top:
        for t in T:
            v = react.get((r, t, p))
            if v and t in vara.get((r, p), ()):
                admit[(r, t, c, r2, c2)] = admit.get((r, t, c, r2, c2), 0.0) + 1 / v
    # --- OPTION RREG <= GR_ARC;
    _set(db, "RREG", {(a[0], a[2]) for a in arc})
    # --- CNT = EPS; OPTION CLEAR=GR_GID;  LOOP(GR_ARC(R,C,REG,COM), F = GR_GID(R,C); Z = GR_GID(REG,COM);
    #       IF(NOT F+Z, GR_GID(R,C)=CNT; GR_GID(REG,COM)=CNT; CNT=CNT+1;  ELSEIF NOT F, GR_GID(R,C)=Z;
    #       ELSEIF NOT Z, GR_GID(REG,COM)=F;  ELSEIF F NE Z, MY_F=MIN(F,Z); DONE=MAX(F,Z); IF(CNT=DONE+1,CNT=DONE);
    #         GR_GID(TRACKC)$(GR_GID(TRACKC)=DONE) = MY_F));
    #     (an EPS record is present: 'NOT F' is false for F = EPS)
    gid, cnt = {}, 0
    for r, c, r2, c2 in _sorted(db, arc):
        a, b = (r, c), (r2, c2)
        f, z = gid.get(a), gid.get(b)
        if f is None and z is None:
            gid[a] = gid[b] = cnt
            cnt += 1
        elif f is None:
            gid[a] = z
        elif z is None:
            gid[b] = f
        elif f != z:
            my_f, done = min(f, z), max(f, z)
            if cnt == done + 1:
                cnt = done
            for k in trackc:
                if k in gid and gid[k] == done:
                    gid[k] = my_f
    # --- LOOP(SAMEAS('1',J),GR_GRID(J+GR_GID(R,C),TRACKC(R,C)) = YES);
    _set(db, "GR_GRID", {(str(1 + int(round(gid.get(k, 0)))), k[0], k[1]) for k in trackc})
    # --- OPTION GR_GID <= GR_PTDF; GR_GID(TRACKC) = NOT GR_GID(TRACKC);
    #     (the projection '<=' matches the first C of GR_PTDF, the line end: the nodes of the lines with transfer
    #      factors drop out, and GR_GID keeps the other nodes)
    ptdf_nodes = {(k[0], k[3]) for k in ptdf}
    grgid = {k: 1.0 for k in trackc if k not in ptdf_nodes}
    # --- TRACKPC(RP_GRID(R,P),C)$GR_FLOW(R,P,C) $= GR_GID(R,C);
    trackpc = {(r, p, c) for (r, p, c) in flow if (r, c) in grgid}
    # --- LOOP((R,TSL('DAYNITE')), Z=0;
    #       IF(SUM(TRACKPC(R,P,C)$(NOT PRC_TSL(R,P,TSL)$COM_TSL(R,C,TSL)),1),Z=1);
    #       LOOP(RREG(R,REG), IF(SUM(S$(TS_GROUP(R,TSL,S) XOR TS_GROUP(REG,TSL,S)),1), TRACKC(NRGELC(REG,C))$GR_GID(REG,C)=NO; Z = 1));
    #       IF(Z,TRACKC(NRGELC(R,C))$GR_GID(R,C)=NO));
    prctsl = set(q("select r, p from PRC_TSL where tsl='DAYNITE'"))
    comtsl = set(q("select r, c from COM_TSL where tsl='DAYNITE'"))
    tsg = {}
    for r, sl in q("select r, s from TS_GROUP where tsl='DAYNITE'"):
        tsg.setdefault(r, set()).add(sl)
    rreg = {(a[0], a[2]) for a in arc}
    for (r,) in q("select r from REG"):
        z = any(rr == r and (r, p) not in prctsl and (r, c) in comtsl for rr, p, c in trackpc)
        for a, b in rreg:
            if a == r and tsg.get(r, set()) ^ tsg.get(b, set()):
                trackc -= {k for k in nrgelc if k[0] == b and k in grgid}
                z = True
        if z:
            trackc -= {k for k in nrgelc if k[0] == r and k in grgid}
    # --- RC_GRID(RTC(R,T,C))$TRACKC(R,C) = YES;
    rtc = set(q("select r, y, c from RTC"))
    rc_grid = {k for k in rtc if (k[0], k[2]) in trackc}
    _set(db, "RC_GRID", rc_grid)
    # --- OPTION TRACKPC <= GR_PTDF; TRACKPC(R,P,C)$GR_GID(R,C) = NO; OPTION RP_GRID < TRACKPC, CLEAR=TRACKPC, CLEAR=TRACKP;
    rp_grid = {(k[0], k[2]) for k in ptdf if (k[0], k[3]) not in grgid}
    trackp = set()
    # --- option gr_sus < gr_admit;  gr_sus(rc_grid,rc) $= gr_admit(rc_grid,rc)*(-1);
    #     gr_sus(rc_grid(r,t,c),r,c) = -sum(trackc(rc),gr_sus(rc_grid,rc));          (the susceptance matrix; not read)
    #     ('<' between two parameters over (ALL_REG,T,C,ALL_REG,C) maps the repeated domains the other way round: GR_SUS
    #      starts as the transpose of GR_ADMIT, (r2,t,c2,r,c), as GAMS leaves it)
    rcs = set(q("select r, c from RC"))
    sus = {}
    for (r, t, c, r2, c2), v in admit.items():
        sus[(r2, t, c2, r, c)] = sus.get((r2, t, c2, r, c), 0.0) + v
    for (r, t, c, r2, c2), v in admit.items():
        if (r, t, c) in rc_grid and (r2, c2) in rcs:
            sus[(r, t, c, r2, c2)] = -v
    trackc_gams = _sorted(db, trackc)                # SUM over TRACKC in entry order: a set of labels has no fixed
    for (r, t, c) in _sorted(db, rc_grid):           # order in Python (the hash seed), and the last digit followed it
        v = -sum(sus.get((r, t, c, r2, c2), 0.0) for (r2, c2) in trackc_gams)
        if v:
            sus[(r, t, c, r, c)] = v
        else:
            sus.pop((r, t, c, r, c), None)
    return Nodes(
        react=react, arc=arc, trackc=trackc, admit=admit, grgid=grgid, rtc=rtc, rc_grid=rc_grid, rp_grid=rp_grid,
        sus=sus)


@dataclass(frozen=True, slots=True)
class Allocation:
    """The allocation of supply and demand to the nodes (_allocation).  The unit stage normalises endfr, genfr and
    demfr in place, and adds to endc in place."""
    gmapc: set              # GR_GMAPC (r, nrg_grid, c)
    endfr: dict             # GR_ENDFR (r, t, com, c), without the grid nodes
    genfr: dict             # GR_GENFR (r, y, c, item), with the '0' records
    trackp: set             # TRACKP (r, p) of GR_GENFR(R,'0',C,P), for gasgrids.vda
    genmap: dict            # GR_GENMAP (r, p, item)
    genp: set               # GR_GENP (r, p)
    demmap: set             # GR_DEMMAP (r, cg, c)
    endc: set               # GR_ENDC (r, nrg_grid, cg)
    genlev: dict            # GR_GENLEV (r, c), rounded
    glev: object            # GR_GENLEV(r, c), 0 when absent
    prcmap: set             # GR_PRCMAP (r, p, c, item)
    allmap: set             # GR_ALLMAP (r, cg, c)
    algmap: set             # GR_ALGMAP (r, cg, cg)
    comtype: list           # COM_TYPE
    demfr: dict             # GR_DEMFR (r, t, c, s)


def _allocation(db: DB, N: Nodes) -> Allocation:
    """The allocation of supply and demand to the nodes, powerflo.vda lines 106-132: GR_DEMFR levelled, GR_GMAPC,
    GR_ENDFR and GR_GENFR prepared, GR_GENMAP, GR_GENP, GR_DEMMAP and GR_ENDC, GR_GENLEV rounded, the process and
    commodity maps (GR_PRCMAP, GR_CMAP, GR_ALLMAP), the grid allocations (GR_ALGMAP, GR_DEMMAP), and GR_DEMFR on every
    timeslice of the balance of a grid node."""
    q = db.q
    trackc, rc_grid = N.trackc, N.rc_grid
    # --- $BATINCLUDE pp_lvlfc.mod GR_DEMFR C COM_TS '' ",'0','0','0','0'" ALL_TS T RTC(R,T,C)
    if db.card("GR_DEMFR"):
        from ..lvl import lvlfc
        lvlfc(db, "GR_DEMFR", ["c"], "COM_TS", "MILESTONYR", "in_RTC(a.r,a.y,a.c)")
    # --- GR_GMAPC(NRG_GMAP(R,NRG_GRID,C)) $= TRACKC(R,C);
    gmapc = {(r, g, c) for r, g, c in q("select r, nrg_grid, c from NRG_GMAP") if (r, c) in trackc}
    # --- GR_ENDFR(R,T,COM,C)$TRACKC(R,C) = 0;
    endfr = {k[:4]: v for k in q("select r, y, c, cg, value from GR_ENDFR") for v in [k[4]] if (k[0], k[3]) not in trackc}
    # --- GR_GENFR(R,LL--ORD(LL),C,ITEM)$GR_GENFR(R,LL,C,ITEM)=1;
    genfr = {k[:4]: k[4] for k in q("select r, y, c, u, value from GR_GENFR")}
    for r, y, c, u in list(genfr):
        genfr[(r, "0", c, u)] = 1.0
    # --- LOOP((RC(R,C),RP(R,P))$GR_GENFR(R,'0',C,P),TRACKP(RP)=YES);
    rc = set(q("select r, c from RC"))
    rp = set(q("select r, p from RP"))
    trackp = {(r, u) for (r, y, c, u) in genfr if y == "0" and (r, c) in rc and (r, u) in rp}
    # --- GR_GENMAP(TRACKP(R,P),P)$(NOT SUM(PRC$GR_GENMAP(R,PRC,P),1))=YES;
    genmap = {k[:3]: k[3] for k in q("select r, p, u, value from GR_GENMAP")}
    mapped = {(r, u) for r, p, u in genmap}
    for r, p in trackp:
        if (r, p) not in mapped:
            genmap[(r, p, p)] = 1.0
    # --- OPTION GR_GENP < GR_GENMAP, GR_DEMMAP < GR_ENDFR;
    genp = {(r, p) for r, p, u in genmap}
    demmap = {(r, cg, c) for (r, y, c, cg) in endfr}
    # --- LOOP((GR_DEMMAP(R,COM,C),GR_GMAPC(R,NRG_GRID,C)),GR_ENDC(R,NRG_GRID,COM)=YES);
    endc = {(r, g, cg) for (r, cg, c) in demmap for (r2, g, c2) in gmapc if r2 == r and c2 == c}
    # --- GR_GENLEV(TRACKC) = 0; GR_GENLEV(R,C)$GR_GENLEV(R,C) = ROUND(GR_GENLEV(R,C));
    genlev = {}
    for r, c, v in q("select r, c, value from GR_GENLEV"):
        v = math.copysign(math.floor(abs(v) + 0.5), v)           # GAMS ROUND: half away from zero
        if (r, c) not in trackc and v != 0:
            genlev[(r, c)] = v
    glev = lambda r, c: genlev.get((r, c), 0.0)
    # --- TRACKPC(RPC(GR_GENP(R,P),C))$GR_GENLEV(R,C)=YES;
    # --- GR_PRCMAP(TRACKPC(R,P,C),ITEM)$(TOP(R,P,C,'OUT')$GR_GENMAP(R,P,ITEM))=YES;
    #     GR_PRCMAP(TRACKPC(RP_IRE(R,P),C),ITEM)$GR_GENMAP(R,P,ITEM)=YES;
    #     (TRACKPC read from RPC with GR_GENP and GR_GENLEV joined, and with its two tests)
    _tmp_rows(db, "t_gp", ["r", "p"], genp)
    _tmp_rows(db, "t_gl", ["r", "c"], genlev)
    items_of = {}                                   # GR_GENMAP(R,P,ITEM) by (R,P)
    for (r, p, u) in genmap:
        items_of.setdefault((r, p), []).append(u)
    prcmap = {(r, p, c, u) for (r, p, c) in q("""select k.r, k.p, k.c from RPC k join t_gp a on a.r=k.r and a.p=k.p
                                                   join t_gl b on b.r=k.r and b.c=k.c
                                                   where in_TOP(k.r,k.p,k.c,'OUT') or in_RP_IRE(k.r,k.p)""")
              for u in items_of.get((r, p), ())}
    # --- OPTION GR_CMAP < GR_PRCMAP, CLEAR=GR_DEMMAP, CLEAR=RXX;
    cmap = {(r, c, u) for r, p, c, u in prcmap}
    demmap = set()
    # --- LOOP((GR_GMAPC(R,NRG_GRID,C),GR_CMAP(R,COM,ITEM))$GR_GENFR(R,'0',C,ITEM),RXX(R,NRG_GRID,COM)=YES);
    rxx = {(r, g, com) for (r, g, c) in gmapc for (r2, com, u) in cmap if r2 == r and (r, "0", c, u) in genfr}
    # --- LOOP(RXX(R,NRG_GRID,COM),GR_ALLMAP(R,C,COM)$GR_GMAPC(R,NRG_GRID,C)=YES);
    allmap = {(r, c, com) for (r, g, com) in rxx for (r2, g2, c) in gmapc if r2 == r and g2 == g}
    # --- GR_ALLMAP(TRACKC(R,COM),C)$(PROD(COM1$GR_ALLMAP(R,COM1,C),0)$GR_GENLEV(R,C)) $= SUM(GR_ALLMAP(R,COM,COM2),1);
    new = set()
    for (r, com) in trackc:
        if any(a[0] == r and a[1] == com for a in allmap):
            for (r2, c) in genlev:
                if r2 == r and not any(a[0] == r and a[2] == c for a in allmap):
                    new.add((r, com, c))
    allmap |= new
    # --- LOOP(NRG_GRID,GR_ALLMAP(R,C,COM)$((NOT GR_GMAPC(R,NRG_GRID,C))$NRG_GMAP(R,NRG_GRID,COM)) = NO);
    nrg_gmap = set(q("select r, nrg_grid, c from NRG_GMAP"))
    grids = [g for (g,) in q("select * from NRG_GRID")]
    allmap = {(r, c, com) for (r, c, com) in allmap if not any((r, g, com) in nrg_gmap and (r, g, c) not in gmapc for g in grids)}
    # --- GR_ALGMAP(R,'NRG',C)$((GR_GENLEV(R,C)=1)$GR_GENLEV(R,C))=YES;  GR_ALGMAP(R,C,C)$((GR_GENLEV(R,C)=2)$..)=YES;
    algmap = {(r, "NRG", c) for (r, c), v in genlev.items() if v == 1} | {(r, c, c) for (r, c), v in genlev.items() if v == 2}
    # --- GR_ALGMAP(R,COM_TYPE(CG),CG)$(SUM(TRACKC(R,C),1)>1) $= SUM(GR_ALGMAP(R,CG,C),1);
    comtype = [cg for (cg,) in q("select cg from COM_TYPE")]
    nreg = {}
    for r, c in trackc:
        nreg[r] = nreg.get(r, 0) + 1
    algmap |= {(r, cg, cg) for (r, cg, c) in list(algmap) if cg in comtype and nreg.get(r, 0) > 1}
    # --- GR_DEMMAP(GR_ALLMAP(R,C,COM))$(GR_GENLEV(R,COM) < 3) = YES;
    demmap = {(r, c, com) for (r, c, com) in allmap if glev(r, com) < 3}
    # --- IF(CARD(GR_DEMFR),GR_DEMFR(RTCS_VARC(RC_GRID(R,T,C),S)) = GR_DEMFR(R,T,C,S)+EPS);
    #     (every timeslice of the balance of a grid node gets a record: EPS where no fraction is given)
    demfr = {(r, t, c, s): v for r, t, c, s, v in q("select r, y, c, s, value from GR_DEMFR")}
    if demfr:
        for r, t, c, s in q("select r, y, c, s from RTCS_VARC"):
            if (r, t, c) in rc_grid:
                demfr.setdefault((r, t, c, s), 0.0)
    # --- GR_ENDC(R,NRG_GRID,'DEM')$SUM(GR_ENDC(R,NRG_GRID,C),1) = YES;
    endc |= {(r, g, "DEM") for (r, g, c) in endc}
    return Allocation(
        gmapc=gmapc, endfr=endfr, genfr=genfr, trackp=trackp, genmap=genmap, genp=genp, demmap=demmap, endc=endc,
        genlev=genlev, glev=glev, prcmap=prcmap, allmap=allmap, algmap=algmap, comtype=comtype, demfr=demfr)


@dataclass(frozen=True, slots=True)
class Units:
    """The units of the allocations (_units)."""
    endc: set               # GR_ENDC, completed (the allocation's set, added to in place)
    genmap: dict            # GR_GENMAP, normalised
    gr_units: dict          # GR_UNITS (r, t, c) as the last pass of the loop over GR_ENDC leaves it
    ado: set                # GR_ADO (r, t, c)
    gnall: set              # GR_GNALL (r, t, c)


def _units(db: DB, A: Topology, N: Nodes, G: Allocation) -> Units:
    """The units of the allocations, powerflo.vda lines 133-162: the demand fractions of the regions with sectoral
    demand (GR_DEMFR from GR_ENDFR, normalised with GR_UNITS), GR_ENDC completed, GR_GENMAP and GR_GENFR normalised,
    GR_DEMFR normalised by grid, and in each grid the node of largest demand fraction (GR_ADO, GR_GNALL)."""
    q = db.q
    T = A.T
    trackc, rtc, rc_grid = N.trackc, N.rtc, N.rc_grid
    gmapc, endfr, genfr, genmap, endc, glev, allmap = G.gmapc, G.endfr, G.genfr, G.genmap, G.endc, G.glev, G.allmap
    comtype, demfr = G.comtype, G.demfr
    # --- LOOP((R,NRG_GRID)$GR_ENDC(R,NRG_GRID,'DEM'),
    #       GR_DEMFR(RTCS_VARC(RC_GRID(R,T,COM),S)) = SUM(GR_ENDC(R,NRG_GRID,C),MIN(0.33,GR_ENDFR(R,T,COM,C)));
    #       GR_UNITS(RTC(R,T,C))$GR_ENDC(R,NRG_GRID,C) = SUM(RC_GRID(R,T,COM),GR_ENDFR(R,T,COM,C))+1-1;
    #       GR_ENDFR(RC_GRID(R,T,COM),C)$(GR_ENDC(R,NRG_GRID,C)$GR_UNITS(R,T,C)) = GR_ENDFR(R,T,COM,C)/GR_UNITS(R,T,C);
    #       OPTION CLEAR=GR_UNITS);
    dem = _sorted(db, {(r, g) for (r, g, cg) in endc if cg == "DEM"})
    # RC_GRID and RTC by region, and RC_GRID by (region, period), each in the order of the set (the order of the sums)
    rcg_r, rcg_rt, rtc_r = {}, {}, {}
    for (r, t, com) in rc_grid:
        rcg_r.setdefault(r, []).append((t, com))
        rcg_rt.setdefault((r, t), []).append(com)
    for (r, t, c) in rtc:
        rtc_r.setdefault(r, []).append((t, c))
    # RTCS_VARC: only the RC_GRID entries are read (in table order)
    rtcs_varc = {}
    if dem:
        for r, y, c, sl in q("select r, y, c, s from RTCS_VARC where in_RC_GRID(r,y,c) order by rowid"):
            rtcs_varc.setdefault((r, y, c), []).append(sl)
    for r, g in dem:
        cs = [cg for (r2, g2, cg) in endc if r2 == r and g2 == g]
        for (t, com) in rcg_r.get(r, ()):
            v = sum(min(0.33, endfr.get((r, t, com, c), 0.0)) for c in cs)
            for sl in rtcs_varc.get((r, t, com), ()):
                if v != 0:
                    demfr[(r, t, com, sl)] = v
                else:
                    demfr.pop((r, t, com, sl), None)
        units = {}
        for (t, c) in rtc_r.get(r, ()):
            if c in cs:
                units[(r, t, c)] = sum(endfr.get((r, t, com, c), 0.0) for com in rcg_rt.get((r, t), ())) + 1 - 1
        for (t, com) in rcg_r.get(r, ()):
            for c in cs:
                u = units.get((r, t, c), 0.0)
                if u and (r, t, com, c) in endfr:
                    endfr[(r, t, com, c)] = endfr[(r, t, com, c)] / u
    # --- LOOP(GR_ALLMAP(R,COM,C),GR_ENDC(R,NRG_GRID,C)$((GR_GENLEV(R,C)>2)$GR_GMAPC(R,NRG_GRID,COM)$GR_GENLEV(R,C)) = YES);
    for (r, com, c) in allmap:
        if glev(r, c) > 2:
            endc |= {(r, g, c) for (r2, g, c2) in gmapc if r2 == r and c2 == com}
    # --- GR_ENDC(R,NRG_GRID,'NRG')$(NOT GR_ENDC(R,NRG_GRID,'DEM')) = SUM(GR_GMAPC(R,NRG_GRID,C),1);
    endc |= {(r, g, "NRG") for (r, g, c) in gmapc if (r, g, "DEM") not in endc}
    # --- PRC_YMAX(GR_GENP(R,P)) = SUM(ITEM$GR_GENMAP(R,P,ITEM),GR_GENMAP(R,P,ITEM))+1-1;
    #     GR_GENMAP(GR_GENP(R,P),ITEM)$(PRC_YMAX(R,P)$GR_GENMAP(R,P,ITEM)) = GR_GENMAP(R,P,ITEM)/PRC_YMAX(R,P);
    ymax = {}
    for (r, p, u), v in genmap.items():
        ymax[(r, p)] = ymax.get((r, p), 0.0) + v
    ymax = {k: v + 1 - 1 for k, v in ymax.items()}
    genmap = {(r, p, u): (v / ymax[(r, p)] if ymax.get((r, p)) else v) for (r, p, u), v in genmap.items()}
    # --- LOOP(RC_GRID(R,T,C),GR_UNITS(R,T,ITEM)$GR_GENFR(R,T,C,ITEM)=1);
    #     GR_UNITS(R,T,ITEM)$GR_UNITS(R,T,ITEM) = SUM(TRACKC(R,C),GR_GENFR(R,T,C,ITEM))+1-1;
    #     GR_GENFR(RC_GRID(R,T,C),ITEM)$GR_UNITS(R,T,ITEM) = GR_GENFR(R,T,C,ITEM)/GR_UNITS(R,T,ITEM);
    units = {(r, t, u) for (r, t, c, u) in genfr if (r, t, c) in rc_grid}
    by_rtu = {}                                     # the GR_GENFR values summed, by (R,T,ITEM), in the order of GR_GENFR
    for (r, t, c, u), v in genfr.items():
        if (r, c) in trackc:
            by_rtu.setdefault((r, t, u), []).append(v)
    units = {k: sum(by_rtu.get(k, ())) + 1 - 1 for k in units}
    for (r, t, c, u) in list(genfr):
        if (r, t, c) in rc_grid and units.get((r, t, u)):
            genfr[(r, t, c, u)] = genfr[(r, t, c, u)] / units[(r, t, u)]
    # --- DEMFR normalization: LOOP(NRG_GRID, ...
    #       GR_DEMFR(RC_GRID(R,T,C),S)$(GR_GMAPC(R,NRG_GRID,C)$GR_UNITS(R,T,S)) = GR_DEMFR(R,T,C,S)/GR_UNITS(R,T,S)+EPS;
    for (g,) in _sorted(db, q("select * from NRG_GRID")):
        nodes = {(r, c) for (r, g2, c) in gmapc if g2 == g}
        units = {(r, t, sl) for (r, t, c, sl) in demfr if (r, t, c) in rc_grid and (r, c) in nodes}
        by_rts = {}                                 # the GR_DEMFR values summed, by (R,T,S), in the order of GR_DEMFR
        for (r, t, c, sl), v in demfr.items():
            if (r, c) in nodes:
                by_rts.setdefault((r, t, sl), []).append(v)
        units = {k: sum(by_rts.get(k, ())) + 1 - 1 for k in units}
        units = {k: v for k, v in units.items() if v != 0}
        units_rt = {}                               # the same, by (R,T), in the order of `units`
        for (r2, t2, sl), u in units.items():
            units_rt.setdefault((r2, t2), []).append((sl, u))
        for (r, t, c) in rc_grid:
            if (r, c) not in nodes:
                continue
            for sl, u in units_rt.get((r, t), ()):
                demfr[(r, t, c, sl)] = demfr.get((r, t, c, sl), 0.0) / u + EPS
    # --- LOOP(GR_ENDC(R,NRG_GRID,COM_TYPE(CG)),
    #       GR_UNITS(RC_GRID(R,T,C))$GR_GMAPC(R,NRG_GRID,C) = SUM(COM_TS(R,C,S),GR_DEMFR(R,T,C,S));
    #       LOOP(T, Z=MAX(EPS,SMAX(GR_GMAPC(R,NRG_GRID,C),GR_UNITS(R,T,C)));
    #         LOOP(GR_GMAPC(R,NRG_GRID,C)$Z,IF(GR_UNITS(R,T,C)=Z,GR_ADO(R,T,C)=YES;Z=0)));
    #       IF(SAMEAS(CG,'DEM'),GR_DEMFR(GR_ADO(R,T,C),S)$GR_GMAPC(R,NRG_GRID,C)=0);
    #       GR_GNALL(RC_GRID(R,T,C))$SUM(GR_ALLMAP(R,C,COM),GR_GMAPC(R,NRG_GRID,C)) = YES);
    #     (a sum of EPS values is EPS: the record stays; Z = EPS is true in a $-condition)
    comts = set(q("select r, c, s from COM_TS"))
    uo = _ordmap(db)
    gr_units, ado, gnall = {}, set(), set()
    for (r, g, cg) in _sorted(db, {e for e in endc if e[2] in comtype}):
        nodes = sorted({c for (r2, g2, c) in gmapc if r2 == r and g2 == g}, key=lambda c: uo.get(c, 0))
        for (r2, t, c) in rc_grid:
            if r2 == r and c in nodes:
                vals = [v for (r3, t3, c3, sl), v in demfr.items() if (r3, t3, c3) == (r, t, c) and (r, c, sl) in comts]
                if vals:
                    gr_units[(r, t, c)] = sum(vals)
                else:
                    gr_units.pop((r, t, c), None)
        for t in T:
            z = max(0.0, max([gr_units.get((r, t, c), 0.0) for c in nodes], default=0.0))
            live = True                                 # Z = MAX(EPS, ..) is never 'false' before the first hit
            for c in nodes:
                if live and gr_units.get((r, t, c), 0.0) == z:
                    ado.add((r, t, c))
                    live = False
        if cg == "DEM":
            for k in [k for k in demfr if (k[0], k[1], k[2]) in ado and (k[0], g, k[2]) in gmapc]:
                del demfr[k]
        gnall |= {(r2, t, c) for (r2, t, c) in rc_grid if r2 == r and (r, g, c) in gmapc
                  and any(a[0] == r and a[1] == c for a in allmap)}
    # --- GR_ADO(RTC(RC_GRID)) = NOT GR_ADO(RTC);
    ado = (ado - rc_grid) | {k for k in rc_grid if k not in ado}
    return Units(
        endc=endc, genmap=genmap, gr_units=gr_units, ado=ado, gnall=gnall)


def _ptdf_lines(db: DB, A: Topology, N: Nodes, G: Allocation):
    """The transfer factors completed, powerflo.vda lines 171-186, where the file turns from the allocations to the
    lines of the grids with transfer factors (* Complete PTDF processing): with transfer factors (DFUNC) GR_PTDF
    without the far ends, the factors below %PDTOL% and the rounding to 2^-32, the candidate lines
    GR_CANDID and no new capacity for existing lines (NCAP_BND); else RP_GRID cleared. Then the nodal commodity
    balances of the reactance nodes made equalities (COM_LIM 'FX'). Returns GR_ARC, made again from GR_TOP when
    there are transfer factors."""
    q = db.q
    T, ptdf, dfunc, top, rp_prc = A.T, A.ptdf, A.dfunc, A.top, A.rp_prc
    arc, trackc, grgid, rp_grid = N.arc, N.trackc, N.grgid, N.rp_grid
    algmap = G.algmap
    # --- IF(DFUNC, OPTION GR_ARC <= GR_TOP, CLEAR=GR_CANDID;
    #       GR_PTDF(R,T,P,C,ALL_R,COM)$RP_PRC(R,P)=0;
    #       GR_PTDF(R,T,P,C,ALL_R,COM)$((ABS(GR_PTDF(R,T,P,C,ALL_R,COM))<%PDTOL%)$GR_PTDF(R,T,P,C,ALL_R,COM)) = 0;
    #       GR_PTDF(R,T,P,C,ALL_R,COM)$((NOT GR_ALGMAP(R,'NRG','NRG'))$GR_PTDF(..)) = ROUND(GR_PTDF(..)/POWER(2,-32))*POWER(2,-32);
    #       OPTION TRACKP < GR_PTDF, PRC_YMAX < NCAP_PASTI, TRACKC < GR_PTDF;
    #       GR_CANDID(R,T,P)$(RP_GRID(R,P)$TRACKP(R,P)) = YES;
    #       NCAP_BND(GR_CANDID(R,T,P),'UP')$PRC_YMAX(R,P) = MAX(EPS,NCAP_BND(R,T,P,'UP'));
    #       DFUNC = 0; OPTION CLEAR=PRC_YMAX, CLEAR=TRACKP;
    #     ELSE OPTION CLEAR=RP_GRID);
    candid = set()
    if dfunc:
        arc = {t[:4] for t in top}
        ptdf = {k: v for k, v in ptdf.items() if (k[0], k[2]) not in rp_prc}
        ptdf = {k: v for k, v in ptdf.items() if not (abs(v) < 1e-5)}
        nrgnrg = (lambda r: (r, "NRG", "NRG") in algmap)
        ptdf = {k: (v if nrgnrg(k[0]) else round(v / 2 ** -32) * 2 ** -32) for k, v in ptdf.items()}
        ptdf = {k: v for k, v in ptdf.items() if v != 0}
        tp = {(k[0], k[2]) for k in ptdf}
        pasti = {(r, p) for r, p in q("select distinct r, p from NCAP_PASTI")}
        trackc = {(k[0], k[5]) for k in ptdf}          # '<': the last C of GR_PTDF
        candid = {(r, t, p) for (r, p) in rp_grid if (r, p) in tp for t in T}
        up = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from NCAP_BND where l='UP'")}
        _add_par(db, "NCAP_BND", {(r, t, p, "UP"): max(0.0, up.get((r, t, p), 0.0))      # MAX(EPS, ..): EPS is 0.0
                                  for (r, t, p) in sorted(candid) if (r, p) in pasti})
    else:
        rp_grid = set()
    _set(db, "RP_GRID", rp_grid)
    _set(db, "GR_CANDID", candid)
    _par(db, "GR_PTDF", ptdf)
    # --- COM_LIM(TRACKC(RC),'FX')$((NOT SUM(COM_LIM(RC,L),1))$GR_GID(RC)) = YES;
    lim = {(r, c) for r, c in q("select r, c from COM_LIM")}
    _add(db, "COM_LIM", {(r, c, "FX") for r, c in trackc if (r, c) not in lim and (r, c) in grgid})
    # --- OPTION CLEAR=TRACKC,CLEAR=RP_PRC,CLEAR=TRACKPC;
    return arc


def _write_powerflo(db: DB, A: Topology, N: Nodes, G: Allocation, U: Units, arc):
    """The sets and parameters of powerflo.vda into the database, after its main block."""
    T, top, flow = A.T, A.top, A.flow
    react, admit, grgid, sus = N.react, N.admit, N.grgid, N.sus
    gmapc, endfr, genfr, genp, demmap, genlev = G.gmapc, G.endfr, G.genfr, G.genp, G.demmap, G.genlev
    prcmap, allmap, algmap, demfr = G.prcmap, G.allmap, G.algmap, G.demfr
    endc, genmap, gr_units, ado, gnall = U.endc, U.genmap, U.gr_units, U.ado, U.gnall
    # write the sets and parameters of powerflo.vda
    _set(db, "GR_TOP", top); _set(db, "GR_ARC", arc)
    _par(db, "GR_FLOW", {k: float(v) for k, v in flow.items()})
    _par(db, "GR_GID", grgid)
    _par(db, "GR_ADMIT", admit); _par(db, "GR_SUS", sus); _par(db, "PRC_REACT", react)
    _set(db, "GR_GMAPC", gmapc); _set(db, "GR_GENP", genp); _set(db, "GR_PRCMAP", prcmap)
    _set(db, "GR_ALLMAP", allmap); _set(db, "GR_ALGMAP", algmap); _set(db, "GR_DEMMAP", demmap)
    _set(db, "GR_ENDC", endc); _set(db, "GR_ADO", ado); _set(db, "GR_GNALL", gnall)
    _par(db, "GR_ENDFR", endfr); _par(db, "GR_GENFR", genfr); _par(db, "GR_GENMAP", genmap)
    _par(db, "GR_GENLEV", genlev); _par(db, "GR_DEMFR", demfr); _par(db, "GR_UNITS", gr_units)


# ------------------------------------------------------------------------------------------------ gasgrids.vda
def gasgrids(db: DB, T, trackp):
    q, s = db.q, db.s
    solmip = db.ctl.get("SOLMIP")
    # --- OPTION GG_WTX < GG_PP;
    pp = {k[:6]: k[6] for k in q("select r, y, p, c, l, j, value from GG_PP")}
    wtx = {(r, p, c) for (r, y, p, c, l, j) in pp}
    # --- TRACKC(R,C) $= SUM(NRG_GMAP(R,'GAS',C),GG_DENS(R,C));
    dens = {(r, c): v for r, c, v in q("select r, c, value from GG_DENS")}
    trackc = {(r, c) for r, g, c in q("select r, nrg_grid, c from NRG_GMAP where nrg_grid='GAS'") if (r, c) in dens}
    # --- LOOP(GR_GRID(J,TRACKC), GG_DENS(R,C)$((NOT GG_DENS(R,C))$GR_GRID(J,R,C)) = GG_DENS(TRACKC));
    #     (the loop controls R and C: no change) -- stop if a grid has nodes both with and without a density
    grid = q("select j, r, c from GR_GRID")
    js = {j for j, r, c in grid if (r, c) in trackc}
    nodens = [(r, c) for j, r, c in grid if j in js and (r, c) not in dens]
    if nodens:
        unsupported(db, "gas grid nodes without a density GG_DENS in a grid with densities (gasgrids.vda)", ["GG_DENS"])
    # --- OPTION TRACKC < GG_DENS;
    trackc = set(dens)
    # --- GG_RTC(RC_GRID(R,T,C)) $= TRACKC(R,C);
    rc_grid = set(q("select r, y, c from RC_GRID"))
    rtc = {k for k in rc_grid if (k[0], k[2]) in trackc}
    # --- TRACKP(RP_IRE(R,P))$SUM(TRACKC(R,C)$GR_FLOW(R,P,C),1) = YES;
    flow = {k[:3]: k[3] for k in q("select r, p, c, value from GR_FLOW")}
    rpire = set(q("select r, p from RP_IRE"))
    trackp = set(trackp) | {(r, p) for (r, p, c) in flow if (r, p) in rpire and (r, c) in trackc}
    # --- GG_RTPC(RTP(R,T,P),C)$(GG_RTC(R,T,C)$GR_FLOW(R,P,C)) = YES;
    rtp = set(q("select r, y, p from RTP"))
    rtpc = {(r, t, p, c) for (r, p, c) in flow for t in T if (r, t, p) in rtp and (r, t, c) in rtc}
    # --- GG_ARC(GR_ARC(TRACKC(R,C),RC))=YES;
    rc = set(q("select r, c from RC"))
    ggarc = {a for a in q("select r, c, r2, c2 from GR_ARC") if (a[0], a[1]) in trackc and (a[2], a[3]) in rc}
    # --- GG_TOP(TOP_IRE(TRACKC(R,C),RC,P))$TRACKP(R,P) = YES; OPTION GG_LINK <= GG_TOP, CLEAR=GG_TOP, GG_EDGE <= GG_LINK;
    toptmp = {t for t in q("select r, c, r2, c2, p from TOP_IRE") if (t[0], t[1]) in trackc and (t[2], t[3]) in rc and (t[0], t[4]) in trackp}
    link = {(r, p, c, r2, c2) for (r, c, r2, c2, p) in toptmp}
    edge = {(r, p, r2) for (r, p, c, r2, c2) in link}
    # --- GG_TOP(GR_TOP(TRACKC(R,C),RC,P)) = YES;
    ggtop = {t for t in q("select r, c, r2, c2, p from GR_TOP") if (t[0], t[1]) in trackc and (t[2], t[3]) in rc}
    # --- Sync KGF and KLP: LOOP(GG_TOP(R,C,REG,COM,P), ...)
    kgf = {k[:4]: k[4] for k in q("select r, y, p, c, value from GG_KGF")}
    klp = {k[:4]: k[4] for k in q("select r, y, p, c, value from GG_KLP")}
    for (r, c, r2, c2, p) in _sorted(db, ggtop):
        for t in T:
            # GG_KGF(R,T,P,C)$((NOT GG_KGF(R,T,P,C))$GG_KGF(REG,T,P,COM)) = GG_KGF(REG,T,P,COM);  and the reverse
            # (the source is tested on record: a value given as 0 is EPS, which $ takes as true and copies)
            if (r, t, p, c) not in kgf and (r2, t, p, c2) in kgf:
                kgf[(r, t, p, c)] = kgf[(r2, t, p, c2)]
            if (r2, t, p, c2) not in kgf and (r, t, p, c) in kgf:
                kgf[(r2, t, p, c2)] = kgf[(r, t, p, c)]
            # GG_KLP(R,T,P,C)$((NOT GG_KLP(R,T,P,C))$GG_KLP(REG,T,P,COM)) = GG_KLP(REG,T,P,COM);
            if (r, t, p, c) not in klp and (r2, t, p, c2) in klp:
                klp[(r, t, p, c)] = klp[(r2, t, p, c2)]
            # GG_KLP(R,T,P,COM2(ACTCG))$(NOT GG_KLP(R,T,P,COM2)) = GG_KLP(REG,T,P,COM2);
            if (r, t, p, "ACT") not in klp and (r2, t, p, "ACT") in klp:
                klp[(r, t, p, "ACT")] = klp[(r2, t, p, "ACT")]
            # GG_KLP(REG,T,P,COM) = 0; IF(NOT SAMEAS(R,REG),GG_KLP(REG,T,P,COM2) = 0)
            klp.pop((r2, t, p, c2), None)
            if r != r2:
                for k in [k for k in klp if k[0] == r2 and k[1] == t and k[2] == p]:
                    del klp[k]
    # --- GG_PRBD(GG_RTC(RTC),BD('UP'))$(GG_PRBD(RTC,BD)<GG_PRBD(RTC,'LO')) $= GG_PRBD(RTC,'LO');
    #     GG_PRBD(GG_RTC(RTC),BD('LO'))$(GG_PRBD(RTC,BD)>GG_PRBD(RTC,'UP')) $= GG_PRBD(RTC,'UP');
    prbd = {k[:4]: k[4] for k in q("select r, y, c, l, value from GG_PRBD")}
    pb = lambda r, t, c, l: prbd.get((r, t, c, l), 0.0)
    for (r, t, c) in rtc:
        # ($= copies a source on record, an EPS too)
        if pb(r, t, c, "UP") < pb(r, t, c, "LO") and (r, t, c, "LO") in prbd:
            prbd[(r, t, c, "UP")] = prbd[(r, t, c, "LO")]
        if pb(r, t, c, "LO") > pb(r, t, c, "UP") and (r, t, c, "UP") in prbd:
            prbd[(r, t, c, "LO")] = prbd[(r, t, c, "UP")]
    # --- GG_GAMMA(GG_RTPC(R,T,P,C))$(NOT RPC_IRE(R,P,C,'EXP')) = 1;  GG_GAMMA(GG_RTPC)$(GG_GAMMA<1+1/128) = 1;
    gamma = {k[:4]: k[4] for k in q("select r, y, p, c, value from GG_GAMMA")}
    exp_ = set(q("select r, p, c from RPC_IRE where ie='EXP'"))
    for (r, t, p, c) in rtpc:
        if (r, p, c) not in exp_:
            gamma[(r, t, p, c)] = 1.0
        if gamma.get((r, t, p, c), 0.0) < 1 + 1 / 128:
            gamma[(r, t, p, c)] = 1.0
    gm = lambda r, t, p, c: gamma.get((r, t, p, c), 0.0)
    # --- LOOP(GG_LINK(R,P,C,REG,COM)$GG_LINK(REG,P,COM,R,C),TRACKPC(R,P,C)=YES);
    trackpc = {(r, p, c) for (r, p, c, r2, c2) in link if (r2, p, c2, r, c) in link}
    # --- $IFI NOT %SOLMIP%==YES GG_WTX(TRACKPC) = NO;   $IFI %SOLMIP%==YES GG_M1 = 1;
    if not solmip:
        wtx -= trackpc
    else:
        s["GG_M1"] = 1.0
    m1 = s["GG_M1"]
    # --- GG_WTX(TRACKPC(R,P,C))$SUM(GG_LINK(R,P,C,REG,COM)$GG_WTX(REG,P,COM),1)=YES;
    wtx |= {(r, p, c) for (r, p, c) in trackpc if any(l[:3] == (r, p, c) and (l[3], p, l[4]) in wtx for l in link)}
    # --- Autogenerate pressure points:  LOOP((GG_RTPC(R,T,P,C),GG_LINK(R,P,C,REG,COM)), ...)
    ppm = {}
    for (r, t, p, c) in _sorted(db, rtpc):
        for (r1, p1, c1, r2, c2) in _sorted(db, [l for l in link if l[:3] == (r, p, c)]):
            cnt = round(max(0.0, pp.get((r, "0", p, c, "N", "1"), 0.0), pp.get((r2, "0", p, c2, "N", "1"), 0.0)))
            dfunc = ((r, p, c) in wtx) and cnt != 0
            # IF(DFUNC->CNT, ...)  is always true here (DFUNC implies CNT)
            cnt = min(50, cnt)
            f = pb(r, t, c, "UP") * max(1.0, gm(r, t, p, c))
            z = max(f * .1, pb(r2, t, c2, "LO"))
            if f > z:
                if dfunc:
                    my_f = 1.25 if cnt < 9 else ((1 - z / f) / 0.001) ** (1 / cnt)
                    cnt = math.ceil(math.log((1 - z / f) / 0.001) / math.log(my_f) - .001) + 1
                    for j in range(1, 52):
                        if j <= cnt:
                            pp[(r, t, p, c, "UP", str(j))] = f
                            pp[(r2, t, p, c2, "LO", str(j))] = f * (1 - .001 * my_f ** (j - 1))
                else:
                    n = GG_WN
                    my_f, df = 1.283, .233
                    done = (1 - z / f) * df / (n / 2 * (n - 1))
                    n = n - 1 + m1 / 2
                    zz = (1 - z / f) * (1 - df) / (my_f ** n)
                    for j in range(1, GG_WN + 1):
                        ppm[(r, t, p, c, r2, c2, str(j))] = f * (1 - zz * my_f ** (j - 1) - j / 2 * (j - 1) * done)
    # --- GG_PP(R,LL,P,C,'N',OMG) = 0; OPTION GG_WTX < GG_PP, OMG < GG_PP;
    pp = {k: v for k, v in pp.items() if k[4] != "N"}
    wtx = {(r, p, c) for (r, y, p, c, l, j) in pp}
    omg = {j for (r, y, p, c, l, j) in pp}
    # --- GG_PPM(GG_RTPC(R,T,P,C),R,C,GG_O(J))$(NOT GG_WTX(R,P,C)) = GG_PRBD(R,T,C,'UP')*MAX(1,GG_GAMMA(R,T,P,C));
    for (r, t, p, c) in rtpc:
        if (r, p, c) not in wtx:
            for j in range(1, GG_WN + 1):
                ppm[(r, t, p, c, r, c, str(j))] = pb(r, t, c, "UP") * max(1.0, gm(r, t, p, c))
    ppm = {k: v for k, v in ppm.items() if v != 0}
    # --- GG_PPW(GG_RTPC(R,T,P,C),RC,GG_O(J))$((NOT GG_WTX(R,P,C))$GG_PPM(R,T,P,C,RC,J)) = SQRT(PPM(..,R,C,J)**2-PPM(..,RC,J)**2);
    ppw = {}
    for k, v in ppm.items():
        r, t, p, c = k[:4]
        if (r, t, p, c) in rtpc and (r, p, c) not in wtx:
            w = math.sqrt(ppm.get((r, t, p, c, r, c, k[6]), 0.0) ** 2 - v ** 2)
            if w != 0:
                ppw[k] = w
    # --- GG_GAMMA(GG_RTPC(R,T,P,C))$(GG_GAMMA(R,T,P,C)<1+1/128) = 0;
    for k in rtpc:
        if gamma.get(k, 0.0) < 1 + 1 / 128:
            gamma.pop(k, None)
    # --- GG_RTPC(R,T,P,C)$(NOT GG_KGF(R,T,P,C)) = NO;
    rtpc = {k for k in rtpc if k in kgf}           # (NOT EPS is false: a KGF given as 0 keeps the pipeline)
    # --- GG_KLP(RTPC(R,T,P,C))$(NOT GG_RTPC(RTPC)) = 0;
    rtpc_all = set(q("select r, y, p, c from RTPC"))
    klp = {k: v for k, v in klp.items() if not (k in rtpc_all and k not in rtpc)}
    # --- LOOP(GG_LINK(GG_WTX(R,P,C),REG,COM),GG_PP(R,T,P,C,'UP',OMG)$(GG_PP(R,T,P,C,'UP',OMG)<=GG_PP(REG,T,P,COM,'LO',OMG))=0);
    for (r, p, c, r2, c2) in _sorted(db, link):
        if (r, p, c) in wtx:
            for k in [k for k in pp if k[0] == r and k[2] == p and k[3] == c and k[4] == "UP" and k[5] in omg]:
                if k in pp and pp[k] <= pp.get((r2, k[1], p, c2, "LO", k[5]), 0.0):
                    del pp[k]
    # --- IRE_FLOSUM(GG_RTPC(R,T,P,C),ANNUAL,IE,C,'IN')$(NOT RPC_IRE(R,P,C,IE)) $= RPC_IRE(R,P,C,'IMP');
    imp = set(q("select r, p, c from RPC_IRE where ie='IMP'"))
    ire = set(q("select r, p, c, ie from RPC_IRE"))
    rows = [(r, t, p, c, "ANNUAL", ie, c, "IN", 1.0) for (r, t, p, c) in rtpc for ie in ("IMP", "EXP")
            if (r, p, c, ie) not in ire and (r, p, c) in imp]
    if rows:
        db.x("create or replace temp table t_fs (r VARCHAR, y VARCHAR, p VARCHAR, c VARCHAR, s VARCHAR, ie VARCHAR, c2 VARCHAR, io VARCHAR, value DOUBLE)")
        db.insert_rows("t_fs", rows)
        db.put("IRE_FLOSUM", "select * from t_fs")
    # --- GG_WINK(GG_LINK(R,P,C,RC))$(NOT GG_WTX(R,P,C)) = YES;
    wink = {l for l in link if l[:3] not in wtx}
    # --- GG_MM(GG_RTPC(R,T,P,C)) = MAX(60,GG_PRBD(R,T,C,'UP'))*MAX(1,GG_GAMMA(R,T,P,C))*GG_KGF(R,T,P,C);
    mm = {(r, t, p, c): max(60.0, pb(r, t, c, "UP")) * max(1.0, gm(r, t, p, c)) * kgf.get((r, t, p, c), 0.0) for (r, t, p, c) in rtpc}
    # --- GG_PPW(GG_RTPC(R,T,P,C),R,C,'1')$GG_WTX(R,P,C) = SUM(OMG$GG_PP(R,T,P,C,'UP',OMG),1);
    for (r, t, p, c) in rtpc:
        if (r, p, c) in wtx:
            n = sum(1 for j in omg if (r, t, p, c, "UP", j) in pp)
            if n:
                ppw[(r, t, p, c, r, c, "1")] = float(n)
    # --- GG_KGF(GG_RTPC)$(NOT SUM((RC,J)$GG_PPW(GG_RTPC,RC,J),1)) = 0;
    has_w = {k[:4] for k in ppw}
    kgf = {k: v for k, v in kgf.items() if not (k in rtpc and k not in has_w)}
    # write
    _set(db, "GG_WTX", wtx); _set(db, "OMG", {(j,) for j in omg})
    _set(db, "GG_RTC", rtc); _set(db, "GG_RTPC", rtpc); _set(db, "GG_ARC", ggarc); _set(db, "GG_TOP", ggtop)
    _set(db, "GG_LINK", link); _set(db, "GG_EDGE", edge); _set(db, "GG_WINK", wink)
    _par(db, "GG_KGF", kgf); _par(db, "GG_KLP", klp); _par(db, "GG_PRBD", prbd); _par(db, "GG_GAMMA", gamma)
    _par(db, "GG_PP", pp); _par(db, "GG_PPM", ppm); _par(db, "GG_PPW", ppw); _par(db, "GG_MM", mm)


# ------------------------------------------------------------------------------------------------ DECL
def decl(db: DB):
    """powerflo.vda DECL and gasgrids.vda DECL (mod_vars.mod, before bndmain.mod)."""
    if not db.ctl.get("POWERFLO"):
        return
    # --- LOOP(J$SUM(GR_GRID(J,R,C)$GR_GID(R,C),1), Z = SMAX(GR_GRID(J,R,C),SUM(P$GR_FLOW(R,P,C),1));
    #       LOOP(GR_GRID(J,R,C)$Z,IF(SUM(P$GR_FLOW(R,P,C),1)=Z, Z=0; VAR_COMAUX.FX(R,T,C,S)=EPS)));
    #     (the phase angle of the node with most lines is zero; VAR_COMAUX is in the DC power flow equations only)
    q = db.q
    gid = {(r, c) for r, c in q("select r, c from GR_GID")}
    nl = {}
    for r, p, c in q("select r, p, c from GR_FLOW"):
        nl[(r, c)] = nl.get((r, c), 0) + 1
    grid = _sorted(db, q("select j, r, c from GR_GRID"))
    fx = {}
    T = [y for (y,) in q("select y from MILESTONYR")]
    S = [x for (x,) in q("select s from ALL_TS")]
    for j in dict.fromkeys(g[0] for g in grid if (g[1], g[2]) in gid):
        nodes = [(r, c) for jj, r, c in grid if jj == j]
        z = max(nl.get(k, 0) for k in nodes)
        for k in nodes:
            if z and nl.get(k, 0) == z:
                z = 0
                fx.update({(k[0], t, k[1], sl): (0.0, 0.0) for t in T for sl in S})
    _bound_table(db, "VAR_COMAUX", fx)
    #     GR_GRID(J,R,'ACT') $= SUM(GR_GRID(J,NRGELC(R,C)),1);
    db.add("GR_GRID", "select distinct g.j, g.r, 'ACT' as c from GR_GRID g where in_NRGELC(g.r, g.c)")
    # --- EQ_GR_XBND: the capacity of lines between regions (TOP_IRE with ALL_R <> R) is not written
    if db.card("GR_XBND") and db.q1("""select count(*) from TOP_IRE t join GR_GRID g on g.r=t.r and g.c=t.c
                                         where t.r <> t.r2""") + db.q1("""select count(*) from TOP_IRE t join GR_GRID g
                                         on g.r=t.r2 and g.c=t.c2 where t.r <> t.r2"""):
        unsupported(db, "N-1 bounds (GR_XBND) on grids with lines between regions (powerflo.vda EQ_GR_XBND)", ["GR_XBND"])
    candidates(db)
    if not gas(db):
        return
    # --- OPTION TRACKPC < GG_KLP; TRACKPC(R,P,C)$(NOT GR_FLOW(R,P,C)) = NO
    #     LOOP(GG_LINK(TRACKPC(R,P,C),REG,COM),RPC_EQIRE(REG,P,COM,IE) = NO);
    db.x("""delete from RPC_EQIRE e where exists(select 1 from GG_LINK l where l.r2=e.r and l.p=e.p and l.c2=e.c
             and exists(select 1 from GG_KLP k where k.r=l.r and k.p=l.p and k.c=l.c) and in_GR_FLOW(l.r,l.p,l.c))""")
    INF = float("inf")
    lo, up = {}, {}
    # --- LOOP(GG_TOP(R,C,REG,COM,P),
    #       VAR_GG_PR.LO(GG_RTC(R,T,C),S)$PRC_TS(R,P,S) = GG_PRBD(R,T,C,'LO');  .UP = GG_PRBD(R,T,C,'UP');
    #       VAR_GG_PR.LO(RTC(REG,T,COM),S)$PRC_TS(R,P,S) = GG_PRBD(RTC,'LO');      .UP = GG_PRBD(RTC,'UP'));
    #     (a zero upper bound is a bound of zero)
    prbd = {k[:4]: k[4] for k in q("select r, y, c, l, value from GG_PRBD")}
    ggrtc = set(q("select r, y, c from GG_RTC"))
    rtc = set(q("select r, y, c from RTC"))
    prcts = {}
    for r, p, sl in q("select r, p, s from PRC_TS"):
        prcts.setdefault((r, p), []).append(sl)
    pr_lo, pr_up = {}, {}
    for (r, c, r2, c2, p) in _sorted(db, q("select r, c, r2, c2, p from GG_TOP")):
        for (a, b, k) in ((r, c, ggrtc), (r2, c2, rtc)):
            for (x, t, y) in k:
                if x != a or y != b:
                    continue
                for sl in prcts.get((r, p), ()):
                    pr_lo[(a, t, b, sl)] = prbd.get((a, t, b, "LO"), 0.0)
                    pr_up[(a, t, b, sl)] = prbd.get((a, t, b, "UP"), 0.0)
    _bound_table(db, "VAR_GG_PR", {k: (pr_lo.get(k, 0.0), pr_up.get(k, INF)) for k in set(pr_lo) | set(pr_up)})
    # --- VAR_GG_PADD.LO(RTP(r,t,p),COM(%PGPRIM%),S)$(PRC_TS(R,P,S)$GG_KLP(r,t,p,COM)) =
    #       SUM(RPC_IRE(TRACKPC(R,P,C),'EXP'),MIN((GG_PRBD(R,T,C,'UP')*MAX(1,GG_GAMMA(R,T,P,C))+GG_PRBD(R,T,C,'LO'))/2*GG_KLP(R,T,P,C),
    #           GG_KLP(r,t,p,COM)) * GG_DENS(R,C) * RS_STGPRD(R,S));
    klp = {k[:4]: k[4] for k in q("select r, y, p, c, value from GG_KLP")}
    gamma = {k[:4]: k[4] for k in q("select r, y, p, c, value from GG_GAMMA")}
    dens = {(r, c): v for r, c, v in q("select r, c, value from GG_DENS")}
    stgprd = {(r, sl): v for r, sl, v in q("select r, s, value from RS_STGPRD")}
    flow = set(q("select r, p, c from GR_FLOW"))
    exp_ = set(q("select r, p, c from RPC_IRE where ie='EXP'"))
    trackpc = {(r, p, c) for (r, t, p, c) in klp if (r, p, c) in flow}
    pad = {}
    for (r, t, p) in q("select r, y, p from RTP"):
        a = klp.get((r, t, p, "ACT"))
        if not a:
            continue
        for sl in prcts.get((r, p), ()):
            v = sum(min((prbd.get((r, t, c, "UP"), 0.0) * max(1.0, gamma.get((r, t, p, c), 0.0)) + prbd.get((r, t, c, "LO"), 0.0)) / 2
                        * klp.get((r, t, p, c), 0.0), a) * dens.get((r, c), 0.0) * stgprd.get((r, sl), 0.0)
                    for (r2, p2, c) in trackpc if r2 == r and p2 == p and (r, p, c) in exp_)
            pad[(r, t, p, "ACT", sl)] = (v, INF)
    _bound_table(db, "VAR_GG_PADD", pad)
    # --- VAR_GG_PDIF.FX(GG_RTPC(REG,T,P,COM),R,C,S)$((NOT GG_LINK(REG,P,COM,R,C))$GG_LINK(R,P,C,REG,COM)$PRC_TS(REG,P,S)) = 0;
    link = set(q("select r, p, c, r2, c2 from GG_LINK"))
    rtpc = set(q("select r, y, p, c from GG_RTPC"))
    pdif = {}
    for (r, p, c, r2, c2) in link:
        if (r2, p, c2, r, c) in link:
            continue
        for (x, t, y, z) in rtpc:
            if (x, y, z) == (r2, p, c2):
                for sl in prcts.get((r2, p), ()):
                    pdif[(r2, t, p, c2, r, c, sl)] = (0.0, 0.0)
    _bound_table(db, "VAR_GG_PDIF", pdif)
    # --- VAR_GG_STEP.UP(RTPCS_VARF(GG_RTPC(R,T,P,C),S),GG_O)$SUM(GG_LINK(R,P,C,RC)$GG_PPW(R,T,P,C,RC,GG_O),1) = EXP(1);
    ppw = set(q("select r, y, p, c, r2, c2, j from GG_PPW"))
    varf = {}
    for r, t, p, c, sl in q("select r, y, p, c, s from RTPCS_VARF"):
        varf.setdefault((r, t, p, c), []).append(sl)
    step = {}
    for (r, t, p, c, r2, c2, j) in ppw:
        if (r, t, p, c) in rtpc and (r, p, c, r2, c2) in link and 1 <= int(j) <= GG_WN:
            for sl in varf.get((r, t, p, c), ()):
                step[(r, t, p, c, sl, j)] = (0.0, math.e)
    _bound_table(db, "VAR_GG_STEP", step)
    # --- VAR_GG_Y.UP(RTPCS_VARF(GG_RTPC,S)) = 1;           (in the MIP VAR_GG_Y is binary: 1 is its default bound)
    if not db.ctl.get("SOLMIP"):
        _bound_table(db, "VAR_GG_Y", {(r, t, p, c, sl): (0.0, 1.0) for (r, t, p, c) in rtpc for sl in varf.get((r, t, p, c), ())})


def candidates(db: DB):
    """powerflo.vda DECL: IF(CARD(GR_CANDID), ...): virtual capacity bounds of the candidate lines."""
    q = db.q
    candid = set(q("select r, y, p from GR_CANDID"))
    if not candid:
        return
    T = [y for (y,) in q("select y from MILESTONYR order by yv(y)")]
    # --- GR_CAPUP(GR_CANDID(R,T,P)) = SUM(PYR(V)$COEF_CPT(R,V,T,P),NCAP_PASTI(R,V,P)*ROUND(COEF_CPT(R,V,T,P)));
    pasti = {(r, v, p): x for r, v, p, x in q("select r, y, p, value from NCAP_PASTI")}
    pyr = {y for (y,) in q("select y from PASTYEAR")}          # PYR: alias of PASTYEAR
    capup = {}
    for r, v, t, p, x in q("select r, y, y2, p, value from COEF_CPT"):
        if (r, t, p) in candid and v in pyr and x:
            capup[(r, t, p)] = capup.get((r, t, p), 0.0) + pasti.get((r, v, p), 0.0) * math.copysign(math.floor(abs(x) + 0.5), x)
    capup = {k: v for k, v in capup.items() if v != 0}
    # --- GR_CANDID(R,T,P)$SUM(RP_GRID(REG,P)$GR_CAPUP(REG,T,P),1) = NO;   RVP(GR_CANDID) = YES;
    rp_grid = set(q("select r, p from RP_GRID"))
    candid = {(r, t, p) for (r, t, p) in candid if not any((r2, t, p) in capup for (r2, p2) in rp_grid if p2 == p)}
    rvp = set(candid)
    # --- GR_CAPUP(RVP(R,T,P))$GR_DNCAP(R,P) = ...                                  (GR_DNCAP is 0 without DSC)
    # --- LOOP(T,GR_CAPUP(RVP(R,TT(MIYR_1),P))$(NOT GR_CAPUP(RVP)) = MAX(CAP_BND(R,T,P,'UP'),GR_CAPUP(R,T,P))+1-1);
    capbnd = {(r, t, p): v for r, t, p, v in q("select r, y, p, value from CAP_BND where l='UP'")}
    first = {y for (y,) in q("select y from MIYR_1")}
    for t in T:
        for (r, tt, p) in sorted(rvp):
            if tt in first and not capup.get((r, tt, p)):
                v = max(capbnd.get((r, t, p), 0.0), capup.get((r, t, p), 0.0)) + 1 - 1
                if v:
                    capup[(r, tt, p)] = v
    # --- LOOP(TT(T+1),GR_CAPUP(RVP(R,TT,P))$(NOT GR_CAPUP(RVP)) = GR_CAPUP(R,T,P)+(CAP_BND(RVP,'UP')-GR_CAPUP(R,T,P))$(CAP_BND(RVP,'UP')>0));
    for t, tt in zip(T, T[1:]):
        for (r, t2, p) in sorted(rvp):
            if t2 == tt and not capup.get((r, tt, p)):
                prev = capup.get((r, t, p), 0.0)
                cb = capbnd.get((r, tt, p), 0.0)
                v = prev + ((cb - prev) if cb > 0 else 0.0)
                if v:
                    capup[(r, tt, p)] = v
    # --- LOOP(GR_TOP(R,C,REG,COM,P),GR_CAPUP(R,T,P)$GR_CAPUP(REG,T,P)=MIN(GR_CAPUP(REG,T,P),GR_CAPUP(R,T,P)+INF$(NOT GR_CAPUP(R,T,P)));
    #        IF(NOT SAMEAS(R,REG),GR_CAPUP(REG,T,P) = 0));
    for (r, c, r2, c2, p) in _sorted(db, q("select r, c, r2, c2, p from GR_TOP")):
        for t in T:
            if capup.get((r2, t, p)):
                a = capup.get((r, t, p), 0.0)
                capup[(r, t, p)] = min(capup[(r2, t, p)], a if a else math.inf)
            if r != r2:
                capup.pop((r2, t, p), None)
    # --- GR_CANDID(RVP)$(NOT GR_CAPUP(RVP)) = NO;
    candid = {k for k in candid if capup.get(k)}
    # --- CAP_BND(GR_CANDID(R,T,P),'UP')$((NOT CAP_BND(R,T,P,'UP'))$(NOT GR_DNCAP(R,P))) = GR_CAPUP(R,T,P);
    #     RTP_VARP(GR_CANDID(R,T,P))$(NOT GR_DNCAP(R,P)) = YES;
    _add_par(db, "CAP_BND", {(r, t, p, "UP"): capup[(r, t, p)] for (r, t, p) in candid if not capbnd.get((r, t, p))})
    _add(db, "RTP_VARP", candid)
    # --- VAR_IRE.LO(R,T,T,P,C(ACTCG),S,'EXP')$(PRC_TS(R,P,S)$RVP(R,T,P)) = -INF;   OPTION CLEAR=RVP;
    #     (the virtual flow over a candidate line is the export of ACT, a free variable)
    ire = {(r, t, t, p, "ACT", sl, "EXP"): (-math.inf, math.inf)
           for (r, t, p) in rvp for (r2, p2, sl) in q("select r, p, s from PRC_TS") if (r2, p2) == (r, p)}
    _bound_table(db, "VAR_IRE", ire)
    db.clear("RVP")
    _set(db, "GR_CANDID", candid)
    _par(db, "GR_CAPUP", capup)


def _bound_table(db, var, d):
    """B_<var>(d0..dn, lower, upper) with the bounds that differ from 0 .. +INF."""
    INF = float("inf")
    rows = [k + v for k, v in sorted(d.items()) if v != (0.0, INF)]
    n = len(next(iter(d))) if d else 0
    if not n:
        return
    db.x(f'create or replace table "B_{var}" ({", ".join(f"d{i} VARCHAR" for i in range(n))}, lower DOUBLE, upper DOUBLE)')
    if rows:
        db.insert_rows(f'"B_{var}"', rows)
    db.bounds.add(var)
