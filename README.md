# Conversión de voz 🎙️

Crea la voz de un usuario a partir de un audio y genera voz desde texto, con Python.

**Demo:** https://cuyox3.github.io/conversion/

## Qué hace

1. **Crea tu voz.** Sube un audio (WAV, MP3, OGG, M4A, WebM) o grábalo con el micrófono.
   Python analiza la muestra y guarda un *perfil de voz*: tono medio y rango, expresividad,
   velocidad al hablar (sílabas/seg) y brillo del timbre, con una gráfica del contorno de tono.
2. **Tus voces.** Cada usuario puede crear varias voces; se guardan en su navegador.
3. **Texto a voz**, con dos motores:
   - **Navegador** (funciona directo en GitHub Pages): el perfil elige una voz base masculina o
     femenina y ajusta tono y velocidad de la Web Speech API para acercarse a tu voz.
   - **Clonación neuronal** (servidor Python opcional): [Coqui XTTS-v2](https://huggingface.co/coqui/XTTS-v2)
     imita tu timbre a partir de unos segundos de muestra. Devuelve un WAV que puedes descargar.

## Cómo funciona

| Parte | Tecnología |
|---|---|
| `python/analisis_voz.py` | Análisis con NumPy: tono con el algoritmo **YIN**, velocidad con la envolvente de energía, brillo con el centroide espectral. El mismo archivo corre en el navegador y en el servidor. |
| `index.html` + `assets/` | Interfaz estática. Carga **Pyodide** (CPython compilado a WebAssembly) y ejecuta el análisis en Python dentro del navegador: el audio no sale de tu equipo. |
| `server/` | API **FastAPI** con XTTS-v2 para la clonación neuronal, más una CLI. |
| `tests/` | Pruebas con pytest (voces sintéticas de tono conocido y flujo completo de la API). |

GitHub Pages solo sirve archivos estáticos y no puede ejecutar un modelo neuronal de ~2 GB,
por eso la clonación real vive en el servidor opcional.

## Servidor de clonación

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
COQUI_TOS_AGREED=1 uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Luego, en la página, elige **Clonación neuronal** y escribe `http://localhost:8000`.
La primera petición descarga y carga el modelo (tarda unos minutos; con GPU es mucho más rápido).

Con Docker:

```bash
docker build -f server/Dockerfile -t conversion .
docker run -p 8000:8000 -v conversion-datos:/data conversion
```

Variables de entorno: `CONVERSION_ORIGENES` (orígenes CORS permitidos, separados por comas),
`CONVERSION_VOCES` (carpeta de muestras) y `CONVERSION_MODELO`.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/salud` | Estado del servidor y del modelo |
| POST | `/api/voces` | Crea una voz (`nombre`, `audio` WAV) y devuelve su perfil |
| GET | `/api/voces` | Lista las voces |
| GET / DELETE | `/api/voces/{id}` | Consulta o borra una voz |
| POST | `/api/voces/{id}/hablar` | Texto a voz con la voz clonada (`texto`, `idioma`) → WAV |

### CLI

```bash
python -m server.cli analizar mi_voz.wav
python -m server.cli hablar mi_voz.wav "Hola, esta es mi voz clonada" -o salida.wav
```

## Desarrollo

```bash
python -m http.server 8080      # abre http://localhost:8080
pip install numpy pytest fastapi python-multipart httpx && pytest
```

Cada push a `main` corre las pruebas y publica el sitio en GitHub Pages
(`.github/workflows/pages.yml`).

## Uso responsable

Clona solo tu propia voz o la de personas que te hayan dado su permiso. XTTS-v2 se distribuye
bajo la [Coqui Public Model License](https://coqui.ai/cpml) (uso no comercial).
