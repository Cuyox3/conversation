"""Análisis de voz con NumPy.

Este módulo se ejecuta igual en el navegador (Pyodide, en GitHub Pages) y en
el servidor de clonación (FastAPI). A partir de una muestra de voz calcula un
"perfil de voz": tono, rango, velocidad al hablar y brillo del timbre, y lo
traduce a parámetros para un sintetizador de texto a voz.
"""

import io
import wave

import numpy as np

SR_ANALISIS = 16000          # frecuencia de muestreo de trabajo
MAX_SEGUNDOS = 30            # se analiza como máximo esta duración
F0_MIN, F0_MAX = 60.0, 450.0  # rango de tono humano considerado (Hz)
VENTANA_MS, SALTO_MS = 40, 10
UMBRAL_YIN = 0.15
SILABAS_REF = 5.5            # sílabas/seg de un hablante promedio en español


# ---------- utilidades de audio ----------

def a_mono(muestras):
    """Convierte (n,) o (n, canales) a un vector mono float64."""
    x = np.asarray(muestras, dtype=np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    return x


def remuestrear(x, sr_origen, sr_destino=SR_ANALISIS):
    """Remuestreo lineal sencillo (suficiente para análisis)."""
    if sr_origen == sr_destino or len(x) == 0:
        return x
    n = int(round(len(x) * sr_destino / sr_origen))
    t_origen = np.arange(len(x)) / sr_origen
    t_destino = np.arange(n) / sr_destino
    return np.interp(t_destino, t_origen, x)


def leer_wav(datos):
    """Lee bytes de un WAV PCM (8/16/32 bits) y devuelve (muestras, sr)."""
    with wave.open(io.BytesIO(datos), "rb") as w:
        sr, canales, ancho = w.getframerate(), w.getnchannels(), w.getsampwidth()
        crudo = w.readframes(w.getnframes())
    tipos = {1: np.uint8, 2: np.int16, 4: np.int32}
    if ancho not in tipos:
        raise ValueError(f"WAV de {ancho * 8} bits no soportado")
    x = np.frombuffer(crudo, dtype=tipos[ancho]).astype(np.float64)
    if ancho == 1:
        x = (x - 128.0) / 128.0
    else:
        x /= float(2 ** (8 * ancho - 1))
    return x.reshape(-1, canales), sr


def escribir_wav(x, sr):
    """Devuelve bytes de un WAV PCM de 16 bits mono."""
    x = np.clip(np.asarray(x, dtype=np.float64), -1.0, 1.0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _tramas(x, largo, salto):
    if len(x) < largo:
        x = np.pad(x, (0, largo - len(x)))
    n = 1 + (len(x) - largo) // salto
    idx = np.arange(largo)[None, :] + salto * np.arange(n)[:, None]
    return x[idx]


# ---------- estimación de tono (YIN) ----------

def tono_yin(tramas, sr):
    """Estima F0 por trama con el algoritmo YIN. Devuelve Hz (0 = sordo)."""
    largo = tramas.shape[1]
    tau_min = int(sr / F0_MAX)
    tau_max = min(int(sr / F0_MIN), largo // 2)
    w = largo - tau_max

    # Función diferencia d(tau) vía FFT para todas las tramas a la vez
    n_fft = 1 << int(np.ceil(np.log2(2 * largo)))
    espectro = np.fft.rfft(tramas, n_fft, axis=1)
    autocorr = np.fft.irfft(espectro * np.conj(espectro), n_fft, axis=1)[:, :tau_max + 1]
    energia = np.cumsum(np.pad(tramas ** 2, ((0, 0), (1, 0))), axis=1)
    e0 = energia[:, w][:, None]
    taus = np.arange(tau_max + 1)
    e_tau = energia[:, taus + w] - energia[:, taus]
    dif = e0 + e_tau - 2 * autocorr

    # Diferencia normalizada por la media acumulada
    acumulada = np.cumsum(dif[:, 1:], axis=1)
    dnorm = np.ones_like(dif)
    dnorm[:, 1:] = dif[:, 1:] * taus[1:] / np.maximum(acumulada, 1e-12)

    f0 = np.zeros(len(tramas))
    for i, d in enumerate(dnorm):
        bajo = np.where(d[tau_min:] < UMBRAL_YIN)[0]
        if len(bajo) == 0:
            continue
        t = bajo[0] + tau_min
        while t + 1 < len(d) and d[t + 1] < d[t]:
            t += 1
        # Interpolación parabólica para afinar tau
        if 0 < t < len(d) - 1:
            a, b, c = d[t - 1], d[t], d[t + 1]
            den = a - 2 * b + c
            t = t + 0.5 * (a - c) / den if den != 0 else t
        f0[i] = sr / t
    return f0


# ---------- perfil de voz ----------

def _suavizar(x, n):
    if n <= 1 or len(x) < n:
        return x
    return np.convolve(x, np.ones(n) / n, mode="same")


def analizar(muestras, sr):
    """Analiza una muestra de voz y devuelve el perfil como diccionario."""
    x = remuestrear(a_mono(muestras), sr)
    x = x[: SR_ANALISIS * MAX_SEGUNDOS]
    if len(x) < SR_ANALISIS * 0.5:
        raise ValueError("La muestra es muy corta: graba al menos 2 segundos de voz.")
    x = x - x.mean()
    pico = np.max(np.abs(x))
    if pico < 1e-4:
        raise ValueError("La muestra está en silencio.")
    saturadas = float(np.mean(np.abs(x) > 0.98))
    x = x / pico

    largo = int(SR_ANALISIS * VENTANA_MS / 1000)
    salto = int(SR_ANALISIS * SALTO_MS / 1000)
    tramas = _tramas(x, largo, salto)
    rms = np.sqrt((tramas ** 2).mean(axis=1))
    umbral_voz = max(0.02, 0.1 * np.percentile(rms, 95))
    con_voz = rms > umbral_voz

    f0 = tono_yin(tramas, SR_ANALISIS)
    f0[~con_voz] = 0
    sonoras = f0 > 0
    if sonoras.sum() < 10:
        raise ValueError("No se detectó voz clara. Intenta con una grabación con menos ruido.")
    f0v = f0[sonoras]
    # Quita saltos de octava extremos
    mediana = np.median(f0v)
    f0v = f0v[(f0v > mediana / 1.8) & (f0v < mediana * 1.8)]

    semitonos = 12 * np.log2(f0v / np.median(f0v))
    segundos_habla = con_voz.sum() * SALTO_MS / 1000

    # Velocidad: picos de la envolvente de energía ≈ núcleos silábicos
    env = _suavizar(rms, 5)
    picos = (env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > umbral_voz * 1.5)
    # Distancia mínima entre sílabas: 100 ms
    idx = np.where(picos)[0]
    if len(idx):
        idx = idx[np.concatenate(([True], np.diff(idx) >= 100 // SALTO_MS))]
    silabas_seg = len(idx) / max(segundos_habla, 0.5)

    # Brillo: centroide espectral de las tramas con voz
    ventana = np.hanning(largo)
    mag = np.abs(np.fft.rfft(tramas[con_voz] * ventana, axis=1))
    freqs = np.fft.rfftfreq(largo, 1 / SR_ANALISIS)
    centroide = float((mag * freqs).sum() / max(mag.sum(), 1e-12))

    f0_media = float(np.median(f0v))
    registro = registro_de(f0_media)

    # Contorno de tono para graficar (máx. 300 puntos)
    paso = max(1, len(f0) // 300)
    contorno = [round(float(v), 1) for v in f0[::paso]]

    perfil = {
        "f0_media": round(f0_media, 1),
        "f0_min": round(float(np.percentile(f0v, 10)), 1),
        "f0_max": round(float(np.percentile(f0v, 90)), 1),
        "expresividad": round(float(np.std(semitonos)), 2),
        "silabas_seg": round(float(silabas_seg), 2),
        "brillo_hz": round(centroide, 0),
        "registro": registro,
        "duracion_seg": round(len(x) / SR_ANALISIS, 2),
        "segundos_habla": round(segundos_habla, 2),
        "contorno": contorno,
        "contorno_ms": SALTO_MS * paso,
    }
    perfil["tts"] = parametros_tts(perfil)
    # Ruido de fondo: energía de las tramas más silenciosas frente a las de voz
    snr = 20 * np.log10(np.percentile(rms, 95) / max(np.percentile(rms, 10), 1e-6))
    perfil["calidad"] = calidad_muestra(segundos_habla, snr, saturadas)
    return perfil


def calidad_muestra(segundos_habla, snr_db, saturadas):
    """Puntuación 0–100 de la muestra y consejos para mejorarla.

    Los servicios comerciales piden lo mismo: voz clara, sin ruido ni
    saturación, y suficiente duración (ElevenLabs recomienda 1–2 minutos para
    la clonación instantánea; XTTS y Chatterbox funcionan desde ~6–10 s).
    """
    puntos, consejos = 100, []
    if segundos_habla < 6:
        puntos -= 35
        consejos.append("Graba más voz: al menos 10 segundos hablando.")
    elif segundos_habla < 10:
        puntos -= 15
        consejos.append("Con 10–30 segundos de voz el clon se parece más.")
    if snr_db < 15:
        puntos -= 35
        consejos.append("Hay mucho ruido de fondo: graba en un lugar silencioso.")
    elif snr_db < 25:
        puntos -= 15
        consejos.append("Se oye algo de ruido de fondo; acércate al micrófono.")
    if saturadas > 0.001:
        puntos -= 25
        consejos.append("El audio está saturado: baja el volumen del micrófono.")
    puntos = max(0, puntos)
    nivel = "buena" if puntos >= 80 else "aceptable" if puntos >= 50 else "baja"
    return {"puntos": puntos, "nivel": nivel, "snr_db": round(float(snr_db), 1), "consejos": consejos}


def registro_de(f0):
    if f0 < 145:
        return "grave"
    return "media" if f0 < 200 else "aguda"


def disenar(f0_media, silabas_seg=SILABAS_REF, expresividad=2.0):
    """Diseño de voz: crea un perfil a partir de parámetros, sin grabación."""
    f0 = float(np.clip(f0_media, F0_MIN, F0_MAX))
    rango = 2 ** (expresividad / 12)  # ±1 desviación típica, en semitonos
    perfil = {
        "f0_media": round(f0, 1),
        "f0_min": round(f0 / rango, 1),
        "f0_max": round(f0 * rango, 1),
        "expresividad": round(float(expresividad), 2),
        "silabas_seg": round(float(silabas_seg), 2),
        "brillo_hz": None,
        "registro": registro_de(f0),
        "disenada": True,
        "contorno": [],
        "contorno_ms": SALTO_MS,
    }
    perfil["tts"] = parametros_tts(perfil)
    return perfil


def parametros_tts(perfil):
    """Traduce el perfil a parámetros de un sintetizador (Web Speech API).

    - genero: preferencia de voz del sintetizador ("masculina"/"femenina").
    - pitch: 0.5–1.5, desplazamiento de tono respecto a la voz base.
    - rate: 0.6–1.6, velocidad relativa al habla promedio.
    """
    f0 = perfil["f0_media"]
    genero = "masculina" if f0 < 165 else "femenina"
    referencia = 120.0 if genero == "masculina" else 210.0
    semitonos = 12 * np.log2(f0 / referencia)
    pitch = float(np.clip(1 + semitonos / 12, 0.5, 1.5))
    rate = float(np.clip(perfil["silabas_seg"] / SILABAS_REF, 0.6, 1.6))
    return {"genero": genero, "pitch": round(pitch, 2), "rate": round(rate, 2)}


def analizar_wav(datos):
    """Atajo: analiza directamente los bytes de un archivo WAV."""
    x, sr = leer_wav(datos)
    return analizar(x, sr)
