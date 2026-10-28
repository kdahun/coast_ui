"""'비정상' 의 정의 — **한 곳**. 지도·목록·카드·토폴로지·검사 스크립트가 전부 여기만 본다.

행 단위 (judge = rule / xgb / knn / truth)
  · 비정상  = 그 판정기가 코드를 붙인 행. 룰은 `code_primary` 열 그대로(ml_all 이 PRIMARY_ORDER 로 정한 대표 코드).
             XGB G·kNN G·정답은 `xgb_G__*`/`knn_G__*`/`y_truth__*` 양성 코드 중 **같은 PRIMARY_ORDER 의 첫 코드**.
  · 보류    = 비정상이 아니면서 (a) REPORT_RATE_SLOW 의 환경성 갈래(slow_kind ∈ ENV_LOSS·UNKNOWN) 이거나
             (b) kNN 판정기에서 Unknown 인 행. 위반이 아니라 "판정을 미룬 것" — 별도 색(분홍).
             갈래는 룰의 `rule_slow_kind`(정답 판정기는 `truth_slow_kind`)를 쓴다 — ML 은 코드만 예측하므로
             갈래는 룰 것을 빌린다(ml_all console/risk.py 와 같은 규칙).
  · 정상    = 나머지(판정 없음).

배 단위 (보는 기간 안)
  · 비정상 1건 이상이면 비정상 배. 배의 위협·영향 = 그 배 비정상 코드들 중 PRIMARY_ORDER 가장 앞 코드의 것
    (= 영향 H → M → L, 같은 등급 안은 결정 문서 §7 순서). 대표 코드도 그것.
  · 비정상이 없고 보류 1건 이상이면 보류 배. 둘 다 없으면 정상 배.
  · 비정상 비율(행) = 비정상 행 ÷ 그 배 행.

생성 벌의 "정답 기준"도 같은 식이다(judge='truth'). 관리자 화면 기본은 판정 기준(룰).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import mlall

JUDGES = {"rule": "룰(위협 엔진)", "xgb": "XGBoost G", "knn": "kNN G", "truth": "정답지(생성 벌)"}
ML_VERSION = "G"                                 # 판정기 선택 — 1차는 G 고정(설계값)
HOLD_KINDS = {"REPORT_RATE_SLOW": ("ENV_LOSS", "UNKNOWN")}     # 보류 갈래 (지시서 §1-5)

# 행 상태 코드 (int8) — 집계가 빠르게 되도록 숫자로
OK, HOLD, ABN = 0, 1, 2
STATE_LABEL = {OK: "정상", HOLD: "보류", ABN: "비정상"}
STATE_KEY = {OK: "ok", HOLD: "hold", ABN: "abn"}
NO_CODE = -1


@dataclass(frozen=True)
class CodeBook:
    """코드 ↔ 번호. 번호 = PRIMARY_ORDER 순서(0 이 가장 앞 = 가장 센 코드)."""
    order: tuple[str, ...]
    threat_rank: tuple[int, ...]
    impact: tuple[str, ...]

    def index(self, code: str) -> int:
        return self.order.index(code)

    @property
    def n(self) -> int:
        return len(self.order)


def codebook() -> CodeBook:
    TH, R = mlall.modules()
    order = tuple(R.PRIMARY_ORDER)
    ranks, imps = [], []
    for c in order:
        t = TH.threat_of(c)
        ranks.append(t.rank if t else 0)
        imps.append(t.impact if t else "L")
    return CodeBook(order, tuple(ranks), tuple(imps))


def flag_columns(judge: str, cb: CodeBook) -> dict[str, str]:
    if judge == "rule":
        return {c: f"y_rule__{c}" for c in cb.order}
    if judge == "truth":
        return {c: f"y_truth__{c}" for c in cb.order}
    if judge in ("xgb", "knn"):
        return {c: f"{judge}_{ML_VERSION}__{c}" for c in cb.order}
    raise ValueError(f"judge 는 {list(JUDGES)} 중 하나 — 받은 값 '{judge}'")


def judge_available(df: pd.DataFrame, judge: str, cb: CodeBook) -> bool:
    try:
        cols = flag_columns(judge, cb)
    except ValueError:
        return False
    return all(c in df.columns for c in cols.values())


def row_state(df: pd.DataFrame, judge: str, cb: CodeBook) -> tuple[np.ndarray, np.ndarray]:
    """행마다 (상태 OK/HOLD/ABN, 대표 코드 번호 또는 -1). 한 번 계산해 캐시해 둔다."""
    cols = flag_columns(judge, cb)
    n = len(df)
    code_idx = np.full(n, NO_CODE, np.int16)
    if judge == "rule" and "code_primary" in df.columns:
        # ml_all 이 정한 대표 코드 그대로 — 번호표로 바꾼다
        cp = df["code_primary"].astype("object").to_numpy()
        lut = {c: i for i, c in enumerate(cb.order)}
        code_idx = np.array([lut.get(v, NO_CODE) if isinstance(v, str) else NO_CODE for v in cp], np.int16)
    else:
        F = df[[cols[c] for c in cb.order]].to_numpy()
        F = np.nan_to_num(F.astype(np.float32), nan=0.0) > 0
        # 첫 양성 코드(= PRIMARY_ORDER 가장 앞) — argmax 는 첫 True 를 준다
        anyv = F.any(axis=1)
        first = F.argmax(axis=1)
        code_idx = np.where(anyv, first, NO_CODE).astype(np.int16)
    state = np.where(code_idx >= 0, ABN, OK).astype(np.int8)
    # 보류 — 비정상이 아닌 행만
    hold = np.zeros(n, bool)
    kind_prefix = "truth_" if judge == "truth" else "rule_"
    for code, kinds in HOLD_KINDS.items():
        attrs = mlall.rules().ATTR_OF_CODE.get(code, ())
        for a in attrs:
            col = f"{kind_prefix}{a}"
            if col in df.columns:
                v = df[col].astype("object").to_numpy()
                hold |= np.isin(v, list(kinds))
    if judge == "knn":
        uc = f"knn_unknown_{ML_VERSION}"
        if uc in df.columns:
            hold |= df[uc].fillna(False).to_numpy(bool)
    state[(state == OK) & hold] = HOLD
    return state, code_idx


def ship_summary(mmsi: np.ndarray, state: np.ndarray, code_idx: np.ndarray, cb: CodeBook) -> pd.DataFrame:
    """배 단위 — n_rows·n_abn·n_hold·상태·대표 코드·위협·영향·비정상 비율."""
    d = pd.DataFrame({"mmsi": mmsi, "abn": (state == ABN).astype(np.int32), "hold": (state == HOLD).astype(np.int32),
                      "code": np.where(code_idx >= 0, code_idx, 10_000).astype(np.int32)})
    g = d.groupby("mmsi", sort=True).agg(n_rows=("abn", "size"), n_abn=("abn", "sum"), n_hold=("hold", "sum"),
                                         code_min=("code", "min")).reset_index()
    g["state"] = np.where(g["n_abn"] > 0, ABN, np.where(g["n_hold"] > 0, HOLD, OK)).astype(np.int8)
    has = g["code_min"] < 10_000
    g["code"] = [cb.order[i] if ok else None for i, ok in zip(g["code_min"], has)]
    g["threat"] = [cb.threat_rank[i] if ok else None for i, ok in zip(g["code_min"], has)]
    g["impact"] = [cb.impact[i] if ok else None for i, ok in zip(g["code_min"], has)]
    g["abn_ratio"] = (g["n_abn"] / g["n_rows"]).astype(float)
    return g.drop(columns=["code_min"])
