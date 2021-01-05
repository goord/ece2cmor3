#!/usr/bin/env python
# Thomas Reerink
#
# Run example:
#  python mip-experiment-list.py
#
# Looping over all MIPs and within each MIP over all its MIP experiments.
# Printing the MIP experiment list with some additional info.
#
# This script is part of the subpackage genecec (GENerate EC-Eearth Control output files)
# which is part of ece2cmor3.
#

from __future__ import print_function
from dreqPy import dreq
dq = dreq.loadDreq()

mip_counter        = 0
experiment_counter = 0

mip_list_file_name = 'mip-experiment-list.txt'
mip_list_file = open(mip_list_file_name, 'w' )

# Loop over the MIPs:
for mip in dq.coll['mip'].items:
  mip_counter = mip_counter + 1
 #print '{:3} {:15} {}'.format(mip_counter, mip.label, mip)
  print('{:3} {:15} {}'.format(mip_counter, mip.label, str(mip).replace('Item <1.1 Model Intercomparison Project>: [', '').replace(']', '').replace(mip.label, '').replace(' - set of', 'DECK - set of')))
  # Loop over the MIP experiments:
  for u in dq.inx.iref_by_sect[mip.uid].a['experiment']:
    ex = dq.inx.uid[u]
    if mip.label != ex.mip:
     print(' The mip.label and ex.mip are different: {:15} versus {:15}'.format(mip.label, ex.mip))
    mip_list_file.write( '{:12} {:28} tier-{:1}  {}'.format(ex.mip, ex.label, ex.tier[0], ex.title) + '\n')
    experiment_counter = experiment_counter + 1
    
mip_list_file.close()

print('Number of MIPs is: {:3} and the number of MIP experiments is: {}'.format(mip_counter, experiment_counter))

print('\nThe file ', mip_list_file_name, ' has been created.\n')


experiment_tiers_included = [1,2,3]
#ec_earth_mips = ['CMIP'] # for basic test
#ec_earth_mips = ['CMIP', 'DCPP']
ec_earth_mips  = ['CMIP', 'AerChemMIP', 'CDRMIP', 'C4MIP',                   'DCPP',                              'HighResMIP', 'ISMIP6', 'LS3MIP', 'LUMIP', 'OMIP', 'PAMIP', 'PMIP', 'RFMIP', 'ScenarioMIP', 'VolMIP', 'CORDEX', 'DynVarMIP', 'SIMIP', 'VIACSAB'] # All 19 EC-Earth MIPs
#ec_earth_mips = ['CMIP', 'AerChemMIP', 'CDRMIP', 'C4MIP', 'CFMIP', 'DAMIP', 'DCPP', 'FAFMIP', 'GeoMIP', 'GMMIP', 'HighResMIP', 'ISMIP6', 'LS3MIP', 'LUMIP', 'OMIP', 'PAMIP', 'PMIP', 'RFMIP', 'ScenarioMIP', 'VolMIP', 'CORDEX', 'DynVarMIP', 'SIMIP', 'VIACSAB'] # All 24 CMIP6 MIPs
experiment_counter = 0

mip_counter        = 0
experiment_counter = 0

mip_list_file_name = 'ece-mip-experiment-list.txt'
mip_list_file = open(mip_list_file_name, 'w' )

# Loop over the MIPs:
for mip in dq.coll['mip'].items:
  if mip.label in ec_earth_mips: 
   mip_counter = mip_counter + 1
  #print '{:3} {:15} {}'.format(mip_counter, mip.label, mip)
   print('{:3} {:15} {}'.format(mip_counter, mip.label, str(mip).replace('Item <1.1 Model Intercomparison Project>: [', '').replace(']', '').replace(mip.label, '').replace(' - set of', 'DECK - set of')))
   # Loop over the MIP experiments:
  #mip_list_file.write( '{:36}'.format(mip.label) + '\n')
   mip_list_file.write( '\n{:36} {}'.format(mip.label, str(mip).replace('Item <1.1 Model Intercomparison Project>: [', '').replace(']', '').replace(mip.label, '').replace(' - set of', 'DECK - set of')) + '\n')
   for u in dq.inx.iref_by_sect[mip.uid].a['experiment']:
   #if ex.tier[0] in experiment_tiers_included and mip.label in ec_earth_mips: 
     ex = dq.inx.uid[u]
     mip_list_file.write( ' {:28} tier-{:1}  {}'.format(ex.label, ex.tier[0], ex.title) + '\n')
    #mip_list_file.write( ' {:28} tier-{:1}'.format(ex.label, ex.tier[0]) + '\n')
     experiment_counter = experiment_counter + 1
    
mip_list_file.close()

print('Number of MIPs is: {:3} and the number of MIP experiments is: {}'.format(mip_counter, experiment_counter))

print('\nThe file ', mip_list_file_name, ' has been created.\n')
