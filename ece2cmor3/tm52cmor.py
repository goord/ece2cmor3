import datetime
import json
import logging
import os
import warnings

import Ngl
import cmor
import netCDF4
import numpy

from ece2cmor3 import cmor_source, cmor_target, cmor_task, cmor_utils

# Logger object
log = logging.getLogger(__name__)

# Experiment name
exp_name_ = None

# Table root
table_root_ = None

# Files that are being processed in the current execution loop.
tm5_files_ = []

# Dictionary of tm5 grid type with cmor grid id.
dim_ids_ = {}

# List of depth axis ids with cmor grid id.
depth_axes_ = {}

# Dictionary of output frequencies with cmor time axis id.
time_axes_ = {}

# Dictionary of sea-ice output types, 1 by default...
type_axes_ = {}

ps_tasks = {}

time_axis_ids = {}
type_axis_ids = {}
depth_axis_ids = {}
zfactor_ids = {}

# Reference date, times will be converted to hours since refdate
ref_date_ = None

unit_miss_match = []
failed = []

areacella_ = 0

# Default pressure levels if not provided (Pa)
plev19_ = numpy.array(
    [100000., 92500., 85000., 70000., 60000., 50000., 40000., 30000., 25000., 20000., 15000., 10000., 7000., 5000.,
     3000., 2000., 1000., 500., 100.])
plev39_ = numpy.array([100000., 92500., 85000., 70000., 60000., 50000., 40000.,
                       30000., 25000., 20000., 17000., 15000., 13000., 11500.,
                       10000., 9000., 8000., 7000., 5000., 3000., 2000.,
                       1500., 1000., 700., 500., 300., 200., 150.,
                       100., 70., 50., 40., 30., 20., 15.,
                       10., 7., 5., 3.])

extra_axes = {"lambda550nm": {"ncdim": "lambda550nm",
                              "ncunits": "nm",
                              "ncvals": [550.0]}}

#
ignore_frequency = ['subhrPt', '3hrPt']
ps6hrpath_ = None
# using_grid_=False
path_ = None


# Initializes the processing loop.
def initialize(path, expname, tabledir, prefix, refdate):
    """initialize the cmorization for TM5
    Description:
        
    Input variables:
        path, String: path to TM5 files
        expname, string: name of the experiment
        tabledir, string: path to tables
        prefix, string: table prefix
    Returns:
        boolean: success
    """
    global log, tm5_files_, exp_name_, table_root_, ref_date_, plev39_, plev19_, areacella_, path_
    exp_name_ = expname
    path_ = path
    table_root_ = os.path.join(tabledir, prefix)
    # select all TM5 files with expname from path
    tm5_files_ = cmor_utils.find_tm5_output(path, expname)
    if len(tm5_files_) == 0:
        log.error('no TM5 varibles found, exiting!')
        exit()
    areacella_file = cmor_utils.find_tm5_output(path, expname, 'areacella', 'fx')
    if len(areacella_file) == 0:
        log.error('Areacella not found!')
        exit()
    else:
        areacella_ = netCDF4.Dataset(areacella_file[0], 'r').variables['areacella'][:]
    cal = None
    ref_date_ = refdate

    # read pressure level definitions from CMIP6_coordante file
    # and save globally
    coordfile = os.path.join(tabledir, prefix + "_coordinate.json")
    if os.path.exists(coordfile):
        with open(coordfile) as f:
            data = json.loads(f.read())
        axis_entries = data.get("axis_entry", {})
        axis_entries = {k.lower(): v for k, v in axis_entries.iteritems()}
        plev19 = numpy.array([numpy.float(value) for value in axis_entries['plev19']['requested']])
        plev19_ = plev19
        plev39 = numpy.array([numpy.float(value) for value in axis_entries['plev39']['requested']])
        plev39_ = plev39
    else:
        log.warning('Using default pressure level definitions')

    cmor.load_table(table_root_ + "_grids.json")
    return True


# Resets the module globals.
def finalize():
    """finalize, clear variables
    Args:
        none
    Retruns:
        none
    """
    global tm5_files_, dim_ids_, depth_axes_, time_axes_, plev19_, plev39_
    log.info('Unit miss match variables %s ' % unit_miss_match)
    tm5_files_ = []
    dim_ids_ = {}
    depth_axes_ = {}
    time_axes_ = {}
    plev39_ = []
    plev19_ = []


def set_freqid(freq):
    """set freqid for filenames
    Args:
        freq (string): set freqid depending on the table frequency
    Returns:
        freqid (string): Freqid for AERchemMIP data
    """
    if freq == 'monC':
        freqid = 'AERmon'
    elif freq == '1hr':
        freqid = 'AERhr'
    elif freq == 'day':
        freqid = 'AERday'
    elif freq == '6hrPt':
        freqid = 'AER6hr'
    elif freq == 'mon':
        freqid = 'AERmon'
    else:
        log.error('unknown frequency %s' % freq)
        return None
    return freqid


def check_freqid(task):
    """ Check if we freqid will be cmorized and fix teh freqid for special cases
    Args:
        task (cmor.task): task for which we are checking
    Returns:
        boolean: True if task will be cmorized
        freqid (string): name of frequency in files 
    """
    global log
    freqid = set_freqid(task.target.frequency)
    if task.target.frequency == 'monC':
        if task.target.table == 'Amon' and (task.target.variable == 'pfull' or task.target.variable == 'phalf'):
            task.set_failed()
            log.info('Variable %s in table %s will be produced by IFS' % (task.target.variable, task.target.table))
            return False, None
    elif task.target.frequency in ignore_frequency:
        log.info('frequency %s ignored, no data prduced at this frequency' % task.target.frequency)
        # continue
        return False, None
    elif task.target.table == 'AERmonZ':
        freqid = freqid + 'Z'
    elif freqid is None:
        log.error('Frequency %s of variable %s is unkonwn' % (task.target.frequency, task.target.variable))
        return False, None
    return True, freqid


# Executes the processing loop.
def execute(tasks):
    """execute the cmorization tasks for TM5
    Description:
        
    Args:
        tasks (list): list of tasks 
    Returns:
        boolean: success
    """
    global log, time_axes_, depth_axes_, table_root_, tm5_files_, areacella_, using_grid_, ps_tasks
    log.info("Executing %d tm5 tasks..." % len(tasks))
    log.info("Cmorizing tm5 tasks...")
    # Assign file to each task
    for task in tasks:
        setattr(task, cmor_task.output_path_key, None)
        if task.target.frequency == 'fx':
            log.info('fx frequency has no variables from TM5')
            task.set_failed()
            continue
        elif task.target.frequency == 'monC':
            if 'Clim' in task.target.variable:
                log.info('Variable %s in table %s is climatological variable and thus not available in TM5.' % (
                task.target.variable, task.target.table))
                task.set_failed()
                continue
            elif task.target.table == 'Amon' and (task.target.variable == 'pfull' or task.target.variable == 'phalf'):
                task.set_failed()
                log.info('Variable %s in table %s will be produced by IFS' % (task.target.variable, task.target.table))
                continue
        elif task.target.frequency in ignore_frequency:
            log.info('frequency %s ignored, no data prduced at this frequency' % task.target.frequency)
            continue
        elif 'Clim' in task.target.variable:
            log.infor("Climatological variables not supported")
            task.set_failed()
            continue

        success, freqid = check_freqid(task)
        if not success:
            task.set_failed()
            log.info('Frequency %s for task %s not available.'(task.target.frequency, task.target.variable))
            continue
        for fstr in tm5_files_:
            # only select files which start with variable name and have _ behind (e.g. o3 .neq. o3loss)
            # and freqid has _ behing (e.g. monZ .neq. mon)

            # catch variablename + '_' to prevent o3 and o3loss mixing up...
            if os.path.basename(fstr).startswith(task.source.variable() + "_") and freqid + '_' in fstr:
                fname = fstr
                if getattr(task, cmor_task.output_path_key) is None:
                    setattr(task, cmor_task.output_path_key, fstr)
                else:
                    log.critical(
                        'Second file with same frequency and name. Currently supporting only one year per directory.')
                    log.critical(fstr)
                    exit(' Exiting ece2cmor.')
            if not os.path.exists(fstr):
                log.info('No path found for variable %s from TM5' % task.target.variable)
                task.set_failed()
                continue
    ps_tasks = get_ps_tasks(tasks)

    # group the taks according to table
    taskdict = cmor_utils.group(tasks, lambda t: t.target.table)
    for table, tasklist in taskdict.iteritems():
        try:
            log.info("Loading CMOR table %s to process %d variables..." % (table, len(tasklist)))
            tab_id = cmor.load_table("_".join([table_root_, table]) + ".json")
            cmor.set_table(tab_id)
        except Exception as e:
            log.error("ERR -6: CMOR failed to load table %s, skipping variables %s. Reason: %s"
                      % (table, ','.join([tsk.target.variable for tsk in tasklist]), e.message))
            continue
        #     #postprocess data to zonal mean and plev39, or do it before this point
        if table == '3hr':
            for task in tasklist:
                task.set_failed()
            log.error("Table %s will not be implemented for TM5" % table)
            log.error("ERR -6: Skipping variable %s not implemented" % task.target.variable)
            continue
            # postprocess data to zonal mean and plev39, or do it before this point
        if table == 'Eday':
            log.info("Table Eday not supported for variable %s " % task.target.variable)
        log.info("Creating longitude and latitude axes for table %s..." % table)
        dim_ids_['lat'] = create_lat()
        dim_ids_['lon'] = create_lon()
        # create or assign time axes to tasks
        log.info("Creating time axes for table %s..." % table)
        # create_time_axes(tasklist)
        time_axes_ = create_time_axes(tasklist)  # time_axes

        taskmask = dict([t, False] for t in tasklist)
        for task in tasklist:
            # define task properties
            # 2D grid
            if task.target.variable == 'ch4Clim' or task.target.variable == 'ch4globalClim' or task.target.variable == 'o3Clim':
                log.error(
                    'ERR -8: Task for %s is not produced in any of the simulations with TM5.' % task.target.variable)
                task.set_failed()
                continue

            ncf = getattr(task, cmor_task.output_path_key)
            tgtdims = getattr(task.target, cmor_target.dims_key).split()
            if "latitude" in tgtdims and "longitude" in tgtdims:
                setattr(task, 'lon', dim_ids_['lon'])
                setattr(task, 'lat', dim_ids_['lat'])
            # ZONAL
            if "latitude" in tgtdims and not "longitude" in tgtdims:
                setattr(task, "zonal", True)
            if "site" in tgtdims:
                log.critical('Z-dimension site not implemented ')
                task.set_failed()
                continue
            if task.status == cmor_task.status_failed:
                continue
            create_depth_axes(task)
            if 'lambda550nm' in tgtdims:
                success = create_type_axes(task)
                if not success:
                    log.error('Lambda 550nm could not be created, setting task failed')
                    task.set_failed()
                    continue
            if taskmask[task]:
                log.warning("Ignoring source variable in nc file %s, since it has already been cmorized." % ncf)
            else:
                if task.status not in [cmor_task.status_failed]:
                    log.info("Cmorizing source variable %s to target variable %s from file %s." % (
                    task.source.variable(), task.target.variable, ncf))
                    execute_netcdf_task(task, tab_id)
                    if task.status < 0:
                        if task.target.variable == 'cdnc':
                            log.error(
                                "ERR -10: Cmorizing failed for %s, but variable is produced by IFS." % task.target.variable)
                        elif task.target.variable == 'o3Clim':
                            log.error(
                                "ERR -11: Cmorizing failed for %s, check tm5par.json since source will be o3 instead of %s." % (
                                task.target.variable, task.source.variable()))
                        elif task.target.variable == 'phalf':
                            log.error(
                                "ERR -11: Cmorizing failed for %s,  but variable is produced by IFS." % task.target.variable)
                        elif task.target.variable == 'ch4Clim' or task.target.variable == 'ch4global' or task.target.variable == 'ch4globalClim':
                            log.error(
                                "ERR -12: Cmorizing failed for %s, check tm5par.json since source will be ch4 instead of %s." % (
                                task.target.variable, task.source.variable()))
                        else:
                            log.error("ERR -13: Cmorizing failed for %s" % task.target.variable)
                    else:
                        taskmask[task] = True
                else:
                    log.info("Skipping variable %s for unknown reason..." % (task.source.variable()))
        for task, executed in taskmask.iteritems():
            if not executed:
                log.error("ERR -14: The source variable %s of target %s in  table %s failed to cmorize" % (
                task.source.variable(), task.target.variable, task.target.table))
                failed.append([task.target.variable, task.target.table])

    if len(unit_miss_match) > 0:
        log.info('Unit problems: %s' % unit_miss_match)
    if len(failed) > 0:
        for ifail in failed:
            log.info('Cmorization failed for : %s' % ifail)


# Performs a single task.
def execute_netcdf_task(task, tableid):
    """excute task for netcdf data
    Args:
        task (cmor.task): task which will be handled
        tableid (cmor.table): table which will have this task
    Returns:
        boolean: success of writing a variable
    """
    global log, dim_ids_, depth_axes_, time_axes_, areacella_
    interpolate_to_pressure = False
    task.status = cmor_task.status_cmorizing
    filepath = getattr(task, cmor_task.output_path_key, None)

    if not filepath:
        log.error("ERR -15: Could not find file containing data for variable %s in table %s" % (
        task.target.variable, task.target.table))
        task.set_failed()
        return

    store_var = getattr(task, "store_with", None)
    if task.target.dims >= 3:
        if 'lon' in dim_ids_ and 'lat' in dim_ids_:
            axes = [dim_ids_['lat'], dim_ids_['lon']]
        else:
            dim_ids_['lat'] = create_lat()
            dim_ids_['lon'] = create_lon()
            axes = [dim_ids_['lat'], dim_ids_['lon']]
        if hasattr(task, "z_axis_id"):
            axes.append(getattr(task, "z_axis_id"))
            checkaxes = getattr(task.target, cmor_target.dims_key).split()
            if 'plev19' in checkaxes:
                interpolate_to_pressure = True
            elif 'plev39' in checkaxes:
                interpolate_to_pressure = True
            # make explicit if just to check that all axes are there
            elif 'alevel' in checkaxes:
                interpolate_to_pressure = False
            elif 'alevhalf' in checkaxes:
                interpolate_to_pressure = False
            else:
                log.error('ERR -16: unknown dimension in z_axis_id')
        else:
            log.error('ERR -17: No z_axis_id found.')
    elif task.target.dims == 2:
        if task.target.table == 'AERmonZ':
            '''
            2D Zonal lat+lev
            '''
            # cmor.load_table(table_root_ + "_coordinate.json")
            if 'lat' in dim_ids_:
                axes = [dim_ids_['lat']]
            else:
                dim_ids_['lat'] = create_lat()
                axes = [dim_ids_['lat']]
            # zonal variables...
            # needs lat only, no grid....
            if hasattr(task, "z_axis_id"):
                axes.append(getattr(task, "z_axis_id"))
                if 'plev19' in getattr(task.target, cmor_target.dims_key).split():
                    interpolate_to_pressure = True
                elif 'plev39' in getattr(task.target, cmor_target.dims_key).split():
                    interpolate_to_pressure = True
        elif not hasattr(task, "z_axis_id"):
            ''' 
            2D variables lon+lat

            '''
            if not ('lon' in dim_ids_ and 'lat' in dim_ids_):
                dim_ids_['lat'] = create_lat()
                dim_ids_['lon'] = create_lon()
                axes = [dim_ids_['lat'], dim_ids_['lon']]
            else:
                axes = [dim_ids_['lat'], dim_ids_['lon']]
        else:
            log.error('ERR -18: unsupported 2D dimensions %s' % task.target.dims)
            exit('Exiting!')
    elif task.target.dims == 0:
        axes = []
    else:
        log.error('ERR -19: unsupported dimensions %s for variable' % (task.target.dims, task.target.variable))
        exit()
    time_id = getattr(task, "time_axis", 0)
    if time_id != 0:
        axes.append(time_id)
    for key in type_axes_:

        if key[0] == task.target.table and key[1] in getattr(task.target, cmor_target.dims_key):
            axes.append(type_axes_[key])
    try:
        dataset = netCDF4.Dataset(filepath, 'r')
    except Exception as e:
        log.error("ERR -20: Could not read netcdf file %s while cmorizing variable %s in table %s. Cause: %s" % (
            filepath, task.target.variable, task.target.table, e.message))
        return
    varid = create_cmor_variable(task, dataset, axes)
    if varid < 0:
        return False

    ## for pressure level variables we need to do interpolation, for which we need
    ## pyngl module
    if interpolate_to_pressure:
        psdata = get_ps_var(getattr(getattr(task, 'ps_task', None), cmor_task.output_path_key, None))
        pressure_levels = getattr(task, 'pressure_levels')
        ncvar = interpolate_plev(pressure_levels, dataset, psdata, task.source.variable())
        ncvar[ncvar > 1e20] = numpy.nan
    else:
        ncvar = dataset.variables[task.source.variable()]

    # handle zonal vars
    if task.target.table == 'AERmonZ':
        # assumption: data is shape [time,lat,lon] (roll longitude dimension
        vals = numpy.copy(ncvar[:])
        # zonal mean so mean over longitudes
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', '.*Mean of empty slice.*', )
            vals = numpy.nanmean(vals, axis=-1)
        # change shape, swap lat<->lev
        vals = numpy.swapaxes(vals, 1, 2)
        missval = getattr(task.target, cmor_target.missval_key, 1.e+20)
        ncvar = vals.copy()
    # handle global means
    elif task.target.dims == 0:
        # global means
        missval = getattr(task.target, cmor_target.missval_key, 1.e+20)
        vals = numpy.copy(ncvar[:])
        if task.target.variable == 'co2mass':
            # calculate area-weighted sum
            vals = numpy.sum((vals * areacella_[numpy.newaxis, :, :]), axis=(1, 2))
        else:
            # calculate area-weighted mean
            vals = numpy.mean(vals, axis=1)
            vals = numpy.sum((vals * areacella_[numpy.newaxis, :, :]), axis=(1, 2)) / numpy.sum(areacella_)
        ncvar = vals.copy()
    # handle normal case
    else:  # assumption: data is shape [time,lat,lon] (we need to roll longitude dimension so that
        #  the data corresponds to the dimension definition of tables (from [-180 , 180] to [0,360] deg).)
        #  so by half the longitude dimension
        missval = getattr(task.target, cmor_target.missval_key, 1.e+20)
        vals = numpy.copy(ncvar[:])
        dims = numpy.shape(vals)
        nroll = dims[-1] / 2
        ncvar = numpy.roll(vals, nroll, len(dims) - 1)
        vals = numpy.copy(ncvar[:, :, :])
    # Default values
    factor = 1.0
    term = 0.0
    timdim = 0
    # check for missing values
    if numpy.isnan(ncvar).any():
        nanmask = ~numpy.isnan(ncvar)
    else:
        nanmask = None
    # 3D variables need the surface pressure for calculating the pressure at model levels
    if store_var:
        # get the ps-data associated with this data
        psdata = get_ps_var(getattr(getattr(task, 'ps_task', None), cmor_task.output_path_key, None))
        # roll psdata like the original
        psdata = numpy.roll(psdata[:], nroll, len(numpy.shape(psdata[:])) - 1)
        cmor_utils.netcdf2cmor(varid, ncvar, timdim, factor, term, store_var, psdata,
                               swaplatlon=False, fliplat=True, mask=nanmask, missval=missval)
    else:
        cmor_utils.netcdf2cmor(varid, ncvar, timdim, factor, term, store_var, None,
                               swaplatlon=False, fliplat=True, mask=nanmask, missval=missval)
    cmor.close(varid)

    if store_var:
        cmor.close(store_var)
    task.status = cmor_task.status_cmorized


# Creates a variable in the cmor package
def create_cmor_variable(task, dataset, axes):
    """ Create cmor variable object
    Args:
        task (cmor.task): task for which we are creating a variable object
        dataset (netcdf-dataset): netcdf dataset containing the data for TM5 for this variable
        axes (list): list of axes ids for creation of cmor.variable object
    Returns:
        cmor.variable object: object identifier of created variable
    
    """
    srcvar = task.source.variable()
    ncvar = dataset.variables[srcvar]
    unit = getattr(ncvar, "units", None)
    if unit != getattr(task.target, "units"):
        if unit == 'mole mole-1':
            # files have mole mole-1 but should be mol mol-1
            unit = getattr(task.target, "units")
        elif srcvar == 'toz' or srcvar == 'tropoz':
            # unit is just different
            if unit == 'DU':
                setattr(task, cmor_task.conversion_key, 1e-5)
            unit = getattr(task.target, "units")
        elif srcvar == 'co2mass':
            # co2mass gets converted to area sum
            unit = getattr(task.target, "units")
        else:
            unit_miss_match.append(task.target.variable)
            log.error("ERR -21: unit miss match, variable %s" % task.target.variable)
            return task.set_failed()

    if (not unit) or hasattr(task, cmor_task.conversion_key):  # Explicit unit conversion
        unit = getattr(task.target, "units")
    if hasattr(task.target, "positive") and len(task.target.positive) != 0:
        return cmor.variable(table_entry=str(task.target.variable), units=str(unit), axis_ids=axes,
                             original_name=str(srcvar), positive="down")
    else:
        return cmor.variable(table_entry=str(task.target.variable), units=str(unit), axis_ids=axes,
                             original_name=str(srcvar))


def interpolate_plev(pressure_levels, dataset, psdata, varname):
    """interpolate pressure levels
    args:
        pressure_levels (numpy array): output pressure levels
        dataset(netcdf-dataset): input data for variable
        psdata (numpy-array): data for pressure at surface
        varname (string): name of variable for reading in the data
    Returns:
        interpolated_data (numpy-array): intepolated data in give pressure levels
    """
    ####
    # Interpolate data from model levels to pressure levels
    # pressure_levels defines the pressure levels
    # Based on pyngl example: 
    # https://www.pyngl.ucar.edu/Examples/Scripts/vinth2p.py 
    ####

    # Reference pressure 1e5 Pa in TM5, here in hPa 
    p0mb = 1000

    # Vertical coordinate must be from top to bottom: [::-1]
    hyam = dataset.variables["hyam"][:]
    # Vertical interplation routine expects formula a*p0 + b*ps, 
    # TM5 has a + b*ps, change a-> a*p0 by dividing a by the reference in TM5 p0=1e5 (1000 mb / hPa)
    hyam = hyam[::-1] / 100000
    # Vertical coordinate must be from top to bottom: [::-1]

    hybm = dataset.variables["hybm"][:]
    hybm = hybm[::-1]
    # Vertical coordinate must be from top to bottom: [::-1]
    data = dataset.variables[varname][:, :, :, :]
    data = data[:, ::-1, :, :]

    interpolation = 1  # 1 linear, 2 log, 3 loglog
    # divide pressure_levels by 100 to get in mb
    interpolated_data = Ngl.vinth2p(data, hyam, hybm, pressure_levels / 100, psdata[:, :, :], interpolation, p0mb, 1,
                                    False)
    return interpolated_data


# Creates time axes in cmor and attach the id's as attributes to the tasks
def create_time_axes(tasks):
    """ Create  time axes for all tasks
    Args:
        tasks (list): list of tasks for which time axes need to be created
    Returns:
        time_axes (dictionary): dictionary of time axes, with table+dimension combination as key
    
    """

    global log  # ,time_axes_
    time_axes = {}
    for task in tasks:
        freq = task.target.frequency
        tgtdims = getattr(task.target, cmor_target.dims_key)
        if getattr(task, cmor_task.output_path_key) == None:
            continue
        for time_dim in [d for d in list(set(tgtdims.split())) if d.startswith("time")]:
            key = (task.target.table, time_dim)
            if key in time_axes:
                tid = time_axes[key]
            else:
                time_operator = getattr(task.target, "time_operator", ["point"])
                log.info("Creating time axis using variable %s..." % task.target.variable)
                tid = create_time_axis(path=getattr(task, cmor_task.output_path_key),
                                       name=time_dim, has_bounds=(time_operator != ["point"]))
                time_axes[key] = tid
            setattr(task, "time_axis", tid)
            break
    return time_axes


# Creates a tie axis for the corresponding table (which is suppoed to be loaded)
def create_time_axis(path, name, has_bounds):
    """ creage time axis for a give frequency
    Args:
        path (string): full path to netcdf file with this freq
        name (string): tablename
        has_bounds (boolean): true if it has bounds
    Returns:
        cmor.axis-object: time axis object with given freq
    """
    global log, ref_date_
    vals = None
    units = None
    ds = None
    #
    ncfile = path
    refdate = ref_date_
    try:
        ds = netCDF4.Dataset(ncfile)
        timvar = ds.variables["time"]
        tm5unit = ds.variables["time"].units
        vals = timvar[:]
        units = getattr(timvar, "units")
        if has_bounds:
            bnds = getattr(timvar, "bounds")
            bndvar = ds.variables[bnds]
    except:
        ds.close()
    tm5refdate = datetime.datetime.strptime(tm5unit, "days since %Y-%m-%d %H:%M:%S")
    # delta days for change of reftime
    diff_days = (refdate - tm5refdate).total_seconds() / 86400
    vals = vals - diff_days
    if has_bounds:
        bndvar2 = numpy.zeros_like(bndvar)
        bndvar2[:, 0] = bndvar[:, 0] - int(diff_days)
        bndvar2[:, 1] = bndvar[:, 1] - int(diff_days)
        bndvar = bndvar2
        # hourly bounds can have overlap by -1e-14, which is caught by cmor library as an error
        # so just correct it always
        for i in range(numpy.shape(bndvar2)[0] - 1):
            bndvar2[i + 1, 0] = bndvar2[i, 1]
    if len(vals) == 0 or units == None:
        log.error("ERR -22: No time values or units could be read from tm5 output files %s" % str(path))
        return -1
    units = "days since " + str(ref_date_)
    ####
    if has_bounds:
        return cmor.axis(table_entry=str(name), units=units, coord_vals=vals, cell_bounds=bndvar[:, :])
    else:
        return cmor.axis(table_entry=str(name), units=units, coord_vals=vals)


def create_type_axes(task):
    """ create type axes(lambda 550nm only for the moment)
    Args:
        task (cmor.task-object): task for which type axes will be created
    Returns:
        Boolean: if succesful creation
    """
    global type_axes
    table = task.target.table
    key = (table, 'lambda550nm')
    if key not in type_axes_:
        type_axes_[key] = {}
    filepath = getattr(task, cmor_task.output_path_key)
    log.info("Creating extra axes for table %s using file %s..." % (table, filepath))
    table_type_axes = type_axes_[key]
    tgtdims = set(getattr(task.target, cmor_target.dims_key).split()).intersection(extra_axes.keys())
    for dim in tgtdims:
        if dim == 'lambda550nm':
            ncunits = extra_axes['lambda550nm']['ncunits']
            ncvals = extra_axes['lambda550nm']['ncvals']
            ax_id = cmor.axis(table_entry="lambda550nm", units=ncunits, coord_vals=ncvals)
            setattr(task, "lambda_axis", ax_id)
            type_axes_[key] = ax_id
        else:
            log.info("Unknown dimenstion %s in table %s." % (dim, table))
            return False
    return True


def create_depth_axes(task):
    """ create depth axes 
    Args:
        task (cmor.task-object): task for which the depth axes are created
    Returns:
        boolean: is creation successful or not
    """
    global log_depth_axis_ids, zfactor_ids

    tgtdims = getattr(task.target, cmor_target.dims_key)
    # zdims all other than xy
    # including lambda550nm...
    zdims = getattr(task.target, "z_dims", [])
    if len(zdims) == 0:
        return False
    if len(zdims) > 1:
        log.error("ERR -23: Skipping variable %s in table %s with dimensions %s with multiple z-directions." % (
            task.target.variable, task.target.table, tgtdims))
        task.set_failed()
        return False
    zdim = str(zdims[0])
    key = (task.target.table, zdim)
    if key not in depth_axis_ids:
        log.info("Creating vertical axis %s for table %s..." % (zdim, task.target.table))

    if key in depth_axis_ids:
        # setattr(task, "z_axis_id", depth_axis_ids[zdim])
        if zdim == "alevel":
            setattr(task, "z_axis_id", depth_axis_ids[key][0])
            setattr(task, "store_with", depth_axis_ids[key][1])
        elif zdim == "alevhalf":
            setattr(task, "z_axis_id", depth_axis_ids[key][0])
            setattr(task, "store_with", depth_axis_ids[key][1])
        elif zdim == "plev19":
            setattr(task, "z_axis_id", depth_axis_ids[key])
            setattr(task, "pressure_levels", plev19_)
        elif zdim == "plev39":
            setattr(task, "z_axis_id", depth_axis_ids[key])
            setattr(task, "pressure_levels", plev39_)
        else:
            setattr(task, "z_axis_id", depth_axis_ids[key])
        return True
    elif zdim == 'alevel':
        log.info("Creating model full level axis for variable %s..." % task.target.variable)
        axisid, psid = create_hybrid_level_axis(task)
        depth_axis_ids[key] = (axisid, psid)
        if key[0] not in zfactor_ids:
            zfactor_ids[key[0]] = psid
        setattr(task, "z_axis_id", axisid)
        setattr(task, "store_with", psid)
        return True
    elif zdim == 'alevhalf':
        # if zdim not in depth_axis_ids:
        log.info("Creating model half level axis for variable %s..." % task.target.variable)
        axisid, psid = create_hybrid_level_axis(task, 'alevhalf')
        depth_axis_ids[key] = (axisid, psid)
        if key[0] not in zfactor_ids:
            zfactor_ids[key[0]] = psid
        setattr(task, "z_axis_id", axisid)
        setattr(task, "store_with", psid)
        return True
    elif zdim == "lambda550nm":
        log.info("Creating wavelength axis for variable %s..." % task.target.variable)
        axisid = cmor.axis(table_entry=zdim, units="nm", coord_vals=[550.0])
        depth_axis_ids[key] = axisid
        setattr(task, "z_axis_id", axisid)
        return True
    elif zdim == "plev19":
        axisid = cmor.axis(table_entry=zdim, units="Pa", coord_vals=plev19_)
        depth_axis_ids[key] = axisid
        setattr(task, "z_axis_id", axisid)
        setattr(task, "pressure_levels", plev19_)
        return True
    elif zdim == "plev39":
        axisid = cmor.axis(table_entry=zdim, units="Pa", coord_vals=plev39_)
        depth_axis_ids[key] = axisid
        setattr(task, "z_axis_id", axisid)
        setattr(task, "pressure_levels", plev39_)
        return True
    elif zdim == "site":
        log.critical('Z-dimension %s will not be implemented.' % zdim)
        return False
    else:
        log.critical("Z-dimension %s not found for variable %s..." % (zdim, task.target.variable))
        return False


# Creates the hybrid model vertical axis in cmor.
def create_hybrid_level_axis(task, leveltype='alevel'):
    """Create hybrud levels
    Args:
        task (cmor.task-object): task for which levels are created
        leveltype (string): which kind (alevel, alevhalf)
    Returns:
        axisid (cmor.axis-object): axis id for levels
        storewith (cmor.zfactor-object): surface pressure field for saving into same file. needed for calculation of pressure on model levels.
    """
    global time_axes_, store_with_ps_, dim_ids_, zfactor_ids
    # define grid axes and time axis for hybrid levels
    axes = [getattr(task, 'lat'), getattr(task, 'lon'), getattr(task, "time_axis")]

    # define before hybrid factors, and have the same
    # for 
    pref = 80000  # TODO: Move reference pressure level to model config
    path = getattr(task, cmor_task.output_path_key)
    ds = None
    try:
        ds = netCDF4.Dataset(path)
        am = ds.variables["hyam"]
        aunit = getattr(am, "units")
        bm = ds.variables["hybm"]
        bunit = getattr(bm, "units")
        hcm = am[:] / pref + bm[:]
        n = hcm.shape[0]
        if "hyai" in ds.variables:
            ai = ds.variables["hyai"]
            abnds = numpy.empty([n, 2])
            abnds[:, 0] = ai[0:n]
            abnds[:, 1] = ai[1:n + 1]
            bi = ds.variables["hybi"]
            bbnds = numpy.empty([n, 2])
            bbnds[:, 0] = bi[0:n]
            bbnds[:, 1] = bi[1:n + 1]
            hcbnds = abnds / pref + bbnds
            hci = ai[:] / pref + bi[:]
            n = hci.shape[0]
        else:
            log.critical("Interface values for hybrid levels not present!")
        if leveltype == 'alevel':
            axisid = cmor.axis(table_entry="alternate_hybrid_sigma", coord_vals=hcm, cell_bounds=hcbnds, units="1")
            cmor.zfactor(zaxis_id=axisid, zfactor_name="ap", units=str(aunit), axis_ids=[axisid], zfactor_values=am[:],
                         zfactor_bounds=abnds)
            cmor.zfactor(zaxis_id=axisid, zfactor_name="b", units=str(bunit), axis_ids=[axisid], zfactor_values=bm[:],
                         zfactor_bounds=bbnds)
        elif leveltype == 'alevhalf':
            axisid = cmor.axis(table_entry="alternate_hybrid_sigma_half", coord_vals=hci, units="1")

            cmor.zfactor(zaxis_id=axisid, zfactor_name="ap_half", units=str(aunit), axis_ids=[axisid, ],
                         zfactor_values=ai[:])
            cmor.zfactor(zaxis_id=axisid, zfactor_name="b_half", units=str(bunit), axis_ids=[axisid, ],
                         zfactor_values=bi[:])
        # Use the same ps for both types of hybrid levels,
        # for some reason defining their own confuses the cmor
        # to check in case of Half levels, for the ps from full levels
        if task.target.variable == 'ec550aer':
            psvarname = 'ps1'
        else:
            psvarname = 'ps'
        # if depth_axis_ids[('task.table',leveltype)]!=None:

        #    setattr(task,'store_with',depth_axis_ids[('task.table',leveltype)])
        if task.target.table not in zfactor_ids:
            storewith = cmor.zfactor(zaxis_id=axisid, zfactor_name=psvarname,
                                     axis_ids=axes, units="Pa")
            setattr(task, 'store_with', storewith)
        else:
            storewith = zfactor_ids[task.target.table]
        return axisid, storewith
    finally:
        if ds is not None:
            ds.close()


def create_lat():
    """Create latitude dimension
    Args:
        none
    Returns:
        lat_id (cmor.axis): cmor.axis-object 
    """
    yvals = numpy.linspace(89, -89, 90)
    ny = len(yvals)
    lat_bnd = numpy.linspace(90, -90, 91)
    lat_id = cmor.axis(table_entry="latitude", units="degrees_north",
                       coord_vals=yvals, cell_bounds=lat_bnd)
    return lat_id


def create_lon():
    """Create longitude dimension
    Args:
        none
    Returns:
        lon_id (cmor_axis): cmor.axis-object 
    """
    xvals = numpy.linspace(1.5, 358.5, 120)
    nx = len(xvals)
    lon_bnd = numpy.linspace(0, 360, 121)
    lon_id = cmor.axis(table_entry="longitude", units="degrees_east",
                       coord_vals=xvals, cell_bounds=lon_bnd)
    return lon_id


# Surface pressure variable lookup utility
def get_ps_var(ncpath):
    """ read surface pressure variable for 3D output
    Args:
        ncpath (string): full path to ps_*.nc file
    Returns:
        numpy-array: [lon,lat,time]-array containing surface pressure values  
    """

    if not ncpath:
        log.error("ERR -2: No path defined for surface pressure (ps).")
        return None
    if not os.path.exists(ncpath):
        log.error("ERR -3: Path does not exist for surface pressure (ps).")
        return None
    ds = None
    try:
        ds = netCDF4.Dataset(ncpath)
        if "ps" in ds.variables:
            return ds.variables["ps"]
        else:
            log.error("ERR -4: Variable ps not present in pressure file.")
            return None
    except Exception as e:
        log.error("ERR -5: Could not read netcdf file %s for surface pressure, reason: %s" % (ncpath, e.message))
        return None


# Creates extra tasks for surface pressure
def get_ps_tasks(tasks):
    """ find ps (surface preseure) tasks for different tables
    Args:
        tasks (list): list of tasks
    Returns:
        result (dictionary): dictionary based on the frequencies of different tasks with corresponding ps-tasks as values.

    """
    global exp_name_, path_
    tasks_by_freq = cmor_utils.group(tasks, lambda task: task.target.frequency)
    result = {}
    for freq, task_group in tasks_by_freq.iteritems():
        tasks3d = [t for t in task_group if (
                    "alevel" in getattr(t.target, cmor_target.dims_key).split() or "plev19" in getattr(t.target,
                                                                                                       cmor_target.dims_key).split() or
                    "alevhalf" in getattr(t.target, cmor_target.dims_key).split() or "plev39" in getattr(t.target,
                                                                                                         cmor_target.dims_key).split())]
        if not any(tasks3d):
            continue
        ps_tasks = [t for t in task_group if t.source.variable() == "ps" and
                    getattr(t, "time_operator", "point") in ["mean", "point"]]
        ps_task = ps_tasks[0] if any(ps_tasks) else None
        if ps_task:
            result[freq] = ps_task
        else:
            source = cmor_source.tm5_source("ps")
            ps_task = cmor_task.cmor_task(source, cmor_target.cmor_target("ps", freq))
            setattr(ps_task.target, cmor_target.freq_key, freq)
            setattr(ps_task.target, "time_operator", ["point"])
            freqid = set_freqid(freq)
            filepath = cmor_utils.find_tm5_output(path_, exp_name_, "ps", freqid)
            setattr(ps_task, cmor_task.output_path_key, filepath[0])
            result[freq] = ps_task
        for task3d in tasks3d:
            setattr(task3d, "ps_task", ps_task)
    return result
