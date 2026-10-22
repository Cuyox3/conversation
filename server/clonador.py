"""Envoltura de Coqui XTTS-v2: clona una voz con unos segundos de muestra."""

import os
import tempfile
import threading
from pathlib import Path

IDIOMAS = ["es", "en", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"]
MODELO = os.environ.get("CONVERSION_MODELO", "tts_models/multilingual/multi-dataset/xtts_v2")


class Clonador:
    """Carga el modelo una sola vez (perezosamente) y lo reutiliza."""

    def __init__(self, nombre_modelo=MODELO):
        self.nombre_modelo = nombre_modelo
        self._tts = None
        self._candado = threading.Lock()

    @property
    def cargado(self):
        return self._tts is not None

    def _modelo(self):
        with self._candado:
            if self._tts is None:
                import torch
                from TTS.api import TTS

                dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
                self._tts = TTS(self.nombre_modelo).to(dispositivo)
            return self._tts

    def sintetizar(self, texto, muestra_wav, idioma="es"):
        """Devuelve los bytes WAV de `texto` dicho con la voz de `muestra_wav`."""
        tts = self._modelo()
        with tempfile.TemporaryDirectory() as tmp:
            salida = Path(tmp) / "salida.wav"
            with self._candado:  # el modelo no es seguro entre hilos
                tts.tts_to_file(text=texto, speaker_wav=str(muestra_wav), language=idioma, file_path=str(salida))
            return salida.read_bytes()
