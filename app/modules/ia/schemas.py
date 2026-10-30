from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class PrediccionIAOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_prediccion: int
    id_cita: int
    version_modelo: str
    probabilidad_no_show: Decimal
    nivel_riesgo: str
    umbral_aplicado: Decimal
    features_snapshot: dict[str, Any]
    explicabilidad_resumen: str | None
    fecha_hora_inferencia: datetime
    es_simulacion: bool = True
    rotulo_etico: str = "Resultado simulado — Dataset sintético acreditado (RF-056)"


class ResultadoPrediccionLoteOut(BaseModel):
    version_modelo: str
    evaluadas: int
    riesgo_alto: int
    riesgo_medio: int
    riesgo_bajo: int
    predicciones: list[PrediccionIAOut]


class MatrizConfusionOut(BaseModel):
    tn: int
    fp: int
    fn: int
    tp: int


class BloqueMetricasOut(BaseModel):
    umbral: float
    f1_score: float
    precision: float
    recall: float
    roc_auc: float
    pr_auc: float
    matriz_confusion: MatrizConfusionOut


class MetricasModeloOut(BaseModel):
    version_modelo: str
    algoritmo: str
    semilla: int
    fecha_entrenamiento: str
    es_simulacion: bool
    rotulo_etico: str
    umbral_alto: float
    umbral_medio: float
    cumple_meta_f1_82: bool
    metricas_test: BloqueMetricasOut
    metricas_val: BloqueMetricasOut
    metricas_baseline_test: BloqueMetricasOut
    auditoria_equidad: dict[str, Any]
    importancia_global_variables: list[dict[str, Any]]


class DatasetResumenOut(BaseModel):
    version_dataset: str
    semilla: int
    total_historicas: int
    atendidas_historicas: int
    no_show_historicas: int
    proximas_operativas_bd: int
    train_size: int
    val_size: int
    test_size: int
    tasa_no_show_global: float
    tasa_no_show_train: float
    tasa_no_show_val: float
    tasa_no_show_test: float
    features_autorizadas: list[str]
    control_leakage: dict[str, Any]
    rotulo_etico: str

