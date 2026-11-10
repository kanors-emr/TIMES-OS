# SPDX-License-Identifier: GPL-3.0-or-later
# The objective coefficients (eqobj.mod preamble, eqobjinv.mod, eqobjfix.mod, eqobsalv.mod, coef_alt.lin INV/FIX,
# eqobjann.tm COEF, prepret.dsc OBJFIX), as timespp/prep/objective.py computes them, statement for statement, on
# label codes and integer years: _investment, _fixed_costs and eoh, and the rows of the tables _write_tables stores.
# The Python is the reference; this agrees with it to the bit (TIMESPP_KERNELS=check:objective).
#
# Its order is the reference's wherever it changes a float: the vintages in RTP's order, each vintage's investment
# steps in the order spreads() makes them, INVSPRED's sets in Python's own iteration order (pyset_order), the sums by
# Python's sum() (PySum). Where the reference would raise (a key it reads that is not there, a division by zero) the
# kernel declines and the reference runs, and raises.
#
# Columns in (objective.py, _kernel_inputs): par, the year sets, B E M D IPD, RTP, the (r,v,p) attributes, RTP_OFF,
# the discounting by (r,y,cur), RDCUR, the OB_ costs by (r,p,cur,y), PRC_RESID, COEF_CPT, VNT, the shapes, PERIODYR,
# NCAP_OCOM, G_RCUR, PRC_REFIT, and with VNRET RVPRL, VNTRT, PERIODYR and RTP_CPTYR. Columns out: OBJ_OUT below.

const K3 = Tuple{Int32,Int,Int32}                      # (r, v, p)
const K4 = Tuple{Int32,Int,Int32,Int32}                # (r, v, p, cur)
const OBK = Tuple{Int32,Int32,Int32,Int}               # (r, p, cur, y): the OB_ tables
const RYC = Tuple{Int32,Int,Int32}                     # (r, y, cur)
const KJ = Tuple{Int,Int}                              # (K, JOT)

need(d::AbstractDict, k) = (v = get(d, k, nothing); v === nothing ? throw(Decline("a key the reference reads is not there")) : v)

struct ColReader
    v::Vector{Any}
    i::Base.RefValue{Int}
end
ColReader(v) = ColReader(v, Ref(0))
nextcol(c::ColReader) = (c.i[] += 1; c.v[c.i[]])
i32(c::ColReader) = nextcol(c)::Vector{Int32}
function f64(c::ColReader)
    v = nextcol(c)::Vector{Float64}
    any(isnan, v) && throw(Decline("a value that is NaN or NULL"))
    v
end

yearset(c) = Set{Int}(Int(y) for y in i32(c))
function ipar(c)
    y, v = i32(c), f64(c)
    all(isinteger, v) || throw(Decline("B, E, M, D or IPD with a value that is not an integer"))
    Dict{Int,Int}(Int(y[i]) => Int(v[i]) for i in eachindex(y))
end
function p3(c)
    r, y, p, v = i32(c), i32(c), i32(c), f64(c)
    d = Dict{K3,Float64}()
    sizehint!(d, length(r))
    for i in eachindex(r)
        d[(r[i], Int(y[i]), p[i])] = v[i]
    end
    d
end
function k3set(c)
    r, y, p = i32(c), i32(c), i32(c)
    Set{K3}((r[i], Int(y[i]), p[i]) for i in eachindex(r))
end
function rycd(c)
    r, y, cur, v = i32(c), i32(c), i32(c), f64(c)
    d = Dict{RYC,Float64}()
    for i in eachindex(r)
        d[(r[i], Int(y[i]), cur[i])] = v[i]
    end
    d
end
function obd(c)
    r, p, cur, y, v = i32(c), i32(c), i32(c), i32(c), f64(c)
    d = Dict{OBK,Float64}()
    sizehint!(d, length(r))
    for i in eachindex(r)
        d[(r[i], p[i], cur[i], Int(y[i]))] = v[i]
    end
    d
end
"""An OB_ table by (r, p, cur): the values of each over its years as one vector, and which years have a record. It
answers get and haskey on (r, p, cur, y) as the Dict would; the series of the last (r, p, cur) asked is kept, as
the sums ask year after year of one process."""
struct Series
    y0::Int
    v::Vector{Float64}
    has::BitVector
end
mutable struct SeriesTable
    d::Dict{Tuple{Int32,Int32,Int32},Series}
    lastk::Tuple{Int32,Int32,Int32}
    last::Union{Nothing,Series}
end
@inline function series(t::SeriesTable, r, p, cur)
    k = (Int32(r), Int32(p), Int32(cur))
    k == t.lastk && return t.last
    s = get(t.d, k, nothing)
    t.lastk = k
    t.last = s
    s
end
@inline function Base.haskey(t::SeriesTable, k::OBK)
    s = series(t, k[1], k[2], k[3])
    s === nothing && return false
    i = k[4] - s.y0 + 1
    1 <= i <= length(s.v) && s.has[i]
end
@inline function Base.get(t::SeriesTable, k::OBK, default)
    s = series(t, k[1], k[2], k[3])
    s === nothing && return default
    i = k[4] - s.y0 + 1
    (1 <= i <= length(s.v) && s.has[i]) ? s.v[i] : default
end
function obseries(c)
    r, p, cur, y, v = i32(c), i32(c), i32(c), i32(c), f64(c)
    span = Dict{Tuple{Int32,Int32,Int32},Tuple{Int,Int}}()
    for i in eachindex(r)
        k = (r[i], p[i], cur[i])
        lo, hi = get(span, k, (typemax(Int), typemin(Int)))
        span[k] = (min(lo, Int(y[i])), max(hi, Int(y[i])))
    end
    d = Dict{Tuple{Int32,Int32,Int32},Series}(k => Series(lo, zeros(hi - lo + 1), falses(hi - lo + 1)) for (k, (lo, hi)) in span)
    for i in eachindex(r)                                   # in the rows' order: the last record of a key is kept
        s = d[(r[i], p[i], cur[i])]
        j = Int(y[i]) - s.y0 + 1
        s.v[j] = v[i]
        s.has[j] = true
    end
    SeriesTable(d, (Int32(-1), Int32(-1), Int32(-1)), nothing)
end

function lists(a::Vector{Int32}, b::Vector{Int32})
    d = Dict{Int,Vector{Int}}()
    for i in eachindex(a)
        push!(get!(() -> Int[], d, Int(a[i])), Int(b[i]))
    end
    d
end

"""_net: A + B - C for every key of any of them, each value by the expression A.get(k, 0.0) + B.get(k, 0.0) - C.get(k, 0.0)
(computed at the lookup: the same expression on the same values)."""
struct Net
    A::SeriesTable
    B::SeriesTable
    C::SeriesTable
end
Base.haskey(n::Net, k) = haskey(n.A, k) || haskey(n.B, k) || haskey(n.C, k)
Base.get(n::Net, k, default) = haskey(n, k) ? get(n.A, k, 0.0) + get(n.B, k, 0.0) - get(n.C, k, 0.0) : default
# _on_record: EPS-EPS is EPS (0.0 on record), x-x is 0 and has none
onrecord(n::Net, k) = haskey(n, k) && (get(n, k, 0.0) != 0 || (get(n.A, k, 0.0) == 0 && get(n.B, k, 0.0) == 0 && get(n.C, k, 0.0) == 0))
# _eps_grouped: A + (B - C) of the annualised form, EPS+(x-x) is EPS
function epsgrouped(n::Net, k)
    a, b, c = get(n.A, k, 0.0), get(n.B, k, 0.0), get(n.C, k, 0.0)
    return a == 0 && b - c == 0 && (haskey(n.A, k) || (b == 0 && c == 0 && (haskey(n.B, k) || haskey(n.C, k))))
end

# out: the tables as columns; each spec gives the integer columns (L: a label code, Y: an integer written as its
# text) and the number of Float64 columns after them (objective.py: OBJ_OUT, in this order)
mutable struct Table
    ints::Vector{Vector{Int32}}
    vals::Vector{Vector{Float64}}
end
newtable(ni, nv) = Table([Int32[] for _ in 1:ni], [Float64[] for _ in 1:nv])
"""One row: its integer columns, then its Float64 columns (unrolled over the tuples, which mix Int32 and Int)."""
@inline function row!(t::Table, ints::Tuple, vals::Tuple=())
    pushcols!(t.ints, Int32, 1, ints...)
    pushcols!(t.vals, Float64, 1, vals...)
    t
end
@inline pushcols!(cols, ::Type, j) = nothing
@inline function pushcols!(cols, ::Type{T}, j, x, rest...) where {T}
    push!(cols[j], T(x))
    pushcols!(cols, T, j + 1, rest...)
end

function objective(cols::Vector{Any})
    c = ColReader(cols)
    par = f64(c)
    classic, lev, DS = par[1] != 0, par[2] != 0, par[3]
    MINYR, MIYR_V1, MIYR_VL, ALTOBJ, VNRET, nage, py312, MAXLIFE0 = par[4], par[5], par[6], par[7], par[8] != 0,
        Int(par[9]), par[10] != 0, par[11]
    psum = PySum(py312)
    ALL, K, K_EOH, Y_EOH, T, PASTMILE, PYR_S, PASTYEAR = (yearset(c) for _ in 1:8)
    B, E, M, D, IPD = (ipar(c) for _ in 1:5)
    rr, ry, rp = i32(c), i32(c), i32(c)
    rtp = K3[(rr[i], Int(ry[i]), rp[i]) for i in eachindex(rr)]
    TLIFE, ELIFE, RPTI, PASTI, DLIFE, DELIF, DLAG, NDR, FDR, ILED, CILED = (p3(c) for _ in 1:11)
    off = k3set(c)
    DISC, GDR, RFR, PVT = (rycd(c) for _ in 1:4)
    a, b = i32(c), i32(c)
    rdcur = Dict{Int32,Vector{Int32}}()
    rdorder = Int32[]                                   # the regions in the order of RDCUR's sort (rdcur.items())
    for i in eachindex(a)
        haskey(rdcur, a[i]) || push!(rdorder, a[i])
        push!(get!(() -> Int32[], rdcur, a[i]), b[i])
    end
    ICO, ISU, ITX, FOM, FSB, FTX = (obseries(c) for _ in 1:6)
    DCC, DLC = obd(c), obd(c)
    a, b = i32(c), i32(c)
    resid0 = Set{Tuple{Int32,Int32}}(zip(a, b))
    resid = p3(c)
    cr, cv, cp, ct, cx = i32(c), i32(c), i32(c), i32(c), f64(c)
    a, b = i32(c), i32(c)
    vnt = lists(a, b)
    CPX = k3set(c)
    a, b, d_, e_, v_ = i32(c), i32(c), i32(c), i32(c), f64(c)
    RCPX = Dict{Tuple{Int32,Int,Int32,Int},Float64}((a[i], Int(b[i]), d_[i], Int(e_[i])) => v_[i] for i in eachindex(a))
    FOMX, TAXX, SUBX, FOMM, TAXM, SUBM = (p3(c) for _ in 1:6)
    a, b, v_ = i32(c), i32(c), f64(c)
    SHP = Dict{KJ,Float64}((Int(a[i]), Int(b[i])) => v_[i] for i in eachindex(a))
    a, b, v_ = i32(c), i32(c), f64(c)
    MUL = Dict{KJ,Float64}((Int(a[i]), Int(b[i])) => v_[i] for i in eachindex(a))
    a, b = i32(c), i32(c)
    period_of = Dict{Int,Int}()
    for i in eachindex(a)
        period_of[Int(b[i])] = Int(a[i])
    end
    ocom = k3set(c)
    a, b = i32(c), i32(c)
    grcur = Dict{Int32,Int32}()
    for i in eachindex(a)
        grcur[a[i]] = b[i]
    end
    a, b, d_, v_ = i32(c), i32(c), i32(c), f64(c)
    retro = Set{Tuple{Int32,Int32}}((a[i], d_[i]) for i in eachindex(a) if v_[i] < 0)
    rvprl = k3set(c)
    a, b = i32(c), i32(c)
    vntrt = lists(a, b)
    a, b = i32(c), i32(c)
    peryr = Dict{Int,Vector{Int}}()
    for i in eachindex(a)
        Int(b[i]) in Y_EOH && push!(get!(() -> Int[], peryr, Int(a[i])), Int(b[i]))
    end
    a, b, d_, e_ = i32(c), i32(c), i32(c), i32(c)
    cptyr_res = Dict{K3,Vector{Int}}()
    for i in eachindex(a)
        push!(get!(() -> Int[], cptyr_res, (a[i], Int(b[i]), e_[i])), Int(d_[i]))
    end
    objective_kernel(classic, lev, DS, MINYR, MIYR_V1, MIYR_VL, ALTOBJ, VNRET, nage, psum, MAXLIFE0,
                     ALL, K, K_EOH, Y_EOH, T, PASTMILE, PYR_S, PASTYEAR, B, E, M, D, IPD, rtp,
                     TLIFE, ELIFE, RPTI, PASTI, DLIFE, DELIF, DLAG, NDR, FDR, ILED, CILED, off,
                     DISC, GDR, RFR, PVT, rdcur, rdorder, ICO, ISU, ITX, FOM, FSB, FTX, DCC, DLC, resid0, resid,
                     (cr, cv, cp, ct, cx), vnt, CPX, RCPX, FOMX, TAXX, SUBX, FOMM, TAXM, SUBM, SHP, MUL, period_of,
                     ocom, grcur, retro, rvprl, vntrt, peryr, cptyr_res)
end

function objective_kernel(classic, lev, DS, MINYR, MIYR_V1, MIYR_VL, ALTOBJ, VNRET, nage, psum, MAXLIFE0,
                          ALL, K, K_EOH, Y_EOH, T, PASTMILE, PYR_S, PASTYEAR, B, E, M, D, IPD, rtp,
                          TLIFE, ELIFE, RPTI, PASTI, DLIFE, DELIF, DLAG, NDR, FDR, ILED, CILED, off,
                          DISC, GDR, RFR, PVT, rdcur, rdorder, ICO, ISU, ITX, FOM, FSB, FTX, DCC, DLC, resid0, resid,
                          cptcols, vnt, CPX, RCPX, FOMX, TAXX, SUBX, FOMM, TAXM, SUBM, SHP, MUL, period_of,
                          ocom, grcur, retro, rvprl, vntrt, peryr, cptyr_res)
    YEARS = ALL
    rtpset = Set{K3}(rtp)
    nocur = Int32[]
    curs(r) = get(rdcur, r, nocur)
    # ICOST, FOMC: OBJ_ICOST+OBJ_ITAX-OBJ_ISUB and OBJ_FOM+OBJ_FTX-OBJ_FSB (_net)
    ICOST, FOMC = Net(ICO, ITX, ISU), Net(FOM, FTX, FSB)
    # COEF_CPT by vintage: (r, v, p) -> the rows of its periods, in COEF_CPT's sort (_Slices)
    cr, cv, cp, ct, cx = cptcols
    cpt = Dict{K3,UnitRange{Int}}()
    i0 = 1
    for i in eachindex(cr)
        if i == length(cr) || (cr[i+1], cv[i+1], cp[i+1]) != (cr[i], cv[i], cp[i])
            cpt[(cr[i], Int(cv[i]), cp[i])] = i0:i
            i0 = i + 1
        end
    end
    # --- SUM(T, COEF_CPT(R,V,T,P)*OBJ_PVT(R,T,CUR)), once per vintage and currency (cptpv)
    cpv = Dict{K4,Float64}()
    function cptpv(r, v, p, cur)
        x = get(cpv, (r, v, p, cur), nothing)
        x === nothing || return x
        rg = get(cpt, (r, v, p), 1:0)
        x = psum(cx[j] * get(PVT, (r, Int(ct[j]), cur), 0.0) for j in rg)
        cpv[(r, v, p, cur)] = x
    end

    # ------------------------------------------------------------------ eqobjinv.mod
    # --- OBJ_ICUR(RTP(R,V,P),CUR)$(OBJ_ICOST + OBJ_ISUB + OBJ_ITAX) = YES;  OBJ_ICUR(RTP_OFF,CUR)$(NOT NCAP_PASTI(RTP_OFF)) = NO;
    #     OBJ_ICUR(RTP(R,V,P),CUR)$OBJ_DCOST(R,V,P,CUR) = YES;                     (a cost of EPS counts: the test is on the record)
    icur = K4[]
    for (r, v, p) in rtp, cur in curs(r)
        kk = (r, p, cur, v)
        if (haskey(ICOST, kk) || haskey(DCC, kk)) && !((r, v, p) in off && !haskey(PASTI, (r, v, p)))
            push!(icur, (r, v, p, cur))
        end
    end
    # --- LOOP(CUR,OBJ_SUMS3(RTP(R,V,P))$OBJ_DCOST(R,V,P,CUR) = YES);  LOOP((RTP,COM)$NCAP_OCOM(RTP,COM),OBJ_SUMS3(RTP) = YES);
    sums3 = Set{K3}()
    for (r, p, cur, v) in keys(DCC)
        (r, v, p) in rtpset && push!(sums3, (r, v, p))
    end
    for k in ocom
        k in rtpset && push!(sums3, k)
    end
    # --- OPTION OBJ_YES < OBJ_ICUR; OBJ_YES(OBJ_SUMS3) = YES;
    yes = Set{K3}(k[1:3] for k in icur)
    union!(yes, sums3)
    # --- NCAP_DLIFE(OBJ_SUMS3(R,V,P))$(ROUND(NCAP_DLIFE(R,V,P)) LE 0) = 1;  NCAP_DELIF(OBJ_SUMS3(R,V,P)) = MAX(1,NCAP_DELIF(R,V,P));
    fixdl = newtable(3, 2)
    for k in sums3
        rnd(get(DLIFE, k, 0.0)) <= 0 && (DLIFE[k] = 1.0)
        DELIF[k] = pymax(1.0, get(DELIF, k, 0.0))
    end
    for k in sums3
        row!(fixdl, k, (DLIFE[k], DELIF[k]))
    end
    # --- NCAP_TLIFE(OBJ_YES(R,V,P))$(ROUND(NCAP_TLIFE(R,V,P)) LE 0) = 1;   same for NCAP_ELIFE
    fixtl, fixel = newtable(3, 0), newtable(3, 0)
    for (tab, d) in ((fixtl, TLIFE), (fixel, ELIFE))
        fix = K3[k for k in yes if rnd(get(d, k, 0.0)) <= 0]
        for k in fix
            d[k] = 1.0
            row!(tab, k)
        end
    end
    # --- OBJ_I2(RTP)$NCAP_ILED(RTP) = YES;   OBJ_FCUR(RTP(R,V,P),CUR)$OBJ_DLAGC(R,V,P,CUR) = YES;   (eqobjfix.mod 35)
    i2(k) = haskey(ILED, k)
    dlc_v = Set{K3}((r, v, p) for (r, p, cur, v) in keys(DLC))
    fcur = K4[]
    for (r, v, p) in rtp, cur in curs(r)
        kk = (r, p, cur, v)
        (haskey(FOMC, kk) || haskey(DLC, kk)) && push!(fcur, (r, v, p, cur))
    end
    # --- COR_SALVI;  COR_SALVI(OBJ_ICUR(OBJ_I2(R,V,P),CUR)) = COR_SALVI(R,V,P,CUR) / ((1+G_DRATE(R,V,CUR))**%DISCSHIFT%);  OBJ_CRF
    #     OBJ_PASTI(OBJ_ICUR(RTP(R,PASTYEAR(V),P),CUR)) = NCAP_PASTI(R,V,P) *
    #        MAX(0,MIN(1,(((1+G_DRATE)**(YEARVAL(V)+ROUND(NCAP_ILED(R,V,P))-MINYR+NCAP_ELIFE(R,V,P))-1) / ((1+G_DRATE)**NCAP_ELIFE(R,V,P)-1))));
    cor, crf, opasti = Dict{K4,Float64}(), Dict{K4,Float64}(), Dict{K4,Float64}()
    sizehint!(cor, length(icur)); sizehint!(crf, length(icur))
    corx(ndr, rf, el) = pydiv(pypow(pydiv(1 + ndr, 1 + rf), DS) * ((1 - pydiv(1, 1 + ndr)) * (1 - pypow(1 + rf, -el))),
                              (1 - pydiv(1, 1 + rf)) * (1 - pypow(1 + ndr, -el))) - 1
    for (r, v, p, cur) in icur
        k = (r, v, p)
        dr, ndr, rf, el = get(GDR, (r, v, cur), 0.0), get(NDR, k, 0.0), get(RFR, (r, v, cur), 0.0), get(ELIFE, k, 0.0)
        x = 0.0
        if ndr > 0
            x = corx(ndr, rf, el)
        end
        c_ = (x + 1) * pypow(1 + dr, DS)
        if i2(k)
            c_ = pydiv(c_, pypow(1 + dr, DS))
        end
        cor[(r, v, p, cur)] = c_
        crf[(r, v, p, cur)] = pydiv(c_ * (1 - pydiv(1, 1 + dr)), 1 - pypow(1 + dr, -rnd(el)))
        if v in PASTYEAR
            f = pymax(0.0, pymin(1.0, pydiv(pypow(1 + dr, (v + rnd(get(ILED, k, 0.0)) - MINYR) + el) - 1, pypow(1 + dr, el) - 1)))
            w = get(PASTI, k, 0.0) * f
            if w != 0 || (f != 0 && haskey(PASTI, k))
                opasti[(r, v, p, cur)] = w
            end
        end
    end
    # --- MAXLIFE = MAX(SMAX(T,2*D(T)),Z,CEIL(MAXLIFE));  OPYEAR(LIFE,AGE)$(...(ORD(LIFE) LE MAXLIFE)) = YES;   (OPYEAR: objective.py)
    maxE = typemin(Int); hasE = false
    for (r, v, p) in rtp
        v in PYR_S || continue
        for t in T
            if get(resid, (r, t, p), 0.0) != 0
                e = need(E, t)
                (!hasE || e > maxE) && (maxE = e)
                hasE = true
            end
        end
    end
    z = (hasE ? Float64(maxE) : -Inf) - MIYR_V1 + 2
    maxlife = Float64(pymax(pymax(maximum(2 * need(D, t) for t in T), z), pyceil(MAXLIFE0)))
    # --- OBJ_1A(RTP(R,V,P))$((NOT OBJ_I2(R,V,P))$(COEF_RPTI(R,V,P) LT 1.01)) = YES;  OBJ_1B ...; OBJ_2A ...; OBJ_2B ...
    is1a(k) = !i2(k) && get(RPTI, k, 0.0) < 1.01
    is1b(k) = !i2(k) && !is1a(k) && k[2] in T
    is2a(k) = i2(k) && get(RPTI, k, 0.0) <= 1
    is2b(k) = i2(k) && !is2a(k) && k[2] in T
    start(v) = v in T ? (need(M, v) - (need(IPD, v) - 1), need(IPD, v)) : (need(B, v), 1)
    function idc(k)
        r, v, p = k
        zl = get(ILED, k, 0.0)
        out = KJ[]
        if is2a(k)
            # LL+MY_F: GAMS rounds the non-integer lag MY_F itself, not the year it points to
            push!(out, (v + rnd(need(B, v) - v + zl), 1 + pymax(0, rnd(zl) - 1)))
        elseif is2b(k)
            for cc in 1:pyfloor(need(RPTI, k))
                push!(out, (v + rnd(rnd(need(B, v) + (cc - 1) * need(TLIFE, k)) - v + zl), 1 + pymax(0, rnd(zl) - 1)))
            end
        end
        KJ[(y0, j) for (y0, j) in out if y0 in YEARS]
    end
    function spreads(k)
        r, v, p = k
        if i2(k)
            # Cases 2a / 2b: one payment in the commissioning year (OBJ_SUMII(R,V,P,LIFE,LL,JOT+(1-ORD(JOT)))$OBJ_IDC)
            return KJ[(y0, 1) for (y0, _j) in idc(k)]
        end
        if is1a(k)
            st = start(v)
            return st[1] in K ? KJ[st] : KJ[]
        end
        v in T || return KJ[]
        zz = need(TLIFE, k)
        out = KJ[]
        # --- IF((ROUND(Z)-IPD(T)%CTST%) LE 0, F = B(T) - %ZHALF% - YEARVAL(T); ...  ELSE CNT = %ISTEP%; ...
        if rnd(zz) - (classic ? need(IPD, v) : 1) <= 0
            push!(out, (need(B, v) - (classic ? pyceil(zz / 2 - 0.5) : fld(rnd(zz), 2)), trunc(Int, rnd(need(RPTI, k) * zz) - 1) + 1))
        else
            cnt = classic ? need(IPD, v) : pymin(need(IPD, v), rnd(zz))
            # --- F = B(T)-YEARVAL(T)-FLOOR(CNT/2); FOR(OBJ_C = 1 TO COEF_RPTI, OBJ_SUMII(R,T,P,LIFE,K(LL+F),AGE+CNT) = YES; F = F+Z)
            f = Float64(need(B, v) - v - floor(Int, cnt / 2))
            for _ in 1:pyfloor(need(RPTI, k))
                push!(out, (v + rnd(f), cnt))
                f += zz
            end
        end
        KJ[(y0, jot) for (y0, jot) in out if y0 in K]
    end
    # OBJ_SUMII by vintage: [(LIFE, K, JOT)]
    sumii = Dict{K3,Vector{Tuple{Int,Int,Int}}}()
    sizehint!(sumii, length(yes))
    for k in yes
        life = 1 + pymax(0, rnd(pymin(nage, get(ELIFE, k, 0.0))) - 1)
        sumii[k] = [(life, y0, jot) for (y0, jot) in spreads(k) if 1 <= jot <= nage]
    end
    # --- OPTION KAGE < OBJ_SUMII;  INVSTEP(KAGE(LL,JOT),LL+(ORD(AGE)-1),..)$OPYEAR(JOT,AGE) = YES;
    steps(keyset) = Dict{KJ,Vector{Int}}((k0, jot) => [y for y in k0:k0+jot-1 if y in ALL] for (k0, jot) in keyset if jot <= maxlife)
    kage0 = Set{KJ}()
    for lst in values(sumii), (_, k0, jot) in lst
        push!(kage0, (k0, jot))
    end
    invstep = steps(kage0)
    FILB = Set{Int}(need(B, t) for t in T)
    invspred = Dict{KJ,Vector{KJ}}()                         # INVSPRED(K, JOT, LL, K'): each set in Python's order
    jd = Dict{Tuple{Int32,Int32,Int,Int},Float64}()
    wd = Dict{Tuple{Int32,Int32,Int,Int,Int},Float64}()
    JDf(key) = classic ? 1.0 : get(jd, key, 0.0)            # %CAPJD% / %CAPWD% empty with CTST ''
    WDf(key) = classic ? 1.0 : get(wd, key, 0.0)
    # --- coef_alt.lin INV:  OBJ_JD(RDCUR(R,CUR),K,JOT)$KAGE(K,JOT) = 1;
    if !classic
        for r in rdorder, cur in rdcur[r], (k0, jot) in kage0
            k0 in K && (jd[(r, cur, k0, jot)] = 1.0)
        end
    end
    # --- interest during construction for any fractional ILED (eqobjinv.mod): OBJ_DIVI(R,V,P) = 1/(1+Z*MY_F/F)
    divi = Dict{K3,Float64}()
    my_f = 0.0
    for (r, v, p, cur) in icur
        k = (r, v, p)
        i2(k) || continue
        z = get(CILED, k, 0.0)
        local f
        if haskey(CILED, k)                     # IF(Z, ...): an EPS COEF_ILED (exact start year) is true
            cc = 1 + get(GDR, (r, v, cur), 0.0)
            my_f, f, cnt = 0.0, 0.0, 0.0
            for (y0, jot) in idc(k)
                cnt = jot
                if jot <= maxlife
                    my_f += psum(get(DISC, (r, y0 - a, cur), 0.0) for a in 1:jot if (y0 - a) in YEARS)
                end
                f += get(DISC, (r, y0, cur), 0.0)
            end
            my_f = pydiv(pydiv(my_f, f), cnt) - 1
            f = pydiv(pydiv(pypow(cc, cnt) - 1, 1 - pydiv(1, cc)), cnt) - 1
            cnt = pymax(1e-5, z)
            z = pydiv(pydiv(pypow(cc, cnt) - 1, 1 - pydiv(1, cc)), cnt) - 1
        else
            f = 1.0
        end
        divi[k] = pydiv(1, 1 + pydiv(z * my_f, f))
    end
    # --- coef_alt.lin INV: OBJ_DIVI(OBJ_YES(R,V,P))$(NOT OBJ_I2(R,V,P)) = 1+MIN(IPD(V)-1,ROUND(NCAP_TLIFE(R,V,P))-1)$T(V);
    #     OBJ_DIVI(OBJ_YES(OBJ_1B(R,T,P)))$(ROUND(NCAP_TLIFE(R,T,P)) EQ 1) = NCAP_TLIFE(R,T,P);
    for k in yes
        r, v, p = k
        if classic
            # --- (eqobjinv.mod, CTST '') OBJ_DIVI(OBJ_YES(OBJ_1A(R,V,P))) = 1+(IPD(V)-1)$MILESTONYR(V);
            #     OBJ_DIVI(OBJ_YES(OBJ_1B(R,T,P))) = NCAP_TLIFE(R,T,P);
            #     IF(ALTOBJ,OBJ_DIVI(OBJ_YES(OBJ_1B(R,T,P)))$((ROUND(NCAP_TLIFE(R,T,P))-IPD(T)%CTST%) GT 0) = IPD(T)*MIN(1,NCAP_TLIFE(R,T,P)));
            if is1a(k)
                divi[k] = 1 + (v in T ? need(IPD, v) - 1 : 0)
            elseif is1b(k)
                divi[k] = need(TLIFE, k)
                if ALTOBJ != 0 && rnd(need(TLIFE, k)) - need(IPD, v) > 0
                    divi[k] = need(IPD, v) * pymin(1, need(TLIFE, k))
                end
            end
            continue
        end
        if !i2(k)
            divi[k] = 1 + (v in T ? pymin(need(IPD, v) - 1, rnd(need(TLIFE, k)) - 1) : 0)
        end
        if is1b(k) && rnd(need(TLIFE, k)) == 1
            divi[k] = need(TLIFE, k)
        end
    end
    # --- OBJ_DIVIII(OBJ_SUMS3(R,V,P)) = OBJ_DIVI(R,V,P);  OBJ_DIVIII(OBJ_SUMS3(OBJ_I2(R,V,P))) = ROUND(NCAP_DLIFE(R,V,P));
    diviii = Dict{K3,Float64}(k => (i2(k) ? rnd(need(DLIFE, k)) : need(divi, k)) for k in sums3)
    # --- OBJ_CRFD(R,PASTMILE(V),P,CUR)$OBJ_PASTI(R,V,P,CUR) = SUM(OBJ_SUMII(R,V,P,LIFE,K,JOT),NCAP_PASTI(R,V,P)*OBJ_CRF(R,V,P,CUR)/OBJ_DISC(R,K,CUR));
    #     OBJ_PASTI(R,PASTMILE(V),P,CUR)$OBJ_CRFD(R,V,P,CUR) = SUM(VNT(V,T),COEF_CPT(R,V,T,P)*OBJ_PVT(R,T,CUR))*OBJ_CRFD(R,V,P,CUR)/COR_SALVI(R,V,P,CUR);
    if !classic
        for key in collect(keys(opasti))
            r, v, p, cur = key
            v in PASTMILE || continue
            k = (r, v, p)
            crfd = psum(pydiv(get(PASTI, k, 0.0) * crf[key], need(DISC, (r, y0, cur)))
                        for (_l, y0, _j) in get(sumii, k, ()) if y0 in K)
            if crfd != 0
                vv = get(vnt, v, Int[])
                w = pydiv(psum(cx[j] * get(PVT, (r, Int(ct[j]), cur), 0.0) for j in get(cpt, k, 1:0) if Int(ct[j]) in vv) * crfd, cor[key])
                if w != 0
                    opasti[key] = w
                else
                    delete!(opasti, key)
                end
            end
        end
    end
    # --- coef_alt.lin DOFIX (_dofix): INVSPRED, OBJ_JD, OBJ_WD
    function dofix(invst, with_wd)
        if classic
            for ((k0, jot), ys) in invst
                haskey(invspred, (k0, jot)) || (invspred[(k0, jot)] = pyset_order(KJ[(y, y) for y in ys if y in K]))
            end
            return
        end
        kage = Set{KJ}(kj for kj in keys(invst) if !(kj[1] in FILB) && kj[1] in K)
        for (k0, jot) in keys(invst)
            jot > 1 && k0 in FILB && (k0 + fld(jot, 2)) in FILB && push!(kage, (k0, jot))
        end
        for ((k0, jot), ys) in invst
            haskey(invspred, (k0, jot)) && continue      # (the same rows again: a set it already is)
            ys = [y for y in ys if y in K]
            invspred[(k0, jot)] = pyset_order((k0, jot) in kage ? KJ[(k0 + fld(jot, 2), y) for y in ys] : KJ[(y, y) for y in ys])
        end
        for r in rdorder, cur in rdcur[r]
            for (k0, jot) in kage
                den = psum(pydiv(get(DISC, (r, y, cur), 0.0), need(DISC, (r, mid, cur))) for (mid, y) in invspred[(k0, jot)])
                jd[(r, cur, k0, jot)] = pydiv(jot, den)
            end
            if with_wd
                for ((k0, jot), ys) in invst
                    if (k0, jot) in kage
                        for y in ys
                            w = psum(pydiv(get(DISC, (r, y, cur), 0.0), need(DISC, (r, mid, cur))) for (mid, yy) in invspred[(k0, jot)] if yy == y)
                            w != 0 && (wd[(r, cur, k0, jot, y)] = w * jd[(r, cur, k0, jot)])
                        end
                    else
                        for y in ys
                            y in K && (wd[(r, cur, k0, jot, y)] = 1.0)
                        end
                    end
                end
            end
        end
    end
    dofix(invstep, false)
    # --- Decommissioning spreads (eqobjinv.mod, Cases III): OBJ_SUMIII(R,V,P,LL,K,Y)
    sumiii = Dict{K3,Vector{Tuple{Int,Int,Int}}}()
    for k in sums3
        dl = rnd(need(DLIFE, k))
        dl > nage && continue
        f = pyceil(need(TLIFE, k) + get(DLAG, k, 0.0))
        out = Set{Tuple{Int,Int,Int}}()
        for (_life, y0, jot) in get(sumii, k, ())
            y0 in K_EOH || continue
            if i2(k)
                if dl <= maxlife && y0 in K
                    for a in 1:dl
                        (y0 + a - 1) in ALL && (y0 + a - 1 + f) in ALL && push!(out, (y0, y0, y0 + a - 1 + f))
                    end
                end
            else
                for (mid, y) in get(invspred, (y0, jot), KJ[])
                    (mid + f) in ALL && push!(out, (mid, y, mid + f))
                end
            end
        end
        isempty(out) || (sumiii[k] = sort!(collect(out)))
    end

    # ------------------------------------------------------------------ eqobjfix.mod
    # --- OBJ_FCUR;  OPTION OBJ_YES < OBJ_FCUR;  OBJ_YES(RTP_OFF(R,T,P))$(NOT NCAP_PASTI(R,T,P)) = NO;
    yes2 = Set{K3}(k[1:3] for k in fcur)
    filter!(k -> !(k in off && k[2] in T && !haskey(PASTI, k)), yes2)
    # --- OBJ_DIVIV(OBJ_YES(R,V,P)) = MAX(1,MIN(CARD(AGE),CEIL(NCAP_TLIFE(R,V,P)-0.5)));
    #     OBJ_DIVIV(OBJ_YES(R,PYR_S(V),P))$PRC_RESID(R,'0',P)=MAX(2,SMAX(T$(PRC_RESID(R,T,P)>0),E(T))-MIYR_V1+2);
    diviv = Dict{K3,Float64}(k => pymax(1, pymin(nage, pyceil(need(TLIFE, k) - 0.5))) for k in yes2)
    for (r, v, p) in yes2
        if v in PYR_S && (r, p) in resid0
            m = -Inf
            for t in T
                get(resid, (r, t, p), 0.0) > 0 && (m = pymax(m, Float64(need(E, t))))
            end
            diviv[(r, v, p)] = pymax(2, m - MIYR_V1 + 2)
        end
    end
    # --- RTP_SHAPE(OBJ_YES(RTP),'1',J+MAX(0,NCAP_FOMX(RTP)-1),J+MAX(0,NCAP_FOMM(RTP)-1))$(NCAP_FOMX+NCAP_FOMM+NCAP_CPX) = YES;  '2', '3'
    #     OPTION RTP_ISHPR < RTP_SHAPE;  RTP_SHAPE(RTP_SHAPE(RTP,J,'1','1'))$(NOT NCAP_CPX(RTP)) = NO;
    ix(d, k) = 1 + pymax(0, rnd(get(d, k, 0.0)) - 1)
    jfom = Dict{K3,KJ}(k => (ix(FOMX, k), ix(FOMM, k)) for k in yes2 if k in CPX || haskey(FOMX, k) || haskey(FOMM, k))
    jtax = Dict{K3,KJ}(k => (ix(TAXX, k), ix(TAXM, k)) for k in yes2 if haskey(TAXX, k) || haskey(TAXM, k))
    jsub = Dict{K3,KJ}(k => (ix(SUBX, k), ix(SUBM, k)) for k in yes2 if haskey(SUBX, k) || haskey(SUBM, k))
    ishpr = union(Set{K3}(keys(jfom)), keys(jtax), keys(jsub))
    rtp_shape = Dict{K3,KJ}(k => j for (k, j) in jfom if j != (1, 1) || k in CPX)
    rtp_shape2 = Dict{K3,KJ}(k => j for (k, j) in jtax if j != (1, 1) || k in CPX)
    rtp_shape3 = Dict{K3,KJ}(k => j for (k, j) in jsub if j != (1, 1) || k in CPX)
    # 1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),SHAPE(J,AGE)*MULTI(JJ,Y_EOH)-1)   (shape: the curves of '2' or '3' instead)
    function shp(k, a, ye, shape=rtp_shape)
        j = get(shape, k, nothing)
        j === nothing ? 1.0 : get(SHP, (j[1], a), 0.0) * get(MUL, (j[2], ye), 0.0)
    end
    # 1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),MULTI(JJ,Y_EOH)-1): the multiplier curve alone
    function mul(k, ye, shape)
        j = get(shape, k, nothing)
        j === nothing ? 1.0 : 1 + (get(MUL, (j[2], ye), 0.0) - 1)
    end
    sumiv = Dict{K3,Vector{Tuple{Int,Int,Int}}}()
    sizehint!(sumiv, length(yes2))
    for k in yes2
        r, v, p = k
        lst = Tuple{Int,Int,Int}[]
        if is2a(k)
            # --- OBJ_SUMIV(LL+(B(LL)+NCAP_ILED(R,LL,P)-YEARVAL(LL)),OBJ_YES(OBJ_2A(R,V(LL),P)),'1',AGE+(OBJ_DIVIV(R,LL,P)-1)) = YES;
            push!(lst, (v + rnd(need(B, v) + get(ILED, k, 0.0) - v), 1, trunc(Int, diviv[k])))
        elseif is2b(k)
            # --- Z = NCAP_TLIFE(R,T,P); MY_F = ROUND(B(T)+NCAP_ILED(R,T,P))-YEARVAL(T);
            #     FOR(OBJ_C = 1 TO COEF_RPTI(R,T,P), F = MY_F; MY_F = F+Z; CNT = ROUND(MY_F)-ROUND(F)-1; OBJ_SUMIV(LL+F,R,T,P,'1',AGE+CNT) = YES);
            zz = need(TLIFE, k)
            mf = Float64(rnd(need(B, v) + get(ILED, k, 0.0)) - v)
            for _ in 1:pyfloor(need(RPTI, k))
                f, mf = mf, mf + zz
                push!(lst, (v + rnd(f), 1, trunc(Int, rnd(mf) - rnd(f) - 1) + 1))
            end
        elseif is1a(k)
            y0, jot = start(v)
            push!(lst, (y0, jot, trunc(Int, diviv[k])))
        elseif v in T
            zz = need(TLIFE, k)
            if rnd(zz) - (classic ? need(IPD, v) : 1) <= 0
                push!(lst, (need(B, v) - (classic ? pyceil(zz / 2 - 0.5) : fld(rnd(zz), 2)), trunc(Int, rnd(need(RPTI, k) * zz) - 1) + 1,
                            trunc(Int, diviv[k])))
            else
                cnt = classic ? need(IPD, v) : pymin(need(IPD, v), rnd(zz))
                # --- CNT = %ISTEP%; OBJ_D = CNT-1; MY_F = B(T)-YEARVAL(T)-FLOOR(CNT/2);
                #     FOR(OBJ_C = 1 TO COEF_RPTI(R,T,P), F = MY_F; MY_F = F+Z; CNT = ROUND(MY_F)-ROUND(F)-1; OBJ_SUMIV(LL+F,R,T,P,AGE+OBJ_D,AGE+CNT) = YES)
                mf = Float64(need(B, v) - v - floor(Int, cnt / 2))
                for _ in 1:pyfloor(need(RPTI, k))
                    f, mf = mf, mf + zz
                    push!(lst, (v + rnd(f), cnt, trunc(Int, rnd(mf) - rnd(f) - 1) + 1))
                end
            end
        end
        # --- OBJ_SUMIV(OBJ_SUMIV(K_EOH,R,PASTMILE,P,JOT,AGE))$(NOT NCAP_PASTI(R,PASTMILE,P)) = NO;
        sumiv[k] = [(y0, jot, life) for (y0, jot, life) in lst if y0 in ALL && 1 <= jot <= nage && 1 <= life <= nage &&
                    !(v in PASTMILE && y0 in K_EOH && !haskey(PASTI, k))]
    end
    # --- Cases IV.2.a / IV.2.b: Surveillance (decommissioning delay, NCAP_DLAGC), only with a lead time: OBJ_SUMIVS(R,V,P,K,Y)
    sumivs = Dict{K3,Vector{KJ}}()
    for k in rtp
        (k in dlc_v && !(k[2] in PASTMILE && !haskey(PASTI, k))) || continue
        r, v, p = k
        if is2a(k)
            starts = Float64[get(B, v, 0) + get(ILED, k, 0.0)]
        elseif is2b(k)
            starts = Float64[need(B, v) + get(ILED, k, 0.0) + (cc - 1) * need(TLIFE, k) for cc in 1:pyfloor(need(RPTI, k))]
        else
            continue
        end
        out = KJ[]
        for s0 in starts
            f = rnd(s0 + need(TLIFE, k))
            zz = f + get(DLAG, k, 0.0)
            kk = v + rnd(s0 - v)
            if kk in ALL
                for y in f:pyceil(zz)-1
                    y in ALL && !((kk, y) in out) && push!(out, (kk, y))
                end
            end
        end
        isempty(out) || (sumivs[k] = sort!(out))
    end
    # --- OBJ_LIFE(K,R,JOT,LIFE,CUR): present value of the years of operation that start in year K
    lifekeys = Set{Tuple{Int32,Int,Int,Int}}()
    for (k, lst) in sumiv, (y0, jot, life) in lst
        y0 in K && push!(lifekeys, (k[1], y0, jot, life))
    end
    invstep2 = steps(Set{KJ}((y0, jot) for (_, y0, jot, _l) in lifekeys))
    # --- LOOP(KAGE(K,JOT),OBJ_LIFE(LL,R,JOT,LIFE,CUR)$INVSTEP(K,JOT,LL,JOT) $= OBJ_LIFE(K,R,JOT,LIFE,CUR));  (chained, as GAMS does it)
    lifeyrs = copy(lifekeys)
    by = Dict{Int,Set{Tuple{Int32,Int}}}()
    for (r, y0, jot, life) in lifekeys
        push!(get!(() -> Set{Tuple{Int32,Int}}(), by, jot), (r, life))
    end
    for (k0, jot) in sort!(collect(Set{KJ}((y0, jot) for (_, y0, jot, _l) in lifekeys)))
        for (r, life) in by[jot]
            if (r, k0, jot, life) in lifeyrs
                for y in get(invstep2, (k0, jot), Int[])
                    push!(lifeyrs, (r, y, jot, life))
                end
            end
        end
    end
    objlife = Dict{Tuple{Int,Int32,Int,Int,Int32},Float64}()
    for (r, y, jot, life) in lifeyrs, cur in curs(r)
        if y in K && life <= maxlife
            val = psum(get(DISC, (r, yy, cur), 0.0) for yy in y:y+life-1 if yy in Y_EOH)
            val != 0 && (objlife[(y, r, jot, life, cur)] = val)
        end
    end
    dofix(invstep2, true)
    # --- OBJ_DIVIV(OBJ_YES(R,PASTMILE,P)) = 1;  OBJ_DIVIV(OBJ_YES(R,T,P)) = MAX(1,MIN(IPD(T),ROUND(NCAP_TLIFE(R,T,P)))$(OBJ_1B(R,T,P)+OBJ_1A(R,T,P)));
    for k in yes2
        r, v, p = k
        if classic
            # --- (eqobjfix.mod, CTST '') OBJ_DIVIV(OBJ_YES(R,PASTMILE,P)) = 1;  OBJ_DIVIV(OBJ_YES(R,T,P))$(NOT OBJ_1B(R,T,P)) = 1+(IPD(T)-1)$OBJ_1A(R,T,P);
            #     IF(ALTOBJ, OBJ_DIVIV(OBJ_1B(OBJ_YES(R,T,P)))$((ROUND(NCAP_TLIFE(R,T,P))-IPD(T)%CTST%) GT 0) = IPD(T));
            v in PASTMILE && (diviv[k] = 1)
            v in T && !is1b(k) && (diviv[k] = 1 + (is1a(k) ? need(IPD, v) - 1 : 0))
            if v in T && is1b(k) && ALTOBJ != 0 && rnd(need(TLIFE, k)) - need(IPD, v) > 0
                diviv[k] = need(IPD, v)
            end
            continue
        end
        v in PASTMILE && (diviv[k] = 1)
        v in T && (diviv[k] = pymax(1, (is1a(k) || is1b(k)) ? pymin(need(IPD, v), rnd(need(TLIFE, k))) : 0))
    end
    # --- LOOP(PYR_S(V), LOOP((OBJ_SUMIV(V,R,V,P,JOT,LIFE),G_RCUR(R,CUR))$PRC_RESID(R,'0',P),
    #        OBJ_DIVIV(R,V,P) = NCAP_PASTI(R,V,P)*OBJ_LIFE(V,R,JOT,LIFE,CUR)/SUM(VNT(V,T)$PRC_RESID(R,T,P),PRC_RESID(R,T,P)*OBJ_PVT(R,T,CUR))));
    if !classic
        for k in yes2
            r, v, p = k
            if v in PYR_S && (r, p) in resid0 && haskey(grcur, r)
                cur = grcur[r]
                for (y0, jot, life) in sumiv[k]
                    if y0 == v
                        den = psum(need(resid, (r, t, p)) * get(PVT, (r, t, cur), 0.0) for t in get(vnt, v, Int[]) if get(resid, (r, t, p), 0.0) != 0)
                        diviv[k] = pydiv(get(PASTI, k, 0.0) * get(objlife, (v, r, jot, life, cur), 0.0), den)
                    end
                end
            end
        end
    end

    # ------------------------------------------------------------------ eqobsalv.mod: salvage share of each investment step
    # (eoh, for the horizon of the model: miyr = MIYR_VL, Y_EOH, OBJ_LIFE as above)
    miyr = MIYR_VL
    all_v = VNRET || classic                # PFT is '' with CTST '': every vintage, past ones too
    # --- OBJ_SALI(OBJ_SUMII(R,V%PFT%,P,AGE,K_EOH,JOT),K,LL--ORD(LL))$((YEARVAL(K)+NCAP_TLIFE(R,V,P)-1>MIYR_VL)$INVSPRED(K_EOH,JOT,K,LL))=YES;
    #     OPTION OBJ_SUMSI <= OBJ_SALI;  LOOP((RP(R,PRC),P)$PRC_REFIT(RP,P),IF(PRC_REFIT(RP,P)<0, OBJ_SUMSI(R,T,P,K)=NO));  OPTION OBJ_SUMS <= OBJ_SUMSI;
    mids = Dict{K3,Vector{Int}}()                         # OBJ_SUMSI by vintage
    sumsi = Set{Tuple{Int32,Int,Int32,Int}}()
    for k in yes
        r, v, p = k
        (!(all_v || v in T) || (v in T && (r, p) in retro)) && continue
        for (_, y0, jot) in get(sumii, k, ())
            y0 in K_EOH || continue
            for (mid, _y) in get(invspred, (y0, jot), KJ[])
                if mid in K && mid + need(TLIFE, k) - 1 > miyr
                    push!(sumsi, (r, v, p, mid))
                end
            end
        end
    end
    sums = Set{K3}(kk[1:3] for kk in sumsi)
    # --- LOOP(OBJ_SUMIVS(R,V,P,K,Y)$(YEARVAL(K)+NCAP_TLIFE(R,V,P)-1 GT MIYR_VL), OBJ_SUMS3(R,V,P) = YES; OBJ_SUMSI(R,V,P,K) = YES);
    survs3 = Set{K3}()
    for (k, lst) in sumivs, (kk, _y) in lst
        if kk + need(TLIFE, k) - 1 > miyr
            push!(survs3, k)
            push!(sumsi, (k[1], k[2], k[3], kk))
        end
    end
    for (r, v, p, mid) in sumsi
        push!(get!(() -> Int[], mids, (r, v, p)), mid)
    end
    # --- SALV_INV(OBJ_SUMSI(R,V,P,K))$OBJ_ICUR(R,V,P,CUR) = MIN(1,(((1+G_DRATE)*EXP(NCAP_FDR))**(NCAP_TLIFE+YEARVAL(K)-MIYR_VL-1)-1) /
    #                                                              (((1+G_DRATE)*EXP(NCAP_FDR))**NCAP_TLIFE-1));
    salv = Dict{Tuple{Int32,Int,Int32,Int},Float64}()
    for (r, v, p, cur) in icur
        k = (r, v, p)
        ms = get(mids, k, nothing)
        ms === nothing && continue
        tl, dr, fd = need(TLIFE, k), get(GDR, (r, v, cur), 0.0), get(FDR, k, 0.0)
        for mid in ms
            g = (1 + dr) * pyexp(fd)
            salv[(r, v, p, mid)] = pymin(1, pydiv(pypow(g, ((tl + mid) - miyr) - 1) - 1, pypow(g, tl) - 1))
        end
    end
    # --- Shape-reduced salvage at EOH+1:  Z = SMAX(T$(B(T)<=MIYR_VL+1),ORD(T)-1);
    #     LOOP(MIYR_1(T-Z), SALV_INV(OBJ_SUMSI(RTP,K))$NCAP_CPX(RTP) = SALV_INV(RTP,K)*(1+RTP_CPX(RTP,T)));
    if !isempty(CPX)
        ts_ = [t for t in T if need(B, t) <= miyr + 1]
        isempty(ts_) && throw(Decline("no period begins by MIYR_VL+1 (the reference raises)"))
        tl_ = maximum(ts_)
        for key in collect(keys(salv))
            (key[1], key[2], key[3]) in CPX && (salv[key] *= 1 + get(RCPX, (key[1], key[2], key[3], tl_), 0.0))
        end
    end
    # --- LOOP(MIYR_1(LL), F = MIYR_VL+1-YEARVAL(MIYR_1); OBJ_DCEOH(RDCUR(R,CUR)) = OBJ_DISC(R,LL+F,CUR));
    dceoh = Dict{Tuple{Int32,Int32},Float64}()
    for r in rdorder, cur in rdcur[r]
        dceoh[(r, cur)] = get(DISC, (r, trunc(Int, miyr) + 1, cur), 0.0)
    end
    # --- OBJSCC(OBJ_ICUR(OBJ_SUMS(R,V,P),CUR)) = COR_SALVI(R,V,P,CUR) / OBJ_DCEOH(R,CUR) / OBJ_DIVI(R,V,P) *
    #       SUM((OBJ_SUMII(R,V,P,AGE,K_EOH,JOT),INVSPRED(K_EOH,JOT,LL,K))$SALV_INV(R,V,P,LL),OBJ_JD(R,CUR,K_EOH,JOT)*
    #           (OBJ_ICOST(R,K,P,CUR)+OBJ_ITAX(R,K,P,CUR)-OBJ_ISUB(R,K,P,CUR)) * SALV_INV(R,V,P,LL) * OBJ_DISC(R,K,CUR));
    #     OBJ_IAD(RDCUR(R,CUR)) = SUM(OBJ_ICUR(OBJ_SUMS(R,PASTMILE(V),P),CUR)$((OBJ_PASTI(R,V,P,CUR)=0)+0%CTST%),
    #                                 OBJSCC(R,V,P,CUR)*NCAP_PASTI(R,V,P)*OBJ_DCEOH(R,CUR));
    objscc = Dict{K4,Float64}()
    iad = Dict{Tuple{Int32,Int32},Float64}()
    iadorder = Tuple{Int32,Int32}[]
    for (r, v, p, cur) in icur
        k = (r, v, p)
        k in sums || continue
        tot, rec = 0.0, false
        for (_, y0, jot) in sumii[k]
            y0 in K_EOH || continue
            jd_ = JDf((r, cur, y0, jot))
            sx = KJ[]
            sxv = Float64[]
            for (mid, y) in get(invspred, (y0, jot), KJ[])
                sv = get(salv, (r, v, p, mid), 0.0)
                sv != 0 && (push!(sx, (y, 0)); push!(sxv, sv))
            end
            tot += psum(jd_ * get(ICOST, (r, p, cur, sx[i][1]), 0.0) * sxv[i] * get(DISC, (r, sx[i][1], cur), 0.0) for i in eachindex(sx))
            rec = rec || any(onrecord(ICOST, (r, p, cur, y)) for (y, _) in sx)
        end
        val = pydiv(pydiv(cor[(r, v, p, cur)], need(dceoh, (r, cur))), need(divi, k)) * tot
        if val != 0 || rec
            objscc[(r, v, p, cur)] = val
            if v in PASTMILE && (!classic || get(opasti, (r, v, p, cur), 0.0) == 0)
                haskey(iad, (r, cur)) || push!(iadorder, (r, cur))
                iad[(r, cur)] = get(iad, (r, cur), 0.0) + val * get(PASTI, k, 0.0) * dceoh[(r, cur)]
            end
        end
    end
    # ------------------------------------------------------------------ eqobsalv.mod: decommissioning
    # --- LOOP(OBJ_SUMIII(OBJ_SUMS(R,V,P),LL,K,Y), OBJ_SUMS3(R,V,P) = YES);
    sums3s = Set{K3}(k for k in keys(sumiii) if k in sums)
    union!(sums3s, survs3)
    # --- EQ_OBJSALV, Cases IV: SUM(OBJ_SUMIVS(R,V,P,K,Y)$SALV_INV(R,V,P,K), OBJ_DISC(R,Y,CUR) * OBJ_DLAGC(R,K,P,CUR) * SALV_INV(R,V,P,K) * ...)
    #     stored per unit of capacity as OBJ_SALVS
    salvs = Dict{K4,Float64}()
    for (k, lst) in sumivs
        r, v, p = k
        for cur in curs(r)
            tm = KJ[(kk, y) for (kk, y) in lst if get(salv, (r, v, p, kk), 0.0) != 0]
            if !isempty(tm)
                salvs[(r, v, p, cur)] = psum(get(DISC, (r, y, cur), 0.0) * get(DLC, (r, p, cur, kk), 0.0) * salv[(r, v, p, kk)] for (kk, y) in tm)
            end
        end
    end
    # --- COR_SALVD(RTP(R,V,P),CUR)$OBJ_DCOST(R,V,P,CUR) = (((1-1/(1+NCAP_DRATE))*(1-1/(1+OBJ_RFR)**NCAP_DELIF)) /
    #        ((1-1/(1+OBJ_RFR))*(1-1/(1+NCAP_DRATE)**NCAP_DELIF)))$(NCAP_DRATE GT 0) + 1$(NCAP_DRATE EQ 0);
    #     OBJ_CRFD(RTP(R,V,P),CUR)$OBJ_DCOST(R,V,P,CUR) = COR_SALVD * (1-(1/(1+G_DRATE))) / (1-(1+G_DRATE)**(-ROUND(NCAP_DELIF)));
    corsd, crfd_d = Dict{K4,Float64}(), Dict{K4,Float64}()
    corsd_order = K4[]
    for (r, p, cur, v) in keys(DCC)
        k = (r, v, p)
        (k in rtpset && cur in curs(r)) || continue
        ndr, rf, de, dr = get(NDR, k, 0.0), get(RFR, (r, v, cur), 0.0), get(DELIF, k, 0.0), get(GDR, (r, v, cur), 0.0)
        x = ndr > 0 ? pydiv((1 - pydiv(1, 1 + ndr)) * (1 - pydiv(1, pypow(1 + rf, de))),
                            (1 - pydiv(1, 1 + rf)) * (1 - pydiv(1, pypow(1 + ndr, de)))) : 1.0
        haskey(corsd, (r, v, p, cur)) || push!(corsd_order, (r, v, p, cur))
        corsd[(r, v, p, cur)] = x
        crfd_d[(r, v, p, cur)] = pydiv(x * (1 - pydiv(1, 1 + dr)), 1 - pypow(1 + dr, -rnd(de)))
    end
    dcost(r, kk, p, cur) = get(DCC, (r, p, cur, kk), 0.0)
    # --- SALV_DEC(OBJ_SUMS3(R,V,P),CUR)$COR_SALVD(R,V,P,CUR) = COR_SALVD(R,V,P,CUR) / OBJ_DIVIII(R,V,P) / OBJ_DCEOH(R,CUR) *
    #       SUM(OBJ_SUMIII(R,V,P,LL,K,Y)$SALV_INV(R,V,P,LL),SALV_INV(R,V,P,LL)*OBJ_DCOST(R,K,P,CUR)*OBJ_DISC(R,Y,CUR));
    salvdec = Dict{K4,Float64}()
    for key in corsd_order
        r, v, p, cur = key
        k = (r, v, p)
        k in sums3s || continue
        tot = psum(salv[(r, v, p, ll)] * dcost(r, kk, p, cur) * get(DISC, (r, y, cur), 0.0)
                   for (ll, kk, y) in need(sumiii, k) if get(salv, (r, v, p, ll), 0.0) != 0)
        f = pydiv(pydiv(corsd[key], need(diviii, k)), need(dceoh, (r, cur)))
        val = f * tot
        if val != 0
            salvdec[key] = val
        elseif f != 0 && any(get(DCC, (r, p, cur, kk), NaN) == 0.0 && get(DISC, (r, y, cur), 0.0) != 0
                             for (ll, kk, y) in need(sumiii, k) if get(salv, (r, v, p, ll), 0.0) != 0)
            salvdec[key] = 0.0                       # a decommissioning cost given as EPS: EPS, a record
        end
    end
    # --- EQ_OBJINV, Cases III: SUM(OBJ_SUMIII(R,V,P,LL,K,Y)$OBJ_DCOST(R,V,P,CUR), OBJ_DISC(R,Y,CUR) * COR_SALVD(R,V,P,CUR) * OBJ_DCOST(R,K,P,CUR) * ... / OBJ_DIVIII(R,V,P))
    #     stored per unit as OBJ_CDEC
    cdec = Dict{K4,Float64}()
    for key in corsd_order
        r, v, p, cur = key
        k = (r, v, p)
        (haskey(sumiii, k) && haskey(DCC, (r, p, cur, v))) || continue
        x = corsd[key]
        val = pydiv(psum(get(DISC, (r, y, cur), 0.0) * x * dcost(r, kk, p, cur) for (ll, kk, y) in sumiii[k]), need(diviii, k))
        val != 0 && (cdec[key] = val)
    end

    # ------------------------------------------------------------------ eqobjann.tm, COEF section
    obinv, obfix, cinv, cfix = newtable(4, 1), newtable(4, 1), newtable(4, 1), newtable(4, 1)
    for (r, v, p, cur) in icur
        k = (r, v, p)
        dr = get(GDR, (r, v, cur), 0.0)
        c = 0.0
        v in T && (c += cptpv(r, v, p, cur))
        kc = v + rnd(need(B, v) - v + get(ILED, k, 0.0))   # the commissioning year (the lag is rounded)
        if v in PASTMILE && kc in K
            c += pydiv(get(DISC, (r, kc, cur), 0.0) * (1 - pypow(1 + dr, -need(TLIFE, k))), 1 - pydiv(1, 1 + dr))
        end
        val, rec, ann = 0.0, false, false
        tot = gross = 0.0
        crv, dv, inT = cor[(r, v, p, cur)], need(divi, k), v in T
        for (_, y0, jot) in sumii[k]
            y0 in K_EOH || continue
            sp = get(invspred, (y0, jot), KJ[])
            inner = psum(get(DISC, (r, y, cur), 0.0) * (1 - (inT ? get(salv, (r, v, p, mid), 0.0) : 0.0)) * get(ICOST, (r, p, cur, y), 0.0)
                         for (mid, y) in sp)
            whole = psum(get(DISC, (r, y, cur), 0.0) * get(ICOST, (r, p, cur, y), 0.0) for (mid, y) in sp)
            rec = rec || any(onrecord(ICOST, (r, p, cur, y)) for (mid, y) in sp)
            # --- eqobjann.tm 54: (OBJ_ICOST(R,K,P,CUR) + (OBJ_ITAX(R,K,P,CUR) - OBJ_ISUB(R,K,P,CUR))%2)
            ann = ann || any(epsgrouped(ICOST, (r, p, cur, y)) for (mid, y) in sp)
            jd_ = JDf((r, cur, y0, jot))
            tot += pydiv(jd_ * inner * crv, dv)
            gross += pydiv(jd_ * whole * crv, dv)
        end
        # --- EQ_OBJINV: SUM(OBJ_SUMII(..K_EOH,JOT), OBJ_JD * SUM(INVSPRED, OBJ_DISC*(OBJ_ICOST+OBJ_ITAX-OBJ_ISUB)) * COR_SALVI / OBJ_DIVI)
        (gross != 0 || rec) && row!(cinv, (r, v, p, cur), (gross,))
        tot += get(cdec, (r, v, p, cur), 0.0)            # Cases III: decommissioning
        if c != 0
            val = tot / c
        else
            rec = ann = false
        end
        if v in PASTMILE && (r, p) in resid0
            val = crf[(r, v, p, cur)] * get(ICOST, (r, p, cur, v), 0.0)
        end
        (val != 0 || rec || ann) && row!(obinv, (r, v, p, cur), (val,))
    end
    for (r, v, p, cur) in fcur
        k = (r, v, p)
        c = cptpv(r, v, p, cur)
        lst = k in yes2 ? get(sumiv, k, Tuple{Int,Int,Int}[]) : Tuple{Int,Int,Int}[]
        # --- eqobjann.tm 68-69: COEF_CRF(OBJ_FCUR(R,V,P,CUR)) = SUM(RTP_CPTYR(R,V,T,P),COEF_CPT(R,V,T,P)*OBJ_PVT(R,T,CUR));
        #     $IFI NOT %ANNCOST%==LEV COEF_CRF(OBJ_FCUR(R,PASTMILE(V),P,CUR)) = SUM(OBJ_SUMIV(K_EOH,R,V,P,JOT,LIFE),OBJ_LIFE(K_EOH,R,JOT,LIFE,CUR));
        if v in PASTMILE && !lev
            c = psum(get(objlife, (y0, r, jot, life, cur), 0.0) for (y0, jot, life) in lst if y0 in K_EOH)
        end
        val = 0.0
        rec = ann = false                             # an EPS cost gives an EPS coefficient
        tot = 0.0
        shaped = k in ishpr
        for (y0, jot, life) in lst
            y0 in K_EOH || continue
            sp = get(invspred, (y0, jot), KJ[])
            # (EPS: a cost on record that is EPS; a cost with a value times a shape of 0 is 0, no record:
            #  OBJ_FOM * (1+SHAPE(J,AGE)*MULTI(JJ,Y_EOH)-1) with SHAPE or MULTI EPS)
            rec = rec || any(get(FOMC, (r, p, cur, y), NaN) == 0.0 && onrecord(FOMC, (r, p, cur, y)) for (mid, y) in sp)
            # --- eqobjann.tm 79: (OBJ_FOM(R,K,P,CUR)+(OBJ_FTX(R,K,P,CUR)-OBJ_FSB(R,K,P,CUR))%2)
            ann = ann || any(epsgrouped(FOMC, (r, p, cur, y)) for (mid, y) in sp)
            if !shaped
                tot += pydiv(psum(get(objlife, (mid, r, jot, life, cur), 0.0) * WDf((r, cur, y0, jot, y)) * get(FOMC, (r, p, cur, y), 0.0)
                                  for (mid, y) in sp), diviv[k])
            elseif life <= maxlife
                # --- SUM((INVSPRED(K_EOH,JOT,LL,K),OPYEAR(LIFE,AGE),Y_EOH(LL+(ORD(AGE)-1))),
                #       OBJ_DISC(R,Y_EOH,CUR) * (1+SUM(PERIODYR(T,Y_EOH),RTP_CPX(R,V,P,T))$NCAP_CPX(R,V,P)) * %CAPWD%
                #       (OBJ_FOM(R,K,P,CUR) * (1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),SHAPE(J,AGE)*MULTI(JJ,Y_EOH)-1)) + ...)) / OBJ_DIVIV(R,V,P)
                for (mid, y) in sp
                    ftx, fsb = get(FTX, (r, p, cur, y), 0.0), get(FSB, (r, p, cur, y), 0.0)
                    if (ftx != 0 || fsb != 0) && (haskey(rtp_shape2, k) || haskey(rtp_shape3, k) || get(rtp_shape, k, (1, 1)) != (1, 1))
                        # --- (OBJ_FOM * (1+..'1'..) + OBJ_FTX * (1+..'2'..) - OBJ_FSB * (1+..'3'..)): each by its curve
                        fo = get(FOM, (r, p, cur, y), 0.0)
                        w_ = WDf((r, cur, y0, jot, y))
                        tot += pydiv(w_ * psum(get(DISC, (r, ye, cur), 0.0) * (1 + get_rcpx(RCPX, r, v, p, period_of, ye))
                                               * (fo * shp(k, a, ye) + ftx * shp(k, a, ye, rtp_shape2) - fsb * shp(k, a, ye, rtp_shape3))
                                               for (a, ye) in ((a, mid + a - 1) for a in 1:life) if ye in Y_EOH), diviv[k])
                        continue
                    end
                    w = WDf((r, cur, y0, jot, y)) * get(FOMC, (r, p, cur, y), 0.0)
                    if w != 0
                        tot += pydiv(w * psum(get(DISC, (r, ye, cur), 0.0) * (1 + get_rcpx(RCPX, r, v, p, period_of, ye)) * shp(k, a, ye)
                                              for (a, ye) in ((a, mid + a - 1) for a in 1:life) if ye in Y_EOH), diviv[k])
                    end
                end
            end
        end
        # --- Case V - Decommissioning Surveillance:  SUM(OBJ_SUMIVS(R,V,P,K,Y), OBJ_DISC(R,Y,CUR) * OBJ_DLAGC(R,K,P,CUR))
        if haskey(sumivs, k)
            rec = rec || any(haskey(DLC, (r, p, cur, kk)) for (kk, y) in sumivs[k])
            tot += psum(get(DISC, (r, y, cur), 0.0) * get(DLC, (r, p, cur, kk), 0.0) for (kk, y) in sumivs[k])
        end
        # --- EQ_OBJFIX: the same sums, not divided by the capital recovery of the annualised form
        (tot != 0 || rec) && row!(cfix, (r, v, p, cur), (tot,))
        if c != 0
            val = tot / c
        else
            rec = ann = false
        end
        if v in PASTMILE && (r, p) in resid0
            den = psum(pydiv(need(resid, (r, t, p)), need(PASTI, k)) * get(PVT, (r, t, cur), 0.0)
                       for t in get(vnt, v, Int[]) if get(resid, (r, t, p), 0.0) != 0)
            val = pydiv(val * c, den)
        end
        (val != 0 || rec || ann) && row!(obfix, (r, v, p, cur), (val,))
    end

    # ------------------------------------------------------------------ prepret.dsc, label OBJFIX (term of EQ_ANNFIX)
    # --- SUM((OBJ_SUMIV(K_EOH,R,V,P,JOT,LIFE),VNTRT(V,T))$RVPRL(R,V,P),
    #       SUM((INVSPRED(K_EOH,JOT,LL,K),KTYAGE(LL,T,Y_EOH,AGE))$OPYEAR(LIFE,AGE),
    #           -OBJ_DISC(R,Y_EOH,CUR) * %CAPWD% (OBJ_FOM(R,K,P,CUR)+OBJ_FTX(R,K,P,CUR)-OBJ_FSB(R,K,P,CUR))) *
    #       %VART%_SCAP(R,V,T,P) / OBJ_DIVIV(R,V,P))
    #     stored as COEF_OBFIXR(R,V,T,P,CUR)
    obfixr = newtable(5, 1)
    if VNRET
        # --- SUM(RTP_CPTYR(R,PYR_S(V(K)),T,P)$((NOT RVPRL(R,V,P))$PRC_RCAP(R,P)), ... %VART%_SCAP(R,V,T,P))    'RESIDS require special handling'
        #     SUM(PERIODYR(T,Y_EOH), -OBJ_DISC(R,Y_EOH,CUR) * (OBJ_FOM(R,K,P,CUR) * (1+SUM(RTP_SHAPE(R,V,P,'1',J,JJ),MULTI(JJ,Y_EOH)-1)) + FTX - FSB))
        for (r, v, p, cur) in fcur
            k = (r, v, p)
            for t in get(cptyr_res, k, Int[])
                w = get(FOMC, (r, p, cur, v), 0.0)
                local tot
                if any(get(sh, k, (1, 1))[2] != 1 for sh in (rtp_shape, rtp_shape2, rtp_shape3))
                    fo, ftx, fsb = get(FOM, (r, p, cur, v), 0.0), get(FTX, (r, p, cur, v), 0.0), get(FSB, (r, p, cur, v), 0.0)
                    tot = -psum(get(DISC, (r, ye, cur), 0.0) * (fo * mul(k, ye, rtp_shape) + ftx * mul(k, ye, rtp_shape2)
                                                               - fsb * mul(k, ye, rtp_shape3)) for ye in get(peryr, t, Int[]))
                else
                    tot = -w * psum(get(DISC, (r, ye, cur), 0.0) for ye in get(peryr, t, Int[]))
                end
                rec = w == 0 && onrecord(FOMC, (r, p, cur, v)) && !isempty(get(peryr, t, Int[]))
                (tot != 0 || rec) && row!(obfixr, (r, v, t, p, cur), (tot,))
            end
        end
        for (r, v, p, cur) in fcur
            k = (r, v, p)
            (k in rvprl && k in yes2) || continue
            for t in get(vntrt, v, Int[])
                tot = 0.0
                rec = false
                pt = get(peryr, t, Int[])
                for (y0, jot, life) in sumiv[k]
                    (!(y0 in K_EOH) || life > maxlife) && continue
                    for (mid, y) in get(invspred, (y0, jot), KJ[])
                        w = WDf((r, cur, y0, jot, y)) * get(FOMC, (r, p, cur, y), 0.0)
                        # a fixed cost given as 0 (EPS) leaves an EPS coefficient on the retired capacity
                        if w == 0 && !rec && onrecord(FOMC, (r, p, cur, y)) && WDf((r, cur, y0, jot, y)) != 0
                            rec = any(0 <= ye - mid < life for ye in pt)
                        end
                        ftx, fsb = get(FTX, (r, p, cur, y), 0.0), get(FSB, (r, p, cur, y), 0.0)
                        if (ftx != 0 || fsb != 0) && (haskey(rtp_shape2, k) || haskey(rtp_shape3, k) || get(rtp_shape, k, (1, 1)) != (1, 1))
                            fo, w_ = get(FOM, (r, p, cur, y), 0.0), WDf((r, cur, y0, jot, y))
                            tot -= w_ * (1 + (k in CPX ? get(RCPX, (r, v, p, t), 0.0) : 0.0)) * psum(
                                get(DISC, (r, ye, cur), 0.0) * (fo * shp(k, ye - mid + 1, ye) + ftx * shp(k, ye - mid + 1, ye, rtp_shape2)
                                                                - fsb * shp(k, ye - mid + 1, ye, rtp_shape3))
                                for ye in pt if 0 <= ye - mid < life)
                            continue
                        end
                        if w != 0
                            # ... -OBJ_DISC(R,Y_EOH,CUR) * (1+RTP_CPX(R,V,P,T)$NCAP_CPX(R,V,P)) * %CAPWD% (OBJ_FOM * (1+SUM(RTP_SHAPE,SHAPE*MULTI-1)) ...)
                            shaped = k in ishpr
                            tot -= w * (1 + (k in CPX ? get(RCPX, (r, v, p, t), 0.0) : 0.0)) * psum(
                                get(DISC, (r, ye, cur), 0.0) * (shaped ? shp(k, ye - mid + 1, ye) : 1.0)
                                for ye in pt if 0 <= ye - mid < life)
                        end
                    end
                end
                (tot != 0 || rec) && row!(obfixr, (r, v, t, p, cur), (pydiv(tot, diviv[k]),))
            end
        end
    end

    # ------------------------------------------------------------------ the tables (eoh_tables, _write_tables)
    O = Dict{String,Table}()
    O["SCAL"] = newtable(0, 1)
    for x in (maxlife, hasE ? Float64(maxE) : 0.0, hasE ? 1.0 : 0.0)
        push!(O["SCAL"].vals[1], x)
    end
    O["FIXDL"], O["FIXTL"], O["FIXEL"] = fixdl, fixtl, fixel
    O["COEF_OBFIXR"], O["OBJ_CFIX"] = obfixr, cfix
    tb = O["SALV_INV"] = newtable(4, 1)
    for ((r, v, p, y), x) in salv
        x != 0 && row!(tb, (r, v, p, y), (x,))
    end
    tb = O["OBJ_SUMS"] = newtable(3, 0); for k in sums; row!(tb, k); end
    tb = O["OBJSCC"] = newtable(4, 1); for (k, x) in objscc; row!(tb, k, (x,)); end
    tb = O["OBJ_DCEOH"] = newtable(2, 1)
    for r in rdorder, cur in rdcur[r]
        x = dceoh[(r, cur)]
        x != 0 && row!(tb, (r, cur), (x,))
    end
    tb = O["OBJ_IAD"] = newtable(2, 1); for k in iadorder; iad[k] != 0 && row!(tb, k, (iad[k],)); end
    tb = O["OBJ_SUMS3"] = newtable(3, 0); for k in sums3s; row!(tb, k); end
    tb = O["COR_SALVD"] = newtable(4, 1); for k in corsd_order; row!(tb, k, (corsd[k],)); end
    tb = O["OBJ_CRFD"] = newtable(4, 1); for k in corsd_order; crfd_d[k] != 0 && row!(tb, k, (crfd_d[k],)); end
    tb = O["SALV_DEC"] = newtable(4, 1); for (k, x) in salvdec; row!(tb, k, (x,)); end
    tb = O["OBJ_LIFE"] = newtable(5, 1); for (k, x) in objlife; row!(tb, k, (x,)); end
    tb = O["OBJ_SALVS"] = newtable(4, 1); for (k, x) in salvs; row!(tb, k, (x,)); end
    tb = O["OBJ_ICUR"] = newtable(4, 0); for k in icur; row!(tb, k); end
    tb = O["OBJ_FCUR"] = newtable(4, 0); for k in fcur; row!(tb, k); end
    O["COEF_OBINV"], O["COEF_OBFIX"], O["OBJ_CINV"] = obinv, obfix, cinv
    tb = O["COR_SALVI"] = newtable(4, 1); for k in icur; row!(tb, k, (cor[k],)); end
    tb = O["OBJ_CRF"] = newtable(4, 1); for k in icur; row!(tb, k, (crf[k],)); end
    tb = O["OBJ_DIVI"] = newtable(3, 1); for (k, x) in divi; row!(tb, k, (x,)); end
    tb = O["OBJ_DIVIV"] = newtable(3, 1); for (k, x) in diviv; row!(tb, k, (x,)); end
    tb = O["RTP_ISHPR"] = newtable(3, 0); for k in ishpr; row!(tb, k); end
    tb = O["RTP_SHAPE"] = newtable(6, 0)
    for (n, sh) in ((1, rtp_shape), (2, rtp_shape2), (3, rtp_shape3)), (k, (j, jj)) in sh
        row!(tb, (k..., n, j, jj))
    end
    tb = O["OBJ_PASTI"] = newtable(4, 1); for (k, x) in opasti; row!(tb, k, (x,)); end
    tb = O["KAGE"] = newtable(2, 0)
    if classic
        for kj in Set{KJ}((y0, jot) for (_r, y0, jot, _l) in lifekeys); row!(tb, kj); end
    end
    tb = O["OBJ_JD"] = newtable(4, 1); for (k, x) in jd; row!(tb, k, (x,)); end
    tb = O["OBJ_WD"] = newtable(5, 1); for (k, x) in wd; row!(tb, k, (x,)); end
    tb = O["INVSPRED"] = newtable(4, 0)                    # each set's rows in Python's order (objective.py checks it)
    for ((y0, j), st) in invspred, (mid, y) in st
        row!(tb, (y0, j, mid, y))
    end
    tb = O["OBJ_SUMII"] = newtable(6, 0)
    for (k, lst) in sumii, (life, y0, jot) in lst; row!(tb, (k..., life, y0, jot)); end
    tb = O["OBJ_SUMIV"] = newtable(6, 0)
    for (k, lst) in sumiv, (y0, jot, life) in lst; row!(tb, (y0, k..., jot, life)); end
    tb = O["OBJ_YES"] = newtable(3, 0)
    classic || for k in yes2; row!(tb, k); end
    tb = O["OBJ_DIVIII"] = newtable(3, 1); for (k, x) in diviii; row!(tb, k, (x,)); end
    tb = O["OBJ_SUMIII"] = newtable(6, 0)
    for (k, lst) in sumiii, (ll, kk, y) in lst; row!(tb, (k..., ll, kk, y)); end
    tb = O["OBJ_SUMIVS"] = newtable(5, 0)
    for (k, lst) in sumivs, (kk, y) in lst; row!(tb, (k..., kk, y)); end
    tb = O["OBJ_CDEC"] = newtable(4, 1); for (k, x) in cdec; row!(tb, k, (x,)); end
    tb = O["DLC_V"] = newtable(0, 1); push!(tb.vals[1], isempty(dlc_v) ? 0.0 : 1.0)
    res = Any[]
    for name in OBJ_OUT
        append!(res, O[name].ints)
        append!(res, O[name].vals)
    end
    res
end

"""RTP_CPX(R,V,P,T) of the period that holds year ye (PERIODYR); 0 for a year in no period."""
function get_rcpx(RCPX, r, v, p, period_of, ye)
    t = get(period_of, ye, nothing)
    t === nothing ? 0.0 : get(RCPX, (r, v, p, t), 0.0)
end

# the output tables, in this order (objective.py: OBJ_OUT)
const OBJ_OUT = ["SCAL", "FIXDL", "FIXTL", "FIXEL", "COEF_OBFIXR", "OBJ_CFIX", "SALV_INV", "OBJ_SUMS", "OBJSCC",
                 "OBJ_DCEOH", "OBJ_IAD", "OBJ_SUMS3", "COR_SALVD", "OBJ_CRFD", "SALV_DEC", "OBJ_LIFE", "OBJ_SALVS",
                 "OBJ_ICUR", "OBJ_FCUR", "COEF_OBINV", "COEF_OBFIX", "OBJ_CINV", "COR_SALVI", "OBJ_CRF", "OBJ_DIVI",
                 "OBJ_DIVIV", "RTP_ISHPR", "RTP_SHAPE", "OBJ_PASTI", "KAGE", "OBJ_JD", "OBJ_WD", "INVSPRED",
                 "OBJ_SUMII", "OBJ_SUMIV", "OBJ_YES", "OBJ_DIVIII", "OBJ_SUMIII", "OBJ_SUMIVS", "OBJ_CDEC", "DLC_V"]

"""The columns of a small made-up model for the precompile workload (codes: region 0, currency 1, processes 2 and 3),
with past and new vintages, a lead time, investment, fixed and decommissioning costs, surveillance, a shape and retirement,
so that the kernel's every part is compiled with the package."""
function objective_example(classic::Bool, vnret::Bool)
    i = Int32
    Y = 2000:2060
    T = i[2005, 2010, 2020, 2030]
    Bv = Dict(2000 => 2000, 2005 => 2003, 2010 => 2008, 2020 => 2016, 2030 => 2026)
    Ev = Dict(2000 => 2000, 2005 => 2007, 2010 => 2015, 2020 => 2025, 2030 => 2035)
    ys = i[2000, 2005, 2010, 2020, 2030]
    ipar(f) = Any[ys, Float64[f(y) for y in ys]]
    rtp = [(y, p) for p in i[2, 3] for y in ys]
    rv(f) = (k = [(y, p) for (y, p) in rtp if f(y, p) !== nothing];
             Any[i[0 for _ in k], i[y for (y, _) in k], i[p for (_, p) in k], Float64[f(y, p) for (y, p) in k]])
    ryc(f) = Any[i[0 for _ in Y], Int32.(collect(Y)), i[1 for _ in Y], Float64[f(y) for y in Y]]
    ob(f) = (k = [(p, y) for p in i[2, 3] for y in Y if f(p, y) !== nothing];
             Any[i[0 for _ in k], i[p for (p, _) in k], i[1 for _ in k], i[y for (_, y) in k], Float64[f(p, y) for (p, y) in k]])
    cpt = [(v, p, t) for (v, p) in rtp for t in T if t >= v]
    per = [(t, y) for t in T for y in Bv[t]:Ev[t]]
    cols = Any[[Float64(classic), 0.0, 0.5, 2005.0, 2005.0, 2030.0, 1.0, Float64(vnret), 60.0, 0.0, 0.0],
               Int32.(collect(Y)), Int32.(collect(Y)), Int32.(collect(2000:2030)), Int32.(collect(2005:2030)), T, i[2000], i[2000], i[2000]]
    append!(cols, ipar(y -> Bv[y])); append!(cols, ipar(y -> Ev[y])); append!(cols, ipar(y -> div(Bv[y] + Ev[y], 2)))
    append!(cols, ipar(y -> Ev[y] - Bv[y] + 1)); append!(cols, ipar(y -> Ev[y] - Bv[y] + 1))
    append!(cols, Any[i[0 for _ in rtp], i[y for (y, _) in rtp], i[p for (_, p) in rtp]])
    append!(cols, rv((y, p) -> p == 3 ? 7.5 : 20.0))                              # NCAP_TLIFE
    append!(cols, rv((y, p) -> 20.0))                                             # NCAP_ELIFE
    append!(cols, rv((y, p) -> p == 3 && y == 2030 ? 2.5 : 1.0))                  # COEF_RPTI
    append!(cols, rv((y, p) -> y == 2000 ? 100.0 : nothing))                      # NCAP_PASTI
    append!(cols, rv((y, p) -> p == 3 && y == 2010 ? 2.0 : nothing))              # NCAP_DLIFE
    append!(cols, rv((y, p) -> p == 3 && y == 2010 ? 3.0 : nothing))              # NCAP_DELIF
    append!(cols, rv((y, p) -> p == 3 && y == 2010 ? 1.0 : nothing))              # NCAP_DLAG
    append!(cols, rv((y, p) -> p == 2 ? 0.08 : nothing))                          # NCAP_DRATE
    append!(cols, rv((y, p) -> p == 2 && y == 2010 ? 0.01 : nothing))             # NCAP_FDR
    append!(cols, rv((y, p) -> p == 2 && y in (2020, 2030) ? 1.5 : nothing))      # NCAP_ILED
    append!(cols, rv((y, p) -> p == 2 && y == 2020 ? 0.5 : nothing))              # COEF_ILED
    append!(cols, Any[i[0], i[2030], i[3]])                                       # RTP_OFF
    append!(cols, ryc(y -> 0.95^(y - 2005))); append!(cols, ryc(y -> 0.05)); append!(cols, ryc(y -> 0.04))
    append!(cols, Any[i[0, 0, 0, 0], T, i[1, 1, 1, 1], [1.0, 0.8, 0.6, 0.4]])        # OBJ_PVT
    append!(cols, Any[i[0], i[1]])                                                # RDCUR
    append!(cols, ob((p, y) -> 1000.0)); append!(cols, ob((p, y) -> p == 2 && y == 2010 ? 10.0 : nothing))
    append!(cols, ob((p, y) -> p == 2 && y == 2010 ? 5.0 : nothing)); append!(cols, ob((p, y) -> 20.0))
    append!(cols, ob((p, y) -> p == 3 && y == 2020 ? 1.0 : nothing)); append!(cols, ob((p, y) -> p == 3 && y == 2020 ? 2.0 : nothing))
    append!(cols, ob((p, y) -> p == 3 && y == 2010 ? 50.0 : nothing)); append!(cols, ob((p, y) -> p == 2 && y == 2020 ? 3.0 : nothing))
    append!(cols, Any[i[0], i[2]])                                                # PRC_RESID(r,'0',p)
    append!(cols, Any[i[0, 0, 0], i[2005, 2010, 2020], i[2, 2, 2], [80.0, 60.0, 30.0]])
    append!(cols, Any[i[0 for _ in cpt], i[v for (v, _, _) in cpt], i[p for (_, p, _) in cpt], i[t for (_, _, t) in cpt],
                      Float64[1.0 for _ in cpt]])
    vn = [(v, t) for v in ys for t in T if t >= v]
    append!(cols, Any[i[v for (v, _) in vn], i[t for (_, t) in vn]])              # VNT
    append!(cols, Any[i[0], i[2010], i[3]])                                       # NCAP_CPX
    append!(cols, Any[i[0], i[2010], i[3], i[2020], [0.1]])                       # RTP_CPX
    append!(cols, rv((y, p) -> p == 2 && y == 2010 ? 2.0 : nothing))              # NCAP_FOMX
    append!(cols, rv((y, p) -> p == 3 && y == 2020 ? 2.0 : nothing))              # NCAP_FTAXX
    for _ in 1:4
        append!(cols, rv((y, p) -> nothing))
    end
    append!(cols, Any[i[j for j in 1:2 for a in 1:60], i[a for j in 1:2 for a in 1:60], Float64[j == 1 ? 1.0 : 1 - a / 100 for j in 1:2 for a in 1:60]])
    append!(cols, Any[i[j for j in 1:2 for y in Y], i[y for j in 1:2 for y in Y], Float64[j == 1 ? 1.0 : 1.02 for j in 1:2 for y in Y]])
    append!(cols, Any[i[t for (t, _) in per], i[y for (_, y) in per]])            # PERIODYR of the milestones
    append!(cols, Any[i[], i[], i[]])                                             # NCAP_OCOM
    append!(cols, Any[i[0], i[1]])                                                # G_RCUR
    append!(cols, Any[i[0], i[2], i[3], [-1.0]])                                  # PRC_REFIT
    if vnret
        vt = [(v, t) for (v, t) in vn if v != t]
        cy = [(v, t) for (v, t) in vn if v == 2000]
        append!(cols, Any[i[0], i[2010], i[2], i[v for (v, _) in vt], i[t for (_, t) in vt],
                          i[t for (t, _) in per], i[y for (_, y) in per],
                          i[0 for _ in cy], i[v for (v, _) in cy], i[t for (_, t) in cy], i[2 for _ in cy]])
    else
        append!(cols, Any[i[] for _ in 1:11])
    end
    cols
end
