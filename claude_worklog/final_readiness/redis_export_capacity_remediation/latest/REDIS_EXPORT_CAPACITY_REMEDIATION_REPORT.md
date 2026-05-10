# Redis Export Capacity Remediation Report

Generated: 2026-05-10T06:39:34.737306+00:00

REDIS_EXPORT_CAPACITY_REMEDIATION_READY

## Target

- key: `liquidations:events`
- memory: 12729.194 MB
- stream length: 70928809
- next safe milestone: REDIS_FULL_EXPORT_HUMAN_APPROVAL_REQUIRED

## Benchmark Summary

| batch | entries | seconds | entries/sec | compressed_bytes | compression_ratio |
| --- | --- | --- | --- | --- | --- |
| 1000 | 1000 | 0.0088 | 113847.27 | 37540 | 0.1198 |
| 5000 | 5000 | 0.036 | 138846.48 | 171588 | 0.1094 |
| 10000 | 10000 | 0.0672 | 148761.9 | 328528 | 0.1047 |
| 25000 | 25000 | 0.1746 | 143148.04 | 763128 | 0.0973 |

## Estimate

- estimated compressed export: 2.169 GiB
- estimated runtime: 0.13 hours
- disk feasible: True
- full export feasible with human approval: True

No Redis mutation was executed.

REDIS_EXPORT_CAPACITY_REMEDIATION_REPORT_READY
