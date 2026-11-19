# SPDX-License-Identifier: GPL-3.0-or-later
"""Domain violations in the input data (GAMS error 170), handled as TIMES does.

The DD files are read under $ONWARNING, so a record with a label that is not in the domain set of
its position (a flow of a commodity that was never declared, say) is a warning, not an error. When
there has been any warning TIMES reloads the data through a GDX file with filtering switched on
(setglobs.gms, gdxfilter.gms):

    $ GDXOUT _dd_.gdx / $ UNLOAD ... $ IF NOT warnings $GOTO SYSD ... $BATINCLUDE gdxfilter MAIN
    gdxfilter.gms:  $onFiltered;  $LOADR <every symbol with data and more than one dimension>

so the offending records disappear from every symbol of two or more dimensions; one-dimensional
symbols are not reloaded. ppmain.mod then writes one line to the QA log:

    $ IF WARNINGS $BATINCLUDE pp_qaput.%1 PUTOUT 0 * 'GAMS Warnings Detected; Input Data have been filtered via GDX'

Here: the same records are removed, the same line goes to the QA log, and the records are listed
in `db.domain_violations` in the form of the GAMS listing ("**** 170  Domain violation for element").
A domain is checked when it names a one-dimensional set (or an alias of one), also when that set has no members: GAMS
checks a label against the set as declared, so with an empty domain set every record of the symbol violates it (a
blend without SET SPE: BL_TYPE, BL_SPEC, BL_COM over SPE are all removed, and no EQG_BLND is built).

The filter runs only with DATAGDX YES (set in the run file, as Veda writes it, or by DATAGDXI YES: initmty.mod 489).
Without it, DATAGDX NO or not set at all, there is no filter (setglobs.gms 13: $ IF NOT %DATAGDX%==YES $GOTO SYSD) and
GAMS keeps the records, labels outside their domains included: that is not ported, so such a run stops when there are
any, and adding $SET DATAGDX YES to the run file makes it run.
"""
from .engine import DB

QA_LINE = "*** GAMS Warnings Detected; Input Data have been filtered via GDX"


def _domain_sets(db: DB, sy):
    """For each index position of a symbol: (column, name of the domain set) or None when it is not checked."""
    out = []
    for col, d in zip(sy.cols, sy.domain):
        d = d.upper()
        d = db.alias.get(d, d)
        t = db.sym.get(d)
        ok = d != "*" and t is not None and t.kind == "set" and len(t.cols) == 1 and d != sy.name
        out.append((col, d, t.cols[0]) if ok else None)
    return out


def filtered(db):
    """The filter runs: DATAGDX YES, or DATAGDXI YES (initmty.mod 489: $ IF %DATAGDXI%==YES $SETGLOBAL DATAGDX YES).
    Not set, DATAGDX is not YES and setglobs.gms 13 skips the filter."""
    env = getattr(db, "env", {})
    return any(str(env.get(k, "")).strip().strip("'\"").upper() == "YES" for k in ("DATAGDX", "DATAGDXI"))


def apply(db: DB, verbose=False):
    """Remove records that violate their domain; return the list of violations found."""
    found = []
    for name, sy in list(db.sym.items()):
        if sy.kind not in ("set", "par") or not sy.cols or not db.card(name):
            continue
        checks = [c for c in _domain_sets(db, sy) if c]
        if not checks:
            continue
        cond = " or ".join(f'a.{col} not in (select {dc} from "{d}")' for col, d, dc in checks)
        rows = db.q(f'select * from "{name}" a where {cond}')
        if not rows:
            continue
        nk = len(sy.cols)
        members = {d: {v for (v,) in db.q(f'select {dc} from "{d}"')} for _, d, dc in checks}
        pos = {col: (i, d) for i, (col, d, _) in zip([sy.cols.index(c[0]) for c in checks], checks)}
        for r in rows:
            bad = [f"{r[i]} not in {d}" for col, (i, d) in pos.items() if r[i] not in members[d]]
            found.append((name, tuple(r[:nk]), "; ".join(bad), nk > 1))
        if nk > 1 and filtered(db):                     # $LOADR only for symbols of more than one dimension
            db.x(f'delete from "{name}" a where {cond}')
    db.domain_violations = [f"**** 170  Domain violation for element   {n}  {'.'.join(map(str, k))}   ({why})"
                            + ("" if dropped else "   [one-dimensional symbol: kept]") for n, k, why, dropped in found]
    if found and not filtered(db):
        from .controls import unsupported
        unsupported(db, "domain violations without $SET DATAGDX YES in the run file (GAMS keeps those records; TIMES "
                        "filters them only with DATAGDX YES, as Veda writes it): " + "; ".join(f"{n} {'.'.join(map(str, k))}" for n, k, _, _ in found[:5])
                    + (f" and {len(found) - 5} more" if len(found) > 5 else ""), sorted({n for n, _, _, _ in found}))
    elif found:
        db.log.insert(0, QA_LINE)
        if verbose:
            for line in db.domain_violations[:50]:
                print(" ", line)
    return found
