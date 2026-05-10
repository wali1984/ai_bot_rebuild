# Export Capacity Human Approval Packet

No Redis mutation is requested in this packet.

- recommended method: resume_safe_chunked_xrange_to_compressed_jsonl
- recommended batch size: 10000
- estimated runtime: 0.13 hours
- estimated compressed size: 2.169 GiB
- next safe milestone: REDIS_FULL_EXPORT_HUMAN_APPROVAL_REQUIRED

Exact command design must be implemented as a separate approved export run with runtime/load guards. Do not trim Redis until export/offload is verified.

REDIS_EXPORT_CAPACITY_HUMAN_APPROVAL_PACKET_READY
