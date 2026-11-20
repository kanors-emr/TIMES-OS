# TIMES-OS user guide

How to install TIMES-OS, run a model, read the verdict and the results, and use the options and the extensions.
For what TIMES-OS is, see the [README](../README.md); for how its agreement with TIMES in GAMS is checked, see
[verification](verification.md).

## Installing and running

### From a clone

You need **Python 3.11 or newer**. `setup` installs the rest, Julia included (when none of 1.11 or newer is found: on Windows through
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
  compiles the Julia code ahead on the example model, and runs it. Julia's packages and their compiled code go
  into `.julia_depot` in this folder, not Julia's store in your home folder (`~/.julia`); `setup --julia-depot
  <folder>` puts them elsewhere, for example in a depot shared with your other Julia work. Allow ten to fifteen minutes the first time. It
  ends with "Setup is complete" or with the list of what is missing. Later commands use `.venv` without activating
  it. When Gurobi is installed, `setup` also installs the `gurobipy` of its version, for `--gurobi`; when a MOSEK licence is found, the
  Julia packages of `--mosek`. No TIMES source
  is needed: the TIMES v4.9.8 declaration files the chain reads are included (`times_pp/timespp/times_src/`). Only
  the comparison with TIMES in GAMS (`--check`, see [verification](verification.md)) needs GAMS and the TIMES source.
  When `setup` finds GAMS, it also fetches the TIMES source v4.9.8 from IEA-ETSAP's repository into
  `TIMES_model-v4.9.8/` in this folder, unless a source of that version is found already (`--no-times-source`: it
  does not). `setup --gams <gams executable> --times <TIMES source folder>` records where they are when they are not
  found.
  Everything `setup` installs by default is open-source. The GDX packages (`requirements-gams.txt`: `gamsapi[transfer]`
  and `gamspy_base`, which comes under the GAMS licence) serve only the comparison with GAMS, `--lp` and `--jacobian`:
  `setup` installs them when it finds GAMS, or with `setup --gdx`.
- A clone that has never been set up (no `.venv`, no `.julia_env`, no setup in `settings.json`) does not run:
  `run` and `verify` say so in one line and stop before anything is installed or written. `TIMES_SETUP_CHECK=0`
  lets them through, for an environment you look after yourself.
- A run stops at its start, in one line, when the Python that runs the preprocessor has no DuckDB or one the code
  cannot use (today 2 or newer; `requirements.txt` says `duckdb<2`), naming the version found and what puts it
  right: `python TIMES.py setup` here; installed, `pip install --force-reinstall times-os`. `check` shows the
  DuckDB in use.
- **Stochastic models.** The equations of stochastic TIMES (`$SET STAGES YES`, `$SET SPINES YES`) compiled ahead
  are a package of their own in this repository (`times_eq/addons/TimesEqStochastic`), which `setup` compiles with
  the rest. Where it is missing or out of date (after a change in `times_eq/src`, or an update of the code without a
  new `setup`), the first run of a model with one of the two switches installs and compiles it, for a few minutes,
  once (nothing is downloaded); the run says so before it starts, and later runs start at once. `check` shows
  whether it is compiled. A `SENSIS` run does not need it.
- A **run folder** holds one model run: the run file (`<case>.run`) and the DD files (`*.dd`). It is written from the model
  workbooks by Veda or by another VedaTL parser (VedaTL, the Veda Tag Language, is how TIMES model workbooks are
  written). The input files are only read; a run writes the results that later runs read into the folder's `GAMSSAVE` (or the
  folder itself), as TIMES does, and everything else into its result folder.
- **Comments in the run file and the DD files** are read as GAMS reads them: `*` in column 1 (or the character of
  `$COMMENT`), `$ONTEXT` ... `$OFFTEXT`, `$HIDDEN`, end-of-line comments (`$ONEOLCOM`, `$EOLCOM`), in-line comments
  (`$ONINLINE`, `$INLINECOM`, nested with `$ONNESTCOM`), with their scope: a switch set in an included file ends with
  it, unless the including file has `$ONGLOBAL`. Several options may share one `$` line. Comment characters set on
  GAMS's command line or in `gamsconfig.yaml` (`eolCom`, `inlineCom`) are not seen: set them in the files. `$DOLLAR`,
  `$MINCOL`, `$MAXCOL` are not read: the run stops on them, naming the file and the line.
- **What GAMS refuses in a DD file stops the run** with the file, the line, what was expected there and the line
  itself (cut to 120 characters): a comment character where comments are not switched on, a record without its value
  or with words after it, a key with more or fewer labels than the declared domain, a label with a character GAMS
  does not allow, an in-line comment or `$ONTEXT` still open at the end of a file. The verdict is
  `ERROR: the input cannot be read: <file>, line <n>: ...`.
- When a folder holds several run files, give the one you want: `python TIMES.py run <run folder>/<run file>.run`. The
  `.run` may be left out when no folder has that name. The case takes the name of the run file, so each run file of a folder has its own result folder.
- `python TIMES.py example <folder>` copies the example model, DemoS_012, into a new or empty folder and prints the
  line that runs it.
- The result is `runs/<case>/report_<case>.txt`; `--out <folder>` puts the results elsewhere. The last line of a
  run is `Output files available here: <folder>`. **The report's first line is the verdict.**

Give `run` a folder that holds several run folders and it does them all and adds `runs/summary.txt`, with a count of
the unsupported features by the number of models that need each one. Several folders, run files, wildcards and a list file
(`--cases cases.txt`: one per line, `#` comments) can be mixed.

### Installing with pip (beta)

TIMES-OS can also be installed as a Python package. In this release that is a beta feature, offered to those
willing to help test it: if you are, we would be glad to hear how it goes. Until a release makes it a regular
feature, the clone above is the way to install for everyone else.

You need **Python 3.11 or newer**; TIMES-OS installs the rest, Julia included. Windows is the main platform; Linux
and macOS work too.

```
pip install times-os
times-os example demo
times-os run demo
```

`python -m times_os` is the same command as `times-os` and always works, also where the `times-os` command is not on
the PATH (on Windows a Python installed for one user often leaves its `Scripts` folder off it). Everywhere in this
guide, `python TIMES.py <command>` (the form of a clone, above) is `times-os <command>` for an installed package:
`run`, `check`, `verify` and `setup` take the same options.

- `times-os example <folder>` copies the example model, DemoS_012, into a new or empty folder and prints the line that
  runs it. `times-os --version` prints the version, the TIMES version it follows and Python's.
- **The first run sets TIMES-OS up**, once. It says so in one line before it starts, with where its log is, then shows
  its steps: Julia is installed when none of 1.11 or newer is found (an older one is left as it is; on Windows through winget or the Microsoft Store; on any system
  as a portable copy from julialang.org, no administrator rights needed), the Julia packages are installed and
  compiled ahead on the example model, and the example model is run as the test. It needs an internet connection,
  about 8 GB of memory and some time: Julia compiles its packages, from ten minutes on a fast machine to over an
  hour on a small one. While it works, the console shows its steps and, at least once a minute, a line with the
  step, the minutes so far and what Julia is doing (the package it installs or compiles); the log has everything.
  `times-os setup` does it beforehand, with all its output; `times-os check` (which also sets up first when no setup
  is made) shows what is installed, where the code and the data folder are, and whether the setup is the one for
  this version. A failed setup ends with the full path of its log.
- **One setup at a time.** When two runs start together on a new installation, one makes the setup and the other
  says that it waits for it, with a line a minute, then runs without a setup of its own. A setup that was stopped
  (its process is gone, or it began more than 6 hours ago) does not block the next one: it is taken over, and the
  run says so.
- The code is in Python's package folder and is only read there. What TIMES-OS makes for itself (its settings, the
  Julia environment and the compiled workload, a Julia it installs, on Windows the Segment Heap copy of Python, the
  log of the setup, Python's compiled files of its code) is in its **data folder**:

  | System | Data folder |
  |---|---|
  | Windows | `%LOCALAPPDATA%\times-os` (e.g. `C:\Users\<you>\AppData\Local\times-os`) |
  | macOS | `~/Library/Application Support/times-os` |
  | Linux | `$XDG_DATA_HOME/times-os`, by default `~/.local/share/times-os` |

  `TIMES_DATA=<folder>` puts it elsewhere: a new or empty folder, or one that times-os made. TIMES-OS marks its data
  folder with a file `times-os-data.txt`; a folder that holds other things and no such file is refused before
  anything is written in it, and `times-os clean` never removes it. Julia's packages and their compiled code are in
  `.julia_depot` in the data folder, shared by its environments (`times-os setup --julia-depot <folder>` puts them
  elsewhere); `times-os clean` removes it with the data folder.
- **One part of the data folder for each Python environment.** Installed in two environments (two venvs, or a
  venv and a conda environment), times-os keeps the settings, the Julia environment, the compiled workload and the
  Segment Heap copy of each in a part of its own, `env-<code>` in the data folder (`environment.txt` there names
  the Python and the code). Each environment is set up once, at its first run; going back and forth between them
  sets nothing up again, and the setup of one never changes what a run of the other uses. A Julia that setup
  installs, the TIMES source and the one-setup-at-a-time lock are shared. `times-os check` names the part in use.
- The results go to `times-os-runs/<case>/` in the folder that holds the run folder (`C:\models\MyCase` gives
  `C:\models\times-os-runs\MyCase\`), the same place wherever the command is run from, also from inside the
  run folder (`times-os run .`). Several cases share one `times-os-runs`, in the lowest folder that holds every run
  folder given (siblings: their parent; folders at different depths: the higher one's), with `summary.txt`; run
  folders on different drives: beside the first. Where `times-os-runs` cannot be made or written there (a read-only
  share; directly under a drive, where it often cannot be made), the run stops before any work and asks for
  `--out <folder>`, which puts the results anywhere (and then nothing is made or tried beside the run folder). A folder there that this runner did not make is never replaced. The last line of a run is
  `Output files available here: <folder>`. **The report's first line is the verdict.**
- **Update:** `pip install -U times-os`. The next run sees the new version and brings the setup up to date first
  (it says so; Julia compiles the new code once). Another Python environment has its own part of the data folder,
  set up at its own first run.
- **Remove:** `times-os clean` lists what is in the data folder (only one marked as times-os's) and how much, and
  asks before removing it, with the parts of every environment
  (`--yes`: it does not ask); Julia itself and Julia's package store are left, and it says where they are. Then
  `pip uninstall times-os`. Your model folders and results are never touched.
- **Extras.** The plain package is the open chain, all open-source. The comparison with TIMES in GAMS (`--check`,
  `--gams run`), `--lp` and `--jacobian` read and write GDX files: `pip install "times-os[gdx]"` (`gamsapi[transfer]`
  and `gamspy_base`, which comes under the GAMS licence). `--gurobi`: `pip install "times-os[gurobi]"
  gurobipy==<the version of your Gurobi licence>`. `--mosek`: `times-os setup --mosek` (Julia packages, not Python
  ones). A run that needs them and does not find them names that line.
- About once a day a run asks PyPI for the latest version of `times-os` (nothing is sent but the request for the
  package's public page; two seconds at most, nothing said without a network) and says so in one line at its end
  when a newer one is out. `TIMES_UPDATE_CHECK=0` turns this off.
- **Where it has run:** this release's package has been installed and run, first run and second, on Windows and
  Linux on GitHub's runners and on a Windows workstation of KanORS-EMR; on macOS, an earlier version of it has.
- **Tell us what you find**, whatever it is: in the repository's [Issues](https://github.com/kanors-emr/TIMES-OS/issues),
  or by email to times-os@kanors.com. `times-os --version` and `times-os check` name both.

## The verdict

| Verdict (line 1 of `report_<case>.txt`, after `VERDICT`) | Meaning | Exit status |
|---|---|---|
| `SOLVED` | Solved: objective, sizes, and `solution.db3` with the levels and marginals of every variable and equation. Not compared with GAMS, as no published result is beside the model; `--jacobian` writes the matrix to compare with GAMS yourself. | 0 |
| `UNSUPPORTED` | The model uses TIMES features this implementation does not have yet. All of them are listed, with the number of records of each. | 3 |
| `NOT SOLVED` | The model was built and not solved (`--no-solve`, or above `--max-solve-rows`), or the solver did not reach an optimum (time limit, or a failure of the solver). | 1 |
| `ERROR` | A step failed; the message is in the report. | 1 |
| `INFEASIBLE` | The model's data cannot be met: rows are left with no column and a constant that does not satisfy them (`0 = 2.685`, a demand nothing can supply), on which TIMES in GAMS stops too ("equation infeasible due to rhs value"). All of them are listed in `julia.log`. Not a defect. | 5 |
| `SAME` | The model was compared with TIMES in GAMS and agrees: with `--check`, its matrix entry by entry; for a model with a published result (`models/`, the open reference models), with that result (`SAME OBJECTIVE` when only the objective is compared, as with `--gams run`, or `--gams reuse` and a GAMS listing in the run folder). | 0 |
| `DIFFERENT` | The model was compared with TIMES in GAMS and does not agree (`DIFFERENT OBJECTIVE` when only the objectives were compared). A defect; please report it. What differs follows, with the counts (`DIFFERENT: 32 column bounds (check 4)`). It is the verdict whenever a comparison differs, also when the run was not solved or GAMS only wrote its matrix; that comes after it (`; not solved here (...)`). | 1 |

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
| `report_<case>.txt` | The verdict; TIME AND MEMORY (the time to the solver and the peak memory, and when the run ran GAMS, GAMS's and the ratio; with `--no-solve`, the time to the built model, beside GAMS's to the start of CONVERT); the unsupported features or the differences, the input files with their hashes, the versions of everything. Complete in itself. |
| `report_<case>.json` | The same for a program (TIME AND MEMORY under `against_gams`). |
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
open-source software. The results go to `runs/<case>/` (installed with pip: `times-os-runs/<case>/` beside the run
folder): `solution.db3`, the Veda result files and the run report.
When the run folder holds a published result (`expected.json`), the objective is compared with it and the report
gives the verdict. GAMS is not needed. A run uses GAMS only when you ask for it (`--check`, `--gams run` or `reuse`,
`verify`, or the same in `times-os.toml`): otherwise no GAMS is started and no GAMS result in the run folder is read.
A GAMS listing there (as Veda leaves it) is compared with only with `--gams reuse`; the verdict says when one is there.

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
| `--gams reference\|run\|reuse\|skip` | What the result is compared with. `reference`: the published result in the run folder (`expected.json`; the default when it is there). `run`: TIMES in GAMS, run now, solved, its objective compared. `reuse`: the GAMS listing already in the run folder (only when given). `skip`: nothing (the default, unless `--check` or a published result). |
| `--times <folder>` | The TIMES source folder for this run's GAMS comparison (default: the one `setup` recorded or found). |
| `--solver auto\|simplex\|ipm\|hipo\|ipx` | HiGHS method. `auto` uses the simplex, and above 150,000 rows the interior point code `ipx` without crossover. `ipm` or `hipo` is the newer, parallel interior point code of HiGHS (HiPO); if it fails, `ipx` is tried. |
| `--time-limit <seconds>` | Limit for the HiGHS solve (default 3600). |
| `--tolerance <number>` | Relative difference of the objectives that still counts as the same, for a model with a published result (default 1e-6). |
| `--points <folder>` | Where the results of an earlier run are (`LPOINT`, `FIXBOH`, `TIMESED`) when they are not where TIMES looks: its result folder or its run folder; repeated as needed (`TIMES_POINTS`: folders separated by `;`). See "Runs that read an earlier run". |
| `--threads <n>` | Threads HiGHS may use (default: its own choice). |
| `--highs-option <name=value>` | Any HiGHS option, repeated as needed; applied last (e.g. `run_crossover=on`). |
| `--no-solve` | Build the model and solve nothing: sizes and times, without GAMS. With `--check` (or `--gams run`), GAMS runs to its solver and stops there, and the sizes are compared (with `--check`, the matrices). |
| `--solve`, `--max-solve-rows <n>` | Above `--max-solve-rows` (default 2,000,000 rows) the model is built and not solved, unless `--solve`. |
| `--no-report` | No Veda result files. |
| `--keep` | Keep the model's tables (`model_parquet/`, `model.tjb`) and the copy of the run folder. |
| `--db3` | Also write the model's tables as one SQLite file, `model.db3`; with `--keep` it stays. |
| `--jacobian [<file>]` | The model's matrix as a GDX in the format of GAMS CONVERT's jacobian file (see [verification](verification.md)). Without `<file>`: `<case>.gdx` in the case's result folder (the case is the name of the run folder or run file). A name without a folder goes into the case's result folder; `.gdx` is added when missing; an existing folder gets `<case>_jacobian.gdx`. |
| `--lp <solver>`, `--cplex` | Solve with an LP solver of your own GAMS installation (`cplex`, or any LP solver its licence has) instead of HiGHS: the model is handed to GAMS as a GDX and solved there, with `<solver>.opt` of the run folder; the results are written as after a HiGHS solve. `--solver-option name=value` adds option lines; `--gams-exe <file>` says where GAMS is. HiGHS needs nothing and stays the default. GAMS receives the matrix by row and column number (`times_eq/gams/solve_lp.gms`, the same program for every model, without equation or column listing); its files (`gamslp/` in the result folder: the program's listing, the GDX of the LP and of the solution) are removed after the solve, or kept with `--keep`. The report gives the time of each part of the hand-over (the LP taken from JuMP, the GDX written, GAMS to the solver's start, the solver, the rest of GAMS, the solution read back) and the peak memory of GAMS's processes beside that of the whole run. A myopic run (`TIMESTEP`, and `FIXBOH`, which is solved as one step) is solved step by step by the same solver: each step in its own folder `gamslp/step<k>`, its GAMS log `gamslp_step<k>.log`; the report sums the hand-over over the steps. The model is handed to the solver once and Julia's own copy of it is emptied before the solve, and GAMS leaves memory while its solver runs (it saves its state and restarts after the solver, `solvelink=0`), so that no idle copy of the model is held beside the solver's; the same holds for `--gurobi`. Two settings change that: `TIMES_LP_DIRECT=0` keeps Julia's copy through the solve (JuMP hands the model over at the solve), and `TIMES_GAMS_SOLVELINK=2` keeps GAMS in memory beside its solver (GAMS's own default, a few seconds quicker on a large model); the report says which was used (the hand-over "direct" or "JuMP"; GAMS's log `gamslp.log`: "Executing CPLEX (Solvelink=0)"). |
| `--lp-names` | With `--lp` and `--keep`: GAMS receives the model by TIMES's names instead, each equation and variable family over its labels (`EQG_COMBAL('REG1','2005','ELC','S')`, `VAR_FLO(...)`), so that its listing (`gamslp/lp_names.lst`) shows the rows and columns of each family as TIMES's listing does, as many as GAMS shows by default (3 per equation and variable). The program (`gamslp/lp_names.gms`) and its data (`gamslp/named.gdx`) stay beside it: for more of the listing, run it again from that folder, e.g. `gams lp_names.gms --IN=named.gdx --OUT=solution.gdx lp=cplex limrow=50 limcol=50`. The solution is the same as by number. Ignored without `--keep`. |
| `--gurobi` | Solve with Gurobi through its Python interface, without GAMS: needs a Gurobi licence and the Python packages `gurobipy` (the version of the licence) and `scipy`. `setup` installs them when it finds Gurobi (`GUROBI_HOME`, `gurobi_cl` on the PATH, or the default folder `gurobi<version>`), with the `gurobipy` of that version; for a licence without a local installation, `setup --gurobi <version>`. Options: `gurobi.opt` of the run folder and `--solver-option name=value`, as Gurobi parameters; lines that are not Gurobi parameters are named in the report. The results are written as after a HiGHS solve. |
| `--mosek` | Solve with MOSEK through its Julia interface (the Julia packages `Mosek` and `MosekTools`), without GAMS and without a file between them: JuMP hands the model to MOSEK as it does to HiGHS. Needs a MOSEK licence (`MOSEKLM_LICENSE_FILE`, or `mosek.lic` in the folder `mosek` of your home folder) and the two packages, which `setup` installs when it finds the licence, or `setup --mosek`. Options: `mosek.opt` of the run folder (a parameter a line, `name value`) and `--solver-option name=value`, as MOSEK parameters (`MSK_IPAR_...`, `MSK_DPAR_...`), an integer parameter's value as a number or by name (`MSK_IPAR_INTPNT_BASIS=MSK_BI_NEVER`); `--threads` and `--time-limit` apply. The model is handed to MOSEK directly, without JuMP's copy of it beside MOSEK's (less memory); `TIMES_MOSEK_DIRECT=0` gives MOSEK JuMP's copy instead (a run of TIMES-MACRO MLF always does). MOSEK's log is in `julia.log`. The results are written as after a HiGHS solve; myopic and SENSIS runs and the Negishi iterations of TIMES-MACRO MLF solve each LP with MOSEK. `--lp mosek` is MOSEK through your GAMS. |
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

### A settings file for the options of `run`: `times-os.toml`

Options that you give to every run can be written once in a settings file, `times-os.toml` (TOML). Its keys are the
long names of `run`'s options without the dashes. A switch is `true` or `false`, a repeated option is a list, and a
relative path is taken from the file's folder:

```toml
# times-os.toml, in C:\models (beside the run folders) or in your home folder
out = "D:/results"              # --out D:/results
threads = 8                     # --threads 8
time-limit = 3600               # --time-limit 3600
keep = true                     # --keep
solver-option = ["lpmethod=4"]  # --solver-option lpmethod=4, repeated for each item
```

- **Where it is read:** first the nearest `times-os.toml` going up from the folder that holds the run folder (for
  several cases, from their common folder) to the drive's root; then your own, `times-os.toml` in your home folder.
  A key in the nearest file wins over the same key in yours.
- **What wins:** the command line, then a `TIMES_<name>` setting (`TIMES_POINTS`, `TIMES_GAMS`), then the nearest
  file, then yours, then the built-in default.
- A run names the files it read in one line at its start, and in its report. An unknown key, or a value of the wrong
  kind, stops the run before any work, naming the file and the key.
- `times-os config [<run folder>]` (from a clone: `python TIMES.py config`) prints every option with the value in force
  and where it comes from, and the two places it looks.
- `cases` is given on the command line only: in a file it would add its cases to every run, so a file with it is
  refused like an unknown key.
- With no `times-os.toml` anywhere, nothing changes. Setup's own test of the example reads none, and
  `TIMES_SETTINGS_FILES=0` turns the files off for every run (a check that must not depend on them sets it).

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

**Comparing such a run with a run of TIMES in GAMS.** The later run starts from the results this implementation
wrote for the earlier run; a GAMS run of the later model started from those GAMS wrote. When the earlier run has
several optimal solutions (most large models have: capacity that costs nothing, equal trade routes, the same
activity split differently over timeslices), the two solvers end at different ones with the same objective, and the
later runs, fixed at them, are two different models whose objectives differ a little. That is not a difference of
this implementation: the report then says `SOLVED`, with both objectives and the reason. `--check` (and `--gams
run`) makes this implementation read what GAMS reads, and the two then agree entry by entry. The Veda result files
of a run with `FIXBOH` hold the fixed periods as the earlier run had them, as in TIMES.

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
| `times_os` | The package's launcher: the `times-os` command and `python -m times_os` run `TIMES.py`; installed by pip, the tree above is in the package (`times_os/_tree`) and is only read. |
| [`times_pp`](../times_pp/README.md) | The TIMES v4.9.8 preprocessor in Python on DuckDB, with Julia kernels for its heaviest steps: interpolation, timeslice levelling, capacity transfer and cost coefficients, objective coefficients, bounds. Output: the sets and parameters of the model, one table each. |
| [`times_eq`](../times_eq/README.md) | The TIMES equations in Julia/JuMP, built from those tables. One file per equation family, the algebra in its docstring. |
| [`times_rpt`](../times_rpt/README.md) | The TIMES report writer in Python: the report parameters and the Veda result files. |
| [`models`](../models/README.md) | The feature models, with the published TIMES-in-GAMS results. `setup` runs `DemoS_012` as its test. |
