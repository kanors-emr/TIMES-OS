# SPDX-License-Identifier: GPL-3.0-or-later
"""rptmisc.rpt — miscellaneous shared reportings.

Ported from TIMES v4.9.8 rptmisc.rpt. Each block quotes the statements it replaces.
Parameters are written under their GAMS names. The %1 prefix and the SOW index are
empty, which is the ordinary (non-stochastic) Veda report.

What is ported so far
---------------------
Activity levels, including the storage shift (the RP_STL loop), and activity marginals.
Capacity: PAR_CAPL, PAR_PASTI (past plant and early retirement), PAR_CAPM, PAR_CAPBD,
PAR_NCAPL, PAR_CUMRET.
Commodities: PAR_COMPRDL/M, PAR_COMNETL/M, AGG_OUT, PAR_COMBALEM, PAR_PEAKM.
PAR_COMBALGM is assigned only when the report prefix is S. This writer uses an empty
prefix, so the parameter stays empty.
PAR_NCAPM divides the new-capacity marginal by COEF_OBJINV. rpt_objc.rpt builds
that coefficient from the investment spread before the capacity block runs.
RPT_OPT thresholds are read from the model. An absent option is 0, so 'ACT','2' GE 0
is true and activity marginals are reported, matching a run that sets no RPT_OPT.
Cumulative flows are unscaled by CUFSCAL (10 unless the run file sets it).
User constraints: a Veda run sets VAR_UC to YES, so levels and marginals come
from the variables (rptmisc.rpt 166-192). rptlite.rpt skips par_uc.rpt in that case.
PAR_UCRTP uses the same coefficient for its capacity groups.
PAR_EOUT (electricity by energy source) is written only when RPT_OPT('FLO','5')
is set. SOLANS defaults to NO, so a run that does not set it leaves it empty.

The statements followed are those of TIMES v4.9.8; where a reading differs, 4.9.8 decides.
"""
from __future__ import annotations

from . import cost_ann, paruc, rptobj, solflo
from .load import install_last_step

# gams.transfer renders the GAMS label ¤ as the four characters \xa4. Labels are
# upper-cased, so the stored label is \XA4.
_RET = "\\XA4"

# Present in the writer; not yet reached with rows by a model.
UNVERIFIED = {
    "PAR_FLOM": "sol_flo.red line 22, from the activity marginal of a process in RP_PGACT; "
                "line 31 then exits, so substituted-flow marginals are never written. "
                "The sum is empty on this list",
    "PAR_CUMRET": "rptmisc.rpt line 37, when RPT_OPT('CAP','5') > 0",
    "PAR_CUMCST": "rptmisc.rpt line 153 copies VAR_CUMCST.L; needs a cumulative cost bound (REG_CUMCST)",
    "PAR_UCMRK": "rptmisc.rpt lines 159-162, when RPT_OPT('COMPRD','4') is set and a commodity has FLO_MARK",
    "PAR_UCMAX": "rptmisc.rpt lines 186-190; needs a user constraint in UC_GMAX, which declares EQG_UCMAX",
    "RTP_OBJ": "written by rpt_obj.rpt; cost_ann.rpt line 153 clears it before the reports are written",
    "RTP_NPV": "written by rpt_obj.rpt; cost_ann.rpt line 153 clears it before the reports are written",
    "PAR_ACTC": "eqobjvar.rpt writes the tax column; cost_ann.rpt line 198 clears it before the reports are written",
    "PAR_FLOC": "eqobjvar.rpt writes the tax column; cost_ann.rpt line 198 clears it before the reports are written",
    "PAR_COMC": "eqobjvar.rpt writes the tax column; cost_ann.rpt line 198 clears it before the reports are written",
}
# Empty for every Veda run, with the statement that leaves it so.
EXPECTED_EMPTY = {
    "PAR_COMBALGM": "rptmisc.rpt line 65, written only when the report prefix is S",
    "CST_DAM": "the damage report; DAMAGE is not set on these runs",
}
# Ported, and not reached by the models run so far.
UNTESTED = {
    "par_uc.rpt": "rptlite.rpt line 161 skips the three calls when VAR_UC is YES, which Veda run files set",
    "rpt_obj.rpt STAGES": "lines 17-18 and the %SIC% factor; STAGES is not set",
    "rpt_obj.rpt ETL": "line 37, the VAR_IC term; ETL is not set",
    "eqobjvar.rpt legacy": "line 107 exits before the legacy block",
    "rpt_objc.rpt BENCOST": "lines 90-125; BENCOST is not YES (refused by switches.py), so the cost-benefit rows of PAR_NCAPR are not written",
    "PAR_RTCS": "rptlite.rpt line 158, the power level of an aggregate commodity: no commodity of an energy type with RPT_OPT(type,'1') is an aggregate (COM_AGG) on this list",
    "cal_caps.mod": "eqobjvar.rpt lines 73 and 96; this implementation does not add this sum. with RPC_CAPFLO rows CST_FLOC still matches, so the omitted sum does not change the costs on this list",
    "cost_ann.rpt ETL": "lines 66-73; ETL is not set",
    "powerflo.vda": "cost_ann.rpt line 175, included only when OBJ_COMBAL is defined",
}
# One run-file line that switches on every RPT_OPT gate above:
# $SET RPT_OPT 'CAP'.'5' 1, 'FLO'.'3' 1, 'COMPRD'.'4' 1, 'FOSSIL'.'1' 1, 'NUCLR'.'1' 1, 'SYNTH'.'1' 1, 'RATE'.'1' 1, 'RENEN'.'1' 1, 'LIMRENEW'.'1' 1, 'FRERENEW'.'1' 1, 'CONSRV'.'1' 1, 'ELC'.'1' 1, 'LTHEAT'.'1' 1, 'HTHEAT'.'1' 1, 'GAS'.'1' 1, 'H2G'.'1' 1, 'CO2G'.'1' 1


def run(db):
    """Activity, capacity, commodities, flows and user constraints. Returns the names written."""
    _rpt_opt_defaults(db)
    from . import mlf
    if mlf.on(db):
        # TIMES-MACRO MLF: rpt_ext.mlf writes the report (rptmain.mod 20), rptmisc.rpt inside it
        return mlf.run(db, _misc)
    names = solflo.run(db)
    # solve.stp:127 recomputes salvage for the window; lines 296-321 do not restore it.
    install_last_step(db)
    # rptlite.rpt line 149. coef_objinv is the last call inside rpt_obj, and PAR_NCAPM reads it below.
    obj_names = rptobj.run(db)
    # rptlite.rpt line 153, after rpt_obj and before the capacity report.
    cost_names = cost_ann.run(db)
    names += _misc(db)
    _par_rtcs(db)
    _abs_p_out(db)
    # rpt_ext.cli (rptmain.mod: the reports of the extensions after the main ones): CM_RESULT, CM_MAXC_M
    from . import rptcli
    names += rptcli.run(db)
    return names + ["PAR_RTCS"] + obj_names + cost_names


def _misc(db):
    """rptmisc.rpt (rptlite.rpt line 156; rpt_ext.mlf calls it too)."""
    _r_df(db)
    _par_actl(db)
    _par_actm(db)
    _capacity(db)
    _filter_act(db)
    _commodities(db)
    _flows(db)
    _constraints(db)
    _par_eout(db)
    _levcost(db)
    return ["R_DF", "PAR_ACTL", "PAR_ACTM",
            "PAR_CAPL", "PAR_PASTI", "PAR_CAPM", "PAR_CAPBD", "PAR_NCAPL", "PAR_NCAPM", "PAR_CUMRET",
            "PAR_COMPRDL", "PAR_COMPRDM", "PAR_COMNETL", "PAR_COMNETM", "AGG_OUT",
            "PAR_COMBALEM", "PAR_COMBALGM", "PAR_PEAKM",
            "F_IN", "F_OUT", "P_OUT", "VAL_FLO", "PAR_EOUT",
            "PAR_CUMFLOL", "PAR_CUMFLOM", "PAR_CUMCST", "PAR_UCRTP", "PAR_UCMRK",
            "PAR_UCSL", "PAR_UCSM", "PAR_UCMAX"]


def _rpt_opt_defaults(db):
    """rptlite.rpt line 19, before anything is reported: RPT_OPT('FLO','1')$RPT_OPT('FLO','3')=1.
    (Line 18 turns EPS options into 0; a 0 option is no row here, so it needs nothing.)"""
    if "RPT_OPT" not in db.sym or not (_opt(db, "FLO", "3") or 0):
        return
    db.put("RPT_OPT", "select 'FLO' as u, '1' as j, 1.0 as value")


def _r_df(db):
    """R_DF(R,T) = SIGN(COEF_PVT(R,T))/MAX(1E-9,ABS(COEF_PVT(R,T)));"""
    db.declare("R_DF", "par", ["R", "T"])
    db.put("R_DF", """
        select r, y,
               sign(value) / greatest(1e-9, abs(value)) as value
        from COEF_PVT
    """)


def _par_actl(db):
    """
    PAR_ACTL(RTP_VINTYR(R,V,T,P),S)$PRC_TS(R,P,S) $= VAR_ACT.L(R,V,T,P,S);

    LOOP((RP_STL(R,P,TSL,BD),TS_GROUP(R,TSL,TS))$RLUP(R,'DAYNITE',TSL),
      Z=G_YRFR(R,TS)*365/TS_CYCLE(R,TS);
      YKVAL(VNT(V,T))=SMIN(RS_BELOW(R,TS,S),VAR_ACT.L(R,VNT,P,S)/Z)$NCAP_YES(R,V,P);
      PAR_ACTL(R,VNT,P,S)$(TS_MAP(R,TS,S)$YKVAL(VNT))
        = VAR_ACT.L(R,VNT,P,S)+YKVAL(VNT)*(1-(1+Z)$RS_BELOW(R,TS,S)));
    """
    db.declare("PAR_ACTL", "par", ["R", "LL", "LL", "P", "S"])
    # '$=' of an EPS level stores EPS. L_VAR_ACT holds EPS as a 0 row, so zeros are kept.
    db.put("PAR_ACTL", """
        select a.r, a.y, a.y2, a.p, a.s, a.value as value
        from L_VAR_ACT a
        where in_RTP_VINTYR(a.r, a.y, a.y2, a.p)
          and in_PRC_TS(a.r, a.p, a.s)
    """, zero="eps")
    # one pass per (region, process, parent timeslice); BD is not used in the body
    db.x("""
        create or replace temp table stl as
        select distinct st.r, st.p, g.s as ts,
               v_G_YRFR(st.r, g.s) * 365.0 / v_TS_CYCLE(st.r, g.s) as z
        from RP_STL st
        join TS_GROUP g on g.r = st.r and g.tsl = st.tsl
        where in_RLUP(st.r, 'DAYNITE', st.tsl)
          and v_TS_CYCLE(st.r, g.s) != 0
    """)
    db.x("""
        create or replace temp table ykval as
        select l.r, l.p, l.ts, l.z, n.y, v.y2,
               min(v_L_VAR_ACT(l.r, n.y, v.y2, l.p, b.s2) / l.z) as ykval
        from stl l
        join NCAP_YES n on n.r = l.r and n.p = l.p
        join VNT v on v.y = n.y
        join RS_BELOW b on b.r = l.r and b.s = l.ts
        group by l.r, l.p, l.ts, l.z, n.y, v.y2
        having min(v_L_VAR_ACT(l.r, n.y, v.y2, l.p, b.s2) / l.z) != 0
    """)
    # plain '=' : a zero result removes the record. Two nested RP_STL levels can
    # write the same key; GAMS keeps whichever pass runs last. Identical values
    # collapse. Different values stop here rather than picking one.
    db.x("""
        create or replace temp table shift as
        select k.r, k.y, k.y2, k.p, m.s2 as s,
               v_L_VAR_ACT(k.r, k.y, k.y2, k.p, m.s2)
               + k.ykval * (1 - case when in_RS_BELOW(k.r, k.ts, m.s2) then 1 + k.z else 0 end) as value
        from ykval k
        join TS_MAP m on m.r = k.r and m.s = k.ts
    """)
    clash = db.q("""
        select r, y, y2, p, s, min(value), max(value) from shift
        group by r, y, y2, p, s
        having min(value) <> max(value)
        limit 3
    """)
    if clash:
        raise RuntimeError(
            "RP_STL writes one activity key from two parent timeslices with different values; "
            f"GAMS keeps the last pass. First keys: {clash}")
    db.put("PAR_ACTL", """
        select r, y, y2, p, s, any_value(value) as value from shift
        group by r, y, y2, p, s
    """, zero="delete")


def _par_actm(db):
    """
    Z = (RPT_OPT('ACT','2') GE 0);
    PAR_ACTM(R,V,T,P,S)$VAR_ACT.M(R,V,T,P,S) = ROUND(VAR_ACT.M(R,V,T,P,S)*R_DF(R,T),7)$Z;
    PAR_ACTM(R,'0',T,P,S) $= EQL_ACTBND.M(R,T,P,S)*R_DF(R,T);
    PAR_ACTM(R,'0',T,P,S) $= EQG_ACTBND.M(R,T,P,S)*R_DF(R,T);
    PAR_ACTM(R,'0',T,P,S) $= EQE_ACTBND.M(R,T,P,S)*R_DF(R,T);
    """
    db.declare("PAR_ACTM", "par", ["R", "LL", "LL", "P", "S"])
    z = db.q1("select count(*) from RPT_OPT where u = 'ACT' and j = '2' and value < 0")
    if not z:
        db.put("PAR_ACTM", """
            select a.r, a.y, a.y2, a.p, a.s, round(a.value * v_R_DF(a.r, a.y2), 7) as value
            from M_VAR_ACT a
        """, zero="skip")
    for src, cols in (
        ("M_EQL_ACTBND", "r, y, p, s"),
        ("M_EQG_ACTBND", "r, y, p, s"),
        ("M_EQE_ACTBND", "r, y, p, s"),
    ):
        if src not in db.sym:
            continue
        db.put("PAR_ACTM", f"""
            select r, '0' as y, y as y2, p, s, value * v_R_DF(r, y) as value from "{src}"
        """, zero="skip")


def _capacity(db):
    """
    OPTION CLEAR=RTP_CAPYR,CLEAR=COEF_CAP;
    RTP_CAPYR(RTP_CPTYR(R,TT,T,P))$VAR_NCAP.L(R,TT,P) = YES;
    VAR_CAP.M(RTP)$(NOT VAR_CAP.M(RTP)) $= EQE_CPT.M(RTP);
    PAR_CAPL(RTP(R,T,P)) = SUM(RTP_CAPYR(R,TT,T,P), COEF_CPT(R,TT,T,P)*VAR_NCAP.L(R,TT,P));
    PAR_PASTI(RTP(R,T,P),'0') = SUM(PYR(K)$COEF_CPT(R,K,T,P),
                                    COEF_CPT(R,K,T,P)*NCAP_PASTI(R,K,P)-RTFORC(R,K,T,P)$PYR_S(K));
    $IF DEFINED VNRET
      COEF_CAP(R,V,T,P) $= VAR_SCAP.L(R,V,T,P);
      PAR_PASTI(RTP(R,T,P),'¤')$PRC_RCAP(R,P) =
        -SUM(VNTRT(V,T), COEF_CAP(R,V,T,P)*COEF_CPT(R,V,T,P)-RTFORC(R,V,T,P));
    IF(RPT_OPT('CAP','5')>0, PAR_CUMRET(RTP_CPTYR) $= COEF_CAP(RTP_CPTYR));
    PAR_CAPM(RTP(R,T,P)) $= VAR_CAP.M(RTP)*R_DF(R,T);
    PAR_CAPBD(RTP,'LO') $= CAP_BND(RTP,'LO');
    PAR_CAPBD(RTP_OFF(RTP),'UP')$RCAP_BND(RTP,'N') $= PRC_RESID(RTP);
    PAR_CAPBD(RTP,'UP')$(CAP_BND(RTP,'UP') NE INF) $= CAP_BND(RTP,'UP');
    PAR_NCAPL(RTP(R,V,P)) $= VAR_NCAP.L(RTP);
    PAR_NCAPM(RTP)$(VAR_NCAP.M(RTP)*COEF_OBJINV(RTP)) = VAR_NCAP.M(RTP)/COEF_OBJINV(RTP);

    PYR is an alias of PASTYEAR (setglobs.gms). VNRET is the retirement compile flag;
    a solved model that has VAR_SCAP compiled that line in.
    """
    db.clear("RTP_CAPYR", "COEF_CAP")
    # VAR_NCAP.L controls the index with $, and an EPS level is true there.
    if "L_VAR_NCAP" in db.sym:
        db.add("RTP_CAPYR", """
            select r, y, y2, p from RTP_CPTYR
            where in_L_VAR_NCAP(r, y, p)
        """)
    db.declare("PAR_CAPL", "par", ["R", "T", "P"])
    # A product is EPS when the level or the coefficient is EPS. A sum of only
    # EPS terms is EPS; a numeric term absorbs EPS as zero. Plain '=' drops a zero sum.
    db.x("""
        create or replace temp table capl as
        select t.r, t.y, t.p,
               sum(case when v_L_VAR_NCAP(c.r, c.y, c.p) = 0 or v_COEF_CPT(c.r, c.y, c.y2, c.p) = 0 then 0
                        else v_COEF_CPT(c.r, c.y, c.y2, c.p) * v_L_VAR_NCAP(c.r, c.y, c.p) end) as value,
               sum(case when v_L_VAR_NCAP(c.r, c.y, c.p) = 0
                          or (in_COEF_CPT(c.r, c.y, c.y2, c.p) and v_COEF_CPT(c.r, c.y, c.y2, c.p) = 0)
                        then 1 else 0 end) as neps
        from RTP t
        join RTP_CAPYR c on c.r = t.r and c.y2 = t.y and c.p = t.p
        group by t.r, t.y, t.p
    """)
    db.put("PAR_CAPL", "select r, y, p, value from capl where value <> 0")
    db.put("PAR_CAPL", "select r, y, p, 0 as value from capl where value = 0 and neps > 0", zero="eps")
    # past capacity still online. PYR(K) is PASTYEAR.
    db.declare("PAR_PASTI", "par", ["R", "T", "P", "ITEM"])
    # PYR(K)$COEF_CPT includes an EPS coefficient. EPS minus a real forced retirement is that number negated.
    db.x("""
        create or replace temp table pasti0 as
        select t.r, t.y, t.p,
               sum((case when c.value = 0 or v_NCAP_PASTI(c.r, c.y, c.p) = 0 then 0
                         else c.value * v_NCAP_PASTI(c.r, c.y, c.p) end)
                   - (case when in_PYR_S(c.y) then v_RTFORC(c.r, c.y, c.y2, c.p) else 0 end)) as value,
               sum(case when (c.value = 0 or (in_NCAP_PASTI(c.r, c.y, c.p) and v_NCAP_PASTI(c.r, c.y, c.p) = 0))
                             and not (in_PYR_S(c.y) and v_RTFORC(c.r, c.y, c.y2, c.p) <> 0)
                        then 1 else 0 end) as neps
        from RTP t
        join COEF_CPT c on c.r = t.r and c.y2 = t.y and c.p = t.p
        where in_PASTYEAR(c.y)
        group by t.r, t.y, t.p
    """)
    db.put("PAR_PASTI", "select r, y, p, '0' as u, value from pasti0 where value <> 0")
    db.put("PAR_PASTI", "select r, y, p, '0' as u, 0 as value from pasti0 where value = 0 and neps > 0", zero="eps")
    if "L_VAR_SCAP" in db.sym:
        db.put("COEF_CAP", "select r, y, y2, p, value from L_VAR_SCAP", zero="eps")
        db.x(f"""
            create or replace temp table pasti_ret as
            select t.r, t.y, t.p,
                   -sum((case when v_COEF_CAP(t.r, v.y, t.y, t.p) = 0 or v_COEF_CPT(t.r, v.y, t.y, t.p) = 0
                              then 0
                              else v_COEF_CAP(t.r, v.y, t.y, t.p) * v_COEF_CPT(t.r, v.y, t.y, t.p) end)
                        - v_RTFORC(t.r, v.y, t.y, t.p)) as value,
                   sum(case when ((in_COEF_CAP(t.r, v.y, t.y, t.p) and v_COEF_CAP(t.r, v.y, t.y, t.p) = 0)
                                  or (in_COEF_CPT(t.r, v.y, t.y, t.p) and v_COEF_CPT(t.r, v.y, t.y, t.p) = 0))
                                 and v_RTFORC(t.r, v.y, t.y, t.p) = 0
                            then 1 else 0 end) as neps
            from RTP t
            join VNTRT v on v.y2 = t.y
            where in_PRC_RCAP(t.r, t.p)
              and (in_COEF_CAP(t.r, v.y, t.y, t.p) or in_COEF_CPT(t.r, v.y, t.y, t.p)
                   or v_RTFORC(t.r, v.y, t.y, t.p) <> 0)
            group by t.r, t.y, t.p
        """)
        db.put("PAR_PASTI", f"select r, y, p, '{_RET}' as u, value from pasti_ret where value <> 0")
        db.put("PAR_PASTI",
               f"select r, y, p, '{_RET}' as u, 0 as value from pasti_ret where value = 0 and neps > 0",
               zero="eps")
    db.declare("PAR_CUMRET", "par", ["R", "YEAR", "YEAR", "P"])
    z = db.q1("select value from RPT_OPT where u = 'CAP' and j = '5'")
    if z and z > 0 and db.card("COEF_CAP"):
        db.put("PAR_CUMRET", """
            select c.r, c.y, c.y2, c.p, v_COEF_CAP(c.r, c.y, c.y2, c.p) as value
            from RTP_CPTYR c
            where v_COEF_CAP(c.r, c.y, c.y2, c.p) != 0
        """, zero="skip")
    db.declare("PAR_CAPM", "par", ["R", "T", "P"])
    # NOT VAR_CAP.M is false for an EPS marginal, so the equation marginal does not replace it.
    # EPS times R_DF stays EPS.
    eq_v = "v_M_EQE_CPT(t.r, t.y, t.p)" if "M_EQE_CPT" in db.sym else "0"
    eq_in = "in_M_EQE_CPT(t.r, t.y, t.p)" if "M_EQE_CPT" in db.sym else "false"
    cap_in = "in_M_VAR_CAP(t.r, t.y, t.p)" if "M_VAR_CAP" in db.sym else "false"
    cap_v = "v_M_VAR_CAP(t.r, t.y, t.p)" if "M_VAR_CAP" in db.sym else "0"
    db.x(f"""
        create or replace temp table capm as
        select t.r, t.y, t.p,
               (case when {cap_in} then {cap_v} else {eq_v} end) * v_R_DF(t.r, t.y) as value,
               (case when {cap_in} then {cap_v} = 0 else {eq_in} and {eq_v} = 0 end) as eps
        from RTP t
        where {cap_in} or {eq_in}
    """)
    db.put("PAR_CAPM", "select r, y, p, value from capm where value <> 0", zero="skip")
    db.put("PAR_CAPM", "select r, y, p, 0 as value from capm where eps and value = 0", zero="eps")
    db.declare("PAR_CAPBD", "par", ["R", "T", "P", "BD"])
    if db.card("CAP_BND"):
        db.put("PAR_CAPBD", """
            select b.r, b.y, b.p, 'LO' as l, b.value as value
            from CAP_BND b
            where b.l = 'LO' and in_RTP(b.r, b.y, b.p)
        """, zero="skip")
        db.put("PAR_CAPBD", """
            select b.r, b.y, b.p, 'UP' as l, b.value as value
            from CAP_BND b
            where b.l = 'UP' and in_RTP(b.r, b.y, b.p) and isfinite(b.value)
        """, zero="skip")
    if db.card("RTP_OFF") and db.card("RCAP_BND"):
        db.put("PAR_CAPBD", """
            select a.r, a.y, a.p, 'UP' as l, v_PRC_RESID(a.r, a.y, a.p) as value
            from RTP_OFF a
            where in_RTP(a.r, a.y, a.p) and v_RCAP_BND(a.r, a.y, a.p, 'N') != 0
        """, zero="skip")
    db.declare("PAR_NCAPL", "par", ["R", "V", "P"])
    if "L_VAR_NCAP" in db.sym:
        db.put("PAR_NCAPL", """
            select a.r, a.y, a.p, a.value as value from L_VAR_NCAP a
            where in_RTP(a.r, a.y, a.p)
        """, zero="eps")
    # PAR_NCAPM(RTP)$(VAR_NCAP.M*COEF_OBJINV) = VAR_NCAP.M/COEF_OBJINV.
    # EPS times a nonzero coefficient is EPS, and that product passes the dollar
    # condition, so the stored result is EPS. A zero marginal does not.
    db.declare("PAR_NCAPM", "par", ["R", "V", "P"])
    if "M_VAR_NCAP" in db.sym and db.card("COEF_OBJINV"):
        db.put("PAR_NCAPM", """
            select a.r, a.y, a.p, a.value / v_COEF_OBJINV(a.r, a.y, a.p) as value
            from M_VAR_NCAP a
            where in_RTP(a.r, a.y, a.p) and a.value * v_COEF_OBJINV(a.r, a.y, a.p) != 0
        """)
        db.put("PAR_NCAPM", """
            select a.r, a.y, a.p, 0 as value
            from M_VAR_NCAP a
            where in_RTP(a.r, a.y, a.p) and a.value = 0
              and v_COEF_OBJINV(a.r, a.y, a.p) <> 0
        """, zero="eps")


def _copy_eps(db, dest, src, domain):
    """dest $= src. An EPS source is stored. A source that was never stored is left unset."""
    db.declare(dest, "par", domain)
    if src not in db.sym:
        return
    c = ", ".join(db.cols(dest))
    db.put(dest, f'select {c}, value from "{src}"', zero="eps")


def _marginal_df(db, dest, src, domain):
    """dest $= src * R_DF(R,T).

    EPS times a nonzero discount is EPS, and '$=' stores it. A product that is a
    real zero does not write. The year is the second index.
    """
    db.declare(dest, "par", domain)
    if src not in db.sym:
        return
    cols = db.cols(dest)
    c = ", ".join(cols)
    y = cols[1]
    db.x(f"""
        create or replace temp table scaled as
        select {c},
               case when value = 0 then 0.0 else value * v_R_DF(r, {y}) end as value,
               value = 0 and v_R_DF(r, {y}) <> 0 as eps
        from "{src}"
    """)
    db.put(dest, f"select {c}, value from scaled where value <> 0")
    db.put(dest, f"select {c}, 0 as value from scaled where eps", zero="eps")


def _commodities(db):
    """
    PAR_COMPRDL(R,T,C,S) $= VAR_COMPRD.L(R,T,C,S);
    PAR_COMPRDM(R,T,C,S) $= VAR_COMPRD.M(R,T,C,S)*R_DF(R,T);
    PAR_COMNETL(R,T,C,S) $= VAR_COMNET.L(R,T,C,S);
    PAR_COMNETM(R,T,C,S) $= VAR_COMNET.M(R,T,C,S)*R_DF(R,T);

    OPTION AGR < COM_AGG;
    AGG_OUT(R,T,C,S)$(RTCS_VARC(R,T,C,S)$AGR(R,C)) =
      SUM(RTC(R,T,COM)$COM_AGG(RTC,C), COM_AGG(RTC,C) *
         SUM(RTCS_VARC(RTC,TS)$RS_FR(R,S,TS), RS_FR(R,S,TS)*(1+RTCS_FR(R,T,COM,S,TS)) *
           (VAR_COMNET.L(RTC,TS)$RC_AGP(R,COM,'LO') + VAR_COMPRD.L(RTC,TS)$RC_AGP(R,COM,'FX'))));
    OPTION CLEAR=AGR;

    PAR_COMBALEM(R,T,C,S) $= EQG_COMBAL.M(R,T,C,S)*R_DF(R,T);
    PAR_COMBALEM(R,T,C,S) $= EQE_COMBAL.M(R,T,C,S)*R_DF(R,T);
    PAR_PEAKM(R,T,CG,S)   $= EQ_PEAK.M(R,T,CG,S)*R_DF(R,T);
    $IF %1==S PAR_COMBALGM(RTC,S) $= EQG_COMBAL.L(RTC,S);

    AGR is the projection of COM_AGG onto (R, C) and is cleared at the end of the block,
    so it is not kept. The prefix here is empty, so the PAR_COMBALGM line does not run.
    The second PAR_COMBALEM writes over the first where the equality marginal exists.
    """
    dom = ["R", "T", "C", "S"]
    _copy_eps(db, "PAR_COMPRDL", "L_VAR_COMPRD", dom)
    _marginal_df(db, "PAR_COMPRDM", "M_VAR_COMPRD", dom)
    _copy_eps(db, "PAR_COMNETL", "L_VAR_COMNET", dom)
    _marginal_df(db, "PAR_COMNETM", "M_VAR_COMNET", dom)
    _agg_out(db)
    _marginal_df(db, "PAR_COMBALEM", "M_EQG_COMBAL", dom)
    _marginal_df(db, "PAR_COMBALEM", "M_EQE_COMBAL", dom)
    _marginal_df(db, "PAR_PEAKM", "M_EQ_PEAK", ["R", "T", "CG", "S"])
    db.declare("PAR_COMBALGM", "par", dom)


def _live(db, name, call, absent):
    """in_/v_ call when the symbol was loaded, otherwise a constant."""
    return call if name in db.sym else absent


def _agg_out(db):
    """See _commodities. Plain '=' drops a zero sum. A sum of only EPS terms stays EPS."""
    db.declare("AGG_OUT", "par", ["R", "T", "C", "S"])
    if "COM_AGG" not in db.sym or "RS_FR" not in db.sym or "RTCS_VARC" not in db.sym:
        return
    if not db.card("COM_AGG"):
        return
    net_in = _live(db, "L_VAR_COMNET", "in_L_VAR_COMNET(g.r, g.y, g.c, f.s2)", "false")
    net_v = _live(db, "L_VAR_COMNET", "v_L_VAR_COMNET(g.r, g.y, g.c, f.s2)", "0")
    prd_in = _live(db, "L_VAR_COMPRD", "in_L_VAR_COMPRD(g.r, g.y, g.c, f.s2)", "false")
    prd_v = _live(db, "L_VAR_COMPRD", "v_L_VAR_COMPRD(g.r, g.y, g.c, f.s2)", "0")
    lo = _live(db, "RC_AGP", "in_RC_AGP(g.r, g.c, 'LO')", "false")
    fx = _live(db, "RC_AGP", "in_RC_AGP(g.r, g.c, 'FX')", "false")
    fr = _live(db, "RTCS_FR", "v_RTCS_FR(g.r, g.y, g.c, f.s, f.s2)", "0")
    # 1+RTCS_FR absorbs EPS, so an EPS fraction does not make the product EPS.
    # EPS*0 is 0, including a zero (1+RTCS_FR). A numeric term absorbs EPS in the sum.
    db.x(f"""
        create or replace temp table agg_ts as
        select g.r, g.y, g.c as com, g.c2 as c, f.s, g.value as w,
               (1 + {fr}) as scale,
               v_RS_FR(g.r, f.s, f.s2) as rs,
               v_RS_FR(g.r, f.s, f.s2) = 0 as rs_eps,
               ({lo} and {net_in} and {net_v} <> 0) as net_num,
               ({lo} and {net_in} and {net_v} = 0) as net_eps,
               {net_v} as net,
               ({fx} and {prd_in} and {prd_v} <> 0) as prd_num,
               ({fx} and {prd_in} and {prd_v} = 0) as prd_eps,
               {prd_v} as prd
        from COM_AGG g
        join RS_FR f on f.r = g.r
        where in_RTCS_VARC(g.r, g.y, g.c, f.s2)
    """)
    db.x("""
        create or replace temp table agg_com as
        select r, y, com, c, s, any_value(w) as w,
               sum(case when piece_eps then 0 else piece end) as value,
               sum(case when piece_eps then 1 else 0 end) as neps
        from (
            select r, y, com, c, s, w,
                   (net_num or prd_num) as lvl_num,
                   ((net_eps or prd_eps) and not (net_num or prd_num)) as lvl_eps,
                   (case when net_num then net else 0 end) + (case when prd_num then prd else 0 end) as lvl,
                   scale, rs, rs_eps
            from agg_ts
        ) t
        cross join lateral (
            select
                (scale <> 0 and (lvl_eps or (rs_eps and lvl_num and lvl <> 0))) as piece_eps,
                case
                    when scale = 0 or not lvl_num or lvl_eps or rs_eps then 0
                    else rs * scale * lvl
                end as piece
        ) p
        group by r, y, com, c, s
    """)
    # COM_AGG is EPS when its stored value is 0. EPS times a zero sum is 0.
    db.x("""
        create or replace temp table agg_sum as
        select r, y, c, s,
               sum(case when prod_eps then 0 else prod end) as value,
               sum(case when prod_eps then 1 else 0 end) as neps
        from (
            select r, y, c, s,
                   (value = 0 and neps = 0) as inner_zero,
                   (value = 0 and neps > 0) as inner_eps,
                   w = 0 as w_eps,
                   w, value
            from agg_com
        ) t
        cross join lateral (
            select
                (not inner_zero and (w_eps or inner_eps)) as prod_eps,
                case when inner_zero or w_eps or inner_eps then 0 else w * value end as prod
        ) p
        group by r, y, c, s
    """)
    db.put("AGG_OUT", """
        select r, y, c, s, value from agg_sum
        where value <> 0 and in_RTCS_VARC(r, y, c, s)
    """)
    db.put("AGG_OUT", """
        select r, y, c, s, 0 as value from agg_sum
        where value = 0 and neps > 0 and in_RTCS_VARC(r, y, c, s)
    """, zero="eps")


def _filter_act(db):
    """Z=RPT_OPT('ACT','9'); IF(Z>0, PAR_ACTL(R,V,T,P,S)$((PAR_ACTL<Z)$PAR_ACTL)=0);"""
    z = db.q1("select value from RPT_OPT where u = 'ACT' and j = '9'")
    if z and z > 0:
        # $PAR_ACTL is true for EPS, and EPS (or a negative level) is below Z: both go
        db.zap("PAR_ACTL", f"value < {float(z)}")


def _opt(db, item, j):
    if "RPT_OPT" not in db.sym:
        return None
    return db.q1(f"select value from RPT_OPT where u = '{item}' and j = '{j}'")


def _flows(db):
    """rptmisc.rpt lines 70-148. F_IN, F_OUT, then the completion of production and net."""
    _f_inout(db)
    _f_in_out(db)
    db.clear("F_INOUTS")
    _small_values(db)
    _flow_timeslices(db)
    _complete_com(db)
    _val_flo(db)


def _par_eout(db):
    """Electricity supply by energy source. rptmisc.rpt lines 194-211.

        $IF SOLANS==YES  RPT_OPT('FLO','5') = 1;
        IF(RPT_OPT('FLO','5'),
          TRACKP(R,P)$SUM(TOP(RPC_SPG,'IN')$NRGELC, 1) = YES;
          TRACKPC(RPC(RP_FLO))$(TOP(...,'OUT')$NRGELC) = YES;
          TRACKPC(TRACKP,C) = NO;  OPTION TRACKP < TRACKPC;
          TRACKPG(TRACKP,C)$((NOT NRGELC)$NRG$TOP(...,'IN')) = YES;
          F_VIO(RTP_VINTYR,IO)$TRACKP = SUM(F_OUT)$((NOT IPS(IO))) + SUM(F_IN)$IPS(IO) + 1 - 1;
          PAR_EOUT(RTP_VINTYR,C)$(F_VIO(...,'IN')$TRACKPG) =
              F_VIO(...,'OUT') / F_VIO(...,'IN') * SUM(S$F_IN, F_IN);
          CLEAR TRACKPC;
          LOOP(TOP_IRE(R,C,NRGELC(R,COM),P), TRACKPC(R,P,C)=YES; TRACKPC(R,P,COM)=YES);
          KEEP_FLOF(RPC)$(NOT TRACKPC) $= SUM(RPC_IRE,1)$NRGELC;
          PAR_EOUT(RTP_VINTYR,C)$(KEEP_FLOF$RP_IRE) =
              SUM(F_OUT)$RPC_IRE(...,'IMP') - SUM(F_IN)$RPC_IRE(...,'EXP'));

    IPS is /IN, N/, so the OUT total is electricity output and the IN total is
    the fuel input. +1-1 stores EPS when that sum is zero. The GAMSPy reading of
    the same statements is rptmisc_rpt.py; 4.9.8 is the source of this block.
    These runs do not set the option, so the body does not run.
    """
    db.declare("PAR_EOUT", "par", ["R", "ALLYEAR", "T", "P", "C"])
    db.clear("PAR_EOUT")
    if not _opt(db, "FLO", "5"):
        return
    need = ("TOP", "RPC_SPG", "NRGELC", "RP_FLO", "NRG", "RTP_VINTYR", "F_IN", "F_OUT")
    if not all(n in db.sym for n in need):
        return
    # rptmain.mod line 19 includes solsetv.v3 before the report on a Veda run.
    # solsetv.v3 line 150: NRGELC(NRG(R,C)) $= NRG_TMAP(R,'ELC',C).
    if "NRG_TMAP" in db.sym:
        db.add("NRGELC", """
            select n.r, n.c from NRG n
            where in_NRG_TMAP(n.r, 'ELC', n.c)
        """)
    db.x("""
        create or replace temp table eout_in as
        select distinct t.r, t.p
        from TOP t
        join RPC_SPG g on g.r = t.r and g.p = t.p and g.c = t.c
        where t.io = 'IN' and in_NRGELC(t.r, t.c)
    """)
    db.x("""
        create or replace temp table eout_pc as
        select distinct t.r, t.p, t.c
        from TOP t
        join RP_FLO f on f.r = t.r and f.p = t.p
        where t.io = 'OUT' and in_NRGELC(t.r, t.c)
          and not exists (select 1 from eout_in i where i.r = t.r and i.p = t.p)
    """)
    db.x("""
        create or replace temp table eout_p as
        select distinct r, p from eout_pc
    """)
    db.x("""
        create or replace temp table eout_pg as
        select distinct t.r, t.p, t.c
        from TOP t
        join eout_p p on p.r = t.r and p.p = t.p
        where t.io = 'IN' and not in_NRGELC(t.r, t.c) and in_NRG(t.r, t.c)
    """)
    # +1-1: a zero sum is EPS, a nonzero sum absorbs it.
    db.x("""
        create or replace temp table eout_vio as
        select v.r, v.y, v.y2, v.p, q0.io,
               coalesce(q.value, 0) as value
        from RTP_VINTYR v
        join eout_p p on p.r = v.r and p.p = v.p
        cross join (select 'OUT' as io union all select 'IN') q0
        left join (
            select o.r, o.y, o.y2, o.p, 'OUT' as io,
                   sum(o.value order by o.c, o.s) as value
            from F_OUT o
            join eout_pc pc on pc.r = o.r and pc.p = o.p and pc.c = o.c
            group by o.r, o.y, o.y2, o.p
            union all
            select i.r, i.y, i.y2, i.p, 'IN' as io,
                   sum(i.value order by i.c, i.s) as value
            from F_IN i
            join eout_pg pg on pg.r = i.r and pg.p = i.p and pg.c = i.c
            group by i.r, i.y, i.y2, i.p
        ) q on q.r = v.r and q.y = v.y and q.y2 = v.y2 and q.p = v.p and q.io = q0.io
    """)
    # A zero fuel total is EPS (+1-1), and $EPS is true, so GAMS divides by EPS
    # and stores UNDF. Those rows are left unwritten.
    db.x("""
        create or replace temp table eout_fuel as
        select i.r, i.y, i.y2, i.p, i.c,
               sum(i.value order by i.s) as value,
               case when sum(i.value order by i.s) = 0
                     and arg_max(i.value, i.s) = 0 then 1 else 0 end as is_eps
        from F_IN i
        join eout_pg g on g.r = i.r and g.p = i.p and g.c = i.c
        group by i.r, i.y, i.y2, i.p, i.c
    """)
    db.x("""
        create or replace temp table eout_share as
        select v.r, v.y, v.y2, v.p, g.c,
               case when f.is_eps = 0 and f.value <> 0 and vout.value <> 0
                    then vout.value / vin.value * f.value else 0 end as value,
               case when (vout.value = 0 and f.value <> 0)
                      or (f.is_eps = 1 and (vout.value <> 0 or f.value = 0))
                    then 1 else 0 end as is_eps
        from eout_vio vin
        join eout_vio vout on vout.r = vin.r and vout.y = vin.y and vout.y2 = vin.y2
                          and vout.p = vin.p and vout.io = 'OUT'
        join eout_pg g on g.r = vin.r and g.p = vin.p
        left join eout_fuel f on f.r = vin.r and f.y = vin.y and f.y2 = vin.y2
                             and f.p = vin.p and f.c = g.c
        join RTP_VINTYR v on v.r = vin.r and v.y = vin.y and v.y2 = vin.y2 and v.p = vin.p
        where vin.io = 'IN' and vin.value <> 0
    """)
    db.put("PAR_EOUT", "select r, y, y2, p, c, value from eout_share where is_eps = 0")
    db.put("PAR_EOUT", "select r, y, y2, p, c, 0 as value from eout_share where is_eps = 1",
           zero="eps")
    if "TOP_IRE" not in db.sym:
        return
    db.x("""
        create or replace temp table eout_tie as
        select r, p, c from (
            select k.r, k.p, k.c as c
            from TOP_IRE k
            where k.r2 = k.r and in_NRGELC(k.r, k.c2)
            union
            select k.r, k.p, k.c2 as c
            from TOP_IRE k
            where k.r2 = k.r and in_NRGELC(k.r, k.c2)
        ) q
    """)
    if "RPC_IRE" not in db.sym or "RP_IRE" not in db.sym:
        return
    db.x("""
        create or replace temp table eout_keep as
        select i.r, i.p, i.c
        from RPC_IRE i
        join RP_IRE rp on rp.r = i.r and rp.p = i.p
        where in_NRGELC(i.r, i.c)
          and not exists (select 1 from eout_tie t
                          where t.r = i.r and t.p = i.p and t.c = i.c)
        group by i.r, i.p, i.c
    """)
    db.x("""
        create or replace temp table eout_side as
        select v.r, v.y, v.y2, v.p, k.c,
               coalesce((select sum(o.value order by o.s) from F_OUT o
                         where o.r = v.r and o.y = v.y and o.y2 = v.y2 and o.p = v.p and o.c = k.c
                           and in_RPC_IRE(k.r, k.p, k.c, 'IMP')), 0) as fout,
               coalesce((select sum(i.value order by i.s) from F_IN i
                         where i.r = v.r and i.y = v.y and i.y2 = v.y2 and i.p = v.p and i.c = k.c
                           and in_RPC_IRE(k.r, k.p, k.c, 'EXP')), 0) as fin
        from eout_keep k
        join RTP_VINTYR v on v.r = k.r and v.p = k.p
    """)
    # Plain '=' replaces the fuel share. A zero result deletes the row.
    db.put("PAR_EOUT", """
        select r, y, y2, p, c, fout - fin as value from eout_side
    """)


def _f_inout(db):
    """
    F_INOUT(R,V,T,P,C,'IN')$COEF_ICOM = COEF_ICOM * RTP_CAPVL;
    F_INOUT(R,V,T,P,C,'OUT')$COEF_OCOM = COEF_OCOM * RTP_CAPVL
      + SUM(VNTRT(V,TT(LL+MIN(VN2T(V,T),RVPRL))), (-COEF_OCOM*VAR_SCAP.L + COEF_RCOM*VAR_RCAP.L)$RCAP_OCAP);
    F_INOUT(RTP_CPTYR(R,V,T,P),C,IO)$NCAP_COM(R,V,P,C,IO) = F_INOUT + (RTP_CAPVL-COEF_CAP)*COEF_CPT*NCAP_COM*(1+COEF_CIO);
    F_INOUTS(R,V,T,P,C,ANNUAL,IO)$F_INOUT = F_INOUTS + F_INOUT;
    The lagged sum is controlled by $RCAP_OCAP. Without RCAP_OCAP the sum is 0 (with it, the step stops).
    """
    db.declare("F_INOUT", "par", ["R", "ALLYEAR", "T", "P", "C", "IO"])
    db.clear("F_INOUT")
    if "RCAP_OCAP" in db.sym and db.card("RCAP_OCAP"):
        raise RuntimeError(
            "F_INOUT retirement lag (rptmisc.rpt lines 72-73) is not ported; RCAP_OCAP has rows")
    cap = "v_RTP_CAPVL(g.r, g.y, g.p)" if "RTP_CAPVL" in db.sym else "0"
    for src, io in (("COEF_ICOM", "IN"), ("COEF_OCOM", "OUT")):
        if src not in db.sym or not db.card(src):
            continue
        # an EPS coefficient (an input given as 0) times a non-zero capacity is EPS and stays on record;
        # a zero capacity makes a plain 0, which the assignment removes
        db.put("F_INOUT", f"""
            select g.r, g.y, g.y2, g.p, g.c, '{io}' as io, g.value * {cap} as value
            from "{src}" g where {cap} <> 0
        """, zero="eps")
    # --- F_INOUT(RTP_CPTYR(R,V,T,P),C,IO)$NCAP_COM(R,V,P,C,IO) = F_INOUT(R,V,T,P,C,IO) +
    #       (RTP_CAPVL(R,V,P)-COEF_CAP(R,V,T,P)) * COEF_CPT(R,V,T,P) * NCAP_COM(R,V,P,C,IO) * (1+COEF_CIO(R,V,T,P,C,IO));
    #     rptmisc.rpt lines 74-75: the flows tied to the installed capacity over its life (NCAP_COM)
    if "NCAP_COM" in db.sym and db.card("NCAP_COM") and "RTP_CPTYR" in db.sym:
        n, k = db.cols("NCAP_COM"), db.cols("RTP_CPTYR")
        capvl = "v_RTP_CAPVL(k.{0}, k.{1}, k.{3})" if "RTP_CAPVL" in db.sym else "0"
        cap = "v_COEF_CAP(k.{0}, k.{1}, k.{2}, k.{3})" if "COEF_CAP" in db.sym else "0"
        cpt = "v_COEF_CPT(k.{0}, k.{1}, k.{2}, k.{3})" if "COEF_CPT" in db.sym else "0"
        cio = "v_COEF_CIO(k.{0}, k.{1}, k.{2}, k.{3}, n.{c}, n.{io})" if "COEF_CIO" in db.sym else "0"
        expr = f"({capvl} - {cap}) * {cpt} * n.value * (1 + {cio})".format(*k, c=n[3], io=n[4])
        db.put("F_INOUT", f"""
            select k.{k[0]}, k.{k[1]}, k.{k[2]}, k.{k[3]}, n.{n[3]}, n.{n[4]},
                   v_F_INOUT(k.{k[0]}, k.{k[1]}, k.{k[2]}, k.{k[3]}, n.{n[3]}, n.{n[4]}) + {expr} as value
            from RTP_CPTYR k join "NCAP_COM" n on n.{n[0]} = k.{k[0]} and n.{n[1]} = k.{k[1]} and n.{n[2]} = k.{k[3]}
            where n.value <> 0
        """)
    if db.card("F_INOUT"):
        # $F_INOUT holds for EPS; old + EPS is EPS (kept), a sum that cancels to 0 is removed
        db.put("F_INOUTS", """
            select r, y, y2, p, c, 'ANNUAL' as s, io,
                   value + v_F_INOUTS(r, y, y2, p, c, 'ANNUAL', io) as value
            from F_INOUT
            where not (value <> 0 and value + v_F_INOUTS(r, y, y2, p, c, 'ANNUAL', io) = 0)
        """, zero="eps")


def _f_in_out(db):
    """
    F_IN(R,V,T,P,C,S)$TOP(R,P,C,'IN') $= PAR_FLO;
    F_IN $= PAR_IRE(...,'EXP');
    F_IN$RPCS_VAR $= VAR_SIN.L;
    F_IN$F_INOUTS(...,'IN') = F_IN + F_INOUTS;
    PAR_FLO$RPCS_VAR $= VAR_SOUT.L * STG_EFF;
    F_OUT$TOP(...,'OUT') $= PAR_FLO;
    F_OUT $= PAR_IRE(...,'IMP');
    F_OUT$F_INOUTS(...,'OUT') = F_OUT + F_INOUTS;
    """
    flo = ["R", "ALLYEAR", "T", "P", "C", "S"]
    db.declare("F_IN", "par", flo)
    db.declare("F_OUT", "par", flo)
    db.put("F_IN", """
        select r, y, y2, p, c, s, value from PAR_FLO
        where in_TOP(r, p, c, 'IN')
    """, zero="eps")
    db.put("F_IN", "select r, y, y2, p, c, s, value from PAR_IRE where ie = 'EXP'", zero="eps")
    if "L_VAR_SIN" in db.sym:
        db.put("F_IN", """
            select r, y, y2, p, c, s, value from L_VAR_SIN
            where in_RPCS_VAR(r, p, c, s)
        """, zero="eps")
    if db.card("F_INOUTS"):
        db.put("F_IN", """
            select r, y, y2, p, c, s, v_F_IN(r, y, y2, p, c, s) + value as value
            from F_INOUTS where io = 'IN'
              and not (value <> 0 and v_F_IN(r, y, y2, p, c, s) + value = 0)
        """, zero="eps")
    if "L_VAR_SOUT" in db.sym:
        eff = "v_STG_EFF(r, y, p)" if "STG_EFF" in db.sym else "1"
        db.put("PAR_FLO", f"""
            select r, y, y2, p, c, s, value * {eff} as value from L_VAR_SOUT
            where in_RPCS_VAR(r, p, c, s)
        """, zero="eps")
    db.put("F_OUT", """
        select r, y, y2, p, c, s, value from PAR_FLO
        where in_TOP(r, p, c, 'OUT')
    """, zero="eps")
    db.put("F_OUT", "select r, y, y2, p, c, s, value from PAR_IRE where ie = 'IMP'", zero="eps")
    if db.card("F_INOUTS"):
        db.put("F_OUT", """
            select r, y, y2, p, c, s, v_F_OUT(r, y, y2, p, c, s) + value as value
            from F_INOUTS where io = 'OUT'
              and not (value <> 0 and v_F_OUT(r, y, y2, p, c, s) + value = 0)
        """, zero="eps")


def _small_values(db):
    """The RPT_OPT(*,'9') block. A value whose absolute value is below the threshold is removed."""
    if "RPT_OPT" not in db.sym:
        return
    groups = db.q("select u from RPT_OPT where j = '9' and value > 0.1")
    for (item,) in groups:
        db.x(f"update RPT_OPT set value = 0 where u = '{item}' and j = '9' and value > 0.1")
    for item, table, absolute in (
        ("ACT", "PAR_ACTL", False),
        ("CAP", "PAR_CAPL", False),
        ("NCAP", "PAR_NCAPL", False),
        ("FLO", "F_OUT", True),
        ("COMPRD", "PAR_COMPRDL", True),
        ("COMNET", "PAR_COMNETL", True),
    ):
        z = _opt(db, item, "9")
        if z and z > 0 and table in db.sym:
            # X$((X<Z)$X)=0: the $X is true for EPS too, and EPS < Z, so EPS records go as well;
            # without ABS a negative value is below the threshold and goes too.
            test = f"abs(value) < {float(z)}" if absolute else f"value < {float(z)}"
            db.zap(table, test)
    z = _opt(db, "CAP", "9")
    if z and z > 0 and "PAR_PASTI" in db.sym:
        db.zap("PAR_PASTI", f"u = '{_RET}' and abs(value) < {float(z)}")
    z = _opt(db, "FLO", "9")
    if z and z > 0:
        db.zap("F_IN", f"abs(value) < {float(z)}")


def _flow_timeslices(db):
    """
    Reporting stays on COM_TS when RPT_OPT('FLO','1') is at least 1.
    %RPT_FLOTS% is unset in a Veda run, so the ANNUAL-only branch is not compiled
    and an absent option leaves RCS empty: flows stay on the slices they were written on.
    """
    db.declare("P_OUT", "par", ["R", "T", "P", "C", "S"])
    db.declare("VAL_FLO", "par", ["R", "ALLYEAR", "LL", "PRC", "C"])
    flo1 = _opt(db, "FLO", "1") or 0
    # --- UNCD1(U2(COM_TYPE))$RPT_OPT(U2,'3')=YES; UNCD1(U2(NRG_TYPE))$RPT_OPT(U2,'1')=YES;
    #     RPT_OPT('FLO','1')$CARD(UNCD1)=YES;    (rptmisc.rpt 100-102: power levels or a fall-back need COM_TS)
    if "RPT_OPT" in db.sym and db.card("RPT_OPT"):
        types = []
        for name, j in (("COM_TYPE", "3"), ("NRG_TYPE", "1")):
            if name in db.sym and db.card(name):
                t = db.cols(name)[0]
                types.append(f"""select 1 from RPT_OPT o join "{name}" m on upper(m.{t}) = upper(o.u)
                                 where o.j = '{j}' and o.value <> 0""")
        if types and db.q1(f"select count(*) from ({' union all '.join(types)})"):
            flo1 = 1
    db.rcs_on = False
    if flo1 >= 1 and "COM_TS" in db.sym:
        db.declare("RCS", "set", ["R", "C", "S"])
        db.assign("RCS", "select r, c, s from COM_TS")
        db.rcs_on = bool(db.card("RCS"))
        _redistribute(db, "F_IN")
        _redistribute(db, "F_OUT")
        db.clear("RCS")


def _eps_sum(db, name, select, keys, mode):
    """Assign name from `select` (keys, value): a GAMS SUM with EPS. The terms are the rows of `select`;
    a row whose value is 0 is an EPS term (a product of present records, one of them EPS). The sum is
    the numeric total when it is not 0; EPS when every term is EPS; nothing when there are no terms.
        mode 'set'  : '='  over the keys the select returns (a total that cancels to 0 deletes the record)
        mode 'dollar': '$=' (only a nonzero or EPS result is assigned)"""
    k = ", ".join(keys)
    db.x(f"""create or replace temp table eps_sum as
             select {k}, sum(value) as value, bool_and(value = 0) as all_eps
             from ({select}) t group by {k}""")
    if mode == "set":
        # a nonzero total, or EPS; a total that cancels to 0 removes the old record
        db.put(name, f"select {k}, value from eps_sum where value <> 0 or all_eps", zero="eps")
        on = " and ".join(f"o_.{c} = e.{c}" for c in keys)
        db.x(f'delete from "{name}" o_ where exists (select 1 from eps_sum e where {on} and e.value = 0 and not e.all_eps)')
    else:
        db.put(name, f"select {k}, value from eps_sum where value <> 0 or all_eps", zero="eps")


def _comprdl_ts(db):
    """rptmisc.rpt line 125, in the branch where the flows are at COM_TS:
    PAR_COMPRDL(RTCS_VARC(RTTC(R,T,C)),S) = SUM((VNT(V,T),P)$F_OUT(R,V,T,P,C,S),F_OUT(R,V,T,P,C,S));
    A plain '=' over the domain: a key of the domain with no output loses its earlier record."""
    if "RTCS_VARC" not in db.sym or not db.q1("select count(*) from rttc_w"):
        return
    db.x("""create or replace temp table comprd_dom as
            select d.r, d.y, d.c, d.s from RTCS_VARC d
            join rttc_w t on t.r = d.r and t.y = d.y and t.c = d.c""")
    db.x("""create or replace temp table comprd_new as
            select d.r, d.y, d.c, d.s, sum(f.value) as value, bool_and(f.value = 0) as all_eps
            from comprd_dom d
            join F_OUT f on f.r = d.r and f.y2 = d.y and f.c = d.c and f.s = d.s and in_VNT(f.y, f.y2)
            group by d.r, d.y, d.c, d.s""")
    # every key of the domain is assigned: those without a result (or with a cancelled sum) go
    db.x("""delete from PAR_COMPRDL o_ where exists (select 1 from comprd_dom d
              where d.r = o_.r and d.y = o_.y and d.c = o_.c and d.s = o_.s)""")
    db.put("PAR_COMPRDL", "select r, y, c, s, value from comprd_new where value <> 0 or all_eps", zero="eps")


def _p_out(db):
    """rptmisc.rpt lines 127-131, the optional power levels, for each energy type with RPT_OPT(type,'1'):
    F=(ROUND(RPT_OPT(U2,'3'))=2);
    P_OUT(RTPC(R,T,P,C),S)$(COM_TS(R,C,S)$NRG_TMAP(R,NRG_TYPE,C)) =
        SUM(VNT(V,T)$F_OUT, F_OUT/G_YRFR(R,S)/RPT_OPT(U2,'1')) - SUM(VNT(V,T)$F_IN, F_IN/G_YRFR/RPT_OPT(U2,'1'))$F;
    ELC.3 = 2 makes the level net of the process inputs of the same commodity (storage, own use)."""
    if "RPT_OPT" not in db.sym or "NRG_TMAP" not in db.sym or "NRG_TYPE" not in db.sym:
        return
    nt = db.cols("NRG_TMAP")[1]
    types = db.q(f"""select o.u, o.value from RPT_OPT o
                     where o.j = '1' and o.value <> 0
                       and exists (select 1 from NRG_TYPE n where upper(n.{db.cols('NRG_TYPE')[0]}) = upper(o.u))
                     order by o.u""")
    for u, div in types:
        f3 = _opt(db, u, "3") or 0
        net = round(f3) == 2
        terms = f"""
            select f.r, f.y2 as y, f.p, f.c, f.s, f.value / v_G_YRFR(f.r, f.s) / {float(div)} as value
            from F_OUT f
            where in_VNT(f.y, f.y2)"""
        if net:
            terms += f"""
            union all
            select f.r, f.y2 as y, f.p, f.c, f.s, -f.value / v_G_YRFR(f.r, f.s) / {float(div)} as value
            from F_IN f
            where in_VNT(f.y, f.y2)"""
        dom = f"""in_RTPC(t.r, t.y, t.p, t.c) and in_COM_TS(t.r, t.c, t.s)
                  and exists (select 1 from NRG_TMAP m where m.r = t.r and upper(m.{nt}) = '{u.upper()}' and m.c = t.c)"""
        _eps_sum(db, "P_OUT", f"select * from ({terms}) t where {dom}", ["r", "y", "p", "c", "s"], "set")


def _val_flo(db):
    """rptmisc.rpt lines 133-142, the value of each flow at the commodity marginal (RPT_OPT('FLO','3')):
    VAL_FLO(R,V,T,P,C) $= SUM(S$F_IN, F_IN*PAR_COMBALEM(R,T,C,S));
    F_INOUTS(R,V,T,P,C,ANNUAL,'OUT') $= SUM(S$F_OUT, F_OUT*PAR_COMBALEM);
    VAL_FLO$F_INOUTS(...,'OUT') = VAL_FLO - F_INOUTS(...,'OUT');
    Inputs count positive, outputs negative. Z is the option itself, but with STAGES (line 136):
    $IFI %STAGES%==YES Z = ROUND(Z/10);"""
    z = _opt(db, "FLO", "3") or 0
    if getattr(db, "stages", None):
        z = float(int(abs(z) / 10 + 0.5)) * (1 if z >= 0 else -1)
    if not z:
        return
    term = """select f.r, f.y, f.y2, f.p, f.c, f.value * m.value as value
              from {t} f join PAR_COMBALEM m on m.r = f.r and m.y = f.y2 and m.c = f.c and m.s = f.s"""
    _eps_sum(db, "VAL_FLO", term.format(t="F_IN"), ["r", "y", "y2", "p", "c"], "dollar")
    k = ["r", "y", "y2", "p", "c"]
    db.x(f"""create or replace temp table val_out as
             select r, y, y2, p, c, sum(value) as value, bool_and(value = 0) as all_eps
             from ({term.format(t="F_OUT")}) t group by r, y, y2, p, c""")
    # $= : the outputs whose sum is nonzero or EPS; then VAL_FLO = VAL_FLO - that, a plain '='
    db.x("delete from val_out where value = 0 and not all_eps")
    db.x("""create or replace temp table val_new as
            select o.r, o.y, o.y2, o.p, o.c,
                   coalesce(v.value, 0) - o.value as value,
                   (v.value is null or v.value = 0) and o.all_eps as eps
            from val_out o
            left join VAL_FLO v on v.r = o.r and v.y = o.y and v.y2 = o.y2 and v.p = o.p and v.c = o.c""")
    db.x("""delete from VAL_FLO v where exists (select 1 from val_new n
              where n.r = v.r and n.y = v.y and n.y2 = v.y2 and n.p = v.p and n.c = v.c)""")
    db.put("VAL_FLO", "select r, y, y2, p, c, value from val_new where value <> 0 or eps", zero="eps")


def _levcost(db):
    """rptmisc.rpt lines 212-266, the levelized cost of new capacity, PAR_NCAPR(R,V,P,'LEVCOST'), when
    RPT_OPT('NCAP','1') is set. F=1 (the usual value): costs of the process per unit of its main output,
    discounted to the base year: the investment (COEF_RTP, rpt_objc.rpt), activity and flow costs, the
    inputs valued at their commodity marginals, less the value of the outputs that are not the main output
    (and of the main output of a CHP that is not electricity), less a peak-capacity credit:

      NCAP_YES(R,T,P)$(VAR_NCAP.L*COEF_RTP$(RP_INOUT(R,P,'OUT')+PRC_PKAF(R,P))=0)=NO;
      PASTSUM(R,T,P)$PAR_CAPL = PAR_CAPL+SUM(PASTCV,PAR_PASTI(R,T,P,PASTCV))+1-1;
      TRACKPC: outputs of ELE/CHP/HPL processes that are NRG and not (PG and (ELC or not CHP));
      RP_GRP(RPC_PG(RP_PRC,C))$(NOT TRACKPC) (F=1): main outputs, not credited;
      PAR_RTCS (peak marginal / (1+reserve) by timeslice) and TRACKPG for the outputs of a peak commodity;
      PAR_NCAPR(NCAP_YES(R,TT(V),P),'LEVCOST') = (vintaged / non-vintaged formula) / MAX(MICRO, main output).
    Taken only for F = 1 (RPT_OPT('NCAP','1') = 1). F < 0 (the ENV credit and the COEF_CAP aux share) and
    F > 1 (the peak capacity term on RPC_PKC processes) are not ported: nothing is written, and the run report
    names the option (switches.py)."""
    f = _opt(db, "NCAP", "1") or 0
    if f != 1:
        return
    coef = "coef_rtp_cnt"
    if not db.q1(f"select count(*) from information_schema.tables where table_name = '{coef}'"):
        return
    db.declare("PAR_NCAPR", "par", ["R", "ALLYEAR", "P", "ITEM"])
    # NCAP_YES(R,T,P)$(...=0) = NO, over the periods only
    outp = "in_RP_INOUT(n.r, n.p, 'OUT')" if "RP_INOUT" in db.sym else "false"
    pkaf = "in_PRC_PKAF(n.r, n.p)" if "PRC_PKAF" in db.sym else "false"
    db.x(f"""delete from NCAP_YES n where in_MILESTONYR(n.y) and not (
                v_L_VAR_NCAP(n.r, n.y, n.p) <> 0
                and coalesce((select c.value from {coef} c where c.r = n.r and c.y = n.y and c.p = n.p), 0) <> 0
                and ({outp} or {pkaf}))""")
    # PASTSUM(R,T,P)$PAR_CAPL = PAR_CAPL + SUM(PASTCV, PAR_PASTI) +1-1
    db.x("""create or replace temp table lev_pastsum as
            select c.r, c.y, c.p, c.value + coalesce((select sum(pp.value) from PAR_PASTI pp
                   where pp.r = c.r and pp.y = c.y and pp.p = c.p), 0) as value
            from PAR_CAPL c""")
    # NRGELC (solsetv.v3 150): NRG commodities mapped to the ELC energy type
    nt = db.cols("NRG_TMAP")[1] if "NRG_TMAP" in db.sym else None
    nrgelc = (f"(in_NRG(x.r, x.c) and exists (select 1 from NRG_TMAP m where m.r = x.r and upper(m.{nt}) = 'ELC' and m.c = x.c))"
              if nt else "false")
    # RP_PRC < NCAP_YES; TRACKP = ELE+CHP+HPL; TRACKPC: their NRG outputs, not (PG and (NRGELC or not CHP))
    kinds = " or ".join(f"in_{k}(n.r, n.p)" for k in ("ELE", "CHP", "HPL") if k in db.sym) or "false"
    chp = "in_CHP(x.r, x.p)" if "CHP" in db.sym else "false"
    db.x(f"""create or replace temp table lev_trackpc as
             select distinct x.r, x.p, x.c from TOP x
             join (select distinct n.r, n.p from NCAP_YES n where {kinds}) k on k.r = x.r and k.p = x.p
             where x.io = 'OUT' and in_NRG(x.r, x.c)
               and not (in_RPC_PG(x.r, x.p, x.c) and ({nrgelc} or not {chp}))""")
    # RP_GRP(RPC_PG(RP_PRC,C))$(NOT TRACKPC): the main outputs of the processes still in NCAP_YES
    db.x("""create or replace temp table lev_grp as
            select distinct g.r, g.p, g.c from RPC_PG g
            join (select distinct r, p from NCAP_YES) n on n.r = g.r and n.p = g.p
            where not exists (select 1 from lev_trackpc t where t.r = g.r and t.p = g.p and t.c = g.c)""")
    # peak credit: TRACKPG(RP_PRC,C)$TOP OUT for each C of a peak commodity group, and PAR_RTCS
    db.x("create or replace temp table lev_rtcs as select '' r, '' y, '' c, '' s, 0.0 as value where false")
    db.x("create or replace temp table lev_trackpg as select '' r, '' p, '' c where false")
    if all(n in db.sym for n in ("COM_PEAK", "COM_GMAP", "COM_PKTS", "PAR_PEAKM", "RTCS_VARC")) and db.card("COM_PEAK"):
        db.x("""create or replace temp table lev_trackpg as
                select distinct x.r, x.p, x.c from COM_PEAK k
                join COM_GMAP g on g.r = k.r and g.cg = k.cg
                join TOP x on x.r = g.r and x.c = g.c and x.io = 'OUT'
                join (select distinct r, p from NCAP_YES) n on n.r = x.r and n.p = x.p""")
        rsv = "v_COM_PKRSV" if "COM_PKRSV" in db.sym else None
        res = (f"greatest({rsv}(d.r, d.y, g.c), {rsv}(d.r, d.y, k.cg))" if rsv else "0")
        ie = "v_COM_IE(d.r, d.y, d.c, d.s)" if "COM_IE" in db.sym else "1"
        # the loop over (CG,C) assigns PAR_RTCS(RTCS_VARC(R,T,C,S)) for each C; a later CG wins
        pk = db.cols("PAR_PEAKM")
        db.x(f"""create or replace temp table lev_pk as
                 select d.r, d.y, d.c, d.s, k.cg,
                        sum(pm.value / (1 + {res}) * v_RS_FR(d.r, ps.s, d.s)) as v
                 from COM_PEAK k
                 join COM_GMAP g on g.r = k.r and g.cg = k.cg
                 join RTCS_VARC d on d.r = g.r and d.c = g.c
                 join COM_PKTS ps on ps.r = k.r and ps.cg = k.cg
                 join RS_TREE tr on tr.r = d.r and tr.s = d.s and tr.s2 = ps.s
                 join PAR_PEAKM pm on pm.{pk[0]} = d.r and pm.{pk[1]} = d.y and pm.{pk[2]} = k.cg and pm.{pk[3]} = ps.s
                 group by d.r, d.y, d.c, d.s, k.cg""")
        # PAR_RTCS(RTCS_VARC(R,T,C,S)) = ... for each (CG,C) of the loop; a later CG replaces an earlier one
        db.x(f"""create or replace temp table lev_rtcs as
                 select d.r, d.y, d.c, d.s, arg_max(coalesce(p.v, 0) * {ie}, k.cg) as value
                 from COM_PEAK k
                 join COM_GMAP g on g.r = k.r and g.cg = k.cg
                 join RTCS_VARC d on d.r = g.r and d.c = g.c
                 left join lev_pk p on p.r = d.r and p.y = d.y and p.c = d.c and p.s = d.s and p.cg = k.cg
                 group by d.r, d.y, d.c, d.s""")
    # the bracket of lines 242-252, set by set. fv is the vintage of the flows and costs (V when the process is
    # vintaged, T when not); the peak credit also needs the capacity vintage, so its part is kept by timeslice.
    ie = "v_COM_IE(o.r, o.y2, o.c, ct.s)" if "COM_IE" in db.sym else "1"
    parts = []
    if "CST_ACTC" in db.sym:
        parts.append("select r, y as fv, y2 as t, p, value from CST_ACTC")
    for tab in ("CST_FLOC", "CST_FLOX"):
        if tab in db.sym:
            parts.append(f"""select z.r, z.y, z.y2, z.p, z.value from {tab} z
                             join TOP x on x.r = z.r and x.p = z.p and x.c = z.c and x.io in ('IN', 'OUT')""")
    # inputs at the commodity marginal: SUM((COM_TS(R,C,S),RS_TREE(R,S,TS))$F_IN, PAR_COMBALEM(R,T,C,S)*F_IN(..TS)*RS_FR(R,S,TS))
    parts.append("""select o.r, o.y, o.y2, o.p, m.value * o.value * v_RS_FR(o.r, ct.s, o.s)
                    from F_IN o
                    join TOP x on x.r = o.r and x.p = o.p and x.c = o.c and x.io = 'IN'
                    join COM_TS ct on ct.r = o.r and ct.c = o.c
                    join RS_TREE tr on tr.r = o.r and tr.s = ct.s and tr.s2 = o.s
                    join PAR_COMBALEM m on m.r = o.r and m.y = o.y2 and m.c = o.c and m.s = ct.s""")
    # outputs other than the main ones, credited at the marginal times COM_IE
    parts.append(f"""select o.r, o.y, o.y2, o.p, -m.value * {ie} * o.value * v_RS_FR(o.r, ct.s, o.s)
                     from F_OUT o
                     join TOP x on x.r = o.r and x.p = o.p and x.c = o.c and x.io = 'OUT'
                     join COM_TS ct on ct.r = o.r and ct.c = o.c
                     join RS_TREE tr on tr.r = o.r and tr.s = ct.s and tr.s2 = o.s
                     join PAR_COMBALEM m on m.r = o.r and m.y = o.y2 and m.c = o.c and m.s = ct.s
                     where not exists (select 1 from lev_grp g where g.r = o.r and g.p = o.p and g.c = o.c)""")
    db.x(f"""create or replace temp table lev_cost as
             select r, fv, t, p, sum(value) as value from (
               select * from ({' union all '.join(parts)}) u(r, fv, t, p, value)) z
             group by r, fv, t, p""")
    # peak credit: (NCAP_PKCNT(R,V,P,S)**RPC_PKF)*PAR_RTCS(R,T,C,S)$TRACKPG * F_OUT(..TS)*RS_FR(R,S,TS), outputs not in RP_GRP
    pkf = "in_RPC_PKF(o.r, o.p, o.c)" if "RPC_PKF" in db.sym else "false"
    db.x(f"""create or replace temp table lev_pkc as
             select o.r, o.y as fv, o.y2 as t, o.p, ct.s, {pkf} as raised,
                    sum(rc.value * o.value * v_RS_FR(o.r, ct.s, o.s)) as value
             from F_OUT o
             join lev_trackpg g on g.r = o.r and g.p = o.p and g.c = o.c
             join COM_TS ct on ct.r = o.r and ct.c = o.c
             join RS_TREE tr on tr.r = o.r and tr.s = ct.s and tr.s2 = o.s
             join lev_rtcs rc on rc.r = o.r and rc.y = o.y2 and rc.c = o.c and rc.s = ct.s
             where not exists (select 1 from lev_grp q where q.r = o.r and q.p = o.p and q.c = o.c)
             group by o.r, o.y, o.y2, o.p, ct.s, {pkf}""")
    # main output: SUM(RPCS_VAR(RPC_PG(R,P,C),S)$(NOT TRACKPC), PAR_FLO(R,fv,T,P,C,S))
    db.x("""create or replace temp table lev_out as
            select pf.r, pf.y as fv, pf.y2 as t, pf.p, sum(pf.value) as value
            from PAR_FLO pf
            join RPC_PG g on g.r = pf.r and g.p = pf.p and g.c = pf.c
            join RPCS_VAR rv on rv.r = pf.r and rv.p = pf.p and rv.c = pf.c and rv.s = pf.s
            where not exists (select 1 from lev_trackpc k where k.r = pf.r and k.p = pf.p and k.c = pf.c)
            group by pf.r, pf.y, pf.y2, pf.p""")
    pkcnt = "v_NCAP_PKCNT(k.r, k.v, k.p, q.s)" if "NCAP_PKCNT" in db.sym else "0"
    # (period, capacity vintage, flow vintage) of each sum: vintaged RTP_VINTYR / RTP_CPTYR with fv = V,
    # non-vintaged RTP_CPTYR with fv = T and the weight COEF_CPT/PASTSUM
    vint = "in_PRC_VINT(t.r, t.p)" if "PRC_VINT" in db.sym else "false"
    db.x(f"""create or replace temp table lev_keys as
             select t.r, t.y as v, t.y2 as t, t.p, t.y as fv, 1.0 as w, 'num' as part
             from RTP_VINTYR t where {vint}
             union all
             select t.r, t.y, t.y2, t.p, t.y, 1.0, 'den' from RTP_CPTYR t where {vint}
             union all
             select t.r, t.y, t.y2, t.p, t.y2, v_COEF_CPT(t.r, t.y, t.y2, t.p) / ps.value, 'both'
             from RTP_CPTYR t join lev_pastsum ps on ps.r = t.r and ps.y = t.y2 and ps.p = t.p
             where not {vint} and ps.value <> 0""")
    db.x(f"""create or replace temp table lev_terms as
             select k.r, k.v, k.p,
                    sum(case when k.part <> 'den' then v_COEF_PVT(k.r, k.t) * k.w * (
                          coalesce(c.value, 0)
                          - coalesce((select sum(case when q.raised then {pkcnt} else 1 end * q.value)
                                      from lev_pkc q where q.r = k.r and q.fv = k.fv and q.t = k.t and q.p = k.p), 0))
                        else 0 end) as num,
                    sum(case when k.part <> 'num' then v_COEF_PVT(k.r, k.t) * k.w * coalesce(o.value, 0) else 0 end) as den
             from lev_keys k
             left join lev_cost c on c.r = k.r and c.fv = k.fv and c.t = k.t and c.p = k.p
             left join lev_out o on o.r = k.r and o.fv = k.fv and o.t = k.t and o.p = k.p
             group by k.r, k.v, k.p""")
    # vintaged: COEF_RTP*VAR_NCAP.L + the sums; non-vintaged: COEF_RTP + the sums
    db.put("PAR_NCAPR", f"""
        select n.r, n.y, n.p, 'LEVCOST' as u,
               (coalesce(c.value, 0) * case when {vint.replace('t.', 'n.')} then v_L_VAR_NCAP(n.r, n.y, n.p) else 1 end
                + coalesce(x.num, 0)) / greatest(1e-6, coalesce(x.den, 0)) as value
        from NCAP_YES n
        left join {coef} c on c.r = n.r and c.y = n.y and c.p = n.p
        left join lev_terms x on x.r = n.r and x.v = n.y and x.p = n.p
        where in_MILESTONYR(n.y)
    """)


def _par_rtcs(db):
    """rptlite.rpt line 158, after rptmisc ("add aggregation levels"): the power level of an aggregate
    commodity, read by Veda as VAR_POut beside P_OUT:
    LOOP(NRG_TYPE,Z=RPT_OPT(NRG_TYPE,'1'); IF(Z,
        PAR_RTCS(RTCS_VARC(R,T,C,S))$NRG_TMAP(R,NRG_TYPE,C)=AGG_OUT(R,T,C,S)/G_YRFR(R,S)/Z));
    The NCAP.1 block uses PAR_RTCS as a work table and clears it before this line."""
    db.declare("PAR_RTCS", "par", ["R", "T", "C", "S"])
    if "RPT_OPT" not in db.sym or "NRG_TMAP" not in db.sym or "AGG_OUT" not in db.sym or "RTCS_VARC" not in db.sym:
        return
    nt = db.cols("NRG_TMAP")[1]
    for u, z in db.q(f"""select o.u, o.value from RPT_OPT o where o.j = '1' and o.value <> 0
                          and exists (select 1 from NRG_TYPE n where upper(n.{db.cols('NRG_TYPE')[0]}) = upper(o.u))
                          order by o.u"""):
        db.x(f"""create or replace temp table rtcs_dom as
                 select d.r, d.y, d.c, d.s from RTCS_VARC d
                 where exists (select 1 from NRG_TMAP m where m.r = d.r and upper(m.{nt}) = '{u.upper()}' and m.c = d.c)""")
        # a plain '=' over the domain: keys without AGG_OUT lose any earlier value
        db.x("""delete from PAR_RTCS o_ where exists (select 1 from rtcs_dom d
                  where d.r = o_.r and d.y = o_.y and d.c = o_.c and d.s = o_.s)""")
        db.put("PAR_RTCS", f"""
            select a.r, a.y, a.c, a.s, a.value / v_G_YRFR(a.r, a.s) / {float(z)} as value
            from AGG_OUT a join rtcs_dom d on d.r = a.r and d.y = a.y and d.c = a.c and d.s = a.s
        """, zero="eps")


def _redistribute(db, name):
    """Move name off slices that are not in RCS, onto the RCS slices, through RS_TREE."""
    db.x(f"""
        create or replace temp table f_ios as
        select r, y, y2, p, c, s, value from "{name}"
        where not in_RCS(r, c, s)
    """)
    db.x(f"""
        delete from "{name}" f
        where exists (select 1 from f_ios i
                      where i.r = f.r and i.y = f.y and i.y2 = f.y2
                        and i.p = f.p and i.c = f.c and i.s = f.s)
    """)
    rs = "v_RS_FR(i.r, g.s, i.s)" if "RS_FR" in db.sym else "0"
    fr = "v_RTCS_FR(i.r, i.y2, i.c, g.s, i.s)" if "RTCS_FR" in db.sym else "0"
    db.put(name, f"""
        select i.r, i.y, i.y2, i.p, i.c, g.s,
               v_{name}(i.r, i.y, i.y2, i.p, i.c, g.s)
               + sum(i.value * {rs} * (1 + {fr})) as value
        from f_ios i
        join RCS g on g.r = i.r and g.c = i.c
        join RS_TREE tree on tree.r = i.r and tree.s = g.s and tree.s2 = i.s
        group by i.r, i.y, i.y2, i.p, i.c, g.s
    """)


def _complete_com(db):
    """
    RTTC(RTC)$(NOT SUM(RHS_COMPRD)) = YES;
    RXX(RTC)$(NOT SUM(RCS_COMBAL)) = YES;
    IF(RPT_OPT('COMPRD','1') <= 0, RTTC$(NOT RXX) = NO);
    IF(CARD(RCS), ... power levels ...);
    ELSE PAR_COMPRDL(RTTC,ANNUAL) = SUM(F_OUT);
    PAR_COMPRDL(RTTC,S)$AGG_OUT = PAR_COMPRDL + AGG_OUT;
    PAR_COMNETL(RXX,S) $= PAR_COMPRDL;
    PAR_COMNETL(RTCS_VARC(RXX,ANNUAL)) = PAR_COMPRDL*PROD(RTTC,COM_IE) - SUM(F_INOUT IN);
    PAR_COMPRDL(RXX(RTTC),S) = 0;
    VAR_COMNET.L(RXX,S) $= PAR_COMNETL;
    """
    if "RTC" not in db.sym:
        return
    # RTTC and RXX are work sets. The model may already have an RXX with another domain,
    # so these live in temp tables rather than those symbols.
    rhs = "not exists (select 1 from RHS_COMPRD h where h.r = t.r and h.y = t.y and h.c = t.c)" \
        if "RHS_COMPRD" in db.sym else "true"
    bal = "not exists (select 1 from RCS_COMBAL b where b.r = t.r and b.y = t.y and b.c = t.c)" \
        if "RCS_COMBAL" in db.sym else "true"
    db.x(f"create or replace temp table rttc_w as select t.r, t.y, t.c from RTC t where {rhs}")
    db.x(f"create or replace temp table rxx_w as select t.r, t.y, t.c from RTC t where {bal}")
    z = _opt(db, "COMPRD", "1")
    if z is None or z <= 0:
        db.x("""
            delete from rttc_w t
            where not exists (select 1 from rxx_w x where x.r = t.r and x.y = t.y and x.c = t.c)
        """)
    # RCS is cleared inside the IF; which branch ran is what _flow_timeslices saw
    rcs = getattr(db, "rcs_on", False)
    if rcs:
        _comprdl_ts(db)
        _p_out(db)
    if not rcs and db.q1("select count(*) from rttc_w"):
        db.x("""
            create or replace temp table prd_ann as
            select t.r, t.y, t.c, sum(f.value) as value
            from rttc_w t
            join F_OUT f on f.r = t.r and f.y2 = t.y and f.c = t.c
            where in_VNT(f.y, f.y2)
            group by t.r, t.y, t.c
        """)
        db.put("PAR_COMPRDL", "select r, y, c, 'ANNUAL' as s, value from prd_ann where value <> 0")
        db.put("PAR_COMPRDL", """
            select r, y, c, 'ANNUAL' as s, 0 as value from prd_ann p
            where value = 0 and exists (
                select 1 from PAR_COMPRDL d where d.r=p.r and d.y=p.y and d.c=p.c and d.s='ANNUAL')
        """)
    if db.q1("select count(*) from rttc_w") and "AGG_OUT" in db.sym and db.card("AGG_OUT"):
        db.put("PAR_COMPRDL", """
            select a.r, a.y, a.c, a.s, v_PAR_COMPRDL(a.r, a.y, a.c, a.s) + a.value as value
            from AGG_OUT a
            where exists (select 1 from rttc_w t where t.r = a.r and t.y = a.y and t.c = a.c)
        """)
    if db.q1("select count(*) from rxx_w"):
        db.put("PAR_COMNETL", """
            select d.r, d.y, d.c, d.s, d.value
            from PAR_COMPRDL d
            where exists (select 1 from rxx_w x where x.r = d.r and x.y = d.y and x.c = d.c)
        """, zero="eps")
        ie = "v_COM_IE(d.r, d.y, d.c, d.s)" if "COM_IE" in db.sym else "1"
        if db.card("F_INOUT") and "VNT" in db.sym and "RPC_CAPFLO" in db.sym:
            db.x("""
                create or replace temp table cap_in as
                select f.r, f.y2 as y, f.c, sum(f.value) as value
                from F_INOUT f
                where f.io = 'IN' and in_VNT(f.y, f.y2)
                  and in_RPC_CAPFLO(f.r, f.y, f.p, f.c)
                group by f.r, f.y2, f.c
            """)
            minus = "coalesce(k.value, 0)"
            join = "left join cap_in k on k.r = d.r and k.y = d.y and k.c = d.c"
        else:
            minus, join = "0", ""
        db.put("PAR_COMNETL", f"""
            select d.r, d.y, d.c, d.s,
                   d.value * (case when exists (select 1 from rttc_w t
                               where t.r = d.r and t.y = d.y and t.c = d.c) then {ie} else 1 end)
                   - {minus} as value
            from PAR_COMPRDL d
            {join}
            where exists (select 1 from rxx_w x where x.r = d.r and x.y = d.y and x.c = d.c)
              and d.s = 'ANNUAL'
              and in_RTCS_VARC(d.r, d.y, d.c, d.s)
        """)
        db.x("""
            delete from PAR_COMPRDL d
            where exists (select 1 from rxx_w x where x.r = d.r and x.y = d.y and x.c = d.c)
              and exists (select 1 from rttc_w t where t.r = d.r and t.y = d.y and t.c = d.c)
        """)
        if "L_VAR_COMNET" in db.sym:
            db.put("L_VAR_COMNET", """
                select d.r, d.y, d.c, d.s, d.value
                from PAR_COMNETL d
                where exists (select 1 from rxx_w x where x.r = d.r and x.y = d.y and x.c = d.c)
            """, zero="eps")


def _constraints(db):
    """rptmisc.rpt lines 149-192. Cumulative flows, dynamic bounds, then user constraints."""
    _cumflo(db)
    _ucrtp(db)
    _ucmrk(db)
    if _flag(db, "VAR_UC"):
        # $IF NOT %VAR_UC%==YES $GOTO UC_DONE  — the block runs when the flag is YES.
        # rptlite then skips par_uc.rpt. The dumped VAR_UC already holds SOLVE_STATUS,
        # written by VAR_UC.L('%SYSPREFIX%SOLVE_STATUS') $= MODELSTAT before the copy.
        _uc_levels(db)
        _uc_marginals(db)
        _ucmax(db)
    else:
        paruc.run(db, "SM", "EQE")
        paruc.run(db, "SM", "EQG")
        paruc.run(db, "SM", "EQL")
    _uc_filter(db)


def _flag(db, name):
    env = getattr(db, "env", None) or {}
    return str(env.get(name, "")).strip().strip("'\"").upper() == "YES"


def _cumflo(db):
    """
    PAR_CUMFLOL(R,P,C,YEAR,LL) $= VAR_CUMFLO.L * CUFSCAL;
    PAR_CUMFLOM(R,P,C,YEAR,LL) $= VAR_CUMFLO.M * (1/CUFSCAL);
    PAR_CUMCST(R,YEAR,LL,COSTAGG,CUR) $= VAR_CUMCST.L;
    CUFSCAL defaults to 10 (eqmain.mod). '$=' stores an EPS level or marginal.
    """
    env = getattr(db, "env", None) or {}
    scal = float(env.get("CUFSCAL", 10))
    db.declare("PAR_CUMFLOL", "par", ["R", "P", "C", "LL", "LL"])
    db.declare("PAR_CUMFLOM", "par", ["R", "P", "C", "LL", "LL"])
    db.declare("PAR_CUMCST", "par", ["R", "LL", "LL", "COSTAGG", "CUR"])
    if "L_VAR_CUMFLO" in db.sym:
        db.put("PAR_CUMFLOL", f"""
            select r, p, c, y, y2, value * {scal} as value from L_VAR_CUMFLO
        """, zero="eps")
    if "M_VAR_CUMFLO" in db.sym:
        db.put("PAR_CUMFLOM", f"""
            select r, p, c, y, y2, value * {1.0 / scal} as value from M_VAR_CUMFLO
        """, zero="eps")
    if "L_VAR_CUMCST" in db.sym:
        db.put("PAR_CUMCST", """
            select r, y, y2, agg, cur, value from L_VAR_CUMCST
        """, zero="eps")


def _ucrtp(db):
    """
    $IF DEFINED EQE_UCRTP
      EQN_UCRTP.M(UC_N,R,T,P,UC_GRPTYPE,BD('FX')) $= EQE_UCRTP.M;
    PAR_UCRTP(UC_N,R,T,P,UC_GRPTYPE) $=
      SUM(BD$PRC_DYNUC(UC_N,'RHS',R,T,P,UC_GRPTYPE,BD),
          EQN_UCRTP.M*(1/COEF_OBJINV(R,T,P))$COEF_OBJINV(R,T,P));
    PAR_UCRTP(UC_N,R,T,P,'ACT') $=
      SUM(BD$PRC_DYNUC(UC_N,'RHS',R,T,P,'ACT',BD), EQN_UCRTP.M*R_DF(R,T));
    The $IF covers only the FX copy. The activity group is written after the
    other groups, so it replaces them. COEF_OBJINV is the coefficient from rpt_objc.
    """
    db.declare("PAR_UCRTP", "par", ["UC_N", "R", "T", "P", "UC_GRPTYPE"])
    if "M_EQE_UCRTP" in db.sym and "M_EQN_UCRTP" in db.sym:
        db.put("M_EQN_UCRTP", """
            select uc, r, y, p, grp, l, value from M_EQE_UCRTP where l = 'FX'
        """, zero="eps")
    if "PRC_DYNUC" not in db.sym or "M_EQN_UCRTP" not in db.sym:
        return
    coef = "COEF_OBJINV" in db.sym
    if coef:
        db.put("PAR_UCRTP", """
            select d.uc, d.r, d.y, d.p, d.grp,
                   sum(v_M_EQN_UCRTP(d.uc, d.r, d.y, d.p, d.grp, d.l)
                       / v_COEF_OBJINV(d.r, d.y, d.p)) as value
            from PRC_DYNUC d
            where d.side = 'RHS' and in_COEF_OBJINV(d.r, d.y, d.p)
              and v_COEF_OBJINV(d.r, d.y, d.p) <> 0
            group by d.uc, d.r, d.y, d.p, d.grp
        """, zero="skip")
    db.put("PAR_UCRTP", """
        select d.uc, d.r, d.y, d.p, 'ACT' as grp,
               sum(v_M_EQN_UCRTP(d.uc, d.r, d.y, d.p, 'ACT', d.l) * v_R_DF(d.r, d.y)) as value
        from PRC_DYNUC d
        where d.side = 'RHS' and d.grp = 'ACT'
        group by d.uc, d.r, d.y, d.p
    """, zero="skip")


def _ucmrk(db):
    """
    IF(RPT_OPT('COMPRD','4'),
      PAR_UCMRK $= EQL_FLOMRK.M; PAR_UCMRK $= EQG_FLOMRK.M; PAR_UCMRK $= EQE_FLOMRK.M;
      PAR_UCMRK$PAR_UCMRK = (PAR_UCMRK/COEF_PVT)$(NOT SUM(RX_MARK(R,LL,ITEM,C,BD),1)));
    An absent option is 0, so the body does not run. The last statement divides
    where no market row exists and deletes the record where one does.
    """
    db.declare("PAR_UCMRK", "par", ["R", "T", "ITEM", "C", "S"])
    if not (_opt(db, "COMPRD", "4") or 0):
        return
    for eq in ("M_EQL_FLOMRK", "M_EQG_FLOMRK", "M_EQE_FLOMRK"):
        if eq in db.sym:
            db.put("PAR_UCMRK", f"select r, y, u, c, s, value from {eq}", zero="eps")
    mark = ""
    if "RX_MARK" in db.sym:
        mark = """
            and not exists (select 1 from RX_MARK m
                            where m.r = p.r and m.u = p.u and m.c = p.c)
        """
    db.put("PAR_UCMRK", f"""
        select p.r, p.y, p.u, p.c, p.s,
               p.value / nullif(v_COEF_PVT(p.r, p.y), 0) as value
        from PAR_UCMRK p
        where true {mark}
    """)
    if "RX_MARK" in db.sym:
        db.x("""
            delete from PAR_UCMRK p
            where exists (select 1 from RX_MARK m
                          where m.r = p.r and m.u = p.u and m.c = p.c)
        """)


def _uc_levels(db):
    """
    PAR_UCSL(UC_N,'NONE','NONE','NONE') $= VAR_UC.L;
    PAR_UCSL(UC_N,R,'NONE','NONE')      $= VAR_UCR.L;
    PAR_UCSL(UC_N,'NONE',T,'NONE')      $= VAR_UCT.L;
    PAR_UCSL(UC_N,R,T,'NONE')           $= VAR_UCRT.L;
    PAR_UCSL(UC_N,'NONE',T,S)           $= VAR_UCTS.L;
    PAR_UCSL(UC_N,R,T,S)                $= VAR_UCRTS.L;
    """
    db.declare("PAR_UCSL", "par", ["UC_N", "*", "*", "*"])
    db.declare("PAR_UCSM", "par", ["UC_N", "*", "*", "*"])
    _uc_put(db, "PAR_UCSL", "L_VAR_UC",
            "select uc, 'NONE' as u, 'NONE' as u2, 'NONE' as u3, value from L_VAR_UC")
    _uc_put(db, "PAR_UCSL", "L_VAR_UCR",
            "select uc, r as u, 'NONE' as u2, 'NONE' as u3, value from L_VAR_UCR")
    _uc_put(db, "PAR_UCSL", "L_VAR_UCT",
            "select uc, 'NONE' as u, y as u2, 'NONE' as u3, value from L_VAR_UCT")
    _uc_put(db, "PAR_UCSL", "L_VAR_UCRT",
            "select uc, r as u, y as u2, 'NONE' as u3, value from L_VAR_UCRT")
    _uc_put(db, "PAR_UCSL", "L_VAR_UCTS",
            "select uc, 'NONE' as u, y as u2, s as u3, value from L_VAR_UCTS")
    _uc_put(db, "PAR_UCSL", "L_VAR_UCRTS",
            "select uc, r as u, y as u2, s as u3, value from L_VAR_UCRTS")


def _uc_marginals(db):
    """
    PAR_UCSM(UCN,R,T,ANNUAL)$UC_R_SUM(R,UCN) $= VAR_UCT.M*R_DF(R,T);
    PAR_UCSM(UCN,R,T,S)$UC_TS_EACH(R,UCN,S)  $= VAR_UCTS.M*R_DF(R,T);
    PAR_UCSM(UC_N,'NONE','NONE','NONE') $= VAR_UC.M;
    PAR_UCSM(UC_N,R,'NONE','NONE')      $= VAR_UCR.M;
    PAR_UCSM(UC_N,'NONE',T,'NONE')      $= VAR_UCT.M;
    PAR_UCSM(UC_N,R,T,'NONE')           $= VAR_UCRT.M*R_DF(R,T);
    PAR_UCSM(UC_N,'NONE',T,S)           $= VAR_UCTS.M;
    PAR_UCSM(UC_N,R,T,S)                $= VAR_UCRTS.M*R_DF(R,T);
    Later statements replace an earlier key; the overlapping keys carry the same value.
    """
    db.declare("PAR_UCSM", "par", ["UC_N", "*", "*", "*"])
    if "M_VAR_UCT" in db.sym and "UC_R_SUM" in db.sym:
        db.put("PAR_UCSM", """
            select u.uc, g.r as u, u.y as u2, 'ANNUAL' as u3,
                   u.value * v_R_DF(g.r, u.y) as value
            from M_VAR_UCT u
            join UC_R_SUM g on g.uc = u.uc
        """, zero="eps")
    if "M_VAR_UCTS" in db.sym and "UC_TS_EACH" in db.sym:
        db.put("PAR_UCSM", """
            select u.uc, g.r as u, u.y as u2, g.s as u3,
                   u.value * v_R_DF(g.r, u.y) as value
            from M_VAR_UCTS u
            join UC_TS_EACH g on g.uc = u.uc and g.s = u.s
        """, zero="eps")
    _uc_put(db, "PAR_UCSM", "M_VAR_UC",
            "select uc, 'NONE' as u, 'NONE' as u2, 'NONE' as u3, value from M_VAR_UC")
    _uc_put(db, "PAR_UCSM", "M_VAR_UCR",
            "select uc, r as u, 'NONE' as u2, 'NONE' as u3, value from M_VAR_UCR")
    _uc_put(db, "PAR_UCSM", "M_VAR_UCT",
            "select uc, 'NONE' as u, y as u2, 'NONE' as u3, value from M_VAR_UCT")
    if "M_VAR_UCRT" in db.sym:
        db.put("PAR_UCSM", """
            select u.uc, u.r as u, u.y as u2, 'NONE' as u3,
                   u.value * v_R_DF(u.r, u.y) as value
            from M_VAR_UCRT u
        """, zero="eps")
    _uc_put(db, "PAR_UCSM", "M_VAR_UCTS",
            "select uc, 'NONE' as u, y as u2, s as u3, value from M_VAR_UCTS")
    if "M_VAR_UCRTS" in db.sym:
        db.put("PAR_UCSM", """
            select u.uc, u.r as u, u.y as u2, u.s as u3,
                   u.value * v_R_DF(u.r, u.y) as value
            from M_VAR_UCRTS u
        """, zero="eps")


def _uc_put(db, name, src, select):
    if src in db.sym:
        db.put(name, select, zero="eps")


def _ucmax(db):
    """
    PAR_UCMAX(UC_N,ALL_R,'-',C)$UC_GMAX(UC_N,ALL_R,'N',C,'N')
      = VAR_UC.L - EQG_UCMAX.L(UC_N,ALL_R,'N',C,'N');
    PAR_UCMAX(UC_N,ALL_R,P,C)$UC_GMAX(...,P,C,'EACH')
      = VAR_UC.L - EQG_UCMAX.L(...,P,C,'EACH');
    and the same for one region, also controlled by UC_R_EACH.
    Plain '=' : a zero result removes the record. UC_GMAX is not in these models.
    """
    db.declare("PAR_UCMAX", "par", ["UC_N", "ALL_R", "ITEM", "C"])
    if "UC_GMAX" not in db.sym or "L_EQG_UCMAX" not in db.sym:
        return
    each = "in_UC_R_EACH(g.r, g.uc)" if "UC_R_EACH" in db.sym else "false"
    db.put("PAR_UCMAX", f"""
        select g.uc, g.r, '-' as u, g.c,
               v_L_VAR_UC(g.uc) - v_L_EQG_UCMAX(g.uc, g.r, g.u, g.c, g.u2) as value
        from UC_GMAX g
        where g.u2 = 'N' and g.u = 'N'
    """)
    db.put("PAR_UCMAX", f"""
        select g.uc, g.r, g.u, g.c,
               v_L_VAR_UC(g.uc) - v_L_EQG_UCMAX(g.uc, g.r, g.u, g.c, g.u2) as value
        from UC_GMAX g
        where g.u2 = 'EACH'
    """)
    db.put("PAR_UCMAX", f"""
        select g.uc, g.r, '-' as u, g.c,
               v_L_VAR_UCR(g.uc, g.r) - v_L_EQG_UCMAX(g.uc, g.r, g.u, g.c, g.u2) as value
        from UC_GMAX g
        where g.u = 'N' and g.u2 = 'N' and {each}
    """)
    db.put("PAR_UCMAX", f"""
        select g.uc, g.r, g.u, g.c,
               v_L_VAR_UCR(g.uc, g.r) - v_L_EQG_UCMAX(g.uc, g.r, g.u, g.c, g.u2) as value
        from UC_GMAX g
        where g.u2 = 'EACH' and {each}
    """)


def _uc_filter(db):
    """Z=RPT_OPT('UCN','9'); IF(Z>0, PAR_UCSL$((ABS(PAR_UCSL)<Z)$PAR_UCSL)=0)."""
    if "PAR_UCSL" not in db.sym:
        db.declare("PAR_UCSL", "par", ["UC_N", "*", "*", "*"])
    z = _opt(db, "UCN", "9")
    if z and z > 0:
        db.zap("PAR_UCSL", f"value <> 0 and abs(value) < {float(z)}")


def _abs_p_out(db):
    """rptlite.rpt 172-173, the reserve provision of the ancillary balancing services (ABS=YES) as power levels:
    $IFI %ABS%==YES Z=RPT_OPT('RATE','1'); IF(Z,TRACKPC(BS_BSC)=YES; TRACKPC(BS_STGP(R,P),C)$=BS_RTYPE(R,C));
    $IFI %ABS%==YES %1P_OUT(%3RTP(R,T,P),C,S)$(PRC_TS(R,P,S)$BS_COMTS(R,C,S)$TRACKPC(R,P,C)$Z)=
                    SUM(RTP_VINTYR(R,V,T,P),VAR_BSFSP(R,V,T,P,C,S)+VAR_BSFNSP(R,V,T,P,C,S))*PRC_CAPACT(R,P)/Z;
    VAR_BSFSP / VAR_BSFNSP: VAR_BSPRS(R,V,T,P,C,S,'N' / 'FX')$BS_RVT(R,V,T) (equ_ext.abs)."""
    if "BS_RTYPE" not in db.sym or "L_VAR_BSPRS" not in db.sym or "RPT_OPT" not in db.sym:
        return
    z = _opt(db, "RATE", "1") or 0
    if not z:
        return
    db.declare("P_OUT", "par", ["R", "T", "P", "C", "S"])
    db.x("""create or replace temp table abs_tpc as
            select r, p, c from BS_BSC union select g.r, g.p, b.c from BS_STGP g join BS_RTYPE b on b.r = g.r""")
    db.x("""create or replace temp table abs_dom as
            select k.r, k.y, k.p, t.c, s.s from RTP k join abs_tpc t on t.r = k.r and t.p = k.p
            join PRC_TS s on s.r = k.r and s.p = k.p
            where in_MILESTONYR(k.y) and in_BS_COMTS(k.r, t.c, s.s)""")
    db.x("""delete from P_OUT o_ where exists (select 1 from abs_dom d where d.r = o_.r and d.y = o_.y and d.p = o_.p
                                                and d.c = o_.c and d.s = o_.s)""")
    db.put("P_OUT", f"""select d.r, d.y, d.p, d.c, d.s, sum(l.value) * v_PRC_CAPACT(d.r, d.p) / {float(z)} as value
                        from abs_dom d join RTP_VINTYR v on v.r = d.r and v.y2 = d.y and v.p = d.p
                        join L_VAR_BSPRS l on l.r = d.r and l.y = v.y and l.y2 = d.y and l.p = d.p and l.c = d.c
                                          and l.s = d.s and l.l in ('N', 'FX')
                        where in_BS_RVT(d.r, v.y, d.y)
                        group by d.r, d.y, d.p, d.c, d.s""")
