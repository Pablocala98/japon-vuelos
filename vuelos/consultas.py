"""Cuenta las consultas gastadas y frena antes de pasarse de los límites de config.yaml."""
import json
from datetime import date
from pathlib import Path

from .fuentes.base import SinCupo


class CupoDelDia(SinCupo):
    """Se llegó al límite que nos pusimos. No es una falla: la app sigue mañana."""


class Contador:
    def __init__(self, archivo: Path, limites: dict, dia: date, sin_limite_diario: tuple[str, ...] = ()):
        self._archivo = archivo
        self._limites = limites
        self._dia = dia.isoformat()
        self._mes = dia.isoformat()[:7]
        self._sin_limite_diario = sin_limite_diario
        self._tope_externo: dict[str, int] = {}
        self._datos = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}

    def _fuente(self, fuente: str) -> dict:
        return self._datos.setdefault(fuente, {"total": 0, "por_dia": {}, "por_mes": {}})

    def gastadas_hoy(self, fuente: str) -> int:
        return self._fuente(fuente)["por_dia"].get(self._dia, 0)

    def gastadas_del_mes(self, fuente: str) -> int:
        return self._fuente(fuente)["por_mes"].get(self._mes, 0)

    def disponibles(self, fuente: str) -> int:
        limites = self._limites[fuente]
        datos = self._fuente(fuente)
        restos = []
        if "por_dia" in limites and fuente not in self._sin_limite_diario:
            restos.append(limites["por_dia"] - self.gastadas_hoy(fuente))
        if "total_gratis" in limites:
            restos.append(limites["total_gratis"] - datos["total"])
        if "por_mes" in limites:
            restos.append(limites["por_mes"] - datos["por_mes"].get(self._mes, 0))
        if fuente in self._tope_externo:
            restos.append(self._tope_externo[fuente])
        return max(min(restos), 0)

    def limitar(self, fuente: str, restantes: int) -> None:
        """Suma lo que informa la propia fuente, por si gastó más de lo que contamos acá."""
        self._tope_externo[fuente] = restantes

    def verificar(self, fuente: str) -> None:
        if self.disponibles(fuente) <= 0:
            raise CupoDelDia(f"{fuente}: se llegó al límite de consultas")

    def registrar(self, fuente: str, cantidad: int = 1) -> None:
        datos = self._fuente(fuente)
        datos["total"] += cantidad
        datos["por_dia"][self._dia] = datos["por_dia"].get(self._dia, 0) + cantidad
        datos["por_mes"][self._mes] = datos["por_mes"].get(self._mes, 0) + cantidad
        if fuente in self._tope_externo:
            self._tope_externo[fuente] -= cantidad
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        self._archivo.write_text(json.dumps(self._datos, indent=2), encoding="utf-8")

    def resumen(self) -> dict:
        return {
            fuente: {
                "gastadas_hoy": self.gastadas_hoy(fuente),
                "disponibles_hoy": self.disponibles(fuente),
                "total": self._fuente(fuente)["total"],
            }
            for fuente in self._limites
        }


class ContadorConReserva:
    """Cada consulta de `fuente` cuenta también en el tope de `reserva` (los stopovers usan el cupo de SerpApi)."""

    def __init__(self, contador: Contador, fuente: str, reserva: str):
        self._contador, self._fuente, self._reserva = contador, fuente, reserva

    def disponibles(self, fuente: str) -> int:
        propio = self._contador.disponibles(fuente)
        return min(propio, self._contador.disponibles(self._reserva)) if fuente == self._fuente else propio

    def verificar(self, fuente: str) -> None:
        if self.disponibles(fuente) <= 0:
            raise CupoDelDia(f"{fuente}: se llegó al límite de consultas para stopovers")

    def registrar(self, fuente: str, cantidad: int = 1) -> None:
        self._contador.registrar(fuente, cantidad)
        if fuente == self._fuente:
            self._contador.registrar(self._reserva, cantidad)

    def limitar(self, fuente: str, restantes: int) -> None:
        self._contador.limitar(fuente, restantes)

    def gastadas_hoy(self, fuente: str) -> int:
        return self._contador.gastadas_hoy(fuente)

    def resumen(self) -> dict:
        return self._contador.resumen()
