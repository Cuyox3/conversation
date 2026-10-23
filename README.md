# Conversión de voz 🎙️

Crea la voz de un usuario a partir de un audio y genera voz desde texto, con Python.

**Demo:** https://cuyox3.github.io/conversation/

## Qué hace

1. **Crea tu voz.** Sube un audio (WAV, MP3, OGG, M4A, WebM) o grábalo con el micrófono, confirma
   que tienes permiso para clonarla y Python calcula su *perfil*: tono medio y rango, expresividad,
   velocidad (sílabas/seg) y brillo del timbre, con la gráfica del tono. También revisa la
   **calidad de la muestra** (duración, ruido de fondo, saturación) y da consejos.
   También puedes **diseñar una voz** con controles, sin grabar nada.
2. **Tus voces.** Cada usuario puede crear varias voces; se guardan en su navegador.
3. **Texto a voz**, con tres motores:
   - **Navegador** (funciona directo en GitHub Pages): el perfil elige una voz base masculina o
     femenina y ajusta tono y velocidad de la Web Speech API. Es una aproximación, no un clon.
   - **XTTS-v2** (servidor): clonación neuronal en 17 idiomas, con control de velocidad y variación.
   - **Chatterbox** (servidor): clonación neuronal de Resemble AI, licencia MIT, 23 idiomas y
     **control de emoción**.
   El texto largo (hasta 5000 caracteres) se divide en oraciones.
4. **Cambiador de voz** (speech-to-speech): convierte una grabación al tono y timbre de una de tus
   voces conservando lo que dices y cómo lo dices. Corre en Python dentro del navegador.
5. **¿Lo generó una IA?** Todo el audio generado lleva una **marca de agua inaudible**; el verificador
   dice si un WAV salió de Conversión.

## Inspiración: qué hacen los servicios comerciales

| Servicio | Lo que ofrece | Lo que tomamos |
|---|---|---|
| [ElevenLabs](https://elevenlabs.io/docs) | Clonación instantánea (≈1 min de audio) y profesional; voice changer; voice design | Clonación zero-shot, cambiador de voz, diseño de voz, guía de calidad de muestra |
| [Resemble AI](https://www.resemble.ai/) / [Chatterbox](https://huggingface.co/ResembleAI/chatterbox) | Modelo abierto MIT con control de emoción; marca de agua Perth y detector | Motor Chatterbox, marca de agua y verificador propios |
| Descript, Resemble | Verificación de consentimiento antes de clonar | Declaración de consentimiento obligatoria (navegador y API) |
| Cartesia, Fish Audio, PlayHT | Clonación con 10–30 s, baja latencia, muchos idiomas | Muestras de 10–30 s; selección de idioma |

Diferencias honestas: los servicios comerciales usan modelos propios entrenados con miles de horas,
verificación de identidad más estricta y marcas de agua que resisten MP3; aquí la marca es
espectro ensanchado sencillo (resiste WAV, volumen y ruido, no recortes ni MP3) y el cambiador es
procesamiento de señal clásico, no una red neuronal.

## Cómo funciona

| Parte | Tecnología |
|---|---|
| `python/analisis_voz.py` | Perfil y calidad: tono con **YIN**, velocidad con la envolvente de energía, brillo con el centroide espectral; diseño de voces. |
| `python/cambiador_voz.py` | Cambiador: **vocoder de fase** para el tono y **cepstrum** para mover los formantes de forma independiente. |
| `python/marca_agua.py` | Marca de agua por **espectro ensanchado** (−30 dB) y detector por correlación. |
| `index.html` + `assets/` | Interfaz estática. Carga **Pyodide** (CPython en WebAssembly) y ejecuta esos módulos en el navegador: el audio no sale de tu equipo salvo que uses el servidor. |
| `server/` | API **FastAPI** con XTTS-v2 y Chatterbox, más una CLI. |
| `tests/` | Pruebas con pytest: voces sintéticas de tono conocido, cambiador, marca de agua y la API completa con un motor falso. |

GitHub Pages solo sirve archivos estáticos y no puede ejecutar modelos neuronales de varios GB,
por eso la clonación neuronal vive en el servidor opcional.

## Servidor de clonación

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
COQUI_TOS_AGREED=1 uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Para Chatterbox (en un entorno aparte si choca con las versiones de torch):
`pip install -r server/requirements-chatterbox.txt` y `CONVERSION_MOTOR=chatterbox`.

Luego, en la página, elige **XTTS-v2** o **Chatterbox** y escribe `http://localhost:8000`.
La primera petición descarga y carga el modelo (tarda unos minutos; con GPU es mucho más rápido).

Con Docker:

```bash
docker build -f server/Dockerfile -t conversion .
docker run -p 8000:8000 -v conversion-datos:/data conversion
```

Variables de entorno: `CONVERSION_ORIGENES` (orígenes CORS permitidos, separados por comas),
`CONVERSION_VOCES` (carpeta de muestras) y `CONVERSION_MOTOR` (`xtts` o `chatterbox`).

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/salud` | Estado del servidor y de los motores |
| POST | `/api/voces` | Crea una voz (`nombre`, `audio` WAV, `consentimiento=true`) y devuelve su perfil |
| GET | `/api/voces` | Lista las voces |
| GET / DELETE | `/api/voces/{id}` | Consulta o borra una voz |
| POST | `/api/voces/{id}/hablar` | Texto a voz (`texto`, `idioma`, `motor`, `velocidad`, `temperatura`, `emocion`, `fidelidad`) → WAV con marca |
| POST | `/api/voces/{id}/convertir` | Cambiador: `audio` WAV → mismo audio con esta voz |
| POST | `/api/verificar` | Detecta la marca de agua en un `audio` WAV |

### CLI

```bash
python -m server.cli analizar mi_voz.wav
python -m server.cli hablar mi_voz.wav "Hola, esta es mi voz clonada" -o salida.wav
python -m server.cli hablar mi_voz.wav "¡Qué emoción!" -m chatterbox --emocion 1.0
python -m server.cli convertir mi_voz.wav otra_grabacion.wav -o convertida.wav
python -m server.cli verificar salida.wav
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
bajo la [Coqui Public Model License](https://coqui.ai/cpml) (uso no comercial); Chatterbox es MIT.
