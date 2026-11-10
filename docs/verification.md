# Verification: agreement with TIMES in GAMS

TIMES-OS is accepted only where it builds the same model as TIMES in GAMS. For every verified case the optimisation
problem itself is compared with the one TIMES in GAMS builds from the same input files: every row and column matched
by name, every coefficient, right-hand side, constraint sense and bound. A matching objective value follows from
that; on its own it would prove little.

The coverage is stated attribute by attribute in [`FEATURES.md`](../FEATURES.md): 380 of the 452 input attributes
TIMES uses, about 84%. Most of the rest belong to specialised extensions, such as endogenous technology learning,
stand-alone MACRO and the IER extension. A model that uses anything not covered stops, and its report lists
everything it needs; nothing is silently changed.

## The check every release passes

    python TIMES.py run <run folder> --no-solve --check

GAMS runs TIMES once on a copy of the run file, with the same `REDUCE`, using the solver CONVERT, which writes the
model's matrix instead of solving it. TIMES-OS builds the same run. Then the two matrices are compared entry by entry,
by the rule below. Nothing is solved on either side: the matrix holds the whole model, its objective function
included, so a solve would add only the objective value (which a model with discrete capacity needs as well, see
below). The first line of `runs/<case>/report_<case>.txt` is the verdict: `SAME`, or `DIFFERENT` with the equations
and variables that differ. Every release of TIMES-OS passes this check on the open
reference models below before it is published; with it, anyone with GAMS can make the same check on a model of their
own.

It needs GAMS, with a licence for the size of the model (GAMS's free licence covers small models only), and the TIMES
source, v4.9.8, which is IEA-ETSAP's and not part of this repository
([etsap-TIMES/TIMES_model](https://github.com/etsap-TIMES/TIMES_model)). When `setup` finds GAMS, it fetches that
version of the source from there into `TIMES_model-v4.9.8/` (unless one is found already), and records where both
are; `setup --gams <gams executable> --times <TIMES source folder>` gives them when they are elsewhere, and
`--times <folder>` gives the source for one run. Without GAMS or the source, `--check` stops before anything is run
and says which is missing. With several cases, the matrices are compared after every case
has run; `python TIMES.py verify <result folder>` compares a finished case again.

**The rule.** Rows and columns are matched by name and labels, and each must be in both. Every coefficient is equal
within 1e-9 relative (plus 1e-12 absolute), an explicit zero on both sides (EPS in GAMS) counting as equal; every
right-hand side and bound is equal by the same rule, a right-hand side made of constants that cancel equal within 64
machine epsilons of their size.

**What it covers.** Every row and column of the model, its coefficients, right-hand sides and bounds, and the
objective. For a model with discrete capacity (the DSC extension), the variable types TIMES-OS gives for the solve
(binary, SOS1, semi-continuous) are outside the matrix comparison: compare such a model's objective as well, with
`--gams run`.

**Where the two may differ.** Nowhere in the model: any difference the check finds is a defect, to be reported. The
objective value, once the model is solved, may differ within the solver's tolerance, because a solver given the same
linear program with its rows and columns in another order stops at its own tolerance (for CPLEX, up to about 2e-9
relative with crossover and 2e-6 when its options stop the barrier without crossover).

`--gams run` also solves the model in GAMS and compares the objectives; a GAMS listing already in the run folder, as
Veda leaves it, is compared with in the same way, without running GAMS.

## Open reference models

The companion repository [**TIMES-OS-models**](https://github.com/kanors-emr/TIMES-OS-models) publishes 17 cases of
9 openly licensed TIMES models, from 3 thousand to 8.2 million rows, each with its input files and the result TIMES
v4.9.8 in GAMS gives for it. On every case TIMES-OS builds the same matrix as TIMES in GAMS, by the rule above, and
CPLEX finds the same objective value on both (within 2e-9 where it ends with crossover). The table there also gives,
case by case, the time and memory TIMES-OS takes to build the model against TIMES in GAMS, and how far HiGHS goes.
Each case folder runs as it is: `python TIMES.py run <case folder>` builds the model and compares its result with the
published one. The ten cases up to 1 million rows solve with HiGHS; the larger ones need a solver of that strength
(they were solved with CPLEX, `--lp cplex`). Each case folder also runs with `--check`. The evidence for TIMES-OS
1.0.0 is the repository's tag `v1.0.0`.

## The same check by hand

Where TIMES in GAMS runs elsewhere (for instance on another machine, or from Veda), the check can be made in three
steps. You need GAMS with TIMES v4.9.8 for the first step only.

**1. TIMES in GAMS: write the matrix with CONVERT.** In a copy of the run folder, add this line to the run file,
before the `$BATINCLUDE maindrv.mod` line:

    OPTION LP=CONVERT, MIP=CONVERT, RMIP=CONVERT;

and create `convert.opt` (and a copy named `convert.op2`) holding the one line

    jacobian gams.gdx

Run the case as usual. Instead of solving, GAMS writes the model's matrix to `gams.gdx`.

**2. TIMES-OS: write the same matrix.**

    python TIMES.py run <run folder> --no-solve --jacobian ours.gdx

`ours.gdx` is in the case's result folder (`runs/<case>/`), in the same layout as CONVERT's: rows and columns with
their TIMES names, the coefficients, right-hand sides and bounds.

**3. Compare the two.**

    python times_pp/tools/compare_jacobian.py runs/<case>/ours.gdx gams.gdx

The two files number rows and columns differently; the tool matches them by name and labels. Every coefficient must
be in both files and equal within 1e-9 relative (plus 1e-12 absolute; an explicit zero, EPS in GAMS, equals an
explicit zero), and every right-hand side and column bound likewise. If all holds, the report says the two are the
same linear program (exit status 0). If not, it lists the differences by equation and variable, with an example of
each and the first rows or columns that differ (exit status 1). On a large model, `--memory 16GB` and
`--temp <folder>` keep it within the machine's memory.

## Agreement with TIMES in GAMS

Each model of the library under [`models/`](../models/README.md) carries the result TIMES in GAMS gave for it
(`expected.json`; where size allows, the GAMS solution and matrix). `run` compares with those on its own, with no
GAMS on the machine:

    python TIMES.py run models/DemoS_012
    python TIMES.py run models            # all of them; runs/summary.txt has the verdicts

Beyond the library, the same linear program as TIMES in GAMS, every coefficient, right-hand side and bound matched
by name, has been obtained on public models such as these:

| Model | Rows | Columns | Coefficients |
|---|---:|---:|---:|
| DemoS_012 (TIMES demo, step 12; standard objective), as shipped (`REDUCE YES`) | 6,034 | 8,456 | 37,064 |
| DemoS_012, without the reduction (`TIMES_REDUCE=NO`) | 16,215 | 18,129 | 63,720 |
| TIMES-NZ v3.0.8, Steady scenario (EECA, MIT), without the reduction | 1,408,361 | 1,299,224 | 5,066,303 |
| TIMES-NZ v3.0.8, Shift scenario (EECA, MIT), without the reduction | 1,483,415 | 1,371,716 | 5,415,901 |

and on production models of up to 19 million rows and 120 million coefficients.
