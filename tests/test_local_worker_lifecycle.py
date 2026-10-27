"""Real harmless child regression for admission retention and parent-death cleanup."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

from meeting_memory.repo.local_transcription import LocalTranscriptionClient
from meeting_memory.types.local_transcription import LocalTranscriptionCancelled

CHILD = """
import sys,time
from pathlib import Path
from meeting_memory.repo.local_worker import read_request
from meeting_memory.repo.local_worker_lifetime import worker_parent_lifetime
request=Path(sys.argv[1])
row=read_request(request)
with worker_parent_lifetime(request,row):
 print('ready',flush=True)
 time.sleep(60)
"""

PARENT = """
import json,os,subprocess,sys,tempfile
from pathlib import Path
from meeting_memory.repo.local_process import child_environment,local_operation_lock
from meeting_memory.repo.local_worker_lifetime import LOCK_FD_ENV,TEMP_ROOT_ENV
root=Path(sys.argv[1])
request_dir=Path(tempfile.mkdtemp(prefix='meeting-memory-inference-',dir=root))
pcm_dir=Path(tempfile.mkdtemp(prefix='meeting-memory-decoding-',dir=root))
audio=pcm_dir/'decoded.wav'
audio.write_bytes(b'private fake PCM')
audio.chmod(0o600)
request=request_dir/'request.json'
request.write_text(json.dumps({'operation':'infer','cache':str(root/'cache'),'audio':str(audio)}))
request.chmod(0o600)
with local_operation_lock(
 progress=lambda _:None,cancelled=lambda:False,lock_path=root/'lock'
) as fd:
 env=child_environment(offline=True)
 env[LOCK_FD_ENV]=str(fd)
 env[TEMP_ROOT_ENV]=str(root.resolve())
 child=subprocess.Popen([sys.executable,'-c',sys.argv[2],str(request)],
  env=env,pass_fds=(fd,),stdout=subprocess.PIPE,text=True)
 if child.stdout.readline().strip()!='ready':
  raise RuntimeError('fake child did not reach lifetime guard')
 print(json.dumps({'pid':child.pid,'request':str(request_dir),'pcm':str(pcm_dir)}),flush=True)
 sys.stdin.read(1)
"""


def test_parent_death_keeps_lock_until_private_cleanup_and_child_exit(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    marker = cache / "keep-shared-weights"
    marker.write_text("never removed")
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    parent = subprocess.Popen(
        [sys.executable, "-c", PARENT, str(tmp_path), CHILD],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = None
    descriptor = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(parent.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=10), "fake parent did not report readiness"
        info = json.loads(parent.stdout.readline())
        child_pid = info["pid"]
        descriptor = os.open(tmp_path / "lock", os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("active operation did not retain admission")
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                assert time.monotonic() < deadline, "orphan retained admission"
                time.sleep(0.02)
        # Admission cannot reopen while the orphan's private inputs remain.
        assert not Path(info["request"]).exists()
        assert not Path(info["pcm"]).exists()
        assert marker.read_text() == "never removed"
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if child_pid:
            # The child may already have exited after its parent-death cleanup.
            with contextlib.suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)
        for stream in (parent.stdin, parent.stdout, parent.stderr):
            stream.close()


def test_client_close_permanently_rejects_new_admission_and_signals_active_child():
    import pytest

    class Child:
        terminated = False

        def terminate(self):
            self.terminated = True

    client = LocalTranscriptionClient()
    child = Child()
    client._track_process(child)
    client.close()
    assert child.terminated
    with pytest.raises(LocalTranscriptionCancelled):
        client.transcribe(None)
    late_child = Child()
    client._track_process(late_child)
    assert late_child.terminated
