# What is covered: TIMES v4.9.8 input attributes

Every input attribute TIMES v4.9.8 declares, and what this implementation does with it. A model that uses an
attribute, or a use of an attribute, that is not supported stops with the verdict `UNSUPPORTED` and lists all it
needs; nothing is skipped or approximated.

**Status** is one of:
- **supported**: read and used as TIMES uses it;
- **supported, refused in some uses**: the message names the use that stops (for example an option or a combination
  with another attribute);
- **refused**: a model with data in it stops, with a message naming it;
- **not yet supported**: an extension this implementation does not cover yet (TIMES-MACRO other than its linearised form
  MLF, damage, ETL, experimental declarations), named in the message;
- **not read**: declared as an input and not read by this implementation (one set, `REF`);
- **not used by TIMES**: declared in TIMES and never read by it.

The model reduction of the run file (`$SET REDUCE`) is supported at TIMES's three levels: `NO`; `YES` (flows replaced
by the activity, processes without an activity variable, processes turned off by a zero activity bound); any other
value or none (the capacity variables and the emissions of `FLO_SUM` on input flows only). It changes no attribute's
status.

## The attributes

By area, as the TIMES declarations group them; each attribute with its domain and the description TIMES gives it.

| | count |
|---|---:|
| attributes in all | 472 |
| supported | 344 |
| supported, refused in some uses | 36 |
| refused | 7 |
| not yet supported | 64 |
| not read | 1 |
| not used by TIMES | 20 |

### activity

| attribute | kind | status |
|---|---|---|
| `ACT_BND`(REG,ALLYEAR,PRC,TS,BD) Bound on activity of a process | parameter | supported |
| `ACT_COST`(REG,ALLYEAR,PRC,CUR) Variable costs associated with activity of a process | parameter | supported |
| `ACT_CSTRMP`(R,ALLYEAR,P,L,CUR) Ramp-up (L=UP) or ramp-down (L=LO) cost per unit of load change | parameter | supported |
| `ACT_CSTSD`(R,ALLYEAR,P,UPT,BD,CUR) Start-up (BD=UP) and shutdown costs (BD=LO) per unit of started-up capacity, by start-up type | parameter | supported, refused in some uses: discrete unit commitment (DUC=YES: binary on-line indicators, eqlducs.vda) |
| `ACT_CSTUP`(R,ALLYEAR,P,TSLVL,CUR) Variable costs associated with startup of a process | parameter | supported |
| `ACT_CUM`(REG,PRC,ITEM,ITEM,LIM) Bound on cumulative activity | parameter | supported |
| `ACT_FLO`(REG,ALLYEAR,PRC,CG,S) General process transformation parameter | parameter | supported |
| `ACT_TIME`(R,ALLYEAR,P,L) Minimum online/offline hours | parameter | supported |

### attributes for experimental ecb extension

| attribute | kind | status |
|---|---|---|
| `COM_MSHGV`(R,YEAR,C) Choices heterogeneity parameter | parameter | not yet supported: experimental extension (TIMES's own 'experimental' declarations) |
| `NCAP_MSPRF`(R,YEAR,C,P,LIM) Preference parameters in choice | parameter | not yet supported: experimental extension (TIMES's own 'experimental' declarations) |

### basic sets

| attribute | kind | status |
|---|---|---|
| `DM`(COM) | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `MITER`() | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `MR`(REG) | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `MRTC`(REG,YEAR,COM) | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `NITER`() | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `TB`(T) | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `TM_DAM`(R,ITEM) | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `TM_DD`(R,C,T) | parameter | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `TM_DDF_DM`(R,T,C) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DDF_SP`(R,T,C) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DDF_Y`(R,T) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DEFVAL`() | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DEM`(REG,YEAR,COM) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DMC`(REG,YEAR,COM) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_F2`(R,T,C) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_GDP`(REG,YEAR) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_HSX`(R,YEAR) Hockey-stick exponent | parameter | not yet supported: MACRO (MSA); accepted in a run without MACRO that is not stepped (TIMESTEP, FIXBOH) |
| `TM_MDTL`(R) Market damage linear coeff. | parameter | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `TM_MDTQ`(R) Market damage quadratic coeff. | parameter | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |
| `TRD`() | set | not yet supported: MACRO (MSA); accepted in a run without MACRO, which does not read it |

### capacity installed

| attribute | kind | status |
|---|---|---|
| `CAP_BND`(REG,ALLYEAR,PRC,BD) Bound on total installed capacity in a period | parameter | supported |
| `NCAP_SEMI`(R,ALLYEAR,P) Semi-continuous capacity, lower bound | parameter | supported, refused in some uses: discrete capacity without the DSC extension (the run file sets neither DSC nor DSCAUTO) |
| `NCAP_START`(REG,PRC) Start year for new investments | parameter | supported |

### climate module time-dependent parameters

| attribute | kind | status |
|---|---|---|
| `CM_COUPLE`(CM_ITEM,YEAR,CM_ITEM,CM_Q) Coupled impact on concentration | parameter | refused: coupled concentrations of the climate module (ppm_ext.cli 19-41, coef_ext.cli 42-51) |
| `CM_DECAY`(CM_ITEM,CM_Q) Annual decay of concentration | parameter | refused: user-defined decays of the climate module (ppm_ext.cli 34, coef_ext.cli 34-41) |
| `CM_EXOFORC`(ALLYEAR) Radiative forcing from exogenous sources | parameter | supported |
| `CM_HISTORY`(ALLYEAR,CM_ITEM) Calibration values for CO2 and forcing | parameter | supported |
| `CM_LINFOR`(ALLYEAR,CM_ITEM,LIM) Linearized forcing function | parameter | supported |
| `CM_MAXC`(ALLYEAR,ITEM) Maximum level of climate variable | parameter | supported |
| `CM_MAXCO2C`(ALLYEAR) Maximum allowable atmospheric CO2 concentration | parameter | supported |
| `CM_STATS`(CM_ITEM,ALLYEAR,CM_Q) Calibration values for CO2 and forcing | parameter | supported |
| `UC_CLI`(UC_N,SIDE,REG,ALLYEAR,CM_ITEM) Climate variable | parameter | supported |

### commodities

| attribute | kind | status |
|---|---|---|
| `COM`(COM_GRP) All Commodities | set | supported |
| `COM_DESC`(REG,COM) Region-based commodity descriptions | set | supported |
| `COM_GMAP`(REG,COM_GRP,COM) User groups of individual commodities | set | supported |
| `COM_GRP`() All CGs and each individal commodity | set | supported |
| `COM_LIM`(REG,COM,LIM) List of equation type for balance | set | supported |
| `COM_OFF`(REG,COM,*,*) Periods for which a commodity is unavailable | set | supported |
| `COM_TMAP`(REG,COM_TYPE,COM) Primary grouping of commodities | set | supported |
| `COM_TS`(REG,COM,ALL_TS) List of commodity timeslices | set | supported |
| `COM_TSL`(REG,COM,TSLVL) Level at which a commodity tracked | set | supported |
| `COM_TYPE`(COM_GRP) Primary grouping of commodities | set | supported |
| `COM_UNIT`(REG,COM,UNITS_COM) Units associated with each commodity | set | supported |

### currency

| attribute | kind | status |
|---|---|---|
| `CUR`() Currencies (c$) | set | supported |
| `CUR_MAP`(REG,CUR_GRP,CUR) Grouping of the currenies | set | not used by TIMES |

### damage input parameters

| attribute | kind | status |
|---|---|---|
| `DAM_BQTY`(REG,COM) Base quantity of emissions | parameter | not yet supported: damage costs (DAMAGE extension) |
| `DAM_COST`(REG,ALLYEAR,COM,CUR) Marginal damage cost of emissions | parameter | not yet supported: damage costs (DAMAGE extension) |
| `DAM_ELAST`(REG,COM,LIM) Elasticity of damage cost | parameter | not yet supported: damage costs (DAMAGE extension) |
| `DAM_STEP`(REG,COM,LIM) Step number for emissions up to base | parameter | not yet supported: damage costs (DAMAGE extension) |
| `DAM_VOC`(REG,COM,LIM) Variance of emissions | parameter | not yet supported: damage costs (DAMAGE extension) |

### decommissioning of capacity

| attribute | kind | status |
|---|---|---|
| `NCAP_DCOST`(REG,ALLYEAR,PRC,CUR) Cost of decomissioning | parameter | supported |
| `NCAP_DELIF`(REG,ALLYEAR,PRC) Economic lifetime to pay for decomissioning | parameter | supported |
| `NCAP_DLAG`(REG,ALLYEAR,PRC) Delay to begin decomissioning | parameter | supported |
| `NCAP_DLAGC`(REG,ALLYEAR,PRC,CUR) Cost of decomissioning delay | parameter | supported |
| `NCAP_DLIFE`(REG,ALLYEAR,PRC) Time for the actual decomissioning | parameter | supported |
| `NCAP_OCOM`(REG,ALLYEAR,PRC,COM) Commodity release during decomissioning | parameter | supported |
| `NCAP_VALU`(REG,ALLYEAR,PRC,COM,CUR) Value of material released during decomissioning | parameter | supported, refused in some uses: late revenues of decommissioning flows (NCAP_VALU with NCAP_OCOM, eqobsalv.mod) |

### demands

| attribute | kind | status |
|---|---|---|
| `COM_BPRICE`(REG,ALLYEAR,COM,TS,CUR) Base price of elastic demands | parameter | supported |
| `COM_BQTY`(REG,COM,TS) Base quantity for elastic demands | parameter | supported |
| `COM_ELAST`(REG,ALLYEAR,COM,TS,LIM) Elasticity of demand | parameter | supported |
| `COM_ELASTX`(REG,ALLYEAR,COM,BD) Elasticity shape of demand | parameter | refused: demand elasticity shape curves (COM_ELASTX) |
| `COM_PROJ`(REG,ALLYEAR,COM) Demand baseline projection | parameter | supported |
| `COM_STEP`(REG,COM,LIM) Step size for elastic demand | parameter | supported |
| `COM_VOC`(REG,ALLYEAR,COM,BD) Variance of elastic demand | parameter | supported |

### demands / emissions / financials

| attribute | kind | status |
|---|---|---|
| `DEM_SMAP`(REG,DEM_SECT,COM) Grouping of DEMs (commodities) to their sector | set | not used by TIMES |
| `ENV_MAP`(REG,ENV_GRP,COM) Grouping of ENVs (commodities) to their emissions group | set | not used by TIMES |
| `FIN_MAP`(REG,FIN_GRP,COM) Grouping of FINs (commodities) to their financial group | set | not used by TIMES |

### energy

| attribute | kind | status |
|---|---|---|
| `NRG_FMAP`(REG,NRG_FORM,COM) Grouping of NRG by Solid/Liquid/Gas | set | not used by TIMES |
| `NRG_GMAP`(REG,NRG_GRID,COM) Association of energy carriers to grids | set | supported |
| `NRG_TMAP`(REG,NRG_TYPE,COM) Grouping of energy carriers by type | set | supported |

### experimental parameters

| attribute | kind | status |
|---|---|---|
| `DAM_COEF`(REG,ALLYEAR,COM,S) Coefficient from commodity to damage | parameter | not yet supported: experimental extension (TIMES's own 'experimental' declarations) |
| `DAM_TQTY`(REG,ALLYEAR,COM) Base quantity of emissions by year | parameter | not yet supported: experimental extension (TIMES's own 'experimental' declarations) |
| `DAM_TVOC`(REG,ALLYEAR,COM,LIM) Variance of emissions by year | parameter | not yet supported: experimental extension (TIMES's own 'experimental' declarations) |

### flow of commodities through processes

| attribute | kind | status |
|---|---|---|
| `FLO_BDLVL`(REG,ALLYEAR,PRC,CG,S,BD) Bound on the flow variable by hourly rate level | parameter | supported |
| `FLO_BND`(REG,ALLYEAR,PRC,CG,TS,BD) Bound on the flow variable | parameter | supported |
| `FLO_COST`(REG,ALLYEAR,PRC,COM,TS,CUR) Added variable O&M of using a commodity | parameter | supported |
| `FLO_CUM`(REG,PRC,COM,ITEM,ITEM,LIM) Bound on cumulative flow | parameter | supported |
| `FLO_DELIV`(REG,ALLYEAR,PRC,COM,TS,CUR) Delivery cost for using a commodity | parameter | supported |
| `FLO_FEQ`(REG,ALLYEAR,PRC,COM) Fossil equivalent of a commodity in a process | parameter | not used by TIMES |
| `FLO_FR`(REG,ALLYEAR,PRC,COM,TS,LIM) Load-curve limitations for a process commodity flow | parameter | supported |
| `FLO_FUNC`(REG,ALLYEAR,PRC,CG,CG,TS) Relationship between 2 (group of) flows | parameter | supported |
| `FLO_FUNCX`(REG,ALLYEAR,PRC,CG,CG) Change in FLO_FUNC/FLO_SUM by age | parameter | supported |
| `FLO_MARK`(REG,ALLYEAR,PRC,COM,BD) Process-wise market share in total commodity production | parameter | supported |
| `FLO_SHAR`(REG,ALLYEAR,PRC,C,CG,TS,BD) Relationship between members of the same flow group | parameter | supported |
| `FLO_SUB`(REG,ALLYEAR,PRC,COM,TS,CUR) Subsidy for the production/use of a commodity | parameter | supported |
| `FLO_SUM`(REG,ALLYEAR,PRC,CG,C,CG,TS) Multipier for commodity in cg1 where each is summed into cg2 | parameter | supported |
| `FLO_TAX`(REG,ALLYEAR,PRC,COM,TS,CUR) Tax on the production/use of a commodity | parameter | supported |
| `PRC_MARK`(REG,ALLYEAR,PRC,ITEM,C,LIM) Process group-wise market share | parameter | supported |
| `PRC_REFIT`(REG,PRC,PRC) Process with retrofit or life-extension | parameter | supported |
| `PRC_RESID`(REG,ALLYEAR,PRC) Residual capacity available in each period | parameter | supported |

### general commodities

| attribute | kind | status |
|---|---|---|
| `COM_AGG`(REG,ALLYEAR,COM,COM) Commodity aggregation parameter | parameter | supported, refused in some uses: elastic demands aggregated into other demands (CES demand aggregation with TIMESED: COM_AGG between demands) |
| `COM_BNDNET`(REG,ALLYEAR,COM,TS,LIM) Net bound on commodity (e.g., emissions) | parameter | supported |
| `COM_BNDPRD`(REG,ALLYEAR,COM,TS,LIM) Limit on production of a commodity | parameter | supported |
| `COM_CSTNET`(REG,ALLYEAR,COM,TS,CUR) Cost on Net of commodity (e.g. emissions tax) | parameter | supported |
| `COM_CSTPRD`(REG,ALLYEAR,COM,TS,CUR) Cost on production of a commodity | parameter | supported |
| `COM_CUMNET`(REG,BOHYEAR,EOHYEAR,COM,LIM) Cumulative net bound on commodity (e.g. emissions) | parameter | supported, refused in some uses: cumulative commodity bounds with OBJ LIN (eqcumcom.mod weights periods with TPULSE) |
| `COM_CUMPRD`(REG,BOHYEAR,EOHYEAR,COM,LIM) Cumulative limit on production of a commodity | parameter | supported, refused in some uses: cumulative commodity bounds with OBJ LIN (eqcumcom.mod weights periods with TPULSE) |
| `COM_FR`(REG,ALLYEAR,COM,TS) Seasonal distribution of a commodity | parameter | supported |
| `COM_IE`(REG,ALLYEAR,COM,TS) Seasonal efficiency of commodity | parameter | supported |
| `COM_SUBNET`(REG,ALLYEAR,COM,TS,CUR) Subsidy on a commodity net | parameter | supported |
| `COM_SUBPRD`(REG,ALLYEAR,COM,TS,CUR) Subsidy on production of a commodity net | parameter | supported |
| `COM_TAXNET`(REG,ALLYEAR,COM,TS,CUR) Tax on a commodity net | parameter | supported |
| `COM_TAXPRD`(REG,ALLYEAR,COM,TS,CUR) Tax on production of a commodity net | parameter | supported |

### globals

| attribute | kind | status |
|---|---|---|
| `G_CHNGMONY`(REG,ALLYEAR,CUR) Exchange rate for currency | parameter | not used by TIMES |
| `G_CUREX`(CUR,CUR) Global currency conversions | parameter | supported |
| `G_DRATE`(REG,ALLYEAR,CUR) Discount rate for a currency | parameter | supported |
| `G_OFFTHD`(ALLYEAR) Threshold for OFF ranges | parameter | supported |
| `G_OVERLAP`() Overlap of stepped solutions (in years) | parameter | supported |
| `G_RFRIR`(REG,ALLYEAR) Riskfree real interest rate | parameter | supported |
| `G_YRFR`(ALL_REG,TS) Seasonal fraction of the year | parameter | supported |
| `REG_BDNCAP`(ALL_R,L) Year up to which VAR_NCAPs are to be fixed | parameter | supported |
| `REG_FIXT`(ALL_R) Year up to which periods are fixed | parameter | supported |
| `R_CUREX`(ALL_REG,CUR,CUR) Regional currency conversions | parameter | supported |
| `TS_CYCLE`(REG,TS) Length of cycles below timeslice, in days | parameter | supported |

### input aliases

| attribute | kind | status |
|---|---|---|
| `ALPH`(R,KP,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `BETA`(R,KP,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `CCAP0`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `CCAPK`(R,KP,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `CCAPM`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `CCOST0`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `CCOSTK`(R,KP,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `CCOSTM`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `CLUSTER`(R,P,P) | parameter | not yet supported: endogenous technology learning (ETL) |
| `KP`() | set | not yet supported: endogenous technology learning (ETL) |
| `NTCHTEG`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `PAT`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `PBT`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `PRAT`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `SC0`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `SEG`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `WEIG`(R,KP,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |

### input control parameters

| attribute | kind | status |
|---|---|---|
| `SW_LAMBDA`() | parameter | supported, refused in some uses: SW_LAMBDA with STAGES=YES (the tradeoff analysis) |
| `SW_PROB`(ALLSOW) | parameter | supported |
| `SW_SPROB`(J,ALLSOW) | parameter | supported |
| `SW_START`(J) | parameter | supported, refused in some uses: STAGES with several states of the world in the first period (TIMES solves each SOW on its own) |
| `SW_SUBS`(J,ALLSOW) | parameter | supported |

### input parameters

| attribute | kind | status |
|---|---|---|
| `BS_BNDPRS`(R,YEAR,P,C,S,L) Bound on process reserve provision | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_CAPACT`(R) Conversion factor from exogenous reserve demand to activity | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_DELTA`(R,YEAR,C,S) Calibration parameters for probabilistic reserve demands | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_DEMDET`(R,YEAR,RSP,C,S) Deterministic demands of reserves - EXOGEN and WMAXSI | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_DETWT`(R,YEAR,C) Weights for deterministic reserve demands | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_LAMBDA`(R,YEAR,C) Fudge factors for dependencies in reserve requirements | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_MAINT`(R,YEAR,P,S) Continuous maintenance duration (hours) | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_OMEGA`(REG,YEAR,COM,TS) Indicator of how to define reserve demand from deterministic and probabilistic component | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_RMAX`(R,YEAR,P,C,S) Maximum contribution of process p to provision of reserve c as a fraction of capacity | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_RTYPE`(R,C) Types of reserve commodities, positive or negative 1-4 | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_SHARE`(R,YEAR,C,ITEM,L) Share of group reserve provision | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_SIGMA`(R,YEAR,C,ITEM,S) Standard deviation of imbalance source ITEM | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |
| `BS_STIME`(R,P,COM,BD) Minimum times for reserve provision from storage (hours) | parameter | supported (with `$SET ABS YES` in the run file, as in TIMES) |

### interpolation defaults

| attribute | kind | status |
|---|---|---|
| `IE_DEFAULT`(*) | parameter | supported |
| `INT_DEFAULT`(*) | set | supported |

### materials

| attribute | kind | status |
|---|---|---|
| `MAT_GMAP`(REG,MAT_GRP,COM) Grouping of materials | set | not used by TIMES |
| `MAT_TMAP`(REG,MAT_TYPE,COM) Material by type | set | not used by TIMES |
| `MAT_VOL`(REG,COM) Material accounted for by volume | set | not used by TIMES |
| `MAT_WT`(REG,COM) Material accounted for by weight | set | not used by TIMES |

### miscellaneous

| attribute | kind | status |
|---|---|---|
| `ACTCG`(CG) | set | supported |
| `G_RCUR`(REG,CUR) Main currency unit by region | set | supported |
| `G_UAMAT`(U) Unit for activity of material process | set | not used by TIMES |
| `G_UANRG`(U) Unit for activity of energy process | set | not used by TIMES |
| `G_UCMAT`(U) Unit for capacity of material process | set | not used by TIMES |
| `G_UCNRG`(U) Unit for capacity of energy process | set | not used by TIMES |
| `SOW`() Stochastic State-of-the-World | set | supported |
| `SW_T`(ALLYEAR,ALLSOW) Stochastic state indexes by period | set | supported |

### new capacity

| attribute | kind | status |
|---|---|---|
| `NCAP_AF`(REG,ALLYEAR,PRC,TS,BD) Availability of capacity | parameter | supported |
| `NCAP_AFA`(REG,ALLYEAR,PRC,BD) Annual Availability of capacity | parameter | supported |
| `NCAP_AFM`(R,ALLYEAR,P) Pointer to availity change multiplier | parameter | supported |
| `NCAP_AFS`(REG,ALLYEAR,PRC,TS,BD) Seasonal Availability of capacity | parameter | supported |
| `NCAP_AFSX`(R,ALLYEAR,P,BD) Change in seasonal capacity availability | parameter | supported |
| `NCAP_AFX`(R,ALLYEAR,P) Change in capacity availability | parameter | supported |
| `NCAP_BND`(REG,ALLYEAR,PRC,LIM) Bound on overall capacity in a period | parameter | supported |
| `NCAP_BPME`(REG,ALLYEAR,PRC) Back pressure mode efficiency (or total eff.) | parameter | supported |
| `NCAP_CDME`(REG,ALLYEAR,PRC) Condensing mode efficiency | parameter | supported |
| `NCAP_CEH`(REG,ALLYEAR,PRC) Coefficient of electricity to heat | parameter | supported |
| `NCAP_CHPR`(REG,ALLYEAR,PRC,LIM) Combined heat:power ratio | parameter | supported |
| `NCAP_CLAG`(REG,ALLYEAR,PRC,COM,IO) Lagtime of a commodity after new capacity ready | parameter | supported |
| `NCAP_CLED`(REG,ALLYEAR,PRC,COM) Leadtime of a commodity before new capacity ready | parameter | supported |
| `NCAP_COM`(REG,ALLYEAR,PRC,COM,IO) Use (but +) of commodity based upon capacity | parameter | supported |
| `NCAP_COST`(REG,ALLYEAR,PRC,CUR) Investment cost for new capacity | parameter | supported |
| `NCAP_CPX`(REG,ALLYEAR,PRC) Pointer to capacity transfer multiplier | parameter | supported |
| `NCAP_DRATE`(REG,ALLYEAR,PRC) Process specific discount (hurdle) rate | parameter | supported |
| `NCAP_ELIFE`(REG,ALLYEAR,PRC) Economic (payback) lifetime | parameter | supported |
| `NCAP_FDR`(REG,ALLYEAR,PRC) Functional depreciation rate of process | parameter | supported |
| `NCAP_FOM`(REG,ALLYEAR,PRC,CUR) Fixed annual O&M costs | parameter | supported |
| `NCAP_FOMM`(REG,ALLYEAR,PRC) Pointer to fixed O&M change multiplier | parameter | supported |
| `NCAP_FOMX`(REG,ALLYEAR,PRC) Change in fixed O&M | parameter | supported |
| `NCAP_FSUB`(REG,ALLYEAR,PRC,CUR) Fixed tax on installed capacity | parameter | supported |
| `NCAP_FSUBM`(REG,ALLYEAR,PRC) Pointer to fixed subsidy change multiplier | parameter | supported |
| `NCAP_FSUBX`(REG,ALLYEAR,PRC) Change in fixed tax | parameter | supported |
| `NCAP_FTAX`(REG,ALLYEAR,PRC,CUR) Fixed tax on installed capacity | parameter | supported |
| `NCAP_FTAXM`(REG,ALLYEAR,PRC) Pointer to fixed tax change multiplier | parameter | supported |
| `NCAP_FTAXX`(REG,ALLYEAR,PRC) Change in fixed tax | parameter | supported |
| `NCAP_ICOM`(REG,ALLYEAR,PRC,COM) Input of commodity for install of new capacity | parameter | supported |
| `NCAP_ILED`(REG,ALLYEAR,PRC) Lead-time required for building a new capacity | parameter | supported |
| `NCAP_ISPCT`(REG,ALLYEAR,PRC) Subsidy as % of new investment cost | parameter | supported |
| `NCAP_ISUB`(REG,ALLYEAR,PRC,CUR) Subsidy for a new investment in capacity | parameter | supported |
| `NCAP_ITAX`(REG,ALLYEAR,PRC,CUR) Tax on a new investment in capacity | parameter | supported |
| `NCAP_LCOST`(REG,ALLYEAR,PRC) % labor cost of new investment | parameter | not used by TIMES |
| `NCAP_LFOM`(REG,ALLYEAR,PRC) % labor cost of fixed O&M | parameter | not used by TIMES |
| `NCAP_OLIFE`(REG,ALLYEAR,PRC) Operating lifetime of a process | parameter | supported |
| `NCAP_PASTI`(REG,ALLYEAR,PRC) Capacity install prior to study years | parameter | supported |
| `NCAP_PASTY`(REG,ALLYEAR,PRC) Buildup years for past investments | parameter | supported |
| `NCAP_TLIFE`(REG,ALLYEAR,PRC) Technical lifetime of a process | parameter | supported |
| `RCAP_BLK`(REG,ALLYEAR,PRC) Retirement block size | parameter | supported |
| `RCAP_BND`(REG,ALLYEAR,PRC,LIM) Retirement bounds | parameter | supported |

### other

| attribute | kind | status |
|---|---|---|
| `ACT_CSTPL`(R,ALLYEAR,P,CUR) Partial load cost penalty | parameter | supported |
| `ACT_EFF`(REG,YEAR,PRC,CG,TS) Activity efficiency for process | parameter | supported |
| `ACT_LOSPL`(R,ALLYEAR,P,L) Fuel consumption increase at minimum load | parameter | supported |
| `ACT_LOSSD`(R,LL,P,UPT,BD) Efficiency at one hour from start-up (BD=UP) or at one hour to end of shut-down (BD=LO) | parameter | supported |
| `ACT_MAXNON`(R,LL,P,UPT) Max. non-operational time before transition to next stand-by condition, by start-up type, in hours | parameter | supported |
| `ACT_MINLD`(R,ALLYEAR,P) Minimum stable operation level | parameter | supported |
| `ACT_SDTIME`(R,LL,P,UPT,BD) Duration of start-up (BD=UP) and shut-down BD=LO) phases, by start-up type, in hours | parameter | supported |
| `ACT_UPS`(R,ALLYEAR,P,S,L) Max. ramp rate, fraction of capacity per hour | parameter | supported, refused in some uses: ramp rates or minimum loads with a year-0 record left after interpolation (ACT_UPS levelling, eqactups.vda) |
| `COM_CSTBAL`(R,ALLYEAR,C,S,ITEM,CUR) Cost on specific component of node balance | parameter | supported |
| `FLO_EFF`(REG,ALLYEAR,PRC,CG,COM,S) General process flow-relation parameter | parameter | supported |
| `FLO_EMIS`(REG,ALLYEAR,PRC,CG,COM,S) General process emission parameter | parameter | supported |
| `FLO_MRKCON`(REG,ALLYEAR,PRC,COM,TS,BD) Bound on the share of a flow in the total consumption of a commmodity | parameter | not yet supported: IER extension |
| `FLO_MRKPRD`(REG,ALLYEAR,PRC,COM,TS,BD) Bound on the share of a flow in the total production of a commmodity | parameter | not yet supported: IER extension |
| `GG_DENS`(R,C) Density of gases | parameter | supported, refused in some uses: gas grid nodes without a density GG_DENS in a grid with densities (gasgrids.vda) |
| `GG_GAMMA`(R,YEAR,P,C) Comprossion factor | parameter | supported |
| `GG_KGF`(R,YEAR,P,C) Weymouth constants | parameter | supported |
| `GG_KLP`(R,YEAR,P,C) Linepack constants | parameter | supported |
| `GG_PP`(R,YEAR,P,C,L,J) Fixed pressure points | parameter | supported |
| `GG_PRBD`(R,YEAR,C,LIM) Nodal pressure bounds | parameter | supported |
| `GR_DEMFR`(R,ALLYEAR,C,S) Fraction of total electricity demand allocated to grid node | parameter | supported |
| `GR_ENDFR`(R,ALLYEAR,C,CG) Fraction of sectoral electricity demand allocated to grid node | parameter | supported |
| `GR_GENFR`(R,ALLYEAR,C,ITEM) Fraction of electricity generation type allocated to grid node | parameter | supported |
| `GR_GENLEV`(R,C) Grid connection category for electricity generation commodity | parameter | supported |
| `GR_GENMAP`(R,P,ITEM) Mapping of technology to generation type | parameter | supported |
| `GR_PTDF`(R,YEAR,P,C,ALL_R,C) PTDF of transmission line | parameter | supported |
| `GR_THMIN`(R,LL,P) Thermal minimum level | parameter | supported |
| `GR_VARGEN`(R,S,ITEM,BD) Variance in type of generation | parameter | supported |
| `GR_XBND`(R,ALLYEAR) Maximum level of net imports to / exports from region | parameter | supported, refused in some uses: N-1 bounds (GR_XBND) on grids with lines between regions (powerflo.vda EQ_GR_XBND) |
| `NCAP_AFAC`(REG,ALLYEAR,PRC,CG) Annual availability of capacity for commodity group CG | parameter | supported |
| `NCAP_AFC`(REG,ALLYEAR,PRC,CG,STL) Availability of capacity for commodity group CG | parameter | supported |
| `NCAP_AFCS`(REG,ALLYEAR,PRC,CG,TS) Availability of capacity for commodity group CG | parameter | supported |
| `NCAP_DISC`(R,ALLYEAR,P,UNIT) Unit size of discrete capacity addition | parameter | supported, refused in some uses: discrete capacity without the DSC extension (the run file sets neither DSC nor DSCAUTO) |
| `PRC_REACT`(R,ALLYEAR,P) Reactance of transmission line | parameter | supported |
| `RCAP_OCAP`(R,YEAR,P,C) Maximum age of retired process to have NCAP_OCOM flow | parameter | supported, refused in some uses: flows of retired capacity (RCAP_OCAP) in a model without retirements (no RCAP_BND / PRC_REFIT) |
| `SOL_ACFR`(R,UC_COST,T) | parameter | not yet supported: MACRO (MLF); accepted in a run without MACRO, which does not read it |
| `STG_MAXCYC`(R,YEAR,P) Maximum number of storage cycles over lifetime | parameter | supported |
| `STL`() | set | supported |
| `TEG`(PRC) | set | not yet supported: endogenous technology learning (ETL) |
| `TL_CCAP0`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `TL_CCAPM`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `TL_CLUSTER`(R,P,P) | parameter | not yet supported: endogenous technology learning (ETL) |
| `TL_MRCLUST`(R,P,R,P) | parameter | not yet supported: endogenous technology learning (ETL) |
| `TL_PRAT`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `TL_SC0`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `TL_SEG`(R,PRC) | parameter | not yet supported: endogenous technology learning (ETL) |
| `TM_ADDER`(R,T,C) Demand decoupling adder | parameter | not yet supported: MACRO; accepted in a run without MACRO, which does not read it |
| `TM_AEEIFAC`(R,YEAR,C) Periodwise Autonomous energy efficiency and demand decoupling factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_AEEIV`(R,YEAR,C) Annual Autonomous energy efficiency and demand decoupling factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_AKL`(R) Production function constant | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_AMP`(R,ALLYEAR) Amortisation of past investments (from CSA only) | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_ARBM`() | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_ASRV`(R) Annual capital survival factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_B`(R,C) Demand coefficient | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_C0`(R) Consume in the first period | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_CAP`(R,P) Base year capacity values for expanding technologies | parameter | not yet supported: MACRO; accepted in a run without MACRO, which does not read it |
| `TM_CAPTB`(R,P) Cumulative quadratic capacity penalty level | parameter | refused with MACRO MLF: with TM_QFAC, the capacity variables of eqmain.mod 75; MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_CSTINV`(R,ALLYEAR,P) Annualized investment costs | parameter | not yet supported: MACRO; accepted in a run without MACRO, which does not read it |
| `TM_D0`(R,C) Demand in first period | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DDATPREF`(R,C) Reference marginal price for demand | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DDF`(R,ALLYEAR,C) Demand decoupling factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DEPR`(R) Depreciation rate | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DESUB`(R) Elasticity of substitution between demands | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DFACT`(R,YEAR) Utility discount factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DFACTCURR`(R,YEAR) Intermediate parameter for the utility discount factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_DMTOL`(R) Demand lower bound factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_EC0`(R) Energy costs in the first period | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_ESUB`(R) Elasticity of substitution | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_EXPBND`(R,ALLYEAR,P) Market Penetration Cutoff for Applying Cost Penalty | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_EXPF`(R,ALLYEAR) Annual percent expansion factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_GDP0`(R) GDP in the first period | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_GR`(R,ALLYEAR) MACRO Projected Annual GDP Growth | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_GROWV`(R,ALLYEAR) Labour growth rate | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_IV0`(R) Investment in the first period | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_IVETOL`(R) Investment and enery tolerance | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_K0`(R) Capital stock in first period | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_KGDP`(R) Initial capital to GDP ratio | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_KPVS`(R) Capital value share | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_L`(R,YEAR) Annual labor index | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_PP`(R,YEAR) | set | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_PWT`(ALLYEAR) Period weight | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_QFAC`(R) Switch for market penetration penalty function | parameter | refused with MACRO MLF: with TM_CAPTB, the capacity variables of eqmain.mod 75; MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_RHO`(R) Substitution constant | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_SCALE_CST`() Scaling factor cost units | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_SCALE_NRG`() Scaling factor demand units | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_SCALE_UTIL`() Scaling factor utility function | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_STEP`(R,CG,LIM) Steps in CES substitution | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_TSRV`(R,YEAR) Capital survival factor between two periods | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_UDF`(R,ALLYEAR) Utility discount factor | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_VOC`(R,YEAR,CG,BD) Variance in CES component or utility | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_Y0`(R) Annual production in first period | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `TM_YCHECK`(R) Check | parameter | supported with MACRO MLF (and TIMESED); MACRO YES, MSA, CSA not yet supported; accepted in a run without MACRO, which does not read it |
| `UC_ACTBET`(UC_N,ALL_REG,ALLYEAR,PRC) | parameter | supported |
| `UC_DYNBND`(UC_N,LIM) Dynamic process-wise UC bounds | set | supported, refused in some uses: dynamic process bounds, cumulative cost bounds, blending or dynamic UC bounds in a myopic run (solve.stp) |
| `UC_FLOBET`(UC_N,ALL_REG,ALLYEAR,PRC,CG) | parameter | supported |
| `VDA_CEH`(REG,ALLYEAR,PRC) The slope of pass-out turbine (alias NCAP_CEH) | parameter | supported |
| `VDA_EMCB`(REG,ALLYEAR,COM,COM) Combustion emission parameter (aka EMI_comb) | parameter | supported |
| `VDA_FLOP`(REG,ALLYEAR,PRC,CG,S) General process transformation parameter | parameter | supported |

### peak

| attribute | kind | status |
|---|---|---|
| `COM_PKFLX`(REG,ALLYEAR,COM,TS) Peaking flux ratio | parameter | supported |
| `COM_PKRSV`(REG,ALLYEAR,COM) Peaking reserve margin | parameter | supported |
| `FLO_PKCOI`(REG,ALLYEAR,PRC,COM,ALL_TS) Factor increasing the average demand | parameter | supported |
| `NCAP_PKCNT`(REG,ALLYEAR,PRC,ALL_TS) Fraction of capacity contributing to peaking in time-slice TS | parameter | supported |

### peaking

| attribute | kind | status |
|---|---|---|
| `COM_PEAK`(REG,COM_GRP) Peaking required flag | set | supported |
| `COM_PKTS`(REG,COM_GRP,TS) Peaking time-slices | set | supported |
| `PRC_PKAF`(ALL_REG,PRC) Flag for default value of NCAP_PKCNT | set | supported |
| `PRC_PKNO`(ALL_REG,PRC) Processes which cannot be involved in peaking | set | supported |

### predefined items

| attribute | kind | status |
|---|---|---|
| `ALL_REG`() | set | supported |
| `UNIT`() Numbers of different units | set | supported |

### process

| attribute | kind | status |
|---|---|---|
| `PRC`() List of all processes | set | supported |
| `PRC_ACTUNT`(REG,PRC,CG,UNITS_ACT) Primary commodity (or group) & activity unit | set | supported |
| `PRC_AOFF`(REG,PRC,*,*) Periods for which activity is unavailable | set | supported |
| `PRC_CAPUNT`(REG,PRC,CG,UNITS_CAP) Unit of capacity | set | supported |
| `PRC_CG`(R,PRC,COM_GRP) Commodity groups for a process | set | supported |
| `PRC_DESC`(R,P) Process descriptions by region | set | supported |
| `PRC_DSCNCAP`(R,P) Process with discrete capacity additions | set | supported, refused in some uses: discrete capacity without the DSC extension (the run file sets neither DSC nor DSCAUTO) |
| `PRC_FOFF`(REG,PRC,COM,ALL_TS,*,*) Periods/timeslices for which flow is not possible | set | supported |
| `PRC_MAP`(REG,PRC_GRP,PRC) Grouping of processes to nature | set | supported |
| `PRC_NOFF`(REG,PRC,*,*) Periods for which new capacity can NOT be built | set | supported |
| `PRC_RCAP`(REG,PRC) Process with early retirement | set | supported |
| `PRC_RMAP`(REG,PRC_RSOURC,PRC) Grouping of XTRACT processes | set | not used by TIMES |
| `PRC_SIMV`(REG,PRC) Process is to be vintage-simulated | set | supported |
| `PRC_SPG`(REG,PRC,COM_GRP) Shadow Primary Group | set | supported |
| `PRC_TS`(ALL_REG,PRC,ALL_TS) Timeslices for a process | set | supported |
| `PRC_TSL`(REG,PRC,TSLVL) Timeslice level for a process | set | supported |
| `PRC_VINT`(REG,PRC) Process is to be vintaged | set | supported |

### process units

| attribute | kind | status |
|---|---|---|
| `PRC_ACTFLO`(REG,ALLYEAR,PRC,CG) Convert from process activity to particular commodity flow | parameter | supported |
| `PRC_CAPACT`(REG,PRC) Factor for going from capacity to activity | parameter | supported |
| `PRC_GMAP`(REG,PRC,ITEM) User-defined groupings of processes | parameter | supported |

### region

| attribute | kind | status |
|---|---|---|
| `REG`(ALL_REG) List of Regions | set | supported |
| `REG_GRP`(*) List of regional groups | set | not used by TIMES |
| `REG_RMAP`(REG_GRP,ALL_REG) Grouping of regions in/out of area of study | set | not used by TIMES |

### regional cost bounds

| attribute | kind | status |
|---|---|---|
| `REG_BNDCST`(REG,ALLYEAR,COSTAGG,CUR,BD) Bound on regional costs by type | parameter | supported, refused in some uses: cost bounds (REG_CUMCST, REG_BNDCST) with OBJ LIN (the pulses of eqbndcst.mod) |
| `REG_CUMCST`(REG,ALLYEAR,ALLYEAR,COSTAGG,CUR,BD) Cumulative bound on regional costs | parameter | supported, refused in some uses: cost bounds (REG_CUMCST, REG_BNDCST) with OBJ LIN (the pulses of eqbndcst.mod) |

### scalars

| attribute | kind | status |
|---|---|---|
| `LASTLL`(LL) | set | supported |

### set for calibration quantities

| attribute | kind | status |
|---|---|---|
| `CM_CO2GTC`(REG,C) Conversion factors from CO2 commodities to GtC | parameter | supported |
| `CM_GHGMAP`(R,C,CG) Conversion factors from regional GHG commodities to CLI | parameter | supported |
| `CM_HISTS`(CG) | set | supported |
| `CM_OFOR`(CM_ITEM) | set | supported |
| `CM_PPM`(CM_ITEM) Conversion factors between Gt/Mt and ppm/ppb | parameter | supported |
| `CM_PREDEF`() Historical CO2 concentration and incremental forcing quantities | set | supported |
| `CM_Q`() Reservoir Qualifier | set | supported |
| `FORCING`() Radiative Forcing | set | supported |
| `UC_GRPTYPE`() | set | supported |

### sets and parameters used for chp plants

| attribute | kind | status |
|---|---|---|
| `ECT_AFBPT`(REG,ALLYEAR,PRC,BD) Availability of backpressure mode operation of extraction condensing CHP | parameter | not yet supported: IER extension |
| `ECT_AFCON`(REG,ALLYEAR,PRC,BD) Availability of condensing mode operation of extraction condensing CHP | parameter | not yet supported: IER extension |
| `ECT_CGIN`(REG,PRC,COM_GRP) Fuel input commodity group of ECT CHP plant | set | not yet supported: IER extension |
| `ECT_CGOUT`(REG,PRC,COM_GRP) Output commodity group ELC+HEAT of ECT CHP plant | set | not yet supported: IER extension |
| `ECT_CHP`(REG,PRC) Set of extraction condensing CHP plants | set | not yet supported: IER extension |
| `ECT_DHT`(REG,PRC,COM) Heat commodity of extraction condensing CHP plants | set | not yet supported: IER extension |
| `ECT_ELC`(REG,PRC,COM) Electricity commodity of extraction condensing CHP plants | set | not yet supported: IER extension |
| `ECT_INP2CON`(REG,ALLYEAR,PRC) Conversion factor from input capacity to heat capacity in BPT point | parameter | not yet supported: IER extension |
| `ECT_INP2DHT`(REG,ALLYEAR,PRC) Conversion factor from input capacity to heat capacity in BPT point | parameter | not yet supported: IER extension |
| `ECT_INP2ELC`(REG,ALLYEAR,PRC) Conversion factor from input capacity to ELC capacity in BPT point | parameter | not yet supported: IER extension |
| `ECT_REH`(REG,ALLYEAR,PRC) Ratio of electricity to heat in brackpressure point | parameter | not yet supported: IER extension |

### shape and multi

| attribute | kind | status |
|---|---|---|
| `MULTI`(J,ALLYEAR) Multiplier table | parameter | supported |
| `SHAPE`(J,AGE) Shaping table | parameter | supported |

### stochastic extension

| attribute | kind | status |
|---|---|---|
| `ITEM`() | set | supported |

### stochastic input parameters

| attribute | kind | status |
|---|---|---|
| `S_CAP_BND`(REG,ALLYEAR,PRC,BD,J,ALLSOW) Bound on total installed capacity | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_CM_CONST`(ITEM,J,ALLSOW) Climate constants | parameter | supported, refused in some uses: the climate module with STAGES: no climate sensitivity CS for SOW {w} (coef_ext.cli 117); with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_CM_MAXC`(ALLYEAR,ITEM,J,ALLSOW) Maximum allowable climatic quantity | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_CM_MAXCO2C`(ALLYEAR,J,ALLSOW) Maximum allowable atmospheric CO2 concentration | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_COM_CUMNET`(R,BOHYEAR,EOHYEAR,C,BD,J,ALLSOW) Cumulative limit on COMNET | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_COM_CUMPRD`(R,BOHYEAR,EOHYEAR,C,BD,J,ALLSOW) Cumulative limit on COMPRD | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_COM_FR`(R,ALLYEAR,C,S,J,ALLSOW) Commodity fraction multipliers | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_COM_PROJ`(REG,ALLYEAR,COM,J,ALLSOW) Demand scenario projection | parameter | supported |
| `S_COM_TAX`(R,ALLYEAR,C,S,COM_VAR,CUR,J,ALLSOW) Tax on commodity NET/PRD | parameter | supported |
| `S_DAM_COST`(R,ALLYEAR,C,CUR,J,ALLSOW) Damage costs | parameter | refused: damage costs by SOW with STAGES=YES (DAMAGE is not supported) |
| `S_FLO_CUM`(R,P,C,ITEM,ITEM,BD,J,ALLSOW) Cumulative limit on FLOW | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_FLO_FUNC`(R,ALLYEAR,P,CG,CG,J,ALLSOW) Uncertain multiplier of process transformation | parameter | supported, refused in some uses: S_FLO_FUNC of a trade process with STAGES=YES (IRE_FLOSUM by SOW: cal_ire.mod 16, eqobjvar.mod 83); with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_NCAP_AFS`(R,ALLYEAR,P,S,J,ALLSOW) Seasonal availability factors | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_NCAP_COST`(R,ALLYEAR,P,J,ALLSOW) Uncertain multiplier of investment cost | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_UCOBJ`(UC_N,ALLSOW) Weight of UC objective component in tradeoff analysis | parameter | refused: the tradeoff analysis of stochastic TIMES (S_UCOBJ, SW_LAMBDA) |
| `S_UC_RHS`(UC_N,LIM,J,ALLSOW) RHS of user constraint | parameter | supported, refused in some uses: S_UC_RHS of OBJ1 (the minimax regret of the tradeoff analysis); with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_UC_RHSR`(ALL_REG,UC_N,LIM,J,ALLSOW) RHS of user constraint | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_UC_RHSRT`(ALL_REG,UC_N,ALLYEAR,LIM,J,ALLSOW) RHS of user constraint | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_UC_RHSRTS`(ALL_REG,UC_N,ALLYEAR,TS,LIM,J,ALLSOW) RHS of user constraint | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_UC_RHST`(UC_N,ALLYEAR,LIM,J,ALLSOW) RHS of user constraint | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |
| `S_UC_RHSTS`(UC_N,ALLYEAR,TS,LIM,J,ALLSOW) RHS of user constraint | parameter | supported, refused in some uses: with `SENSIS` (only `S_COM_PROJ` and `S_COM_TAX` are taken with it) |

### storage

| attribute | kind | status |
|---|---|---|
| `PRC_NSTTS`(REG,PRC,ALL_TS) Night storage process and time-slice for storaging | set | supported |
| `PRC_STGIPS`(REG,PRC,COM) Storage process and stored commodity for inter-period storage | set | supported |
| `PRC_STGTSS`(REG,PRC,COM) Storage process and stored commodity for time-slice storage | set | supported |
| `STGIN_BND`(REG,ALLYEAR,PRC,C,S,BD) Bound on output-flow of storage process | parameter | supported |
| `STGOUT_BND`(REG,ALLYEAR,PRC,C,S,BD) Bound on output-flow of storage process | parameter | supported |
| `STG_CHRG`(REG,ALLYEAR,PRC,S) Exogeneous charging of a storage technology | parameter | supported |
| `STG_EFF`(REG,ALLYEAR,PRC) Storage efficiency | parameter | supported |
| `STG_LOSS`(REG,ALLYEAR,PRC,S) Annual energy loss from a storage technology | parameter | supported |
| `STG_SIFT`(R,ALLYEAR,P,C,S) Max load sifting in proportion to total load | parameter | supported |

### time

| attribute | kind | status |
|---|---|---|
| `B`(ALLYEAR) Beginning year of each model period | parameter | supported |
| `D`(ALLYEAR) Length of each period | parameter | supported |
| `DATAYEAR`(ALLYEAR) Years for which user data is provided | set | supported |
| `E`(ALLYEAR) Ending year of each model period | parameter | supported |
| `M`(ALLYEAR) Middle year of each Period | parameter | supported |
| `MILESTONYR`(ALLYEAR) Projection years for which model to be run | set | supported |
| `MODLYEAR`(ALLYEAR) Years for which the model is to be run (MILESTONYR+PASTYEAR) | set | supported |
| `PASTYEAR`(ALLYEAR) Years before 1st MILESTONYR for which PASTI needs to be handled | set | supported |
| `TS`(ALL_TS) | set | supported |
| `TS_GROUP`(ALL_REG,TSLVL,TS) Timeslice Level assignment | set | supported |
| `TS_MAP`(ALL_REG,ALL_TS,ALL_TS) Timeslice hierarchy tree: node+below | set | supported |
| `TS_OFF`(REG,TS,BOHYEAR,EOHYEAR) Timeslices turned off | set | supported |

### topology

| attribute | kind | status |
|---|---|---|
| `TOP`(REG,PRC,COM,IO) Topology for all process | set | supported |
| `TOP_IRE`(ALL_REG,COM,ALL_REG,COM,PRC) Trade within area of study | set | supported |

### trade of commodities

| attribute | kind | status |
|---|---|---|
| `IRE_BND`(ALL_R,ALLYEAR,COM,TS,ALL_REG,IE,BD) Limit on inter-reg exchange of commodity | parameter | supported |
| `IRE_CCVT`(ALL_REG,COM,ALL_REG,COM) Commodity unit conversion factor between regions | parameter | supported |
| `IRE_FLO`(ALL_R,ALLYEAR,PRC,COM,ALL_R,COM,TS) Efficiency of exchange for inter-regional trade | parameter | supported |
| `IRE_FLOSUM`(REG,ALLYEAR,PRC,COM,TS,IE,COM,IO) Aux. consumption/emissions from inter-regional trade | parameter | supported, refused in some uses: flow tax bounds (REG_CUMCST FLOTAX / FLOSUB) on auxiliary flows of trade processes (IRE_FLOSUM) |
| `IRE_PRICE`(REG,ALLYEAR,PRC,COM,TS,ALL_R,IE,CUR) Exogenous price of import/export | parameter | supported |
| `IRE_TSCVT`(ALL_REG,ALL_TS,ALL_REG,ALL_TS) Identification and TS-conversion factor between regions | parameter | supported |
| `IRE_XBND`(ALL_REG,ALLYEAR,COM,TS,IE,BD) Limit on all (external and inter-regional) exchange of commodity | parameter | supported |

### user constraints

| attribute | kind | status |
|---|---|---|
| `UC_ACT`(UC_N,SIDE,ALL_REG,ALLYEAR,PRC,ALL_TS) Multiplier of activity variables | parameter | supported |
| `UC_ATTR`(ALL_R,UC_N,SIDE,UC_GRPTYPE,UC_NAME) Mapping of parameter names to groups | set | supported |
| `UC_CAP`(UC_N,SIDE,ALL_REG,ALLYEAR,PRC) Multiplier of capacity variables | parameter | supported |
| `UC_COMCON`(UC_N,SIDE,ALL_REG,ALLYEAR,COM,TS) Multiplier of VAR_COMCON variables | parameter | supported |
| `UC_COMNET`(UC_N,SIDE,ALL_REG,ALLYEAR,COM,TS) Multiplier of VAR_COMNET variables | parameter | supported |
| `UC_COMPRD`(UC_N,SIDE,ALL_REG,ALLYEAR,COM,TS) Multiplier of VAR_COMPRD variables | parameter | supported |
| `UC_CUMACT`(UC_N,ALL_REG,PRC,ITEM,ITEM) Multiplier of cumulative process activity variable | parameter | supported |
| `UC_CUMCOM`(UC_N,ALL_REG,COM_VAR,COM,ITEM,ITEM) Multiplier of cumulative commodity variable | parameter | supported |
| `UC_CUMFLO`(UC_N,ALL_REG,PRC,COM,ITEM,ITEM) Multiplier of cumulative process flow variable | parameter | supported |
| `UC_FLO`(UC_N,SIDE,ALL_REG,ALLYEAR,PRC,COM,TS) Multiplier of flow variables | parameter | supported |
| `UC_IRE`(UC_N,SIDE,ALL_REG,ALLYEAR,PRC,COM,TS,IE) Multiplier of inter-regional exchange variables | parameter | supported |
| `UC_N`(*) Names of all manual constraints | set | supported |
| `UC_NCAP`(UC_N,SIDE,ALL_REG,ALLYEAR,PRC) Multiplier of VAR_NCAP variables | parameter | supported |
| `UC_RHS`(UC_N,LIM) Constant in user constraint | parameter | supported, refused in some uses: cumulative global user constraints in a myopic run (solve.stp relaxes their RHS with the levels of the previous step) |
| `UC_RHSR`(ALL_REG,UC_N,LIM) Constant in user constraint | parameter | supported |
| `UC_RHSRS`(ALL_REG,UC_N,TS,LIM) Constant in user constraint | parameter | supported |
| `UC_RHSRT`(ALL_REG,UC_N,ALLYEAR,LIM) Constant in user constraint | parameter | supported |
| `UC_RHSRTS`(ALL_REG,UC_N,ALLYEAR,TS,LIM) Constant in user constraint | parameter | supported |
| `UC_RHSS`(UC_N,TS,LIM) Constant in user constraint | parameter | supported |
| `UC_RHST`(UC_N,ALLYEAR,LIM) Constant in user constraint | parameter | supported |
| `UC_RHSTS`(UC_N,ALLYEAR,TS,LIM) Constant in user constraint | parameter | supported |
| `UC_R_EACH`(ALL_R,UC_N) Specification of regions, if UC_REG=EACH | set | supported |
| `UC_R_SUM`(ALL_R,UC_N) Specification of regions, if UC_REG=SUM | set | supported |
| `UC_TIME`(UC_N,ALL_R,ALLYEAR) Multiplier of time in model periods (years) | parameter | supported |
| `UC_TSL`(ALL_R,UC_N,SIDE,TSLVL) UC timeslice level | set | supported |
| `UC_TS_EACH`(ALL_R,UC_N,ALL_TS) Specification of time-slices, if UC_TS=EACH | set | supported |
| `UC_TS_SUM`(ALL_R,UC_N,ALL_TS) Specification of time-slices, if UC_TS=SUM | set | supported |
| `UC_T_EACH`(ALL_R,UC_N,ALLYEAR) Specification of periods, if UC_DYN=EACH | set | supported |
| `UC_T_SUCC`(ALL_R,UC_N,ALLYEAR) Specification of periods, if UC_DYN=SUCC | set | supported |
| `UC_T_SUM`(ALL_R,UC_N,ALLYEAR) Specification of periods, if UC_DYN=SEVERAL | set | supported |
| `UC_UCN`(UC_N,SIDE,ALL_R,ALLYEAR,UC_N) Multiplier of user constraint variable | parameter | supported |

### user provided parameters

| attribute | kind | status |
|---|---|---|
| `BL_COM`(R,COM,OPR,SPE) | parameter | supported |
| `BL_DELIVC`(R,COM,COM,CUR) | parameter | supported |
| `BL_INP`(R,COM,COM) | parameter | supported |
| `BL_SPEC`(R,COM,SPE) | parameter | supported |
| `BL_START`(R,COM,SPE) | parameter | supported |
| `BL_TYPE`(R,COM,SPE) | parameter | supported |
| `BL_UNIT`(R,COM,SPE) | parameter | supported |
| `BL_VAROMC`(R,COM,CUR) | parameter | supported |
| `CONVERT`(OPR,CVT) | parameter | supported |
| `ENV_BL`(R,COM,COM,OPR,YEAR) | parameter | supported |
| `PEAKDA_BL`(R,COM,YEAR) | parameter | supported |

### user provided sets & scalars

| attribute | kind | status |
|---|---|---|
| `BLE`(COM) | set | supported |
| `OPR`(COM) | set | supported |
| `REF`(R,PRC) | set | not read |
| `REFUNIT`(R) | parameter | supported |
| `SPE`(*) | set | supported |

### which sows are available at each period

| attribute | kind | status |
|---|---|---|
| `SW_STAGE`(J,ALLSOW) Internal SOWs at each stage | set | supported |
| `SW_TPROB`(T,ALLSOW) | parameter | supported |
| `SW_TSW`(ALLSOW,ALLYEAR,ALLSOW) Mapping from finest SOWs to unique SOW at each period | set | supported |
| `SW_UCT`(UC_N,T,ALLSOW) | set | supported |
