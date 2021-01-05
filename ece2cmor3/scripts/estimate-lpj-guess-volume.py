#!/usr/bin/env python

# Call this script e.g. by:
#  ./estimate-lpj-guess-volume.py --drq cmip6-data-request/cmip6-data-request-m=CMIP-e=CMIP-t=1-p=1/cmvme_CMIP_piControl_1_1.xlsx
#  ./estimate-lpj-guess-volume.py --drq cmip6-data-request/cmip6-data-request-m=LS3MIP-e=land-hist-t=1-p=1/cmvme_LS3MIP_land-hist_1_1.xlsx
#
# This script estimates the volume of the output from LPJ-GUESS for one MIP experiment.
#
# This script is part of the subpackage genecec (GENerate EC-Eearth Control output files)
# which is part of ece2cmor3.
#
# Note that this script is called by the script:
#  genecec-per-mip-experiment.sh
#

from __future__ import print_function
import xml.etree.ElementTree as xmltree
import os.path                                                # for checking file or directory existence with: os.path.isfile or os.path.isdir
import sys                                                    # for aborting: sys.exit
from os.path import expanduser
import argparse
import logging

from ece2cmor3 import ece2cmorlib, taskloader, cmor_source, cmor_target, cmor_utils, components


# Logging configuration
logformat = "%(asctime)s %(levelname)s:%(name)s: %(message)s"
logdateformat = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.DEBUG, format=logformat, datefmt=logdateformat)

# Logger construction
log = logging.getLogger(__name__)


# Main program
def main():
    parser = argparse.ArgumentParser(description="Estimates the volume of the output from LPJ-GUESS for a given CMIP6 "
                                                 "data request for EC-Earth3")
    varsarg = parser.add_mutually_exclusive_group(required=True)
    varsarg.add_argument("--vars", metavar="FILE", type=str,
                         help="File (json) containing cmor variables per EC-Earth component")
    varsarg.add_argument("--drq", metavar="FILE", type=str,
                         help="File (json|f90 namelist|xlsx) containing cmor variables")
    parser.add_argument("--tabdir", metavar="DIR", type=str, default=ece2cmorlib.table_dir_default,
                        help="Cmorization table directory")
    parser.add_argument("--tabid", metavar="PREFIX", type=str, default=ece2cmorlib.prefix_default,
                        help="Cmorization table prefix string")

    args = parser.parse_args()

    print("")
    print("Running estimate-lpj-guess-volume.py with:")
    print("./estimate-lpj-guess-volume.py " + cmor_utils.ScriptUtils.get_drq_vars_options(args))
    print("")

    if args.vars is not None and not os.path.isfile(args.vars):
        log.fatal("Your variable list json file %s cannot be found." % args.vars)
        sys.exit(' Exiting estimate-lpj-guess-volume.')

    if args.drq is not None and not os.path.isfile(args.drq):
        log.fatal("Your data request file %s cannot be found." % args.drq)
        sys.exit(' Exiting estimate-lpj-guess-volume.')

    # Initialize ece2cmor:
    ece2cmorlib.initialize_without_cmor(ece2cmorlib.conf_path_default, mode=ece2cmorlib.PRESERVE, tabledir=args.tabdir,
                                        tableprefix=args.tabid)

    # Load only LPJ-GUESS variables as task targets:
    try:
        if getattr(args, "vars", None) is not None:
            taskloader.load_tasks(args.vars, active_components=["lpjg"])
        else:
            taskloader.load_tasks_from_drq(args.drq, active_components=["lpjg"], check_prefs=False)
    except taskloader.SwapDrqAndVarListException as e:
        log.error(e.message)
        opt1, opt2 = "vars" if e.reverse else "drq", "drq" if e.reverse else "vars"
        log.error("It seems you are using the --%s option where you should use the --%s option for this file"
                  % (opt1, opt2))
        sys.exit(' Exiting estimate-lpj-guess-volume.')

    print('\n Number of activated data request tasks is', len(ece2cmorlib.tasks), '\n')
        

    total_layer_equivalent= 0
    count = 0
    for task in ece2cmorlib.tasks:
      count = count + 1
      print(' {:15} {:8} {:15} {}'.format(task.target.variable, task.target.table, task.target.units, task.target.frequency))

      # LPJ-GUESS Volume estimate: estimate the number of 2D layers per variable in output due to the number of time steps per year:
      if task.target.frequency == 'yr':
       layer_number_due_to_freq = 1
      elif task.target.frequency == 'mon':
       layer_number_due_to_freq = 12
      elif task.target.frequency == 'day':
       layer_number_due_to_freq = 365
      elif task.target.frequency == '3hrPt':
       layer_number_due_to_freq = 365.25 * 8.
      elif task.target.frequency == 'fx':
       layer_number_due_to_freq = 0
      elif task.target.frequency == 'monC':
       layer_number_due_to_freq = 1./30.        # Number of climate points: 1 per 30 year?
      elif task.target.frequency == 'subhrPt':
      #layer_number_due_to_freq = 365.25 * 12.  # At least hourly, thus sofar under limit (Actually there should't be (sub) houry variables available?).
       layer_number_due_to_freq = 0             # Because there won't be any subhourly output from LPJ-GUESS.
      else:
       print('\n Unknown frequency in LPJ-GUESS Volume estimate for: ', task.target.variable, '\n')
       layer_number_due_to_freq = 0

      # LPJ-GUESS Volume estimate: estimate the number vertical layers per variable:
      zdim=getattr(task.target, "z_dims", [])
      if len(zdim) == 0:
       vertical_dim = 1
      else:
       if zdim[0] == 'vegtype':
        vertical_dim = 31
       elif zdim[0] == 'landuse':
        vertical_dim = 4
       elif zdim[0] == 'sdepth':
        vertical_dim = 2
       else:
        vertical_dim = 1

      # LPJ-GUESS Volume estimate: calculate the number of 2D layers in output due to the number of time steps & the number of vertical layers per year per variable:
      layers_per_var_per_yr = layer_number_due_to_freq * vertical_dim
      # LPJ-GUESS Volume estimate: and for all variables together:
      total_layer_equivalent = total_layer_equivalent + layers_per_var_per_yr
     #print(' {:3} varname: {:15} freq: {:5} table: {:7} zdim: {:30} vertical dim: {:3} {:2} {:8} layers per var per yr: {:8}'.format(count, task.target.variable, task.target.frequency, task.target.table, getattr(task.target, "z_dims", []), vertical_dim, len(zdim), layer_number_due_to_freq, layers_per_var_per_yr ))

    print('\n With a 2D layer equivalent of ', total_layer_equivalent, ' the LPJ-GUESS Volume estimate for this CMIP6 data request at T255 grid is ', total_layer_equivalent * 0.12 / 1000.0, ' GB per year\n')
    print(' The number of variables which is available from LPJ-GUESS in EC-Erth3 for this experiment is', count)

    volume_estimate = open('volume-estimate-lpj-guess.txt','w')
    volume_estimate.write(' \nEC-Earth3 LPJ-GUESS Volume estimates of generated output:{}'.format('\n'))
    volume_estimate.write('  Volume estimate for the LPJ-GUESS T255 grid: {} GB/yr{}'.format(total_layer_equivalent * 0.12 / 1000.0, '\n'))
    volume_estimate.write('  With {:8} horizontal data slices per year across the vertical and time dimension.{}'.format(int(total_layer_equivalent), '\n\n'))
    volume_estimate.close()


    # Finishing up
    ece2cmorlib.finalize_without_cmor()



if __name__ == "__main__":
    main()
