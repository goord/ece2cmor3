from builtins import str
from builtins import object
import json
import logging
import os
import re

from ece2cmor3 import cmor_utils

# Logger instance.
log = logging.getLogger(__name__)


# Base class for cmor source objects, which represent variables produced by a model
class cmor_source(object):

    def __init__(self):
        pass

    def variable(self):
        pass

    def model_component(self):
        pass


# Creates an ece2cmor task source from the input dictionary
def create_cmor_source(attributes, component):
    result = None
    src = attributes.get("source", None)
    if component == "ifs":
        expr = attributes.get("expr", None)
        if src is None and expr is None:
            log.error(
                "Could not find an IFS source or expression entry within attributes %s" % (str(attributes.__dict__)))
            return None
        result = ifs_source.read(src, expr, mask_expr=attributes.get(mask_expression_key, None),
                                 expr_order=int(attributes.get("expr_order", "0")))
    if component == "nemo":
        if src is None:
            log.error("Could not find a NEMO source variable within attributes %s" % (str(attributes.__dict__)))
        result = netcdf_source(src, component)
    if component == "lpjg":
        if src is None:
            log.error("Could not find a LPJG source variable within attributes %s" % (str(attributes.__dict__)))
        result = lpjg_source(src)
    if component == "tm5":
        if src is None:
            log.error("Could not find a TM5 source variable within attributes %s" % (str(attributes.__dict__)))
        result = tm5_source(src)
    # if component == NEWCOMPONENT:
    # create some source here, if NEWCOMPONENT has nc files as output, the NEMO case can be copied
    return result


# NetCDF cmor source
class netcdf_source(cmor_source):

    def __init__(self, variable, component):
        super(netcdf_source, self).__init__()
        self.variable_ = variable
        self.component_ = component

    def variable(self):
        return self.variable_

    def model_component(self):
        return self.component_


# ECMWF grib code object
class grib_code(object):
    def __init__(self, var_id_, tab_id_=128):
        self.var_id = var_id_
        self.tab_id = tab_id_

    def __eq__(self, other):
        return self.var_id == other.var_id and self.tab_id == other.tab_id

    def __str__(self):
        return str(self.var_id) + '.' + str(self.tab_id)

    def __hash__(self):
        return self.var_id + self.tab_id * 1000

    @classmethod
    def read(cls, istr):
        s = istr[3:] if istr.startswith("var") else istr
        string_pair = s.split('.')
        if len(string_pair) == 1:
            code_string = string_pair[0]
            if len(code_string) > 3:
                vid, tid = int(code_string[3:]), int(code_string[:3])
            else:
                vid, tid = int(code_string), 128
        elif len(string_pair) == 2:
            vid, tid = int(string_pair[0]), int(string_pair[1])
        else:
            raise Exception("Invalid input string for grib code:", istr)
        cls = grib_code(vid, tid)
        return cls

    @staticmethod
    def to_cdo_str(c):
        if c.tab_id == 128:
            return "var" + str(c.var_id)
        return "var" + str(c.__hash__())


# Reads a group of grib codes from a json-file
def read_grib_codes_group(file, key):
    s = open(file).read()
    data = json.loads(s)
    if key in data:
        return [grib_code.read(s) for s in data[key]]
    else:
        return []


ifs_grid = cmor_utils.cmor_enum(["point", "spec"])
expression_key = "expr"
expression_order_key = "expr_order"
mask_expression_key = "mask_expr"


# IFS source subclass, constructed from a given grib code.
class ifs_source(cmor_source):
    # Existing grib code lists, read from resources.
    grib_codes_file = os.path.join(os.path.dirname(__file__), "resources/grib_codes.json")
    grib_codes_3D = read_grib_codes_group(grib_codes_file, "MFP3D")
    grib_codes_2D_dyn = read_grib_codes_group(grib_codes_file, "MFP2DF")
    grib_codes_2D_phy = read_grib_codes_group(grib_codes_file, "MFPPHY")
    grib_codes_extra = read_grib_codes_group(grib_codes_file, "NVEXTRAGB")
    grib_codes_sh = read_grib_codes_group(grib_codes_file, "ICMSH")
    grib_codes_accum = read_grib_codes_group(grib_codes_file, "ACCUMFLD")
    grib_codes_min = read_grib_codes_group(grib_codes_file, "MINFLD")
    grib_codes_max = read_grib_codes_group(grib_codes_file, "MAXFLD")
    grib_codes_fx = read_grib_codes_group(grib_codes_file, "FXFLD")
    grib_codes = grib_codes_3D + grib_codes_2D_dyn + grib_codes_2D_phy + grib_codes_extra

    # Constructor.
    def __init__(self, code):
        super(ifs_source, self).__init__()
        global log
        if not code:
            self.code_ = None
            self.spatial_dims = -1
            self.grid_ = -1
        else:
            self.code_ = code
            self.spatial_dims = -1
            self.grid_ = ifs_grid.spec if code in ifs_source.grib_codes_sh else ifs_grid.point
            self.spatial_dims = 3 if code in (ifs_source.grib_codes_3D + ifs_source.grib_codes_2D_dyn) else 2

    # Returns the model component.
    def model_component(self):
        return "ifs"

    def variable(self):
        return str(self.code_)

    # Returns the grid.
    def grid(self):
        return ifs_grid[self.grid_] if self.grid_ >= 0 else None

    # Returns the grid id.
    def grid_id(self):
        return self.grid_

    # Returns the grib code.
    def get_grib_code(self):
        return grib_code(self.code_.var_id, self.code_.tab_id) if self.code_ else None

    # Returns the argument grib codes in case of a post-processing expression variable.
    def get_root_codes(self):
        if hasattr(self, "root_codes"):
            return [grib_code(c.var_id, c.tab_id) for c in getattr(self, "root_codes")]
        else:
            return [self.get_grib_code()] if self.code_ else []

    # Creates an instance from the input string s.
    @classmethod
    def read(cls, s, expr=None, mask_expr=None, expr_order=0):
        global log
        gc = grib_code.read(s)
        cls = ifs_source(gc)
        if expr is not None:
            if gc in ifs_source.grib_codes:
                log.error("Expression %s assigned to reserved existing grib code %s, skipping expression assignment"
                          % (expr, str(gc)))
            else:
                # Remove whitespace
                expr_string = expr.replace(" ", "")
                # Find all variable strings
                varstrs = re.findall("var[0-9]{1,3}(?![0-9])", expr_string) + re.findall("var[0-9]{6}(?![0-9])",
                                                                                         expr_string)
                # Split into LHS and RHS
                groups = re.search("^var([0-9]{1,3}|[0-9]{6})\=(?!\=)", expr_string)

                # Remove LHS if present
                if groups is not None:
                    log.warning("Ignoring left-hand side assignment in expression %s" % expr)
                    varstrs.remove(groups.group(0)[:-1])
                    expr_string = expr_string[len(groups.group(0)):]

                # Remove leading zeros
                expr_string = re.sub("var[0-9]{6}", lambda o: "var" + o.group(0)[-3:].lstrip('0'), expr_string)

                # Add LHS again
                expr_string = '='.join(["var" + str(gc.var_id), expr_string])

                # Collect root codes
                root_codes = []
                for varstr in varstrs:
                    code = grib_code.read(varstr)
                    if code not in ifs_source.grib_codes:
                        log.error("Unknown grib code %s in expression %s found" % (str(code), expr))
                    if code not in root_codes:
                        root_codes.append(code)

                num_sp_codes = len([c for c in root_codes if c in ifs_source.grib_codes_sh])
                if num_sp_codes != 0 and num_sp_codes != len(root_codes):
                    log.error("Invalid combination of gridpoint and spectral variables in expression %s" % expr)

                cls.grid_ = ifs_grid.spec if all(
                    [c in ifs_source.grib_codes_sh for c in root_codes]) else ifs_grid.point
                cls.spatial_dims = 3 if any([c in ifs_source.grib_codes_3D for c in root_codes]) else 2
                setattr(cls, "root_codes", root_codes)
                setattr(cls, expression_key, expr_string)
                setattr(cls, expression_order_key, expr_order)
        if mask_expr is not None:
            setattr(cls, mask_expression_key, mask_expr)
            varstrs = re.findall("var[0-9]{1,3}(?![0-9])", mask_expr) + re.findall("var[0-9]{6}(?![0-9])", mask_expr)
            # Collect root codes
            root_codes = getattr(cls, "root_codes", [cls.get_grib_code()])
            for varstr in varstrs:
                code = grib_code.read(varstr)
                if code not in ifs_source.grib_codes:
                    log.error("Unknown grib code %s in expression %s found" % (str(code), mask_expr))
                if code not in root_codes:
                    root_codes.append(code)
            setattr(cls, "root_codes", root_codes)
        return cls

    # Creates in instance from the input codes.
    @classmethod
    def create(cls, vid, tid=128):
        cls = ifs_source(grib_code(vid, tid))
        return cls


# LPJ-Guess source subclass
class lpjg_source(cmor_source):

    def __init__(self, colname):
        super(lpjg_source, self).__init__()
        self.colname_ = colname

    def model_component(self):
        return "lpjg"

    def variable(self):
        return self.colname_


# LTM5 source subclass
class tm5_source(cmor_source):

    def __init__(self, colname):
        super(tm5_source, self).__init__()
        self.colname_ = colname

    def model_component(self):
        return "tm5"

    def variable(self):
        return self.colname_
