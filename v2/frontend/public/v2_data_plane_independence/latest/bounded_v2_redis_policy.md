# Bounded V2 Redis Policy

V2 Redis is transport/cache only. Every stream/key must have maxlen/TTL/namespace owner, source freshness, producer/consumer mapping, and dashboard memory bands. No audit/history accumulation in Redis. Legacy Redis trim remains deferred unless exact approval exists.
