from builtins import range
from past.builtins import basestring
from builtins import object
import os
import re
import json
import logging

# Log object.
log = logging.getLogger(__name__)

# Axes information read from tables.
axes = {}

# Special files:
coord_file = "coordinate"

# Json file keys:
head_key = "header"
specs_version_key = "data_specs_version"
cmor_version_key = "cmor_version"
conventions_key = "Conventions"
date_key = "table_date"
axis_key = "axis_entry"
var_key = "variable_entry"
freq_key = "frequency"
realm_key = "modeling_realm"
missval_key = "missing_value"
int_missval_key = "int_missing_value"
dims_key = "dimensions"
levs_key = "generic_levels"
cell_measures_key = "cell_measures"
cell_methods_key = "cell_methods"
valid_min_key = "valid_min"
valid_max_key = "valid_max"
cell_measure_axes = ["time", "area", "volume", "latitude", "longitude", "grid_latitude", "grid_longitude", "depth"]
mask_key = "mask"
xydims = {"latitude", "longitude", "gridlatitude", "gridlongitude", "xgre", "ygre", "xant", "yant"}
extra_dims = {"basin", "spectband", "iceband", "landUse", "vertices", "effectRadLi", "effectRadIc", "tau",
              "lambda550nm", "scatratio", "dbze", "soilpools", "sza5", "vegtype", "site", "siline"}


# Class for cmor target objects, which represent output variables.
class cmor_target(object):

    def __init__(self, var_id__, tab_id__):
        self.variable = var_id__
        self.table = tab_id__
        self.dims = 2

    def __str__(self):
        return self.table + ": " + self.variable


# Derives the table id for the given file path
def get_table_id(filepath, prefix):
    fname = os.path.basename(filepath)
    regex = re.search("^" + prefix + "_.*.json$", fname)
    if not regex:
        raise Exception("Unable to match file name", fname, "as cmor table json-file with prefix", prefix)
    return regex.group()[len(prefix) + 1:len(fname) - 5]


def print_drq_version(filepath):
    with open(filepath, 'r') as f:
        try:
            data = json.loads(f.read())
            header = get_lowercase(data, head_key, None)
            if header is None:
                return False
            for key in [specs_version_key, cmor_version_key, conventions_key, date_key]:
                log.info("CMOR tables %s : %s" % (key, header.get(key, "unknown")))
            return True
        except ValueError as err:
            log.warning("Input table %s has been ignored. Reason: %s" % (filepath, format(err)))
            return False


# Creates cmor-targets from the input json-file
def create_targets_for_file(filepath, prefix):
    global log, axes, head_key, freq_key, realm_key, levs_key, axis_key, var_key, dims_key
    global cell_methods_key, cell_measures_key, cell_measure_axes
    tabid = get_table_id(filepath, prefix)
    with open(filepath, 'r') as f:
        result = []
        try:
            data = json.loads(f.read())
        except ValueError as err:
            log.warning("Input table %s has been ignored. Reason: %s" % (filepath, format(err)))
            return result
    freq = None
    realm = None
    header = get_lowercase(data, head_key, None)
    modlevs = None
    missval = None
    missvalint = None
    if header:
        freq = get_lowercase(header, freq_key, None)
        realm = get_lowercase(header, realm_key, None)
        missval = get_lowercase(header, missval_key, None)
        missvalint = get_lowercase(header, int_missval_key, None)
        modlevs = get_lowercase(header, levs_key, None)
    axes_entries = get_lowercase(data, axis_key, {})
    if modlevs:
        for modlev in modlevs.split():
            axes_entries[modlev] = {"requested": "all"}
    axes[tabid] = axes_entries
    var_entries = get_lowercase(data, var_key, {})
    for k, v in var_entries.items():
        target = cmor_target(k, tabid)
        target.frequency = freq
        target.realm = realm
        if missval:
            setattr(target, missval_key, float(missval))
        if missvalint:
            setattr(target, int_missval_key, int(missvalint))
        for k2, v2 in v.items():
            key = k2.lower()
            setattr(target, key, v2)
            if key == dims_key.lower():
                spacedims = list(set([s for s in v2.split() if not (s.lower().startswith("time") or
                                                                    s.lower().startswith("type"))])
                                 - extra_dims)
                setattr(target, "space_dims", spacedims)
                target.dims = len(spacedims)
                zdims = list(set(spacedims) - xydims)
                if any(zdims):
                    setattr(target, "z_dims", zdims)
            if key in [cell_measures_key.lower(), cell_methods_key.lower()]:
                cell_measure_str = re.sub("[\(\[].*?[\)\]]", "", v2.strip())
                if cell_measure_str not in ["@OPT", "--OPT", "", None]:
                    cell_measures = cell_measure_str.split(':')
                    for i in range(1, len(cell_measures)):
                        prev_words = cell_measures[i - 1].split()
                        if len(prev_words) == 0:
                            log.error("Error parsing cell measures %s for variable %s in table %s" % (v2, k, tabid))
                            break
                        measure_dim = prev_words[-1].strip().lower()
                        if measure_dim not in cell_measure_axes:
                            log.error("Error parsing cell measures %s for variable %s in table %s" % (v2, k, tabid))
                            break
                        key = measure_dim + "_operator"
                        value = cell_measures[i].strip().lower()
                        if i < len(cell_measures) - 1:
                            value = ' '.join(value.split(' ')[:-1])
                        if hasattr(target, key):
                            getattr(target, key).append(value)
                        else:
                            setattr(target, key, [value])
        if validate_target(target):
            result.append(target)
    return result


# Creates axes info dictionaries for given file
def create_axes_for_file(filepath, prefix):
    global log, axes, axis_key
    tabid = get_table_id(filepath, prefix)
    with open(filepath, 'r') as f:
        result = []
        try:
            data = json.loads(f.read())
        except ValueError as err:
            log.warning("Input table %s has been ignored. Reason: %s" % (filepath, format(err)))
            return result
        axes[tabid] = get_lowercase(data, axis_key, {})


# Utility function for lower-case dictionary searches
def get_lowercase(dictionary, key, default):
    if not isinstance(key, basestring):
        return dictionary.get(key, default)
    lowerkey = key.lower()
    for k, v in dictionary.items():
        if isinstance(k, basestring) and k.lower() == lowerkey:
            return v
    return default


# Creates cmor-targets from all json files in the given directory, with argument prefix.
def create_targets(path, prefix):
    global coord_file
    result = []
    drq_version_printed = False
    if os.path.isfile(path):
        if os.path.basename(path) not in [prefix + "_CV.json", prefix + "_CV_test.json"]:
            print_drq_version(path)
            result = result + create_targets_for_file(path, prefix)
    elif os.path.isdir(path):
        coordfilepath = os.path.join(path, prefix + "_" + coord_file + ".json")
        if not drq_version_printed:
            drq_version_printed = print_drq_version(coordfilepath)
        if os.path.exists(coordfilepath):
            create_axes_for_file(coordfilepath, prefix)
        expr = re.compile("^" + prefix + "_.*.json$")
        paths = [os.path.join(path, f) for f in os.listdir(path) if re.match(expr, f)]
        for p in paths:
            if os.path.basename(p) not in [prefix + "_CV.json", prefix + "_CV_test.json"]:
                if not drq_version_printed:
                    drq_version_printed = print_drq_version(p)
                result = result + create_targets_for_file(p, prefix)
    return result


# Validates a CMOR target, skipping those that do not make any sense
def validate_target(target):
    global log, valid_min_key, valid_max_key
    minstr = getattr(target, valid_min_key, "").strip()
    maxstr = getattr(target, valid_max_key, "").strip()
    minnr = float(minstr) if minstr else -float("inf")
    maxnr = float(maxstr) if maxstr else float("inf")
    if minnr == maxnr:
        log.error("The target variable %s in table %s has invalid bounds..."
                  "skipping this target" % (target.variable, target.table))
        return False
    return True


model_axes = ["alevel", "alevhalf", "olevel", "olevhalf"]
pressure_axes = ["air_pressure"]
height_axes = ["height", "altitude"]  # TODO: distinguish


# Returns the frequency (in hours) of the target variable
def get_freq(target):
    freq = getattr(target, freq_key, None)
    if freq == "day":
        return 24
    if freq in ["6hr", "6hrPt"]:
        return 6
    if freq in ["3hr", "3hrPt"]:
        return 3
    if freq in ["1hr", "1hrPt"]:
        return 1
    if freq in ["subhr", "subhrPt", "fx"]:
        return 0
    return -1


def is_instantaneous(target):
    time_operator = getattr(target, "time_operator", [])
    return len(time_operator) == 0 or time_operator[0] in ["point", "instant"]


# Sets the z-axis attributes for the given target
def get_z_axis(target):
    global log
    result = []
    for axisname in getattr(target, "z_dims", []):
        if axisname in model_axes:
            result.append((axisname, [-1]))
        else:
            axisinfo = get_axis_info(target.table).get(axisname, None)
            if not axisinfo:
                print(target.__dict__)
                log.warning("Could not retrieve information for axis %s in table %s" % (axisname, target.table))
                continue
            zvar = axisinfo.get("standard_name", None)
            if zvar in pressure_axes + height_axes:
                levels = axisinfo.get("requested", [])
                if not any(levels):
                    val = axisinfo.get("value", None)
                    if val:
                        levels = [val]
                if not any(levels):
                    log.warning("Could not retrieve levels for vertical coordinate %s" % axisname)
                    continue
                result.append((zvar, levels))
    if not any(result):
        return None, []
    if len(result) > 1:
        log.warning("Multiple vertical axes declared for variable %s in table %s:"
                    "taking first coordinate %s" % target.var_id, target.tab_id, result[0][0])
    return result[0]


# Returns the axes defined for the input table.
def get_axis_info(table_id):
    global axes, coord_file
    result = axes.get(coord_file, {})
    overrides = axes.get(table_id, {})
    for k, v in overrides.items():
        result[k] = v
    return result
