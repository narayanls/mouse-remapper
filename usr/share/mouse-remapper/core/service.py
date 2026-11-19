"""Controle do serviço systemd de usuário (mouse-remapper.service)."""

import subprocess

from .i18n import _

SERVICE = "mouse-remapper.service"


def _ctl(*args) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["systemctl", "--user", *args],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None


def is_active() -> bool:
    r = _ctl("is-active", SERVICE)
    return bool(r) and r.stdout.strip() == "active"


def is_enabled() -> bool:
    r = _ctl("is-enabled", SERVICE)
    return bool(r) and r.stdout.strip() == "enabled"


def start() -> bool:
    r = _ctl("start", SERVICE)
    return bool(r) and r.returncode == 0


def stop() -> bool:
    r = _ctl("stop", SERVICE)
    return bool(r) and r.returncode == 0


def apply(has_mappings: bool) -> tuple[bool, str]:
    """Ativa (e reinicia) o serviço para carregar a nova configuração.

    Sem mapeamentos, o serviço é desativado."""
    if not has_mappings:
        r = _ctl("disable", "--now", SERVICE)
        return (bool(r) and r.returncode == 0, "" if r is None else r.stderr.strip())
    _ctl("daemon-reload")
    r = _ctl("enable", SERVICE)
    if not r or r.returncode != 0:
        return False, _("Could not enable the service: {error}").format(
            error="" if r is None else r.stderr.strip())
    r = _ctl("restart", SERVICE)
    if not r or r.returncode != 0:
        return False, _("Could not start the service: {error}").format(
            error="" if r is None else r.stderr.strip())
    return True, ""


def disable() -> bool:
    r = _ctl("disable", "--now", SERVICE)
    return bool(r) and r.returncode == 0
