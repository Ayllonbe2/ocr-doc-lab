# Hacia un OCR local multi-documento

Propuesta para llevar lo que hace MRZ Lab con el DNI a **otros documentos** (titulaciones,
certificados, pólizas…) y servirlo como un **servicio OCR propio, sin nube**, con un endpoint por
tipo de documento.

Estado: propuesta, sin implementar.

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

Lo que ya existe en `mrzlab/`, sin cambios de fondo:

| Pieza | Módulo |
|---|---|
| Motores OCR (Tesseract, RapidOCR) detrás de una interfaz común | `motores.py` |
| Calidad de la imagen (nitidez, luz, reflejos, resolución) | `calidad.py` |
| Enderezado de la tarjeta, contraste local | `preproceso.py` |
| Plantilla de posiciones (dónde está cada campo) | `plantilla.py` |

A añadir:

- **Entrada de PDF.** Si el PDF es digital (tiene capa de texto), se lee el texto directamente,
  sin OCR: es más rápido y no tiene errores de lectura. Solo los PDF escaneados y las fotos pasan
  por el OCR. En certificados y titulaciones lo habitual es lo primero.
- **Resultado común:** `{tipo, campos, validaciones, calidad, avisos}`. Cada campo lleva de dónde
  sale (etiqueta, posición, capa de texto) para poder medir y depurar.

### Un extractor por tipo de documento

Cada tipo es una pieza independiente con la misma interfaz:

```python
class Extractor:
    tipo = "flc_60h"                        # identificador del endpoint
    campos = ("titular", "nif", "horas", "entidad", "fecha")

    def extraer(self, lineas, imagen) -> Resultado:
        """Campos a partir de las líneas del OCR (texto + caja) o de la capa de texto del PDF."""

    def validar(self, campos) -> dict[str, bool]:
        """Comprobaciones propias del documento (letra del NIF, fechas coherentes, horas mínimas…)."""
```

Ejemplos: `dni` (ya existe: MRZ y anverso), certificados de formación, titulaciones oficiales,
pólizas de seguro, certificados de empresa. Añadir un documento nuevo es añadir un extractor y sus
casos de prueba; el resto no cambia.

### Endpoints

Con versión desde el principio, para poder cambiar el contrato sin romper a nadie:

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/v1/documentos/tipos` | Tipos admitidos y los campos de cada uno |
| `POST` | `/v1/documentos/{tipo}/extraer` | Extrae los campos de un documento (imagen o PDF) |
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

## Servirlo en su propio subdominio

Por ejemplo `ocr.ejemplo.es`, con Docker y [Caddy](https://caddyserver.com/) como proxy inverso
(certificado HTTPS automático):

1. **DNS:** registro `A` `ocr` → IP del servidor (y `AAAA` si usa IPv6).
2. **Proxy:**

   ```caddyfile
   ocr.ejemplo.es {
       request_body {
           max_size 16MB
       }
       reverse_proxy ocr:8001
   }
   ```

3. **Docker Compose:** el contenedor del OCR en la misma red que Caddy, sin publicar su puerto
   al exterior, y con límite de CPU, porque el OCR local consume varios segundos de CPU por
   documento y no debe dejar sin recursos al resto de servicios del servidor:

   ```yaml
   ocr:
     build: .
     environment:
       OCR_API_KEY: ${OCR_API_KEY:?}
     networks: [web]
     deploy:
       resources:
         limits:
           cpus: "2"
           memory: 3g
   ```

**¿Hace falta exponerlo?** Solo si lo van a llamar clientes de fuera del servidor o si vive en otro
servidor. Si quien lo usa está en el mismo servidor, es más seguro dejarlo solo en la red interna
de Docker: los documentos no viajan por internet. Si se expone, además de HTTPS y la clave: límite
de peticiones por IP o lista de IPs permitidas.

## Relación con MRZ Lab

MRZ Lab es el **banco de pruebas**: aquí se comparan motores, se calibran umbrales y plantillas y se
mide cada extractor con lotes y `verdad.csv`. El servicio es la **versión de producción** de lo que
aquí funcione. Para otros documentos, el lab necesitaría:

- selector de tipo de documento en la página (hoy: anverso / reverso del DNI);
- `verdad.csv` por tipo, con sus campos;
- muestras sintéticas de cada documento, para probar sin datos reales.
