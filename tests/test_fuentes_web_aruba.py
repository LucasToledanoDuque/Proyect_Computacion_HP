import csv
import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "DatosEnriquecimiento1Año" / "scripts"),
)

from descargar_fuentes_web import (
    extract_context_facts,
    extract_holidays,
    extract_power_facts,
    format_generated_outputs,
    run,
    scrape_pages,
    update_calendar,
)


class FakeDriver:
    def __init__(self):
        self.page_source = ""
        self.visited = []
        self.closed = False
        self.timeout = None

    def set_page_load_timeout(self, _timeout):
        self.timeout = _timeout

    def get(self, url):
        self.visited.append(url)
        self.page_source = f"<html><body><p>{url}</p></body></html>"

    def quit(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _exception_type, _exception_value, _traceback):
        self.quit()
        return False


class WebSourceTests(unittest.TestCase):
    def test_selenium_renders_pages_and_soup_parses_rendered_html(self):
        driver = FakeDriver()
        pages = scrape_pages(
            {"web": "https://example.test/"},
            driver_factory=lambda: driver,
        )

        self.assertIn("https://example.test/", pages["web"].get_text())
        self.assertEqual(driver.visited, ["https://example.test/"])
        self.assertTrue(driver.closed)
        self.assertEqual(driver.timeout, 45)

    def test_extracts_current_capacity_and_demand_table(self):
        rows = [
            ("Recip Phase 1+2 (6 Engines)", "47.4 MW"),
            ("Recip Phase 3 (4 Engines)", "45.6 MW"),
            ("Recip Phase 3 Expansion (2 Engines)", "36.2 MW"),
            ("Recip Phase 4 (6 Engines)", "103.2 MW"),
            ("Gas Turbine (GT)", "20.0 MW"),
            ("Wind Turbines (WP-Vaderpiet)", "30.0 MW"),
            ("Sunrise Solar Park", "6.1 MW"),
            ("Battery Energy Storage System I (BESS I)", "1 MW / 4 MWh"),
            ("Average load demand (2026)", "121 MW"),
            ("Max peak load demand (2026)", "172 MW"),
        ]
        html = (
            "<table>"
            + "".join(
                f"<tr><td>{name}</td><td>{value}</td></tr>" for name, value in rows
            )
            + "</table>"
        )

        facts = extract_power_facts(BeautifulSoup(html, "html.parser"))

        self.assertEqual(facts["equipos"]["capacidad_firme_total_mw"], 252.4)
        self.assertAlmostEqual(facts["equipos"]["renovable_total_mw"], 36.1)
        self.assertEqual(facts["demanda"]["demanda_media_proyectada_2026_mw"], 121)

    def test_holidays_exclude_equinox_and_solstice_rows(self):
        html = """
        <table>
          <tr><td>Christmas Day</td><td>Thursday, December 25, 2025</td></tr>
          <tr><td>King's Day</td><td>Monday, April 27, 2026</td></tr>
          <tr><td>June Solstice</td><td>Sunday, June 21, 2026</td></tr>
        </table>
        """
        holidays = extract_holidays(
            {"holidays_2025": BeautifulSoup(html, "html.parser")}
        )

        self.assertEqual(holidays["2025-12-25"], "Christmas Day")
        self.assertEqual(holidays["2026-04-27"], "King's Day")
        self.assertNotIn("2026-06-21", holidays)

    def test_context_facts_keep_old_capacity_announcements_distinct(self):
        pages = {
            "wartsila": BeautifulSoup(
                "<p>This will add an additional 36 MW. "
                "The share of the island's power generation capacity will be "
                "230 MW, representing 85 percent of the 268 MW total.</p>",
                "html.parser",
            ),
            "sunrise": BeautifulSoup(
                "<p>This ambitious 5.9 MW project is planned.</p>", "html.parser"
            ),
            "vader_piet": BeautifulSoup(
                '<table class="infobox"><tr><th>Capacity</th>'
                "<td>30 MW</td></tr></table>",
                "html.parser",
            ),
        }

        facts = extract_context_facts(pages)

        self.assertEqual(facts["ampliacion_wartsila_anunciada_mw"], 36)
        self.assertEqual(facts["capacidad_isla_mencionada_en_anuncio_mw"], 268)
        self.assertEqual(facts["sunrise_capacidad_anunciada_2017_mw"], 5.9)
        self.assertEqual(
            facts["vader_piet_ficha_publicada"],
            [{"campo": "Capacity", "valor": "30 MW"}],
        )

    def test_calendar_merges_holidays_and_monthly_tourism_by_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:

            root = Path(temp_dir)
            source_calendar_path = root / "calendar.csv"
            output_calendar_path = root / "output" / "calendar.csv"
            tourism_path = root / "tourism.csv"
            columns = [
                "timestamp",
                "fecha_local",
                "es_fin_de_semana",
                "festivo_nombre",
                "es_festivo",
                "es_laborable",
                "turistas_stopover_mes",
                "turistas_stopover_dia_medio",
                "pasajeros_crucero_mes",
            ]
            with source_calendar_path.open("w", encoding="utf-8", newline="") as stream:

                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": "2026-04-27T00:00:00Z",
                        "fecha_local": "2026-04-27",
                    }
                )
            with tourism_path.open("w", encoding="utf-8", newline="") as stream:

                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "mes",
                        "stopover",
                        "stopover_anio_anterior",
                        "var_pct",
                        "cruceros_pasajeros",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "mes": "2026-04",
                        "stopover": "141135",
                        "stopover_anio_anterior": "126419",
                        "var_pct": "11.6",
                        "cruceros_pasajeros": "86466",
                    }
                )

            update_calendar(
                source_calendar_path,
                output_calendar_path,
                {"2026-04-27": "King's Day"},
                tourism_path,
            )

            with output_calendar_path.open(encoding="utf-8", newline="") as stream:

                output_reader = csv.DictReader(stream)
                output_columns = output_reader.fieldnames
                row = next(output_reader)
            self.assertEqual(row["es_festivo"], "1")
            self.assertEqual(row["es_laborable"], "0")
            self.assertEqual(row["turistas_stopover_mes"], "141135")
            self.assertEqual(row["turistas_stopover_dia_medio"], "4704.5")
            self.assertEqual(row["turistas_stopover_anio_anterior"], "126419")
            self.assertEqual(row["turistas_variacion_pct"], "11.6")
            self.assertEqual(row["pasajeros_crucero_mes"], "86466")
            self.assertLess(
                output_columns.index("timestamp"),
                output_columns.index("fecha_local"),
            )
            self.assertLess(
                output_columns.index("es_festivo"),
                output_columns.index("turistas_stopover_mes"),
            )
            self.assertLess(
                output_columns.index("turistas_stopover_anio_anterior"),
                output_columns.index("pasajeros_crucero_mes"),
            )
            with source_calendar_path.open(encoding="utf-8", newline="") as stream:

                original_row = next(csv.DictReader(stream))
            self.assertEqual(original_row["festivo_nombre"], "")

    def test_run_writes_separate_enriched_files_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:

            base = Path(temp_dir) / "DatosEnriquecimiento1Año"
            for directory in ("calendario", "sistema_electrico", "turismo"):

                (base / directory).mkdir(parents=True)

            calendar_source = base / "calendario" / "aruba_calendario_5min.csv"
            with calendar_source.open("w", encoding="utf-8", newline="") as stream:

                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "timestamp",
                        "fecha_local",
                        "festivo_nombre",
                        "es_festivo",
                        "es_laborable",
                        "turistas_stopover_mes",
                        "turistas_stopover_dia_medio",
                        "pasajeros_crucero_mes",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": "2026-04-27T00:00:00Z",
                        "fecha_local": "2026-04-27",
                    }
                )

            system_dir = base / "sistema_electrico"
            system_csv = system_dir / "aruba_sistema_electrico.csv"
            system_csv.write_text(
                "unidad,tipo,capacidad_mw,operador\n"
                "Recip Phase 1+2 (6 motores),termica_motores,1,WEB Aruba\n"
                "Recip Phase 3 (4 motores),termica_motores,1,WEB Aruba\n"
                "Recip Phase 3 Expansion (2 motores),termica_motores,1,WEB Aruba\n"
                "Recip Phase 4 (6 motores),termica_motores,1,WEB Aruba\n"
                "Turbina de gas (GT),termica_turbina_gas,1,WEB Aruba\n"
                "Parque eólico Vader Piet,eolica,1,WEB Aruba\n"
                "Sunrise Solar Park,solar_fv,1,WEB Aruba\n"
                "BESS I,almacenamiento,1,WEB Aruba\n",
                encoding="utf-8",
            )
            demand_json = system_dir / "aruba_demanda_referencia.json"
            demand_json.write_text('{"fuente":"original"}\n', encoding="utf-8")
            tourism_csv = base / "turismo" / "aruba_turismo_mensual.csv"
            tourism_csv.write_text(
                "mes,stopover,stopover_anio_anterior,var_pct,cruceros_pasajeros\n"
                "2026-04,141135,126419,11.6,86466\n",
                encoding="utf-8",
            )
            source_bytes = {
                path: path.read_bytes()
                for path in (calendar_source, system_csv, demand_json, tourism_csv)
            }

            equipment = [
                ("Recip Phase 1+2 (6 Engines)", "47.4 MW"),
                ("Recip Phase 3 (4 Engines)", "45.6 MW"),
                ("Recip Phase 3 Expansion (2 Engines)", "36.2 MW"),
                ("Recip Phase 4 (6 Engines)", "103.2 MW"),
                ("Gas Turbine (GT)", "20.0 MW"),
                ("Wind Turbines (WP-Vaderpiet)", "30.0 MW"),
                ("Sunrise Solar Park", "6.1 MW"),
                ("Battery Energy Storage System I (BESS I)", "1 MW / 4 MWh"),
                ("Average load demand (2026)", "121 MW"),
                ("Max peak load demand (2026)", "172 MW"),
            ]
            power_html = (
                "<table>"
                + "".join(
                    f"<tr><td>{name}</td><td>{value}</td></tr>"
                    for name, value in equipment
                )
                + "</table>"
            )
            holidays_html = (
                "<table><tr><td>King's Day</td>"
                "<td>Monday, April 27, 2026</td></tr></table>"
            )

            def scrape(_urls):
                return {
                    "web_aruba": BeautifulSoup(power_html, "html.parser"),
                    "holidays_2025": BeautifulSoup(holidays_html, "html.parser"),
                    "holidays_2026": BeautifulSoup(holidays_html, "html.parser"),
                    "wartsila": BeautifulSoup(
                        "<p>add an additional 36 MW</p>", "html.parser"
                    ),
                    "sunrise": BeautifulSoup("<p>5.9 MW project</p>", "html.parser"),
                    "vader_piet": BeautifulSoup(
                        "<table class='infobox'></table>", "html.parser"
                    ),
                }

            evidence_path = run(base, scrape=scrape)
            output = base / "salida_web"
            self.assertEqual(
                evidence_path,
                output / "sistema_electrico" / "fuentes_web.json",
            )
            self.assertTrue(
                (output / "calendario" / "aruba_calendario_5min.csv").exists()
            )
            self.assertTrue(
                (output / "sistema_electrico" / "aruba_sistema_electrico.csv").exists()
            )
            self.assertTrue((output / "turismo" / "aruba_turismo_mensual.csv").exists())
            for path, content in source_bytes.items():

                self.assertEqual(path.read_bytes(), content)

            with (output / "calendario" / "aruba_calendario_5min.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                enriched = next(csv.DictReader(stream))
            self.assertEqual(enriched["festivo_nombre"], "King's Day")
            self.assertEqual(enriched["turistas_stopover_mes"], "141135")
            with (output / "sistema_electrico" / "aruba_sistema_electrico.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                fleet_rows = list(csv.DictReader(stream))
            self.assertEqual(
                [row["tipo"] for row in fleet_rows],
                [
                    "termica_motores",
                    "termica_motores",
                    "termica_motores",
                    "termica_motores",
                    "termica_turbina_gas",
                    "eolica",
                    "solar_fv",
                    "almacenamiento",
                ],
            )
            self.assertEqual(
                fleet_rows[0]["capacidad_mw"],
                "47.4",
            )
            with (output / "turismo" / "aruba_turismo_mensual.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                tourism_months = [row["mes"] for row in csv.DictReader(stream)]
            self.assertEqual(tourism_months, sorted(tourism_months))
            format_generated_outputs(output)
            with (output / "sistema_electrico" / "aruba_sistema_electrico.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                fleet_rows = list(csv.DictReader(stream))
            self.assertEqual(
                [row["capacidad_mw"] for row in fleet_rows],
                [
                    "47.4",
                    "45.6",
                    "36.2",
                    "103.2",
                    "20.0",
                    "30.0",
                    "6.1",
                    "1.0",
                ],
            )


if __name__ == "__main__":

    unittest.main()
