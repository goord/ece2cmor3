from __future__ import division
from builtins import zip
from builtins import str
from builtins import range
from past.utils import old_div
import cmor
import glob
import logging
import multiprocessing
import netCDF4
import numpy
import os

from datetime import datetime, timedelta
from ece2cmor3 import grib_filter, cdoapi, cmor_source, cmor_target, cmor_task, cmor_utils, postproc

timeshift = timedelta(0)
# Apply timeshift for instance in case you want manually to add a shift for the piControl:
# timeshift = datetime(2260, 1, 1) - datetime(1850, 1, 1)

# Logger construction
log = logging.getLogger(__name__)

# Experiment name
exp_name_ = None

# Table root
table_root_ = None

# Files that are being processed in the current execution loop.
ifs_gridpoint_files_ = None
ifs_spectral_files_ = None
ifs_init_gridpoint_file_ = None
ifs_init_spectral_file_ = None

# IFS surface pressure grib codes
surface_pressure = cmor_source.grib_code(134)
ln_surface_pressure = cmor_source.grib_code(152)

# Start date of the processed data
start_date_ = None

# Fast storage temporary path
temp_dir_ = None

# Reference date, times will be converted to hours since refdate
ref_date_ = None

# Autofilter option
auto_filter_ = True

# Available geospatial masks, assigned by ece2cmorlib
masks = {}


# Controls whether we enter filtering+post-processing stage
def do_post_process():
    return str(os.environ.get("ECE2CMOR3_IFS_POSTPROC", "True")).lower() != "false"


# Controls whether we use 2d grid for IFS, or just lat/lon axes
def use_2d_grid():
    return str(os.environ.get("ECE2CMOR3_IFS_GRID_2D", "False")).lower() == "true"


# Controls whether to clean up the IFS temporary data
def cleanup_tmpdir():
    return str(os.environ.get("ECE2CMOR3_IFS_CLEANUP", "True")).lower() != "false"


# Guesses the IFS output frequency
def get_output_freq(task):
    # If the environment variable is set, we take that as our guess
    env_val = os.environ.get("ECE2CMOR3_IFS_NFRPOS", -1)
    try:
        env_val = int(env_val)
    except ValueError:
        log.error("Could not interpret environment variable ECE2CMOR3_IFS_NFRPOS with value %s as integer" %
                  str(env_val))
        env_val = -1
    if env_val >= 0:
        return env_val
    # If the output frequency was set (auto-filtering), take that one
    if hasattr(task, cmor_task.output_frequency_key):
        return getattr(task,  cmor_task.output_frequency_key)
    # Try to read from the raw model output
    if hasattr(task, cmor_task.filter_output_key):
        raise Exception("Cannot determine post-processing frequency for %s, please provide it by setting the "
                        "ECE2CMOR3_IFS_NFRPOS environment variable to the output frequency (in hours)" %
                        task.target.variable)
#        return grib_filter.read_source_frequency(getattr(task, cmor_task.filter_output_key))


# Initializes the processing loop.
def initialize(path, expname, tableroot, refdate, tempdir=None, autofilter=True):
    global log, exp_name_, table_root_, ifs_gridpoint_files_, ifs_spectral_files_, ifs_init_spectral_file_,\
        ifs_init_gridpoint_file_, temp_dir_, ref_date_, start_date_, auto_filter_

    exp_name_ = expname
    table_root_ = tableroot
    ref_date_ = refdate
    auto_filter_ = autofilter

    ifs_init_spectral_file_, ifs_init_gridpoint_file_ = find_init_files(path, expname)
    file_pattern = expname + "+[0-9][0-9][0-9][0-9][0-9][0-9]"
    gpfiles = {cmor_utils.get_ifs_date(f): os.path.join(path, f) for f in glob.glob1(path, "ICMGG" + file_pattern)
               if not f.endswith("+000000")}
    shfiles = {cmor_utils.get_ifs_date(f): os.path.join(path, f) for f in glob.glob1(path, "ICMSH" + file_pattern)
               if not f.endswith("+000000")}

    if any(shfiles) and any(gpfiles) and set(shfiles.keys()) != set(gpfiles.keys()):
        intersection = set(gpfiles.keys()).intersection(set(shfiles.keys()))
        if not any(intersection):
            log.error("Gridpoint files %s and spectral files %s correspond to different months, no overlap found..." %
                      (str(list(gpfiles.values())), str(list(shfiles.values()))))
            ifs_gridpoint_files_ = {}
            ifs_spectral_files_ = {}
            return False
        else:
            ifs_gridpoint_files_ = {date: gpfiles[date] for date in intersection}
            ifs_spectral_files_ = {date: shfiles[date] for date in intersection}
            log.warning("Gridpoint files %s and spectral files %s correspond to different months, found overlapping "
                        "dates %s" % (str(list(gpfiles.values())), str(list(shfiles.values())), str(intersection)))
    else:
        ifs_gridpoint_files_, ifs_spectral_files_ = gpfiles, shfiles
    if ifs_init_gridpoint_file_ is None:
        if any(ifs_gridpoint_files_.values()):
            ifs_init_gridpoint_file_ = list(ifs_gridpoint_files_.values())[0]
        else:
            log.error("No gridpoint files found for experiment %s in directory %s, exiting initialization" %
                      (exp_name_, path))
            return False

    tmpdir_parent = os.getcwd() if tempdir is None else tempdir
    # Apply timeshift
    start_date_ = datetime.combine(min(ifs_gridpoint_files_.keys()), datetime.min.time()) - timeshift
    dirname = '-'.join([exp_name_, "ifs", start_date_.isoformat().split('-')[0]])
    temp_dir_ = os.path.join(tmpdir_parent, dirname)
    if not os.path.exists(temp_dir_):
        os.makedirs(temp_dir_)
    if auto_filter_:
        ini_gpf = None if ifs_init_gridpoint_file_ == list(ifs_gridpoint_files_.values())[0] else ifs_init_gridpoint_file_
        grib_filter.initialize(ifs_gridpoint_files_, ifs_spectral_files_, temp_dir_, ini_gpfile=ini_gpf,
                               ini_shfile=ifs_init_spectral_file_)
    return True


def find_init_files(path, exp):
    def find_file(f):
        for root, dirs, files in os.walk(os.path.abspath(os.path.join(path, ".."))):
            if f in files:
                return os.path.join(root, f)
        return None
    return find_file("ICMSH" + exp + "+000000"), find_file("ICMGG" + exp + "+000000")


def execute(tasks, nthreads=1):
    global log, start_date_, auto_filter_

    supported_tasks = [t for t in filter_tasks(tasks) if t.status == cmor_task.status_initialized]
    log.info("Executing %d IFS tasks..." % len(supported_tasks))
    mask_tasks = get_mask_tasks(supported_tasks)
    fx_tasks = [t for t in supported_tasks if cmor_target.get_freq(t.target) == 0]
    surf_pressure_tasks = get_sp_tasks(supported_tasks)
    regular_tasks = [t for t in supported_tasks if t not in surf_pressure_tasks and cmor_target.get_freq(t.target) != 0]

    # No fx filtering needed, cdo can handle this file
    if ifs_init_gridpoint_file_.endswith("+000000"):
        tasks_to_filter = surf_pressure_tasks + regular_tasks
        tasks_no_filter = fx_tasks + mask_tasks
        for task in tasks_no_filter:
            # dirty hack for orography being in ICMGG+000000 file...
            if task.target.variable in ["orog", "areacella"]:
                task.source.grid_ = cmor_source.ifs_grid.point
            if task.source.grid_id() == cmor_source.ifs_grid.spec:
                setattr(task, cmor_task.filter_output_key, [ifs_init_spectral_file_])
            else:
                setattr(task, cmor_task.filter_output_key, [ifs_init_gridpoint_file_])
            setattr(task, cmor_task.output_frequency_key, 0)
    else:
        tasks_to_filter = mask_tasks + fx_tasks + surf_pressure_tasks + regular_tasks
        tasks_no_filter = []

    if auto_filter_:
        tasks_todo = tasks_no_filter + grib_filter.execute(tasks_to_filter, filter_files=do_post_process(),
                                                           multi_threaded=(nthreads > 1))
    else:
        tasks_todo = tasks_no_filter
        for task in tasks_to_filter:
            if task.source.grid_id() == cmor_source.ifs_grid.point:
                setattr(task, cmor_task.filter_output_key, list(ifs_gridpoint_files_.values()))
                tasks_todo.append(task)
            elif task.source.grid_id() == cmor_source.ifs_grid.spec:
                setattr(task, cmor_task.filter_output_key, list(ifs_spectral_files_.values()))
                tasks_todo.append(task)
            else:
                log.error("Task ifs source has unknown grid for %s in table %s" % (task.target.variable,
                                                                                   task.target.table))
                task.set_failed()

    for task in tasks_todo:
        setattr(task, cmor_task.output_frequency_key, get_output_freq(task))

    # First post-process surface pressure and mask tasks
    for task in list(set(tasks_todo).intersection(mask_tasks + surf_pressure_tasks)):
        postproc.post_process(task, temp_dir_, do_post_process())
    for task in list(set(tasks_todo).intersection(mask_tasks)):
        read_mask(task.target.variable, getattr(task, cmor_task.output_path_key))
    proctasks = list(set(tasks_todo).intersection(regular_tasks + fx_tasks))
    if nthreads == 1:
        for task in proctasks:
            cmor_worker(task)
    else:
        pool = multiprocessing.Pool(processes=nthreads)
        pool.map(cmor_worker, proctasks)
        for task in proctasks:
            setattr(task, cmor_task.output_path_key, postproc.get_output_path(task, temp_dir_))
    if cleanup_tmpdir():
        clean_tmp_data(tasks_todo)


# Worker function for parallel cmorization (not working at the present...)
def cmor_worker(task):
    log.info("Post-processing variable %s for target variable %s..." % (task.source.get_grib_code().var_id,
                                                                        task.target.variable))
    postproc.post_process(task, temp_dir_, do_post_process())
    if task.status == cmor_task.status_failed:
        return
    log.info("Cmorizing source variable %s to target variable %s..." % (task.source.get_grib_code().var_id,
                                                                        task.target.variable))
    define_cmor_axes(task)
    if task.status == cmor_task.status_failed:
        return
    execute_netcdf_task(task)


# Converts the masks that are needed into a set of tasks
def get_mask_tasks(tasks):
    global log, masks
    selected_masks = []
    for task in tasks:
        msk = getattr(task.target, cmor_target.mask_key, None)
        if msk:
            if msk not in masks:
                log.warning("Mask %s is not supported as an IFS mask, skipping masking" % msk)
                delattr(task.target, cmor_target.mask_key)
            else:
                selected_masks.append(msk)
            continue
        for area_operator in getattr(task.target, "area_operator", []):
            words = area_operator.split()
            if len(words) == 3 and words[1] == "where":
                mask_name = words[2]
                if mask_name not in masks:
                    log.warning("Mask %s is not supported as an IFS mask, skipping masking" % mask_name)
                else:
                    selected_masks.append(mask_name)
                    setattr(task.target, cmor_target.mask_key, mask_name)
    result = []
    for m in set(selected_masks):
        target = cmor_target.cmor_target(m, "fx")
        setattr(target, cmor_target.freq_key, "fx")
        setattr(target, "time_operator", ["point"])
        setattr(target, cmor_target.dims_key, "latitude longitude")
        result_task = cmor_task.cmor_task(masks[m]["source"], target)
        result.append(result_task)
    return result


# Reads the post-processed mask variable and converts it into a boolean array
def read_mask(name, filepath):
    global masks
    try:
        dataset = netCDF4.Dataset(filepath, 'r')
    except Exception as e:
        log.error("Could not read netcdf file %s while reading mask %s, reason: %s" % (filepath, name, e.message))
        return
    try:
        ncvars = dataset.variables
        codestr = str(masks[name]["source"].get_grib_code().var_id)
        varlist = [v for v in ncvars if str(getattr(ncvars[v], "code", None)) == codestr]
        if len(varlist) == 0:
            varlist = [v for v in ncvars if str(v) == "var" + codestr]
        if len(varlist) > 1:
            log.warning(
                "CDO variable retrieval resulted in multiple (%d) netcdf variables; will take first" % len(varlist))
        ncvar = ncvars[varlist[0]]
        if len(ncvar.shape) == 2:
            var = ncvar[:, :]
        elif len(ncvar.shape) == 3 and ncvar.shape[0] == 1:
            var = ncvar[0, :, :]
        elif len(ncvar.shape) == 4 and ncvar.shape[0] == 1 and ncvar.shape[1] == 1:
            var = ncvar[0, 0, :, :]
        else:
            log.error(
                "After processing, the shape of the mask variable is %s which cannot be applied to time slices" % str(
                    ncvar.shape))
            return
        f, v = masks[name]["operator"], masks[name]["rhs"]
        func = numpy.vectorize(lambda x: f(x, v))
        masks[name]["array"] = func(var[:, :])
    finally:
        dataset.close()


# Deletes all temporary paths and removes temp directory
def clean_tmp_data(tasks):
    global temp_dir_, ifs_gridpoint_files_, ifs_spectral_files_
    tmp_files = [str(os.path.join(temp_dir_, f)) for f in os.listdir(temp_dir_)]
    for task in tasks:
        for key in [cmor_task.filter_output_key, cmor_task.output_path_key]:
            data_path = getattr(task, key, None)
            if data_path is None:
                continue
            if isinstance(data_path, list):
                data_paths = data_path
            else:
                data_paths = [data_path]
            for dpath in data_paths:
                dp = str(dpath)
                if dp not in list(ifs_spectral_files_.values()) + list(ifs_gridpoint_files_.values()) and dp in tmp_files:
                    try:
                        os.remove(dp)
                    except OSError:
                        pass
    if not any(os.listdir(temp_dir_)):
        os.rmdir(temp_dir_)
        temp_dir_ = os.getcwd()
    else:
        log.warning("Skipped removal of nonempty work directory %s" % temp_dir_)


# Creates a sub-list of tasks that we believe we can successfully process
def filter_tasks(tasks):
    global log
    log.info("Inspecting %d tasks." % len(tasks))
    result = []
    for task in tasks:
        tgtdims = getattr(task.target, cmor_target.dims_key, "").split()
        haslat = "latitude" in tgtdims
        haslon = "longitude" in tgtdims
        # 2D horizontal variables, zonal means and global means
        if (haslat and haslon) or (haslat and not haslon) or (not haslat and not haslon):
            result.append(task)
        else:
            # TODO: Support zonal variables
            log.error("Variable %s has unsupported combination of dimensions %s and will be skipped." % (
                task.target.variable, tgtdims))
    log.info("Validated %d tasks for processing." % len(result))
    return result


# Creates extra tasks for surface pressure
def get_sp_tasks(tasks):
    tasks_by_freq = cmor_utils.group(tasks, lambda task: (task.target.frequency,
                                                          '_'.join(getattr(task.target, "time_operator", ["mean"]))))
    result = []
    for freq, task_group in tasks_by_freq.items():
        tasks3d = [t for t in task_group if "alevel" in getattr(t.target, cmor_target.dims_key).split()]
        if not any(tasks3d):
            continue
        surf_pressure_tasks = [t for t in task_group if t.source.get_grib_code() == surface_pressure]
        if len(surf_pressure_tasks) > 0:
            surf_pressure_task = surf_pressure_tasks[0]
            result.append(surf_pressure_task)
        else:
            source = cmor_source.ifs_source(surface_pressure)
            surf_pressure_task = cmor_task.cmor_task(source, cmor_target.cmor_target("sp", tasks3d[0].target.table))
            setattr(surf_pressure_task.target, cmor_target.freq_key, freq[0])
            setattr(surf_pressure_task.target, "time_operator", freq[1].split('_'))
            setattr(surf_pressure_task.target, cmor_target.dims_key, "latitude longitude")
            find_sp_variable(surf_pressure_task)
            result.append(surf_pressure_task)
        for task3d in tasks3d:
            setattr(task3d, "sp_task", surf_pressure_task)
    return result


# Finds the surface pressure data source: gives priority to SH file.
def find_sp_variable(task):
    global ifs_gridpoint_files_, ifs_spectral_files_, surface_pressure, ln_surface_pressure, auto_filter_
    ifs_ps_source = cmor_source.ifs_source.create(134)
    setattr(ifs_ps_source, cmor_source.expression_key, "var134=exp(var152)")
    setattr(ifs_ps_source, "root_codes", [cmor_source.grib_code(134)])
    if auto_filter_:
        if grib_filter.spvar is None:
            log.error("Could not find surface pressure in model output...")
            return
        log.info("Found surface pressure in file %s" % grib_filter.spvar[2])
        setattr(task, cmor_task.filter_output_key, [grib_filter.spvar[2]])
        if grib_filter.spvar[0] == 152:
            task.source = ifs_ps_source
        task.source.grid_ = 1 if grib_filter.spvar[2] == ifs_spectral_files_ else 0
        return
    log.info("Looking for surface pressure variable in input files...")
    command = cdoapi.cdo_command()
    code_string = command.show_code(list(ifs_spectral_files_.values())[0])
    codes = [cmor_source.grib_code(int(c)) for c in code_string[0].split()]
    if surface_pressure in codes:
        log.info("Found surface pressure in spectral files")
        setattr(task, cmor_task.filter_output_key, list(ifs_spectral_files_.values()))
        task.source.grid_ = 1
        return
    if ln_surface_pressure in codes:
        log.info("Found lnsp in spectral file")
        setattr(task, cmor_task.filter_output_key, list(ifs_spectral_files_.values()))
        task.source = ifs_ps_source
        return
    log.info("Did not find sp or lnsp in spectral file: assuming gridpoint file contains sp")
    setattr(task, cmor_task.filter_output_key, list(ifs_gridpoint_files_.values()))
    task.source.grid_ = 0


global_grid_id = -1
local_grid_ids = {}
time_axis_ids = {}
time_axis_bnds = {}
depth_axis_ids = {}


def define_cmor_axes(task):
    global global_grid_id, local_grid_ids
    if task.status in [cmor_task.status_failed, cmor_task.status_cmorized]:
        return
    tgtdims = getattr(task.target, cmor_target.dims_key).split()
    grid_id = -1
    has_lats, has_lons = "latitude" in tgtdims, "longitude" in tgtdims
    if use_2d_grid() and has_lats and has_lons:
        if global_grid_id == -1:
            cmor.load_table(table_root_ + "_grids.json")
            global_grid_id = create_grid_from_file(getattr(task, cmor_task.output_path_key))
        grid_id = global_grid_id
    else:
        grid_ids = local_grid_ids.get(task.target.table, None)
        if grid_ids is None or (has_lons and grid_ids[0] is None) or (has_lats and grid_ids[1] is None):
            cmor.load_table("_".join([table_root_, task.target.table]) + ".json")
            grid_ids = create_grid_from_file(getattr(task, cmor_task.output_path_key))
            local_grid_ids[task.target.table] = grid_ids
        if has_lons:
            if has_lats:
                grid_id = grid_ids
            else:
                grid_id = grid_ids[1]
        else:
            if has_lats:
                grid_id = grid_ids[0]
    setattr(task, "grid_id", grid_id)
    log.info("Loading CMOR table %s..." % task.target.table)
    try:
        tab_id = cmor.load_table("_".join([table_root_, task.target.table]) + ".json")
        cmor.set_table(tab_id)
    except Exception as e:
        log.error("CMOR failed to load table %s, the following variable will be skipped: %s. Reason: %s" % (
            task.target.table, task.target.variable, e.message))
        task.set_failed()
        return
    create_time_axes(task)
    if task.status == cmor_task.status_failed:
        return
    create_depth_axes(task)


# Executes a single task
def execute_netcdf_task(task):
    global log
    task.next_state()
    filepath = getattr(task, cmor_task.output_path_key, None)
    if not filepath:
        log.error(
            "Could not find file containing data for variable %s in table %s" % (task.target.variable,
                                                                                 task.target.table))
        return
    store_var = getattr(task, "store_with", None)
    surf_pressure_task = getattr(task, "sp_task", None)
    surf_pressure_path = getattr(surf_pressure_task, "path", None) if surf_pressure_task else None
    if store_var and not surf_pressure_path:
        log.error(
            "Could not find file containing surface pressure for model level variable...skipping variable %s in table "
            "%s" % (task.target.variable, task.target.table))
        return
    axes = []
    t_bnds = []
    if hasattr(task, "grid_id"):
        task_grid_id = getattr(task, "grid_id")
        if isinstance(task_grid_id, tuple):
            axes.extend([a for a in task_grid_id if a is not None])
        else:
            axes.append(task_grid_id)
    if hasattr(task, "z_axis_id"):
        axes.append(getattr(task, "z_axis_id"))
    if hasattr(task, "t_axis_id"):
        axes.append(getattr(task, "t_axis_id"))
        t_bnds = time_axis_bnds.get(getattr(task, "t_axis_id"), [])
    try:
        dataset = netCDF4.Dataset(filepath, 'r')
    except Exception as e:
        log.error("Could not read netcdf file %s while cmorizing variable %s in table %s. Cause: %s" % (
            filepath, task.target.variable, task.target.table, e.message))
        return
    try:
        ncvars = dataset.variables
        dataset.set_auto_mask(False)
        codestr = str(task.source.get_grib_code().var_id)
        varlist = [v for v in ncvars if str(getattr(ncvars[v], "code", None)) == codestr]
        if len(varlist) == 0:
            varlist = [v for v in ncvars if str(v) == "var" + codestr]
        if task.target.variable == "areacella":
            varlist = ["cell_area"]
        if len(varlist) == 0:
            log.error("No suitable variable found in cdo-produced file %s fro cmorizing variable %s in table %s... "
                      "dismissing task" % (filepath, task.target.variable, task.target.table))
            task.set_failed()
            return
        if len(varlist) > 1:
            log.warning(
                "CDO variable retrieval resulted in multiple (%d) netcdf variables; will take first" % len(varlist))
        ncvar = ncvars[varlist[0]]
        unit = getattr(ncvar, "units", None)
        if (not unit) or hasattr(task, cmor_task.conversion_key):
            unit = getattr(task.target, "units")
        if len(getattr(task.target, "positive", "")) > 0:
            var_id = cmor.variable(table_entry=str(task.target.variable), units=str(unit), axis_ids=axes,
                                    positive="up" if getattr(task, cmor_task.conversion_key, None) == "vol2fluxup" else "down")
        else:
            var_id = cmor.variable(table_entry=str(task.target.variable), units=str(unit), axis_ids=axes)
        flip_sign = (getattr(task.target, "positive", None) == "up")
        factor, term = get_conversion_constants(getattr(task, cmor_task.conversion_key, None),
                                                getattr(task, cmor_task.output_frequency_key))
        time_dim, index = -1, 0
        for d in ncvar.dimensions:
            if d.startswith("time"):
                time_dim = index
                break
            index += 1

        time_selection = None
        time_stamps = cmor_utils.read_time_stamps(filepath)
        if any(time_stamps) and len(t_bnds) > 0:
            time_slice_map = []
            for bnd in t_bnds:
                candidates = [t for t in time_stamps if bnd[0] <= t <= bnd[1]]
                if any(candidates):
                    time_slice_map.append(time_stamps.index(candidates[0]))
                else:
                    log.warning("For variable %s in table %s, no valid time point could be found at %s...inserting "
                                "missing values" % (task.target.variable, task.target.table, str(bnd[0])))
                    time_slice_map.append(-1)
            time_selection = numpy.array(time_slice_map)

        mask = getattr(task.target, cmor_target.mask_key, None)
        mask_array = masks[mask].get("array", None) if mask in masks else None
        missval = getattr(task.target, cmor_target.missval_key, 1.e+20)
        if flip_sign:
            missval = -missval
        cmor_utils.netcdf2cmor(var_id, ncvar, time_dim, factor, term, store_var, get_sp_var(surf_pressure_path),
                               swaplatlon=False, fliplat=True, mask=mask_array, missval=missval,
                               time_selection=time_selection, force_fx=(cmor_target.get_freq(task.target) == 0))
        cmor.close(var_id)
        task.next_state()
        if store_var:
            cmor.close(store_var)
    finally:
        dataset.close()


# Returns the constants A,B for unit conversions of type y = A*x + B
def get_conversion_constants(conversion, output_frequency):
    global log
    if not conversion:
        return 1.0, 0.0
    if conversion == "cum2inst":
        return 1.0 / (3600 * output_frequency), 0.0
    if conversion == "inst2cum":
        return 3600 * output_frequency, 0.0
    if conversion == "pot2alt":
        return 1.0 / 9.81, 0.0
    if conversion == "alt2pot":
        return 9.807, 0.0
    if conversion == "vol2flux":
        return 1000.0 / (3600 * output_frequency), 0.0
    if conversion == "vol2fluxup":
        return old_div(- 1000.0, (3600 * output_frequency)), 0.0
    if conversion == "vol2massl":
        return 1000.0, 0.0
    if conversion == "frac2percent":
        return 100.0, 0.0
    if conversion == "percent2frac":
        return 0.01, 0.0
    if conversion == "K2degC":
        return 1.0, -273.15
    if conversion == "degC2K":
        return 1.0, 273.15
    log.error("Unknown explicit unit conversion: %s" % conversion)
    return 1.0, 0.0


# Creates time axes in cmor and attach the id's as attributes to the tasks
def create_time_axes(task):
    global log, time_axis_ids, time_axis_bnds
    tgtdims = getattr(task.target, cmor_target.dims_key)
    # TODO: better to check in the table axes if the standard name of the dimension equals "time"
    time_dims = [d for d in list(set(tgtdims.split())) if d.startswith("time")]
    if not any(time_dims):
        return
    if len(time_dims) > 1:
        log.error("Skipping variable %s in table %s with dimensions %s with multiple time dimensions." % (
            task.target.variable, task.target.table, tgtdims))
        task.set_failed()
        return
    time_dim = str(time_dims[0])
    key = (task.target.table, time_dim)
    if key in time_axis_ids:
        tid = time_axis_ids[key]
    else:
        time_operator = getattr(task.target, "time_operator", ["mean"])
        log.info("Creating time axis using variable %s..." % task.target.variable)
        tid, tlow, tup = create_time_axis(freq=task.target.frequency, path=getattr(task, cmor_task.output_path_key),
                                          name=time_dim, has_bounds=(time_operator != ["point"]))
        time_axis_ids[key] = tid
        time_axis_bnds[tid] = list(zip(tlow, tup))
    setattr(task, "t_axis_id", tid)


# Creates depth axes in cmor and attach the id's as attributes to the tasks
def create_depth_axes(task):
    global log, depth_axis_ids
    tgtdims = getattr(task.target, cmor_target.dims_key)
    z_dims = getattr(task.target, "z_dims", [])
    if not any(z_dims):
        return
    if len(z_dims) > 1:
        log.error("Skipping variable %s in table %s with dimensions %s with multiple z-directions." % (
            task.target.variable, task.target.table, tgtdims))
        task.set_failed()
        return
    z_dim = str(z_dims[0])
    key = (task.target.table, z_dim)
    if key in depth_axis_ids:
        if z_dim == "alevel":
            setattr(task, "z_axis_id", depth_axis_ids[key][0])
            setattr(task, "store_with", depth_axis_ids[key][1])
        else:
            setattr(task, "z_axis_id", depth_axis_ids[key])
        return
    elif z_dim == "alevel":
        log.info("Creating model level axis using variable %s..." % task.target.variable)
        axisid, psid = create_hybrid_level_axis(task)
        depth_axis_ids[key] = (axisid, psid)
        setattr(task, "z_axis_id", axisid)
        setattr(task, "store_with", psid)
        return
    elif z_dim == "sdepth":
        log.info("Creating soil depth axis using variable %s..." % task.target.variable)
        axisid = create_soil_depth_axis(z_dim)
        depth_axis_ids[key] = axisid
        setattr(task, "z_axis_id", axisid)
    elif z_dim == "sdepth1":
        log.info("Creating soil depth axis 1 using variable %s..." % task.target.variable)
        axisid = create_soil_depth_axis(z_dim)
        depth_axis_ids[key] = axisid
        setattr(task, "z_axis_id", axisid)
    elif z_dim in cmor_target.get_axis_info(task.target.table):
        axis = cmor_target.get_axis_info(task.target.table)[z_dim]
        levels = axis.get("requested", [])
        if levels == "":
            levels = []
        value = axis.get("value", None)
        if value:
            levels.append(value)
        unit = axis.get("units", None)
        if len(levels) == 0:
            log.warning("Skipping axis %s in table %s with no levels" % (z_dim, task.target.table))
            return
        else:
            values = [float(l) for l in levels]
            if axis.get("must_have_bounds", "no") == "yes":
                bounds_list, n = axis.get("requested_bounds", []), len(values)
                if not bounds_list:
                    bounds_list = [float(x) for x in axis.get("bounds_values", []).split()]
                if len(bounds_list) == 2 * n:
                    bounds_array = numpy.empty([n, 2])
                    for i in range(n):
                        bounds_array[i, 0], bounds_array[i, 1] = bounds_list[2 * i], bounds_list[2 * i + 1]
                    axisid = cmor.axis(table_entry=str(z_dim), coord_vals=values, units=unit,
                                       cell_bounds=bounds_array)
                else:
                    log.error("Failed to retrieve bounds for vertical axis %s" % str(z_dim))
                    axisid = cmor.axis(table_entry=str(z_dim), coord_vals=values, units=unit)
            else:
                axisid = cmor.axis(table_entry=str(z_dim), coord_vals=values, units=unit)
            depth_axis_ids[key] = axisid
            setattr(task, "z_axis_id", axisid)
    else:
        log.error("Vertical dimension %s for variable %s not found in header of table %s" % (
            z_dim, task.target.variable, task.target.table))


# Creates the hybrid model vertical axis in cmor.
def create_hybrid_level_axis(task):
    pref = 80000  # TODO: Move reference pressure level to model config
    path = getattr(task, cmor_task.output_path_key)
    ds = None
    try:
        ds = netCDF4.Dataset(path)
        am = ds.variables["hyam"]
        aunit = getattr(am, "units")
        bm = ds.variables["hybm"]
        bunit = getattr(bm, "units")
        hcm = old_div(am[:], pref) + bm[:]
        n = hcm.shape[0]
        ai = ds.variables["hyai"]
        abnds = numpy.empty([n, 2])
        abnds[:, 0] = ai[0:n]
        abnds[:, 1] = ai[1:n + 1]
        bi = ds.variables["hybi"]
        bbnds = numpy.empty([n, 2])
        bbnds[:, 0] = bi[0:n]
        bbnds[:, 1] = bi[1:n + 1]
        hcbnds = old_div(abnds, pref) + bbnds
        axisid = cmor.axis(table_entry="alternate_hybrid_sigma", coord_vals=hcm, cell_bounds=hcbnds, units="1")
        cmor.zfactor(zaxis_id=axisid, zfactor_name="ap", units=str(aunit), axis_ids=[axisid], zfactor_values=am[:],
                     zfactor_bounds=abnds)
        cmor.zfactor(zaxis_id=axisid, zfactor_name="b", units=str(bunit), axis_ids=[axisid], zfactor_values=bm[:],
                     zfactor_bounds=bbnds)
        axes = []
        if hasattr(task, "grid_id"):
            task_grid_id = getattr(task, "grid_id")
            if isinstance(task_grid_id, tuple):
                axes.extend(task_grid_id)
            else:
                axes.append(task_grid_id)
        axes.append(getattr(task, "t_axis_id"))
        zfactor_name = "ps"
        if "time1" in getattr(task.target, cmor_target.dims_key, []):
            zfactor_name = "ps1"
        elif "time2" in getattr(task.target, cmor_target.dims_key, []):
            zfactor_name = "ps2"
        storewith = cmor.zfactor(zaxis_id=axisid, zfactor_name=zfactor_name, axis_ids=axes, units="Pa")
        return axisid, storewith
    finally:
        if ds is not None:
            ds.close()


# Creates a soil depth axis.
def create_soil_depth_axis(name):
    global log
    if name == "sdepth1":
        return cmor.axis(table_entry=name, coord_vals=[0.05], cell_bounds=[0.0, 0.1], units="m")
    # Hard-coded because cdo fails to pass soil depths correctly:
    bndcm = numpy.array([0, 7, 28, 100, 289])
    values = 0.5 * (bndcm[:4] + bndcm[1:])
    bounds = numpy.transpose(numpy.stack([bndcm[:4], bndcm[1:]]))
    return cmor.axis(table_entry=name, coord_vals=values, cell_bounds=bounds, units="cm")


# Makes a time axis for the given table
def create_time_axis(freq, path, name, has_bounds):
    global log, start_date_, ref_date_
    date_times = cmor_utils.read_time_stamps(path)
    if len(date_times) == 0:
        log.error("Empty time step list encountered at time axis creation for files %s" % str(path))
        return 0, [], []
    if has_bounds:
        bounds = numpy.empty([len(date_times), 2])
        rounded_times = [(cmor_utils.get_rounded_time(freq, time)) for time in date_times]
        dt_low = rounded_times
        dt_up = rounded_times[1:] + [cmor_utils.get_rounded_time(freq, date_times[-1], 1)]
        bounds[:, 0], units = cmor_utils.date2num([t - timeshift for t in dt_low], ref_date_)
        bounds[:, 1], units = cmor_utils.date2num([t - timeshift for t in dt_up], ref_date_)
        times = bounds[:, 0] + old_div((bounds[:, 1] - bounds[:, 0]), 2)
        return cmor.axis(table_entry=str(name), units=units, coord_vals=times, cell_bounds=bounds), dt_low, dt_up
    step = cmor_utils.make_cmor_frequency(freq)
    if date_times[0] >= start_date_ + step:
        date = date_times[0]
        extra_dates = []
        while date > start_date_:
            date = date - step
            extra_dates.append(date)
        log.warning("The file %s seems to be missing %d time stamps at the beginning, these will be added" %
                    (path, len(extra_dates)))
        date_times = extra_dates[::-1] + date_times
    if date_times[0] < start_date_:
        date_times = [t for t in date_times if t >= start_date_]
        log.warning("The file %s seems to be containing %d too many time stamps at the beginning, these will be "
                    "removed" % (path, len([t for t in date_times if t >= start_date_])))
    times, units = cmor_utils.date2num([t - timeshift for t in date_times], ref_date_)
    return cmor.axis(table_entry=str(name), units=units, coord_vals=times), date_times, date_times


# Surface pressure variable lookup utility
def get_sp_var(ncpath):
    if not ncpath:
        return None
    if not os.path.exists(ncpath):
        return None
    try:
        ds = netCDF4.Dataset(ncpath)
        if "var134" in ds.variables:
            return ds.variables["var134"]
        for v in ds.variables:
            if getattr(v, "code", 0) == 134:
                return v
        return None
    except Exception as e:
        log.error("Could not read netcdf file %s for surface pressure, reason: %s" % (ncpath, e.message))
        return None


# Creates the regular gaussian grids from the postprocessed file argument.
def create_grid_from_file(filepath):
    global log
    command = cdoapi.cdo_command()
    grid_descr = command.get_grid_descr(filepath)
    gridtype = grid_descr.get("gridtype", "unknown")
    if gridtype != "gaussian":
        log.error("Cannot read other grids then regular gaussian grids, current grid type read from file %s was % s" % (
            filepath, gridtype))
        return None
    xvals = read_coordinate_vals(grid_descr, 'x', 360)
    yvals = read_coordinate_vals(grid_descr, 'y', 180)
    if xvals is None or yvals is None:
        log.error("Invalid grid detected in post-processed data: %s" % str(grid_descr))
        return None
    return create_gauss_grid(xvals, yvals)


def read_coordinate_vals(grid_descr, xydir, ndegrees):
    att_vals = xydir + "vals"
    if att_vals in grid_descr:
        return grid_descr[att_vals]
    att_first, att_size = xydir + "first", xydir + "size"
    if att_first in grid_descr and att_first in grid_descr:
        x0, n = float(grid_descr[att_first]), int(grid_descr[att_size])
        dx = float(ndegrees) / n
        return numpy.array([x0 + i * dx for i in range(n)])
    log.error("Could not retrieve %s-coordinate values from %s" % (xydir, str(grid_descr)))
    return None


# Creates the regular gaussian grid from its arguments.
def create_gauss_grid(xvals, yvals):
    nx, ny = len(xvals), len(yvals)
    if use_2d_grid() and nx > 1 and ny > 1:
        lon_mids, lat_mids = get_lon_mids(xvals), get_lat_mids(yvals)
        vert_lats = numpy.empty([ny, nx, 4])
        vert_lats[:, :, 0] = numpy.tile(lat_mids[0:ny], (nx, 1)).transpose()
        vert_lats[:, :, 1] = vert_lats[:, :, 0]
        vert_lats[:, :, 2] = numpy.tile(lat_mids[1:ny + 1], (nx, 1)).transpose()
        vert_lats[:, :, 3] = vert_lats[:, :, 2]
        vert_lons = numpy.empty([ny, nx, 4])
        vert_lons[:, :, 0] = numpy.tile(lon_mids[0:nx], (ny, 1))
        vert_lons[:, :, 3] = vert_lons[:, :, 0]
        vert_lons[:, :, 1] = numpy.tile(lon_mids[1:nx + 1], (ny, 1))
        vert_lons[:, :, 2] = vert_lons[:, :, 1]
        i_index_id = cmor.axis(table_entry="i_index", units="1", coord_vals=numpy.array(list(range(1, nx + 1))))
        j_index_id = cmor.axis(table_entry="j_index", units="1", coord_vals=numpy.array(list(range(1, ny + 1))))
        lon_arr = numpy.tile(xvals, (ny, 1))
        lat_arr = numpy.tile(yvals[::-1], (nx, 1)).transpose()
        return cmor.grid(axis_ids=[j_index_id, i_index_id], latitude=lat_arr, longitude=lon_arr,
                         latitude_vertices=vert_lats, longitude_vertices=vert_lons)
    else:
        lats = cmor.axis(table_entry="latitude", coord_vals=yvals[::-1], cell_bounds=get_lat_mids(yvals)[::-1],
                         units="degrees_north") if (ny > 1) else None
        lons = cmor.axis(table_entry="longitude", coord_vals=xvals, cell_bounds=get_lon_mids(xvals),
                         units="degrees_east") if (nx > 1) else None
        return lats, lons


def get_lon_mids(xvals):
    nx = len(xvals)
    if nx < 2:
        return None
    lon_mids = numpy.empty([nx + 1])
    lon_mids[0] = xvals[0] - 0.5 * (xvals[1] - xvals[0])
    lon_mids[1:nx] = 0.5 * (xvals[0:nx - 1] + xvals[1:nx])
    lon_mids[nx] = lon_mids[0] % 360.
    return lon_mids


def get_lat_mids(yvals):
    ny = len(yvals)
    if ny < 2:
        return None
    lat_mids = numpy.empty([ny + 1])
    lat_mids[0] = 90.
    lat_mids[1:ny] = 0.5 * (yvals[0:ny - 1] + yvals[1:ny])
    lat_mids[ny] = -90.
    return lat_mids
