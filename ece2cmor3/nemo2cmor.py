from __future__ import absolute_import
from builtins import str
from builtins import range
from builtins import object
import logging
import os
import re
from datetime import timedelta

import cmor
import netCDF4
import numpy

from ece2cmor3 import cmor_target, cmor_task, cmor_utils
from .__load_nemo_vertices__ import load_vertices_from_file

timeshift = timedelta(0)
# Apply timeshift for instance in case you want manually to add a shift for the piControl:
# timeshift = datetime(2260,1,1) - datetime(1850,1,1)

# Logger object
log = logging.getLogger(__name__)

# Test mode: accept oddly-sized test grids etc.
test_mode_ = False

extra_axes = {"basin": {"ncdim": "3basin",
                        "ncvals": ["global_ocean", "atlantic_arctic_ocean", "indian_pacific_ocean"]},
              "typesi": {"ncdim": "ncatice"},
              "iceband": {"ncdim": "ncatice",
                          "ncunits": "m",
                          "ncvals": [0.277, 0.7915, 1.635, 2.906, 3.671],
                          "ncbnds": [0., 0.454, 1.129, 2.141, 3.671, 99.0]}}

# Experiment name
exp_name_ = None

# Reference date
ref_date_ = None

# Table root
table_root_ = None

# Files that are being processed in the current execution loop.
nemo_files_ = []

# Nemo bathymetry file
bathy_file_ = None

# Nemo bathymetry grid
bathy_grid_ = "opa_grid_T_2D"

# Nemo basin file
basin_file_ = None

# Nemo subbasin grid
basin_grid_ = "opa_grid_T_2D"

# Dictionary of NEMO grid type with cmor grid id.
grid_ids_ = {}

# List of depth axis ids with cmor grid id.
depth_axes_ = {}

# Dictionary of output frequencies with cmor time axis id.
time_axes_ = {}

# Dictionary of sea-ice output types, 1 by default.
type_axes_ = {}

# Dictionary of latitude axes ids for meridional variables.
lat_axes_ = {}

# Dictionary of masks
nemo_masks_ = {}


# Initializes the processing loop.
def initialize(path, expname, tableroot, refdate, testmode=False):
    global log, nemo_files_, bathy_file_, basin_file_, exp_name_, table_root_, ref_date_, test_mode_
    exp_name_ = expname
    table_root_ = tableroot
    ref_date_ = refdate
    test_mode_ = testmode
    nemo_files_ = cmor_utils.find_nemo_output(path, expname)
    expdir = os.path.abspath(os.path.join(os.path.realpath(path), "..", "..", ".."))
    ofxdir = os.path.abspath(os.path.join(os.path.realpath(path), "..", "ofx-data"))
    bathy_file_ = os.path.join(ofxdir, "bathy_meter.nc")
    if not os.path.isfile(bathy_file_):
        # Look in env or ec-earth run directory
        bathy_file_ = os.environ.get("ECE2CMOR3_NEMO_BATHY_METER", os.path.join(expdir, "bathy_meter.nc"))
    if not os.path.isfile(bathy_file_):
        log.warning("Nemo bathymetry file %s does not exist...variable deptho in Ofx will be dismissed "
                    "whenever encountered" % bathy_file_)
        bathy_file_ = None
    basin_file_ = os.path.join(ofxdir, "subbasins.nc")
    if not os.path.isfile(basin_file_):
        # Look in env or ec-earth run directory
        basin_file_ = os.environ.get("ECE2CMOR3_NEMO_SUBBASINS", os.path.join(expdir, "subbasins.nc"))
    if not os.path.isfile(basin_file_):
        log.warning("Nemo subbasin file %s does not exist...variable basin in Ofx will be dismissed "
                    "whenever encountered" % basin_file_)
        basin_file_ = None
    return True


# Resets the module globals.
def finalize():
    global nemo_files_, grid_ids_, depth_axes_, time_axes_
    nemo_files_ = []
    grid_ids_ = {}
    depth_axes_ = {}
    time_axes_ = {}


# Executes the processing loop.
def execute(tasks):
    global log, time_axes_, depth_axes_, table_root_
    log.info("Looking up variables in files...")
    tasks = lookup_variables(tasks)
    log.info("Creating NEMO grids in CMOR...")
    create_grids(tasks)
    log.info("Creating NEMO masks...")
    create_masks(tasks)
    log.info("Executing %d NEMO tasks..." % len(tasks))
    log.info("Cmorizing NEMO tasks...")
    task_groups = cmor_utils.group(tasks, lambda tsk1: getattr(tsk1, cmor_task.output_path_key, None))
    for filename, task_group in task_groups.items():
        dataset = netCDF4.Dataset(filename, 'r')
        task_sub_groups = cmor_utils.group(task_group, lambda tsk2: tsk2.target.table)
        for table, task_list in task_sub_groups.items():
            log.info("Start cmorization of %s in table %s" % (','.join([t.target.variable for t in task_list]), table))
            try:
                tab_id = cmor.load_table("_".join([table_root_, table]) + ".json")
                cmor.set_table(tab_id)
            except Exception as e:
                log.error("CMOR failed to load table %s, skipping variables %s. Reason: %s"
                          % (table, ','.join([tsk3.target.variable for tsk3 in task_list]), e.message))
                continue
            if table not in time_axes_:
                log.info("Creating time axes for table %s from data in %s..." % (table, filename))
            create_time_axes(dataset, task_list, table)
            if table not in depth_axes_:
                log.info("Creating depth axes for table %s from data in %s ..." % (table, filename))
            create_depth_axes(dataset, task_list, table)
            if table not in type_axes_:
                log.info("Creating extra axes for table %s from data in %s ..." % (table, filename))
            create_type_axes(dataset, task_list, table)
            for task in task_list:
                execute_netcdf_task(dataset, task)
        dataset.close()


def lookup_variables(tasks):
    valid_tasks = []
    for task in tasks:
        if (task.target.table, task.target.variable) == ("Ofx", "deptho"):
            if bathy_file_ is None:
                log.error("Could not use bathymetry file for variable deptho in table Ofx: task skipped.")
                task.set_failed()
            else:
                setattr(task, cmor_task.output_path_key, bathy_file_)
                valid_tasks.append(task)
            continue
        if (task.target.table, task.target.variable) == ("Ofx", "basin"):
            if basin_file_ is None:
                log.error("Could not use subbasin file for variable basin in table Ofx: task skipped.")
                task.set_failed()
            else:
                setattr(task, cmor_task.output_path_key, basin_file_)
                valid_tasks.append(task)
            continue
        file_candidates = select_freq_files(task.target.frequency, task.target.variable)
        results = []
        for ncfile in file_candidates:
            ds = netCDF4.Dataset(ncfile)
            if task.source.variable() in ds.variables:
                results.append(ncfile)
            ds.close()
        if len(results) == 0:
            log.error('Variable {:20} in table {:10} was not found in the NEMO output files: task skipped.'
                      .format(task.source.variable(), task.target.table))
            task.set_failed()
            continue
        if len(results) > 1:
            log.error("Variable %s needed for %s in table %s was found in multiple NEMO output files %s... "
                      "dismissing task" % (task.source.variable(), task.target.variable, task.target.table,
                                           ','.join(results)))
            task.set_failed()
            continue
        setattr(task, cmor_task.output_path_key, results[0])
        valid_tasks.append(task)
    return valid_tasks


def create_basins(target, dataset):
    meanings = {"atlmsk": "atlantic_ocean", "indmsk": "indian_ocean", "pacmsk": "pacific_ocean"}
    flagvals = [int(s) for s in getattr(target, "flag_values", "").split()]
    basins = getattr(target, "flag_meanings", "").split()
    data = numpy.copy(dataset.variables["glomsk"][...])
    missval = int(getattr(target, cmor_target.int_missval_key))
    data[data > 0] = missval
    for var, basin in meanings.items():
        if var in list(dataset.variables.keys()) and basin in basins:
            flagval = flagvals[basins.index(basin)]
            arr = dataset.variables[var][...]
            data[arr > 0] = flagval
    return data, dataset.variables["glomsk"].dimensions, missval


# Performs a single task.
def execute_netcdf_task(dataset, task):
    global log
    task.status = cmor_task.status_cmorizing
    grid_axes = [] if not hasattr(task, "grid_id") else [getattr(task, "grid_id")]
    z_axes = getattr(task, "z_axes", [])
    t_axes = [] if not hasattr(task, "time_axis") else [getattr(task, "time_axis")]
    type_axes = [getattr(task, dim + "_axis") for dim in list(type_axes_.get(task.target.table, {}).keys()) if
                 hasattr(task, dim + "_axis")]
    # TODO: Read axes order from netcdf file!
    axes = grid_axes + z_axes + type_axes + t_axes
    srcvar = task.source.variable()
    if task.target.variable == "basin":
        ncvar, dimensions, missval = create_basins(task.target, dataset)
    else:
        ncvar = dataset.variables[srcvar]
        dimensions = ncvar.dimensions
        missval = getattr(ncvar, "missing_value", getattr(ncvar, "_FillValue", numpy.nan))
    varid = create_cmor_variable(task, srcvar, ncvar, axes)
    time_dim, index, time_sel = -1, 0, None
    for d in dimensions:
        if d.startswith("time"):
            time_dim = index
            break
        index += 1
    time_sel = None
    if len(t_axes) > 0 > time_dim:
        for d in dataset.dimensions:
            if d.startswith("time"):
                time_sel = list(range(len(d)))  # ensure copying of constant fields
                break
    if len(grid_axes) == 0:  # Fix for global averages/sums
        vals = numpy.ma.masked_equal(ncvar[...], missval)
        ncvar = numpy.mean(vals, axis=(1, 2))
    factor, term = get_conversion_constants(getattr(task, cmor_task.conversion_key, None))
    log.info('Cmorizing variable {:20} in table {:7} in file {}'
             .format(srcvar, task.target.table, getattr(task, cmor_task.output_path_key)))
    mask = getattr(task.target, cmor_target.mask_key, None)
    if mask is not None:
        mask = nemo_masks_.get(mask, None)
    cmor_utils.netcdf2cmor(varid, ncvar, time_dim, factor, term,
                           missval=getattr(task.target, cmor_target.missval_key, missval),
                           time_selection=time_sel,
                           mask=mask)
    cmor.close(varid, file_name=True)
    task.status = cmor_task.status_cmorized


# Returns the constants A,B for unit conversions of type y = A*x + B
def get_conversion_constants(conversion):
    global log
    if not conversion:
        return 1.0, 0.0
    if conversion == "tossqfix":
        return 1.0, 0.0
    if conversion == "frac2percent":
        return 100.0, 0.0
    if conversion == "percent2frac":
        return 0.01, 0.0
    if conversion == "K2degC":
        return 1.0, -273.15
    if conversion == "degC2K":
        return 1.0, 273.15
    if conversion == "sv2kgps":
        return 1.e+9, 0.
    log.error("Unknown explicit unit conversion %s will be ignored" % conversion)
    return 1.0, 0.0


# Creates a variable in the cmor package
def create_cmor_variable(task, srcvar, ncvar, axes):
    unit = getattr(ncvar, "units", None)
    if (not unit) or hasattr(task, cmor_task.conversion_key):  # Explicit unit conversion
        unit = getattr(task.target, "units")
    if hasattr(task.target, "positive") and len(task.target.positive) != 0:
        return cmor.variable(table_entry=str(task.target.variable), units=str(unit), axis_ids=axes,
                             original_name=str(srcvar), positive=getattr(task.target, "positive"))
    else:
        return cmor.variable(table_entry=str(task.target.variable), units=str(unit), axis_ids=axes,
                             original_name=str(srcvar))


# Creates all depth axes for the given table from the given files
def create_depth_axes(ds, tasks, table):
    global depth_axes_
    if table not in depth_axes_:
        depth_axes_[table] = {}
    log.info("Creating depth axes for table %s using file %s..." % (table, ds.filepath()))
    table_depth_axes = depth_axes_[table]
    other_nc_axes = ["time_counter", "x", "y"] + [extra_axes[k]["ncdim"] for k in list(extra_axes.keys())]
    for task in tasks:
        z_axes = []
        if task.source.variable() in ds.variables:
            z_axes = [d for d in ds.variables[task.source.variable()].dimensions if d not in other_nc_axes]
        z_axis_ids = []
        for z_axis in z_axes:
            if z_axis not in ds.variables:
                log.error("Cannot find variable %s in %s for vertical axis construction" % (z_axis, ds.filepath()))
                continue
            zvar = ds.variables[z_axis]
            axis_type = "half" if cmor_target.get_z_axis(task.target)[0] == "olevhalf" else "full"
            key = "-".join([getattr(zvar, "long_name"), axis_type])
            if key in table_depth_axes:
                z_axis_ids.append(table_depth_axes[key])
            else:
                depth_bounds = ds.variables[getattr(zvar, "bounds", None)]
                if depth_bounds is None:
                    log.warning("No depth bounds found in file %s, taking midpoints" % (ds.filepath()))
                    depth_bounds = numpy.zeros((len(zvar[:]), 2), dtype=numpy.float64)
                    depth_bounds[1:, 0] = 0.5 * (zvar[0:-1] + zvar[1:])
                    depth_bounds[0:-1, 1] = depth_bounds[1:, 0]
                    depth_bounds[0, 0] = zvar[0]
                    depth_bounds[-1, 1] = zvar[-1]
                entry = "depth_coord_half" if cmor_target.get_z_axis(task.target)[0] == "olevhalf" else "depth_coord"
                units = getattr(zvar, "units", "")
                if len(units) == 0:
                    log.warning("Assigning unit meters to depth coordinate %s without units" % entry)
                    units = "m"
                b = depth_bounds[:, :]
                b[b < 0] = 0
                z_axis_id = cmor.axis(table_entry=entry, units=units, coord_vals=zvar[:], cell_bounds=b)
                z_axis_ids.append(z_axis_id)
                table_depth_axes[key] = z_axis_id
        setattr(task, "z_axes", z_axis_ids)


def create_time_axes(ds, tasks, table):
    global time_axes_
    if table == "Ofx":
        return
    if table not in time_axes_:
        time_axes_[table] = {}
    log.info("Creating time axis for table %s using file %s..." % (table, ds.filepath()))
    table_time_axes = time_axes_[table]
    for task in tasks:
        tgtdims = getattr(task.target, cmor_target.dims_key)
        for time_dim in [d for d in list(set(tgtdims.split())) if d.startswith("time")]:
            if time_dim in table_time_axes:
                time_operator = getattr(task.target, "time_operator", ["point"])
                nc_operator = getattr(ds.variables[task.source.variable()], "online_operation", "instant")
                if time_operator[0] in ["point", "instant"] and nc_operator != "instant":
                    log.warning("Cmorizing variable %s with online operation attribute %s in %s to %s with time "
                                "operation %s" % (task.source.variable(), nc_operator, ds.filepath(), str(task.target),
                                                  time_operator[0]))
                if time_operator[0] in ["mean", "average"] and nc_operator != "average":
                    log.warning("Cmorizing variable %s with online operation attribute %s in %s to %s with time "
                                "operation %s" % (task.source.variable(), nc_operator, ds.filepath(), str(task.target),
                                                  time_operator[0]))
                tid = table_time_axes[time_dim]
            else:
                times, time_bounds, units, calendar = read_times(ds, task)
                if times is None:
                    log.error("Failed to read time axis information from file %s, skipping variable %s in table %s" %
                              (ds.filepath(), task.target.variable, task.target.table))
                    task.set_failed()
                    continue
                tstamps, tunits = cmor_utils.num2num(times, ref_date_, units, calendar, timeshift)
                if calendar != "proleptic_gregorian":
                    cmor.set_cur_dataset_attribute("calendar", calendar)
                if time_bounds is None:
                    tid = cmor.axis(table_entry=str(time_dim), units=tunits, coord_vals=tstamps)
                else:
                    tbounds, tbndunits = cmor_utils.num2num(time_bounds, ref_date_, units, calendar, timeshift)
                    tid = cmor.axis(table_entry=str(time_dim), units=tunits, coord_vals=tstamps,
                                    cell_bounds=tbounds)
                table_time_axes[time_dim] = tid
            setattr(task, "time_axis", tid)
    return table_time_axes


# Creates a time axis for the currently loaded table
def read_times(ds, task):
    def get_time_bounds(v):
        bnd = getattr(v, "bounds", None)
        if bnd in ds.variables:
            res = ds.variables[bnd][:, :]
        else:
            res = numpy.empty([len(v[:]), 2])
            res[1:, 0] = 0.5 * (v[0:-1] + v[1:])
            res[:-1, 1] = res[1:, 0]
            res[0, 0] = 1.5 * v[0] - 0.5 * v[1]
            res[-1, 1] = 1.5 * v[-1] - 0.5 * v[-2]
        return res

    vals, bndvals, units, calendar = None, None, None, None
    if cmor_target.is_instantaneous(task.target):
        ncvar = ds.variables.get("time_instant", None)
        if ncvar is not None:
            vals, units, calendar = ncvar[:], getattr(ncvar, "units", None), getattr(ncvar, "calendar", None)
        else:
            log.warning("Could not find time_instant variable in %s, looking for generic time..." % ds.filepath())
            for varname, ncvar in list(ds.variables.items()):
                if getattr(ncvar, "standard_name", "").lower() == "time":
                    log.warning("Found variable %s for instant time variable in file %s" % (varname, ds.filepath()))
                    vals, units, calendar = ncvar[:], getattr(ncvar, "units", None), getattr(ncvar, "calendar", None)
                    break
            if vals is None:
                log.error("Could not find time variable in %s for %s... giving up" % (ds.filepath(), str(task.target)))
    else:
        ncvar = ds.variables.get("time_centered", None)
        if ncvar is not None:
            vals, bndvals, units, calendar = ncvar[:], get_time_bounds(ncvar), getattr(ncvar, "units", None), \
                                             getattr(ncvar, "calendar", None)
        else:
            log.warning("Could not find time_centered variable in %s, looking for generic time..." % ds.filepath())
            for varname, ncvar in list(ds.variables.items()):
                if getattr(ncvar, "standard_name", "").lower() == "time":
                    log.warning("Found variable %s for instant time variable in file %s" % (varname, ds.filepath()))
                    vals, bndvals, units, calendar = ncvar[:], get_time_bounds(ncvar), getattr(ncvar, "units", None), \
                                                     getattr(ncvar, "calendar", None)
                    break
            if vals is None:
                log.error("Could not find time variable in %s for %s... giving up" % (ds.filepath(), str(task.target)))
    # Fix for proleptic gregorian in XIOS output as gregorian
    if calendar is None or calendar == "gregorian":
        calendar = "proleptic_gregorian"
    return vals, bndvals, units, calendar


def create_type_axes(ds, tasks, table):
    global type_axes_
    if table not in type_axes_:
        type_axes_[table] = {}
    log.info("Creating extra axes for table %s using file %s..." % (table, ds.filepath()))
    table_type_axes = type_axes_[table]
    for task in tasks:
        tgtdims = set(getattr(task.target, cmor_target.dims_key).split()).intersection(list(extra_axes.keys()))
        for dim in tgtdims:
            if dim in table_type_axes:
                axis_id = table_type_axes[dim]
            else:
                axisinfo = extra_axes[dim]
                nc_dim_name = axisinfo["ncdim"]
                if nc_dim_name in ds.dimensions:
                    ncdim, ncvals = ds.dimensions[nc_dim_name], axisinfo.get("ncvals", [])
                    if len(ncdim) == len(ncvals):
                        axis_values, axis_unit = ncvals, axisinfo.get("ncunits", "1")
                    else:
                        if any(ncvals):
                            log.error("Ece2cmor values for extra axis %s, %s, do not match dimension %s length %d found"
                                      " in file %s, taking values found in file" % (dim, str(ncvals), nc_dim_name,
                                                                                    len(ncdim), ds.filepath()))
                        ncvars = [v for v in ds.variables if list(ds.variables[v].dimensions) == [ncdim]]
                        axis_values, axis_unit = list(range(len(ncdim))), "1"
                        if any(ncvars):
                            if len(ncvars) > 1:
                                log.warning("Multiple axis variables found for dimension %s in file %s, choosing %s" %
                                            (nc_dim_name, ds.filepath(), ncvars[0]))
                            axis_values, axis_unit = list(ncvars[0][:]), getattr(ncvars[0], "units", None)
                else:
                    log.error("Dimension %s could not be found in file %s, inserting using length-one dimension "
                              "instead" % (nc_dim_name, ds.filepath()))
                    axis_values, axis_unit = [1], "1"
                if "ncbnds" in axisinfo:
                    bndlist = axisinfo["ncbnds"]
                    if len(bndlist) - 1 != len(axis_values):
                        log.error("Length of axis bounds %d does not correspond to axis coordinates %s" %
                                  (len(bndlist) - 1, str(axis_values)))
                    bnds = numpy.zeros((len(axis_values), 2))
                    bnds[:, 0] = bndlist[:-1]
                    bnds[:, 1] = bndlist[1:]
                    axis_id = cmor.axis(table_entry=dim, coord_vals=axis_values, units=axis_unit, cell_bounds=bnds)
                else:
                    axis_id = cmor.axis(table_entry=dim, coord_vals=axis_values, units=axis_unit)
                table_type_axes[dim] = axis_id
            setattr(task, dim + "_axis", axis_id)
    return table_type_axes


# Selects files with data with the given frequency
def select_freq_files(freq, varname):
    global exp_name_, nemo_files_
    if freq == "fx":
        nemo_freq = "1y"
    elif freq in ["yr", "yrPt"]:
        nemo_freq = "1y"
    elif freq == "monPt":
        nemo_freq = "1m"
    # TODO: Support climatological variables
    # elif freq == "monC":
    #    nemo_freq = "1m"   # check
    elif freq.endswith("mon"):
        n = 1 if freq == "mon" else int(freq[:-3])
        nemo_freq = str(n) + "m"
    elif freq.endswith("day"):
        n = 1 if freq == "day" else int(freq[:-3])
        nemo_freq = str(n) + "d"
    elif freq.endswith("hr"):
        n = 1 if freq == "hr" else int(freq[:-2])
        nemo_freq = str(n) + "h"
    elif freq.endswith("hrPt"):
        n = 1 if freq == "hrPt" else int(freq[:-4])
        nemo_freq = str(n) + "h"
    else:
        log.error('Could not associate cmor frequency {:7} with a '
                  'nemo output frequency for variable {}'.format(freq, varname))
        return []
    return [f for f in nemo_files_ if cmor_utils.get_nemo_frequency(f, exp_name_) == nemo_freq]


def create_masks(tasks):
    global nemo_masks_
    for task in tasks:
        mask = getattr(task.target, cmor_target.mask_key, None)
        if mask is not None and mask not in list(nemo_masks_.keys()):
            for nemo_file in nemo_files_:
                ds = netCDF4.Dataset(nemo_file, 'r')
                maskvar = ds.variables.get(mask, None)
                if maskvar is not None:
                    dims = maskvar.dimensions
                    if len(dims) == 2:
                        nemo_masks_[mask] = numpy.logical_not(numpy.ma.getmask(maskvar[...]))
                    elif len(dims) == 3:
                        nemo_masks_[mask] = numpy.logical_not(numpy.ma.getmask(maskvar[0, ...]))
                    else:
                        log.error("Could not create mask %s from nc variable with %d dimensions" % (mask, len(dims)))


# Reads all the NEMO grid data from the input files.
def create_grids(tasks):
    task_by_file = cmor_utils.group(tasks, lambda tsk: getattr(tsk, cmor_task.output_path_key, None))

    def get_nemo_grid(f):
        if f == bathy_file_:
            return bathy_grid_
        if f == basin_file_:
            return basin_grid_
        return cmor_utils.get_nemo_grid(f)

    file_by_grid = cmor_utils.group(list(task_by_file.keys()), get_nemo_grid)
    for grid_name, file_paths in file_by_grid.items():
        output_files = set(file_paths) - {bathy_file_, basin_file_, None}
        if any(output_files):
            filename = list(output_files)[0]
        else:
            filename = file_paths[0]
            log.warning("Using the file %s of EC-Earth to build %s due to lack of other output" % (filename, grid_name))
        grid = read_grid(filename)
        write_grid(grid, [t for fname in file_paths for t in task_by_file[fname]])


# Reads a particular NEMO grid from the given input file.
def read_grid(ncfile):
    ds = None
    try:
        ds = netCDF4.Dataset(ncfile, 'r')
        name = getattr(ds.variables["nav_lon"], "nav_model", cmor_utils.get_nemo_grid(ncfile))
        if name == "scalar":
            return None
        lons = ds.variables["nav_lon"][:, :] if "nav_lon" in ds.variables else []
        lats = ds.variables["nav_lat"][:, :] if "nav_lat" in ds.variables else []
        if len(lons) == 0 and len(lats) == 0:
            return None
        return nemo_grid(name, lons, lats)
    finally:
        if ds is not None:
            ds.close()


# Transfers the grid to cmor.
def write_grid(grid, tasks):
    global grid_ids_, lat_axes_
    nx = grid.lons.shape[0]
    ny = grid.lons.shape[1]
    if ny == 1:
        if nx == 1:
            log.error("The grid %s consists of a single point which is not supported, dismissing variables %s" %
                      (grid.name, ','.join([t.target.variable + " in " + t.target.table for t in tasks])))
            return
        for task in tasks:
            dims = getattr(task.target, "space_dims", "")
            if "longitude" in dims:
                log.error("Variable %s in %s has longitude dimension, but this is absent in the ocean output file of "
                          "grid %s" % (task.target.variable, task.target.table, grid.name))
                task.set_failed()
                continue
            latnames = {"latitude", "gridlatitude"}
            latvars = list(set(dims).intersection(set(latnames)))
            if not any(latvars):
                log.error("Variable %s in %s has no (grid-)latitude defined where its output grid %s does, dismissing "
                          "it" % (task.target.variable, task.target.table, grid.name))
                task.set_failed()
                continue
            if len(latvars) > 1:
                log.error("Variable %s in %s with double-latitude dimensions %s is not supported" %
                          (task.target.variable, task.target.table, str(dims)))
                task.set_failed()
                continue
            key = (task.target.table, grid.name, latvars[0])
            if key not in list(lat_axes_.keys()):
                cmor.load_table(table_root_ + "_" + task.target.table + ".json")
                lat_axis_id = cmor.axis(table_entry=latvars[0], coord_vals=grid.lats[:, 0], units="degrees_north",
                                        cell_bounds=grid.vertex_lats)
                lat_axes_[key] = lat_axis_id
            else:
                lat_axis_id = lat_axes_[key]
            setattr(task, "grid_id", lat_axis_id)
    else:
        if grid.name not in grid_ids_:
            cmor.load_table(table_root_ + "_grids.json")
            i_index_id = cmor.axis(table_entry="j_index", units="1", coord_vals=numpy.array(list(range(1, nx + 1))))
            j_index_id = cmor.axis(table_entry="i_index", units="1", coord_vals=numpy.array(list(range(1, ny + 1))))
            grid_id = cmor.grid(axis_ids=[i_index_id, j_index_id],
                                latitude=grid.lats,
                                longitude=grid.lons,
                                latitude_vertices=grid.vertex_lats,
                                longitude_vertices=grid.vertex_lons)
            grid_ids_[grid.name] = grid_id
        else:
            grid_id = grid_ids_[grid.name]
        for task in tasks:
            dims = getattr(task.target, "space_dims", [])
            if "latitude" in dims and "longitude" in dims:
                setattr(task, "grid_id", grid_id)
            else:
                log.error("Variable %s in %s has output on a 2d horizontal grid, but its requested dimensions are %s" %
                          (task.target.variable, task.target.table, str(dims)))
                task.set_failed()


# Get the NEMO grid type utility:
def get_grid_type(grid_name):
    if grid_name == "icemod":
        return 't'
    expr = re.compile("(?i)(zoom|vert)?_sum$")
    result = re.search(expr, grid_name)
    if result is not None:
        return 't'
    expr = re.compile("(?i)grid_((T|U|V|W)_(2|3)D)|((T|U|V|W)$)")
    result = re.search(expr, grid_name)
    if not result:
        return None
    match = result.group(1)
    if match is None:
        match = result.group(0)
    result = match[0].lower()
    return 't' if result == 'w' else result


# Class holding a NEMO grid, including bounds arrays
class nemo_grid(object):

    def __init__(self, name_, lons_, lats_):
        self.name = name_
        flon = numpy.vectorize(lambda x: x % 360)
        flat = numpy.vectorize(lambda x: (x + 90) % 180 - 90)
        self.lons = flon(nemo_grid.smoothen(lons_))
        input_lats = lats_
        # Dirty hack for XIOS bug in zonal grid, yielding incorrect last latitude (see issue #669)
        if input_lats.shape[1] == 1:
            if input_lats.shape[0] > 2 and input_lats[-1, 0] <= input_lats[-2, 0]:
                input_lats[-1, 0] = input_lats[-2, 0] + (input_lats[-2, 0] - input_lats[-3, 0])
        self.lats = flat(input_lats)
        gridtype = get_grid_type(name_)
        if input_lats.shape[0] == 1 or input_lats.shape[1] == 1 or gridtype is None:
            # In the case of 1D horizontal case we keep the old method:
            log.info("Using fallback to the old midpoint calculation method for grid %s with shape %s" %
                     (self.name, input_lats.shape))
            self.vertex_lons = nemo_grid.create_vertex_lons(lons_)
            self.vertex_lats = nemo_grid.create_vertex_lats(input_lats)
        else:
            self.vertex_lons, self.vertex_lats = load_vertices_from_file(gridtype, input_lats.shape)
            if self.vertex_lons is None or self.vertex_lats is None:
                if test_mode_:
                    log.info("Using fallback to the old midpoint calculation method for grid %s with shape %s" %
                             (self.name, input_lats.shape))
                    self.vertex_lons = nemo_grid.create_vertex_lons(lons_)
                    self.vertex_lats = nemo_grid.create_vertex_lats(input_lats)
                else:
                    raise Exception("Vertices could not be loaded from ece2cmor3 nc files")

    @staticmethod
    def create_vertex_lons(a):
        ny = a.shape[0]
        nx = a.shape[1]
        f = numpy.vectorize(lambda x: x % 360)
        if nx == 1:  # Longitudes were integrated out
            if ny == 1:
                return f(numpy.array([a[0, 0]]))
            return numpy.zeros([ny, 2])
        b = numpy.zeros([ny, nx, 4])
        b[:, 1:nx, 0] = f(0.5 * (a[:, 0:nx - 1] + a[:, 1:nx]))
        b[:, 0, 0] = f(1.5 * a[:, 0] - 0.5 * a[:, 1])
        b[:, 0:nx - 1, 1] = b[:, 1:nx, 0]
        b[:, nx - 1, 1] = f(1.5 * a[:, nx - 1] - 0.5 * a[:, nx - 2])
        b[:, :, 2] = b[:, :, 1]
        b[:, :, 3] = b[:, :, 0]
        return b

    @staticmethod
    def create_vertex_lats(a):
        ny = a.shape[0]
        nx = a.shape[1]
        f = numpy.vectorize(lambda x: (x + 90) % 180 - 90)
        if nx == 1:  # Longitudes were integrated out
            if ny == 1:
                return f(numpy.array([a[0, 0]]))
            b = numpy.zeros([ny, 2])
            b[1:ny, 0] = f(0.5 * (a[0:ny - 1, 0] + a[1:ny, 0]))
            b[0, 0] = f(2 * a[0, 0] - b[1, 0])
            b[0:ny - 1, 1] = b[1:ny, 0]
            b[ny - 1, 1] = f(1.5 * a[ny - 1, 0] - 0.5 * a[ny - 2, 0])
            return b
        b = numpy.zeros([ny, nx, 4])
        b[1:ny, :, 0] = f(0.5 * (a[0:ny - 1, :] + a[1:ny, :]))
        b[0, :, 0] = f(2 * a[0, :] - b[1, :, 0])
        b[:, :, 1] = b[:, :, 0]
        b[0:ny - 1, :, 2] = b[1:ny, :, 0]
        b[ny - 1, :, 2] = f(1.5 * a[ny - 1, :] - 0.5 * a[ny - 2, :])
        b[:, :, 3] = b[:, :, 2]
        return b

    @staticmethod
    def modlon2(x, a):
        if x < a:
            return x + 360.0
        else:
            return x

    @staticmethod
    def smoothen(a):
        nx = a.shape[0]
        ny = a.shape[1]
        if ny == 1:
            return a
        mod = numpy.vectorize(nemo_grid.modlon2)
        b = numpy.empty([nx, ny])
        for i in range(0, nx):
            x = a[i, 1]
            b[i, 0] = a[i, 0]
            b[i, 1] = x
            b[i, 2:] = mod(a[i, 2:], x)
        return b
