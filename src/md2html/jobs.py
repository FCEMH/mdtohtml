from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Job:
    id: str
    status: str  # "queued", "running", "cancelling", "cancelled", "success", "warning", "failed"
    request: dict[str, Any]
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    process: subprocess.Popen | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    staging_file: Path | None = None


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start_job(self, request_data: dict[str, Any]) -> str:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        job = Job(
            id=job_id,
            status="queued",
            request=request_data,
            progress={"stage": "queued", "current": 0, "total": 1, "message": "排队中..."},
        )
        with self._lock:
            self._jobs[job_id] = job

        t = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        t.start()
        return job_id

    def _run_job(self, job: Job) -> None:
        with job.lock:
            if job.status == "cancelled":
                return
            job.status = "running"
            job.progress = {"stage": "prepare", "current": 0, "total": 1, "message": "启动构建进程..."}

        # Calculate staging file if output is specified
        if job.request.get("output"):
            out = Path(job.request["output"])
            job.staging_file = out.parent / f".staging.{job.id}_{out.name}"

        payload = {
            "job_id": job.id,
            **job.request,
        }

        # Build clean environment without corrupted PYTHONPATH
        env = dict(os.environ)
        # Ensure system dist-packages is in path or pythonpath doesn't have ROS conflicts
        env["PYTHONPATH"] = ""

        try:
            # preexec_fn=os.setsid creates an independent process group on Linux
            proc = subprocess.Popen(
                [sys.executable, "-m", "md2html.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                preexec_fn=os.setsid,
            )
            job.process = proc
        except Exception as e:
            with job.lock:
                job.status = "failed"
                job.result = {"status": "failed", "error_message": f"无法启动构建进程: {e}"}
            return

        # Send request payload
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        # Stream stdout lines
        result_payload = None
        for line in iter(proc.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = data.get("event")
            if event == "progress":
                with job.lock:
                    if job.status in ("running", "queued"):
                        job.progress = {
                            "stage": data.get("stage", "running"),
                            "current": data.get("current", 0),
                            "total": data.get("total", 1),
                            "source": data.get("source", ""),
                            "message": data.get("message", ""),
                        }
            elif event == "result":
                result_payload = data

        proc.wait()
        stderr_output = proc.stderr.read()

        with job.lock:
            if job.status == "cancelling" or job.status == "cancelled":
                job.status = "cancelled"
                if job.staging_file and job.staging_file.exists():
                    job.staging_file.unlink(missing_ok=True)
                return

            if result_payload:
                job.result = result_payload
                job.status = result_payload.get("status", "success")
                if job.status == "success":
                    job.progress = {"stage": "done", "current": 1, "total": 1, "message": "生成完成"}
            else:
                job.status = "failed"
                job.result = {
                    "status": "failed",
                    "error_message": stderr_output.strip() or "工作进程异常退出",
                }

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return False

        with job.lock:
            if job.status in ("success", "warning", "failed", "cancelled"):
                return False  # Already finished/committed
            job.status = "cancelling"
            proc = job.process

        if proc and proc.poll() is None:
            try:
                # Terminate the whole process group
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                # Wait up to 2 seconds for graceful shutdown
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

        with job.lock:
            job.status = "cancelled"
            job.progress = {"stage": "cancelled", "current": 0, "total": 1, "message": "已取消"}
            if job.staging_file and job.staging_file.exists():
                job.staging_file.unlink(missing_ok=True)

        return True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return None

        with job.lock:
            return {
                "id": job.id,
                "status": job.status,
                "progress": dict(job.progress),
                "result": dict(job.result) if job.result else None,
            }


# Global job manager instance
job_manager = JobManager()
