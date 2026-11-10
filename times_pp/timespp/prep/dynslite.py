# SPDX-License-Identifier: GPL-3.0-or-later
"""dynslite.vda: dynamic timeslice trees ($SETGLOBAL DYNTS YES with TS_OFF; NORTS(R,T,S) is -INF for a timeslice off in
a milestone year, timslice.mod).  Each part acts only when NORTS has records (IF(CARD(NORTS), ..)):

  prelev(db)    PRELEV, at the end of pp_prelv.vda: the storage leads of the seasons, then CLEAR
  reduce(db)    REDUCE, at the end of pp_reduce.red: the timeslices off leave the control sets
  postlev(db)   POSTLEV, at the end of ppm_ext.vda: the ANNUAL fallback of vintaged processes interpolated again, then CLEAR
  bounds(db)    BOUNDS, at the end of bndmain.mod: the variables of the timeslices off fixed at zero (HOLDFIXED)

%TMP% is $NORTS(R,T,S) on the year and timeslice of the attribute itself (its first region, year and timeslice
columns)."""
from ..engine import DB


def _on(db: DB):
    return "NORTS" in db.sym and db.card("NORTS") > 0


def _off(db: DB, name, cond="", rvp=None):
    """X(..)$NORTS(R,T,S) = 0 (or = NO): the records of X on a timeslice off in their own year (and the condition)."""
    if name.upper() not in db.sym or not db.card(name):
        return
    cols = db.cols(name)
    r, y, s = (next(c for c in cols if c == k) for k in ("r", "y", "s"))
    w = f"in_NORTS({r}, {y}, {s})"
    if rvp:
        w += f" and in_{rvp}({r}, {y}, p)"
    db.zap(name, w + (f" and ({cond})" if cond else ""))


def prelev(db: DB):
    """dynslite.vda PRELEV"""
    if not _on(db):
        return
    if str(db.env.get("DUC", "")).strip("'\"").upper() == "YES":
        raise ValueError("TS_OFF cannot be used with DUC")
    # --- LOOP((R,ANNUAL(S),T), F=0;
    #       LOOP(RS_BELOW1(R,S,TS)$(NOT NORTS(R,T,TS)), IF(F, RS_STG(R,TS)=ORD(TS)-Z; Z=ORD(TS); ELSE Z=ORD(TS); F=Z));
    #       RS_STG(R,S+(F-ORD(S)))$F = F-Z);
    ts = [t for (t,) in db.q("select y from MILESTONYR order by yv(y)")]
    off = {(r, t, s) for r, t, s in db.q("select r, y, s from NORTS where value <> 0")}
    stg = {(r, s): v for r, s, v in db.q("select r, s, value from RS_STG")}
    for (r,) in db.q("select r from REG order by r"):
        kids = db.q(f"select b.s2, ord_s(b.s2) from RS_BELOW1 b where b.r='{r}' and b.s='ANNUAL' order by ord_s(b.s2)")
        for t in ts:
            F = Z = 0
            first = None
            for s, o in kids:
                if (r, t, s) in off:
                    continue
                if F:
                    stg[(r, s)] = o - Z
                    Z = o
                else:
                    Z = o
                    F = Z
                    first = s
            if F:
                stg[(r, first)] = F - Z
    db.clear("RS_STG")
    rows = [(r, s, float(v)) for (r, s), v in stg.items() if v]
    if rows:
        db.put("RS_STG", " union all ".join(f"select '{r}' as r, '{s}' as s, cast({v!r} as DOUBLE) as value" for r, s, v in rows))
    # --- LOOP((TS_GROUP(R,'SEASON',S),TS(S--RS_STG(R,S)))$RS_STGPRD(R,S),RS_STGAV(R,S) = (G_YRFR(R,S)+G_YRFR(R,TS))/2/RS_STGPRD(R,S));
    db.put("RS_STGAV", """select p.r, p.s, (v_G_YRFR(p.r,p.s) + v_G_YRFR(p.r, o2.s)) / 2 / p.value as value
                          from RS_STGPRD p join TS_GROUP g on g.r=p.r and g.s=p.s and g.tsl='SEASON' join ORD_S o1 on o1.s=p.s
                          join ORD_S o2 on o2.ord = 1 + ((o1.ord - 1 - cast(v_RS_STG(p.r,p.s) as INTEGER)) % (select count(*) from ORD_S)
                                                         + (select count(*) from ORD_S)) % (select count(*) from ORD_S)""")
    # --- QA: LOOP(RT_PP(R,T), Z=SUM((RS_BELOW1(R,ANNUAL,TS),S(TS--RS_STG(R,TS)))$((NOT NORTS(R,T,TS))$NORTS(R,T,S)),1);
    #       IF(Z, 'Unsupported dynamic timeslice trees with overlap -- Fatal'))
    bad = db.q("""select k.r, k.y from RT_PP k join RS_BELOW1 b on b.r=k.r and b.s='ANNUAL' join ORD_S o1 on o1.s=b.s2
                  join ORD_S o2 on o2.ord = 1 + ((o1.ord - 1 - cast(v_RS_STG(k.r,b.s2) as INTEGER)) % (select count(*) from ORD_S)
                                                 + (select count(*) from ORD_S)) % (select count(*) from ORD_S)
                  where not in_NORTS(k.r, k.y, b.s2) and in_NORTS(k.r, k.y, o2.s)""")
    if bad:
        raise ValueError(f"Unsupported dynamic timeslice trees with overlap -- Fatal: timeslice trees have shared branches (R.T)={bad[0]}")
    # --- Bounds and variable costs: cleared on the timeslices off
    for n in ("ACT_BND", "COM_BNDNET", "COM_BNDPRD", "FLO_BND", "FLO_FR", "IRE_BND", "IRE_XBND", "STGIN_BND",
              "STGOUT_BND", "COM_BPRICE"):
        _off(db, n)
    clear(db)


def clear(db: DB):
    """dynslite.vda CLEAR (RVP as it stands is added to: at POSTLEV it still holds the vintaged processes on ANNUAL)"""
    # --- RVP(RTP(R,T,P))$(NOT PRC_VINT(R,P))=YES;  X(RVP(R,T,P),..,S)%TMP%=0;  OPTION CLEAR=RVP;
    db.add("RVP", "select r, y, p from RTP where not in_PRC_VINT(r, p) except select r, y, p from RVP")
    for n in ("ACT_FLO", "FLO_FUNC", "FLO_SUM", "NCAP_AF", "FLO_SHAR", "FLO_ASHAR", "STG_LOSS", "IRE_FLO", "ACT_EFF"):
        _off(db, n, rvp="RVP")
    db.clear("RVP")
    # --- Vintaged ANNUAL: RVP(RTP(R,V,P))$PRC_VINT(R,P)$=PRC_TSL(R,P,'ANNUAL');
    #     LOOP(MIYR_1(T), X(RVP(R,V,P),..,S)$(cond$(NORTS(R,V,S)+NORTS(R,T,S)$PASTMILE(V)))=0);  OPTION CLEAR=RVP;
    db.add("RVP", "select r, y, p from RTP where in_PRC_VINT(r, p) and in_PRC_TSL(r, p, 'ANNUAL')")
    t1 = db.q1("select y from MIYR_1")
    for n, cond in (("ACT_FLO", "in_RPS_S1(r, p, 'ANNUAL')"), ("FLO_FUNC", ""), ("FLO_SUM", "in_RPCS_VAR(r, p, c, 'ANNUAL')"),
                    ("NCAP_AF", ""), ("FLO_SHAR", "in_RPCS_VAR(r, p, c, 'ANNUAL')"), ("FLO_ASHAR", "in_RPS_S2(r, p, 'ANNUAL')"),
                    ("STG_LOSS", ""), ("IRE_FLO", "")):
        if n.upper() not in db.sym or not db.card(n):
            continue
        w = f"in_RVP(r, y, p) and (v_NORTS(r, y, s) + (case when in_PASTMILE(y) then v_NORTS(r, '{t1}', s) else 0 end)) <> 0"
        db.zap(n, w + (f" and {cond}" if cond else ""))
    db.clear("RVP")
    # --- Milestone years: all cleared
    for n in ("COM_IE", "COM_PKFLX", "COM_ELAST", "FLO_PKCOI", "STG_SIFT", "IRE_FLOSUM", "UC_ACT", "UC_FLO", "UC_IRE",
              "UC_COM", "UC_RHSRTS"):
        _off(db, n)


def reduce(db: DB):
    """dynslite.vda REDUCE"""
    if not _on(db):
        return
    # --- RTPS_OFF(RTP(R,T,P),S)$PRC_TS(R,P,S) $= NORTS(R,T,S);
    db.add("RTPS_OFF", "select k.r, k.y, k.p, t.s from RTP k join PRC_TS t on t.r=k.r and t.p=k.p where in_NORTS(k.r, k.y, t.s)")
    # --- RTPCS_OUT(RTP(R,T,P),C,S)$RPCS_VAR(R,P,C,S) $= NORTS(R,T,S);
    db.add("RTPCS_OUT", """select k.r, k.y, k.p, v.c, v.s from RTP k join RPCS_VAR v on v.r=k.r and v.p=k.p
                           where in_NORTS(k.r, k.y, v.s)""")
    # --- RTCS_VARC, RCS_COMBAL, RCS_COMPRD, RHS_COMBAL, RHS_COMPRD, RTX_MARK: (..)%TMP% = NO
    for n in ("RTCS_VARC", "RCS_COMBAL", "RCS_COMPRD", "RHS_COMBAL", "RHS_COMPRD", "RTX_MARK"):
        _off(db, n)


def postlev(db: DB):
    """dynslite.vda POSTLEV: the ANNUAL attributes of the vintaged processes on ANNUAL interpolated again (option 3, the
    series those with a record in a vintage of RVP; DATAYEAR the label '0' alone while it runs), then CLEAR."""
    if not _on(db):
        return
    from .. import interp
    # --- RVP(RTP(R,V,P))$PRC_VINT(R,P)$=PRC_TSL(R,P,'ANNUAL');  OPTION FIL<DATAYEAR; DATAYEAR(LL)=LASTLL(LL);
    db.add("RVP", "select r, y, p from RTP where in_PRC_VINT(r, p) and in_PRC_TSL(r, p, 'ANNUAL') except select r, y, p from RVP")
    db.tmp("dyn_datayear", "select * from DATAYEAR")
    db.assign("DATAYEAR", "select '0' as y")

    def again(name):
        # --- X(R,LL--ORD(LL),P,..,ANNUAL)$(X(R,LL,P,..,ANNUAL)$RVP(R,LL,P))=3;  fillparm X .. V 'RVP(R,V,P)' '>0' X_.. X_..
        if name.upper() not in db.sym or not db.card(name):
            return
        cols = [c for c in db.cols(name) if c != "value"]
        k = ", ".join(c if c != "y" else "'0' as y" for c in cols)
        db.put(name, f"select distinct {k}, 3 as value from \"{name}\" where s='ANNUAL' and in_RVP(r, y, p)")
        interp.fillparm(db, name, "V", ("RVP", ("r", "p")), x=True)       # every option here is 3: GE 0 and > 0 the same

    again("FLO_FUNC")
    # --- RVP(R,V,P)$(NOT RPS_S1(R,P,'ANNUAL')) = NO;
    db.remove("RVP", where="not in_RPS_S1(r, p, 'ANNUAL')")
    for n in ("ACT_EFF", "ACT_FLO", "FLO_SUM"):
        again(n)
    # --- OPTION DATAYEAR<FIL;
    db.assign("DATAYEAR", "select * from dyn_datayear")
    clear(db)

def _fx0(db: DB, var, select):
    """VAR.FX(keys) = 0: the bounds of the keys given (d0..dn) become 0, 0 (replacing any given before)."""
    db.x(f"create or replace temp table dyn_fx as {select}")
    cols = [r[0] for r in db.q("describe dyn_fx")]
    decl = ", ".join(f"d{i} VARCHAR" for i in range(len(cols)))
    db.x(f'create table if not exists "B_{var}" ({decl}, lower DOUBLE, upper DOUBLE)')
    on = " and ".join(f"b.d{i}=f.{c}" for i, c in enumerate(cols))
    db.x(f'delete from "B_{var}" b where exists(select 1 from dyn_fx f where {on})')
    db.x(f'insert into "B_{var}" select distinct {", ".join(cols)}, 0.0, 0.0 from dyn_fx')
    db.bounds.add(var)


def bounds(db: DB):
    """dynslite.vda BOUNDS: the variables of the timeslices off fixed at zero; %MODEL_NAME%.HOLDFIXED=1 (the fixed
    variables are constants in the matrix: times_eq leaves them out, DYNFIX)."""
    if not _on(db):
        return
    # --- OPTION RTC_NET<RHS_COMBAL,RTC_PRD<RHS_COMPRD;
    db.assign("RTC_NET", "select distinct r, y, c from RHS_COMBAL")
    db.assign("RTC_PRD", "select distinct r, y, c from RHS_COMPRD")
    db.bounds = getattr(db, "bounds", set())
    k = "from RTP_VINTYR k join {j} where in_RT_PP(k.r, k.y2) and in_NORTS(k.r, k.y2, x.s)"
    v = "k.r, k.y, k.y2, k.p"
    # --- VAR_ACT.FX(RTP_VINTYR(R,V,T,P),S%SWT%$PRC_TS(R,P,S)) = 0;
    _fx0(db, "VAR_ACT", f"select {v}, x.s " + k.format(j="PRC_TS x on x.r=k.r and x.p=k.p"))
    rpcs = "RPCS_VAR x on x.r=k.r and x.p=k.p"
    # --- VAR_FLO / VAR_SIN / VAR_SOUT .FX(RTP_VINTYR(R,V,T,P),C,S%SWT%$RPCS_VAR(R,P,C,S)) = 0;
    for var in ("VAR_FLO", "VAR_SIN", "VAR_SOUT"):
        _fx0(db, var, f"select {v}, x.c, x.s " + k.format(j=rpcs))
    # --- VAR_IRE.FX(RTP_VINTYR(R,V,T,P),C,S,IE%SWT%$RPCS_VAR(R,P,C,S)) = 0;
    _fx0(db, "VAR_IRE", f"select {v}, x.c, x.s, i.ie " + k.format(j=rpcs + ", (select 'IMP' as ie union all select 'EXP') i"))
    # --- VAR_UPS.FX(RTP_VINTYR(R,V,T,P),S,L%SWT%$RPS_UPS(R,P,S)) = 0;
    _fx0(db, "VAR_UPS", f"select {v}, x.s, l.l " + k.format(j="RPS_UPS x on x.r=k.r and x.p=k.p, LIM l"))
    # --- VAR_UPT.FX(RTP_VINTYR(R,V,T,P),S,UPT%SWT%$RPS_UPS(R,P,S)$RP_DP(R,P)) = 0;
    _fx0(db, "VAR_UPT", f"select {v}, x.s, u.upt " + k.format(j="RPS_UPS x on x.r=k.r and x.p=k.p, (select 'COLD' as upt union all select 'WARM' union all select 'HOT') u")
         + " and in_RP_DP(k.r, k.p)")
    # --- VAR_UDP.FX(RTP_VINTYR(R,V,T,P),S,BD%SWT%$PRC_TS(R,P,S)$RP_UPR(R,P,BD)) = 0;
    _fx0(db, "VAR_UDP", f"select {v}, x.s, u.l " + k.format(j="PRC_TS x on x.r=k.r and x.p=k.p join RP_UPR u on u.r=k.r and u.p=k.p"))
    # --- VAR_COMNET.FX(RTC_NET(R,T,C),S%SWT%$COM_TS(R,C,S)) = 0;   VAR_COMPRD: RTC_PRD
    for var, rtc in (("VAR_COMNET", "RTC_NET"), ("VAR_COMPRD", "RTC_PRD")):
        _fx0(db, var, f"""select k.r, k.y, k.c, x.s from {rtc} k join COM_TS x on x.r=k.r and x.c=k.c
                          where in_RT_PP(k.r, k.y) and in_NORTS(k.r, k.y, x.s)""")
    # --- $IF %VAR_UC%==YES UC_RHSMAP(R,T,UCN,UC_NUMBER,S)%TMP% = NO;
    if db.ctl.get("VAR_UC"):
        _off(db, "UC_RHSMAP")
