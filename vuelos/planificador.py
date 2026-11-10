"""Decide qué calendarios mirar cada día y recuerda los precios por fecha que ya vimos.

La rotación no necesita guardar estado: sale de la fecha, así que siempre avanza.
"""
import json
from calendar import monthrange
from datetime import date, timedelta
from itertools import product
from pathlib import Path

ANTIGUEDAD_MAXIMA_DIAS = 35  # un precio más viejo que esto no se usa (los meses no preferidos se revisan cada ~27 días)
MARGEN_PARA_SALIR = 7         # no se buscan meses que terminan antes de una semana


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


def es_preferida(cfg: dict, salida: str) -> bool:
    fechas = cfg["fechas"]
    return fechas["salida_preferida_desde"] <= salida[:10] <= fechas.get("salida_preferida_hasta", fechas["salida_hasta"])


def _estadia_del_medio(cfg: dict) -> int:
    estadias = sorted(cfg["fechas"]["estadia_dias"])
    return estadias[len(estadias) // 2]


def calendarios_preferidos(cfg: dict) -> list[dict]:
    """Abril-junio: todas las rutas y estadías. San Pablo-Osaka, que suele salir más caro, solo con la estadía del medio."""
    medio, alternativa = _estadia_del_medio(cfg), (cfg["viaje"]["origen_alternativo"], "OSA")
    return [{"origen": o, "destino": d, "desde": v[0], "hasta": v[1], "estadia": e}
            for v, e, (o, d) in product(ventanas(cfg), cfg["fechas"]["estadia_dias"], rutas(cfg))
            if es_preferida(cfg, v[0]) and ((o, d) != alternativa or e == medio)]


def calendarios_resto(cfg: dict) -> list[dict]:
    """El resto del año: la estadía del medio y sin San Pablo-Osaka, para que la vuelta no tarde demasiado."""
    medio, alternativa = _estadia_del_medio(cfg), (cfg["viaje"]["origen_alternativo"], "OSA")
    # Se alternan los meses: así cada día cae en una parte distinta del año.
    por_mes = [[{"origen": o, "destino": d, "desde": v[0], "hasta": v[1], "estadia": medio}
                for (o, d) in rutas(cfg) if (o, d) != alternativa]
               for v in ventanas(cfg) if not es_preferida(cfg, v[0])]
    return [c for grupo in zip(*por_mes) for c in grupo] if por_mes else []


def ciclo_calendarios(cfg: dict) -> list[dict]:
    """Todas las combinaciones que se revisan, primero las de abril-junio."""
    return calendarios_preferidos(cfg) + calendarios_resto(cfg)


def _sin_pasados(calendarios: list[dict], dia: date) -> list[dict]:
    limite = (dia + timedelta(days=MARGEN_PARA_SALIR)).isoformat()
    return [c for c in calendarios if c["hasta"] >= limite]


def calendarios_del_dia(cfg: dict, dia: date, cantidad: int) -> list[dict]:
    """Por día: todos menos uno de abril-junio, y uno del resto del año. La rotación sale de la fecha."""
    preferidos = _sin_pasados(calendarios_preferidos(cfg), dia)
    resto = _sin_pasados(calendarios_resto(cfg), dia)
    de_preferidos = cantidad - 1 if resto and preferidos else cantidad
    elegidos = []
    if preferidos:
        inicio = dia.toordinal() * de_preferidos
        elegidos += [preferidos[(inicio + i) % len(preferidos)] for i in range(min(de_preferidos, len(preferidos)))]
    if resto:
        faltan = cantidad - len(elegidos)
        inicio = dia.toordinal() * faltan
        elegidos += [resto[(inicio + i) % len(resto)] for i in range(min(faltan, len(resto)))]
    return elegidos


def barrido_inicial(cfg: dict) -> list[dict]:
    """Una foto de toda la ventana: cada ruta y cada mes, con la estadía del medio."""
    estadia = _estadia_del_medio(cfg)
    return [c for c in ciclo_calendarios(cfg) if c["estadia"] == estadia]


def calendarios_exploracion(cfg: dict) -> list[dict]:
    """Como el barrido en abril-junio, pero sin San Pablo-Osaka, que hasta ahora salió más caro que San Pablo-Tokio."""
    excluida = (cfg["viaje"]["origen_alternativo"], "OSA")
    return [c for c in barrido_inicial(cfg) if (c["origen"], c["destino"]) != excluida and es_preferida(cfg, c["desde"])]


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
