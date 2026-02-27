from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio
from apps.api.routers import instruments, ticks, backtests, simulation, strategy, ops
from apps.api.socket_instance import sio

# Initialize FastAPI
app = FastAPI(title="Trade Bot API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Socket.IO
# sio is imported from apps.api.socket_instance
socket_app = socketio.ASGIApp(sio, app, socketio_path='/simulation-socket')

# Routers
app.include_router(instruments.router)
app.include_router(ticks.router)
app.include_router(backtests.router)
app.include_router(simulation.registry_router) if hasattr(simulation, 'registry_router') else app.include_router(simulation.router)
app.include_router(strategy.router)
app.include_router(ops.router)

@app.get("/api/status")
async def status():
    return {"status": "ok", "version": "v2"}

# Socket Events (Placeholder for now)
@sio.event
async def connect(sid, environ):
    print(f"Socket Connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Socket Disconnected: {sid}")

# To run: uvicorn apps.api.main:socket_app --reload
