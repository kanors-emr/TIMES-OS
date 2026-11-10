# SPDX-License-Identifier: GPL-3.0-or-later
"""Run-file switches -> derived controls (initmty.mod 'CONTROL section', maindrv.mod)."""


class NotPorted(NotImplementedError):
    """Raised when a model uses a TIMES feature that has not been ported yet."""


def given(env, key):
    """A switch as the run file writes it, without quotes."""
    return str(env.get(key, "")).strip().strip("'\"")


def switch(env, key):
    return given(env, key).upper()


def yes(env, key):
    return switch(env, key) == "YES"


def dsc_on(env):
    """The DSC extension is loaded. initmty.mod 453: $IF %DSCAUTO%==YES $SETGLOBAL DSC YES; a DSC set in the run file
    is scoped there and comes before that global, so $SET DSC NO keeps the extension out under DSCAUTO too."""
    return yes(env, "DSC") if given(env, "DSC") else yes(env, "DSCAUTO")


def unsupported(db, what, symbols=()):
    """A feature the port does not have.  Normally this stops the run (NotPorted).  In audit mode (db.audit is a
    list) it is noted and the run goes on, so that one pass lists everything a model needs: every guard of the
    package goes through here, none raises on its own.  symbols: the input that needs the feature, as names (the
    number of records is the whole table) or as {name: number of records concerned}."""
    audit = getattr(db, "audit", None)
    if audit is None:
        raise NotPorted(what + (f": model uses {list(symbols)}" if symbols else ""))
    counts = dict(symbols) if isinstance(symbols, dict) else {n: int(db.card(n)) for n in symbols}
    if counts and any(set(a["symbols"]) == set(counts) for a in audit):
        return                                  # a second guard on the same input: one line in the list
    audit.append({"what": what, "symbols": counts})


# Input that needs no code: descriptions, units and report options.
# PRC_GMAP: initmty.mod 279  PARAMETER PRC_GMAP(REG,PRC,ITEM) 'User-defined groupings of processes' //;
#   declared only; no other statement of TIMES v4.9.8 reads it (Veda writes it for its own reporting).
INERT = {"COM_DESC", "PRC_DESC", "COM_UNIT", "PRC_ACTUNT", "PRC_CAPUNT", "UNITS", "UNITS_COM", "UNITS_CAP", "UNITS_ACT", "UNITS_MONY",
         "RPT_OPT", "ALL_REG", "DATAYEAR", "PASTYEAR", "MODLYEAR", "PRC_GMAP"}
# MACRO input (the TM_ names of initmty.tm and initmty.msa) in a run without MACRO.  The MACRO files are read only
# when MACRO is set:
#   maindrv.mod 26   $   IFI %MACRO%==YES $SET MACRO 'YES' SET TIMESED 0
#   initmty.mod 462  $IFI '%MACRO%'==CSA $SETGLOBAL EXTEND '%EXTEND% MSA'   (and MSA, MLF)
#   initmty.mod 486  $IF %MACRO%==YES $INCLUDE initmty.tm
# so the DD file that gives the data declares the parameter itself, and nothing reads it.  Outside the MACRO files
# TIMES names two of them under $IFI %MACRO%==YES (eqmain.mod 75), and one in a stepped run (TIMESTEP or FIXBOH):
#   solve.stp 154  $IF DEFINED TM_HSX $SETLOCAL TOLR '1E-7' SETLOCAL TOLA 1E-6
MACRO_VALUES = {"YES", "CSA", "MSA", "MLF"}
# Forms of MACRO whose preprocessing is ported but not yet the rest of the run: still refused (the tests of the parts
# ported lift this). MLF is supported (prep/mlf.py, times_eq equations/mlf.jl and negishi.jl, times_rpt mlf.py).
MACRO_IN_PART = set()
MACRO_INPUT = "TM_"
STEPPED_READS = "TM_HSX"
# Names this package spells (in comments or as guards) without reading them as input: inputs_known does not count
# them as known, so that data given for one still stops the run where nothing else accepts it.
NOT_READ = {STEPPED_READS}
_known = None


def macro_run(env):
    return switch(env, "MACRO") in MACRO_VALUES


def macro_unread(n, env):
    """True for a MACRO input that this run of TIMES does not read."""
    return (n.startswith(MACRO_INPUT) and not macro_run(env)
            and not (n == STEPPED_READS and ("TIMESTEP" in env or "FIXBOH" in env)))


# The switches a run file or a DD file may $SET.  Any other name is refused: GAMS may read it, and nothing here would.
# Those this package interprets (each read in the code named by the comment beside its reading):
READ = {"ABS", "ANNCOST", "BOTIME", "CLI", "CM_CALIB", "DAMAGE", "DSC", "DSCAUTO", "DUC", "DYNTS", "ECB", "EOTIME", "ETL", "FIXBOH",
        "GDX_IPRIC", "GDX_IREBND", "LPOINT", "MACRO", "MICRO", "MID_YEAR", "OBJ", "OBJANN", "OBLONG", "REDUCE", "RPOINT", "RUN_NAME",
        "SENSIS", "SPINES", "SPOINT", "STAGES", "STSFLX", "TIMESED", "TIMESTEP", "VARCOST", "VAR_UC", "WAVER"}
# Those that do not change the LP or its solution: they name files, choose reports and listings, or act only on paths
# refused elsewhere.  The TIMES lines:
#   initsys.mod 170-174  $ SET DEBUG NO, DUMPSOL NO, SOLANS NO, ERR_ABORT YES
#   maindrv.mod 24       (MODEL_NAME is set again by TIMES whatever the run file says)
#   maindrv.mod 62       $   IF %DEBUG% == YES       execute_unload "DATADUMP.gdx";
#   rptmain.mod 15       $IF %DUMPSOL%  == 'YES'  $BATINCLUDE dumpsol.%1 %1
#   rptmain.mod 47       $IFI %SOLANS% == YES     $BATINCLUDE solputta.ans S WW, SOW,
#   err_stat.mod 47      $ IF %ERR_ABORT%==NO  $GOTO DONE                     (whether a run with errors goes on)
#   pp_clean.mod 9       $IF %MEMCLEAN%==NO $EXIT                             (clears parameters that no equation reads)
#   pp_clean.mod 25      $IFI NOT '%BENCOST%'=='NO'                           (rpt_objc.rpt: a report)
#   pp_qack.mod 205-206  $IFI '%DEBUG%'==YES $SET XTQA YES;  $IFI NOT '%VDA%%XTQA%'==YESYES $GOTO FINISH    (QA log)
#   rptmain.mod 17       $IFI %VDA% == YES        $SETLOCAL SOLVEDA 1         (SOLVEDA: reports; its uses in equations are under SPINES)
#   rptlite.rpt 16-17    $IF SET RPT_OPT PARAMETER RPT_OPT / %RPT_OPT% /;  $IF %RPT_FLOTS%==COM RPT_OPT('FLO','1')=1;
#   solsetv.v3 183, 204  $ IFI NOT %PUNITS%==YES $EXIT;  $IFI %RPT_TOP%==YES ...  (reports)
#   rptmain.rpt 80       $IF NOT %SUPZERO%==YES                               (ANSWER report files)
#   initsys.mod 19       $ IF SET RunTimes $TITLE %SYSTEM.TITLE% -- %TMP% (v%RunTimes%)
#   equ_ext.mlf 87       $ SETCOMPS %KESTREL% X1 X2 .                         (picks a solver)
#   solve.stc 13, solve.msa 169   MCA1, QSF: on the stochastic and MSA paths, refused
# VEDAVDD (in the run file), SCENARIO_NAME (in the DD files): Veda's own switches; no line of TIMES has these names.
INERT_SWITCHES = {"BENCOST", "DEBUG", "DUMPSOL", "ERR_ABORT", "KESTREL", "MCA1", "MEMCLEAN", "MODEL_NAME", "PUNITS", "QSF", "RPT_FLOTS",
                  "RPT_OPT", "RPT_TOP", "RUNTIMES", "SOLANS", "SOLVEDA", "SUPZERO", "VEDAVDD", "SCENARIO_NAME", "XTQA"}
# Switches that change the model at some values, which this package does not have: taken at the values that leave it as
# TIMES builds it here, refused at any other.
#   initmty.mod 468      $IFI '%VDA%' == YES $SETGLOBAL EXTEND '%EXTEND% VDA'
#   maindrv.mod 114      $   IF %SOLVE_NOW% == NO     $GOTO SKIPTOEND
#   setglobs.gms 13      $ IF NOT %DATAGDX%==YES $GOTO SYSD                   (the filter of domain violations, domfilter.py:
#                        DATAGDX NO is taken where there is no domain violation to filter)
#   initmty.mod 489      $ IF %DATAGDXI%==YES $SETGLOBAL DATAGDX YES
#   initmty.mod 425      $IFI %VALIDATE%==YES IF(ALTOBJ>1,ABORT 'VALIDATE Cancels Alternative Objective'); ALTOBJ=0;   (and 26 more lines)
#   eqcumflo.mod 39, eqcumcom.mod 26   ) / %CUFSCAL%,  ) / %CUCSCAL%
ONLY_AT = {"VDA": {"YES"}, "SOLVE_NOW": {"YES"}, "DATAGDX": {"YES", "NO"}, "DATAGDXI": {"YES"}, "VALIDATE": {"NO", ""}, "CUFSCAL": {"10"},
           "CUCSCAL": {"1000"}, "SHARETOL": {"9E-5"}, "DEF_IEBD": {"10"}, "TRIVINT": {"6"}, "DISCSHIFT": {"0"}, "RETIRE": {"YES"},
           "PGPRIM": {"ACT"}, "OBMAC": {"YES"}, "G2X6": {"YES"}, "GAMS_CGI": {"NO"}}
#   pp_qafs.mod 76       $IF NOT %SHARELAX%==NO LOOP(RP_GIC(R,P,CG,IO,C)$Z, ...   (the relaxation of FLO_SHAR, prep/flows.py)
#   fillvint.gms 15      $IF %VINTOPT%==2 PRC_SIMV(PRC_VINT(R,P)) = NOT PRC_MAP(R,'STG',P);
#   prep_ext.vda 42      $IF %VINTOPT%==1 $BATINCLUDE fillvint VDA_FLOP R 'P,CG,TS' X_RPGS
NOT_AT = {"SHARELAX": {"NO"}, "VINTOPT": {"1", "2"}, "SHELL": {"ANSWER"}, "PREP_ANS": {"YES"}, "INTEXT_ONLY": {"YES"}, "MERGE": {"YES"},
          "CHP_MODE": {"YES"}, "MCA": {"YES"}}


def switches_known(db):
    """Every $SET of the run file and the DD files: taken when this package reads the switch, or it changes nothing, or
    its value leaves the model as it is built here; otherwise refused, naming the line."""
    import os
    seen = set()
    for src, name, value in getattr(db, "user_sets", ()):
        v = str(value).strip().strip("'\"").upper()
        if name in READ or name in INERT_SWITCHES or (name in ONLY_AT and v in ONLY_AT[name]) or (name in NOT_AT and v not in NOT_AT[name]):
            continue
        if model_macro(db, name):
            continue
        if (name, v) not in seen:
            seen.add((name, v))
            unsupported(db, f"run-file switch {name}" + (f"={v}" if name in ONLY_AT or name in NOT_AT else "")
                        + f": not known to this implementation (in {src})")
    # initmty.mod 496: $ IF EXIST %RUN_NAME%~data.gdx $SET TMP %RUN_NAME%~data    (loaded on top of the DD files)
    data = given(db.env, "RUN_NAME") + "~data.gdx"
    if os.path.isfile(os.path.join(getattr(db, "case_dir", "."), data)):
        unsupported(db, f"{data} in the run folder: TIMES loads it on top of the DD files, this implementation does not")


_times_names = None


def model_macro(db, name):
    """A $SET of the model's own: no file of TIMES reads the name (times_switches.json, from the TIMES source), and
    the model's DD files or code files use it as %name% (a label list for their keys, say), where the reader has put
    its value.  A name used nowhere stays refused: most likely a switch of TIMES misspelt."""
    global _times_names
    import os, json, re
    if _times_names is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "times_switches.json")) as f:
            _times_names = set(json.load(f)["names"])
    if name in _times_names:
        return False
    used = getattr(db, "macros_used", None)
    if used is None:
        used = db.macros_used = set()
        for p in getattr(db, "input_files", ()):
            with open(p, "rb") as f:
                used.update(m.decode("latin-1").upper() for m in re.findall(rb"%([A-Za-z_][A-Za-z_0-9]*)%", f.read()))
    return name in used


def inputs_known(db):
    """Stop when a DD file gives data for a set or parameter that no module of this package mentions.

    The guards (require_empty) name the features that are known and not ported.  This is the net below them: an
    attribute of an extension that was never looked at (the grid parameters GR_*, for instance) would otherwise be
    read and ignored, and the model would solve to another optimum without a word."""
    global _known
    import os, re, glob
    if _known is None:
        _known = set()
        for f in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "**", "*.py"), recursive=True):   # prep/ too
            _known.update(re.findall(r"[A-Z][A-Z0-9_]*", open(f, encoding="utf-8").read()))
        _known -= NOT_READ
    new = sorted(n for n in getattr(db, "dd_names", ()) if n not in _known and n not in INERT and not macro_unread(n, db.env)
                 and n in db.sym and db.sym[n].kind != "scalar" and db.card(n) > 0)
    if new:
        if getattr(db, "audit", None) is not None:
            unsupported(db, "input not known to this implementation (data given in the DD files)", new)
        else:
            raise NotPorted("input not known to this implementation (data given in the DD files): " + ", ".join(new))


def run_controls(env):
    """(ctl, ALTOBJ) of a run from its $SET switches: the objective form and the controls the steps read.
    Also used by the report writer (times_rpt), which has the switches of the run but not the preprocessor's db.
    May set env['VARCOST'] = 'LIN' (OBLONG with OBJ ALT), as GAMS does."""
    obj = str(env.get("OBJ", "")).upper()
    altobj = 1.0
    if obj == "STD":
        altobj = 0.0
    elif obj == "ALT":
        altobj = 2.0
    elif obj == "LIN":
        altobj = 3.0
    if yes(env, "VALIDATE"):
        altobj = 0.0
    oblong = yes(env, "OBLONG") or obj == "MOD"
    # %CTST%: '' | '**EPS' | '**0'   (applied as  x%CTST%)
    ctst = ""
    if obj == "ALT":
        ctst = "eps"
    if oblong:
        ctst = "zero"
    if obj == "LIN":
        ctst = "eps"
    if oblong and obj == "ALT":
        env["VARCOST"] = "LIN"
        altobj = -2.0
    ctl = dict(OBJ=obj, OBLONG=oblong, CTST=ctst,
               MID_YEAR=yes(env, "MID_YEAR"), REDUCE=given(env, "REDUCE"),       # as GAMS compares it: NO, YES, other (prep/reduce.py)
               VALIDATE=yes(env, "VALIDATE"), VDA=True,
               VAR_UC=yes(env, "VAR_UC"), VARCOST=str(env.get("VARCOST", "")).upper(),
               BOTIME=int(float(env.get("BOTIME", 1850))), EOTIME=int(float(env.get("EOTIME", 2200))))
    return ctl, altobj


def derive(db):
    inputs_known(db)
    switches_known(db)
    # executable statements in DD files and the run file that the reader could not apply (gamsdata.Reader)
    for src, text, why in getattr(db, "dd_unsupported", ()):
        unsupported(db, f"a statement in {src} that the reader does not execute ({why}): {text[:160]}")
    env = db.env
    db.ctl, altobj = run_controls(env)
    db.s["ALTOBJ"] = altobj
    # initmty.mod 469: $IFI '%ABS%' == YES $SETGLOBAL EXTEND '%EXTEND% ABS'   (the ancillary balancing services, prep/abs.py)
    db.ctl["ABS"] = yes(env, "ABS")
    # initmty.mod 466: $IFI '%CLI%' == YES $SETGLOBAL EXTEND '%EXTEND% CLI'   (the climate module, prep/cli.py)
    db.ctl["CLI"] = yes(env, "CLI")
    for k in ("DAMAGE", "ETL", "ECB", "MICRO"):
        if yes(env, k):
            unsupported(db, f"run-file switch {k}=YES")
    # Stochastic TIMES (prep/stochastic.py), maindrv.mod 33-36:
    #   $IFI %STAGES% == YES $SET STAGES YES
    #   $IFI %SENSIS% == YES $SET STAGES Yes     (SENSIS: the $IFI code of STAGES runs, the case-sensitive $IF does not)
    #   $IFI %SPINES% == YES $SET STAGES YES     (SPINES: the capacity of SOW '1' in every SOW, recurrin.stc 52-179)
    #   $IF  %STAGES% == YES $SET SENSIS 'NO' SET OBJANN NO     (the objective is the expected value)
    stages = "YES" if yes(env, "STAGES") else ""
    if yes(env, "SENSIS"):
        stages = "Yes"
    if yes(env, "SPINES"):
        stages = "YES"
    if stages:
        env["STAGES"] = stages
    db.ctl["SPINES"] = yes(env, "SPINES")
    db.ctl["STAGES"] = bool(stages)             # $IFI %STAGES%==YES
    db.ctl["STAGES_YES"] = stages == "YES"      # $IF %STAGES%==YES (the model of every SOW at once)
    db.ctl["SENSIS"] = stages == "Yes"          # one deterministic model per SOW (solve.stc 18-69, sensis.stc)
    if db.ctl["STAGES"]:
        if db.ctl["STAGES_YES"]:
            env["OBJANN"] = "NO"
        # stages.stc 9: $IF %MACRO%==YES $ABORT Stochastic MACRO Not Implemented - aborted.
        if macro_run(env):
            unsupported(db, "MACRO with STAGES=YES (TIMES aborts: Stochastic MACRO Not Implemented)")
        # the stepped run (solve.stp) with STAGES: not ported
        for k in ("TIMESTEP", "FIXBOH"):
            if given(env, k):
                unsupported(db, f"run-file switch {k} with STAGES=YES (a stochastic myopic run)")
    if macro_run(env) and (switch(env, "MACRO") != "MLF" or "MLF" in MACRO_IN_PART):
        unsupported(db, "run-file switch MACRO=" + switch(env, "MACRO"))
    # MLF opens only through readbprice.mod 20 (maindrv.mod 28-29: TIMESED not NO and not 0); without it GAMS stops
    # at compile time (Unknown symbol VAR_UTIL)
    if switch(env, "MACRO") == "MLF" and switch(env, "TIMESED") in ("", "NO", "0"):
        unsupported(db, "MACRO MLF without TIMESED: TIMES needs the base prices of a reference run "
                        "($SET TIMESED YES or the run's name)")
    # TIMESED: the base prices of an earlier run (setglobs.gms 339: $SETGLOBAL TIMESED 0)
    #   maindrv.mod 28  $   IFI NOT %TIMESED%==NO
    #   maindrv.mod 29  $   IF NOT %TIMESED%==0 $BATINCLUDE readbprice.mod
    # readbprice.mod loads them from com_bprice (YES) or from <name>_DP / <name> (any other value, as Veda writes it) and
    # then sets TIMESED 'YES': elastic demands (prep/elastic.py). NO (and 0) solve without them; NO only writes this
    # run's prices afterwards (wrtbprice.mod), which does not change the model.
    #   maindrv.mod 25  $   IFI %MICRO%%TIMESED%==YES0 $SET TIMESED YES     (MICRO: refused above)
    from .prep.elastic import readbprice
    readbprice(db)
    # bnd_ire.vda: trade flows fixed (GDX_IREBND) or priced (GDX_IPRIC) from an earlier run's GDX, when that GDX exists
    for k in getattr(db, "trade_gdx", ()):
        unsupported(db, f"run-file switch {k} (trade bounds or prices from an earlier run's GDX, bnd_ire.vda)")
    # TIMESTEP (myopic run, solve.stp): the steps are prepared by prep/myopic.py; STEPPED implies VAR_UC (initmty.mod)
    db.ctl["TIMESTEP"] = None
    if "TIMESTEP" in env:
        db.ctl["TIMESTEP"] = int(float(str(env["TIMESTEP"]).strip("'\"")))
        db.ctl["VAR_UC"] = True
        if str(env.get("OBJANN", "")).strip("'\"").upper() == "YES":
            unsupported(db, "OBJANN=YES with TIMESTEP (annualised objective in a myopic run)")
    # FIXBOH (initmty.mod 444: $IF SET FIXBOH IF(NOT ALLYEAR('%FIXBOH%'), ABORT 'Invalid Control: FIXBOH'); then
    # $SETGLOBAL STEPPED - and VAR_UC YES): the periods up to the year fixed at the solution LPOINT names (prep/fixboh.py)
    db.ctl["FIXBOH"] = None
    if given(env, "FIXBOH"):
        try:
            db.ctl["FIXBOH"] = abs(float(given(env, "FIXBOH")))
        except ValueError:
            raise NotPorted(f"Invalid Control: FIXBOH ({given(env, 'FIXBOH')} is not a year)")
        db.ctl["VAR_UC"] = True
        # spoint.mod 42: $IF NOT SET LPOINT $GOTO RUNNAME (no point loaded: the fixed columns at their level, 0)
        if not given(env, "LPOINT"):
            unsupported(db, "run-file switch FIXBOH without LPOINT (the periods fixed at a solution that is not loaded, spoint.mod)")
        if "TIMESTEP" in env:
            unsupported(db, "run-file switches FIXBOH and TIMESTEP together (a myopic run from a loaded solution, solve.stp)")
    # SPOINT (spoint.mod): 1 (or YES) only saves the solution point after the solve; 2 and 3 load one before it
    if "SPOINT" in env and str(env["SPOINT"]).strip("'\"").upper() not in ("1", "YES"):
        unsupported(db, f"run-file switch SPOINT={env['SPOINT']} (loading a solution point)")
    # RPOINT (initmty.mod 441: $SETGLOBAL RPOINT NO): the run reports a loaded point and does not solve
    #   maindrv.mod 105  $   IF NOT %RPOINT%==NO $GOTO REPORT
    if switch(env, "RPOINT") not in ("", "NO"):
        unsupported(db, f"run-file switch RPOINT={given(env, 'RPOINT')} (a report of a loaded solution point, no solve)")
    # LPOINT (spoint.mod 42-47): execute_loadpoint '<LPOINT>_p.gdx', the levels and marginals of an earlier run as the
    # starting point; bounds are not loaded, so on its own the model is the same.  With REG_BDNCAP the loaded point
    # does change it: spoint.mod (after LABEL FINISH) fixes or bounds VAR_NCAP up to the years of REG_BDNCAP at the
    # loaded levels (prep/spoint.py).  Without a loaded point TIMES clears REG_BDNCAP ($IF NOT %LOAD%==2 $CLEAR
    # REG_BDNCAP), as here.
    return db.ctl


def ctst(db, x):
    """x%CTST%  ->  x, x**EPS or x**0 (GAMS: x**0 = 1, 0**EPS = 0)."""
    c = db.ctl["CTST"]
    if c == "":
        return x
    return 1.0   # x**0 = 1; x**EPS = 1 for x>0
