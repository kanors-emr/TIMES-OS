# SPDX-License-Identifier: GPL-3.0-or-later
# DC power flow of the grid extension by transfer factors (powerflo.vda POWFLO): EQ_GR_PTDFLO, the virtual
# flows of candidate lines (EQ_GR_VIRTCAP, EQ_GR_VIRTBND) and the N-1 bound EQ_GR_XBND (lines within a region;
# the preprocessor stops on lines between regions), and the phase-angle form EQ_GR_POWFLO (line reactances PRC_REACT).

const GR_BIGM = 10.0          # %BIGM%

"""Virtual flow over candidate line p (VAR_GRVIRT): the export of ACT by p, a free variable."""
gr_virt(m::Model, r, t, p, s) = m.v.VAR_IRE(r, t, t, p, m.K.ACT, s, m.K.EXP)

"""
    EQ_GR_PTDFLO(r,t,p,c,s)                                                      powerflo.vda

Flow over line p, out of its node c (GR_FLOW(r,p,c) > 0), in the timeslices of the process:

    SUM(v, ts flow timeslice with RS_FR(s,ts), RS_FR(s,ts) * SUM(ie, VAR_IRE(r,v,t,p,c,s,ie) * (+1 EXP, -1 IMP)))
      [+ VAR_GRVIRT(r,t,p,s), candidate line]
      =  SUM(node com with COM_TS(com,s), GR_PTDF(r,t,p,c,r2,com) * VAR_COMAUX(r2,t,com,s))
"""
function eq_gr_ptdflo!(m::Model)
    (; RP_GRID, GR_FLOW, GR_PTDF, GR_CANDID, RC_GRID, RPC_IRE, RS_FR, COM_TS) = m.d
    isempty(RP_GRID) && return
    (; rps_s1, vintages, flow_s, ts_frac) = m.ix
    (; VAR_IRE, VAR_COMAUX) = m.v
    (; IMP, EXP) = m.K
    ptdf = Dict{NTuple{4,Id},Vector{Tuple{Id,Id,Float64}}}()      # (r,t,p,c) -> (r2, com, factor)
    for ((r, t, p, c, r2, com), x) in GR_PTDF
        push!(get!(ptdf, (r, t, p, c), Tuple{Id,Id,Float64}[]), (r2, com, plain(x)))
    end
    for ((r, p, c), f) in GR_FLOW
        plain(f) > 0 && (r, p) in RP_GRID || continue
        for t in m.T, s in rps_s1[r, p]
            lhs = AE()
            for v in vintages[r, t, p]
                k = sum((plain(RS_FR(r, s, ts)) for ts in onbranch(flow_s[r, t, p, c], ts_frac[r, s]) if !iszero(RS_FR(r, s, ts))); init = 0.0)
                iszero(k) && continue
                for ie in (IMP, EXP)
                    (r, p, c, ie) in RPC_IRE && add!(lhs, ie == EXP ? k : -k, VAR_IRE(r, v, t, p, c, s, ie))
                end
            end
            (r, t, p) in GR_CANDID && (r, t, c) in RC_GRID && add!(lhs, 1.0, gr_virt(m, r, t, p, s))
            rhs = AE()
            for (r2, com, x) in get(ptdf, (r, t, p, c), ())
                (r2, t, com) in RC_GRID && (r2, com, s) in COM_TS && add!(rhs, x, VAR_COMAUX(r2, t, com, s))
            end
            row!(m, :EQ_GR_PTDFLO, (r, t, p, c, s), lhs, EQ, rhs)
        end
    end
end

"""
    EQ_GR_VIRTCAP(r,t,p,c,s,bd) / EQ_GR_VIRTBND(r,t,p)                          powerflo.vda

The virtual flow over a candidate line is bounded by its virtual capacity in both directions (BDSIG: LO +1,
UP -1), and the virtual capacity is BIGM * GR_CAPUP * (1 - VAR_CAP/GR_CAPUP) / BIGM: what is left of the
largest capacity once the line is built.

    n(c) * VAR_GRVIRT(r,t,p,s) * BDSIG(bd)  <=  VAR_XCAP(r,t,p) * PRC_CAPACT(r,p) * G_YRFR(r,s)     n(c): lines (r,c,..,p) of GR_TOP
    VAR_XCAP(r,t,p)  =  BIGM * GR_CAPUP * (1 - (1 - (1 - VAR_CAP(r,t,p) / GR_CAPUP) / BIGM))
"""
function eq_gr_virt!(m::Model)
    (; GR_CANDID, GR_FLOW, GR_TOP, GR_CAPUP, PRC_CAPACT, G_YRFR, RTP) = m.d
    isempty(GR_CANDID) && return
    (; rps_s1) = m.ix
    (; VAR_XCAP, VAR_CAP) = m.v
    (; LO, UP) = m.K
    ntop = Dict{NTuple{3,Id},Int}()
    for (r, c, r2, c2, p) in GR_TOP
        ntop[(r, p, c)] = get(ntop, (r, p, c), 0) + 1
    end
    for (r, t, p) in GR_CANDID
        t in m.sub || continue
        for ((r1, p1, c), f) in GR_FLOW
            (r1 == r && p1 == p && plain(f) > 0) || continue
            n = get(ntop, (r, p, c), 0)
            for s in rps_s1[r, p], (bd, sg) in ((LO, 1.0), (UP, -1.0))
                lhs = AE()
                n > 0 && add!(lhs, n * sg, gr_virt(m, r, t, p, s))
                rhs = AE()
                add!(rhs, plain(PRC_CAPACT(r, p)) * plain(G_YRFR(r, s)), VAR_XCAP(r, t, p))
                row!(m, :EQ_GR_VIRTCAP, (r, t, p, c, s, bd), lhs, LE, rhs)
            end
        end
        u = plain(GR_CAPUP(r, t, p))
        rhs = AE()
        # BIGM*U*(1 - ((1 - CAP/U)/BIGM)), as GAMS evaluates it: constant U, coefficient -1 of VAR_CAP
        if (r, t, p) in RTP
            add!(rhs, GR_BIGM * u * (1 - (1 - 1 / GR_BIGM)), 1.0)
            add!(rhs, -GR_BIGM * u * (1 / u / GR_BIGM), VAR_CAP(r, t, p))
        else
            add!(rhs, GR_BIGM * u * (1 - (1 - 1 / GR_BIGM)), 1.0)
        end
        row!(m, :EQ_GR_VIRTBND, (r, t, p), 1.0 * VAR_XCAP(r, t, p), EQ, rhs)
    end
end

"""
    EQ_GR_XBND(r,t,j,ie,s)                                                       powerflo.vda

Simplified N-1 security bound on the net imports (ie = IMP) or exports (EXP) of grid j in a finest timeslice:

    SUM(node c of j, commodity com taking demand at c, (-1 for EXP) *
        (VAR_GRIDIO(r,t,com,c,s,IN) [allocation by group NRG] - VAR_GRIDIO(r,t,com,c,s,OUT)))
      <=  GR_XBND(r,t) * capacity of the lines between j and other regions (none here: such lines stop the run)
"""
function eq_gr_xbnd!(m::Model)
    (; GR_XBND, GR_GRID, GR_DEMMAP, GR_ALGMAP, RTC, RC_GRID, FINEST) = m.d
    isempty(GR_XBND) && return
    (; gr_dem_of) = m.ix
    (; VAR_GRIDIO) = m.v
    (; IMP, EXP, IN, OUT, NRG, ACT) = m.K
    for (j, r, a) in GR_GRID
        a == ACT || continue
        for t in m.T
            t in m.sub || continue
            has(GR_XBND, r, t) || continue
            iszero(GR_XBND(r, t)) && !iseps(GR_XBND(r, t)) && continue
            for (r1, s) in FINEST, ie in (IMP, EXP)
                r1 == r || continue
                sg = ie == EXP ? -1.0 : 1.0
                lhs = AE()
                for (j2, r2, c) in GR_GRID
                    (j2 == j && r2 == r && (r, t, c) in RC_GRID) || continue
                    for com in gr_dem_of[r, c]
                        (r, t, com) in RTC || continue
                        (r, NRG, com) in GR_ALGMAP && add!(lhs, sg, VAR_GRIDIO(r, t, com, c, s, IN))
                        add!(lhs, -sg, VAR_GRIDIO(r, t, com, c, s, OUT))
                    end
                end
                row!(m, :EQ_GR_XBND, (r, t, j, ie, s), lhs, LE, 0.0)
            end
        end
    end
end

"""
    EQ_GR_POWFLO(r,t,c,s,r2,c2)                                                  powerflo.vda (POWFLO)

DC power flow by phase angles: for each arc (c of r to c2 of r2) with an admittance GR_ADMIT (the sum of
1 / PRC_REACT over its lines that have a reactance and are available in t), in every timeslice s of node c
(RTCS_VARC of a node in RC_GRID), the flow into r2 over those lines equals the admittance times the angle
difference. VAR_COMAUX is the phase angle (free; one node of each disjoint grid fixed at 0, powerflo.vda DECL).

    SUM(p in GR_TOP(r,c,r2,c2,p) with PRC_REACT(r,t,p), v, s in RTPCS_VARF(r2,t,p,c2,s),
        SUM(ie in RPC_IRE(r2,p,c2), VAR_IRE(r2,v,t,p,c2,s,ie) * (+1 IMP, -1 EXP)))
      =  (VAR_COMAUX(r,t,c,s) - VAR_COMAUX(r2,t,c2,s)) * GR_ADMIT(r,t,c,r2,c2)
"""
function eq_gr_powflo!(m::Model)
    (; GR_ADMIT, GR_TOP, PRC_REACT, RC_GRID, RTPCS_VARF, RPC_IRE) = m.d
    isempty(GR_ADMIT) && return
    (; varc_ts, vintages) = m.ix
    (; VAR_IRE, VAR_COMAUX) = m.v
    (; IMP, EXP) = m.K
    lines = Dict{NTuple{4,Id},Vector{Id}}()                          # (r,c,r2,c2) -> lines p
    for (r, c, r2, c2, p) in GR_TOP
        push!(get!(lines, (r, c, r2, c2), Id[]), p)
    end
    for ((r, t, c, r2, c2), admit) in GR_ADMIT
        (r, t, c) in RC_GRID || continue
        (m.stepped && !(t in m.sub)) && continue
        for s in varc_ts[r, t, c]
            lhs = AE()
            for p in get(lines, (r, c, r2, c2), ())
                iszero(plain(PRC_REACT(r, t, p))) && continue
                (r2, t, p, c2, s) in RTPCS_VARF || continue
                for v in vintages[r2, t, p], ie in (IMP, EXP)
                    (r2, p, c2, ie) in RPC_IRE && add!(lhs, ie == EXP ? -1.0 : 1.0, VAR_IRE(r2, v, t, p, c2, s, ie))
                end
            end
            a = plain(admit)
            rhs = AE()
            add!(rhs, a, VAR_COMAUX(r, t, c, s))
            add!(rhs, -a, VAR_COMAUX(r2, t, c2, s))
            row!(m, :EQ_GR_POWFLO, (r, t, c, s, r2, c2), lhs, EQ, rhs)
        end
    end
end
