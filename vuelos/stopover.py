"""Stopovers: un solo pasaje que se queda unos días en Madrid o Estambul, a la ida o a la vuelta.

Son 3 tramos (multidestino), y solo Google Flights los busca: cada opción completa gasta 3 consultas de SerpApi.
Las fechas salen del calendario de precios: las salidas más baratas del mes pedido.
"""
from datetime import date, timedelta

TIPO = "stopover"
SALIDAS_POR_BUSQUEDA = 2
SEPARACION_MINIMA = 3  # días entre las 2 salidas que se prueban, para no repetir casi la misma fecha
FECHAS_SIN_CALENDARIO = (10, 20)  # si el calendario no tiene ese mes, se prueban estos días
CORRIMIENTOS = (0, 1, -1)  # si la aerolínea no vuela ese día, se prueba el siguiente y el anterior


def tipo(ciudad: str, cuando: str) -> str:
    return f"{TIPO}_{ciudad}_{cuando}"


def es_stopover(opcion: dict) -> bool:
    return opcion.get("tipo", "").startswith(TIPO + "_")


def datos_del_tipo(tipo_opcion: str) -> tuple[str, str]:
    """'stopover_estambul_vuelta' -> ('estambul', 'vuelta')."""
    _, ciudad, cuando = tipo_opcion.split("_", 2)
    return ciudad, cuando


def tramos(salida: date, dias: int, cuando: str, dias_en_japon: int, origen: str, escala: str, japon: str) -> list[tuple[str, str, str]]:
    """Las 3 partes del viaje, con fechas que respetan los días en Japón.

    A Japón se llega 2 días después de salir (1 si se sale de la ciudad del stopover). Iberia y Turkish salen
    de Japón de noche y llegan a Madrid o Estambul al día siguiente.
    """
    if cuando == "ida":
        sale_escala = salida + timedelta(days=1 + dias)
        sale_japon = sale_escala + timedelta(days=1 + dias_en_japon)
        return [(origen, escala, salida.isoformat()), (escala, japon, sale_escala.isoformat()), (japon, origen, sale_japon.isoformat())]
    sale_japon = salida + timedelta(days=2 + dias_en_japon)
    sale_escala = sale_japon + timedelta(days=1 + dias)
    return [(origen, japon, salida.isoformat()), (japon, escala, sale_japon.isoformat()), (escala, origen, sale_escala.isoformat())]


def salidas(filas: list[dict], mes: str | None, preferida, dia: date) -> list[dict]:
    """Las salidas más baratas del calendario para el mes pedido (o los meses preferidos), separadas entre sí.

    Cada fila trae "salida" y "ruta" (BUE-TYO o BUE-OSA). Si el calendario no tiene ese mes, se prueban días fijos.
    """
    desde = (dia + timedelta(days=7)).isoformat()
    candidatas = sorted((f for f in filas if f["salida"] >= desde and (f["salida"].startswith(mes) if mes else preferida(f["salida"]))),
                        key=lambda f: f["precio"])
    elegidas = []
    for fila in candidatas:
        if all(abs((date.fromisoformat(fila["salida"]) - date.fromisoformat(e["salida"])).days) >= SEPARACION_MINIMA for e in elegidas):
            elegidas.append(fila)
        if len(elegidas) == SALIDAS_POR_BUSQUEDA:
            return elegidas
    if mes and not elegidas:
        fijas = [f"{mes}-{d:02d}" for d in FECHAS_SIN_CALENDARIO]
        return [{"salida": s, "ruta": "BUE-TYO", "precio": None} for s in fijas if s >= desde]
    return elegidas


def detalle(opcion: dict, cfg: dict) -> dict:
    """Cuándo se llega y se sale de cada lugar. Las fechas son las locales de cada aeropuerto."""
    ciudad, cuando = datos_del_tipo(opcion["tipo"])
    lugar = cfg["stopovers"][ciudad]
    t = opcion["tramos"]
    if cuando == "ida":
        llega_escala, sale_escala, llega_japon, sale_japon = t[0]["llegada"], t[1]["salida"], t[1]["llegada"], t[2]["salida"]
    else:
        llega_japon, sale_japon, llega_escala, sale_escala = t[0]["llegada"], t[1]["salida"], t[1]["llegada"], t[2]["salida"]
    dias = lambda a, b: (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    return {
        "ciudad": ciudad, "nombre": lugar["nombre"], "aeropuerto": lugar["aeropuerto"], "cuando": cuando,
        "aerolinea": lugar.get("aerolinea_nombre"), "sitio": lugar.get("sitio"), "aviso": lugar.get("aviso"),
        "sale_buenos_aires": t[0]["salida"], "llega_escala": llega_escala, "sale_escala": sale_escala,
        "dias_en_escala": dias(llega_escala, sale_escala), "llega_japon": llega_japon, "sale_japon": sale_japon,
        "dias_en_japon": dias(llega_japon, sale_japon), "llega_buenos_aires": t[2]["llegada"],
        "dias_de_viaje": dias(t[0]["salida"], t[2]["llegada"]),
    }
