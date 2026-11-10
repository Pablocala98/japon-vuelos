"""Links de búsqueda en Google Flights. No gastan consultas: abren la búsqueda ya armada.

Google Flights entiende búsquedas escritas en inglés en el parámetro "q". El link abre la
búsqueda; el vuelo exacto se elige ahí, y el precio puede no ser el mismo.
"""
from urllib.parse import urlencode

BASE = "https://www.google.com/travel/flights"


def _url(texto: str) -> str:
    return f"{BASE}?{urlencode({'q': texto, 'hl': 'es-419', 'curr': 'USD'})}"


def _ida_y_vuelta(origen: str, destino: str, salida: str, regreso: str, pasajeros: int) -> str:
    return _url(f"Flights from {origen} to {destino} on {salida[:10]} through {regreso[:10]} for {pasajeros} adults")


def google_flights(opcion: dict, pasajeros: int) -> list[dict]:
    ida, vuelta = opcion["tramos"][0], opcion["tramos"][-1]
    if opcion["tipo"] == "san_pablo" and opcion.get("partes"):
        largo, corto = opcion["partes"]["largo"], opcion["partes"]["corto"]
        return [
            {"texto": "Buscar el pasaje desde San Pablo", "url": _ida_y_vuelta(largo["origen"], largo["destino"], largo["salida"], largo["regreso"], pasajeros)},
            {"texto": "Buscar el tramo Buenos Aires–San Pablo", "url": _ida_y_vuelta(corto["origen"], corto["destino"], corto["salida"], corto["regreso"], pasajeros)},
        ]
    if ida["ruta"][-1] != vuelta["ruta"][0]:  # open-jaw: llega a una ciudad y vuelve de otra
        texto = (f"Multi-city flights from {ida['ruta'][0]} to {ida['ruta'][-1]} on {ida['salida'][:10]} "
                 f"and from {vuelta['ruta'][0]} to {vuelta['ruta'][-1]} on {vuelta['salida'][:10]} for {pasajeros} adults")
        return [{"texto": "Buscar en Google Flights (revisá que quede como multidestino)", "url": _url(texto)}]
    return [{"texto": "Buscar en Google Flights", "url": _ida_y_vuelta(ida["ruta"][0], ida["ruta"][-1], ida["salida"], vuelta["salida"], pasajeros)}]
