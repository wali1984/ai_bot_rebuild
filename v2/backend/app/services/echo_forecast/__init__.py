"""Echo analog forecaster package — per-timeframe k-NN pattern-analog forecast."""

from app.services.echo_forecast.analog_forecaster import (
    PIT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    STATUS_INSUFFICIENT_DATA,
    STATUS_INVALID_INPUT,
    STATUS_OK,
    AnalogForecast,
    PITAnalogCandidate,
    PITAnalogForecast,
    PITCurrentWindow,
    compute_analog_forecast,
    compute_feature_schema_sha256,
    compute_outcome_schema_sha256,
    compute_pit_safe_analog_forecast,
)

__all__ = [
    "AnalogForecast",
    "PITAnalogCandidate",
    "PITAnalogForecast",
    "PITCurrentWindow",
    "PIT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_INVALID_INPUT",
    "STATUS_OK",
    "compute_analog_forecast",
    "compute_feature_schema_sha256",
    "compute_outcome_schema_sha256",
    "compute_pit_safe_analog_forecast",
]
