"""Conexión con Ignav (https://ignav.com/docs). Los precios son del grupo completo."""
from datetime import datetime

from .base import FuenteError, pedir

BASE = "https://ignav.com/api/fares"
NOMBRE = "ignav"
EQUIPAJE = {"reported_included": "incluida", "estimated": "estimada", "unknown": "sin_confirmar"}
# Ignav a veces trae solo el código. Un código que no esté acá se muestra tal cual.
AEROLINEAS = {
    "3U": "Sichuan Airlines", "AA": "American", "AC": "Air Canada", "AD": "Azul", "AF": "Air France",
    "AM": "Aeroméxico", "AR": "Aerolíneas Argentinas", "AV": "Avianca", "AZ": "ITA Airways", "BA": "British Airways",
    "CA": "Air China", "CM": "Copa", "CX": "Cathay Pacific", "CZ": "China Southern", "DL": "Delta",
    "EK": "Emirates", "ET": "Ethiopian", "EY": "Etihad", "G3": "GOL", "IB": "Iberia", "JA": "JetSMART",
    "JL": "JAL", "KE": "Korean Air", "KL": "KLM", "LA": "LATAM", "LH": "Lufthansa", "LX": "SWISS",
    "MU": "China Eastern", "NH": "ANA", "NZ": "Air New Zealand", "OZ": "Asiana", "QF": "Qantas", "QR": "Qatar",
    "SQ": "Singapore Airlines", "TK": "Turkish", "TP": "TAP", "UA": "United", "UX": "Air Europa", "ZG": "ZIPAIR",
}


class Ignav:
    def __init__(self, api_key: str | None, contador, pasajeros: int, carry_on: int, despachadas: int, max_escalas: int):
        if not api_key:
            raise FuenteError("Ignav: falta la clave IGNAV_API_KEY")
        self._headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
        self._contador = contador
        self._comunes = {
            "adults": pasajeros,
            "cabin_class": "economy",
            "carry_on_bags": carry_on * pasajeros,
            "checked_bags": despachadas * pasajeros,
            "market": "US",  # hace que los precios vengan en USD
        }
        self.max_escalas = max_escalas

    def _post(self, ruta: str, cuerpo: dict) -> dict:
        self._contador.verificar(NOMBRE)
        # El pedido de links con el número de itinerario no acepta nada más: los pasajeros ya vienen en ese número.
        comunes = {} if ruta == "booking-links" else self._comunes
        datos = pedir("POST", f"{BASE}/{ruta}", "Ignav", headers=self._headers, json=_sin_nulos({**comunes, **cuerpo}))
        self._contador.registrar(NOMBRE)  # los pedidos fallidos no se cobran
        return datos

    def _escalas(self, max_escalas: int | None) -> int:
        return self.max_escalas if max_escalas is None else max_escalas

    def calendario(self, origen: str, destino: str, desde: str, hasta: str, estadia: int, max_escalas: int | None = None) -> dict:
        """Precio más bajo por fecha de salida. Hasta 31 días; cuenta como 1 consulta."""
        return self._post("cheapest-dates", {
            "origin": origen,
            "destination": destino,
            "departure_date_range": {"start": desde, "end": hasta},
            "stay_days": estadia,
            "max_stops": self._escalas(max_escalas),
        })

    def ida_y_vuelta(self, origen: str, destino: str, salida: str, regreso: str, max_escalas: int | None = None) -> dict:
        return self._post("round-trip", {
            "origin": origen,
            "destination": destino,
            "departure_date": salida,
            "return_date": regreso,
            "max_stops": self._escalas(max_escalas),
        })

    def links_de_compra(self, ignav_id: str) -> dict:
        """Dónde comprar un itinerario ya encontrado. Cuenta como 1 consulta."""
        return self._post("booking-links", {"ignav_id": ignav_id})

    def open_jaw(self, origen: str, llegada: str, salida_vuelta: str, regreso_a: str, fecha_ida: str, fecha_vuelta: str) -> dict:
        return self._post("search", {"legs": [
            {"origin": origen, "destination": llegada, "departure_date": fecha_ida, "max_stops": self.max_escalas},
            {"origin": salida_vuelta, "destination": regreso_a, "departure_date": fecha_vuelta, "max_stops": self.max_escalas},
        ]})


def _sin_nulos(cuerpo: dict) -> dict:
    """Sin límite de escalas, "max_stops" directamente no se manda."""
    limpio = {clave: valor for clave, valor in cuerpo.items() if valor is not None}
    if "legs" in limpio:
        limpio["legs"] = [_sin_nulos(tramo) for tramo in limpio["legs"]]
    return limpio


def normalizar(itinerario: dict, tipo: str) -> dict:
    """Convierte un itinerario de Ignav al formato común de la app."""
    tramos = itinerario.get("legs") or [t for t in (itinerario.get("outbound"), itinerario.get("inbound")) if t]
    precio = itinerario.get("price") or {}
    estado = (itinerario.get("baggage_pricing") or {}).get("status", "unknown")
    return {
        "tipo": tipo,
        "fuente": NOMBRE,
        "ignav_id": itinerario.get("ignav_id"),
        "precio_total": precio.get("amount"),
        "moneda": precio.get("currency"),
        "precio_verificado": precio.get("status") == "verified",
        "equipaje": EQUIPAJE.get(estado, "sin_confirmar"),
        "tramos": [_tramo(t) for t in tramos],
    }


def links(respuesta: dict) -> list[dict]:
    """Los links de compra en el formato de la app: primero las aerolíneas y el vuelo exacto."""
    tramos = {("outbound",): "ida", ("inbound",): "vuelta"}
    resultado, vistos = [], set()
    for opcion in respuesta.get("booking_options") or []:
        clave_tramos = tuple(opcion.get("legs") or ())
        alcance = tramos.get(clave_tramos, "ida y vuelta" if clave_tramos else "todo el viaje")
        for link in opcion.get("links") or []:
            if not link.get("url") or link["url"] in vistos:
                continue
            vistos.add(link["url"])
            precio = link.get("price") or {}
            resultado.append({
                "proveedor": link.get("provider_name") or "?",
                "aerolinea": link.get("provider_type") == "airline",
                "exacto": link.get("specificity") == "exact_flight",
                "precio": precio.get("amount") if precio.get("currency") == "USD" else None,
                "alcance": alcance,
                "url": link["url"],
            })
    return sorted(resultado, key=lambda l: (not l["exacto"], not l["aerolinea"], l["precio"] or float("inf")))


def _aerolinea(segmento: dict) -> str:
    codigo = segmento.get("marketing_carrier_code")
    return segmento.get("operating_carrier_name") or AEROLINEAS.get(codigo) or codigo or "?"


def _tramo(tramo: dict) -> dict:
    segmentos = tramo.get("segments") or []
    return {
        "aerolineas": sorted({_aerolinea(s) for s in segmentos}),
        "ruta": [s.get("departure_airport") for s in segmentos] + [s.get("arrival_airport") for s in segmentos[-1:]],
        "salida": (segmentos[0].get("departure_time_local") or "")[:16] if segmentos else None,
        "llegada": (segmentos[-1].get("arrival_time_local") or "")[:16] if segmentos else None,
        "escalas": max(len(segmentos) - 1, 0),
        "horas": round(tramo["duration_minutes"] / 60, 1) if tramo.get("duration_minutes") else None,
        "minutos": tramo.get("duration_minutes"),
        "paradas": [_parada(llega, sale) for llega, sale in zip(segmentos, segmentos[1:])],
    }


def _parada(llega: dict, sale: dict) -> dict:
    """La escala entre dos vuelos: cuánto se espera, si cruza la noche y si hay que cambiar de aeropuerto."""
    minutos = None
    if llega.get("arrival_time_utc") and sale.get("departure_time_utc"):
        diferencia = datetime.fromisoformat(sale["departure_time_utc"]) - datetime.fromisoformat(llega["arrival_time_utc"])
        minutos = round(diferencia.total_seconds() / 60)
    otro = sale.get("departure_airport") if sale.get("departure_airport") != llega.get("arrival_airport") else None
    return {
        "aeropuerto": llega.get("arrival_airport"),
        "sale_de": otro,
        "minutos": minutos,
        "noche": (llega.get("arrival_time_local") or "")[:10] != (sale.get("departure_time_local") or "")[:10],
        "cambio_pasaje": False,
    }
