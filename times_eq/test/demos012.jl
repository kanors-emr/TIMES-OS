# SPDX-License-Identifier: GPL-3.0-or-later
# DemoS_012 for the tests: the tables made from models/DemoS_012 by the preprocessor, in a temporary folder, and what
# GAMS generates for it, from models/DemoS_012/expected.json (a run of `setup` has made .venv).
import JSON

const REPOSITORY = normpath(joinpath(@__DIR__, "..", ".."))
const DEMOS012 = joinpath(REPOSITORY, "models", "DemoS_012")
const REPOSITORY_PYTHON = joinpath(REPOSITORY, ".venv", Sys.iswindows() ? "Scripts" : "bin", Sys.iswindows() ? "python.exe" : "python")
isfile(REPOSITORY_PYTHON) && !haskey(ENV, "TIMES_PYTHON") && (ENV["TIMES_PYTHON"] = REPOSITORY_PYTHON)
const EXPECTED = JSON.parsefile(joinpath(DEMOS012, "expected.json"))
const GAMS_ROWS = Dict(Symbol(k) => Int(v) for (k, v) in EXPECTED["row_counts"])
const GAMS_COLUMNS = Int(EXPECTED["gams"]["columns"])
const GAMS_NONZEROS = Int(EXPECTED["gams"]["nonzeros"])
const GAMS_OBJECTIVE = Float64(EXPECTED["objective"])

"""The tables of DemoS_012, made in a temporary folder. -> model.db3"""
function demos012_tables()
    work = mktempdir()
    case = joinpath(work, "case")
    cp(DEMOS012, case)
    run_file = only(filter(f -> endswith(lowercase(f), ".run"), readdir(case; join = true)))
    file = joinpath(work, "model.db3")
    run(setenv(`$REPOSITORY_PYTHON -m timespp $run_file - $file`; dir = joinpath(REPOSITORY, "times_pp")))
    return file
end
