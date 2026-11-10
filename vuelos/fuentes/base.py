"""Lo común a todas las fuentes: pedidos HTTP con reintentos y errores claros."""
import time

import requests

TIEMPO_MAXIMO = 90
ESPERAS_REINTENTO = (5, 20)
CODIGOS_TEMPORALES = {424, 429, 500, 502, 503, 504}


class FuenteError(Exception):
    """Falla de una fuente. El mensaje se muestra en el dashboard: nunca incluye claves."""


class SinCupo(FuenteError):
    """La fuente se quedó sin consultas gratis. No hay que seguir insistiendo."""


def pedir(metodo: str, url: str, fuente: str, **kwargs) -> dict:
    """Hace el pedido y devuelve el JSON. Reintenta solo las fallas temporales."""
    ultimo_error = "error desconocido"
    for espera in (*ESPERAS_REINTENTO, None):
        try:
            respuesta = requests.request(metodo, url, timeout=TIEMPO_MAXIMO, **kwargs)
        except requests.RequestException as error:
            # El texto original puede incluir la URL con la clave: solo se guarda el tipo.
            ultimo_error = f"sin conexión ({type(error).__name__})"
        else:
            if respuesta.status_code == 200:
                try:
                    return respuesta.json()
                except ValueError:
                    ultimo_error = "respuesta inválida (no es JSON)"
            elif respuesta.status_code == 402:
                raise SinCupo(f"{fuente}: se terminaron las consultas gratis")
            elif respuesta.status_code in CODIGOS_TEMPORALES:
                ultimo_error = f"falla temporal (HTTP {respuesta.status_code})"
            elif respuesta.status_code in (401, 403):
                raise FuenteError(f"{fuente}: la clave no es válida (HTTP {respuesta.status_code})")
            else:
                raise FuenteError(
                    f"{fuente}: pedido rechazado (HTTP {respuesta.status_code}): "
                    f"{_detalle(respuesta)}"
                )
        if espera is not None:
            time.sleep(espera)
    raise FuenteError(f"{fuente}: {ultimo_error}")


def _detalle(respuesta: requests.Response) -> str:
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return "sin detalle"
    error = cuerpo.get("error", cuerpo)
    if isinstance(error, dict):
        error = error.get("message") or error.get("code") or "sin detalle"
    return str(error)[:200]
