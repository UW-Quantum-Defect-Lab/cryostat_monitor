"""
This module contains the dataclasses `Measurement` and `TemperatureControllerMeasurement`.
These dataclasses are used to store the data of a single logging process
for the cryostat and temperature controller respectively.
"""

import datetime
from dataclasses import dataclass

MEASUREMENT_HEADER_MAP = {
    'timestamp': 'Timestamp',
    'pressure': 'Pressure (psi)',
    'refill_status': 'LN2 Refill Status',
    'sample_space_temperature': 'SS Temp (K)',
    'cold_head_temperature': 'CH Temp (K)',
    'cold_head_set_point': 'CH Set Point (K)',
    'cold_head_heater_percentage': 'CH Heater (%)',
    'helium_level': 'LHe Level (in)',
    'nitrogen_level': 'LN2 Level (in)'
}
"""
A map to convert `Measurement` dataclass attribute names to more visually appealing names.
"""


@dataclass
class Measurement:
    """ A dataclass that holds the data of a single cryostat logging process. """
    timestamp: datetime.datetime
    pressure: float
    refill_status: int
    sample_space_temperature: float
    cold_head_temperature: float
    cold_head_set_point: float
    cold_head_heater_percentage: float
    helium_level: float
    nitrogen_level: float


@dataclass
class TemperatureControllerMeasurement:
    """ A dataclass that holds the data of a single temperature controller measurement. """
    timestamp: datetime.datetime
    ch_temp: float
    ch_set_point: float
    ch_heater_range: int
    ch_heater_percent: float
    ch_manual_output: float
    ss_temp: float
    ss_set_point: float
    ss_heater_range: int
    ss_heater_percent: float
    ss_manual_output: float
