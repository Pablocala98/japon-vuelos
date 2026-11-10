"""Ventajas y desventajas de cada opción, con reglas fijas, para que el dashboard las muestre al elegirla."""
from . import aeropuertos, evaluar, planificador, stopover

LLEGADA_INCOMODA = (22, 6)  # llegar a Japón entre las 22 y las 6
HORAS_CORTO = 30
ESPERA_LARGA = 8 * 60       # minutos
CONEXION_CORTA = 90         # minutos, dentro de un mismo pasaje
# Requisitos de tránsito para pasaporte argentino que vale la pena avisar siempre.
TRANSITO = {
    "AR": {
        "US": "necesitás visa de Estados Unidos vigente, aunque no salgas del aeropuerto",
        "CA": "necesitás una eTA o una visa de Canadá, aunque no salgas del aeropuerto",
    },
}


def avisos_de_escalas(tramos: list[dict], pasaporte: str | None) -> tuple[list[str], list[str]]:
    """Desventajas por las escalas (visa, cambio de aeropuerto, noches, esperas) y ventajas si son cómodas."""
    desventajas, avisados = [], set()
    paradas = [aeropuertos.con_lugares(p) for t in tramos for p in aeropuertos.paradas_de(t)]
    for p in paradas:
        lugar = p["lugar"]
        donde = f"{lugar['ciudad']}, {lugar['pais']}" if lugar["pais"] else lugar["ciudad"]
        requisito = TRANSITO.get(pasaporte or "", {}).get(lugar["pais_codigo"])
        if requisito and lugar["pais_codigo"] not in avisados:
            avisados.add(lugar["pais_codigo"])
            desventajas.append(f"Escala en {lugar['pais']} ({lugar['ciudad']}): con pasaporte argentino {requisito}.")
        if p.get("lugar_salida"):
            desventajas.append(f"En {lugar['ciudad']} llegás a {lugar['codigo']} y salís de {p['lugar_salida']['codigo']}: tenés que cambiar de aeropuerto.")
        if p["minutos"] is not None and p["minutos"] >= ESPERA_LARGA:
            desventajas.append(f"Espera de {aeropuertos.duracion(p['minutos'])} en {donde}{' (con noche)' if p['noche'] else ''}.")
        elif p["noche"] and not p["cambio_pasaje"]:
            desventajas.append(f"La escala en {donde} es de noche.")
        if p["minutos"] is not None and p["minutos"] < CONEXION_CORTA and not p["cambio_pasaje"]:
            desventajas.append(f"Conexión corta en {donde}: {aeropuertos.duracion(p['minutos'])}.")
    ventajas = []
    con_duracion = [p for p in paradas if p["minutos"] is not None]
    if con_duracion and len(con_duracion) == len(paradas) and all(CONEXION_CORTA <= p["minutos"] <= 4 * 60 for p in paradas):
        ventajas.append("Todas las escalas duran entre 1 h 30 min y 4 h.")
    return ventajas, desventajas


def usd(valor: float) -> str:
    return f"USD {round(valor):,}".replace(",", ".")


def horas(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def evaluar_opcion(opcion: dict, mas_barata: float, cfg: dict) -> dict:
    """`mas_barata` es el total con valijas de la mejor opción del día."""
    ventajas, desventajas = [], []
    precio = opcion["precio_con_valijas"]
    precios, restricciones = cfg["precios"], cfg["restricciones"]
    tramos = opcion["tramos"]
    ida, vuelta = tramos[0], tramos[-1]

    if precio <= mas_barata:
        ventajas.append("Es la más barata disponible.")
    else:
        desventajas.append(f"Cuesta {usd(precio - mas_barata)} más que la más barata disponible.")
    if precio <= precios["comprar"]:
        ventajas.append(f"Entra en tu presupuesto: {opcion['categoria']}.")
    else:
        if opcion["precio_total"] <= precios["comprar"]:
            ventajas.append(f"Sin valijas ({usd(opcion['precio_total'])}) entra en tu tope de {usd(precios['comprar'])}.")
            desventajas.append(f"Con las valijas estimadas se pasa de tu tope por {usd(precio - precios['comprar'])}.")
        else:
            desventajas.append(f"Se pasa de tu tope por {usd(precio - precios['comprar'])}.")
        if opcion["categoria"] != evaluar.CARO:
            ventajas.append(f"Está cerca de tu tope: {opcion['categoria']}.")

    if opcion["equipaje"] == "incluida":
        ventajas.append("La valija despachada está incluida.")
    elif opcion["equipaje"] == "estimada":
        ventajas.append("El precio ya incluye un costo estimado de la valija.")
    else:
        desventajas.append(f"La valija no está confirmada: sumamos {usd(opcion['valijas_estimadas'])} estimados.")
    if not opcion.get("precio_verificado"):
        desventajas.append("Precio sin confirmar: revisalo antes de comprar.")

    max_escalas = max(t["escalas"] for t in tramos)
    if max_escalas <= 1:
        ventajas.append("Como mucho 1 escala por tramo.")
    elif max_escalas > restricciones["max_escalas"]:
        desventajas.append(f"Hasta {max_escalas} escalas en un tramo.")
    max_horas = max(t["horas"] or 0 for t in tramos)
    if max_horas <= HORAS_CORTO:
        ventajas.append(f"Viaje corto: el tramo más largo dura {horas(max_horas)} h.")
    elif max_horas > (restricciones["max_horas_por_tramo"] or float("inf")):
        desventajas.append(f"Viaje largo: un tramo dura {horas(max_horas)} h.")

    if stopover.es_stopover(opcion):
        ventajas.append("Un solo pasaje con los días de stopover: si un vuelo se atrasa, la aerolínea te reubica.")
    elif opcion["tipo"] == "san_pablo":
        desventajas.append("Son 2 pasajes separados: si perdés la conexión en San Pablo, nadie está obligado a reubicarte.")
        desventajas.append("Tenés que hacer el cambio de avión en San Pablo, con tus valijas.")
    elif ida["ruta"][-1] != vuelta["ruta"][0]:
        ventajas.append(f"Llegás a {ida['ruta'][-1]} y volvés desde {vuelta['ruta'][0]}: no tenés que volver al punto de llegada.")
    else:
        ventajas.append("Un solo pasaje: si un vuelo se atrasa, la aerolínea te reubica.")

    dias = opcion.get("dias_en_japon")
    if dias is not None:
        if dias == restricciones["dias_en_japon"]:
            ventajas.append(f"{dias} días en Japón, justo lo que querés.")
        else:
            desventajas.append(f"{dias} días en Japón (querés {restricciones['dias_en_japon']}).")
    if planificador.es_preferida(cfg, ida["salida"]):
        ventajas.append("Sale entre abril y junio, como preferís.")
    else:
        desventajas.append("Sale fuera de abril-junio, tus meses preferidos.")
    mas_ventajas, mas_desventajas = avisos_de_escalas(tramos, cfg["viaje"].get("pasaporte"))
    ventajas += mas_ventajas
    desventajas += mas_desventajas
    hora_llegada = int(ida["llegada"][11:13]) if ida.get("llegada") else None
    if hora_llegada is not None and (hora_llegada >= LLEGADA_INCOMODA[0] or hora_llegada < LLEGADA_INCOMODA[1]):
        desventajas.append(f"Llegás a Japón a las {ida['llegada'][11:16]}.")
    return {"ventajas": ventajas, "desventajas": desventajas}
