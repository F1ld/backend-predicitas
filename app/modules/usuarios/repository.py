from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.auth.models import Usuario
from app.modules.usuarios.schemas import FiltrosUsuarios


def listar(db: Session, f: FiltrosUsuarios) -> tuple[int, list[Usuario]]:
    consulta = select(Usuario)
    if f.q:
        texto = f.q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        patron = f"%{texto}%"
        consulta = consulta.where(or_(func.lower(Usuario.nombre_completo).like(patron, escape="\\"),
                                      func.lower(Usuario.correo_institucional).like(patron, escape="\\")))
    if f.rol:
        consulta = consulta.where(Usuario.rol == f.rol)
    if f.activo is not None:
        consulta = consulta.where(Usuario.activo == f.activo)
    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    items = db.scalars(consulta.order_by(Usuario.nombre_completo, Usuario.id_usuario)
                       .limit(f.limite).offset(f.desplazamiento))
    return total, list(items)


def por_id_para_actualizar(db: Session, id_usuario: int) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.id_usuario == id_usuario).with_for_update())


def otros_administradores_activos(db: Session, excepto: int) -> int:
    """Cuenta los ADMINISTRADOR activos distintos de `excepto`, bloqueando sus filas para
    que dos operaciones simultáneas no dejen el sistema sin administrador."""
    filas = db.scalars(
        select(Usuario.id_usuario)
        .where(Usuario.rol == "ADMINISTRADOR", Usuario.activo.is_(True), Usuario.id_usuario != excepto)
        .with_for_update()
    )
    return len(list(filas))
