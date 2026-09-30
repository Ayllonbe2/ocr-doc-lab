"""Regenera el contrato publicado del servicio: `docs/openapi.json` y un ejemplo de respuesta por
tipo de documento en `docs/ejemplos/<tipo>.json` (con documentos sintéticos, datos ficticios).

    python -m herramientas.contrato

Los tests comparan estos ficheros con el servicio: si el contrato cambia, hay que regenerarlos
(y avisar a quien llama).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent


def main() -> None:
    os.environ.setdefault("OCR_ALLOW_ANONYMOUS", "true")
    from mrzlab import documentos
    from mrzlab import sintetico_docs as sd
    from servicio.app import app

    (RAIZ / "docs" / "openapi.json").write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    carpeta = RAIZ / "docs" / "ejemplos"
    carpeta.mkdir(parents=True, exist_ok=True)
    for tipo in sd.PLANTILLAS:
        pdf, _ = sd.generar(tipo, np.random.default_rng(2024))
        d = documentos.procesar(pdf, tipo).a_dict()
        d["tiempo_ms"] = 0                         # estable entre ejecuciones
        (carpeta / f"{tipo}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("escrito", tipo)


if __name__ == "__main__":
    main()
