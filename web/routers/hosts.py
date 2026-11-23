# -*- coding: utf-8 -*-
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.services.data_service import load_deployment_data

router = APIRouter()

CONFIG_PATH = None
WEB_SETTINGS_PATH = None

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)


@router.get("/", response_class=HTMLResponse)
async def hosts_page(request: Request):
    data = load_deployment_data(CONFIG_PATH, WEB_SETTINGS_PATH)
    hosts = data.get("hosts", [])

    # 从 config.yaml 读取 servers 的 SSH 配置
    svc = None  # 使用同一份配置
    import yaml
    if CONFIG_PATH and os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}
    else:
        cfg = {}

    servers_map = {}
    for s in cfg.get("servers", []):
        host = s.get("host")
        if host:
            servers_map[host] = s

    # 构造真实主机数据
    real_hosts = []
    for h in hosts:
        ip = h["ip"]
        info = servers_map.get(ip, {})
        real_hosts.append({
            "ip": ip,
            "hostname": ip,
            "ssh_port": info.get("port", 22),
            "ssh_user": info.get("username", "root"),
            "ssh_auth": "密钥",
            "components": [{"name": c, "class": "green"} for c in h.get("components", [])],
        })

    return _templates.TemplateResponse(
        request,
        "hosts.html",
        {
            "hosts": real_hosts,
            "host_count": len(real_hosts),
            "component_count": sum(len(h["components"]) for h in real_hosts),
        },
    )