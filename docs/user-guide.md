# TIMES-OS user guide

How to install TIMES-OS, run a model, read the verdict and the results, and use the options and the extensions.
For what TIMES-OS is, see the [README](../README.md); for how its agreement with TIMES in GAMS is checked, see
[verification](verification.md).

## Installing and running

You need **Python 3.11 or newer**. `setup` installs the rest, Julia included (when none is found: on Windows through
winget or the Microsoft Store; on any system as a portable copy from julialang.org). git is only for cloning; a ZIP
download from GitHub works as well. Windows is the main platform; Linux works too.

```
git clone https://github.com/kanors-emr/TIMES-OS
cd TIMES-OS
python TIMES.py setup
python TIMES.py run <run folder>
```

On Windows, `setup.ps1` does the same and also checks that Python is there first:

```
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

- `setup` installs the Python packages into `.venv` in this folder and the Julia packages into `.julia_env`,
  compiles the Julia code ahead on the example model, and runs it. Allow ten to fifteen minutes the first time. It
  ends with "Setup is complete" or with the list of what is missing. Later commands use `.venv` without activating
  it. When Gurobi is installed, `setup` also installs the `gurobipy` of its version, for `--gurobi`. No TIMES source
  is needed: the TIMES v4.9.8 declaration files the chain reads are included (`times_pp/timespp/times_src/`). Only
  the comparison with TIMES in GAMS (`--check`, see [verification](verification.md)) needs GAMS and the TIMES source.
  When `setup` finds GAMS, it also fetches the TIMES source v4.9.8 from IEA-ETSAP's repository into
  `TIMES_model-v4.9.8/` in this folder, unless a source of that version is found already (`--no-times-source`: it
  does not). `setup --gams <gams executable> --times <TIMES source folder>` records where they are when they are not
  found.
  Everything `setup` installs by default is open-source. The GDX packages (`requirements-gams.txt`: `gamsapi[transfer]`
  and `gamspy_base`, which comes under the GAMS licence) serve only the comparison with GAMS, `--lp` and `--jacobian`:
  `setup` installs them when it finds GAMS, or with `setup --gdx`.
- A **run folder** holds one model run: the run file (`<case>.run`) and the DD files (`*.dd`). It is written from the model
  workbooks by Veda or by another VedaTL parser (VedaTL, the Veda Tag Language, is how TIMES model workbooks are
  written). The input files are only read; a run writes the results that later runs read into the folder's `GAMSSAVE` (or the
  folder itself), as TIMES does, and everything else into its result folder.
- When a folder holds several run files, give the one you want: `python TIMES.py run <run folder>/<run file>.run`. The
  `.run` may be left out when no folder has that name. The case takes the name of the run file, so each run file of a folder has its own result folder.
- The result is `runs/<case>/report_<case>.txt`. **Its first line is the verdict.**

Give `run` a folder that holds several run folders and it does them all and adds `runs/summary.txt`, with a count of
the unsupported features by the number of models that need each one. Several folders, run files, wildcards and a list file
(`--cases cases.txt`: one per line, `#` comments) can be mixed.

## The verdict

| Verdict (line 1 of `report_<case>.txt`, after `VERDICT`) | Meaning | Exit status |
|---|---|---|
| `SOLVED` | Solved: objective, sizes, and `solution.db3` with the levels and marginals of every variable and equation. Not compared with GAMS, as no published result is beside the model; `--jacobian` writes the matrix to compare with GAMS yourself. | 0 |
| `UNSUPPORTED` | The model uses TIMES features this implementation does not have yet. All of them are listed, with the number of records of each. | 3 |
| `NOT SOLVED` | The model was built and not solved (`--no-solve`, or above `--max-solve-rows`), or the solver did not reach an optimum (time limit, or a failure of the solver). | 1 |
| `ERROR` | A step failed; the message is in the report. | 1 |
| `INFEASIBLE` | The model's data cannot be met: rows are left with no column and a constant that does not satisfy them (`0 = 2.685`, a demand nothing can supply), on which TIMES in GAMS stops too ("equation infeasible due to rhs value"). All of them are listed in `julia.log`. Not a defect. | 5 |
| `SAME` | The model was compared with TIMES in GAMS and agrees: with `--check`, its matrix entry by entry; for a model with a published result (`models/`, the open reference models), with that result (`SAME OBJECTIVE` when only the objective is compared, as with `--gams run` or a GAMS listing in the run folder). | 0 |
| `DIFFERENT` | The model was compared with TIMES in GAMS and does not agree (`DIFFERENT OBJECTIVE` when only the objectives were compared). A defect; please report it. | 1 |

When a run is solved but its result files (the Veda files, or the results later runs read) could not be written, the
report's second line says `NOT WRITTEN` and what, and the exit status is 4 (unless a verdict above gives 1, 3 or 5).

Each case's results go to `runs/<case>/` (or `--out <folder>/<case>/`), `<case>` being the name of the run folder or run
file; a second case of the same name in one run goes to `<case>_2/`, and so on. A result folder is replaced only when
it is one this runner made; a run whose result folder would be the model's own folder, lie inside it or hold it (for
example `--out` the folder that holds the run folder, as `run C:\Models\Base --out C:\Models`) stops before anything is
done, with exit status 2.

## Results

- `solution.db3`: levels and marginals of every variable and equation, one table per family, by TIMES name.
- `<run>_julia.vd`, `.vde`, `.vds`: the Veda result files, to import into Veda next to a GAMS run. The attributes of
  a plain run, and those of the report options most Veda models set, are written; a report option that is not
  covered is named in the run report. `--no-report` skips them.
- `model_parquet/` (with `--keep`): the model's sets and parameters as TIMES holds them just before the solve, one
  Parquet file per symbol, by TIMES name. `--db3` also writes them as one SQLite file, `model.db3`.

## What is in a result folder

| File | |
|---|---|
| `report_<case>.txt` | The verdict, the unsupported features or the differences, the input files with their hashes, the versions of everything. Complete in itself. |
| `report_<case>.json` | The same for a program. |
| `preprocess.log`, `preprocess.json` | The preprocessor, and its result with every switch of the run file. |
| `solution.db3` | Levels and marginals of every variable and equation. |
| `julia.log`, `highs.log` | The model build; the solver log. |
| `<run>_julia.vd`, `.vde`, `.vds` | The Veda result files. |
| `model_parquet/`, `model.tjb` | With `--keep`: the model's tables (Parquet, one file per symbol) and the binary copy the equations read. |
| `work/` | With `--keep`: the copy of the run folder that was used. |

## Options of `run`

The three commands most runs need:

    python TIMES.py run <run folder>

Builds the model of the run folder (its run file and DD files, as Veda writes them) and solves it with HiGHS, all on
open-source software. The results go to `runs/<case>/`: `solution.db3`, the Veda result files and the run report.
When the run folder holds a published result (`expected.json`) or a GAMS listing, the objective is compared with it
and the report gives the verdict. GAMS is not needed.

    python TIMES.py run <run folder> --no-solve --check

Checks the model against TIMES in GAMS, solving nothing. The model is built here; TIMES in GAMS runs on the same run
folder up to its solver, where CONVERT writes its matrix; the two matrices are compared entry by entry, and the report
says SAME or DIFFERENT (see [verification](verification.md)). It is the quickest check of a model, and the one for
models too large to solve. Needs GAMS and the TIMES source, which `setup` fetches when it finds GAMS; a source of
your own is given with `--times <folder>` (the folder that holds `initsys.mod` and `maindrv.mod`). Without GAMS or
the source, the run stops before anything is done and says which is missing.
Without `--no-solve`, the model is also solved, by both, and the objectives are compared as well.

    python TIMES.py run <run folder> --cplex

As the first, but solved with CPLEX from your own GAMS installation instead of HiGHS: the model built here is handed
to GAMS and solved there, with the run folder's `cplex.opt`, and the results are written as after a HiGHS solve. For
models that HiGHS solves too slowly. Needs GAMS with a CPLEX licence. `--cplex` is short for `--lp cplex`.

All the options:

| Option | |
|---|---|
| `--out <folder>` | Where the results go. Default: `runs/` in this folder. |
| `--check` | Compare the model with TIMES in GAMS entry by entry: GAMS writes its matrix with CONVERT, and the two are compared after the run (see [verification](verification.md)). Needs GAMS and the TIMES source: without them the run stops before anything is done (exit status 2). `python TIMES.py verify <result folder>` compares a finished case again. |
| `--gams reference\|run\|reuse\|skip` | What the result is compared with. `reference`: the published result in the run folder (`expected.json`; the default when it is there). `run`: TIMES in GAMS, run now, solved, its objective compared. `reuse`: the GAMS listing already in the run folder (the default when there is one). `skip`: nothing. |
| `--times <folder>` | The TIMES source folder for this run's GAMS comparison (default: the one `setup` recorded or found). |
| `--solver auto\|simplex\|ipm\|hipo\|ipx` | HiGHS method. `auto` uses the simplex, and above 150,000 rows the interior point code `ipx` without crossover. `ipm` or `hipo` is the newer, parallel interior point code of HiGHS (HiPO); if it fails, `ipx` is tried. |
| `--time-limit <seconds>` | Limit for the HiGHS solve (default 3600). |
| `--tolerance <number>` | Relative difference of the objectives that still counts as the same, for a model with a published result (default 1e-6). |
| `--points <folder>` | Where the results of an earlier run are (`LPOINT`, `FIXBOH`, `TIMESED`) when they are not where TIMES looks: its result folder or its run folder; repeated as needed (`TIMES_POINTS`: folders separated by `;`). See "Runs that read an earlier run". |
| `--threads <n>` | Threads HiGHS may use (default: its own choice). |
| `--highs-option <name=value>` | Any HiGHS option, repeated as needed; applied last (e.g. `run_crossover=on`). |
| `--no-solve` | Build the model and solve nothing: sizes and times. When GAMS and the TIMES source are found, GAMS runs to its solver and stops there, and the sizes are compared (with `--check`, the matrices). |
| `--solve`, `--max-solve-rows <n>` | Above `--max-solve-rows` (default 2,000,000 rows) the model is built and not solved, unless `--solve`. |
| `--no-report` | No Veda result files. |
| `--keep` | Keep the model's tables (`model_parquet/`, `model.tjb`) and the copy of the run folder. |
| `--db3` | Also write the model's tables as one SQLite file, `model.db3`; with `--keep` it stays. |
| `--jacobian [<file>]` | The model's matrix as a GDX in the format of GAMS CONVERT's jacobian file (see [verification](verification.md)). Without `<file>`: `<case>.gdx` in the case's result folder (the case is the name of the run folder or run file). A name without a folder goes into the case's result folder; `.gdx` is added when missing; an existing folder gets `<case>_jacobian.gdx`. |
| `--lp <solver>`, `--cplex` | Solve with an LP solver of your own GAMS installation (`cplex`, or any LP solver its licence has) instead of HiGHS: the model is handed to GAMS as a GDX and solved there, with `<solver>.opt` of the run folder; the results are written as after a HiGHS solve. `--solver-option name=value` adds option lines; `--gams-exe <file>` says where GAMS is. HiGHS needs nothing and stays the default. GAMS receives the matrix by row and column number (`times_eq/gams/solve_lp.gms`, the same program for every model, without equation or column listing); its files (`gamslp/` in the result folder: the program's listing, the GDX of the LP and of the solution) are removed after the solve, or kept with `--keep`. The report gives the time of each part of the hand-over (the LP taken from JuMP, the GDX written, GAMS to the solver's start, the solver, the rest of GAMS, the solution read back) and the peak memory of GAMS's processes beside that of the whole run. A myopic run (`TIMESTEP`, and `FIXBOH`, which is solved as one step) is solved step by step by the same solver: each step in its own folder `gamslp/step<k>`, its GAMS log `gamslp_step<k>.log`; the report sums the hand-over over the steps. |
| `--lp-names` | With `--lp` and `--keep`: GAMS receives the model by TIMES's names instead, each equation and variable family over its labels (`EQG_COMBAL('REG1','2005','ELC','S')`, `VAR_FLO(...)`), so that its listing (`gamslp/lp_names.lst`) shows the rows and columns of each family as TIMES's listing does, as many as GAMS shows by default (3 per equation and variable). The program (`gamslp/lp_names.gms`) and its data (`gamslp/named.gdx`) stay beside it: for more of the listing, run it again from that folder, e.g. `gams lp_names.gms --IN=named.gdx --OUT=solution.gdx lp=cplex limrow=50 limcol=50`. The solution is the same as by number. Ignored without `--keep`. |
| `--gurobi` | Solve with Gurobi through its Python interface, without GAMS: needs a Gurobi licence and the Python packages `gurobipy` (the version of the licence) and `scipy`. `setup` installs them when it finds Gurobi (`GUROBI_HOME`, `gurobi_cl` on the PATH, or the default folder `gurobi<version>`), with the `gurobipy` of that version; for a licence without a local installation, `setup --gurobi <version>`. Options: `gurobi.opt` of the run folder and `--solver-option name=value`, as Gurobi parameters; lines that are not Gurobi parameters are named in the report. The results are written as after a HiGHS solve. |
| `--low-memory` | The preprocessor keeps its tables in a work file instead of in memory: slower, for large models on machines with little memory. |
| `--bundle` | Also write `<case>_bundle.zip`, for a report of a problem: the report, the logs, the run file, the DD files and the solver options; no other file of the run folder. Look through it before attaching it anywhere public. |
| `--cases <file>` | The cases listed in a file, one run folder per line. |
| `--quiet` | Do not show the output of the preprocessor, GAMS, Julia and HiGHS while they run. It is in the log files either way. |
| `--profile [cpu\|allocs]` | Write `julia_profile.txt`: where the Julia table load and the equation build spend time, or which lines allocate. |

The model is reduced as the run file's `REDUCE` says, as TIMES reduces it: `NO` not at all; `YES` the whole reduction
(flows that the activity determines are replaced by the activity, a process with a zero activity bound is turned off
there); any other value, or no `$SET REDUCE` line, only the capacity variables and the emissions defined by `FLO_SUM`
on input flows. The environment variable `TIMES_REDUCE=NO` builds the unreduced model whatever the run file says
(`TIMES_REDUCE=YES` the reduced one). The optimum is the same at every level; the model is smaller with the reduction.

`python TIMES.py check` shows what is installed, and, when GAMS is found, its version and the LP solvers its licence
allows for `--lp` (found by solving a small LP of 6,000 rows with each solver, a few seconds, then kept in `settings.json`
for that GAMS installation and licence file). `--lp` with a solver the licence does not have stops before the model
is built, and says which ones it has.

## Runs that read an earlier run: elastic demands, FIXBOH, LPOINT

Some runs read the results of an earlier run, as in TIMES: elastic demands (`$SET TIMESED YES` or `$SET TIMESED
<run>`) read its base prices, `FIXBOH` and `LPOINT` its solution point. The earlier run is a run of this
implementation: it writes those results itself, after the solve, where TIMES writes them, and the later run reads
them, with no GAMS and no GDX library on the machine.

| The earlier run | It writes (in `GAMSSAVE` of its run folder, or the run folder when there is none) |
|---|---|
| every run that solves | `<run>_p.parquet`: the levels and marginals of every variable and equation, which `LPOINT <run>` and `FIXBOH` read (TIMES writes it with `SPOINT 1`; a run of TIMES in GAMS writes the whole run with `GDX=` on its command line) |
| `$SET TIMESED NO` | `<run>_DP.parquet` (and `com_bprice.parquet` in the run folder): the base prices of the demands, which `TIMESED <run>` (and `TIMESED YES`) read |

`<run>` is the run file's `RUN_NAME`. Each file carries the name and folder of the run that wrote it.

**Where a later run looks** is where TIMES looks, from the later run's own folder: `GAMSSAVE` of that folder (or the
folder itself when it has none) for `LPOINT <name>` and `TIMESED <name>`, and the folder itself for `com_bprice`. The
name may carry a path, as in TIMES: `$SET LPOINT ..\BaseCase\GAMSSAVE\base3`. So two runs in one folder find each
other's results.

**When they are not there**, a run looks where the earlier run left them. Veda copies the GDX files of an earlier run
into the folder of a later one before it starts it; nothing copies these Parquet files. So a run then looks in:

- the folders given with `--points <folder>` (repeated as needed; or `TIMES_POINTS`, folders separated by `;`): each
  folder and its `GAMSSAVE`, so the result folder or the run folder of the earlier run;
- the result folders of the runner, `<--out folder>\<run>` and `runs\<run>`, where the earlier run's results are
  copied after it solves: `<run>` is the file's name without `_p` or `_DP`, and the file is read only when its mark
  names that run.

The report says which file was read, and which run wrote it, when.

**It reads only results written by a run of this implementation** (Parquet, with that run's mark). A GDX file, such
as one TIMES in GAMS wrote, is not read, and a run of this implementation writes no GDX file of results, so the two
never mix. When no file is found, the report lists every file it looked for, and why each was passed over.

## TIMES-MACRO in its linearised form (MLF)

A run file with `$SET MACRO MLF` couples TIMES with the macro-economic model MACRO in its linearised form, as TIMES
does: the model `TIMES_MACRO` maximises the utility of the regions with MACRO (those given `TM_GR`, with `TM_GDP0`).
It needs a reference run, as TIMES does:

1. the reference: the same model with `$SET TIMESED NO` and `$SET ANNCOST LEV`; it writes the base prices of the
   demands and the annual cost shares (`<run>_DP`, `com_bprice`, see above);
2. the MLF run: `$SET MACRO MLF` and `$SET TIMESED <reference run>` (or `YES` for `com_bprice`), with the MACRO
   inputs (`TM_GDP0`, `TM_GR`, and any of `TM_DEPR`, `TM_ESUB`, `TM_KGDP`, `TM_KPVS`, `TM_DMTOL`, `TM_DESUB`, ...).

The run calibrates MACRO first: a small non-linear program solved with Ipopt in a loop, as TIMES solves it with its
NLP solver. The calibration is the one part of a run computed within a tolerance: its parameters agree with TIMES's
to the accuracy of the solvers (within 1e-6 relative), and the run report says how many iterations it took. Then the
linear program is solved with HiGHS, and again while the Negishi weights of the regions move. A run is the same from
run to run on the same machine. `MACRO YES`, `MSA` and `CSA` are not covered; an MLF run with taxes or subsidies in
its objective stops and says so.

**Convergence of the Negishi iterations.** The verdict of a run says the last LP was solved to its optimum. It does not
say the regional weights have settled: as in TIMES, the iterations stop at `NITER` even when the weights are still
moving, and the run goes on with the last LP. The report's NOTES then say `the Negishi weights did not converge`, with the
last gap and the tolerance. A later solve that does not end optimal stops the iterations with a message.

## Stochastic runs (`STAGES`)

A run file with `$SET STAGES YES` and a scenario tree (`SW_START`, `SW_SUBS`, `SW_SPROB` or `SW_PROB`) is built as
TIMES builds it: the model of every state of the world (SOW) of the tree at once, every equation and variable by SOW
under TIMES's names (`ES_*`, `VAS_*`, the SOW the last index), a variable of a period shared by the SOWs that are not
yet apart in it, and the expected value of the cost as the objective. Uncertain inputs: `S_COM_PROJ`, `S_COM_TAX`,
`S_FLO_CUM`, `S_CAP_BND`, `S_COM_CUMNET`, `S_COM_CUMPRD`, `S_COM_CUM`, `S_NCAP_COST`, `S_FLO_FUNC`, `S_NCAP_AFS`,
`S_COM_FR`; the right-hand sides of user constraints (`S_UC_RHS*`) and the climate module (`S_CM_*`) by SOW. The Veda files of such a run have the `Sow`
dimension, as TIMES writes them with `times2veda_stc.vdd` (each result of each SOW, with the marginals undiscounted by
its probability). A run with `$SET SENSIS YES` solves one deterministic model for each SOW of the first period in
turn, each reported under its SOW, as TIMES does. A run with `$SET SPINES YES` is built as
TIMES builds it: the capacity and its investment, fixed and salvage costs of the first SOW in every SOW, and with
`SOLVEDA` 1 the cumulative constraints as expected values; its Veda files hold the expected values, as TIMES reports
them. Not covered, and named when a run uses them: the other `S_*` inputs, `S_FLO_FUNC` of a trade
process, the investment costs of `S_NCAP_COST` in the cost results, several SOWs in the first period (other than with
`SPINES` or `SENSIS`), `SENSIS` with other uncertain inputs than `S_COM_PROJ` and `S_COM_TAX`, `SPINES` with discrete capacity, retirements or `PRC_DYNUC`, and with `SOLVEDA` 1 cost bounds, `UC_TIME` or cumulative user constraints by period or timeslice, the tradeoff analysis (`S_UCOBJ`, `SW_LAMBDA`), and `STAGES` with MACRO, `TIMESTEP` or
`FIXBOH`. A stochastic model is several times the size of the deterministic one.

## Where things are

| Folder | |
|---|---|
| `TIMES.py` | The one command: `setup`, `check`, `run`, `verify`. |
| [`times_pp`](../times_pp/README.md) | The TIMES v4.9.8 preprocessor in Python on DuckDB, with Julia kernels for its heaviest steps: interpolation, timeslice levelling, capacity transfer and cost coefficients, objective coefficients, bounds. Output: the sets and parameters of the model, one table each. |
| [`times_eq`](../times_eq/README.md) | The TIMES equations in Julia/JuMP, built from those tables. One file per equation family, the algebra in its docstring. |
| [`times_rpt`](../times_rpt/README.md) | The TIMES report writer in Python: the report parameters and the Veda result files. |
| [`models`](../models/README.md) | The feature models, with the published TIMES-in-GAMS results. `setup` runs `DemoS_012` as its test. |
