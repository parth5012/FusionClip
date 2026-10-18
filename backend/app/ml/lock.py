"""Distributed Inference Execution Seam for multi-worker GPU memory admission.

Replaces single-process threading.RLock with:
1. RedisDistributedLock: Distributed mutex with heartbeat auto-renew & crash protection.
2. InMemoryLockAdapter: Non-blocking in-memory RLock adapter for CI/unit tests.

Satisfies: "one adapter = hypothetical seam, two adapters = real seam".
"""

from __future__ import annotations

import abc
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Channel for cross-worker VRAM eviction broadcast
EVICTION_CHANNEL = "ml:gpu:evict"

# Lua scripts for atomic Redis lock operations in production
_LUA_EXTEND = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
else
    return 0
end
"""

_LUA_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class InferenceLockTimeoutError(TimeoutError):
    """Raised when acquiring the inference lock times out."""
    pass


class InferenceLockSeam(abc.ABC):
    """Abstract interface defining the inference lock seam."""

    device: int

    @abc.abstractmethod
    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """Acquire the inference lock."""
        raise NotImplementedError

    @abc.abstractmethod
    def release(self) -> None:
        """Release the inference lock."""
        raise NotImplementedError

    @abc.abstractmethod
    def locked(self) -> bool:
        """Return True if the lock is currently held."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_owner(self) -> bool:
        """Return True if the current thread is the confirmed holder of the lock."""
        raise NotImplementedError

    def __enter__(self) -> "InferenceLockSeam":
        if not self.acquire(blocking=True):
            raise InferenceLockTimeoutError(
                f"Failed to acquire inference lock for device {self.device}"
            )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class InMemoryLockAdapter(InferenceLockSeam):
    """In-memory lock adapter backed by threading.RLock.

    Used in local development, single-process tests, and CI where Redis is absent.
    """

    def __init__(self, device: int = 0) -> None:
        self.device = device
        self._lock = threading.RLock()
        self._owner_thread: Optional[int] = None
        self._reentrancy = 0
        self._state_lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        current_thread = threading.get_ident()
        with self._state_lock:
            if self._owner_thread == current_thread:
                self._reentrancy += 1
                return True

        if blocking:
            if timeout is not None and timeout >= 0:
                acquired = self._lock.acquire(blocking=True, timeout=timeout)
            else:
                acquired = self._lock.acquire(blocking=True)
        else:
            acquired = self._lock.acquire(blocking=False)

        if acquired:
            with self._state_lock:
                self._owner_thread = current_thread
                self._reentrancy = 1
        return acquired

    def release(self) -> None:
        current_thread = threading.get_ident()
        with self._state_lock:
            if self._owner_thread != current_thread:
                raise RuntimeError("Cannot release un-acquired lock or lock owned by another thread")
            self._reentrancy -= 1
            if self._reentrancy == 0:
                self._owner_thread = None
                self._lock.release()

    def locked(self) -> bool:
        with self._state_lock:
            return self._owner_thread is not None

    def is_owner(self) -> bool:
        current_thread = threading.get_ident()
        with self._state_lock:
            return self._owner_thread == current_thread

    def __enter__(self) -> "InMemoryLockAdapter":
        if not self.acquire(blocking=True):
            raise InferenceLockTimeoutError(
                f"Failed to acquire in-memory inference lock for device {self.device}"
            )
        return self


class RedisDistributedLock(InferenceLockSeam):
    """Redis-backed distributed lock with lease auto-renew (heartbeat).

    Ensures mutual exclusion across multiple FastAPI and Celery worker processes.
    Provides:
    - Safe acquisition with unique ownership tokens.
    - Lease TTL with background heartbeat daemon to prevent dead-worker lockouts.
    - Thread-local re-entrancy for nested caller blocks.
    - Atomic release and extend via Lua scripts or pipeline WATCH/MULTI/EXEC.
    - Eviction broadcast via Redis Pub/Sub.
    """

    def __init__(
        self,
        redis_client: Any,
        device: int = 0,
        lock_name: Optional[str] = None,
        lease_ttl: float = 60.0,
        heartbeat_interval: float = 15.0,
        default_timeout: float = 120.0,
    ) -> None:
        self.redis_client = redis_client
        self.device = device
        self.lock_name = lock_name or f"ml:lock:gpu:{device}"
        self.lease_ttl = lease_ttl
        self.heartbeat_interval = heartbeat_interval
        self.default_timeout = default_timeout

        self._instance_token = uuid.uuid4().hex
        self._thread_locals = threading.local()
        self._heartbeat_threads: dict[int, tuple[threading.Thread, threading.Event]] = {}
        self._lost_threads: dict[int, bool] = {}
        self._lease_deadlines: dict[int, float] = {}
        self._state_lock = threading.Lock()

        self._lua_extend = None
        self._lua_release = None
        try:
            self._lua_extend = self.redis_client.register_script(_LUA_EXTEND)
            self._lua_release = self.redis_client.register_script(_LUA_RELEASE)
        except Exception:
            pass

    def _get_owner_token(self) -> str:
        tid = threading.get_ident()
        return f"{self._instance_token}:{os.getpid()}:{tid}"

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        if timeout is None:
            timeout = self.default_timeout if blocking else 0.0

        owner_token = self._get_owner_token()
        reentrancy = getattr(self._thread_locals, "reentrancy", 0)

        # Thread-local reentrancy check
        if reentrancy > 0:
            self._thread_locals.reentrancy = reentrancy + 1
            return True

        ttl_ms = int(self.lease_ttl * 1000)
        start_time = time.monotonic()

        while True:
            acquired = bool(
                self.redis_client.set(self.lock_name, owner_token, nx=True, px=ttl_ms)
            )
            if acquired:
                tid = threading.get_ident()
                with self._state_lock:
                    self._lease_deadlines[tid] = time.monotonic() + self.lease_ttl
                self._thread_locals.reentrancy = 1
                self._start_heartbeat(owner_token)
                return True

            if not blocking:
                return False

            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                return False

            sleep_time = min(0.05, max(0.005, timeout - elapsed))
            time.sleep(sleep_time)

    def _atomic_release(self, owner_token: str) -> bool:
        """Release key atomically if value matches owner_token."""
        try:
            if self._lua_release:
                res = self._lua_release(keys=[self.lock_name], args=[owner_token])
                return bool(res)
        except Exception:
            pass

        # Fallback to WATCH/MULTI/EXEC for fakeredis or redis without Lua
        try:
            with self.redis_client.pipeline() as pipe:
                pipe.watch(self.lock_name)
                val = pipe.get(self.lock_name)
                if isinstance(val, bytes):
                    val = val.decode("utf-8")
                if val == owner_token:
                    pipe.multi()
                    pipe.delete(self.lock_name)
                    pipe.execute()
                    return True
                pipe.unwatch()
                return False
        except Exception as e:
            logger.warning(f"Error releasing Redis lock {self.lock_name}: {e}")
            return False

    def _atomic_extend(self, owner_token: str, ttl_ms: int) -> bool:
        """Extend key TTL atomically if value matches owner_token.

        Returns:
            True if key matched and TTL was extended.
            False if key does not match owner_token (confirmed ownership loss).
        Raises:
            Exception on transient Redis/network errors.
        """
        if self._lua_extend:
            try:
                res = self._lua_extend(keys=[self.lock_name], args=[owner_token, ttl_ms])
                return bool(res)
            except Exception as e:
                # If Redis script error occurs or connection failed, fallback or re-raise
                logger.debug(f"Lua extend error for {self.lock_name}: {e}")

        with self.redis_client.pipeline() as pipe:
            pipe.watch(self.lock_name)
            val = pipe.get(self.lock_name)
            if isinstance(val, bytes):
                val = val.decode("utf-8")
            if val == owner_token:
                pipe.multi()
                pipe.pexpire(self.lock_name, ttl_ms)
                pipe.execute()
                return True
            pipe.unwatch()
            return False

    def release(self) -> None:
        owner_token = self._get_owner_token()
        reentrancy = getattr(self._thread_locals, "reentrancy", 0)

        if reentrancy <= 0:
            raise RuntimeError(f"Cannot release un-acquired lock {self.lock_name}")

        if reentrancy > 1:
            self._thread_locals.reentrancy = reentrancy - 1
            return

        # Outermost release
        self._thread_locals.reentrancy = 0
        self._stop_heartbeat()
        self._atomic_release(owner_token)

    def locked(self) -> bool:
        reentrancy = getattr(self._thread_locals, "reentrancy", 0)
        if reentrancy > 0:
            return True
        try:
            return bool(self.redis_client.exists(self.lock_name))
        except Exception:
            return False

    def is_owner(self) -> bool:
        tid = threading.get_ident()
        with self._state_lock:
            if self._lost_threads.get(tid, False):
                return False
            deadline = self._lease_deadlines.get(tid, 0.0)
            if deadline and time.monotonic() > deadline:
                return False
        reentrancy = getattr(self._thread_locals, "reentrancy", 0)
        return reentrancy > 0

    def _start_heartbeat(self, owner_token: str) -> None:
        tid = threading.get_ident()
        stop_event = threading.Event()
        ttl_ms = int(self.lease_ttl * 1000)

        def _heartbeat_worker() -> None:
            while not stop_event.wait(timeout=self.heartbeat_interval):
                now = time.monotonic()
                with self._state_lock:
                    deadline = self._lease_deadlines.get(tid, 0.0)

                # Check if the lease deadline expired while waiting or retrying
                if deadline and now >= deadline:
                    logger.error(
                        f"Redis lock {self.lock_name} lease deadline expired without successful renewal"
                    )
                    with self._state_lock:
                        self._lost_threads[tid] = True
                    break

                try:
                    success = self._atomic_extend(owner_token, ttl_ms)
                except Exception as ex:
                    # Transient error: keep retrying while lease is still valid
                    logger.warning(
                        f"Transient heartbeat renewal error for {self.lock_name}: {ex}; will retry"
                    )
                    if time.monotonic() >= deadline:
                        logger.error(
                            f"Redis lock {self.lock_name} lease expired during renewal errors"
                        )
                        with self._state_lock:
                            self._lost_threads[tid] = True
                        break
                    continue

                if not success:
                    logger.error(
                        f"Redis lock {self.lock_name} heartbeat renewal failed (lost lock ownership)"
                    )
                    with self._state_lock:
                        self._lost_threads[tid] = True
                    break

                # Renewal succeeded: advance lease deadline
                with self._state_lock:
                    self._lease_deadlines[tid] = time.monotonic() + self.lease_ttl

        hb_thread = threading.Thread(target=_heartbeat_worker, daemon=True)
        with self._state_lock:
            self._heartbeat_threads[tid] = (hb_thread, stop_event)
            self._lost_threads[tid] = False
        hb_thread.start()

    def _stop_heartbeat(self) -> None:
        tid = threading.get_ident()
        with self._state_lock:
            pair = self._heartbeat_threads.pop(tid, None)
            self._lost_threads.pop(tid, None)
            self._lease_deadlines.pop(tid, None)
        if pair:
            _, stop_event = pair
            stop_event.set()

    def broadcast_eviction(self, reason: str = "") -> int:
        """Publish an eviction request across all worker processes."""
        payload = json.dumps({
            "device": self.device,
            "reason": reason,
            "timestamp": time.time(),
        })
        try:
            return self.redis_client.publish(EVICTION_CHANNEL, payload)
        except Exception as e:
            logger.error(f"Failed to publish eviction message: {e}")
            return 0

    def subscribe_eviction(self, callback: Callable[[str], None]) -> threading.Event:
        """Subscribe to eviction requests and run callback when notified."""
        stop_event = threading.Event()
        pubsub = self.redis_client.pubsub()
        pubsub.subscribe(EVICTION_CHANNEL)

        def _listener() -> None:
            try:
                while not stop_event.is_set():
                    msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                    if msg and msg.get("type") == "message":
                        data = msg.get("data")
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        try:
                            callback(str(data))
                        except Exception as cb_err:
                            logger.error(f"Error in eviction callback: {cb_err}")
            finally:
                try:
                    pubsub.unsubscribe(EVICTION_CHANNEL)
                    pubsub.close()
                except Exception:
                    pass

        t = threading.Thread(target=_listener, daemon=True)
        t.start()
        return stop_event

    def __enter__(self) -> "RedisDistributedLock":
        if not self.acquire(blocking=True):
            raise InferenceLockTimeoutError(
                f"Failed to acquire distributed inference lock for device {self.device}"
            )
        return self


def get_inference_lock(
    device: int = 0,
    redis_client: Optional[Any] = None,
    force_in_memory: bool = False,
    lease_ttl: float = 60.0,
    heartbeat_interval: float = 15.0,
    default_timeout: float = 120.0,
) -> InferenceLockSeam:
    """Factory creating the appropriate inference lock seam adapter.

    Selection rules:
    - force_in_memory=True or INFERENCE_LOCK_BACKEND='memory': Returns InMemoryLockAdapter.
    - Explicit redis_client passed: Returns RedisDistributedLock.
    - INFERENCE_LOCK_BACKEND='redis': Connects to Redis; fails fast (raises error) if unreachable.
    - Default (no explicit backend configured): Attempts connection with 2s timeout.
      Falls back to InMemoryLockAdapter with ERROR log if unreachable.
    """
    backend = os.getenv("INFERENCE_LOCK_BACKEND", "").lower()
    if force_in_memory or backend == "memory":
        return InMemoryLockAdapter(device=device)

    if redis_client is not None:
        return RedisDistributedLock(
            redis_client=redis_client,
            device=device,
            lease_ttl=lease_ttl,
            heartbeat_interval=heartbeat_interval,
            default_timeout=default_timeout,
        )

    import redis
    from app.config import settings

    if backend == "redis":
        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=5.0, socket_timeout=5.0
        )
        try:
            client.ping()
        except redis.RedisError as e:
            logger.error(f"Inference lock backend 'redis' unreachable for device {device}: {e}")
            raise
        return RedisDistributedLock(
            redis_client=client,
            device=device,
            lease_ttl=lease_ttl,
            heartbeat_interval=heartbeat_interval,
            default_timeout=default_timeout,
        )

    # Default fallback mode
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2.0, socket_timeout=2.0
        )
        client.ping()
        return RedisDistributedLock(
            redis_client=client,
            device=device,
            lease_ttl=lease_ttl,
            heartbeat_interval=heartbeat_interval,
            default_timeout=default_timeout,
        )
    except Exception as e:
        logger.error(
            f"Redis unreachable ({e}); falling back to InMemoryLockAdapter for device {device}"
        )
        return InMemoryLockAdapter(device=device)
