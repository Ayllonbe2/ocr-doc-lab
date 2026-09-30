"""Un extractor por tipo de documento. Añadir un tipo = añadir su clase aquí y sus pruebas."""
from __future__ import annotations

from .base import Extractor
from .empresa import (AperturaCentro, CertificadoAeat, CertificadoTgss, DocumentacionCae, EvaluacionRiesgos,
                      PlanSeguridadSalud, RegistroEmpresa, SeguroRc)
from .titulaciones import Flc60h, TsPrl, TsRiesgos
from .trabajador import (ContratoLaboral, EntregaEpis, FormacionArt19, InformacionArt18,
                         ReconocimientoMedico)

REGISTRO: dict[str, Extractor] = {e.tipo: e for e in (
    Flc60h(), TsRiesgos(), TsPrl(),
    CertificadoTgss(), CertificadoAeat(), SeguroRc(), RegistroEmpresa(), AperturaCentro(),
    PlanSeguridadSalud(), EvaluacionRiesgos(), DocumentacionCae(),
    ContratoLaboral(), ReconocimientoMedico(), InformacionArt18(), FormacionArt19(), EntregaEpis(),
)}
