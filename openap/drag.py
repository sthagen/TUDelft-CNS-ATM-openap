"""OpenAP drag model."""

import os
import importlib
import pandas as pd
import glob
import yaml
import math
import warnings
from . import prop
from .extra import ndarrayconvert


curr_path = os.path.dirname(os.path.realpath(__file__))
dir_dragpolar = curr_path + "/data/dragpolar/"
file_synonym = curr_path + "/data/dragpolar/_synonym.csv"

polar_synonym = pd.read_csv(file_synonym)


class Drag(object):
    """Compute the drag of aircraft."""

    def __init__(self, ac, wave_drag=False, **kwargs):
        """Initialize Drag object.

        Args:
            ac (string): ICAO aircraft type (for example: A320).
            wave_drag (bool): enable wave_drag model (experimental).

        """
        if not hasattr(self, "np"):
            self.np = importlib.import_module("numpy")

        if not hasattr(self, "aero"):
            self.aero = importlib.import_module("openap").aero

        self.use_synonym = kwargs.get("use_synonym", False)

        self.ac = ac.lower()
        self.aircraft = prop.aircraft(ac, **kwargs)
        self.polar = self.dragpolar()

        self.wave_drag = wave_drag
        if self.wave_drag:
            warnings.warn("Performance warning: Wave drag model is experimental.")

    def dragpolar(self):
        """Find and construct the drag polar model.

        Returns:
            dict: drag polar model parameters.

        """
        polar_files = glob.glob(dir_dragpolar + "*.yml")
        ac_polar_available = [s[-8:-4].lower() for s in polar_files]

        if self.ac in ac_polar_available:
            ac = self.ac
        else:
            syno = polar_synonym.query("orig==@self.ac")
            if self.use_synonym and syno.shape[0] > 0:
                ac = syno.new.iloc[0]
            else:
                raise RuntimeError(f"Drag polar for {self.ac} not avaiable in OpenAP.")

        f = dir_dragpolar + ac + ".yml"
        dragpolar = yaml.safe_load(open(f))
        return dragpolar

    @ndarrayconvert
    def _cl(self, mass, tas, alt, path_angle):
        v = tas * self.aero.kts
        h = alt * self.aero.ft
        gamma = path_angle * self.np.pi / 180

        S = self.aircraft["wing"]["area"]

        rho = self.aero.density(h)
        qS = 0.5 * rho * v ** 2 * S
        L = mass * self.aero.g0 * self.np.cos(gamma)
        qS = self.np.where(qS < 1e-3, 1e-3, qS)
        cl = L / qS
        return cl

    @ndarrayconvert
    def _calc_drag(self, mass, tas, alt, cd0, k, path_angle):
        v = tas * self.aero.kts
        h = alt * self.aero.ft
        gamma = path_angle * self.np.pi / 180

        S = self.aircraft["wing"]["area"]

        rho = self.aero.density(h)
        qS = 0.5 * rho * v ** 2 * S
        L = mass * self.aero.g0 * self.np.cos(gamma)
        qS = self.np.where(qS < 1e-3, 1e-3, qS)
        cl = L / qS
        cd = cd0 + k * cl ** 2
        D = cd * qS
        return D

    @ndarrayconvert
    def clean(self, mass, tas, alt, path_angle=0):
        """Compute drag at clean configuration (considering compressibility).

        Args:
            mass (int or ndarray): Mass of the aircraft (unit: kg).
            tas (int or ndarray): True airspeed (unit: kt).
            alt (int or ndarray): Altitude (unit: ft).
            path_angle (float or ndarray): Path angle (unit: degree). Defaults to 0.

        Returns:
            int: Total drag (unit: N).

        """

        cd0 = self.polar["clean"]["cd0"]
        k = self.polar["clean"]["k"]

        if self.wave_drag:
            mach = self.aero.tas2mach(tas * self.aero.kts, alt * self.aero.ft)
            cl = self._cl(mass, tas, alt, path_angle)

            sweep = math.radians(self.aircraft["wing"]["sweep"])
            tc = self.aircraft["wing"]["t/c"]
            if tc is None:
                tc = 0.11

            cos_sweep = math.cos(sweep)
            mach_crit = (
                0.87 - 0.108 / cos_sweep - 0.1 * cl / (cos_sweep ** 2) - tc / cos_sweep
            ) / cos_sweep

            dmach = self.np.where(mach - mach_crit <= 0, 0, mach - mach_crit)

            dCdw = self.np.where(dmach, 20 * dmach ** 4, 0)

        else:
            dCdw = 0

        cd0 = cd0 + dCdw

        D = self._calc_drag(mass, tas, alt, cd0, k, path_angle)
        return D

    @ndarrayconvert
    def nonclean(self, mass, tas, alt, flap_angle, path_angle=0, landing_gear=False):
        """Compute drag at at non-clean configuration.

        Args:
            mass (int or ndarray): Mass of the aircraft (unit: kg).
            tas (int or ndarray): True airspeed (unit: kt).
            alt (int or ndarray): Altitude (unit: ft).
            flap_angle (int or ndarray): flap deflection angle (unit: degree).
            path_angle (float or ndarray): Path angle (unit: degree). Defaults to 0.
            landing_gear (bool): Is landing gear extended? Defaults to False.

        Returns:
            int or ndarray: Total drag (unit: N).

        """
        cd0 = self.polar["clean"]["cd0"]
        k = self.polar["clean"]["k"]

        # --- calc new CD0 ---
        lambda_f = self.polar["flaps"]["lambda_f"]
        cfc = self.polar["flaps"]["cf/c"]
        SfS = self.polar["flaps"]["Sf/S"]

        delta_cd_flap = (
            lambda_f
            * (cfc) ** 1.38
            * (SfS)
            * self.np.sin(flap_angle * self.np.pi / 180) ** 2
        )

        if landing_gear:
            delta_cd_gear = (
                self.aircraft["limits"]["MTOW"]
                * 9.8065
                / self.aircraft["wing"]["area"]
                * 3.16e-5
                * self.aircraft["limits"]["MTOW"] ** (-0.215)
            )
        else:
            delta_cd_gear = 0

        cd0_total = cd0 + delta_cd_flap + delta_cd_gear

        # --- calc new k ---
        if self.aircraft["engine"]["mount"] == "rear":
            delta_e_flap = 0.0046 * flap_angle
        else:
            delta_e_flap = 0.0026 * flap_angle

        ar = self.aircraft["wing"]["span"] ** 2 / self.aircraft["wing"]["area"]
        k_total = 1 / (1 / k + self.np.pi * ar * delta_e_flap)

        D = self._calc_drag(mass, tas, alt, cd0_total, k_total, path_angle)
        return D
