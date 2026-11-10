# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_DSCNCAP(r,t,p) / EQ_DSCONE(r,t,p)                                        equ_ext.dsc

Discrete and semi-continuous capacity additions (the DSC extension, a MIP): the new capacity of a process of
PRC_DSCNCAP is one of its unit sizes NCAP_DISC (VAR_DNCAP, an SOS1 set over the units; unit 0, of size EPS, is the
choice of none) and/or a semi-continuous amount VAR_SNCAP (0, or between NCAP_SEMI and its upper bound):

    VAR_NCAP(r,t,p)  =  SUM(unit with NCAP_DISC, NCAP_DISC(r,t,p,unit) * VAR_DNCAP(r,t,p,unit))  +  VAR_SNCAP(r,t,p) [NCAP_SEMI]
    SUM(unit with NCAP_DISC, VAR_DNCAP(r,t,p,unit))  =  1                       [NCAP_DISC(r,t,p,'0') given]

The rows and the bounds are those of GAMS (VAR_SNCAP keeps [NCAP_SEMI, UP] as its bounds, as the matrix check reads
them); the variable types are set only before a solve (`discrete_for_solve!`): VAR_SNCAP semi-continuous, VAR_DNCAP
binary where EQ_DSCONE makes its units sum to one (SOS1 with a unit sum), an SOS1 set otherwise.
"""
function eq_dsc!(m::Model)
    (; PRC_DSCNCAP, NCAP_DISC, NCAP_SEMI, RTP) = m.d
    (; VAR_NCAP, VAR_DNCAP, VAR_SNCAP) = m.v
    (isempty(PRC_DSCNCAP) || isempty(NCAP_DISC)) && return     # no unit sizes: the extension is off, PRC_DSCNCAP is data
    zero = id!(m.L, "0")
    units = Dict{Tuple{Id,Id,Id},Vector{Id}}()
    for ((r, t, p, u), _) in NCAP_DISC
        push!(get!(units, (r, t, p), Id[]), u)
    end
    sos = Vector{Tuple{Vector{JuMP.VariableRef},Vector{Float64},Bool}}()
    semi = JuMP.VariableRef[]
    for (r, t, p) in RTP
        (t in m.T && (r, p) in PRC_DSCNCAP) || continue
        (m.stepped && !(t in m.sub)) && continue
        us = sort(get(units, (r, t, p), Id[]); by = u -> something(tryparse(Float64, label(m.L, u)), Inf))
        e = AE()
        for u in us
            add!(e, NCAP_DISC(r, t, p, u), VAR_DNCAP(r, t, p, u))
        end
        if has(NCAP_SEMI, r, t, p)
            add!(e, 1.0, VAR_SNCAP(r, t, p))
            push!(semi, VAR_SNCAP(r, t, p))
        end
        row!(m, :EQ_DSCNCAP, (r, t, p), 1.0 * VAR_NCAP(r, t, p), ==, e)
        one_ = has(NCAP_DISC, r, t, p, zero)
        if one_
            s = AE()
            for u in us
                add!(s, 1.0, VAR_DNCAP(r, t, p, u))
            end
            row!(m, :EQ_DSCONE, (r, t, p), s, ==, 1.0)
        end
        isempty(us) || push!(sos, ([VAR_DNCAP(r, t, p, u) for u in us], collect(1.0:length(us)), one_))
    end
    m.jump.ext[:dsc] = (sos = sos, semi = semi)
end

"""The variable types of the DSC extension, set before a solve (see eq_dsc!)."""
function discrete_for_solve!(jm::JuMP.Model)
    d = get(jm.ext, :dsc, nothing)
    d === nothing && return
    for (xs, w, one_) in d.sos
        if one_
            foreach(JuMP.set_binary, xs)
        else
            JuMP.@constraint(jm, xs in MOI.SOS1(w))
        end
    end
    for x in d.semi
        if JuMP.is_fixed(x)                 # NCAP_SEMI equal to its upper bound: the variable is fixed at it
            lo = up = JuMP.fix_value(x)
            JuMP.unfix(x)
        else
            lo = JuMP.has_lower_bound(x) ? JuMP.lower_bound(x) : 0.0
            up = JuMP.has_upper_bound(x) ? JuMP.upper_bound(x) : Inf
            JuMP.has_lower_bound(x) && JuMP.delete_lower_bound(x)
            JuMP.has_upper_bound(x) && JuMP.delete_upper_bound(x)
        end
        JuMP.@constraint(jm, x in MOI.Semicontinuous(lo, up))
    end
    delete!(jm.ext, :dsc)
end
