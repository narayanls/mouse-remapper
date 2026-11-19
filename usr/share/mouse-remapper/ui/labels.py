"""Rótulos de teclas que respeitam o layout ativo (ex.: ABNT2 mostra “Ç”)."""

from gi.repository import Gdk

from core import keys


def key_label(code: int) -> str:
    if code in keys.FRIENDLY:
        return keys.FRIENDLY[code]
    display = Gdk.Display.get_default()
    if display is not None:
        try:
            ok, keymap_keys, keyvals = display.map_keycode(code + 8)  # evdev + 8 = keycode XKB
            if ok:
                for kk, kv in zip(keymap_keys, keyvals):
                    if kk.group == 0 and kk.level == 0:
                        ch = Gdk.keyval_to_unicode(kv)
                        if ch:
                            char = chr(ch)
                            if char.isprintable() and not char.isspace():
                                return char.upper()
                        break
        except Exception:  # noqa: BLE001
            pass
    return keys.key_label(code)


def combo_text(step) -> str:
    return keys.combo_text(step, key_label)


def steps_text(steps) -> str:
    return keys.steps_text(steps, key_label)
