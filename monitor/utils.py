"""
This module implements utility methods that the cryostat and temperature controller GUIs use to
interact with devices, collect data and save data to files.
"""

import datetime
import random
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from devices.devices import PressureSensor, RefillStatusReader, TemperatureController, CryogenLevelSensor, \
    ArduinoForPressureAndRefill
from monitor.checks import get_monitor_report
from monitor.constants import DATA_FILENAME_FORMAT, FILE_TIMESTAMP_FORMAT
from monitor.measurement import Measurement, MEASUREMENT_HEADER_MAP, TemperatureControllerMeasurement


def get_new_pressure_sensor_instance() -> PressureSensor | None:
    """
    Returns a new instance of the pressure sensor.

    Returns
    -------
    PressureSensor | None
        A new instance of the pressure sensor or none if connection is not established.
    """
    try:
        pressure_sensor = PressureSensor()
        pressure_sensor.initialize()
        pressure_sensor.terminate()
        print(f'Successfully connected pressure sensor.')
        return pressure_sensor
    except Exception as e:
        print(f'Pressure sensor was not connected: {e}')

    return None


def get_new_refill_status_reader_instance() -> RefillStatusReader | None:
    """
    Returns a new instance of the refill status reader.

    Returns
    -------
    RefillStatusReader | None
        A new instance of the refill status reader or none if connection is not established.
    """
    try:
        refill_status_reader = RefillStatusReader()
        refill_status_reader.initialize()
        refill_status_reader.terminate()
        print(f'Successfully connected refill status reader.')
        return refill_status_reader
    except Exception as e:
        print(f'Refill status reader was not connected: {e}')

    return None


def get_arduino_for_pressure_and_refill_instance() -> ArduinoForPressureAndRefill | None:
    """
    Returns a new instance of the arduino for pressure and refill.

    Returns
    -------
    ArduinoForPressureAndRefill | None
        A new instance of the arduino for pressure and refill or none if connection is not established.
    """
    try:
        instance = ArduinoForPressureAndRefill.from_resource_port(ArduinoForPressureAndRefill.DEFAULT_PORT)
        print(f'Successfully connected Arduino Uno R3.')
        return instance
    except Exception as e:
        print(f'Arduino for pressure and refill was not connected: {e}')

    return None


def get_temperature_controller_instance() -> TemperatureController | None:
    """
    Returns a new instance of the temperature controller.

    Returns
    -------
    TemperatureController | None
        A new instance of the temperature controller or none if connection is not established.
    """
    try:
        instance = TemperatureController.from_resource_port(TemperatureController.DEFAULT_PORT)
        print(f'Successfully connected temperature controller.')
        return instance
    except Exception as e:
        print(f'Temperature controller was not connected: {e}')

    return None


def get_cryogen_level_sensor_instance() -> CryogenLevelSensor | None:
    """
    Returns a new instance of the cryogen level sensor.

    Returns
    -------
    TemperatureController | None
        A new instance of the cryogen level sensor or none if connection is not established.

    """
    try:
        instance = CryogenLevelSensor.from_resource_port(CryogenLevelSensor.DEFAULT_PORT)
        print(f'Successfully connected cryogen level sensor.')
        return instance
    except Exception as e:
        print(f'Cryogen level sensor was not connected: {e}')

    return None


def get_new_device_instances() \
        -> tuple[
            PressureSensor | None,
            RefillStatusReader | None,
            ArduinoForPressureAndRefill | None,
            TemperatureController | None,
            CryogenLevelSensor | None
        ]:
    """
    Returns new instances of all devices with which we were able to estable a connection.

    Returns
    -------
    tuple[PressureSensor | None, RefillStatusReader | None, ArduinoForPressureAndRefill | None, TemperatureController | None, CryogenLevelSensor | None]
        A tuple of all device instances with which a connection was established.
    """
    pressure_sensor = get_new_pressure_sensor_instance()
    refill_status_reader = get_new_refill_status_reader_instance()
    arduino_for_pressure_and_refill = get_arduino_for_pressure_and_refill_instance()
    temperature_controller = get_temperature_controller_instance()
    cryogen_level_sensor = get_cryogen_level_sensor_instance()

    return (pressure_sensor, refill_status_reader, arduino_for_pressure_and_refill,
            temperature_controller, cryogen_level_sensor)


def single_acquisition(
        pressure_sensor: PressureSensor = None,
        refill_status_reader: RefillStatusReader = None,
        arduino_for_pressure_and_refill: ArduinoForPressureAndRefill = None,
        temperature_controller: TemperatureController = None,
        cryogen_level_sensor: CryogenLevelSensor = None,
) -> Measurement:
    """
    Performs a single acquisition of data from all the devices.
    For each device that is not None, we
    1. Wait to acquire its lock,
    2. establish a momentary connection,
    3. perform the measurement,
    4. terminate the connection,
    5. and release the lock.

    Parameters
    ----------
    pressure_sensor : PressureSensor, optional
        The pressure sensor instance.
    refill_status_reader : RefillStatusReader, optional
        The refill status reader instance.
    arduino_for_pressure_and_refill : ArduinoForPressureAndRefill, optional
        The arduino for pressure and refill instance.
    temperature_controller : TemperatureController, optional
        The temperature controller instance.
    cryogen_level_sensor : CryogenLevelSensor, optional
        The cryogen level sensor instance.

    Returns
    -------
    Measurement
        The measured data.

    """

    if arduino_for_pressure_and_refill:
        arduino_for_pressure_and_refill.connect()
        arduino_for_pressure_and_refill._lock.acquire()

    timestamp = datetime.datetime.now()

    if pressure_sensor:
        with pressure_sensor._lock:
            pressure_sensor.initialize()
            pressure = pressure_sensor.read()
            pressure_sensor.terminate()
    elif arduino_for_pressure_and_refill:
        pressure = arduino_for_pressure_and_refill.read_pressure()
    else:
        pressure = np.nan

    if refill_status_reader:
        with refill_status_reader._lock:
            refill_status_reader.initialize()
            refill_status = refill_status_reader.read()
            refill_status_reader.terminate()
    elif arduino_for_pressure_and_refill:
        refill_status = arduino_for_pressure_and_refill.read_refill_status()
    else:
        refill_status = np.nan

    if arduino_for_pressure_and_refill:
        arduino_for_pressure_and_refill.disconnect()
        arduino_for_pressure_and_refill._lock.release()

    if temperature_controller:
        with temperature_controller._lock:
            temperature_controller.connect()
            sample_space_temperature = temperature_controller.get_sample_space_temperature()
            cold_head_temperature = temperature_controller.get_cold_head_temperature()
            cold_head_heater_percentage = temperature_controller.get_cold_head_heater_percentage()
            cold_head_set_point = temperature_controller.get_cold_head_set_point()
            temperature_controller.disconnect()
    else:
        sample_space_temperature = np.nan
        cold_head_temperature = np.nan
        cold_head_heater_percentage = np.nan
        cold_head_set_point = np.nan

    if cryogen_level_sensor:
        with cryogen_level_sensor._lock:
            cryogen_level_sensor.connect()
            helium_level = cryogen_level_sensor.read_helium_level()
            nitrogen_level = cryogen_level_sensor.read_nitrogen_level()
            cryogen_level_sensor.disconnect()
    else:
        helium_level = np.nan
        nitrogen_level = np.nan

    return Measurement(
        timestamp,
        pressure,
        refill_status,
        sample_space_temperature,
        cold_head_temperature,
        cold_head_set_point,
        cold_head_heater_percentage,
        helium_level,
        nitrogen_level
    )


def write_measurement_to_file(measurement: Measurement, parent_folder: str = ''):
    """
    Writes the measurement to a file that is of the format `DATA_FILENAME_FORMAT`.

    Parameters
    ----------
    measurement : Measurement
        The measurement to be written.
    parent_folder : str
        The parent folder to which the file should be written.
    """
    filename = measurement.timestamp.strftime(DATA_FILENAME_FORMAT)
    filepath = Path(parent_folder).joinpath(filename)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    data = pd.DataFrame(asdict(measurement), index=[0])
    data['timestamp'] = data['timestamp'].dt.strftime(FILE_TIMESTAMP_FORMAT)
    data.rename(columns=MEASUREMENT_HEADER_MAP, inplace=True)

    data.to_csv(filepath, mode="a", header=not filepath.is_file(), index=False)


def perform_real_logging_processes(
        pressure_sensor: PressureSensor = None,
        refill_status_reader: RefillStatusReader = None,
        arduino_for_pressure_and_refill: ArduinoForPressureAndRefill = None,
        temperature_controller: TemperatureController = None,
        cryogen_level_sensor: CryogenLevelSensor = None,
        folder: str = '',
):
    """
    Performs a real cryostat logging process (not randomized).

    During the logging process,
    1. data is retrieved via the `single_acquisition`,
    2. stored in a file via `write_measurement_to_file`,
    3. and a monitor report is created via `get_monitor_report`.

    Parameters
    ----------
    pressure_sensor : PressureSensor, optional
        The pressure sensor instance.
    refill_status_reader : RefillStatusReader, optional
        The refill status reader instance.
    arduino_for_pressure_and_refill : ArduinoForPressureAndRefill, optional
        The arduino for pressure and refill instance.
    temperature_controller : TemperatureController, optional
        The temperature controller instance.
    cryogen_level_sensor : CryogenLevelSensor, optional
        The cryogen level sensor instance.
    folder : str, optional
        The folder to which the measurement should be written.

    Returns
    -------
    Measurement
        The measured data.
    """
    measurement = single_acquisition(
        pressure_sensor, refill_status_reader, arduino_for_pressure_and_refill,
        temperature_controller, cryogen_level_sensor
    )
    write_measurement_to_file(measurement, folder)
    get_monitor_report(measurement)

    return measurement


def perform_dummy_logging_processes(folder: str = ''):
    """
    Performs a dummy cryostat logging process (randomized data).
    This method is used when no devices are detected.

    During the logging process,
    1. data is retrieved via the `single_acquisition`,
    2. stored in a file via `write_measurement_to_file`,
    3. and a monitor report is created via `get_monitor_report`.

    Parameters
    ----------
    folder : str, optional
        The folder to which the measurement should be written.

    Returns
    -------
    Measurement
        The measured dummy-data.
    """
    measurement = Measurement(
        datetime.datetime.now(),
        1 + random.random(),
        0,
        5 + 0.2 * random.random(),
        4.05 + 0.14 * random.random(),
        4.12,
        36.5 + 2 * random.random(),
        22.1,
        18
    )
    write_measurement_to_file(measurement, folder)
    get_monitor_report(measurement)

    return measurement


def temperature_controller_acquisition(temperature_controller: TemperatureController):
    """
    Acquire all data of interest for the temperature controller.

    Parameters
    ----------
    temperature_controller : TemperatureController
        The temperature controller instance.

    Returns
    -------
    TemperatureControllerMeasurement
        The measured temperature controller data.
    """
    with temperature_controller._lock:
        temperature_controller.connect()
        measurement = TemperatureControllerMeasurement(
            timestamp=datetime.datetime.now(),
            ch_temp=temperature_controller.get_cold_head_temperature(),
            ch_set_point=temperature_controller.get_cold_head_set_point(),
            ch_heater_range=temperature_controller.get_cold_head_heater_range(),
            ch_heater_percent=temperature_controller.get_cold_head_heater_percentage(),
            ch_manual_output=temperature_controller.get_cold_head_manual_output(),
            ss_temp=temperature_controller.get_sample_space_temperature(),
            ss_set_point=temperature_controller.get_sample_space_set_point(),
            ss_heater_range=temperature_controller.get_sample_space_heater_range(),
            ss_heater_percent=temperature_controller.get_sample_space_heater_percentage(),
            ss_manual_output=temperature_controller.get_sample_space_manual_output(),
        )
        temperature_controller.disconnect()

    return measurement


def dummy_temperature_controller_acquisition():
    """
    Creates dummy temperature controller data.
    This method is used when the temperature controller is not detected.

    Returns
    -------
    TemperatureControllerMeasurement
        The measured temperature controller data.
    """
    measurement = TemperatureControllerMeasurement(
        timestamp=datetime.datetime.now(),
        ch_temp=4.05 + 0.14 * random.random(),
        ch_set_point=4.12,
        ch_heater_range=2,
        ch_heater_percent=36.5 + 2 * random.random(),
        ch_manual_output=0.,
        ss_temp=5 + 0.2 * random.random(),
        ss_set_point=6,
        ss_heater_range=0,
        ss_heater_percent=0.,
        ss_manual_output=0.,
    )

    return measurement
