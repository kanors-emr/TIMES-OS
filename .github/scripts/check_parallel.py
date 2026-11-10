# SPDX-License-Identifier: GPL-3.0-or-later
"""A serial and a parallel build of a model give the same matrix, entry by entry.

    python .github/scripts/check_parallel.py [model folder]

The model (default models/DemoS_012, on a copy) is read once by the preprocessor and built twice by Julia, with one
worker and with the default number, each writing its matrix (--matrix-out: rows, columns, bounds and every entry, in
the order of the model). The two must be identical, byte by byte. Exit status 1 otherwise.
"""
import glob, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "models", "DemoS_012")
JULIA_ENV = os.path.join(ROOT, ".julia_env")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(ROOT, ".venv", "bin", "python")


def build(work, name, env):
    out = os.path.join(work, name)
    subprocess.check_call(["julia", "--startup-file=no", f"--threads={os.cpu_count() or 2}", f"--project={JULIA_ENV}",
                           os.path.join(ROOT, "times_eq", "tools", "run_case.jl"), os.path.join(work, "model.db3"),
                           os.path.join(work, name + ".json"), "--no-solve", "--matrix-out", out],
                          env=dict(os.environ, **env), stdout=subprocess.DEVNULL)
    return out


def main():
    with tempfile.TemporaryDirectory() as work:
        case = os.path.join(work, "case")
        shutil.copytree(MODEL, case)
        run = glob.glob(os.path.join(case, "*.run"))[0]
        subprocess.check_call([PY, "-m", "timespp", run, "-", os.path.join(work, "model.db3")], cwd=os.path.join(ROOT, "times_pp"),
                              stdout=subprocess.DEVNULL)
        a, b = build(work, "serial", {"TIMESEQ_PAR_WORKERS": "1"}), build(work, "parallel", {})
        names, other = sorted(os.listdir(a)), sorted(os.listdir(b))
        if not names or names != other:
            print(f"the matrices have different files: {names} and {other}")
            return 1
        for f in names:
            with open(os.path.join(a, f), "rb") as x, open(os.path.join(b, f), "rb") as y:
                if x.read() != y.read():
                    print(f"{f}: the serial and the parallel build differ")
                    return 1
        print(f"serial and parallel builds: the same matrix, all {len(names)} files of it identical")
        return 0


if __name__ == "__main__":
    sys.exit(main())
