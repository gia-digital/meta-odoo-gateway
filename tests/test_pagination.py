from starlette.requests import Request

from app.core.pagination import make_pager, normalize_page_size, parse_page, safe_list_params


def _request(path: str = "/dashboard/leads", query: str = "") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query.encode(),
        "headers": [],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("127.0.0.1", 1),
    }
    return Request(scope)


def test_parse_page_and_size():
    assert parse_page(None) == 1
    assert parse_page("0") == 1
    assert parse_page("3") == 3
    assert parse_page("no") == 1
    assert normalize_page_size(None) == 25
    assert normalize_page_size("50") == 50
    assert normalize_page_size("15") == 25


def test_pager_clamps_and_preserves_filters():
    pager = make_pager(
        _request(query="channel=whatsapp&status=&page=9&notice=ok&edit=4"),
        page=9,
        total=60,
        page_size=25,
    )
    assert pager.page == 3
    assert pager.pages == 3
    assert pager.start == 51
    assert pager.end == 60
    assert pager.offset == 50
    assert pager.has_prev is True
    assert pager.has_next is False
    assert pager.prev_url == "/dashboard/leads?channel=whatsapp&page=2"
    assert "notice" not in pager.next_url
    assert "edit" not in pager.extra
    assert pager.extra == "page=3&channel=whatsapp"
    assert pager.links[0]["n"] == 1
    assert pager.links[-1]["current"] is True


def test_pager_window_inserts_ellipsis():
    pager = make_pager(_request(query="q=acero"), page=6, total=250, page_size=25)
    marks = ["…" if item.get("ellipsis") else item["n"] for item in pager.links]
    assert marks[0] == 1
    assert "…" in marks
    assert marks[-1] == 10
    assert pager.show_sizes is True
    assert pager.sizes[1]["url"] == "/dashboard/leads?q=acero&per=50"


def test_empty_pager():
    pager = make_pager(_request(), page=4, total=0, page_size=25)
    assert pager.page == 1
    assert pager.start == 0
    assert pager.end == 0
    assert pager.show_nav is False
    assert pager.extra == ""


def test_safe_list_params_drops_noise():
    assert safe_list_params("page=2&per=50&q=varilla&edit=1&notice=x") == {
        "page": "2",
        "per": "50",
        "q": "varilla",
    }
    assert safe_list_params("page=1&per=25&per=999") == {}
