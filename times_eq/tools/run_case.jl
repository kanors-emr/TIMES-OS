# SPDX-License-Identifier: GPL-3.0-or-later
# One preprocessed model from tables to an optimum, with everything that can be said about it written to a file.
#
#   julia --project=<env with TimesEq, JuMP, HiGHS> tools/run_case.jl model.db3 result.json
#         [--gams gams_solution.db3] [--matrix gams_matrix.db3] [--solver auto|simplex|ipm|hipo|ipx] [--time-limit seconds] [--no-solve] [--highs-log file]
#         [--solve] [--max-solve-rows n]   (above n rows, default 2,000,000, HiGHS is not tried unless --solve is given)
#         [--solution solution.db3] [--threads n] [--highs-option name=value ...]
#         [--profile cpu|allocs --profile-out julia_profile.txt]
#
# --threads: the threads HiGHS may use (0: its own choice). --highs-option: any HiGHS option, repeated as needed; it is
# applied after the choices made here (solver, crossover), so it can override them, e.g. --highs-option run_crossover=on.
#
# Used by TIMES.py (repository root), which runs the whole chain and writes the report. Nothing here stops
# at the first problem: each step (load, build, compare with GAMS, solve) records what happened, and the next
# one runs if it can. --matrix: the matrix GAMS wrote with CONVERT, as gams_matrix.db3. --gams: the GAMS solution (REDUCE NO), as gams_solution.db3.
#
#   julia ... tools/run_case.jl --wait
#
# --wait: the packages are loaded, then the run waits for two lines on its input: the settings (NAME=value, separated by
# tabs) and the arguments above (separated by tabs). TIMES.py starts Julia so while the preprocessor runs, and Julia's
# start-up (about 1.5 s) is no longer part of the run. Its input closed before the two lines: the process ends.
const T_SCRIPT = time()                      # before the packages are loaded: their loading is timed as well
using TimesEq
# Stochastic TIMES (TIMESEQ_STOCHASTIC=1: TIMES.py sets it for a run file with STAGES or SPINES): the add-on
# TimesEqStochastic holds the equation functions compiled for its variable families. Where it is not installed the
# run goes on, and compiles them itself.
if get(ENV, "TIMESEQ_STOCHASTIC", "") == "1"
    try
        @eval using TimesEqStochastic
    catch
        @warn "The add-on TimesEqStochastic is not in this Julia environment: the equations of stochastic TIMES are compiled in this run (python TIMES.py setup installs it)."
    end
end
if get(ARGS, 1, "") == "--wait"
    const EARLY = time() - T_SCRIPT
    const SETTINGS, ARGUMENTS = readline(stdin), readline(stdin; keep = true)
    endswith(ARGUMENTS, '\n') || exit(0)
    for kv in split(SETTINGS, '\t'; keepempty = false)
        k, v = split(kv, '='; limit = 2)
        ENV[k] = v
    end
    exit(TimesEq.RunCase.run_case(String.(split(chomp(ARGUMENTS), '\t')); t_script = time(), using_seconds = 0.0, early_seconds = EARLY))
end
exit(TimesEq.RunCase.run_case(ARGS; t_script = T_SCRIPT, using_seconds = time() - T_SCRIPT))
