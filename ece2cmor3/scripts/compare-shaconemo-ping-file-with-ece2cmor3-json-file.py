#!/usr/bin/env python

# Call this script by:
#  ./compare-shaconemo-ping-file-with-ece2cmor3-json-file.py

# This script reads the shaconemo xml ping files (the files which relate NEMO code variable
# names with CMOR names. NEMO code names which are labeled by 'dummy_' are not identified by
# the Shaconemo comunity. The ece2cmor3 json file lists all NEMO variables which can currently
# be cmorized by ece2cmor3. The script shows which variables are only in one of both files
# available.

from __future__ import print_function
import xml.etree.ElementTree as xmltree
import json
from os.path import expanduser

#ping_file_directory = expanduser("~")+"/cmorize/shaconemo/ORCA1_LIM3_PISCES/EXP00/"
#ping_file_directory = expanduser("~")+"/ec-earth-3/branch-r6874-control-output-files/runtime/classic/ctrl/"
ping_file_directory = expanduser("~")+"/ec-earth-3/trunk/runtime/classic/ctrl/"

treeOcean     = xmltree.parse(ping_file_directory + "ping_ocean_DR1.00.27.xml"    )
treeSeaIce    = xmltree.parse(ping_file_directory + "ping_seaIce_DR1.00.27.xml"   )
treeOcnBgChem = xmltree.parse(ping_file_directory + "ping_ocnBgChem_DR1.00.27.xml")

rootOcean     = treeOcean.getroot()            # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements
rootSeaIce    = treeSeaIce.getroot()           # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements
rootOcnBgChem = treeOcnBgChem.getroot()        # This root has two indices: the 1st index refers to field_definition-element, the 2nd index refers to the field-elements

field_elements_Ocean     = rootOcean    [0][:]
field_elements_SeaIce    = rootSeaIce   [0][:]
field_elements_OcnBgChem = rootOcnBgChem[0][:]

## This function excludes the dummy_ variables from the ping list and removes the CMIP6_ prefix.
#def filter_dummy_vars_in_ping_list(field_elements):
#    pinglist = []
#    for child in field_elements:
#     if child.attrib["field_ref"].startswith('dummy_'):
#      continue
#     else:
#      pinglist.append(child.attrib["id"][6:])
#     return pinglist

#pinglistOcean     = filter_dummy_vars_in_ping_list(field_elements_Ocean    )
#pinglistSeaIce    = filter_dummy_vars_in_ping_list(field_elements_SeaIce   )
#pinglistOcnBgChem = filter_dummy_vars_in_ping_list(field_elements_OcnBgChem)

#Exclude the dummy_ variables from the ping list and removes the CMIP6_ prefix.
pinglistOcean = []
for child in field_elements_Ocean:
 if child.attrib["field_ref"].startswith('dummy_'):
  continue
 else:
  pinglistOcean.append(child.attrib["id"][6:])

pinglistSeaIce = []
for child in field_elements_SeaIce:
 if child.attrib["field_ref"].startswith('dummy_'):
  continue
 else:
  pinglistSeaIce.append(child.attrib["id"][6:])

pinglistOcnBgChem = []
for child in field_elements_OcnBgChem:
 if child.attrib["field_ref"].startswith('dummy_'):
  continue
 else:
  pinglistOcnBgChem.append(child.attrib["id"][6:])

total_pinglist = pinglistOcean + pinglistSeaIce + pinglistOcnBgChem

f = open("../resources/nemopar.json").read()
data = json.loads(f)
#print data

targets = []
for d in data:
    targets.append(str(d["target"]))
#print targets
print('\n The ', len(set(targets) - set(total_pinglist)), ' variables which are in ece2cmor3\'s nemopar.json file but not in the ping file:\n ', set(targets) - set(total_pinglist))
print('\n The ', len(set(total_pinglist) - set(targets)), ' variables which are in the ping file but not in the ece2cmor3 json file:\n ', set(total_pinglist) - set(targets))
print('\n There are ', len(targets), ' variables in the ece2cmor3 nemopar.json file, and ', len(total_pinglist), 'non-dummy variables in the shaconemo ping file')
print('\n There are ', len(set(targets) & set(total_pinglist)), ' variables with the same name in both files\n')

#history

#print rootOcean.attrib["id"], rootSeaIce.attrib["id"], rootOcnBgChem.attrib["id"]

#print field_elements_Ocean    [1].__dict__  # Example print of the 1st Ocean     field-element
#print field_elements_SeaIce   [1].__dict__  # Example print of the 1st SeaIce    field-element
#print field_elements_OcnBgChem[1].__dict__  # Example print of the 1st OcnBgChem field-element

#print field_elements_Ocean    [1].tag,field_elements_Ocean    [1].attrib["id"],field_elements_Ocean    [1].attrib["field_ref"],field_elements_Ocean    [1].text  # Example print of the tag and some specified attributes of the 1st Ocean     field-element
#print field_elements_SeaIce   [1].tag,field_elements_SeaIce   [1].attrib["id"],field_elements_SeaIce   [1].attrib["field_ref"],field_elements_SeaIce   [1].text  # Example print of the tag and some specified attributes of the 1st SeaIce    field-element
#print field_elements_OcnBgChem[1].tag,field_elements_OcnBgChem[1].attrib["id"],field_elements_OcnBgChem[1].attrib["field_ref"],field_elements_OcnBgChem[1].text  # Example print of the tag and some specified attributes of the 1st OcnBgChem field-element

#for field_elements in [field_elements_Ocean, field_elements_SeaIce, field_elements_OcnBgChem]:
#    for child in field_elements:
#        print child.attrib["id"], child.attrib["field_ref"], child.text

#print rootOcean[0][0].attrib["field_ref"]
#print rootOcean[0][0].text
#print rootOcean[0][1].attrib["expr"]
#print rootOcean[0][1].text
