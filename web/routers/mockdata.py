import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from web.services.mockdata_service import MockdataService

router = APIRouter()

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)

MOCKDATA_SERVICE = None


def _get_svc():
    if MOCKDATA_SERVICE is None:
        return None
    return MOCKDATA_SERVICE


@router.get("/mockdata", response_class=HTMLResponse)
async def mockdata_page(request: Request):
    return _templates.TemplateResponse(
        request, "mockdata.html",
        {"nav_mockdata": "active"},
    )


@router.get("/mockdata/modules")
async def list_modules():
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    modules = svc.list_modules()
    return {"ok": True, "modules": modules}


@router.get("/mockdata/status")
async def all_status():
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    status = svc.get_all_status()
    return {"ok": True, "status": status}


@router.get("/mockdata/status/{module}")
async def module_status(module: str):
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    info = svc.get_module_status(module)
    if info is None:
        return JSONResponse({"ok": False, "error": "未知模块"}, status_code=404)
    return {"ok": True, "status": info}


@router.post("/mockdata/start/{module}")
async def start_module(module: str):
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    result = svc.start_module(module)
    if not result["ok"]:
        return JSONResponse(result, status_code=409)
    return JSONResponse(result)


@router.post("/mockdata/stop/{module}")
async def stop_module(module: str):
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    result = svc.stop_module(module)
    if not result["ok"]:
        return JSONResponse(result, status_code=409)
    return JSONResponse(result)


@router.post("/mockdata/start-all")
async def start_all():
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    results = {}
    for name in svc.list_modules():
        results[name] = svc.start_module(name)
    return {"ok": True, "results": results}


@router.post("/mockdata/stop-all")
async def stop_all():
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    results = {}
    for name in svc.list_modules():
        results[name] = svc.stop_module(name)
    return {"ok": True, "results": results}


@router.get("/mockdata/config")
async def read_config():
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    cfg = svc.read_config()
    return {"ok": True, "config": cfg}


@router.post("/mockdata/config")
async def write_config(config: dict):
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    result = svc.write_config(config)
    if not result["ok"]:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@router.get("/mockdata/config/raw")
async def read_config_raw():
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    text = svc.read_config_raw()
    return {"ok": True, "text": text}


@router.post("/mockdata/config/raw")
async def write_config_raw(body: dict):
    svc = _get_svc()
    if svc is None:
        return JSONResponse({"ok": False, "error": "MockdataService 未初始化"}, status_code=500)
    text = body.get("text", "")
    if not isinstance(text, str):
        return JSONResponse({"ok": False, "error": "text 字段必须是字符串"}, status_code=400)
    result = svc.write_config_raw(text)
    if not result["ok"]:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)
