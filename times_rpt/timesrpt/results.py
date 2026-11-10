# SPDX-License-Identifier: GPL-3.0-or-later
"""The results of a run that later runs read, written after the solve as TIMES writes them (maindrv.mod 121-123).

    python results.py <model> <solution.db3> <out folder> <run folder> <run name> <preprocess.json>

    spoint.mod 14-18     the solution point <GDXPATH><run>_p (levels and marginals of every variable and equation),
                         which a later run loads with LPOINT or FIXBOH.  TIMES writes it with SPOINT 1 or YES, and a
                         run of TIMES in GAMS writes the whole run with GDX= on its command line; here it is written
                         after every solve, so that a later run can load it whatever the run file says
    wrtbprice.mod        TIMESED other than 0 and YES (NO, or the name of base prices that were not loaded): the base
                         prices of the demands, SOL_BPRICE, in com_bprice (the run folder) and <GDXPATH><run>_DP,
                         which a later run reads with TIMESED (elastic demands); with ANNCOST LEV also SOL_ACFR,
                         the annual costs as shares of the demand expenditure (read by MACRO MLF)

GDXPATH is the folder GAMSSAVE of the run folder when there is one, else the run folder (the folder as its user gave
it).  Each file is written as Parquet, with the mark of the run that wrote it (timespp/refpoint.py); a run reads only
these, never a GDX file.  A copy of each goes to the out folder.  Prints one line per file.
"""
import json, os, shutil, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "times_pp"))

from timespp import refpoint  # noqa: E402


def switch(env, k):
    return str(env.get(k, "")).strip().strip("'\"")


def point(solution):
    """{symbol: (kind, rows)} of every variable and equation of the solution: labels, level, marginal."""
    con = sqlite3.connect(solution)
    try:
        out = {}
        for name, kind, dim in con.execute("select name, kind, dim from __symbols").fetchall():
            cols = ", ".join([f'"d{i}"' for i in range(dim)] + ["level", "marginal"])
            rows = [tuple(r[:dim]) + (_v(r[dim]), _v(r[dim + 1])) for r in con.execute(f'select {cols} from "{name}"')]
            out[name] = (kind, rows)
        return out
    finally:
        con.close()


def _v(x):
    return 0.0 if x is None else float(x)


def base_prices(model, solution, env=None):
    """wrtbprice.mod 15-18 (and 28-30):
      DINV(R,T,CUR)$G_RCUR(R,CUR) = 1/COEF_PVT(R,T);
      SOL_BPRICE(R,T,C,S,CUR)$(RCS_COMBAL(R,T,C,S,'LO')$DEM(R,C)) = DINV(R,T,CUR)*EQG_COMBAL.M(R,T,C,S);
      SOL_BPRICE(R,T,C,S,CUR)$(RCS_COMBAL(R,T,C,S,'FX')$DEM(R,C)) = DINV(R,T,CUR)*EQE_COMBAL.M(R,T,C,S);
    with DEM the commodities with a demand projection (ppmain.mod 747: OPTION DEM < COM_PROJ).  A marginal of 0 gives no
    record (an EPS marginal of GAMS would give an EPS price; a solution here does not tell the two apart).
    With ANNCOST LEV also SOL_ACFR, the annual costs as shares of the demand expenditure (cost_shares)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "times_pp"))
    from timesrpt.load import open_case
    return prices_of(open_case(model, solution), env)


def prices_of(db, env=None):
    """base_prices of a model and its solution already in db."""
    rows = []
    for eq, bd in (("EQG_COMBAL", "LO"), ("EQE_COMBAL", "FX")):
        if f"M_{eq}" not in db.sym:
            continue
        rows += db.q(f"""select b.r, b.y, b.c, b.s, g.cur, (1 / v_COEF_PVT(b.r, b.y)) * m.value
                         from RCS_COMBAL b join "M_{eq}" m on m.r = b.r and m.y = b.y and m.c = b.c and m.s = b.s
                         join G_RCUR g on g.r = b.r
                         where b.l = '{bd}' and exists(select 1 from COM_PROJ p where p.r = b.r and p.c = b.c)
                           and m.value <> 0 and v_COEF_PVT(b.r, b.y) <> 0""")
    out = {"SOL_BPRICE": ("parameter", [tuple(r[:5]) + (float(r[5]), None) for r in sorted(rows)])}
    if switch(env or {}, "ANNCOST").upper() == "LEV" and switch(env or {}, "STAGES").upper() != "YES":
        out["SOL_ACFR"] = ("parameter", cost_shares(db, env, rows))
    return out


# wrtbprice.mod 12: SET ANCAT(UC_COST,ITEM) / COST.(INV, FIX, VAR, DAM), TAX.(INVX, FIXX, VARX) /;
ANCAT = {"COST": ("INV", "FIX", "VAR", "DAM"), "TAX": ("INVX", "FIXX", "VARX")}


def cost_shares(db, env, prices):
    """wrtbprice.mod 28-30, the annual costs of the report (cost_ann.rpt with ANNCOST LEV) as shares of the demand
    expenditure at the base prices, for TIMES-MACRO MLF:
      RB(R,T) = SUM((COM_TS(DEM(R,C),S),RDCUR(R,CUR)),SOL_BPRICE(R,T,C,S,CUR)*COM_FR(R,T,C,S)*COM_PROJ(R,T,C))+1-1;
      $IFI NOT %STAGES%==YES
      $IFI %ANNCOST%==LEV SOL_ACFR(R,UC_COST,T)$RB(R,T)=SUM(SYSUCMAP(SYSUC,ITEM)$ANCAT(UC_COST,ITEM),REG_ACOST(R,T,SYSUC)) / RB(R,T);
    SYSUCMAP maps each label to itself (solsysd.v3).  The report is computed again here from the solution."""
    from timesrpt import rptmisc
    from timespp.controls import run_controls
    db.env = dict(env)
    db.ctl, _ = run_controls(dict(db.env))
    rptmisc.run(db)
    db.x("create or replace temp table sol_bprice (r varchar, y varchar, c varchar, s varchar, cur varchar, value double)")
    if prices:
        db.con.executemany("insert into sol_bprice values (?, ?, ?, ?, ?, ?)", [tuple(r[:5]) + (float(r[5]),) for r in prices])
    rb = {(r, y): v for r, y, v in db.q("""
        select b.r, b.y, sum(b.value * v_COM_FR(b.r, b.y, b.c, b.s) * v_COM_PROJ(b.r, b.y, b.c))
        from sol_bprice b
        where in_COM_TS(b.r, b.c, b.s) and in_RDCUR(b.r, b.cur)
        group by b.r, b.y""") if v}
    acost = {}
    if "REG_ACOST" in db.sym:
        r_, y_, u_ = db.cols("REG_ACOST")
        for r, y, u, v in db.q(f'select {r_}, {y_}, {u_}, value from "REG_ACOST"'):
            acost[(r, y, str(u).upper())] = float(v)
    rows = []
    for (r, y), b in sorted(rb.items()):
        for cat, items in ANCAT.items():
            v = sum(acost.get((r, y, i), 0.0) for i in items) / b
            if v:
                rows.append((r, cat, y, v, None))
    return rows


def main(argv):
    if len(argv) < 6:
        print(__doc__)
        return 2
    model, solution, out, folder, run, pj = argv[:6]
    env = json.load(open(pj, encoding="utf-8")).get("switches", {}) if os.path.isfile(pj) else {}
    gp = refpoint.gdxpath(folder)
    written = []
    import time
    by = (run, os.path.abspath(folder), time.strftime("%Y-%m-%d %H:%M:%S"))      # the mark of this run in each file

    def save(stem_dir, stem, symbols):
        files, note = refpoint.write(os.path.join(stem_dir, stem), symbols, by=by)
        for f in files:
            shutil.copy2(f, os.path.join(out, os.path.basename(f)))
            print(f"  wrote {f}")
            written.append(f)
        if note:
            print(f"  {note}")
    # maindrv.mod 123: $IF SET SPOINT $BATINCLUDE spoint.mod 0  (spoint.mod 13-18: 1 or YES, an odd number: SAVEPOINT=1);
    # written here after every solve (see above)
    save(gp, run + "_p", point(solution))
    # maindrv.mod 121-122: $IF NOT %TIMESED%==0  $IF NOT %TIMESED%==YES $BATINCLUDE wrtbprice.mod
    ed = switch(env, "TIMESED").upper()
    loaded = (json.load(open(pj, encoding="utf-8")) if os.path.isfile(pj) else {}).get("base_prices_from")
    if ed and ed not in ("0", "YES") and not loaded:      # (base prices loaded: readbprice.mod made TIMESED YES)
        bp = base_prices(model, solution, env)
        save(folder, "com_bprice", bp)                   # wrtbprice.mod 33: EXECUTE_UNLOAD 'com_bprice',...
        save(gp, run + "_DP", bp)                        # wrtbprice.mod 34: EXECUTE_UNLOAD '%GDXPATH%%RUN_NAME%_DP',...
    json.dump({"written": written}, open(os.path.join(out, "results_written.json"), "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
