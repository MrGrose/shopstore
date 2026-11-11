from pydantic import BaseModel, Field


class ScraperRunStatusSchema(BaseModel):
    # Текущий этап pipeline: idle | import | finalize | dom
    phase: str = "idle"
    import_chunk_size: int = Field(10, ge=1)
    import_queue_pending: int = Field(0, ge=0)
    import_queue_running: int = Field(0, ge=0)
    import_queue_failed: int = Field(0, ge=0)
    finalize_queue_pending: int = Field(0, ge=0)
    finalize_queue_running: int = Field(0, ge=0)
    finalize_queue_failed: int = Field(0, ge=0)
    dom_queue_pending: int = Field(0, ge=0)
    dom_queue_running: int = Field(0, ge=0)
    dom_queue_failed: int = Field(0, ge=0)
    dom_chunks_remaining: int = Field(
        0,
        ge=0,
        description="dom_queue_pending + dom_queue_running",
    )
    estimated_dom_products_remaining: int = Field(
        0,
        ge=0,
        description="dom_chunks_remaining × import_chunk_size (оценка)",
    )
    dom_queue_max_pending: int = Field(
        60,
        ge=1,
        description="Порог pending catalog_dom для rolling refresh",
    )
    dom_queue_overloaded: bool = Field(
        False,
        description="pending > dom_queue_max_pending — новые rolling jobs не ставятся",
    )
