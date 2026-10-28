"""헤드리스 캡처(2차) — docs/screenshots/coast_r2_{overview,map,map_card,ships,ship_detail,flow,signal}[_1280].png
1440×900 한 벌 + 1280×800 한 벌(파일 이름에 _1280). 지시서 §4.

    .\\venv\\Scripts\\python.exe tests\\capture.py [--base http://127.0.0.1:8801] [--out docs/screenshots]

서버가 떠 있어야 한다. 설치된 Chrome(없으면 Edge)을 playwright channel 로 쓴다 — 브라우저 내려받기 없음.
브라우저 콘솔 오류·페이지 오류가 하나라도 있으면 종료 코드 1 (캡처는 그래도 남긴다). 1차 캡처(coast_*.png)는 지우지 않는다(전/후 비교용).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _common import api  # noqa: E402


def launch(p):
    for ch in ("chrome", "msedge", None):
        try:
            return p.chromium.launch(channel=ch, headless=True) if ch else p.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {ch or 'chromium'} 실행 실패: {str(e).splitlines()[0]}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8801")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    a = ap.parse_args()
    sys.argv = [sys.argv[0], a.base]          # _common.base() 가 읽는다
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    w = api("/api/window", src="real", judge="rule")
    mm = next(s["mmsi"] for s in sorted(w["ships"], key=lambda s: (s["impact"] != "H", -s["abn_ratio"])) if s["kinds"]["pos"][0] > 0 and s["state"] == "abn")
    errors: list[str] = []
    with sync_playwright() as p:
        browser = launch(p)
        if browser is None:
            print("브라우저를 못 띄움"); return 2
        for width, height, suffix in ((1440, 900, ""), (1280, 800, "_1280")):
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            shot = lambda name: (page.screenshot(path=str(out / f"coast_r2_{name}{suffix}.png")), print(f"  coast_r2_{name}{suffix}.png"))  # noqa: E731
            # ① 상황판
            page.goto(a.base + "/#/overview?src=real", wait_until="networkidle")
            page.wait_for_function("document.querySelectorAll('#ovTiles .tile').length === 4 && window.coast && window.coast.shipSrc.getFeatures().length > 0", timeout=90000)
            page.wait_for_timeout(1500); shot("overview")
            # ② 지도 — 필터 패널 열고(툴바 방식이 보이게)
            page.evaluate("() => window.coast.navigate('map')")
            page.wait_for_function("document.querySelector('#map-main .ol-viewport') !== null", timeout=30000)
            page.wait_for_timeout(1200)
            page.evaluate("() => { window.coast.fitShips(window.coast.maps.main, 0); const v = window.coast.maps.main.getView(); v.setZoom(Math.max(v.getZoom(), 11)); }")
            page.click("#toolbar .tb[data-panel=legend]"); page.wait_for_timeout(800); shot("map")
            page.click("#toolbar .tb[data-panel=legend]")
            # ②-카드 — 배 클릭 → 오른쪽 카드 + 항적
            page.evaluate(f"() => openCard({mm}, true)")
            page.wait_for_function("document.querySelector('#shipCard .kv') !== null", timeout=60000)
            page.wait_for_timeout(1200); shot("map_card")
            # ③ 목록
            page.evaluate("() => window.coast.navigate('ships')")
            page.wait_for_function("document.querySelectorAll('#shipTable tbody tr').length > 0", timeout=30000)
            page.wait_for_timeout(500); shot("ships")
            # ③-상세
            page.evaluate(f"() => window.coast.navigate('ship', '{mm}')")
            page.wait_for_function("document.querySelector('#map-ship .ol-viewport') && document.querySelector('#shipDetail .hourly')", timeout=60000)
            page.wait_for_timeout(1500); shot("ship_detail")
            # ④ 수신 현황
            page.evaluate("() => window.coast.navigate('flow')")
            page.wait_for_function("document.querySelectorAll('#barSite .hbar').length > 0", timeout=30000)
            page.wait_for_timeout(500); shot("flow")
            # ⑤ 신호 품질 — 수신 여유 + 환경 잔차 + 보고 밀도 켜고
            page.evaluate("() => window.coast.navigate('signal')")
            page.wait_for_function("document.querySelectorAll('#sigCards .sigcard').length === 4 && document.querySelector('#map-signal .ol-viewport')", timeout=120000)
            page.check("#sgEnv"); page.check("#sgDensity")
            page.wait_for_function("document.querySelector('#status').textContent === '' && window.coast.S.layers.signal.env.getSource().getFeatures().length > 0", timeout=120000)
            page.evaluate("() => { window.coast.fitShips(window.coast.maps.signal, 0); const v = window.coast.maps.signal.getView(); v.setZoom(Math.max(v.getZoom(), 11)); }")
            page.wait_for_timeout(1500); shot("signal")
            page.close()
        browser.close()
    if errors:
        print("브라우저 오류:"); [print("  " + e) for e in errors]
        return 1
    print("브라우저 오류 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
