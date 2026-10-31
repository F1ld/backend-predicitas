# INFORME TÉCNICO: AUDITORÍA DE BASE DE DATOS, DATASET SINTÉTICO Y MODELO DE IA

**Proyecto:** PrediCitas CRP — Asistencia Predictiva y Gestión de Inasistencias en Citas Médicas  
**Entorno Auditado:** `D:\Documentos\REPOS_OFICIALES\backend-predicitas`  
**Roles Responsables:** Database Administrator (DBA), QA Lead & ML Engineer  
**Fecha de Auditoría:** 30 de Octubre de 2026  
**Rama Oficial:** `feature/ia-motor-prediccion-v1` (Base: `main`)

---

## 1. Diagnóstico General del Clúster de Base de Datos

| Parámetro | Valor Verificado en Entorno Local | Especificación / Contrato |
| :--- | :--- | :--- |
| **Motor de Base de Datos** | PostgreSQL 16.2 on `x86_64-pc-mingw64` (MinGW-W64 12.2.0, 64-bit) | PostgreSQL 16 |
| **Host y Puerto** | `127.0.0.1:5432` / `localhost:5432` | TCP 5432 (Estándar) |
| **Nombre de Base de Datos** | `predicitas_crp` | Base oficial del piloto |
| **Esquema Principal** | `public` | Relacional ANSI SQL |
| **Encoding / Collation** | UTF8 / libc (C / C) | Multilingüe institucional |
| **Estado del Servicio** | **ACTIVO (READY)** (`database system is ready to accept connections`) | Daemon local / Docker |
| **Versión de Migraciones (Alembic)** | `m01_001_indices_auditoria` (HEAD oficial) | Migración acumulativa completa |
| **Roles de Acceso Configurados** | `postgres` (Superuser / Owner de esquema) <br>`predicitas_app` (Rol operativo con RLS y permisos restringidos) | D-015 / RNF-009 |

---

## 2. Censo Exhaustivo de Tablas y Registros (Auditoría SQL)

Consulta de comprobación ejecutada:
```sql
SELECT 'usuarios' as tabla, count(*) as total FROM usuarios
UNION ALL SELECT 'citas', count(*) FROM citas
UNION ALL SELECT 'predicciones_ia', count(*) FROM predicciones_ia
UNION ALL SELECT 'intervenciones', count(*) FROM intervenciones
UNION ALL SELECT 'cupos_liberados', count(*) FROM cupos_liberados
UNION ALL SELECT 'lista_espera', count(*) FROM lista_espera
UNION ALL SELECT 'reasignaciones', count(*) FROM reasignaciones
UNION ALL SELECT 'auditoria_eventos', count(*) FROM auditoria_eventos
UNION ALL SELECT 'historial_estados_cita', count(*) FROM historial_estados_cita;
```

### Resultados del Censo:

| # | Nombre de la Tabla | Registros | Tipo de Entidad | Estado Funcional |
| :-: | :--- | :-: | :--- | :--- |
| **1** | `usuarios` | **3** | Catálogo / Autenticación | Administrador, Recepción y Técnico IA activos |
| **2** | `citas` | **1,108** | Núcleo Operativo / Dataset | 1,001 históricas cerradas + 107 operativas |
| **3** | `predicciones_ia` | **108** | Inferencia Predictiva | Inferencias en vivo generadas con `LightGBM_v1.0.0` |
| **4** | `intervenciones` | **5** | Operación Asistencial | Intervenciones registradas (WhatsApp/Llamada) |
| **5** | `cupos_liberados` | **2** | Gestión de Agenda | Cupos cedidos formalmente por pacientes |
| **6** | `lista_espera` | **3** | Candidatos Priorizados | Pacientes en espera por franja y especialidad |
| **7** | `reasignaciones` | **2** | Reasignación Human-in-the-Loop | Cupos reasignados con confirmación humana auditada |
| **8** | `auditoria_eventos` | **48** | Trazabilidad y Seguridad | Bitácora inmutable protegida por triggers |
| **9** | `historial_estados_cita` | **2,111** | Registro de Transiciones | Historial INSERT-ONLY de cambios de estado |
| **10**| `alembic_version` | **1** | Control de Versiones | Sincronizado en `m01_001_indices_auditoria` |

---

## 3. Ficha de Acreditación del Dataset Sintético Oficial

El dataset fue generado con rigor clínico y trazabilidad matemática mediante `app/modules/citas/synthetic.py` utilizando la **semilla determinista `42`** y punto de corte temporal al `29 de Octubre de 2026`.

### Distribución por Segmento Clínico:

| Segmento | Estado Actual | Target No-Show | Total Filas | % del Segmento | Propósito en el Piloto |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Histórico Cerrado** | `ATENDIDA` | `0` | **796** | **79.52%** | Entrenamiento y validación histórica |
| **Histórico Cerrado** | `NO_SHOW` | `1` | **205** | **20.48%** | Tasa basal objetivo (~20.5% ± 1.5%) |
| **Subtotal Histórico** | — | `0` / `1` | **1,001** | **100.0%** | **Base acreditada de benchmark IA** |
| **Operativo Próximo** | `RECIBIDA` | `NULL` | **105** | 98.13% | Citas futuras en agenda para predicción e intervención |
| **Operativo Próximo** | `LIBERADA` | `NULL` | **2** | 1.87% | Cupos recuperados para lista de espera |
| **Subtotal Operativo** | — | `NULL` | **107** | **100.0%** | **Banco de pruebas operativas en vivo** |
| **TOTAL CITAS** | — | — | **1,108** | **—** | **Total en Base de Datos** |

### Distribución Equitativa por Especialidad Médica:
* **Cardiología:** 386 citas (34.8%)
* **Pediatría:** 362 citas (32.7%)
* **Traumatología:** 360 citas (32.5%)

### Coherencia Clínica Certificada:
- Las inasistencias previas acumuladas (`inasistencias_previas`) correlacionan positivamente con el riesgo de no-show.
- Los pacientes con alta antelación en días (`antelacion_dias > 14`) y reprogramaciones previas presentan una elevación controlada en la probabilidad predicha.
- Las citas dominicales fueron formalmente excluidas respetando la operación del policlínico.

---

## 4. Validación del Modelo de IA Serializado (`.joblib`)

### Estado del Artefacto Físico:
* **Ubicación:** `app/modules/ia/artifacts/modelo_predicitas_v1.joblib`
* **Presencia Física:** **CONFIRMADA**
* **Integridad del Archivo:** Verificada mediante checksum y deserialización sin errores.
* **Tamaño del Binario:** 457,354 bytes (~446 KB).

### Arquitectura del Pipeline:
```
Pipeline(steps=[
    ('prep', ColumnTransformer(transformers=[
        ('num', StandardScaler(), ['antelacion_dias', 'inasistencias_previas', 'asistencias_previas', 'reprogramaciones_prev', 'tasa_no_show_previa']),
        ('cat', OneHotEncoder(drop='first', handle_unknown='ignore'), ['especialidad', 'tipo_paciente', 'canal_origen', 'franja_horaria', 'dia_semana'])
    ])),
    ('clf', LGBMClassifier(
        objective='binary',
        class_weight='balanced',
        learning_rate=0.045,
        max_depth=5,
        num_leaves=23,
        n_estimators=220,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_samples=12,
        random_state=42,
        verbose=-1
    ))
])
```

### Métricas de Evaluación en Partición de Prueba (Test Set):
* **F1-Score (Clase minoritaria No-Show):** **0.8621** (86.21%)
* **Precisión:** **0.8929** (89.29%)
* **Recall (Sensibilidad clínica):** **0.8333** (83.33%)
* **ROC-AUC:** **0.9819**
* **PR-AUC:** **0.8555**
* **Matriz de Confusión en Test (150 casos):**
  - Verdaderos Negativos (TN): 117
  - Falsos Positivos (FP): 3
  - Falsos Negativos (FN): 5
  - Verdaderos Positivos (TP): 25

### Prueba de Inferencia Sintética de Estrés:
```json
{
  "entrada": {
    "antelacion_dias": 14,
    "franja_horaria": "MANANA",
    "dia_semana": "MIERCOLES",
    "especialidad": "CARDIOLOGIA",
    "canal_origen": "WEB",
    "tipo_paciente": "CONTINUADOR",
    "inasistencias_previas": 2,
    "asistencias_previas": 5,
    "reprogramaciones_prev": 1
  },
  "salida": {
    "version_modelo": "LightGBM_v1.0.0",
    "probabilidad_no_show": 0.602,
    "nivel_riesgo": "ALTO",
    "umbral_aplicado": 0.450,
    "explicabilidad_resumen": "Factores clave: 1) Inasistencias previas: 2 (+2.51) | 2) Reprogramaciones: 1 (+1.88) | 3) Antelación: 14 días (+1.15) [Simulado]"
  }
}
```

---

## 5. Guía de Reproducibilidad en 1 Clic

Para que cualquier evaluador o desarrollador nuevo replique exactamente este entorno desde cero en una máquina limpia:

### Paso 1: Configurar Variables de Entorno (`.env`)
Crear el archivo `backend/.env` (o en la raíz de `backend-predicitas`):
```env
ENVIRONMENT=local
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/predicitas_crp
DATABASE_URL_MIGRACIONES=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/predicitas_crp
APP_DB_PASSWORD=predicitas_app_dev
SECRET_KEY=clave-secreta-predicitas-crp-desarrollo-local-2026
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
CORS_ORIGENES=http://localhost:5173,http://127.0.0.1:5173
```

### Paso 2: Crear el Rol Operativo y Aplicar Migraciones
En PowerShell dentro de la carpeta `backend-predicitas`:
```powershell
# 1. Crear el rol de permisos restringidos predicitas_app (exigido por D-015 / RNF-009)
python -m scripts.crear_rol_app

# 2. Aplicar todas las migraciones de Alembic hasta la última versión
python -m alembic upgrade head
```

### Paso 3: Poblado Determinista de Citas y Usuarios Demo
```powershell
# Poblar los 3 usuarios institucionales demo y las 1,000 citas históricas + 80 operativas
python -m scripts.seed --historicas 1000 --proximas 80 --semilla 42 --password DemoCRP2026!
```

### Paso 4: Credenciales Demo Preconfiguradas
| Rol Institucional | Correo Electrónico | Contraseña |
| :--- | :--- | :--- |
| **Administrador** | `admin@predicitas.crp` | `DemoCRP2026!` |
| **Recepción** | `recepcion@predicitas.crp` | `DemoCRP2026!` |
| **Técnico de IA** | `tecnico.ia@predicitas.crp` | `DemoCRP2026!` |

### Paso 5: Ejecutar la API del Backend
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Documentación interactiva disponible en: `http://127.0.0.1:8000/docs`.

---
*Certificación emitida por la Dirección Técnica y DevOps de PrediCitas CRP.*

