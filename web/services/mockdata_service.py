import os
import signal
import subprocess
import sys
import time

import yaml

MODULES = {
    "alert": {"name": "alert", "label": "告警数据",
              "output": "alerts_aiops / alerts_rule_aiops",
              "output_type": "topic"},
    "metrics": {"name": "metrics", "label": "基础指标",
                "output": "infra_metrics_aiops / apm_metrics_aiops",
                "output_type": "topic"},
    "trans-metrics": {"name": "trans-metrics", "label": "交易指标",
                      "output": "bpm_trans_metrics_aiops",
                      "output_type": "topic"},
    "trans-details": {"name": "trans-details", "label": "交易链路明细",
                      "output": "bpm_trans_details_aiops",
                      "output_type": "topic"},
    "itsm-devops": {"name": "itsm-devops", "label": "ITSM & DevOps",
                    "output": "itsm_devops / itsm_tickets",
                    "output_type": "table"},
}


class MockdataService:
    def __init__(self, mockdata_dir=None):
        self._mockdata_dir = mockdata_dir or self._find_mockdata_dir()
        self._processes = {}  # module_name -> subprocess.Popen
        self._last_started_at = {}
        self._last_stopped_at = {}

    @staticmethod
    def _find_mockdata_dir():
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        candidate = os.path.join(script_dir, "mockdata")
        if os.path.isdir(candidate):
            return candidate
        return os.path.join(os.getcwd(), "mockdata")

    def _get_script_path(self):
        return os.path.join(self._mockdata_dir, "run_mockdata.py")

    def _config_path(self):
        return os.path.join(self._mockdata_dir, "config", "common_config.yaml")

    def _logs_path(self):
        return os.path.join(self._mockdata_dir, "logs")

    def list_modules(self):
        result = {}
        for name, info in MODULES.items():
            m = dict(info)
            m["last_started_at"] = self._last_started_at.get(name)
            m["last_stopped_at"] = self._last_stopped_at.get(name)
            result[name] = m
        return result

    def get_all_status(self):
        self._cleanup_stale_processes()
        result = {}
        for name in MODULES:
            result[name] = self.get_module_status(name)
        return result

    def get_module_status(self, name):
        if name not in MODULES:
            return None
        info = MODULES[name]
        proc = self._processes.get(name)
        if proc is None:
            return {"name": name, "status": "stopped", "pid": None,
                    "started_at": None, "output": info["output"],
                    "output_type": info["output_type"],
                    "last_started_at": self._last_started_at.get(name),
                    "last_stopped_at": self._last_stopped_at.get(name)}
        ret = proc.poll()
        if ret is not None:
            del self._processes[name]
            self._last_stopped_at[name] = time.strftime("%Y-%m-%d %H:%M:%S")
            return {"name": name, "status": "stopped", "pid": None,
                    "started_at": None, "output": info["output"],
                    "output_type": info["output_type"],
                    "last_started_at": self._last_started_at.get(name),
                    "last_stopped_at": self._last_stopped_at.get(name)}
        return {"name": name, "status": "running", "pid": proc.pid,
                "started_at": getattr(proc, "_started_at", None),
                "output": info["output"],
                "output_type": info["output_type"],
                "last_started_at": self._last_started_at.get(name),
                "last_stopped_at": self._last_stopped_at.get(name)}

    def start_module(self, name):
        if name not in MODULES:
            return {"ok": False, "error": "未知模块: {}".format(name)}
        existing = self.get_module_status(name)
        if existing and existing["status"] == "running":
            return {"ok": False, "error": "模块 [{}] 已在运行中".format(name)}
        script = self._get_script_path()
        if not os.path.isfile(script):
            return {"ok": False, "error": "脚本不存在: {}".format(script)}
        try:
            proc = subprocess.Popen(
                [sys.executable, script, name],
                cwd=self._mockdata_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            started_at = time.strftime("%Y-%m-%d %H:%M:%S")
            proc._started_at = started_at
            self._last_started_at[name] = started_at
            self._processes[name] = proc
            return {"ok": True, "pid": proc.pid}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def stop_module(self, name):
        if name not in MODULES:
            return {"ok": False, "error": "未知模块: {}".format(name)}
        proc = self._processes.get(name)
        if proc is None:
            return {"ok": False, "error": "模块 [{}] 未在运行中".format(name)}
        try:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            del self._processes[name]
            self._last_stopped_at[name] = time.strftime("%Y-%m-%d %H:%M:%S")
            return {"ok": True}
        except ProcessLookupError:
            del self._processes[name]
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def read_config(self):
        path = self._config_path()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def write_config(self, cfg):
        path = self._config_path()
        try:
            dir_name = os.path.dirname(path)
            if not os.path.isdir(dir_name):
                os.makedirs(dir_name, exist_ok=True)
            with open(path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def read_config_raw(self):
        path = self._config_path()
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception:
            return ""

    def write_config_raw(self, text):
        path = self._config_path()
        try:
            dir_name = os.path.dirname(path)
            if not os.path.isdir(dir_name):
                os.makedirs(dir_name, exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def cleanup_orphans(self):
        for name, proc in list(self._processes.items()):
            ret = proc.poll()
            if ret is None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
        self._processes.clear()

    def _cleanup_stale_processes(self):
        for name, proc in list(self._processes.items()):
            ret = proc.poll()
            if ret is not None:
                self._last_stopped_at[name] = time.strftime("%Y-%m-%d %H:%M:%S")
                del self._processes[name]
