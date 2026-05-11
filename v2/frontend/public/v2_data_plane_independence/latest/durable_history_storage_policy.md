# Durable History Storage Policy

Durable V2 storage must own liquidation history, feature snapshots, predictions, signals, execution intents, paper/shadow fills, positions, PnL, risk decisions, and audit events. Redis cannot be permanent historical truth. Records require IDs, timestamps, source freshness, schema version, and evidence pointers.
