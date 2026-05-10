# Export Integrity Check

Status: passed

- expected entries: 70930810
- exported entries: 70930810
- first exported id: 1772952007223-4
- last exported id: 1778432485206-24
- pre-export last id included: True
- chunk count: 710
- sha256 all ok: True
- duplicate chunk sequence: False

Sample parse:

```json
{
  "first": {
    "chunk": 0,
    "field_keys": [
      "ingest_ts",
      "notional",
      "price",
      "qty",
      "side",
      "source",
      "src_id",
      "src_key"
    ],
    "first_line_id": "1772952007223-4"
  },
  "last": {
    "chunk": 709,
    "field_keys": [
      "ingest_ts",
      "notional",
      "price",
      "qty",
      "side",
      "source",
      "src_id",
      "src_key"
    ],
    "first_line_id": "1777708845633-2"
  },
  "middle": {
    "chunk": 355,
    "field_keys": [
      "ingest_ts",
      "notional",
      "price",
      "qty",
      "side",
      "source",
      "src_id",
      "src_key"
    ],
    "first_line_id": "1774336156232-2"
  }
}
```

REDIS_LIQUIDATIONS_EXPORT_INTEGRITY_CHECK_READY
