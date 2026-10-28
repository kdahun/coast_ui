"""설정 — 저장소 뿌리 `.env.local` 한 파일 (견본 `.env.example`, git 제외).

규칙(ml_all 과 같다)
  · 이미 설정된 환경변수가 이긴다. 파일은 기본값 자리.
  · 경로 값이 상대경로면 이 저장소 뿌리 기준으로 푼다. 절대경로·호스트는 코드에 박지 않는다.
  · 비밀번호류는 어떤 메시지에도 찍지 않는다(이 앱은 DB 를 쓰지 않으므로 애초에 없다).

이름
  AISINT_ML_ALL_ROOT   판정 산출물이 있는 ml_all 저장소. 기본 `../ais_integrity_ml_all`
  COAST_TILE_URL       지도 타일 주소 ({z}/{x}/{y}). 기본 `http://localhost:8080/styles/dark-matter/{z}/{x}/{y}.png`
                       타일 서버가 없으면 배경 없이 항행수역(sea_mask) 윤곽만 그린다.
  COAST_PORT           run_coast.ps1 기본 포트(8800). 스크립트 인자 -Port 가 이긴다.
  COAST_POLL_MS        프런트 폴링 주기(ms). 1차는 0 = 꺼짐 (LiveProvider 가 붙으면 켠다).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
DEFAULT_TILE = "http://localhost:8080/styles/dark-matter/{z}/{x}/{y}.png"

_loaded = False


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        if val[:1] in ("'", '"'):
            q = val[0]
            end = val.find(q, 1)
            val = val[1:end] if end > 0 else val[1:]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        out[key] = val
    return out


def load_env() -> None:
    """`.env.local` 을 한 번 읽어 비어 있는 환경변수만 채운다."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    if ENV_FILE.exists():
        for k, v in _parse(ENV_FILE.read_text(encoding="utf-8")).items():
            os.environ.setdefault(k, v)


def _path(name: str, default: str) -> Path:
    load_env()
    raw = os.environ.get(name, "").strip() or default
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (ROOT / p).resolve()


def ml_all_root() -> Path:
    return _path("AISINT_ML_ALL_ROOT", "../ais_integrity_ml_all")


def tile_url() -> str:
    load_env()
    return os.environ.get("COAST_TILE_URL", "").strip() or DEFAULT_TILE


def poll_ms() -> int:
    load_env()
    try:
        return max(0, int(os.environ.get("COAST_POLL_MS", "0") or 0))
    except ValueError:
        return 0


def summary() -> dict:
    """화면·검사에 보여 줄 설정(비밀 없음)."""
    r = ml_all_root()
    return {"ml_all_root": str(r), "ml_all_root_exists": r.exists(), "tile_url": tile_url(),
            "poll_ms": poll_ms(), "env_file": str(ENV_FILE), "env_file_exists": ENV_FILE.exists()}
