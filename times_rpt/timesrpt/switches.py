# SPDX-License-Identifier: GPL-3.0-or-later
"""The report options of a run that the port does not cover.

Most of the GAMS report runs in every model, but some blocks run only when the model sets a report option:
RPT_OPT in the data (Veda writes it to syssettings.dd from the run settings) or a $SET switch in the run file.
Many Veda models set several (levelized cost, flow values, power levels, electricity by source). A block the
port does not have would leave its Veda attributes out of the VD file without a word; check() names them, so
the run can say which attributes are missing and why.

    unported   options whose block is not ported: their attributes are not in the VD file
    unverified options whose block is ported but not yet reached with rows by a model
"""
from __future__ import annotations

# (option item, option index) -> what GAMS writes when it is set
UNPORTED_OPT = {
}
UNVERIFIED_OPT = {
    ("CAP", "5"): "cumulative retirements, PAR_CUMRET (rptmisc.rpt 37)",
}
# The same as GDX2VEDA writes (the option set Veda writes for most models): NCAP.1 = 1 (PAR_NCAPR
# LEVCOST), FLO.3 (VAL_FLO), OBJ.1 (CST_PVP / CST_PVC), ELC.1 with ELC.3 = 2 (P_OUT), FLO.5 (PAR_EOUT), FLO.1
# (flows and production at the commodity timeslices), COMPRD.1, ACT.2 = -1 and the *.9 thresholds.
# $SET switches of the run file
UNPORTED_ENV = {
}
# The report parameters an option of UNPORTED_OPT / UNPORTED_ENV changes although the port writes them: they are left
# out of the VD file (write.py), so that the numbers of the ordinary path are not taken for the option's.  None now:
# the OBJ options and ANNCOST LEV (cost_ann.rpt 19-32, 90-104, 165-172) are ported.
WITHHELD_OPT = {}
WITHHELD_ENV = {}
UNVERIFIED_ENV = {}   # SOLANS YES sets RPT_OPT('FLO','5'), covered above


def _options(db):
    if "RPT_OPT" not in db.sym or not db.card("RPT_OPT"):
        return {}
    cols = db.cols("RPT_OPT")
    return {(str(u).upper(), str(j)): v for u, j, v in db.q(f'select {cols[0]}, {cols[1]}, value from "RPT_OPT"')}


def _members(db, name):
    if name not in db.sym or not db.card(name):
        return set()
    c = db.cols(name)[0]
    return {str(x).upper() for (x,) in db.q(f'select {c} from "{name}"')}


def check(db):
    """(unported, unverified): lists of 'option: what is missing' for the options this run sets."""
    opt = _options(db)
    env = {k.upper(): str(v).strip("'\"").upper() for k, v in getattr(db, "env", {}).items()}
    unported, unverified = [], []
    for (u, j), what in UNPORTED_OPT.items():
        if opt.get((u, j)):
            unported.append(f"RPT_OPT('{u}','{j}') = {opt[(u, j)]:g}: {what}")
    for (u, j), what in UNVERIFIED_OPT.items():
        if opt.get((u, j)):
            unverified.append(f"RPT_OPT('{u}','{j}') = {opt[(u, j)]:g}: {what}")
    # power levels and the fall-back to ANNUAL (rptmisc.rpt 100-101, 127-133, 267-280):
    #   UNCD1 = commodity types with RPT_OPT(type,'3') and energy types with RPT_OPT(type,'1'); when it is not
    #   empty, flows are reported at the commodity timeslices (ported, rptmisc.py _flow_timeslices); then
    #   P_OUT for each energy type with '1' (ELC.3 = 2 makes it net of inputs), and a fall-back to ANNUAL for
    #   each type in UNCD1 whose '3' is negative (ported, rptmisc.py _annual_fallback).  $SET RPT_FLOTS ANNUAL
    #   (rptmisc.rpt 110: every flow at ANNUAL, without RPT_OPT('FLO','1')) is ported too (_flow_timeslices).
    # $SET BENCOST YES is ported (rptobjc.py _bencost) but for the capacity-related flow costs in its cost
    # coefficient (rpt_objc.rpt 63-73), which a model with NCAP_ICOM, NCAP_OCOM or NCAP_COM flows has
    if env.get("BENCOST") == "YES" and env.get("STAGES") != "YES" and "RPC_CAPFLO" in db.sym and db.card("RPC_CAPFLO"):
        unported.append("$SET BENCOST YES: the costs of the capacity-related flows (NCAP_ICOM, NCAP_OCOM, NCAP_COM) "
                        "are not in the COST of the benefit-cost indicators (rpt_objc.rpt 63-73)")
    for k, (val, what) in UNPORTED_ENV.items():
        if env.get(k) == val:
            unported.append(f"$SET {k} {val}: {what}")
    for k, (val, what) in UNVERIFIED_ENV.items():
        if env.get(k) == val:
            unverified.append(f"$SET {k} {val}: {what}")
    return unported, unverified


def withheld(db):
    """The report parameters left out of the VD file for the options of this run (WITHHELD_ENV)."""
    env = {k.upper(): str(v).strip("'\"").upper() for k, v in getattr(db, "env", {}).items()}
    opt, out = _options(db), set()
    for key, names in WITHHELD_OPT.items():
        if opt.get(key):
            out |= names
    for k, (val, names) in WITHHELD_ENV.items():
        if env.get(k) == val:
            out |= names
    return out
