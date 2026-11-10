# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQE_UCRT(r,t,uc), EQE_UCRTS(r,t,uc,s), EQE_UCT(uc,t), EQE_UCTS(uc,t,s)      equcwrap.mod, equserco.mod, uc_*.mod
    EQE_UCRSU(r,t,uc), EQE_UCRSUS(r,t,uc,s), EQE_UCSU(uc,t), EQE_UCSUS(uc,t,s)   the same, between successive periods
    EQE_UCRS(r,t,uc,tsl,s)                                                      written for every timeslice of level tsl

User constraints by period. The row defines the left-hand side as a variable; the right-hand
side of the constraint (UC_RHSRT, UC_RHSRTS, UC_RHST, UC_RHSTS) is the bound on that variable.

    SUM(flows, UC_FLO * flow) + SUM(trade, UC_IRE * trade) + SUM(c, UC_COM * VAR_COMPRD / VAR_COMNET)
        + SUM(p, UC_CAP * VAR_CAP(r,t,p)) + SUM(p, UC_NCAP * VAR_NCAP(r,t,p))
        + SUM((p,v,ts), UC_ACT * VAR_ACT(r,v,t,p,ts))   =  VAR_UCRT(uc,r,t)

EQE_UC (UC_RHS) and EQE_UCR (UC_RHSR) sum the periods too, and add the cumulative commodity and flow terms once:
SUM(UC_CUMCOM * VAR_CUMCOM * CUCSCAL) + SUM(UC_CUMFLO * VAR_CUMFLO * CUFSCAL).

EQE_UCRT sums the timeslices selected for the constraint; EQE_UCRTS is written per timeslice;
EQE_UCT and EQE_UCTS do the same with the regions selected (UC_R_SUM) summed.

A dynamic constraint (UC_T_SUCC) relates period t to the next period tt: the terms given for the
left-hand side are taken in t, those given for the right-hand side in tt, with the opposite sign:

    terms(LHS, t)  -  terms(RHS, tt)   =  VAR_UCRT(uc,r,t)   or   VAR_UCRTS(uc,r,t,s)

With the GROWTH attribute on a group of terms, their coefficient is a growth factor per year and
is raised to the number of years between the two periods (see `uc_terms`).

In a constraint written for every timeslice of a level (EQE_UCRS) the flows, activities and commodity
quantities are divided by the year fraction of the timeslice: the constraint compares rates, and a
capacity term can stand next to them.
"""
function eq_userco!(m::Model)
    uc_supported(m)
    uc_rhsmap!(m, exprtype(), m.d.UC_RHSMAP)
    uc_rest!(m, exprtype())
end

"""
eq_userco! in pieces (`PIECES`): the loop over UC_RHSMAP in about `n - 1` contiguous blocks (one entry's row depends on
no other entry), the first with the checks of the input; then the loops after it, EQE_UC to EQE_UCSUS, as one piece.
Committed one after another, the pieces' rows are the family's rows in its order.
"""
function userco_pieces(m::Model, n::Int)
    rows = m.d.UC_RHSMAP.rows
    ps = Function[rm -> (j == 1 && uc_supported(rm); uc_rhsmap!(rm, exprtype(), b)) for (j, b) in enumerate(blocks(rows, n - 1))]
    return push!(ps, rm -> uc_rest!(rm, exprtype()))
end

# UC_MAPCOST (initsys.mod lines 134-139): the attribute names mapped onto the cost attributes COST, DELIV, TAX, SUB, ANNUL
const UC_MAPPED = ("FLO_COST", "NCAP_COST", "FLO_DELIV", "INVCOST", "INVTAX", "INVSUB", "FLO_TAX", "NCAP_ITAX", "FLO_SUB", "NCAP_ISUB")

"""
    costsum(xs)

The sum of the costs of a user-constraint term as GAMS has it: a cost that is EPS (a cost given as 0 under \$ONEPS, or
interpolated as EPS before its first value) stays EPS when nothing nonzero comes with it (EPS+0, MIN(0,EPS) and
MAX(0,EPS) are EPS in GAMS), so the term keeps an EPS entry in the row; a nonzero cost beside it gives that value
(x + EPS is x). Not exactly GAMS's order: GAMS sums term by term, so nonzero costs that cancel to exactly 0 after an
EPS give 0 there, and EPS here.
"""
function costsum(xs)
    f, eps = 0.0, false
    for x in xs
        iseps(x) ? (eps = true) : (f += x)
    end
    iszero(f) && eps ? EPS : f
end

"""The user-constraint input the equations do not support yet: an error that names it."""
function uc_supported(m::Model)
    (; UC_ATTR) = m.d
    (; LHS, GROWTH, NCAP, PERIOD, SYNC, N, BUILDUP, NET, COMPRD, COMNET, COMCON, NEWFLO) = m.K
    other = Dict{String,Vector{String}}()             # attribute on group => constraints that use it
    for (r, uc, side, grp, name) in UC_ATTR
        # the climate terms (uc_cli.mod): GROWTH and PERIOD (see `uc_cli_terms`); YES (init_ext.vda 129: they make the
        # constraint dynamic on the right-hand side). The dynamic attributes (N, SYNC, CUMSUM, CUM+) are not taken on them.
        if label(m.L, grp) == "CLI"
            label(m.L, name) in ("GROWTH", "PERIOD", "YES") && continue
            ucs = get!(other, "$(label(m.L, name)) on CLI", String[])
            label(m.L, uc) in ucs || push!(ucs, label(m.L, uc))
            continue
        end
        (name == GROWTH || ((name == PERIOD || name == BUILDUP) && grp == NCAP) || name == SYNC || name == N) && continue
        # the dynamic attributes (UC_DYNT: N, CUMSUM, CUM+, SYNC; equserco.mod line 83, eqmain.mod 211-215): see `uc_dynamic`;
        # CAPFLO on FLO (uc_flo.mod lines 50-64): see `uc_terms`; YES, in UC_NAME, is read by no equation
        (name == m.K.CUMSUM || label(m.L, name) in ("CUM+", "CAPFLO", "YES")) && continue
        # a timeslice level (init_ext.vda line 130: UC_TSL) left in UC_ATTR by a constraint with UC_T_SUCC (ppmain.mod
        # 1108 drops its UC_TSL, line 1113 removes the name only for R_UC): read by no equation
        label(m.L, name) in ("ANNUAL", "SEASON", "WEEKLY", "DAYNITE") && continue
        # PERIOD and NEWFLO on flows, trade and activity (UC_PERDS of uc_flo.mod / uc_ire.mod / uc_act.mod), PERIOD on the
        # commodity groups (uc_com.mod line 35): see `uc_terms`. TIMES reads them on no other group (uc_cap.mod has
        # neither; ppmain.mod line 1154 drops PERIOD from cumulative constraints but on NCAP)
        (name == PERIOD || name == NEWFLO) && continue
        # EFF on the commodity groups (uc_com.mod line 28), PERDISC in cumulative constraints (uc_flo.mod line 22,
        # uc_ire.mod 21, uc_act.mod 22, uc_com.mod 25): see `uc_terms`; on other groups TIMES does not read them
        (name == m.K.EFF || name == m.K.PERDISC) && continue
        # ONLINE on CAP in a constraint by timeslice (uc_cap.mod lines 36-43): see `uc_terms`; TIMES reads it nowhere else
        name == m.K.ONLINE && continue
        # the cost attributes on flows, trade, activity and commodities (uc_flo.mod lines 41-46, uc_ire.mod 41-46,
        # uc_act.mod 43, uc_com.mod 37-39): see `uc_terms`; uc_cap.mod has none, and on activity only COST is read
        (grp != NCAP && (name == m.K.COST || name == m.K.TAX || name == m.K.SUB || name == m.K.DELIV || name == m.K.ANNUL ||
                         label(m.L, name) in UC_MAPPED)) && continue
        # NET on a commodity group is settled in the preprocessor (which UC_COM entries exist); nothing in the equations
        (name == NET && (grp == COMPRD || grp == COMNET || grp == COMCON)) && continue
        # CAPACT on CAP: the capacity term multiplied by PRC_CAPACT (see `uc_terms`)
        (name == m.K.CAPACT && grp == m.K.CAP) && continue
        # INVCOST / ANNUL / CUMSUM on NCAP: annual investment payments, cumulated over the periods (see `uc_terms`)
        ((name == m.K.INVCOST || name == m.K.ANNUL || name == m.K.CUMSUM) && grp == NCAP) && continue
        # COST / TAX / SUB / DELIV on NCAP (the UC_COST attributes of uc_ncap.mod lines 37-42; DELIV has no NCAP term, so
        # it only joins the sum, adding nothing): investment cost, tax and subsidy of the period (see `uc_terms`); the names
        # they are mapped from (UC_MAPCOST, ppmain.mod line 1156) stay in UC_ATTR and have no term of their own
        (grp == NCAP && (name == m.K.COST || name == m.K.TAX || name == m.K.SUB || name == m.K.DELIV ||
                         label(m.L, name) in UC_MAPPED)) && continue
        ucs = get!(other, "$(label(m.L, name)) on $(label(m.L, grp))", String[])
        label(m.L, uc) in ucs || push!(ucs, label(m.L, uc))
    end
    isempty(other) || error("TIMES feature not supported yet: user-constraint attributes " *
        join(("$k ($(length(v)) constraint$(length(v) == 1 ? "" : "s"), e.g. $(v[1]))" for (k, v) in sort!(collect(other); by = first)), "; "))
    # climate terms (uc_cli.mod) are added to the dynamic constraints between periods only (`uc_dynamic`); a constraint
    # written for every timeslice of a level (UC_DS: EQE_UCRS, `uc_tslevel`) does not take them yet
    cli = Set((r, uc) for (r, uc, side, grp, name) in UC_ATTR if label(m.L, grp) == "CLI")
    for (r, uc, tsl) in m.d.UC_DS
        (r, uc) in cli && error("TIMES feature not supported yet: climate terms (UC_CLI) in a user constraint on a " *
                                "timeslice level ($(label(m.L, uc)), $(label(m.L, tsl)))")
    end
end

# UC_TIME on the right-hand side of the non-dynamic constraints (equserco.mod line 117, %8 = 0 or 2):
#   + SUM((%7V(T))$UC_TIME(UC_N,R,T), %5 UC_TIME(UC_N,R,T)*FPD(T))      FPD = D; taken to the left with a minus;
# per region and period as the constraint sums them (a timeslice row takes the whole annual amount)
uctime(m::Model, uc, r, t) = (has(m.d.UC_TIME, uc, r, t) && !(t in m.fwd)) ? plain(m.d.UC_TIME(uc, r, t)) * plain(m.d.D(t)) : 0.0
with_time(e, k) = (iszero(k) || add!(e, -k, 1.0); e)

"""The rows of the loop over UC_RHSMAP (EQE_UCRT, EQE_UCRTS, EQE_UCRSU, EQE_UCRSUS, EQE_UCRS) for the entries `rhsmap`."""
function uc_rhsmap!(m::Model, ::Type{E}, rhsmap) where {E}
    (; UC_DS) = m.d
    (; uc_ts_sum) = m.ix
    (; VAR_UCRT, VAR_UCRTS) = m.v
    (; SEVERAL, EACH, SUCC, DYNAMIC, ANNUAL) = m.K

    for (r, t, uc, scope, s) in rhsmap
        if scope == SEVERAL && s == ANNUAL
            row!(m, :EQE_UCRT, (r, t, uc), with_time(uc_terms(E, m, uc, r, t, uc_ts_sum[r, uc]), uctime(m, uc, r, t)), ==, VAR_UCRT(uc, r, t))
        elseif scope == EACH
            row!(m, :EQE_UCRTS, (r, t, uc, s), with_time(uc_terms(E, m, uc, r, t, (s,)), uctime(m, uc, r, t)), ==, VAR_UCRTS(uc, r, t, s))
        elseif scope == DYNAMIC && s == ANNUAL
            # a step of a myopic run: RSU(UC_RTSUC(R,T,UC_N))$UC_RHSMAP(..), with UC_RTSUC of the step
            (m.stepped && !((r, t, uc) in m.d.UC_RTSUC)) && continue
            sow_ucsucc(m, uc, t) || continue
            row!(m, :EQE_UCRSU, (r, t, uc), uc_dynamic(E, m, uc, r, t, uc_ts_sum[r, uc]), ==, sow_own(m, VAR_UCRT, uc, r, t))
        elseif scope == SUCC
            (m.stepped && !((r, t, uc) in m.d.UC_RTSUC)) && continue
            sow_ucsucc(m, uc, t) || continue
            row!(m, :EQE_UCRSUS, (r, t, uc, s), uc_dynamic(E, m, uc, r, t, (s,)), ==, sow_own(m, VAR_UCRTS, uc, r, t, s))
        elseif (r, uc, scope) in UC_DS
            # written for every timeslice of the level `scope` (UC_ATTR with a level name)
            row!(m, :EQE_UCRS, (r, t, uc, scope, s), uc_tslevel(E, m, uc, r, t, scope, s), ==, VAR_UCRTS(uc, r, t, s))
        else
            error("TIMES feature not supported yet: user constraint $(label(m.L, uc)) of type $(label(m.L, scope))")
        end
    end
end

"""
The left-hand side of EQE_UCRS(r,t,uc,tsl,s), a constraint written for every timeslice s of the level tsl
(equcwrap.mod, the last call of equserco.mod, with the terms summed as)

    SUM((UC_TSL(R,UC_N,SIDE,TSL),G_UDS(SL,SIDE,S))\$(RHS(SIDE)->RS_PREV(R,SL,S)),UC_SIGN(SIDE)* terms(SIDE,S))

The terms given for the left-hand side are taken in s. When the constraint has the level on its right-hand side too
(UC_TSL(r,uc,'RHS',tsl): a level name on the RHS in UC_ATTR, or a constraint dynamic on the RHS made a timeslice
constraint, ppmain.mod 1171), it is timeslice-dynamic: the terms given for the right-hand side are taken in the
timeslice before s in the cycle of its parent (RS_PREV), with the opposite sign:

    terms(LHS, s) / G_YRFR(s)  -  terms(RHS, s-1) / G_YRFR(s-1)   =  VAR_UCRTS(uc,r,t,s)

(the flows, activities, trade and commodities per unit of time of their own timeslice, the capacity terms as they
are). UC_TIME is summed the same way (equserco.mod line 117, %5 being the same SUM): + UC_TIME*D(t) for the left-hand
side, - UC_TIME*D(t) for the right, nothing when both are there.
"""
function uc_tslevel(::Type{E}, m::Model, uc, r, t, tsl, s) where {E}
    RHS = m.K.RHS
    e = uc_terms(E, m, uc, r, t, (s,); per_hour = true)
    k = uctime(m, uc, r, t)
    if (r, uc, RHS, tsl) in m.d.UC_TSL
        # G_UDS(SL,'RHS',S) is RS_PREV in the regions with a timeslice-dynamic constraint (ppmain.mod 1179), so the
        # condition is RS_PREV(R,SL,S)
        for ps in m.ix.ts_prev[r, s]
            add!(e, -1.0, uc_terms(E, m, uc, r, t, (ps,); side = RHS, per_hour = true))
            k -= uctime(m, uc, r, t)
        end
    end
    return with_time(e, k)
end

"""The rows after the loop over UC_RHSMAP: EQE_UC, EQE_UCR (with the cumulative terms), EQE_UCT, EQE_UCTS, EQE_UCSU, EQE_UCSUS."""
function uc_rest!(m::Model, ::Type{E}) where {E}
    (; UC_UT, UC_UTS, UC_T_EACH, UC_TS_EACH, UC_DYNDIR, MILESTONYR, UC_RHS, UC_RHSR, UC_R_EACH, UC_CUMCOM, UC_CUMFLO, RPC_CUMFLO) = m.d
    (; uc_ts_sum, uc_regions, uc_t_sum) = m.ix
    (; VAR_UCT, VAR_UCTS, VAR_UC, VAR_UCR, VAR_CUMCOM, VAR_CUMFLO) = m.v
    (; LHS, RHS) = m.K

    # Cumulative commodity terms of EQE_UC / EQE_UCR (equserco.mod line 49, mode 2 only), added once per region,
    # outside the sums over periods and timeslices:
    #   + SUM((COM_VAR,C,YEAR,LL)$UC_CUMCOM(UC_N,R,COM_VAR,C,YEAR,LL), UC_CUMCOM(..) * VAR_CUMCOM(R,C,COM_VAR,YEAR,LL) * CUCSCAL)
    # VAR_CUMCOM is the variable of EQ_CUMNET / EQ_CUMPRD (cumcom.jl): the preprocessor puts every UC_CUMCOM entry in
    # RC_CUMCOM (ppmain.mod line 1020), so the row that defines it exists.
    cumcom = Dict{Tuple{Id,Id},Vector{Tuple{NTuple{4,Id},Float64}}}()
    for ((uc, r, cv, c, y1, y2), v) in UC_CUMCOM
        push!(get!(cumcom, (uc, r), Tuple{NTuple{4,Id},Float64}[]), ((cv, c, y1, y2), plain(v)))
    end
    # The same for cumulative flows and activities (uc_flo.mod line 77, mode 2 only; UC_CUMACT is UC_CUMFLO with
    # c = ACT after ppmain.mod line 1009), restricted to RPC_CUMFLO:
    #   + SUM(RPC_CUMFLO(R,P,C,ALLYEAR,LL)$UC_CUMFLO(UC_N,R,P,C,ALLYEAR,LL), UC_CUMFLO(..) * VAR_CUMFLO(R,P,C,ALLYEAR,LL) * CUFSCAL)
    cumflo = Dict{Tuple{Id,Id},Vector{Tuple{NTuple{4,Id},Float64}}}()
    for ((uc, r, p, c, y1, y2), v) in UC_CUMFLO
        (r, p, c, y1, y2) in RPC_CUMFLO || continue
        push!(get!(cumflo, (uc, r), Tuple{NTuple{4,Id},Float64}[]), ((p, c, y1, y2), plain(v)))
    end
    function cumcom_terms(uc, r)
        e = E()
        for ((cv, c, y1, y2), v) in get(cumcom, (uc, r), ())
            iszero(v) || add!(e, v * CUCSCAL, VAR_CUMCOM(r, c, cv, y1, y2))
        end
        for ((p, c, y1, y2), v) in get(cumflo, (uc, r), ())
            iszero(v) || add!(e, v * m.cufscal, VAR_CUMFLO(r, p, c, y1, y2))
        end
        e
    end

    # EQE_UC(uc): one constraint over all regions and periods (equcwrap.mod, mode 2: the terms of a cumulative
    # constraint (UC_DT) are weighted by the length of the period)
    #   SUM(UC_R_SUM(r,uc), SUM(UC_T_SUM(r,uc,t), SUM(UC_TS_SUM(r,uc,s), terms)))  ==  VAR_UC(uc)
    # SPINES, %SCUM%: QE_UC and QE_UCR are the rows of SOW '1' only, the terms of the periods their expected values
    # (recurrin.stc 117-118, equcwrap.mod 17 TSUM; sow_expected); UC_TIME not with them yet
    w1 = sow_w1_scum(m)
    scum = m.sw !== nothing && m.sw.scum
    for uc in unique(k[1] for (k, _) in UC_RHS)
        w1 || break
        regions = uc_regions[uc]
        any(r -> !isempty(uc_t_sum[r, uc]) && !isempty(uc_ts_sum[r, uc]), regions) || continue
        any(r -> (r, uc, LHS) in UC_DYNDIR || (r, uc, RHS) in UC_DYNDIR, regions) &&
            error("TIMES feature not supported yet: dynamic global user constraint ($(label(m.L, uc)))")
        lhs = E()
        for r in regions, t in uc_t_sum[r, uc]
            add!(lhs, 1.0, sow_expected(() -> uc_terms(E, m, uc, r, t, uc_ts_sum[r, uc]; cumulative = true), m, E))
            (scum && !iszero(uctime(m, uc, r, t))) &&
                error("TIMES feature not supported yet with SPINES and SOLVEDA 1: UC_TIME in $(label(m.L, uc))")
            with_time(lhs, uctime(m, uc, r, t))
        end
        for r in regions
            add!(lhs, 1.0, cumcom_terms(uc, r))
        end
        row!(m, :EQE_UC, (uc,), lhs, ==, VAR_UC(uc))
    end
    # EQE_UCR(r, uc): the same per region
    for (r, uc) in unique((k[1], k[2]) for (k, _) in UC_RHSR)
        w1 || break
        ((r, uc) in UC_R_EACH && !isempty(uc_t_sum[r, uc]) && !isempty(uc_ts_sum[r, uc])) || continue
        ((r, uc, LHS) in UC_DYNDIR || (r, uc, RHS) in UC_DYNDIR) &&
            error("TIMES feature not supported yet: dynamic regional user constraint ($(label(m.L, uc)))")
        haskey(m.rows, :EQE_UCR) && (r, uc) in m.rows[:EQE_UCR].keys && continue
        lhs = E()
        for t in uc_t_sum[r, uc]
            add!(lhs, 1.0, sow_expected(() -> uc_terms(E, m, uc, r, t, uc_ts_sum[r, uc]; cumulative = true), m, E))
            (scum && !iszero(uctime(m, uc, r, t))) &&
                error("TIMES feature not supported yet with SPINES and SOLVEDA 1: UC_TIME in $(label(m.L, uc))")
            with_time(lhs, uctime(m, uc, r, t))
        end
        add!(lhs, 1.0, cumcom_terms(uc, r))
        row!(m, :EQE_UCR, (r, uc), lhs, ==, VAR_UCR(uc, r))
    end

    for (uc, t) in UC_UT
        # EQE_UCT(UC_N,T): periods only; UC_UT < UC_RHST also holds the years written in the DD files (e.g. 2050 in a
        # model whose periods end in 2045)
        t in MILESTONYR || continue
        regions = uc_regions[uc]
        any(r -> (r, uc, t) in UC_T_EACH && !isempty(uc_ts_sum[r, uc]), regions) || continue
        lhs = E()
        for r in regions
            add!(lhs, 1.0, uc_terms(E, m, uc, r, t, uc_ts_sum[r, uc]))
            with_time(lhs, uctime(m, uc, r, t))
        end
        row!(m, :EQE_UCT, (uc, t), lhs, ==, VAR_UCT(uc, t))
    end

    for (uc, t, s) in UC_UTS
        t in MILESTONYR || continue
        regions = uc_regions[uc]
        any(r -> (r, uc, t) in UC_T_EACH && (r, uc, s) in UC_TS_EACH, regions) || continue
        lhs = E()
        for r in regions
            add!(lhs, 1.0, uc_terms(E, m, uc, r, t, (s,)))
            with_time(lhs, uctime(m, uc, r, t))
        end
        row!(m, :EQE_UCTS, (uc, t, s), lhs, ==, VAR_UCTS(uc, t, s))
    end

    # EQE_UCSU(uc,t) / EQE_UCSUS(uc,t,s): dynamic constraints between successive periods with the regions selected
    # (UC_R_SUM) summed; written where a region of the constraint has t in UC_T_SUCC (UC_RTSUC, also the set of a
    # myopic step) and, for the second, s in UC_TS_EACH. The variables are those of EQE_UCT / EQE_UCTS.
    #   SU(UC_N,T)$(SUM(UC_T_SUCC(UC_R_SUM(R,UC_N),T)$SUM(UC_TS_SUM(R,UC_N,S),1),1)$UC_UT(UC_N,T))
    #   SUS(UC_N,T,S)$(SUM(UC_T_SUCC(UC_R_SUM(R,UC_N),T)$UC_TS_EACH(R,UC_N,S),1)$UC_UTS(UC_N,T,S))
    succ = m.d.UC_RTSUC
    for (uc, t) in UC_UT
        t in MILESTONYR || continue                       # EQE_UCSU(UC_N,T): periods only, as EQE_UCT
        regions = uc_regions[uc]
        any(r -> (r, t, uc) in succ && !isempty(uc_ts_sum[r, uc]), regions) || continue
        sow_ucsucc(m, uc, t) || continue
        lhs = E()
        for r in regions
            add!(lhs, 1.0, uc_dynamic(E, m, uc, r, t, uc_ts_sum[r, uc]))
        end
        row!(m, :EQE_UCSU, (uc, t), lhs, ==, sow_own(m, VAR_UCT, uc, t))
    end
    for (uc, t, s) in UC_UTS
        regions = uc_regions[uc]
        any(r -> (r, t, uc) in succ && (r, uc, s) in UC_TS_EACH, regions) || continue
        sow_ucsucc(m, uc, t) || continue
        lhs = E()
        for r in regions
            add!(lhs, 1.0, uc_dynamic(E, m, uc, r, t, (s,)))
        end
        row!(m, :EQE_UCSUS, (uc, t, s), lhs, ==, sow_own(m, VAR_UCTS, uc, t, s))
    end
end

"""
Dynamic user constraint of period t (equserco.mod, label DYNAMIC). The left-hand side terms are
taken in t. Where the right-hand side terms are taken depends on the side that carries the dynamics
(UC_DYNDIR):

    dynamics on the left:    terms(LHS, t)  -  terms(RHS, next period)        the years between are LAGT(t)
    dynamics on the right:   terms(LHS, t)  -  terms(RHS, previous period)    the years between are LEAD(t)
                             (a group of right-hand side terms with the SYNC attribute: of period t itself)
                             - capacity installed before the horizon, in the first period (uc_pasti.mod)
                             =  variable  +  UC_TIME(uc,r,t) * LEAD(t)

In the second form a growth coefficient is applied backwards (see `uc_terms`): the constraint
compares the new period with what the previous one allows.
"""
function uc_dynamic(::Type{E}, m::Model, uc, r, t, slices) where {E}
    (; UC_DYNDIR, UC_TIME, UC_CAP, UC_ATTR, RTP, COEF_CPT, NCAP_PASTI, LAGT, LEAD, M, B) = m.d
    (; uc_gmap_p, cptyr) = m.ix
    (; LHS, RHS, CAP, GROWTH, SYNC) = m.K
    i = findfirst(==(t), m.T)
    i === nothing && error("dynamic user constraint $(label(m.L, uc)) outside the periods")
    if !((r, uc, RHS) in UC_DYNDIR)
        years = plain(LAGT(t))
        e = uc_terms(E, m, uc, r, t, slices; side = LHS, years, nested = true)
        # the last period (a constraint summed over regions, one of which has its dynamics on the right-hand side):
        # UC_TMAP(TT,T,T,'RHS','N') has no next period, so the right-hand side terms are absent
        i < length(m.T) && add!(e, -1.0, uc_terms(E, m, uc, r, m.T[i+1], slices; side = RHS, years, nested = true))
        has(UC_TIME, uc, r, t) && add!(e, -plain(UC_TIME(uc, r, t)), years)
        return e
    end
    years = -plain(LEAD(t))
    # UC_TMAP (eqmain.mod 211-215) and equserco.mod line 83: a group of terms is taken through each dynamic attribute
    # UC_DYNT for which LIM(UC_DYNT) xor UC_ATTR(R,UC_N,SIDE,grp,UC_DYNT), LIM holding N:
    #   N        (not given)  LHS: period t;  RHS: the period before (t-1)
    #   CUMSUM   (given)      LHS: the periods before t, with the coefficients of t; RHS: those before t-1, coefficients of t-1
    #   SYNC     (given, RHS) period t
    #   CUM+     (given, RHS) the periods before t, with the coefficients of t (ppmain.mod 1162: SYNC with CUMSUM on the RHS)
    # (ppmain.mod line 1168 adds N wherever SYNC is set, so SYNC moves a group from t-1 to t). On new capacity CUMSUM is
    # taken inside `uc_terms` (cumsum = true, with the N term).
    attr(sd, grp, name) = (r, uc, sd, grp, name) in UC_ATTR
    grps = (m.K.FLO, m.K.IRE, m.K.ACT, m.K.COMPRD, m.K.COMNET, m.K.COMCON, CAP, m.K.NCAP, m.K.UCN)
    nl = any(grp -> attr(LHS, grp, m.K.N), grps)
    e = nl ? uc_terms(E, m, uc, r, t, slices; side = LHS, years, only = grp -> !attr(LHS, grp, m.K.N), nested = true, cumsum = true) :
             uc_terms(E, m, uc, r, t, slices; side = LHS, years, nested = true, cumsum = true)
    sync(grp) = attr(RHS, grp, SYNC)
    prev(grp) = !attr(RHS, grp, m.K.N)
    add!(e, -1.0, uc_terms(E, m, uc, r, t, slices; side = RHS, years, only = sync, nested = true, cumsum = true))
    for grp in grps
        one = ==(grp)
        # CUMSUM on the LHS: the periods before t (new capacity: inside the N term, unless N is given there)
        if attr(LHS, grp, m.K.CUMSUM) && (grp != m.K.NCAP || attr(LHS, grp, m.K.N))
            for tt in m.T[1:i-1]
                add!(e, 1.0, uc_terms(E, m, uc, r, tt, slices; side = LHS, years, only = one, nested = true, tc = t))
            end
        end
        # CUMSUM on the RHS: the periods before t-1, with the coefficients of t-1
        if i > 2 && attr(RHS, grp, m.K.CUMSUM) && (grp != m.K.NCAP || attr(RHS, grp, m.K.N))
            for tt in m.T[1:i-2]
                add!(e, -1.0, uc_terms(E, m, uc, r, tt, slices; side = RHS, years, only = one, nested = true, tc = m.T[i-1]))
            end
        end
        # CUM+ on the RHS: the periods before t, with the coefficients of t
        if attr(RHS, grp, m.K[Symbol("CUM+")])
            for tt in m.T[1:i-1]
                add!(e, -1.0, uc_terms(E, m, uc, r, tt, slices; side = RHS, years, only = one, nested = true, tc = t))
            end
        end
    end
    # the climate terms (uc_cli.mod, equserco.mod line 101): LHS of period t, RHS of the period before
    add!(e, 1.0, uc_cli_terms(m, uc, r, t, t, LHS, years, slices))
    i > 1 && add!(e, -1.0, uc_cli_terms(m, uc, r, m.T[i-1], m.T[i-1], RHS, years, slices))
    if i > 1
        add!(e, -1.0, uc_terms(E, m, uc, r, m.T[i-1], slices; side = RHS, years, only = prev, nested = true, cumsum = true))
    else
        # uc_pasti.mod: the capacity of the past investments stands for the period before the first
        for p in uc_gmap_p[r, uc, CAP]
            (r, t, p) in RTP || continue
            k = plain(UC_CAP(uc, RHS, r, t, p))
            iszero(k) && continue
            (r, uc, RHS, CAP, GROWTH) in UC_ATTR && (k *= abs(k)^(plain(M(t)) - plain(B(t))))
            past = sum(plain(COEF_CPT[r, v, t, p]) * plain(NCAP_PASTI(r, v, p)) for (v, q) in cptyr[r, t] if q == p && has(NCAP_PASTI, r, v, p); init = 0.0)
            add!(e, -k, past)
        end
    end
    has(UC_TIME, uc, r, t) && add!(e, -plain(UC_TIME(uc, r, t)), plain(LEAD(t)))
    return e
end

"""
The terms of user constraint uc given for one side, in region r and period t, summed over `slices`.

In a dynamic constraint (`years` given) the groups of terms with the GROWTH attribute have their
coefficient k, a growth factor per year, replaced by

    k^years  on the left-hand side,        1 / k^years  on the right-hand side

(written in TIMES as  k * ABS(k)^(years * UC_SIGN(side) - 1)); `years` is negative when the dynamics are
on the right-hand side.

`only` restricts the terms to some groups (FLO, IRE, ACT, COMPRD, COMNET, CAP, NCAP, UCN). `nested` adds the
variables of nested constraints (UC_UCN), which TIMES has in dynamic constraints only.

New capacity (UC_NCAP) is the investment variable of the period; with the BUILDUP attribute it is divided
by the lead of the period (a build rate per year). With the PERIOD attribute it is the
capacity commissioned in the period instead: the investments of the vintages whose lead time ends in
t (RVPT), and for a lifetime shorter than the period every repetition of the investment (COEF_RPTI).

`tc` is the period of the coefficients (UC_FLO, UC_IRE, UC_ACT, UC_COM, UC_CAP, UC_NCAP, UC_UCN and the CST_ANNC of
ANNUL; LL of equserco.mod line 83, %7 / %6 of the uc_*.mod files), `t` that of the variables and of everything else
(TT, %4): they differ only for the terms that a dynamic constraint takes from other periods (CUMSUM, CUM+).
"""
function uc_terms(::Type{E}, m::Model, uc, r, t, slices; side = m.K.LHS, years = nothing, per_hour = false, only = grp -> true, cumulative = false, nested = false, cumsum = false, tc = t) where {E}
    (; RS_FR, RS_BELOW, RHS_COMPRD, RHS_COMBAL, RTP, RTP_VARA, UC_FLO, UC_IRE, UC_COM, UC_CAP, UC_ACT, UC_NCAP, UC_ATTR, COM_IE, RVPT, RTP_OFF, COEF_RPTI, G_YRFR, UC_DT, D) = m.d
    (; uc_map_flo, uc_map_ire, uc_gmap_c, uc_gmap_p, vintages, flow_s, varc_ts, prc_ts, rvpt_v, ts_frac) = m.ix
    (; VAR_COMPRD, VAR_COMNET, VAR_CAP, VAR_ACT, VAR_NCAP) = m.v
    (; LHS, PRD, NET, CAP, ACT, FLO, IRE, COMPRD, COMNET, GROWTH, NCAP, PERIOD, BUILDUP) = m.K
    # UC_ATTR PERIOD / NEWFLO on FLO, IRE and ACT (the PROD over UC_PERDS in uc_flo.mod, uc_ire.mod, uc_act.mod):
    #   PERIOD:  the coefficient times FPD(t) = D(t), the total over the period
    #   NEWFLO:  FPD(t) * 1$(V = T or RVPT(r,v,p,t)) / FPD(t), only the vintage commissioned in the period
    #   both:    the product of the two factors
    perds(grp, v, p) = begin
        f = 1.0
        if (r, uc, side, grp, PERIOD) in UC_ATTR
            f *= plain(D(t))
        end
        if (r, uc, side, grp, m.K.NEWFLO) in UC_ATTR
            f *= (v == t || (r, v, p, t) in RVPT) ? 1.0 : 0.0
        end
        f
    end

    # a quantity at ts counts in s fully, unless s lies below ts: then with the share of s
    share(c, s, ts) = (r, ts, s) in RS_BELOW ? frac(m, r, t, c, s, ts) : 1.0
    # growth factor per year -> factor over the years between the two periods of a dynamic constraint
    power = years === nothing ? 0.0 : years * (side == LHS ? 1 : -1) - 1
    grow(k, grp) = (years === nothing || plain(k) == 0 || !((r, uc, side, grp, GROWTH) in UC_ATTR)) ? k : k * abs(k)^power

    # a constraint summing the periods (mode 2 of equcwrap.mod): the flow, activity, commodity and trade terms of a
    # cumulative constraint (UC_DT) are weighted by the length of the period (FPD = D); capacity terms are not.
    # With PERDISC on the group (on the LHS, for both sides) the weight is the present value of the period instead
    # (uc_flo.mod line 22, uc_ire.mod 21, uc_act.mod 22, uc_com.mod 25):
    #   (1+(FPD(T)+(COEF_PVT(R,T)-FPD(T))$UC_ATTR(R,UC_N,'LHS',grp,'PERDISC')-1)$UC_DT(R,UC_N))
    # COEF_PVT is given to the equations as UC_PVT (port-only, written only for the regions that use PERDISC)
    cum = cumulative && (r, uc) in UC_DT
    wd = cum ? plain(D(t)) : 1.0
    wdg(grp) = (cum && (r, uc, LHS, grp, m.K.PERDISC) in UC_ATTR) ? plain(m.d.UC_PVT(r, t)) : wd

    # The cost attributes (UC_COST: COST, DELIV, TAX, SUB, ANNUL; the names of UC_MAPCOST are mapped onto them in the
    # preprocessor). On a group with any of them the coefficient is multiplied by the sum of the costs of the
    # attributes given, in the period of the term, over the currencies of the region (RDCUR):
    #   flows and trade (uc_flo.mod lines 41-46, uc_ire.mod 41-46), over the timeslice of the flow and ANNUAL (TS_ANN):
    #     SUM((RDCUR(R,CUR),TS_ANN(TS,SL)), OBJ_FCOST(R,%4,P,C,SL,CUR)$COST + OBJ_FDELV(..)$DELIV
    #                                       + MIN(0,OBJ_FTAX(..))$SUB + MAX(0,OBJ_FTAX(..))$TAX)
    #   activity (uc_act.mod line 43), COST only:  PROD(UC_ATTR(R,UC_N,%5,'ACT','COST'),SUM(RDCUR(R,CUR),OBJ_ACOST(R,%4,P,CUR)))
    #   commodities (uc_com.mod lines 37-39):      SUM((UC_ATTR(R,UC_N,%5,UC_GRPTYPE,UC_COST),RDCUR(R,CUR)),OBJ_COM%10(R,%4,C,TS,UC_COST,CUR))
    # (ANNUL or DELIV on a group with no such cost: the sum is empty, the coefficient 0, as in TIMES.)
    # A cost that is EPS stays EPS through these sums (costsum).
    attr(grp, name) = (r, uc, side, grp, name) in UC_ATTR
    hascost(grp) = attr(grp, m.K.COST) || attr(grp, m.K.DELIV) || attr(grp, m.K.TAX) || attr(grp, m.K.SUB) || attr(grp, m.K.ANNUL)
    cflo, cire, acost = hascost(FLO), hascost(IRE), attr(ACT, m.K.COST)
    curs = (cflo || cire || acost || hascost(COMPRD) || hascost(COMNET) || hascost(m.K.COMCON)) ?
           [cur for (rr, cur) in m.d.RDCUR if rr == r] : Id[]
    flocost(grp, p, c, ts) = begin
        (; OB_FCOS, OB_FDEL, OB_FTAX) = m.d
        co, de, su, ta = attr(grp, m.K.COST), attr(grp, m.K.DELIV), attr(grp, m.K.SUB), attr(grp, m.K.TAX)
        xs = Float64[]
        for cur in curs, sl in (ts == m.K.ANNUAL ? (ts,) : (ts, m.K.ANNUAL))
            co && push!(xs, OB_FCOS(r, p, c, sl, cur, t))
            de && push!(xs, OB_FDEL(r, p, c, sl, cur, t))
            (su || ta) || continue
            x = OB_FTAX(r, p, c, sl, cur, t)                 # MIN(0,EPS) and MAX(0,EPS) are EPS
            su && push!(xs, iseps(x) ? x : min(0.0, x))
            ta && push!(xs, iseps(x) ? x : max(0.0, x))
        end
        costsum(xs)
    end
    e = E()
    for s in slices
        hw = per_hour ? 1 / G_YRFR[r, s] : 1.0           # constraint on a timeslice level: quantities per unit of time
        wf, wi = hw * wdg(FLO), hw * wdg(IRE)
        for (p, c) in uc_map_flo[uc, side, r], v in vintages[r, t, p], ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s])
            (only(FLO) && has(RS_FR, r, s, ts)) || continue
            k = grow(UC_FLO(uc, side, r, tc, p, c, ts), FLO) * share(c, s, ts) * wf * perds(FLO, v, p)
            cflo && (k *= flocost(FLO, p, c, ts))
            iszero(k) || add!(e, k, flow(E, m, r, v, t, p, c, ts))
        end
        # CAPFLO (uc_flo.mod lines 50-64): the flows that come with capacity, investment or decommissioning of the
        # processes in UC_CAPFLO (flows with no flow variable, RPC_NOFLO; ppmain.mod line 661), as cal_caps.mod writes them,
        # times SUM(RPCS_VAR(R,P,C,TS),RS_FR(R,TS,S)*UC_FLO(UC_N,%5,R,%7,P,C,TS)); with GROWTH times
        # SUM(RPCS_VAR,RS_FR(R,TS,S)*POWER(ABS(UC_FLO),..)), PERIOD times FPD (NEWFLO: 0), and the cost attributes times
        # SUM(RPCS_VAR,RS_FR(R,TS,S)*the costs of uc_flo.mod lines 59-63)
        if only(FLO) && !isempty(m.d.UC_CFLOW)
            for (u, sd, rr, p, c) in m.d.UC_CFLOW
                (u == uc && sd == side && rr == r) || continue
                tss = m.ix.rpcs_s[r, p, c]
                kb = sum((RS_FR(r, ts, s) * plain(UC_FLO(uc, side, r, tc, p, c, ts)) for ts in tss); init = 0.0)
                iszero(kb) && continue
                if years !== nothing && (r, uc, side, FLO, GROWTH) in UC_ATTR
                    kb *= sum((RS_FR(r, ts, s) * abs(plain(UC_FLO(uc, side, r, tc, p, c, ts)))^power for ts in tss); init = 0.0)
                end
                (r, uc, side, FLO, PERIOD) in UC_ATTR && (kb *= plain(D(t)))
                (r, uc, side, FLO, m.K.NEWFLO) in UC_ATTR && (kb *= 0.0)
                cflo && (kb *= sum((RS_FR(r, ts, s) * flocost(FLO, p, c, ts) for ts in tss); init = 0.0))
                kb *= wf
                iszero(kb) && continue
                for io in (m.K.IN, m.K.OUT)
                    add!(e, kb, capacity_flows(E, m, r, t, c, s, io; only = ==(p)))
                end
            end
        end
        for (p, c, ie) in uc_map_ire[uc, r], v in vintages[r, t, p], ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s])
            (only(IRE) && has(RS_FR, r, s, ts)) || continue
            f = perds(IRE, v, p)
            cire && (f *= flocost(IRE, p, c, ts))
            iszero(f) || add!(e, grow(UC_IRE(uc, side, r, tc, p, c, ts, ie), IRE) * share(c, s, ts) * wi * f, trade(m, r, v, t, p, c, ts, ie))
        end
        wa = hw * wdg(ACT)
        for p in uc_gmap_p[r, uc, ACT]
            ((r, t, p) in RTP_VARA && only(ACT)) || continue
            ac = acost ? costsum(m.d.OB_ACT(r, p, cur, t) for cur in curs) : 1.0
            for ts in onbranch(prc_ts[r, p], ts_frac[r, s])
                k = grow(UC_ACT(uc, side, r, tc, p, ts), ACT) * RS_FR(r, s, ts) * wa
                iszero(k) && continue
                for v in vintages[r, t, p]
                    f = perds(ACT, v, p)
                    acost && (f *= ac)
                    iszero(f) || add!(e, k * f, VAR_ACT(r, v, t, p, ts))
                end
            end
        end
        for (kind, defined, VAR, gross, OBJ_COM) in ((PRD, RHS_COMPRD, VAR_COMPRD, COMPRD, m.d.OBJ_COMPD), (NET, RHS_COMBAL, VAR_COMNET, COMNET, m.d.OBJ_COMNT))
            for (c, grp) in uc_gmap_c[r, uc, kind], ts in onbranch(varc_ts[r, t, c], ts_frac[r, s])
                ((r, t, c, ts) in defined && has(RS_FR, r, s, ts) && only(grp)) || continue
                k = grow(UC_COM(uc, kind, side, r, tc, c, ts, grp), grp)
                # coefficient given per unit before losses: (1+(1/COM_IE(R,%4,C,TS)-1)$(UC_ATTR(R,UC_N,%5,UC_GRPTYPE,'EFF')
                # XOR DIAG(UC_GRPTYPE,'COM%9'))) (uc_com.mod line 28): the gross group, or with EFF any other group.
                # A COM_IE given as 0 is EPS and keeps its record (ppmain.mod 704-705, OPTION RCS < COM_IE counts it):
                # GAMS stops with "division by eps", and so does the port
                if (grp == gross) ⊻ attr(grp, m.K.EFF)
                    ie = COM_IE[r, t, c, ts]
                    iseps(ie) && error("division by eps: user constraint ", label(m.L, uc), " (", join(label(m.L, (r, t, s)), ","),
                                       "): COM_IE(", join(label(m.L, (r, t, c, ts)), ","), ") is EPS (given as 0); TIMES stops here too (uc_com.mod 28)")
                    k /= ie
                end
                # PERIOD (uc_com.mod line 35): the total over the period, FPD(%4)
                attr(grp, PERIOD) && (k *= plain(D(t)))
                if hascost(grp)
                    k *= costsum(OBJ_COM(r, t, c, ts, n, cur) for n in (m.K.COST, m.K.DELIV, m.K.TAX, m.K.SUB, m.K.ANNUL) if attr(grp, n)
                                 for cur in curs)
                end
                add!(e, k * share(c, s, ts) * (hw * wdg(grp)), VAR(r, t, c, ts))
            end
        end
    end
    capact = (r, uc, side, CAP, m.K.CAPACT) in UC_ATTR
    for p in uc_gmap_p[r, uc, CAP]
        ((r, t, p) in RTP && only(CAP)) || continue
        k = grow(UC_CAP(uc, side, r, tc, p), CAP)
        # CAPACT (uc_cap.mod line 28): the capacity in activity units, PROD(UC_ATTR(r,uc,side,'CAP','CAPACT'),PRC_CAPACT(r,p))
        capact && (k = k * plain(m.d.PRC_CAPACT(r, p)))
        add!(e, k, VAR_CAP(r, t, p))
    end
    # ONLINE (uc_cap.mod lines 36-43, only in a constraint by timeslice, %5 = S, with VDA): the capacity off line is taken
    # off the capacity of the dispatchable processes (RP_UPL(R,P,'FX')):
    #   SUM(RTP(R,%3,P)$(RP_UPL(R,P,'FX')$UC_GMAP_P(R,UC_N,'CAP',P)), EPS+
    #     UC_CAP(UC_N,%4,R,%6,P)*PROD(UC_ATTR(R,UC_N,%4,'CAP','CAPACT'),PRC_CAPACT(R,P)) *
    #     SUM(RTP_VINTYR(R,V,%3,P),(%UPSCAPS%)))$UC_ATTR(R,UC_N,%4,'CAP','ONLINE')
    # with %UPSCAPS% = -SUM(TS_MAP(R,ALL_TS,S)$RPS_UPS(R,P,ALL_TS),VAR_UPS(R,V,T,P,ALL_TS,'N')) (coef_ext.vda line 30)
    if per_hour && (r, uc, side, CAP, m.K.ONLINE) in UC_ATTR
        for p in uc_gmap_p[r, uc, CAP]
            ((r, t, p) in RTP && only(CAP) && (r, p, m.K.FX) in m.d.RP_UPL) || continue
            k = UC_CAP(uc, side, r, tc, p)
            capact && (k = k * plain(m.d.PRC_CAPACT(r, p)))
            iszero(k) && continue
            for s in slices, v in vintages[r, t, p]
                add!(e, -k, offline(m, r, v, t, p, s))
            end
        end
    end
    # Reserve flows (uc_cap.mod lines 44-49, ABS=YES, in the same constraints as ONLINE):
    #   SUM(BS_UCMAP(UC_N,%4,R,P,C)$BS_COMTS(R,C,S),UC_FLO(UC_N,%4,R,%6,P,C,'ANNUAL') * PRC_CAPACT(R,P) *
    #     SUM((RTP_VINTYR(R,V,%3,P),BS_PRS(R,P,TS))$RS_FR(R,S,TS),RS_FR(R,TS,S) *
    #       SUM(LNX(L),%VAR%_BSPRS(R,V,T,P,C,TS,L)$(IPS(L)+BS_SUPP(R,P)$(ABS(BS_RTYPE(R,C))>2)))))
    if per_hour && !isempty(m.d.BS_UCMAP)
        (; BS_UCMAP, BS_COMTS, BS_PRS, BS_SUPP, BS_RTYPE, PRC_CAPACT) = m.d
        for (u, sd, rr, p, c) in BS_UCMAP
            (u == uc && sd == side && rr == r && only(CAP)) || continue
            k = UC_FLO(uc, side, r, tc, p, c, m.K.ANNUAL) * PRC_CAPACT(r, p)
            nsp = (r, p) in BS_SUPP && abs(plain(BS_RTYPE(r, c))) > 2
            for s in slices
                (r, c, s) in BS_COMTS || continue
                for v in vintages[r, t, p], (rr2, pp, ts) in BS_PRS
                    (rr2 == r && pp == p && has(RS_FR, r, s, ts)) || continue
                    f = k * RS_FR(r, ts, s)
                    add!(e, f, m.v.VAR_BSPRS(r, v, t, p, c, ts, m.K.N))
                    nsp && add!(e, f, m.v.VAR_BSPRS(r, v, t, p, c, ts, m.K.FX))
                end
            end
        end
    end
    period = (r, uc, side, NCAP, PERIOD) in UC_ATTR
    # The cost attributes on NCAP (uc_ncap.mod lines 37-42): with any of UC_COST (COST, DELIV, TAX, SUB, ANNUL) on the side,
    # the coefficient is multiplied by
    #   PROD(L('N'),PROD(REG(R)$SUM(UC_ATTR(R,UC_N,%4,'NCAP',UC_COST),1),
    #     SUM(RDCUR(R,CUR),
    #   $IF NOT %3==%6   SUM(UC_ATTR(R,UC_N,%4,'NCAP',UC_ANNUL),CST_ANNC(R,%3,P,%6,UC_ANNUL,CUR))+
    #                    OBJ_ICOST(R,%3,P,CUR)$UC_ATTR(R,UC_N,%4,'NCAP','COST')
    #                    +OBJ_ITAX(R,%3,P,CUR)$UC_ATTR(R,UC_N,%4,'NCAP','TAX')
    #                    -OBJ_ISUB(R,%3,P,CUR)$UC_ATTR(R,UC_N,%4,'NCAP','SUB'))))
    # ANNUL (the INVCOST attribute, ppmain.mod line 1156): the annual investment payment in t of the investment made in tt,
    # CST_ANNC(r,tt,p,t,'INVCOST',cur); ANNUL sets CUMSUM, so it is only in the form dynamic on the right-hand side,
    # where %3 (TT) differs from %6 (LL). COST / TAX / SUB: the cost, tax and subsidy of the period tt of the
    # investment (%3), UC_ICOST(r,tt,p,name,cur) as the preprocessor writes them.
    annul = (r, uc, side, NCAP, m.K.ANNUL) in UC_ATTR
    # SUM(UC_ATTR(R,UC_N,%4,'NCAP',UC_ANNUL),CST_ANNC(R,%3,P,%6,UC_ANNUL,CUR)): INVCOST, INVTAX, INVSUB as given
    annuls = Id[n for n in (m.K.INVCOST, m.K.INVTAX, m.K.INVSUB) if annul && (r, uc, side, NCAP, n) in UC_ATTR]
    icost = (r, uc, side, NCAP, m.K.COST) in UC_ATTR
    itax = (r, uc, side, NCAP, m.K.TAX) in UC_ATTR
    isub = (r, uc, side, NCAP, m.K.SUB) in UC_ATTR
    costs = annul || icost || itax || isub || (r, uc, side, NCAP, m.K.DELIV) in UC_ATTR
    # The currencies of these costs, and their sums, in loops: a second `curs` (the one of the flows above) captured by
    # a closure made both a box of unknown type, and the generators over it were compiled in every run that has them.
    # The order of the terms is that of the generators.
    ncurs = costs ? Id[cur for (rr, cur) in m.d.RDCUR if rr == r] : Id[]
    function uci(tt, p, name)
        f = 0.0
        for cur in ncurs
            has(m.d.UC_ICOST, r, tt, p, name, cur) && (f += plain(m.d.UC_ICOST(r, tt, p, name, cur)))
        end
        return f
    end
    # CUMSUM (ANNUL sets it, ppmain.mod line 1161): in the form dynamic on the right-hand side the new capacity is taken in
    # every period tt up to the period t of the coefficient (UC_TMAP(T,LL,TT,SIDE,'N') and (..,'CUMSUM'), eqmain.mod
    # lines 212-213; equserco.mod line 83), the coefficient being that of t
    tts = (cumsum && (r, uc, side, NCAP, m.K.CUMSUM) in UC_ATTR) ? m.T[1:findfirst(==(t), m.T)] : (t,)
    for p in uc_gmap_p[r, uc, NCAP]
        only(NCAP) || continue
        k0 = grow(UC_NCAP(uc, side, r, tc, p), NCAP)
        iszero(k0) && continue
        for tt in tts
            (r, tt, p) in RTP || continue
            k = k0
            (r, uc, side, NCAP, BUILDUP) in UC_ATTR && (k = k / plain(m.d.LEAD(tt)))    # a build rate: per year of the lead of the period
            if costs
                f = 0.0
                for n in annuls, cur in ncurs
                    has(m.d.CST_ANNC, r, tt, p, tc, n, cur) && (f += plain(m.d.CST_ANNC(r, tt, p, tc, n, cur)))
                end
                icost && (f += uci(tt, p, m.K.COST))
                itax && (f += uci(tt, p, m.K.TAX))
                isub && (f -= uci(tt, p, m.K.SUB))
                k *= f
            end
            iszero(k) && continue
            (r, tt, p) in RTP_OFF || add!(e, k, VAR_NCAP(r, tt, p))
            if period
                # COEF_RPTI(R,T,P) - PROD(RVPT(R,T,P,MILESTONYR),2) (uc_ncap.mod line 30): 2 when the investment of t is
                # commissioned in any period (its own, or a later one with a long lead time), 1 when it never is
                n = count(t2 -> (r, tt, p, t2) in RVPT, m.T)
                for v in rvpt_v[r, p, tt]
                    add!(e, k, VAR_NCAP(r, v, p))
                end
                add!(e, k * (plain(COEF_RPTI(r, tt, p)) - 2.0^n), VAR_NCAP(r, tt, p))
            end
        end
    end
    # Nested user constraints (equserco.mod lines 76 and 99, dynamic constraints only): the variable of another
    # constraint uc2 by period, which must be free (UC_RHSRT(r,uc2,t,'N')), with the coefficient of period t:
    #   UC_UCN(uc,side,r,t,uc2) * VAR_UCRT(uc2,r,t)
    # UC_TMAP with UC_DYNT 'N' gives the coefficient the year of the variable in both forms; no GROWTH factor.
    if nested && only(m.K.UCN)
        for uc2 in m.ix.uc_ucn[uc, side, r, t]
            has(m.d.UC_RHSRT, r, uc2, t, m.K.N) || continue
            k = plain(m.d.UC_UCN(uc, side, r, tc, uc2))
            iszero(k) || add!(e, k, m.v.VAR_UCRT(uc2, r, t))
        end
    end
    return e
end
