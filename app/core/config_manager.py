import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_config_dir() -> Path:
    """Returns the platform-specific configuration directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    
    cfg_dir = Path(base) / "slidecast"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir


def get_config_file_path() -> Path:
    return get_config_dir() / "config.json"


def load_config() -> dict:
    cfg_path = get_config_file_path()
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(data: dict):
    cfg_path = get_config_file_path()
    try:
        current = load_config()
        current.update(data)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Erro ao salvar configurações: %s", exc)


def get_gemini_api_key() -> Optional[str]:
    # 1. Environment variable
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # 2. Config file
    cfg = load_config()
    key = cfg.get("gemini_api_key")
    if key and isinstance(key, str) and key.strip():
        return key.strip()

    return None


def set_gemini_api_key(key: str):
    save_config({"gemini_api_key": key.strip()})


def get_openai_api_key() -> Optional[str]:
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    cfg = load_config()
    key = cfg.get("openai_api_key")
    if key and isinstance(key, str) and key.strip():
        return key.strip()
    return None


def set_openai_api_key(key: str):
    save_config({"openai_api_key": key.strip()})


def get_image_provider() -> str:
    cfg = load_config()
    return cfg.get("image_provider", "auto")


def set_image_provider(provider: str):
    save_config({"image_provider": provider})


def get_elevenlabs_api_key() -> Optional[str]:
    env_key = os.environ.get("ELEVENLABS_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    cfg = load_config()
    key = cfg.get("elevenlabs_api_key")
    if key and isinstance(key, str) and key.strip():
        return key.strip()
    return None


def set_elevenlabs_api_key(key: str):
    save_config({"elevenlabs_api_key": key.strip()})


def get_replicate_api_key() -> Optional[str]:
    env_key = os.environ.get("REPLICATE_API_TOKEN") or os.environ.get("REPLICATE_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    cfg = load_config()
    key = cfg.get("replicate_api_key")
    if key and isinstance(key, str) and key.strip():
        return key.strip()
    return None


def set_replicate_api_key(key: str):
    save_config({"replicate_api_key": key.strip()})


def get_avatar_engine() -> str:
    cfg = load_config()
    return cfg.get("avatar_engine", "cloud")


def set_avatar_engine(engine: str):
    save_config({"avatar_engine": engine})


def get_active_clone_id() -> Optional[str]:
    cfg = load_config()
    return cfg.get("active_clone_id")


def set_active_clone_id(clone_id: str):
    save_config({"active_clone_id": clone_id})

