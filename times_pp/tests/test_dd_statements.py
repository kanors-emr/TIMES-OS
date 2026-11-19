# SPDX-License-Identifier: GPL-3.0-or-later
"""Assignments in DD files and in the run file, as GAMS runs them.

GAMS enters the data of every file first (at compile time) and then runs the assignments in their order: a statement
sees the data of every file, also of the files included after it, and the run file's statements before the driver of
TIMES take their place among those of the DD files. A set is assigned as a parameter is: `= YES` (or any non-zero
value) makes the member, without the text it had; `= NO` removes it. Each case is a run file and the DD files it
includes, with the records GAMS has at the end (labels upper case).
"""
import os
import tempfile

from timespp.load import read_case

HEAD = ("SET REG / DE, FR, UK /;\nALIAS(REG,R);\nSET ALL_TS / ANNUAL, S, W /;\nALIAS(ALL_TS,TS);\n"
        "SET ALLYEAR / 2010*2050 /;\nSET MILESTONYR(ALLYEAR) //;\nALIAS(MILESTONYR,T);\nSET N / A, B /;\n"
        "SET C / ELC, GAS /;\nSET K(REG,N);\nSET KT(REG,N,ALLYEAR);\nSET PK(REG,C,ALL_TS);\nSET M(REG,C,C);\n"
        "PARAMETER P(REG,C) //;\nSCALAR G / 0 /;\n$ONMULTI\n")
YEARS = {("DE", "A", "2020"): "", ("DE", "A", "2030"): "", ("FR", "A", "2020"): "", ("FR", "A", "2030"): "",
         ("UK", "A", "2020"): "", ("UK", "A", "2030"): ""}

# name: (the rest of the run file, {DD file: text}, {symbol: records})
CASES = {
    "set_yes_over_an_alias": ("$include a.dd\n", {"a.dd": "K(R,'A') = YES;\n"},
                              {"K": {("DE", "A"): "", ("FR", "A"): "", ("UK", "A"): ""}}),
    "set_yes_over_a_set_and_labels": ("$include a.dd\n", {"a.dd": "K(REG,'B') = YES;\nK('UK','A') = YES;\n"},
                                      {"K": {("DE", "B"): "", ("FR", "B"): "", ("UK", "A"): "", ("UK", "B"): ""}}),
    "set_no": ("$include a.dd\n", {"a.dd": "SET K / DE.A, FR.A 'txt', FR.B /;\nK(REG,'A') = NO;\n"},
               {"K": {("FR", "B"): ""}}),
    "set_yes_drops_the_text": ("$include a.dd\n", {"a.dd": "SET K / DE.A 'txt', FR.B 'other' /;\nK(REG,'A') = YES;\n"},
                               {"K": {("DE", "A"): "", ("FR", "A"): "", ("FR", "B"): "other", ("UK", "A"): ""}}),
    "set_no_on_data_given_later": ("$include a.dd\n$include b.dd\n",
                                   {"a.dd": "K(REG,'A') = NO;\n", "b.dd": "SET K / DE.A, FR.B /;\n"},
                                   {"K": {("FR", "B"): ""}}),
    "set_over_years_given_later": ("$include a.dd\nSET MILESTONYR / 2020, 2030 /;\n",
                                   {"a.dd": "KT(REG,'A',T) = YES;\n"}, {"KT": YEARS}),
    "set_timeslices": ("$include a.dd\n", {"a.dd": "SET PK / DE.ELC.(ANNUAL,S,W), FR.ELC.S /;\nPK(REG,'ELC',TS) = NO;\n"
                                                   "PK(REG,'GAS','ANNUAL') = YES;\n"},
                       {"PK": {("DE", "GAS", "ANNUAL"): "", ("FR", "GAS", "ANNUAL"): "", ("UK", "GAS", "ANNUAL"): ""}}),
    "set_three_labels": ("$include a.dd\n", {"a.dd": "M(REG,'ELC','GAS') = YES;\n"},
                         {"M": {("DE", "ELC", "GAS"): "", ("FR", "ELC", "GAS"): "", ("UK", "ELC", "GAS"): ""}}),
    "parameter_on_data_given_later": ("$include a.dd\n$include b.dd\n",
                                      {"a.dd": "P(REG,C)$P(REG,C) = 5;\n", "b.dd": "PARAMETER P / DE.ELC 2, FR.GAS 3 /;\n"},
                                      {"P": {("DE", "ELC"): 5.0, ("FR", "GAS"): 5.0}}),
    "run_file_among_dd_files": ("$include a.dd\nK('DE','A') = YES;\n$include b.dd\n",
                                {"a.dd": "K(REG,'A') = NO;\n", "b.dd": "SET K / FR.A /;\nK(REG,'B') = YES;\n"},
                                {"K": {("DE", "A"): "", ("DE", "B"): "", ("FR", "B"): "", ("UK", "B"): ""}}),
    "run_file_scalar": ("$include a.dd\n;\ng = 2010;\n", {"a.dd": "SCALAR G / 1990 /;\n"}, {"G": {(): 2010.0}}),
    "run_file_scalar_before_its_data": ("g = 2010;\n$include a.dd\n", {"a.dd": "SCALAR G / 1990 /;\n"},
                                        {"G": {(): 2010.0}}),
}


def read(tail, files):
    with tempfile.TemporaryDirectory() as d:
        for name, text in dict({"case.run": HEAD + tail}, **files).items():
            with open(os.path.join(d, name), "w", newline="") as f:
                f.write(text)
        rd, _ = read_case(os.path.join(d, "case.run"), workers=1)
    return rd


def test_cases():
    bad = []
    for name, (tail, files, want) in CASES.items():
        rd = read(tail, files)
        got = {s: dict(rd.sym[s].data) for s in want}
        if rd.dd_unsupported or got != want:
            bad.append((name, rd.dd_unsupported, got, want))
    assert not bad, bad
