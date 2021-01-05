#!/usr/bin/env python

# Call this script e.g. by:
#  ./drq2varlist.py --drq cmip6-data-request/cmip6-data-request-m=CMIP-e=CMIP-t=1-p=1/cmvme_CMIP_piControl_1_1.xlsx --ececonf EC-EARTH-AOGCM
#  ./drq2varlist.py --drq ../resources/test-data-request/drqlist-nemo-all.json                                      --ececonf dummy
#  ./drq2varlist.py --drq cmip6-data-request/cmip6-data-request-m\=C4MIP.CDRMIP.CMIP.LUMIP.OMIP-e\=historical-t\=1-p\=1/cmvme_c4.cd.cm.lu.om_historical_1_1.xlsx --ececonf EC-EARTH-CC
# or for the special "test all" case by:
#  ./drq2varlist.py --allvars --ececonf EC-EARTH-AOGCM --varlist ece-cmip6-data-request-varlist-all-EC-EARTH-AOGCM.json
#  ./drq2varlist.py --allvars --ececonf EC-EARTH-CC    --varlist ece-cmip6-data-request-varlist-all-EC-EARTH-CC.json
#
# This script converts the drq produced xlsx cmip6 data request file to an ec-earth json cmip6 data request file. In 
# the created ec-earth cmip6 data request json file the ec-earth ignored fields are omitted and the preferences are 
# applied based on the EC-Earth3 model configuration which is taken into consideration.
#
# This script is part of the subpackage genecec (GENerate EC-Eearth Control output files)
# which is part of ece2cmor3.
#
# Note that this script is called by the script:
#  genecec-per-mip-experiment.sh
#
from __future__ import print_function
import os
import sys

import argparse
import logging
import json

from ece2cmor3 import ece2cmorlib, components, taskloader, cmor_utils

# Logging configuration
logformat = "%(asctime)s %(levelname)s:%(name)s: %(message)s"
logdateformat = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.DEBUG, format=logformat, datefmt=logdateformat)
log = logging.getLogger(__name__)


def main():
    formatter = lambda prog: argparse.ArgumentDefaultsHelpFormatter(prog, max_help_position=37)
    parser = argparse.ArgumentParser(description="Create component-specified varlist json for given data request", formatter_class=formatter)
    required = parser.add_argument_group("required arguments")
    varsarg = required.add_mutually_exclusive_group(required=True)
    varsarg.add_argument("--drq", metavar="FILE", type=str,
                        help="File (xlsx|json) containing requested cmor variables (Required, unless --allvars is used)")
    varsarg.add_argument("--allvars", action="store_true", default=False,
                        help="Read all possible variables from CMOR tables (Required, unless --drq is used)")
    parser.add_argument("--ececonf", metavar='|'.join(list(components.ece_configs.keys())), type=str,
                        help="EC-Earth configuration")
    parser.add_argument("--varlist", "-o", metavar="FILE.json", type=str, default="ece-cmip6-data-request-varlist.json",
                        help="Output file name")
    parser.add_argument("--tabdir", metavar="DIR", type=str, default=ece2cmorlib.table_dir_default,
                        help="Cmorization table directory")
    parser.add_argument("--tabid", metavar="PREFIX", type=str, default=ece2cmorlib.prefix_default,
                        help="Cmorization table prefix string")

    args = parser.parse_args()

    print("")
    print("Running drq2varlist.py with:")
    print("./drq2varlist.py " + cmor_utils.ScriptUtils.get_drq_vars_options(args))
    print("")

    if not args.allvars and not os.path.isfile(args.drq):
        log.fatal("Your data request file %s cannot be found." % args.drq)
        sys.exit(' Exiting drq2varlist.')

    # Initialize ece2cmor:
    ece2cmorlib.initialize_without_cmor(tabledir=args.tabdir, tableprefix=args.tabid)

    try:
        if getattr(args, "allvars", False):
            matches, omitted = taskloader.load_drq("allvars", config=args.ececonf, check_prefs=True)
        else:
            matches, omitted = taskloader.load_drq(args.drq, config=args.ececonf, check_prefs=True)
            # Here we load extra permanent tasks for LPJ-GUESS because the LPJ_GUESS community likes to output these variables at any time independent wheter they are requested by the data request:
            if args.ececonf in ["EC-EARTH-CC", "EC-EARTH-Veg", "EC-EARTH-Veg-LR"]:
               matches_permanent, omitted_permanent = taskloader.load_drq(os.path.join(os.path.dirname(__file__), "..", "resources", "permanent-tasks.json"), config=args.ececonf, check_prefs=True)
               for model, targetlist in list(matches_permanent.items()):
                   if model in matches:
                      for target in targetlist:
                         if target not in matches[model]:
                            matches[model].append(target)
                   else:
                      matches[model] = targetlist
    except taskloader.SwapDrqAndVarListException as e:
        log.error(e.message)
        opt1, opt2 = "vars" if e.reverse else "drq", "drq" if e.reverse else "vars"
        log.error("It seems you are using the --%s option where you should use the --%s option for this file"
                  % (opt1, opt2))
        sys.exit(' Exiting drq2varlist.')

    result = {}
    for model, targetlist in list(matches.items()):
        result[model] = {}
        for target in targetlist:
            table = target.table

            # Taking off several variables from the json data request files:
            skip_case = False
            if target.variable in ['intdoc']:
             # See issue #521:
             log.info(" Variable %s %s is listed in the omit list of drq2varlist and therefore skipped. See https://github.com/EC-Earth/ece2cmor3/issues/521" % (target.table, target.variable))
             skip_case = True
            if target.variable in ['rlntds', 'hfibthermds', 'hflso', 'agessc', 'ficeberg', 'hfsso', 'hfcorr', 'wfcorr', 'nwdFracLut']:
             # See issue #498 & #469:
             log.info(" Variable %s %s is listed in the omit list of drq2varlist and therefore skipped. See https://github.com/EC-Earth/ece2cmor3/issues/498 & https://github.com/EC-Earth/ece2cmor3/issues/469" % (target.table, target.variable))
             skip_case = True
            if target.variable in ['hfibthermds2d', 'ficeberg2d', 'fgcfc12']:
             # See issue #516 and #609-36 & #609-37 at ece-portal:
             log.info(" Variable %s %s is listed in the omit list of drq2varlist and therefore skipped. See https://github.com/EC-Earth/ece2cmor3/issues/516 & https://dev.ec-earth.org/issues/609#note-36" % (target.table, target.variable))
             skip_case = True
            if target.variable in ['cfc11', 'fgsf6']:
             # See issue #504:
             log.info(" Variable %s %s is listed in the omit list of drq2varlist and therefore skipped. See https://github.com/EC-Earth/ece2cmor3/issues/504" % (target.table, target.variable))
             skip_case = True
            if table in ['Oyr'] and target.variable in ['cfc11', 'ocontempdiff', 'ocontemppadvect', 'ocontemppmdiff', 'ocontemprmadvect', 'ocontemptend', 'osaltdiff', 'osaltpadvect', 'osaltpmdiff', 'osaltrmadvect', 'osalttend']:
             # See issue #493 & #542:
             log.info(" Variable %s %s is listed in the omit list of drq2varlist and therefore skipped. See https://github.com/EC-Earth/ece2cmor3/issues/493 & https://github.com/EC-Earth/ece2cmor3/issues/542" % (target.table, target.variable))
             skip_case = True
            if getattr(args, "allvars", True):
             if table in ['6hrPlevPt'] and target.variable in ['ta27', 'hus27']:
              # See issue #542:
              # Conflicting combinations (skip the 2nd one, an arbitrary choice):
              # 6hrPlevPt:  ta7h,  ta27
              # 6hrPlevPt: hus7h, hus27
              log.info(" Variable %s %s is listed in the omit list of drq2varlist and therefore skipped. See https://github.com/EC-Earth/ece2cmor3/issues/542" % (target.table, target.variable))
              skip_case = True
             if table in ['Emon'] and target.variable in ['hus27', 'va27', 'ua27']:
              # See issue #542:
              # Emon:        hus, hus27
              # Emon:         va,  va27
              # Emon:         ua,  ua27
              log.info(" Variable %s %s is listed in the omit list of drq2varlist and therefore skipped. See https://github.com/EC-Earth/ece2cmor3/issues/542" % (target.table, target.variable))
              skip_case = True

            if skip_case is False:
             if table in result[model]:
                 result[model][table].append(target.variable)
             else:
                 result[model][table] = [target.variable]
    with open(args.varlist, 'w') as ofile:
        json.dump(result, ofile, indent=4, separators=(',', ': '), sort_keys=True)
        ofile.write('\n')  # Add newline at the end of the json file because the python json package doesn't do this.
        ofile.close()


if __name__ == "__main__":
    main()
