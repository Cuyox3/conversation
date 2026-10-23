"""Uso desde la terminal, sin navegador.

    python -m server.cli analizar mi_voz.wav
    python -m server.cli hablar mi_voz.wav "Hola, esta es mi voz clonada" -o salida.wav
    python -m server.cli hablar mi_voz.wav "¡Qué emoción!" -m chatterbox --emocion 1.0
    python -m server.cli convertir mi_voz.wav otra_grabacion.wav -o convertida.wav
    python -m server.cli verificar salida.wav
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import analisis_voz as av  # noqa: E402
import cambiador_voz as cv  # noqa: E402
import marca_agua as ma  # noqa: E402


def _leer(ruta):
    x, sr = av.leer_wav(ruta.read_bytes())
    return x.mean(axis=1), sr


def main():
    p = argparse.ArgumentParser(description="Clonación de voz y texto a voz")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analizar", help="Muestra el perfil y la calidad de una voz")
    a.add_argument("muestra", type=Path)

    h = sub.add_parser("hablar", help="Genera voz a partir de texto con la voz de la muestra")
    h.add_argument("muestra", type=Path)
    h.add_argument("texto")
    h.add_argument("-i", "--idioma", default="es")
    h.add_argument("-m", "--motor", default="xtts", choices=["xtts", "chatterbox"])
    h.add_argument("--velocidad", type=float)
    h.add_argument("--temperatura", type=float)
    h.add_argument("--emocion", type=float)
    h.add_argument("--fidelidad", type=float)
    h.add_argument("-o", "--salida", type=Path, default=Path("salida.wav"))

    c = sub.add_parser("convertir", help="Cambia una grabación a la voz de la muestra")
    c.add_argument("muestra", type=Path)
    c.add_argument("fuente", type=Path)
    c.add_argument("-o", "--salida", type=Path, default=Path("convertida.wav"))

    v = sub.add_parser("verificar", help="Detecta la marca de agua de Conversión")
    v.add_argument("audio", type=Path)

    args = p.parse_args()
    if args.cmd == "analizar":
        perfil = av.analizar(*_leer(args.muestra))
        perfil.pop("contorno")
        print(json.dumps(perfil, indent=2, ensure_ascii=False))
    elif args.cmd == "hablar":
        from .clonador import Clonador

        opciones = {k: getattr(args, k) for k in ("velocidad", "temperatura", "emocion", "fidelidad")}
        wav = Clonador().sintetizar(args.texto, args.muestra, args.idioma, args.motor, opciones)
        args.salida.write_bytes(wav)
        print(f"Audio guardado en {args.salida}")
    elif args.cmd == "convertir":
        destino = av.analizar(*_leer(args.muestra))
        x, sr = _leer(args.fuente)
        tono, formantes = cv.factores_hacia(av.analizar(x, sr), destino)
        y, sr_y = cv.cambiar(x, sr, tono, formantes)
        args.salida.write_bytes(av.escribir_wav(ma.insertar(y), sr_y))
        print(f"Tono ×{tono:.2f}, formantes ×{formantes:.2f}. Audio guardado en {args.salida}")
    else:
        r = ma.detectar(_leer(args.audio)[0])
        print(("Lleva" if r["marca"] else "No lleva") + f" la marca de Conversión (puntuación {r['puntuacion']})")


if __name__ == "__main__":
    main()
