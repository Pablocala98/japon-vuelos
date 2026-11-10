"""Pruebas sin internet: no gastan consultas. Uso: .venv/bin/python -m unittest discover tests"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from vuelos import evaluar, planificador
from vuelos.config import cargar_config
from vuelos.consultas import Contador, CupoDelDia
from vuelos.fuentes import ignav, serpapi

CFG = cargar_config()
RESTRICCIONES = CFG["restricciones"]


def tramo(ruta, salida, llegada, escalas=1, horas=30.0, aerolinea="X"):
    return {"aerolineas": [aerolinea], "ruta": ruta, "salida": salida, "llegada": llegada, "escalas": escalas, "horas": horas}


def opcion(precio, tramos, equipaje="sin_confirmar", fuente="ignav"):
    return {"tipo": "ida_y_vuelta", "fuente": fuente, "precio_total": precio, "moneda": "USD",
            "precio_verificado": True, "equipaje": equipaje, "tramos": tramos}


IDA = tramo(["EZE", "MAD", "NRT"], "2027-05-23T18:05", "2027-05-25T14:00")
VUELTA = tramo(["NRT", "MAD", "EZE"], "2027-06-15T22:10", "2027-06-16T20:00")


class Filtros(unittest.TestCase):
    def test_acepta_lo_que_cumple(self):
        self.assertIsNone(evaluar.motivo_descarte(opcion(5000, [IDA, VUELTA]), RESTRICCIONES))

    def test_descarta_mas_de_36_horas(self):
        larga = tramo(["KIX", "IST", "GRU", "EZE"], "2027-06-15T22:05", "2027-06-17T10:00", 2, 36.3)
        self.assertIn("36", evaluar.motivo_descarte(opcion(5786, [IDA, larga]), RESTRICCIONES))

    def test_descarta_mas_de_2_escalas(self):
        muchas = tramo(["A", "B", "C", "D", "E"], "2027-05-23T10:00", "2027-05-24T10:00", 3, 20)
        self.assertIn("escalas", evaluar.motivo_descarte(opcion(4000, [muchas, VUELTA]), RESTRICCIONES))

    def test_descarta_sin_precio_o_sin_duracion(self):
        self.assertEqual(evaluar.motivo_descarte(opcion(None, [IDA, VUELTA]), RESTRICCIONES), "sin precio")
        sin_horas = tramo(["EZE", "NRT"], "x", "y", 0, None)
        self.assertEqual(evaluar.motivo_descarte(opcion(4000, [sin_horas, VUELTA]), RESTRICCIONES), "sin duración informada")


class DiasEnJapon(unittest.TestCase):
    def test_cuenta_del_dia_de_llegada_al_dia_de_salida(self):
        self.assertEqual(evaluar.dias_en_japon(opcion(5000, [IDA, VUELTA])), 21)

    def test_descarta_fuera_de_19_a_21(self):
        tarde = tramo(["NRT", "MAD", "EZE"], "2027-06-16T10:00", "2027-06-17T20:00")
        self.assertIn("días en Japón", evaluar.motivo_descarte(opcion(5000, [IDA, tarde]), RESTRICCIONES))

    def test_con_stopover_cuenta_el_tramo_que_llega_a_japon(self):
        madrid = tramo(["EZE", "MAD"], "2027-05-20T18:00", "2027-05-21T10:00", 0, 12)
        resto = tramo(["MAD", "NRT"], "2027-05-22T12:00", "2027-05-23T10:00", 0, 15)
        vuelta = tramo(["NRT", "EZE"], "2027-06-12T10:00", "2027-06-13T10:00", 0, 30)
        self.assertEqual(evaluar.dias_en_japon(opcion(5000, [madrid, resto, vuelta])), 20)

    def test_el_tramo_corto_a_san_pablo_no_se_mide(self):
        corta = opcion(600, [tramo(["AEP", "GRU"], "2027-05-23T12:00", "2027-05-23T15:00", 0, 3),
                             tramo(["GRU", "AEP"], "2027-06-16T23:00", "2027-06-17T02:00", 0, 3)])
        self.assertIsNone(evaluar.dias_en_japon(corta))
        self.assertIsNone(evaluar.motivo_descarte(corta, RESTRICCIONES))


class Valijas(unittest.TestCase):
    def test_sin_confirmar_suma_las_valijas_de_los_2_en_los_2_tramos(self):
        resultado = evaluar.completar(opcion(5082, [IDA, VUELTA]), CFG)
        costo = CFG["equipaje"]["costo_estimado_valija_por_tramo"]
        self.assertEqual(resultado["valijas_estimadas"], 4 * costo)
        self.assertEqual(resultado["precio_con_valijas"], 5082 + 4 * costo)
        self.assertEqual(resultado["por_persona"], 2541)

    def test_incluida_no_suma(self):
        resultado = evaluar.completar(opcion(3500, [IDA, VUELTA], "incluida"), CFG)
        self.assertEqual(resultado["precio_con_valijas"], 3500)
        self.assertEqual(resultado["categoria"], "🟢 ideal")

    def test_la_categoria_usa_el_precio_con_valijas(self):
        costo_total = 4 * CFG["equipaje"]["costo_estimado_valija_por_tramo"]
        resultado = evaluar.completar(opcion(3500, [IDA, VUELTA]), CFG)
        self.assertEqual(resultado["precio_con_valijas"], 3500 + costo_total)
        self.assertNotEqual(resultado["categoria"], "🟢 ideal")

    def test_limites_de_categoria(self):
        precios = CFG["precios"]
        self.assertEqual(evaluar.categoria(3800, precios), "✅ comprar")
        self.assertEqual(evaluar.categoria(4000, precios), "👀 casi")
        self.assertEqual(evaluar.categoria(4001, precios), evaluar.CARO)


class SanPablo(unittest.TestCase):
    larga = opcion(4000, [tramo(["GRU", "IST", "NRT"], "2027-05-23T23:55", "2027-05-25T20:00", 1, 31.2),
                          tramo(["NRT", "IST", "GRU"], "2027-06-15T22:05", "2027-06-16T18:00", 1, 30)])

    def corta(self, llega_ida="2027-05-23T15:00", sale_vuelta="2027-06-16T23:00"):
        return opcion(300, [tramo(["AEP", "GRU"], "2027-05-23T12:00", llega_ida, 0, 3),
                            tramo(["GRU", "AEP"], sale_vuelta, "2027-06-17T02:00", 0, 3)])

    def test_combina_y_cuenta_el_cambio_como_escala(self):
        total = evaluar.combinar_san_pablo(self.larga, self.corta(), 4)
        self.assertEqual(total["precio_total"], 4300)
        self.assertEqual(total["tramos"][0]["escalas"], 2)
        self.assertEqual(total["tramos"][0]["ruta"], ["AEP", "GRU", "IST", "NRT"])
        self.assertAlmostEqual(total["tramos"][0]["horas"], 3 + 8.9 + 31.2, places=1)
        self.assertEqual(total["tramos_valija_sin_confirmar"], 4)
        self.assertTrue(total["avisos"])

    def test_rechaza_conexion_corta(self):
        self.assertIsNone(evaluar.combinar_san_pablo(self.larga, self.corta(llega_ida="2027-05-23T21:00"), 4))
        self.assertIsNone(evaluar.combinar_san_pablo(self.larga, self.corta(sale_vuelta="2027-06-16T19:00"), 4))


    def test_la_combinacion_de_mas_de_36_horas_no_cuenta_como_valida(self):
        larga = opcion(3262, [tramo(["GRU", "IST", "NRT"], "2027-05-23T23:55", "2027-05-25T20:00", 1, 31.2),
                              tramo(["NRT", "IST", "GRU"], "2027-06-15T22:05", "2027-06-16T18:00", 1, 30)])
        tarde = opcion(610, [tramo(["AEP", "GRU"], "2027-05-23T02:00", "2027-05-23T05:00", 0, 3),
                             tramo(["GRU", "AEP"], "2027-06-16T23:00", "2027-06-17T02:00", 0, 3)])
        con_limite = {**RESTRICCIONES, "max_horas_por_tramo_san_pablo": 36}
        validas, descartada = evaluar.combinaciones_san_pablo([larga], [tarde], con_limite)
        self.assertEqual(validas, [])
        self.assertEqual(descartada["precio_total"], 3872)
        self.assertIn("36", descartada["motivo"])

        temprano = opcion(610, [tramo(["AEP", "GRU"], "2027-05-23T16:00", "2027-05-23T19:00", 0, 3),
                                tramo(["GRU", "AEP"], "2027-06-16T23:00", "2027-06-17T02:00", 0, 3)])
        mas_corta = opcion(3262, [tramo(["GRU", "IST", "NRT"], "2027-05-23T23:55", "2027-05-25T20:00", 1, 26),
                                  tramo(["NRT", "IST", "GRU"], "2027-06-15T22:05", "2027-06-16T18:00", 1, 26)])
        validas, descartada = evaluar.combinaciones_san_pablo([mas_corta], [temprano], RESTRICCIONES)
        self.assertEqual([v["precio_total"] for v in validas], [3872])
        self.assertIsNone(descartada)


    def test_un_vuelo_largo_da_una_sola_combinacion_la_mas_barata_y_corta(self):
        larga = opcion(3262, [tramo(["GRU", "IST", "NRT"], "2027-05-23T23:55", "2027-05-25T20:00", 1, 26),
                              tramo(["NRT", "IST", "GRU"], "2027-06-15T22:05", "2027-06-16T18:00", 1, 26)])
        def corta(precio, llega_ida):
            sale = llega_ida[:11] + f"{int(llega_ida[11:13]) - 3:02d}:00"
            return opcion(precio, [tramo(["AEP", "GRU"], sale, llega_ida, 0, 3),
                                   tramo(["GRU", "AEP"], "2027-06-16T23:00", "2027-06-17T02:00", 0, 3)])
        cortas = [corta(700, "2027-05-23T19:00"), corta(610, "2027-05-23T15:00"), corta(610, "2027-05-23T19:00")]
        validas, _ = evaluar.combinaciones_san_pablo([larga], cortas, RESTRICCIONES)
        self.assertEqual(len(validas), 1)
        self.assertEqual(validas[0]["precio_total"], 3872)
        self.assertEqual(validas[0]["tramos"][0]["llegada"], "2027-05-25T20:00")
        self.assertEqual(validas[0]["tramos"][0]["salida"], "2027-05-23T16:00")  # la espera más corta


    def test_san_pablo_tiene_su_propio_limite_de_horas(self):
        larga = opcion(2548, [tramo(["GRU", "MAD", "NRT"], "2027-06-06T19:20", "2027-06-08T18:35", 1, 35),
                              tramo(["NRT", "FRA", "GRU"], "2027-06-28T10:35", "2027-06-29T08:00", 1, 30)])
        corta = opcion(980, [tramo(["AEP", "GRU"], "2027-06-06T09:00", "2027-06-06T11:55", 0, 3),
                             tramo(["GRU", "AEP"], "2027-06-29T15:00", "2027-06-29T18:00", 0, 3)])
        sin_limite = {**RESTRICCIONES, "max_horas_por_tramo_san_pablo": None}
        validas, _ = evaluar.combinaciones_san_pablo([larga], [corta], sin_limite)
        self.assertEqual([v["precio_total"] for v in validas], [3528])
        self.assertGreater(validas[0]["tramos"][0]["horas"], 36)

        con_limite = {**RESTRICCIONES, "max_horas_por_tramo_san_pablo": 36}
        validas, descartada = evaluar.combinaciones_san_pablo([larga], [corta], con_limite)
        self.assertEqual(validas, [])
        self.assertIn("36", descartada["motivo"])

    def test_buenos_aires_mantiene_las_36_horas(self):
        larga = tramo(["EZE", "MAD", "NRT"], "2027-04-25T18:05", "2027-04-27T18:35", 1, 36.5)
        sin_limite = {**RESTRICCIONES, "max_horas_por_tramo_san_pablo": None}
        self.assertIn("36", evaluar.motivo_descarte(opcion(4554, [larga, VUELTA]), sin_limite))


class Juntar(unittest.TestCase):
    def test_saca_repetidos_y_guarda_precio_de_cada_fuente(self):
        a = evaluar.completar(opcion(5792, [IDA, VUELTA]), CFG)
        b = evaluar.completar(opcion(5367, [IDA, VUELTA], fuente="serpapi"), CFG)
        juntas = evaluar.juntar([a, b])
        self.assertEqual(len(juntas), 1)
        self.assertEqual(juntas[0]["precio_total"], 5367)
        self.assertEqual(juntas[0]["precios_por_fuente"], {"ignav": 5792, "serpapi": 5367})


class ContadorDeConsultas(unittest.TestCase):
    def nuevo(self, carpeta, dia=date(2026, 11, 7), **kwargs):
        limites = {"ignav": {"por_dia": 2, "total_gratis": 3}, "serpapi": {"por_dia": 8, "por_mes": 9}}
        return Contador(Path(carpeta) / "c.json", limites, dia, **kwargs)

    def test_frena_en_el_limite_diario_y_lo_recuerda(self):
        with tempfile.TemporaryDirectory() as carpeta:
            contador = self.nuevo(carpeta)
            contador.registrar("ignav", 2)
            with self.assertRaises(CupoDelDia):
                contador.verificar("ignav")
            self.assertEqual(self.nuevo(carpeta).disponibles("ignav"), 0)

    def test_al_otro_dia_hay_cupo_pero_el_total_no_se_renueva(self):
        with tempfile.TemporaryDirectory() as carpeta:
            self.nuevo(carpeta).registrar("ignav", 2)
            self.assertEqual(self.nuevo(carpeta, date(2026, 11, 8)).disponibles("ignav"), 1)

    def test_barrido_ignora_el_diario_pero_no_el_total(self):
        with tempfile.TemporaryDirectory() as carpeta:
            contador = self.nuevo(carpeta, sin_limite_diario=("ignav",))
            contador.registrar("ignav", 2)
            self.assertEqual(contador.disponibles("ignav"), 1)

    def test_barrido_no_afecta_el_limite_de_la_otra_fuente(self):
        with tempfile.TemporaryDirectory() as carpeta:
            contador = self.nuevo(carpeta, sin_limite_diario=("ignav",))
            contador.registrar("serpapi", 8)
            self.assertEqual(contador.disponibles("serpapi"), 0)

    def test_limite_mensual_y_tope_externo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            contador = self.nuevo(carpeta)
            contador.registrar("serpapi", 2)
            self.assertEqual(contador.disponibles("serpapi"), 6)
            contador.limitar("serpapi", 1)
            self.assertEqual(contador.disponibles("serpapi"), 1)


class Planificador(unittest.TestCase):
    def test_ventanas_de_abril_a_junio(self):
        self.assertEqual(planificador.ventanas(CFG), [("2027-04-01", "2027-04-30"), ("2027-05-01", "2027-05-31"), ("2027-06-01", "2027-06-30")])

    def test_ciclo_tiene_todas_las_combinaciones_sin_repetir(self):
        ciclo = planificador.ciclo_calendarios(CFG)
        self.assertEqual(len(ciclo), 4 * 3 * 3)
        self.assertEqual(len({str(c) for c in ciclo}), 36)

    def test_la_rotacion_recorre_todo_el_ciclo(self):
        ciclo = planificador.ciclo_calendarios(CFG)
        vistos = set()
        for i in range(len(ciclo)):
            dia = date.fromordinal(date(2026, 11, 7).toordinal() + i)
            vistos |= {str(c) for c in planificador.calendarios_del_dia(CFG, dia, 2)}
        self.assertEqual(len(vistos), len(ciclo))

    def test_mayo_y_junio_van_primero(self):
        ciclo = planificador.ciclo_calendarios(CFG)
        primeros = ciclo[:12]
        self.assertGreater(sum(c["desde"] >= "2027-05" for c in primeros), sum(c["desde"] < "2027-05" for c in primeros))

    def test_barrido_es_una_estadia_por_ruta_y_mes(self):
        barrido = planificador.barrido_inicial(CFG)
        self.assertEqual(len(barrido), 12)
        self.assertEqual({c["estadia"] for c in barrido}, {22})

    def test_memoria_borra_fechas_sin_tarifa_e_ignora_datos_viejos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            memoria = planificador.Memoria(Path(carpeta) / "m.json")
            precio = lambda monto: {"amount": monto, "currency": "USD", "status": "unverified"}
            memoria.guardar_calendario("BUE", "TYO", 23, {"dates": [
                {"departure_date": "2027-05-02", "return_date": "2027-05-25", "price": precio(5000)},
                {"departure_date": "2027-05-01", "return_date": "2027-05-24", "price": precio(4000)},
            ]}, date(2026, 11, 7))
            memoria.guardar_calendario("BUE", "TYO", 23, {"dates": [{"departure_date": "2027-05-01", "price": None}]}, date(2026, 11, 7))
            filas = memoria.mejores_fechas("BUE-TYO", date(2026, 11, 7))
            self.assertEqual([f["salida"] for f in filas], ["2027-05-02"])
            self.assertEqual(memoria.mejores_fechas("BUE-TYO", date(2027, 1, 1)), [])


class Normalizar(unittest.TestCase):
    def test_ignav_traduce_el_estado_de_la_valija(self):
        itinerario = {"price": {"amount": 5786.0, "currency": "USD", "status": "verified"},
                      "baggage_pricing": {"status": "reported_included"},
                      "legs": [{"duration_minutes": 120, "segments": [
                          {"operating_carrier_name": None, "marketing_carrier_code": "3U", "departure_airport": "EZE",
                           "arrival_airport": "MAD", "departure_time_local": "2027-05-23T15:05:00", "arrival_time_local": "2027-05-24T08:00:00"}]}]}
        resultado = ignav.normalizar(itinerario, "open_jaw")
        self.assertEqual(resultado["equipaje"], "incluida")
        self.assertTrue(resultado["precio_verificado"])
        self.assertEqual(resultado["tramos"][0]["aerolineas"], ["Sichuan Airlines"])
        self.assertEqual(resultado["tramos"][0]["salida"], "2027-05-23T15:05")
        self.assertEqual(resultado["tramos"][0]["horas"], 2.0)

    def test_serpapi_usa_el_mismo_formato_de_hora(self):
        opcion_serpapi = {"total_duration": 1884, "flights": [{"airline": "KLM",
            "departure_airport": {"id": "EZE", "time": "2027-05-23 15:05"}, "arrival_airport": {"id": "AMS", "time": "2027-05-24 09:00"}}]}
        resultado = serpapi.tramo(opcion_serpapi)
        self.assertEqual(resultado["salida"], "2027-05-23T15:05")
        self.assertEqual(resultado["horas"], 31.4)


if __name__ == "__main__":
    unittest.main()
