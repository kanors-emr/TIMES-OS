# TimesEq — the TIMES equations in Julia/JuMP

This package takes a TIMES model that has already been preprocessed (by `times_pp`, the folder next to this one)
and states its equations as a JuMP model. Any LP solver that JuMP supports can then solve it; `TIMES.py` uses
HiGHS.

    DD files --times_pp--> tables --TimesEq (Julia/JuMP)--> solver

```julia
using TimesEq, JuMP, HiGHS
d = TimesEq.load("model.db3")       # the path times_pp was given
m = TimesEq.build(d)
set_optimizer(m.jump, HiGHS.Optimizer)
optimize!(m.jump)
```

`load` takes the path of `model.db3` and reads the `model.tjb` beside it instead when that file is of the same run
(`TIMESEQ_TJB=0`: always `model.db3`). It does so also when `times_pp` wrote the folder `model_parquet/` in place of
`model.db3`; without `model.tjb`, make `model.db3` from the folder first (`times_pp/tools/pq2db3.py`).

To run a model from its DD files, use `TIMES.py` in the repository root; its README is the place to start.
This page is about the equations alone. `examples/demos012.jl <model.db3>` loads, builds and solves the example
model from the output of `times_pp` and prints the rows of each equation, the columns, the coefficients and the
objective next to those of TIMES in GAMS.

## How the equations are written

Each equation family is one function in its own file under `src/equations/`, with the algebra in the docstring and
the same thing in code below it, and the GAMS file it follows named at the top:

```julia
"""
    EQ_PTRANS(r,v,t,p,cg1,cg2,s)

    SUM(c in cg2, flow(c) at s)  =  SUM(c in cg1, COEF_PTRAN(r,v,p,cg1,c,cg2,ts) * flow(c) at s)
"""
function eq_ptrans!(m::Model)
    (; RTP_VINTYR, RP_STD, RS_TREE, COEF_PTRAN) = m.d                      # sets and parameters used
    (; ffunc, rps_s1, flow_cs, flow_s, group_c, rpc_c, ts_tree) = m.ix     # lookups used

    for (r, v, t, p) in RTP_VINTYR, (cg1, cg2) in ffunc[r, p], s in rps_s1[r, p]      # rows
        (r, p) in RP_STD || continue
        any(has(COEF_PTRAN, r, v, p, cg1, c, cg2, ts) for c in rpc_c[r, p] for ts in ts_tree[r, s]) || continue

        driven = @expression(m.jump, sum(frac(m, r, t, c, s, ts) * flow(m, r, v, t, p, c, ts)
            for c in group_c[r, cg2] for ts in flow_s[r, t, p, c] if (r, s, ts) in RS_TREE))

        driving = @expression(m.jump, sum(COEF_PTRAN(r, v, p, cg1, c, cg2, ts) * frac(m, r, t, c, s, ts) * flow(m, r, v, t, p, c, ts)
            for (c, ts) in flow_cs[r, t, p] if (r, s, ts) in RS_TREE && has(COEF_PTRAN, r, v, p, cg1, c, cg2, ts)))

        row!(m, :EQ_PTRANS, (r, v, t, p, cg1, cg2, s), driven, ==, driving)
    end
end
```

- Names are the TIMES names. `COEF_PTRAN(...)` is a parameter value (0 when absent), `(r, p) in RP_STD` a set
  membership, `VAR_FLO(...)` a variable.
- `src/schema.jl` declares every set, parameter and variable the equations read, with named columns. Nothing else is
  read, and a table with the wrong number of columns is rejected.
- Variables are created when an equation first uses them, with the bounds given in the input. Zero coefficients are
  dropped, rows without variables are not generated, and variables that end up in no row are removed. This is what
  GAMS does, which is why the matrix has the same size.
- GAMS has a second zero, EPS: a zero that is on record. A parameter entry of EPS reads as the constant `EPS` here;
  a coefficient that comes out as EPS keeps the variable in the row and in the model, as in GAMS, and is counted and
  listed but not passed to the solver (`row!`). Compare such a value through `plain(x)`.
- Terms used by several equations (a flow brought to another timeslice, trade, installed capacity) are in
  `src/terms.jl`.
- Input that needs a feature not yet supported is listed in `UNSUPPORTED` in `src/schema.jl`, or stops where the
  equations meet it (`TIMES feature not supported yet`): `build` stops with a message naming the feature rather than
  building a model that ignores it. `TimesEq.unread(d)` shows every non-empty input table the equations do not read.

## Solving

`TIMES.py` solves the model with HiGHS by default. Around the equations:

- `src/steps.jl`: a myopic run (`TIMESTEP`) step by step, and a `FIXBOH` run, as `solve.stp` does;
- `src/gamslp.jl`: an MOI optimizer that hands the LP to an LP solver of the user's GAMS through a GDX
  (`gams/solve_lp.gms`, or a program by TIMES's names with `--lp-names`) and reads the solution back;
  `solvers/gurobilp.py`: Gurobi through its Python interface;
- `src/stochastic.jl`: stochastic TIMES (`STAGES`): every equation and variable by state of the world, and the
  expected cost as the objective; `addons/TimesEqStochastic`: a package with no model code, which compiles the
  equations ahead for the stochastic variable families (`STAGES`, `SPINES`). `TIMES.py setup` compiles it, or the
  first run of such a model where it is missing; `tools/run_case.jl` loads it for those runs;
- `src/negishi.jl`: TIMES-MACRO MLF, the calibration of MACRO (an NLP solved with Ipopt) and the Negishi iterations
  around the linearised model (`equations/mlf.jl`).

## Building in parallel

The equation families are computed on several threads at once and added to the model one after another, in a fixed
order, so the model is the same, row for row and column for column, whatever the number of threads. The longest
families are computed in pieces. `TIMES.py` starts Julia with the threads and settings it needs.

## Looking at a model

- `TimesEq.row_counts(m)`, `column_counts(m)`, `nonzeros(m)`
- `TimesEq.write_triplets("model.csv", m)`: every coefficient as (equation, row, variable, column, value). Two
  implementations of TIMES agree when this table is the same.
- `TimesEq.build(d; names = true)` followed by `JuMP.write_to_file(m.jump, "model.lp")` for a readable LP file.
- `TimesEq.write_matrix(m, folder)`: the matrix (rows, columns, coefficients, right-hand sides and bounds, with the
  names and labels) as plain binary files in a folder. `TIMES.py run --jacobian <file>` calls it and writes the
  folder as a GDX in the layout of the jacobian GDX of GAMS's CONVERT solver (`times_pp/tools/jacobian_gdx.py`);
  `times_pp/tools/compare_jacobian.py` compares two such files by the names of the rows and columns.

## Speed

The example model, DemoS_012, loads in about a second and builds in a fraction of one once Julia has compiled
(`TIMES.py setup` compiles ahead). On models of a million rows and more the build takes tens of seconds; on the
largest models run so far (19 million rows) about 30 seconds on 24 threads, faster than GAMS generates the same model.

## Licence

GPL-3.0-or-later, the licence of TIMES, which this package follows. See `LICENSE` and `NOTICE.md`.

## Credits

The equations are those of TIMES, developed and maintained by IEA-ETSAP (GAMS source:
https://github.com/etsap-TIMES/TIMES_model, GPL-3.0). The equation files name the GAMS file each one follows.
This is an independent project of KanORS-EMR and not an ETSAP product. KanORS-EMR is responsible for the code.
