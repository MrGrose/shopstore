from src.jobs.dom_watchdog import job_needs_requeue


# Живой worker не считается кандидатом на requeue.
def test_live_worker_does_not_need_requeue() -> None:
    assert job_needs_requeue("w1", {"w1", "w2"}) is False


# Мёртвый или пустой worker — recovery requeue.
def test_dead_or_missing_worker_needs_requeue() -> None:
    assert job_needs_requeue("w-dead", {"w1"}) is True
    assert job_needs_requeue(None, {"w1"}) is True
    assert job_needs_requeue("", {"w1"}) is True
