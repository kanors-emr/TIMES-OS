#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""TIMES: run a TIMES model through the open chain: DD files -> Python preprocessor -> Julia/JuMP -> HiGHS -> Veda
result files; and, where TIMES in GAMS is at hand, compare the model with the one it builds.

    python TIMES.py setup [--julia <julia executable>] [--gams <gams executable>] [--times <TIMES source folder>] [--no-times-source] [--gdx] [--dev] [--no-segheap] [--no-julia-install] [--install-julia winget|store|portable] [--gurobi <version>]
    python TIMES.py check
    python TIMES.py run <run folder> [<run folder> ...] [--cases <list file>] [options]
    python TIMES.py verify <result folder> [...] [--keep] [--quiet]

setup   creates .venv and installs the Python packages there, installs the Julia packages, finds Julia, writes
        settings.json, and runs the example model.  Run it once after cloning.  check and run use .venv when it is there.
        On Windows it also makes .venv/segheap: a copy of the interpreter on the Segment Heap, in which the preprocessor
        runs about twice as fast as on Windows's default heap (no administrator rights needed; run setup again after
        upgrading Python).  --no-segheap: no copy (the preprocessor runs on the default heap); for one run,
        TIMES_SEGHEAP=0 does the same.
        When no Julia is found, setup installs it, trying in turn: winget's Juliaup package, the Microsoft Store's Julia
        (both Windows, through winget), and a portable copy of the latest stable release from julialang.org in .julia_bin
        (checked against its published SHA-256; no administrator rights).  --no-julia-install: do not.
        --install-julia <way>: install Julia that one way even if one is found (winget, store or portable).
        When Gurobi is installed (GUROBI_HOME, gurobi_cl on the PATH, or the default folder gurobi<version>), setup
        also installs the Python packages of --gurobi: gurobipy of that version (a Gurobi licence is for one version)
        and scipy.  --gurobi <version>: that version of gurobipy, for a licence without a local installation.
        For the comparison with TIMES in GAMS (optional): --gams <gams executable> and --times <TIMES source folder> are
        kept in settings.json (found by themselves when GAMS is on the PATH or in C:\\GAMS, and when the source is a
        folder beside this one or Veda's GAMS_SrcTIMES folder).  The TIMES source is not part of this repository: it is
        IEA-ETSAP's (https://github.com/etsap-TIMES/TIMES_model).  When GAMS is found and no source of the version
        this implementation follows is, setup fetches that version from there into TIMES_model-v<version> in this
        folder (with git, or as the tag's zip file when git is not installed); --no-times-source: do not.
        The GDX packages these need (requirements-gams.txt: gamsapi[transfer] and gamspy_base, the latter under the
        GAMS licence) are installed only when GAMS is found, or with --gdx (also for --jacobian without GAMS); the
        open chain needs only open-source packages.
        The Julia package is compiled ahead on a whole case (models/DemoS_012), so that a run does not wait for the
        compiler; after a change in times_eq/src the next run compiles it again first (about 5 minutes).
        The equations of stochastic TIMES (STAGES, SPINES) compiled ahead are a package of their own
        (times_eq/addons/TimesEqStochastic), compiled with the rest.  Where it is missing or older than times_eq/src,
        the first run of a model with STAGES or SPINES installs and compiles it (a few minutes, once), and says so.
        --dev  for work on times_eq/src: compile ahead only the equation functions (about 2 minutes after a change
               instead of 5), and every run compiles the rest (about 1.5 minutes more per run).  setup without --dev
               goes back to the whole case.
check   says what is installed and what is missing, and the LP solvers the licence of your GAMS allows (for --lp;
        found once, in a few seconds, and kept in settings.json for that GAMS).
run     a list of cases (run folders: the run file and the DD files of one model, as Veda writes them), one after the other:
          0. reads the model with the Python preprocessor and lists every input not supported yet,
          1. builds the model in Julia and solves it with HiGHS,
          2. writes the solution as solution.db3 (levels, marginals and bounds of every column and row, by GAMS name)
             and the Veda result files of it, <run>_julia.vd, .vde and .vds (times_rpt; --no-report skips it),
          3. with --gams run or --check: runs TIMES in GAMS on a copy of the same run file, with the same REDUCE,
          4. writes <output>/<case>/report_<case>.txt (verdict in the first line) and report_<case>.json, and
             <output>/summary.txt for more than one case.
        A published reference (expected.json in the run folder, as in models/) is compared with: the objective, the
        size of the model, and the GAMS solution or matrix when they are published beside it.
        A myopic run (TIMESTEP in the run file) is solved step by step, as TIMES does.
        The cases: run folders, run files, folders that hold run folders, wildcards (expanded here, also on cmd), and
        --cases <file> (one per line, # comments, paths relative to the file's folder), mixed in any order; a case
        named twice runs once.  A run file (.run may be left out when no folder has that name) runs that file of its
        folder, as the case named after it; a run folder with several run files runs one of them.  summary.txt says how the list was formed.  The run folders are not changed.

The comparison with TIMES in GAMS (needs GAMS, its licence for the size of the model, and the TIMES source):

    python TIMES.py run <run folder> --no-solve --check [--times <TIMES source folder>]

        is the check every release of this implementation passes: GAMS runs TIMES once on a copy of the run file, with
        the solver CONVERT, which writes the model's matrix instead of solving it; this implementation builds the same
        run (and solves it too without --no-solve); then the two matrices are compared entry by entry, rows and
        columns by their names (every coefficient, right-hand side and bound).  The verdict, in the first line of
        the report: SAME, or DIFFERENT with the equations and variables that differ.  With several cases, the matrices are compared after every case has
        run (Ctrl+C stops the comparisons and keeps the runs).  --gams run instead solves the model in GAMS as well and
        compares the objectives; a GAMS listing already in the run folder (as Veda leaves it) is compared with in the
        same way, without running GAMS.  Without GAMS or the TIMES source, --check stops before anything is run.
verify  the matrix comparison of --check on finished cases: a result folder of one case (<output>/<case>), or a folder
        of them (its summary.txt is updated).  The case needs its tables and work/ (kept by a run with --check until it
        has passed).  --keep: keep the tables after a passed check.

options of run:
    --out <folder>          where the results go (default: runs/ in this repository)
    --check [inline]        compare the model with TIMES in GAMS entry by entry (see above).  inline: GAMS first, then
                            this implementation compares while it builds (one case at a time; for finding a difference)
    --gams reference|run|reuse|skip
                            reference: compare with the published GAMS result in the folder (expected.json, and
                            gams_solution.db3 / gams_matrix.db3 when present; the default when expected.json is there);
                            run: run TIMES in GAMS now and compare; reuse: compare with a GAMS listing already in the
                            run folder (the default when there is one); skip: no comparison
    --times <folder>        the TIMES source folder for this run (default: the one setup found)
    --solver auto|simplex|ipm|hipo|ipx   HiGHS method (auto: simplex, and the interior point code ipx above 150,000 rows;
                            ipm or hipo: the newer, parallel interior point code HiPO, with ipx as the fallback)
    --threads <n>           threads HiGHS may use (default: HiGHS's own choice)
    --highs-option <name=value>   any HiGHS option, repeated as needed; applied last, e.g. run_crossover=on
    --lp highs|cplex|<an LP solver of your GAMS>
                            the LP solver (default highs, which needs nothing else); any other is a solver of your own GAMS
                            installation (as GAMS's LP=): the model is built as always and handed to GAMS as a GDX, GAMS
                            solves it, the solution comes back (solution.db3, the Veda files, the report as after HiGHS).
                            The option file is <solver>.opt in the run folder (Veda writes cplex.opt there), as it is;
                            --threads and --time-limit go to GAMS as threads= and reslim=; --solver, --highs-option and
                            --max-solve-rows do not apply.  GAMS's log: gamslp.log in the result folder
    --lp-names              with --lp and --keep: GAMS gets the model by TIMES's names (equations and variables by family,
                            over their labels) instead of rows and columns by number, so that its listing (gamslp/lp_names.lst
                            in the result folder) shows the rows and columns as TIMES's listing does; the program
                            (lp_names.gms) and its data (named.gdx) stay beside it, to run again with limrow= and limcol=
                            for more of the listing. Ignored without --keep (the GAMS files are removed after the solve)
    --cplex                 --lp cplex
    --gurobi                Gurobi through its Python interface (gurobipy), without GAMS: needs a Gurobi licence and the Python
                            packages gurobipy (the version of the licence) and scipy, which setup installs when it
                            finds Gurobi (or setup --gurobi <version>);
                            options: gurobi.opt in the run folder, --solver-option name=value, as Gurobi parameters
                            (--lp gurobi is Gurobi through your GAMS)
    --solver-option <name=value>  a line added to the solver's option file (after the run folder's), repeated as needed
    --gams-exe <file>       the GAMS executable for --lp (default: TIMES_GAMS, settings.json "gams", the PATH, C:\\GAMS)
    --time-limit <seconds>  limit of each solve (default: the run file's OPTION RESLIM, else GAMS's default; 0: no limit)
                            and of the GAMS run (default: none)
    --tolerance <number>    relative difference of the objectives that still counts as the same (default 1e-6)
    --points <folder>       where the results of earlier runs are (LPOINT, FIXBOH, TIMESED), when they are not where TIMES
                            looks: the result folder or the run folder of the earlier run; repeated as needed (TIMES_POINTS:
                            folders separated by ;). The result folders of this runner (--out, runs\\) are looked in as well
    --bundle                also write <case>_bundle.zip: the report, the logs, the run file, the DD files and the solver
                            options (no other file of the run folder); look through it before attaching it anywhere public
    --keep                  keep the tables and the converted GAMS solution (large) after the run
    --jacobian [<file>]     also write the model's matrix as a GDX in the layout of the jacobian GDX that GAMS's CONVERT
                            solver writes, to compare with the one GAMS writes for the same run (by the names of the rows
                            and columns: times_pp/tools/compare_jacobian.py). Without <file>: <case>.gdx in the case's
                            result folder (the case: the name of the run folder). A name without a folder goes into
                            the case's result folder (runs/<case>/<file>), a path where it says, an existing folder
                            gets <case>_jacobian.gdx; .gdx is added when missing
    --db3                   also make model.db3 from the tables (written as the folder model_parquet, Parquet files:
                            TIMES_TABLES=db3 writes model.db3 instead); with --keep it stays.
                            TIMES_DROP=1: the preprocessor also drops each table once written and no longer read
                            (less memory after its peak; off by default)
    --no-solve              solve nothing: the model is built (and, when GAMS and the TIMES source are found, GAMS runs
                            to its solver and stops there: the sizes are compared; with --check the matrices too)
    --solve                 solve with HiGHS whatever the size (by default a model above --max-solve-rows is only built)
    --max-solve-rows <n>    the size above which HiGHS is not tried (default 2,000,000 rows)
    --cases <file>          the cases listed in a file, one run folder per line (see above)
    --no-report             do not write the Veda result files of the solution (by default <run>_julia.vd, .vde and
                            .vds go to the result folder, for import into Veda; report options of the model that are
                            not covered are named in the report)
    --low-memory            the preprocessor keeps its tables in a work file in the result folder instead of in memory
                            (DuckDB held to 3GB, the rest on disk; the file is deleted at the end): slower, for large
                            models on machines with little memory (about half the memory at the peak)
    --quiet                 do not show the output of the preprocessor, GAMS, Julia and HiGHS while they run
                            (it is in the log files of the result folder either way)
    --profile [cpu|allocs]  write julia_profile.txt: where the Julia table load and the equation build spend time
                            (cpu, the default) or which lines allocate (allocs: 1 allocation in 100 is recorded).
                            The HiGHS solve is not in the profile. The run is a little slower.

    The model is reduced as the run file's REDUCE says, as TIMES reduces it: NO none; YES the whole reduction (flows
    replaced by the activity, processes off where a zero bound turns them off); any other value, or no $SET REDUCE line,
    the capacity variables and the emissions only. TIMES_REDUCE=NO builds the unreduced model whatever the run file
    says (TIMES_REDUCE=YES the reduced one); GAMS runs the same copy.

exit status of run and verify: 0 every model solved (or built, with --no-solve) and, where it was compared, the same as
TIMES in GAMS; 1 a difference (DIFFERENT, DIFFERENT OBJECTIVE), an error or a model not solved; 3 a model uses
unsupported input (and none differs); 5 a model's data cannot be met (INFEASIBLE; after 1 and 3); 4 solved, but result
files were not written (the report's NOT WRITTEN line); 130 the matrix comparisons were stopped (Ctrl+C); 2 nothing was
run (a result folder would be the run folder, overlap it, or replace a folder this runner did not make).
"""
import sys, os, re, json, glob, time, shutil, hashlib, platform, subprocess, zipfile, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(ROOT, "settings.json")
JULIA_ENV = os.path.join(ROOT, ".julia_env")
VENV = os.path.join(ROOT, ".venv")
JULIA_BIN = os.path.join(ROOT, ".julia_bin")    # Julia as setup installs it, the last way it tries (a portable copy, no administrator rights)
JULIA_VERSIONS = "https://julialang-s3.julialang.org/bin/versions.json"
PORT_VERSION = "4.9.8"                         # the TIMES version this implementation follows
TIMES_REPO = "https://github.com/etsap-TIMES/TIMES_model"
OUTPUT_EXT = {".gdx", ".parquet", ".lst", ".vd", ".vde", ".vds", ".vdt", ".log", ".exe", ".g00", ".put", ".sta", ".zip", ".db3", ".duckdb",
              ".lxi", ".ref", ".csv", ".xlsx", ".accdb", ".mdb", ".bak", ".tmp"}
WIN = os.name == "nt"


def setting(name, default=None):
    """A setting from the environment: TIMES_<name>."""
    if os.environ.get("TIMES_" + name):
        return os.environ["TIMES_" + name]
    return default


# ----------------------------------------------------------------------------------------------------------------
# small helpers
def venv_python():
    """The Python of .venv."""
    return os.path.join(VENV, "Scripts", "python.exe") if WIN else os.path.join(VENV, "bin", "python")


SEGHEAP = os.path.join(VENV, "segheap")        # Windows: the interpreter copy on the Segment Heap, made by setup


def winheap():
    """times_pp/timespp/winheap.py, loaded by its path (standard library only; the timespp package needs DuckDB)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("tj_winheap", os.path.join(ROOT, "times_pp", "timespp", "winheap.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def base_python():
    """The interpreter .venv was made from (home in its pyvenv.cfg), else sys._base_executable."""
    cfg = os.path.join(VENV, "pyvenv.cfg")
    m = re.search(r"(?m)^\s*home\s*=\s*(.+?)\s*$", read(cfg)) if os.path.isfile(cfg) else None
    if m and os.path.isfile(os.path.join(m.group(1), "python.exe")):
        return os.path.join(m.group(1), "python.exe")
    b = getattr(sys, "_base_executable", None)
    return b if b and os.path.isfile(b) else None


def make_segheap():
    """Windows: the preprocessor's interpreter. DuckDB allocates from the process heap, and Windows's default heap (the
    NT heap) makes the preprocessor about twice as slow as on Linux; the Segment Heap gives Linux speed. The heap type
    is read from the executable's manifest, so this copies the interpreter .venv was made from (python.exe and its
    DLLs, about 7 MB) into .venv/segheap, asks for the Segment Heap in the copy's manifest, and has the copy run on
    .venv's packages. No administrator rights, no registry change. The copy is not signed any more: where
    application control blocks unsigned programs, the check fails and the runner keeps using .venv's Python.
    -> the entry of settings.json (status ok, or failed and why)"""
    rec = {"made": datetime.datetime.now().isoformat(timespec="seconds"), "version": platform.python_version()}
    # the layout of a venv: Python takes the folder above the program's as sys.prefix when pyvenv.cfg is there, and
    # reads the .pth files of <prefix>/Lib/site-packages
    exe = os.path.join(SEGHEAP, "Scripts", "python.exe")
    # Some Pythons run on the Segment Heap already: a packaged one (the Microsoft Store's Python, whose files Windows
    # also does not let a program copy: WinError 1920), or any Python where Windows gives every program the Segment
    # Heap. Then .venv's own Python is used, and no copy is made.
    try:
        code, out, _ = call([sys.executable, os.path.join(ROOT, "times_pp", "timespp", "winheap.py"), "selftest"], timeout=600)
        got = json.loads(out.strip().splitlines()[-1])
        if got.get("heap") == "segment" and got.get("worker_heap") == "segment" and "duckdb" in got:
            shutil.rmtree(SEGHEAP, ignore_errors=True)
            rec.update(status="ok", python=for_settings(sys.executable), how="this Python runs on the Segment Heap already: no copy needed")
            return rec
    except Exception:
        pass                                  # (the check is only a short cut: the copy below says what goes wrong)
    try:
        build = sys.getwindowsversion().build
        rec["windows_build"] = build
        if build < 19041:   # the heapType element of the manifest is read from Windows 10 2004 / Windows Server 2022 on
            raise RuntimeError(f"this Windows (build {build}) does not let a program ask for the Segment Heap; that needs Windows 10 version 2004, "
                               "Windows 11 or Windows Server 2022 (build 19041 or later)")
        base = base_python()
        if not base:
            raise RuntimeError("the interpreter .venv was made from was not found")
        home = os.path.dirname(base)
        rec["base"] = base
        shutil.rmtree(SEGHEAP, ignore_errors=True)
        os.makedirs(os.path.dirname(exe))
        for f in ["python.exe"] + [f for f in os.listdir(home) if re.fullmatch(r"(?i)python3\d*\.dll|vcruntime140(_\d)?\.dll", f)]:
            shutil.copy2(os.path.join(home, f), os.path.join(os.path.dirname(exe), f))
        winheap().add_segment_heap(exe)
        write(os.path.join(SEGHEAP, "pyvenv.cfg"), f"home = {home}\ninclude-system-site-packages = false\nversion = {platform.python_version()}\nexecutable = {base}\n")
        sp = os.path.join(SEGHEAP, "Lib", "site-packages")
        os.makedirs(sp)
        # .venv's packages (its .pth files too), found from the copy's own place; and sys._base_executable: without it
        # multiprocessing starts the DD reader's workers in the base interpreter, on the NT heap (bpo-35797)
        write(os.path.join(sp, "times_segheap.pth"), "import os, site, sys; site.addsitedir(os.path.join(os.path.dirname(sys.prefix), 'Lib', 'site-packages')); "
                                                    "sys._base_executable = sys.executable\n")
        code, out, _ = call([exe, os.path.join(ROOT, "times_pp", "timespp", "winheap.py"), "selftest"], timeout=600)
        try:
            got = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise RuntimeError(f"the copy did not run (exit {code}): " + (out.strip()[-500:] or "no output"))
        same = lambda a, b: bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
        why = [w for w, bad in (("the copy is not on the Segment Heap", got.get("heap") != "segment"),
                                ("DuckDB does not import in the copy: " + got.get("duckdb_error", ""), "duckdb" not in got),
                                ("its worker processes are not on the Segment Heap: " + str(got.get("worker_error") or got.get("worker_heap")), got.get("worker_heap") != "segment"),
                                (f"it runs as {got.get('image')}", not same(got.get("image"), exe)),
                                (f"its worker processes run {got.get('worker_image')}", not same(got.get("worker_image"), exe))) if bad]
        if why:
            raise RuntimeError("; ".join(why))
        rec.update(status="ok", python=for_settings(exe))
    except Exception as x:
        rec.update(status="failed", why=f"{x}" if isinstance(x, RuntimeError) else f"{type(x).__name__}: {x}")
        shutil.rmtree(SEGHEAP, ignore_errors=True)
    return rec


def pp_python():
    """The interpreter for the preprocessor and the report writer: on Windows the Segment Heap copy, when setup made it
    and it passed its check and the base Python is still the same version; else this one. TIMES_SEGHEAP=0 (or
    setup --no-segheap) turns the copy off.  -> (path, what it is)"""
    if not WIN:
        return sys.executable, "this Python"
    if setting("SEGHEAP", "1") == "0":
        return sys.executable, "NT heap: the Segment Heap copy is switched off (TIMES_SEGHEAP=0)"
    h = settings().get("segment_heap") or {}
    exe = locate(h.get("python"))
    if not h:
        return sys.executable, "NT heap: no Segment Heap copy (python TIMES.py setup makes it)"
    if h.get("status") == "off":
        return sys.executable, f"NT heap: the Segment Heap copy is switched off ({h.get('why')}; python TIMES.py setup makes it)"
    if h.get("status") != "ok":
        return sys.executable, f"NT heap: the Segment Heap copy could not be made at setup ({h.get('why')})"
    if not exe or not os.path.isfile(exe):
        return sys.executable, "NT heap: the Segment Heap copy is missing (python TIMES.py setup makes it again)"
    if h.get("version") != platform.python_version():
        return sys.executable, (f"NT heap: Python changed from {h.get('version')} to {platform.python_version()} since the Segment Heap copy was made "
                                "(python TIMES.py setup makes it again)")
    return exe, "Segment Heap"


def in_project_venv():
    """True when this process is the .venv of this repository."""
    return os.path.normcase(os.path.realpath(sys.prefix)) == os.path.normcase(os.path.realpath(VENV))


def reexec_in_venv():
    """Continue this command in .venv. None when this process should carry on."""
    vp = venv_python()
    if in_project_venv() or not os.path.isfile(vp) or setting("REEXEC") == "1":
        return None
    env = os.environ.copy()
    env["TIMES_REEXEC"] = "1"                          # do not re-enter if .venv does not change the interpreter
    return subprocess.call([vp] + sys.argv, env=env)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_json(path):
    """A JSON file another process replaces while this one runs (preprocess.json). On Windows the file cannot be
    opened for a moment while it is being replaced, or while a virus scanner or the search indexer holds it:
    try again for up to 30 s."""
    for i in range(300):
        try:
            return json.loads(read(path))
        except (PermissionError, json.JSONDecodeError):
            if i == 299:
                raise
            time.sleep(0.1)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


VERBOSE = True                                  # run: show the output of each program while it runs (--quiet turns it off)


def call(cmd, cwd=None, log=None, timeout=None, env=None, echo=None, follow=None, show=None, stop_on=None, started=None):
    """Run a program; output to the file `log` (or returned).  -> (exit status or None on timeout, output, seconds)

    echo: a prefix; with it (and VERBOSE) every line of output is also shown, as it comes.
    follow: a file the program writes its own log to; its new lines are shown as well.
    show: for the lines of `follow`: line -> the line to show, or None for none (the file itself is not changed).
    stop_on: (pattern, list): the program and the processes it started are ended at the first line of `follow` that
    matches the pattern, and the line is added to the list (GAMS stopped at its solver).
    started: (process, text) for a program already started (`started_early`): `text` goes to its input, which is then
    closed, and the program is followed from there as if started now (`cmd` and `env` are then not used)."""
    t0 = time.time()
    # A limit beyond what the system's waits accept (on Windows about 49.7 days, 2**32 ms: threading.Timer and
    # subprocess fail with OverflowError) is no limit: a run file's RESLIM of 1E7 s or more means none was meant.
    if timeout is not None and timeout >= 4.0e6:
        timeout = None
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    e.update(env or {})
    try:
        if log and (echo is not None and VERBOSE or stop_on and follow or timeout or started):
            import threading
            if started:
                p = started[0]
                try:
                    p.stdin.write(started[1].encode("utf-8"))
                    p.stdin.close()
                except OSError:                          # it ended before (its output says why)
                    pass
            else:
                p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=e,
                                     **({"start_new_session": True} if (stop_on or timeout) and not WIN else {}))
            expired = threading.Event()

            def out_of_time():
                expired.set()
                end_tree(p)                              # with what it started (GAMS, a solver)

            timer = threading.Timer(timeout, out_of_time) if timeout else None
            timer and timer.start()
            done = threading.Event()

            def tail():                                  # the program's own log file, line by line
                pos = 0
                while True:
                    last = done.is_set()
                    try:
                        with open(follow, "rb") as g:
                            g.seek(pos)
                            chunk = g.read()
                        cut = len(chunk) if last else chunk.rfind(b"\n") + 1
                        for line in chunk[:cut].decode("utf-8", "replace").splitlines():
                            if stop_on and not stop_on[1] and stop_on[0].search(line):
                                stop_on[1].append(line.rstrip())
                                end_tree(p)
                            line = show(line.rstrip()) if show else line.rstrip()
                            if line is not None and VERBOSE and echo is not None:
                                print(echo + line, flush=True)
                        pos += cut
                    except OSError:
                        pass
                    if last:
                        return
                    done.wait(0.25 if stop_on else 1.0)

            th = threading.Thread(target=tail, daemon=True) if follow else None
            th and th.start()
            with open(log, "w", encoding="utf-8", errors="replace") as f:
                for raw in p.stdout:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    f.write(line + "\n")
                    if VERBOSE and echo is not None:
                        print(echo + line, flush=True)
            code = p.wait()
            done.set()
            th and th.join(10)
            if timer:
                timer.cancel()
                if expired.is_set() and code != 0:
                    return None, read(log), time.time() - t0
            return code, read(log), time.time() - t0
        if log:
            with open(log, "w", encoding="utf-8", errors="replace") as f:
                p = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, env=e)
            out = read(log)
        else:
            p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=e)
            out = p.stdout.decode("utf-8", "replace")
        return p.returncode, out, time.time() - t0
    except subprocess.TimeoutExpired:
        return None, (read(log) if log and os.path.exists(log) else ""), time.time() - t0
    except OSError as x:
        return -1, f"could not start {cmd[0]}: {x}", time.time() - t0


def end_tree(p):
    """End a process and the processes it started (GAMS runs its solver in another process)."""
    try:
        if WIN:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import signal
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        p.kill()


def plain_path(path):
    """A path without blanks for the GAMS command line (Windows: the short 8.3 form), or the path as it is."""
    if WIN and " " in path:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024):
                return buf.value
        except Exception:
            pass
    return path


def settings():
    s = {}
    if os.path.exists(SETTINGS):
        try:
            s = json.loads(read(SETTINGS))
        except ValueError:
            pass
    return s


def locate(path):
    """Absolute form of a path. A relative path is taken from this repository."""
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    return os.path.abspath(path)


def for_settings(path):
    """Path as stored in settings.json. Inside this repository it is relative to the repository."""
    path = os.path.abspath(path)
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:                                          # another drive: a relative path cannot name it
        return path
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return path
    return rel.replace("\\", "/")


def pin_timeseq_path():
    """The TimesEq source in .julia_env is ../times_eq (TimesPPKernels ../times_pp/jlkernels, the add-on of stochastic
    TIMES ../times_eq/addons/TimesEqStochastic), so the checkout can be moved."""
    for name in ("Project.toml", "Manifest.toml"):
        path = os.path.join(JULIA_ENV, name)
        if not os.path.isfile(path):
            continue
        text = read(path)
        new = re.sub(r'(path\s*=\s*")[^"]*times_eq(")', r'\1../times_eq\2', text)
        new = re.sub(rf'(path\s*=\s*")[^"]*times_eq[\\/]+addons[\\/]+{STOCH_ADDON}(")', rf'\1../times_eq/addons/{STOCH_ADDON}\2', new)
        new = re.sub(r'(path\s*=\s*")[^"]*times_pp[\\/]+jlkernels(")', r'\1../times_pp/jlkernels\2', new)
        if new != text:
            write(path, new)


def num(x, digits=6):
    return "-" if x is None else (f"{x:,}" if isinstance(x, int) else f"{x:.{digits}f}")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


# ----------------------------------------------------------------------------------------------------------------
# finding the programs
def find_julia(given=None):
    cands = [given, locate(settings().get("julia")), shutil.which("julia")]
    home = os.path.expanduser("~")
    cands += [os.path.join(home, ".juliaup", "bin", "julia.exe" if WIN else "julia")]
    if WIN:   # the Microsoft Store's Julia (juliaup) puts its julia.exe here
        cands.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "julia.exe"))
    vkey = lambda f: tuple(int(x) for x in re.findall(r"\d+", os.path.basename(os.path.dirname(os.path.dirname(f))))[:3])
    cands += sorted(glob.glob(os.path.join(JULIA_BIN, "julia-*", "bin", "julia.exe" if WIN else "julia")), key=vkey, reverse=True)
    if WIN:
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
            cands += sorted(glob.glob(os.path.join(base, "Programs", "Julia*", "bin", "julia.exe")), reverse=True)
            cands += sorted(glob.glob(os.path.join(base, "Julia*", "bin", "julia.exe")), reverse=True)
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def gams_for_lp(given=None):
    r"""The GAMS executable for --lp (solving with a solver of the user's GAMS): --gams-exe, TIMES_GAMS, settings.json
    "gams", the PATH, C:\GAMS\<version>\gams.exe (the newest)."""
    cands = [given, os.environ.get("TIMES_GAMS"), locate(settings().get("gams")), shutil.which("gams")]
    if WIN:
        cands += sorted(glob.glob(r"C:\GAMS\*\gams.exe"), key=lambda p: [int(x) if x.isdigit() else 0 for x in re.split(r"[\\.]", p)], reverse=True)
    else:
        cands += sorted(glob.glob("/opt/gams/*/gams"), reverse=True)
    for c in cands:
        if c and os.path.isdir(c):
            c = os.path.join(c, "gams.exe" if WIN else "gams")
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None



def gams_lp_solvers(gams, fresh=False):
    """The version of the GAMS at `gams` and the LP solvers its licence allows: one GAMS run solves a small LP of 6,000
    rows and columns (larger than GAMS's demo and community limits, so a solver that is not licensed refuses it)
    with each solver of the installation that takes an LP (gmscmp*.txt: LP among its model types, not hidden, not a
    tool). A few seconds; the answer is kept in settings.json ("gams_lp") for this GAMS (its path, version and the
    date of its licence file) and found again there. -> {"gams", "version", "licensed": [...], "not_licensed": [...],
    "seconds"} or {..., "error": ...}"""
    sysdir = os.path.dirname(gams)
    stamp = os.path.join(sysdir, "gamsstmp.txt")
    m = re.search(r"\b(\d+\.\d+\.\d+)\b", read(stamp)) if os.path.isfile(stamp) else None
    lic = os.path.join(sysdir, "gamslice.txt")
    key = {"gams": gams, "version": m.group(1) if m else None,
           "licence_time": int(os.path.getmtime(lic)) if os.path.isfile(lic) else None}
    old = settings().get("gams_lp") or {}
    if not fresh and "licensed" in old and all(old.get(k) == v for k, v in key.items()):
        return old
    cmp_file = os.path.join(sysdir, "gmscmpNT.txt" if WIN else "gmscmpun.txt")
    if not os.path.isfile(cmp_file):
        return {**key, "error": f"no {os.path.basename(cmp_file)} in {sysdir}"}
    names = []
    for line in read(cmp_file).splitlines():              # solverId fileType dictType licCodes defaultOk hidden lines modelTypes...
        w = line.split()
        if len(w) > 7 and re.fullmatch(r"[A-Z][A-Z0-9]*", w[0]) and w[4] == "1" and w[5] == "0" and "LP" in w[7:]:
            names.append(w[0])
    if not names:
        return {**key, "error": f"no LP solver in {cmp_file}"}
    import tempfile
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="times_lp_solvers_") as d:
        lines = ["Set i / 1*6000 /;", "Variable x(i), z;", "x.lo(i) = 1;", "Equation e(i), o;", "e(i).. x(i) =g= 2;",
                 "o.. z =e= sum(i, x(i));", "Model m / all /;", "m.solvelink = 5; m.solprint = 0; m.limrow = 0; m.limcol = 0;",
                 "file f / solvers.txt /; put f;"]
        for n in names:
            lines += [f"$ifThen solver {n}", f"option lp = {n}; solve m using lp minimizing z;",
                      f'put "{n} " m.solvestat:0:0 " " m.modelstat:0:0 /;', "$endIf"]
        write(os.path.join(d, "solvers.gms"), "\n".join(lines) + "\n")
        try:
            code, _, _ = call([gams, "solvers.gms", "lo=0"], cwd=d, timeout=120)
        except Exception as x:
            return {**key, "error": f"GAMS did not run: {x}"}
        out = os.path.join(d, "solvers.txt")
        if not os.path.isfile(out):
            return {**key, "error": f"GAMS stopped (exit code {code}) before it tried the solvers"}
        res = dict(l.split(None, 1) for l in read(out).splitlines() if l.strip())
    ok = [n for n in names if res.get(n, "").split()[:2] == ["1", "1"]]
    ans = {**key, "licensed": ok, "not_licensed": [n for n in names if n not in ok], "seconds": round(time.time() - t0, 1)}
    s = settings()
    s["gams_lp"] = ans
    write(SETTINGS, json.dumps(s, indent=1))
    return ans

def julia_runs(exe, timeout=1800):
    """The version of the Julia at `exe` if it runs and is 1.11 or newer, else None. A juliaup julia.exe downloads its
    release on the first start, which can take minutes."""
    try:
        code, out, _ = call([exe, "--version"], timeout=timeout)
    except Exception:
        return None
    m = re.search(r"julia version (\d+)\.(\d+)\.(\d+)", out or "")
    return m.group(0) if code == 0 and m and (int(m.group(1)), int(m.group(2))) >= (1, 11) else None


def install_julia(only=None):
    """No Julia was found: install it, trying in turn (Windows) winget's Juliaup package, the Microsoft Store's Julia
    (also through winget), and a portable copy of the latest stable release from julialang.org in .julia_bin (checked
    against its published SHA-256; no installer, no administrator rights); elsewhere the portable copy only.
    only: one of "winget", "store", "portable" (setup --install-julia <way>, to try one way). -> julia executable or None"""
    home = os.path.expanduser("~")
    found = lambda: next((c for c in ([os.path.join(home, ".juliaup", "bin", "julia.exe"),
                                       os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "julia.exe")]
                                      + ([shutil.which("julia")] if shutil.which("julia") else [])) if os.path.isfile(c)), None)

    def by_winget(what, cmd):
        if not shutil.which("winget"):
            return None, "winget is not on this machine"
        print(f"   {what}: {' '.join(cmd)}", flush=True)
        code, out, _ = call(cmd + ["--accept-package-agreements", "--accept-source-agreements"], timeout=1800)
        exe = found()                     # (winget also exits non-zero when the package is there already)
        if not exe:
            return None, f"winget exit {code}: " + " ".join((out or "").strip().splitlines()[-2:])[:300]
        print(f"   {exe}: starting it once (juliaup downloads the release on the first start; can take minutes) ...", flush=True)
        v = julia_runs(exe)
        return (exe, v) if v else (None, f"{exe} does not run, or is older than 1.11")

    ways = []
    if WIN:
        ways += [("winget", "Juliaup (winget)", lambda: by_winget("Juliaup through winget", ["winget", "install", "--id", "Julialang.Juliaup", "-e"])),
                 ("store", "Julia from the Microsoft Store (winget)",
                  lambda: by_winget("the Microsoft Store's Julia through winget", ["winget", "install", "--name", "Julia", "--id", "9NJNWW8PVKMN", "-e", "-s", "msstore"]))]
    ways += [("portable", "a portable copy from julialang.org", install_julia_portable)]
    tried = []
    for key, what, f in ways:
        if only and key != only:
            continue
        print(f"   Julia: trying {what} ...", flush=True)
        try:
            exe, info = f()
        except Exception as x:
            exe, info = None, f"{type(x).__name__}: {x}"
        if exe:
            print(f"   done: {info} ({exe})", flush=True)
            return exe
        print(f"   not this way: {info}", flush=True)
        tried.append(f"{what}: {info}")
    print("   Julia could not be installed (" + "; ".join(tried) + ").\n   Install Julia 1.11 or newer yourself "
          "(https://julialang.org/downloads/), open a new terminal and run setup again, or: setup --julia <julia executable>")
    return None


def install_julia_portable():
    """The latest stable Julia (1.11 or newer) from julialang.org, unpacked into .julia_bin. -> (exe, version) or (None, why)"""
    import urllib.request, tarfile
    osname, ext = ("winnt", "zip") if WIN else ("linux", "tar.gz") if sys.platform.startswith("linux") else (None, None)
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine().lower())
    if not osname or not arch:
        return None, f"no portable copy for this platform ({sys.platform}, {platform.machine()})"
    with urllib.request.urlopen(JULIA_VERSIONS, timeout=60) as r:
        versions = json.loads(r.read())
    vkey = lambda v: tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    stable = sorted((v for v, d in versions.items() if d.get("stable") and vkey(v) >= (1, 11)), key=vkey)
    for v in reversed(stable):
        f = [f for f in versions[v]["files"] if f.get("os") == osname and f.get("arch") == arch and f.get("kind") == "archive" and f.get("extension") == ext]
        if f:
            f = f[0]
            break
    else:
        return None, f"no Julia archive for {osname} {arch} in {JULIA_VERSIONS}"
    os.makedirs(JULIA_BIN, exist_ok=True)
    part = os.path.join(JULIA_BIN, os.path.basename(f["url"]) + ".part")
    print(f"   downloading Julia {v} ({f['size'] / 1e6:.0f} MB) from {f['url']} ...", flush=True)
    h, got, t0, shown = hashlib.sha256(), 0, time.time(), 0
    with urllib.request.urlopen(f["url"], timeout=120) as r, open(part, "wb") as out:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            out.write(b); h.update(b); got += len(b)
            if got - shown >= 50e6:
                shown = got
                print(f"      {got / 1e6:.0f} MB ({time.time() - t0:.0f} s)", flush=True)
    if f.get("sha256") and h.hexdigest() != f["sha256"]:
        return None, f"the download does not match its published SHA-256 ({h.hexdigest()} against {f['sha256']})"
    print("   unpacking ...", flush=True)
    dest, tmp = os.path.join(JULIA_BIN, f"julia-{v}"), os.path.join(JULIA_BIN, f"_unpack-{v}")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if ext == "zip":
        with zipfile.ZipFile(part) as z:
            z.extractall(tmp)
    else:
        with tarfile.open(part) as z:
            z.extractall(tmp)
    tops = os.listdir(tmp)
    os.replace(os.path.join(tmp, tops[0]) if len(tops) == 1 else tmp, dest)
    shutil.rmtree(tmp, ignore_errors=True)
    os.remove(part)
    exe = os.path.join(dest, "bin", "julia.exe" if WIN else "julia")
    if not WIN:
        os.chmod(exe, 0o755)
    ver = julia_runs(exe, timeout=600)
    return (exe, ver) if ver else (None, f"the unpacked Julia does not run ({exe})")


def find_gams(given=None):
    cands = [given, locate(settings().get("gams")), shutil.which("gams")]
    if WIN:
        for pat in (r"C:\GAMS\*\gams.exe", r"C:\GAMS\*\*\gams.exe", r"C:\Program Files\GAMS*\gams.exe", r"C:\Program Files\GAMS\*\gams.exe"):
            cands += sorted(glob.glob(pat), reverse=True)
    else:
        cands += sorted(glob.glob("/opt/gams/*/gams"), reverse=True)
    for c in cands:
        if c and os.path.isdir(c):
            c = os.path.join(c, "gams.exe" if WIN else "gams")
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def times_version(folder):
    try:
        m = re.search(r"TIMES -- VERSION ([0-9.]+)", read(os.path.join(folder, "initsys.mod"))[:2000])
        return m.group(1) if m else None
    except OSError:
        return None


TIMES_GIVEN = None          # run --times <folder>: the TIMES source folder for this run


def find_times(given=None, any_saved=True):
    """The TIMES source folder (it must hold initsys.mod and maindrv.mod); PORT_VERSION preferred.  The folder given
    (run --times, setup --times), or else the one saved in settings.json, wins over the others; any_saved=False passes
    the saved one by unless it is PORT_VERSION."""
    given = given or TIMES_GIVEN
    saved = settings().get("times")
    if not any_saved and not (saved and times_version(locate(saved)) == PORT_VERSION):
        saved = None
    cands = [given, locate(saved), os.path.join(ROOT, "TIMES_model-v" + PORT_VERSION), os.path.join(ROOT, "TIMES_model")]
    for base in (os.path.dirname(ROOT), r"C:\Veda\Veda" if WIN else None, r"C:\VEDA\Veda" if WIN else None):
        if base and os.path.isdir(base):
            cands += sorted(glob.glob(os.path.join(base, "GAMS_SrcTIMES*")), key=lambda d: (times_version(d) != PORT_VERSION, d))
            cands += glob.glob(os.path.join(base, "TIMES_model")) + glob.glob(os.path.join(base, "TIMES_model-v*"))
    ok = [os.path.abspath(c) for c in cands if c and os.path.isfile(os.path.join(c, "initsys.mod")) and os.path.isfile(os.path.join(c, "maindrv.mod"))]
    if given or saved:
        return ok[0] if ok else None
    ok.sort(key=lambda d: times_version(d) != PORT_VERSION)
    return ok[0] if ok else None


def declarations_differ(src):
    """The TIMES declaration files (times_pp/timespp/times_src) whose copy in the TIMES source folder `src` is different
    or missing; [] when GAMS reads the same declarations as the open chain."""
    mine = os.path.join(ROOT, "times_pp", "timespp", "times_src")
    def norm(p):
        try:
            with open(p, "rb") as f:
                return f.read().replace(b"\r\n", b"\n")
        except OSError:
            return None
    return [f for f in sorted(os.listdir(mine)) if f != "README.md" and norm(os.path.join(mine, f)) != norm(os.path.join(src, f))]


def revision():
    """The revision of this code, when git is there to tell."""
    code, out, _ = call(["git", "-C", ROOT, "--no-optional-locks", "rev-parse", "--short", "HEAD"])
    if code != 0:
        return "unknown (not a git checkout, or git not installed)"
    code2, dirty, _ = call(["git", "-C", ROOT, "--no-optional-locks", "status", "--porcelain", "--untracked-files=no"])
    return out.strip() + (" + local changes" if code2 == 0 and dirty.strip() else "")


def python_packages():
    found, missing = {}, []
    for mod, pip in (("duckdb", "duckdb<2"), ("pandas", "pandas"), ("numpy", "numpy"), ("gams.transfer", "gamsapi[transfer]"), ("gamspy_base", "gamspy_base")):
        try:
            m = __import__(mod, fromlist=["x"])
            found[mod] = getattr(m, "__version__", "installed")
        except Exception as x:                                   # ImportError, or a broken installation
            missing.append((mod, pip, str(x).splitlines()[0][:120] if str(x) else type(x).__name__))
    return found, missing


def gurobi_folder_version(path):
    """The version in the name of a Gurobi folder (gurobi1303: 13.0.3), or None."""
    m = re.search(r"gurobi(\d+)(\d)(\d)", path.lower())
    return f"{int(m.group(1))}.{m.group(2)}.{m.group(3)}" if m else None


def find_gurobi():
    """(version, folder) of the Gurobi installed here (GUROBI_HOME, gurobi_cl on the PATH, else the newest default
    folder), or (None, None). The version is gurobi_cl's own, else the one in the folder's name."""
    homes = [os.environ.get("GUROBI_HOME")]
    cl = shutil.which("gurobi_cl")
    if cl:
        homes.append(os.path.dirname(os.path.dirname(cl)))
    found = []
    for pat in ([r"C:\gurobi*\win64"] if WIN else ["/opt/gurobi*/linux64", "/opt/gurobi*/armlinux64", "/Library/gurobi*/macos_universal2"]):
        found += glob.glob(pat)
    homes += sorted(found, key=lambda h: tuple(int(x) for x in (gurobi_folder_version(h) or "0.0.0").split(".")), reverse=True)
    for h in homes:
        if not h or not os.path.isdir(h):
            continue
        exe = os.path.join(h, "bin", "gurobi_cl" + (".exe" if WIN else ""))
        if os.path.isfile(exe):
            code, out, _ = call([exe, "--version"], timeout=60)
            m = re.search(r"version (\d+\.\d+\.\d+)", out or "") if code == 0 else None
            if m:
                return m.group(1), os.path.abspath(h)
        if gurobi_folder_version(h):
            return gurobi_folder_version(h), os.path.abspath(h)
    return None, None


def package_version(name):
    """The installed version of the Python package `name` (as pip names it), or None."""
    import importlib.metadata
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def gdx_library():
    """'' when the GDX library (gamspy_base's, else GAMS_DIR's) loads, else why not. Its folder is added to the DLL
    search path first, as times_eq/gams/gamslp.py and times_pp/tools/jacobian_gdx.py do (some Pythons, the Microsoft
    Store's for one, do not find the libraries it needs through PATH, where gams.transfer puts the folder)."""
    try:
        import gams.transfer as gt
        try:
            import gamspy_base
            d = gamspy_base.directory
        except ImportError:
            d = os.environ.get("GAMS_DIR")
        if not d:
            return ""
        if WIN and hasattr(os, "add_dll_directory") and os.path.isdir(d):
            _DLL_DIRS.append(os.add_dll_directory(d))
        gt.Container(system_directory=d)
        return ""
    except ImportError:
        return ""                                        # the missing package is reported on its own
    except Exception as x:
        return (str(x).splitlines() or [type(x).__name__])[0][:200]


_DLL_DIRS = []


def julia_ready(julia):
    if not julia or not os.path.isfile(os.path.join(JULIA_ENV, "Manifest.toml")):
        return False, "the Julia packages are not installed"
    code, out, _ = call([julia, "--startup-file=no", f"--project={JULIA_ENV}", "-e", "using TimesEq, JuMP, HiGHS; print(\"ok \", VERSION)"], timeout=1800)
    ok = code == 0 and "ok " in out
    return ok, ("" if ok else julia_error(out)) or (out.strip().splitlines()[-1] if out.strip() else "no output")


def julia_error(out):
    """The part of a Julia output that says what failed: from the first ERROR line, at most 25 lines."""
    lines = out.strip().splitlines()
    i = next((k for k, l in enumerate(lines) if l.lstrip().startswith("ERROR") or "Failed to precompile" in l), None)
    return "" if i is None else "\n".join(lines[i:i + 25])


def check(verbose=True):
    """-> (ready for the open chain, ready for the comparison with GAMS, lines)"""
    s = settings()
    lines, chain, gams_ok = [], True, True
    ok = sys.version_info >= (3, 11)
    chain &= ok
    lines.append(("ok" if ok else "MISSING", "Python", f"{platform.python_version()} ({sys.executable})" + ("" if ok else "  -> Python 3.11 or newer is needed")))
    found, missing = python_packages()
    need = [m for m in missing if m[0] in ("duckdb", "pandas", "numpy")]
    chain &= not need
    lines.append(("ok" if not need else "MISSING", "Python packages (preprocessor)", ", ".join(f"{k} {v}" for k, v in found.items() if k in ("duckdb", "pandas", "numpy"))
                  + ("  -> missing: " + ", ".join(m[1] for m in need) + "; run: python TIMES.py setup" if need else "")))
    seg = True
    if WIN:
        exe, heap = pp_python()
        seg = heap == "Segment Heap"
        lines.append(("ok" if seg else "NOTE", "Preprocessor heap", f"{heap} ({exe})" if seg else
                      heap + "; the preprocessor runs about half as fast"))
    cpus = os.cpu_count() or 4
    lines.append(("ok", "Threads", f"DuckDB {os.environ['TIMESPP_THREADS'] + ' (TIMESPP_THREADS)' if os.environ.get('TIMESPP_THREADS') else min(8 if seg else 4, cpus)}; "
                  f"Julia {(os.environ.get('JULIA_NUM_THREADS') or 'auto') + ' (' + str(cpus) + ' processors)'}, "
                  f"garbage collector {os.environ.get('JULIA_NUM_GC_THREADS') or max(1, min(12, cpus // 2))}, "
                  f"at most {os.environ.get('TIMESEQ_PAR_WORKERS') or 8} equation families at once (4 when memory is short)"))
    gdx_err = gdx_library() if "gams.transfer" in found else ""
    gdx = "gams.transfer" in found and not gdx_err
    gdx_why = (f"  -> the GDX library does not load: {gdx_err}" if gdx_err else
               "not installed: needed only for the comparison with TIMES in GAMS, --lp and --jacobian  -> run: python TIMES.py setup --gdx")
    lines.append(("ok" if gdx else "NOTE", "Python packages (GDX: the comparison with GAMS, --lp, --jacobian)", ", ".join(f"{k} {v}" for k, v in found.items() if k in ("gams.transfer", "gamspy_base"))
                  + ("" if gdx else gdx_why)
                  + ("" if "gamspy_base" in found or not gdx else "  (gamspy_base not installed: the GDX library of the GAMS installation is used)")))
    julia = find_julia()
    if julia:
        _, out, _ = call([julia, "--version"], timeout=120)
        ready, why = julia_ready(julia)
        chain &= ready
        lines.append(("ok", "Julia", f"{out.strip()} ({julia})"))
        lines.append(("ok" if ready else "MISSING", "Julia packages (TimesEq, JuMP, HiGHS)", "installed in .julia_env" if ready else f"{why}  -> run: python TIMES.py setup"))
        man = os.path.join(JULIA_ENV, "Manifest.toml")
        kern = os.path.isfile(man) and "TimesPPKernels" in read(man) and bool(s.get("julia_bindir"))
        lines.append(("ok" if kern else "NOTE", "Julia kernels of the preprocessor", "TimesPPKernels in .julia_env (on by default; TIMESPP_KERNELS=none turns them off)"
                      if kern else "not installed: the preprocessor runs without them  -> run: python TIMES.py setup"))
        # Ipopt: the calibration of TIMES-MACRO MLF (times_eq/tools/mlf_calibrate.jl); every other run goes without it
        ipopt = os.path.isfile(man) and re.search(r'(?m)^\[\[deps\.Ipopt\]\]', read(man)) is not None
        lines.append(("ok" if ipopt else "NOTE", "Ipopt (the calibration of TIMES-MACRO MLF)", "installed in .julia_env" if ipopt
                      else "not installed: a run with MACRO MLF cannot calibrate  -> run: python TIMES.py setup"))
        # stochastic TIMES: its equations compiled ahead are an add-on, compiled by setup or by the first such run
        if ready and stochastic_installed():
            julia_compiled(julia)
        lines.append(("ok", "Stochastic TIMES (STAGES, SPINES): its add-on", "compiled (TimesEqStochastic in .julia_env)")
                     if ready and stochastic_installed() and STOCH["compiled"] else
                     ("NOTE", "Stochastic TIMES (STAGES, SPINES): its add-on",
                      ("installed, not compiled" if ready and stochastic_installed() else "not installed")
                      + ": the first run with STAGES or SPINES compiles it (a few minutes, once); python TIMES.py setup does it now"))
    else:
        chain = False
        lines.append(("MISSING", "Julia", "not found  -> run: python TIMES.py setup   (it installs Julia: winget's Juliaup, the Microsoft Store's "
                      "Julia, or a portable copy into .julia_bin; or give the place of your own: setup --julia <julia executable>)"))
    src = find_times()
    if src:
        v = times_version(src)
        lines.append(("ok" if v == PORT_VERSION else "NOTE", "TIMES source", f"v{v} ({src})" + ("" if v == PORT_VERSION else f"  -> this implementation follows v{PORT_VERSION}; results can differ with another version")))
    else:   # the open chain carries the TIMES declarations it reads (times_pp/timespp/times_src): the source is for GAMS only
        lines.append(("NOTE", "TIMES source", f"not found  -> needed only to run GAMS for the comparison: git clone --branch v{PORT_VERSION} --depth 1 {TIMES_REPO} \"{os.path.join(ROOT, 'TIMES_model-v' + PORT_VERSION)}\"   "
                      "(or give its place: setup --times <folder with initsys.mod>)"))
    gams = find_gams()
    gams_ok = bool(gams) and gdx
    lines.append(("ok" if gams else "NOTE", "GAMS", gams or "not found  -> needed only for the comparison with TIMES in GAMS (run --check); give its place with: setup --gams <gams executable>"))
    lp_gams = gams_for_lp()
    if lp_gams:
        a = gams_lp_solvers(lp_gams)
        lines.append(("ok" if a.get("licensed") else "NOTE", "GAMS for --lp <solver>",
                      f"GAMS {a.get('version') or '(version not found)'} ({lp_gams}); "
                      + ("LP solvers of its licence: " + ", ".join(a["licensed"]) if a.get("licensed") else
                         f"its LP solvers could not be listed: {a['error']}" if a.get("error") else "no LP solver licensed for models of this size")))
    else:
        lines.append(("NOTE", "GAMS for --lp <solver>", "not found: needed only to solve with a solver of your GAMS (HiGHS, the default, needs nothing)"))
    g_ver, g_home = find_gurobi()
    have, sci = package_version("gurobipy"), package_version("scipy")
    if have and sci:
        lines.append(("ok" if not g_ver or g_ver == have else "NOTE", "Python packages (--gurobi)", f"gurobipy {have}, scipy {sci}"
                      + (f"  -> Gurobi {g_ver} is installed ({g_home}): run: python TIMES.py setup (it installs gurobipy {g_ver})" if g_ver and g_ver != have else "")))
    else:
        lines.append(("NOTE", "Python packages (--gurobi)", "gurobipy and scipy not installed: needed only for --gurobi  -> "
                      + (f"run: python TIMES.py setup (it installs gurobipy {g_ver}, for Gurobi {g_ver} in {g_home})" if g_ver else
                         "no Gurobi found here; run: python TIMES.py setup --gurobi <the version of your Gurobi licence>")))
    lines.append(("ok", "This code", revision()))
    if verbose:
        for st, what, text in lines:
            print(f"  {st:8}{what:46}{text}")
        print()
        print("  The open chain (DD files -> Python -> Julia -> HiGHS) " + ("is ready." if chain else "is NOT ready: see MISSING above."))
        print("  The comparison with GAMS " + ("is ready." if chain and gams_ok else "is NOT ready." if chain else "needs the chain first."))
    return chain, chain and gams_ok, lines


# ----------------------------------------------------------------------------------------------------------------
# setup
def reduce_of(run_text):
    """REDUCE as the run file sets it, without quotes, as TIMES compares it (case and all); None when the run file does
    not set it.  Read as the preprocessor reads the run file (timespp/gamsdata.py: $IF NOT SET ... $SET, several SETs
    on one line, $ONTEXT blocks), so that what is reported is what is built."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("tj_gamsdata", os.path.join(ROOT, "times_pp", "timespp", "gamsdata.py"))
        m = sys.modules.get("tj_gamsdata")
        if m is None:
            m = importlib.util.module_from_spec(spec)
            sys.modules["tj_gamsdata"] = m           # (before it runs: its dataclasses look their module up there)
            spec.loader.exec_module(m)
        rd = m.Reader()
        rd.read_text(run_text, src="run")
        v = rd.env.get("REDUCE")
        return None if v is None else str(v).strip().strip("'\"")
    except Exception:
        found = re.findall(r"(?im)^[ \t]*\$[ \t]*SET(?:GLOBAL|LOCAL)?[ \t]+REDUCE[ \t]+(\S+)", run_text)
        return found[-1].strip("'\"") if found else None


def reduce_level(value):
    """The level of the model reduction that TIMES makes of a REDUCE value: NO (none), YES (the whole reduction), or
    PART for any other value or none at all (the capacity variables and the emissions only: pp_reduce.red)."""
    return value if value in ("NO", "YES") else "PART"


def reduce_text(value):
    return value if value is not None else "none (no $SET REDUCE line)"


def with_reduce(run_text, value):
    """The run file with REDUCE set to `value`: every $SET REDUCE given the value (also one behind $IF NOT SET REDUCE),
    or, with none, a $SET REDUCE line before the first $BATINCLUDE."""
    new, k = re.subn(r"""(?i)(\$[ \t]*SET(?:GLOBAL|LOCAL)?[ \t]+REDUCE[ \t]+)('[^'\n]*'|"[^"\n]*"|\S+)""",
                     lambda m: m.group(1) + f"'{value}'", run_text)
    if k == 0:
        new = re.sub(r"(?im)^(\s*\$\s*BATINCLUDE\s)", f"$SET REDUCE '{value}'\n\\1", run_text, count=1)
    return new


def reduce_no(run_text):
    """The run file with REDUCE set to NO: the model without reduction."""
    return with_reduce(run_text, "NO")


def same_reduce(R, G):
    """GAMS's model is the one built here: both at the same REDUCE level (a report written before the port followed
    the run file's REDUCE was built with NO)."""
    built = ((R.get("input") or {}).get("reduce") or {}).get("built", "NO")
    return reduce_level(G.get("REDUCE")) == reduce_level(built)


MILESTONE_RE = re.compile(r"(?ims)^(\s*SET\s+MILESTONYR\s*/)([^/]*)(/\s*;?)")   # GAMS takes the statement without its ;




WORKLOAD_DIR = os.path.join(ROOT, "times_eq", "precompile")
WORKLOAD_TXT = os.path.join(WORKLOAD_DIR, "WORKLOAD.txt")
WORKLOAD_JSON = os.path.join(WORKLOAD_DIR, "model.json")
TIMESEQ_UUID = "cb114957-84c0-488e-862f-6e374d3cba32"


def workload_mode():
    """'full' (a whole case is compiled ahead), 'dev' (setup --dev) or '' (no workload written yet)."""
    t = read(WORKLOAD_TXT) if os.path.isfile(WORKLOAD_TXT) else ""
    m = re.search(r"(?m)^mode: (\w+)", t)
    return m.group(1) if m else ""


def pp_fingerprint():
    """sha256 of the preprocessor's code (times_pp/timespp), to know when the workload tables are out of date."""
    h = hashlib.sha256()
    base = os.path.join(ROOT, "times_pp", "timespp")
    for d, dirs, files in sorted(os.walk(base)):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            if f.endswith((".py", ".json")):
                h.update(os.path.relpath(os.path.join(d, f), base).replace("\\", "/").encode())
                with open(os.path.join(d, f), "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()[:16]


def tables_fingerprint(db):
    """sha256 of the table and column names of a preprocessed model: what the compiled code depends on."""
    import sqlite3
    con = sqlite3.connect(db)
    try:
        h = hashlib.sha256()
        for (t,) in con.execute("select name from sqlite_master where type = 'table' order by name"):
            cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
            h.update((t + ":" + ",".join(cols) + "\n").encode())
        return h.hexdigest()[:16]
    finally:
        con.close()


def write_workload_txt(mode, tables=""):
    """WORKLOAD.txt is a dependency of the compiled package: when its text changes, Julia compiles TimesEq again.
    So it holds only what the compiled code depends on (the mode and the table layout), and is rewritten only when
    that changes. -> True if it changed."""
    text = ("The precompile workload of TimesEq (src/TimesEq.jl). Written by TIMES.py; not in the repository.\n"
            "full: a whole case is run on model.db3 (models/DemoS_012, preprocessed) when the package is compiled.\n"
            "dev (setup --dev): only the equation functions are compiled ahead.\n"
            "Julia compiles the package again when this text changes.\n\n"
            f"mode: {mode}\n" + (f"tables: {tables}\n" if tables else ""))
    if os.path.isfile(WORKLOAD_TXT) and read(WORKLOAD_TXT) == text:
        return False
    os.makedirs(WORKLOAD_DIR, exist_ok=True)
    write(WORKLOAD_TXT, text)
    return True


def write_workload(src, mode="full"):
    """The precompile workload of TimesEq. full: the tables of models/DemoS_012 (times_eq/precompile/model.db3),
    made by the preprocessor as a run makes them, and WORKLOAD.txt; dev: WORKLOAD.txt only. -> True if written."""
    if mode == "dev":
        write_workload_txt("dev")
        print("   precompile workload: dev (setup --dev): only the equation functions are compiled ahead")
        return True
    import tempfile
    os.makedirs(WORKLOAD_DIR, exist_ok=True)
    model = os.path.join(ROOT, "models", "DemoS_012")
    tmp = tempfile.mkdtemp(prefix="tj_workload_")
    db = os.path.join(WORKLOAD_DIR, "model.db3")
    try:
        for f in os.listdir(model):
            if os.path.isfile(os.path.join(model, f)):
                shutil.copy2(os.path.join(model, f), os.path.join(tmp, f))
        run_file = os.path.join(tmp, "demos_012.run")
        write(run_file, reduce_no(read(run_file)))
        new = os.path.join(tmp, "model.db3")
        code, out, t = call([pp_python()[0], "-m", "timespp", run_file, "-", new], cwd=os.path.join(ROOT, "times_pp"), timeout=1800)
        if code == 0 and os.path.isfile(new):
            shutil.copy2(new, db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if code != 0:
        print("   the tables for the precompile workload could not be written:\n" + (out or "")[-1500:])
        return False
    write(WORKLOAD_JSON, json.dumps({"preprocessor": pp_fingerprint(), "tables": tables_fingerprint(db)}, indent=1))
    changed = write_workload_txt("full", tables_fingerprint(db))
    print(f"   the tables of models/DemoS_012 for the precompile workload: {os.path.relpath(db, ROOT)}  ({t:.0f} s)"
          + ("" if changed else "; table layout unchanged"))
    return True


def refresh_workload():
    """Before a run: when the preprocessor changed since the workload tables were written, write them again, so that
    the next compilation of TimesEq does not run on tables the code no longer reads. Julia compiles again only if
    the table layout changed."""
    mode = workload_mode()
    if mode == "dev":
        return
    if mode != "full":                    # no WORKLOAD.txt, or one written before 2026-10-10 (no mode line): full, as setup does
        src = None
        print("The precompile workload is from an older setup: writing it again (Julia then compiles TimesEq once) ...", flush=True)
        write_workload(src)
        return
    try:
        seen = json.loads(read(WORKLOAD_JSON)).get("preprocessor") if os.path.isfile(WORKLOAD_JSON) else None
    except ValueError:
        seen = None
    if seen == pp_fingerprint() and os.path.isfile(os.path.join(WORKLOAD_DIR, "model.db3")):
        return
    src = None
    print("The preprocessor changed since the tables of the precompile workload were written: writing them again ...", flush=True)
    write_workload(src)


def julia_compiled(julia):
    """Whether TimesEq is compiled for the current code (False: the next Julia start compiles it). None if unknown.
    The same Julia start says it for the add-on of stochastic TIMES, when that is installed (STOCH["compiled"])."""
    code, out, _ = call([julia, "--startup-file=no", f"--project={JULIA_ENV}", "-e",
                         f'print(Base.isprecompiled(Base.PkgId(Base.UUID("{TIMESEQ_UUID}"), "TimesEq")))'
                         + (f'; print(" ", Base.isprecompiled(Base.PkgId(Base.UUID("{STOCH_UUID}"), "{STOCH_ADDON}")))' if stochastic_installed() else "")],
                        timeout=300)
    words = out.strip().splitlines()[-1].split() if code == 0 and out.strip() else []
    known = {"true": True, "false": False}
    STOCH["compiled"] = known.get(words[1]) if len(words) > 1 else None
    return known.get(words[0]) if words else None


# Stochastic TIMES (STAGES, SPINES). The equations are TimesEq's; compiled ahead for the stochastic variable families
# they are in a package of their own, times_eq/addons/TimesEqStochastic, which only models with one of the two switches
# need. setup installs and compiles it; where it is missing or out of date the first such run does (stochastic_addon).
STOCH_ADDON = "TimesEqStochastic"
STOCH_UUID = "9df4f6c9-5869-4434-ac3d-16d3750b7416"
STOCH_PATH = os.path.join(ROOT, "times_eq", "addons", STOCH_ADDON)
STOCH = {"compiled": None}      # whether the add-on is compiled for the current code, once this process has asked Julia


def needs_stochastic(run_text):
    """True for a run file whose model has the variable families of stochastic TIMES: STAGES or SPINES, and not
    SENSIS (a SENSIS run builds one deterministic model for each state of the world)."""
    yes = lambda k: (switch(run_text, k) or "") == "YES"
    return (yes("STAGES") or yes("SPINES")) and not yes("SENSIS")


def stochastic_installed():
    """The add-on of stochastic TIMES is in .julia_env."""
    man = os.path.join(JULIA_ENV, "Manifest.toml")
    return os.path.isfile(man) and re.search(rf'(?m)^\[\[deps\.{STOCH_ADDON}\]\]', read(man)) is not None


def stochastic_addon(julia, case=""):
    """Before Julia is started for a model with STAGES or SPINES: the add-on is added to .julia_env when it is not
    there (from this repository; no download) and compiled when it is not (once, several minutes), and each is said,
    so that the wait is explained. -> True when the run can load it; False: the run compiles that code itself."""
    if not julia or not os.path.isdir(STOCH_PATH):
        return False
    tag = f"[{case}] " if case else ""
    if STOCH["compiled"]:
        return True
    if not stochastic_installed():
        print(f"{tag}stochastic TIMES: adding its add-on ({STOCH_ADDON}, from this repository) to .julia_env ...", flush=True)
        path = STOCH_PATH.replace("\\", "/")
        code, out, t = call([julia, "--startup-file=no", f"--project={JULIA_ENV}", "-e",
                             f'using Pkg; Pkg.offline(true); Pkg.develop(Pkg.PackageSpec(path="{path}"))'],
                            env={"JULIA_PKG_PRECOMPILE_AUTO": "0"}, timeout=1800)
        if code != 0 or not stochastic_installed():
            print(f"{tag}   NOT added: this run compiles the equations of stochastic TIMES itself\n" + (julia_error(out) or out[-1500:]), flush=True)
            return False
        pin_timeseq_path()
        STOCH["compiled"] = None
    if STOCH["compiled"] is None:
        julia_compiled(julia)
    if not STOCH["compiled"]:
        print(f"{tag}stochastic TIMES: compiling its add-on once (several minutes); later runs start at once ...", flush=True)
        code, out, t = call([julia, "--startup-file=no", f"--project={JULIA_ENV}", "-e", f'using Pkg; Pkg.precompile("{STOCH_ADDON}")'], timeout=7200)
        if code != 0 or julia_error(out):
            print(f"{tag}   NOT compiled: this run compiles the equations of stochastic TIMES itself\n" + (julia_error(out) or out[-1500:]), flush=True)
            return False
        print(f"{tag}   done  ({t:.0f} s)", flush=True)
        STOCH["compiled"] = True
    return True


def compile_notice(julia):
    """Say so before a run when Julia will compile TimesEq first, so that the wait is not taken for a hang."""
    if julia and julia_compiled(julia) is False:
        mode = workload_mode()
        how = ("about 2 minutes (setup --dev)" if mode == "dev" else
               "about 5 minutes, with the whole-case workload; setup --dev makes this shorter while times_eq/src is being changed")
        print(f"TimesEq is compiled again before the first model ({how}): times_eq/src, its workload or a Julia package changed.", flush=True)


def example_copy():
    """models/DemoS_012 in runs/_setup_test/input: a run writes results into its run folder, and models/ stays as it is."""
    copy = os.path.join(ROOT, "runs", "_setup_test", "input", "DemoS_012")
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "models", "DemoS_012"), copy)
    return copy


def fetch_times_source(found=None):
    """The TIMES source of the version this implementation follows, from IEA-ETSAP's repository (TIMES_REPO) into
    TIMES_model-v<version> in this folder: with git when it is installed, else the tag's zip file.  The folder, or None;
    a folder of that name that is not that source is left as it is."""
    dest = os.path.join(ROOT, "TIMES_model-v" + PORT_VERSION)
    if os.path.exists(dest):
        print(f"   {dest} is there and is not the TIMES source v{PORT_VERSION}: left as it is (give the source with --times <folder>)")
        return None
    print("2. TIMES source " + (f"is v{times_version(found)} ({found})" if found else "not found") + f": fetching v{PORT_VERSION} from "
          f"{TIMES_REPO} into {dest} ...\n   (IEA-ETSAP's, under its own licence; used only for the comparison with TIMES in GAMS; "
          "setup --no-times-source does not fetch it)")
    t0 = time.time()
    if shutil.which("git"):
        code, out, _ = call(["git", "clone", "--branch", "v" + PORT_VERSION, "--depth", "1", TIMES_REPO, dest], timeout=1800)
    else:
        import io, urllib.request
        part = dest + ".part"
        try:
            with urllib.request.urlopen(f"{TIMES_REPO}/archive/refs/tags/v{PORT_VERSION}.zip", timeout=600) as r:
                data = r.read()
            shutil.rmtree(part, ignore_errors=True)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(part)
            inner = [os.path.join(part, d) for d in os.listdir(part)]
            shutil.move(inner[0] if len(inner) == 1 and os.path.isdir(inner[0]) else part, dest)
            code, out = 0, ""
        except Exception as x:
            code, out = 1, f"{type(x).__name__}: {x}"
        shutil.rmtree(part, ignore_errors=True)
    ok = code == 0 and times_version(dest) == PORT_VERSION
    print("   " + (f"done  ({time.time() - t0:.0f} s)" if ok else "FAILED:\n" + (out or "")[-1500:]))
    return dest if ok else None


def setup(args):
    opt = lambda name: args[args.index(name) + 1] if name in args else None
    if "--skip-install" not in args and not os.path.isfile(venv_python()):
        if sys.version_info < (3, 11):
            print(f"Python 3.11 or newer is needed to create .venv ({platform.python_version()} at {sys.executable}).")
            return 1
        print("Creating .venv ...")
        code, out, t = call([sys.executable, "-m", "venv", VENV])
        if code != 0 or not os.path.isfile(venv_python()):
            print("   FAILED to create .venv" + (":\n" + out[-2000:] if out else f" (exit {code})") + f"  ({t:.0f} s)")
            return 1
        print(f"   done  ({t:.0f} s)")
    forwarded = reexec_in_venv()
    if forwarded is not None:
        return forwarded
    s = settings()
    print("TIMES-OS setup\n")
    if "--skip-install" not in args:
        print("1. Python packages (.venv, pip install -r requirements.txt) ...")
        code, out, t = call([sys.executable, "-m", "pip", "install", "-r", os.path.join(ROOT, "requirements.txt")])
        print("   " + ("done" if code == 0 else "FAILED:\n" + out[-2000:]) + f"  ({t:.0f} s)")
        # the GDX packages (requirements-gams.txt; gamspy_base comes under the GAMS licence): only with GAMS, or when asked
        if find_gams(opt("--gams")) or "--gdx" in args:
            print("   the GDX packages (requirements-gams.txt: gamsapi[transfer], gamspy_base), for the comparison with TIMES in"
                  " GAMS, --lp and --jacobian ...")
            code, out, t = call([sys.executable, "-m", "pip", "install", "-r", os.path.join(ROOT, "requirements-gams.txt")])
            print("   " + ("done" if code == 0 else "FAILED:\n" + out[-2000:]) + f"  ({t:.0f} s)")
        else:
            print("   GAMS not found: the GDX packages (requirements-gams.txt) are not installed; they serve only the comparison"
                  " with TIMES in GAMS, --lp and --jacobian (setup --gdx installs them)")
        # --gurobi: gurobipy of the version of the Gurobi found here (a Gurobi licence is for one version), and scipy
        g_ver, g_home = (opt("--gurobi"), None) if opt("--gurobi") else find_gurobi()
        if not g_ver:
            print("   gurobipy not installed: no Gurobi found (needed only for --gurobi; setup --gurobi <version> installs that version)")
        elif package_version("gurobipy") == g_ver and package_version("scipy"):
            print(f"   gurobipy {g_ver} and scipy, for --gurobi: installed")
        else:
            print(f"   gurobipy {g_ver} and scipy, for --gurobi (" + (f"Gurobi {g_ver} in {g_home}" if g_home else "setup --gurobi") + ") ...")
            code, out, t = call([sys.executable, "-m", "pip", "install", f"gurobipy=={g_ver}", "scipy"])
            if code == 0:
                print(f"   done  ({t:.0f} s)")
            elif "No matching distribution" in out or "Could not find a version" in out:
                print(f"   not installed: gurobipy {g_ver} is not available from pip for this Python (needed only for --gurobi;"
                      " setup --gurobi <version> installs another version, for a licence of that version)")
            else:
                print("   not installed (needed only for --gurobi):\n" + out[-2000:] + f"  ({t:.0f} s)")
    if WIN and "--no-segheap" in args:
        shutil.rmtree(SEGHEAP, ignore_errors=True)
        s["segment_heap"] = {"status": "off", "why": "setup --no-segheap"}
        write(SETTINGS, json.dumps(s, indent=1))
        print("   no Segment Heap copy (setup --no-segheap): the preprocessor runs on Windows's default heap")
    elif WIN and in_project_venv():
        print("   the preprocessor's interpreter on the Segment Heap (.venv/segheap) ...")
        s["segment_heap"] = make_segheap()
        write(SETTINGS, json.dumps(s, indent=1))
        print("   " + (("done: the preprocessor runs on the Segment Heap" + (f" ({s['segment_heap']['how']})" if s["segment_heap"].get("how") else ""))
                     if s["segment_heap"]["status"] == "ok" else
                     f"NOT made ({s['segment_heap']['why']}): the preprocessor runs on Windows's default heap, about half as fast"))
    src = find_times(opt("--times"))
    fetch = not opt("--times") and "--no-times-source" not in args and (not src or times_version(src) != PORT_VERSION)
    fetch = fetch and bool(find_gams(opt("--gams")))        # the source serves only the comparison with TIMES in GAMS
    if fetch:
        other = find_times(any_saved=False)
        src = other if other and times_version(other) == PORT_VERSION else (fetch_times_source(src) or src)
    if src and times_version(src) != PORT_VERSION:
        print(f"   TIMES source is v{times_version(src)}; this implementation follows v{PORT_VERSION}")
    julia = find_julia(opt("--julia"))
    if opt("--install-julia") or (not julia and not opt("--julia") and "--no-julia-install" not in args):
        print("2. Julia " + (f"(--install-julia {opt('--install-julia')})" if opt("--install-julia") else "was not found: installing it") + " ...")
        julia = install_julia(opt("--install-julia")) or julia
    if julia:
        s["julia"] = for_settings(julia)
        if "--skip-install" not in args:
            print("3. Julia packages (TimesEq from this repository, JuMP, HiGHS, Ipopt; several minutes the first time) ...")
            write_workload(src, "dev" if "--dev" in args else "full")
            path = os.path.join(ROOT, "times_eq").replace("\\", "/")
            # TimesPPKernels: the preprocessor's Julia kernels (times_pp/jlkernels; on by default, TIMESPP_KERNELS=none turns them off)
            kpath = os.path.join(ROOT, "times_pp", "jlkernels").replace("\\", "/")
            # the add-on of stochastic TIMES is compiled with the rest; --dev leaves it out of .julia_env (what was
            # compiled of it stays), and the first run with STAGES or SPINES puts it in
            kind = "dev" if "--dev" in args else "full"
            spath = STOCH_PATH.replace("\\", "/")
            addon = (f', Pkg.PackageSpec(path="{spath}")' if kind == "full" else "")
            leave = ("" if kind == "full" else f'haskey(Pkg.project().dependencies, "{STOCH_ADDON}") && Pkg.rm("{STOCH_ADDON}"); ')
            if kind == "dev":
                print("   stochastic TIMES (STAGES, SPINES): --dev leaves its add-on out; the first run of such a model compiles it")
            code, out, t = call([julia, "--startup-file=no", f"--project={JULIA_ENV}", "-e",
                                 f'using Pkg; Pkg.develop([Pkg.PackageSpec(path="{path}"), Pkg.PackageSpec(path="{kpath}"){addon}]); '
                                 f'Pkg.add(["JuMP", "HiGHS", "Ipopt"]); {leave}Pkg.precompile()'], env={"JULIA_PKG_PRECOMPILE_AUTO": "0"}, timeout=7200)
            s["setup"] = kind
            if code == 0 and julia_error(out):              # Pkg.precompile can report a failed package and still exit 0
                code = 1
            print("   " + ("done" if code == 0 else "FAILED:\n" + out[-3000:]) + f"  ({t:.0f} s)")
            if code == 0:
                pin_timeseq_path()
                # where libjulia is, for the kernels the preprocessor runs in its own process (timespp/kernels.py)
                bc, bout, _ = call([julia, "--startup-file=no", "-e", "print(Sys.BINDIR)"], timeout=600)
                bindir = bout.strip().splitlines()[-1] if bc == 0 and bout.strip() else ""
                if os.path.isdir(bindir):
                    s["julia_bindir"] = bindir
    else:
        print("3. Julia is not installed (see above): the Julia packages are not installed either.")
    if src:
        s["times"] = for_settings(src)
    gams = find_gams(opt("--gams"))
    if gams:
        s["gams"] = for_settings(gams)
    s.pop("gams_lp", None)                                  # the LP solvers of the user's GAMS: found again by check below
    write(SETTINGS, json.dumps(s, indent=1))
    print("\nWhat is there now:\n")
    chain, _, _ = check()
    if not chain:
        print("\nSetup is not complete.  Do what the MISSING lines say and run setup again.")
        return 1
    if "--no-test" in args:
        return 0
    print("\nThe example model (models/DemoS_012, compared with its published GAMS result) ...\n")
    code = run([example_copy(), "--out", os.path.join(ROOT, "runs", "_setup_test")])
    rep = json.loads(read(os.path.join(ROOT, "runs", "_setup_test", "DemoS_012", "report_DemoS_012.json")))
    want = json.loads(read(os.path.join(ROOT, "models", "DemoS_012", "expected.json")))
    obj = rep.get("julia", {}).get("objective")
    good = obj is not None and abs(obj - want["objective"]) <= 1e-9 * abs(want["objective"]) and rep["verdict"].split(":")[0] in ("SAME", "SAME OBJECTIVE", "SOLVED")
    print("\nSetup " + (f"is complete: the example gives the expected objective {want['objective']}" + (", and the model is the published GAMS one." if rep["verdict"].startswith("SAME") else ".")
          if good else f"FAILED on the example: {rep['verdict']}\nSee {os.path.join(ROOT, 'runs', '_setup_test', 'DemoS_012', 'report_DemoS_012.txt')}"))
    return 0 if good else 1


# ----------------------------------------------------------------------------------------------------------------
# one model
def run_files(folder):
    return [f for f in sorted(glob.glob(os.path.join(folder, "*.[rR][uU][nN]"))) if os.path.basename(f).lower() != "runfile.run"]


def is_run_file(f):
    return os.path.isfile(f) and os.path.splitext(f)[1].lower() == ".run"


def dd_list(run_file):
    """DD files of the run file, in order: (name as written, path or None).  Veda puts them in the run folder or its parent."""
    folder = os.path.dirname(os.path.abspath(run_file))
    out = []
    for m in re.finditer(r"(?im)^\s*\$\s*(?:BAT)?INCLUDE\s+(\S+)", read(run_file)):
        name = m.group(1).strip("'\"")
        if not name.lower().endswith(".dd"):             # (no file of TIMES or Veda has .dds; the preprocessor refuses it)
            continue
        path = None
        for d in (folder, os.path.dirname(folder)):
            for cand in os.listdir(d):
                if cand.lower() == name.lower():
                    path = os.path.join(d, cand)
                    break
            if path:
                break
        out.append((name, path))
    return out


def switch(text, name):
    """Value of $SET name in a run file (the last one that is not commented out)."""
    m = re.findall(rf"(?im)^\s*\$\s*SET(?:GLOBAL|LOCAL)?\s+{name}\s+(\S+)", text)
    return m[-1].strip("'\"").upper() if m else None


def run_name(text):
    """RUN_NAME of a run file as written (the names of the results it writes: <RUN_NAME>_p, <RUN_NAME>_DP)."""
    m = re.findall(r"(?im)^\s*\$\s*SET(?:GLOBAL|LOCAL)?\s+RUN_NAME\s+(\S+)", text)
    return m[-1].strip("'\"") if m else None


def raw_switch(text, name):
    """Value of $SET name in a run file as written (case and path kept), or None."""
    m = re.findall(rf"(?im)^\s*\$\s*SET(?:GLOBAL|LOCAL)?\s+{name}\s+(\S+)", text)
    return m[-1].strip("'\"") if m else None


def gams_base_files(folder, text):
    """The GDX files of earlier runs that TIMES in GAMS reads from the run folder (LPOINT: spoint.mod 10-11;
    TIMESED: readbprice.mod 13-16), for the run of GAMS made here in a copy of the folder.  The copy has no gamssave
    folder, so its GDXPATH is the copy itself: a file is copied there under the name GAMS looks for, and a name that
    carries a path is given in the copy's run file as the absolute path of the file it names in the run folder.
    -> (copies [(file, name in the copy)], {switch: new value})."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("tj_refpoint", os.path.join(ROOT, "times_pp", "timespp", "refpoint.py"))
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    copies, values = [], {}
    def take(name, suffixes, in_gdxpath=True, switch_name=None):
        if switch_name and re.search(r"[\\/:]", name):
            d, st = rp.locate(folder, name, in_gdxpath)
            values[switch_name] = os.path.join(d, st)
            return
        for sfx in suffixes:
            d, st = rp.locate(folder, name + sfx, in_gdxpath)
            p = rp._exists(d, st + ".gdx")
            if p:
                copies.append((p, os.path.basename(name) + sfx + ".gdx"))
    lp = raw_switch(text, "LPOINT")
    if lp:
        take(lp, ("_p", ""), switch_name="LPOINT")
    ed = raw_switch(text, "TIMESED")
    if ed and ed.upper() not in ("NO", "0", "YES"):
        take(ed, ("_DP", ""), switch_name="TIMESED")
    if ed and ed.upper() not in ("NO", "0"):
        take("com_bprice", ("",), in_gdxpath=False)                    # (readbprice.mod 13: else com_bprice)
    return copies, values


def parse_listing(path):
    t = read(path)
    g = {"listing": path}
    def last(pat, conv=str):
        m = re.findall(pat, t)
        return conv(m[-1]) if m else None
    n = lambda s: int(s.replace(",", ""))
    g["gams_version"] = (re.search(r"GAMS (\d+\.\d+\.\d+)", t[:4000]) or re.search(r"GAMS Rev (\d+)", t[:4000]) or [None, None])[1]
    g["times_version"] = last(r"TIMES -- VERSION ([0-9.]+)")
    g["rows"] = last(r"SINGLE EQUATIONS\s+([\d,]+)", n)
    g["columns"] = last(r"SINGLE VARIABLES\s+([\d,]+)", n)
    g["nonzeros"] = last(r"NON ZERO ELEMENTS\s+([\d,]+)", n)
    g["solver"] = last(r"(?m)^\s+SOLVER\s+(\S+)")
    g["solver_status"] = last(r"\*\*\*\* SOLVER STATUS\s+(.+)", str.strip)
    g["model_status"] = last(r"\*\*\*\* MODEL STATUS\s+(.+)", str.strip)
    g["objective"] = last(r"\*\*\*\* OBJECTIVE VALUE\s+([-+0-9.EeDd]+)", lambda s: float(s.replace("D", "E").replace("d", "e")))
    # a myopic run (TIMESTEP) solves once per step: the statistics and objective of every solve, in order
    g["step_sizes"] = list(zip(*(map(n, re.findall(pat, t)) for pat in (r"SINGLE EQUATIONS\s+([\d,]+)", r"SINGLE VARIABLES\s+([\d,]+)", r"NON ZERO ELEMENTS\s+([\d,]+)"))))
    g["step_objectives"] = [float(x.replace("D", "E").replace("d", "e")) for x in re.findall(r"\*\*\*\* OBJECTIVE VALUE\s+([-+0-9.EeDd]+)", t)]
    # the rows GAMS found with no column and a constant that does not satisfy them (INFEASIBLE EQUATIONS; it stops)
    g["infeasible_rows"] = re.findall(r"(?m)^(\w+(?:\([^)]*\))?)\.\.\s+0 =[EGLN]= .*\bINFES\b", t)
    errs = re.findall(r"(?m)^\*\*\*\*\s+\d+ ERROR\(S\).*$|^\*\*\*\* Exec Error.*$|^\*\*\*\*\s*\$\d+.*$|^.*\bError\b.*abort.*$", t)
    # compilation errors are marked `**** $nnn` under the offending line, once per occurrence; GAMS explains each
    # number once at the end of the listing ("nnn  text"): one line per distinct error, with its meaning and count
    out, seen = [], {}
    for e in errs:
        e = e.strip()
        m = re.match(r"\*\*\*\*\s*\$(\d+)", e)
        if m:
            code = m.group(1)
            if code in seen:
                seen[code] += 1
                continue
            seen[code] = 1
            why = re.search(r"(?m)^\s*%s\s{2,}([A-Za-z][A-Za-z ,'()/:-]+?)\s*$" % code, t)
            e = f"compilation error ${code}" + (f": {why.group(1).strip()}" if why else "")
            out.append([e, code])
        else:
            out.append([e[:200], None])
    g["errors"] = [e + (f"  ({seen[c]} occurrences)" if c and seen[c] > 1 else "") for e, c in out[:10]]
    return g


def gams_summary(g):
    if not g:
        return "no GAMS result"
    return f"{g.get('solver_status') or 'no solve'} / {g.get('model_status') or '-'}"


def physical_memory():
    """Bytes of physical memory, or None."""
    try:
        if WIN:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in (
                    "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            return m.ullTotalPhys if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) else None
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return None


def _process_tree_bytes(root, under=None):
    """The working set (resident memory) of every process below `root` (not root itself), summed, in bytes; None where
    the system does not tell (Windows: a Toolhelp snapshot for the parents, K32GetProcessMemoryInfo for each process;
    Linux: /proc). under: a program's name (e.g. "gams"): -> (that sum, the part of it in the processes of that name
    and the processes below them)."""
    try:
        if WIN:
            import ctypes
            from ctypes import wintypes
            k = ctypes.windll.kernel32

            class PE(ctypes.Structure):
                _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                            ("szExeFile", ctypes.c_wchar * 260)]

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            k.OpenProcess.restype = wintypes.HANDLE
            k.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            snap = k.CreateToolhelp32Snapshot(2, 0)                 # TH32CS_SNAPPROCESS
            if not snap or snap == wintypes.HANDLE(-1).value:
                return None
            children, names = {}, {}
            try:
                e = PE(); e.dwSize = ctypes.sizeof(PE)
                ok = k.Process32FirstW(snap, ctypes.byref(e))
                while ok:
                    children.setdefault(e.th32ParentProcessID, []).append(e.th32ProcessID)
                    names[e.th32ProcessID] = os.path.splitext(e.szExeFile)[0].lower()
                    ok = k.Process32NextW(snap, ctypes.byref(e))
            finally:
                k.CloseHandle(snap)

            def size(pid):
                h = k.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
                if not h:
                    return 0
                try:
                    c = PMC(); c.cb = ctypes.sizeof(PMC)
                    return c.WorkingSetSize if k.K32GetProcessMemoryInfo(h, ctypes.byref(c), c.cb) else 0
                finally:
                    k.CloseHandle(h)
        elif os.path.isdir("/proc/self"):
            children, names = {}, {}
            for d in os.listdir("/proc"):
                if d.isdigit():
                    try:
                        with open(f"/proc/{d}/stat") as f:
                            st = f.read()
                        ppid = int(st.rsplit(")", 1)[1].split()[1])
                        children.setdefault(ppid, []).append(int(d))
                        names[int(d)] = st.split("(", 1)[1].rsplit(")", 1)[0].lower()
                    except (OSError, ValueError, IndexError):
                        pass
            page = os.sysconf("SC_PAGE_SIZE")

            def size(pid):
                try:
                    with open(f"/proc/{pid}/statm") as f:
                        return int(f.read().split()[1]) * page
                except (OSError, ValueError, IndexError):
                    return 0
        else:
            return None
        total, part, todo, seen = 0, 0, [(c, False) for c in children.get(root, [])], set()
        while todo:
            p, inside = todo.pop()
            if p in seen or p == root:
                continue
            seen.add(p)
            inside = inside or (under is not None and names.get(p) in under)
            b = size(p)
            total += b
            part += b if inside else 0
            todo += [(c, inside) for c in children.get(p, [])]
        return total if under is None else (total, part)
    except Exception:
        return None


class TreePeak:
    """The peak memory of the processes this run starts: every `interval` seconds the working sets of all the processes
    below this one are summed, and the largest sum is kept for the window that is open (`window(name)`; None closes
    it). Each window keeps its own peak, so a window can be opened more than once. In a window other than "gams", the
    peak of the GAMS processes in it (gams and the processes it starts: --lp) is kept apart too, as "<window>_gams"."""

    GAMS = ("gams", "gamscmex")

    def __init__(self, interval=0.5):
        import threading
        self.interval, self.name, self.peak = interval, None, {}
        self.stop_ = threading.Event()
        self.lock = threading.Lock()
        self.ok = _process_tree_bytes(os.getpid()) is not None
        self.th = threading.Thread(target=self._run, daemon=True)
        if self.ok:
            self.th.start()
            TreePeak.running.add(self)

    running = set()                                         # samplers not closed (a case that stopped on an error leaves one)

    def window(self, name):
        with self.lock:
            self._sample()                                  # a last sample for the window that closes
            self.name = name
            if name is not None:
                self.peak.setdefault(name, 0)

    def _sample(self):
        if self.name is None:
            return
        b = _process_tree_bytes(os.getpid(), under=self.GAMS)
        if b is None:
            return
        b, g = b
        if b > self.peak[self.name]:
            self.peak[self.name] = b
        if g and self.name != "gams" and g > self.peak.get(self.name + "_gams", 0):
            self.peak[self.name + "_gams"] = g

    def _run(self):
        while not self.stop_.wait(self.interval):
            with self.lock:
                self._sample()

    def close(self):
        self.window(None)
        self.stop_.set()
        if self.ok:
            self.th.join(5)
        TreePeak.running.discard(self)
        return {k: round(v / 2**30, 2) for k, v in self.peak.items()}


def julia_threads(tjb):
    """Julia's flags and environment for the build: the equation families are built in threads, and the garbage
    collector marks in threads (build -20% from that alone), unless JULIA_NUM_THREADS, JULIA_NUM_GC_THREADS or
    TIMESEQ_PAR_WORKERS say otherwise. At most 8 families compute at once, 4 when memory is short: they add about
    6.5 GB to the build's peak on a model of 19 M rows.  tjb: model.tjb, whose size gives the expected peak.
    -> (flags, environment, what was used, a note or None)"""
    flags, env, used, note = [], {}, {}, None
    cpus = os.cpu_count() or 1
    if os.environ.get("JULIA_NUM_THREADS"):
        used["threads"] = os.environ["JULIA_NUM_THREADS"] + " (JULIA_NUM_THREADS)"
    else:
        flags.append("--threads=auto")
        used["threads"] = f"auto ({cpus})"
    if os.environ.get("JULIA_NUM_GC_THREADS"):
        used["gc_threads"] = os.environ["JULIA_NUM_GC_THREADS"] + " (JULIA_NUM_GC_THREADS)"
    else:
        gc = max(1, min(12, cpus // 2))
        flags.append(f"--gcthreads={gc}")
        used["gc_threads"] = gc
    if os.environ.get("TIMESEQ_PAR_WORKERS"):
        used["families_at_once"] = os.environ["TIMESEQ_PAR_WORKERS"] + " (TIMESEQ_PAR_WORKERS)"
    else:
        # Julia's peak with HiGHS holding the model, as measured: 45 GB with a model.tjb of 1.5 GB, 34-38 GB with one
        # of 3.3 GB. The size of model.tjb is a poor guide past that, so 30 GB per GB of model.tjb, at most 45 GB (no
        # larger peak measured). Short: less than 1.4 times that (a machine of 64 GB runs the 45 GB case with 8).
        workers, mem = 8, physical_memory()
        peak = min(45.0, 30.0 * os.path.getsize(tjb) / 2**30) if os.path.isfile(tjb) else None
        if mem and peak and mem / 2**30 < 1.4 * peak:
            workers = 4
            note = (f"memory: {mem / 2**30:.0f} GB, less than 1.4 times Julia's expected peak (about {peak:.0f} GB): "
                    "4 equation families built at once instead of 8")
        env["TIMESEQ_PAR_WORKERS"] = str(workers)
        used["families_at_once"] = workers
        used["memory_gb"] = round(mem / 2**30, 1) if mem else None
        used["expected_peak_gb"] = round(peak, 1) if peak else None
    return flags, env, used, note


EARLY = []          # Julia processes started for a run (julia_early) and not given it yet


def julia_early(julia, flags, env=None):
    """Julia started as the preprocessor starts: it loads its packages (about 1.5 s) while the preprocessor runs, and
    waits for its run on its input (times_eq/tools/run_case.jl --wait; `call` with `started`). TIMES_EARLY=0:
    not started early. env: what the packages need to know as they load (TIMESEQ_STOCHASTIC). -> the process, or None"""
    end_early()
    if (setting("EARLY", "1") or "1").strip() == "0":
        return None
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    e.update(env or {})
    try:
        p = subprocess.Popen([julia] + flags + ["--startup-file=no", f"--project={JULIA_ENV}", os.path.join(ROOT, "times_eq", "tools", "run_case.jl"), "--wait"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=e,
                             **({"start_new_session": True} if not WIN else {}))
    except OSError:
        return None
    EARLY.append(p)
    return p


def end_early():
    """The early Julia processes that were not given a run: their input closed, they end."""
    while EARLY:
        p = EARLY.pop()
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            end_tree(p)


def is_case_folder(f):
    """A run file, a run folder (run file and DD files), or a folder that holds run folders."""
    return is_run_file(f) or os.path.isdir(f) and (bool(run_files(f)) or any(os.path.isdir(os.path.join(f, d)) and run_files(os.path.join(f, d))
                                                           for d in os.listdir(f)))


def jacobian_file(given, case, out):
    """Where --jacobian writes: no file given (True) -> <case>.gdx in the case's result folder (the case: the name of the
    run folder or run file); a folder that exists -> <folder>/<case>_jacobian.gdx; a name without a folder -> in the case's result
    folder (runs/<case>/<name>); a path -> there. .gdx is added when the name has another extension or none."""
    if given is True:
        return os.path.abspath(os.path.join(out, case + ".gdx"))
    if os.path.isdir(given):
        return os.path.abspath(os.path.join(given, case + "_jacobian.gdx"))
    f = given if os.path.dirname(given) else os.path.join(out, given)
    if os.path.splitext(f)[1].lower() != ".gdx":
        f += ".gdx"
    return os.path.abspath(f)


RESULT_MARK = ".times_result"           # in every result folder this runner makes: the only folders it deletes


def case_of(c):
    """The case name of a run folder or run file: the run file's name, or the folder's."""
    return os.path.splitext(os.path.basename(c))[0] if is_run_file(c) else os.path.basename(os.path.normpath(os.path.abspath(c)))


def within(a, b):
    """True when path a is b or inside it."""
    a, b = os.path.normcase(os.path.realpath(a)), os.path.normcase(os.path.realpath(b))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def result_folders(cases, out_root):
    """-> ([(case, its result folder)], [problems]): one result folder per case under out_root, distinct (a second case of
    the same name gets <name>_2, ...), never the run folder itself, inside it, or holding it; and a folder that exists is
    replaced only when it is a result folder of this runner."""
    names, used, problems = [], set(), []
    for c in cases:
        name, k = case_of(c), 1
        while os.path.normcase(name) in used:
            k += 1
            name = f"{case_of(c)}_{k}"
        used.add(os.path.normcase(name))
        out = os.path.join(out_root, name)
        src = os.path.dirname(os.path.abspath(c)) if is_run_file(c) else os.path.abspath(c)
        if within(out, src) or within(src, out):
            problems.append(f"{c}: its results would go to {out}, which is the run folder or overlaps it; give --out a folder "
                            "outside the model's folders")
        elif os.path.exists(out) and not os.path.isdir(out):
            problems.append(f"{c}: {out} is a file, where its result folder would go; give --out another folder, or move it")
        elif os.path.isdir(out) and os.listdir(out) and not (os.path.exists(os.path.join(out, RESULT_MARK))
                                                         or os.path.exists(os.path.join(out, f"report_{name}.txt"))):
            problems.append(f"{c}: {out} exists and is not a result folder of this runner; it is not replaced: give --out "
                            "another folder, or move it")
        names.append((name, out))
    return names, problems


GAMS_RESLIM = 1e10                      # GAMS's default ResLim (optgams.def: ResLim double 0 10000000000.00 ...)
NITER_MLF = 18                          # initmty.mlf 22: SET NITER /1*18/;
STEPS_AT_MOST = 100


def time_limit_of(given, run_text):
    """The limit of each solve, in seconds, and where it comes from. -> (seconds, 0 for none; the source)
    --time-limit; else the run file's last OPTION RESLIM=, as GAMS would apply it; else GAMS's default."""
    if given is not None:
        return given, "--time-limit" if given else "--time-limit 0: no limit"
    found = []
    for m in re.finditer(r"(?im)^(?!\*)[ \t]*OPTION\b[^;]*;", run_text):
        found += re.findall(r"(?i)\bRESLIM\s*=\s*([0-9.]+(?:[eE][+-]?\d+)?)", m.group(0))
    if found:
        return float(found[-1]), "the run file's OPTION RESLIM"
    return GAMS_RESLIM, "GAMS's default ResLim (the run file has no OPTION RESLIM)"


def solves_allowed(run_text):
    """How many solves one run may make: each may be solved again with ipx; the Negishi iterations of MLF, and the
    steps of a myopic run, are solves of their own."""
    n = 1 + NITER_MLF if (switch(run_text, "MACRO") or "") == "MLF" else 1
    return 2 * (STEPS_AT_MOST if switch(run_text, "TIMESTEP") is not None else n)


def process_limit(limit, run_text):
    """The timer on the Julia process: none without a limit; with one, the limit of every solve allowed and an hour for the rest."""
    seconds = limit * solves_allowed(run_text) + 3600
    return seconds if limit and seconds < 1e9 else None


def write_jacobian(R, pp_exe, jf, out, o):
    """--jacobian: the model's matrix (written by Julia after the solve) as a jacobian GDX; a file not written is flagged."""
    print(f"[{R['case']}] the matrix as a jacobian GDX (--jacobian) ...", flush=True)
    code, _, t = call([pp_exe, os.path.join(ROOT, "times_pp", "tools", "jacobian_gdx.py"), os.path.join(out, "matrix_here"), jf],
                      cwd=os.path.join(ROOT, "times_pp"), log=os.path.join(out, "jacobian_gdx.log"), timeout=o["pp_limit"], echo="    ")
    R["timings"]["jacobian_gdx"] = round(t, 1)
    R["jacobian"] = {"file": jf, "written": code == 0 and os.path.exists(jf), "seconds_matrix_out": (R.get("julia") or {}).get("matrix_out_seconds"),
                     "seconds_gdx": round(t, 1)}
    if not R["jacobian"]["written"]:
        R["notes"].append("the jacobian GDX (--jacobian) could not be written: see jacobian_gdx.log")
        R.setdefault("files_not_written", []).append("the jacobian GDX (jacobian_gdx.log)")


def write_db3(R, pp_exe, out, o):
    """--db3: model.db3 from the folder of tables; a file not written is flagged."""
    print(f"[{R['case']}] model.db3 from model_parquet (--db3) ...", flush=True)
    code, _, t = call([pp_exe, os.path.join(ROOT, "times_pp", "tools", "pq2db3.py"), os.path.join(out, "model_parquet")],
                      cwd=os.path.join(ROOT, "times_pp"), log=os.path.join(out, "pq2db3.log"), timeout=o["pp_limit"], echo="    ")
    R["timings"]["model_db3_from_parquet"] = round(t, 1)
    if code or not os.path.exists(os.path.join(out, "model.db3")):
        R["notes"].append("model.db3 could not be made from model_parquet (--db3): see pq2db3.log")
        R.setdefault("files_not_written", []).append("model.db3 (pq2db3.log)")


def one_case(folder, out_root, o, case=None):
    """Run one model, given as a run folder or a run file.  -> the report (dict); files in out_root/<case>."""
    t_start = time.time()
    chosen = os.path.abspath(folder) if is_run_file(folder) else None
    folder = os.path.dirname(chosen) if chosen else os.path.abspath(folder)
    case = case or case_of(chosen or folder)
    out = os.path.join(out_root, case)
    work = os.path.join(out, "work")
    if os.path.isdir(out) and (os.path.exists(os.path.join(out, RESULT_MARK)) or os.path.exists(os.path.join(out, f"report_{case}.txt"))):
        shutil.rmtree(out, ignore_errors=True)               # a result folder of an earlier run of this case (checked in result_folders)
    os.makedirs(work, exist_ok=True)
    write(os.path.join(out, RESULT_MARK), "a result folder of TIMES.py: replaced by the next run of this case\n")
    s = settings()
    src, julia, gams = find_times(), find_julia(), find_gams()
    R = {"case": case, "folder": folder, "started": datetime.datetime.now().isoformat(timespec="seconds"), "verdict": None, "checks": [],
         "environment": {"code": revision(), "port_follows_TIMES": PORT_VERSION, "os": platform.platform(), "python": platform.python_version(),
                         "times_source": src, "times_source_version": times_version(src) if src else None, "julia": julia, "gams": gams},
         "notes": [], "timings": {}}
    notes = R["notes"]

    def finish(verdict):
        R["verdict"] = verdict
        R["timings"]["total"] = round(time.time() - t_start, 1)
        write_report(out, R)
        # the tables and what GAMS wrote stay for the matrix check of --check (deleted after a passed check), or with --keep
        tidy(out, o["keep"] or (o["check"] == "after" and R.get("phase") == "timing"))
        if o["bundle"]:
            # the reports and logs of the result folder, and of the input only what TIMES reads: the run file, the DD files and
            # the solver options (the run folder can hold other files: they are not taken)
            with zipfile.ZipFile(os.path.join(out_root, case + "_bundle.zip"), "w", zipfile.ZIP_DEFLATED) as z:
                for base, _, files in os.walk(out):
                    in_work = os.path.relpath(base, out).split(os.sep)[0] == "work"
                    for f in files:
                        p, ext = os.path.join(base, f), os.path.splitext(f)[1].lower()
                        if in_work and ext not in (".run", ".dd", ".opt"):
                            continue
                        if ext not in (".db3", ".gdx", ".g00", ".parquet") and os.path.getsize(p) < 200e6:
                            z.write(p, os.path.relpath(p, out_root))
        drop_work(out, o["keep"] or (o["check"] == "after" and R.get("phase") == "timing"))
        return R

    # --- the input
    runs = run_files(folder)
    if not runs:
        return finish("ERROR: no run file (*.run) in the folder")
    run_file = chosen or runs[0]
    if len(runs) > 1 and not chosen:
        lst = sorted(glob.glob(os.path.join(folder, "*.lst")), key=os.path.getmtime)
        stem = os.path.splitext(os.path.basename(lst[-1]))[0].lower() if lst else case.lower()
        run_file = next((r for r in runs if os.path.splitext(os.path.basename(r))[0].lower() == stem), runs[0])
        notes.append(f"{len(runs)} run files in the folder; used {os.path.basename(run_file)}")
    name = os.path.splitext(os.path.basename(run_file))[0]
    run_text = read(run_file)
    dds = dd_list(run_file)
    lost = [n for n, p in dds if p is None]
    if lost:
        R["input"] = {"run_file": run_file, "missing_dd_files": lost}
        return finish("ERROR: DD files named in the run file are not in the run folder or its parent: " + ", ".join(lost))
    # TIMES-MACRO MLF: its Negishi iterations (rpt_ext.mlf) solve the LP again after each update of the weights; that loop
    # runs with HiGHS only so far, so a run with another solver would stop after the first LP: refused until it is there
    if (switch(run_text, "MACRO") or "").upper() == "MLF" and o["solve"] and o.get("lp", "highs") != "highs":
        return finish("ERROR: MACRO MLF is solved with HiGHS only so far (its Negishi iterations solve the LP again with "
                      f"the same solver); run it without {'--gurobi' if o['lp'] == 'gurobipy' else '--lp'}")
    R["input"] = {"run_file": run_file, "dd_files": [{"name": os.path.basename(p), "bytes": os.path.getsize(p), "sha256_16": sha(p),
                                                       "from_parent_folder": os.path.dirname(p) != folder} for _, p in dds],
                  "run_file_sha256_16": sha(run_file),
                  "switches": {k: switch(run_text, k) for k in ("REDUCE", "OBJ", "OBJANN", "OBLONG", "MID_YEAR", "VAR_UC", "VARCOST", "DSCAUTO", "VALIDATE",
                                                                 "STAGES", "SPINES", "SENSIS", "MACRO", "DAMAGE", "CLI", "ETL", "TIMESED", "SPOINT", "FIXBOH", "TIMESTEP", "BOTIME", "EOTIME")
                               if switch(run_text, k) is not None}}
    # the open chain reads the TIMES declarations carried with it (times_pp/timespp/times_src); the TIMES source folder
    # is needed only to run GAMS, and when there is one its declaration files should be the same ones
    if not src and gams:
        notes.append("the TIMES source folder is not known (setup --times <folder>): GAMS is not run")
        gams = None
    elif src:
        R["environment"]["declarations_as_gams"] = declarations_differ(src)
        if R["environment"]["declarations_as_gams"]:
            notes.append("the TIMES declaration files of the GAMS source differ from the copy carried with the port ("
                         + ", ".join(R["environment"]["declarations_as_gams"]) + "): the two runs did not read the same declarations")
    # a copy to work in: every input file of the folder, the DD files of the parent folder, nothing that a run writes
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        if os.path.isfile(p) and os.path.splitext(f)[1].lower() not in OUTPUT_EXT and (os.path.getsize(p) < 500e6 or f.lower().endswith(".dd")):
            shutil.copy2(p, os.path.join(work, f))
    for n, p in dds:
        if os.path.dirname(p) != folder:
            shutil.copy2(p, os.path.join(work, os.path.basename(p)))
    # The results of earlier runs (LPOINT, FIXBOH, TIMESED) are read from the run folder itself, not from this copy:
    # the preprocessor is given the folder (TIMESPP_RUN_FOLDER), and a run writes its own results there.
    # For the run of GAMS in this copy: the GDX files GAMS reads, where it looks for them in the copy
    gams_refs, gams_ref_values = gams_base_files(folder, run_text)
    for p, ref_name in gams_refs:
        shutil.copy2(p, os.path.join(work, ref_name))
    if gams_refs or gams_ref_values:
        R["input"]["earlier_results_for_gams"] = [os.path.relpath(p, folder) for p, _ in gams_refs] + list(gams_ref_values.values())
    for k, v in gams_ref_values.items():
        run_text = re.sub(rf"(?im)^(\s*\$\s*SET(?:GLOBAL|LOCAL)?\s+{k}\s+)\S+", lambda m: m.group(1) + f"'{v}'", run_text)
    wrun = os.path.join(work, os.path.basename(run_file))
    # REDUCE: the run file's, unless the setting REDUCE says otherwise (NO: the unreduced model whatever the run file says)
    reduce_user = reduce_of(run_text)
    want = (setting("REDUCE") or "").strip().strip("'\"")
    if want and want not in ("NO", "YES"):
        return finish(f"ERROR: the setting TIMES_REDUCE is {want}: NO or YES (or not set: the run file's REDUCE)")
    reduce_built = want or reduce_user
    limit, limit_from = time_limit_of(o.get("time_limit"), run_text)
    R["time_limit"] = {"seconds": limit, "from": limit_from}
    R["input"]["reduce"] = {"run_file": reduce_text(reduce_user), "built": reduce_text(reduce_built), "level": reduce_level(reduce_built),
                            "setting": want or None}
    if want and reduce_level(want) != reduce_level(reduce_user):
        said = (f"REDUCE: the run file has {reduce_text(reduce_user)}, the model is built with REDUCE {want} "
                f"(the setting TIMES_REDUCE)")
        print(f"[{case}] {said}", flush=True)
        notes.append(said)
    write(wrun, with_reduce(run_text, want) if want else run_text)

    # --- 0. the preprocessor, listing everything that is not supported
    print(f"[{case}] reading the model (Python preprocessor) ...", flush=True)
    pj = os.path.join(out, "preprocess.json")
    # The preprocessor writes model.tjb (what the equations read), then preprocess.json, then model.db3. It runs in a
    # thread: the run goes on as soon as preprocess.json is there, and model.db3 is waited for where it is needed
    # (pp_done(): the Veda result files, the end of the run).
    # model.db3 written beside the equation build with all of DuckDB's threads slows the build (19 M rows: 50-60 s ->
    # 84-86 s, the copy into HiGHS 21-30 -> 39 s). With 2 threads (the default, beside2) it no longer does, and it is
    # done about 75 s sooner than when held back until the model is in HiGHS (TIMES_DB3=after: the file `go`,
    # which Julia makes after the copy into HiGHS, when it needs model.db3, or at its end, and the runner before GAMS
    # runs and in pp_done()), so the preprocessor's memory is freed before HiGHS needs its own.
    # beside: all threads, as before; beside<n>: n threads.
    import threading
    pp_exe, heap = pp_python()
    R["environment"]["preprocessor_python"] = {"path": pp_exe, "heap": heap}
    if WIN and heap != "Segment Heap":
        print(f"[{case}] {heap}", flush=True)
        notes.append(f"the preprocessor ran on Windows's default heap, about half as fast as on the Segment Heap: {heap}")
    db3_mode = setting("DB3", "beside2")
    go = os.path.join(out, "model.db3.go")
    pp_env = {"TIMESPP_DB3_AFTER": go} if db3_mode == "after" else {"TIMESPP_DB3_THREADS": db3_mode[6:]} if db3_mode[6:].isdigit() else {}
    # The tables as a folder of Parquet files (model_parquet), each written as soon as it is final, beside the steps
    # (times_pp's stream.py): the preprocessor ends soon after its steps, before HiGHS starts. TIMES_TABLES=db3:
    # model.db3 as before. A myopic run writes its steps beside the folder (model_steps.db3); --low-memory model.db3.
    # TIMES_DROP=1: also drop each table from the preprocessor's memory once written and
    # no longer read. Off by default: which step reads a table last comes from traced models
    # (db3_drop.json), and a model with a feature none of them has stops with "Table ... does not exist"; the gain on
    # the run's peak comes from the preprocessor's earlier end, not from the drops.
    # --db3: model.db3 too, made from the folder at the end of the run (times_pp/tools/pq2db3.py, the same content).
    # A table of more than 1 M rows is written after model.tjb (its sort beside the steps would take DuckDB's threads
    # from them, and model.tjb would come later), with all of DuckDB's threads: on 19 M rows model.tjb comes 1-2 s later
    # than with model.db3 (written beside the steps, 10 s), the preprocessor ends at ~145 s, before HiGHS starts
    # (~194 s, as before); with 2 threads (beside2) it would end only then.
    # TIMES_PQ_DEFER, TIMES_PQ_THREADS set them.
    tables = setting("TABLES", "parquet")
    if tables == "parquet":
        pp_env.pop("TIMESPP_DB3_THREADS", None)
        pp_env.update({"TIMESPP_DB3_STREAM": "1", "TIMESPP_DROP": "1" if (setting("DROP") or "0").strip() == "1" else "0",
                       "TIMESPP_DB3_WRITERS": setting("PQ_WRITERS", "1"),
                       "TIMESPP_DB3_DEFER": setting("PQ_DEFER", "1000000")})
        if setting("PQ_THREADS"):
            pp_env["TIMESPP_DB3_THREADS"] = setting("PQ_THREADS")
    R["environment"]["model_db3"] = db3_mode
    R["environment"]["tables"] = tables
    R["environment"]["drops"] = pp_env.get("TIMESPP_DROP") == "1"
    pp_env["TIMESPP_RUN_FOLDER"] = folder        # the results of earlier runs: found and written in the run folder itself
    # and, when not there, where the earlier run left them: the folders of --points (TIMES_POINTS), then the result
    # folders <results>/<run> of this runner (refpoint.py)
    points = o.get("points", []) + [p for p in (setting("POINTS") or "").split(os.pathsep) if p.strip()]
    if points:
        pp_env["TIMESPP_POINTS"] = os.pathsep.join(os.path.abspath(p) for p in points)
    pp_env["TIMESPP_RESULTS"] = os.pathsep.join(dict.fromkeys([out_root, os.path.join(ROOT, "runs")]))
    # compared with a run of TIMES in GAMS: both start from the results of earlier runs that GAMS reads (refpoint.py)
    if o["gams"] in ("run", "reuse") or (o["gams"] is None and bool(gams) and (bool(o["check"]) or not o["solve"])):
        pp_env["TIMESPP_BASE_FROM_GAMS"] = "1"
    def release_db3():
        if db3_mode == "after" and not os.path.exists(go):
            open(go, "w").close()
    pp = {}
    def pp_run():
        pp["code"], _, pp["t"] = call([pp_exe, "-m", "timespp", wrun, "-", os.path.join(out, "model.db3"), "--audit", pj]
                                      + (["--low-memory"] if o["low_memory"] else []), env=pp_env,
                                      cwd=os.path.join(ROOT, "times_pp"), log=os.path.join(out, "preprocess.log"), timeout=o["pp_limit"], echo="    ")
    pp_thread = threading.Thread(target=pp_run, daemon=True)
    # stochastic TIMES: Julia loads the add-on with its equations compiled (installed and compiled here the first time,
    # before the run is timed)
    t_addon = time.time()
    stoch_env = {"TIMESEQ_STOCHASTIC": "1"} if julia and needs_stochastic(run_text) and stochastic_addon(julia, case) else {}
    R["input"]["stochastic_addon"] = bool(stoch_env)
    if time.time() - t_addon >= 1.0:
        R["timings"]["stochastic_addon"] = round(time.time() - t_addon, 1)
        notes.append(f"stochastic TIMES: its add-on was installed or compiled before this run ({time.time() - t_addon:.0f} s, once)")
    # the peak memory of phase 1 (the port: preprocessor, Julia, model.db3 beside them, the Veda files; GAMS alone),
    # the working sets of the processes this run starts, summed, every 0.5 s (TreePeak); not the matrix check
    mem = TreePeak(0.5)
    mem.window("port")
    t_pp = time.time()
    R["timings"]["before_preprocess"] = round(t_pp - t_start, 1)   # start-up of the run: settings, the copy of the input
    # Julia started now loads its packages while the preprocessor runs; it is given its run when the tables are there
    jflags_early = julia_threads("")[0] if julia else None
    j_early = julia_early(julia, jflags_early, stoch_env) if julia else None
    pp_thread.start()
    while pp_thread.is_alive() and not os.path.exists(pj):
        pp_thread.join(0.5)
    R["timings"]["preprocess"] = round(time.time() - t_pp, 1)

    def pp_done():
        """model.db3 complete (the preprocessor finished); preprocess.json then has its final content."""
        release_db3()
        if pp_thread.is_alive():
            print(f"[{case}] waiting for model.db3 ...", flush=True)
        pp_thread.join()
        R["timings"]["preprocess_with_db3"] = round(pp.get("t", time.time() - t_pp), 1)
        if os.path.exists(go):
            os.remove(go)
        if os.path.exists(pj):
            F = read_json(pj)
            for k in ("symbols_written", "seconds", "export_seconds"):
                if k in F and "preprocess" in R:
                    R["preprocess"][k] = F[k]

    P = read_json(pj) if os.path.exists(pj) else {"status": "error", "unsupported": [], "stopped_in": "start",
                                                       "error": "time limit" if pp.get("code", 0) is None else read(os.path.join(out, "preprocess.log"))[-2000:]}
    R["preprocess"] = {k: P.get(k) for k in ("status", "unsupported", "stopped_in", "error", "symbols_written", "seconds", "tjb_seconds", "duckdb_threads", "heap", "parallel_stages")}
    # the results of earlier runs the run read (TIMESED, LPOINT, FIXBOH): which file, Parquet or GDX, written by whom
    for e in P.get("earlier_results") or []:
        if os.path.normcase(e["file"]).startswith(os.path.normcase(os.path.abspath(work)) + os.sep):
            e["file"] = os.path.join(folder, os.path.relpath(e["file"], work))     # (read from its copy in work/)
        R.setdefault("earlier_results_read", []).append(e)
        notes.append(f"{e['read_for']}: read {e['file']} ({e['format']}, written by {e['written_by']})")
        e.get("warning") and notes.append("WARNING: " + e["warning"])
    # TIMES-MACRO MLF: the calibration of MACRO (the one part computed within a tolerance), how it went and with what
    if P.get("mlf_calibration"):
        R["mlf_calibration"] = C = P["mlf_calibration"]
        notes.append(f"TIMES-MACRO MLF: the calibration of MACRO with Ipopt ({C['ipopt']}): {C['nlps']} NLPs, "
                     f"{C['iterations']} iterations of the first loop and {C['negishi']} of the Negishi weights, last "
                     f"errors {C['last']}; it agrees with TIMES's within the accuracy of the solvers, not to the bit")
    R["input"]["all_switches"] = P.get("switches", {})
    R["checks"].append(["0", "all inputs supported", "yes" if P["status"] == "ok" else ("NO" if P["status"] == "unsupported" else "ERROR"),
                        "" if P["status"] == "ok" else f"{len(P['unsupported'])} unsupported" if P["status"] == "unsupported" else "the preprocessor failed", ""])

    # --- 1. GAMS and 2. Julia
    # By default the run is the timing phase: the port (preprocess, build, solve) and then GAMS (a normal run, timed to
    # its solver), each alone on the machine; GAMS's matrix and the entry-by-entry comparison come after every case of
    # the run, with --check (check_case), or later with `TIMES.py verify`. --check inline: GAMS first, its matrix,
    # then Julia compares while it builds. A published reference (expected.json) or a listing in the folder has no
    # GAMS run to time: Julia compares with it while it runs.
    inline = o["check"] == "inline"
    ref = os.path.join(folder, "expected.json")                # a published GAMS result (models/<case>): compared with, no GAMS needed
    ref_matrix = os.path.exists(ref) and os.path.exists(os.path.join(folder, "gams_matrix.db3"))   # a published reference with its matrix
    user_lst = sorted(glob.glob(os.path.join(folder, "*.lst")), key=os.path.getmtime)
    if chosen:                                                  # the other run files of the folder have their own listings
        user_lst = [f for f in user_lst if os.path.splitext(os.path.basename(f))[0].lower() == name.lower()]
    # running GAMS is opt-in (--gams run), except with --no-solve or --check, which have no purpose without it
    wants_gams = (not o["solve"] or bool(o["check"])) and bool(gams) and not ref_matrix
    mode = o["gams"] or ("run" if wants_gams else "models" if os.path.exists(ref) else "reuse" if user_lst else "skip")
    if o.get("milestones") and mode in ("models", "reuse"):
        # a published result or a listing in the folder is of the whole model, not of the reduced one
        mode = "run" if gams else "skip"
        notes.append("--milestones: the GAMS result in the folder is of the whole model; " +
                     ("GAMS is run on the reduced one instead" if gams else "nothing to compare with (GAMS not found)"))
    if (not o["solve"] or o["check"]) and mode != "run" and not (mode == "models" and ref_matrix):
        why = "GAMS was not found; give its place with: setup --gams <gams executable>" if not gams else f"--gams {mode} was given"
        print(f"[{case}] {'--no-solve' if not o['solve'] else '--check'}, but GAMS is not run here ({why}): no GAMS matrix, so the model is not compared entry by entry", flush=True)
        notes.append(f"{'--no-solve' if not o['solve'] else '--check'}, but GAMS was not run here ({why}): no GAMS matrix, so check 4 was not made")
    G = None
    if user_lst:
        u = parse_listing(user_lst[-1])
        newest_dd = max([os.path.getmtime(p) for _, p in dds] + [0])
        R["gams_existing"] = {k: u.get(k) for k in ("listing", "gams_version", "times_version", "rows", "columns", "nonzeros", "solver", "solver_status", "model_status", "objective")}
        R["gams_existing"]["REDUCE"] = reduce_text(reduce_user)
        R["gams_existing"]["dd_files_newer_than_listing"] = newest_dd > os.path.getmtime(user_lst[-1]) + 60
    R["run_options"] = {"solve": o["solve"], "tolerance": o["tolerance"], "check": o["check"], "keep": o["keep"]}
    R["phase"] = "timing" if mode == "run" and not inline else "complete"

    def gams_matrix():
        release_db3()                                       # model.db3 is written while GAMS runs, not beside the build
        was = mem.name
        mem.window("matrix")                                # the matrix check (--check inline) is not measured
        try:
            return write_gams_matrix(case, work, out, wrun, name, src, gams, o, R, notes)
        finally:
            mem.window(was)

    def gams_inline():
        """--check inline, --gams reuse or reference: G before Julia, which compares with it while it builds."""
        nonlocal mode
        G, gdx = None, None
        if P["status"] != "ok" and mode == "run":
            notes.append("GAMS was not run: the model cannot be built by the port yet, so there is nothing to compare")
            mode = "reuse" if user_lst else "skip"
        if mode == "run":
            if not gams:
                notes.append("GAMS was not found, so it was not run (python TIMES.py setup --gams <gams executable>)")
                mode = "reuse" if user_lst else "skip"
            elif not o["solve"]:                            # --no-solve: GAMS generates the model and writes its matrix; nothing is solved on either side
                code, t, got = gams_matrix()
                R["timings"]["gams"] = round(t, 1)
                lst = [f for f in glob.glob(os.path.join(work, "*.lst")) if os.path.splitext(os.path.basename(f))[0].lower() == (name + "_matrix").lower()]
                if lst:
                    shutil.copy2(lst[0], os.path.join(out, "gams_listing.lst"))
                    G = parse_listing(os.path.join(out, "gams_listing.lst"))
                else:
                    G = {"errors": ["GAMS wrote no listing"]}
                G.update(mode="run now", REDUCE=reduce_text(reduce_built), exit_status=code, seconds=round(t, 1), matrix_only=True, objective=None, solver="CONVERT", **got)
                if got.get("matrix_file"):                    # TIMES ends this call with "errors during solution": expected, CONVERT returns no solution
                    G["exit_status"] = 0
                G["errors"] = [] if got.get("matrix_file") else (G.get("errors") or []) + (["time limit reached"] if code is None else [])
            else:
                G, gdx = gams_run(solve=True)
        if mode == "reuse":
            if not user_lst:
                notes.append("no GAMS listing in the run folder to reuse")
                mode = "skip"
            else:
                G = parse_listing(user_lst[-1])
                G.update(mode="existing run of the folder", REDUCE=reduce_text(reduce_user))
                if R["gams_existing"]["dd_files_newer_than_listing"]:
                    notes.append("the DD files are newer than the GAMS listing: the listing may not be the run of these DD files")
                for c in (os.path.join(folder, "GAMSSAVE", name + ".gdx"), os.path.join(folder, name + ".gdx")):
                    if os.path.exists(c):
                        gdx = c
                        break
        if mode == "models":
            if not os.path.exists(ref):
                notes.append("no expected.json in the run folder (--gams reference)")
                mode = "skip"
            else:
                X = json.loads(read(ref))
                g = X.get("gams") or {}
                G = {"mode": "published reference (expected.json)", "REDUCE": g.get("REDUCE"), "gams_version": g.get("gams_version"),
                     "times_version": g.get("times_version"), "solver": g.get("solver"), "solver_status": g.get("solver_status"), "model_status": g.get("model_status"),
                     "rows": g.get("rows"), "columns": g.get("columns"), "nonzeros": g.get("nonzeros"), "objective": g.get("objective", X.get("objective"))}
                for f, key in (("gams_solution.db3", "solution_file"), ("gams_matrix.db3", "matrix_file")):
                    if os.path.exists(os.path.join(folder, f)):
                        shutil.copyfile(os.path.join(folder, f), os.path.join(out, f))
                        G[key] = True
                if not G.get("solution_file"):
                    notes.append("the reference has no gams_solution.db3: sizes and the objective are compared, not the solution")
        if G:
            gams_solution_file(G, gdx, gams, out, notes, same_reduce(R, G))
            R["gams"] = G
            if inline and G.get("mode") == "run now" and G.get("objective") is not None:
                G.update(gams_matrix()[2])
            if G.get("times_version") and G["times_version"] != PORT_VERSION:
                notes.append(f"GAMS ran TIMES v{G['times_version']}; the port follows v{PORT_VERSION}")
        return G

    def gams_run(solve):
        """GAMS on the work copy, timed to its solver ("Executing <solver>: elapsed" in its log): a normal run
        with solve, else stopped there (the time to the solver and the size of the model; nothing solved).
        -> (G, the solution GDX or None)"""
        release_db3()
        print(f"[{case}] running TIMES in GAMS ..." if solve else
              f"[{case}] running TIMES in GAMS, stopped at its solver (the port did not solve) ...", flush=True)
        gdx = os.path.join(work, "gams_solution.gdx")
        stopped = []
        was = mem.name
        mem.window("gams")
        code, _, t = call([gams, os.path.basename(wrun), "IDIR=" + plain_path(src), "PS=99999", "LO=2", "LF=gams_log.txt"]
                          + (["GDX=gams_solution.gdx"] if solve else []),
                          cwd=work, log=os.path.join(out, "gams_console.txt"), timeout=o["gams_limit"],
                          echo="    ", follow=os.path.join(work, "gams_log.txt"),
                          stop_on=None if solve else (GAMS_AT_SOLVER, stopped))
        mem.window(was)
        if os.path.exists(os.path.join(work, "gams_log.txt")):
            shutil.copy2(os.path.join(work, "gams_log.txt"), os.path.join(out, "gams_log.txt"))
        lst = [f for f in glob.glob(os.path.join(work, "*.lst")) if os.path.splitext(os.path.basename(f))[0].lower() == name.lower()]
        G = {"errors": []}
        if lst:
            shutil.copy2(lst[0], os.path.join(out, "gams_listing.lst"))
            try:
                G = parse_listing(os.path.join(out, "gams_listing.lst"))
            except Exception as x:                          # a listing cut short when GAMS was stopped
                G = {"errors": [f"the listing could not be read ({type(x).__name__})"]}
        elif solve:
            G["errors"] = ["GAMS wrote no listing"]
        F = gams_log_facts(os.path.join(work, "gams_log.txt"))
        for k in ("rows", "columns", "nonzeros"):
            if G.get(k) is None and F.get(k) is not None:
                G[k] = F[k]
        G.update(mode="run now", REDUCE=reduce_text(reduce_built), exit_status=code, seconds=round(t, 1), seconds_to_solver=F.get("seconds_to_solver"),
                 solver=G.get("solver") or F.get("solver"),
                 phases=gams_phases(os.path.join(work, "gams_log.txt"), os.path.join(out, "gams_listing.lst") if lst else None))
        R["timings"]["gams"] = round(t, 1)
        if F.get("seconds_to_solver") is not None:
            R["timings"]["gams_to_solver"] = F["seconds_to_solver"]
        if not solve:
            G.update(stopped_at_solver=bool(stopped), objective=None, exit_status=0 if stopped else code)
            if not stopped:
                G["errors"] = (G.get("errors") or []) + ["GAMS ended before its solver" + (" (time limit reached)" if code is None else "")]
            return G, None
        if G.get("objective") is None:                    # why: the last lines of the GAMS log that carry a message
            tail = read(os.path.join(out, "gams_log.txt")) if os.path.exists(os.path.join(out, "gams_log.txt")) else read(os.path.join(out, "gams_console.txt"))
            G.setdefault("errors", []).extend(x.strip()[:200] for x in [y for y in tail.splitlines() if y.startswith("***") or "rror" in y][-6:])
        if code is None:
            G.setdefault("errors", []).insert(0, "time limit reached")
        return G, (gdx if os.path.exists(gdx) else None)

    def gams_convert_run():
        """--check: GAMS's one run, the model generated and its matrix written by CONVERT (nothing solved), timed and
        measured as GAMS's run; the GAMS matrix read for phase 2. -> G"""
        release_db3()
        was = mem.name
        mem.window("gams")
        try:
            code, t, got = write_gams_matrix(case, work, out, wrun, name, src, gams, o, R, notes)
        finally:
            mem.window(was)
        log = os.path.join(work, "gams_matrix_log.txt")
        if os.path.exists(log):
            shutil.copy2(log, os.path.join(out, "gams_log.txt"))
        lst = [f for f in glob.glob(os.path.join(work, "*.lst")) if os.path.splitext(os.path.basename(f))[0].lower() == (name + "_matrix").lower()]
        G = {"errors": []}
        if lst:
            shutil.copy2(lst[0], os.path.join(out, "gams_listing.lst"))
            try:
                G = parse_listing(os.path.join(out, "gams_listing.lst"))
            except Exception as x:
                G = {"errors": [f"the listing could not be read ({type(x).__name__})"]}
        F = gams_log_facts(log)
        for k in ("rows", "columns", "nonzeros"):
            if G.get(k) is None and F.get(k) is not None:
                G[k] = F[k]
        G.update(mode="run now", REDUCE=reduce_text(reduce_built), exit_status=0 if (got.get("matrix_pq") or got.get("matrix_file")) else code,
                 seconds=round(t, 1), seconds_to_solver=F.get("seconds_to_solver"), matrix_only=True, objective=None, solver="CONVERT",
                 phases=gams_phases(log, os.path.join(out, "gams_listing.lst") if lst else None), **got)
        G["errors"] = [] if (got.get("matrix_pq") or got.get("matrix_file")) else (G.get("errors") or []) + (["time limit reached"] if code is None else [])
        R["timings"]["gams"] = round(t, 1)
        if F.get("seconds_to_solver") is not None:
            R["timings"]["gams_to_solver"] = F["seconds_to_solver"]
        return G

    if mode != "run" or inline:
        G = gams_inline()

    J = None
    if P["status"] == "ok":
        if not julia:
            notes.append("Julia was not found (python TIMES.py setup)")
        else:
            print(f"[{case}] " + (f"building the model in Julia and solving it with {o['lp'].upper()} {'through Python (gurobipy)' if o['lp'] == 'gurobipy' else 'through GAMS'} ..." if o["solve"] and o["lp"] != "highs"
                                   else "building and solving the model in Julia (HiGHS) ..." if o["solve"]
                                   else "building the model in Julia (--no-solve: HiGHS is not run) ..."), flush=True)
            jj = os.path.join(out, "julia.json")
            jflags, jenv, used, jnote = julia_threads(os.path.join(out, "model.tjb"))
            R["environment"]["julia_settings"] = used
            print(f"[{case}] Julia: threads {used['threads']}, garbage collector threads {used['gc_threads']}, "
                  f"at most {used['families_at_once']} equation families at once" + (f"  ({jnote})" if jnote else ""), flush=True)
            jnote and notes.append(jnote)
            jenv.update(stoch_env)
            if db3_mode == "after":
                jenv["TIMESEQ_DB3_GO"] = go
            cmd = [julia] + jflags + ["--startup-file=no", f"--project={JULIA_ENV}", os.path.join(ROOT, "times_eq", "tools", "run_case.jl"), os.path.join(out, "model.db3"), jj,
                   "--solver", o["solver"], "--time-limit", str(limit)]
            if o["threads"]:
                cmd += ["--threads", str(o["threads"])]
            if o["lp"] != "highs":
                # an LP solver of the user's GAMS: the run folder's <solver>.opt as it is (Veda writes cplex.opt beside the run file)
                optf = os.path.join(os.path.dirname(run_file), ("gurobi" if o["lp"] == "gurobipy" else o["lp"]) + ".opt")
                cmd += ["--lp", o["lp"], "--gams-exe", o["gams_exe"], "--python", sys.executable,
                        "--lp-work", os.path.join(out, "gamslp"), "--lp-log", os.path.join(out, "gamslp.log")]
                cmd += ["--lp-optfile", optf] if os.path.isfile(optf) else []
                for kv in o["solver_options"]:
                    cmd += ["--solver-option", kv]
                cmd += ["--keep"] if o["keep"] else []
                cmd += ["--lp-names"] if o["lp_names"] else []
            for kv in o["highs_options"]:
                cmd += ["--highs-option", kv]
            if G and G.get("solution_file"):
                cmd += ["--gams", os.path.join(out, "gams_solution.db3")]
            if G and G.get("matrix_file"):
                cmd += ["--matrix", os.path.join(out, "gams_matrix.db3")]
            if not o["solve"]:
                cmd += ["--no-solve"]
            elif o["force_solve"]:
                cmd += ["--solve"]
            cmd += ["--max-solve-rows", str(o["max_solve_rows"])]
            if o["profile"]:
                cmd += ["--profile", o["profile"], "--profile-out", os.path.join(out, "julia_profile.txt")]
            cmd += ["--highs-log", os.path.join(out, "highs.log")]
            cmd += ["--solution", os.path.join(out, "solution.db3")]
            if (o["check"] and check_parquet()) or o.get("jacobian"):   # the run's matrix, for the check without a second
                cmd += ["--matrix-out", os.path.join(out, "matrix_here")]  # the model's matrix, as write_matrix writes it
            # the Julia started early, given its settings and arguments (the same as on a command line), if they can be
            # sent as tab-separated lines and its flags are these
            script = cmd.index(os.path.join(ROOT, "times_eq", "tools", "run_case.jl"))
            early = None
            if j_early in EARLY and j_early.poll() is None and jflags == jflags_early and not any(
                    c in a for a in cmd[script + 1:] + [f"{k}={v}" for k, v in jenv.items()] for c in "\t\n"):
                EARLY.remove(j_early)
                early = (j_early, "\t".join(f"{k}={v}" for k, v in jenv.items()) + "\n" + "\t".join(cmd[script + 1:]) + "\n")
            end_early()
            R["timings"]["julia_started"] = round(time.time() - t_start, 1)
            code, _, t = call(cmd, log=os.path.join(out, "julia.log"), timeout=process_limit(limit, run_text), env=jenv, echo="    ", follow=os.path.join(out, "highs.log"),
                              started=early)
            R["timings"]["julia"] = round(t, 1)
            code is None and notes.append(f"the Julia process and those it started were ended after {t:.0f} s (time limit of each solve {limit:g} s)")
            J = json.loads(read(jj)) if os.path.exists(jj) else {"stage": "start", "error": "Julia did not start or was stopped; see julia.log"}
            if "equation infeasible due to rhs value" in (J.get("error") or ""):   # the rows, all of them: julia.log lists them
                J["infeasible_rows"] = [l.strip() for l in read(os.path.join(out, "julia.log")).splitlines()
                                        if l.startswith("  infeasible: ")]
            R["julia"] = J
            if o["lp_names"]:                                 # where the listing by names is, or why there is none
                notes.append(J.get("lp_names") or ("--lp-names ignored: it applies to --lp with a solver of your GAMS" if o["lp"] == "highs"
                                                   else "--lp-names: the model was not solved through GAMS"))
            cw = compile_warning(J)
            if cw:
                print(f"[{case}] WARNING: {cw}", flush=True)
                notes.append("WARNING: " + cw)
            R["highs"] = highs_log_profile(os.path.join(out, "highs.log"))
            if J.get("solve_started_unix"):                   # start of the run to HiGHS's start (the time compared with GAMS's "to solver")
                R["timings"]["to_highs"] = round(J["solve_started_unix"] - t_start, 1)
                if (J.get("gamslp") or {}).get("gams_to_solver_seconds") is not None:   # --lp: to the solver's start in GAMS
                    H = lp_hand_over(J["gamslp"])
                    R["timings"]["to_highs"] = round(J["solve_started_unix"] - t_start + H["copy"] + H["gdx"] + H["to_solver"], 1)
            elif os.path.exists(os.path.join(out, "highs.log")):    # a Julia before solve_started_unix: the creation of HiGHS's log
                st = os.stat(os.path.join(out, "highs.log"))
                born = st.st_ctime if WIN else getattr(st, "st_birthtime", None)
                if born:
                    R["timings"]["to_highs"] = round(born - t_start, 1)

    end_early()                                       # (a Julia started early and not given a run)
    # --- the Veda result files of the Julia solution: <run>_julia.vd, .vde, .vds (times_rpt), unless --no-report
    pp_done()
    sol = os.path.join(out, "solution.db3")
    # (a SENSIS run: the solution of each solve in solution~<w>.db3, which the report reads SOW by SOW)
    sensis_sols = J and J.get("steps") and J["steps"][0].get("sow") and all(s.get("solution_file") for s in J["steps"])
    # a run with FIXBOH: the levels and marginals of the loaded point that the model of the run does not have (the
    # equations of the fixed periods, the variables in none of its rows) stay as loaded in TIMES, and its reports and
    # its solution point have them. Here they are put under the solution before both are written (loadedpoint.py)
    fixed = [e for e in R.get("earlier_results_read") or [] if str(e.get("read_for", "")).startswith("FIXBOH")]
    if fixed and J and J.get("objective") is not None and os.path.exists(sol):
        code, _, t = call([pp_exe, os.path.join(ROOT, "times_rpt", "timesrpt", "loadedpoint.py"), sol, fixed[-1]["file"], model_tables(out)],
                          cwd=ROOT, log=os.path.join(out, "loadedpoint.log"), timeout=o["pp_limit"], echo="    ")
        R["timings"]["loaded_point"] = round(t, 1)
        code and notes.append("the loaded point was not put under the solution (loadedpoint.log): the Veda result files "
                              "and the solution point written for later runs lack most of the fixed periods")
    if o["report"] and J and J.get("objective") is not None and (os.path.exists(sol) or sensis_sols):
        scen =os.path.splitext(os.path.basename(run_file))[0] + "_julia"
        print(f"[{case}] writing the Veda result files ({scen}.vd, .vde, .vds) ...", flush=True)
        code, _, t = call([pp_exe, os.path.join(ROOT, "times_rpt", "timesrpt", "write.py"), model_tables(out), sol,
                           out, scen, "-", pj], cwd=ROOT, log=os.path.join(out, "report.log"), timeout=o["pp_limit"], echo="    ")
        R["timings"]["report"] = round(t, 1)
        rj = os.path.join(out, scen + "_report.json")
        if code == 0 and os.path.exists(rj):
            R["veda_report"] = json.loads(read(rj))
        else:
            R["veda_report"] = {"error": read(os.path.join(out, "report.log"))[-2000:]}
            notes.append("the Veda result files were not written: see report.log")
            R.setdefault("files_not_written", []).append("the Veda result files (report.log)")

    # --- the results later runs read (maindrv.mod 121-123), in the run folder's GAMSSAVE (or the run folder), as TIMES
    #     writes them: the solution point <run>_p after every solve (TIMES: with SPOINT; a run of TIMES in GAMS writes
    #     the whole run with GDX= on its command line), the base prices with TIMESED NO (<run>_DP, com_bprice)
    if J and J.get("objective") is not None and os.path.exists(sol):
        rn = run_name(run_text) or os.path.splitext(os.path.basename(run_file))[0]
        print(f"[{case}] writing the results later runs read ({rn}_p, {rn}_DP) ...", flush=True)
        code, _, t = call([pp_exe, os.path.join(ROOT, "times_rpt", "timesrpt", "results.py"), model_tables(out), sol, out, folder, rn, pj],
                          cwd=ROOT, log=os.path.join(out, "results.log"), timeout=o["pp_limit"], echo="    ")
        R["timings"]["results_for_later_runs"] = round(t, 1)
        rw = os.path.join(out, "results_written.json")
        R["results_for_later_runs"] = json.loads(read(rw))["written"] if code == 0 and os.path.exists(rw) else None
        code and notes.append("the results later runs read (LPOINT, FIXBOH, TIMESED) were not written: see results.log")
        code and R.setdefault("files_not_written", []).append("the results later runs read (results.log)")

    if o.get("jacobian") and os.path.isdir(os.path.join(out, "matrix_here")):
        # --jacobian: the model's matrix (written by Julia after the solve) as a jacobian GDX
        write_jacobian(R, pp_exe, jacobian_file(o["jacobian"], case, out), out, o)
        if not (o["check"] and check_parquet()):
            shutil.rmtree(os.path.join(out, "matrix_here"), ignore_errors=True)
    mem.window(None)                                        # the port is done: model.db3 written, the Veda files
    if o.get("db3") and not os.path.exists(os.path.join(out, "model.db3")) and os.path.isdir(os.path.join(out, "model_parquet")):
        write_db3(R, pp_exe, out, o)

    JU = (J or {}).get("unsupported") or []
    if JU and P["status"] == "ok":                           # the preprocessor takes the input, the equations for it are not written
        R["equations_unsupported"] = JU
        R["checks"][0] = ["0", "all inputs supported", "NO", f"{len(JU)} unsupported (equations)", ""]
    if J and J.get("first_attempt"):
        notes.append(J["first_attempt"])
    if J and J.get("negishi_converged") is False:
        N = J["negishi_last"]
        notes.append(f"WARNING: the Negishi weights did not converge: after {N['iterations']} iterations the last gap is {N['gap']:g}, "
                     f"tolerance {N['tolerance']:g} (NITER, the limit of the iterations, was reached; TIMES stops there too)")

    # --- GAMS after the port (the timing phase), once the port is done (model.db3, the Veda files): alone on the machine,
    # as the port was. It solves when the port solved; when the port did not (--no-solve, a model above --max-solve-rows) it is stopped at its solver.
    if mode == "run" and not inline:
        if P["status"] != "ok":
            notes.append("GAMS was not run: the model cannot be built by the port yet, so there is nothing to compare")
            R["phase"] = "complete"
        else:
            solved = bool(J and "termination" in J)
            if o["check"] and not (J and J.get("steps")):
                # --check: one GAMS run, with CONVERT. It generates the model as a solve would and writes its matrix
                # instead of solving: its log gives the time to the solver and its listing the phases (GENERATION TIME),
                # so the same run is the timing and the matrix of the check (phase 2 only compares). No GAMS objective.
                G, gdx = gams_convert_run(), None
            else:
                G, gdx = gams_run(solve=solved)
            R["gams"] = G
            if not solved and o["solve"] and J and J.get("solve_skipped"):
                notes.append("the port did not solve the model (above --max-solve-rows), so GAMS was stopped at its solver too")
            if G.get("times_version") and G["times_version"] != PORT_VERSION:
                notes.append(f"GAMS ran TIMES v{G['times_version']}; the port follows v{PORT_VERSION}")
            if gdx:
                R["gams"]["solution_gdx"] = os.path.relpath(gdx, out)

    peaks = mem.close()
    R["memory"] = {"port_gb": peaks.get("port"), "gams_gb": peaks.get("gams"), "interval_s": 0.5, "port_gams_gb": peaks.get("port_gams"),
                   "gams_stopped_at_solver": bool((R.get("gams") or {}).get("stopped_at_solver"))} if mem.ok else None

    # --- the verdict (judge: also made again after the matrix check)
    return finish(judge(R, R["run_options"]))


def infeasible_verdict(found, G, notes):
    """INFEASIBLE: Julia stopped on rows left with no column whose constant the model's data do not satisfy
    (`0 =E= 2.685`), as GAMS stops on them ("equation infeasible due to rhs value"). Not a defect of this
    implementation: the data make the model infeasible. found: julia.log's lines of those rows ("infeasible: <row>..
    0 =E= 2.685"); G: a GAMS run of the case, whose rows are compared with these; notes: the report's notes, to which
    the first rows are added."""
    lines = [l.split("infeasible: ", 1)[-1] for l in found]
    rows = [l.split("..")[0] for l in lines]
    notes.append(f"{len(rows)} row{'s' if len(rows) != 1 else ''} with no column and a constant that does not satisfy it"
                 + (f"; the first: {'; '.join(lines[:5])}" if lines else "") + " (julia.log lists them all)")
    v = (f"INFEASIBLE: the model's data cannot be met: {len(rows)} row{'s' if len(rows) != 1 else ''} with no column"
         f" whose constant does not satisfy it ({rows[0] if rows else '?'}{', ...' if len(rows) > 1 else ''})")
    if G and G.get("infeasible_rows") is not None:
        key = lambda r: r.replace("'", "").replace('"', "").lower()
        mine, gams = {key(r) for r in rows}, {key(r) for r in G["infeasible_rows"]}
        if mine == gams:
            v += f"; GAMS stops on the same {len(gams)} rows"
        elif gams:
            v = (f"DIFFERENT: rows with no column whose constant does not satisfy it: {len(mine)} here, {len(gams)} in GAMS,"
                 f" {len(mine & gams)} in both")
        else:
            v = f"DIFFERENT: {len(rows)} rows with no column whose constant does not satisfy it here, none in GAMS"
    return v


def judge(R, o):
    """The checks and the verdict from what the run recorded (R: preprocess, gams, julia; o: tolerance, solve). Made at
    the end of the run, and again after the matrix check (check_case), which adds its comparisons to R['julia'].
    While the matrix is not checked yet (R['phase'] 'timing'), the verdict is provisional: SAME OBJECTIVE, BUILT or
    DIFFERENT OBJECTIVE."""
    P, G, J = R.get("preprocess") or {}, R.get("gams"), R.get("julia")
    notes = R["judge_notes"] = []
    timing = R.get("phase") == "timing"
    R["checks"] = [["0", "all inputs supported", "yes" if P.get("status") == "ok" else ("NO" if P.get("status") == "unsupported" else "ERROR"),
                    "" if P.get("status") == "ok" else f"{len(P.get('unsupported') or [])} unsupported" if P.get("status") == "unsupported" else "the preprocessor failed", ""]]
    JU = R.get("equations_unsupported") or []
    if JU and P.get("status") == "ok":
        R["checks"][0] = ["0", "all inputs supported", "NO", f"{len(JU)} unsupported (equations)", ""]
    tol = o.get("tolerance", 1e-6)
    C = (J or {}).get("compare")
    diffs = []
    if J and J.get("rows") is not None and G and G.get("rows") is not None:
        if same_reduce(R, G):
            for key, label in (("rows", "rows"), ("columns", "columns"), ("nonzeros", "non-zeros")):
                same = J[key] == G[key]
                R["checks"].append(["1", label, "same" if same else "DIFFERENT", num(J[key]), num(G[key])])
                same or diffs.append(label)
        else:
            for key, label in (("rows", "rows"), ("columns", "columns"), ("nonzeros", "non-zeros")):
                R["checks"].append(["1", label, "not comparable", num(J[key]), num(G[key]) + f" (REDUCE {G.get('REDUCE')})"])
    if C:
        R["checks"].append(["1", "rows of every equation, key by key", "same" if C["same_rows"] else "DIFFERENT",
                            f"{C['row_families']} equations", f"{C['row_families_differ']} differ: {C['rows_missing']} rows missing, {C['rows_extra']} extra" if not C["same_rows"] else ""])
        C["same_rows"] or diffs.append("rows of some equations")
    gobj = None
    if G and G.get("objective") is not None:
        gobj = C["gams_objective"] if C and C.get("gams_objective") is not None else G["objective"]
    if J and J.get("objective") is not None:
        if gobj is not None:
            rel = abs(J["objective"] - gobj) / max(1.0, abs(gobj))
            R["objective_relative_difference"] = rel
            same = rel <= tol
            R["checks"].append(["2", "objective", "same" if same else "DIFFERENT", f"{J['objective']:.6f}", f"{gobj:.6f}   relative difference {rel:.1e}"])
            same or diffs.append("objective")
        else:
            R["checks"].append(["2", "objective", "nothing to compare", f"{J['objective']:.6f}", gams_summary(G)])
    if C:
        R["checks"].append(["3", "GAMS solution in the Julia rows", "same" if C["same_solution"] else "DIFFERENT", "",
                            f"largest relative difference {C['activity_worst']:.1e}; {C['activity_rows_off']} rows above {C['tolerance_rows']:.0e}"])
        C["same_solution"] or diffs.append("row activities at the GAMS solution")
        if C["gams_has_duals"]:
            R["checks"].append(["3", "reduced costs from the GAMS marginals", "same" if C["same_duals"] else "DIFFERENT", "",
                                f"largest relative difference {C['reduced_cost_worst']:.1e}; {C['reduced_cost_columns_off']} columns above {C['tolerance_reduced_cost']:.0e}"])
        if "same_rhs" in C:
            ok = C["same_rhs"] and C["same_bounds"]
            R["checks"].append(["3", "right-hand sides and bounds", "same" if ok else "DIFFERENT", "",
                                "" if ok else f"{C['rhs_rows_off']} rows, {C['bounds_columns_off']} columns"])
            C["same_rhs"] or diffs.append("right-hand sides")
            C["same_bounds"] or diffs.append("column bounds")
        if C["gams_interior"]:
            notes.append(f"the GAMS solution is not a vertex ({C['gams_columns_off_vertex']:,} columns are off their bounds and have a reduced cost): it comes from an interior point "
                         f"method without crossover, and satisfies its own rows only to that method's tolerance. Check 3 therefore uses {C['tolerance_rows']:.0e} for the rows and "
                         f"{C['tolerance_reduced_cost']:.0e} for the reduced costs, not {C['tolerance']:.0e}. For the strict check, run GAMS with crossover (a simplex method, or the "
                         "barrier with crossover in the solver option file)")
            C["same_duals"] or diffs.append("reduced costs")
    ST = (J or {}).get("steps")
    several = bool(ST) and len(ST) > 1 and not ST[0].get("sow")    # a myopic run of several steps: no one matrix to compare afterwards
    read = R.get("earlier_results_read") or []                     # the results of earlier runs this run read (FIXBOH, LPOINT, TIMESED)
    fixboh = any(str(e.get("read_for", "")).startswith("FIXBOH") for e in read)
    # results written by this implementation, while the GAMS run compared with (one already in the folder) read GAMS's
    own_start = [e for e in read if str(e.get("written_by", "")).startswith("this implementation")] if G and G.get("mode") == "existing run of the folder" else []
    if ST:                                                   # a myopic run (TIMESTEP): one model per step
        sizes, objs = (G or {}).get("step_sizes") or [], (G or {}).get("step_objectives") or []
        for i, st in enumerate(ST):
            w = (st.get("window") or str(st["year"])).split()
            win = f"step {st['step']} ({w[0]}{'-' + w[-1] if len(w) > 1 else ''})"
            if i < len(sizes):
                g3 = tuple(sizes[i])
                same = (st["rows"], st["columns"], st["nonzeros"]) == g3
                R["checks"].append(["1", f"{win}: size", "same" if same else "DIFFERENT",
                                    f"{st['rows']:,} {st['columns']:,} {st['nonzeros']:,}", f"{g3[0]:,} {g3[1]:,} {g3[2]:,}"])
                same or diffs.append(f"size of step {st['step']}")
            if i < len(objs) and st.get("objective") is not None:
                rel = abs(st["objective"] - objs[i]) / max(1.0, abs(objs[i]))
                same = rel <= tol
                R["checks"].append(["2", f"{win}: objective", "same" if same else "DIFFERENT", f"{st['objective']:.6f}", f"{objs[i]:.6f}   relative difference {rel:.1e}"])
                same or diffs.append(f"objective of step {st['step']}")
        imp = [str(st["step"]) for st in ST if st.get("status") != "OPTIMAL" and st.get("objective") is not None]
        if imp:
            notes.append(f"HiGHS ended step{'s' if len(imp) > 1 else ''} {', '.join(imp)} with {ST[int(imp[0]) - 1]['status']} (an interior point solve without crossover "
                         "that it calls imprecise) and a feasible point, not a proved optimum; the run took that point as the solution of the step and fixed the steps "
                         "after it there. Its objective cannot be lower than the optimum of the step")
        if G and G.get("objective") is not None and len(sizes) != len(ST):
            notes.append(f"the GAMS listing has {len(sizes)} solves, Julia made {len(ST)} steps")
            diffs.append("number of steps")
        CS = J.get("compare_steps")
        if CS:
            # a run with FIXBOH: GAMS's file also holds the rows of the fixed periods, loaded with the solution point and
            # not generated; with the model's row count that of GAMS and no row here that GAMS lacks, the rows are the same
            loaded = (fixboh and not CS["same_rows"] and not CS["rows_extra"] and G and G.get("rows") is not None
                      and J.get("rows") == G.get("rows"))
            rows_same = CS["same_rows"] or loaded
            R["checks"].append(["1", "rows of every equation over all steps", "same" if rows_same else "DIFFERENT", f"{CS['row_families']} equations",
                                (f"and {CS['rows_missing']:,} rows of the fixed periods in the GAMS file, from the loaded point" if loaded else "") if rows_same
                                else f"{CS['row_families_differ']} differ: {CS['rows_missing']} rows missing, {CS['rows_extra']} extra"])
            rows_same or diffs.append("rows of the steps")
            other = not any(x.startswith("objective of step") for x in diffs)
            R["checks"].append(["3", "levels of the merged solution", "same" if CS["same_levels"] else ("other optimum" if other else "DIFFERENT"),
                                f"{CS['columns_compared']:,} columns",
                                f"largest relative difference {CS['level_worst']:.1e}" + ("" if CS["same_levels"] else f"; {CS['levels_off']} columns above {CS['tolerance']:.0e}")])
            if not CS["same_levels"] and other:
                who = (J.get("solver") or "HiGHS").split()[0] if (J or {}).get("gamslp") else "HiGHS"
                notes.append("the levels of the merged solution differ from those of GAMS while every step has the GAMS objective: a step with several optimal "
                             f"solutions, where {who} and the GAMS solver chose different ones; the steps after it are then fixed at another point")
    M = (J or {}).get("matrix")
    if M:
        ent = M["entries_only_here"] + M["entries_only_gams"] + M["entries_different"]
        unm = M["rows_only_here"] + M["rows_only_gams"] + M["columns_only_here"] + M["columns_only_gams"]
        how = "; compared as Parquet in DuckDB" if (G or {}).get("matrix_pq") else ("; compared by a second Julia build" if (G or {}).get("matrix_file") else "")
        R["checks"].append(["4", "matrix: every coefficient", "same" if not ent else "DIFFERENT", f"{M['entries_here']:,}", f"{M['entries_gams']:,}   " + (
            (f"largest relative difference {M['largest_relative_difference_equal']:.1e} (tolerance {M['tolerance']:.0e})" if "largest_relative_difference_equal" in M else "")
            if not ent else f"only here {M['entries_only_here']:,}, only in GAMS {M['entries_only_gams']:,}, other value {M['entries_different']:,}") + how])
        R["checks"].append(["4", "matrix: rows and columns by name", "same" if not unm else "DIFFERENT", "",
                            "" if not unm else f"rows {M['rows_only_here']:,} only here, {M['rows_only_gams']:,} only in GAMS; columns {M['columns_only_here']:,} / {M['columns_only_gams']:,}"])
        R["checks"].append(["4", "matrix: right-hand sides and senses", "same" if not M["rhs_different"] else "DIFFERENT", f"{M['rows_gams']:,} rows",
                            (f"{M['rhs_different']:,} differ" if M["rhs_different"] else "") +
                            (f"{'; ' if M['rhs_different'] else ''}{M['rhs_rounding']:,} equal within rounding of constants that cancel (decision 0007)"
                             if M.get("rhs_rounding") else "")])
        R["checks"].append(["4", "matrix: column bounds", "same" if not M["bounds_different"] else "DIFFERENT", f"{M['columns_gams']:,} columns",
                            "" if not M["bounds_different"] else f"{M['bounds_different']:,} differ"])
        M["same_model"] or diffs.append("matrix")
    elif timing:
        R["checks"].append(["4", "matrix, entry by entry", "not yet", "", "a myopic run: compared step by step while it runs, with --check inline" if several else
                            "after the timing: --check, or python TIMES.py verify <result folder>"])
    else:
        R["checks"].append(["4", "matrix, entry by entry", "not made", "", "needs the GAMS matrix (--gams run, or gams_matrix.db3 in a reference folder)" if not (G and G.get("matrix_file")) else ""])
    pending = "; the matrix is not checked yet (" + ("a myopic run: --check inline" if several else "--check, or python TIMES.py verify") + ")"

    if P.get("status") == "unsupported":
        n = len(P["unsupported"])
        return f"UNSUPPORTED: the model uses {n} thing{'s' if n != 1 else ''} this implementation does not have yet" + ("" if not G else f" (GAMS: {gams_summary(G)})")
    if P.get("status") != "ok":
        return f"ERROR: the preprocessor failed in '{P.get('stopped_in')}'"
    if not J:
        return "ERROR: Julia is not set up (python TIMES.py setup)"
    if J.get("stage") != "done":
        err = J.get("error") or ""
        if JU:
            return (f"UNSUPPORTED: the model uses {len(JU)} thing{'s' if len(JU) != 1 else ''} the equations do not have yet"
                    + ("" if not G else f" (GAMS: {gams_summary(G)})"))
        if "not supported yet" in err:                       # found while the equations were written: one at a time
            R["checks"][0] = ["0", "all inputs supported", "NO", "unsupported (equations)", ""]
            return "UNSUPPORTED: " + err.replace("TIMES feature not supported yet: ", "the equations do not have yet: ")[:400]
        if J.get("infeasible_rows"):
            return infeasible_verdict(J["infeasible_rows"], G, notes)
        return f"ERROR: Julia stopped in stage '{J.get('stage')}': {err[:300]}"
    if J.get("solve_skipped"):
        notes.append("not solved: " + J["solve_skipped"])
    if M and M["same_model"]:                                # the same linear program: what a solver makes of it is secondary
        if "termination" not in J:
            tail = "; not solved here (" + ("too large for HiGHS" if J.get("solve_skipped") else "--no-solve") + ")"
        elif J.get("objective") is None:
            tail = f"; {solver_name(J)} did not solve it ({J.get('termination')}), which says nothing about the model"
        elif "objective" in diffs:
            tail = f"; {solver_name(J)} ends at another objective (relative difference {R.get('objective_relative_difference', 0):.1e}): a matter of the solver"
        elif gobj is None:
            tail = f"; {solver_name(J)} objective {J['objective']:.6f}" + ("" if J.get("termination") == "OPTIMAL" else f" (feasible point, status {J.get('termination')})") + " (GAMS did not solve: --check)"
        else:
            tail = f"; {solver_name(J)} finds the GAMS objective" + ("" if J.get("termination") == "OPTIMAL" else f" (feasible point, status {J.get('termination')})")
        other = [x for x in diffs if x != "objective"]
        if not other:
            return "SAME: the same linear program as GAMS, every coefficient, right-hand side and bound" + tail
    unproved = J.get("termination") != "OPTIMAL" and J.get("objective") is not None and gobj is not None and "objective" not in diffs
    if unproved:
        notes.append(f"HiGHS ended with {J.get('termination')} (an interior point solve that it calls imprecise) and gave a feasible point, not a proved optimum. "
                     "The objective of that point is the one of GAMS within the tolerance, and it cannot be lower than the optimum of the same model: the comparison stands")
    if (not o.get("solve", True) or J.get("solve_skipped")) and "termination" not in J:
        why = "too large for HiGHS, see NOTES" if J.get("solve_skipped") else "--no-solve"
        if diffs:
            return "DIFFERENT: " + ", ".join(diffs)
        if C:
            return f"SAME: model size, rows, GAMS solution, reduced costs, right-hand sides and bounds agree; not solved here ({why})"
        if timing and G and G.get("rows") is not None and same_reduce(R, G):
            return f"BUILT: rows, columns and non-zeros are those of GAMS; not solved here ({why})" + pending
        return f"NOT SOLVED: built and not solved ({why}); " + ("the GAMS matrix was not read, so only the sizes are compared (see NOTES)" if G and G.get("rows") else "nothing to compare with")
    if J.get("termination") != "OPTIMAL" and not unproved:
        built = (" Checks that differ: " + ", ".join(diffs) + ".") if diffs else (" The model itself agrees with GAMS in checks 1 and 3." if C else
                 " Rows, columns and non-zeros are those of GAMS." if G and same_reduce(R, G) and G.get("rows") is not None else "")
        return f"NOT SOLVED: the model was built, and {solver_name(J)} ended with {J.get('termination')}." + built + (pending[1:].capitalize() + "." if timing else "")
    if not G:
        return f"SOLVED: objective {J['objective']:.6f}; not compared with GAMS (--gams run to compare)"
    if G.get("objective") is None and G.get("matrix_only") and not G.get("errors"):
        return (f"SOLVED: objective {J['objective']:.6f}; rows, columns and non-zeros are those of GAMS (GAMS wrote its matrix, not solved)"
                + (pending if timing else ""))
    if G.get("objective") is None:
        return f"ERROR: the GAMS run gave no objective ({gams_summary(G)}; {'; '.join(G.get('errors', [])[:2]) or 'see the listing'}); Julia objective {J['objective']:.6f}"
    if diffs and own_start and all(d == "objective" or d.startswith("objective of step") for d in diffs):
        # not a difference of the model: the two runs start from two solutions of the earlier run
        for c in R["checks"]:
            if c[0] == "2" and c[2] == "DIFFERENT":
                c[2] = "another start"
        what = ", ".join(sorted({str(e.get("read_for", "")).split(":")[0] for e in own_start}))
        notes.append(f"the objective is not that of the GAMS run in the folder (relative difference {R.get('objective_relative_difference', 0):.1e}), and that says "
                     f"nothing about the model: this run read the results of the earlier run as this implementation wrote them ({what}), the GAMS run read "
                     "those GAMS wrote. Where the earlier run has several optimal solutions the two are different points, and the periods fixed at them and "
                     "the base prices taken from them make two different models. To compare this model with TIMES in GAMS on the same results: --check")
        return (f"SOLVED: objective {J['objective']:.6f}; not compared with the GAMS run in the folder, which started from GAMS's results of the earlier run "
                f"and this run from its own (see NOTES; --check compares the two on the same results)")
    if diffs:
        if timing and diffs == ["objective"]:
            return f"DIFFERENT OBJECTIVE: relative difference {R.get('objective_relative_difference', 0):.1e}; rows, columns and non-zeros agree" + pending
        return "DIFFERENT: " + ", ".join(diffs)
    if ST and ST[0].get("sow"):
        return f"SAME: all {len(ST)} models of the SENSIS run agree with GAMS (model size and objective of every solve)"
    if ST:
        CS = J.get("compare_steps")
        return (("SAME: the run with FIXBOH agrees with GAMS (model size and objective" if len(ST) == 1 and fixboh else
                 f"SAME: all {len(ST)} steps of the myopic run agree with GAMS (model size and objective of every step")
                + (", rows of all steps" + (", levels" if CS["same_levels"] else "; the levels differ, see NOTES") if CS else "") + ")")
    if C:
        return ("SAME: model size, rows, objective, GAMS solution and reduced costs all agree" if C["gams_has_duals"]
                else "SAME: model size, rows, objective and GAMS solution agree (no marginals in the GAMS file)")
    if timing:
        return "SAME OBJECTIVE: the objective, rows, columns and non-zeros are those of GAMS" + pending
    return "SAME OBJECTIVE: only the objective was compared"


GAMS_AT_SOLVER = re.compile(r"^--- Executing (?!after solve)")    # the line of the GAMS log where its solver starts


def gams_log_facts(path):
    """From a GAMS log: the seconds to the first solver ("--- Executing HIGHS (Solvelink=2): elapsed 0:04:05.214"),
    the solver, and the size of the model it generated ("---   448,511 rows  795,128 columns  2,280,902 non-zeroes")."""
    if not os.path.exists(path):
        return {}
    t = read(path)
    f = {}
    m = re.search(r"(?m)^--- Executing (?!after solve)(\S+?)(?: \([^)]*\))?: elapsed (\d+):(\d+):([\d.]+)", t)
    if m:
        f["solver"] = m.group(1)
        f["seconds_to_solver"] = round(int(m.group(2)) * 3600 + int(m.group(3)) * 60 + float(m.group(4)), 1)
    m = re.search(r"(?m)^---\s+([\d,]+) rows\s+([\d,]+) columns\s+([\d,]+) non-zeroes", t)
    if m:
        f["rows"], f["columns"], f["nonzeros"] = (int(x.replace(",", "")) for x in m.groups())
    return f


def gams_phases(log, lst):
    """GAMS's time to its solver by phase, from what a GAMS run writes anyway: the log's elapsed stamps ("--- Starting
    execution: elapsed", "--- Executing <solver>: elapsed"), the listing's COMPILATION TIME and GENERATION TIME, and,
    when the run file sets OPTION PROFILE=1 (Veda's run files do), the profile lines of the listing, whose second
    number is the execution clock ("----  42015 Solve Init TIMES   0.000   0.094 SECS"). Seconds, and where each comes from.
      start-up     the GAMS process to its compilation (elapsed at "Starting execution" less the compilation)
      compilation  the run file, the DD files and the TIMES source read and compiled
      execution    the TIMES preprocessing, up to the solve statement ("Solve Init")
      generation   the model generated: "Solve Init" to "Solve Fini" (= GENERATION TIME); of it, "equations" up to the
                   last equation and "model for the solver" after it (the instance written for the solver)
      hand-over    the rest to "Executing <solver>"
    A run stopped at its solver may have a listing cut short: the end of the generation is then the solver's stamp."""
    if not os.path.exists(log):
        return {}
    t = read(log)
    P = {"source": {}}
    def hms(m):
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"(?m)^--- Starting execution: elapsed (\d+):(\d+):([\d.]+)", t)
    exec_at = hms(m) if m else None
    m = re.search(r"(?m)^--- Executing (?!after solve)\S+?(?: \([^)]*\))?: elapsed (\d+):(\d+):([\d.]+)", t)
    solver_at = hms(m) if m else None
    if solver_at is None:
        return {}
    P["to_solver"] = round(solver_at, 1)
    P["source"]["to_solver"] = "log: Executing <solver>: elapsed"
    L = read(lst) if lst and os.path.exists(lst) else ""
    comp = re.search(r"(?m)^COMPILATION TIME\s*=\s*([\d.]+) SECONDS", L)
    gen = re.search(r"(?m)^GENERATION TIME\s*=\s*([\d.]+) SECONDS", L)
    prof = [(m.group(1).strip(), float(m.group(2))) for m in
            re.finditer(r"(?m)^----\s*\d+ (.{20,}?)\s+[\d.]+\s+([\d.]+) SECS", L)]
    init = next((i for i, (w, _) in enumerate(prof) if w.startswith("Solve Init")), None)
    fini = next((i for i in range(init or 0, len(prof)) if prof[i][0].startswith("Solve Fini")), None) if init is not None else None
    if exec_at is not None:
        c = float(comp.group(1)) if comp else None
        P["start_up"] = round(exec_at - c, 1) if c is not None else None
        P["compilation"] = round(c if c is not None else exec_at, 1)
        P["source"]["compilation"] = "listing: COMPILATION TIME" if c is not None else "log: Starting execution: elapsed (with the start-up)"
        P["source"]["start_up"] = "log: Starting execution: elapsed, less COMPILATION TIME"
    if init is not None:
        P["execution"] = round(prof[init][1], 1)
        P["source"]["execution"] = "listing profile: Solve Init (execution clock)"
        eqs = [s for w, s in prof[init + 1:fini] if w.startswith("Equation")]
        if eqs:
            P["equations"] = round(eqs[-1] - prof[init][1], 1)
        if fini is not None:
            P["generation"] = round(prof[fini][1] - prof[init][1], 1)
            P["source"]["generation"] = "listing profile: Solve Init to Solve Fini" + (f" (GENERATION TIME {float(gen.group(1)):.1f})" if gen else "")
            if eqs:
                P["model_for_solver"] = round(prof[fini][1] - eqs[-1], 1)
        elif exec_at is not None:   # a listing cut short at the solver
            P["generation"] = round(solver_at - exec_at - prof[init][1], 1)
            P["source"]["generation"] = "Solve Init to the solver's stamp (the listing was cut short at the solver): with the hand-over"
            if eqs:
                P["model_for_solver"] = round(P["generation"] - P["equations"], 1)
    elif gen:
        P["generation"] = round(float(gen.group(1)), 1)
        P["source"]["generation"] = "listing: GENERATION TIME (no profile: execution and hand-over not apart)"
    if exec_at is not None and P.get("execution") is not None and P.get("generation") is not None:
        P["hand_over"] = round(max(0.0, solver_at - exec_at - P["execution"] - P["generation"]), 1)
        P["source"]["hand_over"] = "the solver's stamp less the phases before it"
    return P


def lp_hand_over(X):
    """--lp: the seconds of the hand-over to the solver of the user's GAMS and back, from julia.json's "gamslp" (X):
    copy (the LP taken from JuMP), gdx (arrays and the GDX written), to_solver (the GAMS process to its solver's
    start: loading the GDX and generating the LP), after_solver (the GAMS process after its solver: the solution
    written), read (the solution read back), total (all of them: everything of the solve but the solver's own time)."""
    g = lambda k: X.get(k) or 0.0
    to = X.get("gams_to_solver_seconds")
    to = g("gams_seconds") - g("solver_seconds") if to is None else to
    h = {"copy": g("copy_seconds"), "gdx": g("arrays_seconds") + g("gdx_seconds"), "to_solver": to,
         "after_solver": max(0.0, g("gams_seconds") - to - g("solver_seconds")), "read": g("read_seconds")}
    h["total"] = sum(h.values())
    return {k: round(v, 2) for k, v in h.items()}


def port_phases(R):
    """The port's time to HiGHS by phase, from the report: start-up (the runner before the preprocessor; the Julia
    script's packages), preprocessing (times_pp to model.tjb), model.tjb (written), load, build, counts, the copy into
    HiGHS (with the solver setup), and the rest (julia.exe to its script, waits, Julia's bookkeeping): they add up to
    to_highs."""
    T, J, P = R.get("timings", {}), R.get("julia") or {}, R.get("preprocess") or {}
    ph = J.get("phases") or {}
    if T.get("to_highs") is None or not ph or T.get("preprocess") is None:
        return {}
    tjb = P.get("tjb_seconds") or 0.0
    sec = lambda k: (ph.get(k) or {}).get("seconds", 0.0)
    out = {"start_up": round((T.get("before_preprocess") or 0.0) + (J.get("using_seconds") or 0.0) + (J.get("before_main_seconds") or 0.0), 1),
           "preprocessing": round(T["preprocess"] - tjb, 1), "model_tjb": round(tjb, 1),
           "load": round(sec("load"), 1), "build": round(sec("build"), 1), "counts": round(sec("counts"), 1),
           "copy_to_highs": round(sec("solver setup") + sec("copy to HiGHS"), 1), "to_solver": T["to_highs"]}
    if (J.get("gamslp") or {}).get("gams_to_solver_seconds") is not None:     # --lp: the hand-over to GAMS's solver
        H = lp_hand_over(J["gamslp"])
        out["copy_to_highs"] = round(sec("solver setup") + H["copy"] + H["gdx"] + H["to_solver"], 1)
    out["rest"] = round(out["to_solver"] - sum(v for k, v in out.items() if k != "to_solver"), 1)
    return out


def phase_table(R):
    """The two times to the solver side by side, phase against the phase that does the same work; each column adds
    up to its total. [] when either side is missing."""
    O, G = port_phases(R), ((R.get("gams") or {}).get("phases") or {})
    if not O or not G or G.get("execution") is None:
        return []
    lp = bool((R.get("julia") or {}).get("gamslp"))
    f = lambda x: "-" if x is None else f"{x:.1f}"
    rows = [("start-up", O["start_up"], "start-up", G.get("start_up"), "runner, julia.exe and packages / gams.exe"),
            ("preprocessing (times_pp)", O["preprocessing"], "compilation + execution", (G.get("compilation") or 0.0) + G["execution"],
             f"GAMS: compilation {f(G.get('compilation'))} (parses the data and the TIMES source; the port's code is cached), execution {f(G['execution'])}"),
            ("model.tjb written", O["model_tjb"], "", None, "no counterpart: GAMS keeps its data in memory"),
            ("load + build + counts", O["load"] + O["build"] + O["counts"], "generation", G.get("generation"),
             f"port: load {f(O['load'])}, build {f(O['build'])}, counts {f(O['counts'])}; GAMS: equations {f(G.get('equations'))}, model for the solver {f(G.get('model_for_solver'))}"),
            ("copy into HiGHS" if not lp else "hand-over (--lp)", O["copy_to_highs"], "hand-over", G.get("hand_over"),
             ("port: the whole model into HiGHS" if not lp else "port: the LP to a GDX and GAMS to its solver's start (generation included)")
             + "; GAMS: the instance is written in its generation, and read by the solver after the stamp"),
            ("rest (waits, bookkeeping)", O["rest"], "", None, "")]
    L = [f"  {'the port':28}{'s':>8}    {'GAMS':26}{'s':>8}  {'port/GAMS':>9}   note"]
    for a, x, b, y, n in rows:
        r = f"{x / y:.2f}" if y else ""
        L.append(f"  {a:28}{x:8.1f}    {b:26}{(f'{y:8.1f}' if y is not None else ''):>8}  {r:>9}   {n}".rstrip())
    L.append(f"  {'to the solver':28}{O['to_solver']:8.1f}    {'to the solver':26}{G['to_solver']:8.1f}  {O['to_solver'] / G['to_solver']:9.2f}")
    return L


def write_gams_matrix(case, work, out, wrun, name, src, gams, o, R, notes):
    """The run file with the solver CONVERT, which writes every coefficient and solves nothing.
    -> (exit status, seconds, what was read)"""
    got = {}
    print(f"[{case}] " + ("GAMS writes its matrix (CONVERT) ..." if o["solve"] else "GAMS generates the model and writes its matrix (CONVERT; --no-solve: nothing is solved) ..."), flush=True)
    mrun = os.path.join(work, name + "_matrix.run")
    text, k = re.subn(r"(?im)^(\s*\$\s*BATINCLUDE\s+maindrv)", "OPTION LP=CONVERT, MIP=CONVERT, RMIP=CONVERT;\n\\1", read(wrun), count=1)
    write(mrun, text)
    for ext in ("opt", "op2"):
        write(os.path.join(work, "convert." + ext), "jacobian matrix_jacobian.gdx\n")
    jgdx = os.path.join(work, "matrix_jacobian.gdx")
    seen = {"end": False}

    def shown(line):                                    # CONVERT returns no solution, so TIMES ends this call with "errors during solution":
        if seen["end"] or "is deprecated" in line:      # expected, and not shown; the whole log is in work/gams_matrix_log.txt
            return None
        if "Reading solution for model" in line:
            seen["end"] = True
            return "--- GAMS matrix written; this GAMS run (CONVERT) solves nothing"
        return line
    code, _, t = call([gams, os.path.basename(mrun), "IDIR=" + plain_path(src), "PS=99999", "LO=2", "LF=gams_matrix_log.txt"],
                      cwd=work, log=os.path.join(out, "gams_matrix_console.txt"), timeout=o["gams_limit"],
                      echo="    ", follow=os.path.join(work, "gams_matrix_log.txt"), show=shown)
    R["timings"]["gams_matrix"] = round(t, 1)
    if k and os.path.exists(jgdx):
        try:
            sys.path.insert(0, os.path.join(ROOT, "times_pp", "tools"))
            import gdx2sqlite
            t0 = time.time()
            if check_parquet() and os.path.isdir(os.path.join(out, "matrix_here")):
                import matrix_pq                         # the Parquet-to-Parquet check: GAMS's matrix as Parquet
                got["matrix_entries"] = matrix_pq.gams(jgdx, os.path.join(out, "matrix_gams_pq"), os.path.dirname(gams))["entries"]
                got["matrix_pq"] = True
            else:
                got["matrix_entries"] = gdx2sqlite.convert_jacobian(jgdx, os.path.join(out, "gams_matrix.db3"), os.path.dirname(gams))
                got["matrix_file"] = True
            R["timings"]["gams_matrix_convert"] = round(time.time() - t0, 1)
        except Exception as x:
            notes.append(f"the GAMS matrix could not be read ({type(x).__name__}: {str(x)[:200]}): check 4 was not made"
                         + ("; install the reader with: python -m pip install \"gamsapi[transfer]\" gamspy_base" if isinstance(x, ImportError) else ""))
    else:
        notes.append("GAMS did not write its matrix (the CONVERT call; see gams_matrix_log.txt in work/): check 4 was not made")
    return code, t, got


def gams_solution_file(G, gdx, gams, out, notes, same):
    """The GAMS solution (a GDX of a run with an objective, of the REDUCE level of the model built here: `same`) as
    gams_solution.db3, for checks 1 and 3."""
    full = G.get("solution_file", False)
    if gdx and same and G.get("objective") is not None:
        try:
            sys.path.insert(0, os.path.join(ROOT, "times_pp", "tools"))
            import gdx2sqlite
            gdx2sqlite.convert(gdx, os.path.join(out, "gams_solution.db3"), os.path.dirname(gams) if gams else None, solution_only=True)
            full = True
        except Exception as x:
            notes.append(f"the GAMS solution file could not be read ({type(x).__name__}: {str(x)[:200]}): only sizes and the objective are compared"
                         + ("; install the reader with: python -m pip install \"gamsapi[transfer]\" gamspy_base   (the same python that runs TIMES.py)"
                            if isinstance(x, ImportError) else ""))
    elif not same:
        notes.append("the GAMS run had REDUCE " + str(G.get("REDUCE")) + ", another level than the model built here: only the objective is compared")
    G["solution_file"] = full


MODEL_FILES = ("model.db3", "model.tjb", "model_steps.db3", "gams_solution.db3", "gams_matrix.db3")
MODEL_FOLDERS = ("model_parquet",           # the tables as Parquet files, in place of model.db3 (times_pp's stream.py)
                 "matrix_here", "matrix_here_pq", "matrix_gams_pq", "matrix_check.tmp")   # the matrix check in Parquet


def check_parquet():
    """The matrix check of --check. By default (TIMES_CHECK unset, or =parquet) without a second build: this model's
    matrix written by the run and GAMS's, as Parquet, compared in DuckDB (times_pp/tools/matrix_pq.py).
    TIMES_CHECK=julia: Julia builds the model again and compares (compare_matrix).
    TIMES_CHECK, the old name, is still read. A GAMS solution is compared by a Julia build in either case."""
    return (setting("CHECK") or "parquet").strip().lower() != "julia"


def model_tables(out):
    """The preprocessor's tables of a run: model.db3, or the Parquet folder written in its place."""
    f = os.path.join(out, "model_parquet")
    return f if os.path.isdir(f) and not os.path.exists(os.path.join(out, "model.db3")) else os.path.join(out, "model.db3")
GAMS_WORK_FILES = ("*.gdx", "*.g00", "*.lst", "*.put", "*.dmp")       # what GAMS wrote in work/ (the input copy stays)


def tidy(out, keep_model):
    """Delete the large files of a finished case: the tables, the converted GAMS files, and what GAMS wrote in work/.
    keep_model: keep them (--keep, or for a matrix check still to come)."""
    if keep_model:
        return
    for f in MODEL_FILES:
        if os.path.exists(os.path.join(out, f)):
            os.remove(os.path.join(out, f))
    for f in MODEL_FOLDERS:
        shutil.rmtree(os.path.join(out, f), ignore_errors=True)
    for pat in GAMS_WORK_FILES:
        for f in glob.glob(os.path.join(out, "work", pat)):
            try:
                os.remove(f)
            except OSError:
                pass


def drop_work(out, keep):
    """Delete work/, the copy of the input the run was made on (every DD file of the case: as large as the model's
    input, and the same files as in the case's folder), once the report is written. The run file as run is kept
    beside the report. keep: a matrix check still to come needs work/, or --keep."""
    work = os.path.join(out, "work")
    if keep or not os.path.isdir(work):
        return
    for f in glob.glob(os.path.join(work, "*.run")):
        if not f.lower().endswith("_matrix.run"):
            shutil.copy2(f, os.path.join(out, "run_file_" + os.path.basename(f)))
    shutil.rmtree(work, ignore_errors=True)


def write_report(out, R):
    write(os.path.join(out, f"report_{R['case']}.json"), json.dumps(R, indent=1))
    write(os.path.join(out, f"report_{R['case']}.txt"), report_text(R))


def check_case(out, o):
    """The matrix check of one finished case (phase 2 of --check, and `verify`): GAMS writes its matrix (CONVERT) in the
    case's work copy, a fresh Julia process builds the model again from the kept model.tjb and compares it with GAMS,
    entry by entry, and with the GAMS solution when GAMS solved; the report is judged again and rewritten.
    -> the report (dict)."""
    rj = glob.glob(os.path.join(out, "report_*.json"))
    if not rj:
        return {"case": os.path.basename(out), "verdict": "ERROR: no report_*.json in " + out, "checks": [], "timings": {}, "check_status": "not possible"}
    R = json.loads(read(rj[0]))
    case = R["case"]
    P, J, G = R.get("preprocess") or {}, R.get("julia") or {}, R.get("gams") or {}
    work = os.path.join(out, "work")
    run_file = (R.get("input") or {}).get("run_file") or ""
    wrun = os.path.join(work, os.path.basename(run_file))
    name = os.path.splitext(os.path.basename(run_file))[0]

    def skip(why):
        R["check_status"] = why
        write_report(out, R)
        print(f"[{case}] matrix check: {why}", flush=True)
        return R
    if J.get("matrix") and J["matrix"].get("same_model") is not None and R.get("phase") != "timing":
        return skip("checked already")
    if P.get("status") != "ok" or J.get("stage") != "done":
        return skip("skipped: the run itself did not complete (" + R["verdict"].split(":")[0] + ")")
    if J.get("steps") and not (len(J["steps"]) == 1 or J["steps"][0].get("sow")):
        return skip("skipped: a myopic run is compared step by step only while it runs (--check inline)")
    if J.get("steps") and not J.get("matrix_out"):
        # (FIXBOH: one model, its matrix written; SENSIS: the matrix of the first solve, the one GAMS's CONVERT run writes)
        return skip("skipped: the run did not write its matrix (run it with --check, or compare while it runs with --check inline)")
    if not same_reduce(R, G):
        return skip("skipped: the GAMS run had REDUCE " + str(G.get("REDUCE")) + ", another level than the model built here")
    missing = [f for f in ("model.db3", "model.tjb") if not os.path.exists(os.path.join(out, f))
               and not (f == "model.db3" and os.path.isdir(os.path.join(out, "model_parquet")))] + ([] if os.path.exists(wrun) else ["work/" + os.path.basename(wrun)])
    if J.get("steps") and not J["steps"][0].get("sow")             and not any(os.path.exists(os.path.join(out, f)) for f in ("model.db3", "model_steps.db3")):
        missing.append("model_steps.db3")             # (the steps of a FIXBOH run, beside the Parquet folder; SENSIS has none)
    if missing:
        return skip("not possible: " + ", ".join(missing) + " not kept (run with --check)")
    src, julia, gams = find_times(), find_julia(), find_gams()
    if not (src and julia and gams):
        return skip("not possible: " + ", ".join(n for n, v in (("the TIMES source", src), ("Julia", julia), ("GAMS", gams)) if not v) + " not found (setup)")
    notes = R["notes"]
    o = dict(o, solve=(R.get("run_options") or {}).get("solve", True))
    t0 = time.time()
    if not (G.get("matrix_pq") or G.get("matrix_file")):      # (phase 1 made the CONVERT run already: --check)
        code, t, got = write_gams_matrix(case, work, out, wrun, name, src, gams, o, R, notes)
        G.update(got)
    R["gams"] = G
    gdx = os.path.join(out, G["solution_gdx"]) if G.get("solution_gdx") else None
    if gdx and os.path.exists(gdx) and not G.get("solution_file"):
        gams_solution_file(G, gdx, gams, out, notes, same_reduce(R, G))
    jj = os.path.join(out, "julia_check.json")
    Mq = None
    if G.get("matrix_pq"):
        # the matrix check without a second build: this model's matrix (written by the run) and GAMS's, as Parquet,
        # compared in DuckDB with compare_matrix's rules (times_pp/tools/matrix_pq.py)
        print(f"[{case}] comparing the matrix with GAMS's in DuckDB (Parquet; no second build) ...", flush=True)
        pp_exe, _ = pp_python()
        tool = os.path.join(ROOT, "times_pp", "tools", "matrix_pq.py")
        mj = os.path.join(out, "matrix_check.json")
        c1, _, t1 = call([pp_exe, tool, "ours", os.path.join(out, "matrix_here"), os.path.join(out, "matrix_here_pq")],
                         log=os.path.join(out, "matrix_check.log"), timeout=(o["time_limit"] or 3600) + 3600, echo="    ")
        c2, _, t2 = call([pp_exe, tool, "compare", os.path.join(out, "matrix_here_pq"), os.path.join(out, "matrix_gams_pq"), "--json", mj,
                          "--temp", os.path.join(out, "matrix_check.tmp")],
                         log=os.path.join(out, "matrix_check_compare.log"), timeout=(o["time_limit"] or 3600) + 3600, echo="    ")
        R["timings"]["matrix_here_parquet"], R["timings"]["matrix_compare"] = round(t1, 1), round(t2, 1)
        if os.path.exists(mj):
            Mq = json.loads(read(mj))["matrix"]
    if G.get("solution_file") or (G.get("matrix_file") and not G.get("matrix_pq")):
        print(f"[{case}] building the model again in Julia and comparing it with GAMS ...", flush=True)
        jflags, jenv, _, _ = julia_threads(os.path.join(out, "model.tjb"))
        if (R.get("input") or {}).get("stochastic_addon") and stochastic_installed():
            jenv["TIMESEQ_STOCHASTIC"] = "1"
        cmd = [julia] + jflags + ["--startup-file=no", f"--project={JULIA_ENV}", os.path.join(ROOT, "times_eq", "tools", "run_case.jl"),
                                  os.path.join(out, "model.db3"), jj, "--no-solve"]
        if G.get("matrix_file") and not G.get("matrix_pq"):
            cmd += ["--matrix", os.path.join(out, "gams_matrix.db3")]
        if G.get("solution_file"):
            cmd += ["--gams", os.path.join(out, "gams_solution.db3")]
        code, _, t = call(cmd, log=os.path.join(out, "julia_check.log"), timeout=(o["time_limit"] or 3600) + 3600, env=jenv, echo="    ")
        R["timings"]["julia_check"] = round(t, 1)
        Jc = json.loads(read(jj)) if os.path.exists(jj) else {"stage": "start", "error": "Julia did not start or was stopped; see julia_check.log"}
    else:                                           # (nothing for Julia: the run's own size stands for the check's)
        Jc = {"stage": "done" if Mq is not None else "matrix", "error": None if Mq is not None else "the DuckDB matrix check wrote no result (matrix_check_compare.log)",
              "rows": J.get("rows"), "columns": J.get("columns"), "nonzeros": J.get("nonzeros")}
    if Mq is not None:
        Jc["matrix"] = Mq
        Jc["matrix_seconds"] = R["timings"]["matrix_compare"]
    R["julia_check"] = {k: Jc.get(k) for k in ("stage", "error", "rows", "columns", "nonzeros", "load_seconds", "build_seconds", "compare_seconds", "matrix_seconds")}
    if Jc.get("stage") != "done":
        notes.append(f"the matrix check stopped in stage '{Jc.get('stage')}': {(Jc.get('error') or '')[:300]} (julia_check.log)")
        R["check_status"] = "failed"
        write_report(out, R)
        return R
    if (Jc.get("rows"), Jc.get("columns"), Jc.get("nonzeros")) != (J.get("rows"), J.get("columns"), J.get("nonzeros")):
        notes.append(f"the model built for the check ({Jc.get('rows')} rows, {Jc.get('columns')} columns, {Jc.get('nonzeros')} non-zeros) is not the size "
                     "of the one the run built: the check does not cover the run")
        R["check_status"] = "failed"
        write_report(out, R)
        return R
    for k in ("compare", "matrix"):
        if Jc.get(k) is not None:
            J[k] = Jc[k]
    R["julia"] = J
    R["phase"] = "checked"
    R["check_status"] = "checked"
    R["timings"]["check"] = round(time.time() - t0, 1)
    R["verdict"] = judge(R, R.get("run_options") or {"tolerance": o["tolerance"], "solve": o["solve"]})
    write_report(out, R)
    if R["verdict"].startswith("SAME"):
        tidy(out, o["keep"])
        drop_work(out, o["keep"])
    print(f"[{case}] {R['verdict']}", flush=True)
    return R


def check_all(reports, out_root, o, header):
    """Phase 2 over the cases of a run, in order; Ctrl+C (or Ctrl+Break) stops it, the cases not reached keep their
    timing result and are listed as not checked. -> True when it was stopped"""
    if WIN:
        import signal
        signal.signal(signal.SIGBREAK, signal.default_int_handler)     # Ctrl+Break stops the checks as Ctrl+C does
    print("\n== the matrix checks (phase 2): GAMS writes its matrix, Julia builds again and compares; Ctrl+C stops here, "
          "the timing results stay as they are\n", flush=True)
    stopped = False
    for i, R in enumerate(reports):
        if stopped:
            R["check_status"] = "not checked (stopped)"
            continue
        if R.get("phase") != "timing":
            R.setdefault("check_status", "nothing to check" if R.get("phase") == "complete" else R.get("check_status"))
            continue
        try:
            reports[i] = check_case(os.path.join(out_root, R["case"]), o)
        except KeyboardInterrupt:
            print(f"\n[{R['case']}] matrix check stopped (Ctrl+C); the cases after it are not checked", flush=True)
            R["check_status"] = "not checked (stopped)"
            stopped = True
        if len(reports) > 1:
            write(os.path.join(out_root, "summary.txt"), summary_text(reports, header))
    return stopped




# ----------------------------------------------------------------------------------------------------------------
# the report
def highs_log_profile(path):
    """What the HiGHS log says about the solve: the presolved size, the method and its set-up, the iterations and their
    pace, crossover and the warnings. Read from highs.log after the run; {} when there is no log."""
    if not os.path.exists(path):
        return {}
    t = read(path)
    P = {}
    def num(x):
        try:
            return float(x)
        except ValueError:
            return None
    m = re.search(r"(?m)^Running HiGHS (\S+)", t)
    if m:
        P["version"] = m.group(1)
    m = re.search(r"(?m)^LP has (\d+) rows; (\d+) cols; (\d+) nonzeros", t)
    if m:
        P["rows"], P["columns"], P["nonzeros"] = map(int, m.groups())
    m = re.search(r"(?m)^Presolve reductions: rows (\d+)\(-?\d+\); columns (\d+)\(-?\d+\); nonzeros (\d+)", t)
    if m:
        P["presolved"] = list(map(int, m.groups()))
    elif re.search(r"(?m)^Presolve reductions: rows 0\(|Presolve: Optimal|Problem solved by presolve", t):
        P["presolved"] = [0, 0, 0]
    if "Running HiPO" in t:
        P["method"] = "HiPO"
        for key, label in (("threads", "Threads:"), ("newton", "Newton system:"), ("parallelism", "Parallelism:"),
                           ("analyse_seconds", "Analyse time:"), ("factor_nnz", "Nnz:"), ("fill_in", "Fill-in:"),
                           ("flops", "Flops:"), ("factor_mb", "Serial memory:")):
            m = re.search(r"(?m)^" + re.escape(label) + r"\s+(.+?)\s*$", t)
            if m:
                P[key] = m.group(1).replace(" MB", "")
    elif re.search(r"(?m)^IPX version", t):
        P["method"] = "IPX"
    elif "simplex solver" in t:
        P["method"] = "simplex"
    elif re.search(r"(?m)PDLP", t):
        P["method"] = "PDLP"
    # HiPO with log_dev_level=1: where its time went (Solver.cpp, printSummary)
    for key, label in (("factor_seconds", "Factorisation time:"), ("solve_seconds", "Solve time:"),
                       ("matrix_seconds", "Matrix time:"), ("residual_seconds", "Residual time:"),
                       ("factorisations", "Factorisations:"), ("solves", "Solves:"), ("correctors", "Correctors:")):
        m = re.search(r"(?m)^" + re.escape(label) + r"\s+([\d.e+-]+)\s*$", t)
        if m:
            P[key] = num(m.group(1))
    # the iteration tables: (iteration, seconds since the solve started) of each line printed
    rows = []
    for m in re.finditer(r"(?m)^\s*(\d+)\*?\s+[-+\d.e]+\s+[-+\d.e]+\s+[-+\d.e]+\s+[-+\d.e]+\s+[-+\d.e]+\s+([\d.]+)\s*$", t):
        rows.append((int(m.group(1)), float(m.group(2))))
    if not rows:
        for m in re.finditer(r"(?m)^\s+(\d+)\s+[-+\d.e]+\s+.*?([\d.]+)s\s*$", t):
            rows.append((int(m.group(1)), float(m.group(2))))
    if rows:
        P["first_iteration_seconds"] = rows[0][1]
        P["last_iteration_seconds"] = rows[-1][1]
        if rows[-1][0] > rows[0][0]:
            P["seconds_per_iteration"] = (rows[-1][1] - rows[0][1]) / (rows[-1][0] - rows[0][0])
    for key, label in (("ipm_iterations", "IPM       iterations"), ("simplex_iterations", "Simplex   iterations"),
                       ("crossover_iterations", "Crossover iterations"), ("pdlp_iterations", "PDLP      iterations")):
        m = re.search(r"(?m)^" + re.escape(label) + r":\s*(\d+)", t)
        if m:
            P[key] = int(m.group(1))
    m = re.search(r"(?m)^IPX iterations:\s+(\d+)", t)        # HiPO handing over to IPX
    if m:
        P["ipx_after_hipo"] = int(m.group(1))
    m = re.search(r"(?m)^HiGHS run time\s*:\s*([\d.]+)", t)
    if m:
        P["run_seconds"] = float(m.group(1))
    m = re.search(r"(?m)^Model status\s*:\s*(.+?)\s*$", t)
    if m:
        P["status"] = m.group(1)
    m = re.search(r"(?m)^P-D objective error :\s*(\S+)", t)
    if m:
        P["pd_objective_error"] = num(m.group(1))
    warn = []
    for m in re.finditer(r"(?m)^WARNING: (.+?)\s*$", t):
        w = " ".join(m.group(1).split())
        if w.startswith("Solution optimality conditions") or w.startswith("Consider scaling") or w in warn:
            continue
        if w.startswith("num/max") and warn and warn[-1].endswith("but with"):    # the second line of a two-line warning
            warn[-1] += " " + w.replace("num/max", "(number/largest)")
            continue
        warn.append(w)
    if warn:
        P["warnings"] = warn
    return P


def solve_lines(J, H):
    """The SOLVE lines of the report: how many cores the solve kept busy and where its time went."""
    if not H and not J.get("solve_cpu_seconds"):
        return []
    L = []
    wall, cpu = J.get("solve_seconds"), J.get("solve_cpu_seconds")
    cores = J.get("cpu_threads")
    used = ""
    if wall and cpu is not None and wall >= 0.5:
        used = f"; cores in use {cpu / wall:.1f}" + (f" of {cores}" if cores else "") + f" (CPU {cpu:.1f} s in {wall:.1f} s)"
    meth = H.get("method") or J.get("solver", "")
    setup = []
    if H.get("threads"):
        setup.append(f"{H['threads']} threads")
    if H.get("newton"):
        setup.append("Newton system " + H["newton"].replace(" preferred", "").replace("NE", "normal equations").replace("AS", "augmented"))
    if H.get("parallelism"):
        setup.append("parallelism " + H["parallelism"].replace(" preferred", "").lower())
    L.append(f"          solve     {meth}" + (f" ({', '.join(setup)})" if setup else "") + used + (f"; HiGHS {H['version']}" if H.get("version") else ""))
    if H.get("presolved") and H.get("rows"):
        r, c, n = H["presolved"]
        L.append(f"          presolve  rows {H['rows']:,} -> {r:,}, columns {H['columns']:,} -> {c:,}, non-zeros {H['nonzeros']:,} -> {n:,}")
    it = []
    if H.get("ipm_iterations") is not None:
        it.append(f"{H['ipm_iterations']} interior point iterations")
    if H.get("simplex_iterations"):
        it.append(f"{H['simplex_iterations']:,} simplex iterations")
    if H.get("ipx_after_hipo"):
        it.append(f"then {H['ipx_after_hipo']} IPX iterations")
    if H.get("crossover_iterations"):
        it.append(f"crossover {H['crossover_iterations']:,} iterations")
    pace = []
    if H.get("first_iteration_seconds") is not None:
        pace.append(f"first iteration at {H['first_iteration_seconds']:.1f} s")
    if H.get("seconds_per_iteration") is not None and H.get("method") != "simplex":
        pace.append(f"{H['seconds_per_iteration']:.2f} s per iteration")
    if H.get("analyse_seconds"):
        pace.append(f"analyse {float(H['analyse_seconds']):.1f} s")
    if H.get("factor_nnz"):
        pace.append(f"factor non-zeros {H['factor_nnz']}, fill-in {H.get('fill_in')}, flops {H.get('flops')}, memory {H.get('factor_mb')} MB")
    if H.get("factor_seconds") is not None:
        parts = [f"factorisation {H['factor_seconds']:.1f} s" + (f" ({int(H['factorisations'])}x)" if H.get("factorisations") else ""),
                 f"solves {H.get('solve_seconds', 0):.1f} s" + (f" ({int(H['solves'])}x)" if H.get("solves") else "")]
        parts += [f"{n} {H[k]:.1f} s" for k, n in (("matrix_seconds", "matrix"), ("residual_seconds", "residuals")) if H.get(k)]
        pace.append("HiPO time in " + ", ".join(parts))
    if it or pace:
        L.append("          iterations " + "; ".join(it + pace) + (f"; HiGHS run time {H['run_seconds']:.1f} s" if H.get("run_seconds") is not None else ""))
    for w in H.get("warnings", [])[:4]:
        L.append(f"          warning   {w}")
    return L


COMPILE_WARN_SECONDS = 10.0


def compile_warning(J):
    """A warning when Julia compiled more than COMPILE_WARN_SECONDS while building the model. With the package compiled
    ahead by setup (full mode), a build compiles about a second at most; much more means that some code this model
    reaches is compiled again in every run (typically a value whose type Julia cannot know before the run), which costs
    that time on every run of the model. Not given with setup --dev, nor with the build switch that the workload does
    not compile ahead (TIMESEQ_PAR_PIECES=0). None when there is nothing to say."""
    b = (J.get("phases") or {}).get("build") or {}
    c = b.get("compile_seconds")
    if c is None or c <= COMPILE_WARN_SECONDS:
        return None
    if workload_mode() == "dev" or os.environ.get("TIMESEQ_PAR_PIECES") == "0":
        return None
    return (f"Julia compiled {c:.1f} s while building the model (summed over its threads), of a build of {b.get('seconds', 0):.1f} s. "
            "With the package compiled ahead, a build compiles about a second: some code this model reaches is compiled "
            "again in every run. To find it, run times_eq/tools/run_case.jl on this model.db3 with Julia's --trace-compile "
            "option and look for the methods with the longest compile times.")


def julia_time_lines(J, wall):
    """Where the Julia run spent its time: one line of wall seconds by phase, one of compiling, garbage collection
    and memory. "start and packages" is the Julia process before the first phase (start-up, package loading,
    precompiling after a code change; for a Julia started early, from when it was given its run); "other" is the
    rest of the script that no phase covers."""
    ph = J.get("phases")
    if not ph:   # a result written before the phases were recorded
        return [f"          load {J.get('load_seconds')} s, build {J.get('build_seconds')} s, compare {J.get('compare_seconds', '-')} s, solve {J.get('solve_seconds', '-')} s; Julia {J.get('julia')}"]
    main = ("load", "checks", "build", "counts", "steps", "compare", "matrix", "solver setup", "copy to HiGHS", "solve", "solution", "solution file", "result file")
    order = [k for k in main if k in ph] + sorted(k for k in ph if k not in main)
    script, using, before = J.get("script_seconds") or 0.0, J.get("using_seconds") or 0.0, J.get("before_main_seconds") or 0.0
    start = using + (max(0.0, wall - script) if wall else 0.0)
    other = max(0.0, script - using - before - sum(ph[k]["seconds"] for k in order))
    early = (f" (packages loaded while the preprocessor ran: {J['using_seconds_early']:.1f} s)"
             if J.get("using_seconds_early") is not None else "")
    parts = ([f"start and packages {start:.1f} s{early}"] + ([f"script compile {before:.1f} s"] if before else [])
             + [f"{k} {ph[k]['seconds']:.1f} s" for k in order] + [f"other {other:.1f} s"])
    line1 = "          time      " + ", ".join(parts) + (f"; Julia process {wall:.1f} s" if wall else "") + f"; Julia {J.get('julia')}"
    comp = ", ".join(f"{k} {ph[k]['compile_seconds']:.1f} s" for k in order if ph[k]["compile_seconds"] >= 0.05) or "none measured"
    # the comparisons with GAMS (compare, matrix) are checks, not the cost of running the model: shown apart
    checks = [k for k in order if k in ("compare", "matrix")]
    gc = sum(ph[k]["gc_seconds"] for k in order if k not in checks)
    gb = sum(ph[k]["alloc_gb"] for k in order if k not in checks)
    gc_c = sum(ph[k]["gc_seconds"] for k in checks)
    gb_c = sum(ph[k]["alloc_gb"] for k in checks)
    peak = ""
    if J.get("maxrss_build_gb") is not None:
        # the peak up to the built model; the whole process (comparison, solve) only when it went higher
        peak = f"; peak memory {J['maxrss_build_gb']:.1f} GB to the built model"
        if J.get("maxrss_gb") is not None and J["maxrss_gb"] > J["maxrss_build_gb"] + 0.05:
            peak += f", {J['maxrss_gb']:.1f} GB for the whole run"
    elif J.get("maxrss_gb") is not None:   # a result written before maxrss_build_gb was recorded
        peak = f"; peak memory {J['maxrss_gb']:.1f} GB" + (" (with the comparison)" if checks else "")
    line2 = (f"          compiling (summed over the threads) {comp}; garbage collection {gc:.1f} s; allocated {gb:.1f} GB{peak}"
             + (f"; the comparison with GAMS: garbage collection {gc_c:.1f} s, allocated {gb_c:.1f} GB" if checks else ""))
    return [line1, line2]


def solver_name(J):
    """The solver of the run, by name (HiGHS, or the solver of the user's GAMS with --lp)."""
    name = ((J or {}).get("solver") or "").split()
    return name[0] if name else "the solver"


def report_text(R):
    L = []
    add = L.append
    add(f"VERDICT  {R['verdict']}")
    if R.get("files_not_written"):
        add("NOT WRITTEN  " + "; ".join(R["files_not_written"]))
    add(f"model    {R['case']}    ({R['folder']})")
    add(f"when     {R['started']}    total {R['timings'].get('total', '-')} s")
    if R.get("time_limit") and (R.get("run_options") or {}).get("solve", True):
        add(f"limit   {R['time_limit']['seconds']:g} s for each solve    ({R['time_limit']['from']})")
    add("")
    add("This file is written by TIMES.py. It is complete in itself: everything needed to understand")
    add("the result is below; the files it names are in the same folder.")
    add("")
    add("CHECKS")
    if R.get("gams"):
        add(f"  {'':3}{'check':40}{'result':20}{'Julia':24}GAMS")
        for lvl, what, res, a, b in R["checks"]:
            add(f"  {lvl:3}{what:40}{res:20}{a + '   ' if len(a) >= 24 else a:24}{b}".rstrip())
    else:                                       # nothing to compare with: the checks made on the model alone
        for lvl, what, res, a, b in R["checks"]:
            if res != "not made":
                add(f"  {what:40}{res:20}{a}".rstrip())
    P = R.get("preprocess")
    if P and P["status"] != "ok":
        add("")
        if P["unsupported"]:
            add(f"NOT SUPPORTED YET ({len(P['unsupported'])})")
            add("  Each line is one thing this implementation does not have yet. The input that needs it follows, with the number of records in the model.")
            for u in P["unsupported"]:
                sy = ", ".join(f"{k} ({v})" for k, v in u["symbols"].items())
                add(f"  - {u['what']}" + (f":  {sy}" if sy else ""))
        if P.get("stopped_in"):
            add(f"  The preprocessor could not go past the step '{P['stopped_in']}'" + (", so input that is only looked at in later steps is not in this list." if P["unsupported"] else "."))
        elif P["unsupported"]:
            add("  The preprocessor went through all its steps noting these as it met them, so the list is complete on the input side;")
            add("  the equations were not built, so what the equation module may lack is not known until these are supported.")
        for x in P.get("incomplete_steps") or []:
            last = (x["error"].strip().splitlines() or [""])[-1][:160]
            add(f"  The step '{x['step']}' could not complete with this input (most likely because of the above; {last});")
            add("  its remaining statements were skipped, so input that only they look at may be missing from the list.")
        if P.get("error"):
            add("  Error of the preprocessor (this is a defect of this implementation or an input it does not expect, not a listed limitation):")
            L.extend("    " + x for x in P["error"].strip().splitlines()[-12:])
    JU = R.get("equations_unsupported")
    if JU:
        add("")
        add(f"NOT SUPPORTED YET ({len(JU)})")
        add("  The preprocessor handles this input (or derives these tables from it); the equations that use them are not written yet.")
        for u in JU:
            add(f"  - {u['what']}:  {', '.join(u['tables'])}")
    J = R.get("julia")
    if J and J.get("error") and not JU:
        add("")
        add(f"JULIA stopped in stage '{J.get('stage')}'" + ("" if "not supported yet" not in J["error"] else
            "  (the equations are written one family after another and stop at the first thing they lack: there may be more)"))
        L.extend("    " + x for x in J["error"].splitlines()[:12])
    M = (J or {}).get("matrix")
    if M and M.get("equations"):
        add("")
        add("MATRIX BY EQUATION (check 4: the coefficients of GAMS and of Julia, matched by row and column name)")
        add(f"  {'equation':16}{'rows':>10}{'coefficients':>14}{'equal':>12}{'other value':>13}{'only here':>11}{'only GAMS':>11}   largest relative difference of the equal ones")
        for e in M["equations"]:
            add(f"  {e['name']:16}{e['rows']:>10,}{e['entries_gams']:>14,}{e['equal']:>12,}{e['different']:>13,}{e['only_here']:>11,}{e['only_gams']:>11,}   {e['largest_relative_difference']:.1e}")
        add(f"  {'all':16}{M['rows_gams']:>10,}{M['entries_gams']:>14,}{sum(e['equal'] for e in M['equations']):>12,}{M['entries_different']:>13,}{M['entries_only_here']:>11,}{M['entries_only_gams']:>11,}   {M.get('largest_relative_difference_equal', 0.0):.1e}")
        if M.get("entries_zero_both"):
            add(f"  {M['entries_zero_both']:,} of the equal coefficients are zero on both sides: GAMS keeps them in the matrix (EPS), and so does this implementation.")
    if M and not M["same_model"]:
        add("")
        add("MATRIX DIFFERENCES (entries by equation and variable; then right-hand sides and bounds)")
        for x in M["details"][:40]:
            add(f"  {x['kind']:13}{x['equation']:14} x {x['variable']:12}{x['entries']:>9,}   e.g. {x['example']}")
        L.extend("  " + x for x in M["examples"])
    C = (J or {}).get("compare")
    if C and not (C["same_rows"] and C["same_solution"] and (C["same_duals"] or not C["gams_has_duals"]) and C.get("same_rhs", True) and C.get("same_bounds", True)):
        add("")
        add("DIFFERENCES")
        for f in C["families"]:
            if f["missing"] or f["extra"]:
                add(f"  {f['name']}: Julia {f['julia']} rows, GAMS {f['gams']}; {f['missing']} in GAMS and not in Julia, {f['extra']} in Julia and not in GAMS")
                L.extend(f"      in GAMS only:  {x}" for x in f["missing_examples"])
                L.extend(f"      in Julia only: {x}" for x in f["extra_examples"])
        for a in C["activity"]:
            add(f"  {a['name']}: {a['rows_off']} rows where the GAMS solution gives another row level (largest relative difference {a['worst']:.2e}); e.g. {a['example']}")
        for a in C.get("rhs", []):
            add(f"  {a['name']}: {a['rows_off']} rows with another right-hand side or sense; e.g. {a['example']}")
        for a in C.get("bounds", []):
            add(f"  {a['name']}: {a['columns_off']} columns with other bounds; e.g. {a['example']}")
        for a in C["reduced_cost"]:
            add(f"  {a['name']}: {a['columns_off']} columns with another reduced cost (largest relative difference {a['worst']:.2e}); e.g. {a['example']}")
    G = R.get("gams")
    add("")
    add("THE TWO RUNS" if G else "THE RUN")
    if G:
        add(f"  GAMS    {G.get('mode')}" + "".join(f"; {w}{G[k]}" for w, k in (("REDUCE ", "REDUCE"), ("GAMS ", "gams_version"), ("TIMES v", "times_version"), ("solver ", "solver"))
                                                  if G.get(k) is not None))
        what = ("model generated and its matrix written, nothing solved (--no-solve)" if G.get("matrix_only") else
                "model generated, stopped at its solver (the port did not solve)" if G.get("stopped_at_solver") else
                gams_summary(G) + "; objective " + str(G.get("objective")))
        add(f"          {what}; rows {num(G.get('rows'))}, columns {num(G.get('columns'))}, non-zeros {num(G.get('nonzeros'))}"
            + (f"; {G['seconds']} s" if G.get("seconds") else "") + (f", {G['seconds_to_solver']} s to the solver" if G.get("seconds_to_solver") is not None else "")
            + (f"; exit status {G['exit_status']}" if G.get("exit_status") else ""))
        if R["timings"].get("to_highs") is not None and G.get("seconds_to_solver"):
            start = "the solver's start in GAMS, --lp" if (J or {}).get("gamslp") else "HiGHS's start"
            add(f"          time to the solver: the port {R['timings']['to_highs']} s (start of the run to {start}), GAMS {G['seconds_to_solver']} s:"
                f" {R['timings']['to_highs'] / G['seconds_to_solver']:.2f} times GAMS's")
            tab = phase_table(R)
            if tab:
                add("")
                add("  time to the solver by phase, each against the GAMS phase that does the same work (seconds; GAMS's from its log")
                add("  and the profile lines of its listing, OPTION PROFILE=1 of the run file)")
                L.extend(tab)
                add("")
        if G.get("objective") is None and not G.get("stopped_at_solver"):   # (with --no-solve: only when the matrix was not written)
            for e in G.get("errors", [])[-8:]:
                add(f"          GAMS said: {e}")
    E = R.get("gams_existing")
    if E and (not G or G.get("mode") != "existing run of the folder"):
        add(f"  (the run already in the folder: REDUCE {E['REDUCE']}; TIMES v{E['times_version']}; {E.get('solver_status')} / {E.get('model_status')}; objective {E['objective']}"
            + ("; its DD files are newer than this listing" if E["dd_files_newer_than_listing"] else "") + ")")
    MM = R.get("memory")
    if MM and (MM.get("port_gb") is not None or MM.get("gams_gb") is not None):
        g = MM.get("gams_gb")
        add(f"  memory  peak working set of the processes of each run, summed, every {MM['interval_s']} s: the open chain "
            f"{MM['port_gb']} GB (preprocessor and Julia, model.db3 included), GAMS "
            + ("not run" if g is None else f"{g} GB" + (" (to its solver)" if MM.get("gams_stopped_at_solver") else " (the whole run)"))
            + (f"; in the open chain's, GAMS of --lp {MM['port_gams_gb']} GB" if MM.get("port_gams_gb") is not None else ""))
    if J and J.get("rows") is not None:
        solved = (f"{J.get('solver', 'solver not named')}; {J['termination']}; objective {J.get('objective') if J.get('objective') is not None else 'none'}"
                  if "termination" in J else "built, not solved")
        add(f"  Julia   {solved}; rows {num(J['rows'])}, columns {num(J['columns'])}, non-zeros {num(J['nonzeros'])}")
        X = J.get("gamslp")
        if X:
            if "python_seconds" in X:
                add(f"          through Python (gurobipy): Gurobi {X.get('solver_version', '')}, {X.get('python_seconds', 0):.1f} s "
                    f"(build {X.get('generation_seconds', 0):.1f} s, solver {X.get('solver_seconds', 0):.1f} s, {X.get('iterations', 0):,} iterations); Gurobi's log: gamslp.log")
                if X.get("options_skipped"):
                    add("          option lines not applied (not Gurobi parameters): " + ", ".join(X["options_skipped"]))
                if X.get("no_duals"):
                    add("          NO DUALS: Gurobi gave no marginals; the marginals in solution.db3 are empty (NaN), "
                        "so prices and reduced costs are missing from the results")
            else:
              H = lp_hand_over(X)
              add(f"          through GAMS: the LP taken from JuMP {H['copy']:.1f} s, to a GDX {H['gdx']:.1f} s, GAMS {X.get('gams_seconds', 0):.1f} s "
                  f"(to the solver's start {H['to_solver']:.1f} s, of it generation {X.get('generation_seconds', 0):.1f} s; solver {X.get('solver_seconds', 0):.1f} s, "
                  f"{X.get('iterations', 0):,} iterations; after it {H['after_solver']:.1f} s), read back {X.get('read_seconds', 0):.1f} s: "
                  f"the hand-over {H['total']:.1f} s; " + ("GAMS's log: gamslp_step1.log" if X.get("steps") == 1 else
                                                            f"the {X['steps']} steps summed; GAMS's logs: gamslp_step1.log ... gamslp_step{X['steps']}.log"
                                                            if X.get("steps") else "GAMS's log: gamslp.log"))
            if X.get("infeasibility"):
                add(f"          optimal, with infeasibilities after unscaling: {X['infeasibility']}")
        if J.get("highs_options"):
            add("          HiGHS options: " + ", ".join(f"{k}={v}" for k, v in sorted(J["highs_options"].items())))
        L.extend(julia_time_lines(J, R["timings"].get("julia")))
        L.extend(solve_lines(J, R.get("highs") or {}))
        if J.get("steps") and J["steps"][0].get("sow"):
            add(f"          a SENSIS run: {len(J['steps'])} models, one for each state of the world of the first period, each solved on its own")
        elif J.get("steps") and len(J["steps"]) == 1:
            add("          one model, with its first periods fixed at the solution point the run loads (FIXBOH)" if (R.get("input", {}).get("switches") or {}).get("FIXBOH")
                else "          a run in steps with one step: one model")
        elif J.get("steps"):
            add(f"          a myopic run: {len(J['steps'])} steps, each {'solved' if 'termination' in J else 'built'} with the periods before its window fixed at the solution of the steps before")
        if J.get("solution_file"):
            add(f"          solution: {os.path.basename(J['solution_file'])} (levels, marginals and bounds of every column and row, by GAMS name"
                + (", merged over the steps" if J.get("steps") else "") + ")")
    elif P:
        add("  Julia   not run" + ("" if P["status"] == "ok" else " (the model uses input not supported yet, so the equations were not built)" if P["status"] == "unsupported" else " (the preprocessor failed)"))
    notes = R["notes"] + (R.get("judge_notes") or [])
    if R.get("check_status") and R["check_status"] != "checked":
        notes = notes + [f"matrix check: {R['check_status']}"]
    if notes:
        add("")
        add("NOTES")
        L.extend("  - " + n for n in notes)
    I = R.get("input", {})
    add("")
    add("INPUT")
    add(f"  run file  {I.get('run_file')}    sha256 {I.get('run_file_sha256_16', '-')}")
    if I.get("switches"):
        add("  switches  " + "  ".join(f"{k}={v}" for k, v in I["switches"].items()))
        rd = I.get("reduce") or {}
        add("            (as in the run file" + (f"; the copy used here has REDUCE={rd.get('built')}: the setting TIMES_REDUCE" if rd.get("setting") else "") + ")")
    for d in I.get("dd_files", []):
        add(f"  DD file   {d['name']:40}{d['bytes']:>12,} bytes  sha256 {d['sha256_16']}" + ("  (from the parent folder)" if d["from_parent_folder"] else ""))
    for d in I.get("missing_dd_files", []):
        add(f"  DD file   {d}   MISSING")
    V = R.get("veda_report")
    if V:
        add("")
        add("VEDA RESULT FILES (of the Julia solution; import them into Veda as a scenario next to the GAMS run)")
        if V.get("error"):
            add("  NOT WRITTEN: the report writer stopped; report.log has the message")
        else:
            n = sum(V.get("attributes", {}).values())
            add(f"  {V['scenario']}.vd, .vde, .vds   {n:,} rows in {len(V.get('attributes', {}))} attributes, {V.get('seconds')} s")
            for x in V.get("options_not_ported", []):
                add(f"  NOT IN THE FILE   {x}")
            for x in V.get("options_not_verified", []):
                add(f"  not yet compared with GAMS   {x}")
            if V.get("options_not_ported"):
                add("  The model asks for these reports and they are not written yet; everything else is written.")
    E = R["environment"]
    add("")
    add("ENVIRONMENT")
    add(f"  TIMES code         {E['code']}   (follows TIMES v{E['port_follows_TIMES']})")
    add(f"  TIMES source       v{E['times_source_version']}  {E['times_source']}")
    add(f"  Python {E['python']};  Julia {E['julia']};  GAMS {E['gams']}")
    add(f"  system             {E['os']}")
    if E.get("preprocessor_python"):
        P = R.get("preprocess") or {}
        add(f"  preprocessor       {E['preprocessor_python']['heap'].split(':')[0]}" + (f", DuckDB with {P['duckdb_threads']} threads" if P.get("duckdb_threads") else "")
            + (f", parallel stages level {P['parallel_stages']}" if P.get("parallel_stages") is not None else "")
            + (f";  the tables as model_parquet/, streamed beside the steps; tables dropped once no longer read: {'on (TIMES_DROP=1)' if E.get('drops') else 'off (TIMES_DROP=1 turns it on)'}"
               if E.get("tables") == "parquet" else
               f";  model.db3 written {'after the model is in HiGHS' if E.get('model_db3') == 'after' else 'beside the build (' + str(E.get('model_db3')) + ')'}"))
    if E.get("julia_settings"):
        S = E["julia_settings"]
        add(f"  Julia              threads {S['threads']}, garbage collector threads {S['gc_threads']}, at most {S['families_at_once']} equation families at once"
            + (f" (memory {S['memory_gb']} GB, expected peak {S['expected_peak_gb']} GB)" if S.get("expected_peak_gb") else ""))
    add(f"  seconds            " + ", ".join(f"{k} {v}" for k, v in R["timings"].items()))
    add("")
    add("FILES (same folder)")
    add(f"  report_{R['case']}.json   all of the above and more, for a program")
    add("  preprocess.log    the Python preprocessor;  preprocess.json: its result, with every switch of the run file")
    add("  gams_listing.lst  the GAMS listing of the run made here;  gams_log.txt: its log;  work/matrix_jacobian.gdx: the GAMS matrix")
    add("  julia.log         model build and the comparison with GAMS equation by equation"
        + (";  highs.log: the solver log" if J and "termination" in J else ""))
    if J and J.get("profile"):
        add(f"  julia_profile.txt  samples of the Julia table load and the equation build ({J.get('profile_mode', 'cpu')})")
    if V and not V.get("error"):
        add(f"  {V['scenario']}.vd/.vde/.vds   the Veda result files;  {V['scenario']}_report.json, report.log: what was written")
    add("  work/             the copy of the run folder that was used")
    add("")
    add("WHAT THE VERDICT MEANS")
    add("  SAME            every check that could be made against the published GAMS result agrees. With the published matrix the")
    add("                  two are the same linear program, and have the same optimum whether or not the solver finds it.")
    add("  SAME OBJECTIVE  the optimum is the one published; no more was published to compare with.")
    add("  DIFFERENT       the model runs and something does not agree with the published result: a defect. DIFFERENCES above says where to look.")
    add("  UNSUPPORTED     the model uses TIMES features this implementation does not have yet; they are all listed above. Not a defect.")
    add("  BUILT           the model was built and not solved (--no-solve, or too large for HiGHS); its rows, columns and non-zeros are those")
    add("                  of GAMS. The matrix is not compared entry by entry yet: the first line says how to have that done.")
    add("  NOT SOLVED      the model was built and the solver did not reach an optimum (time limit, or a failure of the solver). julia.log has the solver log.")
    add("  ERROR           a step failed. If it is the preprocessor or Julia, it is a defect; the message is above.")
    add("  INFEASIBLE      the model's data cannot be met: rows left with no column whose constant does not satisfy them")
    add("                  (0 = 2.685), on which TIMES in GAMS stops too (equation infeasible due to rhs value). Not a defect.")
    add("  SOLVED          the open chain solved the model; there was no published GAMS result to compare with (--jacobian writes the matrix")
    add("                  in the layout of GAMS's CONVERT jacobian, to compare with GAMS's own).")
    add("                  Also when the GAMS run at hand started from other results of an earlier run (FIXBOH, LPOINT, TIMESED) than this")
    add("                  run: the two objectives are then those of two models, and NOTES says so (--check compares on the same results).")
    add("  To report or to work on a result, hand over this file (or the bundle made with --bundle, which adds the input files).")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------------------------
# run
def run(args):
    global TIMES_GIVEN
    o = {"check": None, "matrix": False, "solve": True, "gams": None, "solver": "auto", "threads": 0, "highs_options": [], "time_limit": None, "gams_limit": None, "pp_limit": 7200, "tolerance": 1e-6, "bundle": False, "keep": False, "profile": "",
         "force_solve": False, "max_solve_rows": 2000000, "report": True, "low_memory": False, "milestones": None, "db3": False, "jacobian": None,
         "lp": "highs", "solver_options": [], "gams_exe": None, "lp_names": False, "points": []}
    out_root, folders, i = os.path.join(ROOT, "runs"), [], 0       # folders: (what was given, how) in order
    while i < len(args):
        a = args[i]
        if a == "--out":
            out_root = os.path.abspath(args[i + 1]); i += 1
        elif a == "--points":
            if i + 1 >= len(args):
                print("--points needs a folder: the result folder or the run folder of an earlier run")
                return 2
            o["points"].append(args[i + 1]); i += 1
        elif a == "--times":
            if i + 1 >= len(args) or not (os.path.isfile(os.path.join(args[i + 1], "initsys.mod")) and os.path.isfile(os.path.join(args[i + 1], "maindrv.mod"))):
                print("--times needs the TIMES source folder (the one that holds initsys.mod and maindrv.mod)")
                return 2
            TIMES_GIVEN = os.path.abspath(args[i + 1]); i += 1
        elif a == "--gams":
            o["gams"] = args[i + 1].lower(); i += 1
            o["gams"] = "models" if o["gams"] == "reference" else o["gams"]     # the documented name; "models" the older one
        elif a == "--solver":
            o["solver"] = args[i + 1].lower(); i += 1
        elif a == "--threads":
            o["threads"] = int(args[i + 1]); i += 1
        elif a == "--lp":
            o["lp"] = args[i + 1].lower(); i += 1
        elif a == "--cplex":
            o["lp"] = "cplex"
        elif a == "--lp-names":
            o["lp_names"] = True
        elif a == "--gurobi":
            o["lp"] = "gurobipy"
        elif a == "--solver-option":
            o["solver_options"].append(args[i + 1]); i += 1
        elif a == "--gams-exe":
            o["gams_exe"] = args[i + 1]; i += 1
        elif a == "--highs-option":
            if "=" not in args[i + 1]:
                print(f"--highs-option needs name=value, got {args[i + 1]}")
                return 2
            o["highs_options"].append(args[i + 1]); i += 1
        elif a == "--time-limit":
            o["time_limit"] = float(args[i + 1]); o["gams_limit"] = float(args[i + 1]) * 4 + 600; i += 1
        elif a == "--tolerance":
            o["tolerance"] = float(args[i + 1]); i += 1
        elif a in ("--bundle", "--keep", "--db3"):
            o[a[2:]] = True
        elif a == "--check":
            o["check"] = "after"
            if i + 1 < len(args) and args[i + 1].lower() in ("inline", "after"):
                o["check"] = args[i + 1].lower(); i += 1
            o["matrix"] = o["check"] == "inline"
        elif a == "--no-matrix":
            print("--no-matrix is gone: the matrix is compared only with --check (after the timing) or --check inline")
            return 2
        elif a == "--cases":
            if i + 1 >= len(args):
                print("--cases needs a file: one run folder per line")
                return 2
            folders.append((args[i + 1], "list")); i += 1
        elif a == "--no-solve":
            o["solve"] = False
        elif a == "--solve":
            o["force_solve"] = True
        elif a == "--max-solve-rows":
            o["max_solve_rows"] = int(float(args[i + 1])); i += 1
        elif a == "--profile":
            if i + 1 < len(args) and args[i + 1] in ("cpu", "allocs"):
                o["profile"] = args[i + 1]; i += 1
            else:
                o["profile"] = "cpu"
        elif a == "--no-report":
            o["report"] = False
        elif a == "--low-memory":
            o["low_memory"] = True
        elif a == "--jacobian":
            # the file is optional: none (the next word is an option, a run folder or a folder of them, or nothing)
            # -> <case>.gdx in the case's result folder; else a name, a path or a folder (jacobian_file() places it)
            nxt = args[i + 1] if i + 1 < len(args) else None
            if nxt is None or nxt.startswith("--") or glob.has_magic(nxt) or is_case_folder(nxt):
                o["jacobian"] = True
            else:
                o["jacobian"] = nxt; i += 1
        elif a == "--quiet":
            global VERBOSE
            VERBOSE = False
        elif a.startswith("--"):
            print(f"unknown option {a}\n\n{__doc__}")
            return 2
        else:
            folders.append((a, "arg"))
        i += 1
    if o["gams"] not in (None, "models", "run", "reuse", "skip") or o["solver"] not in ("auto", "simplex", "ipm", "hipo", "ipx"):
        print(__doc__)
        return 2
    if o["lp"] == "gurobipy":
        o["gams_exe"] = ""
        # checked before the model is built: setup installs gurobipy and scipy only when it finds Gurobi (a Gurobi licence is for one version)
        import importlib.util
        missing = [p for p in ("gurobipy", "scipy") if importlib.util.find_spec(p) is None]
        if missing:
            g_ver, g_home = find_gurobi()
            print(f"--gurobi needs the Python packages gurobipy and scipy ({', '.join(missing)} not found in {sys.executable}):\n"
                  + (f"  python TIMES.py setup   (it installs gurobipy {g_ver}, for Gurobi {g_ver} in {g_home})" if g_ver else
                     "  python TIMES.py setup --gurobi <the version of your Gurobi licence>\n"
                     f"  or: {sys.executable} -m pip install gurobipy==<the version of your Gurobi licence> scipy"))
            return 2
    elif o["lp"] != "highs":
        o["gams_exe"] = gams_for_lp(o["gams_exe"])
        if not o["gams_exe"]:
            print(f"--lp {o['lp']}: GAMS was not found (--gams-exe <gams executable>, TIMES_GAMS, settings.json \"gams\", or gams on the PATH)")
            return 2
        a = gams_lp_solvers(o["gams_exe"])                  # (kept in settings.json: found again in no time)
        if "licensed" in a and o["lp"].upper() not in a["licensed"]:
            print(f"--lp {o['lp']}: " + ("not an LP solver of" if o["lp"].upper() not in a["not_licensed"] else "not in the licence of")
                  + f" GAMS {a.get('version') or ''} ({o['gams_exe']}); its licence has: {', '.join(a['licensed']) or 'none'}")
            return 2
        if o["solver"] != "auto" or o["highs_options"]:
            print(f"note: --lp {o['lp']}: --solver and --highs-option are for HiGHS and are not used")
    cases, how = case_list(folders)
    if cases is None:
        return 2
    if not cases:
        print(__doc__)
        return 2
    planned, problems = result_folders(cases, out_root)
    if problems:
        print("Nothing was run; the result folders would harm the input:\n  " + "\n  ".join(problems))
        return 2
    for c, (name, _) in zip(cases, planned):
        if name != case_of(c):
            print(f"[{name}] {c}: another case has the name {case_of(c)}; its results go to {os.path.join(out_root, name)}")
    if o["check"] and o["gams"] in (None, "run"):
        # --check compares the model with TIMES in GAMS: settled before anything is built, so that a check that cannot be
        # made does not end as a run compared with nothing.  A run folder with a published reference and its matrix
        # (expected.json, gams_matrix.db3) is compared with those, without GAMS.
        here = lambda c, f: os.path.exists(os.path.join(os.path.dirname(c) if is_run_file(c) else c, f))
        if o["gams"] == "run" or not all(here(c, "expected.json") and here(c, "gams_matrix.db3") for c in cases):
            missing = ([] if find_gams() else ["GAMS (python TIMES.py setup --gams <gams executable>)"]) + \
                      ([] if find_times() else [f"the TIMES source v{PORT_VERSION} (--times <TIMES source folder>; python TIMES.py setup "
                                                "fetches it when GAMS is found)"])
            if missing:
                print("--check compares the model with TIMES in GAMS, which needs " + " and ".join(missing) + ".  Nothing was run.")
                return 2
    needs_gdx = o["gams"] in ("run", "reuse") or bool(o["check"]) or bool(o.get("jacobian")) or o["lp"] not in ("highs", "gurobipy") or (o["gams"] is None and any(      # the GDX reader is needed only when a GAMS run or listing is read;
        glob.glob(os.path.join(d, "*.lst")) and not os.path.exists(os.path.join(d, "expected.json")) for d in (os.path.dirname(c) if is_run_file(c) else c for c in cases)))   # a published reference needs no GAMS at all
    if needs_gdx:                                           # without the GDX reader no GAMS result can be compared: settle it before the long steps
        missing = [m for m in python_packages()[1] if m[0] in ("gams.transfer", "gamspy_base")]
        if missing:
            pips = sorted({m[1] for m in missing})
            print(f"The GDX packages (GAMS result and matrix files) are not installed in this Python ({sys.executable}). Installing: {' '.join(pips)}"
                  " (gamspy_base comes under the GAMS licence) ...", flush=True)
            code, out, t = call([sys.executable, "-m", "pip", "install"] + pips, timeout=1800)
            import importlib
            importlib.invalidate_caches()
            if code != 0 or any(m[0] == "gams.transfer" for m in python_packages()[1]):
                print("FAILED" + (":\n" + out[-2000:] if out else "") +
                      f"\nInstall it and run again:   \"{sys.executable}\" -m pip install \"gamsapi[transfer]\" gamspy_base\n"
                      "(or use --gams skip to solve without comparing).")
                return 1
            print(f"   done  ({t:.0f} s)", flush=True)
    os.makedirs(out_root, exist_ok=True)
    refresh_workload()
    compile_notice(locate(settings().get("julia")) or find_julia())
    # phase 1, the timing: every case in turn, its report and the summary written as soon as it is done
    reports = []
    for c, (name, _) in zip(cases, planned):
        try:
            R = one_case(c, out_root, o, name)
        except Exception as x:                               # a defect of this script must not stop a batch
            import traceback
            R = {"case": name, "verdict": f"ERROR: TIMES.py itself failed ({type(x).__name__}: {x})", "checks": [], "timings": {}}
            os.makedirs(os.path.join(out_root, R["case"]), exist_ok=True)
            write(os.path.join(out_root, R["case"], f"report_{R['case']}.txt"), "VERDICT  " + R["verdict"] + "\n\n" + traceback.format_exc())
        for m in list(TreePeak.running):                     # the sampler of a case that stopped on an error
            m.close()
        reports.append(R)
        print(f"[{R['case']}] {R['verdict']}" + (f"\n[{R['case']}] NOT WRITTEN: {'; '.join(R['files_not_written'])}" if R.get("files_not_written") else "")
              + f"\n[{R['case']}] report: {os.path.join(out_root, R['case'], 'report_' + R['case'] + '.txt')}", flush=True)
        if len(cases) > 1:
            write(os.path.join(out_root, "summary.txt"), summary_text(reports, how, len(cases)))
    # phase 2, with --check: the matrix of every case, compared after all the timings
    stopped = False
    if o["check"] == "after":
        stopped = check_all(reports, out_root, o, how)
    if len(cases) > 1:
        write(os.path.join(out_root, "summary.txt"), summary_text(reports, how, len(cases)))
        print(f"\nsummary: {os.path.join(out_root, 'summary.txt')}")
    return exit_status(reports, stopped)


def exit_status(reports, stopped=False):
    kinds = {r["verdict"].split(":")[0] for r in reports}
    return (1 if kinds & {"DIFFERENT", "DIFFERENT OBJECTIVE", "ERROR", "NOT SOLVED"} else 3 if "UNSUPPORTED" in kinds
            else 5 if "INFEASIBLE" in kinds else 130 if stopped else 4 if any(r.get("files_not_written") for r in reports) else 0)


def case_list(given):
    """The cases of a run, in order, each once. given: (text, "arg" | "list") in the order of the command line: a run
    folder, a run file, a folder of run folders, a wildcard (expanded here: cmd does not), or --cases <file> (one per
    line, # comments, paths relative to the file's folder). -> (folders and run files, how the list was formed), (None, _) on error"""
    cases, seen, how = [], set(), []

    def add(f, origin):
        k = os.path.normcase(os.path.abspath(f))
        if k in seen:
            how.append(f"  (once only: {f}, also {origin})")
            return
        seen.add(k)
        cases.append(os.path.abspath(f))

    def one(f, origin):
        if not os.path.exists(f) and is_run_file(f + ".run"):
            f += ".run"
        if is_run_file(f):
            add(f, origin)
            return True
        if not os.path.isdir(f):
            print(f"not a folder or a run file: {f}" + (f" ({origin})" if origin else ""))
            return False
        if run_files(f):
            add(f, origin)
            return True
        sub = [os.path.join(f, d) for d in sorted(os.listdir(f)) if os.path.isdir(os.path.join(f, d)) and run_files(os.path.join(f, d))]
        if not sub:
            print(f"no run file (*.run) in {f} or in its subfolders")
            return False
        for d in sub:
            add(d, origin)
        return True

    for text, kind in given:
        n0 = len(cases)
        if kind == "list":
            if not os.path.isfile(text):
                print(f"--cases: no such file: {text}")
                return None, how
            base = os.path.dirname(os.path.abspath(text))
            for line in read(text).splitlines():
                line = line.split("#", 1)[0].strip()
                if line and not one(line if os.path.isabs(line) else os.path.join(base, line), f"--cases {text}"):
                    return None, how
            how.append(f"  --cases {text}: {len(cases) - n0} run folders")
        elif glob.has_magic(text):
            hits = sorted(h for h in glob.glob(text) if os.path.isdir(h) or is_run_file(h))
            if not hits:
                print(f"nothing matches {text}")
                return None, how
            for h in hits:
                if not one(h, text):
                    return None, how
            how.append(f"  {text}: {len(cases) - n0} run folders (wildcard)")
        else:
            if not one(text, ""):
                return None, how
            how.append(f"  {text}" + (f": {len(cases) - n0} run folders" if len(cases) - n0 != 1 else ""))
    return cases, how


def verify(args):
    """python TIMES.py verify <result folder> [...] [--keep] [--quiet]: the matrix check (phase 2 of --check) on
    finished cases: a case's result folder, or a folder of them (a batch, whose summary.txt is updated)."""
    o = {"keep": False, "time_limit": 3600.0, "gams_limit": None, "tolerance": 1e-6, "solve": True}
    folders = []
    for a in args:
        if a == "--keep":
            o["keep"] = True
        elif a == "--quiet":
            global VERBOSE
            VERBOSE = False
        elif a.startswith("--"):
            print(f"unknown option {a}\n\n{__doc__}")
            return 2
        else:
            folders += sorted(glob.glob(a)) if glob.has_magic(a) else [a]
    if not folders:
        print(__doc__)
        return 2
    code = 0
    for f in folders:
        f = os.path.abspath(f)
        if glob.glob(os.path.join(f, "report_*.json")):
            root, outs = os.path.dirname(f), [f]
        else:
            root = f
            outs = [os.path.join(f, d) for d in sorted(os.listdir(f)) if glob.glob(os.path.join(f, d, "report_*.json"))] if os.path.isdir(f) else []
        if not outs:
            print(f"no finished case (report_*.json) in {f} or its subfolders")
            return 2
        reports = [json.loads(read(glob.glob(os.path.join(d, "report_*.json"))[0])) for d in outs]
        how = [f"  verify {f}"]
        for R in reports:
            if (R.get("phase") == "complete" and (R.get("gams") or {}).get("mode") == "run now"
                    and not (R.get("julia") or {}).get("matrix")):
                R["phase"] = "timing"           # run with GAMS before Julia and no matrix (--check inline was not given): checked now
        stopped = check_all(reports, root, o, how)
        if len(outs) > 1:
            write(os.path.join(root, "summary.txt"), summary_text(reports, how, len(outs)))
            print(f"\nsummary: {os.path.join(root, 'summary.txt')}")
        code = max(code, exit_status(reports, stopped))
        if stopped:
            break
    return code


def summary_text(reports, how=None, total=None):
    L = [f"TIMES: {len(reports)} models" + (f" of {total}" if total and total != len(reports) else "")
         + f", {datetime.datetime.now().isoformat(timespec='seconds')}", ""]
    if how:
        L += ["the cases, in the order run:"] + how + [""]
    count = {}
    for r in reports:
        k = r["verdict"].split(":")[0]
        count[k] = count.get(k, 0) + 1
    L.append("  ".join(f"{k} {v}" for k, v in sorted(count.items())))
    L.append("")
    L.append(f"{'model':32}{'verdict':21}{'rows':>10}{'objective (Julia)':>22}{'objective (GAMS)':>22}{'rel. diff.':>12}{'seconds':>9}"
             f"{'to solver':>10}{'GAMS to solver':>16}{'port GB':>9}{'GAMS GB':>9}  matrix check")
    for r in reports:
        J, G = r.get("julia") or {}, r.get("gams") or r.get("gams_existing") or {}
        rel = r.get("objective_relative_difference")
        th = r["timings"].get("to_highs")
        MM = r.get("memory") or {}
        chk = r.get("check_status") or ("pending" if r.get("phase") == "timing" else "-")
        L.append(f"{r['case'][:31]:32}{r['verdict'].split(':')[0]:21}{num(J.get('rows')):>10}"
                 f"{(format(J['objective'], '.4f') if J.get('objective') is not None else '-'):>22}"
                 f"{(format(G['objective'], '.4f') if G.get('objective') is not None else '-'):>22}"
                 f"{(format(rel, '.1e') if rel is not None else '-'):>12}{r['timings'].get('total', 0):>9}"
                 f"{(th if th is not None else '-'):>10}{(G.get('seconds_to_solver') if G.get('seconds_to_solver') is not None else '-'):>16}"
                 f"{(MM.get('port_gb') if MM.get('port_gb') is not None else '-'):>9}{(MM.get('gams_gb') if MM.get('gams_gb') is not None else '-'):>9}  {chk}")
    both = [(r, port_phases(r), (r.get("gams") or {}).get("phases") or {}) for r in reports]
    both = [(r, O, G) for r, O, G in both if O and G.get("execution") is not None]
    if both:
        L += ["", "TIME TO THE SOLVER BY PHASE, the port / GAMS (seconds; report_<case>.txt says what each pair covers)", "",
              f"{'model':32}{'start-up':>14}{'preprocessing':>16}{'model.tjb':>10}{'load+build+counts':>20}{'copy / hand-over':>18}{'rest':>7}{'to the solver':>16}"]
        p = lambda a, b: f"{a:.1f} / {b:.1f}" if b is not None else f"{a:.1f} / -"
        for r, O, G in both:
            L.append(f"{r['case'][:31]:32}{p(O['start_up'], G.get('start_up')):>14}"
                     f"{p(O['preprocessing'], (G.get('compilation') or 0.0) + G['execution']):>16}{O['model_tjb']:>10.1f}"
                     f"{p(O['load'] + O['build'] + O['counts'], G.get('generation')):>20}{p(O['copy_to_highs'], G.get('hand_over')):>18}"
                     f"{O['rest']:>7.1f}{p(O['to_solver'], G['to_solver']):>16}")
    feats = {}
    for r in reports:
        for u in (r.get("preprocess") or {}).get("unsupported") or []:
            key = u["what"] if not u["symbols"] else ", ".join(sorted(u["symbols"]))
            feats.setdefault(key, []).append(r["case"])
        for u in r.get("equations_unsupported") or []:
            feats.setdefault(u["what"] + " (equations)", []).append(r["case"])
    if feats:
        L += ["", "NOT SUPPORTED YET, by number of models that need it", ""]
        for k, v in sorted(feats.items(), key=lambda kv: (-len(set(kv[1])), kv[0])):
            L.append(f"{len(set(v)):4}  {k}    [{', '.join(sorted(set(v)))}]")
    other = [r for r in reports if r["verdict"].split(":")[0] in ("DIFFERENT", "DIFFERENT OBJECTIVE", "ERROR", "NOT SOLVED", "INFEASIBLE")]
    if other:
        L += ["", "DIFFERENT, DIFFERENT OBJECTIVE, ERROR, NOT SOLVED or INFEASIBLE", ""]
        L += [f"  {r['case']}: {r['verdict']}" for r in other]
    return "\n".join(L) + "\n"


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        # a character the console or a redirected file cannot encode (Julia's messages have some) is replaced: a
        # message must not stop the run that prints it
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if argv[0] in ("check", "run", "verify"):
        forwarded = reexec_in_venv()
        if forwarded is not None:
            return forwarded
    if argv[0] == "setup":
        return setup(argv[1:])
    if argv[0] == "check":
        chain, with_gams, _ = check()
        return 0 if chain else 1
    if argv[0] == "run":
        return run(argv[1:])
    if argv[0] == "verify":
        return verify(argv[1:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
