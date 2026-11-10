# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQG_UCMAX(uc,all_r,item,c,name) / EQG_UCSUMAX(uc)                            ucbet.vda

The variable of a user constraint is at least the weighted flows (UC_FLOBET) or activities (UC_ACTBET, as UC_FLOBET on
ACT) over its periods UC_T_SUM, each period weighted by FPD(t), or COEF_PVT(r,t) with PERDISC on LHS ACT:

    VAR_UC(uc) [all_r without UC_GMAXR]  +  VAR_UCR(uc,all_r) [all_r a region with UC_GMAXR]
        >=  flows  (name = N:    SUM(r = all_r with UC_GMAXR, or every r without it when all_r is IMPEXP),
                                 SUM((p,com,s), UC_FLOBET(uc,r,t,p,c) * (flow of com in group c [standard],
                                                                         import of com [trade])))
        +   activities (name = EACH: process item; r = all_r, or every r when all_r is IMPEXP,
                                 UC_FLOBET(uc,r,t,p,ACT) * (VAR_ACT [standard], import [trade]))

    VAR_UC(uc)  >=  SUM(r with UC_GMAXR(r,uc), VAR_UCR(uc,r))                    (when some UC_GMAXR(.,uc))

The sums are taken over the vintages of each period; trade processes count their imports only (VAR_IRE, or the
activity times PRC_ACTFLO when the activity is the trade flow).
"""
function eq_ucbet!(m::Model)
    (; UC_GMAX, UC_GMAXR, UC_FLOBET, UC_T_SUM, UC_ATTR, UC_PVT, FPD, REG, RTPCS_VARF, RP_STD, RP_IRE, RPC_IRE, RPC_AIRE,
       PRC_ACTFLO, RTP_VARA, COM_GMAP) = m.d
    (; vintages, prc_ts, group_c, flow_cs) = m.ix
    (; VAR_UC, VAR_UCR, VAR_ACT, VAR_IRE) = m.v
    (; LHS, ACT, PERDISC, IMP, N, EACH) = m.K
    isempty(UC_GMAX) && return
    IMPEXP = id!(m.L, "IMPEXP")
    regs = [r for (r,) in REG]
    periods = Dict{Tuple{Id,Id},Vector{Id}}()
    for (r, uc, t) in UC_T_SUM
        t in m.T && push!(get!(periods, (r, uc), Id[]), t)
    end
    bet = Dict{Tuple{Id,Id,Id,Id},Vector{Tuple{Id,Float64}}}()        # (uc, r, t, c) -> [(p, w)]
    for ((uc, r, t, p, c), w) in UC_FLOBET
        push!(get!(bet, (uc, r, t, c), Tuple{Id,Float64}[]), (p, w))
    end
    weight(r, uc, t) = (r, uc, LHS, ACT, PERDISC) in UC_ATTR ? UC_PVT(r, t) : FPD(t)
    # the import flows of commodity com of trade process p in timeslice s
    function imports(e, k, r, v, t, p, com, s)
        (r, p, com, IMP) in RPC_IRE || return
        if (r, p, com) in RPC_AIRE
            add!(e, k * PRC_ACTFLO(r, v, p, com), VAR_ACT(r, v, t, p, s))
        else
            add!(e, k, VAR_IRE(r, v, t, p, com, s, IMP))
        end
    end
    function flows!(e, uc, r, c)
        for t in get(periods, (r, uc), Id[])
            ft = weight(r, uc, t)
            for (p, w) in get(bet, (uc, r, t, c), Tuple{Id,Float64}[]), (com, s) in flow_cs[r, t, p]
                (r, c, com) in COM_GMAP || continue
                for v in vintages[r, t, p]
                    (r, p) in RP_STD && add!(e, ft * w, flow(m, r, v, t, p, com, s))
                    (r, p) in RP_IRE && imports(e, ft * w, r, v, t, p, com, s)
                end
            end
        end
    end
    function activities!(e, uc, r, p)
        for t in get(periods, (r, uc), Id[])
            ft = weight(r, uc, t)
            for (q, w) in get(bet, (uc, r, t, ACT), Tuple{Id,Float64}[])
                q == p || continue
                for v in vintages[r, t, p]
                    if (r, p) in RP_STD && (r, t, p) in RTP_VARA
                        for s in prc_ts[r, p]
                            add!(e, ft * w, VAR_ACT(r, v, t, p, s))
                        end
                    end
                    if (r, p) in RP_IRE
                        for (com, s) in flow_cs[r, t, p]
                            imports(e, ft * w, r, v, t, p, com, s)
                        end
                    end
                end
            end
        end
    end

    for (uc, ar, item, c, name) in UC_GMAX
        lhs = AE()
        region = ar in regs
        if (ar, uc) in UC_GMAXR
            region && add!(lhs, 1.0, VAR_UCR(uc, ar))
        else
            add!(lhs, 1.0, VAR_UC(uc))
        end
        rhs = AE()
        if name == N
            if region
                (ar, uc) in UC_GMAXR && flows!(rhs, uc, ar, c)
            else
                for r in regs
                    (r, uc) in UC_GMAXR || flows!(rhs, uc, r, c)
                end
            end
        elseif name == EACH
            for r in (region ? (ar,) : regs)
                activities!(rhs, uc, r, item)
            end
        end
        row!(m, :EQG_UCMAX, (uc, ar, item, c, name), lhs, >=, rhs)
    end
    done = Set{Id}()
    for (ar, uc) in UC_GMAXR
        uc in done && continue
        push!(done, uc)
        rhs = AE()
        for r in regs
            (r, uc) in UC_GMAXR && add!(rhs, 1.0, VAR_UCR(uc, r))
        end
        row!(m, :EQG_UCSUMAX, (uc,), 1.0 * VAR_UC(uc), >=, rhs)
    end
end
