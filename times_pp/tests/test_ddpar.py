# SPDX-License-Identifier: GPL-3.0-or-later
"""The DD files read in parallel processes (ddpar.py) give the Reader state of reading them one after the other; and
the data blocks read from their text (gamsdata.Reader._parse_body) give the state of reading them from their tokens.

  python tests/test_ddpar.py [case.run ...]

Without arguments: a small made-up case whose DD files use what the parallel reader must get right ($ONEPS local to
the file that sets it, zeros removing earlier records, set texts replaced, SET.name, aliases, ranges and
parentheses in keys, assignment statements, a %name% set by an earlier DD file, $IF NOT SET, a scalar declared in an
earlier DD file), and data blocks of one record per line next to blocks that only look like it.  With run files: each
is read both ways and the states compared, and read once more with every data block from its tokens (TIMESPP_DD_FAST=0).
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from timespp.load import read_case
from timespp import gamsdata

FILES = {
    "a.dd": """$ONEPS
$SET MYVAL '7'
SET REG ' ' / 'R1' 'r2' /;
SET PRC ' ' / P1 'proc one', P2 /;
PARAMETER ACT_BND ' ' / 'R1'.'2020'.'P1'.'ANNUAL'.'UP' 5, R1.2030.P1.ANNUAL.UP 0 /;
ALIAS (PRC, PP);
SCALAR MYS / 3 /;
""",
    "b.dd": """PARAMETER ACT_BND / 'R1'.'2020'.'P1'.'ANNUAL'.'UP' 0 /;
$OFFEPS
PARAMETER NCAP_COST / R1.2020.(P1,P2).CUR 1, R1.2030.P1.CUR 0, 'r2'.'2020'.'p1'.'cur' 2, R1.2020.P3.CUR 4 /;
SET PRC / P1 'new text', P3 /;
SET MYSET / SET.PP, 'X' /;
""",
    "c.dd": """PARAMETER NCAP_FOM / R1.2020.P1.CUR %MYVAL% /;
""",
    "d.dd": """$IF NOT SET FOO $SET FOO 1
PARAMETER NCAP_FOM / R1.2030.P1.CUR %FOO% /;
""",
    "e.dd": """NCAP_COST(REG,'2020',PRC,'CUR')$(NCAP_COST(REG,'2020',PRC,'CUR') > 1.5) = EPS;
SET ALLYEAR / 2000*2003 /;
PARAMETER G_DRATE / R1.(2020,2030).CUR 0.05 /;
PARAMETER ZZ() 'a scalar in a DD file' / 4 /;
""",
    "f.dd": """PARAMETER ZZ / 5 /;
PARAMETER NCAP_COST / R1.2020.P2.CUR 0 /;
SET NEWS / 'q1' 'Q2' /;
""",
}
RUN = "$SET RUN_NAME 'T'\n" + "".join(f"$BATINCLUDE {f}\n" for f in FILES)


# data blocks of one record per line (read from their text), and blocks that only look like it (read from their tokens)
BLOCKS = {
    "g.dd": """$ONEPS
SET REG ' '
/
'R1'
r2 'region two'
'R 3' "text / with a slash"

'r.4'.'x'\t
/;
PARAMETER ACT_BND ' ' /
'R1'.2020.'P1'.ANNUAL.'UP' 1.5
R1.2030.P1.ANNUAL.UP 0
'R1'.'2040'.P2.'ANNUAL'.UP EPS
'r2'.2020.'p.1'.'annual'.'lo' -2e3
'R1'.2050.'P1'.'ANNUAL'.'UP'
'R1'.2060.'P1'.'ANNUAL'.'FX' +INF
'R1'.2070.'P1'.'ANNUAL'.'FX' 1_0
/;
SET EMPTY ' '
/
/;
SCALAR S1 ' '
/
5
/;
SET TS ' '
/
2020.5
2021
/;
SET TS2
/
SET.REG
'x2'
/;
PARAMETER P3
/
'R1' 1
'R1'.'a' '2'
/;
SET S3
/
'a' b
'c' 'text'
/;
PARAMETER P4
/
'R1'.'b' 2
'R1' .5
/;
PARAMETER P5
/
2020.'R1' 3
'R1'.'c' 4
/;
PARAMETER P6
/
'R1'.'d' 1.5.0
/;
PARAMETER P7
/
'R1'.'e' .25
'R1'.'f' 0.5
/;
""",
}


def test_fast_blocks():
    """The blocks of FILES and BLOCKS read from their text where they can, and all from their tokens: the same state."""
    with tempfile.TemporaryDirectory() as d:
        files = dict(FILES, **BLOCKS)
        for f, t in files.items():
            with open(os.path.join(d, f), "w") as h:
                h.write(t)
        run = os.path.join(d, "t.run")
        with open(run, "w") as h:
            h.write("$SET RUN_NAME 'T'\n" + "".join(f"$BATINCLUDE {f}\n" for f in files))
        used = []
        pb = gamsdata.Reader._parse_body

        def counted(self, *a):
            r = pb(self, *a)
            used.append(r is not None)
            return r
        gamsdata.Reader._parse_body = counted
        try:
            a, oa = read_case(run, d, workers=1)
        finally:
            gamsdata.Reader._parse_body = pb
        gamsdata.FAST_BLOCKS = False
        try:
            b, ob = read_case(run, d, workers=1)
        finally:
            gamsdata.FAST_BLOCKS = True
        c, oc = read_case(run, d, workers=3)
        sa, sb, sc = state(a), state(b), state(c)
        bad = [k for k in sa if sa[k] != sb[k]] + (["order"] if oa != ob else [])
        assert not bad, f"blocks read from their text and from their tokens differ in: {bad}"
        bad = [k for k in sa if sa[k] != sc[k]] + (["order"] if oa != oc else [])
        assert not bad and "g.dd" not in c.dd_serial, f"parallel and serial reading differ in: {bad}"
        # from the text: REG, ACT_BND; from the tokens: S1 (a scalar), TS, TS2, P3, S3, P4, P5, P6, P7
        assert used.count(True) == 2 and used.count(False) == 9, used
        assert a.sym["ACT_BND"].data[("R1", "2040", "P2", "ANNUAL", "UP")] == "EPS"
        assert a.sym["TS"].data == {("2020.5",): "", ("2021",): ""}
        # a value without its leading zero after a blank is a value, as GAMS reads it ('R1'.5 would be a key)
        assert a.sym["P7"].data == {("R1", "E"): 0.25, ("R1", "F"): 0.5}, a.sym["P7"].data
        return used


def state(rd):
    return {"sym": [(n, s.kind, s.domain, s.text, s.src, list(s.data.items())) for n, s in rd.sym.items()],
            "uel": list(rd.uel.items()), "casing": list(rd.casing.items()), "env": list(rd.env.items()),
            "alias": list(rd.alias.items()), "applied": rd.dd_applied, "unsup": rd.dd_unsupported,
            "enc": sorted(rd.encodings), "names": sorted(rd.dd_names), "oneps": rd.oneps}


def compare(run, src, workers=3, tokens=False):
    """What differs between reading serially and in `workers` processes; with tokens=True, between reading serially
    and reading serially with every data block from its tokens."""
    a, oa = read_case(run, src, workers=1)
    if tokens:
        gamsdata.FAST_BLOCKS = False
    try:
        b, ob = read_case(run, src, workers=1 if tokens else workers)
    finally:
        gamsdata.FAST_BLOCKS = True
    sa, sb = state(a), state(b)
    bad = [k for k in sa if sa[k] != sb[k]] + (["order"] if oa != ob else [])
    return bad, b


def test_made_up():
    with tempfile.TemporaryDirectory() as d:
        for f, t in FILES.items():
            with open(os.path.join(d, f), "w") as h:
                h.write(t)
        run = os.path.join(d, "t.run")
        with open(run, "w") as h:
            h.write(RUN)
        bad, rd = compare(run, d)
        assert not bad, f"parallel and serial reading differ in: {bad}"
        assert rd.dd_workers == 3
        # read here after all: c (%MYVAL% set by a), d ($IF NOT SET)
        assert sorted(rd.dd_serial) == ["c.dd", "d.dd"], rd.dd_serial
        # $ONEPS is local to the file that sets it (as GAMS 54 reads an included file): the 0 of a.dd is EPS, the 0 of
        # b.dd removes the record
        assert rd.sym["ACT_BND"].data[("R1", "2030", "P1", "ANNUAL", "UP")] == "EPS"
        assert ("R1", "2020", "P1", "ANNUAL", "UP") not in rd.sym["ACT_BND"].data
        assert ("R1", "2020", "P2", "CUR") not in rd.sym["NCAP_COST"].data              # removed by f.dd
        assert rd.sym["NCAP_COST"].data[("R1", "2020", "P3", "CUR")] == "EPS"            # the statement of e.dd
        assert rd.dd_applied and rd.dd_applied[0][2] >= 1
        return rd


if __name__ == "__main__":
    if len(sys.argv) > 1:
        src = os.environ.get("TIMESPP_SRC", "")
        for run in sys.argv[1:]:
            bad, rd = compare(run, src, int(os.environ.get("TIMESPP_DD_WORKERS", "3")))
            print(f"{run}: {'SAME' if not bad else 'DIFFERENT in ' + ', '.join(bad)}"
                  f"  ({rd.dd_workers} workers; read here: {rd.dd_serial or 'none'})")
            bad, rd = compare(run, src, tokens=True)
            print(f"{run}: {'SAME' if not bad else 'DIFFERENT in ' + ', '.join(bad)}  (every data block from its tokens)")
    else:
        rd = test_made_up()
        print("ok: parallel reading = serial reading; read here after all:", rd.dd_serial)
        print("   applied:", rd.dd_applied, " unsupported:", rd.dd_unsupported)
        used = test_fast_blocks()
        print(f"ok: data blocks from their text = from their tokens ({used.count(True)} from the text, "
              f"{used.count(False)} from the tokens)")
