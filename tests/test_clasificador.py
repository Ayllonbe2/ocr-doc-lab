"""¿Qué documento es? Cada tipo sintético se reconoce como él mismo y como ningún otro."""
import numpy as np
import pytest

from mrzlab import clasificador, documentos
from mrzlab import sintetico_docs as sd
from mrzlab.extractores import REGISTRO


@pytest.mark.parametrize("tipo", list(REGISTRO))
def test_cada_tipo_se_reconoce(tipo):
    pdf, _ = sd.generar(tipo, np.random.default_rng(7))
    c = clasificador.clasificar(documentos.leer(pdf).texto_norm, solicitado=tipo)
    assert c["tipo_detectado"] == tipo and c["coincide"], c


def test_cada_plantilla_tiene_su_tipo():
    assert set(sd.PLANTILLAS) == set(REGISTRO)


def test_texto_sin_relacion_es_desconocido():
    c = clasificador.clasificar("FACTURA DE LA LUZ DEL MES DE MARZO IMPORTE TOTAL", solicitado="flc_60h")
    assert c["tipo_detectado"] is None and not c["coincide"]


def test_documento_de_otro_tipo():
    """Un diploma FLC subido como máster: OTRO_DOCUMENTO, nunca COMPLETA."""
    pdf, _ = sd.generar("flc_60h", np.random.default_rng(8))
    r = documentos.procesar(pdf, "ts_prl")
    assert r.lectura == documentos.OTRO_DOCUMENTO and r.clasificacion["tipo_detectado"] == "flc_60h"


@pytest.mark.parametrize("tipo", list(REGISTRO))
def test_ningun_tipo_da_por_completo_el_documento_de_otro(tipo):
    """Nivel N: el documento de cada tipo, procesado como el siguiente tipo, nunca es COMPLETA."""
    tipos = list(REGISTRO)
    otro = tipos[(tipos.index(tipo) + 1) % len(tipos)]
    pdf, _ = sd.generar(tipo, np.random.default_rng(9))
    assert documentos.procesar(pdf, otro).lectura != documentos.COMPLETA
