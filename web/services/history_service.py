# -*- coding: utf-8 -*-
import json
import os
import threading
from datetime import datetime


class HistoryService(object):

    def __init__(self, history_path):
        self._history_path = history_path
        self._lock = threading.Lock()

    def _load(self):
        if not os.path.isfile(self._history_path):
            return {"runs": [], "counter": 0}
        try:
            with open(self._history_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return {"runs": [], "counter": 0}

    def _save(self, data):
        tmp = self._history_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._history_path)

    def create_run(self, components, hosts_count, mode="Web UI"):
        with self._lock:
            data = self._load()
            counter = data.get("counter", 0) + 1
            now = datetime.now()
            run = {
                "id": counter,
                "date": now.strftime("%Y-%m-%d"),
                "started_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "ended_at": None,
                "status": "running",
                "status_label": "运行中",
                "components": components,
                "hosts": hosts_count,
                "duration": None,
                "mode": mode,
                "logs": [],
            }
            data["runs"].insert(0, run)
            data["counter"] = counter
            self._save(data)
            return counter

    def update_run(self, run_id, status, status_label, duration=None, ended_at=None):
        with self._lock:
            data = self._load()
            for run in data["runs"]:
                if run["id"] == run_id:
                    run["status"] = status
                    run["status_label"] = status_label
                    if duration:
                        run["duration"] = duration
                    if ended_at:
                        run["ended_at"] = ended_at
                    break
            self._save(data)

    def append_log(self, run_id, time, level, tag, msg):
        with self._lock:
            data = self._load()
            for run in data["runs"]:
                if run["id"] == run_id:
                    run.setdefault("logs", []).append({
                        "time": time,
                        "level": level,
                        "tag": tag,
                        "msg": msg,
                    })
                    break
            self._save(data)

    def load_runs(self, limit=None):
        data = self._load()
        runs = data.get("runs", [])
        if limit:
            runs = runs[:limit]
        return runs

    def get_run(self, run_id):
        for run in self.load_runs():
            if run["id"] == run_id:
                return run
        return None
