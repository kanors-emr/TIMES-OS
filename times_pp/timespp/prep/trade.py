# SPDX-License-Identifier: GPL-3.0-or-later
"""ppmain.mod: inter-regional exchange (prices, levelling of IRE_FLO, the trade control sets)."""
from ..engine import DB


# ---------------------------------------------------------------------------
def trade_attributes(db: DB):
    """Inter-regional exchange: prices, IRE_FLO levelling, trade control sets."""
    from ..lvl import lvlfc, trees, aggregate, read_series, _ctl_map, _out, _write
    lvlfc(db, "IRE_PRICE", ["p", "c"], "RPCS_VAR", "DATAYEAR", "in_RPC_IRE(a.r,a.p,a.c,a.ie)")
    lvlfc(db, "IRE_FLOSUM", ["p"], "PRC_TS", "MILESTONYR", "in_RTP(a.r,a.y,a.p)")
    # ---- pp_lvlif.mod: IRE_FLO(REG,V,P,COM,R,C,S) given off the flow timeslices of the importing side
    if db.card("IRE_FLO"):
        for r, p, c in db.q("""select distinct a.r2, a.p, a.c2 from IRE_FLO a where in_REG(a.r) and in_REG(a.r2) and a.s <> 'ANNUAL'
                               and not in_RPCS_VAR(a.r2,a.p,a.c2,a.s) and not in_RPC_IRE(a.r2,a.p,a.c2,'IMP')"""):
            db.log.append(f"*02 WARNING - IRE_FLO import commodity not in TOP_IRE: R={r} P={p} C={c}")
        key, series = read_series(db, "IRE_FLO", """in_REG(a.r) and in_REG(a.r2) and in_MODLYEAR(a.y) and exists(
              select 1 from IRE_FLO b where b.r=a.r and b.y=a.y and b.p=a.p and b.c=a.c and b.r2=a.r2 and b.c2=a.c2
                and b.s <> 'ANNUAL' and not in_RPCS_VAR(b.r2,b.p,b.c2,b.s) and in_RPC_IRE(b.r2,b.p,b.c2,'IMP'))""")
        prc_ts = _ctl_map(db, "PRC_TS", ["p"])
        T, out = trees(db), []
        for k, arr in series.items():
            r2, p = k[key.index("r2")], k[key.index("p")]
            for ts in prc_ts.get((r2, p), ()):
                if ts not in arr:
                    v = aggregate(T[r2], arr, ts)
                    if v is not None:
                        out.append(k + (ts, _out(v)))
        _write(db, "IRE_FLO", key, out)
        # --- IRE_FLO(RTP(REG,V,P),COM,R,C,S)$((NOT IRE_FLO(..,S))$PRC_TS(R,P,S)) $= IRE_FLO(REG,V,P,COM,R,C,'ANNUAL');
        db.put("IRE_FLO", """select a.r, a.y, a.p, a.c, a.r2, a.c2, t.s, a.value from IRE_FLO a join PRC_TS t on t.r=a.r2 and t.p=a.p
                             where a.s='ANNUAL' and in_RTP(a.r,a.y,a.p) and in_REG(a.r2)
                               and not in_IRE_FLO(a.r,a.y,a.p,a.c,a.r2,a.c2,t.s)""", zero="eps")
    # ---- trade indicators (only trade between two model regions)
    db.tmp("t_top", "select r, c, r2, c2, p from TOP_IRE where in_REG(r) and in_REG(r2)")
    # --- LOOP(TOP_IRE(R,C,REG,COM,P),RXX(R,C,P) = YES; RPC_IREIO(REG,P,COM,'IMP','IN') = YES);
    db.assign("RXX", "select distinct r, c as u, p as u2 from t_top")
    db.add("RPC_IREIO", "select distinct r2 as r, p, c2 as c, 'IMP' as ie, 'IN' as io from t_top")
    # --- RPC_IREIO(R,P,C,'EXP','IN')$RXX(R,C,P) = YES;
    db.add("RPC_IREIO", "select distinct r, p, c, 'EXP' as ie, 'IN' as io from t_top")
    # --- RPC_IREIO(RPC_IRE(R,P,C,IE),'OUT')$(NOT RPC_IREIO(R,P,C,IE,'IN')) = YES;
    db.add("RPC_IREIO", "select r, p, c, ie, 'OUT' as io from RPC_IRE where in_REG(r) and not in_RPC_IREIO(r,p,c,ie,'IN')")
    # --- PRC_MAP(R,'DISTR',P)$PRC_MAP(R,'CORR',P) = YES;  IRE_DIST(RP_IRE(R,P))$PRC_MAP(R,'DISTR',P) = YES;
    db.add("PRC_MAP", "select r, 'DISTR' as prc_grp, p from PRC_MAP where prc_grp='CORR' and in_REG(r)")
    db.add("IRE_DIST", "select r, p from RP_IRE where in_REG(r) and in_PRC_MAP(r,'DISTR',p)")
    q = db.q
    dist = set(q("select r, p from IRE_DIST"))
    top = [tuple(x) for x in q("select r, c, r2, c2, p from t_top order by r, p, c, r2, c2")]
    tops = set(top)
    ndest = {}
    for r, c, r2, c2, p in top:
        ndest[r, c, p] = ndest.get((r, c, p), 0) + 1
    # --- Define a marketplace whenever imports to several regions, or an intermediate region between two other regions
    #     LOOP(RXX(R,C,P)$(SUM(TOP_IRE(R,C,REG,COM,P),1) GT 1),RPC_MARKET(R,P,C,'EXP') = YES);
    market = {(r, p, c) for (r, c, p), n in ndest.items() if n > 1}
    #     LOOP(TOP_IRE(REG,COM,RXX(R,C,P))$(NOT SUM(COM1$TOP_IRE(R,C,REG,COM1,P),1)),RPC_MARKET(R,P,C,'EXP') = YES);
    #     RXX(R,C,P)$IRE_DIST(R,P) = NO;
    #     LOOP(TOP_IRE(REG,COM,RXX(R,C,P))$(NOT SUM(COM1$TOP_IRE(R,C,REG,COM1,P),1)),RPC_MARKET(R,P,C,'EXP') = YES);
    back = {(r, c, r2, p) for r, c, r2, c2, p in top}
    for reg, com, r, c, p in top:
        if (r, c, p) in ndest and (r, p) not in dist and (r, c, reg, p) not in back:
            market.add((r, p, c))
    # --- Ensure that over distribution all directly linked regions after first market are also markets
    #     TRACKPC(IRE_DIST(R,P),C)$RPC_MARKET(R,P,C,'EXP') = YES;
    #     WHILE(CARD(TRACKPC), OPTION CLEAR=RXX;
    #       LOOP((TRACKPC(R,P,C),TOP_IRE(R,C,REG,COM,P),RPC_IRE(REG,P,COM1,'EXP')),
    #         IF(NOT SUM(COM2$TOP_IRE(REG,COM1,R,COM2,P),1),RXX(REG,P,COM1)=YES));
    #       OPTION CLEAR=TRACKPC; TRACKPC(RXX(R,P,C))$(NOT RPC_MARKET(R,P,C,'EXP')) = YES;  RPC_MARKET(TRACKPC,'EXP') = YES);
    exps = {}
    for r, p, c in q("select r, p, c from RPC_IRE where ie='EXP' and in_REG(r)"):
        exps.setdefault((r, p), []).append(c)
    trackpc = {(r, p, c) for r, p, c in market if (r, p) in dist}
    while trackpc:
        rxx = set()
        for r, p, c in trackpc:
            for a, b, reg, com, pp in top:
                if (a, b, pp) == (r, c, p):
                    for com1 in exps.get((reg, p), ()):
                        if not any((x, y, z, w) == (reg, com1, r, p) for x, y, z, w2, w in top):
                            rxx.add((reg, p, com1))
        trackpc = rxx - market
        market |= trackpc
    # --- Set the import commodities for marketplaces
    #     LOOP(RPC_MARKET(R,P,C,IE)$(NOT SUM(TOP_IRE(R,C,R,COM,P),1)), Z=SUM(RPC_IRE(R,P,COM,'IMP'),1)+EPS;
    #       IF(Z EQ 1, LOOP(RPC_IRE(R,P,COM,'IMP'), Z=0; CG_GRP(R,P,C,COM) = YES));  IF(Z,CG_GRP(R,P,C,C) = YES));
    #     LOOP(CG_GRP(R,P,C,COM),RC_RC(R,C,R,COM) = YES);  TOP_IRE(RC_RC(R,C,R,COM),P)$CG_GRP(R,P,C,COM) = YES;
    imps = {}
    for r, p, c in q("select r, p, c from RPC_IRE where ie='IMP' and in_REG(r)"):
        imps.setdefault((r, p), []).append(c)
    selfl = []
    for r, p, c in sorted(market):
        if any(a == r and b == c and a2 == r and pp == p for a, b, a2, b2, pp in top):
            continue
        #   Z=SUM(RPC_IRE(R,P,COM,'IMP'),1)+EPS;  IF(IRE_DIST(R,P), (Z GT 1: unsupported diverging topology, a QA warning)
        #   ELSEIF Z=1, Z=SUM(COM$RPC_MARKET(R,P,COM,'EXP'),1));
        #   IF(Z EQ 1, LOOP(RPC_IRE(R,P,COM,'IMP'), Z=0; CG_GRP(R,P,C,COM) = YES));  IF(Z,CG_GRP(R,P,C,C) = YES)
        im = imps.get((r, p), [])
        z = len(im)
        if (r, p) not in dist and z == 1:
            z = sum(1 for a, b, cc in market if (a, b) == (r, p))
        selfl.append((r, c, r, im[0] if z == 1 else c, p))
    if selfl:
        db.load_rows("RC_RC", sorted({(r, c, r2, c2) for r, c, r2, c2, p in selfl} - set(map(tuple, q("select * from RC_RC")))))
        db.load_rows("TOP_IRE", [x for x in selfl if x not in tops])
        top += [x for x in selfl if x not in tops]
        tops |= set(selfl)
    # --- Complete the preparation of marketplace: LOOP(TOP_IRE(R,C,R,COM,P), ... F = SUM((RTP(R,T,P),S)$IRE_FLO(R,T,P,C,R,COM,S),1);
    #       LOOP((REG,COM1)$(TOP_IRE(R,C,REG,COM1,P)$(NOT F)), F = SUM((RTP(R,T,P),S)$IRE_FLO(R,T,P,C,REG,COM1,S),1);
    #         IF(F, IRE_FLO(RTP(R,V,P),C,R,COM,S)$RPCS_VAR(R,P,COM,S) = IRE_FLO(R,V,P,C,REG,COM1,S)))));
    has = {tuple(x) for x in q("""select distinct r, p, c, r2, c2 from IRE_FLO f where in_MILESTONYR(y) and in_RTP(r,y,p)""")}
    regs = [r for (r,) in q("select r from REG order by r")]
    rtpv = {}
    for r, y, p in q("select r, y, p from RTP"):
        rtpv.setdefault((r, p), []).append(y)
    for r, c, r2, com, p in [x for x in top if x[0] == x[2]]:
        if (r, p) in dist:
            # --- IF(IRE_DIST(R,P), IRE_FLO(RTP(R,V,P),C,R,COM,S)$((IRE_FLO(R,V,P,C,R,COM,S) EQ 0)$RPCS_VAR(R,P,COM,S)) = 1;
            db.put("IRE_FLO", f"""select k.r, k.y, k.p, '{c}' as c, k.r as r2, '{com}' as c2, v.s, 1.0 as value
                                  from RTP k join RPCS_VAR v on v.r=k.r and v.p=k.p and v.c='{com}'
                                  where k.r='{r}' and k.p='{p}' and v_IRE_FLO(k.r,k.y,k.p,'{c}',k.r,'{com}',v.s) = 0""")
            continue
        if (r, p, c, r, com) in has:
            continue
        for reg in regs:
            src = [(a2, b2) for a, b, a2, b2, pp in top if a == r and b == c and pp == p and a2 == reg and (r, p, c, a2, b2) in has]
            if src:
                reg1, com1 = sorted(src)[0]
                db.put("IRE_FLO", f"""select f.r, f.y, f.p, f.c, '{r}' as r2, '{com}' as c2, f.s, f.value from IRE_FLO f
                                      where f.r='{r}' and f.p='{p}' and f.c='{c}' and f.r2='{reg1}' and f.c2='{com1}'
                                        and in_RTP(f.r,f.y,f.p) and in_RPCS_VAR(f.r,f.p,'{com}',f.s)""", zero="eps")
                has.add((r, p, c, r, com))
                break
    # --- Set standard EQIRE control for all imports other than from marketplace region
    #     LOOP(TOP_IRE(R,C,REG,COM,P)$RPC_MARKET(R,P,C,'EXP'),IF(NOT SAMEAS(R,REG),TRACKPC(REG,P,COM) = YES));
    #     RPC_EQIRE(RPC_IRE(R,P,C,'IMP'))$((NOT TRACKPC(R,P,C))$RPC_IREIO(R,P,C,'IMP','IN')) = YES;
    frommkt = {(r2, p, c2) for r, c, r2, c2, p in top if (r, p, c) in market and r != r2}
    eqire = {(r, p, c, "IMP") for r, p, c in q("""select r, p, c from RPC_IRE where ie='IMP' and in_REG(r)
                                                 and in_RPC_IREIO(r,p,c,'IMP','IN')""") if (r, p, c) not in frommkt}
    # --- Set all non-standard EQIRE and MARKET controls
    #     LOOP(TOP_IRE(R,C,R,COM,P), IF(NOT RPC_EQIRE(R,P,COM,'IMP'), RPC_EQIRE(R,P,C,'EXP') = YES;
    #       ELSEIF RPC_MARKET(R,P,C,'EXP'), IF(IRE_DIST(R,P), RPC_EQIRE(R,P,C,'EXP') = YES; ELSE RPC_MARKET(R,P,COM,'IMP') = YES)));
    #     TOP_IRE(R,C,R,COM,P)$RPC_EQIRE(R,P,C,'EXP') = NO;
    mk = {(r, p, c, "EXP") for r, p, c in market}
    for r, c, r2, com, p in [x for x in top if x[0] == x[2]]:
        if (r, p, com, "IMP") not in eqire:
            eqire.add((r, p, c, "EXP"))
        elif (r, p, c) in market:
            if (r, p) in dist:
                eqire.add((r, p, c, "EXP"))
            else:
                mk.add((r, p, com, "IMP"))
    db.load_rows("RPC_EQIRE", sorted(eqire))
    db.load_rows("RPC_MARKET", sorted(mk))
    db.x("""delete from TOP_IRE where r = r2 and in_REG(r) and in_RPC_EQIRE(r,p,c,'EXP')""")
    db.tmp("t_top", "select r, c, r2, c2, p from TOP_IRE where in_REG(r) and in_REG(r2)")
    # --- Copy shutdown periods of marketplace to import regions
    #     LOOP(RPC_MARKET(R,P,C,'EXP'),RTPC(REG,T,P,COM)$(TOP_IRE(R,C,REG,COM,P)$(NOT RTP_VARA(R,T,P))) = NO);
    db.remove("RTPC", where="""exists(select 1 from t_top a where a.r2=RTPC.r and a.c2=RTPC.c and a.p=RTPC.p
                                      and in_RPC_MARKET(a.r,a.p,a.c,'EXP') and in_MILESTONYR(RTPC.y) and not in_RTP_VARA(a.r,RTPC.y,a.p))""")
    # --- LOOP(TOP_IRE(REG,C,R,COM,P)$RPC_EQIRE(R,P,COM,'IMP'),RTPC(REG,T,P,C)$(NOT RTP_VARA(R,T,P)) = NO);
    db.remove("RTPC", where="""exists(select 1 from t_top a where a.r=RTPC.r and a.c=RTPC.c and a.p=RTPC.p
                                      and in_RPC_EQIRE(a.r2,a.p,a.c2,'IMP') and not in_RTP_VARA(a.r2,RTPC.y,a.p))""")
    # --- RP_AIRE(RP_IRE(R,P),'EXP')$(RP_AIRE(R,P,'IMP')$IRE_DIST(R,P)) = NO;
    db.remove("RP_AIRE", where="ie='EXP' and in_RP_IRE(r,p) and in_RP_AIRE(r,p,'IMP') and in_IRE_DIST(r,p)")
    # --- IRE_FLOSUM(RTP(R,T,P),C,S,IE,COM,IO)$(RPC_PG(R,P,C)$RP_AIRE(R,P,IE)$IRE_FLOSUM(RTP,%PGPRIM%,S,IE,COM,IO)) =
    #        IRE_FLOSUM(RTP,%PGPRIM%,S,IE,COM,IO)*(1/PRC_ACTFLO(RTP,C));   IRE_FLOSUM(R,T,P,%PGPRIM%,S,IE,COM,IO) = 0;
    db.put("IRE_FLOSUM", """select f.r, f.y, f.p, g.c, f.s, f.ie, f.c2, f.io, f.value * (1 / v_PRC_ACTFLO(f.r,f.y,f.p,g.c)) as value
                            from IRE_FLOSUM f join RPC_PG g on g.r=f.r and g.p=f.p
                            where f.c='ACT' and in_MILESTONYR(f.y) and in_RTP(f.r,f.y,f.p) and in_RP_AIRE(f.r,f.p,f.ie)""", zero="eps")
    db.zap("IRE_FLOSUM", "c='ACT' and in_MILESTONYR(y) and in_REG(r)")
    # --- LOOP(TOP_IRE(R,C,REG,COM,P), IF(NOT SUM((RTP(R,T,P),S)$IRE_FLO(R,T,P,C,REG,COM,S),1),
    #        IRE_FLO(RTP(R,V,P),C,REG,COM,S)$PRC_TS(REG,P,S) = 1));
    db.put("IRE_FLO", """select k.r, k.y, k.p, a.c, a.r2, a.c2, t.s, 1 as value from t_top a join RTP k on k.r=a.r and k.p=a.p
                         join PRC_TS t on t.r=a.r2 and t.p=a.p
                         where not exists(select 1 from IRE_FLO f where f.r=a.r and f.p=a.p and f.c=a.c and f.r2=a.r2 and f.c2=a.c2
                                          and in_MILESTONYR(f.y) and in_RTP(f.r,f.y,f.p))""")
