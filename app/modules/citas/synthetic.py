"""Generador de citas clínicas sintéticas reproducibles con semilla fija (Entregable E-04).

Los resultados son SIMULADOS (RF-056 / RN16): el prefijo SIM en los identificadores lo deja explícito.
La tasa de no-show (~20%, rango 18%–22%) es un supuesto de modelado para la Sede San Isidro
(Cardiología, Traumatología y Pediatría), no un dato real de la Clínica Ricardo Palma (RF-033).
"""
import math
import random
from datetime import date, datetime, timedelta

from app.modules.citas.reglas import LIMA, derivar_variables

MEDICOS = {
    "CARDIOLOGIA": ["Dr. Ramírez", "Dra. Quispe", "Dr. Valdivia"],
    "TRAUMATOLOGIA": ["Dra. Vargas", "Dr. Salcedo", "Dr. Paredes"],
    "PEDIATRIA": ["Dr. Mendoza", "Dra. Morales", "Dra. Cárdenas"],
}
HORAS_MANANA = [(h, m) for h in range(8, 13) for m in (0, 30)]   # 08:00 a 12:30
HORAS_TARDE = [(h, m) for h in range(14, 19) for m in (0, 30)]   # 14:00 a 18:30

PESOS_CANAL = {"PRESENCIAL": -0.65, "WEB": 0.25, "CALL_CENTER": 0.60}
PESOS_ESPECIALIDAD = {"CARDIOLOGIA": -0.30, "PEDIATRIA": 0.15, "TRAUMATOLOGIA": 0.35}
PESOS_DIA = {
    "LUNES": -0.15,
    "MARTES": 0.00,
    "MIERCOLES": 0.00,
    "JUEVES": 0.05,
    "VIERNES": 0.35,
    "SABADO": -0.25,
}


def _sigmoide(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def _calibrar(zs: list[float], objetivo: float) -> float:
    """Busca el intercepto beta_0 que lleva la tasa media de no-show al objetivo (bisección)."""
    bajo, alto = -25.0, 25.0
    for _ in range(80):
        medio = (bajo + alto) / 2.0
        tasa = sum(_sigmoide(z + medio) for z in zs) / len(zs)
        if tasa < objetivo:
            bajo = medio
        else:
            alto = medio
    return (bajo + alto) / 2.0


def _fecha_laborable(rng: random.Random, inicio: date, fin: date) -> date:
    """Selecciona un día laborable entre lunes y sábado (el piloto no atiende domingos)."""
    dias_rango = max(0, (fin - inicio).days)
    while True:
        dia = inicio + timedelta(days=rng.randint(0, dias_rango))
        if dia.weekday() != 6:
            return dia


def _muestrear_antelacion(rng: random.Random) -> int:
    """Simula tiempos reales de agendamiento entre 0 y 60 días."""
    u = rng.random()
    if u < 0.45:
        return rng.randint(0, 7)      # Reservas cercanas (alta adherencia)
    if u < 0.80:
        return rng.randint(8, 21)     # Reservas de mediano plazo
    return rng.randint(22, 60)        # Reservas lejanas (mayor probabilidad de olvido)


def _muestrear_historial_paciente(rng: random.Random, tipo_paciente: str) -> tuple[int, int, int]:
    """Garantiza coherencia clínica estricta según el tipo de paciente (NUEVO vs CONTINUADOR)."""
    if tipo_paciente == "NUEVO":
        # Invariante clínica: un paciente nuevo jamás tiene asistencias ni inasistencias previas.
        asistencias = 0
        inasistencias = 0
        reprogramaciones = rng.choices([0, 1, 2], weights=[82, 13, 5])[0]
        return asistencias, inasistencias, reprogramaciones

    # Paciente CONTINUADOR: posee historial previo coherente con su propensión individual.
    total_previas = rng.randint(1, 14)
    perfil_incumplidor = rng.random() < 0.24
    if perfil_incumplidor:
        tasa_individual = rng.uniform(0.35, 0.85)
        inasistencias = max(1, min(total_previas, round(total_previas * tasa_individual)))
        reprogramaciones = rng.choices([0, 1, 2, 3], weights=[35, 35, 20, 10])[0]
    else:
        tasa_individual = rng.uniform(0.0, 0.18)
        inasistencias = min(total_previas - 1, round(total_previas * tasa_individual))
        reprogramaciones = rng.choices([0, 1, 2], weights=[85, 12, 3])[0]

    asistencias = max(0, total_previas - inasistencias)
    if asistencias == 0 and inasistencias == 0:
        asistencias = 1
    return asistencias, inasistencias, reprogramaciones


def _calcular_logit_clinico(
    *,
    antelacion: int,
    tipo_paciente: str,
    canal: str,
    franja: str,
    especialidad: str,
    dia_semana: str,
    asistencias: int,
    inasistencias: int,
    reprogramaciones: int,
    rng: random.Random,
) -> float:
    """Ecuación logística con efectos principales, interacciones clínicas no lineales y ruido controlado."""
    tasa_previa = inasistencias / (asistencias + inasistencias + 1.0)

    # 1. Efectos principales lineales
    z_lineal = (
        0.085 * (antelacion - 14)
        + 1.35 * inasistencias
        - 0.28 * asistencias
        + 2.40 * tasa_previa
        + 0.85 * reprogramaciones
        + (0.90 if tipo_paciente == "NUEVO" else -0.20)
        + PESOS_CANAL[canal]
        + (0.55 if franja == "TARDE" else -0.15)
        + PESOS_ESPECIALIDAD[especialidad]
        + PESOS_DIA.get(dia_semana, 0.0)
    )

    # 2. Interacciones clínicas no lineales (capturadas por árboles LightGBM)
    z_interacciones = 0.0
    if inasistencias >= 2 and antelacion >= 14:
        z_interacciones += 2.60
    if tipo_paciente == "NUEVO" and antelacion >= 20 and canal in ("CALL_CENTER", "WEB"):
        z_interacciones += 2.35
    if reprogramaciones >= 1 and (inasistencias >= 1 or antelacion >= 18):
        z_interacciones += 1.95
    if franja == "TARDE" and canal == "CALL_CENTER" and antelacion >= 15:
        z_interacciones += 1.50
    if (
        tipo_paciente == "CONTINUADOR"
        and asistencias >= 3
        and inasistencias == 0
        and reprogramaciones == 0
        and antelacion <= 14
    ):
        z_interacciones -= 2.50

    # 3. Ruido gaussiano controlado (RF-034)
    ruido = rng.gauss(0.0, 0.42)
    return z_lineal + z_interacciones + ruido


def _registro_base(rng: random.Random, numero: int, dia: date, corte: datetime, prefijo: str) -> tuple[dict, float]:
    especialidad = rng.choice(list(MEDICOS))
    franja = "MANANA" if rng.random() < 0.55 else "TARDE"
    hora, minuto = rng.choice(HORAS_MANANA if franja == "MANANA" else HORAS_TARDE)
    fecha_hora = datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=LIMA)

    antelacion_objetivo = _muestrear_antelacion(rng)
    registro = (fecha_hora - timedelta(days=antelacion_objetivo)).replace(
        hour=rng.randint(8, 18), minute=rng.choice((0, 15, 30, 45))
    )
    registro = min(registro, corte, fecha_hora - timedelta(minutes=30))

    derivadas = derivar_variables(fecha_hora, registro)
    antelacion_real = min(60, derivadas["antelacion_dias"])
    if derivadas["antelacion_dias"] > 60:
        registro = (fecha_hora - timedelta(days=60)).replace(hour=10, minute=0)
        derivadas = derivar_variables(fecha_hora, registro)
        antelacion_real = derivadas["antelacion_dias"]

    tipo = "NUEVO" if rng.random() < 0.30 else "CONTINUADOR"
    asistencias, inasistencias, reprogramaciones = _muestrear_historial_paciente(rng, tipo)
    canal = rng.choices(["WEB", "CALL_CENTER", "PRESENCIAL"], weights=[50, 30, 20])[0]

    # Pacientes continuadores comparten IDs dentro de una cohorte simulada de 650 pacientes
    id_pac_num = numero if tipo == "NUEVO" else rng.randint(1, 650)

    registro_dict = {
        "id_cita_externa": f"CIT-{prefijo}-{numero:06d}",
        "paciente_anon_id": f"PAC-{prefijo}-{id_pac_num:05d}",
        "sede": "SAN_ISIDRO",
        "especialidad": especialidad,
        "medico": rng.choice(MEDICOS[especialidad]),
        "fecha_hora_cita": fecha_hora.isoformat(),
        "fecha_registro_cita": registro.isoformat(),
        "antelacion_dias": antelacion_real,
        "tipo_paciente": tipo,
        "canal_origen": canal,
        "franja_horaria": derivadas["franja_horaria"],
        "dia_semana": derivadas["dia_semana"],
        "inasistencias_previas": inasistencias,
        "reprogramaciones_prev": reprogramaciones,
        "asistencias_previas": asistencias,
    }

    z = _calcular_logit_clinico(
        antelacion=antelacion_real,
        tipo_paciente=tipo,
        canal=canal,
        franja=derivadas["franja_horaria"],
        especialidad=especialidad,
        dia_semana=derivadas["dia_semana"],
        asistencias=asistencias,
        inasistencias=inasistencias,
        reprogramaciones=reprogramaciones,
        rng=rng,
    )
    return registro_dict, z


def generar_citas(
    historicas: int = 1000,
    proximas: int = 80,
    semilla: int = 42,
    desde: date = date(2026, 10, 29),
    tasa_no_show: float = 0.20,
    con_invalidas: bool = True,
    prefijo: str = "SIM",
) -> list[dict]:
    """Genera el dataset sintético reproducible (1,000 históricas + 80 próximas por defecto).

    - Históricas: estado_actual en ('ATENDIDA', 'NO_SHOW') y target_no_show en (0, 1),
      con tasa global de no-show calibrada entre 18% y 22% (por defecto 20%).
    - Próximas: fecha futura en los próximos 14 días, estado_actual = 'RECIBIDA' y
      target_no_show = None (NULL estricto).
    """
    rng = random.Random(semilla)
    corte = datetime(desde.year, desde.month, desde.day, tzinfo=LIMA) - timedelta(hours=6)
    inicio_historico = desde - timedelta(days=200)
    fin_historico = desde - timedelta(days=2)
    registros: list[dict] = []

    # 1. Citas históricas cerradas (con desenlace ATENDIDA / NO_SHOW y target 0 / 1)
    base = [
        _registro_base(rng, n, _fecha_laborable(rng, inicio_historico, fin_historico), corte, prefijo)
        for n in range(1, historicas + 1)
    ]
    if base:
        intercepto = _calibrar([z for _, z in base], tasa_no_show)
        for registro, z in base:
            prob = _sigmoide(z + intercepto)
            no_show = rng.random() < prob
            registros.append({
                **registro,
                "estado_actual": "NO_SHOW" if no_show else "ATENDIDA",
                "target_no_show": 1 if no_show else 0,
            })

    # 2. Citas próximas operativas (próximos 14 días, estado RECIBIDA y target_no_show = None)
    for n in range(historicas + 1, historicas + proximas + 1):
        dia = _fecha_laborable(rng, desde, desde + timedelta(days=13))
        registro, _ = _registro_base(rng, n, dia, corte, prefijo)
        registros.append({
            **registro,
            "estado_actual": "RECIBIDA",
            "target_no_show": None,
        })

    # 3. Filas inválidas opcionales para pruebas del validador de importación (RF-011, RF-012, RF-013)
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
