# SPDX-License-Identifier: GPL-3.0-or-later
# The hand-over of the built model to HiGHS in one call.
#
# JuMP keeps the model in its own cache and copies it into the solver at optimize!. With the bridge layer that
# set_optimizer puts between JuMP and HiGHS by default, that copy is MOI's incremental one: every row is handed to
# HiGHS on its own (Highs_addRow), which on a model of 15 M rows is slow and allocates a great deal. HiGHS has a copy
# that passes the whole matrix at once (Highs_passModel), used when there is no bridge layer; but it orders the rows by
# their sense (>=, <=, =), where the incremental copy keeps the order of JuMP's cache. `attach_highs!` passes the
# matrix at once in the order of the incremental copy, so that HiGHS receives the same LP, row for row and column for
# column, as before.

import HiGHS

const HIGHS_ROW_SETS = (MOI.GreaterThan{Float64}, MOI.LessThan{Float64}, MOI.EqualTo{Float64}, MOI.Interval{Float64})

"""
    attach_highs!(jm::JuMP.Model) -> Symbol

Copy the model of `jm` into its optimizer, a `HiGHS.Optimizer` set with `add_bridges = false` (see `use_highs!`),
before `optimize!`. `:passmodel`: in one call (Highs_passModel), rows and columns in the order of MOI's incremental
copy. `:incremental`: the model holds something that copy does not pass (integer variables, other constraint types,
names, starts), and MOI's incremental copy did it, as JuMP would have. `:none`: nothing done (not that optimizer,
or already attached); `optimize!` copies the model as usual.
"""
function attach_highs!(jm::JuMP.Model)
    discrete_for_solve!(jm)                 # the variable types of the DSC extension (equations/dsc.jl)
    co = JuMP.backend(jm)
    co isa MOI.Utilities.CachingOptimizer || return :none
    co.state == MOI.Utilities.EMPTY_OPTIMIZER || return :none
    dest = co.optimizer
    dest isa HiGHS.Optimizer || return :none
    src = co.model_cache
    types = MOI.get(src, MOI.ListOfConstraintTypesPresent())
    plain = all(types) do (F, S)
        (F == MOI.VariableIndex || F == MOI.ScalarAffineFunction{Float64}) && S in HIGHS_ROW_SETS &&
            isempty(MOI.get(src, MOI.ListOfConstraintAttributesSet{F,S}()))
    end
    plain &= isempty(MOI.get(src, MOI.ListOfVariableAttributesSet()))
    # (a callback set on the model is passed on after the copy: runcase.jl sets one without events, so that HiGHS.jl
    # does not install its interrupt callback)
    plain &= all(a -> a isa Union{MOI.Name,MOI.ObjectiveSense,MOI.ObjectiveFunction{MOI.VariableIndex},
                                  MOI.ObjectiveFunction{MOI.ScalarAffineFunction{Float64}},HiGHS.CallbackFunction},
                 MOI.get(src, MOI.ListOfModelAttributesSet()))
    MOI.Utilities.final_touch(co, nothing)
    # (the incremental copy hands the objective over as it is: HiGHS without bridges takes no single-variable objective
    #  (OBJZ), so a model with integer, SOS or semi-continuous variables passes it as the same affine function)
    if !plain && MOI.get(src, MOI.ObjectiveFunctionType()) == MOI.VariableIndex
        f = MOI.get(src, MOI.ObjectiveFunction{MOI.VariableIndex}())
        MOI.set(src, MOI.ObjectiveFunction{MOI.ScalarAffineFunction{Float64}}(), convert(MOI.ScalarAffineFunction{Float64}, f))
    end
    map = plain ? copy_ordered!(dest, src, [S for (F, S) in types if F == MOI.ScalarAffineFunction{Float64}]) :
                  MOI.Utilities.default_copy_to(dest, src)
    if plain
        for a in MOI.get(src, MOI.ListOfModelAttributesSet())
            a isa HiGHS.CallbackFunction && MOI.set(dest, a, MOI.get(src, a))
        end
    end
    co.state = MOI.Utilities.ATTACHED_OPTIMIZER
    co.model_to_optimizer_map = map
    co.optimizer_to_model_map = MOI.Utilities._reverse_index_map(map)
    return plain ? :passmodel : :incremental
end

"""`use_highs!(jm)`: HiGHS as the optimizer of `jm`, without JuMP's bridge layer (the LP needs no bridge; without
it `attach_highs!` can pass the model in one call)."""
use_highs!(jm::JuMP.Model) = JuMP.set_optimizer(jm, HiGHS.Optimizer; add_bridges = false)

# HiGHS.jl's MOI.copy_to (src/MOI_wrapper.jl), with the rows in the order of `row_sets` (the constraint types of the
# source, in the order MOI's incremental copy takes them) instead of >=, <=, =, interval.
function copy_ordered!(dest::HiGHS.Optimizer, src::MOI.ModelLike, row_sets)
    MOI.empty!(dest)                              # (what HiGHS._check_input_data checks, attach_highs! did)
    mapping = MOI.Utilities.IndexMap()
    numcol = HiGHS._copy_to_columns(dest, src, mapping)
    collower, colupper = fill(-Inf, numcol), fill(Inf, numcol)
    rowlower, rowupper = Float64[], Float64[]
    I, J, V = HiGHS.HighsInt[], HiGHS.HighsInt[], Float64[]
    for S in HIGHS_ROW_SETS
        HiGHS._extract_bound_data(dest, src, mapping, collower, colupper, S)
    end
    for S in row_sets
        HiGHS._extract_row_data(dest, src, mapping, rowlower, rowupper, I, J, V, S)
    end
    numrow = HiGHS.HighsInt(length(rowlower))
    A = HiGHS.SparseArrays.sparse(I, J, V, numrow, numcol)
    I = J = V = nothing
    is_max = MOI.get(src, MOI.ObjectiveSense()) == MOI.MAX_SENSE
    dest.is_feasibility = false
    dest.is_objective_sense_set = true
    ret = HiGHS.Highs_passModel(dest, numcol, numrow, length(A.nzval), 0, HiGHS.kHighsMatrixFormatColwise, 0,
        is_max ? HiGHS.kHighsObjSenseMaximize : HiGHS.kHighsObjSenseMinimize, 0.0, fill(0.0, numcol),
        collower, colupper, rowlower, rowupper, A.colptr .- HiGHS.HighsInt(1), A.rowval .- HiGHS.HighsInt(1), A.nzval,
        C_NULL, C_NULL, C_NULL, C_NULL)
    HiGHS._check_ret(ret)
    # the objective as an affine function (a single variable, OBJZ, is one: what JuMP's bridge layer made of it)
    F = MOI.get(src, MOI.ObjectiveFunctionType())
    f = MOI.Utilities.map_indices(mapping, MOI.get(src, MOI.ObjectiveFunction{F}()))
    MOI.set(dest, MOI.ObjectiveFunction{MOI.ScalarAffineFunction{Float64}}(), convert(MOI.ScalarAffineFunction{Float64}, f))
    return mapping
end
