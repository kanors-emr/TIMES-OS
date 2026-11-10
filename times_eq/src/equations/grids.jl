# SPDX-License-Identifier: GPL-3.0-or-later
# Grids (VEDA-TIMES grid extension): powerflo.vda and gasgrids.vda.
#
# A grid commodity (GAS, ELC, ...) is split into nodes (RC_GRID), connected by trade processes inside the region.
# The supply of the commodity is allocated to the nodes by generation type (EQ_GR_GENALL, GR_GENFR / GR_GENMAP),
# and so is the demand (EQ_GR_DEMALL, GR_ENDFR): the flows between the commodity and its nodes are VAR_GRIDIO,
# which also enter the commodity balances (the IREAUX terms of cal_ire.mod, see `grid_io`).
#
# Gas grids add pressures to the nodes and turn the pipeline flows into mass flows bounded by the pressures
# (Weymouth), with compressors and linepack. In the LP the Weymouth relation is a stepped linearisation
# (EQ_GG_WEYMST, EQ_GG_STEP); in the MIP (fixed pressure points GG_PP) a Taylor expansion (EQ_GG_WEYMTX) and
# binary flow directions VAR_GG_Y.
#
# The DC power flow by transfer factors, the candidate lines and the N-1 bound are in ptdf.jl. Not written: the
# phase-angle form (EQ_GR_POWFLO) and the nodal balance costs; the preprocessor stops when the input has them.

"""
Flows between commodity c and its grid nodes in the balance of c, and between a node and its commodity in the
balance of the node (powerflo.vda IREAUX, on the consumption side, times COM_IE):

    SUM(node com of c, GRIDIO(r,t,c,com,s,OUT) - GRIDIO(r,t,c,com,s,IN) [allocation by group NRG])     c a grid commodity
    SUM(commodity com of node c, GRIDIO(r,t,com,c,s,IN) [allocation by group NRG] - GRIDIO(r,t,com,c,s,OUT))   c a node
"""
function grid_io(m::Model, r, t, c, s)
    (; GR_ALGMAP) = m.d
    (; gr_dem_at, gr_dem_of) = m.ix
    (; VAR_GRIDIO) = m.v
    (; IN, OUT, NRG) = m.K
    e = AE()
    for com in gr_dem_at[r, c]
        add!(e, 1.0, VAR_GRIDIO(r, t, c, com, s, OUT))
        (r, NRG, c) in GR_ALGMAP && add!(e, -1.0, VAR_GRIDIO(r, t, c, com, s, IN))
    end
    for com in gr_dem_of[r, c]
        (r, NRG, com) in GR_ALGMAP && add!(e, 1.0, VAR_GRIDIO(r, t, com, c, s, IN))
        add!(e, -1.0, VAR_GRIDIO(r, t, com, c, s, OUT))
    end
    return e
end

"""
    EQ_GR_GENALL(r,t,c,s,cg)                                                     powerflo.vda

Supply allocated to node c, for allocation group cg (GR_ALGMAP(r,cg,cg)):

    SUM(process p supplying com as generation type item [GR_PRCMAP], com in group cg,
        GR_GENMAP(r,p,item) * GR_GENFR(r,t,c,item) * (output of p [standard process, c a node of com] |
                                                      import * (1 + IRE_FLOSUM(..,IMP,com,OUT)) | storage output - input))
      [+ GRIDIO(r,t,c,c,s,OUT) - GRIDIO(r,t,c,c,s,IN) - ... for a balancing node]
      =  SUM(com in group cg with node c, GRIDIO(r,t,com,c,s,OUT) [+ GRIDIO(r,t,com,c,s,IN), allocation by commodity])
"""
function eq_gr_genall!(m::Model)
    (; GR_GNALL, GR_ALGMAP, GR_ALLMAP, GR_DEMMAP, GR_GENMAP, GR_GENFR, RP_STD, RP_IRE, RPC_IRE, RPC_STG, RTC, TOP, RS_FR, IRE_FLOSUM) = m.d
    (; varc_ts, gr_prcmap, gr_algmap, gr_dem_of, vintages, flow_s, rpcs_s, ts_frac) = m.ix
    (; VAR_GRIDIO, VAR_SIN, VAR_SOUT) = m.v
    (; IN, OUT, IMP, NRG) = m.K
    isempty(GR_GNALL) && return
    walked = Set{NTuple{4,Id}}()        # (r, t, p, com) whose storage flows have been walked over all their timeslices
    for (r, t, c) in GR_GNALL, (r1, cg, cg2) in GR_ALGMAP
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        (r1 == r && cg == cg2) || continue
        for s in varc_ts[r, t, c]
            lhs = AE()
            for (p, com, item) in gr_prcmap[r]
                (r, cg, com) in GR_ALGMAP || continue
                w = GR_GENMAP(r, p, item) * GR_GENFR(r, t, c, item)
                # (EPS * EPS underflows to 0 here and is EPS in GAMS: with both on record the term stays, as a zero)
                iszero(w) && has(GR_GENMAP, r, p, item) && has(GR_GENFR, r, t, c, item) && (w = EPS)
                iszero(w) && continue
                if (r, p) in RP_STD && (r, c, com) in GR_ALLMAP
                    for ts in onbranch(flow_s[r, t, p, com], ts_frac[r, s])
                        has(RS_FR, r, s, ts) || continue
                        f = w * frac(m, r, t, com, s, ts)
                        for v in vintages[r, t, p]
                            add!(lhs, f, flow(m, r, v, t, p, com, ts))
                        end
                    end
                end
                if (r, p) in RP_IRE && (r, p, com, IMP) in RPC_IRE
                    for ts in onbranch(flow_s[r, t, p, com], ts_frac[r, s])
                        has(RS_FR, r, s, ts) || continue
                        f = w * (1 + IRE_FLOSUM(r, t, p, com, ts, IMP, com, OUT)) * RS_FR(r, s, ts)
                        for v in vintages[r, t, p]
                            add!(lhs, f, trade(m, r, v, t, p, com, ts, IMP))
                        end
                    end
                end
                if (r, p, com) in RPC_STG
                    # every timeslice the first time (the variables are created in that order, as before; off the branch
                    # of s the coefficient is zero and add! leaves the term out), then those on the branch
                    first = !((r, t, p, com) in walked)
                    first && push!(walked, (r, t, p, com))
                    for ts in (first ? rpcs_s[r, p, com] : onbranch(rpcs_s[r, p, com], ts_frac[r, s])), v in vintages[r, t, p]
                        f = w * RS_FR(r, s, ts)
                        add!(lhs, f, VAR_SOUT(r, v, t, p, com, ts))
                        (r, p, com, IN) in TOP && add!(lhs, -f, VAR_SIN(r, v, t, p, com, ts))
                    end
                end
            end
            if (r, cg, c) in GR_ALLMAP
                add!(lhs, 1.0, VAR_GRIDIO(r, t, c, c, s, OUT))
                add!(lhs, -1.0, VAR_GRIDIO(r, t, c, c, s, IN))
                for com in gr_dem_of[r, c]
                    add!(lhs, -1.0, VAR_GRIDIO(r, t, com, c, s, OUT))
                    (r, NRG, com) in GR_ALGMAP && add!(lhs, 1.0, VAR_GRIDIO(r, t, com, c, s, IN))
                end
            end
            rhs = AE()
            for com in gr_algmap[r, cg]
                ((r, c, com) in GR_ALLMAP && (r, t, com) in RTC) || continue
                add!(rhs, 1.0, VAR_GRIDIO(r, t, com, c, s, OUT))
                (r, com, com) in GR_ALGMAP && add!(rhs, 1.0, VAR_GRIDIO(r, t, com, c, s, IN))
            end
            row!(m, :EQ_GR_GENALL, (r, t, c, s, cg), lhs, ==, rhs)
        end
    end
end

"""
    EQ_GR_DEMALL(r,t,c,s,grid)                                                   powerflo.vda

Demand allocated to node c (all nodes with a demand fraction GR_DEMFR but the largest of the grid, GR_ADO):

    output of standard processes into a sectoral demand com * (GR_GENMAP * GR_GENFR - GR_ENDFR(r,t,c,com) * (1 + GR_ENDFR(r,t,com,com)) - ...)
      + exports * GR_GENMAP * (GR_ENDFR(r,t,c,com) [+ GR_DEMFR] - GR_GENFR)
      + SUM(commodity com of node c, GRIDIO(r,t,com,c,s,IN) - GR_ENDFR(r,t,c,com) * SUM(node com2 of com, GRIDIO(r,t,com,com2,s,IN)))
      [- GR_DEMFR * SUM(largest nodes, GRIDIO(r,t,ACT,com,s,IN)), grids without sectoral demands]     =  0

and for the largest node, the aggregate of the withdrawals:

    GRIDIO(r,t,ACT,c,s,IN) - SUM(commodity com of node c, node com2 of the grid, GRIDIO(r,t,com,com2,s,IN))  =  0
"""
function eq_gr_demall!(m::Model)
    (; RC_GRID, GR_ADO, GR_DEMFR, GR_ENDFR, GR_ENDC, GR_GENP, GR_GENMAP, GR_GENFR, GR_DEMMAP, GR_ALGMAP, GR_ALLMAP, GR_PRCMAP,
       RP_STD, RP_IRE, RPC_IRE, RTC, RS_FR, IRE_FLOSUM) = m.d
    (; varc_ts, gr_grid_of, gr_endc, gr_gmapc, gr_prcmap, gr_dem_of, gr_dem_at, top_p, vintages, flow_s, ts_frac) = m.ix
    (; VAR_GRIDIO) = m.v
    (; IN, OUT, EXP, NRG, ACT) = m.K
    isempty(GR_DEMFR) && return
    for (r, t, c) in RC_GRID, g in gr_grid_of[r, c], s in varc_ts[r, t, c]
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        has(GR_DEMFR, r, t, c, s) || continue
        lhs = AE()
        nrg = (r, g, NRG) in GR_ENDC
        if (r, t, c) in GR_ADO
            for com in gr_endc[r, g], p in top_p[r, com, OUT]
                (r, p) in RP_STD || continue
                ((r, p) in GR_GENP && (r, c, com) in GR_DEMMAP) && continue
                k = sum((GR_GENMAP(r, p, item) * GR_GENFR(r, t, c, item) for (p2, c2, item) in gr_prcmap[r] if p2 == p && c2 == com); init = 0.0) -
                    GR_ENDFR(r, t, c, com) * (1 + GR_ENDFR(r, t, com, com)) - (((r, p) in GR_GENP && nrg) ? GR_DEMFR(r, t, c, s) : 0.0)
                iszero(k) && continue
                for ts in onbranch(flow_s[r, t, p, com], ts_frac[r, s])
                    has(RS_FR, r, s, ts) || continue
                    f = k * frac(m, r, t, com, s, ts)
                    for v in vintages[r, t, p]
                        add!(lhs, f, flow(m, r, v, t, p, com, ts))
                    end
                end
            end
            for (p, com, item) in gr_prcmap[r]
                ((r, p) in RP_IRE && (r, p, com, EXP) in RPC_IRE && (r, NRG, com) in GR_ALGMAP && (r, c, com) in GR_ALLMAP) || continue
                k = GR_GENMAP(r, p, item) * (GR_ENDFR(r, t, c, com) + (nrg ? GR_DEMFR(r, t, c, s) : 0.0) - GR_GENFR(r, t, c, item))
                iszero(k) && continue
                for ts in onbranch(flow_s[r, t, p, com], ts_frac[r, s])
                    has(RS_FR, r, s, ts) || continue
                    f = k * (1 + IRE_FLOSUM(r, t, p, com, ts, EXP, com, IN)) * RS_FR(r, s, ts)
                    for v in vintages[r, t, p]
                        add!(lhs, f, trade(m, r, v, t, p, com, ts, EXP))
                    end
                end
            end
            for com in gr_dem_of[r, c]
                (r, t, com) in RTC || continue
                add!(lhs, 1.0, VAR_GRIDIO(r, t, com, c, s, IN))
                k = GR_ENDFR(r, t, c, com)
                iszero(k) && continue
                for com2 in gr_dem_at[r, com]
                    (r, t, com2) in RTC && add!(lhs, -k, VAR_GRIDIO(r, t, com, com2, s, IN))
                end
            end
            if nrg
                k = GR_DEMFR(r, t, c, s)
                for com in gr_gmapc[r, g]
                    (r, t, com) in GR_ADO || add!(lhs, -k, VAR_GRIDIO(r, t, ACT, com, s, IN))
                end
            end
        else
            add!(lhs, 1.0, VAR_GRIDIO(r, t, ACT, c, s, IN))
            for com in gr_dem_of[r, c]
                (r, t, com) in RTC || continue
                for com2 in gr_gmapc[r, g]
                    (r, t, com2) in RTC && add!(lhs, -1.0, VAR_GRIDIO(r, t, com, com2, s, IN))
                end
            end
        end
        row!(m, :EQ_GR_DEMALL, (r, t, c, s, g), lhs, ==, 0.0)
    end
end

# ---------------------------------------------------------------------------------------------- gas grids

"""Pressure at the inlet of pipeline p at node c: VAR_GG_PR(r,t,c,s) [+ VAR_GG_PADD(r,t,p,c,s) with a compressor, GG_GAMMA]."""
function gg_prio(m::Model, r, t, p, c, s)
    e = AE()
    add!(e, 1.0, m.v.VAR_GG_PR(r, t, c, s))
    has(m.d.GG_GAMMA, r, t, p, c) && add!(e, 1.0, m.v.VAR_GG_PADD(r, t, p, c, s))
    return e
end

"""Unsigned pressure of pipeline p at node c: VAR_GG_PDIF(r,t,p,c,r,ACT,s)."""
gg_pru(m::Model, r, t, p, c, s) = m.v.VAR_GG_PDIF(r, t, p, c, r, m.K.ACT, s)

"""
Flow direction from node c to node c2 (VAR_GG_Y2 / the factor of VAR_GG_PDMAX):

    VAR_GG_Y(r,t,p,c,s) [pipeline in direction c -> c2]  +  1 - VAR_GG_Y(r2,t,p,c2,s) [pipeline in direction c2 -> c]
"""
function gg_dir(m::Model, r, t, p, c, r2, c2, s)
    e = AE()
    (r, c, r2, c2, p) in m.d.GG_TOP && add!(e, 1.0, m.v.VAR_GG_Y(r, t, p, c, s))
    if (r2, c2, r, c, p) in m.d.GG_TOP
        e.constant += 1.0
        add!(e, -1.0, m.v.VAR_GG_Y(r2, t, p, c2, s))
    end
    return e
end

"""
Slack of the Weymouth rows (VAR_GG_WSLAC): with a Weymouth constant at c,

    VAR_GG_PDIF(r,t,p,ACT,r,c,s) [+ 8/11 * VAR_GG_PDIF(r2,t,p,ACT,r2,c2,s), reverse direction stepped, LP]
"""
function gg_wslac(m::Model, r, t, p, c, r2, c2, s)
    e = AE()
    has(m.d.GG_KGF, r, t, p, c) || return e
    (; ACT) = m.K
    add!(e, 1.0, m.v.VAR_GG_PDIF(r, t, p, ACT, r, c, s))
    ((r2, p, c2, r, c) in m.d.GG_WINK && iszero(plain(m.d.GG_M1()))) && add!(e, 8 / 11, m.v.VAR_GG_PDIF(r2, t, p, ACT, r2, c2, s))
    return e
end

"""Largest pressure difference over the pipeline from c to c2: MAX((GG_PRBD(c,UP) * MAX(1,GG_GAMMA))**z - GG_PRBD(c2,LO)**z, 0)."""
gg_pdmax(m::Model, r, t, p, c, r2, c2, z) =
    max((plain(m.d.GG_PRBD(r, t, c, m.K.UP)) * max(1.0, plain(m.d.GG_GAMMA(r, t, p, c))))^z - plain(m.d.GG_PRBD(r2, t, c2, m.K.LO))^z, 0.0)

"""
Gas grid equations (gasgrids.vda), for each pipeline p from node c to node c2 (GG_LINK) in the timeslices of p:

    EQ_GG_MFLO    VAR_GG_MF * GG_DENS(r,c) * G_YRFR(r,s) * 8760  =  (export at c + import at c2) / 2
    EQ_GG_GAMA    VAR_GG_PADD  <=  (GG_GAMMA - 1) * VAR_GG_PR                                     compressor
    EQ_GG_MBND    VAR_GG_MF [+ slack]  <=  GG_MM * pressure difference (N)  |  GG_KGF * SQRT(pdmax(2)) * direction (FX)
    EQ_GG_WEYMTX  VAR_GG_MF  <=  GG_KGF * (Taylor expansion at the pressure points GG_PP)          (MIP)
    EQ_GG_HLIP    linepack(s)  =  linepack(previous s) + exports - imports at both ends
    EQ_GG_HLEV    linepack  =  GG_KLP * GG_DENS * RS_STGPRD * mean pressure
    EQ_GG_PDIF1   pressure difference / unsigned pressure bounded by the flow direction
    EQ_GG_PDIF2   reverse pressure difference = inlet pressures difference + pressure difference
    EQ_GG_STEP    SUM(steps) of both directions <= 1                                                  (LP)
    EQ_GG_PRIO    unsigned pressures of both ends = inlet pressure (N) | outlet pressure (FX) ...
    EQ_GG_WEYMST  mass flow (FX), pressure difference (LO) and unsigned pressure (UP) on the steps of GG_PPW / GG_PPM
"""
function eq_gg!(m::Model)
    (; GG_RTPC, GG_LINK, GG_TOP, GG_ARC, GG_EDGE, GG_WINK, GG_WTX, OMG, GG_DENS, GG_GAMMA, GG_KGF, GG_KLP, GG_MM, GG_PRBD,
       GG_PP, GG_PPM, GG_PPW, GG_M1, G_YRFR, RS_STGPRD, RPC_PG, COM_GMAP) = m.d
    (; gg_link, gg_ppw, gg_pp, prc_ts, vintages, top_ire_rr, ts_prev, rpc_ire) = m.ix
    (; VAR_GG_PR, VAR_GG_MF, VAR_GG_PDIF, VAR_GG_PADD, VAR_GG_STEP, VAR_GG_Y) = m.v
    (; ACT, IMP, EXP, LO, UP, FX, N) = m.K
    isempty(GG_RTPC) && return
    m1 = plain(GG_M1())
    lp = iszero(m1)
    J1, J2, J99 = id!(m.L, "1"), id!(m.L, "2"), id!(m.L, "99")
    for (r, t, p, c) in GG_RTPC
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        wtx = (r, p, c) in GG_WTX
        gamma = plain(GG_GAMMA(r, t, p, c))
        for (r2, c2) in gg_link[r, p, c], s in prc_ts[r, p]
            back = (r2, p, c2, r, c) in GG_LINK
            fwd = (r, c, r2, c2, p) in GG_TOP
            rev = (r2, c2, r, c, p) in GG_TOP
            arc = (r, c, r2, c2) in GG_ARC
            wink = (r, p, c, r2, c2) in GG_WINK
            mf = VAR_GG_MF(r, t, p, c, r2, c2, s)
            # --- EQ_GG_MFLO: trade flows of the pipeline as a mass flow
            q = AE()
            edge = (r, p, r) in GG_EDGE
            for (com, com2) in top_ire_rr[r, r2, p]
                if edge
                    (xor((r, p, com2) in RPC_PG, (r, p, c) in RPC_PG) || ((r, c, com) in COM_GMAP && (r2, c2, com2) in COM_GMAP)) || continue
                end
                for v in vintages[r, t, p]
                    add!(q, 0.5, trade(m, r, v, t, p, com, s, EXP))
                end
                for v in vintages[r2, t, p]
                    add!(q, 0.5, trade(m, r2, v, t, p, com2, s, IMP))
                end
            end
            row!(m, :EQ_GG_MFLO, (r, t, p, c, r2, c2, s), GG_DENS[r, c] * G_YRFR[r, s] * 8760 * mf, ==, q)
            # --- EQ_GG_GAMA: pressure added by the compressor
            if has(GG_GAMMA, r, t, p, c)
                row!(m, :EQ_GG_GAMA, (r, t, p, c, r2, c2, s), 1.0 * VAR_GG_PADD(r, t, p, c, s), <=, (gamma - 1) * VAR_GG_PR(r, t, c, s))
            end
            # (the inputs that multiply a variable are taken as they are: one given as 0 is EPS, and the entry stays, as a
            #  zero, as in GAMS: GG_MM / GG_KGF / GG_KLP / GG_PRBD below)
            # --- EQ_GG_MBND: mass flow bounded by the pressure difference (N) and by the largest difference (FX)
            lhs = AE()
            add!(lhs, 1.0, mf)
            (r2, p, c2, r, c) in GG_WINK && add!(lhs, 1.0, gg_wslac(m, r, t, p, c, r2, c2, s))
            if lp || wtx
                rhs = AE()
                if fwd
                    d = gg_prio(m, r, t, p, c, s) - gg_prio(m, r2, t, p, c2, s)
                    back && add!(d, 1.0, VAR_GG_PDIF(r2, t, p, c2, r, c, s))
                    add!(rhs, GG_MM(r, t, p, c), d)
                end
                rev && add!(rhs, GG_MM(r, t, p, c), VAR_GG_PDIF(r, t, p, c, r2, c2, s))
                row!(m, :EQ_GG_MBND, (r, t, p, c, r2, c2, N, s), lhs, <=, rhs)
            end
            if back
                k = GG_KGF(r, t, p, c) * sqrt(gg_pdmax(m, r, t, p, c, r2, c2, 2))
                row!(m, :EQ_GG_MBND, (r, t, p, c, r2, c2, FX, s), lhs, <=, k * gg_dir(m, r, t, p, c, r2, c2, s))
            end
            # --- EQ_GG_WEYMTX: Taylor expansion of the Weymouth relation at the pressure points
            if wtx
                for j in gg_pp[r, t, p, c, UP]
                    j in OMG || continue
                    up, lo = plain(GG_PP(r, t, p, c, UP, j)), plain(GG_PP(r2, t, p, c2, LO, j))
                    den = sqrt(up^2 - lo^2)
                    outlet = gg_prio(m, r2, t, p, c2, s)
                    back && add!(outlet, -1.0, VAR_GG_PDIF(r2, t, p, c2, r, c, s))
                    rhs = GG_KGF(r, t, p, c) * (up / den * gg_prio(m, r, t, p, c, s) - lo / den * outlet)
                    row!(m, :EQ_GG_WEYMTX, (r, t, p, c, r2, c2, s, j), 1.0 * mf, <=, rhs)
                end
            end
            # --- EQ_GG_HLIP / EQ_GG_HLEV: linepack balance and level (in the direction of the grid edge)
            if arc
                pack = VAR_GG_PADD(r, t, p, ACT, s)
                if has(GG_KLP, r, t, p, c)
                    prev = isempty(ts_prev[r, s]) ? s : first(ts_prev[r, s])
                    rhs = AE()
                    add!(rhs, 1.0, VAR_GG_PADD(r, t, p, ACT, prev))
                    for (x, y) in ((r, c), (r2, c2)), ie in rpc_ire[x, p, y], v in vintages[x, t, p]
                        add!(rhs, ie == EXP ? 1.0 : -1.0, trade(m, x, v, t, p, y, s, ie))
                    end
                    row!(m, :EQ_GG_HLIP, (r, t, p, c, r2, c2, s), 1.0 * pack, ==, rhs)
                end
                k = GG_KLP(r, t, p, c) * GG_DENS(r, c) * RS_STGPRD(r, s) / 2
                row!(m, :EQ_GG_HLEV, (r, t, p, c, r2, c2, s), 1.0 * pack, ==, k * (gg_prio(m, r, t, p, c, s) + gg_prio(m, r2, t, p, c2, s)))
            end
            # --- EQ_GG_PDIF1: pressure differences bounded by the flow direction (bidirectional pipelines)
            if back
                dir = gg_dir(m, r, t, p, c, r2, c2, s)
                row!(m, :EQ_GG_PDIF1, (r, t, p, c, r2, c2, J99, s),
                     VAR_GG_PDIF(r, t, p, c, r2, c2, s) - gg_pdmax(m, r, t, p, c, r2, c2, 1) * dir, <=, 0.0)
                if !wtx
                    pru = gg_pru(m, r, t, p, c, s)
                    row!(m, :EQ_GG_PDIF1, (r, t, p, c, r2, c2, J1, s), pru - GG_PRBD(r, t, c, UP) * dir, <=, 0.0)
                    row!(m, :EQ_GG_PDIF1, (r, t, p, c, r2, c2, J2, s),
                         pru - (gg_prio(m, r, t, p, c, s) - GG_PRBD(r, t, c, LO) * (1.0 - dir)), <=, 0.0)
                end
                # --- EQ_GG_PDIF2
                if fwd
                    row!(m, :EQ_GG_PDIF2, (r, t, p, c, r2, c2, s), 1.0 * VAR_GG_PDIF(r2, t, p, c2, r, c, s), ==,
                         gg_prio(m, r2, t, p, c2, s) - gg_prio(m, r, t, p, c, s) + VAR_GG_PDIF(r, t, p, c, r2, c2, s))
                end
            end
            if wink
                ppw = gg_ppw[r, t, p, c, r2, c2]
                # --- EQ_GG_STEP: the steps of both directions add up to at most one
                if lp && arc && (r2, p, c2, r, c) in GG_WINK
                    e = AE()
                    foreach(j -> add!(e, 1.0, VAR_GG_STEP(r, t, p, c, s, j)), ppw)
                    foreach(j -> add!(e, 1.0, VAR_GG_STEP(r2, t, p, c2, s, j)), gg_ppw[r2, t, p, c2, r, c])
                    row!(m, :EQ_GG_STEP, (r, t, p, c, r2, c2, s), e, <=, 1.0)
                end
                # --- EQ_GG_PRIO: unsigned pressures of both ends
                if arc
                    both = gg_pru(m, r, t, p, c, s) + gg_pru(m, r2, t, p, c2, s)
                    slack = VAR_GG_PDIF(r, t, p, c, r, c, s)
                    row!(m, :EQ_GG_PRIO, (r, t, p, c, r2, c2, N, s), both - VAR_GG_PDIF(r2, t, p, c2, r, c, s), ==,
                         gg_prio(m, r, t, p, c, s) - slack)
                    row!(m, :EQ_GG_PRIO, (r, t, p, c, r2, c2, FX, s), both - VAR_GG_PDIF(r, t, p, c, r2, c2, s), ==,
                         gg_prio(m, r2, t, p, c2, s) - slack)
                end
                # --- EQ_GG_WEYMST: stepped Weymouth relation
                kgf = GG_KGF(r, t, p, c)
                flowsteps, dsteps, psteps = AE(), AE(), AE()
                for j in ppw
                    x = VAR_GG_STEP(r, t, p, c, s, j)
                    add!(flowsteps, kgf * GG_PPW(r, t, p, c, r2, c2, j), x)
                    add!(dsteps, plain(GG_PPM(r, t, p, c, r, c, j)) - plain(GG_PPM(r, t, p, c, r2, c2, j)), x)
                    add!(psteps, plain(GG_PPM(r, t, p, c, r, c, j)), x)
                end
                row!(m, :EQ_GG_WEYMST, (r, t, p, c, r2, c2, LO, s), 1.0 * VAR_GG_PDIF(r, t, p, c, r2, c2, s), ==, dsteps)
                row!(m, :EQ_GG_WEYMST, (r, t, p, c, r2, c2, UP, s), 1.0 * gg_pru(m, r, t, p, c, s), ==, psteps)
                row!(m, :EQ_GG_WEYMST, (r, t, p, c, r2, c2, FX, s), mf + gg_wslac(m, r, t, p, c, r2, c2, s), ==, flowsteps)
            end
        end
    end
    # the flow directions are binary in the MIP
    if m1 > 0
        for x in values(VAR_GG_Y.x)
            JuMP.set_binary(x)
            JuMP.set_upper_bound(x, 1.0)          # as GAMS reports the bounds of a binary variable
        end
    end
end
