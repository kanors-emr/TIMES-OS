# SPDX-License-Identifier: GPL-3.0-or-later
using Test, JuMP, HiGHS, TimesEq
include("demos012.jl")
include("gamslp.jl")

"""The model built from `file` has the rows, columns, non-zeros and optimum that GAMS reports."""
function same_as_gams(file, solution, gams_rows, gams_columns, gams_nonzeros, gams_objective)
    d = TimesEq.load(String(file))
    m = TimesEq.build(d)

    @testset "same matrix size as GAMS" begin
        rows = TimesEq.row_counts(m)
        @test Set(keys(rows)) == Set(keys(gams_rows))
        for (eq, n) in gams_rows
            @test (eq, get(rows, eq, 0)) == (eq, n)
        end
        @test num_variables(m.jump) == gams_columns
        @test TimesEq.nonzeros(m) == gams_nonzeros
    end

    @testset "the GAMS solution satisfies every row" begin
        if isfile(solution)
            for (eq, viol) in TimesEq.check_solution(m, TimesEq.load_levels(d, solution))
                @test (eq, viol < 1e-6) == (eq, true)
            end
            r = TimesEq.compare_gams(m, d, String(solution); io = devnull)
            @test r.same_rows
            @test r.same_solution
            @test r.same_duals
            @test r.same_rhs
            @test r.same_bounds
        else
            get(ENV, "TIMESEQ_REQUIRE", "") == "all" ? (@test isfile(solution)) : (@test_skip isfile(solution))
        end
    end

    @testset "same optimum as GAMS/CPLEX" begin
        set_optimizer(m.jump, HiGHS.Optimizer)
        set_silent(m.jump)
        optimize!(m.jump)
        @test termination_status(m.jump) == OPTIMAL
        @test objective_value(m.jump) ≈ gams_objective rtol = 1e-9
    end
end

# DemoS_012 as the repository ships it. TIMESEQ_DEMOS012 may name other tables instead (several, separated by ;): all must
# give the same model. The GAMS solution, where it is there, is checked too.
files = haskey(ENV, "TIMESEQ_DEMOS012") ? split(ENV["TIMESEQ_DEMOS012"], ';') : [demos012_tables()]
solution = get(ENV, "TIMESEQ_DEMOS012_SOLUTION", joinpath(DEMOS012, "gams_solution.db3"))

@testset "DemoS_012: $(basename(f))" for f in files
    same_as_gams(f, solution, GAMS_ROWS, GAMS_COLUMNS, GAMS_NONZEROS, GAMS_OBJECTIVE)
end

