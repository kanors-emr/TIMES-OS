# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQL_INSHR / EQE_INSHR / EQG_INSHR, EQL_OUTSHR / EQE_OUTSHR / EQG_OUTSHR (r,v,t,p,c,cg,s)     eqfloshr.mod

Share of commodity c in the flows of commodity group cg on the same side of the process.

    FLO_SHAR(r,v,p,c,cg,s,LO) * SUM(com in cg, flow(com) at s)  <=  flow(c) at s

`>=` for an upper and `=` for a fixed share.
"""
eq_floshr!(m::Model) = _eq_floshr!(m, exprtype(), m.d.FLO_SHAR)

"""
eq_floshr! in about `n` pieces (`PIECES`): contiguous blocks of FLO_SHAR. A block starts where no process (r, v, p) of
the entries before it comes again: the first group the block's loop looks up is then of another process than the
last one looked up before, so the loop's caches are emptied there in the whole loop as in the block, and the blocks'
rows, committed one after another, are the family's rows in its order.
"""
function floshr_pieces(m::Model, n::Int)
    sh = m.d.FLO_SHAR
    N = length(sh)
    lastpos = Dict{NTuple{3,Id},Int}()
    for (i, k) in enumerate(sh.keys)
        lastpos[(k[1], k[2], k[3])] = i
    end
    cuts = [1]
    reach = 0                                           # the last position of the processes before i
    for (i, k) in enumerate(sh.keys)
        length(cuts) < n && reach < i && i >= length(cuts) * N / n + 1 && push!(cuts, i)
        reach = max(reach, lastpos[(k[1], k[2], k[3])])
    end
    push!(cuts, N + 1)
    # the loop of _eq_floshr! empties its caches where the process changes: so it must change at every cut
    for j in 2:length(cuts)-1
        a, b = sh.keys[cuts[j]-1], sh.keys[cuts[j]]
        (a[1], a[2], a[3]) == (b[1], b[2], b[3]) && error("floshr_pieces: a cut inside the entries of one process")
    end
    return Function[rm -> _eq_floshr!(rm, exprtype(), ParPart(sh, cuts[j]:cuts[j+1]-1)) for j in 1:length(cuts)-1]
end

function _eq_floshr!(m::Model, ::Type{E}, entries) where {E}
    (; RP_STD, TOP, RPG_RED, RTP_VINTYR, RTPCS_VARF, COM_GMAP) = m.d
    (; top_c, flow_s, ts_frac) = m.ix
    (; VAR_FLO) = m.v
    (; IN, OUT) = m.K
    kinds = (by_bound(m, "INSHR"; share = true), by_bound(m, "OUTSHR"; share = true))
    groups = Dict{Tuple{Id,Id,Id,Id,Id,Id,Id,Bool},E === LX ? LX : Any}()
    walked = Set{Tuple{Id,Id,Id,Bool}}()     # (t, cg, io, reduced) of the process whose group sum walked every timeslice
    last_r = last_v = last_p = nothing

    # The caches (groups, walked) are emptied when an entry of another process (r, v, p) than the last one looks up a
    # group, and floshr_pieces cuts FLO_SHAR only where the process changes, so that a piece starts with them as empty
    # as the whole loop has them at that entry: a change to what they hold, or to when they are emptied, must recheck
    # that cut.
    for ((r, v, p, c, cg, s, bd), share) in entries, (side, io) in enumerate((IN, OUT)), t in m.T
        (m.stepped && !(t in m.sub)) && continue     # a myopic step: the window only (row! filters too)
        ((r, p) in RP_STD && (r, p, c, io) in TOP) || continue
        ((r, v, t, p) in RTP_VINTYR && (r, t, p, c, s) in RTPCS_VARF) || continue

        # emissions tied to other flows are replaced by those flows when the group has been reduced
        reduced = (r, p, cg, io) in RPG_RED
        f(com, ts) = reduced ? flow(E, m, r, v, t, p, com, ts) : VAR_FLO(r, v, t, p, com, ts)

        # the sum over the group is the same for every commodity of the group with a share: built once, then reused
        # (each row multiplies it by its own share into a new expression; the sum itself is never changed)
        group = if plain(share) > 0
            gk = (r, v, t, p, cg, s, io, reduced)
            if r != last_r || v != last_v || p != last_p          # FLO_SHAR comes process by process: keep only its groups
                empty!(groups); empty!(walked); last_r, last_v, last_p = r, v, p
            end
            get!(groups, gk) do
                # The first sum of a group of the process walks every timeslice of its flows: the variables are created
                # in that order, as before. A timeslice off the branch of s has a fraction of zero, and its term is
                # dropped by row!; the next sums (other timeslices s) take only those on the branch (onbranch, terms.jl).
                first = !((t, cg, io, reduced) in walked)
                first && push!(walked, (t, cg, io, reduced))
                tss(com) = first ? flow_s[r, t, p, com] : onbranch(flow_s[r, t, p, com], ts_frac[r, s])
                # (two sums, so that each term is of one type: a variable, or an emission's expression)
                reduced ? @esum(E, m.jump, sum(frac(m, r, t, com, s, ts) * flow(E, m, r, v, t, p, com, ts)
                              for com in top_c[r, p, io] if (r, cg, com) in COM_GMAP for ts in tss(com))) :
                          @esum(E, m.jump, sum(frac(m, r, t, com, s, ts) * VAR_FLO(r, v, t, p, com, ts)
                              for com in top_c[r, p, io] if (r, cg, com) in COM_GMAP for ts in tss(com)))
            end
        else
            0.0
        end

        name, sense = kinds[side](bd)
        # share * group: as a product applied while the row is copied (Scaled) when the group is an LX
        row!(m, name, (r, v, t, p, c, cg, s), group isa LX ? Scaled(Float64(share), group) : share * group, sense, f(c, s))
    end
end
