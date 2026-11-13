# Changelog

## 1.0.3 (November 2026): FLO_FUNCX shapes on capacity flows and with repeated investments

#### Model features
- `FLO_FUNCX` with the group `CAPFLO` (a shape by age on a capacity-related flow `NCAP_COM`) is supported: the
  shape averaged over each period scales the flow (`COEF_CIO`), and `NCAP_CLAG` on the same flow takes precedence,
  as in TIMES (`coef_shp.mod`; `times_pp/timespp/prep/coefficients.py`, `flo_shape` and `clag_shape`). Before, a
  model with it stopped as UNSUPPORTED.
- `FLO_FUNCX` on a process invested in more than once within a period (a lifetime shorter than the period,
  `COEF_RPTI` > 1) is supported: such a vintage takes the shape averaged over its whole lifetime, as in TIMES
  (`times_pp/timespp/prep/coefficients.py`, `flo_shape`). Before, a model with it stopped as UNSUPPORTED.

#### Agreement fixes
- `FLO_FUNCX` given on a group that is not a commodity (`CAPFLO`, `ACT`) is kept for a process that is not
  vintaged, as TIMES keeps it (`prep_ext.vda`); only a shape whose first index is a commodity is dropped there
  (`times_pp/timespp/prep/extensions.py`). Before, every `FLO_FUNCX` of such a process was dropped.

#### Still not supported
- The capacity transfer of `NCAP_OCOM` asked for by `FLO_FUNCX(r,'0',p,'CAPFLO',c)` = 3 stops with its own message
  (`times_pp/timespp/prep/coefficients.py`, `coef_shp`).

Each was compared with TIMES in GAMS on the DemoS_012 example with such shapes added: the same preprocessed tables
and the same matrix.

## 1.0.2 (November 2026): a run with FIXBOH reports its fixed periods; the remaining report options

#### The Veda result files
- The Veda result files of a run with `FIXBOH` lacked most of the fixed periods: activities and flows that are in
  none of the equations of the run, and every equation level and marginal of those periods (commodity balances,
  user constraints, peak). TIMES keeps for them the levels and marginals of the solution point the run loads, and
  reports them. They are now put under the solution before the Veda files and the solution point for later runs
  (`<run>_p`) are written, less what TIMES clears of the loaded point (`times_rpt/timesrpt/loadedpoint.py`,
  `TIMES.py`). On a FIXBOH run of the DemoS_012 example, the solution of GAMS cut down to the model and completed
  this way gives the Veda file of GAMS, every attribute, row and value.
- The cost of elastic demands is written to the Veda files (`Cost_Els`): it was computed and counted in `Cost_NPV`,
  `Reg_wobj` and `Reg_ACost`, and left out of the file (`times_rpt/timesrpt/vd.py`). On three elastic runs of the
  DemoS_012 example the file written from the solution of GAMS has the rows and values of the Veda file of GAMS.
- The report options that were named as not covered are written: the topology (`RPT_OPT('FLO','7')` or
  `$SET RPT_TOP YES`: `PAR_Top`); flows at ANNUAL (`$SET RPT_FLOTS ANNUAL`, and a negative
  `RPT_OPT(<commodity type>,'3')`; an energy type with only its option `'3'` set now also reports its flows at the
  commodity timeslices, as TIMES does); the levelized cost with the credit of the ENV commodities
  (`RPT_OPT('NCAP','1')` below 0) and with the peak capacity credit (above 1); the cost-benefit indicators of new
  capacity (`$SET BENCOST YES`: COST, CGAP, GGAP, RATIO and GRATIO of `VAR_NcapR`), without the ranging information
  of the solver and without the costs of capacity-related flows, which the run report names when a model has them
  (`times_rpt/timesrpt/rptmisc.py`, `rptobjc.py`, `switches.py`). Each is compared with the Veda file of GAMS on
  the DemoS_012 example with the option set. Damage costs (`Cost_Dam`) are not written.
- The levelized cost (`RPT_OPT('NCAP','1')`) took no account of the second energy outputs of electricity and
  heating plants: the sets of those plants were read empty. They are read from `PRC_MAP`, as TIMES sets them before
  its reports (`times_rpt/timesrpt/rptmisc.py`).

#### Runs and the comparison with TIMES in GAMS
- `run <folder> --no-solve --check` on a run with `FIXBOH` built the model and did not compare its matrix with the
  one of GAMS (the report said the check was skipped, as for a myopic run). The matrix is now written and compared,
  as it is when the run is solved (`times_eq/src/runcase.jl`).
- The run report: the verdict `BUILT` is explained with the others; a myopic run of several steps is told to use
  `--check inline`, the only way its matrices are compared; a run with `FIXBOH` is no longer called "a myopic run:
  1 steps"; a model built and not solved reads "built, not solved"; the build of a run in steps with `--no-solve` is
  timed as "steps", not under "other"; the compile seconds are said to be summed over the threads; the time limit
  of the solves and `highs.log` are left out when nothing was solved (`TIMES.py`).
- A solved run with `FIXBOH` that is compared with a GAMS run already in its folder was called `DIFFERENT` for its
  rows, although every check agreed: the result file of GAMS also holds the rows of the fixed periods, loaded with
  the solution point, and they were counted as missing here. They are now named as what they are, and the run is
  `SAME` (`TIMES.py`).
- A run that reads the results of an earlier run (`FIXBOH`, `LPOINT`, `TIMESED`) reads those this implementation
  wrote, while a GAMS run already in the folder read those GAMS wrote. Where the earlier run has several optimal
  solutions, the two are different points, and the periods fixed at them make two different models: the objectives
  then differ without any difference in the model. Such a run is no longer called `DIFFERENT`: its verdict is
  `SOLVED`, with the two objectives and the reason in the report. `--check` compares the two on the same results
  (`TIMES.py`).
- The verdict names the solver that solved (`CPLEX finds the GAMS objective`), not always HiGHS; the sizes of a step
  no longer run together in the report; a run of one step no longer speaks of "1 steps" (`TIMES.py`,
  `times_eq/src/runcase.jl`).
- With its output sent to a file on Windows, `setup` (or a run) stopped with `UnicodeEncodeError` when a message it
  printed held a character the file's encoding lacks, hiding the message itself (a failed Julia step, for one). Such
  a character is now replaced (`TIMES.py`).

- The models built are the same as in 1.0.1: the 17 cases of the open reference models are `SAME` against TIMES in
  GAMS, entry by entry.

## 1.0.1 (November 2026): a shorter setup

#### Setup
- `setup` takes about half the time it took in 1.0.0 (on a Windows desktop 13.5 to 6.75 minutes), and its
  largest compile needs about 5 GB of memory instead of about 10 GB; a change in `times_eq/src` is compiled again
  in less than half the time too. Less code is compiled for the same models:
  - the equations of stochastic TIMES (`STAGES`, `SPINES`) are compiled ahead in an add-on package of their own
    (`times_eq/addons/TimesEqStochastic`), which `setup` compiles after TimesEq. A run of a model with `STAGES`
    or `SPINES` that finds it missing or out of date compiles it first (a few minutes, once), and says so;
  - the equations built in threads share one compiled task instead of one for each equation family
    (`times_eq/src/TimesEq.jl`);
  - the terms of user constraints are compiled once for each kind of expression, instead of once for each way
    a constraint calls them (`times_eq/src/equations/userco.jl`).
- With Julia 1.11, a run of a model with `STAGES` or `SPINES` no longer compiles part of the model at every run
  (`times_eq/src/model.jl`).
- `check` shows whether the stochastic add-on is compiled.

#### Runs
- A time limit beyond what the system's waits accept (a run file's `OPTION RESLIM` times the solves a run allows, of
  about 4 million seconds or more) stopped the timer with `OverflowError: timeout value is too large` on Windows; the
  run went on without a limit. Such a limit now counts as no limit, without the message (`TIMES.py`).

- The models built are the same as in 1.0.0.

## 1.0.0 (November 2026): the public release, under the GNU General Public License

- TIMES Open Stack (TIMES-OS) is released under the GNU General Public License, version 3 or later, the licence of
  TIMES (`LICENSE`). Its home is https://github.com/kanors-emr/TIMES-OS.
- The setting that starts Julia after the preprocessor instead of beside it is `TIMES_EARLY=0` (it was
  `TIMES_JULIA_EARLY`; `TIMES.py`).
- The comparison with TIMES in GAMS is part of the runner: `run <run folder> --check` runs TIMES in GAMS with CONVERT
  and compares the two matrices entry by entry (SAME or DIFFERENT); `verify <result folder>` compares a finished case
  again; `--gams run` also solves in GAMS and compares the objectives; `--times <folder>` gives the TIMES source for a
  run; `run <run folder> --no-solve --check` compares the matrices without a solve. It needs GAMS and the TIMES
  source, which is not part of this repository (`docs/verification.md`); without them `--check` stops before
  anything is run, with exit status 2, and says which is missing.
- `setup` fetches the TIMES source v4.9.8 from IEA-ETSAP's repository into `TIMES_model-v4.9.8/` when it finds GAMS
  and no source of that version (with git, or as the tag's zip file); `--no-times-source` turns it off.
- `setup` installs only open-source packages by default. The GDX packages (`requirements-gams.txt`: gamsapi and
  gamspy_base, the latter under the GAMS licence), which serve only the comparison with GAMS, `--lp` and `--jacobian`,
  are installed when GAMS is found, or with `setup --gdx`.
- `--bundle` takes only the reports, the logs, the run file, the DD files and the solver options, no other file of the
  run folder.
- `setup` reports a Gurobi version that pip does not offer as a note, not a failure.
- The models built are the same as in 0.5.2.

## Before the public release

The versions below were shared with reviewers before the public release; their history is kept here as it was.

### 0.5.2 (November 2026): rows that the data make infeasible

- A row left with no column whose constant does not satisfy it (`EQE_COMBAL(...)..  0 =E= 2.685`: a demand that no
  process can supply) now stops the build, as it stops TIMES in GAMS ("equation infeasible due to rhs value"), with
  every such row listed. Before, such rows were left out without a word, and the model built had no sign of the
  infeasibility. A constant of at most 1e-15 counts as zero, as in GAMS. Rows of this kind that the constant
  satisfies (`0 =G= -1`) are still left out, as in GAMS.
- The new verdict `INFEASIBLE` (exit status 5) says so: the model's data cannot be met; not a defect.

### 0.5.1 (November 2026): more of GAMS in the input files

#### Input

- Label ranges with a text before the number in data keys (`'R'.2030.'P'.S-H01*S-H06 -1`): one record per label,
  as in GAMS. Before, such a range was read as one label and its records were lost.
- Label lists given by a `$SET` of the run file and used in data keys (`$SET NIGHT (W-H01*W-H06,S-H01*S-H05)`,
  then `...%NIGHT%.UP 3`).
- `#set` in data (every member of a set), explanatory texts without quotes, `$ONTEXT` blocks inside data.
- A file of the model's own GAMS code that the run file includes (`$BATINCLUDE myfixes.gms`) is read where it
  stands, as a DD file is; before, it was refused. Its statements, and those of DD files, may now be `LOOP`s and
  assignments that use `SAMEAS`, `SUM` / `PROD` / `SMAX` / `SMIN`, other parameters and sets, as in
  `LOOP(UCOFF, UC_RHSRT(R,UC_N,ALLYEAR,LIM)$SAMEAS(UCOFF,UC_N) = 0;)` (`times_pp/timespp/ddexec.py`; what is read:
  `times_pp/README.md`, "What a DD file may contain").
- A `$SET` of the run file whose name no file of TIMES reads, used as `%name%` in the DD files (a label list of the
  model's own), no longer stops the run as an unknown switch. A name used nowhere still does (a misspelt switch).
- `$SET DATAGDX NO` is taken when the input has no domain violations (TIMES filters them only with `DATAGDX YES`;
  with violations the run stops and names them).

#### The same model as TIMES

- A run with `FIXBOH` or `TIMESTEP` and balancing services (the ABS extension): the `EQ_BS*` equations are written
  for the periods of the window only, as in TIMES (`%R_T%` / `%R_V_T%` in `equ_ext.abs`); before, they were also
  written for the fixed periods, with their variables (`times_eq/src/model.jl`).
- A decommissioning cost given as 0 (`NCAP_DCOST`, an EPS value in GAMS) keeps its zero entry for `VAR_NCAP` in
  `EQ_OBJINV`, as in TIMES (`times_pp/timespp/prep/objective.py`).
- `--no-solve` with `FIXBOH`: the periods before the window are fixed at the loaded solution point and relaxed as in
  a solve, no longer at zero.
- `--no-solve` with `TIMESTEP` (a run in steps): each step starts from its own capacity bounds, as in a solve; before,
  the bounds relaxed in one step were carried into the next (`times_eq/src/runcase.jl`).

### 0.5.0 (November 2026): TIMES v4.9.8, SENSIS and SPINES, quicker myopic and FIXBOH runs, storage flow costs in the results

#### Before you update

- The implementation now follows TIMES v4.9.8 (ETSAP's maintenance release of 4 November 2026). Run
  `python TIMES.py setup` once after `git pull`: when the TIMES source it finds is another version, it fetches v4.9.8
  into `TIMES_model-v4.9.8` beside it (an older copy is left as it is) and uses it for the comparison with GAMS;
  `setup --times <folder>` keeps the folder you give. Without git it says which version it found and which one the
  implementation follows.
- `setup` also compiles the parts of the package that now start earlier (an environment set up before still works,
  without those savings).

#### The same model as TIMES v4.9.8

- Two quality checks of TIMES v4.9.8 that end the run before the model is built, with the messages of its
  `QA_CHECK.LOG` and `*** FATAL QA ERROR - Check the QA_CHECK.LOG file for details ***`: a process with a `PRC_ACTFLO`
  of 0 for a commodity of its primary group, and a process with an `ACT_BND` LO above its UP on a timeslice of its
  own level (`times_pp/timespp/prep/sets.py`).
- Past investments with `NCAP_PASTY`: spread on every year that has one, not only on the past years of the DD files,
  over a whole number of years (`NCAP_PASTY` rounded), so the whole investment is kept
  (`times_pp/timespp/prep/periods.py`).
- CHP processes: an `NCAP_CDME` given as 0 is taken as absent; the slope uses the larger of `NCAP_CDME` and
  `NCAP_BPME` (a back-pressure efficiency of 0 no longer stops the run); a heat-to-power ratio given as 0 gives an
  activity-to-flow factor of 1 and an output share of 0 (EPS) for the heat, as in TIMES (`times_pp/timespp/prep/chp.py`).
- The risk-free rate `G_RFRIR` is used only where it is above 0; elsewhere the discount rate stays
  (`times_pp/timespp/prep/costs.py`).
- The operating life in retirement (`NCAP_OLIFE`, EQL_SCAP) counts as at least one year: a life given as 0 no longer
  stops the run (`times_eq/src/equations/retire.jl`).
- The capacity-bound warning of the QA log also names `NCAP_BND` with LO above UP (`times_pp/timespp/prep/capacity.py`).

#### TIMES features now covered

- **`$SET SENSIS YES`**: one deterministic model for each state of the world (SOW) of the first period, built and
  solved in turn in one run, each reported under its SOW, as TIMES does; with HiGHS (the default) or a solver of your
  GAMS (`--lp`), and with the climate module (`$SET CLI YES`). Its first model is built in seconds. Not supported
  (named in the run report): uncertain inputs other than `S_COM_PROJ` and `S_COM_TAX` with `SENSIS`.
  Code: `times_eq/src/runcase.jl` (the solves in turn), `times_eq/src/stochastic.jl`, `times_eq/src/equations/cli.jl`,
  `times_pp/timespp/prep/stochastic.py`, `times_rpt/timesrpt/stochastic.py`.
- **`$SET SPINES YES`**: the capacity and its investment, fixed and salvage costs of the first SOW in every SOW, the
  cumulative constraints as expected values with `SOLVEDA` 1; its Veda files hold the expected values, as TIMES reports
  them. Not supported (named in the run report): `SPINES` with discrete capacity, retirements or `PRC_DYNUC`, and with
  `SOLVEDA` 1 cost bounds, `UC_TIME` or cumulative user constraints by period or timeslice. Code:
  `times_eq/src/stochastic.jl`, `times_eq/src/equations/objann.jl`, `cumcom.jl`, `cumflo.jl`, `userco.jl`, `cpt.jl`,
  `times_rpt/timesrpt/stochastic.py`, `solflo.py`.
- Several SOWs in the first period are taken with `SPINES` or `SENSIS`; with `STAGES` alone they are still refused.
- **`FIXBOH` with dynamic bounds by process** (`UC_DYNBND`, `PRC_DYNUC`), as TIMES in GAMS takes them; they were
  refused. Code: `times_pp/timespp/prep/fixboh.py`, `times_eq/src/equations/ucrtp.jl`.

#### The same model as TIMES in more cases

- `$SET DSC NO` in a run file keeps the discrete capacity extension out under `DSCAUTO YES` too
  (`times_pp/timespp/controls.py`, `times_pp/timespp/prep/dsc.py`).
- `NCAP_ICOM` of a process with a negative `NCAP_ILED`: the commodity flows are in the period before the investment,
  not in its own period (`times_pp/timespp/prep/coefficients.py`, `objective.py`).
- A `PRC_ACTFLO` given as 0 (EPS under `$ONEPS`) gives its `FLO_SUM` and `IRE_FLOSUM`, and so its `EQ_PTRANS`
  (`times_pp/timespp/prep/flows.py`); an availability coefficient given as EPS times EPS stays EPS in
  `EQ_CAPACT` (`times_eq/src/equations/capact.jl`).
- A fixed or investment cost whose tax and subsidy cancel exactly (`NCAP_FTAX` equal to `NCAP_FSUB`, `NCAP_COST` equal
  to `NCAP_ISUB`) gives no coefficient; the model had an entry of 0 there, which did not change the solution
  (`times_pp/timespp/prep/objective.py`).
- Under `FIXBOH` or in a stepped run: start-up variables by type (`VAR_UPT`) are fixed outside the window, and a user
  constraint with a right-hand side of EPS in a relaxed region and period takes the absolute tolerance where `UC_RN`
  lists it (`times_eq/src/steps.jl`, `times_pp/timespp/prep/fixboh.py`).

#### Input files

- A key that starts with a number and a dot before a quoted label (`2030.'CO2-PPM' 410`) is read as TIMES in GAMS
  reads it, the labels `2030` and `CO2-PPM`; it was read as a value, and the run stopped
  (`times_pp/timespp/gamsdata.py`).
- A run that reads the results of an earlier run (`LPOINT`, `FIXBOH`, `TIMESED`) and does not find them where TIMES
  looks now looks where the earlier run left them: the folders given with the new option `--points <folder>` (or
  `TIMES_POINTS`), then the runner's result folders, `<--out folder>\<run>` and `runs\<run>`. Veda copies only the GDX
  files of the earlier run into the later one's folder, so a `FIXBOH` run made with Veda stopped there before. The
  message when they are not found names the run that writes them and the option `--points`
  (`times_pp/timespp/refpoint.py`, `TIMES.py`).

#### Speed

- A myopic run (`TIMESTEP`) or a run with `FIXBOH` no longer writes `model.db3`: its tables go into `model_parquet` as
  for any run, and the tables of its steps into a small file beside it, `model_steps.db3`, which the equations wait
  for instead of the whole `model.db3`: on a model of 6.7 million rows (`FIXBOH`) the solver starts about a minute
  sooner; `tools/pq2db3.py` puts the step tables back when it makes `model.db3` (`times_pp/timespp/stream.py`,
  `export.py`, `tjb.py`, `times_eq/src/data.jl`, `tjb.jl`).
- The `FIXBOH` step of a large model takes seconds, not minutes, when capacity bounds are relaxed: 13 s against 11
  minutes on a model of 6.7 million rows (`times_pp/timespp/prep/fixboh.py`).
- Julia is started as the preprocessor starts and loads its packages while it runs: about 1.5 s less in every run
  (`TIMES_EARLY=0` starts it after the preprocessor, as before). The matrix of `--jacobian` (about 1 s) and the
  calibration of TIMES-MACRO MLF (about 5 s, when Ipopt is installed) are compiled with the package
  (`TIMES.py`, `times_eq/src/TimesEq.jl`, `times_eq/ext/`).
- The models built are the same in every case above.

#### Results and reports

- The flow costs of a storage process (`FLO_COST` on what it stores, `FLO_DELIV` on what it releases) are reported
  from its storage flows, as TIMES in GAMS reports them: the input times `FLO_COST`, the output times `STG_EFF` and
  `FLO_DELIV`. With `RPT_OPT('OBJ','1')` such a run stopped before the Veda result files were written; without it the
  annual flow costs of such processes were left out (`times_rpt/timesrpt/eqobjvar.py`).

### 0.4.0 (November 2026): stochastic TIMES, the run file checked, Python 3.11 and Julia 1.11

#### Before you update

- **Python 3.11 or newer and Julia 1.11 or newer are required** (the preprocessor would not start on Python 3.10, and
  Julia 1.10 was never tested). After `git pull`, run `python TIMES.py setup` again; it says what to update.
- **The run file is checked** as the DD files are. A switch this implementation does not know, an include other than the
  DD files and the files of TIMES (also of a file that does not exist), an executable statement other than `OPTION`,
  and a `$IF` other than those Veda writes each stop the run as `UNSUPPORTED`, naming the line; before, they were passed
  over. `$INCLUDE` of a DD file is read as `$BATINCLUDE` is. `.dds` files are refused.

#### TIMES features now covered

- **Stochastic runs** (`$SET STAGES YES`): the model of every state of the world (SOW) of a scenario tree, as TIMES
  builds it: the tree from `SW_START`, `SW_SUBS`, `SW_SPROB` (or `SW_PROB`), copied branches; every equation and
  variable by SOW (TIMES's names `ES_*`, `VAS_*`), a variable of a period shared by the SOWs that are not yet apart
  there; the expected value of the cost as the objective. Uncertain attributes: `S_COM_PROJ`, `S_COM_TAX`, `S_FLO_CUM`,
  `S_CAP_BND`, `S_COM_CUMNET`, `S_COM_CUMPRD`, `S_COM_CUM`; the right-hand sides of user constraints by SOW
  (`S_UC_RHS`, `S_UC_RHSR`, `S_UC_RHST`, `S_UC_RHSRT`, `S_UC_RHSTS`, `S_UC_RHSRTS`); the climate module by SOW
  (`S_CM_MAXCO2C`, `S_CM_MAXC`, `S_CM_CONST`); the uncertain investment cost (`S_NCAP_COST`), transformation
  multipliers (`S_FLO_FUNC`), availability factors (`S_NCAP_AFS`) and commodity fractions (`S_COM_FR`). The Veda files
  of a stochastic run have the `Sow` dimension (`times2veda_stc.vdd`, carried with the port). The equations are built
  in threads, as those of a deterministic run, and the rows of a period a SOW shares with an earlier one are not
  computed again. Not supported (named in the run report): the other `S_*` attributes, `S_FLO_FUNC` of a trade
  process, the investment costs of `S_NCAP_COST` in the cost results, several SOWs in the first period, `SENSIS`,
  `SPINES`, the tradeoff analysis (`S_UCOBJ`, `SW_LAMBDA`), and STAGES with MACRO, `TIMESTEP` or `FIXBOH`. Code:
  `times_pp/timespp/prep/stochastic.py`, `times_eq/src/stochastic.jl`, `times_rpt/timesrpt/stochastic.py`.

#### The same model as TIMES in more cases

- A technical life (`NCAP_TLIFE`) between 0.5 and 1 year is kept as given, as in TIMES; only a life of 0.499 or less
  is set to 1. Before, every life below 1 was set to 1, which changed the repeated investments and the costs of such a
  process.
- A transformation (`FLO_FUNC`, `FLO_EMIS`) of a process whose flows are also given per unit of activity (`ACT_FLO`) is
  multiplied by that factor only for the process's primary group, as in TIMES; before, it was multiplied for any group
  of the process that had one.
- With the model reduction (`REDUCE YES`), an emission whose factor and source flow are both given as 0 keeps its zero
  coefficient in the commodity balance, as TIMES does.
- A DD file that does not set `$ONEPS` itself no longer takes it from the DD file before it: GAMS keeps `$ONEPS` local to
  the file that sets it. A data key that starts with a number with a dot (`1.1 0.25` in a parameter of two indexes) is
  read as labels, as GAMS reads it. DD files over 500 MB are read like any other.

#### Solving

- The time limit of a solve is the run file's last `OPTION RESLIM`, or GAMS's default with none, unless `--time-limit`
  says otherwise (`0`: no limit); the report says which. Every solve gets it, the Negishi iterations of MLF too, and a
  run that outlasts its limits is ended with every process it started.
- MLF: a Negishi solve that is not optimal stops the iterations with a message, and the report says when they ended at
  `NITER` with the weights still moving.
- With `--lp`, an optimum with infeasibilities after unscaling (CPLEX: "optimal with unscaled infeasibilities") is an
  optimum like any other, and the report shows the largest row and bound violations. Before, the run was `NOT SOLVED`
  and the solution was dropped.
- The threaded model build no longer spends most of its time in garbage collection: a 13-million-row model builds in
  about 33 s, not about 790 s. The model built is the same.

#### Results and reports

- **The .vd files write numbers as TIMES in GAMS writes them** (15 significant digits, as GDX2VEDA): the values are
  unchanged, the text of some lines differs from earlier runs of this implementation.
- A failed `--jacobian` or `--db3` is flagged as `NOT WRITTEN`, exit status 4, as the Veda result files are.
- A stochastic run compared with a GAMS run of it (`--gams reuse`) no longer reports rows of `EQ_COMBAL`, `EQ_IRE`,
  `EQ_PEAK`, `EQE_CPT` and the like as missing: TIMES copies the marginals of the stochastic rows into them for its
  report; they are not rows of the model.
- `models/DemoS_012/expected.json` holds the GAMS result in full; the report of a published reference shows what the
  reference says. The automated checks hold the objective to 1e-9, and check that a serial and a parallel build give
  the same matrix. `setup` and the automated checks run on a copy of `models/DemoS_012`, so that a run leaves no file
  there.

### 0.3.1 (October 2026): result folders that cannot harm the input; result files that were not written are flagged

- A run whose result folder would be the model's own folder, lie inside it or hold it (for example `--out` the folder
  that holds the run folder) stops before anything is done, with exit status 2; before, the folder was emptied first.
  A result folder is replaced only when this runner made it (it holds the file `.times_result`, or a run report). In a
  run of several cases, a second case with the same name goes to `<case>_2` instead of replacing the first's results.
- When the Veda result files, or the results later runs read, could not be written, the report's second line says
  `NOT WRITTEN` and what, the console says so, and the exit status is 4 (unless the verdict gives 1 or 3); before, only a
  note in the report said so.
- TIMES-MACRO MLF with `--lp` or `--gurobi` stops with a message: its Negishi iterations solve the LP again, so far with
  HiGHS only; before, such a run stopped after its first LP without saying so.

### 0.3.0 (October 2026): the model reduction of TIMES (REDUCE), the results of earlier runs

#### TIMES features now covered

- **The model is reduced as the run file says** (`$SET REDUCE`), at the three levels of TIMES: `NO` no reduction;
  `YES` (what Veda writes) flows that the activity determines are replaced by the activity (the only flow of the
  primary group, flows tied to it by `FLO_FUNC` / `FLO_SUM` or a single `ACT_EFF`, trade flows that are the activity),
  processes with no capacity variable and no activity attribute have no activity variable, and a process with an
  upper or fixed activity bound of zero is turned off there; any other value, or no `$SET REDUCE` line, only the
  capacity variables of the processes that need them and the emissions defined by `FLO_SUM` on input flows. The model
  is the one TIMES builds in GAMS, row by row; the optimum is the same at every level. Before, a `REDUCE YES` run file
  was built without the reduction (same optimum, a larger model: `models/DemoS_012` had 16,215 rows, now 6,034). The
  flows replaced by the activity are reported from it, as TIMES reports them. Code: `times_pp/timespp/prep/reduce.py`,
  `times_eq/src/terms.jl` (`reduced_flow`).
- `TIMES_REDUCE=NO` (an environment variable) builds the unreduced model whatever the run file says; `TIMES_REDUCE=YES`
  the reduced one. When the setting changes the level the run file asks for, the run says so on the console and in the
  report's notes. `$SET REDUCE` is read as the preprocessor reads the run file (also behind `$IF NOT SET REDUCE`, not
  inside `$ONTEXT` blocks).

#### The results of earlier runs (LPOINT, FIXBOH, TIMESED)

- **A run writes its solution point after every solve** (`<run>_p.parquet` in `GAMSSAVE`, or the run folder), not only
  with `SPOINT`: a later run (`LPOINT`, `FIXBOH`) can load it whatever the earlier run file says, as a run of TIMES in
  GAMS can load the GDX that its command line writes.
- **A later run looks where TIMES looks, from its own folder**, and `LPOINT` and `TIMESED` may carry a path, as in
  TIMES. Before, the results were looked for in a copy of the folder, and a name with a path was not found.
- **Only results written by a run of this implementation are read** (Parquet, with that run's mark); GDX files of
  results are neither read nor written. When none is found, the message lists every file looked for and why each was
  passed over. Code: `times_pp/timespp/refpoint.py`, `times_rpt/timesrpt/results.py`.

#### Running

- `python TIMES.py run <run file>` runs that run file of its folder, as the case named after it. A folder is read as
  before; a folder with several run files still runs one of them. The `.run` may be left out when no folder has that
  name.

#### Documents

- `FEATURES.md`, what is covered attribute by attribute, is now in the repository root (it was `times_pp/FEATURES.md`):
  it covers the whole chain, not only the preprocessor.

### 0.2.0 (October 2026): TIMES-MACRO (MLF), elastic demands, the climate module, solvers of your GAMS

#### TIMES features now covered

- **TIMES-MACRO in its linearised form** (`$SET MACRO MLF` with a reference run, `$SET TIMESED YES` or the
  reference's name): the calibration of MACRO (its NLP solved with Ipopt), the linearised model `TIMES_MACRO`
  maximising the utility, the Negishi iterations, and the report of TIMES-MACRO, as TIMES in GAMS has them; the Veda
  files have `VAR_Macro`. The reference run is a run with `$SET TIMESED NO` and `$SET ANNCOST LEV` (it writes the base
  prices and the annual cost shares); it can be a run of this implementation. The calibration agrees with TIMES's
  (CONOPT) within the accuracy of the NLP solvers (every calibrated parameter within 1e-6 relative); everything else is
  computed as TIMES computes it. Refused, with a message: `MACRO YES`, `MSA`, `CSA`; MLF without a reference run (as
  TIMES stops); an MLF run with taxes or subsidies in its objective; `TM_QFAC` with `TM_CAPTB`. Code:
  `times_pp/timespp/prep/mlf.py`, `times_eq/src/equations/mlf.jl`, `times_eq/src/negishi.jl`, `times_rpt/timesrpt/mlf.py`.
- **Elastic demands** (`$SET TIMESED YES`, or the name of an earlier run as Veda writes it): the demands with
  `COM_ELAST`, `COM_VOC` and `COM_STEP` move away from their projection in steps, valued at the base prices of the
  earlier run, as in TIMES (`EQ_OBJELS`, the elastic terms of the commodity balances and of the objective); the cost
  is reported as `Cost_Els` in the Veda files. Not supported: demands aggregated into other demands (CES aggregation)
  and shaped elasticities (`COM_ELASTX`). Code: `prep/elastic.py`, `equations/objels.jl`.
- **`FIXBOH`** with **`LPOINT`**: the periods up to the year (or `REG_FIXT` by region) fixed at the solution of an
  earlier run, with the relaxations TIMES applies to user constraints, cumulative and capacity bounds and trade
  (`prep/fixboh.py`, `times_eq/src/steps.jl`). **`LPOINT`** with **`REG_BDNCAP`**: new capacity fixed or bounded at the
  levels of the earlier run (`prep/spoint.py`).
- **The results later runs read** are written by this implementation itself: with `SPOINT 1` the solution point
  `<run>_p`, with `TIMESED NO` the base prices `<run>_DP` and `com_bprice` (with `ANNCOST LEV` also `SOL_ACFR`, the
  annual costs as shares of the demand expenditure), in the run folder's `GAMSSAVE` (or the run folder), where TIMES
  writes them. They are Parquet files, which need no GAMS and no GDX library, and also GDX files when the GDX library
  loads, so that TIMES in GAMS can use them; a run reads either, Parquet first. So the reference run and the runs that
  read it all run without GAMS. The run report names each earlier result read and which run wrote it.
  `TIMES_NO_GDX=1`: no GDX of results read or written. Code: `times_pp/timespp/refpoint.py`,
  `times_rpt/timesrpt/results.py`.
- **The climate module** (`$SET CLI YES`): the global emissions of CO2 (`CM_CO2GTC`) and of CH4 and N2O
  (`CM_GHGMAP`), their concentrations in the atmosphere and the ocean layers, the radiative forcing (linearised:
  `CM_LINFOR`, exogenous: `CM_EXOFORC`) and the temperature changes of the surface and the deep ocean, with bounds on
  them (`CM_MAXC`, `CM_MAXCO2C`) and climate terms in user constraints (`UC_CLI`, with `GROWTH` and `PERIOD`), as in
  TIMES; calibrated from `CM_HISTORY` / `CM_CONST` or TIMES's defaults. The Veda files have its results as
  `VAR_Climate` and `Dual_clic`. Not supported (named in the run report): `CM_COUPLE`, `CM_DECAY` and `CM_PHI` given
  in the data, years beyond the horizon (`CM_CONST('EXT-EOH')`), `OBJ LIN`, `UC_CLI` in a user constraint on a
  timeslice level, and the climate module with MACRO or in a myopic or `FIXBOH` run. Code: `prep/cli.py`,
  `equations/cli.jl`, `times_rpt/timesrpt/rptcli.py`.
- **Timeslice-dynamic user constraints**: a user constraint on a timeslice level whose right-hand side is on that
  level too (`UC_ATTR` with the level name on the `RHS`, for example `R.UC.RHS.FLO.DAYNITE`) links each timeslice to
  the one before it in its cycle: the right-hand side terms are taken in the previous timeslice, with the opposite
  sign, as in TIMES (`equations/userco.jl`).
- **Simulated vintages** (`PRC_SIMV`: `prep/simv.py`, `equations/capvac.jl`) and **dynamic timeslice trees**
  (`TS_OFF` with `DYNTS`, `dynslite.vda`: `prep/dynslite.py`), as in TIMES.
- `FLO_EFF` and `NCAP_AFCS` given in the input are accepted: TIMES moves them to `FLO_EMIS` and `NCAP_AFC` before
  they are read, and so does this implementation.
- **The levelized annual costs of the report**: `$SET ANNCOST LEV` and `RPT_OPT('OBJ','2')` give the levelized annual
  investment and fixed costs, and with `ANNCOST LEV` the variable costs as levelized costs (`Cost_Inv`, `Cost_Invx`,
  `Cost_Fom`, `Cost_Fixx`, `Cost_Act`, `Cost_Flo`, `Cost_Com`, `Time_NPV`, `Reg_ACost`), as TIMES writes them, also
  with `RPT_OPT('OBJ','1')` of either sign (`times_rpt/timesrpt/cost_ann.py`). These were named in the run report and
  left out of the Veda files.

#### Solvers

- `--lp <solver>` solves myopic runs (`TIMESTEP`) and runs with `FIXBOH` too, each step by that solver of your GAMS.
  Each step has its own work folder (`gamslp/step<k>`) and GAMS log (`gamslp_step<k>.log`); the report's solver line
  names the steps and its hand-over line sums them.
- `--lp`: the LP is written to GAMS through the GDX library directly, about ten times faster (on a model of 1.4
  million rows, 11 s before, 1 s now). The report times each part of the hand-over (the LP taken from JuMP, the GDX
  written, GAMS's start to the solver's start, the solver's own time, GAMS after the solver, the solution read back)
  and gives the peak memory of GAMS's processes within the run.
- `check` lists GAMS for `--lp`: where it is, its version and the LP solvers its licence allows (found once with a
  small LP per solver, then kept in `settings.json`). `--lp <solver>` with a solver the licence does not have stops
  before the model is built.
- `--lp-names` (with `--lp` and `--keep`): GAMS receives the model by TIMES's names, each equation and variable family
  over its labels, so that its listing (`gamslp/lp_names.lst`) shows the equations and columns as TIMES's listing
  does. The program (`lp_names.gms`) and its data (`named.gdx`) are kept beside it, to run again with `limrow=` and
  `limcol=`; the solution comes back as by number. Without `--lp-names` nothing changes.
- `--gurobi`: the model solved by Gurobi through its Python interface (`times_eq/solvers/gurobilp.py`), without GAMS;
  the results are written as after a HiGHS solve. Options come from `gurobi.opt` of the run folder and
  `--solver-option`; lines that are not Gurobi parameters are named in the report. When Gurobi returns no duals (a
  solve stopped at a limit), the report says so and the marginals are left empty rather than written as zeros.
  `--lp gurobi` remains Gurobi through your GAMS.

#### Setup

- `setup` installs Ipopt (through Ipopt.jl) with the other Julia packages, and `check` lists it; only MLF runs use it.
  `NOTICE.md` names Ipopt and the libraries of its binary build with their licences.
- `setup` finds Gurobi (`GUROBI_HOME`, `gurobi_cl` on the PATH, or the default folder `gurobi<version>`) and installs
  the Python packages of `--gurobi` into `.venv`: `gurobipy` of that version (a Gurobi licence is for one version) and
  `scipy`. `setup --gurobi <version>` installs that version, for a licence without a local installation. `check`
  lists them, and says when the installed `gurobipy` is not the version of the Gurobi found.
- On Windows older than build 19041 (Windows 10 version 2004), which does not let a program ask for the Segment
  Heap, `setup` says so instead of making an interpreter copy that cannot use it; the runner uses `.venv`'s Python.

#### The same model as TIMES in more cases

- An input given as 0 in a DD file read with `$ONEPS` is EPS: a value on record that counts as 0. More of the
  statements that read such an input now treat it as TIMES does, so the model keeps the EPS entries TIMES keeps (and
  only those):
  - cost bounds `REG_BNDCST` / `REG_CUMCST` with costs, taxes or subsidies given as EPS (investment, decommissioning,
    fixed, commodity and flow costs); a fixed cost shaped by `SHAPE` / `MULTI` given as EPS, whose coefficient is 0 as
    in TIMES; the coefficients of these bounds are summed in TIMES's order;
  - the salvage value of a decommissioning cost given as EPS; blending costs `BL_VAROMC`, `BL_DELIVC`, `BL_INP` and
    conversion factors `CONVERT` given as EPS; an exchange rate `R_CUREX` given as EPS;
  - the growth multiplier of a dynamic process or commodity bound (`UC_CAP`, `UC_ACT`, `UC_COMNET` ... with
    `UC_DYNBND`), the ramp rate `ACT_UPS` and the minimum load `ACT_MINLD` given as EPS;
  - user constraints with cost attributes (`UC_ATTR` `COST`, `DELIV`, `TAX`, `SUB` on flows and trade, `COST` on
    activity, the cost attributes of commodity groups): a cost given or interpolated as EPS keeps its zero entry;
  - the defaults and copies that keep an EPS: `NCAP_CLED` from a lead time of EPS, the turning point of the residual
    load curve, `NCAP_DISC` from `NCAP_SEMI`, the reserve times `BS_STIME`; a capacity bound `CAP_BND` of EPS is
    converted as TIMES converts it; a storage loss `STG_LOSS` of EPS gives no loss below the annual level;
  - the maintenance equations of the ancillary balancing services are written from `BS_MAINT` also when no reserve
    commodity is left.
- A dynamic user constraint summed over regions, one of which has its dynamics on the left-hand side, now has its last
  period (it stopped before).
- Dynamic timeslices (`DYNTS`, `TS_OFF`) with the ancillary balancing services (`ABS`): the reserve equations are
  written only on the timeslices on in each period; simulated vintages with `FIXBOH` and `REG_FIXT`: no capacity-use
  rows (`EQ_CAPVAC`) in the periods fixed for a region; both as in TIMES.
- Myopic runs: fixed bounds and right-hand sides are split into lower and upper bounds on the model periods only, as
  in TIMES (a record of another year was split too; no effect on the model).
- A model whose data gives MACRO parameters (`TM_GDP0`, `TM_GR`, `TM_DMTOL` and the other `TM_*`) runs when the run
  file sets no MACRO switch: TIMES does not read them then, and neither does this implementation.

#### Input files

- DD files may give a parameter as a `TABLE` (row labels, column labels, a value under each column label), as
  hand-written files such as ETSAP's TIMES_Demo do; a table of another form is named in the run report.
- A value written without its leading zero after a blank (`'R1'.2020.'P1' .4`) is read as 0.4, as GAMS reads it; such
  a record was lost before.
- The run-file switch `RPOINT` other than `NO` (a report of a loaded solution, no solve) is not supported yet and now
  stops the run with `UNSUPPORTED` instead of being passed over.
- The matrix comparison (`compare_jacobian.py`) reads models with SOS variables (discrete capacity).

### 0.1.6 (October 2026): the GDX library on every Windows Python

- `--lp`, `--jacobian` and `times_pp/tools/compare_jacobian.py` load the GDX library on Pythons that do not look in
  PATH for the libraries a DLL needs (the Microsoft Store's Python, for one): its folder is added to the DLL search
  path (`times_eq/gams/gamslp.py`, `times_pp/tools/jacobian_gdx.py`, `compare_jacobian.py`). Before, the GDX step
  stopped with "Could not load shared library ... gmdcclib64.dll" (WinError 126).
- When that step fails, the message points to the Python error above it instead of saying that packages are missing
  (`times_eq/src/gamslp.jl`); `python TIMES.py setup` loads the GDX library once and says why when it does not
  (`TIMES.py`).

### 0.1.5 (October 2026): ancillary balancing services

- The ancillary balancing services extension of TIMES (reserves; `$SET ABS YES` in the run file) is supported: the
  reserve parameters `BS_*`, the reserve equations `EQ_BS00`-`EQ_BS28`, the reserve provision in user constraints and
  in start-up types, and the reserve provision in `VAR_POut` of the Veda result files. A model with these parameters
  was refused before (`UNSUPPORTED`). In the code: the preprocessing of `init_ext.abs`, `prep_ext.abs`,
  `coef_ext.abs`, `mod_vars.abs` and `equ_ext.abs` in `times_pp/timespp/prep/abs.py`, with the declarations read from
  `initmty.abs` (now carried in `times_pp/timespp/times_src/`); the equations in `times_eq/src/equations/abs.jl`, with
  the reserve terms in `userco.jl` and `startup.jl`; the reserve provision in `P_OUT` in `times_rpt/timesrpt/rptmisc.py`.
- A correction that also applies without the extension: ramp-rate parameters `ACT_UPS` given with the type `N` are
  kept as given, as TIMES keeps them, instead of being spread over the process timeslices (`times_pp/timespp/lvl.py`,
  `prep/bounds.py`).
- Setup, on a Python that runs on the Segment Heap already (the Microsoft Store's Python, or where Windows gives every
  program the Segment Heap), uses it as it is instead of trying to copy it (which Windows refuses there,
  WinError 1920), and no longer reports the preprocessor on the slower default heap.

### 0.1.4 (October 2026): clearer run reports

- The run report says "this implementation" for what it does not have yet, names the solver that ran (HiGHS, or the
  solver of your GAMS with `--lp`), and, for a model with no published GAMS result beside it, shows only the checks
  that were made and the one run ("THE RUN"), without an empty GAMS column.
- README: the verdict table says where the verdict is in the report, what SOLVED compares with, and "the solver" for
  NOT SOLVED.

### 0.1.3 (October 2026): shared with reviewers

- The versions before 1.0.0 were shared with a small group of reviewers ahead of the public release.

### 0.1.2 (October 2026): setup installs Julia

- `python TIMES.py setup` installs Julia when none is found, trying in turn winget's Juliaup package, the Microsoft
  Store's Julia (both on Windows, through winget), and a portable copy of the latest stable release from julialang.org
  in `.julia_bin` (checked against its published SHA-256; no administrator rights). It says why a way failed before it
  tries the next. `--no-julia-install`: none; `--install-julia winget|store|portable`: that way only.
- `setup.ps1` leaves Julia to that, and no longer needs git (a downloaded copy has none).
- `setup` no longer says it failed when the example agrees with its published objective (`SAME OBJECTIVE`).
- `--jacobian` without a file name writes `<case>.gdx` in the case's result folder (the case: the name of the run
  folder).

### 0.1.1 (October 2026): where --jacobian writes

- `--jacobian <file>`: a name without a folder goes into the case's result folder (`runs/<case>/`); `.gdx` is added
  when missing; an existing folder gets `<case>_jacobian.gdx`.

### 0.1.0 (October 2026): first shared version

The open chain for TIMES v4.9.7: DD files -> preprocessor (`times_pp`, Python and DuckDB, with Julia kernels) ->
equations (`times_eq`, Julia/JuMP) -> HiGHS -> report writer (`times_rpt`, Veda result files).

- The same linear program as TIMES in GAMS, coefficient by coefficient, on the models it supports; on models of up
  to 19 million rows and 120 million coefficients.
- Coverage: every input attribute of TIMES v4.9.7 is classified in `times_pp/FEATURES.md`; a model that needs an
  attribute or a use that is not supported stops with the verdict `UNSUPPORTED` and lists all it needs.
- Both objective forms (standard, `OBLONG`, and annualised, `OBJANN`), myopic runs (`TIMESTEP`), the grid extension
  (`powerflo.vda`, `gasgrids.vda`), the discrete-capacity extension, user constraints with every `UC_ATTR` modifier.
- The model's tables written as Parquet files (`model_parquet/`, one per table) as soon as each is final, while the
  preprocessor runs; `--db3` also writes them as one SQLite file. `TIMES_DROP=1` also releases each table from the
  preprocessor's memory once it is written and no longer read.
- The equation families built on several threads, with the model the same whatever the number of threads.
- Veda result files (`.vd`, `.vde`, `.vds`) for a plain run and the report options most Veda models set.
- The model library (`models/`) with the published TIMES-in-GAMS results; `run` compares with them without GAMS.
- `--lp <solver>` / `--cplex`: the model solved by an LP solver of the user's GAMS installation (CPLEX, ...), handed
  over as a GDX; HiGHS stays the default.
- `--jacobian <file>`: the model's matrix as a GDX in the layout of the jacobian GDX that GAMS's CONVERT solver
  writes, and `times_pp/tools/compare_jacobian.py` to compare two such files by the names of rows and columns.
