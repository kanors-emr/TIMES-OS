# SPDX-License-Identifier: GPL-3.0-or-later
"""GDX -> SQLite, one table per symbol (the layout gamspy writes for a db3 export).

Sets: one column per domain; parameters: domain columns + 'value'; scalars: 'value'.
Universe domains are named 'uni'; if a domain name repeats, every column gets a _<pos> suffix.
EPS is written as 0.0.

Needs:  pip install "gamsapi[transfer]" gamspy_base      (without gamspy_base: the folder of a GAMS installation,
        as third argument or in the environment variable GAMS_DIR)
Usage:  python tools/gdx2sqlite.py dump.gdx out.db3 [GAMS folder]
"""
import sys, os, sqlite3
import gams.transfer as gt, numpy as np


_DLL_DIRS = []


def _dll_folder(d):
    """The GDX library's folder, also added to the DLL search path on Windows. gams.transfer only puts the folder on
    PATH, and some Pythons (the Microsoft Store's, for one) do not look in PATH for the libraries a DLL needs: there
    gmdcclib64.dll does not load (WinError 126) unless its folder is added this way."""
    if d and os.name == "nt" and hasattr(os, "add_dll_directory") and os.path.isdir(d):
        _DLL_DIRS.append(os.add_dll_directory(d))
    return d


def system_directory(given=None):
    """Where the GDX library is: gamspy_base (pip) when installed, else the given GAMS installation."""
    try:
        import gamspy_base
        return _dll_folder(gamspy_base.directory)
    except ImportError:
        return _dll_folder(given or os.environ.get("GAMS_DIR"))


def colnames(dom):
    names = ["uni" if d == "*" else d for d in dom]
    if len(set(names)) < len(names):
        names = [f"{n}_{i}" for i, n in enumerate(names)]
    return names


def write_var(con, name, s, kind):
    """Variables / equations: domain columns + level, marginal, lower, upper (EPS -> 0)."""
    dom = [d if isinstance(d, str) else d.name for d in s.domain]
    cols = [f"d{i}" for i in range(len(dom))]
    decl = ", ".join(f'"{x}" TEXT' for x in cols)
    decl += (", " if decl else "") + "level REAL, marginal REAL, lower REAL, upper REAL"
    con.execute(f'create table "{name}" ({decl})')
    _meta.append((name, kind.lower(), len(dom)))
    df = s.records
    if df is None or len(df) == 0:
        return 0
    df = df.iloc[:, :len(cols) + 4].copy()
    df.columns = cols + ["level", "marginal", "lower", "upper"]
    for c in ("level", "marginal", "lower", "upper"):
        v = df[c].to_numpy()
        v = np.where(gt.SpecialValues.isEps(v), 0.0, v)
        v = np.where(np.isposinf(v), 1e300, np.where(np.isneginf(v), -1e300, v))
        df[c] = v
    for c in cols:
        df[c] = df[c].astype(str)
    con.executemany(f'insert into "{name}" values ({",".join("?" * len(df.columns))})', df.itertuples(index=False, name=None))
    return 1


def convert(gdx, out, gams_dir=None, solution_only=False):
    """solution_only: variables and equations only (all that the comparison with the GAMS solution reads)."""
    sd = system_directory(gams_dir)
    c = gt.Container(gdx, system_directory=sd) if sd else gt.Container(gdx)
    if os.path.exists(out):
        os.remove(out)
    con = sqlite3.connect(out)
    n = 0
    meta = []
    global _meta
    _meta = meta
    for name, s in c.data.items():
        kind = type(s).__name__
        if kind in ("Variable", "Equation"):
            n += write_var(con, name, s, kind)
            continue
        if kind not in ("Set", "Parameter") or solution_only:
            continue
        meta.append((name, kind.lower(), len(s.domain)))
        dom = [d if isinstance(d, str) else d.name for d in s.domain]
        cols = colnames(dom)
        df = s.records
        decl = ", ".join(f'"{x}" TEXT' for x in cols)
        if kind == "Parameter":
            decl += (", " if decl else "") + '"value" REAL'
        con.execute(f'create table "{name}" ({decl})')
        if df is None or len(df) == 0:
            continue
        df = df.copy()
        if kind == "Set":
            df = df.iloc[:, :len(cols)]
            df.columns = cols
        else:
            df.columns = cols + ["value"]
            v = df["value"].to_numpy()
            v = np.where(gt.SpecialValues.isEps(v), 0.0, v)
            df["value"] = np.where(np.isposinf(v), 1e300, np.where(np.isneginf(v), -1e300, v))
        for col in cols:
            df[col] = df[col].astype(str)
        con.executemany(f'insert into "{name}" values ({",".join("?" * len(df.columns))})', df.itertuples(index=False, name=None))
        n += 1
    con.execute("create table __symbols (name TEXT, kind TEXT, dim INTEGER)")
    con.executemany("insert into __symbols values (?,?,?)", meta)
    con.commit(); con.close()
    return n


KEYSEP = "\x1f"     # joins the labels of a row or column key: a label may contain '|' or ','


def numbers(labels):
    """The numbers of CONVERT's labels e<i> / x<j> (a pandas Series of str), as int64; the columns of SOS and
    semi-continuous variables are labelled s1s1('4430'), sc4431 etc. (number() of convert_jacobian, vectorised)."""
    n = labels.str.extract(r"^[a-z](\d+)$")[0]
    odd = n.isna()
    if odd.any():
        n[odd] = labels[odd].str.extract(r"'(\d+)'")[0].fillna(labels[odd].str.extract(r"^[A-Za-z]+(\d+)$")[0])
    return n.astype("int64")


def _labels(text):
    """The labels of 'a','b,c',2023 -> [a, b,c, 2023]: commas inside quotes belong to the label (a commodity name
    may hold commas)."""
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


def convert_jacobian(gdx, out, gams_dir=None):
    """The matrix that GAMS writes with the CONVERT solver (option file: `jacobian jacobian.gdx`) -> SQLite.

    rows(i, name, key, lower, upper), cols(j, name, key, lower, upper), a(i, j, value).  i and j are the numbers
    in e<i> and x<j>; name is the equation or variable, key its labels joined by KEYSEP, chr(31) (upper case).  lower/upper of a
    row are its right-hand side bounds, with all variable terms on the left.  An EPS coefficient is 0.0."""
    import re
    sd = system_directory(gams_dir)
    c = gt.Container(gdx, system_directory=sd) if sd else gt.Container(gdx)
    if os.path.exists(out):
        os.remove(out)
    con = sqlite3.connect(out)

    def number(label, prefix):
        """The number of e<i> / x<j>; the columns of SOS and semi-continuous variables are labelled s1s1('4430'), sc4431 etc."""
        t = str(label)
        if t[len(prefix):].isdigit() and t.startswith(prefix):
            return int(t[len(prefix):])
        m = re.search(r"'(\d+)'", t) or re.match(r"[A-Za-z]+(\d+)$", t)        # s1s1('4430'), sc4431
        return int(m.group(1))

    def names(sym, prefix):
        res = {}
        for label, text in sym.records.itertuples(index=False, name=None):
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(?:\((.*)\))?$", text.strip())
            key = KEYSEP.join(_labels(m.group(2))) if m.group(2) else ""
            res[label] = (number(label, prefix), m.group(1).upper(), key.upper())
        return res

    def num(v):
        v = np.where(gt.SpecialValues.isEps(v), 0.0, v)
        return np.where(np.isposinf(v), 1e300, np.where(np.isneginf(v), -1e300, v))

    for table, idx, setname, sym, prefix in (("rows", "i", "i", "e", "e"), ("cols", "j", "j", "x", "x")):
        nm = names(c[setname], prefix)
        df = c[sym].records
        lo, up = num(df["lower"].to_numpy()), num(df["upper"].to_numpy())
        con.execute(f"create table {table} ({idx} INTEGER, name TEXT, key TEXT, lower REAL, upper REAL)")
        con.executemany(f"insert into {table} values (?,?,?,?,?)",
                        [nm[l] + (float(a), float(b)) for l, a, b in zip(df.iloc[:, 0].astype(str), lo, up)])
    con.execute("create table meta (name TEXT, value TEXT)"); con.execute("insert into meta values (?, ?)", ("keysep", KEYSEP))
    a = c["A"].records
    con.execute("create table a (i INTEGER, j INTEGER, value REAL)")
    def numbers(col, prefix):
        t = col.astype(str)
        try:
            return t.str[1:].astype(int).tolist()
        except ValueError:                      # SOS / semi-continuous columns (s1s1('4430')): one by one
            return [number(l, prefix) for l in t]
    con.executemany("insert into a values (?,?,?)", zip(numbers(a.iloc[:, 0], "e"), numbers(a.iloc[:, 1], "x"),
                                                        num(a["value"].to_numpy()).tolist()))
    con.commit(); con.close()
    return len(a)


if __name__ == "__main__":
    print(convert(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), "non-empty symbols written")
