# SPDX-License-Identifier: GPL-3.0-or-later
"""Timeslice levelling kernels (pp_lvlfc.mod, pp_lvlbr.mod, pp_lvlbd.mod, ...).

A value given on a timeslice other than those where the model needs it is moved there:
aggregated from finer timeslices (weighted by year fraction, or summed) or inherited from
the nearest coarser timeslice.  Work is done series by series in Python; EPS (explicit zero)
is carried as a tiny number so that it survives sums and products as in GAMS.
"""
from collections import defaultdict

from .engine import DB

TINY = 1e-300


def _in(v):
    return TINY if v == 0 else v


def _out(v):
    return 0.0 if abs(v) < 1e-200 else v


class Tree:
    """Timeslice tree of one region."""

    def __init__(self, db: DB, r):
        self.g = {s: v for s, v in db.q(f"select s, value from G_YRFR where r='{r}'")}
        self.parent = {c: p for p, c in db.q(f"select s, s2 from RS_BELOW1 where r='{r}'")}
        self.all = [s for (s,) in db.q(f"select s from TS_GROUP g where r='{r}' order by ord_tsl(tsl), ord_s(s)")]
        self.level = {s: l for s, l in db.q(f"select s, tsl from TS_GROUP where r='{r}'")}
        self.finest = {s for (s,) in db.q(f"select s from FINEST where r='{r}'")}
        # a timeslice outside the tree (G_YRFR given as 0 or negative: timslice.mod 50-56 take it out of TS_GROUP,
        # TS_MAP and RS_BELOW) has no relations, as the empty RS_BELOW / RS_TREE of GAMS's loops
        self.anc = defaultdict(list)
        for s in self.all:
            a, x = [], s
            while x in self.parent:
                x = self.parent[x]
                a.append(x)
            self.anc[s] = a                      # nearest first
        self.below = defaultdict(list, {s: [t for t in self.all if s in self.anc[t]] for s in self.all})
        self.leaves = defaultdict(list, {s: [t for t in [s] + self.below[s] if t in self.finest] for s in self.all})


def trees(db: DB):
    if not hasattr(db, "_trees"):
        db._trees = {r: Tree(db, r) for (r,) in db.q("select r from REG")}
    return db._trees


def nearest(tree: Tree, arr, s):
    """Value on s, or on the nearest coarser timeslice that has one: (value, source timeslice)."""
    if s in arr:
        return arr[s], s
    for u in tree.anc[s]:
        if u in arr:
            return arr[u], u
    return None, None


def lvlfc(db: DB, name, ent, ctl, years=None, cond="true", weighted=False, fill=None, take=None, all_ts=False, flag_n=False,
          dom=None):
    """pp_lvlfc.mod.

    name     parameter %1, indexed (R[,year],entity..,[extra..],S,tail..)
    ent      columns of `name` that, with r and s, index the control set %3        (%2)
    ctl      control set %3(R,entity..,S): the timeslices where values are needed
    years    set restricting the year index (%7); None if the parameter has no year or all years
    cond     SQL condition on a row `a` of the parameter (%8)
    weighted %9 = 1: quantities (summed when aggregated, split by year fraction when inherited)
    fill     %11: None | '0' (fill remaining control timeslices from ANNUAL) | '1' | 'N'
             any value also removes what is left on timeslices outside the control set
    take     %12: extra SQL condition on a row
    all_ts   %6 = S2: every series is processed, not only those with values off the control set
    dom      SQL condition on a row `a`: the domain of the tail indexes %4 (e.g. BD of ',BD'); rows outside it are
             not read, flagged or removed
    """
    cols = db.cols(name)
    key = [c for c in cols if c != "s"]
    ks = ", ".join(f"a.{c}" for c in key)
    yc = "y" if "y" in cols else None
    ysel = f"and in_{years}(a.y)" if (years and yc) else ""
    ctl_of = lambda al: f"in_{ctl}({al}.r, " + ", ".join(f"{al}.{c}" for c in ent) + f", {al}.s)"
    if not db.card(name):
        return
    tk = f"and ({take})" if take else ""
    dm = f"and ({dom})" if dom else ""
    if fill == "N":
        # --- %1(R,LL--ORD(LL),%2%10,S+STOA(S)%4)$(STOAL(R,S)$%1(R,LL,%2%10,S%4)) = 1;   flag series given below ANNUAL
        sel = ", ".join("'0' as y" if c == "y" else f"a.{c}" for c in key)
        db.put(name, f"select distinct {sel}, 'ANNUAL' as s, 1 as value from \"{name}\" a where v_STOAL(a.r,a.s) <> 0 and in_REG(a.r) {dm}")
        flag = " and ".join(f"f.{c}=a.{c}" for c in key if c != "y")
        tk = f"and exists(select 1 from \"{name}\" f where f.y='0' and f.s='ANNUAL' and {flag})"
    # --- LOOP((%REGY%,%2%10,S%4)$(%TS%%1(..)), UNCD7(..)$(%8%TAKE%) = YES);
    off = "" if all_ts else f"and not {ctl_of('a')}"
    db.x(f"""create or replace temp table lv_keys as select distinct {ks} from "{name}" a
             where in_REG(a.r) {ysel} {off} and ({cond}) {tk} {dm}""")
    if db.q1("select count(*) from lv_keys"):
        on = " and ".join(f"k.{c}=a.{c}" for c in key)
        series = {}
        for row in db.q(f'select {ks}, a.s, a.value from "{name}" a join lv_keys k on {on}'):
            series.setdefault(row[:-2], {})[row[-2]] = _in(row[-1])
        need = {}
        kidx = [key.index(e) for e in ent]
        ri = key.index("r")
        ents = {(k[ri],) + tuple(k[i] for i in kidx) for k in series}
        db.x("create or replace temp table lv_ent as select * from (values " +
             ", ".join("(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in e) + ")" for e in ents) +
             ") t(r, " + ", ".join(ent) + ")")
        cc = db.cols(ctl)
        cmap = dict(zip(["r"] + ent, cc[:-1]))
        eon = " and ".join(f"c.{cmap[e]}=t.{e}" for e in ["r"] + ent)
        for row in db.q(f'select {", ".join("t." + e for e in ["r"] + ent)}, c.{cc[-1]} from "{ctl}" c join lv_ent t on {eon}'):
            need.setdefault(row[:-1], []).append(row[-1])
        T = trees(db)
        out = []
        for k, arr in series.items():
            tr = T[k[ri]]
            want = need.get((k[ri],) + tuple(k[i] for i in kidx), [])
            # --- IF((NOT SUM(RS_BELOW(R,'ANNUAL',S)$TS_ARRAY(S),1))$TS_ARRAY('ANNUAL'),
            if "ANNUAL" in arr and not any(s != "ANNUAL" for s in arr):
                a = arr["ANNUAL"]
                for s in want:
                    out.append(k + (s, _out(a * tr.g[s] / tr.g["ANNUAL"] if weighted else a)))
            else:
                for ts in want:
                    if ts in arr:
                        continue
                    tot, hit = 0.0, False
                    for s in tr.leaves[ts]:
                        v, u = nearest(tr, arr, s)
                        if v is None:
                            continue
                        hit = True
                        if u != s and weighted:
                            v = v * tr.g[s] / tr.g[u]
                        tot += v if weighted else v * tr.g[s] / tr.g[ts]
                    if hit:
                        out.append(k + (ts, _out(tot)))
        db.x(f"create or replace temp table lv_out ({', '.join(c + ' VARCHAR' for c in key)}, s VARCHAR, value DOUBLE)")
        if out:
            import pandas as pd
            df = pd.DataFrame(out, columns=key + ["s", "value"])
            db.con.register("lv_df", df); db.x("insert into lv_out select * from lv_df"); db.con.unregister("lv_df")
        db.put(name, f"select {', '.join(cols)}, value from lv_out", zero="eps")
    if fill == "0":
        # --- %1(%REGY%,%2%10,S%4)$((NOT %1(..,S%4))$%3(R,%2,S)) $= %1(%REGY%,%2%10,'ANNUAL'%4);
        cc = db.cols(ctl)
        cmap = dict(zip(["r"] + ent, cc[:-1]))
        eon = " and ".join(f"c.{cmap[e]}=a.{e}" for e in ["r"] + ent)
        sel = ", ".join(f"c.{cc[-1]} as s" if c == "s" else f"a.{c}" for c in cols)
        exists = " and ".join(f"b.{c}=a.{c}" for c in key)
        db.put(name, f"""select {sel}, a.value from "{name}" a join "{ctl}" c on {eon}
                         where a.s='ANNUAL' and in_REG(a.r) {ysel}
                           and not exists(select 1 from "{name}" b where {exists} and b.s=c.{cc[-1]})""", zero="eps")
    if fill is not None:
        # --- %1(R,LL,%2%10,S%4)$((NOT %3(R,%2,S))%TAKE%) = 0;
        db.x(f"delete from \"{name}\" a where in_REG(a.r) and not {ctl_of('a')} {tk} {dm}")


def _write(db, name, key, rows, zero="eps"):
    db.x(f"create or replace temp table lv_out ({', '.join(c + ' VARCHAR' for c in key)}, s VARCHAR, value DOUBLE)")
    if rows:
        import pandas as pd
        df = pd.DataFrame(rows, columns=key + ["s", "value"])
        db.con.register("lv_df", df); db.x("insert into lv_out select * from lv_df"); db.con.unregister("lv_df")
    db.put(name, f"select {', '.join(db.cols(name))}, value from lv_out", zero=zero)


def _ctl_map(db, ctl, ent, only=None):
    """{(r, entity..): set(timeslices)} for a control set %3(R,entity..,S); only: a query of (r, entity..) to restrict
    it to (the rest are not read)."""
    cc = db.cols(ctl)
    out = {}
    if only:
        on = " and ".join(f"c.{a}=o.{b}" for a, b in zip(cc[:-1], ["r"] + ent))
        sql = f'select {", ".join("c." + c for c in cc)} from "{ctl}" c where exists(select 1 from ({only}) o where {on})'
    else:
        sql = f'select {", ".join(cc)} from "{ctl}"'
    for row in db.q(sql):
        out.setdefault(row[:-1], set()).add(row[-1])
    return out


def lvlbr(db: DB, name, ctl, ent, inherit_missing=False, fx_check=False):
    """pp_lvlbr.mod: bound-type parameters X(R,V,P[,..],S,BD) (NCAP_AF, FLO_SHAR).

    ctl / ent   control set and the columns of `name` that index it (besides r and s)
    inherit_missing  %5: also fill control timeslices that have no value, when others below have one
    fx_check    %6: FX given together with LO/UP on a control timeslice -> LO/UP dropped
    """
    if not db.card(name):
        return
    cols = db.cols(name)
    key = [c for c in cols if c != "s"]
    ks = ", ".join(f"a.{c}" for c in key)
    ri, kidx = key.index("r"), [key.index(e) for e in ent]
    # only the series with a value off the control timeslices do anything below: those, and the control timeslices of
    # their entities, are read (in the table's row order, which the loop below and its warnings follow)
    n = db.tmp("lv_brkeys", f"""select distinct {ks} from "{name}" a where in_RTP(a.r,a.y,a.p)
                              and not in_{ctl}(a.r, {', '.join('a.' + e for e in ent)}, a.s)""")
    cm = _ctl_map(db, ctl, ent, f"select distinct r, {', '.join(ent)} from lv_brkeys") if n else {}
    T = trees(db)
    order = {s: o for s, o in db.q("select s, ord from ORD_S")}
    series = {}
    on = " and ".join(f"k.{c}=a.{c}" for c in key)
    for row in db.q(f'''select {ks}, a.s, a.value from "{name}" a where in_RTP(a.r,a.y,a.p)
                        and exists(select 1 from lv_brkeys k where {on}) order by a.rowid''') if n else ():
        series.setdefault(row[:-2], {})[row[-2]] = _in(row[-1])
    out, warned = [], set()
    for k, arr in series.items():
        tr = T[k[ri]]
        ctls = cm.get((k[ri],) + tuple(k[i] for i in kidx), set())
        off = [s for s in arr if s not in ctls]
        if not off:
            continue
        marks = set()
        for s in sorted(off, key=order.get):
            f, z = 0, 1
            for ts in sorted(tr.anc[s], key=order.get):
                if not z:
                    break
                if ts in arr:
                    f = 1
                    if ts in ctls:
                        z = 0
                        if (k, ts) not in warned:
                            warned.add((k, ts))
                            db.log.append(f"*01 WARNING - {name} Bounds conflict: Bound at {ctl} level and below, lower ignored: {k} TS={ts}")
                elif ts in ctls:
                    z = 0
                    marks.add(ts)
            if z:
                desc = [t for t in tr.below[s] if t in arr]
                if not f and not desc:
                    marks.add(s)
                else:
                    none_pos = not any(arr[t] > 1e-200 and t in ctls for t in desc)
                    for t in tr.below[s]:
                        if t in ctls and (none_pos or (inherit_missing and t not in arr)):
                            marks.add(t)
        new = {}
        for ts in sorted(marks, key=order.get):
            if ts in ctls:
                tot, hit = 0.0, False
                for s in tr.leaves[ts]:
                    v, u = nearest(tr, arr, s)
                    if v is not None:
                        hit = True
                        tot += tr.g[s] * v
                if hit:
                    arr[ts] = new[ts] = tot / tr.g[ts]
            else:
                for s in tr.below[ts]:
                    if s in ctls:
                        arr[s] = new[s] = arr[ts]
        out += [k + (s, _out(v)) for s, v in new.items()]
    _write(db, name, key, out)
    if fx_check:
        # --- LOOP((R,V,P%2,S)$%1(..,'FX'), IF(%3(R,P,%7S) AND (%1(..,'UP') + %1(..,'LO')), warning; %1(..,BDNEQ) = 0
        cc = db.cols(ctl)
        cmap = dict(zip(["r"] + ent, cc[:-1]))
        eon = " and ".join(f"c.{cmap[e]}=a.{e}" for e in ["r"] + ent)
        same = " and ".join(f"b.{c}=a.{c}" for c in cols if c != "l")
        n = db.tmp("lv_fx", f"""select distinct {', '.join('a.' + c for c in cols if c != 'l')} from "{name}" a
                                where a.l='FX' and in_MODLYEAR(a.y) and exists(select 1 from "{ctl}" c where {eon} and c.{cc[-1]}=a.s)
                                  and exists(select 1 from "{name}" b where {same} and b.l in ('LO','UP') and b.value <> 0)""")
        if n:
            for row in db.q("select * from lv_fx"):
                db.log.append(f"*01 WARNING - {name} Bounds conflict: FX + LO/UP at same TS-level, latter ignored: {row}")
            same = " and ".join(f'b.{c}="{name}".{c}' for c in cols if c != "l")
            db.zap(name, f"l in ('LO','UP') and exists(select 1 from lv_fx b where {same})")


def aggregate(tr: Tree, arr, ts):
    """SUM(RS_TREE(FINEST(R,S),TS), G_YRFR(R,S)*(nearest value at or above S))/G_YRFR(R,TS); None if nothing found."""
    tot, hit = 0.0, False
    for s in tr.leaves[ts]:
        v, _ = nearest(tr, arr, s)
        if v is not None:
            hit = True
            tot += tr.g[s] * v
    return tot / tr.g[ts] if hit else None


def read_series(db, name, where="true"):
    cols = db.cols(name)
    key = [c for c in cols if c != "s"]
    ks = ", ".join(f"a.{c}" for c in key)
    series = {}
    for row in db.q(f'select {ks}, a.s, a.value from "{name}" a where {where}'):
        series.setdefault(row[:-2], {})[row[-2]] = _in(row[-1])
    return key, series


def lvlus(db: DB, name, ctl, ent, lvl_tab, lvl_ent, floor=None):
    """pp_lvlus.mod: user-constraint coefficients UC_ACT / UC_FLO / UC_IRE / UC_COM by timeslice.

    ctl, ent   control set and the columns of `name` indexing it (besides r, s)
    lvl_tab    PRC_TSL or COM_TSL: timeslice level of the process / commodity (column lvl_ent of `name`)
    floor      SQL expression for %9 (a minimum level index), or None
    The first loop is replayed in GAMS record order because it carries the scalar F from one record to the next.
    """
    if not db.card(name):
        return
    cols = db.cols(name)
    key = [c for c in cols if c not in ("s", "y")]
    ordc = ", ".join(f"(select u.ord from __uel u where u.label = a.{c})" for c in cols)
    recs = f'select {", ".join("a." + c for c in cols)}, a.value from "{name}" a where in_MILESTONYR(a.y) and in_REG(a.r)'
    ki = [cols.index(c) for c in key]
    ri, si, yi = cols.index("r"), cols.index("s"), cols.index("y")
    li = cols.index(lvl_ent)
    marks, F = {}, 0
    # the loop looks only at the records given on a timeslice that is neither ANNUAL nor one of the entity's own
    # (%3): those alone are read, in record order (the others leave F and the marks as they are)
    own = f'in_{ctl}({", ".join("a." + c for c in ["r"] + ent + ["s"])})'
    rows = db.q(f"{recs} and a.s <> 'ANNUAL' and not {own} order by {ordc}")
    if rows:
        lv = {}
        fl = f", {floor}" if floor else ", 0"
        for r, e, o, f0 in db.q(f"""select a.r, a.{db.cols(lvl_tab)[1]}, max(ord_tsl(a.tsl)) - 1{fl.replace('{a}', 'a')} from "{lvl_tab}" a
                                    group by all"""):
            lv[(r, e)] = max(o, f0 or 0)
        stoal = {(r, s): v for r, s, v in db.q("select r, s, value from STOAL")}
    for row in rows:
        k = tuple(row[i] for i in ki)
        r, s = row[ri], row[si]
        z = stoal.get((r, s), 0)
        m = marks.setdefault(k, set())
        if "OUT" in m:
            if z > F:
                F = 9; m.add("IN")
        else:
            F = lv.get((r, row[li]), float("-inf"))
            if z > F:
                F = 9; m.update(("IN", "OUT"))
            else:
                m.add("OUT")
    # the series of the marked entries only: all their records, in record order
    series = {}
    if marks:
        cm = _ctl_map(db, ctl, ent)
        T = trees(db)
        db.x(f"create or replace temp table lv_keys ({', '.join(c + ' VARCHAR' for c in key)})")
        db.insert_rows("lv_keys", list(marks))
        on = " and ".join(f"m.{c}=a.{c}" for c in key)
        for row in db.q(f"{recs} and exists(select 1 from lv_keys m where {on}) order by {ordc}"):
            series.setdefault(tuple(row[i] for i in ki), {}).setdefault(row[yi], {})[row[si]] = _in(row[-1])
    out = []
    kr = key.index("r")
    ke = [key.index(e) for e in ent]
    for k, m in marks.items():
        tr = T[k[kr]]
        want = cm.get((k[kr],) + tuple(k[i] for i in ke), ())
        for y, arr in series[k].items():
            if "IN" in m:                       # given below the level: aggregate
                for ts in want:
                    if ts not in arr:
                        v = aggregate(tr, arr, ts)
                        if v is not None:
                            out.append((k, y, ts, _out(v)))
            else:                               # given above the level: inherit from the nearest coarser timeslice
                for s in want:
                    v, _ = nearest(tr, arr, s)
                    if v is not None:
                        out.append((k, y, s, _out(v)))
    if out:
        db.x(f"create or replace temp table lv_out ({', '.join(c + ' VARCHAR' for c in key)}, y VARCHAR, s VARCHAR, value DOUBLE)")
        import pandas as pd
        df = pd.DataFrame([k + (y, s, v) for k, y, s, v in out], columns=key + ["y", "s", "value"])
        db.con.register("lv_df", df); db.x("insert into lv_out select * from lv_df"); db.con.unregister("lv_df")
        db.put(name, f"select {', '.join(cols)}, value from lv_out", zero="eps")
    # --- %1(..,S%5)$(%3(R,%7%10,S)$(NOT %1(..,S%5))) $= %1(..,'ANNUAL'%5);
    cc = db.cols(ctl)
    cmap = dict(zip(["r"] + ent, cc[:-1]))
    eon = " and ".join(f"c.{cmap[e]}=a.{e}" for e in ["r"] + ent)
    sel = ", ".join(f"c.{cc[-1]} as s" if c == "s" else f"a.{c}" for c in cols)
    same = " and ".join(f"b.{c}=a.{c}" for c in cols if c != "s")
    # (every key it assigns is absent from the table, as the NOT EXISTS says: a put would delete nothing, so the rows
    #  are inserted as they come, as put inserts them)
    db.x(f"""insert into "{name}" select {sel}, a.value from "{name}" a join "{ctl}" c on {eon}
             where a.s='ANNUAL' and in_MILESTONYR(a.y) and in_REG(a.r) and a.value is not null
               and not exists(select 1 from "{name}" b where {same} and b.s=c.{cc[-1]})""")
