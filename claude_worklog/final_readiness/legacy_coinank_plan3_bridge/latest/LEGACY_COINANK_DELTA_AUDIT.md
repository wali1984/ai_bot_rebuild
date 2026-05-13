# Legacy CoinAnk Delta Audit

Read-only audit of the operator-patched live legacy CoinAnk ingestor. The live bot was not edited from AI BOT REBUILD.

| Item | Value |
|---|---|
| live hash | `2cd0263d4f50c8531a7b2f2400ff502250309d1a8daf9dc6d1192c46269d268d` |
| reference hash before | `42644e2003683deaa2bde69b5a73a4fef8ee6544e6ada52a634e4167deb30ade` |
| reference hash after | `2cd0263d4f50c8531a7b2f2400ff502250309d1a8daf9dc6d1192c46269d268d` |
| monitor hash | `55820c3eb988afd2041bc8b392db2650e297ac75ac82180068737a9d2ab96ced` |
| legacy_reference refreshed | `True` |
| diff line count | `20` |
| secret assignments | `0` |

## Required Source Checks

| Item | Value |
|---|---|
| required_tfs_default | `PASS` |
| kline_disabled_by_default | `PASS` |
| orderbook_disabled_by_default | `PASS` |
| lastprice_disabled_by_default | `PASS` |
| plan4_disabled_by_default | `PASS` |
| endtime_helpers_preserved | `PASS` |
| agg_cvd_uses_exchanges_basecoin | `PASS` |
| indicator_smc_exists | `PASS` |
| radar_popular_endpoints_exist | `PASS` |
| funding_weighted_exists | `PASS` |
| ls_buy_sell_exists | `PASS` |
| ls_toptrader_positions_exists | `PASS` |
| endpoint_manifest_publisher_exists | `PASS` |
| raw_liquidation_global_supported | `PASS` |
| global_feature_contract_supported | `PASS` |
| marketOrder_getAggCvd_uses_exchanges_baseCoin | `PASS` |

## Forbidden Source Checks

| Item | Value |
|---|---|
| hard_params_list_cap_present | `PASS` |
| possible_hardcoded_api_key_assignment | `PASS` |

## Diff Excerpt

```diff
--- HEAD:legacy_reference/ingest/live_coinank.py
+++ /home/wali/Desktop/AI BOT/ingest/live_coinank.py
@@ -2241,8 +2241,15 @@
                 continue
             p = psets[0]
             data = fetch_endpoint(key, spec["path"], p)
-            if data and data.get("success"):
-                print(f"  [ok]   {key}: success=True data_keys={list((data.get('data') or {}).keys())[:4]}")
+            if data and (data.get("success") or data.get("code") == "1"):
+                inner = data.get("data")
+                if isinstance(inner, dict):
+                    dk = list(inner.keys())[:4]
+                elif isinstance(inner, list):
+                    dk = [f"list[{len(inner)}]"]
+                else:
+                    dk = [str(type(inner).__name__)]
+                print(f"  [ok]   {key}: success=True data_keys={dk}")
                 ok_count += 1
             else:
                 print(f"  [fail] {key}: {str(data)[:120]}")
```
