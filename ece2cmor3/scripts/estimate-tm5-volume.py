#!/usr/bin/env python

# Call this script e.g. by:
#  ./estimate-tm5-volume.py --drq cmip6-data-request/cmip6-data-request-m=CMIP-e=CMIP-t=1-p=1/cmvme_CMIP_piControl_1_1.xlsx
#  ./estimate-tm5-volume.py --drq cmip6-data-request/cmip6-data-request-m=AerChemMIP-e=CMIP-t=1-p=1/cmvme_AerChemMIP_amip_1_1.xlsx
#  ./estimate-tm5-volume.py --drq cmip6-data-request/cmip6-data-request-m=AerChemMIP-e=hist-1950HC-t=1-p=1/cmvme_AerChemMIP_hist-1950HC_1_1.xlsx
#
# This script estimates the volume of the output from TM5 for one MIP experiment.
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

from ece2cmor3 import ece2cmorlib, taskloader, cmor_utils

# Logging configuration
logformat = "%(asctime)s %(levelname)s:%(name)s: %(message)s"
logdateformat = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.DEBUG, format=logformat, datefmt=logdateformat)

# Logger construction
log = logging.getLogger(__name__)


# Main program
def main():
    parser = argparse.ArgumentParser(description="Estimates the volume of the output from TM5 for a given CMIP6 data "
                                                 "request for EC-Earth3")
    varsarg = parser.add_mutually_exclusive_group(required=True)
    varsarg.add_argument("--vars", metavar="FILE", type=str,
                         help="File (json) containing cmor variables per EC-Earth component")
    varsarg.add_argument("--drq", metavar="FILE", type=str,
                         help="File (json|f90 namelist|xlsx) containing cmor variables")
    parser.add_argument("--tabdir", metavar="DIR", type=str, default=ece2cmorlib.table_dir_default,
                        help="Cmorization table directory")
    parser.add_argument("--tabid", metavar="PREFIX", type=str, default=ece2cmorlib.prefix_default,
                        help="Cmorization table prefix string")
    parser.add_argument("--short", action="store_true", default=False, help="Leave out the tasklist")
    
    args = parser.parse_args()

    print("")
    print("Running estimate-tm5-volume.py with:")
    print("./estimate-tm5-volume.py " + cmor_utils.ScriptUtils.get_drq_vars_options(args))
    print("")

    if args.vars is not None and not os.path.isfile(args.vars):
        log.fatal("Your variable list json file %s cannot be found." % args.vars)
        sys.exit(' Exiting estimate-tm5-volume.')

    if args.drq is not None and not os.path.isfile(args.drq):
        log.fatal("Your data request file %s cannot be found." % args.drq)
        sys.exit(' Exiting estimate-tm5-volume.')

    # Initialize ece2cmor:
    ece2cmorlib.initialize_without_cmor(ece2cmorlib.conf_path_default, mode=ece2cmorlib.PRESERVE, tabledir=args.tabdir,
                                        tableprefix=args.tabid)

    # Load only TM5 variables as task targets:
    try:
        if getattr(args, "vars", None) is not None:
            taskloader.load_tasks(args.vars, active_components=["tm5"])
        else:
            taskloader.load_tasks_from_drq(args.drq, active_components=["tm5"], check_prefs=False)
    except taskloader.SwapDrqAndVarListException as e:
        log.error(e.message)
        opt1, opt2 = "vars" if e.reverse else "drq", "drq" if e.reverse else "vars"
        log.error("It seems you are using the --%s option where you should use the --%s option for this file"
                  % (opt1, opt2))
        sys.exit(' Exiting estimate-tm5-volume.')

    for task in ece2cmorlib.tasks:
         print(' {:15} {:9} {:15} {}'.format(task.target.variable, task.target.table, task.target.units, task.target.frequency))
        #print task.target.__dict__

    print(' Number of activated data request tasks is', len(ece2cmorlib.tasks))
        

    total_layer_equivalent = 0
    count = 0
    per_freq = {}
    task_per_freq = {}
    for task in ece2cmorlib.tasks:
      count = count + 1
      if not getattr(args,'short',False):
        print(' {:15} {:9} {:15} {}'.format(task.target.variable, task.target.table, task.target.units, task.target.frequency))

      if task.target.table not in task_per_freq.keys():
        task_per_freq[task.target.table] = 0
      if task.target.table not in per_freq.keys():
        per_freq[task.target.table] = 0

      # TM5 Volume estimate: estimate the number of 2D layers per variable in output due to the number of time steps per year:
      if task.target.frequency == 'yr':
       layer_number_due_to_freq = 1.
      elif task.target.frequency == 'mon':
       layer_number_due_to_freq = 12.
      elif task.target.frequency == 'day':
       layer_number_due_to_freq = 365.
      elif task.target.frequency == '3hrPt':
       layer_number_due_to_freq = 0.
      elif task.target.frequency == '6hrPt':
       layer_number_due_to_freq = 365.25 * 4.
      elif task.target.frequency == '1hr':
       layer_number_due_to_freq = 365.25 * 24.
      elif task.target.frequency == 'fx':
       layer_number_due_to_freq = 0.
      elif task.target.frequency == 'monC':
       layer_number_due_to_freq = 1.0 / 30.0    # Number of climate points: 1 per 30 year?
      elif task.target.frequency == 'subhrPt':
      #layer_number_due_to_freq = 365.25 * 12.  # At least hourly, thus sofar under limit (Actually there should't be (sub) houry variables available?).
       layer_number_due_to_freq = 0.            # Because there won't be any subhourly output from TM5.
      else:
       print('\n Unknown frequency in TM5  Volume estimate for: {:15} at table: {:9} with frequency: {}\n'.format(task.target.variable, task.target.table, task.target.frequency))
       layer_number_due_to_freq = 0.

      if task.target.table == 'Emon':
       layer_number_due_to_freq = 0.

      # TM5 Volume estimate: estimate the number vertical layers per variable:
      zdim=getattr(task.target, "z_dims", [])
      if len(zdim) == 0:
       vertical_dim = 1.
      else:
       if zdim[0] == 'alevel':
        vertical_dim = 35. #34 + 1 for ps
       elif zdim[0] == 'alevhalf':
        vertical_dim = 36. # 34 + 1 for ps
       elif zdim[0] == 'plev39':
        vertical_dim = 39.
       elif zdim[0] == 'plev19':
        vertical_dim = 19.
       else:
        vertical_dim = 1.

      task_per_freq[task.target.table] = task_per_freq[task.target.table]+1
      # TM5 Volume estimate: calculate the number of 2D layers in output due to the number of time steps & the number of vertical layers per year per variable:
      layers_per_var_per_yr = layer_number_due_to_freq * vertical_dim
      if task.target.table =='AERmonZ':
        per_freq[task.target.table] = per_freq[task.target.table] + layers_per_var_per_yr / 120.0
        # TM5 Volume estimate: and for all variables together:
        total_layer_equivalent = total_layer_equivalent + layers_per_var_per_yr / 120.0
      else:
        per_freq[task.target.table] = per_freq[task.target.table] + layers_per_var_per_yr
        # TM5 Volume estimate: and for all variables together:
        total_layer_equivalent = total_layer_equivalent + layers_per_var_per_yr
    #print(' {:3} varname: {:15} freq: {:5} table: {:7} zdim: {:30} vertical dim: {:3} {:2} {:8} layers per var per yr: {:8}'.format(count, task.target.variable, task.target.frequency, task.target.table, getattr(task.target, "z_dims", []), vertical_dim, len(zdim), layer_number_due_to_freq, layers_per_var_per_yr ))

    print('\n With a 2D layer equivalent of ', total_layer_equivalent, ' the TM5 Volume estimate for this CMIP6 data request is ', total_layer_equivalent * 0.04 / 1000.0, ' GB per year\n')
    print(' The number of variables which is available from TM5 in EC-Erth3 for this experiment is', count)
    for i in per_freq:
      #if i =='AERmonZ':
      #  print 'Table: {} \tsize: {} GB/yr'.format(i,per_freq[i]*0.04/1000/120)
      #else:
      print('Table: {} \t tasks {} \tsize: {} GB/yr'.format(i,task_per_freq[i], per_freq[i] * 0.04 / 1024.0))
    volume_estimate = open('volume-estimate-tm5.txt','w')
    volume_estimate.write(' \nEC-Earth3 TM5 Volume estimates of generated output:{}'.format('\n'))
    volume_estimate.write('  Volume estimate for the TM5 3x2 degrees grid: {} GB/yr{}'.format(total_layer_equivalent * 0.04 / 1000.0, '\n'))
    volume_estimate.write('  With {:8} horizontal data slices per year across the vertical and time dimension.{}'.format(int(total_layer_equivalent), '\n\n'))
    volume_estimate.close()


    # Finishing up
    ece2cmorlib.finalize_without_cmor()



if __name__ == "__main__":
    main()
