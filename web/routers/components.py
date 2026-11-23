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
async def components_page(request: Request):
    data = load_deployment_data(CONFIG_PATH, WEB_SETTINGS_PATH)
    return _templates.TemplateResponse(
        request, "components.html",
        {
            "nav_components": "active",
            "components": data.get("components", []),
            "hosts": data.get("hosts", []),
        },
    )
