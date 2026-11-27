# SPDX-License-Identifier: GPL-3.0-or-later
"""Prices of exogenous trade taken from an earlier run ($SET GDX_IPRIC <run>): init_ext.vda 137-156, bnd_ire.vda.

A model cut out of a larger one (some regions of it) trades with the regions left out through exogenous trade
processes.  With GDX_IPRIC, TIMES prices that trade at the marginal prices of the larger run: for the trade flows that
were endogenous there (RPC_IREIO(..,'IN') of that run) and are not endogenous here, the prices PAR_IPRIC of that run
replace OBJ_IPRIC, period by period.

    init_ext.vda 147-156
      $IF NOT SET GDX_IPRIC $GOTO FINISH
      $IF NOT EXIST %GDXPATH%%GDX_IPRIC%.GDX $GOTO FINISH
      $GDXIN %GDXPATH%%GDX_IPRIC%
      $LABEL LOAD2 LOAD RPC_IREIN=RPC_IREIO PREMILE=MILESTONYR PAR_IPRIC
      $GDXIN
      $LABEL FINISH
      PAR_IPRIC(R,T,P,C,TS,IE)$RPC_IREIN(R,P,C,IE,'OUT') = 0;
      RPC_IREIN(R,P,C,IE,'OUT') = NO;

    bnd_ire.vda (equ_ext.vda 67: $ IF DEFINED PREMILE $BATINCLUDE bnd_ire.vda)
      RPC_IREIN(RPC_IREIO) = NO;
      PAR_IPRIC(R,T,P,C,TS,IE)$(NOT RPC_IREIN(R,P,C,IE,'IN')) = 0;
      OPTION CLEAR=FIL; LOOP(T$(NOT PREMILE(T)),FIL(TT)$YK(TT,T) = YES);
      $BATINCLUDE fillcost PAR_IPRIC R 'P,C,TS,IE' ",'0'" FIL CARD(FIL) '' '' PAR_IPRIC X_IREFLO
      LOOP(T$CARD(PAR_IPRIC),
        OBJ_IPRIC(R,Y_EOH,P,C,TS,IE,CUR)$(PERIODYR(T,Y_EOH)$RPCS_VAR(R,P,C,TS)$RPC_IREIN(R,P,C,IE,'IN')) =
          PAR_IPRIC(R,T,P,C,TS,IE));

$LOAD takes the records whose labels are in the domains declared here (RPC_IREIN(R,P,C,IE,IO), PREMILE(ALLYEAR),
PAR_IPRIC(R,ALLYEAR,P,C,TS,IE)) and leaves the others out.

The file is a GDX written by GAMS.  As for the other results of earlier runs (refpoint.py), it is read when the run is
compared with TIMES in GAMS, which reads it too; a run on its own refuses the switch.  The periods of the earlier run
must hold those of this one (FIL empty): prices carried to other periods (fillcost) are not ported.  The trade flows
fixed from an earlier run (GDX_IREBND, PAR_IRE) are refused in controls.py.
"""
from ..engine import DB
from ..controls import unsupported, given
from .. import refpoint


def _read(path, names):
    """{name: rows} of the sets and parameters `names` of a GDX file: label tuples, a parameter with its value last
    (EPS as 0)."""
    gt, d = refpoint.gdx_library()
    if gt is None:
        from ..controls import NotPorted
        raise NotPorted(f"{path} is a GDX file and the GDX library does not load ({d})")
    c = gt.Container(system_directory=d)
    have = refpoint._gdx_names(path, gt, d)
    c.read(path, symbols=[n for n in names if n in have])
    out = {}
    for n in names:
        s = c.data.get(n)
        if s is None or s.records is None or len(s.records) == 0:
            out[n] = []
            continue
        df = s.records
        k = s.dimension
        labels = [df.iloc[:, i].astype(str).tolist() for i in range(k)]
        if isinstance(s, gt.Parameter):
            vals = refpoint._plain(df["value"].to_numpy(), gt)
            out[n] = [tuple(lab[i] for lab in labels) + (vals[i],) for i in range(len(df))]
        else:
            out[n] = [tuple(lab[i] for lab in labels) for i in range(len(df))]
    return out


def bnd_ire(db: DB):
    """init_ext.vda 147-156 and bnd_ire.vda: OBJ_IPRIC from the prices PAR_IPRIC of the run GDX_IPRIC names.  Nothing
    without the switch, or when its GDX file is not there (init_ext.vda 148)."""
    if "GDX_IPRIC" not in getattr(db, "trade_gdx", ()):
        return
    name = given(db.env, "GDX_IPRIC")
    d, stem = refpoint.locate(refpoint.run_folder(db), name)
    path = refpoint._exists(d, stem + ".gdx")
    if path is None:
        return
    if not refpoint.from_gams():
        unsupported(db, f"run-file switch GDX_IPRIC in a run on its own: the trade prices of run {name} are a GDX file of GAMS, "
                        "read only when the run is compared with TIMES in GAMS (--check, --gams run)")
        return
    got = _read(path, ["RPC_IREIO", "MILESTONYR", "PAR_IPRIC"])
    refpoint.note_read(db, path, f"GDX_IPRIC {name}: the trade prices of an earlier run (bnd_ire.vda)")
    canon = lambda sql: {str(x).upper(): x for (x,) in db.q(sql)}
    R, P, C, S, Y = (canon(f'select * from "{n}"') for n in ("REG", "PRC", "COM", "ALL_TS", "ALLYEAR"))
    U = str.upper
    # --- $LOAD RPC_IREIN=RPC_IREIO PREMILE=MILESTONYR PAR_IPRIC     (the records inside the domains)
    irein = {(R[U(r)], P[U(p)], C[U(c)], U(ie), U(io)) for r, p, c, ie, io in got["RPC_IREIO"]
             if U(r) in R and U(p) in P and U(c) in C and U(ie) in ("IMP", "EXP") and U(io) in ("IN", "OUT")}
    premile = {Y[U(y)] for (y,) in got["MILESTONYR"] if U(y) in Y}
    ipric = {(R[U(r)], Y[U(y)], P[U(p)], C[U(c)], S[U(s)], U(ie)): v for r, y, p, c, s, ie, v in got["PAR_IPRIC"]
             if U(r) in R and U(y) in Y and U(p) in P and U(c) in C and U(s) in S and U(ie) in ("IMP", "EXP")}
    T = [y for (y,) in db.q("select y from MILESTONYR order by yv(y)")]
    Ts = set(T)
    rpci = lambda k: (k[0], k[2], k[3], k[5])
    # --- PAR_IPRIC(R,T,P,C,TS,IE)$RPC_IREIN(R,P,C,IE,'OUT') = 0;   RPC_IREIN(R,P,C,IE,'OUT') = NO;
    out = {k[:4] for k in irein if k[4] == "OUT"}
    ipric = {k: v for k, v in ipric.items() if not (k[1] in Ts and rpci(k) in out)}
    irein = {k for k in irein if k[4] != "OUT"}
    # --- RPC_IREIN(RPC_IREIO) = NO;
    irein -= set(db.q("select r, p, c, ie, io from RPC_IREIO"))
    # --- PAR_IPRIC(R,T,P,C,TS,IE)$(NOT RPC_IREIN(R,P,C,IE,'IN')) = 0;
    inn = {k[:4] for k in irein if k[4] == "IN"}
    ipric = {k: v for k, v in ipric.items() if not (k[1] in Ts and rpci(k) not in inn)}
    db.trade_prices = {"file": path, "records": len(ipric)}
    # --- OPTION CLEAR=FIL; LOOP(T$(NOT PREMILE(T)),FIL(TT)$YK(TT,T) = YES);   fillcost PAR_IPRIC .. FIL CARD(FIL) ..
    if any(t not in premile for t in T):
        unsupported(db, f"run-file switch GDX_IPRIC with periods that run {name} does not have "
                        "(its trade prices carried to other milestone years, bnd_ire.vda 20-26)")
        return
    # --- LOOP(T$CARD(PAR_IPRIC),
    #       OBJ_IPRIC(R,Y_EOH,P,C,TS,IE,CUR)$(PERIODYR(T,Y_EOH)$RPCS_VAR(R,P,C,TS)$RPC_IREIN(R,P,C,IE,'IN')) =
    #         PAR_IPRIC(R,T,P,C,TS,IE));
    #     (an assignment with =: where the price of the earlier run is 0, the price of this run goes; EPS stays EPS.
    #      CUR is free in the statement, every currency declared; the objective reads the prices of the currencies
    #      of the region, RDCUR(R,CUR) (eqobjvar.mod 54-55), and only those are written)
    if not ipric:
        return
    db.x("create or replace temp table t_irein (r VARCHAR, p VARCHAR, c VARCHAR, ie VARCHAR)")
    db.insert_rows("t_irein", sorted(inn))
    db.x("create or replace temp table t_ipric (r VARCHAR, y VARCHAR, p VARCHAR, c VARCHAR, s VARCHAR, ie VARCHAR, value DOUBLE)")
    db.insert_rows("t_ipric", sorted(k + (v,) for k, v in ipric.items() if k[1] in Ts))
    db.remove("OBJ_IPRIC", where="""in_Y_EOH(y) and in_RPCS_VAR(r,p,c,s)
                   and exists(select 1 from PERIODYR q where q.y2=OBJ_IPRIC.y and in_MILESTONYR(q.y))
                   and exists(select 1 from t_irein i where i.r=OBJ_IPRIC.r and i.p=OBJ_IPRIC.p and i.c=OBJ_IPRIC.c and i.ie=OBJ_IPRIC.ie)""")
    db.put("OBJ_IPRIC", """select a.r, q.y2 as y, a.p, a.c, a.s, a.ie, u.cur, a.value
                           from t_ipric a join PERIODYR q on q.y=a.y join RDCUR u on u.r=a.r
                           where in_Y_EOH(q.y2) and in_RPCS_VAR(a.r,a.p,a.c,a.s)
                             and exists(select 1 from t_irein i where i.r=a.r and i.p=a.p and i.c=a.c and i.ie=a.ie)""", zero="eps")
