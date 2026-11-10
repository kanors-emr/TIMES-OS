# SPDX-License-Identifier: GPL-3.0-or-later
# fillparm.gms: the standard inter-/extrapolation of non-cost parameters, as interp.fillparm (timespp/interp.py) does
# it, statement for statement, so that the result is the same to the bit (the same upserts and deletes, in the same
# order). interp._fillparm_kernel prepares the columns (labels as codes, the year tests done in SQL) and writes the
# result back with interp's semantics (_write: deletes, then put with EPS rows; the option records removed last).
#
# Columns in (kernels.py: _fillparm_columns):
#   1  Float64 [nk, x, thr, keycond(, thrk)]   nk key columns; x: GAMS passes a work table (%8); option test
#                                      DFUNC >= thr; keycond: the series must also pass the key test (flag 8); thrk
#                                      (optional): the threshold of a series that passes the key test, instead of thr
#   2 .. 1+nk  Int32 key codes, one column per index of the parameter but the year, the records in table order
#   then  Int32 year (where flag 4), UInt8 flags (1 year '0', 2 in DATAYEAR, 4 in DM_YEAR, 8 key test), Float64 value
#   then  Int32 target years (MODLYEAR or MILESTONYR, in order)
#   then  Int32 control [nalt, ia1, ib1, ...]: nalt = -1 no control condition; else the years a series may be
#         extrapolated to are the union over the alternatives: CTRL(key[ia], year, key[ib]) (ia > 0), or a list of
#         years for every series (ia = 0); then three Int32 columns per alternative: a, b, year
# Columns out: the upserts (nk key columns, year, value: as interp's `ups`, with a value of at most TINY made 0, the
# EPS row), then the deletes (nk key columns, year: interp's `dels`).

const EPS = 1e-300
const TINY = 1e-200

"""GAMS ROUND(): half away from zero (interp._rd)."""
rd(x::Float64) = floor(abs(x) + 0.5) * (x >= 0 ? 1.0 : -1.0)

# the C library's pow, as Python's float ** float calls it (bit-identical growth rates)
@static if Sys.iswindows()
    cpow(x::Float64, y::Float64) = ccall((:pow, "ucrtbase"), Float64, (Float64, Float64), x, y)
else
    cpow(x::Float64, y::Float64) = ccall(:pow, Float64, (Float64, Float64), x, y)
end

struct Decline <: Exception
    why::String
end
Base.showerror(io::IO, e::Decline) = print(io, "kernel declines: ", e.why)

function pack(keys::Vector{Vector{Int32}}, r::Int, bits::Int)
    k = UInt128(0)
    @inbounds for c in keys
        k = (k << bits) | UInt128(c[r] + 1)
    end
    k
end

"""Rows grouped into series in the order of their first record, the records of a series in table order:
(series of each row, first row index per series + 1 sentinel, rows ordered by series)."""
function group_series(keys::Vector{Vector{Int32}}, n::Int)
    m = 0
    for c in keys, v in c
        m = max(m, Int(v) + 1)
    end
    bits = max(1, ceil(Int, log2(m + 1)))
    length(keys) * bits <= 128 || throw(Decline("$(length(keys)) key columns of $bits bits do not pack into 128"))
    id = Dict{UInt128,Int32}()
    sizehint!(id, n ÷ 4)
    ser = Vector{Int32}(undef, n)
    @inbounds for r in 1:n
        ser[r] = get!(id, pack(keys, r, bits), Int32(length(id) + 1))
    end
    ns = length(id)
    start = zeros(Int, ns + 1)
    @inbounds for r in 1:n
        start[ser[r]+1] += 1
    end
    acc = 1
    @inbounds for s in 1:ns
        c = start[s+1]; start[s] = acc; acc += c
    end
    start[ns+1] = acc
    pos = copy(start)
    order = Vector{Int}(undef, n)
    @inbounds for r in 1:n
        s = ser[r]; order[pos[s]] = r; pos[s] += 1
    end
    ns, start, order
end

"""For each alternative of the control condition, (r, p) -> its years (kernels.py codes them once per content)."""
function control_maps(ctl::Vector{Int32}, alts::Vector{Any})
    nalt = Int(ctl[1])
    maps = Dict{UInt64,Vector{Int32}}[]
    ia = Int[]; ib = Int[]; free = Int32[]
    for j in 1:max(nalt, 0)
        a, b, y = alts[3j-2]::Vector{Int32}, alts[3j-1]::Vector{Int32}, alts[3j]::Vector{Int32}
        push!(ia, ctl[2j]); push!(ib, ctl[2j+1])
        d = Dict{UInt64,Vector{Int32}}()
        if ia[end] == 0
            append!(free, y)
        else
            @inbounds for i in eachindex(y)
                push!(get!(() -> Int32[], d, (UInt64(UInt32(a[i])) << 32) | UInt32(b[i])), y[i])
            end
        end
        push!(maps, d)
    end
    nalt, maps, ia, ib, free
end

function fillparm(cols::Vector{Any})
    par = cols[1]::Vector{Float64}
    nk = Int(par[1]); x = par[2] != 0; thr = par[3]; keycond = par[4] != 0; thrk = length(par) >= 5 ? par[5] : thr
    keys = Vector{Int32}[cols[1+i]::Vector{Int32} for i in 1:nk]
    yint = cols[2+nk]::Vector{Int32}
    flags = cols[3+nk]::Vector{UInt8}
    value = cols[4+nk]::Vector{Float64}
    tg = cols[5+nk]::Vector{Int32}
    ctl = cols[6+nk]::Vector{Int32}
    fillparm_kernel(keys, yint, flags, value, tg, ctl, Any[cols[7+nk:end]...], x, thr, keycond, thrk)
end

function fillparm_kernel(keys::Vector{Vector{Int32}}, yint::Vector{Int32}, flags::Vector{UInt8},
                         value::Vector{Float64}, tg::Vector{Int32}, ctl::Vector{Int32}, alts::Vector{Any},
                         x::Bool, thr::Float64, keycond::Bool, thrk::Float64 = thr)
    n = length(value)
    nk = length(keys)
    any(isnan, value) && throw(Decline("a value is NaN or NULL"))
    ns, start, order = group_series(keys, n)
    nalt, maps, ia, ib, free = control_maps(ctl, alts)
    ntg = length(tg)
    tix = Dict{Int32,Int}(t => i for (i, t) in enumerate(tg))
    # the result, as interp's ups / dels (series row of the key, year, value)
    ups_r = Int[]; ups_y = Int32[]; ups_v = Float64[]
    del_r = Int[]; del_y = Int32[]
    okr = falses(ntg)
    item = zeros(Float64, ntg); isset = falses(ntg); inord = Int[]
    pts_y = Int32[]; pts_v = Float64[]
    freeok = falses(ntg)
    for y in free
        i = get(tix, y, 0); i > 0 && (freeok[i] = true)
    end
    @inbounds for s in 1:ns
        r1 = order[start[s]]
        # --- LOOP(DATAYEAR, UNCD7(%2,%3%4)$%1(%2,DATAYEAR,%3) = YES;);
        #     the series: its option (year '0'), its points over DM_YEAR (sorted), whether it has data (interp._series)
        hasopt = false; optv = 0.0; has = false
        empty!(pts_y); empty!(pts_v)
        for q in start[s]:start[s+1]-1
            r = order[q]; f = flags[r]; v = value[r]
            if f & 0x01 != 0
                optv = v == 0 ? EPS : v; hasopt = true
                f & 0x02 != 0 && (has = true)
                continue
            end
            f & 0x02 != 0 && (has = true)
            if f & 0x04 != 0
                push!(pts_y, yint[r]); push!(pts_v, v == 0 ? EPS : v)
            end
        end
        has || continue
        # pts.sort(): by year, then value (stable)
        for i in 2:length(pts_y)
            yi, vi = pts_y[i], pts_v[i]; j = i - 1
            while j >= 1 && (pts_y[j] > yi || (pts_y[j] == yi && pts_v[j] > vi))
                pts_y[j+1] = pts_y[j]; pts_v[j+1] = pts_v[j]; j -= 1
            end
            pts_y[j+1] = yi; pts_v[j+1] = vi
        end
        # --- the years the control condition allows
        if nalt < 0
            fill!(okr, true)
        else
            okr .= freeok
            for j in 1:nalt
                ia[j] == 0 && continue
                ys = get(maps[j], (UInt64(UInt32(keys[ia[j]][r1])) << 32) | UInt32(keys[ib[j]][r1]), nothing)
                ys === nothing && continue
                for y in ys
                    i = get(tix, y, 0); i > 0 && (okr[i] = true)
                end
            end
        end
        # --- LOOP(UNCD7(%2,%3%4), DFUNC = ROUND(%1(%2,'%DFLBL%',%3));
        #       IF(DFUNC %7, OPTION CLEAR=MY_FIL2; CNT = (DFUNC LE 999);
        #         MY_ARRAY(DM_YEAR) = %1(%2,DM_YEAR,%3); LAST_VAL=0; F = 0; Z = 0;
        hasopt && !isfinite(optv) && throw(Decline("an option that is not finite"))
        DF = hasopt ? rd(optv) : 0.0
        key = flags[r1] & 0x08 != 0
        (DF >= (key ? thrk : thr) && (!keycond || key)) || continue
        CNT = DF <= 999
        LAST = 0.0; F = 0.0; Z = 0.0; FIRST = 0.0; MYFY = 0.0
        fill!(isset, false); empty!(inord)
        # --- LOOP(DM_YEAR$MY_ARRAY(DM_YEAR), MY_F = MY_ARRAY(DM_YEAR); Z = YEARVAL(DM_YEAR);
        #       IF(LAST_VAL,
        #         IF(CNT OR (Z LE DFUNC),             ! linear interpolation
        #           %ITEM%$((Z GT YEARVAL(%5))$(YEARVAL(%5) GT MY_FYEAR))
        #             = LAST_VAL + (MY_F-LAST_VAL)/(Z-MY_FYEAR)*(YEARVAL(%5)-MY_FYEAR);
        #         ELSE                                ! exponential function
        #           %ITEM%$((Z GT YEARVAL(%5))$(YEARVAL(%5) GT MY_FYEAR)) = LAST_VAL*POWER(1+MY_F,YEARVAL(%5)-MY_FYEAR)+EPS;
        #           MY_F = LAST_VAL*POWER(1+MY_F,Z-MY_FYEAR)+EPS;
        #           %1(%2,DM_YEAR,%3) = MY_F;);      ! overwrite old data
        #       ELSE F = Z; FIRST_VAL = MY_F;);
        #       LAST_VAL = MY_F; MY_FYEAR=Z;);
        for k in eachindex(pts_y)
            Zy = pts_y[k]; MY_F = pts_v[k]
            if LAST != 0
                if CNT || Zy <= DF
                    for (i, t) in enumerate(tg)
                        if MYFY < t < Zy
                            isset[i] || (isset[i] = true; push!(inord, i))
                            item[i] = LAST + (MY_F - LAST) / (Zy - MYFY) * (t - MYFY)
                        end
                    end
                else
                    for (i, t) in enumerate(tg)
                        if MYFY < t < Zy
                            isset[i] || (isset[i] = true; push!(inord, i))
                            item[i] = LAST * cpow(1 + MY_F, t - MYFY) + EPS
                        end
                    end
                    MY_F = LAST * cpow(1 + MY_F, Zy - MYFY) + EPS
                    push!(ups_r, r1); push!(ups_y, Zy); push!(ups_v, MY_F)          # overwrite old data
                end
            else
                F = Float64(Zy); FIRST = MY_F
            end
            LAST = MY_F; MYFY = Float64(Zy); Z = Float64(Zy)
        end
        # --- IF(DFUNC GT 1, IF(CNT,DFUNC=MOD(DFUNC,10);
        #       IF(DFUNC EQ 2, FIRST_VAL = EPS; LAST_VAL = EPS; ELSEIF DFUNC EQ 4, Z = INF; ELSEIF DFUNC EQ 5, F = 0)));
        if DF > 1 && CNT
            DF = rem(DF, 10.0)
            if DF == 2
                FIRST = EPS; LAST = EPS
            elseif DF == 4
                Z = Inf
            elseif DF == 5
                F = 0.0
            end
        end
        # --- IF((DFUNC NE 1), %DATA%$%6 $= FIRST_VAL$(YEARVAL(%5) LT F) %ADD% + LAST_VAL$(YEARVAL(%5) GT Z);
        #     $IF NOT '%8' == '' ELSE %DATA%$%6 $= %ITEM%;
        #     without %8 the interpolated values are assigned (%ITEM% is the parameter itself), then the extrapolation
        #     under the control condition; with %8 both go through the work table, under the control condition
        if !x
            for i in inord                                              # '=' assignment
                v = item[i]
                if v != 0
                    push!(ups_r, r1); push!(ups_y, tg[i]); push!(ups_v, v)
                else
                    push!(del_r, r1); push!(del_y, tg[i])
                end
            end
            if DF != 1
                for (i, t) in enumerate(tg)
                    v = (t < F ? FIRST : 0.0) + (t > Z ? LAST : 0.0)
                    if v != 0 && okr[i]
                        push!(ups_r, r1); push!(ups_y, t); push!(ups_v, v)
                    end
                end
            end
        else
            for (i, t) in enumerate(tg)
                v = isset[i] ? item[i] : 0.0
                if DF != 1
                    v = (t < F ? FIRST : 0.0) + v + (t > Z ? LAST : 0.0)
                end
                if v != 0 && okr[i]
                    push!(ups_r, r1); push!(ups_y, t); push!(ups_v, v)
                end
            end
        end
    end
    for i in eachindex(ups_v)                       # _write: a value of at most TINY is stored as EPS (0)
        abs(ups_v[i]) > TINY || (ups_v[i] = 0.0)
    end
    out = Any[]
    for c in keys
        push!(out, c[ups_r])
    end
    push!(out, ups_y, ups_v)
    for c in keys
        push!(out, c[del_r])
    end
    push!(out, del_y)
    out
end
