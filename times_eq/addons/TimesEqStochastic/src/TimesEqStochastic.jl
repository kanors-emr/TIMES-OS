# SPDX-License-Identifier: GPL-3.0-or-later
# The equation functions of TimesEq compiled ahead for stochastic TIMES (STAGES, SPINES: the variable families VarsST).
# This package holds no model code: the equations are those of TimesEq. It holds only this part of the compile
# workload, so that TimesEq itself compiles in less time and memory, and a change in the equations is compiled again
# for the stochastic families only by those who run them: `TIMES.py setup` compiles it with the rest, and where it is
# missing or out of date the first run of a model with STAGES or SPINES does. A run loads it (tools/run_case.jl) when
# the run file has one of the two switches; without it the same code is compiled in every such run. A SENSIS run
# builds deterministic models and does not need it.
module TimesEqStochastic

using TimesEq
import JuMP, PrecompileTools

PrecompileTools.@compile_workload begin
    # the equation functions for the variable families of stochastic TIMES (STAGES: VarsST): an empty model with one
    # state of the world (SOW '1' in SW_TSW), so that a stochastic run does not wait for the compiler either
    let L = TimesEq.Labels(), w = TimesEq.id!(L, "1"), t = TimesEq.id!(L, "2020")
        Id, Table, Data = TimesEq.Id, TimesEq.Table, TimesEq.Data
        sw = Dict{Symbol,Any}(:SW_TSW => Table{NTuple{3,Id}}([(w, t, w)], Set([(w, t, w)])), :SOW => Table{Id}([w], Set([w])),
                              :SW_T => Table{NTuple{2,Id}}([(t, w)], Set([(t, w)])))
        TimesEq.build(Data("", L, sw, Dict{Symbol,Any}(), Dict{Symbol,Any}(), Dict{Symbol,Int}()); names = true)
        # the same in threads (build_parallel!): its tasks and commits for these variable families
        m = TimesEq.build(Data("", L, sw, Dict{Symbol,Any}(), Dict{Symbol,Any}(), Dict{Symbol,Int}()); names = true, parallel = true)
        # what a run counts on the built model
        TimesEq.nonzeros(m); TimesEq.column_counts(m)
    end
end

end # module
