from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Local development model gateway", version="0.1.0")


class LiveResponse(BaseModel):
    status: Literal["alive"]


@app.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    """Local deterministic gateway contract; replace its URL for a real model runtime."""
    return LiveResponse(status="alive")
