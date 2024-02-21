import datetime

from monitor.measurement import MEASUREMENT_HEADER_MAP

PLOTTABLE_PARAMETERS = ['None'] + list(MEASUREMENT_HEADER_MAP.values())[1:]

DEFAULT_INTERVAL = 60
DEFAULT_TEMPERATURE_CONTROLLER_INTERVAL = 10


class _DateConstants:

    _default_end_to_start_date_difference = datetime.timedelta(days=1)

    @property
    def default_end_to_start_date_difference(self):
        return self._default_end_to_start_date_difference

    @default_end_to_start_date_difference.setter
    def default_end_to_start_date_difference(self, value: datetime.timedelta):
        self._default_end_to_start_date_difference = value

    @property
    def default_end_date(self) -> datetime.datetime:
        return datetime.datetime.today()

    @property
    def default_start_date(self) -> datetime.datetime:
        return self.default_end_date - datetime.timedelta(days=1)


DynamicDateConstants = _DateConstants()

NEXT_LOG_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
DATE_ENTRY_FORMAT = '%m/%d/%Y'
PLOT_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
TABLE_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'

DEFAULT_WINDOW_STYLE_THEME = 'darkly'

DEFAULT_CRYOSTAT_MONITOR_WIDTH = 1440
DEFAULT_CRYOSTAT_MONITOR_HEIGHT = 890

DEFAULT_TEMPERATURE_CONTROLLER_WIDTH = 1470
DEFAULT_TEMPERATURE_CONTROLLER_HEIGHT = 650

DEFAULT_WIDGET_PADX = 5
DEFAULT_WIDGET_PADY = 5

HIGH_DPI_SCALING = 2.
