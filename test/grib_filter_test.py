import logging
import os
import unittest
from datetime import datetime

import pytest

from ece2cmor3 import grib_filter, grib_file, cmor_source, ece2cmorlib, cmor_task, cmor_target

logging.basicConfig(level=logging.DEBUG)

test_data_path = os.path.join(os.path.dirname(__file__), "test_data", "ifs", "001")
tmp_path = os.path.join(os.path.dirname(__file__), "tmp")


class grib_filter_test(unittest.TestCase):
    test_mode = True
    date = datetime(year=1990, month=1, day=1, hour=1)
    gg_file = "ICMGGECE3+199001.csv" if test_mode else "ICMGGECE3+199001"
    gg_path = {date: os.path.join(test_data_path, gg_file)}
    sh_file = "ICMSHECE3+199001.csv" if test_mode else "ICMSHECE3+199001"
    sh_path = {date: os.path.join(test_data_path, sh_file)}
    grib_file.test_mode = test_mode
    if not os.path.exists(tmp_path):
        os.makedirs(tmp_path)

    @staticmethod
    def test_initialize():
        grib_filter.initialize(grib_filter_test.gg_path, grib_filter_test.sh_path, tmp_path)
        assert grib_filter.varsfreq[(133, 128, grib_file.hybrid_level_code, 9, cmor_source.ifs_grid.point)] == 6
        assert grib_filter.varsfreq[
                   (133, 128, grib_file.pressure_level_Pa_code, 85000, cmor_source.ifs_grid.point)] == 6
        assert grib_filter.varsfreq[(164, 128, grib_file.surface_level_code, 0, cmor_source.ifs_grid.point)] == 3

    @staticmethod
    def test_validate_tasks():
        grib_filter.initialize(grib_filter_test.gg_path, grib_filter_test.sh_path, tmp_path)
        ece2cmorlib.initialize()
        tgt1 = ece2cmorlib.get_cmor_target("clwvi", "CFday")
        src1 = cmor_source.ifs_source.read("79.128")
        tsk1 = cmor_task.cmor_task(src1, tgt1)
        tgt2 = ece2cmorlib.get_cmor_target("ua", "Amon")
        src2 = cmor_source.ifs_source.read("131.128")
        tsk2 = cmor_task.cmor_task(src2, tgt2)
        valid_tasks, varstasks = grib_filter.validate_tasks([tsk1, tsk2])
        assert valid_tasks == [tsk1, tsk2]
        key1 = (79, 128, grib_file.surface_level_code, 0, cmor_source.ifs_grid.point)
        key2 = (131, 128, grib_file.pressure_level_Pa_code, 92500, cmor_source.ifs_grid.spec)
        assert varstasks[key1] == [tsk1]
        assert varstasks[key2] == [tsk2]
        ltype, plevs = cmor_target.get_z_axis(tgt2)
        levs = sorted([float(p) for p in plevs])
        levcheck = sorted([k[3] for k in varstasks if k[0] == 131])
        assert levs == levcheck

    @staticmethod
    def test_surf_var():
        grib_filter.initialize(grib_filter_test.gg_path, grib_filter_test.sh_path, tmp_path)
        ece2cmorlib.initialize()
        tgt = ece2cmorlib.get_cmor_target("clwvi", "CFday")
        src = cmor_source.ifs_source.read("79.128")
        tsk = cmor_task.cmor_task(src, tgt)
        grib_filter.execute([tsk])
        filepath = os.path.join(tmp_path, "79.128.1.3")
        assert os.path.isfile(filepath)
        assert getattr(tsk, cmor_task.filter_output_key) == [filepath]
        with open(filepath) as fin:
            reader = grib_file.create_grib_file(fin)
            date, time = 0, 0
            while reader.read_next():
                param = reader.get_field(grib_file.param_key)
                assert param == 79
                newdate = reader.get_field(grib_file.date_key)
                if date != 0 and newdate != date:
                    assert newdate == date + 1
                    date = newdate
                newtime = reader.get_field(grib_file.time_key)
                assert newtime == (time + 300) % 2400
                time = newtime
        os.remove(filepath)

    @staticmethod
    def test_expr_var():
        grib_filter.initialize(grib_filter_test.gg_path, grib_filter_test.sh_path, tmp_path)
        ece2cmorlib.initialize()
        tgt = ece2cmorlib.get_cmor_target("sfcWind", "Amon")
        src = cmor_source.ifs_source.read("214.128", "sqrt(sqr(var165)+sqr(var166))")
        tsk = cmor_task.cmor_task(src, tgt)
        grib_filter.execute([tsk])
        filepath1 = os.path.join(tmp_path, "166.128.105_165.128.105.3")
        filepath2 = os.path.join(tmp_path, "165.128.105_166.128.105.3")
        assert os.path.isfile(filepath1) or os.path.isfile(filepath2)
        assert getattr(tsk, cmor_task.filter_output_key) in ([filepath1], [filepath2])
        filepath = getattr(tsk, cmor_task.filter_output_key)[0]
        with open(filepath) as fin:
            reader = grib_file.create_grib_file(fin)
            date, time = 0, 0
            while reader.read_next():
                param = reader.get_field(grib_file.param_key)
                assert param in [165, 166]
                newdate = reader.get_field(grib_file.date_key)
                if date != 0 and newdate != date:
                    assert newdate == date + 1
                    date = newdate
                newtime = reader.get_field(grib_file.time_key)
                if newtime != time:
                    assert newtime == (time + 300) % 2400
                    time = newtime
        os.remove(filepath)

    @staticmethod
    def test_pressure_var():
        grib_filter.initialize(grib_filter_test.gg_path, grib_filter_test.sh_path, tmp_path)
        ece2cmorlib.initialize()
        tgt = ece2cmorlib.get_cmor_target("ua", "Amon")
        src = cmor_source.ifs_source.read("131.128")
        tsk = cmor_task.cmor_task(src, tgt)
        grib_filter.execute([tsk])
        filepath = os.path.join(tmp_path, "131.128.210.6")
        assert os.path.isfile(filepath)
        assert getattr(tsk, cmor_task.filter_output_key), [filepath]
        with open(filepath) as fin:
            reader = grib_file.create_grib_file(fin)
            date, time = 0, 0
            while reader.read_next():
                param = reader.get_field(grib_file.param_key)
                assert param == 131
                newdate = reader.get_field(grib_file.date_key)
                if date != 0 and newdate != date:
                    assert newdate == date + 1
                    date = newdate
                newtime = reader.get_field(grib_file.time_key)
                if newtime != time:
                    assert newtime == (time + 600) % 2400
                    time = newtime
        os.remove(filepath)

    @staticmethod
    def test_prev_month_find():
        exp = "pmt1"
        fnames = ["ICM" + t + exp + "+" + dt for t in ["GG", "SH"] for dt in ["000000", "185001", "184912"]]
        path1 = os.path.join(tmp_path, "prev_mon_test_src", "001")
        if not os.path.exists(path1):
            os.makedirs(path1)
        for fname in fnames:
            open(os.path.join(path1, fname), 'a').close()
        path2 = os.path.join(tmp_path, "prev_mon_test_dst")
        if not os.path.exists(path2):
            os.makedirs(path2)
        for fname in fnames:
            if not os.path.exists(os.path.join(path2, fname)):
                os.symlink(os.path.join(path1, fname), os.path.join(path2, fname))
        inifile = grib_filter.get_prev_file(os.path.join(path2, "ICMGG" + exp + "+185001"))
        assert inifile in [os.path.join(path2, "ICMGG" + exp + "+184912"),
                           os.path.join(path1, "ICMGG" + exp + "+184912")]
        for fname in fnames:
            os.unlink(os.path.join(path2, fname))
            os.remove(os.path.join(path1, fname))
        os.rmdir(path1)
        os.rmdir(os.path.join(tmp_path, "prev_mon_test_src"))
        os.rmdir(path2)

    @staticmethod
    def test_ini_month_find():
        exp = "pmt2"
        fnames = ["ICM" + t + exp + "+" + dt for t in ["GG", "SH"] for dt in ["000000", "185001"]]
        path1 = os.path.join(tmp_path, "prev_mon_test_src", "001")
        if not os.path.exists(path1):
            os.makedirs(path1)
        for fname in fnames:
            open(os.path.join(path1, fname), 'a').close()
        path2 = os.path.join(tmp_path, "prev_mon_test_dst", "001")
        if not os.path.exists(path2):
            os.makedirs(path2)
        for fname in fnames:
            if not os.path.exists(os.path.join(path2, fname)):
                os.symlink(os.path.join(path1, fname), os.path.join(path2, fname))
        inifile = grib_filter.get_prev_file(os.path.join(path2, "ICMGG" + exp + "+185001"))
        assert inifile == os.path.join(path2, "ICMGG" + exp + "+000000")
        for fname in fnames:
            os.unlink(os.path.join(path2, fname))
            os.remove(os.path.join(path1, fname))
        os.rmdir(path1)
        os.rmdir(os.path.join(tmp_path, "prev_mon_test_src"))
        os.rmdir(path2)
        os.rmdir(os.path.join(tmp_path, "prev_mon_test_dst"))
