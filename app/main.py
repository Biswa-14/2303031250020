from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Affordmed Backend", version="1.0.0")


class Item(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    available: bool = True


@app.get("/")
def read_root() -> dict:
    return {"message": "FastAPI backend is running"}


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.get("/items")
def list_items() -> list[dict]:
    return [
        {"id": 1, "name": "Sample item", "price": 10.0, "available": True}
    ]


@app.post("/items", status_code=201)
def create_item(item: Item) -> dict:
    return {"message": "Item created", "item": item.model_dump()}
