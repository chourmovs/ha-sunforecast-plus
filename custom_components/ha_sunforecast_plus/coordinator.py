"""DataUpdateCoordinator for the Sunforecast Plus integration."""
from __future__ import annotations
from datetime import timedelta, datetime, timezone
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .open_meteo_solar_forecast import Estimate, OpenMeteoSolarForecast

from .const import (
    CONF_AZIMUTH,
    CONF_BASE_URL,
    CONF_DAMPING_EVENING,
    CONF_DAMPING_MORNING,
    CONF_DECLINATION,
    CONF_EFFICIENCY_FACTOR,
    CONF_INVERTER_POWER,
    CONF_MODULES_POWER,
    CONF_MODEL,
    ##CONF_CLOUD_MODEL,
    ##CONF_CLOUD_CORRECTION_FACTOR,
    ##DEFAULT_CLOUD_CORRECTION_FACTOR,
    DOMAIN,
    LOGGER,
)
from .exceptions import OpenMeteoSolarForecastUpdateFailed

def clean_value(value):
    """Remove brackets and convert to float, then return as string."""
    if isinstance(value, str):
        value = value.strip('[]')
    cleaned_value = round(float(value), 2)
    LOGGER.debug("Cleaned value: %s", cleaned_value)
    return str(cleaned_value)

class OpenMeteoSolarForecastDataUpdateCoordinator(DataUpdateCoordinator[Estimate]):
    """The Solar Forecast Data Update Coordinator."""
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Solar Forecast coordinator."""
        self.config_entry = entry
        self.daily_forecasts = {}  # Dictionnaire pour stocker les prévisions journalières

        # Our option flow may cause it to be an empty string,
        # this if statement is here to catch that.
        api_key = entry.options.get(CONF_API_KEY) or None

        # Handle new options that were added after the initial release
        ac_kwp = entry.options.get(CONF_INVERTER_POWER, 0)
        ac_kwp = ac_kwp / 1000 if ac_kwp else None

        # Ensure latitude and longitude are valid numbers
        latitude = clean_value(entry.data[CONF_LATITUDE])
        longitude = clean_value(entry.data[CONF_LONGITUDE])
        if not (-90 <= float(latitude) <= 90) or not (-180 <= float(longitude) <= 180):
            raise ValueError("Invalid latitude or longitude values")

        self.forecast = OpenMeteoSolarForecast(
            api_key=api_key,
            session=async_get_clientsession(hass),
            latitude=float(latitude),
            longitude=float(longitude),
            azimuth=entry.options[CONF_AZIMUTH] - 180,
            base_url=entry.options[CONF_BASE_URL],
            ac_kwp=ac_kwp,
            dc_kwp=(entry.options[CONF_MODULES_POWER] / 1000),
            declination=entry.options[CONF_DECLINATION],
            efficiency_factor=entry.options[CONF_EFFICIENCY_FACTOR],
            damping_morning=entry.options.get(CONF_DAMPING_MORNING, 0.0),
            damping_evening=entry.options.get(CONF_DAMPING_EVENING, 0.0),
            weather_model=entry.options.get(CONF_MODEL, "best_match"),
        )

        # Initialiser les attributs pour le débogage
        self.cloud_cover_data = []
        self.original_values = {}
        self.adjustment_stats = {}

        update_interval = timedelta(minutes=30)

        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=update_interval)

    async def _async_update_data(self) -> Estimate:
        """Fetch Open-Meteo Solar Forecast estimates."""
        try:
            estimate = await self.forecast.estimate()
            
            for day in estimate.wh_days:
                date_str = day.isoformat()
                self.daily_forecasts[date_str] = estimate.wh_days[day]
            return estimate
        
        except Exception as error:
            LOGGER.error("Error fetching data: %s", error)
            raise OpenMeteoSolarForecastUpdateFailed(f"Error fetching data: {error}") from error
