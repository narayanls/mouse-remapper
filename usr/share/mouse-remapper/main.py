#!/usr/bin/env python3
"""Mouse Remapper — macros de teclado nos botões do mouse.

Uso:
    mouse-remapper            abre a interface
    mouse-remapper --daemon   executa o serviço em segundo plano (systemd)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if "--daemon" in sys.argv[1:]:
        from core import daemon
        return daemon.run()

    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from ui.application import MouseRemapperApp

    return MouseRemapperApp().run([a for a in sys.argv if a != "--daemon"])


if __name__ == "__main__":
    sys.exit(main())
