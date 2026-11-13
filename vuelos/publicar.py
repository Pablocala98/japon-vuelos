"""Arma docs/datos.js, que lee el dashboard. No gasta consultas.

Uso: .venv/bin/python -m vuelos.publicar

Es un .js y no un .json para que docs/index.html también se pueda abrir con doble clic.
"""
import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from statistics import median

from . import aeropuertos, analisis, enlaces, evaluar, stopover, ventajas
from .config import RAIZ, cargar_config
from .consultas import Contador
from .fechas import ahora, hoy

DOCS = RAIZ / "docs"
DATOS = RAIZ / "data"
OPCIONES_EN_PAGINA = 40
CONSULTAS_TIPICAS_POR_STOPOVER = 6  # 2 fechas x 3 pasos; los reintentos suman 1 cada uno
NOMBRES_TIPO = {"ida_y_vuelta": "Ida y vuelta", "open_jaw": "Llega a una ciudad y vuelve de otra",
                "san_pablo": "Desde San Pablo (2 pasajes)"}
JAPON = {"NRT": "TYO", "HND": "TYO", "KIX": "OSA", "ITM": "OSA"}


def _nombre_tipo(tipo: str, cfg: dict) -> str:
    if tipo.startswith(stopover.TIPO + "_"):
        ciudad, cuando = stopover.datos_del_tipo(tipo)
        return f"Stopover en {cfg['stopovers'].get(ciudad, {}).get('nombre', ciudad)} a la {cuando}"
    return NOMBRES_TIPO.get(tipo, tipo)


def _tramo_para_pagina(t: dict) -> dict:
    paradas = [_parada_para_pagina(p) for p in aeropuertos.paradas_de(t)]
    minutos = [p["minutos"] for p in paradas]
    return {
        **{k: t[k] for k in ("ruta", "salida", "llegada", "escalas", "horas", "aerolineas")},
        "minutos": t.get("minutos"),
        "paradas": paradas,
        "horas_escalas": round(sum(minutos) / 60, 1) if paradas and None not in minutos else None,
        # Días que pasan entre la salida y la llegada, en hora local (+1, +2).
        "dias_mas": (date.fromisoformat(t["llegada"][:10]) - date.fromisoformat(t["salida"][:10])).days if t.get("llegada") and t.get("salida") else 0,
    }


def _id(opcion: dict) -> str:
    return hashlib.sha1(json.dumps(evaluar.clave_vuelo(opcion)).encode()).hexdigest()[:10]


def _parada_para_pagina(parada: dict) -> dict:
    con_lugar = aeropuertos.con_lugares(parada)
    lugar, salida = con_lugar["lugar"], con_lugar["lugar_salida"]
    return {
        "codigo": lugar["codigo"], "aeropuerto": lugar["nombre"], "ciudad": lugar["ciudad"], "pais": lugar["pais"],
        "pais_codigo": lugar["pais_codigo"],
        "sale_de": salida and {"codigo": salida["codigo"], "aeropuerto": salida["nombre"]},
        "minutos": parada["minutos"], "duracion": aeropuertos.duracion(parada["minutos"]),
        "noche": parada["noche"], "cambio_pasaje": parada["cambio_pasaje"],
    }


def para_pagina(opcion: dict, mas_barata: float, precio_anterior: float | None, cfg: dict) -> dict:
    ida, vuelta = opcion["tramos"][0], opcion["tramos"][-1]
    return {
        "id": _id(opcion),
        "tipo": _nombre_tipo(opcion["tipo"], cfg),
        "desde_san_pablo": opcion["tipo"] == "san_pablo",
        "destino": next((JAPON[t["ruta"][-1]] for t in opcion["tramos"] if t["ruta"][-1] in JAPON), None),
        "aerolineas": sorted({a for t in opcion["tramos"] for a in t["aerolineas"]}),
        "tramos": [_tramo_para_pagina(t) for t in opcion["tramos"]],
        "sale": ida["salida"], "vuelve": vuelta["salida"], "dias_en_japon": opcion.get("dias_en_japon"),
        "precio_total": round(opcion["precio_total"]), "precio_con_valijas": opcion["precio_con_valijas"],
        "por_persona_con_valijas": opcion["por_persona_con_valijas"], "valijas_estimadas": opcion["valijas_estimadas"],
        "equipaje": opcion["equipaje"], "precio_verificado": bool(opcion.get("precio_verificado")),
        "categoria": opcion["categoria"], "precios_por_fuente": opcion.get("precios_por_fuente", {}),
        "desglose": opcion.get("desglose"),
        "visto": opcion.get("visto"), "precio_confirmado": opcion.get("precio_confirmado"),
        "confianza": opcion.get("confianza") or evaluar.confianza(opcion),
        "confiable": opcion.get("confiable", True), "links_fallidos": opcion.get("links_fallidos") or [],
        "cambio_vs_anterior": round(opcion["precio_total"] - precio_anterior) if precio_anterior is not None else None,
        "nueva": precio_anterior is None,
        **ventajas.evaluar_opcion(opcion, mas_barata, cfg),
        "links_google": enlaces.google_flights(opcion, cfg["viaje"]["pasajeros"]),
        "links_compra": opcion.get("links_compra") or [],
    }


def duraciones(opciones: list[dict]) -> dict:
    """Cuánto tardan de verdad los vuelos encontrados, por origen. El buscador lo usa para estimar llegadas."""
    resultado = {}
    for clave, grupo in (("bue", [o for o in opciones if o["tipo"] != "san_pablo"]), ("gru", [o for o in opciones if o["tipo"] == "san_pablo"])):
        if not grupo:
            continue
        ida = [o["tramos"][0] for o in grupo]
        vuelta = [o["tramos"][-1] for o in grupo]

        def dias(tramos):
            return Counter((date.fromisoformat(t["llegada"][:10]) - date.fromisoformat(t["salida"][:10])).days for t in tramos)

        resultado[clave] = {
            "ida_horas": round(median(t["horas"] for t in ida), 1),
            "vuelta_horas": round(median(t["horas"] for t in vuelta), 1),
            "ida_dias": dias(ida).most_common(1)[0][0],
            "vuelta_dias": dias(vuelta).most_common(1)[0][0],
            "ida_dias_rango": [min(dias(ida)), max(dias(ida))],
            "vuelta_dias_rango": [min(dias(vuelta)), max(dias(vuelta))],
            "opciones": len(grupo),
        }
    return resultado


def armar(cfg: dict, dia: date) -> dict:
    dias = analisis.cargar_dias(DATOS)
    fechas_con_datos = [f for f in dias if f <= dia.isoformat()]
    fecha = fechas_con_datos[-1] if fechas_con_datos else None
    resumen = analisis.generar(cfg, date.fromisoformat(fecha)) if fecha else None
    opciones = analisis.vigentes(dias, fecha, cfg) if fecha else []
    anteriores = [f for f in dias if fecha and f < fecha]
    previas = analisis.vigentes(dias, anteriores[-1], cfg) if anteriores else []
    precio_anterior = {evaluar.clave_vuelo(o): o["precio_total"] for o in previas}
    mas_barata = next((o["precio_con_valijas"] for o in opciones if o.get("confiable", True)), 0)

    archivo_promos = DATOS / "promociones" / f"{dia.isoformat()}.json"
    promos = json.loads(archivo_promos.read_text(encoding="utf-8")) if archivo_promos.exists() else None
    archivo_resultados = DATOS / "resultados" / f"{fecha}.json"
    del_dia = json.loads(archivo_resultados.read_text(encoding="utf-8")) if fecha and archivo_resultados.exists() else {}
    return {
        "generado": ahora(),
        "fecha_datos": fecha,
        "preferencias": {
            "pasajeros": cfg["viaje"]["pasajeros"], "dias_en_japon": cfg["restricciones"]["dias_en_japon"],
            "max_escalas": cfg["restricciones"]["max_escalas"], "max_horas": cfg["restricciones"]["max_horas_por_tramo"],
            "precios": {k: cfg["precios"][k] for k in ("ideal", "comprar", "casi")},
            "tolerancia_dias": cfg["restricciones"]["tolerancia_dias"],
            "costo_valija": cfg["equipaje"]["costo_estimado_valija_por_tramo"],
        },
        "resumen": resumen and {k: resumen[k] for k in ("comparado_con", "comparacion", "mejores_hoy")},
        "evolucion": resumen["evolucion"] if resumen else [],
        "fechas": resumen["fechas"] if resumen else None,
        "duraciones": duraciones(opciones),
        "ventana": {"desde": cfg["fechas"]["salida_desde"], "hasta": cfg["fechas"]["salida_hasta"],
                    "preferida_desde": cfg["fechas"]["salida_preferida_desde"],
                    "preferida_hasta": cfg["fechas"].get("salida_preferida_hasta", cfg["fechas"]["salida_hasta"])},
        "opciones": [para_pagina(o, mas_barata, precio_anterior.get(evaluar.clave_vuelo(o)), cfg) for o in opciones[:OPCIONES_EN_PAGINA]],
        "promociones": promos,
        "stopovers": stopovers(cfg, dia),
        "actualizar": {"repositorio": (cfg.get("publicacion") or {}).get("repositorio") or None, "flujo": "buscar.yml",
                       "limites": {f: cfg["consultas"][f].get("por_dia") for f in ("ignav", "serpapi")}},
        "estado": {"cupo": del_dia.get("cupo"), "errores": del_dia.get("errores", []) + ((promos or {}).get("errores") or []),
                   "promos_fuente": "promociones-aereas.com.ar"},
    }


def stopovers(cfg: dict, dia: date) -> dict:
    """Lo encontrado en los stopovers pedidos en los últimos días, y el cupo que queda este mes."""
    carpeta = DATOS / "stopovers"
    limite = (dia - timedelta(days=cfg["stopovers"].get("dias_vigencia", 14))).isoformat()
    por_vuelo, pedidos = {}, []
    for archivo in sorted(carpeta.glob("*.json")) if carpeta.exists() else []:
        if archivo.stem < limite:
            continue
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        for opcion in datos.get("opciones", []):
            por_vuelo[evaluar.clave_vuelo(opcion)] = {**evaluar.completar(opcion, cfg), "visto": archivo.stem}
        pedidos += datos.get("pedidos", [])
    opciones = sorted(por_vuelo.values(), key=lambda o: o["precio_con_valijas"])
    mas_barata = next((o["precio_con_valijas"] for o in opciones if o.get("confiable", True)), 0)
    contador = Contador(DATOS / "consultas.json", cfg["consultas"], dia)
    limites = cfg["consultas"]
    quedan = min(limites["stopover"]["por_mes"] - contador.gastadas_del_mes("stopover"),
                 limites["serpapi"]["por_mes"] - contador.gastadas_del_mes("serpapi"))
    return {
        "opciones": [{**para_pagina(o, mas_barata, o["precio_total"], cfg), "stopover": stopover.detalle(o, cfg)} for o in opciones],
        "pedidos": sorted(pedidos, key=lambda p: p["pedido"], reverse=True)[:10],
        "ciudades": {clave: {"nombre": v["nombre"], "aerolinea": v.get("aerolinea_nombre"), "aeropuerto": v["aeropuerto"]}
                     for clave, v in cfg["stopovers"].items() if isinstance(v, dict)},
        "cupo": {"quedan_consultas": max(quedan, 0), "busquedas_aprox": max(quedan, 0) // CONSULTAS_TIPICAS_POR_STOPOVER,
                 "por_busqueda": limites["stopover"]["por_busqueda"]},
        "dias_vigencia": cfg["stopovers"].get("dias_vigencia", 14),
    }


def publicar(cfg: dict, dia: date) -> dict:
    datos = armar(cfg, dia)
    DOCS.mkdir(exist_ok=True)
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    (DOCS / "datos.js").write_text(f"window.DATOS = {texto};\n", encoding="utf-8")
    return datos


def main() -> None:
    datos = publicar(cargar_config(), hoy())
    print(f"docs/datos.js listo: {len(datos['opciones'])} opciones del {datos['fecha_datos']}")


if __name__ == "__main__":
    main()
