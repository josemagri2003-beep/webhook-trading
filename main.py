"""
Servidor webhook para recibir alertas de TradingView
y exponerlas a la plataforma vía SSE (Server-Sent Events).

Deploy en Railway.app (gratis):
  1. Subir este archivo como main.py
  2. requirements.txt: fastapi uvicorn
  3. Comando: uvicorn main:app --host 0.0.0.0 --port $PORT
  4. La URL pública de Railway va en TradingView → Alert → Webhook URL
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio, json
from datetime import datetime
from collections import deque

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cola en memoria — últimas 100 alertas
alerts: deque = deque(maxlen=100)
# Clientes SSE conectados
clients: list = []


@app.post("/webhook")
async def receive_alert(request: Request):
    """TradingView POST con JSON de la alerta."""
    try:
        body = await request.json()
    except Exception:
        raw = await request.body()
        body = {"raw": raw.decode()}

    alert = {
        "id":     datetime.utcnow().isoformat(),
        "time":   datetime.utcnow().strftime("%H:%M:%S"),
        "ticker": body.get("ticker", "—"),
        "price":  body.get("price",  0),
        "level":  body.get("level",  body.get("raw", "—")),
        "pct":    body.get("pct",    "—"),
        "msg":    body.get("message", ""),
    }
    alerts.appendleft(alert)

    # Notificar a todos los clientes SSE
    dead = []
    for q in clients:
        try:
            await q.put(alert)
        except Exception:
            dead.append(q)
    for q in dead:
        clients.remove(q)

    return JSONResponse({"ok": True})


@app.get("/alerts")
async def get_alerts():
    """Devuelve las últimas alertas como JSON (para carga inicial)."""
    return list(alerts)


@app.get("/stream")
async def stream(request: Request):
    """SSE — la plataforma se conecta aquí para recibir alertas en tiempo real."""
    queue: asyncio.Queue = asyncio.Queue()
    clients.append(queue)

    async def event_generator():
        # Enviar alertas existentes al conectar
        for a in list(alerts)[:10]:
            yield f"data: {json.dumps(a)}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    alert = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(alert)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "alerts": len(alerts), "clients": len(clients)}
