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
    CONF_CLOUD_MODEL,
    CONF_CLOUD_CORRECTION_FACTOR,
    DEFAULT_CLOUD_CORRECTION_FACTOR,
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
            
            cloud_cover_data = await self._fetch_hourly_cloud_cover()
            self._adjust_estimate_with_cloud_cover(estimate, cloud_cover_data)
            
            for day in estimate.wh_days:
                date_str = day.isoformat()
                self.daily_forecasts[date_str] = estimate.wh_days[day]
            return estimate
        except Exception as error:
            LOGGER.error("Error fetching data: %s", error)
            raise OpenMeteoSolarForecastUpdateFailed(f"Error fetching data: {error}") from error

    async def _fetch_hourly_cloud_cover(self) -> list:
        """Fetch hourly cloud cover data from open-meteo.com."""
        
        latitude = clean_value(str(self.forecast.latitude))
        longitude = clean_value(str(self.forecast.longitude))
        cloud_cover_model=self.config_entry.options.get(CONF_CLOUD_MODEL,"best_match")
        LOGGER.debug("Fetching cloud cover data for latitude: %s, longitude: %s", latitude, longitude)
        
        # Obtenir des prévisions sur 7 jours avec un pas de temps horaire
        # Inclure les timestamps pour pouvoir aligner les données
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=cloud_cover&timeformat=iso8601&timezone=auto&models={cloud_cover_model}&forecast_days=7"
        LOGGER.debug("Fetching cloud cover data from URL: %s", url)
        
        async with self.forecast.session.get(url) as response:
            if response.status != 200:
                response_text = await response.text()
                LOGGER.error("Failed to fetch cloud cover data: %s. Response: %s", response.status, response_text)
                raise Exception(f"Failed to fetch cloud cover data: {response.status}")
            
            data = await response.json()
            
            # Stocker la réponse complète pour référence
            self.last_cloud_api_response = data
            
            cloud_cover_data = data.get("hourly", {}).get("cloud_cover", [])
            
            
            return cloud_cover_data

    def _adjust_estimate_with_cloud_cover(self, estimate: Estimate, cloud_cover_data: list) -> None:
        """Ajuster l'estimation solaire en fonction des données de nébulosité."""
        if not cloud_cover_data:
            LOGGER.warning("No cloud cover data available for adjustment")
            return
        
        # Stocker les données de nébulosité pour y accéder depuis le capteur de débogage
        self.cloud_cover_data = cloud_cover_data
        
        # Récupérer la liste des timestamps des données de nébulosité depuis l'API
        cloud_timestamps = []
        try:
            # Essayer de récupérer les timestamps depuis la dernière réponse API
            cloud_timestamps = self.last_cloud_api_response.get("hourly", {}).get("time", [])
        except (AttributeError, KeyError):
            LOGGER.warning("No cloud timestamp data available, using sequential hours")
        
        # Sauvegarder les valeurs originales avant ajustement pour comparaison
        self.original_values = {
            "watts": {str(k): v for k, v in estimate.watts.items()},
            "wh_period": {str(k): v for k, v in estimate.wh_period.items()},
            "wh_days": {str(k): v for k, v in estimate.wh_days.items()},
            "power_production_now": estimate.power_production_now,
            "energy_production_today": estimate.energy_production_today,
            "energy_production_tomorrow": estimate.energy_production_tomorrow
        }
        
        # Somme totale avant ajustement pour calculer le pourcentage
        total_energy_before = sum(estimate.wh_period.values())
        
        # Convertir les timestamps cloud en dictionnaire pour faciliter la recherche
        cloud_cover_dict = {}
        if cloud_timestamps:
            for i, timestamp_str in enumerate(cloud_timestamps):
                if i < len(cloud_cover_data):
                    # Convertir le format "2024-04-06T12:00" en datetime
                    try:
                        # Supprimer le 'T' et ajouter les secondes si nécessaire
                        dt_str = timestamp_str.replace('T', ' ')
                        if len(dt_str.split(':')) == 2:
                            dt_str += ':00'  # Ajouter les secondes si non présentes
                        cloud_dt = datetime.fromisoformat(dt_str)
                        cloud_cover_dict[cloud_dt] = cloud_cover_data[i]
                        # LOGGER.debug("Cloud timestamp mapping: %s -> %s%%", dt_str, cloud_cover_data[i])
                    except ValueError as e:
                        LOGGER.error("Error parsing timestamp %s: %s", timestamp_str, e)
        
        # Créer un journal de débogage pour les ajustements
        adjustment_log = {}
        
        # Ajuster les watts (puissance instantanée)
        for timestamp, watts in list(estimate.watts.items()):
            # Chercher la valeur de nébulosité pour ce timestamp spécifique
            cloud_cover_percent = 0
            
            if cloud_cover_dict:
                # Essayer de trouver le timestamp le plus proche
                closest_timestamp = None
                min_difference = timedelta(hours=24)  # Initialiser à une grande valeur
                
                # Convertir timestamp local en UTC si nécessaire pour la comparaison
                utc_timestamp = timestamp
                if timestamp.tzinfo:  # Si timestamp a une timezone
                    utc_timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
                
                for cloud_dt in cloud_cover_dict:
                    # Calculer la différence en ignorant les secondes/microsecondes
                    dt1 = utc_timestamp.replace(second=0, microsecond=0)
                    dt2 = cloud_dt.replace(second=0, microsecond=0)
                    difference = abs(dt1 - dt2)
                    
                    if difference < min_difference:
                        min_difference = difference
                        closest_timestamp = cloud_dt
                
                # Si on a trouvé un timestamp proche (moins de 2 heures de différence)
                if closest_timestamp and min_difference <= timedelta(hours=2):
                    cloud_cover_percent = cloud_cover_dict[closest_timestamp]
                    # LOGGER.debug(
                    #     "Matched timestamp %s with cloud data timestamp %s (diff: %s), cloud cover: %s%%",
                    #     timestamp, closest_timestamp, min_difference, cloud_cover_percent
                    # )
                else:
                    # Fallback à l'ancienne méthode basée sur l'heure du jour
                    day_offset = (timestamp.date() - estimate.now().date()).days
                    hour_index = timestamp.hour + (day_offset * 24)
                    
                    if 0 <= hour_index < len(cloud_cover_data):
                        cloud_cover_percent = cloud_cover_data[hour_index]
                        # LOGGER.debug(
                        #     "Using fallback hour index method for %s: day_offset=%s, hour=%s, index=%s, cloud cover: %s%%", 
                        #     timestamp, day_offset, timestamp.hour, hour_index, cloud_cover_percent
                        # )
            else:
                # Fallback à l'ancienne méthode basée sur l'heure du jour comme dernier recours
                day_offset = (timestamp.date() - estimate.now().date()).days
                hour_index = timestamp.hour + (day_offset * 24)
                
                if 0 <= hour_index < len(cloud_cover_data):
                    cloud_cover_percent = cloud_cover_data[hour_index]
            

            # Facteur d'ajustement: 100% de nébulosité = réduction de 70% (ajustable selon vos besoins)

            cloud_correction_factor = self.config_entry.options.get(CONF_CLOUD_CORRECTION_FACTOR, DEFAULT_CLOUD_CORRECTION_FACTOR)
            adjustment_factor = 1.0 - (cloud_cover_percent / 100.0 * cloud_correction_factor)
            adjusted_watts = watts * adjustment_factor
                 
            # Appliquer l'ajustement
            estimate.watts[timestamp] = adjusted_watts
        
        # Utiliser la même logique pour ajuster wh_period
        for timestamp, wh in list(estimate.wh_period.items()):
            # Même méthode d'alignement que pour watts
            cloud_cover_percent = 0
            
            # [Répéter la même logique d'alignement que ci-dessus]
            if cloud_cover_dict:
                # Trouver le timestamp le plus proche...
                # [code similaire à ci-dessus]
                pass
            else:
                # Fallback
                day_offset = (timestamp.date() - estimate.now().date()).days
                hour_index = timestamp.hour + (day_offset * 24)
                
                if 0 <= hour_index < len(cloud_cover_data):
                    cloud_cover_percent = cloud_cover_data[hour_index]
            
            adjustment_factor = 1.0 - (cloud_cover_percent / 100.0 * cloud_correction_factor)
            estimate.wh_period[timestamp] = wh * adjustment_factor
            
            # Ajouter au compteur de totaux pour les statistiques
            date_str = timestamp.date().isoformat()
            if date_str in adjustment_log:
                adjustment_log[date_str]["original_total"] += wh
                adjustment_log[date_str]["adjusted_total"] += (wh * adjustment_factor)
        
        # Pour wh_days, calculer une moyenne journalière de nébulosité
        date_cloud_cover = {}  # Stocke la couverture nuageuse moyenne par jour
        
        # Si nous avons des timestamps, calculer la moyenne par jour correctement
        if cloud_timestamps:
            for i, timestamp_str in enumerate(cloud_timestamps):
                if i < len(cloud_cover_data):
                    try:
                        dt_str = timestamp_str.replace('T', ' ')
                        cloud_dt = datetime.fromisoformat(dt_str)
                        date_str = cloud_dt.date().isoformat()
                        
                        if date_str not in date_cloud_cover:
                            date_cloud_cover[date_str] = {
                                "total": cloud_cover_data[i],
                                "count": 1
                            }
                        else:
                            date_cloud_cover[date_str]["total"] += cloud_cover_data[i]
                            date_cloud_cover[date_str]["count"] += 1
                    except ValueError:
                        pass
        # Sinon, faire une estimation plus basique
        else:
            # Diviser les données de cloud_cover_data en tranches de 24h
            for i in range(0, len(cloud_cover_data), 24):
                day_slice = cloud_cover_data[i:i+24]
                if day_slice:
                    day_idx = i // 24
                    today = estimate.now().date()
                    date = today + timedelta(days=day_idx)
                    date_cloud_cover[date.isoformat()] = {
                        "total": sum(day_slice),
                        "count": len(day_slice)
                    }
        
        # Ajuster wh_days avec la nébulosité moyenne par jour
        for day, wh in list(estimate.wh_days.items()):
            date_str = day.isoformat()
            if date_str in date_cloud_cover and date_cloud_cover[date_str]["count"] > 0:
                avg_cloud_cover = date_cloud_cover[date_str]["total"] / date_cloud_cover[date_str]["count"]
            else:
                # Fallback
                day_offset = (day - estimate.now().date()).days
                start_idx = day_offset * 24
                end_idx = start_idx + 24
                day_slice = cloud_cover_data[start_idx:end_idx] if 0 <= start_idx < len(cloud_cover_data) else []
                avg_cloud_cover = sum(day_slice) / len(day_slice) if day_slice else 0
                
            adjustment_factor = 1.0 - (avg_cloud_cover / 100.0 * 0.7)
            estimate.wh_days[day] = wh * adjustment_factor
            
            # Enregistrer pour le débogage ( A garder)
            LOGGER.debug(
                "Day adjustment - %s: avg cloud cover: %.1f%%, original: %.1f, adjusted: %.1f", 
                date_str, avg_cloud_cover, wh, (wh * adjustment_factor)
            )
        
        # Calculer les statistiques d'ajustement
        total_energy_after = sum(estimate.wh_period.values())
        adjustment_pct = ((total_energy_after - total_energy_before) / total_energy_before * 100) if total_energy_before else 0
        
        # Stocker les statistiques et le log d'ajustement
        self.adjustment_stats = {
            "average_cloud_cover": sum(cloud_cover_data[:24])/min(24, len(cloud_cover_data)) if cloud_cover_data else 0,
            "total_energy_before_adjustment": total_energy_before,
            "total_energy_after_adjustment": total_energy_after,
            "adjustment_percentage": adjustment_pct,
            "daily_adjustments": adjustment_log
        }
