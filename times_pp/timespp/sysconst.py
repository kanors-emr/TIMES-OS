# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed system sets that TIMES declares with data outside the files read in stage 1.

Source: setglobs.gms (BDNEQ, BDUPX, BDLOX, BDSIG, IPS, LNX, RHS), ppmain.mod (MATPRC, SUBT),
initsys.mod (YEARVAL), coef_shp.mod (AGEJ), timslice.mod (JS), init_ext.vda (DUMIMP), initmty.dsc (UNIT).
"""

from .controls import dsc_on


def load(db):
    def put(name, rows):
        if db.card(name) == 0:
            db.load_rows(name, rows)
    put("BDNEQ", [("LO",), ("UP",)])
    put("BDUPX", [("FX",), ("UP",)])
    put("BDLOX", [("LO",), ("FX",)])
    put("BDSIG", [("LO", 1.0), ("UP", -1.0)])
    put("IPS", [("IN",), ("N",)])
    put("LNX", [("N",), ("FX",)])
    put("RHS", [("RHS",)])
    put("MATPRC", [("PRV",), ("PRW",)])
    put("SUBT", db.q("select y from MILESTONYR"))     # SET SUBT(T) / SET.T /  (compile time)
    put("AGEJ", [("1", "1")])
    put("JS", [("1", "ANNUAL")])
    put("DUMIMP", [("IMPNRGZ",), ("IMPMATZ",), ("IMPDEMZ",)])
    # --- initmty.dsc: SET UNIT / 0*100 /  (the DSC extension, loaded with the run switch DSC or DSCAUTO; initmty.vda
    #     has UNIT /0/). Only when the DD files give unit sizes, so that the other models keep their tables and labels.
    if dsc_on(db.env) and db.card("NCAP_DISC"):
        have = {u for (u,) in db.q('select * from "UNIT"')}
        db.load_rows("UNIT", [(str(j),) for j in range(101) if str(j) not in have])
    # --- YEARVAL(ALLYEAR) = %BOTIME% + ORD(ALLYEAR)-1;   YEARVAL('0') = 0  (no record)
    if db.card("YEARVAL") == 0:
        db.x('insert into "YEARVAL" select y, cast(y as DOUBLE) from ALLYEAR where y <> \'0\'')
