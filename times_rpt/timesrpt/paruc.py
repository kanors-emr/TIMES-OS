# SPDX-License-Identifier: GPL-3.0-or-later
"""par_uc.rpt — user-constraint marginals from the bound equations.

rptlite.rpt calls this three times, writing PAR_UCSM:

    $BATINCLUDE par_uc.rpt SM EQE
    $BATINCLUDE par_uc.rpt SM EQG
    $BATINCLUDE par_uc.rpt SM EQL

and skips all three when VAR_UC is YES. A Veda run sets VAR_UC to YES, so
rptmisc.rpt writes PAR_UCSL and PAR_UCSM from the variables instead, and these
calls do not run. The %3 prefix and the %4 SOW index are empty.
"""
from __future__ import annotations


def run(db, suffix, eq):
    """One batinclude. suffix is the parameter ending (SM); eq is EQE, EQG or EQL."""
    name = "PAR_UC" + suffix
    db.declare(name, "par", ["UC_N", "*", "*", "*"])
    # PAR_UCSM(UC_N,'NONE','NONE','NONE') $= EQ_UC.M(UC_N);
    _direct(db, name, f"M_{eq}_UC", "'NONE'", "'NONE'", "'NONE'")
    # PAR_UCSM(UC_N,'NONE',T,'NONE') $= EQ_UCT.M; then $= EQ_UCSU.M (last write kept).
    _direct(db, name, f"M_{eq}_UCT", "'NONE'", None, "'NONE'")
    _direct(db, name, f"M_{eq}_UCTS", "'NONE'", None, None)
    _direct(db, name, f"M_{eq}_UCSU", "'NONE'", None, "'NONE'")
    _direct(db, name, f"M_{eq}_UCSUS", "'NONE'", None, None)
    _shuffled(db, name, eq)


def _direct(db, name, src, region, year, slice_):
    if src not in db.sym:
        return
    sy = db.sym[src]
    uc = _field(sy, "UC_N")
    year_sql = f"n.{_field(sy, 'T', 'YEAR', 'ALLYEAR')}" if year is None else year
    slice_sql = f"n.{_field(sy, 'S', 'TS', 'ALL_TS')}" if slice_ is None else slice_
    db.put(name, f"""
        select n.{uc} as uc, {region} as u, {year_sql} as u2, {slice_sql} as u3, n.value
        from "{src}" n
    """, zero="eps")


def _shuffled(db, name, eq):
    """
    Equations store the region first. PAR_RTUS(R,YEAR,UC_N,S) is projected onto
    PAR_URTS(UC_N,R,YEAR,S), which is that index order swapped back.

    PAR_RTUS(R,'0',UC_N,ANNUAL) $= EQ_UCR.M(R,UC_N);
    PAR_RTUS(R,T,UC_N,ANNUAL)   $= EQ_UCRT.M(R,T,UC_N);
    PAR_RTUS(R,T,UC_N,ANNUAL)   $= EQ_UCRSU.M(R,T,UC_N);
    PAR_UCSM(UC_N,R,'NONE','NONE') $= PAR_URTS(UC_N,R,'0',ANNUAL);
    PAR_UCSM(UC_N,R,T,'NONE')      $= PAR_URTS(UC_N,R,T,ANNUAL)*(1/COEF_PVT(R,T));

    Then the same for the timeslice equations EQ_UCRTS, EQ_UCRSUS and, over TSL,
    EQ_UCRS. Two TSL levels that write one key with different values stop here.
    """
    db.x("create or replace temp table par_rtus (r VARCHAR, y VARCHAR, uc VARCHAR, s VARCHAR, value DOUBLE)")
    _rtus(db, f"M_{eq}_UCR", "'0'", "'ANNUAL'")
    _rtus(db, f"M_{eq}_UCRT", None, "'ANNUAL'")
    _rtus(db, f"M_{eq}_UCRSU", None, "'ANNUAL'")
    _from_rtus(db, name, annual_only=True)
    db.x("delete from par_rtus")
    _rtus(db, f"M_{eq}_UCRTS", None, None)
    _rtus(db, f"M_{eq}_UCRSUS", None, None)
    _ucrs(db, f"M_{eq}_UCRS")
    _from_rtus(db, name, annual_only=False)


def _rtus(db, src, year, slice_):
    """$= onto PAR_RTUS. A later statement replaces the same key."""
    if src not in db.sym:
        return
    sy = db.sym[src]
    r = _field(sy, "R", "ALL_R", "REG")
    uc = _field(sy, "UC_N")
    year_sql = f"n.{_field(sy, 'T', 'YEAR', 'ALLYEAR')}" if year is None else year
    slice_sql = f"n.{_field(sy, 'S', 'TS', 'ALL_TS')}" if slice_ is None else slice_
    db.x(f"""
        create or replace temp table rtus_new as
        select n.{r} as r, {year_sql} as y, n.{uc} as uc, {slice_sql} as s, n.value
        from "{src}" n
    """)
    db.x("""
        delete from par_rtus o
        where exists (select 1 from rtus_new n
                      where n.r = o.r and n.y = o.y and n.uc = o.uc and n.s = o.s)
    """)
    db.x("insert into par_rtus select * from rtus_new")


def _ucrs(db, src):
    """LOOP(TSL, PAR_RTUS(R,T,UC_N,S) $= EQ_UCRS.M(R,T,UC_N,TSL,S))."""
    if src not in db.sym:
        return
    sy = db.sym[src]
    r = _field(sy, "R", "ALL_R", "REG")
    y = _field(sy, "T", "YEAR", "ALLYEAR")
    uc = _field(sy, "UC_N")
    s = _field(sy, "S", "TS", "ALL_TS")
    clash = db.q(f"""
        select {r}, {y}, {uc}, {s}, min(value), max(value)
        from "{src}"
        group by 1, 2, 3, 4
        having min(value) <> max(value)
        limit 3
    """)
    if clash:
        raise RuntimeError(
            "EQ_UCRS writes one user-constraint key from two timeslice levels with different "
            f"marginals; GAMS keeps the last TSL. First keys: {clash}")
    db.x(f"""
        create or replace temp table rtus_new as
        select {r} as r, {y} as y, {uc} as uc, {s} as s, any_value(value) as value
        from "{src}"
        group by 1, 2, 3, 4
    """)
    db.x("""
        delete from par_rtus o
        where exists (select 1 from rtus_new n
                      where n.r = o.r and n.y = o.y and n.uc = o.uc and n.s = o.s)
    """)
    db.x("insert into par_rtus select * from rtus_new")


def _from_rtus(db, name, annual_only):
    """
    PAR_UCSM(UC_N,R,'NONE','NONE') $= PAR_URTS where the year is '0' and the slice is ANNUAL.
    PAR_UCSM(UC_N,R,T,'NONE') $= PAR_URTS(ANNUAL) * (1/COEF_PVT), for milestone years T.
    The timeslice pass writes PAR_UCSM(UC_N,R,T,S) the same way, on every slice.
    """
    if annual_only:
        db.put(name, """
            select uc, r as u, 'NONE' as u2, 'NONE' as u3, value
            from par_rtus
            where y = '0' and s = 'ANNUAL'
        """, zero="eps")
        where = "s = 'ANNUAL'"
        slice_sql = "'NONE'"
    else:
        where = "true"
        slice_sql = "t.s"
    year = "in_T(t.y)" if "T" in db.sym else "true"
    db.put(name, f"""
        select t.uc, t.r as u, t.y as u2, {slice_sql} as u3,
               t.value / nullif(v_COEF_PVT(t.r, t.y), 0) as value
        from par_rtus t
        where {where} and {year}
    """, zero="eps")


def _field(sy, *names):
    want = {n.upper() for n in names}
    for domain, col in zip(sy.domain, sy.cols):
        if domain.upper() in want:
            return col
    raise KeyError(f"{sy.name} has no index in {names}; domain is {sy.domain}")
