import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DomChunkContextData:
    owner_token: str | None
    rq_job_id: str | None
    lane_id: str | None


_dom_chunk_ctx: ContextVar[DomChunkContextData | None] = ContextVar(
    "dom_chunk_ctx",
    default=None,
)


# Возвращает id текущей RQ-задачи или None вне worker.
def get_rq_job_id() -> str | None:
    try:
        from rq.job import get_current_job
    except ImportError:
        return None
    job = get_current_job()
    if job is None:
        return None
    return str(job.id)


# Читает контекст DOM chunk из contextvar (пустой, если вне chunk).
def get_dom_chunk_context() -> DomChunkContextData:
    ctx = _dom_chunk_ctx.get()
    if ctx is None:
        return DomChunkContextData(None, None, None)
    return ctx


# Устанавливает owner_token, rq_job_id и lane_id на время DOM chunk.
@contextmanager
def dom_chunk_context(
    owner_token: str | None,
    lane_id: str | None,
) -> Iterator[None]:
    data = DomChunkContextData(
        owner_token=owner_token,
        rq_job_id=get_rq_job_id(),
        lane_id=(lane_id or "").strip() or None,
    )
    token: Token[DomChunkContextData | None] = _dom_chunk_ctx.set(data)
    try:
        yield
    finally:
        _dom_chunk_ctx.reset(token)


# Пишет одну JSON-строку structured log в stdout worker.
def _log_event(event: str, payload: dict[str, Any]) -> None:
    body = {"event": event, **payload}
    logger.info("%s %s", event, json.dumps(body, ensure_ascii=False, default=str))


# Событие старта DOM chunk со списком product_id.
def log_dom_chunk_start(
    product_ids: list[int],
    owner_token: str | None,
    lane_id: str | None,
) -> None:
    ctx = get_dom_chunk_context()
    _log_event(
        "dom_chunk_start",
        {
            "rq_job_id": ctx.rq_job_id or get_rq_job_id(),
            "owner_token": owner_token,
            "product_ids": product_ids,
            "lane_id": (lane_id or ctx.lane_id or "").strip() or None,
        },
    )


# Событие обогащения одного SKU (dom_product).
def log_dom_product(payload: dict[str, Any]) -> None:
    _log_event("dom_product", payload)


# Событие результата import в БД для DOM SKU (dom_product_db).
def log_dom_product_db(
    product_id: int,
    db_outcome: str,
    supplier_price_committed: bool,
    supplier_price_eur: str | None = None,
) -> None:
    ctx = get_dom_chunk_context()
    body: dict[str, Any] = {
        "product_id": product_id,
        "rq_job_id": ctx.rq_job_id,
        "owner_token": ctx.owner_token,
        "lane_id": ctx.lane_id,
        "db_outcome": db_outcome,
        "supplier_price_committed": supplier_price_committed,
    }
    if supplier_price_eur is not None:
        body["supplier_price_eur"] = supplier_price_eur
    _log_event("dom_product_db", body)
