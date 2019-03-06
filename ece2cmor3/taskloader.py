import csv
import json
import logging
import os

from ece2cmor3 import components
from ece2cmor3 import ece2cmorlib, cmor_source, cmor_target, cmor_task
from ece2cmor3.cmor_source import create_cmor_source

log = logging.getLogger(__name__)

json_source_key = "source"
json_target_key = "target"
json_table_key = "table"
json_tables_key = "tables"
json_mask_key = "mask"
json_masked_key = "masked"
json_filepath_key = "filepath"

variable_prefs_file = os.path.join(os.path.dirname(__file__), "resources", "varprefs.csv")

omit_vars_file_01 = os.path.join(os.path.dirname(__file__), "resources/lists-of-omitted-variables",
                                 "list-of-omitted-variables-01.xlsx")
omit_vars_file_02 = os.path.join(os.path.dirname(__file__), "resources/lists-of-omitted-variables",
                                 "list-of-omitted-variables-02.xlsx")
omit_vars_file_03 = os.path.join(os.path.dirname(__file__), "resources/lists-of-omitted-variables",
                                 "list-of-omitted-variables-03.xlsx")
omit_vars_file_04 = os.path.join(os.path.dirname(__file__), "resources/lists-of-omitted-variables",
                                 "list-of-omitted-variables-04.xlsx")
omit_vars_file_05 = os.path.join(os.path.dirname(__file__), "resources/lists-of-omitted-variables",
                                 "list-of-omitted-variables-05.xlsx")
ignored_vars_file = os.path.join(os.path.dirname(__file__), "resources",
                                 "list-of-ignored-cmpi6-requested-variables.xlsx")
identified_missing_vars_file = os.path.join(os.path.dirname(__file__), "resources",
                                            "list-of-identified-missing-cmpi6-requested-variables.xlsx")

mask_predicates = {"=": lambda x, a: x == a,
                   "==": lambda x, a: x == a,
                   "!=": lambda x, a: x != a,
                   "<": lambda x, a: x < a,
                   "<=": lambda x, a: x <= a,
                   ">": lambda x, a: x > a,
                   ">=": lambda x, a: x >= a}

skip_tables = False
with_pingfile = False


# API function: loads the argument list of targets
# TODO: Refactor: Composition of simple task loading and dismissing intelligently
def load_targets(varlist, active_components=None, target_filters=None, config=None):
    global log
    requested_targets = read_targets(varlist)
    if target_filters is None:
        target_filters = {}
    for msg, func in target_filters.items():
        filtered_targets = filter(func, requested_targets)
        for tgt in list(set(requested_targets) - set(filtered_targets)):
            log.info("Dismissing %s target variable %s in table %s..." % (msg, tgt.variable, tgt.table))
        requested_targets = filtered_targets
    log.info("Found %d requested cmor target variables." % len(requested_targets))
    considered_targets = omit_targets(requested_targets)
    ignored_targets = [t for t in requested_targets if getattr(t, "load_status", None) == "ignored"]
    identified_missing_targets = [t for t in requested_targets if
                                  getattr(t, "load_status", None) == "identified missing"]
    missing_targets = [t for t in requested_targets if getattr(t, "load_status", None) == "missing"]
    matches = filter_targets(considered_targets, config)
    valid_matches = validate_matches(matches)
    loaded_targets = create_tasks(valid_matches, active_components)
    load_masks(load_model_vars())
    return loaded_targets, ignored_targets, identified_missing_targets, missing_targets


def validate_matches(matches):
    duplicates = {m: set() for m in matches.keys()}
    for model in matches.keys():
        targetlist = matches[model]
        n = len(targetlist)
        for i in range(n):
            t1 = targetlist[i]
            key1 = '_'.join([t1.variable, t1.table])
            okey1 = '_'.join([getattr(t1, "out_name", t1.variable), t1.table])
            if i < n - 1:
                for j in range(i + 1, n):
                    t2 = targetlist[j]
                    key2 = '_'.join([t2.variable, t2.key])
                    okey2 = '_'.join([getattr(t1, "out_name", t2.variable), t2.table])
                    if t1 == t2 or key1 == key2:
                        log.error("Found duplicate target %s in table %s for model %s: dismissing duplicate hit"
                                  % (t1.variable, t1.table, model))
                        duplicates[model].add(j)
                    elif okey1 == okey2:
                        log.error("Found duplicate output name for targets %s, %s in table %s for model %s: dismissing"
                                  " duplicate hit" % (t1.variable, t2.variable, t1.table, model))
                        duplicates[model].add(j)
            index = matches.keys().index(model) + 1
            if index < len(matches.keys()):
                for other_model in matches.keys()[index:]:
                    other_targetlist = matches[other_model]
                    for t2 in other_targetlist:
                        key2 = '_'.join([t2.variable, t2.key])
                        okey2 = '_'.join([getattr(t1, "out_name", t2.variable), t2.table])
                        if t1 == t2 or key1 == key2:
                            log.error("Found duplicate target %s in table %s for models %s and %s: dismissing "
                                      "duplicate hit" % (t1.variable, t1.table, model, other_model))
                            duplicates[other_model].add(other_targetlist.index(t2))
                        elif okey1 == okey2:
                            log.error(
                                "Found duplicate output name for targets %s, %s in table %s for models %s and %s: "
                                "dismissing duplicate hit" % (t1.variable, t2.variable, t1.table, model, other_model))
                            duplicates[other_model].add(other_targetlist.index(t2))
    result = {m : [] for m in matches.keys()}
    for model, targetlist in matches.items():
        for i in range(len(targetlist)):
            if i not in duplicates[model]:
                result[model].append(targetlist[i])
    return result


def read_targets(varlist):
    targetlist = []
    if isinstance(varlist, basestring):
        if os.path.isfile(varlist):
            fname, fext = os.path.splitext(varlist)
            if len(fext) == 0:
                targetlist = load_targets_f90nml(varlist)
            elif fext[1:] == "json":
                targetlist = load_targets_json(varlist)
            elif fext[1:] == "xlsx":
                targetlist = load_targets_excel(varlist)
            elif fext[1:] == "nml":
                targetlist = load_targets_f90nml(varlist)
            else:
                log.error("Cannot create a list of cmor-targets for file %s with unknown file type" % varlist)
    elif all(isinstance(t, cmor_target.cmor_target) for t in varlist):
        targetlist = varlist
    elif isinstance(varlist, dict):
        targetlist = []
        for table, val in varlist.iteritems():
            varseq = [val] if isinstance(val, basestring) else val
            for v in varseq:
                add_target(v, table, targetlist)
    else:
        log.error("Cannot create a list of cmor-targets for argument %s" % varlist)
    return targetlist


# Filters out ignored, identified missing and omitted targets from the input target list. Attaches attributes to the
# omitted targets to track what happened to the variable
def omit_targets(targetlist):
    omitvarlist_01 = load_checkvars_excel(omit_vars_file_01)
    omitvarlist_02 = load_checkvars_excel(omit_vars_file_02)
    omitvarlist_03 = load_checkvars_excel(omit_vars_file_03)
    omitvarlist_04 = load_checkvars_excel(omit_vars_file_04)
    omitvarlist_05 = load_checkvars_excel(omit_vars_file_05)
    omit_lists = {"omit 01": omitvarlist_01, "omit 02": omitvarlist_02, "omit 03": omitvarlist_03,
                  "omit 04": omitvarlist_04, "omit 05": omitvarlist_05}
    ignoredvarlist = load_checkvars_excel(ignored_vars_file)
    identifiedmissingvarlist = load_checkvars_excel(identified_missing_vars_file)
    filtered_list = []
    for target in targetlist:
        key = target.variable if skip_tables else (target.table, target.variable)
        if key in ignoredvarlist:
            target.ecearth_comment, target.comment_author = ignoredvarlist[key]
            setattr(target, "load_status", "ignored")
        elif key in identifiedmissingvarlist:
            setattr(target, "load_status", "identified missing")
            if with_pingfile:
                comment, author, model, units, pingcomment = identifiedmissingvarlist[key]
                setattr(target, "ecearth_comment", comment)
                setattr(target, "comment_author", author)
                setattr(target, "model", model)
                setattr(target, "units", units)
                setattr(target, "pingcomment", target.pingcomment)
            else:
                comment, author = identifiedmissingvarlist[key]
                setattr(target, "ecearth_comment", comment)
                setattr(target, "comment_author", author)
        elif any([key in omitvarlist for omitvarlist in omit_lists.values()]):
            for status, omitvarlist in omit_lists.items():
                if key in omitvarlist:
                    setattr(target, "load_status", status)
                    break
        else:
            filtered_list.append(target)
    return filtered_list


# Loads a json file containing the cmor targets.
def load_targets_json(varlist):
    vartext = open(varlist).read()
    varlist = json.loads(vartext)
    targets = []
    for tab, var in varlist.iteritems():
        if isinstance(var, basestring):
            add_target(var, tab, targets)
        else:
            for v in var:
                add_target(v, tab, targets)
    return targets


# Loads the legacy ece2cmorlib input namelists to targets
def load_targets_f90nml(varlist):
    global log
    import f90nml
    vlist = f90nml.read(varlist)
    targets = []
    for sublist in vlist["varlist"]:
        freq = sublist["freq"]
        vars2d = sublist.get("vars2d", [])
        vars3d = sublist.get("vars3d", [])
        for v in (vars2d + vars3d):
            tlist = ece2cmorlib.get_cmor_target(v)
            tgt = [t for t in tlist if t.frequency == freq]
            if len(tgt) == 0:
                log.error(
                    "Could not find cmor targets of variable %s with frequency %s in current set of tables" % (v, freq))
            targets.extend(tgt)
    return targets


# Loads a drq excel file containing the cmor targets.
def load_targets_excel(varlist):
    global log
    import xlrd
    targets = []
    cmor_colname = "CMOR Name"
    vid_colname = "vid"
    priority_colname = "Priority"  # Priority column name for the experiment   cmvme_*.xlsx files
    default_priority_colname = "Default Priority"  # Priority column name for the mip overview cmvmm_*.xlsx files
    mip_list_colname = "MIPs (by experiment)"
    book = xlrd.open_workbook(varlist)
    for sheetname in book.sheet_names():
        if sheetname.lower() in ["notes", "fx"]:
            continue
        sheet = book.sheet_by_name(sheetname)
        row = sheet.row_values(0)
        if cmor_colname not in row:
            log.error(
                "Could not find cmor variable column in sheet %s for file %s: skipping variable" % (sheet, varlist))
            continue
        index = row.index(cmor_colname)
        vid_index = row.index(vid_colname)
        if priority_colname in row:
            priority_index = row.index(priority_colname)
        elif default_priority_colname in row:
            # If no "Priority" column is found try to find a "Default Priority" column
            priority_index = row.index(default_priority_colname)
        else:
            # If no "Priority" column and no "Default Priority" column are found, abort with message
            raise Exception(
                "Error: Could not find priority variable column in sheet %s for file %s. Program has been aborted." % (
                    sheet, varlist))
        mip_list_index = row.index(mip_list_colname)
        varnames = [c.value for c in sheet.col_slice(colx=index, start_rowx=1)]
        vids = [c.value for c in sheet.col_slice(colx=vid_index, start_rowx=1)]
        priority = [c.value for c in sheet.col_slice(colx=priority_index, start_rowx=1)]
        mip_list = [c.value for c in sheet.col_slice(colx=mip_list_index, start_rowx=1)]
        for i in range(len(varnames)):
            add_target(str(varnames[i]), sheetname, targets, vids[i], priority[i], mip_list[i])
    return targets


# Small utility loading targets from the list
def add_target(variable, table, targetlist, vid=None, priority=None, mip_list=None):
    global log
    target = ece2cmorlib.get_cmor_target(variable, table)
    if target:
        if vid:
            target.vid = vid
        if priority:
            target.priority = priority
        if mip_list:
            target.mip_list = mip_list
        targetlist.append(target)
        return True
    else:
        log.error("The %s variable does not appear in the CMOR table file %s" % (variable, table))
    return False


# Loads the basic excel ignored file containing the cmor variables for which has been decided that they will be not
# taken into account or it loads the basic excel identified-missing file containing the cmor variables which have
# been identified but are not yet fully cmorized. This function can be used to read any excel file which has been
# produced by the checkvars.py script, in other words it can read the basic ignored, basic identified missing,
# available, ignored, identified-missing, and missing files.
def load_checkvars_excel(basic_ignored_excel_file):
    global log, skip_tables, with_pingfile
    import xlrd
    table_colname = "Table"
    var_colname = "variable"
    comment_colname = "comment"
    author_colname = "comment author"
    model_colname = "model component in ping file"
    units_colname = "units as in ping file"
    pingcomment_colname = "ping file comment"
    book = xlrd.open_workbook(basic_ignored_excel_file)
    varlist = {}
    for sheetname in book.sheet_names():
        if sheetname.lower() in ["notes"]:
            continue
        sheet = book.sheet_by_name(sheetname)
        header = sheet.row_values(0)
        coldict = {}
        for colname in [table_colname, var_colname, comment_colname, author_colname]:
            if colname not in header:
                log.error(
                    "Could not find the column '%s' in sheet %s for file %s: skipping sheet" % (
                        colname, sheet, varlist))
                continue
            coldict[colname] = header.index(colname)
        tablenames = [] if skip_tables else [c.value for c in
                                             sheet.col_slice(colx=coldict[table_colname], start_rowx=1)]
        varnames = [c.value for c in sheet.col_slice(colx=coldict[var_colname], start_rowx=1)]
        comments = [c.value for c in sheet.col_slice(colx=coldict[comment_colname], start_rowx=1)]
        authors = [c.value for c in sheet.col_slice(colx=coldict[author_colname], start_rowx=1)]
        model, units, pingcomment = [], [], []
        if with_pingfile:
            if model_colname not in header:
                # log.error("Could not find the column '%s' in sheet %s for file %s: skipping sheet" % (model_colname,
                # sheet, varlist))
                continue
            coldict[model_colname] = header.index(model_colname)
            model = [c.value for c in sheet.col_slice(colx=coldict[model_colname], start_rowx=1)]
            coldict[units_colname] = header.index(units_colname)
            units = [c.value for c in sheet.col_slice(colx=coldict[units_colname], start_rowx=1)]
            coldict[pingcomment_colname] = header.index(pingcomment_colname)
            pingcomment = [c.value for c in sheet.col_slice(colx=coldict[pingcomment_colname], start_rowx=1)]
        if skip_tables:
            for i in range(len(varnames)):
                if with_pingfile:
                    varlist[varnames[i]] = (comments[i], authors[i], model[i], units[i], pingcomment[i])
                else:
                    varlist[varnames[i]] = (comments[i], authors[i])
        else:
            for i in range(len(varnames)):
                varlist[(tablenames[i], varnames[i])] = (comments[i], authors[i])
    return varlist


def match_variables(targets, model_variables):
    global json_target_key
    # Return value: dictionary of models and lists of targets
    matches = {m: [] for m in components.models.keys()}
    # Loop over requested variables
    for target in targets:
        # Loop over model components
        for model, variable_mapping in model_variables.items():
            # Loop over supported variables by the component
            for parblock in variable_mapping:
                if matchvarpar(target, parblock):
                    if target in matches[model]:
                        raise Exception("Invalid model parameter file %s: multiple source found found for target %s "
                                        "in table %s" % (components.models[model][components.table_file],
                                                         target.variable, target.table))
                    else:
                        matches[model].append(target)
    return matches


# Checks whether the variable matches the parameter table block
def matchvarpar(target, parblock):
    result = False
    parvars = parblock.get(json_target_key, None)
    if isinstance(parvars, list) and target.variable in parvars:
        result = True
    if isinstance(parvars, basestring) and target.variable == parvars:
        result = True
    if hasattr(parblock, json_table_key) and target.table != parblock[json_table_key]:
        result = False
    if hasattr(parblock, json_tables_key) and target.table not in parblock[json_tables_key]:
        result = False
    return result


def load_prefs_file(tables, configs):
    mapping = {}
    with open(variable_prefs_file, 'r') as prefsfile:
        reader = csv.reader(prefsfile, delimiter=',')
        for row in reader:
            if row[1].strip() == "*":
                tabs = tables
            else:
                tabs = [row[1]]
            if row[3].strip() == "*":
                cfgs = configs
            else:
                cfgs = [row[3]]
            model_list = row[2].lstrip('[').rstrip(']').split()
            for tab in tabs:
                for cfg in cfgs:
                    mapping[(row[0], tab, cfg)] = model_list
    return mapping


# Creates tasks for the considered requested targets, using the parameter tables in the resource folder
def create_tasks(matches, active_components):
    global log, ignored_vars_file, json_table_key, skip_tables
    loaded_targets = []
    model_vars = load_model_vars()
    for model, targets in matches.items():
        if active_components is list and model not in active_components:
            continue
        parblocks = model_vars[model]
        for target in targets:
            parmatch = [b for b in parblocks if matchvarpar(target, b)][0]
            task = create_cmor_task(parmatch, target, model)
            comment_string = model + ' code name = ' + parmatch.get(json_source_key, "?")
            if cmor_source.expression_key in parmatch.keys():
                comment_string += ", expression = " + parmatch[cmor_source.expression_key]
            setattr(target, "ecearth_comment", comment_string)
            setattr(target, "comment_author", "automatic")
            ece2cmorlib.add_task(task)
            loaded_targets.append(target)
    log.info("Created %d ece2cmor tasks from input variable list." % len(loaded_targets))
    return loaded_targets


# Tests the targets against the model parameter table files and preferences file
def filter_targets(targets, config):

    # Load model component parameter tables
    model_vars = load_model_vars()

    # Match model component variables with requested targets
    matches = match_variables(targets, model_vars)

    matched_targets = [t for target_list in matches.values() for t in target_list]
    for t in matched_targets:
        if t not in matches:
            setattr(t, "load_status", "missing")

    # Check against preferences file
    if config is not None:
        prefslist = load_prefs_file(list(set([t.table for t in targets])), components.ece_configs)
        for key, preferred_models in prefslist:
            if key[2] != config:
                continue
            model_match = None
            for model in preferred_models:
                if any([t for t in matched_targets[model] if (t.variable, t.table) == (key[0], key[1])]):
                    model_match = model
                    break
            for model in matches:
                if model != model_match:
                    for t in matches[model]:
                        if (t.variable, t.table) == (key[0], key[1]):
                            log.info("Removing variable %s in table %s from targets for %s for configuration %s due to "
                                     "preference ordering..." % (t.variable, t.table, model, config))
                            matches[model].remove(t)
    return matches


def load_model_vars():
    model_vars = {}
    for m in components.models:
        tabfile = components.models[m].get(components.table_file, "")
        if os.path.isfile(tabfile):
            with open(tabfile) as f:
                model_vars[m] = json.loads(f.read())
        else:
            log.warning("Could not read variable table file %s for component %s" % (tabfile, m))
            model_vars[m] = []
    return model_vars


# TODO: Delegate to components
def load_masks(model_vars):
    for par in model_vars["ifs"]:
        if json_mask_key in par:
            name = par[json_mask_key]
            expr = par.get(cmor_source.expression_key, None)
            if not expr:
                log.error("No expression given for mask %s, ignoring mask definition" % name)
            else:
                srcstr, func, val = parse_maskexpr(expr)
                if srcstr:
                    src = create_cmor_source({json_source_key: srcstr}, "ifs")
                    ece2cmorlib.add_mask(name, src, func, val)


# Parses the input mask expression
# TODO: Delegate to components
def parse_maskexpr(exprstring):
    global mask_predicates
    ops = list(mask_predicates.keys())
    ops.sort(key=len)
    for op in ops[::-1]:
        tokens = exprstring.split(op)
        if len(tokens) == 2:
            src = tokens[0].strip()
            if src.startswith("var"):
                src = src[3:]
            if len(src.split(".")) == 1:
                src += ".128"
            func = mask_predicates[op]
            val = float(tokens[1].strip())
            return src, func, val
    log.error("Expression %s could not be parsed to a valid mask expression")
    return None, None, None


# Creates a single task from the target and parameter table entry
def create_cmor_task(pardict, target, component):
    global log, json_source_key
    source = create_cmor_source(pardict, component)
    if source is None:
        raise ValueError("Failed to construct a source for target variable %s in table %s...skipping task"
                         % (target.variable, target.table))
    task = cmor_task.cmor_task(source, target)
    mask = pardict.get(json_masked_key, None)
    if mask:
        setattr(task.target, cmor_target.mask_key, mask)
    for par in pardict:
        if par not in [json_source_key, json_target_key, json_mask_key, json_masked_key, json_table_key, "expr"]:
            setattr(task, par, pardict[par])
    return task
