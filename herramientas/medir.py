"""Mide los extractores con un lote de documentos y su verdad.

Dos modos:

    # Lote real (fuera del repositorio): carpeta con los documentos y verdad.csv
    python -m herramientas.medir datos/reales

    # Lote sintético generado al vuelo: N documentos por tipo y por origen
    python -m herramientas.medir --sintetico 3 --origenes digital,escaneado,foto

verdad.csv (una fila por campo, así vale para cualquier tipo):

    archivo,tipo,campo,valor
    diploma1.pdf,flc_60h,nif,12345678Z
    diploma1.pdf,flc_60h,horas,60
    diploma1.pdf,flc_60h,fecha,2025-03-14

Lo que importa es la columna «erróneos dados por buenos»: un campo con un valor distinto del
real en un documento que el servicio da por COMPLETO. Debe ser 0.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from mrzlab import documentos
from mrzlab.validadores import sin_acentos


def normalizar(v) -> str:
    if v is None:
        return ""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    # Sin el punto final: «S.A.U» y «S.A.U.» son la misma razón social.
    s = " ".join(sin_acentos(str(v)).split()).rstrip(".")
    return {"TRUE": "true", "FALSE": "false", "SI": "true", "NO": "false"}.get(s, s)


class Informe:
    def __init__(self):
        self.docs = defaultdict(lambda: defaultdict(int))              # (tipo, origen) -> lectura -> n
        self.campos = defaultdict(lambda: defaultdict(int))            # (tipo, campo) -> bien/falta/mal/mal_aceptado
        self.tiempos = defaultdict(list)                               # origen -> ms
        self.errores: list[str] = []

    def anotar(self, nombre: str, tipo: str, origen: str, verdad: dict, r: dict) -> None:
        self.docs[(tipo, origen)][r["lectura"]] += 1
        self.tiempos[origen].append(r["tiempo_ms"])
        for campo, esperado in verdad.items():
            if esperado in (None, ""):
                continue
            leido = r["campos"].get(campo, {}).get("valor")
            if leido is None:
                self.campos[(tipo, campo)]["falta"] += 1
            elif normalizar(leido) == normalizar(esperado):
                self.campos[(tipo, campo)]["bien"] += 1
            else:
                aceptado = r["lectura"] == documentos.COMPLETA
                self.campos[(tipo, campo)]["mal_aceptado" if aceptado else "mal"] += 1
                if aceptado:
                    self.errores.append(f"{nombre} [{tipo}/{origen}] {campo}: leído «{leido}», real «{esperado}»")

    def imprimir(self) -> int:
        print("\n== Documentos por tipo y origen ==")
        print(f"{'tipo':26s} {'origen':14s} {'n':>3s} {'COMPLETA':>9s} {'INCOMPL.':>9s} {'ILEGIBLE':>9s} {'OTRO':>5s}")
        for (tipo, origen), c in sorted(self.docs.items()):
            n = sum(c.values())
            print(f"{tipo:26s} {origen:14s} {n:3d} {c['COMPLETA']:9d} {c['INCOMPLETA']:9d} {c['ILEGIBLE']:9d} "
                  f"{c['OTRO_DOCUMENTO']:5d}")
        print("\n== Campos ==")
        print(f"{'tipo':26s} {'campo':22s} {'bien':>5s} {'falta':>6s} {'mal':>4s} {'MAL DADO POR BUENO':>19s}")
        for (tipo, campo), c in sorted(self.campos.items()):
            print(f"{tipo:26s} {campo:22s} {c['bien']:5d} {c['falta']:6d} {c['mal']:4d} {c['mal_aceptado']:19d}")
        print("\n== Tiempo por documento (ms) ==")
        for origen, ts in sorted(self.tiempos.items()):
            ts = sorted(ts)
            p95 = ts[min(len(ts) - 1, int(round(0.95 * (len(ts) - 1))))]
            print(f"{origen:14s} n={len(ts):3d} mediana={statistics.median(ts):7.0f} p95={p95:7.0f}")
        print(f"\n== Erróneos dados por buenos: {len(self.errores)} ==")
        for e in self.errores:
            print("  " + e)
        return len(self.errores)


def lote_real(carpeta: Path, informe: Informe) -> None:
    verdad: dict[str, tuple[str, dict]] = {}
    with open(carpeta / "verdad.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            tipo, campos = verdad.setdefault(fila["archivo"], (fila["tipo"], {}))
            campos[fila["campo"]] = fila["valor"]
    for archivo, (tipo, campos) in verdad.items():
        ruta = carpeta / archivo
        try:
            r = documentos.procesar(ruta.read_bytes(), tipo).a_dict()
        except Exception as e:
            print(f"  {archivo}: error {type(e).__name__}: {e}", file=sys.stderr)
            continue
        informe.anotar(archivo, tipo, r["origen"], campos, r)
        print(f"  {archivo:40s} {tipo:24s} {r['lectura']:14s} {r['tiempo_ms']:6d} ms", flush=True)


def lote_sintetico(n: int, origenes: list[str], tipos: list[str] | None, informe: Informe) -> None:
    from mrzlab import sintetico_docs as sd
    for tipo in tipos or list(sd.PLANTILLAS):
        for i in range(n):
            for origen in origenes:
                rng = np.random.default_rng(1000 * i + sum(map(ord, tipo)))    # reproducible
                pdf, verdad = sd.generar(tipo, rng)
                if origen == "escaneado":
                    datos = sd.escanear(pdf, rng)
                elif origen == "foto":
                    # Una foto es de una sola página: solo cuentan los campos de la primera.
                    datos = sd.a_jpeg(sd.foto(sd.a_imagen(pdf, 200), rng))
                    verdad = {k: v for k, v in verdad.items() if k not in sd.CAMPOS_PAGINA_2.get(tipo, ())}
                else:
                    datos = pdf
                r = documentos.procesar(datos, tipo).a_dict()
                informe.anotar(f"{tipo}#{i}", tipo, origen, verdad, r)
                print(f"  {tipo:24s} #{i} {origen:10s} {r['lectura']:14s} {r['tiempo_ms']:6d} ms", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("carpeta", nargs="?", type=Path, help="carpeta con los documentos y verdad.csv")
    p.add_argument("--sintetico", type=int, metavar="N", help="N documentos sintéticos por tipo y origen")
    p.add_argument("--origenes", default="digital,escaneado,foto")
    p.add_argument("--tipos", help="solo estos tipos (separados por comas)")
    a = p.parse_args(argv)
    if not a.carpeta and not a.sintetico:
        p.error("indica una carpeta o --sintetico N")
    informe = Informe()
    t0 = time.time()
    if a.carpeta:
        lote_real(a.carpeta, informe)
    if a.sintetico:
        lote_sintetico(a.sintetico, a.origenes.split(","), a.tipos.split(",") if a.tipos else None, informe)
    errores = informe.imprimir()
    print(f"\nTotal: {time.time() - t0:.0f} s")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
