"""Nomes amigáveis para teclas e botões (códigos evdev)."""

from evdev import ecodes as e

# Ordem canônica em que os modificadores são pressionados/exibidos.
MODIFIER_ORDER = [
    e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL,
    e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT,
    e.KEY_LEFTALT, e.KEY_RIGHTALT,
    e.KEY_LEFTMETA, e.KEY_RIGHTMETA,
]
MODIFIERS = set(MODIFIER_ORDER)

# Rótulos fixos (não dependem do layout do teclado).
FRIENDLY = {
    e.KEY_LEFTCTRL: "Ctrl", e.KEY_RIGHTCTRL: "Ctrl Direito",
    e.KEY_LEFTSHIFT: "Shift", e.KEY_RIGHTSHIFT: "Shift Direito",
    e.KEY_LEFTALT: "Alt", e.KEY_RIGHTALT: "AltGr",
    e.KEY_LEFTMETA: "Super", e.KEY_RIGHTMETA: "Super Direito",
    e.KEY_ESC: "Esc", e.KEY_ENTER: "Enter", e.KEY_KPENTER: "Enter (Num)",
    e.KEY_SPACE: "Espaço", e.KEY_BACKSPACE: "Backspace", e.KEY_TAB: "Tab",
    e.KEY_CAPSLOCK: "Caps Lock", e.KEY_NUMLOCK: "Num Lock", e.KEY_SCROLLLOCK: "Scroll Lock",
    e.KEY_INSERT: "Insert", e.KEY_DELETE: "Delete", e.KEY_HOME: "Home", e.KEY_END: "End",
    e.KEY_PAGEUP: "Page Up", e.KEY_PAGEDOWN: "Page Down",
    e.KEY_UP: "Seta ↑", e.KEY_DOWN: "Seta ↓", e.KEY_LEFT: "Seta ←", e.KEY_RIGHT: "Seta →",
    e.KEY_SYSRQ: "Print Screen", e.KEY_PAUSE: "Pause", e.KEY_COMPOSE: "Menu",
    e.KEY_MUTE: "Mudo", e.KEY_VOLUMEDOWN: "Volume −", e.KEY_VOLUMEUP: "Volume +",
    e.KEY_PLAYPAUSE: "Play/Pause", e.KEY_STOPCD: "Parar mídia",
    e.KEY_NEXTSONG: "Próxima faixa", e.KEY_PREVIOUSSONG: "Faixa anterior",
    e.KEY_BRIGHTNESSUP: "Brilho +", e.KEY_BRIGHTNESSDOWN: "Brilho −",
    e.KEY_CALC: "Calculadora", e.KEY_WWW: "Navegador", e.KEY_MAIL: "E-mail",
    e.KEY_HOMEPAGE: "Página inicial", e.KEY_BACK: "Voltar (navegador)",
    e.KEY_FORWARD: "Avançar (navegador)", e.KEY_REFRESH: "Atualizar (navegador)",
    e.KEY_KPPLUS: "Num +", e.KEY_KPMINUS: "Num −", e.KEY_KPASTERISK: "Num *",
    e.KEY_KPSLASH: "Num /", e.KEY_KPDOT: "Num ,",
}

# Rótulos de reserva para pontuação (posição do layout americano).
# A interface tenta antes descobrir o caractere real pelo layout ativo.
PUNCTUATION = {
    e.KEY_MINUS: "-", e.KEY_EQUAL: "=", e.KEY_LEFTBRACE: "[", e.KEY_RIGHTBRACE: "]",
    e.KEY_SEMICOLON: ";", e.KEY_APOSTROPHE: "'", e.KEY_GRAVE: "`",
    e.KEY_BACKSLASH: "\\", e.KEY_COMMA: ",", e.KEY_DOT: ".", e.KEY_SLASH: "/",
    e.KEY_102ND: "\\ (tecla ISO)", e.KEY_RO: "/ (ABNT)",
}

BUTTON_NAMES = {
    e.BTN_LEFT: "Botão esquerdo",
    e.BTN_RIGHT: "Botão direito",
    e.BTN_MIDDLE: "Botão do meio (roda)",
    e.BTN_SIDE: "Lateral – Voltar",
    e.BTN_EXTRA: "Lateral – Avançar",
    e.BTN_FORWARD: "Botão Avançar",
    e.BTN_BACK: "Botão Voltar",
    e.BTN_TASK: "Botão extra (Task)",
}
COMMON_BUTTONS = list(BUTTON_NAMES)

_BAD_ALIASES = {"KEY_MIN_INTERESTING", "BTN_MISC", "BTN_MOUSE"}


def raw_name(code: int) -> str | None:
    """Nome evdev do código (KEY_A, BTN_SIDE…), escolhendo o alias mais legível."""
    for table in (e.KEY, e.BTN):
        name = table.get(code)
        if name is None:
            continue
        if isinstance(name, (list, tuple)):
            good = [n for n in name if n not in _BAD_ALIASES]
            name = (good or list(name))[0]
        return name
    return None


def key_label(code: int) -> str:
    if code in FRIENDLY:
        return FRIENDLY[code]
    if code in PUNCTUATION:
        return PUNCTUATION[code]
    name = raw_name(code)
    if not name:
        return f"Código {code}"
    if name.startswith("BTN_"):
        return button_label(code)
    name = name[4:]  # remove "KEY_"
    if name.startswith("KP") and len(name) > 2:
        return "Num " + name[2:].capitalize()
    if len(name) <= 3:  # A, 5, F12…
        return name.upper()
    return name.replace("_", " ").title()


def button_label(code: int) -> str:
    if code in BUTTON_NAMES:
        return BUTTON_NAMES[code]
    name = raw_name(code)
    if name and name.startswith("BTN_"):
        suffix = name[4:]
        if suffix.isdigit():
            return f"Botão {suffix}"
        return f"Botão {suffix.replace('_', ' ').title()}"
    if name and name.startswith("KEY_"):
        # Alguns mouses "gamer" enviam teclas de teclado nos botões extras.
        return f"Botão que envia “{key_label(code)}”"
    return f"Botão {code}"


def sort_combo(codes) -> list[int]:
    """Modificadores primeiro (ordem canônica); demais teclas na ordem gravada."""
    codes = list(dict.fromkeys(codes))
    mods = [c for c in MODIFIER_ORDER if c in codes]
    rest = [c for c in codes if c not in MODIFIERS]
    return mods + rest


def combo_text(step, label=key_label) -> str:
    return " + ".join(label(k) for k in step)


def steps_text(steps, label=key_label) -> str:
    return "  →  ".join(combo_text(s, label) for s in steps)


def output_key_codes() -> list[int]:
    """Todas as teclas KEY_* que o teclado virtual pode emitir."""
    codes = []
    for code in range(1, 0x2FF):
        if 0x100 <= code < 0x160 or 0x2C0 <= code < 0x2E8:
            continue  # faixas BTN_*
        name = raw_name(code)
        if name and name.startswith("KEY_"):
            codes.append(code)
    return codes


def selectable_key_codes() -> list[int]:
    """Lista ordenada de teclas oferecidas na escolha manual."""
    ordered = [e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT, e.KEY_LEFTALT, e.KEY_RIGHTALT, e.KEY_LEFTMETA,
               e.KEY_RIGHTCTRL, e.KEY_RIGHTSHIFT, e.KEY_RIGHTMETA]
    letters = sorted((getattr(e, f"KEY_{c}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
                     key=lambda c: raw_name(c))
    digits = [getattr(e, f"KEY_{d}") for d in "1234567890"]
    fkeys = [getattr(e, f"KEY_F{i}") for i in range(1, 25)]
    common = [e.KEY_ESC, e.KEY_ENTER, e.KEY_SPACE, e.KEY_TAB, e.KEY_BACKSPACE, e.KEY_DELETE,
              e.KEY_INSERT, e.KEY_HOME, e.KEY_END, e.KEY_PAGEUP, e.KEY_PAGEDOWN,
              e.KEY_UP, e.KEY_DOWN, e.KEY_LEFT, e.KEY_RIGHT, e.KEY_SYSRQ, e.KEY_CAPSLOCK,
              e.KEY_MUTE, e.KEY_VOLUMEDOWN, e.KEY_VOLUMEUP, e.KEY_PLAYPAUSE,
              e.KEY_PREVIOUSSONG, e.KEY_NEXTSONG, e.KEY_STOPCD]
    ordered += letters + digits + fkeys + common
    seen = set(ordered)
    for code in range(1, 249):
        name = raw_name(code)
        if code not in seen and name and name.startswith("KEY_") and code != e.KEY_RESERVED:
            ordered.append(code)
            seen.add(code)
    return ordered
