# SPDX-License-Identifier: GPL-3.0-or-later
"""Stochastic TIMES ($SET STAGES YES): the preprocessing.

    prep_ext(db, interp)  prep_ext.stc  (preppm.mod 216: before the extensions' prep_ext)
    stages(db)            stages.stc    (maindrv.mod 65: after ppm_ext, before coefmain), with fillsow.stc

The declarations are those of initmty.stc (load.py reads them). A stochastic model has a tree of states of the world
(SOW): stage 1 has one SOW from SW_START('1'), each SOW of a stage has SW_SUBS children from the start year of the next
stage, with the conditional probabilities SW_SPROB (or the probabilities of the last stage SW_PROB). The model is
written for the SOWs that are distinct in each period (SW_T(T,SOW)); SW_TSW(SOW,T,W) maps each SOW of the last stage to
its representative W in period T, SW_TPROB(T,W) is the probability of W in T. The uncertain attributes S_<attribute>
give the value of the attribute by stage J and SOW of that stage; fillsow.stc merges them into stage '1' by
representative SOW.

The tree is small (at most 96 SOWs, a few stages), so its statements are run here on Python dictionaries, in the order
of the GAMS code.
"""
from __future__ import annotations
import math
from ..engine import DB
from ..controls import unsupported
from .common import require_empty

EPS = 0.0                                         # a parameter row with value 0 is EPS


def on(db: DB):
    """maindrv.mod 33: $IFI %STAGES% == YES $SET STAGES YES   (with SENSIS too: STAGES is then Yes)"""
    return bool(db.ctl.get("STAGES"))


def tagged(db: DB):
    """$IF %STAGES%==YES (case-sensitive): the model of every SOW at once, its variables and bounds by SOW; not with
    SENSIS (maindrv.mod 34: $IFI %SENSIS% == YES $SET STAGES Yes), whose solves are deterministic models."""
    return bool(db.ctl.get("STAGES_YES"))


def _ord(labels):
    return {k: i + 1 for i, k in enumerate(labels)}


def _rows(db: DB, name, where="true"):
    return db.q(f'select * from "{name}" where {where}')


def _write(db: DB, name, rows):
    """Replace the records of `name` by `rows` (tuples of labels [and value])."""
    db.clear(name)
    db.insert_rows(f'"{name}"', sorted(set(rows)) if db.sym[name].kind == "set" else rows)


# ---------------------------------------------------------------------------------------------------------------------
# prep_ext.stc

def prep_ext(db: DB, interp):
    """prep_ext.stc: the interpolation of the uncertain attributes, and the flags they set (preppm.mod 216)."""
    if not on(db):
        return
    require_empty(db, ["S_DAM_COST"], "damage costs by SOW with STAGES=YES (DAMAGE is not supported)")
    require_empty(db, ["S_UCOBJ"], "the tradeoff analysis of stochastic TIMES (S_UCOBJ, SW_LAMBDA)")
    if db.ctl.get("SENSIS"):
        # SENSIS: the demand projections and taxes of the SOW of each solve (eqcombal.mod 109, eqpeak.mod 81,
        # eqobjvar.mod 48: $IFI %STAGES%); the others reset by sensis.stc or read through the MX macros, not yet
        require_empty(db, ["S_NCAP_COST", "S_FLO_FUNC", "S_NCAP_AFS", "S_COM_FR", "S_CAP_BND", "S_FLO_CUM", "S_COM_CUM",
                           "S_COM_CUMNET", "S_COM_CUMPRD", "S_UC_RHS", "S_UC_RHSR", "S_UC_RHST", "S_UC_RHSRT", "S_UC_RHSTS",
                           "S_UC_RHSRTS", "S_CM_MAXCO2C", "S_CM_MAXC", "S_CM_CONST"],
                      "with SENSIS (sensis.stc, the MX macros of recurrin.stc)")
    if db.card("S_FLO_FUNC") and db.q1("select count(*) from S_FLO_FUNC f where in_RP_IRE(f.r, f.p)"):
        unsupported(db, "S_FLO_FUNC of a trade process with STAGES=YES (IRE_FLOSUM by SOW: cal_ire.mod 16, eqobjvar.mod 83)", ["S_FLO_FUNC"])
    if db.s.get("SW_LAMBDA"):
        unsupported(db, "SW_LAMBDA with STAGES=YES (the tradeoff analysis)", ["SW_LAMBDA"])
    if db.q1("select count(*) from S_UC_RHS where uc='OBJ1'"):
        unsupported(db, "S_UC_RHS of OBJ1 (the minimax regret of the tradeoff analysis)", ["S_UC_RHS"])
    F, P = interp.fillparm, interp.prepparm
    # --- $ BATINCLUDE fillparm S_COM_PROJ 'R' 'C,J,WW' ",'0','0','0'" MILESTONYR 1 'GE 0'
    F(db, "S_COM_PROJ", "T", None)
    # --- $ BATINCLUDE fillparm S_COM_TAX 'R' 'C,S,COM_VAR,CUR,J,WW' "" MILESTONYR 1 'GE 0'
    F(db, "S_COM_TAX", "T", None)
    # --- $ BATINCLUDE fillparm S_NCAP_COST 'R' 'P,J,WW' ",'0','0','0'" MILESTONYR 1 'GE 0'
    F(db, "S_NCAP_COST", "T", None)
    # --- $ IF DEFINED S_FLO_FUNC $BATINCLUDE fillparm S_FLO_FUNC R 'P,CG,CG2,J,WW' ",'0'" MILESTONYR 1 'GE 0'
    if db.card("S_FLO_FUNC"):
        F(db, "S_FLO_FUNC", "T", None)
    # --- $ IF DEFINED S_NCAP_AFS $BATINCLUDE fillparm S_NCAP_AFS R 'P,TS,J,WW' ",'0','0'" MILESTONYR 1 'GE 0'
    if db.card("S_NCAP_AFS"):
        F(db, "S_NCAP_AFS", "T", None)
    # --- $ IF DEFINED S_COM_FR   $BATINCLUDE fillparm S_COM_FR  R 'C,TS,J,WW' ",'0','0'" MILESTONYR 1 'GE 0'
    if db.card("S_COM_FR"):
        F(db, "S_COM_FR", "T", None)
    # --- $ BATINCLUDE prepparm S_CAP_BND 'R' 'P,BD,J,WW' ",'0'" MILESTONYR 'RTP(R,MILESTONYR,P)' 1
    P(db, "S_CAP_BND", "T", ("RTP", ("r", "p")), 1)
    # --- $ BATINCLUDE prepparm S_UC_RHSRT 'ALL_R,UC_N' 'L,J,WW' ",'0'" MILESTONYR 1 1
    #     $ BATINCLUDE prepparm S_UC_RHSRTS 'ALL_R,UC_N' 'TS,L,J,WW' "" MILESTONYR 1 1
    #     $ BATINCLUDE prepparm S_UC_RHST 'UC_N' 'L,J,WW' ",'0','0'" MILESTONYR 1 1
    #     $ BATINCLUDE prepparm S_UC_RHSTS 'UC_N' 'TS,L,J,WW' ",'0'" MILESTONYR 1 1
    for n in ("S_UC_RHSRT", "S_UC_RHSRTS", "S_UC_RHST", "S_UC_RHSTS"):
        P(db, n, "T", None, 1)
    # --- $ BATINCLUDE recurrin.stc MXPAR: the macros of S_NCAP_AFS / S_COM_FR (afmx, rtcs_fr, com_frmx in times_eq)
    # --- S_COM_CUM(R,'NET',ALLYEAR(BOHYEAR+BEOH(BOHYEAR)),LL(EOHYEAR+BEOH(EOHYEAR)),C,BD,J,WW) $= S_COM_CUMNET(..);
    #     S_COM_CUM(R,'PRD',...) $= S_COM_CUMPRD(..);   OPTION CLEAR=S_COM_CUMPRD,CLEAR=S_COM_CUMNET;
    f, yr = _years(db)
    for cv, src in (("NET", "S_COM_CUMNET"), ("PRD", "S_COM_CUMPRD")):
        db.put("S_COM_CUM", f"""select r, '{cv}' as cv, {f('y')} as y, {f('y2')} as y2, c, l, j, w, value from "{src}"
                                where in_REG(r) and {yr(f('y'))} and {yr(f('y2'))}""", zero="eps")
    db.clear("S_COM_CUMNET", "S_COM_CUMPRD")
    # --- S_COM_CUM(R,COM_VAR,ALLYEAR,LL,C,'LO',J,WW)$((S_COM_CUM(..'LO'..) EQ 0)$S_COM_CUM(..'LO'..)) = 0;
    db.remove("S_COM_CUM", where="l='LO' and value = 0")
    # --- RC_CUMCOM(R,COM_VAR,ALLYEAR,LL,C) $= SUM((BD,J,WW)$S_COM_CUM(R,COM_VAR,ALLYEAR,LL,C,BD,J,WW),YES);
    db.add("RC_CUMCOM", "select distinct r, cv, y, y2, c from S_COM_CUM")
    # --- LOOP((R,T,C,S,COM_VAR,CUR,J,WW)$S_COM_TAX(R,T,C,S,COM_VAR,CUR,J,WW),UC_COM('OBJ1',COM_VAR,'LHS',R,'0',C,ANNUAL,'UCN')=1);
    db.put("UC_COM", """select distinct 'OBJ1' as uc, cv, 'LHS' as side, r, '0' as y, c, 'ANNUAL' as s, 'UCN' as grp, 1 as value
                        from S_COM_TAX where in_MILESTONYR(y)""")
    # --- LOOP((R,T,P,BD,J,WW)$S_CAP_BND(R,T,P,BD,J,WW),RTP_VARP(R,T,P) = YES);
    db.add("RTP_VARP", "select distinct r, y, p from S_CAP_BND where in_REG(r) and in_MILESTONYR(y) and in_PRC(p)")
    # --- * collect transformation tuples:  $ IF DEFINED S_FLO_FUNC OPTION RP_FFSGG <= S_FLO_FUNC;
    if db.card("S_FLO_FUNC"):
        db.add("RP_FFSGG", "select distinct r, p, cg, cg2 from S_FLO_FUNC")
    # --- Set flags for Phased UC_N
    #     UC_R_SUM(R,'OBJZ') = YES; UC_R_EACH(R,'OBJZ') = YES; UC_R_SUM(R,'OBJ1') = YES;
    #     UC_T_SUM(R,'OBJZ',T) = YES; UC_T_SUM(R,'OBJ1',MIYR_1) = YES;
    db.add("UC_R_SUM", "select r, 'OBJZ' as uc from REG")
    db.add("UC_R_EACH", "select r, 'OBJZ' as uc from REG")
    db.add("UC_R_SUM", "select r, 'OBJ1' as uc from REG")
    db.add("UC_T_SUM", "select r, 'OBJZ' as uc, y from REG, MILESTONYR")
    db.add("UC_T_SUM", "select r, 'OBJ1' as uc, y from REG, MIYR_1")
    # --- LOOP((UC_N,WW)$S_UCOBJ(UC_N,WW),UC_RHS(UC_N,'N')$(NOT UC_RHS(UC_N,'N')) = -1);   (S_UCOBJ refused)
    # --- SW_PARM = CARD(S_COM_PROJ) + CARD(S_CAP_BND) + CARD(S_COM_CUMPRD) + CARD(S_COM_CUMNET);
    #     SW_PARM = SW_PARM + CARD(S_CM_CONST) + CARD(S_CM_MAXC);   (the two CUM ones are cleared above)
    db.s["SW_PARM"] = float(db.card("S_COM_PROJ") + db.card("S_CAP_BND") + db.card("S_CM_CONST") + db.card("S_CM_MAXC"))
    # --- UC_RHS(UC_N,'UP')$((NOT UC_RHS(UC_N,'UP'))$SUM((LIM,J,WW)$S_UC_RHS(UC_N,LIM,J,WW),1)) = INF;
    #     UC_RHSR(R,UC_N,'UP')$((NOT UC_RHSR(R,UC_N,'UP'))$SUM((LIM,J,WW)$S_UC_RHSR(R,UC_N,LIM,J,WW),1)) = INF;
    #     UC_RHST(UC_N,T,'UP')$((NOT UC_RHST(UC_N,T,'UP'))$SUM((LIM,J,WW)$S_UC_RHST(UC_N,T,LIM,J,WW),1)) = INF;
    #     UC_RHSRT(R,UC_N,T,'UP')$((NOT UC_RHSRT(R,UC_N,T,'UP'))$SUM((LIM,J,WW)$S_UC_RHSRT(R,UC_N,T,LIM,J,WW),1)) = INF;
    #     UC_RHSTS(UC_N,T,S,'UP')$((NOT UC_RHSTS(UC_N,T,S,'UP'))$SUM((LIM,J,WW)$S_UC_RHSTS(UC_N,T,S,LIM,J,WW),1)) = INF;
    #     UC_RHSRTS(R,UC_N,T,S,'UP')$((NOT UC_RHSRTS(R,UC_N,T,S,'UP'))$SUM((LIM,J,WW)$S_UC_RHSRTS(R,UC_N,T,S,LIM,J,WW),1)) = INF;
    for n, k in (("UC_RHS", "uc"), ("UC_RHSR", "r, uc"), ("UC_RHST", "uc, y"), ("UC_RHSRT", "r, uc, y"),
                 ("UC_RHSTS", "uc, y, s"), ("UC_RHSRTS", "r, uc, y, s")):
        on_ = " and ".join(f"u.{c.strip()}=s.{c.strip()}" for c in k.split(","))
        ycond = "and in_MILESTONYR(s.y)" if "y" in k else ""
        rcond = "and in_REG(s.r)" if k.startswith("r") else ""
        db.put(n, f"""select distinct {', '.join('s.' + c.strip() for c in k.split(','))}, 'UP' as l, 'Infinity'::double as value
                      from S_{n} s where not exists(select 1 from {n} u where {on_} and u.l='UP') {ycond} {rcond}""")
    # --- UC_DYNBND('OBJ1','N')=YES;
    db.add("UC_DYNBND", "select 'OBJ1' as uc, 'N' as l")


def _years(db: DB):
    """BOHYEAR+BEOH(BOHYEAR) as SQL of a column (BOH: the year of BOTIME, EOH: that of EOTIME), and the test that it is a
    year of LL (not '0'), as bounds.py writes them."""
    from .bounds import _eoh
    bot, eot = str(db.ctl["BOTIME"]), str(db.ctl["EOTIME"])
    f = lambda c: _eoh(c).replace("{BOT}", bot).replace("{EOT}", eot)
    yr = lambda c: f"in_ALLYEAR({c}) and {c} <> '0'"
    return f, yr


# ---------------------------------------------------------------------------------------------------------------------
# stages.stc

def stages(db: DB):
    """stages.stc: the tree of SOWs, the maps of periods to SOWs, the uncertain attributes merged into stage '1'
    (maindrv.mod 65, after ppm_ext)."""
    if not on(db):
        return
    s = db.s
    # SET AUXSOW(ALLSOW) / 1 /;   (stages.stc 17)
    db.declare("AUXSOW", "set", ["ALLSOW"])
    db.assign("AUXSOW", "select '1' as w")
    J = [j for (j,) in db.q("select j from J")]                     # '1', '2', ... in order
    jo = _ord(J)
    WW = [w for (w,) in db.q("select w from ALLSOW")]
    wo = _ord(WW)
    T = [y for (y,) in db.q("select y from MILESTONYR order by yv(y)")]
    yv = lambda y: int(y)
    # stages.stc 22: OPTION SUC_L<UC_T_SUCC; SUC_L(UC_ON)$SUC_L(UC_ON)=(NOT UC_DYNDIR(UC_ON,'RHS'));
    db.put("SUC_L", "select distinct r, uc, 1 as value from UC_T_SUCC")
    db.remove("SUC_L", where="exists(select 1 from UC_DYNDIR d where d.r=SUC_L.r and d.uc=SUC_L.uc and d.side='RHS')")

    subs = {(j, w): v for j, w, v in _rows(db, "SW_SUBS")}
    sprob = {(j, w): v for j, w, v in _rows(db, "SW_SPROB")}
    prob = {w: v for w, v in _rows(db, "SW_PROB")}
    start = {j: v for j, v in _rows(db, "SW_START")}
    # --- SW_SUBS('1',WW)$(ORD(WW) > 1) = 0;
    subs = {k: v for k, v in subs.items() if not (k[0] == "1" and wo[k[1]] > 1)}
    # --- IF(SW_SUBS('1','1') EQ 0,
    #       IF(CARD(SW_SUBS)+CARD(SW_SPROB) EQ 0, SW_SUBS('1','1') = MAX(1,SMAX(WW$SW_PROB(WW),ORD(WW)));
    #       ELSE SW_SUBS('1','1') = MAX(1,SMAX(WW$(SW_SPROB('2',WW)+SW_SUBS('2',WW)),ORD(WW)))));
    if not subs.get(("1", "1")):
        if not subs and not sprob:
            subs[("1", "1")] = max([1] + [wo[w] for w, v in prob.items() if v])
        else:
            subs[("1", "1")] = max([1] + [wo[w] for w in WW if sprob.get(("2", w)) or subs.get(("2", w))])
    # --- LAST_VAL = SMAX((J,WW)$SW_SUBS(J,WW),ORD(J));
    last = max(jo[j] for (j, w), v in subs.items() if v)
    # --- LOOP(JJ(J-1)$(ORD(J) LE LAST_VAL), F = MAX(1,SW_SUBS(J,'1')); Z = SUM(WW$SW_SUBS(JJ,WW),SW_SUBS(JJ,WW));
    #       LOOP(WW$(ORD(WW) LE Z), IF(NOT SW_SUBS(J,WW), SW_COPY(J,WW)$(ORD(WW) > 1) = YES; SW_SUBS(J,WW) = F;)));
    copy = set()
    for j in J[1:last]:
        jj = J[jo[j] - 2]
        f = max(1, subs.get((j, "1"), 0))
        z = sum(v for (a, w), v in subs.items() if a == jj)
        for w in WW[:int(z)]:
            if not subs.get((j, w)):
                if wo[w] > 1:
                    copy.add((j, w))
                subs[(j, w)] = f
    # --- LOOP((J,ALLSOW)$SW_SUBS(J,ALLSOW), IF(ORD(ALLSOW) EQ 1, F = 0); Z = SW_SUBS(J,ALLSOW)+F;
    #       SW_CHILD(J,ALLSOW,WW)$((ORD(WW) LE Z)*(ORD(WW) > F)) = YES; F = Z;);
    child = {}                                  # (j, parent) -> [children]
    f = 0
    for j in J:
        for a in WW:
            v = subs.get((j, a))
            if not v:
                continue
            if wo[a] == 1:
                f = 0
            z = v + f
            child[(j, a)] = [w for w in WW if f < wo[w] <= z]
            f = z
    # --- LOOP(SW_CHILD(J,ALLSOW,WW), SOW(WW) = YES);
    sow = sorted({w for ws in child.values() for w in ws}, key=wo.get)
    sowset = set(sow)
    # --- SW_PHASE = 0;  UC_TS_SUM(R,'OBJZ',S) = NO;  UC_TS_EACH(R,'OBJZ',S) = NO;
    s["SW_PHASE"] = 0.0
    db.remove("UC_TS_SUM", where="uc='OBJZ'")
    db.remove("UC_TS_EACH", where="uc='OBJZ'")
    # IF(SUM((UC_N,SOW)$S_UCOBJ(UC_N,SOW),1), ... ELSEIF SUM((J,SOW)$S_UC_RHS('OBJ1','FX',J,SOW),1), ...): both refused
    # --- $IF NOT %STAGES%==YES SW_START('1') = 9999; SW_LAMBDA = 0; SW_PARM = 0;
    #     (SENSIS: MY_FYEAR 9999 below puts the start of every stage at the first milestone, a SOW per solve)
    if not tagged(db):
        start["1"] = 9999.0
        s["SW_LAMBDA"] = 0.0
        s["SW_PARM"] = 0.0
    # --- FOR(Z = LAST_VAL-1 DOWNTO 0, LOOP((SAMEAS(J-Z,'1'),JJ(J+1)),
    #       IF(Z=LAST_VAL-1,SW_TREE(J,ALLSOW,SOW)$SW_CHILD(J,ALLSOW,SOW) = YES;
    #       ELSE LOOP(SW_CHILD(J,ALLSOW,WW),SW_TREE(J,ALLSOW,SOW)$SW_TREE(JJ,WW,SOW) = YES;))));
    tree = set()                                # (j, node, finest)
    for z in range(last - 1, -1, -1):
        j, jn = J[z], J[z + 1]
        for (a_j, a), ws in child.items():
            if a_j != j:
                continue
            for w in ws:
                if z == last - 1:
                    if w in sowset:
                        tree.add((j, a, w))
                else:
                    tree.update([(j, a, x) for (b_j, b, x) in tree if b_j == jn and b == w])
    # --- MY_FYEAR = SW_START('1'); Z = 0; SW_START('1') = 0;  SW_START(J)$(ORD(J) > LAST_VAL+1) = 0;
    my_fyear = start.get("1", 0.0)
    start["1"] = 0.0
    start = {j: v for j, v in start.items() if jo[j] <= last + 1 and v}
    # --- LOOP(MIYR_1(TT), F = -1;
    #       LOOP(J$(ORD(J) LE LAST_VAL+1),
    #         MY_F = SW_START(J);
    #         IF(NOT MY_F, F = F+1; Z = MAX(Z+1,YEARVAL(TT+F)); SW_START(J) = Z;
    #         ELSEIF MY_F > Z, Z = MY_F; F = MAX(1,F,SUM(T$(YEARVAL(T) < MY_F),1));
    #           SW_START(J) = MAX(YEARVAL(TT+(F-1))+1,Z);
    #         ELSE SW_START(J) = SW_START(J-1));
    #     ));
    yt = lambda i: yv(T[i]) if 0 <= i < len(T) else 0     # YEARVAL(TT+i), TT the first milestone; 0 off the set
    f, z = -1, 0
    for j in J[:last + 1]:
        my_f = start.get(j, 0.0)
        if not my_f:
            f += 1
            z = max(z + 1, yt(f))
            start[j] = z
        elif my_f > z:
            z = my_f
            f = max(1, f, sum(1 for t in T if yv(t) < my_f))
            start[j] = max(yt(f - 1) + 1, z)
        else:
            start[j] = start.get(J[jo[j] - 2], 0.0) if jo[j] > 1 else 0.0
        if not start[j]:
            del start[j]
    # --- LOOP(J$SW_START(J), SW_TSTG(T,J)$(SW_START(J) LE YEARVAL(T)) = YES);
    tstg = {(t, j) for j in J if start.get(j) for t in T if start[j] <= yv(t)}
    # --- IF(MY_FYEAR GE SW_START('2'), SW_START(J)$((SW_START(J) LE MY_FYEAR)$SW_START(J)) = MIYR_V1);
    if my_fyear >= start.get("2", 0.0):
        for j in list(start):
            if start[j] <= my_fyear:
                start[j] = s["MIYR_V1"]
    # --- SW_DESC(J,WW) = SUM(SW_TREE(J,WW,SOW),1);
    desc = {}
    for (j, a, w) in tree:
        desc[(j, a)] = desc.get((j, a), 0) + 1
    # --- LOOP(SAMEAS(WW,'1'), F = 0;
    #       LOOP((J,SOW)$SW_SUBS(J,SOW), IF(ORD(J) NE F, Z = 0; F = ORD(J)); SW_STAGE(J,WW+Z) = YES; Z = Z + SW_DESC(J,SOW)));
    stage = set()
    f = 0
    for j in J:
        for a in sow:
            if not subs.get((j, a)):
                continue
            if jo[j] != f:
                z, f = 0, jo[j]
            if z < len(WW):
                stage.add((j, WW[z]))
            z += desc.get((j, a), 0)
    # --- LOOP((JJ(J-1),ALLSOW)$SW_SUBS(JJ,ALLSOW), Z=0; MY_F=0;
    #       IF(ORD(ALLSOW) EQ 1, F=0; ELSE F=F+CNT); CNT=SW_SUBS(JJ,ALLSOW);
    #       LOOP(SW_CHILD(JJ,ALLSOW,WW)$SW_SPROB(J,WW), Z=Z+SW_SPROB(J,WW); MY_F=MY_F+1);
    #       IF(SW_COPY(JJ,ALLSOW)$(NOT MY_F), SW_SPROB(J,WW)$SW_CHILD(JJ,ALLSOW,WW) = SW_SPROB(J,WW-F);
    #       ELSE SW_SPROB(J,WW)$((NOT SW_SPROB(J,WW))*SW_CHILD(JJ,ALLSOW,WW)) = MAX(0,1-Z)/(CNT-MY_F)));
    cnt = s.get("CNT", 0.0)
    f = 0
    for j in J[1:]:
        jj = J[jo[j] - 2]
        for a in WW:
            v = subs.get((jj, a))
            if not v:
                continue
            z, my_f = 0.0, 0
            f = 0 if wo[a] == 1 else f + cnt
            cnt = v
            kids = child.get((jj, a), [])
            for w in kids:
                if (j, w) in sprob:                 # (an EPS probability, given as 0, is a record)
                    z += sprob[(j, w)]
                    my_f += 1
            if (jj, a) in copy and not my_f:
                for w in kids:
                    src = WW[wo[w] - 1 - int(f)] if wo[w] - int(f) >= 1 else None
                    if src and (j, src) in sprob:
                        sprob[(j, w)] = sprob[(j, src)]
                    else:
                        sprob.pop((j, w), None)
            else:
                for w in kids:
                    if (j, w) not in sprob:
                        val = max(0.0, 1 - z) / (cnt - my_f)
                        if val:
                            sprob[(j, w)] = val
    s["CNT"] = float(cnt)
    # --- LOOP(SW_COPY(JJ(J-1),W), F=0; LOOP(SW_CHILD(JJ,W,WW), IF(F=0,F=ORD(WW)-1); SW_CPMAP(J,WW,WW-F)=YES));
    cpmap = set()
    for j in J[1:]:
        jj = J[jo[j] - 2]
        for a in WW:
            if (jj, a) not in copy:
                continue
            f = 0
            for w in child.get((jj, a), []):
                if f == 0:
                    f = wo[w] - 1
                if wo[w] - f >= 1:
                    cpmap.add((j, w, WW[wo[w] - f - 1]))
    # --- SW_SPROB('1','1') = 1;
    sprob[("1", "1")] = 1.0
    # --- LOOP((J,WW)$SW_SUBS(J,WW), Z = SUM(SOW$SW_CHILD(J,WW,SOW),SW_SPROB(J+1,SOW));
    #       IF(Z NE 1,SW_SPROB(J+1,SOW)$SW_CHILD(J,WW,SOW) = SW_SPROB(J+1,SOW)/Z;));
    for j in J[:-1]:
        jn = J[jo[j]]
        for a in WW:
            if not subs.get((j, a)):
                continue
            kids = [w for w in child.get((j, a), []) if w in sowset]
            z = sum(sprob.get((jn, w), 0.0) for w in kids)
            if z != 1:
                for w in kids:
                    if (jn, w) in sprob:
                        sprob[(jn, w)] = sprob[(jn, w)] / z          # (EPS / z is EPS)
    # --- LOOP(SAMEAS(J-LAST_VAL,'1'), SW_TREE(J,SOW,SOW) = YES);   OPTION SW_REV < SW_TREE;
    jl = J[last]
    tree.update((jl, w, w) for w in sow)
    rev = {(w, j, a) for (j, a, w) in tree}
    # --- SW_PROB(SOW)$(NOT SW_PROB(SOW)) = PROD(SW_TREE(JJ,ALLSOW,SOW),SW_SPROB(JJ,ALLSOW));
    for w in sow:
        if not prob.get(w):
            p = 1.0
            for (j, a, x) in sorted(tree, key=lambda k: (jo[k[0]], wo[k[1]])):
                if x == w:
                    p *= sprob.get((j, a), 0.0)
            prob[w] = p
    # --- SW_PROB(ALLSOW)$(SW_PROB(ALLSOW) LE 0) = 0;  Z = SUM(ALLSOW,SW_PROB(ALLSOW));
    #     IF(Z EQ 0, Z = 1; SW_PROB('1') = Z);   SW_PROB(SOW) = SW_PROB(SOW)/Z;
    prob = {w: v for w, v in prob.items() if v > 0}
    z = 0.0
    for w in sorted(prob, key=wo.get):
        z += prob[w]
    if z == 0:
        z = 1.0
        prob["1"] = z
    for w in sow:
        if w in prob:
            prob[w] = prob[w] / z
    prob = {w: v for w, v in prob.items() if v}
    # --- LOOP(SAMEAS(J,'1'), SW_STAGE(J+LAST_VAL,SOW) = YES;);
    #     LOOP(J$(ORD(J) LE LAST_VAL), SW_STAGE(J+1,SOW)$SW_STAGE(J,SOW) = YES;);
    stage.update((jl, w) for w in sow)
    for j in J[:last]:
        jn = J[jo[j]]
        stage.update([(jn, w) for (a, w) in stage if a == j and w in sowset])
    # --- LOOP(SW_STAGE(J,SOW), SW_T(T,SOW)$(SW_START(J) LE YEARVAL(T)) = YES);
    swt = {(t, w) for (j, w) in stage if w in sowset for t in T if start.get(j, 0.0) <= yv(t)}
    # --- LOOP(T, F = 0;
    #       LOOP(SW_T(T,WW), Z = ORD(WW);
    #         SW_TSW(SOW(ALLSOW),T,WW+(F-Z))$((ORD(ALLSOW) GE F)*(ORD(ALLSOW) < Z)) = YES;  F = Z;);
    #       SW_TSW(SOW(ALLSOW),T,WW)$((ORD(WW) EQ F)*(ORD(ALLSOW) GE F)) = YES;);
    tsw = set()
    for t in T:
        f = 0
        for w in sorted((w for (u, w) in swt if u == t), key=wo.get):
            z = wo[w]
            if f >= 1:
                tsw.update((a, t, WW[f - 1]) for a in sow if f <= wo[a] < z)
            f = z
        if f >= 1:
            tsw.update((a, t, WW[f - 1]) for a in sow if wo[a] >= f)
    # --- SW_TPROB(T,W) = SUM(SW_TSW(SOW,T,W),SW_PROB(SOW));
    tprob = {}
    for (a, t, w) in sorted(tsw, key=lambda k: wo[k[0]]):
        if a in prob:
            tprob[(t, w)] = tprob.get((t, w), 0.0) + prob[a]
    # --- SW_T(T,ALLSOW)$(SW_TPROB(T,ALLSOW) EQ 0) = NO;  SW_TSW(SOW,T,WW)$(NOT SW_T(T,WW)) = NO;
    swt = {(t, w) for (t, w) in swt if tprob.get((t, w))}
    tsw = {(a, t, w) for (a, t, w) in tsw if (t, w) in swt}
    # solve.stc 18: DOITER = (SUM(SW_T(MIYR_1,WW),1) GT 1) OR ..: with several SOWs in the first period TIMES solves each
    # SOW on its own ("Decomposed deterministic scenarios"), not one stochastic model; not with SPINES:
    #   solve.stc 19  $IFI %SPINES%==YES DOITER = 0;
    if sum(1 for (t, w) in swt if t == T[0]) > 1 and not db.ctl.get("SPINES") and tagged(db):
        unsupported(db, "STAGES with several states of the world in the first period (TIMES solves each SOW on its own)", ["SW_START"])
    # --- SW_MAP(SW_T(T,WW),J,SOW)$(SW_TSTG(T,J)*SW_TREE(J,SOW,WW)) = YES;
    swmap = {(t, w, j, a) for (t, w) in swt for (j, a, x) in tree if x == w and (t, j) in tstg}

    _write(db, "SW_SUBS", [(j, w, float(v)) for (j, w), v in subs.items() if v])
    _write(db, "SW_COPY", list(copy))
    _write(db, "SW_CHILD", [(j, a, w) for (j, a), ws in child.items() for w in ws])
    _write(db, "SOW", [(w,) for w in sow])
    _write(db, "SW_TREE", list(tree))
    _write(db, "SW_START", [(j, float(v)) for j, v in start.items() if v])
    _write(db, "SW_TSTG", list(tstg))
    _write(db, "SW_DESC", [(j, a, float(v)) for (j, a), v in desc.items()])
    _write(db, "SW_STAGE", list(stage))
    _write(db, "SW_SPROB", [(j, w, v) for (j, w), v in sprob.items()])
    _write(db, "SW_CPMAP", list(cpmap))
    _write(db, "SW_REV", list(rev))
    _write(db, "SW_PROB", [(w, v) for w, v in prob.items()])
    _write(db, "SW_T", list(swt))
    _write(db, "SW_TSW", list(tsw))
    _write(db, "SW_TPROB", [(t, w, v) for (t, w), v in tprob.items() if (t, w) in swt])
    _write(db, "SW_MAP", list(swmap))
    s["LAST_VAL"] = float(last)
    s["MY_FYEAR"] = float(my_fyear)

    # --- LOOP(R, SW_UCT(UC_N,SW_T(T,SOW))$(UC_T_SUCC(R,UC_N,T)$UC_DYNDIR(R,UC_N,'RHS'))  = YES;
    #       LOOP(SW_T(T+1,SOW),SW_UCT(UC_N,T,SOW)$(UC_T_SUCC(R,UC_N,T)*(NOT UC_DYNDIR(R,UC_N,'RHS'))) = YES;));
    db.add("SW_UCT", """select u.uc, u.y, w.w from UC_T_SUCC u join SW_T w on w.y=u.y
                        where exists(select 1 from UC_DYNDIR d where d.r=u.r and d.uc=u.uc and d.side='RHS')""")
    db.add("SW_UCT", """select u.uc, u.y, w.w from UC_T_SUCC u
                        join (select y, lead(y) over (order by yv(y)) as y1 from MILESTONYR) n on n.y=u.y
                        join SW_T w on w.y=n.y1
                        where not exists(select 1 from UC_DYNDIR d where d.r=u.r and d.uc=u.uc and d.side='RHS')""")
    # --- S_FLO_CUM(R,P,C,BOHYEAR+BEOH(BOHYEAR),EOHYEAR+BEOH(EOHYEAR),BD,J,SOW) $= S_FLO_CUM(R,P,C,BOHYEAR,EOHYEAR,BD,J,SOW);
    #     S_FLO_CUM(R,P,C,BOHYEAR,EOHYEAR,BD,J,SOW)$(NOT LL(BOHYEAR)*LL(EOHYEAR)) = 0;
    #     RPC_CUMFLO(RP(R,P),C,ALLYEAR,LL) $= SUM((BD,J,SOW)$S_FLO_CUM(R,P,C,ALLYEAR,LL,BD,J,SOW),YES);
    f_, yr = _years(db)
    db.put("S_FLO_CUM", f"select r, p, c, {f_('u')} as u, {f_('u2')} as u2, l, j, w, value from S_FLO_CUM where in_SOW(w)", zero="eps")
    db.zap("S_FLO_CUM", f"not ({yr('u')} and {yr('u2')})")
    db.add("RPC_CUMFLO", "select distinct r, p, c, u as y, u2 as y2 from S_FLO_CUM where in_RP(r,p)")
    # --- SUPERYR(PERIODYR(T,LL)) = YES;  LOOP(MIYR_1(T),SUPERYR(T--1,LL)$(YEARVAL(LL) > MIYR_VL) = YES);
    db.assign("SUPERYR", "select y, y2 from PERIODYR where in_MILESTONYR(y)")
    db.add("SUPERYR", f"""select (select y from MILESTONYR order by yv(y) desc limit 1) as y, y as y2 from ALLYEAR
                          where y <> '0' and yv(y) > {s['MIYR_VL']}""")
    # --- the uncertain attributes (fillsow.stc)
    fillsow(db, "COM_PROJ", "T", absolute=False)
    fillsow(db, "COM_TAX", "T", absolute=True, period="SW_T")
    fillsow(db, "NCAP_COST", "T", absolute=False)
    fillsow(db, "CAP_BND", "T", absolute=True, period="SW_T")
    fillsow(db, "COM_CUM", "LL", absolute=True, period="SUPERYR", baseline=True)
    fillsow(db, "FLO_CUM", "LL", absolute=True, period="SUPERYR", baseline=True)
    for n in ("UC_RHST", "UC_RHSRT", "UC_RHSTS", "UC_RHSRTS"):
        fillsow(db, n, "T", absolute=True, period="SW_T")
    fillsow(db, "UC_RHS", "", absolute=True, period="YES", baseline=True)
    fillsow(db, "UC_RHSR", "", absolute=True, period="YES", baseline=True)
    db.clear("SUPERYR")
    # --- $ BATINCLUDE pp_lvlfc.mod S_COM_TAX C COM_TS ',COM_VAR,CUR,J,WW' "" ALL_TS T RC(R,C)$(ORD(J)=1)
    from ..lvl import lvlfc
    lvlfc(db, "S_COM_TAX", ["c"], "COM_TS", "MILESTONYR", "in_RC(a.r,a.c) and a.j='1'")
    # --- S_COM_TAX(RTC(R,T,C),S,COM_VAR,CUR,'1',W)$(NOT SW_T(T,W)) $= SUM(SW_TSW(W,T,WW),S_COM_TAX(RTC,S,COM_VAR,CUR,'1',WW));
    db.put("S_COM_TAX", """select x.r, x.y, x.c, x.s, x.cv, x.cur, '1' as j, m.w, x.value from S_COM_TAX x
                           join SW_TSW m on m.y=x.y and m.w2=x.w
                           where x.j='1' and in_RTC(x.r,x.y,x.c) and not in_SW_T(x.y,m.w)""", zero="eps")
    # --- the uncertain NCAP_COST: OPTION RVP < S_NCAP_COST;
    #     OBJ_SIC(RVP(R,T,P),SOW)$SW_T(T,SOW) = PROD(SW_MAP(T,SOW,J,WW)$S_NCAP_COST(R,T,P,J,WW),S_NCAP_COST(R,T,P,J,WW))-1;
    #     OPTION CLEAR=RVP,CLEAR=TRACKP,CLEAR=S_NCAP_COST;
    db.put("OBJ_SIC", """select k.r, k.y, k.p, m.ww as w, product(x.value) - 1 as value
                         from (select distinct r, y, p from S_NCAP_COST) k join SW_MAP m on m.y=k.y
                         join S_NCAP_COST x on x.r=k.r and x.y=k.y and x.p=k.p and x.j=m.j and x.w=m.ww2
                         group by k.r, k.y, k.p, m.ww""")
    db.clear("S_NCAP_COST")
    if db.card("S_FLO_FUNC") and tagged(db):      # stages.stc 220: $IF %SENSIS%==YES $GOTO DIDFUNC (sensis.stc 29-37)
        flo_func(db)
    if db.card("S_NCAP_AFS"):
        ncap_afs(db)
    if db.card("S_COM_FR"):
        com_fr(db)
    # (port-only SW_SENSIS: the equations build one deterministic model per first-period SOW, solve.stc 35-52)
    if db.ctl.get("SENSIS"):
        db.declare("SW_SENSIS", "par", [])
        db.s["SW_SENSIS"] = 1.0


def spines_sets(db: DB):
    """SPINES (recurrin.stc 52-124, eqmain.mod 30): every SOW has the capacity, the investment, fixed and salvage costs
    of SOW '1'; the sets of that, and %SCUM% (SOLVEDA 1: the cumulative constraints once, as expected values).
    Nothing without SPINES."""
    if not db.ctl.get("SPINES"):
        return
    # --- SET OBJSW1(OBV);  OBJSW1('OBJINV')=YES;  OBJSW1('OBJFIX')=YES;  OBJSW1('OBJSAL')=YES;
    db.declare("OBJSW1", "set", ["OBV"])
    _write(db, "OBJSW1", [("OBJINV",), ("OBJFIX",), ("OBJSAL",)])
    # --- SET UCRTPSW1(UC_GRPTYPE,WW);  UCRTPSW1('ACT',SOW) = YES;  UCRTPSW1('CAP','1') = YES;  UCRTPSW1('NCAP','1') = YES;
    db.declare("UCRTPSW1", "set", ["UC_GRPTYPE", "ALLSOW"])
    _write(db, "UCRTPSW1", [("ACT", w) for (w,) in db.q("select * from SOW")] + [("CAP", "1"), ("NCAP", "1")])
    # --- $IF %SOLVEDA%==1 $GOTO DYQAGG  ...  $LABEL DYQAGG  $SETGLOBAL SCUM 1
    #     (port-only SW_SCUM: 1 when the cumulative constraints and their variables are those of SOW '1', weighted by
    #     SW_TPROB; recurrin.stc 96-123, eqcumcom.mod, eqcumflo.mod, eqbndcst.mod, equcwrap.mod)
    db.declare("SW_SCUM", "par", [])
    db.s["SW_SCUM"] = 1.0 if str(db.env.get("SOLVEDA", "")).strip().strip("'\"") == "1" else 0.0


def com_fr(db: DB):
    """stages.stc 250-271: the uncertain COM_FR. S_COM_FR(R,T,C,S,'1',W), the multiplier less 1 of COM_FR in SOW W
    (recurrin.stc 49: COM_FRMX = COM_FR*(1+S_COM_FR(R,T,C,S,'1',SOW))), and RCS_SSFR(R,C,S,TS,W,LL), the change of
    RTCS_FR(R,T,C,S,TS) in SOW W, LL the period or '0' for the part shared by the periods of stage 2 on (recurrin.stc 48:
    RTCS_FR = RTCS_FRMX + SUM(SW_T2W(SOW,T,W,T0),RCS_SSFR(R,C,S,TS,W,T0))). For the equations, RTCS_SFRW(R,T,C,S,TS,W):
    that sum for the SOW W that represents the row's SOW in T."""
    J = [j for (j,) in db.q("select j from J")]
    stg2 = {y for (y,) in db.q("select y from SW_TSTG where j='2'")}
    # --- T0(T)=YES; T0('0')=YES; SW_T2W(SW_TSW(SOW,T,WW),T)=YES; SW_T2W(SW_TSW(SOW,T,WW),'0')$SW_TSTG(T,'2')=YES;
    db.add("T0", "select y from MILESTONYR union all select '0' as y")
    db.add("SW_T2W", """select w as ww, y, w2 as ww2, y as y2 from SW_TSW where in_MILESTONYR(y)
                        union all select w as ww, y, w2 as ww2, '0' as y2 from SW_TSW where in_SW_TSTG(y, '2')""")
    swmap = {}
    for y, w, j, w2 in db.q("select y, ww, j, ww2 from SW_MAP"):
        swmap.setdefault((y, j), []).append((w, w2))
    given = {}
    for r, y, c, s, j, w, x in db.q("select r, y, c, s, j, w, value from S_COM_FR"):
        given.setdefault((y, j, w), []).append((r, c, s, x))
    # --- T0(T)=YES; T0('0')=YES; SW_T2W(SW_TSW(SOW,T,WW),T)=YES; SW_T2W(SW_TSW(SOW,T,WW),'0')$SW_TSTG(T,'2')=YES;
    #     LOOP(J, RTCS_SFR(R,T,C,S,W,S) $= SUM(SW_MAP(T,W,J,WW),S_COM_FR(R,T,C,S,J,WW)));
    sfr = {}                                                       # (r, t, c, s, w) -> RTCS_SFR(R,T,C,S,W,S)
    for j in J:
        tot = {}
        for (y, jj), pairs in swmap.items():
            if jj != j:
                continue
            for (w, w2) in pairs:
                for (r, c, s, x) in given.get((y, j, w2), ()):
                    tot[(r, y, c, s, w)] = tot.get((r, y, c, s, w), 0.0) + x
        sfr.update({k: x for k, x in tot.items() if x})
    # --- RTCS_SFR(R,T,C,S,W,S)$RTCS_SFR(R,T,C,S,W,S) = RTCS_SFR(R,T,C,S,W,S)-1;   OPTION CLEAR=S_COM_FR;
    sfr = {k: x - 1 for k, x in sfr.items()}
    db.clear("S_COM_FR")
    cfr = {(r, y, c, s): x for r, y, c, s, x in db.q("select r, y, c, s, value from COM_FR")}
    parents, children = {}, {}
    for r, a, b in db.q("select r, s, s2 from RS_BELOW1"):
        parents.setdefault((r, b), []).append(a)
        children.setdefault((r, a), []).append(b)
    group = {}
    for r, tsl, s in db.q("select r, tsl, s from TS_GROUP"):
        group.setdefault((r, tsl.upper()), set()).add(s)
    levels = [l.upper() for (l,) in db.q("select * from TSLVL")]
    # --- RTCSW(R,T,C,S+STOA(S),W)$RTCS_SFR(R,T,C,S,W,S) = YES;     (S+STOA(S): ANNUAL)
    #     RTCSW(R,T,C,S,W)$((COM_FR(R,T,C,S) > 0)$RTCSW(R,T,C,'ANNUAL',W)) = YES;
    ann = {(r, y, c, w) for (r, y, c, s, w) in sfr}
    rtcsw = {(r, y, c, "ANNUAL", w) for (r, y, c, w) in ann}
    for (r, y, c, s), x in cfr.items():
        if x > 0:
            for (r2, y2, c2, w) in ann:
                if (r2, y2, c2) == (r, y, c):
                    rtcsw.add((r, y, c, s, w))
    # --- * Fill down the multipliers
    #     RTCS_SFR(RTCSW(R,T,C,S,W),S)$((NOT RTCS_SFR(RTCSW,S))$TS_GROUP(R,'WEEKLY',S)) = SUM(RS_BELOW1(R,TS,S),RTCS_SFR(R,T,C,TS,W,TS));
    #     RTCS_SFR(RTCSW(R,T,C,S,W),S)$((NOT RTCS_SFR(RTCSW,S))$TS_GROUP(R,'DAYNITE',S)) = SUM(RS_BELOW1(R,TS,S),RTCS_SFR(R,T,C,TS,W,TS));
    for lvl in ("WEEKLY", "DAYNITE"):
        new = {}
        for k in sorted(rtcsw):
            r, y, c, s, w = k
            if not sfr.get(k) and s in group.get((r, lvl), ()):
                new[k] = sum(sfr.get((r, y, c, a, w), 0.0) for a in parents.get((r, s), ()))
        sfr.update(new)
    # --- * Sum up COM_FR for all commodities that have it defined
    #     FOR(Z=3 DOWNTO 1,LOOP(TSLVL$(ORD(TSLVL)=Z),
    #       RTCS_SFR(RTCSW(R,T,C,S,W),S)$TS_GROUP(R,TSLVL,S) =
    #         SUM(RS_BELOW1(R,S,TS),(1+RTCS_SFR(R,T,C,TS,W,TS))*COM_FR(R,T,C,TS))/COM_FR(R,T,C,S)-1;));
    for z in (3, 2, 1):
        lvl = levels[z - 1]
        new = {}
        for k in sorted(rtcsw):
            r, y, c, s, w = k
            if s in group.get((r, lvl), ()):
                tot = sum((1 + sfr.get((r, y, c, b, w), 0.0)) * cfr.get((r, y, c, b), 0.0) for b in children.get((r, s), ()))
                new[k] = tot / cfr[(r, y, c, s)] - 1
        sfr.update(new)
    sfr = {k: x for k, x in sfr.items() if x}
    # --- S_COM_FR(R,T,C,S,'1',W)$RTCSW(R,T,C,S,W) = (1+RTCS_SFR(R,T,C,S,W,S))/(1+RTCS_SFR(R,T,C,'ANNUAL',W,'ANNUAL'))-1;
    scf = {}
    for k in rtcsw:
        r, y, c, s, w = k
        x = (1 + sfr.get(k, 0.0)) / (1 + sfr.get((r, y, c, "ANNUAL", w), 0.0)) - 1
        if x:
            scf[k] = x
    db.load_rows("S_COM_FR", [(r, y, c, s, "1", w, x) for (r, y, c, s, w), x in sorted(scf.items())])
    # --- OPTION CLEAR=RTCS_SFR;
    #     RTCS_SFR(RTCSW(R,T,C,S,W),TS)$RS_BELOW(R,TS,S) = (1+RTCS_FRMX(R,T,C,S,TS))*(((1+S_COM_FR(R,T,C,S,'1',W))/MAX(1E-9,1+S_COM_FR(R,T,C,TS,'1',W)))-1);
    #     RTCS_SFR(RTCSW(R,T,C,S,W),TS)$(ABS(RTCS_SFR(R,T,C,S,W,TS)) < 1E-9) = 0;
    frmx = {(r, y, c, s, ts): x for r, y, c, s, ts, x in db.q("select r, y, c, s, s2, value from RTCS_FR")}
    above = {}
    for r, a, b in db.q("select r, s, s2 from RS_BELOW"):
        above.setdefault((r, b), []).append(a)
    ssfr = {}                                                      # (r, t, c, s, w, ts) -> RTCS_SFR(R,T,C,S,W,TS)
    for k in sorted(rtcsw):
        r, y, c, s, w = k
        for ts in above.get((r, s), ()):
            x = (1 + frmx.get((r, y, c, s, ts), 0.0)) * (((1 + scf.get(k, 0.0)) / max(1e-9, 1 + scf.get((r, y, c, ts, w), 0.0))) - 1)
            if abs(x) >= 1e-9:
                ssfr[(r, y, c, s, w, ts)] = x
    # --- RTCS_SFR(R,LL--ORD(LL),C,S,W,TS)$SW_TSTG(LL,'2') $= RTCS_SFR(R,LL,C,S,W,TS);     (LL--ORD(LL): '0')
    #     RTCS_SFR(R,T,C,S,W,TS)$(SW_TSTG(T,'2')$RTCS_SFR(R,'0',C,S,W,TS)) = RTCS_SFR(R,T,C,S,W,TS)-RTCS_SFR(R,'0',C,S,W,TS);
    order = {y: i for i, (y,) in enumerate(db.q("select y from MILESTONYR order by yv(y)"))}
    zero = {}
    for (r, y, c, s, w, ts), x in sorted(ssfr.items(), key=lambda kv: order.get(kv[0][1], -1)):
        if y in stg2:
            zero[(r, c, s, w, ts)] = x
    for (r, c, s, w, ts), z in zero.items():
        for y in stg2:
            k = (r, y, c, s, w, ts)
            ssfr[k] = ssfr.get(k, 0.0) - z
    ssfr = {k: x for k, x in ssfr.items() if x}
    ssfr.update({(r, "0", c, s, w, ts): z for (r, c, s, w, ts), z in zero.items()})
    # --- OPTION RCS_SSFR <= RTCS_SFR; OPTION CLEAR=RTCSW,CLEAR=RTCS_SFR;
    db.load_rows("RCS_SSFR", [(r, c, s, ts, w, y, x) for (r, y, c, s, w, ts), x in sorted(ssfr.items())])
    # port-only: RTCS_SFRW(R,T,C,S,TS,W) = SUM(T0 of SW_T2W(.,T,W,T0), RCS_SSFR(R,C,S,TS,W,T0)), T0 = T and, in stage 2 on, '0'
    sfrw = {}
    for (r, y, c, s, w, ts), x in ssfr.items():
        if y != "0":
            sfrw[(r, y, c, s, ts, w)] = sfrw.get((r, y, c, s, ts, w), 0.0) + x
    for (r, c, s, w, ts), z in zero.items():
        for y in stg2:
            k = (r, y, c, s, ts, w)
            sfrw[k] = sfrw.get(k, 0.0) + z
    db.declare("RTCS_SFRW", "par", ["R", "ALLYEAR", "C", "S", "TS", "ALLSOW"])   # (a model without S_COM_FR has no table)
    db.load_rows("RTCS_SFRW", [k + (x,) for k, x in sorted(sfrw.items()) if x])


def _round(x, n):
    """GAMS ROUND(x, n): halves away from zero."""
    f = 10.0 ** n
    return math.copysign(math.floor(abs(x) * f + 0.5) / f, x)


def ncap_afs(db: DB):
    """stages.stc 238-247: the uncertain NCAP_AFS (an availability by SOW) as RTP_SAFS(R,T,P,S,W), the multiplier less 1
    of COEF_AF in the rows of W (recurrin.stc 46: COEF_AFMX = COEF_AF*(1+RTP_SAFS(R,T,P,S,SOW)))."""
    db.declare("RTP_SAFS", "par", ["R", "ALLYEAR", "P", "S", "ALLSOW"])        # (a model without S_NCAP_AFS has no table)
    db.clear("RTP_SAFS")
    J = [j for (j,) in db.q("select j from J")]
    swmap = {}
    for y, w, j, w2 in db.q("select y, ww, j, ww2 from SW_MAP"):
        swmap.setdefault((y, j), []).append((w, w2))
    afs_in = {}
    for r, y, p, s, j, w, x in db.q("select r, y, p, s, j, w, value from S_NCAP_AFS"):
        afs_in.setdefault((y, j, w), []).append((r, p, s, x))
    # --- LOOP(J, RTP_SAFS(R,T,P,S,W) $= SUM(SW_MAP(T,W,J,WW),S_NCAP_AFS(R,T,P,S,J,WW)));
    safs = {}
    for j in J:
        tot = {}
        for (y, jj), pairs in swmap.items():
            if jj != j:
                continue
            for (w, w2) in pairs:
                for (r, p, s, x) in afs_in.get((y, j, w2), ()):
                    tot[(r, y, p, s, w)] = tot.get((r, y, p, s, w), 0.0) + x
        safs.update({k: x for k, x in tot.items() if x})
    # --- OPTION CLEAR=S_NCAP_AFS;
    #     LOOP(BDUPX(BD),
    #       S_NCAP_AFS(R,T,P,S,'1',W)$((NCAP_AF(R,T,P,S,BD) > 0)$RTP_SAFS(R,T,P,S,W)) = RTP_SAFS(R,T,P,S,W)/NCAP_AF(R,T,P,S,BD);
    #       S_NCAP_AFS(R,T,P,S,'1',W)$((NCAP_AFS(R,T,P,S,BD) > 0)$RTP_SAFS(R,T,P,S,W)) = RTP_SAFS(R,T,P,S,W)/NCAP_AFS(R,T,P,S,BD);
    #       S_NCAP_AFS(R,T,P,ANNUAL(S),'1',W)$((NCAP_AFA(R,T,P,BD) > 0)$RTP_SAFS(R,T,P,S,W)) = RTP_SAFS(R,T,P,S,W)/NCAP_AFA(R,T,P,BD));
    af = {(r, y, p, s, l): x for r, y, p, s, l, x in db.q("select r, y, p, s, l, value from NCAP_AF")}
    afs = {(r, y, p, s, l): x for r, y, p, s, l, x in db.q("select r, y, p, s, l, value from NCAP_AFS")}
    afa = {(r, y, p, l): x for r, y, p, l, x in db.q("select r, y, p, l, value from NCAP_AFA")}
    ann = {s for (s,) in db.q("select s from ANNUAL")}
    rel = {}
    for (bd,) in db.q("select l from BDUPX"):
        for (r, y, p, s, w), x in safs.items():
            for base in (af.get((r, y, p, s, bd), 0.0), afs.get((r, y, p, s, bd), 0.0),
                         afa.get((r, y, p, bd), 0.0) if s in ann else 0.0):
                if base > 0:
                    rel[(r, y, p, s, w)] = x / base
    # --- OPTION CLEAR=RTP_SAFS; RTP_SAFS(R,T,P,S,W)$S_NCAP_AFS(R,T,P,S,'1',W) = ROUND(S_NCAP_AFS(R,T,P,S,'1',W)-1,8);
    rows = [(r, y, p, s, w, _round(x - 1, 8)) for (r, y, p, s, w), x in sorted(rel.items()) if x]
    db.load_rows("RTP_SAFS", [k for k in rows if k[-1]])
    db.clear("S_NCAP_AFS")


def flo_func(db: DB):
    """stages.stc 214-231: the uncertain FLO_FUNC as RTP_FFCS(R,V,P,CG,CG2,SOW), the multiplier less 1 of the
    transformation (cg, cg2) of vintage v in the rows of SOW w (%SHFF%S in eqptrans.mod, cal_fflo.mod, cal_red.red,
    cal_nored.red, pp_actef.vda)."""
    # --- PARAMETER RTP_FFCS(R,ALLYEAR,P,CG,CG%SWD%); OPTION CLEAR=RTP_FFCS;
    db.declare("RTP_FFCS", "par", ["R", "ALLYEAR", "P", "CG", "CG", "ALLSOW"])     # (a model without S_FLO_FUNC has no table)
    db.clear("RTP_FFCS")
    act = {c for (c,) in db.q("select cg from ACTCG")}
    # --- RP_FFSGG(R,P,ACTCG(CG),CG) = NO;
    ffsgg = {(r, p, a, b) for r, p, a, b in db.q("select r, p, cg, cg2 from RP_FFSGG") if not (a in act and a == b)}
    # --- RP_FFSGGM(RP_PG(RP,CG1),CG,ACTCG,CG)$RP_FFSGG(RP,ACTCG,CG) = YES;
    #     RP_FFSGGM(RP_FFSGG(RP,CG,CG2),CG,CG2)$(NOT ACTCG(CG)) = YES;
    pg = {}
    for r, p, cg in db.q("select r, p, cg from RP_PG"):
        pg.setdefault((r, p), []).append(cg)
    ffm = {}                                                       # (r, p, cg, cg2) -> [(source cg, cg2)]
    for (r, p, a, b) in sorted(ffsgg):
        targets = [(g, b) for g in pg.get((r, p), ())] if a in act else [(a, b)]
        for (g, h) in targets:
            ffm.setdefault((r, p, g, h), []).append((a, b))
    # --- OPTION RP_FFSGG <= RP_FFSGGM, TRACKP < RP_FFSGG;
    trackp = {(r, p) for (r, p, _, _) in ffm}
    # --- UNCD7(R,TT,T--ORD(T),P,SOW,'','')$TRACKP(R,P) $= RTP_VINTYR(R,TT,T,P)$SW_T(T,SOW);
    #     LOOP(UNCD7(R,T,TT,P,SOW,'',''),RTPW(R,T,P,SOW)=YES);
    rtpw = {}
    for r, v, p, w in db.q("select distinct k.r, k.y, k.p, s.w from RTP_VINTYR k join SW_T s on s.y=k.y2"):
        if (r, p) in trackp:
            rtpw.setdefault((r, p), []).append((v, w))
    tsw = {(w, y): w2 for w, y, w2 in db.q("select w, y, w2 from SW_TSW")}
    swmap = {}
    for y, w, j, w2 in db.q("select y, ww, j, ww2 from SW_MAP"):
        swmap.setdefault((y, w), []).append((j, w2))
    sff = {(r, y, p, a, b, j, w): x for r, y, p, a, b, j, w, x in db.q("select r, y, p, cg, cg2, j, w, value from S_FLO_FUNC")}
    # --- RTP_FFCS(R,T,P,CG,COM_GRP,SOW)$(RTPW(R,T,P,SOW)*RP_FFSGG(R,P,CG,COM_GRP)) =
    #       SUM((RP_FFSGGM(R,P,CG,COM_GRP,CG1,CG2),SW_TSW(SOW,T,W)),
    #         PROD(SW_MAP(T,W,J,WW)$S_FLO_FUNC(R,T,P,CG1,CG2,J,WW),S_FLO_FUNC(R,T,P,CG1,CG2,J,WW))-1);
    ffcs = {}
    for (r, p, g, h), src in ffm.items():
        for (v, w) in rtpw.get((r, p), ()):
            W = tsw.get((w, v))
            if W is None:
                continue
            x = 0.0
            for (a, b) in src:
                pr = 1.0
                for (j, ww) in swmap.get((v, W), ()):
                    f = sff.get((r, v, p, a, b, j, ww))
                    if f:
                        pr *= f
                x += pr - 1
            if x:
                ffcs[(r, v, p, g, h, w)] = x
    # --- * Remap reduced FUNC flows
    #     LOOP(RPCG_PTRAN(RP,C,COM,CG,CG2)$RP_FFSGG(RP,CG,CG2),IF(RPC_FFUNC(RP,C),RP_DCGG(RP,C,CG,CG2,'UP')=YES; ELSE RP_DCGG(RP,COM,CG,CG2,'LO')=YES));
    #     RP_DCGG(RPC_FFUNC(RP,COM),CG,C,'UP')$(RPG_1ACE(RP,CG,COM)$RPC_ACT(RP,C)) $= RP_FFSGG(RP,CG,C);
    ffunc = set(db.q("select r, p, c from RPC_FFUNC"))
    dcgg = []
    for r, p, c, com, a, b in db.q("select r, p, c, c2, cg, cg2 from RPCG_PTRAN"):
        if (r, p, a, b) in ffm:
            dcgg.append((r, p, c, a, b, "UP") if (r, p, c) in ffunc else (r, p, com, a, b, "LO"))
    for r, p, a, com, c in db.q("""select g.r, g.p, g.cg, g.c, k.cg from RPG_1ACE g
                                   join RPC_FFUNC f on f.r=g.r and f.p=g.p and f.c=g.c join RPC_ACT k on k.r=g.r and k.p=g.p"""):
        if (r, p, a, c) in ffm:
            dcgg.append((r, p, com, a, c, "UP"))
    dcgg = sorted(set(dcgg))
    if dcgg:
        sig = {l: x for l, x in db.q("select l, value from BDSIG")}
        rtp = set(db.q("select r, y, p from RTP"))
        # --- RTP_FFCS(RTP(R,T,P),ACTCG,C,W)$RPC_FFUNC(R,P,C) $= SUM(RP_DCGG(R,P,C,CG,CG2,L),
        #       (POWER(RTP_FFCS(RTP,CG,CG2,W)+1,BDSIG(L))-1)$(RTP_FFCS(RTP,CG,CG2,W)+1));
        new = {}
        for (r, v, p, a, b, w), x in ffcs.items():
            for (r2, p2, c, a2, b2, l) in dcgg:
                if (r2, p2, a2, b2) == (r, p, a, b) and (r, v, p) in rtp and x + 1:
                    for g in act:
                        k = (r, v, p, g, c, w)
                        new[k] = new.get(k, 0.0) + (x + 1) ** sig.get(l, 0.0) - 1
        for k, x in new.items():
            if x and (k[0], k[2], k[4]) in ffunc:
                ffcs[k] = x
        # --- LOOP(RP_DCGG(R,P,C,CG,CG2,L),RTP_FFCS(R,T,P,CG,CG2,W) = 0);
        drop = {(r, p, a, b) for (r, p, _, a, b, _) in dcgg}
        ffcs = {k: x for k, x in ffcs.items() if (k[0], k[2], k[3], k[4]) not in drop}
    db.load_rows("RTP_FFCS", [(r, v, p, g, h, w, x) for (r, v, p, g, h, w), x in sorted(ffcs.items())])
    # --- OPTION CLEAR=S_FLO_FUNC,CLEAR=RTPW,CLEAR=RP_DCGG,CLEAR=RP_FFSGG,CLEAR=RP_FFSGGM;
    db.clear("S_FLO_FUNC", "RP_FFSGG")


def fillsow(db: DB, name, year, absolute, period=None, baseline=False):
    """fillsow.stc: S_<name> filled for the SOWs of the copied branches, and (absolute attributes) the deterministic
    value copied to stage 1, SOW 1, and the stages merged into stage '1' by representative SOW.

    year      'T' (a period), 'LL' (the second year of a cumulative attribute) or '' (no year)   (%4)
    absolute  %5 = YES: the merge into stage '1'
    period    %6: 'SW_T' (SW_T(T,WW)), 'SUPERYR' (SUPERYR(T,LL)) or 'YES'
    baseline  %7 = YES: the deterministic value is copied to stage '1', SOW '1'"""
    sn = "S_" + name
    if not db.card(sn) and not baseline:
        return
    cols = [c for c in db.cols(sn)]
    key = cols[:-2]                                # the index before (J, WW)
    yc = None if not year else ("y" if year == "T" else ("u2" if "u2" in cols else "y2"))
    kx = [c for c in key if c != yc]
    sel = lambda al, y=None: ", ".join((f"{y} as {c}" if (c == yc and y) else f"{al}.{c}") for c in key)
    grp = lambda al: ", ".join(f"{al}.{c}" for c in key)
    on_ = lambda a, b, cs: " and ".join(f"{a}.{c}={b}.{c}" for c in cs) or "true"
    # --- S_%1(%2%4%TAIL%,'1',SOW)$(NOT SAMEAS(SOW,'1')) = 0;
    db.remove(sn, where="j='1' and w<>'1' and in_SOW(w)")

    # --- $IF NOT '%4'=='' S_%1(%2LL--ORD(LL)%TAIL%,J,WW) $= S_%1(%2LL%TAIL%,J,WW);    (the year '0': the last data year)
    def flags():
        if yc:
            db.put(sn, f"""select {sel('a', "'0'")}, a.j, a.w,
                                  arg_max(a.value, case when a.{yc}='0' then 99999 else yv(a.{yc}) end) as value
                           from "{sn}" a group by {", ".join(f"a.{c}" for c in kx)}{", " if kx else ""}a.j, a.w""", zero="eps")
    flags()
    n0 = db.card(sn)
    # --- S_%1(%2%4%TAIL%,J,WW)$(%STG%(NOT S_%1(%2%IX%%TAIL%,J,WW))) $= SUM(SW_CPMAP(J,WW,SOW),S_%1(%2%4%TAIL%,J,SOW));
    #     (%STG% = SW_TSTG(T,J)$ for a period;  IX = '0', or no year index)
    stg = "and in_SW_TSTG(a.y, a.j)" if year == "T" else ""
    yflag = f"f.{yc}='0' and " if yc else ""
    noflag = f"not exists(select 1 from \"{sn}\" f where {yflag}f.j=m.j and f.w=m.ww and {on_('f', 'a', kx)})"
    ycond = f"and a.{yc} <> '0'" if yc else ""
    db.put(sn, f"""select {sel('a')}, m.j, m.ww as w, sum(a.value) as value from "{sn}" a
                   join SW_CPMAP m on m.j=a.j and m.ww2=a.w where {noflag} {stg} {ycond}
                   group by {grp('a')}, m.j, m.ww""", zero="skip")
    if not absolute:
        return
    # --- $IF NOT '%4'=='' IF(CARD(S_%1)>F, S_%1(%2LL--ORD(LL)%TAIL%,J,WW) $= S_%1(%2LL%TAIL%,J,WW));
    if db.card(sn) > n0:
        flags()
    # --- $IF '%7'==YES  S_%1(%2%4%TAIL%,'1','1')$(NOT S_%1(%2%IX%%TAIL%,'1','1')) $= %1(%2%4%TAIL%);
    if baseline:
        bc = [c for c in db.cols(name)]
        assert len(bc) == len(key), (name, bc, key)
        b = ", ".join(f"a.{c} as {k}" for c, k in zip(bc, key))
        nf = f"not exists(select 1 from \"{sn}\" f where {yflag}f.j='1' and f.w='1' and " + \
             (" and ".join(f"f.{k}=a.{c}" for c, k in zip(bc, key) if k != yc) or "true") + ")"
        yb = f"and a.{bc[key.index(yc)]} <> '0'" if yc else ""
        db.put(sn, f"""select {b}, '1' as j, '1' as w, a.value from "{name}" a where {nf} {yb}""", zero="eps")
    # --- Merge to single stage 1:
    #     $IFI NOT '%4'==LL  LOOP(J$SW_START(J),S_%1(%2%4%TAIL%,'1',WW)$(%STG%%6) $= SUM(SW_REV(WW,J,SOW),S_%1(%2%4%TAIL%,J,SOW)));
    #     $IFI '%4' == LL    LOOP(SW_TSTG(T,J), S_%1(%2%4%TAIL%,'1',WW)$(%6$SW_T(T,WW)) $= SUM(SW_REV(WW,J,SOW),S_%1(%2%4%TAIL%,J,SOW)));
    if year == "LL":
        for (t, j) in db.q("select y, j from SW_TSTG order by cast(j as integer), yv(y)"):
            db.put(sn, f"""select {sel('a')}, '1' as j, r.ww as w, sum(a.value) as value from "{sn}" a
                           join SW_REV r on r.j=a.j and r.ww2=a.w
                           where a.j='{j}' and in_SUPERYR('{t}', a.{yc}) and in_SW_T('{t}', r.ww)
                           group by {grp('a')}, r.ww""", zero="eps")
    else:
        for (j,) in db.q("select j from SW_START order by cast(j as integer)"):
            cond = "true"
            if year == "T":
                cond = f"in_SW_TSTG(a.y, '{j}')" + (" and in_SW_T(a.y, r.ww)" if period == "SW_T" else "")
            db.put(sn, f"""select {sel('a')}, '1' as j, r.ww as w, sum(a.value) as value from "{sn}" a
                           join SW_REV r on r.j=a.j and r.ww2=a.w
                           where a.j='{j}' and {cond} {ycond}
                           group by {grp('a')}, r.ww""", zero="eps")
    # --- $IF '%4'=='LL' S_%1(%2%IX%%TAIL%,J,WW) = 0;
    if year == "LL":
        db.remove(sn, where=f"{yc}='0'")


# ---------------------------------------------------------------------------------------------------------------------
# bndmain.mod with STAGES: the bounds of the variables by SOW (VAS_<X>)

# the position of the period in the key of each variable (%VART%: T; %VARV%: the vintage V of VAR_NCAP); None: the
# variable has no period and exists for every SOW (%SOW%)
PERIOD = dict(VAR_ACT=2, VAR_FLO=2, VAR_IRE=2, VAR_NCAP=1, VAR_CAP=1, VAR_COMNET=1, VAR_COMPRD=1, VAR_CUMFLO=None,
              VAR_CUMCOM=None, VAR_SIN=2, VAR_SOUT=2, VAR_UDP=2, VAR_UPS=2, VAR_RCAP=2, VAR_SCAP=2, VAR_DRCAP=2,
              VAR_UC=None, VAR_UCR=None, VAR_UCT=1, VAR_UCTS=1, VAR_UCRT=2, VAR_UCRTS=2, VAR_OBJ=None, VAR_ELAST=1,
              VAR_OBJELS=None, VAR_BLND=1, VAR_UPT=2, VAR_CUMCST=None, VAR_DNCAP=1, VAR_SNCAP=1)


# the slack variables of the user constraints by period: the position of the region in the key (None: none)
UC_SLACK = dict(VAR_UCT=None, VAR_UCTS=None, VAR_UCRT=1, VAR_UCRTS=1)


def vas(var):
    """VAR_ACT -> VAS_ACT (stages.stc 12: SET VAR 'VAS')"""
    return "VAS_" + var[4:]


def bounds(db: DB):
    """The bounds of bndmain.mod by SOW: a bound set with %SWD% / %SWT% (`$SW_T(T,SOW)`) is that of every SOW of its
    period (SW_T); one without a period that of every SOW. B_VAR_<X> becomes B_VAS_<X>, the SOW its last column.
    bnd_set.mod 28-33 then sets the uncertain capacity bounds S_CAP_BND(R,T,P,BD,'1',SOW) over them. (The cumulative
    bounds are set by SOW in cum_bounds.)"""
    if not on(db):
        return
    # --- mod_vars.mod: VARIABLE VAS_EXPOBJ (free: the expected value of the objective, EQ_EXPOBJ)
    db.x('create or replace table "B_VAS_EXPOBJ" (lower DOUBLE, upper DOUBLE)')
    db.x('''insert into "B_VAS_EXPOBJ" values ('-inf'::double, 'inf'::double)''')
    db.bounds.add("VAS_EXPOBJ")
    if not tagged(db):
        return                                 # SENSIS: the bounds of the deterministic model (sensis.stc per solve)
    for var in sorted(db.bounds):
        if not var.startswith("VAR_"):
            continue
        if var not in PERIOD:
            unsupported(db, f"bounds of {var} with STAGES=YES")
            continue
        n = len(db.q(f'describe "B_{var}"')) - 2
        ks = ", ".join(f"b.d{i}" for i in range(n))
        cols = ", ".join(f"d{i} VARCHAR" for i in range(n + 1))
        db.x(f'create or replace table "B_{vas(var)}" ({cols}, lower DOUBLE, upper DOUBLE)')
        k = PERIOD[var]
        if var in ("VAR_RCAP", "VAR_SCAP", "VAR_DRCAP"):
            # prepret.dsc 72-82, 125-127: %VAR%_RCAP.LO(VNRET(V,T,P)%SOW%) = ..: every SOW, whatever the period
            db.x(f'insert into "B_{vas(var)}" select {ks}, s.w, b.lower, b.upper from "B_{var}" b, SOW s')
        elif var == "VAR_SOUT":
            # bnd_stg.mod 14: %VAR%_SOUT.LO(RTP_VINTYR(R,V,T,P),%PGPRIM%,S%SWD%)$((RPS_STG(R,P,S)->0)$RP_STS(R,P)) = -INF:
            # %SWD% is ',WW', uncontrolled: every label of ALLSOW; the bounds of STGOUT_BND by SW_T (bnd_stg.mod 20-26)
            free = "b.d4='ACT' and b.lower = '-inf'::double"
            db.x(f'insert into "B_{vas(var)}" select {ks}, s.w, b.lower, b.upper from "B_{var}" b, ALLSOW s where {free}')
            db.x(f'insert into "B_{vas(var)}" select {ks}, s.w, b.lower, b.upper from "B_{var}" b join SW_T s on s.y=b.d{k} where not ({free})')
        elif var in UC_SLACK and db.card("SUC_L"):
            # bnd_ucw.mod 12: $IF %STAGES%==YES $SET TMP (T-SUC_L(R,UC_N)); bnd_ucv.mod:
            #   %1.LO(UC_N,R,TT(T-SUC_L(R,UC_N)),SOW)$(UC_ON(R,UC_N)*UC_T_EACH(R,UC_N,TT)$SW_T(T,SOW)) $= UC_RHSRT(R,UC_N,TT,'LO')
            # a constraint dynamic on its left-hand side (SUC_L) has the bound of period TT for the SOWs of the period
            # after it (none for the last period); the others by SW_T of their own period
            rc = UC_SLACK[var]
            on_r = f"l.r=b.d{rc} and " if rc is not None else ""
            lead = "(select y, lead(y) over (order by yv(y)) as y1 from MILESTONYR)"
            db.x(f"""create or replace temp table t_dyn as select distinct b.* from "B_{var}" b
                     join SUC_L l on {on_r}l.uc=b.d0 where l.value > 0""")
            db.x(f"""insert into "B_{vas(var)}" select distinct {ks}, s.w, b.lower, b.upper from t_dyn b
                     join {lead} n on n.y=b.d{k} join SW_T s on s.y=n.y1""")
            nd = " and ".join(f"d.d{i}=b.d{i}" for i in range(n))
            db.x(f"""insert into "B_{vas(var)}" select {ks}, s.w, b.lower, b.upper from "B_{var}" b join SW_T s on s.y=b.d{k}
                     where not exists(select 1 from t_dyn d where {nd})""")
        elif k is None:
            db.x(f'insert into "B_{vas(var)}" select {ks}, s.w, b.lower, b.upper from "B_{var}" b, SOW s')
        else:
            db.x(f'insert into "B_{vas(var)}" select {ks}, s.w, b.lower, b.upper from "B_{var}" b join SW_T s on s.y=b.d{k}')
            db.x(f"""insert into "B_{vas(var)}" select {ks}, s.w, b.lower, b.upper from "B_{var}" b, SOW s
                     where not in_MILESTONYR(b.d{k})""")
        db.x(f'drop table "B_{var}"')
        db.bounds.discard(var)
        db.bounds.add(vas(var))
    # --- bnd_set.mod 28-33 (VAR_CAP: CAP_BND, control RTP(R,T,P), qualifier $SW_T(T,SOW)):
    #     %1.LO(%4%SOW%)%5 $= S_%3(%2,'LO','1',SOW);  %1.UP(..) $= S_%3(%2,'UP','1',SOW);  %1.FX(..) $= S_%3(%2,'FX','1',SOW);
    if db.card("S_CAP_BND"):
        if "VAS_CAP" not in db.bounds:
            db.x('create table "B_VAS_CAP" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, lower DOUBLE, upper DOUBLE)')
            db.bounds.add("VAS_CAP")
        db.x("""create or replace temp table t_scap as
                select r, y, p, w, max(case when l='LO' then value end) as lo, max(case when l='UP' then value end) as up,
                       max(case when l='FX' then value end) as fx
                from S_CAP_BND where j='1' and in_RTP(r,y,p) and in_SW_T(y,w) and in_SOW(w) group by r, y, p, w""")
        db.x("""insert into "B_VAS_CAP" select r, y, p, w, 0, 'inf'::double from t_scap s
                where not exists(select 1 from "B_VAS_CAP" b where b.d0=s.r and b.d1=s.y and b.d2=s.p and b.d3=s.w)""")
        db.x("""update "B_VAS_CAP" b set lower = coalesce(s.fx, s.lo, b.lower), upper = coalesce(s.fx, s.up, b.upper)
                from t_scap s where b.d0=s.r and b.d1=s.y and b.d2=s.p and b.d3=s.w""")
    uc_bounds(db)


# the slack variables of the user constraints: (variable, RHS attribute, the key of the variable as columns of the
# attribute, by period)   (bnd_ucw.mod 14-19)
UC_VARS = (("VAR_UC", "UC_RHS", ["uc"], False), ("VAR_UCR", "UC_RHSR", ["uc", "r"], False),
           ("VAR_UCT", "UC_RHST", ["uc", "y"], True), ("VAR_UCRT", "UC_RHSRT", ["uc", "r", "y"], True),
           ("VAR_UCTS", "UC_RHSTS", ["uc", "y", "s"], True), ("VAR_UCRTS", "UC_RHSRTS", ["uc", "r", "y", "s"], True))


def uc_bounds(db: DB):
    """bnd_ucv.mod 46-53 with STAGES: the uncertain RHS of the user constraints (S_UC_RHS*, merged into stage '1' by
    fillsow.stc) as bounds of the slack variables by SOW, over the bounds of the deterministic RHS.

      IF(SW_PHASE NE -2,
        %1.LO(UC_N%2%3%4%13%9%SOW%)%6 $= S_%5(%3%2UC_N%4%9,'LO','1',SOW);
        %1.UP(UC_N%2%3%4%13%9%SOW%)%6 $= S_%5(%3%2UC_N%4%9,'UP','1',SOW);
        %1.FX(UC_N%2%3%4%13%9%SOW%)%6 $= S_%5(%3%2UC_N%4%9,'FX','1',SOW););

    %6 is $UC_ON(R,UC_N) (in LOOP(R, ..) for the families without a region), for a period
    $(UC_ON(R,UC_N)*UC_T_EACH(R,UC_N,TT)$SW_T(T,SOW)) with UC_T_EACH(UC_T_SUCC) = YES and %13 = (T-SUC_L(R,UC_N)): the
    bound of period TT is that of the SOWs of T, the period after TT for a constraint dynamic on its left-hand side.
    (SW_PHASE is 0 here: S_UCOBJ, which sets the phases, is refused; so are the deviation bounds 'N' of phase 2.)"""
    db.x("create or replace temp table t_uclead as select y, lead(y) over (order by yv(y)) as y1 from MILESTONYR")
    for var, par, key, per in UC_VARS:
        sn = "S_" + par
        if not db.card(sn):
            continue
        rr = "a.r" if "r" in key else "o.r"
        if per:
            tt = f"case when coalesce(v_SUC_L({rr},a.uc),0) > 0 then n.y1 else a.y end"
            cond = f"""exists(select 1 from UC_ON o join t_uclead n on n.y=a.y where o.uc=a.uc {"and o.r=a.r" if "r" in key else ""}
                              and (in_UC_T_EACH({rr},a.uc,a.y) or in_UC_T_SUCC({rr},a.uc,a.y)) and in_SW_T({tt}, a.w))"""
        else:
            cond = f"""exists(select 1 from UC_ON o where o.uc=a.uc {"and o.r=a.r" if "r" in key else ""})"""
        ks = ", ".join(f"a.{c}" for c in key)
        db.x(f"""create or replace temp table t_sucb as
                 select {ks}, a.w, max(case when a.l='LO' then a.value end) as lo, max(case when a.l='UP' then a.value end) as up,
                        max(case when a.l='FX' then a.value end) as fx
                 from "{sn}" a where a.j='1' and a.l in ('LO','UP','FX') and in_SOW(a.w) and {cond}
                 group by {ks}, a.w""")
        b = vas(var)
        n = len(key)
        if b not in db.bounds:
            cols = ", ".join(f"d{i} VARCHAR" for i in range(n + 1))
            db.x(f'create or replace table "B_{b}" ({cols}, lower DOUBLE, upper DOUBLE)')
            db.bounds.add(b)
        on_ = " and ".join(f"b.d{i}=s.{c}" for i, c in enumerate(key)) + f" and b.d{n}=s.w"
        # (a variable without a deterministic bound is free: bnd_ucv.mod 23-24)
        db.x(f"""insert into "B_{b}" select {", ".join(f"s.{c}" for c in key)}, s.w, '-inf'::double, 'inf'::double from t_sucb s
                 where not exists(select 1 from "B_{b}" b where {on_})""")
        db.x(f"""update "B_{b}" b set lower = coalesce(s.fx, s.lo, b.lower), upper = coalesce(s.fx, s.up, b.upper)
                 from t_sucb s where {on_}""")


def cum_bounds(db: DB):
    """bnd_cum.mod with STAGES (SW1 = 'S_', SW2 = ",'1'%SOW%"): the cumulative bounds of the SOWs, from the uncertain
    attributes merged into stage '1' (S_FLO_CUM, S_COM_CUM); the deterministic ones only give the 'N' modifiers."""
    # --- %SW1%FLO_CUM(R,P,C,YEAR,LL,BD%SW2%)$((%SW1%FLO_CUM(..) LT 0)$%SW1%FLO_CUM(..)) = 0;
    db.zap("S_FLO_CUM", "value < 0 and l in ('LO','UP','FX') and j='1' and in_SOW(w)")
    # --- FLO_CUM(R,P,C,YEAR,'EOH','N') $= FLO_CUM(R,P,C,YEAR,'%EOTIME%','N');   FLO_CUM(RPC_CUMFLO(R,P,C,YEAR,LL),'N') = 0;
    eot = str(db.ctl["EOTIME"])
    db.put("FLO_CUM", f"select r, p, c, u, 'EOH' as u2, 'N' as l, value from FLO_CUM where l='N' and u2='{eot}'", zero="eps")
    db.zap("FLO_CUM", "l='N' and in_RPC_CUMFLO(r,p,c,u,u2)")
    # --- %SW1%FLO_CUM(R,P,C,YEAR,LL,BD%SW2%)$%SW1%FLO_CUM(R,P,C,YEAR,LL,'FX'%SW2%) = %SW1%FLO_CUM(..,'FX'%SW2%)$BDNEQ(BD);
    db.put("S_FLO_CUM", """select f.r, f.p, f.c, f.u, f.u2, q.l, f.j, f.w, f.value from S_FLO_CUM f, BDNEQ q
                           where f.l='FX' and f.j='1' and in_SOW(f.w)""", zero="eps")
    db.zap("S_FLO_CUM", "l='FX' and j='1' and in_SOW(w)")
    # --- %VAR%_CUMFLO.LO/UP(R,P,C,YEAR,LL %SOW%)$%SW1%FLO_CUM(R,P,C,YEAR,LL,bd%SW2%) =
    #         %SW1%FLO_CUM(R,P,C,YEAR,LL,bd%SW2%)*(1/%CUFSCAL%)*(FLO_CUM(R,P,C,YEAR,LL,'N')+1);
    #     (the 'N' modifiers are 0 here: flexible horizons with MULTI are refused in bounds.py)
    scal = float(db.env.get("CUFSCAL", 10))
    db.x('create table if not exists "B_VAS_CUMFLO" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, d5 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x(f"""insert into "B_VAS_CUMFLO" select r, p, c, u, u2, w,
                 coalesce(max(case when l='LO' then value / {scal} end), 0), coalesce(max(case when l='UP' then value / {scal} end), 'inf'::double)
             from S_FLO_CUM where l in ('LO','UP') and j='1' and in_SOW(w) group by r, p, c, u, u2, w""")
    db.bounds.add("VAS_CUMFLO")
    if not db.card("RC_CUMCOM"):
        return
    if db.ctl["OBJ"] == "LIN":
        unsupported(db, "cumulative commodity bounds with OBJ LIN (eqcumcom.mod weights periods with TPULSE)", ["COM_CUMNET", "COM_CUMPRD"])
    # --- COM_CUM(R,%1,YEAR,'0',C,'N') $= COM_CUM(R,%1,YEAR,'%EOTIME%',C,'N');  COM_CUM(RC_CUMCOM(R,%1,YEAR,LL,C),'N') = 0;
    db.put("COM_CUM", f"select r, cv, y, '0' as y2, c, 'N' as l, value from COM_CUM where l='N' and y2='{eot}'", zero="eps")
    db.zap("COM_CUM", "l='N' and in_RC_CUMCOM(r,cv,y,y2,c)")
    # --- %SW1%COM_CUM(R,%1,YEAR,LL,C,BD%SW2%)$%SW1%COM_CUM(..,'FX'%SW2%) = %SW1%COM_CUM(..,'FX'%SW2%)$BDNEQ(BD);
    db.put("S_COM_CUM", """select f.r, f.cv, f.y, f.y2, f.c, q.l, f.j, f.w, f.value from S_COM_CUM f, BDNEQ q
                           where f.l='FX' and f.j='1' and in_SOW(f.w)""", zero="eps")
    db.zap("S_COM_CUM", "l='FX' and j='1' and in_SOW(w)")
    # --- %SW1%COM_CUM(RC_CUMCOM(R,%1,LL,YEAR,C),BD%SW2%)$(YEARVAL(LL)>MIYR_VL)=EPS; RC_CUMCOM(R,%1,LL,YEAR,C)$(YEARVAL(LL)>MIYR_VL)=NO;
    vl = db.s["MIYR_VL"]
    db.put("S_COM_CUM", f"""select k.r, k.cv, k.y, k.y2, k.c, b.l, '1' as j, s.w, 0 as value from RC_CUMCOM k, SOW s,
                            (select 'LO' as l union all select 'UP' union all select 'FX') b where yv(k.y) > {vl}""", zero="eps")
    db.remove("RC_CUMCOM", where=f"yv(y) > {vl}")
    # --- %SW1%COM_CUM(RC_CUMCOM(R,%1,YEAR,LL,C),L('LO')%SW2%)$(NOT %SW1%COM_CUM(RC_CUMCOM,L%SW2%)) =
    #         -INF$SUM((RTC(R,T,C),ANNUAL(S)),MIN(0,COM_BNDPRD(RTC,S,L)$DIAG(%1,'PRD')+COM_BNDNET(RTC,S,L)$DIAG(%1,'NET')+1-1));
    db.put("S_COM_CUM", """select k.r, k.cv, k.y, k.y2, k.c, 'LO' as l, '1' as j, s.w, '-inf'::double as value from RC_CUMCOM k, SOW s
                           where not exists(select 1 from S_COM_CUM f where f.r=k.r and f.cv=k.cv and f.y=k.y and f.y2=k.y2 and f.c=k.c
                                            and f.l='LO' and f.j='1' and f.w=s.w)
                             and exists(select 1 from RTC t where t.r=k.r and t.c=k.c and
                                        least(0, case when k.cv='PRD' then coalesce(v_COM_BNDPRD(t.r,t.y,t.c,'ANNUAL','LO'),0)
                                                      else coalesce(v_COM_BNDNET(t.r,t.y,t.c,'ANNUAL','LO'),0) end) < 0)""")
    # --- %VAR%_CUMCOM.LO/UP(R,C,%1,YEAR,LL %SOW%)$%SW1%COM_CUM(R,%1,YEAR,LL,C,bd%SW2%) = ..*(1/%CUCSCAL%)*(COM_CUM(..,'N')+1);
    scal = float(db.env.get("CUCSCAL", 1000))
    db.x('create table if not exists "B_VAS_CUMCOM" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, d5 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x(f"""insert into "B_VAS_CUMCOM" select r, c, cv, y, y2, w,
                 coalesce(max(case when l='LO' then value / {scal} end), 0),
                 coalesce(max(case when l='UP' then value / {scal} end), 'inf'::double)
             from S_COM_CUM where l in ('LO','UP') and j='1' and in_SOW(w) group by r, c, cv, y, y2, w""")
    db.bounds.add("VAS_CUMCOM")


# ---------------------------------------------------------------------------------------------------------------------
# spoint.mod 22 (maindrv.mod 104, before the solve): $IF %STAGES%==YES $BATINCLUDE clearsol.stc ALL
#   clearsol.stc 10 includes mod_vars.mod, and mod_vars.mod 94 prepret.dsc DECL, whose statements run again:
#   RVPRL(RTP(R,V,P))$PRC_RCAP(R,P)=MAX(0,SMAX(VNRET(V,T,P),YEARVAL(T))-YEARVAL(V));
#   so the residual capacity that eqobj.mod took out of RVPRL (prepret.dsc 129: RVPRL(R,PYR_S,P)$PRC_RESID(R,'0',P)=NO)
#   is in it again when the model is generated: its fixed-cost credit (prepret.dsc 136-145, not the "RESIDS" block),
#   EQL_SCAP and the salvage see it. (The other statements of DECL give what they gave before, or bounds of VAR_*,
#   which the stochastic model does not have.)

def keep_rvprl(db: DB, where):
    """The RVPRL records prepret.dsc 129 removes, kept for the solve of a stochastic run (spoint.mod 22:
    $IF %STAGES%==YES $BATINCLUDE clearsol.stc ALL)."""
    if not tagged(db):
        return
    db.x(f'create or replace table "STC_RVPRL" as select * from RVPRL where {where}')


def rvprl_at_solve_sql(db: DB):
    """RVPRL as the solve sees it: with STAGES, with the records kept by keep_rvprl."""
    if tagged(db) and db.q1("select count(*) from information_schema.tables where table_name='STC_RVPRL'"):
        return 'select r, y, p from RVPRL union select r, y, p from "STC_RVPRL"'
    return "select r, y, p from RVPRL"


def rvprl_at_solve(db: DB):
    """RVPRL of the solve (after the last dump): the records kept by keep_rvprl back in it."""
    if tagged(db) and db.q1("select count(*) from information_schema.tables where table_name='STC_RVPRL'"):
        db.put("RVPRL", 'select * from "STC_RVPRL"', zero="eps")
