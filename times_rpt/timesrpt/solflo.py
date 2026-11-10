# SPDX-License-Identifier: GPL-3.0-or-later
"""sol_flo.red and sol_ire.rpt — process flows and inter-regional exchange.

Called from rptlite.rpt before rptmisc. With REDUCE YES the flows replaced by the activity (RPC_ACT,
RPC_FFUNC) and the primary flows of the processes without an activity variable (NO_ACT) are rebuilt
from the solution; with REDUCE NO those sets are empty and the statements have nothing to substitute.
Emission flows tied to other flows are not model variables; the emission sum rebuilds them onto PAR_FLO.

The shape product is always compiled for the flow-function and emission sums
(sol_flo.red line 15 is not under the RTP_FFCS test). It is
(1+RTP_FFCX(R,V,T,P,group,C)$PRC_VINT(R,P)). In a stochastic run with S_FLO_FUNC it has a second factor,
(1+RTP_FFCS(R,V,P,group,C,SOW)) of the SOW reported (sol_flo.red line 14): RTP_FFCSW, filled for each SOW.

rptmain.rpt lines 80-84 would store EPS on a flow variable that has no value.
rptlite.rpt, which is the writer that includes rptmisc.rpt, does not, so that fill is
not applied.
"""
from __future__ import annotations

# %PGPRIM% in the TIMES source. The preprocessor uses the same label.
_PG = "ACT"


def run(db):
    """PAR_FLO, PAR_FLOM, PAR_IRE, PAR_IREM. F_IOSET and F_INOUTS are work symbols."""
    _par_flo(db)
    _par_flom(db)
    _f_ioset(db)
    _par_ire(db)
    return ["PAR_FLO", "PAR_FLOM", "PAR_IRE", "PAR_IREM"]


def _par_flo(db):
    """
    PAR_FLO(R,V,T,P,C,S) $= VAR_FLO.L(R,V,T,P,C,S);

    PAR_FLO(RTP_VINTYR(R,V,T,P),C,S)$PRC_TS(R,P,S) $=
      SUM(RPC_ACT(RP_PGACT(R,P),C), VAR_ACT.L(R,V,T,P,S)*PRC_ACTFLO(R,V,P,C));

    VAR_ACT.L(RTP_VINTYR,S) $= SUM(RPC_PG(RP_FLO(NO_ACT),C), VAR_FLO.L*(1/PRC_ACTFLO));
    VAR_ACT.L(RTP_VINTYR,S) $= SUM(RPC_IRE(RPC_PG(NO_ACT,C),IE)$RP_AIRE, VAR_IRE.L*(1/PRC_ACTFLO));

    PAR_FLO(RTP_VINTYR,C,S)$(RTPCS_VARF$RPC_FFUNC) =
      SUM((RPC_ACT(R,P,COM),RS_TREE(R,S,TS))$VAR_ACT.L,
          VAR_ACT.L*RS_FR(R,S,TS)*(1+RTCS_FR(R,T,COM,S,TS))*(ACT_FLO(R,V,P,C,S)*SHP1));

    PAR_FLO(RTP_VINTYR,C,S)$(RTPCS_VARF$RPC_EMIS) =
      SUM((FS_EMIT(R,P,C,CG1,COM),RS_TREE(R,S,TS))$PAR_FLO(R,V,T,P,COM,TS),
          PAR_FLO*RS_FR*(1+RTCS_FR)*COEF_PTRAN(R,V,P,CG1,COM,C,TS)*SHP3);
    """
    db.declare("PAR_FLO", "par", ["R", "ALLYEAR", "ALLYEAR", "P", "C", "S"])
    if "L_VAR_FLO" in db.sym:
        c = ", ".join(db.cols("PAR_FLO"))
        db.put("PAR_FLO", f'select {c}, value from L_VAR_FLO', zero="eps")
    _activity_flows(db)
    _no_act(db, marginal=False)
    _ffunc(db)
    _emissions(db)


def _par_flom(db):
    """
    PAR_FLOM(RTP_VINTYR,C,S)$PRC_TS $= SUM(RPC_ACT(RP_PGACT,C), VAR_ACT.M*(1/PRC_ACTFLO));
    VAR_ACT.M $= SUM(RPC_PG(RP_FLO(NO_ACT),C), VAR_FLO.M*PRC_ACTFLO);
    VAR_ACT.M $= SUM(RPC_IRE(...)$RP_AIRE, VAR_IRE.M*PRC_ACTFLO);
    The marginal call then exits. Emission and flow-function marginals are not rebuilt.
    """
    db.declare("PAR_FLOM", "par", ["R", "ALLYEAR", "ALLYEAR", "P", "C", "S"])
    if "M_VAR_ACT" not in db.sym or "RPC_ACT" not in db.sym or not db.card("RPC_ACT"):
        _no_act(db, marginal=True)
        return
    db.x("""
        create or replace temp table flom as
        select v.r, v.y, v.y2, v.p, a.cg as c, act.s,
               sum(case when v_PRC_ACTFLO(v.r, v.y, v.p, a.cg) = 0 then 0
                        else act.value / v_PRC_ACTFLO(v.r, v.y, v.p, a.cg) end) as value
        from RTP_VINTYR v
        join RP_PGACT g on g.r = v.r and g.p = v.p
        join RPC_ACT a on a.r = v.r and a.p = v.p
        join M_VAR_ACT act on act.r = v.r and act.y = v.y and act.y2 = v.y2 and act.p = v.p
        where in_PRC_TS(v.r, v.p, act.s)
        group by v.r, v.y, v.y2, v.p, a.cg, act.s
    """)
    db.put("PAR_FLOM", "select r, y, y2, p, c, s, value from flom where value <> 0")
    _no_act(db, marginal=True)


def _activity_flows(db):
    if "L_VAR_ACT" not in db.sym or "RPC_ACT" not in db.sym or not db.card("RPC_ACT"):
        return
    db.x("""
        create or replace temp table actflo as
        select v.r, v.y, v.y2, v.p, a.cg as c, act.s,
               sum(act.value * v_PRC_ACTFLO(v.r, v.y, v.p, a.cg)) as value,
               sum(case when act.value = 0 or v_PRC_ACTFLO(v.r, v.y, v.p, a.cg) = 0 then 1 else 0 end) as neps
        from RTP_VINTYR v
        join RP_PGACT g on g.r = v.r and g.p = v.p
        join RPC_ACT a on a.r = v.r and a.p = v.p
        join L_VAR_ACT act on act.r = v.r and act.y = v.y and act.y2 = v.y2 and act.p = v.p
        where in_PRC_TS(v.r, v.p, act.s)
        group by v.r, v.y, v.y2, v.p, a.cg, act.s
    """)
    db.put("PAR_FLO", "select r, y, y2, p, c, s, value from actflo where value <> 0")
    db.put("PAR_FLO",
           "select r, y, y2, p, c, s, 0 as value from actflo where value = 0 and neps > 0",
           zero="eps")


def _no_act(db, marginal):
    """The two NO_ACT assignments. The exchange one runs second and overwrites."""
    src = "M_VAR_FLO" if marginal else "L_VAR_FLO"
    ire = "M_VAR_IRE" if marginal else "L_VAR_IRE"
    dest = "M_VAR_ACT" if marginal else "L_VAR_ACT"
    if dest not in db.sym or "NO_ACT" not in db.sym or not db.card("NO_ACT"):
        return
    sign = "*" if marginal else "/"
    if src in db.sym:
        db.x(f"""
            create or replace temp table noact as
            select v.r, v.y, v.y2, v.p, f.s,
                   sum(case when v_PRC_ACTFLO(v.r, v.y, v.p, g.c) = 0 then 0
                            else f.value {sign} v_PRC_ACTFLO(v.r, v.y, v.p, g.c) end) as value
            from RTP_VINTYR v
            join NO_ACT n on n.r = v.r and n.p = v.p
            join RP_FLO rf on rf.r = v.r and rf.p = v.p
            join RPC_PG g on g.r = v.r and g.p = v.p
            join "{src}" f on f.r = v.r and f.y = v.y and f.y2 = v.y2 and f.p = v.p and f.c = g.c
            group by v.r, v.y, v.y2, v.p, f.s
        """)
        db.put(dest, f"select r, y, y2, p, s, value from noact where value <> 0")
    if ire in db.sym and "RPC_IRE" in db.sym:
        db.x(f"""
            create or replace temp table noact as
            select v.r, v.y, v.y2, v.p, f.s,
                   sum(case when v_PRC_ACTFLO(v.r, v.y, v.p, g.c) = 0 then 0
                            else f.value {sign} v_PRC_ACTFLO(v.r, v.y, v.p, g.c) end) as value
            from RTP_VINTYR v
            join NO_ACT n on n.r = v.r and n.p = v.p
            join RPC_PG g on g.r = v.r and g.p = v.p
            join RPC_IRE i on i.r = v.r and i.p = v.p and i.c = g.c
            join RP_AIRE a on a.r = v.r and a.p = v.p and a.ie = i.ie
            join "{ire}" f on f.r = v.r and f.y = v.y and f.y2 = v.y2 and f.p = v.p
                           and f.c = g.c and f.ie = i.ie
            group by v.r, v.y, v.y2, v.p, f.s
        """)
        db.put(dest, "select r, y, y2, p, s, value from noact where value <> 0")


def _shape(db, alias="v", group="fs.cg", commodity="e.cg"):
    """(1+RTP_FFCX(R,V,T,P,group,C)$PRC_VINT(R,P)), times (1+RTP_FFCS(R,V,P,group,C,SOW)) of the SOW reported in a
    stochastic run (RTP_FFCSW). One when the coefficients are absent."""
    ffcs = ""
    if "RTP_FFCSW" in db.sym and db.card("RTP_FFCSW"):
        ffcs = f" * (1 + v_RTP_FFCSW({alias}.r, {alias}.y, {alias}.p, {group}, {commodity}))"
    if "RTP_FFCX" not in db.sym or "PRC_VINT" not in db.sym:
        return f"(1{ffcs})"
    return (
        f"(1 + case when in_PRC_VINT({alias}.r, {alias}.p) "
        f"then v_RTP_FFCX({alias}.r, {alias}.y, {alias}.y2, {alias}.p, {group}, {commodity}) "
        f"else 0 end){ffcs}"
    )


def _ffunc(db):
    if "RPC_FFUNC" not in db.sym or not db.card("RPC_FFUNC") or "L_VAR_ACT" not in db.sym:
        return
    shp = _shape(db, group=f"'{_PG}'", commodity="ff.c")
    db.x(f"""
        create or replace temp table ffunc as
        select v.r, v.y, v.y2, v.p, ff.c, tree.s,
               sum(act.value * v_RS_FR(v.r, tree.s, tree.s2)
                   * (1 + v_RTCS_FR(v.r, v.y2, a.cg, tree.s, tree.s2))
                   * v_ACT_FLO(v.r, v.y, v.p, ff.c, tree.s) * {shp}) as value
        from RTP_VINTYR v
        join RPC_FFUNC ff on ff.r = v.r and ff.p = v.p
        join RPC_ACT a on a.r = v.r and a.p = v.p
        join RS_TREE tree on tree.r = v.r
        join L_VAR_ACT act on act.r = v.r and act.y = v.y and act.y2 = v.y2 and act.p = v.p
                           and act.s = tree.s2
        where in_RTPCS_VARF(v.r, v.y2, v.p, ff.c, tree.s)
        group by v.r, v.y, v.y2, v.p, ff.c, tree.s
    """)
    db.put("PAR_FLO", "select r, y, y2, p, c, s, value from ffunc where value <> 0")
    db.put("PAR_FLO", "select r, y, y2, p, c, s, 0 as value from ffunc where value = 0", zero="delete")


def _emissions(db):
    if "RPC_EMIS" not in db.sym or not db.card("RPC_EMIS"):
        return
    if "FS_EMIT" not in db.sym or "RS_TREE" not in db.sym:
        return
    shp = _shape(db)
    rs = "v_RS_FR(v.r, tree.s, tree.s2)" if "RS_FR" in db.sym else "0"
    fr = "v_RTCS_FR(v.r, v.y2, fs.c2, tree.s, tree.s2)" if "RTCS_FR" in db.sym else "0"
    coef = ("v_COEF_PTRAN(v.r, v.y, v.p, fs.cg, fs.c2, e.cg, tree.s2)"
            if "COEF_PTRAN" in db.sym else "0")
    # One assignment: the sum reads PAR_FLO as it stands after the variable copy.
    db.x(f"""
        create or replace temp table emis as
        select v.r, v.y, v.y2, v.p, e.cg as c, tree.s,
               sum(b.value * {rs} * (1 + {fr}) * {coef} * {shp}) as value
        from RTP_VINTYR v
        join RPC_EMIS e on e.r = v.r and e.p = v.p
        join FS_EMIT fs on fs.r = v.r and fs.p = v.p and fs.c = e.cg
        join RS_TREE tree on tree.r = v.r
        join PAR_FLO b on b.r = v.r and b.y = v.y and b.y2 = v.y2 and b.p = v.p
                       and b.c = fs.c2 and b.s = tree.s2
        where in_RTPCS_VARF(v.r, v.y2, v.p, e.cg, tree.s)
        group by v.r, v.y, v.y2, v.p, e.cg, tree.s
    """)
    db.put("PAR_FLO", "select r, y, y2, p, c, s, value from emis where value <> 0")
    db.put("PAR_FLO", """
        select r, y, y2, p, c, s, 0 as value from emis e
        where value = 0
          and exists (select 1 from PAR_FLO p where p.r=e.r and p.y=e.y and p.y2=e.y2
                      and p.p=e.p and p.c=e.c and p.s=e.s)
    """)


def _f_ioset(db):
    """
    LOOP(RPC_IRE(R,P,COM,IE),
      F_IOSET(RTP_VINTYR(R,V,T,P),C,TS,IO)$(RPCS_VAR(R,P,COM,TS)$IRE_FLOSUM(R,T,P,COM,TS,IE,C,IO))
        = RC(R,C));
    """
    db.declare("F_IOSET", "set", ["R", "ALLYEAR", "T", "P", "C", "S", "IO"])
    if "IRE_FLOSUM" not in db.sym or not db.card("IRE_FLOSUM"):
        return
    if getattr(db, "no_f_ioset", False):
        return      # the expected values of SPINES (rptmain.stc 116: OPTION CLEAR=F_IOSET before the report)
    db.assign("F_IOSET", """
        select distinct v.r, v.y, v.y2, v.p, f.c2 as c, f.s, f.io
        from IRE_FLOSUM f
        join RTP_VINTYR v on v.r = f.r and v.y2 = f.y and v.p = f.p
        join RPC_IRE i on i.r = f.r and i.p = f.p and i.c = f.c and i.ie = f.ie
        where in_RPCS_VAR(f.r, f.p, f.c, f.s)
          and in_RC(f.r, f.c2)
    """)


def _par_ire(db):
    """
    PAR_IRE(RTP_VINTYR,C,S,IE)$(RTPCS_VARF$RPC_IRE) =
      VAR_IRE.L$(NOT RPC_AIRE) + (VAR_ACT.L*PRC_ACTFLO)$RPC_AIRE;
    PAR_IREM(...) = VAR_IRE.M$(NOT RPC_AIRE) + (VAR_ACT.M/PRC_ACTFLO)$RPC_AIRE;

    F_INOUTS(F_IOSET(R,V,T,P,COM,S,IO)) =
      SUM(RPC_IRE(R,P,C,IE), IRE_FLOSUM(R,T,P,C,S,IE,COM,IO)*PAR_IRE(R,V,T,P,C,S,IE));
    """
    dom = ["R", "ALLYEAR", "ALLYEAR", "P", "C", "S", "IMPEXP"]
    db.declare("PAR_IRE", "par", dom)
    db.declare("PAR_IREM", "par", dom)
    db.clear("PAR_IRE", "PAR_IREM")
    if "RPC_IRE" not in db.sym or not db.card("RPC_IRE"):
        db.declare("F_INOUTS", "par", ["R", "ALLYEAR", "T", "P", "C", "S", "IO"])
        return
    _ire_body(db, "PAR_IRE", "L_VAR_IRE", "L_VAR_ACT", divide=False)
    _ire_body(db, "PAR_IREM", "M_VAR_IRE", "M_VAR_ACT", divide=True)
    _f_inouts(db)


def _ire_body(db, dest, var, act, divide):
    if var not in db.sym and act not in db.sym:
        return
    has_var = var in db.sym
    has_act = act in db.sym
    var_in = f"in_{var}(v.r, v.y, v.y2, v.p, i.c, vf.s, i.ie)" if has_var else "false"
    var_v = f"v_{var}(v.r, v.y, v.y2, v.p, i.c, vf.s, i.ie)" if has_var else "0"
    act_v = f"v_{act}(v.r, v.y, v.y2, v.p, vf.s)" if has_act else "0"
    coef = "v_PRC_ACTFLO(v.r, v.y, v.p, i.c)"
    if divide:
        derived = f"case when {coef} = 0 then 0 else {act_v} / {coef} end"
    else:
        derived = f"{act_v} * {coef}"
    aire = "in_RPC_AIRE(v.r, v.p, i.c)" if "RPC_AIRE" in db.sym else "false"
    db.x(f"""
        create or replace temp table ire as
        select v.r, v.y, v.y2, v.p, i.c as c, vf.s as s, i.ie as ie,
               case when {aire} then {derived} else {var_v} end as value,
               (not ({aire}) and {var_in} and {var_v} = 0) as eps
        from RTP_VINTYR v
        join RPC_IRE i on i.r = v.r and i.p = v.p
        join RTPCS_VARF vf on vf.r = v.r and vf.y = v.y2 and vf.p = v.p and vf.c = i.c
    """)
    db.put(dest, "select r, y, y2, p, c, s, ie, value from ire where value <> 0")
    db.put(dest, "select r, y, y2, p, c, s, ie, 0 as value from ire where eps", zero="eps")


def _f_inouts(db):
    db.declare("F_INOUTS", "par", ["R", "ALLYEAR", "T", "P", "C", "S", "IO"])
    if "F_IOSET" not in db.sym or not db.card("F_IOSET"):
        return
    db.x("""
        create or replace temp table ireaux as
        select o.r, o.y, o.y2, o.p, o.c, o.s, o.io,
               sum(f.value * v_PAR_IRE(o.r, o.y, o.y2, o.p, f.c, o.s, f.ie)) as value
        from F_IOSET o
        join IRE_FLOSUM f on f.r = o.r and f.y = o.y2 and f.p = o.p
                          and f.s = o.s and f.c2 = o.c and f.io = o.io
        join RPC_IRE i on i.r = f.r and i.p = f.p and i.c = f.c and i.ie = f.ie
        group by o.r, o.y, o.y2, o.p, o.c, o.s, o.io
    """)
    db.put("F_INOUTS", "select r, y, y2, p, c, s, io, value from ireaux where value <> 0")
