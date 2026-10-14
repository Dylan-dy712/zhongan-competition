"""Serialize OCR trial requests across API and Worker processes on one host."""
from contextlib import contextmanager
import math
import os
import threading
import time

_lock = threading.Lock()
_finished = 0.0


@contextmanager
def ocr_request_slot(lock_path: str | None = None, interval: float = 1.1):
    global _finished
    with _lock:
        if not lock_path:
            delay = interval-(time.monotonic()-_finished)
            if delay > 0:
                time.sleep(delay)
            try:
                yield
            finally:
                _finished = time.monotonic()
            return
        if os.name != 'posix':
            raise RuntimeError('OCR_PROVIDER_ERROR:THROTTLE_CONFIG_INVALID')
        import fcntl
        try:
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise RuntimeError('OCR_PROVIDER_ERROR:THROTTLE_UNAVAILABLE') from None
        with os.fdopen(descriptor, 'r+', encoding='ascii') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stamp = stream.read().strip()
                try:
                    previous = float(stamp) if stamp else 0.0
                except ValueError:
                    previous = 0.0
                if not math.isfinite(previous):
                    previous = 0.0
                delay = interval-(time.time()-previous)
                if delay > 0:
                    time.sleep(min(delay, interval))
                try:
                    yield
                finally:
                    stream.seek(0)
                    stream.truncate()
                    stream.write(str(time.time()))
                    stream.flush()
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
