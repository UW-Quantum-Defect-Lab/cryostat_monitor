"""
This module provides base classes for interacting with NIDAQ analog inputs and PyVISA message-based devices.
These interfaces are used to define specific devices.
"""

import enum
import threading
import time
import warnings
from functools import partial
from typing import Callable, Type

import nidaqmx
import nidaqmx.error_codes
import nidaqmx.system
import numpy as np
import pandas as pd
from pyvisa import ResourceManager, VisaIOError
from pyvisa.attributes import Attribute
from pyvisa.resources import MessageBasedResource

from devices.constants import SAMPLE_SPACE_WARMED_UP_TEMP
from devices.utils import MessageBasedResourceType, _str_is_float, force_clear_message_based_resource, _convert_str, \
    find_available_resources_by_visa_attribute, find_available_resources_by_idn


resource_manager = ResourceManager()
ni_local_system = nidaqmx.system.System.local()


class NIDAQAnalogInput:
    """
    This class is a wrapper for the NIDAQ analog input. It allows you to read the voltage on the input channel
    and apply a response function to it.

    The response function is a polynomial function that maps the voltage on the daq to the output.

    Attributes
    ----------
    device_name : str
        The name of the connected DAQ device (e.g., 'Dev1')
    channel_name : str
        The name of the analog input channel on the DAQ device (e.g., 'ai0')
    instrument_repr_name : str
        A formatted representation of the instrument name, device name, and channel name.
    response_function_method : Callable | None
        The custom response function method to convert voltage to value. Giving a `response_function_method`
        overwrites the class's default method, resulting in dismissal of the `response_function_file`
        [Not implemented]
    response_function_file : str | None
        The path to a CSV file containing the response function for voltage-to-value conversion.
    response_function_poly_order : int
        The polynomial order for fitting the response function.
    response_curve : list
        The coefficients of the response function polynomial.

    """

    INSTRUMENT_NAME: str = 'NIDAQ Analog Input'
    """ The name of the instrument associated with the analog input (e.g. 'Pressure Gauge'). """

    def __init__(self, device_name: str, channel_name: str,
                 response_function_method: Callable = None, response_function_file: str = None,
                 response_function_poly_order: int = 4):

        """
        Parameters
        ----------
        device_name : str
            The name of the connected DAQ device (e.g., 'Dev1')
        channel_name : str
            The name of the analog input channel on the DAQ device (e.g., 'ai0')
        response_function_method : Callable, optional
            The custom response function method to convert voltage to value. Giving a `response_function_method`
            overwrites the class's default method, resulting in dismissal of the `response_function_file`
            [Not implemented]
        response_function_file : str, optional
            The path to a CSV file containing the response function for voltage-to-value conversion.
            The file must have two columns, and have a header.
            The first column must be the output value you want, the second must be the corresponding voltage output.

        response_function_poly_order : int, optional
            The polynomial order for fitting the response function. Default is 4.

        Notes
        -----
        Default response function is a linear response, meaning that a voltage reading will be returned as is.

        Raises
        ------
        nidaqmx.DaqError
            If the DAQ device is not connected or if an error occurs during initialization or termination.

        Warns
        -----
        UserWarning
            If there is a method error during initialization, a task is still running during termination,
            or voltage reading failure during the read operation.
        """

        self.device_name = device_name
        if not self.is_daq_connected():
            raise self._device_not_connected_error()
        self.channel_name = channel_name
        self.instrument_repr_name = f'{self.INSTRUMENT_NAME} ({self.device_name}/{self.channel_name})'

        if response_function_method is not None:
            self.response_function_method = response_function_method

        self.response_function_file = response_function_file
        self.response_function_poly_order = response_function_poly_order

        self.response_curve = [1, 0]
        if self.response_function_file is not None:
            file_df = pd.read_csv(self.response_function_file)
            self.response_curve = np.polyfit(file_df[file_df.keys()[1]], file_df[file_df.keys()[0]],
                                             self.response_function_poly_order)

        self.task: nidaqmx.Task | None = None
        self.channel = None

    def is_daq_connected(self):
        """ Check if the specific DAQ device is connected. """
        connected_device_names = [device.name for device in ni_local_system.devices]
        return self.device_name in connected_device_names

    def initialize(self):
        """ Initialize the DAQ task and channel for analog input. """
        if not self.is_daq_connected():
            raise self._device_not_connected_error()
        try:
            self.task = nidaqmx.Task()
            self.channel = self.task.ai_channels.add_ai_voltage_chan(self.channel_name)
        except nidaqmx.errors.Error:
            warnings.warn(f'{self.instrument_repr_name}: '
                          'NI DAQmx method error during initialization. '
                          'Check instrument name or if instrument is available')

    def terminate(self):
        """ Terminate the DAQ task and channel. """
        if not self.is_daq_connected():
            raise self._device_not_connected_error()
        try:
            if self.task.is_task_done():
                try:
                    self.task.close()
                    self.task = None
                    self.channel = None
                    # print(self.instrument_repr_name + ': Instrument successfully terminated')
                except nidaqmx.errors.Error:
                    warnings.warn(self.instrument_repr_name + ': NI DAQmx Method Error. Could not clear task.')
            else:
                warnings.warn(self.instrument_repr_name + ': Task is still running')
        except nidaqmx.errors.DaqError:
            pass
            # print(self.instrument_repr_name + ': Task already terminated')

    def voltage_to_value(self, voltage):
        """ Convert voltage to a corresponding value using the response function. """
        return np.polyval(self.response_curve, voltage)

    def read(self):
        """ Read and convert the channel voltage output to a value."""
        if self.task is not None:
            voltage = self.task.read()
            return self.voltage_to_value(voltage)
        else:
            warnings.warn(self.instrument_repr_name + ': Voltage reading failure. Task is not running.')
            return np.nan

    def _device_not_connected_error(self):
        """ Returns 'not connected' `nidaqmx.DaqError`. """
        return nidaqmx.DaqError(f'Device {self.device_name} is not connected.',
                                nidaqmx.error_codes.DAQmxErrors.NO_CABLED_DEVICE)


class MessageBasedDevice:
    """
    A class representing a message-based device with advanced communication capabilities.

    Attributes
    ----------

    _lock: threading.RLock
        A lock for thread-safe communication operations.
        Make sure to acquire lock before performing any operations (even establishing a connection).
    mediator: pyvisa.resources.MessageBasedResource | pyvisa.resources.SerialInstrument |
            pyvisa.resources.USBInstrument | pyvisa.resources.GPIBInstrument
        The mediator object that provides a communication interface between the computer and the device.
    instrument_repr_name:  str
        A formatted representation of the instrument name and device name.
    """

    CLEAR: str = '*CLR'
    """ The command for clearing the device. """

    WRITE_TERMINATION: str = '\r\n'
    """ The termination string for write operations. """
    READ_TERMINATION: str = '\n'
    """ The termination string for read operations. """

    QUERY_DELAY = 10 ** -9
    """ 
    The delay between write and read operations when querying the device in seconds. 
    Even the smallest delay will prevent your read-operation from raising a timeout error.
    """
    POST_COMMUNICATION_DELAY = 10 ** -9
    """ The delay after communication operations in seconds. """

    POST_CONNECTION_DELAY = 0
    """ The delay after establishing a connection in seconds. """

    INSTRUMENT_NAME = 'Unidentified Instrument'
    """ The default name for an unidentified instrument. """

    def __init__(self, mediator: MessageBasedResourceType):
        """
        Parameters
        ----------
            mediator: pyvisa.resources.MessageBasedResource | pyvisa.resources.SerialInstrument |
            pyvisa.resources.USBInstrument | pyvisa.resources.GPIBInstrument
        The mediator object that provides a communication interface between the computer and the device.
        """
        self._lock = threading.RLock()
        self.mediator = mediator
        self.connect()
        self.instrument_repr_name = f'{self.INSTRUMENT_NAME} ({self.mediator.resource_name})'
        self.disconnect()

    def connect(self):
        """ If disconnected, establish a connection to the message-based device. """
        with self._lock:
            if self.is_connected():
                return
            self.mediator.open()
            if self.POST_CONNECTION_DELAY:
                time.sleep(self.POST_CONNECTION_DELAY)
            else:
                time.sleep(self.POST_COMMUNICATION_DELAY)
            self.clear(with_lock=False)

    def disconnect(self):
        """ If connected, terminate the connection to the message-based device. """
        with self._lock:
            if not self.is_connected():
                return
            self.clear(with_lock=False)
            self.mediator.before_close()
            time.sleep(self.POST_COMMUNICATION_DELAY)
            self.mediator.close()
            time.sleep(self.POST_COMMUNICATION_DELAY)

    def is_connected(self, with_lock=False):
        """
        Check if the device is currently connected.

        Parameters
        ----------
        with_lock : bool, optional
            Use a lock when checking the connection status. Default is False.

        Returns
        -------
        bool
            True if connected, False otherwise.
        """
        def action():
            # Accessing the session property itself will raise an InvalidSession exception if the session is not open.
            return self.mediator._session is not None
        
        if with_lock:
            with self._lock:
                return action()
        else:
            return action()

    def clear(self, force: bool = False, with_lock: bool = True):
        """
        Clear the device, optionally forcing the clear operation.

        Parameters
        ----------
        force : bool, optional
            Force the clear operation. Default is False.
        with_lock : bool, optional
            Use a lock when performing the clear operation. Default is True.
        """
        def action():
            if not self.is_connected():
                return
            try: 
                self.mediator.clear()
                time.sleep(self.POST_COMMUNICATION_DELAY)
            except VisaIOError as e:
                pass  # Device does not support the clear operation
            if force:
                self.safe_write(self.CLEAR)
                time.sleep(self.POST_COMMUNICATION_DELAY)
                force_clear_message_based_resource(self.mediator)

        if with_lock:
            with self._lock:
                action()
        else:
            action()

    def __del__(self):
        """ Disconnect and clean up the instance on deletion. """
        self.disconnect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """ Disconnect the device upon exiting. """
        self.disconnect()

    @staticmethod
    def form_message(primary_command, is_query: bool = True, channel: int | str = None):
        """
        Form a message for a given primary command, with optional query and channel.

        Parameters
        ----------
        primary_command : str
            The primary command for the message.
        is_query : bool, optional
            Specify if the message is a query. Default is True. If true, appends a '?' after the primary command.
        channel : int or str, optional
            The channel information to include in the message. If not None, appends the value after the end of the
            command (after '?' if applicable), adding a space in between. (e.g., 'MEAS? 1')

        Returns
        -------
        str
            The formed message.
        """
        message = primary_command
        if is_query:
            message += '?'
        if channel is not None:
            message += f' {channel}'
        return message

    def safe_query(self, message: str, delay: float | None = None, until_buffer_empty: bool = False) -> str:
        """
        Safely (with lock and connection check) query the device,
        handling communication delays and buffer considerations.

        Parameters
        ----------
        message : str
            The query message to send to the device.
        delay : float or None, optional
            Additional delay after the query's write operation
            (inherited from `pyvisa.resource.MessageBasedResource.query()`). Default is None.
        until_buffer_empty : bool, optional
            Recursively retrieve all data in buffer, if buffer is not empty. Default is False.

        Returns
        -------
        str
            The response from the device.
        """
        with self._lock:
            if not self.is_connected():
                return ''
            response = self.mediator.query(message, delay)
            time.sleep(self.POST_COMMUNICATION_DELAY)
            if until_buffer_empty:
                while self.mediator.bytes_in_buffer > 0:
                    response += self.mediator.read()
                    time.sleep(self.POST_COMMUNICATION_DELAY)
        return response

    def safe_write(self, message: str, termination: str | None = None, encoding: str | None = None):
        """
        Safely (with lock and connection check) write a message to the device.
        Same as `pyvisa.resources.MessageBasedResource.write()`.

        Parameters
        ----------
        message : str
            The message to write to the device.
        termination : str or None, optional
            The termination string for the write operation. Default is None.
        encoding : str or None, optional
            The encoding to use for the message. Default is None.
        """
        with self._lock:
            if not self.is_connected():
                return
            self.mediator.write(message, termination, encoding)
            time.sleep(self.POST_COMMUNICATION_DELAY)

    def safe_read(self, termination: str | None = None, encoding: str | None = None,
                  check_buffer_before: bool = False, until_buffer_empty: bool = False) -> str:
        """
        Safely (with lock and connection check) read from the device,
        considering termination, encoding, and buffer conditions.

        Parameters
        ----------
        termination : str or None, optional
            The termination string for the read operation. Default is None.
        encoding : str or None, optional
            The encoding to use for reading. Default is None.
        check_buffer_before : bool, optional
            Check if the device buffer is empty before reading. Default is False.
        until_buffer_empty : bool, optional
            Wait until the device buffer is empty before returning. Default is False.

        Returns
        -------
        str
            The read response from the device.
        """
        with self._lock:
            if not self.is_connected():
                return ''
            if check_buffer_before:
                if self.mediator.bytes_in_buffer == 0:
                    return ''
            response = self.mediator.read(termination, encoding)
            time.sleep(self.POST_COMMUNICATION_DELAY)
            if until_buffer_empty:
                while self.mediator.bytes_in_buffer > 0:
                    response += self.mediator.read()
                    time.sleep(self.POST_COMMUNICATION_DELAY)

        return response

    @staticmethod
    def parse_response(response: str) -> list[int | float | str] | int | float | str:
        """
        Parse the response from the device into a list of values or a single value.
        Converts valid ints and floats to their corresponding type.

        Parameters
        ----------
        response : str
            The response string from the device.

        Returns
        -------
        list[int | float | str] or int or float or str
            Parsed response values.
        """
        response = response.strip()
        response_list: list[str] = response.split(',')
        response_list = [_convert_str(r.strip()) for r in response_list]

        return response_list if len(response_list) > 1 else response_list[0]

    @staticmethod
    def _set_rm_kwargs_defaults(method):
        """
        Set default keyword arguments for pyvisa.resources.MessageBasedResource-based methods.

        Parameters
        ----------
        method : callable
            The method to wrap with default keyword arguments.

        Returns
        -------
        Callable
            The wrapped method.
        """
        def wrapper(cls, *args, **rm_kwargs):
            rm_kwargs.setdefault('write_termination', cls.WRITE_TERMINATION)
            rm_kwargs.setdefault('read_termination', cls.READ_TERMINATION)
            rm_kwargs.setdefault('query_delay', cls.QUERY_DELAY)
            return method(cls, *args, **rm_kwargs)
        return wrapper

    @classmethod
    @_set_rm_kwargs_defaults
    def from_resource_port(
            cls,
            resource_port: str,
            **rm_kwargs,
    ) -> 'MessageBasedDevice':
        """
        Create an instance of MessageBasedDevice from the resource port.

        Parameters
        ----------
        resource_port : str
            The resource port for the message-based device (e.g. 'COM1', 'ASRL2::INSTR', or 'GPIB0::3::INSTR')
        **rm_kwargs
            Additional keyword arguments for the `pyvisa.ResourceManager.open_resource()` method.

        Returns
        -------
        MessageBasedDevice
            An instance of MessageBasedDevice.
        """
        resource = resource_manager.open_resource(resource_port, **rm_kwargs)

        if not isinstance(resource, MessageBasedResource):
            # TODO: Change message
            raise ValueError(f'Resource {resource} with resource_port {resource_port} is not a MessageBasedResource.')
        return cls(resource)

    @classmethod
    @_set_rm_kwargs_defaults
    def from_visa_attribute(
            cls,
            visa_attribute: Type[Attribute],
            desired_attr_value: str,
            is_partial: bool = False,
            connection_time_delay: float = None,
            correct_read_termination: bool = False,
            **rm_kwargs,
    ) -> 'MessageBasedDevice':
        """
        Search and create an instance of pyvisa.resources.MessageBasedResource
        by searching for a VISA attribute - value match.
        Will parse through all available devices and compare between the
        desired and the collected value of the requested VISA attribute.

        Parameters
        ----------
        visa_attribute : Type[Attribute]
            The VISA attribute type to use for resource identification.
        desired_attr_value : str
            The desired value of the VISA attribute.
        is_partial : bool, optional
            Specify if the attribute value is partial (e.g. desired value is 'Spinach' but the entire
            VISA attribute will be '18th Spinach Corp'. Default is False.
        connection_time_delay : float, optional
            The delay after connection in seconds. Default is None.
            Use if device of interest (e.g. Arduino) has a fixed loading time after establishing a connection.
            It will greatly impact operation speed.
        correct_read_termination : bool, optional
            Correct read termination during resource identification. Default is False.
        **rm_kwargs
            Additional keyword arguments for the `pyvisa.ResourceManager.open_resource()` method.

        Returns
        -------
        MessageBasedDevice
            An instance of MessageBasedDevice.
        """

        if connection_time_delay is None:
            connection_time_delay = cls.POST_CONNECTION_DELAY

        resource_list = find_available_resources_by_visa_attribute(
            resource_manager, visa_attribute, desired_attr_value, is_partial,
            connection_time_delay, correct_read_termination, **rm_kwargs
        )

        if len(resource_list) == 0:
            raise ValueError(f'No resource found with visa_attribute {visa_attribute}.')  # TODO: Change message
        elif len(resource_list) > 1:
            raise ValueError(f'Multiple resources found with visa_attribute {visa_attribute}.')  # TODO: Change message

        resource = resource_list[0]
        if not isinstance(resource, MessageBasedResource):
            # TODO: Change message
            raise ValueError(f'Resource {resource} is not a MessageBasedResource.')

        return cls(resource)

    @classmethod
    @_set_rm_kwargs_defaults
    def from_idn(
            cls,
            idn: str,
            is_partial: bool = False,
            connection_time_delay: float = None,
            correct_read_termination: bool = False,
            **rm_kwargs,
    ) -> 'MessageBasedDevice':
        """
        Create an instance of MessageBasedDevice from an identification ('*IDN?' query) string.

        Parameters
        ----------
        idn : str
            The identification string for resource identification (e.g. 'Matisse TS').
        is_partial : bool, optional
            Specify if the identification string is partial (e.g., desired IDN is 'Spinach'
            but the entire IDN is '18th Spinach Corp'). Default is False.
        connection_time_delay : float, optional
            The delay after connection in seconds. Default is None.
            Use if device of interest (e.g., Arduino) has a fixed loading time after establishing a connection.
            It will greatly impact operation speed.
        correct_read_termination : bool, optional
            Correct read termination during resource identification. Default is False.
        **rm_kwargs
            Additional keyword arguments for the `pyvisa.ResourceManager.open_resource()` method.

        Returns
        -------
        MessageBasedDevice
            An instance of MessageBasedDevice.
        """

        if connection_time_delay is None:
            connection_time_delay = cls.POST_CONNECTION_DELAY

        resource_list = find_available_resources_by_idn(
            resource_manager, idn, is_partial, connection_time_delay,
            correct_read_termination, **rm_kwargs
        )

        if len(resource_list) == 0:
            raise ValueError(f'No resource found with idn {idn}.')  # TODO: Change message
        elif len(resource_list) > 1:
            raise ValueError(f'Multiple resources found with idn {idn}.')  # TODO: Change message

        return cls(resource_list[0])
    
    def wrap_single_action(self, method):
        """
        Performs action while acquiring lock. Connects and disconnects the device.

        Parameters
        ----------
        method : callable
            The method to wrap.

        Returns
        -------
        Callable
            The wrapped method.
        """
        def wrapper(cls, *args, **rm_kwargs):
            with self._lock:
                self.connect()
                result = method(cls, *args, **rm_kwargs)
                self.disconnect()
            return result
        return wrapper


class PressureSensor(NIDAQAnalogInput):
    """
    The pressure sensor class based on `NIDAQAnalogInput`
    allows the user to read the pressure through a DAQ ai channel.

    For this sensor, 1 V -> 1 psi (linear relationship).
    """

    INSTRUMENT_NAME = 'Pressure Sensor'

    def __init__(self, device_name: str = 'Dev1', channel_name: str = 'ai0'):
        """
        Parameters
        ----------
        device_name : str, optional
            The name of the NI DAQ device. Default is 'Dev1'.
        channel_name : str, optional
            The name of the NI DAQ channel. Default is 'ai0'.
        """
        super().__init__(device_name, channel_name)


class RefillStatusReader(NIDAQAnalogInput):

    """
    The Refill Status Reader class based on `NIDAQAnalogInput`
    allows the user to read the refill status through a DAQ ai channel.
    """

    INSTRUMENT_NAME = 'Refill Status Reader'

    def __init__(self, device_name: str = 'Dev1', channel_name: str = 'ai1'):
        """
        Parameters
        ----------
        device_name : str, optional
            The name of the NI DAQ device. Default is 'Dev1'.
        channel_name : str, optional
            The name of the NI DAQ channel. Default is 'ai1'.
        """
        super().__init__(device_name, channel_name)


class ArduinoForPressureAndRefill(MessageBasedDevice):
    """
    This class assumes a predefined arduino UNO R3 configuration found in .device.arduino

    The current configuration allows four commands to be given to the arduino:

    1. *IDN? -> returns "Arduino-Uno-R3"
    2. *CLR -> does nothing
    3. PRESSURE -> returns the pressure reading as a string
    4. REFILL -> returns the refill status reading as a string
    """

    MEASURE_PRESSURE = 'PRESSURE'
    MEASURE_REFILL = 'REFILL'
    CLEAR = '*CLR'

    WRITE_TERMINATION = '\r\n'
    READ_TERMINATION = '\r\n'

    QUERY_DELAY = 10 ** -9  # s, even the smallest delay will help your device-read from crushing on you.
    POST_COMMUNICATION_DELAY = 10 ** -9  # same communication issue when device is not ready to move forward.
    POST_CONNECTION_DELAY = 2

    INSTRUMENT_NAME = 'Arduino-Uno-R3'
    DEFAULT_PORT = 'ASRL3::INSTR'

    def read_pressure(self):
        """
        If the device connection is active, queries the pressure from the arduino and returns
        the pressure as a float. Otherwise, returns np.nan.

        Returns
        -------
        float
            The pressure reading.
        """
        if self.mediator is not None:
            message = self.form_message(self.MEASURE_PRESSURE, True)
            response = self.safe_query(message)
            if _str_is_float(response):
                return float(response)
        return np.nan

    def read_refill_status(self):
        """
        If the device connection is active, queries the refill status from the arduino and returns
        the refill status as a float. Otherwise, returns np.nan.

        Returns
        -------
        float
            The refill status reading.
        """
        if self.mediator is not None:
            message = self.form_message(self.MEASURE_REFILL, True)
            response = self.safe_query(message)
            if _str_is_float(response):
                return float(response)
        return np.nan


class TemperatureController(MessageBasedDevice):
    """
    This class defines only the commands we need for everyday operations,
    such as controlling the heaters and measuring the temperatures.

    Additionally, it provides functionality for some more advanced protocols, such as

    1. Warming up the sample space for a sample change,
    2. Adjusting the cold head heater according to the pressure reading, helpful
    when the PID is not fast enough (e.g., during magnetic field sweeps).

    Find the device manual here: https://www.lakeshore.com/docs/default-source/product-downloads/335_manual038a7cfe0db7421f941ebb45db85741f.pdf?sfvrsn=e16b9529_1

    """
    class HeaterRangeValues(enum.Enum):
        """
        Enumerator correlating heater range strings
        with their corresponding integer values.
        """
        OFF = 0
        LOW = 1
        MEDIUM = 2
        HIGH = 3

    class HeaterMaxPercent(enum.Enum):
        """
        Enumerator defining the maximum heater percent values.
        This is not related to the device itself,
        but it is a developer-set limit used
        in the extra implemented protocols.
        """
        OFF = 100
        LOW = 80
        MEDIUM = 80
        HIGH = 50

    class HeaterOutputModes(enum.Enum):
        pass

    STARTING_HEATER_MIN_PERCENT = 10
    """ The minimum heater percent value, set by the 
    developer for use in the extra implemented protocols. """

    KELVIN_READING = 'KRDG'
    HEATER_OUTPUT = 'HTR'
    MANUAL_OUTPUT = 'MOUT'
    HEATER_RANGE = 'RANGE'
    SET_POINT = 'SETP'
    CLEAR = '*CLR'

    WRITE_TERMINATION = '\r\n'
    READ_TERMINATION = '\n'

    QUERY_DELAY = 10 ** -2  # s, even the smallest delay will help your device-read from crushing on you.
    POST_COMMUNICATION_DELAY = 10 ** -2  # same communication issue when device is not ready to move forward.

    INSTRUMENT_NAME = 'Lakeshore 335'

    COLD_HEAD_IN_CHANNEL = 'A'
    SAMPLE_SPACE_IN_CHANNEL = 'B'
    COLD_HEAD_OUT_CHANNEL = 1
    SAMPLE_SPACE_OUT_CHANNEL = 2

    DEFAULT_PORT = 'GPIB0::12::INSTR'

    def __init__(self, mediator: MessageBasedResourceType):
        super().__init__(mediator)
        self.stop_warmup_event: threading.Event | None = None
        self._warmup_interval = 20  # seconds
        self._sample_space_warmup_target_temperature = SAMPLE_SPACE_WARMED_UP_TEMP

    def quick_query(self, command: str, channel: str | int = None) -> float:
        """
        Query made easy. Provide the command and the channel.
        This method will formulate the message, and return the
        answer as a float.

        Parameters
        ----------
        command : str
            The command to query (no question mark (?))
        channel : str | int, optional
            The channel to query (1 or 2, 'A' or 'B'). Default is None.

        Returns
        -------
        float
            The response from the device.
        """
        message = self.form_message(command, True, channel)
        
        response = self.safe_query(message)
        if _str_is_float(response):
            return float(response)
        return np.nan

    def quick_write(self, command: str, value: list[float | int] | float | int, channel: str | int):
        """
        Write made easy. Provide the command, value and channel.
        This method will formulate the message and write it to the
        device.

        Parameters
        ----------
        command : str
            The command to write
        value : list[float | int] | float | int
            The value to write.
        channel : str | int
            The channel to write to (1 or 2, 'A' or 'B').
        """
        if isinstance(value, list):
            value = ','.join(value)
        message = f'{command} {channel},{value}'
        self.safe_write(message, self.WRITE_TERMINATION)

    def get_sample_space_temperature(self) -> float:
        """ Returns the sample space temperature. """
        return self.quick_query(self.KELVIN_READING, self.SAMPLE_SPACE_IN_CHANNEL)

    def get_cold_head_temperature(self) -> float:
        """ Returns the cold head temperature. """
        return self.quick_query(self.KELVIN_READING, self.COLD_HEAD_IN_CHANNEL)

    def get_sample_space_heater_percentage(self) -> float:
        """ Returns the sample space heater percentage. """
        return self.quick_query(self.HEATER_OUTPUT, self.SAMPLE_SPACE_OUT_CHANNEL)

    def get_cold_head_heater_percentage(self) -> float:
        """ Returns the cold head heater percentage. """
        return self.quick_query(self.HEATER_OUTPUT, self.COLD_HEAD_OUT_CHANNEL)

    def get_sample_space_manual_output(self) -> float:
        """ Returns the sample space manual output. """
        return self.quick_query(self.MANUAL_OUTPUT, self.SAMPLE_SPACE_OUT_CHANNEL)

    def get_cold_head_manual_output(self) -> float:
        """ Returns the cold head manual output. """
        return self.quick_query(self.MANUAL_OUTPUT, self.COLD_HEAD_OUT_CHANNEL)

    def get_sample_space_heater_range(self) -> str:
        """ Returns the sample space heater range as a title-styled string (e.g., 'Medium') """
        response = self.quick_query(self.HEATER_RANGE, self.SAMPLE_SPACE_OUT_CHANNEL)
        return TemperatureController.HeaterRangeValues(response).name.title()

    def get_cold_head_heater_range(self) -> str:
        """ Returns the cold head heater range as title-styled string (e.g., 'Medium'). """
        response = self.quick_query(self.HEATER_RANGE, self.COLD_HEAD_OUT_CHANNEL)
        return TemperatureController.HeaterRangeValues(response).name.title()

    def get_sample_space_set_point(self) -> float:
        """ Returns the sample space set-point. """
        return self.quick_query(self.SET_POINT, self.SAMPLE_SPACE_OUT_CHANNEL)

    def get_cold_head_set_point(self) -> float:
        """ Returns the cold head set-point. """
        return self.quick_query(self.SET_POINT, self.COLD_HEAD_OUT_CHANNEL)

    def set_sample_space_manual_output(self, value: float):
        """ Sets the sample space manual output. """
        self.quick_write(self.MANUAL_OUTPUT, value, self.SAMPLE_SPACE_OUT_CHANNEL)

    def set_cold_head_manual_output(self, value: float):
        """ Sets the cold head manual output. """
        self.quick_write(self.MANUAL_OUTPUT, value, self.COLD_HEAD_OUT_CHANNEL)

    def set_heater_range(self, value: str | int | HeaterRangeValues, channel: int):
        """
        Sets the heater range.

        Parameters
        ----------
        value : str | int | HeaterRangeValues
            The value to set.
            If it is an integer, it will be used as is.
            If it is a string, it will be converted to the corresponding integer value.
            If it is an enumerator, it will be converted to the corresponding integer value.

        channel : int
            The channel to set the value to.
        """
        if isinstance(value, str):
            value = TemperatureController.HeaterRangeValues[value.upper()].value
        elif isinstance(value, TemperatureController.HeaterRangeValues):
            value = value.value
        self.quick_write(self.HEATER_RANGE, value, channel)

    def set_sample_space_heater_range(self, value: str | int | HeaterRangeValues):
        """
        Sets the sample space heater range.

        Parameters
        ----------
        value : str | int | HeaterRangeValues
            The value to set.
            If it is an integer, it will be used as is.
            If it is a string, it will be converted to the corresponding integer value.
            If it is an enumerator, it will be converted to the corresponding integer value.
        """
        self.set_heater_range(value, self.SAMPLE_SPACE_OUT_CHANNEL)

    def set_cold_head_heater_range(self, value: str | int | HeaterRangeValues):
        """
        Sets the cold head heater range.

        Parameters
        ----------
        value : str | int | HeaterRangeValues
            The value to set.
            If it is an integer, it will be used as is.
            If it is a string, it will be converted to the corresponding integer value.
            If it is an enumerator, it will be converted to the corresponding integer value.
        """
        self.set_heater_range(value, self.COLD_HEAD_OUT_CHANNEL)

    def set_sample_space_set_point(self, value: float):
        """ Sets the sample space set-point. """
        self.quick_write(self.SET_POINT, value, self.SAMPLE_SPACE_OUT_CHANNEL)

    def set_cold_head_set_point(self, value: float):
        """ Sets the cold head set-point. """
        self.quick_write(self.SET_POINT, value, self.COLD_HEAD_OUT_CHANNEL)

    def reset_cold_head_heater_output(self, set_point: float = None):
        """
        Resets the cold head heater output:
        1. sets heater range to "OFF".
        2. sets manual output to 0.
        3. If provided, changes set-point.
        4. Sets heater range to "MEDIUM".

        In our specific experimental setup, this will allow
        the cryostat to find equilibrium at heater percentage around 36 %.

        Parameters
        ----------
        set_point : float, optional
            The set-point to set. Default is None. If None, set-point stays the same.
        """
        self.set_cold_head_heater_range('off')
        self.set_cold_head_manual_output(0.)
        if set_point:
            self.set_cold_head_set_point(set_point)
        self.set_cold_head_heater_range('medium')

    @property
    def warmup_interval(self):
        """ The interval between two temperature acquisitions. """
        return self._warmup_interval

    @property
    def sample_space_warmup_target_temperature(self):
        """ The target temperature for the sample space warm-up. """
        return self._sample_space_warmup_target_temperature

    @sample_space_warmup_target_temperature.setter
    def sample_space_warmup_target_temperature(self, value):
        self._sample_space_warmup_target_temperature = value

    def warmup_loop(self, stop_event: threading.Event):
        # TODO: Add docstring explaining the warmup process
        sample_space_data = np.array([self.get_sample_space_temperature()])
        self.segmented_warmup_sleep(time.time(), stop_event, 0.5)

        max_size = 5
        while not stop_event.is_set():
            start_time = time.time()
            try:
                new_data = self.get_sample_space_temperature()
                if len(sample_space_data) < max_size:
                    sample_space_data = np.append(sample_space_data, new_data)
                else:
                    sample_space_data = np.roll(sample_space_data, -1)[:max_size]
                    sample_space_data[-1] = new_data
                self.check_warmup_heater_status(sample_space_data)
            except Exception as e:
                print("Error collecting data:", e)
            self.segmented_warmup_sleep(start_time, stop_event, 0.5)
        print(f'Finished, {stop_event}')

    # @property
    # def sample_space_is_warmed_up(self):
    #     return self.get_sample_space_temperature() > SAMPLE_SPACE_WARMED_UP_TEMP

    def check_warmup_heater_status(self, temperature_data: np.ndarray):
        # TODO: Add docstring explaining the warmup checks
        temperature_diffs = - np.diff(temperature_data)
        mean_temp_diff_per_minute = np.mean(temperature_diffs) / (self.warmup_interval / 60)

        heater_range = self.HeaterRangeValues[self.get_sample_space_heater_range().upper()]
        heater_manual_output = self.get_sample_space_manual_output()

        target_temperature = self.sample_space_warmup_target_temperature
        if temperature_data[-1] > target_temperature - 2:
            if mean_temp_diff_per_minute > 0.5 or temperature_data[-1] > target_temperature + 2:
                self.set_sample_space_manual_output(max(heater_manual_output - 10, 0))
                if heater_range != self.HeaterRangeValues.HIGH:
                    self.set_sample_space_heater_range('High')
            elif mean_temp_diff_per_minute < - 0.5:
                self.set_sample_space_manual_output(min(heater_manual_output + 2, 50))
                if heater_range != self.HeaterRangeValues.HIGH:
                    self.set_sample_space_heater_range('High')
            return

        # TODO: Add condition for when the temperature is very low. I have observed that for < 50 K,
        #  the increase stalls goes up, flat and up again for 1-3 different temperatures. I need to allow the system to
        #  stall and not force it to heat up!

        if mean_temp_diff_per_minute < 1:
            if heater_range == self.HeaterRangeValues.OFF:
                self.set_sample_space_manual_output(self.STARTING_HEATER_MIN_PERCENT)
                self.set_sample_space_heater_range("Low")
            else:
                max_heater_value = self.HeaterMaxPercent[heater_range.name].value
                if heater_manual_output < max_heater_value:
                    self.set_sample_space_manual_output(min(heater_manual_output + 5, max_heater_value))
                else:
                    self.set_sample_space_manual_output(self.STARTING_HEATER_MIN_PERCENT)
                    higher_heater_range = self.HeaterRangeValues(heater_range.value + 1)
                    self.set_sample_space_heater_range(higher_heater_range)
            return

        if mean_temp_diff_per_minute > 3:
            if heater_range == self.HeaterRangeValues.OFF:
                return
            if heater_manual_output > self.STARTING_HEATER_MIN_PERCENT:
                self.set_sample_space_manual_output(max(heater_manual_output - 5, self.STARTING_HEATER_MIN_PERCENT))
            else:
                lower_heater_range = self.HeaterRangeValues(heater_range.value - 1)
                max_lower_heater_value = self.HeaterMaxPercent[lower_heater_range.name].value
                self.set_sample_space_heater_range(lower_heater_range)
                self.set_sample_space_manual_output(max_lower_heater_value)
            return

        # if mean_temp_diff_per_minute < 1:
        #     if heater_range == 'Low':
        #         if heater_manual_output < 80:
        #             self.set_sample_space_manual_output(heater_manual_output + 5)
        #         else:
        #             self.set_sample_space_manual_output(10)
        #             self.set_sample_space_heater_range("Medium")
        #     elif heater_range == 'Medium':
        #         if heater_manual_output < 80:
        #             self.set_sample_space_manual_output(heater_manual_output + 5)
        #         else:
        #             self.set_sample_space_manual_output(10)
        #             self.set_sample_space_heater_range("High")
        #     elif heater_range == 'High':
        #         if heater_manual_output < 50:
        #             self.set_sample_space_manual_output(heater_manual_output + 5)
        #     return
        #
        # if mean_temp_diff_per_minute > 3:
        #     self.set_sample_space_manual_output(max(heater_manual_output - 5, 5))

    def segmented_warmup_sleep(self, start_time, stop_event: threading.Event, time_step):
        """ Managing the wait time between warm-up acquisitions. """
        remaining_time = self.warmup_interval - (time.time() - start_time)

        while remaining_time > 0 and not stop_event.is_set():
            time.sleep(remaining_time if remaining_time < time_step else time_step)
            remaining_time = self.warmup_interval - (time.time() - start_time)

    def start_sample_space_warmup(self):
        """ Starting the thread for the sample space warmup process. """
        self.stop_warmup_event = threading.Event()
        thread_target = partial(self.warmup_loop, self.stop_warmup_event)
        thread = threading.Thread(target=thread_target)
        thread.start()

    def stop_sample_space_warmup(self):
        """ Terminates the thread for the sample space warmup process. """
        self.stop_warmup_event.set()
        time.sleep(5)
        self.set_sample_space_manual_output(0)
        self.set_sample_space_heater_range('off')

    def __del__(self):
        if not self.stop_warmup_event.is_set():
            self.stop_sample_space_warmup()
        super().__del__()


class CryogenLevelSensor(MessageBasedDevice):
    """ The cryogenic level sensor class defined based on the `MessageBasedDevice`. """
    MEASURE = 'MEAS'
    CLEAR = '*CLR'

    WRITE_TERMINATION = '\r\n'
    READ_TERMINATION = ''

    QUERY_DELAY = 10 ** -1  # s, even the smallest delay will help your device-read from crushing on you.
    POST_COMMUNICATION_DELAY = 10 ** -1  # same communication issue when device is not ready to move forward.
    POST_CONNECTION_DELAY = 0.5

    INSTRUMENT_NAME = 'LM-510'

    HELIUM_CHANNEL: int = 1
    NITROGEN_CHANNEL: int = 2

    DEFAULT_PORT = 'ASRL4::INSTR'

    def parse_response(self, response: str) -> list[int | float | str] | int | float | str:
        response = response.split('\r\n')[1]  # removes echoed write and next line!
        return super().parse_response(response)

    def quick_query(self,  command: str, channel: int, delay: float = None) -> str:
        """
        Query made easy. Provide the command and the channel.
        This method will formulate the message, and return the
        answer as a float.

        Parameters
        ----------
        command : str
            The command to query (no question mark (?))
        channel : str | int, optional
            The channel to query (1 or 2).
        delay: float
            Additional delay after the query's write operation (inherited
            from pyvisa.resource.MessageBasedResource.query()). Default is None.

        Returns
        -------
        str
            The response from the device.
        """
        message = self.form_message(command, True, channel)
        response = self.safe_query(message, delay, until_buffer_empty=True)
        return response

    def quick_level_query(self, channel: int) -> float:
        """
        Easy query of cryogenic level readout. Provide a channel, get back a float.
        If the response is invide, a significant delay will be applied, and the query will be
        repeated one more time. If the query is still invalid, `np.nan` will be returned.

        Parameters
        ----------
        channel : str | int, optional
            The channel to query (1 or 2).

        Returns
        -------
        float
            The response from the device.

        """
        def get_processed_response(delay: float = None):
            """ Process single query response """
            response = self.quick_query(self.MEASURE, channel, delay)
            parsed_response = self.parse_response(response)
            if _str_is_float(parsed_response[:-3]):
                return float(parsed_response[:-3])
            return np.nan

        processed_response = get_processed_response()
        if np.isnan(processed_response):
            time.sleep(0.5)
            self.clear(force=True)
            time.sleep(0.5)
            processed_response = get_processed_response(delay=self.POST_COMMUNICATION_DELAY * 10)
        
        return processed_response

    def read_helium_level(self) -> float:
        """
        Queries helium channel for cryogenic level.
        Will use a series of sleep implementations to make sure the query does not get return `np.nan`.

        Returns
        -------
        float
            The helium level value.
        """
        time.sleep(0.1)
        self.clear(force=True)
        time.sleep(0.1)
        response = self.quick_level_query(self.HELIUM_CHANNEL)
        time.sleep(0.1)
        self.clear(force=True)
        time.sleep(0.1)
        return response

    def read_nitrogen_level(self) -> float:
        """
        Queries nitrogen channel for cryogenic level.
        Will use a series of sleep implementations to make sure the query does not get return `np.nan`.

        Returns
        -------
        float
            The nitrogen level value.
        """
        time.sleep(0.1)
        self.clear(force=True)
        time.sleep(0.1)
        response = self.quick_level_query(self.NITROGEN_CHANNEL)
        time.sleep(0.1)
        self.clear(force=True)
        time.sleep(0.1)
        return response


class ColdHeadHeaterOnPressureStabilization:
    """
    This class is designed to be used with the `ColdHeadHeater` class.
    It will attempt to stabilize the cold head temperature by monitoring the
    pressure of the cryostat instead of the cold head temperature.
    """
    def __init__(self, temperature_controller: TemperatureController, pressure_read_method: Callable[[], float],
                 get_target_pressure_method: Callable[[], float], reading_interval: float = 10):
        """
        Parameters
        ----------
        temperature_controller : TemperatureController
            The temperature controller.
        pressure_read_method : Callable[[], float]
            The callable method to use to read the pressure.
        get_target_pressure_method : Callable[[], float]
            The callable method to use to get the target pressure.
        reading_interval : float, optional
            The interval between readings. Default is 10 seconds.
        """
        self.temperature_controller = temperature_controller
        self.pressure_read_method = pressure_read_method
        self.get_target_pressure = get_target_pressure_method
        self.reading_interval = reading_interval

        self.stop_stabilization_event: threading.Event | None = None
        self.stabilization_is_on = threading.Event()

    def attempt_stabilization_by_pressure(self, pressure_data: np.ndarray):
        """
        Performs a step in an attempt to stabilize the cold head temperature
        by monitoring the pressure of the cryostat instead of the cold head temperature.

        Parameters
        ----------
        pressure_data : numpy.ndarray
            A 1D-float-array of pressure readings.
        """
        manual_output_step = 5
        mean_pressure = np.mean(pressure_data)
        if mean_pressure < self.get_target_pressure():
            cold_head_manual_output = self.temperature_controller.get_cold_head_manual_output()
            new_cold_head_manual_output = max(cold_head_manual_output - manual_output_step, 0)
            self.temperature_controller.set_cold_head_manual_output(new_cold_head_manual_output)
        else:
            cold_head_manual_output = self.temperature_controller.get_cold_head_manual_output()
            new_cold_head_manual_output = min(cold_head_manual_output - manual_output_step, 80)
            self.temperature_controller.set_cold_head_manual_output(new_cold_head_manual_output)

    def stabilization_loop(self, stop_event: threading.Event):
        # TODO: Add docstring explaining the stabilization process
        self.stabilization_is_on.set()
        cold_head_heater_percentage_data = []
        for i in range(10):
            with self.temperature_controller._lock:
                self.temperature_controller.connect()
                cold_head_heater_percentage_data.append(self.temperature_controller.get_cold_head_heater_percentage())
                self.temperature_controller.disconnect()
            self.segmented_stabilization_sleep(time.time(), stop_event, 0.5, 2)

        mean_heater_percentage = round(np.mean(cold_head_heater_percentage_data), 1)

        with self.temperature_controller._lock:
            self.temperature_controller.connect()
            heater_range = self.temperature_controller.get_cold_head_heater_range()
            self.temperature_controller.set_cold_head_heater_range('off')
            self.temperature_controller.set_cold_head_manual_output(mean_heater_percentage)
            self.temperature_controller.set_cold_head_heater_range(heater_range)
            self.temperature_controller.disconnect()

        pressure_data = np.array([self.pressure_read_method()])

        max_size = 5
        while not stop_event.is_set():
            start_time = time.time()
            try:
                new_data = self.pressure_read_method()
                if len(pressure_data) < max_size:
                    pressure_data = np.append(pressure_data, new_data)
                else:
                    pressure_data = np.roll(pressure_data, -1)[:max_size]
                    pressure_data[-1] = new_data
                self.attempt_stabilization_by_pressure(pressure_data)
            except Exception as e:
                print("Error collecting data:", e)
            self.segmented_stabilization_sleep(start_time, stop_event, 0.5)

        with self.temperature_controller._lock:
            self.temperature_controller.connect()
            self.temperature_controller.set_cold_head_heater_range('off')
            self.temperature_controller.set_cold_head_manual_output(mean_heater_percentage)
            self.temperature_controller.set_cold_head_heater_range(heater_range)
            self.temperature_controller.disconnect()

        self.stabilization_is_on.clear()
        print(f'Finished, {stop_event}')

    def start_pressure_stabilization(self):
        """ Starts the pressure stabilization thread. """
        if not self.stop_stabilization_event.is_set():
            return
        counter = 0
        while self.stabilization_is_on.is_set() and counter < 60:
            counter += 1
            time.sleep(0.5)

        self.stop_stabilization_event = threading.Event()
        thread_target = partial(self.stabilization_loop, self.stop_stabilization_event)
        thread = threading.Thread(target=thread_target)
        thread.start()

    def stop_pressure_stabilization(self):
        """ Terminates the pressure stabilization thread. """
        self.stop_stabilization_event.set()

    def segmented_stabilization_sleep(self, start_time, stop_event: threading.Event, time_step, interval: float = None):
        """ Managing the wait time between pressure acquisitions. """
        if interval is None:
            interval = self.reading_interval

        remaining_time = interval - (time.time() - start_time)

        while remaining_time > 0 and not stop_event.is_set():
            time.sleep(remaining_time if remaining_time < time_step else time_step)
            remaining_time = interval - (time.time() - start_time)
