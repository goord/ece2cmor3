import datetime
import json
import logging
import os
import tempfile

import cmor
from builtins import str
from six import string_types

from ece2cmor3 import __version__, cmor_target, cmor_task, nemo2cmor, ifs2cmor, lpjg2cmor, tm52cmor, postproc, \
    cmor_utils

# Logger instance
log = logging.getLogger(__name__)

# Module configuration defaults
conf_path_default = os.path.join(os.path.dirname(__file__), "resources", "metadata-templates",
                                 "cmip6-CMIP-piControl-metadata-template.json")
cmor_mode_default = cmor.CMOR_PRESERVE
prefix_default = "CMIP6"
table_dir_default = os.path.join(os.path.dirname(__file__), "resources", "tables")

# ece2cmor master API.
metadata = {}
cmor_mode = cmor_mode_default
prefix = prefix_default
table_dir = table_dir_default
tasks = []
targets = []
masks = {}
enable_masks = True
auto_filter = True

# CMOR modes
APPEND = cmor.CMOR_APPEND
APPEND_NC3 = cmor.CMOR_APPEND_3
REPLACE = cmor.CMOR_REPLACE
REPLACE_NC3 = cmor.CMOR_REPLACE_3
PRESERVE = cmor.CMOR_PRESERVE
PRESERVE_NC3 = cmor.CMOR_PRESERVE_3


# Initialization function without using the cmor library, must be called before starting
def initialize_without_cmor(metadata_path=conf_path_default, mode=cmor_mode_default, tabledir=table_dir_default,
                            tableprefix=prefix_default):
    global prefix, table_dir, targets, metadata, cmor_mode
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    cmor_mode = mode
    table_dir = tabledir
    prefix = tableprefix
    validate_setup_settings()
    targets = cmor_target.create_targets(table_dir, prefix)


# Initialization function, must be called before starting
def initialize(metadata_path=conf_path_default, mode=cmor_mode_default, tabledir=table_dir_default,
               tableprefix=prefix_default, outputdir=None, logfile=None, create_subdirs=True):
    global prefix, table_dir, targets, metadata, cmor_mode
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    cmor_mode = mode
    table_dir = tabledir
    prefix = tableprefix
    validate_setup_settings()
    logname = logfile
    if logfile is not None:
        logname = '.'.join(logfile.split('.')[:-1] + ["cmor", "log"])
    cmor.setup(table_dir, cmor_mode, logfile=logname, create_subdirectories=(1 if create_subdirs else 0))
    if outputdir is not None:
        metadata["outpath"] = outputdir
    if "outpath" not in metadata:
        metadata["outpath"] = os.path.join(os.getcwd(), "cmor")
    hist = metadata.get("history", "")
    newline = "processed by ece2cmor {version}, git rev. " \
              "{sha}\n".format(version=__version__.version, sha=cmor_utils.get_git_hash())
    metadata["history"] = newline + hist if len(hist) != 0 else newline
    metadata["latest_ece2cmor_version"] = __version__.version
    metadata["ece2cmor_git_revision"] = cmor_utils.get_git_hash()
    metadata["latest_applied_cmor_fixer_version"] = 'None'
    for key, val in list(metadata.items()):
        log.info("Metadata attribute %s: %s", key, val)
    with tempfile.NamedTemporaryFile("r+w", suffix=".json", delete=False) as tmp_file:
        json.dump(metadata, tmp_file)
    cmor.dataset_json(tmp_file.name)
    cmor.set_cur_dataset_attribute("calendar", "proleptic_gregorian")
    targets = cmor_target.create_targets(table_dir, prefix)
    tmp_file.close()
    os.remove(tmp_file.name)


# Validation of setup configuration
def validate_setup_settings():
    global prefix, table_dir, cmor_mode
    if not table_dir or not isinstance(table_dir, string_types):
        log.error("Invalid cmorization table string given...aborting")
        raise Exception("Cmorization table directory is empty or not a string")
    if not os.path.exists(table_dir):
        log.error("Cmorization table directory %s does not exist" % table_dir)
        raise Exception("Cmorization table directory does not exist")
    if not prefix or not isinstance(prefix, string_types):
        log.error("Cmorization table prefix is empty or not a string")
        raise Exception("Cmorization table prefix is empty or not a string")
    if cmor_mode not in [APPEND, APPEND_NC3, REPLACE, REPLACE_NC3, PRESERVE, PRESERVE_NC3]:
        log.error("Invalid CMOR netcdf file action %s given" % str(cmor_mode))
        raise Exception("Invalid CMOR netcdf file action")
    return 0


# Closes cmor
def finalize_without_cmor():
    global tasks, targets, masks
    targets = []
    tasks = []
    masks = {}


# Closes cmor
def finalize():
    global tasks, targets, masks
    cmor.close()
    targets = []
    tasks = []
    masks = {}


# Returns one or more cmor targets for task creation.
def get_cmor_target(var_id, tab_id=None):
    global log, targets
    if tab_id is None:
        return [t for t in targets if t.variable == var_id]
    else:
        results = [t for t in targets if t.variable == var_id and t.table == tab_id]
        if len(results) == 1:
            return results[0]
        elif len(results) == 0:
            return None
        else:
            log.error("Table validation error: multiple variables with name %s found in table %s" % (var_id, tab_id))


# Adds a task to the task list.
def add_task(tsk):
    global log, tasks, targets
    if isinstance(tsk, cmor_task.cmor_task):
        if tsk.target not in targets:
            log.error("Cannot append tasks with unknown target %s" % str(tsk.target))
            return False
        duptasks = [t for t in tasks if t.target is tsk.target]
        if len(duptasks) != 0:
            log.warning("Replacing task producing %s" % str(tsk.target))
            tasks.remove(duptasks[0])
        tasks.append(tsk)
    else:
        log.error("Can only append cmor_task to the list, attempt to append %s" % str(tsk))
        return False
    return True


# Adds a mask
def add_mask(name, src, func, val):
    global masks
    masks[name] = {"source": src, "operator": func, "rhs": val}


# Performs an IFS cmorization processing:
def perform_ifs_tasks(datadir, expname,
                      refdate=None,
                      postprocmode=postproc.recreate,
                      tempdir="/tmp/ece2cmor",
                      taskthreads=4,
                      cdothreads=4):
    global log, tasks, table_dir, prefix, masks
    validate_setup_settings()
    validate_run_settings(datadir, expname)
    ifs_tasks = [t for t in tasks if t.source.model_component() == "ifs"]
    log.info("Selected %d IFS tasks from %d input tasks" % (len(ifs_tasks), len(tasks)))
    if len(ifs_tasks) == 0:
        return
    tableroot = os.path.join(table_dir, prefix)
    if enable_masks:
        ifs2cmor.masks = {k: masks[k] for k in masks if masks[k]["source"].model_component() == "ifs"}
    else:
        ifs2cmor.masks = {}
    if (not ifs2cmor.initialize(datadir, expname, tableroot, refdate if refdate else datetime.datetime(1850, 1, 1),
                                tempdir=tempdir, autofilter=auto_filter)):
        return
    postproc.postproc_mode = postprocmode
    postproc.cdo_threads = cdothreads
    ifs2cmor.execute(ifs_tasks, nthreads=taskthreads)

# Performs a NEMO cmorization processing:
def perform_nemo_tasks(datadir, expname, refdate):
    global log, tasks, table_dir, prefix
    validate_setup_settings()
    validate_run_settings(datadir, expname)
    nemo_tasks = [t for t in tasks if t.source.model_component() == "nemo"]
    log.info("Selected %d NEMO tasks from %d input tasks" % (len(nemo_tasks), len(tasks)))
    tableroot = os.path.join(table_dir, prefix)
    if not nemo2cmor.initialize(datadir, expname, tableroot, refdate):
        return
    nemo2cmor.execute(nemo_tasks)


# Performs a LPJG cmorization processing:
def perform_lpjg_tasks(datadir, ncdir, expname, refdate):
    global log, tasks, table_dir, prefix
    validate_setup_settings()
    validate_run_settings(datadir, expname)
    lpjg_tasks = [t for t in tasks if t.source.model_component() == "lpjg"]
    log.info("Selected %d LPJG tasks from %d input tasks" % (len(lpjg_tasks), len(tasks)))
    if not lpjg2cmor.initialize(datadir, ncdir, expname, table_dir, prefix, refdate):
        return
    lpjg2cmor.execute(lpjg_tasks)


# Performs a TM5 cmorization processing:
def perform_tm5_tasks(datadir, ncdir, expname, refdate=None):
    global log, tasks, table_dir, prefix
    validate_setup_settings()
    validate_run_settings(datadir, expname)
    tm5_tasks = [t for t in tasks if t.source.model_component() == "tm5"]
    log.info("Selected %d TM5 tasks from %d input tasks" % (len(tm5_tasks), len(tasks)))
    if (not tm52cmor.initialize(datadir, expname, table_dir, prefix, refdate)):
        return
    tm52cmor.execute(tm5_tasks)


# def perform_NEWCOMPONENT_tasks(datadir, expname, startdate, interval):
#    global log, tasks, table_dir, prefix
#    validate_setup_settings()
#    validate_run_settings(datadir, expname)
#    NEWCOMPONENT_tasks = [t for t in tasks if isinstance(t.source, cmor_source.NEWCOMPONENT_source)]
#    log.info("Selected %d NEWCOMPONENT tasks from %d input tasks" % (len(NEWCOMPONENT_tasks), len(tasks)))
#    tableroot = os.path.join(table_dir, prefix)
#    if not NEWCOMPONENT2cmor.initialize(datadir, expname, tableroot, startdate, interval):
#        return
#    NEWCOMPONENT2cmor.execute(NEWCOMPONENT_tasks)


# Validation of cmor session configuration
def validate_run_settings(datadir, expname):
    if not datadir or not isinstance(datadir, str):
        log.error("Invalid output data directory string given...aborting")
        raise Exception("Output data directory is empty or not a string")
    if not os.path.exists(datadir):
        log.error("Output data directory %s does not exist" % table_dir)
        raise Exception("Output data directory does not exist")
    if not expname:
        log.error("Invalid empty experiment name given...aborting")
        raise Exception("Experiment name is empty string or None")
