#!/usr/bin/env python

# Call this script e.g. by:
#  ./create-parent-experiment-check-code.py
#
# With this script it is possible to generate the block of bash code which checks for the parent MIP
# experiment info. This block is copied in the modify-metadata-template.sh bash script. The
# parent_activity_id and parent_experiment_id are read from the cmor tables from the CMIP6_CV.json file.
#
# This script is part of the subpackage genecec (GENerate EC-Eearth Control output files)
# which is part of ece2cmor3.
#

from __future__ import print_function
import json


#Read JSON data into the datastore variable
with open('../resources/tables/CMIP6_CV.json', 'r') as g:
    datastore = json.load(g)

#for k, v in datastore.iteritems():
#    print k, v

#print datastore["CV"]["activity_id"]
#print '\n'
#print datastore["CV"]["source_id"]["EC-Earth3"]
#print datastore["CV"]["experiment_id"]["1pctCO2"]["parent_activity_id"]


code_parent_check_file = open('code-parent-check.sh','w')
code_parent_check_file.write('\n')

#requested_item=

for k, v in datastore["CV"]["experiment_id"].iteritems():
   #print ' {:30} {:30} {:30}'.format(k, v["activity_id"][0], v["parent_experiment_id"][0])

    if k != v["experiment_id"]:
     print(' IDs differ: {:30} {:30} {:30}'.format(v["activity_id"][0], v["experiment_id"], k))
    if len(v["activity_id"][:]) != 1:
     print(' The activity_id has multiple entries: {:30} {:30}'.format(v["activity_id"], k))
#   if len(v["parent_activity_id"][:]) != 1:
#    print ' The parent_activity_id has multiple entries: {:30} {:30} {:30}'.format(v["activity_id"], k, v["parent_activity_id"][:])
#   if len(v["parent_experiment_id"][:]) != 1:
#    print ' The parent_experiment_id has multiple entries: {:30} {:30} {:30}'.format(v["activity_id"], k, v["parent_experiment_id"][:])
#   if len(v["required_model_components"][:]) != 1:
#    print ' The required_model_components has multiple entries: {:30} {:30} {:30}'.format(v["activity_id"], k, v["required_model_components"][:])
#   if len(v["sub_experiment_id"][:]) != 1:
#    print ' The sub_experiment_id has multiple entries: {:30} {:30} {:30}'.format(v["activity_id"], k, v["sub_experiment_id"][:])
    
#   code_parent_check_file.write(' {:30} {:30} {:30} {:30} {:30} {:30} {:200} {}\n'.format(v["activity_id"][0], k, v["parent_activity_id"][0], v["parent_experiment_id"][0], v["required_model_components"][0], ' '.join(v["additional_allowed_model_components"][:]), v["experiment"], ' '.join(v["sub_experiment_id"][:]) ))
#   code_parent_check_file.write(' {:30} {:30} {:30} {:30} {:30} {:30} {:200} {}\n'.format("'"+v["activity_id"][0]+"'", "'"+k+"'", "'"+v["parent_activity_id"][0]+"'", "'"+v["parent_experiment_id"][0]+"'", "'"+v["required_model_components"][0]+"'", "'"+' '.join(v["additional_allowed_model_components"][:])+"'", "'"+v["experiment"]+"'", "'"+' '.join(v["sub_experiment_id"][:])+"'" ))


    # Checking the activity_id for cases of more then one MIP:
    activity_id_list   = v["activity_id"][0].split()
    n_activity_id_list = len(activity_id_list)
   #if n_activity_id_list != 1:
   # for counter in range(n_activity_id_list):
   #  print ' {:3} {:30} {:30} {:30}'.format(counter, k, v["activity_id"][0], activity_id_list[counter])

    # Split between MIPs in case more than one MIP is listed in the activity_id:
    for counter in range(n_activity_id_list):
    #print ' {:3} {:30} {:30} {:30}'.format(counter, k, v["activity_id"][0], activity_id_list[counter])
     code_parent_check_file.write(' if [ "$mip" = {:30} ] && [ "$experiment" = {:30} ]; then declare -a parent_info=({:30} {:30} {:30} {:30} {:30} {:30} {:200} {}); fi\n'.format("'"+activity_id_list[counter]+"'", "'"+k+"'", "'"+activity_id_list[counter]+"'", "'"+k+"'", "'"+v["parent_activity_id"][0]+"'", "'"+v["parent_experiment_id"][0]+"'", "'"+v["required_model_components"][0]+"'", "'"+' '.join(v["additional_allowed_model_components"][:])+"'", "'"+v["experiment"].replace("'", "")+"'", "'"+' '.join(v["sub_experiment_id"][:])+"'" ))

code_parent_check_file.close()




# Fragment from the CMIP6_CV.json:

# if [ "${ececonf}" = 'EC-EARTH-AOGCM'   ]; then declare -a ece_res=('

#       "experiment_id":{
#           "1pctCO2":{
#               "activity_id":[
#                   "CMIP"
#               ],
#               "additional_allowed_model_components":[
#                   "AER",
#                   "CHEM",
#                   "BGC"
#               ],
#               "experiment":"1 percent per year increase in CO2",
#               "experiment_id":"1pctCO2",
#               "parent_activity_id":[
#                   "CMIP"
#               ],
#               "parent_experiment_id":[
#                   "piControl"
#               ],
#               "required_model_components":[
#                   "AOGCM"
#               ],
#               "sub_experiment_id":[
#                   "none"
#               ]
#           },
