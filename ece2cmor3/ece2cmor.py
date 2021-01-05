#!/usr/bin/env python
import time

import argparse
import datetime
import dateutil.parser
import dateutil.relativedelta
import logging
import os
import sys

from ece2cmor3 import ece2cmorlib, taskloader, components, __version__, cmor_target, cmor_utils

# Logger object
log = logging.getLogger(__name__)


def main(args=None):
    if args is None:
        pass

    formatter = lambda prog: argparse.ArgumentDefaultsHelpFormatter(prog, max_help_position=30)

    parser = argparse.ArgumentParser(description="Post-processing and cmorization of EC-Earth output",
                                     formatter_class=formatter)
    required = parser.add_argument_group("required arguments")

    parser.add_argument("datadir", metavar="DIR", type=str, help="EC-Earth data directory, i.e. for a given component, "
                                                                 "for a given leg")
    parser.add_argument("--exp", metavar="EXPID", type=str, default="ECE3", help="Experiment prefix")
    varsarg = required.add_mutually_exclusive_group(required=True)
    varsarg.add_argument("--varlist", metavar="FILE", type=str,
                         help="File (json) containing cmor variables grouped per table, grouped per EC-Earth component")
    varsarg.add_argument("--drq", metavar="FILE", type=str,
                         help="File (json|f90 namelist|xlsx) containing cmor variables, grouped per table")
    required.add_argument("--meta", metavar="FILE.json", type=str, required=True, help="Input metadata file")
    parser.add_argument("--odir", metavar="DIR", type=str, default=None, help="Output directory, by default the "
                                                                              "metadata \'outpath\' entry")
    cmor_utils.ScriptUtils.add_model_exclusive_options(parser, "ece2cmor")
    parser.add_argument("--ececonf", metavar='|'.join(list(components.ece_configs.keys())), type=str,
                        help="EC-Earth configuration (only used with --drq option)")
    parser.add_argument("--refd", metavar="YYYY-mm-dd", type=str, default="1850-01-01",
                        help="Reference date for output time axes")
    parser.add_argument("--npp", metavar="N", type=int, default=8, help="Number of parallel tasks (only relevant for "
                                                                        "IFS cmorization")
    parser.add_argument("--log", action="store_true", default=False, help="Write to log file")
    parser.add_argument("--flatdir", action="store_true", default=False, help="Do not create sub-directories in "
                                                                                    "output folder")
    parser.add_argument("--tabledir", metavar="DIR", type=str, default=ece2cmorlib.table_dir_default,
                        help="Cmorization table directory")
    parser.add_argument("--tableprefix", metavar="PREFIX", type=str, default=ece2cmorlib.prefix_default,
                        help="Cmorization table prefix string")
    parser.add_argument("--tmpdir", metavar="DIR", type=str, default="/tmp/ece2cmor",
                        help="Temporary working directory")
    parser.add_argument("--overwritemode", metavar="MODE", type=str, default="preserve",
                        help="MODE:preserve|replace|append, CMOR netcdf overwrite mode",
                        choices=["preserve", "replace", "append"])
    parser.add_argument("--skip_alevel_vars", action="store_true", default=False, help="Prevent loading atmospheric "
                                                                                       "model-level variables")
    parser.add_argument("-V", "--version", action="version",
                        version="%(prog)s {version}".format(version=__version__.version))
    # Deprecated arguments, only for backward compatibility
    parser.add_argument("--ncdo", metavar="N", type=int, default=4, help=argparse.SUPPRESS)
    parser.add_argument("--nomask", action="store_true", default=False, help=argparse.SUPPRESS)
    parser.add_argument("--nofilter", action="store_true", default=False, help=argparse.SUPPRESS)
    parser.add_argument("--atm", action="store_true", default=False, help="Deprecated! Use --ifs instead")
    parser.add_argument("--oce", action="store_true", default=False, help="Deprecated! Use --nemo instead")
    parser.add_argument("--conf", action="store_true", help="Deprecated! Use --meta instead")
    parser.add_argument("--vars", action="store_true", help="Deprecated! Use --varlist instead")
    cmor_utils.ScriptUtils.add_model_tabfile_options(parser)

    args = parser.parse_args()

    cmor_utils.ScriptUtils.set_custom_tabfiles(args)

    logfile = None
    logformat = "%(asctime)s %(levelname)s:%(name)s: %(message)s"
    logdateformat = "%Y-%m-%d %H:%M:%S"
    if getattr(args, "log", False):
        dirs = os.path.abspath(args.datadir).split(os.sep)
        fname = '-'.join([args.exp] + dirs[-2:] + [time.strftime("%Y%m%d%H%M%S", time.gmtime())])
        logfile = '.'.join([fname, "log"])
        logging.basicConfig(filename=logfile, level=logging.DEBUG, format=logformat, datefmt=logdateformat)
    else:
        logging.basicConfig(level=logging.DEBUG, format=logformat, datefmt=logdateformat)

    if not os.path.isdir(args.datadir):
        log.fatal("Your data directory argument %s cannot be found." % args.datadir)
        sys.exit(' Exiting ece2cmor.')

    if args.varlist is not None and not os.path.isfile(args.varlist):
        log.fatal("Your variable list json file %s cannot be found." % args.varlist)
        sys.exit(' Exiting ece2cmor.')

    if args.drq is not None and not os.path.isfile(args.drq):
        log.fatal("Your data request file %s cannot be found." % args.drq)
        sys.exit(' Exiting ece2cmor.')

    if not os.path.isfile(args.meta):
        log.fatal("Your metadata file %s cannot be found." % args.meta)
        sys.exit(' Exiting ece2cmor.')

    modedict = {"preserve": ece2cmorlib.PRESERVE, "append": ece2cmorlib.APPEND, "replace": ece2cmorlib.REPLACE}

    # Initialize ece2cmor:
    ece2cmorlib.initialize(args.meta, mode=modedict[args.overwritemode], tabledir=args.tabledir,
                           tableprefix=args.tableprefix, outputdir=args.odir, logfile=logfile,
                           create_subdirs=(not args.flatdir))
    ece2cmorlib.enable_masks = not args.nomask
    ece2cmorlib.auto_filter = not args.nofilter

    active_components = cmor_utils.ScriptUtils.get_active_components(args, args.ececonf)

    filters = None
    if args.skip_alevel_vars:
        def ifs_model_level_variable(target):
            zaxis, levs = cmor_target.get_z_axis(target)
            return zaxis not in ["alevel", "alevhalf"]
        filters = {"model level": ifs_model_level_variable}
    try:
        if getattr(args, "varlist", None) is not None:
            taskloader.load_tasks(args.varlist, active_components=active_components, target_filters=filters,
                                  check_duplicates=True)
        else:
            taskloader.load_tasks_from_drq(args.drq, active_components=["ifs"], target_filters=filters,
                                           check_prefs=True)
    except taskloader.SwapDrqAndVarListException as e:
        log.error(e.message)
        opt1, opt2 = "vars" if e.reverse else "drq", "drq" if e.reverse else "vars"
        log.error("It seems you are using the --%s option where you should use the --%s option for this file"
                  % (opt1, opt2))
        sys.exit(' Exiting ece2cmor.')

    refdate = datetime.datetime.combine(dateutil.parser.parse(args.refd), datetime.datetime.min.time())

    if "ifs" in active_components:
        ece2cmorlib.perform_ifs_tasks(args.datadir, args.exp,
                                      refdate=refdate,
                                      tempdir=args.tmpdir,
                                      taskthreads=args.npp,
                                      cdothreads=args.ncdo)
    if "nemo" in active_components:
        ece2cmorlib.perform_nemo_tasks(args.datadir, args.exp, refdate)

    if "lpjg" in active_components:
        ece2cmorlib.perform_lpjg_tasks(args.datadir, args.tmpdir, args.exp, refdate)
    if "tm5" in active_components:
        ece2cmorlib.perform_tm5_tasks(args.datadir, args.tmpdir, args.exp, refdate)

#   if procNEWCOMPONENT in active_components:
#       ece2cmorlib.perform_NEWCOMPONENT_tasks(args.datadir, args.exp, refdate)

    ece2cmorlib.finalize()


if __name__ == "__main__":
    main()
