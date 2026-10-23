import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import analisis_voz as av  # noqa: E402

SR = 22050


def voz_sintetica(f0, segundos=3.0, silabas_seg=5.0, sr=SR):
    """Tren de pulsos glotales con armónicos, modulado en sílabas."""
    t = np.arange(int(segundos * sr)) / sr
    vibrato = 1 + 0.02 * np.sin(2 * np.pi * 3 * t)
    fase = 2 * np.pi * np.cumsum(f0 * vibrato) / sr
    x = sum(np.sin(k * fase) / k for k in range(1, 12))
    envolvente = np.clip(np.sin(np.pi * silabas_seg * t), 0, None) ** 2
    return 0.5 * x * envolvente


@pytest.mark.parametrize("f0", [100, 150, 220, 300])
def test_detecta_tono(f0):
    perfil = av.analizar(voz_sintetica(f0), SR)
    assert perfil["f0_media"] == pytest.approx(f0, rel=0.05)


def test_registro_y_genero():
    grave = av.analizar(voz_sintetica(100), SR)
    aguda = av.analizar(voz_sintetica(240), SR)
    assert grave["registro"] == "grave" and grave["tts"]["genero"] == "masculina"
    assert aguda["registro"] == "aguda" and aguda["tts"]["genero"] == "femenina"


def test_velocidad():
    lenta = av.analizar(voz_sintetica(150, segundos=4, silabas_seg=3), SR)
    rapida = av.analizar(voz_sintetica(150, segundos=4, silabas_seg=7), SR)
    assert lenta["silabas_seg"] < rapida["silabas_seg"]
    assert lenta["tts"]["rate"] < rapida["tts"]["rate"]


def test_wav_ida_y_vuelta():
    datos = av.escribir_wav(voz_sintetica(180), SR)
    perfil = av.analizar_wav(datos)
    assert perfil["f0_media"] == pytest.approx(180, rel=0.05)
    assert 0.5 <= perfil["tts"]["pitch"] <= 1.5


def test_errores():
    with pytest.raises(ValueError, match="corta"):
        av.analizar(np.zeros(1000), SR)
    with pytest.raises(ValueError, match="silencio"):
        av.analizar(np.zeros(SR * 3), SR)


def test_disenar_voz():
    perfil = av.disenar(230, silabas_seg=7)
    assert perfil["registro"] == "aguda" and perfil["disenada"]
    assert perfil["f0_min"] < 230 < perfil["f0_max"]
    assert perfil["tts"]["genero"] == "femenina" and perfil["tts"]["rate"] > 1
    assert av.disenar(20)["f0_media"] == av.F0_MIN
