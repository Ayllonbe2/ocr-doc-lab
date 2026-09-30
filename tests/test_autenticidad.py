"""Firma PAdES, códigos de verificación, QR y metadatos. Certificados generados en el test."""
import io
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest

from mrzlab import autenticidad, documentos
from mrzlab import sintetico_docs as sd


def test_codigos_de_verificacion():
    texto = ("Código Seguro de Verificación: ABCD1234EFGH5678\n"
             "CÓDIGO ELECTRÓNICO DE AUTENTICIDAD (CEA): XYZ1-2345-ABCD-9876\n"
             "Puede comprobarlo con el CSV: verificar en la sede")
    assert autenticidad.codigos_verificacion(texto) == [{"tipo": "CSV", "codigo": "ABCD1234EFGH5678"},
                                                        {"tipo": "CEA", "codigo": "XYZ12345ABCD9876"}]


def test_palabras_que_contienen_cea_o_csv_no_cuentan():
    assert autenticidad.codigos_verificacion("OCEANO 12345678 LIENCEA 99999999") == []


def test_qr():
    qr = cv2.QRCodeEncoder.create().encode("https://sede.ejemplo/verificar?csv=ABC123")
    img = cv2.resize(qr, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    img = cv2.copyMakeBorder(img, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    assert autenticidad.qrs([cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)]) == ["https://sede.ejemplo/verificar?csv=ABC123"]


def test_avisos_de_metadatos():
    assert autenticidad.avisos_metadatos({"producer": "Adobe Photoshop 25"}, [])
    assert autenticidad.avisos_metadatos({"revisiones": 3}, [])
    assert autenticidad.avisos_metadatos({"producer": "sintetico_docs", "revisiones": 1}, []) == []


# ── Firma electrónica ────────────────────────────────────────────────────────

def _firmante():
    """Certificado autofirmado de prueba (nada real)."""
    pytest.importorskip("pyhanko")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pyhanko.sign import signers
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ORGANISMO DE PRUEBA")])
    ahora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
            .not_valid_after(ahora + timedelta(days=30))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
            .sign(clave, hashes.SHA256()))
    pem_clave = clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    pem_cert = cert.public_bytes(serialization.Encoding.PEM)
    from asn1crypto import keys, x509 as ax509
    from asn1crypto import pem as apem
    _, _, der_clave = apem.unarmor(pem_clave)
    _, _, der_cert = apem.unarmor(pem_cert)
    return signers.SimpleSigner(signing_cert=ax509.Certificate.load(der_cert),
                                signing_key=keys.PrivateKeyInfo.load(der_clave), cert_registry=None)


def _firmar(pdf: bytes) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    salida = io.BytesIO()
    signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf)), signers.PdfSignatureMetadata(field_name="Firma"),
                     signer=_firmante(), output=salida)
    return salida.getvalue()


def test_pdf_firmado_integro():
    pdf, _ = sd.generar("certificado_aeat", np.random.default_rng(1))
    firmas = autenticidad.firmas(_firmar(pdf))
    assert len(firmas) == 1
    f = firmas[0]
    assert f["integra"] and f["cubre_todo"] and not f["modificado_tras_firmar"]
    assert "ORGANISMO DE PRUEBA" in f["firmante"] and f["confianza_comprobada"] is False


def test_pdf_modificado_tras_firmar():
    from pyhanko.pdf_utils.generic import NameObject, TextStringObject
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    pdf, _ = sd.generar("certificado_aeat", np.random.default_rng(1))
    firmado = _firmar(pdf)
    w = IncrementalPdfFileWriter(io.BytesIO(firmado))
    w.root[NameObject("/Lang")] = TextStringObject("es")     # un cambio cualquiera tras la firma
    w.update_root()
    salida = io.BytesIO()
    w.write(salida)
    f = autenticidad.firmas(salida.getvalue())[0]
    assert f["integra"] and not f["cubre_todo"] and f["modificado_tras_firmar"]
    assert "El PDF se ha modificado después de firmarse" in autenticidad.avisos_metadatos({}, [f])


def test_bytes_alterados_rompen_la_firma():
    pdf, verdad = sd.generar("certificado_aeat", np.random.default_rng(1))
    firmado = bytearray(_firmar(pdf))
    i = firmado.find(b"/Producer")
    firmado[i + 12] = (firmado[i + 12] + 1) % 256        # un byte dentro de lo firmado
    firmas = autenticidad.firmas(bytes(firmado))
    assert not firmas or not firmas[0]["integra"]


def test_ficha_con_firma_electronica_cuenta_como_firmada():
    pdf, _ = sd.generar("entrega_epis", np.random.default_rng(2), firmada=False)
    r = documentos.procesar(_firmar(pdf), "entrega_epis")
    assert r.campos["firmado"].valor is True and r.campos["firmado"].origen == "firma_electronica"
