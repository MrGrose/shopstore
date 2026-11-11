import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.jobs import translation_job as translation_job_mod
from src.jobs.translation_job import (
    _translate_product,
    dispatch_pending_translations,
    run_translate_product,
)
from src.services.catalog.importing.helpers import hash_text
from src.utils.translate_descriptions import (
    translate_plain_text_to_ru,
    translation_backfill_skip_reason,
)

_EN_RAW = (
    "Explore the Versatility of the adidas Sports Bag Designed for the sport "
    "enthusiast who needs space for shoes, rackets and training gear every day."
)
_VALID_RU = (
    "Кроссовки Nike Court Slam для тенниса с амортизацией Zoom Air "
    "и верхом из кожи adidas. Артикул SKU-12345."
)
_NEW_RAW = _EN_RAW + " Extra colorway details for the updated collection."


# Собирает async session maker, где add() синхронный.
def _session_maker(session):
    session.add = MagicMock()
    maker = MagicMock()
    maker.return_value.__aenter__ = AsyncMock(return_value=session)
    maker.return_value.__aexit__ = AsyncMock(return_value=None)
    return maker


# Собирает MagicMock продукта для worker/dispatcher unit-тестов.
def _product(
    *,
    product_id: int = 7,
    raw: str = _EN_RAW,
    ru: str | None = None,
    is_active: bool = True,
    translated_hash: str | None = None,
):
    product = MagicMock()
    product.id = product_id
    product.description_raw = raw
    product.description_ru = ru
    product.description_hash = hash_text(raw)
    product.description_translated_hash = translated_hash
    product.is_active = is_active
    return product


@pytest.mark.asyncio
async def test_worker_skips_when_ru_matches_current_hash(monkeypatch):
    product = _product(ru=_VALID_RU, translated_hash=hash_text(_EN_RAW))
    session = AsyncMock()
    session.get = AsyncMock(return_value=product)
    session.commit = AsyncMock()
    monkeypatch.setattr(
        "src.jobs.translation_job.async_session_maker",
        _session_maker(session),
    )
    translated = AsyncMock(side_effect=AssertionError("must not translate"))
    monkeypatch.setattr(
        "src.jobs.translation_job.translate_description_html",
        translated,
    )
    result = await _translate_product(7)
    assert result["status"] == "skip"
    assert result["reason"] == "valid_ru"


@pytest.mark.asyncio
async def test_worker_translates_outdated_valid_ru(monkeypatch):
    old_hash = hash_text(_EN_RAW)
    product = _product(
        raw=_NEW_RAW,
        ru=_VALID_RU,
        translated_hash=old_hash,
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=product)
    session.commit = AsyncMock()
    monkeypatch.setattr(
        "src.jobs.translation_job.async_session_maker",
        _session_maker(session),
    )
    monkeypatch.setattr(
        "src.jobs.translation_job._sleep_range",
        lambda: (0.0, 0.0),
    )
    monkeypatch.setattr(
        "src.jobs.translation_job.translate_description_html",
        lambda *args, **kwargs: _VALID_RU,
    )
    result = await _translate_product(7)
    assert result["status"] == "translated"
    assert product.description_ru == _VALID_RU
    assert product.description_translated_hash == hash_text(_NEW_RAW)
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_worker_preserves_valid_ru_on_failure(monkeypatch):
    old_hash = hash_text(_EN_RAW)
    product = _product(
        raw=_NEW_RAW,
        ru=_VALID_RU,
        translated_hash=old_hash,
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=product)
    session.rollback = AsyncMock()
    monkeypatch.setattr(
        "src.jobs.translation_job.async_session_maker",
        _session_maker(session),
    )
    monkeypatch.setattr(
        "src.jobs.translation_job._sleep_range",
        lambda: (0.0, 0.0),
    )
    monkeypatch.setattr(
        "src.jobs.translation_job.translate_description_html",
        lambda *args, **kwargs: None,
    )
    result = await _translate_product(7)
    assert result["status"] == "failed_preserved"
    assert product.description_ru == _VALID_RU
    session.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_worker_timeout_does_not_raise(monkeypatch):
    product = _product(ru=None)
    session = AsyncMock()
    session.get = AsyncMock(return_value=product)
    session.commit = AsyncMock()
    monkeypatch.setattr(
        "src.jobs.translation_job.async_session_maker",
        _session_maker(session),
    )
    monkeypatch.setattr(
        "src.jobs.translation_job._sleep_range",
        lambda: (0.0, 0.0),
    )

    def _boom(*args, **kwargs):
        raise TimeoutError("LibreTranslate timeout")

    monkeypatch.setattr(
        "src.jobs.translation_job.translate_description_html",
        _boom,
    )
    result = await _translate_product(7)
    assert result["status"] == "failed_cleared"


@pytest.mark.asyncio
async def test_dispatcher_enqueues_without_libretranslate(monkeypatch):
    product = _product(product_id=11, ru=None)
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=MagicMock(all=lambda: [product]))
    session.rollback = AsyncMock()
    monkeypatch.setattr(
        "src.jobs.translation_job.async_session_maker",
        _session_maker(session),
    )
    enqueued: list[int] = []

    def _enqueue(product_id: int, raw_hash: str | None = None):
        enqueued.append(product_id)
        return MagicMock(id="job-1")

    monkeypatch.setattr(
        "src.jobs.translation_job.enqueue_translation_product",
        _enqueue,
    )
    monkeypatch.setattr(
        "src.jobs.translation_job.translate_description_html",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dispatcher must not translate")
        ),
    )
    stats = await dispatch_pending_translations(dry_run=False, force=False, limit=10)
    assert stats["enqueued"] == 1
    assert enqueued == [11]


@pytest.mark.asyncio
async def test_dispatcher_skips_current_ru(monkeypatch):
    product = _product(
        ru=_VALID_RU,
        translated_hash=hash_text(_EN_RAW),
    )
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=MagicMock(all=lambda: [product]))
    session.rollback = AsyncMock()
    monkeypatch.setattr(
        "src.jobs.translation_job.async_session_maker",
        _session_maker(session),
    )
    monkeypatch.setattr(
        "src.jobs.translation_job.enqueue_translation_product",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not enqueue")
        ),
    )
    stats = await dispatch_pending_translations(dry_run=False, force=False, limit=10)
    assert stats["enqueued"] == 0
    assert stats["skipped"]["valid_ru"] == 1


def test_skip_reason_outdated_valid_ru():
    raw_hash = hash_text(_NEW_RAW)
    assert (
        translation_backfill_skip_reason(
            _NEW_RAW,
            _VALID_RU,
            True,
            raw_hash=raw_hash,
            translated_hash=hash_text(_EN_RAW),
        )
        is None
    )


def test_dhl_plain_text_helper_not_used_by_translation_job():
    source = inspect.getsource(translation_job_mod)
    assert "translate_plain_text_to_ru" not in source
    assert callable(translate_plain_text_to_ru)


def test_run_translate_product_is_sync_entrypoint(monkeypatch):
    async def _fake(product_id: int):
        return {"status": "skip", "reason": "valid_ru", "product_id": product_id}

    monkeypatch.setattr("src.jobs.translation_job._translate_product", _fake)
    result = run_translate_product(3)
    assert result["status"] == "skip"
    assert result["product_id"] == 3


def test_translate_descriptions_utils_has_no_jobs_imports() -> None:
    source = Path("src/utils/translate_descriptions.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    job_imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("src.jobs")
    ]
    assert job_imports == []
