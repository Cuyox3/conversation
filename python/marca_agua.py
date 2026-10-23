"""Marca de agua de audio por espectro ensanchado.

Igual que el Perth Watermarker de Resemble AI o SynthID, permite reconocer
después que un audio fue generado por esta app. Se suma un ruido
pseudoaleatorio (derivado de una clave) muy por debajo del nivel de la voz;
para detectarlo se correlaciona el audio con ese mismo ruido.

Limitaciones: resiste guardar en WAV de 16 bits, cambios de volumen y algo de
ruido, pero no recortes del inicio ni recompresión fuerte (MP3 de baja tasa).
"""

import numpy as np

BLOQUE = 4096
CLAVE = 20261022
NIVEL_DB = -30.0       # potencia de la marca respecto a la del bloque
UMBRAL_Z = 6.0         # puntuación mínima para afirmar que hay marca


def _ruido(n_bloques, clave):
    rng = np.random.default_rng(clave)
    return rng.choice([-1.0, 1.0], size=(n_bloques, BLOQUE))


def insertar(x, clave=CLAVE):
    """Devuelve `x` (float, -1..1) con la marca de agua."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x) // BLOQUE
    if n == 0:
        return x.copy()
    y = x.copy()
    bloques = y[: n * BLOQUE].reshape(n, BLOQUE)
    rms = np.sqrt((bloques ** 2).mean(axis=1, keepdims=True))
    bloques += _ruido(n, clave) * rms * 10 ** (NIVEL_DB / 20)
    return np.clip(y, -1.0, 1.0)


def detectar(x, clave=CLAVE):
    """Devuelve {'marca': bool, 'puntuacion': z} para el audio `x`."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x) // BLOQUE
    if n == 0:
        return {"marca": False, "puntuacion": 0.0, "bloques": 0}
    bloques = x[: n * BLOQUE].reshape(n, BLOQUE)
    # Blanquea con la primera diferencia: atenúa la voz (graves) y no la marca
    d = np.diff(bloques, axis=1)
    p = np.diff(_ruido(n, clave), axis=1)
    norma = np.linalg.norm(d, axis=1) * np.linalg.norm(p, axis=1)
    validos = norma > 1e-9
    if not validos.any():
        return {"marca": False, "puntuacion": 0.0, "bloques": int(n)}
    r = (d * p).sum(axis=1)[validos] / norma[validos]
    # Sin marca, cada r ~ N(0, 1/L); se combinan los bloques en una puntuación z
    z = float(r.sum() * np.sqrt(d.shape[1]) / np.sqrt(len(r)))
    return {"marca": z > UMBRAL_Z, "puntuacion": round(z, 1), "bloques": int(validos.sum())}
