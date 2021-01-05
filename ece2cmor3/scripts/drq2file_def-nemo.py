#!/usr/bin/env python

# Call this script e.g. by:
#  ./drq2file_def-nemo.py --drq cmip6-data-request/cmip6-data-request-m=CMIP-e=CMIP-t=1-p=1/cmvme_CMIP_piControl_1_1.xlsx
#
# With this script it is possible to generate the EC-Earth3 NEMO control output files, i.e.
# the NEMO xml files for XIOS (the file_def files for OPA, LIM and PISCES) for one MIP experiment.
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
import re                                                     # for regular expressions

from ece2cmor3 import ece2cmorlib, taskloader, cmor_source, cmor_target, cmor_utils, components

basic_file_def_file_name          = "./xios-nemo-file_def-files/basic-cmip6-file_def_nemo.xml"
file_def_file_name                = "./xios-nemo-file_def-files/cmip6-file_def_nemo.xml"
file_def_opa_file_name            = "./xios-nemo-file_def-files/file_def_nemo-opa.xml"
file_def_lim_file_name            = "./xios-nemo-file_def-files/file_def_nemo-lim3.xml"
file_def_pisces_file_name         = "./xios-nemo-file_def-files/file_def_nemo-pisces.xml"
file_def_opa_file_name_compact    = "./xios-nemo-file_def-files/file_def_nemo-opa-compact.xml"
file_def_lim_file_name_compact    = "./xios-nemo-file_def-files/file_def_nemo-lim3-compact.xml"
file_def_pisces_file_name_compact = "./xios-nemo-file_def-files/file_def_nemo-pisces-compact.xml"

# Logging configuration
logformat = "%(asctime)s %(levelname)s:%(name)s: %(message)s"
logdateformat = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.DEBUG, format=logformat, datefmt=logdateformat)

# Logger construction
log = logging.getLogger(__name__)


# Main program
def main():
    parser = argparse.ArgumentParser(description="Create NEMO XIOS file_def input files for a given CMIP6 data request")
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
    print("Running drq2ppt.py with:")
    print("./drq2file_def-nemo.py " + cmor_utils.ScriptUtils.get_drq_vars_options(args))
    print("")

    if args.vars is not None and not os.path.isfile(args.vars):
        log.fatal("Your variable list json file %s cannot be found." % args.vars)
        sys.exit(' Exiting drq2file_def-nemo.')

    if args.drq is not None and not os.path.isfile(args.drq):
        log.fatal("Your data request file %s cannot be found." % args.drq)
        sys.exit(' Exiting drq2file_def-nemo.')

    # Initialize ece2cmor:
    ece2cmorlib.initialize_without_cmor(ece2cmorlib.conf_path_default, mode=ece2cmorlib.PRESERVE, tabledir=args.tabdir,
                                        tableprefix=args.tabid)

    # Load only ocean variables as task targets:
    try:
        if getattr(args, "vars", None) is not None:
            taskloader.load_tasks(args.vars, active_components=["nemo"])
        else:
            taskloader.load_tasks_from_drq(args.drq, active_components=["nemo"], check_prefs=False)
    except taskloader.SwapDrqAndVarListException as e:
        log.error(e.message)
        opt1, opt2 = "vars" if e.reverse else "drq", "drq" if e.reverse else "vars"
        log.error("It seems you are using the --%s option where you should use the --%s option for this file"
                  % (opt1, opt2))
        sys.exit(' Exiting drq2file_def-nemo.')

    for task in ece2cmorlib.tasks:
         print(' {:15} {:9} {:15} {}'.format(task.target.variable, task.target.table, task.target.units, task.target.frequency))
        #print task.target.__dict__

    print(' Number of activated data request tasks is', len(ece2cmorlib.tasks))
        

    # READING THE BASIC FILE_DEF FILE:
    if os.path.isfile(basic_file_def_file_name) == False: print(' The file ', basic_file_def_file_name, '  does not exist.'); sys.exit(' stop')

    tree_basic_file_def             = xmltree.parse(basic_file_def_file_name)
    root_basic_file_def             = tree_basic_file_def.getroot()                        # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements
   #field_elements_basic_file_def   = root_basic_file_def[0][:]

    total_layer_equivalent= 0
    count = 0
    for field in root_basic_file_def.findall('.//field[@id]'):
     for task in ece2cmorlib.tasks:
      if field.attrib["name"] == task.target.variable and field.attrib["table"] == task.target.table:
       field.attrib["enabled"] = "True"
       count = count + 1
      #print field.attrib["name"], field.attrib["table"]

       # NEMO Volume estimate: estimate the number of 2D layers per variable in output due to the number of time steps per year:
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
       else:
        print('\n Unknown frequency in NEMO Volume estimate for: {:15} at table: {:9} with frequency: {}\n'.format(task.target.variable, task.target.table, task.target.frequency))
        layer_number_due_to_freq = 0

       # NEMO Volume estimate: estimate the number vertical layers per variable:
       zdim=getattr(task.target, "z_dims", [])
       if len(zdim) == 0:
        vertical_dim = 1
       else:
        if zdim[0] == 'olevel':
         vertical_dim = 75
       #elif zdim[0] == 'typesea':
       #elif zdim[0] == 'depth100m':
       #elif zdim[0] == 'depth0m':
        else:
         vertical_dim = 1
        
       # NEMO Volume estimate: calculate the number of 2D layers in output due to the number of time steps & the number of vertical layers per year per variable:
       layers_per_var_per_yr = layer_number_due_to_freq * vertical_dim
       # NEMO Volume estimate: and for all variables together:
       total_layer_equivalent = total_layer_equivalent + layers_per_var_per_yr
      #print(' {:3} varname: {:15} freq: {:5} table: {:7} zdim: {:30} vertical dim: {:3} {:2} {:8} layers per var per yr: {:8}'.format(count, task.target.variable, task.target.frequency, task.target.table, getattr(task.target, "z_dims", []), vertical_dim, len(zdim), layer_number_due_to_freq, layers_per_var_per_yr ))
        
     # After the table attribute has been used to match with the data request, the table attribute is removed here because it is not a valid XIOS attribute:
     field.attrib.pop('table', None)

    # Write the NEMO XIOS file_def input files:
    tree_basic_file_def.write(file_def_file_name)

    print('\n With a 2D layer equivalent of ', total_layer_equivalent, ' the NEMO Volume estimate for this CMIP6 data request is ', total_layer_equivalent * 0.43 / 1000.0, ' GB per year\n')
    print(' The number of variables which is enabled in', file_def_file_name, ' is', count)


    volume_estimate = open('volume-estimate-nemo.txt','w')
    volume_estimate.write(' \nEC-Earth3 NEMO volume estimates of generated output:{}'.format('\n'))
    volume_estimate.write('  Volume estimate for the ORCA1L75   grid: {} GB/yr{}'.format(total_layer_equivalent * 0.43 / 1000.0, '\n'))
    volume_estimate.write('  Volume estimate for the ORCA025L75 grid: {} GB/yr{}'.format(total_layer_equivalent * 5.76 / 1000.0, '\n'))
    volume_estimate.write('  With {:8} horizontal data slices per year across the vertical and time dimension.{}'.format(int(total_layer_equivalent), '\n\n'))
    volume_estimate.close()


    # SPLIT THE FILE_DEF FILE IN THREE FILE_DEF FILES FOR OPA, LIM AND PISCES:

    # FILE_DEF FILE FOR OPA:
    tree_opa = xmltree.parse(file_def_file_name)
    root_opa = tree_opa.getroot()                        # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements

    for file_element in root_opa.findall('./file_group/file'):
     # Get the model component info from this attribute by  using a regular expression:
     model_component = re.search('_(.+?)_', file_element.attrib["name_suffix"]).group(1)
     if model_component == 'lim' or model_component == 'pisces':
     #print ' Remove file for opa file_def:', file_element.attrib["id"], model_component
      # Remove this file element from its parent element the file_group element:
      root_opa[0].remove(file_element)

    root_opa[0].attrib["id"] = "id_file_group_opa"
    tree_opa.write(file_def_opa_file_name)


    # FILE_DEF FILE FOR LIM:
    tree_lim = xmltree.parse(file_def_file_name)
    root_lim = tree_lim.getroot()                        # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements

    for file_element in root_lim.findall('./file_group/file'):
     # Get the model component info from this attribute by  using a regular expression:
     model_component = re.search('_(.+?)_', file_element.attrib["name_suffix"]).group(1)
     if model_component == 'opa' or model_component == 'pisces':
     #print ' Remove file for lim file_def:', file_element.attrib["id"], model_component
      # Remove this file element from its parent element the file_group element:
      root_lim[0].remove(file_element)

    root_lim[0].attrib["id"] = "id_file_group_lim"
    tree_lim.write(file_def_lim_file_name)


    # FILE_DEF FILE FOR PISCES:
    tree_pisces = xmltree.parse(file_def_file_name)
    root_pisces = tree_pisces.getroot()                        # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements

    for file_element in root_pisces.findall('./file_group/file'):
     # Get the model component info from this attribute by  using a regular expression:
     model_component = re.search('_(.+?)_', file_element.attrib["name_suffix"]).group(1)
     if model_component == 'opa' or model_component == 'lim':
     #print ' Remove file for pisces file_def:', file_element.attrib["id"], model_component
      # Remove this file element from its parent element the file_group element:
      root_pisces[0].remove(file_element)

    root_pisces[0].attrib["id"] = "id_file_group_pisces"
    tree_pisces.write(file_def_pisces_file_name)

    # Finishing up
    ece2cmorlib.finalize_without_cmor()


    # PRODUCE FILE_DEF FILES FOR OPA, LIM AND PISCES WITH ONLY ENABLED VARIABLES:

    # FILE_DEF FILE FOR OPA WITH ONLY ENABLED VARIABLES:
    tree_opa_enabled_only = xmltree.parse(file_def_opa_file_name)
    root_opa_enabled_only = tree_opa_enabled_only.getroot()    # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements

    for file_element in root_opa_enabled_only.findall('./file_group/file'):
      for field_element in file_element.findall('field[@enabled="False"]'): file_element.remove(field_element)
    tree_opa_enabled_only.write(file_def_opa_file_name_compact)


    # FILE_DEF FILE FOR LIM WITH ONLY ENABLED VARIABLES:
    tree_lim_enabled_only = xmltree.parse(file_def_lim_file_name)
    root_lim_enabled_only = tree_lim_enabled_only.getroot()    # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements

    for file_element in root_lim_enabled_only.findall('./file_group/file'):
      for field_element in file_element.findall('field[@enabled="False"]'): file_element.remove(field_element)
    tree_lim_enabled_only.write(file_def_lim_file_name_compact)


    # FILE_DEF FILE FOR PISCES WITH ONLY ENABLED VARIABLES:
    tree_pisces_enabled_only = xmltree.parse(file_def_pisces_file_name)
    root_pisces_enabled_only = tree_pisces_enabled_only.getroot()    # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements

    for file_element in root_pisces_enabled_only.findall('./file_group/file'):
      for field_element in file_element.findall('field[@enabled="False"]'): file_element.remove(field_element)
    tree_pisces_enabled_only.write(file_def_pisces_file_name_compact)





if __name__ == "__main__":
    main()
