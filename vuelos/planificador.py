"""Decide qué calendarios mirar cada día y recuerda los precios por fecha que ya vimos.

La rotación no necesita guardar estado: sale de la fecha, así que siempre avanza.
"""
import json
from calendar import monthrange
from datetime import date, timedelta
from itertools import product
from pathlib import Path

CADA_CUANTOS_PREFERIDOS = 3  # por cada 3 calendarios de mayo-junio, entra 1 de abril
ANTIGUEDAD_MAXIMA_DIAS = 21  # un precio más viejo que esto no se usa para elegir fechas


def rutas(cfg: dict) -> list[tuple[str, str]]:
    """BUE y GRU contra las dos ciudades de Japón (BUE, TYO y OSA agrupan sus aeropuertos)."""
    return [(origen, destino) for origen in ("BUE", cfg["viaje"]["origen_alternativo"]) for destino in ("TYO", "OSA")]


def ventanas(cfg: dict) -> list[tuple[str, str]]:
    """Parte el rango de salida en meses, porque un calendario abarca hasta 31 días."""
    desde = date.fromisoformat(cfg["fechas"]["salida_desde"])
    hasta = date.fromisoformat(cfg["fechas"]["salida_hasta"])
    resultado = []
    while desde <= hasta:
        fin_mes = desde.replace(day=monthrange(desde.year, desde.month)[1])
        fin = min(fin_mes, hasta)
        resultado.append((desde.isoformat(), fin.isoformat()))
        desde = fin + timedelta(days=1)
    return resultado


def ciclo_calendarios(cfg: dict) -> list[dict]:
    """Todas las combinaciones, con mayo-junio apareciendo antes y más seguido que abril."""
    combinaciones = [
        {"origen": o, "destino": d, "desde": v[0], "hasta": v[1], "estadia": e}
        for e, v, (o, d) in product(cfg["fechas"]["estadia_dias"], ventanas(cfg), rutas(cfg))
    ]
    preferida = cfg["fechas"]["salida_preferida_desde"]
    preferidas = [c for c in combinaciones if c["desde"] >= preferida]
    otras = [c for c in combinaciones if c["desde"] < preferida]
    ciclo = []
    for i, combinacion in enumerate(preferidas):
        ciclo.append(combinacion)
        if otras and (i + 1) % CADA_CUANTOS_PREFERIDOS == 0:
            ciclo.append(otras.pop(0))
    return ciclo + otras


def calendarios_del_dia(cfg: dict, dia: date, cantidad: int) -> list[dict]:
    ciclo = ciclo_calendarios(cfg)
    inicio = dia.toordinal() * cantidad
    return [ciclo[(inicio + i) % len(ciclo)] for i in range(min(cantidad, len(ciclo)))]


def barrido_inicial(cfg: dict) -> list[dict]:
    """Una foto de toda la ventana: cada ruta y cada mes, con la estadía del medio."""
    estadias = sorted(cfg["fechas"]["estadia_dias"])
    estadia = estadias[len(estadias) // 2]
    return [c for c in ciclo_calendarios(cfg) if c["estadia"] == estadia]


def calendarios_exploracion(cfg: dict) -> list[dict]:
    """Como el barrido, pero sin San Pablo-Osaka, que hasta ahora salió más caro que San Pablo-Tokio."""
    excluida = (cfg["viaje"]["origen_alternativo"], "OSA")
    return [c for c in barrido_inicial(cfg) if (c["origen"], c["destino"]) != excluida]


class Memoria:
    """Precios por fecha ya vistos, por ruta y estadía. Es la base del análisis de fechas."""

    def __init__(self, archivo: Path):
        self._archivo = archivo
        self.datos = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}

    def guardar_calendario(self, origen: str, destino: str, estadia: int, respuesta: dict, dia: date) -> int:
        """Devuelve cuántas fechas con precio trajo."""
        fechas = self.datos.setdefault(f"{origen}-{destino}", {}).setdefault(str(estadia), {})
        con_precio = 0
        for fila in respuesta.get("dates") or []:
            salida = fila["departure_date"]
            if fila.get("price"):
                fechas[salida] = {"regreso": fila.get("return_date"), "precio": fila["price"]["amount"], "visto": dia.isoformat()}
                con_precio += 1
            else:
                fechas.pop(salida, None)  # ya no hay tarifa: no conviene seguir eligiéndola
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        self._archivo.write_text(json.dumps(self.datos, indent=1), encoding="utf-8")
        return con_precio

    def mejores_fechas(self, ruta: str, dia: date) -> list[dict]:
        """Las fechas de una ruta de más barata a más cara, sin datos demasiado viejos."""
        limite = (dia - timedelta(days=ANTIGUEDAD_MAXIMA_DIAS)).isoformat()
        filas = [
            {"ruta": ruta, "estadia": int(estadia), "salida": salida, **fila}
            for estadia, fechas in self.datos.get(ruta, {}).items()
            for salida, fila in fechas.items()
            if fila["visto"] >= limite
        ]
        return sorted(filas, key=lambda f: f["precio"])
