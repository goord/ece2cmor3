from builtins import str
import logging
import os
import requests

import netCDF4
import numpy

# Logger object
log = logging.getLogger(__name__)

orca1_grid_shape = (292, 362)
orca025_grid_shape = (1050, 1442)

cached_vertices = {}


def load_vertices_from_file(gridtype, shape):
    global cached_vertices
    gridchar = gridtype
    if shape == orca1_grid_shape:
        mesh = "ORCA1"
    elif shape == orca025_grid_shape:
        mesh = "ORCA025"
    else:
        log.fatal("Unsupported grid resolution for NEMO: %s" % str(shape))
        return None, None
    if (mesh, gridchar) in list(cached_vertices.keys()):
        return cached_vertices[(mesh, gridchar)][0], cached_vertices[(mesh, gridchar)][1]
    file_name = '-'.join(["nemo", "vertices", mesh, gridchar, "grid"]) + ".nc"
    fullpath = os.path.join(os.path.dirname(__file__), "resources", "nemo-vertices", file_name)
    if not os.path.isfile(fullpath):
        if not get_from_b2share(file_name, fullpath):
            log.fatal("The file %s could not be downloaded, please install manually at %s" % (file_name, fullpath))
            return None, None
    nemo_vertices_file_name = os.path.join("ece2cmor3/resources/nemo-vertices/", fullpath)
    nemo_vertices_netcdf_file = netCDF4.Dataset(nemo_vertices_file_name, 'r')
    lon_vertices_raw = numpy.array(nemo_vertices_netcdf_file.variables["vertices_longitude"][...], copy=True)
    lat_vertices = numpy.array(nemo_vertices_netcdf_file.variables["vertices_latitude"][...], copy=True)
    nemo_vertices_netcdf_file.close()
    lon_vertices = numpy.where(lon_vertices_raw < 0, lon_vertices_raw + 360., lon_vertices_raw)
    cached_vertices[(mesh, gridchar)] = (lon_vertices, lat_vertices)
    return lon_vertices, lat_vertices


def get_from_b2share(fname, fullpath):
    site = "https://b2share.eudat.eu/api"
    record = "3ad7d5c5f1ab419297c1e02bded8d70f"
    resp = requests.get('/'.join([site, "records", record]))
    if not resp:
        log.error("Problem getting record data from b2share server: %d" % resp.status_code)
        return False
    d = resp.json()
    for f in d["files"]:
        if f["key"] == fname:
            url = '/'.join([site, "files", f["bucket"], f["key"]])
            log.info("Downloading file %s from b2share archive..." % fname)
            fresp = requests.get(url)
            if not fresp:
                log.error("Problem getting file %s from b2share server: %d" % (fname, resp.status_code))
                return False
            with open(fullpath, 'wb') as fd:
                fd.write(fresp.content)
            log.info("...success, file %s created" % fullpath)
    return True
