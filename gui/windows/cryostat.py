import ctypes
import datetime
import threading
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas
import pandas as pd
import ttkbootstrap
from functools import partial
from matplotlib import pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from slack_sdk.models.blocks import HeaderBlock, SectionBlock, PlainTextObject
from ttkbootstrap.scrolled import ScrolledFrame
from ttkbootstrap.tableview import Tableview
from ttkbootstrap.utility import enable_high_dpi_awareness

from devices import TemperatureController
from gui.constants import DEFAULT_WINDOW_STYLE_THEME, DEFAULT_WIDGET_PADX, DEFAULT_WIDGET_PADY, DEFAULT_INTERVAL, \
    DynamicDateConstants, PLOTTABLE_PARAMETERS, DATE_ENTRY_FORMAT, \
    NEXT_LOG_DATETIME_FORMAT, PLOT_DATETIME_FORMAT, DEFAULT_CRYOSTAT_MONITOR_WIDTH, DEFAULT_CRYOSTAT_MONITOR_HEIGHT, \
    TABLE_DATETIME_FORMAT, HIGH_DPI_SCALING
from gui.utils import CustomNavigationToolbar, Spinbox, DateSuperWidget, CheckBox, get_dates, pd_concat, \
    get_plot_datetime_format, get_photo_path
from monitor.checks import ColdHeadLimits, PressureLimits
from monitor.communication import send_slack_message_via_webhook
from monitor.constants import DATA_FILENAME_FORMAT, DATA_STORAGE_FOLDER, FILE_TIMESTAMP_FORMAT
from monitor.measurement import MEASUREMENT_HEADER_MAP, Measurement
from monitor.utils import perform_dummy_logging_processes, get_new_device_instances, perform_real_logging_processes


# plt.switch_backend('agg')


class CryostatMonitorGraphics(ttkbootstrap.Frame):
    def __init__(self, parent):
        self. _configure_device_instances()
        parent.title("Cryostat Monitor" if self._devices else "DUMMY Cryostat Monitor")
        super().__init__(parent)

        self.style = ttkbootstrap.Style(DEFAULT_WINDOW_STYLE_THEME)
        if self.style.theme.type == 'dark':
            plt.style.use('dark_background')

        self.stop_collection_event: threading.Event | None = None  # changes in every thread
        self.measurement_is_active_event: threading.Event = threading.Event()  # same over all threads
        self.dates: list[datetime.date] = []
        self.plottable_data: pd.DataFrame = pd.DataFrame(columns=list(MEASUREMENT_HEADER_MAP.values()))

        self._create_widgets()
        self.load_archive_data()
        self.update_plot()
        self._initialize_table()

        self._set_default_geometry()

    def _configure_device_instances(self):
        devices = get_new_device_instances()
        if all([device is None for device in devices]):
            devices = None

        self._devices = devices

    def perform_logging_process(self, folder: str):
        if self._devices:
            return perform_real_logging_processes(*self._devices, folder=folder)
        else:
            return perform_dummy_logging_processes(folder)

    def _set_default_geometry(self):
        width = DEFAULT_CRYOSTAT_MONITOR_WIDTH
        height = DEFAULT_CRYOSTAT_MONITOR_HEIGHT

        self.configure(width=width, height=height)

    def _create_widgets(self):
        self._create_pane_windows()
        self._create_table_visualization_frame()
        self._create_user_input_frame()
        self._create_plot_visualization_frame()
        self._put_panes_together()

    def _create_pane_windows(self):
        self.vertical_pane = ttkbootstrap.Frame(self.master)
        self.horizontal_pane = ttkbootstrap.Frame(self.vertical_pane)

    def _put_panes_together(self):
        ttkbootstrap.Separator(self.vertical_pane).pack(fill='both', expand=False)

        # self.horizontal_pane.add(self.user_input_frame)
        # self.horizontal_pane.add(self.plot_visualization_frame)
        self.horizontal_pane.pack(fill='both', expand=True)

        # self.vertical_pane.add(self.table_visualization_frame)
        # self.vertical_pane.add(self.horizontal_pane)
        self.vertical_pane.pack(fill='both', expand=True)

    def _create_user_input_frame(self):
        self.user_input_frame = ScrolledFrame(self.horizontal_pane, autohide=False)
        self.user_input_frame.pack(fill='both', expand=False, side='left',
                                   padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)
        self._user_input_frame_row_count = 0
        self._create_data_collection_widgets()
        self._create_data_selection_visualization_widgets()

        self.user_input_frame.container.update()
        req_width = self.user_input_frame.winfo_reqwidth()
        req_width += self.user_input_frame.vscroll.winfo_reqwidth()
        self.user_input_frame.container.configure(width=req_width)

    def _create_table_visualization_frame(self):
        self.table_visualization_frame = ttkbootstrap.Frame(self.vertical_pane)
        self.table_visualization_frame.pack(fill='both', expand=False)

        self.table_view = Tableview(
            self.table_visualization_frame,
            coldata=list(MEASUREMENT_HEADER_MAP.values()),
            rowdata=[],
            # autofit=True,
            paginated=True,
            pagesize=5,
            autoalign=True,
            height=5,
        )
        # self.table_view.view.pack_configure(side='bottom')
        self.table_view.pack(fill='both', expand=True, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

    def _create_plot_visualization_frame(self):
        self.plot_visualization_frame = ttkbootstrap.Frame(self.horizontal_pane)
        self.plot_visualization_frame.pack(fill='both', expand=True)

        self.figure = plt.Figure(figsize=(5, 3), layout='constrained', facecolor=self.style.colors.bg)

        self.canvas = FigureCanvasTkAgg(self.figure, master=self.plot_visualization_frame)

        CustomNavigationToolbar(self.canvas, self.plot_visualization_frame, pack_toolbar=False).pack(
            fill='both', expand=False, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)
        self.canvas.get_tk_widget().pack(fill='both', expand=True, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

    def _create_data_collection_widgets(self):

        rc = self._user_input_frame_row_count

        # ---------------- Interval ----------------
        ttkbootstrap.Label(self.user_input_frame, text="Interval (seconds):").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY, sticky='w')

        interval_values = [1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50, 60, 90, 120, 150, 180, 240, 300]

        self.interval_entry = Spinbox(self.user_input_frame, DEFAULT_INTERVAL, interval_values, width=12)
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
        # ---------------- utilities ----------------
        self.force_ch_heater_to_medium_button = CheckBox(
            self.user_input_frame, text="Force CH heater range to medium", bootstyle='square-toggle')
        self.force_ch_heater_to_medium_button.grid(row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY,
                                                   columnspan=2, sticky='ns')
        self.force_ch_heater_to_medium_button.value.set(True)
        # self.force_ch_heater_to_medium_button.value.trace_add('write', self._some_function)

        self._user_input_frame_row_count = rc + 1

    def _create_data_selection_visualization_widgets(self):

        rc = self._user_input_frame_row_count

        # ---------------- Start date and time ----------------
        ttkbootstrap.Label(self.user_input_frame, text="Start date:").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY+10, sticky='nw')

        self.start_date_entry = DateSuperWidget(self.user_input_frame,
                                                startdate=DynamicDateConstants.default_start_date,
                                                checkboxtext="Set to yesterday", command=self._on_date_entry_update)
        self.start_date_entry.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc += 1

        # ---------------- End date and time ----------------
        ttkbootstrap.Label(self.user_input_frame, text="End date:").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY+10, sticky='nw')

        self.end_date_entry = DateSuperWidget(self.user_input_frame,
                                              startdate=DynamicDateConstants.default_end_date,
                                              checkboxtext="Set to today", command=self._on_date_entry_update)
        self.end_date_entry.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc += 1

        # ---------------- Parameter 1 ----------------
        ttkbootstrap.Label(self.user_input_frame, text="Plot variable (left):").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY+10, sticky='nw')

        self.param_combo1 = ttkbootstrap.Combobox(
            self.user_input_frame, values=PLOTTABLE_PARAMETERS, state='readonly', width=13)
        self.param_combo1.current(1)
        self.param_combo1.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)
        self.param_combo1.bind("<<ComboboxSelected>>", self.update_plot)

        rc += 1

        # ---------------- Parameter 2 ----------------
        ttkbootstrap.Label(self.user_input_frame, text="Plot variable (right):").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY + 10, sticky='nw')

        self.param_combo2 = ttkbootstrap.Combobox(
            self.user_input_frame, values=PLOTTABLE_PARAMETERS, state='readonly', width=13)
        self.param_combo2.current(0)
        self.param_combo2.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        self.param_combo2.bind("<<ComboboxSelected>>", self.update_plot)

        rc += 1

        # ---------------- Set Point Checkbox ----------------
        ttkbootstrap.Label(self.user_input_frame, text="With 'CH Temp' plot:").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY + 10, sticky='nw')

        self.set_point_checkbox = CheckBox(
            master=self.user_input_frame, text="Show Set Point", command=self.update_plot)
        self.set_point_checkbox.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc += 1

        # ---------------- Timestap Limits ----------------
        ttkbootstrap.Label(self.user_input_frame, text="Plot x-axis span (hours):").grid(
            row=rc, column=0, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY, sticky='w')

        span_values = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 10, 12, 15, 18, 20, 24, 30, 36, 48, 60]
        self.x_axis_span = Spinbox(self.user_input_frame, 24, span_values,
                                   width=12, state='disabled', post_validation_command=self.update_plot)
        self.x_axis_span.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

        rc += 1

        self.x_axis_span_checkbox = CheckBox(
            master=self.user_input_frame, text="All available", command=self._on_axis_span_checkbox_update)
        self.x_axis_span_checkbox.grid(row=rc, column=1, padx=DEFAULT_WIDGET_PADX, pady=DEFAULT_WIDGET_PADY)

    def get_temperature_controller_device(self) -> TemperatureController | None:
        device = None
        if self._devices:
            for dev in self._devices:
                if isinstance(dev, TemperatureController):
                    device = dev
                    break
        return device

    def _on_axis_span_checkbox_update(self):
        if self.x_axis_span_checkbox.value.get():
            self.x_axis_span.config(state="disabled")
        else:
            self.x_axis_span.config(state="normal")

        self.update_plot()

    def _on_date_entry_update(self):
        is_loaded = self.load_archive_data()
        if is_loaded:
            self._initialize_table()
            self.update_plot()

    def get_start_date(self):
        if self.start_date_entry.check_box.value.get():
            return DynamicDateConstants.default_start_date.strftime(DATE_ENTRY_FORMAT)
        else:
            return self.start_date_entry.get_date_str()

    def get_end_date(self):
        if self.end_date_entry.check_box.value.get():
            return DynamicDateConstants.default_end_date.strftime(DATE_ENTRY_FORMAT)
        else:
            return self.end_date_entry.get_date_str()

    @property
    def interval(self) -> float:
        return self.interval_entry.last_valid_value

    def load_archive_data(self) -> bool:
        dates = get_dates(self.get_start_date(), self.get_end_date(), fmt=DATE_ENTRY_FORMAT)
        if self.dates == dates and self.dates != []:
            return False

        all_data = pd.DataFrame(columns=list(MEASUREMENT_HEADER_MAP.values()))
        for date in dates:
            filename = date.strftime(DATA_FILENAME_FORMAT)
            file_path = Path(DATA_STORAGE_FOLDER).joinpath(filename)
            if file_path.is_file():
                data = pd.read_csv(str(file_path))
                data['Timestamp'] = file_path.stem + data['Timestamp']
                all_data = pd_concat([all_data, data])

        all_data['Timestamp'] = pd.to_datetime(
            all_data['Timestamp'], format=Path(DATA_FILENAME_FORMAT).stem + FILE_TIMESTAMP_FORMAT).astype('datetime64[us]')

        self.plottable_data = all_data
        self.dates = dates

        return True

    def collect_data(self, stop_event: threading.Event):
        counter = 0
        while not stop_event.is_set():
            counter += 1
            try:
                self.collection_status_label.config(text=f'Measuring...')
                self.measurement_is_active_event.set()
                start_time = time.time()
                measurement = self.perform_logging_process(DATA_STORAGE_FOLDER)
                self.measurement_is_active_event.clear()
                self.collection_status_label.config(text=f'Updating GUI...')
                self.append_collected_datum(measurement)
                self.check_cold_head_heater_range_after_measurement(measurement)
                self.check_date_change_during_collection()
            except Exception as e:
                print("Error while collecting data:", e)
            self.update_visualizations()
            self.segmented_collection_sleep(start_time, stop_event, 0.5)
        self.collection_status_label.config(text="Idle")
        self.start_collection_button.config(state="normal")

    def append_collected_datum(self, measurement: Measurement):
        new_data = pd.DataFrame(asdict(measurement), index=[0])
        new_data.rename(columns=MEASUREMENT_HEADER_MAP, inplace=True)
        self.plottable_data = pd_concat([self.plottable_data, new_data])

    def check_date_change_during_collection(self):
        if len(self.plottable_data['Timestamp']) < 2:
            return
        date_before: pandas.Timestamp = self.plottable_data.iloc[-2]['Timestamp']
        date_after: pandas.Timestamp = self.plottable_data.iloc[-1]['Timestamp']
        if date_before.day != date_after.day:
            self.start_date_entry.set_to_next_day()
            self.end_date_entry.set_to_next_day()
            self.load_archive_data()

    def check_cold_head_heater_range_after_measurement(self, measurement: Measurement):
        if not self.force_ch_heater_to_medium_button.value.get():
            return
        if not (measurement.cold_head_heater_percentage == 0.0 or measurement.cold_head_heater_percentage > 85.):
            return
        if not (measurement.cold_head_temperature < ColdHeadLimits.HIGH_TEMPERATURE):
            return

        temperature_controller = self.get_temperature_controller_device()
        with temperature_controller._lock:
            temperature_controller.connect()
            ch_hr = temperature_controller.get_cold_head_heater_range()
            if ch_hr != "Medium":
                temperature_controller.set_cold_head_heater_range("Medium")
                block_subject = HeaderBlock(text='Note')
                block_message = SectionBlock(text=PlainTextObject(
                    text=f"Cold Head heater range was wrongly set to '{ch_hr}'. "
                         f"Heater was set back to 'Medium'."))
                blocks = [block_subject, block_message]
                send_slack_message_via_webhook(blocks=blocks)
            temperature_controller.disconnect()

    def _initialize_table(self):
        self.table_view.delete_rows()
        df = self.plottable_data.iloc[::-1].copy(deep=True)
        df['Timestamp'] = df['Timestamp'].dt.strftime(TABLE_DATETIME_FORMAT)
        values = df.to_records(index=False).tolist()
        self.table_view.insert_rows(0, values)
        self.table_view.load_table_data()
        self.table_view.autofit_columns()

    def update_visualizations(self):
        self.update_table()
        self.update_plot()

    def update_table(self):
        values = list(self.plottable_data.iloc[-1])
        values[0] = values[0].strftime(TABLE_DATETIME_FORMAT)
        self.table_view.insert_row(0, values)
        self.table_view.load_table_data()

    def update_plot(self, event=None):
        self.figure.clear()

        param1 = self.param_combo1.get()
        param2 = self.param_combo2.get()

        ax1: plt.Axes = self.figure.add_subplot(111)
        ax1.set_facecolor(self.style.colors.bg)
        ax2: plt.Axes = ax1.twinx()

        # get x limits from user input if necessary
        if not self.x_axis_span_checkbox.value.get():
            x_lim_mask = (self.plottable_data['Timestamp'] >
                          self.plottable_data['Timestamp'].iloc[-1] -
                          datetime.timedelta(hours=self.x_axis_span.last_valid_value))
            x_lim_mask = x_lim_mask.to_numpy()
        else:
            x_lim_mask = [True] * len(self.plottable_data['Timestamp'])

        x_data = self.plottable_data['Timestamp'].to_numpy()[x_lim_mask]
        if len(x_data) < 2:
            return

        def plot_param(param, axis, color, axis_side):
            if param != "None":
                y_data = self.plottable_data[param].to_numpy(dtype=np.float_)[x_lim_mask]
                valid_indices = np.isfinite(y_data)
                filtered_x_data = x_data[valid_indices]
                filtered_y_data = y_data[valid_indices]

                if len(filtered_y_data) > 0:
                    axis.plot(filtered_x_data, filtered_y_data, color=color, alpha=0.75)
                    axis.set_ylabel(param)
                    ax1.spines[axis_side].set_color(color)
                    ax2.spines[axis_side].set_color(color)

                    if param == 'CH Temp (K)' and self.set_point_checkbox.value.get():
                        axis.plot(x_data, self.plottable_data['CH Set Point (K)'].to_numpy()[x_lim_mask],
                                  color=self.style.colors.warning, alpha=0.5, linestyle='--')

        plot_param(param1, ax1, self.style.colors.info, 'left')
        plot_param(param2, ax2, self.style.colors.danger, 'right')

        # ax2.get_yaxis().set_visible(False)

        ax1.set_xlabel("Time")
        ax1.tick_params(axis='x', rotation=15)
        x_min, x_max = ax1.get_xlim()
        # if not self.x_axis_span_checkbox.value.get():
        #     x_min = max(x_min, x_max - self.x_axis_span.last_valid_value/24)
        #     ax1.set_xlim(x_min, x_max)
        #
        datetime_fmt = get_plot_datetime_format(
            datetime.datetime.fromtimestamp(x_min * 24 * 3600),
            datetime.datetime.fromtimestamp(x_max * 24 * 3600),
            PLOT_DATETIME_FORMAT
        )
        
        ax1.xaxis.set_major_formatter(mdates.DateFormatter(datetime_fmt))

        ax1.patch.set_alpha(int(param1 != "None"))  # Set subplot transparency to 0
        ax1.yaxis.set_visible(param1 != "None")  # Hide y-axis ticks and labels
        ax1.spines["left"].set_visible(param1 != "None")  # Hide left spine
        ax2.patch.set_alpha(int(param2 != "None"))  # Set subplot transparency to 0
        ax2.yaxis.set_visible(param2 != "None")  # Hide y-axis ticks and labels
        ax2.spines["right"].set_visible(param2 != "None")  # Hide right spine

        # self.figure.canvas.draw()
        self.figure.canvas.draw_idle()
        self.canvas.draw()  # Update the canvas to display the plot

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
        if self.measurement_is_active_event.is_set():  # not necessary, but just in case
            self.collection_status_label.config(text="Cannot start while previous thread is running...")
            return

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
        if self.measurement_is_active_event.is_set():
            self.collection_status_label.config(text="Stopping after measurement is completed...")
        self.stop_collection_button.config(state="disabled")
        # start button is enabled only when data collection is finished!

    def destroy(self):
        if self.stop_collection_event:
            self.stop_collection_event.set()
            # sleep_time = 0.5
            # if self.measurement_is_active_event.is_set():
            #     sleep_time += 3
            # time.sleep(sleep_time)  # wait for the collection thread to close
        super().destroy()


class CryostatMonitorWindow(ttkbootstrap.Window):
    def __init__(self, want_default_geometry=True, title='Cryostat Monitor', *args, **kwargs):
        super().__init__(title=title, *args, **kwargs)

        # self.iconbitmap("../graphics/CryostatMonitor.ico")

        photo_path = get_photo_path("Cryostat.png")
        photo = ttkbootstrap.PhotoImage(file=photo_path)

        self.wm_iconphoto(False, photo)

        enable_high_dpi_awareness(self, HIGH_DPI_SCALING)

        self.main_frame = CryostatMonitorGraphics(self)

        if want_default_geometry:
            self._set_default_geometry()

    def _set_default_geometry(self):
        width = DEFAULT_CRYOSTAT_MONITOR_WIDTH
        height = DEFAULT_CRYOSTAT_MONITOR_HEIGHT

        s_width = self.winfo_screenwidth()
        s_height = self.winfo_screenheight()

        displacement_x = int(s_width / 2 - width / 2)
        displacement_y = int(s_height / 2 - 3 * height / 5)

        self.update_idletasks()
        self.geometry(f'{width}x{height}+{displacement_x}+{displacement_y}')

    def destroy(self):
        # TODO: update with notification if program stops working
        print('Notify users that Cryostat Monitor Window is off')
        super().destroy()


if __name__ == "__main__":
    # TODO: Put in a try except statement and notify user if something is wrong?
    myappid = "QDL.CryostatMonitor.CryostatMonitor.1"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = CryostatMonitorWindow()
    app.mainloop()

