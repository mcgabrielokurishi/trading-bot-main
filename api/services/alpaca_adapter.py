from __future__ import annotations

import json
import os
from typing import Any

try:
    from api.services.broker import broker_service
except ImportError:  # pragma: no cover
    from services.broker import broker_service


class AlpacaAdapter:
    def __init__(self) -> None:
        self.provider = "alpaca"
        self.base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    def connect(self, api_key: str, secret_key: str, paper: bool = True) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "paper": paper,
            "api_key": api_key,
            "secret_key": secret_key,
            "base_url": self.base_url,
            "status": "connected",
        }

    def submit_order(self, user_id: int, symbol: str, side: str, quantity: int, order_type: str = "market") -> dict[str, Any]:
        connection = broker_service.get_connection(user_id)
        if connection is None:
            return {"status": "not_connected", "provider": self.provider}
        status = "paper_ready" if getattr(connection, "paper", True) else "submitted"
        return {
            "provider": self.provider,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "status": status,
            "paper": getattr(connection, "paper", True),
            "endpoint": self.base_url,
        }


alpaca_adapter = AlpacaAdapter()
