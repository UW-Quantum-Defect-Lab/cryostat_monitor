"""
This very extensive module provides methods for checking the status of the cryostat,
and submitting reports when something goes wrong.
"""

import datetime
import enum
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Literal, TypedDict

import numpy as np
import yaml
from slack_sdk.models.blocks import HeaderBlock, PlainTextObject, SectionBlock, DividerBlock, MarkdownTextObject

from monitor.constants import STATUS_CHANGE_DISCARD_TIME, NITROGEN_REFILLING_FOR_TOO_LONG, EMAIL_INFO_FILE_PATH, \
    EMAIL_TIMESTAMP_FORMAT, ALERT_FILENAME_FORMAT, DATA_STORAGE_FOLDER, DAILY_REPORT_TIMES
from monitor.measurement import Measurement, MEASUREMENT_HEADER_MAP
from monitor.communication import send_email, send_slack_message_via_webhook, dict_to_markdown_table


class PressureLimits:
    """ Cryostat's pressure limitations that should trigger alerts. """
    LOW = 0.2
    MED_LOW = 0.8
    MED_HIGH = 2.2
    HIGH = 2.8


class NitrogenLevelLimits:
    """ Cryostat's nitrogen level limitations that should trigger alerts. """
    LOW = 6.


class HeliumLevelLimits:
    """ Cryostat's helium level limitations that should trigger alerts. """
    LOW = 20.5


class ColdHeadLimits:
    """ Cryostat's cold head temperature and heater limitations that should trigger alerts. """
    LOW_HEATER_PERCENTAGE = 10.
    HIGH_HEATER_PERCENTAGE = 50.

    LOW_TEMPERATURE = 4.
    HIGH_TEMPERATURE = 4.3


class PressureStatus(enum.Enum):
    """ Enumeration of all possible pressure statuses. """
    NORMAL = 0
    NO_READING = 1
    LOW = 2
    HIGH = 3


class NitrogenStatus(enum.Enum):
    """ Enumeration of all possible nitrogen statuses. """
    NORMAL = 0
    NO_READING = 1
    LOW = 2
    REFILLING = 10
    REFILLING_FOR_TOO_LONG = 11


class HeliumStatus(enum.Enum):
    """ Enumeration of all possible helium statuses. """
    NORMAL = 0
    NO_READING = 1
    LOW = 2
    REFILLING = 10


class ColdHeadTemperatureStatus(enum.Enum):
    """ Enumeration of all possible cold head temperature statuses. """
    NORMAL = 0
    NO_READING = 1
    LOW = 2
    HIGH = 3


class ColdHeadHeaterStatus(enum.Enum):
    """ Enumeration of all possible cold head heater statuses. """
    NORMAL = 0
    NO_READING = 1
    LOW = 2
    HIGH = 3
    OFF = 100


class CompressorStatus(enum.Enum):
    """ Enumeration of all possible compressor statuses. """
    OFF = 100
    ON = 101


class AlertType(enum.Enum):
    """
    Enumeration of all possible Alert types.

    Attributes
    ----------
    UNKNOWN : int
        Usually related to no readings.
    INFO : int
        Everything is normal.
    WARNING : int
        Something may be wrong, plenty of time to observe and react.
    ERROR : int
        Something is probably wrong, and reaction time is a bit limited.
    CRITICAL : int
        Something is most probably wrong, and reaction time is very limited.
    """

    UNKNOWN = 0
    """ Usually related to no readings. """
    INFO = 1
    """ Everything is normal. """
    WARNING = 2
    """ Something may be wrong, plenty of time to observe and react. """
    ERROR = 3
    """ Something is probably wrong, and reaction time is a bit limited. """
    CRITICAL = 4
    """ Something is most probably wrong, and reaction time is very limited. """


class ElementMonitor:
    """
    ElelmentMonitor is a horrible name for this class.
    I am really sorry I could not figure out a better one.

    The word 'element' is to be associated with different equipment
    parts or physical values (e.g., pressure, nitrogen, helium,
    cold head, compressor).

    This class connects the different types of alerts (`AlertType`)
    different statuses (e.g., `PressureStatus`, `NitrogenStatus`, etc)
    and the messages that are associated with each.
    You can compare element monitors to find whose AlertType is more
    important (e.g., an element monitor of type `AlertType.ERROR` is more
    important than an element monitor of type `AlertType.WARNING`).

    This class does NOT send out alerts.

    Attributes
    ----------
    status : enum.Enum | tuple[enum.Enum]
        The status of the element.
    type : AlertType
        The type of the element associated with the specific element status.
    message : str
        The message associated with the specific element status and alert type.
    message_title : str
        The title of the message associated with the specific element status and alert type.
    """
    _name = 'Element'
    """ The name of the element. """
    _identifier = 'element'
    """ The identifier of the element. Same as the name, 
    but all lowercase, and underscores instead of whitespaces. """
    TYPES: dict[enum.Enum | tuple[enum.Enum], AlertType] = {}
    """ A map between each element status and an alert type. """
    MESSAGES: dict[enum.Enum | tuple[enum.Enum], str] = {}
    """ A map between each element status and a message. """

    def __init__(self, status: enum.Enum | tuple[enum.Enum, ...]):
        """
        Parameters
        ----------
        status : enum.Enum | tuple[enum.Enum]
            The status of the element.
        """
        self.status: enum.Enum | tuple[enum.Enum, ...] = status
        self.type: AlertType = self._get_type_from_status()
        self.message: str = self._get_message_from_status()
        self.message_title: str = self._get_message_title_from_status()

    def _get_type_from_status(self):
        """
        Get the alert type from the element status.

        Returns
        -------
        AlertType
            The alert type associated with the element status.
            If the element status is not in the TYPES map, returns `AlertType.UNKNOWN`.
        """
        if self.status in self.TYPES:
            return self.TYPES[self.status]
        return AlertType.UNKNOWN

    def _get_message_from_status(self):
        """
        Get the message from the element status.

        Returns
        -------
        str
            The message associated with the element status.
            If the element status is not in the MESSAGES map, returns 'Unknown status: [status]'.
        """
        if self.status in self.MESSAGES:
            return self.MESSAGES[self.status]
        return f'Unknown status: {self.status}'

    @property
    def status_class_name(self):
        """
        Get the class name of the element status for printing purposes.

        Returns
        -------
        str | list[str]
            The class name of the element status.
            For example, if the class name of the status is `PressureStatus`, it returns 'Pressure'.
            If the status is a sequence of statuses, it returns a list of names.
            For example, if the tuple of statuses is (`ColdHeadTemperatureStatus`, `ColdHeadHeaterStatus`),
            it returns ['Cold head temperature', 'Cold head heater'].
        """
        if isinstance(self.status, tuple):
            return [str(status.__class__.__name__).replace('Status', '') for status in self.status]
        else:
            return str(self.status.__class__.__name__).replace('Status', '')

    def get_status_repr_string(self):
        """
        Get the string representation of the element status.

        Returns
        -------
        str
            The string representation of the element status.
            For example, if the status is `PressureStatus.NORMAL`, it returns 'Pressure is normal'.
            If the status is a sequence of statuses, it returns a string of statuses separated by commas.
            For example, if the tuple of statuses is (`ColdHeadTemperatureStatus.NORMAL`, `ColdHeadHeaterStatus.OFF`),
            it returns 'ColdHeadTemperature is normal, ColdHeadHeater is off'.
        """
        if isinstance(self.status, tuple):
            status_values_str = [status.name.lower().replace('_', ' ') for status in self.status]
            status_class_str = [scn for scn in self.status_class_name]
        else:
            status_values_str = [self.status.name.lower().replace('_', ' ')]
            status_class_str = [self.status_class_name]

        return ', '.join([f'{name} is {val}' for val, name in zip(status_values_str, status_class_str)])

    def _get_message_title_from_status(self):
        """
        Get the message title from the element status.

        Returns
        -------
        str
            The message title associated with the element status.
            For example, 'ERROR: Nitrogen is refilling for too long'.

        """
        status_string = self.get_status_repr_string()
        return f'{self.type.name}: {status_string}'

    @property
    def name(self):
        """ The name of the element. """
        return self._name

    @property
    def identifier(self):
        """ The identifier of the element. Same as the name,
        but all lowercase, and underscores instead of whitespaces. """
        return self._identifier

    def __repr__(self):
        return f'Name: {self.name}\nStatus: {self.status}\nType: {self.type}\nMessage: {self.message}'

    def __lt__(self, other):
        return self.type.value < other.type.value

    def __le__(self, other):
        return self.type.value <= other.type.value

    def __gt__(self, other):
        return self.type.value > other.type.value

    def __ge__(self, other):
        return self.type.value >= other.type.value

    def __eq__(self, other):
        return self.type.value == other.type.value

    def __ne__(self, other):
        return self.type.value != other.type.value


class PressureMonitor(ElementMonitor):
    _name = 'Pressure'
    _identifier = 'pressure'
    TYPES: dict[PressureStatus, AlertType] = {
        PressureStatus.NORMAL: AlertType.INFO,
        PressureStatus.NO_READING: AlertType.WARNING,
        PressureStatus.LOW: AlertType.WARNING,
        PressureStatus.HIGH: AlertType.WARNING,
    }
    MESSAGES: dict[PressureStatus, str] = {
        PressureStatus.NORMAL: 'Pressure is normal',
        PressureStatus.NO_READING: 'Pressure is not available',
        PressureStatus.LOW: 'Pressure is low',
        PressureStatus.HIGH: 'Pressure is high',
    }

    def __init__(self, status: PressureStatus, pressure_value: float):
        """
        Parameters
        ----------
        status : PressureStatus
            The status of the pressure.
        pressure_value : float
            The value of the pressure.
        """
        self.pressure_value = pressure_value
        self.status: PressureStatus
        super().__init__(status)

    def _get_message_from_status(self):
        message = super()._get_message_from_status()
        message += f' @ {self.pressure_value} psi'
        message += '.'
        return message


class NitrogenMonitor(ElementMonitor):
    _name = 'Nitrogen'
    _identifier = 'nitrogen'
    TYPES: dict[NitrogenStatus, AlertType] = {
        NitrogenStatus.NORMAL: AlertType.INFO,
        NitrogenStatus.NO_READING: AlertType.WARNING,
        NitrogenStatus.LOW: AlertType.WARNING,
        NitrogenStatus.REFILLING: AlertType.INFO,
        NitrogenStatus.REFILLING_FOR_TOO_LONG: AlertType.ERROR,
    }
    MESSAGES: dict[NitrogenStatus, str] = {
        NitrogenStatus.NORMAL: 'Nitrogen level is normal',
        NitrogenStatus.NO_READING: 'Nitrogen level is not available',
        NitrogenStatus.LOW: 'Nitrogen level is low',
        NitrogenStatus.REFILLING: 'Nitrogen jacket is being refilled',
        NitrogenStatus.REFILLING_FOR_TOO_LONG: 'Nitrogen supply dewar is empty',
    }

    def __init__(self, status: NitrogenStatus, nitrogen_level_value: float):
        """
        Parameters
        ----------
        status : NitrogenStatus
            The status of the nitrogen jacket.
        nitrogen_level_value : float
            The value of the nitrogen level.
        """
        self.status: NitrogenStatus
        self.status = status
        self.nitrogen_level_value: float
        self.nitrogen_level_value = nitrogen_level_value
        super().__init__(status)

    def _get_message_from_status(self):
        global _status_changes
        message = super()._get_message_from_status()

        if self.status == NitrogenStatus.REFILLING:
            if _status_changes.latest_statuses['nitrogen'] == NitrogenStatus.REFILLING:
                refilling_since = _status_changes.latest_timestamps['nitrogen'].strftime(EMAIL_TIMESTAMP_FORMAT)
                message += f' since {refilling_since}, with nitrogen level @ {self.nitrogen_level_value} in'
            else:
                message += f' since now, with nitrogen level @ {self.nitrogen_level_value} in'
        elif self.status == NitrogenStatus.REFILLING_FOR_TOO_LONG:
            refilling_since = _status_changes.nitrogen[-2].timestamp.strftime(EMAIL_TIMESTAMP_FORMAT)
            # refilling_since = _status_changes.latest_timestamps['nitrogen'].strftime(EMAIL_TIMESTAMP_FORMAT)
            message += f', refilling since {refilling_since}. Current nitrogen level @ {self.nitrogen_level_value} in'
        else:
            message += f' @ {self.nitrogen_level_value} in'
        message += '.'

        return message


class HeliumMonitor(ElementMonitor):
    _name = 'Helium'
    _identifier = 'helium'
    TYPES: dict[HeliumStatus, AlertType] = {
        HeliumStatus.NORMAL: AlertType.INFO,
        HeliumStatus.NO_READING: AlertType.WARNING,
        HeliumStatus.LOW: AlertType.WARNING,
        HeliumStatus.REFILLING: AlertType.INFO,
    }
    MESSAGES: dict[HeliumStatus, str] = {
        HeliumStatus.NORMAL: 'Helium level is normal',
        HeliumStatus.NO_READING: 'Helium level is not available',
        HeliumStatus.LOW: 'Helium level is low',
        HeliumStatus.REFILLING: 'Helium jacket is being refilled',
    }

    def __init__(self, status: HeliumStatus, helium_level_value: float):
        """
        Parameters
        ----------
        status : HeliumStatus
            The status of the helium jacket.
        helium_level_value : float
            The value of the helium level.
        """
        self.helium_level_value = helium_level_value
        super().__init__(status)

    def _get_message_from_status(self):
        message = super()._get_message_from_status()
        message += f' @ {self.helium_level_value} in'
        message += '.'
        return message


class ColdHeadMonitor(ElementMonitor):
    _name = 'Cold Head'
    _identifier = 'cold_head'
    TYPES: dict[tuple[ColdHeadTemperatureStatus, ColdHeadHeaterStatus], AlertType] = {
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.NORMAL): AlertType.INFO,
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.LOW): AlertType.WARNING,
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.HIGH): AlertType.WARNING,
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.OFF): AlertType.ERROR,
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.NORMAL): AlertType.CRITICAL,
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.LOW): AlertType.WARNING,
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.HIGH): AlertType.CRITICAL,
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.OFF): AlertType.ERROR,
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.NORMAL): AlertType.WARNING,
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.LOW): AlertType.WARNING,
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.HIGH): AlertType.ERROR,
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.OFF): AlertType.CRITICAL,
        (ColdHeadTemperatureStatus.NO_READING, ColdHeadHeaterStatus.NO_READING): AlertType.CRITICAL,
    }
    MESSAGES: dict[tuple[ColdHeadTemperatureStatus, ColdHeadHeaterStatus], str] = {
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.NORMAL):
            'Cold head temperature and heater are normal',
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.LOW):
            'Cold head temperature is normal, but heater is low',
        # means: 1. ramping field, 2. refilling helium, 3. heading to low ch temps, 4. heater PID is adjusting
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.HIGH):
            'Cold head temperature is normal, but heater is high',
        # means: 1. heater PID is adjusting, 2. heater range may be on low
        (ColdHeadTemperatureStatus.NORMAL, ColdHeadHeaterStatus.OFF):
            'Cold head temperature is normal, but heater is off',
        # means: 1. ramping field, 2. refilling helium, 3. heading to low ch temps, 4. someone forgot the heater off
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.NORMAL):
            'Cold head temperature is low, but heater is normal',
        # means: 1. heater range may be on low, 2. heater PID is adjusting, 3. cold head is clogged
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.LOW):
            'Cold head temperature and heater are low',
        # means: 1. heater PID is adjusting
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.HIGH):
            'Cold head temperature is low, but heater is high',
        # means: 1. heater range may be on low, 2. heater PID is adjusting, 3. cold head is clogged
        (ColdHeadTemperatureStatus.LOW, ColdHeadHeaterStatus.OFF):
            'Cold head temperature is low and heater is off',
        # means: 1. someone forgot the heater off
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.NORMAL):
            'Cold head temperature is high, but heater is normal',
        # means:
        # 1. PID is adjusting,
        # 2. compressor just (temporary, no critical alert for this) turned off (combined with sudden pressure increase)
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.LOW):
            'Cold head temperature is high and heater is low',
        # means:
        # 1. PID is adjusting,
        # 2. compressor just (temporary, no critical alert for this) turned off (combined with sudden pressure increase)
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.HIGH):
            'Cold head temperature and heater are high ',
        # means:
        # 1. PID is adjusting
        # 2. Something unknown, which could be a problem!
        (ColdHeadTemperatureStatus.HIGH, ColdHeadHeaterStatus.OFF):
            'Cold head temperature is high and heater is off.',
        # means:
        # 1. cold head is being cooled down (combined with generally high pressure for long time),
        # 2. compressor is off (pressure spiked up in recent readings)
        (ColdHeadTemperatureStatus.NO_READING, ColdHeadHeaterStatus.NO_READING):
            'Cold head can not be reached.\n'
            'Reasons: 1. Temperature controller may be turned off.',
    }

    def __init__(
            self,
            status: tuple[ColdHeadTemperatureStatus, ColdHeadHeaterStatus],
            temperature_value: float,
            heater_value: float
    ):
        """
        Parameters
        ----------
        status: tuple[ColdHeadTemperatureStatus, ColdHeadHeaterStatus]
            The status of the cold head.
        temperature_value: float
            The value of the temperature at the cold head.
        heater_value: float
            The value of the heater percentage on the cold head.
        """
        self.temperature_value = temperature_value
        self.heater_value = heater_value
        self.temperature_status: ColdHeadTemperatureStatus = status[0]
        self.heater_status: ColdHeadHeaterStatus = status[1]
        super().__init__(status)

    def _get_message_from_status(self):
        message = super()._get_message_from_status()
        message += f' @ {self.temperature_value} K, {self.heater_value} %'
        message += '.'
        return message


class CompressorMonitor(ElementMonitor):
    _name = 'Compressor'
    _identifier = 'compressor'
    TYPES: dict[CompressorStatus, AlertType] = {
        CompressorStatus.ON: AlertType.INFO,
        CompressorStatus.OFF: AlertType.ERROR,
    }
    MESSAGES: dict[CompressorStatus, str] = {
        CompressorStatus.ON: 'Compressor is on',
        CompressorStatus.OFF: 'Compressor is off',
    }

    def _get_message_from_status(self):
        message = super()._get_message_from_status()
        message += '.'
        return message


class MonitorReport:
    """
    Generates reports in various formats based on a measurement
    and various element statuses. Is responsible for sending said
    reports when necessary (when an alert type is of level Warning
    or higher, or when an overall report is requested.)
    """

    def __init__(
            self,
            measurement: Measurement,
            pressure: PressureMonitor,
            nitrogen: NitrogenMonitor,
            helium: HeliumMonitor,
            cold_head: ColdHeadMonitor,
            compressor: CompressorMonitor,
    ):
        """
        Parameters
        ----------
        measurement : Measurement
            The measurement object containing all the relevant data.
        pressure : PressureMonitor
            The pressure monitor object.
        nitrogen : NitrogenMonitor
            The nitrogen monitor object.
        helium : HeliumMonitor
            The helium monitor object.
        cold_head : ColdHeadMonitor
            The cold head monitor object.
        compressor : CompressorMonitor
            The compressor monitor object.
        """
        self._measurement = measurement
        self._pressure = pressure
        self._nitrogen = nitrogen
        self._helium = helium
        self._cold_head = cold_head
        self._compressor = compressor

        self.log_changed_statuses()
        self._bad_changes_persist = self.log_change_persistence()
        self.notify_if_necessary()
        self.send_daily_report_if_necessary()

    @property
    def bad_changes_persist(self):
        """
        Returns True if any bad changes in monitor statuses persist, False otherwise.
        Persistence is determined as a repeated status report over two consecutive measurements.

        Returns
        -------
        bool
            True if bad changes persist, False otherwise.
        """
        return self._bad_changes_persist

    @property
    def monitors(self) \
            -> tuple[PressureMonitor, NitrogenMonitor, HeliumMonitor, ColdHeadMonitor, CompressorMonitor]:
        """
        Returns a tuple of all monitor objects associated with this report.

        Returns
        -------
        tuple[PressureMonitor, NitrogenMonitor, HeliumMonitor, ColdHeadMonitor, CompressorMonitor]
            A tuple containing `PressureMonitor`, `NitrogenMonitor`, `HeliumMonitor`,
            `ColdHeadMonitor`, and `CompressorMonitor` objects.
        """
        return self._pressure, self._nitrogen, self._helium, self._cold_head, self._compressor

    @property
    def all_monitors_okay(self) -> bool:
        """
        Returns True if all monitors have INFO or (INFO, INFO) status, False otherwise.

        Returns
        -------
        bool
            True if all monitors are okay, False otherwise.
        """
        return all([monitor.type is (AlertType.INFO or (AlertType.INFO, AlertType.INFO)) for monitor in self.monitors])

    def get_troubled_monitors(self) -> list[PressureMonitor | NitrogenMonitor |
                                            HeliumMonitor | ColdHeadMonitor | CompressorMonitor]:
        """
        Returns a sorted list of monitors with non-INFO status.
        The list is sorted by `alertType` significance.

        Returns
        -------
        list[PressureMonitor | NitrogenMonitor | HeliumMonitor | ColdHeadMonitor | CompressorMonitor]
            A sorted list of `PressureMonitor`, `NitrogenMonitor`, `HeliumMonitor`,
            `ColdHeadMonitor`, and `CompressorMonitor` objects with non-INFO status.
        """
        troubled_monitors = [monitor for monitor in self.monitors
                             if monitor.type is not (AlertType.INFO or (AlertType.INFO, AlertType.INFO))]
        return sorted(troubled_monitors, reverse=True)

    def get_statuses(self) \
            -> dict[str,
                    PressureStatus | NitrogenStatus | HeliumStatus |
                    ColdHeadTemperatureStatus | ColdHeadHeaterStatus | CompressorStatus]:
        """
        Returns a dictionary of monitor statuses.

        Returns
        -------
        dict
            A dictionary where keys are monitor identifiers and values are corresponding
            status objects.
        """
        statuses = {}
        for monitor in self.monitors:
            if not isinstance(monitor.status, tuple):
                statuses[monitor.identifier] = monitor.status
            else:  # Change to a more generic implementation if you define a new Monitor with multiple statuses
                statuses['cold_head_temperature'] = monitor.status[0]
                statuses['cold_head_heater'] = monitor.status[1]

        return statuses

    def get_troubling_statuses(self) \
            -> dict[str,
                    PressureStatus | NitrogenStatus | HeliumStatus |
                    ColdHeadTemperatureStatus | ColdHeadHeaterStatus | CompressorStatus]:
        """
        Returns a dictionary of statuses from troubled monitors.

        Returns
        -------
        dict
            A dictionary with keys as monitor identifiers and values as status objects
            of only troubled monitors.
        """
        troubled_monitors = self.get_troubled_monitors()
        troubling_statuses = {}

        for monitor in troubled_monitors:
            if not isinstance(monitor.status, tuple):
                troubling_statuses[monitor.identifier] = monitor.status
            else:  # Change to a more generic implementation if you define a new Monitor with multiple statuses
                if monitor.status[0] != ColdHeadTemperatureStatus.NORMAL:
                    troubling_statuses['cold_head_temperature'] = monitor.status[0]
                if monitor.status[1] != ColdHeadHeaterStatus.NORMAL:
                    troubling_statuses['cold_head_heater'] = monitor.status[1]

        return troubling_statuses

    def log_changed_statuses(self):
        """
        Logs changes in monitor statuses.

        This method compares current monitor statuses with previously recorded ones.
        If any changes occur, it logs them in the global `_status_changes` object.
        """
        global _status_changes
        latest_statuses = _status_changes.latest_statuses
        all_statuses = self.get_statuses()
        keys_to_be_appended = [key for key in all_statuses if latest_statuses[key] != all_statuses[key]]
        statuses_to_append = {key: all_statuses[key] for key in keys_to_be_appended}
        _status_changes.append_status_changes(self._measurement.timestamp, **statuses_to_append)

        if len(keys_to_be_appended):
            return True
        else:
            return False

    def log_change_persistence(self):
        """
        Checks and updates the `_bad_changes_persist` flag based on existing changes.

        This method iterates through existing status changes and checks if any bad changes
        persist. If so, the `_bad_changes_persist` will take a True value.

        Notes
        -----
        This method uses the same global variables `_status_changes` and
        `_latest_timestamps` as `log_changed_statuses`.
        """
        global _status_changes
        latest_statuses = _status_changes.latest_statuses
        latest_timestamps = _status_changes.latest_timestamps
        new_statuses = self.get_statuses()
        new_timestamp = self._measurement.timestamp

        bad_changes_persist = False
        for key in latest_statuses:
            if new_statuses[key] == latest_statuses[key] and new_timestamp != latest_timestamps[key]:
                if not _status_changes[key][-1].persisted:
                    _status_changes[key][-1].persisted = True
                    if key in self.get_troubling_statuses():
                        bad_changes_persist = True

        return bad_changes_persist

    def report_on_all_monitors(self, join_string: str = '\n\n') -> str:
        """
        Generates a report string containing messages from all monitors.

        Parameters
        ----------
        join_string : str, optional
            The string used to join individual monitor messages, defaults to '\n\n'.

        Returns
        -------
        str
            A string containing combined messages from all monitors.
        """
        return join_string.join([monitor.message for monitor in self.monitors])

    def report_on_troubled_monitors(self, join_string: str = '\n\n') -> str:
        """
        Generates a report string containing messages from troubled monitors.

        Parameters
        ----------
        join_string : str, optional
            The string used to join individual monitor messages, defaults to '\n\n'.

        Returns
        -------
        str
            A string containing combined messages from troubled monitors.
        """
        return join_string.join([monitor.message for monitor in self.get_troubled_monitors()])

    def repr_status_of_all_monitors(self, join_string: str = '\n\n') -> str:
        """
        Generates a string representing the status of all monitors.

        Parameters
        ----------
        join_string : str, optional
            The string used to join individual monitor status titles, defaults to '\n\n'.

        Returns
        -------
        str
            A string containing titles of all monitor statuses.
        """
        return join_string.join([monitor.message_title for monitor in self.monitors])

    def repr_status_of_troubled_monitors(self, join_string: str = ', ') -> str:
        """
        Generates a string representing the status of troubled monitors.
        The alert type will be the same as the first troubled monitor
        (the troubled monitor list is sorted but decreasing importance).

        Parameters
        ----------
        join_string : str, optional
            The string used to join individual monitor status titles, defaults to ', '.

        Returns
        -------
        str
            A string containing titles of troubled monitor statuses.
        """
        return join_string.join([monitor.message_title if i == 0 else monitor.message_title.split(': ')[1]
                                 for i, monitor in enumerate(self.get_troubled_monitors())])

    def notify_if_necessary(self):
        """
        Sends notifications if there are persistent bad changes in monitor statuses.
        Notification styles include: email/text, slack, local file.

        This method checks for several conditions before sending notifications:
            - There are troubled monitors (monitors with non-INFO status).
            - Bad changes persist over at least two measurements.
            - There are new bad status changes since the last notification.

        If all conditions are met, it sends email and Slack notifications using
        pre-defined helper functions.

        """
        global _status_changes

        if not len(self.get_troubled_monitors()) > 0:  # we only report if there is an issue to report
            return
        if not self.bad_changes_persist:  # we only report if issue persists
            return
        if not _status_changes.at_least_one_new_status_in_list(list(self.get_troubling_statuses().keys())):  # we only report new issues
            return

        self.write_report()
        self.notify_via_email()
        self.notify_via_slack()

    def notify_via_email(self):
        """
        Sends an email notification about troubled monitors.

        This method reads sender credentials and recipient addresses from a file,
        then composes an email using the report on troubled monitors and their statuses.
        Finally, it sends the email using a pre-defined `send_email` function.

        Notes
        -----
        The credentials should be stored in a yaml file.

        The general structure is:

        ```yaml
        sender_id: my_account_name
        sender_server: gmail.com
        sender_password: my_v3ry_53cur3_p455w0rd!
        recipients:
          - some_recipient@uw.edu
          - 1234567890@tmomail.net
        ```

        Alternative find the template in `email_info_template.yaml`.
        """
        # file = open(EMAIL_INFO_FILE_PATH, 'r')  # for txt file
        # sender_id, sender_password, *recipients = file.read().splitlines()
        # file.close()
        #
        # send_email(sender_id=sender_id, sender_password=sender_password, recipients=recipients,
        #            message=self.report_on_troubled_monitors(), subject=self.repr_status_of_troubled_monitors())

        with open(EMAIL_INFO_FILE_PATH, 'r') as file:
            email_info = yaml.safe_load(file)

        send_email(
            **email_info,
            message=self.report_on_troubled_monitors(),
            subject=self.repr_status_of_troubled_monitors()
        )

    def notify_via_slack(self):
        """
        Sends a Slack notification about troubled monitors.

        This method constructs Slack message blocks with titles and messages based on
        the report on troubled monitors and their statuses. Then, it sends the message
        using the `send_slack_message_via_webhook` function.
        """
        block_subject = HeaderBlock(text=self.repr_status_of_troubled_monitors())
        block_message = SectionBlock(text=PlainTextObject(text=self.report_on_troubled_monitors()))
        blocks = [block_subject, block_message]
        send_slack_message_via_webhook(blocks=blocks)

    def write_report(self):
        """
        Writes a report file containing timestamps and messages about troubled monitors.

        This method creates a filename based on the measurement timestamp and opens the
        file in append mode. Then, it writes a formatted string containing the timestamp,
        troubled monitor statuses, and a separator line.

        Notes
        -----
        This method assumes the existence of helper functions to format the
        timestamp and message strings, and constants like `FOLDER`, `ALERT_FILENAME_FORMAT`,
        and `EMAIL_TIMESTAMP_FORMAT`.
        """
        file_path: Path = DATA_STORAGE_FOLDER.joinpath(self._measurement.timestamp.strftime(ALERT_FILENAME_FORMAT))
        with open(str(file_path), 'a') as file:
            time_string = self._measurement.timestamp.strftime(EMAIL_TIMESTAMP_FORMAT)
            error_message = f"{self.repr_status_of_troubled_monitors()}\n\n{self.report_on_troubled_monitors()}"
            file.write(f"{time_string} | {error_message}\n\n-------------------------\n\n")

    def send_daily_report_if_necessary(self):
        """
        Finds out and if needed sends a daily report via Slack if sufficient time has passed since the last one.
        to submit the report, we use the `submit_daily_report_via_slack` class method.

        This method checks if enough time has passed since the last daily report
        based on pre-defined report times and the measurement timestamp. If enough time
        has passed, it submits a Slack message containing various information:

            - Worst monitor status
            - Status summary of all monitors
            - Measurement parameters and their values
        """
        global _last_daily_report_notification

        today = self._measurement.timestamp.date()
        yesterday = today - datetime.timedelta(days=1)

        report_times = [datetime.datetime.combine(yesterday, drt) for drt in DAILY_REPORT_TIMES]
        report_times += [datetime.datetime.combine(today, drt) for drt in DAILY_REPORT_TIMES]
        report_times_from_measurement = [self._measurement.timestamp - rt for rt in report_times]
        nearest_previous_report_time = min([rtfm for rtfm in report_times_from_measurement
                                            if rtfm > datetime.timedelta()])

        last_report_from_measurement = self._measurement.timestamp - _last_daily_report_notification

        if last_report_from_measurement > nearest_previous_report_time:
            self.submit_daily_report_via_slack()
            _last_daily_report_notification = self._measurement.timestamp

    def submit_daily_report_via_slack(self):
        """
        Submits a daily report to Slack with monitor statuses and measurement details.

        This method constructs Slack message blocks with information about:

            - Worst monitor status
            - Status summary of all monitors
            - Measurement parameters and their values

        Then, it sends the message using the `send_slack_message_via_webhook` function.

        Notes
        -----
        This method assumes the existence of helper functions to construct
        Slack message blocks and a `send_slack_message_via_webhook` function, as well as
        constants like `MEASUREMENT_HEADER_MAP` and `dict_to_markdown_table`.
        """
        worst_status = sorted(self.monitors)[-1].type.name
        block_subject = HeaderBlock(text=f'Status report → {worst_status}')

        status_text = '\n'.join([f'(*{m.type.name}*) {m.get_status_repr_string()}'
                                 for i, m in enumerate(self.monitors)])
        block_status = SectionBlock(text=MarkdownTextObject(text=status_text))

        measurement_dict = asdict(self._measurement)
        measurement_dict = {MEASUREMENT_HEADER_MAP[key]: measurement_dict[key] for key in measurement_dict}
        measurement_dict.pop('Timestamp')
        tabled_data = dict_to_markdown_table(measurement_dict, ('Parameters', 'Values'))
        block_data = SectionBlock(text=MarkdownTextObject(text=tabled_data))

        blocks = [block_subject, DividerBlock(), block_status, DividerBlock(), block_data]
        send_slack_message_via_webhook(blocks=blocks)


def check_pressure(pressure: float):
    """
    Checks the pressure level and returns a PressureMonitor object.

    Parameters
    ----------
    pressure : float
        The pressure value to check.

    Returns
    -------
    PressureMonitor
        A PressureMonitor object with the corresponding status and pressure value.
    """
    if np.isnan(pressure):
        status = PressureStatus.NO_READING
    elif pressure < PressureLimits.LOW:
        status = PressureStatus.LOW
    elif pressure > PressureLimits.HIGH:
        status = PressureStatus.HIGH
    else:
        status = PressureStatus.NORMAL

    pressure_alert = PressureMonitor(status, pressure)

    return pressure_alert


def check_nitrogen(nitrogen_level: float, nitrogen_refill_status: float | int):
    """
    Checks the nitrogen level and refill status, and
    returns a NitrogenMonitor object.

    Other nitrogen is considered to be refilling for too
    long if the refill status has persisted for more than
    `NITROGEN_REFILLING_FOR_TOO_LONG` hours.

    Parameters
    ----------
    nitrogen_level : float
        The nitrogen level value to check.
    nitrogen_refill_status : float | int
        An indicator of whether nitrogen is currently being refilled.

    Returns
    -------
    NitrogenMonitor
        A NitrogenMonitor object with the corresponding status and nitrogen level value.
    """
    if np.isnan(nitrogen_level):
        status = NitrogenStatus.NO_READING
    elif nitrogen_level < NitrogenLevelLimits.LOW:
        status = NitrogenStatus.LOW
    else:
        status = NitrogenStatus.NORMAL

    if nitrogen_refill_status:
        global _status_changes
        status = NitrogenStatus.REFILLING
        latest_nitrogen_status_timestamp = _status_changes.latest_timestamps['nitrogen']
        latest_nitrogen_status = _status_changes.latest_statuses['nitrogen']
        # TODO: Make more robust by taking into account 5-minute switch-on swith-offs that reset the following statement
        if latest_nitrogen_status is NitrogenStatus.REFILLING:
            datetime_now = datetime.datetime.now()
            time_for_refilling_for_too_long = datetime.timedelta(hours=NITROGEN_REFILLING_FOR_TOO_LONG)
            if datetime_now - latest_nitrogen_status_timestamp > time_for_refilling_for_too_long:
                status = NitrogenStatus.REFILLING_FOR_TOO_LONG
        elif latest_nitrogen_status is NitrogenStatus.REFILLING_FOR_TOO_LONG:
            status = NitrogenStatus.REFILLING_FOR_TOO_LONG

    nitrogen_alert = NitrogenMonitor(status, nitrogen_level)

    return nitrogen_alert


def check_helium(helium_level: float):
    """
    Checks the helium level and returns a HeliumMonitor object.

    Parameters
    ----------
    helium_level : float
        The helium level value to check.

    Returns
    -------
    HeliumMonitor
        A HeliumMonitor object with the corresponding status and helium level value.
    """
    # TODO: Implement time-dependent checks for refill
    if np.isnan(helium_level):
        status = HeliumStatus.NO_READING
    elif helium_level < HeliumLevelLimits.LOW:
        status = HeliumStatus.LOW
    else:
        status = HeliumStatus.NORMAL

    helium_alert = HeliumMonitor(status, helium_level)

    return helium_alert


def check_cold_head(temperature: float, heater_percentage: float):
    """
    Checks the cold head temperature and heater percentage,
    and returns a ColdHeadMonitor object.

    Parameters
    ----------
    temperature : float
        The cold head temperature value to check.
    heater_percentage : float
        The cold head heater percentage value to check.

    Returns
    -------
    ColdHeadMonitor
        A ColdHeadMonitor object with the corresponding temperature and heater status,
        and the raw temperature and heater percentage values.
    """
    if np.isnan(temperature):
        temperature_status = ColdHeadTemperatureStatus.NO_READING
    elif temperature < ColdHeadLimits.LOW_TEMPERATURE:
        temperature_status = ColdHeadTemperatureStatus.LOW
    elif temperature > ColdHeadLimits.HIGH_TEMPERATURE:
        temperature_status = ColdHeadTemperatureStatus.HIGH
    else:
        temperature_status = ColdHeadTemperatureStatus.NORMAL

    if np.isnan(heater_percentage):
        heater_status = ColdHeadHeaterStatus.NO_READING
    elif heater_percentage < ColdHeadLimits.LOW_HEATER_PERCENTAGE:
        heater_status = ColdHeadHeaterStatus.LOW
    elif heater_percentage > ColdHeadLimits.HIGH_HEATER_PERCENTAGE:
        heater_status = ColdHeadHeaterStatus.HIGH
    else:
        heater_status = ColdHeadHeaterStatus.NORMAL

    cold_head_alert = ColdHeadMonitor((temperature_status, heater_status), temperature, heater_percentage)

    return cold_head_alert


def check_compressor(
        pressure_status: PressureStatus,
        cold_head_temperature_status: ColdHeadTemperatureStatus,
        cold_head_heater_status: ColdHeadHeaterStatus,
):
    """
    Checks the pressure, cold head temperature, and cold head heater status,
    and returns a CompressorMonitor object.

    Parameters
    ----------
    pressure_status : PressureStatus
        The pressure status of the system.
    cold_head_temperature_status : ColdHeadTemperatureStatus
        The cold head temperature status.
    cold_head_heater_status : ColdHeadHeaterStatus
        The cold head heater status.

    Returns
    -------
    CompressorMonitor
        A CompressorMonitor object with the corresponding compressor status.
    """
    if pressure_status is PressureStatus.HIGH and cold_head_temperature_status is ColdHeadTemperatureStatus.HIGH:
        status = CompressorStatus.OFF
    else:
        status = CompressorStatus.ON
    return CompressorMonitor(status)


def get_monitor_report(measurement: Measurement):
    """
    Generates a MonitorReport object based on a measurement and monitor statuses.

    Parameters
    ----------
    measurement : Measurement
        The measurement object containing relevant data.

    Returns
    -------
    MonitorReport
        A MonitorReport object summarizing the measurement and monitor statuses.
    """
    pressure = check_pressure(measurement.pressure)
    nitrogen = check_nitrogen(measurement.nitrogen_level, measurement.refill_status)
    helium = check_helium(measurement.helium_level)
    cold_head = check_cold_head(measurement.cold_head_temperature, measurement.cold_head_heater_percentage)
    compressor = check_compressor(pressure.status, cold_head.temperature_status, cold_head.heater_status)

    return MonitorReport(measurement, pressure, nitrogen, helium, cold_head, compressor)


@dataclass
class _StatusChange:
    """
    Represents a change in status for a monitored component.

    Attributes
    ----------
    timestamp : datetime.datetime
        The timestamp when the status change occurred.
    status : PressureStatus | NitrogenStatus | HeliumStatus | ColdHeadTemperatureStatus | ColdHeadHeaterStatus | CompressorStatus
        The new status of the component.
    persisted : bool
        Indicates whether the status change has been persisted (e.g., saved to a database).
    """
    timestamp: datetime.datetime
    status: (PressureStatus | NitrogenStatus | HeliumStatus |
             ColdHeadTemperatureStatus | ColdHeadHeaterStatus | CompressorStatus)
    persisted: bool = False


class _StatusChangeDictType(TypedDict):
    timestamp: datetime.datetime
    status: PressureStatus | NitrogenStatus | HeliumStatus | ColdHeadTemperatureStatus | ColdHeadHeaterStatus | CompressorStatus
    persisted: bool


@dataclass
class StatusChanges:
    """
    Manages a collection of status changes for monitored components.

    Attributes
    ----------
    pressure : list[_StatusChange]
        A list of status changes for the pressure component.
    nitrogen : list[_StatusChange]
        A list of status changes for the nitrogen component.
    helium : list[_StatusChange]
        A list of status changes for the helium component.
    cold_head_temperature : list[_StatusChange]
        A list of status changes for the cold head temperature component.
    cold_head_heater : list[_StatusChange]
        A list of status changes for the cold head heater component.
    compressor : list[_StatusChange]
        A list of status changes for the compressor component.
    """
    pressure: list[_StatusChange] = field(default_factory=list, init=False)
    nitrogen: list[_StatusChange] = field(default_factory=list, init=False)
    helium: list[_StatusChange] = field(default_factory=list, init=False)
    cold_head_temperature: list[_StatusChange] = field(default_factory=list, init=False)
    cold_head_heater: list[_StatusChange] = field(default_factory=list, init=False)
    compressor: list[_StatusChange] = field(default_factory=list, init=False)

    def __getitem__(self, item):
        """ Returns the list of status changes for the specified component. """
        if item not in self._field_names():
            raise KeyError(f'Invalid key {item}')
        return self.__getattribute__(item)

    def as_dict(self) -> dict[str, list[_StatusChangeDictType]]:
        """ Returns a dictionary representation of the status changes. """
        return asdict(self)

    def _field_names(self):
        """ Returns a list of the field names (attributes) in the dataclass. """
        return [f.name for f in fields(self)]

    @property
    def latest_statuses(self) \
            -> dict[str,
                    PressureStatus | NitrogenStatus | HeliumStatus |
                    ColdHeadTemperatureStatus | ColdHeadHeaterStatus | CompressorStatus | None]:
        """ Returns a dictionary of the latest statuses for each component. """
        field_dict = self.as_dict()
        return {field_name: field_dict[field_name][-1]['status'] if len(field_dict[field_name]) else None
                for field_name in field_dict}

    @property
    def latest_timestamps(self) -> dict[str, datetime.datetime | None]:
        """ Returns a dictionary of the timestamps for the latest status changes for each component. """
        field_dict = self.as_dict()
        return {field_name: field_dict[field_name][-1]['timestamp'] if len(field_dict[field_name]) else None
                for field_name in field_dict}

    @property
    def latest_persistences(self) -> dict[str, bool]:
        """ Returns a dictionary indicating whether the latest
        status changes for each component have been persisted. """
        field_dict = self.as_dict()
        return {field_name: field_dict[field_name][-1]['persisted'] if len(field_dict[field_name]) else None
                for field_name in field_dict}

    def at_least_one_new_status_in_list(
            self,
            keys: list[Literal['pressure', 'nitrogen', 'helium',
                               'cold_head_temperature', 'cold_head_heater', 'compressor']]
            ):
        """ Checks if there's at least one new status (not
         previously persisted) in the specified list of components. """
        latest_statuses = self.latest_statuses

        for field_name in keys:
            if latest_statuses[field_name] not in [status_change.status for status_change in self[field_name]
                                                   if status_change.persisted][:-1]:
                return True

        return False

    def append_status_changes(
            self,
            timestamp: datetime.datetime,
            pressure: PressureStatus = None,
            nitrogen: NitrogenStatus = None,
            helium: HeliumStatus = None,
            cold_head_temperature: ColdHeadTemperatureStatus = None,
            cold_head_heater: ColdHeadHeaterStatus = None,
            compressor: CompressorStatus = None,
            remove_old_values=True,
    ):
        """ Appends a new status change for one or more components. """
        if pressure is not None:
            self.pressure.append(_StatusChange(timestamp, pressure))
        if nitrogen is not None:
            self.nitrogen.append(_StatusChange(timestamp, nitrogen))
        if helium is not None:
            self.helium.append(_StatusChange(timestamp, helium))
        if cold_head_temperature is not None:
            self.cold_head_temperature.append(_StatusChange(timestamp, cold_head_temperature))
        if cold_head_heater is not None:
            self.cold_head_heater.append(_StatusChange(timestamp, cold_head_heater))
        if compressor is not None:
            self.compressor.append(_StatusChange(timestamp, compressor))

        if remove_old_values:
            field_names = self._field_names()
            for field_name in field_names:  # loop through fields (e.g., pressure, compressor, etc.)
                if len(self[field_name]) == 0:
                    continue
                while (datetime.datetime.now() - self[field_name][0].timestamp >
                       datetime.timedelta(hours=STATUS_CHANGE_DISCARD_TIME)):
                    self[field_name].pop(0)  # remove the oldest element (the first one)
                    if len(self[field_name]) == 0:
                        break


_status_changes = StatusChanges()
""" An installation of the StatusChanges class. 
There should only be one that handles everything. """
_status_changes.append_status_changes(
    timestamp=datetime.datetime.now() - datetime.timedelta(hours=3),
    pressure=PressureStatus.NORMAL,
    nitrogen=NitrogenStatus.NORMAL,
    helium=HeliumStatus.NORMAL,
    cold_head_temperature=ColdHeadTemperatureStatus.NORMAL,
    cold_head_heater=ColdHeadHeaterStatus.NORMAL,
    compressor=CompressorStatus.ON,
)

# _last_daily_report_notification = datetime.datetime.now() - datetime.timedelta(days=1)
_last_daily_report_notification = datetime.datetime.now()
""" 
The first definition of the datetime for the last daily report. 
This object will be updated accordingly in the monitor report 
objects that are created for every measurement. 
"""