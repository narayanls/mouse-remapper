"""Leitura e gravação da configuração em ~/.config/mouse-remapper/config.json.

Formato:
{
  "version": 1,
  "devices": {
    "1d57:fa60": {                      # vendor:product do mouse
      "name": "Fortrek Gaming Mouse",
      "mappings": [
        {"button": 275, "steps": [[29, 46]]},          # BTN_SIDE -> Ctrl+C
        {"button": 276, "steps": [[29, 46], [29, 47]]} # sequência de etapas
      ]
    }
  }
}
"""

import json
import os
import tempfile
from pathlib import Path

CONFIG_VERSION = 1


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "mouse-remapper"


def config_file() -> Path:
    return config_dir() / "config.json"


def empty_config() -> dict:
    return {"version": CONFIG_VERSION, "devices": {}}


def _clean_mapping(m) -> dict | None:
    try:
        button = int(m["button"])
        steps = [[int(k) for k in step] for step in m.get("steps", []) if step]
    except (KeyError, TypeError, ValueError):
        return None
    if not steps:
        return None
    return {"button": button, "steps": steps}


def load() -> dict:
    path = config_file()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return empty_config()
    except (OSError, json.JSONDecodeError):
        # Arquivo corrompido: preserva uma cópia e começa do zero.
        try:
            path.rename(path.with_suffix(".json.bak"))
        except OSError:
            pass
        return empty_config()

    cfg = empty_config()
    for key, dev in (raw.get("devices") or {}).items():
        if not isinstance(dev, dict):
            continue
        maps = [c for c in (_clean_mapping(m) for m in dev.get("mappings", [])) if c]
        cfg["devices"][str(key)] = {"name": str(dev.get("name", key)), "mappings": maps}
    return cfg


def save(cfg: dict) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    data = {"version": CONFIG_VERSION, "devices": cfg.get("devices", {})}
    # Escrita atômica: arquivo temporário + rename.
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, config_file())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def profiles(cfg: dict) -> dict:
    """Retorna {chave_do_dispositivo: [mapeamentos]} apenas com perfis não vazios."""
    return {k: d["mappings"] for k, d in cfg.get("devices", {}).items() if d.get("mappings")}
