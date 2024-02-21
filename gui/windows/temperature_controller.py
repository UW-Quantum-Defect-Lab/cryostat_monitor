import ctypes
import threading
import time
import datetime
from functools import partial
from typing import Callable

import ttkbootstrap
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.scrolled import ScrolledFrame
from ttkbootstrap.utility import enable_high_dpi_awareness

from devices import TemperatureController
from devices.devices import ColdHeadHeaterOnPressureStabilization
from gui.constants import DEFAULT_WINDOW_STYLE_THEME, DEFAULT_WIDGET_PADX, DEFAULT_WIDGET_PADY, \
    NEXT_LOG_DATETIME_FORMAT, DEFAULT_TEMPERATURE_CONTROLLER_INTERVAL, DEFAULT_TEMPERATURE_CONTROLLER_WIDTH, \
    DEFAULT_TEMPERATURE_CONTROLLER_HEIGHT, HIGH_DPI_SCALING
from gui.utils import MeterWithNeedle, DiscreteRangeMeter, Spinbox, CheckBox, Entry, get_photo_path
from monitor.measurement import TemperatureControllerMeasurement
from monitor.utils import dummy_temperature_controller_acquisition, get_temperature_controller_instance, \
    temperature_controller_acquisition


class TemperatureControllerGraphics(ttkbootstrap.Frame):
    def __init__(self, parent, device: TemperatureController = None, read_pressure_method: Callable[[], float] = None):
        parent.title("Temperature Controller" if device else "DUMMY Temperature Controller")
        super().__init__(parent)

        self._device = device
        self._read_pressure_method = read_pressure_method

        self.style = ttkbootstrap.Style(DEFAULT_WINDOW_STYLE_THEME)
        self.stop_collection_event: threading.Event | None = None
        self.stop_warmup_event: threading.Event | None = None

        self._create_widgets()

    def _create_widgets(self):
        self._create_user_input_frame()
        self._create_temperature_frame()

    def _create_temperature_frame(self):
        self.meters_frame = ttkbootstrap.Frame(self.master)
        self._create_cold_head_temperature_widgets()
        self._create_sample_space_temperature_widgets()

        self.meters_frame.pack(fill='both', expand=False, side='left',
                               padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

    def _create_user_input_frame(self):

        self._user_input_frame_row_count = 0
        self._create_data_collection_widgets()

        self.user_input_frame.container.update()
        req_width = self.user_input_frame.winfo_reqwidth()
        req_width += self.user_input_frame.vscroll.winfo_reqwidth()
        self.user_input_frame.container.configure(width=req_width)

    @property
    def interval(self) -> float:
        return self.interval_entry.last_valid_value

    def _create_data_collection_widgets(self):
        self.user_input_frame = ScrolledFrame(self.master, autohide=False)
        self.user_input_frame.pack(fill='both', expand=False, side='left',
                                   padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc = self._user_input_frame_row_count

        # ---------------- Interval ----------------
        ttkbootstrap.Label(self.user_input_frame, text="Interval (seconds):").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY, sticky='w')

        interval_values = [1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50, 60, 90, 120, 150, 180, 240, 300]

        self.interval_entry = Spinbox(
            self.user_input_frame, DEFAULT_TEMPERATURE_CONTROLLER_INTERVAL, interval_values, width=12)
        self.interval_entry.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc += 1

        # ---------------- Collection ----------------
        self.start_collection_button = ttkbootstrap.Button(
            self.user_input_frame, text="Start", command=self.start_collection, width=12)
        self.start_collection_button.grid(row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self.stop_collection_button = ttkbootstrap.Button(
            self.user_input_frame, text="Stop", command=self.stop_collection, state="disabled", width=12)
        self.stop_collection_button.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc += 1

        self.collection_status_label = ttkbootstrap.Label(self.user_input_frame, text="Idle")
        self.collection_status_label.grid(row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY,
                                          columnspan=2, sticky='ns')

        rc += 1

        self.reset_ch_heater_button = ttkbootstrap.Button(
            self.user_input_frame, text="Reset Cold Head Heater Output",
            command=self._on_reset_ch_heater)
        self.reset_ch_heater_button.grid(
            row=rc, column=0, columnspan=2, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY, sticky='we')

        rc += 1

        # ---------------- Warm up SS ----------------
        self.warmup_frame = ttkbootstrap.Frame(self.user_input_frame)
        self.warmup_frame.grid(
            row=rc, column=0, columnspan=2, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY, sticky='we')

        self.warmup_sample_space_button = CheckBox(
            self.warmup_frame, text="Warm up SS to (K): ", bootstyle='danger-square-toggle')
        self.warmup_sample_space_button.pack(
            fill='both', expand=True, side='left', padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)
        self.warmup_sample_space_button.value.set(False)
        self.warmup_sample_space_button.value.trace_add('write', self._on_warmup_sample_space_toggle)

        if self._device:
            target_temp = self._device.sample_space_warmup_target_temperature
        else:
            target_temp = 255
        self.warmup_target_temperature_entry = Entry(self.warmup_frame, target_temp, round_digit=0, width=5,
                                                     post_validation_command=self._on_warmup_target_temperature_update)
        self.warmup_target_temperature_entry.pack(
            fill='both', expand=False, side='left', padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc += 1

        # ---------------- Pressure stabilization ----------------
        self.pressure_stabilization_frame = ttkbootstrap.Frame(self.user_input_frame)
        self.pressure_stabilization_frame.grid(
            row=rc, column=0, columnspan=2, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY, sticky='we')

        self.pressure_stabilization_button = CheckBox(
            self.pressure_stabilization_frame, text="Stabilize to pressure (psi): ",
            bootstyle='danger-square-toggle')
        self.pressure_stabilization_button.pack(
            fill='both', expand=True, side='left', padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)
        self.pressure_stabilization_button.value.set(False)
        self.pressure_stabilization_button.value.trace_add('write', self._on_pressure_stabilization_toggle)

        target_pressure = round(self._read_pressure_method(), 2) if self._read_pressure_method else 1.7
        self.pressure_stabilization_target_pressure_entry = Entry(
            self.pressure_stabilization_frame, target_pressure, round_digit=2, width=5)
        self.pressure_stabilization_target_pressure_entry.pack(
            fill='both', expand=False, side='left', padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        if self._device and self._read_pressure_method:
            self.pressure_stabilization_instance = ColdHeadHeaterOnPressureStabilization(
                self._device, self._read_pressure_method,
                lambda: self.pressure_stabilization_target_pressure_entry.last_valid_value)
        else:
            self.pressure_stabilization_instance = None

        self._user_input_frame_row_count = rc + 1

    def _on_reset_ch_heater(self, *_):
        result = Messagebox.show_question(
            f"Are you sure you want to change RESET the Cold Head heater output? "
            f"This action will:\n\t1. Change the heater range to 'OFF'.\n\t2. Change the manual output to '0.0'.\n\t"
            f"3. Change the heater range to 'Medium'.",

            "Confirm RESET of Cold Head heater output",
            self,
            ["Yes:secondary", "No:primary"], width=1000
        )
        if result == 'Yes' and self._device is not None:
            self._device.connect()
            self._device.reset_cold_head_heater_output()
            self._device.disconnect()

    def _on_warmup_target_temperature_update(self):
        if self._device:
            self._device.sample_space_warmup_target_temperature = self.warmup_target_temperature_entry.get()

    def _on_warmup_sample_space_toggle(self, *_):
        if self.warmup_sample_space_button.value.get():
            result = Messagebox.show_question(
                f"Are you sure you want to change START warming the sample space to "
                f"{self.warmup_target_temperature_entry.last_valid_value}?\n"
                f"This action will:\n"
                f"\t1. Turn the sample space heater ON.\n"
                f"\t2. Monitor and adjust the heater to\n"
                f"\t   maintain a temperature change rate\n"
                f"\t   of 1 - 3 K/minute.\n"
                f"\t3. Maintain temperature within ±2 K.\n "
                f"MAKE SURE THE NEEDLE VALUE IS CLOSED BEFORE STARTING!!!",

                "Confirm START Sample Space warmup.",
                self,
                ["Yes:secondary", "No:primary"],
            )
            if result == 'Yes':
                if self._device is not None:
                    self._device.start_sample_space_warmup()
            else:
                self.warmup_sample_space_button.value.set(False)
        else:
            result = Messagebox.show_question(
                f"Are you sure you want to STOP warming the sample space?\n"
                f"This action will turn the sample space heater OFF, "
                f"and stop monitoring and adjusting the sample space temperature.",
                "Confirm STOP Sample Space warmup.",
                self,
                ["Yes:secondary", "No:primary"],
            )
            if result == 'Yes':
                if self._device is not None:
                    self._device.stop_sample_space_warmup()
            else:
                self.warmup_sample_space_button.value.set(True)

    def _on_pressure_stabilization_toggle(self, *_):
        if self.pressure_stabilization_button.value.get():
            result = Messagebox.show_question(
                f"Are you sure you want to change START stabilizing the cold head through the pressure reading "
                f"to {self.pressure_stabilization_target_pressure_entry.last_valid_value}?\n"
                f"This action will:\n"
                f"\t1. Estimate the average heater percentage (AHP).\n"
                f"\t2. Turn the heater off, set the manual output to the AHP, and turn the heater back on.\n"
                f"\t3. Change the manual output to keep the pressure stable.\n ",
                "Confirm START cold head pressure stabilization.",
                self,
                ["Yes:secondary", "No:primary"],
            )
            if result == 'Yes':
                if self.pressure_stabilization_instance is not None:
                    self.pressure_stabilization_instance.start_pressure_stabilization()
            else:
                self.pressure_stabilization_button.value.set(False)
        else:
            result = Messagebox.show_question(
                f"Are you sure you want to STOP stabilizing cold head via pressure?\n"
                f"This action will turn the cold head heater off, "
                f"set the cold head output to the average heater percentage measured prior "
                f"and turn the heater back on.",
                "Confirm STOP pressure stabilization.",
                self,
                ["Yes:secondary", "No:primary"],
            )
            if result == 'Yes':
                if self.pressure_stabilization_instance is not None:
                    self.pressure_stabilization_instance.stop_pressure_stabilization()
            else:
                self.pressure_stabilization_button.value.set(True)

    def _create_cold_head_temperature_widgets(self):
        self.cold_head_temperature_frame = ttkbootstrap.Frame(self.meters_frame)

        ttkbootstrap.Label(self.cold_head_temperature_frame, text='Cold\nHead', justify='center',
                           font="-size 20 -weight bold").pack(
            fill='both', expand=True, side='left', padx=DEFAULT_WIDGET_PADX+20, pady=DEFAULT_WIDGET_PADY, anchor='center')

        ch_temp_ranges = [(3.9, 4.3), (3, 10), (0, 25), (0, 80), (0, 140), (0, 310)]
        self.cold_head_temperature_meter = MeterWithNeedle(
            master=self.cold_head_temperature_frame,
            amountstart=ch_temp_ranges[0][0],
            amounttotal=ch_temp_ranges[0][0],
            amountranges=ch_temp_ranges,
            amountused=6.7,
            amountneedle=4.13,
            stepsize=0.001,
            round_digit=3,
            textleft='Temperature: ',
            textright='K',
            subtext='S.P.: ',
            interactive=True,
            saferange=[(4, 4.2), (3.9, 4.3)],
            needle_entry_setter_callable=self._device.wrap_single_action(self._device.set_cold_head_set_point) if self._device else None,
        )
        self.cold_head_temperature_meter.pack(fill='both', expand=True, side='left',
                                              padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self.cold_head_heater_range_meter = DiscreteRangeMeter(
            discrete_range_values=self._device.HeaterRangeValues
            if self._device else TemperatureController.HeaterRangeValues,
            on_value_change_action=self._device.wrap_single_action(self._device.set_cold_head_heater_range) if self._device else None,
            discrete_range_value_safety={0: 'warning', 1: 'danger', 2: 'info', 3: 'danger'},
            master=self.cold_head_temperature_frame,
            meterthickness=40,
            subtext='Heater Range'
        )
        self.cold_head_heater_range_meter.pack(fill='both', expand=True, side='left',
                                               padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self.cold_head_heater_percentage_meter = MeterWithNeedle(
            master=self.cold_head_temperature_frame,
            amountstart=0,
            amounttotal=100,
            amountused=36.5,
            amountneedle=36,
            stepsize=0.1,
            round_digit=1,
            textleft='Heater: ',
            textright='%',
            subtext='M.O.: ',
            interactive=True,
            saferange=[(29, 43), (15, 50)],
            meterthickness=20,
            needle_entry_setter_callable=self._device.wrap_single_action(self._device.set_cold_head_manual_output) if self._device else None,
        )
        self.cold_head_heater_percentage_meter.pack(fill='both', expand=True, side='left',
                                                    padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self.cold_head_temperature_frame.pack(fill='both', expand=True, side='top',
                                              padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

    def _create_sample_space_temperature_widgets(self):
        self.sample_space_temperature_frame = ttkbootstrap.Frame(self.meters_frame)

        ttkbootstrap.Label(self.sample_space_temperature_frame, text='Sample\nSpace', justify='center',
                           font="-size 20 -weight bold").pack(
            fill='both', expand=True, side='left', padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        ss_temp_ranges = [(1.4, 10), (0, 25), (0, 80), (0, 140), (0, 300)]
        self.sample_space_temperature_meter = MeterWithNeedle(
            master=self.sample_space_temperature_frame,
            amountstart=ss_temp_ranges[0][0],
            amounttotal=ss_temp_ranges[0][0],
            amountranges=ss_temp_ranges,
            amountused=5.254,
            amountneedle=6.,
            stepsize=0.01,
            round_digit=3,
            textleft='Temperature: ',
            textright='K',
            subtext='S.P.: ',
            saferange=[(1.4, 10), (1.4, 20)],
            needle_entry_setter_callable=self._device.wrap_single_action(self._device.set_sample_space_set_point) if self._device else None,
        )

        self.sample_space_temperature_meter.pack(fill='both', expand=True, side='left',
                                                 padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)
        self.sample_space_heater_range_meter = DiscreteRangeMeter(
            discrete_range_values=self._device.HeaterRangeValues
            if self._device else TemperatureController.HeaterRangeValues,
            on_value_change_action=self._device.wrap_single_action(self._device.set_sample_space_heater_range) if self._device else None,
            discrete_range_value_safety={0: 'info', 1: 'warning', 2: 'warning', 3: 'danger'},
            master=self.sample_space_temperature_frame,
            meterthickness=40,
            subtext='Heater Range',
        )
        self.sample_space_heater_range_meter.pack(fill='both', expand=True, side='left',
                                                  padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self.sample_space_heater_percentage_meter = MeterWithNeedle(
            master=self.sample_space_temperature_frame,
            amountstart=0,
            amounttotal=100,
            amountused=0,
            amountneedle=0,
            stepsize=0.1,
            round_digit=1,
            textleft='Heater: ',
            textright='%',
            subtext='M.O.: ',
            saferange=[(0, 0), (0, 0)],
            meterthickness=20,
            needle_entry_setter_callable=self._device.wrap_single_action(self._device.set_sample_space_manual_output) if self._device else None,
        )
        self.sample_space_heater_percentage_meter.pack(fill='both', expand=True, side='left',
                                                       padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self.sample_space_temperature_frame.pack(fill='both', expand=True, side='bottom',
                                                 padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

    def update_meters(self, measurement: TemperatureControllerMeasurement):
        # Cold Head
        self.cold_head_temperature_meter.amountusedvar.set(measurement.ch_temp)
        if not self.cold_head_temperature_meter.needleentry.user_is_modifying and \
                self.cold_head_temperature_meter.value_before_interaction is None:
            self.cold_head_temperature_meter.amountneedlevar.set(measurement.ch_set_point)

        if not self.cold_head_heater_range_meter.user_is_modifying:
            self.cold_head_heater_range_meter.set_amountusedvar_hr_value(measurement.ch_heater_range)

        self.cold_head_heater_percentage_meter.amountusedvar.set(measurement.ch_heater_percent)
        if not self.cold_head_heater_percentage_meter.needleentry.user_is_modifying and \
                self.cold_head_heater_percentage_meter.value_before_interaction is None:
            self.cold_head_heater_percentage_meter.amountneedlevar.set(measurement.ch_manual_output)

        # Sample Space
        self.sample_space_temperature_meter.amountusedvar.set(measurement.ss_temp)
        if not self.sample_space_temperature_meter.needleentry.user_is_modifying and \
                self.sample_space_temperature_meter.value_before_interaction is None:
            self.sample_space_temperature_meter.amountneedlevar.set(measurement.ss_set_point)

        if not self.sample_space_heater_range_meter.user_is_modifying:
            self.sample_space_heater_range_meter.set_amountusedvar_hr_value(measurement.ss_heater_range)

        self.sample_space_heater_percentage_meter.amountusedvar.set(measurement.ss_heater_percent)
        if not self.sample_space_heater_percentage_meter.needleentry.user_is_modifying and \
                self.sample_space_heater_percentage_meter.value_before_interaction is None:
            self.sample_space_heater_percentage_meter.amountneedlevar.set(measurement.ss_manual_output)

    def _single_data_acquisition(self):
        if self._device:
            return temperature_controller_acquisition(self._device)
        else:
            return dummy_temperature_controller_acquisition()

    def collect_data(self, stop_event: threading.Event):
        counter = 0
        while not stop_event.is_set():
            counter += 1
            start_time = time.time()
            try:
                measurement = self._single_data_acquisition()
                self.update_meters(measurement)
            except Exception as e:
                print("Error collecting data:", e)
            self.segmented_collection_sleep(start_time, stop_event, 0.5)

    def segmented_collection_sleep(self, start_time, stop_event: threading.Event, time_step):
        remaining_time = self.interval - (time.time() - start_time)

        next_log = datetime.datetime.fromtimestamp(start_time + self.interval).strftime(NEXT_LOG_DATETIME_FORMAT)
        next_log_original = next_log
        self.collection_status_label.config(text=f'Next @ {next_log}')

        while remaining_time > 0 and not stop_event.is_set():

            next_log = datetime.datetime.fromtimestamp(start_time + self.interval).strftime(NEXT_LOG_DATETIME_FORMAT)
            if next_log_original != next_log:
                self.collection_status_label.config(text=f'Next @ {next_log}')
                next_log_original = next_log

            time.sleep(remaining_time if remaining_time < time_step else time_step)
            remaining_time = self.interval - (time.time() - start_time)

            try:  # in case parent program is suddenly shut down
                self.update_idletasks()
            except RuntimeError:
                self.stop_collection_event.set()

    def start_collection(self):
        self.start_collection_button.config(state="disabled")
        self.collection_status_label.config(text="Starting...")
        self.stop_collection_button.config(state="normal")
        self.stop_collection_event = threading.Event()
        thread_target = partial(self.collect_data, self.stop_collection_event)
        thread = threading.Thread(target=thread_target)

        thread.start()
        self.collection_status_label.config(text="Started!")

    def stop_collection(self):
        self.stop_collection_event.set()
        self.collection_status_label.config(text="Idle")
        self.start_collection_button.config(state="normal")
        self.stop_collection_button.config(state="disabled")

    def destroy(self):
        if self.stop_collection_event:
            self.stop_collection_event.set()
        super().destroy()


class TemperatureControllerWindow(ttkbootstrap.Window):
    def __init__(self, want_default_geometry=True, title='Temperature Controller', *args, **kwargs):
        super().__init__(title, *args, **kwargs)

        photo_path = get_photo_path("thermometer-snow.png")
        photo = ttkbootstrap.PhotoImage(file=photo_path)
        self.wm_iconphoto(False, photo)

        enable_high_dpi_awareness(self, HIGH_DPI_SCALING)

        device = get_temperature_controller_instance()
        self.main_frame = TemperatureControllerGraphics(self, device)

        if want_default_geometry:
            self._set_default_geometry()

    def _set_default_geometry(self):
        width = DEFAULT_TEMPERATURE_CONTROLLER_WIDTH
        height = DEFAULT_TEMPERATURE_CONTROLLER_HEIGHT

        s_width = self.winfo_screenwidth()
        s_height = self.winfo_screenheight()
        self.update()

        displacement_x = int(s_width / 2 - width / 2)
        displacement_y = int(s_height / 2 - 3 * height / 5)

        self.geometry(f'{width}x{height}+{displacement_x}+{displacement_y}')

    def destroy(self):
        # TODO: update with notification if program stops working
        print('Notify users that the Temperature Controller Window is off')
        super().destroy()


class TemperatureControllerTopLevel(ttkbootstrap.Toplevel):
    def __init__(self, want_default_geometry=True, title='Temperature Controller',
                 device: TemperatureController = None, *args, **kwargs):
        super().__init__(title, *args, **kwargs)

        photo_path = get_photo_path("thermometer-snow.png")
        photo = ttkbootstrap.PhotoImage(file=photo_path)
        self.wm_iconphoto(False, photo)

        enable_high_dpi_awareness(self, HIGH_DPI_SCALING)

        self.main_frame = TemperatureControllerGraphics(self, device)

        if want_default_geometry:
            self._set_default_geometry()

    def _set_default_geometry(self):
        width = DEFAULT_TEMPERATURE_CONTROLLER_WIDTH
        height = DEFAULT_TEMPERATURE_CONTROLLER_HEIGHT

        s_width = self.winfo_screenwidth()
        s_height = self.winfo_screenheight()
        self.update()

        displacement_x = int(s_width / 2 - width / 2)
        displacement_y = int(s_height / 2 - 3 * height / 5)

        self.update_idletasks()
        self.geometry(f'{width}x{height}+{displacement_x}+{displacement_y}')

    def destroy(self):
        # TODO: update with notification if program stops working
        print('Notify users that Temperature Controller pop-up is off')
        super().destroy()


if __name__ == "__main__":
    # TODO: Put in a try except statement and notify user if something is wrong?
    myappid = "QDL.CryostatMonitor.TemperatureController.1"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = TemperatureControllerWindow()
    app.mainloop()

