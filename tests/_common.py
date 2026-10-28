"""검사 공통 — API 호출·parquet 직접 읽기(coast 패키지의 집계 코드를 거치지 않는다)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 한글 콘솔(cp949)·파이프에서도 결과 줄("—" 등)이 깨지지 않게 — 2026-10-27 코디네이터
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from coast import mlall, settings  # noqa: E402

BASE = "http://127.0.0.1:8800"
FILES = {"real": "risk_map_real.parquet", "ds015": "risk_map_ds015.parquet"}
# 검사 기간 — 소스마다 (시작, 끝). None = 전체. 부분 기간은 시간 필터가 맞는지도 본다
PERIODS = {"real": [(None, None), ("2026-06-09T20:00:00", "2026-06-09T23:00:00")],
           "ds015": [(None, None), ("2020-03-20T12:00:00", "2020-03-20T15:00:00")]}


def base() -> str:
    for a in sys.argv[1:]:
        if a.startswith("http"):
            return a.rstrip("/")
    return BASE


def api(path: str, **params) -> dict:
    r = requests.get(base() + path, params={k: v for k, v in params.items() if v is not None}, timeout=300)
    if not r.ok:
        raise SystemExit(f"{path} {r.status_code}: {r.text[:300]}")
    return r.json()


def read_parquet(src: str, columns: list[str] | None = None) -> pd.DataFrame:
    p = settings.ml_all_root() / "output" / "datagen" / FILES[src]
    df = pd.read_parquet(p, columns=columns)
    df["vsi_time"] = pd.to_datetime(df["vsi_time"])
    return df


def period_mask(df: pd.DataFrame, t0: str | None, t1: str | None):
    m = pd.Series(True, index=df.index)
    if t0:
        m &= df["vsi_time"] >= pd.Timestamp(t0)
    if t1:
        m &= df["vsi_time"] <= pd.Timestamp(t1)
    return m.to_numpy()


class Check:
    def __init__(self, name: str):
        self.name = name; self.n = 0; self.fail: list[str] = []

    def eq(self, label: str, a, b, tol: float = 0.0):
        self.n += 1
        ok = (abs(float(a) - float(b)) <= tol) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else (a == b)
        if not ok:
            self.fail.append(f"{label}: API {a} ≠ 직접 {b}")

    def ok(self, label: str, cond: bool, detail: str = ""):
        self.n += 1
        if not cond:
            self.fail.append(f"{label} {detail}".strip())

    def done(self) -> int:
        if self.fail:
            print(f"[{self.name}] 실패 {len(self.fail)} / 검사 {self.n}")
            for f in self.fail[:30]:
                print("   ✗", f)
            return 1
        print(f"[{self.name}] 통과 — 검사 {self.n} 건")
        return 0
