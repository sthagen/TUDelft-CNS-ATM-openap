"""OpenAP thrust model.

Simplified two-shaft turbonfan model base on:

    - M. Bartel, T. M. Young, Simplified Thrust and Fuel Consumption
    Models for Modern Two-Shaft Turbonfan Engines

    - C. Svoboda, Turbofan engine database as a preliminary desgin (cruise thrust)

"""

import importlib
from openap import prop
from openap.extra import ndarrayconvert


class Thrust(object):
    """Simplified two-shaft turbonfan model."""

    def __init__(self, ac, eng=None, **kwargs):
        """Initialize Thrust object.

        Args:
            ac (string): ICAO aircraft type (for example: A320).
            eng (string): Engine type (for example: CFM56-5A3).

        """
        if not hasattr(self, "np"):
            self.np = importlib.import_module("numpy")

        if not hasattr(self, "aero"):
            self.aero = importlib.import_module("openap").aero

        aircraft = prop.aircraft(ac, **kwargs)

        if eng is None:
            eng = aircraft["engine"]["default"]

        engine = prop.engine(eng)

        if type(aircraft["engine"]["options"]) == dict:
            eng_options = list(aircraft["engine"]["options"].values())
        elif type(aircraft["engine"]["options"]) == list:
            eng_options = list(aircraft["engine"]["options"])
        if engine["name"] not in eng_options:
            raise RuntimeError(
                f"Engine {eng} and aircraft {ac} mismatch. Available engines for {ac} are {eng_options}"
            )

        self.cruise_alt = aircraft["cruise"]["height"] / self.aero.ft
        # self.cruise_alt = 30000
        self.eng_bpr = engine["bpr"]
        self.eng_max_thrust = engine["max_thrust"]
        self.eng_number = aircraft["engine"]["number"]

        if engine["cruise_mach"] > 0:
            self.cruise_mach = engine["cruise_mach"]
            self.eng_cruise_thrust = engine["cruise_thrust"]
        else:
            self.cruise_mach = aircraft["cruise"]["mach"]
            self.eng_cruise_thrust = 0.2 * self.eng_max_thrust + 890

    def _dfunc(self, mratio):
        d = -0.4204 * mratio + 1.0824
        return d

    def _nfunc(self, roc):
        # n = self.np.where(roc<1500, 0.89, self.np.where(roc<2500, 0.93, 0.97))
        n = 2.667e-05 * roc + 0.8633
        return n

    def _mfunc(self, vratio, roc):
        m = -1.2043e-1 * vratio - 8.8889e-9 * roc ** 2 + 2.4444e-5 * roc + 4.7379e-1
        return m

    @ndarrayconvert
    def takeoff(self, tas, alt=None):
        """Calculate thrust at takeoff condition.

        Args:
            tas (float or ndarray): True airspeed (kt).
            alt (float or ndarray): Altitude of the runway (ft). Defaults to 0.

        Returns:
            float or ndarray: Total thrust (unit: N).

        """
        mach = self.aero.tas2mach(tas * self.aero.kts, 0)

        eng_bpr = self.eng_bpr
        G0 = 0.0606 * self.eng_bpr + 0.6337

        if alt is None:
            # at sea level
            ratio = (
                1
                - 0.377 * (1 + eng_bpr) / self.np.sqrt((1 + 0.82 * eng_bpr) * G0) * mach
                + (0.23 + 0.19 * self.np.sqrt(eng_bpr)) * mach ** 2
            )

        else:
            # at certain altitude
            P = self.aero.pressure(alt * self.aero.ft)
            dP = P / self.aero.p0

            A = -0.4327 * dP ** 2 + 1.3855 * dP + 0.0472
            Z = 0.9106 * dP ** 3 - 1.7736 * dP ** 2 + 1.8697 * dP
            X = 0.1377 * dP ** 3 - 0.4374 * dP ** 2 + 1.3003 * dP

            ratio = (
                A
                - 0.377
                * (1 + eng_bpr)
                / self.np.sqrt((1 + 0.82 * eng_bpr) * G0)
                * Z
                * mach
                + (0.23 + 0.19 * self.np.sqrt(eng_bpr)) * X * mach ** 2
            )

        F = ratio * self.eng_max_thrust * self.eng_number
        return F

    @ndarrayconvert
    def cruise(self, tas, alt):
        """Calculate thrust at the cruise.

        Args:
            tas (float or ndarray): True airspeed (kt).
            alt (float or ndarray): Altitude (ft).

        Returns:
            float or ndarray: Total thrust (unit: N).

        """
        return self.climb(tas, alt, roc=0)

    @ndarrayconvert
    def climb(self, tas, alt, roc):
        """Calculate thrust during the climb.

        Args:
            tas (float or ndarray): True airspeed (kt).
            alt (float or ndarray): Altitude(ft)
            roc (float or ndarray): Vertical rate (ft/min).

        Returns:
            float or ndarray: Total thrust (unit: N).

        """
        roc = self.np.abs(roc)

        h = alt * self.aero.ft
        tas = self.np.where(tas < 10, 10, tas)

        mach = self.aero.tas2mach(tas * self.aero.kts, h)
        vcas = self.aero.tas2cas(tas * self.aero.kts, h)

        P = self.aero.pressure(h)
        P10 = self.aero.pressure(10000 * self.aero.ft)
        Pcr = self.aero.pressure(self.cruise_alt * self.aero.ft)

        # approximate thrust at top of climb (REF 2)
        Fcr = self.eng_cruise_thrust * self.eng_number
        vcas_ref = self.aero.mach2cas(self.cruise_mach, self.cruise_alt * self.aero.ft)

        # segment 3: alt > 30000:
        d = self._dfunc(mach / self.cruise_mach)
        b = (mach / self.cruise_mach) ** (-0.11)
        ratio_seg3 = d * self.np.log(P / Pcr) + b

        # segment 2: 10000 < alt <= 30000:
        a = (vcas / vcas_ref) ** (-0.1)
        n = self._nfunc(roc)
        ratio_seg2 = a * (P / Pcr) ** (-0.355 * (vcas / vcas_ref) + n)

        # segment 1: alt <= 10000:
        F10 = Fcr * a * (P10 / Pcr) ** (-0.355 * (vcas / vcas_ref) + n)
        m = self._mfunc(vcas / vcas_ref, roc)
        ratio_seg1 = m * (P / Pcr) + (F10 / Fcr - m * (P10 / Pcr))

        ratio = self.np.where(
            alt > 30000, ratio_seg3, self.np.where(alt > 10000, ratio_seg2, ratio_seg1)
        )

        F = ratio * Fcr
        return F

    def descent_idle(self, tas, alt):
        """Idle thrust during the descent.

        Note: The idle thrust at the descent is taken as 7% of the maximum
        avaiable thrust. This may (likely) differ from actual idle thrust.

        Args:
            tas (float or ndarray): True airspeed (kt).
            alt (float or ndarray): Altitude(ft)

        Returns:
            float or ndarray: Total thrust (unit: N).

        """
        F = 0.07 * self.climb(tas, alt, roc=0)
        return F
