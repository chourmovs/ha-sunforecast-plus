# HA SunForecast Plus Integration

SunForecast Plus is a custom Home Assistant integration designed to provide more accurate solar production forecasts using weather data from [Open-Meteo](https://open-meteo.com/).

Unlike other forecast integrations, **SunForecast Plus introduces a second-level correction based on cloud cover** percentage. Even small clouds can drastically reduce your solar production, so this integration applies a correction factor to account for cloud impact.

The integration uses the `cloud_cover_total` metric from Open-Meteo to adjust the expected solar output.

As shown below, different weather models (like Meteo-France or GFS) interpret 100% cloud cover differently:

![Cloud Cover Models](https://i.imgur.com/2ZTGl62.png)

**Tip:** Use the "lowest bidder" (e.g. `gfs_graphcast025`) and adjust the correction intensity with the `cloud_correction_factor`. A value of `0` disables cloud correction, while `1` applies full correction based on cloud cover.

You can test available models for your location [here](https://open-meteo.com/en/docs?hourly=temperature_2m,cloud_cover).


## Installation

### HACS

1. Go to the HACS page in your Home Assistant instance.
2. Click on `Integrations`.
3. Click on the three dots in the top right corner.
4. Click on `Custom repositories`.
5. Add `chourmovs/ha-sunforecast-plus` as the repository URL.
6. Click on `Category` and select `Integration`.
7. Click on `Add`.
8. A new custom integration shows up for installation "SunForecast Plus", install it.
9. Restart Home Assistant.


### Manual

1. Download the [latest release](https://github.com/chourmovs/ha-sunforecast-plus/releases/latest).
2. Unpack the release and copy the `custom_components/sunforecast_plus` directory to the `custom_components` directory in your Home Assistant configuration directory.
3. Restart Home Assistant.


## Configuration

To use this integration in your installation, head to "Settings" in the Home Assistant UI, then "Integrations". Click on the plus button and search for "Sun Forecast Plus" and follow the instructions.

Configuration part 1:

![Capture1](https://i.imgur.com/vUW141X.png)

Configuration part 2:

![Capture2](https://i.imgur.com/C8Pgflj.png)


**Tip**
To see the cloud-cover correction in action, activate the specific log in your configuration.yaml
```
logger:
  default: info
  logs:
    custom_components.ha_sunforecast_plus: debug
    custom_components.ha_sunforecast_plus.data_update_coordinator: debug
```
![Capture3](https://i.imgur.com/aJ0IIPw.png)

**Optional: Display Logs in your dashboard using Lovelace Card**

You can display recent adjustment logs using a markdown card in your dashboard. Here's an example:

```yaml
  type: markdown
  title: Logs ha_sunforecast_plus
  content: >
    ```text
    {% set log_lines = state_attr('sensor.solar_production_forecast_ha_sunforecast_logs', 'log_lines') %}
    {% if log_lines %}
      {% for line in log_lines %}
        {{ line.split("Day adjustment -")[1] }}
      {% endfor %}
    {% else %}
      No logs available.
    {% endif %}
```
## Common Mistakes

### API Key

This should be left blank as the Open-Meteo API does not require an API key. An API key is required for commercial use only per-Open-Meteo's [terms of service](https://open-meteo.com/en/terms).

### Azimuth

The azimuth range for this integration is 0 to 360 degrees, with 0 being North, 90 being East, 180 being South, and 270 being West. If you have a negative azimuth, add 360 to it to get the correct value. For example, -90 degrees should be entered as 270 degrees.

### DC Efficiency

The DC efficiency is the efficiency of the DC wiring and should not be confused with the cell efficiency. The DC efficiency is typically around 0.93. The cell efficiency is accounted for in the cell temperature calculation and is assumed to be 0.12.

### Confusing Power Sensors with Energy Sensors

The power sensors start with "Solar production forecast Estimated power" and the energy sensors start with "Solar production forecast Estimated energy". The power sensors show the power expected to be available at that time, and the energy sensors show the energy expected to be produced as an average over an hour.


### Disabled Sensors

Some sensors are disabled by default to reduce load on the recorder database. If you want one of these sensors, you can enable it and wait about a minute for sensor data to appear.

### Power Sensor Update Frequency

The power sensors update every 15 minutes, so you may not see immediate changes in the power sensors. They are not interpolated every minute. For example, consider that the integration knows that the power values will be as follows for the given instants:

- `12:00`: `100` W
- `12:15`: `200` W
- `12:30`: `300` W

If you check the "Power Now" sensor at:

- `12:00`, it will show `100` W (data taken from `12:00`)
- `12:15`, it will show `200` W (data taken from `12:15`)
- `12:22`, it will show `200` W (data taken from `12:15`)
- `12:37`, it will show `300` W (data taken from `12:30`)

Notice that the power sensor picks the last known value until the next update, not necessarily the closest value. Also, the power sensors are not interpolated, so the "Power Now" sensor will not show ~`150` W at `12:07`.



## Credits

This project was initially a fork of [rany2/ha-open-meteo-solar-forecast](https://github.com/rany2/ha-open-meteo-solar-forecast) for personal use, when I realised that improvement proposed was a nice step forward and needed their own life.

The [forecast_solar component code](https://github.com/home-assistant/core/tree/dev/homeassistant/components/forecast_solar) was used as a base for this integration. Thanks for such a clean starting point!

## ☕ Support this project

If you find this integration useful and want to support its development, consider [buying me a coffee](https://www.buymeacoffee.com/chourmovs):

[![Buy Me a Coffee](https://img.buymeacoffee.com/button-api/?text=Buy me a coffee&emoji=☕&slug=chourmovs&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff)](https://www.buymeacoffee.com/chourmovs)