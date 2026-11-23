"""Testes unitários do logging estruturado em JSON do Nó Central (SCRUM-32)."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from src.api.main import configure_logging as configure_api_logging
from src.logging_config import JsonLogFormatter, configure_json_logging
from src.server.main import configure_logging as configure_ingestion_logging
from src.worker.main import configure_logging as configure_worker_logging


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    """Preserva handlers e nível originais do root logger entre testes."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        yield
    finally:
        root.handlers.clear()
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)


def test_json_log_formatter_emits_essential_fields_and_iso8601_utc() -> None:
    stream = io.StringIO()
    configure_json_logging(service="ingestion", level="INFO", stream=stream)

    test_logger = logging.getLogger("src.server.test")
    test_logger.info("Servidor iniciado na porta %d", 50051)
    test_logger.warning("Pacote fora de ordem: seq=%d", 42)
    test_logger.error("Falha ao publicar no SNS")

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 3

    expected = [
        ("INFO", "Servidor iniciado na porta 50051"),
        ("WARNING", "Pacote fora de ordem: seq=42"),
        ("ERROR", "Falha ao publicar no SNS"),
    ]
    for line, (expected_level, expected_message) in zip(lines, expected, strict=True):
        parsed = json.loads(line)
        assert parsed["level"] == expected_level
        assert parsed["service"] == "ingestion"
        assert parsed["logger"] == "src.server.test"
        assert parsed["message"] == expected_message

        ts_raw = parsed["timestamp"]
        assert ts_raw.endswith("Z")
        ts_parsed = datetime.fromisoformat(ts_raw)
        assert ts_parsed.tzinfo == UTC


def test_json_log_formatter_keeps_exception_as_single_valid_json_line() -> None:
    stream = io.StringIO()
    configure_json_logging(service="worker", level="INFO", stream=stream)

    test_logger = logging.getLogger("src.worker.test")
    try:
        raise RuntimeError("erro simulado no banco")
    except RuntimeError:
        test_logger.exception("Falha ao persistir lote")

    raw_output = stream.getvalue().strip()
    assert "\n" not in raw_output

    parsed = json.loads(raw_output)
    assert parsed["level"] == "ERROR"
    assert parsed["service"] == "worker"
    assert parsed["logger"] == "src.worker.test"
    assert parsed["message"] == "Falha ao persistir lote"
    assert "RuntimeError: erro simulado no banco" in parsed["exception"]


def test_uvicorn_loggers_emit_json_via_root_handler() -> None:
    stream = io.StringIO()
    configure_json_logging(service="api", level="INFO", stream=stream)

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:50000",
        "GET",
        "/health",
        "1.1",
        200,
    )

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["level"] == "INFO"
    assert parsed["service"] == "api"
    assert parsed["logger"] == "uvicorn.access"
    assert '127.0.0.1:50000 - "GET /health HTTP/1.1" 200' == parsed["message"]


@pytest.mark.parametrize(
    ("configure_fn", "expected_service"),
    [
        (configure_ingestion_logging, "ingestion"),
        (configure_worker_logging, "worker"),
        (configure_api_logging, "api"),
    ],
)
def test_service_entrypoints_configure_json_formatter(
    configure_fn,
    expected_service: str,
) -> None:
    configure_fn("WARNING")

    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len(root.handlers) == 1

    formatter = root.handlers[0].formatter
    assert isinstance(formatter, JsonLogFormatter)
    assert formatter.service == expected_service
