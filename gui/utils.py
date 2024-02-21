import datetime
import enum
import math
import re
import warnings
from pathlib import Path
from typing import Callable, Any

import pandas as pd
import ttkbootstrap
from PIL import ImageTk, Image, ImageDraw
from matplotlib import cbook
from matplotlib.axes import Axes
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
from ttkbootstrap import DEFAULT, FULL, utility, Bootstyle, M
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.validation import validator as ttk_validator, add_validation, ValidationEvent

from gui.constants import DATE_ENTRY_FORMAT, DEFAULT_WIDGET_PADX, DEFAULT_WIDGET_PADY


def str_is_float(string: str):
    try:
        float(string)
        return True
    except ValueError:
        return False


def get_photo_path(filename: str | Path) -> str:
    filename = Path(filename)
    filename_list = [
        Path('gui/graphics').joinpath(filename),
        Path('../graphics').joinpath(filename),
        Path('graphics').joinpath(filename),
        Path('../gui/graphics').joinpath(filename),
    ]
    for filename in filename_list:
        if filename.exists():
            return str(filename)


class DoubleVar(ttkbootstrap.DoubleVar):
    def __init__(self, master=None, value: float = None, name: str = None, round_digit: int = None):
        super().__init__(master, value, name)
        self._last_valid_value = self.get()
        self._round_digit = round_digit

    def set(self, value: float):
        if self._round_digit:
            value = round(value, self._round_digit)
        super().set(value)
        self._last_valid_value = value

    def _update_last_valid_value(self):
        value = self.get()
        if self._round_digit:
            value = round(value, self._round_digit)
        self._last_valid_value = value


    @property
    def last_valid_value(self) -> float:
        return self._last_valid_value


class StringVar(ttkbootstrap.StringVar):
    def __init__(self, master=None, value: str = None, name: str = None, round_digit: int = None):
        super().__init__(master, value, name)
        self._last_valid_value = self.get()
        self._round_digit = round_digit

    def set(self, value: str):
        if self._round_digit:
            value = f'{value}.{self._round_digit}f'
        super().set(value)
        self._last_valid_value = value

    def _update_last_valid_value(self):
        value = self.get()
        if self._round_digit:
            value = f'{value}.{self._round_digit}f'
        self._last_valid_value = value

    @property
    def last_valid_value(self) -> str:
        return self._last_valid_value


class Entry(ttkbootstrap.Entry):
    def __init__(self, master=None, starting_value=1.,
                 textvariable: DoubleVar | StringVar = None,
                 round_digit: int = None, post_validation_command: Callable[[], None] = None, **kwargs):
        super().__init__(master, **kwargs)

        self.value = textvariable or DoubleVar(self, starting_value)
        self.configure(textvariable=self.value)
        self.bind('<Key>', self.user_modification_action)
        add_validation(self, self.validate_interval, 'focusout')
        self.bind('<Return>', self.on_entry_submission)
        self.post_validation_command = post_validation_command
        self._round_digit = round_digit
        self._user_is_modifying = False

    @property
    def last_valid_value(self) -> float:
        return self.value.last_valid_value

    @property
    def user_is_modifying(self) -> bool:
        return self._user_is_modifying

    def user_modification_action(self, event=None):
        self._user_is_modifying = True

    @staticmethod
    @ttk_validator
    def validate_interval(event: ValidationEvent):
        self = event.widget
        if str_is_float(str(event.postchangetext)):
            if float(event.postchangetext) >= 0:
                self.value._update_last_valid_value()
                if self.post_validation_command is not None:
                    self.post_validation_command()
                self._user_is_modifying = False
                return True

        self.value.set(self.last_valid_value)
        return False

    def on_entry_submission(self, event=None):
        self.master.focus_set()

    def set_value(self, value):
        self.value.set(value)
        if self.post_validation_command is not None:
            self.post_validation_command()


class Spinbox(ttkbootstrap.Spinbox):
    def __init__(self, master=None, starting_value=1., values: list = None,
                 textvariable: DoubleVar | StringVar = None,
                 round_digit: int = None, post_validation_command: Callable[[], None] = None, **kwargs):
        super().__init__(master, **kwargs)

        self.value = textvariable or DoubleVar(self, starting_value)
        self.configure(values=values, textvariable=self.value)
        add_validation(self, self.validate_interval, 'focusout')
        self.bind('<Return>', self.on_entry_submission)
        self.bind('<<Increment>>', self.on_entry_submission)
        self.bind('<<Decrement>>', self.on_entry_submission)
        self.post_validation_command = post_validation_command
        self._round_digit = round_digit

    @property
    def last_valid_value(self) -> float:
        return self.value.last_valid_value

    @staticmethod
    @ttk_validator
    def validate_interval(event: ValidationEvent):
        self = event.widget
        if str_is_float(str(event.postchangetext)):
            if float(event.postchangetext) >= 0:
                self.value._update_last_valid_value()
                if self.post_validation_command is not None:
                    self.post_validation_command()
                return True

        self.value.set(self.last_valid_value)
        return False

    def on_entry_submission(self, event=None):
        self.master.focus_set()

    def set_value(self, value):
        self.value.set(value)
        if self.post_validation_command is not None:
            self.post_validation_command()


class CheckBox(ttkbootstrap.Checkbutton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value = ttkbootstrap.BooleanVar(self.master, True)
        self.configure(onvalue=True, offvalue=False, variable=self.value)
        self._recent_grid_info = self.grid_info()

    def grid(self, *args, **kwargs):
        super().grid(*args, **kwargs)
        self._recent_grid_info = self.grid_info()

    def show(self):
        self.grid(**self._recent_grid_info)

    def hide(self):
        self.grid_forget()


class DateWidget(ttkbootstrap.DateEntry):
    def __init__(self, master=None, post_validation_command: Callable[[], None] = None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.value = ttkbootstrap.StringVar(self, self.entry.get())
        self.entry.configure(textvariable=self.value)
        add_validation(self.entry, self.validate_entry, 'focusout')
        self.entry.bind('<Return>', self.on_entry_submission)
        self._post_validation_command = post_validation_command
        self._last_valid_value = self.value.get()

    @property
    def last_valid_value(self) -> str:
        return self._last_valid_value

    @staticmethod
    @ttk_validator
    def validate_entry(event: ValidationEvent):
        self: DateWidget = event.widget.master
        try:
            datetime.datetime.strptime(event.postchangetext, DATE_ENTRY_FORMAT)
            self._last_valid_value = event.postchangetext
            if self._post_validation_command is not None:
                self._post_validation_command()
            return True
        except Exception:
            self.value.set(self._last_valid_value)
            return False

    def on_entry_submission(self, event=None):
        self.focus_set()


class DateSuperWidget(ttkbootstrap.Frame):
    def __init__(self, master=None, startdate=None, checkboxtext: str = None,
                 command: Callable[[], None] = None, **kwargs):
        super().__init__(master, **kwargs)

        self.date_entry = DateWidget(self, command, startdate=startdate, width=11)
        self.check_box = CheckBox(self, text=checkboxtext, command=self._on_date_checkbox_toggle)
        self._command = command

        self.date_entry.pack(fill='both', expand=True, side='top', padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)
        self.check_box.pack(fill='both', expand=True, side='bottom', padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self._apply_state_changes()

    def _apply_state_changes(self):
        if self.check_box.value.get():
            self.date_entry.button.config(state="disabled")
            self.date_entry.entry.config(state="disabled")
        else:
            self.date_entry.button.config(state="normal")
            self.date_entry.entry.config(state="normal")

    def _on_date_checkbox_toggle(self):
        self._apply_state_changes()

        if self._command is not None:
            self._command()

    def get_date(self) -> datetime.datetime:
        return datetime.datetime.strptime(self.get_date_str(), DATE_ENTRY_FORMAT)

    def get_date_str(self) -> str:
        return self.date_entry.last_valid_value

    def set_from_date(self, date: datetime.datetime):
        date_str = date.strftime(DATE_ENTRY_FORMAT)
        self.set_from_date_str(date_str)

    def set_from_date_str(self, date: str):
        self.date_entry.value.set(date)

    def set_to_next_day(self):
        old_sde = self.get_date()
        new_sde = old_sde + datetime.timedelta(days=1)
        self.set_from_date(new_sde)

        if self._command is not None:
            self._command()


class CustomNavigationToolbar(NavigationToolbar2Tk):

    @staticmethod
    def _mouse_event_to_message(event: MouseEvent):
        if event.inaxes and event.inaxes.get_navigate():
            try:
                axes_list: list[Axes] = event.canvas.figure.axes
                data_points = [ax.transData.inverted().transform((event.x, event.y)) for ax in axes_list]
                s_list = [ax.format_coord(*data_point) for ax, data_point in zip(axes_list, data_points)]
                if all([ax.yaxis.get_visible() for ax in axes_list]):
                    try:
                        s = f'Left:\t{s_list[0]}\nRight:\t{s_list[1]}'.expandtabs(2)
                    except IndexError as e:
                        print(e)
                        s = str(e)
                else:
                    if axes_list[0].yaxis.get_visible():
                        s = s_list[0]
                    else:
                        s = s_list[1]
            except (ValueError, OverflowError):
                pass
            else:
                s = s.rstrip()
                artists = [a for a in event.inaxes._mouseover_set
                           if a.contains(event)[0] and a.get_visible()]
                if artists:
                    a = cbook._topmost_artist(artists)
                    if a is not event.inaxes.patch:
                        data = a.get_cursor_data(event)
                        if data is not None:
                            data_str = a.format_cursor_data(data).rstrip()
                            if data_str:
                                s = s + '\n' + data_str
                return s
        return ""


def get_dates(start: str, end: str, fmt: str = "%m/%d/%Y") -> list[datetime.date]:
    start_date = datetime.datetime.strptime(start, fmt).date()
    end_date = datetime.datetime.strptime(end, fmt).date()

    delta = end_date - start_date  # returns timedelta
    return [start_date + datetime.timedelta(days=i) for i in range(delta.days + 1)]


def pd_concat(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        # dfs = [df.reset_index(drop=True).dropna(axis=1, how='all') for df in dfs if not df.empty]
        # dfs = [df.reset_index(drop=True).dropna(axis=1, how='all') for df in dfs]
        dfs = [df.reset_index(drop=True) for df in dfs]
        dfs = [df for df in dfs]

        return pd.concat(dfs)


def get_plot_datetime_format(time_min: datetime.datetime, time_max: datetime.datetime, initial_fmt: str):
    time_delta = time_max - time_min

    fmt = initial_fmt
    if time_delta <= datetime.timedelta(weeks=53) and time_min.year == time_max.year:
        fmt = fmt.replace('%Y', '')
        fmt = fmt.replace('%y', '')
        fmt = fmt.replace('%G', '')
    if time_delta <= datetime.timedelta(days=31) and time_min.month == time_max.month:
        fmt = fmt.replace('%b', '')
        fmt = fmt.replace('%B', '')
        fmt = fmt.replace('%m', '')
    if time_delta <= datetime.timedelta(days=7) and time_min.isocalendar()[1] == time_max.isocalendar()[1]:
        # time_min.isocalendar()[1] is the week number (0 to 53)
        fmt = fmt.replace('%U', '')
        fmt = fmt.replace('%W', '')
        fmt = fmt.replace('%V', '')
    if time_delta <= datetime.timedelta(days=1) and time_min.day == time_max.day:
        fmt = fmt.replace('%a', '')
        fmt = fmt.replace('%A', '')
        fmt = fmt.replace('%w', '')
        fmt = fmt.replace('%u', '')
        fmt = fmt.replace('%j', '')
        fmt = fmt.replace('%d', '')
    if time_delta <= datetime.timedelta(hours=1) and time_min.hour == time_max.hour:
        fmt = fmt.replace('%H', '')
        fmt = fmt.replace('%I', '')
    if time_delta <= datetime.timedelta(minutes=1) and time_min.minute == time_max.minute:
        fmt = fmt.replace('%M', '')

    if time_delta >= datetime.timedelta(hours=1):
        fmt = fmt.replace('%S', '')
    if time_delta >= datetime.timedelta(hours=60):
        fmt = fmt.replace('%M', '')
    if time_delta >= datetime.timedelta(days=31):
        fmt = fmt.replace('%H', '')
        fmt = fmt.replace('%I', '')

    pattern = r'[^\w%][^\w%]|[^\w%]$'
    fmt = re.sub(pattern, '', fmt)
    pattern = r'^[^\w%]%'
    fmt = re.sub(pattern, '%', fmt)

    return fmt.strip(' ')
# import enum
# from typing import Any
#
# import ttkbootstrap as ttk
# from ttkbootstrap.dialogs import Messagebox
#
# from devices import TemperatureController
#
# app = ttk.Window()
#
# #
# # class ExtendedEnum(enum.Enum):
# #
# #     @classmethod
# #     def values(cls):
# #         return [c.value for c in cls]


class DiscreteRangeMeter(ttkbootstrap.Meter):
    #
    # class DiscreteRangeValues(enum.Enum):
    #     OFF = 0
    #     LOW = 1
    #     MEDIUM = 2
    #     HIGH = 3
    #
    # DEFAULT_HEATER_RANGE_VALUE_SAFETY = {0: 'warning', 1: 'danger', 2: 'info', 3: 'danger'}
    # DEFAULT_CHANNEL = 1

    def __init__(
            self,
            discrete_range_values: enum.EnumMeta,
            on_value_change_action: Callable[[int], Any] = None,
            discrete_range_value_safety: dict[int: str] = None,
            **kwargs
    ):
        self._user_is_modifying = False
        kwargs.setdefault('subtext', 'Discrete Range')
        super().__init__(
            amounttotal=len(discrete_range_values),
            stripethickness=int(360/len(discrete_range_values)),
            metertype="full",
            interactive=True,
            **kwargs
        )

        self.on_value_change_action = on_value_change_action
        self.discrete_range_values = discrete_range_values
        self.discrete_range_value_safety = discrete_range_value_safety

        self.discrete_range_var = ttkbootstrap.StringVar(self, value=None)
        self.textcenter.configure(textvariable=self.discrete_range_var)

        self.amountusedvar.trace_add("write", self._on_amountusedvar_write)
        default_hr_value = min([c.value for c in self.discrete_range_values])
        self.set_amountusedvar_hr_value(default_hr_value)

    def _on_amountusedvar_write(self, *_):
        val = self.get_hr_str_value(self.get_amountusedvar_hr_value())
        self.discrete_range_var.set(val)
        self.configure(bootstyle=self.get_bootstyle_by_hr_value())

    def get_hr_str_value(self, value: Any) -> str:
        return str(self.discrete_range_values(value).name).title()

    def get_bootstyle_by_hr_value(self) -> str:
        return self.discrete_range_value_safety[self.get_amountusedvar_hr_value()]

    def get_amountusedvar_hr_value(self) -> int:
        return self.amountusedvar.get() - 1

    def set_amountusedvar_hr_value(self, value: int):
        if isinstance(value, str):
            value = self.discrete_range_values[value.upper()].value
        self.amountusedvar.set(value + 1)

    def _on_dial_interact(self, e: ttkbootstrap.tk.Event):
        self._user_is_modifying = True
        previous_value = self.get_amountusedvar_hr_value()
        super()._on_dial_interact(e)
        new_value = self.get_amountusedvar_hr_value()
        if self._confirm_hr_change() == 'Yes':
            if self.on_value_change_action is not None:
                self.on_value_change_action(new_value)
            else:
                pass
        else:
            self.set_amountusedvar_hr_value(previous_value)
        self._user_is_modifying = False

    @property
    def user_is_modifying(self) -> bool:
        return self._user_is_modifying

    def _confirm_hr_change(self) -> bool:
        result = Messagebox.show_question(
            f"Are you sure you want to change the heater range to "
            f"{self.get_hr_str_value(self.get_amountusedvar_hr_value())}?",
            "Confirm Heater Range Change",
            self,
            ["Yes:secondary", "No:primary"],
        )
        return result


class MeterWithNeedle(ttkbootstrap.Meter):
    def __init__(
            self,
            master=None,
            bootstyle: str = DEFAULT,
            arcrange: float = None,
            arcoffset: float = None,
            amountstart: float = 0,
            amounttotal: float = 100,
            amountused: float = 0,
            wedgesize: float = 0,
            amountneedle: float = 0,
            needlesize: float = 1,
            stepsize: float = 1,
            metersize: int = 200,
            metertype: str = FULL,
            meterthickness: int = 10,
            showtext: bool = True,
            interactive: bool = False,
            stripethickness: int = 0,
            textleft: str = None,
            textright: str = None,
            textfont: str = "-size 20 -weight bold",
            subtext: str = None,
            subtextstyle: str = DEFAULT,
            subtextfont: str = "-size 10",
            needle_entry_width: float = 5,
            round_digit=3,
            needle_entry_setter_callable: Callable[[float | str], Any] = None,
            toggling_interaction=True,
            amountranges: list[tuple[float, float]] = None,
            saferange: list[tuple[float, float]] = None,
            **kwargs,
    ):
        """
        Parameters:

            master (Widget):
                The parent widget.

            arcrange (int):
                The range of the arc if degrees from start to end.

            arcoffset (int):
                The amount to offset the arc's starting position in degrees.
                0 is at 3 o'clock.

            amounttotal (int):
                The maximum value of the meter.

            amountused (int):
                The current value of the meter; displayed in a center label
                if the `showtext` property is set to True.

            wedgesize (int):
                Sets the length of the indicator wedge around the arc. If
                greater than 0, this wedge is set as an indicator centered
                on the current meter value.

            metersize (int):
                The meter is square. This represents the size of one side
                if the square as measured in screen units.

            bootstyle (str):
                Sets the indicator and center text color. One of primary,
                secondary, success, info, warning, danger, light, dark.

            metertype ('full', 'semi'):
                Displays the meter as a full circle or semi-circle.

            meterthickness (int):
                The thickness of the indicator.

            showtext (bool):
                Indicates whether to show the left, center, and right text
                labels on the meter.

            interactive (bool):
                Indicates that the user may adjust the meter value with
                mouse interaction.

            stripethickness (int):
                The indicator can be displayed as a solid band or as
                striped wedges around the arc. If the value is greater than
                0, the indicator changes from a solid to striped, where the
                value is the thickness of the stripes (or wedges).

            textleft (str):
                A short string inserted to the left of the center text.

            textright (str):
                A short string inserted to the right of the center text.

            textfont (Union[str, Font]):
                The font used to render the center text.

            subtext (str):
                Supplemental text that appears below the center text.

            subtextstyle (str):
                The bootstyle color of the subtext. One of primary,
                secondary, success, info, warning, danger, light, dark.
                The default color is Theme specific and is a lighter
                shade based on whether it is a 'light' or 'dark' theme.

            subtextfont (Union[str, Font]):
                The font used to render the subtext.

            stepsize (int):
                Sets the amount by which to change the meter indicator
                when incremented by mouse interaction.

            **kwargs:
                Other keyword arguments that are passed directly to the
                `Frame` widget that contains the meter components.
        """

        super(ttkbootstrap.ttk.Frame, self).__init__(master, "ttk::frame", **kwargs)

        self.needle_entry_setter_callable = needle_entry_setter_callable

        # widget variables
        self.amountusedvar_str = ttkbootstrap.StringVar(value=f'{amountused:.{round_digit}f}')
        self.amountusedvar = ttkbootstrap.DoubleVar(value=amountused)
        self.amountusedvar.trace_add("write", self.update_amountusedvar_label)
        self.amountusedvar.trace_add("write", self._draw_meter)

        self.amountneedlevar_str = StringVar(value=f'{amountneedle:.{round_digit}f}')
        self.amountneedlevar = ttkbootstrap.DoubleVar(self, value=amountneedle)
        self.amountneedlevar.trace_add("write", self.update_amountneedlevar_label)
        self.amountneedlevar.trace_add("write", self._draw_meter)

        self.amountstartvar = ttkbootstrap.DoubleVar(value=amountstart)
        self.amounttotalvar = ttkbootstrap.DoubleVar(value=amounttotal)
        self.labelvar = ttkbootstrap.StringVar(value=subtext)

        # misc settings
        self._set_arc_offset_range(metertype, arcoffset, arcrange)
        self._towardsmaximum = True
        self._metersize = utility.scale_size(self, metersize)
        self._meterthickness = utility.scale_size(self, meterthickness)
        self._stripethickness = stripethickness
        self._showtext = showtext
        self._wedgesize = wedgesize
        self._stepsize = stepsize
        self._textleft = textleft
        self._textright = textright
        self._textfont = textfont
        self._subtext = subtext
        self._subtextfont = subtextfont
        self._subtextstyle = subtextstyle
        self._bootstyle = bootstyle
        self._interactive = interactive
        self._bindids = {}
        self._needlesize = needlesize
        self._needle_entry_width = needle_entry_width
        self._round_digit = round_digit
        self._toggling_interaction = toggling_interaction
        self._amountranges = amountranges
        self._saferange = saferange

        self._value_before_interaction: float | None = None

        self._setup_widget()
        self.set_amountused_bootstyle_by_saferange()

    @property
    def value_before_interaction(self) -> float | None:
        return self._value_before_interaction

    def set_amountused_bootstyle_by_saferange(self):
        if self._saferange is None:
            return
        value = self['amountused']
        if self._saferange[0][0] <= value <= self._saferange[0][1]:
            self.configure(bootstyle='info')
        elif self._saferange[1][0] <= value <= self._saferange[1][1]:
            self.configure(bootstyle='warning')
        else:
            self.configure(bootstyle='danger')

    def update_amountusedvar_label(self, *_):
        value = float(self.amountusedvar_str.get())
        if value != self["amountused"]:
            self.amountusedvar_str.set(f'{self["amountused"]:.{self._round_digit}f}')
        self.set_amountused_bootstyle_by_saferange()

    def update_amountneedlevar_label(self, *_):
        value = float(self.amountneedlevar_str.last_valid_value)
        if value != self["amountneedle"]:
            self.amountneedlevar_str.set(f'{self["amountneedle"]:.{self._round_digit}f}')

    def _setup_widget(self):
        self.meterframe = ttkbootstrap.Frame(
            master=self, width=self._metersize, height=self._metersize
        )
        self.indicator = ttkbootstrap.Label(self.meterframe)
        self.textframe = ttkbootstrap.Frame(self.meterframe)
        self.textleft = ttkbootstrap.Label(
            master=self.textframe,
            text=self._textleft,
            font=self._subtextfont,
            bootstyle=(self._subtextstyle, "metersubtxt"),
            anchor=ttkbootstrap.tk.S,
            padding=(0, 5),
        )
        self.textcenter = ttkbootstrap.Label(
            master=self.textframe,
            textvariable=self.amountusedvar_str,
            bootstyle=(self._bootstyle, "meter"),
            font=self._textfont,
        )
        self.textright = ttkbootstrap.Label(
            master=self.textframe,
            text=self._textright,
            font=self._subtextfont,
            bootstyle=(self._subtextstyle, "metersubtxt"),
            anchor=ttkbootstrap.tk.S,
            padding=(0, 5),
        )
        self.subtextframe = ttkbootstrap.Frame(self.meterframe)
        self.subtext = ttkbootstrap.Label(
            master=self.subtextframe,
            text=self._subtext,
            bootstyle=(self._subtextstyle, "metersubtxt"),
            font=self._subtextfont,
            anchor=ttkbootstrap.tk.S,
            padding=(0, 5)
        )
        self.subtext.grid(row=0, column=0, padx=0, sticky='s')
        # self.needleentry = ttk.Label(
        #     master=self.subtextframe,
        #     textvariable=self.amountneedlevar_str,
        #     bootstyle=(self._subtextstyle, "metersubtxt"),
        #     font=self._textfont,
        #     anchor=ttk.tk.S,
        # )
        needle_entry_state = "normal" if self._interactive else "disabled"
        self.needleentry = Entry(
            master=self.subtextframe,
            textvariable=self.amountneedlevar_str,
            # bootstyle=(self._subtextstyle, "metersubtxt"),
            font=self._subtext,
            round_digit=self._round_digit,
            width=self._needle_entry_width,
            state=needle_entry_state,
            # anchor=ttk.tk.S,
            # from_=self.amountstartvar.get(),
            # to=self.amounttotalvar.get(),
            # increment=self._stepsize,
            post_validation_command=self._text_needle_post_validation_command,
        )
        self.needleentry.grid(row=0, column=1, padx=0, sticky='s')
        self.subtextright = ttkbootstrap.Label(
            master=self.subtextframe,
            text=self._textright,
            font=self._subtextfont,
            bootstyle=(self._subtextstyle, "metersubtxt"),
            anchor=ttkbootstrap.tk.S,
            padding=(0, 5)
        )
        self.subtextright.grid(row=0, column=2, padx=0, sticky='s')
        self.interaction_toggle_box = CheckBox(self.meterframe, bootstyle="info-round-toggle",
                                               text='Adjustable',command=self._on_toggle_box_action)
        self.interaction_toggle_box.value.set(self._interactive)

        self.bind("<<ThemeChanged>>", self._on_theme_change)
        self.bind("<<Configure>>", self._on_theme_change)
        self._set_interactive_bind()
        self._draw_base_image()
        self._draw_meter()

        # set widget geometry
        self.indicator.place(x=0, y=0)
        self.meterframe.pack()
        self._set_show_text()

    def _on_toggle_box_action(self, event=None):
        self['interactive'] = self.interaction_toggle_box.value.get()

    def _text_needle_post_validation_command(self):
        self._value_before_interaction = self.amountneedlevar.get()
        self.amountneedlevar.set(float(self.amountneedlevar_str.get()))
        self._on_dial_release()

    def _set_show_text(self):
        self.subtextframe.pack_forget()
        self.interaction_toggle_box.pack_forget()
        super()._set_show_text()
        self._set_toggle_box()

    def _set_subtext(self):
        self.subtext.grid(row=0, column=0)
        self.needleentry.grid(row=0, column=1)
        self.subtextright.grid(row=0, column=2, padx=5)
        if self._subtextfont:
            if self._showtext:
                self.subtextframe.place(relx=0.5, rely=0.6, anchor=ttkbootstrap.tk.CENTER)
            else:
                self.subtextframe.place(relx=0.5, rely=0.5, anchor=ttkbootstrap.tk.CENTER)

    def _set_toggle_box(self):
        if self._toggling_interaction:
            self.interaction_toggle_box.place(relx=0.5, rely=0.3, anchor=ttkbootstrap.tk.CENTER)
            self._on_toggle_box_action()

    def _set_amountrange(self):
        if self._amountranges is None:
            return

        needle_value = self['amountneedle']
        used_value = self['amountused']
        start_value = self['amountstart']
        total_value = self['amounttotal']

        for rng in self._amountranges:
            if rng[0] < needle_value < rng[1] and rng[0] < used_value < rng[1]:
                self.amountstartvar.set(rng[0])
                self.amounttotalvar.set(rng[1])
                break

    def _draw_meter(self, *_):
        """Draw a meter"""
        self._set_amountrange()
        img = self._base_image.copy()
        draw = ImageDraw.Draw(img)
        if self._stripethickness > 0:
            self._draw_striped_meter(draw)
        else:
            self._draw_solid_meter(draw)

        self._draw_meter_needle(draw)

        self._meterimage = ImageTk.PhotoImage(
            img.resize((self._metersize, self._metersize), Image.BICUBIC)
        )
        self.indicator.configure(image=self._meterimage)

    def _draw_meter_needle(self, draw: ImageDraw.Draw):
        x1 = y1 = self._metersize * M - 20
        width = self._meterthickness * M

        # bootstyle = (self._subtextstyle, "metersubtxt")
        bootstyle = (self._subtextstyle, "metersubtxt", "label")
        ttkstyle = Bootstyle.ttkstyle_name(string="-".join(bootstyle))
        textcolor = self._lookup_style_option(ttkstyle, "foreground")

        needle_value = self._needle_meter_value()
        draw.arc(
            xy=(0, 0, x1, y1),
            start=needle_value - self._needlesize,
            end=needle_value + self._needlesize,
            fill=textcolor,
            width=width,
        )

    def _needle_meter_value(self) -> float:
        """Calculate the value to be used to draw the arc length of the
        needle meter."""
        rel_value = (self["amountneedle"] - self["amountstart"]) / (self["amounttotal"] - self["amountstart"])
        value = rel_value * self._arcrange + self._arcoffset
        return value

    def _meter_value(self) -> float:
        """Calculate the value to be used to draw the arc length of the
        progress meter."""
        rel_value = (self["amountused"] - self["amountstart"]) / (self["amounttotal"] - self["amountstart"])
        value = rel_value * self._arcrange + self._arcoffset
        return value

    def _set_interactive_bind(self):
        seq1 = "<B1-Motion>"
        seq2 = "<Button-1>"
        seq3 = "<ButtonRelease-1>"

        if self._interactive:
            self._bindids[seq1] = self.indicator.bind(
                seq1, self._on_dial_interact
            )
            self._bindids[seq2] = self.indicator.bind(
                seq2, self._on_dial_interact
            )
            self._bindids[seq3] = self.indicator.bind(
                seq3, self._on_dial_release
            )
            return

        if seq1 in self._bindids:
            self.indicator.unbind(seq1, self._bindids.get(seq1))
            self.indicator.unbind(seq2, self._bindids.get(seq2))
            self.indicator.unbind(seq3, self._bindids.get(seq3))
            self._bindids.clear()

    def _set_widget_colors(self):
        super()._set_widget_colors()
        bootstyle = (self._bootstyle, "meter", "label")
        ttkstyle = Bootstyle.ttkstyle_name(string="-".join(bootstyle))
        dark = self._lookup_style_option(ttkstyle, "dark")
        self._needlecolor = dark

    def _on_dial_interact(self, e: ttkbootstrap.tk.Event):
        """Callback for mouse drag motion on meter indicator"""
        if self._value_before_interaction is None:
            self._value_before_interaction = self.amountneedlevar.get()

        dx = e.x - self._metersize // 2
        dy = e.y - self._metersize // 2
        rads = math.atan2(dy, dx)
        degs = math.degrees(rads)

        if degs > self._arcoffset:
            factor = degs - self._arcoffset
        else:
            factor = 360 + degs - self._arcoffset

        # clamp the value between 0 and `amounttotal`
        amountstart = self.amountstartvar.get()
        amounttotal = self.amounttotalvar.get() - amountstart
        lastused = self.amountneedlevar.get() - amountstart
        amountneedle = (amounttotal / self._arcrange * factor)

        # calculate amount used given stepsize
        if amountneedle > self._stepsize / 2:
            amountneedle = round(amountneedle // self._stepsize * self._stepsize + self._stepsize, self._round_digit)
        else:
            amountneedle = 0
        # if the number is the same, then do not redraw
        if lastused == amountneedle:
            return
        # set the amount used variable
        if amountneedle < 0:
            self.amountneedlevar.set(0)
        elif amountneedle > amounttotal:
            self.amountneedlevar.set(amounttotal + amountstart)
        else:
            self.amountneedlevar.set(amountneedle + amountstart)

    def _on_dial_release(self, e: ttkbootstrap.tk.Event = None):
        if self._confirm_needle_change() == 'Yes':
            if self.needle_entry_setter_callable is not None:
                self.needle_entry_setter_callable(self.amountneedlevar.get())
            else:
                pass
        else:
            self.amountneedlevar.set(self._value_before_interaction)
        self._value_before_interaction = None

    def _confirm_needle_change(self) -> bool:
        result = Messagebox.show_question(
            f"Are you sure you want to change the {self._subtext} to "
            f"{self.amountneedlevar_str.get()}?",
            f"Confirm {self._subtext} Change",
            self,
            ["Yes:secondary", "No:primary"],
        )
        return result

    def _configure_get(self, cnf):
        """Override the configuration get method"""
        if cnf == "amountstart":
            return self.amountstartvar.get()
        elif cnf == "amountneedle":
            return self.amountneedlevar.get()
        elif cnf == "needlesize":
            return self._needlesize
        elif cnf == "needle_entry_width":
            return self._needle_entry_width
        elif cnf == "device":
            return self._device
        elif cnf == "channel":
            return self._channel
        elif cnf == "round_digit":
            return self._round_digit
        else:
            return super()._configure_get(cnf)

    def _configure_set(self, **kwargs):
        if "interactive" in kwargs:
            self._interactive = kwargs.pop("interactive")
            needle_entry_state = "normal" if self._interactive else "disabled"
            self.needleentry.configure(state=needle_entry_state)
            self._set_interactive_bind()
        if "amountstart" in kwargs:
            amountstart = kwargs.pop("amountstart")
            self.amountstartvar.set(amountstart)
        if "amountneedle" in kwargs:
            amountneedle = kwargs.pop("amountneedle")
            self.amountneedlevar.set(amountneedle)
        if "needlesize" in kwargs:
            self._needlesize = kwargs.pop("needlesize")
        if "needle_entry_width" in kwargs:
            self._needle_entry_width = kwargs.pop("needle_entry_width")
        if "device" in kwargs:
            self._device = kwargs.pop("device")
        if "channel" in kwargs:
            self._channel = kwargs.pop("channel")
        if "round_digit" in kwargs:
            self._round_digit = kwargs.pop("round_digit")

        super()._configure_set(**kwargs)
