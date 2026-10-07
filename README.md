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
├── data/
│   ├── raw/             Datos originales sin procesar
│   └── processed/       Datos depurados para el entrenamiento
├── docs/                Anteproyecto, entregas y memoria
├── models/              Modelos entrenados
├── notebooks/           Análisis exploratorio y prototipos
├── src/
│   ├── data/            Carga y preprocesado de datos
│   ├── models/          Entrenamiento y evaluación
│   ├── dispatch/        Lógica de despacho energético
│   └── visualization/   Visualización de resultados
├── tests/               Pruebas
├── requirements.txt
└── README.md
```

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
