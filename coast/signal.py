"""신호 품질 — §4. 등고선 2종(수신 여유·환경 잔차) + 보고 밀도·ENV_LOSS 층 + 배 원인 카드.

근거와 식은 docs/SIGNAL_QUALITY_BASIS.md 에 출처 URL 과 함께 적었다. 여기 상수는 그 문서의 표와 1:1 이다.

  (가) 수신 여유(dB) = rssi − SENS_DBM(−107 dBm, ITU-R M.1371-6 최소 감도 @ PER 20 %)
       등고선 0 / 10 / 20 dB — 10 dB 는 동일 채널 보호비(C/(I+N) ≈ 10 dB). 3단계 = 나쁨 < 0 · 보통 0~10 · 좋음 ≥ 10
  (나) 환경 잔차(dB) = rssi_resid(관측 − 거리 기대값, ml_all 거리 모델 그대로) 등고선 −10 / −5 / 0 / +5
       "가림 의심" 문턱 −X 는 ml_all rules.THRESHOLDS['rssi_resid_db'](4 dB) 와 같은 값 — 설계값.

만드는 법(둘 다 같다): 기간 안 위치 있는 보고 → (0.5 km 칸, 배) 중앙값 → 칸 중앙값(배 3척 이상인 칸이 표본점)
→ 정규 크리깅(지수 반분산 모델, 이웃 16점) 으로 0.5 km 격자 보간 → 육지(sea_mask 밖)·표본점 3 km 밖은 비움
→ marching squares 로 등고선 → GeoJSON. 표본점이 적으면(< MIN_SAMPLES) 배 1척 이상 칸을 IDW 로 대체하고 method 에 적는다.

생존 편향: 수신된 메시지만 보이므로 아주 나쁜 곳은 값이 낮게 나오는 게 아니라 **점이 없다**. 그래서 보고 밀도(배×분)
층과 ENV_LOSS 비율 층을 같이 내려 주고 범례에 그 주의를 적는다(legend.caveat).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.spatial import cKDTree

from . import mlall

# ── 표준·논문 근거 값 ───────────────────────────────────────────────────
SENS_DBM = -107.0          # ITU-R M.1371-6 Annex 2 §… 최소 수신기 감도 (PER 20 %)
PROT_DB = 10.0             # 동일 채널 보호비 C/(I+N) ≈ 10 dB
MARGIN_LEVELS = (0.0, 10.0, 20.0)
ENV_LEVELS = (-10.0, -5.0, 0.0, 5.0)
# ── 설계값(근거 없음 — 문서 표에 명시) ─────────────────────────────────
GRID_KM = 0.5
MAX_DIST_KM = 3.0          # 가장 가까운 표본점이 이보다 멀면 그리지 않음
MIN_SHIPS_PER_CELL = 3     # 칸을 표본점으로 치는 최소 배 수
MIN_SAMPLES = 30           # 크리깅 표본점이 이보다 적으면 IDW
NEIGHBORS = 16             # 국소 크리깅 이웃 수
VARIO_MAX_KM = 15.0
STALE_S = 600              # 시점에서 10 분보다 오래된 마지막 보고 = 반투명
NEAR_KM = 3.0              # 혼잡: 반경 3 km 안 배 수 (ml_all NEAR_KM 과 같음)
SLOTS_PER_FRAME = 2250
KM_PER_DEG = 111.32

LAYERS = {
    "margin": {"label": "수신 여유 (dB)", "unit": "dB", "levels": list(MARGIN_LEVELS), "kind": "contour",
               "desc": f"RSSI − ({SENS_DBM:g} dBm). 0 미만 = 표준 감도 미만, 0~{PROT_DB:g} = 간섭 하나면 끊길 여유, ≥ {PROT_DB:g} = 보호비만큼 여유, ≥ 20 넉넉"},
    "env": {"label": "환경 잔차 (dB)", "unit": "dB", "levels": list(ENV_LEVELS), "kind": "contour",
            "desc": "관측 RSSI − 거리 기대값(ml_all 거리 모델). 음수가 큰 곳 = 가림·음영 의심"},
    "density": {"label": "보고 밀도 (배×분)", "unit": "배×분", "kind": "cells",
                "desc": "0.5 km 칸마다 (배, 분) 조합 수. 점이 없는 곳은 '좋은 곳'이 아니라 '들리지 않은 곳'일 수 있다(생존 편향)"},
    "envloss": {"label": "ENV_LOSS 비율 (%)", "unit": "%", "kind": "cells",
                "desc": "0.5 km 칸의 행 중 REPORT_RATE_SLOW 환경성 유실(ENV_LOSS) 갈래 비율"},
}
CAVEAT = ("생존 편향 주의 — 수신된 메시지만 보이므로 아주 나쁜 곳은 값이 낮게 나오는 것이 아니라 점이 없다. "
          "보고 밀도·ENV_LOSS 층을 함께 켜서 '비어 있는 곳'을 보라.")


def margin_level(margin_db: float | None) -> str | None:
    if margin_db is None or not math.isfinite(margin_db):
        return None
    return "bad" if margin_db < 0 else ("fair" if margin_db < PROT_DB else "good")


LEVEL_LABEL = {"good": "좋음", "fair": "보통", "bad": "나쁨"}


def env_threshold_db() -> float:
    return mlall.threshold("rssi_resid_db")


# ── 격자 · 육지 마스크 ───────────────────────────────────────────────────
@lru_cache(maxsize=1)
def sea_mask() -> dict:
    p = mlall.sea_mask_path()
    d = json.loads(p.read_text(encoding="utf-8"))
    cells = set()
    for c in d["cells"]:
        a, b = c.split(",")
        cells.add((int(a), int(b)))
    return {"cell_deg": float(d["cell_deg"]), "lat0": float(d["lat0"]), "lon0": float(d["lon0"]), "cells": cells}


def is_sea(lat: np.ndarray, lon: np.ndarray, neighbors: int = 1) -> np.ndarray:
    """ml_all geo.on_land 와 같은 규칙(이웃 1칸까지 바다로 본다)의 반대값."""
    m = sea_mask()
    iy = np.floor((lat - m["lat0"]) / m["cell_deg"]).astype(int)
    ix = np.floor((lon - m["lon0"]) / m["cell_deg"]).astype(int)
    out = np.zeros(len(lat), bool)
    cells = m["cells"]
    for i in range(len(lat)):
        for dy in range(-neighbors, neighbors + 1):
            if out[i]:
                break
            for dx in range(-neighbors, neighbors + 1):
                if (ix[i] + dx, iy[i] + dy) in cells:
                    out[i] = True
                    break
    return out


def sea_mask_geojson() -> dict:
    """항행수역 칸을 사각형으로 — 타일 서버가 없을 때 배경(육지 윤곽) 대용."""
    m = sea_mask()
    d = m["cell_deg"]
    feats = []
    for ix, iy in sorted(m["cells"]):
        lon, lat = m["lon0"] + ix * d, m["lat0"] + iy * d
        feats.append({"type": "Feature", "properties": {},
                      "geometry": {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}})
    return {"type": "FeatureCollection", "features": feats, "cell_deg": d}


def grid_spec(lat: np.ndarray, lon: np.ndarray, km: float = GRID_KM, pad_km: float = 1.0) -> dict:
    lat0 = float(np.nanmin(lat)); lat1 = float(np.nanmax(lat))
    lon0 = float(np.nanmin(lon)); lon1 = float(np.nanmax(lon))
    latc = 0.5 * (lat0 + lat1)
    dlat = km / KM_PER_DEG
    dlon = km / (KM_PER_DEG * math.cos(math.radians(latc)))
    pad_lat, pad_lon = pad_km / KM_PER_DEG, pad_km / (KM_PER_DEG * math.cos(math.radians(latc)))
    lats = np.arange(lat0 - pad_lat, lat1 + pad_lat + dlat, dlat)
    lons = np.arange(lon0 - pad_lon, lon1 + pad_lon + dlon, dlon)
    return {"km": km, "lats": lats, "lons": lons, "dlat": dlat, "dlon": dlon, "latc": latc}


def to_km(lat: np.ndarray, lon: np.ndarray, latc: float) -> np.ndarray:
    """위경도 → 평면 km (등거리 근사, 작은 해역)."""
    return np.c_[(lon - 0.0) * KM_PER_DEG * math.cos(math.radians(latc)), lat * KM_PER_DEG]


# ── 표본점: (칸, 배) 중앙값 → 칸 중앙값 ─────────────────────────────────
def cell_samples(lat: np.ndarray, lon: np.ndarray, mmsi: np.ndarray, value: np.ndarray, g: dict) -> pd.DataFrame:
    ok = np.isfinite(value) & np.isfinite(lat) & np.isfinite(lon)
    ix = np.floor((lon[ok] - g["lons"][0]) / g["dlon"]).astype(int)
    iy = np.floor((lat[ok] - g["lats"][0]) / g["dlat"]).astype(int)
    d = pd.DataFrame({"ix": ix, "iy": iy, "mmsi": mmsi[ok], "v": value[ok]})
    per_ship = d.groupby(["ix", "iy", "mmsi"], sort=False)["v"].median().reset_index()
    cell = per_ship.groupby(["ix", "iy"], sort=False).agg(v=("v", "median"), n_ships=("mmsi", "size")).reset_index()
    cell["lat"] = g["lats"][0] + (cell["iy"] + 0.5) * g["dlat"]
    cell["lon"] = g["lons"][0] + (cell["ix"] + 0.5) * g["dlon"]
    return cell


# ── 반분산(variogram) · 정규 크리깅 ───────────────────────────────────────
def _exp_model(h, c0, c1, a):
    return c0 + c1 * (1.0 - np.exp(-h / np.maximum(a, 1e-6)))


def fit_variogram(xy: np.ndarray, v: np.ndarray, max_km: float = VARIO_MAX_KM, nbins: int = 15, max_pairs: int = 200_000, seed: int = 0) -> dict:
    """경험 반분산 → 지수 모델(nugget c0, partial sill c1, range a). 쌍은 무작위 표본."""
    n = len(v)
    rng = np.random.default_rng(seed)
    m = min(max_pairs, n * (n - 1) // 2)
    i = rng.integers(0, n, m); j = rng.integers(0, n, m)
    keep = i != j
    i, j = i[keep], j[keep]
    h = np.hypot(*(xy[i] - xy[j]).T)
    gam = 0.5 * (v[i] - v[j]) ** 2
    sel = h <= max_km
    h, gam = h[sel], gam[sel]
    edges = np.linspace(0, max_km, nbins + 1)
    b = np.clip(np.searchsorted(edges, h, side="right") - 1, 0, nbins - 1)
    hc, gc, nc = [], [], []
    for k in range(nbins):
        s = b == k
        if s.sum() >= 30:
            hc.append(float(h[s].mean())); gc.append(float(gam[s].mean())); nc.append(int(s.sum()))
    hc, gc = np.array(hc), np.array(gc)
    var = float(np.var(v)) if n > 1 else 1.0
    p = {"c0": 0.2 * var, "c1": 0.8 * var, "a": max_km / 3, "fitted": False}
    if len(hc) >= 4:
        try:
            popt, _ = curve_fit(_exp_model, hc, gc, p0=[p["c0"], p["c1"], p["a"]],
                                bounds=([0, 1e-6, 0.1], [max(var * 3, 1e-3), max(var * 3, 1e-3), max_km * 3]), maxfev=5000)
            p = {"c0": float(popt[0]), "c1": float(popt[1]), "a": float(popt[2]), "fitted": True}
        except (RuntimeError, ValueError):
            pass
    p["bins"] = [{"h_km": float(a_), "gamma": float(b_), "n": c_} for a_, b_, c_ in zip(hc, gc, nc)]
    p["model"] = "exponential"
    return p


def ordinary_kriging(xy: np.ndarray, v: np.ndarray, q: np.ndarray, vario: dict, k: int = NEIGHBORS) -> np.ndarray:
    """국소 정규 크리깅 — 질의점마다 가장 가까운 k 표본점으로 OK 연립방정식을 푼다(배치)."""
    k = min(k, len(v))
    tree = cKDTree(xy)
    d, idx = tree.query(q, k=k)
    if k == 1:
        d, idx = d[:, None], idx[:, None]
    c0, c1, a = vario["c0"], vario["c1"], vario["a"]
    sill = c0 + c1

    def cov(h):
        return sill - _exp_model(h, c0, c1, a)       # 공분산 = sill − γ(h)

    P = xy[idx]                                      # (M, k, 2)
    dij = np.linalg.norm(P[:, :, None, :] - P[:, None, :, :], axis=-1)   # (M, k, k)
    M = len(q)
    A = np.zeros((M, k + 1, k + 1))
    A[:, :k, :k] = cov(dij) + np.eye(k) * 1e-6 * max(sill, 1e-6)
    A[:, :k, k] = 1.0; A[:, k, :k] = 1.0
    b = np.zeros((M, k + 1))
    b[:, :k] = cov(d)
    b[:, k] = 1.0
    try:
        w = np.linalg.solve(A, b[..., None])[..., 0]
    except np.linalg.LinAlgError:
        w = np.linalg.lstsq(A.reshape(-1, k + 1, k + 1)[0], b[0], rcond=None)[0][None].repeat(M, 0)
    return (w[:, :k] * v[idx]).sum(axis=1)


def idw(xy: np.ndarray, v: np.ndarray, q: np.ndarray, k: int = NEIGHBORS, power: float = 2.0) -> np.ndarray:
    k = min(k, len(v))
    tree = cKDTree(xy)
    d, idx = tree.query(q, k=k)
    if k == 1:
        d, idx = d[:, None], idx[:, None]
    w = 1.0 / np.maximum(d, 1e-3) ** power
    out = (w * v[idx]).sum(axis=1) / w.sum(axis=1)
    exact = d[:, 0] < 1e-9                 # 표본점 위에서는 그 값 그대로(정확 보간)
    out[exact] = v[idx[exact, 0]]
    return out


def interpolate_field(samples: pd.DataFrame, g: dict) -> dict:
    """표본점(칸 중앙값) → 격자 값(2D, NaN = 그리지 않음). 방법·반분산 모델·마스크 정보도 같이."""
    strong = samples[samples["n_ships"] >= MIN_SHIPS_PER_CELL]
    method = "kriging"
    use = strong
    if len(strong) < MIN_SAMPLES:
        method = "idw"
        use = samples[samples["n_ships"] >= 1]
    lats, lons = g["lats"], g["lons"]
    LON, LAT = np.meshgrid(lons, lats)
    Q = to_km(LAT.ravel(), LON.ravel(), g["latc"])
    Z = np.full(Q.shape[0], np.nan)
    info = {"method": method, "n_samples": int(len(use)), "n_cells_with_ships": int(len(samples)),
            "min_ships_per_cell": MIN_SHIPS_PER_CELL, "max_dist_km": MAX_DIST_KM, "grid_km": g["km"], "variogram": None}
    if len(use) == 0:
        return {"Z": Z.reshape(LAT.shape), "info": info, "lats": lats, "lons": lons}
    xy = to_km(use["lat"].to_numpy(float), use["lon"].to_numpy(float), g["latc"])
    v = use["v"].to_numpy(float)
    near_d, _ = cKDTree(xy).query(Q, k=1)
    sea = is_sea(LAT.ravel(), LON.ravel())
    keep = (near_d <= MAX_DIST_KM) & sea
    if keep.any():
        if method == "kriging":
            vario = fit_variogram(xy, v)
            info["variogram"] = vario
            Z[keep] = ordinary_kriging(xy, v, Q[keep], vario)
        else:
            Z[keep] = idw(xy, v, Q[keep])
    info["n_grid"] = int(keep.sum())
    return {"Z": Z.reshape(LAT.shape), "info": info, "lats": lats, "lons": lons}


def field_value_at(field: dict, lat: float, lon: float) -> float | None:
    """격자 값 찾기(가장 가까운 칸). 없으면 None."""
    lats, lons, Z = field["lats"], field["lons"], field["Z"]
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    i = int(round((lat - lats[0]) / (lats[1] - lats[0]))) if len(lats) > 1 else 0
    j = int(round((lon - lons[0]) / (lons[1] - lons[0]))) if len(lons) > 1 else 0
    if 0 <= i < Z.shape[0] and 0 <= j < Z.shape[1] and math.isfinite(Z[i, j]):
        return float(Z[i, j])
    return None


# ── marching squares (등고선, 선형 보간; d3-contour 와 같은 알고리즘) ──────────
# 칸 네 모서리 비트: 1 = 좌하(0,0) · 2 = 우하(1,0) · 4 = 우상(1,1) · 8 = 좌상(0,1). 변: 0 = 아래 · 1 = 오른쪽 · 2 = 위 · 3 = 왼쪽
# 선분은 <b>방향</b>이 있다 — 값 ≥ level 인 쪽이 진행 방향의 왼쪽. 그래서 끝점 → 시작점으로만 이어 붙이면
# 등고선이 격자점 값과 정확히 같은 퇴화 경우(한 점에 선분 넷)에도 고리가 끊기지 않는다.
_CASES = {1: [(0, 3)], 2: [(1, 0)], 3: [(1, 3)], 4: [(2, 1)], 6: [(2, 0)], 7: [(2, 3)], 8: [(3, 2)],
          9: [(0, 2)], 11: [(1, 2)], 12: [(3, 1)], 13: [(0, 1)], 14: [(3, 0)]}


def marching_squares(Z: np.ndarray, lats: np.ndarray, lons: np.ndarray, level: float) -> list[list[list[float]]]:
    """등고선 level 의 방향 있는 선분들 → 이어 붙인 폴리라인 [[lon, lat], …] 목록. NaN 칸은 건너뛴다."""
    ny, nx = Z.shape
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(ny - 1):
        for j in range(nx - 1):
            z00, z10, z11, z01 = Z[i, j], Z[i, j + 1], Z[i + 1, j + 1], Z[i + 1, j]
            if not (math.isfinite(z00) and math.isfinite(z10) and math.isfinite(z11) and math.isfinite(z01)):
                continue
            c = (1 if z00 >= level else 0) | (2 if z10 >= level else 0) | (4 if z11 >= level else 0) | (8 if z01 >= level else 0)
            if c in (0, 15):
                continue
            x0, x1, y0, y1 = lons[j], lons[j + 1], lats[i], lats[i + 1]

            def pt(edge: int) -> tuple[float, float]:
                if edge == 0:
                    t = (level - z00) / (z10 - z00) if z10 != z00 else 0.5
                    return (x0 + t * (x1 - x0), y0)
                if edge == 1:
                    t = (level - z10) / (z11 - z10) if z11 != z10 else 0.5
                    return (x1, y0 + t * (y1 - y0))
                if edge == 2:
                    t = (level - z01) / (z11 - z01) if z11 != z01 else 0.5
                    return (x0 + t * (x1 - x0), y1)
                t = (level - z00) / (z01 - z00) if z01 != z00 else 0.5
                return (x0, y0 + t * (y1 - y0))

            if c in (5, 10):      # 안장 — 가운데 값으로 가른다
                center = 0.25 * (z00 + z10 + z11 + z01)
                if c == 5:
                    pairs = [(0, 1), (2, 3)] if center >= level else [(0, 3), (2, 1)]
                else:
                    pairs = [(3, 0), (1, 2)] if center >= level else [(1, 0), (3, 2)]
            else:
                pairs = _CASES[c]
            for a, b in pairs:
                segs.append((pt(a), pt(b)))
    return _join_segments(segs)


def _join_segments(segs: list) -> list[list[list[float]]]:
    """방향 있는 선분을 끝점 → 시작점으로 이어 폴리라인으로. 한 점에 후보가 여럿이면(격자점 값 = level 인 퇴화)
    들어온 방향과 가장 곧게 이어지는 것을 고른다 — 고리가 한 점에서 꼬집히지 않게."""
    def key(p):
        return (round(p[0], 9), round(p[1], 9))
    by_start: dict[tuple, list[int]] = {}
    by_end: dict[tuple, list[int]] = {}
    segs = [sg for sg in segs if key(sg[0]) != key(sg[1])]      # 길이 0 선분(격자점 값 = level) 은 버린다
    for n, (a, b) in enumerate(segs):
        by_start.setdefault(key(a), []).append(n)
        by_end.setdefault(key(b), []).append(n)
    used = [False] * len(segs)

    def take(table: dict, k: tuple, direction: tuple[float, float], forward: bool) -> int | None:
        best, best_dot = None, -2.0
        for m in table.get(k, []):
            if used[m]:
                continue
            a, b = segs[m]
            d = (b[0] - a[0], b[1] - a[1])
            norm = math.hypot(d[0], d[1]) or 1.0
            dot = (d[0] * direction[0] + d[1] * direction[1]) / norm
            if dot > best_dot:
                best, best_dot = m, dot
        if best is not None:
            used[best] = True
        return best

    def unit(p, q):
        d = (q[0] - p[0], q[1] - p[1]); n = math.hypot(d[0], d[1]) or 1.0
        return (d[0] / n, d[1] / n)

    lines = []
    for n in range(len(segs)):
        if used[n]:
            continue
        used[n] = True
        a, b = segs[n]
        line = [a, b]
        while key(line[-1]) != key(line[0]):          # 앞으로: 끝점에서 시작하는 선분
            m = take(by_start, key(line[-1]), unit(line[-2], line[-1]), True)
            if m is None:
                break
            line.append(segs[m][1])
        while key(line[-1]) != key(line[0]):          # 뒤로: 시작점에서 끝나는 선분
            m = take(by_end, key(line[0]), unit(line[1], line[0]) if len(line) > 1 else (0.0, 0.0), False)
            if m is None:
                break
            line.insert(0, segs[m][0])
        lines.append([[float(p[0]), float(p[1])] for p in line])
    return lines


def contour_geojson(field: dict, levels: tuple[float, ...], layer: str) -> dict:
    feats = []
    for lv in levels:
        for line in marching_squares(field["Z"], field["lats"], field["lons"], lv):
            if len(line) < 2:
                continue
            feats.append({"type": "Feature", "properties": {"level": lv, "layer": layer},
                          "geometry": {"type": "LineString", "coordinates": line}})
    return {"type": "FeatureCollection", "features": feats}


def cells_geojson(lat: np.ndarray, lon: np.ndarray, g: dict, props: pd.DataFrame, value_key: str) -> dict:
    """칸 사각형 폴리곤 층(보고 밀도·ENV_LOSS)."""
    feats = []
    for r in props.itertuples(index=False):
        x0 = g["lons"][0] + r.ix * g["dlon"]; y0 = g["lats"][0] + r.iy * g["dlat"]
        x1, y1 = x0 + g["dlon"], y0 + g["dlat"]
        p = {k: (float(v) if isinstance(v, (float, np.floating)) else int(v)) for k, v in r._asdict().items() if k not in ("ix", "iy")}
        feats.append({"type": "Feature", "properties": p,
                      "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}})
    return {"type": "FeatureCollection", "features": feats, "value_key": value_key}


# ── 배 원인 카드 (§4-11) ───────────────────────────────────────────────────
def ship_cards(rows: pd.DataFrame, env_at_pos: float | None, near_ships: int | None, slot_use: float | None,
               others_resid_median: float | None, tx_weak_rule: bool) -> dict:
    """네 몫(송신기 약함 / 해역 환경 / 혼잡·간섭 / 미상) + 종합 3단계.

    dB 귀속(문서 §3):
      전체 저하 T = min(0, mean snr_resid)               — 거리 기대 대비 SNR 부족분
      환경   e = min(0, 환경 잔차 등고선 값)              — 이 위치가 원래 낮게 들리는 정도(다른 배들로 만든 장)
      송신기 x = min(0, mean rssi_resid − e)             — 같은 자리 다른 배보다 더 약한 정도(배 고유)
      혼잡   c = min(0, mean snr_resid − mean rssi_resid)  — 세기로 설명 안 되는 SNR 추가 손실 = 잡음·간섭 상승
      미상   u = min(0, T − (e + x + c))                  — 셋으로 설명 안 되는 나머지(환경값 없음 등)
      몫 % = |부분| ÷ (|e|+|x|+|c|+|u|). 전체 저하가 0 이면(기대보다 잘 들림) 몫은 모두 0.
    """
    n = int(len(rows))
    rssi = rows["rssi"].to_numpy(float)
    resid = rows["rssi_resid"].to_numpy(float)
    sres = rows["snr_resid"].to_numpy(float) if "snr_resid" in rows.columns else np.full(n, np.nan)
    rssi_med = float(np.nanmedian(rssi)) if n and np.isfinite(rssi).any() else None
    margin = (rssi_med - SENS_DBM) if rssi_med is not None else None
    r_mean = float(np.nanmean(resid)) if np.isfinite(resid).any() else None
    r_se = float(np.nanstd(resid) / math.sqrt(max(1, np.isfinite(resid).sum()))) if np.isfinite(resid).any() else None
    s_mean = float(np.nanmean(sres)) if np.isfinite(sres).any() else None
    tx_se = mlall.threshold("txweak_se")
    vs_others = (r_mean - others_resid_median) if (r_mean is not None and others_resid_median is not None) else None
    tx_flag = bool(tx_weak_rule or (vs_others is not None and r_se is not None and vs_others <= -tx_se * r_se and n >= 25))
    e = min(0.0, env_at_pos) if env_at_pos is not None else None
    x = min(0.0, r_mean - (e or 0.0)) if r_mean is not None else None
    c = min(0.0, s_mean - r_mean) if (s_mean is not None and r_mean is not None) else None
    T = min(0.0, s_mean) if s_mean is not None else (min(0.0, r_mean) if r_mean is not None else None)
    parts = {"tx": x, "env": e, "cong": c}
    explained = sum(v for v in parts.values() if v is not None)
    u = min(0.0, T - explained) if T is not None else None
    parts["unknown"] = u
    absum = sum(abs(v) for v in parts.values() if v is not None)
    shares = {k: (abs(v) / absum if (v is not None and absum > 0) else 0.0) for k, v in parts.items()}
    thr = env_threshold_db()
    return {
        "n_rows": n, "rssi_med_dbm": rssi_med, "margin_db": margin, "level": margin_level(margin),
        "level_label": LEVEL_LABEL.get(margin_level(margin), "자료 없음"),
        "rssi_resid_mean_db": r_mean, "rssi_resid_se_db": r_se, "snr_resid_mean_db": s_mean,
        "shares": shares, "parts_db": parts,
        "cards": [
            {"key": "tx", "label": "송신기 약함", "share": shares["tx"], "db": x, "flag": tx_flag,
             "text": (f"다른 배보다 {abs(vs_others):.1f} dB {'약하게' if vs_others < 0 else '세게'} 들림" if vs_others is not None else "비교할 다른 배 없음")
                     + (f" · 룰 TX_WEAK" if tx_weak_rule else "") + (f" (기준 {tx_se:g} SE)" if not tx_weak_rule else "")},
            {"key": "env", "label": "해역 환경(가림)", "share": shares["env"], "db": e,
             "flag": bool(env_at_pos is not None and env_at_pos <= -thr),
             "text": (f"이 위치는 원래 {abs(env_at_pos):.1f} dB {'낮게' if env_at_pos < 0 else '높게'} 들리는 곳" if env_at_pos is not None else "환경 등고선 값 없음(표본 부족)")
                     + f" (가림 의심 기준 −{thr:g} dB)"},
            {"key": "cong", "label": "혼잡·간섭", "share": shares["cong"], "db": c,
             "flag": bool(slot_use is not None and slot_use >= 0.5),
             "text": (f"주변 배 {near_ships}척(3 km)" if near_ships is not None else "주변 배 수 없음")
                     + (f", 슬롯 {slot_use * 100:.0f}% 사용" if slot_use is not None else "")},
            {"key": "unknown", "label": "미상", "share": shares["unknown"], "db": u, "flag": False,
             "text": "위 셋으로 설명되지 않는 나머지"},
        ],
        "basis": {"sens_dbm": SENS_DBM, "prot_db": PROT_DB, "env_threshold_db": thr, "tx_se": tx_se, "near_km": NEAR_KM},
    }
