# times_pp — the TIMES preprocessor

A Python + DuckDB restatement of the TIMES v4.9.8 preprocessor: everything TIMES in GAMS does between reading the
DD files and the `SOLVE` statement (`ppmain.mod`, `preppm.mod`, `coefmain.mod`, `bndmain.mod` and the VEDA extension
hooks): interpolation, timeslice levelling, defaults, the capacity-transfer set, cost and objective coefficients,
bounds. It reads the DD files a TIMES run reads and writes the sets and parameters TIMES holds just before the solve,
one table per symbol, from which `times_eq` (the folder next to this one) builds the equations. No GAMS anywhere
in it.

To run a whole model, use `TIMES.py` in the repository root; this page is about the preprocessor alone.
What is covered, attribute by attribute: [`FEATURES.md`](../FEATURES.md) (in the repository root).

Derived from the TIMES model generator ((C) IEA-ETSAP, GPL-3.0-or-later) and released under the same licence; see
`LICENSE` and `NOTICE.md`.

## How it reads

The steps are grouped by topic in `timespp/prep/`; `timespp/pipeline.py` lists them in the order TIMES runs them
in GAMS, and that list is what runs. **Every block of Python quotes the GAMS statements it replaces**
(`# --- <statement>`), so the code can be read against the TIMES source line by line. While it runs, the terminal
shows each phase with its time, and inside the longer phases each step as it finishes.

| Path | What |
|---|---|
| `timespp/__main__.py` | command line: run file -> the model's tables (`python -m timespp`) |
| `timespp/pipeline.py` | the phases and steps in the order of TIMES |
| `timespp/gamsdata.py` | reader for GAMS SET / PARAMETER data statements (DD files, `initsys.mod`, `initmty.mod`, `*.def`) |
| `timespp/engine.py` | sparse symbol store on DuckDB; `in_X()` / `v_X()` lookup macros; EPS = stored zero |
| `timespp/load.py`, `sysconst.py` | run file + declarations + DD files -> database; fixed system sets |
| `timespp/controls.py` | run-file switches (`OBJ`, `OBLONG`, `TIMESTEP`, ...) -> derived controls; `NotPorted` |
| `timespp/interp.py`, `lvl.py` | inter-/extrapolation (`fillparm.gms`, `prepparm.gms`, `filparam`), timeslice levelling (`pp_lvlfc`, `pp_lvlbr`, `pp_lvlus`) |
| `timespp/prep/` | the steps by topic: periods, timeslices and dynamic timeslice trees, interpolation, control sets, capacity, simulated vintages, flows and CHP, commodities, trade, storage, user constraints, defaults, VEDA attributes and coefficients, coefficients and costs, objective, bounds, myopic runs and FIXBOH, grids, discrete capacity, the residual load curve, the extensions (ancillary balancing services, elastic demands, TIMES-MACRO MLF, the climate module), the model reduction (`REDUCE`), stochastic TIMES (`STAGES`: the tree and the `S_*` attributes) |
| `timespp/refpoint.py` | the results of an earlier run that a run reads: its solution point (`LPOINT`, `FIXBOH`) and its base prices (`TIMESED`), from the Parquet files that an earlier run of this implementation wrote (a GDX file is not read) |
| `timespp/kernels.py`, `../jlkernels/` | Julia kernels: the same computation as a step's Python, in Julia, to the bit (below) |
| `timespp/tjb.py` | `model.tjb`, the binary copy of the tables the equations read, written as each table becomes final |
| `timespp/stream.py`, `export.py` | `model_parquet/` (one Parquet file per table, written as each becomes final) and `model.db3` |
| `timespp/declarations.json` | symbol domains, taken once from the v4.9.8 declarations |
| `timespp/times_src/` | the TIMES v4.9.8 declaration files the chain reads |
| `tools/pq2db3.py` | `model_parquet/` -> `model.db3` (one SQLite file) |
| `tools/gdx2sqlite.py` | the matrix or solution TIMES in GAMS writes (GDX) -> SQLite, for `TIMES.py --check` and `verify` |
| `tools/matrix_pq.py` | the matrix comparison of `--check`: both matrices as Parquet, compared entry by entry in DuckDB |
| `columns.txt` | column names of every symbol table |

## Run it alone

From this folder:

    python -m timespp <run folder>\<case>.run - <out folder>\model.db3 [--audit result.json] [--low-memory] [--memory 3GB]

The run file is read for its switches and its list of DD files; nothing is executed. The second argument is a TIMES
source folder whose declaration files are read, or `-` for the TIMES v4.9.8 declaration files in
`timespp/times_src`. The model is reduced as the run file's `REDUCE` says (`timespp/prep/reduce.py`), and both objective forms
(`OBJANN YES` or not) are covered. The results of earlier runs (`LPOINT`, `FIXBOH`, `TIMESED`) are read from the run
file's folder, as TIMES reads them (`timespp/refpoint.py`).

It writes `model.tjb` beside the path given (the binary copy the equations read, complete first) and then
`model.db3`. With `TIMESPP_DB3_STREAM=1` (what `TIMES.py` sets) it writes the folder `model_parquet/` in place of
`model.db3`, one Parquet file per table; the steps of a myopic run (`TIMESTEP`, or `FIXBOH`) go into
`model_steps.db3` beside it, and a run with `--low-memory` writes `model.db3` either way.
`python tools/pq2db3.py <out folder>\model_parquet` makes `model.db3` from the folder (with the steps, when there).
`--low-memory` keeps the tables in a work file beside the output instead of in memory, with DuckDB held to
`--memory` (default 3GB): slower, much less memory.

`--audit result.json` lists every unsupported feature of the model in one pass: each guard notes its feature and
goes on, so the list covers all steps rather than stopping at the first. This is what `TIMES.py` uses for the
`UNSUPPORTED` verdict.

## Julia kernels

Where a step's time is Python looping over rows, a Julia kernel can do the same computation instead: interpolation
(`fillparm`), the cost series (`fillcost`) and the objective coefficients (`objective`) are on by default once
`TIMES.py setup` has installed the kernels; `retirement` and `coef_ptr` exist and are off. The Python stays the
reference, with the GAMS lines quoted, and the kernel quotes them too.

`TIMESPP_KERNELS` chooses: unset, the defaults; `none`, no kernel and no Julia; a comma list; `check:<name>` runs the
Python and the kernel on every call and stops at the first table that differs. A kernel declines input it does not
cover, and the Python runs that call. How to add one: `jlkernels/README.md`.

## What a DD file may contain

The preprocessor reads DD files; it does not run GAMS code. A DD file may hold:

- **Data statements**: `SET`, `PARAMETER`, `SCALAR`, `TABLE` and `ALIAS`, with or without a domain, with
  `/ ... /` data, explanatory texts (quoted, or unquoted words up to the end of the line), `EPS`, `INF`, `NA`, and
  `$ONEPS` / `$OFFEPS`. In a key, a list in parentheses `(a,b,c)`, a label range `S-H01*S-H24` (the same text before
  a number that rises by one; numbers of the same width keep it) and `#set` (every member of a set read before)
  give one record each, as in GAMS. `%name%` is replaced by the value of a `$SET`, so a run file may give a list of
  labels once (`$SET NIGHT (W-H01*W-H06,S-H01*S-H05)`) and the DD files use it in their keys (`...%NIGHT%.UP 3`).
- **Directives that do not change the data**: `$ONEMPTY`, `$ONWARNING`, `$ONMULTI`, `$ONLISTING` and the like
  (with their `OFF` forms), `$TITLE`, comment lines and `$ONTEXT` ... `$OFFTEXT` blocks (also inside data),
  `$SET` / `$SETGLOBAL` / `$SETLOCAL`, and `$IF NOT SET <name> $SET <name> ...`.
- **`DISPLAY` statements**, which are ignored.
- **Assignments and loops**, applied where they stand to the data read before them, as GAMS does:

      SYM(i1,...,in)$(condition) = value;
      LOOP(set $(condition), statements);

  `SYM` is a parameter (or a scalar, without indices). Each index is a set or alias name (the statement runs over
  its members), a name a `LOOP` controls, a set name restricted to one label (`UC_N('X')`), or a quoted label
  (`'UP'`); an index named twice runs over the diagonal. The condition and the value may use numbers, `EPS`, `INF`,
  `YES`, `NO`, `ABS()`, `+ - * /`, the comparisons `< <= > >= = <>` (or `LT LE GT GE EQ NE`), `NOT`, `AND`, `OR`,
  `$`, any parameter or scalar read so far, any set (1 for a member, else 0), `SAMEAS(a,b)`, and
  `SUM`, `PROD`, `SMAX`, `SMIN` over a set or a list of sets, with a condition. A `LOOP` runs over a set or a list
  of sets, in the order of their labels, with any of these statements inside. Veda models use this form to clean
  up data at the end of a scenario file, for example:

      ACT_BND(R,DATAYEAR,P,S,BD)$((ACT_BND(R,DATAYEAR,P,S,BD)<3E-5)$ACT_BND(R,DATAYEAR,P,S,BD)) = EPS;

  or to switch off a list of user constraints:

      SET UCOFF / UC_A, UC_B /;
      LOOP(UCOFF, UC_RHSRT(R,UC_N,ALLYEAR,LIM)$SAMEAS(UCOFF,UC_N) = 0; );

  The statements applied, with the number of records each changed, are in `preprocess.log`.

The run file may include, besides the DD files, a file of the model's own GAMS code from the run folder (any file
that is not one of TIMES's, included with `$BATINCLUDE` or `$INCLUDE` without arguments). It is read where the run
file includes it, under the same rules as a DD file.

Anything else - another `$` directive (`$INCLUDE` in a DD file, other `$IF` forms, `$GOTO`...), an `OPTION` in a
DD file, an assignment or expression of another form (`ORD`, `CARD`, attributes such as `.L`...) - is reported as
unsupported input, with the file and the statement, and the run stops with the verdict `UNSUPPORTED`; a statement
refused inside a `LOOP` changes nothing. Nothing is skipped silently.

## Conventions

* One table per symbol; a parameter row with value 0 is a GAMS `EPS` (an explicit zero, on record). The row's
  absence means no value.
* Every block of Python quotes the GAMS statements it replaces, in the order GAMS runs them.
* A model that uses a feature not yet supported stops with `NotPorted` naming the feature. Nothing is silently
  skipped, approximated or defaulted.
* Where GAMS does something its documentation does not say (the order of a loop over a set, the arithmetic of a
  sum, the treatment of EPS), the code does what GAMS does and says so in a comment.
