# SPDX-License-Identifier: GPL-3.0-or-later
"""Load a preprocessed model and a solution into one timespp.engine database.

The solution is a SQLite file in the layout of times_eq ``write_solution`` (also that of
a GAMS GDX converted to SQLite): one table per variable and equation, index columns
``d0``.., then ``level, marginal, lower, upper``, and ``__symbols(name, kind, dim)``.
A DuckDB file with those same columns is read the same way.

Levels and marginals become parameters ``L_<symbol>`` and ``M_<symbol>``. A missing
record reads as 0. An EPS level or marginal is a stored 0, which is what the engine
does for every other explicit zero. In a DuckDB file the marker is ``level_sv`` /
``marginal_sv`` = ``'EPS'``. A SQLite solution has no separate marker: EPS is
written as 0.0, and a plain 0 is not stored.

The solution file gives levels and marginals only, never model data. This loader copies
levels and marginals of variables and equations and nothing else.
"""
from __future__ import annotations
import json, os

from timespp.engine import DB

HERE = os.path.dirname(os.path.abspath(__file__))
DECL = os.path.normpath(os.path.join(HERE, "..", "..", "times_pp", "timespp", "declarations.json"))
DOMAINS = json.load(open(os.path.join(HERE, "domains.json"), encoding="utf-8"))

# eqobsalv.mod rebuilds these inside each window (solve.stp line 127). The WHILE
# (solve.stp lines 296-321) advances the window and restores user-constraint sets
# and bounds; it does not restore these. After the loop they are the last window's.
STEP_SALVAGE = ("SALV_INV", "OBJ_SUMS", "OBJSCC", "OBJ_DCEOH", "OBJ_IAD",
                "OBJ_SUMS3", "COR_SALVD", "OBJ_CRFD", "SALV_DEC")


def open_case(model_path, solution_path):
    """Model from ``model.db3`` (what ``times_pp`` writes) or the Parquet folder it writes in its place
    (``model_parquet``, TIMESPP_DB3_STREAM), plus a solution file."""
    db = DB()
    _load_model(db, model_path)
    load_solution(db, solution_path)
    return db


def load_solution(db, path, names=None):
    """Attach ``path`` (``.db3`` or ``.duckdb``) and copy levels and marginals.

    ``names`` limits the copy. A name that is not a variable or an equation stops
    the load: the solution gives levels and marginals, not model data.
    """
    src = path.replace("\\", "/")
    kind = "sqlite" if src.lower().endswith((".db3", ".sqlite")) else "duckdb"
    db.con.execute(f"attach '{src}' as src (type {kind})")
    try:
        _copy_solution(db, names)
    finally:
        db.con.execute("detach src")


def _load_model(db, path):
    """Copy sets and parameters. Variable tables in this file are bounds, not the solution."""
    with open(DECL, encoding="utf-8") as f:
        decl = json.load(f)
    src = path.replace("\\", "/")
    _attach_model(db, src)
    have = {r[0] for r in db.con.execute(
        "select table_name from information_schema.tables where table_catalog = 'mdl'").fetchall()}
    kind = {n: k for n, k, _d in db.con.execute('select name, kind, dim from mdl."__symbols"').fetchall()}
    for name, spec in decl.items():
        if name not in have or kind.get(name) == "variable":
            continue
        if spec["kind"] != "set" and not spec["domain"]:
            db.declare(name, "par", [])
            val = db.con.execute(f'select value from mdl."{name}"').fetchone()
            db.s[name] = float(val[0]) if val and val[0] is not None else 0.0
            continue
        db.declare(name, "set" if spec["kind"] == "set" else "par", spec["domain"])
        db.x(f'insert into "{name}" select * from mdl."{name}"')
    if "BS_RTYPE" in have:
        _load_abs(db, have, kind)
    from . import mlf
    mlf.load(db, have)
    from . import rptcli
    rptcli.load(db, have)
    _install_saved_step(db, have)
    # the spelling of the labels in the DD files (times_pp export.py), for the VD file; the tables hold capitals
    if "__casing" in have:
        db.casing = {u: t for u, t in db.con.execute('select label, text from mdl."__casing"').fetchall()}
    # the explanatory texts of the DD files (times_pp export.py), for the .vde file
    if "__texts" in have:
        db.sym_text, db.elem_text = {}, {}
        for n, e, t in db.con.execute('select name, element, text from mdl."__texts"').fetchall():
            if e is None:
                db.sym_text[n] = t
            else:
                db.elem_text.setdefault(n, {})[tuple(e.split("\x1f"))] = t
    # the encoding of the DD files (times_pp export.py), for the bytes of the VD files
    db.dd_encoding = "utf-8"
    if "__encoding" in have:
        db.dd_encoding = db.con.execute('select encoding from mdl."__encoding"').fetchone()[0]
    db.con.execute("detach mdl")
    db.con.execute("detach database if exists stp")     # (Windows keeps an attached file locked)


def _load_abs(db, have, kind):
    """The sets and parameters of the ancillary balancing services (a run with $SET ABS YES), which rptlite.rpt 172-173
    reads: their declarations are those of initmty.abs, and init_ext.abs 9: SET BS_RVT(R,YEAR,T);"""
    from timespp.gamsdata import Reader
    from timespp.load import BUNDLED_SRC
    rd = Reader({"ABS": "YES"})
    rd.read_file(os.path.join(BUNDLED_SRC, "initmty.abs"))
    decl = {n: (s.kind, s.domain) for n, s in rd.sym.items()}
    decl["BS_RVT"] = ("set", ["R", "YEAR", "T"])
    for name, (k, dom) in decl.items():
        if name not in have or name in db.sym or kind.get(name) == "variable":
            continue
        if dom is None:
            n = len([c for c in db.con.execute(f'select * from mdl."{name}" limit 0').description])
            dom = ["*"] * (n if k == "set" else n - 1)
        db.declare(name, "set" if k == "set" else "par", dom)
        db.x(f'insert into "{name}" select * from mdl."{name}"')


def _attach_model(db, src):
    """The model's tables as the catalog mdl: model.db3 attached, or the Parquet folder (one <table>.parquet per
    table and the metadata, times_pp's stream.py) as views of an attached in-memory catalog of the same name; with
    the folder, the steps of a myopic run (model_steps.db3 beside it) as views in the same catalog."""
    if not os.path.isdir(src):
        db.con.execute(f"attach '{src}' as mdl (type sqlite)")
        return
    db.con.execute("attach ':memory:' as mdl")
    for f in sorted(os.listdir(src)):
        if f.endswith(".parquet"):
            p = os.path.join(src, f).replace("\\", "/").replace("'", "''")
            db.con.execute(f"create view mdl.\"{f[:-8]}\" as select * from read_parquet('{p}')")
    steps = os.path.join(os.path.dirname(os.path.abspath(src)), "model_steps.db3")
    if os.path.exists(steps):
        p = steps.replace("\\", "/").replace("'", "''")
        db.con.execute(f"attach '{p}' as stp (type sqlite, read_only)")
        for (t,) in db.con.execute("select table_name from information_schema.tables where table_catalog = 'stp'").fetchall():
            if t.startswith("__step"):
                db.con.execute(f'create view mdl."{t}" as select * from stp."{t}"')


def install_last_step(db):
    """Put the last window's salvage into the live tables.

    the preprocessor's prep/myopic.py keeps each window on db.steps and then restores the base model, where
    these tables are empty. solve.stp leaves the last window's values in place.
    """
    steps = getattr(db, "steps", None) or []
    if not steps:
        return
    last = steps[-1]["tables"]
    for name in STEP_SALVAGE:
        if name not in db.sym or name not in last:
            continue
        db.clear(name)
        db.load_rows(name, last[name])


def _install_saved_step(db, have):
    """The same last window, from the __step tables export.py wrote into model.db3."""
    if "__steps" not in have:
        return
    k = db.q1("select max(step) from mdl.__steps")
    if k is None:
        return
    for name in STEP_SALVAGE:
        tab = f"__step{k}_{name}"
        if tab not in have or name not in db.sym:
            continue
        cols = db.cols(name)
        labels = ", ".join(f"upper(i{i})" for i in range(len(cols)))
        db.clear(name)
        if db.sym[name].kind == "set":
            db.x(f'insert into "{name}" select {labels} from mdl."{tab}"')
        else:
            db.x(f'insert into "{name}" select {labels}, value from mdl."{tab}"')


def _copy_solution(db, names):
    cols = {r[0] for r in db.con.execute(
        "select column_name from information_schema.columns "
        "where table_catalog = 'src' and table_name = '__symbols'").fetchall()}
    domain_sql = "domain" if "domain" in cols else "null"
    listed = db.con.execute(
        f"select name, lower(kind), dim, {domain_sql} from src.__symbols").fetchall()
    kind_of = {name: kind for name, kind, _dim, _domain in listed}
    if names is not None:
        bad = [n for n in names if kind_of.get(n) not in ("variable", "equation")]
        if bad:
            raise SystemExit(
                "load_solution copies levels and marginals of variables and equations only; "
                "these are results, not inputs: " + ", ".join(bad))
        wanted = set(names)
        listed = [row for row in listed if row[0] in wanted]
    rows = [row for row in listed if row[1] in ("variable", "equation")]
    for name, _kind, dim, domain in rows:
        there = db.q1(
            "select count(*) from information_schema.tables "
            f"where table_catalog = 'src' and table_name = '{name}'")
        if not there:
            continue
        try:
            indexes = _indexes(name, dim, domain)
        except KeyError:
            # a column or row family that GAMS does not have (times_eq writes some of its own, e.g. VAR_COMAUX):
            # no report statement reads it. Listed in db.solution_skipped.
            db.solution_skipped = getattr(db, "solution_skipped", []) + [name]
            continue
        for prefix, value, flag in (("L_", "level", "level_sv"), ("M_", "marginal", "marginal_sv")):
            _copy_attr(db, prefix + name, name, indexes, value, flag)


def _indexes(name, dim, domain):
    if not dim:
        return []
    if domain:
        parts = [p if p != "uni" else "*" for p in str(domain).split(",") if p]
        if len(parts) == dim:
            return parts
    if name in DOMAINS and len(DOMAINS[name]) == dim:
        return DOMAINS[name]
    raise KeyError(f"{name} has {dim} indexes and no domain; it is not in domains.json")


def _copy_attr(db, dest, src, indexes, value, flag):
    if not indexes:
        db.declare(dest, "par", [])
        row = db.con.execute(f'select "{value}" from src."{src}"').fetchone()
        db.s[dest] = float(row[0]) if row and row[0] else 0.0
        return
    db.declare(dest, "par", indexes)
    labels = ", ".join(f'upper(d{i})' for i in range(len(indexes)))
    db.x(f'insert into "{dest}" select {labels}, "{value}" from src."{src}" '
         f'where "{value}" <> 0 and "{value}" is not null')
    has = db.q1(
        "select count(*) from information_schema.columns "
        f"where table_catalog = 'src' and table_name = '{src}' and column_name = '{flag}'")
    if has:
        db.x(f'insert into "{dest}" select {labels}, 0 from src."{src}" where "{flag}" = \'EPS\'')
