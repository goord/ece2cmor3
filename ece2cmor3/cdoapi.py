from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import object
import _thread
import numpy
import logging
import cdo
import os

# Log object
log = logging.getLogger(__name__)


# Class for interfacing with the CDO python wrapper.
class cdo_command(object):
    # CDO operator strings
    timselmean_operator = "timselmean"
    timselmin_operator = "timselmin"
    timselmax_operator = "timselmax"
    select_code_operator = "selcode"
    select_var_operator = "selvar"
    set_code_operator = "setcode"
    set_missval_operator = "setmissval"
    expression_operator = "expr"
    add_expression_operator = "aexpr"
    spectral_operator = "sp2gpl"
    gridtype_operator = "setgridtype"
    area_operator = "gridarea"
    select_z_operator = "selzaxis"
    select_lev_operator = "sellevel"
    select_step_operator = "seltimestep"
    shift_time_operator = "shifttime"
    ml2pl_operator = "ml2plx"
    ml2hl_operator = "ml2hl"
    merge_operator = "merge"
    set_misstoc_operator = "setmisstoc"

    # CDO operators
    min = "min"
    max = "max"
    mean = "mean"
    sum = "sum"
    select = "sel"

    # CDO time intervals
    hour = "hour"
    day = "day"
    month = "mon"
    year = "year"

    # CDO spatial keywords
    zonal = "zon"
    meridional = "mer"
    field = "fld"

    # CDO level/grid keywords
    regular_grid_type = "regular"
    height = "height"
    pressure = "pressure"
    model_level = "hybrid"
    surf_level = "surface"

    post_expr_operator = "post_expr"
    post_addexpr_operator = "post_aexpr"

    # Optimized operator ordering for CDO:
    operator_ordering = [set_code_operator, post_expr_operator, post_addexpr_operator, set_misstoc_operator, year + sum,
                         year + mean, year + min, year + max, month + sum, month + mean, month + min, month + max,
                         day + sum, day + mean, day + min, day + max, timselmean_operator, zonal + sum, zonal + mean,
                         zonal + min, zonal + max, meridional + sum, meridional + mean, meridional + min, meridional + max,
                         field + sum, field + mean, field + min, field + max, area_operator, gridtype_operator,
                         ml2pl_operator, ml2hl_operator, set_missval_operator, add_expression_operator,
                         expression_operator, spectral_operator, select_lev_operator, select_z_operator, select + hour,
                         select + day, select + month, shift_time_operator, select_step_operator, select_code_operator]

    # Constructor
    def __init__(self, code=0):
        self.operators = {}
        self.app = cdo.Cdo()
        if code > 0:
            self.add_operator(cdo_command.select_code_operator, code)

    # Adds an operator
    def add_operator(self, operator, *args):
        global log
        if operator in cdo_command.operator_ordering:
            if operator not in self.operators:
                self.operators[operator] = list(args)
            else:
                self.operators[operator].extend(list(args))
        else:
            log.error("Unknown operator was rejected: ", operator)

    # Creates a command string from the given operator list
    def create_command(self):
        keys = cdo_command.optimize_order(
            sorted(list(self.operators.keys()), key=lambda op: cdo_command.operator_ordering.index(op)))
        return " ".join([cdo_command.make_option(k, self.operators[k]) for k in keys])

    def merge(self, ifiles, ofile):
        if isinstance(ifiles, str):
            return self.app.merge(input=ifiles, output=ofile)
        return self.app.merge(input=' '.join(ifiles), output=ofile)

    def show_code(self, ifile):
        return self.app.showcode(input=ifile)

    # Applies the current set of operators to the input file.
    def apply(self, ifile, ofile=None, threads=4, grib_first=False):
        global log
        keys = cdo_command.optimize_order(
            sorted(list(self.operators.keys()), key=lambda op: cdo_command.operator_ordering.index(op)))
        option_string = "-f nc" if threads < 2 else ("-f nc -P " + str(threads))
        if grib_first:
            option_string = "" if threads < 2 else ("-P " + str(threads))
        func = getattr(self.app, keys[0], None)
        app_args = None
        if func:
            app_args = ",".join([str(a) for a in self.operators.get(keys[0], [])])
            input_string = " ".join([cdo_command.make_option(k, self.operators[k]) for k in keys[1:]] + [ifile])
        else:
            func = getattr(self.app, "copy")
            input_string = " ".join([cdo_command.make_option(k, self.operators[k]) for k in keys] + [ifile])
        output_file = ofile
        if ofile and grib_first:
            output_file = ofile[:-3] + ".grib"
        ntries = 0
        max_tries = int(os.environ.get("ECE2CMOR3_CDO_TRIALS", 4))
        f = None
        while ntries < max_tries:
            ntries += 1
            try:
                if app_args and ofile:
                    f = func(app_args, input=input_string, output=output_file, options=option_string)
                elif app_args:
                    f = func(app_args, input=input_string, options=option_string)
                elif ofile:
                    f = func(input=input_string, output=output_file, options=option_string)
                else:
                    f = func(input=input_string, options=option_string)
                if grib_first:
                    option_string = "-f nc"
                    f = self.app.copy(input=output_file, output=ofile, options=option_string)
                    try:
                        os.remove(output_file)
                    except OSError as eos:
                        log.error(str(eos))
                return f
            except cdo.CDOException as e:
                if ntries == max_tries:
                    log.error("Attempt %d/%d to apply cdo %s %s %s failed:" %
                              (ntries, max_tries, option_string, input_string, output_file))
                    log.error(str(e))
                else:
                    log.warning("Attempt %d/%d to apply cdo %s %s %s failed, retrying..." %
                                (ntries, max_tries, option_string, input_string, output_file))
                    if os.path.isfile(output_file):
                        try:
                            os.remove(output_file)
                        except OSError as eos:
                            log.error(str(eos))
                    if os.path.isfile(ofile):
                        try:
                            os.remove(ofile)
                        except OSError as eos:
                            log.error(str(eos))
                f = None
        return f

    # Applies the current set of operators and returns the netcdf variables in memory:
    def apply_cdf(self, ifile, threads=4):
        keys = cdo_command.optimize_order(
            sorted(list(self.operators.keys()), key=lambda op: cdo_command.operator_ordering.index(op)))
        option_string = "" if threads < 2 else ("-P " + str(threads))
        func = getattr(self.app, keys[0], None)
        app_args = None
        if func:
            app_args = ",".join([str(a) for a in self.operators.get(keys[0], [])])
            input_string = " ".join([cdo_command.make_option(k, self.operators[k]) for k in keys[1:]] + [ifile])
        else:
            func = getattr(self.app, "copy")
            input_string = " ".join([cdo_command.make_option(k, self.operators[k]) for k in keys] + [ifile])
        try:
            if app_args:
                return func(app_args, input=input_string, options=option_string, returnCdf=True).variables
            else:
                return func(input=input_string, options=option_string, returnCdf=True).variables
        except cdo.CDOException as e:
            log.error(str(e))
            return None

    # Grid description method
    def get_grid_descr(self, ifile):
        global log
        int_fields = ["gridsize", "np", "xsize", "ysize"]
        real_fields = ["xfirst", "xinc", "yfirst", "yinc"]
        array_fields = ["xvals", "yvals"]
        infolist = []
        try:
            infolist = self.app.griddes(input=ifile)
        except cdo.CDOException as e:
            log.error(str(e))
        info_dict = {}
        prev_key = ""
        for info in infolist:
            s = str(info)
            if len(s) == 0:
                continue
            if s[0] == '#':
                continue
            string_list = s.split('=')
            if len(string_list) == 0:
                continue
            elif len(string_list) == 1:
                if prev_key in info_dict:
                    info_dict[prev_key] += (' ' + string_list[0].strip())
                else:
                    log.error("Could not connect grid description line %s to an "
                              "existing key-value pair" % string_list[0])
                    continue
            elif len(string_list) == 2:
                key = string_list[0].strip()
                info_dict[key] = string_list[1].strip()
                prev_key = key
            else:
                log.error("Could not parse grid description line %s as a key-value pair" % s)
                continue
        for k, v in info_dict.items():
            if k in int_fields:
                info_dict[k] = int(v)
            if k in real_fields:
                info_dict[k] = float(v)
            if k in array_fields:
                info_dict[k] = numpy.array([float(x) for x in v.split()])
        return info_dict

    # Returns a list vertical axes corresponding to the input variable
    def get_z_axes(self, ifile, var):
        if not ifile:
            return []
        select_operator = cdo_command.select_code_operator if isinstance(var, int) else cdo_command.select_var_operator
        try:
            output = self.app.showltype(input=" ".join([cdo_command.make_option(select_operator, [var]), ifile]))
        except cdo.CDOException as e:
            log.error(str(e))
            return []
        if isinstance(output, list):
            output = output[0]
        return [] if not output else [int(s) for s in output.split()]

    # Returns a list of levels for a given variable and axis
    def get_levels(self, ifile, var, axis):
        if not ifile:
            return []
        select_operator = cdo_command.select_code_operator if isinstance(var, int) else cdo_command.select_var_operator
        selvar_operator = cdo_command.make_option(select_operator, [var])
        selzaxis_operator = cdo_command.make_option(cdo_command.select_z_operator, [axis])
        try:
            output = self.app.showlevel(input=" ".join([selzaxis_operator, selvar_operator, ifile]))
        except cdo.CDOException as e:
            log.error(str(e))
            return []
        if isinstance(output, list):
            output = output[0]
        return [] if not output else [float(s) for s in output.split()]

    # Option writing utility function
    @staticmethod
    def make_option(key, args):
        option = "-" + key
        if key == cdo_command.post_expr_operator:
            option = "-" + cdo_command.expression_operator
        if key == cdo_command.post_addexpr_operator:
            option = "-" + cdo_command.add_expression_operator
        if key in [cdo_command.expression_operator, cdo_command.add_expression_operator, cdo_command.post_expr_operator,
                   cdo_command.post_addexpr_operator]:
            return option + ",\'" + ';'.join([str(a) for a in args]) + "\'"
        return (option + "," + ",".join([str(a) for a in args])) if any(args) else option

    # Reshuffles operator ordering to increase performance
    @staticmethod
    def optimize_order(operator_list):
        i1 = operator_list.index(cdo_command.spectral_operator) if cdo_command.spectral_operator in operator_list else 0
        i2 = operator_list.index(cdo_command.gridtype_operator) if cdo_command.gridtype_operator in operator_list else 0
        times = [cdo_command.year, cdo_command.month, cdo_command.day]
        ops = [cdo_command.mean, cdo_command.min, cdo_command.max, cdo_command.sum]
        zones = [cdo_command.zonal, cdo_command.meridional, cdo_command.field]
        nonlinear_operators = [t + cdo_command.min for t in times] + [t + cdo_command.max for t in times] + \
                              [z + o for o in ops for z in zones] + \
                              [cdo_command.expression_operator, cdo_command.add_expression_operator] + \
                              [cdo_command.area_operator]
        i = i1 + i2
        while i > 0:
            if operator_list[i - 1] in nonlinear_operators:
                break
            operator_list[i - 1], operator_list[i] = operator_list[i], operator_list[i - 1]
            i -= 1
        return operator_list
