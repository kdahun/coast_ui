// (e) 아이콘 회전 각이 선수와 같은지 — 단위 검사 (브라우저·서버 없이 node 로).
//
//   node tests/check_icon_rotation.js
//
// static/rotation.js 의 함수를 그대로 쓴다(지도 app.js 와 같은 코드). 아이콘은 0° 에서 동쪽을 향하므로
// (mapping.json icon_points_deg = 90) OL 회전(시계방향 라디안) = (침로 − 90)·π/180 을 0~2π 로 접은 값.
// 2차: 우선순위 heading → cog(data) → cog(track) → last → none(북쪽 0°, 원형 점 없음) 과 출처 문구.
'use strict';
const path = require('path');
const fs = require('fs');
const R = require(path.join(__dirname, '..', 'static', 'rotation.js'));
const mapping = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'static', 'icons', 'mapping.json'), 'utf8'));
const P = mapping.icon_points_deg;
let n = 0; const fail = [];
const near = (a, b) => Math.abs(a - b) < 1e-9;
function ok(label, cond, detail) { n++; if (!cond) fail.push(label + (detail ? ' ' + detail : '')); }

ok('mapping icon_points_deg = 90 (아이콘이 동쪽을 향함)', P === 90);
ok('mapping 원형 점 아님', mapping.no_heading_marker !== 'circle');
// 침로 → 회전: 북(0) → 270° 시계방향, 동(90) → 0, 남(180) → 90°, 서(270) → 180°
const cases = [[0, 270], [90, 0], [180, 90], [270, 180], [45, 315], [359.5, 269.5], [360, 270], [-90, 180]];
for (const [hdg, deg] of cases) {
  const r = R.iconRotationRad(hdg, P);
  ok(`침로 ${hdg}° → 회전 ${deg}°`, near(r, deg * Math.PI / 180), `got ${(r * 180 / Math.PI).toFixed(3)}°`);
}
// 아이콘 끝점이 실제로 침로 방향을 가리키는가
for (const hdg of [0, 30, 90, 135, 180, 225, 270, 300]) {
  const r = R.iconRotationRad(hdg, P);
  const x = Math.cos(r), y = Math.sin(r);
  const ex = Math.sin(hdg * Math.PI / 180), ey = -Math.cos(hdg * Math.PI / 180);
  ok(`침로 ${hdg}° 아이콘 끝점 방향`, Math.abs(x - ex) < 1e-9 && Math.abs(y - ey) < 1e-9, `(${x.toFixed(3)},${y.toFixed(3)}) vs (${ex.toFixed(3)},${ey.toFixed(3)})`);
}
for (let h = -720; h <= 720; h += 7.5) { const r = R.iconRotationRad(h, P); ok(`회전 범위 ${h}`, r >= 0 && r < 2 * Math.PI); }
ok('iconRotationRad(null) → null (호출자가 쓰지 않음)', R.iconRotationRad(null, P) === null);
ok('iconRotationRad(NaN) → null', R.iconRotationRad(NaN, P) === null);

// ── 우선순위 heading > cog(data) > cog(track) > last > none ──
const sc = (s) => R.shipCourse(s);
ok('heading 우선', sc({ heading: 10, cog: 200, cog_source: 'data', last_dir: 5 }).deg === 10 && sc({ heading: 10, cog: 200, cog_source: 'data' }).source === 'heading');
ok('heading 없으면 cog(data)', sc({ heading: null, cog: 200, cog_source: 'data' }).deg === 200 && sc({ heading: null, cog: 200, cog_source: 'data' }).source === 'cog');
ok('cog 가 항적 추정이면 track', sc({ heading: null, cog: 200, cog_source: 'track' }).source === 'track' && sc({ heading: null, cog: 200, cog_source: 'track' }).deg === 200);
ok('heading·cog 없으면 last', sc({ heading: null, cog: null, cog_source: null, last_dir: 77, last_dir_source: 'heading' }).deg === 77 && sc({ heading: null, cog: null, last_dir: 77 }).source === 'last');
ok('전부 없으면 none — 북쪽 0° (원형 점 없음)', sc({ heading: null, cog: null, last_dir: null }).deg === 0 && sc({ heading: null, cog: null, last_dir: null }).source === 'none');
ok('빈 객체도 none', sc({}).source === 'none' && sc({}).deg === 0);
ok('shipCourse 는 null 을 돌려주지 않는다', [{}, { heading: null }, { cog: NaN }, { last_dir: undefined }].every((s) => sc(s) !== null && isFinite(sc(s).deg)));
ok('none 의 회전 = 북쪽(270°)', near(R.iconRotationRad(sc({}).deg, P), 270 * Math.PI / 180));
ok('heading 0 은 유효(북)', sc({ heading: 0, cog: 100, cog_source: 'data' }).source === 'heading' && sc({ heading: 0, cog: 100 }).deg === 0);
// 출처 문구
ok('문구 heading', R.courseText({ heading: 123 }).includes('선수 123°') && R.courseText({ heading: 123 }).includes('HDG'));
ok('문구 cog', R.courseText({ heading: null, cog: 98, cog_source: 'data' }).includes('침로 98°') && R.courseText({ heading: null, cog: 98, cog_source: 'data' }).includes('COG'));
ok('문구 track', R.courseText({ heading: null, cog: 45, cog_source: 'track' }).includes('항적 추정'));
ok('문구 last', R.courseText({ heading: null, cog: null, last_dir: 30, last_dir_source: 'cog' }).includes('마지막 침로'));
ok('문구 none', R.courseText({}).includes('방향 미상') && R.courseText({}).includes('북쪽'));
// 색 매핑 — mapping.json 한 곳
ok('H → red', R.colorOf({ state: 'abn', impact: 'H' }, mapping, false) === 'red');
ok('M → yellow', R.colorOf({ state: 'abn', impact: 'M' }, mapping, false) === 'yellow');
ok('L → blue', R.colorOf({ state: 'abn', impact: 'L' }, mapping, false) === 'blue');
ok('ok → gray', R.colorOf({ state: 'ok' }, mapping, false) === 'gray');
ok('hold → pink', R.colorOf({ state: 'hold' }, mapping, false) === 'pink');
ok('선택 → green', R.colorOf({ state: 'abn', impact: 'H' }, mapping, true) === 'green');
for (const c of ['gray', 'red', 'blue', 'green', 'pink', 'yellow']) ok(`아이콘 파일 vessel_${c}.png 있음`, fs.existsSync(path.join(__dirname, '..', 'static', 'icons', `vessel_${c}.png`)));
// app.js 가 같은 함수를 쓰는지(복사본 금지) · 원형 점 코드 없음 · 선버스트/생키/d3 없음
const app = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
ok('app.js 가 CoastRotation.iconRotationRad 를 쓴다', app.includes('CoastRotation.iconRotationRad('));
ok('app.js 가 CoastRotation.shipCourse 를 쓴다', app.includes('CoastRotation.shipCourse('));
ok('app.js 가 CoastRotation.colorOf 를 쓴다', app.includes('CoastRotation.colorOf('));
ok('app.js 가 CoastRotation.courseText 를 쓴다', app.includes('CoastRotation.courseText('));
ok('app.js 배 스타일에 원형 점 분기 없음', !/rot === null/.test(app));
ok('app.js 에 선버스트·생키·d3 없음', !/sunburst|sankey|d3\./i.test(app));
const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
ok('index.html 에 d3 스크립트 없음', !/d3/.test(html));
ok('index.html 에 CDN 없음', !/https?:\/\/[^"']*\.(js|css)/.test(html));
ok('vendor 에 d3 없음', !fs.existsSync(path.join(__dirname, '..', 'static', 'vendor', 'd3.min.js')) && !fs.existsSync(path.join(__dirname, '..', 'static', 'vendor', 'd3-sankey.min.js')));

if (fail.length) { console.log(`[icon_rotation] 실패 ${fail.length} / 검사 ${n}`); fail.forEach((f) => console.log('   ✗ ' + f)); process.exit(1); }
console.log(`[icon_rotation] 통과 — 검사 ${n} 건`);
