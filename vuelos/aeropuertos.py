"""Nombre, ciudad y país de cada aeropuerto, a partir de vuelos/datos/aeropuertos.json (OurAirports)."""
import json
from functools import cache
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parent / "datos" / "aeropuertos.json"


@cache
def _tabla() -> dict:
    return json.loads(ARCHIVO.read_text(encoding="utf-8")) if ARCHIVO.exists() else {}


def describir(codigo: str | None) -> dict:
    """Si el código no está en la tabla, devuelve el código solo: la página sigue funcionando."""
    datos = _tabla().get(codigo or "", {})
    return {
        "codigo": codigo,
        "nombre": datos.get("nombre", codigo),
        "ciudad": datos.get("ciudad", codigo),
        "pais": datos.get("pais", ""),
        "pais_codigo": datos.get("pais_codigo", ""),
    }


def paradas_de(tramo: dict) -> list[dict]:
    """Las escalas de un tramo. Los datos viejos no las guardaban: se arman desde la ruta, sin duración."""
    if "paradas" in tramo:
        return tramo["paradas"]
    return [{"aeropuerto": codigo, "sale_de": None, "minutos": None, "noche": False, "cambio_pasaje": False}
            for codigo in tramo["ruta"][1:-1]]


def con_lugares(parada: dict) -> dict:
    lugar = describir(parada["aeropuerto"])
    return {**parada, "lugar": lugar, "lugar_salida": describir(parada["sale_de"]) if parada.get("sale_de") else None}


def duracion(minutos: int | None) -> str:
    if minutos is None:
        return ""
    horas, resto = divmod(int(minutos), 60)
    return f"{horas} h {resto} min" if horas and resto else (f"{horas} h" if horas else f"{resto} min")
