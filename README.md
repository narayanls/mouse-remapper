# Mouse Remapper

Map keyboard shortcuts and key sequences to your mouse buttons on Linux.

Mouse Remapper is a small GTK 4 / libadwaita app that turns any mouse button into a keyboard macro, such as `Ctrl + C` on a side button or `Ctrl + C → Alt + Tab → Ctrl + V` on another. It works at the kernel input level (evdev/uinput), so it behaves the same on **Wayland and X11** and in any desktop environment.

## Features

- **Key combinations**: assign a shortcut like `Ctrl + Shift + T` to a button. While you hold the button, the keys stay pressed, so you can also use a button as a held modifier (e.g. Shift).
- **Key sequences**: record several steps that are sent in order with one click.
- **Easy recording**: click *Record keys* and press the combination, or pick keys from a list. Click *Detect button* and press the mouse button you want to use.
- **Test before saving**: a built-in test mode turns your macros on temporarily, with no changes saved.
- **Runs in the background**: saved macros are applied by a systemd user service, so they keep working after you close the app and after a reboot.
- **Per-device profiles**: each mouse (identified by vendor:product ID) has its own mappings.
- **Hot-plug support**: unplugging and reconnecting a mouse or wireless receiver is detected automatically.
- **Layout-aware labels**: key names follow your active keyboard layout (e.g. ABNT2 shows `Ç`).
- **Gaming mouse friendly**: extra buttons exposed by a mouse's secondary "keyboard" interface are grouped under the same device.

- **English and Portuguese**: the language follows your system. Portuguese systems (Brazil or Portugal) get Portuguese; every other language gets English.

## How it works

1. The app takes exclusive control (a "grab") of the mouse's input nodes that contain a mapped button.
2. A virtual clone of the mouse is created with uinput, and every event that is **not** mapped (movement, scroll, other buttons) is passed through to it unchanged.
3. When a mapped button is pressed, the corresponding keys are sent through a virtual keyboard.

## Requirements

- Linux with the `uinput` kernel module
- Python 3.10+
- GTK 4 and libadwaita
- PyGObject (`python-gobject`)
- python-evdev
- systemd (for the background service)
- Your user in the `input` group

## Installation

### Arch Linux and derivatives

Download the package (`mouse-remapper-<version>-any.pkg.tar.zst`) from the [latest release](https://github.com/narayanls/mouse-remapper/releases/latest) and install it with pacman:

```bash
sudo pacman -U mouse-remapper-*-any.pkg.tar.zst
```

pacman will install the required dependencies automatically.

The package installs the app, the systemd user service, a udev rule for `/dev/uinput`, and loads the `uinput` module on boot.

### Grant access to your mouse

Mouse Remapper needs to read input devices, so your user must be in the `input` group:

```bash
sudo usermod -aG input $USER
```

Then **reboot**. Logging out or reopening the app is not enough for the new group to take effect. If something is missing, the app shows a banner with the exact command to run.

## Usage

1. Open **Mouse Remapper** from your app menu, or run `mouse-remapper`.
2. Select your mouse.
3. Under the keyboard card, click **Record keys** and press a combination. Enable the sequence option to add more steps.
4. Under the mouse card, click **Detect button** and press the mouse button you want to use, or choose one from the list.
5. Click **Add mapping**.
6. Optionally click **Test** and try the button in the test field.
7. Click **Save**. The background service is enabled and your macros stay active, including after a reboot.

> Mapping the left mouse button is allowed, but it will stop clicking while the macro is active.

## Configuration

Mappings are stored in `~/.config/mouse-remapper/config.json` (or `$XDG_CONFIG_HOME/mouse-remapper/config.json`). Buttons and keys use evdev codes:

```json
{
  "version": 1,
  "devices": {
    "1d57:fa60": {
      "name": "Gaming Mouse",
      "mappings": [
        { "button": 275, "steps": [[29, 46]] },
        { "button": 276, "steps": [[29, 46], [29, 47]] }
      ]
    }
  }
}
```

In this example, `275` is `BTN_SIDE` mapped to `Ctrl + C`, and `276` is `BTN_EXTRA` mapped to the sequence `Ctrl + C → Ctrl + V`.

## Troubleshooting

| Problem | Solution |
| --- | --- |
| No mouse is listed / "no permission to read the mouse" | Add your user to the `input` group and reboot. |
| "The uinput module is not loaded" | Run `sudo modprobe uinput`. |
| "No permission on /dev/uinput" | Reinstall the package so the udev rule is applied, then reboot. |
| "Device in use by another program" | Another remapper (e.g. input-remapper, Solaar rules) may be grabbing the mouse. Stop it and try again. |
| Macros don't work after closing the app | Check the service with `systemctl --user status mouse-remapper.service` and click **Save** again. |

## Translations

The interface uses [gettext](https://www.gnu.org/software/gettext/). Strings in the source code are in English, and translations live in `po/`:

- `po/mouse-remapper.pot`: template with every translatable string
- `po/pt.po`: Portuguese (used for both `pt_BR` and `pt_PT`)

The language is picked from `LANGUAGE`, `LC_ALL`, `LC_MESSAGES` and `LANG`, in the same order gettext uses. To try another language without changing your system:

```bash
LANGUAGE=en mouse-remapper   # force English
LANGUAGE=pt mouse-remapper   # force Portuguese
```

**Adding a language** (requires `gettext`):

1. Create the file from the template, e.g. for Spanish: `msginit -i po/mouse-remapper.pot -o po/es.po -l es`
2. Translate the `msgstr` entries.

The new language is picked up automatically once the package is rebuilt; there is nothing to change in the code.

**After changing strings in the code**, run `po/update-po.sh` to refresh the template and merge new strings into every `.po` file.

**Running from the repository**: run `po/build-mo.sh` once to compile the translations into `usr/share/locale/`, then `python3 usr/share/mouse-remapper/main.py`. The package build compiles them automatically.

## Project structure

```
usr/
├── bin/mouse-remapper              launcher
└── share/
    ├── applications/               .desktop entry
    ├── icons/                      app icon
    └── mouse-remapper/
        ├── main.py                 entry point (GUI or --daemon)
        ├── core/                   config, devices, remapping engine, daemon, systemd control, i18n
        └── ui/                     GTK 4 / libadwaita interface
po/                                 translations (gettext)
pkgbuild/                           Arch Linux packaging
```

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
