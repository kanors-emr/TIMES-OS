# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers the steps share: SQL macros of the database, the guard for unported input, OFF ranges, ROUND."""
import math
import os
from ..controls import unsupported
from ..engine import DB


def setup_helpers(db: DB):
    x = db.x
    x("create or replace macro yv(y) as coalesce(try_cast(y as INTEGER), 0)")
    x("create or replace macro ys(n) as cast(cast(n as BIGINT) as VARCHAR)")
    x("create or replace macro ground(v) as sign(v) * floor(abs(v) + 0.5)")          # GAMS ROUND(): half away from zero
    # ORD() of timeslices = entry order of ALL_TS
    x("""create or replace table ORD_S as
         select a.s, cast(row_number() over (order by u.ord) as INTEGER) as ord
         from ALL_TS a join __uel u on u.label = a.s""")
    x("create or replace view k_ORD_S as select s as k0_, ord as val_ from ORD_S")
    x("create or replace macro ord_s(a0) as (select t_.val_ from k_ORD_S t_ where t_.k0_ = a0)")
    x("create or replace table TSL_ORD as select * from (values ('ANNUAL',1),('SEASON',2),('WEEKLY',3),('DAYNITE',4)) t(tsl,ord)")
    x("create or replace view k_TSL_ORD as select tsl as k0_, ord as val_ from TSL_ORD")
    x("create or replace macro ord_tsl(a0) as (select t_.val_ from k_TSL_ORD t_ where t_.k0_ = a0)")


def require_empty(db, names, what):
    used = [n for n in names if n in db.sym and db.sym[n].kind != "scalar" and db.card(n)]
    if used:
        if os.environ.get("TIMESPP_SOFT"):          # audit mode: report the guard and carry on
            print(f"  GUARD {what}: {used}")
            return
        unsupported(db, what, used)


def off_years(db: DB, table, keys, extra=""):
    """pp_off.mod: milestone years inside an OFF range  X(R,keys,BOHYEAR,EOHYEAR).

    FIL(EOHYEARS(LL)) = BOH <= LL <= EOH, over all ranges of the same (R,keys);  result = T with FIL(T) and
    SUM(PERIODYR(T,FIL),1)/D(T) >= G_OFFTHD(T): the share of the years of the period that are off reaches the threshold
    (G_OFFTHD is zero unless given, and then the milestone year alone decides).
    Returns SQL giving (r, <keys>, y)."""
    k = ", ".join(f"n.{c}" for c in ["r"] + keys)
    kf = ", ".join(f"f.{c}" for c in ["r"] + keys)
    return f"""with fil as (select distinct {k}, e.y from "{table}" n, EOHYEARS e
                           where yv(e.y) >= (case when n.u='BOH' then -1e9 else yv(n.u) end)
                             and yv(e.y) <= (case when n.u2='EOH' then 1e9 else yv(n.u2) end) {extra})
               select {kf}, t.y from fil f join PERIODYR t on t.y2 = f.y
               where in_MILESTONYR(t.y)
               group by {kf}, t.y
               having bool_or(f.y = t.y) and count(*) / v_D(t.y) >= v_G_OFFTHD(t.y)"""


def _values(rows, cols):
    """A SELECT over literal rows (strings quoted, numbers as DOUBLE)."""
    lit = lambda v: "'" + str(v).replace("'", "''") + "'" if isinstance(v, str) else f"cast({float(v)!r} as DOUBLE)"
    return " union all ".join("select " + ", ".join(f"{lit(v)} as {c}" for v, c in zip(row, cols)) for row in rows)


def rnd(x):
    """GAMS ROUND(x)"""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)
