from builtins import str
import logging
import unittest
from testfixtures import LogCapture

from ece2cmor3.cmor_source import ifs_source, netcdf_source, grib_code

logging.basicConfig(level=logging.DEBUG)


class cmor_source_tests(unittest.TestCase):

    @staticmethod
    def test_default_ifs_source():
        src = ifs_source(None)
        assert src.grid() is None
        assert src.get_grib_code() is None
        assert not any(src.get_root_codes())

    @staticmethod
    def test_surface_pressure():
        code = grib_code(134, 128)
        assert code in ifs_source.grib_codes_2D_dyn

    @staticmethod
    def test_specific_humidity():
        code = grib_code(135, 128)
        src = ifs_source(code)
        assert src.grid() == "spec"
        assert src.spatial_dims == 3

    @staticmethod
    def test_snow_depth():
        code = grib_code(141, 128)
        src = ifs_source(code)
        assert src.grid() == "point"
        assert src.spatial_dims == 2

    @staticmethod
    def test_create_from_ints():
        src = ifs_source.create(133, 128)
        assert src.get_grib_code() == grib_code(133, 128)

    @staticmethod
    def test_create_from_string():
        src = ifs_source.read("133.128")
        assert src.get_grib_code() == grib_code(133, 128)

    @staticmethod
    def test_create_from_short_string():
        src = ifs_source.read("133")
        assert src.get_grib_code() == grib_code(133, 128)

    @staticmethod
    def test_create_from_short_string_masked():
        src = ifs_source.read("133", mask_expr="var172<=0.5")
        assert set(src.get_root_codes()) == {grib_code(133, 128), grib_code(172, 128)}

    @staticmethod
    def test_create_from_var_string():
        src = ifs_source.read("var133")
        assert src.get_grib_code() == grib_code(133, 128)

    @staticmethod
    def test_create_from_var_string_masked():
        src = ifs_source.read("var133", mask_expr="var172<=0.5")
        assert set(src.get_root_codes()) == {grib_code(133, 128), grib_code(172, 128)}

    @staticmethod
    def test_create_from_expr():
        src = ifs_source.read("88.128", "sqrt(sq(var165)+sq(var166))")
        assert src.get_grib_code() == grib_code(88, 128)
        assert set(src.get_root_codes()) == {grib_code(165, 128), grib_code(166, 128)}
        assert getattr(src, "expr") == "var88=sqrt(sq(var165)+sq(var166))"
        assert src.grid() == "point"
        assert src.spatial_dims == 2

    @staticmethod
    def test_create_from_expr2():
        src = ifs_source.read("var88", "sqrt(sq(var131)+sq(var132))")
        assert src.get_grib_code() == grib_code(88, 128)
        assert set(src.get_root_codes()) == {grib_code(131, 128), grib_code(132, 128)}
        assert getattr(src, "expr") == "var88=sqrt(sq(var131)+sq(var132))"
        assert src.grid() == "spec"
        assert src.spatial_dims == 3

    @staticmethod
    def test_create_from_expr3():
        src = ifs_source.read("var88", "sqrt(sq(var128131)+sq(var128132))")
        assert src.get_grib_code() == grib_code(88, 128)
        assert set(src.get_root_codes()) == {grib_code(131, 128), grib_code(132, 128)}
        assert getattr(src, "expr") == "var88=sqrt(sq(var131)+sq(var132))"
        assert src.grid() == "spec"
        assert src.spatial_dims == 3

    @staticmethod
    def test_create_from_expr4():
        src = ifs_source.read("var129124", "var126094 + var126099 + var126106 + var126110")
        assert src.get_grib_code() == grib_code(124, 129)
        assert set(src.get_root_codes()) == {grib_code(94, 126), grib_code(99, 126), grib_code(106, 126),
                                             grib_code(110, 126)}
        assert getattr(src, "expr") == "var124=var94+var99+var106+var110"
        assert src.grid() == "point"
        assert src.spatial_dims == 3

    @staticmethod
    def test_create_from_expr5():
        src = ifs_source.read("88", "var88=sqrt(sq(var131)+sq(var132))")
        assert src.get_grib_code() == grib_code(88, 128)
        assert set(src.get_root_codes()) == {grib_code(131, 128), grib_code(132, 128)}
        assert getattr(src, "expr") == "var88=sqrt(sq(var131)+sq(var132))"
        assert src.grid() == "spec"
        assert src.spatial_dims == 3

    @staticmethod
    def test_create_from_expr6():
        src = ifs_source.read("88", "(var144==0)*sqrt(sq(var131)+sq(var132))")
        assert src.get_grib_code() == grib_code(88, 128)
        assert set(src.get_root_codes()) == {grib_code(144, 128), grib_code(131, 128), grib_code(132, 128)}
        assert getattr(src, "expr") == "var88=(var144==0)*sqrt(sq(var131)+sq(var132))"
        assert src.spatial_dims == 3

    @staticmethod
    def test_create_from_expr_masked():
        src = ifs_source.read("88", "(var144==0)*sqrt(sq(var131)+sq(var132))", mask_expr="var172>0.5")
        assert src.get_grib_code() == grib_code(88, 128)
        assert set(src.get_root_codes()) == {grib_code(144, 128), grib_code(131, 128), grib_code(132, 128),
                                             grib_code(172, 128)}
        assert getattr(src, "expr") == "var88=(var144==0)*sqrt(sq(var131)+sq(var132))"
        assert src.spatial_dims == 3

    @staticmethod
    def test_invalid_expression1():
        with LogCapture() as logc:
            ifs_source.read("141.128", "sqrt(sq(var165)+sq(var166))")
            assert "cmor_source ERROR" in str(logc)

    @staticmethod
    def test_invalid_expression2():
        with LogCapture() as logc:
            ifs_source.read("89.128", "sqrt(sq(var88)+sq(var166))")
            assert "cmor_source ERROR" in str(logc)

    @staticmethod
    def test_create_netcdf_source():
        src = netcdf_source("tos", "nemo")
        assert src.variable() == "tos"
        assert src.model_component() == "nemo"
