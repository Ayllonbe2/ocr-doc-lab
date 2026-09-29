"""MRZ Lab.

ONNX Runtime (lo usa RapidOCR) envía telemetría a Microsoft por defecto, también en Linux.
Se desactiva aquí, antes de que ningún módulo lo importe: el laboratorio no debe hacer
ninguna conexión saliente.
"""
import os

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
