# -*- coding: utf-8 -*-
"""
Redis Stream Reader - Reliable Signal Ingestion
================================================
Shared helper for consuming Redis streams in both trader.py and trader-asjad.py.

Features:
- Consumer group mode (XREADGROUP) with automatic group creation
- Plain mode (XREAD) fallback with last_id persistence  
- Self-healing on NOGROUP errors
- Minimal logging (one line per event type)

This module handles ONLY stream reading/acking. No trading logic.
"""

import os
import socket
import time
import logging
from typing import Optional, List, Tuple, Any, Dict

logger = logging.getLogger(__name__)


class RedisStreamReader:
    """
    Reliable Redis stream reader with consumer group support and self-healing.
    
    Supports two modes:
    - "group": Uses XREADGROUP with consumer groups (default, recommended)
    - "plain": Uses plain XREAD with last_id persistence (fallback)
    """
    
    def __init__(
        self,
        redis_client,
        stream: str,
        mode: str = "group",
        group: Optional[str] = None,
        consumer: Optional[str] = None,
        last_id_key: Optional[str] = None,
        start_id_plain: str = "$",
        account_id: str = "default"
    ):
        """
        Initialize the stream reader.
        
        Args:
            redis_client: Redis client instance
            stream: Stream name (e.g., "signals:trading")
            mode: "group" (XREADGROUP) or "plain" (XREAD)
            group: Consumer group name (auto-generated if None)
            consumer: Consumer name (auto-generated if None)
            last_id_key: Redis key for persisting last_id in plain mode
            start_id_plain: Starting ID for plain mode ("$" = latest, "0-0" = all)
            account_id: Account identifier for unique group/consumer names
        """
        self.redis = redis_client
        self.stream = stream
        self.mode = mode.lower() if mode else "group"
        self.account_id = account_id
        
        # Generate defaults for group mode
        self.group = group or f"trader:{account_id}"
        self.consumer = consumer or f"{socket.gethostname()}:{os.getpid()}"
        
        # Plain mode settings
        self.last_id_key = last_id_key or f"trader:last_id:{account_id}:{stream.replace(':', '_')}"
        self.start_id_plain = start_id_plain
        self._plain_last_id = None
        
        # State tracking
        self._group_ensured = False
        self._last_nogroup_warn_ts = 0
        self._nogroup_warn_interval = 60  # Only warn once per 60s
        
        # Log effective settings on init
        logger.info(
            f"TRADER_STREAM_MODE | stream={stream} | mode={self.mode} | "
            f"group={self.group if self.mode == 'group' else 'N/A'} | "
            f"consumer={self.consumer if self.mode == 'group' else 'N/A'}"
        )
        
        # Warn if plain mode (weaker semantics)
        if self.mode == "plain":
            logger.warning(
                f"WARN_PLAIN_MODE_MULTI_TRADER_RISK | stream={stream} | "
                "Plain mode has weaker delivery guarantees"
            )
    
    def ensure_group(self) -> bool:
        """
        Ensure the consumer group exists, creating it if necessary.
        
        Uses MKSTREAM to create the stream if it doesn't exist.
        Swallows BUSYGROUP error if group already exists.
        
        Returns:
            True if group is ready, False on error
        """
        if self._group_ensured:
            return True
            
        try:
            # Create group with MKSTREAM (creates stream if needed)
            self.redis.xgroup_create(
                self.stream, 
                self.group, 
                id="$",  # Start from new messages
                mkstream=True
            )
            logger.info(
                f"CONSUMER_GROUP_READY | stream={self.stream} | "
                f"group={self.group} | consumer={self.consumer} | created=True"
            )
            self._group_ensured = True
            return True
            
        except Exception as e:
            error_str = str(e).upper()
            
            if "BUSYGROUP" in error_str:
                # Group already exists - this is fine
                if not self._group_ensured:
                    logger.info(
                        f"CONSUMER_GROUP_READY | stream={self.stream} | "
                        f"group={self.group} | consumer={self.consumer} | created=False"
                    )
                self._group_ensured = True
                return True
            else:
                logger.error(f"Failed to create consumer group: {e}")
                return False
    
    def _is_nogroup_error(self, exception: Exception) -> bool:
        """Check if exception is a NOGROUP error."""
        return "NOGROUP" in str(exception).upper()
    
    def _handle_nogroup(self, op_name: str) -> bool:
        """
        Handle NOGROUP error by recreating the group.
        
        Args:
            op_name: Name of the operation that failed
            
        Returns:
            True if healed successfully
        """
        now = time.time()
        
        # Rate-limit warnings
        if now - self._last_nogroup_warn_ts >= self._nogroup_warn_interval:
            logger.warning(
                f"CONSUMER_GROUP_HEAL | op={op_name} | stream={self.stream} | "
                f"group={self.group} | healing..."
            )
            self._last_nogroup_warn_ts = now
        
        # Reset state and recreate
        self._group_ensured = False
        return self.ensure_group()
    
    def read(self, block_ms: int = 1000, count: int = 10) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Read messages from the stream.
        
        Args:
            block_ms: Block timeout in milliseconds
            count: Maximum number of messages to read
            
        Returns:
            List of (message_id, message_data) tuples
        """
        if self.mode == "group":
            return self._read_group(block_ms, count)
        else:
            return self._read_plain(block_ms, count)
    
    def _read_group(self, block_ms: int, count: int) -> List[Tuple[str, Dict[str, Any]]]:
        """Read using XREADGROUP (consumer group mode)."""
        # Ensure group exists
        if not self.ensure_group():
            return []
        
        try:
            streams = self.redis.xreadgroup(
                self.group,
                self.consumer,
                {self.stream: ">"},  # Read only new messages
                count=count,
                block=block_ms
            )
            
            if not streams:
                return []
            
            # Flatten: streams is [(stream_name, [(msg_id, msg_data), ...])]
            messages = []
            for stream_name, stream_messages in streams:
                for msg_id, msg_data in stream_messages:
                    messages.append((msg_id, msg_data))
            
            return messages
            
        except Exception as e:
            if self._is_nogroup_error(e):
                if self._handle_nogroup("xreadgroup"):
                    # Retry once after healing
                    try:
                        streams = self.redis.xreadgroup(
                            self.group,
                            self.consumer,
                            {self.stream: ">"},
                            count=count,
                            block=block_ms
                        )
                        if not streams:
                            return []
                        messages = []
                        for stream_name, stream_messages in streams:
                            for msg_id, msg_data in stream_messages:
                                messages.append((msg_id, msg_data))
                        return messages
                    except Exception as retry_err:
                        logger.debug(f"XREADGROUP retry failed: {retry_err}")
                        return []
            else:
                logger.debug(f"XREADGROUP error: {e}")
            return []
    
    def _read_plain(self, block_ms: int, count: int) -> List[Tuple[str, Dict[str, Any]]]:
        """Read using plain XREAD."""
        # Load last_id from Redis if not cached
        if self._plain_last_id is None:
            try:
                stored_id = self.redis.get(self.last_id_key)
                if stored_id:
                    self._plain_last_id = stored_id.decode() if isinstance(stored_id, bytes) else stored_id
                else:
                    self._plain_last_id = self.start_id_plain
            except Exception as e:
                logger.debug(f"Failed to load last_id: {e}")
                self._plain_last_id = self.start_id_plain
        
        try:
            streams = self.redis.xread(
                {self.stream: self._plain_last_id},
                count=count,
                block=block_ms
            )
            
            if not streams:
                return []
            
            messages = []
            for stream_name, stream_messages in streams:
                for msg_id, msg_data in stream_messages:
                    messages.append((msg_id, msg_data))
            
            return messages
            
        except Exception as e:
            logger.debug(f"XREAD error: {e}")
            return []
    
    def ack(self, msg_id: str) -> bool:
        """
        Acknowledge a message (group mode only).
        
        In plain mode, this is a no-op - use commit_last_id instead.
        
        Args:
            msg_id: Message ID to acknowledge
            
        Returns:
            True on success
        """
        if self.mode != "group":
            return True  # No-op in plain mode
        
        try:
            self.redis.xack(self.stream, self.group, msg_id)
            return True
        except Exception as e:
            if self._is_nogroup_error(e):
                if self._handle_nogroup("xack"):
                    try:
                        self.redis.xack(self.stream, self.group, msg_id)
                        return True
                    except Exception:
                        pass
            logger.debug(f"XACK failed for {msg_id}: {e}")
            return False
    
    def commit_last_id(self, msg_id: str) -> bool:
        """
        Commit the last processed message ID (plain mode).
        
        This persists the ID to Redis for restart continuity.
        
        Args:
            msg_id: Message ID to commit
            
        Returns:
            True on success
        """
        try:
            self.redis.set(self.last_id_key, msg_id)
            self._plain_last_id = msg_id
            return True
        except Exception as e:
            logger.debug(f"Failed to commit last_id: {e}")
            return False
    
    def get_pending_count(self) -> int:
        """
        Get count of pending (unacked) messages for this consumer.
        
        Returns:
            Number of pending messages, or 0 on error/plain mode
        """
        if self.mode != "group":
            return 0
        
        try:
            pending = self.redis.xpending(self.stream, self.group)
            if pending and len(pending) >= 1:
                return pending[0]  # First element is total pending count
            return 0
        except Exception as e:
            if self._is_nogroup_error(e):
                self._handle_nogroup("xpending")
            return 0
    
    def claim_stale_messages(self, min_idle_ms: int = 60000, count: int = 10) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Claim stale messages from other consumers (group mode only).
        
        Useful for recovering messages from crashed consumers.
        
        Args:
            min_idle_ms: Minimum idle time before claiming
            count: Maximum messages to claim
            
        Returns:
            List of claimed (message_id, message_data) tuples
        """
        if self.mode != "group":
            return []
        
        try:
            # Get pending entries for this consumer
            pending = self.redis.xpending_range(
                self.stream,
                self.group,
                min="-",
                max="+",
                count=count
            )
            
            if not pending:
                return []
            
            # Claim messages that have been idle too long
            claimed = []
            for entry in pending:
                msg_id = entry.get('message_id') or entry.get('message-id')
                idle = entry.get('time_since_delivered') or entry.get('idle', 0)
                
                if msg_id and idle >= min_idle_ms:
                    try:
                        result = self.redis.xclaim(
                            self.stream,
                            self.group,
                            self.consumer,
                            min_idle_ms,
                            [msg_id]
                        )
                        if result:
                            for claimed_id, claimed_data in result:
                                claimed.append((claimed_id, claimed_data))
                    except Exception as claim_err:
                        if self._is_nogroup_error(claim_err):
                            self._handle_nogroup("xclaim")
                            break
                        logger.debug(f"XCLAIM failed for {msg_id}: {claim_err}")
            
            return claimed
            
        except Exception as e:
            if self._is_nogroup_error(e):
                self._handle_nogroup("xpending_range")
            return []


def get_stream_reader_config(account_id: str = "default") -> Dict[str, Any]:
    """
    Get stream reader configuration from environment.
    
    Args:
        account_id: Account identifier (primary, asjad, etc.)
        
    Returns:
        Dict with configuration values
    """
    return {
        "mode": os.getenv("TRADER_SIGNAL_READ_MODE", "group"),
        "group": os.getenv("TRADER_CONSUMER_GROUP", f"trader:{account_id}"),
        "consumer": os.getenv("TRADER_CONSUMER_NAME", f"{socket.gethostname()}:{os.getpid()}"),
        "start_id_plain": os.getenv("TRADER_STREAM_START_ID_PLAIN", "$"),
    }

