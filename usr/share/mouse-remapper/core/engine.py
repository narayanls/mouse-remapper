"""Motor de remapeamento.

Funcionamento:
  1. Abre os nós /dev/input do mouse configurado que possuem algum dos botões
     mapeados e faz um "grab" exclusivo (o sistema deixa de vê-los diretamente).
  2. Cria um clone virtual (uinput) de cada nó capturado e repassa para ele
     todos os eventos que NÃO foram mapeados (movimento, roda, outros botões).
  3. Quando um botão mapeado é pressionado, emite as teclas em um teclado
     virtual. Com uma única combinação, as teclas ficam pressionadas enquanto
     o botão estiver pressionado (dá para "segurar" Shift, por exemplo).
     Com uma sequência, as etapas são enviadas em ordem ao pressionar.

O mesmo motor é usado pelo serviço em segundo plano e pelo modo de teste da
interface. Novos dispositivos (reconexão USB/receptor) são detectados
automaticamente.
"""

import logging
import select
import threading
import time
from dataclasses import dataclass

import evdev
from evdev import UInput, ecodes as e

from . import devices, keys

log = logging.getLogger("mouse-remapper")

STEP_DELAY = 0.04      # pausa entre etapas de uma sequência
TAP_DELAY = 0.012      # tempo entre pressionar e soltar numa etapa
RESCAN_INTERVAL = 30.0  # nova varredura mesmo sem mudança em /dev/input
GRAB_WAIT = 3.0        # espera botões soltos antes do grab


@dataclass
class _Attached:
    dev: evdev.InputDevice
    clone: UInput
    table: dict  # botão -> etapas


class Remapper:
    def __init__(self, profiles: dict, require_device: bool = False, on_ready=None):
        """profiles: {chave_dispositivo: [{"button": int, "steps": [[int, ...], ...]}]}"""
        self.profiles: dict[str, dict[int, list[list[int]]]] = {}
        for dev_key, maps in profiles.items():
            table = {}
            for m in maps:
                steps = [keys.sort_combo(int(k) for k in s) for s in m.get("steps", []) if s]
                if steps:
                    table[int(m["button"])] = steps
            if table:
                self.profiles[dev_key] = table

        self.require_device = require_device
        self.on_ready = on_ready
        self._stop = threading.Event()
        self._attached: dict[str, _Attached] = {}
        self._held: dict[tuple, list[int]] = {}
        self._keyboard: UInput | None = None
        self._failed: dict[str, str] = {}

    # ------------------------------------------------------------------ API
    def stop(self):
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run(self):
        if not self.profiles:
            if self.require_device:
                raise RuntimeError("Nenhum mapeamento para testar.")
            log.info("Nenhum mapeamento configurado; aguardando.")
            while not self._stop.wait(1.0):
                pass
            return

        try:
            self._keyboard = UInput({e.EV_KEY: keys.output_key_codes()},
                                    name=f"{devices.VIRTUAL_PREFIX} Keyboard")
        except OSError as exc:
            raise RuntimeError(
                f"Não foi possível criar o teclado virtual em {devices.UINPUT_PATH}: {exc}") from exc

        try:
            self._loop()
        finally:
            for path in list(self._attached):
                self._detach(path)
            self._keyboard.close()
            self._keyboard = None

    # ---------------------------------------------------------------- laço
    def _loop(self):
        last_listing = None
        last_scan = 0.0
        first = True
        while not self._stop.is_set():
            listing = devices.event_nodes()
            now = time.monotonic()
            if listing != last_listing or now - last_scan > RESCAN_INTERVAL:
                self._scan()
                last_listing, last_scan = listing, now
                if first:
                    first = False
                    if self.require_device and not self._attached:
                        detail = "; ".join(sorted(set(self._failed.values())))
                        raise RuntimeError(
                            "Não foi possível capturar o mouse." + (f" {detail}" if detail else
                            " Verifique se ele está conectado."))
                    if self.on_ready:
                        self.on_ready(len(self._attached))

            if not self._attached:
                self._stop.wait(1.0)
                continue

            by_fd = {a.dev.fd: path for path, a in self._attached.items()}
            try:
                ready, _, _ = select.select(list(by_fd), [], [], 1.0)
            except (OSError, ValueError):
                ready = []
                for path in list(self._attached):
                    try:
                        self._attached[path].dev.fileno()
                    except Exception:
                        self._detach(path)
            for fd in ready:
                path = by_fd.get(fd)
                att = self._attached.get(path)
                if att is None:
                    continue
                try:
                    for ev in att.dev.read():
                        self._handle(path, att, ev)
                except BlockingIOError:
                    pass
                except OSError:
                    log.info("Dispositivo desconectado: %s", path)
                    self._detach(path)

    def _scan(self):
        for group in devices.list_groups(only_mice=False):
            table = self.profiles.get(group.key)
            if not table:
                continue
            for path in group.paths:
                if path in self._attached:
                    continue
                self._attach(path, table)

    def _attach(self, path: str, table: dict):
        try:
            dev = evdev.InputDevice(path)
        except OSError as exc:
            self._fail(path, f"Sem acesso a {path} ({exc.strerror}).")
            return
        try:
            caps_keys = set(dev.capabilities().get(e.EV_KEY, []))
            if not caps_keys & set(table):
                dev.close()  # este nó não tem nenhum botão mapeado
                return

            # Não captura com botão pressionado: o "soltar" iria para o clone
            # e o botão original ficaria preso no sistema.
            deadline = time.monotonic() + GRAB_WAIT
            while dev.active_keys() and time.monotonic() < deadline and not self._stop.is_set():
                time.sleep(0.05)

            name = f"{devices.VIRTUAL_PREFIX} ({dev.name})"[:79]
            clone = UInput.from_device(dev, name=name)
            try:
                dev.grab()
            except OSError as exc:
                clone.close()
                raise OSError(exc.errno, "dispositivo em uso por outro programa") from exc
        except OSError as exc:
            dev.close()
            msg = exc.strerror or str(exc)
            self._fail(path, f"Falha ao capturar {path}: {msg}.")
            return

        self._failed.pop(path, None)
        self._attached[path] = _Attached(dev=dev, clone=clone, table=table)
        log.info("Capturado: %s (%s)", path, dev.name)

    def _fail(self, path: str, msg: str):
        if self._failed.get(path) != msg:
            log.warning(msg)
        self._failed[path] = msg

    def _detach(self, path: str):
        att = self._attached.pop(path, None)
        if att is None:
            return
        for held_key in [k for k in self._held if k[0] == path]:
            self._release(*held_key)
        for closer in (att.dev.ungrab, att.dev.close, att.clone.close):
            try:
                closer()
            except Exception:
                pass

    # ------------------------------------------------------------- eventos
    def _handle(self, path: str, att: _Attached, ev):
        if ev.type == e.EV_KEY and ev.code in att.table:
            if ev.value == 1:
                self._press(path, ev.code, att.table[ev.code])
            elif ev.value == 0:
                self._release(path, ev.code)
            return  # valor 2 (auto-repetição) é ignorado
        att.clone.write_event(ev)

    def _press(self, path: str, button: int, steps: list[list[int]]):
        kb = self._keyboard
        if len(steps) == 1:
            step = steps[0]
            for k in step:
                kb.write(e.EV_KEY, k, 1)
            kb.syn()
            self._held[(path, button)] = step
            return
        for i, step in enumerate(steps):
            if i:
                time.sleep(STEP_DELAY)
            for k in step:
                kb.write(e.EV_KEY, k, 1)
            kb.syn()
            time.sleep(TAP_DELAY)
            for k in reversed(step):
                kb.write(e.EV_KEY, k, 0)
            kb.syn()

    def _release(self, path: str, button: int):
        step = self._held.pop((path, button), None)
        if not step or self._keyboard is None:
            return
        for k in reversed(step):
            self._keyboard.write(e.EV_KEY, k, 0)
        self._keyboard.syn()
