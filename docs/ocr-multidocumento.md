# Hacia un OCR local multi-documento

Propuesta para llevar lo que hace el lab con el DNI a **otros documentos** (titulaciones,
certificados, pólizas…) y servirlo como un **servicio OCR propio, sin nube y solo en localhost**, con un endpoint por
tipo de documento.

Estado: implementado (18 tipos de documento). Qué falta y cómo se ha medido: [Roadmap](roadmap.md).

## Por qué

- **Privacidad:** los documentos de identidad y los certificados son datos personales. Con un OCR
  local no salen de tu servidor, y si el servicio no guarda nada, tampoco quedan copias.
- **Fiabilidad:** el OCR genérico en la nube lee texto, pero no sabe qué es cada dato. Casi toda
  la calidad está en la extracción (etiquetas, posiciones, dígitos de control, validaciones), y eso
  es código propio en cualquier caso.
- **Un solo sitio para cada cosa:** motores, calidad de imagen y preprocesado se comparten entre
  todos los documentos; lo que cambia de uno a otro es solo el extractor.

## Diseño

### Núcleo común

| Pieza | Módulo |
|---|---|
| Motores OCR (Tesseract, RapidOCR) detrás de una interfaz común | `motores.py` |
| Calidad de la imagen (nitidez, luz, reflejos, resolución; y para A4, alto de la letra) | `calidad.py` |
| PDF: capa de texto y render (PDFium), formularios sin aplanar (pdfplumber) | `pdf.py` |
| Hoja en la foto, orientación e inclinación | `pagina.py` |
| OCR de páginas: Tesseract; en fotos, detección de RapidOCR y relectura por línea | `ocr_documento.py` |
| Leer un documento y extraer los campos de un tipo | `documentos.py` |
| NIF/NIE/CIF, fechas, importes | `validadores.py` |
| Firma PAdES, CSV/CEA, QR, metadatos | `autenticidad.py` |
| Qué tipo de documento es | `clasificador.py` |

- **Entrada de PDF.** Si el PDF es digital (tiene capa de texto), se lee el texto directamente,
  sin OCR: es más rápido y no tiene errores de lectura. Solo los PDF escaneados y las fotos pasan
  por el OCR. Se decide por página.
- **Resultado común:** `{tipo, lectura, origen, campos, validaciones, clasificacion, autenticidad,
  calidad, avisos}`. Cada campo lleva de dónde sale (`capa_texto`, `formulario`, `ocr:<motor>`) y
  su confianza.

### Un extractor por tipo de documento

Cada tipo es una pieza independiente con la misma interfaz (`mrzlab/extractores/base.py`):

```python
class Extractor:
    tipo = "flc_60h"                        # identificador del endpoint
    campos = ("titular", "nif", "horas", "numero_registro", "numero_curso", "entidad", "fecha")
    obligatorios = ("titular", "nif", "horas", "fecha")
    claves = {r"FUNDACION LABORAL DE LA CONSTRUCCION": 3, ...}   # para el clasificador

    def extraer(self, doc) -> dict[str, Campo]:
        """Campos a partir de las líneas (texto + caja + origen), vengan del PDF o del OCR."""

    def validar(self, campos, doc) -> dict[str, bool | None]:
        """Comprobaciones propias del documento (letra del NIF, horas mínimas, vigencia…)."""
```

Añadir un documento nuevo es añadir un extractor, su plantilla sintética
(`sintetico_docs.py`) y sus pruebas; el resto no cambia.

### Endpoints

Con versión desde el principio, para poder cambiar el contrato sin romper a nadie:

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/v1/documentos/tipos` | Tipos admitidos y los campos de cada uno |
| `POST` | `/v1/documentos/{tipo}/extraer` | Extrae los campos de un documento (imagen o PDF) |
| `POST` | `/v1/documentos/clasificar` | Qué tipo de documento es |
| `POST` | `/v1/dni/verificar` | Flujo completo del DNI: anverso + reverso + DNI declarado → verificado / repetir / revisión manual |
| `GET` | `/health` | Estado del servicio y de los motores |

Reglas del servicio:

- **Sin estado y sin guardar nada.** Quien llama envía los bytes; el servicio procesa en memoria
  (sin ficheros temporales en disco) y responde. No descarga de ningún almacenamiento ni guarda
  copias. Los logs solo llevan el tipo, el resultado y el tiempo, nunca datos del documento.
- **Autenticación** con una clave compartida (`X-Api-Key`), comparada en tiempo constante.
- **Límites:** tamaño máximo por fichero y número de páginas por PDF.

## Cómo migrar desde un OCR en la nube

1. **Convivir.** Los endpoints nuevos se añaden junto a los actuales; nada cambia para quien ya los
   usa.
2. **Medir.** Por cada tipo de documento, un lote de ejemplos reales (con consentimiento) y su
   `verdad.csv`, igual que con el DNI: acierto por campo, y sobre todo **cuántos datos erróneos se
   dan por buenos**, que debe ser 0.
3. **Cambiar tipo a tipo.** Quien llama pasa al endpoint nuevo documento a documento, empezando por
   los que mejor salen en la medición.
4. **Retirar la nube.** Dependencias, credenciales, variables de entorno y la mención en la
   política de privacidad.

El riesgo está en el paso 2: en documentos desordenados o de mala calidad un OCR en la nube suele
leer mejor. Por eso se mide antes de cambiar, y la calidad de imagen sirve para pedir otra foto en
vez de dar por bueno un dato dudoso.

## Solo en localhost

El servicio **no se expone**: ni subdominio, ni proxy público, ni puerto abierto a internet. Escucha
en `127.0.0.1` (o solo en la red interna de Docker) y lo usa quien corre en la misma máquina, así
que los documentos nunca viajan por la red.

```yaml
ocr:
  build: .
  ports:
    - "127.0.0.1:8001:8001"      # o sin «ports» si quien llama está en la misma red de Docker
  environment:
    OCR_API_KEY: ${OCR_API_KEY:?}
  deploy:
    resources:
      limits:
        cpus: "2"                # el OCR gasta varios segundos de CPU por documento
        memory: 3g
```

La clave `X-Api-Key` queda como segunda barrera frente a otros procesos de la misma máquina.
Plan de desarrollo, tipo a tipo y con sus pruebas: [Roadmap](roadmap.md).

## Relación entre el lab y el servicio

El lab es el **banco de pruebas**: aquí se comparan motores, se calibran umbrales y plantillas y se
mide cada extractor con lotes y `verdad.csv`. El servicio es la **versión de producción** de lo que
aquí funcione. Para otros documentos, el lab necesitaría:

- selector de tipo de documento en la página (hoy: anverso / reverso del DNI);
- `verdad.csv` por tipo, con sus campos;
- muestras sintéticas de cada documento, para probar sin datos reales.
