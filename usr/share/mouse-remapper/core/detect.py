"""Detecção do botão do mouse: espera o próximo botão pressionado."""

import select
import threading
import time

import evdev
from evdev import ecodes as e


class ButtonDetector:
    def __init__(self, paths, callback, timeout: float = 15.0):
        """callback(code | None, error | None) é chamado na thread de detecção."""
        self.paths = list(paths)
        self.callback = callback
        self.timeout = timeout
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def cancel(self):
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self):
        devs, code, error = [], None, None
        try:
            for path in self.paths:
                try:
                    devs.append(evdev.InputDevice(path))
                except OSError as exc:
                    error = f"Sem acesso a {path} ({exc.strerror})."
            if not devs:
                raise RuntimeError(error or "Mouse não encontrado.")
            error = None
            deadline = time.monotonic() + self.timeout
            while code is None and not self._stop.is_set():
                if time.monotonic() > deadline:
                    error = "Tempo esgotado: nenhum botão foi pressionado."
                    break
                ready, _, _ = select.select(devs, [], [], 0.25)
                for dev in ready:
                    try:
                        for ev in dev.read():
                            if ev.type == e.EV_KEY and ev.value == 1:
                                code = ev.code
                                break
                    except BlockingIOError:
                        pass
                    if code is not None:
                        break
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        finally:
            for dev in devs:
                dev.close()
        if not self._stop.is_set():
            self.callback(code, error)
