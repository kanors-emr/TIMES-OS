# SPDX-License-Identifier: GPL-3.0-or-later
# DemoS_012 without GAMS:   DD files -> timespp (Python) -> tables -> TimesEq -> HiGHS
#   python -m timespp <case.run> <TIMES source> DEMOS012_pp.db3
#   julia --project=examples -e 'using Pkg; Pkg.develop(path="."); Pkg.instantiate()'     (once)
#   julia --project=examples examples/demos012.jl DEMOS012_pp.db3
using JuMP, HiGHS, TimesEq
include(joinpath(@__DIR__, "..", "test", "demos012.jl"))

file = length(ARGS) >= 1 ? ARGS[1] : joinpath(@__DIR__, "..", "data", "DEMOS012_pp.db3")
@time "Load tables" d = TimesEq.load(file)
@time "Build model" m = TimesEq.build(d)
@time "Build model again (compiled)" m = TimesEq.build(d)

rows = TimesEq.row_counts(m)
println("\nEquation        Julia    GAMS")
for k in sort(collect(union(keys(rows), keys(GAMS_ROWS))), by = k -> -get(GAMS_ROWS, k, 0))
    a, b = get(rows, k, 0), get(GAMS_ROWS, k, 0)
    println(rpad(k, 14), lpad(a, 7), lpad(b, 8), a == b ? "" : "   <-- rows differ")
end
println("\nrows      ", sum(values(rows)), "   (GAMS ", sum(values(GAMS_ROWS)), ")")
println("columns   ", num_variables(m.jump), "   (GAMS ", GAMS_COLUMNS, ")")
println("nonzeros  ", TimesEq.nonzeros(m), "   (GAMS ", GAMS_NONZEROS, ")")

set_optimizer(m.jump, HiGHS.Optimizer)
set_silent(m.jump)
@time "Solve (HiGHS)" optimize!(m.jump)
println("status    ", termination_status(m.jump))
println("objective ", objective_value(m.jump), "   (GAMS/CPLEX ", GAMS_OBJECTIVE, ")")
