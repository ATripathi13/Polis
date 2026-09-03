from fastapi import FastAPI

from api.router import api_router


app = FastAPI(
    title="Polis",
    description="Organizational Operating System",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "polis",
    }


app.include_router(api_router)