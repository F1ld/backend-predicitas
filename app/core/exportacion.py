"""Exportación de reportes (contratos/comun.json → exportacion y servicios_internos; D-016).

    responder(filas, columnas, formato, nombre) -> Response

- json: lista de objetos con solo las `columnas` pedidas.
- csv: UTF-8 con BOM, separador coma, cabecera con los nombres de campo del contrato.
- xlsx: una hoja (openpyxl) con la cabecera en negrita.

csv y xlsx se descargan como <nombre>_<fecha en Lima>.<ext>. Registrar el evento EXPORT
en auditoría (modulo=REPORTES) le toca a quien llama, porque conoce al usuario y la sesión de BD.
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from openpyxl import Workbook
from openpyxl.styles import Font

from app.core.errores import Validacion

ZONA_LIMA = ZoneInfo("America/Lima")
FORMATOS = ("json", "csv", "xlsx")
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Un texto que empieza así lo interpretan Excel o LibreOffice como fórmula (inyección CSV).
_INICIO_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def responder(filas: list[dict], columnas: list[str], formato: str, nombre: str) -> Response:
    formato = (formato or "json").lower()
    if formato not in FORMATOS:
        raise Validacion("Formato de exportación no válido",
                         campos={"formato": "Debe ser json, csv o xlsx"})
    if formato == "json":
        return JSONResponse(jsonable_encoder([{c: f.get(c) for c in columnas} for f in filas]))

    archivo = f"{nombre}_{datetime.now(ZONA_LIMA).date().isoformat()}.{formato}"
    cabeceras = {"Content-Disposition": f'attachment; filename="{archivo}"'}
    if formato == "csv":
        return Response(_csv(filas, columnas), media_type="text/csv; charset=utf-8", headers=cabeceras)
    return Response(_xlsx(filas, columnas), media_type=TIPO_XLSX, headers=cabeceras)


def _texto_seguro(valor: str) -> str:
    return "'" + valor if valor.startswith(_INICIO_FORMULA) else valor


def _celda_csv(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, str):
        return _texto_seguro(valor)
    return str(valor)


def _csv(filas: list[dict], columnas: list[str]) -> bytes:
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow(columnas)
    for fila in filas:
        escritor.writerow([_celda_csv(fila.get(c)) for c in columnas])
    return salida.getvalue().encode("utf-8-sig")


def _celda_xlsx(valor):
    if isinstance(valor, datetime) and valor.tzinfo is not None:
        # Excel no guarda zona horaria: se escribe la hora de Lima.
        return valor.astimezone(ZONA_LIMA).replace(tzinfo=None)
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, str):
        return _texto_seguro(valor)
    if isinstance(valor, (dict, list)):
        return str(valor)
    return valor


def _xlsx(filas: list[dict], columnas: list[str]) -> bytes:
    libro = Workbook()
    hoja = libro.active
    hoja.title = "datos"
    hoja.append(columnas)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in filas:
        hoja.append([_celda_xlsx(fila.get(c)) for c in columnas])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
