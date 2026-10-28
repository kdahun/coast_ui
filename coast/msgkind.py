"""메시지 종류 — 토폴로지 2층. AIS 위치 보고 / AIS 정적·기타 / ASM / VDE.

ITU-R M.1371 메시지 번호 기준.
  pos     위치 보고          1·2·3(Class A) · 18·19(Class B) · 27(장거리)
  static  정적·기타          4(기지국 시각) · 5·24(정적) · 20·22·23(채널·할당) · 7·9~17·21 등 나머지 AIS
  asm     응용 특정(ASM)     6·8(바이너리) · 25·26(단일 슬롯·다중 슬롯 바이너리)
  vde     VDE                데이터에 없음 — 0 으로 자리만(요구 ⑤)
"""
from __future__ import annotations

import numpy as np

KINDS = (
    {"key": "pos", "label": "AIS 위치 보고", "msg": (1, 2, 3, 18, 19, 27)},
    {"key": "static", "label": "AIS 정적·기타", "msg": ()},          # 나머지 AIS 전부
    {"key": "asm", "label": "ASM", "msg": (6, 8, 25, 26)},
    {"key": "vde", "label": "VDE", "msg": ()},                        # 자리만
)
KEYS = tuple(k["key"] for k in KINDS)
POS, STATIC, ASM, VDE = 0, 1, 2, 3


def kind_index(msg_type: np.ndarray) -> np.ndarray:
    """msg_type 배열 → 종류 번호(int8). 모르는 번호(결측 포함)는 static."""
    m = np.nan_to_num(np.asarray(msg_type, dtype=float), nan=-1).astype(int)
    out = np.full(len(m), STATIC, np.int8)
    out[np.isin(m, KINDS[POS]["msg"])] = POS
    out[np.isin(m, KINDS[ASM]["msg"])] = ASM
    return out


def table() -> list[dict]:
    return [{"key": k["key"], "label": k["label"], "msg": list(k["msg"]),
             "note": "나머지 AIS 전부" if k["key"] == "static" else ("데이터에 없음 — 0 자리" if k["key"] == "vde" else "")}
            for k in KINDS]
