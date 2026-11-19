"""Tradução da interface (gettext).

Os textos do código estão em inglês. Se existir um catálogo para o idioma do
sistema, ele é carregado; caso contrário, fica o inglês. Hoje há apenas o
catálogo "pt", usado para pt_BR, pt_PT etc.

Os catálogos compilados ficam em <prefixo>/share/locale/<idioma>/LC_MESSAGES/
mouse-remapper.mo. O caminho é relativo a este arquivo, então funciona tanto
instalado (/usr/share/locale) quanto rodando direto do repositório
(usr/share/locale, depois de compilar os .po).
"""

import gettext
import os
import re
from pathlib import Path

DOMAIN = "mouse-remapper"
# .../share/mouse-remapper/core/i18n.py -> .../share/locale
LOCALE_DIR = Path(__file__).resolve().parent.parent.parent / "locale"


def _base_language(value: str) -> str:
    """'pt_BR.UTF-8' -> 'pt', 'en_US@euro' -> 'en'."""
    return re.split(r"[_.@-]", value.strip(), maxsplit=1)[0].lower()


def ui_language() -> str:
    """Idioma da interface, seguindo a mesma prioridade do gettext."""
    locale_value = ""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        locale_value = os.environ.get(var, "").strip()
        if locale_value:
            break
    if locale_value in ("", "C", "POSIX") or locale_value.startswith("C."):
        return "en"  # o gettext ignora LANGUAGE quando o locale é C
    for entry in os.environ.get("LANGUAGE", "").split(":"):
        if entry.strip():
            locale_value = entry
            break
    return _base_language(locale_value) or "en"


def _load():
    lang = ui_language()
    if lang != "en" and gettext.find(DOMAIN, LOCALE_DIR, languages=[lang]):
        return lang, gettext.translation(DOMAIN, LOCALE_DIR, languages=[lang])
    return "en", gettext.NullTranslations()  # sem tradução: inglês


LANGUAGE, _translation = _load()

_ = _translation.gettext
ngettext = _translation.ngettext
