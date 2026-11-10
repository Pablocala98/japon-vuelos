"""Arma vuelos/datos/aeropuertos.json a partir de la base pública de OurAirports (dominio público).

Se corre una sola vez, o cuando aparezca un aeropuerto que falte:
  curl -L -o /tmp/oa/airports.csv https://davidmegginson.github.io/ourairports-data/airports.csv
  curl -L -o /tmp/oa/countries.csv https://davidmegginson.github.io/ourairports-data/countries.csv
  .venv/bin/python herramientas/armar_aeropuertos.py /tmp/oa
"""
import csv
import json
import re
import sys
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "vuelos" / "datos" / "aeropuertos.json"
TIPOS = {"large_airport", "medium_airport"}

PAISES = {
    "AE": "Emiratos Árabes Unidos", "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BE": "Bélgica", "BO": "Bolivia",
    "BR": "Brasil", "CA": "Canadá", "CH": "Suiza", "CL": "Chile", "CN": "China", "CO": "Colombia", "CR": "Costa Rica",
    "CZ": "Chequia", "DE": "Alemania", "DK": "Dinamarca", "DO": "República Dominicana", "EC": "Ecuador", "EG": "Egipto",
    "ES": "España", "ET": "Etiopía", "FI": "Finlandia", "FR": "Francia", "GB": "Reino Unido", "GR": "Grecia",
    "HK": "Hong Kong", "HU": "Hungría", "ID": "Indonesia", "IE": "Irlanda", "IL": "Israel", "IN": "India", "IT": "Italia",
    "JO": "Jordania", "JP": "Japón", "KE": "Kenia", "KR": "Corea del Sur", "KW": "Kuwait", "MA": "Marruecos", "MO": "Macao",
    "MX": "México", "MY": "Malasia", "NL": "Países Bajos", "NO": "Noruega", "NZ": "Nueva Zelanda", "OM": "Omán",
    "PA": "Panamá", "PE": "Perú", "PH": "Filipinas", "PL": "Polonia", "PT": "Portugal", "PY": "Paraguay", "QA": "Catar",
    "RU": "Rusia", "SA": "Arabia Saudita", "SE": "Suecia", "SG": "Singapur", "TH": "Tailandia", "TR": "Turquía",
    "TW": "Taiwán", "US": "Estados Unidos", "UY": "Uruguay", "VE": "Venezuela", "VN": "Vietnam", "ZA": "Sudáfrica",
    "BH": "Baréin", "CU": "Cuba", "GT": "Guatemala", "SV": "El Salvador", "HN": "Honduras", "NI": "Nicaragua",
    "PR": "Puerto Rico", "RO": "Rumania", "RS": "Serbia", "HR": "Croacia", "LU": "Luxemburgo", "IS": "Islandia",
    "UZ": "Uzbekistán", "KZ": "Kazajistán", "LK": "Sri Lanka", "MV": "Maldivas", "NG": "Nigeria", "SN": "Senegal",
    "AO": "Angola", "MU": "Mauricio", "MN": "Mongolia", "KH": "Camboya", "MM": "Birmania", "NP": "Nepal",
    "PK": "Pakistán", "BD": "Bangladés", "IR": "Irán", "IQ": "Irak", "LB": "Líbano", "CY": "Chipre", "MT": "Malta",
}
CIUDADES = {
    "Tokyo": "Tokio", "Istanbul": "Estambul", "London": "Londres", "Frankfurt am Main": "Fráncfort", "Frankfurt": "Fráncfort",
    "Zurich": "Zúrich", "New York": "Nueva York", "Munich": "Múnich", "Rome": "Roma", "Milan": "Milán", "Paris": "París",
    "Dubai": "Dubái", "Addis Ababa": "Adís Abeba", "São Paulo": "San Pablo", "Rio De Janeiro": "Río de Janeiro",
    "Rio de Janeiro": "Río de Janeiro", "Seoul": "Seúl", "Beijing": "Pekín", "Shanghai": "Shanghái", "Singapore": "Singapur",
    "Sydney": "Sídney", "Bogota": "Bogotá", "Panama City": "Ciudad de Panamá", "Mexico City": "Ciudad de México",
    "Lisbon": "Lisboa", "Brussels": "Bruselas", "Vienna": "Viena", "Copenhagen": "Copenhague", "Warsaw": "Varsovia",
    "Athens": "Atenas", "Cairo": "El Cairo", "Riyadh": "Riad", "Jeddah": "Yeda", "Moscow": "Moscú", "Geneva": "Ginebra",
    "Helsinki": "Helsinki", "Stockholm": "Estocolmo", "Dallas-Fort Worth": "Dallas", "Philadelphia": "Filadelfia",
    "Chengdu": "Chengdú", "Guangzhou": "Cantón", "Kuala Lumpur": "Kuala Lumpur", "Ho Chi Minh City": "Ciudad Ho Chi Minh",
    "Hanoi": "Hanói", "Taipei": "Taipéi", "Osaka": "Osaka", "Kyoto": "Kioto", "Montreal": "Montreal", "Doha": "Doha",
}
# Aeropuertos cuyo "municipio" en la base no es la ciudad que la gente reconoce.
POR_CODIGO = {
    "NRT": "Tokio (Narita)", "HND": "Tokio (Haneda)", "KIX": "Osaka (Kansai)", "ITM": "Osaka (Itami)",
    "EZE": "Buenos Aires (Ezeiza)", "AEP": "Buenos Aires (Aeroparque)", "GRU": "San Pablo (Guarulhos)",
    "CGH": "San Pablo (Congonhas)", "VCP": "Campinas", "GIG": "Río de Janeiro (Galeão)", "DFW": "Dallas",
    "JFK": "Nueva York (JFK)", "EWR": "Nueva York (Newark)", "IAD": "Washington (Dulles)", "ORD": "Chicago",
    "LHR": "Londres (Heathrow)", "LGW": "Londres (Gatwick)", "CDG": "París (Charles de Gaulle)", "FCO": "Roma (Fiumicino)",
    "MXP": "Milán (Malpensa)", "IST": "Estambul", "SAW": "Estambul (Sabiha Gökçen)", "PVG": "Shanghái (Pudong)",
    "PEK": "Pekín", "PKX": "Pekín (Daxing)", "ICN": "Seúl (Incheon)", "TFU": "Chengdú (Tianfu)", "AUH": "Abu Dabi",
    "IAH": "Houston", "SFO": "San Francisco", "LAX": "Los Ángeles", "YYZ": "Toronto", "YVR": "Vancouver",
    "SYD": "Sídney", "MEL": "Melbourne", "AKL": "Auckland", "AMS": "Ámsterdam",
}


def _nombre(nombre: str) -> str:
    """"Adolfo Suárez Madrid–Barajas Airport" -> "Adolfo Suárez Madrid–Barajas"."""
    limpio = re.sub(r"\s*\b(International\s+)?Airport\b\s*", " ", nombre.strip())
    return re.sub(r"\s+-\s+", " – ", re.sub(r"\s{2,}", " ", limpio)).strip(" -–")


def main(carpeta: str) -> None:
    origen = Path(carpeta)
    paises_en = {}
    with open(origen / "countries.csv", encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            paises_en[fila["code"]] = fila["name"]
    aeropuertos = {}
    with open(origen / "airports.csv", encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            codigo = (fila["iata_code"] or "").strip()
            if len(codigo) != 3 or fila["type"] not in TIPOS:
                continue
            if codigo in aeropuertos and fila["type"] != "large_airport":
                continue  # si un código aparece dos veces, gana el aeropuerto grande
            pais = fila["iso_country"]
            municipio = fila["municipality"] or ""
            aeropuertos[codigo] = {
                "nombre": _nombre(fila["name"]),
                "ciudad": POR_CODIGO.get(codigo) or CIUDADES.get(municipio, municipio),
                "pais": PAISES.get(pais, paises_en.get(pais, pais)),
                "pais_codigo": pais,
            }
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(dict(sorted(aeropuertos.items())), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(aeropuertos)} aeropuertos en {DESTINO}")


if __name__ == "__main__":
    main(sys.argv[1])
