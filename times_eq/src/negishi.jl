# SPDX-License-Identifier: GPL-3.0-or-later
"""
    negishi!(d, m, solve!) -> (m, iterations)                                           rpt_ext.mlf 14-48

TIMES-MACRO MLF after its LP is solved: the Negishi iterations. The weights of the regions in the utility are set from
the solution, and the LP is solved again with them while they move:

    LOOP(NITER\$DOITER,
      TM_NWTIT(NITER,MR) = TM_NWT(MR);
      MY_ARRAY(PP) = ABS(EQ_TRDBAL.M(PP));
      TM_NWT(MR(R)) = SUM(PP, MY_ARRAY(PP)*(VAR_C.L(R,PP)+VAR_NTX.L(R,PP)));
      Z = SUM(MR(R), TM_NWT(R));  IF(Z>0, TM_NWT(MR) = TM_NWT(MR) / Z);
      IF(CARD(MR)=1, Z=0; ELSE Z = SUM(MR, ABS(TM_NWTIT(NITER,MR)-TM_NWT(MR))));
      F=TM_DEFVAL('NEGTOL'); IF(ORD(NITER)=1, F=F*(1+LOG(10**.1)) ELSE F=ABS(F));
      RB(MR(R),T)=TM_TAXREV(R,T);  TM_TAXREV(MR(R),PP(T)) = REG_ACOST(R,T,'INVX')+REG_ACOST(R,T,'FIXX')+REG_ACOST(R,T,'VARX');
      DFUNC = SMAX(MR(R),TM_SCALE_CST*SUM(PP(T),COEF_PVT(R,T)*ABS(TM_TAXREV(R,T)-RB(R,T)))/SUM(PP(T),COEF_PVT(R,T)*VAR_EC.L(R,T)*TM_HDF(R,T)));
      DOITER=(MAX(Z,DFUNC)>=F+MIN(0,DOITER));
      IF(DOITER, SOLVE %MODEL_NAME% MAXIMIZING VAR_UTIL USING LP));

with DOITER = 1 at the start (`DOITER=1-INF\$(DOITER=NA)`). The rebate of tax revenues (TM_TAXREV, DFUNC) needs the
annual taxes of the solution; a model with taxes or subsidies in its objective stops in the preprocessor, so here
TM_TAXREV stays 0 and DFUNC is 0. A new solve builds the model again with the new weights (`solve!(m)` solves a built
model; the last model and the iterations are returned, each as (z, f, dfunc, doiter, weights)).
"""
function negishi!(d::Data, m::Model, solve!::Function)
    isempty(d.tables.MLF) && return m, NamedTuple[]
    (; MR, PP, NITER, TM_NWT, TM_DEFVAL) = d.tables
    (; VAR_C, VAR_NTX) = m.v
    negtol = id!(d.L, "NEGTOL")
    its = NamedTuple[]
    doiter = 1.0
    for n in 1:length(NITER)
        doiter == 0 && break
        if length(MR) - min(0, doiter) == 0
            doiter = 0.0
            break
        end
        old = Dict(r => TM_NWT(r) for r in MR)
        trd = Dict(t => abs(row_marginal(m, :EQ_TRDBAL, (t,))) for t in PP)
        lev(v, k...) = haskey(v.x, k) ? JuMP.value(v.x[k]) : 0.0
        new = Dict(r => sum(trd[t] * (lev(VAR_C, r, t) + lev(VAR_NTX, r, t)) for t in PP; init = 0.0) for r in MR)
        z = sum(values(new); init = 0.0)
        z > 0 && (new = Dict(r => x / z for (r, x) in new))
        for r in MR
            TM_NWT.d[(r,)] = new[r]
        end
        z = length(MR) == 1 ? 0.0 : sum(abs(old[r] - new[r]) for r in MR)
        f = TM_DEFVAL(negtol)
        f = n == 1 ? f * (1 + log(10^0.1)) : abs(f)
        dfunc = 0.0
        doiter = Float64(max(z, dfunc) >= f + min(0, doiter))
        push!(its, (iteration = n, gap = z, tolerance = f, tax_gap = dfunc, solve_again = doiter != 0,
                    weights = Dict(label(d.L, r) => new[r] for r in MR)))
        if doiter != 0
            m = build(d)
            solve!(m)
            (; VAR_C, VAR_NTX) = m.v
        end
    end
    return m, its
end

"""GAMS's marginal of a row of the solved model (the change of the objective per unit of its right-hand side)."""
function row_marginal(m::Model, name::Symbol, key::Tuple)
    r = m.rows[name]
    i = findfirst(==(key), r.keys)
    i === nothing && return 0.0
    sgn = JuMP.objective_sense(m.jump) == JuMP.MAX_SENSE ? -1.0 : 1.0
    return sgn * JuMP.dual(r.refs[i])
end
