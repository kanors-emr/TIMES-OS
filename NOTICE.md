# Notice

**An open chain for TIMES**: `times_pp` (Python preprocessor) and `times_eq` (Julia/JuMP equations).

Copyright (C) 2026 KanORS-EMR

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License (file `LICENSE`) for more details.

## Derived from TIMES

This work follows the source code of the TIMES model generator, version 4.9.8:

> The Integrated MARKAL-EFOM System - TIMES
> Copyright (C) 2000-2025 IEA Energy Technology Systems Analysis Programme (ETSAP)
> GNU General Public License, version 3 or later
> https://github.com/etsap-TIMES/TIMES_model

- `times_pp` restates the TIMES preprocessor in Python. Each block quotes the GAMS statements it
  replaces.
- `times_eq` restates TIMES equations in Julia/JuMP. Each equation file names the GAMS file it
  follows.
- `times_pp/timespp/times_src/` holds fifteen TIMES v4.9.8 files unchanged: the declaration files the Veda run file
  includes (`initsys.mod`, `units.def`, `maplists.def`, `globals.def`, `initmty.mod`, `initmty.vda`), the declarations
  of the extensions it covers (`initmty.abs`, ancillary balancing services; `initmty.tm` and `initmty.mlf`,
  TIMES-MACRO MLF; `initmty.cli`, the climate module; `initmty.stc`, stochastic TIMES; each read when the run file
  switches it on), and four the report writer reads (`times2veda.vdd`, `times2veda_stc.vdd` for stochastic runs,
  `solsetv.v3`, `setglobs.gms`). © IEA-ETSAP, GPL-3.0-or-later. Their
  declaration and data statements are read; no GAMS code in them is run. See `times_src/README.md`.

The authors and maintainers of TIMES are listed in `AUTHORS.md` of the TIMES repository. TIMES is
the reference; where this work and TIMES differ, TIMES is right.

## Acknowledgements

- **IEA-ETSAP** and the TIMES developers, for TIMES and for publishing its source.
- The DemoS_012 demonstration model is part of the VEDA-TIMES demo models.

## Input

The chain reads the DD and RUN files a TIMES run reads. They are written from the model workbooks by Veda
(https://veda-documentation.readthedocs.io) or by another parser of VedaTL, the Veda Tag Language, which is how TIMES
model workbooks are written.

## Status of this work

- This is an independent project of KanORS-EMR. It is not a product of IEA-ETSAP.
- It covers the features of the models it has been verified on; a model that needs anything else stops
  and lists what it needs. KanORS-EMR is responsible for the code on `main`.

## Dependencies

Not included; each under its own licence: DuckDB and pandas (Python); JuMP, SQLite.jl and
PrecompileTools (Julia); HiGHS for the tests and the example. The calibration of TIMES-MACRO in its
linearised form (MLF) uses Ipopt (EPL-2.0), through Ipopt.jl (MIT), and the libraries of its binary
build: MUMPS (CeCILL-C), METIS (Apache-2.0), SPRAL (BSD-3-Clause), the AMPL Solver Library (a
permissive licence of AMPL Optimization), OpenBLAS (BSD-3-Clause), hwloc (BSD-3-Clause) and the GCC
runtime libraries (GPL-3.0 with the GCC Runtime Library Exception). Optional, for the comparison with TIMES in
GAMS, `--lp` and `--jacobian` only, and installed only when GAMS is found or asked for (`requirements-gams.txt`):
gamsapi (GAMS Development Corporation) and gamspy_base, which comes under the GAMS licence agreement.
