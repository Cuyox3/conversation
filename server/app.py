"""Servidor de clonación de voz (FastAPI + Coqui XTTS-v2).

GitHub Pages solo sirve archivos estáticos, así que la clonación neuronal
(que necesita un modelo de ~2 GB) vive en este servidor opcional. La página
lo usa cuando escribes su URL en «Servidor de clonación».

Arranque:
    pip install -r server/requirements.txt
    COQUI_TOS_AGREED=1 uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

import json
import os
import re
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "python"))
import analisis_voz as av  # noqa: E402

from .clonador import IDIOMAS, Clonador  # noqa: E402

DIR_VOCES = Path(os.environ.get("CONVERSION_VOCES", RAIZ / "voces"))
DIR_VOCES.mkdir(parents=True, exist_ok=True)
ORIGENES = os.environ.get(
    "CONVERSION_ORIGENES", "https://cuyox3.github.io,http://localhost:8080,http://127.0.0.1:8080"
).split(",")
MAX_BYTES = 10 * 1024 * 1024
MAX_TEXTO = 1000

app = FastAPI(title="Conversión de voz", version="1.0.0")
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


@app.get("/api/salud")
def salud():
    return {"ok": True, "modelo": clonador.nombre_modelo, "cargado": clonador.cargado, "idiomas": IDIOMAS}


@app.post("/api/voces")
async def crear_voz(nombre: str = Form(...), audio: UploadFile = File(...)):
    """Crea la voz de un usuario a partir de una muestra WAV."""
    datos = await audio.read()
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "El audio supera 10 MB")
    try:
        perfil = av.analizar_wav(datos)
    except Exception as e:  # WAV inválido o sin voz
        raise HTTPException(422, str(e))

    voz_id = uuid.uuid4().hex
    carpeta = DIR_VOCES / voz_id
    carpeta.mkdir()
    (carpeta / "muestra.wav").write_bytes(datos)
    meta = {"id": voz_id, "nombre": nombre.strip()[:60] or "Mi voz", "perfil": perfil}
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
def hablar(voz_id: str, texto: str = Form(...), idioma: str = Form("es")):
    """Genera voz a partir de texto con la voz clonada del usuario."""
    carpeta = _ruta_voz(voz_id)
    texto = texto.strip()
    if not texto:
        raise HTTPException(422, "Escribe un texto")
    if len(texto) > MAX_TEXTO:
        raise HTTPException(422, f"El texto supera {MAX_TEXTO} caracteres")
    if idioma not in IDIOMAS:
        raise HTTPException(422, f"Idioma no soportado: {idioma}")
    wav = clonador.sintetizar(texto, carpeta / "muestra.wav", idioma)
    return Response(wav, media_type="audio/wav")
