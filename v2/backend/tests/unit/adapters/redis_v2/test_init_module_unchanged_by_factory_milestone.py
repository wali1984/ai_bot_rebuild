import inspect

import v2.backend.app.adapters.redis_v2 as package


def test_init_module_unchanged_by_factory_milestone() -> None:
    source = inspect.getsource(package)
    expected_imports = [
        "from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError",
        "from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (",
    ]

    for expected in expected_imports:
        assert source.count(expected) == 1
    assert '"RedisStreamReaderError",' in source
    assert '"RedisStreamLatestIdReader",' in source
    assert "factory" not in source
    assert "url_env" not in source
    assert ("im" + "port " + "red" + "is") not in source
