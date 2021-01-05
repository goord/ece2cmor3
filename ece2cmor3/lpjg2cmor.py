import json
import logging
from datetime import date

import cmor
import netCDF4
import numpy as np
import pandas as pd
from cdo import *

# for compressed files
import gzip
import shutil

from ece2cmor3 import cmor_utils, cmor_target, cmor_task

# from cmor.Test.test_python_open_close_cmor_multiple import path

# Logger object
log = logging.getLogger(__name__)

# Experiment name
exp_name_ = None

# Table root
table_root_ = None

# Reference date i.e. the start date given by user as a command line parameter
ref_date_ = None

# lpjg_path_ is the directory where the data files (LPJG .out-files) are located
lpjg_path_ = None

# ncpath_ is the tmp directory where the temporary netcdf files will be placed
ncpath_ = None
ncpath_created_ = False

target_grid_ = "T255"
gridfile_ = os.path.join(os.path.dirname(__file__), "resources/lpjg-grid-content", "ingrid_T255_unstructured.txt")

# list of requested entries for the land use axis
landuse_requested_ = []

# the cmor prefix (e.g. CMIP6) is currently needed to treat the possible requests for land use types, but  might be
# unnecessary in the future depending on how much of the request will be handled in already when writing the model
# output
cmor_prefix_ = None

_months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']

# various things extracted from Michael.Mischurow out2nc tool: ec_earth.py
grids = {
    80: [18, 25, 36, 40, 45, 54, 60, 64, 72, 72, 80, 90, 96, 100, 108, 120, 120, 128, 135, 144, 144, 150, 160, 160, 180,
         180, 180, 192, 192, 200, 200, 216, 216, 216, 225, 225, 240, 240, 240, 256, 256, 256, 256, 288, 288, 288, 288,
         288, 288, 288, 288, 288, 300, 300, 300, 300, 320, 320, 320, 320, 320, 320, 320, 320, 320, 320, 320, 320, 320,
         320, 320, 320, 320, 320, 320, 320, 320, 320, 320, 320],
    128: [18, 25, 36, 40, 45, 50, 60, 64, 72, 72, 80, 90, 90, 100, 108, 120, 120, 125, 128, 144, 144, 150, 160, 160,
          180, 180, 180, 192, 192, 200, 216, 216, 216, 225, 240, 240, 240, 250, 250, 256, 270, 270, 288, 288, 288, 300,
          300, 320, 320, 320, 320, 324, 360, 360, 360, 360, 360, 360, 360, 375, 375, 375, 375, 384, 384, 400, 400, 400,
          400, 405, 432, 432, 432, 432, 432, 432, 432, 450, 450, 450, 450, 450, 480, 480, 480, 480, 480, 480, 480, 480,
          480, 480, 486, 486, 486, 500, 500, 500, 500, 500, 500, 500, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512,
          512, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512],
}
grids = {i: j + j[::-1] for i, j in grids.items()}


def rnd(x, digits=3):
    return round(x, digits)


def coords(df, root, meta):
    global gridfile_, target_grid_
    # deg is 128 in N128
    # common deg: 32, 48, 80, 128, 160, 200, 256, 320, 400, 512, 640
    # correspondence to spectral truncation:
    # t159 = n80; t255 = n128; t319 = n160; t639 = n320; t1279 = n640
    # i.e. t(2*X -1) = nX
    # number of longitudes in the regular grid: deg * 4
    # At deg >= 319 polar correction might have to be applied (see Courtier and Naughton, 1994)
    deg = 128
    grid_size = len(df)
    if grid_size == 10407:
        target_grid_ = "T159"
        deg = 80
        gridfile_ = os.path.join(os.path.dirname(__file__), "resources/lpjg-grid-content",
                                 "ingrid_T159_unstructured.txt")
    elif grid_size != 25799:
        log.error("Current grid with %i cells is not supported!", grid_size)
        exit(-1)

    lons = [lon for num in grids[deg] for lon in np.linspace(0, 360, num, False)]
    x, w = np.polynomial.legendre.leggauss(deg * 2)
    lats = np.arcsin(x) * 180 / -np.pi
    lats = [lats[i] for i, n in enumerate(grids[deg]) for _ in range(n)]

    if 'i' not in root.dimensions:
        root.createDimension('i', len(lons))
        root.createDimension('j', 1)

        latitude = root.createVariable('lat', 'f4', ('j', 'i'))
        latitude.standard_name = 'latitude'
        latitude.long_name = 'latitude coordinate'
        latitude.units = 'degrees_north'
        # latitude.bounds = 'lat_vertices'
        latitude[:] = lats

        longitude = root.createVariable('lon', 'f4', ('j', 'i'))
        longitude.standard_name = 'longitude'
        longitude.long_name = 'longitude coordinate'
        longitude.units = 'degrees_east'
        # longitude.bounds = 'lon_vertices'
        longitude[:] = lons

    run_lons = [rnd(i) for i in (df.index.levels[0].values + 360.0) % 360.0]
    run_lats = [rnd(i) for i in df.index.levels[1]]

    df.index.set_levels([run_lons, run_lats], inplace=True)
    df = df.reindex([(rnd(i), rnd(j)) for i, j in zip(lons, lats)], fill_value=meta['missing'])

    return df, ('j', 'i')


# TODO: if LPJG data that has been run on the regular grid is also used, the corresponding coords function
# from Michael Mischurow's regular.py should be added here (possibly with some modifications)

# Initialization before the processing of the LPJ-Guess tasks
def initialize(path, ncpath, expname, tabledir, prefix, refdate):
    global log, exp_name_, table_root_, ref_date_
    global lpjg_path_, ncpath_, ncpath_created_, landuse_requested_, cmor_prefix_
    exp_name_ = expname
    table_root_ = os.path.join(tabledir, prefix)
    lpjg_path_ = path
    ref_date_ = refdate
    cmor_prefix_ = prefix
    if not ncpath.startswith("/"):
        ncpath_ = os.path.join(lpjg_path_, ncpath)
    else:
        ncpath_ = ncpath
    if not os.path.exists(ncpath_) and not ncpath_created_:
        os.makedirs(ncpath_)
        ncpath_created_ = True
    cmor.load_table(table_root_ + "_grids.json")

    coordfile = os.path.join(tabledir, prefix + "_coordinate.json")
    if os.path.exists(coordfile):
        with open(coordfile) as f:
            data = json.loads(f.read())
        axis_entries = data.get("axis_entry", {})
        axis_entries = {k.lower(): v for k, v in axis_entries.iteritems()}
        if axis_entries['landuse']['requested']:
            landuse_requested_ = [entry.encode('ascii') for entry in axis_entries['landuse']['requested']]

    return True


# Executes the processing loop.
# used the nemo2cmor.py execute as template
def get_lpj_freq(frequency):
    if frequency == "yr" or frequency == "yrPt":
        return "yearly"
    if frequency == "mon":
        return "monthly"
    if frequency == "day":
        return "daily"
    return None


def execute(tasks):
    global log, table_root_
    global lpjg_path_, ncpath_
    log.info("Executing %d lpjg tasks..." % len(tasks))
    log.info("Cmorizing lpjg tasks...")
    taskdict = cmor_utils.group(tasks, lambda t: t.target.table)
    for table, tasklist in taskdict.iteritems():
        try:
            tab_id = cmor.load_table("_".join([table_root_, table]) + ".json")
            cmor.set_table(tab_id)
        except Exception as e:
            log.error("CMOR failed to load table %s, skipping variables %s. Reason: %s"
                      % (table, ','.join([tsk.target.variable for tsk in tasklist]), e.message))
            continue

        lon_id = None
        lat_id = None
        for task in tasklist:
            freq = task.target.frequency.encode()
            freqstr = get_lpj_freq(task.target.frequency)
            if freqstr is None:
                log.error("The frequency %s for variable %s in table %s is not supported by lpj2cmor" %
                          (task.target.frequency, task.target.variable, task.target.table))
                task.set_failed()
                continue

            # if compressed file .out.gz file exists, uncompress it to temporary .out file
            gzfile = os.path.join(lpjg_path_, task.source.variable() + "_" + freqstr + ".out.gz")
            if os.path.exists(gzfile):
                lpjgfile = os.path.join(ncpath_, task.source.variable() + "_" + freqstr + ".out")
                log.info("Uncompressing file " + gzfile + " to temporary file " + lpjgfile)
                with gzip.open(gzfile, 'rb') as f_in, open(lpjgfile, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            else:
                lpjgfile = os.path.join(lpjg_path_, task.source.variable() + "_" + freqstr + ".out")

            if not os.path.exists(lpjgfile):
                log.error("The file %s does not exist. Skipping CMORization of variable %s."
                          % (lpjgfile, task.source.variable()))
                task.set_failed()
                continue
            if not check_time_resolution(lpjgfile, freq):
                log.error("The data in the file %s did not match the expected frequency (time resolution). "
                          "Skipping CMORization of variable %s." % (lpjgfile, task.source.variable()))
                task.set_failed()
                continue
            log.info("Processing file " + lpjgfile)
            setattr(task, cmor_task.output_path_key, task.source.variable() + ".out")
            outname = task.target.out_name
            outdims = task.target.dimensions

            # find first and last year in the .out-file
            firstyear, lastyear = find_timespan(lpjgfile)
            # check if user given reference year is after the first year in data file: this is not allowed
            if int(ref_date_.year) > firstyear:
                log.error("The reference date given is after the first year in the data (%s) for variable %s "
                          "in file %s. Skipping CMORization." % (firstyear, task.source.variable(), lpjgfile))
                task.set_failed()
                continue

            # divide the data in the .out-file by year to temporary files
            yearly_files = divide_years(lpjgfile, firstyear, lastyear, outname)

            for yearfile in yearly_files:

                # Read data from the .out-file and generate the netCDF file including remapping
                ncfile = create_lpjg_netcdf(freq, yearfile, outname, outdims)

                if ncfile is None:
                    if "landUse" in outdims.split():
                        log.error("Land use columns in file %s do not contain all of the requested land use types. "
                                  "Skipping CMORization of variable %s" % (
                                      getattr(task, cmor_task.output_path_key), task.source.variable()))
                    else:
                        log.error(
                            "Unexpected subtype in file %s: either no type axis has been requested for variable %s "
                            "or explicit treatment for the axis has not yet been implemented. Skipping CMORization."
                            % (getattr(task, cmor_task.output_path_key), task.source.variable()))
                    break

                # special treatment of fco2nat=fco2nat_lpjg+fgco2_nemo
                if outname == "fco2nat" and freq == "mon" and table == "Amon" and (
                        cmor.get_cur_dataset_attribute("source_id") == "EC-Earth3-CC"):
                    if not add_nemo_variable(task, ncfile, "fgco2", "1m"):
                        log.error("There was a problem adding nemo variable %s to %s in table %s... "
                                  "exiting ece2cmor3" % ("fgco2", task.target.variable, task.target.table))
                        exit(-1)

                dataset = netCDF4.Dataset(ncfile, 'r')
                # Create the grid, need to do only once as all LPJG variables will be on same grid
                # Currently create_grid just creates latitude and longitude axis since that should be all that is needed
                if lon_id is None and lat_id is None:
                    lon_id, lat_id = create_grid(dataset, task)
                setattr(task, "longitude_axis", lon_id)
                setattr(task, "latitude_axis", lat_id)

                # Create cmor time axis for current variable
                create_time_axis(dataset, task)

                # if this is a land use variable create cmor land use axis
                if "landUse" in outdims.split():
                    create_landuse_axis(task, lpjgfile, freq)

                # if this is a pft variable (e.g. landCoverFrac) create cmor vegtype axis
                if "vegtype" in outdims.split():
                    create_vegtype_axis(task, lpjgfile, freq)

                # if this variable has the soil depth dimension sdepth 
                # (NB! not sdepth1 or sdepth10) create cmor sdepth axis
                if "sdepth" in outdims.split():
                    create_sdepth_axis(task, lpjgfile, freq)

                # if this variable has one or more "singleton axes" (i.e. axes 
                # of length 1) which can be those dimensions 
                # named "type*", these will be created here
                for lpjgcol in outdims.split():
                    if lpjgcol.startswith("type"):
                        # THIS SHOULD BE LINKED TO CIP6_coordinate.json!
                        if lpjgcol == "typenwd":
                            singleton_value = "herbaceous_vegetation"
                        elif lpjgcol == "typepasture":
                            singleton_value = "pastures"
                        else:
                            continue
                        create_singleton_axis(task, lpjgfile, str(lpjgcol), singleton_value)

                # cmorize the current task (variable)
                execute_single_task(dataset, task)
                dataset.close()

                # remove the regular (non-cmorized) netCDF file and the temporary .out file for current year
                os.remove(ncfile)
                os.remove(yearfile)

            # end yearfile loop

            # if compressed file .out.gz file exists, remove temporary .out file
            if os.path.exists(gzfile):
                os.remove(lpjgfile)

    return


# checks that the time resolution in the .out data file matches the requested frequency
def check_time_resolution(lpjgfile, freq):
    with open(lpjgfile) as f:
        header = next(f).lower().split()
    if freq == "mon":
        return 'mth' in header or header[-12:] == _months
    elif freq == "day":
        return 'day' in header
    elif freq.startswith("yr"):
        # to find out if it is yearly data have to check that it is neither monthly nor daily
        if 'mth' in header or header[-12:] == _months or 'day' in header:
            return False
        else:
            return True
    else:
        return False  # LPJ-Guess only supports yearly, monthly or daily time resolutions


# Returns first and last year present in the .out data file
def find_timespan(lpjgfile):
    df = pd.read_csv(lpjgfile, delim_whitespace=True, usecols=['Year'], dtype=np.int32)

    firstyr = df['Year'].min()
    lastyr = df['Year'].max()

    return firstyr, lastyr


# Divides the .out file by year to a set of temporary files This approach was chosen to avoid problems with trying to
#  keep huge amounts of data in the memory as the original .out-files can have even >100 years worth of daily data
def divide_years(lpjgfile, firstyr, lastyr, outname):
    files = {}
    filenames = []
    with open(lpjgfile) as f:
        header = next(f)
        # create the yearly files and write header to each
        for yr in range(firstyr, lastyr + 1):
            fname = os.path.join(ncpath_, outname + "_" + str(yr) + ".out")
            filenames.append(fname)
            files[yr] = open(fname, 'w')
            files[yr].write(header)

        # assign the data lines in the .out-file to correct yearly file
        for line in f:
            yr = int(line.split()[2])
            if yr < firstyr:
                continue
            files[yr].write(line)

    for yr in files:
        files[yr].close()

    return filenames


# this function builds upon a combination of _get and save_nc functions from the out2nc.py tool originally by Michael
#  Mischurow
def create_lpjg_netcdf(freq, inputfile, outname, outdims):
    global ncpath_, gridfile_

    # checks for additional dimensions besides lon,lat&time (for those dimensions where the dimension actually exists
    #  in lpjg data)
    is_land_use = "landUse" in outdims.split()
    is_veg_type = "vegtype" in outdims.split()
    is_sdepth = "sdepth" in outdims.split()

    # assigns a flag to handle two different possible monthly LPJ-Guess formats
    months_as_cols = False
    if freq == "mon":
        with open(inputfile) as f:
            header = next(f).lower().split()
            months_as_cols = header[-12:] == _months

    if freq == "mon" and not months_as_cols:
        idx_col = [0, 1, 2, 3]
    elif freq == "day":
        idx_col = [0, 1]
    else:
        idx_col = [0, 1, 2]

    df = pd.read_csv(inputfile, delim_whitespace=True, index_col=idx_col, dtype=np.float64, compression='infer')
    df.rename(columns=lambda x: x.lower(), inplace=True)

    if is_land_use:
        # NOTE: The following treatment of landuse types is likely to change depending on how the lut data requests
        # will be treated when creating the .out-files
        if not landuse_requested_:  # no specific request for land use types, pick all types present in the .out-file
            landuse_types = list(df.columns.values)
        elif cmor_prefix_ == "CMIP6":
            # NOTE: the land use files in the .out-files should match the CMIP6 requested ones (in content if not in
            # name) for future CMIP6 runs this is just a temporary placeholder solution for testing purposes!
            landuse_types = ['psl', 'pst', 'crp', 'urb']
        else:
            # for now skip the variable entirely if there is not exact matches in the .out-file for all the requested
            #  landuse types (except for CMIP6-case of course)
            colnames = list(df.columns.values)
            for lut in landuse_requested_:
                if lut not in colnames:
                    return None
            landuse_types = landuse_requested_

        df_list = []
        for lut in range(len(landuse_types)):
            colname = landuse_types[lut]
            df_list.append(get_lpjg_datacolumn(df, freq, colname, months_as_cols))

    elif is_veg_type:
        pfts = list(df.columns.values)
        df_list = []
        for p in range(len(pfts)):
            df_list.append(get_lpjg_datacolumn(df, freq, pfts[p], months_as_cols))

    elif is_sdepth:
        depths = list(df.columns.values)
        if "year" in depths:
            if freq == "mon" or freq == "day":
                depths = list(depths[2:])
            else:
                depths = list(depths[1:])
        df_list = []
        for sd in range(len(depths)):
            df_list.append(get_lpjg_datacolumn(df, freq, depths[sd], months_as_cols))

    else:  # regular variable
        colname = ""
        if not months_as_cols:
            if "total" not in list(df.columns.values):
                return None
            else:
                colname = "total"
        df = get_lpjg_datacolumn(df, freq, colname, months_as_cols)
        df_list = [df]

    if freq.startswith("yr"):
        str_year = str(int(df_list[0].columns[0]))
    else:
        str_year = str(int(df_list[0].columns[0][1]))

    log.info("Creating lpjg netcdf file for variable " + outname + " for year " + str_year)

    ncfile = os.path.join(ncpath_, outname + "_" + freq + "_" + str_year + ".nc")
    # Note that ncfile could be named anything, it will be deleted later and the cmorization takes care of proper
    # naming conventions for the final file

    # temporary netcdf file name (will be removed after remapping is done)
    temp_ncfile = os.path.join(ncpath_, 'LPJGtemp.nc')
    root = netCDF4.Dataset(temp_ncfile, 'w')  # now format is NETCDF4

    root.createDimension('time', None)
    timev = root.createVariable('time', 'f4', ('time',))
    refyear = int(ref_date_.year)
    if freq == "mon":
        curyear, tres = int(df_list[0].columns[0][1]), 'month'
        t_since_fyear = (curyear - refyear) * 12
    elif freq == "day":
        curyear, tres = int(df_list[0].columns[0][1]), 'day'
        t_since_fyear = (date(curyear, 1, 1) - date(refyear, 1, 1)).days
    else:
        curyear, tres = int(df_list[0].columns[0]), 'year'
        t_since_fyear = curyear - refyear
    timev[:] = np.arange(t_since_fyear, t_since_fyear + df_list[0].shape[1])
    timev.units = '{}s since {}-01-01'.format(tres, refyear)
    timev.calendar = "proleptic_gregorian"

    meta = {"missing": 1.e+20}  # the missing/fill value could/should be taken from the target header info if available
    # and does not need to be in a meta dict since coords only needs the fillvalue anyway, but do it like this (i.e.
    # out2nc-style) for now

    N_dfs = len(df_list)
    df_normalised = []
    dimensions = []

    for l in range(N_dfs):
        # TODO: if different LPJG grids possible you need an if-check here to choose which function is called
        df_out, dimensions = coords(df_list[l], root, meta)
        df_normalised.append(df_out)

    if N_dfs == 1:
        dimensions = 'time', dimensions[0], dimensions[1]

        variable = root.createVariable(outname, 'f4', dimensions, zlib=True,
                                       shuffle=False, complevel=5, fill_value=meta['missing'])
        if outname == "tsl":
            variable[:] = df_normalised[
                0].values.T  # TODO: see out2nc for what to do here if you have the LPJG regular grid
        else:
            dumvar = df_normalised[0].values.T
            variable[:] = np.where(dumvar < 1.e+20, dumvar,
                                   0.)  # TODO: see out2nc for what to do here if you have the LPJG regular grid

    else:
        root.createDimension('fourthdim', N_dfs)

        dimensions = 'time', 'fourthdim', dimensions[0], dimensions[1]
        variable = root.createVariable(outname, 'f4', dimensions, zlib=True,
                                       shuffle=False, complevel=5, fill_value=meta['missing'])
        for l in range(N_dfs):
            if outname == "tsl":
                variable[:, l, :, :] = df_normalised[
                    l].values.T  # TODO: see out2nc for what to do here if you have the LPJG regular grid
            else:
                dumvar = df_normalised[l].values.T
                variable[:, l, :, :] = np.where(dumvar < 1.e+20, dumvar,
                                                0.)  # TODO: see out2nc for what to do here if you have the LPJG regular grid

    root.sync()
    root.close()

    # do the remapping
    cdo = Cdo()

    if target_grid_ == "T159":
        cdo.remapycon('n80', input="-setgrid," + gridfile_ + " " + temp_ncfile,
                      output=ncfile)
    else:
        cdo.remapycon('n128', input="-setgrid," + gridfile_ + " " + temp_ncfile,
                      output=ncfile)  # TODO: add remapping for possible other grids

    os.remove(temp_ncfile)

    return ncfile


# finds the nemo output containing varname at nemo_freq
# this uses code in nemo2cmor.py, which could be moved to cmor_utils
def find_nemo_file(varname, nemo_freq):
    # find the nemo output folder for this leg (assumes it is in the runtime/output/nemo/??? folder)
    path_output_lpjg, leg_no = os.path.split(lpjg_path_)
    path_output = os.path.split(path_output_lpjg)
    nemo_path = os.path.join(path_output[0], 'nemo', leg_no)
    # get the file which contains fgco2
    try:
        nemo_files = cmor_utils.find_nemo_output(nemo_path, exp_name_)
    except OSError:
        log.error("Cannot find any nemo output files in %s" % nemo_path)
        return ""
    file_candidates = [f for f in nemo_files if cmor_utils.get_nemo_frequency(f, exp_name_) == nemo_freq]
    results = []
    for ncfile in file_candidates:
        ds = netCDF4.Dataset(ncfile)
        if varname in ds.variables:
            results.append(ncfile)
        ds.close()
    # simplified error reporting
    if len(results) != 1:
        log.error("Cannot find any suitable nemo output files in %s" % nemo_path)
        return ""
    return results[0]


# this function builds upon a combination of _get and save_nc functions from the out2nc.py tool originally by Michael
#  Mischurow
def add_nemo_variable(task, ncfile, nemo_var_name, nemo_var_freq):
    # find nemo raw output file
    nemo_ifile = find_nemo_file(nemo_var_name, nemo_var_freq)
    if nemo_ifile == "":
        log.error("NEMO variable %s needed for target %s in table %s was not found in nemo output... "
                  % (nemo_var_name, task.target.variable, task.target.table))
        return False

    # define auxiliary and temp. files
    nemo_maskfile = os.path.join(os.path.dirname(__file__), "resources", "nemo-mask-ece.nc")
    nemo_ofile = os.path.join(ncpath_, "tmp_nemo.nc")
    interm_file = os.path.join(ncpath_, "intermediate.nc")
    if os.path.exists(nemo_ofile):
        os.remove(nemo_ofile)
    if os.path.exists(interm_file):
        os.remove(interm_file)

    # make sure the mask and input file have same dimensions
    ds_maskfile = netCDF4.Dataset(nemo_maskfile, 'r')
    ds_ifile = netCDF4.Dataset(nemo_ifile, 'r')
    dims_maskfile = ds_maskfile.dimensions
    dims_ofile = ds_ifile.dimensions
    if dims_maskfile['x'].size != dims_ofile['x'].size or dims_maskfile['y'].size != dims_ofile['y'].size:
        log.error(
            "NEMO mask and output file, required for NEMO variable %s needed for target %s in table %s do not have same dimensions... "
            % (nemo_var_name, task.target.variable, task.target.table))
        return False
    ds_maskfile.close()
    ds_ifile.close()

    # perform the conservative remapping using cdo
    # cdo -L selvar,${varname} ${ifile} tmp1.nc
    # CDO_REMAP_NORM=destarea cdo -L invertlat -setmisstoc,0 -remapycon,n128 -selindexbox,2,361,2,292 -mul tmp1.nc $mask $ofile
    log.info("Using the following cdo version for conservative remapping")
    os.system("cdo -V")
    os.system("cdo -L selvar," + nemo_var_name + " " + nemo_ifile + " " + interm_file)
    if target_grid_ == "T159":
        remap_grid = 'n80'
    elif target_grid_ == "T255":
        remap_grid = 'n128'
    else:
        log.error("WRONG GRID %s in function add_nemo_variable in lpjg2cmor.py!" % target_grid_)
        exit(-1)
    os.system(
        "CDO_REMAP_NORM=destarea cdo -L invertlat -setmisstoc,0 -remapycon," + remap_grid + " -selindexbox,2,361,2,292 -mul " + interm_file + " " + nemo_maskfile + " " + nemo_ofile)

    if not os.path.exists(nemo_ofile):
        log.error("There was a problem remapping %s variable in nemo output file %s needed for %s in table %s... "
                  % (nemo_var_name, nemo_ifile, task.target.variable, task.target.table))
        return False

    # add the nemo output to the lpjg output
    if os.path.exists(interm_file):
        os.remove(interm_file)
    os.system("cdo -L add -selvar," + task.target.variable + " " + ncfile + " " + nemo_ofile + " " + interm_file)
    if not os.path.exists(interm_file):
        log.error("There was a problem adding remapped %s variable from nemo output file %s to %s in table %s... "
                  % (nemo_var_name, nemo_ifile, task.target.variable, task.target.table))
        return False

    # overwrite final ncfile and cleanup
    os.remove(nemo_ofile)
    shutil.move(interm_file, ncfile)

    return True


# Extracts single column from the .out-file
def get_lpjg_datacolumn(df, freq, colname, months_as_cols):
    if freq == "day":
        # create a single time column so that extra days won't be added to 
        # the time axis (if there are both leap and non-leap years)
        # Time axis needs to be modified on first call 
        if "year" in list(df.columns.values):
            df['timecolumn'] = df['year'] + 0.001 * df['day']
            df.drop(columns=['year', 'day'], inplace=True)
            df.set_index('timecolumn', append=True, inplace=True)
        df = df[[colname]]
        df = df.unstack()

    elif freq.startswith("yr"):
        df = df.pop(colname)
        df = df.unstack()
    elif freq == "mon":
        if months_as_cols:
            df = df.unstack()
            df = df.reindex(sorted(df.columns, key=(lambda x: (x[1], _months.index(x[0])))),
                            axis=1, copy=False)
        else:
            df = df.pop(colname)
            df = df.unstack().unstack()
            df = df.reindex(sorted(df.columns, key=(lambda x: (x[1], x[0]))),
                            axis=1, copy=False)
    return df


# Performs CMORization of a single task/year
def execute_single_task(dataset, task):
    global log
    task.status = cmor_task.status_cmorizing
    lon_axis = [] if not hasattr(task, "longitude_axis") else [getattr(task, "longitude_axis")]
    lat_axis = [] if not hasattr(task, "latitude_axis") else [getattr(task, "latitude_axis")]
    t_axis = [] if not hasattr(task, "time_axis") else [getattr(task, "time_axis")]
    lu_axis = [] if not hasattr(task, "landUse_axis") else [getattr(task, "landUse_axis")]
    veg_axis = [] if not hasattr(task, "vegtype_axis") else [getattr(task, "vegtype_axis")]
    sdep_axis = [] if not hasattr(task, "sdepth_axis") else [getattr(task, "sdepth_axis")]

    # loop over potential singleton axes
    singleton_axis = []
    for ax in dir(task):
        if ax.startswith("singleton_"):
            singleton_axis += [getattr(task, ax)]

    axes = lon_axis + lat_axis + lu_axis + veg_axis + sdep_axis + t_axis + singleton_axis
    varid = create_cmor_variable(task, dataset, axes)

    ncvar = dataset.variables[task.target.out_name]
    missval = getattr(ncvar, "missing_value", getattr(ncvar, "fill_value", np.nan))

    factor = get_conversion_factor(getattr(task, cmor_task.conversion_key, None))
    log.info("CMORizing variable %s in table %s form %s in "
             "file %s..." % (task.target.out_name, task.target.table, task.source.variable(),
                             getattr(task, cmor_task.output_path_key)))
    cmor_utils.netcdf2cmor(varid, ncvar, 0, factor, missval=getattr(task.target, cmor_target.missval_key, missval),
                           swaplatlon=True)
    closed_file = cmor.close(varid, file_name=True)
    log.info("CMOR closed file %s" % closed_file)
    task.status = cmor_task.status_cmorized


# Creates cmor time axis for the variable
# The axis is created separately for each variable and each year
def create_time_axis(ds, task):
    # finding the time dimension name: adapted from nemo2cmor, presumably there is always only one time dimension and
    #  the length of the time_dim list will be 1
    tgtdims = getattr(task.target, cmor_target.dims_key)
    time_dim = [d for d in list(set(tgtdims.split())) if d.startswith("time")]

    timevals = ds.variables["time"][:]  # time variable in the netcdf-file from create_lpjg_netcdf is "time"
    # time requires bounds as well, the following should simply set them to be from start to end of each
    # year/month/day (as appropriate for current data)
    f = np.vectorize(lambda x: x + 1)
    time_bnd = np.stack((timevals, f(timevals)), axis=-1)

    tid = cmor.axis(table_entry=str(time_dim[0]), units=getattr(ds.variables["time"], "units"),
                    coord_vals=timevals, cell_bounds=time_bnd)
    setattr(task, "time_axis", tid)

    return


# Creates longitude and latitude cmor-axes for LPJ-Guess variables Seems this is enough for cmor according to the
# cmor documentation, and there is indeed no problem at least when passing the data through the CMORization functions
def create_grid(ds, task):
    lons = ds.variables["lon"][:]
    lats = ds.variables["lat"][:]

    # create the cell bounds since they are required: we have a 512x256 grid with longitude from 0 to 360 and
    # latitude from -90 to 90, i.e. resolution ~0.7 longitude values start from 0 so the cell lower bounds are the
    # same as lons (have to be: cmor requires monotonically increasing values so 359.X to 0.X is not allowed)
    lon_half_dists = np.insert(0.5 * (lons[1:] - lons[:-1]), 0, [0.5 * (lons[1] - lons[0])])
    lon_bnd = np.stack((lons[:] - lon_half_dists, lons[:] + lon_half_dists), axis=-1)

    # creating latitude bounds so that latitude values are the (approximate) mid-points of the cell lower and upper
    # bounds
    if target_grid_ == "T159":
        lat_bnd_lower = np.array([-90.0, -88.47338107])
        nsteps = 159
        step_length = 1.11991622
    elif target_grid_ == "T255":
        lat_bnd_lower = np.array([-90.0, -89.12264116])
        nsteps = 255
        step_length = 0.70175308
    for i in range(1, nsteps):
        lat_bnd_lower = np.append(lat_bnd_lower, lat_bnd_lower[i] + step_length)
    lat_bnd_upper = np.append(lat_bnd_lower[1:], 90.0)
    lat_bnd = np.stack((lat_bnd_lower, lat_bnd_upper), axis=-1)

    lon_id = cmor.axis(table_entry="longitude", units=getattr(ds.variables["lon"], "units"),
                       coord_vals=lons, cell_bounds=lon_bnd)
    lat_id = cmor.axis(table_entry="latitude", units=getattr(ds.variables["lat"], "units"),
                       coord_vals=lats, cell_bounds=lat_bnd)

    return lon_id, lat_id


# Unit conversion utility method (not really needed but carried over from nemo2cmor anyway)
def get_conversion_factor(conversion):
    global log
    if not conversion:
        return 1.0
    #   if conversion == "tossqfix":
    #       return 1.0
    if conversion == "frac2percent":
        return 100.0
    if conversion == "percent2frac":
        return 0.01
    log.error("Unknown explicit unit conversion %s will be ignored" % conversion)
    return 1.0


# Creates a variable in the cmor package
def create_cmor_variable(task, dataset, axes):
    srcvar = task.source.variable()
    unit = getattr(task.target, "units")
    if hasattr(task.target, "positive") and len(task.target.positive) != 0:
        return cmor.variable(table_entry=str(task.target.out_name), units=str(unit), axis_ids=axes,
                             original_name=str(srcvar), positive=task.target.positive)
    else:
        return cmor.variable(table_entry=str(task.target.out_name), units=str(unit), axis_ids=axes,
                             original_name=str(srcvar))


# Creates a cmor landUse axis
def create_landuse_axis(task, lpjgfile, freq):
    if landuse_requested_:
        landusevals = landuse_requested_
    else:
        with open(lpjgfile) as f:
            header = next(f).split()
            if freq.startswith("yr"):
                landusevals = header[3:]
            else:
                landusevals = header[4:]

    LU_id = cmor.axis(table_entry="landUse", units='none', coord_vals=landusevals)

    setattr(task, "landUse_axis", LU_id)
    return


# Creates a cmor vegtype axis
def create_vegtype_axis(task, lpjgfile, freq):
    with open(lpjgfile) as f:
        header = next(f).split()
        if freq.startswith("yr"):
            pfts = header[3:]
        else:
            pfts = header[4:]
    vegtypevals = pfts

    veg_id = cmor.axis(table_entry="vegtype", units='none', coord_vals=vegtypevals)

    setattr(task, "vegtype_axis", veg_id)
    return


# Creates a cmor sdepth axis
def create_sdepth_axis(task, lpjgfile, freq):
    log.info("Creating depth axis using file %s..." % lpjgfile)
    with open(lpjgfile) as f:
        header = next(f).split()
        if freq.startswith("yr"):
            depths = header[3:]
        else:
            depths = header[4:]
    sdepthvals = np.array([float(d) for d in depths])

    sdepth_bnd_lower = np.append(0, sdepthvals[:-1])
    sdepth_bnd = np.stack((sdepth_bnd_lower, sdepthvals), axis=-1)

    sdep_id = cmor.axis(table_entry="sdepth", units='m', coord_vals=sdepthvals,
                        cell_bounds=sdepth_bnd)

    setattr(task, "sdepth_axis", sdep_id)
    return


# Creates a cmor singleton depth axis
def create_singleton_axis(task, lpjgfile, lpjgcol, singleton_value):
    log.info("Creating singleton axis for %s using file %s..." % (lpjgcol, lpjgfile))

    axis_name = "singleton_" + lpjgcol + "_axis"
    single_id = cmor.axis(table_entry=lpjgcol, units='none', coord_vals=[singleton_value])

    setattr(task, axis_name, single_id)
    return
