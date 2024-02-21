import ctypes
import ttkbootstrap

from gui.windows.cryostat import CryostatMonitorWindow
from gui.windows.temperature_controller import TemperatureControllerTopLevel


class Application(CryostatMonitorWindow):
    def __init__(self, want_default_geometry=True, *args, **kwargs):

        super().__init__(False, *args, **kwargs)
        self._create_menu()
        self.temperature_controller_top_level: TemperatureControllerTopLevel | None = None

        if want_default_geometry:
            self._set_default_geometry()

    def _create_menu(self):
        menubar = ttkbootstrap.Menu(self)

        window_menu = ttkbootstrap.Menu(menubar, tearoff=False)
        window_menu.add_command(label="Open Temperature Controller", command=self.open_temperature_controller)
        menubar.add_cascade(label="Other applications", menu=window_menu)

        self.config(menu=menubar)

    def open_temperature_controller(self):
        if self.temperature_controller_top_level is None:
            device = self.main_frame.get_temperature_controller_device()
            self.temperature_controller_top_level = TemperatureControllerTopLevel(device=device)
            self.temperature_controller_top_level.bind('<Destroy>', self._on_temperature_controller_top_level_destroy)
        else:
            self.temperature_controller_top_level.focus_set()

    def _on_temperature_controller_top_level_destroy(self, *_):
        self.temperature_controller_top_level = None

    def destroy(self):
        if self.temperature_controller_top_level is not None:
            self.temperature_controller_top_level.destroy()
        # TODO: update with notification if program stops working
        print('Notify users that the application is off')
        super().destroy()


if __name__ == "__main__":
    # TODO: Put in a try except statement and notify user if something is wrong?
    myappid = "QDL.CryostatMonitor.CryostatMonitorMain.1"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    
    app = Application()
    # monitor = CryostatMonitorGraphics(app)
    app.mainloop()
