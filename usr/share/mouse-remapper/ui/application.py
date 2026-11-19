from gi.repository import Adw, Gio, Gtk

from core import APP_ID, APP_NAME, updater
from core.i18n import _
from .window import MainWindow


class MouseRemapperApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.connect("activate", self._on_activate)

        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_args: self.props.active_window and self.props.active_window.close())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _on_activate(self, _app):
        win = self.props.active_window or MainWindow(application=self)
        win.present()

    def _on_about(self, *_args):
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=updater.display_version(updater.installed_version()),
            developer_name="narayanls",
            comments=_("Create keyboard macros on your mouse buttons."),
            license_type=Gtk.License.GPL_3_0,
        )
        dialog.present(self.props.active_window)
