# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the preprocessed model to SQLite in the layout the Julia package (times_eq) reads.

Same layout as a GAMS GDX file converted to SQLite: one table per symbol, index columns then
'value' (parameters), an explicit zero (EPS) as 0.0, +/-INF as +/-1e300, and a table
__symbols(name, kind, dim), __casing(label, text) with the spelling of the labels in the DD files, and
__texts(name, element, text) with their explanatory texts, __encoding(encoding) the encoding of the DD files.  Variable bounds are written as variable tables (level, marginal, lower, upper).
"""
import os, sqlite3

# Row order: DuckDB's parallel joins and GROUP BYs return rows in no fixed order, and the Julia package builds the
# model in table order, so the same input gave HiGHS a differently ordered LP (and another presolve, other iteration
# counts) from one run to the next. Tables of two or more index columns are written sorted by them; a table of one
# column keeps its order (an ordered set, such as the time slices), unless its labels are all numbers (years: a
# set computed with select distinct comes out in any order), which are then written in increasing order.
def _sorted(n):
    return n >= 2


def _year_order(db, name, col):
    """' order by <col> as a number' when every label of the one-column table is a number, else ''."""
    try:
        bad = db.q(f'select count(*) from "{name}" where try_cast("{col}" as double) is null')[0][0]
    except Exception:
        return ""
    return "" if bad else f' order by try_cast("{col}" as double)'


def _num(v):
    if v != v:
        return None
    return 1e300 if v == float("inf") else (-1e300 if v == float("-inf") else v)


_VALUE = ("case when isnan({c}) then NULL when {c} = 'inf'::double then 1e300 "
          "when {c} = '-inf'::double then -1e300 else {c} end")


def _sqlite_extension(db):
    """DuckDB's SQLite extension, if it can be loaded (it is downloaded once, on first use)."""
    try:
        db.con.execute("LOAD sqlite")
        return True
    except Exception:
        try:
            db.con.execute("INSTALL sqlite")
            db.con.execute("LOAD sqlite")
            return True
        except Exception:
            return False


def to_sqlite(db, path, token=None):
    """Write the tables.  DuckDB writes them into the SQLite file itself when its SQLite extension is there
    (three times faster on a large model: no rows pass through Python); otherwise Python's sqlite3 does.
    The two give the same file content, row for row."""
    final, path = path, path + ".part"           # complete under its own name only (see to_bin)
    for p in (final, path):
        if os.path.exists(p):
            os.remove(p)
    n = _to_sqlite_any(db, path)
    if token is not None:
        con = sqlite3.connect(path)
        con.execute("create table __tjb (token INTEGER)")
        con.execute("insert into __tjb values (?)", (token,))
        con.commit()
        con.close()
    os.replace(path, final)
    return n


def _to_sqlite_any(db, path):
    if os.environ.get("TIMESPP_EXPORT") != "python" and _sqlite_extension(db):
        try:
            return _to_sqlite_duckdb(db, path)
        except Exception as e:
            print(f"  (the tables are written through Python: {type(e).__name__}: {str(e)[:200]})")
            try:
                db.con.execute("DETACH o_")
            except Exception:
                pass
            if os.path.exists(path):
                os.remove(path)
    return _to_sqlite_python(db, path)


def _to_sqlite_duckdb(db, path):
    x = db.con.execute
    x(f"ATTACH '{path}' AS o_ (TYPE sqlite)")
    x("BEGIN TRANSACTION")                          # one commit for the file, not one per table
    meta = []
    for name, sy in db.sym.items():
        if sy.kind == "scalar":
            x(f'create table o_."{name}" ("value" DOUBLE)')
            x(f'insert into o_."{name}" values (?)', [_num(float(db.s.get(name, 0.0)))])
            meta.append((name, "parameter", 0))
            continue
        n = len(sy.cols)
        decl = [f'"i{i}" VARCHAR' for i in range(n)] + (['"value" DOUBLE'] if sy.kind == "par" else [])
        x(f'create table o_."{name}" ({", ".join(decl)})')
        meta.append((name, "set" if sy.kind == "set" else "parameter", n))
        tc = [r[0] for r in db.q(f'describe "{name}"')]          # the columns, in order, as select * gives them
        src = [f'"{c}"' for c in tc[:n]]
        if sy.kind == "par":
            src.append(_VALUE.format(c=f'"{tc[n]}"'))
        if src:
            order = f' order by {", ".join(src[:n])}' if _sorted(n) else (_year_order(db, name, tc[0]) if n == 1 else "")
            x(f'insert into o_."{name}" select {", ".join(src)} from "{name}"{order}')
    for var in sorted(getattr(db, "bounds", ())):
        bc = [r[0] for r in db.q(f'describe "B_{var}"')]
        n = len(bc) - 2
        decl = ", ".join(f'"d{i}" VARCHAR' for i in range(n))
        x(f'create table o_."{var}" ({decl + ", " if decl else ""}level DOUBLE, marginal DOUBLE, lower DOUBLE, upper DOUBLE)')
        meta.append((var, "variable", n))
        sel = [f'"{c}"' for c in bc[:n]] + ["0.0", "0.0", _VALUE.format(c=f'"{bc[n]}"'), _VALUE.format(c=f'"{bc[n + 1]}"')]
        order = f' order by {", ".join(sel[:n])}' if n else ""
        x(f'insert into o_."{var}" select {", ".join(sel)} from "B_{var}"{order}')
    x("COMMIT")
    x("DETACH o_")
    con = sqlite3.connect(path)
    _steps(db, con)
    _casing(db, con)
    con.execute("create table __symbols (name TEXT, kind TEXT, dim INTEGER)")
    con.executemany("insert into __symbols values (?,?,?)", meta)
    con.commit()
    con.close()
    return len(meta)


# model.db3's values as SQLite gives them back: SQLite stores a REAL with a whole value as an integer, so a -0.0
# reads back as 0.0. The Parquet folder writes 0.0 too (DuckDB's tables, and model.tjb, keep -0.0).
_PQ_VALUE = ("case when isnan({c}) then NULL when {c} = 'inf'::double then 1e300 "
             "when {c} = '-inf'::double then -1e300 when {c} = 0 then 0.0 else {c} end")


def table_sql(db, name, con=None):
    """(source relation, SELECT) of one table of model.db3 as _to_sqlite_duckdb writes it: the same columns, values
    and ORDER BY, named as in model.db3 (i0.., value; d0.., level, marginal, lower, upper). For the Parquet folder
    (stream.py). name: a symbol, or a variable whose bounds are in B_<name>; None for a scalar. con: the connection to
    read the columns on (default db's)."""
    q = (lambda s: con.execute(s).fetchall()) if con is not None else db.q
    sy = db.sym.get(name)
    if sy is not None:
        if sy.kind == "scalar":
            return None
        n = len(sy.cols)
        tc = [r[0] for r in q(f'describe "{name}"')]
        src = [f'"{c}" as "i{i}"' for i, c in enumerate(tc[:n])]
        if sy.kind == "par":
            src.append(_PQ_VALUE.format(c=f'"{tc[n]}"') + ' as "value"')
        if not src:
            return name, f'select 1 as one_ from "{name}" where false'
        by = [f'"{c}"' for c in tc[:n]]
        order = f' order by {", ".join(by)}' if _sorted(n) else (_year_order_on(q, name, tc[0]) if n == 1 else "")
        return name, f'select {", ".join(src)} from "{name}"{order}'
    bc = [r[0] for r in q(f'describe "B_{name}"')]
    n = len(bc) - 2
    sel = [f'"{c}" as "d{i}"' for i, c in enumerate(bc[:n])] + ['0.0 as "level"', '0.0 as "marginal"',
           _PQ_VALUE.format(c=f'"{bc[n]}"') + ' as "lower"', _PQ_VALUE.format(c=f'"{bc[n + 1]}"') + ' as "upper"']
    order = f' order by {", ".join(f"{chr(34)}{c}{chr(34)}" for c in bc[:n])}' if n else ""
    return f"B_{name}", f'select {", ".join(sel)} from "B_{name}"{order}'


def _year_order_on(q, name, col):
    """_year_order on a connection of the caller's."""
    try:
        bad = q(f'select count(*) from "{name}" where try_cast("{col}" as double) is null')[0][0]
    except Exception:
        return ""
    return "" if bad else f' order by try_cast("{col}" as double)'


def symbols(db):
    """(name, kind, dim) of every table of model.db3, in the order of its __symbols."""
    out = [(n, "parameter" if sy.kind in ("scalar", "par") else "set", 0 if sy.kind == "scalar" else len(sy.cols))
           for n, sy in db.sym.items()]
    for var in sorted(getattr(db, "bounds", ())):
        out.append((var, "variable", len(db.dropped[f"B_{var}"][0]) - 2 if f"B_{var}" in getattr(db, "dropped", {})
                    else len(db.q(f'describe "B_{var}"')) - 2))
    return out


def metadata(db, token=None):
    """The metadata tables of model.db3 other than the symbols' own: name -> (declaration, rows): __casing, __texts,
    __encoding, __symbols, and __tjb with the token (as _casing and to_sqlite write them)."""
    m = {"__casing": ("label TEXT, text TEXT", [(u, t) for u, t in getattr(db, "casing", {}).items() if t != u])}
    rows = [(n, None, t) for n, t in getattr(db, "sym_text", {}).items() if t]
    rows += [(n, "\x1f".join(k), t) for n, d in getattr(db, "elem_text", {}).items() for k, t in d.items()]
    m["__texts"] = ("name TEXT, element TEXT, text TEXT", rows)
    m["__encoding"] = ("encoding TEXT", [(getattr(db, "dd_encoding", "utf-8"),)])
    m["__symbols"] = ("name TEXT, kind TEXT, dim INTEGER", symbols(db))
    if token is not None:
        m["__tjb"] = ("token INTEGER", [(token,)])
    return m


def _casing(db, con):
    """__casing(label, text): how the DD files spell a label the tables hold in capitals, where the two differ.
    The report writer (times_rpt) needs it for the VD file; it is not a symbol, and not in __symbols."""
    rows = [(u, t) for u, t in getattr(db, "casing", {}).items() if t != u]
    con.execute("create table __casing (label TEXT, text TEXT)")
    con.executemany("insert into __casing values (?,?)", rows)
    # __texts(name, element, text): the explanatory texts of the DD files, of a symbol (element NULL) and of the
    # elements of a set (the labels of the element joined by the unit separator, chr(31)), for the .vde file of the report
    rows = [(n, None, t) for n, t in getattr(db, "sym_text", {}).items() if t]
    rows += [(n, "\x1f".join(k), t) for n, d in getattr(db, "elem_text", {}).items() for k, t in d.items()]
    con.execute("create table __texts (name TEXT, element TEXT, text TEXT)")
    con.executemany("insert into __texts values (?,?,?)", rows)
    # __encoding(encoding): how the DD files were written (utf-8 or latin-1); the report writes their texts back so
    con.execute("create table __encoding (encoding TEXT)")
    con.execute("insert into __encoding values (?)", (getattr(db, "dd_encoding", "utf-8"),))


def _to_sqlite_python(db, path):
    con = sqlite3.connect(path)
    meta = []
    for name, sy in db.sym.items():
        if sy.kind == "scalar":
            con.execute(f'create table "{name}" ("value" REAL)')
            con.execute(f'insert into "{name}" values (?)', (_num(float(db.s.get(name, 0.0))),))
            meta.append((name, "parameter", 0))
            continue
        n = len(sy.cols)
        cols = [f"i{i}" for i in range(n)]
        decl = ", ".join(f'"{c}" TEXT' for c in cols)
        if sy.kind == "par":
            decl += (", " if decl else "") + '"value" REAL'
        con.execute(f'create table "{name}" ({decl})')
        meta.append((name, "set" if sy.kind == "set" else "parameter", n))
        rows = db.q(f'select * from "{name}"' + (_year_order(db, name, db.q(f'describe "{name}"')[0][0]) if n == 1 else ""))
        if not rows:
            continue
        if _sorted(n):
            rows = sorted(rows, key=lambda r: r[:n])
        if sy.kind == "par":
            rows = [r[:-1] + (_num(r[-1]),) for r in rows]
        con.executemany(f'insert into "{name}" values ({",".join("?" * len(rows[0]))})', rows)
    for var in sorted(getattr(db, "bounds", ())):
        n = len(db.q(f'describe "B_{var}"')) - 2
        rows = sorted(db.q(f'select * from "B_{var}"'), key=lambda r: r[:n])
        decl = ", ".join(f'"d{i}" TEXT' for i in range(n))
        con.execute(f'create table "{var}" ({decl + ", " if decl else ""}level REAL, marginal REAL, lower REAL, upper REAL)')
        meta.append((var, "variable", n))
        con.executemany(f'insert into "{var}" values ({",".join("?" * (n + 4))})',
                        [r[:n] + (0.0, 0.0, _num(r[n]), _num(r[n + 1])) for r in rows])
    _steps(db, con)
    _casing(db, con)
    con.execute("create table __symbols (name TEXT, kind TEXT, dim INTEGER)")
    con.executemany("insert into __symbols values (?,?,?)", meta)
    con.commit()
    con.close()
    return len(meta)


def steps_of(path):
    """The file of a myopic run's steps beside model.db3, when the Parquet folder is written in its place."""
    return os.path.join(os.path.dirname(os.path.abspath(path)), "model_steps.db3")


def to_steps(db, path, token):
    """The steps of a myopic run (the tables _steps writes into model.db3) in a file of their own, with __tjb (the
    token of model.tjb): written under another name and renamed, so that it appears complete."""
    tmp = path + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    try:
        con.execute("pragma journal_mode = off")
        con.execute("pragma synchronous = off")
        _steps(db, con)
        con.execute("create table __tjb (token INTEGER)")
        con.execute("insert into __tjb values (?)", (token,))
        con.commit()
    finally:
        con.close()
    os.replace(tmp, path)


def _steps(db, con):
    """A myopic run (prep/myopic.py): for step k, the tables "__step<k>_<name>" replace the table <name> of the main pass
    (sets, parameters and the bound tables of variables); __steps lists them, with the first year of the window."""
    st = getattr(db, "steps", None)
    if not st:
        return
    con.execute("create table __steps (step INTEGER, year INTEGER, name TEXT, kind TEXT, dim INTEGER)")
    for step in st:
        k = step["step"]
        meta = []
        for name, rows in step["tables"].items():
            sy = db.sym[name]
            n = len(sy.cols)
            tab = f"__step{k}_{name}"
            decl = ", ".join([f'"i{i}" TEXT' for i in range(n)] + (['"value" REAL'] if sy.kind == "par" else []))
            con.execute(f'create table "{tab}" ({decl})')
            if rows:
                if _sorted(n):
                    rows = sorted(rows, key=lambda r: r[:n])
                if sy.kind == "par":
                    rows = [r[:-1] + (_num(r[-1]),) for r in rows]
                con.executemany(f'insert into "{tab}" values ({",".join("?" * len(rows[0]))})', rows)
            meta.append((k, step["year"], name, "set" if sy.kind == "set" else "parameter", n))
        for var, rows in step["bounds"].items():
            n = len(rows[0]) - 2 if rows else len(db.q(f'describe "B_{var}"')) - 2
            tab = f"__step{k}_{var}"
            decl = ", ".join(f'"d{i}" TEXT' for i in range(n))
            con.execute(f'create table "{tab}" ({decl + ", " if decl else ""}level REAL, marginal REAL, lower REAL, upper REAL)')
            con.executemany(f'insert into "{tab}" values ({",".join("?" * (n + 4))})',
                            [r[:n] + (0.0, 0.0, _num(r[n]), _num(r[n + 1])) for r in sorted(rows, key=lambda r: r[:n])])
            meta.append((k, step["year"], var, "variable", n))
        # a run with FIXBOH: the levels of the loaded solution point in the periods the step fixes (spoint.mod)
        for var, rows in step.get("levels", {}).items():
            n = len(rows[0]) - 1 if rows else 0
            tab = f"__step{k}_L_{var}"
            decl = ", ".join([f'"d{i}" TEXT' for i in range(n)] + ['"level" REAL'])
            con.execute(f'create table "{tab}" ({decl})')
            con.executemany(f'insert into "{tab}" values ({",".join("?" * (n + 1))})', [r[:n] + (_num(r[n]),) for r in rows])
            meta.append((k, step["year"], var, "level", n))
        for name, v in step["scalars"].items():
            tab = f"__step{k}_{name}"
            con.execute(f'create table "{tab}" ("value" REAL)')
            con.execute(f'insert into "{tab}" values (?)', (_num(float(v)),))
            meta.append((k, step["year"], name, "parameter", 0))
        con.executemany("insert into __steps values (?,?,?,?,?)", meta)


# ------------------------------------------------------------------------------------------------- binary copy
# model.tjb: the tables times_eq reads, in a binary layout it reads without parsing text (TimesEq.load prefers it to
# model.db3 when both are of the same run).  Written before model.db3, so that the equations can start while
# model.db3 is still being written.  Little-endian:
#   "TJB1"  u64 token (the same number is in model.db3, table __tjb: a model.tjb of another run is not used)
#   u8 steps (1: a myopic run, whose steps are in model.db3, or model_steps.db3 beside the Parquet folder)
#   u64 number of labels; u32 byte length of each; the labels, UTF-8, one after the other (numbered from 0)
#   u64 number of tables; for each, in the order of __symbols in model.db3:
#     u16 length + name (UTF-8); u8 kind (0 set, 1 parameter, 2 variable); u8 dim; u64 rows; u8 data (0: the rows
#     are in model.db3 only: a table the equations do not read, as times_eq/src/schema.jl lists them); with data,
#     dim columns of i32 label numbers; then for a parameter its f64 values, for a variable f64 lower and upper
#     (+-inf as they are: what TimesEq makes of +-1e300 in model.db3)
import struct, re


def _wanted():
    """The sets, parameters and variables the equations read (times_eq/src/schema.jl: SETS, PARS, VARS), or None
    (all) when the file is not there."""
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "times_eq", "src", "schema.jl")
    if not os.path.isfile(f):
        return None
    text = open(f, encoding="utf-8").read()
    out = set()
    for block in ("SETS", "PARS", "VARS"):
        m = re.search(rf"^const {block} = \($(.*?)^\)", text, re.S | re.M)
        if not m:
            return None
        names = {n.upper() for n in re.findall(r"^\s*([A-Za-z_]\w*)\s*=\s*\(", m.group(1), re.M)}
        out |= names
        if block == "VARS":
            # stochastic TIMES: the bounds by state of the world, VAS_<X> for VAR_<X> (times_eq/src/data.jl is_vas)
            out |= {"VAS_" + n[4:] for n in names if n.startswith("VAR_")}
    return out


def _label_cols(db):
    """(table, kind, kind code, source columns, value columns) of every table written, in the order of to_sqlite."""
    out = []
    dropped = getattr(db, "dropped", {})          # tables dropped once written (stream.py): their columns as they were
    desc = lambda t: dropped[t.upper()][0] if t.upper() in dropped else [r[0] for r in db.q(f'describe "{t}"')]
    for name, sy in db.sym.items():
        if sy.kind == "scalar":
            out.append((name, None, 1, [], None))
            continue
        tc = desc(name)
        n = len(sy.cols)
        out.append((name, name, 0 if sy.kind == "set" else 1, tc[:n], [tc[n]] if sy.kind == "par" else []))
    for var in sorted(getattr(db, "bounds", ())):
        bc = desc(f"B_{var}")
        n = len(bc) - 2
        out.append((var, f"B_{var}", 2, bc[:n], bc[n:n + 2]))
    return out


def to_bin(db, path, token):
    import numpy as np
    tabs = _label_cols(db)
    want = _wanted()
    tabs = [(n, s, k, c, v, want is None or n.upper() in want) for n, s, k, c, v in tabs]
    x = db.con.execute
    # every label of every written column, numbered in sorted order
    x("create or replace temp table __labs (l VARCHAR)")
    for _, src, _, cols, _, data in tabs:
        if src and cols and data:
            # one column at a time: a DISTINCT on a plain column, rather than on a list of the columns unnested
            for c in cols:
                x(f'insert into __labs select distinct cast("{c}" as VARCHAR) from "{src}"')
    x("create or replace temp table __lab as select l, (row_number() over (order by l) - 1)::INTEGER as i "
      "from (select distinct l from __labs where l is not null)")
    x("drop table __labs")
    labels = [r[0] for r in db.q("select l from __lab order by i")]
    # each label as a number, as the ORDER BY of model.db3 takes it (try_cast; isnum: it is one)
    nn = db.q("select try_cast(l as double), try_cast(l as double) is not null from __lab order by i")
    num = np.array([v if v is not None else np.nan for v, _ in nn] or [0.0], dtype=float)
    isnum = np.array([b for _, b in nn] or [False], dtype=bool)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        w = f.write
        w(b"TJB1"); w(struct.pack("<QB", token, 1 if getattr(db, "steps", None) else 0))
        enc = [l.encode("utf-8") for l in labels]
        w(struct.pack("<Q", len(enc))); w(np.array([len(b) for b in enc], dtype="<u4").tobytes()); w(b"".join(enc))
        w(struct.pack("<Q", len(tabs)))
        for name, src, kind, cols, vals, data in tabs:
            nb = name.encode("utf-8")
            if src is None:                      # a scalar: a parameter of no index, one row
                w(struct.pack("<H", len(nb))); w(nb); w(struct.pack("<BBQB", 1, 0, 1, 1))
                v = float(db.s.get(name, 0.0))
                w(np.array([v], dtype="<f8").tobytes())
                continue
            if not data:
                w(struct.pack("<H", len(nb))); w(nb)
                w(struct.pack("<BBQB", kind, len(cols), db.q1(f'select count(*) from "{src}"'), 0))
                continue
            # the number of each label by a join (one per column), the rows put back in their order
            sel = [f"l{i}.i as k{i}" for i in range(len(cols))] + [f'cast(t_."{c}" as DOUBLE) as v{i}' for i, c in enumerate(vals)]
            joins = " ".join(f'join __lab l{i} on l{i}.l = cast(t_."{c}" as VARCHAR)' for i, c in enumerate(cols))
            # (rowid: the order of the table, as a plain scan gives it to model.db3; the join does not keep it, and
            # row_number() over () would not either with several threads.)
            # with two index columns or more (or a variable), the rows in the order model.db3 has, by the label numbers
            # (which follow the order of the text), rows that tie in the order of the table: an ORDER BY on integers,
            # sorted by DuckDB's threads (far less than the ORDER BY on the text, or numpy's lexsort)
            by = len(cols) >= 2 or (kind == 2 and len(cols) > 0)
            q = f'select t_.rowid as rid_, {", ".join(sel)} from "{src}" t_ {joins}'
            if sel and by:
                # sorted into a temp table, then read: DuckDB hands the rows of an ORDER BY query to Python far more
                # slowly than those of a table (COEF_PTRAN of 27 M rows: 9 s against 3 + 1.4 s); the table keeps
                # the sorted order (rid_ last, so no ties), and rid_ is not read
                x(f"create or replace temp table __tjb_sorted as {q} order by " + ", ".join(f"k{i}" for i in range(len(cols))) + ", rid_")
                arr = x("select * exclude (rid_) from __tjb_sorted").fetchnumpy()
                x("drop table __tjb_sorted")
            else:
                arr = db.con.execute(q).fetchnumpy() if sel else {}
            if arr:
                rid = None if by else np.asarray(arr.pop("rid_"))
                # a one-column table of numbers by number (rows that tie in the order of the table), any other the
                # order of the table (the ORDER BY above did the rest)
                ks = [np.asarray(arr[f"k{i}"]) for i in range(len(cols))]
                if by:
                    o = None                     # in order already
                elif len(cols) == 1 and kind != 2 and bool(isnum[ks[0]].all()):
                    o = np.lexsort([rid, num[ks[0]]])
                else:
                    o = np.argsort(rid, kind="stable")
                if o is not None:
                    arr = {k: np.asarray(v)[o] for k, v in arr.items()}
            nrows = len(next(iter(arr.values()))) if arr else db.q1(f'select count(*) from "{src}"')
            w(struct.pack("<H", len(nb))); w(nb); w(struct.pack("<BBQB", kind, len(cols), nrows, 1))
            for i in range(len(cols)):
                w(np.ascontiguousarray(arr[f"k{i}"], dtype="<i4").tobytes())
            for i in range(len(vals)):
                a = arr[f"v{i}"]
                if hasattr(a, "mask"):           # a NULL value: NaN (TimesEq stops on it, as on a NULL in model.db3)
                    a = a.filled(np.nan)
                w(np.ascontiguousarray(a, dtype="<f8").tobytes())
    x("drop table __lab")
    os.replace(tmp, path)
    return len(tabs)
