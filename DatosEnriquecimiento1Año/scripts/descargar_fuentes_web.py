from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver

BASE = Path(__file__).resolve().parent.parent
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

CALENDAR_COLUMN_ORDER = (
    "timestamp",
    "fecha_local",
    "hora_local",
    "minuto",
    "mes",
    "dia_del_anio",
    "dia_semana",
    "es_fin_de_semana",
    "es_festivo",
    "festivo_nombre",
    "es_laborable",
    "hora_sin",
    "hora_cos",
    "dow_sin",
    "dow_cos",
    "doy_sin",
    "doy_cos",
    "turistas_stopover_mes",
    "turistas_stopover_anio_anterior",
    "turistas_variacion_pct",
    "turistas_stopover_dia_medio",
    "pasajeros_crucero_mes",
)

FLEET_TYPE_ORDER = {
    "termica_motores": 0,
    "termica_turbina_gas": 1,
    "eolica": 2,
    "solar_fv": 3,
    "almacenamiento": 4,
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

    for row in soup.select("tr"):

        cells = [cell.get_text(" ", strip=True) for cell in row.select("th, td")]

        if len(cells) >= 2:

            label, value = cells[0], cells[1]
            key = FLEET_NAME_MAP.get(label.casefold())
            capacity = _capacity_mw(value)

            if key and capacity is not None:

                equipment[key] = capacity

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

    equipment["capacidad_firme_total_mw"] = sum(
        equipment[name]
        for name in (
            "Recip Phase 1+2 (6 motores)",
            "Recip Phase 3 (4 motores)",
            "Recip Phase 3 Expansion (2 motores)",
            "Recip Phase 4 (6 motores)",
            "Turbina de gas (GT)",
        )
    )

    equipment["renovable_total_mw"] = sum(
        equipment[name] for name in ("Parque eólico Vader Piet", "Sunrise Solar Park")
    )

    return {"equipos": equipment, "demanda": demand}


def extract_holidays(pages: dict[str, BeautifulSoup]):
    holidays: dict[str, str] = {}

    for page_name, soup in pages.items():

        if page_name.startswith("holidays_"):

            for row in soup.select("tr"):

                cells = [
                    cell.get_text(" ", strip=True) for cell in row.select("th, td")
                ]

                if len(cells) >= 2 and cells[0] and cells[1]:

                    holiday_name, date_text = cells[0], cells[1]
                    is_season = (
                        "equinox" in holiday_name.casefold()
                        or "solstice" in holiday_name.casefold()
                    )

                    if not is_season:

                        try:

                            holiday_date = datetime.strptime(
                                date_text, "%A, %B %d, %Y"
                            ).date()
                        except ValueError:

                            holiday_date = None
                        if holiday_date is not None:

                            holidays[holiday_date.isoformat()] = holiday_name

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


def update_electricity_files(
    source_system_dir: Path,
    output_system_dir: Path,
    facts: dict[str, object],
    captured_at: str,
):

    output_system_dir.mkdir(parents=True, exist_ok=True)

    for filename in (
        "aruba_sistema_electrico.csv",
        "aruba_demanda_referencia.json",
    ):
        shutil.copy2(source_system_dir / filename, output_system_dir / filename)

    csv_path = output_system_dir / "aruba_sistema_electrico.csv"

    with csv_path.open(encoding="utf-8-sig", newline="") as stream:

        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames or not rows:

        raise ValueError(f"El fichero de parque está vacío: {csv_path}")

    equipment = facts["equipos"]

    if not isinstance(equipment, dict):

        raise ValueError(
            "Los datos de capacidades extraídos no tienen el formato esperado."
        )

    for row in rows:

        if row["unidad"] in equipment:

            row["capacidad_mw"] = f"{equipment[row['unidad']]:.1f}"

    rows.sort(
        key=lambda row: (
            FLEET_TYPE_ORDER.get(row["tipo"], len(FLEET_TYPE_ORDER)),
            row["unidad"].casefold(),
        )
    )

    with csv_path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    demand = facts["demanda"]

    if not isinstance(demand, dict):

        raise ValueError(
            "Los datos de demanda extraídos no tienen el formato esperado."
        )

    reference = {
        "fuente": SOURCES["web_aruba"],
        "fecha_extraccion_utc": captured_at,
        "capacidad_firme_total_mw": equipment["capacidad_firme_total_mw"],
        "renovable_total_mw": equipment["renovable_total_mw"],
        **demand,
    }

    (output_system_dir / "aruba_demanda_referencia.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def order_calendar_file(calendar_path: Path):

    with calendar_path.open(encoding="utf-8-sig", newline="") as stream:

        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames or "timestamp" not in fieldnames:

        raise ValueError(
            f"El calendario no tiene la columna 'timestamp': {calendar_path}"
        )

    ordered_columns = [
        column for column in CALENDAR_COLUMN_ORDER if column in fieldnames
    ]

    ordered_columns.extend(
        column for column in fieldnames if column not in ordered_columns
    )

    rows.sort(key=lambda row: row["timestamp"])

    with calendar_path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=ordered_columns)
        writer.writeheader()
        writer.writerows(rows)


def sort_fleet_file(fleet_path: Path):

    with fleet_path.open(encoding="utf-8-sig", newline="") as stream:

        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames or not {"unidad", "tipo", "capacidad_mw"}.issubset(fieldnames):

        raise ValueError(
            f"El inventario eléctrico tiene columnas inesperadas: {fleet_path}"
        )

    for row in rows:

        if row["capacidad_mw"]:

            row["capacidad_mw"] = f"{float(row['capacidad_mw']):.1f}"

    rows.sort(
        key=lambda row: (
            FLEET_TYPE_ORDER.get(row["tipo"], len(FLEET_TYPE_ORDER)),
            row["unidad"].casefold(),
        )
    )

    with fleet_path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def update_calendar(
    source_calendar_path: Path,
    output_calendar_path: Path,
    holidays: dict[str, str],
    tourism_path: Path,
):

    with tourism_path.open(encoding="utf-8-sig", newline="") as stream:

        tourism_by_month = {
            row["mes"]: row for row in csv.DictReader(stream) if row.get("mes")
        }

    with source_calendar_path.open(encoding="utf-8-sig", newline="") as stream:

        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames or not rows:

        raise ValueError(f"El calendario está vacío: {source_calendar_path}")

    for row in rows:

        local_date = date.fromisoformat(row["fecha_local"])
        holiday_name = holidays.get(local_date.isoformat(), "")
        row["festivo_nombre"] = holiday_name

        if holiday_name:

            row["es_festivo"] = "1"

        else:

            row["es_festivo"] = "0"

        if local_date.weekday() < 5 and not holiday_name:

            row["es_laborable"] = "1"

        else:

            row["es_laborable"] = "0"

        monthly = tourism_by_month.get(local_date.strftime("%Y-%m"))

        if monthly:

            stopover = monthly.get("stopover", "")
            cruises = monthly.get("cruceros_pasajeros", "")
            row["turistas_stopover_mes"] = stopover

            if stopover:

                daily_average = (
                    int(stopover) / monthrange(local_date.year, local_date.month)[1]
                )
                row["turistas_stopover_dia_medio"] = f"{daily_average:.1f}"

            else:

                row["turistas_stopover_dia_medio"] = ""

            row["pasajeros_crucero_mes"] = cruises
            row["turistas_stopover_anio_anterior"] = monthly.get(
                "stopover_anio_anterior", ""
            )
            row["turistas_variacion_pct"] = monthly.get("var_pct", "")

        else:

            row.setdefault("turistas_stopover_anio_anterior", "")
            row.setdefault("turistas_variacion_pct", "")

    for column in ("turistas_stopover_anio_anterior", "turistas_variacion_pct"):

        if column not in fieldnames:

            fieldnames.append(column)
    output_calendar_path.parent.mkdir(parents=True, exist_ok=True)

    with output_calendar_path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    order_calendar_file(output_calendar_path)


def copy_tourism_in_month_order(source_path: Path, output_path: Path):
    with source_path.open(encoding="utf-8-sig", newline="") as stream:

        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames or "mes" not in fieldnames:

        raise ValueError(f"El CSV mensual no tiene la columna 'mes': {source_path}")
    rows.sort(key=lambda row: row["mes"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:

        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def format_generated_outputs(output: Path):
    """Apply consistent column and row ordering to generated CSV files."""
    order_calendar_file(output / "calendario" / "aruba_calendario_5min.csv")
    sort_fleet_file(output / "sistema_electrico" / "aruba_sistema_electrico.csv")
    tourism_path = output / "turismo" / "aruba_turismo_mensual.csv"
    copy_tourism_in_month_order(tourism_path, tourism_path)


def run(
    base: Path,
    scrape: Callable[[dict[str, str]], dict[str, BeautifulSoup]] = scrape_pages,
    output: Path | None = None,
):
    output = output or base / "salida_web"
    base_resolved = base.resolve()
    output_resolved = output.resolve()
    source_dirs = {
        (base / name).resolve()
        for name in ("calendario", "sistema_electrico", "turismo")
    }
    if output_resolved == base_resolved or any(
        output_resolved == source_dir
        or source_dir in output_resolved.parents
        or output_resolved in source_dir.parents
        for source_dir in source_dirs
    ):
        raise ValueError(
            "La carpeta de salida debe ser distinta de los directorios de datos originales."
        )

    urls = {name: url for name, url in SOURCES.items() if name != "tourism"}
    pages = scrape(urls)
    power_facts = extract_power_facts(pages["web_aruba"])
    holidays = extract_holidays(pages)
    context_facts = extract_context_facts(pages)
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    update_electricity_files(
        base / "sistema_electrico",
        output / "sistema_electrico",
        power_facts,
        captured_at,
    )
    update_calendar(
        base / "calendario" / "aruba_calendario_5min.csv",
        output / "calendario" / "aruba_calendario_5min.csv",
        holidays,
        base / "turismo" / "aruba_turismo_mensual.csv",
    )
    copy_tourism_in_month_order(
        base / "turismo" / "aruba_turismo_mensual.csv",
        output / "turismo" / "aruba_turismo_mensual.csv",
    )
    format_generated_outputs(output)

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
            "archivo_local_utilizado": "turismo/aruba_turismo_mensual.csv",
            "nota": (
                "Se conserva la tabla recopilada localmente; la página de inicio "
                "no proporciona el conjunto mensual de Aruba como tabla descargable."
            ),
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
        help="Directorio DatosEnriquecimiento1Año.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Carpeta para los ficheros generados (por defecto, <base>/salida_web).",
    )
    args = parser.parse_args()
    try:

        evidence_path = run(args.base, output=args.output)
    except (OSError, ValueError, RuntimeError) as exc:

        print(f"Error al actualizar los datos: {exc}", file=sys.stderr)
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
