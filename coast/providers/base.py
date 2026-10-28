"""제공자 층 — 프런트가 보는 유일한 데이터 계약. 실시간 확장의 핵심(지시서 §1-3).

프런트는 `/api/*` 만 본다. `/api/*` 는 이 인터페이스만 부른다. 그래서 제공자를 바꿔 꽂아도(parquet → 실시간)
화면은 모른다.

    SnapshotProvider
      sources()                     → [Source]          데이터 소스 목록(실해역·생성 벌·앞으로의 실시간)
      window(src, t0, t1, flt)      → WindowStats       기간 합산: 위협 카드·해안국 카드·토폴로지·선박 목록
      ships_at(src, t, flt)         → [ShipState]       시점: 배마다 t 직전 마지막 보고(위치·침로·속력·등급·코드·신호 요약)
      ship(src, mmsi, t0, t1)       → ShipDetail        배 상세: 코드·갈래·시간대별·신호 원인 카드·항적
      contours(src, t0, t1, layer)  → GeoJSON           §4 등고선·보고 밀도·ENV_LOSS 층
      signal_summary(src, t0, t1, flt) → dict           (2차) ⑤ 신호 품질 화면 — 해안국 전체 원인 카드 4장·3단계 수
      changes_since(src, t)         → Delta | None      실시간용 자리 — ParquetProvider 는 None. **LiveProvider 가 구현**

1차 구현은 `parquet.py` 의 ParquetProvider(ml_all 산출물 읽기 전용). 실시간 수집기가 생기면 `live.py` 의
LiveProvider 가 같은 여섯 메서드를 구현하고 `app.py` 의 `PROVIDER` 한 줄만 바꾼다(또는 소스 하나로 추가).

값은 전부 JSON 으로 바로 내려갈 dict/list 다(필드는 아래 TypedDict). 시각은 ISO 문자열(초 단위), 좌표는 WGS84 도.
"""
from __future__ import annotations

from typing import Any, Protocol, TypedDict


class Source(TypedDict):
    id: str                 # 'real' | 'ds015' | (실시간: 'live')
    label: str
    kind: str               # 'real' | 'generated' | 'live'
    t_min: str              # ISO
    t_max: str
    sites: list[int]        # 해안국(수신소) id 목록 — N 곳 설계
    has_truth: bool         # 정답지 유무(생성 벌)
    judges: list[str]       # 이 소스에서 쓸 수 있는 판정기


class Filter(TypedDict, total=False):
    judge: str              # rule | xgb | knn | truth
    site: int | None
    kind: str | None        # pos | static | asm | vde
    threat: int | str | None   # 1..5 | 'ok' | 'hold'


class ShipRow(TypedDict):
    mmsi: int
    state: str              # ok | hold | abn
    threat: int | None
    impact: str | None      # H | M | L
    code: str | None        # 대표 코드(PRIMARY_ORDER 가장 앞)
    kind_of_code: str | None   # 대표 코드의 갈래(slow_kind 등)
    n_rows: int
    n_abn: int
    n_hold: int
    abn_ratio: float
    t_first: str
    t_last: str
    sites: list[int]
    kinds: dict[str, list[int]]   # 메시지 종류별 [행, 비정상, 보류]
    signal: dict[str, Any]        # {level: good|fair|bad, margin_db, rssi_med, resid_mean, n}


class WindowStats(TypedDict):
    src: str
    t0: str
    t1: str
    judge: str
    n_rows: int
    n_ships: int
    threat_cards: list[dict]      # rank 1..5 + ok + hold — {rank, key, title, impact, action, n_ships, n_rows}
    site_cards: list[dict]        # 해안국마다 — 받은 메시지·배 수·비정상 비율(행/배)·보류 비율·신호 요약
    topology: dict                # tree(site→kind→state→ships) · sankey(nodes, links) · tables
    ships: list[ShipRow]


class ShipState(TypedDict):
    mmsi: int
    lat: float
    lon: float
    t: str                  # 그 시점 직전 마지막 보고 시각
    age_s: int              # 시점 − 마지막 보고(초). 600 초 넘으면 반투명
    heading: float | None   # 선수 HDG(도, 0~359). 511·결측이면 None
    cog: float | None       # 대지 침로 COG(도, 0~359.9). 360·결측이면 항적에서 추정(없으면 None)
    cog_source: str | None  # 'data' | 'track' | None
    last_dir: float | None  # (2차) 위 둘이 없을 때 — 기간 안(시점 이전) 마지막 유효 HDG/COG
    last_dir_source: str | None   # 'heading' | 'cog' | None
    dir_deg: float          # (2차) 최종 방향 — 우선순위 heading → cog → track → last → 0°(북쪽 고정)
    dir_source: str         # 'heading' | 'cog' | 'track' | 'last' | 'none'  (원형 점 없음 — 'none' 도 에셋으로 그린다)
    sog: float | None       # 대지 속력 SOG(노트). 102.3·결측이면 None
    row_state: str          # 그 보고 행 자체의 상태
    row_code: str | None
    state: str              # 배 단위(기간) 상태 — 지도 색은 이것
    threat: int | None
    impact: str | None
    code: str | None
    abn_ratio: float
    signal: dict[str, Any]
    near_ships: int         # 시점 스냅샷에서 반경 3 km 안 다른 배 수


class ShipDetail(TypedDict):
    mmsi: int
    summary: ShipRow
    codes: list[dict]       # 코드별 — n(양성 행), 갈래 분포, 위협·영향·설명
    hourly: list[dict]      # 시간대별 {hour, n, abn, hold}
    kinds: list[dict]       # 메시지 종류별 {key, label, n, abn, hold}
    signal_cards: dict      # §4-11 네 몫 + 종합 3단계
    track: list[list]       # [[lat, lon, iso, state], …] 시각순, 최대 2000점


class Delta(TypedDict):
    since: str
    until: str
    ships: list[ShipState]


class SnapshotProvider(Protocol):
    def sources(self) -> list[Source]: ...
    def window(self, src: str, t0: str | None, t1: str | None, flt: Filter) -> WindowStats: ...
    def ships_at(self, src: str, t: str | None, flt: Filter, t0: str | None = None, t1: str | None = None) -> list[ShipState]: ...
    def ship(self, src: str, mmsi: int, t0: str | None, t1: str | None, flt: Filter) -> ShipDetail: ...
    def contours(self, src: str, t0: str | None, t1: str | None, layer: str) -> dict: ...
    def signal_summary(self, src: str, t0: str | None, t1: str | None, flt: Filter) -> dict: ...
    def changes_since(self, src: str, t: str) -> Delta | None: ...
