# SPDX-License-Identifier: GPL-3.0-or-later
# fillcost.gms: cost series over the years of FIL, interpolated between data years and extrapolated outside them, as
# costs.fillcost (timespp/prep/costs.py) does it, statement for statement, so that the result is the same to the bit.
# costs._fillcost_kernel prepares the columns (labels as codes; only the records on DM_YEAR, which are the only ones
# that count) and writes the result with fillcost's put (EPS rows kept).
#
# Columns in:
#   1  Float64 [nk, mode2, bext, fext, ri, pi]   nk key columns; mode2: the data years kept as they are (OB_X);
#                                                bext / fext: extrapolation limited to PRC_YMIN / PRC_YMAX, the
#                                                ranges of t_yrng by (key[ri], key[pi])
#   2 .. 1+nk  Int32 key codes;  then Int32 year;  Float64 value (an EPS or NULL already 1e-300, as fillcost carries it)
#   then  Int32 the years of FIL, in order;  then t_yrng: Int32 r, Int32 p, Float64 lo, Float64 hi
# Columns out: nk key columns, year, value (a value of at most 1e-200 made 0, the EPS row).

function fillcost(cols::Vector{Any})
    par = cols[1]::Vector{Float64}
    nk = Int(par[1])
    keys = Vector{Int32}[cols[1+i]::Vector{Int32} for i in 1:nk]
    yr = cols[2+nk]::Vector{Int32}; val = cols[3+nk]::Vector{Float64}
    years = cols[4+nk]::Vector{Int32}
    rr, rp = cols[5+nk]::Vector{Int32}, cols[6+nk]::Vector{Int32}
    lo, hi = cols[7+nk]::Vector{Float64}, cols[8+nk]::Vector{Float64}
    fillcost_kernel(keys, yr, val, years, rr, rp, lo, hi, par[2] != 0, par[3] != 0, par[4] != 0, Int(par[5]), Int(par[6]))
end

function fillcost_kernel(keys, yr, val, years, rr, rp, lo, hi, mode2, bext, fext, ri, pi)
    n = length(val)
    ns, start, order = group_series(keys, n)
    rng = Dict{UInt64,Tuple{Float64,Float64}}()
    for i in eachindex(rr)
        rng[(UInt64(UInt32(rr[i])) << 32) | UInt32(rp[i])] = (lo[i], hi[i])
    end
    out_r = Int[]; out_y = Int32[]; out_v = Float64[]
    py = Int32[]; pv = Float64[]
    ymin = isempty(years) ? Int32(0) : minimum(years); ymax = isempty(years) ? Int32(0) : maximum(years)
    mid = Dict{Int32,Float64}()
    @inbounds for s in 1:ns
        empty!(py); empty!(pv); empty!(mid)
        for q in start[s]:start[s+1]-1
            r = order[q]; push!(py, yr[r]); push!(pv, val[r])
        end
        # pts = sorted((int(y), v) ...): one record per year (a second one would be a duplicate key: the kernel declines)
        p = sortperm(py)
        py .= py[p]; pv .= pv[p]
        for i in 2:length(py)
            py[i] == py[i-1] && throw(Decline("two records of a series in the same year"))
        end
        r1 = order[start[s]]
        # --- LOOP over the data years: IF(LAST_VAL, linear interpolation between this one and the last; ELSE the first)
        f = Int32(0); first = 0.0; last = 0.0; lasty = Int32(0)
        for i in eachindex(py)
            z = py[i]; v = pv[i]
            if last != 0
                slope = (v - last) / (z - lasty)
                for y in lasty+1:z-1
                    mid[y] = v + slope * (y - z)
                end
            else
                f = z; first = v
            end
            last = v; lasty = z
        end
        isempty(py) && continue
        if mode2
            for i in eachindex(py)
                mid[py[i]] = pv[i]
            end
        end
        l, h = (bext || fext) ? get(rng, (UInt64(UInt32(keys[ri][r1])) << 32) | UInt32(keys[pi][r1]), (0.0, 0.0)) :
               (-1e9, 1e9)
        # --- the years of FIL: interpolated, plus FIRST_VAL before the first data year (from PRC_YMIN with bext) and
        #     LAST_VAL after the last (up to PRC_YMAX with fext)
        for y in years
            v = get(mid, y, 0.0)
            if y < f && (!bext || y >= l)
                v += first
            end
            if y > lasty && (!fext || y <= h)
                v += last
            end
            if v != 0
                push!(out_r, r1); push!(out_y, y); push!(out_v, abs(v) > 1e-200 ? v : 0.0)
            end
        end
    end
    out = Any[]
    for c in keys
        push!(out, c[out_r])
    end
    push!(out, out_y, out_v)
    out
end
