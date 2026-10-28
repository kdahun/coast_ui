"""(f) 2차 화면 검사 — 헤드리스 Chrome 으로 5 화면 + 배 상세 1개를 열어 콘솔/페이지 오류 0, 화면마다 고유 요소,
상황판 문장의 숫자 = /api/window, ④ 막대 합 = 전체 를 본다. 1280 폭에서 가로 스크롤이 없는지도 본다.

    .\\venv\\Scripts\\python.exe tests\\check_pages.py [http://127.0.0.1:8801]

서버가 떠 있어야 한다. 설치된 Chrome(없으면 Edge)을 playwright channel 로 쓴다 — 브라우저 내려받기 없음.
"""
from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

from _common import Check, api, base


def launch(p):
    for ch in ("chrome", "msedge", None):
        try:
            return p.chromium.launch(channel=ch, headless=True) if ch else p.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {ch or 'chromium'} 실행 실패: {str(e).splitlines()[0]}")
    raise SystemExit("브라우저를 못 띄움")


def main() -> int:
    c = Check("pages")
    B = base()
    w = api("/api/window", src="real", judge="rule")
    counts = {"H": 0, "M": 0, "L": 0, "hold": 0, "ok": 0}
    for t in w["threat_cards"]:
        counts[t["impact"] if isinstance(t["rank"], int) else t["rank"]] += t["n_ships"]
    with sync_playwright() as p:
        browser = launch(p)
        for width, height in ((1440, 900), (1280, 800)):
            errors: list[str] = []
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            tag = f"{width}x{height}"
            no_hscroll = "() => document.documentElement.scrollWidth <= window.innerWidth && [...document.querySelectorAll('.page.active')].every(e => e.scrollWidth <= e.clientWidth + 1)"
            # ① 상황판
            page.goto(B + "/#/overview?src=real", wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('#ovTiles .tile').length === 4 && window.coast && window.coast.shipSrc.getFeatures().length > 0", timeout=90000)
            page.wait_for_timeout(800)
            c.ok(f"{tag} ① 타일 4장", page.locator("#ovTiles .tile").count() == 4)
            c.ok(f"{tag} ① 위협 카드 5장", page.locator("#threatCards .card").count() == 5)
            c.ok(f"{tag} ① 작은 지도", page.locator("#map-mini .ol-viewport").count() == 1)
            c.ok(f"{tag} ① 봐야 할 배 5척", page.locator("#ovTop tbody tr[data-mmsi]").count() == 5)
            sent = page.locator("#ovSentence").inner_text()
            nums = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+)척", sent)]
            c.ok(f"{tag} ① 문장 숫자 = /api/window", nums[:5] == [w["n_ships"], counts["H"], counts["M"], counts["L"], counts["hold"]], f"{nums[:5]} vs {[w['n_ships'], counts['H'], counts['M'], counts['L'], counts['hold']]}")
            tiles = [int(x.replace(",", "")) for x in page.locator("#ovTiles .tile .n").all_inner_texts() for x in [re.sub(r"\s*척.*", "", x)]]
            c.ok(f"{tag} ① 타일 숫자 = /api/window", tiles == [counts["H"], counts["M"], counts["L"], counts["hold"]], f"{tiles}")
            c.ok(f"{tag} ① 가로 스크롤 없음", page.evaluate(no_hscroll))
            # ② 지도 — 배 아이콘 · 툴바 4 · 시점 띠 · 카드
            page.evaluate("() => window.coast.navigate('map')")
            page.wait_for_function("document.querySelector('#page-map').classList.contains('active') && document.querySelector('#map-main .ol-viewport')", timeout=30000)
            page.wait_for_timeout(800)
            c.ok(f"{tag} ② 지도", page.locator("#map-main .ol-viewport").count() == 1)
            c.ok(f"{tag} ② 툴바 아이콘 4", page.locator("#toolbar .tb").count() == 4)
            c.ok(f"{tag} ② 시점 띠", page.locator("#timebar #tslider").count() == 1 and page.locator("#tPlay").count() == 1)
            n_feat = page.evaluate("() => window.coast.shipSrc.getFeatures().length")
            c.ok(f"{tag} ② 배 수 = ships_at 필터 전", n_feat == len(api("/api/ships_at", src="real", judge="rule")["ships"]), f"{n_feat}")
            # 원형 점 0척: 모든 배가 아이콘 스타일(Icon) — 출처 none 도 아이콘
            circ = page.evaluate("() => { const fs = window.coast.shipSrc.getFeatures(); const L = window.coast.maps.main.getLayers().getArray().find(l => l.getSource && l.getSource() === window.coast.shipSrc); let circ = 0, none = 0; for (const f of fs) { const st = L.getStyleFunction()(f, 1); const last = st[st.length - 1]; if (!(last.getImage() instanceof ol.style.Icon)) circ++; if (CoastRotation.shipCourse(f.get('ship')).source === 'none') none++; } return [circ, none, fs.length]; }")
            c.ok(f"{tag} ② 원형 점 0척 (아이콘 아닌 배)", circ[0] == 0, f"{circ}")
            c.ok(f"{tag} ② 방향 미상 배도 아이콘으로 그림", circ[1] >= 0)
            # 패널 하나만 열린다
            page.click("#toolbar .tb[data-panel=filter]"); page.wait_for_timeout(200)
            c.ok(f"{tag} ② 필터 패널 열림", page.locator("#panel-filter").is_visible())
            page.click("#toolbar .tb[data-panel=legend]"); page.wait_for_timeout(200)
            c.ok(f"{tag} ② 패널 하나만", page.locator("#panel-legend").is_visible() and not page.locator("#panel-filter").is_visible())
            c.ok(f"{tag} ② 범례에 방향 미상", "방향 미상" in page.locator("#legend").inner_text())
            page.click("#toolbar .tb[data-panel=legend]")
            # 배 카드 — 위치 보고 있는 비정상 배 하나 클릭(프로그램으로)
            mm = next(s["mmsi"] for s in sorted(w["ships"], key=lambda s: (s["impact"] != "H", -s["abn_ratio"])) if s["kinds"]["pos"][0] > 0 and s["state"] == "abn")
            page.evaluate(f"() => window.coast.S.detail = null")
            page.evaluate(f"() => openCard({mm}, true)")
            page.wait_for_function("document.querySelector('#shipCard .kv') !== null", timeout=60000)
            page.wait_for_timeout(500)
            card = page.locator("#shipCard").inner_text()
            c.ok(f"{tag} ② 카드 내용(등급·코드·속력/방향·마지막 보고·신호 원인·자세히)", all(k in card for k in ("등급", "대표 코드", "속력 / 방향", "마지막 보고", "송신기 약함", "자세히")), card[:120])
            c.ok(f"{tag} ② 카드 MMSI", str(mm) in card)
            c.ok(f"{tag} ② 가로 스크롤 없음", page.evaluate(no_hscroll))
            # 시점 ◀ ▶ · 재생(1초마다 1분)
            t_end = page.evaluate("() => window.coast.F.t")
            page.click("#tPrev"); page.wait_for_timeout(400)
            c.ok(f"{tag} ② ◀ 1분 전", page.evaluate("() => window.coast.F.t") < t_end)
            page.click("#tPrev"); page.click("#tPrev"); page.wait_for_timeout(300)
            t_before = page.evaluate("() => window.coast.F.t")
            page.click("#tPlay"); page.wait_for_timeout(2300)
            t_after = page.evaluate("() => window.coast.F.t"); page.click("#tPlay")
            c.ok(f"{tag} ② 재생: 2초 뒤 시점이 1분 이상 앞으로", t_after > t_before and page.evaluate("() => window.coast.S.playing === null"), f"{t_before} → {t_after}")
            c.ok(f"{tag} ② 해시에 시점 실림", "t=" in page.url)
            page.evaluate("() => setT(window.coast.F.t1)")
            # ③ 목록
            page.evaluate("() => window.coast.navigate('ships')")
            page.wait_for_function("document.querySelector('#page-ships').classList.contains('active') && document.querySelectorAll('#shipTable tbody tr').length > 0", timeout=30000)
            c.ok(f"{tag} ③ 표 열 8", page.locator("#shipTable thead th").count() == 8)
            c.ok(f"{tag} ③ 행 수 = 배 수", page.locator("#shipTable tbody tr").count() == min(1500, w["n_ships"]))
            c.ok(f"{tag} ③ 영향 배지에 글자", "즉시 확인" in page.locator("#shipTable tbody tr").first.inner_text())
            page.click("#shipTable thead th[data-key=mmsi]"); page.wait_for_timeout(200)
            first = page.locator("#shipTable tbody tr td").first.inner_text()
            c.ok(f"{tag} ③ 머리 클릭 정렬(MMSI 오름차순)", int(first) == min(s["mmsi"] for s in w["ships"]), first)
            c.ok(f"{tag} ③ 가로 스크롤 없음", page.evaluate(no_hscroll))
            # ③-상세
            page.evaluate(f"() => window.coast.navigate('ship', '{mm}')")
            page.wait_for_function("document.querySelector('#page-ship').classList.contains('active') && document.querySelector('#map-ship .ol-viewport') && document.querySelector('#shipDetail .hourly')", timeout=60000)
            page.wait_for_timeout(600)
            det = page.locator("#shipDetail").inner_text()
            c.ok(f"{tag} ③ 상세: 요약·지도·시간별·종류·코드별·신호 원인", all(k in det for k in ("등급", "항적", "시간별 판정", "메시지 종류별 건수", "코드별 비정상 행 수", "송신기 약함")))
            c.ok(f"{tag} ③ 상세 ← 목록 · 지도에서 보기", page.locator("#backList").count() == 1 and page.locator("#toMap").count() == 1)
            c.ok(f"{tag} ③ 상세 시간별 막대 그려짐", page.evaluate("() => [...document.querySelectorAll('#shipDetail .hourly .col div')].some(d => parseFloat(d.style.height) > 0)"))
            c.ok(f"{tag} ③ '지도에서 보기' 링크에 mmsi", f"mmsi={mm}" in page.locator("#toMap").get_attribute("href"))
            page.click("#toMap"); page.wait_for_function("document.querySelector('#page-map').classList.contains('active') && document.querySelector('#shipCard .kv') !== null", timeout=60000)
            c.ok(f"{tag} ③ '지도에서 보기' → 지도 + 카드", str(mm) in page.locator("#shipCard").inner_text())
            page.evaluate("() => closeCard()")
            c.ok(f"{tag} ③ 상세 가로 스크롤 없음", page.evaluate(no_hscroll))
            # ④ 수신 현황
            page.evaluate("() => window.coast.navigate('flow')")
            page.wait_for_function("document.querySelector('#page-flow').classList.contains('active') && document.querySelectorAll('#barSite .hbar').length > 0", timeout=30000)
            c.ok(f"{tag} ④ 막대 3묶음", page.locator("#barSite .hbar").count() >= 1 and page.locator("#barKind .hbar").count() == 4 and page.locator("#barThreat .hbar").count() == 7)
            c.ok(f"{tag} ④ 선버스트·생키 없음", page.locator("#sunburst, #sankey, svg path").count() == 0)
            tot = w["topology"]["total"]
            sent = page.locator("#flowSentence").inner_text()
            n_rows = int(re.search(r"([\d,]+)건", sent).group(1).replace(",", ""))
            c.ok(f"{tag} ④ 문장 건수 = total", n_rows == tot["n_rows"], f"{n_rows} vs {tot['n_rows']}")
            # 막대 ① 조각 폭 합 ≈ 100 %, 오른쪽 건수 합 = 전체
            widths = page.evaluate("() => [...document.querySelectorAll('#barSite .hbar')].map(b => [...b.querySelectorAll('.seg')].map(s => parseFloat(s.style.width)).reduce((a, x) => a + x, 0))")
            c.ok(f"{tag} ④ 막대① 조각 합 = 100 %", all(abs(x - 100) < 0.05 for x in widths), f"{widths}")
            site_rows = [int(re.search(r"([\d,]+)\s*건", t).group(1).replace(",", "")) for t in page.locator("#barSite .hbar .val").all_inner_texts()]
            c.ok(f"{tag} ④ 막대① 건수 합 = 전체", sum(site_rows) == tot["n_rows"], f"{site_rows}")
            kind_rows = [int(re.search(r"([\d,]+)\s*건", t).group(1).replace(",", "")) for t in page.locator("#barKind .hbar .val").all_inner_texts()]
            c.ok(f"{tag} ④ 막대② 건수 합 = 전체 (VDE 0 자리)", sum(kind_rows) == tot["n_rows"] and kind_rows[3] == 0, f"{kind_rows}")
            th_ships = [int(re.search(r"([\d,]+)\s*척", t).group(1).replace(",", "")) for t in page.locator("#barThreat .hbar .val").all_inner_texts()]
            c.ok(f"{tag} ④ 막대③ 배 수 합(위협 1~5+보류+정상) = 전체 배", sum(th_ships) == w["n_ships"], f"{th_ships}")
            c.ok(f"{tag} ④ 상위 20 표", 0 < page.locator("#flowTop tr[data-mmsi]").count() <= 20)
            # 조각 클릭 = 공유 필터(목록·지도에 반영)
            page.click("#barThreat .hbar .seg[data-act='threat:5']"); page.wait_for_timeout(300)
            th5 = next(t for t in w["threat_cards"] if t["rank"] == 5)["n_ships"]
            n_f = page.evaluate("() => window.coast.shipSrc.getFeatures().length")
            page.evaluate("() => window.coast.navigate('ships')"); page.wait_for_timeout(400)
            c.ok(f"{tag} ④ 위협 5 조각 클릭 → 목록 행 수 = 위협 5 배 수", page.locator("#shipTable tbody tr").count() == th5, f"{page.locator('#shipTable tbody tr').count()} vs {th5}")
            c.ok(f"{tag} ④ 같은 필터가 지도에도(≤ 위협 5 배 수)", n_f <= th5)
            c.ok(f"{tag} ④ 해시에 필터 실림", "th=5" in page.url)
            page.evaluate("() => { clearFilter('all'); afterFilter(); }")
            c.ok(f"{tag} ④ 가로 스크롤 없음", page.evaluate(no_hscroll))
            # ⑤ 신호 품질
            page.evaluate("() => window.coast.navigate('signal')")
            page.wait_for_function("document.querySelector('#page-signal').classList.contains('active') && document.querySelectorAll('#sigCards .sigcard').length === 4 && document.querySelector('#map-signal .ol-viewport')", timeout=120000)
            page.wait_for_function("document.querySelector('#status').textContent === ''", timeout=120000)
            c.ok(f"{tag} ⑤ 원인 카드 4장", page.locator("#sigCards .sigcard").count() == 4)
            c.ok(f"{tag} ⑤ 지도", page.locator("#map-signal .ol-viewport").count() == 1)
            c.ok(f"{tag} ⑤ 왜 이렇게 그렸나 10줄", page.locator("#sigWhy li").count() == 10)
            c.ok(f"{tag} ⑤ 근거 문서 링크", page.locator("a[href='/docs/SIGNAL_QUALITY_BASIS.md']").count() >= 1)
            ss = api("/api/signal_summary", src="real", judge="rule")
            shares = [float(x.rstrip("%")) for x in page.locator("#sigCards .sigcard .n").all_inner_texts()]
            c.ok(f"{tag} ⑤ 카드 % = API", all(abs(a - round(b["share"] * 100)) < 0.6 for a, b in zip(shares, ss["cards"])), f"{shares}")
            c.ok(f"{tag} ⑤ 몫 합 = 100 %", abs(sum(x["share"] for x in ss["cards"]) - 1) < 2e-3)
            c.ok(f"{tag} ⑤ 3단계 합 = 배 수", sum(ss["levels"].values()) == ss["n_ships"])
            c.ok(f"{tag} ⑤ 등고선 그려짐", page.evaluate("() => window.coast.S.layers.signal.margin.getSource().getFeatures().length") > 0)
            c.ok(f"{tag} ⑤ 가로 스크롤 없음", page.evaluate(no_hscroll))
            # 조건 버튼·팝오버 (소스 2개·기간·판정기·정답)
            page.click("#condBtn"); page.wait_for_timeout(200)
            c.ok(f"{tag} 조건 팝오버(소스·기간·판정기)", page.locator("#condPop").is_visible() and page.locator("#src option").count() == 2 and page.locator("#judge option").count() >= 2)
            page.select_option("#src", "ds015")
            page.wait_for_function("window.coast.F.src === 'ds015' && window.coast.S.window && window.coast.S.window.src === 'ds015'", timeout=90000)
            page.wait_for_timeout(500)
            c.ok(f"{tag} 생성 벌 '정답 보기' 토글 보임", page.locator("#truthWrap").is_visible())
            c.ok(f"{tag} 해시에 src 실림", "src=ds015" in page.url)
            c.ok(f"{tag} 브라우저 오류 0", not errors, "; ".join(errors[:5]))
            c.ok(f"{tag} docs 경로", page.request.get(B + "/docs/SIGNAL_QUALITY_BASIS.md").status == 200 and page.request.get(B + "/docs/../coast/app.py").status in (404, 400))
            page.close()
        browser.close()
    return c.done()


if __name__ == "__main__":
    sys.exit(main())
