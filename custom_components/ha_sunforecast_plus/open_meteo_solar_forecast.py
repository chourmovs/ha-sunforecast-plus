"""Asynchronous Python client for the API."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import datetime as dt
from typing import Any, Self

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_CLOUD_CORRECTION_FACTOR,
    CONF_CLOUD_MODEL,
    DEFAULT_CLOUD_CORRECTION_FACTOR,
    LOGGER,
)
from .constants import ALPHA_TEMP, G_STC, TEMP_STC_CELL, RossModelConstants
from .exceptions import (
    OpenMeteoSolarForecastAuthenticationError,
    OpenMeteoSolarForecastConfigError,
    OpenMeteoSolarForecastConnectionError,
    OpenMeteoSolarForecastError,
    OpenMeteoSolarForecastInvalidModel,
    OpenMeteoSolarForecastRatelimitError,
    OpenMeteoSolarForecastRequestError,
)
from .models import Estimate


@dataclass
class OpenMeteoSolarForecast:
    """Main class for handling connections with the API."""

    azimuth: float | list[float]
    declination: float | list[float]
    dc_kwp: float | list[float]
    latitude: float | list[float]
    longitude: float | list[float]
    config_entry: ConfigEntry

    past_days: int = 92
    forecast_days: int = 16

    ac_kwp: float | None = None
    api_key: str | None = None
    base_url: str | None = None
    weather_model: str | None = None
    damping_morning: float | list[float] = 0.0
    damping_evening: float | list[float] = 0.0
    efficiency_factor: float | list[float] = 1.0

    session: ClientSession | None = None
    _close_session: bool = False

    def __post_init__(self) -> None:
        """Initialize the OpenMeteoSolarForecast object."""
        if self.base_url is None:
            self.base_url = "https://api.open-meteo.com"
        if self.ac_kwp is None:
            self.ac_kwp = float("inf")

        if list in map(
            type,
            (
                self.azimuth,
                self.declination,
                self.dc_kwp,
                self.latitude,
                self.longitude,
            ),
        ):
            if not all(
                isinstance(param, list) and len(param) == len(self.dc_kwp)
                for param in (
                    self.azimuth,
                    self.declination,
                    self.dc_kwp,
                    self.latitude,
                    self.longitude,
                )
            ):
                raise OpenMeteoSolarForecastConfigError(
                    "The parameters must be of the same length"
                )
        else:
            self.azimuth = [self.azimuth]
            self.declination = [self.declination]
            self.dc_kwp = [self.dc_kwp]
            self.latitude = [self.latitude]
            self.longitude = [self.longitude]

        def test_param_len(attr_name: str, other_attr: list[Any]) -> list[Any]:
            """Validate the length of a param and return a list of the same length."""
            attr = getattr(self, attr_name)
            if isinstance(attr, list):
                if len(attr) != len(other_attr):
                    msg = f"{attr_name} must be the same length as the other parameters"
                    raise OpenMeteoSolarForecastConfigError(msg)
            else:
                attr = [attr] * len(other_attr)
            return attr

        self.efficiency_factor = test_param_len("efficiency_factor", self.dc_kwp)
        self.damping_morning = test_param_len("damping_morning", self.dc_kwp)
        self.damping_evening = test_param_len("damping_evening", self.dc_kwp)

    async def _request(
        self,
        uri: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Handle a request to the API."""
        if self.session is None:
            self.session = ClientSession()
            self._close_session = True

        if self.api_key:
            params = params or {}
            params["apikey"] = self.api_key

        if self.weather_model:
            if "," in self.weather_model:
                raise OpenMeteoSolarForecastInvalidModel(
                    "Multiple models are not supported"
                )
            params = params or {}
            params["models"] = self.weather_model

        response = await self.session.request(
            "GET",
            self.base_url + uri,
            params=params,
        )

        if response.status in (502, 503):
            raise OpenMeteoSolarForecastConnectionError("The API is unreachable")

        if response.status == 400:
            raise OpenMeteoSolarForecastRequestError("Bad request")

        if response.status in (401, 403):
            raise OpenMeteoSolarForecastAuthenticationError("Invalid API key")

        if response.status == 422:
            raise OpenMeteoSolarForecastConfigError("Invalid configuration")

        if response.status == 429:
            raise OpenMeteoSolarForecastRatelimitError("Rate limit exceeded")

        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            text = await response.text()
            raise OpenMeteoSolarForecastError(
                "Unexpected response from the API",
                {"Content-Type": content_type, "response": text},
            )

        return await response.json()

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        """Convert a value to float, returning None if invalid."""
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_open_meteo_timestamp(timestamp_str: str) -> datetime | None:
        """Parse an Open-Meteo timestamp safely."""
        try:
            dt_str = timestamp_str.replace("T", " ")
            if len(dt_str.split(":")) == 2:
                dt_str += ":00"
            return datetime.fromisoformat(dt_str)
        except ValueError as exc:
            LOGGER.debug("Invalid cloud timestamp %s: %s", timestamp_str, exc)
            return None

    async def _fetch_hourly_cloud_cover(self) -> tuple[list[str], list[float | None]]:
        """Fetch hourly cloud cover timestamps and values from Open-Meteo."""
        if self.session is None:
            self.session = ClientSession()
            self._close_session = True

        latitude = str(self.latitude[0])
        longitude = str(self.longitude[0])
        cloud_cover_model = self.config_entry.options.get(
            CONF_CLOUD_MODEL,
            "best_match",
        )

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "cloud_cover",
            "timeformat": "iso8601",
            "timezone": "auto",
            "models": cloud_cover_model,
            "forecast_days": "7",
        }

        LOGGER.debug(
            "Fetching cloud cover data for latitude=%s longitude=%s model=%s",
            latitude,
            longitude,
            cloud_cover_model,
        )

        async with self.session.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
        ) as response:
            if response.status != 200:
                response_text = await response.text()
                LOGGER.error(
                    "Failed to fetch cloud cover data: %s. Response: %s",
                    response.status,
                    response_text,
                )
                raise OpenMeteoSolarForecastConnectionError(
                    f"Failed to fetch cloud cover data: {response.status}"
                )

            data = await response.json()
            hourly = data.get("hourly", {})
            cloud_timestamps = hourly.get("time", [])
            raw_cloud_cover = hourly.get("cloud_cover", [])

            cloud_cover_data = [
                self._safe_float(value) for value in raw_cloud_cover
            ]

            LOGGER.debug(
                "Fetched %d cloud timestamps and %d cloud cover points",
                len(cloud_timestamps),
                len(cloud_cover_data),
            )

            return cloud_timestamps, cloud_cover_data

    def _build_cloud_cover_index(
        self,
        cloud_timestamps: list[str],
        cloud_cover_data: list[float | None],
    ) -> dict[datetime, float]:
        """Build a timestamp -> cloud cover dictionary."""
        cloud_cover_dict: dict[datetime, float] = {}

        for i, timestamp_str in enumerate(cloud_timestamps):
            if i >= len(cloud_cover_data):
                continue

            value = self._safe_float(cloud_cover_data[i])
            if value is None:
                continue

            cloud_dt = self._parse_open_meteo_timestamp(timestamp_str)
            if cloud_dt is None:
                continue

            cloud_cover_dict[cloud_dt] = value

        for cloud_dt, cloud_cover in cloud_cover_dict.items():
            LOGGER.debug(
                "Cloud timestamp %s -> %.2f%% cloud cover",
                cloud_dt.isoformat(),
                cloud_cover,
            )

        return cloud_cover_dict

    def _get_cloud_cover_for_timestamp(
        self,
        timestamp: dt,
        estimate: Estimate,
        cloud_cover_dict: dict[datetime, float],
        cloud_cover_data: list[float | None],
    ) -> float:
        """Resolve cloud cover for a given timestamp."""
        closest_timestamp: datetime | None = None
        min_difference = timedelta(hours=24)

        if cloud_cover_dict:
            compare_timestamp = timestamp
            if timestamp.tzinfo:
                compare_timestamp = timestamp.astimezone(timezone.utc).replace(
                    tzinfo=None
                )

            compare_timestamp = compare_timestamp.replace(second=0, microsecond=0)

            for cloud_dt in cloud_cover_dict:
                dt2 = cloud_dt.replace(second=0, microsecond=0)
                difference = abs(compare_timestamp - dt2)

                if difference < min_difference:
                    min_difference = difference
                    closest_timestamp = cloud_dt

            if closest_timestamp and min_difference <= timedelta(hours=2):
                value = cloud_cover_dict[closest_timestamp]
                if value > 0:
                    LOGGER.debug(
                        "Closest cloud timestamp for %s is %s with cloud cover %.2f%%",
                        timestamp,
                        closest_timestamp,
                        value,
                    )
                return value

        day_offset = (timestamp.date() - estimate.now().date()).days
        hour_index = timestamp.hour + (day_offset * 24)

        if 0 <= hour_index < len(cloud_cover_data):
            fallback_value = self._safe_float(cloud_cover_data[hour_index])
            if fallback_value is not None:
                LOGGER.debug(
                    "Fallback cloud cover for %s is %.2f%%",
                    timestamp,
                    fallback_value,
                )
                return fallback_value

        LOGGER.debug("No cloud cover data available for timestamp: %s", timestamp)
        return 0.0

    def _build_daily_cloud_cover(
        self,
        estimate: Estimate,
        cloud_timestamps: list[str],
        cloud_cover_data: list[float | None],
    ) -> dict[str, dict[str, float]]:
        """Build daily average cloud cover aggregates."""
        date_cloud_cover: dict[str, dict[str, float]] = {}

        if cloud_timestamps:
            for i, timestamp_str in enumerate(cloud_timestamps):
                if i >= len(cloud_cover_data):
                    continue

                value = self._safe_float(cloud_cover_data[i])
                if value is None:
                    continue

                cloud_dt = self._parse_open_meteo_timestamp(timestamp_str)
                if cloud_dt is None:
                    continue

                date_str = cloud_dt.date().isoformat()
                if date_str not in date_cloud_cover:
                    date_cloud_cover[date_str] = {
                        "total": value,
                        "count": 1.0,
                    }
                else:
                    date_cloud_cover[date_str]["total"] += value
                    date_cloud_cover[date_str]["count"] += 1.0
        else:
            for i in range(0, len(cloud_cover_data), 24):
                day_slice = [
                    value
                    for value in (
                        self._safe_float(v) for v in cloud_cover_data[i : i + 24]
                    )
                    if value is not None
                ]
                if day_slice:
                    day_idx = i // 24
                    today = estimate.now().date()
                    date_value = today + timedelta(days=day_idx)
                    date_cloud_cover[date_value.isoformat()] = {
                        "total": sum(day_slice),
                        "count": float(len(day_slice)),
                    }

        return date_cloud_cover

    def _get_daily_average_cloud_cover(
        self,
        day: datetime.date,
        estimate: Estimate,
        date_cloud_cover: dict[str, dict[str, float]],
        cloud_cover_data: list[float | None],
    ) -> float:
        """Resolve average cloud cover for a given day."""
        date_str = day.isoformat()
        if date_str in date_cloud_cover and date_cloud_cover[date_str]["count"] > 0:
            total = date_cloud_cover[date_str]["total"]
            count = date_cloud_cover[date_str]["count"]
            return total / count

        day_offset = (day - estimate.now().date()).days
        start_idx = day_offset * 24
        end_idx = start_idx + 24

        if 0 <= start_idx < len(cloud_cover_data):
            day_slice = [
                value
                for value in (
                    self._safe_float(v) for v in cloud_cover_data[start_idx:end_idx]
                )
                if value is not None
            ]
            if day_slice:
                return sum(day_slice) / len(day_slice)

        return 0.0

    async def _adjust_estimate_with_cloud_cover(
        self,
        estimate: Estimate,
        cloud_timestamps: list[str],
        cloud_cover_data: list[float | None],
    ) -> None:
        """Adjust solar estimates using cloud cover data."""
        LOGGER.debug("Starting adjustment of solar estimate using cloud cover data")

        if not cloud_cover_data:
            LOGGER.warning("No cloud cover data available for adjustment")
            return

        self.original_values = {
            "watts": {str(k): v for k, v in estimate.watts.items()},
            "wh_period": {str(k): v for k, v in estimate.wh_period.items()},
            "wh_days": {str(k): v for k, v in estimate.wh_days.items()},
            "power_production_now": estimate.power_production_now,
            "energy_production_today": estimate.energy_production_today,
            "energy_production_tomorrow": estimate.energy_production_tomorrow,
        }

        LOGGER.debug(
            "Retrieved %d cloud timestamps for adjustment",
            len(cloud_timestamps),
        )

        total_energy_before = sum(estimate.wh_period.values())
        cloud_cover_dict = self._build_cloud_cover_index(
            cloud_timestamps,
            cloud_cover_data,
        )
        adjustment_log: dict[str, dict[str, float]] = {}

        cloud_correction_factor = self.config_entry.options.get(
            CONF_CLOUD_CORRECTION_FACTOR,
            DEFAULT_CLOUD_CORRECTION_FACTOR,
        )

        for timestamp, watts in list(estimate.watts.items()):
            cloud_cover_percent = self._get_cloud_cover_for_timestamp(
                timestamp,
                estimate,
                cloud_cover_dict,
                cloud_cover_data,
            )
            adjustment_factor = 1.0 - (
                cloud_cover_percent / 100.0 * cloud_correction_factor
            )
            estimate.watts[timestamp] = watts * adjustment_factor

        for timestamp, wh in list(estimate.wh_period.items()):
            cloud_cover_percent = self._get_cloud_cover_for_timestamp(
                timestamp,
                estimate,
                cloud_cover_dict,
                cloud_cover_data,
            )
            adjustment_factor = 1.0 - (
                cloud_cover_percent / 100.0 * cloud_correction_factor
            )
            adjusted_wh = wh * adjustment_factor
            estimate.wh_period[timestamp] = adjusted_wh

            date_str = timestamp.date().isoformat()
            if date_str not in adjustment_log:
                adjustment_log[date_str] = {
                    "original_total": 0.0,
                    "adjusted_total": 0.0,
                }
            adjustment_log[date_str]["original_total"] += wh
            adjustment_log[date_str]["adjusted_total"] += adjusted_wh

        date_cloud_cover = self._build_daily_cloud_cover(
            estimate,
            cloud_timestamps,
            cloud_cover_data,
        )

        for day, wh in list(estimate.wh_days.items()):
            avg_cloud_cover = self._get_daily_average_cloud_cover(
                day,
                estimate,
                date_cloud_cover,
                cloud_cover_data,
            )
            adjustment_factor = 1.0 - (
                avg_cloud_cover / 100.0 * cloud_correction_factor
            )
            estimate.wh_days[day] = wh * adjustment_factor

            if avg_cloud_cover > 0:
                LOGGER.debug(
                    "Day adjustment - %s: avg cloud cover: %.1f%%, original: %.1f, adjusted: %.1f",
                    day.isoformat(),
                    avg_cloud_cover,
                    wh,
                    wh * adjustment_factor,
                )

        total_energy_after = sum(estimate.wh_period.values())
        adjustment_pct = (
            ((total_energy_after - total_energy_before) / total_energy_before * 100)
            if total_energy_before
            else 0
        )

        first_24h = [
            value
            for value in (
                self._safe_float(v) for v in cloud_cover_data[:24]
            )
            if value is not None
        ]

        self.adjustment_stats = {
            "average_cloud_cover": (
                sum(first_24h) / len(first_24h) if first_24h else 0
            ),
            "total_energy_before_adjustment": total_energy_before,
            "total_energy_after_adjustment": total_energy_after,
            "adjustment_percentage": adjustment_pct,
            "daily_adjustments": adjustment_log,
        }

        reduction = total_energy_before - total_energy_after
        percent_reduction = (
            100 * reduction / total_energy_before if total_energy_before else 0
        )
        if percent_reduction > 0:
            LOGGER.info(
                "Cloud correction applied: total energy before=%.2f kWh, after=%.2f kWh, reduction=%.2f%%",
                total_energy_before,
                total_energy_after,
                percent_reduction,
            )

    async def estimate(self) -> Estimate:
        """Get solar production estimations from the API."""
        w_avg: dict[dt, int] = defaultdict(int)
        w_inst: dict[dt, int] = defaultdict(int)
        wh_days: dict[dt, int] = defaultdict(int)

        def gen_power(gti: float, t_amb: float, eff: float) -> int:
            """Calculate the power generated by a solar panel."""
            temp_cell = t_amb + gti * RossModelConstants.NOT_SO_WELL_COOLED
            power = dc_wp
            power *= gti / G_STC
            power *= 1 + ALPHA_TEMP * (temp_cell - TEMP_STC_CELL)
            power *= eff
            return round(max(0, power))

        def calculate_damping_coefficient(
            time: dt,
            sunrise: dt,
            sunset: dt,
            damping_morning: float,
            damping_evening: float,
        ) -> float:
            """Calculate the damping coefficient for the current time."""
            morning_start = sunrise
            morning_end = sunrise + (sunset - sunrise) / 2
            evening_start = morning_end
            evening_end = sunset

            def linear_damping(start: dt, end: dt, damping: float) -> float:
                """Calculate the linear damping coefficient."""
                duration = end - start
                elapsed = time - start
                damping = 1.0 - damping
                return (elapsed / duration) * (1.0 - damping) + damping

            if morning_start <= time <= morning_end:
                return linear_damping(morning_start, morning_end, damping_morning)

            if evening_start <= time <= evening_end:
                return linear_damping(evening_end, evening_start, damping_evening)

            return 1.0

        utc_offset = None
        for (
            azimuth,
            declination,
            dc_kwp,
            latitude,
            lonitude,
            efficiency,
            damping_morning,
            damping_evening,
        ) in zip(
            self.azimuth,
            self.declination,
            self.dc_kwp,
            self.latitude,
            self.longitude,
            self.efficiency_factor,
            self.damping_morning,
            self.damping_evening,
            strict=True,
        ):
            params = {
                "latitude": str(latitude),
                "longitude": str(lonitude),
                "azimuth": str(azimuth),
                "tilt": str(declination),
                "minutely_15": (
                    "temperature_2m,"
                    "global_tilted_irradiance,"
                    "global_tilted_irradiance_instant"
                ),
                "daily": "sunrise,sunset",
                "forecast_days": str(self.forecast_days),
                "past_days": str(self.past_days),
                "timezone": "auto",
            }
            data = await self._request("/v1/forecast", params=params)

            gti_avg_arr = data["minutely_15"]["global_tilted_irradiance"]
            gti_inst_arr = data["minutely_15"]["global_tilted_irradiance_instant"]
            temp_arr = data["minutely_15"]["temperature_2m"]

            if utc_offset is None:
                utc_offset = data["utc_offset_seconds"]
            elif utc_offset != data["utc_offset_seconds"]:
                raise OpenMeteoSolarForecastConfigError(
                    "The UTC offset is not the same for all locations"
                )

            time_arr = [
                dt.strptime(time, "%Y-%m-%dT%H:%M").replace(
                    tzinfo=timezone(timedelta(seconds=utc_offset))
                )
                for time in data["minutely_15"]["time"]
            ]
            sunrise_dict = {
                dt.strptime(time, "%Y-%m-%dT%H:%M")
                .replace(tzinfo=timezone(timedelta(seconds=utc_offset)))
                .date(): dt.strptime(time, "%Y-%m-%dT%H:%M")
                .replace(tzinfo=timezone(timedelta(seconds=utc_offset)))
                for time in data["daily"]["sunrise"]
            }
            sunset_dict = {
                dt.strptime(time, "%Y-%m-%dT%H:%M")
                .replace(tzinfo=timezone(timedelta(seconds=utc_offset)))
                .date(): dt.strptime(time, "%Y-%m-%dT%H:%M")
                .replace(tzinfo=timezone(timedelta(seconds=utc_offset)))
                for time in data["daily"]["sunset"]
            }

            damping_factors = [
                calculate_damping_coefficient(
                    time,
                    sunrise_dict[time.date()],
                    sunset_dict[time.date()],
                    damping_morning,
                    damping_evening,
                )
                for time in time_arr
            ]

            dc_wp = dc_kwp * 1000

            for i, time in enumerate(time_arr):
                if i - 1 < 0:
                    continue

                if None in (
                    gti_avg_arr[i],
                    gti_inst_arr[i],
                    *temp_arr[i - 1 : i + 1],
                ):
                    continue

                g_avg = gti_avg_arr[i]
                g_inst = gti_inst_arr[i]
                temp_avg = (temp_arr[i] + temp_arr[i - 1]) / 2
                temp_inst = temp_arr[i - 1]
                time_start = time - timedelta(minutes=15)
                eff_damped = efficiency * damping_factors[i]

                w_avg[time_start] += gen_power(g_avg, temp_avg, eff_damped)
                w_inst[time_start] += gen_power(g_inst, temp_inst, eff_damped)

        ac_wp = self.ac_kwp * 1000
        for time in w_avg:
            w_avg[time] = min(w_avg[time], ac_wp)
        for time in w_inst:
            w_inst[time] = min(w_inst[time], ac_wp)

        wh_period: dict[dt, float] = {}
        wh_period_count: dict[dt, int] = {}
        for time, power in w_avg.items():
            hour = time.replace(minute=0, second=0, microsecond=0)
            wh_period[hour] = wh_period.get(hour, 0) + power
            wh_period_count[hour] = wh_period_count.get(hour, 0) + 1

        for time in wh_period:
            wh_period[time] /= wh_period_count[time]

        for time, power in wh_period.items():
            day = time.date()
            wh_days[day] = wh_days.get(day, 0) + power

        estimate = Estimate(
            watts=w_inst,
            wh_period=wh_period,
            wh_days=wh_days,
            api_timezone=timezone(timedelta(seconds=utc_offset)),
        )

        cloud_timestamps, cloud_cover_data = await self._fetch_hourly_cloud_cover()
        await self._adjust_estimate_with_cloud_cover(
            estimate,
            cloud_timestamps,
            cloud_cover_data,
        )

        return estimate

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

    async def __aenter__(self) -> Self:
        """Async enter."""
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit."""
        await self.close()
