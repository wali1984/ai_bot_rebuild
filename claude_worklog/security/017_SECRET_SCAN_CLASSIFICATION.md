# 017 Secret Scan Classification

## Result
The watchdog stopped after generated remediation text triggered a broad secret scan.

## Classification
False positive unless high-confidence scanner reports real credential material.

## Reason
Generic policy words such as `token`, `secret`, `risk-gateway`, `approval-token`, or RBAC references are expected in architecture/security documents and are not credentials.

## Required scanner behavior
Use high-confidence credential patterns for commit blocking:
- private key blocks
- AWS access keys
- GitHub tokens
- OpenAI-style secret keys
- Slack tokens
- Google API keys
- explicit assignment of long credential-like values

Do not block on generic architecture terms.

017_SECRET_SCAN_FALSE_POSITIVE_CLASSIFIED
