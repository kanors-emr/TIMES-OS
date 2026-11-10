# DemoS_012

**Shows**: the TIMES demonstration model at step 12 — a complete small energy system, the base
every other model in the library starts from.

**Built from**: the VEDA-TIMES demo models (DemoS_012), as Veda writes the run folder.

**Attributes and tables**: the ordinary set — processes and commodities (`~FI_T`, `~FI_PROCESS`,
`~FI_COMM`), demand projections, `~TFM_INS`, user constraints, trade between two regions,
peak reserve, emissions.

**What to look at**: `VAR_NCAP` and `VAR_ACT` by period; the objective (25,268,554.43 with the
annualised objective, 25,271,809.43 with the standard one).

**Size**: 6,034 rows / 8,456 columns / 37,064 non-zeros (the run file as shipped: `REDUCE YES`, standard objective);
16,215 / 18,129 / 63,720 without the reduction (`TIMES_REDUCE=NO`). HiGHS solves it in a few seconds.

**Solves with**: TIMES v4.9.8 in GAMS 54.1.0, CPLEX (the same matrix and objective as with v4.9.7).

**Source**: IEA-ETSAP / KanORS-EMR demo models. **Licence**: CC BY 4.0 (model data).
