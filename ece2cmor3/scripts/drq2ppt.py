#!/usr/bin/env python

# Call this script e.g. by:
#  ./drq2ppt.py --drq cmip6-data-request/cmip6-data-request-m=CMIP-e=CMIP-t=1-p=1/cmvme_CMIP_piControl_1_1.xlsx
# or for the special "test all" case by:
#  ./drq2ppt.py --allvars
#
# With this script it is possible to generate the EC-Earth3 IFS control output files, i.e.
# the IFS Fortran namelists (the ppt files) for one MIP experiment.
#
# This script is part of the subpackage genecec (GENerate EC-Eearth Control output files)
# which is part of ece2cmor3.
#
# Note that this script is called by the script:
#  genecec-per-mip-experiment.sh
#
from __future__ import print_function
import sys
import os

import argparse
import logging
import re

import f90nml

from ece2cmor3 import ece2cmorlib, taskloader, cmor_source, cmor_target, cmor_utils, components

# Logging configuration
logformat = "%(asctime)s %(levelname)s:%(name)s: %(message)s"
logdateformat = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.DEBUG, format=logformat, datefmt=logdateformat)

# Logger construction
log = logging.getLogger(__name__)


# Determines the ifs output period for given task (in hours)
def get_output_freq(task):
    if task.target.frequency == "fx":
        return 0
    if task.target.frequency.startswith("subhr"):
        log.warning("Variable %s in table %s: sub-hourly frequencies are not supported... Skipping variable" %
                    (task.target.variable, task.target.table))
        return -1
    regex = re.search("^[0-9]+hr*", task.target.frequency)
    if regex:
        return int(regex.group(0)[:-2])
    return get_sample_freq(task)


# Determines the ifs output frequency for daily/monthly variables. By default
# 2D variables are requested on 3-hourly basis and 3D variables on 6-hourly basis.
def get_sample_freq(task):
    if any(c in cmor_source.ifs_source.grib_codes_3D for c in task.source.get_root_codes()):
        return 6
    else:
        return 3


# Counts spectral and gridpoint messages in the given list
def count_spectral_codes(code_list):
    return len(set([c for c in code_list if c in cmor_source.ifs_source.grib_codes_sh])), \
           len(set([c for c in code_list if c not in cmor_source.ifs_source.grib_codes_sh]))


# Takes the union of two namelists
def join_namelists(nml1, nml2):
    result = {"CFPFMT": "MODEL"}
    for key in ["MFP2DF", "MFPPHY", "MFP3DFS", "MFP3DFP", "MFP3DFH"]:
        codes = sorted(list(set(nml1.get(key, [])) | set(nml2.get(key, []))))
        numcodes = len(codes)
        numkey_chars = list(key)
        numkey_chars[0] = 'N'
        numkey = "".join(numkey_chars)
        if numcodes > 0:
            result[key] = codes
            result[numkey] = numcodes
    for key in ["RFP3P", "RFP3H"]:
        levels = sorted(list(set(nml1.get(key, [])) | set(nml2.get(key, []))))
        if key == "RFP3P":
            levels = list(reversed(levels))
        if len(levels) > 0:
            result[key] = levels
    if "NRFP3S" in nml1.keys() or "NRFP3S" in nml2.keys():
        # To include all model levels use magic number -99. Opposite, by using the magic number -1 the variable is not saved at any model level:
        result["NRFP3S"] = -1
    return result


# Writes a set of input IFS files for the requested tasks
def write_ppt_files(tasks):
    freqgroups = cmor_utils.group(tasks, get_output_freq)
    # Fix for issue 313, make sure to always generate 6-hourly ppt:
    if freqgroups.keys() == [3]:
        freqgroups[6] = []
    if -1 in freqgroups.keys():
        freqgroups.pop(-1)
    freqs_to_remove = []
    for freq1 in freqgroups:
        if freq1 <= 0:
            continue
        for freq2 in freqgroups:
            if freq2 > freq1:
                if freq2 % freq1 == 0:
                    freqgroups[freq2] = freqgroups[freq1] + freqgroups[freq2]
                else:
                    log.error("Frequency %d is not a divisor of frequency %d: this is not supported, "
                              "removing the former" % (freq1, freq2))
                    freqs_to_remove.append(freq1)
    for freq in set(freqs_to_remove):
        freqgroups.pop(freq, None)
    num_slices_tot_sp, num_slices_tot_gp, num_blocks_tot_sp, num_blocks_tot_gp = 0, 0, 0, 0
    min_freq = max(freqgroups.keys())
    prev_freq = 0
    fx_namelist = {}
    for freq in sorted(freqgroups.keys()):
        mfp2df, mfpphy, mfp3dfs, mfp3dfp, mfp3dfh = [], [], [], [], []
        num_slices_sp, num_slices_gp, num_blocks_sp, num_blocks_gp = 0, 0, 0, 0
        alevs, plevs, hlevs = [], [], []
        for task in freqgroups[freq]:
            zaxis, levs = cmor_target.get_z_axis(task.target)
            root_codes = task.source.get_root_codes()
            if not zaxis:
                for code in root_codes:
                    if freq > 0 and code in cmor_source.ifs_source.grib_codes_fx:
                        continue
                    if code in cmor_source.ifs_source.grib_codes_3D:
                        # Exception for orog and areacella, depend only on lowest level of 129:
                        if task.target.variable in ["orog", "areacella"] and code == cmor_source.grib_code(129):
                            mfp2df.append(code)
                        else:
                            log.warning("3D grib code %s used in 2D cmor-target %s..."
                                        "assuming this is on model levels" % (str(code), task.target.variable))
                            mfp3dfs.append(code)
                    elif code in cmor_source.ifs_source.grib_codes_2D_dyn:
                        log.info("Adding grib code %s to MFP2DF %dhr ppt file for variable "
                                 "%s in table %s" % (str(code), freq, task.target.variable, task.target.table))
                        mfp2df.append(code)
                    elif code in cmor_source.ifs_source.grib_codes_2D_phy:
                        log.info("Adding grib code %s to MFPPHY %dhr ppt file for variable "
                                 "%s in table %s" % (str(code), freq, task.target.variable, task.target.table))
                        mfpphy.append(code)
                    else:
                        log.error("Unknown 2D IFS grib code %s skipped" % str(code))
            else:
                for code in root_codes:
                    if freq > 0 and code in cmor_source.ifs_source.grib_codes_fx:
                        continue
                    if code in cmor_source.ifs_source.grib_codes_3D:
                        if zaxis in cmor_target.model_axes:
                            log.info("Adding grib code %s to MFP3DFS %dhr ppt file for variable "
                                     "%s in table %s" % (str(code), freq, task.target.variable, task.target.table))
                            mfp3dfs.append(code)
                            alevs.extend(levs)
                        elif zaxis in cmor_target.pressure_axes:
                            log.info("Adding grib code %s to MFP3DFP %dhr ppt file for variable "
                                     "%s in table %s" % (str(code), freq, task.target.variable, task.target.table))
                            mfp3dfp.append(code)
                            plevs.extend(levs)
                        elif zaxis in cmor_target.height_axes:
                            log.info("Adding grib code %s to MFP3DFH %dhr ppt file for variable "
                                     "%s in table %s" % (str(code), freq, task.target.variable, task.target.table))
                            mfp3dfh.append(code)
                            hlevs.extend(levs)
                        else:
                            log.error("Axis type %s unknown, adding grib code %s"
                                      "to model level variables" % (zaxis, str(code)))
                    elif code in cmor_source.ifs_source.grib_codes_2D_dyn:
                        mfp2df.append(code)
                    elif code in cmor_source.ifs_source.grib_codes_2D_phy:
                        mfpphy.append(code)
                    # case for PEXTRA tendencies is missing
                    else:
                        log.error("Unknown 3D IFS grib code %s skipped" % str(code))
        # Always add the geopotential, recommended by ECMWF
        if cmor_source.grib_code(129) not in mfp3dfs:
            mfp2df.append(cmor_source.grib_code(129))
        # Always add the surface pressure, recommended by ECMWF
        mfpphy.append(cmor_source.grib_code(134))
        # Always add the logarithm of surface pressure, recommended by ECMWF
        mfp2df.append(cmor_source.grib_code(152))
        nfp2dfsp, nfp2dfgp = count_spectral_codes(mfp2df)
        mfp2df = sorted(list(map(lambda c: c.var_id if c.tab_id == 128 else c.__hash__(), set(mfp2df))))
        nfpphysp, nfpphygp = count_spectral_codes(mfpphy)
        mfpphy = sorted(list(map(lambda c: c.var_id if c.tab_id == 128 else c.__hash__(), set(mfpphy))))
        nfp3dfssp, nfp3dfsgp = count_spectral_codes(mfp3dfs)
        mfp3dfs = sorted(list(map(lambda c: c.var_id if c.tab_id == 128 else c.__hash__(), set(mfp3dfs))))
        nfp3dfpsp, nfp3dfpgp = count_spectral_codes(mfp3dfp)
        mfp3dfp = sorted(list(map(lambda c: c.var_id if c.tab_id == 128 else c.__hash__(), set(mfp3dfp))))
        nfp3dfhsp, nfp3dfhgp = count_spectral_codes(mfp3dfh)
        mfp3dfh = sorted(list(map(lambda c: c.var_id if c.tab_id == 128 else c.__hash__(), set(mfp3dfh))))
        plevs = sorted(list(set([float(s) for s in plevs])))[::-1]
        hlevs = sorted(list(set([float(s) for s in hlevs])))
        namelist = {"CFPFMT": "MODEL"}
        if any(mfp2df):
            namelist["NFP2DF"] = len(mfp2df)
            namelist["MFP2DF"] = mfp2df
            num_slices_sp += nfp2dfsp
            num_slices_gp += nfp2dfgp
        if any(mfpphy):
            namelist["NFPPHY"] = len(mfpphy)
            namelist["MFPPHY"] = mfpphy
            num_slices_sp += nfpphysp
            num_slices_gp += nfpphygp
        if any(mfp3dfs):
            namelist["NFP3DFS"] = len(mfp3dfs)
            namelist["MFP3DFS"] = mfp3dfs
            # To include all model levels use magic number -99. Opposite, by using the magic number -1 the variable is not saved at any model level:
            namelist["NRFP3S"] = -1
            num_blocks_sp += nfp3dfssp
            num_blocks_gp += nfp3dfsgp
        if any(mfp3dfp):
            namelist["NFP3DFP"] = len(mfp3dfp)
            namelist["MFP3DFP"] = mfp3dfp
            namelist["RFP3P"] = plevs
            num_slices_sp += (nfp3dfpsp * len(plevs))
            num_slices_gp += (nfp3dfpgp * len(plevs))
        if any(mfp3dfh):
            namelist["NFP3DFH"] = len(mfp3dfh)
            namelist["MFP3DFH"] = mfp3dfh
            namelist["RFP3H"] = hlevs
            num_slices_sp += (nfp3dfhsp * len(hlevs))
            num_slices_gp += (nfp3dfhgp * len(hlevs))
        num_slices_tot_sp = num_slices_sp if prev_freq == 0 else \
            (num_slices_sp + ((freq/prev_freq) - 1) * num_slices_tot_sp)
        num_slices_tot_gp = num_slices_gp if prev_freq == 0 else \
            (num_slices_gp + ((freq/prev_freq) - 1) * num_slices_tot_gp)
        num_blocks_tot_sp = num_blocks_sp if prev_freq == 0 else \
            (num_blocks_sp + ((freq/prev_freq) - 1) * num_blocks_tot_sp)
        num_blocks_tot_gp = num_blocks_gp if prev_freq == 0 else \
            (num_blocks_gp + ((freq/prev_freq) - 1) * num_blocks_tot_gp)
        prev_freq = freq
        nml = f90nml.Namelist({"NAMFPC": namelist})
        nml.uppercase, nml.end_comma = True, True
        if freq > 0:
            f90nml.write(nml, "pptdddddd%04d" % (100 * freq,))
        if freq == 0:
            fx_namelist = namelist
        if freq == min_freq:
            # Always add orography and land mask for lowest frequency ppt
            mfpphy.extend([129, 172, 43])
            mfpphy = sorted(list(set(mfpphy)))
            namelist["MFPPHY"] = mfpphy
            namelist["NFPPHY"] = len(mfpphy)
            nml = f90nml.Namelist({"NAMFPC": join_namelists(namelist, fx_namelist)})
            nml.uppercase, nml.end_comma = True, True
            # Write initial state ppt
            f90nml.write(nml, "ppt0000000000")
    average_hours_per_month = 730
    slices_per_month_sp = (average_hours_per_month * num_slices_tot_sp) / prev_freq
    slices_per_month_gp = (average_hours_per_month * num_slices_tot_gp) / prev_freq
    blocks_per_month_sp = (average_hours_per_month * num_blocks_tot_sp) / prev_freq
    blocks_per_month_gp = (average_hours_per_month * num_blocks_tot_gp) / prev_freq
    num_layers = 91
    log.info("")
    log.info("EC-Earth IFS output volume estimates:")
    log.info("---------------------------------------------------------------------------")
    log.info("# spectral GRIB messages p/m:  %d" % (slices_per_month_sp + num_layers * blocks_per_month_sp))
    log.info("# gridpoint GRIB messages p/m: %d" % (slices_per_month_gp + num_layers * blocks_per_month_gp))
    log.info("---------------------------------------------------------------------------")
    log.info("                           T255L91                     T511L91               ")
    log.info("---------------------------------------------------------------------------")
    vol255 = (slices_per_month_sp + num_layers * blocks_per_month_sp) * 0.133 / 1000. +\
             (slices_per_month_gp + num_layers * blocks_per_month_gp) * 0.180 / 1000.
    vol511 = (slices_per_month_sp + num_layers * blocks_per_month_sp) * 0.503 / 1000. +\
             (slices_per_month_gp + num_layers * blocks_per_month_gp) * 0.698 / 1000.
    log.info("                           %.2f GB/yr                %.2f GB/yr        " % (12*vol255, 12*vol511))

    volume_estimate = open('volume-estimate-ifs.txt','w')
    volume_estimate.write(' \nEC-Earth3 IFS volume estimates of generated output:{}'.format('\n'))
    volume_estimate.write('  Volume estimate of the spectral + gridpoint GRIB files for T255L91 grid: {} GB/yr{}'.format(12*vol255, '\n'))
    volume_estimate.write('  Volume estimate of the spectral + gridpoint GRIB files for T511L91 grid: {} GB/yr{}'.format(12*vol511, '\n\n'))
    volume_estimate.write('  Number of spectral  GRIB messages per month: {}{}'.format(slices_per_month_sp + num_layers * blocks_per_month_sp, '\n'))
    volume_estimate.write('  Number of gridpoint GRIB messages per month: {}{}'.format(slices_per_month_gp + num_layers * blocks_per_month_gp, '\n\n'))
    volume_estimate.close()


# Main program
def main():
    parser = argparse.ArgumentParser(description="Create IFS ppt files for given data request")
    varsarg = parser.add_mutually_exclusive_group(required=True)
    varsarg.add_argument("--vars", metavar="FILE", type=str,
                         help="File (json) containing cmor variables per EC-Earth component")
    varsarg.add_argument("--drq", metavar="FILE", type=str,
                         help="File (json|f90 namelist|xlsx) containing cmor variables")
    varsarg.add_argument("--allvars", action="store_true", default=False,
                         help="Read all possible variables from CMOR tables")
    parser.add_argument("--tabdir", metavar="DIR", type=str, default=ece2cmorlib.table_dir_default,
                        help="Cmorization table directory")
    parser.add_argument("--tabid", metavar="PREFIX", type=str, default=ece2cmorlib.prefix_default,
                        help="Cmorization table prefix string")

    args = parser.parse_args()

    print("")
    print("Running drq2ppt.py with:")
    print(" ./drq2ppt.py " + cmor_utils.ScriptUtils.get_drq_vars_options(args))
    print("")

    if args.vars is not None and not os.path.isfile(args.vars):
        log.fatal("Your variable list json file %s cannot be found." % args.vars)
        sys.exit(' Exiting drq2ppt.')

    if args.drq is not None and not os.path.isfile(args.drq):
        log.fatal("Your data request file %s cannot be found." % args.drq)
        sys.exit(' Exiting drq2ppt.')

    # Initialize ece2cmor:
    ece2cmorlib.initialize_without_cmor(ece2cmorlib.conf_path_default, mode=ece2cmorlib.PRESERVE, tabledir=args.tabdir,
                                        tableprefix=args.tabid)

    # Load only atmosphere variables as task targets:
    try:
        if getattr(args, "vars", None) is not None:
            taskloader.load_tasks(args.vars, active_components=["ifs"])
        elif getattr(args, "allvars", False):
            taskloader.load_tasks_from_drq("allvars", active_components=["ifs"], check_prefs=False)
        else:
            taskloader.load_tasks_from_drq(args.drq, active_components=["ifs"], check_prefs=False)
    except taskloader.SwapDrqAndVarListException as e:
        log.error(e.message)
        opt1, opt2 = "vars" if e.reverse else "drq", "drq" if e.reverse else "vars"
        log.error("It seems you are using the --%s option where you should use the --%s option for this file"
                  % (opt1, opt2))
        sys.exit(' Exiting drq2ppt.')

    # Write the IFS input files
    write_ppt_files(ece2cmorlib.tasks)

    # Finishing up
    ece2cmorlib.finalize_without_cmor()


if __name__ == "__main__":
    main()
