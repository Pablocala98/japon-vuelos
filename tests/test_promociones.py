"""Pruebas de la Etapa 4, con feeds simulados: no usan internet."""
import time
import unittest
from datetime import datetime, timedelta, timezone

from vuelos import promociones
from vuelos.config import cargar_config

CFG = cargar_config()
MEDIOS = CFG["medios_de_pago"]


def entrada(titulo, resumen="", etiquetas=(), horas_atras=2, link=None):
    publicada = (datetime.now(timezone.utc) - timedelta(hours=horas_atras)).timetuple()
    return {"title": titulo, "summary": resumen, "tags": [{"term": e} for e in etiquetas],
            "published_parsed": time.struct_time(publicada), "link": link or f"https://x/{titulo[:20]}", "id": link or titulo}


class Clasificar(unittest.TestCase):
    def test_japon_aunque_tenga_tildes(self):
        promo = promociones.clasificar(entrada("¡Vuelos a Japón! Tokio desde U$D 1.300"), MEDIOS)
        self.assertTrue(promo["japon"])
        self.assertIn("japon", promo["motivos"][0])

    def test_vuelos_a_asia(self):
        promo = promociones.clasificar(entrada("Cyber Monday: Vuelos a Asia con hasta U$D 120 de Descuento", etiquetas=["Vuelos a Asia"]), MEDIOS)
        self.assertIn("Vuelos a Asia", promo["motivos"])

    def test_promo_de_aerolinea_que_vuela_a_japon(self):
        promo = promociones.clasificar(entrada("Turkish: 20% de descuento en vuelos a todo el mundo"), MEDIOS)
        self.assertIn("Turkish", promo["motivos"][0])

    def test_galicia_visa_en_vuelos(self):
        promo = promociones.clasificar(entrada("Vuelos a Europa en 6 cuotas sin interés con Galicia Visa"), MEDIOS)
        self.assertIn("Con Galicia Visa", promo["motivos"])
        self.assertIsNone(promo["aviso"])

    def test_galicia_solo_eminent_no_se_muestra(self):
        self.assertIsNone(promociones.clasificar(entrada("Vuelos con 12 cuotas para Galicia Éminent"), MEDIOS))

    def test_galicia_eminent_y_visa_avisa(self):
        promo = promociones.clasificar(entrada("Vuelos: Galicia Éminent y Galicia Visa con cuotas"), MEDIOS)
        self.assertIn("Con Galicia Visa", promo["motivos"])
        self.assertIn("Eminent", promo["aviso"])

    def test_galicia_en_hoteles_no_sirve(self):
        self.assertIsNone(promociones.clasificar(entrada("Hoteles en Bariloche en 18 cuotas con Galicia", etiquetas=["Alojamiento"]), MEDIOS))

    def test_no_confunde_partes_de_palabras(self):
        self.assertIsNone(promociones.clasificar(entrada("Paquetes a Punta Cana con Vuelos Directos", etiquetas=["Vuelos a América"]), MEDIOS))
        self.assertIsNone(promociones.clasificar(entrada("Vuelos y Hotel en Copacabana", etiquetas=["Vuelos a Brasil"]), MEDIOS))

    def test_promo_de_aerolinea_a_un_solo_destino_no_sirve(self):
        self.assertIsNone(promociones.clasificar(entrada("Vuelos a Cabo Frío con LATAM en cuotas", etiquetas=["Vuelos a Brasil"]), MEDIOS))

    def test_galicia_en_hoteles_con_etiqueta_de_vuelos_no_sirve(self):
        self.assertIsNone(promociones.clasificar(entrada("Hoteles RIU en Cancún en 3 cuotas", "con Galicia Mastercard",
                                                         etiquetas=["Vuelos a América"]), MEDIOS))

    def test_lo_que_no_tiene_que_ver_se_descarta(self):
        self.assertIsNone(promociones.clasificar(entrada("Vuelos a Florianópolis desde U$D 222", etiquetas=["Vuelos a Brasil"]), MEDIOS))


class Buscar(unittest.TestCase):
    def test_filtra_por_horas_saca_repetidos_y_sigue_si_un_feed_falla(self):
        def leer(url, agent):
            if "galicia" in url:
                raise OSError("sin red")
            if "asia" in url:
                return {"status": 200, "entries": [entrada("Vuelos a Japón", link="a"), entrada("Vuelos a Asia viejos", etiquetas=["Vuelos a Asia"], horas_atras=200)]}
            return {"status": 200, "entries": [entrada("Vuelos a Japón", link="a"), entrada("Vuelos a Corea con descuento", horas_atras=5)]}
        resultado = promociones.buscar(CFG, leer=leer, pausa=0)
        self.assertEqual([p["titulo"] for p in resultado["promociones"]], ["Vuelos a Japón", "Vuelos a Corea con descuento"])
        self.assertEqual(len(resultado["errores"]), 1)
        self.assertIn("Búsqueda Galicia", resultado["errores"][0])

    def test_feed_caido_queda_como_error(self):
        resultado = promociones.buscar(CFG, leer=lambda url, agent: {"status": 404, "bozo": 1, "entries": []}, pausa=0)
        self.assertEqual(resultado["promociones"], [])
        self.assertEqual(len(resultado["errores"]), len(promociones.FEEDS))


if __name__ == "__main__":
    unittest.main()
