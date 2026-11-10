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
    ("FLO", "7"): "topology, PAR_TOP / PAR_Top (solsetv.v3 FINISHUP)",
}
UNVERIFIED_OPT = {
    ("CAP", "5"): "cumulative retirements, PAR_CUMRET (rptmisc.rpt 37)",
    ("COMPRD", "4"): "market-share constraint levels, PAR_UCMRK (rptmisc.rpt 159-162); compared on a model without FLO_MARK",
}
# The same as GDX2VEDA writes (the option set Veda writes for most models): NCAP.1 = 1 (PAR_NCAPR
# LEVCOST), FLO.3 (VAL_FLO), OBJ.1 (CST_PVP / CST_PVC), ELC.1 with ELC.3 = 2 (P_OUT), FLO.5 (PAR_EOUT), FLO.1
# (flows and production at the commodity timeslices), COMPRD.1, ACT.2 = -1 and the *.9 thresholds.
# $SET switches of the run file
UNPORTED_ENV = {
    "BENCOST": ("YES", "benefit-cost ratios, PAR_NCAPR (rpt_objc.rpt 90-125)"),
    "RPT_TOP": ("YES", "topology, PAR_TOP / PAR_Top (solsetv.v3 FINISHUP)"),
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
    #   each type in UNCD1 whose '3' is negative.
    nrg, com = _members(db, "NRG_TYPE"), _members(db, "COM_TYPE")
    uncd1 = {u for (u, j), v in opt.items() if v and ((j == "3" and u in com) or (j == "1" and u in nrg))}
    ncap1 = opt.get(("NCAP", "1")) or 0
    if ncap1 and ncap1 != 1:
        unported.append(f"RPT_OPT('NCAP','1') = {ncap1:g}: only 1 is ported; the ENV credit (< 0) and the peak "
                        f"capacity term (> 1) of the levelized cost are not (rptmisc.rpt 214-236)")
    for u in sorted(uncd1):
        if (opt.get((u, "3")) or 0) < 0:
            unported.append(f"RPT_OPT('{u}','3') = {opt[(u, '3')]:g}: flows of {u} reported at ANNUAL (rptmisc.rpt 267-280)")
    for k, (val, what) in UNPORTED_ENV.items():
        if env.get(k) == val:
            unported.append(f"$SET {k} {val}: {what}")
    for k, (val, what) in UNVERIFIED_ENV.items():
        if env.get(k) == val:
            unverified.append(f"$SET {k} {val}: {what}")
    if env.get("RPT_FLOTS"):
        unported.append(f"$SET RPT_FLOTS {env['RPT_FLOTS']}: flows reported at ANNUAL (rptmisc.rpt 110)")
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
