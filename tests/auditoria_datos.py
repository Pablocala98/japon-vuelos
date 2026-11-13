"""Auditoría de lo publicado: revisa cada opción real de docs/datos.js. Sin internet.

Uso: .venv/bin/python -m unittest discover -s tests -p "auditoria*.py"
GitHub la corre después de cada búsqueda. No está en las pruebas normales porque depende de los datos del día.
"""
import json
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
BUENOS_AIRES = {"EZE", "AEP"}
JAPON = {"NRT", "HND", "KIX", "ITM"}


def cargar() -> dict:
    texto = (RAIZ / "docs" / "datos.js").read_text(encoding="utf-8")
    return json.loads(texto[texto.index("{"):texto.rindex("}") + 1])


D = cargar()
P = D["preferencias"]


def dias(a: str, b: str) -> int:
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


def todas():
    return [("vuelo", o) for o in D["opciones"]] + [("stopover", o) for o in (D.get("stopovers") or {}).get("opciones", [])]


class Precios(unittest.TestCase):
    def test_las_cuentas_cierran(self):
        for _, o in todas():
            with self.subTest(o["id"]):
                self.assertAlmostEqual(o["precio_con_valijas"], o["precio_total"] + o["valijas_estimadas"], delta=1)
                self.assertAlmostEqual(o["por_persona_con_valijas"], o["precio_con_valijas"] / P["pasajeros"], delta=1)
                self.assertGreater(o["precio_total"], 300)  # para 2 personas a Japón, menos que esto es un error seguro
                if o["equipaje"] in ("incluida", "estimada"):
                    self.assertEqual(o["valijas_estimadas"], 0)

    def test_la_categoria_corresponde_al_precio(self):
        for _, o in todas():
            precio, topes = o["precio_con_valijas"], P["precios"]
            esperada = "ideal" if precio <= topes["ideal"] else "comprar" if precio <= topes["comprar"] else "casi" if precio <= topes["casi"] else "caro"
            with self.subTest(o["id"]):
                self.assertIn(esperada, o["categoria"])

    def test_la_confianza_es_coherente(self):
        for _, o in todas():
            with self.subTest(o["id"]):
                self.assertIn(o["confianza"], ("confirmado", "verificado", "google", "sin_confirmar"))
                self.assertEqual(o["confiable"], o["confianza"] != "sin_confirmar")
                if o["confianza"] == "confirmado":
                    self.assertTrue(o["precio_confirmado"])

    def test_lo_mas_barato_tiene_precio_respaldado(self):
        confiables = [o for o in D["opciones"] if o["confiable"]]
        mejor = (D.get("resumen") or {}).get("mejores_hoy", {}).get("total")
        if confiables and mejor:
            self.assertEqual(mejor["precio_con_valijas"], min(o["precio_con_valijas"] for o in confiables))


class Itinerarios(unittest.TestCase):
    def test_salen_de_buenos_aires_pasan_por_japon_y_vuelven(self):
        for tipo, o in todas():
            t = o["tramos"]
            with self.subTest(o["id"]):
                self.assertIn(t[0]["ruta"][0], BUENOS_AIRES)
                self.assertIn(t[-1]["ruta"][-1], BUENOS_AIRES)
                self.assertTrue(any(x["ruta"][-1] in JAPON for x in t))
                self.assertTrue(any(x["ruta"][0] in JAPON for x in t))
                self.assertEqual(len(t), 3 if tipo == "stopover" else 2)

    def test_cada_tramo_es_coherente(self):
        for _, o in todas():
            for i, t in enumerate(o["tramos"]):
                with self.subTest(f"{o['id']} tramo {i}"):
                    self.assertEqual(len(t["ruta"]), t["escalas"] + 2)
                    self.assertEqual([p["codigo"] for p in t["paradas"]], t["ruta"][1:-1])
                    self.assertEqual(t["dias_mas"], dias(t["salida"], t["llegada"]))
                    self.assertTrue(0 <= t["dias_mas"] <= 3)
                    self.assertTrue(1 <= t["horas"] <= 80)
                    if t.get("minutos"):
                        self.assertAlmostEqual(t["minutos"] / 60, t["horas"], delta=0.1)
                    esperas = [p["minutos"] for p in t["paradas"]]
                    if t["paradas"] and None not in esperas:
                        self.assertTrue(all(m >= 0 for m in esperas))
                        self.assertLess(sum(esperas) / 60, t["horas"])
                if i:
                    self.assertGreaterEqual(t["salida"][:10], o["tramos"][i - 1]["llegada"][:10])

    def test_dias_en_japon(self):
        for tipo, o in todas():
            t = o["tramos"]
            llega = next(x["llegada"] for x in t if x["ruta"][-1] in JAPON)
            sale = next(x["salida"] for x in t if x["ruta"][0] in JAPON)
            with self.subTest(o["id"]):
                self.assertEqual(o["dias_en_japon"], dias(llega, sale))
                self.assertLessEqual(abs(o["dias_en_japon"] - P["dias_en_japon"]), P["tolerancia_dias"])

    def test_el_destino_y_las_fechas_de_la_tarjeta(self):
        for _, o in todas():
            with self.subTest(o["id"]):
                self.assertIn(o["destino"], ("TYO", "OSA"))
                self.assertEqual(o["sale"], o["tramos"][0]["salida"])
                self.assertEqual(o["vuelve"], o["tramos"][-1]["salida"])
                self.assertTrue(D["ventana"]["desde"] <= o["sale"][:10] <= D["ventana"]["hasta"])

    def test_las_escalas_tienen_lugar(self):
        for _, o in todas():
            for t in o["tramos"]:
                for p in t["paradas"]:
                    with self.subTest(f"{o['id']} {p['codigo']}"):
                        self.assertTrue(p["ciudad"] and p["aeropuerto"])
                        self.assertEqual(len(p["pais_codigo"]), 2, "sin país: falta en vuelos/datos/aeropuertos.json")


class Links(unittest.TestCase):
    def test_los_links_son_seguros(self):
        for _, o in todas():
            for link in o["links_compra"] + o["links_google"]:
                with self.subTest(link["url"][:60]):
                    self.assertTrue(link["url"].startswith("https://"))

    def test_google_busca_las_mismas_fechas_y_aeropuertos(self):
        for _, o in todas():
            if o["desde_san_pablo"]:
                continue  # 2 pasajes: se revisa en las pruebas de enlaces
            consulta = parse_qs(urlparse(o["links_google"][0]["url"]).query)["q"][0]
            with self.subTest(o["id"]):
                for t in (o["tramos"][0], o["tramos"][-1]):
                    self.assertIn(t["salida"][:10], consulta)
                self.assertIn(o["tramos"][0]["ruta"][0], consulta)


class Vigencia(unittest.TestCase):
    def test_nada_viejo(self):
        for _, o in todas():
            with self.subTest(o["id"]):
                self.assertLessEqual(dias(o["visto"], D["fecha_datos"]), 14)
                self.assertGreaterEqual(dias(o["visto"], D["fecha_datos"]), 0)

    def test_stopovers_coherentes(self):
        for o in (D.get("stopovers") or {}).get("opciones", []):
            s = o["stopover"]
            with self.subTest(o["id"]):
                self.assertEqual(s["dias_en_escala"], dias(s["llega_escala"], s["sale_escala"]))
                self.assertEqual(s["dias_en_japon"], dias(s["llega_japon"], s["sale_japon"]))
                self.assertEqual(s["llega_buenos_aires"], o["tramos"][-1]["llegada"])
                self.assertGreaterEqual(s["dias_en_escala"], 1)


if __name__ == "__main__":
    unittest.main()
