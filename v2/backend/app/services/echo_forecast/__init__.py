"""Echo analog forecaster package — per-timeframe k-NN pattern-analog forecast."""
from app.services.echo_forecast.analog_forecaster import (
    AnalogForecast,
    compute_analog_forecast,
    SCHEMA_VERSION,
)

__all__ = ["AnalogForecast", "compute_analog_forecast", "SCHEMA_VERSION"]
