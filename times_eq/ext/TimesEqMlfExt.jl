# SPDX-License-Identifier: GPL-3.0-or-later
# The calibration of TIMES-MACRO MLF (mlf_calibration.jl), compiled with TimesEq when Ipopt is in its environment, and
# run by tools/mlf_calibrate.jl. Compiled ahead, the calibration of a small model takes a fraction of a second; compiled
# in the run, as a script, it took about 5 s more, whatever the model's size.
module TimesEqMlfExt

using TimesEq, JuMP, Ipopt
import PrecompileTools

include("mlf_calibration.jl")

# The input of the workload: one region and three periods, MACRO's default parameters (capital-GDP ratio 2.5,
# depreciation 5%, value share of capital 0.25, elasticity 0.25) and an economy of GDP 100 whose energy service has a
# value share of 5%. Its calibration solves the NLP six times, through both loops of calibase.mlf.
function workload_input(file)
    T = ("2020", "2030", "2040")
    gdp = Dict("2020" => 100.0, "2030" => 125.0, "2040" => 150.0)
    lab = Dict("2020" => 1.0, "2030" => 1.25, "2040" => 1.5)
    dem = Dict("2020" => 50.0, "2030" => 55.0, "2040" => 60.0)
    r = "R"
    rows = String[]
    rec(n, k...) = push!(rows, join((n, k...), '\t'))
    rec("@T", T...); rec("@NITER", "1", "2", "3"); rec("@REG", r)
    rec("MR", r, "1.0")
    for (k, v) in (("TM_SCALE_NRG", 0.001), ("TM_SCALE_UTIL", 0.001), ("TM_SCALE_CST", 0.001), ("TM_ARBM", 1.0))
        rec(k, repr(v))
    end
    rec("TM_DEFVAL", "USEHDF", "1.0")
    for (k, v) in (("TM_RHO", -3.0), ("TM_KPVS", 0.25), ("TM_DEPR", 5.0), ("TM_ESUB", 0.25), ("TM_KGDP", 2.5),
                   ("TM_IVETOL", 0.5), ("TM_GDP0", 100.0), ("TM_K0", 250.0), ("TM_IV0", 20.0), ("TM_C0", 80.0), ("TM_Y0", 100.0),
                   ("TM_AKL", 5.97e-5), ("TM_NWT", 1.0))
        rec(k, r, repr(v))
    end
    rec("TM_B", r, "ACT", "6.25e-12")
    for t in T
        rec("NYPER", t, "10.0"); rec("D", t, "10.0"); rec("TM_PWT", t, "1.0")
        rec("TM_GDPGOAL", r, t, repr(gdp[t])); rec("TM_L", r, t, repr(lab[t])); rec("TM_GR", r, t, "2.0"); rec("TM_GROWV", r, t, "2.0")
        rec("TM_DFACT", r, t, "1.0"); rec("TM_TSRV", r, t, "0.6"); rec("TM_HDF", r, t, "1.0"); rec("COEF_PVT", r, t, "1.0")
        rec("TM_QSFA", r, t, "-1.0"); rec("TM_QSFB", r, t, "ACT", "1e-4"); rec("TM_AMP", r, t, "5.0")
        rec("TM_DEM", r, t, "ACT", repr(dem[t])); rec("TM_DMC", r, t, "ACT", "0.1"); rec("TM_AEEIFAC", r, t, "ACT", "1.0")
        rec("L:VAR_C", r, t, repr(0.8 * gdp[t])); rec("L:VAR_INV", r, t, repr(0.2 * gdp[t])); rec("L:VAR_K", r, t, repr(2.5 * gdp[t]))
        rec("L:VAR_D", r, t, "ACT", repr(dem[t] / 1000)); rec("L:VAR_DEM", r, t, "ACT", repr(dem[t]))
        for (c, l) in (("KN", 2.5 * gdp[t]), ("LAB", lab[t]), ("AKL", 4.0))
            rec("L:VAR_D", r, t, c, repr(l)); rec("LO:VAR_D", r, t, c, "0.001")
        end
        rec("LO:VAR_C", r, t, "1.0"); rec("LO:VAR_K", r, t, "1.0"); rec("LO:VAR_D", r, t, "ACT", "1e-6")
    end
    rec("LO:VAR_K", r, T[1], "250.0"); rec("UP:VAR_K", r, T[1], "250.0")
    rec("LO:VAR_D", r, T[1], "ACT", repr(dem[T[1]] / 1000)); rec("UP:VAR_D", r, T[1], "ACT", repr(dem[T[1]] / 1000))
    write(file, join(rows, '\n') * '\n')
end

PrecompileTools.@compile_workload begin
    tmp = mktempdir()
    try
        workload_input(joinpath(tmp, "in.tsv"))
        main([joinpath(tmp, "in.tsv"), joinpath(tmp, "out.tsv")])
    catch e
        # a failing workload only means less is compiled ahead
        @warn "TimesEqMlfExt precompile workload failed; the calibration is compiled when it runs" exception = (e, catch_backtrace())
    end
    rm(tmp; recursive = true, force = true)
end

end # module
