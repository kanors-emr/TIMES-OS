# SPDX-License-Identifier: GPL-3.0-or-later
"""python -m timesrpt   runs tests/run_cases.py"""
import runpy, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "times_pp"))
raise SystemExit(runpy.run_path(os.path.join(os.path.dirname(__file__), "..", "tests", "run_cases.py"), run_name="__main__"))
