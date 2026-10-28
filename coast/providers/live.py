"""LiveProvider — 실시간 수집기가 생기면 여기에 구현한다 (1차: 자리만, 전부 NotImplementedError).

같은 일곱 메서드(base.SnapshotProvider — 2차에 signal_summary 추가)를 구현하고 `app.py` 의 PROVIDERS 에 'live' 소스로 꽂는다.
  · `sources()` 가 kind='live' 소스 하나를 낸다(t_max 는 지금).
  · `window`/`ships_at`/`ship`/`contours` 는 수집기 버퍼(예: 최근 24 h 링 버퍼)에서 같은 모양의 dict 를 만든다 —
    비정상 정의는 반드시 `coast/judge.py` 를 그대로 쓴다(여기서 다시 정의하지 않는다).
  · `changes_since(src, t)` 가 t 이후 바뀐 배만 Delta 로 돌려주면 프런트 폴링 훅(app.js POLL_MS > 0)이 지도만 갱신한다.
"""
from __future__ import annotations

from .base import Delta, Filter, ShipDetail, ShipState, Source, WindowStats


class LiveProvider:
    def sources(self) -> list[Source]:
        raise NotImplementedError("LiveProvider: 실시간 수집기가 아직 없다 (1차 범위 밖)")

    def window(self, src: str, t0: str | None, t1: str | None, flt: Filter) -> WindowStats:
        raise NotImplementedError

    def ships_at(self, src: str, t: str | None, flt: Filter, t0: str | None = None, t1: str | None = None) -> list[ShipState]:
        raise NotImplementedError

    def ship(self, src: str, mmsi: int, t0: str | None, t1: str | None, flt: Filter) -> ShipDetail:
        raise NotImplementedError

    def contours(self, src: str, t0: str | None, t1: str | None, layer: str) -> dict:
        raise NotImplementedError

    def signal_summary(self, src: str, t0: str | None, t1: str | None, flt: Filter) -> dict:
        raise NotImplementedError

    def changes_since(self, src: str, t: str) -> Delta | None:
        raise NotImplementedError
