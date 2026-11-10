# SPDX-License-Identifier: GPL-3.0-or-later
"""The matrix check (TIMES.py --check) without a second build: both matrices as Parquet, compared in DuckDB.

  python tools/matrix_pq.py ours <write_matrix folder> <out folder>        this model's matrix -> Parquet
  python tools/matrix_pq.py gams <matrix_jacobian.gdx> <out folder> [GAMS system folder]   GAMS's (CONVERT) -> Parquet
  python tools/matrix_pq.py compare <ours folder> <gams folder> [--json out.json] [--memory 16GB] [--temp folder]

`ours`: what times_eq's write_matrix (`run_case.jl --matrix-out`) wrote after the normal run's build. `gams`: what
GAMS's CONVERT solver writes (`jacobian matrix_jacobian.gdx`, as TIMES.py's write_gams_matrix asks), read as
gdx2sqlite.convert_jacobian reads it (names upper case, the labels of a key joined by chr(31), EPS as 0.0). Each folder:
rows.parquet (i, name, key, lower, upper[, cancel]), cols.parquet (j, name, key, lower, upper), a.parquet (i, j, value).

`compare` applies compare_matrix's rules (times_eq/src/compare.jl) exactly: rows and columns matched by name and key;
every coefficient on both sides, equal within a relative 1e-9 (+1e-12); zero on both sides counts as equal (EPS in
GAMS); right-hand sides and column bounds the same, a right-hand side made of constants that cancel equal within 64
machine epsilons of their size. It prints the same report and returns (and writes with --json)
the same fields as compare_matrix, under "matrix". The join runs in DuckDB on all processors, spilling to disk past
--memory. Where compare_matrix shows the first few examples in the order of a Julia Dict (which is not the same from
one session to the next), this shows the first in the order of the rows' names: the counts are the same, examples
of a count above `show` may be other ones."""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare_jacobian

KEYSEP = "\x1f"
TOL = 1e-9
EPS64 = 64 * 2.220446049250313e-16           # 64 * eps(Float64): decision 0007


def _duck(memory=None, temp=None):
    import duckdb
    con = duckdb.connect()
    if memory:
        con.execute(f"SET memory_limit='{memory}'")
    if temp:
        os.makedirs(temp, exist_ok=True)
        con.execute(f"SET temp_directory='{temp.replace(chr(39), chr(39) * 2)}'")
    return con


def _p(folder, name):
    return os.path.join(folder, name).replace("\\", "/").replace("'", "''")


# ------------------------------------------------------------------------------------------------ this model
def ours(src, out):
    """write_matrix's binary columns -> rows.parquet (i, name, key, lower, upper, cancel), cols.parquet (j, name, key,
    lower, upper), a.parquet (i, j, value), meta.json."""
    import numpy as np, pandas as pd
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(src, "meta.json")))
    rd = lambda n, t: np.fromfile(os.path.join(src, n), dtype=t)
    names = open(os.path.join(src, "names.txt"), encoding="utf-8").read().split("\n")[:-1]
    labels = open(os.path.join(src, "labels.txt"), encoding="utf-8").read().split("\n")[:-1]
    con = _duck()
    con.register("names_", pd.DataFrame({"id": np.arange(len(names), dtype=np.int32), "name": names}))
    con.register("labels_", pd.DataFrame({"id": np.arange(1, len(labels) + 1, dtype=np.int32), "l": labels}))

    def keyed(kind, dims, first, extra):
        d = {first[0]: first[1], "name_id": rd(f"{kind}_name.i32", "<i4")}
        for n in range(1, dims + 1):
            d[f"k{n}"] = rd(f"{kind}_k{n}.i32", "<i4")
        for c in extra:
            d[c] = rd(f"{kind}_{c}.f64", "<f8")
        con.register("t_", pd.DataFrame(d, copy=False))
        joins = " ".join(f"left join labels_ l{n} on l{n}.id = t_.k{n}" for n in range(1, dims + 1))
        key = f"concat_ws(chr(31), {', '.join(f'l{n}.l' for n in range(1, dims + 1))})" if dims else "''"
        con.execute(f"COPY (select t_.{first[0]}, n_.name, {key} as key, {', '.join('t_.' + c for c in extra)} from t_ "
                    f"join names_ n_ on n_.id = t_.name_id {joins} order by t_.{first[0]}) TO '{_p(out, kind + '.parquet')}' (FORMAT parquet)")
        con.unregister("t_")

    nrow = meta["rows"]
    keyed("rows", meta["row_dims"], ("i", np.arange(1, nrow + 1, dtype=np.int32)), ["lower", "upper", "cancel"])
    keyed("cols", meta["col_dims"], ("j", rd("cols_j.i32", "<i4")), ["lower", "upper"])
    con.register("a_", pd.DataFrame({"i": rd("a_i.i32", "<i4"), "j": rd("a_j.i32", "<i4"), "value": rd("a_value.f64", "<f8")}, copy=False))
    con.execute(f"COPY a_ TO '{_p(out, 'a.parquet')}' (FORMAT parquet)")
    json.dump(meta, open(os.path.join(out, "meta.json"), "w"))
    return {"rows": nrow, "columns": meta["columns"], "entries": meta["entries"], "seconds": round(time.time() - t0, 1)}


# ------------------------------------------------------------------------------------------------ GAMS
def _keys(prefix, labels_texts):
    """The (index number, NAME, KEY) of CONVERT's set texts 'EQ(a,b)', as gdx2sqlite.convert_jacobian makes them (its
    names()), vectorised: a text with a quote is parsed by gdx2sqlite._labels (commas inside quotes belong to the
    label), the others split at commas; each label stripped; NAME and KEY upper case."""
    import pandas as pd
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gdx2sqlite
    labels, text = labels_texts
    m = text.str.strip().str.extract(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\((.*)\))?$")
    inner = m[1]
    key = inner.fillna("").str.replace(r"\s*,\s*", KEYSEP, regex=True).str.strip()
    q = inner.fillna("").str.contains("['\"]", regex=True)
    if q.any():
        key[q] = [KEYSEP.join(gdx2sqlite._labels(s)) for s in inner[q]]
    return gdx2sqlite.numbers(labels), m[0].str.upper(), key.str.upper()


def gams(gdx, out, gams_dir=None):
    """CONVERT's matrix_jacobian.gdx -> rows.parquet (i, name, key, lower, upper), cols.parquet (j, ...), a.parquet
    (i, j, value): convert_jacobian's content (+-inf as +-1e300, EPS as 0.0), as Parquet."""
    import numpy as np, pandas as pd
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gdx2sqlite
    import gams.transfer as gt
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    sd = gdx2sqlite.system_directory(gams_dir)
    c = gt.Container(gdx, system_directory=sd) if sd else gt.Container(gdx)
    t_read = time.time() - t0

    def num(v):
        v = np.where(gt.SpecialValues.isEps(v), 0.0, v)
        return np.where(np.isposinf(v), 1e300, np.where(np.isneginf(v), -1e300, v))

    con = _duck()
    for table, idx, setname, sym, prefix in (("rows", "i", "i", "e", "e"), ("cols", "j", "j", "x", "x")):
        s = c[setname].records
        n, nm, key = _keys(prefix, (s.iloc[:, 0].astype(str), s.iloc[:, 1].astype(str)))
        names = pd.DataFrame({"label": s.iloc[:, 0].astype(str).values, idx: n.values, "name": nm.values, "key": key.values})
        df = c[sym].records
        vals = pd.DataFrame({"label": df.iloc[:, 0].astype(str).values, "lower": num(df["lower"].to_numpy()), "upper": num(df["upper"].to_numpy())})
        con.register("n_", names); con.register("v_", vals)
        con.execute(f"COPY (select n_.{idx}, n_.name, n_.key, v_.lower, v_.upper from v_ join n_ using (label) order by n_.{idx}) "
                    f"TO '{_p(out, table + '.parquet')}' (FORMAT parquet)")
        con.unregister("n_"); con.unregister("v_")
    a = c["A"].records
    con.register("a_", pd.DataFrame({"i": gdx2sqlite.numbers(a.iloc[:, 0].astype(str)).values,
                                     "j": gdx2sqlite.numbers(a.iloc[:, 1].astype(str)).values,
                                     "value": num(a["value"].to_numpy())}))
    con.execute(f"COPY a_ TO '{_p(out, 'a.parquet')}' (FORMAT parquet)")
    return {"entries": len(a), "seconds": round(time.time() - t0, 1), "read_gdx_seconds": round(t_read, 1)}


# ------------------------------------------------------------------------------------------------ compare
jl = None                                    # (the comparison and its printing: compare_jacobian.py)

def compare(ours_dir, gams_dir, show=3, tol=TOL, memory=None, temp=None):
    t0 = time.time()
    con = _duck(memory, temp)
    x = con.execute
    q = lambda s: x(s).fetchall()
    meta = json.load(open(os.path.join(ours_dir, "meta.json")))
    inf = lambda c: f"(case when {c} >= 1e299 then 'inf'::double when {c} <= -1e299 then '-inf'::double else {c} end)"
    near = lambda a, b: f"(({a} = {b}) or (isfinite({a}) and isfinite({b}) and abs({a} - {b}) <= {tol} * greatest(abs({a}), abs({b})) + 1e-12))"
    within = lambda a, b, s: f"(({a} = {b}) or (isfinite({a}) and isfinite({b}) and abs({a} - {b}) <= {EPS64} * {s}))"
    x(f"create view gr as select i, name, key, {inf('lower')} lo, {inf('upper')} up from read_parquet('{_p(gams_dir, 'rows.parquet')}')")
    x(f"create view gc as select j, name, key, {inf('lower')} lo, {inf('upper')} up from read_parquet('{_p(gams_dir, 'cols.parquet')}')")
    x(f"create view ga as select i, j, value v from read_parquet('{_p(gams_dir, 'a.parquet')}')")
    x(f"create view orr as select i, name, key, lower lo, upper up, cancel from read_parquet('{_p(ours_dir, 'rows.parquet')}')")
    x(f"create view oc as select j, name, key, lower lo, upper up from read_parquet('{_p(ours_dir, 'cols.parquet')}')")
    x(f"create view oa as select i, j, value v from read_parquet('{_p(ours_dir, 'a.parquet')}')")
    return compare_jacobian.compare_core(con, meta["jump_columns"], show, tol)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    what = argv[0]
    if what == "ours":
        print(json.dumps(ours(argv[1], argv[2])))
    elif what == "gams":
        print(json.dumps(gams(argv[1], argv[2], argv[3] if len(argv) > 3 else None)))
    elif what == "compare":
        opt = lambda o: argv[argv.index(o) + 1] if o in argv else None
        res, text = compare(argv[1], argv[2], memory=opt("--memory"), temp=opt("--temp"))
        print(text)
        if opt("--json"):
            json.dump({"matrix": res}, open(opt("--json"), "w"), indent=1)
        return 0 if res["same_model"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
