# SPDX-License-Identifier: GPL-3.0-or-later
# The calibration of TIMES-MACRO in its linearised form (MLF): calibase.mlf with ddfupd.msa, the NLP model MCE solved
# with Ipopt (JuMP), statement by statement as TIMES has them. Compiled with TimesEq (TimesEqMlfExt.jl) when Ipopt is in
# its environment; run by tools/mlf_calibrate.jl, which says what goes in and what comes out.
#
# The calibration is the one part of an MLF run that is computed within a tolerance: Ipopt's local optimum agrees with
# the one CONOPT finds in GAMS to the accuracy of the solvers. Ipopt's options are fixed (IPOPT_OPTIONS) and one thread
# is used, so that a run is the same on the same machine and code.
# (JuMP and Ipopt: from the module that includes this file)

const IPOPT_OPTIONS = ("linear_solver" => "mumps", "tol" => 1e-10, "constr_viol_tol" => 1e-10, "acceptable_tol" => 1e-9, "max_iter" => 3000,
                       "print_level" => 0, "sb" => "yes")

const K = Tuple{Vararg{String}}
const D = Dict{K,Float64}

# ---------------------------------------------------------------------------------------------- the data
struct Data
    p::Dict{String,D}                       # parameters, sets (value 1) and scalars (key ())
    order::Dict{String,Vector{String}}      # the ordered sets
end
par(d::Data, n) = get!(D, d.p, n)
val(P::D, k...) = get(P, k, 0.0)
function put!(P::D, k::K, x::Float64)       # an assignment: 0 is no record
    x == 0 ? delete!(P, k) : (P[k] = x)
end

function read_in(file)
    d = Data(Dict{String,D}(), Dict{String,Vector{String}}())
    for line in eachline(file)
        isempty(line) && continue
        f = split(line, '\t')
        if startswith(f[1], "@")
            d.order[f[1][2:end]] = String.(f[2:end])
        else
            par(d, String(f[1]))[Tuple(String.(f[2:end-1]))] = parse(Float64, f[end])
        end
    end
    return d
end

# ------------------------------------------------------------------------------------- the model MCE
# The variables of MACRO (mod_vars.tm): their levels, bounds and, after a solve, marginals, by key.
const VARS = ("VAR_UTIL", "VAR_C", "VAR_INV", "VAR_EC", "VAR_NTX", "VAR_K", "VAR_D", "VAR_DEM", "VAR_SP")
const FREE = ("VAR_UTIL", "VAR_NTX")
struct State
    l::Dict{String,D}; lo::Dict{String,D}; up::Dict{String,D}; m::Dict{String,D}    # m: marginals of variables and equations
end
lo(S, v, k) = get(S.lo[v], k, v in FREE ? -Inf : 0.0)
up(S, v, k) = get(S.up[v], k, Inf)
function fx!(S, v, k, x)                    # .FX: both bounds and the level
    S.lo[v][k] = x; S.up[v][k] = x; S.l[v][k] = x
end

"""
MODEL MCE / EQ_UTIL, EQ_PROD_Y, EQ_AKL, EQ_LABOR, EQ_KNCAP, EQ_MCAP, EQ_TMC, EQ_DD, EQ_IVECBND, EQ_ESCOST, EQ_TRDBAL /;
SOLVE MCE MAXIMIZING VAR_UTIL USING NLP, for the regions MR (equ_ext.mlf 8-62). Each equation is stated with its
variables on the left and its constant on the right, as GAMS normalises it; its marginal is GAMS's, the change of the
utility per unit of the right-hand side (-dual in JuMP for a maximisation); a variable's marginal is its reduced cost.
`replace`: SOLVEOPT=REPLACE (the records of the variables not in the model go back to their defaults), else MERGE.
"""
function solve_mce!(d::Data, S::State, MR::Vector{String}; replace::Bool = false)
    T = d.order["T"]; TB = T[1]; PP = T[2:end]; TLAST = T[end]; DM = ("ACT",)
    p(n) = par(d, n)
    NWT, PWT, DFACT, AKL, RHO, B, KPVS, L, TSRV, NYD, GROWV, DEPR = p("TM_NWT"), p("TM_PWT"), p("TM_DFACT"), p("TM_AKL"),
        p("TM_RHO"), p("TM_B"), p("TM_KPVS"), p("TM_L"), p("TM_TSRV"), p("D"), p("TM_GROWV"), p("TM_DEPR")
    AEEIFAC, Y0, IVETOL, QSFA, QSFB, AMP, HDF = p("TM_AEEIFAC"), p("TM_Y0"), p("TM_IVETOL"), p("TM_QSFA"), p("TM_QSFB"),
        p("TM_AMP"), p("TM_HDF")
    nrg, sutil = val(p("TM_SCALE_NRG")), val(p("TM_SCALE_UTIL"))
    m = Model(Ipopt.Optimizer)
    for (k, v) in IPOPT_OPTIONS
        set_attribute(m, k, v)
    end
    X = Dict{Tuple{String,K},VariableRef}()
    function var(v, k...)
        get!(X, (v, k)) do
            x = @variable(m)
            a, b = lo(S, v, k), up(S, v, k)
            if a == b
                fix(x, a)
            else
                isfinite(a) && set_lower_bound(x, a)
                isfinite(b) && set_upper_bound(x, b)
            end
            l = get(S.l[v], k, 0.0)                     # the level as the starting point, projected on the bounds
            set_start_value(x, min(max(l, a), b))
            x
        end
    end
    E = Dict{Tuple{String,K},ConstraintRef}()
    # EQ_UTIL.. SUM(MR(R), SUM(T, TM_NWT(R) * TM_PWT(T) * TM_DFACT(R,T) * LOG(VAR_C(R,T)))) =E= VAR_UTIL * MAX(1,LOG(TM_SCALE_UTIL*1000))/1000;
    E[("EQ_UTIL", ())] = @constraint(m, sum(val(NWT, r) * val(PWT, t) * val(DFACT, r, t) * log(var("VAR_C", r, t)) for r in MR for t in T)
                                         - var("VAR_UTIL") * max(1, log(sutil * 1000)) / 1000 == 0)
    for r in MR
        rho = val(RHO, r)
        for t in T
            # EQ_PROD_Y(MR(R),T).. VAR_C(R,T) + VAR_INV(R,T) + VAR_EC(R,T) + VAR_NTX(R,T)$PP(T) =E=
            #   (TM_AKL(R) * VAR_D(R,T,'AKL')**TM_RHO(R) + SUM(DM,TM_B(R,DM)*VAR_D(R,T,DM)**TM_RHO(R))) ** (1/TM_RHO(R));
            lhs = var("VAR_C", r, t) + var("VAR_INV", r, t) + var("VAR_EC", r, t) + (t in PP ? var("VAR_NTX", r, t) : 0.0)
            E[("EQ_PROD_Y", (r, t))] = @constraint(m, lhs - (val(AKL, r) * var("VAR_D", r, t, "AKL")^rho +
                                       sum(val(B, r, c) * var("VAR_D", r, t, c)^rho for c in DM))^(1 / rho) == 0)
            # EQ_AKL(MR(R),T).. VAR_D(R,T,'AKL') =E= (VAR_D(R,T,'KN')**(TM_KPVS(R))) * VAR_D(R,T,'LAB')**(1-TM_KPVS(R));
            kp = val(KPVS, r)
            E[("EQ_AKL", (r, t))] = @constraint(m, var("VAR_D", r, t, "AKL") - var("VAR_D", r, t, "KN")^kp * var("VAR_D", r, t, "LAB")^(1 - kp) == 0)
            # EQ_LABOR(MR(R),T).. VAR_D(R,T,'LAB') =E= TM_L(R,T);
            E[("EQ_LABOR", (r, t))] = @constraint(m, var("VAR_D", r, t, "LAB") == val(L, r, t))
            # EQ_KNCAP(MR(R),T).. VAR_D(R,T,'KN') =E= VAR_K(R,T);
            E[("EQ_KNCAP", (r, t))] = @constraint(m, var("VAR_D", r, t, "KN") - var("VAR_K", r, t) == 0)
        end
        for i in 1:length(T)-1
            # EQ_MCAP(MR(R),PP(T+1)).. VAR_K(R,PP) =E= VAR_K(R,T)*TM_TSRV(R,T) + (D(T+1)*VAR_INV(R,T+1)+TM_TSRV(R,T)*D(T)*VAR_INV(R,T))/2;
            t, t1 = T[i], T[i+1]
            E[("EQ_MCAP", (r, t1))] = @constraint(m, var("VAR_K", r, t1) - var("VAR_K", r, t) * val(TSRV, r, t) -
                (val(NYD, t1) * var("VAR_INV", r, t1) + val(TSRV, r, t) * val(NYD, t) * var("VAR_INV", r, t)) / 2 == 0)
        end
        # EQ_TMC(MR(R),TLAST(T)).. VAR_K(R,T) * (TM_GROWV(R,T) + TM_DEPR(R))/100 =L= VAR_INV(R,T);
        E[("EQ_TMC", (r, TLAST))] = @constraint(m, var("VAR_K", r, TLAST) * (val(GROWV, r, TLAST) + val(DEPR, r)) / 100 - var("VAR_INV", r, TLAST) <= 0)
        for t in PP
            # EQ_IVECBND(MR(R),PP(T)).. VAR_INV(R,T) + VAR_EC(R,T) =L= TM_Y0(R) * TM_L(R,T) ** TM_IVETOL(R);
            E[("EQ_IVECBND", (r, t))] = @constraint(m, var("VAR_INV", r, t) + var("VAR_EC", r, t) <= val(Y0, r) * val(L, r, t)^val(IVETOL, r))
            for c in DM
                # EQ_DD(MR(R),PP(T),C('ACT')).. VAR_DEM(R,T,C) =E= ((1/TM_SCALE_NRG) * (TM_AEEIFAC(R,T,C) * VAR_D(R,T,C) + VAR_SP(R,T,C)));
                E[("EQ_DD", (r, t, c))] = @constraint(m, var("VAR_DEM", r, t, c) -
                    (1 / nrg) * (val(AEEIFAC, r, t, c) * var("VAR_D", r, t, c) + var("VAR_SP", r, t, c)) == 0)
            end
            # EQ_ESCOST(MR(R),PP(T)).. SUM(DM('ACT'), TM_QSFA(R,T) + TM_QSFB(R,T,DM)*VAR_DEM(R,T,DM)**2) + TM_AMP(R,T) =E= VAR_EC(R,T)*TM_HDF(R,T);
            E[("EQ_ESCOST", (r, t))] = @constraint(m, sum(val(QSFB, r, t, c) * var("VAR_DEM", r, t, c)^2 for c in DM) -
                var("VAR_EC", r, t) * val(HDF, r, t) == -(sum(val(QSFA, r, t) for c in DM) + val(AMP, r, t)))
        end
    end
    for t in PP
        # EQ_TRDBAL(PP).. SUM(MR(R), VAR_NTX(R,PP)) =E= 0;
        E[("EQ_TRDBAL", (t,))] = @constraint(m, sum(var("VAR_NTX", r, t) for r in MR) == 0)
    end
    @objective(m, Max, var("VAR_UTIL"))
    optimize!(m)
    st = termination_status(m)
    st in (MOI.LOCALLY_SOLVED, MOI.OPTIMAL, MOI.ALMOST_LOCALLY_SOLVED) ||
        error("the calibration NLP (MCE) of MACRO for $(join(MR, ",")): Ipopt ended with $st")
    # the solution into the records: MERGE keeps the records of what is not in the model, REPLACE resets them
    if replace
        for v in VARS, k in collect(keys(S.l[v]))
            haskey(X, (v, k)) || delete!(S.l[v], k)
        end
        for v in VARS
            empty!(S.m[v])
        end
    end
    for ((v, k), x) in X
        S.l[v][k] = value(x)
        S.m[v][k] = reduced_cost(x)
    end
    for ((e, k), c) in E
        get!(D, S.m, e)[k] = -dual(c)
    end
    return (status = string(st), iterations = MOI.get(m, MOI.BarrierIterations()), utility = value(var("VAR_UTIL")), regions = MR)
end

# ------------------------------------------------------------------------------------------- ddfupd.msa
function ddfupd!(d::Data, S::State, MR, REG)
    T = d.order["T"]; T_1 = T[1]; PP = T[2:end]; TLAST = T[end]; DM = ("ACT",)
    p(n) = par(d, n)
    GOAL, GDP, PAR_Y, DEM, PAR_MC, ESUB, RHO, NYPER = p("TM_GDPGOAL"), p("TM_GDP"), p("PAR_Y"), p("TM_DEM"), p("PAR_MC"),
        p("TM_ESUB"), p("TM_RHO"), p("NYPER")
    # TM_DDF_Y(MR(R),T(T_1)) = 1;
    # TM_DDF_Y(MR(R),PP) = ((TM_GDPGOAL(R,PP)/TM_GDP(R,PP))**.7) * PAR_Y(R,PP)/SUM(T_1(T),PAR_Y(R,T));
    Y = p("TM_DDF_Y")
    for r in MR
        put!(Y, (r, T_1), 1.0)
        for t in PP
            put!(Y, (r, t), ((val(GOAL, r, t) / val(GDP, r, t))^0.7) * val(PAR_Y, r, t) / val(PAR_Y, r, T_1))
        end
    end
    # TM_DDF_DM(R,T,DM)$TM_DEM(R,T,DM) = 1;
    # LOOP(T_1(TT),TM_DDF_DM(R,T,DM)$TM_DEM(R,TT,DM) = TM_DEM(R,T,DM) / TM_DEM(R,TT,DM));
    # LOOP(T_1(TT),TM_DDF_SP(R,T,DM)$PAR_MC(R,TT,DM) = PAR_MC(R,T,DM) / PAR_MC(R,TT,DM));
    DDM, DSP = p("TM_DDF_DM"), p("TM_DDF_SP")
    for r in REG, t in T, c in DM
        val(DEM, r, t, c) != 0 && put!(DDM, (r, t, c), 1.0)
    end
    for r in REG, t in T, c in DM
        val(DEM, r, T_1, c) != 0 && put!(DDM, (r, t, c), val(DEM, r, t, c) / val(DEM, r, T_1, c))
    end
    for r in REG, t in T, c in DM
        val(PAR_MC, r, T_1, c) != 0 && put!(DSP, (r, t, c), val(PAR_MC, r, t, c) / val(PAR_MC, r, T_1, c))
    end
    # OPTION CLEAR=TM_DDF;
    # TM_F2(R,T,DM)$TM_DDF_SP(R,T,DM) = TM_DDF_DM(R,T,DM) / (TM_DDF_Y(R,T) * TM_DDF_SP(R,T,DM) ** (-TM_ESUB(R)));
    # TM_DDF(R,PP(T+1),DM)$TM_F2(R,T,DM) = 100 * (1 - (TM_F2(R,PP,DM)/TM_F2(R,T,DM))**((TM_RHO(R)-1)/(NYPER(T)*TM_RHO(R))));
    DDF, F2 = p("TM_DDF"), p("TM_F2")
    empty!(DDF)
    for r in REG, t in T, c in DM
        val(DSP, r, t, c) != 0 && put!(F2, (r, t, c), val(DDM, r, t, c) / (val(Y, r, t) * val(DSP, r, t, c)^(-val(ESUB, r))))
    end
    for r in REG, i in 1:length(T)-1, c in DM
        t, t1 = T[i], T[i+1]
        val(F2, r, t, c) != 0 || continue
        rho = val(RHO, r)
        put!(DDF, (r, t1, c), 100 * (1 - (val(F2, r, t1, c) / val(F2, r, t, c))^((rho - 1) / (val(NYPER, t) * rho))))
    end
    # TM_GROWV(R,T) = TM_GROWV(R,T) + (TM_GR(R,T) - PAR_GRGDP(R,T));  TM_GROWV(R,TLAST) = TM_GR(R,TLAST);
    GROWV, GR, GRGDP = p("TM_GROWV"), p("TM_GR"), p("PAR_GRGDP")
    for r in REG, t in T
        put!(GROWV, (r, t), val(GROWV, r, t) + (val(GR, r, t) - val(GRGDP, r, t)))
    end
    for r in REG
        put!(GROWV, (r, TLAST), val(GR, r, TLAST))
    end
    # TM_AEEIV(MR,T,DM) = TM_DDF(MR,T,DM) / 100;
    AEEIV = p("TM_AEEIV")
    for r in MR, t in T, c in DM
        put!(AEEIV, (r, t, c), val(DDF, r, t, c) / 100)
    end
    # TM_DFACTCURR(R,T) = 1 - (TM_KPVS(R)/TM_KGDP(R) - TM_DEPR(R)/100 - TM_GROWV(R,T)/100);
    # TM_IV0(R) = TM_K0(R) * (TM_DEPR(R) + SUM(T_1(T),TM_GROWV(R,T)))/100;  TM_C0(R) = TM_GDP0(R) - TM_IV0(R);
    DFC, KPVS, KGDP, DEPR, K0, IV0, C0, GDP0 = p("TM_DFACTCURR"), p("TM_KPVS"), p("TM_KGDP"), p("TM_DEPR"), p("TM_K0"),
        p("TM_IV0"), p("TM_C0"), p("TM_GDP0")
    for r in REG, t in T
        put!(DFC, (r, t), 1 - (val(KPVS, r) / val(KGDP, r) - val(DEPR, r) / 100 - val(GROWV, r, t) / 100))
    end
    for r in REG
        put!(IV0, (r,), val(K0, r) * (val(DEPR, r) + val(GROWV, r, T_1)) / 100)
        put!(C0, (r,), val(GDP0, r) - val(IV0, r))
    end
    # LOOP(PP(T+1),
    #   TM_AEEIFAC(MR,PP,DM) = TM_AEEIFAC(MR,T,DM) * (1 - TM_AEEIV(MR,PP,DM)) ** NYPER(T);
    #   TM_DFACT(R,PP)       = TM_DFACT(R,T) * TM_DFACTCURR(R,T) ** NYPER(T);
    #   TM_L(R,PP)           = TM_L(R,T) * (1+TM_GROWV(R,T)/100) ** NYPER(T));
    AEEIFAC, DFACT, L = p("TM_AEEIFAC"), p("TM_DFACT"), p("TM_L")
    for i in 1:length(T)-1
        t, t1 = T[i], T[i+1]
        for r in MR, c in DM
            put!(AEEIFAC, (r, t1, c), val(AEEIFAC, r, t, c) * (1 - val(AEEIV, r, t1, c))^val(NYPER, t))
        end
        for r in REG
            put!(DFACT, (r, t1), val(DFACT, r, t) * val(DFC, r, t)^val(NYPER, t))
            put!(L, (r, t1), val(L, r, t) * (1 + val(GROWV, r, t) / 100)^val(NYPER, t))
        end
    end
    # TM_DFACT(MR(R),TLAST)$(TM_ARBM NE 1) = TM_DFACT(R,TLAST) *
    #     (1-MIN(.999,TM_DFACTCURR(R,TLAST))**(NYPER(TLAST)*TM_ARBM)) / (1-MIN(.999,TM_DFACTCURR(R,TLAST))**(NYPER(TLAST) * 1 ));
    arbm = val(p("TM_ARBM"))
    if arbm != 1
        for r in MR
            b = min(0.999, val(DFC, r, TLAST))
            put!(DFACT, (r, TLAST), val(DFACT, r, TLAST) * (1 - b^(val(NYPER, TLAST) * arbm)) / (1 - b^(val(NYPER, TLAST) * 1)))
        end
    end
    # VAR_INV.FX(MR,T(T_1)) = TM_IV0(MR);
    for r in MR
        fx!(S, "VAR_INV", (r, T_1), val(IV0, r))
    end
end

# ------------------------------------------------------------------------------------------- calibase.mlf
smax(xs) = (v = -Inf; for x in xs; v = max(v, x); end; v)

function calibase!(d::Data, S::State, msgs::Vector{String})
    T = d.order["T"]; TB = T[1]; PP = T[2:end]; DM = ("ACT",)
    NITER, REG = d.order["NITER"], d.order["REG"]
    MR = [r for r in REG if haskey(par(d, "MR"), (r,))]
    p(n) = par(d, n)
    nrg, cst = val(p("TM_SCALE_NRG")), val(p("TM_SCALE_CST"))
    GOAL, GDP, PAR_Y, GROWV, GR, GRGDP, PAR_MC, DMC, DEM, NWT, HDF, NYPER, IVETOL, YCHECK = p("TM_GDPGOAL"), p("TM_GDP"),
        p("PAR_Y"), p("TM_GROWV"), p("TM_GR"), p("PAR_GRGDP"), p("PAR_MC"), p("TM_DMC"), p("TM_DEM"), p("TM_NWT"),
        p("TM_HDF"), p("NYPER"), p("TM_IVETOL"), p("TM_YCHECK")
    # TM_YCHECK(R) = TM_IVETOL(R);  TM_IVETOL(R) = MAX(1,TM_IVETOL(R));
    for r in REG
        put!(YCHECK, (r,), val(IVETOL, r))
        put!(IVETOL, (r,), max(1, val(IVETOL, r)))
    end
    # SET LOOPS / NWT, DDF, GDP /;  PARAMETER MSA_ERR(NITER,LOOPS,REG);
    # PARAMETER TM_TOL(ITEM) / CAL 1E-5, MST 1E-7, DEM 0, EQUIL 1 /;  SCALAR ERRDEM / 0 /, ERRGDP / 0 /, DOITER/ 1 /;
    for l in ("NWT", "DDF", "GDP")
        p("LOOPS")[(l,)] = 1.0
    end
    ERR, TOL = p("MSA_ERR"), p("TM_TOL")
    empty!(TOL); TOL[("CAL",)] = 1e-5; TOL[("MST",)] = 1e-7; TOL[("EQUIL",)] = 1.0
    errdem = errgdp = 0.0
    # TM_GDP(MR,T) = TM_GDPGOAL(MR,T);  PAR_Y(MR,T) = TM_GDPGOAL(MR,T);  TM_GROWV(R,T) = TM_GR(R,T);  PAR_GRGDP(R,T) = TM_GR(R,T);
    # PAR_MC(R,T,DM)$TM_DEM(R,T,DM) = TM_DMC(R,T,DM);  MREG(MR) = YES;  TM_NWT(MR) = 1;  TM_HDF(MR,T) = 1;  VAR_NTX.FX(MR,PP)=0;
    for r in MR, t in T
        put!(GDP, (r, t), val(GOAL, r, t)); put!(PAR_Y, (r, t), val(GOAL, r, t))
    end
    for r in REG, t in T
        put!(GROWV, (r, t), val(GR, r, t)); put!(GRGDP, (r, t), val(GR, r, t))
        for c in DM
            val(DEM, r, t, c) != 0 && put!(PAR_MC, (r, t, c), val(DMC, r, t, c))
        end
    end
    MREG = copy(MR)
    for r in MR
        p("MREG")[(r,)] = 1.0
        put!(NWT, (r,), 1.0)
        for t in T
            put!(HDF, (r, t), 1.0)
        end
        for t in PP
            fx!(S, "VAR_NTX", (r, t), 0.0)
        end
    end
    l(v, k...) = get(S.l[v], k, 0.0)
    mg(v, k...) = get(get(S.m, v, D()), k, 0.0)
    solve!(regs; replace = false) = (s = solve_mce!(d, S, regs; replace); push!(msgs, "# NLP MCE $(join(regs, ",")): $(s.status), $(s.iterations) iterations, utility $(s.utility)"); s)

    # DOITER=1$CARD(MR);
    # LOOP(NITER$DOITER, $INCLUDE ddfupd.msa
    #   IF(ORD(NITER)<5, LOOP(MREG, MR(R)= NO; MR(R(MREG))=YES; SOLVE MCE MAXIMIZING VAR_UTIL USING NLP); MR(R(MREG))=YES;
    #   ELSE SOLVE MCE MAXIMIZING VAR_UTIL USING NLP);
    doiter = !isempty(MR)
    for (n, niter) in enumerate(NITER)
        doiter || break
        ddfupd!(d, S, MR, REG)
        if n < 5
            for r in MREG
                solve!([r])
            end
        else
            solve!(MR)
        end
        # TM_GDP(R,T) = VAR_C.L(R,T) + VAR_INV.L(R,T);
        # PAR_GRGDP(MR(R),TP(T-1)) = 100 * ((TM_GDP(R,T)/TM_GDP(R,TP))**(1/NYPER(TP))-1);
        # PAR_Y(R,T) = VAR_C.L(R,T) + VAR_INV.L(R,T) + VAR_EC.L(R,T) + VAR_NTX.L(R,T)$(NOT TB(T));
        # PAR_MC(MR(R),PP(T),DM(C)) = MAX(ABS(VAR_SP.M(R,T,C)*TM_SCALE_NRG),ABS(EQ_DD.M(R,T,C))) / MAX(EQ_ESCOST.M(R,T),-VAR_EC.M(R,T)) / TM_SCALE_CST;
        for r in REG, t in T
            put!(GDP, (r, t), l("VAR_C", r, t) + l("VAR_INV", r, t))
        end
        for r in MR, i in 2:length(T)
            put!(GRGDP, (r, T[i-1]), 100 * ((val(GDP, r, T[i]) / val(GDP, r, T[i-1]))^(1 / val(NYPER, T[i-1])) - 1))
        end
        for r in REG, t in T
            put!(PAR_Y, (r, t), l("VAR_C", r, t) + l("VAR_INV", r, t) + l("VAR_EC", r, t) + (t == TB ? 0.0 : l("VAR_NTX", r, t)))
        end
        for r in MR, t in PP, c in DM
            put!(PAR_MC, (r, t, c), max(abs(mg("VAR_SP", r, t, c) * nrg), abs(mg("EQ_DD", r, t, c))) / max(mg("EQ_ESCOST", r, t), -mg("VAR_EC", r, t)) / cst)
        end
        # MSA_ERR(NITER,'DDF',MR(R)) = SMAX((T,DM(C)),ABS(TM_DEM(R,T,C)-VAR_DEM.L(R,T,C))/TM_DEM(R,T,C));
        # MSA_ERR(NITER,'GDP',MR(R)) = SMAX(T,ABS(TM_GDPGOAL(R,T)-TM_GDP(R,T))/TM_GDPGOAL(R,T));
        # ERRDEM = SMAX(MR, MSA_ERR(NITER,'DDF',MR));  ERRGDP = SMAX(MR, MSA_ERR(NITER,'GDP',MR));
        # IF(MAX(ERRDEM,ERRGDP) < TM_TOL('CAL')*ORD(NITER), DOITER=0);
        for r in MR
            put!(ERR, (niter, "DDF", r), smax(abs(val(DEM, r, t, c) - l("VAR_DEM", r, t, c)) / val(DEM, r, t, c) for t in T for c in DM))
            put!(ERR, (niter, "GDP", r), smax(abs(val(GOAL, r, t) - val(GDP, r, t)) / val(GOAL, r, t) for t in T))
        end
        errdem = smax(val(ERR, niter, "DDF", r) for r in MR)
        errgdp = smax(val(ERR, niter, "GDP", r) for r in MR)
        push!(msgs, "# calibration iteration $niter: MSA_ERR DDF $errdem, GDP $errgdp")
        max(errdem, errgdp) < val(TOL, "CAL") * n && (doiter = false)
    end
    # TM_TOL('DEM') = ERRDEM/300;  TM_TOL('GDP') = ERRGDP/300;
    put!(TOL, ("DEM",), errdem / 300); put!(TOL, ("GDP",), errgdp / 300)
    # VAR_NTX.UP(MR,PP) = INF;  VAR_NTX.LO(MR,PP) =-INF;  OPTION CLEAR=MSA_ERR;
    for r in MR, t in PP
        S.lo["VAR_NTX"][(r, t)] = -Inf; S.up["VAR_NTX"][(r, t)] = Inf
    end
    empty!(ERR)
    # TM_NWT(MR(R)) = SUM(TP, TM_GDPGOAL(R,TP)*TM_DFACT(R,TP));  Z = SUM(MR(R),TM_NWT(R));  TM_NWT(MR(R)) = TM_NWT(R) / Z;
    DFACT, UDF, PVT, NWTIT = p("TM_DFACT"), p("TM_UDF"), p("COEF_PVT"), p("TM_NWTIT")
    for r in MR
        put!(NWT, (r,), sum(val(GOAL, r, t) * val(DFACT, r, t) for t in T))
    end
    z = sum(val(NWT, r) for r in MR; init = 0.0)
    for r in MR
        put!(NWT, (r,), val(NWT, r) / z)
    end
    usehdf = round(val(p("TM_DEFVAL"), "USEHDF"), RoundNearestTiesAway)
    doiter = !isempty(MR)
    for (n, niter) in enumerate(NITER)
        doiter || break
        # OPTION BRATIO=0.25,SOLVEOPT=REPLACE;  SOLVE MCE MAXIMIZING VAR_UTIL USING NLP;
        solve!(MR; replace = true)
        # TM_GDP(MR(R),PP) = VAR_C.L(R,PP)+VAR_INV.L(R,PP) + VAR_NTX.L(R,PP);
        # PAR_GRGDP(MR(R),tp(T-1)) = 100 * ((TM_GDP(R,T)/TM_GDP(R,TP))**(1/NYPER(TP))-1);
        # PAR_Y(R,T) = VAR_C.L(R,T) + VAR_INV.L(R,T) + VAR_EC.L(R,T) + VAR_NTX.L(R,T)$(NOT TB(T));
        # PAR_MC(MR(R),PP(T),DM(C)) = MAX(ABS(VAR_SP.M(R,T,C)*TM_SCALE_NRG),ABS(EQ_DD.M(R,T,C))) / MAX(EQ_ESCOST.M(R,T),-VAR_EC.M(R,T)) / TM_SCALE_CST / tm_hdf(r,t);
        for r in MR, t in PP
            put!(GDP, (r, t), l("VAR_C", r, t) + l("VAR_INV", r, t) + l("VAR_NTX", r, t))
        end
        for r in MR, i in 2:length(T)
            put!(GRGDP, (r, T[i-1]), 100 * ((val(GDP, r, T[i]) / val(GDP, r, T[i-1]))^(1 / val(NYPER, T[i-1])) - 1))
        end
        for r in REG, t in T
            put!(PAR_Y, (r, t), l("VAR_C", r, t) + l("VAR_INV", r, t) + l("VAR_EC", r, t) + (t == TB ? 0.0 : l("VAR_NTX", r, t)))
        end
        for r in MR, t in PP, c in DM
            put!(PAR_MC, (r, t, c), max(abs(mg("VAR_SP", r, t, c) * nrg), abs(mg("EQ_DD", r, t, c))) / max(mg("EQ_ESCOST", r, t), -mg("VAR_EC", r, t)) / cst / val(HDF, r, t))
        end
        # MSA_ERR(NITER,'DDF',MR(R)) = SMAX((T(TT+1),DM(C)),ABS(TM_DEM(R,T,C)-VAR_DEM.L(R,T,C))/TM_DEM(R,T,C));
        # MSA_ERR(NITER,'GDP',MR(R)) = SMAX(T,ABS(TM_GDPGOAL(R,T)-TM_GDP(R,T))/TM_GDPGOAL(R,T));
        for r in MR
            put!(ERR, (niter, "DDF", r), smax(abs(val(DEM, r, t, c) - l("VAR_DEM", r, t, c)) / val(DEM, r, t, c) for t in PP for c in DM))
            put!(ERR, (niter, "GDP", r), smax(abs(val(GOAL, r, t) - val(GDP, r, t)) / val(GOAL, r, t) for t in T))
        end
        # ERRDEM = SMAX(MR, MSA_ERR(NITER,'DDF',MR));  ERRGDP = SMAX(MR, MSA_ERR(NITER,'GDP',MR));
        # DFUNC = ((ERRGDP>1.5*TM_TOL('GDP'))+(ERRDEM>1.5*TM_TOL('DEM')))*(MAX(ERRDEM,ERRGDP)>TM_TOL('MST'));
        errdem = smax(val(ERR, niter, "DDF", r) for r in MR)
        errgdp = smax(val(ERR, niter, "GDP", r) for r in MR)
        dfunc = ((errgdp > 1.5 * val(TOL, "GDP")) + (errdem > 1.5 * val(TOL, "DEM"))) * (max(errdem, errgdp) > val(TOL, "MST"))
        # LOOP(TB(T-1), MY_ARRAY(PP) = ABS(EQ_TRDBAL.M(PP)/EQ_TRDBAL.M(T)));
        # TM_NWT(MR(R)) = SUM(PP, MY_ARRAY(PP)*VAR_C.L(R,PP) + MY_ARRAY(PP)*VAR_NTX.L(R,PP));
        # TM_NWT(MR) = TM_NWT(MR) / SUM(REG, TM_NWT(REG));  TM_NWTIT(NITER,MR) = TM_NWT(MR);
        my = Dict(t => abs(mg("EQ_TRDBAL", t) / mg("EQ_TRDBAL", T[2])) for t in PP)
        for r in MR
            put!(NWT, (r,), sum(my[t] * l("VAR_C", r, t) + my[t] * l("VAR_NTX", r, t) for t in PP))
        end
        z = sum(val(NWT, r) for r in REG)
        for r in MR
            put!(NWT, (r,), val(NWT, r) / z)
            put!(NWTIT, (niter, r), val(NWT, r))
        end
        # IF(CARD(MR)=1, TM_TOL('EQUIL')=0; ELSE TM_TOL('EQUIL') = SUM(MR, ABS(TM_NWTIT(NITER-1,MR) - TM_NWT(MR))));
        # MSA_ERR(NITER,'NWT',MR) = TM_TOL('EQUIL');  IF(DFUNC, TM_TOL('EQUIL')=1);
        # IF(TM_TOL('EQUIL') LE TM_TOL('MST') OR ORD(NITER)=CARD(NITER), DOITER=0);
        prev = n > 1 ? NITER[n-1] : ""
        put!(TOL, ("EQUIL",), length(MR) == 1 ? 0.0 : sum(abs(val(NWTIT, prev, r) - val(NWT, r)) for r in MR))
        for r in MR
            put!(ERR, (niter, "NWT", r), val(TOL, "EQUIL"))
        end
        dfunc != 0 && put!(TOL, ("EQUIL",), 1.0)
        push!(msgs, "# Negishi iteration $niter: MSA_ERR DDF $errdem, GDP $errgdp, NWT $(val(ERR, niter, "NWT", MR[1]))")
        (val(TOL, "EQUIL") <= val(TOL, "MST") || n == length(NITER)) && (doiter = false)
        if doiter
            # TM_UDF(R,T)=TM_HDF(R,T); TM_HDF(R,T)=COEF_PVT(R,T);
            # LOOP(PP(T-1),TM_HDF(MR(R),T) = TM_HDF(R,PP)*EQ_ESCOST.M(R,T)/EQ_ESCOST.M(R,PP));
            # Z=ROUND(TM_DEFVAL('USEHDF'));  TM_HDF(R,T)=TM_UDF(R,T)*(TM_HDF(R,T)/COEF_PVT(R,T))**.5$Z;
            for r in REG, t in T
                put!(UDF, (r, t), val(HDF, r, t)); put!(HDF, (r, t), val(PVT, r, t))
            end
            for i in 3:length(T), r in MR
                t, t0 = T[i], T[i-1]
                put!(HDF, (r, t), val(HDF, r, t0) * mg("EQ_ESCOST", r, t) / mg("EQ_ESCOST", r, t0))
            end
            for r in REG, t in T
                put!(HDF, (r, t), val(UDF, r, t) * (val(HDF, r, t) / val(PVT, r, t))^(usehdf != 0 ? 0.5 : 0.0))
            end
            # $INCLUDE ddfupd.msa;  TM_DFACT(R,PP) = TM_DFACT(R,PP)/TM_HDF(R,PP)
            ddfupd!(d, S, MR, REG)
            for r in REG, t in PP
                # TIMES stops here on a region without MACRO data (its TM_HDF is 0): "division by zero"
                val(HDF, r, t) == 0 && error("TIMES STOPS: calibase.mlf, TM_DFACT(R,PP) = TM_DFACT(R,PP)/TM_HDF(R,PP): division by zero " *
                    "for the region $r, which has no MACRO data (TM_HDF is 0): TIMES ends this run with an execution error")
                put!(DFACT, (r, t), val(DFACT, r, t) / val(HDF, r, t))
            end
        end
    end
    # GDPLOSS(MR,TP)= 100*(TM_GDPGOAL(MR,TP)-TM_GDP(MR,TP))/TM_GDPGOAL(MR,TP);
    # TM_DDF_DM(MR,TP,DM)=(VAR_DEM.L(MR,TP,DM)/TM_DEM(MR,TP,DM));
    LOSS, DDM = p("GDPLOSS"), p("TM_DDF_DM")
    for r in MR, t in T
        put!(LOSS, (r, t), 100 * (val(GOAL, r, t) - val(GDP, r, t)) / val(GOAL, r, t))
        for c in DM
            put!(DDM, (r, t, c), l("VAR_DEM", r, t, c) / val(DEM, r, t, c))
        end
    end
    # TM_IVETOL(MR(R)) = MAX(TM_YCHECK(R),SMAX(PP$(TM_L(R,PP)>1),LOG((VAR_INV.L(R,PP)+VAR_EC.L(R,PP))/TM_Y0(R))/LOG(TM_L(R,PP)))+.005);
    L, Y0 = p("TM_L"), p("TM_Y0")
    for r in MR
        put!(IVETOL, (r,), max(val(YCHECK, r), smax(log((l("VAR_INV", r, t) + l("VAR_EC", r, t)) / val(Y0, r)) / log(val(L, r, t))
                                                        for t in PP if val(L, r, t) > 1) + 0.005))
    end
    p("ERRDEM")[()] = errdem; p("ERRGDP")[()] = errgdp; p("DOITER")[()] = Float64(doiter)
end

# ------------------------------------------------------------------------------------------- main
const OUT = ("TM_YCHECK", "TM_IVETOL", "TM_GDP", "PAR_Y", "TM_GROWV", "PAR_GRGDP", "PAR_MC", "MREG", "TM_NWT", "TM_HDF",
             "TM_UDF", "TM_DDF_Y", "TM_DDF_DM", "TM_DDF_SP", "TM_DDF", "TM_F2", "TM_AEEIV", "TM_DFACTCURR", "TM_IV0", "TM_C0",
             "TM_AEEIFAC", "TM_DFACT", "TM_L", "TM_NWTIT", "GDPLOSS", "MSA_ERR", "TM_TOL", "ERRDEM", "ERRGDP", "DOITER", "LOOPS")

function main(args)
    d = read_in(args[1])
    S = State(Dict(v => D() for v in VARS), Dict(v => D() for v in VARS), Dict(v => D() for v in VARS), Dict(v => D() for v in VARS))
    for (n, P) in d.p
        for (pre, field) in (("L:", S.l), ("LO:", S.lo), ("UP:", S.up))
            startswith(n, pre) && (field[n[length(pre)+1:end]] = P)
        end
    end
    msgs = String[]
    t = @elapsed calibase!(d, S, msgs)
    open(args[2], "w") do io
        for line in msgs
            println(io, line)
        end
        println(io, "# calibration: $(round(t; digits = 1)) s; Ipopt ", pkgversion(Ipopt), ", options ", join(("$k=$v" for (k, v) in IPOPT_OPTIONS), " "))
        rec(name, k, x) = println(io, join((name, k..., repr(x)), '\t'))
        for n in OUT, (k, x) in sort!(collect(par(d, n)))
            rec(n, k, x)
        end
        for v in VARS, (k, x) in sort!(collect(S.l[v]))
            rec("L:" * v, k, x)
        end
        for (v, P) in S.m, (k, x) in sort!(collect(P))
            rec("M:" * v, k, x)
        end
    end
end
