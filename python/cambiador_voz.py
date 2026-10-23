"""Cambiador de voz (speech-to-speech) con NumPy.

Convierte una grabación para que suene con el tono y el timbre de otra voz,
conservando lo que se dice y cómo se dice (ritmo y entonación), como el
"voice changer" de los servicios comerciales, pero con procesamiento de señal
clásico en lugar de una red neuronal:

1. Vocoder de fase: estira el audio en el tiempo y lo remuestrea para cambiar
   el tono sin cambiar la duración.
2. Corrección de envolvente: con el cepstrum se separa la envolvente espectral
   (formantes, el "timbre") de la estructura armónica (el tono) y se aplica la
   envolvente original desplazada por el factor de formantes deseado.
"""

import numpy as np

import analisis_voz as av

N_FFT = 1024
SALTO = 256
COEF_CEPSTRUM = 40  # coeficientes que describen la envolvente
SR_TRABAJO = 22050


def _stft(x):
    ventana = np.hanning(N_FFT)
    x = np.pad(x, (N_FFT // 2, N_FFT // 2))
    n = 1 + (len(x) - N_FFT) // SALTO
    idx = np.arange(N_FFT)[None, :] + SALTO * np.arange(n)[:, None]
    return np.fft.rfft(x[idx] * ventana, axis=1)


def _istft(espectro, largo):
    ventana = np.hanning(N_FFT)
    tramas = np.fft.irfft(espectro, N_FFT, axis=1) * ventana
    total = N_FFT + SALTO * (len(tramas) - 1)
    y = np.zeros(total)
    norma = np.zeros(total)
    for i, t in enumerate(tramas):
        y[i * SALTO:i * SALTO + N_FFT] += t
        norma[i * SALTO:i * SALTO + N_FFT] += ventana ** 2
    y /= np.maximum(norma, 1e-8)
    y = y[N_FFT // 2:]
    return np.pad(y, (0, max(0, largo - len(y))))[:largo]


def estirar(x, factor):
    """Vocoder de fase: cambia la duración por `factor` sin cambiar el tono."""
    S = _stft(x)
    pasos = np.arange(0, len(S) - 1, 1 / factor)
    fase_esperada = 2 * np.pi * SALTO * np.arange(S.shape[1]) / N_FFT
    fase = np.angle(S[0])
    salida = np.empty((len(pasos), S.shape[1]), dtype=complex)
    for i, t in enumerate(pasos):
        k = int(t)
        frac = t - k
        mag = (1 - frac) * np.abs(S[k]) + frac * np.abs(S[k + 1])
        salida[i] = mag * np.exp(1j * fase)
        delta = np.angle(S[k + 1]) - np.angle(S[k]) - fase_esperada
        delta -= 2 * np.pi * np.round(delta / (2 * np.pi))
        fase = fase + fase_esperada + delta
    return _istft(salida, int(round(len(x) * factor)))


def _envolvente(espectro):
    """Envolvente espectral suave (magnitud) vía cepstrum real."""
    log_mag = np.log(np.abs(espectro) + 1e-9)
    cep = np.fft.irfft(log_mag, N_FFT, axis=1)
    cep[:, COEF_CEPSTRUM:N_FFT - COEF_CEPSTRUM] = 0
    return np.exp(np.fft.rfft(cep, N_FFT, axis=1).real)


def cambiar(x, sr, factor_tono=1.0, factor_formantes=1.0):
    """Cambia tono y formantes de `x` de forma independiente.

    factor_tono: 2.0 sube una octava, 0.5 la baja.
    factor_formantes: >1 timbre más "pequeño"/brillante, <1 más grande/oscuro.
    Devuelve (audio, sr) a SR_TRABAJO.
    """
    x = av.remuestrear(av.a_mono(x), sr, SR_TRABAJO)
    pico = np.max(np.abs(x)) or 1.0
    x = x / pico
    if abs(factor_tono - 1) > 1e-3:
        estirado = estirar(x, factor_tono)
        # Remuestrear a la duración original sube/baja el tono y los formantes
        y = np.interp(np.linspace(0, len(estirado) - 1, len(x)), np.arange(len(estirado)), estirado)
    else:
        y = x.copy()

    # Corrige formantes: envolvente original desplazada por factor_formantes
    Sx, Sy = _stft(x), _stft(y)
    n = min(len(Sx), len(Sy))
    Sx, Sy = Sx[:n], Sy[:n]
    env_x, env_y = _envolvente(Sx), _envolvente(Sy)
    bins = np.arange(Sx.shape[1])
    env_objetivo = np.array([np.interp(bins / factor_formantes, bins, e) for e in env_x])
    ganancia = np.clip(env_objetivo / np.maximum(env_y, 1e-9), 0, 10)
    y = _istft(Sy * ganancia, len(x))
    return 0.95 * y / (np.max(np.abs(y)) or 1.0), SR_TRABAJO


def factores_hacia(perfil_origen, perfil_destino):
    """Factores de tono y formantes para llevar la voz de origen a la de destino."""
    tono = perfil_destino["f0_media"] / perfil_origen["f0_media"]
    # Los formantes cambian menos que el tono entre personas (≈ raíz cuarta)
    formantes = float(np.clip(tono ** 0.25, 0.8, 1.25))
    return float(np.clip(tono, 0.4, 2.5)), formantes
