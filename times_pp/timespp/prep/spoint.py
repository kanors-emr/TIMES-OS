# SPDX-License-Identifier: GPL-3.0-or-later
"""A solution point loaded from an earlier run (spoint.mod 1, before the solve): LPOINT, and FIXBOH.

    $SET LPOINT <run>      the levels and marginals of the run <run> (execute_loadpoint): a starting point for the
                           solver, which does not change the model, unless REG_BDNCAP is given:
    REG_BDNCAP(R,BD)       new capacity of the periods up to the year REG_BDNCAP(R,BD) fixed (FX) or bounded (LO, UP)
                           at the loaded levels (spoint.mod 64-87)

spoint.mod 10-11, 40-49: the file looked for is <GDXPATH><LPOINT>_p, then <GDXPATH><LPOINT>; with FIXBOH the other
way round, and a missing file stops the run.  GDXPATH is that of the run folder, and LPOINT may carry a path
(refpoint.py: which files a run reads).  Without a file loaded, REG_BDNCAP is cleared (spoint.mod 65).
"""
from ..engine import DB
from ..controls import NotPorted, given
from .. import refpoint


def loaded_point(db: DB, symbols, fixboh=False):
    """The results of the run LPOINT names: ({SYMBOL: {key in upper case: (level, marginal)}}, file), or ({}, None)
    when no file is found (with FIXBOH: NotPorted, spoint.mod 49)."""
    lp = given(db.env, "LPOINT")
    if not lp:
        return {}, None
    folder = refpoint.run_folder(db)
    # spoint.mod 10-11: $SETLOCAL PATH '%GDXPATH%' SETLOCAL PNT1 '_p' SETLOCAL PNT2 '';
    #                   $IF SET FIXBOH $SETLOCAL PNT1 '' SETLOCAL PNT2 '_p'      (the file: %PATH%%LPOINT%%PNTn%)
    names = [lp, lp + "_p"] if fixboh else [lp + "_p", lp]
    path, looked = refpoint.find([refpoint.locate(folder, n) for n in names])
    if path is None:
        if fixboh:
            run = refpoint.run_of(lp) if lp.lower().endswith("_p") else lp
            raise NotPorted(f"FIXBOH: could not load the results of run {lp} (spoint.mod 49: $ABORT Could not load gdx file "
                            f"{lp}). Looked for: {'; '.join(looked)}. A run of this implementation writes its solution "
                            f"point ({run}_p.parquet) when it solves: solve the run {run} first, or say where its results "
                            "are with --points <folder> (its result folder or its run folder)")
        return {}, None
    pts = refpoint.read(path, symbols)
    refpoint.note_read(db, path, f"{'FIXBOH ' + given(db.env, 'FIXBOH') + ', ' if fixboh else ''}LPOINT {lp}: "
                                 "the solution point of an earlier run (spoint.mod)")
    out = {}
    for name, (kind, rows) in pts.items():
        if kind in ("variable", "equation"):
            out[name] = {tuple(str(x).upper() for x in r[:-2]): (float(r[-2]), float(r[-1] or 0.0)) for r in rows}
    db.loaded_point_from = path
    return out, path


def reg_bdncap(db: DB):
    """spoint.mod 63-87 (after LABEL FINISH): with a solution point loaded, the new capacity of the periods up to
    REG_BDNCAP(R,BD) fixed or bounded at its loaded level.  Called before the steps (solve.stp), after bndmain.mod."""
    if "REG_BDNCAP" not in db.sym or not db.card("REG_BDNCAP") or not given(db.env, "LPOINT"):
        return
    fixboh = db.ctl.get("FIXBOH") is not None
    pt, path = loaded_point(db, ["VAR_NCAP", "EQG_COMBAL", "EQE_COMBAL"], fixboh)
    # $IF NOT %LOAD%==2 $CLEAR REG_BDNCAP;  $IF NOT %LOAD%==2 $EXIT
    if path is None:
        return
    U = str.upper
    q = db.q
    bd = {}
    for r, l, v in q("select * from REG_BDNCAP"):
        bd.setdefault(U(r), {})[U(l)] = v
    # --- REG_BDNCAP(R,BDNEQ)$REG_BDNCAP(R,'FX')=MAX(REG_BDNCAP(R,BDNEQ),REG_BDNCAP(R,'FX'))$SUM(BD,REG_BDNCAP(R,BD)$BDSIG(BD));
    #     REG_BDNCAP(R,'FX')$SUM(BDNEQ$REG_BDNCAP(R,BDNEQ),1)=0;
    for r, b in bd.items():
        if "FX" in b:
            lu = sum(v for k, v in b.items() if k in ("LO", "UP"))
            for k in ("LO", "UP"):
                v = max(b.get(k, 0.0), b["FX"]) if lu else 0.0
                if v:
                    b[k] = v
                else:
                    b.pop(k, None)
            if any(k in b for k in ("LO", "UP")):
                del b["FX"]
    bd = {r: {k: v for k, v in b.items() if v} for r, b in bd.items()}
    # --- LOOP((R,BD)$REG_BDNCAP(R,BD),Z=REG_BDNCAP(R,BD); RT_NO(R,T)$(M(T)<=Z)=YES);
    M = {U(t): v for t, v in q("select y, value from M where in_MILESTONYR(y)")}
    rt_no = {(r, t) for r, b in bd.items() for z in b.values() for t, m in M.items() if m <= z}
    # --- RTCS(RTC,S--ORD(S))$=EQG_COMBAL.M(RTC,S);  RTCS(RTC,S--ORD(S))$=EQE_COMBAL.M(RTC,S);  OPTION FIL < RTCS;
    #     (the periods with a commodity balance of non-zero marginal in the loaded point)
    fil = {k[1] for e in ("EQG_COMBAL", "EQE_COMBAL") for k, (_, m) in pt.get(e, {}).items() if m}
    # --- PASTSUM(RTP(RT_NO(R,T(FIL)),P))$PRC_CAP(R,P)=EPS;  PASTSUM(RTP(RT_NO,P)) $= VAR_NCAP.L(RTP);
    rtp = {(U(r), U(t), U(p)): (r, t, p) for r, t, p in q("select r, y, p from RTP where in_MILESTONYR(y)") if (U(r), U(t)) in rt_no}
    cap = {(U(r), U(p)) for r, p in q("select r, p from PRC_CAP")}
    past = {k: 0.0 for k in rtp if k[1] in fil and (k[0], k[2]) in cap}
    for k, (lev, _) in pt.get("VAR_NCAP", {}).items():
        if k in rtp and lev:
            past[k] = lev
    # --- RTPS_BD(RTP(RT_NO(R,T),P),ANNUAL,BD)$((M(T)<=REG_BDNCAP(R,BD))$PASTSUM(RTP)) = YES;
    #     RTPS_BD(RTP(RT_NO(R,T),P),ANNUAL(S),BDNEQ)$(RTPS_BD(RTP,S,'LO')$RTPS_BD(RTP,S,'UP')) = BDSIG(BDNEQ)-NCAP_BND(R,'0',P,'N');
    nb = {}
    for r, y, p, l, v in q("select r, y, p, l, value from NCAP_BND"):
        nb[(U(r), U(y), U(p), U(l))] = v
    sel = {}
    for k in past:
        r, t, p = k
        s = {b for b, z in bd.get(r, {}).items() if M[t] <= z}
        if "LO" in s and "UP" in s:
            n = nb.get((r, "0", p, "N"), 0.0)
            s = {b for b in s if b == "FX"} | {b for b, sig in (("LO", 1), ("UP", -1)) if sig - n}
        if s:
            sel[k] = s
    # --- NCAP_BND(RTP(RT_NO(R,T),P),BD)$RTPS_BD(RTP,'ANNUAL',BD) = MAX(EPS,PASTSUM(RTP),NCAP_BND(RTP,BD)$BDLOX(BD));
    #     NCAP_BND(RTP(RT_NO,P),'UP')$(NCAP_BND(RTP,'LO')$NCAP_BND(RTP,'UP')) = SMAX(BDNEQ,NCAP_BND(RTP,BDNEQ));
    new = {}
    for k, s in sel.items():
        for b in s:
            new[k + (b,)] = max(0.0, past[k], nb.get(k + (b,), 0.0) if b in ("LO", "FX") else 0.0)
    for k in rtp:
        lo, up = k + ("LO",), k + ("UP",)
        have = lambda x: x in new or x in nb
        if have(lo) and have(up) and (lo in new or up in new):
            new[up] = max(new.get(lo, nb.get(lo)), new.get(up, nb.get(up)))
    if not new:
        return
    # --- VAR_NCAP.LO(RTP(RT_NO(R,T),P)) $= NCAP_BND(RTP,'LO');  .UP $= NCAP_BND(RTP,'UP');  .FX $= NCAP_BND(RTP,'FX');
    #     (EPS assigns 0; the records not changed above are the bounds bndmain.mod gave)
    cols = db.cols("NCAP_BND")
    db.x('create or replace temp table t_nb as select * from "NCAP_BND" limit 0')
    db.insert_rows("t_nb", [rtp[k[:3]] + (k[3], v) for k, v in sorted(new.items())])
    db.put("NCAP_BND", f"select {', '.join(cols)}, value from t_nb", zero="eps")
    keys = sorted({k[:3] for k in new})
    bnds = {(U(a), U(b), U(c)): (lo, up) for a, b, c, lo, up in q('select * from "B_VAR_NCAP"')}
    rows = []
    for k in keys:
        lo, up = bnds.get(k, (0.0, float("inf")))
        nlo, nup, nfx = (new.get(k + (b,), nb.get(k + (b,))) for b in ("LO", "UP", "FX"))
        lo = nlo if nlo is not None else lo
        up = nup if nup is not None else up
        if nfx is not None:
            lo = up = nfx
        rows.append(rtp[k] + (lo, up))
    db.x('create table if not exists "B_VAR_NCAP" (d0 VARCHAR, d1 VARCHAR, d2 VARCHAR, lower DOUBLE, upper DOUBLE)')
    db.x("create or replace temp table t_nk (c0 VARCHAR, c1 VARCHAR, c2 VARCHAR)")
    db.insert_rows("t_nk", [r[:3] for r in rows])
    db.x('delete from "B_VAR_NCAP" where exists(select 1 from t_nk k where k.c0 = d0 and k.c1 = d1 and k.c2 = d2)')
    db.insert_rows("B_VAR_NCAP", rows)
    db.bounds.add("VAR_NCAP")

