# SPDX-License-Identifier: GPL-3.0-or-later
"""The preprocessor step by step, in the order TIMES runs these statements in GAMS.

The order matters to the bit: each step reads what the steps before it wrote. So it is written out here, once, and
everything that runs the preprocessor takes it from here. The steps themselves live in prep/<topic>.py.

A phase is a stretch of the GAMS source (ppmain.mod, coefmain.mod, ...); its title is the line the terminal shows with
its time. A step is one function; the terminal shows its title and time under its phase when the phase has more than
one step. `dump` labels the point in the GAMS source right after the step.
"""
from dataclasses import dataclass
from typing import Callable, Optional
from .prep import (extensions, stochastic, periods, interpolation, sets, timeslices, capacity, flows, defaults, commodities, trade,
                   bounds, storage, userconstraints, veda_attributes, coefficients, veda_coefficients, objective, myopic, mlf, cli)


@dataclass(frozen=True)
class Step:
    run: Callable                   # run(db)
    title: str                      # what the terminal shows
    dump: Optional[str] = None      # label of the point in the GAMS source after this step


# ppmain.mod after preppm.mod
PPMAIN = [
    Step(periods.horizon_years, "years of the horizon and of late costs", "07"),
    Step(sets.control_sets, "control sets of regions, processes, commodities; primary groups", "08"),
    Step(timeslices.commodity_timeslices, "timeslices of the commodities; peak timeslices", "09"),
    Step(timeslices.process_timeslices, "timeslices of the processes", "10"),
    Step(timeslices.flow_variable_timeslices, "timeslices of the flow variables", "11"),
    Step(capacity.lifetimes_and_capacity_transfer, "lifetimes, lead times, capacity transfer", "12"),
    Step(capacity.capacity_bounds_and_periods, "capacity bounds, availability periods, PRC_ACTFLO / PRC_CAPACT defaults", "13"),
    Step(flows.veda_flow_attributes, "VEDA flow attributes before levelling (pp_prelv.vda), FLO_SHAR checks (pp_qafs.mod)", "14"),
    Step(defaults.shapes_and_defaults, "SHAPE / MULTI curves, defaults of the attributes not by timeslice", "15"),
    Step(commodities.commodity_attributes, "commodity attributes by timeslice", "16"),
    Step(timeslices.timeslice_fractions, "timeslice fractions; elastic demands", "17"),
    Step(capacity.availability_by_timeslice, "availability factors and peak contribution by timeslice", "18"),
    Step(flows.flow_attributes_by_timeslice, "flow attributes by timeslice (and pp_chp.mod)", "19"),
    Step(trade.trade_attributes, "inter-regional exchange", "20"),
    Step(commodities.balance_types, "commodity balance types; conversion factors of trade", "21"),
    Step(bounds.bounds_by_timeslice, "bounds by timeslice; cumulative bounds", "22"),
    Step(commodities.balance_variables, "where the balances need VAR_COMNET / VAR_COMPRD", "23"),
    Step(storage.storage_controls, "storage", "24"),
    Step(userconstraints.user_constraints, "user constraints", "25"),
    Step(sets.balance_control_sets, "control sets of the commodity balances; blending", "26"),
    Step(sets.variable_control_sets, "control sets of the variables (pp_reduce.red)", "27"),
]

# (phase title, steps). Before them: the declarations and the DD files (load.py, controls.py, sysconst.py, domfilter.py).
PHASES = [
    ("init_ext.vda", [Step(extensions.init_ext, "VEDA extension attributes", "01")]),
    ("ppmain.mod (periods, timeslices, topology)", [
        Step(periods.topology_control_sets, "control sets of the topology; storage processes", "02"),
        Step(periods.periods_and_years, "periods and years", "03"),
        Step(timeslices.timeslices, "timeslices (timslice.mod)", "04"),
        Step(periods.past_vintages_and_start_years, "past investments, start years of new processes", "05")]),
    ("preppm.mod (inter-/extrapolation)", [
        Step(interpolation.year_sets_and_costs, "year sets, currencies, commodity costs, UC_COM, vintages", "41"),
        Step(interpolation.interpolate_costs, "cost parameters", "42"),
        Step(interpolation.interpolate_attributes, "standard parameters (fillparm)", "43"),
        Step(interpolation.interpolate_bounds, "bounds", "44"),
        Step(interpolation.extension_attributes, "extensions (prep_ext.vda)", "45"),
        Step(interpolation.shape_pointers, "SHAPE / MULTI pointers (preshape.gms)", "06")]),
    ("ppmain.mod (control sets, levelling, trade, UC)", PPMAIN),
    ("ppm_ext.vda", [Step(veda_attributes.ppm_ext, "VEDA attributes after levelling", "61")]),
    ("stages.stc (stochastic TIMES)", [Step(stochastic.stages, "the tree of states of the world, uncertain attributes")]),
    ("coefmain.mod", [Step(coefficients.coefmain, "coefficients", "62")]),
    ("coef_ext.vda", [Step(veda_coefficients.coef_ext, "VEDA coefficients", "63")]),
    ("mod_vars.cli (the climate module)", [Step(cli.mod_vars, "the bounds of the climate variables")]),
    ("retirement and refit controls", [Step(capacity.retirement_controls, "retirement and refit controls")]),
    ("objective coefficients", [Step(objective.objective_coefficients, "objective coefficients")]),
    ("equ_ext.mlf (TIMES-MACRO MLF)", [Step(mlf.equ_ext, "the calibration of MACRO, presolve.mlf, the bounds of MACRO")]),
    ("recurrin.stc SPINES (eqmain.mod 30)", [Step(stochastic.spines_sets, "the sets of SOW '1' of the spines")]),
    ("bounds, AFS, UC maps", [Step(bounds.variable_bounds, "bounds, AFS, UC maps", "64")]),
    ("pp_qack.mod (final control sets)", [Step(sets.final_control_sets, "final control sets", "99")]),
    ("solve.stp (the steps of a myopic run)", [Step(myopic.myopic_steps, "the steps of a myopic run")]),
]


def steps():
    """Every step, in order."""
    return [s for _, ph in PHASES for s in ph]
