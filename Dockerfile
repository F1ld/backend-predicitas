# API PrediCitas CRP · Python 3.12 (D-002)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # /app no es escribible por el usuario de la API: la cobertura y la caché de pytest van a /tmp.
    COVERAGE_FILE=/tmp/.coverage \
    PYTEST_ADDOPTS="-o cache_dir=/tmp/.pytest_cache"

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Usuario sin privilegios: el proceso de la API no corre como root.
RUN useradd --create-home --uid 1000 predicitas
COPY --chown=predicitas:predicitas . .
USER predicitas

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
