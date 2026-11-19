# SPDX-License-Identifier: GPL-3.0-or-later
"""TIMES-OS, installed with pip: the launcher of the runner (TIMES.py).

    times-os setup | check | run <run folder> ... | verify <result folder> | example <folder> | clean | --version
    python -m times_os ...          (the same; works also where the times-os command is not on the PATH)

The package carries the runner and its code as they are in the repository, in the folder _tree beside this file. The
runner reads its code there and never writes there: what it makes for itself (its settings, the Julia environment,
the precompile workload, a Julia it installs) goes to the data folder, data_folder() below.  From a clone of the
repository installed with `pip install -e .` there is no _tree: the clone's own code runs, as it is edited, and its
state goes to the data folder, as for any installed package; `python TIMES.py` in the same clone keeps its state in
the clone."""
__version__ = "1.3.0"          # the release's version: written here by the export (scripts/publish_clone.ps1 -Version)
