"""El "día" de la app es siempre el de Buenos Aires, corra donde corra."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")


def hoy() -> date:
    return datetime.now(ZONA).date()


def ahora() -> str:
    return datetime.now(ZONA).isoformat(timespec="seconds")
