"""Pruebas de la Etapa 3, sin internet."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from vuelos import analisis, evaluar
from vuelos.config import cargar_config

CFG = cargar_config()
MARGEN = CFG["precios"]["margen_igual"]


def tramo(ruta, salida, llegada, horas=30.0):
    return {"aerolineas": ["X"], "ruta": ruta, "salida": salida, "llegada": llegada, "escalas": 1, "horas": horas}


def opcion(precio, salida="2027-05-01", tipo="ida_y_vuelta", equipaje="incluida"):
    sale = date.fromisoformat(salida)
    llega = sale.replace(day=sale.day + 2)
    vuelve = sale.replace(day=sale.day + 22)
    return {"tipo": tipo, "fuente": "ignav", "precio_total": precio, "moneda": "USD", "precio_verificado": True,
            "equipaje": equipaje, "tramos": [
                tramo(["EZE", "MAD", "NRT"], f"{salida}T20:00", f"{llega.isoformat()}T10:00"),
                tramo(["NRT", "MAD", "EZE"], f"{vuelve.isoformat()}T20:00", f"{vuelve.isoformat()}T23:00")]}


def dia(*opciones):
    return [evaluar.completar(o, CFG) for o in opciones]


class Comparacion(unittest.TestCase):
    def test_mejoro_empeoro_e_igual(self):
        self.assertEqual(analisis.comparar(dia(opcion(4000)), dia(opcion(4100, "2027-05-02")), MARGEN)["estado"], "mejoró")
        self.assertEqual(analisis.comparar(dia(opcion(4200)), dia(opcion(4100, "2027-05-02")), MARGEN)["estado"], "empeoró")
        self.assertEqual(analisis.comparar(dia(opcion(4110)), dia(opcion(4100, "2027-05-02")), MARGEN)["estado"], "igual")

    def test_sin_dia_anterior(self):
        resultado = analisis.comparar(dia(opcion(4000)), None, MARGEN)
        self.assertEqual(resultado["estado"], "sin_datos")
        self.assertIsNone(resultado["diferencia"])

    def test_avisa_cuando_cruza_un_umbral(self):
        resultado = analisis.comparar(dia(opcion(3700)), dia(opcion(3900, "2027-05-02")), MARGEN)
        self.assertEqual(resultado["cruzo_umbral"], "Entró en ✅ comprar")
        resultado = analisis.comparar(dia(opcion(4100)), dia(opcion(3900, "2027-05-02")), MARGEN)
        self.assertEqual(resultado["cruzo_umbral"], "Salió de 👀 casi")
        self.assertIsNone(analisis.comparar(dia(opcion(5000)), dia(opcion(5500)), MARGEN)["cruzo_umbral"])

    def test_compara_el_mismo_vuelo_aunque_no_sea_el_mejor(self):
        hoy = dia(opcion(4000, "2027-04-01"), opcion(5000))
        ayer = dia(opcion(5200), opcion(6000, "2027-06-01"))
        resultado = analisis.comparar(hoy, ayer, MARGEN)
        mismos = resultado["mismos_vuelos"]
        self.assertEqual((mismos["comparados"], mismos["bajaron"], mismos["cambio_promedio"]), (1, 1, -200))
        self.assertIsNone(resultado["aviso"])

    def test_avisa_si_ningun_vuelo_coincide(self):
        resultado = analisis.comparar(dia(opcion(6000)), dia(opcion(4300, "2027-04-02")), MARGEN)
        self.assertEqual(resultado["estado"], "empeoró")
        self.assertIn("otras fechas", resultado["aviso"])


class Historial(unittest.TestCase):
    def test_reevalua_dias_viejos_con_la_config_de_hoy(self):
        fuera = opcion(3000)
        fuera["tramos"][1]["salida"] = "2027-05-30T20:00"  # 28 días en Japón: hoy no cumple
        validas = analisis.reevaluar({"opciones": [fuera, opcion(4000)]}, CFG)
        self.assertEqual([o["precio_total"] for o in validas], [4000])

    def test_evolucion_separa_buenos_aires_y_san_pablo(self):
        dias = {"2026-11-06": {"opciones": [opcion(4000), opcion(3500, "2027-05-02", tipo="san_pablo")]},
                "2026-11-07": {"opciones": [opcion(4100)]}}
        filas = analisis.evolucion(dias, CFG)
        # El 7, San Pablo sigue vigente desde el 6; el vuelo desde Buenos Aires es el mismo y queda con su precio nuevo.
        self.assertEqual([(f["total"], f["buenos_aires"], f["san_pablo"]) for f in filas], [(3500, 4000, 3500), (3500, 4100, 3500)])

    def test_ultimo_tramo_corto_usa_el_dia_mas_reciente_con_dato(self):
        dias = {"a": {"san_pablo": [{"tramo_corto": 610}]}, "b": {"san_pablo": [{"tramo_corto": None}]}, "c": {}}
        self.assertEqual(analisis.ultimo_tramo_corto(dias), 610)


class Vigentes(unittest.TestCase):
    def test_una_buena_opcion_de_ayer_sigue_disponible_con_su_fecha(self):
        dias = {"2026-11-09": {"opciones": [opcion(3500, "2027-05-02")]}, "2026-11-10": {"opciones": [opcion(4500)]}}
        lista = analisis.vigentes(dias, "2026-11-10", CFG)
        self.assertEqual([(o["precio_total"], o["visto"]) for o in lista], [(3500, "2026-11-09"), (4500, "2026-11-10")])

    def test_el_mismo_vuelo_queda_con_el_precio_mas_reciente(self):
        dias = {"2026-11-09": {"opciones": [opcion(3500)]}, "2026-11-10": {"opciones": [opcion(3700)]}}
        self.assertEqual([(o["precio_total"], o["visto"]) for o in analisis.vigentes(dias, "2026-11-10", CFG)], [(3700, "2026-11-10")])

    def test_despues_de_3_dias_deja_de_mostrarse(self):
        dias = {"2026-11-06": {"opciones": [opcion(3000, "2027-05-02")]}, "2026-11-10": {"opciones": [opcion(4500)]}}
        self.assertEqual([o["precio_total"] for o in analisis.vigentes(dias, "2026-11-10", CFG)], [4500])

    def test_la_comparacion_no_avisa_si_la_mejor_sigue_siendo_la_misma(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = Path(carpeta)
            (datos / "resultados").mkdir()
            (datos / "resultados" / "2026-11-09.json").write_text(json.dumps({"opciones": [opcion(3500, "2027-05-02")]}), encoding="utf-8")
            (datos / "resultados" / "2026-11-10.json").write_text(json.dumps({"opciones": [opcion(4500)]}), encoding="utf-8")
            comparacion = analisis.generar(CFG, date(2026, 11, 10), datos)["comparacion"]
            self.assertEqual(comparacion["estado"], "igual")
            self.assertIsNone(comparacion["aviso"])


class PrecioConfirmado(unittest.TestCase):
    def test_los_links_actualizan_el_precio_de_san_pablo(self):
        base = {**opcion(3528, tipo="san_pablo"), "desglose": {"desde_san_pablo": 2548, "buenos_aires_san_pablo": 980}}
        nueva = evaluar.confirmar_precio(evaluar.completar(base, CFG), [2552, 908], "2026-11-10", CFG)
        self.assertEqual(nueva["precio_total"], 3460)
        self.assertEqual(nueva["desglose"], {"desde_san_pablo": 2552, "buenos_aires_san_pablo": 908})
        self.assertEqual(nueva["precio_confirmado"], {"total": 3460, "fecha": "2026-11-10"})
        self.assertEqual(nueva["precio_con_valijas"], 3460)  # equipaje "incluida" en este ejemplo


class Fechas(unittest.TestCase):
    memoria = {
        "BUE-TYO": {"22": {"2027-05-01": {"regreso": "2027-05-23", "precio": 4500, "visto": "2026-11-09"},
                           "2027-05-20": {"regreso": "2027-06-11", "precio": 4300, "visto": "2026-11-09"}},
                    "30": {"2027-05-01": {"regreso": "2027-05-31", "precio": 100, "visto": "2026-11-09"}}},
        "GRU-TYO": {"22": {"2027-06-06": {"regreso": "2027-06-28", "precio": 2548, "visto": "2026-11-09"},
                           "2027-04-01": {"regreso": "2027-04-23", "precio": 2000, "visto": "2026-10-01"}}},
    }

    def test_ranking_suma_el_tramo_corto_y_ignora_estadias_y_datos_viejos(self):
        fechas = analisis.analisis_fechas(self.memoria, CFG, date(2026, 11, 9), 980)
        self.assertEqual([(c["ruta"], c["precio_comparable"]) for c in fechas["ranking"]],
                         [("GRU-TYO", 3528), ("BUE-TYO", 4300), ("BUE-TYO", 4500)])
        self.assertEqual(fechas["ranking"][0]["dias_en_japon_aprox"], 20)

    def test_sin_tramo_corto_san_pablo_no_entra_al_ranking(self):
        fechas = analisis.analisis_fechas(self.memoria, CFG, date(2026, 11, 9), None)
        self.assertEqual({c["ruta"] for c in fechas["ranking"]}, {"BUE-TYO"})
        self.assertIn("GRU-TYO", {c["ruta"] for c in fechas["celdas"]})

    def test_mejor_por_mes(self):
        fechas = analisis.analisis_fechas(self.memoria, CFG, date(2026, 11, 9), 980)
        self.assertEqual([(c["ruta"], c["salida"]) for c in fechas["mejor_por_mes"]], [("BUE-TYO", "2027-05-20"), ("GRU-TYO", "2027-06-06")])


class RankingVariado(unittest.TestCase):
    def test_como_maximo_4_fechas_por_ruta(self):
        memoria = {"GRU-TYO": {"22": {f"2027-05-{d:02d}": {"regreso": None, "precio": 2500 + d, "visto": "2026-11-09"} for d in range(1, 11)}},
                   "BUE-TYO": {"22": {"2027-05-01": {"regreso": None, "precio": 4300, "visto": "2026-11-09"}}}}
        ranking = analisis.analisis_fechas(memoria, CFG, date(2026, 11, 9), 980)["ranking"]
        self.assertEqual(sum(c["ruta"] == "GRU-TYO" for c in ranking), 4)
        self.assertIn("BUE-TYO", {c["ruta"] for c in ranking})


class Generar(unittest.TestCase):
    def test_escribe_el_analisis_del_dia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = Path(carpeta)
            (datos / "resultados").mkdir()
            for fecha, precio in (("2026-11-06", 4400), ("2026-11-09", 4300)):
                (datos / "resultados" / f"{fecha}.json").write_text(json.dumps({"opciones": [opcion(precio)]}), encoding="utf-8")
            resultado = analisis.generar(CFG, date(2026, 11, 9), datos)
            self.assertEqual(resultado["comparado_con"], "2026-11-06")
            self.assertEqual(resultado["comparacion"]["estado"], "mejoró")
            self.assertEqual(resultado["comparacion"]["mismos_vuelos"]["cambio_promedio"], -100)
            self.assertTrue((datos / "analisis" / "2026-11-09.json").exists())

    def test_la_exploracion_del_mismo_dia_cuenta(self):
        with tempfile.TemporaryDirectory() as carpeta:
            datos = Path(carpeta)
            for sub, precio in (("resultados", 6000), ("exploracion", 3528)):
                (datos / sub).mkdir()
                (datos / sub / "2026-11-09.json").write_text(json.dumps({"opciones": [opcion(precio, f"2027-05-0{1 if sub == 'resultados' else 2}")],
                                                                         "san_pablo": [{"tramo_corto": 980}] if sub == "exploracion" else []}), encoding="utf-8")
            (datos / "exploracion" / "calendario.json").write_text("{}", encoding="utf-8")  # no es un día: se ignora
            resultado = analisis.generar(CFG, date(2026, 11, 9), datos)
            self.assertEqual(resultado["mejores_hoy"]["total"]["precio_total"], 3528)
            self.assertEqual(resultado["fechas"]["tramo_corto_usado"], 980)


if __name__ == "__main__":
    unittest.main()
