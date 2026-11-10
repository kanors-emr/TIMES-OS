# SPDX-License-Identifier: GPL-3.0-or-later
"""The results of the climate module (rpt_ext.cli, rpt_par.cli): CM_RESULT and CM_MAXC_M, which the .vd file has as
VAR_Climate and Dual_clic (times2veda.vdd 95-96).

    CM_RESULT(item, 'CM-EMIS' | 'CM-FORC', y)      the totals VAR_CLITOT (emissions; forcings)
    CM_RESULT(item, 'CM-ATM' | 'CM-UP' | 'CM-LO', y)   the reservoirs VAR_CLIBOX
    CM_RESULT(conc, 'CM-PPX', y)                    the atmospheric concentrations (ppm, ppb)
    CM_RESULT('FORC+CO2' | 'FORC+TOT', 'CM-FORC', y)   the radiative forcing of CO2 and the total, by year
    CM_RESULT('DELTA+ATM' | 'DELTA+LO', 'CM-DT', y)    the temperature changes, by year, from the forcing by year
    CM_MAXC_M(item, y)                              the shadow prices of the totals and of the bounds (absolute)

The forcing and the temperatures by year are computed from the solution as TIMES does: the CO2 concentration taken
linear between the milestone years, its forcing logarithmic, the other forcings linear, and the temperature boxes
stepped year by year with the matrix CM_SIG.
"""
from __future__ import annotations
import math

EPS = 1e-300
BOXES = ("ATM", "UP", "LO", "N")


# the tables of the climate module the report reads (prep/cli.py; declarations of initmty.cli and ppm_ext.cli)
TABLES = {"CM_TKIND": ("set", ["CM_ITEM"]), "CM_EMIS": ("set", ["CM_ITEM"]), "CM_HISTS": ("set", ["CG"]),
          "CM_OFOR": ("set", ["CM_ITEM"]), "CM_BOXMAP": ("set", ["CM_ITEM", "CM_ITEM", "CM_BOX"]),
          "CM_FORCMAP": ("set", ["CM_ITEM", "CM_ITEM"]), "CM_ATMAP": ("set", ["CM_ITEM", "CM_ITEM"]),
          "CM_REBOX": ("set", ["CM_Q", "CM_Q"]), "SUPERYR": ("set", ["T", "ALLYEAR"]),
          "CM_CONST": ("par", ["ITEM"]), "CM_PPM": ("par", ["CM_ITEM"]), "CM_LED": ("par", ["ALLYEAR"]),
          "CM_EXOFORC": ("par", ["ALLYEAR"]), "CM_STAT0": ("par", ["CM_ITEM", "CM_Q"]),
          "CM_PHI": ("par", ["CM_ITEM", "ITEM", "ITEM"]), "CM_LINFOR": ("par", ["ALLYEAR", "CM_ITEM", "LIM"]),
          "CM_SIG": ("par", ["ALLSOW", "ITEM", "ITEM"]), "CM_SIG1": ("par", ["ALLSOW"]), "CM_CALIB": ("par", [])}


def load(db, have):
    """The tables of TABLES from model.db3 (attached as mdl), when the run has the climate module."""
    if "CM_TKIND" not in have:
        return
    for name, (kind, dom) in TABLES.items():
        if name not in have:
            continue
        if kind == "par" and not dom:
            db.declare(name, "par", [])
            val = db.con.execute(f'select value from mdl."{name}"').fetchone()
            db.s[name] = float(val[0]) if val and val[0] is not None else 0.0
            continue
        db.declare(name, kind, dom)
        db.clear(name)
        db.x(f'insert into "{name}" select * from mdl."{name}"')


def _get(db, name):
    if name not in db.sym:
        return {}
    return {tuple(r[:-1]): (EPS if r[-1] == 0 else r[-1]) for r in db.q(f'select * from "{name}"')}


def _set(db, name):
    return [tuple(r) for r in db.q(f'select * from "{name}"')] if name in db.sym else []


def _n(v):
    return 0.0 if v is None or abs(v) < 1e-200 else v


def _yv(y):
    return int(y) if y != "0" else 0


def run(db):
    """rpt_ext.cli 31-45 with rpt_par.cli (one state of the world, '1'). Returns the names written."""
    if "CM_TKIND" not in db.sym or not db.card("CM_TKIND"):
        return []
    one = lambda n: {k[0]: v for k, v in _get(db, n).items()}
    const = one("CM_CONST")
    C = lambda k: _n(const.get(k, 0.0))
    ppm = one("CM_PPM")
    led = one("CM_LED")
    exo = one("CM_EXOFORC")
    calib = _n(db.s.get("CM_CALIB", 1.0)) if "CM_CALIB" in db.s else 1.0
    stat0 = _get(db, "CM_STAT0")
    phi = _get(db, "CM_PHI")
    linfor = _get(db, "CM_LINFOR")
    sig = _get(db, "CM_SIG")
    sig1 = one("CM_SIG1")
    boxmap = _set(db, "CM_BOXMAP")
    fmap = _set(db, "CM_FORCMAP")
    atmap = _set(db, "CM_ATMAP")
    emis = {e for (e,) in _set(db, "CM_EMIS")}
    tkind = {e for (e,) in _set(db, "CM_TKIND")}
    ofor = [e for (e,) in _set(db, "CM_OFOR")]
    hists = [h for (h,) in _set(db, "CM_HISTS")]
    rebox = _set(db, "CM_REBOX")
    T = sorted((y for (y,) in db.q("select * from MILESTONYR")), key=_yv)
    M = {y: v for y, v in db.q("select * from M")}
    ys = sorted((y for (y,) in db.q("select * from ALLYEAR")), key=lambda y: (y == "0", _yv(y)))
    ypos = {y: i for i, y in enumerate(ys)}
    lag = lambda y, k: ys[ypos[y] - int(k)] if ypos[y] - int(k) >= 0 else None
    superyr = {(t, y) for t, y in _set(db, "SUPERYR")}
    tot = {k: v for k, v in _get(db, "L_VAR_CLITOT").items()}
    box = {k: v for k, v in _get(db, "L_VAR_CLIBOX").items()}
    mtot = _get(db, "M_EQ_CLITOT")
    mmax = _get(db, "M_EQ_CLIMAX")
    result, maxc_m = {}, {}
    led_years = [y for y in ys if led.get(y, 0) != 0]
    # --- MY_F = SUM(CM_BOXMAP('CO2-GTC',CM_VAR,CM_BOX)$CM_PHI('CO2-GTC',CM_BOX,'CO2-GTC'),CM_STAT0(CM_VAR,CM_BOX))/CM_CONST('CO2-PREIND');
    #     (CM_STAT0 of CM_VAR, the quantity: CO2-ATM, which has none: 0, as in TIMES)
    co2 = [(v, b) for a, v, b in boxmap if a == "CO2-GTC" and phi.get(("CO2-GTC", b, "CO2-GTC"), 0) != 0]
    my_f = sum(_n(stat0.get((v, b), 0.0)) for v, b in co2) / C("CO2-PREIND")
    # --- VALLVL = CM_CONST('GAMMA') / LOG(2);  Z = SMIN(T,M(T)-CM_CALIB)$CARD(VAR_CLIBOX);
    vallvl = C("GAMMA") / math.log(2)
    z = min(M[t] - calib for t in T) if box else 0.0
    # --- LOOP(LL$(Z$CM_LED(LL)), CNT = MAX(1,CM_LED(LL));
    #       ATTLVL = SUM(CM_BOXMAP('CO2-GTC',CM_VAR,CM_BOX)$CM_PHI('CO2-GTC',CM_BOX,'CO2-GTC'),VAR_CLIBOX.L(CM_VAR,CM_BOX,LL))/CM_CONST('CO2-PREIND');
    #       Z = (ATTLVL - MY_F) / CNT;
    #       FOR(F = 0 TO CNT-1, MY_ARRAY(LL-F) = VALLVL*LOG(ATTLVL-F*Z)+CM_EXOFORC(LL-F));
    #       MY_F = ATTLVL);
    arr = {}
    if z:
        for ll in led_years:
            cnt = max(1.0, _n(led[ll]))
            att = sum(_n(box.get((v, b, ll), 0.0)) for v, b in co2) / C("CO2-PREIND")
            z = (att - my_f) / cnt
            f = 0
            while f <= cnt - 1:
                y = lag(ll, f)
                if y is not None:
                    arr[y] = vallvl * math.log(att - f * z) + _n(exo.get(y, 0.0))
                f += 1
            my_f = att
    # --- CM_RESULT('FORC+CO2','CM-FORC',LL)$CM_LED(LL) = MY_ARRAY(LL)-CM_EXOFORC(LL);
    for ll in led_years:
        v = arr.get(ll, 0.0) - _n(exo.get(ll, 0.0))
        if v != 0:
            result[("FORC+CO2", "CM-FORC", ll)] = v

    def linf(e, y, quant):
        """CM_LINFOR(y,e,'FX') + CM_LINFOR(y,e,'N')/CM_PPM(e) * SUM(CM_BOXMAP(e,CM_VAR,CM_BOX)$CM_PHI(e,CM_BOX,e), quant(CM_VAR,CM_BOX))"""
        s = sum(quant(v, b) for a, v, b in boxmap if a == e and phi.get((e, b, e), 0) != 0)
        return _n(linfor.get((y, e, "FX"), 0.0)) + _n(linfor.get((y, e, "N"), 0.0)) / _n(ppm[e]) * s
    # --- Calculate radiative forcing from other emissions in each year
    #     LOOP(SUPERYR(T,LL)$CM_LED(LL), CM_RESULT(CM_OFOR,'CM-FORC',LL) =
    #       SUM(CM_FORCMAP(CM_OFOR,CM_EMIS),CM_LINFOR(LL,CM_EMIS,'FX')+CM_LINFOR(LL,CM_EMIS,'N')/CM_PPM(CM_EMIS)*
    #         SUM(CM_BOXMAP(CM_EMIS,CM_VAR,CM_BOX)$CM_PHI(CM_EMIS,CM_BOX,CM_EMIS),VAR_CLIBOX.L(CM_VAR,CM_BOX,LL))) +
    #       SUM(CM_FORCMAP(CM_TKIND(CM_OFOR),CM_VAR)$((NOT CM_EMIS(CM_VAR))$CM_TKIND(CM_VAR)),VAR_CLITOT.L(CM_OFOR,LL)));
    for t in T:
        for ll in led_years:
            if (t, ll) not in superyr:
                continue
            for o in ofor:
                v = sum(linf(e, ll, lambda a, b: _n(box.get((a, b, ll), 0.0))) for oo, e in fmap if oo == o and e in emis)
                if o in tkind:
                    v += sum(_n(tot.get((o, ll), 0.0)) for oo, x in fmap if oo == o and x not in emis and x in tkind)
                if v != 0:
                    result[(o, "CM-FORC", ll)] = v
                else:
                    result.pop((o, "CM-FORC", ll), None)
    # --- LOOP(MIYR_1(T), FIRST_VAL =
    #       SUM(CM_FORCMAP(CM_OFOR,CM_EMIS),CM_LINFOR(T,CM_EMIS,'FX')+CM_LINFOR(T,CM_EMIS,'N')/CM_PPM(CM_EMIS)*
    #         SUM(CM_BOXMAP(CM_EMIS,CM_VAR,CM_BOX)$CM_PHI(CM_EMIS,CM_BOX,CM_EMIS),CM_STAT0(CM_VAR,CM_BOX))) +
    #       SUM(CM_FORCMAP(CM_TKIND,CM_VAR)$((NOT CM_EMIS(CM_VAR))$CM_TKIND(CM_VAR)),VAR_CLITOT.L(CM_TKIND,T)));
    t1 = T[0]
    of = set(ofor)
    first = sum(linf(e, t1, lambda a, b: _n(stat0.get((a, b), 0.0))) for o, e in fmap if o in of and e in emis)
    first += sum(_n(tot.get((k, t1), 0.0)) for k, x in fmap if k in tkind and x not in emis and x in tkind)
    # --- LOOP(LL$CM_LED(LL), CNT = MAX(1,CM_LED(LL));
    #       LAST_VAL = SUM(CM_FORCMAP(CM_OFOR,CM_TKIND(CM_VAR)),CM_RESULT(CM_OFOR,'CM-FORC',LL));
    #       FOR(F = 0 TO CNT-1, MY_F = F/CNT; MY_FIL2(LL-F) = MY_F*FIRST_VAL+(1-MY_F)*LAST_VAL);
    #       FIRST_VAL = LAST_VAL);
    #     MY_ARRAY(LL)$MY_ARRAY(LL) = MY_ARRAY(LL) + MY_FIL2(LL);
    fil2 = {}
    for ll in led_years:
        cnt = max(1.0, _n(led[ll]))
        last = sum(result.get((o, "CM-FORC", ll), 0.0) for o, x in fmap if o in of and x in tkind)
        f = 0
        while f <= cnt - 1:
            y = lag(ll, f)
            if y is not None:
                fil2[y] = f / cnt * first + (1 - f / cnt) * last
            f += 1
        first = last
    for y in list(arr):
        if arr[y] != 0:
            arr[y] += fil2.get(y, 0.0)
    # --- CM_DT_FORC(LL) = MY_ARRAY(LL);
    # --- LOOP((CM_VAR('FORCING'),LL)$CM_LED(LL), Z = CM_LED(LL);
    #       OPTION CLEAR=CM_RR;  CM_RR('1',CM_BUCK,CM_BOX) = DIAG(CM_BUCK,CM_BOX);
    #       FOR(F = 0 TO Z-1,
    #         CM_RR('2',CM_BOX,'LO') = CM_RR('2',CM_BOX,'LO') + MY_ARRAY(LL-F)*CM_RR('1',CM_BOX,'ATM');
    #         CM_RR('1',CM_BUCK,CM_BOX) = SUM(CM_Q$CM_BOX(CM_Q),CM_RR('1',CM_BUCK,CM_Q)*CM_SIG(SOW,CM_Q,CM_BOX)));
    #       CM_DELTAT(LL,CM_BOX) = CM_RR('1',CM_BOX,'ATM') * CM_DELTAT(LL-CM_LED(LL),'ATM') + CM_RR('1',CM_BOX,'LO') * CM_DELTAT(LL-CM_LED(LL),'LO') +
    #         CM_RR('2',CM_BOX,'LO') * CM_SIG1(SOW) + (CM_RR('1',CM_BOX,'ATM') * CM_STAT0('FORCING','ATM') +
    #         CM_RR('1',CM_BOX,'LO') * CM_STAT0('FORCING','LO'))$MIYR_1(LL));
    m = {(i, j): _n(v) for (w, i, j), v in sig.items() if w == "1"}
    s1 = _n(sig1.get("1", 0.0))
    deltat = {}
    if "FORCING" in hists:
        for ll in led_years:
            zz = _n(led[ll])
            r1 = {(b, b): 1.0 for b in BOXES}
            r2 = {}
            f = 0
            while f <= zz - 1:
                y = lag(ll, f)
                a = arr.get(y, 0.0) if y is not None else 0.0
                for b in BOXES:
                    r2[b] = r2.get(b, 0.0) + a * r1.get((b, "ATM"), 0.0)
                r1 = {(i, k): sum(r1.get((i, j), 0.0) * m.get((j, k), 0.0) for j in BOXES) for i in BOXES for k in BOXES}
                f += 1
            p = lag(ll, zz)
            for b in BOXES:
                v = (r1.get((b, "ATM"), 0.0) * deltat.get((p, "ATM"), 0.0) + r1.get((b, "LO"), 0.0) * deltat.get((p, "LO"), 0.0)
                     + r2.get(b, 0.0) * s1)
                if ll == t1:
                    v += r1.get((b, "ATM"), 0.0) * _n(stat0.get(("FORCING", "ATM"), 0.0)) + r1.get((b, "LO"), 0.0) * _n(stat0.get(("FORCING", "LO"), 0.0))
                if v != 0:
                    deltat[(ll, b)] = v
                else:
                    deltat.pop((ll, b), None)
    # --- Shadow price of total and maximum constraints
    #     CM_MAXC_M(CM_VAR,T) $= ABS(EQ_CLITOT.M(CM_VAR,T,T));
    #     CM_MAXC_M(CM_VAR,LL) $= MAX(CM_MAXC_M(CM_VAR,LL),ABS(EQ_CLIMAX.M(LL,CM_VAR)))$EQ_CLIMAX.M(LL,CM_VAR);
    hs = set(hists)
    for (v, t, ll), x in mtot.items():
        if v in hs and t == ll and t in M and x != 0:
            maxc_m[(v, t)] = abs(x)
    for (ll, v), x in mmax.items():
        if v in hs and x != 0:
            maxc_m[(v, ll)] = max(maxc_m.get((v, ll), 0.0), abs(x))
    # --- Collect all basic results
    #     CM_RESULT(CM_VAR,'CM-EMIS',LL)$CM_EMIS(CM_VAR) $= VAR_CLITOT.L(CM_VAR,LL);
    #     CM_RESULT(CM_VAR,'CM-FORC',LL)$(NOT CM_EMIS(CM_VAR)) $= VAR_CLITOT.L(CM_VAR,LL);
    #     CM_RESULT(CM_VAR,CM_Q,LL) $= SUM(CM_REBOX(CM_Q,CM_BOX),VAR_CLIBOX.L(CM_VAR,CM_BOX,LL));
    for (v, ll), x in tot.items():
        if v in hs and x != 0:
            result[(v, "CM-EMIS" if v in emis else "CM-FORC", ll)] = x
    for (v, b, ll), x in box.items():
        if v not in hs:
            continue
        for q, bb in rebox:
            if bb == b and x != 0:
                result[(v, q, ll)] = x
    #     LOOP(CM_ATMAP(CM_EMIS,CM_HISTS), CM_RESULT(CM_HISTS,'CM-PPX',LL)$CM_LED(LL) =
    #       SUM(CM_BOXMAP(CM_EMIS,CM_VAR,CM_BOX)$CM_PHI(CM_EMIS,CM_BOX,CM_EMIS),VAR_CLIBOX.L(CM_VAR,CM_BOX,LL))/CM_PPM(CM_EMIS));
    for e, h in atmap:
        if e not in emis or h not in hs:
            continue
        for ll in led_years:
            v = sum(_n(box.get((a, b, ll), 0.0)) for x, a, b in boxmap if x == e and phi.get((e, b, e), 0) != 0) / _n(ppm[e])
            if v != 0:
                result[(h, "CM-PPX", ll)] = v
            else:
                result.pop((h, "CM-PPX", ll), None)
    #     CM_RESULT('FORC+TOT','CM-FORC',LL)$CM_LED(LL) $= CM_DT_FORC(LL);
    #     CM_RESULT('DELTA+ATM','CM-DT',LL) $= CM_DELTAT(LL,'ATM');  CM_RESULT('DELTA+LO','CM-DT',LL) $= CM_DELTAT(LL,'LO');
    for ll in led_years:
        if arr.get(ll, 0) != 0:
            result[("FORC+TOT", "CM-FORC", ll)] = arr[ll]
    for (ll, b), v in deltat.items():
        if b in ("ATM", "LO"):
            result[("DELTA+" + b, "CM-DT", ll)] = v
    for name, d, dom in (("CM_RESULT", result, ["ITEM", "ITEM", "ALLYEAR"]), ("CM_MAXC_M", maxc_m, ["ITEM", "ALLYEAR"])):
        db.declare(name, "par", dom)
        db.clear(name)
        db.load_rows(name, [k + (0.0 if abs(v) < 1e-200 else v,) for k, v in sorted(d.items())])
    return ["CM_RESULT", "CM_MAXC_M"]
