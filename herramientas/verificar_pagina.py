"""Abre docs/index.html en Chrome (sin ventana) y compara lo que se VE en cada tarjeta con docs/datos.js.

Uso: .venv/bin/python herramientas/verificar_pagina.py
Revisa precio, horarios, aeropuertos, escalas, duraciones, días en Japón y que no haya errores de JavaScript.
Necesita Google Chrome instalado. No gasta consultas.
"""
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Tarjetas(HTMLParser):
    """Junta el texto visible de cada <article id="opcion-...">, separando sus partes por clase."""

    def __init__(self):
        super().__init__()
        self.tarjetas: dict[str, dict] = {}
        self._pila: list[tuple[str, str | None]] = []
        self._actual: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "article" and (a.get("id") or "").startswith("opcion-"):
            self._actual = a["id"][7:]
            self.tarjetas[self._actual] = {"texto": [], "precio": [], "punta": [], "duracion": [], "escalas": []}
        clases = (a.get("class") or "").split()
        parte = next((c for c in ("precio-grande", "punta", "duracion", "escalas") if c in clases), None)
        self._pila.append((tag, parte))

    def handle_endtag(self, tag):
        while self._pila:
            abierto, _ = self._pila.pop()
            if abierto == tag:
                break
        if tag == "article":
            self._actual = None

    def handle_data(self, data):
        if not self._actual or not data.strip():
            return
        t = self.tarjetas[self._actual]
        t["texto"].append(data.strip())
        for _, parte in reversed(self._pila):
            if parte:
                t[{"precio-grande": "precio"}.get(parte, parte)].append(data.strip())
                break


def numero(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def minutos(t: dict) -> str:
    m = t["minutos"] if t.get("minutos") is not None else round(t["horas"] * 60)
    return f"{m // 60} h" + (f" {m % 60:02d}" if m % 60 else "")


def main() -> int:
    texto = (RAIZ / "docs" / "datos.js").read_text(encoding="utf-8")
    datos = json.loads(texto[texto.index("{"):texto.rindex("}") + 1])
    resultado = subprocess.run(
        ["perl", "-e", "alarm 60; exec @ARGV", CHROME, "--headless=old", "--disable-gpu", "--virtual-time-budget=5000",
         "--enable-logging=stderr", "--v=0", "--dump-dom", f"file://{RAIZ / 'docs' / 'index.html'}"],
        capture_output=True, text=True)
    errores_js = [l for l in resultado.stderr.splitlines() if "Uncaught" in l or ("CONSOLE" in l and "rror" in l)]
    parser = Tarjetas()
    parser.feed(resultado.stdout)
    problemas = [f"JavaScript: {e}" for e in errores_js]

    opciones = datos["opciones"] + (datos.get("stopovers") or {}).get("opciones", [])
    mostradas = 0
    for o in opciones:
        tarjeta = parser.tarjetas.get(o["id"])
        if not tarjeta:
            continue  # los stopovers solo se ven si coinciden con lo elegido en el formulario
        mostradas += 1
        visto = " ".join(tarjeta["texto"])
        # Precio grande = total con valijas, tal cual el dato.
        if numero(o["precio_con_valijas"]) not in " ".join(tarjeta["precio"]):
            problemas.append(f"{o['id']}: precio mostrado {tarjeta['precio']} != {o['precio_con_valijas']}")
        for t in o["tramos"]:
            for hora, aeropuerto in ((t["salida"][11:16], t["ruta"][0]), (t["llegada"][11:16], t["ruta"][-1])):
                if hora not in tarjeta["punta"] or aeropuerto not in tarjeta["punta"]:
                    problemas.append(f"{o['id']}: no se ve {hora} {aeropuerto}")
            if minutos(t) not in " ".join(tarjeta["duracion"]):
                problemas.append(f"{o['id']}: duración {minutos(t)} no aparece en {tarjeta['duracion']}")
            for p in t["paradas"]:
                if p["codigo"] not in tarjeta["escalas"]:
                    problemas.append(f"{o['id']}: falta la escala {p['codigo']}")
        if o.get("dias_en_japon") is not None and f"🗾 {o['dias_en_japon']} días" not in visto:
            problemas.append(f"{o['id']}: no se ven los {o['dias_en_japon']} días en Japón")
        if not o.get("confiable", True) and "sin confirmar" not in visto:
            problemas.append(f"{o['id']}: precio sin confirmar y la tarjeta no lo avisa")
        if o["equipaje"] == "sin_confirmar" and "🧳 ?" not in visto:
            problemas.append(f"{o['id']}: valija sin confirmar y la tarjeta no lo avisa")
        if o["equipaje"] == "incluida" and "🧳 incluida" not in visto:
            problemas.append(f"{o['id']}: valija incluida y la tarjeta no lo dice")
    sin_tarjeta = [o["id"] for o in datos["opciones"] if o["id"] not in parser.tarjetas]
    if sin_tarjeta:
        problemas.append(f"vuelos sin tarjeta en la página: {sin_tarjeta}")
    if re.search(r"undefined|NaN|\[object Object\]", " ".join(" ".join(t["texto"]) for t in parser.tarjetas.values())):
        problemas.append("aparece 'undefined', 'NaN' u 'object' en alguna tarjeta")

    print(f"Tarjetas revisadas: {mostradas} (de {len(datos['opciones'])} vuelos y {len(opciones) - len(datos['opciones'])} stopovers)")
    for p in problemas:
        print("  ✗", p)
    print("Sin problemas." if not problemas else f"{len(problemas)} problemas.")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
