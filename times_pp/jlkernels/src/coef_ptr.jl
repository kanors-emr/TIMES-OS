# SPDX-License-Identifier: GPL-3.0-or-later
# coef_ptr.mod: COEF_PTRAN from FLO_FUNC / FLO_SUM, as coefficients.coef_ptr (timespp/prep/coefficients.py) does it,
# statement for statement, on label codes; its inputs come through kernels.to_julia.
#
# Columns in (coefficients._coef_ptr_kernel): every label as a code (kernels.Labels), the tables in this order
#   FLO_SUM r y p cg c cg2 s value | FLO_FUNC r y p cg cg2 s value | RPC r p c | RTP r y p | MODLYEAR y | COM c |
#   COM_GMAP r cg c | PRC_TSL r p tsl | TS_GROUP r tsl s | TS_MAP r s s2 | RPCS_VAR r p c s | RPCC_FFUNC r p cg cg2 |
#   PRC_CG r p cg | RC r c | rank (Int32 per code: the rank of the label in DuckDB's VARCHAR order)
# Columns out: COEF_PTRAN r y p cg c cg2 s value (both statements' rows, written to the empty table), RPCC_FFUNC
# r p cg cg2 (the whole set after the statement), PRC_CG r p cg (the records added).

const I32 = Vector{Int32}
const T2 = NTuple{2,Int32}; const T3 = NTuple{3,Int32}; const T4 = NTuple{4,Int32}
const T5 = NTuple{5,Int32}; const T6 = NTuple{6,Int32}; const T7 = NTuple{7,Int32}

"""Rows grouped by their first N key columns: each row's codes and its row number packed into one UInt128 and sorted;
a group is a run of equal codes, found by binary search on the packed codes."""
struct Grouped{N}
    p::Vector{Int}                     # row numbers in group order
    packed::Vector{UInt128}            # the codes of each group, packed, ascending
    keys::Vector{NTuple{N,Int32}}
    starts::Vector{Int}                # group i: p[starts[i]:starts[i+1]-1]
    bits::NTuple{N,Int}                # the bits of each key column
end
colbits(c::I32) = isempty(c) ? 1 : max(1, 64 - leading_zeros(UInt64(maximum(c)) + 1))
function pack(k::NTuple{N,Int32}, b::NTuple{N,Int}) where {N}
    x = UInt128(0)
    for j in 1:N
        x = (x << b[j]) | UInt128(k[j])
    end
    x
end
function groups(cols::Vector{I32}, ::Val{N}) where {N}
    n = length(cols[1])
    b = ntuple(j -> colbits(cols[j]), Val(N)); rb = max(1, 64 - leading_zeros(UInt64(max(n, 1))))
    sum(b) + rb <= 128 || throw(Decline("the codes of $N columns and the row number do not pack into 128 bits"))
    v = Vector{UInt128}(undef, n)
    pfor(1:n) do i
        x = UInt128(0)
        for j in 1:N
            x = (x << b[j]) | UInt128(cols[j][i])
        end
        v[i] = (x << rb) | UInt128(i)
    end
    sort!(v)
    mask = (UInt128(1) << rb) - 1
    p = Vector{Int}(undef, n)
    packed = UInt128[]; starts = Int[]
    for i in 1:n
        p[i] = Int(v[i] & mask)
        kx = v[i] >> rb
        if i == 1 || kx != packed[end]
            push!(packed, kx); push!(starts, i)
        end
    end
    push!(starts, n + 1)
    keys = [ntuple(j -> cols[j][p[starts[g]]], Val(N)) for g in 1:length(packed)]
    Grouped{N}(p, packed, keys, starts, b)
end
function Base.get(g::Grouped{N}, k::NTuple{N,Int32}, default) where {N}
    any(j -> k[j] >= (Int32(1) << g.bits[j]), 1:N) && return default     # a code no row of the table has
    x = pack(k, g.bits)
    i = searchsortedfirst(g.packed, x)
    (i <= length(g.packed) && g.packed[i] == x) ? (g.starts[i]:g.starts[i+1]-1) : default
end
Base.haskey(g::Grouped{N}, k::NTuple{N,Int32}) where {N} = get(g, k, nothing) !== nothing
grange(g::Grouped, i) = g.starts[i]:g.starts[i+1]-1

function multimap(::Type{K}, keys, vals) where {K}
    d = Dict{K,Vector{Int32}}()
    for (k, v) in zip(keys, vals)
        push!(get!(() -> Int32[], d, k), v)
    end
    d
end

function coef_ptr(cols::Vector{Any})
    c = Iterators.Stateful(cols)
    take(n) = I32[popfirst!(c)::I32 for _ in 1:n]
    fs = take(7); fsv = popfirst!(c)::Vector{Float64}
    ff = take(6); ffv = popfirst!(c)::Vector{Float64}
    rpc, rtp, modl, com, gm, tsl, tg, tm, rv, rpcc0, pc, rc = take(3), take(3), take(1), take(1), take(3), take(3),
        take(3), take(3), take(4), take(4), take(3), take(2)
    rank = popfirst!(c)::I32
    coef_ptr_kernel(fs, fsv, ff, ffv, rpc, rtp, modl[1], com[1], gm, tsl, tg, tm, rv, rpcc0, pc, rc, rank)
end

function coef_ptr_kernel(fs, fsv, ff, ffv, rpc, rtp, modl, com, gm, tsl, tg, tm, rv, rpcc0, pc, rc, rank)
    n = length(rank)                                          # the number of codes
    RPC = Set{T3}(zip(rpc...)); RTP = Set{T3}(zip(rtp...))
    MODLYEAR = falses(n); MODLYEAR[modl .+ 1] .= true
    COM = falses(n); COM[com .+ 1] .= true
    GMAP = multimap(T2, zip(gm[1], gm[2]), gm[3])
    fsg = groups(fs, Val(6)); fsp = fsg.p                     # FLO_SUM by (r,y,p,cg,c,cg2): its timeslices
    ffg = groups(ff, Val(5)); ffp = ffg.p                     # FLO_FUNC by (r,y,p,cg,cg2)
    fss, ffs = fs[7], ff[6]
    # --- OPTION CGTEST <= FLO_SUM; CGTEST(R,V,P,COM_GRP,C,CG)$(NOT RPC(R,P,C)) = NO;
    ttest = T6[k for k in fsg.keys if (k[1], k[3], k[5]) in RPC]
    # --- LOOP((CGTEST(R,V,P,COM_GRP,C,CG),S)$FLO_FUNC(R,V,P,CG,COM_GRP,S),CG_GRP(R,P,COM_GRP,CG) = YES);
    grp = Set{T4}()
    for k in ttest
        MODLYEAR[k[2]+1] && haskey(ffg, (k[1], k[2], k[3], k[6], k[4])) && push!(grp, (k[1], k[3], k[4], k[6]))
    end
    grp_rp = Dict{T2,Vector{T2}}()
    for g in grp
        push!(get!(() -> T2[], grp_rp, (g[1], g[2])), (g[3], g[4]))
    end
    # --- CGTES2(RTP(R,V,P),COM_GRP,C,CG)$((COM_GMAP(R,COM_GRP,C)*RPC(R,P,C))$CG_GRP(R,P,COM_GRP,CG)) = YES;
    tes2 = T6[]; tes2set = Set{T6}()
    for i in eachindex(rtp[1])
        r, y, p = rtp[1][i], rtp[2][i], rtp[3][i]
        gs = get(grp_rp, (r, p), nothing); gs === nothing && continue
        for (cg, cg2) in gs, cc in get(GMAP, (r, cg), Int32[])
            (r, p, cc) in RPC && (t = (r, y, p, cg, cc, cg2); push!(tes2, t); push!(tes2set, t))
        end
    end
    # --- OPTION CG_GRP <= FLO_FUNC;
    #     CGTES2(RTP(R,V,P),COM_GRP,C,CG)$(COM_GMAP(R,COM_GRP,C)$RPC(R,P,C)$CG_GRP(R,P,COM_GRP,CG)) $= SUM(S$FLO_FUNC(RTP,COM_GRP,CG,S),1);
    for k in ffg.keys
        r, y, p, cg, cg2 = k
        (r, y, p) in RTP || continue
        for cc in get(GMAP, (r, cg), Int32[])
            t = (r, y, p, cg, cc, cg2)
            (r, p, cc) in RPC && !(t in tes2set) && (push!(tes2, t); push!(tes2set, t))
        end
    end
    # --- CGTES2(CGTEST(RTP,C,COM,CG)) $= CGTES2(RTP,C,C,CG);
    #     (an inserted row has c <> cg, so it cannot satisfy the test of another: one pass is the statement)
    add = T6[k for k in ttest if (k[1], k[2], k[3]) in RTP && COM[k[4]+1] &&
             (k[1], k[2], k[3], k[4], k[4], k[6]) in tes2set && !(k in tes2set)]
    for k in add
        push!(tes2, k); push!(tes2set, k)
    end
    # --- OPTION CG_GRP <= CGTEST;
    grp2 = Set{T4}((k[1], k[3], k[4], k[6]) for k in ttest)
    # the timeslices as a dense index for the per-row work
    tsx = zeros(Int32, n); tsn = Int32(0)
    for x in (tg[3], tm[2], tm[3], rv[4], fss, ffs), s in x
        tsx[s+1] == 0 && (tsn += 1; tsx[s+1] = tsn)
    end
    TSMAP = Dict{Int32,BitMatrix}()                           # region -> TS_MAP(r, s, s2) as a matrix
    for i in eachindex(tm[1])
        m = get!(() -> falses(tsn, tsn), TSMAP, tm[1][i])
        m[tsx[tm[2][i]+1], tsx[tm[3][i]+1]] = true
    end
    TSG = multimap(T2, zip(tg[1], tg[2]), tg[3])
    PTSL = multimap(T2, zip(tsl[1], tsl[2]), tsl[3])
    # the timeslices g.s summed over for (r,p): PRC_TSL l join TS_GROUP g, in the order of `order by g.s`
    GS = Dict{T2,Vector{Int32}}()
    for (rp, ls) in PTSL
        v = Int32[]
        for l in ls
            append!(v, get(TSG, (rp[1], l), Int32[]))
        end
        sort!(v; by = s -> rank[s+1])
        GS[rp] = v
    end
    RV = multimap(T3, zip(rv[1], rv[2], rv[3]), rv[4])
    empty3 = Int32[]
    # --- COEF_PTRAN(CGTES2(R,V,P,COM_GRP,C,CG),S)$((YES$FLO_SUM(CGTES2,S)+(NOT CG_GRP(R,P,CG,COM_GRP)))$RPCS_VAR(R,P,C,S)) =
    #       SUM((PRC_TSL(R,P,TSL),TS_GROUP(R,TSL,TS))$TS_MAP(R,TS,S),
    #         ((1+(1/FLO_FUNC(R,V,P,CG,COM_GRP,TS)-1)$FLO_FUNC(R,V,P,CG,COM_GRP,TS))$(NOT FLO_FUNC(R,V,P,COM_GRP,CG,TS)) +
    #          FLO_FUNC(R,V,P,COM_GRP,CG,TS)) * (1$(NOT FLO_SUM(CGTES2,S)) + FLO_SUM(CGTES2,S)));
    #     (put, '=': a zero result is no record, but one with a term from a forward FLO_FUNC or a FLO_SUM given as 0 is EPS;
    #      the sum in the order of g.s, as the SQL orders it)
    nt = Threads.nthreads()
    chunks = collect(Iterators.partition(1:length(tes2), max(1, cld(length(tes2), 4nt))))
    parts = Vector{Tuple{Vector{T7},Vector{Float64}}}(undef, length(chunks))
    pfor(eachindex(chunks)) do ci
        ok = Vector{T7}(); ov = Float64[]
        has1 = falses(tsn); v1 = zeros(tsn); has2 = falses(tsn); v2 = zeros(tsn)
        for i in chunks[ci]
            r, y, p, cg, cc, cg2 = k = tes2[i]
            ss = get(RV, (r, p, cc), empty3); isempty(ss) && continue
            gl = get(GS, (r, p), empty3)
            tm_r = get(TSMAP, r, nothing)
            f1 = get(ffg, (r, y, p, cg, cg2), 1:0); f2 = get(ffg, (r, y, p, cg2, cg), 1:0)
            for j in f1; s = tsx[ffs[ffp[j]]+1]; has1[s] = true; v1[s] = ffv[ffp[j]]; end
            for j in f2; s = tsx[ffs[ffp[j]]+1]; has2[s] = true; v2[s] = ffv[ffp[j]]; end
            fr = get(fsg, k, 1:0)
            nogrp = !((r, p, cg2, cg) in grp2)
            for s in ss
                hasfs = false; b = 1.0                        # in_FLO_SUM(k, v.s) / v_FLO_SUM
                for j in fr
                    if fss[fsp[j]] == s
                        hasfs = true; b = fsv[fsp[j]]; break
                    end
                end
                (hasfs || nogrp) || continue
                tm_r === nothing && continue
                xs = tsx[s+1]
                acc = 0.0; hit = false; eps = false
                for gs in gl
                    g = tsx[gs+1]
                    tm_r[g, xs] || continue
                    a = has1[g] ? 0.0 : has2[g] ? 1 / v2[g] : 1.0
                    acc += (a + (has1[g] ? v1[g] : 0.0)) * b
                    eps |= (has1[g] && v1[g] == 0) || (hasfs && b == 0)
                    hit = true
                end
                if hit && (acc != 0 || isnan(acc) || eps)
                    push!(ok, (r, y, p, cg, cc, cg2, s)); push!(ov, acc)
                end
            end
            for j in f1; has1[tsx[ffs[ffp[j]]+1]] = false; end
            for j in f2; has2[tsx[ffs[ffp[j]]+1]] = false; end
        end
        parts[ci] = (ok, ov)
    end
    # --- COEF_PTRAN(CGTEST(R,V,P,CG,C,CG2),S)$((NOT CGTES2(CGTEST))$RPCS_VAR(R,P,C,S)) $= FLO_SUM(CGTEST,S);
    #     (put with EPS rows: a zero is kept)
    gch = collect(Iterators.partition(eachindex(fsg.keys), max(1, cld(length(fsg.keys), 4nt))))
    parts2 = Vector{Tuple{Vector{T7},Vector{Float64}}}(undef, length(gch))
    pfor(eachindex(gch)) do ci
        ok = Vector{T7}(); ov = Float64[]
        for gi in gch[ci]
            k = fsg.keys[gi]
            r, y, p, cg, cc, cg2 = k
            ((r, p, cc) in RPC && !(k in tes2set)) || continue
            ss = get(RV, (r, p, cc), empty3)
            for j in grange(fsg, gi)
                s = fss[fsp[j]]
                if s in ss
                    push!(ok, (r, y, p, cg, cc, cg2, s)); push!(ov, fsv[fsp[j]])
                end
            end
        end
        parts2[ci] = (ok, ov)
    end
    allp = vcat(parts, parts2)
    off = cumsum([0; [length(x[2]) for x in allp]])
    ccols = [Vector{Int32}(undef, off[end]) for _ in 1:7]; cv = Vector{Float64}(undef, off[end])
    pfor(eachindex(allp)) do q
        ks, vs = allp[q]
        for (i, k) in enumerate(ks)
            o = off[q] + i
            for j in 1:7
                ccols[j][o] = k[j]
            end
            cv[o] = vs[i]
        end
    end
    # --- CGTEST(CGTES2) = YES;  OPTION CG_GRP <= CGTEST;  CG_GRP(RPCC_FFUNC) = NO;  OPTION RPCC_FFUNC <= CG_GRP;
    rpccs = Set{T4}(zip(rpcc0...))
    g3 = Set{T4}((k[1], k[3], k[4], k[6]) for k in ttest)
    for k in tes2
        push!(g3, (k[1], k[3], k[4], k[6]))
    end
    g3 = T4[g for g in g3 if !(g in rpccs)]
    # --- OPTION RP_GRP <= CG_GRP; PRC_CG(RP_GRP)=YES; OPTION RP_GRP < CG_GRP; PRC_CG(RP_GRP)=YES;
    pcs = Set{T3}(zip(pc...))
    newpc = T3[]
    for g in g3, x in ((g[1], g[2], g[3]), (g[1], g[2], g[4]))
        x in pcs || (push!(pcs, x); push!(newpc, x))
    end
    # --- RPCC_FFUNC(R,P,CG,C)$(RC(R,C)$(NOT RPC(R,P,C))) = NO;
    RC = Set{T2}(zip(rc...))
    g3 = T4[g for g in g3 if !((g[1], g[4]) in RC && !((g[1], g[2], g[4]) in RPC))]
    Any[ccols..., cv, (Int32[g[j] for g in g3] for j in 1:4)..., (Int32[x[j] for x in newpc] for j in 1:3)...]
end
