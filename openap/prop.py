"""Retrive properties of aircraft and engines."""

import os
import glob
import yaml
import numpy as np
import pandas as pd

curr_path = os.path.dirname(os.path.realpath(__file__))
dir_aircraft = curr_path + "/data/aircraft/"
file_engine = curr_path + "/data/engine/engines.csv"
file_synonym = curr_path + "/data/aircraft/_synonym.csv"

aircraft_synonym = pd.read_csv(file_synonym) 

def available_aircraft(use_synonym=False):
    """Get available aircraft types in OpenAP model.

    Returns:
        list of string: aircraft types.

    """
    files = sorted(glob.glob(dir_aircraft + "*.yml"))
    acs = [f[-8:-4] for f in files]

    if use_synonym:
        syno = aircraft_synonym.orig.to_list()
        acs = acs + syno

    return acs


def aircraft(ac, use_synonym=False):
    """Get details of an aircraft type.

    Args:
        ac (string): ICAO aircraft type (for example: A320).

    Returns:
        dict: Performance parameters related to the aircraft.

    """
    ac = ac.lower()

    files = glob.glob(dir_aircraft + ac + ".yml")

    if len(files) == 0:
        syno = aircraft_synonym.query('orig==@ac')
        if use_synonym and syno.shape[0] > 0:
            new_ac = syno.new.iloc[0]
            files = glob.glob(dir_aircraft + new_ac + ".yml")
        else:
            raise RuntimeError(f"Aircraft {ac} not avaiable in OpenAP.")

    f = files[0]
    acdict = yaml.safe_load(open(f))

    return acdict


def aircraft_engine_options(ac):
    """Get engine options of an aircraft type.

    Args:
        ac (string): ICAO aircraft type (for example: A320).

    Returns:
        list of string: Engine options.

    """
    acdict = aircraft(ac)

    if type(acdict["engine"]["options"]) == dict:
        eng_options = list(acdict["engine"]["options"].values())
    elif type(acdict["engine"]["options"]) == list:
        eng_options = list(acdict["engine"]["options"])

    return eng_options


def search_engine(eng):
    """Search engine by the starting characters.

    Args:
        eng (string): Engine type (for example: CFM56-5).

    Returns:
        list or None: Matching engine types.

    """
    ENG = eng.strip().upper()
    engines = pd.read_csv(file_engine)

    available_engines = engines.query("name.str.startswith(@ENG)", engine="python")

    if available_engines.shape[0] == 0:
        print("Engine not found.")
        result = None
    else:
        print("Engines found:")
        result = available_engines.name.tolist()
        print(result)

    return result


def engine(eng):
    """Get engine parameters.

    Args:
        eng (string): Engine type (for example: CFM56-5B6).

    Returns:
        dict: Engine parameters.

    """
    ENG = eng.strip().upper()
    engines = pd.read_csv(file_engine)

    # try to look for the unique engine
    available_engines = engines.query(
        "name.str.upper().str.startswith(@ENG)", engine="python"
    )
    if available_engines.shape[0] >= 1:
        available_engines.index = available_engines.name

        seleng = available_engines.to_dict(orient="records")[0]
        seleng["name"] = eng

        # compute fuel flow correction factor kg/s/N per meter
        if np.isfinite(seleng["cruise_sfc"]):
            sfc_cr = seleng["cruise_sfc"]
            sfc_to = (seleng["fuel_c3"] + seleng["fuel_c2"] + seleng["fuel_c1"]) / (
                seleng["max_thrust"] / 1000
            )
            fuel_ch = np.round((sfc_cr - sfc_to) / (seleng["cruise_alt"] * 0.3048), 8)
        else:
            fuel_ch = 6.7e-7

        seleng["fuel_ch"] = fuel_ch
    else:
        raise RuntimeError(f"Data for engine {eng} not found.")

    return seleng


def func_fuel(c3, c2, c1):
    return lambda x: c3 * x ** 3 + c2 * x ** 2 + c1 * x
