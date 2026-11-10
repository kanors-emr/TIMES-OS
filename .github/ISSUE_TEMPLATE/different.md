---
name: A model that runs but does not agree with GAMS
about: The verdict was DIFFERENT, NOT SOLVED or ERROR. This is a defect of the port.
title: "DIFFERENT: <model name>"
labels: defect
---

**Model** (name, size, public or private):

**Command** (`python TIMES.py run <folder> ...` with the options used):

**First line of `report_<case>.txt`**:

**With GAMS and the TIMES source at hand: the first line after `--check`** (`SAME`, or `DIFFERENT` with the
equations and variables that differ):

**The section of the report that names the equations or the step** (or attach the bundle
written by `run --bundle`, which adds the logs and the input files):

```
paste here
```

**Versions** (from the end of the report: code revision, TIMES source, GAMS, Julia, Python):
