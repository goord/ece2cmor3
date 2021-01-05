#!/usr/bin/env python

# Call this script by:
#  ./check-for-obsolete-cmor-variables-in-json-file.py

import sys
import os
import logging
import argparse
import json
from ece2cmor3 import ece2cmorlib, taskloader, cmor_source, cmor_utils, components

# Logging configuration
logformat = "%(asctime)s %(levelname)s:%(name)s: %(message)s"
logdateformat = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.DEBUG, format=logformat, datefmt=logdateformat)

# Logger construction
log = logging.getLogger(__name__)


def check_obsolete(fname):
    f = open(fname).read()
    data = json.loads(f)
    for d in data:
        tgt = d.get("target", None)
        if not tgt: continue
        tgtlist = [tgt]
        if isinstance(tgt, list):
            tgtlist = tgt
        for tvar in tgtlist:
            if tvar not in [t.variable for t in ece2cmorlib.targets]:
                if tvar in ["rsscsaf", "rssaf", "rlscsaf", "rlsaf"]:
                 log.info("Non-cmor target found (see #575) in %s: %s" % (fname, tvar))
                else:
                 log.info("Obsolete target found in %s: %s" % (fname, tvar))
    log.info("\n")


# Main program
def main():
    parser = argparse.ArgumentParser(description="Check for obsolete cmor variables in json file")
    parser.add_argument("--tabdir", metavar="DIR", type=str, default=ece2cmorlib.table_dir_default,
                        help="Cmorization table directory")
    parser.add_argument("--tabid", metavar="PREFIX", type=str, default=ece2cmorlib.prefix_default,
                        help="Cmorization table prefix string")
    parser.add_argument("--output", metavar="FILE", type=str, default=None, help="Output path to write variables to")
    cmor_utils.ScriptUtils.add_model_exclusive_options(parser, "checkvars")

    args = parser.parse_args()

    # Initialize ece2cmor:
    ece2cmorlib.initialize_without_cmor(ece2cmorlib.conf_path_default, mode=ece2cmorlib.PRESERVE, tabledir=args.tabdir,
                                        tableprefix=args.tabid)

    active_components = cmor_utils.ScriptUtils.get_active_components(args)

    for model in list(components.models.keys()):
        if model in active_components:
            check_obsolete(components.models[model][components.table_file])

    # Finishing up
    ece2cmorlib.finalize_without_cmor()


if __name__ == "__main__":
    main()
