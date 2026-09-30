"""Entrada de documentos: PDF digital, escaneado y formularios, límites y errores."""
import io

import numpy as np
import pytest

from mrzlab import documentos, motores, ocr_documento, pdf
from mrzlab import sintetico_docs as sd


def _pdf_con(dibujar, paginas=1, **kw) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, **kw)
    for i in range(paginas):
        dibujar(c, i)
        c.showPage()
    c.save()
    return buf.getvalue()


def _hay_motores():
    if not any(m.disponible()[0] for m in motores.TODOS):
        pytest.skip("sin motores OCR en este entorno")


def test_pdf_digital_no_pasa_por_ocr(monkeypatch):
    """Un PDF con capa de texto se lee directamente: si llegara al OCR, el test fallaría."""
    def prohibido(*a, **k):
        raise AssertionError("un PDF digital no debe pasar por el OCR")
    monkeypatch.setattr(ocr_documento, "leer", prohibido)
    datos, verdad = sd.generar("certificado_tgss", np.random.default_rng(1))
    doc = documentos.leer(datos)
    assert doc.origen == "pdf_digital"
    assert verdad["identificador"] in doc.texto_norm


def test_campo_en_pagina_2_se_encuentra():
    datos, verdad = sd.generar("contrato_laboral", np.random.default_rng(2))
    r = documentos.procesar(datos, "contrato_laboral")
    assert r.campos["fecha_inicio"].valor == verdad["fecha_inicio"]
    assert r.campos["fecha_inicio"].pagina == 2


def test_cajas_en_fraccion_de_la_pagina():
    datos, _ = sd.generar("registro_empresa", np.random.default_rng(3))
    doc = documentos.leer(datos)
    for ln in doc.lineas:
        x, y, w, h = ln.caja
        assert 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1


def test_valores_de_formulario_sin_aplanar_se_leen():
    """Un formulario rellenado en el propio PDF guarda los valores en anotaciones, no en el texto."""
    def dibujar(c, _):
        c.drawString(72, 760, "CIF/NIF/NIE")
        c.acroForm.textfield(name="cif", value="B12345674", x=72, y=720, width=200, height=20)
        c.drawString(72, 680, "Texto suficiente para que la página cuente como digital y no escaneada.")
    doc = documentos.leer(_pdf_con(dibujar))
    formulario = [ln for ln in doc.lineas if ln.origen == "formulario"]
    assert [ln.texto for ln in formulario] == ["B12345674"]
    assert formulario[0].caja[1] > [ln for ln in doc.lineas if "CIF/NIF" in ln.texto][0].caja[1]


def test_pdf_escaneado_se_detecta_y_pasa_por_ocr():
    _hay_motores()
    datos, _ = sd.generar("certificado_aeat", np.random.default_rng(4))
    escaneado = sd.escanear(datos, np.random.default_rng(4))
    assert pdf.lineas_capa_texto(pdf.abrir(escaneado), 0, 1) == []
    doc = documentos.leer(escaneado)
    assert doc.origen == "pdf_escaneado"
    assert doc.paginas[0].motor and doc.paginas[0].calidad["veredicto"] in ("apta", "riesgo", "rechazar")


def test_pdf_mixto_digital_y_escaneado():
    _hay_motores()
    rng = np.random.default_rng(5)
    digital, _ = sd.generar("seguro_rc", rng)
    escaneado = sd.escanear(digital, rng)
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    w.add_page(PdfReader(io.BytesIO(digital)).pages[0])
    w.add_page(PdfReader(io.BytesIO(escaneado)).pages[0])
    buf = io.BytesIO()
    w.write(buf)
    doc = documentos.leer(buf.getvalue())
    assert doc.origen == "pdf_mixto" and [p.tipo for p in doc.paginas] == ["digital", "escaneada"]


def test_pdf_cifrado_con_contraseña():
    from reportlab.lib import pdfencrypt
    datos = _pdf_con(lambda c, _: c.drawString(72, 700, "secreto"),
                     encrypt=pdfencrypt.StandardEncryption("clave", canPrint=0))
    with pytest.raises(documentos.DocumentoInvalido) as e:
        documentos.leer(datos)
    assert e.value.motivo == "cifrado"


def test_pdf_corrupto():
    with pytest.raises(documentos.DocumentoInvalido) as e:
        documentos.leer(b"%PDF-1.7\nesto no es un pdf")
    assert e.value.motivo == "corrupto"


def test_demasiadas_paginas():
    datos = _pdf_con(lambda c, i: c.drawString(72, 700, f"página {i}"), paginas=6)
    with pytest.raises(documentos.DocumentoInvalido) as e:
        documentos.leer(datos, max_paginas=5)
    assert e.value.motivo == "demasiadas_paginas"


def test_formato_no_admitido_y_vacio():
    with pytest.raises(documentos.DocumentoInvalido) as e:
        documentos.leer(b"PK\x03\x04 un docx")
    assert e.value.motivo == "formato"
    with pytest.raises(documentos.DocumentoInvalido) as e:
        documentos.leer(b"")
    assert e.value.motivo == "vacio"


def test_modelos_largos_admiten_mas_paginas():
    """El contrato oficial trae 20 páginas de instrucciones: su tipo admite más que el resto."""
    from mrzlab.extractores import REGISTRO
    assert REGISTRO["contrato_laboral"].max_paginas >= 20
    assert documentos.max_paginas_admitidas() >= 20


def test_revisiones_de_un_pdf_linealizado():
    # Un PDF «linealizado» lleva dos %%EOF de fábrica: no es una modificación posterior.
    lineal = b"%PDF-1.5\n1 0 obj<</Linearized 1>>endobj\n%%EOF\nresto\n%%EOF\n"
    assert pdf.metadatos(type("P", (), {"metadata": {}})(), lineal)["revisiones"] == 1
    editado = b"%PDF-1.5\n%%EOF\nanadido\n%%EOF\n"
    assert pdf.metadatos(type("P", (), {"metadata": {}})(), editado)["revisiones"] == 2
