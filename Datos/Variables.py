# Fichero que va a leer los .json

"""Definición de variables, aruba_station:

        Valores que utilizan:
            "id": string,
            "name": string,
            "code": string,
            "latitude": float,
            "longitude": float,
            "elevation_m": int,
            "district": string,
            "is_active": boolean

        Que representan:
            "id": Valor unico que representa la muestra,
            "name": Nombre de la estación,
            "code": código de la estación,
            "latitude": coordenadas en el y de la estación,
            "longitude": coordenadas en el eje x de la estación,
            "elevation_m": coordenadas en el eje z de la estación,
            "district": zona en la que se encuentra,
            "is_active": valor que representa si la estación esta activa
            
"""
"""Definición de variables, train_aruba_lecturas:

        Valores que utilizan:
        "id": string,
        "station_id": string,
        "timestamp": string,
        "temperature_c": float,
        "humidity_pct": float,
        "wind_speed_kmh": float,
        "wind_direction_deg": float,
        "pressure_hpa": float,
        "precipitation_mm": float,
        "visibility_km": float,
        "uv_index": float

        Que representan:
        "id": identificador único de la lectura,
        "station_id": identificador único de la estación a la que pertenece la lectura,
        "timestamp": cuando se ha realizado la lectura,
        "temperature_c": temperatura registrada,
        "humidity_pct": humedad registrada,
        "wind_speed_kmh": velocidad de viento registrada,
        "wind_direction_deg": direccion del viento,
        "pressure_hpa": presión registrada,
        "precipitation_mm": precipitación atmosférica registrada,
        "visibility_km": km visbles en el momento de la toma de información,
        "uv_index": radiación ultravioleta registrada en la toma de información
"""