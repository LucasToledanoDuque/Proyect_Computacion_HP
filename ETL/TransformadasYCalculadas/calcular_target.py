"""
Calcula las variables derivadas y el target (P_renovable_MW) a partir de las
lecturas corregidas y de los datos de enriquecimiento.

Entrada: ETL/transformado/db_meteorologica_sinDesfase.csv.gz
         DatosEnriquecimiento/clima_solar y DatosEnriquecimiento/calendario
Salida:  dataset_modelo_5min.csv.gz (en esta misma carpeta)
"""
from pathlib import Path
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
LECTURAS = RAIZ / "ETL" / "transformado" / "db_meteorologica_sinDesfase.csv.gz"
ENR = RAIZ / "DatosEnriquecimiento"
SALIDA = Path(__file__).resolve().parent / "dataset_modelo_5min.csv.gz"

# Estación más cercana al parque eólico y a la planta solar
SAN_NICOLAAS = "963fdb57-b257-472d-b56e-892b265c2524"

# Parque eólico Vader Piet: 10 turbinas de 3 MW con el buje a 80 m
N_TURBINAS = 10
ALTURA_BUJE = 80
ALTURA_MEDIDA = 10
DISPONIBILIDAD = 0.95

# Curva de potencia aproximada de una turbina de 3 MW (velocidad en m/s, potencia en kW)
CURVA_V = [0, 3.49, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 25, 25.01]
CURVA_P = [0, 0, 40, 80, 190, 350, 590, 890, 1270, 1700, 2150, 2550, 2850, 2970, 3000, 3000, 0]

# Planta solar Sunrise Solar Park
P_SOLAR_MW = 6.1
RENDIMIENTO = 0.85

# Número de filas de 5 minutos que hay en 1 hora y en 24 horas
UNA_HORA = 12
UN_DIA = 288


def potencia_eolica(viento_80m, densidad):
    # Potencia de una turbina según la curva (en kW)
    p = np.interp(viento_80m, CURVA_V, CURVA_P)
    # Con aire más denso la turbina da algo más, pero nunca más de 3000 kW
    p = np.minimum(p * densidad / 1.225, 3000)
    # Pasamos a MW y multiplicamos por las 10 turbinas
    return p / 1000 * N_TURBINAS * DISPONIBILIDAD


def main():
    print("Leyendo lecturas...")
    d = pd.read_csv(LECTURAS)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d = d.drop_duplicates(["station_id", "timestamp"])

    T = d["temperature_c"]
    HR = d["humidity_pct"]

    # Punto de rocío (fórmula de Magnus)
    g = np.log(HR / 100) + 17.62 * T / (243.12 + T)
    d["punto_rocio_c"] = (243.12 * g / (17.62 - g)).round(2)

    # Densidad del aire húmedo: parte de aire seco + parte de vapor de agua
    presion_vapor = HR / 100 * 6.112 * np.exp(17.62 * T / (243.12 + T))
    temp_kelvin = T + 273.15
    aire_seco = (d["pressure_hpa"] - presion_vapor) * 100 / (287.05 * temp_kelvin)
    vapor = presion_vapor * 100 / (461.5 * temp_kelvin)
    d["densidad_aire_kgm3"] = (aire_seco + vapor).round(4)

    # Viento separado en dirección este-oeste (u) y norte-sur (v)
    angulo = np.deg2rad(d["wind_direction_deg"])
    d["viento_u_kmh"] = (-d["wind_speed_kmh"] * np.sin(angulo)).round(2)
    d["viento_v_kmh"] = (-d["wind_speed_kmh"] * np.cos(angulo)).round(2)

    # UV de un día despejado: el percentil 95 del mismo mes, hora y minuto
    grupos = [d["timestamp"].dt.month, d["timestamp"].dt.hour, d["timestamp"].dt.minute]
    d["uv_ref"] = d.groupby(grupos)["uv_index"].transform(lambda x: x.quantile(0.95))

    # Media de las 12 estaciones en cada instante
    columnas_isla = ["temperature_c", "humidity_pct", "wind_speed_kmh", "pressure_hpa",
                     "precipitation_mm", "visibility_km", "uv_index"]
    isla = d.groupby("timestamp")[columnas_isla].mean().round(2).add_prefix("isla_")

    # Nos quedamos con San Nicolaas y le añadimos la media de la isla
    sn = d[d["station_id"] == SAN_NICOLAAS].set_index("timestamp").sort_index()
    df = sn[["temperature_c", "humidity_pct", "wind_speed_kmh", "wind_direction_deg", "pressure_hpa",
             "precipitation_mm", "visibility_km", "uv_index", "punto_rocio_c", "densidad_aire_kgm3",
             "viento_u_kmh", "viento_v_kmh", "uv_ref"]].join(isla)

    # Añadimos la posición del sol y el calendario (se cruzan por el timestamp en texto)
    fechas = df.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    sol = pd.read_csv(ENR / "clima_solar" / "aruba_solar_estaciones_5min.csv.gz")
    sol = sol[sol["station_id"] == SAN_NICOLAAS].set_index("timestamp")
    sol = sol[["solar_elevation_deg", "solar_azimuth_deg", "ghi_clearsky_wm2", "is_daylight"]]
    df = df.join(sol.reindex(fechas).set_axis(df.index))

    cal = pd.read_csv(ENR / "calendario" / "aruba_calendario_5min.csv", dtype={"festivo_nombre": str})
    cal = cal.set_index("timestamp")[["hora_local", "dia_semana", "es_fin_de_semana", "es_festivo",
                                      "es_laborable", "hora_sin", "hora_cos", "dow_sin", "dow_cos",
                                      "doy_sin", "doy_cos", "turistas_stopover_dia_medio"]]
    df = df.join(cal.reindex(fechas).set_axis(df.index))

    # Eólica: pasamos a m/s y subimos el viento de 10 a 80 m (ley potencial, exponente 0,14)
    df["viento_10m_ms"] = (df["wind_speed_kmh"] / 3.6).round(3)
    df["viento_80m_ms"] = (df["viento_10m_ms"] * (ALTURA_BUJE / ALTURA_MEDIDA) ** 0.14).round(3)
    df["P_eolica_MW"] = potencia_eolica(df["viento_80m_ms"], df["densidad_aire_kgm3"]).round(3)

    # Solar: factor de nubes = UV medido / UV de un día despejado.
    # De noche y al amanecer el UV de referencia es casi 0, así que ahí ponemos 1.
    factor = df["uv_index"] / df["uv_ref"]
    factor[df["uv_ref"] < 0.5] = 1.0
    df["factor_nubes"] = factor.clip(0, 1.1).round(3)
    df["ghi_estimada_wm2"] = (df["ghi_clearsky_wm2"] * df["factor_nubes"]).round(1)

    # Los paneles se calientan con el sol y pierden un 0,4 % por cada grado por encima de 25 °C
    temp_celula = df["temperature_c"] + df["ghi_estimada_wm2"] / 1000 * 25
    df["temp_celula_c"] = temp_celula.round(2)
    perdida_calor = 1 - 0.004 * (temp_celula - 25)
    solar = P_SOLAR_MW * df["ghi_estimada_wm2"] / 1000 * RENDIMIENTO * perdida_calor
    df["P_solar_MW"] = solar.clip(0, P_SOLAR_MW).round(3)

    # Target: generación renovable total
    df["P_renovable_MW"] = (df["P_eolica_MW"] + df["P_solar_MW"]).round(3)

    # Rellenamos los instantes que faltan con filas vacías, para que los
    # desplazamientos de 1 h y 24 h no se salten los huecos
    todas = pd.date_range(df.index.min(), df.index.max(), freq="5min")
    df = df.reindex(todas)
    df.index.name = "timestamp"
    df["hay_lectura"] = df["temperature_c"].notna().astype(int)

    # Valores del pasado, que el modelo sí puede usar
    pr = df["P_renovable_MW"]
    viento = df["wind_speed_kmh"]
    df["P_renovable_lag_1h"] = pr.shift(UNA_HORA)
    df["P_renovable_lag_24h"] = pr.shift(UN_DIA)
    df["P_renovable_media_1h"] = pr.rolling(UNA_HORA).mean().round(3)
    df["viento_media_1h_kmh"] = viento.rolling(UNA_HORA).mean().round(2)
    df["viento_std_1h_kmh"] = viento.rolling(UNA_HORA).std().round(2)
    df["viento_lag_1h_kmh"] = viento.shift(UNA_HORA)
    df["presion_tendencia_3h_hpa"] = (df["pressure_hpa"] - df["pressure_hpa"].shift(3 * UNA_HORA)).round(2)

    # Lo que queremos predecir: la generación dentro de 1 h y de 24 h
    df["target_P_renovable_t+1h"] = pr.shift(-UNA_HORA)
    df["target_P_renovable_t+24h"] = pr.shift(-UN_DIA)

    df = df.drop(columns=["uv_ref"])
    df.index = df.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    df.to_csv(SALIDA, compression="gzip")
    print("Guardado:", SALIDA, df.shape)


if __name__ == "__main__":
    main()
