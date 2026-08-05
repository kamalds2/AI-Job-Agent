from fastapi import FastAPI

from app.database.database import Base, engine

# Import all models
from app.models import *

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Job Agent")


@app.get("/")
def home():
    return {
        "status": "Running",
        "project": "AI Job Agent"
    }