"""Durable state: one file, replaced atomically, written before a mutating request is answered.

`Journal.commit(version)` returns once a snapshot at least as new as `version` is on disk
(file synced, renamed over the old one, directory synced). Concurrent committers share
snapshots: the first becomes the writer and takes a snapshot covering every mutation made
so far; the others wait for it and write again only if theirs was newer.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable

log = logging.getLogger("dossier.persistence")

STATE_FILE = "state.json"


def write_atomic(path: str, data: bytes) -> None:
    """Replace `path` with `data` so that after a crash it holds either the old or the new bytes."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dir_fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def read_state(directory: str) -> bytes | None:
    try:
        with open(os.path.join(directory, STATE_FILE), "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


class Journal:
    def __init__(self, directory: str, snapshot: Callable[[], tuple[int, bytes]]):
        os.makedirs(directory, exist_ok=True)
        self.path = os.path.join(directory, STATE_FILE)
        self._snapshot = snapshot
        self._cv = threading.Condition()
        self._written = 0
        self._busy = False

    def commit(self, version: int) -> None:
        while True:
            with self._cv:
                if self._written >= version:
                    return
                if self._busy:
                    self._cv.wait()
                    continue
                self._busy = True
            done = 0
            try:
                done, data = self._snapshot()
                write_atomic(self.path, data)
            except BaseException:
                done = 0
                raise
            finally:
                with self._cv:
                    self._busy = False
                    self._written = max(self._written, done)
                    self._cv.notify_all()
