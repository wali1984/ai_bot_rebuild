# Cooldown Test Output

Generated: 2026-05-02T21:27:34-04:00

## Symbol universe

==================================== ERRORS ====================================
_ ERROR collecting backend/tests/unit/symbol_universe/test_binance_coinm_fixture_discovery.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/symbol_universe/test_binance_coinm_fixture_discovery.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/symbol_universe/test_binance_coinm_fixture_discovery.py:4: in <module>
    from v2.backend.app.adapters.symbol_sources.binance_coinm import BinanceCoinMFuturesSource
E   ModuleNotFoundError: No module named 'v2'
_ ERROR collecting backend/tests/unit/symbol_universe/test_binance_usdm_fixture_discovery.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/symbol_universe/test_binance_usdm_fixture_discovery.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/symbol_universe/test_binance_usdm_fixture_discovery.py:4: in <module>
    from v2.backend.app.adapters.symbol_sources.binance_usdm import BinanceUsdMFuturesSource
E   ModuleNotFoundError: No module named 'v2'
_ ERROR collecting backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py:6: in <module>
    from v2.backend.app.adapters.symbol_sources.coinank import CoinAnkSymbolSource
E   ModuleNotFoundError: No module named 'v2'
_ ERROR collecting backend/tests/unit/symbol_universe/test_config_versions.py __
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/symbol_universe/test_config_versions.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/symbol_universe/test_config_versions.py:4: in <module>
    from v2.backend.app.adapters.symbol_sources.binance_usdm import BinanceUsdMFuturesSource
E   ModuleNotFoundError: No module named 'v2'
____ ERROR collecting backend/tests/unit/symbol_universe/test_overrides.py _____
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/symbol_universe/test_overrides.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/symbol_universe/test_overrides.py:4: in <module>
    from v2.backend.app.domain.symbols.models import ManualOverride, SymbolOverride, SymbolState, SymbolStateRecord
E   ModuleNotFoundError: No module named 'v2'
__ ERROR collecting backend/tests/unit/symbol_universe/test_state_machine.py ___
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/symbol_universe/test_state_machine.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/symbol_universe/test_state_machine.py:6: in <module>
    from v2.backend.app.domain.symbols.models import SymbolState, SymbolStateRecord
E   ModuleNotFoundError: No module named 'v2'
_ ERROR collecting backend/tests/unit/symbol_universe/test_symbol_normalization.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/symbol_universe/test_symbol_normalization.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/symbol_universe/test_symbol_normalization.py:4: in <module>
    from v2.backend.app.domain.symbols.normalization import (
E   ModuleNotFoundError: No module named 'v2'
=========================== short test summary info ============================
ERROR v2/backend/tests/unit/symbol_universe/test_binance_coinm_fixture_discovery.py
ERROR v2/backend/tests/unit/symbol_universe/test_binance_usdm_fixture_discovery.py
ERROR v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py
ERROR v2/backend/tests/unit/symbol_universe/test_config_versions.py
ERROR v2/backend/tests/unit/symbol_universe/test_overrides.py
ERROR v2/backend/tests/unit/symbol_universe/test_state_machine.py
ERROR v2/backend/tests/unit/symbol_universe/test_symbol_normalization.py
!!!!!!!!!!!!!!!!!!! Interrupted: 7 errors during collection !!!!!!!!!!!!!!!!!!!!
7 errors in 0.06s

## Feature snapshots

==================================== ERRORS ====================================
_ ERROR collecting backend/tests/unit/feature_snapshots/test_feature_snapshot_model.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/feature_snapshots/test_feature_snapshot_model.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/feature_snapshots/test_feature_snapshot_model.py:4: in <module>
    from v2.backend.app.services.feature_snapshots import FeatureSnapshotService
E   ModuleNotFoundError: No module named 'v2'
_ ERROR collecting backend/tests/unit/feature_snapshots/test_freshness_flags.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/feature_snapshots/test_freshness_flags.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/feature_snapshots/test_freshness_flags.py:1: in <module>
    from v2.backend.app.domain.features.freshness import assess_freshness
E   ModuleNotFoundError: No module named 'v2'
_ ERROR collecting backend/tests/unit/feature_snapshots/test_missing_stale_unused.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/feature_snapshots/test_missing_stale_unused.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/feature_snapshots/test_missing_stale_unused.py:4: in <module>
    from v2.backend.app.services.feature_snapshots import FeatureSnapshotService
E   ModuleNotFoundError: No module named 'v2'
_ ERROR collecting backend/tests/unit/feature_snapshots/test_trainer_input_contract.py _
ImportError while importing test module '/home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/unit/feature_snapshots/test_trainer_input_contract.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
v2/backend/tests/unit/feature_snapshots/test_trainer_input_contract.py:4: in <module>
    from v2.backend.app.adapters.feature_pipeline.legacy_adapter import LegacyFeaturePipelineAdapter
E   ModuleNotFoundError: No module named 'v2'
=========================== short test summary info ============================
ERROR v2/backend/tests/unit/feature_snapshots/test_feature_snapshot_model.py
ERROR v2/backend/tests/unit/feature_snapshots/test_freshness_flags.py
ERROR v2/backend/tests/unit/feature_snapshots/test_missing_stale_unused.py
ERROR v2/backend/tests/unit/feature_snapshots/test_trainer_input_contract.py
!!!!!!!!!!!!!!!!!!! Interrupted: 4 errors during collection !!!!!!!!!!!!!!!!!!!!
4 errors in 0.05s

## Trainer adapter/domain
........................................................................ [ 64%]
........................................                                 [100%]
112 passed in 0.06s
