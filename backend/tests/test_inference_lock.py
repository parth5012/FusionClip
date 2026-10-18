import time
import threading
import pytest
import fakeredis

from app.ml.lock import (
    InferenceLockSeam,
    InMemoryLockAdapter,
    RedisDistributedLock,
    InferenceLockTimeoutError,
    get_inference_lock,
)


def test_in_memory_lock_acquire_release():
    lock = InMemoryLockAdapter(device=0)
    assert not lock.locked()
    assert lock.acquire() is True
    assert lock.locked() is True
    lock.release()
    assert not lock.locked()


def test_in_memory_lock_context_manager():
    lock = InMemoryLockAdapter(device=0)
    with lock:
        assert lock.locked() is True
    assert not lock.locked()


def test_in_memory_lock_reentrancy():
    lock = InMemoryLockAdapter(device=0)
    with lock:
        assert lock.locked() is True
        with lock:
            assert lock.locked() is True
        assert lock.locked() is True
    assert not lock.locked()


def test_in_memory_lock_contention_timeout():
    lock = InMemoryLockAdapter(device=0)
    acquired_in_thread = threading.Event()
    release_thread = threading.Event()

    def worker():
        with lock:
            acquired_in_thread.set()
            release_thread.wait(timeout=2.0)

    t = threading.Thread(target=worker)
    t.start()
    assert acquired_in_thread.wait(timeout=1.0) is True

    # Main thread tries non-blocking acquire
    assert lock.acquire(blocking=False) is False
    # Main thread tries acquire with short timeout
    assert lock.acquire(blocking=True, timeout=0.1) is False

    release_thread.set()
    t.join()

    # Now should be able to acquire
    assert lock.acquire(blocking=True, timeout=1.0) is True
    lock.release()


def test_redis_lock_acquire_release():
    fake_client = fakeredis.FakeStrictRedis()
    lock = RedisDistributedLock(redis_client=fake_client, device=0, lease_ttl=5.0)

    assert not lock.locked()
    assert lock.acquire() is True
    assert lock.locked() is True
    # Verify key in redis
    assert fake_client.exists("ml:lock:gpu:0") == 1

    lock.release()
    assert not lock.locked()
    assert fake_client.exists("ml:lock:gpu:0") == 0


def test_redis_lock_context_manager():
    fake_client = fakeredis.FakeStrictRedis()
    lock = RedisDistributedLock(redis_client=fake_client, device=0, lease_ttl=5.0)

    with lock:
        assert lock.locked() is True
        assert fake_client.exists("ml:lock:gpu:0") == 1

    assert not lock.locked()
    assert fake_client.exists("ml:lock:gpu:0") == 0


def test_redis_lock_context_manager_timeout():
    fake_client = fakeredis.FakeStrictRedis()
    fake_client.set("ml:lock:gpu:0", "other_worker_token", px=5000)

    lock = RedisDistributedLock(
        redis_client=fake_client, device=0, default_timeout=0.2
    )
    with pytest.raises(InferenceLockTimeoutError):
        with lock:
            pass


def test_redis_lock_reentrancy():
    fake_client = fakeredis.FakeStrictRedis()
    lock = RedisDistributedLock(redis_client=fake_client, device=0, lease_ttl=5.0)

    with lock:
        assert lock.locked() is True
        # Re-entrant acquire on same thread
        with lock:
            assert lock.locked() is True
        # Still locked after exiting inner context
        assert lock.locked() is True

    # Released only after exiting outermost context
    assert not lock.locked()
    assert fake_client.exists("ml:lock:gpu:0") == 0


def test_redis_lock_contention_between_clients():
    fake_server = fakeredis.FakeServer()
    client1 = fakeredis.FakeStrictRedis(server=fake_server)
    client2 = fakeredis.FakeStrictRedis(server=fake_server)

    lock1 = RedisDistributedLock(redis_client=client1, device=0, lease_ttl=1.0)
    lock2 = RedisDistributedLock(redis_client=client2, device=0, default_timeout=0.1)

    assert lock1.acquire() is True
    # client2 cannot acquire non-blocking
    assert lock2.acquire(blocking=False) is False
    # client2 times out
    assert lock2.acquire(blocking=True, timeout=0.05) is False

    # lock1 releases
    lock1.release()

    # Now client2 can acquire
    assert lock2.acquire(blocking=True, timeout=0.5) is True
    lock2.release()


def test_redis_lock_heartbeat_auto_renew():
    fake_client = fakeredis.FakeStrictRedis()
    lock = RedisDistributedLock(
        redis_client=fake_client,
        device=0,
        lease_ttl=1.0,
        heartbeat_interval=0.2,
    )
    assert lock.acquire() is True
    time.sleep(0.5)
    # Check that key still exists and TTL was refreshed
    pttl = fake_client.pttl("ml:lock:gpu:0")
    assert pttl > 0
    lock.release()
    assert not lock.locked()


def test_redis_lock_peer_eviction_pubsub():
    fake_server = fakeredis.FakeServer()
    client_pub = fakeredis.FakeStrictRedis(server=fake_server)
    client_sub = fakeredis.FakeStrictRedis(server=fake_server)

    evicted = []

    def on_evict(data):
        evicted.append(data)

    lock_sub = RedisDistributedLock(redis_client=client_sub, device=0)
    stop_event = lock_sub.subscribe_eviction(on_evict)

    # Allow subscription setup
    time.sleep(0.05)

    lock_pub = RedisDistributedLock(redis_client=client_pub, device=0)
    lock_pub.broadcast_eviction(reason="Need 13GB for FLUX")

    # Wait for pubsub message
    time.sleep(0.1)
    stop_event.set()

    assert len(evicted) >= 1
    assert "Need 13GB for FLUX" in evicted[0]


def test_get_inference_lock_factory():
    in_mem = get_inference_lock(device=0, force_in_memory=True)
    assert isinstance(in_mem, InMemoryLockAdapter)

    fake_client = fakeredis.FakeStrictRedis()
    redis_lock = get_inference_lock(device=1, redis_client=fake_client)
    assert isinstance(redis_lock, RedisDistributedLock)
    assert redis_lock.device == 1


def test_is_owner_semantics():
    in_mem = InMemoryLockAdapter(device=0)
    assert not in_mem.is_owner()
    with in_mem:
        assert in_mem.is_owner()
    assert not in_mem.is_owner()

    fake_client = fakeredis.FakeStrictRedis()
    redis_lock = RedisDistributedLock(redis_client=fake_client, device=0)
    assert not redis_lock.is_owner()
    with redis_lock:
        assert redis_lock.is_owner()
    assert not redis_lock.is_owner()


def test_heartbeat_ownership_loss_detection():
    fake_client = fakeredis.FakeStrictRedis()
    lock = RedisDistributedLock(
        redis_client=fake_client,
        device=0,
        lease_ttl=2.0,
        heartbeat_interval=0.1,
    )
    assert lock.acquire() is True
    assert lock.is_owner()

    # Simulate another worker forcibly stealing the key in Redis
    fake_client.set("ml:lock:gpu:0", "other_token")

    # Wait for next heartbeat renewal cycle
    time.sleep(0.25)

    # is_owner must detect that ownership was lost
    assert lock.is_owner() is False
    lock.release()


def test_heartbeat_lease_deadline_expiry_on_persistent_network_error():
    fake_client = fakeredis.FakeStrictRedis()
    lock = RedisDistributedLock(
        redis_client=fake_client,
        device=0,
        lease_ttl=0.3,
        heartbeat_interval=0.08,
    )
    assert lock.acquire() is True
    assert lock.is_owner()

    # Simulate persistent Redis connection failure on renewal
    def failing_extend(*args, **kwargs):
        raise ConnectionError("Redis connection dropped")

    lock._atomic_extend = failing_extend

    # Wait beyond lease TTL (0.3s)
    time.sleep(0.45)

    # is_owner must return False because lease deadline expired without renewal
    assert lock.is_owner() is False
    lock.release()


def test_get_inference_lock_env_selection(monkeypatch):
    monkeypatch.setenv("INFERENCE_LOCK_BACKEND", "memory")
    lock = get_inference_lock(device=0)
    assert isinstance(lock, InMemoryLockAdapter)

    # Test redis backend fails fast when unreachable
    monkeypatch.setenv("INFERENCE_LOCK_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://invalid-host-that-does-not-exist:6379/0")
    with pytest.raises(Exception):
        get_inference_lock(device=0)

