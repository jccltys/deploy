# -*- coding: utf-8 -*-
import asyncio
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from web.services.config_service import ConfigService, get_ssh_client

router = APIRouter()

CONFIG_PATH = None
WEB_SETTINGS_PATH = None

# 状态缓存
_status_cache = {}
STATUS_CACHE_TTL = 30  # 秒


def _cache_key(host_ip, components):
    return "{}:{}".format(host_ip, ",".join(sorted(components)))


def _cache_get(key):
    entry = _status_cache.get(key)
    if entry and time.time() - entry["ts"] < STATUS_CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key, data):
    _status_cache[key] = {"data": data, "ts": time.time()}


def _cache_invalidate(host_ip, component=None):
    """操作后清除相关缓存条目，下次查询自动走 SSH"""
    for key in list(_status_cache.keys()):
        if key.startswith(host_ip + ":"):
            if component is None or component in key:
                _status_cache.pop(key, None)

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
)

# 组件 → systemd unit 名称映射
COMPONENT_UNITS = {
    "redis": ["redis"],
    "redis-sentinel": ["redis-sentinel"],
    "mysql": ["mysqld"],
    "zookeeper": ["zookeeper"],
    "kafka": ["kafka"],
    "hadoop-namenode": ["hadoop-namenode"],
    "hadoop-datanode": ["hadoop-datanode"],
    "hadoop-journalnode": ["hadoop-journalnode"],
    "hadoop-zkfc": ["hadoop-zkfc"],
    "hadoop-resourcemanager": ["hadoop-resourcemanager"],
    "hadoop-nodemanager": ["hadoop-nodemanager"],
    "hadoop-jobhistory": ["hadoop-jobhistory"],
    "nacos": ["nacos"],
    "ckman": ["ckman"],
    "clickhouse": ["clickhouse-server"],
    "nebula": ["nebula"],
    "nebula_studio": ["nebula-studio"],
    "nginx": ["nginx"],
    "sso": ["sso"],
    "odmp": ["odmp"],
    "dolphinscheduler": ["dolphinscheduler"],
    "refiner-pro": ["refiner-pro"],
    "refiner-pro-etl": ["refiner-pro-etl"],
    "aimeter": ["aimeter"],
    "aimeter-scheduler": ["aimeter-scheduler"],
}

# 组件展开映射（与 service_check.py 保持一致）
SUB_SERVICE_EXPAND = {
    "refiner": ["refiner-pro", "refiner-pro-etl"],
    "aimeter": ["aimeter", "aimeter-scheduler"],
    "redis": ["redis", "redis-sentinel"],
    "hadoop": [
        "hadoop-namenode", "hadoop-datanode", "hadoop-journalnode",
        "hadoop-zkfc", "hadoop-resourcemanager", "hadoop-nodemanager",
        "hadoop-jobhistory",
    ],
}

# 排除的无 systemd 组件
EXCLUDED = {"java", "java11", "java21", "jax-pyenv", "datax", "odc"}

# 组件图标（复用 service_check 的 COMPONENT_ICONS）
COMPONENT_ICONS = {
    "mysql": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><ellipse cx="24" cy="14" rx="12" ry="8" fill="#22C55E" opacity="0.2"/><path d="M24 6c6.627 0 12 3.582 12 8s-5.373 8-12 8-12-3.582-12-8 5.373-8 12-8z" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M24 22v14M16 32l8 4 8-4" stroke="#22C55E" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "redis": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="24" r="5" fill="#22C55E" opacity="0.2"/></svg>',
    "zookeeper": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M12 34V14l12-6 12 6v20l-12 6-12-6z" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="24" r="3" fill="#22C55E" opacity="0.2"/></svg>',
    "kafka": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M8 28h8l4-12 8 24 4-12h8" stroke="#22C55E" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>',
    "hadoop": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none"/><circle cx="24" cy="20" r="2" fill="#F59E0B" opacity="0.3"/><line x1="24" y1="26" x2="24" y2="32" stroke="#F59E0B" stroke-width="2" stroke-linecap="round"/></svg>',
    "hadoop-namenode": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none"/><circle cx="24" cy="20" r="2" fill="#F59E0B" opacity="0.4"/><line x1="24" y1="26" x2="24" y2="32" stroke="#F59E0B" stroke-width="2" stroke-linecap="round"/><text x="23" y="40" font-size="8" fill="#F59E0B" text-anchor="middle" font-weight="bold">NN</text></svg>',
    "hadoop-datanode": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none" opacity="0.7"/><circle cx="16" cy="24" r="4" fill="#F59E0B" opacity="0.3"/><circle cx="32" cy="24" r="4" fill="#F59E0B" opacity="0.3"/><text x="23" y="40" font-size="8" fill="#F59E0B" text-anchor="middle" font-weight="bold">DN</text></svg>',
    "hadoop-journalnode": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none" opacity="0.55"/><rect x="16" y="18" width="16" height="12" rx="1" stroke="#F59E0B" stroke-width="1.5" fill="none"/><line x1="20" y1="22" x2="28" y2="22" stroke="#F59E0B" stroke-width="1.5"/><text x="23" y="40" font-size="8" fill="#F59E0B" text-anchor="middle" font-weight="bold">JN</text></svg>',
    "hadoop-zkfc": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none" opacity="0.55"/><path d="M18 24l3 3 9-7" stroke="#F59E0B" stroke-width="2" stroke-linecap="round"/><text x="23" y="40" font-size="8" fill="#F59E0B" text-anchor="middle" font-weight="bold">ZK</text></svg>',
    "hadoop-resourcemanager": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none"/><rect x="14" y="18" width="20" height="14" rx="2" stroke="#F59E0B" stroke-width="1.5" fill="none"/><circle cx="24" cy="25" r="3" fill="#F59E0B" opacity="0.3"/><text x="23" y="40" font-size="8" fill="#F59E0B" text-anchor="middle" font-weight="bold">RM</text></svg>',
    "hadoop-nodemanager": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none" opacity="0.7"/><circle cx="24" cy="24" r="8" stroke="#F59E0B" stroke-width="1.5" fill="none"/><circle cx="24" cy="24" r="3" fill="#F59E0B" opacity="0.3"/><text x="23" y="40" font-size="8" fill="#F59E0B" text-anchor="middle" font-weight="bold">NM</text></svg>',
    "hadoop-jobhistory": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6l18 30H6L24 6z" stroke="#F59E0B" stroke-width="1.5" fill="none" opacity="0.55"/><circle cx="24" cy="22" r="6" stroke="#F59E0B" stroke-width="1.5" fill="none"/><polyline points="24,20 24,24 28,26" stroke="#F59E0B" stroke-width="1.5" stroke-linecap="round"/><text x="23" y="40" font-size="8" fill="#F59E0B" text-anchor="middle" font-weight="bold">JH</text></svg>',
    "nacos": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M12 36V16l12-6 12 6v20l-12 6-12-6z" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="22" r="3" fill="#22C55E" opacity="0.2"/></svg>',
    "ckman": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M8 42V18l8-4v28l-8 4z" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M16 14l16 8v20" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="16" cy="14" r="3" fill="#22C55E" opacity="0.2"/></svg>',
    "clickhouse": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><ellipse cx="24" cy="20" rx="10" ry="6" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M14 20v8c0 3.314 4.477 6 10 6s10-2.686 10-6v-8" stroke="#22C55E" stroke-width="1.5" fill="none"/></svg>',
    "nginx": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#22C55E" stroke-width="1.5" fill="none"/><path d="M18 24l4 4 8-8" stroke="#22C55E" stroke-width="2" stroke-linecap="round"/></svg>',
    "nebula": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M12 38V18l12-8 12 8v20l-12 8-12-8z" stroke="#22C55E" stroke-width="1.5" fill="none"/><circle cx="24" cy="22" r="4" fill="#22C55E" opacity="0.2"/></svg>',
    "nebula_studio": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M12 38V18l12-8 12 8v20l-12 8-12-8z" stroke="#94A3B8" stroke-width="1.5" fill="none"/><circle cx="24" cy="22" r="4" fill="#94A3B8" opacity="0.2"/></svg>',
    "sso": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="16" r="6" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M12 38c0-6.627 5.373-12 12-12s12 5.373 12 12M4 42c0-8.837 8.954-16 20-16s20 7.163 20 16" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>',
    "odmp": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><rect x="8" y="10" width="32" height="28" rx="4" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M16 20h4v4h-4zM28 20h4v4h-4zM22 30h4v4h-4zM16 30h4v-4M28 30h4v-4" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "dolphinscheduler": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M24 6c3 0 6 2 6 6s-3 6-6 6-6-2-6-6 3-6 6-6z" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M14 30c0-5.523 4.477-10 10-10s10 4.477 10 10M8 42c0-8.837 7.163-16 16-16s16 7.163 16 16" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>',
    "refiner-pro": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M12 16h24l-6 12H18l-6-12z" stroke="#A855F7" stroke-width="1.5" fill="none"/><circle cx="16" cy="14" r="2" fill="#A855F7" opacity="0.3"/><circle cx="32" cy="14" r="2" fill="#A855F7" opacity="0.3"/><path d="M24 28v6M18 34h12" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "refiner-pro-etl": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><path d="M12 16h24l-6 12H18l-6-12z" stroke="#A855F7" stroke-width="1.5" fill="none" opacity="0.7"/><circle cx="16" cy="14" r="2" fill="#A855F7" opacity="0.3"/><circle cx="32" cy="14" r="2" fill="#A855F7" opacity="0.3"/><path d="M24 28v6M18 34h12" stroke="#A855F7" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "aimeter": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#A855F7" stroke-width="1.5" fill="none"/><path d="M18 24l4 4 8-8" stroke="#A855F7" stroke-width="2" stroke-linecap="round"/></svg>',
    "aimeter-scheduler": '<svg width="16" height="16" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="14" stroke="#A855F7" stroke-width="1.5" fill="none" opacity="0.7"/><path d="M18 24l4 4 8-8" stroke="#A855F7" stroke-width="2" stroke-linecap="round"/></svg>',
}


def _get_icon(comp_name):
    return COMPONENT_ICONS.get(comp_name.lower())


def _get_hadoop_hosts_for_sub(sub_name, hadoop_hosts):
    """根据 Hadoop 部署拓扑返回子服务实际运行的主机列表"""
    sorted_hosts = sorted(hadoop_hosts)
    nn1 = sorted_hosts[0] if sorted_hosts else ""
    nn2 = sorted_hosts[1] if len(sorted_hosts) >= 2 else ""
    mapping = {
        "hadoop-namenode": [h for h in (nn1, nn2) if h],
        "hadoop-datanode": list(sorted_hosts),
        "hadoop-journalnode": list(sorted_hosts),
        "hadoop-zkfc": [h for h in (nn1, nn2) if h],
        "hadoop-resourcemanager": [h for h in (nn1, nn2) if h],
        "hadoop-nodemanager": list(sorted_hosts),
        "hadoop-jobhistory": [nn1] if nn1 else [],
    }
    return mapping.get(sub_name, list(sorted_hosts))


def _should_flatten(cfg, comp_name, host_ips):
    """某些组件在有条件时需要扁平化（不作为可展开分组）"""
    if cfg and comp_name == "redis":
        # 单机部署 → 展开成组无意义，扁平为单服务
        return len(host_ips) < 3
    return False


def _build_service_data(cfg):
    """返回 (services, groups, standalone, sidebar) —
    services:  扁平列表供 By Host 过滤
    groups:    多子服务分组
    standalone: 无分组的单服务
    sidebar:   分组+独立服务按字母排序的合并列表（供 By Component 侧边栏渲染）
    """
    deploy_map = cfg.get("deploy", {})
    comp_hosts = {}
    for host, comps in deploy_map.items():
        for comp in comps:
            cl = comp.lower()
            comp_hosts.setdefault(cl, []).append(host)

    services = []
    groups = []
    sub_set = set()

    for comp_name in sorted(comp_hosts.keys()):
        if comp_name in EXCLUDED:
            continue
        host_ips = comp_hosts[comp_name]
        sub_list = SUB_SERVICE_EXPAND.get(comp_name)
        if sub_list and not _should_flatten(cfg, comp_name, host_ips):
            children = []
            for sub in sub_list:
                if sub not in COMPONENT_UNITS:
                    continue
                if comp_name == "hadoop":
                    sub_hosts = _get_hadoop_hosts_for_sub(sub, host_ips)
                else:
                    sub_hosts = list(host_ips)
                child = {
                    "name": sub,
                    "icon": _get_icon(sub) or _get_icon(comp_name) or "",
                    "hosts": sub_hosts,
                }
                services.append(child)
                children.append(child)
                sub_set.add(sub)
            if children:
                children.sort(key=lambda c: c["name"])
                groups.append({
                    "name": comp_name,
                    "icon": _get_icon(comp_name) or "",
                    "children": children,
                })
        else:
            if comp_name in COMPONENT_UNITS:
                services.append({
                    "name": comp_name,
                    "icon": _get_icon(comp_name) or "",
                    "hosts": list(host_ips),
                })

    standalone = [s for s in services if s["name"] not in sub_set]

    # 合并分组 + 独立服务，按字母排序
    sidebar = []
    for g in groups:
        sidebar.append({"type": "group", "name": g["name"], "children": g["children"]})
    for s in standalone:
        sidebar.append({"type": "item", "name": s["name"], "hosts": s["hosts"], "icon": s["icon"]})
    sidebar.sort(key=lambda x: x["name"])

    return services, groups, standalone, sidebar


def _get_server_info(cfg, host_ip):
    for s in cfg.get("servers", []):
        if s.get("host") == host_ip:
            return s
    return None


async def _ssh_run(server_info, command, timeout=30):
    def _run():
        ssh = get_ssh_client(server_info, dry_run=False)
        try:
            code, stdout, stderr = ssh.execute(command, timeout=timeout)
            return code, stdout, stderr
        finally:
            ssh.close()
    return await asyncio.to_thread(_run)


def _build_status_cmd(unit_names):
    cmds = []
    for u in unit_names:
        cmds.append("echo '---{}---' && systemctl is-active {} 2>/dev/null || echo 'unknown'".format(u, u))
    return " && ".join(cmds)


def _build_operate_and_status_cmd(unit_names, action):
    if action == "status":
        return _build_status_cmd(unit_names)

    # 先执行操作，再查询状态
    op_map = {"start": "start", "stop": "stop", "restart": "restart"}
    op = op_map.get(action)
    if not op:
        return _build_status_cmd(unit_names)

    # 用 ; 分隔操作命令，确保单个 unit 失败不会阻断后续命令
    op_cmds = []
    for u in unit_names:
        op_cmds.append("systemctl {} {} 2>&1".format(op, u))
    status_cmds = []
    for u in unit_names:
        status_cmds.append("echo '---{}---' && systemctl is-active {} 2>/dev/null || echo 'unknown'".format(u, u))
    return "; ".join(op_cmds) + "; " + "; ".join(status_cmds)


def _parse_status_output(output, unit_names):
    statuses = {}
    lines = (output or "").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        matched = False
        for u in unit_names:
            if line == "---{}---".format(u):
                if i + 1 < len(lines):
                    statuses[u] = lines[i + 1].strip().lower()
                i += 1
                matched = True
                break
        if not matched:
            i += 1
    for u in unit_names:
        if u not in statuses:
            statuses[u] = "unknown"
    return statuses


def _aggregate_component_status(unit_statuses):
    statuses = list(unit_statuses.values())
    if all(s == "active" for s in statuses):
        return "running"
    elif all(s in ("inactive", "dead", "stopped") for s in statuses):
        return "stopped"
    else:
        return "degraded"


# ── 页面路由 ─────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def service_manager_page(request: Request):
    cfg = _load_config()
    if not cfg:
        return _templates.TemplateResponse(
            request, "service_manager.html",
            {"services": [], "sidebar": [], "hosts": [], "error": "config.yaml 未找到或无效"},
        )

    services, groups, standalone, sidebar = _build_service_data(cfg)
    servers_map = {}
    for s in cfg.get("servers", []):
        host = s.get("host")
        if host:
            servers_map[host] = s

    # 收集所有主机
    deploy_map = cfg.get("deploy", {})
    hosts = []
    for host in sorted(deploy_map.keys()):
        hosts.append({"ip": host})

    return _templates.TemplateResponse(
        request, "service_manager.html",
        {
            "services": services,
            "groups": groups,
            "standalone": standalone,
            "sidebar": sidebar,
            "hosts": hosts,
            "nav_service_manager": "active",
        },
    )


def _load_config():
    if not CONFIG_PATH or not os.path.isfile(CONFIG_PATH):
        return None
    svc = ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)
    return svc.read_config()


# ── API：查询状态 ────────────────────────────────────

@router.post("/api/status")
async def api_status(request: Request):
    body = await request.json()
    host_ip = body.get("host", "")
    components = body.get("components", [])
    force = body.get("force", False)

    ck = _cache_key(host_ip, components)
    if not force:
        cached = _cache_get(ck)
        if cached is not None:
            return JSONResponse({"ok": True, "results": cached, "cached": True})

    cfg = _load_config()
    if not cfg:
        return JSONResponse({"ok": False, "error": "config.yaml 未找到"})

    server_info = _get_server_info(cfg, host_ip)
    if not server_info:
        return JSONResponse({"ok": False, "error": "主机 {} 未配置".format(host_ip)})

    results = {}
    for comp in components:
        units = COMPONENT_UNITS.get(comp, [comp])
        cmd = _build_status_cmd(units)
        try:
            code, stdout, stderr = await _ssh_run(server_info, cmd, timeout=15)
            unit_statuses = _parse_status_output(stdout, units)
            agg_status = _aggregate_component_status(unit_statuses)
            results[comp] = {
                "ok": code == 0 or all(s == "active" for s in unit_statuses.values()),
                "status": agg_status,
                "units": unit_statuses,
            }
        except Exception as e:
            results[comp] = {"ok": False, "status": "error", "error": str(e)[:100]}

    _cache_set(ck, results)
    return JSONResponse({"ok": True, "results": results, "cached": False})


# ── API：单服务操作 ──────────────────────────────────

@router.post("/api/operate")
async def api_operate(request: Request):
    body = await request.json()
    host_ip = body.get("host", "")
    component = body.get("component", "")
    action = body.get("action", "status")

    if action not in ("start", "stop", "restart", "status"):
        return JSONResponse({"ok": False, "error": "无效操作: {}".format(action)})

    cfg = _load_config()
    if not cfg:
        return JSONResponse({"ok": False, "error": "config.yaml 未找到"})

    server_info = _get_server_info(cfg, host_ip)
    if not server_info:
        return JSONResponse({"ok": False, "error": "主机 {} 未配置".format(host_ip)})

    units = COMPONENT_UNITS.get(component, [component])
    cmd = _build_operate_and_status_cmd(units, action)

    try:
        code, stdout, stderr = await _ssh_run(server_info, cmd, timeout=60)
        unit_statuses = _parse_status_output(stdout, units)
        agg_status = _aggregate_component_status(unit_statuses)
        if action in ("start", "stop", "restart"):
            _cache_invalidate(host_ip, component)
        return JSONResponse({
            "ok": True,
            "component": component,
            "action": action,
            "status": agg_status,
            "units": unit_statuses,
            "output": (stdout or "")[-500:],
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


# ── API：批量操作 ────────────────────────────────────

@router.post("/api/batch-operate")
async def api_batch_operate(request: Request):
    body = await request.json()
    component = body.get("component", "")
    hosts = body.get("hosts", [])
    action = body.get("action", "status")

    if action not in ("start", "stop", "restart", "status"):
        return JSONResponse({"ok": False, "error": "无效操作: {}".format(action)})

    cfg = _load_config()
    if not cfg:
        return JSONResponse({"ok": False, "error": "config.yaml 未找到"})

    units = COMPONENT_UNITS.get(component, [component])
    cmd = _build_operate_and_status_cmd(units, action)
    results = []

    for host_ip in hosts:
        server_info = _get_server_info(cfg, host_ip)
        if not server_info:
            results.append({"host": host_ip, "ok": False, "error": "主机未配置"})
            continue
        try:
            code, stdout, stderr = await _ssh_run(server_info, cmd, timeout=60)
            unit_statuses = _parse_status_output(stdout, units)
            agg_status = _aggregate_component_status(unit_statuses)
            if action in ("start", "stop", "restart"):
                _cache_invalidate(host_ip, component)
            results.append({
                "host": host_ip,
                "ok": True,
                "status": agg_status,
                "units": unit_statuses,
            })
        except Exception as e:
            results.append({"host": host_ip, "ok": False, "error": str(e)[:100]})

    return JSONResponse({"ok": True, "results": results})
