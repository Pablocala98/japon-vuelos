"""Promociones de las últimas horas que sirven para el viaje a Japón.

Uso: .venv/bin/python -m vuelos.promociones   (no gasta consultas de vuelos)

Fuente: los feeds públicos de promociones-aereas.com.ar, que su robots.txt permite leer.
El Galicia no publica sus promociones en un formato legible sin navegador, así que solo
aparecen cuando este sitio las menciona.
"""
import json
import re
import time
import unicodedata
from calendar import timegm
from datetime import datetime, timedelta, timezone

import feedparser

from .config import RAIZ, cargar_config
from .fechas import ZONA, ahora, hoy

DATOS = RAIZ / "data"
AGENTE = "japon-vuelos/1.0 (app personal de seguimiento de precios)"
PAUSA_ENTRE_PEDIDOS = 5  # segundos: el sitio pide no apurarlo
FEEDS = {
    "Últimas publicaciones": "https://promociones-aereas.com.ar/feed/",
    "Últimas publicaciones (página 2)": "https://promociones-aereas.com.ar/feed/?paged=2",
    "Vuelos a Asia": "https://promociones-aereas.com.ar/category/vuelos-a-asia/feed/",
    "Búsqueda Galicia": "https://promociones-aereas.com.ar/?s=galicia&feed=rss2",
}
JAPON = ("japon", "tokio", "tokyo", "osaka", "kioto", "kyoto", "narita", "haneda")
ASIA = ("asia", "corea", "seul", "china", "shanghai", "pekin", "hong kong", "tailandia", "bangkok", "singapur", "vietnam")
# Aerolíneas que llevan de Argentina a Japón con 1 o 2 escalas.
AEROLINEAS = ("turkish", "qatar", "emirates", "ethiopian", "iberia", "klm", "air france", "lufthansa", "ita airways",
              "latam", "american airlines", "delta", "united", "british airways", "air canada", "swiss", "ana ", "jal",
              "japan airlines", "air europa", "aeromexico", "copa")
# Una promo de aerolínea sirve si no es para un solo destino: todo el mundo, internacionales, etc.
ALCANCE_GENERAL = ("todos los destinos", "todos sus destinos", "todo el mundo", "internacional", "internacionales",
                   "muchos destinos", "travel sale", "hot sale", "black friday", "cyber monday", "larga distancia")
VUELOS = ("vuelo", "vuelos", "pasaje", "pasajes", "aereo", "aereos")


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar palabras."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()


def _contiene(texto: str, palabras) -> list[str]:
    """Palabras enteras: "ana" no aparece dentro de "Punta Cana" ni "copa" dentro de "Copacabana"."""
    return [p.strip() for p in palabras if re.search(rf"\b{re.escape(p.strip())}\b", texto)]


def clasificar(entrada: dict, medios_de_pago: list[dict]) -> dict | None:
    """Devuelve la promo con sus motivos, o None si no sirve para este viaje."""
    etiquetas = [t.get("term", "") for t in entrada.get("tags") or []]
    texto = _plano(" ".join([entrada.get("title", ""), entrada.get("summary", ""), " ".join(etiquetas)]))
    titulo = _plano(entrada.get("title", ""))
    es_de_vuelos = bool(_contiene(titulo, VUELOS)) or any(_plano(e).startswith("vuelos") for e in etiquetas)
    alcance_general = bool(_contiene(texto, ALCANCE_GENERAL))

    motivos, aviso = [], None
    if japon := _contiene(texto, JAPON):
        motivos.append(f"Menciona {', '.join(sorted(set(japon)))}")
    asia = es_de_vuelos and bool(_contiene(texto, ASIA))
    if asia:
        motivos.append("Vuelos a Asia")
    aerolineas = _contiene(texto, AEROLINEAS)
    if es_de_vuelos and aerolineas and (alcance_general or asia or japon):
        motivos.append(f"Promo de {', '.join(a.title() for a in aerolineas)}, que vuela a Japón")
    titulo_de_vuelos = bool(_contiene(titulo, VUELOS))  # las etiquetas de hoteles también dicen "Vuelos a..."
    for medio in medios_de_pago:
        banco = _plano(medio["banco"])
        if banco not in texto or not titulo_de_vuelos:
            continue
        excluidas = [x for x in medio.get("excluir", []) if _plano(x) in texto]
        tarjetas = [t for t in medio.get("tarjetas", []) if _plano(t) in texto]
        if excluidas and not tarjetas:
            return None  # es solo para tarjetas que no tenés
        motivos.append(f"Con {medio['banco']}" + (f" {' y '.join(tarjetas)}" if tarjetas else ""))
        if excluidas:
            aviso = f"Puede ser solo para {', '.join(excluidas)}: revisá las condiciones."
    if not motivos:
        return None
    publicada = entrada.get("published_parsed")
    return {
        "titulo": entrada.get("title", "").strip(),
        "link": entrada.get("link"),
        "publicada": datetime.fromtimestamp(timegm(publicada), timezone.utc).astimezone(ZONA).isoformat(timespec="minutes") if publicada else None,
        "motivos": motivos,
        "aviso": aviso,
        "japon": bool(japon),
    }


def buscar(cfg: dict, leer=feedparser.parse, pausa: float = PAUSA_ENTRE_PEDIDOS) -> dict:
    """Lee los feeds y se queda con lo publicado en las últimas horas. Un feed que falla no frena al resto."""
    horas = cfg["promociones"]["horas"]
    desde = datetime.now(ZONA) - timedelta(hours=horas)
    promos, errores, vistas = {}, [], set()
    for i, (nombre, url) in enumerate(FEEDS.items()):
        if i:
            time.sleep(pausa)
        try:
            feed = leer(url, agent=AGENTE)
        except Exception as error:  # feedparser casi no tira errores, pero una caída de red no debe frenar la app
            errores.append(f"{nombre}: sin conexión ({type(error).__name__})")
            continue
        estado, entradas = feed.get("status"), feed.get("entries") or []
        if (estado and estado >= 400) or (feed.get("bozo") and not entradas):
            errores.append(f"{nombre}: no se pudo leer (HTTP {estado})")
            continue
        for entrada in entradas:
            clave = entrada.get("id") or entrada.get("link")
            if clave in vistas:
                continue
            vistas.add(clave)
            promo = clasificar(entrada, cfg["medios_de_pago"])
            if promo and promo["publicada"] and datetime.fromisoformat(promo["publicada"]) >= desde:
                promos[clave] = promo
    ordenadas = sorted(promos.values(), key=lambda p: p["publicada"] or "", reverse=True)
    ordenadas.sort(key=lambda p: not p["japon"])  # lo de Japón primero; dentro de cada grupo, lo más nuevo
    return {"actualizado": ahora(), "horas": horas, "promociones": ordenadas, "errores": errores, "leidas": len(vistas)}


def guardar(resultado: dict, dia) -> None:
    carpeta = DATOS / "promociones"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{dia.isoformat()}.json").write_text(json.dumps(resultado, indent=1, ensure_ascii=False), encoding="utf-8")


def mostrar(resultado: dict) -> None:
    print(f"\n=== PROMOCIONES (últimas {resultado['horas']} h, {resultado['leidas']} publicaciones leídas) ===")
    if not resultado["promociones"]:
        print("Ninguna sirve para el viaje a Japón.")
    for promo in resultado["promociones"]:
        print(f"- {promo['publicada'][:16].replace('T', ' ')} | {promo['titulo']}")
        print(f"  {' · '.join(promo['motivos'])}{' · ⚠️ ' + promo['aviso'] if promo['aviso'] else ''}")
        print(f"  {promo['link']}")
    for error in resultado["errores"]:
        print(f"ERROR: {error}")


def main() -> None:
    resultado = buscar(cargar_config())
    guardar(resultado, hoy())
    mostrar(resultado)


if __name__ == "__main__":
    main()
