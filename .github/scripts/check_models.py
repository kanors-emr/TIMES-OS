# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the models listed in models/ci_models.txt on the open chain. A verified model (expected.json) must reproduce
its published GAMS result; a contributed one (no expected.json) must come out SOLVED or UNSUPPORTED, never ERROR. No GAMS is needed: the comparison is with expected.json (and gams_solution.db3 /
gams_matrix.db3 when the case has them).

    python .github/scripts/check_models.py [models/ci_models.txt]

A case whose GAMS matrix is published (gams_matrix.db3) must come out SAME, i.e. the same matrix entry by entry;
a case without it can only be held to its sizes and objective (SAME / SAME OBJECTIVE, or SOLVED with the expected
objective). Every case that solved must have its Veda result files, exit status 0 and no NOT WRITTEN line in its report.
Exit status 1 otherwise.
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
lst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "models", "ci_models.txt")
cases = [l.strip() for l in open(lst, encoding="utf-8") if l.strip() and not l.startswith("#")]
bad = []
for c in cases:
    folder = os.path.join(ROOT, "models", c)
    verified = os.path.exists(os.path.join(folder, "expected.json"))
    want = json.load(open(os.path.join(folder, "expected.json"), encoding="utf-8")) if verified else None
    out = os.path.join(ROOT, "runs", "ci")
    copy = os.path.join(out, "input", c)              # a run writes results into its run folder: models/ stays as it is
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(folder, copy)
    code = subprocess.call([sys.executable, os.path.join(ROOT, "TIMES.py"), "run", copy, "--out", out, "--quiet"])
    rep_path = os.path.join(out, c, f"report_{c}.json")
    if not os.path.exists(rep_path):
        bad.append(f"{c}: no report (exit {code})"); print(f"{c}: no report"); continue
    rep = json.load(open(rep_path, encoding="utf-8"))
    verdict = (rep.get("verdict") or "").split(":")[0]
    obj = (rep.get("julia") or {}).get("objective")
    # a run that solved left its Veda result files, and every file asked for; a report's NOT WRITTEN line is a failure
    solved = verdict in ("SAME", "SAME OBJECTIVE", "SOLVED")
    if rep.get("files_not_written"):
        bad.append(f"{c}: NOT WRITTEN: {'; '.join(rep['files_not_written'])}")
    if solved:
        scen = os.path.splitext(os.path.basename(rep["input"]["run_file"]))[0] + "_julia"
        lost = [e for e in (".vd", ".vde", ".vds") if not os.path.isfile(os.path.join(out, c, scen + e))]
        if lost:
            bad.append(f"{c}: no {scen}{', '.join(lost)}")
    if code != (3 if verdict == "UNSUPPORTED" else 0):
        bad.append(f"{c}: exit status {code} with the verdict {rep.get('verdict')}")
    if verified:
        ok_obj = obj is not None and abs(obj - want["objective"]) <= 1e-9 * abs(want["objective"])
        has_matrix = os.path.exists(os.path.join(folder, "gams_matrix.db3"))
        ok = ok_obj and ((verdict == "SAME") if has_matrix else verdict in ("SAME", "SAME OBJECTIVE", "SOLVED"))
        print(f"{c}: {rep.get('verdict')}; objective {obj} (expected {want['objective']})")
    else:                                                    # a contributed model: the chain must not fail on it
        ok = verdict in ("SOLVED", "UNSUPPORTED")
        print(f"{c} (contributed, not verified): {rep.get('verdict')}; objective {obj}")
    if not ok:
        bad.append(f"{c}: {rep.get('verdict')}")
    with open(os.path.join(out, c, f"report_{c}.txt"), encoding="utf-8") as f:
        print("    " + f.readline().rstrip())
if bad:
    print("\nNOT REPRODUCED:\n  " + "\n  ".join(bad)); sys.exit(1)
print(f"\nall {len(cases)} models: verified ones reproduce their GAMS result, contributed ones run")
