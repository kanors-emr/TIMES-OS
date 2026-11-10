# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare two matrices in the layout of the jacobian GDX that GAMS's CONVERT solver writes (`jacobian <file>.gdx`),
for example the one TIMES.py writes from its own run (`--jacobian <file>`) against the one GAMS writes for the
same TIMES case (REDUCE NO).

  python compare_jacobian.py <first.gdx> <second.gdx> [--json out.json] [--memory 16GB] [--temp folder]
                             [--gams-dir <GAMS system folder>]

The layout: sets i (e1, e2, ...) and j (x1, ...) whose element texts are the names of the rows and columns,
`NAME(label,...)`; equations e (the rows: lower and upper are the right-hand side bounds, all variable terms on the
left) and variables x (lower, upper: the column bounds); parameter A(i,j) (EPS: an explicit zero). The two files may
number their rows and columns differently: rows and columns are matched by name and labels (upper case; a label in
quotes may contain commas). Optional in the first file: cancel(i), the size of the constants that cancelled in a row's
right-hand side.

The rules, row by row and entry by entry ("here" is the first file, "GAMS" the second):
- every coefficient must be in both files and equal: relative difference at most 1e-9 (+ 1e-12 absolute); an
  explicit zero on both sides is equal (EPS in GAMS);
- every row the same right-hand side bounds and every column the same bounds, by the same rule; a right-hand side made
  of constants that cancel is equal within 64 machine epsilons of their size (cancel(i)): its value is the rounding
  remainder of that arithmetic, which depends on the order it is done in.
When all of this holds the two are the same linear program. The report: counts, the largest relative differences, a
table by equation, the differences by (kind, equation, variable) with an example each, and the first few rows or
columns that differ. Exit status 0: the same; 1: not the same. The comparison runs in DuckDB, on all processors,
spilling to disk past --memory."""
import os, sys, json, time, re

KEYSEP = "\x1f"                              # joins the labels of a row or column key
TOL = 1e-9
EPS64 = 64 * 2.220446049250313e-16           # 64 * eps(Float64)


def _duck(memory=None, temp=None):
    import duckdb
    con = duckdb.connect()
    if memory:
        con.execute(f"SET memory_limit='{memory}'")
    if temp:
        os.makedirs(temp, exist_ok=True)
        con.execute(f"SET temp_directory='{temp.replace(chr(39), chr(39) * 2)}'")
    return con


def numbers(labels):
    """The numbers of CONVERT's labels e<i> / x<j> (a pandas Series of str), as int64; the columns of SOS and
    semi-continuous variables are labelled s1s1('4430'), sc4431 etc."""
    n = labels.str.extract(r"^[a-z](\d+)$")[0]
    odd = n.isna()
    if odd.any():
        n[odd] = labels[odd].str.extract(r"'(\d+)'")[0].fillna(labels[odd].str.extract(r"^[A-Za-z]+(\d+)$")[0])
    return n.astype("int64")


def _labels(text):
    """The labels of 'a','b,c',2023 -> [a, b,c, 2023]: commas inside quotes belong to the label (a model can
    have names like 'UCT_TRANSGRP LIMIT -F- A,,B')."""
    out, cur, q = [], [], None
    for ch in text:
        if q:
            if ch == q:
                q = None
            else:
                cur.append(ch)
        elif ch in "'\"":
            q = ch
        elif ch == ",":
            out.append("".join(cur).strip()); cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return out



def jl(x):
    """A Float64 as Julia prints it (string(x)): the shortest digits that read back the same, in plain notation when the
    decimal exponent is from -4 to 5, else d.ddde<exp>; always with a '.' (1.0, 1.0e-5, 1.2345e6, Inf, -Inf, NaN)."""
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "-0.0" if str(x).startswith("-") else "0.0"
    r = repr(float(x))
    m = re.fullmatch(r"(-?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?", r)
    sign, ip, fp, ex = m.group(1), m.group(2), m.group(3) or "", int(m.group(4) or 0)
    digits = (ip + fp).lstrip("0")
    point = len(ip) + ex if ip != "0" else ex - (len(fp) - len(fp.lstrip("0")))     # digits before the point
    digits = digits.rstrip("0") or "0"
    e10 = point - 1                                                                  # exponent of the first digit
    if -4 <= e10 < 6:
        if point <= 0:
            s = "0." + "0" * (-point) + digits
        elif point >= len(digits):
            s = digits + "0" * (point - len(digits)) + ".0"
        else:
            s = digits[:point] + "." + digits[point:]
    else:
        s = digits[0] + "." + (digits[1:] or "0") + "e" + str(e10)
    return sign + s



def _sig3(v):
    """Julia's round(v; sigdigits = 3), printed: Base.Math's arithmetic (digits = 3 - hidigit; x * 10^digits rounded
    to nearest, ties to even, / 10^digits, or with the step 10^-digits), so the same Float64 as Julia."""
    import math
    if v == 0 or v != v or v in (float("inf"), float("-inf")):
        return jl(float(v))
    d = 3 - (1 + math.floor(math.log10(abs(v))))
    if d >= 0:
        if d > 308:                              # (a subnormal: Julia gives it back as it is)
            return jl(float(v))
        inv = 10.0 ** d
        r = float(round(v * inv)) / inv
    else:
        step = 10.0 ** (-d)
        r = float(round(v / step)) * step
    return jl(r)



def _fix_examples(rows, kind):
    """The examples of compare_matrix's rhs and bnd lists, as it words them."""
    out = []
    for r in rows:
        if kind == "bounds":
            name, key, gj, lo, up, glo, gup = r
            out.append(f"column only here: {name}({key})" if gj == 0 else f"{name}({key}): bounds here [{jl(lo)}, {jl(up)}], GAMS [{jl(glo)}, {jl(gup)}]")
        else:
            name, key, gi, lo, up, glo, gup, cancel, rnd = r
            if gi == 0:
                out.append(f"row only here: {name}({key})")
            elif rnd:
                out.append(f"{name}({key}): right-hand side here [{jl(lo)}, {jl(up)}], GAMS [{jl(glo)}, {jl(gup)}]: "
                           f"equal within the rounding of constants of size {_sig3(cancel)} that cancel (decision 0007)")
            else:
                out.append(f"{name}({key}): right-hand side here [{jl(lo)}, {jl(up)}], GAMS [{jl(glo)}, {jl(gup)}]")
    return out


_DLL_DIRS = []


def _dll_folder(d):
    """The GDX library's folder, also added to the DLL search path on Windows. gams.transfer only puts the folder on
    PATH, and some Pythons (the Microsoft Store's, for one) do not look in PATH for the libraries a DLL needs: there
    gmdcclib64.dll does not load (WinError 126) unless its folder is added this way."""
    if d and os.name == "nt" and hasattr(os, "add_dll_directory") and os.path.isdir(d):
        _DLL_DIRS.append(os.add_dll_directory(d))
    return d


def system_directory(given=None):
    """Where the GDX library is: gamspy_base (pip: no GAMS installation needed) when installed, else the given GAMS
    system folder (or GAMS_DIR)."""
    try:
        import gamspy_base
        return _dll_folder(gamspy_base.directory)
    except ImportError:
        return _dll_folder(given or os.environ.get("GAMS_DIR"))


def read_jacobian(con, gdx, side, system_directory=None):
    """A jacobian GDX into DuckDB: side "first" -> tables orr (i, name, key, lo, up, cancel), oc (j, name, key, lo, up),
    oa (i, j, v); "second" -> gr, gc, ga (the same columns, no cancel). Names and labels upper case, the labels of a key
    joined by chr(31); EPS as 0.0; +-INF as +-inf. Returns the number of columns (x) of the file."""
    import numpy as np, pandas as pd
    import gams.transfer as gt
    sd = globals()["system_directory"](system_directory)
    c = gt.Container(gdx, system_directory=sd) if sd else gt.Container(gdx)
    num = lambda v: np.where(gt.SpecialValues.isEps(v), 0.0, v)
    rows, cols, ents = ("orr", "oc", "oa") if side == "first" else ("gr", "gc", "ga")
    for table, idx, setname, sym in ((rows, "i", "i", "e"), (cols, "j", "j", "x")):
        s = c[setname].records
        lab, text = s.iloc[:, 0].astype(str), s.iloc[:, 1].astype(str)
        m = text.str.strip().str.extract(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\((.*)\))?$")
        inner = m[1].fillna("")
        key = inner.str.replace(r"\s*,\s*", KEYSEP, regex=True).str.strip()
        q = inner.str.contains("['\"]", regex=True)
        if q.any():
            key[q] = [KEYSEP.join(_labels(t)) for t in inner[q]]
        names = pd.DataFrame({"lb": lab.values, idx: numbers(lab).values, "name": m[0].str.upper().values,
                              "key": key.str.upper().values})
        df = c[sym].records
        vals = pd.DataFrame({"lb": df.iloc[:, 0].astype(str).values, "lo": df["lower"].to_numpy(), "up": df["upper"].to_numpy()})
        con.register("n_", names)
        con.register("v_", vals)
        extra, join = "", ""
        if table == "orr":
            cr = c["cancel"].records if "cancel" in c and c["cancel"].records is not None else None
            con.register("c_", pd.DataFrame({"lb": cr.iloc[:, 0].astype(str).values, "cancel": cr.iloc[:, -1].to_numpy()}) if cr is not None and len(cr)
                         else pd.DataFrame({"lb": pd.Series([], dtype=str), "cancel": pd.Series([], dtype=float)}))
            extra, join = ", coalesce(c_.cancel, 0.0) as cancel", " left join c_ on c_.lb = n_.lb"
        con.execute(f"create or replace table {table} as select n_.{idx}, n_.name, n_.key, v_.lo, v_.up{extra} "
                    f"from v_ join n_ on n_.lb = v_.lb{join}")
        for t in ("n_", "v_") + (("c_",) if table == "orr" else ()):
            con.unregister(t)
    a = c["A"].records
    con.register("a_", pd.DataFrame({"i": numbers(a.iloc[:, 0].astype(str)).values,
                                     "j": numbers(a.iloc[:, 1].astype(str)).values, "v": num(a["value"].to_numpy())}))
    con.execute(f"create or replace table {ents} as select * from a_")
    con.unregister("a_")
    return len(c["x"].records)


def compare_core(con, here_columns, show=3, tol=TOL):
    """The comparison on the tables of read_jacobian (or views with the same columns: gr, gc, ga for the second
    matrix, orr, oc, oa for the first): (result dict, report text). here_columns: the columns of the first model, as
    the report shows them."""
    t0 = time.time()
    x = con.execute
    q = lambda s: x(s).fetchall()
    near = lambda a, b: f"(({a} = {b}) or (isfinite({a}) and isfinite({b}) and abs({a} - {b}) <= {tol} * greatest(abs({a}), abs({b})) + 1e-12))"
    within = lambda a, b, s: f"(({a} = {b}) or (isfinite({a}) and isfinite({b}) and abs({a} - {b}) <= {EPS64} * {s}))"
    # GAMS's rows and columns by name and key (a key seen twice: the last, as a Dict keeps it)
    x("create temp table grow as select name, key, arg_max(i, i) i, arg_max(lo, i) lo, arg_max(up, i) up from gr group by name, key")
    x("create temp table gcol as select name, key, arg_max(j, j) j, arg_max(lo, j) lo, arg_max(up, j) up from gc group by name, key")
    # this model's rows and columns -> GAMS's numbers (0: only here)
    x("create temp table rm as select o.i oi, o.name, o.key, o.lo, o.up, o.cancel, coalesce(g.i, 0) gi, g.lo glo, g.up gup "
      "from orr o left join grow g using (name, key)")
    x("create temp table cm as select row_number() over () pos, o.j oj, o.name, o.key, o.lo, o.up, coalesce(g.j, 0) gj, g.lo glo, g.up gup "
      "from oc o left join gcol g using (name, key)")
    rows_gams, cols_gams = q("select count(*) from grow")[0][0], q("select count(*) from gcol")[0][0]
    rows_here = q("select count(*) from rm")[0][0]
    rows_only_here = q("select count(*) from rm where gi = 0")[0][0]
    rows_only_gams = rows_gams - q("select count(distinct gi) from rm where gi <> 0")[0][0]
    cols_only_here = q("select count(*) from cm where gj = 0")[0][0]
    cols_only_gams = cols_gams - q("select count(distinct gj) from cm where gj <> 0")[0][0]
    lab = lambda c: f"replace({c}, chr(31), ',')"
    # column bounds
    bnd_off = q(f"select count(*) from cm where gj <> 0 and not ({near('lo', 'glo')} and {near('up', 'gup')})")[0][0]
    bnd = _fix_examples(q(f"select name, {lab('key')}, gj, lo, up, glo, gup from cm where gj = 0 or not ({near('lo', 'glo')} and {near('up', 'gup')}) order by pos limit {show}"), "bounds")
    # right-hand sides
    off = f"not ({near('lo', 'glo')} and {near('up', 'gup')})"
    rnd = f"(cancel > 0 and {within('lo', 'glo', 'cancel')} and {within('up', 'gup', 'cancel')})"
    rhs_off, rhs_rounding = q(f"select count(*) filter (where {off} and not {rnd}), count(*) filter (where {off} and {rnd}) from rm where gi <> 0")[0]
    rhs = _fix_examples(q(f"select name, {lab('key')}, gi, lo, up, glo, gup, cancel, {rnd} from rm where gi = 0 or {off} order by oi limit {show}"), "rhs")
    here_by = q("select 'column ' || name, count(*) from cm where gj = 0 group by all union all "
                "select 'row ' || name, count(*) from rm where gi = 0 group by all order by 1")
    if here_by:
        rhs.insert(0, "only here, by name: " + ", ".join(f"{k} {n}" for k, n in here_by))
    # entries: this model's, on GAMS's numbers, against GAMS's
    t1 = time.time()
    x("create temp table mine as select r.gi i, c.gj j, a.v v from oa a join rm r on r.oi = a.i join cm c on c.oj = a.j "
      "where r.gi <> 0 and c.gj <> 0")
    x("create temp table m_ as select coalesce(m.i, g.i) i, coalesce(m.j, g.j) j, m.v x, g.v y, "
      "case when m.v is null then 'only_gams' when g.v is null then 'only_here' "
      f"when {near('m.v', 'g.v')} then 'equal' else 'different' end kind from mine m full outer join ga g on m.i = g.i and m.j = g.j")
    entries_here = q("select count(*) from mine")[0][0]
    entries_gams = q("select count(*) from ga")[0][0]
    tot = dict(q("select kind, count(*) from m_ group by kind"))
    extra, missing_, different = tot.get("only_here", 0), tot.get("only_gams", 0), tot.get("different", 0)
    worst = q("select coalesce(max(abs(x - y) / greatest(abs(x), abs(y))), 0.0) from m_ where kind = 'different'")[0][0]
    largest, zeros_both = q("select coalesce(max(abs(x - y) / greatest(abs(x), abs(y))) filter (where x <> y and not (x = 0 and y = 0)), 0.0), "
                            "count(*) filter (where x = 0 and y = 0) from m_ where kind = 'equal'")[0]
    # by equation (GAMS's row name)
    x("create temp table gname as select i, name, key from grow")
    eqs = q("select g.name, count(*) filter (where kind <> 'only_here'), count(*) filter (where kind <> 'only_gams'), "
            "count(*) filter (where kind = 'equal'), count(*) filter (where kind = 'different'), count(*) filter (where kind = 'only_here'), "
            "count(*) filter (where kind = 'only_gams'), "
            "coalesce(max(abs(x - y) / greatest(abs(x), abs(y))) filter (where kind = 'equal' and x <> y and not (x = 0 and y = 0)), 0.0) "
            "from m_ join gname g on g.i = m_.i group by g.name")
    nrows = dict(q("select name, count(*) from grow group by name"))
    eqs.sort(key=lambda r: (-r[1], r[0]))
    # what differs, by (kind, equation, variable), with the first example in the order of GAMS's numbers
    det = q("select kind, gr.name, gc.name, count(*), arg_min(gr.key, m_.i::bigint * 4294967296 + m_.j), "
            "arg_min(gc.key, m_.i::bigint * 4294967296 + m_.j), arg_min(x, m_.i::bigint * 4294967296 + m_.j), "
            "arg_min(y, m_.i::bigint * 4294967296 + m_.j) from m_ join grow gr on gr.i = m_.i join gcol gc on gc.j = m_.j "
            "where kind <> 'equal' group by all")
    t2 = time.time()
    kindtext = {"different": "other value", "only_here": "only here", "only_gams": "only in GAMS"}
    details = []
    for kind, rn, cn, n, rk, ck, xv, yv in sorted(det, key=lambda r: (-r[3], r[0], r[1], r[2])):
        ex = (f"here {jl(xv)}, GAMS {jl(yv)}" if kind == "different" else f"here {jl(xv)}" if kind == "only_here" else f"GAMS {jl(yv)}")
        details.append({"kind": kindtext[kind], "equation": rn, "variable": cn, "entries": n,
                        "example": f"{rn}({rk.replace(KEYSEP, ',')}) x {cn}({ck.replace(KEYSEP, ',')}): {ex}"})
    same = rows_only_here + rows_only_gams + cols_only_here + cols_only_gams + extra + missing_ + different + rhs_off + bnd_off == 0
    out = []
    p = out.append
    p("\nMatrix against GAMS, entry by entry")
    p(f"rows       here {rows_here}   GAMS {rows_gams}   only here {rows_only_here}   only in GAMS {rows_only_gams}")
    p(f"columns    here {here_columns}   GAMS {cols_gams}   only here {cols_only_here}   only in GAMS {cols_only_gams}")
    p(f"entries    here {entries_here}   GAMS {entries_gams}   only here {extra}   only in GAMS {missing_}   other value {different}"
      + (f"   (largest relative difference {_sig3(worst)})" if different > 0 else ""))
    p(f"right-hand sides that differ {rhs_off}   column bounds that differ {bnd_off}"
      + (f"   right-hand sides equal within rounding of cancelled constants {rhs_rounding}" if rhs_rounding > 0 else ""))
    p(f"equal entries: largest relative difference {_sig3(largest)} (tolerance {jl(tol)}); {zeros_both} are zero on both sides (EPS in GAMS)")
    p("\n" + "equation".ljust(16) + "rows".rjust(10) + "entries GAMS".rjust(14) + "here".rjust(12) + "equal".rjust(12) + "other".rjust(8)
      + "only here".rjust(11) + "only GAMS".rjust(11) + "   largest rel. diff. of equal entries")
    equations = []
    for name, eg, eh, eq, ed, oh, og, lw in eqs:
        p(name.ljust(16) + str(nrows.get(name, 0)).rjust(10) + str(eg).rjust(14) + str(eh).rjust(12) + str(eq).rjust(12) + str(ed).rjust(8)
          + str(oh).rjust(11) + str(og).rjust(11) + "   " + _sig3(lw))
        equations.append({"name": name, "rows": nrows.get(name, 0), "entries_gams": eg, "entries_here": eh, "equal": eq, "different": ed,
                          "only_here": oh, "only_gams": og, "largest_relative_difference": lw})
    for d in details:
        p("  " + d["kind"].ljust(13) + d["equation"].ljust(14) + " x " + d["variable"].ljust(12) + str(d["entries"]).rjust(9) + "   e.g. " + d["example"])
    for s in rhs + bnd:
        p("  " + s)
    p("the same linear program as GAMS" if same else "NOT the same linear program as GAMS")
    res = {"rows_gams": rows_gams, "columns_gams": cols_gams, "entries_here": entries_here, "entries_gams": entries_gams,
           "rows_only_here": rows_only_here, "rows_only_gams": rows_only_gams, "columns_only_here": cols_only_here,
           "columns_only_gams": cols_only_gams, "entries_only_here": extra, "entries_only_gams": missing_, "entries_different": different,
           "worst_relative_difference": worst, "rhs_different": rhs_off, "rhs_rounding": rhs_rounding, "bounds_different": bnd_off,
           "details": details, "examples": rhs + bnd, "tolerance": tol, "same_model": same, "largest_relative_difference_equal": largest,
           "entries_zero_both": zeros_both, "equations": equations,
           "seconds": {"rows_columns": round(t1 - t0, 1), "entries": round(t2 - t1, 1), "all": round(time.time() - t0, 1)}}
    return res, "\n".join(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    opt = lambda o: argv[argv.index(o) + 1] if o in argv else None
    con = _duck(opt("--memory"), opt("--temp"))
    n = read_jacobian(con, argv[0], "first", opt("--gams-dir"))
    read_jacobian(con, argv[1], "second", opt("--gams-dir"))
    res, text = compare_core(con, n)
    print(text)
    if opt("--json"):
        json.dump({"matrix": res}, open(opt("--json"), "w"), indent=1)
    return 0 if res["same_model"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
