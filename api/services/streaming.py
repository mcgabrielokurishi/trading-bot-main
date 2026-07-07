import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket


class MarketStreamManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        message = json.dumps(payload)
        dead: list[WebSocket] = []
        for websocket in list(self.connections):
            try:
                await websocket.send_text(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)


market_stream = MarketStreamManager()


async def stream_updates() -> None:
    while True:
        await market_stream.broadcast({
            "type": "market_update",
            "timestamp": time.time(),
            "symbols": ["BTC/USDT", "ETH/USDT", "AAPL"],
        })
        await asyncio.sleep(5)
