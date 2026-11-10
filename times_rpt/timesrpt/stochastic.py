# SPDX-License-Identifier: GPL-3.0-or-later
"""The reports of a stochastic run ($SET STAGES YES): rptmain.stc, and the Veda file of times2veda_stc.vdd.

rptmain.mod 32 calls rptmain.stc instead of the ordinary report:

    $BATINCLUDE rptmain.stc SOW %SWS% "'1'" ",'1')"

Inside it %VAR% is VAS and %EQ% is ES (the variables and equations of the stochastic model carry the SOW index W, the
equations also the stage period T); %VART%_x(..,T,..%SWS%) is SUM(SW_TSW(SOW,T,W),VAS_x(..,T,..,W)): the value of the
SOW W that represents SOW at period T.

rptmain.stc 24-27, the factors that undo the probability weights of the marginals:

    SW_UNPB(SW_T(T,W))=POWER(SW_TPROB(T,W)/SW_NORM,1$SW_PHASE-1); SW_UNPC(T,W) $= SW_UNPB(T,W);
    SW_UNPB('0',W)=POWER(SW_PROB(W)/SW_NORM,1$SW_PHASE-1$SW_PROB(W));

Then, for each SOW with a probability (LOOP(SOW$SW_PROB(SOW), ...)), the solution store is cleared (clearsol.stc), the
levels and marginals of that SOW are put into the VAR_x and EQ_x of the ordinary model (rptmain.stc 37-71, quoted at
SOW_LEVELS and the tables below) and the ordinary reports run with the prefix S and the index SOW (rpt_obj.rpt,
cost_ann.rpt, rptmisc.rpt): SPAR_ACTL(SOW,R,V,T,P,S) is PAR_ACTL of that SOW.  Here each SOW runs the ordinary
report (rptmisc.run) on a database of its own, and its report parameters are stored with the SOW as first index.
The statements of the ordinary report that read %VAR%_x(..%3) read VAS_x(..,SOW) (the SOW itself, not its
representative): VAR_UC, VAR_UCR, VAR_CUMFLO, VAR_CUMCST, VAR_RCAP, VAR_OBJ, VAR_OBJELS and EQG_UCMAX here.

After the loop (rptmain.stc 103-104):

    REG_WOBJ(R,ITEM,CUR) $= SUM(W$SREG_WOBJ(W,R,ITEM,CUR),SW_PROB(W)*SREG_WOBJ(W,R,ITEM,CUR));
    $BATINCLUDE pextlevs.stc "%1"

pextlevs.stc puts the expected levels into VAR_x; times2veda_stc.vdd reads none of them, so it is not done here.
"""
from __future__ import annotations
import os

from timespp.engine import DB

from . import load as _load

# rptmain.stc 37-52, the levels of the representative SOW:
#     VAR_ACT.L(R,V,T,P,S)      $= %VART%_ACT.L(R,V,T,P,S %SWS%);
#     VAR_BLND.L(R,T,COM,C)     $= %VART%_BLND.L(R,T,COM,C %SWS%);
#     VAR_CAP.L(R,T,P)          $= %VART%_CAP.L(R,T,P %2);
#     VAR_COMNET.L(R,T,COM,S)   $= %VART%_COMNET.L(R,T,COM,S %SWS%);
#     VAR_COMPRD.L(R,T,COM,S)   $= %VART%_COMPRD.L(R,T,COM,S %SWS%);
#     VAR_IRE.L(R,V,T,P,C,S,IE) $= %VART%_IRE.L(R,V,T,P,C,S,IE %SWS%);
#     VAR_ELAST.L(R,T,C,S,J,BD) $= %VART%_ELAST.L(R,T,C,S,J,BD %SWS%);
#     VAR_FLO.L(R,V,T,P,C,S)    $= %VART%_FLO.L(R,V,T,P,C,S %SWS%);
#     VAR_NCAP.L(R,T,P)         $= %VART%_NCAP.L(R,T,P %2);
#     VAR_SIN.L(R,V,T,P,C,S)    $= %VART%_SIN.L(R,V,T,P,C,S %SWS%);
#     VAR_SOUT.L(R,V,T,P,C,S)   $= %VART%_SOUT.L(R,V,T,P,C,S %SWS%);
#     VAR_UPS.L(R,V,T,P,S,L)    $= %VART%_UPS.L(R,V,T,P,S,L %SWS%);
#     VAR_UPT.L(R,V,T,P,S,UPT)  $= %VART%_UPT.L(R,V,T,P,S,UPT %SWS%);
#     VAR_UDP.L(R,V,T,P,S,L)    $= %VART%_UDP.L(R,V,T,P,S,L %SWS%);
#     VAR_SCAP.L(R,V,T,P)       $= %VART%_SCAP.L(R,V,T,P%2); VAR_SCAP.L(R,V,'0',P) $= %VAR%_SCAP.L(R,V,'0',P,%1);
# and rptmisc.rpt 171-174, the levels of the user constraints by period:
#     %1PAR_UCSL(%2UC_N,'NONE',T,'NONE') $= %VART%_UCT.L(UC_N,T%SWS%);  (and UCRT, UCTS, UCRTS)
# name: position of the period T among the indexes of VAR_x
SOW_LEVELS = {
    "VAR_ACT": 2, "VAR_BLND": 1, "VAR_CAP": 1, "VAR_COMNET": 1, "VAR_COMPRD": 1, "VAR_IRE": 2, "VAR_ELAST": 1,
    "VAR_FLO": 2, "VAR_NCAP": 1, "VAR_SIN": 2, "VAR_SOUT": 2, "VAR_UPS": 2, "VAR_UPT": 2, "VAR_UDP": 2,
    "VAR_SCAP": 2, "VAR_UCT": 1, "VAR_UCRT": 2, "VAR_UCTS": 1, "VAR_UCRTS": 2,
}
# The levels read as %VAR%_x.L(..%3), %3 = ,SOW: of the SOW itself.
#   rptmisc.rpt 73    %VAR%_RCAP.L(R,V,TT,P%3)
#   rptmisc.rpt 151   %VAR%_CUMFLO.L(R,P,C,YEAR,LL%3)       153  %VAR%_CUMCST.L(R,YEAR,LL,COSTAGG,CUR%3)
#   rptmisc.rpt 169   %VAR%_UC.L(UC_N%3)                    170  %VAR%_UCR.L(UC_N,R%3)
#   rptmisc.rpt 187   %EQ%G_UCMAX.L(UC_N,ALL_R,'N',C,'N'%3)
#   rpt_obj.rpt 77    %VAR%_OBJ.L(R,OBV,CUR%3)              146  %VAR%_OBJELS.L(R,BD,CUR%3)
SOW_OWN_LEVELS = ("VAR_RCAP", "VAR_CUMFLO", "VAR_CUMCST", "VAR_UC", "VAR_UCR", "EQG_UCMAX", "VAR_OBJ", "VAR_OBJELS")
# rptmain.stc 55-61, the marginals of the representative SOW without the probability:
#     VAR_ACT.M(R,V,T,P,S)    $= %VART%_ACT.M(R,V,T,P,S,W)*SW_UNPB(T%SWS%);
#     VAR_CAP.M(R,T,P)        $= SUM(SW_TSW(%1,T,W),%VAR%_CAP.M(R,T,P,W)*SW_UNPC(T,W));
#     VAR_NCAP.M(R,T,P)       $= SUM(SW_TSW(%1,T,W),%VAR%_NCAP.M(R,T,P,W)*SW_UNPC(T,W));
#     VAR_COMNET.M(R,T,COM,S) $= %VART%_COMNET.M(R,T,COM,S,W)*SW_UNPB(T%SWS%);
#     VAR_COMPRD.M(R,T,COM,S) $= %VART%_COMPRD.M(R,T,COM,S,W)*SW_UNPB(T%SWS%);
#     VAR_FLO.M(R,V,T,P,C,S)  $= %VART%_FLO.M(R,V,T,P,C,S,W)*SW_UNPB(T%SWS%);
# and rptmisc.rpt 176-183 with %4 = ,W)*SW_UNPB(T,W):
#     %1PAR_UCSM(%2UC_N,'NONE',T,'NONE') $= %VART%_UCT.M(UC_N,T%4);  (and UCRT, UCTS, UCRTS)
# name: (position of T, factor: B = SW_UNPB, C = SW_UNPC)
SOW_MARGINALS = {
    "VAR_ACT": (2, "b"), "VAR_CAP": (1, "c"), "VAR_NCAP": (1, "c"), "VAR_COMNET": (1, "b"), "VAR_COMPRD": (1, "b"),
    "VAR_FLO": (2, "b"), "VAR_UCT": (1, "b"), "VAR_UCRT": (2, "b"), "VAR_UCTS": (1, "b"), "VAR_UCRTS": (2, "b"),
}
# rptmisc.rpt 152, 178-179 with %5 = ,SOW)*SW_UNPB('0',SOW: the SOW itself, without its probability
#     %1PAR_CUMFLOM(%2R,P,C,YEAR,LL) $= %VAR%_CUMFLO.M(R,P,C,YEAR,LL%5)*(1/%CUFSCAL%);
#     %1PAR_UCSM(%2UC_N,'NONE','NONE','NONE') $= %VAR%_UC.M(UC_N%5);
#     %1PAR_UCSM(%2UC_N,R,'NONE','NONE')      $= %VAR%_UCR.M(UC_N,R%5);
SOW_OWN_MARGINALS = ("VAR_CUMFLO", "VAR_UC", "VAR_UCR")
# rptmain.stc 64-69, 98-99, the equation marginals (the equations ES_x carry the stage period T and W last):
#     EQG_COMBAL.M(R,T,C,S)  $= SUM(SW_TSW(SOW,T,W),%EQ%G_COMBAL.M(R,T,C,S,T,W)*SW_UNPB(T,W));
#     EQE_COMBAL.M(R,T,C,S)  $= SUM(SW_TSW(SOW,T,W),%EQ%E_COMBAL.M(R,T,C,S,T,W)*SW_UNPB(T,W));
#     EQE_COMPRD.M(R,T,C,S)  $= SUM(SW_TSW(SOW,T,W),%EQ%E_COMPRD.M(R,T,C,S,T,W)*SW_UNPB(T,W));
#     EQ_PEAK.M(R,T,CG,S)    $= SUM(SW_TSW(SOW,T,W),%EQ%_PEAK.M(R,T,CG,S,T,W)*SW_UNPB(T,W));
#     EQ_IRE.M(R,T,P,C,IE,S) $= SUM(SW_TSW(SOW,T,W),%EQ%_IRE.M(R,T,P,C,IE,S,T,W)*SW_UNPB(T,W));
#     EQE_CPT.M(R,T,P)       $= SUM(SW_TSW(%1,T,W),%EQ%E_CPT.M(R,T,P,T,W)*SW_UNPC(T,W));
#   EQN_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD('FX'))  $= SUM(SW_TSW(SOW,T,W),%EQ%E_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD,T,W)*SW_UNPB(T,W));
#   EQN_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BDNEQ(BD)) $= SUM(SW_TSW(SOW,T,W),%EQ%N_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD,T,W)*SW_UNPB(T,W));
# EQ name: (ES name, position of T, factor, condition on the BD column)
EQ_MARGINALS = [
    ("EQG_COMBAL", "ESG_COMBAL", 1, "b", None), ("EQE_COMBAL", "ESE_COMBAL", 1, "b", None),
    ("EQE_COMPRD", "ESE_COMPRD", 1, "b", None), ("EQ_PEAK", "ES_PEAK", 1, "b", None),
    ("EQ_IRE", "ES_IRE", 1, "b", None), ("EQE_CPT", "ESE_CPT", 1, "c", None),
    ("EQN_UCRTP", "ESE_UCRTP", 2, "b", "= 'FX'"), ("EQN_UCRTP", "ESN_UCRTP", 2, "b", "in ('LO', 'UP')"),
]

# The report parameters of the ordinary report times2veda_stc.vdd reads with the prefix S: the GAMS name in the vdd
# (spar_actl, sf_in, scst_invc, SCap_New, CM_SRESULT) -> the parameter of the ordinary report.
def ordinary_name(gams):
    g = gams.upper()
    if g.startswith("CM_S"):
        return "CM_" + g[4:]
    return g[1:]


def ported(gams, indexes):
    """Whether the stochastic report fills the GAMS symbol of a times2veda_stc.vdd entry."""
    from .vd import PORTED
    g = gams.lower()
    if g in ("reg_wobj", "objz.l"):
        return True
    if not indexes or indexes[0] != "w":
        return False
    det = ordinary_name(gams).lower()
    return det == "par_combalgm" or det in {p.lower() for p in PORTED}


def on(env):
    """A run with $SET STAGES YES."""
    return str((env or {}).get("STAGES", "")).strip().strip("'\"").upper() == "YES"


def _model_tables(db, model, names):
    """{name: rows} of tables of model.db3 the declarations of the port do not hold (SW_TSW, S_CAP_BND, ...)."""
    _load._attach_model(db, model.replace("\\", "/"))
    try:
        have = {r[0] for r in db.con.execute(
            "select table_name from information_schema.tables where table_catalog = 'mdl'").fetchall()}
        return {n: [tuple(r) for r in db.con.execute(f'select * from mdl."{n}"').fetchall()] if n in have else []
                for n in names}
    finally:
        db.con.execute("detach mdl")


class Tree:
    """The SOWs, their probabilities and representatives, and the factors SW_UNPB / SW_UNPC."""

    def __init__(self, t):
        up = lambda x: str(x).upper()
        self.sow = [up(w) for (w,) in t["SOW"]]
        self.prob = {up(w): float(v) for w, v in t["SW_PROB"]}
        self.tprob = {(up(y), up(w)): float(v) for y, w, v in t["SW_TPROB"]}
        self.tsw = [(up(s), up(y), up(w)) for s, y, w in t["SW_TSW"]]
        self.sw_t = [(up(y), up(w)) for y, w in t["SW_T"]]
        norm = float(t["SW_NORM"][0][0]) if t["SW_NORM"] else 0.0
        phase = float(t["SW_PHASE"][0][0]) if t["SW_PHASE"] else 0.0
        # SW_UNPB(SW_T(T,W))=POWER(SW_TPROB(T,W)/SW_NORM,1$SW_PHASE-1); SW_UNPC(T,W) $= SW_UNPB(T,W);
        # SW_UNPB('0',W)=POWER(SW_PROB(W)/SW_NORM,1$SW_PHASE-1$SW_PROB(W));
        self.unpb, self.unpc = {}, {}
        for y, w in self.sw_t:
            v = _power(self.tprob.get((y, w), 0.0) / norm if norm else 0.0, (1 if phase else 0) - 1)
            self.unpb[(y, w)] = v
            if v:
                self.unpc[(y, w)] = v
        for w in self.sow:
            p = self.prob.get(w, 0.0)
            self.unpb[("0", w)] = _power(p / norm if norm else 0.0, (1 if phase else 0) - (1 if p else 0))
        self.s_com_tax = [tuple(up(x) for x in r[:-1]) + (float(r[-1]),) for r in t["S_COM_TAX"]]
        self.obj_sic = [(up(r), up(y), up(p), up(w), float(v)) for r, y, p, w, v in t["OBJ_SIC"]]
        self.ffcs = [tuple(up(x) for x in r[:-1]) + (float(r[-1]),) for r in t["RTP_FFCS"]]
        self.sfrw = [tuple(up(x) for x in r[:-1]) + (float(r[-1]),) for r in t["RTCS_SFRW"]]
        self.s_cap_bnd = [(up(r), up(y), up(p), up(bd), up(j), up(w), float(v)) for r, y, p, bd, j, w, v in t["S_CAP_BND"]]


def _power(x, n):
    """GAMS POWER(x, n) for an integer n (x**0 is 1, also for x = 0; 0**-1 is an error in GAMS, 0 here)."""
    if n == 0:
        return 1.0
    if x == 0:
        return 0.0
    return x ** n


TREE_TABLES = ("SOW", "SW_PROB", "SW_TPROB", "SW_TSW", "SW_T", "SW_NORM", "SW_PHASE", "S_CAP_BND", "S_COM_TAX", "OBJ_SIC", "RTP_FFCS",
               "RTCS_SFRW")


def _sol_tables(db):
    return {r[0].upper(): r[0] for r in db.con.execute(
        "select table_name from information_schema.tables where table_catalog = 'sol'").fetchall()}


def _put_sow(db, tree, w):
    """rptmain.stc 34-71 for SOW w: clearsol.stc, then the levels and marginals of w in the tables L_x / M_x."""
    # clearsol.stc: every level and marginal of the ordinary model is cleared; only those set below are read.
    for name in list(db.sym):
        if name.startswith(("L_", "M_")) and db.sym[name].kind == "par":
            db.clear(name)
    for name in list(db.s):
        if name.startswith(("L_", "M_")):
            db.s[name] = 0.0
    tabs = _sol_tables(db)
    flags = {(t, c) for t, c in db.con.execute(
        "select table_name, column_name from information_schema.columns where table_catalog = 'sol'").fetchall()}
    db.con.execute("create or replace temp table sw_rep_ (t varchar, w varchar, b double, c double)")
    rows = [(y, ww, tree.unpb.get((y, ww), 0.0), tree.unpc.get((y, ww), 0.0)) for s, y, ww in tree.tsw if s == w]
    if rows:
        db.con.executemany("insert into sw_rep_ values (?, ?, ?, ?)", rows)
    unp0 = tree.unpb.get(("0", w), 0.0)

    def declare(name):
        dom = _load.DOMAINS.get(name[2:])
        if dom is None:
            return None
        if name not in db.sym:
            db.declare(name, "par", dom)
        return db.cols(name)

    def live(s, col):
        """The records of a level or marginal that are there: nonzero, or EPS (a solution with the EPS flag)."""
        if (s, col + "_sv") in flags:
            return f"(v.{col} <> 0 or v.{col}_sv = 'EPS')"
        return f"v.{col} <> 0"

    def src(det, pre="VAS"):
        n = det.replace("VAR_", pre + "_", 1) if det.startswith("VAR_") else "ES" + det[2:]
        return tabs.get(n)

    for name, tpos in SOW_LEVELS.items():
        s = src(name)
        cols = declare("L_" + name) if s else None
        if not cols:
            continue
        n = len(cols)
        lab = ", ".join(f"upper(v.d{i})" for i in range(n))
        db.x(f'''insert into "L_{name}" select {lab}, v.level from sol."{s}" v
                 join sw_rep_ m on m.t = upper(v.d{tpos}) and m.w = upper(v.d{n})
                 where {live(s, "level")}''')
        if name == "VAR_SCAP":
            # VAR_SCAP.L(R,V,'0',P) $= %VAR%_SCAP.L(R,V,'0',P,%1);
            db.x(f'''insert into "L_{name}" select {lab}, v.level from sol."{s}" v
                     where v.d2 = '0' and upper(v.d{n}) = '{w}' and {live(s, "level")}''')
    for name in SOW_OWN_LEVELS:
        s = src(name, "VAS") if name.startswith("VAR_") else tabs.get("ES" + name[2:])
        cols = declare("L_" + name) if s else None
        if not cols:
            continue
        n = len(cols)
        lab = ", ".join(f"upper(v.d{i})" for i in range(n))
        db.x(f'''insert into "L_{name}" select {lab}, v.level from sol."{s}" v
                 where upper(v.d{n}) = '{w}' and {live(s, "level")}''')
    for name, (tpos, f) in SOW_MARGINALS.items():
        s = src(name)
        cols = declare("M_" + name) if s else None
        if not cols:
            continue
        n = len(cols)
        lab = ", ".join(f"upper(v.d{i})" for i in range(n))
        db.x(f'''insert into "M_{name}" select {lab}, v.marginal * m.{f} from sol."{s}" v
                 join sw_rep_ m on m.t = upper(v.d{tpos}) and m.w = upper(v.d{n})
                 where {live(s, "marginal")} and m.{f} <> 0''')
    for name in SOW_OWN_MARGINALS:
        s = src(name)
        cols = declare("M_" + name) if s else None
        if not cols or not unp0:
            continue
        n = len(cols)
        lab = ", ".join(f"upper(v.d{i})" for i in range(n))
        db.x(f'''insert into "M_{name}" select {lab}, v.marginal * {unp0!r} from sol."{s}" v
                 where upper(v.d{n}) = '{w}' and {live(s, "marginal")}''')
    for name, es, tpos, f, bd in EQ_MARGINALS:
        s = tabs.get(es)
        cols = declare("M_" + name) if s else None
        if not cols:
            continue
        n = len(cols)
        lab = ", ".join(f"upper(v.d{i})" for i in range(n))
        cond = f" and upper(v.d{n - 1}) {bd}" if bd else ""
        db.x(f'''insert into "M_{name}" select {lab}, v.marginal * m.{f} from sol."{s}" v
                 join sw_rep_ m on m.t = upper(v.d{n}) and m.w = upper(v.d{n + 1})
                 where upper(v.d{tpos}) = upper(v.d{n}) and {live(s, "marginal")} and m.{f} <> 0{cond}''')
    # rptmain.stc 70:  EQG_COMBAL.L(R,T,C,S)  $= %EQ%G_COMBAL.L(R,T,C,S,T,SOW);
    s = tabs.get("ESG_COMBAL")
    if s and declare("L_EQG_COMBAL"):
        db.x(f'''insert into "L_EQG_COMBAL" select upper(v.d0), upper(v.d1), upper(v.d2), upper(v.d3), v.level
                 from sol."{s}" v where upper(v.d1) = upper(v.d4) and upper(v.d5) = '{w}'
                   and {live(s, "level")}''')


def sensis(env):
    """maindrv.mod 34: $IFI %SENSIS% == YES $SET STAGES Yes: one deterministic model solved for each SOW of the first
    period (solve.stc 35-52), each reported after its solve with the prefix S (solve.stc 56:
    $BATINCLUDE rptlite.rpt S WW, ALLSOW, NO); rptmain.mod 18 then skips the report of the whole run."""
    g = lambda k: str((env or {}).get(k, "")).strip("'\" ").upper()
    return g("SENSIS") == "YES" and g("SPINES") != "YES"


def sensis_solution(solution, w):
    """The solution file of the solve of SOW w of a SENSIS run: <solution>~<w>.<ext>."""
    base, ext = os.path.splitext(solution)
    return f"{base}~{w}{ext}"


def deterred(env):
    """rptmain.stc 19-20: SPINES with SOLVEDA 1 (rptmain.mod 17 sets it with VDA YES) reports the expected values
    (DETERRED: pextlevs.stc, then the ordinary report of SOW '1') in place of the reports of each SOW.
        $IFI %SPINES%%SOLVEDA%==YES1 $GOTO DETERRED"""
    g = lambda k: str((env or {}).get(k, "")).strip("'\" ").upper()
    return g("SPINES") == "YES" and (g("VDA") == "YES" or g("SOLVEDA") == "1")


# pextlevs.stc (%1 = '1', %2 empty), the expected levels:
#   VAR_ACT.L(R,V,T,P,S) $= SUM(SW_T(T,W), SW_TPROB(T,W)*%VAR%_ACT.L(R,V,T,P,S,W));   (and BLND, COMNET, COMPRD, IRE,
#     ELAST, FLO, SIN, SOUT, UPS, UCT, UCRT, UCTS, UCRTS)
#   VAR_CUMCOM.L(R,C,COM_VAR,YEAR,LL)$RC_CUMCOM(R,COM_VAR,YEAR,LL,C) $= SUM(W, SW_PROB(W)*%VAR%_CUMCOM.L(R,C,COM_VAR,YEAR,LL,W));
#     (and CUMFLO$RPC_CUMFLO, OBJELS, UC, UCR, OBJ)
#   VAR_CAP.L(R,T,P) $= SUM(SW_T(T,SOW), SW_TPROB(T,SOW)*%VAR%_CAP.L(R,T,P,%1));   (and NCAP, SCAP, RCAP)
# name: (position of T, weight: t = SW_TPROB(T,W) over SW_T(T,W); p = SW_PROB(W) over W; c = the level of '1' times
# SUM(SW_T(T,SOW), SW_TPROB(T,SOW)))
EXP_LEVELS = {
    "VAR_ACT": (2, "t"), "VAR_BLND": (1, "t"), "VAR_COMNET": (1, "t"), "VAR_COMPRD": (1, "t"), "VAR_IRE": (2, "t"),
    "VAR_ELAST": (1, "t"), "VAR_FLO": (2, "t"), "VAR_SIN": (2, "t"), "VAR_SOUT": (2, "t"), "VAR_UPS": (2, "t"),
    "VAR_CUMCOM": (None, "p"), "VAR_CUMFLO": (None, "p"), "VAR_OBJELS": (None, "p"),
    "VAR_CAP": (1, "c"), "VAR_NCAP": (1, "c"), "VAR_SCAP": (2, "c"), "VAR_RCAP": (2, "c"),
    "VAR_UC": (None, "p"), "VAR_UCR": (None, "p"), "VAR_UCT": (1, "t"), "VAR_UCRT": (2, "t"), "VAR_UCTS": (1, "t"),
    "VAR_UCRTS": (2, "t"), "VAR_OBJ": (None, "p"),
}
# the sums of the marginals:
#   VAR_ACT.M(R,V,T,P,S) $= SUM(SW_T(T,W), %VAR%_ACT.M(R,V,T,P,S,W));   (and COMNET, COMPRD, UCT, UCRT, UCTS, UCRTS)
#   VAR_CUMFLO.M(R,P,C,YEAR,LL) $= SUM(W, %VAR%_CUMFLO.M(R,P,C,YEAR,LL,W));   (and UC, UCR)
#   VAR_CAP.M(R,T,P) $= SUM(SW_T(T,%1), %VAR%_CAP.M(R,T,P,%1));   (and NCAP)
# name: (position of T, s = over SW_T(T,W); a = over W; 1 = of '1' where SW_T(T,'1'))
EXP_MARGINALS = {
    "VAR_ACT": (2, "s"), "VAR_COMNET": (1, "s"), "VAR_COMPRD": (1, "s"), "VAR_CUMFLO": (None, "a"),
    "VAR_CAP": (1, "1"), "VAR_NCAP": (1, "1"), "VAR_UC": (None, "a"), "VAR_UCR": (None, "a"),
    "VAR_UCT": (1, "s"), "VAR_UCRT": (2, "s"), "VAR_UCTS": (1, "s"), "VAR_UCRTS": (2, "s"),
}
#   EQG_COMBAL.M(R,T,C,S) $= SUM(SW_T(T,W), %EQ%G_COMBAL.M(R,T,C,S,T,W));   (and EQE_COMBAL, EQE_COMPRD, EQ_PEAK, EQ_IRE)
#   EQE_CPT.M(R,T,P) $= SUM(SW_T(T,%1), %EQ%E_CPT.M(R,T,P,T,%1));
#   EQN_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD('FX'))  $= SUM(SW_T(T,W), %EQ%E_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD,T,W));
#   EQN_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BDNEQ(BD)) $= SUM(SW_T(T,W), %EQ%N_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD,T,W));
# EQ name: (ES name, position of T, s or 1 as above, condition on the BD column)
EXP_EQ_MARGINALS = [
    ("EQG_COMBAL", "ESG_COMBAL", 1, "s", None), ("EQE_COMBAL", "ESE_COMBAL", 1, "s", None),
    ("EQE_COMPRD", "ESE_COMPRD", 1, "s", None), ("EQ_PEAK", "ES_PEAK", 1, "s", None), ("EQ_IRE", "ES_IRE", 1, "s", None),
    ("EQE_CPT", "ESE_CPT", 1, "1", None),
    ("EQN_UCRTP", "ESE_UCRTP", 2, "s", "= 'FX'"), ("EQN_UCRTP", "ESN_UCRTP", 2, "s", "in ('LO', 'UP')"),
]


def _put_expected(db, tree):
    """rptmain.stc 106-114 (DETERRED): clearsol.stc, then pextlevs.stc: the expected levels and the sums of the
    marginals of every SOW in the tables L_x / M_x, for the ordinary report of SOW '1'."""
    for name in list(db.sym):
        if name.startswith(("L_", "M_")) and db.sym[name].kind == "par":
            db.clear(name)
    for name in list(db.s):
        if name.startswith(("L_", "M_")):
            db.s[name] = 0.0
    tabs = _sol_tables(db)
    flags = {(t, c) for t, c in db.con.execute(
        "select table_name, column_name from information_schema.columns where table_catalog = 'sol'").fetchall()}
    db.con.execute("create or replace temp table swt_ (t varchar, w varchar, p double)")
    db.con.execute("create or replace temp table sowp_ (w varchar, p double)")
    db.con.execute("create or replace temp table sumt_ (t varchar, p double)")
    swt = [(y, w, tree.tprob.get((y, w), 0.0)) for y, w in tree.sw_t]
    if swt:
        db.con.executemany("insert into swt_ values (?, ?, ?)", swt)
        acc = {}
        for y, _w, p in swt:
            acc[y] = acc.get(y, 0.0) + p
        db.con.executemany("insert into sumt_ values (?, ?)", list(acc.items()))
    db.con.executemany("insert into sowp_ values (?, ?)", [(w, tree.prob.get(w, 0.0)) for w in tree.sow])

    def declare(name):
        dom = _load.DOMAINS.get(name[2:])
        if dom is None:
            return None
        if name not in db.sym:
            db.declare(name, "par", dom)
        return db.cols(name)

    def live(s, col):
        if (s, col + "_sv") in flags:
            return f"(v.{col} <> 0 or v.{col}_sv = 'EPS')"
        return f"v.{col} <> 0"

    def put(target, s, n, value, join, where, extra=""):
        lab = ", ".join(f"upper(v.d{i})" for i in range(n))
        db.x(f'''insert into "{target}" select {lab}, sum({value}) as x from sol."{s}" v {join}
                 where {where}{extra} group by all having x <> 0''')

    for name, (tpos, f) in EXP_LEVELS.items():
        s = tabs.get(name.replace("VAR_", "VAS_", 1))
        cols = declare("L_" + name) if s else None
        if not cols:
            continue
        n = len(cols)
        if f == "t":
            put("L_" + name, s, n, "m.p * v.level", f"join swt_ m on m.t = upper(v.d{tpos}) and m.w = upper(v.d{n})",
                live(s, "level"))
        elif f == "p":
            extra = ""
            if name == "VAR_CUMCOM":       # $RC_CUMCOM(R,COM_VAR,YEAR,LL,C)
                extra = " and in_RC_CUMCOM(upper(v.d0), upper(v.d2), upper(v.d3), upper(v.d4), upper(v.d1))"
            elif name == "VAR_CUMFLO":     # VAR_CUMFLO.L(RPC,YEAR,LL)$RPC_CUMFLO(RPC,YEAR,LL): c a commodity of p
                extra = (" and in_RPC_CUMFLO(upper(v.d0), upper(v.d1), upper(v.d2), upper(v.d3), upper(v.d4))"
                         " and in_RPC(upper(v.d0), upper(v.d1), upper(v.d2))")
            put("L_" + name, s, n, "m.p * v.level", f"join sowp_ m on m.w = upper(v.d{n})", live(s, "level"), extra)
        else:
            put("L_" + name, s, n, "m.p * v.level", f"join sumt_ m on m.t = upper(v.d{tpos})",
                f"upper(v.d{n}) = '1' and {live(s, 'level')}")
    # rptmisc.rpt 168, in the report of SOW '1' (%3 empty): VAR_UC.L('%SYSPREFIX%SOLVE_STATUS') $= %MODEL_NAME%.MODELSTAT;
    # as in the ordinary report, the level of the solution's own VAR_UC (written there by that statement)
    s = tabs.get("VAR_UC")
    if s and declare("L_VAR_UC"):
        db.x(f'''insert into "L_VAR_UC" select upper(v.d0), v.level from sol."{s}" v
                 where upper(v.d0) like '%SOLVE_STATUS' and {live(s, "level")}''')
    for name, (tpos, f) in EXP_MARGINALS.items():
        s = tabs.get(name.replace("VAR_", "VAS_", 1))
        cols = declare("M_" + name) if s else None
        if not cols:
            continue
        n = len(cols)
        if f == "s":
            put("M_" + name, s, n, "v.marginal", f"join swt_ m on m.t = upper(v.d{tpos}) and m.w = upper(v.d{n})",
                live(s, "marginal"))
        elif f == "a":
            put("M_" + name, s, n, "v.marginal", "", live(s, "marginal"))
        else:
            put("M_" + name, s, n, "v.marginal", f"join swt_ m on m.t = upper(v.d{tpos}) and m.w = upper(v.d{n})",
                f"upper(v.d{n}) = '1' and {live(s, 'marginal')}")
    for name, es, tpos, f, bd in EXP_EQ_MARGINALS:
        s = tabs.get(es)
        cols = declare("M_" + name) if s else None
        if not cols:
            continue
        n = len(cols)
        cond = f" and upper(v.d{n - 1}) {bd}" if bd else ""
        one = f" and upper(v.d{n + 1}) = '1'" if f == "1" else ""
        put("M_" + name, s, n, "v.marginal", f"join swt_ m on m.t = upper(v.d{n}) and m.w = upper(v.d{n + 1})",
            f"upper(v.d{tpos}) = upper(v.d{n}) and {live(s, 'marginal')}{one}", cond)


def _substituted_expected(db, tree):
    """DETERRED, before pextlevs.stc (rptmain.stc 111):
        $ BATINCLUDE sol_flo.red %V%_FLO .L .L GLOBAL ,SOW $SW_T(T,SOW)
    the flows the reduction substituted (sol_flo.red 34-43: those of RPC_FFUNC and of RPC_EMIS), of each SOW in the
    periods where it is distinct (SW_T), with its own commodity fractions and transformation multipliers, into
    VAS_FLO.L; pextlevs.stc then takes their expected value into VAR_FLO.L. And (rptmain.stc 112)
        $ BATINCLUDE sol_ire.rpt GLOBAL ,SOW SUM(SW_T(T,SOW),SW_TPROB(T,SOW)* )
    the flows of IRE_FLOSUM of the trade processes, their expected value:
        F_INOUTS(F_IOSET(R,V,T,P,COM,S,IO)) = SUM(SW_T(T,SOW),SW_TPROB(T,SOW)* (MX)
          SUM(RPC_IRE(R,P,C,IE),IRE_FLOSUM(R,T,P,C,S,IE,COM,IO)*(VAS_IRE.L(..,SOW)$(NOT RPC_AIRE)+(VAS_ACT.L(..,SOW)*PRC_ACTFLO)$RPC_AIRE)));
    -> ({(r,v,t,p,c,s): flow}, {(r,v,t,p,c,s,io): F_INOUTS})."""
    from . import solflo
    keep = {(y, w) for y, w in tree.sw_t}
    had_fr = "RTCS_FR" in db.sym
    fr0 = [tuple(r) for r in db.q('select * from "RTCS_FR"')] if had_fr else []
    out, inouts = {}, {}
    for w in tree.sow:
        if not any(ww == w for _y, ww in keep):
            continue
        _put_sow(db, tree, w)
        if tree.ffcs:
            db.declare("RTP_FFCSW", "par", ["R", "ALLYEAR", "P", "CG", "CG"])
            db.clear("RTP_FFCSW")
            db.load_rows("RTP_FFCSW", [(r, v, p, a, b, x) for r, v, p, a, b, ww, x in tree.ffcs if ww == w])
        if tree.sfrw:
            _rtcs_fr_sow(db, tree, w)
        for t in ("ffunc", "emis"):
            db.con.execute(f"drop table if exists {t}")
        if "PAR_FLO" in db.sym:
            db.clear("PAR_FLO")
        solflo._par_flo(db)
        if "F_INOUTS" in db.sym:
            db.clear("F_INOUTS")
        solflo._f_ioset(db)
        solflo._par_ire(db)
        if "F_INOUTS" in db.sym:
            for r, v, y, p, c, s, io, x in db.q('select * from "F_INOUTS"'):
                k = (str(y).upper(), w)
                if k in keep and x:
                    key = (r, v, y, p, c, s, io)
                    inouts[key] = inouts.get(key, 0.0) + tree.tprob.get(k, 0.0) * float(x)
        have = {r[0].lower() for r in db.con.execute(
            "select table_name from information_schema.tables where table_type = 'LOCAL TEMPORARY'").fetchall()}
        for t in ("ffunc", "emis"):
            if t not in have:
                continue
            for r, v, y, p, c, s, x in db.q(f"select r, y, y2, p, c, s, value from {t}"):
                k = (str(y).upper(), w)
                if k in keep and x:
                    key = (r, v, y, p, c, s)
                    out[key] = out.get(key, 0.0) + tree.tprob.get(k, 0.0) * float(x)
        if had_fr:
            db.clear("RTCS_FR")
            db.load_rows("RTCS_FR", fr0)
    for t in ("ffunc", "emis"):
        db.con.execute(f"drop table if exists {t}")
    if "PAR_FLO" in db.sym:
        db.clear("PAR_FLO")
    if "RTP_FFCSW" in db.sym:
        db.clear("RTP_FFCSW")                  # $IF DEFINED RTP_FFCS $KILL RTP_FFCS
    return out, inouts


def _after_sow(db, tree, w):
    """The statements of rptmain.stc and rptmisc.rpt that the ordinary report does not have."""
    # rptmisc.rpt 66:  $IF %1==S %1PAR_COMBALGM(%2RTC,S) $= EQG_COMBAL.L(RTC,S);
    db.declare("PAR_COMBALGM", "par", ["R", "ALLYEAR", "C", "S"])
    db.clear("PAR_COMBALGM")
    if "L_EQG_COMBAL" in db.sym:
        c = [f"l.{x}" for x in db.cols("L_EQG_COMBAL")]
        db.x(f'''insert into PAR_COMBALGM select {", ".join(c)}, l.value
                 from L_EQG_COMBAL l where in_RTC({", ".join(c[:3])})''')
    # rptmain.stc 89-90:
    #   SPAR_CAPBD(SOW,RTP(R,T,P),'LO')  $= S_CAP_BND(RTP,'LO','1',SOW);
    #   SPAR_CAPBD(SOW,RTP(R,T,P),'UP')$(S_CAP_BND(RTP,'UP','1',SOW)<INF) $= S_CAP_BND(RTP,'UP','1',SOW);
    rows = [(r, y, p, bd, v) for r, y, p, bd, j, ww, v in tree.s_cap_bnd
            if j == "1" and ww == w and bd in ("LO", "UP") and v != 0 and not (bd == "UP" and v >= 1e300)]
    if rows and "PAR_CAPBD" in db.sym:
        for r, y, p, bd, v in rows:
            if db.q1(f"select in_RTP('{r}', '{y}', '{p}')"):
                c = db.cols("PAR_CAPBD")
                db.x(f'''delete from PAR_CAPBD where {c[0]} = '{r}' and {c[1]} = '{y}' and {c[2]} = '{p}'
                         and {c[3]} = '{bd}' ''')
                db.load_rows("PAR_CAPBD", [(r, y, p, bd, v)])


def sow_reports(model, solution, env, wanted, ctl_env=None):
    """{ordinary name: (domain, rows with the SOW first)} of the report parameters in `wanted`, the tree, and the
    database of the last SOW (for the element texts and sets of the .vde and .vds files)."""
    from . import rptmisc, rptobj
    from timespp.controls import run_controls
    out = {n: None for n in wanted}
    db = DB()
    _load._load_model(db, model)
    tree = Tree(_model_tables(db, model, TREE_TABLES))
    # LOOP(SOW$SW_PROB(SOW), ...): each SOW on a database of its own (the report changes the model's tables);
    # with SPINES (DETERRED) one report, of SOW '1', on the expected values
    det = deterred(env)
    sen = sensis(env)
    if sen:
        # solve.stc 35: LOOP(ALLSOW$SUM(SW_T(MIYR_1,ALLSOW),1), ...): the SOWs of the first period, each its own solve
        y1 = min((y for y, _w in tree.sw_t), key=lambda y: int(y) if y.isdigit() else 0)
        sows = sorted({w for y, w in tree.sw_t if y == y1}, key=lambda w: int(w) if w.isdigit() else 0)
    else:
        sows = ["1"] if det else [w for w in tree.sow if tree.prob.get(w)]
    for k, w in enumerate(sows):
        if k:
            db = DB()
            _load._load_model(db, model)
        db.env = dict(env or {})
        db.ctl, _ = run_controls(dict(db.env))
        db.stages, db.sow_now = tree, w
        sol_w = sensis_solution(solution, w) if sen else solution
        if sen:
            _load.load_solution(db, sol_w)          # the solution of the solve of w, under the deterministic names
            # rptmisc.rpt 168, after the solve: VAR_UC.L('%SYSPREFIX%SOLVE_STATUS') $= %MODEL_NAME%.MODELSTAT;
            # (1, an optimal solve: a SENSIS run writes the solution of a solve that ended optimal)
            if "L_VAR_UC" not in db.sym:
                db.declare("L_VAR_UC", "par", _load.DOMAINS["VAR_UC"])
            if not db.q1("select count(*) from L_VAR_UC where upper(" + db.cols("L_VAR_UC")[0] + ") like '%SOLVE_STATUS'"):
                db.load_rows("L_VAR_UC", [("SOLVE_STATUS", 1.0)])
        kind = "sqlite" if sol_w.lower().endswith((".db3", ".sqlite")) else "duckdb"
        db.con.execute(f"attach '{sol_w.replace(chr(92), '/')}' as sol (type {kind}, read_only)")
        try:
            if sen:
                pass
            elif det:
                sub, inouts = _substituted_expected(db, tree)
                _put_expected(db, tree)
                if sub:
                    # pextlevs.stc: VAR_FLO.L(R,V,T,P,C,S) $= SUM(SW_T(T,W), SW_TPROB(T,W)*%VAR%_FLO.L(R,V,T,P,C,S,W)),
                    # the substituted flows as sol_flo.red set them (=: in place of any level of the solution)
                    if "L_VAR_FLO" not in db.sym:
                        db.declare("L_VAR_FLO", "par", _load.DOMAINS["VAR_FLO"])
                    c = db.cols("L_VAR_FLO")
                    db.con.execute("create or replace temp table subf_ (r varchar, v varchar, t varchar, p varchar, "
                                   "c varchar, s varchar, x double)")
                    db.con.executemany("insert into subf_ values (?, ?, ?, ?, ?, ?, ?)", [k + (x,) for k, x in sub.items()])
                    db.put("L_VAR_FLO", f'''select f.r as {c[0]}, f.v as {c[1]}, f.t as {c[2]}, f.p as {c[3]}, f.c as {c[4]},
                                                   f.s as {c[5]}, f.x as value from subf_ f''')
                if "F_INOUTS" in db.sym:
                    db.clear("F_INOUTS")
                    db.load_rows("F_INOUTS", [k + (x,) for k, x in inouts.items()])
                # OPTION CLEAR=RPC_EMIS,CLEAR=RPC_FFUNC,CLEAR=F_IOSET;  (the report takes those flows as they are:
                # sol_ire.rpt assigns F_INOUTS over the empty F_IOSET and keeps the expected values)
                for n in ("RPC_EMIS", "RPC_FFUNC", "F_IOSET"):
                    if n in db.sym:
                        db.clear(n)
                db.no_f_ioset = True
            else:
                _put_sow(db, tree, w)
            if tree.ffcs and not det:      # DETERRED: $IF DEFINED RTP_FFCS $KILL RTP_FFCS
                # sol_flo.red 14: the transformation multipliers of SOW w, *(1+RTP_FFCS(R,V,P,CG,C,SOW))
                db.declare("RTP_FFCSW", "par", ["R", "ALLYEAR", "P", "CG", "CG"])
                db.load_rows("RTP_FFCSW", [(r, v, p, a, b, x) for r, v, p, a, b, ww, x in tree.ffcs if ww == w])
            if tree.sfrw:
                _rtcs_fr_sow(db, tree, w)
            if tree.obj_sic:
                _obj_sic_sow(db, tree, w)
            tree.my_f = rptobj.my_f(db)
            _objz(db)
        finally:
            db.con.execute("detach sol")
        rptmisc.run(db)
        _after_sow(db, tree, w)
        for n in wanted:
            if n not in db.sym:
                continue
            dom = list(db.sym[n].domain)
            rows = [(w,) + tuple(r) for r in db.q(f'select * from "{n}"')]
            if out[n] is None:
                out[n] = (dom, [])
            out[n][1].extend(rows)
    return out, tree, db


def _rtcs_fr_sow(db, tree, w):
    """The commodity fractions of SOW w with S_COM_FR, as the flow reports read them (sol_flo.red, cal_red.red,
    cal_nored.red, rptmisc.rpt), recurrin.stc 48:
        $IF DEFINED S_COM_FR $MACRO RTCS_FR(R,T,C,S,TS) RTCS_FRMX(R,T,C,S,TS)+SUM(SW_T2W(SOW,T,W,T0),RCS_SSFR(R,C,S,TS,W,T0))
    RTCS_SFRW(R,T,C,S,TS,W) holds the sum over T0 for the SOW W that represents SOW w in period T (SW_TSW)."""
    rep = {y: ww for s, y, ww in tree.tsw if s == w}
    add = {}
    for r, y, c, s, ts, ww, x in tree.sfrw:
        if rep.get(y) == ww:
            add[(r, y, c, s, ts)] = add.get((r, y, c, s, ts), 0.0) + x
    if not add:
        return
    if "RTCS_FR" not in db.sym:
        db.declare("RTCS_FR", "par", ["R", "ALLYEAR", "C", "S", "S"])
    rows = {tuple(r[:-1]): r[-1] for r in db.q('select * from "RTCS_FR"')}
    label = {tuple(str(v).upper() for v in k): k for k in rows}
    for k, x in add.items():
        k = label.get(k, k)
        v = rows.get(k, 0.0) + x
        if v:
            rows[k] = v
        else:
            rows.pop(k, None)              # a GAMS parameter of value 0 holds no record
    db.clear("RTCS_FR")
    db.load_rows("RTCS_FR", [k + (v,) for k, v in rows.items()])


def _obj_sic_sow(db, tree, w):
    """The investment cost multipliers of SOW w with S_NCAP_COST, as the cost reports read them (rpt_obj.rpt 18,
    cost_ann.rpt 39, rpt_objc.rpt 30):
        PASTSUM(NCAP_YES(R,T,P)) = SUM(SW_TSW(SOW,T,WW),OBJ_SIC(R,T,P,WW));
    held as OBJ_SICW(R,T,P), for every (R,T,P) of OBJ_SIC (the reports read it only where they need it)."""
    rep = {y: ww for s, y, ww in tree.tsw if s == w}
    acc = {}
    for r, y, p, ww, x in tree.obj_sic:
        if rep.get(y) == ww:
            acc[(r, y, p)] = acc.get((r, y, p), 0.0) + x
    db.declare("OBJ_SICW", "par", ["R", "ALLYEAR", "P"])
    db.clear("OBJ_SICW")
    db.load_rows("OBJ_SICW", [k + (x,) for k, x in acc.items() if x])


def _objz(db):
    """ObjZ.l of the solution (times2veda_stc.vdd: ObjZ ObjZ.l)."""
    tabs = _sol_tables(db)
    if "OBJZ" in tabs:
        v = db.con.execute(f'select level from sol."{tabs["OBJZ"]}"').fetchone()
        db.s["L_OBJZ"] = float(v[0]) if v and v[0] is not None else 0.0


def not_ported(tree, env):
    """What rptmain.stc does on this run that the port does not: lines for the report."""
    out = []
    if getattr(tree, "my_f", 0):
        out.append("RPT_OPT('OBJ','1') with STAGES: rpt_obj.rpt 18 sets MY_F=EPS$MY_F, which the port does not "
                   "follow; the costs by process are reported as without STAGES")
    spines = str((env or {}).get("SPINES", "")).strip("'\" ").upper()
    if spines == "YES" and not deterred(env):
        out.append("SPINES YES without SOLVEDA 1: the reports of each SOW (rptmain.stc 22-104 with SPINES) are not "
                   "compared with TIMES")
    return out


def report_db(model, solution, env, entries):
    """A database with the stochastic report parameters times2veda_stc.vdd reads: S<name>(SOW,...), REG_WOBJ, ObjZ.l;
    and the database of the last SOW."""
    wanted = sorted({ordinary_name(g) for _a, g, ix in entries if ix and ix[0] == "w"})
    got, tree, last = sow_reports(model, solution, env, wanted)
    out = DB()
    for n, val in got.items():
        if val is None:
            continue
        dom, rows = val
        sname = "CM_S" + n[3:] if n.startswith("CM_") else "S" + n
        out.declare(sname, "par", ["ALLSOW"] + dom)
        out.load_rows(sname, rows)
    # rptmain.stc 103:  REG_WOBJ(R,ITEM,CUR) $= SUM(W$SREG_WOBJ(W,R,ITEM,CUR),SW_PROB(W)*SREG_WOBJ(W,R,ITEM,CUR));
    # (not with SENSIS: rptmain.mod 18, $IFI %SENSIS% == YES $GOTO FINISH)
    if "SREG_WOBJ" in out.sym and not sensis(env):
        out.declare("REG_WOBJ", "par", list(out.sym["SREG_WOBJ"].domain[1:]))
        acc, order = {}, []
        c = out.cols("SREG_WOBJ")
        for row in out.q(f'select {", ".join(c)}, value from SREG_WOBJ'):
            key = tuple(row[1:-1])
            if key not in acc:
                order.append(key)
                acc[key] = 0.0
            acc[key] += tree.prob.get(row[0], 0.0) * float(row[-1])
        out.load_rows("REG_WOBJ", [k + (acc[k],) for k in order])
    out.s["L_OBJZ"] = last.s.get("L_OBJZ", 0.0)
    out.casing = getattr(last, "casing", {})
    out.not_ported = not_ported(tree, env)
    return out, last


def com_tax(db, pulse):
    """eqobjvar.rpt 15 and 39-40, the uncertain commodity tax of the SOW in the tax column of PAR_COMC (a run with
    STAGES; the report of SOW `db.sow_now`):

      $IFI %STAGES%==YES Z=SUM(W(SOW),SW_PROB(W));
      $IFI %STAGES%==YES
        %1_COMC(%3RTC(R,T,C),CUR)$RDCUR(R,CUR) $= SUM((RTCS_VARC(RTC,S),COM_VAR,SW_TSW(SOW,T,W))$S_COM_TAX(RTC,S,COM_VAR,CUR,'1',W),
          (%5(%TMP%S_COM_TAX(R,%4,C,S,COM_VAR,CUR,'1',W))*(VAR_COMPRD.L(RTC,S)$DIAG('PRD',COM_VAR)+VAR_COMNET.L(RTC,S)$DIAG('NET',COM_VAR))
           +%1_COMC(J,RTC,CUR)*G_YRFR(R,S))*SW_PROB(W)/Z);

    pulse False: the call of cost_ann.rpt (%3 J('2'), %4 T, no %5): the tax at the period.
    pulse True: the call of rpt_obj.rpt (%4 Y_EOH, %5 SUM, %TMP% Y_EOH$OBJ_LINT(R,T,Y_EOH,CUR),OBJ_LINT(R,T,Y_EOH,CUR)*):
    the tax of the years of the period, weighted by OBJ_LINT."""
    tree, w = db.stages, db.sow_now
    rows = [r for r in tree.s_com_tax if r[6] == "1"]
    if not rows or "RDCUR" not in db.sym or "PAR_COMC" not in db.sym:
        return
    z = tree.prob.get(w, 0.0)
    if not z:
        return
    db.con.execute("create or replace temp table s_com_tax_ (r varchar, y varchar, c varchar, s varchar, cv varchar, "
                   "cur varchar, j varchar, w varchar, value double)")
    db.con.executemany("insert into s_com_tax_ values (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    db.con.execute("create or replace temp table sw_this_ (y varchar, w varchar, p double)")
    rep = [(y, ww, tree.prob.get(ww, 0.0)) for s, y, ww in tree.tsw if s == w]
    if rep:
        db.con.executemany("insert into sw_this_ values (?, ?, ?)", rep)
    lvl = []
    for name, cv in (("L_VAR_COMPRD", "PRD"), ("L_VAR_COMNET", "NET")):
        if name in db.sym:
            r, y, c, s = db.cols(name)
            lvl.append(f"select {r} as r, {y} as y, {c} as c, {s} as s, '{cv}' as cv, value from \"{name}\"")
    lvl_sql = " union all ".join(lvl) or "select null as r, null as y, null as c, null as s, null as cv, 0.0 as value"
    pj, pr, py, pc, pcur = db.cols("PAR_COMC")
    vr, vy, vc, vs = db.cols("RTCS_VARC")
    gr, gs = db.cols("G_YRFR")
    if pulse:
        lr, ly, ly2, lcur = db.cols("OBJ_LINT")
        tax = (f"(select sum(l.value * y2.value) from OBJ_LINT l join s_com_tax_ y2 on y2.y = l.{ly2} "
               f"where l.{lr} = x.r and l.{ly} = x.y and l.{lcur} = x.cur and y2.r = x.r and y2.c = x.c and y2.s = x.s "
               f"and y2.cv = x.cv and y2.cur = x.cur and y2.j = '1' and y2.w = x.w and l.value <> 0)")
    else:
        tax = "x.value"
    db.x(f"""create or replace temp table com_tax_sw_ as
             select x.r, x.y, x.c, x.cur,
                    sum((coalesce({tax}, 0) * coalesce(lv.value, 0)
                         + v_PAR_COMC('2', x.r, x.y, x.c, x.cur) * v_G_YRFR(x.r, x.s)) * m.p / {z!r}) as value
             from s_com_tax_ x
             join sw_this_ m on m.y = x.y and m.w = x.w
             join RTCS_VARC v on v.{vr} = x.r and v.{vy} = x.y and v.{vc} = x.c and v.{vs} = x.s
             left join ({lvl_sql}) lv on lv.r = x.r and lv.y = x.y and lv.c = x.c and lv.s = x.s and lv.cv = x.cv
             where x.j = '1' and x.value <> 0 and in_RDCUR(x.r, x.cur) and in_RTC(x.r, x.y, x.c)
             group by x.r, x.y, x.c, x.cur""")
    db.put("PAR_COMC", "select '2' as j, r, y, c, cur, value from com_tax_sw_", zero="skip")
