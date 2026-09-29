"""Verificación del DNI: decide VERIFICADO, REPETIR o REVISION_ADMIN.

Regla (100 %): el nº de DNI coincide en el anverso, en el reverso (MRZ válida) y con el que
declara el usuario, **y** el nº de soporte coincide en el anverso y en el reverso.

Si no se consigue leer:
- con mala calidad de foto en la cara que falla → se pide repetirla, una vez;
- si vuelve a pasar (2.º intento) → revisión manual de un admin;
- con buena calidad (repetir no ayudaría) → revisión manual directamente.
Si se lee todo pero algún dato no coincide → revisión manual directamente.

Es **sin estado**: quien llama (el backend) lleva la cuenta de intentos y avisa al admin.
Las imágenes no se guardan: se procesan en memoria y se descartan. Al admin le llegan solo
los datos leídos y el motivo.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum

from . import lectura
from .lectura import LecturaAnverso, LecturaReverso

logger = logging.getLogger(__name__)

INTENTOS_MAX = 2


class Estado(str, Enum):
    VERIFICADO = "VERIFICADO"
    REPETIR = "REPETIR"
    REVISION_ADMIN = "REVISION_ADMIN"


class Motivo(str, Enum):
    OK = "OK"
    MALA_CALIDAD = "MALA_CALIDAD"                   # REPETIR
    INTENTOS_AGOTADOS = "INTENTOS_AGOTADOS"         # 2.º intento con mala calidad
    DATOS_NO_COINCIDEN = "DATOS_NO_COINCIDEN"       # se leyó, pero algo no cuadra
    LECTURA_FALLIDA = "LECTURA_FALLIDA"             # no se leyó y la calidad es buena


def normalizar_dni(texto: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (texto or "").upper())


@dataclass
class Resultado:
    estado: Estado
    motivo: Motivo
    intento: int
    intentos_max: int
    comprobaciones: dict[str, bool | None]
    datos_reverso: dict[str, str | None]
    datos_anverso: dict[str, str | None]
    calidad: dict[str, dict]
    instrucciones: list[str] = field(default_factory=list)   # solo en REPETIR
    avisos: list[str] = field(default_factory=list)          # informativos (p. ej. caducado)
    detalle: str = ""

    def a_dict(self) -> dict:
        d = asdict(self)
        d["estado"], d["motivo"] = self.estado.value, self.motivo.value
        return d


_CAMPOS_REVERSO = ("dni", "num_soporte", "nombre", "apellidos", "nacionalidad",
                   "fecha_nacimiento", "fecha_caducidad")


def decidir(anv: LecturaAnverso, rev: LecturaReverso, dni_declarado: str, intento: int) -> Resultado:
    """La decisión, sin OCR: se puede probar con lecturas hechas a mano."""
    declarado = normalizar_dni(dni_declarado)
    campos_mrz = rev.mrz.campos if rev.valida else {}
    dni_rev, sop_rev = campos_mrz.get("dni"), campos_mrz.get("num_soporte")
    # Del anverso, el candidato que coincide con la MRZ; si no hay, el primero. El dato de la
    # MRZ (protegido por sus controles) también vale si aparece tal cual en el texto del
    # anverso, aunque el OCR lo haya pegado a otro («ABC12345602102024»).
    def del_anverso(valor_mrz, candidatos):
        if valor_mrz and (valor_mrz in candidatos or valor_mrz in anv.texto):
            return valor_mrz
        return candidatos[0] if candidatos else None
    dni_anv = del_anverso(dni_rev, anv.dnis)
    sop_anv = del_anverso(sop_rev, anv.soportes)

    def igual(a, b):
        return None if a is None or b is None else a == b

    comprobaciones = {
        "mrz_valida": rev.valida,
        "dni_anverso_leido": dni_anv is not None,
        "soporte_anverso_leido": sop_anv is not None,
        "dni_anverso_igual_reverso": igual(dni_anv, dni_rev),
        "dni_reverso_igual_declarado": igual(dni_rev, declarado or None),
        "dni_anverso_igual_declarado": igual(dni_anv, declarado or None),
        "soporte_anverso_igual_reverso": igual(sop_anv, sop_rev),
    }
    datos_reverso = {c: campos_mrz.get(c) for c in _CAMPOS_REVERSO}
    datos_anverso = {"dni": dni_anv, "num_soporte": sop_anv}
    cal = {"anverso": asdict(anv.calidad), "reverso": asdict(rev.calidad)}
    avisos = []
    cad = campos_mrz.get("fecha_caducidad")
    if cad and datetime.strptime(cad, "%d/%m/%Y").date() < date.today():
        avisos.append("El DNI está caducado.")

    def res(estado, motivo, detalle="", instrucciones=()):
        return Resultado(estado, motivo, intento, INTENTOS_MAX, comprobaciones, datos_reverso,
                         datos_anverso, cal, list(instrucciones), avisos, detalle)

    comparaciones = [k for k in comprobaciones if "_igual_" in k]
    no_coinciden = [k for k in comparaciones if comprobaciones[k] is False]
    if no_coinciden:
        # Un dato leído con garantías (letra del DNI, controles de la MRZ) no cuadra con otro:
        # repetir la foto no lo arregla.
        return res(Estado.REVISION_ADMIN, Motivo.DATOS_NO_COINCIDEN,
                   "No coinciden: " + ", ".join(no_coinciden))
    if all(comprobaciones[k] is True for k in comparaciones):
        return res(Estado.VERIFICADO, Motivo.OK)

    # Falta algún dato por leer.
    fallidas = []
    if not rev.valida:
        fallidas.append(("reverso", rev.calidad))
    if not (anv.dnis and anv.soportes):
        fallidas.append(("anverso", anv.calidad))
    if not fallidas:  # se leyó todo pero falta el DNI declarado
        return res(Estado.REVISION_ADMIN, Motivo.DATOS_NO_COINCIDEN, "Falta el DNI declarado")
    que = ", ".join(c for c, _ in fallidas)
    if any(c.mala for _, c in fallidas):
        if intento < INTENTOS_MAX:
            instrucciones = []
            for cara, c in fallidas:
                for aviso in c.avisos or ["No se ha podido leer bien."]:
                    instrucciones.append(f"{cara.capitalize()}: {aviso}")
            return res(Estado.REPETIR, Motivo.MALA_CALIDAD, f"No se pudo leer: {que}", instrucciones)
        return res(Estado.REVISION_ADMIN, Motivo.INTENTOS_AGOTADOS,
                   f"No se pudo leer ({que}) tras {intento} intentos con mala calidad")
    return res(Estado.REVISION_ADMIN, Motivo.LECTURA_FALLIDA,
               f"No se pudo leer ({que}) y la calidad de la foto es buena")


def verificar(anverso: bytes, reverso: bytes, dni_declarado: str, intento: int = 1) -> Resultado:
    """Proceso completo. Las imágenes solo viven en memoria durante la llamada."""
    if not 1 <= intento <= INTENTOS_MAX:
        raise ValueError(f"intento debe estar entre 1 y {INTENTOS_MAX}")
    t0 = time.perf_counter()
    img_a = lectura.decodificar(anverso)
    img_r = lectura.decodificar(reverso)
    try:
        resultado = decidir(lectura.leer_anverso(img_a), lectura.leer_reverso(img_r),
                            dni_declarado, intento)
    finally:
        del img_a, img_r
    # Nunca registrar datos del DNI (RGPD): solo el resultado y el tiempo.
    logger.info("Verificación DNI: estado=%s motivo=%s intento=%d %.1fs",
                resultado.estado.value, resultado.motivo.value, intento, time.perf_counter() - t0)
    return resultado
