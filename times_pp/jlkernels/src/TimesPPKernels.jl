# SPDX-License-Identifier: GPL-3.0-or-later
"""
Julia kernels of the TIMES preprocessor (times_pp), run inside the preprocessor's own Python process.

Each kernel replaces one step's Python / SQL computation, to the bit, behind a switch (TIMESPP_KERNELS); the step's
SQL stays the reference. How a kernel is added, switched on and checked: README.md beside this folder.
"""
module TimesPPKernels

import PrecompileTools

include("abi.jl")
include("fillparm.jl")
include("coef_ptr.jl")
include("fillcost.jl")
include("pyorder.jl")
include("objective.jl")
include("retirement.jl")

KERNELS["fillparm"] = fillparm
KERNELS["coef_ptr"] = coef_ptr
KERNELS["fillcost"] = fillcost
KERNELS["objective"] = objective
KERNELS["retirement"] = retirement
# echo: its columns back, copied (the hand-off alone, for benchmarks and tests of kernels.py)
KERNELS["echo"] = cols -> Any[copy(c) for c in cols]

function __init__()
    make_cfunctions()
end

# Compiled with the package: every kernel on a small input of the column types a run passes, through the same entry
# as a run (call_kernel), so that the first call in a run compiles (almost) nothing.
PrecompileTools.@compile_workload begin
    for x in (0.0, 1.0), kc in (0.0, 1.0)
        nk = 2
        keys = Any[Int32[0, 0, 0, 1, 1], Int32[2, 2, 2, 3, 3]]
        yint = Int32[0, 2010, 2030, 2010, 2020]
        flags = UInt8[0x03, 0x06, 0x06, 0x0e, 0x0e]
        value = [1005.0, 1.0, 2.0, 0.0, 0.05]
        tg = Int32[2005, 2010, 2015, 2020, 2025, 2030, 2040]
        for ctl in (Int32[-1], Int32[2, 1, 2, 0, 0])
            alts = ctl[1] < 0 ? Any[] : Any[Int32[0, 1], Int32[2, 3], Int32[2015, 2040], Int32[], Int32[], Int32[2025]]
            call_kernel("fillparm", Any[[Float64(nk), x, 0.0, kc], keys..., yint, flags, value, tg, ctl, alts...])
        end
        value[1] = 2.0                                  # option 2: EPS extrapolation
        call_kernel("fillparm", Any[[Float64(nk), x, 0.0, kc], keys..., yint, flags, value, tg, Int32[-1]])
    end
    call_kernel("echo", Any[Int32[1, 2], [1.0, 2.0], UInt8[1], Int64[3]])
    # coef_ptr on a small made-up process (codes: r 0, years 1 2, p 3, groups 4 7, commodities 5 6, timeslices 8 9 10,
    # timeslice level 11)
    let i = Int32
        ptr = Any[i[0, 0], i[1, 1], i[3, 3], i[4, 4], i[5, 6], i[7, 7], i[9, 10], [2.0, 0.5],      # FLO_SUM
                  i[0, 0], i[1, 1], i[3, 3], i[7, 4], i[4, 7], i[9, 8], [1.5, 0.0],                # FLO_FUNC
                  i[0, 0, 0], i[3, 3, 3], i[5, 6, 4],                                              # RPC
                  i[0, 0], i[1, 2], i[3, 3],                                                       # RTP
                  i[1, 2], i[4, 5, 6],                                                             # MODLYEAR, COM
                  i[0, 0, 0], i[4, 4, 7], i[5, 6, 5],                                              # COM_GMAP
                  i[0], i[3], i[11],                                                               # PRC_TSL
                  i[0, 0], i[11, 11], i[9, 10],                                                    # TS_GROUP
                  i[0, 0, 0, 0], i[9, 10, 8, 8], i[9, 10, 9, 10],                                  # TS_MAP
                  i[0, 0, 0], i[3, 3, 3], i[5, 6, 5], i[9, 10, 8],                                 # RPCS_VAR
                  i[0], i[3], i[4], i[5],                                                          # RPCC_FFUNC
                  i[0], i[3], i[4],                                                                # PRC_CG
                  i[0], i[5],                                                                      # RC
                  i[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]]                                         # rank
        call_kernel("coef_ptr", ptr)
    end
    # fillcost: two series, the second with an extrapolation range, mode2 and not, bext / fext and not
    for m2 in (0.0, 1.0), ext in (0.0, 1.0)
        call_kernel("fillcost", Any[[2.0, m2, ext, ext, 1.0, 2.0], Int32[0, 0, 0, 1], Int32[2, 2, 3, 3],
                                    Int32[2010, 2030, 2020, 2015], [1.0, 2.0, 3.0, 1e-300],
                                    Int32[2005, 2010, 2015, 2020, 2025, 2030, 2040],
                                    Int32[0, 1], Int32[2, 3], [2008.0, -Inf], [2035.0, Inf]])
    end
    # objective on a small made-up model, both forms of the objective, with retirement and without, both sums
    for classic in (false, true), vnret in (true, false), py312 in (0.0, 1.0)
        cols = objective_example(classic, vnret)
        cols[1][10] = py312
        call_kernel("objective", cols)
    end
    # retirement on a small made-up model
    call_kernel("retirement", retirement_example())
    # the C entry, with columns passed by pointer as kernels.py passes them
    let name = "fillparm", cols = Any[[2.0, 0.0, 0.0, 0.0], Int32[0, 0], Int32[1, 1], Int32[2010, 2020],
                                      UInt8[0x06, 0x06], [1.0, 2.0], Int32[2010, 2015, 2020], Int32[-1]]
        GC.@preserve name cols begin
            ptrs = Ptr{Cvoid}[pointer(c) for c in cols]
            types = Int32[typecode(eltype(c)) for c in cols]
            lens = Int64[length(c) for c in cols]
            h = Ref{Int64}(0)
            tpk_call(Base.unsafe_convert(Cstring, name), Int32(length(cols)), pointer(ptrs), pointer(types),
                     pointer(lens), Base.unsafe_convert(Ptr{Int64}, h))
            p = Ref{Ptr{Cvoid}}(C_NULL); t = Ref{Int32}(0); l = Ref{Int64}(0)
            for i in 1:tpk_ncols(h[])
                tpk_col(h[], Int32(i), Base.unsafe_convert(Ptr{Ptr{Cvoid}}, p), Base.unsafe_convert(Ptr{Int32}, t),
                        Base.unsafe_convert(Ptr{Int64}, l))
            end
            tpk_free(h[])
        end
    end
    empty!(TIMES)
    tpk_times(); tpk_error()
end

end
