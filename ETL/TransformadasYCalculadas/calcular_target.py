"""
Calcula variables derivadas y el target P_renovable_MW del Gemelo Digital de Aruba.

Entrada:
  - ETL/transformado/db_meteorologica_sinDesfase.csv.gz        (lecturas cada 5 min, salida del notebook)
  - DatosEnriquecimiento/clima_solar/aruba_solar_estaciones_5min.csv.gz
  - DatosEnriquecimiento/calendario/aruba_calendario_5min.csv
Salida:
  - ETL/TransformadasYCalculadas/dataset_modelo_5min.csv.gz

Uso: botón ▶ de VS Code, o desde la raíz del repo:
  python ETL/TransformadasYCalculadas/calcular_target.py [ruta_lecturas] [carpeta_DatosEnriquecimiento]
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
LECTURAS = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "ETL" / "transformado" / "db_meteorologica_sinDesfase.csv.gz"
ENR = Path(sys.argv[2]) if len(sys.argv) > 2 else RAIZ / "DatosEnriquecimiento"
SALIDA = Path(__file__).resolve().parent / "dataset_modelo_5min.csv.gz"

# ---------------------------------------------------------------- constantes
ST_SAN_NICOLAAS = "963fdb57-b257-472d-b56e-892b265c2524"   # estación más cercana a Vader Piet y a Sunrise Solar Park

# Eólica: Vader Piet (10 turbinas de 3 MW, buje a 80 m)
N_TURBINAS, P_NOMINAL_MW, ALTURA_BUJE, ALTURA_MEDIDA = 10, 3.0, 80, 10
ALFA_CIZALLA = 0.14            # exponente de la ley potencial del perfil de viento
DISPONIBILIDAD = 0.95
RHO_REF = 1.225                # densidad del aire de la curva de potencia (kg/m3)
# Curva de potencia aproximada de una turbina de 3 MW tipo V90 (valores orientativos, kW)
CURVA_V = [0, 3.49, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 25, 25.01]
CURVA_P = [0, 0, 40, 80, 190, 350, 590, 890, 1270, 1700, 2150, 2550, 2850, 2970, 3000, 3000, 0]

# Solar: Sunrise Solar Park
P_SOLAR_MW = 6.1
PR = 0.85                      # performance ratio (inversor, cableado, suciedad)
COEF_TEMP = -0.004             # pérdida por cada °C de célula por encima de 25 °C
NOCT_DELTA = 25                # célula ~25 °C más caliente que el aire con 1000 W/m2

H1, H24 = 12, 288              # pasos de 5 min en 1 h y 24 h


def potencia_eolica(v80_ms, rho):
    p_kw = np.interp(v80_ms, CURVA_V, CURVA_P, left=0, right=0)
    p_kw = np.minimum(p_kw * rho / RHO_REF, 3000)   # corrección por densidad del aire
    return p_kw / 1000 * N_TURBINAS * DISPONIBILIDAD


def main():
    print("Leyendo lecturas...")
    d = pd.read_csv(LECTURAS)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d = d.drop_duplicates(["station_id", "timestamp"])

    # ---------------- variables derivadas por lectura (todas las estaciones)
    T, HR = d["temperature_c"], d["humidity_pct"]
    a, b = 17.62, 243.12
    gamma = np.log(HR / 100) + a * T / (b + T)
    d["punto_rocio_c"] = (b * gamma / (a - gamma)).round(2)
    e = HR / 100 * 6.112 * np.exp(a * T / (b + T))                     # presión de vapor (hPa)
    d["densidad_aire_kgm3"] = ((d["pressure_hpa"] - e) * 100 / (287.05 * (T + 273.15))
                               + e * 100 / (461.5 * (T + 273.15))).round(4)
    rad = np.deg2rad(d["wind_direction_deg"])
    d["viento_u_kmh"] = (-d["wind_speed_kmh"] * np.sin(rad)).round(2)  # componente este-oeste
    d["viento_v_kmh"] = (-d["wind_speed_kmh"] * np.cos(rad)).round(2)  # componente norte-sur

    # referencia de UV con cielo despejado: percentil 95 por mes y hora-minuto
    clave = [d["timestamp"].dt.month, d["timestamp"].dt.hour, d["timestamp"].dt.minute]
    d["uv_ref"] = d.groupby(clave)["uv_index"].transform(lambda s: s.quantile(0.95))

    # ---------------- media de la isla (12 estaciones)
    cols_isla = ["temperature_c", "humidity_pct", "wind_speed_kmh", "pressure_hpa",
                 "precipitation_mm", "visibility_km", "uv_index"]
    isla = d.groupby("timestamp")[cols_isla].mean().round(2).add_prefix("isla_")

    # ---------------- estación de referencia (San Nicolaas)
    sn = d[d["station_id"] == ST_SAN_NICOLAAS].set_index("timestamp").sort_index()
    df = sn[["temperature_c", "humidity_pct", "wind_speed_kmh", "wind_direction_deg", "pressure_hpa",
             "precipitation_mm", "visibility_km", "uv_index", "punto_rocio_c", "densidad_aire_kgm3",
             "viento_u_kmh", "viento_v_kmh", "uv_ref"]].join(isla)

    # ---------------- solar y calendario
    key = df.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    sol = pd.read_csv(ENR / "clima_solar" / "aruba_solar_estaciones_5min.csv.gz")
    sol = sol[sol["station_id"] == ST_SAN_NICOLAAS].set_index("timestamp")
    df = df.join(sol[["solar_elevation_deg", "solar_azimuth_deg", "ghi_clearsky_wm2", "is_daylight"]]
                 .reindex(key).set_axis(df.index))
    cal = pd.read_csv(ENR / "calendario" / "aruba_calendario_5min.csv", dtype={"festivo_nombre": str})
    cal = cal.set_index("timestamp")[["hora_local", "dia_semana", "es_fin_de_semana", "es_festivo",
                                      "es_laborable", "hora_sin", "hora_cos", "dow_sin", "dow_cos",
                                      "doy_sin", "doy_cos", "turistas_stopover_dia_medio"]]
    df = df.join(cal.reindex(key).set_axis(df.index))

    # ---------------- EÓLICA
    df["viento_10m_ms"] = (df["wind_speed_kmh"] / 3.6).round(3)
    df["viento_80m_ms"] = (df["viento_10m_ms"] * (ALTURA_BUJE / ALTURA_MEDIDA) ** ALFA_CIZALLA).round(3)
    df["P_eolica_MW"] = potencia_eolica(df["viento_80m_ms"], df["densidad_aire_kgm3"]).round(3)

    # ---------------- SOLAR
    k = np.where(df["uv_ref"] >= 0.5, df["uv_index"] / df["uv_ref"].where(df["uv_ref"] >= 0.5), 1.0)
    df["factor_nubes"] = np.clip(k, 0, 1.1).round(3)
    df["ghi_estimada_wm2"] = (df["ghi_clearsky_wm2"] * df["factor_nubes"]).round(1)
    t_celula = df["temperature_c"] + df["ghi_estimada_wm2"] / 1000 * NOCT_DELTA
    df["temp_celula_c"] = t_celula.round(2)
    f_temp = 1 + COEF_TEMP * (t_celula - 25)
    df["P_solar_MW"] = np.clip(P_SOLAR_MW * df["ghi_estimada_wm2"] / 1000 * PR * f_temp, 0, P_SOLAR_MW).round(3)

    # ---------------- TARGET
    df["P_renovable_MW"] = (df["P_eolica_MW"] + df["P_solar_MW"]).round(3)

    # rejilla completa de 5 min para que los desplazamientos respeten los huecos
    rejilla = pd.date_range(df.index.min(), df.index.max(), freq="5min")
    df = df.reindex(rejilla)
    df.index.name = "timestamp"
    df["hay_lectura"] = df["temperature_c"].notna().astype(int)

    # lags e históricos (solo información del pasado)
    pr = df["P_renovable_MW"]
    df["P_renovable_lag_1h"] = pr.shift(H1)
    df["P_renovable_lag_24h"] = pr.shift(H24)
    df["P_renovable_media_1h"] = pr.rolling(H1, min_periods=H1).mean().round(3)
    df["viento_media_1h_kmh"] = df["wind_speed_kmh"].rolling(H1, min_periods=H1).mean().round(2)
    df["viento_std_1h_kmh"] = df["wind_speed_kmh"].rolling(H1, min_periods=H1).std().round(2)
    df["viento_lag_1h_kmh"] = df["wind_speed_kmh"].shift(H1)
    df["presion_tendencia_3h_hpa"] = (df["pressure_hpa"] - df["pressure_hpa"].shift(3 * H1)).round(2)

    # targets a futuro
    df["target_P_renovable_t+1h"] = pr.shift(-H1)
    df["target_P_renovable_t+24h"] = pr.shift(-H24)

    df = df.drop(columns=["uv_ref"])
    df.index = df.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SALIDA, compression={"method": "gzip", "compresslevel": 9})
    print("Guardado:", SALIDA, df.shape)


if __name__ == "__main__":
    main()
