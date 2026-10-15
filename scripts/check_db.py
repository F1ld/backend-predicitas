from sqlalchemy import create_engine, text

from app.core.config import get_settings


def main() -> None:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        print("Conexión OK")
        print("Versión :", conn.execute(text("select version()")).scalar())
        print("Zona    :", conn.execute(text("show timezone")).scalar())
        print("Ahora   :", conn.execute(text("select now()")).scalar())
        print("Usuario :", conn.execute(text("select current_user")).scalar())


if __name__ == "__main__":
    main()