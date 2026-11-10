"""Pruebas de los stopovers, sin internet."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from vuelos import enlaces, evaluar, stopover, ventajas
from vuelos.config import cargar_config
from vuelos.consultas import Contador, ContadorConReserva, CupoDelDia

CFG = cargar_config()


def tramo(ruta, salida, llegada, escalas=0, horas=14.0):
    return {"aerolineas": ["Turkish Airlines"], "ruta": ruta, "salida": salida, "llegada": llegada, "escalas": escalas, "horas": horas}


def opcion_estambul_ida():
    base = {"tipo": "stopover_estambul_ida", "fuente": "serpapi", "precio_total": 4200, "moneda": "USD", "precio_verificado": False,
            "equipaje": "sin_confirmar", "tramos": [
                tramo(["EZE", "GRU", "IST"], "2027-05-10T13:00", "2027-05-11T15:00", 1, 21.0),
                tramo(["IST", "NRT"], "2027-05-14T01:00", "2027-05-14T19:00", 0, 12.0),
                tramo(["NRT", "IST", "GRU", "EZE"], "2027-06-03T22:00", "2027-06-04T22:00", 2, 36.0)]}
    return evaluar.completar(base, CFG)


class Fechas(unittest.TestCase):
    def test_stopover_a_la_ida_respeta_los_dias_en_japon(self):
        partes = stopover.tramos(date(2027, 5, 10), 3, "ida", 20, "EZE,AEP", "IST", "NRT,HND")
        self.assertEqual(partes, [("EZE,AEP", "IST", "2027-05-10"), ("IST", "NRT,HND", "2027-05-14"), ("NRT,HND", "EZE,AEP", "2027-06-04")])

    def test_stopover_a_la_vuelta(self):
        partes = stopover.tramos(date(2027, 5, 10), 4, "vuelta", 20, "EZE,AEP", "MAD", "NRT,HND")
        self.assertEqual(partes, [("EZE,AEP", "NRT,HND", "2027-05-10"), ("NRT,HND", "MAD", "2027-06-01"), ("MAD", "EZE,AEP", "2027-06-06")])

    def test_elige_2_salidas_baratas_separadas_del_mes_pedido(self):
        filas = [{"salida": "2027-05-10", "ruta": "BUE-TYO", "precio": 4000}, {"salida": "2027-05-11", "ruta": "BUE-TYO", "precio": 4010},
                 {"salida": "2027-05-20", "ruta": "BUE-OSA", "precio": 4100}, {"salida": "2027-06-01", "ruta": "BUE-TYO", "precio": 3000}]
        elegidas = stopover.salidas(filas, "2027-05", lambda s: True, date(2026, 11, 11))
        self.assertEqual([f["salida"] for f in elegidas], ["2027-05-10", "2027-05-20"])

    def test_sin_calendario_para_el_mes_prueba_dias_fijos(self):
        elegidas = stopover.salidas([], "2027-09", lambda s: True, date(2026, 11, 11))
        self.assertEqual([f["salida"] for f in elegidas], ["2027-09-10", "2027-09-20"])


class Detalle(unittest.TestCase):
    def test_un_stopover_puede_pasar_las_36_horas(self):
        o = opcion_estambul_ida()
        o["tramos"][2]["horas"] = 41.0
        self.assertIsNone(evaluar.motivo_descarte(o, CFG["restricciones"]))
        self.assertIsNotNone(evaluar.motivo_descarte({**o, "tipo": "ida_y_vuelta"}, CFG["restricciones"]))

    def test_dias_en_cada_lugar(self):
        o = opcion_estambul_ida()
        self.assertIsNone(evaluar.motivo_descarte(o, CFG["restricciones"]))
        d = stopover.detalle(o, CFG)
        self.assertEqual((d["nombre"], d["cuando"], d["dias_en_escala"], d["dias_en_japon"]), ("Estambul", "ida", 3, 20))
        self.assertEqual((d["llega_escala"][:10], d["llega_buenos_aires"][:10], d["dias_de_viaje"]), ("2027-05-11", "2027-06-04", 25))

    def test_link_multidestino_con_los_3_tramos(self):
        url = enlaces.google_flights(opcion_estambul_ida(), 2)[0]["url"]
        texto = parse_qs(urlparse(url).query)["q"][0]
        self.assertIn("from EZE to IST on 2027-05-10 and from IST to NRT on 2027-05-14 and from NRT to EZE on 2027-06-03", texto)

    def test_ventaja_de_un_solo_pasaje(self):
        r = ventajas.evaluar_opcion(opcion_estambul_ida(), 4000, CFG)
        self.assertTrue(any("Un solo pasaje con los días de stopover" in v for v in r["ventajas"]))
        self.assertFalse(any("volvés desde" in v for v in r["ventajas"]))


class FiltroDeAerolinea(unittest.TestCase):
    def test_sigue_solo_los_tramos_de_la_aerolinea_del_stopover(self):
        from vuelos import buscar

        def vuelo(aerolinea, desde, hasta, precio, token):
            return {"price": precio, "departure_token": token, "total_duration": 600, "flights": [
                {"airline": aerolinea, "departure_airport": {"id": desde, "time": "2027-05-10 10:00"},
                 "arrival_airport": {"id": hasta, "time": "2027-05-10 20:00"}}]}
        pasos = {None: {"best_flights": [vuelo("LEVEL", "EZE", "IST", 100, "a"), vuelo("Turkish Airlines", "EZE", "IST", 200, "b")]},
                 "b": {"best_flights": [vuelo("Turkish Airlines", "IST", "NRT", 300, "c")]},
                 "c": {"best_flights": [vuelo("Turkish Airlines", "NRT", "EZE", 4000, None), vuelo("LATAM", "NRT", "EZE", 3000, None)]}}
        pedidos = []
        corrida = mock.Mock(cfg=CFG)
        corrida.contador.disponibles.return_value = 10
        buscar._recorrer(corrida, lambda token: pedidos.append(token) or pasos[token], "stopover_estambul_ida", 3, 1,
                         acepta=lambda t: "Turkish Airlines" in t["aerolineas"])
        self.assertEqual(pedidos, [None, "b", "c"])
        self.assertEqual([o["precio_total"] for o in corrida.sumar.call_args.args[0]], [4000])


class Cupo(unittest.TestCase):
    def test_cada_consulta_cuenta_en_serpapi_y_en_stopover(self):
        with tempfile.TemporaryDirectory() as carpeta:
            limites = {"serpapi": {"por_dia": 6, "por_mes": 250}, "stopover": {"por_mes": 60, "por_busqueda": 6}}
            base = Contador(Path(carpeta) / "c.json", limites, date(2026, 11, 11), sin_limite_diario=("serpapi",))
            reserva = ContadorConReserva(base, "serpapi", "stopover")
            reserva.limitar("stopover", 6)
            reserva.registrar("serpapi", 6)  # ya gastó el tope diario normal: igual sigue, porque no hay límite diario acá
            self.assertEqual(base.gastadas_del_mes("serpapi"), 6)
            self.assertEqual(base.gastadas_del_mes("stopover"), 6)
            with self.assertRaises(CupoDelDia):
                reserva.verificar("serpapi")  # se terminó lo de esta búsqueda

    def test_respeta_el_tope_del_mes(self):
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / "c.json"
            archivo.write_text(json.dumps({"stopover": {"total": 60, "por_dia": {}, "por_mes": {"2026-11": 60}}}))
            limites = {"serpapi": {"por_dia": 6, "por_mes": 250}, "stopover": {"por_mes": 60}}
            reserva = ContadorConReserva(Contador(archivo, limites, date(2026, 11, 11), sin_limite_diario=("serpapi",)), "serpapi", "stopover")
            self.assertEqual(reserva.disponibles("serpapi"), 0)


if __name__ == "__main__":
    unittest.main()
