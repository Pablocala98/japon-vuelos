"""La página muestra lo que dijo la fuente, sin inventar: de la respuesta cruda a lo que ve el usuario. Sin internet."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from vuelos import analisis, evaluar, publicar, ventajas
from vuelos.config import cargar_config
from vuelos.fuentes import ignav, serpapi

CFG = cargar_config()


def segmento(desde, hasta, sale_local, llega_local, sale_utc, llega_utc, codigo="LH", nombre="Lufthansa"):
    return {"departure_airport": desde, "arrival_airport": hasta, "departure_time_local": sale_local, "arrival_time_local": llega_local,
            "departure_time_utc": sale_utc, "arrival_time_utc": llega_utc, "marketing_carrier_code": codigo, "operating_carrier_name": nombre}


def itinerario_ignav(precio=5860, estado="verified", valija="unknown"):
    """Imita una respuesta de Ignav: Buenos Aires-Fráncfort-Tokio y vuelta."""
    return {
        "ignav_id": "abc123", "price": {"amount": precio, "currency": "USD", "status": estado}, "baggage_pricing": {"status": valija},
        "outbound": {"duration_minutes": 1726, "segments": [
            segmento("EZE", "FRA", "2027-05-10T14:20:00", "2027-05-11T07:10:00", "2027-05-10T17:20:00", "2027-05-11T05:10:00"),
            segmento("FRA", "NRT", "2027-05-11T10:00:00", "2027-05-12T06:06:00", "2027-05-11T08:00:00", "2027-05-11T21:06:00")]},
        "inbound": {"duration_minutes": 1855, "segments": [
            segmento("NRT", "FRA", "2027-05-31T11:00:00", "2027-05-31T17:30:00", "2027-05-31T02:00:00", "2027-05-31T15:30:00"),
            segmento("FRA", "EZE", "2027-05-31T22:15:00", "2027-06-01T07:55:00", "2027-05-31T20:15:00", "2027-06-01T10:55:00")]},
    }


def opcion_de_ignav(**cambios):
    return evaluar.completar(ignav.normalizar(itinerario_ignav(**cambios), "ida_y_vuelta"), CFG)


class DeLaFuenteAlFormatoComun(unittest.TestCase):
    def test_ignav_conserva_precio_horarios_minutos_y_escalas(self):
        o = ignav.normalizar(itinerario_ignav(), "ida_y_vuelta")
        self.assertEqual((o["precio_total"], o["moneda"], o["precio_verificado"], o["equipaje"]), (5860, "USD", True, "sin_confirmar"))
        ida, vuelta = o["tramos"]
        self.assertEqual(ida["ruta"], ["EZE", "FRA", "NRT"])
        self.assertEqual((ida["salida"], ida["llegada"], ida["minutos"], ida["escalas"]), ("2027-05-10T14:20", "2027-05-12T06:06", 1726, 1))
        self.assertEqual(ida["aerolineas"], ["Lufthansa"])
        # Espera en Fráncfort: de 05:10 a 08:00 UTC = 170 minutos, calculado con las horas UTC de la fuente.
        self.assertEqual(ida["paradas"], [{"aeropuerto": "FRA", "sale_de": None, "minutos": 170, "noche": False, "cambio_pasaje": False}])
        self.assertEqual(vuelta["paradas"][0]["minutos"], 285)

    def test_la_valija_solo_se_da_por_incluida_si_la_fuente_lo_dice(self):
        self.assertEqual(ignav.normalizar(itinerario_ignav(valija="reported_included"), "x")["equipaje"], "incluida")
        self.assertEqual(ignav.normalizar(itinerario_ignav(valija="estimated"), "x")["equipaje"], "estimada")
        self.assertEqual(ignav.normalizar(itinerario_ignav(valija="algo_raro"), "x")["equipaje"], "sin_confirmar")

    def test_serpapi_conserva_horarios_y_espera(self):
        opcion = {"price": 5955, "total_duration": 1730, "layovers": [{"duration": 170, "overnight": False}], "flights": [
            {"airline": "Lufthansa", "departure_airport": {"id": "EZE", "time": "2027-05-10 14:20"}, "arrival_airport": {"id": "FRA", "time": "2027-05-11 07:10"}},
            {"airline": "Lufthansa", "departure_airport": {"id": "FRA", "time": "2027-05-11 10:00"}, "arrival_airport": {"id": "NRT", "time": "2027-05-12 06:06"}}]}
        t = serpapi.tramo(opcion)
        self.assertEqual((t["salida"], t["llegada"], t["minutos"], t["ruta"]), ("2027-05-10T14:20", "2027-05-12T06:06", 1730, ["EZE", "FRA", "NRT"]))
        self.assertEqual(t["paradas"][0]["minutos"], 170)
        self.assertEqual(serpapi.armar("ida_y_vuelta", [t, t], 5955)["equipaje"], "sin_confirmar")  # Google no informa la valija


class LoQueMuestraLaPagina(unittest.TestCase):
    def setUp(self):
        self.fuente = opcion_de_ignav()
        self.pagina = publicar.para_pagina(self.fuente, self.fuente["precio_con_valijas"], None, CFG)

    def test_precios_salen_de_la_fuente_y_las_cuentas_cierran(self):
        p = self.pagina
        self.assertEqual(p["precio_total"], 5860)
        valijas = 2 * 2 * CFG["equipaje"]["costo_estimado_valija_por_tramo"]  # 2 tramos x 2 personas, valija sin confirmar
        self.assertEqual((p["valijas_estimadas"], p["precio_con_valijas"]), (valijas, 5860 + valijas))
        self.assertEqual(p["por_persona_con_valijas"], round((5860 + valijas) / 2))

    def test_horarios_aeropuertos_y_escalas_iguales_a_la_fuente(self):
        for de_fuente, en_pagina in zip(self.fuente["tramos"], self.pagina["tramos"]):
            for campo in ("ruta", "salida", "llegada", "escalas", "minutos", "aerolineas"):
                self.assertEqual(en_pagina[campo], de_fuente[campo], campo)
            self.assertEqual([p["codigo"] for p in en_pagina["paradas"]], de_fuente["ruta"][1:-1])
            self.assertEqual([p["minutos"] for p in en_pagina["paradas"]], [p["minutos"] for p in de_fuente["paradas"]])
        ida = self.pagina["tramos"][0]
        self.assertEqual(ida["dias_mas"], 2)  # sale el 10 y llega el 12 (hora local)
        self.assertEqual(ida["horas_escalas"], round(170 / 60, 1))
        self.assertEqual(ida["paradas"][0]["pais_codigo"], "DE")

    def test_dias_en_japon_y_destino(self):
        self.assertEqual(self.pagina["dias_en_japon"], 19)  # llega el 12/5, sale el 31/5
        self.assertEqual(self.pagina["destino"], "TYO")

    def test_no_inventa_links_de_compra_y_google_usa_las_fechas_del_vuelo(self):
        self.assertEqual(self.pagina["links_compra"], [])
        consulta = parse_qs(urlparse(self.pagina["links_google"][0]["url"]).query)["q"][0]
        self.assertEqual(consulta, "Flights from EZE to NRT on 2027-05-10 through 2027-05-31 for 2 adults")


class Confianza(unittest.TestCase):
    def test_niveles(self):
        self.assertEqual(opcion_de_ignav()["confianza"], "verificado")
        self.assertEqual(opcion_de_ignav(estado="unverified")["confianza"], "sin_confirmar")
        self.assertFalse(opcion_de_ignav(estado="unverified")["confiable"])
        google = evaluar.completar({**ignav.normalizar(itinerario_ignav(estado="unverified"), "x"), "fuente": "serpapi"}, CFG)
        self.assertEqual(google["confianza"], "google")
        confirmada = evaluar.confirmar_precio(opcion_de_ignav(estado="unverified"), [5900], "2026-11-13", CFG)
        self.assertEqual((confirmada["confianza"], confirmada["confiable"], confirmada["precio_total"]), ("confirmado", True, 5900))

    def test_si_google_tambien_lo_vio_deja_de_estar_sin_confirmar(self):
        dudosa = opcion_de_ignav(estado="unverified")
        de_google = {**dudosa, "fuente": "serpapi", "precio_total": dudosa["precio_total"] + 50, "precios_por_fuente": None}
        unida = evaluar.juntar([dudosa, evaluar.completar(de_google, CFG)])[0]
        self.assertTrue(unida["confiable"])

    def test_la_mejor_nunca_es_un_precio_sin_confirmar(self):
        dudosa = opcion_de_ignav(precio=2695, estado="unverified")
        buena = opcion_de_ignav(precio=5860)
        self.assertEqual(analisis.mejor([dudosa, buena])["precio_total"], 5860)
        self.assertIsNone(analisis.mejor([dudosa]))

    def test_sin_confirmar_no_dice_que_es_la_mas_barata_ni_que_entra_en_el_presupuesto(self):
        dudosa = opcion_de_ignav(precio=2695, estado="unverified")
        r = ventajas.evaluar_opcion(dudosa, 99999, CFG)
        self.assertFalse(any("más barata" in v or "presupuesto" in v for v in r["ventajas"]))
        self.assertTrue(any("sin confirmar" in d for d in r["desventajas"]))

    def test_links_que_fallaron_quedan_anotados_y_se_arrastran(self):
        dudosa = {**ignav.normalizar(itinerario_ignav(precio=2695, estado="unverified"), "ida_y_vuelta")}
        dias = {"2026-11-12": {"opciones": [dudosa], "errores": ["link abc123: Ignav: falla temporal (HTTP 424)"]},
                "2026-11-13": {"opciones": [{**dudosa, "ignav_id": "otro"}], "errores": []}}
        lista = analisis.vigentes(dias, "2026-11-13", CFG)
        self.assertEqual(lista[0]["links_fallidos"], ["2026-11-12"])
        r = ventajas.evaluar_opcion(lista[0], 99999, CFG)
        self.assertIn("La fuente no pudo dar dónde comprarlo (1 vez).", r["desventajas"])

    def test_la_pagina_elige_la_mas_barata_respaldada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = Path(carpeta)
            (datos / "resultados").mkdir()
            dia = {"opciones": [ignav.normalizar(itinerario_ignav(precio=2695, estado="unverified"), "ida_y_vuelta"),
                                ignav.normalizar({**itinerario_ignav(precio=5860), "ignav_id": "b"}, "ida_y_vuelta")]}
            dia["opciones"][1]["tramos"][0]["salida"] = "2027-05-10T15:00"  # otro vuelo
            (datos / "resultados" / "2026-11-13.json").write_text(json.dumps(dia), encoding="utf-8")
            resumen = analisis.generar(CFG, date(2026, 11, 13), datos)
            self.assertEqual(resumen["mejores_hoy"]["total"]["precio_total"], 5860)


if __name__ == "__main__":
    unittest.main()
