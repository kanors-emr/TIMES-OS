# Feature models

Small TIMES models, each built to show one feature of TIMES — or one coherent, small set of
features — and nothing else. The library is two things at once:

- **the conformance suite**: a model that has been run against TIMES in GAMS carries the GAMS
  result beside it, and `python TIMES.py run models/<name>` compares the open chain with
  it, with no GAMS on the machine;
- **worked examples of TIMES**: each model's README says what it does, which attributes and
  tables it uses, and what to look at in the solution — the shortest way to learn how a TIMES
  feature behaves is to run a model that contains nothing else.

## Keep them small

A model here should run in HiGHS in well under a minute. That is not a convenience; it is the
point. A feature shown inside a full national model is buried under everything else the model
does, and a full model does not run in an open solver anyway. One feature, one small model, a
README. Start from `DemoS_012` and add one scenario file.

## What a model folder holds

```
models/<name>/
  README.md             what it demonstrates; attributes and tables used; what to look at; source; licence
  <case>.run, *.dd      the run folder, as Veda (or another VedaTL parser) wrote it — this is what runs; required
  source/               the Veda templates (Excel) the DD files were written from — optional, welcome
  expected.json         the GAMS result, when the model has been verified
  gams_solution.db3     the GAMS solution, when verified and under 5 MB  -> check 3 without GAMS
  gams_matrix.db3       the GAMS matrix, when verified and under 5 MB    -> check 4 without GAMS
```

A model is **verified** when `expected.json` is there: its GAMS result has been published and the
open chain reproduces it. A model without it is **contributed**: it runs (`SOLVED`) or it tells
the port what it lacks (`UNSUPPORTED`). Both are useful; the table below says which is which.

Run one, or all:

    python TIMES.py run models/DemoS_012
    python TIMES.py run models            # every model; runs/summary.txt has the verdicts

Files above 5 MB are not kept in the tree; they are attached to the GitHub release of the version
that introduced the model, and `expected.json` names them.

## Models

| Model | Shows | Rows | Status |
|---|---|---|---|
| `DemoS_012` | TIMES demo model, step 12: 2 regions, 11 periods, 6 timeslices; the base the others start from | 6,034 | verified (objective) |
| `TIMES-NZ` (to be added) | New Zealand energy system, Steady scenario, release 3.0.8 (EECA, MIT): the production-size case | 1,408,361 | verified; db3 as release assets |

## Contributing a model

A model is a contribution in its own right; it does not have to come with code, and it does not
have to reproduce anything. It has to go through Veda or another VedaTL parser to DD files, it has to be
documented, and it has to say **which version of TIMES in GAMS solves it** for you (the TIMES
source version, e.g. v4.9.8; the GAMS version and solver if you know them). No proof is asked
for — no listing, no numbers — but the port follows one version at a time.

1. Build it small: `DemoS_012` plus one scenario file or SubRES that switches the feature on.
2. Write the DD files (in Veda, a case with that scenario) and put the run
   folder under `models/<name>/`. Put the Excel templates under `source/` if you can.
3. Write `README.md` from the template below. Say the licence (the model must be redistributable)
   and the TIMES version it solves with.
4. Run it: `python TIMES.py run models/<name>`. `SOLVED` or `UNSUPPORTED` are both fine;
   say which in the pull request. `ERROR` is a defect of the port: report it.
5. Add a line to the table above.

Whether and when a contributed model is verified is decided by KanORS-EMR.

### README template for a model

```markdown
# <name>

**Shows**: <the TIMES feature, in one sentence>.

**Built from**: DemoS_012 + `Scen_<x>.xlsx` (or: standalone; or: <public model>, release <n>).

**Attributes and tables**: <NCAP_AFX, SHAPE, ~TFM_INS ...>.

**What to look at**: <the variables or rows where the feature is visible, and what you should see>.

**Size**: <rows / columns / non-zeros>; HiGHS solves it in <n> s.

**Solves with**: TIMES v<4.9.8> in GAMS <54.1>, <CPLEX> — no proof needed, the version is.

**Source**: <who built it, from what>. **Licence**: <CC BY 4.0 / MIT / ...>.
```

A verified model is changed only with a written reason: it is a result that has been shown to agree, never
something regenerated to make a test pass.
