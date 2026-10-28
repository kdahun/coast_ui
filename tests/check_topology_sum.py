"""(b) 토폴로지 마디 합 = 전체 — 나무(해안국 → 종류 → 상태)·생키 링크·표가 모두 같은 전체 행 수로 닫히는지.

    .\\venv\\Scripts\\python.exe tests\\check_topology_sum.py [http://127.0.0.1:8800]
"""
from __future__ import annotations

import sys

from _common import PERIODS, Check, api


def main() -> int:
    c = Check("topology_sum")
    for src, periods in PERIODS.items():
        for t0, t1 in periods:
            for judge in (["rule", "xgb"] if src == "real" else ["rule", "truth"]):
                w = api("/api/window", src=src, t0=t0, t1=t1, judge=judge)
                topo = w["topology"]; tot = topo["total"]; tag = f"{src} {judge} {t0 or '전체'}"
                c.eq(f"{tag} total = window 행 수", tot["n_rows"], w["n_rows"])
                c.eq(f"{tag} ok+abn+hold = total", tot["ok"] + tot["abn"] + tot["hold"], tot["n_rows"])
                # 나무
                c.eq(f"{tag} 해안국 합", sum(s["n_rows"] for s in topo["tree"]), tot["n_rows"])
                for s in topo["tree"]:
                    c.eq(f"{tag} {s['name']} 종류 합", sum(k["n_rows"] for k in s["children"]), s["n_rows"])
                    c.ok(f"{tag} {s['name']} 종류 4개(VDE 자리 포함)", [k["kind"] for k in s["children"]] == ["pos", "static", "asm", "vde"])
                    for k in s["children"]:
                        c.eq(f"{tag} {s['name']}/{k['name']} 상태 합", sum(st["n_rows"] for st in k["children"]), k["n_rows"])
                        for st in k["children"]:
                            c.ok(f"{tag} {k['name']}/{st['name']} 배 수 ≤ 행 수", st["n_ships"] <= max(st["n_rows"], 0) or st["n_rows"] == 0)
                            c.ok(f"{tag} {k['name']}/{st['name']} 비율", abs(st["ratio"] - (st["n_rows"] / k["n_rows"] if k["n_rows"] else 0)) < 1e-9)
                            if st["ships"]:
                                c.ok(f"{tag} {k['name']}/{st['name']} 상위 배 정렬", all(a["n_rows"] >= b["n_rows"] for a, b in zip(st["ships"], st["ships"][1:])))
                # 생키 — 1층 링크 합 = 2층 링크 합 = total
                sk = topo["sankey"]; nodes = sk["nodes"]
                l1 = [l for l in sk["links"] if nodes[l["source"]]["type"] == "site"]
                l2 = [l for l in sk["links"] if nodes[l["source"]]["type"] == "kind"]
                c.eq(f"{tag} 생키 1층 합", sum(l["value"] for l in l1), tot["n_rows"])
                c.eq(f"{tag} 생키 2층 합", sum(l["value"] for l in l2), tot["n_rows"])
                abn_links = sum(l["value"] for l in l2 if nodes[l["target"]]["type"] == "threat")
                c.eq(f"{tag} 생키 위협 합 = 비정상", abn_links, tot["abn"])
                c.eq(f"{tag} 생키 보류", sum(l["value"] for l in l2 if nodes[l["target"]]["type"] == "hold"), tot["hold"])
                c.ok(f"{tag} 생키 위협 1~5 마디 있음", sorted(n["threat"] for n in nodes if n["type"] == "threat") == [1, 2, 3, 4, 5])
                c.ok(f"{tag} 생키 VDE 자리", any(n["type"] == "kind" and n["kind"] == "vde" for n in nodes))
                # 위협 카드 행 수 합 = 생키 위협 합
                c.eq(f"{tag} 카드 비정상 행 합", sum(x["n_rows"] for x in w["threat_cards"] if isinstance(x["rank"], int)), tot["abn"])
                # 표
                tb = topo["tables"]
                c.eq(f"{tag} 표 해안국 합", sum(r["n_rows"] for r in tb["by_site"]), tot["n_rows"])
                c.eq(f"{tag} 표 종류 합", sum(r["n_rows"] for r in tb["by_kind"]), tot["n_rows"])
                c.ok(f"{tag} 표 VDE 0", next(r for r in tb["by_kind"] if r["kind"] == "vde")["n_rows"] == 0)
                c.ok(f"{tag} 상위 20 ≤ 20", len(tb["top_ships"]) <= 20)
                # 선박 목록의 종류별 합 = 배 행 수, 전체 합 = total
                ships = w["ships"]
                c.eq(f"{tag} 목록 행 합", sum(s["n_rows"] for s in ships), tot["n_rows"])
                c.ok(f"{tag} 배마다 종류 합 = 행", all(sum(v[0] for v in s["kinds"].values()) == s["n_rows"] for s in ships))
                c.eq(f"{tag} 목록 비정상 행 합", sum(s["n_abn"] for s in ships), tot["abn"])
    return c.done()


if __name__ == "__main__":
    sys.exit(main())
