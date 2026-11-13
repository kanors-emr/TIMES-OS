# times_rpt — the TIMES report writer

The TIMES report, in Python: the report parameters TIMES computes after the solve (`rptmain.rpt` and the files it
includes), under their GAMS names, and the Veda result files (`.vd`, `.vde`, `.vds`) that GDX2VEDA writes from them,
driven by `times2veda.vdd` as in TIMES.

`TIMES.py run` calls it after the solve. Alone:

```
python times_rpt/timesrpt/write.py <model tables> <solution.db3> <out folder> <scenario> <TIMES source | -> [<preprocess.json>]
```

`<model tables>` is the `model_parquet/` folder `times_pp` writes, or a `model.db3`; `<solution.db3>` is the solution
`TIMES.py` writes. `-` for the TIMES source uses the TIMES v4.9.8 files carried in `times_pp/timespp/times_src`
(`times2veda.vdd` among them). It writes `<scenario>.vd`, `.vde` and `.vds` in `<out folder>`, and
`<scenario>_report.json`. The tables carry what the files need beyond the sets and parameters: the spelling of the
labels and the explanatory texts of the DD files; the run controls (MID_YEAR, the objective form) come from the
switches in `preprocess.json` (the file `times_pp --audit` writes), which is optional.

| Path | What |
|---|---|
| `timesrpt/write.py` | the files of a run |
| `timesrpt/load.py` | the model's tables and the solution into one DuckDB database |
| `timesrpt/rpt*.py`, `solflo.py`, `cost_ann.py`, `eqobjvar.py` | the report files of TIMES, one module per GAMS file or block, under the GAMS names |
| `timesrpt/vd.py`, `vsets.py` | GDX2VEDA's part: dimensions, the `not-0` option, attributes fed by several parameters |
| `timesrpt/switches.py` | the report options of a run (`RPT_OPT` in the data, `$SET` switches) and which are covered |
| `timesrpt/results.py` | the results later runs read, as TIMES writes them: the solution point `<run>_p` (after every solve), the base prices `<run>_DP` and `com_bprice` (`TIMESED NO`), as Parquet |
| `timesrpt/stochastic.py` | the report of a stochastic run, by state of the world (`times2veda_stc.vdd`) |
| `timesrpt/mlf.py`, `rptcli.py` | the report of TIMES-MACRO MLF (`VAR_Macro`) and of the climate module (`VAR_Climate`, `Dual_clic`) |

**What is written.** The attributes of a plain run, and those of the report options most Veda models set (`FLO.5`,
`NCAP.1`, `FLO.3`, `COMPRD.1`, `ELC.1`, `ACT.2`, `ELC.3`, `COMPRD.4`, `OBJ.1`, and the levelized annual costs of
`OBJ.2` and `$SET ANNCOST LEV`), are written as GDX2VEDA writes them. So are those of the other report options:
the topology (`FLO.7`, or `$SET RPT_TOP YES`: `PAR_Top`), flows at ANNUAL (`$SET RPT_FLOTS ANNUAL`, or a negative
`RPT_OPT(<commodity type>,'3')`), the levelized cost with the credit of the ENV commodities (`NCAP.1` below 0) or
with the peak capacity credit (`NCAP.1` above 1), and the cost-benefit indicators of new capacity
(`$SET BENCOST YES`: `VAR_NcapR` COST, CGAP, GGAP, RATIO, GRATIO; without the ranging information of the solver,
and without the costs of capacity-related flows, which the run report names when a model has them). The cost of
elastic demands is `Cost_Els`. A run with `FIXBOH` reports its fixed periods from the solution point it loads, as
TIMES does (`timesrpt/loadedpoint.py`). Not written: the damage costs (`Cost_Dam`).
A report option whose block is not covered is named in the run report; nothing is written for it.

**A solution from HiGHS.** The objective is that of TIMES in GAMS. Where the LP has more than one optimum, the flows
and marginals are those of the optimum HiGHS found, which can differ from the one another solver finds; and a zero
marginal that GAMS writes as EPS is not marked as EPS.

**From run to run.** With more than one thread, the rows of the `.vd` file can come in another order and the last
digits of some values can differ between two runs on the same model and solution. Set `TIMESPP_THREADS=1` (the
threads of DuckDB, which this writer shares with `times_pp`) for files that are the same from run to run.

## Licence

GPL-3.0-or-later, the licence of TIMES. See `NOTICE.md`.
