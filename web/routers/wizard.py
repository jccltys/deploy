import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from web.services.config_service import ConfigService

router = APIRouter()

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)

CONFIG_PATH = None
WEB_SETTINGS_PATH = None


def _get_service():
    return ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)


def _determine_step_status(settings):
    deployed = settings.get("deployed", False)
    step1_done = settings.get("config_validated", False)
    step2_done = settings.get("templates_done", False)

    if deployed:
        return [
            {"step": 1, "title": "修改 config.yaml", "target": "/config/", "status": "done"},
            {"step": 2, "title": "修改配置文件", "target": "/config/", "status": "done"},
            {"step": 3, "title": "指定参数并开始部署", "target": "/deploy/", "status": "done"},
        ]

    return [
        {
            "step": 1,
            "title": "修改 config.yaml",
            "target": "/config/",
            "status": "done" if step1_done else "active",
        },
        {
            "step": 2,
            "title": "修改配置文件",
            "target": "/config/",
            "status": "done" if step2_done else ("active" if step1_done else "pending"),
        },
        {
            "step": 3,
            "title": "指定参数并开始部署",
            "target": "/deploy/",
            "status": "active" if step2_done else "pending",
        },
    ]


@router.get("/", response_class=HTMLResponse)
async def wizard_page(request: Request):
    service = _get_service()
    settings = service.load_web_settings()
    deployed = settings.get("deployed", False)
    steps = _determine_step_status(settings)
    return _templates.TemplateResponse(
        request, "wizard.html",
        {
            "nav_wizard": "active",
            "steps": steps,
            "deployed": deployed,
        },
    )


@router.get("/status")
async def wizard_status():
    service = _get_service()
    settings = service.load_web_settings()
    deployed = settings.get("deployed", False)
    steps = _determine_step_status(settings)
    return {"steps": steps, "deployed": deployed}


@router.post("/skip-step2")
async def wizard_skip_step2():
    service = _get_service()
    service.save_web_settings(templates_done=True)
    return {"ok": True, "message": "已跳过模板配置步骤"}
