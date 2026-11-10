"""Búsqueda diaria: gasta las consultas del día y guarda data/resultados/AAAA-MM-DD.json.

Uso:
  .venv/bin/python -m vuelos.buscar              corrida normal, respeta los límites diarios
  .venv/bin/python -m vuelos.buscar --solo-plan  muestra qué consultaría, sin gastar nada
  .venv/bin/python -m vuelos.buscar --barrido    una sola vez: foto de toda la ventana de fechas
  .venv/bin/python -m vuelos.buscar --explorar   una sola vez: lo más barato sin límite de escalas ni de horas

Si se corre dos veces el mismo día, no repite lo que ya consultó.
"""
import argparse
import json
from collections import Counter
from datetime import date, timedelta

from . import analisis, evaluar, planificador, promociones, publicar, stopover
from .config import RAIZ, cargar_config, clave
from .consultas import Contador, ContadorConReserva, CupoDelDia
from .fechas import ahora, hoy
from .fuentes import ignav as modulo_ignav
from .fuentes import serpapi as modulo_serpapi
from .fuentes.base import FuenteError, SinCupo
from .fuentes.ignav import Ignav
from .fuentes.serpapi import SerpApi

DATOS = RAIZ / "data"
CALENDARIOS_POR_DIA = 3
MAXIMO_OPCIONES_GUARDADAS = 60
DOS_IDAS_SI_HAY = 7  # con este cupo de SerpApi se completan 2 idas en vez de 1
AEROPUERTOS = {"BUE": "EZE,AEP", "TYO": "NRT,HND", "OSA": "KIX,ITM"}


class Corrida:
    def __init__(self, cfg: dict, dia: date, contador: Contador, memoria: planificador.Memoria, carpeta: str = "resultados"):
        self.cfg = cfg
        self.dia = dia
        self.contador = contador
        self.memoria = memoria
        self.archivo = DATOS / carpeta / f"{dia.isoformat()}.json"
        previo = json.loads(self.archivo.read_text(encoding="utf-8")) if self.archivo.exists() else {}
        self.opciones: list[dict] = previo.get("opciones", [])
        self.descartes: Counter = Counter(previo.get("descartes", {}))
        self.hechas: list[str] = previo.get("consultas_hechas", [])
        self.errores: list[str] = previo.get("errores", [])
        self.san_pablo: list[dict] = previo.get("san_pablo", [])
        self.pedidos: list[dict] = previo.get("pedidos", [])

    def tarea(self, nombre: str, funcion) -> None:
        """Corre una consulta una sola vez por día. Si falla, anota el error y la app sigue."""
        if nombre in self.hechas:
            return
        try:
            funcion()
        except SinCupo:
            raise
        except FuenteError as error:
            self.errores.append(f"{nombre}: {error}")
        else:
            self.hechas.append(nombre)
            self.guardar()

    def sumar(self, opciones: list[dict]) -> None:
        validas = []
        for opcion in opciones:
            motivo = evaluar.motivo_descarte(opcion, self.cfg["restricciones"])
            if motivo:
                self.descartes[motivo] += 1
            else:
                validas.append(evaluar.completar(opcion, self.cfg))
        self.opciones = evaluar.juntar(self.opciones + validas)[:MAXIMO_OPCIONES_GUARDADAS]

    def guardar(self) -> None:
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self.archivo.write_text(json.dumps({
            "fecha": self.dia.isoformat(),
            "actualizado": ahora(),
            "opciones": self.opciones,
            "descartes": dict(self.descartes),
            "san_pablo": self.san_pablo,
            "pedidos": self.pedidos,
            "consultas_hechas": self.hechas,
            "errores": self.errores,
            "cupo": self.contador.resumen(),
        }, indent=1, ensure_ascii=False), encoding="utf-8")

    def guardar_crudo(self, nombre: str, respuesta: dict) -> None:
        """Respuesta completa, para revisarla sin gastar otra consulta. No se sube a GitHub."""
        carpeta = DATOS / "crudo"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{nombre}.json").write_text(json.dumps(respuesta, indent=1, ensure_ascii=False), encoding="utf-8")

    def mejor_fecha(self, *rutas: str) -> dict | None:
        filas = [fila for ruta in rutas for fila in self.memoria.mejores_fechas(ruta, self.dia)
                 if fila["estadia"] in self.cfg["fechas"]["estadia_dias"]]
        return min(filas, key=lambda f: f["precio"], default=None)

    def regreso(self, fila: dict) -> str:
        return fila.get("regreso") or (date.fromisoformat(fila["salida"]) + timedelta(days=fila["estadia"])).isoformat()


# ---------------------------------------------------------------- Ignav

def correr_ignav(c: Corrida, barrido: bool) -> None:
    fuente = Ignav(clave("IGNAV_API_KEY"), c.contador, c.cfg["viaje"]["pasajeros"], c.cfg["equipaje"]["carry_on"],
                   c.cfg["equipaje"]["despachadas"], c.cfg["restricciones"]["max_escalas"])
    calendarios = planificador.barrido_inicial(c.cfg) if barrido else planificador.calendarios_del_dia(c.cfg, c.dia, CALENDARIOS_POR_DIA)
    for calendario in calendarios:
        _calendario(c, fuente, calendario)
    for nombre, funcion in _exactas_ignav(c, fuente):
        c.tarea(nombre, funcion)
    _links_de_compra(c, fuente)


def candidatas_para_links(opciones: list[dict]) -> list[dict]:
    """La mejor del día y todas las que llegan a 👀 casi o mejor, de más barata a más cara."""
    ordenadas = sorted(opciones, key=lambda o: o["precio_con_valijas"])
    elegidas = ordenadas[:1] + [o for o in ordenadas[1:] if o["categoria"] != evaluar.CARO]
    return [o for o in elegidas if o.get("ignav_ids") or o.get("ignav_id")]


def _links_de_compra(c: Corrida, fuente: Ignav) -> None:
    """Pide dónde comprar las mejores opciones. San Pablo son 2 pasajes: gasta 2 consultas."""
    maximo = c.cfg["consultas"]["ignav"].get("links_por_dia", 0)
    gastados = sum(len(h.split(" ", 1)[1].split("+")) for h in c.hechas if h.startswith("link "))
    for opcion in candidatas_para_links(c.opciones):
        ids = opcion.get("ignav_ids") or [opcion["ignav_id"]]
        if opcion.get("links_compra") or gastados + len(ids) > maximo:
            continue

        def consultar(opcion=opcion, ids=ids) -> None:
            todos, precios = [], []
            for numero, ignav_id in enumerate(ids):
                respuesta = fuente.links_de_compra(ignav_id)
                precio = ((respuesta.get("itinerary") or {}).get("price") or {})
                if precio.get("currency") == "USD" and precio.get("amount"):
                    precios.append(precio["amount"])
                for link in modulo_ignav.links(respuesta):
                    if len(ids) > 1:
                        link["pasaje"] = "Desde San Pablo" if numero == 0 else "Buenos Aires–San Pablo"
                    todos.append(link)
            opcion["links_compra"] = todos
            if len(precios) == len(ids):
                # El pedido de links trae el precio de ahora: la opción queda con ese precio confirmado.
                opcion.update(evaluar.confirmar_precio(opcion, precios, c.dia.isoformat(), c.cfg))
            print(f"  links de compra para USD {opcion['precio_con_valijas']}: {len(todos)}")
        c.tarea(f"link {'+'.join(ids)}", consultar)
        gastados += len(ids)


def _calendario(c: Corrida, fuente: Ignav, cal: dict) -> None:
    def consultar() -> None:
        escalas = _escalas_san_pablo(c) if cal["origen"] != "BUE" else c.cfg["restricciones"]["max_escalas"]
        respuesta = fuente.calendario(cal["origen"], cal["destino"], cal["desde"], cal["hasta"], cal["estadia"], escalas)
        cantidad = c.memoria.guardar_calendario(cal["origen"], cal["destino"], cal["estadia"], respuesta, c.dia)
        print(f"  calendario {cal['origen']}-{cal['destino']} {cal['desde'][:7]} {cal['estadia']} días: {cantidad} fechas con precio")
    c.tarea(f"calendario {cal['origen']}-{cal['destino']} {cal['desde'][:7]} {cal['estadia']}d", consultar)


def _escalas_san_pablo(c: Corrida) -> int | None:
    """En San Pablo, el cambio de avión a Buenos Aires ya cuenta como una escala."""
    maximo = c.cfg["restricciones"]["max_escalas"]
    return None if maximo is None else maximo - 1


def _exacta(c: Corrida, fuente: Ignav, fila: dict) -> tuple:
    destino = fila["ruta"].split("-")[1]
    regreso = c.regreso(fila)
    nombre = f"exacta BUE-{destino} {fila['salida']} {regreso}"

    def consultar() -> None:
        respuesta = fuente.ida_y_vuelta("BUE", destino, fila["salida"], regreso)
        c.guardar_crudo(nombre.replace(" ", "_"), respuesta)
        c.sumar([modulo_ignav.normalizar(i, "ida_y_vuelta") for i in respuesta.get("itineraries") or []])
        print(f"  exacta BUE-{destino} {fila['salida']} a {regreso}: {len(respuesta.get('itineraries') or [])} itinerarios")
    return nombre, consultar


def _open_jaw(c: Corrida, fuente: Ignav, llega: str, vuelve: str, fila: dict) -> tuple:
    regreso = c.regreso(fila)
    nombre = f"open-jaw BUE-{llega}/{vuelve}-BUE {fila['salida']} {regreso}"

    def consultar() -> None:
        respuesta = fuente.open_jaw("BUE", llega, vuelve, "BUE", fila["salida"], regreso)
        c.guardar_crudo(nombre.replace(" ", "_").replace("/", "_"), respuesta)
        c.sumar([modulo_ignav.normalizar(i, "open_jaw") for i in respuesta.get("itineraries") or []])
        print(f"  open-jaw BUE-{llega}/{vuelve}-BUE {fila['salida']} a {regreso}: {len(respuesta.get('itineraries') or [])} itinerarios")
    return nombre, consultar


def correr_exploracion(c: Corrida) -> None:
    """Sin límite de escalas ni de horas: 9 calendarios y hasta 6 búsquedas exactas, 15 consultas como máximo."""
    fuente = Ignav(clave("IGNAV_API_KEY"), c.contador, c.cfg["viaje"]["pasajeros"], c.cfg["equipaje"]["carry_on"],
                   c.cfg["equipaje"]["despachadas"], None)
    for calendario in planificador.calendarios_exploracion(c.cfg):
        _calendario(c, fuente, calendario)
    alternativo = c.cfg["viaje"]["origen_alternativo"]
    tokio = [f for f in c.memoria.mejores_fechas("BUE-TYO", c.dia) if f["estadia"] in c.cfg["fechas"]["estadia_dias"]]
    osaka = c.mejor_fecha("BUE-OSA")
    mejor = c.mejor_fecha("BUE-TYO", "BUE-OSA")
    san_pablo = c.mejor_fecha(f"{alternativo}-TYO")
    tareas = [_exacta(c, fuente, fila) for fila in tokio[:2]]
    if osaka:
        tareas.append(_exacta(c, fuente, osaka))
    if mejor:
        tareas.append(_open_jaw(c, fuente, "TYO", "OSA", mejor))
    if mejor and san_pablo:
        tareas.append(_tarea_san_pablo(c, fuente, san_pablo, mejor, alternativo))
    for nombre, funcion in tareas:
        c.tarea(nombre, funcion)


def _exactas_ignav(c: Corrida, fuente: Ignav) -> list[tuple]:
    """Hasta 3 búsquedas exactas sobre las fechas más baratas, para que siempre queden consultas para los links de compra.

    San Pablo va día por medio, o todos los días si parece más barato.
    """
    tokio, osaka = c.mejor_fecha("BUE-TYO"), c.mejor_fecha("BUE-OSA")
    mejor = c.mejor_fecha("BUE-TYO", "BUE-OSA")
    alternativo = c.cfg["viaje"]["origen_alternativo"]
    san_pablo = c.mejor_fecha(f"{alternativo}-TYO", f"{alternativo}-OSA")
    tareas = []

    if mejor and san_pablo and (c.dia.toordinal() % 2 == 0 or san_pablo["precio"] < mejor["precio"]):
        tareas.append(_exacta(c, fuente, mejor))
        tareas.append(_tarea_san_pablo(c, fuente, san_pablo, mejor, alternativo))  # 1 o 2 consultas
        return tareas
    if tokio:
        tareas.append(_exacta(c, fuente, tokio))
    if osaka:
        tareas.append(_exacta(c, fuente, osaka))
    if mejor:
        # Un día llega a Tokio y vuelve de Osaka; al otro, al revés.
        llega, vuelve = ("TYO", "OSA") if c.dia.toordinal() % 2 else ("OSA", "TYO")
        tareas.append(_open_jaw(c, fuente, llega, vuelve, mejor))
    return tareas


def _tarea_san_pablo(c: Corrida, fuente: Ignav, fila: dict, mejor: dict, alternativo: str) -> tuple:
    """Busca el pasaje desde San Pablo y gasta el tramo corto solo si puede convenir."""
    destino = fila["ruta"].split("-")[1]
    regreso = c.regreso(fila)
    escalas = _escalas_san_pablo(c)

    def consultar() -> None:
        respuesta = fuente.ida_y_vuelta(alternativo, destino, fila["salida"], regreso, escalas)
        c.guardar_crudo("san_pablo_largo", respuesta)
        largas = [modulo_ignav.normalizar(i, "desde_san_pablo") for i in respuesta.get("itineraries") or []]
        largas = [o for o in largas if not evaluar.motivo_descarte(o, c.cfg["restricciones"])]
        largas.sort(key=lambda o: o["precio_total"])
        precio_bue = min((o["precio_total"] for o in c.opciones if o["tipo"] != "san_pablo"), default=mejor["precio"])
        info = {"salida": fila["salida"], "regreso": regreso, "destino": destino,
                "mejor_desde_san_pablo": largas[0]["precio_total"] if largas else None,
                "mejor_desde_buenos_aires": precio_bue, "tramo_corto": None, "total": None}
        c.san_pablo.append(info)
        print(f"  San Pablo {alternativo}-{destino} {fila['salida']}: {info['mejor_desde_san_pablo']} (desde BUE: {precio_bue})")
        if not largas or largas[0]["precio_total"] >= precio_bue:
            return  # sin sumar el tramo a Buenos Aires ya es más caro: no gastamos otra consulta
        ida, vuelta = _fechas_tramo_corto(largas[0])
        corta = fuente.ida_y_vuelta("BUE", alternativo, ida, vuelta, 0)
        c.guardar_crudo("san_pablo_corto", corta)
        cortos = [modulo_ignav.normalizar(i, "tramo_corto") for i in corta.get("itineraries") or []]
        cortos = [o for o in cortos if not evaluar.motivo_descarte(o, c.cfg["restricciones"])]
        validas, descartada = evaluar.combinaciones_san_pablo(largas, cortos, c.cfg["restricciones"])
        c.sumar(validas)
        if validas:
            mas_barata = min(validas, key=lambda o: o["precio_total"])
            info["tramo_corto"] = mas_barata["desglose"]["buenos_aires_san_pablo"]
            info["total"] = mas_barata["precio_total"]
        info["validas"] = len(validas)
        info["mejor_descartada"] = descartada
        print(f"  San Pablo: {len(validas)} combinaciones válidas, total {info['total']}; mejor descartada: {descartada}")
    return f"exacta {alternativo}-{destino} {fila['salida']} {regreso}", consultar


def _fechas_tramo_corto(larga: dict) -> tuple[str, str]:
    """Si el vuelo largo sale temprano, se viaja el día anterior; si llega tarde, se vuelve al otro día."""
    sale = larga["tramos"][0]["salida"]
    llega = larga["tramos"][1]["llegada"]
    ida = date.fromisoformat(sale[:10]) - timedelta(days=1 if int(sale[11:13]) < 12 else 0)
    vuelta = date.fromisoformat(llega[:10]) + timedelta(days=1 if int(llega[11:13]) >= 18 else 0)
    return ida.isoformat(), vuelta.isoformat()


# ---------------------------------------------------------------- SerpApi

def correr_serpapi(c: Corrida) -> None:
    fuente = SerpApi(clave("SERPAPI_API_KEY"), c.contador, c.cfg["viaje"]["pasajeros"],
                     c.cfg["equipaje"]["carry_on"], c.cfg["restricciones"]["max_escalas"])
    try:
        restantes = fuente.consultas_restantes()
    except FuenteError as error:
        c.errores.append(f"cupo de SerpApi: {error}")
    else:
        if restantes is not None:
            c.contador.limitar("serpapi", restantes)

    tokio, osaka = c.mejor_fecha("BUE-TYO"), c.mejor_fecha("BUE-OSA")
    mejor = c.mejor_fecha("BUE-TYO", "BUE-OSA")
    if not mejor:
        print("  SerpApi: todavía no hay fechas en memoria para controlar")
        return

    if tokio:
        _ida_y_vuelta_serpapi(c, fuente, tokio)
    _open_jaw_serpapi(c, fuente, mejor)
    if osaka:
        _ida_y_vuelta_serpapi(c, fuente, osaka)


def _recorrer(c: Corrida, pedir_paso, tipo: str, pasos: int, ramas: int, acepta=None) -> None:
    """Sigue los pasos de SerpApi hasta el último, que es el que trae el precio real.

    `acepta(tramo)` deja solo algunos tramos (por ejemplo, los que vuela la aerolínea del stopover).
    """
    acepta = acepta or (lambda tramo: True)
    costo = 1 + (ramas if pasos == 2 else pasos - 1)
    if c.contador.disponibles("serpapi") < costo:
        raise CupoDelDia("serpapi: no alcanza para completar el precio real")

    def nivel(previos: list[dict], token: str | None, numero: int) -> None:
        opciones = modulo_serpapi.opciones(pedir_paso(token))
        if numero == pasos - 1:
            c.sumar([modulo_serpapi.armar(tipo, previos + [modulo_serpapi.tramo(o)], o.get("price"))
                     for o in opciones if acepta(modulo_serpapi.tramo(o))])
            return
        candidatas = [o for o in opciones if o.get("departure_token") and o.get("price")
                      and evaluar.tramo_cumple(modulo_serpapi.tramo(o), c.cfg["restricciones"]) and acepta(modulo_serpapi.tramo(o))]
        candidatas.sort(key=lambda o: o["price"])
        for opcion in candidatas[:ramas if numero == 0 else 1]:
            nivel(previos + [modulo_serpapi.tramo(opcion)], opcion["departure_token"], numero + 1)

    nivel([], None, 0)


def _ida_y_vuelta_serpapi(c: Corrida, fuente: SerpApi, fila: dict) -> None:
    destino = fila["ruta"].split("-")[1]
    regreso = c.regreso(fila)
    ramas = 2 if c.contador.disponibles("serpapi") >= DOS_IDAS_SI_HAY else 1

    def consultar() -> None:
        _recorrer(c, lambda token: fuente.ida_y_vuelta(AEROPUERTOS["BUE"], AEROPUERTOS[destino], fila["salida"], regreso, token),
                  "ida_y_vuelta", 2, ramas)
        print(f"  control SerpApi BUE-{destino} {fila['salida']} a {regreso}: listo")
    c.tarea(f"serpapi BUE-{destino} {fila['salida']} {regreso}", consultar)


def _open_jaw_serpapi(c: Corrida, fuente: SerpApi, fila: dict) -> None:
    regreso = c.regreso(fila)
    tramos = [(AEROPUERTOS["BUE"], AEROPUERTOS["TYO"], fila["salida"]), (AEROPUERTOS["OSA"], AEROPUERTOS["BUE"], regreso)]

    def consultar() -> None:
        _recorrer(c, lambda token: fuente.multidestino(tramos, token), "open_jaw", 2, 1)
        print(f"  control SerpApi open-jaw {fila['salida']} a {regreso}: listo")
    c.tarea(f"serpapi open-jaw {fila['salida']} {regreso}", consultar)


# ---------------------------------------------------------------- Stopovers (se piden a mano)

def correr_stopover(c: Corrida, ciudad: str, dias: int, cuando: str, mes: str | None) -> None:
    """Prueba hasta 2 salidas para el stopover pedido. Cada una gasta 3 consultas de SerpApi."""
    lugar = c.cfg["stopovers"][ciudad]
    fuente = SerpApi(clave("SERPAPI_API_KEY"), c.contador, c.cfg["viaje"]["pasajeros"],
                     c.cfg["equipaje"]["carry_on"], c.cfg["restricciones"]["max_escalas"])
    try:
        restantes = fuente.consultas_restantes()
    except FuenteError as error:
        c.errores.append(f"cupo de SerpApi: {error}")
    else:
        if restantes is not None:
            c.contador.limitar("serpapi", restantes)
    c.contador.limitar("stopover", c.cfg["consultas"]["stopover"]["por_busqueda"])

    filas = [f for ruta in ("BUE-TYO", "BUE-OSA") for f in c.memoria.mejores_fechas(ruta, c.dia)]
    elegidas = stopover.salidas(filas, mes, lambda s: planificador.es_preferida(c.cfg, s), c.dia)
    pedido = {"ciudad": ciudad, "dias": dias, "cuando": cuando, "mes": mes, "pedido": ahora(), "salidas": [], "opciones": 0, "errores": []}
    c.pedidos.append(pedido)
    errores_antes = len(c.errores)
    if not elegidas:
        pedido["errores"].append("No hay fechas para ese mes en el calendario de precios.")
    for fila in elegidas:
        japon = AEROPUERTOS[fila["ruta"].split("-")[1]]
        partes = stopover.tramos(date.fromisoformat(fila["salida"]), dias, cuando, c.cfg["restricciones"]["dias_en_japon"],
                                 AEROPUERTOS["BUE"], lugar["aeropuerto"], japon)
        pedido["salidas"].append(fila["salida"])

        def consultar(partes=partes) -> None:
            # Google Flights devuelve vacío si se le pide solo una aerolínea: se filtra acá, tramo por tramo.
            _recorrer(c, lambda token: fuente.multidestino(partes, token), stopover.tipo(ciudad, cuando), 3, 1,
                      acepta=lambda tramo: lugar["aerolinea_nombre"] in tramo["aerolineas"])
            print(f"  stopover {lugar['nombre']} {dias} días a la {cuando}, sale {partes[0][2]}: listo")
        try:
            c.tarea(f"stopover {ciudad} {cuando} {dias}d {fila['salida']}", consultar)
        except CupoDelDia as aviso:
            pedido["errores"].append(f"Se terminó el cupo: {aviso}")
            break
    # Las opciones de este pedido: misma ciudad y sentido, saliendo en alguna de las fechas probadas.
    pedido["opciones"] = sum(1 for o in c.opciones if o["tipo"] == stopover.tipo(ciudad, cuando)
                             and o["tramos"][0]["salida"][:10] in pedido["salidas"])
    pedido["errores"] += c.errores[errores_antes:]
    c.guardar()


# ---------------------------------------------------------------- Corrida

def correr_fuente(c: Corrida, nombre: str, funcion) -> None:
    """Una fuente que falla no frena a la otra: el error queda para mostrarlo en el dashboard."""
    print(f"\n{nombre}")
    try:
        funcion()
    except CupoDelDia as aviso:
        print(f"  {aviso}: sigue en la próxima corrida")
    except FuenteError as error:
        c.errores.append(str(error))
        print(f"  ERROR: {error}")


def mostrar_resumen(c: Corrida) -> None:
    print(f"\n=== RESULTADOS {c.dia} ({len(c.opciones)} opciones) ===")
    for opcion in c.opciones[:8]:
        print(f"\n{opcion['categoria']} USD {opcion['precio_con_valijas']} los {c.cfg['viaje']['pasajeros']} con valijas "
              f"(USD {opcion['por_persona_con_valijas']} c/u) | pasaje USD {opcion['precio_total']:.0f} "
              f"+ valijas USD {opcion['valijas_estimadas']} | {opcion['tipo']} | {opcion['dias_en_japon']} días en Japón "
              f"| {opcion['precios_por_fuente']}")
        if opcion["excede_limites"]:
            print(f"   ⚠️ {opcion['excede_limites']}")
        for tramo in opcion["tramos"]:
            print(f"   {'-'.join(tramo['ruta'])} | {', '.join(tramo['aerolineas'])} | {tramo['escalas']} escala(s) | {tramo['horas']} h | {tramo['salida']}")
    print(f"\nDescartadas: {dict(c.descartes) or 'ninguna'}")
    print(f"Errores: {c.errores or 'ninguno'}")
    print(f"Consultas: {c.contador.resumen()}")


def configuracion_exploracion(cfg: dict) -> dict:
    """Saca escalas y horas, pero guarda los límites normales para marcar lo que los supera."""
    originales = cfg["restricciones"]
    return {**cfg, "restricciones_originales": originales,
            "restricciones": {**originales, "max_escalas": None, "max_horas_por_tramo": None}}


def main() -> None:
    parser =argparse.ArgumentParser(description="Busca vuelos y guarda los resultados del día.")
    parser.add_argument("--solo-plan", action="store_true", help="muestra el plan sin gastar consultas")
    parser.add_argument("--barrido", action="store_true", help="una sola vez: toda la ventana, por encima del límite diario de Ignav")
    parser.add_argument("--explorar", action="store_true", help="una sola vez: sin límite de escalas ni de horas, hasta 15 consultas de Ignav")
    parser.add_argument("--stopover", choices=("madrid", "estambul"), help="busca un stopover en esa ciudad (lo pedís desde la página)")
    parser.add_argument("--dias", type=int, default=3, help="días en la ciudad del stopover")
    parser.add_argument("--cuando", choices=("ida", "vuelta"), default="ida", help="stopover a la ida o a la vuelta")
    parser.add_argument("--mes", default=None, help="mes de salida AAAA-MM (si no, los meses preferidos)")
    args = parser.parse_args()

    cfg = cargar_config()
    dia = hoy()
    sin_limite = ("ignav",) if args.barrido or args.explorar else ()
    contador = Contador(DATOS / "consultas.json", cfg["consultas"], dia, sin_limite_diario=sin_limite)

    if args.stopover:
        # El tope diario de SerpApi es para la búsqueda diaria: los stopovers tienen su propio tope por mes.
        reserva = ContadorConReserva(Contador(DATOS / "consultas.json", cfg["consultas"], dia, sin_limite_diario=("serpapi",)),
                                     "serpapi", "stopover")
        mes = args.mes if args.mes and args.mes != "cualquiera" else None
        corrida = Corrida(cfg, dia, reserva, planificador.Memoria(DATOS / "calendario.json"), carpeta="stopovers")
        correr_fuente(corrida, f"Stopover en {cfg['stopovers'][args.stopover]['nombre']}",
                      lambda: correr_stopover(corrida, args.stopover, args.dias, args.cuando, mes))
        corrida.guardar()
        mostrar_resumen(corrida)
        publicar.publicar(cfg, dia)
        print("\nDashboard actualizado: docs/datos.js")
        return

    if args.explorar:
        if args.solo_plan:
            print(f"Día {dia}. Cupo: {contador.resumen()}")
            for cal in planificador.calendarios_exploracion(cfg):
                print(f"  calendario {cal['origen']}-{cal['destino']} {cal['desde'][:7]} {cal['estadia']} días, sin límite de escalas")
            print("  y hasta 6 búsquedas exactas sobre las fechas más baratas")
            return
        # Memoria aparte: estos precios sin límites no deben mezclarse con la búsqueda diaria.
        corrida = Corrida(configuracion_exploracion(cfg), dia, contador,
                          planificador.Memoria(DATOS / "exploracion" / "calendario.json"), carpeta="exploracion")
        correr_fuente(corrida, "Ignav, exploración sin límites", lambda: correr_exploracion(corrida))
        corrida.guardar()
        mostrar_resumen(corrida)
        return

    memoria = planificador.Memoria(DATOS / "calendario.json")

    if args.solo_plan:
        calendarios = planificador.barrido_inicial(cfg) if args.barrido else planificador.calendarios_del_dia(cfg, dia, CALENDARIOS_POR_DIA)
        print(f"Día {dia}. Cupo: {contador.resumen()}")
        for cal in calendarios:
            print(f"  calendario {cal['origen']}-{cal['destino']} {cal['desde'][:7]} {cal['estadia']} días")
        print(f"Vueltas completas del ciclo: {len(planificador.ciclo_calendarios(cfg))} calendarios")
        return

    corrida = Corrida(cfg, dia, contador, memoria)
    correr_fuente(corrida, "Ignav", lambda: correr_ignav(corrida, args.barrido))
    correr_fuente(corrida, "SerpApi", lambda: correr_serpapi(corrida))
    corrida.guardar()
    mostrar_resumen(corrida)
    analisis.mostrar(analisis.generar(cfg, dia))
    resultado_promos = promociones.buscar(cfg)
    promociones.guardar(resultado_promos, dia)
    promociones.mostrar(resultado_promos)
    publicar.publicar(cfg, dia)
    print("\nDashboard actualizado: docs/datos.js")


if __name__ == "__main__":
    main()
