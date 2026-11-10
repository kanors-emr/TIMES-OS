# SPDX-License-Identifier: GPL-3.0-or-later
"""What the chain refuses in a run file: a line that GAMS would act on and this implementation does not read stops the
run (UNSUPPORTED, naming the line), rather than being passed over.

  python -m pytest times_pp/tests/test_refusals.py

Each test copies models/DemoS_012 to a temporary folder, adds a line before the driver of TIMES is called, and runs the
preprocessor in audit mode (which lists everything unsupported in one pass). The plain copy goes through.
"""
import json, os, shutil, subprocess, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL = os.path.join(ROOT, "models", "DemoS_012")
RUN = "demos_012.run"
ASSIGN = "NCAP_AFA('REG1','2005','CAPEELC','UP') = 0.9;"


def audit(tmp_path, line=None, extra=None):
    """The audit of a copy of the model with `line` added. -> preprocess.json"""
    case = tmp_path / "case"
    shutil.copytree(MODEL, case)
    for name, text in (extra or {}).items():
        (case / name).write_text(text)
    run = case / RUN
    text = run.read_text()
    if line:
        assert "* do the rest" in text
        text = text.replace("* do the rest", line + "\n* do the rest")
    run.write_text(text)
    out = tmp_path / "audit.json"
    code = subprocess.call([sys.executable, "-m", "timespp", str(run), "-", str(tmp_path / "model.db3"), "--audit", str(out)],
                           cwd=os.path.join(ROOT, "times_pp"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert out.exists(), f"no audit (exit {code})"
    return json.loads(out.read_text())


def refused(P, *words):
    assert P["status"] == "unsupported", P["status"]
    assert any(all(w in u["what"] for w in words) for u in P["unsupported"]), P["unsupported"]


def test_the_plain_copy_goes_through(tmp_path):
    P = audit(tmp_path)
    assert P["status"] == "ok", P.get("unsupported") or P.get("error")


def test_an_assignment_in_the_run_file(tmp_path):
    refused(audit(tmp_path, ASSIGN), "NCAP_AFA", "run file")


def test_an_include_of_a_gms_file_is_read(tmp_path):
    """A file of the run folder that is not TIMES's: the model's own code, read where it stands as a DD file is."""
    P = audit(tmp_path, "$BATINCLUDE custom.gms", {"custom.gms": ASSIGN + "\n"})
    assert P["status"] == "ok", P.get("unsupported") or P.get("error")


def test_a_statement_not_read_in_an_included_file(tmp_path):
    refused(audit(tmp_path, "$BATINCLUDE custom.gms", {"custom.gms": "NCAP_AFA(R,'2005',P,'UP')$NCAP_AFA(R,'2005',P,'UP') = ORD(R);\n"}),
            "ORD(R)", "custom.gms")


def test_an_include_with_arguments(tmp_path):
    refused(audit(tmp_path, "$BATINCLUDE custom.gms X", {"custom.gms": ASSIGN + "\n"}), "custom.gms")


def test_an_include_of_a_file_that_does_not_exist(tmp_path):
    refused(audit(tmp_path, "$BATINCLUDE nosuchfile.gms"), "nosuchfile.gms", "GAMS would stop")


def test_include_without_bat(tmp_path):
    P = audit(tmp_path, "$INCLUDE custom.gms", {"custom.gms": ASSIGN + "\n"})
    assert P["status"] == "ok", P.get("unsupported") or P.get("error")


def test_an_include_of_a_dds_file(tmp_path):
    P = audit(tmp_path, "$BATINCLUDE extra.dds", {"extra.dds": "SET X / A /;\n"})
    assert P["status"] == "ok", P.get("unsupported") or P.get("error")


@pytest.mark.parametrize("line, name", [("$SET VINTOPT 1", "VINTOPT"), ("$SET SHARELAX NO", "SHARELAX"), ("$SET VALIDATE YES", "VALIDATE"),
                                        ("$SETGLOBAL NOSUCHSWITCH 1", "NOSUCHSWITCH"), ("$SETLOCAL SOLMIP YES", "SOLMIP"), ("$SET CUFSCAL 100", "CUFSCAL")])
def test_a_switch_not_known(tmp_path, line, name):
    refused(audit(tmp_path, line), "run-file switch " + name, "not known")


EXTRA_AFA = "PARAMETER NCAP_AFA /\n'REG1'.%MYYEARS%.'CAPEELC'.'UP' 0.9\n/;\n"


def test_a_label_list_of_the_model_is_taken(tmp_path):
    """A $SET whose name no file of TIMES reads, used as %name% in a DD file: the model's own (controls.model_macro)."""
    P = audit(tmp_path, "$SET MYYEARS (2005,2010)\n$BATINCLUDE extra.dd", {"extra.dd": EXTRA_AFA})
    assert P["status"] == "ok", P.get("unsupported") or P.get("error")


def test_datagdx_no(tmp_path):
    """DATAGDX NO: no filter of domain violations in TIMES (setglobs.gms 13), so taken only where there is none."""
    P = audit(tmp_path, "$SET DATAGDX NO")
    assert P["status"] == "ok", P.get("unsupported") or P.get("error")
    bad = "PARAMETER NCAP_AFA /\n'REG1'.2005.'NOSUCHPRC'.'UP' 0.9\n/;\n"
    refused(audit(tmp_path / "b", "$SET DATAGDX NO\n$BATINCLUDE extra.dd", {"extra.dd": bad}), "domain violations", "NOSUCHPRC")


def test_a_switch_in_a_dd_file(tmp_path):
    case_line = "$SET VINTOPT 1\n"
    P = audit(tmp_path, None, {"base.dd": open(os.path.join(MODEL, "base.dd"), encoding="utf-8", errors="replace").read() + case_line})
    refused(P, "run-file switch VINTOPT", "base.dd")


def test_a_conditional_that_is_not_evaluated(tmp_path):
    refused(audit(tmp_path, "$IF NOT SET XYZ $SET OBJ LIN"), "$IF NOT SET XYZ")


@pytest.mark.parametrize("line", ["$SET DSCAUTO YES", "$SET SHARELAX YES", "$SET VDA YES", "OPTION RESLIM=100;", "$ONMULTI"])
def test_lines_that_change_nothing_are_taken(tmp_path, line):
    assert audit(tmp_path, line)["status"] == "ok"
