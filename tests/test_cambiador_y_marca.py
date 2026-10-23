import numpy as np
import pytest

import analisis_voz as av
import cambiador_voz as cv
import marca_agua as ma
from test_analisis_voz import SR, voz_sintetica


@pytest.mark.parametrize("origen,destino", [(120, 220), (220, 130), (150, 150)])
def test_cambiador_lleva_el_tono_al_destino(origen, destino):
    x = voz_sintetica(origen, segundos=3)
    y, sr = cv.cambiar(x, SR, factor_tono=destino / origen)
    assert len(y) == pytest.approx(len(x) * sr / SR, abs=2)
    assert av.analizar(y, sr)["f0_media"] == pytest.approx(destino, rel=0.06)


def test_factores_hacia():
    tono, formantes = cv.factores_hacia({"f0_media": 110}, {"f0_media": 220})
    assert tono == pytest.approx(2.0)
    assert 1.0 < formantes <= 1.25


def test_formantes_cambian_el_brillo():
    x = voz_sintetica(150, segundos=2)
    oscura, sr = cv.cambiar(x, SR, 1.0, 0.85)
    brillante, _ = cv.cambiar(x, SR, 1.0, 1.2)
    assert av.analizar(oscura, sr)["brillo_hz"] < av.analizar(brillante, sr)["brillo_hz"]


def test_marca_de_agua_se_detecta_tras_guardar_wav():
    x = voz_sintetica(160, segundos=4)
    marcado = ma.insertar(x)
    datos = av.escribir_wav(marcado * 0.5, SR)  # cambio de volumen + 16 bits
    leido, _ = av.leer_wav(datos)
    assert ma.detectar(leido[:, 0])["marca"]
    assert not ma.detectar(x)["marca"]


def test_marca_es_imperceptible():
    x = voz_sintetica(160, segundos=2)
    ruido = ma.insertar(x) - x
    snr = 10 * np.log10((x ** 2).sum() / (ruido ** 2).sum())
    assert snr > 25


def test_marca_con_otra_clave_no_se_detecta():
    x = ma.insertar(voz_sintetica(200, segundos=3), clave=1)
    assert not ma.detectar(x, clave=2)["marca"]


def test_calidad_de_la_muestra():
    limpia = av.analizar(voz_sintetica(150, segundos=25), SR)["calidad"]
    rng = np.random.default_rng(0)
    ruidosa = voz_sintetica(150, segundos=4) + 0.15 * rng.standard_normal(4 * SR)
    mala = av.analizar(ruidosa, SR)["calidad"]
    assert limpia["nivel"] == "buena" and not limpia["consejos"]
    assert mala["puntos"] < limpia["puntos"] and mala["consejos"]
