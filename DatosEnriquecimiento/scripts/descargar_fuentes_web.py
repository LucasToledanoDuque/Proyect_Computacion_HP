"""Genera los datos de enriquecimiento de Aruba usando solo internet.

La única entrada local es aruba_stations.json, que debe
estar en la misma carpeta que este script. Si no está, solo se omiten las
estaciones. Lo que internet no publique se deja en blanco.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver

BASE = Path(__file__).resolve().parents[2] / "DatosEnriquecimiento"
SOURCES = {
    "web_aruba": "https://webaruba.com/energy/power-production-figures",
    "wartsila": (
        "https://www.wartsila.com/media/news/27-06-2025-plant-extension-order-"
        "boosts-wartsila-s-share-of-aruba-s-total-power-generation-capacity-to-85-percent-3600992"
    ),
    "vader_piet": "https://en.wikipedia.org/wiki/Vader_Piet_Wind_Farm",
    "sunrise": (
        "https://rmi.org/press-release/press-release-web-aruba-n-v-s-sunrise-"
        "solar-park-gets-a-green-light-for-initiation"
    ),
    "holidays_2025": "https://calendarific.com/holidays/2025/AW",
    "holidays_2026": "https://calendarific.com/holidays/2026/AW",
    "tourism": "https://tourismanalytics.com/",
}

# Páginas de Tourism Analytics donde aparecen las notas mensuales de Aruba
TOURISM_LISTING_URLS = {
    "tourism_list_1": "https://tourismanalytics.com/expertinsights",
    "tourism_list_2": "https://tourismanalytics.com/expertinsights/previous/2",
    "tourism_list_3": "https://tourismanalytics.com/expertinsights/previous/3",
    "tourism_list_4": "https://tourismanalytics.com/expertinsights/previous/4",
}

# Rango del calendario: el mismo que las lecturas aruba_readings_20260924.json.
CALENDAR_START = "2025-09-01T00:00:00"
CALENDAR_END = "2026-09-17T21:55:00"
CALENDAR_STEP_MINUTES = 5

FLEET_NAME_MAP = {
    "recip phase 1+2 (6 engines)": "Recip Phase 1+2 (6 motores)",
    "recip phase 3 (4 engines)": "Recip Phase 3 (4 motores)",
    "recip phase 3 expansion (2 engines)": "Recip Phase 3 Expansion (2 motores)",
    "recip phase 4 (6 engines)": "Recip Phase 4 (6 motores)",
    "gas turbine (gt)": "Turbina de gas (GT)",
    "wind turbines (wp-vaderpiet)": "Parque eólico Vader Piet",
    "sunrise solar park": "Sunrise Solar Park",
    "battery energy storage system i (bess i)": "BESS I",
}

# Texto que aparece en el nombre de la web 
FLEET_TYPE_RULES = (
    ("recip", "termica_motores"),
    ("gas turbine", "termica_turbina_gas"),
    ("wind", "eolica"),
    ("solar", "solar_fv"),
    ("battery", "almacenamiento"),
)

FLEET_TYPE_ORDER = {
    "termica_motores": 0,
    "termica_turbina_gas": 1,
    "eolica": 2,
    "solar_fv": 3,
    "almacenamiento": 4,
}

FLEET_COLUMN_ORDER = (
    "unidad",
    "tipo",
    "capacidad_mw",
    "operador",
    "lat",
    "lon",
    "nota",
)

# Calendarific solo da el nombre del festivo en inglés. Este diccionario lo
# convierte al formato "Inglés (Papiamento)" que usa el calendario del proyecto.
HOLIDAY_NAME_MAP = {
    "new year's day": "New Year's Day (Aña Nobo)",
    "betico croes' birthday": "Betico Croes Day (Dia di Betico)",
    "carnival monday": "Carnival Monday (Dialuna di Carnaval)",
    "national anthem and flag day": "National Anthem and Flag Day (Dia di Himno y Bandera)",
    "good friday": "Good Friday (Bierna Santo)",
    "easter monday": "Easter Monday (Di dos dia di Pasco)",
    "king's day": "King's Day (Dia di Rey)",
    "labor day": "Labour Day (Dia di Obrero)",
    "ascension day": "Ascension Day (Dia di Asuncion)",
    "christmas day": "Christmas Day (Pasco di Nacemento)",
    "boxing day": "Boxing Day (Di dos dia di Pasco di Nacemento)",
}

CALENDAR_COLUMN_ORDER = (
    "timestamp",
    "fecha_local",
    "hora_local",
    "minuto",
    "dia_semana",
    "es_fin_de_semana",
    "mes",
    "dia_del_anio",
    "festivo_nombre",
    "es_festivo",
    "es_laborable",
    "hora_sin",
    "hora_cos",
    "dow_sin",
    "dow_cos",
    "doy_sin",
    "doy_cos",
    "turistas_stopover_mes",
    "turistas_stopover_dia_medio",
    "pasajeros_crucero_mes",
)

TOURISM_COLUMN_ORDER = (
    "mes",
    "stopover",
    "stopover_anio_anterior",
    "var_pct",
    "cruceros_pasajeros",
    "nota",
)

STATIONS_COLUMN_ORDER = (
    "id",
    "name",
    "code",
    "latitude",
    "longitude",
    "elevation_m",
    "district",
    "is_active",
    "dist_vader_piet_km",
)

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

SPANISH_MONTHS = {
    1: "ene",
    2: "feb",
    3: "mar",
    4: "abr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "ago",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dic",
}


def scrape_pages(
    urls: dict[str, str],
    driver_factory: Callable[[], WebDriver] | None = None,
):

    if driver_factory is None:

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        driver_factory = lambda: webdriver.Chrome(options=options)

    pages: dict[str, BeautifulSoup] = {}
    with driver_factory() as driver:

        driver.set_page_load_timeout(45)

        for name, url in urls.items():

            driver.get(url)
            pages[name] = BeautifulSoup(driver.page_source, "html.parser")

    return pages


def _capacity_mw(value: str):

    match = re.search(r"([\d.,]+)\s*MW\b", value, re.IGNORECASE)

    if not match:

        return None

    return float(match.group(1).replace(",", ""))


def extract_power_facts(soup: BeautifulSoup):

    equipment: dict[str, float] = {}
    demand: dict[str, float] = {}
    extras: dict[str, float] = {}

    for row in soup.select("tr"):

        cells = [cell.get_text(" ", strip=True) for cell in row.select("th, td")]

        if len(cells) >= 2:

            label, value = cells[0], cells[1]
            key = FLEET_NAME_MAP.get(label.casefold())
            capacity = _capacity_mw(value)

            if key and capacity is not None:

                equipment[key] = capacity

                
                if key == "BESS I":

                    energy = re.search(r"([\d.,]+)\s*MWh", value, re.IGNORECASE)

                    if energy:

                        extras["bess_energia_mwh"] = float(
                            energy.group(1).replace(",", "")
                        )

            if (
                "average load demand (2026)" in label.casefold()
                and capacity is not None
            ):

                demand["demanda_media_proyectada_2026_mw"] = capacity

            elif (
                "max peak load demand (2026)" in label.casefold()
                and capacity is not None
            ):

                demand["demanda_pico_proyectada_2026_mw"] = capacity

    required = set(FLEET_NAME_MAP.values()) | {
        "demanda_media_proyectada_2026_mw",
        "demanda_pico_proyectada_2026_mw",
    }

    found = set(equipment) | set(demand)
    missing = sorted(required - found)

    if missing:

        raise ValueError(
            "La página de WEB Aruba no contiene los campos esperados: "
            + ", ".join(missing)
        )

    equipment["capacidad_firme_total_mw"] = round(
        sum(
            equipment[name]
            for name in (
                "Recip Phase 1+2 (6 motores)",
                "Recip Phase 3 (4 motores)",
                "Recip Phase 3 Expansion (2 motores)",
                "Recip Phase 4 (6 motores)",
                "Turbina de gas (GT)",
            )
        ),
        1,
    )

    equipment["renovable_total_mw"] = round(
        equipment["Parque eólico Vader Piet"] + equipment["Sunrise Solar Park"], 1
    )

    return {"equipos": equipment, "demanda": demand, "extras": extras}


def extract_holidays(pages: dict[str, BeautifulSoup]):

    holidays: dict[str, str] = {}

    for page_name, soup in pages.items():

        if not page_name.startswith("holidays_"):

            continue

        for row in soup.select("tr"):

            cells = [cell.get_text(" ", strip=True) for cell in row.select("th, td")]

            if len(cells) < 2 or not cells[0] or not cells[1]:

                continue

            holiday_name, date_text = cells[0], cells[1]

            # Los equinoccios y solsticios no son festivos.
            if "equinox" in holiday_name.casefold():

                continue

            if "solstice" in holiday_name.casefold():

                continue

            try:

                holiday_date = datetime.strptime(date_text, "%A, %B %d, %Y").date()

            except ValueError:

                continue

            # Se busca el nombre con papiamento; si no existe,
            # se deja el nombre en inglés de Calendarific.
            name_key = holiday_name.casefold()
            full_name = HOLIDAY_NAME_MAP.get(name_key, holiday_name)
            holidays[holiday_date.isoformat()] = full_name

    if not holidays:

        raise ValueError("No se encontraron festivos con fecha en Calendarific.")

    return holidays


def extract_context_facts(pages: dict[str, BeautifulSoup]):

    wartsila_text = pages["wartsila"].get_text(" ", strip=True)
    sunrise_text = pages["sunrise"].get_text(" ", strip=True)
    facts: dict[str, object] = {}

    patterns = {
        "ampliacion_wartsila_anunciada_mw": (
            wartsila_text,
            r"add an additional\s+([\d.,]+)\s*MW",
        ),
        "capacidad_wartsila_proyectada_mw": (
            wartsila_text,
            r"share of the island.s power generation capacity will be\s+([\d.,]+)\s*MW",
        ),
        "capacidad_isla_mencionada_en_anuncio_mw": (
            wartsila_text,
            r"representing\s+85\s*percent of the\s+([\d.,]+)\s*MW total",
        ),
        "sunrise_capacidad_anunciada_2017_mw": (
            sunrise_text,
            r"([\d.,]+)\s*MW project",
        ),
    }

    for name, (text, pattern) in patterns.items():

        match = re.search(pattern, text, re.IGNORECASE)

        if match:

            facts[name] = float(match.group(1).replace(",", ""))

    # Ubicación de la planta solar (aparece en la nota de prensa de RMI).
    location = re.search(r"(San Nicol[aá]s)", sunrise_text)

    if location:

        facts["sunrise_ubicacion"] = location.group(1)

    # Motores de la ampliación: "two Wärtsilä 50DF dual-fuel engines".
    engines = re.search(
        r"(\w+)\s+W[äa]rtsil[äa]\s+(\w+DF)\s+dual-fuel\s+engines",
        wartsila_text,
        re.IGNORECASE,
    )

    if engines:

        word = engines.group(1).lower()
        quantity = NUMBER_WORDS.get(word)

        if quantity is None and word.isdigit():

            quantity = int(word)

        if quantity is not None:

            facts["wartsila_motores_ampliacion"] = {
                "cantidad": quantity,
                "modelo": engines.group(2),
            }

    wikipedia_rows = []

    for row in pages["vader_piet"].select("table.infobox tr"):

        label = row.find(["th", "td"])
        value = row.find("td")

        if label and value and label is not value:

            wikipedia_rows.append(
                {
                    "campo": label.get_text(" ", strip=True),
                    "valor": value.get_text(" ", strip=True),
                }
            )

    facts["vader_piet_ficha_publicada"] = wikipedia_rows

    return facts


def wikipedia_value(rows: list[dict[str, str]], field: str):

    for row in rows:

        if row["campo"].casefold().startswith(field.casefold()):

            return row["valor"]

    return ""


def vader_piet_coordinates(facts: dict[str, object]):

    # La ficha de Wikipedia trae una fila "Coordinates" con el texto
    # "... 12.47411; -69.89111". De ahí se sacan latitud y longitud.
    for row in facts["vader_piet_ficha_publicada"]:

        if row["campo"] == "Coordinates":

            match = re.search(r"(-?\d+\.\d+);\s*(-?\d+\.\d+)", row["valor"])

            if match:

                latitude = float(match.group(1))
                longitude = float(match.group(2))

                return latitude, longitude

    raise ValueError("No se encontraron las coordenadas de Vader Piet en Wikipedia.")


def wind_farm_note(rows: list[dict[str, str]]):

    # Resultado: "10 turbinas x 3 MW, buje 80 m, rotor 90 m, operativo desde dic-2009"
    units = re.search(
        r"(\d+)\s*[×x]\s*([\d.]+)\s*MW", wikipedia_value(rows, "Units operational")
    )
    hub = re.search(r"(\d+)\s*m", wikipedia_value(rows, "Hub height"))
    rotor = re.search(r"(\d+)\s*m", wikipedia_value(rows, "Rotor diameter"))
    commissioned = re.search(
        r"([A-Za-z]+)\s+(\d{4})", wikipedia_value(rows, "Commission date")
    )

    if not (units and hub and rotor and commissioned):

        return ""

    try:

        month_number = datetime.strptime(commissioned.group(1), "%B").month

    except ValueError:

        return ""

    return (
        f"{units.group(1)} turbinas x {float(units.group(2)):g} MW, "
        f"buje {hub.group(1)} m, rotor {rotor.group(1)} m, "
        f"operativo desde {SPANISH_MONTHS[month_number]}-{commissioned.group(2)}"
    )


def fleet_type(english_name: str):

    for text, fleet_kind in FLEET_TYPE_RULES:

        if text in english_name:

            return fleet_kind

    return ""


def build_fleet_rows(
    power_facts: dict[str, object],
    context_facts: dict[str, object],
    vader_piet: tuple[float, float],
):

    equipment = power_facts["equipos"]
    extras = power_facts["extras"]
    rows = []

    for english_name, unit in FLEET_NAME_MAP.items():

        row = {
            "unidad": unit,
            "tipo": fleet_type(english_name),
            "capacidad_mw": f"{equipment[unit]:.1f}",
            "operador": "WEB Aruba",
            "lat": "",
            "lon": "",
            "nota": "",
        }

        if "expansion" in english_name:

            engines = context_facts.get("wartsila_motores_ampliacion")

            if engines:

                row["nota"] = (
                    f"{engines['cantidad']}x Wärtsilä {engines['modelo']} dual-fuel"
                )

        elif unit == "Parque eólico Vader Piet":

            row["lat"] = str(vader_piet[0])
            row["lon"] = str(vader_piet[1])
            row["nota"] = wind_farm_note(context_facts["vader_piet_ficha_publicada"])

        elif unit == "Sunrise Solar Park":

            announced = context_facts.get("sunrise_capacidad_anunciada_2017_mw")

            if announced is not None:

                # Los decimales se escriben con coma: 5,9 MW.
                announced_text = f"{announced:g}".replace(".", ",")
                current_text = f"{equipment[unit]:g}".replace(".", ",")
                place = context_facts.get("sunrise_ubicacion", "")
                prefix = f"{place}; " if place else ""
                row["nota"] = (
                    f"{prefix}{announced_text} MW en el anuncio de 2017, "
                    f"{current_text} MW según WEB"
                )

        elif unit == "BESS I" and "bess_energia_mwh" in extras:

            row["nota"] = f"{equipment[unit]:g} MW / {extras['bess_energia_mwh']:g} MWh"

        rows.append(row)

    rows.sort(
        key=lambda row: (
            FLEET_TYPE_ORDER.get(row["tipo"], len(FLEET_TYPE_ORDER)),
            row["unidad"].casefold(),
        )
    )

    return rows


def write_csv_file(path: Path, column_order: tuple[str, ...], rows: list[dict]):

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=column_order)
        writer.writeheader()
        writer.writerows(rows)


def write_demand_file(
    output_system_dir: Path,
    power_facts: dict[str, object],
):

    equipment = power_facts["equipos"]
    demand = power_facts["demanda"]

    reference = {
        "fuente": SOURCES["web_aruba"],
        "capacidad_firme_total_mw": round(equipment["capacidad_firme_total_mw"], 1),
        "renovable_total_mw": round(equipment["renovable_total_mw"], 1),
    }

    # La demanda se guarda como entero cuando no tiene decimales (121, no 121.0).
    for key, value in demand.items():

        if float(value).is_integer():

            reference[key] = int(value)

        else:

            reference[key] = value

    output_system_dir.mkdir(parents=True, exist_ok=True)
    (output_system_dir / "aruba_demanda_referencia.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def month_name_to_key(month_name: str, year_text: str):

    try:

        parsed = datetime.strptime(f"{month_name} {year_text}", "%B %Y")

    except ValueError:

        return None

    return (parsed.year, parsed.month)


def months_to_number(text: str):

    text = text.lower()

    if text in NUMBER_WORDS:

        return NUMBER_WORDS[text]

    if text.isdigit():

        return int(text)

    return None


def find_tourism_post_urls(listing_pages: dict[str, BeautifulSoup]):

    post_urls: dict[str, str] = {}
    seen_urls = set()

    for soup in listing_pages.values():

        for link in soup.select("a[href]"):

            href = link["href"]

            if "aruba-received" not in href or "stopover" not in href:

                continue

            full_url = urljoin(SOURCES["tourism"], href)

            if full_url in seen_urls:

                continue

            seen_urls.add(full_url)
            post_urls[f"tourism_post_{len(post_urls)}"] = full_url

    return post_urls


def extract_tourism_facts(*page_groups: dict[str, BeautifulSoup]):

    # Las claves son (año, mes) o (año, nº de meses acumulados).
    facts: dict[str, dict] = {
        "stopover": {},
        "stopover_acumulado": {},
        "cruceros": {},
        "cruceros_acumulado": {},
        "cruceros_escalas": {},
        "cruceros_por_escala": {},
    }

    for pages in page_groups:

        for soup in pages.values():

            text = soup.get_text(" ", strip=True).replace("\u200b", "")
            text = re.sub(r"\s+", " ", text)

            # "Aruba received 143,343 stopover arrivals in June 2026, 13.4% more
            #  than the 126,391 stopover visitors it received in June 2025."
            for match in re.finditer(
                r"Aruba received ([\d,]+) stopover arrivals in ([A-Za-z]+) (\d{4}),\s*"
                r"([\d.]+)%\s*(more|fewer|less)\s+than the ([\d,]+) stopover",
                text,
                re.IGNORECASE,
            ):

                total, month_name, year_text, percent, direction, previous = (
                    match.groups()
                )
                key = month_name_to_key(month_name, year_text)

                if key is None:

                    continue

                sign = "" if direction.lower() == "more" else "-"
                facts["stopover"][key] = (
                    int(total.replace(",", "")),
                    int(previous.replace(",", "")),
                    f"{sign}{percent}",
                )

            # "growing from 762,356 visitors in the first six months of 2025 to
            #  845,501 visitors in the first six months of this year"
            for match in re.finditer(
                r"growing from ([\d,]+) (?:stopover )?visitors in the first (\w+) "
                r"months of (\d{4}) to ([\d,]+) (?:stopover )?visitors in the first",
                text,
                re.IGNORECASE,
            ):

                previous_total, words, year_text, current_total = match.groups()
                months = months_to_number(words)

                if months is None:

                    continue

                # El año del texto es el anterior; el actual es el siguiente.
                year = int(year_text)
                facts["stopover_acumulado"][(year, months)] = int(
                    previous_total.replace(",", "")
                )
                facts["stopover_acumulado"][(year + 1, months)] = int(
                    current_total.replace(",", "")
                )

            # "... in the first eleven months of 2025 with 810,383 cruise passengers"
            # "... in CY 2025 with 970,803 cruise passengers"
            for match in re.finditer(
                r"(?:first (\w+) months of|CY) (\d{4}) with ([\d,]+) cruise passengers",
                text,
                re.IGNORECASE,
            ):

                words, year_text, total = match.groups()
                months = months_to_number(words) if words else 12

                if months is None:

                    continue

                facts["cruceros_acumulado"][(int(year_text), months)] = int(
                    total.replace(",", "")
                )

            # "... 42 cruise ship calls in November 2025 and a total of 98,980 cruise passengers"
            for match in re.finditer(
                r"cruise ship calls in ([A-Za-z]+) (\d{4}) and a total of ([\d,]+) "
                r"cruise passengers",
                text,
                re.IGNORECASE,
            ):

                key = month_name_to_key(match.group(1), match.group(2))

                if key is not None:

                    facts["cruceros"][key] = int(match.group(3).replace(",", ""))

            # Si no hay total mensual: escalas x pasajeros por escala.
            for match in re.finditer(
                r"(\d+) cruise ship calls in ([A-Za-z]+) (\d{4})", text
            ):

                key = month_name_to_key(match.group(2), match.group(3))

                if key is not None:

                    facts["cruceros_escalas"][key] = int(match.group(1))

            for match in re.finditer(
                r"to ([\d,]+) cruise visitors in ([A-Za-z]+) (\d{4})",
                text,
                re.IGNORECASE,
            ):

                key = month_name_to_key(match.group(2), match.group(3))

                if key is not None:

                    facts["cruceros_por_escala"][key] = int(
                        match.group(1).replace(",", "")
                    )

    return facts


def solve_missing_months(
    known: dict[tuple[int, int], int],
    cumulative: dict[tuple[int, int], int],
):

    # Cada acumulado publicado ("ene..n suman X") es una ecuación. Si en una
    # ecuación solo falta un mes, ese mes se obtiene por diferencia.
    equations = []

    for (year, last_month), total in cumulative.items():

        months = [(year, month) for month in range(1, last_month + 1)]
        equations.append((months, total, f"acumulado ene-{SPANISH_MONTHS[last_month]} {year}"))

        # La diferencia entre dos acumulados del mismo año también es una ecuación.
        for (other_year, other_last), other_total in cumulative.items():

            if other_year == year and other_last < last_month:

                months = [(year, month) for month in range(other_last + 1, last_month + 1)]
                equations.append(
                    (
                        months,
                        total - other_total,
                        f"acumulados ene-{SPANISH_MONTHS[last_month]} y "
                        f"ene-{SPANISH_MONTHS[other_last]} {year}",
                    )
                )

    derived: dict[tuple[int, int], str] = {}
    changed = True

    while changed:

        changed = False

        for months, total, label in equations:

            unknown = [month for month in months if month not in known]

            if len(unknown) != 1:

                continue

            known_sum = sum(known[month] for month in months if month in known)
            value = total - known_sum

            if value >= 0:

                known[unknown[0]] = value
                derived[unknown[0]] = label
                changed = True

    return derived


def build_tourism_rows(facts: dict[str, dict], months: list[tuple[int, int]]):

    # Stopover: valores publicados (mes actual y mismo mes del año anterior).
    stopover_known: dict[tuple[int, int], int] = {}

    for (year, month), (current, previous, _percent) in facts["stopover"].items():

        stopover_known[(year, month)] = current
        stopover_known.setdefault((year - 1, month), previous)

    stopover_derived = solve_missing_months(stopover_known, facts["stopover_acumulado"])

    # Cruceros: total mensual publicado, o escalas x pasajeros por escala.
    cruise_known = dict(facts["cruceros"])
    cruise_derived: dict[tuple[int, int], str] = {}

    for key, calls in facts["cruceros_escalas"].items():

        if key not in cruise_known and key in facts["cruceros_por_escala"]:

            cruise_known[key] = calls * facts["cruceros_por_escala"][key]
            cruise_derived[key] = "escalas x pasajeros por escala"

    cruise_derived.update(
        solve_missing_months(cruise_known, facts["cruceros_acumulado"])
    )

    rows = []

    for year, month in months:

        key = (year, month)
        stopover = stopover_known.get(key)
        previous = None
        percent = ""
        notes = []

        if stopover is not None:

            previous = stopover_known.get((year - 1, month))

            if key in facts["stopover"]:

                percent = facts["stopover"][key][2]

            elif previous:

                percent = f"{(stopover / previous - 1) * 100:.1f}"

        else:

            notes.append("Aún no publicado")

        if key in stopover_derived:

            notes.append(f"Stopover derivado de {stopover_derived[key]}")

        if key in cruise_derived:

            notes.append(f"Cruceros derivados de {cruise_derived[key]}")

        cruises = cruise_known.get(key)

        rows.append(
            {
                "mes": f"{year}-{month:02d}",
                "stopover": "" if stopover is None else str(stopover),
                "stopover_anio_anterior": "" if previous is None else str(previous),
                "var_pct": percent,
                "cruceros_pasajeros": "" if cruises is None else str(cruises),
                "nota": "; ".join(notes),
            }
        )

    return rows


def months_between(start: datetime, end: datetime):

    months = []
    year, month = start.year, start.month

    while (year, month) <= (end.year, end.month):

        months.append((year, month))
        month += 1

        if month > 12:

            year += 1
            month = 1

    return months


def write_calendar_file(
    calendar_path: Path,
    start: datetime,
    end: datetime,
    holidays: dict[str, str],
    tourism_rows: list[dict[str, str]],
):

    tourism_by_month = {row["mes"]: row for row in tourism_rows}
    step = timedelta(minutes=CALENDAR_STEP_MINUTES)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)

    with calendar_path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=CALENDAR_COLUMN_ORDER)
        writer.writeheader()
        current = start

        while current <= end:

            local_date = current.date()
            weekday = local_date.weekday()
            day_of_year = local_date.timetuple().tm_yday
            hour_fraction = current.hour + current.minute / 60
            holiday_name = holidays.get(local_date.isoformat(), "")
            monthly = tourism_by_month.get(local_date.strftime("%Y-%m"), {})
            stopover = monthly.get("stopover", "")

            if stopover:

                days_in_month = monthrange(local_date.year, local_date.month)[1]
                daily_average = f"{int(stopover) / days_in_month:.1f}"

            else:

                daily_average = ""

            row = {
                "timestamp": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fecha_local": local_date.isoformat(),
                "hora_local": current.hour,
                "minuto": current.minute,
                "dia_semana": weekday,
                "es_fin_de_semana": int(weekday >= 5),
                "mes": local_date.month,
                "dia_del_anio": day_of_year,
                "festivo_nombre": holiday_name,
                "es_festivo": int(bool(holiday_name)),
                "es_laborable": int(weekday < 5 and not holiday_name),
                "hora_sin": round(math.sin(2 * math.pi * hour_fraction / 24), 4),
                "hora_cos": round(math.cos(2 * math.pi * hour_fraction / 24), 4),
                "dow_sin": round(math.sin(2 * math.pi * weekday / 7), 4),
                "dow_cos": round(math.cos(2 * math.pi * weekday / 7), 4),
                "doy_sin": round(math.sin(2 * math.pi * day_of_year / 365.25), 4),
                "doy_cos": round(math.cos(2 * math.pi * day_of_year / 365.25), 4),
                "turistas_stopover_mes": stopover,
                "turistas_stopover_dia_medio": daily_average,
                "pasajeros_crucero_mes": monthly.get("cruceros_pasajeros", ""),
            }
            writer.writerow(row)
            current += step


def distance_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float):

    # Distancia en línea recta sobre la superficie de la Tierra (fórmula de haversine).
    earth_radius_km = 6371.0088

    lat_a_rad = math.radians(lat_a)
    lat_b_rad = math.radians(lat_b)
    delta_lat = lat_b_rad - lat_a_rad
    delta_lon = math.radians(lon_b - lon_a)

    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a_rad) * math.cos(lat_b_rad) * math.sin(delta_lon / 2) ** 2
    )

    return 2 * earth_radius_km * math.asin(math.sqrt(haversine))


def update_stations(
    stations_path: Path,
    output_stations_dir: Path,
    vader_piet: tuple[float, float],
):

    stations = json.loads(stations_path.read_text(encoding="utf-8-sig"))

    if not stations:

        raise ValueError(f"El fichero de estaciones está vacío: {stations_path}")

    rows = []

    for station in stations:

        distance = distance_km(
            vader_piet[0],
            vader_piet[1],
            station["latitude"],
            station["longitude"],
        )

        # Se copian los datos de la estación y se añade la distancia a Vader Piet.
        row = {
            "id": station.get("id"),
            "name": station.get("name"),
            "code": station.get("code"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
            "elevation_m": station.get("elevation_m"),
            "district": station.get("district"),
            "is_active": station.get("is_active"),
            "dist_vader_piet_km": round(distance, 2),
        }
        rows.append(row)

    rows.sort(key=lambda row: row["code"])
    output_stations_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_stations_dir / "aruba_estaciones_enriquecidas.csv"

    with csv_path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=STATIONS_COLUMN_ORDER)
        writer.writeheader()
        writer.writerows(rows)

    # El JSON usa ":" sin espacio para mantener el formato del fichero original.
    json_path = output_stations_dir / "aruba_estaciones_enriquecidas.json"
    json_text = json.dumps(rows, ensure_ascii=False, indent=2, separators=(",", ":"))
    json_path.write_text(json_text, encoding="utf-8")


def keys_to_text(values: dict):

    # Las claves (año, mes) no se pueden guardar en JSON: se pasan a texto.
    return {str(key): value for key, value in values.items()}


def run(
    base: Path,
    scrape: Callable[[dict[str, str]], dict[str, BeautifulSoup]] = scrape_pages,
    output: Path | None = None,
    stations_path: Path | None = None,
    calendar_start: str = CALENDAR_START,
    calendar_end: str = CALENDAR_END,
):
    output = output or base / "salida_web"
    base_resolved = base.resolve()
    output_resolved = output.resolve()
    data_dirs = {
        (base / name).resolve()
        for name in (
            "calendario",
            "sistema_electrico",
            "turismo",
            "clima_solar_estaciones",
        )
    }
    if output_resolved == base_resolved or any(
        output_resolved == data_dir
        or data_dir in output_resolved.parents
        or output_resolved in data_dir.parents
        for data_dir in data_dirs
    ):
        raise ValueError(
            "La carpeta de salida debe ser distinta de los directorios de datos originales."
        )

    start = datetime.fromisoformat(calendar_start)
    end = datetime.fromisoformat(calendar_end)

    if end < start:

        raise ValueError("El fin del calendario es anterior al inicio.")

    # 1. Se descargan las páginas.
    urls = {name: url for name, url in SOURCES.items() if name != "tourism"}
    pages = scrape(urls)
    tourism_listing_pages = scrape(TOURISM_LISTING_URLS)
    tourism_post_urls = find_tourism_post_urls(tourism_listing_pages)
    tourism_post_pages = scrape(tourism_post_urls) if tourism_post_urls else {}

    # 2. Se extraen los datos de cada página.
    power_facts = extract_power_facts(pages["web_aruba"])
    holidays = extract_holidays(pages)
    context_facts = extract_context_facts(pages)
    vader_piet = vader_piet_coordinates(context_facts)
    tourism_facts = extract_tourism_facts(tourism_listing_pages, tourism_post_pages)
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 3. Se construyen y se guardan las tablas.
    fleet_rows = build_fleet_rows(power_facts, context_facts, vader_piet)
    write_csv_file(
        output / "sistema_electrico" / "aruba_sistema_electrico.csv",
        FLEET_COLUMN_ORDER,
        fleet_rows,
    )
    write_demand_file(output / "sistema_electrico", power_facts)

    tourism_rows = build_tourism_rows(tourism_facts, months_between(start, end))
    write_csv_file(
        output / "turismo" / "aruba_turismo_mensual.csv",
        TOURISM_COLUMN_ORDER,
        tourism_rows,
    )

    write_calendar_file(
        output / "calendario" / "aruba_calendario_5min.csv",
        start,
        end,
        holidays,
        tourism_rows,
    )

    if stations_path is not None:

        update_stations(
            stations_path,
            output / "clima_solar_estaciones",
            vader_piet,
        )

    # 4. Se guarda de dónde sale cada dato y qué no se ha podido obtener.
    months_without_data = []

    for row in tourism_rows:

        if not row["stopover"]:

            months_without_data.append(f"{row['mes']} stopover")

        if not row["cruceros_pasajeros"]:

            months_without_data.append(f"{row['mes']} cruceros")

    provenance = {
        "fecha_extraccion_utc": captured_at,
        "fuentes_consultadas": {
            name: url for name, url in SOURCES.items() if name != "tourism"
        },
        "hechos_temporales_aplicados_al_calendario": dict(sorted(holidays.items())),
        "hechos_contextuales": {
            "web_aruba": power_facts,
            "articulos_y_ficha": context_facts,
        },
        "turismo": {
            "fuente": SOURCES["tourism"],
            "hechos_encontrados": {
                name: keys_to_text(values) for name, values in tourism_facts.items()
            },
            "meses_sin_dato": months_without_data,
        },
        "alcance": (
            "Festivos y turismo se asocian por fecha/mes en el calendario. "
            "Las páginas de capacidades y noticias son contexto EDA, no "
            "mediciones meteorológicas por lectura."
        ),
    }
    evidence_path = output / "sistema_electrico" / "fuentes_web.json"
    evidence_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return evidence_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        type=Path,
        default=BASE,
        help="Directorio DatosEnriquecimiento.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Carpeta para los ficheros generados (por defecto, <base>/salida_web).",
    )
    parser.add_argument(
        "--stations",
        type=Path,
        default=Path(__file__).resolve().parent / "aruba_stations.json",
        help="aruba_stations.json (por defecto, en la misma carpeta que este script).",
    )
    parser.add_argument(
        "--calendar-start",
        default=CALENDAR_START,
        help="Inicio del calendario, por ejemplo 2025-09-01T00:00:00.",
    )
    parser.add_argument(
        "--calendar-end",
        default=CALENDAR_END,
        help="Fin del calendario, por ejemplo 2026-09-17T21:55:00.",
    )
    args = parser.parse_args()

    # aruba_stations.json es opcional: si no está, solo se omiten las estaciones.
    stations_path = args.stations

    if not stations_path.is_file():

        print(f"Aviso: no se encontró {stations_path}; no se generan las estaciones.")
        stations_path = None

    try:

        evidence_path = run(
            args.base,
            output=args.output,
            stations_path=stations_path,
            calendar_start=args.calendar_start,
            calendar_end=args.calendar_end,
        )
    except (OSError, ValueError, RuntimeError) as exc:

        print(f"Error al generar los datos: {exc}", file=sys.stderr)
        return 1
    except WebDriverException as exc:

        print(
            "Error de Selenium/Chrome. Comprueba que Chrome está instalado "
            f"y que Selenium Manager puede descargar el driver: {exc}",
            file=sys.stderr,
        )
        return 1

    print("Se generaron ficheros enriquecidos en una carpeta separada.")
    print(f"Salida: {evidence_path.parent.parent}")
    print(f"Procedencia guardada en: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
