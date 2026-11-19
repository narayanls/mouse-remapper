"""Descoberta de mouses via evdev.

Um mouse físico costuma expor vários nós em /dev/input (ex.: "Mouse" e
"Keyboard" — muitos mouses gamer usam a interface de teclado para os botões
extras). Por isso agrupamos os nós pelo par vendor:product.
"""

import glob
import grp
import os
import pwd
from dataclasses import dataclass, field

import evdev
from evdev import ecodes as e

VIRTUAL_PREFIX = "Mouse Remapper"
UINPUT_PATH = "/dev/uinput"


@dataclass
class DeviceGroup:
    key: str
    name: str
    paths: list = field(default_factory=list)


def event_nodes() -> list[str]:
    return sorted(glob.glob("/dev/input/event*"))


def device_key(dev: evdev.InputDevice) -> str:
    vendor, product = dev.info.vendor, dev.info.product
    if vendor == 0 and product == 0:
        return "name:" + dev.name
    return f"{vendor:04x}:{product:04x}"


def list_groups(only_mice: bool = True) -> list[DeviceGroup]:
    groups: dict[str, dict] = {}
    for path in event_nodes():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            if dev.name.startswith(VIRTUAL_PREFIX):
                continue  # nossos próprios dispositivos virtuais
            caps = dev.capabilities()
            keys = set(caps.get(e.EV_KEY, []))
            is_mouse = e.BTN_LEFT in keys and e.EV_REL in caps
            key = device_key(dev)
            g = groups.setdefault(key, {"names": [], "mouse_names": [], "paths": [], "mouse": False})
            g["paths"].append(path)
            g["names"].append(dev.name)
            if is_mouse:
                g["mouse"] = True
                g["mouse_names"].append(dev.name)
        except OSError:
            continue
        finally:
            dev.close()

    result = []
    for key, g in groups.items():
        if only_mice and not g["mouse"]:
            continue
        names = g["mouse_names"] or g["names"]
        result.append(DeviceGroup(key=key, name=min(names, key=len), paths=sorted(g["paths"])))
    result.sort(key=lambda d: d.name.lower())
    return result


def list_mice() -> list[DeviceGroup]:
    return list_groups(only_mice=True)


def _input_group_configured() -> bool:
    """O usuário já foi adicionado ao grupo input (em /etc/group)?"""
    try:
        group = grp.getgrnam("input")
        user = pwd.getpwuid(os.getuid())
    except KeyError:
        return False
    return user.pw_name in group.gr_mem or user.pw_gid == group.gr_gid


def permission_problems() -> list[str]:
    """Retorna códigos de problema: 'input', 'input-reboot', 'uinput-missing', 'uinput'.

    'input-reboot': o usuário já está no grupo input, mas a sessão atual ainda
    não tem o grupo ativo. Só um reinício (ou novo login completo) aplica isso.
    """
    problems = []
    nodes = event_nodes()
    if nodes and not any(os.access(p, os.R_OK) for p in nodes):
        problems.append("input-reboot" if _input_group_configured() else "input")
    if not os.path.exists(UINPUT_PATH):
        problems.append("uinput-missing")
    elif not os.access(UINPUT_PATH, os.R_OK | os.W_OK):
        problems.append("uinput")
    return problems
