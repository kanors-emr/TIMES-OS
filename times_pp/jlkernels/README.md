# TimesPPKernels: Julia kernels inside the preprocessor

A kernel does the computation of one preprocessor step in Julia instead of Python / SQL, with the same result to
the bit. The Python / SQL code stays where it is, as the readable reference with the GAMS lines quoted above each
statement, and a switch chooses between them. Off (the default) is the preprocessor without kernels, exactly.

- Julia code: this folder, the package `TimesPPKernels` (`src/`). `TIMES.py setup` adds it to `.julia_env`
  and precompiles it; after a change in `src/`, run `julia --project=.julia_env -e "using Pkg; Pkg.precompile()"`
  (or setup again).
- Python side: `timespp/kernels.py` (the switch, Julia's start, the hand-off, the check mode).

## The switch

`TIMESPP_KERNELS` is a comma list of kernel names, or `all`. `none` (or empty): no kernel, Julia is not started.
**Unset: the default kernels (`DEFAULT` in kernels.py: `fillparm`, `fillcost`, `objective`), when `setup` has installed TimesPPKernels.**
If it has not, or if Julia does not start, the Python code runs instead, and the log says so in one line
(`Julia kernels: ...`). A kernel asked for by name stops the run if Julia does not start.

- `TIMESPP_KERNELS=fillparm`: the kernel runs instead of the reference.
- `TIMESPP_KERNELS=check:fillparm` (or `check:all`): every call runs the reference, puts the tables back, runs the
  kernel and compares every table the call writes with the reference's result; the first difference stops the run
  with an error that names the table. This is the mode to develop with on whole models.

A kernel may decline a call it does not cover (raise `kernels.Decline` in Python, `throw(Decline(...))` in Julia):
the reference then runs that call. The preprocessor's log says how many calls each kernel declined, what the
kernels cost, and the start-up (`Julia kernels (TIMESPP_KERNELS): ...`; with `--audit`, also in `preprocess.json`).

Other variables: `TIMESPP_KERNELS_THREADS` (Julia's threads, default 1), `TIMESPP_JULIA_BINDIR` (where libjulia
is; setup writes it to settings.json as `julia_bindir`), `TIMESPP_KERNELS_PROJECT` (the Julia project, default
`.julia_env`).

## How Julia runs in the preprocessor

The preprocessor loads `libjulia` into its own Python process with ctypes and calls `jl_init` once, at the first
kernel call (0.13–0.17 s), then loads `TimesPPKernels` (0.2 s, precompiled). Julia leaves the signals to Python
(`--handle-signals=no`). Kernels are called through C function pointers (`@cfunction`, `src/abi.jl`): the columns go
in as pointers to NumPy buffers (no copy), the result comes back as new Julia vectors that Python copies, then frees.
Nothing crosses as a Julia or Python object, so the precompiled methods (plain `Vector{Int32}`, `Vector{Float64}`,
`Vector{UInt8}`, `Vector{Int64}`) are exactly what a run calls: the first call compiles nothing.

Why not juliacall / PythonCall.jl: importing juliacall took 2.1 s and its first call 1.1 s more
(PythonCall's own compilation), against 0.13 s and 0.2 s here; it also needs juliapkg, which installs PythonCall into
a Julia project of its own (network at the first run) and manages Julia's environment. A kernel needs only columns
of numbers in and out, which the C interface does without any of that. Both run on the Segment Heap copy of Python
(`.venv/segheap`).

Labels: a kernel sees integer codes. `kernels.Labels` keeps one code per label for the life of the database (the
DuckDB table `__klab`); `kernels.to_julia` makes the codes by a join in DuckDB, `kernels.from_julia` turns them back
into labels the same way. (Reading pandas categoricals instead was 5 times slower on the way back.)

## What identity takes (learnt on fillparm)

- The same arithmetic in the same order: `a / b * c` as written, `x + 0.0` kept where Python adds it, EPS as 1e-300
  inside the kernel and stored as 0 (the EPS row) on the way out, `ROUND` half away from zero. Python's `float **
  float` is the C library's `pow`: the kernel calls the same one (`cpow`), not Julia's `^`.
- The same records: the kernel gets exactly the rows the reference reads (the same NULL and year tests, in SQL), in
  table order, and the series in the order of their first record.
- Row order in a table is not part of identity: two runs of the same code can give a table's rows in another order
  (DuckDB inserts in parallel). The check mode compares rows as a multiset, each value to its Float64
  bits (so -0.0, 0.0, EPS and an absent row stay apart), and say "same rows, other order" when only the order moved.
- Where the reference would fail (a NaN option, a year label that is not an integer), the kernel declines, so the
  reference fails the same way.

## When the reference sums in an order Python chooses (learnt on objective)

A float sum depends on the order of its terms, so a kernel sums in the reference's order. Where the reference iterates
a list, that is the list's order, and the kernel builds the same list. Where it iterates a Python set, the order is
the set's slot order, a function of the elements' hashes and of the order they were added. `src/pyorder.jl`
reproduces it (`pyset_order`) for sets of tuples of small non-negative integers, whose hash Python takes from the
integers themselves (tuplehash). A set of labels (strings) cannot be reproduced: their hashes change with every
process (PYTHONHASHSEED). A reference that sums over such a set is not deterministic itself, and its kernel declines
or the reference is given a fixed order first.

- The objective's INVSPRED sets are sets of (year, year): reproduced, and checked again at every call against the
  sets Python itself builds from the kernel's rows (`prep/objective.py`; the kernel's call declines if one differs).
- `sum()` is not one function: up to Python 3.11 it adds left to right; from 3.12 it compensates (Neumaier).
  `PySum` does what the running Python does (the caller passes its version).
- Python raises where Julia goes on: a division by zero, a power or exp that overflows, ROUND of NaN, a key a dict
  does not have. `pydiv`, `pypow`, `pyexp`, `rnd`, `pyfloor`, `pyceil` and `need` decline instead, and the reference
  runs, and raises.
- `x ** y` is the C library's `pow`, `math.exp` its `exp` (`pypow`, `pyexp`); `max(a, b)` and `min(a, b)` keep the
  first argument unless the second is strictly greater (smaller), also against NaN (`pymax`, `pymin`).
- Rows of a table come back in any order: identity is to the rows (above). The order of the declarations does
  matter (the model's tables are written in it): a step that declares tables declares them before the switch, in the
  reference's order.

## The kernels

| kernel | step | what it takes | declines |
|---|---|---|---|
| `fillparm` | interpolation of the standard attributes | the series' interpolation | (see interp.py) |
| `fillcost` | interpolation of the cost attributes | the same, for the costs | (see costs.py) |
| `coef_ptr` | COEF_PTRAN (coefmain.mod) | the whole statement | not on by default: it does not pay |
| `objective` | objective coefficients (`prep/objective.py`) | `_investment`, `_fixed_costs`, `eoh`, the rows `_write_tables` stores; the SQL statements stay in Python | a myopic run (its steps read the Python records), cost bounds (REG_BNDCST, REG_CUMCST), audit mode, and what the reference stops on |
| `retirement` | the bounds of VAR_RCAP and VAR_SCAP (prepret.dsc, `prep/capacity.py`) | `_retirement_bounds`; the sets and SQL statements stay in Python; not on by default (a few seconds won where there is much retirement, lost where there is little) | PYR_S with more than one year when a forced refit sums over it |

