# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod and prepret.dsc: lifetimes, lead times and the capacity transfer set, capacity bounds and the periods
a process is available, availability factors by timeslice, early retirement and refits."""
import time
from .. import kernels
from ..controls import unsupported
import math
from ..engine import DB
from .common import require_empty, off_years, rnd
from . import simv, stochastic


# ---------------------------------------------------------------------------
def lifetimes_and_capacity_transfer(db: DB):
    """Lifetimes, lead times and the capacity transfer set RTP_CPTYR."""
    s = db.s
    # --- NCAP_TLIFE duration check:
    #     LOOP(SAMEAS(AGE,'1'), ... LOOP(RTP(R,T,P)$((NOT LIFE(AGE+(NCAP_TLIFE(RTP)-.999)))$NCAP_TLIFE(RTP)),
    #       IF(NCAP_TLIFE(RTP) < 1, RXX(RTP) = YES; ...));  NCAP_TLIFE(RXX(R,V,P)) = 1);
    #     The lag is rounded (GAMS ROUND): from AGE '1' it leaves LIFE when ROUND(TLIFE-.999) < 0 or >= CARD(AGE).
    #     So a life is set to 1 only when ROUND(TLIFE-.999) < 0, at 0.499 or below; a life between 0.5 and 1 stays.
    nage = db.card("AGE")
    for r, y, p, v in db.q("select r, y, p, v_NCAP_TLIFE(r,y,p) from RTP where in_MILESTONYR(y) and v_NCAP_TLIFE(r,y,p) <> 0"
                           f" and (ground(v_NCAP_TLIFE(r,y,p) - 0.999) < 0 or ground(v_NCAP_TLIFE(r,y,p) - 0.999) >= {nage})"):
        db.log.append(f"*01 WARNING - NCAP_TLIFE out of feasible range: {'Too short, set to 1' if v < 1 else 'No FOM beyond year %d' % nage}, R={r} P={p} V={y}")
    db.put("NCAP_TLIFE", "select r, y, p, 1 as value from RTP where in_MILESTONYR(y) and in_NCAP_TLIFE(r,y,p)"
                         " and ground(v_NCAP_TLIFE(r,y,p) - 0.999) < 0")
    db.clear("RXX")
    # --- NCAP_TLIFE(RTP)$(NOT NCAP_TLIFE(RTP)) = G_TLIFE;
    #     NOT EPS is false: a life given as 0 stays EPS on a past vintage (the check above sets it to 1 on milestone years
    #     only), as in GAMS
    db.put("NCAP_TLIFE", "select r, y, p, {G_TLIFE} as value from RTP where not in_NCAP_TLIFE(r,y,p)")
    # --- G_ILEDNO = (G_ILEDNO+2)%CTST%-2;
    c = db.ctl["CTST"]
    if c == "zero":
        s["G_ILEDNO"] = -1.0
    elif c == "eps":
        s["G_ILEDNO"] = (1.0 if s["G_ILEDNO"] + 2 > 0 else 0.0) - 2
    # --- COEF_ILED(RTP)$NCAP_ILED(RTP) = MAX(ABS(NCAP_ILED(RTP)),COEF_ILED(RTP));
    db.put("COEF_ILED", """select r, y, p, greatest(abs(v_NCAP_ILED(r,y,p)), v_COEF_ILED(r,y,p)) as value
                           from RTP where in_NCAP_ILED(r,y,p)""", zero="eps")       # MAX(ABS(EPS),0) = EPS
    # --- NCAP_ILED(RTP(R,V,P))$NCAP_ILED(RTP) = MAX(EPS,CEIL(NCAP_ILED(RTP)-0.5))$(COEF_ILED(RTP) > MIN(D(V),NCAP_TLIFE(RTP))/G_ILEDNO);
    db.x("""create or replace temp table n_iled as
            select r, y, p, v_COEF_ILED(r,y,p) > least(v_D(y), v_NCAP_TLIFE(r,y,p)) / {G_ILEDNO} as keep,
                   greatest(0, ceil(v_NCAP_ILED(r,y,p) - 0.5)) as value
            from RTP where in_NCAP_ILED(r,y,p)""")
    db.zap("NCAP_ILED", "exists(select 1 from n_iled n where n.r=NCAP_ILED.r and n.y=NCAP_ILED.y and n.p=NCAP_ILED.p and not n.keep)")
    db.put("NCAP_ILED", "select r, y, p, value from n_iled where keep", zero="eps")
    # --- NCAP_ILED(RTP(R,PHYR,P)) = NCAP_ILED(RTP)+COEF_RTP(RTP)+EPS;      PHYR: past years inside a period (INT_DEFAULT('PASTI'))
    db.put("NCAP_ILED", "select r, y, p, v_NCAP_ILED(r,y,p) + v_COEF_RTP(r,y,p) as value from RTP where in_PHYR(y)", zero="eps")
    # --- PRC_REFIT(R,P,PRC)$PRC_REFIT(R,P,PRC)=MAX(ABS(ROUND(PRC_REFIT(R,P,PRC))),MIN(6,ABS(MAX(ROUND(PRC_REFIT(R,P,P)),-1)*2)))*MOD(ROUND(PRC_REFIT(R,P,PRC)),2);
    db.x("""create or replace temp table n_refit as
            select r, p, p2, greatest(abs(ground(value)), least(6, abs(greatest(ground(v_PRC_REFIT(r,p,p)), -1) * 2)))
                             * (cast(ground(value) as BIGINT) % 2) as value from PRC_REFIT where in_REG(r)""")
    db.zap("PRC_REFIT", "in_REG(r)")
    db.put("PRC_REFIT", "select * from n_refit")
    # --- LOOP((RP(R,PRC),P)$PRC_REFIT(RP,P),IF(NOT PRC_RCAP(RP),RTP_OFF(R,T,P)=YES);
    db.add("RTP_OFF", """select distinct f.r, t.y, f.p2 as p from PRC_REFIT f, MILESTONYR t
                         where in_RP(f.r,f.p) and not in_PRC_RCAP(f.r,f.p)""")
    #       IF(PRC_REFIT(RP,P)<-4,NCAP_ELIFE(RTP(R,T,P))$(NCAP_ELIFE(RTP)<1)=NCAP_TLIFE(RTP);
    #         NCAP_TLIFE(RTP(R,T,P))=MAX(NCAP_TLIFE(R,T,PRC)+NCAP_ILED(R,T,PRC)-1,NCAP_TLIFE(RTP))));
    #       (T: the milestone years; the loop runs over the (host, refit) pairs in their order, so a refit process of
    #        two hosts takes the larger of their lives)
    for r, prc, p in db.q("""select r, p, p2 from PRC_REFIT where value < -4 and in_RP(r,p) order by all"""):
        db.put("NCAP_ELIFE", f"""select r, y, p, v_NCAP_TLIFE(r,y,p) as value from RTP
                                 where r='{r}' and p='{p}' and in_MILESTONYR(y) and v_NCAP_ELIFE(r,y,p) < 1""")
        db.put("NCAP_TLIFE", f"""select r, y, p, greatest(v_NCAP_TLIFE(r,y,'{prc}') + v_NCAP_ILED(r,y,'{prc}') - 1, v_NCAP_TLIFE(r,y,p)) as value
                                 from RTP where r='{r}' and p='{p}' and in_MILESTONYR(y)""")
    # --- NCAP_TLIFE(RVP)$((NCAP_PASTI(RVP)=0)$RTP_OFF(RVP)) = 1;
    db.put("NCAP_TLIFE", "select r, y, p, 1 as value from RVP where v_NCAP_PASTI(r,y,p) = 0 and in_RTP_OFF(r,y,p)")
    # --- COEF_RPTI(RTP(R,PASTMILE,P))$NCAP_PASTI(R,PASTMILE,P) = 1;
    db.put("COEF_RPTI", "select r, y, p, 1 as value from RTP where in_PASTMILE(y) and in_NCAP_PASTI(r,y,p)")
    if s["ALTOBJ"]:
        # --- IF(ALTOBJ,COEF_RPTI(RTP(R,T,P))$NCAP_ILED(R,T,P) = MAX(1,CEIL((D(T)-NCAP_ILED(R,T,P))/NCAP_TLIFE(R,T,P)));
        db.put("COEF_RPTI", """select r, y, p, greatest(1, ceil((v_D(y) - v_NCAP_ILED(r,y,p)) / v_NCAP_TLIFE(r,y,p))) as value
                               from RTP where in_MILESTONYR(y) and in_NCAP_ILED(r,y,p)""")
        # ---   COEF_RPTI(RTP(R,T,P))$(((ROUND(NCAP_TLIFE(R,T,P))-IPD(T)%CTST%) > 0)$(NOT NCAP_ILED(R,T,P))) =
        #                 MAX(1,CEIL(MAX(D(T),IPD(T))/NCAP_TLIFE(R,T,P)));
        ipd = "v_IPD(y)" if db.ctl["CTST"] == "" else "1"                 # IPD(T)**0 = IPD(T)**EPS = 1
        db.put("COEF_RPTI", f"""select r, y, p, greatest(1, ceil(greatest(v_D(y), v_IPD(y)) / v_NCAP_TLIFE(r,y,p))) as value
                                from RTP where in_MILESTONYR(y) and not in_NCAP_ILED(r,y,p)
                                  and ground(v_NCAP_TLIFE(r,y,p)) - {ipd} > 0""")
        # ---   COEF_RPTI(RTP(R,T,P))$(NOT COEF_RPTI(R,T,P)) = MAX(1,MAX(D(T),IPD(T))/NCAP_TLIFE(R,T,P));
        db.put("COEF_RPTI", """select r, y, p, greatest(1, greatest(v_D(y), v_IPD(y)) / v_NCAP_TLIFE(r,y,p)) as value
                               from RTP where in_MILESTONYR(y) and not in_COEF_RPTI(r,y,p)""")
    else:
        # --- ELSE COEF_RPTI(RTP(R,T,P)) = MAX(1,CEIL((D(T)-NCAP_ILED(R,T,P))/NCAP_TLIFE(R,T,P))));
        db.put("COEF_RPTI", """select r, y, p, greatest(1, ceil((v_D(y) - v_NCAP_ILED(r,y,p)) / v_NCAP_TLIFE(r,y,p))) as value
                               from RTP where in_MILESTONYR(y)""")
    if s["ALTOBJ"] >= 2:
        unsupported(db, "linearised objective (relaxed capacity transfer thresholds, ALTOBJ >= 2)")
    # --- VNT(V,T)$(M(T) GE M(V)) = YES; YKVAL(VNT(V,T)) = B(T)-B(V);
    db.add("VNT", "select v.y, t.y as y2 from MODLYEAR v, MILESTONYR t where v_M(t.y) >= v_M(v.y)")
    # --- RTP_CPTYR(R,VNT(V,T),P)$((B(V)+NCAP_ILED(R,V,P)<(E(T)+1))$(NCAP_ILED(R,V,P)+COEF_RPTI(R,V,P)*NCAP_TLIFE(R,V,P)>YKVAL(V,T))$RTP(R,V,P)) = YES;
    db.add("RTP_CPTYR", """select k.r, k.y, n.y2, k.p from RTP k join VNT n on n.y = k.y
                           where v_B(k.y) + v_NCAP_ILED(k.r,k.y,k.p) < v_E(n.y2) + 1
                             and v_NCAP_ILED(k.r,k.y,k.p) + v_COEF_RPTI(k.r,k.y,k.p) * v_NCAP_TLIFE(k.r,k.y,k.p) > v_B(n.y2) - v_B(k.y)""")
    db.clear("COEF_RTP")
    # --- RTP_CPTYR(R,MIYR_1(T),T,P)$(RTP(R,T,P)$PRC_MAP(R,'STK',P)) = YES;
    db.add("RTP_CPTYR", "select k.r, k.y, k.y as y2, k.p from RTP k where in_MIYR_1(k.y) and in_PRC_MAP(k.r,'STK',k.p)")


# ---------------------------------------------------------------------------
def capacity_bounds_and_periods(db: DB):
    """Capacity bounds, process availability periods, RTPC, PRC_ACTFLO/PRC_CAPACT defaults."""
    # --- OPTION CLEAR=RVP;  CAP_BND(RTP,BDNEQ) $= CAP_BND(RTP,'FX');
    db.clear("RVP")
    db.put("CAP_BND", """select b.r, b.y, b.p, q.l, b.value from CAP_BND b, BDNEQ q
                         where b.l='FX' and in_RTP(b.r,b.y,b.p)""", zero="eps")
    # --- LOOP((RTP(R,T,P),L('UP'))$((CAP_BND(RTP,L)<=PRC_RESID(RTP))$CAP_BND(RTP,L)),
    #      IF(PRC_RCAP(R,P), Z=0; ELSE Z=PRC_RESID(RTP));
    #      IF(Z, F=CAP_BND(RTP,L); CAP_BND(RTP,L)$(IFQ<10)=EPS; F$(0**(IFQ+F+1$RP_FLO(R,P)))=Z;
    #       IF(F<Z, RCAP_BND(RTP,'N')=Z; <QA: Inconsistent CAP_BND(UP/FX) ... Bound converted to NCAP_BND, R.T.P=>)));
    # The EPS bound is then taken up by RVP below: no new capacity alive in that period, and the CAP_BND removed.
    # IFQ: initmty.mod IFQ /1/, and prep_ext.vda line 71 IFQ$SUM(COM_TYPE(CG(R)),1)=0 (a commodity type named as a region).
    tc = db.cols("COM_TYPE")[0]
    ifq = 0 if db.q1(f"select count(*) from COM_TYPE where in_REG({tc})") else 1
    #     ($CAP_BND(RTP,L) is true for a bound given as EPS: it is converted too, F = EPS < Z)
    conv = db.q("""select b.r, b.y, b.p, b.value, v_PRC_RESID(b.r,b.y,b.p), in_RP_FLO(b.r,b.p) from CAP_BND b
                   where b.l='UP' and in_RTP(b.r,b.y,b.p) and b.value <= v_PRC_RESID(b.r,b.y,b.p)
                     and not in_PRC_RCAP(b.r,b.p) and v_PRC_RESID(b.r,b.y,b.p) <> 0""")
    if conv:
        db.x("create or replace temp table t_capconv (r VARCHAR, y VARCHAR, p VARCHAR, z DOUBLE, rcap BOOLEAN)")
        rows = []
        for r, y, p, f, z, rpflo in conv:
            if ifq + f + (1 if rpflo else 0) == 0:            # 0**0 = 1: F = Z
                f = z
            rows.append((r, y, p, z, f < z))
            if f < z:
                db.log.append(f"*01 WARNING - Inconsistent CAP_BND(UP/FX) defined for process capacity; "
                              f"Bound converted to NCAP_BND, R.T.P= {r}.{y}.{p}")
        db.insert_rows("t_capconv", rows)
        db.put("CAP_BND", "select r, y, p, 'UP' as l, 0 as value from t_capconv", zero="eps")
        db.put("RCAP_BND", "select r, y, p, 'N' as l, z as value from t_capconv where rcap")
    # --- RVP(RTP)$((CAP_BND(RTP,'UP')=0)$CAP_BND(RTP,'UP')) = YES;
    #     LOOP(T, NCAP_BND(R,TT,P,'UP')$(RTP_CPTYR(R,TT,T,P)$RVP(R,T,P)) = EPS);
    db.tmp("t_rvp", "select r, y, p from CAP_BND where l='UP' and value = 0 and in_RTP(r,y,p)")
    db.put("NCAP_BND", """select distinct c.r, c.y, c.p, 'UP' as l, 0 as value from RTP_CPTYR c join t_rvp v
                          on v.r=c.r and v.y=c.y2 and v.p=c.p where in_MILESTONYR(c.y)""", zero="eps")
    # --- RVP(RTP_VARP)=NO; CAP_BND(RVP,BD) = 0;
    db.zap("CAP_BND", "exists(select 1 from t_rvp v where v.r=CAP_BND.r and v.y=CAP_BND.y and v.p=CAP_BND.p) and not in_RTP_VARP(r,y,p)")
    # --- CAP_BND(RTP,BDLOX)$MAPVAL(CAP_BND(RTP,BDLOX)) = 0;   (MAPVAL: EPS or infinite; a stored 0 is an EPS)
    db.zap("CAP_BND", "in_RTP(r,y,p) and in_BDLOX(l) and (value = 0 or isinf(value) or isnan(value))")
    # --- RTP_VARP(RTP(R,T,P))$(CAP_BND(RTP,'UP')*CAP_BND(RTP,'LO')) = YES;
    db.add("RTP_VARP", """select r, y, p from RTP where in_MILESTONYR(y)
                          and v_CAP_BND(r,y,p,'UP') <> 0 and v_CAP_BND(r,y,p,'LO') <> 0""")
    # --- OPTION CLEAR=RVP; PUTGRP = 0;
    #     RVP(RTP_VARP(R,T,P))$(CAP_BND(R,T,P,'LO')>CAP_BND(R,T,P,'UP')) $= CAP_BND(R,T,P,'UP');
    #     RVP(RTP)$((NCAP_BND(RTP,'LO')>NCAP_BND(RTP,'UP'))$NCAP_BND(RTP,'UP')) = YES;
    #     LOOP(RVP, <QA 1: Inconsistent CAP_BND(UP/LO) or NCAP_BND(UP/LO) ... Lower bound set equal to upper bound, R.T.P=>);
    #     (the QA log only: RVP is cleared again before it is read; bndmain.mod reconciles NCAP_BND LO above UP)
    for r, y, p in db.q("""select r, y, p from RTP_VARP where v_CAP_BND(r,y,p,'UP') <> 0
                             and v_CAP_BND(r,y,p,'LO') > v_CAP_BND(r,y,p,'UP')
                           union
                           select r, y, p from NCAP_BND n where l='UP' and in_RTP(r,y,p)
                             and v_NCAP_BND(r,y,p,'LO') > n.value
                           order by r, p, y"""):
        db.log.append(f"*01 WARNING - Inconsistent CAP_BND(UP/LO) or NCAP_BND(UP/LO) defined for process capacity; "
                      f"lower bound set equal to upper bound, R.T.P= {r}.{y}.{p}")
    # --- LOOP(BDUPX(BD),RTP_OFF(RTP)$((NCAP_BND(RTP,BD)=0)$NCAP_BND(RTP,BD)) = YES);
    db.add("RTP_OFF", "select r, y, p from NCAP_BND where in_BDUPX(l) and value = 0 and in_RTP(r,y,p)")
    # --- NO_RVP(RTP_OFF(R,T,P))$(NOT NCAP_PASTI(R,T,P)) = YES;
    db.tmp("t_norvp", "select r, y, p from RTP_OFF where in_MILESTONYR(y) and not in_NCAP_PASTI(r,y,p)")
    # --- LOOP(T, NO_RVP(R,TT,P)$(RTP_CPTYR(R,T,TT,P)$(NOT RTP_OFF(R,T,P))) = NO);
    db.x("""delete from t_norvp n where exists(select 1 from RTP_CPTYR c where c.r=n.r and c.p=n.p and c.y2=n.y
                                               and in_MILESTONYR(c.y) and not in_RTP_OFF(c.r,c.y,c.p))""")
    # --- LOOP(PYR(V), NO_RVP(R,T,P)$(RTP_CPTYR(R,V,T,P)$NCAP_PASTI(R,V,P)) = NO);
    db.x("""delete from t_norvp n where exists(select 1 from RTP_CPTYR c where c.r=n.r and c.p=n.p and c.y2=n.y
                                               and in_PASTYEAR(c.y) and in_NCAP_PASTI(c.r,c.y,c.p))""")
    # --- RTP(NO_RVP) = NO;  RTP_CPTYR(R,T,TT,P)$((NOT NCAP_PASTI(R,T,P))$RTP_OFF(R,T,P)) = NO;
    db.remove("RTP", select="select r, y, p from t_norvp")
    db.remove("RTP_CPTYR", where="in_MILESTONYR(y) and in_MILESTONYR(y2) and not in_NCAP_PASTI(r,y,p) and in_RTP_OFF(r,y,p)")
    # --- PRC_AOFF: RTP_VARA(RTP(R,T,P))$(NOT TRACKP(R,P)) = YES;  for the others all periods outside the OFF ranges
    db.add("RTP_VARA", "select r, y, p from RTP where in_MILESTONYR(y)")
    if db.card("PRC_AOFF"):
        db.remove("RTP_VARA", select="select r, y, p from (" + off_years(db, "PRC_AOFF", ["p"], "and in_RP(n.r,n.p)") + ")")
    # --- RTPC(RTP(R,T,P),C) $= RPC(R,P,C);
    db.add("RTPC", "select k.r, k.y, k.p, c.c from RTP k join RPC c on c.r=k.r and c.p=k.p where in_MILESTONYR(k.y)")
    # --- PRC_FOFF: RTPCS_OUT(RTP_VARA(R,MY_FIL(T),P),C,S) = YES for the OFF periods of (R,P,C,TS) with TS_MAP(R,TS,S)
    if db.card("PRC_FOFF"):
        db.tmp("t_foff", off_years(db, "PRC_FOFF", ["p", "c", "s"], "and in_RPC(n.r,n.p,n.c)"))
        db.add("RTPCS_OUT", """select o.r, o.y, o.p, o.c, v.s from t_foff o join RPCS_VAR v on v.r=o.r and v.p=o.p and v.c=o.c
                               where in_TS_MAP(o.r,o.s,v.s) and in_RTP_VARA(o.r,o.y,o.p)""")
        for r, p, c, ts in db.q("""select distinct n.r, n.p, n.c, n.s from PRC_FOFF n where in_RPC(n.r,n.p,n.c)
                                   and exists(select 1 from RPCS_VAR v where v.r=n.r and v.p=n.p and v.c=n.c and in_RS_BELOW(n.r,v.s,n.s))"""):
            db.log.append(f"*01 WARNING - Flow OFF TS level below VARiable TS level; OFF is ignored: R={r} P={p} C={c} S={ts}")
    # --- $IF DEFINED PRC_SIMV LOOP(T,NO_RVP(R,TT-1,P)$(RTP_CPTYR(R,TT,T,P)$PRC_SIMV(R,P))=YES); NO_RVP(RTP(R,T,P))=NO; RTP(NO_RVP)=YES;
    simv.leading(db)
    # --- RPC_PG(R,P,C)$((NOT RP_PG(R,P,C))$(ROUND(PRC_ACTFLO(R,'0',P,C)<0))) = NO;
    db.remove("RPC_PG", where="not in_RP_PG(r,p,c) and v_PRC_ACTFLO(r,'0',p,c) < 0")
    # --- RPC_PG(RPC_STG) = YES;  RP_STD(RP_FLO(RP))$(NOT RP_STG(RP)) = YES;
    #     (night storage: the commodities of the shadow group are stored commodities too, and so part of the primary group)
    db.add("RPC_PG", "select r, p, c from RPC_STG")
    db.add("RP_STD", "select r, p from RP_FLO where not in_RP_STG(r,p)")
    # --- OPTION RPC_ACT <= PRC_ACTFLO;  RPC_ACT(R,P,C)$(RPC_PG(R,P,C)+(NOT RPC(R,P,C)$RP_STD(R,P))) = NO;
    #     (the removal runs over commodities only: entries for other groups stay)
    db.assign("RPC_ACT", """select distinct r, p, cg from PRC_ACTFLO where in_REG(r)
                            and not (in_COM(cg) and (in_RPC_PG(r,p,cg) or not (in_RPC(r,p,cg) and in_RP_STD(r,p))))""")
    # --- CHP(RP(R,P)) $= PRC_MAP(R,'CHP',P);
    db.add("CHP", "select r, p from PRC_MAP where prc_grp='CHP' and in_RP(r,p)")
    # --- PRC_CAPACT(RP)$(NOT PRC_CAPACT(RP)) = 1;
    #     NOT EPS is false: a PRC_CAPACT given as 0 (EPS under $ONEPS) stays, and so do the capacity terms it multiplies
    db.put("PRC_CAPACT", "select r, p, 1 as value from RP where not in_PRC_CAPACT(r,p)")
    # --- PRC_ACTFLO(RTP(R,V,P),C)$((NOT PRC_ACTFLO(RTP,C))$RPC_PG(R,P,C)) $= SUM(RP_PG(R,P,CG),PRC_ACTFLO(R,V,P,CG));
    #     ... $= PRC_ACTFLO(RTP,%PGPRIM%);   ... = 1;
    #     NOT EPS is false and $= assigns an EPS: a PRC_ACTFLO given as 0 (EPS under $ONEPS), on the commodity or on the
    #     group, stays EPS, and TIMES then stops in EQ_ACTFLO with "division by eps"; times_eq stops
    #     there too)
    db.put("PRC_ACTFLO", """select k.r, k.y, k.p, g.c as cg,
                                   (select sum(a.value) from RP_PG q join PRC_ACTFLO a on a.r=q.r and a.p=q.p and a.cg=q.cg
                                    where q.r=k.r and q.p=k.p and a.y=k.y) as value
                            from RTP k join RPC_PG g on g.r=k.r and g.p=k.p where not in_PRC_ACTFLO(k.r,k.y,k.p,g.c)
                              and exists(select 1 from RP_PG q join PRC_ACTFLO a on a.r=q.r and a.p=q.p and a.cg=q.cg
                                         where q.r=k.r and q.p=k.p and a.y=k.y)""", zero="eps")
    db.put("PRC_ACTFLO", """select k.r, k.y, k.p, g.c as cg, v_PRC_ACTFLO(k.r,k.y,k.p,'ACT') as value
                            from RTP k join RPC_PG g on g.r=k.r and g.p=k.p where not in_PRC_ACTFLO(k.r,k.y,k.p,g.c)
                              and in_PRC_ACTFLO(k.r,k.y,k.p,'ACT')""", zero="eps")
    db.put("PRC_ACTFLO", """select k.r, k.y, k.p, g.c as cg, 1 as value
                            from RTP k join RPC_PG g on g.r=k.r and g.p=k.p where not in_PRC_ACTFLO(k.r,k.y,k.p,g.c)""")
    # --- RP_PGACT(RP_FLO(R,P))$(SUM(RPC_PG(R,P,C),1) EQ 1) = YES;
    db.add("RP_PGACT", "select f.r, f.p from RP_FLO f where (select count(*) from RPC_PG g where g.r=f.r and g.p=f.p) = 1")
    # --- RP_PGACT(RP_IRE(R,P))$(SUM(RPC_IRE(RPC_PG(R,P,C),IE),1) EQ 1) = YES;
    db.add("RP_PGACT", """select f.r, f.p from RP_IRE f where in_REG(f.r) and
                          (select count(*) from RPC_IRE i where i.r=f.r and i.p=f.p and in_RPC_PG(i.r,i.p,i.c)) = 1""")


# ---------------------------------------------------------------------------
def availability_by_timeslice(db: DB):
    """Availability factors and peak contribution by timeslice."""
    from ..lvl import lvlbr, trees, nearest, _in, _out, _write
    # --- RTPS_BD(RTP(R,V,P),S,BD)$PRC_TS(R,P,S) $= NCAP_AFS(RTP,S,BD)$(NOT NCAP_AF(RTP,S,BD));
    db.tmp("t_afs", """select r, y, p, s, l from NCAP_AFS a where in_RTP(r,y,p) and in_PRC_TS(r,p,s)
                       and not in_NCAP_AF(r,y,p,s,l)""")
    lvlbr(db, "NCAP_AF", "PRC_TS", ["p"], inherit_missing=False, fx_check=True)
    # --- NCAP_AF(RTPS_BD)$NCAP_AF(RTPS_BD) $= NCAP_AFS(RTPS_BD);
    db.put("NCAP_AF", """select k.r, k.y, k.p, k.s, k.l, v_NCAP_AFS(k.r,k.y,k.p,k.s,k.l) as value from t_afs k
                         where in_NCAP_AF(k.r,k.y,k.p,k.s,k.l)""", zero="eps")
    # --- RTPS_BD(R,LL--(ORD(LL)*(NCAP_AF(..) GT 0)),P,S,BDUPX(BD))$(V(LL)$NCAP_AF(R,LL,P,S,BD))=YES;
    #     OPTION TRACKP < RTPS_BD; RXX(PRC_TS(TRACKP(R,P),S))$=SUM(RTPS_BD(R,LASTLL,P,S,BDUPX),1);
    db.tmp("t_trackp", "select distinct r, p from NCAP_AF where in_MODLYEAR(y) and in_BDUPX(l)")
    db.tmp("t_pos", "select distinct r, p, s from NCAP_AF where in_MODLYEAR(y) and in_BDUPX(l) and value > 0 and in_PRC_TS(r,p,s)")
    # --- NCAP_AF(RTP(R,V,P),S,'UP')$(PRC_TS(R,P,S)$(NOT TRACKP(R,P))) = 1.0;
    db.put("NCAP_AF", """select k.r, k.y, k.p, t.s, 'UP' as l, 1 as value from RTP k join PRC_TS t on t.r=k.r and t.p=k.p
                         where not exists(select 1 from t_trackp x where x.r=k.r and x.p=k.p)""")
    # --- PRC_TS2(PRC_TS(TRACKP(R,P),S)) = (NOT RXX(R,P,S));
    db.tmp("t_ts2", """select t.r, t.p, t.s from PRC_TS t join t_trackp x on x.r=t.r and x.p=t.p
                       where not exists(select 1 from t_pos q where q.r=t.r and q.p=t.p and q.s=t.s)""")
    # --- NCAP_AF(RTP(R,V,P),S,'UP')$(PRC_TS2(R,P,S)$RP_STG(R,P)) = EPS;  PRC_TS2(RP_STG,S) = NO;
    #     (a storage keeps the timeslices it has no availability for, with an availability of EPS)
    db.put("NCAP_AF", """select k.r, k.y, k.p, z.s, 'UP' as l, 0 as value from RTP k join t_ts2 z on z.r=k.r and z.p=k.p
                         where in_RP_STG(k.r,k.p)""", zero="eps")
    db.x("delete from t_ts2 where in_RP_STG(r,p)")
    # --- PRC_TS2(RP(R,P),S) $= SUM(RS_BELOW(R,TS,S)$PRC_TS2(RP,TS),1);
    db.x("""insert into t_ts2 select distinct k.r, k.p, b.s2 from t_ts2 k join RS_BELOW b on b.r=k.r and b.s=k.s
            where in_RP(k.r,k.p) and not exists(select 1 from t_ts2 z where z.r=k.r and z.p=k.p and z.s=b.s2)""")
    # --- PRC_TS(PRC_TS2) = NO; RPCS_VAR(RPCS_VAR(R,P,C,S))$PRC_TS2(R,P,S) = NO; RTPCS_OUT(RTPC(R,T,P,C),S)$PRC_TS2(R,P,S) = YES;
    if db.q1("select count(*) from t_ts2"):
        db.remove("PRC_TS", select="select r, p, s from t_ts2")
        db.remove("RPCS_VAR", where="exists(select 1 from t_ts2 z where z.r=RPCS_VAR.r and z.p=RPCS_VAR.p and z.s=RPCS_VAR.s)")
        db.add("RTPCS_OUT", "select k.r, k.y, k.p, k.c, z.s from RTPC k join t_ts2 z on z.r=k.r and z.p=k.p")

    # ---- pp_lvlpk.mod 1.0
    # --- LOOP(COM_PKTS(R,CG,S), RCS(COM_TS(R,C,TS))$(RS_TREE(R,S,TS)$COM_GMAP(R,CG,C)) = YES);  TRACKC(R,C) $= SUM(RCS(R,C,S),1);
    db.assign("RCS", """select distinct t.r, t.c, t.s from COM_PKTS k join COM_GMAP m on m.r=k.r and m.cg=k.cg
                        join COM_TS t on t.r=k.r and t.c=m.c where in_RS_TREE(k.r,k.s,t.s)""")
    db.tmp("t_trackc", "select distinct r, c from RCS")
    # --- FLO_PKCOI(RTP(R,T,P),C,S)$(TRACKC(R,C)$PRC_PKNO(R,P)) = 0;
    db.zap("FLO_PKCOI", "in_MILESTONYR(y) and in_RTP(r,y,p) and in_PRC_PKNO(r,p) and exists(select 1 from t_trackc k where k.r=FLO_PKCOI.r and k.c=FLO_PKCOI.c)")
    # --- TRACKPC(RPC(R,P,C))$((TOP(RPC,'OUT')+RPC_IRE(RPC,'IMP'))$TRACKC(R,C)) = YES;
    db.tmp("t_trackpc", """select k.r, k.p, k.c from RPC k join t_trackc c on c.r=k.r and c.c=k.c
                           where in_TOP(k.r,k.p,k.c,'OUT') or in_RPC_IRE(k.r,k.p,k.c,'IMP')""")
    # --- RTP_GRP(RTP_ISHPR(RTP(R,V,P)),C,IO(IPS))$(SUM(RCS(R,C,S)$(NOT NCAP_PKCNT(R,V,P,S)),1)$TRACKPC(R,P,C)) = YES;
    #     LOOP(RTP_GRP(R,V,P,C,IO), ... levelling of NCAP_PKCNT onto the RCS timeslices, default %1 on ANNUAL)
    T = trees(db)
    rcs = {}
    for r, c, s in db.q("select r, c, s from RCS"):
        rcs.setdefault((r, c), []).append(s)
    pk = {}
    for r, y, p, s, v in db.q("select r, y, p, s, value from NCAP_PKCNT where in_RTP(r,y,p)"):
        pk.setdefault((r, y, p), {})[s] = _in(v)
    # the series of each (r, p), in the order of pk: a lookup instead of a scan of every series per (r, p, c)
    pk_rp = {}
    for (r_, y, p_), arr in pk.items():
        pk_rp.setdefault((r_, p_), []).append((y, arr))
    out = []
    for r, p, c in db.q("select r, p, c from t_trackpc"):
        for y, arr in pk_rp.get((r, p), ()):
            if all(s in arr for s in rcs[(r, c)]):
                continue
            tr = T[r]
            f = arr.get("ANNUAL")
            if f is not None and not any(s != "ANNUAL" for s in arr):
                for s in rcs[(r, c)]:
                    arr[s] = f; out.append((r, y, p, s, _out(f)))
            else:
                a2 = dict(arr)
                a2.setdefault("ANNUAL", 1.0)
                for ts in rcs[(r, c)]:
                    if ts in a2:
                        continue
                    tot = sum(tr.g[s] / tr.g[ts] * nearest(tr, a2, s)[0] for s in tr.leaves[ts])
                    arr[ts] = tot; out.append((r, y, p, ts, _out(tot)))
    _write(db, "NCAP_PKCNT", ["r", "y", "p"], out)
    # --- TRACKP(PRC_PKAF(RP))=NOT PRC_PKNO(RP); TRACKPC(PRC_PKNO(RP),C) = NO;
    db.tmp("t_trackp", "select r, p from PRC_PKAF where in_RP(r,p) and not in_PRC_PKNO(r,p)")
    db.x("delete from t_trackpc where in_PRC_PKNO(r,p)")
    # --- RPC_PKF(RPC(RP_FLO(R,P),C))$TRACKC(R,C) = EPS**1$TRACKP(R,P);
    db.put("RPC_PKF", """select k.r, k.p, k.c, case when exists(select 1 from t_trackp x where x.r=k.r and x.p=k.p) then 0 else 1 end as value
                         from RPC k join t_trackc c on c.r=k.r and c.c=k.c where in_RP_FLO(k.r,k.p)""", zero="eps")
    # --- LOOP(TRACKPC(R,P,C),PRC_TS2(R,P,S)$((NOT SUM(RTP(R,V,P),NCAP_PKCNT(RTP,S)))$RCS(R,C,S)) = YES);
    db.tmp("t_ts2", """select distinct k.r, k.p, x.s from t_trackpc k join RCS x on x.r=k.r and x.c=k.c
                       where not exists(select 1 from NCAP_PKCNT n where n.r=k.r and n.p=k.p and n.s=x.s and in_RTP(n.r,n.y,n.p))""")
    #     (a sum of EPS is EPS, and NOT EPS is false: a contribution given as an explicit zero is "provided", and gets no default)
    # --- NCAP_PKCNT(R,YEAR,P,S)$(NCAP_PKCNT(R,YEAR,P,S)=0) = 0;
    db.zap("NCAP_PKCNT", "value = 0")
    # --- NCAP_PKCNT(RTP(R,V,P),S)$PRC_TS2(R,P,S) = 1$(NOT PRC_PKAF(R,P)) +
    #       SUM(PRC_TS(R,P,TS)$RS_TREE(R,S,TS),SMAX(BD,NCAP_AF(RTP,TS,BD))*(1+(G_YRFR(R,TS)/G_YRFR(R,S)-1)$RS_BELOW(R,S,TS)))$PRC_PKAF(R,P);
    db.put("NCAP_PKCNT", """
        select k.r, k.y, k.p, z.s,
               case when not in_PRC_PKAF(k.r,k.p) then 1 else
                 coalesce((select sum(greatest(0, (select max(a.value) from NCAP_AF a where a.r=k.r and a.y=k.y and a.p=k.p and a.s=t.s))
                                      * (case when in_RS_BELOW(k.r,z.s,t.s) then v_G_YRFR(k.r,t.s)/v_G_YRFR(k.r,z.s) else 1 end))
                           from PRC_TS t where t.r=k.r and t.p=k.p and in_RS_TREE(k.r,z.s,t.s)), 0) end as value
        from RTP k join t_ts2 z on z.r=k.r and z.p=k.p""")
    # --- RPC_PKC(TRACKPC(RPC_ACT(TRACKP(RP_STD),C)))=YES;
    db.add("RPC_PKC", """select k.r, k.p, k.c from t_trackpc k where in_RPC_ACT(k.r,k.p,k.c) and in_RP_STD(k.r,k.p)
                         and exists(select 1 from t_trackp x where x.r=k.r and x.p=k.p)""")
    # --- TRACKPC(RP,C)$(NOT RPC_PG(RP,C)*RP_FLO(RP))=NO;
    db.x("delete from t_trackpc where not (in_RPC_PG(r,p,c) and in_RP_FLO(r,p))")
    # --- RPC_PKC(TRACKPC(RP_PGACT(RP),C))$(RP_PG(RP,C)+TRACKP(RP))=YES;
    db.add("RPC_PKC", """select k.r, k.p, k.c from t_trackpc k where in_RP_PGACT(k.r,k.p)
                         and (in_RP_PG(k.r,k.p,k.c) or exists(select 1 from t_trackp x where x.r=k.r and x.p=k.p))""")
    # --- LOOP(NRG_TMAP(R,'ELC',C)$TRACKC(R,C),RPC_PKC(TRACKPC(TRACKP(R,P),C))=YES;TRACKP(R,P)$TRACKPC(R,P,C)=NO);
    for r, c in db.q("""select n.r, n.c from NRG_TMAP n join t_trackc k on k.r=n.r and k.c=n.c join __uel u on u.label=n.c
                        where n.nrg_type='ELC' order by n.r, u.ord"""):
        db.add("RPC_PKC", f"""select k.r, k.p, k.c from t_trackpc k join t_trackp x on x.r=k.r and x.p=k.p
                              where k.r='{r}' and k.c='{c}'""")
        db.x(f"delete from t_trackp x where x.r='{r}' and exists(select 1 from t_trackpc k where k.r=x.r and k.p=x.p and k.c='{c}')")
    db.clear("RCS")


INF = float("inf")


def retirement_controls(db: DB):
    # Python's cyclic garbage collector paused for the step, as for the objective: the step builds
    # hundreds of thousands of small tuples that live to its end, and each full collection walks all of them again
    import gc
    on = gc.isenabled()
    gc.disable()
    try:
        _retirement_controls(db)
    finally:
        if on:
            gc.enable()


def _retirement_controls(db: DB):
    if not db.s.get("VNRET"):                       # $IF DECLARED VNRET
        return
    q, x = db.q, db.x
    # RCAP_BLK (retirement in blocks): a model that gives it is a MIP (init_ext.dsc: $IF DEFINED RCAP_BLK $SETGLOBAL
    # SOLMIP YES, under DSCAUTO, which a run with PGPRIM ACT has); MAPVAL(RCAP_BLK) is non-zero for a special value
    # only (EPS, INF): such a block shapes PASTSUM and VAR_RCAP.LO below
    blk = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from RCAP_BLK where in_RTP(r,y,p)")}
    special = {k for k, v in blk.items() if v == 0 or math.isinf(v)}
    # --- PRC_RCAP(PRC_RCAP(RP)) = PRC_CAP(RP);
    db.remove("PRC_RCAP", where="in_RP(r,p) and not in_PRC_CAP(r,p)")
    # --- LOOP(PRC_RCAP(R,PRC), F=0; MY_F=0; CNT=EPS;
    #       LOOP(P$PRC_REFIT(R,PRC,P),Z=PRC_REFIT(R,PRC,P); CNT$CNT=CNT+1;
    #         IF(ABS(Z)>2, F=F+1); IF(MOD(Z,2)=0,MY_F$(ABS(Z)-4)=3);
    #         IF(Z<0,RTP_TT(R,T,TT,PRC)$COEF_CPT(R,T,TT,P)=YES; ELSE RTP_TT(R,T,T,PRC)$RTP(R,T,P)=YES; CNT=0;));
    #       IF(CNT,Z=(-1+2$(F=CNT))*MAX(1,MY_F); ELSE Z=-2);
    #       IF(NOT MAPVAL(CNT),RP_RTF(R,PRC) = Z);
    #       IF(F,RCAP_BND(RTP(R,T,PRC),'UP')$(NOT SUM(P$PRC_REFIT(R,PRC,P),RTP(R,T,P)$(ABS(PRC_REFIT(R,PRC,P))>2)))=EPS));
    refit = {}
    for r, p, p2, v in q("select r, p, p2, value from PRC_REFIT where in_PRC_RCAP(r,p) and in_REG(r) order by r, p"):
        refit.setdefault((r, p), []).append((p2, v))
    mile = [y for (y,) in q("select y from MILESTONYR order by yv(y)")]
    # (RTP and COEF_CPT are looked up below for the hosts and refit options of PRC_REFIT only: only their rows are read)
    rtp = set(q("""select k.r, k.y, k.p from RTP k
                   semi join (select r, p from PRC_REFIT union select r, p2 from PRC_REFIT) f on f.r=k.r and f.p=k.p"""))
    cpt = {}
    for r, v, t, p in q("""select c.r, c.y, c.y2, c.p from COEF_CPT c
                           semi join (select distinct r, p2 from PRC_REFIT where value < 0) f on f.r=c.r and f.p2=c.p
                           where in_MILESTONYR(c.y) and in_MILESTONYR(c.y2)"""):
        cpt.setdefault((r, p), []).append((v, t))
    rtf, rtt, eps_up = [], set(), []
    for (r, prc), lst in refit.items():
        F, MY_F, CNT = 0, 0.0, None            # CNT = EPS: counts while it stays "on"; None stands for EPS
        cnt_on = True
        n = 0
        for p2, z in lst:
            if cnt_on:
                n += 1
            if abs(z) > 2:
                F += 1
            if z % 2 == 0 and abs(z) != 4:
                MY_F = 3.0
            if z < 0:
                rtt.update((r, t, tt, prc) for (t, tt) in cpt.get((r, p2), ()))
            else:
                rtt.update((r, t, t, prc) for t in mile if (r, t, p2) in rtp)
                cnt_on, n = False, 0
        z = (-1 + (2 if F == n else 0)) * max(1.0, MY_F) if cnt_on else -2.0
        rtf.append((r, prc, z))
        if F:
            eps_up += [(r, t, prc) for t in mile if (r, t, prc) in rtp
                       and not any((r, t, p2) in rtp and abs(zz) > 2 for p2, zz in lst)]
    db.declare("RP_RTF", "par", ["R", "P"])                 # PARAMETER RP_RTF(R,P)   (declared in prepret.dsc)
    db.clear("RP_RTF", "RTP_TT")
    db.load_rows("RP_RTF", rtf)
    db.load_rows("RTP_TT", sorted(rtt))
    if eps_up:
        db.tmp("t_eps", "select * from (values " + ", ".join(f"('{r}','{t}','{p}')" for r, t, p in eps_up) + ") t(r,y,p)")
        db.put("RCAP_BND", "select r, y, p, 'UP' as l, 0 as value from t_eps", zero="eps")
    # --- VNTRT(VNT(V,T))$(NOT SAMEAS(V,T)) = YES;
    db.assign("VNTRT", "select y, y2 from VNT where y <> y2")
    # --- RVPRL(RTP(R,V,P))$PRC_RCAP(R,P)=MAX(0,SMAX(VNRET(V,T,P),YEARVAL(T))-YEARVAL(V));        VNRET(V,T,P) = RTP_CPTYR(R,VNTRT(V,T),P)
    db.put("RVPRL", """select k.r, k.y, k.p, greatest(0, max(yv(c.y2)) - yv(k.y)) as value
                       from RTP k join RTP_CPTYR c on c.r=k.r and c.y=k.y and c.p=k.p and c.y2 <> c.y and in_VNT(c.y,c.y2)
                       where in_MODLYEAR(k.y) and in_PRC_RCAP(k.r,k.p) group by k.r, k.y, k.p""")
    # --- RVP(RTP) $= RVPRL(RTP);  NCAP_ILED(RVP) = NCAP_ILED(RVP)+EPS;                           forces objective cases 2a / 2b
    db.tmp("t_rvp", "select r, y, p from RVPRL where in_RTP(r,y,p)")
    db.put("NCAP_ILED", "select r, y, p, 0 as value from t_rvp where not in_NCAP_ILED(r,y,p)", zero="eps")
    # --- OPTION TRACKP < RCAP_OCAP;  RP_RTF(TRACKP)$(NOT RP_RTF(TRACKP)) = EPS;
    db.put("RP_RTF", "select distinct r, p, 0 as value from RCAP_OCAP where not in_RP_RTF(r,p)", zero="eps")
    # --- VN2T(VNTRT(LL,T(YEAR))) = ORD(YEAR)-ORD(LL);
    db.clear("VN2T")
    db.put("VN2T", "select y, y2, yv(y2) - yv(y) as value from VNTRT where in_MILESTONYR(y2)")
    # --- RCAP_BND(R,T,P,BDNEQ) $= RCAP_BND(R,T,P,'FX');
    db.put("RCAP_BND", """select b.r, b.y, b.p, n.l, b.value from RCAP_BND b, (values ('LO'),('UP')) n(l)
                          where b.l='FX' and in_REG(b.r) and in_MILESTONYR(b.y)""", zero="eps")
    # (the kernel has neither MAPVAL(RCAP_BLK) nor VAR_DRCAP: a model with RCAP_BLK takes the Python whatever the switch)
    if kernels.mode("retirement") == "off" or blk:
        _retirement_bounds(db, refit, mile, rtp, rtf, rtt, blk, special)
    else:
        for var in ("VAR_RCAP", "VAR_SCAP"):       # (the tables the call writes, there for check mode)
            x(f'create or replace table "B_{var}" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, lower DOUBLE, upper DOUBLE)')
        kernels.run("retirement", db, ["B_VAR_RCAP", "B_VAR_SCAP", "RVPRL"],
                    lambda: _retirement_bounds(db, refit, mile, rtp, rtf, rtt, blk, special),
                    lambda: _retirement_bounds_kernel(db, refit, mile, rtp, rtf, rtt))
    # ---- prepret.dsc after the equations at label EQOBJ
    # --- RVPRL(R,PYR_S,P)$PRC_RESID(R,'0',P)=NO;
    #     (with STAGES the solve sees them again: stochastic.rvprl_at_solve)
    stochastic.keep_rvprl(db, "in_PYR_S(y) and in_REG(r) and in_PRC_RESID(r,'0',p)")
    db.zap("RVPRL", "in_PYR_S(y) and in_REG(r) and in_PRC_RESID(r,'0',p)")
    # --- NCAP_OLIFE(R,T,P)$(NOT PRC_VINT(R,P))=NO;
    db.zap("NCAP_OLIFE", "in_MILESTONYR(y) and not in_PRC_VINT(r,p)")
    # --- RCAP_OCAP(RTP,C)$(NOT RVPRL(RTP)) = 0;
    db.zap("RCAP_OCAP", "in_RTP(r,y,p) and not in_RVPRL(r,y,p)")


def _retirement_bounds(db: DB, refit, mile, rtp, rtf, rtt, blk, special):
    """The bounds of VAR_RCAP and VAR_SCAP (prepret.dsc), as B_VAR_RCAP and B_VAR_SCAP, and those of VAR_DRCAP where
    RCAP_BLK is given (blk; special: its EPS/INF blocks). The Julia kernel `retirement` (jlkernels/src/retirement.jl;
    TIMESPP_KERNELS names it) computes the first two for a model without RCAP_BLK; this is its reference."""
    q, x = db.q, db.x
    # --- PASTSUM(RVP(R,V,P))$RCAP_BND(RVP,'N') = -(B(V)+NCAP_ILED(RVP)+ABS(RCAP_BND(RVP,'N')));
    #     PASTSUM(RVP)$((RCAP_BND(RVP,'N')<0)+MAPVAL(RCAP_BLK(RVP))) = MAX(1,ABS(PASTSUM(RVP)));
    pastsum = {}
    for r, v, p, n, b, il in q("""select k.r, k.y, k.p, v_RCAP_BND(k.r,k.y,k.p,'N'), v_B(k.y), v_NCAP_ILED(k.r,k.y,k.p)
                                  from t_rvp k where in_RCAP_BND(k.r,k.y,k.p,'N')"""):
        val = -(b + il + abs(n))
        if n < 0:
            val = max(1.0, abs(val))
        pastsum[(r, v, p)] = val
    rvp = set(q("select r, y, p from t_rvp"))
    for k in sorted(special & rvp):                 # ... +MAPVAL(RCAP_BLK(RVP))) = MAX(1,ABS(PASTSUM(RVP)))
        pastsum[k] = max(1.0, abs(pastsum.get(k, 0.0)))
    vnret = {}                                      # (r,v,p) -> [t..] in period order
    # (only the rows that can give a bound below are read: RVP(R,V,P), or RCAP_BND(R,T,P,'UP') for VAR_RCAP.UP)
    for r, v, t, p in q("""select c.r, c.y, c.y2, c.p from RTP_CPTYR c where c.y <> c.y2 and in_VNT(c.y,c.y2)
                             and (exists(select 1 from t_rvp k where k.r=c.r and k.y=c.y and k.p=c.p)
                                  or in_RCAP_BND(c.r,c.y2,c.p,'UP'))
                           order by c.r, c.p, c.y, yv(c.y2)"""):
        vnret.setdefault((r, v, p), []).append(t)
    forc = {(r, v, t, p): val for r, v, t, p, val in q("select r, y, y2, p, value from RTFORC")}
    bnd = {(r, t, p, l): val for r, t, p, l, val in q("select r, y, p, l, value from RCAP_BND where l in ('LO','UP')")}
    pastmile = {y for (y,) in q("select y from PASTMILE")}
    pasti = {(r, v, p): val for r, v, p, val in q("select r, y, p, value from NCAP_PASTI")}
    prev = {t: (mile[i - 1] if i else None) for i, t in enumerate(mile)}
    rlo, rup, slo, sup = {}, {}, {}, {}
    # --- LOOP(TT(T--1),Z=ORD(T)-1;
    #       VAR_RCAP.LO(VNRET(V,T,P))$RVP(R,V,P) = RCAP_BND(R,T,P,'LO')$(NOT MAPVAL(RCAP_BLK(R,V,P)))+MIN(0,RTFORC(R,V,T,P)-RTFORC(R,V,TT,P)$Z);
    #       VAR_RCAP.UP(VNRET(V,T,P))$RCAP_BND(R,T,P,'UP') =
    #         MIN(SMIN(PASTMILE(V),NCAP_PASTI(R,V,P)),RCAP_BND(R,T,P,'UP')+MAX(0,RTFORC(R,V,T,P)-RTFORC(R,V,TT,P)$Z)));
    for (r, v, p), ts in vnret.items():
        for t in ts:
            if t not in prev:
                continue
            d = forc.get((r, v, t, p), 0.0) - (forc.get((r, v, prev[t], p), 0.0) if prev[t] else 0.0)
            if (r, v, p) in rvp:
                rlo[(r, v, t, p)] = (0.0 if (r, v, p) in special else bnd.get((r, t, p, "LO"), 0.0)) + min(0.0, d)
            if (r, t, p, "UP") in bnd:
                rup[(r, v, t, p)] = min(pasti.get((r, v, p), 0.0) if v in pastmile else INF, bnd[(r, t, p, "UP")] + max(0.0, d))
    # --- VAR_SCAP.LO(VNRET(V,T,P))$RVP(R,V,P) = MAX(RCAP_BND(R,T,P,'LO'),RTFORC(R,V,T,P));
    # --- VAR_SCAP.UP(RTP_CPTYR(R,PASTMILE(V),T,P))$RVP(R,V,P) = MAX(RTFORC(R,V,T,P),NCAP_PASTI(R,V,P));
    for (r, v, p) in rvp:
        for t in vnret.get((r, v, p), ()):
            slo[(r, v, t, p)] = max(bnd.get((r, t, p, "LO"), 0.0), forc.get((r, v, t, p), 0.0))
    for r, v, t, p in q("select c.r, c.y, c.y2, c.p from RTP_CPTYR c where in_PASTMILE(c.y) and in_MILESTONYR(c.y2)"):
        if (r, v, p) in rvp:
            sup[(r, v, t, p)] = max(forc.get((r, v, t, p), 0.0), pasti.get((r, v, p), 0.0))
    # --- LOOP(RVP(R,V,P),Z=1;LOOP(VNRET(V,T,P)$Z,Z=0; VAR_SCAP.UP(R,V,T,P)=MIN(VAR_RCAP.UP(R,V,T,P),VAR_SCAP.UP(R,V,T,P))));
    for k in rvp:
        ts = vnret.get(k, ())
        if ts:
            kk = (k[0], k[1], ts[0], k[2])
            sup[kk] = min(rup.get(kk, INF), sup.get(kk, INF))
    # --- VAR_SCAP.FX(RTP_CPTYR(R,V,T,P))$(((M(T) < ABS(PASTSUM(R,V,P)))+((M(T)-LEAD(T))/PASTSUM(R,V,P) >= 1))$PASTSUM(R,V,P)) = RTFORC(R,V,T,P);
    if pastsum:
        M = {y: v for y, v in q("select y, value from M")}
        LEAD = {y: v for y, v in q("select y, value from LEAD")}
        # (the rows of PASTSUM's keys only: RVP with RCAP_BND(RVP,'N') or a special RCAP_BLK)
        for r, v, t, p in q("""select c.r, c.y, c.y2, c.p from RTP_CPTYR c where in_MILESTONYR(c.y2)
                                 and exists(select 1 from t_rvp k where k.r=c.r and k.y=c.y and k.p=c.p)"""):
            if (r, v, p) not in pastsum:
                continue
            ps = pastsum.get((r, v, p))
            if ps and (M[t] < abs(ps) or (M[t] - LEAD[t]) / ps >= 1):
                slo[(r, v, t, p)] = sup[(r, v, t, p)] = forc.get((r, v, t, p), 0.0)
    # --- PRC_YMAX(PRC_RCAP(RP)) = MIN(0,SUM(P$PRC_REFIT(RP,P),MAX(EPS,3-ABS(PRC_REFIT(RP,P)))));  RVPRL(R,'0',P) $= PRC_YMAX(R,P);
    #     VAR_RCAP.UP(RTP_TT(R,T(TT++1),T,P))$((RP_RTF(R,P)<3)$PRC_YMAX(R,P)) = ...                     forced refits: all refit codes >= 3
    #     (MAX(EPS,3-ABS(z)) is EPS for |z| >= 3: PRC_YMAX is EPS, true, only when every code of the host is; RP_RTF < 3:
    #      the bound is 0 but for an even RP_RTF; T(TT++1): t follows tt, circularly, and VNT(TT,T) leaves out the first t)
    rtfv = {(r, p): z for r, p, z in rtf}
    forced = [rp for rp, lst in refit.items() if all(abs(z) >= 3 for _p, z in lst)]
    if forced:
        db.put("RVPRL", "select * from (values " + ", ".join(f"('{r}','0','{p}',0.0)" for r, p in forced) + ") t(r,y,p,value)",
               zero="eps")
        pyr_s = {y for (y,) in q("select y from PYR_S")}
        for (r, p) in forced:
            z = rtfv.get((r, p), 0.0)
            if not z < 3:
                continue
            for i, t in enumerate(mile):
                if (r, t, t, p) not in rtt:
                    continue
                tt = mile[i - 1]
                val = 0.0
                if i > 0 and z % 2 == 0:
                    val = max(0.0, sum(forc.get((r, v, t, p), 0.0) - forc.get((r, v, tt, p), 0.0)
                                       for v in pyr_s if (r, v, p) in rtp))
                rup[(r, t, t, p)] = val
    for var, lo, up in (("VAR_RCAP", rlo, rup), ("VAR_SCAP", slo, sup)):
        x(f'create or replace table "B_{var}" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, lower DOUBLE, upper DOUBLE)')
        keys = sorted(k for k in set(lo) | set(up) if lo.get(k, 0.0) != 0.0 or up.get(k, INF) != INF)   # (filtered, then sorted)
        rows = [k + (lo.get(k, 0.0), up.get(k, INF)) for k in keys]
        if rows:
            db.insert_rows(f'"B_{var}"', rows)
        db.bounds.add(var)
    # (prepret.dsc at label EQOBJ, after the bounds above; moved here from after RVPRL's zap there, which it does not read)
    # --- (EQOBJ) IF(CARD(RCAP_BLK), RCAP_BLK(RTP)$(RCAP_BLK(RTP) LE 0) = 0;
    #       COEF_CAP(RTP_CPTYR(R,V,T,P))$RCAP_BLK(R,V,P) = (NCAP_PASTI(R,V,P)-RTFORC(R,V,T,P))/RCAP_BLK(R,V,P);
    #       VAR_DRCAP.UP(RTP_CPTYR(R,V,T,P),'1')$PRC_RCAP(R,P) = 1$(ABS(COEF_CAP(R,V,T,P)-MIN(10,ROUND(COEF_CAP(R,V,T,P)))) >1E-9);
    #       VAR_DRCAP.UP(RTP_CPTYR(R,V,T,P),'2')$RCAP_BLK(R,V,P) = MIN(10,FLOOR(VAR_SCAP.UP(R,V,T,P)/RCAP_BLK(R,V,P)+1E-8)));
    #     (VAR_DRCAP is an INTEGER VARIABLE in the MIP: lower bound 0)
    if blk:
        db.zap("RCAP_BLK", "in_RTP(r,y,p) and value <= 0")
        blk = {k: v for k, v in blk.items() if v > 0}
        rcap_p = set(q("select r, p from PRC_RCAP"))
        cptyr = q("select r, y, y2, p from RTP_CPTYR where in_MILESTONYR(y2)")
        coef = {(r, v, t, p): (pasti.get((r, v, p), 0.0) - forc.get((r, v, t, p), 0.0)) / blk[(r, v, p)]
                for r, v, t, p in cptyr if (r, v, p) in blk}
        # (COEF_CAP is a work parameter of the equation section here, not a table of the model: kept local)
        x(f'create or replace table "B_VAR_DRCAP" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, d4 VARCHAR, lower DOUBLE, upper DOUBLE)')
        rows = []
        for r, v, t, p in cptyr:
            if (r, p) in rcap_p:
                c = coef.get((r, v, t, p), 0.0)
                rows.append((r, v, t, p, "1", 0.0, 1.0 if abs(c - min(10, rnd(c))) > 1e-9 else 0.0))
            if (r, v, p) in blk:
                u = sup.get((r, v, t, p), INF)              # (VAR_SCAP.UP: INF where no bound was set)
                rows.append((r, v, t, p, "2", 0.0, 10.0 if math.isinf(u) else float(min(10, math.floor(u / blk[(r, v, p)] + 1e-8)))))
        if rows:
            db.insert_rows('"B_VAR_DRCAP"', sorted(rows))
        db.bounds.add("VAR_DRCAP")


def _retirement_bounds_kernel(db: DB, refit, mile, rtp, rtf, rtt):
    """_retirement_bounds in Julia: the same B_VAR_RCAP, B_VAR_SCAP (and RVPRL of the forced refits), to the bit."""
    import sys
    import numpy as np
    K = "retirement"
    q = db.q
    cols = [np.array([sys.version_info >= (3, 12)], np.float64)]
    L, V = "L", "V"
    rvp4 = [("r", L), ("y", L), ("y2", L), ("p", L)]

    def add(src, spec, where=None):
        cols.extend(kernels.rows_to_julia(db, K, src, spec, where))
    add("""select k.r, k.y, k.p, v_RCAP_BND(k.r,k.y,k.p,'N') as n, v_B(k.y) as b, v_NCAP_ILED(k.r,k.y,k.p) as il
           from t_rvp k where in_RCAP_BND(k.r,k.y,k.p,'N')""", [("r", L), ("y", L), ("p", L), ("n", V), ("b", V), ("il", V)])
    add("t_rvp", [("r", L), ("y", L), ("p", L)])
    add("""select c.r, c.y, c.y2, c.p from RTP_CPTYR c where c.y <> c.y2 and in_VNT(c.y,c.y2)
             and (exists(select 1 from t_rvp k where k.r=c.r and k.y=c.y and k.p=c.p) or in_RCAP_BND(c.r,c.y2,c.p,'UP'))
           order by c.r, c.p, c.y, yv(c.y2)""", rvp4)
    add("RTFORC", rvp4 + [("value", V)])
    add("select r, y, p, case when l = 'LO' then 0 else 1 end as l, value from RCAP_BND where l in ('LO','UP')",
        [("r", L), ("y", L), ("p", L), ("l", "Y"), ("value", V)])
    cols.extend(kernels.frame_to_julia(db, K, [(t,) for t in mile], [("y", L)]))
    add("PASTMILE", [("y", L)])
    add("NCAP_PASTI", [("r", L), ("y", L), ("p", L), ("value", V)])
    add("select c.r, c.y, c.y2, c.p from RTP_CPTYR c where in_PASTMILE(c.y) and in_MILESTONYR(c.y2)", rvp4)
    add("M", [("y", L), ("value", V)])
    add("LEAD", [("y", L), ("value", V)])
    add("""select c.r, c.y, c.y2, c.p from RTP_CPTYR c where in_MILESTONYR(c.y2) and in_RCAP_BND(c.r,c.y,c.p,'N')
             and exists(select 1 from t_rvp k where k.r=c.r and k.y=c.y and k.p=c.p)""", rvp4)
    # --- PRC_YMAX(PRC_RCAP(RP)) = MIN(0,SUM(P$PRC_REFIT(RP,P),MAX(EPS,3-ABS(PRC_REFIT(RP,P)))));  RVPRL(R,'0',P) $= PRC_YMAX(R,P);
    #     (the forced refits, all refit codes >= 3: their RP_RTF and RTP_TT for the kernel, RVPRL below)
    rtfv = {(r, p): z for r, p, z in rtf}
    forced = [rp for rp, lst in refit.items() if all(abs(z) >= 3 for _p, z in lst)]
    cols.extend(kernels.frame_to_julia(db, K, [(r, p, rtfv.get((r, p), 0.0)) for r, p in forced], [("r", L), ("p", L), ("z", V)]))
    fset = set(forced)
    cols.extend(kernels.frame_to_julia(db, K, [k for k in rtt if (k[0], k[3]) in fset], rvp4))
    add("PYR_S" if forced else "select y from PYR_S where false", [("y", L)])
    cols.extend(kernels.frame_to_julia(db, K, sorted(rtp) if forced else [], [("r", L), ("y", L), ("p", L)]))
    out = kernels.call(K, cols)
    t = time.perf_counter()
    if forced:
        db.put("RVPRL", "select * from (values " + ", ".join(f"('{r}','0','{p}',0.0)" for r, p in forced) + ") t(r,y,p,value)",
               zero="eps")
    nrows = 0
    for i, var in enumerate(("VAR_RCAP", "VAR_SCAP")):
        db.x(f'create or replace table "B_{var}" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, d3 VARCHAR, lower DOUBLE, upper DOUBLE)')
        o = out[6 * i:6 * i + 6]
        if len(o[0]):
            rel = kernels.from_julia(db, "u_", ["d0", "d1", "d2", "d3"], o[:4], {"lower": o[4], "upper": o[5]})
            db.x(f'insert into "B_{var}" select d0, d1, d2, d3, lower, upper from {rel} u_')
            db.con.unregister("u_")
            nrows += len(o[0])
        db.bounds.add(var)
    kernels.tally(K, "julia -> duckdb", time.perf_counter() - t, nrows)
