# Gemelo Digital de Aruba

Sistema de predicción y despacho energético basado en técnicas de Machine Learning.

Proyecto desarrollado en la asignatura Proyectos de Computación I del Grado en Ingeniería Informática de la Universidad Europea de Madrid.

## Descripción

El proyecto consiste en el desarrollo de un gemelo digital del sistema eléctrico de Aruba, entendido como un modelo virtual capaz de reproducir el comportamiento de la generación y la demanda energética de la isla. A partir de datos históricos de consumo, variables meteorológicas y producción renovable, se entrenarán modelos predictivos que servirán de base para planificar el despacho de energía y evaluar distintos escenarios de operación.

## Objetivos

1. Recopilar, depurar y estructurar los datos energéticos y meteorológicos necesarios para el estudio.
2. Desarrollar un modelo de predicción de la demanda eléctrica a corto plazo.
3. Desarrollar un modelo de estimación de la generación renovable (solar y eólica).
4. Diseñar un algoritmo de despacho que cubra la demanda priorizando las fuentes renovables.
5. Integrar los componentes anteriores en un gemelo digital que permita la simulación y visualización de escenarios.

## Estructura del repositorio

```
.
├── Datos/                               Datos originales de la asignatura
│   ├── aruba_stations.json              12 estaciones meteorológicas
│   ├── aruba_readings_20260924.json     Lecturas cada 5 min (Git LFS)
│   └── Variables.py                     Descripción de los campos
├── DatosEnriquecimiento/                Datos externos (sep 2025 – sep 2026)
│   ├── calendario/                      Festivos, fines de semana, turismo por día
│   ├── clima_solar/                     Posición solar, radiación y meteo real (Open-Meteo)
│   ├── estaciones/                      Estaciones + distancia al parque eólico
│   ├── sistema_electrico/               Plantas de WEB Aruba y demanda de referencia
│   ├── turismo/                         Turistas y cruceristas por mes
│   ├── scripts/descargar_meteo_real.py  Descarga los datos de Open-Meteo
│   └── descripcion de datos.txt
├── ETL/
│   ├── datos_entrada/                   JSON de lecturas que entran al ETL (Git LFS)
│   ├── ETLScript.py                     1. Une y limpia las lecturas
│   ├── correccion_12h_desfase.ipynb     2. Corrige el desfase de 12 h
│   ├── transformado/                    Salidas del ETL y del notebook
│   └── TransformadasYCalculadas/
│       ├── calcular_target.py           3. Variables calculadas y target
│       ├── dataset_modelo_5min.csv.gz   Dataset final para entrenar
│       └── diccionario_variables.txt    Explicación de cada columna
├── requirements.txt
└── README.md
```

### Cómo ejecutar el pipeline

Todo se puede lanzar con el botón ▶ de VS Code; las rutas son relativas a cada script.

1. `ETL/ETLScript.py` → genera `ETL/transformado/db_meteorologica_unificada.json` (no se sube al repo, 532 MB).
2. `ETL/correccion_12h_desfase.ipynb` → genera `ETL/transformado/db_meteorologica_sinDesfase.csv.gz`.
3. `ETL/TransformadasYCalculadas/calcular_target.py` → genera `dataset_modelo_5min.csv.gz`.

Los JSON se guardan con Git LFS: después de clonar, ejecutar `git lfs install` y `git lfs pull`.

## Tecnologías

El desarrollo se realiza en Python, utilizando pandas y NumPy para el tratamiento de datos, scikit-learn para el modelado y Matplotlib para la visualización de resultados. Las herramientas definitivas se concretarán a lo largo del proyecto.

## Instalación

```bash
git clone https://github.com/<organizacion>/<repositorio>.git
cd <repositorio>
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Planificación

| Hito               | Contenido                                   |
|--------------------|---------------------------------------------|
| Plan de trabajo    | Anteproyecto y cronograma                   |
| Primera entrega    | Aproximadamente el 25 % del desarrollo      |
| Segunda entrega    | Aproximadamente el 60 % del desarrollo      |
| Entrega final      | Proyecto completo y memoria                 |
| Presentación       | Defensa del proyecto en clase               |

## Equipo

- Lucas Toledano
- Franco Zimmermann
- Daniel de Abajo
- Pablo Rodríguez
- Carmen Cano

## Metodología de trabajo

La rama `main` contiene siempre una versión estable del proyecto. Cada nueva funcionalidad o corrección se desarrolla en una rama independiente (`feature/...` o `fix/...`) y se incorpora a `main` mediante pull request, que debe ser revisada por al menos otro miembro del equipo antes de su integración.

## Licencia

Proyecto de carácter académico. Consultar el archivo `LICENSE` para más información.
