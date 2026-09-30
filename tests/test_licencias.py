"""Ninguna dependencia del servicio con licencia GPL/AGPL (por eso no se usa PyMuPDF)."""
from importlib import metadata
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _dependencias() -> list[str]:
    nombres = []
    for linea in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linea = linea.split("#")[0].strip()
        if linea and not linea.startswith("-"):
            nombres.append(linea.split("==")[0])
    return nombres


def _licencia(nombre: str) -> str:
    try:
        meta = metadata.metadata(nombre)
    except metadata.PackageNotFoundError:
        pytest.skip(f"{nombre} no instalado")
    clasificadores = " ".join(v for k, v in meta.items() if k == "Classifier" and "License" in v)
    return f"{meta.get('License-Expression') or ''} {meta.get('License') or ''} {clasificadores}".upper()


@pytest.mark.parametrize("nombre", _dependencias())
def test_sin_licencias_copyleft(nombre):
    licencia = _licencia(nombre)
    # «LGPL» sí se admite (enlazado dinámico); GPL y AGPL, no.
    sin_lgpl = licencia.replace("LGPL", "").replace("LESSER GENERAL PUBLIC", "")
    assert "AGPL" not in licencia and "AFFERO" not in licencia, (nombre, licencia)
    assert "GPL" not in sin_lgpl and "GENERAL PUBLIC LICENSE" not in sin_lgpl, (nombre, licencia)


def test_pymupdf_no_es_dependencia():
    assert not any(n.lower() in ("pymupdf", "fitz") for n in _dependencias())
