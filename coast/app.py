"""해안국 관리자 화면 — FastAPI. 프런트는 `/api/*` 만 본다. `/api/*` 는 제공자(PROVIDER) 만 부른다.

    .\run_coast.ps1 [-Port 8800] [-BindHost 127.0.0.1]

읽기 전용 — POST/PUT/DELETE 없음. 쓰기 기능(확인함·메모·보고서·승격/기각)은 요구 밖(§0-①).
실시간: `changes_since` 자리(`/api/changes`) 와 `ships_at` 의 `since` 인자는 받아 두기만 한다(1차는 무시).
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from . import judge as J
from . import mlall, msgkind, settings, signal
from .providers import ParquetProvider

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
ICON_MAPPING = STATIC / "icons" / "mapping.json"

app = FastAPI(title="해안국 관리자 화면 (coast_ui)", docs_url="/api/docs", redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# ── 제공자 — 실시간이 생기면 여기 한 줄(또는 소스 하나 추가) ──────────────
PROVIDER = ParquetProvider()

_tiles: dict = {"at": 0.0, "ok": None, "url": None}


def _err(e: Exception) -> HTTPException:
    if isinstance(e, (KeyError, ValueError)):
        return HTTPException(422, str(e.args[0]) if e.args else str(e))
    if isinstance(e, FileNotFoundError):
        return HTTPException(404, str(e))
    if isinstance(e, mlall.MlAllMissing):
        return HTTPException(503, str(e))
    raise e


def tiles_ok(url: str) -> bool:
    """타일 서버가 살아 있나 — HEAD 한 번(60 초 캐시). 부산 z=10 타일 하나."""
    now = time.time()
    if _tiles["url"] == url and now - _tiles["at"] < 60 and _tiles["ok"] is not None:
        return _tiles["ok"]
    ok = False
    try:
        z, lat, lon = 10, 35.1, 129.05
        x = int((lon + 180) / 360 * 2 ** z)
        y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 2 ** z)
        req = urllib.request.Request(url.format(z=z, x=x, y=y), method="HEAD")
        with urllib.request.urlopen(req, timeout=1.5) as r:
            ok = 200 <= r.status < 400
    except Exception:          # noqa: BLE001 — 꺼져 있으면 False
        ok = False
    _tiles.update(at=now, ok=ok, url=url)
    return ok


def _flt(judge: str, site: int | None = None, kind: str | None = None) -> dict:
    return {"judge": judge, "site": site, "kind": kind}


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"))


@app.get("/favicon.ico")
def favicon():
    return FileResponse(str(STATIC / "icons" / "vessel_red.png"), media_type="image/png")


@app.get("/api/state")
def api_state():
    """처음 한 번 — 소스·위협·코드·판정기·아이콘 매핑·층·설정."""
    try:
        srcs = PROVIDER.sources()
    except Exception as e:  # noqa: BLE001
        raise _err(e)
    tile = settings.tile_url()
    mapping = json.loads(ICON_MAPPING.read_text(encoding="utf-8")) if ICON_MAPPING.exists() else {}
    return {"sources": srcs, "threats": mlall.threat_table(), "codes": mlall.code_table(), "judges": J.JUDGES,
            "msg_kinds": msgkind.table(), "icon_mapping": mapping,
            "layers": {k: {kk: vv for kk, vv in v.items()} for k, v in signal.LAYERS.items()},
            "signal_basis": {"sens_dbm": signal.SENS_DBM, "prot_db": signal.PROT_DB, "margin_levels": list(signal.MARGIN_LEVELS),
                             "env_levels": list(signal.ENV_LEVELS), "env_threshold_db": signal.env_threshold_db(), "stale_s": signal.STALE_S,
                             "near_km": signal.NEAR_KM, "caveat": signal.CAVEAT,
                             "min_move_m": 30.0, "track_lookback": 20},
            "hold_kinds": {k: list(v) for k, v in J.HOLD_KINDS.items()}, "ml_version": J.ML_VERSION,
            "tile_url": tile, "tiles_ok": tiles_ok(tile), "poll_ms": settings.poll_ms(), "settings": settings.summary(),
            "provider": type(PROVIDER).__name__, "live_ready": False}


@app.get("/api/window")
def api_window(src: str, t0: str | None = None, t1: str | None = None, judge: str = "rule"):
    try:
        return PROVIDER.window(src, t0, t1, _flt(judge))
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/api/ships_at")
def api_ships_at(src: str, t: str | None = None, t0: str | None = None, t1: str | None = None, judge: str = "rule",
                 since: str | None = Query(None, description="실시간용 자리 — 1차는 무시")):
    try:
        ships = PROVIDER.ships_at(src, t, _flt(judge), t0, t1)
    except Exception as e:  # noqa: BLE001
        raise _err(e)
    return {"src": src, "t": t, "judge": judge, "since": since, "n": len(ships), "stale_s": signal.STALE_S, "ships": ships}


@app.get("/api/ship")
def api_ship(src: str, mmsi: int, t0: str | None = None, t1: str | None = None, judge: str = "rule"):
    try:
        return PROVIDER.ship(src, mmsi, t0, t1, _flt(judge))
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/api/contours")
def api_contours(src: str, layer: str, t0: str | None = None, t1: str | None = None):
    try:
        return JSONResponse(PROVIDER.contours(src, t0, t1, layer))
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/api/signal_summary")
def api_signal_summary(src: str, t0: str | None = None, t1: str | None = None, judge: str = "rule"):
    """(2차) ⑤ 신호 품질 — 해안국 전체 원인 카드 4장(송신기/해역 환경/혼잡/미상 몫 %)·3단계 배 수."""
    try:
        return PROVIDER.signal_summary(src, t0, t1, _flt(judge))
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/docs/{name}")
def docs_file(name: str):
    """docs/*.md 읽기 전용 — 화면의 "왜 이렇게 그렸나" 링크용. 이름만 받고 경로 탐색은 막는다."""
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".md"):
        raise HTTPException(404, "not found")
    p = (ROOT / "docs" / name).resolve()
    if p.parent != (ROOT / "docs").resolve() or not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(p), media_type="text/markdown; charset=utf-8")


@app.get("/api/changes")
def api_changes(src: str, since: str):
    """실시간 자리 — ParquetProvider 는 null. LiveProvider 가 구현."""
    try:
        d = PROVIDER.changes_since(src, since)
    except Exception as e:  # noqa: BLE001
        raise _err(e)
    return {"src": src, "since": since, "delta": d, "live": d is not None}


@app.get("/api/seamask")
def api_seamask():
    try:
        return JSONResponse(signal.sea_mask_geojson())
    except Exception as e:  # noqa: BLE001
        raise _err(e)
