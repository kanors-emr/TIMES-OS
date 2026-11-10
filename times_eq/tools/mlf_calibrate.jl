# SPDX-License-Identifier: GPL-3.0-or-later
# The calibration of TIMES-MACRO in its linearised form (MLF): calibase.mlf with ddfupd.msa, the NLP model MCE solved
# with Ipopt (JuMP), statement by statement as TIMES has them (ext/mlf_calibration.jl).
#
#   julia --project=<env with TimesEq, JuMP and Ipopt> tools/mlf_calibrate.jl <in.tsv> <out.tsv>
#
# The preprocessor (times_pp, prep/mlf.py) writes in.tsv: one record per line, the name, its labels and its value,
# separated by tabs (a set: value 1; a scalar: the name and the value); `@<SET>` lines give the order of the ordered
# sets (the milestone years T, NITER, REG); `L:<var>` / `LO:<var>` / `UP:<var>` the levels and bounds of the MACRO
# variables as equ_ext.mlf leaves them. out.tsv holds what calibase.mlf assigns (the parameters, sets and scalars),
# the levels (`L:<var>`) and marginals (`M:<equation or var>`) of the last NLP, and one `#` line per NLP solved.
#
# The code is compiled with TimesEq (its extension TimesEqMlfExt, made when Ipopt is in the environment). An environment
# without it (set up before it existed, or one with JuMP and Ipopt only) runs the same file, compiled in the run.
const EXT = try
    @eval using TimesEq, Ipopt
    Base.get_extension(TimesEq, :TimesEqMlfExt)
catch
    nothing
end
if EXT === nothing
    const M = Module(:MlfCalibration)
    Core.eval(M, :(using JuMP, Ipopt))
    Base.include(M, joinpath(dirname(@__DIR__), "ext", "mlf_calibration.jl"))
    Core.eval(M, :(main($ARGS)))
else
    Base.invokelatest(EXT.main, ARGS)
end
