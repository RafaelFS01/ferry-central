"""Validação de UUIDv4 e controle de deduplicação idempotente de pacotes."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID


class InvalidPacketIdError(ValueError):
    """Erro lançado quando message_id não é um UUIDv4 válido."""


def validate_packet_uuid(raw_message_id: str) -> UUID:
    """Valida e converte message_id garantindo estritamente formato UUIDv4."""
    normalized = raw_message_id.strip() if isinstance(raw_message_id, str) else ""
    if not normalized:
        raise InvalidPacketIdError("message_id é obrigatório e deve ser um UUIDv4 válido.")

    try:
        parsed = UUID(normalized)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidPacketIdError(
            f"message_id inválido ({raw_message_id!r}): esperado UUIDv4."
        ) from exc

    if parsed.version != 4:
        raise InvalidPacketIdError(
            f"message_id inválido ({raw_message_id!r}): esperado UUID versão 4, recebido v{parsed.version}."
        )
    return parsed


class InMemoryIdempotencyCache:
    """Cache LRU com TTL limitado em memória para detecção rápida de duplicidades."""

    def __init__(
        self,
        max_size: int = 50_000,
        ttl_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 0:
            raise ValueError("max_size não pode ser negativo.")
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds não pode ser negativo.")

        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[UUID, float] = OrderedDict()

    def _is_expired(self, stored_at: float, now: float) -> bool:
        if self._ttl_seconds == 0:
            return True
        return (now - stored_at) >= self._ttl_seconds

    def _purge_expired_head(self, now: float) -> None:
        while self._entries:
            oldest_key, stored_at = next(iter(self._entries.items()))
            if not self._is_expired(stored_at, now):
                break
            self._entries.pop(oldest_key, None)

    def contains(self, packet_id: UUID) -> bool:
        """Retorna True se o packet_id estiver ativo no cache."""
        if self._max_size == 0 or self._ttl_seconds == 0:
            return False

        now = self._clock()
        stored_at = self._entries.get(packet_id)
        if stored_at is None:
            return False
        if self._is_expired(stored_at, now):
            self._entries.pop(packet_id, None)
            return False

        self._entries.move_to_end(packet_id)
        return True

    def mark_processed(self, packet_id: UUID) -> None:
        """Registra packet_id como processado respeitando capacidade máxima e TTL."""
        if self._max_size == 0 or self._ttl_seconds == 0:
            return

        now = self._clock()
        self._purge_expired_head(now)
        self._entries[packet_id] = now
        self._entries.move_to_end(packet_id)
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(slots=True)
class _InFlightLockEntry:
    lock: asyncio.Lock
    waiters: int = 0


class IdempotencyGuard:
    """Coordena deduplicação em memória + verificação prévia em banco e lock por pacote."""

    def __init__(
        self,
        cache: InMemoryIdempotencyCache | None = None,
    ) -> None:
        self._cache = cache if cache is not None else InMemoryIdempotencyCache()
        self._locks: dict[UUID, _InFlightLockEntry] = {}

    @asynccontextmanager
    async def lock_packet(self, packet_id: UUID) -> AsyncIterator[None]:
        """Serializa requisições concorrentes com o mesmo packet_id neste nó."""
        entry = self._locks.get(packet_id)
        if entry is None:
            entry = _InFlightLockEntry(lock=asyncio.Lock())
            self._locks[packet_id] = entry
        entry.waiters += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.waiters -= 1
            if entry.waiters == 0 and not entry.lock.locked():
                self._locks.pop(packet_id, None)

    async def is_duplicate(
        self,
        packet_id: UUID,
        db_exists_checker: Callable[[UUID], Awaitable[bool]] | None = None,
    ) -> bool:
        """Verifica se packet_id já foi processado antes da persistência/publicação."""
        if self._cache.contains(packet_id):
            return True

        if db_exists_checker is not None and await db_exists_checker(packet_id):
            self._cache.mark_processed(packet_id)
            return True

        return False

    def mark_processed(self, packet_id: UUID) -> None:
        """Marca packet_id como processado após sucesso do pipeline de ingestão."""
        self._cache.mark_processed(packet_id)

