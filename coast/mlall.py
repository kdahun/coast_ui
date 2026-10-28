"""ml_all 의 판정 뜻을 **읽어 들이는** 다리 — 복사 금지, import 만.

위협 1~5·영향 H/M/L 매핑은 `AISINT_ML_ALL_ROOT/src/aisint/risk/threats.py`, 코드 목록·전역 우선순위
(`PRIMARY_ORDER`)·문턱(`THRESHOLDS`)·속성 열(`ATTR_OF_CODE`)은 `engines/threat/rules.py` 에서 온다.
그쪽 `src` 를 sys.path 에 넣고 import 한다. ml_all 의 파일은 어느 것도 고치지 않는다.

코드 한 줄 설명은 ml_all 에 `code_info` 문구표가 따로 없어(console/risk.py 의 code_info 는 번호·등급만 준다)
`rules.py` 모듈 docstring 의 15코드 표에서 읽는다 — 그 표가 바뀌면 여기 설명도 같이 바뀐다.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

from . import settings


class MlAllMissing(RuntimeError):
    pass


def src_dir() -> Path:
    root = settings.ml_all_root()
    src = root / "src"
    if not (src / "aisint" / "risk" / "threats.py").exists():
        raise MlAllMissing(f"ml_all 저장소를 찾지 못했습니다 — AISINT_ML_ALL_ROOT={root} (.env.local 에서 고칠 것)")
    return src


def output_dir() -> Path:
    return settings.ml_all_root() / "output" / "datagen"


def sea_mask_path() -> Path:
    return settings.ml_all_root() / "config" / "sea_mask.json"


@lru_cache(maxsize=1)
def modules():
    """(threats, rules) 모듈. 한 번만 import."""
    s = str(src_dir())
    if s not in sys.path:
        sys.path.insert(0, s)
    from aisint.risk import threats            # noqa: WPS433 — ml_all 의 모듈
    from aisint.engines.threat import rules    # noqa: WPS433
    return threats, rules


def threats():
    return modules()[0]


def rules():
    return modules()[1]


@lru_cache(maxsize=1)
def code_descriptions() -> dict[str, str]:
    """rules.py docstring 의 `    CODE   설명` 줄 → {code: 설명 한 줄}."""
    doc = rules().__doc__ or ""
    out: dict[str, str] = {}
    for line in doc.splitlines():
        m = re.match(r"^\s{4}([A-Z][A-Z_]+)\s{2,}(\S.*)$", line)
        if m and m.group(1) in rules().CODES and m.group(1) not in out:
            out[m.group(1)] = m.group(2).strip()
    return out


ACTION_OF_IMPACT = {"H": "즉시 확인", "M": "확인 필요", "L": "참고"}
IMPACT_LABEL = {"H": "높음", "M": "중간", "L": "낮음"}


@lru_cache(maxsize=1)
def threat_table() -> list[dict]:
    """위협 1~5 — 화면 카드 순서(rank). codes 는 ml_all 의 15코드 중 그 위협 것."""
    TH, R = modules()
    out = []
    for t in TH.THREATS:
        out.append({"rank": t.rank, "key": t.key, "title": t.title, "impact": t.impact,
                    "impact_label": IMPACT_LABEL[t.impact], "action": ACTION_OF_IMPACT[t.impact],
                    "implemented": bool(t.implemented), "codes": [c for c in R.CODES if c in t.codes],
                    "note": t.note})
    return out


@lru_cache(maxsize=1)
def code_table() -> list[dict]:
    TH, R = modules()
    desc = code_descriptions()
    out = []
    for c in R.CODES:
        t = TH.threat_of(c)
        out.append({"code": c, "threat": t.rank if t else None, "threat_title": t.title if t else None,
                    "impact": t.impact if t else None, "action": ACTION_OF_IMPACT.get(t.impact, "") if t else "",
                    "desc": desc.get(c, ""), "attrs": list(R.ATTR_OF_CODE.get(c, ())),
                    "primary_rank": R.PRIMARY_ORDER.index(c), "provisional": c in TH.PROVISIONAL_CODES,
                    "subthreat": TH.subthreat_of(c)})
    return out


def threshold(name: str) -> float:
    return float(rules().THRESHOLDS[name])
