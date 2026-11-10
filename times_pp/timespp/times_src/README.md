# TIMES declaration files (v4.9.8), carried with the port

These fifteen files are unchanged copies from the TIMES model generator, version 4.9.8
(https://github.com/etsap-TIMES/TIMES_model, tag v4.9.8). They are © IEA-ETSAP and licensed under the
GNU General Public License, version 3 or later, the same licence as this repository. See `NOTICE.md`.

They are here so that the open chain needs no TIMES source folder. A Veda run file includes TIMES's declaration
files (`$BATINCLUDE initsys.mod`, `initmty.mod`) before the DD files. The port reads their declaration and data
statements: the names and domains of the sets and parameters, and TIMES's fixed lists and defaults. It does not run
any GAMS code from them; the executable statements are skipped (`gamsdata.py`), and TIMES's logic is ported by hand.

| file | read by | for |
|---|---|---|
| `initsys.mod` | times_pp | system declarations |
| `units.def` | times_pp | unit lists |
| `maplists.def` | times_pp | the fixed classification sets |
| `globals.def` | times_pp | global defaults |
| `initmty.mod` | times_pp, times_rpt | model declarations; declaration texts for the .vde file |
| `initmty.vda` | times_pp | the declarations of the Veda VDA extensions |
| `initmty.abs` | times_pp | the declarations of the ancillary balancing services (read when the run file sets ABS=YES) |
| `initmty.tm` | times_pp | the declarations of TIMES-MACRO (read with `initmty.mlf`) |
| `initmty.mlf` | times_pp | the declarations of the linearised TIMES-MACRO, MLF (read when the run file sets MACRO=MLF) |
| `initmty.cli` | times_pp | the declarations and defaults of the climate module (read when the run file sets CLI=YES) |
| `initmty.stc` | times_pp | the declarations of stochastic TIMES (read when the run file sets STAGES=YES) |
| `times2veda.vdd` | times_rpt | which attributes go to the .vd file, and how |
| `times2veda_stc.vdd` | times_rpt | the same for a stochastic run (STAGES=YES): the attributes by state of the world |
| `solsetv.v3` | times_rpt | the set texts (ADESC) for the .vde file |
| `setglobs.gms` | times_rpt | declaration texts, read before solsetv.v3 |

When the port moves to another TIMES version, these files are replaced with that version's, together with the
port changes that version needs.
