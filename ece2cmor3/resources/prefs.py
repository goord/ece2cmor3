import logging

from ece2cmor3 import components, cmor_target


def keep_variable(target, model_component, ecearth_config):
    variable = target.variable
    table = target.table

    # If the component producing the variable is not in the configuration anyway, dismiss it
    if ecearth_config in components.ece_configs and model_component not in components.ece_configs.get(ecearth_config):
        return False

    # For tos, look at the requested grid to determine whether it should be nemo or ifs
    if variable == "tos":
        if "areacello" in getattr(target, "area_operator", []):
            return model_component == "nemo"
        if "areacella" in getattr(target, "area_operator", []):
            return model_component == "ifs"

    # For these basic meteorological variables, let them be produced by tm5 for the AER* tables and otherwise ifs
    if variable in ["pfull", "zg", "ps", "tas", "ua", "va", "o3"]:
        if table.startswith("AER"):
            return model_component == "tm5"
        else:
            return model_component == "ifs"

    # Soil moisture etc: prefer ifs over lpjguess in all cases (?)
    if variable in ["mrso", "mrsol", "mrsos", "mrro", "mrros", "tsl"]:
        return model_component == "ifs"

    # Carbon-cycle variables only activated in EC-EARTH-CC
    if variable in ["cfc12", "cfc13", "c14", "sf6", \
                    "bfe", "bfeos", "bsi", "bsios", "calc", "calcos", "chl", "chldiat", "chldiatos", \
                    "chlmisc", "chlmiscos", "chlos", "co3", "co3os", "co3satcalc", "co3satcalcos", \
                    "dcalc", "detoc", "detocos", "dfe", "dfeos", "dissic", "dissicnatos", "dissicos", \
                    "dissoc", "dissocos", "dpco2", "dpo2", "epc100", "epcalc100", "epfe100", "epsi100", \
                    "expc", "expcalc", "expfe", "expn", "expp", "expsi", "fbddtalk", "fbddtdic", "fbddtdife", \
                    "fbddtdin", "fbddtdip", "fbddtdisi", "fgco2", "fgo2", "fric", "frn", "froc", "fsfe", \
                    "fsn", "graz", "intdic", "intdoc", "intpbfe", "intpbsi", "intpcalcite", "intpn2", \
                    "intpp", "intppcalc", "intppdiat", "intppmisc", "intppnitrate", "limfediat", "limfemisc", \
                    "limirrdiat", "limirrmisc", "limndiaz", "limnmisc", "nh4", "nh4os", "no3", "no3os", "o2", \
                    "o2min", "o2os", "pbfe", "pbsi", "pcalc", "ph", "phos", "phyc", "phycos", "phydiat", \
                    "phydiatos", "phyfe", "phyfeos", "phymisc", "phymiscos", "physi", "physios", "pnitrate", \
                    "po4", "po4os", "pp", "ppdiat", "ppmisc", "ppos", "remoc", "si", "sios", "spco2", "talk", \
                    "talknatos", "talkos", "zmeso", "zmesoos", "zmicro", "zmicroos", "zo2min", "zooc", "zoocos"]:
        return model_component == "nemo" and ecearth_config == "EC-EARTH-CC"
        # The list above from the second line on is created by using:
        #  more basic-flat-cmip6-file_def_nemo.xml |grep pisces| sed -e 's/field_ref.*//' -e 's/^.*name=//' | sed -e 's/" .*$/",/' |sort |uniq > pisces-vars.txt

    return True


def choose_variable(target_list, model_component, ecearth_config):
    # For IFS, skip 3D variables on small level subsets in favor of extended level sets
    if model_component == "ifs":
        result = []
        level_sets = [cmor_target.get_z_axis(t) for t in target_list]
        for i in range(len(level_sets)):
            level_type, levels = level_sets[i][0], set(level_sets[i][1])
            add_to_list = True
            for level_type_other, levels_other in level_sets:
                if level_type == level_type_other and levels.issubset(set(levels_other)) \
                        and not set(levels_other).issubset(levels):
                    add_to_list = False
                    break
            if add_to_list:
                result.append(target_list[i])
        # Incompatible variables fix: zg7h and zg27
        vartabs = [(t.table, t.variable) for t in result]
        if ("6hrPlevPt", "zg7h") in vartabs and ("6hrPlevPt", "zg27") in vartabs:
            result.remove([t for t in target_list if (t.table, t.variable) == ("6hrPlevPt", "zg27")][0])
        return result
    return target_list
