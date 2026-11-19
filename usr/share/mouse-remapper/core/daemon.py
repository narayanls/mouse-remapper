"""Serviço em segundo plano: aplica a configuração salva.

Executado pelo systemd (mouse-remapper.service) com `mouse-remapper --daemon`.
SIGHUP recarrega a configuração; SIGTERM/SIGINT encerra.
"""

import logging
import signal
import time

from . import config
from .engine import Remapper

log = logging.getLogger("mouse-remapper")


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    state = {"exit": False, "engine": None}

    def on_term(*_):
        state["exit"] = True
        if state["engine"]:
            state["engine"].stop()

    def on_hup(*_):
        log.info("Recarregando configuração…")
        if state["engine"]:
            state["engine"].stop()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    signal.signal(signal.SIGHUP, on_hup)

    while not state["exit"]:
        profiles = config.profiles(config.load())
        total = sum(len(m) for m in profiles.values())
        log.info("%d mapeamento(s) em %d dispositivo(s).", total, len(profiles))
        engine = Remapper(profiles)
        state["engine"] = engine
        try:
            engine.run()
        except Exception as exc:  # noqa: BLE001
            log.error("%s", exc)
            # Ex.: /dev/uinput sem permissão. Tenta de novo em alguns segundos.
            for _ in range(50):
                if state["exit"]:
                    break
                time.sleep(0.1)
    log.info("Encerrado.")
    return 0
