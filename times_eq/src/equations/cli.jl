# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_CLITOT, EQ_CLICONC, EQ_CLITEMP, EQ_CLIMAX                                    equ_ext.cli, mod_ext.cli

The climate module (`\$SET CLI YES`): the total emissions and forcings VAR_CLITOT(item, y), the quantities in the
climate reservoirs VAR_CLIBOX(item, box, y) (the masses of CO2, CH4, N2O in the atmosphere and the ocean layers, the
temperature changes of the surface and the deep ocean), their balances from one milestone year to the next, and the
bounds on them. The coefficients come from the preprocessor (prep/cli.py): the transport matrices CM_AA, CM_BB, CM_CC
over the years of each period, the linearised forcing functions CM_LINFOR, the starting quantities CM_STAT0.

    EQ_CLITOT(tk, SUPERYR(t,ll))\$CM_LED(ll):
        SUM((RTCS_VARC(r,t,c,s), CG(CM_EMIS(tk)))\$CM_GHGMAP(r,c,cg), VAR_COMNET(r,t,c,s)*CM_GHGMAP(r,c,cg)*CM_EVAR(tk,ll))\$CM_PPM(tk)
        + CM_BEMI(tk,ll)
        + SUM(CM_FORCMAP(tk,emis)\$(NOT CM_EMIS(tk)), CM_LINFOR(ll,emis,'FX') + CM_LINFOR(ll,emis,'N')/CM_PPM(emis) *
              SUM(CM_BOXMAP(emis,v,box)\$CM_PHI(emis,box,emis), VAR_CLIBOX(v,box,ll)))
        + SUM(CM_FORCMAP(tk,v(cg))\$(NOT CM_EMIS(v)), CM_MAXC(ll,cg))  +  CM_EXOFORC(ll)\$(tk = FORCING)
          =  VAR_CLITOT(tk,ll)
    EQ_CLICONC(CM_CONC(CM_EMIS(k),box), t), and EQ_CLITEMP(CM_CONC('FORCING',box), t):
        SUM(CM_BOXMAP(k,v,buck), CM_AA(k,t,'1',box,buck) * VAR_CLIBOX(v,buck,t-1))
        + CM_CC(k,t,'1',box) * VAR_CLITOT(k,t-1)  +  CM_BB(k,t,'1',box) * VAR_CLITOT(k,t)
        + SUM(CM_BOXMAP(k,h,buck)\$CM_AA(k,t,'1',box,buck), CM_AA(k,t,'1',box,buck) * CM_STAT0(k,buck))\$(ORD(t)=1)
          =  SUM(CM_BOXMAP(k,v,box), VAR_CLIBOX(v,box,t))
    EQ_CLIMAX(ll, h)\$CM_MAXC(ll,h):  the quantity h in year ll, linear between the milestone years t-1 and t of the
        period that holds ll (SUPERYR), or after the last one; for an emission its total in the period  <=  CM_MAXC(ll,h)

t-1 is the milestone year before t. A year beyond the horizon with its own balance (EQ_CLIBEOH, CM_CONST('EXT-EOH') > 0)
is not taken (the preprocessor stops on it). The climate terms of user constraints (UC_CLI) are in userco.jl.

With STAGES (stochastic TIMES) the climate variables are by state of the world (SOW), VAS_CLITOT(item, y, w) and
VAS_CLIBOX(item, box, y, w), and the rows of SOW w are: EQ_CLITOT and EQ_CLICONC for the SOWs distinct in t (SW_T),
with the quantities of t-1 of the SOW that represents w there (SW_TSW), in EQ_CLICONC the total of t as well (and so
neither in the first period); EQ_CLITEMP for every SOW, with the coefficients of its climate sensitivity
(S_CM_CONST: CM_AA(FORCING,t,w,..)); EQ_CLIMAX for every SOW with a bound S_CM_MAXC(ll,h,'1',w), the temperature of
a period the mean over the SOWs that w represents there, weighted by their probabilities.
"""
function eq_cli!(m::Model)
    (; CM_TKIND, CM_KIND, CM_EMIS, CM_HISTS, CM_FORCMAP, CM_BOXMAP, CM_CONC, CM_ATMAP, CM_LED, CM_GHGMAP, CM_PPM, CM_EVAR,
        CM_BEMI, CM_LINFOR, CM_PHI, CM_MAXC, CM_EXOFORC, CM_AA, CM_BB, CM_CC, CM_STAT0, PERIODYR, M, LEAD) = m.d
    isempty(CM_TKIND) && return
    (; VAR_COMNET, VAR_CLITOT, VAR_CLIBOX) = m.v
    (; FX, N) = m.K
    lab(s) = get(m.L.ids, s, Id(0))
    FORCING, ATM, W1 = lab("FORCING"), lab("ATM"), lab("1")
    T = m.T
    yv(y) = year(m.L, y)
    prev = Dict(T[i] => T[i-1] for i in 2:length(T))
    first = T[1]
    emis(i) = i in CM_EMIS
    boxmap(k) = [(v, b) for (a, v, b) in CM_BOXMAP if a == k]
    forcmap(k) = [b for (a, b) in CM_FORCMAP if a == k]
    # With STAGES (equ_ext.cli 13-17) the variables have the SOW as their last index: `own` that of the row (%SOW%),
    # rep(t) the SOW that represents it in period t (SW_TSW(SOW,T,W): %VART%, %SWS%); the coefficients of the forcing
    # are by SOW (T%SWO%: CM_AA(CM_KIND,T,SOW,..)), the bounds are S_CM_MAXC(LL,CG,'1',SOW) (%CPAR%).
    # SENSIS (STAGES `Yes`, maindrv.mod 34): the case-sensitive `$IF %STAGES% == YES` sites are not taken, and %SOW%,
    # %VAR% are those of the deterministic model (SW_NOTAGS); the `$IFI` line of equ_ext.cli 13 still wraps the terms of
    # EQ_CLICONC and EQ_CLITEMP in SUM(SOW, ..) over the SOWs of the solve, EQ_CLITEMP with the coefficients of each
    # (T%SWO%: CM_AA(CM_KIND,T,SOW,..)), EQ_CLICONC with those of '1'.
    sens = m.sw !== nothing && m.sw.sensis
    st = m.sw !== nothing && !sens
    own = st ? m.sw.w : nothing
    rep(t) = st ? sow_at(m, t) : nothing
    vx(v, w, k...) = w === nothing ? v(k...) : v(k..., w)
    wc = st ? m.sw.w : W1
    S_CM_MAXC = m.d.S_CM_MAXC
    cpar(ll, cg) = st ? S_CM_MAXC(ll, cg, W1, own) : CM_MAXC(ll, cg)
    # SUPERYR (coef_ext.cli 170-172): SUPERYR(PERIODYR(T,LL))$(YEARVAL(LL) LE YEARVAL(T)) = YES;
    #   SUPERYR(T+1,LL)$((YEARVAL(LL) GT YEARVAL(T))$PERIODYR(T,LL)) = YES;  LOOP(MIYR_1(T++1),SUPERYR(T,LL)$(YEARVAL(LL) GT M(T)) = YES);
    nxt = Dict(T[i] => T[i+1] for i in 1:length(T)-1)
    superyr = Set{NTuple{2,Id}}()
    for (t, ll) in PERIODYR
        t in m.d.MILESTONYR || continue
        if yv(ll) <= yv(t)
            push!(superyr, (t, ll))
        elseif haskey(nxt, t)
            push!(superyr, (nxt[t], ll))
        end
    end
    mlast = plain(M(T[end]))
    for ((y,), _) in CM_LED                   # the years beyond M of the last period that the equations read
        yv(y) > mlast && push!(superyr, (T[end], y))
    end
    for ((y, _), _) in CM_MAXC
        yv(y) > mlast && push!(superyr, (T[end], y))
    end
    if st
        for ((y, _, _, _), _) in S_CM_MAXC
            yv(y) > mlast && push!(superyr, (T[end], y))
        end
    end
    # the net production of the mapped emissions, by (r, c): CM_GHGMAP(r, c, cg)
    ghg = Dict{Id,Vector{Tuple{Id,Id,Float64}}}()
    for ((r, c, cg), x) in CM_GHGMAP
        push!(get!(Vector{Tuple{Id,Id,Float64}}, ghg, cg), (r, c, x))
    end

    # EQ_CLITOT(CM_TKIND,SUPERYR(T,LL) %SOW%)$(CM_LED(LL)%SWT%)   (%SWT%: $SW_T(T,SOW))
    for tk in CM_TKIND, t in T, ((ll,), led) in CM_LED
        ((t, ll) in superyr && led != 0) || continue
        st && !((t, own) in m.sw.swt) && continue
        e = AE()
        if emis(tk) && CM_PPM(tk) != 0
            for (r, c, x) in get(ghg, tk, ())
                for s in m.ix.varc_ts[r, t, c]
                    add!(e, x * CM_EVAR(tk, ll), VAR_COMNET(r, t, c, s))
                end
            end
        end
        add!(e, CM_BEMI(tk, ll), 1.0)
        if !emis(tk)
            for em in forcmap(tk)
                emis(em) || continue
                add!(e, CM_LINFOR(ll, em, FX), 1.0)
                k = CM_LINFOR(ll, em, N) / CM_PPM(em)
                for (v, b) in boxmap(em)
                    CM_PHI(em, b, em) != 0 && add!(e, k, VAR_CLIBOX(v, b, ll))
                end
            end
        end
        for v in forcmap(tk)
            (v in CM_HISTS && !emis(v)) && add!(e, cpar(ll, v), 1.0)
        end
        tk == FORCING && add!(e, CM_EXOFORC(ll), 1.0)
        row!(m, :EQ_CLITOT, (tk, t, ll), e, ==, VAR_CLITOT(tk, ll))
    end

    # EQ_CLICONC(CM_CONC(CM_EMIS(CM_KIND),CM_BOX),T %SOW%)%SWT% and EQ_CLITEMP(CM_CONC(CM_KIND('FORCING'),CM_BOX),T %SOW%)
    # With STAGES the terms of T-1, and in EQ_CLICONC that of the total of T, are in SUM(SW_TSW(SOW,T-1,W), ..) (%SWTD%):
    #   EQ_CLICONC: CM_AA(..,T,'1',..)*VAS_CLIBOX(..,T-1,W) + CM_CC(..)*VAS_CLITOT(..,T-1,W) + CM_BB(..)*VAS_CLITOT(..,T,SOW)
    #   EQ_CLITEMP: CM_AA(..,T,SOW,..)*VAS_CLIBOX(..,T-1,SOW) + CM_CC(..,T,SOW,..)*VAS_CLITOT(..,T-1,W);
    #               CM_BB(..,T,SOW,..)*%VART%_CLITOT(CM_KIND,T %SWS%) outside it
    for (k, box) in CM_CONC, t in T
        k in CM_KIND || continue
        name = emis(k) ? :EQ_CLICONC : k == FORCING ? :EQ_CLITEMP : continue
        conc = name == :EQ_CLICONC
        st && conc && !((t, own) in m.sw.swt) && continue
        e = AE()
        for a in (sens ? (conc ? fill(W1, length(m.sw.members)) : m.sw.members) : (conc ? W1 : wc,))
            if haskey(prev, t)
                tp = prev[t]
                for (v, buck) in boxmap(k)
                    add!(e, CM_AA(k, t, a, box, buck), vx(VAR_CLIBOX, conc ? rep(tp) : own, v, buck, tp))
                end
                add!(e, CM_CC(k, t, a, box), vx(VAR_CLITOT, rep(tp), k, tp))
            end
            if !st || haskey(prev, t) || !conc
                add!(e, CM_BB(k, t, a, box), vx(VAR_CLITOT, conc ? own : rep(t), k, t))
            end
            if t == first
                for (h, buck) in boxmap(k)
                    x = CM_AA(k, t, a, box, buck)
                    x != 0 && add!(e, x * CM_STAT0(k, buck), 1.0)
                end
            end
        end
        rhs = AE()
        for (v, b) in boxmap(k)
            b == box && add!(rhs, 1.0, vx(VAR_CLIBOX, own, v, box, t))
        end
        row!(m, name, (k, box, t), e, ==, rhs)
    end

    # EQ_CLIMAX(LL,CM_HISTS(CG) %SOW%)$%CPAR%
    sows = st ? m.sw.sows : Id[]
    group(y, w) = [x for x in sows if get(m.sw.tsw, (x, y), nothing) == w]   # SW_TSW(W,T,SOW): the SOWs that w represents
    bounds = st ? [((ll, h), cap) for ((ll, h, j, w), cap) in S_CM_MAXC if j == W1 && w == own] : collect(CM_MAXC)
    for ((ll, h), cap) in bounds
        (h in CM_HISTS && cap != 0) || continue
        tkh = h in CM_TKIND
        # the quantity h in year y of SOW w: concentration of an emission (not a total), temperature change, or a forcing
        # total; avg = (numerator, LEAD): with STAGES the temperature is the mean over the SOWs that w represents in y,
        # SUM(SW_TSW(W,y,w), SW_PROB(W)*VAS_CLIBOX(..,y,W))/SW_TPROB(y,w) * numerator / LEAD
        function q!(e, f, y, w, avg = nothing)
            if !tkh
                for (a, b) in CM_ATMAP
                    (b == h && emis(a)) || continue
                    for (v, box) in boxmap(a)
                        CM_PHI(a, box, a) != 0 && add!(e, f / CM_PPM(a), vx(VAR_CLIBOX, w, v, box, y))
                    end
                end
            end
            if (FORCING, h) in CM_ATMAP
                for (v, box) in boxmap(FORCING)
                    box == ATM || continue
                    if avg === nothing
                        add!(e, f, vx(VAR_CLIBOX, w, v, ATM, y))
                    else
                        tp = m.d.SW_TPROB(y, w)
                        for x in group(y, w)
                            add!(e, m.d.SW_PROB(x) / tp * avg[1] / avg[2], VAR_CLIBOX(v, ATM, y, x))
                        end
                    end
                end
            end
            if tkh && !emis(h) && any(b -> emis(b), forcmap(h))
                add!(e, f, vx(VAR_CLITOT, w, h, y))
            end
            return e
        end
        e = AE()
        for t in T
            ((t, ll) in superyr && yv(ll) <= yv(t) && haskey(prev, t)) || continue
            L = plain(LEAD(t))
            f = (yv(t) - yv(ll)) / L
            q!(e, 1.0 - f, t, own, st ? (L + yv(ll) - yv(t), L) : nothing)
            q!(e, f, prev[t], rep(prev[t]), st ? (yv(t) - yv(ll), L) : nothing)
        end
        if emis(h)
            for t in T
                (t, ll) in PERIODYR && add!(e, 1.0, vx(VAR_CLITOT, rep(t), h, t))
            end
        end
        for t in T
            ((t, ll) in superyr && yv(ll) > yv(t)) && q!(e, 1.0, ll, own)
        end
        hit = any(((a, b),) -> b == h && a in CM_KIND, CM_ATMAP) || tkh
        row!(m, :EQ_CLIMAX, (ll, h), e, <=, hit ? cap : 0.0)
    end
end

"""
The climate terms of a dynamic user constraint (uc_cli.mod, included from equserco.mod line 101 in the constraints whose
dynamics are on the right-hand side), side `side` of region r, coefficients of year `tc` on the variables of period `t`,
once for each timeslice of `slices`:

    SUM(CM_VAR\$UC_CLI(UC_N,SIDE,R,LL,CM_VAR), UC_CLI(UC_N,SIDE,R,LL,CM_VAR) *
        (VAR_CLITOT(CM_VAR,TT)\$CM_KIND(CM_VAR) +
         SUM(CM_BOXMAP(CM_KIND,CM_VAR,CM_BOX)\$(NOT CM_ATMAP(CM_KIND,CM_VAR)\$CM_EMIS(CM_KIND)),VAR_CLIBOX(CM_VAR,CM_BOX,TT)) +
         SUM(CM_BOXMAP(CM_EMIS,CM_HISTS,CM_BOX)\$(CM_PHI(CM_EMIS,CM_BOX,CM_EMIS)\$CM_ATMAP(CM_EMIS,CM_VAR)),
             VAR_CLIBOX(CM_VAR,CM_BOX,TT)/CM_PPM(CM_EMIS))\$(NOT CM_TKIND(CM_VAR))) *
        PROD(UC_ATTR(R,UC_N,SIDE,'CLI','GROWTH'), POWER(ABS(UC_CLI(..)),-LEAD(T)*UC_SIGN(SIDE)-1)) *
        PROD(UC_ATTR(R,UC_N,SIDE,'CLI','PERIOD'), FPD(TT)))

(the concentration term is that of CM_VAR, VAR_CLIBOX(CM_VAR,..), over the boxes of the emission, as TIMES writes it).
"""
function uc_cli_terms(m::Model, uc, r, t, tc, side, years, slices)
    (; UC_CLI, UC_ATTR, CM_KIND, CM_EMIS, CM_TKIND, CM_BOXMAP, CM_ATMAP, CM_PHI, CM_PPM, D) = m.d
    e = AE()
    isempty(UC_CLI) && return e
    (; VAR_CLITOT, VAR_CLIBOX) = m.v
    (; GROWTH, PERIOD, LHS) = m.K
    CLI = get(m.L.ids, "CLI", Id(0))
    power = years * (side == LHS ? 1 : -1) - 1
    for ((u, sd, rr, y, v), k) in UC_CLI
        (u == uc && sd == side && rr == r && y == tc && k != 0) || continue
        (r, uc, side, CLI, GROWTH) in UC_ATTR && (k = k * abs(plain(k))^power)
        (r, uc, side, CLI, PERIOD) in UC_ATTR && (k *= plain(D(t)))
        x = AE()
        v in CM_KIND && add!(x, 1.0, VAR_CLITOT(v, t))
        for (a, vv, box) in CM_BOXMAP
            (a in CM_KIND && vv == v && !((a, v) in CM_ATMAP && a in CM_EMIS)) && add!(x, 1.0, VAR_CLIBOX(v, box, t))
        end
        if !(v in CM_TKIND)
            for (a, h, box) in CM_BOXMAP
                (a in CM_EMIS && CM_PHI(a, box, a) != 0 && (a, v) in CM_ATMAP) && add!(x, 1 / CM_PPM(a), VAR_CLIBOX(v, box, t))
            end
        end
        for _ in slices
            add!(e, k, x)
        end
    end
    return e
end
