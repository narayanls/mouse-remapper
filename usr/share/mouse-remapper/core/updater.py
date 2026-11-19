"""Atualizações a partir dos releases do GitHub (sem dependência de GTK).

Fluxo:
  1. fetch_latest() consulta a API do GitHub e devolve o último release
     (rascunhos e pré-lançamentos são ignorados pela própria API).
  2. A versão do release vem do nome do pacote anexado
     (mouse-remapper-<pkgver>-<pkgrel>-any.pkg.tar.zst); se não houver pacote,
     usa a tag (v1.2.0 ou 1.2.0). is_newer() compara com a versão instalada.
  3. download() baixa o pacote para ~/.cache/mouse-remapper/updates e confere o
     tamanho e o SHA-256 informados pelo GitHub.
  4. install() instala com "pkexec pacman -U", que pede a senha numa janela
     do sistema (polkit).
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import VERSION
from .i18n import _

REPO = "narayanls/mouse-remapper"
API_LATEST = os.environ.get("MOUSE_REMAPPER_UPDATE_URL",  # permite testar com outro servidor
                            f"https://api.github.com/repos/{REPO}/releases/latest")
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
INSTALL_DIR = Path("/usr/share/mouse-remapper")
TIMEOUT = 20
CHUNK = 64 * 1024

PACKAGE_RE = re.compile(
    r"^mouse-remapper-(?P<pkgver>[^-]+)-(?P<pkgrel>[^-]+)-any\.pkg\.tar\.(?:zst|xz)$")


class UpdateError(Exception):
    """Falha com mensagem pronta para mostrar ao usuário."""


class UpdateCancelled(Exception):
    pass


@dataclass
class Release:
    version: str
    page_url: str
    notes: str
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int = 0
    sha256: str | None = None


# ------------------------------------------------------------------ versões
def parse_version(value: str) -> tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2)."""
    value = value.strip().lstrip("vV").split("-")[0]
    return tuple(int(n) for n in re.findall(r"\d+", value))


def is_newer(remote: str, local: str = VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


# ------------------------------------------------------------------ consulta
def _open(url: str, accept: str):
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": f"mouse-remapper/{VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def fetch_latest() -> Release:
    try:
        with _open(API_LATEST, "application/vnd.github+json") as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(_("No release has been published yet.")) from exc
        if exc.code in (403, 429):
            raise UpdateError(_("GitHub is limiting requests right now. Try again later.")) from exc
        raise UpdateError(_("Could not check for updates (HTTP {code}).").format(code=exc.code)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(
            _("Could not check for updates. Check your internet connection.")) from exc

    release = Release(
        version=str(data.get("tag_name") or "").lstrip("vV"),
        page_url=str(data.get("html_url") or RELEASES_PAGE),
        notes=str(data.get("body") or "").strip(),
    )
    for asset in data.get("assets") or []:
        match = PACKAGE_RE.match(str(asset.get("name", "")))
        if not match:
            continue
        digest = str(asset.get("digest") or "")
        release.version = match["pkgver"]
        release.asset_name = asset["name"]
        release.asset_url = asset.get("browser_download_url")
        release.asset_size = int(asset.get("size") or 0)
        release.sha256 = digest[7:].lower() if digest.startswith("sha256:") else None
        break
    if not release.version:
        raise UpdateError(_("The latest release has no version number."))
    return release


# --------------------------------------------------------------- instalação
def install_support() -> str:
    """'ok' ou o motivo de não poder instalar: 'source', 'pacman', 'pkexec'."""
    here = Path(__file__).resolve().parent.parent
    if here != INSTALL_DIR:
        return "source"
    if not shutil.which("pacman"):
        return "pacman"
    if not shutil.which("pkexec"):
        return "pkexec"
    return "ok"


def _download_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    return Path(base) / "mouse-remapper" / "updates"


def download(release: Release, progress=None, cancel: threading.Event | None = None) -> Path:
    """Baixa o pacote. progress(fração 0..1 ou None) é chamado na thread atual."""
    if not release.asset_url or not release.asset_name:
        raise UpdateError(_("This release has no package to install."))

    directory = _download_dir()
    shutil.rmtree(directory, ignore_errors=True)  # sobras de tentativas antigas
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / release.asset_name
    partial = target.with_name(target.name + ".part")

    sha = hashlib.sha256()
    received = 0
    try:
        with _open(release.asset_url, "application/octet-stream") as resp, open(partial, "wb") as fh:
            total = release.asset_size or int(resp.headers.get("Content-Length") or 0)
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateCancelled()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                sha.update(chunk)
                received += len(chunk)
                if progress:
                    progress(received / total if total else None)
    except UpdateCancelled:
        partial.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(_("The download failed. Check your internet connection.")) from exc

    if release.asset_size and received != release.asset_size:
        partial.unlink(missing_ok=True)
        raise UpdateError(_("The download is incomplete. Try again."))
    if release.sha256 and sha.hexdigest() != release.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError(_("The downloaded file is corrupted (checksum mismatch). Try again."))
    partial.rename(target)
    return target


def install(package: Path) -> None:
    """Instala o pacote com pacman, pedindo a senha de administrador via polkit."""
    pkexec, pacman = shutil.which("pkexec"), shutil.which("pacman")
    if not pkexec or not pacman:
        raise UpdateError(_("Automatic installation requires pacman and pkexec."))
    try:
        try:
            result = subprocess.run([pkexec, pacman, "-U", "--noconfirm", str(package)],
                                    capture_output=True, text=True)
        except OSError as exc:
            raise UpdateError(str(exc)) from exc
        if result.returncode in (126, 127):
            # 126: janela de senha cancelada; 127: não autorizado / sem agente polkit
            detail = result.stderr.strip()
            raise UpdateError(_("Authorization was not granted.") + (f"\n{detail}" if detail else ""))
        if result.returncode != 0:
            output = (result.stderr.strip() or result.stdout.strip()).splitlines()
            raise UpdateError(_("pacman could not install the update:") + "\n" + "\n".join(output[-6:]))
    finally:
        package.unlink(missing_ok=True)
