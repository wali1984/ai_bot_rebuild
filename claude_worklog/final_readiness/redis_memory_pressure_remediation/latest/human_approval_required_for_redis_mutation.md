# Human Approval Required For Redis Mutation

No Redis mutation is approved by this milestone.

Before any DEL, XDEL, XTRIM, SET, HSET, XADD, FLUSHALL, FLUSHDB, CONFIG SET, or retention mutation, the operator must approve:

- exact key/pattern
- exact command
- expected memory savings
- proof the key is not live-critical or has been offloaded
- backup/export command and verification
- rollback limitations
- post-action validation command

REDIS_MUTATION_REQUIRES_HUMAN_APPROVAL
