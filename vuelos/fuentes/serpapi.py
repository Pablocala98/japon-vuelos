"""Conexión con SerpApi, motor Google Flights (https://serpapi.com/google-flights-api).

Ojo: en ida y vuelta o multidestino, el precio del primer paso NO es el total real.
El total recién aparece en el último paso, y cada paso gasta una consulta.
"""
import json

from .base import FuenteError, pedir

BASE = "https://serpapi.com"
NOMBRE = "serpapi"
# Código de "stops" en SerpApi: 0 = cualquiera, 1 = directo, 2 = hasta 1 escala, 3 = hasta 2.
PARAM_ESCALAS = {0: 1, 1: 2, 2: 3}


class SerpApi:
    def __init__(self, api_key: str | None, contador, pasajeros: int, carry_on: int, max_escalas: int):
        if not api_key:
            raise FuenteError("SerpApi: falta la clave SERPAPI_API_KEY")
        self._clave = api_key
        self._contador = contador
        self._comunes = {
            "engine": "google_flights",
            "currency": "USD",
            "hl": "es",
            "gl": "ar",
            "adults": pasajeros,
            "bags": carry_on * pasajeros,
            "stops": PARAM_ESCALAS[max_escalas],
            "travel_class": 1,
        }

    def _buscar(self, parametros: dict) -> dict:
        self._contador.verificar(NOMBRE)
        datos = pedir("GET", f"{BASE}/search.json", "SerpApi",
                      params={**self._comunes, **parametros, "api_key": self._clave})
        self._contador.registrar(NOMBRE)
        if datos.get("error") and "hasn't returned any results" not in datos["error"]:
            raise FuenteError(f"SerpApi: {datos['error'][:200]}")
        return datos

    def consultas_restantes(self) -> int | None:
        """Lo que informa SerpApi (se actualiza con demora). Esta llamada no gasta cupo."""
        return pedir("GET", f"{BASE}/account.json", "SerpApi", params={"api_key": self._clave}).get("total_searches_left")

    def ida_y_vuelta(self, origen: str, destino: str, salida: str, regreso: str, token: str | None = None) -> dict:
        """Sin token trae las idas; con el token de una ida, las vueltas y su precio total."""
        parametros = {"type": 1, "departure_id": origen, "arrival_id": destino,
                      "outbound_date": salida, "return_date": regreso}
        if token:
            parametros["departure_token"] = token
        return self._buscar(parametros)

    def multidestino(self, tramos: list[tuple[str, str, str]], token: str | None = None, max_escalas: int | None = None) -> dict:
        """Open-jaw o stopover. Cada tramo es (origen, destino, fecha)."""
        parametros = {"type": 3, "multi_city_json": json.dumps(
            [{"departure_id": o, "arrival_id": d, "date": f} for o, d, f in tramos]
        )}
        if token:
            parametros["departure_token"] = token
        if max_escalas is not None:
            parametros["stops"] = PARAM_ESCALAS[max_escalas]
        return self._buscar(parametros)


def opciones(datos: dict) -> list[dict]:
    return (datos.get("best_flights") or []) + (datos.get("other_flights") or [])


def tramo(opcion: dict) -> dict:
    """Convierte una opción de un paso de SerpApi en un tramo del formato común."""
    vuelos = opcion.get("flights") or []
    return {
        "aerolineas": sorted({v.get("airline", "?") for v in vuelos}),
        "ruta": [v["departure_airport"]["id"] for v in vuelos] + [v["arrival_airport"]["id"] for v in vuelos[-1:]],
        "salida": vuelos[0]["departure_airport"].get("time", "").replace(" ", "T") if vuelos else None,
        "llegada": vuelos[-1]["arrival_airport"].get("time", "").replace(" ", "T") if vuelos else None,
        "escalas": max(len(vuelos) - 1, 0),
        "horas": round(opcion["total_duration"] / 60, 1) if opcion.get("total_duration") else None,
        "paradas": _paradas(vuelos, opcion.get("layovers") or []),
    }


def _paradas(vuelos: list[dict], esperas: list[dict]) -> list[dict]:
    paradas = []
    for i, (llega, sale) in enumerate(zip(vuelos, vuelos[1:])):
        espera = esperas[i] if i < len(esperas) else {}
        aeropuerto, sale_de = llega["arrival_airport"]["id"], sale["departure_airport"]["id"]
        paradas.append({
            "aeropuerto": aeropuerto,
            "sale_de": sale_de if sale_de != aeropuerto else None,
            "minutos": espera.get("duration"),
            "noche": bool(espera.get("overnight")),
            "cambio_pasaje": False,
        })
    return paradas


def armar(tipo: str, tramos: list[dict], precio_total) -> dict:
    """Arma la opción completa con los tramos y el precio del último paso."""
    return {
        "tipo": tipo,
        "fuente": NOMBRE,
        "precio_total": precio_total,
        "moneda": "USD",
        "precio_verificado": False,
        "equipaje": "sin_confirmar",  # Google Flights no informa la valija despachada
        "tramos": tramos,
    }
