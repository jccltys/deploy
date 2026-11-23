# -*- coding: utf-8 -*-
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.services.config_service import ConfigService, request_cancel, reset_cancel

router = APIRouter()

CONFIG_PATH = None
WEB_SETTINGS_PATH = None
TEMPLATE_DIR = None

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)


def _get_service():
    return ConfigService(CONFIG_PATH, WEB_SETTINGS_PATH)


def _walk_template_components():
    """递归遍历 TEMPLATE_DIR，返回 [{name, files}] 列表"""
    if not TEMPLATE_DIR or not os.path.isdir(TEMPLATE_DIR):
        return []
    components = []
    for entry in sorted(os.listdir(TEMPLATE_DIR)):
        comp_dir = os.path.join(TEMPLATE_DIR, entry)
        if not os.path.isdir(comp_dir):
            continue
        files = []
        for root, dirs, fnames in os.walk(comp_dir):
            prefix = os.path.relpath(root, comp_dir)
            for f in sorted(fnames):
                if prefix == ".":
                    files.append(f)
                else:
                    files.append(os.path.join(prefix, f))
        if files:
            components.append({"name": entry, "files": files})
    return components


def _read_template_file(component, filename):
    """读取模板文件内容，返回 (content, error)"""
    if not TEMPLATE_DIR or not os.path.isdir(TEMPLATE_DIR):
        return None, "模板目录未配置"
    filepath = os.path.join(TEMPLATE_DIR, component, filename)
    # 防止目录穿越
    real_base = os.path.realpath(TEMPLATE_DIR)
    real_path = os.path.realpath(filepath)
    if not real_path.startswith(real_base + os.sep):
        return None, "无效的文件路径"
    if not os.path.isfile(real_path):
        return None, "文件不存在"
    try:
        with open(real_path, "r") as f:
            return f.read(), None
    except Exception as e:
        return None, "读取失败: {}".format(str(e)[:200])


def _write_template_file(component, filename, content):
    """写入模板文件，返回 (ok, error)"""
    if not TEMPLATE_DIR or not os.path.isdir(TEMPLATE_DIR):
        return False, "模板目录未配置"
    filepath = os.path.join(TEMPLATE_DIR, component, filename)
    real_base = os.path.realpath(TEMPLATE_DIR)
    real_path = os.path.realpath(filepath)
    if not real_path.startswith(real_base + os.sep):
        return False, "无效的文件路径"
    comp_dir = os.path.dirname(real_path)
    try:
        if not os.path.isdir(comp_dir):
            os.makedirs(comp_dir, exist_ok=True)
        with open(real_path, "w") as f:
            f.write(content)
        return True, None
    except Exception as e:
        return False, "写入失败: {}".format(str(e)[:200])


@router.get("/", response_class=HTMLResponse)
async def config_page(request: Request):
    service = _get_service()
    config_raw = service.read_config_raw()
    web_settings = service.load_web_settings()
    template_components = _walk_template_components()
    return _templates.TemplateResponse(
        request, "config.html",
        {
            "config_raw": config_raw,
            "install_dir": web_settings.get("install_dir", ""),
            "package_dir": web_settings.get("package_dir", ""),
            "template_components": template_components,
            "nav_config": "active",
        },
    )


@router.get("/api/raw")
async def api_config_raw():
    service = _get_service()
    content = service.read_config_raw()
    return {"content": content}


@router.get("/api/template/file")
async def api_template_file_get(component: str, file: str):
    content, error = _read_template_file(component, file)
    if error:
        return {"ok": False, "error": error}
    return {"ok": True, "content": content}


@router.post("/api/template/file")
async def api_template_file_save(component: str = Form(...), file: str = Form(...), content: str = Form(...)):
    ok, error = _write_template_file(component, file, content)
    if not ok:
        return {"ok": False, "error": error}
    service = _get_service()
    service.save_web_settings(templates_done=True)
    return {"ok": True}


@router.post("/save")
async def config_save(
    request: Request,
    config_content: str = Form(...),
    install_dir: str = Form(""),
    package_dir: str = Form(""),
):
    reset_cancel()
    service = _get_service()

    errors, yaml_ok, integrity_ok = service.validate_config(config_content)

    if not errors:
        service.write_config_raw(config_content)
        service.save_web_settings(install_dir, package_dir, config_validated=True)
        return {"ok": True, "message": "配置保存成功，所有校验通过"}

    result_type = "warning" if (yaml_ok and not integrity_ok) else "error"
    return {"ok": False, "result_type": result_type, "message": "配置校验未通过", "validation_errors": errors}


@router.post("/check")
async def config_check(
    request: Request,
    config_content: str = Form(...),
):
    reset_cancel()
    service = _get_service()

    errors, yaml_ok, integrity_ok = service.validate_config(config_content)

    if not errors:
        return {"ok": True, "message": "配置校验通过（未保存）"}

    result_type = "warning" if (yaml_ok and not integrity_ok) else "error"
    return {"ok": False, "result_type": result_type, "message": "配置校验未通过", "validation_errors": errors}


@router.post("/reset")
async def config_reset(request: Request):
    service = _get_service()
    config_raw = service.read_config_raw()
    web_settings = service.load_web_settings()
    return _templates.TemplateResponse(
        request, "_editor.html",
        {"config_raw": config_raw, "install_dir": web_settings.get("install_dir", ""), "package_dir": web_settings.get("package_dir", "")},
    )


@router.post("/cancel")
async def config_cancel():
    request_cancel()
    return {"status": "cancelled", "message": "配置校验已取消"}
