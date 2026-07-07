from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

try:
    from api.core.auth import get_current_user
    from api.services.streaming import market_stream
except ImportError:  # pragma: no cover - fallback for direct script execution
    from core.auth import get_current_user
    from services.streaming import market_stream

router = APIRouter(prefix="/ws", tags=["Streaming"])


@router.websocket("/market")
async def market_socket(websocket: WebSocket, token: Optional[str] = None):
    if not token:
        await websocket.close(code=1008)
        return
    try:
        get_current_user(token)
    except ValueError:
        await websocket.close(code=1008)
        return

    await market_stream.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        market_stream.disconnect(websocket)
