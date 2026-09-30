"""Página de documentos del laboratorio: tipos, muestras sintéticas y análisis."""
import pytest
from fastapi.testclient import TestClient

from mrzlab import motores
from mrzlab.app import app
from mrzlab.extractores import REGISTRO

cliente = TestClient(app)


def test_pagina_y_tipos():
    assert "OCR Doc Lab · documentos" in cliente.get("/documentos").text
    assert {t["tipo"] for t in cliente.get("/api/documentos/tipos").json()} == set(REGISTRO)


def test_muestra_digital_y_analisis():
    pdf = cliente.get("/api/documentos/muestra/seguro_rc?origen=digital&semilla=3")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    d = cliente.post("/api/documentos/analizar", data={"tipo": "seguro_rc"},
                     files={"archivo": ("p.pdf", pdf.content, "application/pdf")}).json()
    assert d["lectura"] == "COMPLETA"
    assert d["lab"]["lineas"] and d["lab"]["paginas"][0]["imagen"].startswith("data:image/jpeg;base64,")
    assert all("caja" in c for c in d["campos"].values())


def test_muestra_foto():
    if not any(m.disponible()[0] for m in motores.TODOS):
        pytest.skip("sin motores OCR")
    r = cliente.get("/api/documentos/muestra/entrega_epis?origen=foto&semilla=1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


def test_tipo_desconocido_y_formato():
    assert cliente.get("/api/documentos/muestra/pasaporte").status_code == 404
    r = cliente.post("/api/documentos/analizar", data={"tipo": "flc_60h"},
                     files={"archivo": ("x.docx", b"PK\x03\x04", "application/octet-stream")})
    assert r.status_code == 415
