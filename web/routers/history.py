# -*- coding: utf-8 -*-
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

HISTORY_SERVICE = None

_templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
)

_PER_PAGE = 10


@router.get("/", response_class=HTMLResponse)
async def history_page(request: Request, page: int = 1):
    if HISTORY_SERVICE is None:
        return _templates.TemplateResponse(
            request, "history.html",
            {"runs": [], "page": 1, "total_pages": 1, "page_range": range(0)},
        )

    all_runs = HISTORY_SERVICE.load_runs()
    total = len(all_runs)
    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    page = max(1, min(page, total_pages))

    start = (page - 1) * _PER_PAGE
    end = start + _PER_PAGE
    runs = all_runs[start:end]

    page_range = range(1, total_pages + 1)

    return _templates.TemplateResponse(
        request,
        "history.html",
        {
            "runs": runs,
            "page": page,
            "total_pages": total_pages,
            "page_range": page_range,
        },
    )
