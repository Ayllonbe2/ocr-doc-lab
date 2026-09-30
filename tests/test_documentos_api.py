"""API de documentos: contrato, errores, límites y privacidad (nivel A). Datos ficticios."""
import io
import json
import logging
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mrzlab import sintetico_docs as sd
from mrzlab.extractores import REGISTRO
from servicio.documentos import router

app = FastAPI()
app.include_router(router)
cliente = TestClient(app)

CLAVES = {"tipo", "lectura", "origen", "paginas", "campos", "validaciones", "clasificacion", "autenticidad",
          "calidad", "avisos", "tiempo_ms"}


def _post(tipo, datos, nombre="doc.pdf", tipo_mime="application/pdf"):
    return cliente.post(f"/v1/documentos/{tipo}/extraer", files={"archivo": (nombre, datos, tipo_mime)})


def test_tipos():
    d = cliente.get("/v1/documentos/tipos").json()
    assert {t["tipo"] for t in d["tipos"]} == set(REGISTRO)
    flc = next(t for t in d["tipos"] if t["tipo"] == "flc_60h")
    assert set(flc["obligatorios"]) <= set(flc["campos"]) and flc["grupo"] == "titulacion"


def test_extraer_contrato_de_respuesta():
    pdf, verdad = sd.generar("certificado_tgss", np.random.default_rng(1))
    r = _post("certificado_tgss", pdf)
    assert r.status_code == 200
    d = r.json()
    assert set(d) == CLAVES and d["lectura"] == "COMPLETA" and d["origen"] == "pdf_digital"
    assert d["campos"]["identificador"] == {"valor": verdad["identificador"], "origen": "capa_texto",
                                            "confianza": 1.0, "pagina": 1}
    assert d["campos"]["fecha_emision"]["valor"] == verdad["fecha_emision"].isoformat()
    assert d["clasificacion"]["coincide"] is True
    assert set(d["autenticidad"]) == {"firmas", "codigos_verificacion", "qr", "avisos"}
    # Nada de texto bruto ni imágenes en la respuesta.
    assert not any(k in d for k in ("texto", "imagen", "raw_output", "lineas"))


def test_ejemplos_publicados_coinciden_con_el_contrato():
    """docs/ejemplos/<tipo>.json: si el contrato cambia sin actualizarlos, este test falla."""
    carpeta = Path(__file__).resolve().parent.parent / "docs" / "ejemplos"
    ejemplos = sorted(carpeta.glob("*.json"))
    assert {e.stem for e in ejemplos} == set(REGISTRO)
    for e in ejemplos:
        d = json.loads(e.read_text(encoding="utf-8"))
        assert set(d) == CLAVES, e.name
        assert set(d["campos"]) <= set(REGISTRO[e.stem].campos), e.name


def test_openapi_publicado_al_dia(monkeypatch):
    """docs/openapi.json debe coincidir con el servicio (python -m herramientas.contrato)."""
    import importlib
    import sys
    monkeypatch.setenv("OCR_ALLOW_ANONYMOUS", "true")
    monkeypatch.delenv("OCR_API_KEY", raising=False)
    modulo = importlib.reload(sys.modules["servicio.app"]) if "servicio.app" in sys.modules \
        else importlib.import_module("servicio.app")
    publicado = json.loads((Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text(encoding="utf-8"))
    actual = modulo.app.openapi()
    assert publicado["paths"] == json.loads(json.dumps(actual["paths"]))


def test_tipo_desconocido():
    assert _post("pasaporte", b"%PDF-1.4").status_code == 404


def test_vacio_corrupto_y_formato():
    assert _post("flc_60h", b"").status_code == 400
    assert _post("flc_60h", b"%PDF-1.7\nroto").status_code == 400
    assert _post("flc_60h", b"PK\x03\x04docx", "doc.docx", "application/octet-stream").status_code == 415


def test_demasiado_grande():
    assert _post("flc_60h", b"%PDF" + b"0" * (15 * 1024 * 1024 + 10)).status_code == 413


def test_demasiadas_paginas():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(7):
        c.drawString(72, 700, f"página {i}")
        c.showPage()
    c.save()
    assert _post("flc_60h", buf.getvalue()).status_code == 422


def test_cifrado():
    from reportlab.lib import pdfencrypt
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, encrypt=pdfencrypt.StandardEncryption("clave", canPrint=0))
    c.drawString(72, 700, "secreto")
    c.save()
    assert _post("flc_60h", buf.getvalue()).status_code == 400


def test_sin_motores_y_documento_escaneado(monkeypatch):
    from mrzlab import ocr_documento
    monkeypatch.setattr(ocr_documento, "disponibles", lambda: [])
    pdf, _ = sd.generar("certificado_aeat", np.random.default_rng(2))
    assert _post("certificado_aeat", pdf).status_code == 200          # digital: no necesita OCR
    escaneado = sd.pdf_de_imagen(sd.a_imagen(pdf, 100))
    assert _post("certificado_aeat", escaneado).status_code == 503


def test_clasificar():
    pdf, _ = sd.generar("seguro_rc", np.random.default_rng(3))
    d = cliente.post("/v1/documentos/clasificar", files={"archivo": ("x.pdf", pdf, "application/pdf")}).json()
    assert d["tipo_detectado"] == "seguro_rc" and d["origen"] == "pdf_digital" and d["candidatos"]


def test_reconocimiento_medico_no_devuelve_datos_clinicos():
    """Dato de salud (art. 9 RGPD): solo NIF, fecha y resultado; nada del resto del texto."""
    pdf, verdad = sd.generar("reconocimiento_medico", np.random.default_rng(4))
    d = _post("reconocimiento_medico", pdf).json()
    assert set(d["campos"]) == {"nif", "fecha", "apto"} and d["campos"]["apto"]["valor"] == "APTO"
    assert "clínicas" not in json.dumps(d, ensure_ascii=False).lower()
    assert "OBSERVACIONES" not in json.dumps(d, ensure_ascii=False).upper()


def test_logs_sin_datos_del_documento(caplog):
    pdf, verdad = sd.generar("contrato_laboral", np.random.default_rng(5))
    with caplog.at_level(logging.DEBUG):
        _post("contrato_laboral", pdf)
    registro = " ".join(r.getMessage() for r in caplog.records)
    assert "contrato_laboral" in registro
    for dato in (verdad["nif_trabajador"], verdad["identificador_empresa"], verdad["nombre_trabajador"].split()[1]):
        assert dato not in registro


def test_las_subidas_no_se_escriben_en_disco():
    from starlette.formparsers import MultiPartParser
    from servicio.api import ATRIBUTO_SPOOL, MAX_BYTES
    assert getattr(MultiPartParser, ATRIBUTO_SPOOL) > MAX_BYTES


def test_app_expone_documentos_y_exige_clave(monkeypatch):
    import importlib
    import sys
    monkeypatch.setenv("OCR_API_KEY", "secreta")
    monkeypatch.delenv("OCR_ALLOW_ANONYMOUS", raising=False)
    modulo = importlib.reload(sys.modules["servicio.app"]) if "servicio.app" in sys.modules \
        else importlib.import_module("servicio.app")
    c = TestClient(modulo.app)
    assert c.get("/v1/documentos/tipos").status_code == 401
    assert c.get("/v1/documentos/tipos", headers={"X-Api-Key": "secreta"}).status_code == 200
    assert c.get("/health").json()["tipos_documento"] == len(REGISTRO)
