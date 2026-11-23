# -*- coding: utf-8 -*-
import asyncio
import json
import os
import re

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from web.services.data_service import load_deployment_data

router = APIRouter()

CONFIG_PATH = None
WEB_SETTINGS_PATH = None

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)

_LAST_CHECK_PATH = os.path.join(_SCRIPT_DIR, "logs", "last-check.json")


def _save_last_check(results, host_results, returncode):
    from datetime import datetime
    data = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "returncode": returncode,
        "results": results,
        "host_results": host_results,
    }
    os.makedirs(os.path.dirname(_LAST_CHECK_PATH), exist_ok=True)
    with open(_LAST_CHECK_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_last_check():
    if not os.path.isfile(_LAST_CHECK_PATH):
        return None
    try:
        with open(_LAST_CHECK_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


@router.get("/last")
async def service_check_last():
    data = _load_last_check()
    if data:
        return JSONResponse({"ok": True, **data})
    return JSONResponse({"ok": True, "results": {}, "host_results": {}, "checked_at": None, "returncode": None})


COMPONENT_ICONS = {
    "mysql": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><ellipse cx="24" cy="14" rx="12" ry="8" fill="#22C55E" opacity="0.2"/><path d="M24 6c6.627 0 12 3.582 12 8s-5.373 8-12 8-12-3.582-12-8 5.373-8 12-8z" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M24 22v14M16 32l8 4 8-4" stroke="#22C55E" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "redis": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="24" r="5" fill="#22C55E" opacity="0.2"/></svg>',
    "zookeeper": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 34V14l12-6 12 6v20l-12 6-12-6z" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="24" r="3" fill="#22C55E" opacity="0.2"/></svg>',
    "kafka": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M8 28h8l4-12 8 24 4-12h8" stroke="#22C55E" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>',
    "hadoop": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none"/><circle cx="24" cy="20" r="2" fill="#F59E0B" opacity="0.3"/><line x1="24" y1="26" x2="24" y2="32" stroke="#F59E0B" stroke-width="2" stroke-linecap="round"/></svg>',
    "nacos": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 36V16l12-6 12 6v20l-12 6-12-6z" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="22" r="3" fill="#22C55E" opacity="0.2"/></svg>',
    "ckman": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M8 42V18l8-4v28l-8 4z" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M16 14l16 8v20" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="16" cy="14" r="3" fill="#22C55E" opacity="0.2"/></svg>',
    "clickhouse": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><ellipse cx="24" cy="20" rx="10" ry="6" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M14 20v8c0 3.314 4.477 6 10 6s10-2.686 10-6v-8" stroke="#22C55E" stroke-width="1.5" fill="none"/></svg>',
    "nginx": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M18 24l4 4 8-8" stroke="#22C55E" stroke-width="2" stroke-linecap="round"/></svg>',
    "nebula": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 38V18l12-8 12 8v20l-12 8-12-8z" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="22" r="4" fill="#22C55E" opacity="0.2"/></svg>',
    "nebula_studio": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 38V18l12-8 12 8v20l-12 8-12-8z" stroke="#94A3B8" stroke-width="1.5" fill="none"/><circle cx="24" cy="22" r="4" fill="#94A3B8" opacity="0.2"/></svg>',
    "java": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><rect x="8" y="12" width="32" height="24" rx="3" stroke="#F59E0B" stroke-width="1.5" fill="none"/><text x="24" y="28" text-anchor="middle" fill="#F59E0B" font-size="12" font-weight="bold" opacity="0.6">J</text></svg>',
    "java11": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><rect x="8" y="12" width="32" height="24" rx="3" stroke="#F59E0B" stroke-width="1.5" fill="none"/><text x="24" y="28" text-anchor="middle" fill="#F59E0B" font-size="10" font-weight="bold" opacity="0.6">11</text></svg>',
    "java21": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><rect x="8" y="12" width="32" height="24" rx="3" stroke="#F59E0B" stroke-width="1.5" fill="none"/><text x="24" y="28" text-anchor="middle" fill="#F59E0B" font-size="10" font-weight="bold" opacity="0.6">21</text></svg>',
    "sso": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="16" r="6" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M12 38c0-6.627 5.373-12 12-12s12 5.373 12 12M4 42c0-8.837 8.954-16 20-16s20 7.163 20 16" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>',
    "odmp": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><rect x="8" y="10" width="32" height="28" rx="4" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M16 20h4v4h-4zM28 20h4v4h-4zM22 30h4v4h-4zM16 30h4v-4M28 30h4v-4" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "refiner": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 16h24l-6 12H18l-6-12z" stroke="#A855F7" stroke-width="1.5" fill="none"/><circle cx="16" cy="14" r="2" fill="#A855F7" opacity="0.3"/><circle cx="32" cy="14" r="2" fill="#A855F7" opacity="0.3"/><path d="M24 28v6M18 34h12" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "refiner-pro": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 16h24l-6 12H18l-6-12z" stroke="#A855F7" stroke-width="1.5" fill="none"/><circle cx="16" cy="14" r="2" fill="#A855F7" opacity="0.3"/><circle cx="32" cy="14" r="2" fill="#A855F7" opacity="0.3"/><path d="M24 28v6M18 34h12" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "refiner-pro-etl": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 16h24l-6 12H18l-6-12z" stroke="#A855F7" stroke-width="1.5" fill="none" opacity="0.7"/><circle cx="16" cy="14" r="2" fill="#A855F7" opacity="0.3"/><circle cx="32" cy="14" r="2" fill="#A855F7" opacity="0.3"/><path d="M24 28v6M18 34h12" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "aimeter": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M18 24l4 4 8-8" stroke="#A855F7" stroke-width="2" stroke-linecap="round"/></svg>',
    "aimeter-scheduler": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#A855F7" stroke-width="1.5" fill="none" opacity="0.7"/><path d="M18 24l4 4 8-8" stroke="#A855F7" stroke-width="2" stroke-linecap="round"/></svg>',
    "dolphinscheduler": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M24 6c3 0 6 2 6 6s-3 6-6 6-6-2-6-6 3-6 6-6z" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M14 30c0-5.523 4.477-10 10-10s10 4.477 10 10M8 42c0-8.837 7.163-16 16-16s16 7.163 16 16" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>',
    "datax": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M8 16l16-8 16 8v16l-16 8-16-8V16z" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M24 8v32M8 24h32" stroke="#A855F7" stroke-width="1" opacity="0.3"/></svg>',
    "odc": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><rect x="10" y="8" width="28" height="32" rx="3" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M16 18h16M16 24h12M16 30h8" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "jax-pyenv": '<svg width="18" height="18" viewBox="0 0 48 48" fill="none"><path d="M12 14c0-4.418 8.954-8 20-8s20 3.582 20 8v20c0 4.418-8.954 8-20 8s-20-3.582-20-8V14z" stroke="#A855F7" stroke-width="1.5" fill="none"/><ellipse cx="32" cy="24" rx="8" ry="4" stroke="#A855F7" stroke-width="1.5" fill="none"/></svg>',
}


def _get_icon(comp_name):
    return COMPONENT_ICONS.get(comp_name.lower())


CHECKER_MAP = {
    "mysql": "MySQLChecker", "redis": "RedisChecker", "zookeeper": "ZookeeperChecker",
    "kafka": "KafkaChecker", "hadoop": "HadoopChecker", "nacos": "NacosChecker",
    "ckman": "CkmanChecker", "clickhouse": "ClickHouseChecker", "nginx": "NginxChecker",
    "nebula": "NebulaChecker", "nebula_studio": "NebulaStudioChecker",
    "java": "JavaChecker", "java11": "JavaChecker", "java21": "JavaChecker",
    "sso": "SsoChecker", "odmp": "OdmpChecker",
    "refiner-pro": "RefinerProChecker", "refiner-pro-etl": "RefinerEtlChecker",
    "aimeter": "AimeterAlertChecker", "aimeter-scheduler": "AimeterSchedulerChecker",
    "dolphinscheduler": "DolphinschedulerChecker",
}

PORT_MAP = {
    "mysql": "3306", "redis": "6379", "zookeeper": "2181", "kafka": "9092",
    "nacos": "8848", "ckman": "8808", "clickhouse": "19000", "nginx": "10082", "nebula": "9669",
}


def _guessed_port(name):
    return PORT_MAP.get(name.lower())


def _load_settings():
    if not CONFIG_PATH or not WEB_SETTINGS_PATH:
        return {}, False
    from web.services.config_service import ConfigService
    svc = ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)
    ws = svc.load_web_settings()
    return ws, ws.get("deployed", False)


def _build_services(components, hosts):
    services = []
    # 子服务展开映射：父组件 → [ (子组件名, 端口) ]
    SUB_SERVICE_EXPAND = {
        'refiner': [
            ('refiner-pro', '9091'),
            ('refiner-pro-etl', '19091'),
        ],
        'aimeter': [
            ('aimeter', '36888'),
            ('aimeter-scheduler', '36889'),
        ],
    }
    for comp in components:
        name = comp["name"]
        host_ips = comp.get("hosts", [])

        sub_services = SUB_SERVICE_EXPAND.get(name)
        if sub_services:
            for sub_name, sub_port in sub_services:
                services.append({
                    "name": sub_name,
                    "icon": _get_icon(sub_name) or _get_icon(name),
                    "border_class": "healthy",
                    "status_class": "pending",
                    "status_label": "待检测",
                    "checker": CHECKER_MAP.get(sub_name, "—"),
                    "port": sub_port,
                    "hosts": [{"ip": ip, "status_class": "pending", "status_label": "待检测"} for ip in host_ips],
                })
        else:
            services.append({
                "name": name,
                "icon": _get_icon(name),
                "border_class": "healthy",
                "status_class": "pending",
                "status_label": "待检测",
                "checker": CHECKER_MAP.get(name.lower(), "—"),
                "port": _guessed_port(name),
                "hosts": [{"ip": ip, "status_class": "pending", "status_label": "待检测"} for ip in host_ips],
            })
    return services


@router.get("/", response_class=HTMLResponse)
async def service_check_page(request: Request):
    data = load_deployment_data(CONFIG_PATH, WEB_SETTINGS_PATH)
    components = data.get("components", [])
    hosts = data.get("hosts", [])
    ws, deployed = _load_settings()

    total = len(components)
    summary = {
        "total": total,
        "configured": total,
        "not_deployed": 0,
        "hosts": len(hosts),
        "deployed": deployed,
        "last_check": ws.get("last_check", ""),
    }

    return _templates.TemplateResponse(
        request,
        "service_check.html",
        {
            "services": _build_services(components, hosts),
            "summary": summary,
            "nav_service_check": "active",
        },
    )


_RESULT_RE = re.compile(
    r'([\w-]+):\s*(\d+)/(\d+)\s+健康,\s*(\d+)/(\d+)\s+异常\s+\[(\w+)\]',
)
_HOST_RESULT_RE = re.compile(
    r'\[(HEALTHY|UNHEALTHY)\]\s+(\d+\.\d+\.\d+\.\d+)/([\w-]+):\s*(\w+)',
)


@router.post("/run")
async def run_service_check(request: Request):
    if not CONFIG_PATH or not os.path.isfile(CONFIG_PATH):
        return JSONResponse({"ok": False, "error": "config.yaml not found"})

    ws, _ = _load_settings()
    install_dir = ws.get("install_dir", "")
    if not install_dir:
        return JSONResponse({"ok": False, "error": "install_dir 未设置，请先在配置页面中设置"})

    check_script = os.path.join(_SCRIPT_DIR, "tools", "service_check.py")
    if not os.path.isfile(check_script):
        check_script = os.path.join(_SCRIPT_DIR, "deploy", "tools", "service_check.py")
        if not os.path.isfile(check_script):
            return JSONResponse({"ok": False, "error": "service_check.py not found"})

    cmd = ["python3", check_script, "--nodesfile", CONFIG_PATH,
           "--install-dir", install_dir]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_SCRIPT_DIR,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=300,
        )
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")

        results = {}
        host_results = {}
        # service_check.py 的 logging.StreamHandler 默认输出到 stderr，
        # 所以 stdout 通常是空的，需要同时从 stderr 中解析结果
        for line in out.split("\n") + err.split("\n"):
            m = _RESULT_RE.search(line)
            if m:
                comp = m.group(1).strip().lower()
                ok_count = int(m.group(2))
                fail_count = int(m.group(4))
                status = m.group(6).strip().lower()
                results[comp] = {
                    "ok": ok_count,
                    "fail": fail_count,
                    "status": "healthy" if status == "healthy" else "unhealthy",
                }
            hm = _HOST_RESULT_RE.search(line)
            if hm:
                h_status = hm.group(1).lower()
                h_ip = hm.group(2)
                h_comp = hm.group(3).lower()
                h_detail = hm.group(4).lower()
                key = "{}-{}".format(h_comp, h_ip)
                host_results[key] = {
                    "status": "healthy" if h_status == "healthy" else "unhealthy",
                }

        from datetime import datetime
        from web.services.config_service import ConfigService
        svc = ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)
        ws["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        svc.save_web_settings(**{k: ws[k] for k in
                                 ["install_dir", "package_dir", "config_dir",
                                  "http_port", "deployed", "last_check"]
                                  if k in ws})

        _save_last_check(results, host_results, proc.returncode)

        return JSONResponse({
            "ok": True,
            "returncode": proc.returncode,
            "results": results,
            "host_results": host_results,
            "raw": out[-3000:] if len(out) > 3000 else out,
            "error_log": err[-1000:] if err else "",
        })
    except asyncio.TimeoutError:
        return JSONResponse({"ok": False, "error": "巡检超时（300s）"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


def _parse_check_results(lines):
    results = {}
    host_results = {}
    for line in lines:
        m = _RESULT_RE.search(line)
        if m:
            comp = m.group(1).strip().lower()
            ok_count = int(m.group(2))
            fail_count = int(m.group(4))
            status = m.group(6).strip().lower()
            results[comp] = {
                "ok": ok_count,
                "fail": fail_count,
                "status": "healthy" if status == "healthy" else "unhealthy",
            }
        hm = _HOST_RESULT_RE.search(line)
        if hm:
            h_status = hm.group(1).lower()
            h_ip = hm.group(2)
            h_comp = hm.group(3).lower()
            key = "{}-{}".format(h_comp, h_ip)
            host_results[key] = {
                "status": "healthy" if h_status == "healthy" else "unhealthy",
            }
    return results, host_results


@router.websocket("/ws")
async def service_check_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        if not CONFIG_PATH or not os.path.isfile(CONFIG_PATH):
            await websocket.send_json({"type": "error", "message": "config.yaml not found"})
            return

        ws, _ = _load_settings()
        install_dir = ws.get("install_dir", "")
        if not install_dir:
            await websocket.send_json({"type": "error", "message": "install_dir 未设置，请先在配置页面中设置"})
            return

        check_script = os.path.join(_SCRIPT_DIR, "tools", "service_check.py")
        if not os.path.isfile(check_script):
            check_script = os.path.join(_SCRIPT_DIR, "deploy", "tools", "service_check.py")
            if not os.path.isfile(check_script):
                await websocket.send_json({"type": "error", "message": "service_check.py not found"})
                return

        cmd = ["python3", check_script, "--nodesfile", CONFIG_PATH,
               "--install-dir", install_dir]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_SCRIPT_DIR,
        )

        collected_lines = []

        async def _read_stream(stream, name):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
                collected_lines.append(decoded)
                css_class = "info"
                if "unhealthy" in decoded.lower() or "异常" in decoded:
                    css_class = "fail"
                elif "healthy" in decoded.lower() or "健康" in decoded:
                    css_class = "ok"
                elif "skipped" in decoded.lower() or "跳过" in decoded:
                    css_class = "warn"
                await websocket.send_json({
                    "type": "log",
                    "stream": "stderr" if name == "stderr" else "stdout",
                    "class": css_class,
                    "text": decoded,
                })

        read_tasks = [
            asyncio.create_task(_read_stream(proc.stdout, "stdout")),
            asyncio.create_task(_read_stream(proc.stderr, "stderr")),
        ]

        try:
            returncode = await asyncio.wait_for(proc.wait(), timeout=300)
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            await websocket.send_json({"type": "error", "message": "巡检超时（300s）"})
            return

        for t in read_tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        results, host_results = _parse_check_results(collected_lines)
        _save_last_check(results, host_results, returncode)

        from datetime import datetime
        from web.services.config_service import ConfigService
        svc = ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)
        ws["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        svc.save_web_settings(**{k: ws[k] for k in
                                 ["install_dir", "package_dir", "config_dir",
                                  "http_port", "deployed", "last_check"]
                                 if k in ws})

        await websocket.send_json({
            "type": "result",
            "returncode": returncode,
            "results": results,
            "host_results": host_results,
        })
        await websocket.close()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)[:200]})
        except Exception:
            pass
