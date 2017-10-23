#!/usr/bin/env python

import sys
import os
import logging
import argparse
import json
from ece2cmor3 import ece2cmorlib,taskloader,cmor_source,cmor_utils

# Logging configuration
logging.basicConfig(level=logging.DEBUG)

# Logger construction
log = logging.getLogger(__name__)


# Converts the input fortran variable namelist file to json
def write_varlist(targets,opath):
    tgtgroups = cmor_utils.group(targets,lambda t:t.table)
    tgtdict = dict([k,[t.variable for t in v]] for k,v in tgtgroups.iteritems())
    with open(opath,'w') as ofile:
        json.dump(tgtdict,ofile,indent = 4,separators = (',', ': '))
    logging.info("File %s written" % opath)


# Main program
def main():

    parser = argparse.ArgumentParser(description = "Validate input variable list against CMIP tables")
    parser.add_argument("--vars",   metavar = "FILE",   type = str, required = True, help = "File (json|f90 namelist|xlsx) containing cmor variables")
    parser.add_argument("--tabdir", metavar = "DIR",    type = str, default = ece2cmorlib.table_dir_default, help = "Cmorization table directory")
    parser.add_argument("--tabid",  metavar = "PREFIX", type = str, default = ece2cmorlib.prefix_default, help = "Cmorization table prefix string")
    parser.add_argument("--output", metavar = "FILE",   type = str, default = None, help = "Output path to write variables to")
    parser.add_argument("-a", "--atm", action = "store_true", default = False, help = "Run exclusively for atmosphere variables")
    parser.add_argument("-o", "--oce", action = "store_true", default = False, help = "Run exclusively for ocean variables")

    args = parser.parse_args()

    # Initialize ece2cmor:
    ece2cmorlib.initialize(ece2cmorlib.conf_path_default,mode = ece2cmorlib.PRESERVE,tabledir = args.tabdir,tableprefix = args.tabid)

    # Fix conflicting flags
    procatmos,prococean = not args.oce,not args.atm
    if(not procatmos and not prococean):
        procatmos,prococean = True,True

    # Load the variables as task targets:
    loadedtargets,skippedtargets = taskloader.load_targets(args.vars,load_atm_tasks = procatmos,load_oce_tasks = prococean)

    if(args.output):
        ofile,fext = os.path.splitext(args.output)
        write_varlist(loadedtargets,ofile + ".json")
        write_varlist(skippedtargets,ofile + ".err.json" )

    # Finishing up
    ece2cmorlib.finalize()

if __name__ == "__main__":
    main()