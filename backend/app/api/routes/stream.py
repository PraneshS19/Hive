import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except (WebSocketDisconnect, RuntimeError, OSError, ValueError, TypeError):
                self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
            # Echo heartbeat or client commands
            await websocket.send_json({"type": "pong", "time": datetime.now(UTC).isoformat()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.get("/events/stream")
async def sse_event_stream():
    """Server-Sent Events stream for live simulation events."""
    async def event_generator():
        while True:
            data = json.dumps({
                "type": "heartbeat",
                "timestamp": datetime.now(UTC).isoformat()
            })
            yield f"data: {data}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
