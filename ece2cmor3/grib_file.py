from builtins import next
from builtins import str
from builtins import object
import os
import csv
import subprocess

import gribapi

# Vertical axes codes
surface_level_code = 1
hybrid_level_code = 109
pressure_level_hPa_code = 100
pressure_level_Pa_code = 210
height_level_code = 105
depth_level_code = 111
pv_level_code = 117

# Key names
date_key = "dataDate"
time_key = "dataTime"
param_key = "indicatorOfParameter"
levtype_key = "indicatorOfTypeOfLevel"
table_key = "table2Version"
level_key = "level"

test_mode = False


# Module initializer function
def initialize():
    if not test_mode:
        orig_path = str(subprocess.check_output(["codes_info", "-d"]))
        ece_path = os.path.join(os.path.dirname(__file__), "resources", "grib-table")
        prepended_path = ":".join([ece_path, orig_path])
        os.environ["ECCODES_DEFINITION_PATH"] = prepended_path
        os.environ["GRIB_API_PYTHON_NO_TYPE_CHECKS"] = "1"


# Factory method
def create_grib_file(file_object_):
    if test_mode:
        return csv_grib_mock(file_object_)
    else:
        return ecmwf_grib_api(file_object_)


# Interface for grib file object
class grib_file(object):

    def __init__(self, file_object_):
        self.file_object = file_object_

    def read_next(self, headers_only=False):
        pass

    def write(self, file_object_):
        pass

    def set_field(self, name, value):
        pass

    def get_field(self, name):
        pass

    def release(self):
        pass

    def eof(self):
        pass


# ECMWF grib api implementation of grib file interface
class ecmwf_grib_api(grib_file):

    def __init__(self, file_object_):
        super(ecmwf_grib_api, self).__init__(file_object_)
        self.record = 0

    def read_next(self, headers_only=False):
        self.record = gribapi.grib_new_from_file(self.file_object, headers_only=headers_only)
        return self.record is not None

    def write(self, file_object_):
        gribapi.grib_write(self.record, file_object_)

    def set_field(self, name, value):
        gribapi.grib_set(self.record, name, value)

    def get_field(self, name):
        return gribapi.grib_get_long(self.record, name)

    def release(self):
        gribapi.grib_release(self.record)

    def eof(self):
        return self.record is None


# CSV header-only implementation of grib file interface for testing purposes
class csv_grib_mock(grib_file):
    columns = [date_key, time_key, param_key, levtype_key, level_key]

    def __init__(self, file_object_):
        super(csv_grib_mock, self).__init__(file_object_)
        self.row = []
        self.reader = csv.reader(file_object_, delimiter=',')

    def read_next(self, headers_only=False):
        self.row = next(self.reader, None)
        return self.row is not None

    def write(self, file_object_):
        writer = csv.writer(file_object_)
        writer.writerow(self.row)

    def set_field(self, name, value):
        if name == table_key:
            pass
        self.row[csv_grib_mock.columns.index(name)] = value

    def get_field(self, name):
        if name == table_key:
            return 128
        return int(self.row[csv_grib_mock.columns.index(name)])

    def release(self):
        self.row = []

    def eof(self):
        return self.row is None
