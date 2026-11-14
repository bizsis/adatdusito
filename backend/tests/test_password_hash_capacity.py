"""SECURITY-01/1: bounded scrypt concurrency (threads and worker processes)."""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from app import security
from app.security import HashCapacityError, hash_password, verify_password

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_slots(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRYPT_LOCK_DIR", str(tmp_path / "slots"))
    monkeypatch.delenv("SCRYPT_CONCURRENCY", raising=False)
    monkeypatch.delenv("SCRYPT_QUEUE_TIMEOUT", raising=False)
    return tmp_path / "slots"


class ActivityMeter:
    """Wraps hashlib.scrypt and records the peak number of parallel calls."""

    def __init__(self, inner, delay=0.0):
        self.inner, self.delay = inner, delay
        self.lock = threading.Lock()
        self.active = self.peak = self.calls = 0

    def __call__(self, *args, **kwargs):
        with self.lock:
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
                return b"\0" * 64
            return self.inner(*args, **kwargs)
        finally:
            with self.lock:
                self.active -= 1


def run_threads(count, target):
    errors = []

    def wrapped(index):
        try:
            target(index)
        except Exception as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not errors, errors


def test_parameters_are_unchanged_and_existing_hashes_verify(password_hash):
    assert (security.SCRYPT_N, security.SCRYPT_R, security.SCRYPT_P) == (131072, 8, 1)
    assert verify_password("Test-password-2026!", password_hash)
    assert not verify_password("wrong", password_hash)
    assert not verify_password("x", "scrypt$zz$00")
    assert not verify_password("x", None)


def test_default_allows_two_parallel_hashes_for_hash_and_verify(monkeypatch):
    meter = ActivityMeter(None, delay=0.15)
    monkeypatch.setattr(security.hashlib, "scrypt", meter)
    encoded = "scrypt$" + "00" * 16 + "$" + "00" * 64

    def work(index):
        if index % 2:
            hash_password("Correct-horse-2026")
        else:
            assert verify_password("anything", encoded)

    run_threads(8, work)
    assert meter.calls == 8
    assert meter.peak == 2


def test_limit_is_configurable(monkeypatch):
    monkeypatch.setenv("SCRYPT_CONCURRENCY", "1")
    meter = ActivityMeter(None, delay=0.05)
    monkeypatch.setattr(security.hashlib, "scrypt", meter)
    run_threads(4, lambda i: hash_password("Correct-horse-2026"))
    assert meter.peak == 1


def test_overload_returns_controlled_503(monkeypatch):
    monkeypatch.setenv("SCRYPT_CONCURRENCY", "1")
    monkeypatch.setenv("SCRYPT_QUEUE_TIMEOUT", "0.1")
    with security.hash_slot():
        started = time.monotonic()
        with pytest.raises(HashCapacityError) as error:
            hash_password("Correct-horse-2026")
        assert time.monotonic() - started < 2
    assert error.value.status_code == 503
    assert error.value.headers["Retry-After"] == "5"
    # The slot is released afterwards.
    assert hash_password("Correct-horse-2026").startswith("scrypt$")


def test_slot_is_released_when_hashing_fails(monkeypatch):
    monkeypatch.setenv("SCRYPT_CONCURRENCY", "1")
    monkeypatch.setenv("SCRYPT_QUEUE_TIMEOUT", "0")

    def broken(*args, **kwargs):
        raise MemoryError("simulated")

    monkeypatch.setattr(security.hashlib, "scrypt", broken)
    for _ in range(3):
        with pytest.raises(MemoryError):
            hash_password("Correct-horse-2026")


def test_login_overload_is_http_503_with_retry_after(environment, monkeypatch):
    client = environment[0]
    monkeypatch.setenv("SCRYPT_CONCURRENCY", "1")
    monkeypatch.setenv("SCRYPT_QUEUE_TIMEOUT", "0.1")
    with security.hash_slot():
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "root@example.hu", "password": "Test-password-2026!"},
        )
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["error"]["code"] == "503"
    assert "Test-password" not in response.text


def test_slots_are_shared_between_worker_processes(isolated_slots, tmp_path):
    """Simulates several Uvicorn worker processes sharing one container."""
    log = tmp_path / "intervals"
    log.mkdir()
    start_at = time.time() + 1.5
    script = textwrap.dedent(
        f"""
        import json, os, time
        from app import security
        def slow(*args, **kwargs):
            began = time.time()
            time.sleep(0.3)
            with open(os.path.join({str(log)!r}, str(os.getpid())), "w") as f:
                json.dump([began, time.time()], f)
            return b"\\0" * 64
        security.hashlib.scrypt = slow
        time.sleep(max(0, {start_at!r} - time.time()))
        security.hash_password("Correct-horse-2026")
        """
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "SCRYPT_LOCK_DIR": str(isolated_slots),
        "SCRYPT_QUEUE_TIMEOUT": "30",
    }
    env.pop("SCRYPT_CONCURRENCY", None)
    processes = [
        subprocess.Popen([sys.executable, "-c", script], env=env) for _ in range(5)
    ]
    assert all(p.wait(60) == 0 for p in processes)
    intervals = [json.loads(f.read_text()) for f in log.iterdir()]
    assert len(intervals) == 5
    events = sorted(
        [(begin, 1) for begin, _ in intervals] + [(end, -1) for _, end in intervals],
        key=lambda event: (event[0], event[1]),
    )
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    assert peak <= 2


def test_load_with_real_scrypt_never_exceeds_two(monkeypatch, password_hash):
    """Load test: 12 concurrent real verifications (~128 MiB each)."""
    monkeypatch.setenv("SCRYPT_QUEUE_TIMEOUT", "120")
    meter = ActivityMeter(security.hashlib.scrypt)
    monkeypatch.setattr(security.hashlib, "scrypt", meter)
    results = []
    run_threads(
        12, lambda i: results.append(verify_password("Test-password-2026!", password_hash))
    )
    assert results == [True] * 12
    assert meter.peak <= 2
