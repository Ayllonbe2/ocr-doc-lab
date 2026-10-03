"""Cada tipo de documento de punta a punta con documentos sintéticos (niveles D y E).

- D: PDF digital. Rápido: siempre.
- E: el mismo documento escaneado y fotografiado, con OCR real. Lento: marca `ocr`
  (`pytest -m "not ocr"` para saltarlo).

La regla que no se puede romper: ningún campo con un valor distinto del real en un documento
que se da por COMPLETO.
"""
from datetime import date

import numpy as np
import pytest

from mrzlab import documentos, motores
from mrzlab import sintetico_docs as sd
from mrzlab.extractores import REGISTRO
from mrzlab.validadores import sin_acentos

TIPOS = list(REGISTRO)


def _norm(v):
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        return " ".join(sin_acentos(v).split())
    return v


def _comparar(r, verdad):
    """(campos que faltan, campos erróneos)."""
    faltan, mal = [], []
    for campo, esperado in verdad.items():
        if esperado is None:
            continue
        c = r.campos.get(campo)
        if c is None:
            faltan.append(campo)
        elif _norm(c.valor) != _norm(esperado):
            mal.append((campo, c.valor, esperado))
    return faltan, mal


@pytest.mark.parametrize("tipo", TIPOS)
def test_pdf_digital_completo_y_exacto(tipo):
    pdf, verdad = sd.generar(tipo, np.random.default_rng(11))
    r = documentos.procesar(pdf, tipo)
    faltan, mal = _comparar(r, verdad)
    assert r.lectura == documentos.COMPLETA and r.origen == "pdf_digital", r.avisos
    assert not faltan and not mal, (faltan, mal)
    assert r.tiempo_ms < 3000


@pytest.mark.parametrize("variante,esperado", [({"horas": 20}, False), ({}, True)])
def test_flc_horas(variante, esperado):
    pdf, _ = sd.generar("flc_60h", np.random.default_rng(12), **variante)
    assert documentos.procesar(pdf, "flc_60h").validaciones["horas_minimo_60"] is esperado


def test_master_propio():
    pdf, _ = sd.generar("ts_prl", np.random.default_rng(13), oficial=False)
    r = documentos.procesar(pdf, "ts_prl")
    assert r.validaciones["titulo_oficial"] is False


def test_certificado_caducado_y_no_al_corriente():
    pdf, _ = sd.generar("certificado_tgss", np.random.default_rng(14), antiguedad_min=220, antiguedad_max=300)
    assert documentos.procesar(pdf, "certificado_tgss").validaciones["vigente"] is False
    pdf, _ = sd.generar("certificado_aeat", np.random.default_rng(15), al_corriente=False)
    assert documentos.procesar(pdf, "certificado_aeat").validaciones["al_corriente"] is False


def test_poliza_vencida():
    pdf, _ = sd.generar("seguro_rc", np.random.default_rng(16), vigente=False)
    assert documentos.procesar(pdf, "seguro_rc").validaciones["vigente"] is False


@pytest.mark.parametrize("tipo", ["informacion_art18", "formacion_art19", "entrega_epis"])
def test_ficha_sin_firmar(tipo):
    pdf, _ = sd.generar(tipo, np.random.default_rng(17), firmada=False)
    r = documentos.procesar(pdf, tipo)
    assert r.campos["firmado"].valor is False and r.validaciones["firmado"] is False


def test_pagina_en_blanco_nunca_es_completa():
    if not any(m.disponible()[0] for m in motores.TODOS):
        pytest.skip("sin motores OCR en este entorno")
    r = documentos.procesar(sd.pdf_de_imagen(np.full((1100, 850, 3), 255, np.uint8)), "flc_60h")
    assert r.lectura == documentos.ILEGIBLE and not r.campos


# ── Nivel E: con OCR real ────────────────────────────────────────────────────

def _hay_motores():
    if not any(m.disponible()[0] for m in motores.TODOS):
        pytest.skip("sin motores OCR en este entorno")


@pytest.mark.ocr
@pytest.mark.parametrize("tipo", TIPOS)
def test_escaneado_sin_datos_erroneos(tipo):
    _hay_motores()
    rng = np.random.default_rng(21)
    pdf, verdad = sd.generar(tipo, rng)
    r = documentos.procesar(sd.escanear(pdf, rng), tipo)
    faltan, mal = _comparar(r, verdad)
    assert r.origen == "pdf_escaneado"
    if r.lectura == documentos.COMPLETA:
        assert not mal, mal
    assert r.lectura != documentos.OTRO_DOCUMENTO


@pytest.mark.ocr
@pytest.mark.parametrize("tipo", TIPOS)
def test_foto_sin_datos_erroneos(tipo):
    _hay_motores()
    rng = np.random.default_rng(22)
    pdf, verdad = sd.generar(tipo, rng)
    verdad = {k: v for k, v in verdad.items() if k not in sd.CAMPOS_PAGINA_2.get(tipo, ())}
    r = documentos.procesar(sd.a_jpeg(sd.foto(sd.a_imagen(pdf, 200), rng)), tipo)
    _, mal = _comparar(r, verdad)
    assert r.origen == "imagen"
    if r.lectura == documentos.COMPLETA:
        assert not mal, mal


@pytest.mark.ocr
def test_mayoria_de_escaneados_completos():
    """Criterio del roadmap para escaneados: ≥ 80 % COMPLETA."""
    _hay_motores()
    completos = 0
    for i, tipo in enumerate(TIPOS):
        rng = np.random.default_rng(30 + i)
        pdf, _ = sd.generar(tipo, rng)
        completos += documentos.procesar(sd.escanear(pdf, rng), tipo).lectura == documentos.COMPLETA
    assert completos / len(TIPOS) >= 0.8, completos


@pytest.mark.parametrize("titulo,profesion,habilita", [
    ("Graduado en Ingeniería en Tecnologías Industriales", "ingeniero_industrial", True),
    ("Ingeniero Industrial", "ingeniero_industrial", True),
    ("Ingeniero Técnico Industrial", "ingeniero_industrial", True),
    ("Arquitecto", "arquitecto", True),
    ("Arquitecto Técnico", "arquitecto_tecnico", True),
    ("Graduado en Ingeniería de Edificación", "arquitecto_tecnico", True),
    ("Graduado en Arquitectura Técnica", "arquitecto_tecnico", True),
    ("Ingeniero de Caminos, Canales y Puertos", "otra_ingenieria", False),
])
def test_titulo_tecnico_profesion(titulo, profesion, habilita):
    pdf, _ = sd.generar("titulo_tecnico", np.random.default_rng(18), titulo=titulo, profesion=profesion)
    r = documentos.procesar(pdf, "titulo_tecnico")
    assert r.campos["profesion"].valor == profesion, r.campos.get("titulo")
    assert r.validaciones["habilita_coordinador_seguridad_salud"] is habilita


@pytest.mark.parametrize("horas,esperado", [(200, True), (60, False)])
def test_curso_coordinador_horas(horas, esperado):
    pdf, _ = sd.generar("curso_coordinador_ss", np.random.default_rng(19), horas=horas)
    r = documentos.procesar(pdf, "curso_coordinador_ss")
    assert r.validaciones["horas_minimo_200"] is esperado
    assert r.validaciones["curso_coordinador_seguridad_salud"] is True


def test_master_prl_no_es_titulo_tecnico():
    pdf, _ = sd.generar("ts_prl", np.random.default_rng(20))
    r = documentos.procesar(pdf, "titulo_tecnico")
    assert "profesion" not in r.campos and r.lectura != documentos.COMPLETA
