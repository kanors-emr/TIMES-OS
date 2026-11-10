# Notice

**`times_pp`**, the TIMES preprocessor of TIMES Open Stack (TIMES-OS), in Python on DuckDB.

Copyright (C) 2026 KanORS-EMR

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License (file `LICENSE`) for more details.

## Derived from TIMES

`times_pp` restates the preprocessor of the TIMES model generator, version 4.9.8, in Python. Each block quotes the
GAMS statements it replaces. Where this work and TIMES differ, TIMES is right.

> The Integrated MARKAL-EFOM System - TIMES
> Copyright (C) 2000-2025 IEA Energy Technology Systems Analysis Programme (ETSAP)
> GNU General Public License, version 3 or later
> https://github.com/etsap-TIMES/TIMES_model

`times_pp/timespp/times_src/` holds fifteen TIMES v4.9.8 files unchanged: the declaration files the Veda run file
includes (`initsys.mod`, `units.def`, `maplists.def`, `globals.def`, `initmty.mod`, `initmty.vda`), the declarations
of the extensions it covers (`initmty.abs`, ancillary balancing services; `initmty.tm` and `initmty.mlf`,
TIMES-MACRO MLF; `initmty.cli`, the climate module; `initmty.stc`, stochastic TIMES; each read when the run file
switches it on), and four the report writer reads (`times2veda.vdd`, `times2veda_stc.vdd` for stochastic runs,
`solsetv.v3`, `setglobs.gms`). © IEA-ETSAP, GPL-3.0-or-later. Their
declaration and data statements are read; no GAMS code in them is run. See `times_src/README.md`.

## Dependencies

Not included; each under its own licence: DuckDB and pandas.

The notice of the whole of TIMES-OS, with its acknowledgements: `NOTICE.md` in the repository root.
