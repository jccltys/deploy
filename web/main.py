# -*- coding: utf-8 -*-
import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.routers import config as config_router
from web.routers import deploy as deploy_router
from web.routers import mockdata as mockdata_router
from web.routers import dashboard as dashboard_router
from web.routers import components as components_router
from web.routers import hosts as hosts_router
from web.routers import history as history_router
from web.routers import service_check as service_check_router
from web.routers import wizard as wizard_router
from web.routers import service_manager as service_manager_router
from web.services.deploy_service import DeployService
from web.services.history_service import HistoryService
from web.services.mockdata_service import MockdataService

app = FastAPI(title="DeployHub Web", version="1.0.0")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.include_router(dashboard_router.router, prefix="/dashboard")
app.include_router(config_router.router, prefix="/config")
app.include_router(deploy_router.router, prefix="/deploy")
app.include_router(components_router.router, prefix="/components")
app.include_router(hosts_router.router, prefix="/hosts")
app.include_router(history_router.router, prefix="/history")
app.include_router(service_check_router.router, prefix="/service-check")
app.include_router(service_manager_router.router, prefix="/service-manager")
app.include_router(mockdata_router.router)
app.include_router(wizard_router.router, prefix="/wizard")

_config_path = None
_web_settings_path = None
_script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def set_config_path(path):
    global _config_path, _web_settings_path
    _config_path = path
    config_router.CONFIG_PATH = path
    config_router.TEMPLATE_DIR = os.path.join(_script_dir, "conf", "template")
    settings_dir = os.path.dirname(os.path.abspath(path))
    _web_settings_path = os.path.join(settings_dir, "web_settings.json")
    config_router.WEB_SETTINGS_PATH = _web_settings_path
    wizard_router.CONFIG_PATH = path
    wizard_router.WEB_SETTINGS_PATH = _web_settings_path
    dashboard_router.CONFIG_PATH = path
    dashboard_router.WEB_SETTINGS_PATH = _web_settings_path
    components_router.CONFIG_PATH = path
    components_router.WEB_SETTINGS_PATH = _web_settings_path
    hosts_router.CONFIG_PATH = path
    hosts_router.WEB_SETTINGS_PATH = _web_settings_path
    service_check_router.CONFIG_PATH = path
    service_check_router.WEB_SETTINGS_PATH = _web_settings_path
    service_manager_router.CONFIG_PATH = path
    service_manager_router.WEB_SETTINGS_PATH = _web_settings_path
    history_path = os.path.join(settings_dir, "deploy_history.json")
    history_svc = HistoryService(history_path)
    history_router.HISTORY_SERVICE = history_svc
    deploy_router.DEPLOY_SERVICE = DeployService(
        deploy_dir=_script_dir,
        web_settings_path=_web_settings_path,
        history_service=history_svc,
    )
    mockdata_router.MOCKDATA_SERVICE = MockdataService(
        mockdata_dir=os.path.join(_script_dir, "mockdata"),
    )


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/deploy/")


def start_web(host="0.0.0.0", port=18080, config_path=None):
    """启动 Uvicorn Web 服务"""
    if config_path:
        set_config_path(config_path)
        deploy_router.LOCALADDR = host
    uvicorn.run(app, host=host, port=port, log_level="info")
