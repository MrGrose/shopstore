from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.models.pricing import MarginRule, MarginRuleHistory
from src.repositories.pricing_repo import PricingRepository
from src.web.templating import templates


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        return None

    async def refresh(self, value: object) -> None:
        return None


@pytest.mark.asyncio
async def test_margin_change_appends_history() -> None:
    session = FakeSession()
    repo = PricingRepository(session)  # type: ignore[arg-type]
    rule = MarginRule(
        id=7,
        sport_type="Padel",
        subcategory_slug="rackets",
        margin_percent=Decimal("30.00"),
        is_active=True,
    )

    await repo.update_margin_rule(rule, Decimal("35.00"))

    history = next(row for row in session.added if isinstance(row, MarginRuleHistory))
    assert history.margin_rule_id == 7
    assert history.previous_margin_percent == Decimal("30.00")
    assert history.margin_percent == Decimal("35.00")


@pytest.mark.asyncio
async def test_same_margin_does_not_append_history() -> None:
    session = FakeSession()
    repo = PricingRepository(session)  # type: ignore[arg-type]
    rule = MarginRule(
        id=8,
        sport_type="Padel",
        subcategory_slug="balls",
        margin_percent=Decimal("30.00"),
        is_active=True,
    )

    await repo.update_margin_rule(rule, Decimal("30.00"))

    assert not any(isinstance(row, MarginRuleHistory) for row in session.added)


def test_succeeded_job_status_renders_empty_fragment() -> None:
    template = templates.env.get_template("site/admin/partials/margin_job_status.html")
    job = SimpleNamespace(
        id=12,
        status="succeeded",
        processed_count=239,
        total_count=239,
        updated_count=239,
        error_count=0,
    )

    assert template.render(job=job).strip() == ""


def test_running_job_status_uses_russian_label() -> None:
    template = templates.env.get_template("site/admin/partials/margin_job_status.html")
    job = SimpleNamespace(
        id=13,
        status="running",
        processed_count=120,
        total_count=239,
        updated_count=118,
        error_count=0,
    )

    html = template.render(job=job)

    assert "выполняется" in html
    assert ">running<" not in html


def test_margin_history_renders_date_and_percent_change() -> None:
    template = templates.env.get_template("site/admin/partials/margin_rule_detail.html")
    rule = SimpleNamespace(id=7, subcategory_slug="rackets")
    history = [
        SimpleNamespace(
            created_at=datetime(2026, 7, 14, 13, 10),
            previous_margin_percent=Decimal("100.00"),
            margin_percent=Decimal("130.00"),
        )
    ]

    html = template.render(
        title="Падел → Ракетки",
        storefront_count=239,
        selected_sport="Padel",
        rule=rule,
        active_job=None,
        last_job=None,
        history=history,
    )

    assert "История наценки" in html
    assert "14.07.2026 16:10" in html
    assert "100.00% → <strong>130.00%</strong>" in html
