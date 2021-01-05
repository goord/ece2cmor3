from builtins import str
from builtins import range
import datetime

import cmor
import dateutil
import logging
import netCDF4
import numpy
import os
import unittest

from ece2cmor3 import ifs2cmor, ece2cmorlib

logging.basicConfig(level=logging.DEBUG)

calendar_ = "proleptic_gregorian"


def write_postproc_timestamps(filename, startdate, refdate, interval, offset=0):
    path = os.path.join(ifs2cmor.temp_dir_, filename)
    root = netCDF4.Dataset(path, "w")
    times = []
    time = startdate + interval * offset
    while time.year == startdate.year:
        times.append(time)
        time += interval
    root.createDimension("time", len(times))
    time_variable = root.createVariable("Time", "f8", dimensions=("time",))
    units = "hours since %s" % str(refdate)
    setattr(time_variable, "units", units)
    setattr(time_variable, "calendar", calendar_)
    time_variable[:] = netCDF4.date2num(times, units=units, calendar=calendar_)
    return root, len(times)


class ifs2cmor_tests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = "/tmp/ece2cmor3/ifs2cmor_test"
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
        self.startdate = datetime.datetime(1950, 1, 1)
        self.refdate = datetime.datetime(1850, 1, 1)
        ece2cmorlib.initialize()
        cmor.set_cur_dataset_attribute("calendar", calendar_)

    def test_monthly_time_axis(self):
        ifs2cmor.temp_dir_ = self.temp_dir
        ifs2cmor.ref_date_ = self.refdate
        ifs2cmor.start_date_ = self.startdate
        interval = dateutil.relativedelta.relativedelta(months=1)
        ncroot, numtimes = write_postproc_timestamps("rsds_Amon.nc", self.startdate, self.refdate, interval)
        ncvar = ncroot.createVariable("rsds", "f8", dimensions=("time",))
        ncvar[:] = numpy.full((numtimes,), -1.23)
        filepath = ncroot.filepath()
        ncroot.close()
        cmor.load_table("CMIP6_Amon.json")
        axisid, lower_bnds, upper_bnds = ifs2cmor.create_time_axis(freq="mon", path=filepath, name="time",
                                                                   has_bounds=True)
        assert lower_bnds == [self.startdate + n * interval for n in range(0, 12)]
        assert upper_bnds == [self.startdate + n * interval for n in range(1, 13)]
        os.remove(filepath)

    def test_daily_time_axis(self):
        ifs2cmor.temp_dir_ = self.temp_dir
        ifs2cmor.ref_date_ = self.refdate
        ifs2cmor.start_date_ = self.startdate
        interval = dateutil.relativedelta.relativedelta(days=1)
        ncroot, numtimes = write_postproc_timestamps("rsds_day.nc", self.startdate, self.refdate, interval)
        ncvar = ncroot.createVariable("rsds", "f8", dimensions=("time",))
        ncvar[:] = numpy.full((numtimes,), -1.23)
        filepath = ncroot.filepath()
        ncroot.close()
        cmor.load_table("CMIP6_day.json")
        axisid, lower_bnds, upper_bnds = ifs2cmor.create_time_axis(freq="day", path=filepath, name="time",
                                                                   has_bounds=True)
        assert lower_bnds == [self.startdate + n * interval for n in range(0, 365)]
        assert upper_bnds == [self.startdate + n * interval for n in range(1, 366)]
        os.remove(filepath)

    def test_6hr_time_axis(self):
        ifs2cmor.temp_dir_ = self.temp_dir
        ifs2cmor.ref_date_ = self.refdate
        ifs2cmor.start_date_ = self.startdate
        interval = dateutil.relativedelta.relativedelta(hours=6)
        ncroot, numtimes = write_postproc_timestamps("bs550aer_6hr.nc", self.startdate, self.refdate, interval)
        ncvar = ncroot.createVariable("bs550aer", "f8", dimensions=("time",))
        ncvar[:] = numpy.full((numtimes,), -1.23)
        filepath = ncroot.filepath()
        ncroot.close()
        cmor.load_table("CMIP6_6hrLev.json")
        axisid, lower_bnds, upper_bnds = ifs2cmor.create_time_axis(freq="6hr", path=filepath, name="time",
                                                                   has_bounds=True)
        assert lower_bnds == [self.startdate + n * interval for n in range(0, 4 * 365)]
        assert upper_bnds == [self.startdate + n * interval for n in range(1, 4 * 365 + 1)]
        os.remove(filepath)

    def test_3hr_time_axis(self):
        ifs2cmor.temp_dir_ = self.temp_dir
        ifs2cmor.ref_date_ = self.refdate
        ifs2cmor.start_date_ = self.startdate
        interval = dateutil.relativedelta.relativedelta(hours=3)
        ncroot, numtimes = write_postproc_timestamps("rsds_3hr.nc", self.startdate, self.refdate, interval)
        ncvar = ncroot.createVariable("rsds", "f8", dimensions=("time",))
        ncvar[:] = numpy.full((numtimes,), -1.23)
        filepath = ncroot.filepath()
        ncroot.close()
        cmor.load_table("CMIP6_3hr.json")
        axisid, lower_bnds, upper_bnds = ifs2cmor.create_time_axis(freq="3hr", path=filepath, name="time",
                                                                   has_bounds=True)
        assert lower_bnds == [self.startdate + n * interval for n in range(0, 8 * 365)]
        assert upper_bnds == [self.startdate + n * interval for n in range(1, 8 * 365 + 1)]
        os.remove(filepath)

    def test_6hrPt_time_axis(self):
        ifs2cmor.temp_dir_ = self.temp_dir
        ifs2cmor.ref_date_ = self.refdate
        ifs2cmor.start_date_ = self.startdate
        interval = dateutil.relativedelta.relativedelta(hours=6)
        ncroot, numtimes = write_postproc_timestamps("ta_6hrPlevPt.nc", self.startdate, self.refdate, interval)
        ncvar = ncroot.createVariable("ta", "f8", dimensions=("time",))
        ncvar[:] = numpy.full((numtimes,), 273.2)
        filepath = ncroot.filepath()
        ncroot.close()
        cmor.load_table("CMIP6_6hrPlevPt.json")
        axisid, lower_bnds, upper_bnds = ifs2cmor.create_time_axis(freq="6hrPt", path=filepath, name="time1",
                                                                   has_bounds=False)
        assert lower_bnds == [self.startdate + n * interval for n in range(0, 4 * 365)]
        assert upper_bnds == lower_bnds
        os.remove(filepath)
