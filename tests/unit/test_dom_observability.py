import json
import logging

from src.jobs.dom_observability import log_dom_product


def test_log_dom_product_emits_json(caplog) -> None:
    caplog.set_level(logging.INFO, logger="src.jobs.dom_observability")
    log_dom_product({"product_id": 10348, "outcome": "parsed_ok"})
    assert any("dom_product" in r.message for r in caplog.records)
    line = next(r for r in caplog.records if "dom_product" in r.message)
    payload = json.loads(line.message.split("dom_product ", 1)[1])
    assert payload["event"] == "dom_product"
    assert payload["product_id"] == 10348
