"""Motores de clonación de voz.

- xtts:       Coqui XTTS-v2 — 17 idiomas, licencia CPML (no comercial).
- chatterbox: Resemble AI Chatterbox Multilingual — 23 idiomas, licencia MIT,
              con control de emoción (exaggeration).

Ambos clonan una voz con unos segundos de muestra (zero-shot). Como hacen los
servicios comerciales, el texto largo se divide en oraciones, cada fragmento
se sintetiza por separado y se unen con una pausa breve. Todo el audio
generado lleva la marca de agua de python/marca_agua.py.
"""

import os
import re
import threading

import numpy as np

import analisis_voz as av
import marca_agua as ma

MOTOR_POR_DEFECTO = os.environ.get("CONVERSION_MOTOR", "xtts")
MAX_FRAGMENTO = 220  # XTTS admite ~250 caracteres por fragmento en español
PAUSA_SEG = 0.25


def dividir_texto(texto, maximo=MAX_FRAGMENTO):
    """Divide en fragmentos de hasta `maximo` caracteres respetando oraciones."""
    texto = re.sub(r"\s+", " ", texto).strip()
    oraciones = re.split(r"(?<=[.!?…;:])\s+", texto)
    fragmentos, actual = [], ""
    for oracion in oraciones:
        # Oración demasiado larga: corta por comas y, si no basta, por palabras
        piezas = [oracion]
        if len(oracion) > maximo:
            piezas = []
            for parte in re.split(r"(?<=,)\s+", oracion):
                while len(parte) > maximo:
                    corte = parte.rfind(" ", 0, maximo)
                    corte = corte if corte > 0 else maximo
                    piezas.append(parte[:corte].strip())
                    parte = parte[corte:].strip()
                piezas.append(parte)
        for pieza in piezas:
            if actual and len(actual) + 1 + len(pieza) > maximo:
                fragmentos.append(actual)
                actual = pieza
            else:
                actual = f"{actual} {pieza}".strip()
    if actual:
        fragmentos.append(actual)
    return fragmentos


class MotorXTTS:
    nombre = "xtts"
    descripcion = "Coqui XTTS-v2 (CPML, no comercial)"
    idiomas = ["es", "en", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"]

    def cargar(self, dispositivo):
        from TTS.api import TTS

        self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(dispositivo)
        self.sr = self.tts.synthesizer.output_sample_rate

    def generar(self, texto, muestra, idioma, op):
        wav = self.tts.tts(
            text=texto, speaker_wav=str(muestra), language=idioma,
            speed=op["velocidad"], temperature=op["temperatura"], split_sentences=False,
        )
        return np.asarray(wav, dtype=np.float64)


class MotorChatterbox:
    nombre = "chatterbox"
    descripcion = "Resemble AI Chatterbox Multilingual (MIT)"
    idiomas = ["es", "en", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "ar", "zh", "ja", "ko", "hi",
               "da", "el", "fi", "he", "ms", "no", "sv", "sw"]

    def cargar(self, dispositivo):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self.tts = ChatterboxMultilingualTTS.from_pretrained(device=dispositivo)
        self.sr = self.tts.sr

    def generar(self, texto, muestra, idioma, op):
        wav = self.tts.generate(
            texto, language_id=idioma, audio_prompt_path=str(muestra),
            exaggeration=op["emocion"], cfg_weight=op["fidelidad"], temperature=op["temperatura"],
        )
        return wav.squeeze(0).cpu().numpy().astype(np.float64)


MOTORES = {m.nombre: m for m in (MotorXTTS, MotorChatterbox)}
OPCIONES = {
    # nombre: (por defecto, mínimo, máximo)
    "velocidad": (1.0, 0.5, 2.0),     # XTTS
    "temperatura": (0.7, 0.1, 1.5),   # ambos: variación/creatividad
    "emocion": (0.5, 0.0, 2.0),       # Chatterbox: exageración emocional
    "fidelidad": (0.5, 0.0, 1.0),     # Chatterbox: apego al ritmo de la muestra
}


def normalizar_opciones(opciones):
    op = {}
    for clave, (defecto, minimo, maximo) in OPCIONES.items():
        valor = opciones.get(clave)
        op[clave] = defecto if valor is None else float(np.clip(float(valor), minimo, maximo))
    return op


class Clonador:
    """Carga cada motor una sola vez (perezosamente) y lo reutiliza."""

    def __init__(self):
        self._cargados = {}
        self._candado = threading.Lock()

    def info(self):
        return {
            nombre: {"descripcion": m.descripcion, "idiomas": m.idiomas, "cargado": nombre in self._cargados}
            for nombre, m in MOTORES.items()
        }

    def _motor(self, nombre):
        if nombre not in MOTORES:
            raise ValueError(f"Motor desconocido: {nombre}")
        if nombre not in self._cargados:
            import torch

            motor = MOTORES[nombre]()
            motor.cargar("cuda" if torch.cuda.is_available() else "cpu")
            self._cargados[nombre] = motor
        return self._cargados[nombre]

    def sintetizar(self, texto, muestra_wav, idioma="es", motor=MOTOR_POR_DEFECTO, opciones=None):
        """Devuelve los bytes WAV de `texto` dicho con la voz de `muestra_wav`."""
        op = normalizar_opciones(opciones or {})
        with self._candado:  # los modelos no son seguros entre hilos
            m = self._motor(motor)
            if idioma not in m.idiomas:
                raise ValueError(f"{motor} no soporta el idioma {idioma}")
            pausa = np.zeros(int(m.sr * PAUSA_SEG))
            partes = []
            for fragmento in dividir_texto(texto):
                partes += [m.generar(fragmento, muestra_wav, idioma, op), pausa]
        audio = np.concatenate(partes[:-1])
        audio = 0.95 * audio / (np.max(np.abs(audio)) or 1.0)
        return av.escribir_wav(ma.insertar(audio), m.sr)
