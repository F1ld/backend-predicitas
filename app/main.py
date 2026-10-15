from fastapi import FastAPI

app = FastAPI(title="PrediCitas API", version="0.1.0")


@app.get("/health", tags=["sistema"])
def health():
    return {"estado": "ok"}