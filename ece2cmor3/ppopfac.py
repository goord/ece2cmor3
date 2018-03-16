import logging
from dateutil.relativedelta import relativedelta
from ece2cmor3 import ppsh, pptime, pplevels, pp2cmor, ppexpr, cmor_target, grib_file, cmor_source

# Log object
log = logging.getLogger(__name__)

table_root = None


# Creates the DAG of post-processing operators for a specific task
# TODO: add expression operators
# TODO: right block time interpolation for fluxes?
# TODO: share common grid remapping operators

def create_pp_operators(task):
    pp2cmor.table_root = table_root
    expr = None
    if task.source.get_root_codes() != [task.source.get_grib_code()]:
        expr = getattr(task.source, cmor_source.expression_key, None)
    #        log.warning("Dismissing task with expression operator: %s in %s" % (task.target.variable, task.target.table))
    #        return None

    axisname, leveltype, levs = cmor_target.get_z_axis(task.target)
    store_var = "ps" if leveltype == "alevel" else None

    expr_operator = create_expr_operator(expr)
    space_operator = ppsh.pp_remap_sh()
    time_operator = create_time_operator(task)
    zaxis_operator = create_level_operator(task)
    cmor_operator = pp2cmor.msg_to_cmor(task, store_var)

    if time_operator is None:
        log.warning("Dismissing task without time operator: %s in %s" % (task.target.variable, task.target.table))
        return None

    operators = [zaxis_operator, space_operator, expr_operator, time_operator, cmor_operator]
    operator_chain = [o for o in operators if o is not None]
    if time_operator.is_linear():
        for i in range(len(operator_chain) - 1):
            if operator_chain[i] is space_operator and operator_chain[i + 1] is time_operator:
                operator_chain[i] = time_operator
                operator_chain[i + 1] = space_operator
                break

    for i in range(0, len(operator_chain) - 1):
        operator_chain[i].targets.append(operator_chain[i + 1])
    return operator_chain[0]


def create_ps_operator():
    return ppsh.pp_remap_sh()


def create_expr_operator(expr):
    return None if expr is None else ppexpr.variable_expression(expr)


# Creates a time selection/aggregation operator for a specific task
def create_time_operator(task):
    freq = getattr(task.target, cmor_target.freq_key, None)
    operators = getattr(task.target, "time_operator", ["point"])
    periods = {"mon": relativedelta(months=1), "day": relativedelta(days=1)}
    operator_dict = {"mean": pptime.time_aggregator.linear_mean_operator,
                     "minimum": pptime.time_aggregator.min_operator,
                     "maximum": pptime.time_aggregator.max_operator}
    if len(operators) == 2 and operators[1] == "mean over years" and operators[0].endswith("within years"):
        clim_operator = operators[0][:-13]
        operators = [clim_operator]
    if len(operators) == 1:
        period, operator = periods.get(freq, None), operator_dict.get(operators[0], None)
        if period is None:
            # TODO: catch subhrPt
            if freq.endswith("hr"):
                period = relativedelta(hours=int(freq[:-2]))
            if freq.endswith("hrPt"):
                period = relativedelta(hours=int(freq[:-4]))
        if operators == ["point"] and freq.endswith("hrPt"):
            return pptime.time_filter(period, time_bounds=False)
        if operators == ["mean"] and freq.endswith("hr"):
            if all([c in cmor_source.ifs_source.grib_codes_accum for c in task.source.get_root_codes()]):
                return pptime.time_filter(period, time_bounds=True)
            else:
                log.warning("Requesting average over %d hours for instantaneous field %s is not supported, switching "
                            "to time sampling" % (period.hours, str(task.source.get_grib_code())))
            return pptime.time_filter(period, time_bounds=True)
        if period is not None and operator is not None:
            return pptime.time_aggregator(operator, period)
    log.error("Unsupported combination of frequency %s with time operators %s encountered for %s in table %s" %
              (freq, str(operators), task.target.variable, task.target.table))
    task.set_failed()
    return None


# Creates a vertical level aggregation operator for a specific task
def create_level_operator(task):
    # TODO Correct this for composed variables
    if task.source.get_grib_code() not in cmor_source.ifs_source.grib_codes_3D:
        return None
    axisname, leveltype, levels = cmor_target.get_z_axis(task.target)
    if leveltype == "alevel":
        return pplevels.level_aggregator(level_type=grib_file.hybrid_level_code, levels=None)
    if leveltype == "alevhalf":
        log.error("Vertical half-levels in table %s are not supported by this post-processing software",
                  task.target.table)
        task.set_failed()
        return None
    if leveltype in ["height", "altitude"]:
        return pplevels.level_aggregator(level_type=grib_file.height_level_code, levels=[float(l) for l in levels])
    if leveltype in ["air_pressure"]:
        return pplevels.level_aggregator(level_type=grib_file.pressure_level_code, levels=[float(l) for l in levels])
    return None