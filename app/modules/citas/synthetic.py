"""Generador de citas sintéticas (reproducible con semilla). No toca la base de datos.

Los resultados son SIMULADOS (RF-056 / RN16): el prefijo SIM en los identificadores lo deja explícito.
La tasa de no-show es un supuesto de modelado, no un dato de la clínica (RF-033).
"""
import math
import random
from datetime import date, datetime, timedelta

from app.modules.citas.reglas import LIMA

MEDICOS = {
    "CARDIOLOGIA": ["Dr. Ramírez", "Dra. Quispe", "Dr. Valdivia"],
    "TRAUMATOLOGIA": ["Dra. Vargas", "Dr. Salcedo", "Dr. Paredes"],
    "PEDIATRIA": ["Dr. Mendoza", "Dra. Morales", "Dra. Cárdenas"],
}
HORAS_MANANA = [(h, m) for h in range(8, 13) for m in (0, 30)]  # 08:00 a 12:30
HORAS_TARDE = [(h, m) for h in range(14, 19) for m in (0, 30)]  # 14:00 a 18:30


def _sigmoide(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _calibrar(zs: list[float], objetivo: float) -> float:
    """Busca el intercepto que lleva la tasa media de no-show al objetivo (bisección)."""
    bajo, alto = -15.0, 15.0
    for _ in range(60):
        medio = (bajo + alto) / 2
        tasa = sum(_sigmoide(z + medio) for z in zs) / len(zs)
        bajo, alto = (medio, alto) if tasa < objetivo else (bajo, medio)
    return (bajo + alto) / 2


def _fecha_laborable(rng: random.Random, inicio: date, fin: date) -> date:
    while True:  # lunes a sábado (el dominio del piloto no incluye domingo)
        dia = inicio + timedelta(days=rng.randint(0, (fin - inicio).days))
        if dia.weekday() != 6:
            return dia


def _registro_base(rng: random.Random, numero: int, dia: date, corte: datetime, prefijo: str):
    especialidad = rng.choice(list(MEDICOS))
    franja = "MANANA" if rng.random() < 0.55 else "TARDE"
    hora, minuto = rng.choice(HORAS_MANANA if franja == "MANANA" else HORAS_TARDE)
    fecha_hora = datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=LIMA)

    antelacion = min(60, int(rng.expovariate(1 / 12)) + 1)
    registro = (fecha_hora - timedelta(days=antelacion)).replace(
        hour=rng.randint(8, 18), minute=rng.choice((0, 15, 30, 45))
    )
    registro = min(registro, corte)  # una cita no puede haberse registrado en el futuro

    tipo = "NUEVO" if rng.random() < 0.30 else "CONTINUADOR"
    if tipo == "NUEVO":
        asistencias = inasistencias = 0
    else:
        asistencias = rng.randint(1, 12)
        inasistencias = min(asistencias, rng.choices([0, 1, 2, 3, 4], weights=[55, 25, 10, 6, 4])[0])
    canal = rng.choices(["WEB", "CALL_CENTER", "PRESENCIAL"], weights=[50, 30, 20])[0]

    registro_dict = {
        "id_cita_externa": f"CIT-{prefijo}-{numero:06d}",
        "paciente_anon_id": f"PAC-{prefijo}-{numero:05d}",
        "sede": "SAN_ISIDRO",
        "especialidad": especialidad,
        "medico": rng.choice(MEDICOS[especialidad]),
        "fecha_hora_cita": fecha_hora.isoformat(),
        "fecha_registro_cita": registro.isoformat(),
        "tipo_paciente": tipo,
        "canal_origen": canal,
        "inasistencias_previas": inasistencias,
        "reprogramaciones_prev": rng.choices([0, 1, 2], weights=[80, 15, 5])[0],
        "asistencias_previas": asistencias,
    }
    # Solo variables conocidas al momento de agendar (sin leakage) y ruido controlado.
    z = (
        0.06 * (antelacion - 12)
        + 0.55 * inasistencias
        + (0.7 if tipo == "NUEVO" else 0.0)
        + (0.25 if franja == "TARDE" else 0.0)
        + (0.35 if canal == "CALL_CENTER" else 0.0)
        + rng.gauss(0, 0.6)
    )
    return registro_dict, z


def generar_citas(
    historicas: int = 300,
    proximas: int = 60,
    semilla: int = 42,
    desde: date = date(2026, 10, 20),
    tasa_no_show: float = 0.16,
    con_invalidas: bool = True,
    prefijo: str = "SIM",
) -> list[dict]:
    rng = random.Random(semilla)
    corte = datetime(desde.year, desde.month, desde.day, tzinfo=LIMA) - timedelta(hours=6)
    registros: list[dict] = []

    # Históricas: ya tienen desenlace (ATENDIDA / NO_SHOW).
    base = [
        _registro_base(rng, n, _fecha_laborable(rng, date(2026, 4, 1), date(2026, 10, 14)), corte, prefijo)
        for n in range(1, historicas + 1)
    ]
    if base:
        intercepto = _calibrar([z for _, z in base], tasa_no_show)
        for registro, z in base:
            no_show = rng.random() < _sigmoide(z + intercepto)
            registros.append({**registro, "estado_actual": "NO_SHOW" if no_show else "ATENDIDA"})

    # Próximas: estados operativos, sin desenlace.
    for n in range(historicas + 1, historicas + proximas + 1):
        dia = _fecha_laborable(rng, desde, desde + timedelta(days=13))
        registro, _ = _registro_base(rng, n, dia, corte, prefijo)
        estado = rng.choices(
            ["RECIBIDA", "CONFIRMADA", "REPROGRAMADA", "CANCELADA"], weights=[70, 20, 5, 5]
        )[0]
        registros.append({**registro, "estado_actual": estado})

    # Filas inválidas a propósito, para demostrar las validaciones del importador.
    if con_invalidas and registros:
        molde = dict(registros[-1])
        posterior = (datetime.fromisoformat(molde["fecha_hora_cita"]) + timedelta(days=2)).isoformat()
        registros += [
            {**molde, "id_cita_externa": f"CIT-{prefijo}-INV-001", "sede": "MIRAFLORES"},
            {**molde, "id_cita_externa": f"CIT-{prefijo}-INV-002", "especialidad": "DERMATOLOGIA"},
            {**molde, "id_cita_externa": registros[0]["id_cita_externa"]},
            {**molde, "id_cita_externa": f"CIT-{prefijo}-INV-003", "fecha_registro_cita": posterior},
        ]
    return registros