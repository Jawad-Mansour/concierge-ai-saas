# Owner: Jana
# PLACEHOLDER — minimal stub so the container boots. Owner: overwrite
# this when implementing your slice. The "stub": True field is the
# signal that this is not real yet.
from fastapi import FastAPI

app = FastAPI(title="Concierge modelserver")

@app.get("/health")
def health():
    return {"status": "ok", "service": "modelserver", "stub": True}
