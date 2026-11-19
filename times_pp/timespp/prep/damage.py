# SPDX-License-Identifier: GPL-3.0-or-later
"""Damage costs (DAM_COST) with $SET DAMAGE NO: eqdamage.mod, the part that runs without the damage equations.

TIMES includes eqdamage.mod whenever DAM_COST has data (eqmain.mod: $IF DEFINED DAM_COST $BATINCLUDE eqdamage.%1).
With DAMAGE NO (compared as written: $IF %DAMAGE%==NO) the damage equations EQ_DAMAGE and EQ_OBJDAM are not in the
model (mod_equa.mod), and the objective component OBJDAM is zeroed (SUM_OBJ('OBJDAM',ITEM)=0): what is left that
changes the model is the balance of each commodity with a damage cost, made an equality with the net variable
VAR_COMNET:

    RHS_COMBAL(RTCS_VARC(RXX(R,T,C),S))$(NOT DAM_ELAST(R,C,'N')) = YES;
    RCS_COMBAL(RHS_COMBAL(RXX(R,T,C),S),'FX') = YES;

The other parameters of the extension (DAM_BQTY, DAM_TQTY, DAM_ELAST, DAM_STEP, DAM_VOC, DAM_COEF) shape the damage
equations, the report of the damages, and with DAM_ELAST(R,C,'N') the balances themselves (ppmain.mod); they are
refused, as is any other value of DAMAGE (the damage equations are not ported).
"""
from ..controls import given, unsupported
from ..engine import DB
from .common import require_empty

OTHER = ["DAM_BQTY", "DAM_TQTY", "DAM_ELAST", "DAM_STEP", "DAM_VOC", "DAM_COEF"]


def damage_off(db: DB):
    """DAMAGE is NO as TIMES compares it: $IF %DAMAGE%==NO (case-sensitive; not set: the damage equations are built)."""
    return given(db.env, "DAMAGE") == "NO"


def check(db: DB):
    """The damage costs this implementation builds: DAM_COST with DAMAGE NO, and none of the other inputs."""
    if not db.card("DAM_COST"):
        return
    if not damage_off(db):
        unsupported(db, "damage costs with the damage equations (DAMAGE not NO: EQ_DAMAGE, EQ_OBJDAM)", ["DAM_COST"])
    require_empty(db, OTHER, "damage cost curves (DAM_BQTY, DAM_TQTY, DAM_ELAST, DAM_STEP, DAM_VOC, DAM_COEF)")


def eqdamage(db: DB):
    """eqdamage.mod with DAMAGE NO (the module docstring), in its place at the end of eqmain.mod."""
    if not db.card("DAM_COST") or not damage_off(db):
        return
    # --- DAM_COST(R,T,C,CUR)$((DAM_COST(R,T,C,CUR) EQ 0)$DAM_COST(R,T,C,CUR)) = 0;          (EPS costs removed)
    db.zap("DAM_COST", "value = 0")
    # --- LOOP(RDCUR(R,CUR), RXX(RTC)$DAM_COST(RTC,CUR) = YES);
    db.tmp("t_damrxx", """select distinct k.r, k.y, k.c from RTC k join DAM_COST d on d.r=k.r and d.y=k.y and d.c=k.c
                          join RDCUR u on u.r=d.r and u.cur=d.cur""")
    # --- RHS_COMBAL(RTCS_VARC(RXX(R,T,C),S))$(NOT DAM_ELAST(R,C,'N')) = YES;   (DAM_ELAST: refused, check())
    #     RCS_COMBAL(RHS_COMBAL(RXX(R,T,C),S),'FX') = YES;
    sel = """select v.r, v.y, v.c, v.s from RTCS_VARC v
             where exists(select 1 from t_damrxx x where x.r=v.r and x.y=v.y and x.c=v.c)"""
    db.add("RHS_COMBAL", sel)
    db.add("RCS_COMBAL", """select h.r, h.y, h.c, h.s, 'FX' as l from RHS_COMBAL h
                            where exists(select 1 from t_damrxx x where x.r=h.r and x.y=h.y and x.c=h.c)""")
    db.x("drop table if exists t_damrxx")
