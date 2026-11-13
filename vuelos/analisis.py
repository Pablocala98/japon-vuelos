"""Historial y análisis: compara cada día con el anterior y ordena las fechas por precio.

Uso: .venv/bin/python -m vuelos.analisis   (no gasta consultas: solo lee lo guardado)

Los días viejos se vuelven a evaluar con config.yaml de hoy, así un cambio de preferencias
no hace parecer que el precio subió o bajó.
"""
import json
from datetime import date, timedelta
from pathlib import Path

from . import evaluar, planificador
from .config import RAIZ, cargar_config
from .fechas import ahora, hoy

DATOS = RAIZ / "data"
ORDEN_CATEGORIAS = [etiqueta for _, etiqueta in evaluar.CATEGORIAS] + [evaluar.CARO]
NOMBRES_RUTAS = {"BUE-TYO": "Buenos Aires a Tokio", "BUE-OSA": "Buenos Aires a Osaka",
                 "GRU-TYO": "San Pablo a Tokio", "GRU-OSA": "San Pablo a Osaka"}
GRUPOS = {
    "total": lambda o: True,
    "buenos_aires": lambda o: o["tipo"] != "san_pablo",
    "san_pablo": lambda o: o["tipo"] == "san_pablo",
}
FECHAS_EN_RANKING = 12
FECHAS_POR_RUTA = 4  # para que una sola ruta no llene el ranking


CARPETAS_DEL_DIA = ("resultados", "exploracion")  # la exploración también es parte de lo que se vio ese día


def cargar_dias(datos: Path) -> dict[str, dict]:
    """Junta, por fecha, las opciones y la info de San Pablo de la búsqueda diaria y de la exploración."""
    dias: dict[str, dict] = {}
    for carpeta in CARPETAS_DEL_DIA:
        for archivo in sorted((datos / carpeta).glob("????-??-??.json")):
            contenido = json.loads(archivo.read_text(encoding="utf-8"))
            dia = dias.setdefault(archivo.stem, {"opciones": [], "san_pablo": [], "errores": []})
            dia["opciones"] += contenido.get("opciones", [])
            dia["san_pablo"] += contenido.get("san_pablo", [])
            dia["errores"] += contenido.get("errores", [])
    return dict(sorted(dias.items()))


def reevaluar(datos_del_dia: dict, cfg: dict) -> list[dict]:
    """Las opciones de un día que cumplen las preferencias de hoy, con los precios recalculados."""
    validas = [evaluar.completar(o, cfg) for o in datos_del_dia.get("opciones", [])
               if not evaluar.motivo_descarte(o, cfg["restricciones"])]
    return evaluar.juntar(validas)


def vigentes(dias: dict[str, dict], hasta: str, cfg: dict) -> list[dict]:
    """Las opciones de los últimos días, con la fecha en que se vio cada una. Si un vuelo se vio
    varias veces, queda la vez más reciente. Así una buena opción no desaparece porque hoy se buscaron otras fechas."""
    dias_vigencia = (cfg.get("analisis") or {}).get("dias_vigencia", 1)
    desde = (date.fromisoformat(hasta) - timedelta(days=dias_vigencia - 1)).isoformat()
    por_vuelo = {}
    for fecha, datos in dias.items():  # vienen ordenados de más viejo a más nuevo
        if desde <= fecha <= hasta:
            fallidos = links_fallidos(datos)
            for opcion in reevaluar(datos, cfg):
                clave = evaluar.clave_vuelo(opcion)
                previas = (por_vuelo.get(clave) or {}).get("links_fallidos", [])
                ids = set(opcion.get("ignav_ids") or [opcion.get("ignav_id")])
                fallo_hoy = [fecha] if ids & fallidos else []
                nueva = {**opcion, "visto": fecha}
                if not opcion.get("links_compra") and (previas or fallo_hoy):
                    nueva["links_fallidos"] = sorted(set(previas + fallo_hoy))
                por_vuelo[clave] = nueva
    return sorted(por_vuelo.values(), key=lambda o: o["precio_con_valijas"])


def links_fallidos(datos_del_dia: dict) -> set[str]:
    """Números de Ignav cuyo pedido de links de compra falló ese día (la fuente no pudo dar dónde comprarlo)."""
    ids = set()
    for error in datos_del_dia.get("errores", []):
        if error.startswith("link ") and ":" in error:
            ids |= set(error[5:].split(":", 1)[0].split("+"))
    return ids


def mejor(opciones: list[dict], grupo: str = "total") -> dict | None:
    """La más barata con un precio que alguien respalda: las "sin confirmar" no cuentan como la mejor."""
    return next((o for o in opciones if GRUPOS[grupo](o) and o.get("confiable", True)), None)


def resumen_opcion(opcion: dict | None) -> dict | None:
    if not opcion:
        return None
    ida, vuelta = opcion["tramos"][0], opcion["tramos"][-1]
    return {
        "precio_con_valijas": opcion["precio_con_valijas"], "precio_total": round(opcion["precio_total"]),
        "por_persona_con_valijas": opcion["por_persona_con_valijas"], "categoria": opcion["categoria"],
        "tipo": opcion["tipo"], "aerolineas": sorted(set(ida["aerolineas"]) | set(vuelta["aerolineas"])),
        "sale": ida["salida"], "vuelve": vuelta["salida"], "dias_en_japon": opcion.get("dias_en_japon"),
        "visto": opcion.get("visto"), "precio_confirmado": opcion.get("precio_confirmado"),
    }


def comparar(hoy_opciones: list[dict], previas: list[dict] | None, margen: float,
             vistas_hoy: list[dict] | None = None, vistas_antes: list[dict] | None = None) -> dict:
    """Mejor disponible hoy contra la del día anterior. Los mismos vuelos se comparan solo con lo
    que se buscó de verdad cada día (`vistas_*`), para no comparar un precio consigo mismo."""
    actual, anterior = mejor(hoy_opciones), mejor(previas or [])
    mismos = _mismos_vuelos(vistas_hoy if vistas_hoy is not None else hoy_opciones,
                            vistas_antes if vistas_antes is not None else (previas or []), margen)
    resultado = {"estado": "sin_datos", "diferencia": None, "cruzo_umbral": None, "aviso": None,
                 "mejor_hoy": resumen_opcion(actual), "mejor_anterior": resumen_opcion(anterior),
                 "mismos_vuelos": mismos}
    if not actual or not anterior:
        return resultado
    diferencia = actual["precio_con_valijas"] - anterior["precio_con_valijas"]
    if not mismos["comparados"] and abs(diferencia) > margen:
        resultado["aviso"] = ("Ningún vuelo de hoy coincide con los del día anterior: se buscaron otras fechas, "
                              "así que la diferencia puede deberse a eso y no a un cambio de precios.")
    resultado["diferencia"] = diferencia
    resultado["estado"] = "igual" if abs(diferencia) <= margen else ("mejoró" if diferencia < 0 else "empeoró")
    resultado["cruzo_umbral"] = _cambio_de_categoria(anterior["categoria"], actual["categoria"])
    return resultado


def _cambio_de_categoria(antes: str, ahora_: str) -> str | None:
    if antes == ahora_:
        return None
    sube = ORDEN_CATEGORIAS.index(ahora_) < ORDEN_CATEGORIAS.index(antes)
    return f"{'Entró en' if sube else 'Salió de'} {ahora_ if sube else antes}"


def _mismos_vuelos(hoy_opciones: list[dict], previas: list[dict], margen: float) -> dict:
    """Como cada día se buscan fechas distintas, esto muestra mejor si el mercado se movió."""
    antes = {evaluar.clave_vuelo(o): o["precio_total"] for o in previas}
    cambios = [o["precio_total"] - antes[evaluar.clave_vuelo(o)] for o in hoy_opciones if evaluar.clave_vuelo(o) in antes]
    return {
        "comparados": len(cambios),
        "bajaron": sum(c < -margen for c in cambios),
        "subieron": sum(c > margen for c in cambios),
        "iguales": sum(abs(c) <= margen for c in cambios),
        "cambio_promedio": round(sum(cambios) / len(cambios)) if cambios else None,
    }


def evolucion(dias: dict[str, dict], cfg: dict) -> list[dict]:
    """El mejor precio disponible cada día (lo de ese día más lo que seguía vigente)."""
    filas = []
    for fecha in dias:
        opciones = vigentes(dias, fecha, cfg)
        fila = {"fecha": fecha}
        for grupo in GRUPOS:
            opcion = mejor(opciones, grupo)
            fila[grupo] = opcion["precio_con_valijas"] if opcion else None
        la_mejor = mejor(opciones)
        fila["categoria"] = la_mejor["categoria"] if la_mejor else None
        filas.append(fila)
    return filas


def analisis_fechas(memoria: dict, cfg: dict, dia: date, tramo_corto: float | None) -> dict:
    """Ordena las fechas del calendario. Desde San Pablo suma el tramo corto si ya se conoce su precio."""
    limite = (dia - timedelta(days=planificador.ANTIGUEDAD_MAXIMA_DIAS)).isoformat()
    estadias = {str(e) for e in cfg["fechas"]["estadia_dias"]}
    celdas = []
    for ruta, por_estadia in memoria.items():
        for estadia, fechas in por_estadia.items():
            if estadia not in estadias:
                continue
            for salida, fila in fechas.items():
                if fila["visto"] < limite or not cfg["fechas"]["salida_desde"] <= salida <= cfg["fechas"]["salida_hasta"]:
                    continue
                desde_san_pablo = not ruta.startswith("BUE")
                total = fila["precio"] + (tramo_corto or 0) if desde_san_pablo else fila["precio"]
                celdas.append({
                    "ruta": ruta, "nombre_ruta": NOMBRES_RUTAS.get(ruta, ruta), "estadia": int(estadia),
                    "dias_en_japon_aprox": int(estadia) - 2, "salida": salida, "regreso": fila["regreso"],
                    "precio": round(fila["precio"]), "precio_comparable": round(total) if not desde_san_pablo or tramo_corto else None,
                    "incluye_tramo_corto": desde_san_pablo and bool(tramo_corto), "visto": fila["visto"],
                })
    comparables = sorted((c for c in celdas if c["precio_comparable"] is not None), key=lambda c: c["precio_comparable"])
    ranking, por_ruta = [], {}
    for celda in comparables:
        if por_ruta.get(celda["ruta"], 0) < FECHAS_POR_RUTA and len(ranking) < FECHAS_EN_RANKING:
            ranking.append(celda)
            por_ruta[celda["ruta"]] = por_ruta.get(celda["ruta"], 0) + 1
    por_mes = {}
    for celda in comparables:
        clave = (celda["ruta"], celda["salida"][:7])
        por_mes.setdefault(clave, celda)
    return {
        "nota": "Precios del calendario para los 2, sin confirmar y sin valijas.",
        "tramo_corto_usado": tramo_corto,
        "ranking": ranking,
        "mejor_por_mes": sorted(por_mes.values(), key=lambda c: (c["ruta"], c["salida"])),
        "celdas": sorted(celdas, key=lambda c: (c["ruta"], c["estadia"], c["salida"])),
    }


def ultimo_tramo_corto(dias: dict[str, dict]) -> float | None:
    """El precio más reciente del tramo Buenos Aires-San Pablo para los 2."""
    for datos in reversed(list(dias.values())):
        precios = [info["tramo_corto"] for info in datos.get("san_pablo", []) if info.get("tramo_corto")]
        if precios:
            return min(precios)
    return None


def generar(cfg: dict, dia: date, datos: Path = DATOS) -> dict:
    dias = cargar_dias(datos)
    hoy_iso = dia.isoformat()
    anteriores = [f for f in dias if f < hoy_iso]
    opciones_hoy = vigentes(dias, hoy_iso, cfg)
    previas = vigentes(dias, anteriores[-1], cfg) if anteriores else None
    vistas_hoy = reevaluar(dias[hoy_iso], cfg) if hoy_iso in dias else []
    vistas_antes = reevaluar(dias[anteriores[-1]], cfg) if anteriores else []
    memoria_archivo = datos / "calendario.json"
    memoria = json.loads(memoria_archivo.read_text(encoding="utf-8")) if memoria_archivo.exists() else {}
    analisis = {
        "fecha": hoy_iso,
        "generado": ahora(),
        "comparado_con": anteriores[-1] if anteriores else None,
        "comparacion": comparar(opciones_hoy, previas, cfg["precios"]["margen_igual"], vistas_hoy, vistas_antes),
        "mejores_hoy": {grupo: resumen_opcion(mejor(opciones_hoy, grupo)) for grupo in GRUPOS},
        "evolucion": evolucion(dias, cfg),
        "fechas": analisis_fechas(memoria, cfg, dia, ultimo_tramo_corto(dias)),
    }
    carpeta = datos / "analisis"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{hoy_iso}.json").write_text(json.dumps(analisis, indent=1, ensure_ascii=False), encoding="utf-8")
    return analisis


def mostrar(analisis: dict) -> None:
    comparacion = analisis["comparacion"]
    flechas = {"mejoró": "▼ Mejoró", "empeoró": "▲ Empeoró", "igual": "= Igual", "sin_datos": "Sin día anterior para comparar"}
    print(f"\n=== ANÁLISIS {analisis['fecha']} ===")
    mejor_hoy = comparacion["mejor_hoy"]
    if mejor_hoy:
        print(f"Mejor de hoy: {mejor_hoy['categoria']} USD {mejor_hoy['precio_con_valijas']} con valijas "
              f"({mejor_hoy['tipo']}, {', '.join(mejor_hoy['aerolineas'])}, {mejor_hoy['sale'][:10]} a {mejor_hoy['vuelve'][:10]})")
    else:
        print("Hoy no hay opciones que cumplan tus preferencias.")
    texto = flechas[comparacion["estado"]]
    if comparacion["diferencia"] is not None:
        texto += f" USD {abs(comparacion['diferencia'])} respecto del {analisis['comparado_con']}"
    print(texto)
    if comparacion["aviso"]:
        print(f"Ojo: {comparacion['aviso']}")
    if comparacion["cruzo_umbral"]:
        print(f"¡Atención! {comparacion['cruzo_umbral']}")
    mismos = comparacion["mismos_vuelos"]
    if mismos["comparados"]:
        print(f"Mismos vuelos que el día anterior: {mismos['comparados']} comparados, {mismos['bajaron']} bajaron, "
              f"{mismos['subieron']} subieron, {mismos['iguales']} iguales (promedio {mismos['cambio_promedio']:+} USD)")
    else:
        print("Mismos vuelos que el día anterior: ninguno coincide, porque se buscaron otras fechas.")
    print("\nEvolución del mejor precio con valijas (total / desde Buenos Aires / desde San Pablo):")
    for fila in analisis["evolucion"]:
        print(f"  {fila['fecha']}: {fila['total']} / {fila['buenos_aires']} / {fila['san_pablo']}")
    fechas = analisis["fechas"]
    corto = fechas["tramo_corto_usado"]
    print(f"\nFechas más baratas del calendario (sin valijas{'; San Pablo suma USD ' + str(round(corto)) + ' del tramo corto' if corto else ''}):")
    for celda in fechas["ranking"]:
        print(f"  USD {celda['precio_comparable']} | {celda['nombre_ruta']} | {celda['salida']} a {celda['regreso']} "
              f"| ~{celda['dias_en_japon_aprox']} días en Japón")
    print("\nMejor fecha de cada mes:")
    for celda in fechas["mejor_por_mes"]:
        print(f"  {celda['nombre_ruta']} {celda['salida'][:7]}: USD {celda['precio_comparable']} saliendo el {celda['salida']}")


def main() -> None:
    mostrar(generar(cargar_config(), hoy()))


if __name__ == "__main__":
    main()
