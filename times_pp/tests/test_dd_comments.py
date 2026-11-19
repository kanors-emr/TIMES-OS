# SPDX-License-Identifier: GPL-3.0-or-later
"""Comments in DD and run files: every form GAMS allows is read as GAMS reads it, and what cannot be read stops with
the file and the line.

Each case is a run file and the DD files it includes. READ cases give the records GAMS reads from them (labels upper
case); ERROR cases are files GAMS refuses: the reader stops on them too, naming the file and the line; REFUSED
cases use a form the reader does not follow, and it stops there, naming it.
"""
import os
import tempfile

import pytest

from timespp.gamsdata import InputError
from timespp.load import read_case

RUN = ("SET R / DE, FR, UK /;\nSET C / CO2, CH4 /;\nSET BD / UP, LO, FX /;\nSET S;\n"
       "PARAMETER X(R,C,BD);\nPARAMETER Y(R,BD);\n$INCLUDE a.dd\n")
RUN2 = RUN + "$INCLUDE b.dd\n"
RUN3 = ("SET R / AT, BE /;\nSET N / CO2_BND /;\nSET YR / 0, 2015, 2050 /;\nSET T(R,N,YR);\nPARAMETER V(R,N,YR);\n"
        "PARAMETER W(R,N);\n$INCLUDE a.dd\n")
Z = "\x1a"                                     # Ctrl-Z, the DOS end-of-file mark: GAMS reads nothing after it


def P(body, pre=""):
    """A DD file with one block of X."""
    return pre + "PARAMETER X\n/\n" + body + "\n/;\n"


def SB(body, pre=""):
    """A DD file with one block of the set S."""
    return pre + "SET S\n/\n" + body + "\n/;\n"


X2 = {"X": {("DE", "CO2", "UP"): 5.0, ("FR", "CO2", "LO"): 3.0}}

# name: (run file, {DD file: text}, {symbol: records})
READ = {
    # end of line
    "eol_on": (RUN, {"a.dd": P("DE.CO2.UP 5 !! the bound\nFR.CO2.LO 3", "$ONEOLCOM\n")}, X2),
    "eol_chars": (RUN, {"a.dd": P("DE.CO2.UP 5 # the bound\nFR.CO2.LO 3", "$EOLCOM #\n")}, X2),
    "eol_two_chars": (RUN, {"a.dd": P("DE.CO2.UP 5 // c\nFR.CO2.LO 3", "$EOLCOM //\n")}, X2),
    "eol_whole_line": (RUN, {"a.dd": P("!! a line\nDE.CO2.UP 5\nFR.CO2.LO 3", "$ONEOLCOM\n")}, X2),
    "eol_in_word": (RUN, {"a.dd": SB("A!!B\nC", "$ONEOLCOM\n")}, {"S": {("A",): "", ("C",): ""}}),
    "eol_quoted": (RUN, {"a.dd": SB("A 'text !! kept'\nB", "$ONEOLCOM\n")},
                   {"S": {("A",): "text !! kept", ("B",): ""}}),
    "eol_between_key_and_value": (RUN, {"a.dd": P("DE.CO2.UP !! c\n 5\nFR.CO2.LO 3", "$ONEOLCOM\n")}, X2),
    "eol_declaration": (RUN, {"a.dd": "$ONEOLCOM\nPARAMETER X !! c\n/ !! c\nDE.CO2.UP 5\nFR.CO2.LO 3\n/;\n"}, X2),
    "eol_on_set": (RUN, {"a.dd": "$ONEOLCOM\n$SET V FR !! c\nPARAMETER X / %V%.CO2.UP 5 /;\n"},
                   {"X": {("FR", "CO2", "UP"): 5.0}}),
    "eol_from_run_file": ("$ONEOLCOM\n" + RUN, {"a.dd": P("DE.CO2.UP 5 !! c\nFR.CO2.LO 3")}, X2),
    "eol_on_include_line": ("$ONEOLCOM\n" + RUN.replace("$INCLUDE a.dd", "$INCLUDE a.dd !! c"),
                            {"a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3")}, X2),
    "eol_global": ("$ONGLOBAL\n" + RUN2, {"a.dd": "$ONEOLCOM\nPARAMETER X / DE.CO2.UP 5 /;\n",
                          "b.dd": "PARAMETER Y\n/\nDE.UP 1 !! c\n/;\n"},
                   {"X": {("DE", "CO2", "UP"): 5.0}, "Y": {("DE", "UP"): 1.0}}),
    "eol_table": (RUN, {"a.dd": "$ONEOLCOM\nTABLE Y(R,BD) !! c\n     UP   LO  !! c\nDE   1    2   !! c\nFR   3    4\n;\n"},
                  {"Y": {("DE", "UP"): 1.0, ("DE", "LO"): 2.0, ("FR", "UP"): 3.0, ("FR", "LO"): 4.0}}),
    # in line
    "inline_on": (RUN, {"a.dd": P("DE.CO2.UP 5 /* the bound */\nFR.CO2.LO 3", "$ONINLINE\n")}, X2),
    "inline_in_key": (RUN, {"a.dd": P("DE/* c */.CO2.UP 5\nFR.CO2.LO 3", "$ONINLINE\n")}, X2),
    "inline_lines": (RUN, {"a.dd": P("DE.CO2.UP 5 /* FR.CH4.LO 1\nUK.CO2.LO 4 */\nFR.CO2.LO 3", "$ONINLINE\n")}, X2),
    "inline_chars": (RUN, {"a.dd": P("DE.CO2.UP 5 { c }\n{ UK.CO2.LO 4 } FR.CO2.LO 3", "$INLINECOM { }\n")}, X2),
    "inline_nested": (RUN, {"a.dd": P("DE.CO2.UP 5 { a { UK.CO2.LO 4 } b }\nFR.CO2.LO 3",
                                      "$INLINECOM { }\n$ONNESTCOM\n")}, X2),
    "inline_star_inside": (RUN, {"a.dd": P("DE.CO2.UP 5 /*\n* UK.CO2.LO 4\n$SET V 1\n*/\nFR.CO2.LO 3",
                                           "$ONINLINE\n")}, X2),
    "inline_off": (RUN, {"a.dd": SB("A\nB", "$ONINLINE\n$OFFINLINE\n")}, {"S": {("A",): "", ("B",): ""}}),
    # the comment character, $ONTEXT, $HIDDEN
    "star_lines": (RUN, {"a.dd": P("* a comment\nDE.CO2.UP 5\n*FR.CO2.LO 9\nFR.CO2.LO 3")}, X2),
    "comment_char": (RUN, {"a.dd": P("# a comment\nDE.CO2.UP 5\n#FR.CO2.LO 9\nFR.CO2.LO 3", "$COMMENT #\n")}, X2),
    "ontext": (RUN, {"a.dd": P("DE.CO2.UP 5\n$ONTEXT\nUK.CO2.LO 4 !! /*\n$OFFTEXT\nFR.CO2.LO 3")}, X2),
    "ontext_blank": (RUN, {"a.dd": P("DE.CO2.UP 5\n$ ONTEXT\nUK.CO2.LO 4\n$ OFFTEXT\nFR.CO2.LO 3")}, X2),
    "ontext_include": (RUN + "$ONTEXT\n$INCLUDE b.dd\n$OFFTEXT\n",
                       {"a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3"), "b.dd": "PARAMETER Y / DE.UP 1 /;\n"},
                       {"X": X2["X"], "Y": {}}),
    "hidden": (RUN, {"a.dd": P("DE.CO2.UP 5\n$HIDDEN UK.CO2.LO 4\nFR.CO2.LO 3")}, X2),
    "options_on_one_line": (RUN, {"a.dd": P("DE.CO2.UP EPS !! c\nFR.CO2.LO 3", "$ONEPS ONEOLCOM\n")},
                            {"X": {("DE", "CO2", "UP"): "EPS", ("FR", "CO2", "LO"): 3.0}}),
    # Ctrl-Z ends a file
    "ctrlz_end": (RUN, {"a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3") + Z}, X2),
    "ctrlz_then_data": (RUN, {"a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3") + Z + "\nPARAMETER Y / DE.UP 1 /;\n"},
                        {"X": X2["X"], "Y": {}}),
    "ctrlz_two_files": (RUN2, {"a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3") + Z, "b.dd": "PARAMETER Y / DE.UP 1 /;\n"},
                        {"X": X2["X"], "Y": {("DE", "UP"): 1.0}}),
    "ctrlz_in_run": (RUN + Z + "\n$INCLUDE b.dd\n", {"a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3"),
                                                      "b.dd": "PARAMETER Y / DE.UP 1 /;\n"}, {"X": X2["X"], "Y": {}}),
    # a block ended by '/' without ';' at the end of a file
    "slash_no_semicolon": (RUN2, {"a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3")[:-2] + "\n",
                                  "b.dd": "PARAMETER Y / DE.UP 1 /;\n"}, {"X": X2["X"], "Y": {("DE", "UP"): 1.0}}),
    # blanks before the dots of a key: '.<digits>' is the next label while the key is shorter than the domain
    "dot_blank_set": (RUN3, {"a.dd": "SET T\n/\nAT      .CO2_BND .0\nAT \t  .CO2_BND .2050\n/;\n"},
                      {"T": {("AT", "CO2_BND", "0"): "", ("AT", "CO2_BND", "2050"): ""}}),
    "dot_blank_par": (RUN3, {"a.dd": "PARAMETER V\n/\nAT      .CO2_BND .0 5\nBE .CO2_BND .2015 6\n/;\n"},
                      {"V": {("AT", "CO2_BND", "0"): 5.0, ("BE", "CO2_BND", "2015"): 6.0}}),
    "dot_blank_value": (RUN3, {"a.dd": "PARAMETER W\n/\nAT .CO2_BND .5\n/;\n"},
                        {"W": {("AT", "CO2_BND"): 0.5}}),
}

# name: (run file, {DD file: text}, the file and line named, what the message holds)
ERROR = {
    "eol_not_on": (RUN, {"a.dd": P("DE.CO2.UP 5 !! c\nFR.CO2.LO 3")}, "a.dd, line 3", "!!"),
    "eol_undone_after_include": (RUN2, {"a.dd": "$ONEOLCOM\nPARAMETER X / DE.CO2.UP 5 /;\n",
                                        "b.dd": "PARAMETER Y\n/\nDE.UP 1 !! c\n/;\n"}, "b.dd, line 3", "!!"),
    "eol_global_inside": (RUN2, {"a.dd": "$ONGLOBAL\n$ONEOLCOM\nPARAMETER X / DE.CO2.UP 5 /;\n",
                                 "b.dd": "PARAMETER Y\n/\nDE.UP 1 !! c\n/;\n"}, "b.dd, line 3", "!!"),
    "eol_off": (RUN, {"a.dd": P("DE.CO2.UP 5 !! c", "$ONEOLCOM\n$OFFEOLCOM\n")}, "a.dd, line 5", "!!"),
    "inline_not_on": (RUN, {"a.dd": P("DE.CO2.UP 5\nFR /* c */.CO2.LO 3")}, "a.dd, line 4", ""),
    "inline_open_at_end": (RUN, {"a.dd": P("DE.CO2.UP 5 /* c", "$ONINLINE\n")}, "a.dd, line", "/*"),
    "ontext_open_at_end": (RUN, {"a.dd": P("DE.CO2.UP 5\n$ONTEXT\nFR.CO2.LO 3")}, "a.dd, line", "ONTEXT"),
    "dollar_indented": (RUN, {"a.dd": P("DE.CO2.UP 5", "  $ONEPS\n")}, "a.dd, line 1", "$"),
    "value_missing": (RUN, {"a.dd": P("DE.CO2.UP\nFR.CO2.LO 3")}, "a.dd, line 4", "value"),
    "key_too_short": (RUN, {"a.dd": P("DE.CO2 5")}, "a.dd, line 3", "key"),
    "block_open_at_end": (RUN, {"a.dd": "PARAMETER X\n/\nDE.CO2.UP 5\n"}, "a.dd, line 2", "ends the data of X"),
    "ctrlz_in_data": (RUN, {"a.dd": "PARAMETER X\n/\nDE.CO2.UP 5\n" + Z + "\nFR.CO2.LO 3\n/;\n"}, "a.dd, line 2",
                      "ends the data of X"),
}

# Forms GAMS reads that change what a line means in ways this reader does not follow: refused, with file and line.
REFUSED = {
    "dollar_char": (RUN, {"a.dd": P("DE.CO2.UP 5", "$DOLLAR #\n")}, "a.dd, line 1", "DOLLAR"),
    "maxcol": (RUN, {"a.dd": P("DE.CO2.UP 5", "$MAXCOL 20\n")}, "a.dd, line 1", "MAXCOL"),
    "mincol": (RUN, {"a.dd": P("DE.CO2.UP 5", "$MINCOL 2\n")}, "a.dd, line 1", "MINCOL"),
}


def _read(run, files):
    d = tempfile.mkdtemp(prefix="ddc_")
    for name, text in dict(files, **{"case.run": run}).items():
        with open(os.path.join(d, name), "w", newline="") as f:
            f.write(text.replace("\n", "\r\n"))
    return read_case(os.path.join(d, "case.run"), workers=1)[0]


@pytest.mark.parametrize("name", sorted(READ))
def test_read(name):
    run, files, want = READ[name]
    rd = _read(run, files)
    assert not rd.dd_unsupported, rd.dd_unsupported
    for sym, recs in want.items():
        assert dict(rd.sym[sym].data) == recs, (sym, dict(rd.sym[sym].data))


@pytest.mark.parametrize("name", sorted(ERROR) + sorted(REFUSED))
def test_error(name):
    run, files, where, what = ERROR.get(name) or REFUSED[name]
    try:
        rd = _read(run, files)
    except InputError as e:
        msg = str(e)
    else:
        msg = " | ".join(" ".join(map(str, u)) for u in rd.dd_unsupported)
        assert msg, "read without a refusal"
    assert where in msg and what in msg, msg


def test_errors_in_parallel_reading():
    """Files read in worker processes: a key of the wrong length (known only at the file's turn) and a missing value
    stop the run with the same message as when the files are read one after the other; valid files are read there."""
    for bad, msg in (("PARAMETER Y / DE.UP.X 1 /;\n", "b.dd, line 1"), ("PARAMETER Y\n/\nDE.UP\n/;\n", "b.dd, line 3")):
        d = tempfile.mkdtemp(prefix="ddp_")
        files = {"case.run": RUN2, "a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3"), "b.dd": bad}
        for name, text in files.items():
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        with pytest.raises(InputError) as e:
            read_case(os.path.join(d, "case.run"), workers=2)
        assert str(e.value).startswith(msg), str(e.value)
    d = tempfile.mkdtemp(prefix="ddp_")
    for name, text in {"case.run": RUN2, "a.dd": P("DE.CO2.UP 5\nFR.CO2.LO 3"), "b.dd": "PARAMETER Y / DE.UP 1 /;\n"}.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(text)
    rd = read_case(os.path.join(d, "case.run"), workers=2)[0]
    assert rd.dd_workers == 2 and not rd.dd_serial and rd.sym["Y"].data == {("DE", "UP"): 1.0}


def test_dollar_lines_of_a_run_file():
    """The dollar control lines a program looks at for the DD files and the switches: those in comments are not."""
    from timespp.gamsdata import dollar_lines
    run = ("$SET A 1\n* $SET B 2\n$ONTEXT\n$BATINCLUDE x.dd\n$OFFTEXT\n$ONEOLCOM\n$BATINCLUDE a.dd !! c\n$OFFEOLCOM\n"
           "$ONINLINE\n/* $BATINCLUDE y.dd\n*/\n$SET C 3 /* $SET D 4 */\n")
    assert [l.split() for l in dollar_lines(run)] == [["$SET", "A", "1"], ["$BATINCLUDE", "a.dd"], ["$SET", "C", "3"]]


def test_message_shape():
    """The message names the file, the line, what was expected, and shows the line cut to 120 characters."""
    long = "DE.CO2.UP five " + "x" * 200
    with pytest.raises(InputError) as e:
        _read(RUN, {"a.dd": P(long)})
    msg = str(e.value)
    assert msg.startswith("a.dd, line 3: ") and "value" in msg
    assert msg.endswith(long[:120])
