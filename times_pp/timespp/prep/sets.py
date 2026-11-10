# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod and pp_qack.mod: the control sets of regions, processes and commodities, of the commodity balances
and of the variables."""
from ..engine import DB
from .common import require_empty
from . import dynslite, reduce, stochastic


# ---------------------------------------------------------------------------
def control_sets(db: DB):
    """Region/process/commodity control sets; primary and shadow primary groups."""
    # --- MI_DMAS(COM_GMAP(RC,C)) = YES; MI_DMAS(R,C,C) = NO;      (a commodity used as a group of others)
    n = db.tmp("t_dmas", "select r, cg as c, c as c2 from COM_GMAP where in_RC(r,cg) and cg <> c")
    if n:
        # --- OPTION DEM<TOP; LOOP(MI_DMAS(DEM(R,C),COM), ... 'Commodity group found in topology violating its integrity')
        for r, c in db.q("select distinct r, c from t_dmas d where exists(select 1 from TOP t where t.r=d.r and t.c=d.c)"):
            db.log.append(f"*09 SEVERE ERROR  - Commodity group found in topology; group removed from topology: R={r} CG={c}")
        # --- OPTION DEM<=MI_DMAS; RC(DEM)=NO; RPC(R,P,C)$DEM(R,C)=NO;
        db.remove("RC", select="select distinct r, c from t_dmas")
        db.remove("RPC", where="exists(select 1 from t_dmas d where d.r=RPC.r and d.c=RPC.c)")
    # --- COM_GMAP(RC(R,C),C) = YES;
    db.add("COM_GMAP", "select r, c as cg, c from RC")
    # --- NRG_GMAP(R,NRG_GRID(NRG_TYPE),C) $= NRG_TMAP(R,NRG_TYPE,C);
    db.add("NRG_GMAP", "select r, nrg_type as nrg_grid, c from NRG_TMAP where in_NRG_GRID(nrg_type) and in_REG(r)")
    # --- PRC_CG(RPC) = YES;  PRC_CG(RP_PG) = YES;
    db.add("PRC_CG", "select r, p, c as cg from RPC")
    db.add("PRC_CG", "select r, p, cg from RP_PG")
    # --- OPTION MI_DMAS<=COM_AGG,FIN<COM_TMAP; LOOP(MI_DMAS(R,COM,C)$(FIN(R,COM)$FIN(R,C)),RC(R,C)=YES);
    db.add("RC", """select distinct a.r, a.c2 as c from COM_AGG a where in_REG(a.r)
                    and exists(select 1 from COM_TMAP m where m.r=a.r and m.c=a.c)
                    and exists(select 1 from COM_TMAP m where m.r=a.r and m.c=a.c2)""")
    # --- RPC_CAPFLO(RTP,C)$(NCAP_ICOM(RTP,C)+NCAP_OCOM(RTP,C)) = YES;  RPC_CAPFLO(RTP,C) $= SUM(IO$NCAP_COM(RTP,C,IO),1);
    #     (an entry given as 0 is EPS and counts: EPS + EPS = EPS, which tests as non-zero; only a true sum of 0 does not)
    db.add("RPC_CAPFLO", """select r, y, p, c from (select r, y, p, c, value from NCAP_ICOM union all
                                                  select r, y, p, c, value from NCAP_OCOM) a
                            where in_RTP(r,y,p) group by r, y, p, c having sum(value) <> 0 or max(abs(value)) = 0
                            union select r, y, p, c from NCAP_COM where in_RTP(r,y,p)""")
    # --- OPTION RPC_NOFLO < RPC_CAPFLO;  LOOP(RPC_NOFLO(R,P,C)$(NOT RC(R,C)),RC(R,C)=YES);
    db.assign("RPC_NOFLO", "select distinct r, p, c from RPC_CAPFLO")
    db.add("RC", "select distinct r, c from RPC_NOFLO")
    # --- RPC_PG(RPC(R,P,C))$SUM(RP_PG(R,P,CG)$COM_GMAP(R,CG,C),1) = YES;
    db.add("RPC_PG", """select k.r, k.p, k.c from RPC k
                        where exists(select 1 from RP_PG g where g.r=k.r and g.p=k.p and in_COM_GMAP(k.r, g.cg, k.c))""")
    # --- RPC_PG(RP_IRE(R,P),C)$(NOT RPC_IRE(R,P,C,'IMP')+RPC_IRE(R,P,C,'EXP')) = NO;
    db.remove("RPC_PG", where="in_RP_IRE(r,p) and not (in_RPC_IRE(r,p,c,'IMP') or in_RPC_IRE(r,p,c,'EXP'))")
    # --- RPC_PG(PRC_STGTSS(RP,C))$SUM(PRC_TSL(RP,TSL)$(ORD(TSL)>1),1)=YES;
    db.add("RPC_PG", """select g.r, g.p, g.c from PRC_STGTSS g where in_RP(g.r,g.p)
                        and exists(select 1 from PRC_TSL l where l.r=g.r and l.p=g.p and l.tsl <> 'ANNUAL')""")
    # --- RP_PGTYPE(RP(R,P),COM_TYPE)$SUM(RPC_PG(R,P,C)$COM_TMAP(R,COM_TYPE,C),1) = YES;
    db.add("RP_PGTYPE", "select distinct g.r, g.p, m.cg from RPC_PG g join COM_TMAP m on m.r=g.r and m.c=g.c where in_RP(g.r,g.p)")
    # --- RP_AIRE(RP_IRE(RP),IE)$SUM(RPC_IRE(RPC_PG(RP,C),IE),1) = YES;
    db.add("RP_AIRE", """select distinct i.r, i.p, i.ie from RPC_IRE i where in_RP(i.r,i.p) and in_RP_IRE(i.r,i.p)
                         and in_RPC_PG(i.r,i.p,i.c)""")
    # --- RP_INOUT(RP,IO)$SUM(TOP(RPC_PG(RP,C),IO),1) = YES;
    db.add("RP_INOUT", "select distinct t.r, t.p, t.io from TOP t where in_RP(t.r,t.p) and in_RPC_PG(t.r,t.p,t.c)")
    # --- TRACKP(RP_FLO(RP))$(NOT SUM(PRC_SPG(RP,COM_GRP),1)) = YES;
    db.tmp("t_trackp", "select r, p from RP_FLO f where not exists(select 1 from PRC_SPG g where g.r=f.r and g.p=f.p)")
    # --- LOOP((RP_PGTYPE(RP_FLO(R,P),CG),IO)$(NOT RP_INOUT(R,P,IO)), IF(TRACKP(R,P), ...
    db.tmp("t_side", """select g.r, g.p, g.cg, i.io from RP_PGTYPE g join t_trackp k on k.r=g.r and k.p=g.p,
                        (select 'IN' as io union all select 'OUT') i
                        where in_RP_FLO(g.r,g.p) and not in_RP_INOUT(g.r,g.p,i.io)""")
    #   IF(SUM(TOP(R,P,C,IO)$COM_GMAP(R,CG,C),1),PRC_SPG(R,P,CG) = YES;       same type as the PG on the other side
    db.tmp("t_same", """select * from t_side k where exists(select 1 from TOP t where t.r=k.r and t.p=k.p and t.io=k.io
                                                              and in_COM_GMAP(k.r,k.cg,t.c))""")
    #   ELSE IF((SUM(RPC(R,P,C)$COM_TMAP(R,'MAT',C),1)$SUM(PRC_MAP(R,MATPRC,P),1))$RP_PGTYPE(R,P,'DEM'), PRC_SPG(R,P,'MAT') = YES;
    db.tmp("t_mat", """select * from t_side k where not exists(select 1 from t_same z where z.r=k.r and z.p=k.p and z.cg=k.cg and z.io=k.io)
                       and exists(select 1 from RPC c where c.r=k.r and c.p=k.p and in_COM_TMAP(k.r,'MAT',c.c))
                       and exists(select 1 from PRC_MAP m where m.r=k.r and m.p=k.p and in_MATPRC(m.prc_grp))
                       and in_RP_PGTYPE(k.r,k.p,'DEM')""")
    #   ELSE Z=1; LOOP(PG_SMAP(CG,J,COM_TYPE)$Z, IF(SUM(TOP(R,P,C,IO)$COM_TMAP(R,COM_TYPE,C),1), Z=0; PRC_SPG(R,P,COM_TYPE) = YES)));
    db.tmp("t_first", """select k.r, k.p, arg_min(m.cg2, cast(m.j as INTEGER)) as cg from t_side k join PG_SMAP m on m.cg=k.cg
                         where not exists(select 1 from t_same z where z.r=k.r and z.p=k.p and z.cg=k.cg and z.io=k.io)
                           and not exists(select 1 from t_mat z where z.r=k.r and z.p=k.p and z.cg=k.cg and z.io=k.io)
                           and exists(select 1 from TOP t where t.r=k.r and t.p=k.p and t.io=k.io and in_COM_TMAP(k.r,m.cg2,t.c))
                         group by k.r, k.p, k.cg, k.io""")
    db.add("PRC_SPG", "select r, p, cg from t_same union select r, p, 'MAT' from t_mat union select r, p, cg from t_first")
    # --- LOOP((PRC_SPG(R,P,CG),IO)$(NOT RP_INOUT(R,P,IO)),RPC_SPG(R,P,C)$(TOP(R,P,C,IO)$COM_GMAP(R,CG,C)) = YES);
    db.add("RPC_SPG", """select distinct t.r, t.p, t.c from PRC_SPG g join TOP t on t.r=g.r and t.p=g.p
                         where in_REG(g.r) and not in_RP_INOUT(g.r,g.p,t.io) and in_COM_GMAP(g.r,g.cg,t.c)""")
    # --- PRC_CG(PRC_SPG) = YES;
    db.add("PRC_CG", "select r, p, cg from PRC_SPG where in_REG(r)")


# ---------------------------------------------------------------------------
def balance_control_sets(db: DB):
    """Control sets of the commodity balance equations; blending."""
    # --- RCS_COMBAL(RTCS_VARC(R,T,C,S),LIM)$(COM_LIM(R,C,LIM) * (NOT RHS_COMBAL(R,T,C,S))) = YES;
    db.add("RCS_COMBAL", """select k.r, k.y, k.c, k.s, m.l from RTCS_VARC k join COM_LIM m on m.r=k.r and m.c=k.c
                            where not in_RHS_COMBAL(k.r,k.y,k.c,k.s)""")
    # --- RCS_COMBAL(RHS_COMBAL,'FX') = YES;  RCS_COMPRD(RHS_COMPRD,'FX') = YES;
    db.add("RCS_COMBAL", "select r, y, c, s, 'FX' as l from RHS_COMBAL")
    db.add("RCS_COMPRD", "select r, y, c, s, 'FX' as l from RHS_COMPRD")
    # (BLE_INP is declared empty in ppmain.mod 1240 and its assignment, 1271, is a comment: GAMS cannot be given it)
    require_empty(db, ["BLE_INP"], "refinery blending input set BLE_INP")
    # (BL_SPEC, BL_COM, BL_TYPE and RU_CVT are read as they are by EQ_BLND, eqblnd.mod: times_eq)
    # --- BLE_SPE(R,COM,SPE)$BL_TYPE(R,COM,SPE) = YES;
    db.add("BLE_SPE", "select r, c, spe from BL_TYPE")
    # --- REFUNIT(R)$(NOT REFUNIT(R)) = 1;
    #     (NOT EPS is false: a value given as 0 (EPS under $ONEPS) stays)
    db.put("REFUNIT", "select r, 1 as value from REG where not in_REFUNIT(r)")
    # --- LOOP(BLE_SPE(R,BLE,SPE), BLE_TP(R,T,BLE)$(YEARVAL(T) >= BL_START(R,BLE,SPE)) = YES);
    db.add("BLE_TP", """select distinct b.r, t.y, b.c as u from BLE_SPE b, MILESTONYR t
                        where in_BLE(b.c) and yv(t.y) >= v_BL_START(b.r,b.c,b.spe)""")
    # --- BL_UNIT(BLE_SPE(R,BLE,SPE))$(NOT BL_UNIT(R,BLE,SPE)) = 1;
    db.put("BL_UNIT", "select r, c, spe, 1 as value from BLE_SPE where in_BLE(c) and not in_BL_UNIT(r,c,spe)")
    # --- BLE_SPEOPR(BLE_SPE(R,BLE,SPE),OPR)$BL_COM(R,BLE,OPR,SPE) = YES;
    db.add("BLE_SPEOPR", """select b.r, b.c, b.spe, m.opr from BLE_SPE b join BL_COM m on m.r=b.r and m.c=b.c and m.spe=b.spe
                            where in_BLE(b.c) and in_OPR(m.opr)""")
    # --- BLE_SPEINP(R,BLE,SPE,COM)$(BLE_SPE(R,BLE,SPE) * BLE_INP(R,BLE,COM)) = YES;   (BLE_INP is empty: nothing)
    # --- LOOP(BLE_SPEOPR(R,BLE,SPE,OPR), BLE_OPR(R,BLE,OPR) = YES);
    db.add("BLE_OPR", "select distinct r, c, opr as c2 from BLE_SPEOPR")
    # --- LOOP(BLE_OPR(R,BLE,OPR), BLE_ENV(R,C,BLE,OPR)$(ENV(R,C) * SUM(T, ENV_BL(R,C,BLE,OPR,T))) = YES);
    db.add("BLE_ENV", """select e.r, e.c, e.c2, e.opr from ENV_BL e
                         where in_BLE_OPR(e.r,e.c2,e.opr) and in_ENV(e.r,e.c) and in_MILESTONYR(e.y)
                         group by e.r, e.c, e.c2, e.opr having sum(e.value) <> 0 or bool_or(e.value = 0)""")
    #     (a sum of 0 with a record given as 0 is EPS, and $EPS is true)
    # --- PEAKDA_BL(R,BLE,T)$((NOT PEAKDA_BL(R,BLE,T))$SUM(COM_PEAK(R,C)$BLE_INP(R,BLE,C),1)) = 1;   (BLE_INP empty: nothing)
    # --- BLE_BAL(BLE_TP(R,T,BLE),OPR2)$OPR(BLE) = 1;
    #     BLE_BAL(BLE_TP(R,T,BLE),OPR2)$(NOT OPR(BLE)) = 1$(REFUNIT(R)=1) + CONVERT(OPR2,'WCV')$(REFUNIT(R)=2) + CONVERT(OPR2,'VCV')$(REFUNIT(R)=3);
    db.put("BLE_BAL", """select b.r, b.y, b.u as c, o.c as c2,
                                case when in_OPR(b.u) then 1.0
                                     when v_REFUNIT(b.r) = 1 then 1.0
                                     when v_REFUNIT(b.r) = 2 then v_CONVERT(o.c,'WCV')
                                     when v_REFUNIT(b.r) = 3 then v_CONVERT(o.c,'VCV') else 0.0 end as value
                         from BLE_TP b, OPR o where in_BLE(b.u)""")
    #     (a CONVERT given as EPS: the term it gives is EPS, and so is BLE_BAL)
    db.put("BLE_BAL", """select b.r, b.y, b.u as c, o.c as c2, 0.0 as value
                         from BLE_TP b, OPR o where in_BLE(b.u) and not in_OPR(b.u)
                           and ((v_REFUNIT(b.r) = 2 and in_CONVERT(o.c,'WCV') and v_CONVERT(o.c,'WCV') = 0)
                             or (v_REFUNIT(b.r) = 3 and in_CONVERT(o.c,'VCV') and v_CONVERT(o.c,'VCV') = 0))""", zero="eps")
    # --- the REFUNIT / BL_UNIT and FEQ look-up tables (LOOP(R, IF(REFUNIT(R) = 3, ...); IF(... = 2 ...); IF(... = 1 ...)))
    #     volume:  RU_CVT = 1$(BL_UNIT=3) + CONVERT(OPR,'DENS')$(BL_UNIT=2) + CONVERT(OPR,'VCV')$(BL_UNIT=1);  RU_FEQ(R,OPR,T) = CONVERT(OPR,'VCV')
    #     weight:  RU_CVT = (1/CONVERT(OPR,'DENS'))$(BL_UNIT=3) + 1$(BL_UNIT=2) + CONVERT(OPR,'WCV')$(BL_UNIT=1);  RU_FEQ(R,OPR,T) = CONVERT(OPR,'WCV')
    #     energy:  RU_CVT = (1/CONVERT(OPR,'VCV'))$(BL_UNIT=3) + (1/CONVERT(OPR,'WCV'))$(BL_UNIT=2) + 1$(BL_UNIT=1);  RU_FEQ(R,OPR,T) = 1
    if db.card("BLE_SPEOPR"):
        div = db.q("""select b.r, b.c, b.spe, b.opr from BLE_SPEOPR b
                      where (v_REFUNIT(b.r) = 2 and v_BL_UNIT(b.r,b.c,b.spe) = 3 and v_CONVERT(b.opr,'DENS') = 0)
                         or (v_REFUNIT(b.r) = 1 and v_BL_UNIT(b.r,b.c,b.spe) = 3 and v_CONVERT(b.opr,'VCV') = 0)
                         or (v_REFUNIT(b.r) = 1 and v_BL_UNIT(b.r,b.c,b.spe) = 2 and v_CONVERT(b.opr,'WCV') = 0)""")
        if div:
            raise SystemExit(f"blending: RU_CVT divides by a CONVERT of 0 (GAMS: division by zero, ppmain.mod 1319-1329): {div[:3]}")
    db.put("RU_CVT", """select b.r, b.c as ble, b.spe, b.opr,
                               case v_REFUNIT(b.r)
                                 when 3 then (case v_BL_UNIT(b.r,b.c,b.spe) when 3 then 1.0 when 2 then v_CONVERT(b.opr,'DENS')
                                                                            when 1 then v_CONVERT(b.opr,'VCV') else 0.0 end)
                                 when 2 then (case v_BL_UNIT(b.r,b.c,b.spe) when 3 then 1/v_CONVERT(b.opr,'DENS') when 2 then 1.0
                                                                            when 1 then v_CONVERT(b.opr,'WCV') else 0.0 end)
                                 when 1 then (case v_BL_UNIT(b.r,b.c,b.spe) when 3 then 1/v_CONVERT(b.opr,'VCV')
                                                                            when 2 then 1/v_CONVERT(b.opr,'WCV') when 1 then 1.0 else 0.0 end)
                                 else 0.0 end as value
                        from BLE_SPEOPR b""")
    #     (the CONVERT a term picks given as EPS: RU_CVT is EPS, a record)
    db.put("RU_CVT", """select b.r, b.c as ble, b.spe, b.opr, 0.0 as value from BLE_SPEOPR b
                        where (v_REFUNIT(b.r) = 3 and v_BL_UNIT(b.r,b.c,b.spe) = 2 and in_CONVERT(b.opr,'DENS') and v_CONVERT(b.opr,'DENS') = 0)
                           or (v_REFUNIT(b.r) = 3 and v_BL_UNIT(b.r,b.c,b.spe) = 1 and in_CONVERT(b.opr,'VCV') and v_CONVERT(b.opr,'VCV') = 0)
                           or (v_REFUNIT(b.r) = 2 and v_BL_UNIT(b.r,b.c,b.spe) = 1 and in_CONVERT(b.opr,'WCV') and v_CONVERT(b.opr,'WCV') = 0)""",
           zero="eps")
    #     (RU_FEQ(R,OPR,T) = CONVERT(...) copies an EPS; then RU_FEQ(R,OPR,T)$(NOT RU_FEQ(R,OPR,T)) = 1, and NOT EPS is false)
    db.put("RU_FEQ", """select g.r, o.c, t.y, v_CONVERT(o.c, case v_REFUNIT(g.r) when 3 then 'VCV' else 'WCV' end) as value
                        from REG g, OPR o, MILESTONYR t
                        where v_REFUNIT(g.r) in (2, 3) and in_CONVERT(o.c, case v_REFUNIT(g.r) when 3 then 'VCV' else 'WCV' end)""",
           zero="eps")
    db.put("RU_FEQ", """select g.r, o.c, t.y, 1.0 as value from REG g, OPR o, MILESTONYR t
                        where not in_RU_FEQ(g.r,o.c,t.y)""")


# ---------------------------------------------------------------------------
def variable_control_sets(db: DB):
    """pp_reduce.red (at the level of the run file's REDUCE: prep/reduce.py), flow variable control set RTPCS_VARF,
    vintage control RTP_VINTYR."""
    # --- OPTION RVP < RTP_CPTYR;  RTP_VARA(R,T,P)$(NOT RVP(R,T,P)) = NO;
    db.assign("RVP", "select distinct r, y2 as y, p from RTP_CPTYR")
    db.remove("RTP_VARA", where="in_MILESTONYR(y) and not in_RVP(r,y,p)")
    # ---- pp_reduce.red
    # --- PRC_CAP(RP) = YES;  PRC_ACT(RP) = RP_STD(RP)+RP_IRE(RP);  OPTION RP_AFB < NCAP_AF;
    db.assign("PRC_CAP", "select r, p from RP")
    db.assign("PRC_ACT", "select r, p from RP where in_RP_STD(r,p) or in_RP_IRE(r,p)")
    db.clear("RP_AFB")
    db.put("RP_AFB", "select r, p, l, count(*) as value from NCAP_AF group by r, p, l")   # number of records
    # --- $SETGLOBAL CAL_RED 'cal_nored.red'
    #     $IF %REDUCE% == NO $GOTO REDDONE
    #     ... (the reduction, prep/reduce.py)
    #     $LABEL REDDONE
    reduce.reduce(db)
    reduce.reddone(db)
    # --- $LABEL REDDONE ...  PRC_TS2(PRC_TS(RP_XRED(R,P),S)) = YES;     (also without reduction; read only by cal_red.red)
    db.add("PRC_TS2", "select r, p, s from PRC_TS where in_RP_XRED(r,p)")
    # --- RPC_PKC(RP,C)$(NOT PRC_CAP(RP)) = NO;  RPC_PKF(RPC_PKC) = 0;
    db.remove("RPC_PKC", where="in_RP(r,p) and not in_PRC_CAP(r,p)")
    db.zap("RPC_PKF", "in_RPC_PKC(r,p,c)")
    # --- $IF NOT %RTS%==S $BATINCLUDE dynslite.vda REDUCE
    dynslite.reduce(db)
    # --- RTPCS_VARF(RTPC(RTP_VARA(R,T,P),C),S)$((NOT RTPCS_OUT(R,T,P,C,S))$RPCS_VAR(R,P,C,S)) = YES;
    db.add("RTPCS_VARF", """select k.r, k.y, k.p, k.c, v.s from RTPC k join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c=k.c
                            where in_RTP_VARA(k.r,k.y,k.p) and not in_RTPCS_OUT(k.r,k.y,k.p,k.c,v.s)""")
    # --- RTP_VINTYR(RTP_CPTYR(R,V,T,P))$PRC_VINT(R,P)= YES;
    db.add("RTP_VINTYR", "select r, y, y2, p from RTP_CPTYR where in_PRC_VINT(r,p)")
    # --- RTP_VINTYR(R,T,T,P)$((NOT PRC_VINT(R,P))*RTP(R,T,P)$RVP(R,T,P)) = YES;
    db.add("RTP_VINTYR", """select r, y, y as y2, p from RTP where in_MILESTONYR(y) and not in_PRC_VINT(r,p) and in_RVP(r,y,p)""")
    db.clear("R_UC", "RVP", "RTPCS_OUT")


def final_control_sets(db: DB):
    # --- spoint.mod 22: $IF %STAGES%==YES $BATINCLUDE clearsol.stc ALL   (before the solve; prep/stochastic.py)
    stochastic.rvprl_at_solve(db)
    # --- RPC_CONLY(RTPC(R,T,P,C))$RPC_NOFLO(R,P,C) = YES;                 flows that exist only through capacity
    db.add("RPC_CONLY", "select r, y, p, c from RTPC where in_MILESTONYR(y) and in_RPC_NOFLO(r,p,c)")
    # --- RTPCS_VARF(RPC_CONLY,S) = NO;
    db.remove("RTPCS_VARF", where="in_RPC_CONLY(r,y,p,c)")
    # --- RCS_COMBAL(RHS_COMBAL,BDNEQ) = NO;
    db.remove("RCS_COMBAL", where="l in ('LO','UP') and in_RHS_COMBAL(r,y,c,s)")
    # --- TRACKPC(R,P,C)$(RPC_ACT(R,P,C)+RPC_FFUNC(R,P,C)+RPC_EMIS(R,P,C)) = YES;
    #     RPG_RED(R,P,CG,IO)$(NOT SUM(TOP(TRACKPC(R,P,C),IO)$COM_GMAP(R,CG,C),1)) = NO;
    db.remove("RPG_RED", where="""in_REG(r) and not exists(
        select 1 from TOP t where t.r=RPG_RED.r and t.p=RPG_RED.p and t.io=RPG_RED.io and in_COM_GMAP(t.r,RPG_RED.cg,t.c)
          and (in_RPC_ACT(t.r,t.p,t.c) or in_RPC_FFUNC(t.r,t.p,t.c) or in_RPC_EMIS(t.r,t.p,t.c)))""")
    # --- $IFI %VAR_UC%==YES OPTION UC_GMAP_U<=UC_UCN;
    if db.ctl["VAR_UC"]:
        db.assign("UC_GMAP_U", "select distinct r, uc, uc2 from UC_UCN")
    # --- RTP(NO_RVP) = NO;
    db.remove("RTP", where="in_NO_RVP(r,y,p)")
    # --- OPTION RTP_VNTBYR < RTP_VINTYR, COEF_VNT < COEF_CPT, TRACKP < RP_UPL;         (same indexes in another order)
    db.assign("RTP_VNTBYR", "select r, y2 as y, p, y as y2 from RTP_VINTYR")
    db.clear("COEF_VNT")
    db.x("insert into COEF_VNT select r, y2, p, y, value from COEF_CPT")
    # --- TRACKP(R,P)$=SUM(RP_PL(R,P,L),1); TRACKP(RP_XRED)=YES; TRACKP(CHP)=YES;
    db.tmp("t_p", "select r, p from RP_UPL union select r, p from RP_PL union select r, p from RP_XRED union select r, p from CHP")
    # --- RVP_KMAP(RTP(R,V,P),V)$(PRC_VINT(R,P)$TRACKP(R,P)) = YES; TRACKP(PRC_VINT)=NO;
    # --- RVP_KMAP(RTP(R,T,P),V)$(COEF_VNT(RTP,V)$TRACKP(R,P)) = YES;
    db.add("RVP_KMAP", """select k.r, k.y, k.p, k.y as y2 from RTP k join t_p t on t.r=k.r and t.p=k.p
                          where in_MODLYEAR(k.y) and in_PRC_VINT(k.r,k.p)""")
    db.add("RVP_KMAP", """select c.r, c.y, c.p, c.y2 from COEF_VNT c join t_p t on t.r=c.r and t.p=c.p
                          where in_RTP(c.r,c.y,c.p) and in_MODLYEAR(c.y2) and not in_PRC_VINT(c.r,c.p)""")
    # --- OPTION CLEAR=TRACKPC,CLEAR=TRACKP,CLEAR=RP_XRED;
    db.clear("RP_XRED")
    # --- OPTION CLEAR=TRACKPC,CLEAR=PRC_CG;                                                    (pp_qack.mod 150)
    #     PRC_CG(RP_PG(R,P,CG))$=SUM(RPC_AFLO(R,P,C)$(NOT RPC_FFUNC(R,P,C)),1);                  (164)
    #     "Add PTRANS control for ACT_FLO": what eqptrans.mod reads of PRC_CG from here on is only the primary groups of
    #     processes with a flow given per unit of activity (ACT_FLO) that is not a transformation flow (RPC_FFUNC)
    db.clear("PRC_CG")
    db.add("PRC_CG", """select g.r, g.p, g.cg from RP_PG g
                        where exists(select 1 from RPC_AFLO a where a.r=g.r and a.p=g.p and not in_RPC_FFUNC(a.r,a.p,a.cg))""")
    qa_fatal_checks(db)
    # ---- the tables of the ancillary balancing services that the equations read (abs.final)
    from . import abs as abs_ext
    abs_ext.final(db)


def _qa_label(x):
    """A label as pp_qack.mod puts it in QA_CHECK.LOG (%RL%, %PL%, %CL%: X.TL:MAX(12,X.LEN))."""
    return x.ljust(12)


def qa_fatal_checks(db: DB):
    """pp_qack.mod 196-208: two level-99 checks, and the abort that a level-99 message brings at the end of pp_qack.mod
    (385-389).  The messages are those of QA_CHECK.LOG; the run stops before the equations, as GAMS does."""
    uel = lambda col: f"(select u.ord from __uel u where u.label={col})"
    lines = []
    # --- RTP_CG(RTPC(R,T,P,C),'IN')$(PRC_ACTFLO(RTPC)=0) $= RPC_PG(R,P,C);
    #     IF(CARD(RTP_CG), OPTION TRACKPG < RTP_CG;
    #       LOOP(TRACKPG(R,P,C), <QA 99: Process with zero PRC_ACTFLO for C in PG>
    #         PUT QLOG ' FATAL ERROR   -     R=',%RL%,' P=',%PL%,' C=',%CL%);
    #       OPTION CLEAR=RTP_CG,CLEAR=TRACKPC; PUTGRP=0);
    #     (an EPS PRC_ACTFLO is 0 here; no record is 0 too)
    rows = db.q(f"""select distinct k.r, k.p, k.c, {uel('k.r')} o1, {uel('k.p')} o2, {uel('k.c')} o3 from RTPC k
                    where in_RPC_PG(k.r,k.p,k.c) and v_PRC_ACTFLO(k.r,k.y,k.p,k.c) = 0 order by o1, o2, o3""")
    if rows:
        lines += ["", " *** Process with zero PRC_ACTFLO for C in PG"]
        lines += [f" *99 FATAL ERROR   -     R={_qa_label(r)} P={_qa_label(p)} C={_qa_label(c)}".rstrip() for r, p, c, *_ in rows]
    # --- RVPS(RTP,S)$((ACT_BND(RTP,S,'LO')>ACT_BND(RTP,S,'UP'))$ACT_BND(RTP,S,'UP'))=YES;
    #     IF(CARD(RVPS),RVPS(R,T,P,S)$(NOT RPS_PRCTS(R,P,S)$RTP_VARA(R,T,P))=NO; OPTION PRC_YMIN<RVPS;
    #       LOOP(RP(R,P)$PRC_YMIN(RP), <QA 99: Process has inconsistent ACT_BND(LO/UP) - Infeasible.>
    #         PUT QLOG ' FATALE ERROR  -     R=',%RL%,' P=',%PL%);
    #       OPTION CLEAR=RVPS,CLEAR=PRC_YMIN; PUTGRP=0);
    #     ($ binds before NOT: NOT (RPS_PRCTS(R,P,S)$RTP_VARA(R,T,P)); what stays is a bound on a timeslice of the process
    #      level, in a period with an activity variable.  An UP bound given as EPS counts: LO above it)
    rows = db.q(f"""select distinct b.r, b.p, {uel('b.r')} o1, {uel('b.p')} o2 from ACT_BND b
                    where b.l='UP' and in_RTP(b.r,b.y,b.p) and v_ACT_BND(b.r,b.y,b.p,b.s,'LO') > b.value
                      and in_RPS_PRCTS(b.r,b.p,b.s) and in_RTP_VARA(b.r,b.y,b.p) and in_RP(b.r,b.p)
                    order by o1, o2""")
    if rows:
        lines += ["", " *** Process has inconsistent ACT_BND(LO/UP) - Infeasible."]
        lines += [f" *99 FATALE ERROR  -     R={_qa_label(r)} P={_qa_label(p)}".rstrip() for r, p, *_ in rows]
    if lines:
        db.log += [l for l in lines if l]
        # --- IF(ERRLEV >= 33, IF(ERRLEV=33, ...; ELSE ABORT '*** FATAL QA ERROR - Check the QA_CHECK.LOG file for details ***'));
        raise SystemExit("QA_CHECK.LOG:\n" + "\n".join(lines[1:]) +
                         "\n\n*** FATAL QA ERROR - Check the QA_CHECK.LOG file for details ***")
