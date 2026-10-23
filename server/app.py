"""Servidor de clonación de voz (FastAPI + XTTS-v2 / Chatterbox).

GitHub Pages solo sirve archivos estáticos, así que la clonación neuronal
(modelos de varios GB) vive en este servidor opcional. La página lo usa
cuando escribes su URL en «Servidor de clonación».

Arranque:
    pip install -r server/requirements.txt
    COQUI_TOS_AGREED=1 uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "python"))
import analisis_voz as av  # noqa: E402
import cambiador_voz as cv  # noqa: E402
import marca_agua as ma  # noqa: E402

from .clonador import MOTOR_POR_DEFECTO, MOTORES, Clonador  # noqa: E402

DIR_VOCES = Path(os.environ.get("CONVERSION_VOCES", RAIZ / "voces"))
DIR_VOCES.mkdir(parents=True, exist_ok=True)
ORIGENES = os.environ.get(
    "CONVERSION_ORIGENES", "https://cuyox3.github.io,http://localhost:8080,http://127.0.0.1:8080"
).split(",")
MAX_BYTES = 10 * 1024 * 1024
MAX_TEXTO = 5000

app = FastAPI(title="Conversión de voz", version="2.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=ORIGENES, allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"]
)
clonador = Clonador()


def _ruta_voz(voz_id):
    if not re.fullmatch(r"[a-f0-9]{32}", voz_id):
        raise HTTPException(404, "Voz no encontrada")
    carpeta = DIR_VOCES / voz_id
    if not carpeta.is_dir():
        raise HTTPException(404, "Voz no encontrada")
    return carpeta


def _leer_meta(carpeta):
    return json.loads((carpeta / "perfil.json").read_text(encoding="utf-8"))


async def _leer_wav(audio):
    datos = await audio.read()
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "El audio supera 10 MB")
    try:
        x, sr = av.leer_wav(datos)
    except Exception:
        raise HTTPException(422, "Envía un archivo WAV PCM")
    return datos, x[:, 0] if x.shape[1] == 1 else x.mean(axis=1), sr


@app.get("/api/salud")
def salud():
    return {"ok": True, "motor_por_defecto": MOTOR_POR_DEFECTO, "motores": clonador.info()}


@app.post("/api/voces")
async def crear_voz(
    nombre: str = Form(...), audio: UploadFile = File(...), consentimiento: bool = Form(False)
):
    """Crea la voz de un usuario a partir de una muestra WAV."""
    if not consentimiento:
        raise HTTPException(403, "Confirma que la voz es tuya o que tienes permiso de su dueño")
    datos, x, sr = await _leer_wav(audio)
    try:
        perfil = av.analizar(x, sr)
    except ValueError as e:
        raise HTTPException(422, str(e))

    voz_id = uuid.uuid4().hex
    carpeta = DIR_VOCES / voz_id
    carpeta.mkdir()
    (carpeta / "muestra.wav").write_bytes(datos)
    meta = {
        "id": voz_id,
        "nombre": nombre.strip()[:60] or "Mi voz",
        "consentimiento": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "perfil": perfil,
    }
    (carpeta / "perfil.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


@app.get("/api/voces")
def listar_voces():
    return [
        {k: v for k, v in _leer_meta(c).items() if k != "perfil"}
        for c in sorted(DIR_VOCES.iterdir())
        if (c / "perfil.json").exists()
    ]


@app.get("/api/voces/{voz_id}")
def obtener_voz(voz_id: str):
    return _leer_meta(_ruta_voz(voz_id))


@app.delete("/api/voces/{voz_id}")
def borrar_voz(voz_id: str):
    carpeta = _ruta_voz(voz_id)
    for f in carpeta.iterdir():
        f.unlink()
    carpeta.rmdir()
    return {"ok": True}


@app.post("/api/voces/{voz_id}/hablar")
def hablar(
    voz_id: str,
    texto: str = Form(...),
    idioma: str = Form("es"),
    motor: str = Form(MOTOR_POR_DEFECTO),
    velocidad: float = Form(None),
    temperatura: float = Form(None),
    emocion: float = Form(None),
    fidelidad: float = Form(None),
):
    """Texto a voz con la voz clonada del usuario (marca de agua incluida)."""
    carpeta = _ruta_voz(voz_id)
    texto = texto.strip()
    if not texto:
        raise HTTPException(422, "Escribe un texto")
    if len(texto) > MAX_TEXTO:
        raise HTTPException(422, f"El texto supera {MAX_TEXTO} caracteres")
    if motor not in MOTORES:
        raise HTTPException(422, f"Motor desconocido: {motor}")
    if idioma not in MOTORES[motor].idiomas:
        raise HTTPException(422, f"{motor} no soporta el idioma {idioma}")
    opciones = {"velocidad": velocidad, "temperatura": temperatura, "emocion": emocion, "fidelidad": fidelidad}
    wav = clonador.sintetizar(texto, carpeta / "muestra.wav", idioma, motor, opciones)
    return Response(wav, media_type="audio/wav")


@app.post("/api/voces/{voz_id}/convertir")
async def convertir(voz_id: str, audio: UploadFile = File(...)):
    """Cambiador de voz: dice lo mismo que `audio` con el tono y timbre de la voz."""
    destino = _leer_meta(_ruta_voz(voz_id))["perfil"]
    _, x, sr = await _leer_wav(audio)
    try:
        origen = av.analizar(x, sr)
    except ValueError as e:
        raise HTTPException(422, str(e))
    tono, formantes = cv.factores_hacia(origen, destino)
    y, sr_y = cv.cambiar(x, sr, tono, formantes)
    return Response(av.escribir_wav(ma.insertar(y), sr_y), media_type="audio/wav")


@app.post("/api/verificar")
async def verificar(audio: UploadFile = File(...)):
    """Detecta si un audio WAV lleva la marca de agua de esta app."""
    _, x, _ = await _leer_wav(audio)
    return ma.detectar(x)
