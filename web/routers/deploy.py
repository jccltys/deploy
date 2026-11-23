# -*- coding: utf-8 -*-
import json
import os

from fastapi import APIRouter, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from web.services.deploy_service import DeployService
from web.services.data_service import load_deployment_data

router = APIRouter()

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)

# 全局 DeployService 实例（由 main.py 初始化）
DEPLOY_SERVICE = None

# 启动时的 --localaddr 值（由 main.py start_web 注入）
LOCALADDR = None


@router.get("/", response_class=HTMLResponse)
async def deploy_page(request: Request):
    cfg_raw = ""
    services = []
    install_dir = ""
    package_dir = ""
    config_dir = ""
    http_port = "8000"
    localaddr = ""
    order_pipeline = []
    if DEPLOY_SERVICE and hasattr(DEPLOY_SERVICE, '_deploy_dir'):
        from web.services.config_service import ConfigService
        from web.routers.config import CONFIG_PATH, WEB_SETTINGS_PATH
        if CONFIG_PATH:
            svc = ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)
            cfg = svc.read_config()
            services = sorted(set(
                comp.lower()
                for hosts in cfg.get("deploy", {}).values()
                for comp in hosts
            ))
            cfg_raw = json.dumps(cfg, indent=2, ensure_ascii=False) if cfg else ""
            ws = svc.load_web_settings()
            install_dir = ws.get("install_dir", "")
            package_dir = ws.get("package_dir", "")
            config_dir = ws.get("config_dir", "conf/template/")
            http_port = ws.get("http_port", "8000")
            localaddr = ws.get("localaddr", "")
            config_validated = ws.get("config_validated", False)
            templates_done = ws.get("templates_done", False)
            deployed = ws.get("deployed", False)
            data = load_deployment_data(CONFIG_PATH, WEB_SETTINGS_PATH)
            order_pipeline = data.get("order_pipeline", [])

    return _templates.TemplateResponse(
        request, "deploy.html",
        {
            "services": services,
            "nav_deploy": "active",
            "install_dir": install_dir,
            "package_dir": package_dir,
            "config_dir": config_dir,
            "http_port": http_port,
            "order_pipeline": order_pipeline,
            "config_validated": config_validated,
            "templates_done": templates_done,
            "deployed": deployed,
        },
    )


@router.post("/start")
async def deploy_start(
    request: Request,
    service: str = Form(""),
    install_dir: str = Form(""),
    package_dir: str = Form(""),
    config_dir: str = Form(""),
    http_port: str = Form(""),
    debug: bool = Form(False),
    fail_fast: bool = Form(True),
):
    if DEPLOY_SERVICE is None:
        return JSONResponse({"ok": False, "error": "DeployService 未初始化"}, status_code=500)

    from web.routers.config import CONFIG_PATH
    if not CONFIG_PATH or not os.path.isfile(CONFIG_PATH):
        return JSONResponse({"ok": False, "error": "config.yaml 路径未设置或文件不存在"}, status_code=400)

    if DEPLOY_SERVICE.is_running():
        return JSONResponse({"ok": False, "error": "当前已有部署任务正在进行中"}, status_code=409)

    if not install_dir or not package_dir:
        return JSONResponse({"ok": False, "error": "install_dir 和 package_dir 不能为空"}, status_code=400)

    import asyncio
    asyncio.ensure_future(DEPLOY_SERVICE.start_deploy(
        config_path=CONFIG_PATH,
        install_dir=install_dir,
        package_dir=package_dir,
        config_dir=config_dir or None,
        localaddr=LOCALADDR,
        http_port=int(http_port) if http_port else 8000,
        service=service if service else None,
        debug=debug,
        fail_fast=fail_fast,
    ))
    return JSONResponse({"ok": True, "status": "started"})


@router.post("/settings")
async def deploy_settings(
    install_dir: str = Form(""),
    package_dir: str = Form(""),
    config_dir: str = Form(""),
    http_port: str = Form(""),
):
    from web.routers.config import WEB_SETTINGS_PATH, CONFIG_PATH
    if not CONFIG_PATH:
        return JSONResponse({"ok": False, "error": "config.yaml 路径未设置"}, status_code=400)
    from web.services.config_service import ConfigService
    svc = ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)
    svc.save_web_settings(
        install_dir=install_dir or None,
        package_dir=package_dir or None,
        config_dir=config_dir or None,
        http_port=http_port or None,
    )
    return JSONResponse({"ok": True})


@router.post("/cancel")
async def deploy_cancel():
    if DEPLOY_SERVICE is None:
        return JSONResponse({"ok": False, "error": "DeployService 未初始化"}, status_code=500)
    cancelled = await DEPLOY_SERVICE.cancel_deploy()
    return JSONResponse({"ok": cancelled, "status": "cancelled" if cancelled else "no_active"})


@router.get("/status")
async def deploy_status():
    if DEPLOY_SERVICE is None:
        return JSONResponse({"status": "idle"})
    return JSONResponse({"status": DEPLOY_SERVICE.get_status()})


@router.websocket("/logs")
async def deploy_logs(websocket: WebSocket):
    if DEPLOY_SERVICE is None:
        await websocket.close(code=1011)
        return
    await websocket.accept()
    DEPLOY_SERVICE.register_websocket(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("action") == "cancel":
                await DEPLOY_SERVICE.cancel_deploy()
    except WebSocketDisconnect:
        pass
    finally:
        DEPLOY_SERVICE.unregister_websocket(websocket)
