"""Pruebas del detalle de escalas, sin internet."""
import unittest

from vuelos import aeropuertos, evaluar, ventajas
from vuelos.fuentes import ignav, serpapi


def segmento(sale, llega, sale_utc, llega_utc, sale_local, llega_local):
    return {"departure_airport": sale, "arrival_airport": llega, "departure_time_utc": sale_utc, "arrival_time_utc": llega_utc,
            "departure_time_local": sale_local, "arrival_time_local": llega_local, "operating_carrier_name": "X"}


class Aeropuertos(unittest.TestCase):
    def test_describe_en_espanol(self):
        madrid = aeropuertos.describir("MAD")
        self.assertEqual((madrid["ciudad"], madrid["pais"], madrid["pais_codigo"]), ("Madrid", "España", "ES"))
        self.assertEqual(aeropuertos.describir("NRT")["ciudad"], "Tokio (Narita)")

    def test_codigo_desconocido_no_rompe(self):
        self.assertEqual(aeropuertos.describir("ZZZ")["ciudad"], "ZZZ")

    def test_duracion(self):
        self.assertEqual([aeropuertos.duracion(m) for m in (635, 120, 45, None)], ["10 h 35 min", "2 h", "45 min", ""])

    def test_datos_viejos_sin_paradas_se_arman_desde_la_ruta(self):
        paradas = aeropuertos.paradas_de({"ruta": ["EZE", "MAD", "NRT"]})
        self.assertEqual([(p["aeropuerto"], p["minutos"]) for p in paradas], [("MAD", None)])


class ParadasDeLasFuentes(unittest.TestCase):
    def test_ignav_calcula_la_espera_la_noche_y_el_cambio_de_aeropuerto(self):
        tramo = {"duration_minutes": 1800, "segments": [
            segmento("EZE", "JFK", "2027-05-01T01:00:00Z", "2027-05-01T12:00:00Z", "2027-04-30T22:00:00", "2027-05-01T08:00:00"),
            segmento("LGA", "HND", "2027-05-01T15:30:00Z", "2027-05-02T05:00:00Z", "2027-05-01T11:30:00", "2027-05-02T14:00:00"),
        ]}
        parada = ignav._tramo(tramo)["paradas"][0]
        self.assertEqual((parada["aeropuerto"], parada["sale_de"], parada["minutos"], parada["noche"]), ("JFK", "LGA", 210, False))

    def test_serpapi_usa_las_esperas_de_google(self):
        opcion = {"total_duration": 1800, "flights": [
            {"airline": "KLM", "departure_airport": {"id": "EZE", "time": "2027-05-23 15:05"}, "arrival_airport": {"id": "AMS", "time": "2027-05-24 09:00"}},
            {"airline": "KLM", "departure_airport": {"id": "AMS", "time": "2027-05-24 14:00"}, "arrival_airport": {"id": "NRT", "time": "2027-05-25 09:00"}}],
            "layovers": [{"duration": 300, "id": "AMS", "overnight": False}]}
        parada = serpapi.tramo(opcion)["paradas"][0]
        self.assertEqual((parada["aeropuerto"], parada["minutos"], parada["sale_de"]), ("AMS", 300, None))

    def test_san_pablo_suma_el_cambio_de_pasaje_como_escala(self):
        def t(ruta, sale, llega, paradas):
            return {"aerolineas": ["X"], "ruta": ruta, "salida": sale, "llegada": llega, "escalas": len(ruta) - 2, "horas": 20, "paradas": paradas}
        madrid = [{"aeropuerto": "MAD", "sale_de": None, "minutos": 635, "noche": False, "cambio_pasaje": False}]
        larga = {"precio_total": 2548, "moneda": "USD", "fuente": "ignav", "equipaje": "sin_confirmar", "precio_verificado": True,
                 "tramos": [t(["GRU", "MAD", "NRT"], "2027-06-06T19:20", "2027-06-08T18:35", madrid), t(["NRT", "GRU"], "2027-06-28T10:35", "2027-06-29T05:00", [])]}
        corta = {"precio_total": 980, "moneda": "USD", "fuente": "ignav", "equipaje": "sin_confirmar", "precio_verificado": True,
                 "tramos": [t(["AEP", "GRU"], "2027-06-06T11:55", "2027-06-06T14:40", []), t(["GRU", "AEP"], "2027-06-29T15:40", "2027-06-29T18:40", [])]}
        combinada = evaluar.combinar_san_pablo(larga, corta, 4)
        paradas = combinada["tramos"][0]["paradas"]
        self.assertEqual([(p["aeropuerto"], p["cambio_pasaje"], p["minutos"]) for p in paradas], [("GRU", True, 280), ("MAD", False, 635)])


class AvisosDeEscalas(unittest.TestCase):
    def tramo(self, *paradas):
        return {"ruta": ["EZE"] + [p["aeropuerto"] for p in paradas] + ["NRT"], "paradas": list(paradas)}

    def parada(self, codigo, minutos=180, **extra):
        return {"aeropuerto": codigo, "sale_de": None, "minutos": minutos, "noche": False, "cambio_pasaje": False, **extra}

    def test_estados_unidos_pide_visa_una_sola_vez(self):
        _, contras = ventajas.avisos_de_escalas([self.tramo(self.parada("DFW")), self.tramo(self.parada("JFK"))], "AR")
        visas = [c for c in contras if "visa de Estados Unidos" in c]
        self.assertEqual(len(visas), 1)
        self.assertIn("Escala en Estados Unidos (Dallas)", visas[0])

    def test_sin_pasaporte_argentino_no_avisa_visa(self):
        _, contras = ventajas.avisos_de_escalas([self.tramo(self.parada("DFW"))], "ES")
        self.assertFalse(any("visa" in c for c in contras))

    def test_espera_larga_noche_conexion_corta_y_cambio_de_aeropuerto(self):
        _, contras = ventajas.avisos_de_escalas([self.tramo(self.parada("MAD", 635, noche=True), self.parada("IST", 50),
                                                           self.parada("HND", 200, sale_de="NRT"))], "AR")
        self.assertIn("Espera de 10 h 35 min en Madrid, España (con noche).", contras)
        self.assertIn("Conexión corta en Estambul, Turquía: 50 min.", contras)
        self.assertTrue(any("llegás a HND y salís de NRT" in c for c in contras))

    def test_escalas_comodas_son_ventaja(self):
        pros, contras = ventajas.avisos_de_escalas([self.tramo(self.parada("MAD", 120)), self.tramo(self.parada("DOH", 200))], "AR")
        self.assertEqual(pros, ["Todas las escalas duran entre 1 h 30 min y 4 h."])
        self.assertEqual(contras, [])


if __name__ == "__main__":
    unittest.main()
