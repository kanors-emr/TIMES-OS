# Notice

**`times_eq`**, the TIMES equations of TIMES Open Stack (TIMES-OS), in Julia/JuMP.

Copyright (C) 2026 KanORS-EMR

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License (file `LICENSE`) for more details.

## Derived from TIMES

`times_eq` restates the equations of the TIMES model generator, version 4.9.8, in Julia/JuMP. Each equation file
names the GAMS file it follows. Where this work and TIMES differ, TIMES is right.

> The Integrated MARKAL-EFOM System - TIMES
> Copyright (C) 2000-2025 IEA Energy Technology Systems Analysis Programme (ETSAP)
> GNU General Public License, version 3 or later
> https://github.com/etsap-TIMES/TIMES_model

## Dependencies

Not included; each under its own licence: JuMP, SQLite.jl and PrecompileTools; HiGHS for the tests and the example.
The calibration of TIMES-MACRO in its linearised form (MLF) uses Ipopt (EPL-2.0), through Ipopt.jl (MIT), and the
libraries of its binary build: MUMPS (CeCILL-C), METIS (Apache-2.0), SPRAL (BSD-3-Clause), the AMPL Solver Library (a
permissive licence of AMPL Optimization), OpenBLAS (BSD-3-Clause), hwloc (BSD-3-Clause) and the GCC runtime libraries
(GPL-3.0 with the GCC Runtime Library Exception).

The notice of the whole of TIMES-OS, with its acknowledgements: `NOTICE.md` in the repository root.
