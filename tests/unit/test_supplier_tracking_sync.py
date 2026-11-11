import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.order import OrderStatus
from src.services.orders.dhl_tracking import DhlTrackingFetchError
from src.services.orders.supplier_tracking import SupplierTrackingService
from tests.unit.test_supplier_tracking import _parcellab_payload


class _ProbeSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.entered = False
        self.closed = False
        self._in_txn = False
        self.commits = 0
        self.rollbacks = 0
        self.add = MagicMock()
        self.new: set[object] = set()
        self.dirty: set[object] = set()
        self.deleted: set[object] = set()
        self.get = AsyncMock(return_value=None)

    def in_transaction(self) -> bool:
        return self._in_txn

    def begin_txn(self) -> None:
        self._in_txn = True

    async def commit(self) -> None:
        self.commits += 1
        self._in_txn = False

    async def rollback(self) -> None:
        self.rollbacks += 1
        self._in_txn = False

    async def __aenter__(self) -> "_ProbeSession":
        self.entered = True
        self.closed = False
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None and self._in_txn:
            self.rollbacks += 1
        self._in_txn = False
        self.closed = True
        return False


# Собирает две probe-сессии и фейковый Crud/Shipment для sync_order.
def _sync_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    persist_commit: AsyncMock | None = None,
    placed: bool = True,
):
    from src.services.orders import supplier_tracking as st_module

    created: list[_ProbeSession] = []
    for_update_calls: list[str] = []
    io_snapshots: list[dict[str, object]] = []

    load_order = SimpleNamespace(
        id=7,
        supplier_order_id="TP-2712965",
        supplier_tracking_id="CJ687378245DE",
    )
    persist_order = MagicMock()
    persist_order.id = 7
    persist_order.status = OrderStatus.DELIVERY
    persist_order.supplier_order_id = "TP-2712965"
    persist_order.supplier_tracking_id = "CJ687378245DE"
    persist_order.supplier_tracking_json = None
    persist_order.supplier_tracking_failures = 0
    persist_order.supplier_tracking_last_error = None
    persist_order.supplier_tracking_sync_state = "waiting"
    persist_order.supplier_tracking_next_check_at = datetime(2026, 1, 1, 12, 0, 0)
    persist_order.supplier_tracking_updated_at = None
    persist_order.supplier_tracking_checked_at = None

    header = SimpleNamespace(id=10, external_id="TP-2712965")
    shipment = MagicMock()
    shipment.id = 3
    shipment.order_id = 7
    shipment.supplier_order_id = 10
    shipment.supplier_tracking_number = "CJ687378245DE"
    shipment.status = "in_transit"

    class _FakeCrud:
        def __init__(self, session: _ProbeSession, model=None) -> None:
            self.session = session
            session.begin_txn()

        async def get_by_id(self, order_id: int):
            assert order_id == 7
            return load_order

        async def get_by_id_for_update(self, order_id: int):
            assert order_id == 7
            self.session.begin_txn()
            for_update_calls.append(self.session.name)
            return persist_order

        async def list_placed_supplier_orders(self, order_id: int):
            return [header] if placed else []

        async def get_shipment_by_supplier_order_id(self, supplier_order_id: int):
            return shipment

        async def list_shipments_for_order(self, order_id: int):
            return [shipment]

    class _FakeShipmentService:
        def __init__(self, session: _ProbeSession) -> None:
            self.session = session

        async def create_from_placed_supplier_order(
            self, order_id: int, supplier_order_id: int, commit: bool = True
        ):
            return shipment

    def session_factory() -> _ProbeSession:
        session = _ProbeSession(f"s{len(created)}")
        session.get = AsyncMock(return_value=header)
        created.append(session)
        if persist_commit is not None and len(created) == 2:
            session.commit = persist_commit  # type: ignore[method-assign]
        return session

    def capture_io() -> None:
        io_snapshots.append(
            {
                "open_txns": [item.name for item in created if item.in_transaction()],
                "unclosed": [
                    item.name for item in created if item.entered and not item.closed
                ],
                "for_update": list(for_update_calls),
            }
        )

    monkeypatch.setattr(st_module, "CrudOrder", _FakeCrud)
    monkeypatch.setattr(st_module, "ShipmentService", _FakeShipmentService)
    monkeypatch.setattr(
        st_module, "sync_delivered_alert_after_tracking_check", AsyncMock()
    )
    return SimpleNamespace(
        created=created,
        for_update_calls=for_update_calls,
        io_snapshots=io_snapshots,
        capture_io=capture_io,
        persist_order=persist_order,
        load_order=load_order,
        shipment=shipment,
        session_factory=session_factory,
        module=st_module,
    )


@pytest.mark.asyncio
async def test_sync_order_happy_path_persists_on_fresh_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    original_next = harness.persist_order.supplier_tracking_next_check_at

    async def fake_parcellab(tp_id: str) -> dict:
        assert tp_id
        harness.capture_io()
        return _parcellab_payload()

    async def fake_dhl(piececode: str, proxy_url: str | None = None) -> dict:
        harness.capture_io()
        return {"current_stage": "in_transit", "events": []}

    async def fake_pochta(barcode: str, proxy_url: str | None = None) -> dict:
        harness.capture_io()
        return {"events": []}

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(harness.module, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(harness.module, "fetch_pochta_tracking", fake_pochta)

    result = await SupplierTrackingService(
        session_factory=harness.session_factory
    ).sync_order(7)

    assert result["changed"] is True
    assert harness.persist_order is not None
    assert harness.persist_order.supplier_tracking_checked_at is not None
    assert harness.persist_order.supplier_tracking_next_check_at != original_next
    assert harness.for_update_calls == ["s1"]
    assert [item.closed for item in harness.created] == [True, True]
    assert harness.created[1].commits == 1


@pytest.mark.asyncio
async def test_delayed_parcellab_http_has_no_open_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)

    async def fake_parcellab(tp_id: str) -> dict:
        await asyncio.sleep(0.01)
        harness.capture_io()
        return _parcellab_payload()

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module, "fetch_dhl_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    await SupplierTrackingService(session_factory=harness.session_factory).sync_order(7)

    assert harness.io_snapshots
    assert harness.io_snapshots[0]["open_txns"] == []
    assert harness.io_snapshots[0]["unclosed"] == []
    assert harness.io_snapshots[0]["for_update"] == []


@pytest.mark.asyncio
async def test_delayed_dhl_http_has_no_open_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)

    async def fake_dhl(piececode: str, proxy_url: str | None = None) -> dict:
        await asyncio.sleep(0.01)
        harness.capture_io()
        return {"current_stage": "in_transit", "events": []}

    monkeypatch.setattr(
        harness.module,
        "fetch_supplier_tracking",
        AsyncMock(return_value=_parcellab_payload()),
    )
    monkeypatch.setattr(harness.module, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    await SupplierTrackingService(session_factory=harness.session_factory).sync_order(7)

    assert harness.io_snapshots[0]["open_txns"] == []
    assert harness.io_snapshots[0]["unclosed"] == []
    assert harness.io_snapshots[0]["for_update"] == []


@pytest.mark.asyncio
async def test_browser_queue_wait_has_no_open_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    monkeypatch.setattr(harness.module.settings, "DHL_TRACKING_USE_BROWSER", True)

    async def fake_dhl(piececode: str, proxy_url: str | None = None) -> dict:
        raise DhlTrackingFetchError("blocked", "DHL blocked", True)

    async def fake_browser(piececode: str) -> dict:
        await asyncio.sleep(0.01)
        harness.capture_io()
        return {"current_stage": "in_transit", "events": []}

    monkeypatch.setattr(
        harness.module,
        "fetch_supplier_tracking",
        AsyncMock(return_value=_parcellab_payload()),
    )
    monkeypatch.setattr(harness.module, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    await SupplierTrackingService(
        session_factory=harness.session_factory,
        dhl_browser_fetch=fake_browser,
    ).sync_order(7)

    assert harness.io_snapshots[0]["open_txns"] == []
    assert harness.io_snapshots[0]["unclosed"] == []
    assert harness.io_snapshots[0]["for_update"] == []


@pytest.mark.asyncio
async def test_concurrent_sync_allows_overlapping_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    entered = 0
    gate = asyncio.Event()
    overlap = False

    async def fake_parcellab(tp_id: str) -> dict:
        nonlocal entered, overlap
        entered += 1
        harness.capture_io()
        if entered == 1:
            await gate.wait()
        else:
            overlap = True
            gate.set()
        return _parcellab_payload()

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module, "fetch_dhl_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )
    service = SupplierTrackingService(session_factory=harness.session_factory)
    await asyncio.gather(service.sync_order(7), service.sync_order(7))

    assert overlap is True
    assert all(snap["open_txns"] == [] for snap in harness.io_snapshots)
    assert set(harness.for_update_calls) == {
        harness.created[2].name,
        harness.created[3].name,
    }


@pytest.mark.asyncio
async def test_persist_applies_payload_to_fresh_order_not_load_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    load_checked = object()

    async def fake_parcellab(tp_id: str) -> dict:
        return _parcellab_payload()

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module, "fetch_dhl_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    await SupplierTrackingService(session_factory=harness.session_factory).sync_order(7)

    assert harness.persist_order.supplier_tracking_checked_at is not load_checked
    assert harness.persist_order.supplier_tracking_checked_at is not None
    assert harness.for_update_calls == ["s1"]


@pytest.mark.asyncio
async def test_exception_during_io_does_not_leave_open_txn_or_touch_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    original_next = harness.persist_order.supplier_tracking_next_check_at

    async def fake_parcellab(tp_id: str) -> dict:
        harness.capture_io()
        raise RuntimeError("parcel down")

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)

    with pytest.raises(RuntimeError, match="parcel down"):
        await SupplierTrackingService(
            session_factory=harness.session_factory
        ).sync_order(7)

    assert harness.io_snapshots[0]["open_txns"] == []
    assert harness.io_snapshots[0]["unclosed"] == []
    assert harness.for_update_calls == []
    assert len(harness.created) == 1
    assert harness.created[0].closed is True
    assert harness.created[0]._in_txn is False
    assert harness.persist_order.supplier_tracking_next_check_at == original_next
    assert harness.persist_order.supplier_tracking_checked_at is None


@pytest.mark.asyncio
async def test_persist_failure_rollbacks_and_keeps_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_commit = AsyncMock(side_effect=RuntimeError("persist down"))
    persist_commit.__name__ = "commit"
    harness = _sync_harness(monkeypatch, persist_commit=persist_commit)

    monkeypatch.setattr(
        harness.module,
        "fetch_supplier_tracking",
        AsyncMock(return_value=_parcellab_payload()),
    )
    monkeypatch.setattr(
        harness.module, "fetch_dhl_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    with pytest.raises(RuntimeError, match="persist down"):
        await SupplierTrackingService(
            session_factory=harness.session_factory
        ).sync_order(7)

    persist_session = harness.created[1]
    assert persist_session.closed is True
    assert persist_session._in_txn is False
    assert persist_session.rollbacks == 1
    # In-memory next_check может смениться; due на retry даёт rollback session 2.
    assert persist_commit.await_count == 1


@pytest.mark.asyncio
async def test_sync_order_does_not_pass_orm_through_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    seen: list[object] = []

    async def fake_parcellab(tp_id: str) -> dict:
        seen.append(tp_id)
        return _parcellab_payload()

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module, "fetch_dhl_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    await SupplierTrackingService(session_factory=harness.session_factory).sync_order(7)

    assert seen == ["TP-2712965"] or all(isinstance(item, str) for item in seen)


# Prod job: без session/factory, две owned session через async_session_maker.
@pytest.mark.asyncio
async def test_production_job_entrypoint_uses_two_owned_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    io_reached = False

    async def fake_parcellab(tp_id: str) -> dict:
        nonlocal io_reached
        io_reached = True
        harness.capture_io()
        return _parcellab_payload()

    async def unused_browser(piececode: str) -> dict:
        raise AssertionError("browser fallback не должен вызываться")

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module, "fetch_dhl_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(harness.module, "async_session_maker", harness.session_factory)

    result = await SupplierTrackingService(
        dhl_browser_fetch=unused_browser,
    ).sync_order(7)

    assert io_reached is True
    assert result["changed"] is True
    assert len(harness.created) == 2
    load_session, persist_session = harness.created
    assert load_session is not persist_session
    assert load_session.closed is True
    assert load_session.commits == 1
    assert load_session.in_transaction() is False
    assert persist_session.closed is True
    assert persist_session.commits == 1
    assert harness.io_snapshots
    assert harness.io_snapshots[0]["open_txns"] == []
    assert harness.io_snapshots[0]["unclosed"] == []
    assert harness.io_snapshots[0]["for_update"] == []
    assert harness.for_update_calls == [persist_session.name]


# Injected session с dirty state: sync_order не делает commit caller'а.
@pytest.mark.asyncio
async def test_injected_session_does_not_commit_caller_dirty_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    io_reached = False

    async def fake_parcellab(tp_id: str) -> dict:
        nonlocal io_reached
        io_reached = True
        return _parcellab_payload()

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module, "fetch_dhl_tracking", AsyncMock(return_value={"events": []})
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    injected = _ProbeSession("injected")
    injected.dirty.add(object())
    caller_commit = AsyncMock()
    injected.commit = caller_commit  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="не коммитит чужую"):
        await SupplierTrackingService(session=injected).sync_order(7)

    assert io_reached is False
    assert caller_commit.await_count == 0


# Placed/mirror: CJ сменился за время I/O — старый payload не пишем.
@pytest.mark.asyncio
async def test_stale_placed_cj_is_not_applied_after_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    harness.shipment.customer_tracking_number = None
    io_reached = False

    async def fake_parcellab(tp_id: str) -> dict:
        nonlocal io_reached
        io_reached = True
        harness.shipment.supplier_tracking_number = "CJ-NEW"
        harness.persist_order.supplier_tracking_id = "CJ-NEW"
        return _parcellab_payload()

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module,
        "fetch_dhl_tracking",
        AsyncMock(return_value={"tracking_number": "CJ687378245DE", "events": []}),
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    await SupplierTrackingService(session_factory=harness.session_factory).sync_order(7)

    assert io_reached is True
    assert harness.shipment.supplier_tracking_number == "CJ-NEW"
    assert harness.shipment.customer_tracking_number is None


# Legacy: CJ сменился за время I/O — старый DHL payload не пишем в json.
@pytest.mark.asyncio
async def test_stale_legacy_cj_is_not_applied_after_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch, placed=False)
    harness.load_order.supplier_tracking_id = "CJ-OLD"
    harness.persist_order.supplier_tracking_id = "CJ-OLD"
    harness.persist_order.supplier_tracking_json = {}
    io_reached = False

    async def fake_parcellab(tp_id: str) -> dict:
        nonlocal io_reached
        io_reached = True
        harness.persist_order.supplier_tracking_id = "CJ-NEW"
        return _parcellab_payload()

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module,
        "fetch_dhl_tracking",
        AsyncMock(return_value={"current_stage": "in_transit", "events": []}),
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    result = await SupplierTrackingService(
        session_factory=harness.session_factory
    ).sync_order(7)

    assert io_reached is True
    assert result["changed"] is False
    assert harness.persist_order.supplier_tracking_id == "CJ-NEW"
    assert harness.persist_order.supplier_tracking_json == {}


# Mirror fallback: Order.CJ сменился за I/O — carrier payload старого CJ не пишем.
@pytest.mark.asyncio
async def test_stale_mirror_cj_is_not_applied_after_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _sync_harness(monkeypatch)
    harness.shipment.supplier_tracking_number = ""
    harness.shipment.customer_tracking_number = None
    harness.load_order.supplier_tracking_id = "CJ-OLD"
    harness.persist_order.supplier_tracking_id = "CJ-OLD"
    io_reached = False

    async def fake_parcellab(tp_id: str) -> dict:
        nonlocal io_reached
        io_reached = True
        harness.persist_order.supplier_tracking_id = "CJ-NEW"
        return {"header": [], "body": {}}

    monkeypatch.setattr(harness.module, "fetch_supplier_tracking", fake_parcellab)
    monkeypatch.setattr(
        harness.module,
        "fetch_dhl_tracking",
        AsyncMock(return_value={"tracking_number": "CJ-OLD", "events": []}),
    )
    monkeypatch.setattr(
        harness.module, "fetch_pochta_tracking", AsyncMock(return_value={"events": []})
    )

    await SupplierTrackingService(session_factory=harness.session_factory).sync_order(7)

    assert io_reached is True
    assert harness.persist_order.supplier_tracking_id == "CJ-NEW"
    assert harness.shipment.customer_tracking_number is None
