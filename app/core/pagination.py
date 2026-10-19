"""Paginación de las tablas del dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode

from starlette.requests import Request

DEFAULT_PAGE_SIZE = 25
PAGE_SIZES = (25, 50, 100)
_DROP_KEYS = {"page", "per", "notice", "edit"}
_LIST_KEYS = {"page", "per", "q"}


@dataclass(frozen=True)
class Pager:
    page: int
    pages: int
    page_size: int
    total: int
    offset: int
    start: int
    end: int
    has_prev: bool
    has_next: bool
    show_nav: bool
    show_sizes: bool
    prev_url: str
    next_url: str
    links: list
    sizes: list
    path: str
    extra: str


def parse_page(value: Optional[str]) -> int:
    try:
        return max(1, int(value)) if value else 1
    except (TypeError, ValueError):
        return 1


def normalize_page_size(value: Optional[str]) -> int:
    try:
        size = int(value) if value else DEFAULT_PAGE_SIZE
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    if size in PAGE_SIZES:
        return size
    return DEFAULT_PAGE_SIZE


def safe_list_params(list_qs: str) -> dict:
    params = {}
    for key, value in parse_qsl(list_qs or "", keep_blank_values=False):
        if key in _LIST_KEYS and value:
            params[key] = value
    page = params.get("page")
    if not page or not page.isdigit() or int(page) <= 1:
        params.pop("page", None)
    per = params.get("per")
    if per not in {"50", "100"}:
        params.pop("per", None)
    return params


def make_pager(request: Request, *, page: int, total: int, page_size: int) -> Pager:
    total = max(0, int(total))
    page_size = page_size if page_size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    current = min(max(int(page or 1), 1), pages)
    offset = (current - 1) * page_size
    start = offset + 1 if total else 0
    end = min(offset + page_size, total)
    path = request.url.path
    kept = _kept_params(request)

    def build(target_page: int, size: int) -> str:
        params = list(kept)
        if target_page > 1:
            params.append(("page", str(target_page)))
        if size != DEFAULT_PAGE_SIZE:
            params.append(("per", str(size)))
        return f"{path}?{urlencode(params)}" if params else path

    links = []
    for item in _page_window(current, pages):
        if item is None:
            links.append({"ellipsis": True})
        else:
            links.append(
                {
                    "n": item,
                    "url": build(item, page_size),
                    "current": item == current,
                    "ellipsis": False,
                }
            )
    sizes = [
        {"n": size, "url": build(1, size), "current": size == page_size}
        for size in PAGE_SIZES
    ]
    extra_params = []
    if current > 1:
        extra_params.append(("page", str(current)))
    if page_size != DEFAULT_PAGE_SIZE:
        extra_params.append(("per", str(page_size)))
    extra_params.extend(kept)
    return Pager(
        page=current,
        pages=pages,
        page_size=page_size,
        total=total,
        offset=offset,
        start=start,
        end=end,
        has_prev=current > 1,
        has_next=current < pages,
        show_nav=pages > 1,
        show_sizes=total > DEFAULT_PAGE_SIZE or page_size != DEFAULT_PAGE_SIZE,
        prev_url=build(current - 1, page_size) if current > 1 else "",
        next_url=build(current + 1, page_size) if current < pages else "",
        links=links,
        sizes=sizes,
        path=path,
        extra=urlencode(extra_params),
    )


def _kept_params(request: Request) -> list:
    kept = []
    for key, value in request.query_params.multi_items():
        if key in _DROP_KEYS or value == "":
            continue
        kept.append((key, value))
    return kept


def _page_window(page: int, pages: int, radius: int = 1) -> list:
    if pages <= 7:
        return list(range(1, pages + 1))
    nums = {1, pages}
    for number in range(page - radius, page + radius + 1):
        if 1 <= number <= pages:
            nums.add(number)
    ordered = sorted(nums)
    window = []
    previous = None
    for number in ordered:
        if previous is not None and number - previous > 1:
            window.append(None)
        window.append(number)
        previous = number
    return window
