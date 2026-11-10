# SPDX-License-Identifier: GPL-3.0-or-later
# Everything the equations read, declared in one place.
#
# Column names follow the TIMES documentation: r region, v vintage year, t milestone year, p process,
# c commodity, cg commodity group, s / ts timeslice, io IN/OUT, ie IMP/EXP, bd LO/UP/FX, cur currency,
# uc user constraint. A table whose column count differs from the declaration is rejected at load.

"""Sets (name = columns)."""
const SETS = (
    # time
    MILESTONYR = (:t,),
    PASTYEAR   = (:v,),
    # timeslices
    TS_MAP     = (:r, :s, :ts),             # ts is s or lies below s
    RS_TREE    = (:r, :s, :ts),             # ts is s, above s or below s
    RS_BELOW   = (:r, :s, :ts),             # ts lies strictly below s
    # processes
    RP         = (:r, :p),
    RP_FLO     = (:r, :p),                  # processes with flow variables
    RP_STD     = (:r, :p),                  # standard processes
    RP_IRE     = (:r, :p),                  # trade processes
    RP_AIRE    = (:r, :p, :ie),             # trade processes whose activity is the import / export
    RP_PGFLO   = (:r, :p),
    RP_PGACT   = (:r, :p),
    PRC_ACT    = (:r, :p),                  # processes with an activity equation
    PRC_VINT   = (:r, :p),                  # vintaged processes
    PRC_TS     = (:r, :p, :s),              # timeslices of the process
    RPS_PRCTS  = (:r, :p, :s),              # timeslices at or above the process level
    RPS_S1     = (:r, :p, :s),              # timeslices in which the transformation equations are written
    RTP        = (:r, :t, :p),              # process available in year (t may be a past year)
    RTP_VARA   = (:r, :t, :p),              # activity variable exists
    UC_DYNBND  = (:uc, :bd),                # user constraints written as dynamic bounds by process (EQ_UCRTP)
    RTP_VARP   = (:r, :t, :p),              # capacity variable exists
    RTP_VINTYR = (:r, :v, :t, :p),          # vintage v operates in period t
    RTP_CPTYR  = (:r, :v, :t, :p),          # capacity installed in v is available in t
    # topology
    TOP        = (:r, :p, :c, :io),
    RPC        = (:r, :p, :c),
    RPC_PG     = (:r, :p, :c),              # commodities of the primary group
    RPC_EMIS   = (:r, :p, :c),              # emission flows expressed through other flows
    FS_EMIT    = (:r, :p, :c, :cg, :com),   # emission c depends on flow com (through group cg)
    RPG_RED    = (:r, :p, :cg, :io),
    RPCC_FFUNC = (:r, :p, :cg1, :cg2),      # transformation from group cg1 to group cg2
    RPC_ACE    = (:r, :p, :c),
    RPG_ACE    = (:r, :p, :cg, :io),        # groups with an activity efficiency
    RTPCS_VARF = (:r, :t, :p, :c, :s),      # flow variable exists
    RPCS_VAR   = (:r, :p, :c, :s),
    # commodities
    COM        = (:c,),
    COM_GMAP   = (:r, :cg, :c),             # members of a commodity group
    COM_TS     = (:r, :c, :s),
    RCS_COMTS  = (:r, :c, :s),              # timeslices at or above the level of commodity c
    REG        = (:r,),                     # internal regions
    DEM        = (:r, :c),
    RC         = (:r, :c),                  # commodities of the region
    RTC        = (:r, :t, :c),
    RTCS_VARC  = (:r, :t, :c, :s),          # commodity is tracked in (t, s)
    RCS_COMBAL = (:r, :t, :c, :s, :bd),     # balance type: LO production >= consumption, FX equality
    RCS_COMPRD = (:r, :t, :c, :s, :bd),
    RHS_COMBAL = (:r, :t, :c, :s),          # net-production variable is needed
    RHS_COMPRD = (:r, :t, :c, :s),          # production variable is needed
    RC_AGP     = (:r, :c, :bd),             # aggregation of commodities (COM_AGG) uses NET (LO) / PRD (FX)
    COM_PKTS   = (:r, :cg, :s),             # peak timeslices of a commodity (group)
    RPC_PKC    = (:r, :p, :c),              # processes contributing to the peak by capacity
    # trade
    RPC_IRE    = (:r, :p, :c, :ie),
    RPC_AIRE   = (:r, :p, :c),              # trade flow replaced by the activity
    RPC_ACT    = (:r, :p, :c),              # REDUCE YES: flow replaced by the activity (c of the primary group, or ACT)
    RPC_FFUNC  = (:r, :p, :c),              # REDUCE YES: flow tied to the activity flow, replaced by ACT_FLO x activity
    PRC_TS2    = (:r, :p, :s),              # timeslices of the activity of the processes with RPC_ACT
    NO_ACT     = (:r, :p),                  # REDUCE YES: processes with no activity variable (their primary flows stand in)
    RTPS_OFF   = (:r, :t, :p, :s),          # process turned off in (t, s): no activity equation (REDUCE YES), no availability row
    REDUCE_YES = (:x,),                     # YES: the run reduces the model (REDUCE YES: cal_red.red)
    RPC_EQIRE  = (:r, :p, :c, :ie),         # trade equations to generate
    RPC_MARKET = (:r, :p, :c, :ie),         # marketplaces: EXP = the region exports c to several regions; IMP = its import commodity
    RPC_IREIO  = (:r, :p, :c, :ie, :io),
    TOP_IRE    = (:rexp, :cexp, :rimp, :cimp, :p),
    # availability, cumulative flows, user constraints, objective
    AFS        = (:r, :t, :p, :s, :bd),     # availability equations to generate
    RPC_CUMFLO = (:r, :p, :c, :y1, :y2),
    RC_CUMCOM  = (:r, :cv, :y1, :y2, :c),     # cumulative bound on the net (cv = NET) or gross (PRD) production of c
    UC_RHSMAP  = (:r, :t, :uc, :scope, :s), # scope: SEVERAL (summed over timeslices) or EACH
    UC_TS_SUM  = (:r, :uc, :s),
    UC_MAP_FLO = (:uc, :side, :r, :p, :c),
    UC_MAP_IRE = (:uc, :r, :p, :c, :ie),
    UC_GMAP_P  = (:r, :uc, :grp, :p),
    UC_GMAP_C  = (:r, :uc, :kind, :c, :grp), # kind: PRD or NET
    UC_UT      = (:uc, :t),                 # constraints written per period, all regions together
    UC_R_SUM   = (:r, :uc),                 # regions summed in such a constraint
    UC_R_EACH  = (:r, :uc),                 # regions with a constraint of their own
    UC_T_SUM   = (:r, :uc, :t),             # periods summed in a global or regional constraint
    UC_DT      = (:r, :uc),                 # cumulative constraints: the terms are weighted by the length of the period
    UC_T_EACH  = (:r, :uc, :t),
    UC_TS_EACH = (:r, :uc, :s),             # timeslices for which the constraint is written one by one
    UC_UTS     = (:uc, :t, :s),             # constraints written per period and timeslice, all regions together
    UC_ATTR    = (:r, :uc, :side, :grp, :name), # modifiers of the terms of group grp (FLO, CAP, ...) on one side
    UC_DYNDIR  = (:r, :uc, :side),          # dynamic constraint: the side that carries the growth
    UC_DS      = (:r, :uc, :tsl),           # constraint written for every timeslice of level tsl
    UC_CFLOW   = (:uc, :side, :r, :p, :c),  # port-only: UC_CAPFLO, the capacity flows in user constraints (CAPFLO; only in models that have it)
    UC_TSL     = (:r, :uc, :side, :tsl),    # the sides of such a constraint
    RVPT       = (:r, :v, :p, :t),          # period t in which the capacity of vintage v is commissioned (lead time)
    RTP_OFF    = (:r, :t, :p),              # no new capacity in t
    PRC_CG     = (:r, :p, :cg),             # commodity groups of the process
    RDCUR      = (:r, :cur),
    OBJ_ICUR   = (:r, :v, :p, :cur),
    OBJ_VFLO   = (:r, :p, :c, :cur, :kind), # flows that carry a cost
    OBJ_SUMS   = (:r, :v, :p),              # vintages with a salvage value
    OBJ_SUMS3  = (:r, :v, :p),              # vintages with a salvage value of their decommissioning cost
    OBJANN     = (:x,),                     # YES: the objective is stated in the annualised form (run with OBJANN=YES)
    VARCOST_LIN = (:x,),                    # YES: variable costs weighted with OBJ_LINT (run with VARCOST LIN), else OBJ_DISC over the period
    TS_ANN     = (:s, :ts),                 # ts is s or ANNUAL
    # commodity types
    COM_TYPE   = (:cg,),
    COM_TMAP   = (:r, :cg, :c),             # type cg of commodity c
    # storage
    RP_STG     = (:r, :p),
    RPC_STG    = (:r, :p, :c),              # commodities stored
    PRC_STGTSS = (:r, :p, :c),              # ... in a storage between timeslices
    RPS_STG    = (:r, :p, :s),              # timeslices with a storage level
    RPC_STGN   = (:r, :p, :c, :io),         # commodity both charged and discharged: the side on which it is netted off
    RS_PREV    = (:r, :s, :ts),             # ts precedes s in the cycle of their parent timeslice
    PRC_MAP    = (:r, :grp, :p),            # process type
    PRC_NSTTS  = (:r, :p, :s),              # night storage: the timeslices in which it is charged
    PRC_STGIPS = (:r, :p, :c),              # commodities stored between periods
    RP_STS     = (:r, :p),                  # timeslice storages working on several timeslice levels
    RP_STL     = (:r, :p, :tsl, :l),        # general-level storage balance of an RP_STS at level tsl (EQ_STSBAL; l = N)
    RPC_LS     = (:r, :p, :c),              # load-shifting processes: the shifted input commodity, or ACT
    RS_UP      = (:r, :s, :j, :up),         # parent timeslice up of s, with the cycle type j
    RJ_SL      = (:r, :j, :up, :sl),        # timeslices sl of one cycle below up
    RPC_CUR    = (:r, :p, :c, :cur),        # processes with dispatch costs (c = ACT)
    RS_BELOW1  = (:r, :s, :ts),             # ts lies directly below s
    RTPC       = (:r, :t, :p, :c),
    MIYR_1     = (:t,),                     # first milestone year
    # myopic runs (TIMESTEP): the window of a step and the periods before / after it
    SUBT       = (:t,),                     # periods of the window (all periods in a run without steps)
    BACKWARD   = (:t,),                     # periods before the window: fixed at the solution of the previous steps
    FORWARD    = (:t,),                     # periods after the window: fixed at zero; their vintages are left out (V(FORWARD) = NO)
    UC_RTSUC   = (:r, :t, :uc),             # dynamic user constraints of the step (UC_T_SUCC)
    RTC_NET    = (:r, :t, :c),              # commodities with a net-production variable
    RTC_PRD    = (:r, :t, :c),              # commodities with a production variable
    NO_RVP     = (:r, :t, :p),              # capacity of the window with vintages fixed before it: bounded by the relaxed CAP_BND
    # a run with FIXBOH (solve.stp with REG_FIXT; maindrv.mod 41: %R_T% = RT_PP(R,SUBT(T)), %RTPX% = X), whose periods are
    # fixed by region; under names of their own, so that a run without FIXBOH has none of these tables
    # elastic demands (TIMESED YES), under names of their own (prep/elastic.py)
    OBJELS_R   = (:r,),                     # regions with elastic demands: SUM_OBJ(R,'OBJELS') (eqobj.mod 28)
    ELS_BAL    = (:r, :t, :c, :s, :j, :bd), # steps of an elastic demand in its balance: RCJ(R,C,J,BDNEQ)$COM_ELAST(R,T,C,S,BD)
    # TIMES-MACRO MLF (equ_ext.mlf, presolve.mlf; prep/mlf.py)
    MLF        = (:x,),                     # YES: the model is TIMES_MACRO in the linearised form (run with MACRO MLF)
    MR         = (:r,),                     # regions with MACRO
    PP         = (:t,),                     # every milestone year but the first
    TLAST      = (:t,),                     # the last milestone year
    TM_PP      = (:r, :t),                  # periods linearised (not fixed by FIXBOH / REG_BDNCAP)
    TM_DM      = (:r, :c),                  # demands of the demand CES function
    TM_DMAS    = (:cg, :cg1),               # cg1 is an input of the CES function cg (AKL: KN, LAB; YN: AKL, ACT)
    TM_CES     = (:cg,),                    # the CES functions of production (AKL, YN)
    TM_RCJ     = (:r, :cg, :j, :bd),        # steps j of the input cg (LO, UP)
    # the climate module (equ_ext.cli; prep/cli.py)
    CM_HISTS   = (:i,),                     # the climate items
    CM_EMIS    = (:i,),                     # the emissions (CO2-GTC, and CH4-MT, N2O-MT when mapped)
    CM_KIND    = (:i,),                     # the items with reservoir balances (the emissions; FORCING)
    CM_TKIND   = (:i,),                     # the items with a total VAR_CLITOT
    CM_FORCMAP = (:i, :i2),                 # i2 contributes to the forcing i
    CM_BOXMAP  = (:i, :v, :box),            # the reservoir box of emission (or FORCING) i holds the quantity v
    CM_ATMAP   = (:i, :i2),                 # i2 is the atmospheric concentration (temperature change) of i
    CM_CONC    = (:i, :box),                # the boxes of i with a balance
    LOGJ       = (:j, :bd),                 # steps of the logarithm of consumption
    NITER      = (:u,),                     # the iterations allowed (Negishi loop of the report, rpt_ext.mlf)
    FIXB_RT    = (:r, :t),                  # RT_PP: the periods of a region in the window (rows of %R_T% and %R_V_T%)
    FIXB_NORT  = (:r, :t),                  # NO_RT: the periods of a region fixed at the loaded solution (solve.stp 57, 113)
    FIXB_RTPX  = (:r, :t, :p),              # RTPX: trade processes whose EQ_IRE rows are written (solve.stp 242-243)
    FIXB_IRE   = (:r, :t, :p, :ie),         # RTP_IRE: fixed trade linked to a region in the window, relaxed (solve.stp 250-256)
    FIXB_IREACT = (:r, :t, :p, :ie),        # the same, with REDUCE YES: the activity of the process relaxed too
    UC_T       = (:uc, :t),                 # global user constraints whose RHS is relaxed in the step (capacity terms, R_UC)
    UC_RN      = (:uc, :r),                 # user constraints with coefficients of both signs (r = IMPEXP: any region)
    PERIODYR   = (:t, :y),                  # years of period t
    Y_EOH      = (:y,),                     # years of the model horizon
    RP_UPR     = (:r, :p, :bd),             # processes with ramping costs
    RPG_PACE   = (:r, :p, :cg),             # activity efficiency given on the primary group itself
    PRC_PKNO   = (:r, :p),                  # processes that do not count towards the peak by capacity
    # availability by commodity, market shares
    RPS_CAFLAC = (:r, :p, :s, :bd),         # availability applies to the flows (EQ(l)_CAFLAC), not to the activity
    RPG_AFCX   = (:r, :p, :c, :ie),
    RVP_KMAP   = (:r, :v, :p, :k),          # vintages k that make up the capacity of (v, p)
    RTX_MARK   = (:r, :t, :item, :c, :bd, :s),
    RX_MARK    = (:r, :y, :item, :c, :bd),
    RPS_S2     = (:r, :p, :s),
    # retirement and refit
    PRC_RCAP   = (:r, :p),                  # processes whose capacity may be retired early
    VNTRT      = (:v, :t),                  # v lies before period t
    RTP_TT     = (:r, :tt, :t, :p),         # refit of host p commissioned in tt, counted in period t
    # dispatch
    RP_UPL     = (:r, :p, :bd),             # dispatchable processes: FX a minimum load, LO / UP a ramp rate down / up
    AFUPS      = (:r, :t, :p, :s),          # timeslices in which the load rows EQ_CAPLOAD replace the availability rows
    RPS_UPS    = (:r, :p, :s),              # timeslices that carry the off-line capacity (directly above those of the process)
    RP_UX      = (:r, :p),                  # dispatchable processes that are not vintaged: their capacity variable is used
    RP_PL      = (:r, :p, :bd),             # partial loads: N and FX (ACT_LOSPL given, or N from start-up costs on ANNUAL); UP a storage cycle limit
    RTP_PL     = (:r, :v, :p),              # partial-load vintages whose losses start at the minimum load (EQ_CAPLOAD takes VAR_UPS FX)
    RP_UPS     = (:r, :p, :tsl, :bd),       # start-ups: UP the level on which they are counted, FX the level of the on-line balance, N ...
    RP_UPC     = (:r, :p, :tsl, :bd),       # minimum on-line (UP) / off-line (LO) times, cycle limits (N)
    RP_DP      = (:r, :p),                  # dispatched by start-up type (eqlducs.vda: ACT_CSTSD and a minimum load)
    RP_DPL     = (:r, :p, :tsl),            # the levels on which such a process is dispatched
    RP_UPT     = (:r, :p, :upt, :bd),       # start-up types (UP) and the shut-down (LO, HOT)
    PRC_TSL    = (:r, :p, :tsl),            # timeslice level of the process
    DP_LOSD    = (:r, :v, :p),              # vintages with partial-load losses while starting up / shutting down
    TS_GROUP   = (:r, :tsl, :s),            # timeslices of level tsl
    # grids (powerflo.vda, gasgrids.vda)
    RC_GRID    = (:r, :t, :c),              # grid nodes
    RP_GRID    = (:r, :p),                  # lines with transfer factors (GR_PTDF)
    GR_TOP     = (:r, :c, :r2, :c2, :p),    # line p from node c of r to node c2 of r2, in its own direction
    GR_GRID    = (:j, :r, :c),              # node c (or ACT: the grid has electricity nodes) belongs to disjoint grid j
    GR_CANDID  = (:r, :t, :p),              # candidate lines (new lines with transfer factors)
    FINEST     = (:r, :s),                  # finest timeslices
    GR_GNALL   = (:r, :t, :c),              # nodes that receive a share of the supply (EQ_GR_GENALL)
    GR_ADO     = (:r, :t, :c),              # nodes whose demand is a fixed share (all but the largest of a grid)
    GR_ALGMAP  = (:r, :cg, :cg2),           # allocation of supply to the nodes: by group cg (cg2 = cg) or by commodity
    GR_ALLMAP  = (:r, :c, :com),            # node c of commodity com
    GR_DEMMAP  = (:r, :c, :com),            # node c takes demand of commodity com
    GR_PRCMAP  = (:r, :p, :c, :item),       # process p supplies commodity c as generation type item
    GR_GENP    = (:r, :p),                  # processes with a generation type
    GR_GMAPC   = (:r, :grid, :c),           # node c belongs to grid type grid
    GR_ENDC    = (:r, :grid, :cg),          # sectoral demands of a grid (DEM, NRG or a commodity)
    NRG_TMAP   = (:r, :nrg, :c),            # energy commodity c is of type nrg (ELC: electricity)
    PRC_CAP    = (:r, :p),                  # processes with capacity
    RLDC       = (:item,),                  # residual load curve: the types of generation with a variation (RL-DISP and given)
    GR_RLDC    = (:r, :t),                  #   regions and periods of the curve (t = 0: curtailment by VAR_COMNET)
    GR_RLGT    = (:r, :p, :item),           #   process p is of generation type item (RL-NDIS, RL-DISP, RL-THMIN, RL-WIND, ...)
    UC_GMAX    = (:uc, :r, :item, :c, :name), # maximum of user constraint uc (ucbet.vda): flows of group c (name N) or the
                                            #   activity of process item (name EACH), in region r or all (IMPEXP)
    UC_GMAXR   = (:r, :uc),                 #   the maximum is kept by region (VAR_UCR)
    PRC_DSCNCAP = (:r, :p),                 # processes with discrete or semi-continuous capacity additions (DSC)
    AFSV       = (:r, :t, :p, :s, :bd),     # availability rows of a process with simulated vintages (EQ_CAPVAC, not EQ_CAPACT)
    GG_RTPC    = (:r, :t, :p, :c),          # gas pipeline p at node c
    GG_LINK    = (:r, :p, :c, :r2, :c2),    # directed pipeline: flow from node c to node c2
    GG_TOP     = (:r, :c, :r2, :c2, :p),    # pipeline in its own direction
    GG_ARC     = (:r, :c, :r2, :c2),        # edge of the grid, in its own direction
    GG_EDGE    = (:r, :p, :r2),
    GG_WINK    = (:r, :p, :c, :r2, :c2),    # directed pipeline with stepped Weymouth rows
    GG_WTX     = (:r, :p, :c),              # pipelines with Taylor expansion of the Weymouth equation (fixed pressure points)
    OMG        = (:j,),                     # pressure points of the Taylor expansion
    GG_O       = (:j,),                     # steps of the stepped Weymouth rows
    # ancillary balancing services (ABS=YES: initmty.abs, coef_ext.abs, equ_ext.abs; abs.jl)
    BS_K       = (:item,),                  # sources of imbalance or provision (UP, LO, generation types, groups)
    BS_RTK     = (:r, :t, :item),           # sources of imbalance with a variance, by period
    BS_COMTS   = (:r, :c, :s),              # timeslices of the reserve commodities
    BS_APOS    = (:r, :c),                  # positive reserve commodities
    BS_ANEG    = (:r, :c),                  # negative reserve commodities
    BS_ABD     = (:r, :c, :bd),             # reserve commodities by direction (UP positive, LO negative)
    BS_BSC     = (:r, :p, :c),              # reserve provision by process
    BS_UPL     = (:r, :p, :bd),             # ramp rates of reserve-providing supply processes, written by ABS (EQ_BS07)
    BS_UPC     = (:r, :p, :tsl, :bd),       # minimum on-line / off-line times written by ABS (EQ_BS05)
    BS_TOP     = (:r, :p, :c, :io),         # the flows of the sources of imbalance
    BS_ENDP    = (:r, :p),                  # reserve provision by demand (end-use processes)
    BS_SUPP    = (:r, :p),                  # reserve provision by generation
    BS_STGP    = (:r, :p),                  # reserve provision by storage
    BS_NEGP    = (:r, :p),                  # processes with negative provision
    BS_PRS     = (:r, :p, :s),              # process timeslices for reserve tracking
    BS_SBD     = (:r, :s, :bd),             # timeslices with reserves of direction bd
    BS_UCMAP   = (:uc, :side, :r, :p, :c),  # reserve flows in UC_FLO
    BS_RVT     = (:r, :v, :t),              # vintages and periods with reserve variables (BS_LAMBDA given)
    BS_CONLY   = (:r, :v, :p, :c),          # port-only: RPC_CONLY of the reserve commodities, the limits of EQ_BS11
    # refinery blending (ppmain.mod 1230-1333)
    BLE_OPR    = (:r, :ble, :opr),          # blend ble is made of stream opr
    BLE_TP     = (:r, :t, :ble),            # periods in which the blend's specifications apply (from BL_START)
    BLE_ENV    = (:r, :c, :ble, :opr),      # emission c of blending opr into ble (ENV_BL given in a period)
    # bounds on undiscounted costs (eqbndcst.mod; port-only, prep/bndcst.py)
    BC_ROW     = (:r, :y1, :y2, :agg, :cur, :t), # EQ_BNDCST: costs of category agg in y1..y2; t the period of y2
    # stochastic TIMES (STAGES, stages.stc): the states of the world (SOW) w of the last stage
    SOW        = (:w,),                     # the SOWs
    SW_T       = (:t, :w),                  # the SOWs distinct in period t (each the first of its group)
    SW_TSW     = (:w, :t, :w2),             # SOW w is represented in period t by w2 (with SW_T(t,w2))
    SW_MAP     = (:t, :w, :j, :w2),         # (t, w) of SW_T belongs to SOW w2 of stage j
    SW_UCT     = (:uc, :t, :w),             # the dynamic user constraint uc has a row in (t, w) (stages.stc 177-178)
    OBJSW1     = (:obv,),                   # SPINES: the objective components of SOW '1' in every SOW (recurrin.stc 60-64)
    UCRTPSW1   = (:grp, :w),                # SPINES: the dynamic process bounds (PRC_DYNUC) of group grp written in SOW w
)

"""Parameters (name = key columns). A missing entry reads as 0; `has` tells the two apart."""
const PARS = (
    B          = (:t,),                     # first year of period
    E          = (:t,),                     # last year of period
    G_YRFR     = (:r, :s),                  # fraction of the year
    NORTS      = (:r, :t, :s),              # -INF: timeslice s off in milestone year t (dynamic timeslice trees, DYNTS)
    RS_FR      = (:r, :s, :ts),             # share of ts that falls in s
    RTCS_FR    = (:r, :t, :c, :s, :ts),     # commodity-specific correction of RS_FR
    PRC_CAPACT = (:r, :p),
    PRC_ACTFLO = (:r, :v, :p, :c),
    NCAP_PASTI = (:r, :v, :p),              # capacity installed before the first period
    COEF_CPT   = (:r, :v, :t, :p),          # share of the capacity installed in v available in t
    COEF_AF    = (:r, :v, :t, :p, :s, :bd), # availability factor
    COEF_PTRAN = (:r, :v, :p, :cg1, :c, :cg2, :s),
    RTP_FFCX   = (:r, :v, :t, :p, :cg1, :cg2),  # FLO_FUNCX: average age-shape of vintage v in period t, less 1 (coef_shp.mod)
    ACT_EFF    = (:r, :v, :p, :cg, :s),
    ACT_BND    = (:r, :t, :p, :s, :bd),
    COM_BNDNET = (:r, :t, :c, :s, :bd),     # bound on VAR_COMNET; above the commodity's timeslices a row (eqbndcom.mod); N: a switch (pp_prelv.vda)
    COM_BNDPRD = (:r, :t, :c, :s, :bd),     # the same for VAR_COMPRD
    PRC_REACT  = (:r, :t, :p),              # reactance of line p (powerflo.vda)
    GR_ADMIT   = (:r, :t, :c, :r2, :c2),    # admittance of the arc c of r -> c2 of r2: SUM(lines, 1 / PRC_REACT)
    CAP_BND    = (:r, :t, :p, :bd),
    UC_RHST    = (:uc, :t, :bd),            # RHS of a global user constraint by period (regions summed)
    UC_RHS     = (:uc, :bd),                # RHS of a global user constraint (regions and periods summed)
    UC_RHSR    = (:r, :uc, :bd),            # RHS of a regional constraint summing the periods
    UC_RHSTS   = (:uc, :t, :s, :bd),        # ... by period and timeslice
    FLO_SHAR   = (:r, :v, :p, :c, :cg, :s, :bd),
    FLO_CUM    = (:r, :p, :c, :y1, :y2, :bd),
    IRE_BND    = (:r, :t, :c, :s, :r2, :ie, :bd),   # bound on the trade of r in c with partner r2 (eqirebnd.mod)
    IRE_XBND   = (:r, :t, :c, :s, :ie, :bd),        # bound on all imports or exports of c of region r (eqxbnd.mod)
    UC_UCN     = (:uc, :side, :r, :t, :uc2),    # coefficient of VAR_UCRT(uc2,r,t) in the dynamic constraint uc (nested user constraints)
    UC_RHSRT   = (:r, :uc, :t, :bd),        # RHS of a regional constraint by period (read for the N type of a nested constraint)
    UC_CUMFLO  = (:uc, :r, :p, :c, :y1, :y2),   # coefficient of VAR_CUMFLO in a global or regional user constraint (c = ACT: UC_CUMACT)
    UC_CUMCOM  = (:uc, :r, :cv, :c, :y1, :y2),  # coefficient of VAR_CUMCOM in a global or regional user constraint (UC_RHS, UC_RHSR)
    COM_IE     = (:r, :t, :c, :s),          # commodity efficiency (losses)
    COM_PROJ   = (:r, :t, :c),              # demand
    COM_FR     = (:r, :t, :c, :s),          # demand load curve
    COM_AGG    = (:r, :t, :com, :c),        # com is aggregated into c
    IRE_FLOSUM = (:r, :t, :p, :com, :s, :ie, :c, :io),   # per unit of trade in com: auxiliary flow of c, consumed (IN) or released (OUT)
    COM_PKRSV  = (:r, :t, :c),              # peak reserve margin
    NCAP_PKCNT = (:r, :v, :p, :s),          # share of capacity counted at the peak
    FLO_PKCOI  = (:r, :t, :p, :c, :s),      # coincidence of consumption with the peak
    RPC_PKF    = (:r, :p, :c),              # processes contributing to the peak by production
    IRE_FLO    = (:rexp, :v, :p, :cexp, :rimp, :cimp, :s),
    IRE_CCVT   = (:r, :c, :reg, :com),      # commodity unit conversion between regions
    IRE_TSCVT  = (:r, :s, :reg, :ts),       # timeslice conversion between regions
    UC_FLO     = (:uc, :side, :r, :t, :p, :c, :s),
    UC_IRE     = (:uc, :side, :r, :t, :p, :c, :s, :ie),
    UC_CAP     = (:uc, :side, :r, :t, :p),
    UC_COM     = (:uc, :kind, :side, :r, :t, :c, :s, :grp),
    OBJ_PVT    = (:r, :t, :cur),            # present value factor of period t
    OBJ_LINT   = (:r, :t, :y, :cur),        # weight of year y's cost in period t (interpolation)
    OBJ_DISC   = (:r, :y, :cur),            # discount factor of year y
    OB_ACT     = (:r, :p, :cur, :y),        # activity cost
    OBJ_IPRIC  = (:r, :y, :p, :c, :s, :ie, :cur),
    COEF_OBINV = (:r, :v, :p, :cur),        # annualised investment cost per unit of capacity
    COEF_OBFIX = (:r, :v, :p, :cur),        # annual fixed cost per unit of capacity
    OB_FCOS    = (:r, :p, :c, :s, :cur, :y), # flow cost
    OB_FDEL    = (:r, :p, :c, :s, :cur, :y), # delivery cost
    OB_FTAX    = (:r, :p, :c, :s, :cur, :y), # tax less subsidy on a flow
    OBJ_COMNT  = (:r, :y, :c, :s, :kind, :cur), # cost, tax or subsidy (negative) on the net production of a commodity
    OBJ_COMPD  = (:r, :y, :c, :s, :kind, :cur), # the same on its gross production
    OBJSCC     = (:r, :v, :p, :cur),        # salvage value per unit of capacity
    OBJ_DCEOH  = (:r, :cur),                # discounting of the salvage value to the base year
    COEF_VNT   = (:r, :t, :p, :v),          # COEF_CPT in another order
    COM_PKFLX  = (:r, :t, :c, :s),          # extra load to be covered at the peak
    NCAP_COM   = (:r, :v, :p, :c, :io),     # commodity flow per unit of capacity
    COEF_CIO   = (:r, :v, :t, :p, :c, :io), # NCAP_COM multiplier less 1 for lagged flows (NCAP_CLAG, coef_shp.mod)
    COEF_ICOM  = (:r, :v, :t, :p, :c),      # flow of c consumed in t per unit of new capacity of v (NCAP_ICOM, coef_nio.mod)
    COEF_OCOM  = (:r, :v, :t, :p, :c),      # flow of c released in t per unit of new capacity of v (NCAP_OCOM, coef_nio.mod)
    COEF_RCOM  = (:r, :v, :t, :p, :c),      # flow of c released in t per unit of capacity of v retired early (RCAP_OCAP)
    RCAP_OCAP  = (:r, :v, :p, :c),          # flows of retired capacity: the age limit of the release (sign: before / after)
    FLO_BND    = (:r, :t, :p, :cg, :s, :bd),
    FLO_FR     = (:r, :t, :p, :c, :s, :l),     # fraction of the flow in s (LO/UP/FX); N: divisor of an aggregated flow
    FLO_ASHAR  = (:r, :v, :p, :cg, :cg2, :s, :bd),
    RPCG_ASHAR = (:r, :p, :cg, :cg2, :s),
    PRC_MARK   = (:r, :t, :p, :item, :c, :bd),
    NCAP_AFC   = (:r, :v, :p, :cg, :s),     # availability of the flows of group cg
    NCAP_AFCS  = (:r, :v, :p, :cg, :s),
    RS_TSLVL   = (:r, :s),                  # level of timeslice s
    UC_ACT     = (:uc, :side, :r, :t, :p, :s),
    LAGT       = (:t,),                     # years from the milestone year of t to that of the next period
    # storage
    PRC_SC     = (:r, :p),                  # logarithm of the number of storage cycles
    STG_MAXCYC = (:r, :v, :p),              # storage cycle limit over the lifetime
    COEF_AFUPS = (:r, :v, :p, :s),          # availability of the storage level, for the cycle limit
    NCAP_TLIFE = (:r, :v, :p),              # technical lifetime
    RS_STGPRD  = (:r, :s),                  # number of storage periods in a year, for timeslice s
    RS_STGAV   = (:r, :s),                  # average residence time
    STG_EFF    = (:r, :v, :p),
    STG_LOSS   = (:r, :v, :p, :s),          # loss per storage cycle (negative: equilibrium loss); per year for ANNUAL
    STG_CHRG   = (:r, :t, :p, :s),          # exogenous charge
    STG_SIFT   = (:r, :t, :p, :c, :s),      # load shifting: largest share of the demand for c (or of all, c = ACT) that can be shifted
    ACT_TIME   = (:r, :t, :p, :bd),         # load shifting: hours by which a load can be advanced (LO), delayed (UP) or either (FX)
    ACT_CSTRMP = (:r, :v, :p, :bd, :cur),   # cost of ramping up (UP) or down (LO), per unit of capacity
    JS_CCL     = (:r, :j, :s),              # number of cycles in a year of the timeslices below s
    RS_HR      = (:r, :s),                  # mid-point of timeslice s within its cycle, as a fraction of the year
    STGIN_BND  = (:r, :t, :p, :c, :s, :bd),
    STGOUT_BND = (:r, :t, :p, :c, :s, :bd),
    LEAD       = (:t,),                     # years from the previous milestone year
    UC_NCAP    = (:uc, :side, :r, :t, :p),  # coefficient of new capacity in a user constraint
    PRC_DYNUC  = (:uc, :side, :r, :t, :p, :grp, :bd),   # dynamic bound by process: growth multiplier (LHS) and constant (RHS) per year
    UC_TIME    = (:uc, :r, :t),             # constant per year on the right-hand side of a user constraint
    COEF_RPTI  = (:r, :v, :p),              # number of investments of vintage v within its period (short lifetimes)
    ACT_FLO    = (:r, :v, :p, :cg, :s),     # flow of group cg per unit of activity, where it multiplies the transformation
    D          = (:t,),                     # length of period
    FPD        = (:t,),                     # years of the period an activity counts for (ppmain.mod 165: D)
    NCAP_OLIFE = (:r, :v, :p),              # operating life: the activity of the vintage over its life, in years at full capacity
    M          = (:t,),                     # milestone year of period
    COM_ELAST  = (:r, :t, :c, :s, :bd),     # demand elasticities: only used under TIMESED, which the preprocessor rejects
    # retirement and refit
    RVPRL      = (:r, :v, :p),              # years between v and the last period in which v can be retired
    RP_RTF     = (:r, :p),                  # refit type of a host process
    PRC_REFIT  = (:r, :prc, :p),            # p is a refit of host prc
    RTFORC     = (:r, :v, :t, :p),          # forced retirement
    RCAP_BLK   = (:r, :v, :p),              # retirement in blocks of this size (a MIP: EQ_DSCRET)
    COEF_OBFIXR = (:r, :v, :t, :p, :cur),   # fixed cost saved in period t per unit of capacity of v retired
    OBJ_CINV   = (:r, :v, :p, :cur),        # standard objective: discounted investment cost per unit of capacity of v
    CST_ANNC   = (:r, :v, :p, :t, :name, :cur),  # eqbndcst.mod: annual undiscounted investment payment in t of vintage v (name INVCOST)
    UC_PVT     = (:r, :t),                  # port-only: COEF_PVT, for PERDISC in cumulative user constraints (only regions with PERDISC)
    UC_ICOST   = (:r, :v, :p, :name, :cur),      # port-only: OBJ_ICOST / OBJ_ITAX / OBJ_ISUB of v (name COST, TAX, SUB) for the NCAP cost attributes of user constraints
    OBJ_CFIX   = (:r, :v, :p, :cur),        # standard objective: discounted fixed costs over the life of a unit of capacity of v
    OBJ_PASTI  = (:r, :v, :p, :cur),        # past investment that still carries investment cost within the horizon
    OBJ_CDEC   = (:r, :v, :p, :cur),        # standard objective: discounted decommissioning cost per unit of capacity of v
    SALV_DEC   = (:r, :v, :p, :cur),        # salvage value of the decommissioning cost per unit of capacity, at EOH+1
    OBJ_SALVS  = (:r, :v, :p, :cur),        # salvage value of the decommissioning surveillance cost (NCAP_DLAGC) per unit of capacity
    OBJ_IAD    = (:r, :cur),                # constant of the investment cost equation
    NCAP_FDR   = (:r, :v, :p),              # functional depreciation rate
    # dispatch
    ACT_UPS    = (:r, :v, :p, :s, :bd),     # FX: minimum stable load, share of capacity; LO / UP: largest ramp down / up, share of capacity per hour
    ACT_MINLD  = (:r, :v, :p),              # minimum stable load, share of capacity
    ACT_LOSPL  = (:r, :v, :p, :bd),         # partial loads: FX the loss at the lowest load, LO / UP the loads where the losses start / end
    ACT_CSTUP  = (:r, :v, :p, :tsl, :cur),  # start-up cost per unit of capacity started, start-ups counted on level tsl
    ACT_CSTSD  = (:r, :v, :p, :upt, :bd, :cur), # start-up cost by type (UP), shut-down cost (HOT, LO), the two together (FX)
    ACT_SDTIME = (:r, :v, :p, :upt, :bd),   # start-up (UP) / shut-down (LO) time, hours
    DP_NON     = (:r, :v, :p, :upt, :tsl, :bd), # time off line before a start-up of type upt: LO its start, UP its width (fraction of the year)
    DP_PSUD    = (:r, :v, :p, :upt, :bd),   # load reached in an hour of starting up / shutting down; with losses, their share
    RS_MODUS   = (:r, :s, :j, :up, :sl),    # time from the start of timeslice sl to that of s within their cycle, as a fraction of the year
    # grids
    GR_GENMAP  = (:r, :p, :item),           # share of process p in generation type item
    GR_GENFR   = (:r, :t, :c, :item),       # share of generation type item supplied at node c
    OBJ_COMBAL = (:r, :t, :c, :s, :item, :cur), # cost on a component of a commodity balance (COM_CSTBAL; powerflo.vda CSTBAL)
    GR_ENDFR   = (:r, :t, :c, :cg),         # share of the demand of sector cg taken at node c
    GR_DEMFR   = (:r, :t, :c, :s),          # share of the total demand taken at node c
    GR_PTDF    = (:r, :t, :p, :c, :r2, :c2), # flow over line p out of node c per unit injection at node c2 of r2
    GR_FLOW    = (:r, :p, :c),              # > 0: line p leaves node c (its own direction)
    GR_CAPUP   = (:r, :t, :p),              # largest capacity of a candidate line
    GR_XBND    = (:r, :t),                  # N-1 factor on the line capacities of a grid
    GR_VARGEN  = (:r, :s, :item, :bd),      # residual load curve: variation of generation type item (FX: the type has a row)
    GR_THBND   = (:r, :t, :p, :bd),         #   thermal minimum: FX an amount, LO a level, UP 1/x of the online capacity
    GR_THMIN   = (:r, :t, :p),              #   processes with a thermal minimum bound
    UC_FLOBET  = (:uc, :r, :t, :p, :c),     # weight of the flows of group c (ACT: the activity) of p in the maximum of uc
    NCAP_DISC  = (:r, :t, :p, :unit),       # DSC: size of unit of a discrete capacity addition (unit 0: EPS, none)
    NCAP_SEMI  = (:r, :t, :p),              # DSC: lower bound of a semi-continuous capacity addition
    COEF_CSV   = (:r, :k, :t, :p, :v),      # share of the capacity of vintage k in simulated vintage v in period t (PRC_SIMV)
    GG_DENS    = (:r, :c),                  # density of the gas at node c
    GG_GAMMA   = (:r, :t, :p, :c),          # compression factor at the inlet node of a pipeline (> 1)
    GG_KGF     = (:r, :t, :p, :c),          # Weymouth constant
    GG_KLP     = (:r, :t, :p, :c),          # linepack constant (c = ACT: largest linepack)
    GG_MM      = (:r, :t, :p, :c),          # big-M of the pressure-difference bound
    GG_PRBD    = (:r, :t, :c, :bd),         # nodal pressure bounds
    GG_PP      = (:r, :t, :p, :c, :bd, :j), # fixed pressure points: inlet UP, outlet LO
    GG_PPM     = (:r, :t, :p, :c, :r2, :c2, :j),   # alternate pressure points
    GG_PPW     = (:r, :t, :p, :c, :r2, :c2, :j),   # alternate Weymouth points
    ELS_COEF   = (:r, :t, :c, :s, :j, :bd, :cur),  # value of a step of an elastic demand (EQ_OBJELS, eqobjels.mod 18-21)
    GG_M1      = (),                        # 1 in a MIP (binary flow directions), 0 in the LP
    # ancillary balancing services (abs.jl)
    BS_RTYPE   = (:r, :c),                  # type of reserve commodity c: 1..4 (FCR, aFRR, mFRR, RR), negative for downward
    BS_LAMBDA  = (:r, :t, :c),              # fudge factor for dependencies in the reserve requirements
    BS_DETWT   = (:r, :t, :c),              # weight of the deterministic reserve demand
    BS_OMEGA   = (:r, :t, :c, :s),          # how the demand is formed from the deterministic and probabilistic parts (t = 0: the rows of EQ_BS00)
    BS_DELTA   = (:r, :t, :c, :s),          # calibration of the probabilistic demand
    BS_SIGMA   = (:r, :t, :c, :item, :s),   # standard deviation of imbalance source item
    BS_SHARE   = (:r, :t, :c, :item, :bd),  # share of group item in the provision (bd N: LAMBDA, for the max rows)
    BS_RTCS    = (:rsp, :r, :t, :c, :s),    # EXOGEN / WMAXSI deterministic demands, OMEGA, DELTA by timeslice
    BS_CAPACT  = (:r,),                     # conversion of exogenous reserve demand to activity units
    BS_STIME   = (:r, :p, :c, :bd),         # minimum hours of reserve provision from storage
    BS_RMAX    = (:r, :v, :p, :c, :s),      # maximum reserve provision as a share of capacity
    BS_MAINT   = (:r, :v, :p, :s),          # continuous maintenance duration in hours (negative: from the timeslice above)
    BS_BNDPRS  = (:r, :t, :p, :c, :s, :bd), # bound on process reserve provision (N: a bound is given)
    BS_TSCYC   = (:r, :s),                  # port-only: TS_CYCLE, the cycles of timeslice s in the year (EQ_BS27)
    BS_EUCAP   = (:r, :v, :t, :p, :s),      # port-only: electricity input per unit of activity of an end-use process (EQ_BS24)
    # refinery blending
    BLE_BAL    = (:r, :t, :ble, :opr),      # blend produced per unit of stream opr (REFUNIT: energy, weight, volume)
    ENV_BL     = (:r, :c, :ble, :opr, :t),  # emission c per unit of stream opr blended into ble
    BL_TYPE    = (:r, :ble, :spe),          # specification type: 1 =L=, 2 =G=, 3 =E=, 4 =N=
    BL_COM     = (:r, :ble, :opr, :spe),    # quality spe of stream opr
    BL_SPEC    = (:r, :ble, :spe),          # specification spe of the blend
    RU_CVT     = (:r, :ble, :spe, :opr),    # unit conversion of the specification (REFUNIT / BL_UNIT)
    OBJ_BLNDV  = (:r, :y, :ble, :opr, :cur),  # variable cost of blending, by year
    BC_NCAP    = (:r, :y1, :y2, :agg, :cur, :t, :p),         # EQ_BNDCST: coefficient of VAR_NCAP(r,t,p)
    BC_COMNET  = (:r, :y1, :y2, :agg, :cur, :t, :c, :s),     #   of VAR_COMNET(r,t,c,s)
    BC_COMPRD  = (:r, :y1, :y2, :agg, :cur, :t, :c, :s),     #   of VAR_COMPRD(r,t,c,s)
    BC_FLO     = (:r, :y1, :y2, :agg, :cur, :t, :p, :c, :s), #   of the flows of (t,p,c,s), all vintages
    BC_AGG     = (:r, :y1, :y2, :agg, :cur, :agg2),          #   of a component's VAR_CUMCST in an aggregate's row
    # TIMES-MACRO MLF (equ_ext.mlf; the calibration of MACRO and presolve.mlf, prep/mlf.py)
    BDSIG      = (:bd,),                    # LO: 1, UP: -1
    RD_NLP     = (:r, :c),                  # 1: the demand is the variable VAR_DEM in the commodity balances and the peaks
    TM_NWT     = (:r,),                     # Negishi weight of the region
    TM_PWT     = (:t,),                     # weight of the period in the utility
    TM_DFACT   = (:r, :t),                  # utility discount factor
    TM_UDF     = (:r, :t),                  # weight of the annual costs of a region without MACRO in the utility
    TM_MIDCON  = (:r, :t),                  # consumption at the middle of the steps of its logarithm
    TM_LOGVAL  = (:j, :bd),                 # change of consumption at step j of its logarithm
    TM_LOGJOT  = (),                        # size of a step of the logarithm
    TM_LSC     = (),                        # scale of the steps of the logarithm
    TM_SCALE_UTIL = (),
    TM_SCALE_CST = (),
    TM_SCALE_NRG = (),
    TM_ANNC    = (:r, :t),                  # annual energy system costs of the reference
    TM_SHAR    = (:r, :t, :cg, :cg1),       # shares of the CES functions (and their reverse, cg1 the aggregate)
    TM_CIE     = (:r, :t, :cg),             # level of the CES function cg against its share-weighted inputs
    TM_CESLEV  = (:r, :t, :cg),             # sum of the inputs of the CES function cg at the calibration
    TM_PREF    = (:r, :t, :cg),             # reference price of cg
    TM_QREF    = (:r, :t, :cg),             # reference quantity of cg
    TM_AGC     = (:r, :t, :cg, :cg1, :j, :bd), # aggregation coefficient of step j of input cg1 of the CES function cg
    TM_STEP    = (:r, :cg, :bd),            # number of steps
    TM_VOC     = (:r, :t, :cg, :bd),        # range of the steps (a fraction of the reference quantity)
    TM_TSRV    = (:r, :t),                  # capital surviving a period
    TM_GROWV   = (:r, :t),                  # growth rate (percent)
    TM_DEPR    = (:r,),                     # depreciation rate (percent)
    TM_Y0      = (:r,),                     # production of the first period
    TM_L       = (:r, :t),                  # labour index
    TM_IVETOL  = (:r,),                     # exponent of the bound on investment and energy costs
    TM_AEEIFAC = (:r, :t, :c),              # demand decoupling factor
    TM_DEM     = (:r, :t, :c),              # reference demand (c = ACT: their aggregate)
    TM_AMP     = (:r, :t),                  # cost amplifier
    TM_TAXREV  = (:r, :t),                  # tax revenues rebated
    TM_HDF     = (:r, :t),                  # discount factor of the energy costs
    TM_DEFVAL  = (:u,),                     # defaults of MACRO (NEGTOL: the tolerance of the Negishi loop)
    # the climate module (equ_ext.cli, uc_cli.mod; prep/cli.py)
    CM_LED     = (:y,),                     # years from the previous milestone year (the first: the calibration lag)
    CM_GHGMAP  = (:r, :c, :i),              # emission commodity c counts for the global emission i
    CM_PPM     = (:i,),                     # Gt (Mt) per ppm (ppb)
    CM_EVAR    = (:i, :y),                  # weight of the modelled emissions
    CM_BEMI    = (:i, :y),                  # exogenous emissions
    CM_LINFOR  = (:y, :i, :l),              # linearised forcing of emission i: FX constant, N slope
    CM_PHI     = (:i, :box, :box2),         # transport matrix of i between the boxes (box2 = i: the emission inflow)
    CM_MAXC    = (:y, :i),                  # bound on a climate quantity
    CM_EXOFORC = (:y,),                     # exogenous forcing
    CM_AA      = (:i, :y, :w, :box, :box2), # transport over the years of the period, from box2 at the year before
    CM_BB      = (:i, :y, :w, :box),        # share of the period's total arriving in the box
    CM_CC      = (:i, :y, :w, :box),        # share of the previous period's total arriving in the box
    CM_STAT0   = (:i, :box),                # quantity in the box at the calibration year
    UC_CLI     = (:uc, :side, :r, :y, :i),  # climate quantity in a user constraint
    # stochastic TIMES (STAGES)
    SW_PROB    = (:w,),                     # probability of SOW w
    SW_TPROB   = (:t, :w),                  # probability of (t, w) of SW_T: the sum of its SOWs'
    S_COM_PROJ = (:r, :t, :c, :j, :w),      # multiplier of COM_PROJ in SOW w of stage j
    S_COM_TAX  = (:r, :t, :c, :s, :cv, :cur, :j, :w), # tax on the net / gross production by SOW (j = 1: merged)
    OBJ_SIC    = (:r, :t, :p, :w),          # multiplier less 1 of the investment cost in (t, w) (S_NCAP_COST)
    OBJ_CSIC   = (:r, :v, :p, :cur),        # discounted investment cost of v net of salvage, per unit of OBJ_SIC
    RTP_FFCS   = (:r, :v, :p, :cg1, :cg2, :w),  # multiplier less 1 of the transformation (cg1, cg2) of vintage v in SOW w (S_FLO_FUNC)
    RTP_SAFS   = (:r, :t, :p, :s, :w),      # multiplier less 1 of the availability factor in (t, w) (S_NCAP_AFS)
    S_COM_FR   = (:r, :t, :c, :s, :j, :w),  # multiplier less 1 of COM_FR in SOW w (j = 1: merged, S_COM_FR)
    RTCS_SFRW  = (:r, :t, :c, :s, :ts, :w), # change of RTCS_FR in (t, w): SUM(SW_T2W(SOW,T,W,T0),RCS_SSFR(R,C,S,TS,W,T0)) (S_COM_FR)
    SW_SCUM    = (),                        # port-only, SPINES with SOLVEDA 1 (%SCUM%): the cumulative rows once, as expected values
    SW_SENSIS  = (),                        # port-only, SENSIS: one deterministic model per SOW of the first period (sensis_sows)
    S_FLO_CUM  = (:r, :p, :c, :y1, :y2, :bd, :j, :w), # cumulative flow bound by SOW (j = 1: merged, stages.stc)
    S_CM_MAXC  = (:y, :i, :j, :w),          # bound on a climate quantity by SOW (j = 1: merged, coef_ext.cli)
)

"""Variables (name = columns). Bounds come with the input; the default is [0, +inf)."""
const VARS = (
    VAR_ACT    = (:r, :v, :t, :p, :s),
    VAR_FLO    = (:r, :v, :t, :p, :c, :s),
    VAR_IRE    = (:r, :v, :t, :p, :c, :s, :ie),
    VAR_NCAP   = (:r, :v, :p),
    VAR_CAP    = (:r, :t, :p),
    VAR_COMNET = (:r, :t, :c, :s),
    VAR_COMPRD = (:r, :t, :c, :s),
    VAR_CUMFLO = (:r, :p, :c, :y1, :y2),
    VAR_CUMCOM = (:r, :c, :cv, :y1, :y2),
    VAR_SIN    = (:r, :v, :t, :p, :c, :s),  # flow into storage
    VAR_SOUT   = (:r, :v, :t, :p, :c, :s),  # flow out of storage, before losses
    VAR_UDP    = (:r, :v, :t, :p, :s, :bd), # load change between timeslices (ramping; shifted load)
    VAR_UPS    = (:r, :v, :t, :p, :s, :l),  # dispatch: capacity off line in timeslice s (l = N)
    VAR_RCAP   = (:r, :v, :t, :p),          # capacity of v retired in t
    VAR_SCAP   = (:r, :v, :t, :p),          # capacity of v retired by t (t = 0: capacity without salvage value)
    VAR_DRCAP  = (:r, :v, :t, :p, :j),      # retirement in blocks (j = 2) or of all the rest (j = 1): integer in the MIP
    VAR_UC     = (:uc,),
    VAR_UCR    = (:uc, :r),
    VAR_UCT    = (:uc, :t),
    VAR_UCTS   = (:uc, :t, :s),
    VAR_UCRT   = (:uc, :r, :t),
    VAR_UCRTS  = (:uc, :r, :t, :s),
    VAR_GRIDIO = (:r, :t, :c, :com, :s, :io), # flow between commodity c and grid node com (c = ACT: aggregate withdrawals)
    VAR_COMAUX = (:r, :t, :c, :s),          # net injection at a grid node in the transfer-factor equations (free)
    VAR_XCAP   = (:r, :t, :p),              # virtual capacity of a candidate line
    VAR_GG_PR  = (:r, :t, :c, :s),          # pressure at node c
    VAR_GG_MF  = (:r, :t, :p, :c, :r2, :c2, :s), # mass flow from node c to node c2
    VAR_GG_PDIF = (:r, :t, :p, :c, :r2, :c2, :s), # pressure difference (c2 = ACT: unsigned pressure; c2 = c: slack)
    VAR_GG_PADD = (:r, :t, :p, :c, :s),     # pressure added by the compressor at node c (c = ACT: linepack)
    VAR_GG_STEP = (:r, :t, :p, :c, :s, :j), # weight of step j of the stepped Weymouth rows
    VAR_GG_Y   = (:r, :t, :p, :c, :s),      # flow direction (binary in the MIP)
    VAR_OBJ    = (:r, :obv, :cur),
    VAR_ANNCST = (:obv, :r, :t, :cur),
    OBJZ       = (),
    VAR_EXPOBJ = (),                        # stochastic TIMES: the expected value of the objective (VAS_EXPOBJ, free)
    VAR_ELAST  = (:r, :t, :c, :s, :j, :bd), # step j of the change bd (LO, UP) of an elastic demand (TIMESED)
    VAR_OBJELS = (:r, :bd, :cur),           # change of consumer surplus by elastic demands (EQ_OBJELS)
    VAR_BLND   = (:r, :t, :ble, :opr),      # stream opr blended into ble
    VAR_UPT    = (:r, :v, :t, :p, :s, :upt), # capacity started up in timeslice s, by start-up type
    VAR_CUMCST = (:r, :y1, :y2, :agg, :cur), # undiscounted costs of category agg in the years y1..y2
    VAR_COMLV  = (:clvt, :r, :t, :c, :s),  # ABS: deterministic (DET) and probabilistic (PRB) reserve demand levels
    VAR_BSPRS  = (:r, :v, :t, :p, :c, :s, :l), # ABS: reserve provision (N spinning, FX non-spinning; c = ACT: start-up / shut-down
                                            #   capacity, maintenance; v = t, l = UP: the slack of a bound, EQ_BS26)
    VAR_RLD    = (:r, :t, :s, :item),       # residual load by generation type (RL-DISP: free; RL_THMIN: see resloadc.jl)
    VAR_DNCAP  = (:r, :t, :p, :unit),       # DSC: units built (SOS1 over the units; binary with EQ_DSCONE), see dsc.jl
    VAR_SNCAP  = (:r, :t, :p),              # DSC: semi-continuous capacity addition
    # TIMES-MACRO (mod_vars.tm)
    VAR_UTIL   = (),                        # total utility (free; maximised)
    VAR_C      = (:r, :t),                  # consumption
    VAR_INV    = (:r, :t),                  # investment
    VAR_EC     = (:r, :t),                  # energy costs in MACRO
    VAR_NTX    = (:r, :t),                  # trade in the numeraire (free)
    VAR_K      = (:r, :t),                  # capital
    VAR_D      = (:r, :t, :cg),             # the production factors (KN, LAB, AKL, YN, ACT)
    VAR_DEM    = (:r, :t, :c),              # useful demand (c = ACT: the aggregate)
    VAR_SP     = (:r, :t, :cg),             # scaling of the shadow price
    VAR_OBJCOST = (:r, :t),                 # annual costs of the energy system
    VAR_MELA   = (:r, :t, :cg, :j, :bd),    # step j of a linearised function of cg (LO: down, UP: up)
    # the climate module (mod_vars.cli)
    VAR_CLITOT = (:i, :y),                  # total emission or forcing
    VAR_CLIBOX = (:i, :box, :y),            # quantity in a climate reservoir
)

"""Variables whose default is free."""
const FREE = (:VAR_UC, :VAR_UCR, :VAR_UCT, :VAR_UCTS, :VAR_UCRT, :VAR_UCRTS, :OBJZ, :VAR_COMAUX, :VAR_UTIL, :VAR_NTX, :VAR_EXPOBJ)

"""
Lookups: name = (table, key columns). `ix.name[key...]` returns the remaining columns of the
matching rows (a plain label when one column remains), in table order; nothing matches -> empty.
"""
const INDEXES = (
    vintages   = (:RTP_VINTYR, (:r, :t, :p)),        # -> v
    els_bal    = (:ELS_BAL,    (:r, :t, :c, :s)),    # -> (j, bd): the steps of an elastic demand in its balance
    cpt_v      = (:COEF_CPT,   (:r, :t, :p)),        # -> v with capacity available in t
    cptyr      = (:RTP_CPTYR,  (:r, :t)),            # -> (v, p)
    vara_p     = (:RTP_VARA,   (:r, :t)),            # -> p
    prc_ts     = (:PRC_TS,     (:r, :p)),            # -> s
    rps_s1     = (:RPS_S1,     (:r, :p)),            # -> s
    afs        = (:AFS,        (:r, :t, :p)),        # -> (s, bd)
    flow_cs    = (:RTPCS_VARF, (:r, :t, :p)),        # -> (c, s)
    flow_s     = (:RTPCS_VARF, (:r, :t, :p, :c)),    # -> s
    rpcs_s     = (:RPCS_VAR,   (:r, :p, :c)),        # -> s
    rpc_c      = (:RPC,        (:r, :p)),            # -> c
    pcg        = (:RPC_PG,     (:r, :p)),            # -> c
    rpc_act    = (:RPC_ACT,    (:r, :p)),            # -> c
    prc_ts2    = (:PRC_TS2,    (:r, :p)),            # -> s
    top_c      = (:TOP,        (:r, :p, :io)),       # -> c
    top_p      = (:TOP,        (:r, :c, :io)),       # -> p
    fs_emit    = (:FS_EMIT,    (:r, :p, :c)),        # -> (cg, com)
    ffunc      = (:RPCC_FFUNC, (:r, :p)),            # -> (cg1, cg2)
    rpg_ace    = (:RPG_ACE,    (:r, :p)),            # -> (cg, io)
    rpc_ace    = (:RPC_ACE,    (:r, :p)),            # -> c
    group_c    = (:COM_GMAP,   (:r, :cg)),           # -> c
    com_ts     = (:COM_TS,     (:r, :c)),            # -> s
    varc_ts    = (:RTCS_VARC,  (:r, :t, :c)),        # -> s
    agg_into   = (:COM_AGG,    (:r, :t, :c)),        # -> com
    ire_aux    = (:IRE_FLOSUM, (:r, :t, :c, :io)),   # -> (p, com, s, ie)
    pkc_p      = (:RPC_PKC,    (:r, :c)),            # -> p
    ts_below   = (:TS_MAP,     (:r, :s)),            # -> ts
    ts_tree    = (:RS_TREE,    (:r, :s)),            # -> ts
    ts_frac    = (:RS_FR,      (:r, :s)),            # -> ts
    ts_frac_in = (:RS_FR,      (:r, :ts)),           # -> s: the timeslices s with RS_FR(r, s, ts) (onbranch, terms.jl)
    ts_above   = (:TS_MAP,     (:r, :ts)),           # -> s: ts and the timeslices above it
    ire_p      = (:RPC_IRE,    (:r, :c, :ie)),       # -> p
    ireio      = (:RPC_IREIO,  (:r, :io)),           # -> (p, c, ie)
    importers  = (:TOP_IRE,    (:rexp, :cexp, :p)),  # -> (rimp, cimp)
    exporters  = (:TOP_IRE,    (:rimp, :cimp, :p)),  # -> (rexp, cexp)
    tscvt      = (:IRE_TSCVT,  (:r, :reg, :ts)),     # -> s
    lint       = (:OBJ_LINT,   (:r, :t, :cur)),      # -> y
    uc_ts_sum  = (:UC_TS_SUM,  (:r, :uc)),           # -> s
    uc_map_flo = (:UC_MAP_FLO, (:uc, :side, :r)),    # -> (p, c)
    uc_ucn     = (:UC_UCN,     (:uc, :side, :r, :t)), # -> uc2 (nested user constraints)
    uc_map_ire = (:UC_MAP_IRE, (:uc, :r)),           # -> (p, c, ie)
    uc_gmap_p  = (:UC_GMAP_P,  (:r, :uc, :grp)),     # -> p
    rvpt_v     = (:RVPT,       (:r, :p, :t)),        # -> v
    uc_gmap_c  = (:UC_GMAP_C,  (:r, :uc, :kind)),    # -> (c, grp)
    uc_regions = (:UC_R_SUM,   (:uc,)),              # -> r
    uc_t_sum   = (:UC_T_SUM,   (:r, :uc)),           # -> t
    ncap_com   = (:NCAP_COM,   (:r, :c, :io)),       # -> (v, p)
    icom_at    = (:COEF_ICOM,  (:r, :t, :c)),        # -> (v, p)
    ocom_at    = (:COEF_OCOM,  (:r, :t, :c)),        # -> (v, p)
    stg_c      = (:RPC_STG,    (:r, :p)),            # -> c
    stgtss_c   = (:PRC_STGTSS, (:r, :p)),            # -> c
    stgips_c   = (:PRC_STGIPS, (:r, :p)),            # -> c
    parent     = (:RS_BELOW1,  (:r, :ts)),           # -> s
    period_y   = (:PERIODYR,   (:t,)),               # -> y
    stg_p      = (:RPC_STG,    (:r,)),               # -> (p, c)
    ls_c       = (:RPC_LS,     (:r, :p)),            # -> c
    cycle_of   = (:RS_UP,      (:r, :s)),            # -> (j, up)
    cycle_ts   = (:RJ_SL,      (:r, :j, :up)),       # -> sl
    children   = (:RS_BELOW1,  (:r, :s)),            # -> ts
    prcts_up   = (:RPS_PRCTS,  (:r, :p)),            # -> s
    rtp_p      = (:RTP,        (:r, :t)),            # -> p
    rps_stg    = (:RPS_STG,    (:r, :p)),            # -> s
    ts_prev    = (:RS_PREV,    (:r, :s)),            # -> ts
    stl_lv     = (:RP_STL,     (:r, :p)),            # -> (tsl, l)
    ts_ann     = (:TS_ANN,     (:s,)),               # -> ts
    ptran      = (:COEF_PTRAN, (:r, :v, :p)),        # -> (cg1, c, cg2, s)
    kmap       = (:RVP_KMAP,   (:r, :v, :p)),        # -> k
    type_of    = (:COM_TMAP,   (:r, :c)),            # -> cg
    rpc_ire    = (:RPC_IRE,    (:r, :p, :c)),        # -> ie
    afcx       = (:RPG_AFCX,   (:r, :p, :c)),        # -> ie
    rps_s2     = (:RPS_S2,     (:r, :p)),            # -> s
    rpc_p      = (:RPC,        (:r, :c)),            # -> p
    comprd_s   = (:RHS_COMPRD, (:r, :t, :c)),        # -> s
    refits     = (:PRC_REFIT,  (:r, :prc)),          # -> p
    rx_mark    = (:RX_MARK,    (:r, :item, :c, :bd)), # -> y
    retirable  = (:RTP_CPTYR,  (:r, :t, :p)),        # -> v
    afups      = (:AFUPS,      (:r, :t, :p)),        # -> s
    ups_ts     = (:RPS_UPS,    (:r, :p)),            # -> s
    ups_lv     = (:RP_UPS,     (:r, :p)),            # -> (tsl, bd)
    upc_lv     = (:RP_UPC,     (:r, :p)),            # -> (tsl, bd)
    dpl        = (:RP_DPL,     (:r, :p)),            # -> tsl
    upt_of     = (:RP_UPT,     (:r, :p)),            # -> (upt, bd)
    prc_tsl    = (:PRC_TSL,    (:r, :p)),            # -> tsl
    ts_group   = (:TS_GROUP,   (:r, :tsl)),          # -> s
    gr_prcmap  = (:GR_PRCMAP,  (:r,)),               # -> (p, c, item)
    gr_algmap  = (:GR_ALGMAP,  (:r, :cg)),           # -> cg2
    gr_allmap  = (:GR_ALLMAP,  (:r, :c)),            # -> com
    gr_nodes   = (:GR_ALLMAP,  (:r, :com)),          # -> c
    gr_dem_of  = (:GR_DEMMAP,  (:r, :c)),            # -> com
    gr_dem_at  = (:GR_DEMMAP,  (:r, :com)),          # -> c
    gr_gmapc   = (:GR_GMAPC,   (:r, :grid)),         # -> c
    gr_grid_of = (:GR_GMAPC,   (:r, :c)),            # -> grid
    gr_endc    = (:GR_ENDC,    (:r, :grid)),         # -> cg
    gg_link    = (:GG_LINK,    (:r, :p, :c)),        # -> (r2, c2)
    gg_ppw     = (:GG_PPW,     (:r, :t, :p, :c, :r2, :c2)), # -> j
    gg_pp      = (:GG_PP,      (:r, :t, :p, :c, :bd)),      # -> j
    top_ire_rr = (:TOP_IRE,    (:rexp, :rimp, :p)),  # -> (cexp, cimp)
    ble_opr    = (:BLE_OPR,    (:r, :ble)),          # -> opr
    opr_ble    = (:BLE_OPR,    (:r, :opr)),          # -> ble
    ble_env    = (:BLE_ENV,    (:r, :c)),            # -> (ble, opr)
)

"""Labels the equations refer to by name."""
const KEYWORDS = (:ANNUAL, :ACT, :IN, :OUT, :IMP, :EXP, :LO, :UP, :FX, :LHS, :PRD, :NET, :CAP,
    :COMPRD, :COMNET, :NEWFLO, :SEVERAL, :EACH, :SUCC, :DYNAMIC, :RHS, :GROWTH, :FLO, :IRE, :OBJINV, :OBJFIX, :OBJVAR, :N, :STG, :NST, :STK, :COST, :NCAP, :PERIOD, :UCN, :OBJSAL, :SYNC, :BUILDUP, :NRG, :COMCON, :CAPACT, :CUMSUM, :ANNUL, :INVCOST, :TAX, :SUB, :DELIV, :EFF, :PERDISC, :INVTAX, :INVSUB, :ONLINE, Symbol("CUM+"),
    :CON, :YN, :KN, :DEM)

"""
Input that would need equations or terms that are not written yet. `build` stops when any of
these tables has rows, instead of producing a model that silently ignores them.
"""
const UNSUPPORTED = Pair{String,Vector{Symbol}}[
    "flow shape multipliers by timeslice and state of the world (RTP_FFCS)" => [:RTP_FFCS],
    "damage costs" => [:DAM_COST],
]
