# Contributing

This repository is maintained by KanORS-EMR for one purpose: to keep `main` an ever closer implementation of the
official TIMES, as released by IEA-ETSAP. What goes on `main` is decided with that purpose, by KanORS-EMR, at its
discretion. Maintained by KanORS-EMR; review capacity is limited and no response time is guaranteed.

## Reports

The most useful contribution, and one that needs no code. Run the model:

    python TIMES.py run <run folder> --bundle

and open an issue with `report_<case>.txt` (the issue templates ask for exactly what is needed), or attach the
bundle, which adds the logs, the run file, the DD files and the solver options (it holds the model's data: attach it
only when the model may be public). `UNSUPPORTED` comes with the list of every feature the model needs;
the features real models need weigh in what is done next. `NOT SOLVED`, `DIFFERENT` and `ERROR` are defects or
limits of the solver, and the report says where to look.

**A model that cannot be public.** Send the bundle by email to KanORS-EMR (times-os@kanors.com), not to
an issue, or better, a reduced sample that shows the problem, with sensitive data removed. It is treated in full
confidence, and only what the model shows about TIMES-OS (a missing feature, a difference) is fixed in the open.
KanORS-EMR's commitments for models submitted by 31 December 2026: [scope and
commitments](docs/scope-and-commitments.md).

## Models

A small model that shows one TIMES feature, redistributable, with a README, is welcome under `models/`
([`models/README.md`](models/README.md)). It has to run (`SOLVED`) or say what is missing (`UNSUPPORTED`), and its
README has to say which version of TIMES in GAMS solves it.

## Changes to the code

Pull requests are welcome and are read; whether one is merged is decided by KanORS-EMR.

- **A change that alters the model generated** (anything under `times_pp/timespp/` or `times_eq/src/`) is merged
  only when KanORS-EMR has found it to agree with TIMES in GAMS. Say in the pull request which model and TIMES
  version you checked it on, with the verdict line of `python TIMES.py run <run folder> --check` (it needs GAMS and the
  TIMES source; see [verification](docs/verification.md)), or what else you compared.
- **A feature that TIMES does not have** stays in your fork; the licence allows that. Offer it to IEA-ETSAP for TIMES
  itself: `main` takes only what official TIMES has.
- **Everything else** (usability, reporting, documentation, performance that leaves the model unchanged) is
  considered as it comes.

Keep the TIMES names in the code (`r, v, t, p, s`, the GAMS set and parameter names) and quote the TIMES statement a
block implements: that is what lets a reader check it against the TIMES source.

## Things that are easy to get wrong

- **EPS.** TIMES distinguishes an explicit zero (EPS) from no value. In the tables a row with value 0 is an explicit
  zero. In Julia a parameter read from such a row holds the sentinel `EPS` (`1e-200`): `P(...)` gives 0.0 when there
  is no entry and `EPS` for an explicit zero, `has(P, ...)` tells whether there is an entry at all, and `P[...]`
  insists on one. `EPS` tests as non-zero (so a product with it is `EPS`, not 0) and vanishes when added to a number;
  `iseps(x)` and `plain(x)` are the tests. `row!` drops a coefficient that comes out as `EPS` but still counts the
  variable as used.
- **Columns.** A variable exists only if it has a non-zero coefficient in some row; `times_eq` removes the others at
  the end.

## Style

The tests, after `python TIMES.py setup`:

    python -m pip install pytest
    python -m pytest times_pp\tests
    julia --project=times_eq -e "using Pkg; Pkg.test()"

Julia: `times_eq/.JuliaFormatter.toml`. Python: `ruff format` with the defaults.

Sign your commits off (`git commit -s`, which adds `Signed-off-by: Name <email>`), the
[Developer Certificate of Origin](https://developercertificate.org/): it says you have the right to contribute the
change under the project's licence.

## Commissioned work

A feature needed by a date, support for a model, or work on a fork: write to KanORS-EMR.

## Licence

Contributions are accepted under GPL-3.0-or-later, the licence of TIMES.
