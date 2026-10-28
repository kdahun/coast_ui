"""(a) API 응답의 위협 등급 수·비정상 비율 = parquet 에서 직접 센 값 (실해역·ds_015, 전체 + 부분 기간 1개씩).

    .\\venv\\Scripts\\python.exe tests\\check_counts.py [http://127.0.0.1:8800]

직접 세기(룰 판정기): 비정상 행 = code_primary 가 있는 행. 배의 위협 = 그 배 비정상 코드 중 PRIMARY_ORDER 가장 앞 코드의 위협
(ml_all threats.threat_of). 보류 행 = code_primary 없음 & rule_slow_kind ∈ {ENV_LOSS, UNKNOWN}. coast.judge 를 거치지 않는다.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from _common import PERIODS, Check, api, mlall, period_mask, read_parquet


def main() -> int:
    c = Check("counts")
    TH, R = mlall.modules()
    prio = {code: i for i, code in enumerate(R.PRIMARY_ORDER)}
    rank_of = {code: TH.threat_of(code).rank for code in R.CODES}
    for src, periods in PERIODS.items():
        df = read_parquet(src, ["mmsi", "vsi_time", "site_id", "code_primary", "rule_slow_kind"])
        for t0, t1 in periods:
            w = api("/api/window", src=src, t0=t0, t1=t1, judge="rule")
            m = period_mask(df, t0, t1)
            sub = df[m]
            cp = sub["code_primary"].astype("object")
            abn = cp.notna() & (cp != "")
            hold = ~abn & sub["rule_slow_kind"].astype("object").isin(["ENV_LOSS", "UNKNOWN"])
            tag = f"{src} {t0 or '전체'}~{t1 or ''}"
            c.eq(f"{tag} 행 수", w["n_rows"], int(len(sub)))
            c.eq(f"{tag} 배 수", w["n_ships"], int(sub["mmsi"].nunique()))
            # 행의 위협
            rank_row = cp.map(lambda v: rank_of.get(v, 0) if isinstance(v, str) else 0).to_numpy()
            # 배의 위협 — 가장 앞 코드
            d = pd.DataFrame({"mmsi": sub["mmsi"].to_numpy(), "p": cp.map(lambda v: prio.get(v, 10_000) if isinstance(v, str) else 10_000).to_numpy()})
            pmin = d.groupby("mmsi")["p"].min()
            ship_rank = pmin[pmin < 10_000].map(lambda i: rank_of[R.PRIMARY_ORDER[i]])
            cards = {str(x["rank"]): x for x in w["threat_cards"]}
            for r in range(1, 6):
                c.eq(f"{tag} 위협 {r} 배 수", cards[str(r)]["n_ships"], int((ship_rank == r).sum()))
                c.eq(f"{tag} 위협 {r} 비정상 행 수", cards[str(r)]["n_rows"], int((rank_row == r).sum()))
            c.eq(f"{tag} 보류 행 수", cards["hold"]["n_rows"], int(hold.sum()))
            hold_ships = set(d.loc[hold.to_numpy(), "mmsi"]) - set(ship_rank.index)
            c.eq(f"{tag} 보류 배 수", cards["hold"]["n_ships"], len(hold_ships))
            c.eq(f"{tag} 정상 배 수", cards["ok"]["n_ships"], int(sub["mmsi"].nunique()) - len(ship_rank) - len(hold_ships))
            # 해안국 카드 비정상 비율(행·배)
            for sc in w["site_cards"]:
                ms = (sub["site_id"] == sc["site"]).to_numpy()
                c.eq(f"{tag} 수신소 {sc['site']} 비정상 행 비율", sc["abn_row_ratio"], float(abn.to_numpy()[ms].mean()), tol=1e-9)
                ships_abn = d.loc[ms & abn.to_numpy(), "mmsi"].nunique()
                c.eq(f"{tag} 수신소 {sc['site']} 비정상 배 비율", sc["abn_ship_ratio"], ships_abn / sub.loc[ms, "mmsi"].nunique(), tol=1e-9)
            # 선박 목록: 배마다 비정상 비율(행) 표본 50척
            ships = {s["mmsi"]: s for s in w["ships"]}
            per_ship = pd.DataFrame({"mmsi": sub["mmsi"].to_numpy(), "abn": abn.to_numpy()}).groupby("mmsi")["abn"].agg(["mean", "size"])
            for mm, row in per_ship.sample(min(50, len(per_ship)), random_state=0).iterrows():
                c.eq(f"{tag} 배 {mm} 비정상 비율", ships[int(mm)]["abn_ratio"], float(row["mean"]), tol=1e-4)
                c.eq(f"{tag} 배 {mm} 행 수", ships[int(mm)]["n_rows"], int(row["size"]))
            # 배 위협 표본
            for mm in list(ship_rank.index[:30]):
                c.eq(f"{tag} 배 {mm} 위협", ships[int(mm)]["threat"], int(ship_rank[mm]))
        # 정답 판정기(생성 벌): y_truth__* 로 같은 식
        if src == "ds015":
            cols = [f"y_truth__{code}" for code in R.CODES]
            dt = read_parquet(src, ["mmsi", "vsi_time"] + cols)
            w = api("/api/window", src=src, judge="truth")
            F = dt[cols].to_numpy() > 0
            anyv = F.any(axis=1)
            c.eq("ds015 정답 비정상 행 수", sum(x["n_rows"] for x in w["threat_cards"] if isinstance(x["rank"], int)), int(anyv.sum()))
            # 행의 대표 코드 = 양성 코드 중 PRIMARY_ORDER 가장 앞 (= 우선순위 번호 최소)
            prio_arr = np.array([prio[code] for code in R.CODES])
            pmin_row = np.where(F, prio_arr[None, :], 10_000).min(axis=1)
            d = pd.DataFrame({"mmsi": dt["mmsi"].to_numpy(), "p": pmin_row})
            pmin = d.groupby("mmsi")["p"].min()
            ship_rank = pmin[pmin < 10_000].map(lambda i: rank_of[R.PRIMARY_ORDER[i]])
            cards = {str(x["rank"]): x for x in w["threat_cards"]}
            for r in range(1, 6):
                c.eq(f"ds015 정답 위협 {r} 배 수", cards[str(r)]["n_ships"], int((ship_rank == r).sum()))
    return c.done()


if __name__ == "__main__":
    sys.exit(main())
