from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    email: str = Field(min_length=4, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    email_or_username: str = Field(min_length=3)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    created_at: str
    is_active: bool
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str


class StatusResponse(BaseModel):
    mode: str
    preset: str
    crypto: int
    stocks: int
    forex: int
    commodities: int
    authenticated: bool = True


class TradeSignalRequest(BaseModel):
    symbol: str
    market: str = "crypto"


class TradeSignalResponse(BaseModel):
    symbol: str
    direction: str
    score: float
    market: str
    message: str


class BacktestRequest(BaseModel):
    symbol: str
    start: str
    end: str
    market: str = "crypto"


class BacktestResponse(BaseModel):
    message: str
    symbol: str
    started_at: str


class WatchlistItemCreate(BaseModel):
    symbol: str
    market: str = "crypto"
    notes: str | None = None


class WatchlistItemOut(BaseModel):
    id: int
    symbol: str
    market: str
    notes: str | None = None
    created_at: str


class AlertCreate(BaseModel):
    symbol: str
    market: str = "crypto"
    alert_type: str
    value: float
    description: str | None = None


class AlertOut(BaseModel):
    id: int
    symbol: str
    market: str
    alert_type: str
    value: float
    description: str | None = None
    created_at: str
    active: bool


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = None


class TeamOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    owner_id: int
    created_at: str


class TeamMemberOut(BaseModel):
    id: int
    username: str
    email: str
    role: str


class SubscriptionCreate(BaseModel):
    plan: str = Field(default="pro")
    billing_period: str = Field(default="monthly")


class SubscriptionOut(BaseModel):
    id: int
    plan: str
    status: str
    billing_period: str
    created_at: str


class InvoiceOut(BaseModel):
    id: int
    subscription_id: int
    amount: float
    currency: str
    status: str
    created_at: str


class StrategyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    market: str = "crypto"
    is_public: bool = False


class StrategyCloneRequest(BaseModel):
    name: str | None = None


class StrategyOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    market: str
    is_public: bool
    owner_id: int
    created_at: str
    updated_at: str


class AssistantQueryRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=500)


class AssistantResponse(BaseModel):
    summary: str
    suggested_actions: list[str]


class AutomationRuleCreate(BaseModel):
    name: str
    event_type: str
    action: str
    config: dict[str, Any]


class AutomationRuleOut(BaseModel):
    id: int
    name: str
    event_type: str
    action: str
    config: dict[str, Any]
    created_at: str


class AuditLogOut(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: int | None = None
    details: str | None = None
    created_at: str


class AnalyticsSummaryResponse(BaseModel):
    user_id: int
    total_orders: int
    active_alerts: int
    journal_entries: int
    open_positions: float
    estimated_exposure: float
    summary: str


class BrokerConnectRequest(BaseModel):
    api_key: str
    secret_key: str
    paper: bool = True


class BrokerConnectionOut(BaseModel):
    provider: str
    api_key: str
    secret_key: str
    paper: bool


class ExecutionCreate(BaseModel):
    symbol: str
    side: str
    quantity: int
    price: float


class ExecutionOut(BaseModel):
    id: int
    symbol: str
    side: str
    quantity: int
    price: float
    status: str
    created_at: str


class PositionOut(BaseModel):
    id: int
    symbol: str
    quantity: int
    price: float
    created_at: str


class ReconciliationOut(BaseModel):
    status: str
    positions: list[dict[str, Any]]


class BillingCheckoutRequest(BaseModel):
    plan: str
    currency: str = "USD"


class BillingCheckoutResponse(BaseModel):
    id: int
    plan: str
    currency: str
    status: str
    created_at: str


class BillingWebhookRequest(BaseModel):
    provider: str
    event: str
    payload: dict[str, Any]


class BillingWebhookResponse(BaseModel):
    status: str
    provider: str
    event: str


class AlpacaOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: int
    order_type: str = "market"


class AlpacaOrderResponse(BaseModel):
    provider: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    status: str
    paper: bool
    endpoint: str


class RiskLimitCreate(BaseModel):
    max_drawdown: float = Field(default=0.2)
    max_position_size: float = Field(default=0.25)
    max_daily_loss: float = Field(default=0.05)


class RiskLimitOut(BaseModel):
    id: int
    max_drawdown: float
    max_position_size: float
    max_daily_loss: float
    created_at: str


class RiskScanResponse(BaseModel):
    status: str
    open_positions: int
    active_orders: int
    max_drawdown: float
    max_position_size: float
    max_daily_loss: float


class VerifyEmailRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class OrderCreate(BaseModel):
    symbol: str
    market: str = "crypto"
    side: str
    quantity: float
    price: float | None = None
    notes: str | None = None


class OrderOut(BaseModel):
    id: int
    symbol: str
    market: str
    side: str
    quantity: float
    price: float | None = None
    status: str
    notes: str | None = None
    created_at: str
    updated_at: str


class JournalEntryCreate(BaseModel):
    title: str
    entry_type: str = "note"
    content: str
    tags: str | None = None


class JournalEntryOut(BaseModel):
    id: int
    title: str
    entry_type: str
    content: str
    tags: str | None = None
    created_at: str


class NotificationOut(BaseModel):
    id: int
    title: str
    message: str
    kind: str
    created_at: str
    read_flag: bool


class WebhookCreate(BaseModel):
    name: str
    url: str
    event_type: str = "signal"


class WebhookOut(BaseModel):
    id: int
    name: str
    url: str
    event_type: str
    active: bool
    created_at: str


class AdminStatsResponse(BaseModel):
    users: int
    active_alerts: int
    orders: int
    journal_entries: int
    notifications: int
    webhooks: int
