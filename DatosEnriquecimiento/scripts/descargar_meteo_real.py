"""
Descarga datos meteorológicos REALES de Aruba (Open-Meteo, reanálisis/histórico)
para las 12 estaciones del dataset + el parque eólico Vader Piet, y los deja
interpolados a 5 minutos para poder cruzarlos con train_aruba_lecturas.json.

Uso (desde la raíz del repo):  python DatosEnriquecimiento/scripts/descargar_meteo_real.py
Requisitos: pip install requests pandas
"""
import json, time
from pathlib import Path
import pandas as pd
import requests

BASE = Path(__file__).resolve().parent.parent   # DatosEnriquecimiento/
URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
INICIO, FIN = "2026-03-31", "2026-07-01"
VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "cloud_cover", "cloud_cover_low",
    "shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation",
    "wind_speed_10m", "wind_direction_10m", "wind_speed_80m", "wind_speed_100m",
    "wind_gusts_10m", "precipitation", "surface_pressure",
]
# El reloj del dataset se comporta como hora local de Aruba (UTC-4):
# el pico de UV está a las 12:00. Ajustar si el grupo confirma otra cosa.
DESFASE_DATASET_H = -4

puntos = json.loads((BASE / "estaciones" / "aruba_estaciones_enriquecidas.json").read_text(encoding="utf-8"))
puntos.append({"id": "VADER_PIET", "name": "Vader Piet wind farm",
               "latitude": 12.47411, "longitude": -69.89111})

frames = []
for p in puntos:
    r = requests.get(URL, params={
        "latitude": p["latitude"], "longitude": p["longitude"],
        "start_date": INICIO, "end_date": FIN,
        "hourly": ",".join(VARIABLES), "timezone": "UTC",
        "wind_speed_unit": "kmh",
    }, timeout=60)
    r.raise_for_status()
    h = pd.DataFrame(r.json()["hourly"])
    h["time"] = pd.to_datetime(h["time"], utc=True)
    h = h.set_index("time").resample("5min").interpolate("time")
    h["station_id"] = p["id"]
    # columna para cruzar con el campo 'timestamp' del dataset
    h["timestamp"] = (h.index + pd.Timedelta(hours=DESFASE_DATASET_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    frames.append(h.reset_index().rename(columns={"time": "timestamp_utc_real"}))
    print("OK", p["name"])
    time.sleep(1)

out = pd.concat(frames, ignore_index=True)
destino = BASE / "clima_solar" / "aruba_meteo_real_5min.csv"
out.to_csv(destino, index=False)
print("Guardado:", destino, len(out), "filas")
