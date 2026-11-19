import copy
import threading
from dataclasses import dataclass, field

from evdev import ecodes
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from core import APP_NAME, config, devices, keys, service
from core.i18n import _, ngettext
from core.detect import ButtonDetector
from core.engine import Remapper
from . import labels

CSS = b"""
.editor-card { padding: 18px; }
.editor-value { font-size: 1.35em; font-weight: 700; }
.editor-value.empty { opacity: 0.45; font-weight: 400; }
.recording { animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.6; } }
"""


@dataclass
class DeviceEntry:
    key: str
    name: str
    paths: list = field(default_factory=list)
    connected: bool = True


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(860, 780)

        self.cfg = config.load()
        # Cópia de trabalho: {chave: [mapeamentos]}
        self.mappings = {k: copy.deepcopy(d["mappings"]) for k, d in self.cfg["devices"].items()}
        self.device_entries: list[DeviceEntry] = []
        self.current: DeviceEntry | None = None
        self.dirty = False

        # Estado do editor
        self.editor_steps: list[list[int]] = []
        self.editor_button: int | None = None

        # Gravação de teclas
        self.recording = False
        self._rec_combo: list[int] = []
        self._rec_held: set[int] = set()

        # Detecção / teste
        self.detector: ButtonDetector | None = None
        self.test_engine: Remapper | None = None
        self.test_thread: threading.Thread | None = None
        self._recv_held: set[int] = set()
        self._recv_combo: list[int] = []

        # Pausa do serviço em segundo plano (ele "prende" o mouse)
        self._pause_count = 0
        self._service_was_active = False

        self._updating = False
        self._force_close = False

        self._load_css()
        self._build_ui()
        self._setup_actions()
        self.refresh_devices()
        self.check_permissions()
        self._update_service_status()
        self._update_editor()

        self.connect("close-request", self._on_close_request)

    # ================================================================ UI
    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _build_ui(self):
        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title=APP_NAME)
        header.set_title_widget(self.title_widget)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic",
                                 tooltip_text=_("Scan for mice again"))
        refresh_btn.set_action_name("win.refresh")
        header.pack_start(refresh_btn)

        menu = Gio.Menu()
        menu.append(_("Scan for mice again"), "win.refresh")
        menu.append(_("Disable background service"), "win.disable-service")
        menu.append(_("About {app}").format(app=APP_NAME), "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text=_("Main menu")))
        toolbar.add_top_bar(header)

        self.banner = Adw.Banner(button_label=_("Copy command"))
        self.banner.connect("button-clicked", self._on_banner_copy)
        toolbar.add_top_bar(self.banner)

        self.toast_overlay = Adw.ToastOverlay()
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=900, tightening_threshold=600)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                          margin_top=24, margin_bottom=24, margin_start=18, margin_end=18)
        clamp.set_child(content)
        scrolled.set_child(clamp)
        self.toast_overlay.set_child(scrolled)
        toolbar.set_content(self.toast_overlay)

        # --- Dispositivo
        dev_group = Adw.PreferencesGroup(title=_("Device"))
        self.device_row = Adw.ComboRow(title=_("Mouse"))
        self.device_row.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))
        self.device_row.connect("notify::selected", self._on_device_changed)
        dev_group.add(self.device_row)
        content.append(dev_group)

        # --- Editor
        editor_group = Adw.PreferencesGroup(
            title=_("New macro"),
            description=_("Choose the keys on one side and the mouse button on the other."))
        editor = Gtk.Box(spacing=12)
        size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        keys_card = self._build_keys_card()
        mouse_card = self._build_mouse_card()
        size_group.add_widget(keys_card)
        size_group.add_widget(mouse_card)

        arrow = Gtk.Image.new_from_icon_name("go-previous-symbolic")
        arrow.set_pixel_size(28)
        arrow.set_valign(Gtk.Align.CENTER)
        arrow.add_css_class("dim-label")
        arrow.set_tooltip_text(_("The mouse button sends these keys"))

        editor.append(keys_card)
        editor.append(arrow)
        editor.append(mouse_card)
        editor_group.add(editor)

        self.add_btn = Gtk.Button(label=_("Add mapping"), halign=Gtk.Align.CENTER,
                                  margin_top=12)
        self.add_btn.add_css_class("pill")
        self.add_btn.add_css_class("suggested-action")
        self.add_btn.connect("clicked", self._on_add_mapping)
        editor_group.add(self.add_btn)
        content.append(editor_group)

        # --- Lista de mapeamentos
        self.maps_group = Adw.PreferencesGroup(title=_("Mappings for this mouse"))
        self.maps_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.maps_list.add_css_class("boxed-list")
        placeholder = Gtk.Label(label=_("No mappings yet."), margin_top=18, margin_bottom=18)
        placeholder.add_css_class("dim-label")
        self.maps_list.set_placeholder(placeholder)
        self.maps_group.add(self.maps_list)
        content.append(self.maps_group)

        # --- Área de teste
        test_group = Adw.PreferencesGroup(
            title=_("Testing"),
            description=_("You don't need to save to test. The test uses the macro in the "
                          "editor and the ones in the list; then click “Save” to keep them "
                          "always active."))
        test_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.test_entry = Gtk.Entry(placeholder_text=_("Test area — the resulting keys appear here"))
        self.received_label = Gtk.Label(label=_("Keys received: —"), xalign=0)
        self.received_label.add_css_class("dim-label")
        self.test_status = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.test_status.add_css_class("success")
        self.test_btn = Gtk.ToggleButton(label=_("Test"), halign=Gtk.Align.START)
        self.test_btn.add_css_class("pill")
        self.test_btn.set_tooltip_text(_("Turns the macros on temporarily, without saving"))
        self.test_btn.connect("toggled", self._on_test_toggled)
        test_box.append(self.test_btn)
        test_box.append(self.test_status)
        test_box.append(self.test_entry)
        test_box.append(self.received_label)
        test_group.add(test_box)
        content.append(test_group)

        # --- Barra inferior
        action_bar = Gtk.ActionBar()
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.add_css_class("dim-label")
        action_bar.pack_start(self.status_label)

        self.save_btn = Gtk.Button(label=_("Save"))
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.set_tooltip_text(_("Saves and keeps the macros active after restarting the computer"))
        self.save_btn.connect("clicked", lambda *_args: self.save())
        action_bar.pack_end(self.save_btn)

        toolbar.add_bottom_bar(action_bar)

        self.set_content(toolbar)

        # Captura de teclado (gravação e exibição no teste)
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        key_ctrl.connect("key-released", self._on_key_released)
        self.add_controller(key_ctrl)

    def _card(self, title: str, icon: str) -> tuple[Gtk.Box, Gtk.Box]:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True)
        card.add_css_class("card")
        card.add_css_class("editor-card")
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Image.new_from_icon_name(icon))
        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class("heading")
        head.append(lbl)
        card.append(head)
        return card, head

    def _value_label(self) -> Gtk.Label:
        lbl = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, height_request=64,
                        valign=Gtk.Align.CENTER, vexpand=True, width_chars=14,
                        max_width_chars=28)
        lbl.add_css_class("editor-value")
        return lbl

    def _build_keys_card(self) -> Gtk.Box:
        card, _head = self._card(_("Keyboard keys"), "input-keyboard-symbolic")

        self.keys_label = self._value_label()
        card.append(self.keys_label)

        row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.record_btn = Gtk.Button(label=_("Record keys"))
        self.record_btn.add_css_class("pill")
        self.record_btn.connect("clicked", self._on_record_clicked)
        clear_btn = Gtk.Button(icon_name="edit-clear-symbolic", tooltip_text=_("Clear keys"))
        clear_btn.add_css_class("circular")
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", self._on_clear_keys)
        row.append(self.record_btn)
        row.append(clear_btn)
        card.append(row)

        hint = Gtk.Label(label=_("Click Record and press the combination (e.g. Ctrl + C)."),
                         wrap=True, justify=Gtk.Justification.CENTER)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        card.append(hint)

        self.sequence_check = Gtk.CheckButton(
            label=_("Sequence: each recording adds a step"))
        self.sequence_check.set_tooltip_text(
            _("E.g. Ctrl + C  →  Alt + Tab  →  Ctrl + V, sent in order on click"))
        card.append(self.sequence_check)

        expander = Gtk.Expander(label=_("Pick a key from the list"))
        exp_box = Gtk.Box(spacing=6, margin_top=6)
        self.key_codes = keys.selectable_key_codes()
        key_model = Gtk.StringList.new([f"{labels.key_label(c)}" for c in self.key_codes])
        self.key_dropdown = Gtk.DropDown(model=key_model, hexpand=True, enable_search=True)
        self.key_dropdown.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        add_key_btn = Gtk.Button(icon_name="list-add-symbolic",
                                 tooltip_text=_("Add to combination"))
        add_key_btn.connect("clicked", self._on_add_key_from_list)
        exp_box.append(self.key_dropdown)
        exp_box.append(add_key_btn)
        expander.set_child(exp_box)
        expander.set_tooltip_text(_("Useful for keys the system intercepts, such as Super"))
        card.append(expander)
        return card

    def _build_mouse_card(self) -> Gtk.Box:
        card, _head = self._card(_("Mouse button"), "input-mouse-symbolic")

        self.button_label = self._value_label()
        card.append(self.button_label)

        self.detect_btn = Gtk.Button(label=_("Detect button"), halign=Gtk.Align.CENTER)
        self.detect_btn.add_css_class("pill")
        self.detect_btn.connect("clicked", self._on_detect_clicked)
        card.append(self.detect_btn)

        hint = Gtk.Label(label=_("Click Detect and press the button on the mouse."),
                         wrap=True, justify=Gtk.Justification.CENTER)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        card.append(hint)

        names = [_("Or pick from the list…")] + [keys.button_label(b) for b in keys.COMMON_BUTTONS]
        self.button_dropdown = Gtk.DropDown(model=Gtk.StringList.new(names))
        self.button_dropdown.connect("notify::selected", self._on_button_dropdown)
        card.append(self.button_dropdown)
        return card

    def _setup_actions(self):
        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *_args: (self.refresh_devices(), self.check_permissions()))
        self.add_action(refresh)

        disable = Gio.SimpleAction.new("disable-service", None)
        disable.connect("activate", self._on_disable_service)
        self.add_action(disable)

    # ============================================================ helpers
    def toast(self, msg: str, timeout: int = 3):
        t = Adw.Toast.new(msg)
        t.set_timeout(timeout)
        self.toast_overlay.add_toast(t)

    def _set_dirty(self, value: bool = True):
        self.dirty = value
        self.status_label.set_label(_("Unsaved changes") if value else "")

    def _current_maps(self) -> list:
        if not self.current:
            return []
        return self.mappings.setdefault(self.current.key, [])

    def _update_service_status(self):
        if self._pause_count:
            text = _("Service paused during test/detection")
        elif service.is_active():
            text = _("Macros active in the background")
        else:
            text = _("Background service inactive")
        self.title_widget.set_subtitle(text)

    def _pause_service(self):
        if self._pause_count == 0:
            self._service_was_active = service.is_active()
            if self._service_was_active:
                service.stop()
        self._pause_count += 1
        self._update_service_status()

    def _resume_service(self):
        if self._pause_count == 0:
            return
        self._pause_count -= 1
        if self._pause_count == 0 and self._service_was_active:
            service.start()
            self._service_was_active = False
        self._update_service_status()

    # ========================================================== permissões
    def check_permissions(self):
        problems = devices.permission_problems()
        self._banner_cmd = ""
        self.banner.set_button_label(_("Copy command"))
        if "input-reboot" in problems:
            self.banner.set_title(_("Permission granted! Restart the computer so "
                                    "Mouse Remapper can access the mouse."))
            self.banner.set_button_label("")  # nada a copiar
        elif "input" in problems:
            self.banner.set_title(
                _("No permission to read the mouse. Run the command below and then RESTART "
                  "the computer (closing the app is not enough): {command}").format(
                    command="sudo usermod -aG input $USER"))
            self._banner_cmd = "sudo usermod -aG input $USER"
        elif "uinput-missing" in problems:
            self.banner.set_title(_("The uinput module is not loaded. Run: {command}").format(
                command="sudo modprobe uinput"))
            self._banner_cmd = "sudo modprobe uinput"
        elif "uinput" in problems:
            self.banner.set_title(
                _("No permission on /dev/uinput. Reinstall the package or run: {command}").format(
                    command="sudo udevadm trigger --sysname-match=uinput"))
            self._banner_cmd = "sudo udevadm control --reload && sudo udevadm trigger --sysname-match=uinput"
        self.banner.set_revealed(bool(problems))

    def _on_banner_copy(self, _banner):
        if self._banner_cmd:
            self.get_clipboard().set(self._banner_cmd)
            if "usermod" in self._banner_cmd:
                self.toast(_("Command copied. Run it in the terminal and restart the computer."), 8)
            else:
                self.toast(_("Command copied"))
            # Reavalia em seguida: após o usermod, a faixa passa a pedir o reinício.
            GLib.timeout_add_seconds(5, self._recheck_permissions)

    def _recheck_permissions(self):
        self.check_permissions()
        return self.banner.get_revealed() and "usermod" in self._banner_cmd

    # ========================================================= dispositivos
    def refresh_devices(self):
        prev_key = self.current.key if self.current else None
        entries = [DeviceEntry(g.key, g.name, g.paths, True) for g in devices.list_mice()]
        known = {e.key for e in entries}
        for key in set(self.mappings) | set(self.cfg["devices"]):
            if key in known or not (self.mappings.get(key)):
                continue
            name = self.cfg["devices"].get(key, {}).get("name", key)
            entries.append(DeviceEntry(key, name, [], False))
        self.device_entries = entries

        names = [e.name if e.connected else _("{name} (disconnected)").format(name=e.name) for e in entries]
        self._updating = True
        self.device_row.set_model(Gtk.StringList.new(names))
        index = 0
        for i, e in enumerate(entries):
            if e.key == prev_key:
                index = i
                break
        else:
            for i, e in enumerate(entries):  # prefere um mouse conectado já configurado
                if e.connected and self.mappings.get(e.key):
                    index = i
                    break
        if entries:
            self.device_row.set_selected(index)
        self._updating = False

        if entries:
            self.device_row.set_subtitle("")
        else:
            self.device_row.set_subtitle(_("No mouse found"))
        self._on_device_changed()

    def _on_device_changed(self, *_args):
        if self._updating:
            return
        idx = self.device_row.get_selected()
        new = self.device_entries[idx] if 0 <= idx < len(self.device_entries) else None
        if self.current and new and new.key != self.current.key and self.test_btn.get_active():
            self.test_btn.set_active(False)
        self.current = new
        if new:
            self.device_row.set_subtitle(f"ID {new.key}" if new.connected else _("Disconnected"))
        self._rebuild_list()
        self._update_editor()

    # ============================================================== editor
    def _update_editor(self):
        if self.recording:
            text = labels.combo_text(keys.sort_combo(self._rec_combo)) if self._rec_combo else "…"
            if self.sequence_check.get_active() and self.editor_steps:
                text = labels.steps_text(self.editor_steps) + "  →  " + text
            self._set_value(self.keys_label, text, False)
        elif self.editor_steps:
            self._set_value(self.keys_label, labels.steps_text(self.editor_steps), False)
        else:
            self._set_value(self.keys_label, _("No keys"), True)

        if self.editor_button is None:
            self._set_value(self.button_label, _("No button"), True)
        else:
            self._set_value(self.button_label, keys.button_label(self.editor_button), False)

        exists = any(m["button"] == self.editor_button for m in self._current_maps())
        self.add_btn.set_label(_("Update mapping") if exists else _("Add mapping"))
        self.add_btn.set_sensitive(bool(self.current and self.editor_steps
                                        and self.editor_button is not None))
        self.detect_btn.set_sensitive(bool(self.current and self.current.connected))

    @staticmethod
    def _set_value(label: Gtk.Label, text: str, empty: bool):
        label.set_label(text)
        if empty:
            label.add_css_class("empty")
        else:
            label.remove_css_class("empty")

    # -- gravação de teclas
    def _on_record_clicked(self, _btn):
        if self.recording:
            self._stop_recording(commit=False)
        else:
            self.recording = True
            self._rec_combo, self._rec_held = [], set()
            self.record_btn.set_label(_("Press the keys… (cancel)"))
            self.record_btn.add_css_class("recording")
            self.record_btn.add_css_class("destructive-action")
            self._update_editor()

    def _stop_recording(self, commit: bool):
        if commit and self._rec_combo:
            combo = keys.sort_combo(self._rec_combo)
            if self.sequence_check.get_active():
                self.editor_steps.append(combo)
            else:
                self.editor_steps = [combo]
            self._draft_changed()
        self.recording = False
        self._rec_combo, self._rec_held = [], set()
        self.record_btn.set_label(_("Record keys"))
        self.record_btn.remove_css_class("recording")
        self.record_btn.remove_css_class("destructive-action")
        self._update_editor()

    def _on_key_pressed(self, _ctrl, _keyval, keycode, _state):
        code = keycode - 8  # keycode XKB -> código evdev
        if self.recording:
            if code > 0 and code not in self._rec_combo:
                self._rec_combo.append(code)
            self._rec_held.add(code)
            self._update_editor()
            return True
        if self.test_engine is not None:
            if not self._recv_held:
                self._recv_combo = []
            self._recv_held.add(code)
            if code not in self._recv_combo:
                self._recv_combo.append(code)
            self.received_label.set_label(
                _("Keys received: {keys}").format(
                    keys=labels.combo_text(keys.sort_combo(self._recv_combo))))
        return False

    def _on_key_released(self, _ctrl, _keyval, keycode, _state):
        code = keycode - 8
        self._recv_held.discard(code)
        if self.recording:
            self._rec_held.discard(code)
            if not self._rec_held and self._rec_combo:
                self._stop_recording(commit=True)
            return True
        return False

    def _on_clear_keys(self, _btn):
        if self.recording:
            self._stop_recording(commit=False)
        self.editor_steps = []
        self._update_editor()
        self._draft_changed()

    def _draft_changed(self):
        """Reinicia o teste em andamento para incluir a macro editada."""
        if self.test_engine is not None:
            GLib.idle_add(lambda: (self.test_engine is not None and self._restart_test(), False)[1])

    def _on_add_key_from_list(self, _btn):
        idx = self.key_dropdown.get_selected()
        if not 0 <= idx < len(self.key_codes):
            return
        code = self.key_codes[idx]
        if not self.editor_steps:
            self.editor_steps = [[code]]
        elif code not in self.editor_steps[-1]:
            self.editor_steps[-1] = keys.sort_combo(self.editor_steps[-1] + [code])
        self._update_editor()
        self._draft_changed()

    # -- botão do mouse
    def _on_button_dropdown(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        if idx <= 0:
            return
        self.editor_button = keys.COMMON_BUTTONS[idx - 1]
        dropdown.set_selected(0)
        self._update_editor()
        self._draft_changed()

    def _on_detect_clicked(self, _btn):
        if self.detector:
            self._finish_detection(cancel=True)
            return
        if not self.current or not self.current.connected:
            self.toast(_("Connect and select a mouse first"))
            return
        if self.test_btn.get_active():
            self.test_btn.set_active(False)
        self._pause_service()
        self.detect_btn.set_label(_("Press a mouse button… (cancel)"))
        self.detect_btn.add_css_class("recording")
        self.detector = ButtonDetector(
            self.current.paths,
            lambda code, err: GLib.idle_add(self._on_detected, code, err))
        self.detector.start()

    def _on_detected(self, code, error):
        if self.detector is None:
            return False
        self._finish_detection(cancel=False)
        if error:
            self.toast(error, 5)
        elif code is not None:
            self.editor_button = code
            self._update_editor()
        return False

    def _finish_detection(self, cancel: bool):
        det, self.detector = self.detector, None
        if det is None:
            return
        if cancel:
            det.cancel()
        self.detect_btn.set_label(_("Detect button"))
        self.detect_btn.remove_css_class("recording")
        self._resume_service()

    # -- lista de mapeamentos
    def _on_add_mapping(self, _btn):
        if not self.current or self.editor_button is None or not self.editor_steps:
            return
        maps = self._current_maps()
        maps[:] = [m for m in maps if m["button"] != self.editor_button]
        maps.append({"button": self.editor_button, "steps": copy.deepcopy(self.editor_steps)})
        maps.sort(key=lambda m: m["button"])
        if self.editor_button == ecodes.BTN_LEFT:
            self.toast(_("Warning: the left button will stop clicking while the macro is active."), 6)
        self.editor_steps, self.editor_button = [], None
        self._set_dirty()
        self._rebuild_list()
        self._update_editor()
        if self.test_engine is not None:
            self._restart_test()

    def _rebuild_list(self):
        self.maps_list.remove_all()
        maps = self._current_maps()
        for m in maps:
            row = Adw.ActionRow(title=keys.button_label(m["button"]),
                                subtitle=_("Sends: {keys}").format(keys=labels.steps_text(m["steps"])))
            row.set_use_markup(False)
            row.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))

            edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text=_("Edit"))
            edit.add_css_class("flat")
            edit.connect("clicked", self._on_edit_mapping, m["button"])
            delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text=_("Remove"))
            delete.add_css_class("flat")
            delete.connect("clicked", self._on_delete_mapping, m["button"])
            row.add_suffix(edit)
            row.add_suffix(delete)
            self.maps_list.append(row)
        self.maps_list.set_visible(bool(maps))
        self.maps_group.set_description(
            None if maps else _("No macros added yet. Build one above and click "
                                "“Add mapping”."))

    def _on_edit_mapping(self, _btn, button):
        for m in self._current_maps():
            if m["button"] == button:
                self.editor_button = button
                self.editor_steps = copy.deepcopy(m["steps"])
                self.sequence_check.set_active(len(m["steps"]) > 1)
                self._update_editor()
                self._draft_changed()
                break

    def _on_delete_mapping(self, _btn, button):
        maps = self._current_maps()
        maps[:] = [m for m in maps if m["button"] != button]
        self._set_dirty()
        self._rebuild_list()
        self._update_editor()
        if self.test_engine is not None:
            if maps:
                self._restart_test()
            else:
                self.test_btn.set_active(False)

    # ================================================================ teste
    def _on_test_toggled(self, btn):
        if self._updating:
            return
        if btn.get_active():
            self._start_test()
        else:
            self._stop_test()

    def _set_test_active(self, active: bool):
        self._updating = True
        self.test_btn.set_active(active)
        self._updating = False
        self.test_btn.set_label(_("Stop test") if active else _("Test"))
        if active:
            self.test_btn.add_css_class("destructive-action")
        else:
            self.test_btn.remove_css_class("destructive-action")

    def _draft_mapping(self) -> dict | None:
        """Macro que está no editor (ainda não adicionada à lista)."""
        if self.editor_steps and self.editor_button is not None:
            return {"button": self.editor_button, "steps": copy.deepcopy(self.editor_steps)}
        return None

    def _start_test(self):
        maps = copy.deepcopy(self._current_maps())
        draft = self._draft_mapping()
        if draft:
            maps = [m for m in maps if m["button"] != draft["button"]] + [draft]
        if not self.current or not maps:
            self.toast(_("Choose the keys and the mouse button before testing"))
            self._set_test_active(False)
            return
        if not self.current.connected:
            self.toast(_("The selected mouse is disconnected"))
            self._set_test_active(False)
            return
        if self.detector:
            self._finish_detection(cancel=True)

        self._pause_service()
        self._set_test_active(True)
        self._test_count = len(maps)
        engine = Remapper({self.current.key: maps}, require_device=True,
                          on_ready=lambda n: GLib.idle_add(self._on_test_ready))
        self.test_engine = engine
        self.received_label.set_label(_("Keys received: —"))

        def worker():
            try:
                engine.run()
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._on_test_failed, engine, str(exc))

        self.test_thread = threading.Thread(target=worker, daemon=True)
        self.test_thread.start()

    def _on_test_ready(self):
        if self.test_engine is not None:
            n = self._test_count
            self.test_status.set_label(ngettext(
                "● Test active with {n} macro. Use the mouse button with the cursor "
                "in the field below.",
                "● Test active with {n} macros. Use the mouse button with the cursor "
                "in the field below.", n).format(n=n))
            self.test_status.set_visible(True)
            self.test_entry.grab_focus()
        return False

    def _on_test_failed(self, engine, message):
        if engine is self.test_engine:
            self._stop_test()
            self.toast(message, 6)
            self.check_permissions()
        return False

    def _stop_test(self):
        engine, self.test_engine = self.test_engine, None
        if engine is not None:
            engine.stop()
            if self.test_thread:
                self.test_thread.join(timeout=3)
            self.test_thread = None
            self._resume_service()
        self._recv_held.clear()
        self.test_status.set_visible(False)
        self._set_test_active(False)

    def _restart_test(self):
        self._stop_test()
        self._start_test()

    # =============================================================== salvar
    def save(self) -> bool:
        if self.recording:
            self._stop_recording(commit=False)
        if self.detector:
            self._finish_detection(cancel=True)
        if self.test_engine is not None:
            self._stop_test()

        names = {e.key: e.name for e in self.device_entries}
        devices_cfg = {}
        for key, maps in self.mappings.items():
            if maps:
                name = names.get(key) or self.cfg["devices"].get(key, {}).get("name", key)
                devices_cfg[key] = {"name": name, "mappings": copy.deepcopy(maps)}
        self.cfg["devices"] = devices_cfg
        try:
            config.save(self.cfg)
        except OSError as exc:
            self.toast(_("Error while saving: {error}").format(error=exc), 6)
            return False

        ok, msg = service.apply(bool(devices_cfg))
        self._set_dirty(False)
        self._update_service_status()
        if not ok:
            self.toast(_("Saved, but there was a problem with the service. {details}").format(details=msg), 8)
        elif devices_cfg:
            self.toast(_("Saved! The macros stay active even after a restart."))
        else:
            self.toast(_("Saved. With no mappings, the service was disabled."))
        return True

    def _on_disable_service(self, *_args):
        if self.test_engine is not None:
            self._stop_test()
        self._service_was_active = False
        if service.disable():
            self.toast(_("Service disabled. Click Save to turn it back on."))
        else:
            self.toast(_("Could not disable the service."))
        self._update_service_status()

    # =============================================================== fechar
    def _on_close_request(self, *_args):
        if self.dirty and not self._force_close:
            dialog = Adw.AlertDialog(heading=_("Save changes?"),
                                     body=_("Some mappings have not been saved yet."))
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("discard", _("Discard"))
            dialog.add_response("save", _("Save"))
            dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("save")
            dialog.set_close_response("cancel")
            dialog.connect("response", self._on_close_response)
            dialog.present(self)
            return True
        self._cleanup()
        return False

    def _on_close_response(self, _dialog, response):
        if response == "cancel":
            return
        if response == "save" and not self.save():
            return
        self._force_close = True
        self.close()

    def _cleanup(self):
        if self.detector:
            self._finish_detection(cancel=True)
        if self.test_engine is not None:
            self._stop_test()
        while self._pause_count:
            self._resume_service()
