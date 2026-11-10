# SPDX-License-Identifier: GPL-3.0-or-later
"""Inter-/extrapolation kernels: fillparm.gms, prepparm.gms (filparam.gms: see fill_simple).

The kernels work one data series at a time, exactly as the GAMS loops do.
EPS is carried as a tiny number inside the kernels so that GAMS arithmetic
(EPS + x = x, EPS stays EPS) is reproduced; on output it is stored as 0 (= EPS row).
"""
from __future__ import annotations
import math, time
import pandas as pd
from .engine import DB
from . import kernels

EPS = 1e-300
TINY = 1e-200


def _rd(x):
    """GAMS ROUND(): half away from zero."""
    return float(math.floor(abs(x) + 0.5) * (1 if x >= 0 else -1))


def _targets(db, which):
    tab = {"V": "MODLYEAR", "T": "MILESTONYR", "MILESTONYR": "MILESTONYR", "PASTMILE": "PASTMILE", "EOHYEARS": "EOHYEARS"}[which]
    return [int(y) for (y,) in db.q(f'select y from "{tab}" where y <> \'0\' order by yv(y)')]


class _Each:
    """The years of one series for which the control condition holds, tested with `t in`: a call per test."""
    __slots__ = ("f", "k")

    def __init__(self, f, k):
        self.f, self.k = f, k

    def __contains__(self, t):
        return self.f(self.k, t)


class _All:
    __slots__ = ()

    def __contains__(self, t):
        return True


_ALL = _All()


def _ctrl(db, spec, cols):
    """Control condition %6 -> function(key_tuple) -> the years of that series for which it holds (`t in` tests).

    Looked up once per series; for a control set such as RTP the result is the set of its years for (r, p)."""
    if spec is None:
        return lambda k: _ALL
    if callable(spec):
        f = spec(db, cols)
        return lambda k: _Each(f, k)
    tab, kc = spec                       # e.g. ("RTP", ("r","p")) : RTP(r, year, p)
    # (r, p) -> the years, as integers, for which RTP(r, year, p) holds; a label that is not the plain text of an
    # integer could never equal str(year) and is left out, so the test is the same as (r, str(year), p) in RTP
    # built once per content of the control set: preppm tests the same RTP in many calls; the cache is keyed on the
    # number of records and an order-independent hash of them, so a control set that changed is read again
    sig = db.q(f'select count(*), sum(hash(r, y, p)) from "{tab}"')[0]
    cache = db.__dict__.setdefault("_interp_ctrl", {})
    hit = cache.get(tab)
    if hit is not None and hit[0] == sig:
        years = hit[1]
    else:
        years = {(r, p): set(ys) for r, p, ys in db.q(
            f'select r, p, list(try_cast(y as bigint)) from "{tab}" '
            f'where cast(try_cast(y as bigint) as varchar) = y group by r, p')}
        cache[tab] = (sig, years)
    ir, ip = cols.index(kc[0]), cols.index(kc[1])
    none = frozenset()
    return lambda k: years.get((k[ir], k[ip]), none)


def _load(db, name, drop_n=False):
    """The records of a parameter grouped into series: (cols, {key: [(year label, value), ...]}).

    One pass over the rows as DuckDB returns them: the series in the order of their first record and the records of a
    series in table order, as pandas groupby(sort=False) gave them, without a DataFrame per series. A key with a NULL
    label is left out (groupby drops it). drop_n: leave out the records with l = 'N' (the BD parameters)."""
    sy = db.sym[name]
    cols = [c for c in sy.cols if c != "y"]
    rows = db.x(f'select {", ".join(cols)}{"," if cols else ""} y, value from "{name}"').fetchall()
    n = len(cols)
    il = cols.index("l") if drop_n and "l" in cols else None
    groups = {}
    for row in rows:
        k = row[:n]
        if None in k or (il is not None and k[il] == "N"):
            continue
        v = row[n + 1]
        g = groups.get(k)
        if g is None:
            groups[k] = g = []
        g.append((row[n], float("nan") if v is None else v))
    return cols, groups


def _series(groups, dmyear, datayear):
    """Yield (key, option, points, has_data) per series; points sorted by year over DM_YEAR."""
    for key, g in groups.items():
        opt = None
        pts = []
        has = False
        for y, v in g:
            if y == "0":
                opt = EPS if v == 0 else v
                # DATAYEAR holds the year 0 while preppm.mod interpolates (lines 19 and 242): a series with an option and no
                # data is taken, and an option 2 gives EPS in every target year (fillparm.gms, FIRST_VAL = LAST_VAL = EPS)
                if y in datayear:
                    has = True
                continue
            if y in datayear:
                has = True
            if y in dmyear:
                pts.append((int(y), EPS if v == 0 else v))
        pts.sort()
        yield key, opt, pts, has


def _write(db, name, cols, upserts, deletes=()):
    """upserts: list of key+(year,value); value tiny -> EPS row; exact zeros must not be passed."""
    sy = db.sym[name]
    allc = cols + ["y", "value"]
    if deletes:
        d = pd.DataFrame(list(deletes), columns=cols + ["y"])
        d["y"] = d["y"].astype(str)
        db.con.register("d_", d)
        cond = " and ".join(f"d_.{c}=a.{c}" for c in cols + ["y"])
        db.x(f'delete from "{name}" a where exists(select 1 from d_ where {cond})')
        db.con.unregister("d_")
    if upserts:
        u = pd.DataFrame(list(upserts), columns=allc)
        u["y"] = u["y"].astype(str)
        u["value"] = u["value"].where(u["value"].abs() > TINY, 0.0)
        db.con.register("u_", u)
        db.put(name, f'select {", ".join(sy.cols)}, value from u_ where in_ALLYEAR(y)', zero="eps")
        db.con.unregister("u_")


def _yearsets(db):
    dm = set(y for (y,) in db.q("select y from DM_YEAR"))
    dy = set(y for (y,) in db.q("select y from DATAYEAR"))
    return dm, dy


# ---------------------------------------------------------------------------
def filparam(db: DB, name, target, default=None, bext=True):
    """filparam.gms : dense inter-/extrapolation (source years: all years; no control sets, no qualifiers).

    default : GAMS arg %9, the option used when the series has none on year 0
    bext    : False for the qualifier 'NO$' as %7 (no backward extrapolation: MULTI, ppmain.mod 634)
    """
    name = name.upper()
    if db.card(name) == 0:
        return
    cols, groups = _load(db, name)
    tg = _targets(db, target)
    ups, dels = [], []
    for key, g in groups.items():
        rec = {y: (EPS if v == 0 else v) for y, v in g}
        # --- F=0; Z=INF; MY_FYEAR=9999; DFUNC = ROUND(SRC('0')); IF(NOT DFUNC, DFUNC = %9);
        F = 0.0; Z = math.inf; MYFY = 9999; FIRST = 0.0; LAST = 0.0
        DF = _rd(rec.get("0", 0.0)) or (default or 0.0)
        if DF < 0:
            continue
        for Zy, MY_F in sorted((int(y), v) for y, v in rec.items() if y != "0"):
            Z = Zy
            if Z > MYFY + 1:                                    # linear interpolation
                for t in tg:
                    if MYFY < t < Z:
                        v = LAST + (MY_F - LAST) / (Z - MYFY) * (t - MYFY)
                        (ups if v != 0 else dels).append(key + ((t, v) if v != 0 else (t,)))
            elif Z < MYFY:
                F = Z; FIRST = MY_F
            LAST = MY_F; MYFY = Z
        if DF > 1:
            DF = DF % 10
            if DF == 2:
                FIRST = EPS; LAST = EPS
            elif DF == 4:
                Z = math.inf
            elif DF == 5:
                F = 0
        if DF != 1:
            for t in tg:
                v = (FIRST if bext and t < F else 0.0) + (LAST if t > Z else 0.0)
                if v != 0:
                    ups.append(key + (t, v))
    _write(db, name, cols, ups, dels)


# ---------------------------------------------------------------------------
def _ge0(d):
    return d >= 0


_ge0.kernel_thr = 0.0                       # the kernel's form of this test: option >= 0


class KeyCond:
    """A test on the option code and the series' key for fillparm (keycond=True): option >= thr and the label in
    column `col` in the set `inset`. `sql` is the same key test on the parameter's rows, for the kernel."""

    def __init__(self, thr, col, inset, sql):
        self.thr, self.col, self.inset, self.sql = thr, col, inset, sql

    def __call__(self, d, k):
        return d >= self.thr and k[self.col] in self.inset


class KeyThr:
    """A test on the option code whose threshold depends on the series' key (keycond=True): option >= thr_key when the
    label in column `col` is in the set `inset`, else option >= thr (GAMS 'GE -1$ACTCG(CG)'). `sql` is the same key
    test on the parameter's rows, for the kernel."""

    def __init__(self, thr, thr_key, col, inset, sql):
        self.thr, self.thr_key, self.col, self.inset, self.sql = thr, thr_key, col, inset, sql

    def __call__(self, d, k):
        return d >= (self.thr_key if k[self.col] in self.inset else self.thr)


def fillparm(db: DB, name, target, ctrl, cond=_ge0, x=False, keycond=False):
    """fillparm.gms : standard inter-/extrapolation of non-cost parameters.

    target : 'V' (MODLYEAR) or 'T' (MILESTONYR)      - GAMS arg %5
    ctrl   : control condition for extrapolation       - GAMS arg %6
    cond   : test on the option code                   - GAMS arg %7 ('GE 0'); with keycond=True it is called
             as cond(option, {column: label}) for tests that depend on the series
    x      : True when GAMS passes a work table (%8): interpolated values are then
             also subject to `ctrl`

    With TIMESPP_KERNELS=fillparm the Julia kernel (jlkernels/src/fillparm.jl) computes the same result; this
    Python code is its reference (kernels.py).
    """
    name = name.upper()
    if db.s.get("G_NOINTERP") or db.card(name) == 0:
        return
    if kernels.mode("fillparm") == "off":
        return _fillparm(db, name, target, ctrl, cond, x, keycond)
    kernels.run("fillparm", db, [name], lambda: _fillparm(db, name, target, ctrl, cond, x, keycond),
                lambda: _fillparm_kernel(db, name, target, ctrl, cond, x, keycond))


def _fillparm(db: DB, name, target, ctrl, cond, x, keycond):
    cols, groups = _load(db, name)
    dm, dy = _yearsets(db)
    tg = _targets(db, target)
    ok = _ctrl(db, ctrl, cols)
    ups, dels = [], []
    for key, opt, pts, has in _series(groups, dm, dy):
        okr = ok(key)                              # the years the control condition allows
        if not has:
            continue
        DF = _rd(opt) if opt is not None else 0.0
        if not (cond(DF, dict(zip(cols, key))) if keycond else cond(DF)):
            continue
        CNT = DF <= 999
        LAST = 0.0; F = 0.0; Z = 0.0; FIRST = 0.0; MYFY = 0.0
        item = {}
        for Zy, MY_F in pts:
            if LAST != 0:
                if CNT or Zy <= DF:
                    for t in tg:
                        if MYFY < t < Zy:
                            item[t] = LAST + (MY_F - LAST) / (Zy - MYFY) * (t - MYFY)
                else:
                    for t in tg:
                        if MYFY < t < Zy:
                            item[t] = LAST * (1 + MY_F) ** (t - MYFY) + EPS
                    MY_F = LAST * (1 + MY_F) ** (Zy - MYFY) + EPS
                    ups.append(key + (Zy, MY_F))                 # overwrite old data
            else:
                F = Zy; FIRST = MY_F
            LAST = MY_F; MYFY = Zy; Z = Zy
        if DF > 1 and CNT:
            DF = DF % 10
            if DF == 2:
                FIRST = EPS; LAST = EPS
            elif DF == 4:
                Z = math.inf
            elif DF == 5:
                F = 0
        if not x:
            for t, v in item.items():                            # '=' assignment
                (ups if v != 0 else dels).append(key + ((t, v) if v != 0 else (t,)))
            if DF != 1:
                for t in tg:                                     # (the control test, a pure lookup, last)
                    v = (FIRST if t < F else 0.0) + (LAST if t > Z else 0.0)
                    if v != 0 and t in okr:
                        ups.append(key + (t, v))
        else:
            for t in tg:
                v = item.get(t, 0.0)
                if DF != 1:
                    v = (FIRST if t < F else 0.0) + v + (LAST if t > Z else 0.0)
                if v != 0 and t in okr:
                    ups.append(key + (t, v))
    _write(db, name, cols, ups, dels)
    # --- %1(%2,'0',%3)$%1(%2,'0',%3) = MIN(%RESET%,%1(%2,'0',%3));     (RESET = 0)
    db.x(f'delete from "{name}" where y=\'0\' and value >= 0')


def _kernel_ctrl(db, ctrl, cols, tg):
    """The control condition for the kernel: [nalt, ia1, ib1, ...] and three columns (a, b, year) per alternative.
    A table spec (CTRL, (ca, cb)): CTRL(key[ca], year, key[cb]), the years read as _ctrl reads them; a function
    with `kernel_alts` [(CTRL, ca, cb), ...]: any of them; a function marked `key_free`: the years it allows,
    whatever the series (it is asked for each target year). Any other function: the kernel declines."""
    import numpy as np
    if ctrl is None:
        return np.array([-1], np.int32), []
    if callable(ctrl):
        if getattr(ctrl, "key_free", False):
            f = ctrl(db, cols)
            ys = np.array([t for t in tg if f(None, t)], np.int32)
            return np.array([1, 0, 0], np.int32), [np.empty(0, np.int32), np.empty(0, np.int32), ys]
        alts = getattr(ctrl, "kernel_alts", None)
        if alts is None:
            raise kernels.Decline(f"control condition {ctrl.__name__}")
    else:
        tab, (ca, cb) = ctrl
        alts = [(tab, ca, cb)]
    L = kernels.labels(db)
    cache = db._kernels["ctrl"]
    meta, cols_out = [len(alts)], []
    for tab, ca, cb in alts:
        meta += [cols.index(ca) + 1, cols.index(cb) + 1]
        t = time.perf_counter()
        sig = db.q(f'select count(*), sum(hash(r, y, p)) from "{tab}"')[0]
        hit = cache.get(tab)
        if hit is None or hit[0] != sig:
            L.add(f'select r from "{tab}" union all select p from "{tab}"')
            r = db.con.execute(f"""select ka.code as a, kb.code as b, cast(try_cast(c.y as bigint) as INTEGER) as y
                                   from "{tab}" c join __klab ka on ka.label = c.r join __klab kb on kb.label = c.p
                                   where cast(try_cast(c.y as bigint) as varchar) = c.y""").fetchnumpy()
            hit = cache[tab] = (sig, [np.asarray(r["a"], np.int32), np.asarray(r["b"], np.int32),
                                      np.asarray(r["y"], np.int32)])
            kernels.tally("fillparm", "duckdb -> julia", time.perf_counter() - t, len(hit[1][0]))
        else:
            kernels.tally("fillparm", "duckdb -> julia", time.perf_counter() - t)
        cols_out += hit[1]
    return np.array(meta, np.int32), cols_out


def _fillparm_kernel(db: DB, name, target, ctrl, cond, x, keycond):
    """fillparm in Julia (jlkernels/src/fillparm.jl): the rows _fillparm writes, to the bit."""
    import numpy as np
    K = "fillparm"
    thrk, must = None, True
    if keycond:
        if isinstance(cond, KeyThr):                         # the threshold by the key test, which is not required
            thrk, must = cond.thr_key, False
        elif not isinstance(cond, KeyCond):
            raise kernels.Decline("option test that depends on the series")
        thr, keysql = cond.thr, cond.sql
    else:
        thr, keysql = getattr(cond, "kernel_thr", None), None
        if thr is None:
            raise kernels.Decline("option test")
    sy = db.sym[name]
    cols = [c for c in sy.cols if c != "y"]
    nk = len(cols)
    tg = _targets(db, target)
    ctl, alts = _kernel_ctrl(db, ctrl, cols, tg)
    # --- the records as codes, in table order (_load: a key with a NULL label is left out)
    flags = ("(case when f.y = '0' then 1 else 0 end) + (case when f.y in (select y from DATAYEAR) then 2 else 0 end)"
             " + (case when f.y in (select y from DM_YEAR) then 4 else 0 end)"
             + (f" + (case when {keysql} then 8 else 0 end)" if keysql else ""))
    yint = "try_cast(f.y as INTEGER)"
    dm = "coalesce(f.y in (select y from DM_YEAR), false)"
    r = kernels.to_julia(db, K, name, cols, f"""
        case when {dm} then coalesce({yint}, 0) else 0 end as yint, cast({flags} as UTINYINT) as flags,
        coalesce(f.value, 'nan'::DOUBLE) as value,
        {dm} and coalesce(cast({yint} as varchar) <> f.y, true) as bad""")
    if r["bad"].any():
        raise kernels.Decline("a year of DM_YEAR that is not the text of an integer")
    # --- the kernel
    par = np.array([nk, 1.0 if x else 0.0, thr, 1.0 if keysql and must else 0.0] + ([thrk] if thrk is not None else []),
                   np.float64)
    out = kernels.call(K, [par] + [np.asarray(r[f"c{i}"], np.int32) for i in range(nk)]
                       + [np.asarray(r["yint"], np.int32), np.asarray(r["flags"], np.uint8),
                          np.asarray(r["value"], np.float64), np.array(tg, np.int32), ctl] + alts)
    # --- back into DuckDB, as _write does (the deletes, then the upserts with EPS rows), then the option records
    t = time.perf_counter()
    ups, uy, uv = out[:nk], out[nk], out[nk + 1]
    dls, dy = out[nk + 2:2 * nk + 2], out[2 * nk + 2]
    if len(dy):
        rel = kernels.from_julia(db, "d_", cols, dls, {"y": dy}, "cast(f.y as VARCHAR) as y")
        on = " and ".join(f"d_.{c}=a.{c}" for c in cols + ["y"])
        db.x(f'delete from "{name}" a where exists(select 1 from {rel} d_ where {on})')
        db.con.unregister("d_")
    if len(uy):
        rel = kernels.from_julia(db, "u_", cols, ups, {"y": uy, "value": uv}, "cast(f.y as VARCHAR) as y, f.value")
        db.put(name, f'select {", ".join(sy.cols)}, value from {rel} u_ where in_ALLYEAR(y)', zero="eps")
        db.con.unregister("u_")
    kernels.tally(K, "julia -> duckdb", time.perf_counter() - t, len(uy) + len(dy))
    # --- %1(%2,'0',%3)$%1(%2,'0',%3) = MIN(%RESET%,%1(%2,'0',%3));     (RESET = 0)
    db.x(f'delete from "{name}" where y=\'0\' and value >= 0')


# ---------------------------------------------------------------------------
# the parameters that preppm.mod interpolates over BD (bound types LO, FX, UP) rather than LIM (which adds N)
BD_PARAMS = {"FLO_MARK", "PRC_MARK", "CAP_BND", "NCAP_BND", "COM_BNDNET", "COM_BNDPRD", "ACT_BND", "FLO_BND", "FLO_BDLVL",
             "FLO_SHAR", "IRE_BND", "IRE_XBND", "STGIN_BND", "STGOUT_BND", "REG_BNDCST", "PRC_DYNUC", "BS_BNDPRS"}


def prepparm(db: DB, name, target, ctrl, typ, def_iebd=10, x=False, plus=False, fn=None, reset=0):
    """prepparm.gms : inter-/extrapolation of cost parameters (typ=0) and bounds (typ=1).

    typ      : GAMS arg %7  (0 = costs: only series with an explicit option; 1 = bounds)
    def_iebd : GAMS arg %8  default option for bounds (10 = migrate within period only)
    plus     : GAMS arg %10 == '+'  (leave option records in place)
    fn       : GAMS arg %10 function applied to the option, e.g. -ABS
    """
    name = name.upper()
    s = db.s
    if s.get("G_NOINTERP"):
        db.x(f"delete from INT_DEFAULT where u='{name}'")
        return
    if db.card(name) == 0:
        return
    # interpolated over BD (LO, FX, UP): records of type N stay as given
    cols, groups = _load(db, name, drop_n=name in BD_PARAMS)
    dm, dy = _yearsets(db)
    tg = _targets(db, target)
    tgset = set(tg)
    ok = _ctrl(db, ctrl, cols)
    ie = db.q1(f"select count(*) from IE_DEFAULT where u='{name}'")
    CNT0 = (def_iebd + ((3 - def_iebd) if ie else 0)) if typ else 0
    fil2 = {int(y): v for y, v in db.q("select y, value from FIL2")}          # year -> milestone of its period
    myfil = sorted(int(y) for (y,) in db.q("select y from MY_FIL"))
    t1 = int(db.q1("select y from MIYR_1"))
    ups, dels = [], []
    for key, opt, pts, has in _series(groups, dm, dy):
        okr = ok(key)                              # the years the control condition allows
        o = 0.0 if opt is None else (0.0 if abs(opt) < TINY else opt)
        if CNT0 == 0:
            if not (o > 0):
                continue
        else:
            if o == -13:
                # --- UNCD7(%2,%5,%3%4)$(%1(%2,'0',%3)=-13) $= %1(%2,%5,%3);  %1(%2,%5,%3)$UNCD7(%2,%5,%3%4) = 0;
                #     (bounds only, %7 not 0): the values given on the target years are removed; whether the series is
                #     interpolated afterwards is the usual test below, which -13 fails unless %10 turns it positive
                dels.extend(key + (str(t),) for t, v in pts if t in tgset)
                pts = [(t, v) for t, v in pts if t not in tgset]
            oo = fn(o) if fn else o
            if not (oo > -0.5):
                continue
        DF = float(CNT0)                       # DFUNC = CNT; DFUNC $= ROUND(option);
        if opt is not None:
            if abs(opt) >= TINY and _rd(o) != 0:    # an EPS option leaves the default: DFUNC $= ROUND(EPS) assigns nothing
                DF = _rd(o)                         # (RCAP_BND with only an EPS on year 0 gives no bounds)
        if DF == 10 and not typ:
            raise NotImplementedError(f"{name}: option 10 on a cost parameter")
        arr = dict(pts)
        f2 = {}
        LAST = 0.0; F = 0.0; Z = 0.0; FIRST = 0.0; MYFY = 0.0
        if DF != 10:
            for Zy, MY_F in pts:
                if LAST != 0:
                    if Zy > DF and DF > 999:
                        for t in tg:
                            if MYFY < t < Zy:
                                f2[t] = LAST * (1 + MY_F) ** (t - MYFY) + EPS
                        MY_F = LAST * (1 + MY_F) ** (Zy - MYFY) + EPS
                        f2[Zy] = MY_F
                    else:
                        for t in tg:
                            if MYFY < t < Zy:
                                f2[t] = LAST + (MY_F - LAST) / (Zy - MYFY) * (t - MYFY)
                else:
                    F = Zy; FIRST = MY_F
                LAST = MY_F; MYFY = Zy; Z = Zy
        elif typ:
            # intra-period I/E: values given on non-milestone years move to the period's milestone year
            FIRST = 0.0; MYFY = 0.0
            for y in myfil:
                if y not in arr:
                    continue
                MY_F = arr[y]; Z = y; F = fil2[y]
                if MYFY < F:
                    if F > min(FIRST, Z):
                        LAST = MY_F; FIRST = F
                    tt = int(F)
                    if tt in tgset and tt not in arr:
                        f2[tt] = LAST + (MY_F - LAST) / (Z - MYFY) * (F - MYFY)
                LAST = MY_F; MYFY = Z
            DF = float(typ)
        if typ and math.floor(DF / 10) == 1:
            MYF = fil2.get(int(F), 0.0)
            if F and MYF and MYF < F and int(MYF) in tgset:
                f2[int(MYF)] = FIRST
            MYF = fil2.get(int(Z), 0.0) if Z != math.inf else 0.0
            if MYF > Z and int(MYF) in tgset:
                f2[int(MYF)] = LAST
            DF = DF - 10
        if DF != typ:
            if DF <= 2:
                for t in tg:
                    if t not in f2 and t not in arr and t in okr:
                        f2[t] = EPS
            else:
                if DF == 4:
                    Z = math.inf
                elif DF == 5:
                    F = 0
                for t in tg:
                    v = (FIRST if t < F else 0.0) + (LAST if t > Z else 0.0)
                    if v != 0 and t in okr:
                        f2[t] = v
                if (not typ) and LAST != 0:
                    for t in tg:
                        if t not in f2 and t not in arr and t in okr:
                            f2[t] = EPS
        for t, v in f2.items():
            if v == 0 or t not in tgset:
                continue
            if x and t not in okr:
                continue
            ups.append(key + (t, v))
    _write(db, name, cols, ups, dels)
    # --- %1(%2,'0',%3)$(MAX(0,%1(%2,'0',%3)-MAX(%7,%RESET%))$%1(%2,'0',%3)) = %RESET%;
    #     (with $SET RESET 1 the option record is set to 1 instead of removed)
    if not plus:
        bdonly = " and l <> 'N'" if name in BD_PARAMS and "l" in cols else ""
        if reset:
            db.x(f'update "{name}" set value = {reset} where y=\'0\' and value - {max(typ, reset)} > 0{bdonly}')
        else:
            db.x(f'delete from "{name}" where y=\'0\' and value - {max(typ, 0)} > 0{bdonly}')
    db.x(f"""delete from "{name}" where y='EMPTY'""")
