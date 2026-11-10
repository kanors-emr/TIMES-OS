# SPDX-License-Identifier: GPL-3.0-or-later
"""pp_chp.mod: the flow controls of CHP processes."""
from ..controls import unsupported
from ..engine import DB
from .common import require_empty


# ---------------------------------------------------------------------------
def pp_chp(db: DB):
    """pp_chp.mod : flow control attributes of CHP processes from NCAP_CHPR / NCAP_CEH.

    Works on Python dictionaries, statement by statement; a value of 0 held in a dictionary is an EPS record.
    """
    import math
    q = db.q
    # --- NCAP_CDME(RTP)$(NCAP_CDME(RTP)=0)=0;
    #     (pp_chp.mod 14: a condensing efficiency given as 0, an EPS record, is cleared; it comes before any use of it)
    db.remove("NCAP_CDME", where="value = 0 and in_RTP(r,y,p)")
    cdme = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from NCAP_CDME")}
    cdme_fs = []
    if cdme:
        # --- FLO_SUM(RTP(R,V,P),C,COM,C,ANNUAL)$(RPC_SPG(R,P,COM)$RPC_PG(R,P,C)$NRG_TMAP(R,'ELC',C)) $= NCAP_CDME(RTP);
        #     (pp_chp.mod 19, the overall efficiency for EQ_PTRANS: of any process with NCAP_CDME, CHP or not)
        cdme_fs = [(r, y, p_, c, com, c, "ANNUAL", cdme[(r, y, p_)]) for r, y, p_, c, com in q(
            """select k.r, k.y, k.p, g.c, s.c from RTP k join RPC_PG g on g.r=k.r and g.p=k.p join RPC_SPG s on s.r=k.r and s.p=k.p
               where in_NCAP_CDME(k.r,k.y,k.p) and in_NRG_TMAP(g.r,'ELC',g.c) order by k.r, k.y, k.p, g.c, s.c""")]
    chp = set(db.q("select r, p from CHP"))
    if not chp and not db.card("NCAP_CHPR"):
        if cdme_fs:
            db.con.register("cf_", __import__("pandas").DataFrame(cdme_fs, columns=db.cols("FLO_SUM") + ["value"]))
            db.put("FLO_SUM", "select * from cf_", zero="eps"); db.con.unregister("cf_")
        return
    rtp = q("select r, y, p from RTP")
    chpr = {(r, y, p, l): v for r, y, p, l, v in q("select r, y, p, l, value from NCAP_CHPR")}
    ceh = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from NCAP_CEH")}
    bpme = {(r, y, p): v for r, y, p, v in q("select r, y, p, value from NCAP_BPME")}
    BD = ("LO", "UP", "FX")
    # --- NCAP_CHPR(RTP,BDNEQ)$NCAP_CHPR(RTP,'FX') = 0;
    for k in rtp:
        if k + ("FX",) in chpr:
            chpr.pop(k + ("LO",), None); chpr.pop(k + ("UP",), None)
    # --- COEF_RTP(RTP(R,V,P))$CHP(R,P) = MAX(0,SMAX(BD,NCAP_CHPR(RTP,BD)));
    coef = {}
    #     MAX(EPS,0) is EPS: a ratio given as 0 (EPS, as an NCAP_CHPR FX given as 0) puts the vintage in RVP below
    for k in rtp:
        if (k[0], k[2]) in chp:
            v = max(0.0, max(chpr.get(k + (b,), 0.0) for b in BD))
            if v:
                coef[k] = v
            elif any(k + (b,) in chpr and chpr[k + (b,)] == 0 for b in BD):
                coef[k] = 0.0                                                    # EPS
    # --- NCAP_CEH(RTP)$((COEF_RTP(RTP)>0)$NCAP_CDME(RTP)) = MAX(.001,(NCAP_CDME(RTP)/MAX(NCAP_CDME(RTP),NCAP_BPME(RTP))*(1+COEF_RTP(RTP))-1)/COEF_RTP(RTP));
    #     (NCAP_BPME is 1 where it was not given, ppmain.mod 651; one given as 0 is EPS, and the MAX takes NCAP_CDME)
    for k, cr in coef.items():
        if cr > 0 and k in cdme:
            ceh[k] = max(.001, (cdme[k] / max(cdme[k], bpme.get(k, 0.0)) * (1 + cr) - 1) / cr)
    rvp = []
    rp_grp, trackpg, rp_prc, chp_elc, trackp = set(), set(), set(), set(), set()
    pg = {}
    for r, p_, c in q("select r, p, c from RPC_PG"):
        pg.setdefault((r, p_), []).append(c)
    pgact = set(q("select r, p from RP_PGACT"))
    if chp:
        # --- OPTION PRC_ACT < NCAP_CHPR;  CHP_ELC(RPC_PG(CHP(PRC_ACT(R,P)),C))$NRG_TMAP(R,'ELC',C) = YES;
        has = {(r, p_) for (r, y, p_, l) in chpr} | set(q("select distinct r, p from NCAP_CHPR"))
        elc = set(q("select r, c from NRG_TMAP where nrg_type='ELC'"))
        chp_elc = {(r, p_, c) for (r, p_) in chp & has for c in pg.get((r, p_), ()) if (r, c) in elc}
        # --- OPTION TRACKP < CHP_ELC; TRACKP(RP_PGACT) = NO;
        trackp = {(r, p_) for r, p_, c in chp_elc} - pgact
        # --- RVP(RTP(R,V,P))$(COEF_RTP(RTP)$TRACKP(R,P)) = YES;
        #     (COEF_RTP is set on RTP only, above: RVP is of RTP)
        rvp = [k for k in rtp if k in coef and (k[0], k[2]) in trackp]
        # --- RP_GRP(RPC_PG(TRACKP(RP),C))$(NOT CHP_ELC(RP,C)) = YES;
        rp_grp = {(r, p_, c) for (r, p_) in trackp for c in pg.get((r, p_), ()) if (r, p_, c) not in chp_elc}
        # --- RP_GRP(RP_PGACT(CHP),C)$(TOP(CHP,C,'OUT')$(NOT CHP_ELC(CHP,C))) = YES;
        rp_grp |= {(r, p_, c) for r, p_, c in q("select r, p, c from TOP where io='OUT' and in_CHP(r,p) and in_RP_PGACT(r,p)")
                   if (r, p_, c) not in chp_elc}
        # --- TRACKPG(RP_GRP(RPC_PG(R,P,C)))$COM_LIM(R,C,'N')=YES; OPTION RP_PRC<TRACKPG;
        limn = set(q("select r, c from COM_LIM where l='N'"))
        trackpg = {(r, p_, c) for r, p_, c in rp_grp if c in pg.get((r, p_), ()) and (r, c) in limn}
        rp_prc = {(r, p_) for r, p_, c in trackpg}
        for k in rvp:
            rp = (k[0], k[2])
            # --- NCAP_CEH(RVP(R,V,P))$(NCAP_CEH(RVP)=0) = -0.5$RP_PRC(R,P);
            if ceh.get(k, 0.0) == 0:
                ceh.pop(k, None)
                if rp in rp_prc:
                    ceh[k] = -0.5
            # --- NCAP_BPME(RVP) = MIN(0,SMIN(BD$NCAP_CHPR(RVP,BD),NCAP_CHPR(RVP,BD))*((NCAP_CEH(RVP)+1)$NCAP_CEH(RVP)-1));
            lo = min((chpr[k + (b,)] for b in BD if k + (b,) in chpr), default=math.inf)
            m = (ceh[k] + 1 if k in ceh else 0.0) - 1
            v = min(0.0, lo * m)
            bpme.pop(k, None)
            if v:
                bpme[k] = v
            elif lo == 0 and m:
                bpme[k] = 0.0            # EPS*x and MIN(0,EPS) are EPS: an EPS ratio gives an EPS NCAP_BPME
            # --- NCAP_CEH(RVP)$(NCAP_CEH(RVP)<0) = -NCAP_CEH(RVP);
            if ceh.get(k, 0.0) < 0:
                ceh[k] = -ceh[k]
            # --- NCAP_CHPR(RVP,'FX')$((ABS(NCAP_CEH(RVP)-1)>.01)$(NOT NCAP_CHPR(RVP,'UP'))) = COEF_RTP(RVP)+EPS;
            if abs(ceh.get(k, 0.0) - 1) > .01 and k + ("UP",) not in chpr:
                chpr[k + ("FX",)] = coef[k]
    # ---- Calculate ACTFLOs for pg and elc
    # (RVP, and every look-up below, is of CHP processes: their records are read, and only what changes is written back)
    act = {(r, y, p_, c): v for r, y, p_, c, v in q("select r, y, p, cg, value from PRC_ACTFLO where in_CHP(r,p)")}
    had, act_set = set(act), {}
    for k in rvp:
        r, v_, p_ = k
        for c in pg.get((r, p_), ()):
            kc = k + (c,)
            a = act.get(kc, 0.0)
            # --- PRC_ACTFLO(RVP(R,V,P),C)$RPC_PG(R,P,C) = 1+((PRC_ACTFLO(RVP,C)/COEF_RTP(RVP)+1)/MAX(1E-3,EXP(ABS(LOG(NCAP_CEH(RVP))))-PRC_ACTFLO(RVP,C))-1)$(COEF_RTP(RVP)>0)$TRACKPG(R,P,C);
            #     (a ratio given as 0 leaves COEF_RTP at EPS: the term is not taken, PRC_ACTFLO is 1)
            a = 1 +(((a / coef[k] + 1) / max(1e-3, math.exp(abs(math.log(ceh[k]))) - a) - 1) if (r, p_, c) in trackpg and coef[k] > 0 else 0.0)
            e = ceh.get(k, 0.0)
            # --- PRC_ACTFLO(RVP(R,V,P),C)$((NCAP_CEH(RVP) LE 1)$RPC_PG(R,P,C)) =
            #        POWER(NCAP_CEH(RVP),(1$CHP_ELC(R,P,C)-1)$NCAP_CEH(RVP)) * (1-NCAP_BPME(RVP)) * PRC_ACTFLO(RVP,C);
            if e <= 1:
                ex = ((1 if (r, p_, c) in chp_elc else 0) - 1) if k in ceh else 0
                a = (e ** ex if ex else 1.0) * (1 - bpme.get(k, 0.0)) * a
            # --- PRC_ACTFLO(RVP(R,V,P),C)$(((NCAP_CEH(RVP) GT 1)*NCAP_CEH(RVP))$RPC_PG(R,P,C)) =
            #        (1+(1/NCAP_CEH(RVP)-1)/(1+1/COEF_RTP(RVP))) * POWER(NCAP_CEH(RVP),1-1$CHP_ELC(R,P,C)) * PRC_ACTFLO(RVP,C);
            if e > 1:
                a = (1 + (1 / e - 1) / (1 + 1 / coef[k])) * (e if (r, p_, c) not in chp_elc else 1.0) * a
            act[kc] = act_set[kc] = a
    # --- FLO_SUM(RTP(R,V,P),C,COM,C,ANNUAL)$(RP_GRP(R,P,COM)$CHP_ELC(R,P,C)$NCAP_CDME(RTP)) = -1/PRC_ACTFLO(RTP,COM);
    #     (pp_chp.mod 45, EQ_PTRANS control of low-temperature heat: on every vintage of RTP)
    heat_fs = []
    if cdme:
        for r, p_, c in sorted(chp_elc):
            for com in sorted(x for (a, b, x) in rp_grp if (a, b) == (r, p_)):
                for k in [k for k in rtp if (k[0], k[2]) == (r, p_)]:
                    if k in cdme:
                        x = act.get(k + (com,), 0.0)
                        if not x:
                            raise SystemExit(f"division by {'eps' if k + (com,) in act else 'zero'} (pp_chp.mod 45, as GAMS stops): "
                                             f"PRC_ACTFLO({k[0]},{k[1]},{k[2]},{com}) of a CHP process with NCAP_CDME")
                        heat_fs.append((r, k[1], p_, c, com, c, "ANNUAL", -1 / x))
    # ---- EQ_OUTSHR controls: bound for the electricity output
    # --- RP_GRP(TRACKPG)=NO; TRACKP(RP_PRC)=NO;  OPTION CLEAR=TRACKPG; TRACKPG(RP_PG(TRACKP,CG))=YES;
    rp_grp -= trackpg
    trackp -= rp_prc
    trackpg = {(r, p_, cg) for r, p_, cg in q("select r, p, cg from RP_PG") if (r, p_) in trackp}
    # --- TRACKPG(RP_PGACT(CHP(R,P)),CG('NRG')) $= SUM(RP_GRP(R,P,C)$COM_GMAP(R,CG,C),1);
    nrg = set(q("select r, c from COM_GMAP where cg='NRG'"))
    trackpg |= {(r, p_, "NRG") for r, p_, c in rp_grp if (r, p_) in pgact and (r, p_) in chp and (r, c) in nrg}
    # --- RP_GRP(RP_GRP(RP,C))$SUM(TRACKPG(RP,CG),1) = NO;
    tpg = {}
    for r, p_, cg in trackpg:
        tpg.setdefault((r, p_), []).append(cg)
    rp_grp = {k for k in rp_grp if (k[0], k[1]) not in tpg}
    prc_ts = {}
    for r, p_, s_ in q("select r, p, s from PRC_TS where in_CHP(r,p)"):      # read for CHP_ELC and RP_GRP: CHP only
        prc_ts.setdefault((r, p_), []).append(s_)
    by_rp = {}
    for k in rtp:
        by_rp.setdefault((k[0], k[2]), []).append(k)
    shar = []                                   # (r,y,p,c,cg,s,l,value); value None = delete
    # --- LOOP((CHP_ELC(R,P,C),TRACKPG(R,P,CG)),
    #       FLO_SHAR(RTP(R,V,P),C,CG,S,'LO')$(PRC_TS(R,P,S) * NCAP_CHPR(RTP,'UP')) = 1 / (1+NCAP_CHPR(RTP,'UP'));  FX from FX;  UP from LO
    for r, p_, c in chp_elc:
        for cg in tpg.get((r, p_), ()):
            for k in by_rp.get((r, p_), ()):
                for dst, src in (("LO", "UP"), ("FX", "FX"), ("UP", "LO")):
                    if k + (src,) in chpr:
                        for s_ in prc_ts.get((r, p_), ()):
                            shar.append((r, k[1], p_, c, cg, s_, dst, 1 / (1 + chpr[k + (src,)])))
    # --- FLO_SHAR(RTP(R,V,P),C,CG,S,BD)$(PRC_TS(R,P,S)$RP_PG(R,P,CG)$RP_GRP(R,P,C)) = NCAP_CHPR(RTP,BD)/(NCAP_CHPR(RTP,BD)+1);
    rp_pg = {}
    for r, p_, cg in q("select r, p, cg from RP_PG"):
        rp_pg.setdefault((r, p_), []).append(cg)
    for r, p_, c in rp_grp:
        for cg in rp_pg.get((r, p_), ()):
            for k in by_rp.get((r, p_), ()):
                for b in BD:
                    #     (an NCAP_CHPR given as EPS gives EPS/(EPS+1), an EPS share: the record stays, kept as 0)
                    v = chpr.get(k + (b,))
                    for s_ in prc_ts.get((r, p_), ()):
                        shar.append((r, k[1], p_, c, cg, s_, b, v / (v + 1) if v is not None else None))
    # --- FLO_SUM(RVP,COM,C,COM,S)$((NCAP_BPME(RVP)$NCAP_CEH(RVP)$PRC_ACTFLO(RVP,C)<0)$FLO_EFF(RVP,COM,C,S)) = FLO_EFF(RVP,COM,C,S)/PRC_ACTFLO(RVP,C);
    fsum = []
    rvps = set(rvp)
    for r, y, p_, com, c, s_, v in q("select r, y, p, cg, c, s, value from FLO_EFF where in_CHP(r,p)") if rvps else ():   # RVP: CHP only
        k = (r, y, p_)
        if k in rvps and k in ceh and (k + (c,)) in act and bpme.get(k, 0.0) < 0:
            fsum.append((r, y, p_, com, c, com, s_, v / act[k + (c,)]))
    # --- IF(SUM(CHP(RP_XRED),1),PRC_ACTFLO(RVP(R,V,P),C)$RPC_AFLO(R,P,C)=1; RPC_ACT(RPC_AFLO(CHP(RP_XRED),C))=YES);
    if db.q1("select count(*) from RP_XRED where in_CHP(r,p)"):
        unsupported(db, "CHP processes with ACT_FLO (RP_XRED)")
    # --- LOOP(RPC_PKC(CHP_ELC(R,P,C)),NCAP_PKCNT(RVP(R,V,P),S)$COM_TS(R,C,S)=NCAP_PKCNT(RVP,S)/MAX(1,PRC_ACTFLO(RVP,C)));
    pkc = set(q("select r, p, c from RPC_PKC")) & chp_elc
    pk = []
    if pkc:
        cnt = {(r, y, p_, s_): v for r, y, p_, s_, v in q("select r, y, p, s, value from NCAP_PKCNT")}
        com_ts = {}
        for r, c, s_ in q("select r, c, s from COM_TS"):
            com_ts.setdefault((r, c), []).append(s_)
        for r, p_, c in sorted(pkc):
            for k in rvp:
                if (k[0], k[2]) == (r, p_):
                    for s_ in com_ts.get((r, c), ()):
                        if k + (s_,) in cnt:
                            cnt[k + (s_,)] = cnt[k + (s_,)] / max(1.0, act.get(k + (c,), 0.0))
                            pk.append(k + (s_,))
    # --- RVP(RVP)$(NCAP_CEH(RVP)+1$NCAP_CHPR(RVP,'FX')+NCAP_CHPR(RVP,'LO')>0) = NO;  -> QA for the rest
    mile = {y for (y,) in q("select y from MILESTONYR")}
    vint = set(q("select r, p from PRC_VINT"))
    for k in rvp:
        if not (ceh.get(k, 0.0) + (1 if k + ("FX",) in chpr else 0) + chpr.get(k + ("LO",), 0.0) > 0):
            if k[1] in mile or (k[0], k[2]) in vint:
                db.log.append(f"*01 WARNING - CHP process with zero CEH but only upper bound on CHPR; unusual CHP operation: R={k[0]} P={k[2]} V={k[1]}")
    # ---- write back
    db.clear("NCAP_CHPR", "NCAP_CEH", "NCAP_BPME", "CHP_ELC")
    db.load_rows("NCAP_CHPR", [k + (v,) for k, v in chpr.items()])
    db.load_rows("NCAP_CEH", [k + (v,) for k, v in ceh.items()])
    db.load_rows("NCAP_BPME", [k + (v,) for k, v in bpme.items()])
    db.load_rows("CHP_ELC", sorted(chp_elc))
    import pandas as pd
    # the records set above: those already there changed in place (each keeps its place in the table), the new ones
    # added at the end in the order they were made (as the table written again whole had them)
    upd = [k + (v,) for k, v in act_set.items() if k in had]
    if upd:
        db.con.register("af_", pd.DataFrame(upd, columns=["r", "y", "p", "cg", "value"]))
        db.x("update PRC_ACTFLO a set value = u.value from af_ u where a.r=u.r and a.y=u.y and a.p=u.p and a.cg=u.cg")
        db.con.unregister("af_")
    db.load_rows("PRC_ACTFLO", [k + (v,) for k, v in act_set.items() if k not in had])
    if shar:
        df = pd.DataFrame(shar, columns=db.cols("FLO_SHAR") + ["value"]).drop_duplicates(subset=db.cols("FLO_SHAR"), keep="last")
        db.con.register("sh_", df)
        on = " and ".join(f"a.{c}=sh_.{c}" for c in db.cols("FLO_SHAR"))
        db.x(f"delete from FLO_SHAR a where exists(select 1 from sh_ where {on})")
        db.x("insert into FLO_SHAR select * from sh_ where value is not null")
        db.con.unregister("sh_")
    # FLO_SUM in TIMES's order: pp_chp.mod 19 (NCAP_CDME), 45 (heat), 61 (ACT flows)
    for rows in (cdme_fs, heat_fs, fsum):
        if rows:
            df = pd.DataFrame(rows, columns=db.cols("FLO_SUM") + ["value"])
            db.con.register("fs_", df); db.put("FLO_SUM", "select * from fs_", zero="eps"); db.con.unregister("fs_")
    if pk:
        df = pd.DataFrame([k + (cnt[k],) for k in set(pk)], columns=db.cols("NCAP_PKCNT") + ["value"])
        db.con.register("pk_", df); db.put("NCAP_PKCNT", "select * from pk_", zero="eps"); db.con.unregister("pk_")
