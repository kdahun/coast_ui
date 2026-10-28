// 아이콘 회전·색 — 지도(app.js)와 단위 검사(tests/check_icon_rotation.js)가 같은 함수를 쓴다.
// 아이콘 에셋은 0° 에서 오른쪽(동)을 향한다(static/icons/mapping.json 의 icon_points_deg = 90).
// OpenLayers Icon.rotation 은 시계방향 라디안이므로 회전 = (침로 − icon_points_deg) 를 0~360 으로 접은 뒤 라디안.
//
// 2차(2026-10-27): 원형 점을 없앴다. 방향 우선순위는 서버(ParquetProvider._direction)와 같다 —
//   선수 HDG(heading) → COG 데이터(cog, cog_source='data') → 항적 추정(cog, cog_source='track')
//   → 기간 안 마지막 유효 HDG/COG(last_dir, 출처 'last') → 없으면 북쪽 0° 고정(출처 'none', "?" 표식).
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.CoastRotation = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const num = (v) => v !== null && v !== undefined && isFinite(v);

  function iconRotationRad(courseDeg, pointsDeg) {
    if (!num(courseDeg)) return null;
    const p = (pointsDeg === undefined || pointsDeg === null) ? 90 : pointsDeg;
    const d = (((courseDeg - p) % 360) + 360) % 360;
    return d * Math.PI / 180;
  }

  // 배 → { deg, source }. 항상 값을 준다(원형 점 없음). source ∈ heading | cog | track | last | none
  function shipCourse(ship) {
    if (num(ship.heading)) return { deg: ship.heading, source: 'heading' };
    if (num(ship.cog)) return { deg: ship.cog, source: ship.cog_source === 'track' ? 'track' : 'cog' };
    if (num(ship.last_dir)) return { deg: ship.last_dir, source: 'last' };
    return { deg: 0, source: 'none' };
  }

  // 출처 → 사람이 읽는 문구 (툴팁·카드·범례)
  const SOURCE_LABEL = { heading: '선수 (HDG)', cog: '침로 (COG)', track: '침로 (항적 추정)', last: '마지막 유효값', none: '방향 미상 (북쪽 고정)' };
  function courseText(ship) {
    const c = shipCourse(ship);
    if (c.source === 'none') return SOURCE_LABEL.none;
    if (c.source === 'last') return `${c.deg.toFixed(0)}° (${ship.last_dir_source === 'heading' ? '마지막 선수' : '마지막 침로'})`;
    return `${c.source === 'heading' ? '선수' : '침로'} ${c.deg.toFixed(0)}° (${c.source === 'heading' ? 'HDG' : c.source === 'cog' ? 'COG' : '항적 추정'})`;
  }

  // 배 → 아이콘 색 이름 (mapping.json 한 곳). 선택한 배는 green.
  function colorOf(ship, mapping, selected) {
    if (selected) return mapping.selected || 'green';
    if (ship.state === 'abn' && ship.impact && mapping.by_impact && mapping.by_impact[ship.impact]) return mapping.by_impact[ship.impact];
    if (ship.state === 'hold') return (mapping.by_state && mapping.by_state.hold) || 'pink';
    return (mapping.by_state && mapping.by_state.ok) || 'gray';
  }

  return { iconRotationRad, shipCourse, courseText, colorOf, SOURCE_LABEL };
});
