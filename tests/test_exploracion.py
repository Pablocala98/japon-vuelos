"""Corre la exploración completa con una fuente simulada: no usa internet ni gasta consultas."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from vuelos import buscar, planificador
from vuelos.config import cargar_config
from vuelos.consultas import Contador
from vuelos.fuentes.ignav import Ignav, _sin_nulos

DIA = date(2026, 11, 7)
HORAS_LARGAS = 40


def tramo(origen, destino, sale, llega, minutos):
    return {"duration_minutes": minutos, "segments": [{
        "operating_carrier_name": "Prueba", "departure_airport": origen, "arrival_airport": destino,
        "departure_time_local": sale, "arrival_time_local": llega}]}


def itinerario(tramos, precio):
    return {"price": {"amount": precio, "currency": "USD", "status": "verified"},
            "baggage_pricing": {"status": "reported_included"}, **tramos}


class FuenteSimulada:
    """Responde como Ignav. Un vuelo de 40 h, para ver que sobrevive sin límites y queda marcado."""
    pedidos: list[tuple] = []

    def __init__(self, api_key, contador, pasajeros, carry_on, despachadas, max_escalas):
        self.contador = contador

    def _anotar(self, *pedido):
        self.contador.verificar("ignav")
        self.pedidos.append(pedido)
        self.contador.registrar("ignav")

    def calendario(self, origen, destino, desde, hasta, estadia, max_escalas=None):
        self._anotar("calendario", origen, destino, max_escalas)
        inicio = date.fromisoformat(desde)
        return {"dates": [{
            "departure_date": (inicio + timedelta(days=i)).isoformat(),
            "return_date": (inicio + timedelta(days=i + estadia)).isoformat(),
            "price": {"amount": 3000 + i * 10, "currency": "USD", "status": "unverified"},
        } for i in range(5)]}

    def ida_y_vuelta(self, origen, destino, salida, regreso, max_escalas=None):
        self._anotar("exacta", origen, destino, max_escalas)
        if destino == "GRU":
            return {"itineraries": [itinerario({
                "outbound": tramo("AEP", "GRU", f"{salida}T08:00:00", f"{salida}T11:00:00", 180),
                "inbound": tramo("GRU", "AEP", f"{regreso}T20:00:00", f"{regreso}T23:00:00", 180)}, 300)]}
        partida = date.fromisoformat(salida)
        vuelta = date.fromisoformat(regreso)
        llegada = (partida + timedelta(days=2)).isoformat()
        fin = (vuelta + timedelta(days=1)).isoformat()
        nombre_origen = "GRU" if origen == "GRU" else "EZE"
        return {"itineraries": [itinerario({
            "outbound": tramo(nombre_origen, "NRT", f"{salida}T20:00:00", f"{llegada}T10:00:00", HORAS_LARGAS * 60),
            "inbound": tramo("NRT", nombre_origen, f"{regreso}T20:00:00", f"{fin}T10:00:00", 1800)}, 2900)]}

    def open_jaw(self, origen, llegada, salida_vuelta, regreso_a, fecha_ida, fecha_vuelta):
        self._anotar("open-jaw")
        return {"itineraries": []}


class Exploracion(unittest.TestCase):
    def setUp(self):
        FuenteSimulada.pedidos = []
        self.carpeta = tempfile.TemporaryDirectory()
        self.datos = Path(self.carpeta.name)
        self.cfg = buscar.configuracion_exploracion(cargar_config())

    def tearDown(self):
        self.carpeta.cleanup()

    def correr(self):
        contador = Contador(self.datos / "consultas.json", self.cfg["consultas"], DIA, sin_limite_diario=("ignav",))
        with mock.patch.object(buscar, "DATOS", self.datos), mock.patch.object(buscar, "Ignav", FuenteSimulada), \
                mock.patch.object(buscar, "clave", lambda nombre: "x"):
            memoria = planificador.Memoria(self.datos / "exploracion" / "calendario.json")
            corrida = buscar.Corrida(self.cfg, DIA, contador, memoria, carpeta="exploracion")
            buscar.correr_exploracion(corrida)
            corrida.guardar()
        return corrida, contador

    def test_gasta_como_maximo_15_consultas_y_lo_cuenta(self):
        _, contador = self.correr()
        self.assertLessEqual(len(FuenteSimulada.pedidos), 15)
        self.assertEqual(contador.resumen()["ignav"]["total"], len(FuenteSimulada.pedidos))
        self.assertEqual(sum(p[0] == "calendario" for p in FuenteSimulada.pedidos), 9)

    def test_no_pide_limite_de_escalas_salvo_el_tramo_corto(self):
        self.correr()
        for pedido in FuenteSimulada.pedidos:
            if pedido[0] == "exacta" and pedido[2] == "GRU":
                self.assertEqual(pedido[3], 0)
            elif pedido[0] != "open-jaw":
                self.assertIsNone(pedido[3])

    def test_el_vuelo_largo_queda_y_se_marca(self):
        corrida, _ = self.correr()
        self.assertTrue(corrida.opciones)
        largas = [o for o in corrida.opciones if o["tipo"] == "ida_y_vuelta"]
        self.assertIn("36", largas[0]["excede_limites"])
        self.assertEqual(largas[0]["dias_en_japon"], 20)

    def test_correrla_dos_veces_el_mismo_dia_no_gasta_de_nuevo(self):
        self.correr()
        primera = len(FuenteSimulada.pedidos)
        self.correr()
        self.assertEqual(len(FuenteSimulada.pedidos), primera)

    def test_no_toca_la_memoria_ni_los_resultados_diarios(self):
        self.correr()
        self.assertFalse((self.datos / "calendario.json").exists())
        self.assertFalse((self.datos / "resultados").exists())
        self.assertTrue(json.loads((self.datos / "exploracion" / f"{DIA}.json").read_text(encoding="utf-8"))["opciones"])


class PedidoSinLimite(unittest.TestCase):
    def test_sin_limite_no_se_manda_max_stops(self):
        cuerpo = {"origin": "BUE", "max_stops": None, "legs": [{"origin": "BUE", "max_stops": None}]}
        self.assertEqual(_sin_nulos(cuerpo), {"origin": "BUE", "legs": [{"origin": "BUE"}]})

    def test_la_fuente_real_acepta_que_no_haya_limite(self):
        contador = mock.Mock()
        fuente = Ignav("x", contador, 2, 1, 1, None)
        with mock.patch("vuelos.fuentes.ignav.pedir", return_value={"dates": []}) as pedir:
            fuente.calendario("BUE", "TYO", "2027-05-01", "2027-05-31", 22)
        self.assertNotIn("max_stops", pedir.call_args.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
