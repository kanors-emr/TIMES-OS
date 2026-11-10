# SPDX-License-Identifier: GPL-3.0-or-later
"""The climate module, CLI ($SET CLI YES): the preprocessing.

    init(db)        the sets declared with data in ppm_ext.cli (there from the start of the run)
    ppm_ext(db)     ppm_ext.cli  (maindrv.mod 58, main_ext.mod ppm_ext: after ppm_ext.mlf, before ppm_ext.dsc and .vda)
    coef_ext(db)    coef_ext.cli (maindrv.mod 73, main_ext.mod coef_ext: before coef_ext.vda and coef_ext.abs)
    uc_attr(db)     init_ext.vda 129: the user constraints with climate terms (UC_CLI)

The declarations and defaults are those of initmty.cli (load.py reads them). EXTEND lists CLI after MLF and before DSC,
VDA and ABS (initmty.mod 461-470). The climate module adds the variables VAR_CLITOT and VAR_CLIBOX and the equations
EQ_CLITOT, EQ_CLICONC, EQ_CLITEMP, EQ_CLIBEOH and EQ_CLIMAX (times_eq/src/equations/cli.jl); its one change to the
core equations is the net production VAR_COMNET of the emission commodities it maps (CM_GHGMAP, CM_CO2GTC), whose
balance becomes an equality.

The parameters are small (items by years), so the statements are run here on Python dictionaries, in the order of
the GAMS code. EPS is carried as a tiny number (EPS + x = x) and stored as an EPS row.
"""
from __future__ import annotations
import math
from ..engine import DB
from ..controls import macro_run, unsupported
from .common import require_empty
from . import stochastic

EPS = 1e-300
BOXES = ("ATM", "UP", "LO", "N")                  # CM_BOX(CM_Q) / ATM, UP, LO, N /   (initmty.cli 56)
LIM = ("LO", "FX", "UP", "N")                     # SET LIM / LO, FX, UP, N /         (initsys.mod 70)


def on(db: DB):
    """initmty.mod 466: $IFI '%CLI%' == YES $SETGLOBAL EXTEND '%EXTEND% CLI'"""
    return bool(db.ctl.get("CLI"))


# ---------------------------------------------------------------------------------------------------------------------
# GAMS on dictionaries

def _n(v):
    """the number of a value (EPS is 0 in arithmetic comparisons)"""
    return 0.0 if v is None or abs(v) < 1e-200 else v


def _get(db: DB, name):
    """parameter -> {key tuple: value}, an EPS row as EPS"""
    return {tuple(r[:-1]): (EPS if r[-1] == 0 else r[-1]) for r in db.q(f'select * from "{name}"')}


def _put(db: DB, name, d):
    """{key: value} -> the parameter (replaced): 0 is no row, EPS an EPS row"""
    db.clear(name)
    db.load_rows(name, [k + (0.0 if abs(v) < 1e-200 else v,) for k, v in d.items() if v != 0])


def _sget(db: DB, name):
    return [tuple(r) for r in db.q(f'select * from "{name}"')]


def _sput(db: DB, name, rows):
    db.clear(name)
    seen, out = set(), []
    for r in rows:
        r = r if isinstance(r, tuple) else (r,)
        if r not in seen:
            seen.add(r)
            out.append(r)
    db.load_rows(name, out)


def _years(db: DB):
    """ALLYEAR in its order (BOTIME..EOTIME, then '0'), its positions, and YEARVAL"""
    ys = [y for (y,) in db.q("select y from ALLYEAR order by (y = '0'), yv(y)")]
    return ys, {y: i for i, y in enumerate(ys)}


def _yv(y):
    return int(y) if y != "0" else 0


def filparam(d, ypos, src, tgt, key_ok=lambda k: True, default=None, back_ok=None):
    """filparam.gms: dense inter-/extrapolation of d (a dict, the year at position ypos of its key) from the years `src`
    to the years `tgt` (both in ALLYEAR order), for the series whose key passes key_ok (the control sets %2, %3);
    back_ok(key, year): %7, the qualifier of the backward extrapolation (None: empty); %8 empty; default: %9."""
    src = [y for y in src if y != "0"]
    inset = set(src)
    keys = {}
    for k in d:
        if k[ypos] in inset and key_ok(k[:ypos] + k[ypos + 1:]):
            keys.setdefault(k[:ypos] + k[ypos + 1:], None)
    mk = lambda k, y: k[:ypos] + (y,) + k[ypos:]
    for k in keys:
        # --- F=0; Z=INF; MY_FYEAR=9999;  DFUNC = ROUND(%SRC%('0'));  IF(NOT DFUNC, DFUNC = %9);
        F, Z, myfy, first, last = 0.0, math.inf, 9999, 0.0, 0.0
        df = _round(_n(d.get(mk(k, "0"), 0.0)))
        if not df and default is not None:
            df = default
        if df < 0:
            continue
        arr = [(y, d[mk(k, y)]) for y in src if d.get(mk(k, y), 0) != 0]
        for y, myf in arr:                                   # LOOP(%5$MY_ARRAY(%5), ...)
            Z = _yv(y)
            if Z > myfy + 1:                                 # linear interpolation
                for t in tgt:
                    if Z > _yv(t) > myfy:
                        v = last + (myf - last) / (Z - myfy) * (_yv(t) - myfy)
                        if v == 0:
                            d.pop(mk(k, t), None)
                        else:
                            d[mk(k, t)] = v
            elif Z < myfy:
                F, first = Z, myf
            last, myfy = myf, Z
        if df > 1:
            df = df % 10
            if df == 2:
                first = last = EPS
            elif df == 4:
                Z = math.inf
            elif df == 5:
                F = 0
        if df != 1:
            for t in tgt:                                    # %1(..%6..) $= FIRST_VAL$(%7(YEARVAL(%6) LT F)) + LAST_VAL$(.. GT Z)
                back = _yv(t) < F and (back_ok is None or back_ok(k, t))
                v = (first if back else 0.0) + (last if _yv(t) > Z else 0.0)
                if v != 0:
                    d[mk(k, t)] = v
    return d


def _round(x):
    return float(math.floor(abs(x) + 0.5) * (1 if x >= 0 else -1))


# ---------------------------------------------------------------------------------------------------------------------

def init(db: DB):
    """ppm_ext.cli 8-10 (declarations, compiled before the run):
         SET CM_USUBS(CM_ITEM);  SET CM_COUPMAP(CM_ITEM,CM_ITEM,CM_Q);
         SET CM_REBOX(CM_Q,CM_Q) / CM-ATM.ATM, CM-UP.UP, CM-LO.LO /;"""
    if not on(db):
        return
    db.declare("CM_USUBS", "set", ["CM_ITEM"])
    db.declare("CM_COUPMAP", "set", ["CM_ITEM", "CM_ITEM", "CM_Q"])
    db.declare("CM_REBOX", "set", ["CM_Q", "CM_Q"])
    _sput(db, "CM_REBOX", [("CM-ATM", "ATM"), ("CM-UP", "UP"), ("CM-LO", "LO")])
    refuse(db)


def refuse(db: DB):
    """What the port of the climate module does not take: named, so that no run solves without it."""
    if macro_run(db.env):
        unsupported(db, "the climate module (CLI) with TIMES-MACRO (both declare CM_LED; forcupd.cli of MSA)")
    for k in ("TIMESTEP", "FIXBOH"):
        if str(db.env.get(k, "")).strip("'\" "):
            unsupported(db, f"the climate module (CLI) in a run with {k} (spoint.mod 33, clearsol.stp 26)")
    if str(db.env.get("SPINES", "")).strip("'\" ").upper() == "YES" or str(db.env.get("LPOINT", "")).strip("'\" "):
        unsupported(db, "the climate module (CLI) with a starting point of an earlier run (spoint.mod 33)")
    require_empty(db, ["CM_COUPLE"], "coupled concentrations of the climate module (ppm_ext.cli 19-41, coef_ext.cli 42-51)")
    require_empty(db, ["CM_DECAY"], "user-defined decays of the climate module (ppm_ext.cli 34, coef_ext.cli 34-41)")
    require_empty(db, ["CM_PHI"], "a user-defined transport matrix of the climate module (coef_ext.cli 54-66)")


def ppm_ext(db: DB):
    """ppm_ext.cli 12-71"""
    if not on(db):
        return
    ys, ypos = _years(db)
    REG = {r for (r,) in db.q("select r from REG")}
    CG = [c for (c,) in db.q("select cg from COM_GRP")]
    COM = {c for (c,) in db.q("select cg from COM")}
    RC = set(_sget(db, "RC"))
    ppm = _get(db, "CM_PPM")
    ppm = {k[0]: v for k, v in ppm.items()}
    hists = [h for (h,) in _sget(db, "CM_HISTS")]
    emis = [e for (e,) in _sget(db, "CM_EMIS")]
    # --- CM_GHGMAP(R,COM,C)$(NOT CM_GHGMAP(R,COM,C)) $= IRE_CCVT(R,COM,R,C);
    ghg = _get(db, "CM_GHGMAP")
    for (r, c1, r2, c2), v in _get(db, "IRE_CCVT").items():
        if r == r2 and r in REG and c1 in COM and c2 in COM and (r, c1, c2) not in ghg and v != 0:
            ghg[(r, c1, c2)] = v
    _put(db, "CM_GHGMAP", ghg)
    # --- CM_USUBS(CM_ITEM)$SUM(RC(R,COM)$CM_GHGMAP(R,COM,CM_ITEM),1) = CM_PPM(CM_ITEM);
    mapped = {i for (r, c, i) in ghg if (r, c) in RC}
    usubs = [i for i in CG if i in mapped and ppm.get(i, 0) != 0]
    # --- OPTION CLEAR=UNCD1; UNCD1(CM_USUBS) = CM_HISTS(CM_USUBS);  CM_HISTS(CM_USUBS) = YES;  CM_EMIS(CM_USUBS) = YES;
    hists += [u for u in usubs if u not in hists]
    emis += [u for u in usubs if u not in emis]
    # --- Prepare coupled agents: CM_COUPLE (refused when given) is empty, and so are UNCD7, CM_COUPMAP and then CM_USUBS:
    #     CM_COUPLE(CG,LL,CM_ITEM,'ATM') = 0;  UNCD7(..)$CM_COUPLE(..) = YES;  LOOP(UNCD7(..), ..);
    #     OPTION CM_COUPMAP <= CM_COUPLE;  CM_COUPLE(..,'N') = 0;  CM_COUPLE(..)$(NOT CM_COUPMAP(..)) = 0;
    #     OPTION CM_USUBS < CM_COUPMAP;  LOOP(CM_USUBS(CM_ITEM), ..);
    #     $ BATINCLUDE fillparm CM_COUPLE CG1 'CG,CM_Q' ",'0','0','0','0'" T YES '>=0'
    db.clear("CM_COUPMAP")
    # --- Statistics mappings
    #     CM_STATS(CM_HISTS,LL,'ATM') $= CM_STATS(CM_HISTS,LL,'N');
    #     CM_STATS('FORCING',LL,CM_BOX) $= CM_STATS('DELTA',LL,CM_BOX);
    stats = _get(db, "CM_STATS")
    hs = set(hists)
    for (h, y, q), v in list(stats.items()):
        if q == "N" and h in hs and v != 0:
            stats[(h, y, "ATM")] = v
    for (h, y, q), v in list(stats.items()):
        if h == "DELTA" and q in BOXES and v != 0:
            stats[("FORCING", y, q)] = v
    _put(db, "CM_STATS", stats)
    #     CM_STAT0(CM_VAR,'LIFE')$((CM_DECAY(CM_VAR,'UP')>0)$CM_DECAY(CM_VAR,'UP'))=1/CM_DECAY(CM_VAR,'UP');
    #     (CM_DECAY is refused when given: empty)
    # --- Add missing forcings if functions defined
    #     OPTION CLEAR=UNCD1, CM_USUBS < CM_LINFOR;  UNCD1(CM_USUBS) = YES;
    uncd1 = {i for (y, i, l) in _get(db, "CM_LINFOR")}
    #     OPTION CM_USUBS < CM_FORCMAP;   (the first index)
    fmap = _sget(db, "CM_FORCMAP")
    us = {a for a, b in fmap}
    #     CM_USUBS(CM_EMIS) = NOT CM_USUBS(CM_EMIS);  CM_USUBS(CM_USUBS) = UNCD1(CM_USUBS);  CM_USUBS('CO2-GTC') = NO;
    for e in emis:
        us ^= {e}
    us = {u for u in us if u in uncd1 and u != "CO2-GTC"}
    #     CM_FORCMAP(CM_USUBS,CM_USUBS) = YES;  CM_OFOR(CM_USUBS) = YES;
    order = {c: i for i, c in enumerate(CG)}
    us = sorted(us, key=lambda c: order.get(c, 1 << 30))
    fmap += [(u, u) for u in us]
    _sput(db, "CM_FORCMAP", fmap)
    _sput(db, "CM_OFOR", _sget(db, "CM_OFOR") + [(u,) for u in us])
    _sput(db, "CM_USUBS", us)
    _sput(db, "CM_HISTS", hists)
    _sput(db, "CM_EMIS", emis)
    # --- If calibration values are not provided by user, use the defaults:
    #     CM_CONST(CM_PREDEF) = 0;  LOOP((LL,CM_HISTS)$CM_HISTORY(LL,CM_HISTS),CM_CONST(CM_HISTS) = EPS);
    const = {k[0]: v for k, v in _get(db, "CM_CONST").items()}
    predef = {p for (p,) in _sget(db, "CM_PREDEF")}
    for p in predef:
        const.pop(p, None)
    hist = _get(db, "CM_HISTORY")
    for (y, h), v in hist.items():
        if h in hs and v != 0:
            const[h] = EPS
    deflt = _get(db, "CM_DEFAULT")
    hp = [h for h in hists if h in predef]
    if _n(const.get("CALIBSET", 0)) > 0:
        # --- LOOP(YEAR('%EOTIME%'),
        #       CM_CONST(ITEM)$((NOT CM_CONST(ITEM)+1$CM_PREDEF(ITEM))$CM_DEFAULT(YEAR,ITEM)) = CM_DEFAULT(YEAR,ITEM);
        #       CM_HISTORY(LL(MIYR_1),CM_HISTS(CG(CM_PREDEF)))$(NOT CM_CONST(CM_HISTS)) $= CM_DEFAULT(YEAR,CM_HISTS));
        y = str(db.ctl["EOTIME"])
        for (yy, i), v in deflt.items():
            if yy == y and not (const.get(i, 0) or i in predef) and v != 0:
                const[i] = v
        m1 = db.q1("select y from MIYR_1")
        for h in hp:
            if not const.get(h) and deflt.get((y, h), 0) != 0:
                hist[(m1, h)] = deflt[(y, h)]
    else:
        # --- CM_CONST(ITEM)$((NOT CM_CONST(ITEM)+1$CM_PREDEF(ITEM))$CM_DEFAULT('0',ITEM)) = CM_DEFAULT('0',ITEM);
        #     CM_HISTORY(LL(YEAR-2),CM_HISTS(CG(CM_PREDEF)))$(NOT CM_CONST(CM_HISTS)) $= CM_DEFAULT(LL,CM_HISTS));
        #     (LL: every year but the last two of ALLYEAR, EOTIME and '0')
        for (yy, i), v in deflt.items():
            if yy == "0" and not (const.get(i, 0) or i in predef) and v != 0:
                const[i] = v
        ok = set(ys[:-2])
        for (yy, h), v in deflt.items():
            if yy in ok and h in hp and not const.get(h) and v != 0:
                hist[(yy, h)] = v
    _put(db, "CM_HISTORY", hist)
    # --- AR6 defaults for Gamma, Lambda & CS
    #     IF(CM_CONST('GAMMA')=0, CM_CONST('GAMMA') = 5.5*LOG(2));
    #     IF(CM_CONST('CS')=0, IF(CM_CONST('LAMBDA')=0, CM_CONST('LAMBDA') = CM_CONST('GAMMA')/3);
    #        CM_CONST('CS') = CM_CONST('GAMMA')/CM_CONST('LAMBDA'));
    #     CM_CONST('LAMBDA') = CM_CONST('GAMMA')/CM_CONST('CS');
    if _n(const.get("GAMMA")) == 0:
        const["GAMMA"] = 5.5 * math.log(2)
    if _n(const.get("CS")) == 0:
        if _n(const.get("LAMBDA")) == 0:
            const["LAMBDA"] = _n(const["GAMMA"]) / 3
        const["CS"] = _n(const["GAMMA"]) / _n(const["LAMBDA"])
    const["LAMBDA"] = _n(const["GAMMA"]) / _n(const["CS"])
    # --- E('0')=0; IF(CM_CONST('EXT-EOH') EQ 0, CM_CONST('EXT-EOH')=SMAX(LL$E(LL),E(LL)));
    db.zap("E", "y = '0'")
    if _n(const.get("EXT-EOH")) == 0:
        const["EXT-EOH"] = db.q1("select max(value) from E") or 0.0
    _put(db, "CM_CONST", {(k,): v for k, v in const.items()})


def _matmul(a, m):
    """A(BUCK,BOX) = SUM(CM_Q$CM_BOX(CM_Q), A(BUCK,CM_Q)*M(CM_Q,BOX)), the matrices {(row, column): value} over the boxes"""
    out = {}
    for i in BOXES:
        for k in BOXES:
            v = sum(a.get((i, j), 0.0) * m.get((j, k), 0.0) for j in BOXES)
            if v != 0:
                out[(i, k)] = v
    return out


def coef_ext(db: DB):
    """coef_ext.cli 13-219"""
    if not on(db):
        return
    s, env = db.s, db.env
    ys, ypos = _years(db)
    T = [y for (y,) in db.q("select y from MILESTONYR order by yv(y)")]
    m1 = T[0]
    B = {y: v for y, v in db.q("select y, value from B")}
    M = {y: v for y, v in db.q("select y, value from M")}
    LEAD = {y: v for y, v in db.q("select y, value from LEAD")}
    const = {k[0]: v for k, v in _get(db, "CM_CONST").items()}
    C = lambda k: _n(const.get(k, 0.0))
    ppm = {k[0]: v for k, v in _get(db, "CM_PPM").items()}
    hists = [h for (h,) in _sget(db, "CM_HISTS")]
    hs = set(hists)
    emis = [e for (e,) in _sget(db, "CM_EMIS")]
    boxmap = _sget(db, "CM_BOXMAP")
    atmap = _sget(db, "CM_ATMAP")
    # --- CM_CALIB=1;  $IFI %CM_CALIB%==B CM_CALIB = SUM(MIYR_1(T),M(T)-B(T))+1;  $IFI %CM_CALIB%==M CM_CALIB = EPS;
    calib = 1.0
    sw = str(env.get("CM_CALIB", "")).strip("'\" ").upper()
    if sw == "B":
        calib = M[m1] - B[m1] + 1
    elif sw == "M":
        calib = EPS
    s["CM_CALIB"] = calib

    def lag(y, k):
        i = ypos[y] - int(_n(k))
        return ys[i] if 0 <= i < len(ys) else None
    # --- Inter-/extrapolate calibration values
    #     OPTION CLEAR=FIL; LOOP(MIYR_1(LL),FIL(LL-CM_CALIB) = YES);
    #     $BATINCLUDE filparam CM_HISTORY '' 'CM_HISTS' ",'','','','','',''" LL FIL ''
    y0 = lag(m1, calib)
    fil = [y0] if y0 else []
    hist = filparam(_get(db, "CM_HISTORY"), 0, ys, fil, lambda k: k[0] in hs)
    _put(db, "CM_HISTORY", hist)
    # --- CM_STAT0(CM_HISTS,CM_BOX) = 0;
    stat0 = _get(db, "CM_STAT0")
    for k in [k for k in stat0 if k[0] in hs and k[1] in BOXES]:
        del stat0[k]
    # --- CM_USUBS(CM_HISTS)=CM_EMIS(CM_HISTS)$(NOT SAMEAS(CM_HISTS,'CO2-GTC'));
    usubs = [u for (u,) in _sget(db, "CM_USUBS") if u not in hs] + [h for h in hists if h in emis and h != "CO2-GTC"]
    us = set(usubs)
    _sput(db, "CM_USUBS", usubs)
    # --- LOOP((CM_HISTS,LL,CM_BOX)$CM_STATS(CM_HISTS,LL,CM_BOX),CM_STAT0(CM_HISTS,CM_BOX) = EPS);
    stats = _get(db, "CM_STATS")
    for (h, y, q), v in stats.items():
        if h in hs and q in BOXES and v != 0:
            stat0[(h, q)] = EPS
    # --- LOOP(CM_BOXMAP(CM_HISTS,CM_VAR,CM_BOX(CM_Q))$(NOT CM_STAT0(CM_HISTS,CM_Q)),
    #       CM_STATS(CM_HISTS,LL,CM_Q)$CM_HISTORY(LL,CM_VAR) = CM_HISTORY(LL,CM_VAR)*POWER(CM_PPM(CM_HISTS),-1$CM_USUBS(CM_HISTS)));
    for h, v, q in boxmap:
        if h in hs and v in hs and not stat0.get((h, q)):
            for (y, i), x in hist.items():
                if i == v and x != 0:
                    stats[(h, y, q)] = x / ppm[h] if h in us else x
    # --- $BATINCLUDE filparam CM_STATS 'CM_HISTS,' CM_BOX ",'','','','',''" LL FIL
    stats = filparam(stats, 1, ys, fil, lambda k: k[0] in hs and k[1] in BOXES)
    _put(db, "CM_STATS", stats)
    # --- Pick up the history values
    #     LOOP((MIYR_1(LL),YEAR(LL-CM_CALIB)),
    #       CM_STAT0(CM_HISTS,CM_BOX) = CM_STATS(CM_HISTS,YEAR,CM_BOX)*POWER(CM_PPM(CM_HISTS),1$CM_USUBS(CM_HISTS)));
    #     CM_STAT0(CM_HISTS,'N') = 0;
    if y0:
        for h in hists:
            for q in BOXES:
                x = stats.get((h, y0, q), 0.0)
                x = x * ppm.get(h, 0.0) if h in us else x
                if x != 0:
                    stat0[(h, q)] = x
                else:
                    stat0.pop((h, q), None)
    for h in hists:
        stat0.pop((h, "N"), None)
    # --- Preprocess concentration decays   (CM_DECAY is refused when given: these are its only rows)
    #     CM_DECAY('CH4-MT','ATM') = CM_CONST('PHI-CH4');  CM_DECAY('N2O-MT','ATM') = CM_CONST('PHI-N2O');
    #     CM_DECAY(CM_EMIS,'ATM') $= CM_DECAY(CM_EMIS,'N');  CM_DECAY(CM_EMIS,CM_Q(L)) = 0;
    #     CM_DECAY(CM_EMIS,CM_BOX)$CM_STAT0(CM_EMIS,CM_BOX) = CM_DECAY(CM_EMIS,CM_BOX)+EPS;
    decay = {}
    for i, k in (("CH4-MT", "PHI-CH4"), ("N2O-MT", "PHI-N2O")):
        if const.get(k, 0) != 0:
            decay[(i, "ATM")] = const[k]
    for e in emis:
        if decay.get((e, "N"), 0) != 0:
            decay[(e, "ATM")] = decay[(e, "N")]
        for l in LIM:
            decay.pop((e, l), None)
        for q in BOXES:
            if stat0.get((e, q), 0) != 0:
                decay[(e, q)] = decay.get((e, q), 0.0) + EPS
    #     CM_ATMAP(CM_EMIS,CM_EMIS)$(NOT SUM(CM_ATMAP(CM_EMIS,CM_VAR),1)) = YES;
    for e in emis:
        if not any(a == e and b in hs for a, b in atmap):
            atmap.append((e, e))
    #     LOOP(CM_EMIS$(NOT SUM(CM_BOXMAP(CM_EMIS,CM_VAR,CM_BOX),1)),
    #       CM_BOXMAP(CM_ATMAP(CM_EMIS,CM_VAR),CM_BOX)$CM_DECAY(CM_EMIS,CM_BOX)=YES);
    for e in emis:
        if not any(a == e and b in hs for a, b, q in boxmap):
            boxmap += [(e, v, q) for a, v in atmap if a == e and v in hs for q in BOXES if decay.get((e, q), 0) != 0]
    # --- Coupled concentrations, reference concentration, reference life (coef_ext.cli 43-51): CM_COUPMAP and
    #     CM_COUPLE are empty (CM_COUPLE is refused when given)
    # --- Set up the 3x3 PHI matrix for emissions   (CM_PHI is refused when given: empty)
    #     IF(NOT SUM((CM_BOX,CM_BUCK),CM_PHI('CO2-GTC',CM_BOX,CM_BUCK)),
    #       CM_PHI('CO2-GTC','ATM','UP') = CM_CONST('PHI-UP-AT');  CM_PHI('CO2-GTC','UP','ATM') = CM_CONST('PHI-AT-UP');
    #       CM_PHI('CO2-GTC','UP','LO') = CM_CONST('PHI-LO-UP');   CM_PHI('CO2-GTC','LO','UP') = CM_CONST('PHI-UP-LO'));
    phi = {}
    for a, b, k in (("ATM", "UP", "PHI-UP-AT"), ("UP", "ATM", "PHI-AT-UP"), ("UP", "LO", "PHI-LO-UP"), ("LO", "UP", "PHI-UP-LO")):
        if const.get(k, 0) != 0:
            phi[("CO2-GTC", a, b)] = const[k]
    # --- Default first-order decay models for CH4 and N2O
    #     LOOP(CM_USUBS(CM_EMIS), IF(NOT SUM((CM_BOX,CM_BUCK),CM_PHI(CM_EMIS,CM_BOX,CM_BUCK)),
    #       CM_PHI(CM_EMIS,CM_BOX,CM_BOX)$CM_DECAY(CM_EMIS,CM_BOX) = 1-CM_DECAY(CM_EMIS,CM_BOX)+EPS;
    #       CM_PHI(CM_EMIS,'UP',CM_EMIS) = EPS$CM_STAT0(CM_EMIS,'UP')));
    for e in usubs:
        if e not in emis or any(phi.get((e, a, b), 0) != 0 for a in BOXES for b in BOXES):
            continue
        for q in BOXES:
            if decay.get((e, q), 0) != 0:
                phi[(e, q, q)] = 1 - _n(decay[(e, q)]) + EPS
        if stat0.get((e, "UP"), 0) != 0:
            phi[(e, "UP", e)] = EPS
        else:
            phi.pop((e, "UP", e), None)
    # --- Set emission kinds and FORCING to CM_KIND when active
    #     CM_KIND(CM_VAR)$(SUM((CM_BOX,CM_BUCK)$CM_PHI(CM_VAR,CM_BOX,CM_BUCK),1)$CM_EMIS(CM_VAR)) = YES;
    kind = [k for (k,) in _sget(db, "CM_KIND")]
    for v in hists:
        if v in emis and any(phi.get((v, a, b), 0) != 0 for a in BOXES for b in BOXES) and v not in kind:
            kind.append(v)
    #     CM_EMIS(CM_VAR) = CM_KIND(CM_VAR)$CM_PPM(CM_VAR);
    emis = [e for e in emis if e not in hs] + [v for v in hists if v in kind and ppm.get(v, 0) != 0]
    es = set(emis)
    #     CM_KIND('FORCING') = YES$(SUM(LL$CM_MAXC(LL,'DELTA-ATM'),1)+(CARD(CM_EMIS) GT 1));
    #     IF(CARD(UC_CLI),CM_KIND('FORCING') = YES);
    maxc = _get(db, "CM_MAXC")
    forcing = any(i == "DELTA-ATM" and v != 0 for (y, i), v in maxc.items()) or len(emis) > 1 or db.card("UC_CLI") > 0
    #     $IFI %STAGES%==YES CM_KIND('FORCING')$SUM((LL,J,W)$S_CM_MAXC(LL,'DELTA-ATM',J,W),1) = YES;
    st = stochastic.on(db)
    smaxc = _get(db, "S_CM_MAXC") if st else {}
    forcing = forcing or any(i == "DELTA-ATM" and v != 0 for (y, i, j, w), v in smaxc.items())
    kind =[k for k in kind if k != "FORCING"] + (["FORCING"] if forcing else [])
    #     CM_TKIND(CM_KIND) = YES;  LOOP(CM_FORCMAP(CM_VAR,CM_HISTS)$SUM(LL$CM_MAXC(LL,CM_VAR),1),CM_TKIND(CM_VAR)=YES);
    fmap = _sget(db, "CM_FORCMAP")
    tkind = [k for (k,) in _sget(db, "CM_TKIND")]
    tkind += [k for k in kind if k not in tkind]
    withmax = {i for (y, i), v in maxc.items() if v != 0}
    for a, b in fmap:
        if a in hs and b in hs and a in withmax and a not in tkind:
            tkind.append(a)
    #     CM_FORCMAP('FORC-KYO',CM_VAR)$(NOT CM_FORCMAP(CM_VAR,CM_VAR)) $= CM_PPM(CM_VAR);
    #     CM_FORCMAP('FORCING',CM_VAR) $= CM_PPM(CM_VAR);
    fs = set(fmap)
    for head in ("FORC-KYO", "FORCING"):
        for v in hists:
            if ppm.get(v, 0) != 0 and (head == "FORCING" or (v, v) not in fs) and (head, v) not in fs:
                fmap.append((head, v))
                fs.add((head, v))
    #     CM_FORCMAP(CM_HISTS,CM_VAR)$(SUM(CM_EMIS$CM_FORCMAP(CM_VAR,CM_EMIS),1)$(NOT CM_EMIS(CM_VAR))) = NO;
    tomis = {a for a, b in fmap if b in es}
    fmap = [(a, b) for a, b in fmap if not (a in hs and b in hs and b in tomis and b not in es)]
    # --- Establish set of years beyond EOH
    #     OPTION CLEAR=FIL; YR_VL = 0; FIRST_VAL = CM_CONST('EXT-EOH');  IF(FIRST_VAL GT 0, ...);   (refused)
    s["YR_VL"] = 0.0
    if C("EXT-EOH") > 0:
        unsupported(db, "the climate module beyond the end of the horizon (CM_CONST('EXT-EOH') > 0, coef_ext.cli 83-99)",
                    ["CM_CONST"])
    #     CM_MAXC(LL,CM_EMIS(CM_HISTS(CG)))$(YEARVAL(LL) GT MIYR_VL) = 0;
    for (y, i) in list(maxc):
        if i in es and i in hs and _yv(y) > s["MIYR_VL"]:
            del maxc[(y, i)]
    # --- Complete CM_LED:  LOOP(FIL(LL), Z = ORD(LL); CM_LED(LL) = Z-F; F = Z);   (FIL is empty without EXT-EOH)
    #     CM_LED(T) = LEAD(T); CM_LED(MIYR_1) = CM_CALIB;  PRET(T,T-1)=YES;
    led = {t: LEAD[t] for t in T if LEAD.get(t, 0) != 0}
    led[m1] = calib
    _put(db, "CM_LED", {(y,): v for y, v in led.items()})
    _sput(db, "PRET", [(T[k], T[k - 1]) for k in range(1, len(T))])
    #     $ BATINCLUDE filparam CM_BEMI 'CM_EMIS,' '' ",'','','','',''" LL FIL '' ''   (CM_BEMI, CM_EVAR: empty)
    #     $ BATINCLUDE filparam CM_EVAR 'CM_EMIS,' '' ",'','','','',''" LL FIL '' ''
    #     CM_EVAR(CM_EMIS,T) = 1;
    _put(db, "CM_EVAR", {(e, t): 1.0 for e in emis for t in T})
    led_years = [y for y in ys if led.get(y, 0) != 0]           # LL$CM_LED(LL), in the order of ALLYEAR
    aa, bb, cc = {}, {}, {}
    sows = [w for (w,) in db.q("select w from SOW")]
    if forcing:
        # --- CM_SIG1(SOW) = CM_CONST('SIGMA1');
        #     CM_SIG('1','ATM','ATM') = 1-CM_SIG1('1')*(CM_CONST('LAMBDA')+CM_CONST('SIGMA2'));
        #     CM_SIG(SOW,'ATM','LO') = CM_SIG1(SOW)*CM_CONST('SIGMA2');  CM_SIG(SOW,'LO','ATM') = CM_CONST('SIGMA3');
        #     CM_SIG(SOW,'LO','LO') = 1-CM_CONST('SIGMA3');  CM_PHI('FORCING','ATM','FORCING') = 1;
        sig1 = {w: C("SIGMA1") for w in sows}
        if st:
            # --- $ IFI %STAGES%==YES $BATINCLUDE fillsow.stc CM_CONST CM_STCC '' '' YES YES YES
            #     $ IFI %STAGES%==YES $BATINCLUDE fillsow.stc DAM_COST ..   (DAMAGE is not supported)
            #     $ IFI %STAGES%==YES CM_SIG1(SOW)=S_CM_CONST('SIGMA1','1',SOW);
            #     $ IFI %STAGES%==YES     CM_SIG(SOW,'ATM','ATM') = 1-CM_SIG1(SOW)*(CM_CONST('GAMMA')/S_CM_CONST('CS','1',SOW)+CM_CONST('SIGMA2'));
            scon = _fillsow_const(db, const)
            sig1 = {w: _n(scon.get(("SIGMA1", "1", w), 0.0)) for w in sows}
            sig = {}
            for w in sows:
                cs = _n(scon.get(("CS", "1", w), 0.0))
                if cs == 0:
                    unsupported(db, f"the climate module with STAGES: no climate sensitivity CS for SOW {w} (coef_ext.cli 117)",
                                ["S_CM_CONST"])
                    continue
                sig[(w, "ATM", "ATM")] = 1 - sig1[w] * (C("GAMMA") / cs + C("SIGMA2"))
        else:
            # --- $ IFI NOT %STAGES%==YES CM_SIG('1','ATM','ATM') = 1-CM_SIG1('1')*(CM_CONST('LAMBDA')+CM_CONST('SIGMA2'));
            sig = {("1", "ATM", "ATM"): 1 - sig1.get("1", 0.0) * (C("LAMBDA") + C("SIGMA2"))}
        _put(db, "CM_SIG1", {(w,): v for w, v in sig1.items()})
        for w in sows:
            sig[(w, "ATM", "LO")] = sig1[w] * C("SIGMA2")
            sig[(w, "LO", "ATM")] = C("SIGMA3")
            sig[(w, "LO", "LO")] = 1 - C("SIGMA3")
        sig = {k: v for k, v in sig.items() if v != 0}
        _put(db, "CM_SIG", sig)
        phi[("FORCING", "ATM", "FORCING")] = 1.0
        # --- CM_AA('FORCING',LL,SOW,CM_BUCK,CM_BOX)$CM_LED(LL) = DIAG(CM_BUCK,CM_BOX);  CM_BB('FORCING',LL,SOW,CM_BUCK)$CM_LED(LL) = 0;
        #     CNT=0;
        #     LOOP((CM_VAR('FORCING'),LL)$CM_LED(LL),
        #      IF(CNT, CNT=1; Z = CM_LED(LL); ELSE CNT=EPS; Z=CM_CALIB);
        #       FOR(F = 0 TO Z-1, MY_F = F/Z*CNT;
        #        CM_BB(CM_VAR,LL,SOW,CM_BOX) = CM_BB(CM_VAR,LL,SOW,CM_BOX) + CM_SIG1(SOW)*(1-MY_F)*CM_AA(CM_VAR,LL,SOW,CM_BOX,'ATM');
        #        CM_CC(CM_VAR,LL,SOW,CM_BOX) = CM_CC(CM_VAR,LL,SOW,CM_BOX) + CM_SIG1(SOW)*   MY_F *CM_AA(CM_VAR,LL,SOW,CM_BOX,'ATM');
        #        CM_AA(CM_VAR,LL,SOW,CM_BUCK,CM_BOX) = SUM(CM_Q$CM_BOX(CM_Q),CM_AA(CM_VAR,LL,SOW,CM_BUCK,CM_Q)*CM_SIG(SOW,CM_Q,CM_BOX))));
        cnt = 0.0
        for ll in led_years if "FORCING" in hs else []:
            if cnt:
                cnt, z = 1.0, _n(led[ll])
            else:
                cnt, z = EPS, _n(calib)
            for w in sows:
                a = {(b, b): 1.0 for b in BOXES}
                m = {(i, j): v for (ww, i, j), v in sig.items() if ww == w}
                bv, cv = {}, {}
                f = 0
                while f <= z - 1:
                    myf = f / z * _n(cnt)
                    for b in BOXES:
                        bv[b] = bv.get(b, 0.0) + sig1[w] * (1 - myf) * a.get((b, "ATM"), 0.0)
                        cv[b] = cv.get(b, 0.0) + sig1[w] * myf * a.get((b, "ATM"), 0.0)
                    a = _matmul(a, m)
                    f += 1
                aa.update({("FORCING", ll, w) + k: v for k, v in a.items()})
                bb.update({("FORCING", ll, w, b): v for b, v in bv.items() if v != 0})
                cc.update({("FORCING", ll, w, b): v for b, v in cv.items() if v != 0})
    # --- Set up control set CM_CONC for the BOX equations; complete PHI
    #     OPTION CM_CONC <= CM_BOXMAP;   (the first and the last index)
    _sput(db, "CM_CONC", [(a, q) for a, v, q in boxmap])
    #     CM_PHI(CM_KIND,CM_BOX,CM_BOX)$(NOT CM_PHI(CM_KIND,CM_BOX,CM_BOX)) =
    #       1$CM_STAT0(CM_KIND,CM_BOX)-SUM(CM_BUCK$(NOT SAMEAS(CM_BOX,CM_BUCK)),CM_PHI(CM_KIND,CM_BUCK,CM_BOX));
    for k in kind:
        for b in BOXES:
            if phi.get((k, b, b), 0) == 0:
                v = (1.0 if stat0.get((k, b), 0) != 0 else 0.0) - sum(phi.get((k, u, b), 0.0) for u in BOXES if u != b)
                if v != 0:
                    phi[(k, b, b)] = v
    # --- Calculate the ith powers of PHI, i=1...Z, where Z = LEAD(T)
    #     LOOP(CM_EMIS(CM_VAR),
    #      CM_PHI(CM_VAR,'ATM',CM_VAR)$(NOT SUM(CM_BOX$CM_PHI(CM_VAR,'ATM',CM_VAR),1)) = 1;
    #      CM_AA(CM_VAR,LL,'1',CM_BUCK,CM_BOX)$CM_LED(LL) = DIAG(CM_BUCK,CM_BOX);  CM_BB(CM_VAR,LL,'1',CM_BUCK)$CM_LED(LL) = 0;
    #      CNT = (ALTOBJ NE 3);
    #      LOOP(T$(ALTOBJ NE 3),
    #       IF(ORD(T) GT 1, MY_F = M(T)-B(T)+1; Z = LEAD(T); ELSE MY_F=CM_CALIB; Z=MY_F);
    #        FOR(F = 1 TO Z,
    #          IF(F LE MY_F, CM_BB(CM_VAR,T,'1',CM_BOX) = CM_BB(..) + SUM(CM_BUCK,CM_PHI(CM_VAR,CM_BUCK,CM_VAR)*CM_AA(CM_VAR,T,'1',CM_BOX,CM_BUCK));
    #          ELSE          CM_CC(CM_VAR,T,'1',CM_BOX) = CM_CC(..) + SUM(CM_BUCK,CM_PHI(CM_VAR,CM_BUCK,CM_VAR)*CM_AA(CM_VAR,T,'1',CM_BOX,CM_BUCK)));
    #          CM_AA(CM_VAR,T,'1',CM_BUCK,CM_BOX) = SUM(CM_Q$CM_BOX(CM_Q),CM_AA(CM_VAR,T,'1',CM_BUCK,CM_Q)*CM_PHI(CM_VAR,CM_Q,CM_BOX))));
    #      LOOP(LL$(((ALTOBJ EQ 3) OR NOT T(LL))$CM_LED(LL)), ...linear evolution of emissions...));
    #     (every year with CM_LED is a milestone without EXT-EOH; OBJ LIN is refused)
    if s["ALTOBJ"] == 3:
        unsupported(db, "the climate module with OBJ LIN (the linear evolution of emissions, coef_ext.cli 153-160, and the "
                        "pulses of EQ_CLIMAX)")
    for v in emis:
        if not phi.get((v, "ATM", v)):
            phi[(v, "ATM", v)] = 1.0
        m = {(i, j): x for (e, i, j), x in phi.items() if e == v and i in BOXES and j in BOXES}
        inflow = {u: phi.get((v, u, v), 0.0) for u in BOXES}
        for k, t in enumerate(T):
            if k > 0:
                myf, z = M[t] - B[t] + 1, _n(LEAD.get(t, 0.0))
            else:
                myf = z = _n(calib)
            a = {(b, b): 1.0 for b in BOXES}
            bv, cv = {}, {}
            f = 1
            while f <= z:
                tgt = bv if f <= myf else cv
                for b in BOXES:
                    tgt[b] = tgt.get(b, 0.0) + sum(inflow[u] * a.get((b, u), 0.0) for u in BOXES)
                a = _matmul(a, m)
                f += 1
            aa.update({(v, t, "1") + kk: x for kk, x in a.items()})
            bb.update({(v, t, "1", b): x for b, x in bv.items() if x != 0})
            cc.update({(v, t, "1", b): x for b, x in cv.items() if x != 0})
    _put(db, "CM_AA", aa)
    _put(db, "CM_BB", bb)
    _put(db, "CM_CC", cc)
    _put(db, "CM_PHI", phi)
    _put(db, "CM_DECAY", decay)
    _put(db, "CM_STAT0", stat0)
    _sput(db, "CM_ATMAP", atmap)
    _sput(db, "CM_BOXMAP", boxmap)
    _sput(db, "CM_KIND", kind)
    _sput(db, "CM_TKIND", tkind)
    _sput(db, "CM_EMIS", emis)
    _sput(db, "CM_FORCMAP", fmap)
    # --- Prepare commodity variables for emissions:
    #     CM_GHGMAP(R,C,'CO2-GTC') $= CM_CO2GTC(R,C);
    #     LOOP((R,C,CM_KIND(CM_VAR(CG)))$CM_GHGMAP(R,C,CG),
    #       RHS_COMBAL(RTCS_VARC(R,T,C,S)) = YES;  RCS_COMBAL(RTCS_VARC(R,T,C,S),'FX') = YES);
    db.put("CM_GHGMAP", "select r, c, 'CO2-GTC' as cg, value from CM_CO2GTC where in_REG(r)", zero="skip")
    ks = [k for k in kind if k in hs]
    if ks:
        sel = f"""select v.r, v.y, v.c, v.s from RTCS_VARC v
                  where exists(select 1 from CM_GHGMAP g where g.r = v.r and g.c = v.c
                               and g.cg in ({", ".join(f"'{k}'" for k in ks)}))"""
        db.add("RHS_COMBAL", sel)
        db.add("RCS_COMBAL", f"select r, y, c, s, 'FX' as l from ({sel})")
    # --- Construct SUPERYR (needed in MAX constraints)
    #     SUPERYR(PERIODYR(T,LL))$(YEARVAL(LL) LE YEARVAL(T)) = YES;
    #     SUPERYR(T+1,LL)$((YEARVAL(LL) GT YEARVAL(T))$PERIODYR(T,LL)) = YES;
    #     LOOP(MIYR_1(T++1),SUPERYR(T,LL)$(YEARVAL(LL) GT M(T)) = YES);
    nxt = dict(zip(T, T[1:]))
    sup = []
    for t, ll in db.q("select y, y2 from PERIODYR where in_MILESTONYR(y)"):
        if _yv(ll) <= _yv(t):
            sup.append((t, ll))
        elif t in nxt:
            sup.append((nxt[t], ll))
    sup += [(T[-1], y) for y in ys if _yv(y) > M[T[-1]]]
    sup.sort(key=lambda k: (ypos[k[0]], ypos[k[1]]))
    _sput(db, "SUPERYR", sup)
    #     OPTION FIL < CM_LED, MY_FIL < Y;  MY_FIL(LL)$((YEARVAL(LL)>MIYR_VL)$(ORD(LL) LE YR_VL)) = YES;   (YR_VL = 0)
    fil = led_years
    yset = {x for (x,) in db.q("select y from Y")}
    my_fil = [y for y in ys if y in yset]
    # --- Interpolate parameters by default or if requested by user:
    #     $BATINCLUDE filparam CM_LINFOR '' 'CM_VAR,LIM' ",'','','','',''" DATAYEAR FIL '' ''
    #     $BATINCLUDE filparam CM_MAXCO2C '' '' ",'','','','','',''" LL T '' '' -1
    #     $BATINCLUDE filparam CM_MAXC '' 'CG' ",'','','','','',''" LL FIL '' '' -1
    #     $BATINCLUDE filparam CM_EXOFORC '' '' ",'','','','','',''" LL MY_FIL '' ''
    #     $BATINCLUDE filparam UC_CLI 'UC_N,SIDE,R,' 'CM_VAR' ",'','',''" DATAYEAR T
    dset = {x for (x,) in db.q("select y from DATAYEAR")}
    dy = [y for y in ys if y in dset]
    REG = {r for (r,) in db.q("select r from REG")}
    linfor = filparam(_get(db, "CM_LINFOR"), 0, dy, fil, lambda k: k[0] in hs and k[1] in LIM)
    maxco2c = filparam(_get(db, "CM_MAXCO2C"), 0, ys, T, default=-1)
    maxc = filparam(maxc, 0, ys, fil, default=-1)
    exo = filparam(_get(db, "CM_EXOFORC"), 0, ys, my_fil)
    _put(db, "UC_CLI", filparam(_get(db, "UC_CLI"), 3, dy, T, lambda k: k[2] in REG and k[3] in hs))
    # --- Convert all concentration bounds to PPM basis
    #     CM_MAXC(LL,CG('CO2-PPM'))$CM_MAXCO2C(LL) = MIN(CM_MAXC(LL,CG)+INF$(NOT CM_MAXC(LL,CG)),CM_MAXCO2C(LL)/CM_PPM('CO2-GTC'));
    #     CM_MAXC(LL,CG('CO2-PPM'))$CM_MAXC(LL,'CO2-ATM') = MIN(..,CM_MAXC(LL,'CO2-ATM')*CM_CONST('CO2-PREIND')/CM_PPM('CO2-GTC'));
    #     CM_MAXC(LL,CG('CO2-PPM'))$(CM_MAXC(LL,'FORCING')*(NOT CM_KIND('FORCING'))) = MIN(..,CM_CONST('CO2-PREIND')/CM_PPM('CO2-GTC')*
    #        EXP((CM_MAXC(LL,'FORCING')-CM_EXOFORC(LL))*LOG(2)/CM_CONST('GAMMA')));
    pg = _n(ppm.get("CO2-GTC", 0.0))

    def cur(y):
        v = maxc.get((y, "CO2-PPM"), 0.0)
        return _n(v) if v != 0 else math.inf
    for (y,), v in maxco2c.items():
        if v != 0:
            maxc[(y, "CO2-PPM")] = min(cur(y), _n(v) / pg)
    for (y, i), v in list(maxc.items()):
        if i == "CO2-ATM" and v != 0:
            maxc[(y, "CO2-PPM")] = min(cur(y), _n(v) * C("CO2-PREIND") / pg)
    if not forcing:
        for (y, i), v in list(maxc.items()):
            if i == "FORCING" and _n(v) != 0:
                maxc[(y, "CO2-PPM")] = min(cur(y), C("CO2-PREIND") / pg *
                                           math.exp((_n(v) - _n(exo.get((y,), 0.0))) * math.log(2) / C("GAMMA")))
    # --- Remove bounds from years with undefined concentration
    #     F = SMIN(T,YEARVAL(T));  CM_MAXC(LL,CG)$(YEARVAL(LL) LT F) = 0;
    maxc = {k: v for k, v in maxc.items() if _yv(k[0]) >= _yv(m1)}
    _put(db, "CM_MAXC", maxc)
    if st:
        _stochastic_maxc(db, ys, T, dy, sup, maxc, exo, ppm, C, forcing)
    _put(db, "CM_MAXCO2C", maxco2c)
    # --- Calculate linear slope for FORCING from CO2
    if forcing:
        #   OPTION FIL<CM_LED;  LOOP(CM_ATMAP(CM_EMIS,CM_VAR),CM_LINFOR(FIL(LL),CM_EMIS,L) $= CM_LINFOR(LL,CM_VAR,L));
        for e, v in atmap:
            if e in es and v in hs:
                for y in fil:
                    for l in LIM:
                        x = linfor.get((y, v, l), 0.0)
                        if x != 0:
                            linfor[(y, e, l)] = x
        #   CM_LINFOR(FIL(LL),'CO2-GTC',BDNEQ) $= CM_LINFOR(LL,'CO2-ATM',BDNEQ)*CM_CONST('CO2-PREIND')*(1/CM_PPM('CO2-GTC'));
        for y in fil:
            for l in ("LO", "UP"):
                x = _n(linfor.get((y, "CO2-ATM", l), 0.0)) * C("CO2-PREIND") * (1 / pg)
                if x != 0:
                    linfor[(y, "CO2-GTC", l)] = x
        #   MY_ARRAY(FIL(LL)) = MAX(CM_LINFOR(LL,'CO2-GTC','LO'),
        #      ((CM_LINFOR(LL,'CO2-GTC','UP')-CM_LINFOR(LL,'CO2-GTC','LO')) /
        #       LOG(MAX(1.001,CM_LINFOR(LL,'CO2-GTC','UP')/CM_LINFOR(LL,'CO2-GTC','LO')))))$(CM_LINFOR(LL,'CO2-GTC','LO') GT 0);
        #   CM_LINFOR(FIL(LL),'CO2-GTC','N')$MY_ARRAY(LL) = CM_CONST('GAMMA')/MY_ARRAY(LL)/LOG(2);
        #   CM_LINFOR(FIL(LL),'CO2-GTC','FX')$MY_ARRAY(LL) =
        #      (CM_CONST('GAMMA')/LOG(2) * LOG(MY_ARRAY(LL)*CM_LINFOR(LL,'CO2-GTC','LO')/POWER(CM_CONST('CO2-PREIND')/CM_PPM('CO2-GTC'),2)) -
        #       CM_LINFOR(LL,'CO2-GTC','N')*(MY_ARRAY(LL)+CM_LINFOR(LL,'CO2-GTC','LO')))/2;
        g = C("GAMMA")
        for y in fil:
            lo, up = _n(linfor.get((y, "CO2-GTC", "LO"), 0.0)), _n(linfor.get((y, "CO2-GTC", "UP"), 0.0))
            arr = max(lo, (up - lo) / math.log(max(1.001, up / lo))) if lo > 0 else 0.0
            if arr == 0:
                continue
            n = g / arr / math.log(2)
            linfor[(y, "CO2-GTC", "N")] = n
            linfor[(y, "CO2-GTC", "FX")] = (g / math.log(2) * math.log(arr * lo / (C("CO2-PREIND") / pg) ** 2) - n * (arr + lo)) / 2
    _put(db, "CM_LINFOR", linfor)
    # --- If EXOFORCING is not provided by the user, use default values
    #     IF(NOT SUM(T,CM_EXOFORC(T)),CM_EXOFORC(MY_FIL(LL)) = MIN(1.15, -0.1965 + 0.013465 * (YEARVAL(LL)-1995)));
    if not any(exo.get((t,), 0) != 0 for t in T):
        for y in my_fil:
            exo[(y,)] = min(1.15, -0.1965 + 0.013465 * (_yv(y) - 1995))
    _put(db, "CM_EXOFORC", exo)


# ---------------------------------------------------------------------------------------------------------------------
# The climate module with STAGES: the uncertain climate constants and bounds (S_CM_CONST, S_CM_MAXC, S_CM_MAXCO2C)

def _tree(db: DB):
    """the SOWs (in order) and the sets of the tree that fillsow.stc reads"""
    num = lambda w: int(w) if w.isdigit() else 1 << 30
    sows = sorted((w for (w,) in db.q("select w from SOW")), key=num)
    cpmap = [tuple(r) for r in db.q("select j, ww, ww2 from SW_CPMAP")]
    rev = [tuple(r) for r in db.q("select ww, j, ww2 from SW_REV")]
    return sows, cpmap, rev


def _fillsow_const(db: DB, const):
    """fillsow.stc CM_CONST CM_STCC '' '' YES YES YES (no year, absolute, every period, the deterministic value copied):
    S_CM_CONST(CM_STCC,J,SOW) -> stage '1' by SOW; returns {(item, j, w): value}"""
    stcc = [i for (i,) in db.q("select * from CM_STCC")] if db.card("CM_STCC") else ["CS", "SIGMA1"]   # initmty.cli 59
    S = _get(db, "S_CM_CONST")
    sows, cpmap, rev = _tree(db)
    sw = set(sows)
    # --- S_CM_CONST(CM_STCC,'1',SOW)$(NOT SAMEAS(SOW,'1')) = 0;
    S = {k: v for k, v in S.items() if not (k[0] in stcc and k[1] == "1" and k[2] != "1" and k[2] in sw)}
    # --- S_CM_CONST(CM_STCC,J,WW)$((NOT S_CM_CONST(CM_STCC,J,WW))) $= SUM(SW_CPMAP(J,WW,SOW),S_CM_CONST(CM_STCC,J,SOW));
    for i in stcc:
        for j, ww, w in cpmap:
            x = S.get((i, j, w), 0)
            if x != 0 and not S.get((i, j, ww), 0):
                S[(i, j, ww)] = x
    # --- S_CM_CONST(CM_STCC,'1','1')$(NOT S_CM_CONST(CM_STCC,'1','1')) $= CM_CONST(CM_STCC);
    for i in stcc:
        if not S.get((i, "1", "1"), 0) and const.get(i, 0) != 0:
            S[(i, "1", "1")] = const[i]
    # --- LOOP(J$SW_START(J),S_CM_CONST(CM_STCC,'1',WW)$(YES) $= SUM(SW_REV(WW,J,SOW),S_CM_CONST(CM_STCC,J,SOW)));
    starts = sorted((j for (j,) in db.q("select j from SW_START")), key=int)
    for j in starts:
        for i in stcc:
            new = {}
            for ww, jj, w in rev:
                if jj == j and S.get((i, j, w), 0) != 0:
                    new[ww] = new.get(ww, 0.0) + S[(i, j, w)]
            for ww, x in new.items():
                if x != 0:
                    S[(i, "1", ww)] = x
    _put(db, "S_CM_CONST", S)
    return S


def _stochastic_maxc(db: DB, ys, T, dy, sup, maxc, exo, ppm, C, forcing):
    """coef_ext.cli 184-185, 194-201: the uncertain bounds S_CM_MAXCO2C, S_CM_MAXC interpolated, converted to the PPM basis
    and merged into stage '1' by SOW (fillsow.stc CM_MAXC '' 'CG' LL YES 'SUPERYR(T,LL)' YES)"""
    tstg = {(t, j) for t, j in db.q("select y, j from SW_TSTG")}
    swt = {(t, w) for t, w in db.q("select y, w from SW_T")}
    # --- $IFI %STAGES%==YES $BATINCLUDE filparam S_CM_MAXCO2C '' 'J,WW' ",'','','','',''" DATAYEAR T SW_TSTG(T,J)$ '' -1
    #     $IFI %STAGES%==YES $BATINCLUDE filparam S_CM_MAXC '' 'CG,J,WW' ",'','','',''" DATAYEAR T SW_TSTG(T,J)$ '' -1
    sco2 = filparam(_get(db, "S_CM_MAXCO2C"), 0, dy, T, default=-1, back_ok=lambda k, t: (t, k[0]) in tstg)
    S = filparam(_get(db, "S_CM_MAXC"), 0, dy, T, default=-1, back_ok=lambda k, t: (t, k[1]) in tstg)
    _put(db, "S_CM_MAXCO2C", sco2)
    # --- S_CM_MAXC(LL,CG('CO2-PPM'),J,W)$S_CM_MAXCO2C(LL,J,W) = MIN(S_CM_MAXC(LL,CG,J,W)+INF$(NOT S_CM_MAXC(LL,CG,J,W)),S_CM_MAXCO2C(LL,J,W)/CM_PPM('CO2-GTC'));
    #     S_CM_MAXC(LL,CG('CO2-PPM'),J,W)$S_CM_MAXC(LL,'CO2-ATM',J,W) = MIN(..,S_CM_MAXC(LL,'CO2-ATM',J,W)*CM_CONST('CO2-PREIND')/CM_PPM('CO2-GTC'));
    #     S_CM_MAXC(LL,CG('CO2-PPM'),J,W)$(S_CM_MAXC(LL,'FORCING',J,W)*(NOT CM_KIND('FORCING'))) =
    #        MIN(..,CM_CONST('CO2-PREIND')/CM_PPM('CO2-GTC')*EXP((S_CM_MAXC(LL,'FORCING',J,W)-CM_EXOFORC(LL))*LOG(2)/CM_CONST('GAMMA')));
    pg = _n(ppm.get("CO2-GTC", 0.0))

    def cur(y, j, w):
        v = S.get((y, "CO2-PPM", j, w), 0.0)
        return _n(v) if v != 0 else math.inf
    for (y, j, w), v in sco2.items():
        if v != 0:
            S[(y, "CO2-PPM", j, w)] = min(cur(y, j, w), _n(v) / pg)
    for (y, i, j, w), v in list(S.items()):
        if i == "CO2-ATM" and v != 0:
            S[(y, "CO2-PPM", j, w)] = min(cur(y, j, w), _n(v) * C("CO2-PREIND") / pg)
    if not forcing:
        for (y, i, j, w), v in list(S.items()):
            if i == "FORCING" and _n(v) != 0:
                S[(y, "CO2-PPM", j, w)] = min(cur(y, j, w), C("CO2-PREIND") / pg *
                                              math.exp((_n(v) - _n(exo.get((y,), 0.0))) * math.log(2) / C("GAMMA")))
    #     S_CM_MAXC(LL,CG,J,W)$(YEARVAL(LL) LT F) = 0;
    S = {k: v for k, v in S.items() if _yv(k[0]) >= _yv(T[0])}
    # --- $ BATINCLUDE fillsow.stc CM_MAXC '' 'CG' LL YES 'SUPERYR(T,LL)' YES
    sows, cpmap, rev = _tree(db)
    sw = set(sows)
    #     S_CM_MAXC(LL,CG,'1',SOW)$(NOT SAMEAS(SOW,'1')) = 0;
    S = {k: v for k, v in S.items() if not (k[2] == "1" and k[3] != "1" and k[3] in sw)}

    #     S_CM_MAXC(LL--ORD(LL),CG,J,WW) $= S_CM_MAXC(LL,CG,J,WW);   (the flag of a series: its year '0')
    def flags():
        return {(i, j, w) for (y, i, j, w), v in S.items() if v != 0}
    flag = flags()
    n0 = len(S) + len(flag)
    #     S_CM_MAXC(LL,CG,J,WW)$((NOT S_CM_MAXC('0',CG,J,WW))) $= SUM(SW_CPMAP(J,WW,SOW),S_CM_MAXC(LL,CG,J,SOW));
    for j, ww, w in cpmap:
        for (y, i, jj, w2), v in list(S.items()):
            if jj == j and w2 == w and v != 0 and (i, j, ww) not in flag:
                S[(y, i, j, ww)] = v
        flag |= {(i, j, ww) for (i, jj, w2) in list(flag) if jj == j and w2 == w and (i, j, ww) not in flag}
    #     IF(CARD(S_CM_MAXC)>F, S_CM_MAXC(LL--ORD(LL),CG,J,WW) $= S_CM_MAXC(LL,CG,J,WW));
    if len(S) + len(flag) > n0:
        flag = flags()
    #     S_CM_MAXC(LL,CG,'1','1')$(NOT S_CM_MAXC('0',CG,'1','1')) $= CM_MAXC(LL,CG);
    for (y, i), v in maxc.items():
        if v != 0 and y != "0" and (i, "1", "1") not in flag:
            S[(y, i, "1", "1")] = v
    #     LOOP(SW_TSTG(T,J), S_CM_MAXC(LL,CG,'1',WW)$(SUPERYR(T,LL)$SW_T(T,WW)) $= SUM(SW_REV(WW,J,SOW),S_CM_MAXC(LL,CG,J,SOW)));
    ypos = {y: k for k, y in enumerate(ys)}
    for t, j in sorted(tstg, key=lambda k: (ypos[k[0]], int(k[1]))):
        lls = {ll for (tt, ll) in sup if tt == t}
        new = {}
        for (y, i, jj, w), v in S.items():
            if jj != j or y not in lls or v == 0:
                continue
            for ww, j2, w2 in rev:
                if j2 == j and w2 == w and (t, ww) in swt:
                    new[(y, i, ww)] = new.get((y, i, ww), 0.0) + v
        for (y, i, ww), v in new.items():
            if v != 0:
                S[(y, i, "1", ww)] = v
    #     S_CM_MAXC('0',CG,J,WW) = 0;   (the flags)
    _put(db, "S_CM_MAXC", S)


def uc_attr(db: DB):
    """init_ext.vda 129:
    $ IF %CLI%==YES LOOP((UC_N,SIDE,R,LL,CM_VAR)$UC_CLI(UC_N,SIDE,R,LL,CM_VAR),UC_ATTR(R,UC_N,'RHS','CLI','YES')=YES);"""
    if not on(db) or not db.card("UC_CLI"):
        return
    db.add("UC_ATTR", """select distinct r, uc, 'RHS' as side, 'CLI' as grp, 'YES' as ucn from UC_CLI
                         where in_REG(r) and in_CM_HISTS(cm_item)""")


def mod_vars(db: DB):
    """mod_vars.cli 10-26 (maindrv.mod 78, main_ext.mod mod_vars): the bounds of the climate variables
         POSITIVE VARIABLES  %VAR%_CLITOT(CM_ITEM,LL %SWD%), %VAR%_CLIBOX(CM_ITEM,CM_BOX,LL %SWD%);
         %VAR%_CLITOT.LO(CM_VAR,LL %SOW%)$CM_LED(LL) = MIN(-15,CM_BEMI(CM_VAR,LL));
         %VAR%_CLITOT.LO(CM_VAR('FORCING'),LL%SOW%)$CM_LED(LL) = -2;"""
    if not on(db):
        return
    bemi = _get(db, "CM_BEMI")
    led = [y for (y,) in db.q("select y from CM_LED")]
    rows = [(h, y, -2.0 if h == "FORCING" else min(-15.0, _n(bemi.get((h, y), 0.0))), math.inf)
            for (h,) in _sget(db, "CM_HISTS") for y in led]
    if stochastic.tagged(db):
        # with STAGES (%VAR% = VAS, %SOW% = ',SOW'): the bounds of every SOW
        sows, _, _ = _tree(db)
        db.x('drop table if exists "B_VAS_CLITOT"')
        db.x('create table "B_VAS_CLITOT" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, lower DOUBLE, upper DOUBLE)')
        db.insert_rows('"B_VAS_CLITOT"', [(h, y, w, lo, up) for (h, y, lo, up) in rows for w in sows])
        db.bounds.add("VAS_CLITOT")
        return
    db.x('drop table if exists "B_VAR_CLITOT"')
    db.x('create table "B_VAR_CLITOT" (d0 VARCHAR, d1 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.insert_rows('"B_VAR_CLITOT"', rows)
    db.bounds.add("VAR_CLITOT")
