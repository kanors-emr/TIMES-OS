# SPDX-License-Identifier: GPL-3.0-or-later
"""The runner never harms its input: where the results of a run go, what it may delete, and its exit status.

  python -m pytest times_pp/tests/test_runner_safety.py

No Julia and no model are needed: folders are made in a temporary place and the work of a run is replaced by stubs.
The tests run on each runner of the repository (TIMES.py, and public/TIMES.py where there is one).
"""
import importlib.util, os, shutil, subprocess, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNERS = [p for p in ("TIMES.py", os.path.join("public", "TIMES.py")) if os.path.isfile(os.path.join(ROOT, p))]


def load(rel):
    name = "runner_" + rel.replace(os.sep, "_").replace(".", "_")
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


@pytest.fixture(params=RUNNERS)
def T(request):
    return load(request.param)


def run_folder(where, name="Demo", run=None):
    """A run folder: a run file and a DD file. -> its path"""
    d = os.path.join(str(where), name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, (run or name) + ".run"), "w") as f:
        f.write("$BATINCLUDE base.dd\n")
    with open(os.path.join(d, "base.dd"), "w") as f:
        f.write("SET X / A /;\n")
    return d


def intact(d):
    assert sorted(os.listdir(d))[:2] and os.path.isfile(os.path.join(d, "base.dd"))


class Reached(Exception):
    """Raised by a stub at the first step of a case after its cleanup."""


def clean_only(T, monkeypatch, case, out_root, **kw):
    """one_case up to its cleanup and the first files it writes."""
    def stop():
        raise Reached
    monkeypatch.setattr(T, "settings", stop)
    with pytest.raises(Reached):
        T.one_case(case, str(out_root), {}, **kw)


def go(T, monkeypatch, args):
    """TIMES.py run <args> with the work of each case stubbed. -> (exit status, names of the cases run)"""
    ran = []

    def one_case(c, out_root, o, name):
        ran.append(name)
        return {"case": name, "verdict": "SOLVED", "checks": [], "timings": {}}

    monkeypatch.setattr(T, "one_case", one_case)
    monkeypatch.setattr(T, "refresh_workload", lambda: None)
    monkeypatch.setattr(T, "compile_notice", lambda j: None)
    monkeypatch.setattr(T, "find_julia", lambda *a: None)
    monkeypatch.setattr(T, "write", lambda *a: None)
    return T.run([str(a) for a in args]), ran


# --- where the results go: the run folder is never the place -----------------------------------------------------

def test_out_is_the_parent_of_the_run_folder(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    assert go(T, monkeypatch, [d, "--out", tmp_path / "models"]) == (2, [])
    intact(d)


def test_out_is_the_parent_given_the_run_file(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    assert go(T, monkeypatch, [os.path.join(d, "Demo.run"), "--out", tmp_path / "models"]) == (2, [])
    intact(d)


@pytest.mark.skipif(os.name != "nt", reason="file names differ by case only on Windows")
def test_case_name_in_another_letter_case(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models", "DemoS_012", run="demos_012")
    assert go(T, monkeypatch, [os.path.join(d, "demos_012.run"), "--out", tmp_path / "models"]) == (2, [])
    intact(d)


def test_out_inside_the_run_folder(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path)
    assert go(T, monkeypatch, [d, "--out", os.path.join(d, "results")]) == (2, [])
    intact(d)


def test_out_is_the_run_folder(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path)
    assert go(T, monkeypatch, [d, "--out", d]) == (2, [])
    intact(d)


def test_folder_of_run_folders_with_out_that_folder(T, monkeypatch, tmp_path):
    a, b = run_folder(tmp_path / "set", "A"), run_folder(tmp_path / "set", "B")
    assert go(T, monkeypatch, [tmp_path / "set", "--out", tmp_path / "set"]) == (2, [])
    intact(a), intact(b)


def test_one_bad_case_stops_the_whole_batch(T, monkeypatch, tmp_path):
    a, b = run_folder(tmp_path / "x", "A"), run_folder(tmp_path / "y", "B")
    assert go(T, monkeypatch, [a, b, "--out", tmp_path / "x"]) == (2, [])
    intact(a), intact(b)


def junction(link, target):
    subprocess.check_call(["cmd", "/c", "mklink", "/J", str(link), str(target)], stdout=subprocess.DEVNULL)


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are of Windows")
def test_out_a_junction_to_the_run_folder(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    junction(tmp_path / "out", d)
    try:
        assert go(T, monkeypatch, [d, "--out", tmp_path / "out"]) == (2, [])
        intact(d)
    finally:
        os.rmdir(tmp_path / "out")


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are of Windows")
def test_out_a_junction_to_the_parent_of_the_run_folder(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    junction(tmp_path / "out", tmp_path / "models")
    try:
        assert go(T, monkeypatch, [d, "--out", tmp_path / "out"]) == (2, [])
        intact(d)
    finally:
        os.rmdir(tmp_path / "out")


def test_symbolic_link_to_the_parent(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    try:
        os.symlink(tmp_path / "models", tmp_path / "out", target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links need a privilege here")
    assert go(T, monkeypatch, [d, "--out", tmp_path / "out"]) == (2, [])
    intact(d)


# --- two cases of one name ---------------------------------------------------------------------------------------

def test_two_cases_of_one_name_both_kept(T, tmp_path):
    a, b = run_folder(tmp_path / "x", "Base"), run_folder(tmp_path / "y", "Base")
    planned, problems = T.result_folders([a, b], str(tmp_path / "out"))
    assert not problems
    assert [n for n, _ in planned] == ["Base", "Base_2"]
    assert len({os.path.normcase(o) for _, o in planned}) == 2


def test_name_of_a_second_case_taken_by_a_third(T, tmp_path):
    a, b, c = run_folder(tmp_path / "x", "Base"), run_folder(tmp_path / "y", "Base"), run_folder(tmp_path / "z", "Base_2")
    planned, problems = T.result_folders([c, a, b], str(tmp_path / "out"))
    assert not problems
    assert len({n.lower() for n, _ in planned}) == 3


def test_two_run_files_of_one_name(T, tmp_path):
    a, b = run_folder(tmp_path / "x", "P", run="base"), run_folder(tmp_path / "y", "Q", run="base")
    planned, _ = T.result_folders([os.path.join(a, "base.run"), os.path.join(b, "base.run")], str(tmp_path / "out"))
    assert [n for n, _ in planned] == ["base", "base_2"]


# --- what may be replaced ----------------------------------------------------------------------------------------

def test_a_folder_that_is_not_a_result_folder_is_not_replaced(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    other = tmp_path / "out" / "Demo"
    other.mkdir(parents=True)
    (other / "thesis.docx").write_text("mine")
    assert go(T, monkeypatch, [d, "--out", tmp_path / "out"]) == (2, [])
    assert (other / "thesis.docx").read_text() == "mine"


def test_a_file_in_the_place_of_the_result_folder(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "Demo").write_text("mine")
    assert go(T, monkeypatch, [d, "--out", tmp_path / "out"]) == (2, [])
    assert (tmp_path / "out" / "Demo").read_text() == "mine"


def test_an_empty_folder_is_used(T, tmp_path):
    d = run_folder(tmp_path / "models")
    (tmp_path / "out" / "Demo").mkdir(parents=True)
    assert not T.result_folders([d], str(tmp_path / "out"))[1]


def test_a_second_run_replaces_its_own_result_folder(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    out = tmp_path / "out"
    clean_only(T, monkeypatch, d, out)
    assert os.path.isfile(out / "Demo" / T.RESULT_MARK)
    (out / "Demo" / "old_result.txt").write_text("from the first run")
    assert not T.result_folders([d], str(out))[1]
    clean_only(T, monkeypatch, d, out)
    assert not os.path.exists(out / "Demo" / "old_result.txt")
    assert os.path.isfile(out / "Demo" / T.RESULT_MARK)
    intact(d)


def test_a_result_folder_of_an_older_runner_is_replaced(T, monkeypatch, tmp_path):
    """Before the mark there was the report."""
    d = run_folder(tmp_path / "models")
    old = tmp_path / "out" / "Demo"
    old.mkdir(parents=True)
    (old / "report_Demo.txt").write_text("VERDICT  SOLVED")
    (old / "old_result.txt").write_text("x")
    assert not T.result_folders([d], str(tmp_path / "out"))[1]
    clean_only(T, monkeypatch, d, tmp_path / "out")
    assert not os.path.exists(old / "old_result.txt")


def test_one_case_leaves_alone_what_it_did_not_make(T, monkeypatch, tmp_path):
    """Its own check, whatever came before it."""
    d = run_folder(tmp_path / "models")
    other = tmp_path / "out" / "Demo"
    other.mkdir(parents=True)
    (other / "thesis.docx").write_text("mine")
    clean_only(T, monkeypatch, d, tmp_path / "out")
    assert (other / "thesis.docx").read_text() == "mine"


def old_result_folder(where, name="Demo"):
    """A result folder of an earlier run as it stands: the copy of the run file, no DD files."""
    d = os.path.join(str(where), name)
    os.makedirs(d)
    for f, text in (("run_file_demo.run", "$BATINCLUDE base.dd\n"), (".times_result", "x"), (f"report_{name}.txt", "VERDICT  SOLVED")):
        with open(os.path.join(d, f), "w") as h:
            h.write(text)
    return d


def test_an_old_result_folder_given_as_a_run_folder_with_its_own_place(T, monkeypatch, tmp_path):
    d = old_result_folder(tmp_path / "runs")
    assert go(T, monkeypatch, [d, "--out", tmp_path / "runs"]) == (2, [])
    assert sorted(os.listdir(d)) == sorted([".times_result", "report_Demo.txt", "run_file_demo.run"])


def test_an_old_result_folder_given_as_a_run_folder_elsewhere(T, monkeypatch, tmp_path):
    """It is read like any run folder (and its DD files are missing: a report says so); it is not touched."""
    d = old_result_folder(tmp_path / "runs")
    monkeypatch.setattr(T, "find_julia", lambda *a: None)
    if hasattr(T, "find_times"):
        monkeypatch.setattr(T, "find_times", lambda *a: None)
        monkeypatch.setattr(T, "find_gams", lambda *a: None)
    R = T.one_case(d, str(tmp_path / "out"), {"keep": False, "check": None, "bundle": False}, "Demo")
    assert R["verdict"].startswith("ERROR: DD files")
    assert sorted(os.listdir(d)) == sorted([".times_result", "report_Demo.txt", "run_file_demo.run"])


# --- the exit status ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("verdicts, not_written, want", [
    (["SOLVED"], False, 0), (["SAME"], False, 0), (["SOLVED"], True, 4), (["SAME"], True, 4),
    (["UNSUPPORTED: a"], False, 3), (["UNSUPPORTED: a"], True, 3),
    (["ERROR: x"], False, 1), (["DIFFERENT OBJECTIVE"], False, 1), (["NOT SOLVED: x"], False, 1),
    (["SOLVED", "UNSUPPORTED: a"], False, 3), (["SOLVED", "ERROR: x"], True, 1),
])
def test_exit_status(T, verdicts, not_written, want):
    reports = [dict(verdict=v, files_not_written=["a file"] if not_written else None) for v in verdicts]
    assert T.exit_status(reports) == want




# --- a requested file that could not be written ------------------------------------------------------------------

def failed_writer(*a, **k):
    return 1, "", 0.1


def a_run():
    return {"case": "x", "notes": [], "timings": {}, "verdict": "SOLVED", "julia": {}}


def test_jacobian_not_written(T, monkeypatch, tmp_path):
    monkeypatch.setattr(T, "call", failed_writer)
    R = a_run()
    T.write_jacobian(R, "python", str(tmp_path / "x.gdx"), str(tmp_path), {"pp_limit": 1})
    assert R["jacobian"]["written"] is False
    assert any("jacobian" in f for f in R["files_not_written"])
    assert T.exit_status([R]) == 4


def test_jacobian_writer_says_ok_but_no_file(T, monkeypatch, tmp_path):
    monkeypatch.setattr(T, "call", lambda *a, **k: (0, "", 0.1))
    R = a_run()
    T.write_jacobian(R, "python", str(tmp_path / "x.gdx"), str(tmp_path), {"pp_limit": 1})
    assert T.exit_status([R]) == 4


def test_jacobian_written(T, monkeypatch, tmp_path):
    (tmp_path / "x.gdx").write_text("x")
    monkeypatch.setattr(T, "call", lambda *a, **k: (0, "", 0.1))
    R = a_run()
    T.write_jacobian(R, "python", str(tmp_path / "x.gdx"), str(tmp_path), {"pp_limit": 1})
    assert R["jacobian"]["written"] is True and T.exit_status([R]) == 0


def test_db3_not_written(T, monkeypatch, tmp_path):
    monkeypatch.setattr(T, "call", failed_writer)
    R = a_run()
    T.write_db3(R, "python", str(tmp_path), {"pp_limit": 1})
    assert any("model.db3" in f for f in R["files_not_written"])
    assert T.exit_status([R]) == 4


def test_db3_written(T, monkeypatch, tmp_path):
    (tmp_path / "model.db3").write_text("x")
    monkeypatch.setattr(T, "call", lambda *a, **k: (0, "", 0.1))
    R = a_run()
    T.write_db3(R, "python", str(tmp_path), {"pp_limit": 1})
    assert T.exit_status([R]) == 0


# --- MACRO MLF with another solver than HiGHS: refused before anything is built --------------------------------------

@pytest.mark.parametrize("lp, says", [("cplex", "--lp"), ("gurobipy", "--gurobi")])
def test_mlf_refused_with_another_solver(T, monkeypatch, tmp_path, lp, says):
    d = run_folder(tmp_path / "models")
    with open(os.path.join(d, "Demo.run"), "a") as f:
        f.write("$SET MACRO MLF\n")
    def nothing_runs(*a, **k):
        raise AssertionError("a program was started")
    monkeypatch.setattr(T, "revision", lambda: "x")
    monkeypatch.setattr(T, "call", nothing_runs)
    monkeypatch.setattr(T, "find_julia", lambda *a: None)
    if hasattr(T, "find_times"):
        monkeypatch.setattr(T, "find_times", lambda *a: None)
        monkeypatch.setattr(T, "find_gams", lambda *a: None)
    R = T.one_case(d, str(tmp_path / "out"), {"keep": False, "check": None, "bundle": False, "solve": True, "lp": lp}, "Demo")
    assert R["verdict"].startswith("ERROR: MACRO MLF") and says in R["verdict"]
    assert T.exit_status([R]) == 1
    assert not os.path.exists(tmp_path / "out" / "Demo" / "preprocess.json")


def test_mlf_goes_on_with_highs(T, monkeypatch, tmp_path):
    d = run_folder(tmp_path / "models")
    with open(os.path.join(d, "Demo.run"), "a") as f:
        f.write("$SET MACRO MLF\n")
    monkeypatch.setattr(T, "find_julia", lambda *a: None)
    if hasattr(T, "find_times"):
        monkeypatch.setattr(T, "find_times", lambda *a: None)
        monkeypatch.setattr(T, "find_gams", lambda *a: None)

    class Reached2(Exception):
        pass

    def stop(*a):
        raise Reached2
    monkeypatch.setattr(T, "sha", stop)
    with pytest.raises(Reached2):
        T.one_case(d, str(tmp_path / "out"), {"keep": False, "check": None, "bundle": False, "solve": True, "lp": "highs"}, "Demo")


# --- the time limit --------------------------------------------------------------------------------------------------

def test_limit_given_wins(T):
    assert T.time_limit_of(600.0, "OPTION RESLIM=50000;\n")[0] == 600.0
    assert T.time_limit_of(0.0, "OPTION RESLIM=50000;\n")[0] == 0.0


def test_limit_from_the_run_file_the_last_one(T):
    text = "OPTION RESLIM=100;\n* OPTION RESLIM=7;\noption lp=cplex, reslim = 50000;\nSET X;\n"
    secs, where = T.time_limit_of(None, text)
    assert secs == 50000.0 and "RESLIM" in where


def test_limit_default_is_that_of_gams(T):
    secs, where = T.time_limit_of(None, "$SET X 1\n")
    assert secs == 1e10 and "default" in where


def test_no_process_timer_without_a_limit(T):
    assert T.process_limit(0.0, "") is None
    assert T.process_limit(1e10, "") is None


def test_process_timer_counts_the_solves(T):
    assert T.process_limit(100.0, "") == 100 * 2 + 3600
    assert T.process_limit(100.0, "$SET MACRO MLF\n") == 100 * 2 * 19 + 3600
    assert T.process_limit(100.0, "$SET TIMESTEP 5\n") == 100 * 2 * 100 + 3600


def alive(pid):
    if os.name == "nt":
        out = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}", "/NH"], text=True)
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@pytest.mark.parametrize("verbose", [True, False])
def test_a_timeout_ends_the_whole_tree(T, monkeypatch, tmp_path, verbose):
    """A program that started another: on the timeout neither is left."""
    import time
    monkeypatch.setattr(T, "VERBOSE", verbose)
    pidfile = tmp_path / "child.pid"
    parent = tmp_path / "parent.py"
    parent.write_text("import subprocess, sys, time\n"
                      "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                      f"open(r'{pidfile}', 'w').write(str(p.pid))\n"
                      "time.sleep(120)\n")
    code, _, t = T.call([sys.executable, str(parent)], log=str(tmp_path / "log.txt"), timeout=3, echo="")
    assert code is None and t < 60
    pid = int(pidfile.read_text())
    for _ in range(20):
        if not alive(pid):
            break
        time.sleep(0.25)
    assert not alive(pid)
