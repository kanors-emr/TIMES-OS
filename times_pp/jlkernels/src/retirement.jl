# SPDX-License-Identifier: GPL-3.0-or-later
# The bounds of VAR_RCAP and VAR_SCAP of early retirement (prepret.dsc), as timespp/prep/capacity.py computes them in
# _retirement_bounds, statement for statement, on label codes (years too: they are only compared and looked up here).
# The Python is the reference; this agrees with it to the bit (TIMESPP_KERNELS=check:retirement).
#
# Columns in (capacity._retirement_bounds_kernel): par [py312], PASTSUM's inputs (r v p n b il), RVP (r v p), VNRET
# (r v t p, in period order), RTFORC (r v t p value), RCAP_BND (r t p l value; l 0 LO, 1 UP), MILESTONYR (in year
# order), PASTMILE, NCAP_PASTI (r v p value), the PASTMILE rows of RTP_CPTYR (r v t p), M and LEAD (y value), the
# PASTSUM rows of RTP_CPTYR (r v t p), the forced refit hosts (r p z), RTP_TT (r t t2 p), PYR_S, the RTP of the refits
# (r y p). Columns out: B_VAR_RCAP and B_VAR_SCAP, each r v t p lower upper.

const R4 = NTuple{4,Int32}

function retirement(cols::Vector{Any})
    c = ColReader(cols)
    psum = PySum(f64(c)[1] != 0)
    r, v, p, n, b, il = i32(c), i32(c), i32(c), f64(c), f64(c), f64(c)
    # --- PASTSUM(RVP(R,V,P))$RCAP_BND(RVP,'N') = -(B(V)+NCAP_ILED(RVP)+ABS(RCAP_BND(RVP,'N')));
    #     PASTSUM(RVP)$((RCAP_BND(RVP,'N')<0)+MAPVAL(RCAP_BLK(RVP))) = MAX(1,ABS(PASTSUM(RVP)));
    pastsum = Dict{T3,Float64}()
    for i in eachindex(r)
        val = -(b[i] + il[i] + abs(n[i]))
        n[i] < 0 && (val = pymax(1.0, abs(val)))
        pastsum[(r[i], v[i], p[i])] = val
    end
    a1, a2, a3 = i32(c), i32(c), i32(c)
    rvp = Set{T3}(zip(a1, a2, a3))
    a1, a2, a3, a4 = i32(c), i32(c), i32(c), i32(c)
    vnret = Dict{T3,Vector{Int32}}()                     # (r,v,p) -> [t..] in period order
    for i in eachindex(a1)
        push!(get!(() -> Int32[], vnret, (a1[i], a2[i], a4[i])), a3[i])
    end
    a1, a2, a3, a4, x = i32(c), i32(c), i32(c), i32(c), f64(c)
    forc = Dict{R4,Float64}()
    for i in eachindex(a1)
        forc[(a1[i], a2[i], a3[i], a4[i])] = x[i]
    end
    a1, a2, a3, a4, x = i32(c), i32(c), i32(c), i32(c), f64(c)
    bnd = Dict{R4,Float64}()                             # (r, t, p, l): l 0 LO, 1 UP
    for i in eachindex(a1)
        bnd[(a1[i], a2[i], a3[i], a4[i])] = x[i]
    end
    mile = i32(c)
    pastmile = Set{Int32}(i32(c))
    a1, a2, a3, x = i32(c), i32(c), i32(c), f64(c)
    pasti = Dict{T3,Float64}()
    for i in eachindex(a1)
        pasti[(a1[i], a2[i], a3[i])] = x[i]
    end
    sq = (i32(c), i32(c), i32(c), i32(c))
    a1, x = i32(c), f64(c)
    M = Dict{Int32,Float64}(zip(a1, x))
    a1, x = i32(c), f64(c)
    LEAD = Dict{Int32,Float64}(zip(a1, x))
    pq = (i32(c), i32(c), i32(c), i32(c))
    fr, fp, fz = i32(c), i32(c), f64(c)
    a1, a2, a3, a4 = i32(c), i32(c), i32(c), i32(c)
    rtt = Set{R4}(zip(a1, a2, a3, a4))
    pyr_s = i32(c)
    a1, a2, a3 = i32(c), i32(c), i32(c)
    rtp = Set{T3}(zip(a1, a2, a3))

    NONE = Int32(-1)
    prev = Dict{Int32,Int32}(t => (i > 1 ? mile[i-1] : NONE) for (i, t) in enumerate(mile))
    rlo, rup, slo, sup = Dict{R4,Float64}(), Dict{R4,Float64}(), Dict{R4,Float64}(), Dict{R4,Float64}()
    # --- LOOP(TT(T--1),Z=ORD(T)-1;
    #       VAR_RCAP.LO(VNRET(V,T,P))$RVP(R,V,P) = RCAP_BND(R,T,P,'LO')$(NOT MAPVAL(RCAP_BLK(R,V,P)))+MIN(0,RTFORC(R,V,T,P)-RTFORC(R,V,TT,P)$Z);
    #       VAR_RCAP.UP(VNRET(V,T,P))$RCAP_BND(R,T,P,'UP') =
    #         MIN(SMIN(PASTMILE(V),NCAP_PASTI(R,V,P)),RCAP_BND(R,T,P,'UP')+MAX(0,RTFORC(R,V,T,P)-RTFORC(R,V,TT,P)$Z)));
    for ((r, v, p), ts) in vnret, t in ts
        pt = get(prev, t, nothing)
        pt === nothing && continue
        d = get(forc, (r, v, t, p), 0.0) - (pt != NONE ? get(forc, (r, v, pt, p), 0.0) : 0.0)
        if (r, v, p) in rvp
            rlo[(r, v, t, p)] = get(bnd, (r, t, p, Int32(0)), 0.0) + pymin(0.0, d)
        end
        up = get(bnd, (r, t, p, Int32(1)), nothing)
        if up !== nothing
            rup[(r, v, t, p)] = pymin(v in pastmile ? get(pasti, (r, v, p), 0.0) : Inf, up + pymax(0.0, d))
        end
    end
    # --- VAR_SCAP.LO(VNRET(V,T,P))$RVP(R,V,P) = MAX(RCAP_BND(R,T,P,'LO'),RTFORC(R,V,T,P));
    # --- VAR_SCAP.UP(RTP_CPTYR(R,PASTMILE(V),T,P))$RVP(R,V,P) = MAX(RTFORC(R,V,T,P),NCAP_PASTI(R,V,P));
    for (r, v, p) in rvp, t in get(vnret, (r, v, p), Int32[])
        slo[(r, v, t, p)] = pymax(get(bnd, (r, t, p, Int32(0)), 0.0), get(forc, (r, v, t, p), 0.0))
    end
    for i in eachindex(sq[1])
        r, v, t, p = sq[1][i], sq[2][i], sq[3][i], sq[4][i]
        (r, v, p) in rvp && (sup[(r, v, t, p)] = pymax(get(forc, (r, v, t, p), 0.0), get(pasti, (r, v, p), 0.0)))
    end
    # --- LOOP(RVP(R,V,P),Z=1;LOOP(VNRET(V,T,P)$Z,Z=0; VAR_SCAP.UP(R,V,T,P)=MIN(VAR_RCAP.UP(R,V,T,P),VAR_SCAP.UP(R,V,T,P))));
    for (r, v, p) in rvp
        ts = get(vnret, (r, v, p), nothing)
        if ts !== nothing && !isempty(ts)
            kk = (r, v, ts[1], p)
            sup[kk] = pymin(get(rup, kk, Inf), get(sup, kk, Inf))
        end
    end
    # --- VAR_SCAP.FX(RTP_CPTYR(R,V,T,P))$(((M(T) < ABS(PASTSUM(R,V,P)))+((M(T)-LEAD(T))/PASTSUM(R,V,P) >= 1))$PASTSUM(R,V,P)) = RTFORC(R,V,T,P);
    for i in eachindex(pq[1])
        r, v, t, p = pq[1][i], pq[2][i], pq[3][i], pq[4][i]
        ps = get(pastsum, (r, v, p), 0.0)
        if ps != 0 && (need(M, t) < abs(ps) || (need(M, t) - need(LEAD, t)) / ps >= 1)
            slo[(r, v, t, p)] = sup[(r, v, t, p)] = get(forc, (r, v, t, p), 0.0)
        end
    end
    # --- VAR_RCAP.UP(RTP_TT(R,T(TT++1),T,P))$((RP_RTF(R,P)<3)$PRC_YMAX(R,P)) = ...       forced refits: all refit codes >= 3
    #     (T(TT++1): t follows tt, circularly; the bound is 0 but for an even RP_RTF)
    for i in eachindex(fr)
        r, p, z = fr[i], fp[i], fz[i]
        z < 3 || continue
        for (j, t) in enumerate(mile)
            (r, t, t, p) in rtt || continue
            tt = mile[j > 1 ? j - 1 : length(mile)]
            val = 0.0
            if j > 1 && mod(z, 2) == 0
                length(pyr_s) > 1 && throw(Decline("PYR_S with more than one year (the reference sums over a Python set)"))
                val = pymax(0.0, psum(get(forc, (r, vv, t, p), 0.0) - get(forc, (r, vv, tt, p), 0.0) for vv in pyr_s if (r, vv, p) in rtp))
            end
            rup[(r, t, t, p)] = val
        end
    end
    # the rows of B_VAR_RCAP and B_VAR_SCAP: the keys with a bound other than the default (0 .. INF)
    res = Any[]
    for (lo, up) in ((rlo, rup), (slo, sup))
        ks = R4[k for k in union(Set{R4}(keys(lo)), keys(up)) if get(lo, k, 0.0) != 0.0 || get(up, k, Inf) != Inf]
        for j in 1:4
            push!(res, Int32[k[j] for k in ks])
        end
        push!(res, Float64[get(lo, k, 0.0) for k in ks])
        push!(res, Float64[get(up, k, Inf) for k in ks])
    end
    res
end

"""The columns of a small made-up model for the precompile workload: two vintages retiring over three periods, with
forced RTFORC, a PASTSUM and a forced refit."""
function retirement_example()
    i = Int32
    Any[[0.0],
        i[0], i[10], i[20], [-5.0], [2000.0], [0.0],                        # PASTSUM's inputs
        i[0, 0], i[10, 11], i[20, 20],                                      # RVP
        i[0, 0, 0, 0], i[10, 10, 11, 11], i[12, 13, 12, 13], i[20, 20, 20, 20],      # VNRET
        i[0], i[10], i[13], i[20], [3.0],                                   # RTFORC
        i[0, 0, 0], i[12, 13, 13], i[20, 20, 20], i[0, 1, 1], [1.0, 5.0, 4.0],      # RCAP_BND
        i[11, 12, 13], i[10],                                               # MILESTONYR, PASTMILE
        i[0], i[10], i[20], [7.0],                                          # NCAP_PASTI
        i[0, 0], i[10, 10], i[12, 13], i[20, 20],                           # RTP_CPTYR of PASTMILE
        i[11, 12, 13], [2005.0, 2010.0, 2020.0], i[11, 12, 13], [1.0, 1.0, 2.0],    # M, LEAD
        i[0], i[10], i[12], i[20],                                          # RTP_CPTYR of PASTSUM
        i[0], i[21], [2.0],                                                 # forced refit hosts
        i[0, 0], i[12, 13], i[12, 13], i[21, 21],                           # RTP_TT
        i[10],                                                              # PYR_S
        i[0], i[10], i[21]]                                                 # RTP of the refits
end
