"""Servicio OCR de producción: API HTTP sin estado sobre el núcleo de `mrzlab`.

Las imágenes se procesan en memoria y se descartan: no se guardan en disco (tampoco como fichero
temporal de la subida), no se registran en logs y no salen de este proceso.

ONNX Runtime (lo usa RapidOCR) envía telemetría a Microsoft por defecto: se desactiva aquí,
antes de que ningún módulo lo importe.
"""
import os

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
