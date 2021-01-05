from __future__ import division
from past.utils import old_div
import datetime
import json
import logging
import math
import os
import shutil
import tempfile
import unittest

import cmor
import numpy

import test_utils
from ece2cmor3 import nemo2cmor, cmor_source, cmor_target, cmor_task, ece2cmorlib

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

outpath = os.path.join(os.getcwd(), "cmor")


def circwave(t, j, i):
    return 15 * math.cos((i * i + j * j) / 1000. + 0.1 * t)


def circwave3d(t, z, j, i):
    return 15 * math.cos((i * i + j * j) / 1000. + 0.1 * t) * (old_div(z, 12))


def hypwave(t, j, i):
    return 0.001 * math.sin((i * i - j * j) / 1000. + 0.1 * t)


def init_cmor():
    directory = os.path.join(os.path.dirname(cmor_target.__file__), "resources", "tables")
    cmor.setup(directory)
    conf_path = ece2cmorlib.conf_path_default
    with open(conf_path, 'r') as f:
        metadata = json.load(f)
    metadata["outpath"] = outpath
    with tempfile.NamedTemporaryFile("r+w", suffix=".json", delete=False) as tmp_file:
        json.dump(metadata, tmp_file)
    cmor.dataset_json(tmp_file.name)
    cmor.set_cur_dataset_attribute("calendar", "proleptic_gregorian")
    return directory


class nemo2cmor_tests(unittest.TestCase):

    def setUp(self):
        self.data_dir = os.path.join(os.path.dirname(__file__), "test_data", "nemodata")
        if os.path.exists(self.data_dir):
            return
        os.mkdir(self.data_dir)
        dimx, dimy, dimz = 20, 10, 3
        opf = test_utils.nemo_output_factory()
        opf.make_grid(dimx, dimy, "grid_U", dimz)
        opf.set_timeframe(datetime.date(1990, 1, 1), datetime.date(1991, 1, 1), "1d")
        uto = {"name": "uto",
               "dims": 2,
               "function": circwave,
               "standard_name": "temperature_transport_x",
               "long_name": "Product of x-ward sea water velocity and temperature",
               "units": "m degC s-1"}
        uso = {"name": "uso",
               "dims": 2,
               "function": hypwave,
               "standard_name": "salinity_transport_x",
               "long_name": "Product of x-ward sea water velocity and salinity",
               "units": "kg m-2 s-1"}
        opf.write_variables(self.data_dir, "expn", [uto, uso])

        opf.make_grid(dimx, dimy, "grid_V", dimz)
        opf.set_timeframe(datetime.date(1990, 1, 1), datetime.date(1991, 1, 1), "1d")
        vto = {"name": "vto",
               "dims": 2,
               "function": circwave,
               "standard_name": "temperature_transport_y",
               "long_name": "Product of y-ward sea water velocity and temperature",
               "units": "m degC s-1"}
        vso = {"name": "vso",
               "dims": 2,
               "function": hypwave,
               "standard_name": "salinity_transport_y",
               "long_name": "Product of y-ward sea water velocity and salinity",
               "units": "kg m-2 s-1"}
        opf.write_variables(self.data_dir, "expn", [vto, vso])

        opf.make_grid(dimx, dimy, "grid_T", dimz)
        opf.set_timeframe(datetime.date(1990, 1, 1), datetime.date(1991, 1, 1), "1m")
        tos = {"name": "tos",
               "dims": 2,
               "function": circwave,
               "standard_name": "sea_surface_temperature",
               "long_name": "Sea surface temperature",
               "units": "degC"}
        to = {"name": "to",
              "dims": 3,
              "function": circwave3d,
              "standard_name": "sea_water_temperature",
              "long_name": "Sea water temperature",
              "units": "degC"}
        sos = {"name": "sos",
               "dims": 2,
               "function": hypwave,
               "standard_name": "sea_surface_salinity",
               "long_name": "Sea surface salinity",
               "units": "kg m-3"}
        opf.write_variables(self.data_dir, "expn", [tos, to, sos])

        opf.make_grid(dimx, dimy, "icemod")
        opf.set_timeframe(datetime.date(1990, 1, 1), datetime.date(1991, 1, 1), "6h")
        sit = {"name": "sit", "dims": 2, "function": circwave, "standard_name": "sea_ice_temperature",
               "long_name": "Sea ice temperature", "units": "degC"}
        opf.write_variables(self.data_dir, "expn", [sit])

    def tearDown(self):
        if os.path.exists(outpath):
            try:
                shutil.rmtree(outpath)
            except Exception as e:
                log.warning("Attempt to remove cmorized test data failed, reason: %s" % e.message)
        if os.path.exists(self.data_dir):
            try:
                shutil.rmtree(self.data_dir)
            except Exception as e:
                log.warning("Attempt to remove generated test data failed, reason: %s" % e.message)

    def test_cmor_single_task(self):
        tab_dir = init_cmor()
        nemo2cmor.initialize(self.data_dir, "expn", os.path.join(tab_dir, "CMIP6"), datetime.datetime(1990, 3, 1),
                             testmode=True)
        src = cmor_source.netcdf_source("tos", "nemo")
        tgt = cmor_target.cmor_target("tos", "Omon")
        setattr(tgt, "frequency", "mon")
        setattr(tgt, "dimensions", "longitude latitude time")
        setattr(tgt, "time_operator", ["mean"])
        tgt.space_dims = {"latitude", "longitude"}
        tsk = cmor_task.cmor_task(src, tgt)
        nemo2cmor.execute([tsk])
        nemo2cmor.finalize()
        cmor.close()

    @staticmethod
    def test_create_grid():
        dim = 1000
        lons = numpy.fromfunction(lambda i, j: old_div((i * 360 + 0.5), (0.5 * (dim + j) + 2)), (dim, dim), dtype=numpy.float64)
        lats = numpy.fromfunction(lambda i, j: old_div((j * 180 + 0.5), (0.5 * (dim + i) + 2)) - 90, (dim, dim),
                                  dtype=numpy.float64)

        grid = nemo2cmor.nemo_grid("sum", lons, lats)

        p1 = (grid.vertex_lons[0, 0, 0], grid.vertex_lats[0, 0, 0])
        p2 = (grid.vertex_lons[0, 0, 1], grid.vertex_lats[0, 0, 1])
        p3 = (grid.vertex_lons[0, 0, 2], grid.vertex_lats[0, 0, 2])
        p4 = (grid.vertex_lons[0, 0, 3], grid.vertex_lats[0, 0, 3])

        assert p2[0] == p3[0]
        assert p1[1] == p2[1]
        assert p3[1] == p4[1]

    def test_init_nemo2cmor(self):
        tab_dir = init_cmor()
        nemo2cmor.initialize(self.data_dir, "expn", os.path.join(tab_dir, "CMIP6"), datetime.datetime(1990, 3, 1))
        nemo2cmor.finalize()
        cmor.close()

    def test_cmor_single_task3d(self):
        tab_dir = init_cmor()
        nemo2cmor.initialize(self.data_dir, "expn", os.path.join(tab_dir, "CMIP6"), datetime.datetime(1990, 3, 1),
                             testmode=True)
        src = cmor_source.netcdf_source("to", "nemo")
        tgt = cmor_target.cmor_target("thetao", "Omon")
        setattr(tgt, "frequency", "mon")
        setattr(tgt, "dimensions", "longitude latitude olevel time")
        setattr(tgt, "time_operator", ["mean"])
        tgt.space_dims = {"latitude", "longitude"}
        tsk = cmor_task.cmor_task(src, tgt)
        nemo2cmor.execute([tsk])
        nemo2cmor.finalize()
        cmor.close()

    @staticmethod
    def test_grid_types():
        assert nemo2cmor.get_grid_type("lim_grid_T_2D") == 't'
        assert nemo2cmor.get_grid_type("lim_grid_U_3D") == 'u'
        assert nemo2cmor.get_grid_type("lim_grid_V_2D") == 'v'
        assert nemo2cmor.get_grid_type("lim_grid_W_3D") == 't'
        assert nemo2cmor.get_grid_type("grid_U") == 'u'
        assert nemo2cmor.get_grid_type("opa_grid_ptr_T_3basin_2D") is None
        assert nemo2cmor.get_grid_type("lim_grid_T_3D_ncatice") == 't'
        assert nemo2cmor.get_grid_type("opa_vert_sum") == 't'
        assert nemo2cmor.get_grid_type("opa_zoom_700_sum") == 't'
