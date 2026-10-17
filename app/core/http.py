from fastapi import Request


def ip_cliente(request: Request) -> str:
    """La columna direccion_ip es NOT NULL; si no hay cliente, se usa un valor neutro."""
    return request.client.host if request.client else "0.0.0.0"