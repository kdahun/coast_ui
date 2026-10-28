"""(c) ships_at 가 시점 직전 마지막 보고를 주는지 + (2차) 선수 방향 — parquet 과 대조.

    .\\venv\\Scripts\\python.exe tests\\check_ships_at.py [http://127.0.0.1:8801]

시점 3개 × 소스 2개.
  · 배 수·시각·위치 = parquet 에서 배마다 has_pos & vsi_time ≤ t 인 마지막 행
  · heading = 그 행의 heading(511·결측·범위 밖이면 None), cog = 그 행의 course(360·결측·범위 밖이면 항적 추정 또는 None)
  · 출처 우선순위: heading → cog(데이터) → track(항적 추정, 직전 30 m 이상 떨어진 위치의 방위) → last(기간 안 시점 이전 마지막 유효 HDG/COG) → none(북쪽 0°)
  · 원형(방향 null) 배 0척 — dir_deg 가 모든 배에 있다
  · 시점마다 출처별 척수를 표로 찍는다(CHANGES 에 옮겨 적는다)
"""
from __future__ import annotations

import math
import sys
from collections import Counter

import numpy as np
import pandas as pd

from _common import Check, api, read_parquet

CASES = {"real": [(None, None, None), (None, None, "2026-06-10T01:30:00"), ("2026-06-09T20:00:00", "2026-06-09T23:00:00", "2026-06-09T22:10:00")],
         "ds015": [(None, None, None), (None, None, "2020-03-20T18:00:00"), ("2020-03-20T12:00:00", "2020-03-20T15:00:00", "2020-03-20T13:37:00")]}
VALID = lambda v, hi=360.0: v is not None and not pd.isna(v) and 0.0 <= float(v) < hi   # noqa: E731


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2); dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2); y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def hav_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


def expected_direction(tr: pd.DataFrame) -> tuple[str, float | None]:
    """한 배의 (시점 이전, 기간 안) 위치 보고 행 → 기대 (출처, 각)."""
    last = tr.iloc[-1]
    if VALID(last["heading"]):
        return "heading", float(last["heading"])
    if VALID(last["course"]):
        return "cog", float(last["course"])
    lat, lon = last["lat"], last["lon"]
    for k in range(len(tr) - 2, max(-1, len(tr) - 22), -1):
        if hav_m(tr["lat"].iloc[k], tr["lon"].iloc[k], lat, lon) >= 30:
            return "track", bearing(tr["lat"].iloc[k], tr["lon"].iloc[k], lat, lon)
    for k in range(len(tr) - 2, -1, -1):
        if VALID(tr["heading"].iloc[k]):
            return "last", float(tr["heading"].iloc[k])
        if VALID(tr["course"].iloc[k]):
            return "last", float(tr["course"].iloc[k])
    return "none", 0.0


def main() -> int:
    c = Check("ships_at")
    table = []
    for src, cases in CASES.items():
        df = read_parquet(src, ["mmsi", "vsi_time", "lat", "lon", "has_pos", "heading", "course", "speed"])
        df = df[df["has_pos"] & df["lat"].notna() & df["lon"].notna()].sort_values("vsi_time", kind="stable")
        for t0, t1, t in cases:
            r = api("/api/ships_at", src=src, t=t, t0=t0, t1=t1, judge="rule")
            ships = {s["mmsi"]: s for s in r["ships"]}
            a = pd.Timestamp(t0) if t0 else df["vsi_time"].min()
            b = pd.Timestamp(t1) if t1 else df["vsi_time"].max()
            tt = pd.Timestamp(t) if t else b
            sub = df[(df["vsi_time"] >= a) & (df["vsi_time"] <= tt)]
            last = sub.groupby("mmsi").tail(1).set_index("mmsi")
            tag = f"{src} t={t or '끝'} 기간={t0 or '전체'}"
            c.eq(f"{tag} 배 수", len(ships), len(last))
            c.ok(f"{tag} 모든 배가 시점 이전", all(pd.Timestamp(s["t"]) <= tt for s in ships.values()))
            c.ok(f"{tag} 모든 배가 기간 안", all(pd.Timestamp(s["t"]) >= a for s in ships.values()))
            bad = 0
            for mm, row in last.iterrows():
                s = ships.get(int(mm))
                if s is None or pd.Timestamp(s["t"]) != row["vsi_time"].floor("s") or abs(s["lat"] - row["lat"]) > 1e-4 or abs(s["lon"] - row["lon"]) > 1e-4:
                    bad += 1
            c.eq(f"{tag} 마지막 보고(시각·위치) 불일치 배 수", bad, 0)
            c.ok(f"{tag} age_s = 시점 − 마지막", all(abs(s["age_s"] - (tt - pd.Timestamp(s["t"])).total_seconds()) <= 2 for s in ships.values()))
            c.ok(f"{tag} near_ships ≥ 0", all(s["near_ships"] >= 0 for s in ships.values()))
            # ── 2차: 선수·COG = parquet 마지막 위치 보고 값(511·360 제외) ──
            bad_h = bad_c = bad_s = 0
            for mm, row in last.iterrows():
                s = ships[int(mm)]
                exp_h = float(row["heading"]) if VALID(row["heading"]) else None
                if (s["heading"] is None) != (exp_h is None) or (exp_h is not None and abs(s["heading"] - exp_h) > 1e-6):
                    bad_h += 1
                if VALID(row["course"]):
                    if s["cog_source"] != "data" or abs(s["cog"] - float(row["course"])) > 0.06:
                        bad_c += 1
                elif s["cog_source"] == "data":
                    bad_c += 1
                exp_s = float(row["speed"]) if VALID(row["speed"], 102.3) else None
                if (s["sog"] is None) != (exp_s is None) or (exp_s is not None and abs(s["sog"] - exp_s) > 0.01):
                    bad_s += 1
            c.eq(f"{tag} heading ≠ parquet (511 제외) 배 수", bad_h, 0)
            c.eq(f"{tag} cog(데이터) ≠ parquet (360 제외) 배 수", bad_c, 0)
            c.eq(f"{tag} sog ≠ parquet (102.3 제외) 배 수", bad_s, 0)
            # ── 우선순위·출처 — 배마다 기대 출처와 각 ──
            c.ok(f"{tag} 원형(방향 null) 배 0척", all(s["dir_deg"] is not None and s["dir_source"] in ("heading", "cog", "track", "last", "none") for s in ships.values()))
            c.ok(f"{tag} none 은 북쪽 0°", all(s["dir_deg"] == 0.0 for s in ships.values() if s["dir_source"] == "none"))
            c.ok(f"{tag} dir_source 와 필드 일치", all(
                (s["dir_source"] == "heading" and s["heading"] is not None and s["dir_deg"] == s["heading"]) or
                (s["dir_source"] == "cog" and s["heading"] is None and s["cog_source"] == "data" and s["dir_deg"] == s["cog"]) or
                (s["dir_source"] == "track" and s["heading"] is None and s["cog_source"] == "track" and s["dir_deg"] == s["cog"]) or
                (s["dir_source"] == "last" and s["heading"] is None and s["cog"] is None and s["dir_deg"] == s["last_dir"] and s["last_dir_source"] in ("heading", "cog")) or
                (s["dir_source"] == "none" and s["heading"] is None and s["cog"] is None and s["last_dir"] is None)
                for s in ships.values()))
            bad_dir = []
            groups = {mm: g for mm, g in sub.groupby("mmsi")}
            for mm, s in ships.items():
                exp_src, exp_deg = expected_direction(groups[mm])
                if exp_src != s["dir_source"] or abs(((s["dir_deg"] - exp_deg) + 180) % 360 - 180) > 0.6:
                    bad_dir.append((mm, s["dir_source"], s["dir_deg"], exp_src, round(exp_deg, 1)))
            c.eq(f"{tag} 우선순위대로 출처·각 (불일치 배 수)", len(bad_dir), 0)
            if bad_dir:
                print("   예:", bad_dir[:5])
            cnt = Counter(s["dir_source"] for s in ships.values())
            table.append((src, t or "끝", t0 or "전체", len(ships), cnt.get("heading", 0), cnt.get("cog", 0), cnt.get("track", 0), cnt.get("last", 0), cnt.get("none", 0)))
    print("\n출처별 척수 (HDG / COG / 항적 / last / none) — CHANGES §3-4 표")
    print("| 소스 | 시점 | 기간 | 배 | HDG | COG | 항적 | last | none |\n|---|---|---|---|---|---|---|---|---|")
    for row in table:
        print("| " + " | ".join(str(x) for x in row) + " |")
    print()
    return c.done()


if __name__ == "__main__":
    sys.exit(main())
