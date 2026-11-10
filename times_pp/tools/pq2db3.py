# SPDX-License-Identifier: GPL-3.0-or-later
"""model.db3 from the Parquet folder that times_pp writes in its place (TIMESPP_DB3_STREAM=1, timespp/stream.py).

  python tools/pq2db3.py <model_parquet folder> [<model.db3>]       (default: model.db3 beside the folder)

The same tables as export.to_sqlite writes them: every table of __symbols, in that order, created as there
(i0.. VARCHAR, value DOUBLE; for a variable d0.. VARCHAR, level, marginal, lower, upper DOUBLE), its rows in the
file's order; then the steps of a myopic run (model_steps.db3 beside the folder: __steps and the __step tables, as
created there); then __casing, __texts, __encoding, __symbols and __tjb as Python's sqlite3 writes them. The file is
written as <model.db3>.part and renamed when complete. 64 KiB pages: the content is the same as today's file, the
page layout is not (SQLite writes larger pages faster)."""
import os, sys, time, sqlite3

NUM = ("value", "level", "marginal", "lower", "upper")
META = (("__casing", "label TEXT, text TEXT"), ("__texts", "name TEXT, element TEXT, text TEXT"),
        ("__encoding", "encoding TEXT"), ("__symbols", "name TEXT, kind TEXT, dim INTEGER"), ("__tjb", "token INTEGER"))


def convert(folder, out):
    import duckdb
    folder = os.path.abspath(folder)
    tmp = out + ".part"
    for p in (out, tmp):
        if os.path.exists(p):
            os.remove(p)
    c = sqlite3.connect(tmp)
    c.execute("pragma page_size=65536")
    c.execute("create table __x (a)"); c.execute("drop table __x"); c.commit(); c.close()
    pq = lambda n: os.path.join(folder, n + ".parquet").replace("\\", "/").replace("'", "''")
    con = duckdb.connect()
    try:
        con.execute("LOAD sqlite")
    except Exception:
        con.execute("INSTALL sqlite"); con.execute("LOAD sqlite")
    x = con.execute
    syms = x(f"select name, kind, dim from read_parquet('{pq('__symbols')}')").fetchall()
    x(f"ATTACH '{tmp.replace(chr(39), chr(39) * 2)}' AS o_ (TYPE sqlite)")
    x("BEGIN TRANSACTION")                          # one commit for the file, as export.py
    for name, kind, dim in syms:
        cols = [r[0] for r in x(f"describe select * from read_parquet('{pq(name)}')").fetchall()]
        decl = ", ".join(f'"{c}" DOUBLE' if c in NUM else f'"{c}" VARCHAR' for c in cols)
        x(f'create table o_."{name}" ({decl})')
        x(f"insert into o_.\"{name}\" select * from read_parquet('{pq(name)}')")
    x("COMMIT")
    x("DETACH o_")
    c = sqlite3.connect(tmp)
    steps = os.path.join(os.path.dirname(folder), "model_steps.db3")
    if os.path.exists(steps):                       # a myopic run: its steps, where export.to_sqlite writes them
        c.execute("attach database ? as s", (steps,))
        for name, sql in c.execute("select name, sql from s.sqlite_master where type = 'table' and name <> '__tjb' "
                                   "order by rowid").fetchall():
            c.execute(sql)
            c.execute(f'insert into main."{name}" select * from s."{name}"')
        c.commit()
        c.execute("detach database s")
    for n, decl in META:
        if not os.path.exists(os.path.join(folder, n + ".parquet")):
            continue
        rows = x(f"select * from read_parquet('{pq(n)}')").fetchall()
        c.execute(f"create table {n} ({decl})")
        if rows:
            c.executemany(f"insert into {n} values ({','.join('?' * len(rows[0]))})", rows)
    c.commit()
    c.close()
    con.close()
    os.replace(tmp, out)
    return len(syms)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    folder = argv[0].rstrip("/\\")
    out = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(folder)), "model.db3")
    t = time.time()
    n = convert(folder, out)
    print(f"{n} tables -> {out} in {time.time() - t:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
