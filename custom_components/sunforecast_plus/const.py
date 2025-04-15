"""Constants for the Open-Meteo Solar Forecast integration."""

from __future__ import annotations

import logging

DOMAIN = "sunforecast_plus"
LOGGER = logging.getLogger(__package__)

CONF_BASE_URL = "base_url"
CONF_DECLINATION = "declination"
CONF_AZIMUTH = "azimuth"
CONF_MODULES_POWER = "modules_power"
CONF_DAMPING_MORNING = "damping_morning"
CONF_DAMPING_EVENING = "damping_evening"
CONF_INVERTER_POWER = "inverter_power"
CONF_EFFICIENCY_FACTOR = "efficiency_factor"
CONF_MODEL = "model"
CONF_CLOUD_MODEL ="cloud_model"
CONF_CLOUD_CORRECTION_FACTOR = "cloud_correction_factor"
DEFAULT_CLOUD_CORRECTION_FACTOR = 0.7

ATTR_WATTS = "watts"
ATTR_WH_PERIOD = "wh_period"
