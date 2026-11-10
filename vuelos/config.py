"""Lee las preferencias de config.yaml y las claves de .env o del entorno."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


def cargar_config() -> dict:
    with open(RAIZ / "config.yaml", encoding="utf-8") as archivo:
        return yaml.safe_load(archivo)


def clave(nombre: str) -> str | None:
    """Devuelve una clave, o None si no está cargada."""
    load_dotenv(RAIZ / ".env")
    return (os.environ.get(nombre) or "").strip() or None
