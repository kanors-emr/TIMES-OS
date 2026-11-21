# SPDX-License-Identifier: GPL-3.0-or-later
"""A serial and a parallel build of a model give the same matrix, entry by entry; and so does a build started as a run
starts Julia (run_case.jl --wait: Julia waits on its input for its settings and arguments), with a setting given there.

    python .github/scripts/check_parallel.py [model folder]

The model (default models/DemoS_012, on a copy) is read once by the preprocessor and built twice by Julia, with one
worker and with the default number, each writing its matrix (--matrix-out: rows, columns, bounds and every entry, in
the order of the model), and a third time the --wait way with one worker given on its input (TIMESEQ_PAR_WORKERS=1).
The three must be identical, byte by byte; and a fourth --wait build, given TIMESEQ_PAR_WORKERS=not-a-number, must
stop naming that value (the setting reached Julia's environment). Exit status 1 otherwise.
Every Julia started here uses the Julia depot that setup chose (.julia_depot, or setup --julia-depot), set as the
runner sets it for its own Julia (TIMES.py: saved_julia_depot, use_julia_depot); the depot is named on the first line.
"""
import glob, importlib.util, os, shutil, subprocess, sys, tempfile
os.environ["TIMES_SETTINGS_FILES"] = "0"      # the runs started here read no times-os.toml: a stray one cannot change a check

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "models", "DemoS_012")
JULIA_ENV = os.path.join(ROOT, ".julia_env")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(ROOT, ".venv", "bin", "python")


def use_setup_depot():
    """JULIA_DEPOT_PATH of this process (and so of every Julia it starts) as the runner sets it: the depot in
    settings.json, then Julia's own; a setup that kept no depot leaves Julia's default. -> the depot Julia reads first."""
    spec = importlib.util.spec_from_file_location("times_runner", os.path.join(ROOT, "TIMES.py"))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.use_julia_depot(runner.saved_julia_depot())
    return subprocess.run(["julia", "--startup-file=no", "-e", "print(DEPOT_PATH[1])"], capture_output=True, text=True,
                          check=True).stdout.strip()


def build(work, name, env, wait=False, fails=False):
    """env: given to Julia as its environment; wait: given on its input instead, as a run gives it (run_case.jl --wait).
    fails: the build is to fail; -> its output."""
    out = os.path.join(work, name)
    julia = ["julia", "--startup-file=no", f"--threads={os.cpu_count() or 2}", f"--project={JULIA_ENV}",
             os.path.join(ROOT, "times_eq", "tools", "run_case.jl")]
    args = [os.path.join(work, "model.db3"), os.path.join(work, name + ".json"), "--no-solve", "--matrix-out", out]
    if not wait:
        subprocess.check_call(julia + args, env=dict(os.environ, **env), stdout=subprocess.DEVNULL)
        return out
    p = subprocess.Popen(julia + ["--wait"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    given = "\t".join(f"{k}={v}" for k, v in env.items()) + "\n" + "\t".join(args) + "\n"
    text = p.communicate(given.encode("utf-8"))[0].decode("utf-8", "replace")
    if fails:
        return text if p.returncode else None
    if p.returncode:
        print(text[-3000:])
        raise subprocess.CalledProcessError(p.returncode, julia + ["--wait"])
    return out


def main():
    print(f"Julia's depot: {use_setup_depot()}", flush=True)
    with tempfile.TemporaryDirectory() as work:
        case = os.path.join(work, "case")
        shutil.copytree(MODEL, case)
        run = glob.glob(os.path.join(case, "*.run"))[0]
        subprocess.check_call([PY, "-m", "timespp", run, "-", os.path.join(work, "model.db3")], cwd=os.path.join(ROOT, "times_pp"),
                              stdout=subprocess.DEVNULL)
        a, b = build(work, "serial", {"TIMESEQ_PAR_WORKERS": "1"}), build(work, "parallel", {})
        c = build(work, "waiting", {"TIMESEQ_PAR_WORKERS": "1"}, wait=True)
        names = sorted(os.listdir(a))
        for other, what in ((b, "parallel"), (c, "--wait")):
            if not names or names != sorted(os.listdir(other)):
                print(f"the matrices have different files: {names} and {sorted(os.listdir(other))} ({what})")
                return 1
            for f in names:
                with open(os.path.join(a, f), "rb") as x, open(os.path.join(other, f), "rb") as y:
                    if x.read() != y.read():
                        print(f"{f}: the serial and the {what} build differ")
                        return 1
        # ... and a setting given on its input is in Julia's environment: a value it cannot read stops the build, naming it
        text = build(work, "unread", {"TIMESEQ_PAR_WORKERS": "not-a-number"}, wait=True, fails=True)
        if text is None or "not-a-number" not in text:
            print("--wait: a setting given on Julia's input did not reach its environment (TIMESEQ_PAR_WORKERS=not-a-number "
                  "was not read)" + (f":\n{text[-2000:]}" if text else ""))
            return 1
        print(f"serial, parallel and --wait builds: the same matrix, all {len(names)} files of it identical; a setting "
              "given on the input of a waiting Julia reaches its environment")
        return 0


if __name__ == "__main__":
    sys.exit(main())
