"""Uso desde la terminal, sin navegador.

    python -m server.cli analizar mi_voz.wav
    python -m server.cli hablar mi_voz.wav "Hola, esta es mi voz clonada" -o salida.wav
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import analisis_voz as av  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Clonación de voz y texto a voz")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analizar", help="Muestra el perfil de una voz")
    a.add_argument("muestra", type=Path)

    h = sub.add_parser("hablar", help="Genera voz a partir de texto con la voz de la muestra")
    h.add_argument("muestra", type=Path)
    h.add_argument("texto")
    h.add_argument("-i", "--idioma", default="es")
    h.add_argument("-o", "--salida", type=Path, default=Path("salida.wav"))

    args = p.parse_args()
    if args.cmd == "analizar":
        perfil = av.analizar_wav(args.muestra.read_bytes())
        perfil.pop("contorno")
        print(json.dumps(perfil, indent=2, ensure_ascii=False))
    else:
        from .clonador import Clonador

        args.salida.write_bytes(Clonador().sintetizar(args.texto, args.muestra, args.idioma))
        print(f"Audio guardado en {args.salida}")


if __name__ == "__main__":
    main()
