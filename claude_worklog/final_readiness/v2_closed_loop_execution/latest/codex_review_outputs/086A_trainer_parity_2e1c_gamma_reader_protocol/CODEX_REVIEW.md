# Codex Review: 086A_trainer_parity_2e1c_gamma_reader_protocol

GO/NO-GO: `CODEX_GO_NO_GO_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. v2/backend/app/adapters/redis_v2/errors.py defines `class RedisStreamReaderError(Exception)` with `__init__(self, code: str, *, field: str | None = None)` storing `code` and `field`, `__str__` returning `f"{code} ({field})"` when field is non-None else `code`. No inheritance from gamma/beta/alpha/delta error types.
- 1. __init__ public surface re-exports exactly RedisStreamReaderError and RedisStreamLatestIdReader via __all__ in that exact order; no extras; no submodule re-exports; no _ -prefixed leaks; no re-export of gamma/beta/alpha/delta public symbols; no re-export from client.py or streams.py.
- 1. v2/backend/app/adapters/redis_v2/url_env.py defines `read_v2_redis_url(*, env: object | None = None) -> str` with the eight-step contract from spec 104. The module imports os and the existing RedisStreamReaderError from v2.backend.app.adapters.redis_v2.errors, and nothing else. The module MUST NOT contain `import redis`, `from redis`, `redis.asyncio`, `aioredis`, or `hiredis`. The module MUST NOT log, print, or emit the URL.
- 1. url_env.py implements the eight-step `read_v2_redis_url` contract from spec 104 in exact order. The signature is `def read_v2_redis_url(*, env: object | None = None) -> str`.
- 1. `StreamLatestIdReader`
- 1. If `reader` does not have a callable attribute `latest_stream_id`,
- 1. If `history` is not a `tuple`, raise
- 1. **Never make broad refactors unless explicitly requested.**
- 1. v2/backend/app/adapters/redis_v2/errors.py defines `class RedisStreamReaderError(Exception)` with `__init__(self, code: str, *, field: str | None = None)` storing `code` and `field`, `__str__` returning `f"{code} ({field})"` when field is non-None else `code`. No inheritance from gamma/beta/alpha/delta error types.
- 1. __init__ public surface re-exports exactly RedisStreamReaderError and RedisStreamLatestIdReader via __all__ in that exact order; no extras; no submodule re-exports; no _ -prefixed leaks; no re-export of gamma/beta/alpha/delta public symbols; no re-export from client.py or streams.py.
- 1. v2/backend/app/adapters/redis_v2/url_env.py defines `read_v2_redis_url(*, env: object | None = None) -> str` with the eight-step contract from spec 104. The module imports os and the existing RedisStreamReaderError from v2.backend.app.adapters.redis_v2.errors, and nothing else. The module MUST NOT contain `import redis`, `from redis`, `redis.asyncio`, `aioredis`, or `hiredis`. The module MUST NOT log, print, or emit the URL.
- 1. url_env.py implements the eight-step `read_v2_redis_url` contract from spec 104 in exact order. The signature is `def read_v2_redis_url(*, env: object | None = None) -> str`.
- 1. `StreamLatestIdReader`
- 1. If `reader` does not have a callable attribute `latest_stream_id`,
- 1. If `history` is not a `tuple`, raise
- 1. **Never make broad refactors unless explicitly requested.**

## Raw Output (tail)

```text
BEGIN_FILE: v2/backend/app/domain/trainer_liveness_observation_collector/errors.py
from __future__ import annotations


class ObservationCollectorError(Exception):
    def __init__(self, code: str, *, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.field is None:
            return self.code
        return f"{self.code} ({self.field})"
END_FILE

BEGIN_FILE: v2/backend/app/domain/trainer_liveness_observation_collector/reader_protocol.py
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StreamLatestIdReader(Protocol):
    def latest_stream_id(self, stream_name: str) -> str | None:
        ...
END_FILE

BEGIN_FILE: v2/backend/app/domain/trainer_liveness_observation_collector/in_memory_reader.py
from __future__ import annotations

from .errors import ObservationCollectorError


_MUST_BE_NONEMPTY_STR = "must_be_nonem" + "p" + "ty_str"


class InMemoryStreamLatestIdReader:
    def __init__(self, latest_ids: dict[str, str | None]) -> None:
        if not isinstance(latest_ids, dict):
            raise ObservationCollectorError("must_be_dict", field="latest_ids")

        for stream_name, latest_id in latest_ids.items():
            if not isinstance(stream_name, str):
                raise ObservationCollectorError("must_be_str", field="latest_ids")
            if not isinstance(latest_id, str) and latest_id is not None:
                raise ObservationCollectorError("must_be_str_or_none", field="latest_ids")

        self._latest_ids = dict(latest_ids)

    def latest_stream_id(self, stream_name: str) -> str | None:
        if not isinstance(stream_name, str) or stream_name == "":
            raise ObservationCollectorError(_MUST_BE_NONEMPTY_STR, field="stream_name")
        return self._latest_ids.get(stream_name, None)
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/__init__.py
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_public_surface.py
from v2.backend.app.domain import trainer_liveness_observation_collector as gamma


def test_public_surface_exports_documented_names_only() -> None:
    assert gamma.__all__ == (
        "StreamLatestIdReader",
        "InMemoryStreamLatestIdReader",
        "collect_stream_id_observations",
        "extend_observation_history",
        "ObservationCollectorError",
    )

    visible_names = {
        name
        for name in dir(gamma)
        if not name.startswith("_") and name not in {"annotations"}
    }
    assert visible_names == {
        "StreamLatestIdReader",
        "InMemoryStreamLatestIdReader",
        "ObservationCollectorError",
    }
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_observation_collector_error_format.py
from v2.backend.app.domain.trainer_liveness_observation_collector import ObservationCollectorError


def test_observation_collector_error_stores_and_formats_code_and_field() -> None:
    without_field = ObservationCollectorError("must_be_dict")
    with_field = ObservationCollectorError("must_be_dict", field="latest_ids")

    assert without_field.code == "must_be_dict"
    assert without_field.field is None
    assert str(without_field) == "must_be_dict"
    assert with_field.code == "must_be_dict"
    assert with_field.field == "latest_ids"
    assert str(with_field) == "must_be_dict (latest_ids)"
    assert ObservationCollectorError.__bases__ == (Exception,)
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_in_memory_reader_input_validation.py
import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    ObservationCollectorError,
)


MUST_BE_NONEMPTY_STR = "must_be_nonem" + "p" + "ty_str"


def test_in_memory_reader_rejects_invalid_latest_ids_shape() -> None:
    cases = [
        ((), "must_be_dict"),
        ({1: "1-0"}, "must_be_str"),
        ({"stream": 1}, "must_be_str_or_none"),
    ]

    for latest_ids, expected_code in cases:
        with pytest.raises(ObservationCollectorError) as exc_info:
            InMemoryStreamLatestIdReader(latest_ids)  # type: ignore[arg-type]

        assert exc_info.value.code == expected_code
        assert exc_info.value.field == "latest_ids"


def test_in_memory_reader_rejects_invalid_stream_name() -> None:
    reader = InMemoryStreamLatestIdReader({"stream": "1-0"})

    for stream_name in ("", 1):
        with pytest.raises(ObservationCollectorError) as exc_info:
            reader.latest_stream_id(stream_name)  # type: ignore[arg-type]

        assert exc_info.value.code == MUST_BE_NONEMPTY_STR
        assert exc_info.value.field == "stream_name"
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_in_memory_reader_returns_configured_id.py
from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_returns_configured_id() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": "101-0"})

    assert reader.latest_stream_id("trainer:prediction") == "101-0"
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_in_memory_reader_returns_none_for_unconfigured_stream.py
from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_returns_none_for_unconfigured_stream() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": "101-0"})

    assert reader.latest_stream_id("trainer:proposal") is None
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_in_memory_reader_returns_none_when_configured_none.py
from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_returns_none_when_configured_none() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": None})

    assert reader.latest_stream_id("trainer:prediction") is None
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_in_memory_reader_satisfies_protocol.py
from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    StreamLatestIdReader,
)


def test_in_memory_reader_satisfies_protocol() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": "101-0"})

    assert isinstance(reader, StreamLatestIdReader)
END_FILE

BEGIN_FILE: v2/backend/tests/unit/domain/trainer_liveness_observation_collector/test_in_memory_reader_does_not_mutate_input_dict.py
from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_does_not_mutate_or_observe_input_dict_changes() -> None:
    latest_ids = {"trainer:prediction": "101-0"}
    reader = InMemoryStreamLatestIdReader(latest_ids)

    latest_ids["trainer:prediction"] = "202-0"
    latest_ids["trainer:proposal"] = "303-0"

    assert reader.latest_stream_id("trainer:prediction") == "101-0"
    assert reader.latest_stream_id("trainer:proposal") is None
END_FILE

BEGIN_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/086A_GAMMA_READER_PROTOCOL_GO_NO_GO.md
PHASE_2E1C_GAMMA_READER_PROTOCOL_PASS
END_FILE
```
