"""(d) 등고선 GeoJSON 이 유효하고 레벨이 §4 값(수신 여유 0/10/20 · 환경 잔차 −10/−5/0/+5)인지 + marching squares 단위 검사.

    .\\venv\\Scripts\\python.exe tests\\check_contours.py [http://127.0.0.1:8800]

단위 검사는 서버 없이 coast.signal 만 쓴다: Z = x 인 평면의 0.5 등고선은 x = 0.5 세로선 하나, NaN 칸은 비워진다,
경험 반분산 → 정규 크리깅이 표본점 값을 (거의) 그대로 재현한다(크리깅의 정확 보간 성질).
"""
from __future__ import annotations

import sys

import numpy as np

from _common import PERIODS, Check, api
from coast import signal  # noqa: E402  (_common 이 sys.path 를 넣는다)

EXPECT = {"margin": [0.0, 10.0, 20.0], "env": [-10.0, -5.0, 0.0, 5.0]}


def valid_linestring(coords) -> bool:
    return len(coords) >= 2 and all(len(p) == 2 and -180 <= p[0] <= 180 and -90 <= p[1] <= 90 for p in coords)


def main() -> int:
    c = Check("contours")
    # ── 단위: marching squares ────────────────────────────────────────
    lons = np.linspace(0, 1, 11); lats = np.linspace(0, 1, 6)
    Z = np.tile(lons, (len(lats), 1))                     # Z = x
    lines = signal.marching_squares(Z, lats, lons, 0.5)
    c.eq("MS 평면 Z=x 레벨 0.5 → 선 1개", len(lines), 1)
    if lines:
        xs = [p[0] for p in lines[0]]
        c.ok("MS 선이 x=0.5 세로선", max(abs(x - 0.5) for x in xs) < 1e-9 and len(lines[0]) == len(lats))
    Z2 = Z.copy(); Z2[2, :] = np.nan
    lines2 = signal.marching_squares(Z2, lats, lons, 0.5)
    c.ok("MS NaN 행이 있으면 선이 끊긴다", len(lines2) == 2 and all(len(l) >= 2 for l in lines2))
    c.eq("MS 레벨 밖(2.0)은 선 없음", len(signal.marching_squares(Z, lats, lons, 2.0)), 0)
    # 원뿔(거리장) 레벨 → 닫힌 고리 하나, 반지름 ≈ 레벨
    g = np.linspace(-1, 1, 41); X, Y = np.meshgrid(g, g); D = np.hypot(X, Y)
    ring = signal.marching_squares(D, g, g, 0.5)
    c.eq("MS 원 레벨 0.5 → 고리 1개", len(ring), 1)
    if ring:
        rad = [np.hypot(p[0], p[1]) for p in ring[0]]
        c.ok("MS 원 반지름 ≈ 0.5", max(abs(r - 0.5) for r in rad) < 0.03, f"max dev {max(abs(r - 0.5) for r in rad):.3f}")
        c.ok("MS 고리가 닫힘", np.hypot(ring[0][0][0] - ring[0][-1][0], ring[0][0][1] - ring[0][-1][1]) < 1e-9)
    # ── 단위: 정규 크리깅의 정확 보간 ─────────────────────────────────
    rng = np.random.default_rng(1)
    xy = rng.uniform(0, 20, (300, 2)); v = 5 * np.sin(xy[:, 0] / 4) + 3 * np.cos(xy[:, 1] / 5) + rng.normal(0, 0.3, 300)
    vario = signal.fit_variogram(xy, v)
    c.ok("반분산 모델 적합", vario["fitted"] and vario["c1"] > 0 and vario["a"] > 0)
    pred = signal.ordinary_kriging(xy, v, xy[:50], vario)
    c.ok("OK 표본점 재현(너깃 작으면 ≈ 정확)", float(np.sqrt(np.mean((pred - v[:50]) ** 2))) < 0.6, f"rmse {np.sqrt(np.mean((pred - v[:50]) ** 2)):.3f}")
    mid = np.array([[10.0, 10.0]]); truth = 5 * np.sin(10 / 4) + 3 * np.cos(10 / 5)
    c.ok("OK 중간점 예측 오차 < 1", abs(float(signal.ordinary_kriging(xy, v, mid, vario)[0]) - truth) < 1.0)
    c.ok("IDW 표본점 재현", float(np.max(np.abs(signal.idw(xy, v, xy[:50]) - v[:50]))) < 1e-6)
    # ── API ──────────────────────────────────────────────────────────
    st = api("/api/state")
    c.eq("state margin_levels", st["signal_basis"]["margin_levels"], EXPECT["margin"])
    c.eq("state env_levels", st["signal_basis"]["env_levels"], EXPECT["env"])
    c.eq("state sens_dbm", st["signal_basis"]["sens_dbm"], -107.0)
    c.eq("state prot_db", st["signal_basis"]["prot_db"], 10.0)
    c.eq("state env_threshold_db = ml_all rssi_resid_db", st["signal_basis"]["env_threshold_db"], 4.0)
    for src, periods in PERIODS.items():
        for t0, t1 in periods[:1]:
            for layer, levels in EXPECT.items():
                gj = api("/api/contours", src=src, layer=layer, t0=t0, t1=t1)
                tag = f"{src} {layer}"
                c.eq(f"{tag} type", gj["type"], "FeatureCollection")
                c.eq(f"{tag} levels", gj["levels"], levels)
                c.ok(f"{tag} 등고선 1개 이상", len(gj["features"]) > 0, f"features={len(gj['features'])} info={gj.get('info')}")
                c.ok(f"{tag} 모든 feature 가 LineString·좌표 유효", all(f["type"] == "Feature" and f["geometry"]["type"] == "LineString" and valid_linestring(f["geometry"]["coordinates"]) for f in gj["features"]))
                c.ok(f"{tag} feature level ∈ §4 값", set(f["properties"]["level"] for f in gj["features"]) <= set(levels))
                c.ok(f"{tag} 보간 방법 표기", gj["info"]["method"] in ("kriging", "idw"))
                c.ok(f"{tag} 범례에 생존 편향 주의", "생존 편향" in gj["legend"]["caveat"])
                c.ok(f"{tag} 설계값 표기", gj["legend"]["design"]["grid_km"] == 0.5 and gj["legend"]["design"]["max_dist_km"] == 3.0 and gj["legend"]["design"]["min_ships_per_cell"] == 3)
                if gj["info"]["method"] == "kriging":
                    c.ok(f"{tag} 반분산 모델 기록", gj["info"]["variogram"]["model"] == "exponential")
                # 좌표가 부산 근처(해역 안)
                lons = [p[0] for f in gj["features"] for p in f["geometry"]["coordinates"]]
                lats = [p[1] for f in gj["features"] for p in f["geometry"]["coordinates"]]
                c.ok(f"{tag} 좌표 범위(한반도 남해)", 125 < min(lons) and max(lons) < 132 and 33 < min(lats) and max(lats) < 37)
            for layer in ("density", "envloss"):
                gj = api("/api/contours", src=src, layer=layer, t0=t0, t1=t1)
                c.ok(f"{src} {layer} 폴리곤 유효", len(gj["features"]) > 0 and all(f["geometry"]["type"] == "Polygon" and len(f["geometry"]["coordinates"][0]) == 5 for f in gj["features"]))
                key = "ship_minutes" if layer == "density" else "envloss_ratio"
                c.ok(f"{src} {layer} 값 키", all(key in f["properties"] for f in gj["features"]))
    return c.done()


if __name__ == "__main__":
    sys.exit(main())
