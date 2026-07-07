from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BrokerConnection:
    provider: str
    api_key: str
    secret_key: str
    paper: bool = True


class BrokerService:
    def __init__(self) -> None:
        self.connections: dict[int, BrokerConnection] = {}

    def connect(self, user_id: int, provider: str, api_key: str, secret_key: str, paper: bool = True) -> BrokerConnection:
        connection = BrokerConnection(provider=provider, api_key=api_key, secret_key=secret_key, paper=paper)
        self.connections[user_id] = connection
        return connection

    def get_connection(self, user_id: int) -> BrokerConnection | None:
        return self.connections.get(user_id)

    def sync_positions(self, user_id: int) -> dict[str, Any]:
        return {"user_id": user_id, "positions": [{"symbol": "AAPL", "quantity": 1, "price": 100.0}], "status": "synced"}

    def place_order(self, user_id: int, symbol: str, side: str, quantity: int, price: float) -> dict[str, Any]:
        return {"user_id": user_id, "symbol": symbol, "side": side, "quantity": quantity, "price": price, "status": "submitted"}


broker_service = BrokerService()
