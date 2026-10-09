import pandas as pd
import numpy as np
import os
import glob

def fusionar_y_limpiar_datos(df, columnas_clave):
    # 1. Asegurar que los espacios en blanco se traten como nulos
    df.replace(r'^\s*$', np.nan, regex=True, inplace=True)
    
    # 2. Agrupar por station_id y timestamp
    df_fusionado = df.groupby(columnas_clave, dropna=False).apply(
        lambda grupo: grupo.bfill().ffill().iloc[0], include_groups=False
    ).reset_index()
    
    # 3. Eliminar filas que sigan teniendo algún dato nulo vital tras la fusión
    df_fusionado.dropna(inplace=True)
    
    return df_fusionado

def ejecutar_etl_meteorologico():
    # Configuración de carpetas
    carpeta_entrada = 'datos_entrada'
    carpeta_salida = 'transformado'
    
    if not os.path.exists(carpeta_salida):
        os.makedirs(carpeta_salida)

    # Buscar archivos JSON en la carpeta
    archivos_json = glob.glob(os.path.join(carpeta_entrada, '*.json'))

    if not archivos_json:
        print(f"No se encontraron archivos JSON en la carpeta '{carpeta_entrada}'.")
        return

    datasets = []
    
    # 1. EXTRACT: Leer todos los JSON
    print(f"Leyendo {len(archivos_json)} archivos JSON...")
    for archivo in archivos_json:
        try:
            # Leemos el JSON (orient='records' es el formato estándar de tu imagen)
            df_temp = pd.read_json(archivo)
            
            # Normalizar columnas por seguridad
            df_temp.columns = df_temp.columns.str.lower().str.strip()
            datasets.append(df_temp)
            
        except Exception as e:
            print(f"Error al leer {archivo}: {e}")

    if not datasets:
        return

    # 2. LOAD TEMPORAL: Unir todo
    df_total = pd.concat(datasets, ignore_index=True)
    filas_originales = len(df_total)

    # 3. TRANSFORM: Limpieza inicial de duplicados idénticos
    df_total.drop_duplicates(inplace=True)

    # --- CONFIGURACIÓN DE FUSIÓN ---
    # Identificamos el mismo registro si comparten estación y fecha exacta
    columnas_identificadoras = ['station_id', 'timestamp']
    
    # Verificar que las columnas existan
    if all(col in df_total.columns for col in columnas_identificadoras):
        df_total = fusionar_y_limpiar_datos(df_total, columnas_identificadoras)
    else:
        print("Error: No se encontraron las columnas 'station_id' o 'timestamp'.")
        return

    # 4. FORMAT: Asegurar el formato ISO 8601 para la fecha (como en tu JSON original)
    if 'timestamp' in df_total.columns:
        df_total['timestamp'] = pd.to_datetime(df_total['timestamp']).dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # 5. LOAD FINAL: Guardar la base de datos de salida actualizada
    archivo_final = os.path.join(carpeta_salida, 'db_meteorologica_unificada.json')
    
    # Exportamos en formato JSON manteniendo la misma estructura
    df_total.to_json(archivo_final, orient='records', indent=4)
    
    print(f"\nProceso ETL completado con éxito:")
    print(f"- Registros originales procesados: {filas_originales}")
    print(f"- Registros finales tras actualización y eliminación de nulos: {len(df_total)}")
    print(f"- Base de datos guardada en: {archivo_final}")

if __name__ == '__main__':
    ejecutar_etl_meteorologico()