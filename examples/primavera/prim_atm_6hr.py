#!/usr/bin/env python

import os
import sys
import logging
import ece2cmor
import ifs2cmor
import jsonloader
import cmor_source
import optparse
import datetime
from dateutil.relativedelta import relativedelta

# This example script performs cmorization of one month of atmosphere data, starting at \
# januari 1st 1990. It requires an output directory and an experiment name/prefix to \
# determine the output data files and configure \
# cmor3 correctly. The processed variables are listed in the "variables" dictionary

def is6hrtask(task):
   if(not isinstance(task.source,cmor_source.ifs_source)): return False
   if(task.target.variable in ["ua850","va850"]): return False
   if(getattr(task.target,"frequency",None) == "3hr"): return False
   return (task.source.spatial_dims == 3)

logging.basicConfig(level=logging.DEBUG)

startdate = datetime.date(1990,1,1)
interval = relativedelta(months=1)
curdir = os.path.dirname(os.path.abspath(__file__))

def main(args):

    parser = optparse.OptionParser()
    parser.add_option("-d","--dir" ,dest = "dir" ,help = "IFS output directory")
    parser.add_option("-e","--exp" ,dest = "exp" ,help = "Experiment name (prefix)")
    parser.add_option("-t","--tmp" ,dest = "temp" ,help = "Temporary working directory")
    (opt,args) = parser.parse_args()
    odir = os.path.abspath(opt.dir)
    if(not os.path.isdir(odir)): raise Exception("Nonexistent output directory given:",odir)

    # Initialize ece2cmor with metadata and experiment prefix:
    ece2cmor.initialize(os.path.join(curdir,"primavera.json"),opt.exp)

    # Set directory and time interval for cmorization step:
    ece2cmor.ifsdir = odir
    ece2cmor.startdate = startdate
    ece2cmor.interval = interval

    # Load the variables as task targets:
    jsonloader.load_targets(os.path.join(curdir,"varlist.json"))

    # Remove targets that are constructed from three-hourly data:
    ece2cmor.tasks = [t for t in ece2cmor.tasks if is6hrtask(t)]

    # Execute the cmorization:
    ece2cmor.perform_ifs_tasks(outputfreq = 6,tempdir = opt.temp,maxsizegb = 128,taskthreads = 16)

if __name__ == "__main__":
    main(sys.argv[1:])
