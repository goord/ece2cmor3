import logging
import os
import re

from ece2cmor3 import cmor_task, grib_file, cdoapi, cmor_source, cmor_target

# Log object
log = logging.getLogger(__name__)

# Threading parameters
cdo_threads = 4

# Flags to control whether to execute cdo.
skip = 1
append = 2
recreate = 3
modes = [skip, append, recreate]

# Mode for post-processing
mode = 3


# Post-processes a task
def post_process(task, path, do_postprocess):
    command = create_command(task)
    output_path = get_output_path(task, path)
    if do_postprocess:
        if task.status != cmor_task.status_failed:
            filepath = apply_command(command, task, output_path)
        else:
            filepath = None
    else:
        filepath = 1
    if filepath is not None and task.status != cmor_task.status_failed:
        setattr(task, cmor_task.output_path_key, output_path)


def get_output_path(task, tmp_path):
    return os.path.join(tmp_path, task.target.variable + "_" + task.target.table + ".nc") if tmp_path else None


# Checks whether the task grouping makes sense: only tasks for the same variable and frequency can be safely grouped.
def validate_task_list(tasks):
    global log
    freqset = set(map(lambda t: cmor_target.get_freq(t.target), tasks))
    if len(freqset) != 1:
        log.error("Multiple target variables joined to single cdo command: %s" % str(freqset))
        return False
    return True


# Creates a cdo postprocessing command for the given IFS task.
def create_command(task):
    if not isinstance(task.source, cmor_source.ifs_source):
        raise Exception("This function can only be used to create cdo commands for IFS tasks")
    if hasattr(task, "paths") and len(getattr(task, "paths")) > 1:
        raise Exception("Multiple merged cdo commands are not supported yet")
    result = cdoapi.cdo_command() if hasattr(task.source, cmor_source.expression_key) else cdoapi.cdo_command(
        code=task.source.get_grib_code().var_id)
    add_grid_operators(result, task)
    add_expr_operators(result, task)
    add_time_operators(result, task)
    add_level_operators(result, task)
    return result


# Executes the command and replaces the path attribute for all tasks in the tasklist
# to the output of cdo. This path is constructed from the basepath and the first task.
def apply_command(command, task, output_path=None):
    global log, cdo_threads, skip, append, recreate, mode
    if output_path is None and mode in [skip, append]:
        log.warning(
            "Executing post-processing in skip/append mode without path given: this will skip the entire task.")
    input_files = getattr(task, cmor_task.filter_output_key, [])
    if not any(input_files):
        log.error("Cannot execute cdo command %s for given task because it has no model "
                  "output attribute" % command.create_command())
        return None
    if len(input_files) > 1:
        log.warning("Task %s in table %s appears to have multiple filtered output files, taking first file %s" %
                    (task.target.variable, task.target.table, input_files[0]))
    input_file = input_files[0]
    comm_string = command.create_command()
    log.info("Post-processing target %s in table %s from file %s with cdo command %s" % (
        task.target.variable, task.target.table, input_file, comm_string))
    setattr(task, "cdo_command", comm_string)
    task.next_state()
    result = None
    if mode != skip:
        if mode == recreate or (mode == append and not os.path.exists(output_path)):
            merge_expr = (cdoapi.cdo_command.set_code_operator in command.operators)
            result = command.apply(input_file, output_path, cdo_threads, grib_first=merge_expr)
            if not result:
                task.set_failed()
    else:
        if os.path.exists(output_path):
            result = output_path
    if result is not None:
        task.next_state()
    return result


def mask_rhs(rhs, mask):
    return rhs if mask is None else '(' + rhs + ")/(" + mask + ')'


# Checks whether the string expression denotes height level merging
def add_expr_operators(cdo, task):
    missval = getattr(task, "missval", None)
    if missval is not None:
        cdo.add_operator(cdoapi.cdo_command.set_misstoc_operator, missval)
    fillval = getattr(task, "fillval", None)
    if fillval is not None:
        cdo.add_operator(cdoapi.cdo_command.set_missval_operator, fillval)
    input_expr = getattr(task.source, cmor_source.expression_key, None)
    mask = getattr(task.source, cmor_source.mask_expression_key, None)
    if input_expr is None:
        if mask is None:
            return
        expr = '='.join([cmor_source.grib_code.to_cdo_str(task.source.get_grib_code())] * 2)
    else:
        expr = input_expr
    groups = re.search("^var([0-9]{1,3})\=", expr.replace(" ", ""))
    if groups is None:
        lhs = cmor_source.grib_code.to_cdo_str(task.source.get_grib_code())
        rhs = expr.replace(" ", "")
    else:
        lhs = groups.group(0)[:-1]
        rhs = expr.replace(" ", "")[len(lhs) + 1:]
    new_code = int(lhs[3:])
    order = getattr(task.source, cmor_source.expression_order_key, 0)
    expr_operator = cdoapi.cdo_command.post_expr_operator if order == 1 else cdoapi.cdo_command.expression_operator
    if rhs.startswith("merge(") and rhs.endswith(")"):
        arg = rhs[6:-1]
        sub_expr_list = arg.split(',')
        if not any(getattr(task.target, "z_dims", [])):
            log.warning("Encountered 3d expression for variable with no z-axis: taking first field")
            sub_expr = mask_rhs(sub_expr_list[0].strip(), mask)
            if not re.match("var[0-9]{1,3}", sub_expr):
                cdo.add_operator(expr_operator, "var" + str(new_code) + "=" + sub_expr)
            else:
                task.source = cmor_source.ifs_source.read(sub_expr, mask_expr=mask)
            root_codes = [int(s.strip()[3:]) for s in re.findall("var[0-9]{1,3}", sub_expr)]
            cdo.add_operator(cdoapi.cdo_command.select_code_operator, *root_codes)
            return
        else:
            i = 0
            for sub_expr in sub_expr_list:
                i += 1
                cdo.add_operator(expr_operator, "var" + str(i) + "=" + mask_rhs(sub_expr, mask))
            cdo.add_operator(cdoapi.cdo_command.set_code_operator, new_code)
    else:
        mask_interp_expr = '='.join([lhs, mask_rhs(rhs, mask)])
        cdo.add_operator(expr_operator, mask_interp_expr)
    cdo.add_operator(cdoapi.cdo_command.select_code_operator, *[c.var_id for c in task.source.get_root_codes()])


operator_mapping = {"mean": cdoapi.cdo_command.mean, "maximum": cdoapi.cdo_command.max,
                    "minimum": cdoapi.cdo_command.min, "sum": cdoapi.cdo_command.sum}


# Adds grid remapping operators to the cdo commands for the given task
def add_grid_operators(cdo, task):
    if task.target.variable.startswith("areacell"):
        cdo.add_operator(cdoapi.cdo_command.area_operator)
    grid = task.source.grid_id()
    if grid == cmor_source.ifs_grid.spec:
        cdo.add_operator(cdoapi.cdo_command.spectral_operator)
    else:
        cdo.add_operator(cdoapi.cdo_command.gridtype_operator, cdoapi.cdo_command.regular_grid_type)
    tgtdims = getattr(task.target, cmor_target.dims_key, "").split()
    if "longitude" not in tgtdims:
        operators = [str(o) for o in getattr(task.target, "longitude_operator", [])]
        if len(operators) == 1 and operators[0] in operator_mapping.keys():
            cdo.add_operator(cdoapi.cdo_command.zonal + operator_mapping[operators[0]])
        else:
            log.error("Longitude reduction operator for task %s in table %s is not supported" % (task.target.variable,
                                                                                                 task.target.table))
            task.set_failed()
    if "latitude" not in tgtdims:
        operators = [str(o) for o in getattr(task.target, "latitude_operator", [])]
        if len(operators) == 1 and operators[0] in operator_mapping.keys():
            cdo.add_operator(cdoapi.cdo_command.meridional + operator_mapping[operators[0]])
        else:
            log.error("Latitude reduction operator for task %s in table %s is not supported" % (task.target.variable,
                                                                                                 task.target.table))
            task.set_failed()


# Adds time averaging operators to the cdo command for the given task
def add_time_operators(cdo, task):
    freq = str(getattr(task.target, cmor_target.freq_key, None))
    operators = [str(o) for o in getattr(task.target, "time_operator", ["point"])]
    for i in range(len(operators)):
        operator_words = operators[i].split(" ")
        if len(operator_words) > 2 and operator_words[1] == "where":
            operators[i] = operator_words[0]
    if freq == "yr":
        if operators == ["mean"]:
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.mean)
        elif operators == ["maximum"]:
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.max)
        elif operators == ["minimum"]:
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.min)
        elif operators == ["sum"]:
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.sum)
        elif operators == ["maximum within months", "mean over months"]:
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.max)
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.mean)
        elif operators == ["minimum within months", "mean over months"]:
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.min)
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.mean)
        elif operators == ["maximum within days", "mean over days"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.max)
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.mean)
        elif operators == ["minimum within days", "mean over days"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.min)
            cdo.add_operator(cdoapi.cdo_command.year + cdoapi.cdo_command.mean)
        else:
            log.error(
                "Unsupported combination of frequency %s with time operators %s encountered for variable %s in table %s"
                % (freq, str(operators), task.target.variable, task.target.table))
            task.set_failed()
    elif freq == "yrPt":
        # End-of-year values:
        if operators == ["point"]:
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.month, 12)
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.day, 31)
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.hour, 21)
        else:
            log.error(
                "Unsupported combination of frequency %s with time operators %s encountered for variable %s in table %s"
                % (freq, str(operators), task.target.variable, task.target.table))
            task.set_failed()
    elif freq == "mon":
        if operators == ["point"]:
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.day, 15)
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.hour, 12)
        elif operators == ["mean"]:
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.mean)
        elif operators == ["maximum"]:
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.max)
        elif operators == ["minimum"]:
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.min)
        elif operators == ["sum"]:
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.sum)
        elif operators == ["maximum within days", "mean over days"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.max)
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.mean)
        elif operators == ["minimum within days", "mean over days"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.min)
            cdo.add_operator(cdoapi.cdo_command.month + cdoapi.cdo_command.mean)
        else:
            log.error(
                "Unsupported combination of frequency %s with time operators %s encountered for variable %s in table %s"
                % (freq, str(operators), task.target.variable, task.target.table))
            task.set_failed()
    elif freq == "monPt":
        if operators == ["point"]:
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.day, 15)
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.hour, 12)
        else:
            log.error(
                "Unsupported combination of frequency %s with time operators %s encountered for variable %s in table %s"
                % (freq, str(operators), task.target.variable, task.target.table))
            task.set_failed()
    elif freq == "day":
        if operators == ["point"]:
            cdo.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.hour, 12)
        elif operators == ["mean"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.mean)
        elif operators == ["maximum"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.max)
        elif operators == ["minimum"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.min)
        elif operators == ["sum"]:
            cdo.add_operator(cdoapi.cdo_command.day + cdoapi.cdo_command.sum)
        else:
            log.error(
                "Unsupported combination of frequency %s with time operators %s encountered for variable %s in table %s"
                % (freq, str(operators), task.target.variable, task.target.table))
            task.set_failed()
    elif freq in ["6hr", "6hrPt"] and len(operators) == 1:
        add_high_freq_operator(cdo, 6, operators[0], task)
    elif freq in ["3hr", "3hrPt"] and len(operators) == 1:
        add_high_freq_operator(cdo, 3, operators[0], task)
    elif freq == "fx" and operators == ["point"] or operators == ["mean"]:
        cdo.add_operator(cdoapi.cdo_command.select_step_operator, 1)
    else:
        log.error(
            "Unsupported combination of frequency %s with time operators %s encountered for variable %s in table %s"
            % (freq, str(operators), task.target.variable, task.target.table))
        task.set_failed()


def add_high_freq_operator(cdo_command, target_freq, operator, task):
    timestamps = [i * target_freq for i in range(24 / target_freq)]
    aggregators = {"mean": (cmor_source.ifs_source.grib_codes_accum, cdoapi.cdo_command.timselmean_operator),
                   "minimum": (cmor_source.ifs_source.grib_codes_min, cdoapi.cdo_command.timselmin_operator),
                   "maximum": (cmor_source.ifs_source.grib_codes_max, cdoapi.cdo_command.timselmax_operator)}
    if operator == "point":
        if any([c for c in task.source.get_root_codes() if c in cmor_source.ifs_source.grib_codes_accum]):
            log.warning("Sampling values of accumulated model output for variable %s in "
                        "table %s" % (task.target.variable, task.target.table))
        if any([c for c in task.source.get_root_codes() if c in cmor_source.ifs_source.grib_codes_min]):
            log.warning("Sampling values of minimum model output for variable %s in "
                        "table %s" % (task.target.variable, task.target.table))
        if any([c for c in task.source.get_root_codes() if c in cmor_source.ifs_source.grib_codes_max]):
            log.warning("Sampling values of maximum model output for variable %s in "
                        "table %s" % (task.target.variable, task.target.table))
        cdo_command.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.hour, *timestamps)
    elif operator in aggregators:
        if not all([c for c in task.source.get_root_codes() if c in aggregators[operator][0]]):
            source_freq = getattr(task, cmor_task.output_frequency_key)
            steps = target_freq / source_freq
            if steps == 0:
                log.error("Requested %s at %d-hourly frequency cannot be computed for variable %s in table %s "
                          "because its output frequency is only %d" % (operator, target_freq, task.target.variable,
                                                                       task.target.table, source_freq))
                task.set_failed()
            else:
                log.warning("Computing inaccurate mean value over %d time steps for variable "
                            "%s in table %s" % (target_freq / source_freq, task.target.variable, task.target.table))
                if steps == 1:
                    cdo_command.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.hour, *timestamps)
                else:
                    cdo_command.add_operator(aggregators[operator][1], steps)
        else:
            cdo_command.add_operator(cdoapi.cdo_command.select + cdoapi.cdo_command.hour, *timestamps)
    else:
        log.error("The operator %s is not supported by this post-processing software" % operator)
        task.set_failed()
    return cdo_command


# Translates the cmor vertical level post-processing operation to a cdo command-line option
def add_level_operators(cdo, task):
    global log
    if task.source.spatial_dims == 2:
        return
    zdims = getattr(task.target, "z_dims", [])
    if len(zdims) == 0:
        return
    if len(zdims) > 1:
        log.error("Multiple level dimensions in table %s are not supported by this post-processing software",
                  task.target.table)
        task.set_failed()
        return
    axisname = zdims[0]
    if axisname == "alevel":
        cdo.add_operator(cdoapi.cdo_command.select_z_operator, cdoapi.cdo_command.model_level)
    if axisname == "alevhalf":
        log.error("Vertical half-levels in table %s are not supported by this post-processing software",
                  task.target.table)
        task.set_failed()
        return
    axis_infos = cmor_target.get_axis_info(task.target.table)
    axisinfo = axis_infos.get(axisname, None)
    if not axisinfo:
        log.error("Could not retrieve information for axis %s in table %s" % (axisname, task.target.table))
        task.set_failed()
        return
    levels = axisinfo.get("requested", [])
    if len(levels) == 0:
        val = axisinfo.get("value", None)
        if val:
            levels = [val]
    level_types = [grib_file.hybrid_level_code, grib_file.pressure_level_hPa_code, grib_file.height_level_code]
    input_files = getattr(task, cmor_task.filter_output_key, [])
    if any(input_files):
        level_types = cdo.get_z_axes(input_files[0], task.source.get_root_codes()[0].var_id)
    name = axisinfo.get("standard_name", None)
    if name == "air_pressure":
        add_zaxis_operators(cdo, task, level_types, levels, cdoapi.cdo_command.pressure,
                            grib_file.pressure_level_hPa_code)
    elif name in ["height", "altitude"]:
        add_zaxis_operators(cdo, task, level_types, levels, cdoapi.cdo_command.height, grib_file.height_level_code)
    elif axisname not in ["alevel", "alevhalf"]:
        log.error("Could not convert vertical axis type %s to CDO axis selection operator" % name)
        task.set_failed()


# Helper function for setting the vertical axis and levels selection
def add_zaxis_operators(cdo, task, lev_types, req_levs, axis_type, axis_code):
    if axis_code not in lev_types and grib_file.hybrid_level_code in lev_types:
        log.warning(
            "Could not find %s levels for %s, will interpolate from model levels" % (axis_type, task.target.variable))
        cdo.add_operator(cdoapi.cdo_command.select_code_operator, *[134])
        cdo.add_operator(cdoapi.cdo_command.select_z_operator,
                         *[cdoapi.cdo_command.model_level, cdoapi.cdo_command.surf_level])
        if isinstance(req_levs, list) and any(req_levs):
            cdo.add_operator(cdoapi.cdo_command.ml2pl_operator, *req_levs)
    elif axis_code in lev_types:
        if isinstance(req_levs, list) and any(req_levs):
            levels = [float(s) for s in req_levs]
            input_files = getattr(task, cmor_task.filter_output_key, [])
            if any(input_files):
                levels = cdo.get_levels(input_files[0], task.source.get_root_codes()[0].var_id, axis_type)
            if set([float(s) for s in req_levs]) <= set(levels):
                cdo.add_operator(cdoapi.cdo_command.select_z_operator, axis_type)
                cdo.add_operator(cdoapi.cdo_command.select_lev_operator, *req_levs)
            else:
                log.error("Could not retrieve %s levels %s from levels %s in file for variable %s"
                          % (axis_type, req_levs, levels, task.target.variable))
                task.set_failed()
    else:
        log.error(
            "Could not retrieve %s levels for %s with axes %s" % (axis_type, task.target.variable, str(lev_types)))
        task.set_failed()
