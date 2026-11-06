"""ParquetProvider — ml_all 산출물(`output/datagen/risk_map_*.parquet`)을 읽기만 하는 1차 제공자.

읽는 것
  risk_map_real.parquet   부산 실해역(수신소 1) — 룰·XGB G·kNN G 판정 열
  risk_map_ds015.parquet  생성 벌 ds_015 — + 정답 열(y_truth__*)
  risk_map_ds024.parquet  생성 벌 ds_024 — + 정답 열 (2026-10-28 A4 회차 평가 벌)
  risk_map_ds033.parquet  생성 벌 ds_033 — + 정답 열 (2026-10-30 A6 회차 평가 벌)
  (2차, 2026-10-27)      risk_map 에 `heading`(선수, 도)·`course`(COG, 도)·`speed`(SOG, 노트) 열이 들어왔다
                          (ml_all build_risk_map.py 가 DB 값 그대로 — AIS 관례 HDG 511 · COG 360 · SOG 102.3 = "없음").
                          BASE_COLS 로 바로 읽는다. 세 열 중 risk_map 에 **없는 것만** ml_table_<key>.parquet 에서
                          (mmsi, vsi_time) 조인해 채운다(있는 열은 조인하지 않는다 — speed_x/_y 충돌 금지).
  config/sea_mask.json    항행수역 격자(등고선 육지 마스크·배경 윤곽)

방향 우선순위(ships_at · static/rotation.js 와 같다): 선수 HDG(0~359) → COG 데이터(0~359.9) → 항적 추정(직전 30 m 이상
떨어진 위치의 방위) → 그 배의 기간 안(시점 이전) 마지막 유효 HDG/COG('last') → 없으면 북쪽 0° 고정('none').
원형 점은 없다 — 'none' 배도 에셋으로(북쪽) 그리고 "방향 미상" 표식을 붙인다.

절대 쓰지 않는다. ml_all 쪽 파일은 mtime 이 바뀌면 다시 읽는다. 응답은 (소스, 기간, 시점, 판정기)별 캐시.
"""
from __future__ import annotations

import math
import threading
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .. import judge as J
from .. import mlall, msgkind, signal
from .base import Delta, Filter, ShipDetail, ShipState, Source, WindowStats

SOURCES = {
    "real": {"file": "risk_map_real", "label": "부산 실해역 (수신소 1)", "kind": "real", "ml_table": "ml_table_real.parquet"},
    "ds015": {"file": "risk_map_ds015", "label": "생성 벌 ds_015 (정답 있음)", "kind": "generated", "ml_table": "ml_table_ds015.parquet"},
    # 2026-10-28 A4 재학습 회차(학습 ds_016~023) 평가 벌 — ml_all build_risk_map.py --dataset ds_024
    "ds024": {"file": "risk_map_ds024", "label": "생성 벌 ds_024 (정답 있음)", "kind": "generated", "ml_table": "ml_table_ds024.parquet"},
    # 2026-10-30 A6 재학습 회차(학습 ds_025~032) 평가 벌 — ml_all build_risk_map.py --dataset ds_033
    "ds033": {"file": "risk_map_ds033", "label": "생성 벌 ds_033 (정답 있음)", "kind": "generated", "ml_table": "ml_table_ds033.parquet"},
}
BASE_COLS = ["mmsi", "vsi_time", "site_id", "msg_type", "channel", "rssi", "snr", "rssi_resid", "snr_resid",
             "dist_site_km", "lat", "lon", "has_pos", "frame", "code_primary", "heading", "course", "speed"]
DIR_COLS = ("heading", "course", "speed")     # risk_map 에 없을 때만 ml_table 에서 조인(폴백)
MAX_TRACK = 2000
MIN_MOVE_M = 30.0          # 항적 추정 침로: 이보다 덜 움직였으면 침로 없음(설계값)
TRACK_LOOKBACK = 20        # 항적 추정: 거슬러 보는 최대 행 수(설계값)
HDG_NONE = 511.0           # AIS 관례 — 선수 없음
COG_NONE = 360.0           # AIS 관례 — COG 없음 (0~359.9 만 유효)
SOG_NONE = 102.3           # AIS 관례 — SOG 없음


def valid_heading(v) -> bool:
    return v is not None and math.isfinite(v) and 0.0 <= v < 360.0


def valid_cog(v) -> bool:
    return v is not None and math.isfinite(v) and 0.0 <= v < 360.0


def valid_sog(v) -> bool:
    return v is not None and math.isfinite(v) and 0.0 <= v < SOG_NONE


class _Loaded:
    def __init__(self, df: pd.DataFrame, meta: dict):
        self.df = df
        self.meta = meta
        self.cb = J.codebook()
        self.t = df["vsi_time"].to_numpy("datetime64[ns]")
        self.mmsi = df["mmsi"].to_numpy(np.int64)
        self.site = df["site_id"].to_numpy(np.int64)
        self.kind = msgkind.kind_index(df["msg_type"].to_numpy())
        self.has_pos = df["has_pos"].to_numpy(bool) & np.isfinite(df["lat"].to_numpy(float)) & np.isfinite(df["lon"].to_numpy(float))
        self.lat = df["lat"].to_numpy(float)
        self.lon = df["lon"].to_numpy(float)
        self.heading = df["heading"].to_numpy(float)
        self.course = df["course"].to_numpy(float)
        self.speed = df["speed"].to_numpy(float)
        self._states: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self.lock = threading.Lock()
        # 프레임(분)별 슬롯 사용률 — 수신소마다 (frame 당 보고 수 / 2250)
        fr = df.groupby(["site_id", "frame"], sort=False).size()
        self.slot_use = {k: float(v) / signal.SLOTS_PER_FRAME for k, v in fr.items()}

    def states(self, judge: str) -> tuple[np.ndarray, np.ndarray]:
        with self.lock:
            if judge not in self._states:
                self._states[judge] = J.row_state(self.df, judge, self.cb)
            return self._states[judge]

    def judges(self) -> list[str]:
        return [j for j in J.JUDGES if J.judge_available(self.df, j, self.cb)]


def _iso(ts) -> str:
    return pd.Timestamp(ts).isoformat(timespec="seconds")


def _parse_t(s: str | None, default: pd.Timestamp) -> pd.Timestamp:
    if s is None or s == "" or s == "all":
        return default
    try:
        return pd.Timestamp(s)
    except (ValueError, TypeError) as e:
        raise ValueError(f"시각 형식 오류 '{s}' — ISO(예 2026-06-09T18:00:00)") from e


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        return None if not math.isfinite(float(v)) else round(float(v), 3)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def _dir_valid_rates(df: pd.DataFrame) -> dict:
    """위치 보고 행 중 유효 HDG(0~359)·COG(0~359.9)·SOG 비율 — 소스 메타용."""
    pos = df["has_pos"].to_numpy(bool)
    if not pos.any():
        return {"heading": 0.0, "course": 0.0, "speed": 0.0}
    h = df["heading"].to_numpy(float)[pos]; c = df["course"].to_numpy(float)[pos]; sp = df["speed"].to_numpy(float)[pos]
    return {"heading": round(float(np.mean((h >= 0) & (h < 360))), 4), "course": round(float(np.mean((c >= 0) & (c < 360))), 4),
            "speed": round(float(np.mean((sp >= 0) & (sp < SOG_NONE))), 4)}


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """두 위치의 초기 방위(도, 북 0 시계방향)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371000.0 * 2 * math.asin(math.sqrt(a))


class ParquetProvider:
    def __init__(self, out_dir: Path | None = None):
        self.out_dir = out_dir or mlall.output_dir()
        self._loaded: dict[str, tuple[float, _Loaded]] = {}
        self._cache: dict[tuple, object] = {}
        self._lock = threading.Lock()

    # ── 읽기 ────────────────────────────────────────────────────────────
    def _files(self, src: str) -> tuple[Path, Path]:
        if src not in SOURCES:
            raise KeyError(f"src 는 {list(SOURCES)} 중 하나 — 받은 값 '{src}'")
        f = SOURCES[src]["file"]
        return self.out_dir / f"{f}.parquet", self.out_dir / f"{f}.meta.json"

    def _load(self, src: str) -> _Loaded:
        pqf, mj = self._files(src)
        if not pqf.exists():
            raise FileNotFoundError(f"{src} 지도용 표가 없습니다 — {pqf} (ml_all 에서 build_risk_map.py 로 만든다)")
        mtime = pqf.stat().st_mtime
        with self._lock:
            cur = self._loaded.get(src)
            if cur and cur[0] == mtime:
                return cur[1]
            t0 = time.time()
            names = pq.ParquetFile(pqf).schema.names
            R = mlall.rules()
            attrs = sorted({a for c in R.CODES for a in R.ATTR_OF_CODE.get(c, ())})
            cols = [c for c in BASE_COLS if c in names]
            cols += [c for c in names if c.startswith(("y_rule__", "y_truth__")) or c in (f"knn_unknown_{J.ML_VERSION}",)
                     or c.startswith((f"xgb_{J.ML_VERSION}__", f"knn_{J.ML_VERSION}__"))]
            cols += [f"{p}{a}" for p in ("rule_", "truth_") for a in attrs if f"{p}{a}" in names]
            df = pd.read_parquet(pqf, columns=cols)
            df["vsi_time"] = pd.to_datetime(df["vsi_time"])
            if "has_pos" not in df.columns:
                df["has_pos"] = df["lat"].notna() & df["lon"].notna()
            for c in ("snr_resid", "rssi_resid", "rssi", "snr", "dist_site_km"):
                if c not in df.columns:
                    df[c] = np.nan
            df = df.sort_values("vsi_time", kind="stable").reset_index(drop=True)
            # 방향·속력 — risk_map 에 있는 열(heading·course·speed)은 그대로 쓰고, **없는 열만** ml_table 에서 조인(폴백).
            # 있는 열을 다시 조인하면 speed_x/_y 가 생기므로 금지.
            in_map = [c for c in DIR_COLS if c in df.columns]
            missing = [c for c in DIR_COLS if c not in df.columns]
            sog_join = {"joined": False, "file": SOURCES[src]["ml_table"], "in_risk_map": in_map, "cols": [], "hit_rate": None}
            mt = self.out_dir / SOURCES[src]["ml_table"]
            if missing and mt.exists():
                mnames = pq.ParquetFile(mt).schema.names
                want = [c for c in missing if c in mnames]
                if want:
                    m = pd.read_parquet(mt, columns=["mmsi", "vsi_time"] + want)
                    m["vsi_time"] = pd.to_datetime(m["vsi_time"])
                    m = m.drop_duplicates(["mmsi", "vsi_time"])
                    df = df.merge(m, on=["mmsi", "vsi_time"], how="left")
                    sog_join.update(joined=True, cols=want, hit_rate=float(df["speed"].notna().mean()) if "speed" in df.columns else None)
            for c in DIR_COLS:
                if c not in df.columns:
                    df[c] = np.nan
                df[c] = df[c].astype(float)
            assert not any(c.endswith(("_x", "_y")) for c in df.columns), "조인 충돌(speed_x/_y)"
            meta = {}
            if mj.exists():
                import json
                meta = json.loads(mj.read_text(encoding="utf-8"))
            meta = {"site": meta.get("site"), "has_truth": bool(meta.get("has_truth")) or any(c.startswith("y_truth__") for c in df.columns),
                    "t_min": _iso(df["vsi_time"].min()), "t_max": _iso(df["vsi_time"].max()),
                    "t_min_exact": pd.Timestamp(df["vsi_time"].min()), "t_max_exact": pd.Timestamp(df["vsi_time"].max()), "rows": int(len(df)),
                    "n_mmsi": int(df["mmsi"].nunique()), "file": str(pqf.name), "file_mtime": mtime, "load_seconds": round(time.time() - t0, 1),
                    "sog_join": sog_join, "heading_col": "heading" in in_map, "cog_col": "course" in in_map,
                    "dir_valid": _dir_valid_rates(df)}
            L = _Loaded(df, meta)
            self._loaded[src] = (mtime, L)
            self._cache = {k: v for k, v in self._cache.items() if k[1] != src}
            return L

    def _memo(self, key: tuple, fn):
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        val = fn()
        with self._lock:
            if len(self._cache) > 256:
                self._cache.clear()
            self._cache[key] = val
        return val

    # ── Source ──────────────────────────────────────────────────────────
    def sources(self) -> list[Source]:
        out: list[Source] = []
        for sid, s in SOURCES.items():
            pqf, _ = self._files(sid)
            if not pqf.exists():
                continue
            L = self._load(sid)
            out.append({"id": sid, "label": s["label"], "kind": s["kind"], "t_min": L.meta["t_min"], "t_max": L.meta["t_max"],
                        "sites": sorted(int(x) for x in np.unique(L.site)), "has_truth": bool(L.meta["has_truth"]),
                        "judges": L.judges(), "rows": L.meta["rows"], "n_mmsi": L.meta["n_mmsi"],
                        "sog_join": L.meta["sog_join"], "heading_available": L.meta["heading_col"], "cog_available": L.meta["cog_col"],
                        "dir_valid": L.meta["dir_valid"]})
        return out

    def _range(self, L: _Loaded, t0: str | None, t1: str | None) -> tuple[pd.Timestamp, pd.Timestamp]:
        # 기본값은 초 단위로 자른 ISO 가 아니라 실제 최소·최대 시각 — 마지막 초의 행이 빠지지 않게
        a = _parse_t(t0, L.meta["t_min_exact"])
        b = _parse_t(t1, L.meta["t_max_exact"])
        if b < a:
            a, b = b, a
        return a, b

    def _judge(self, L: _Loaded, flt: Filter) -> str:
        j = (flt or {}).get("judge") or "rule"
        if j not in L.judges():
            raise ValueError(f"이 소스에서 쓸 수 없는 판정기 '{j}' — 가능: {L.judges()}")
        return j

    # ── window ──────────────────────────────────────────────────────────
    def _ships_table(self, src: str, a: pd.Timestamp, b: pd.Timestamp, jd: str) -> pd.DataFrame:
        """기간 안 배 단위 표(캐시) — judge.ship_summary + 종류별·신호·시각·수신소."""
        key = ("ships", src, str(a), str(b), jd)

        def build():
            L = self._load(src)
            m = (L.t >= np.datetime64(a)) & (L.t <= np.datetime64(b))
            state, code_idx = L.states(jd)
            S = J.ship_summary(L.mmsi[m], state[m], code_idx[m], L.cb)
            sub = L.df.loc[m, ["mmsi", "vsi_time", "site_id", "rssi", "rssi_resid"]]
            g = sub.groupby("mmsi", sort=True)
            extra = g.agg(t_first=("vsi_time", "min"), t_last=("vsi_time", "max"), rssi_med=("rssi", "median"),
                          resid_mean=("rssi_resid", "mean"), n_sig=("rssi", "count")).reset_index()
            sites = g["site_id"].unique().apply(lambda x: sorted(int(v) for v in x)).rename("sites").reset_index()
            S = S.merge(extra, on="mmsi", how="left").merge(sites, on="mmsi", how="left")
            # 종류별 [행, 비정상, 보류]
            kd = pd.DataFrame({"mmsi": L.mmsi[m], "kind": L.kind[m], "abn": (state[m] == J.ABN).astype(np.int32),
                               "hold": (state[m] == J.HOLD).astype(np.int32)})
            kg = kd.groupby(["mmsi", "kind"]).agg(n=("abn", "size"), abn=("abn", "sum"), hold=("hold", "sum"))
            kinds_map: dict[int, dict] = {}
            for (mm, kk), r in kg.iterrows():
                kinds_map.setdefault(int(mm), {})[msgkind.KEYS[int(kk)]] = [int(r.n), int(r.abn), int(r.hold)]
            S["kinds"] = [{k: kinds_map.get(int(mm), {}).get(k, [0, 0, 0]) for k in msgkind.KEYS} for mm in S["mmsi"]]
            # 대표 코드의 갈래(룰 kind 열; 정답이면 truth_)
            R = mlall.rules()
            pfx = "truth_" if jd == "truth" else "rule_"
            kind_of_code = {}
            for code in S["code"].dropna().unique():
                attrs = R.ATTR_OF_CODE.get(code, ())
                if not attrs:
                    continue
                col = f"{pfx}{attrs[0]}"
                if col not in L.df.columns:
                    continue
                rows = m & (code_idx == L.cb.index(code))
                v = L.df.loc[rows, ["mmsi", col]]
                v = v[v[col].notna() & (v[col].astype(str) != "")]
                first = v.groupby("mmsi")[col].agg(lambda s: str(s.mode().iloc[0]) if len(s) else None)
                for mm, kv in first.items():
                    kind_of_code[int(mm)] = f"{attrs[0]}={kv}"
            S["kind_of_code"] = [kind_of_code.get(int(mm)) for mm in S["mmsi"]]
            S["margin_db"] = S["rssi_med"] - signal.SENS_DBM
            S["level"] = [signal.margin_level(v) for v in S["margin_db"]]
            return S

        return self._memo(key, build)

    @staticmethod
    def _ship_row(r) -> dict:
        return {"mmsi": int(r.mmsi), "state": J.STATE_KEY[int(r.state)], "threat": int(r.threat) if r.threat is not None and not pd.isna(r.threat) else None,
                "impact": r.impact if isinstance(r.impact, str) else None, "code": r.code if isinstance(r.code, str) else None,
                "kind_of_code": r.kind_of_code if isinstance(r.kind_of_code, str) else None,
                "n_rows": int(r.n_rows), "n_abn": int(r.n_abn), "n_hold": int(r.n_hold), "abn_ratio": round(float(r.abn_ratio), 4),
                "t_first": _iso(r.t_first), "t_last": _iso(r.t_last), "sites": list(r.sites) if isinstance(r.sites, list) else [],
                "kinds": r.kinds,
                "signal": {"level": r.level if isinstance(r.level, str) else None, "margin_db": _clean(r.margin_db),
                           "rssi_med": _clean(r.rssi_med), "resid_mean": _clean(r.resid_mean), "n": int(r.n_sig)}}

    def window(self, src: str, t0: str | None, t1: str | None, flt: Filter) -> WindowStats:
        L = self._load(src)
        a, b = self._range(L, t0, t1)
        jd = self._judge(L, flt)
        key = ("window", src, str(a), str(b), jd)

        def build():
            t_ = time.time()
            m = (L.t >= np.datetime64(a)) & (L.t <= np.datetime64(b))
            state, code_idx = L.states(jd)
            S = self._ships_table(src, a, b, jd)
            ships = [self._ship_row(r) for r in S.itertuples(index=False)]
            # 위협 카드 — 배 수(배의 위협) · 비정상 행 수(행의 코드 위협)
            st, ci = state[m], code_idx[m]
            rank_of_row = np.where(ci >= 0, np.array(L.cb.threat_rank)[np.clip(ci, 0, None)], 0)
            cards = []
            for t in mlall.threat_table():
                cards.append({"rank": t["rank"], "key": t["key"], "title": t["title"], "impact": t["impact"], "action": t["action"],
                              "implemented": t["implemented"], "codes": t["codes"],
                              "n_ships": int((S["threat"] == t["rank"]).sum()), "n_rows": int((rank_of_row == t["rank"]).sum())})
            cards.append({"rank": "hold", "key": "HOLD", "title": "보류(환경성 유실·미상·Unknown)", "impact": None, "action": "지켜봄",
                          "n_ships": int((S["state"] == J.HOLD).sum()), "n_rows": int((st == J.HOLD).sum())})
            cards.append({"rank": "ok", "key": "OK", "title": "정상(판정 없음)", "impact": None, "action": "",
                          "n_ships": int((S["state"] == J.OK).sum()), "n_rows": int((st == J.OK).sum())})
            # 해안국 카드 — 수신소마다
            site_cards = []
            for s in sorted(int(x) for x in np.unique(L.site[m])):
                ms = m & (L.site == s)
                sst = state[ms]
                mm = L.mmsi[ms]
                ships_s = pd.DataFrame({"mmsi": mm, "abn": sst == J.ABN, "hold": sst == J.HOLD}).groupby("mmsi").agg(abn=("abn", "max"), hold=("hold", "max"))
                rssi = L.df.loc[ms, "rssi"].to_numpy(float)
                mg = rssi - signal.SENS_DBM
                ship_margin = pd.DataFrame({"m": mm, "v": mg}).groupby("m")["v"].median()
                lv = pd.Series([signal.margin_level(v) for v in ship_margin.to_numpy(float)])
                n_rows_s = int(ms.sum()); n_ships_s = int(len(ships_s))
                site_cards.append({"site": s, "label": f"수신소 {s}", "n_rows": n_rows_s, "n_ships": n_ships_s,
                                   "abn_rows": int((sst == J.ABN).sum()), "abn_row_ratio": float((sst == J.ABN).mean()) if n_rows_s else 0.0,
                                   "abn_ships": int(ships_s["abn"].sum()), "abn_ship_ratio": float(ships_s["abn"].mean()) if n_ships_s else 0.0,
                                   "hold_rows": int((sst == J.HOLD).sum()), "hold_row_ratio": float((sst == J.HOLD).mean()) if n_rows_s else 0.0,
                                   "hold_ships": int((ships_s["hold"] & ~ships_s["abn"]).sum()),
                                   "signal": {"margin_med_db": _clean(np.nanmedian(mg)) if np.isfinite(mg).any() else None,
                                              "ships_good": int((lv == "good").sum()), "ships_fair": int((lv == "fair").sum()), "ships_bad": int((lv == "bad").sum()),
                                              "rows_below_sens": int((mg < 0).sum())},
                                   "kinds": {msgkind.KEYS[k]: int((L.kind[ms] == k).sum()) for k in range(len(msgkind.KEYS))}})
            topo = self._topology(L, m, state, code_idx, S)
            return {"src": src, "t0": _iso(a), "t1": _iso(b), "judge": jd, "judge_label": J.JUDGES[jd],
                    "n_rows": int(m.sum()), "n_ships": int(len(S)), "threat_cards": cards, "site_cards": site_cards,
                    "topology": topo, "ships": ships, "seconds": round(time.time() - t_, 2)}

        return self._memo(key, build)

    def _topology(self, L: _Loaded, m: np.ndarray, state: np.ndarray, code_idx: np.ndarray, S: pd.DataFrame) -> dict:
        """세 층 나무 + (옛) 선버스트/생키 입력 + 표. 해안국 N 곳.

        API 불변 — 2차 화면(④ 수신 현황)은 tables·total 만 쓰고 tree·sankey 는 그리지 않지만, 숫자 검사(check_topology_sum)와
        호환을 위해 그대로 내려준다.
        """
        st, ci, kd, site, mm = state[m], code_idx[m], L.kind[m], L.site[m], L.mmsi[m]
        ranks = np.array(L.cb.threat_rank)
        rank_row = np.where(ci >= 0, ranks[np.clip(ci, 0, None)], 0)
        d = pd.DataFrame({"site": site, "kind": kd, "state": st, "rank": rank_row, "mmsi": mm})
        # 나무: site → kind → state → ship
        tree = []
        for s, ds in d.groupby("site", sort=True):
            node_s = {"name": f"수신소 {int(s)}", "site": int(s), "n_rows": int(len(ds)), "n_ships": int(ds["mmsi"].nunique()), "children": []}
            for k in range(len(msgkind.KEYS)):
                dk = ds[ds["kind"] == k]
                node_k = {"name": msgkind.KINDS[k]["label"], "kind": msgkind.KEYS[k], "n_rows": int(len(dk)), "n_ships": int(dk["mmsi"].nunique()), "children": []}
                for stv in (J.OK, J.ABN, J.HOLD):
                    dst = dk[dk["state"] == stv]
                    ships_c = dst.groupby("mmsi").size().sort_values(ascending=False)
                    node_st = {"name": J.STATE_LABEL[stv], "state": J.STATE_KEY[stv], "n_rows": int(len(dst)), "n_ships": int(len(ships_c)),
                               "ratio": float(len(dst) / len(dk)) if len(dk) else 0.0,
                               "ships": [{"mmsi": int(a), "n_rows": int(b)} for a, b in ships_c.head(20).items()]}
                    node_k["children"].append(node_st)
                node_s["children"].append(node_k)
            tree.append(node_s)
        # 생키: site → kind → (위협 1~5 | 정상 | 보류)
        nodes, links = [], []
        nid: dict[str, int] = {}

        def node(key: str, label: str, typ: str, **extra):
            if key not in nid:
                nid[key] = len(nodes)
                nodes.append({"id": key, "label": label, "type": typ, **extra})
            return nid[key]

        for s, ds in d.groupby("site", sort=True):
            a = node(f"site:{int(s)}", f"수신소 {int(s)}", "site", site=int(s))
            for k, dk in ds.groupby("kind", sort=True):
                b = node(f"kind:{msgkind.KEYS[int(k)]}", msgkind.KINDS[int(k)]["label"], "kind", kind=msgkind.KEYS[int(k)])
                links.append({"source": a, "target": b, "value": int(len(dk)), "ships": int(dk["mmsi"].nunique())})
        for k in range(len(msgkind.KEYS)):            # VDE 도 자리(0)
            node(f"kind:{msgkind.KEYS[k]}", msgkind.KINDS[k]["label"], "kind", kind=msgkind.KEYS[k])
        tt = {t["rank"]: t for t in mlall.threat_table()}
        for (k, stv, rk), dg in d.groupby(["kind", "state", "rank"], sort=True):
            b = nid[f"kind:{msgkind.KEYS[int(k)]}"]
            if stv == J.ABN:
                c = node(f"threat:{int(rk)}", f"위협 {int(rk)} {tt[int(rk)]['title']}", "threat", threat=int(rk), impact=tt[int(rk)]["impact"])
            elif stv == J.HOLD:
                c = node("state:hold", "보류", "hold")
            else:
                c = node("state:ok", "정상", "ok")
            links.append({"source": b, "target": c, "value": int(len(dg)), "ships": int(dg["mmsi"].nunique())})
        for r in sorted(tt):
            node(f"threat:{r}", f"위협 {r} {tt[r]['title']}", "threat", threat=r, impact=tt[r]["impact"])
        node("state:hold", "보류", "hold"); node("state:ok", "정상", "ok")
        # 표: 해안국별 · 종류별 · 선박 상위 20
        by_site = d.groupby("site").agg(n_rows=("mmsi", "size"), n_ships=("mmsi", "nunique"), abn=("state", lambda s: int((s == J.ABN).sum())),
                                        hold=("state", lambda s: int((s == J.HOLD).sum()))).reset_index()
        by_kind = d.groupby("kind").agg(n_rows=("mmsi", "size"), n_ships=("mmsi", "nunique"), abn=("state", lambda s: int((s == J.ABN).sum())),
                                        hold=("state", lambda s: int((s == J.HOLD).sum()))).reset_index()
        by_kind_rows = [{"kind": msgkind.KEYS[int(r.kind)], "label": msgkind.KINDS[int(r.kind)]["label"], "n_rows": int(r.n_rows),
                         "n_ships": int(r.n_ships), "abn": int(r.abn), "hold": int(r.hold)} for r in by_kind.itertuples(index=False)]
        present = {r["kind"] for r in by_kind_rows}
        for k in range(len(msgkind.KEYS)):
            if msgkind.KEYS[k] not in present:
                by_kind_rows.append({"kind": msgkind.KEYS[k], "label": msgkind.KINDS[k]["label"], "n_rows": 0, "n_ships": 0, "abn": 0, "hold": 0})
        by_kind_rows.sort(key=lambda r: msgkind.KEYS.index(r["kind"]))
        imp_order = {"H": 0, "M": 1, "L": 2}
        top = S[S["state"] == J.ABN].copy()
        top["_i"] = top["impact"].map(imp_order).fillna(9)
        top = top.sort_values(["_i", "threat", "abn_ratio"], ascending=[True, True, False]).head(20)
        return {"tree": tree, "sankey": {"nodes": nodes, "links": links},
                "tables": {"by_site": [{"site": int(r.site), "n_rows": int(r.n_rows), "n_ships": int(r.n_ships), "abn": int(r.abn), "hold": int(r.hold)} for r in by_site.itertuples(index=False)],
                           "by_kind": by_kind_rows,
                           "top_ships": [self._ship_row(r) for r in top.itertuples(index=False)]},
                "total": {"n_rows": int(len(d)), "n_ships": int(d["mmsi"].nunique()), "abn": int((st == J.ABN).sum()), "hold": int((st == J.HOLD).sum()), "ok": int((st == J.OK).sum())}}

    # ── ships_at ────────────────────────────────────────────────────────
    def ships_at(self, src: str, t: str | None, flt: Filter, t0: str | None = None, t1: str | None = None) -> list[ShipState]:
        L = self._load(src)
        a, b = self._range(L, t0, t1)
        tt = _parse_t(t, b)
        tt = min(max(tt, a), b)
        jd = self._judge(L, flt)
        key = ("ships_at", src, str(a), str(b), str(tt), jd)

        def build():
            S = self._ships_table(src, a, b, jd).set_index("mmsi")
            m = L.has_pos & (L.t >= np.datetime64(a)) & (L.t <= np.datetime64(tt))
            state, code_idx = L.states(jd)
            idx = np.flatnonzero(m)                       # 시각순 정렬돼 있다 → 배마다 마지막 둘
            mm = L.mmsi[idx]
            # 각 mmsi 의 마지막·그 직전 행 번호
            order = np.lexsort((idx, mm))
            mm_s, idx_s = mm[order], idx[order]
            last_pos = np.r_[np.flatnonzero(mm_s[1:] != mm_s[:-1]), len(mm_s) - 1]
            first_pos = np.r_[0, last_pos[:-1] + 1]
            out = []
            for lp, fp in zip(last_pos, first_pos):
                i = int(idx_s[lp])
                mmsi = int(mm_s[lp])
                lat, lon = float(L.lat[i]), float(L.lon[i])
                age = int((tt - pd.Timestamp(L.t[i])).total_seconds())
                s = S.loc[mmsi] if mmsi in S.index else None
                rec: dict = {"mmsi": mmsi, "lat": round(lat, 5), "lon": round(lon, 5), "t": _iso(L.t[i]), "age_s": age,
                             **self._direction(L, idx_s[fp:lp + 1]),
                             "row_state": J.STATE_KEY[int(state[i])], "row_code": L.cb.order[code_idx[i]] if code_idx[i] >= 0 else None,
                             "site": int(L.site[i])}
                if s is not None:
                    rec.update({"state": J.STATE_KEY[int(s.state)], "threat": int(s.threat) if not pd.isna(s.threat) else None,
                                "impact": s.impact if isinstance(s.impact, str) else None, "code": s.code if isinstance(s.code, str) else None,
                                "kind_of_code": s.kind_of_code if isinstance(s.kind_of_code, str) else None,
                                "abn_ratio": round(float(s.abn_ratio), 4), "n_rows": int(s.n_rows), "n_abn": int(s.n_abn),
                                "signal": {"level": s.level if isinstance(s.level, str) else None, "margin_db": _clean(s.margin_db), "resid_mean": _clean(s.resid_mean)}})
                else:
                    rec.update({"state": "ok", "threat": None, "impact": None, "code": None, "kind_of_code": None, "abn_ratio": 0.0, "n_rows": 0, "n_abn": 0,
                                "signal": {"level": None, "margin_db": None, "resid_mean": None}})
                out.append(rec)
            # 스냅샷 혼잡 — 반경 3 km 안 다른 배 수(10 분 안 보고만)
            if out:
                fresh = np.array([r["age_s"] <= signal.STALE_S for r in out])
                la = np.radians([r["lat"] for r in out]); lo = np.radians([r["lon"] for r in out])
                dlat = la[:, None] - la[None, :]; dlon = lo[:, None] - lo[None, :]
                h = np.sin(dlat / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dlon / 2) ** 2
                dk = 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
                near = ((dk <= signal.NEAR_KM) & fresh[None, :]).sum(axis=1) - fresh.astype(int)
                for r, n in zip(out, near):
                    r["near_ships"] = int(n)
            return out

        return self._memo(key, build)

    # ── 방향 (선수 기본) ──────────────────────────────────────────────────
    @staticmethod
    def _direction(L: _Loaded, rows: np.ndarray) -> dict:
        """한 배의 위치 보고 행 번호들(시각순, 마지막이 현재) → 방향·속력·출처.

        우선순위: heading(HDG 0~359) → cog(COG 데이터 0~359.9) → cog(항적 추정, 'track') → 기간 안 마지막 유효 HDG/COG('last')
        → 북쪽 0° 고정('none'). rotation.js 의 shipCourse 와 같은 순서 — 바꾸면 둘 다 바꿀 것.
        """
        i = int(rows[-1])
        hd, co, sp = L.heading, L.course, L.speed
        lat, lon = float(L.lat[i]), float(L.lon[i])
        heading = float(hd[i]) if valid_heading(hd[i]) else None
        cog, cog_src = None, None
        if valid_cog(co[i]):
            cog, cog_src = float(co[i]), "data"
        else:
            # 항적 추정: 직전 위치 중 30 m 이상 떨어진 가장 최근 것(최대 TRACK_LOOKBACK 행)
            for k in range(len(rows) - 2, max(-1, len(rows) - 2 - TRACK_LOOKBACK), -1):
                j = int(rows[k])
                if haversine_m(L.lat[j], L.lon[j], lat, lon) >= MIN_MOVE_M:
                    cog, cog_src = bearing_deg(L.lat[j], L.lon[j], lat, lon), "track"
                    break
        last_dir, last_src = None, None
        if heading is None and cog is None:
            # 기간 안(시점 이전) 마지막 유효 HDG/COG — 가장 최근 행부터 거슬러, 그 행의 HDG 를 COG 보다 먼저
            for k in range(len(rows) - 2, -1, -1):
                j = int(rows[k])
                if valid_heading(hd[j]):
                    last_dir, last_src = float(hd[j]), "heading"; break
                if valid_cog(co[j]):
                    last_dir, last_src = float(co[j]), "cog"; break
        if heading is not None:
            dir_deg, dir_src = heading, "heading"
        elif cog is not None:
            dir_deg, dir_src = cog, "cog" if cog_src == "data" else "track"
        elif last_dir is not None:
            dir_deg, dir_src = last_dir, "last"
        else:
            dir_deg, dir_src = 0.0, "none"
        sog = float(sp[i]) if valid_sog(sp[i]) else None
        return {"heading": heading, "cog": round(cog, 1) if cog is not None else None, "cog_source": cog_src,
                "last_dir": round(last_dir, 1) if last_dir is not None else None, "last_dir_source": last_src,
                "dir_deg": round(dir_deg, 1), "dir_source": dir_src, "sog": _clean(sog)}

    # ── ship detail ─────────────────────────────────────────────────────
    def ship(self, src: str, mmsi: int, t0: str | None, t1: str | None, flt: Filter) -> ShipDetail:
        L = self._load(src)
        a, b = self._range(L, t0, t1)
        jd = self._judge(L, flt)
        key = ("ship", src, str(a), str(b), jd, int(mmsi))

        def build():
            S = self._ships_table(src, a, b, jd)
            row = S[S["mmsi"] == mmsi]
            if row.empty:
                raise KeyError(f"기간 안에 MMSI {mmsi} 가 없습니다")
            summary = self._ship_row(next(row.itertuples(index=False)))
            m = (L.mmsi == mmsi) & (L.t >= np.datetime64(a)) & (L.t <= np.datetime64(b))
            state, code_idx = L.states(jd)
            sub = L.df.loc[m]
            st = state[m]
            R = mlall.rules()
            cols = J.flag_columns(jd, L.cb)
            pfx = "truth_" if jd == "truth" else "rule_"
            codes = []
            for c in mlall.code_table():
                col = cols[c["code"]]
                n = int(np.nan_to_num(sub[col].to_numpy(float)).sum()) if col in sub.columns else 0
                n_primary = int((code_idx[m] == L.cb.index(c["code"])).sum())
                kinds = {}
                for at in R.ATTR_OF_CODE.get(c["code"], ()):
                    kc = f"{pfx}{at}"
                    if kc in sub.columns:
                        v = sub[kc].dropna().astype(str)
                        v = v[v != ""]
                        if len(v):
                            kinds[at] = {k: int(x) for k, x in v.value_counts().items()}
                # 양성이 있거나, 보류 갈래(ENV_LOSS·UNKNOWN)·TX_WEAK 가 있는 코드만
                hold_attr = any(k in J.HOLD_KINDS.get(c["code"], ()) or k == "TX_WEAK" for kv in kinds.values() for k in kv)
                if n or n_primary or hold_attr:
                    codes.append({**c, "n": n, "n_primary": n_primary, "kinds": kinds})
            # 시간대별
            hr = sub["vsi_time"].dt.floor("h")
            hd = pd.DataFrame({"hour": hr.to_numpy(), "abn": st == J.ABN, "hold": st == J.HOLD}).groupby("hour").agg(n=("abn", "size"), abn=("abn", "sum"), hold=("hold", "sum")).reset_index()
            hourly = [{"hour": _iso(r.hour), "n": int(r.n), "abn": int(r.abn), "hold": int(r.hold)} for r in hd.itertuples(index=False)]
            kd = pd.DataFrame({"kind": L.kind[m], "abn": st == J.ABN, "hold": st == J.HOLD}).groupby("kind").agg(n=("abn", "size"), abn=("abn", "sum"), hold=("hold", "sum"))
            kinds = [{"key": msgkind.KEYS[k], "label": msgkind.KINDS[k]["label"], "n": int(kd.loc[k, "n"]) if k in kd.index else 0,
                      "abn": int(kd.loc[k, "abn"]) if k in kd.index else 0, "hold": int(kd.loc[k, "hold"]) if k in kd.index else 0} for k in range(len(msgkind.KEYS))]
            # 신호 원인 카드
            posrows = sub[L.has_pos[m]]
            env_val = None
            if len(posrows):
                last = posrows.iloc[-1]
                fld = self._field(src, a, b, "env")
                # 항적 위 환경 잔차 장 값의 중앙값(최대 200 점) — 마지막 위치 하나가 표본 밖이어도 값이 있게
                pick = posrows.iloc[np.linspace(0, len(posrows) - 1, min(200, len(posrows))).astype(int)]
                vals = [signal.field_value_at(fld, float(x), float(y)) for x, y in zip(pick["lat"], pick["lon"])]
                vals = [v for v in vals if v is not None]
                env_val = float(np.median(vals)) if vals else None
                near = self._near_at_minute(L, a, b, mmsi, pd.Timestamp(last["vsi_time"]), float(last["lat"]), float(last["lon"]))
                slot = L.slot_use.get((int(last["site_id"]), pd.Timestamp(last["frame"])) , None) if "frame" in sub.columns else None
            else:
                near, slot = None, None
            others = S[(S["mmsi"] != mmsi) & S["resid_mean"].notna()]["resid_mean"]
            others_med = float(others.median()) if len(others) else None
            tx_rule = bool(("rule_slow_kind" in sub.columns) and (sub["rule_slow_kind"].astype(str) == "TX_WEAK").any())
            cards = signal.ship_cards(sub, env_val, near, slot, others_med, tx_rule)
            # 항적
            tr = sub.loc[L.has_pos[m], ["lat", "lon", "vsi_time"]]
            tr_state = st[L.has_pos[m]]
            n = len(tr)
            if n > MAX_TRACK:
                pick = np.linspace(0, n - 1, MAX_TRACK).astype(int)
                tr, tr_state = tr.iloc[pick], tr_state[pick]
            track = [[round(float(x), 5), round(float(y), 5), _iso(t_), J.STATE_KEY[int(s_)]] for x, y, t_, s_ in zip(tr["lat"], tr["lon"], tr["vsi_time"], tr_state)]
            # 기간 안 마지막 위치 보고의 방향·속력(카드용) — ships_at 과 같은 우선순위
            pos_idx = np.flatnonzero(m & L.has_pos)
            at_last = None
            if len(pos_idx):
                li = int(pos_idx[-1])
                at_last = {"t": _iso(L.t[li]), "lat": round(float(L.lat[li]), 5), "lon": round(float(L.lon[li]), 5), **self._direction(L, pos_idx)}
            return {"mmsi": int(mmsi), "src": src, "t0": _iso(a), "t1": _iso(b), "judge": jd, "summary": summary, "codes": codes,
                    "hourly": hourly, "kinds": kinds, "signal_cards": cards, "track": track, "n_track_rows": int(n), "at_last": at_last}

        return self._memo(key, build)

    def _near_at_minute(self, L: _Loaded, a, b, mmsi: int, t: pd.Timestamp, lat: float, lon: float) -> int:
        """같은 분에 위치 보고가 있는 다른 배 중 반경 3 km 안의 수."""
        m0 = np.datetime64(t.floor("min")); m1 = m0 + np.timedelta64(60, "s")
        m = L.has_pos & (L.t >= m0) & (L.t < m1) & (L.mmsi != mmsi)
        if not m.any():
            return 0
        d = pd.DataFrame({"mmsi": L.mmsi[m], "lat": L.lat[m], "lon": L.lon[m]}).groupby("mmsi").mean()
        la = np.radians(d["lat"].to_numpy()); lo = np.radians(d["lon"].to_numpy())
        p1 = math.radians(lat); l1 = math.radians(lon)
        h = np.sin((la - p1) / 2) ** 2 + math.cos(p1) * np.cos(la) * np.sin((lo - l1) / 2) ** 2
        dk = 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
        return int((dk <= signal.NEAR_KM).sum())

    # ── contours ────────────────────────────────────────────────────────
    def _field(self, src: str, a, b, layer: str) -> dict:
        key = ("field", src, str(a), str(b), layer)

        def build():
            L = self._load(src)
            m = L.has_pos & (L.t >= np.datetime64(a)) & (L.t <= np.datetime64(b))
            lat, lon, mm = L.lat[m], L.lon[m], L.mmsi[m]
            if layer == "margin":
                v = L.df.loc[m, "rssi"].to_numpy(float) - signal.SENS_DBM
            else:
                v = L.df.loc[m, "rssi_resid"].to_numpy(float)
            if m.sum() == 0:
                return {"Z": np.full((2, 2), np.nan), "lats": np.array([0, 1.0]), "lons": np.array([0, 1.0]), "info": {"method": "none", "n_samples": 0}, "samples": None}
            g = signal.grid_spec(lat, lon)
            samples = signal.cell_samples(lat, lon, mm, v, g)
            fld = signal.interpolate_field(samples, g)
            fld["g"] = g
            fld["samples"] = samples
            return fld

        return self._memo(key, build)

    def contours(self, src: str, t0: str | None, t1: str | None, layer: str) -> dict:
        if layer not in signal.LAYERS:
            raise KeyError(f"layer 는 {list(signal.LAYERS)} 중 하나 — 받은 값 '{layer}'")
        L = self._load(src)
        a, b = self._range(L, t0, t1)
        key = ("contours", src, str(a), str(b), layer)

        def build():
            t_ = time.time()
            spec = signal.LAYERS[layer]
            m = L.has_pos & (L.t >= np.datetime64(a)) & (L.t <= np.datetime64(b))
            legend = {"label": spec["label"], "unit": spec["unit"], "desc": spec["desc"], "caveat": signal.CAVEAT,
                      "basis": {"sens_dbm": signal.SENS_DBM, "prot_db": signal.PROT_DB, "env_threshold_db": signal.env_threshold_db()},
                      "design": {"grid_km": signal.GRID_KM, "max_dist_km": signal.MAX_DIST_KM, "min_ships_per_cell": signal.MIN_SHIPS_PER_CELL, "min_samples": signal.MIN_SAMPLES, "neighbors": signal.NEIGHBORS}}
            if spec["kind"] == "contour":
                fld = self._field(src, a, b, layer)
                gj = signal.contour_geojson(fld, tuple(spec["levels"]), layer)
                info = dict(fld["info"])
                if info.get("variogram"):
                    info["variogram"] = {k: v for k, v in info["variogram"].items() if k != "bins"} | {"n_bins": len(info["variogram"].get("bins", []))}
                gj.update({"layer": layer, "levels": list(spec["levels"]), "legend": legend, "info": info,
                           "n_points": int(m.sum()), "n_ships": int(len(np.unique(L.mmsi[m]))), "seconds": round(time.time() - t_, 2)})
                return gj
            lat, lon, mm = L.lat[m], L.lon[m], L.mmsi[m]
            if m.sum() == 0:
                return {"type": "FeatureCollection", "features": [], "layer": layer, "legend": legend, "info": {"n": 0}}
            g = signal.grid_spec(lat, lon)
            ix = np.floor((lon - g["lons"][0]) / g["dlon"]).astype(int)
            iy = np.floor((lat - g["lats"][0]) / g["dlat"]).astype(int)
            if layer == "density":
                minute = L.t[m].astype("datetime64[m]").astype(np.int64)
                d = pd.DataFrame({"ix": ix, "iy": iy, "mmsi": mm, "minute": minute}).drop_duplicates()
                cells = d.groupby(["ix", "iy"]).agg(ship_minutes=("mmsi", "size"), n_ships=("mmsi", "nunique")).reset_index()
                gj = signal.cells_geojson(lat, lon, g, cells, "ship_minutes")
                gj.update({"layer": layer, "legend": legend, "info": {"n_cells": int(len(cells)), "max": int(cells["ship_minutes"].max()), "grid_km": g["km"]}})
                return gj
            sk = L.df.loc[m, "rule_slow_kind"].astype(str).to_numpy() if "rule_slow_kind" in L.df.columns else np.full(int(m.sum()), "")
            d = pd.DataFrame({"ix": ix, "iy": iy, "mmsi": mm, "env": sk == "ENV_LOSS", "hold": np.isin(sk, ["ENV_LOSS", "UNKNOWN"])})
            cells = d.groupby(["ix", "iy"]).agg(n_rows=("env", "size"), n_ships=("mmsi", "nunique"), envloss=("env", "sum"), hold=("hold", "sum")).reset_index()
            cells["envloss_ratio"] = cells["envloss"] / cells["n_rows"]
            cells["hold_ratio"] = cells["hold"] / cells["n_rows"]
            gj = signal.cells_geojson(lat, lon, g, cells, "envloss_ratio")
            gj.update({"layer": layer, "legend": legend, "info": {"n_cells": int(len(cells)), "n_envloss_rows": int(cells["envloss"].sum()), "grid_km": g["km"]}})
            return gj

        return self._memo(key, build)

    # ── 신호 품질 요약 (⑤ 화면) ────────────────────────────────────────────
    def signal_summary(self, src: str, t0: str | None, t1: str | None, flt: Filter) -> dict:
        """해안국 전체의 원인 카드 4장 — 배마다 signal.ship_cards 와 같은 dB 귀속을 벡터로 계산해 합친다.

        배 몫(송신기 x · 해역 환경 e · 혼잡 c · 미상 u)은 ship_cards 의 식 그대로(문서 §3). 전체 몫 % = Σ|부분| ÷ Σ전체.
        '으뜸 원인' = 그 배에서 |부분| 이 가장 큰 몫. ⚑ 수 = 카드 기준(TX_WEAK 룰/2.5 SE · 가림 −4 dB · 슬롯 50 %)에 걸린 배 수.
        """
        L = self._load(src)
        a, b = self._range(L, t0, t1)
        jd = self._judge(L, flt)
        key = ("signal_summary", src, str(a), str(b), jd)

        def build():
            t_ = time.time()
            S = self._ships_table(src, a, b, jd)
            m = (L.t >= np.datetime64(a)) & (L.t <= np.datetime64(b))
            sub = L.df.loc[m, ["mmsi", "site_id", "rssi", "rssi_resid", "snr_resid", "frame"]]
            g = sub.groupby("mmsi").agg(r_mean=("rssi_resid", "mean"), r_std=("rssi_resid", "std"), s_mean=("snr_resid", "mean"),
                                        n=("rssi_resid", "count"), site=("site_id", "last"), frame=("frame", "last"))
            # 해역 환경: 항적 위 환경 잔차 장 값의 중앙값(배마다, 벡터)
            fld = self._field(src, a, b, "env")
            mp = m & L.has_pos
            env_ship = pd.Series(dtype=float)
            if mp.any() and fld.get("Z") is not None and len(fld["lats"]) > 1:
                lats, lons, Z = fld["lats"], fld["lons"], fld["Z"]
                iy = np.rint((L.lat[mp] - lats[0]) / (lats[1] - lats[0])).astype(int)
                ix = np.rint((L.lon[mp] - lons[0]) / (lons[1] - lons[0])).astype(int)
                okc = (iy >= 0) & (iy < Z.shape[0]) & (ix >= 0) & (ix < Z.shape[1])
                val = np.full(len(iy), np.nan)
                val[okc] = Z[iy[okc], ix[okc]]
                env_ship = pd.Series(val, index=L.mmsi[mp]).groupby(level=0).median()
            g["env"] = env_ship.reindex(g.index)
            tx_se = mlall.threshold("txweak_se"); thr = signal.env_threshold_db()
            others_med = float(g["r_mean"].median()) if g["r_mean"].notna().any() else None
            e = np.minimum(0.0, g["env"].to_numpy(float))                       # NaN 이면 NaN
            r = g["r_mean"].to_numpy(float); s_ = g["s_mean"].to_numpy(float)
            x = np.minimum(0.0, r - np.nan_to_num(e, nan=0.0))
            c = np.minimum(0.0, s_ - r)
            T = np.where(np.isfinite(s_), np.minimum(0.0, s_), np.minimum(0.0, r))
            explained = np.nan_to_num(e, nan=0.0) + np.nan_to_num(x, nan=0.0) + np.nan_to_num(c, nan=0.0)
            u = np.minimum(0.0, T - explained)
            parts = {"tx": x, "env": e, "cong": c, "unknown": u}
            absum = {k: float(np.nansum(np.abs(v))) for k, v in parts.items()}
            tot = sum(absum.values())
            share = {k: (absum[k] / tot if tot > 0 else 0.0) for k in parts}
            P = np.vstack([np.nan_to_num(np.abs(v), nan=0.0) for v in parts.values()])   # 4 × 배
            has_any = P.sum(axis=0) > 0
            dom = np.where(has_any, P.argmax(axis=0), -1)
            keys = list(parts)
            n_dom = {k: int((dom == i).sum()) for i, k in enumerate(keys)}
            # ⚑ 수
            r_se = g["r_std"].to_numpy(float) / np.sqrt(np.maximum(1, g["n"].to_numpy(float)))
            tx_rule = pd.Series(False, index=g.index)
            if "rule_slow_kind" in L.df.columns:
                sk = L.df.loc[m, ["mmsi", "rule_slow_kind"]]
                tx_rule = (sk["rule_slow_kind"].astype(str) == "TX_WEAK").groupby(sk["mmsi"]).any().reindex(g.index).fillna(False)
            vs = r - (others_med if others_med is not None else np.nan)
            tx_flag = tx_rule.to_numpy(bool) | (np.isfinite(vs) & np.isfinite(r_se) & (vs <= -tx_se * r_se) & (g["n"].to_numpy() >= 25))
            env_flag = np.isfinite(e) & (g["env"].to_numpy(float) <= -thr)
            slot = np.array([L.slot_use.get((int(si), pd.Timestamp(fr)), np.nan) if pd.notna(fr) else np.nan for si, fr in zip(g["site"], g["frame"])], float)
            cong_flag = np.isfinite(slot) & (slot >= 0.5)
            lv = S["level"].fillna("none").value_counts()
            mg = S["margin_db"].to_numpy(float)
            texts = {
                "tx": f"배 고유로 약하게 들리는 몫 — 같은 자리 다른 배보다 약한 정도(기준 {tx_se:g} SE 또는 룰 TX_WEAK)",
                "env": f"그 자리가 원래 낮게 들리는 몫 — 환경 잔차 등고선 값(가림 의심 기준 −{thr:g} dB)",
                "cong": "세기로 설명 안 되는 SNR 손실 — 주변 배·슬롯 사용(⚑ 슬롯 50 % 이상)",
                "unknown": "위 셋으로 설명되지 않는 나머지(환경 값 없는 배 포함)",
            }
            labels = {"tx": "송신기 약함", "env": "해역 환경(가림)", "cong": "혼잡·간섭", "unknown": "미상"}
            flags = {"tx": int(tx_flag.sum()), "env": int(env_flag.sum()), "cong": int(cong_flag.sum()), "unknown": 0}
            cards = [{"key": k, "label": labels[k], "share": round(share[k], 4), "db_sum": round(-absum[k], 1), "n_dominant": n_dom[k],
                      "n_flag": flags[k], "text": texts[k]} for k in keys]
            return {"src": src, "t0": _iso(a), "t1": _iso(b), "judge": jd, "n_ships": int(len(g)), "n_rows": int(m.sum()),
                    "levels": {"good": int(lv.get("good", 0)), "fair": int(lv.get("fair", 0)), "bad": int(lv.get("bad", 0)), "none": int(lv.get("none", 0))},
                    "margin_med_db": _clean(np.nanmedian(mg)) if np.isfinite(mg).any() else None,
                    "rows_below_sens": int((sub["rssi"].to_numpy(float) < signal.SENS_DBM).sum()),
                    "n_env_known": int(np.isfinite(e).sum()), "n_no_part": int((~has_any).sum()),
                    "cards": cards, "field": {"method": fld["info"].get("method"), "n_samples": fld["info"].get("n_samples")},
                    "basis": {"sens_dbm": signal.SENS_DBM, "prot_db": signal.PROT_DB, "env_threshold_db": thr, "tx_se": tx_se, "near_km": signal.NEAR_KM,
                              "slot_flag": 0.5}, "seconds": round(time.time() - t_, 2)}

        return self._memo(key, build)

    # ── 실시간 자리 ──────────────────────────────────────────────────────
    def changes_since(self, src: str, t: str) -> Delta | None:
        """ParquetProvider 는 변화가 없다 — LiveProvider 가 구현한다(providers/live.py)."""
        return None
