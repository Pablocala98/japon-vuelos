"""Pruebas de la Etapa 5, sin internet."""
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from vuelos import buscar, enlaces, evaluar, ventajas
from vuelos.config import cargar_config
from vuelos.fuentes import ignav

CFG = cargar_config()


def tramo(ruta, salida, llegada, escalas=1, horas=28.0):
    return {"aerolineas": ["Iberia"], "ruta": ruta, "salida": salida, "llegada": llegada, "escalas": escalas, "horas": horas}


def opcion(precio, equipaje="incluida", tipo="ida_y_vuelta", salida="2027-05-10", vuelta=("NRT", "MAD", "EZE"), **extra):
    base = {"tipo": tipo, "fuente": "ignav", "precio_total": precio, "moneda": "USD", "precio_verificado": True,
            "equipaje": equipaje, "tramos": [tramo(["EZE", "MAD", "NRT"], f"{salida}T20:00", "2027-05-12T15:00"),
                                             tramo(list(vuelta), "2027-06-01T20:00", "2027-06-02T10:00")], **extra}
    return evaluar.completar(base, CFG)


class LinksDeIgnav(unittest.TestCase):
    def test_ordena_vuelo_exacto_y_aerolinea_primero_y_saca_repetidos(self):
        respuesta = {"booking_options": [
            {"legs": ["outbound", "inbound"], "links": [
                {"provider_name": "Expedia", "provider_type": "third_party", "specificity": "exact_flight",
                 "price": {"amount": 4700, "currency": "USD"}, "url": "https://e/1"},
                {"provider_name": "Iberia", "provider_type": "airline", "specificity": "exact_flight",
                 "price": {"amount": 4762, "currency": "USD"}, "url": "https://ib/1"},
                {"provider_name": "Iberia", "provider_type": "airline", "specificity": "search_results", "url": "https://ib/2"},
                {"provider_name": "Iberia", "provider_type": "airline", "specificity": "exact_flight", "url": "https://ib/1"},
            ]}]}
        links = ignav.links(respuesta)
        self.assertEqual([l["url"] for l in links], ["https://ib/1", "https://e/1", "https://ib/2"])
        self.assertEqual(links[0]["alcance"], "ida y vuelta")
        self.assertTrue(links[0]["exacto"] and links[0]["aerolinea"])

    def test_el_pedido_de_links_solo_manda_lo_que_acepta(self):
        fuente = ignav.Ignav("x", mock.Mock(), 2, 1, 1, 2)
        with mock.patch("vuelos.fuentes.ignav.pedir", return_value={}) as pedir:
            fuente.links_de_compra("abc")
        self.assertEqual(pedir.call_args.kwargs["json"], {"ignav_id": "abc"})


class CandidatasParaLinks(unittest.TestCase):
    def test_la_mejor_del_dia_y_las_que_llegan_a_casi(self):
        opciones = [opcion(5000, ignav_id="c"), opcion(3900, ignav_id="b"), opcion(3700, ignav_id="a"), opcion(4500, ignav_id="d")]
        self.assertEqual([o["ignav_id"] for o in buscar.candidatas_para_links(opciones)], ["a", "b"])

    def test_sin_numero_de_ignav_no_se_puede_pedir(self):
        self.assertEqual(buscar.candidatas_para_links([opcion(3000)]), [])


class GoogleFlights(unittest.TestCase):
    def consulta(self, url):
        return parse_qs(urlparse(url).query)["q"][0]

    def test_ida_y_vuelta(self):
        links = enlaces.google_flights(opcion(4000), 2)
        self.assertEqual(self.consulta(links[0]["url"]), "Flights from EZE to NRT on 2027-05-10 through 2027-06-01 for 2 adults")

    def test_open_jaw_es_multidestino(self):
        links = enlaces.google_flights(opcion(4000, vuelta=("KIX", "MAD", "EZE")), 2)
        self.assertIn("Multi-city", self.consulta(links[0]["url"]))
        self.assertIn("from KIX to EZE on 2027-06-01", self.consulta(links[0]["url"]))

    def test_san_pablo_da_un_link_por_pasaje(self):
        partes = {"largo": {"origen": "GRU", "destino": "NRT", "salida": "2027-06-06T19:20", "regreso": "2027-06-28T10:35"},
                  "corto": {"origen": "AEP", "destino": "GRU", "salida": "2027-06-06T11:55", "regreso": "2027-06-29T15:40"}}
        links = enlaces.google_flights(opcion(3528, tipo="san_pablo", partes=partes), 2)
        self.assertEqual(len(links), 2)
        self.assertIn("from GRU to NRT on 2027-06-06 through 2027-06-28", self.consulta(links[0]["url"]))
        self.assertIn("from AEP to GRU on 2027-06-06 through 2027-06-29", self.consulta(links[1]["url"]))


class VentajasYDesventajas(unittest.TestCase):
    def test_la_mas_barata_dentro_del_presupuesto(self):
        o = opcion(3700)
        r = ventajas.evaluar_opcion(o, o["precio_con_valijas"], CFG)
        self.assertIn("Es la más barata disponible.", r["ventajas"])
        self.assertIn("Entra en tu presupuesto: ✅ comprar.", r["ventajas"])
        self.assertIn("La valija despachada está incluida.", r["ventajas"])
        self.assertIn("Un solo pasaje: si un vuelo se atrasa, la aerolínea te reubica.", r["ventajas"])

    def test_san_pablo_sin_valijas_dentro_del_tope_pero_con_valijas_no(self):
        o = opcion(3528, equipaje="sin_confirmar", tipo="san_pablo", tramos_valija_sin_confirmar=4)
        r = ventajas.evaluar_opcion(o, 3000, CFG)
        self.assertIn("Sin valijas (USD 3.528) entra en tu tope de USD 3.800.", r["ventajas"])
        self.assertIn("Con las valijas estimadas se pasa de tu tope por USD 368.", r["desventajas"])
        self.assertFalse(any("Entra en tu presupuesto" in v for v in r["ventajas"]))
        self.assertTrue(any("2 pasajes separados" in d for d in r["desventajas"]))
        self.assertTrue(any("más que la más barata" in d for d in r["desventajas"]))

    def test_casi_no_dice_que_entra_en_el_presupuesto(self):
        o = opcion(3900)
        r = ventajas.evaluar_opcion(o, 3900, CFG)
        self.assertIn("Está cerca de tu tope: 👀 casi.", r["ventajas"])
        self.assertIn("Se pasa de tu tope por USD 100.", r["desventajas"])

    def test_dias_salida_en_abril_y_llegada_de_noche(self):
        o = opcion(5000, salida="2027-04-25")
        o["tramos"][0]["llegada"] = "2027-04-27T23:10"
        o["dias_en_japon"] = 21
        r = ventajas.evaluar_opcion(o, 5000, CFG)
        self.assertIn("Sale en abril: preferís mayo o junio.", r["desventajas"])
        self.assertIn("Llegás a Japón a las 23:10.", r["desventajas"])
        self.assertIn("21 días en Japón (querés 20).", r["desventajas"])

    def test_open_jaw(self):
        o = opcion(5000, vuelta=("KIX", "MAD", "EZE"))
        self.assertTrue(any("volvés desde KIX" in v for v in ventajas.evaluar_opcion(o, 5000, CFG)["ventajas"]))


class JuntarConservaLinks(unittest.TestCase):
    def test_si_gana_otra_fuente_se_quedan_el_numero_y_los_links_de_ignav(self):
        de_ignav = opcion(4800, ignav_id="abc", links_compra=[{"url": "u"}])
        de_google = {**opcion(4700), "fuente": "serpapi", "ignav_id": None}
        juntas = evaluar.juntar([de_ignav, de_google])
        self.assertEqual(len(juntas), 1)
        self.assertEqual(juntas[0]["precio_total"], 4700)
        self.assertEqual(juntas[0]["ignav_id"], "abc")
        self.assertEqual(juntas[0]["links_compra"], [{"url": "u"}])


if __name__ == "__main__":
    unittest.main()
