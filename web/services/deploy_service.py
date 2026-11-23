# -*- coding: utf-8 -*-
import asyncio
import datetime
import json
import os
import re
import signal


class DeployService(object):

    def __init__(self, deploy_dir, web_settings_path, history_service=None):
        self._deploy_dir = deploy_dir
        self._web_settings_path = web_settings_path
        self._history_service = history_service
        self._lock = asyncio.Lock()
        self._process = None
        self._status = "idle"
        self._current_run_id = None
        self._run_start_time = None
        self._websockets = set()
        self._config_dir_default = os.path.join(deploy_dir, "conf", "template")

    def get_status(self):
        return self._status

    def is_running(self):
        return self._status == "running"

    def validate_params(self):
        """同步校验参数合法性，返回 None 或错误信息"""
        settings = self._load_web_settings()
        if not settings.get("install_dir") or not settings.get("package_dir"):
            return "install_dir 和 package_dir 不能为空，请在配置页面中设置"
        return None

    def _load_web_settings(self):
        if not os.path.isfile(self._web_settings_path):
            return {"install_dir": "", "package_dir": ""}
        try:
            with open(self._web_settings_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return {"install_dir": "", "package_dir": ""}

    def _build_command(self, config_path, install_dir, package_dir,
                       config_dir, localaddr, http_port, debug, fail_fast, service):
        venv_python = os.path.join(self._deploy_dir, ".venv", "bin", "python")
        if not os.path.isfile(venv_python):
            venv_python = "python3"
        install_script = os.path.join(self._deploy_dir, "install.py")
        cmd = [venv_python, "-u", install_script,
               "--nodesfile", config_path,
               "--install-dir", install_dir,
               "--package-dir", package_dir,
               "--localaddr", localaddr,
               "--http-port", str(http_port)]
        if config_dir:
            cmd.extend(["--config-dir", config_dir])
        if debug:
            cmd.append("--debug")
        if not fail_fast:
            cmd.append("--no-fail-fast")
        if service:
            cmd.extend(["--service", service])
        return cmd

    def _parse_log_line(self, line):
        text = line.rstrip("\n\r")
        level = "INFO"
        m = re.search(r'\[(INFO|ERROR|SUCCESS|WARNING|DEBUG)\]', text)
        if m:
            level = m.group(1)
        return {"text": text, "level": level}

    async def _broadcast(self, message):
        if not self._websockets:
            return
        data = json.dumps(message)
        stale = set()
        for ws in self._websockets:
            try:
                await ws.send_text(data)
            except Exception:
                stale.add(ws)
        self._websockets -= stale

    def register_websocket(self, ws):
        self._websockets.add(ws)

    def unregister_websocket(self, ws):
        self._websockets.discard(ws)

    def _count_hosts_and_components(self, config_path, service):
        try:
            import yaml
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            return 0, ""
        deploy_map = cfg.get("deploy", {})
        hosts_count = len(deploy_map)
        if service:
            comps = [s.strip().lower() for s in service.split(",")]
        else:
            comps = list(sorted(set(
                comp.lower() for hosts in deploy_map.values() for comp in hosts
            )))
        return hosts_count, ", ".join(comps)

    async def start_deploy(self, config_path, install_dir=None, package_dir=None,
                           config_dir=None, localaddr=None, http_port=8000,
                           debug=False, fail_fast=True, service=None):
        if self._lock.locked():
            raise RuntimeError("当前已有部署任务正在进行中")

        async with self._lock:
            settings = self._load_web_settings()
            if not install_dir:
                install_dir = settings.get("install_dir", "")
            if not package_dir:
                package_dir = settings.get("package_dir", "")
            if not config_dir:
                config_dir = self._config_dir_default
            if not localaddr:
                localaddr = "127.0.0.1"

            if not install_dir or not package_dir:
                raise ValueError("install_dir 和 package_dir 不能为空，请在配置页面中设置")

            cmd = self._build_command(
                config_path, install_dir, package_dir, config_dir,
                localaddr, http_port, debug, fail_fast, service,
            )

            self._status = "running"
            self._run_start_time = datetime.datetime.now()
            await self._broadcast({"type": "deploy_start", "cmd": " ".join(cmd[-10:]) + "..."})

            if self._history_service:
                hosts_count, comps = self._count_hosts_and_components(config_path, service)
                self._current_run_id = self._history_service.create_run(
                    components=comps, hosts_count=hosts_count,
                )

            try:
                subprocess_env = os.environ.copy()
                subprocess_env["PYTHONUNBUFFERED"] = "1"
                self._process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=self._deploy_dir,
                    env=subprocess_env,
                )

                log_path = os.path.join(self._deploy_dir, "logs", "deploy.log")

                # 记录当前日志文件大小，跳过历史日志
                initial_size = os.path.getsize(log_path) if os.path.isfile(log_path) else 0

                # Wait for log file to appear (install.py creates it on startup)
                for _ in range(10):
                    if os.path.isfile(log_path):
                        break
                    await asyncio.sleep(0.5)

                if not os.path.isfile(log_path):
                    await self._broadcast({
                        "type": "log", "stream": "system", "level": "WARNING",
                        "message": "日志文件未找到，请检查 deploy.py 所在目录的 logs/ 目录权限",
                    })

                async def _poll_log():
                    """轮询读取日志文件增量，替代 tail -F 避免缓冲和重连丢日志"""
                    nonlocal initial_size
                    while self._process is not None:  # process alive → keep polling
                        try:
                            if os.path.isfile(log_path):
                                with open(log_path, "r") as f:
                                    f.seek(initial_size)
                                    while True:
                                        line = f.readline()
                                        if not line:
                                            break
                                        parsed = self._parse_log_line(line)
                                        await self._broadcast({
                                            "type": "log",
                                            "stream": "file",
                                            "message": parsed["text"],
                                            "level": parsed["level"],
                                        })
                                        if self._history_service and self._current_run_id:
                                            now_str = datetime.datetime.now().strftime("%H:%M:%S")
                                            tag = parsed["level"].ljust(5)
                                            self._history_service.append_log(
                                                self._current_run_id, now_str, parsed["level"].lower(),
                                                tag, parsed["text"].strip(),
                                            )
                                    initial_size = f.tell()
                        except Exception as e:
                            await self._broadcast({
                                "type": "log", "stream": "system", "level": "WARNING",
                                "message": "日志读取异常: {}".format(str(e)),
                            })
                        await asyncio.sleep(0.5)

                poll_task = asyncio.create_task(_poll_log())

                returncode = await self._process.wait()
                self._process = None

                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass

                ended_at = datetime.datetime.now()
                if self._run_start_time:
                    delta = ended_at - self._run_start_time
                    minutes, seconds = divmod(int(delta.total_seconds()), 60)
                    duration = "{}m {:02d}s".format(minutes, seconds)
                else:
                    duration = None

                if returncode == 0:
                    self._status = "completed"
                    await self._broadcast({"type": "deploy_end", "success": True})
                    if self._history_service and self._current_run_id:
                        self._history_service.update_run(
                            self._current_run_id, "success", "成功",
                            duration=duration,
                            ended_at=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    try:
                        settings = self._load_web_settings()
                        settings["deployed"] = True
                        tmp_path = self._web_settings_path + ".tmp"
                        with open(tmp_path, "w") as f:
                            json.dump(settings, f)
                        os.replace(tmp_path, self._web_settings_path)
                    except Exception:
                        pass
                else:
                    self._status = "failed"
                    await self._broadcast({
                        "type": "deploy_end", "success": False,
                        "returncode": returncode,
                    })
                    if self._history_service and self._current_run_id:
                        self._history_service.update_run(
                            self._current_run_id, "failed", "失败",
                            duration=duration,
                            ended_at=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                        )

                self._current_run_id = None
                self._run_start_time = None

            except asyncio.CancelledError:
                self._status = "cancelled"
                await self._broadcast({"type": "deploy_end", "success": False, "cancelled": True})
                if self._history_service and self._current_run_id:
                    ended_at = datetime.datetime.now()
                    if self._run_start_time:
                        delta = ended_at - self._run_start_time
                        minutes, seconds = divmod(int(delta.total_seconds()), 60)
                        duration = "{}m {:02d}s".format(minutes, seconds)
                    else:
                        duration = None
                    self._history_service.update_run(
                        self._current_run_id, "cancelled", "已取消",
                        duration=duration,
                        ended_at=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    self._current_run_id = None
                    self._run_start_time = None
                raise
            except Exception as e:
                self._status = "failed"
                await self._broadcast({"type": "deploy_error", "error": str(e)[:200]})
                if self._history_service and self._current_run_id:
                    ended_at = datetime.datetime.now()
                    if self._run_start_time:
                        delta = ended_at - self._run_start_time
                        minutes, seconds = divmod(int(delta.total_seconds()), 60)
                        duration = "{}m {:02d}s".format(minutes, seconds)
                    else:
                        duration = None
                    self._history_service.update_run(
                        self._current_run_id, "failed", "失败",
                        duration=duration,
                        ended_at=ended_at.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    self._current_run_id = None
                    self._run_start_time = None
                raise

    async def cancel_deploy(self):
        if self._process is None:
            return False
        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.send_signal(signal.SIGKILL)
                await self._process.wait()
            self._status = "cancelled"
            self._process = None
            await self._broadcast({"type": "deploy_end", "success": False, "cancelled": True})
            return True
        except ProcessLookupError:
            self._process = None
            return False
