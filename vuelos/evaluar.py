"""Reglas del viaje: qué opción se descarta, cuánto cuesta la valija y en qué categoría cae."""
from datetime import date, datetime

AEROPUERTOS_JAPON = {"NRT", "HND", "KIX", "ITM"}
TIPOS_SAN_PABLO = {"san_pablo", "desde_san_pablo"}
CATEGORIAS =(("ideal", "🟢 ideal"), ("comprar", "✅ comprar"), ("casi", "👀 casi"))
CARO = "🔴 todavía caro"


def motivo_descarte(opcion: dict, restricciones: dict) -> str | None:
    """Devuelve por qué no sirve la opción, o None si cumple todo."""
    if opcion.get("moneda") != "USD":
        return "precio en otra moneda"
    if not opcion.get("precio_total"):
        return "sin precio"
    if not opcion.get("tramos"):
        return "sin detalle de vuelos"
    max_escalas, max_horas = restricciones["max_escalas"], _max_horas(opcion, restricciones)
    for tramo in opcion["tramos"]:
        if max_escalas is not None and tramo["escalas"] > max_escalas:
            return f"más de {max_escalas} escalas"
        if tramo["horas"] is None:
            return "sin duración informada"
        if max_horas is not None and tramo["horas"] > max_horas:
            return f"más de {max_horas} h en un tramo"
    dias = dias_en_japon(opcion)
    objetivo, tolerancia = restricciones["dias_en_japon"], restricciones["tolerancia_dias"]
    if dias is not None and abs(dias - objetivo) > tolerancia:
        return f"fuera de {objetivo - tolerancia}-{objetivo + tolerancia} días en Japón"
    return None


def _max_horas(opcion: dict, restricciones: dict) -> float | None:
    """La ruta desde San Pablo y los stopovers pueden tener su propio límite de horas (o ninguno)."""
    tipo = opcion.get("tipo") or ""
    clave = ("max_horas_por_tramo_san_pablo" if tipo in TIPOS_SAN_PABLO
             else "max_horas_por_tramo_stopover" if tipo.startswith("stopover_") else None)
    if clave and clave in restricciones:
        propio = restricciones[clave]
        general = restricciones["max_horas_por_tramo"]
        # En la exploración no hay límite general: el de San Pablo no puede volver a ponerlo.
        return None if general is None else propio
    return restricciones["max_horas_por_tramo"]


def dias_en_japon(opcion: dict) -> int | None:
    """Del día de llegada al día de salida de Japón. None si la opción no pisa Japón (tramo corto a San Pablo)."""
    llegada = next((t["llegada"] for t in opcion["tramos"] if t["ruta"][-1] in AEROPUERTOS_JAPON), None)
    salida = next((t["salida"] for t in opcion["tramos"] if t["ruta"][0] in AEROPUERTOS_JAPON), None)
    if not llegada or not salida:
        return None
    return (date.fromisoformat(salida[:10]) - date.fromisoformat(llegada[:10])).days


def tramo_cumple(tramo: dict, restricciones: dict) -> bool:
    max_escalas, max_horas = restricciones["max_escalas"], restricciones["max_horas_por_tramo"]
    return ((max_escalas is None or tramo["escalas"] <= max_escalas)
            and tramo["horas"] is not None
            and (max_horas is None or tramo["horas"] <= max_horas))


def completar(opcion: dict, cfg: dict) -> dict:
    """Agrega precio por persona, costo estimado de valijas y categoría."""
    pasajeros = cfg["viaje"]["pasajeros"]
    tramos_sin_confirmar = 0
    if opcion["equipaje"] == "sin_confirmar":
        tramos_sin_confirmar = opcion.get("tramos_valija_sin_confirmar", len(opcion["tramos"]))
    valijas = (tramos_sin_confirmar * pasajeros * cfg["equipaje"]["despachadas"]
               * cfg["equipaje"]["costo_estimado_valija_por_tramo"])
    con_valijas = round(opcion["precio_total"] + valijas)
    return {
        **opcion,
        "por_persona": round(opcion["precio_total"] / pasajeros),
        "valijas_estimadas": valijas,
        "precio_con_valijas": con_valijas,
        "por_persona_con_valijas": round(con_valijas / pasajeros),
        "categoria": categoria(con_valijas, cfg["precios"]),
        "dias_en_japon": dias_en_japon(opcion),
        # Solo en la exploración sin límites: avisa si no cumple los límites normales.
        "excede_limites": motivo_descarte(opcion, cfg.get("restricciones_originales") or cfg["restricciones"]),
    }


def categoria(precio: float, precios: dict) -> str:
    for clave, etiqueta in CATEGORIAS:
        if precio <= precios[clave]:
            return etiqueta
    return CARO


def combinar_san_pablo(larga: dict, tramo_corto: dict, conexion_minima: float) -> dict | None:
    """Une el pasaje desde San Pablo con el de Buenos Aires-San Pablo, si llegan a conectar."""
    ida_larga, vuelta_larga = larga["tramos"]
    ida_corta, vuelta_corta = tramo_corto["tramos"]
    espera_ida = _horas_entre(ida_corta["llegada"], ida_larga["salida"])
    espera_vuelta = _horas_entre(vuelta_larga["llegada"], vuelta_corta["salida"])
    if espera_ida < conexion_minima or espera_vuelta < conexion_minima:
        return None
    pendientes = (2 if larga["equipaje"] == "sin_confirmar" else 0) + (2 if tramo_corto["equipaje"] == "sin_confirmar" else 0)
    return {
        "tipo": "san_pablo",
        "fuente": larga["fuente"],
        "precio_total": larga["precio_total"] + tramo_corto["precio_total"],
        "moneda": larga["moneda"],
        "precio_verificado": larga["precio_verificado"] and tramo_corto["precio_verificado"],
        "equipaje": "sin_confirmar" if pendientes else "incluida",
        "tramos_valija_sin_confirmar": pendientes,
        "desglose": {"buenos_aires_san_pablo": tramo_corto["precio_total"], "desde_san_pablo": larga["precio_total"]},
        "ignav_ids": [i for i in (larga.get("ignav_id"), tramo_corto.get("ignav_id")) if i],
        "partes": {
            "largo": {"origen": ida_larga["ruta"][0], "destino": ida_larga["ruta"][-1],
                      "salida": ida_larga["salida"], "regreso": vuelta_larga["salida"]},
            "corto": {"origen": ida_corta["ruta"][0], "destino": ida_corta["ruta"][-1],
                      "salida": ida_corta["salida"], "regreso": vuelta_corta["salida"]},
        },
        "avisos": ["Son 2 pasajes separados: si perdés la conexión, la aerolínea no tiene por qué protegerte."],
        "tramos": [_unir(ida_corta, ida_larga, espera_ida), _unir(vuelta_larga, vuelta_corta, espera_vuelta)],
    }


def combinaciones_san_pablo(largas: list[dict], cortas: list[dict], restricciones: dict) -> tuple[list[dict], dict | None]:
    """Devuelve la mejor combinación válida de cada vuelo largo, y la más barata descartada, con el motivo.

    Por cada vuelo largo hay muchos tramos cortos posibles: se queda el más barato y, a igual precio, el más corto.
    """
    validas = []
    descartada = None
    for larga in largas:
        mejor = None
        for corta in cortas:
            combinada = combinar_san_pablo(larga, corta, restricciones["conexion_minima_horas"])
            if not combinada:
                continue
            motivo = motivo_descarte(combinada, restricciones)
            if not motivo:
                if mejor is None or _orden_san_pablo(combinada) < _orden_san_pablo(mejor):
                    mejor = combinada
            elif descartada is None or combinada["precio_total"] < descartada["precio_total"]:
                descartada = {
                    "precio_total": combinada["precio_total"],
                    "motivo": motivo,
                    "tramos": [{"ruta": t["ruta"], "horas": t["horas"], "salida": t["salida"]} for t in combinada["tramos"]],
                }
        if mejor:
            validas.append(mejor)
    return validas, descartada


def confirmar_precio(opcion: dict, precios: list[float], fecha: str, cfg: dict) -> dict:
    """Actualiza la opción con el precio que dio la fuente al pedir los links de compra (uno por pasaje)."""
    total = round(sum(precios), 2)
    actualizada = {**opcion, "precio_total": total, "precio_confirmado": {"total": total, "fecha": fecha},
                   "precios_por_fuente": {**(opcion.get("precios_por_fuente") or {}), "ignav": total}}
    if opcion.get("desglose") and len(precios) == 2:
        actualizada["desglose"] = {"desde_san_pablo": precios[0], "buenos_aires_san_pablo": precios[1]}
    return completar(actualizada, cfg)


def _orden_san_pablo(opcion: dict) -> tuple:
    return opcion["precio_total"], sum(t["horas"] or 0 for t in opcion["tramos"])


def _unir(primero: dict, segundo: dict, espera: float) -> dict:
    return {
        "aerolineas": sorted(set(primero["aerolineas"]) | set(segundo["aerolineas"])),
        "ruta": primero["ruta"] + segundo["ruta"][1:],
        "salida": primero["salida"],
        "llegada": segundo["llegada"],
        "escalas": primero["escalas"] + segundo["escalas"] + 1,
        "horas": round(primero["horas"] + espera + segundo["horas"], 1) if primero["horas"] and segundo["horas"] else None,
        # El cambio entre los 2 pasajes también es una escala: hay que retirar y volver a despachar las valijas.
        "paradas": primero.get("paradas", []) + [{
            "aeropuerto": primero["ruta"][-1], "sale_de": None, "minutos": round(espera * 60),
            "noche": primero["llegada"][:10] != segundo["salida"][:10], "cambio_pasaje": True,
        }] + segundo.get("paradas", []),
    }


def _horas_entre(desde: str, hasta: str) -> float:
    """Ambas horas son locales de San Pablo: no hay que convertir zonas horarias."""
    return (datetime.fromisoformat(hasta) - datetime.fromisoformat(desde)).total_seconds() / 3600


def clave_vuelo(opcion: dict) -> tuple:
    """Identifica el mismo itinerario aunque venga de otra fuente."""
    return tuple((tuple(t["ruta"]), t["salida"], t["llegada"]) for t in opcion["tramos"])


def juntar(opciones: list[dict]) -> list[dict]:
    """Saca repetidos conservando el más barato y anota el precio de cada fuente. Ordena por precio."""
    unicas: dict[tuple, dict] = {}
    for opcion in opciones:
        clave = clave_vuelo(opcion)
        precios = dict(opcion.get("precios_por_fuente") or {opcion["fuente"]: opcion["precio_total"]})
        previa = unicas.get(clave)
        extras = {}
        if previa:
            precios = {**previa["precios_por_fuente"], **precios}
            # El número de Ignav y los links sirven aunque gane el precio de otra fuente.
            extras = {k: previa.get(k) or opcion.get(k) for k in ("ignav_id", "links_compra") if previa.get(k) or opcion.get(k)}
            if previa["precio_con_valijas"] <= opcion["precio_con_valijas"]:
                opcion = previa
        unicas[clave] = {**opcion, **extras, "precios_por_fuente": precios}
    return sorted(unicas.values(), key=lambda o: o["precio_con_valijas"])
