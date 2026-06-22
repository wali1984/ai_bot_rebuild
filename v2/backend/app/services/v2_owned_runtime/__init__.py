"""V2-owned runtime adapters package.

Houses the Redis namespace adapter, exchange fail-closed adapter, and
config adapter that the V2-owned runtime wrappers use. None of these
modules import legacy code; they isolate the V2 side from legacy state.
"""
