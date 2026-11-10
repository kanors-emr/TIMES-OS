# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the Veda result files of a run: <scenario>.vd, .vde and .vds.

    python -m timesrpt.write <model.db3> <solution.db3> <out folder> <scenario> <TIMES source | -> [<preprocess.json>]

"-" for the TIMES source: the files of TIMES v4.9.8 carried with the port (times_pp/timespp/times_src).

model.db3 is what times_pp writes, solution.db3 what times_eq writes (or a GAMS GDX converted to SQLite). The three
files go to <out folder>/<scenario>.vd/.vde/.vds; Veda imports them as a scenario next to the GAMS one. The
Veda attributes are those of times2veda.vdd in the TIMES source that the port fills (vd.PORTED). preprocess.json
gives the $SET switches of the run file, for the report options (switches.py).

Prints one line per file and, when the run sets report options the port does not cover, which attributes are
missing and why (switches.py); writes report.json next to the files with the same. Exit status 0 when written.
"""
from __future__ import annotations
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "times_pp"))

from timesrpt.load import open_case          # noqa: E402
from timesrpt import rptmisc, vd, vsets, switches, stochastic  # noqa: E402
from timespp.controls import run_controls  # noqa: E402
from timespp.load import BUNDLED_SRC  # noqa: E402

def write(model, solution, out, scenario, src, env=None):
    t0 = time.time()
    src = BUNDLED_SRC if src in (None, "", "-") else src
    if stochastic.on(env):
        return write_stochastic(model, solution, out, scenario, src, env, t0)
    db = open_case(model, solution)
    t_open = time.time()                           # reading model.db3 and the solution: the hand-off
    db.env = dict(env or {})
    db.ctl, _ = run_controls(dict(db.env))          # MID_YEAR, CTST...: the preprocessor's db has them, model.db3 not
    unported, unverified = switches.check(db)
    held = switches.withheld(db)
    rptmisc.run(db)
    vdd = os.path.join(src, "times2veda.vdd")
    entries, not0 = vd.vdd_entries(vdd)
    by_attr = {}
    for attr, gams, indexes in entries:
        by_attr.setdefault(attr, []).append((gams, indexes))
    use, absent = [], []
    for attr, sources in by_attr.items():
        if all(g in vd.PORTED and g.upper() not in held for g, _ in sources):
            use.extend((attr, g, ix) for g, ix in sources)
        else:
            absent.append(attr)
    rows, _ = vd.produced_rows(db, use, not0)
    t_rows = time.time()
    os.makedirs(out, exist_ok=True)
    stem = os.path.join(out, scenario)
    enc = getattr(db, "dd_encoding", "utf-8")      # the bytes of the DD files' texts, as GAMS writes them
    vd.write_vd(stem + ".vd", scenario, rows, enc)
    vd.write_quads(stem + ".vde", vsets.descriptions(db, vdd, src), enc)
    vd.write_quads(stem + ".vds", vsets.membership(db, vdd), enc)
    info = {"scenario": scenario, "files": [stem + e for e in (".vd", ".vde", ".vds")],
            "attributes": {a: len(r) for a, r in sorted(rows.items())},
            "attributes_not_ported": sorted(absent),
            "options_not_ported": unported, "options_not_verified": unverified,
            "solution_symbols_not_read": getattr(db, "solution_skipped", []),
            "seconds": round(time.time() - t0, 1),
            "phases": {"read model.db3 and solution": round(t_open - t0, 1), "report rows": round(t_rows - t_open, 1),
                       "write files": round(time.time() - t_rows, 1)}}
    with open(stem + "_report.json", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    return info


def write_stochastic(model, solution, out, scenario, src, env, t0):
    """A run with STAGES: the reports of rptmain.stc (stochastic.py) in the attributes of times2veda_stc.vdd, which
    have the dimension Sow."""
    vdd = os.path.join(src, "times2veda_stc.vdd")
    if not os.path.isfile(vdd):
        raise SystemExit(f"{vdd} is not there: the Veda file of a run with STAGES follows times2veda_stc.vdd "
                         "(give the TIMES source folder)")
    entries, not0 = vd.vdd_entries(vdd)
    by_attr = {}
    for attr, gams, indexes in entries:
        by_attr.setdefault(attr, []).append((gams, indexes))
    use, absent = [], []
    for attr, sources in by_attr.items():
        if all(stochastic.ported(g, ix) for g, ix in sources):
            use.extend((attr, g, ix) for g, ix in sources)
        else:
            absent.append(attr)
    db, last = stochastic.report_db(model, solution, env, use)
    t_rows = time.time()
    rows, _ = vd.produced_rows(db, use, not0, vd.FIELDS_STC)
    os.makedirs(out, exist_ok=True)
    stem = os.path.join(out, scenario)
    enc = getattr(last, "dd_encoding", "utf-8")
    vd.write_vd(stem + ".vd", scenario, rows, enc, vd.FIELDS_STC)
    # initmty.stc 19 (SET UC_N / OBJZ, OBJ1 /) brings the label OBJZ in before solsetv.v3 names the attribute ObjZ
    texts = [("Attribute", p, "OBJZ", t) if d == "Attribute" and e.upper() == "OBJZ" else (d, p, e, t)
             for d, p, e, t in vsets.descriptions(last, vdd, src)]
    vd.write_quads(stem + ".vde", texts, enc)
    vd.write_quads(stem + ".vds", vsets.membership(last, vdd), enc)
    info = {"scenario": scenario, "files": [stem + e for e in (".vd", ".vde", ".vds")],
            "attributes": {a: len(r) for a, r in sorted(rows.items())},
            "attributes_not_ported": sorted(absent),
            "options_not_ported": db.not_ported, "options_not_verified": [],
            "seconds": round(time.time() - t0, 1),
            "phases": {"reports of each SOW": round(t_rows - t0, 1), "write files": round(time.time() - t_rows, 1)}}
    with open(stem + "_report.json", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    return info


def main(argv):
    if len(argv) < 5:
        print(__doc__)
        return 2
    model, solution, out, scenario, src = argv[:5]
    env = {}
    if len(argv) > 5 and os.path.isfile(argv[5]):
        env = json.load(open(argv[5], encoding="utf-8")).get("switches", {})
    info = write(model, solution, out, scenario, src, env)
    n = sum(info["attributes"].values())
    print(f"  wrote {scenario}.vd ({n} rows, {len(info['attributes'])} attributes), .vde and .vds in {info['seconds']} s")
    for x in info["options_not_ported"]:
        print(f"  NOT IN THE VD FILE   {x}")
    for x in info["options_not_verified"]:
        print(f"  not yet compared with GAMS   {x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
