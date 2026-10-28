// 해안국 관리자 화면 2차 — 프런트. /api/* 만 본다(제공자가 바뀌어도 모른다).
// 화면 하나 = 질문 하나: #/overview(몇 척?) #/map(어디?) #/ships·#/ship/<mmsi>(어느 배?) #/flow(어디서 얼마나?) #/signal(전파 상태?)
// 조건(소스·기간·판정기·정답 보기)과 공유 필터는 URL 해시 질의에 실려 화면을 옮겨도 유지된다. 시점(t)은 지도 화면에만.
// 기간(t0·t1) = 합산(카드·목록·수신 현황·등고선), 시점(t) = 지도 배 위치만. 1차 기능은 전부 남아 있고 자리만 바뀌었다.
'use strict';

// ── 실시간 폴링 훅 자리 — 1차 그대로 0(꺼짐). /api/state 의 poll_ms > 0 이면 /api/changes 를 주기로 부른다.
let POLL_MS = 0;

const PAGES = ['overview', 'map', 'ships', 'ship', 'flow', 'signal'];
const GRADES = ['H', 'M', 'L', 'ok', 'hold'];
const GRADE_LABEL = { H: 'H 즉시 확인', M: 'M 확인 필요', L: 'L 참고', ok: '정상', hold: '보류' };
// 공유 필터 F — grades/threats 비어 있음 = 전체
const F = { src: null, t0: null, t1: null, t: null, judge: 'rule', truth: false,
  grades: new Set(), threats: new Set(), site: null, kind: null, nav: null, search: '', mmsi: null };
const S = { state: null, window: null, shipsAt: null, detailCache: new Map(), signal: null, sort: { key: 'default', dir: 1 },
  page: 'overview', param: null, panel: null, playing: null, maps: {}, layers: {}, contourLoaded: {}, contourMeta: {}, fitted: {}, loading: 0 };
const $ = (id) => document.getElementById(id);
const fmtPct = (x, d = 1) => (x === null || x === undefined || isNaN(x)) ? '—' : (x * 100).toFixed(d) + '%';
const fmtN = (x) => (x === null || x === undefined) ? '—' : Number(x).toLocaleString('ko-KR');
const fmtDb = (x, d = 1) => (x === null || x === undefined || isNaN(x)) ? '—' : (x >= 0 ? '+' : '') + Number(x).toFixed(d) + ' dB';
const hhmm = (iso) => iso ? iso.slice(5, 16).replace('T', ' ') : '—';
const mmdd = (iso) => iso ? iso.slice(5, 16).replace('T', ' ') : '—';
const STATE_LABEL = { ok: '정상', hold: '보류', abn: '비정상' };
const LEVEL_LABEL = { good: '좋음', fair: '보통', bad: '나쁨' };
const COLOR_HEX = { red: '#e5484d', yellow: '#f5c518', blue: '#3b82f6', gray: '#9aa5b1', pink: '#f472b6', green: '#22c55e' };
const KIND_LABEL = {};
let mapping = {};

function setStatus(msg) { $('status').textContent = msg || ''; }
function showError(msg) {
  let b = document.querySelector('.errbox');
  if (!b) { b = document.createElement('div'); b.className = 'errbox'; document.body.appendChild(b); }
  b.textContent = msg; clearTimeout(b._t); b._t = setTimeout(() => b.remove(), 8000);
}
async function api(path, params) {
  const u = new URL(path, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== '') u.searchParams.set(k, v); });
  const r = await fetch(u);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) { /* no body */ } throw new Error(`${path}: ${m}`); }
  return r.json();
}
const judgeParam = () => (F.truth ? 'truth' : F.judge);
// 기간이 전체면 t0·t1 을 보내지 않는다 — 서버가 소수점 초까지 포함한 실제 최소·최대 시각을 쓴다(초 단위 ISO 로 보내면 마지막 초의 행이 빠진다)
function periodParams() { const src = currentSource(); return { t0: F.t0 === src.t_min ? null : F.t0, t1: F.t1 === src.t_max ? null : F.t1 }; }
function tParam() { const src = currentSource(); return (F.t === F.t1 && F.t1 === src.t_max) ? null : F.t; }
const currentSource = () => S.state.sources.find((s) => s.id === F.src);
const gradeOf = (s) => (s.state === 'abn' ? (s.impact || 'L') : s.state);
const toLocalInput = (iso) => iso ? iso.slice(0, 16) : '';
const fromLocalInput = (v) => v ? v + ':00' : null;
function minutesBetween(a, b) { return Math.max(0, Math.round((new Date(b) - new Date(a)) / 60000)); }
function addMinutes(iso, m) { const d = new Date(iso); d.setMinutes(d.getMinutes() + m); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`; }
const clampT = (t) => (t < F.t0 ? F.t0 : t > F.t1 ? F.t1 : t);
function codeDesc(code) { const c = S.state.codes.find((x) => x.code === code); return c ? c.desc : ''; }
function threatOf(rank) { return S.state.threats.find((x) => x.rank === rank); }

// ── 해시 라우터 ──────────────────────────────────────────────────────────
function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, qs] = h.split('?');
  const parts = path.split('/');
  const page = PAGES.includes(parts[0]) ? parts[0] : 'overview';
  return { page, param: parts[1] || null, q: new URLSearchParams(qs || '') };
}
function buildHash(page, param) {
  const q = new URLSearchParams(); const src = currentSource();
  if (F.src) q.set('src', F.src);
  if (src && F.t0 && F.t0 !== src.t_min) q.set('t0', F.t0);
  if (src && F.t1 && F.t1 !== src.t_max) q.set('t1', F.t1);
  if (F.judge !== 'rule') q.set('judge', F.judge);
  if (F.truth) q.set('truth', '1');
  if (page === 'map' && F.t && F.t !== F.t1) q.set('t', F.t);
  if (F.grades.size) q.set('g', [...F.grades].join(','));
  if (F.threats.size) q.set('th', [...F.threats].join(','));
  if (F.site !== null) q.set('site', F.site);
  if (F.kind) q.set('kind', F.kind);
  if (F.nav) q.set('nav', F.nav);
  if (F.search) q.set('q', F.search);
  if (page === 'map' && F.mmsi !== null) q.set('mmsi', F.mmsi);
  const qs = q.toString();
  return '#/' + page + (param ? '/' + param : '') + (qs ? '?' + qs : '');
}
function navigate(page, param) { location.hash = buildHash(page, param); }
function syncHash() { history.replaceState(null, '', buildHash(S.page, S.param)); updateMenu(); }
function updateMenu() {
  document.querySelectorAll('#menu a').forEach((a) => { const p = a.dataset.page; a.classList.toggle('active', S.page === p || (S.page === 'ship' && p === 'ships')); a.href = buildHash(p); });
}
async function route() {
  const { page, param, q } = parseHash();
  let reload = false, reloadShips = false;
  const srcId = q.get('src');
  if (srcId && srcId !== F.src && S.state.sources.some((s) => s.id === srcId)) { F.src = srcId; applySourceDefaults(); reload = true; }
  const src = currentSource();
  const t0 = q.get('t0') || src.t_min, t1 = q.get('t1') || src.t_max;
  if (t0 !== F.t0 || t1 !== F.t1) { F.t0 = t0 < t1 ? t0 : t1; F.t1 = t0 < t1 ? t1 : t0; F.t = F.t1; reload = true; }
  const judge = q.get('judge') || 'rule';
  if (judge !== F.judge && src.judges.includes(judge) && judge !== 'truth') { F.judge = judge; reload = true; }
  const truth = q.get('truth') === '1' && !!src.has_truth;
  if (truth !== F.truth) { F.truth = truth; reload = true; }
  const t = q.get('t');
  if (page === 'map' && t) { const tc = clampT(t); if (tc !== F.t) { F.t = tc; reloadShips = true; } }
  F.grades = new Set((q.get('g') || '').split(',').filter((x) => GRADES.includes(x) || x === '-'));
  F.threats = new Set((q.get('th') || '').split(',').map(Number).filter((x) => x >= 1 && x <= 5));
  F.site = q.has('site') ? Number(q.get('site')) : null;
  F.kind = q.get('kind') || null; F.nav = q.get('nav') || null; F.search = q.get('q') || '';
  if (page === 'map' && q.has('mmsi')) F.mmsi = Number(q.get('mmsi'));
  S.page = page; S.param = param;
  if (page !== 'map') stopPlay();
  showPage(page); syncFilterUI(); setCondUI();
  if (reload || !S.window) { await loadWindow(); loadShipsAt(); }
  else if (reloadShips) loadShipsAt();
  renderPage(); renderShips();
}
function showPage(page) {
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + page));
  updateMenu();
  requestAnimationFrame(() => { const m = S.maps[page === 'overview' ? 'mini' : page === 'ship' ? 'ship' : page]; if (m) m.updateSize(); });
}
function renderPage() {
  updateMenu(); updateCondButton();
  if (!S.window) return;
  ({ overview: renderOverview, map: renderMapPage, ships: renderList, ship: renderShipPage, flow: renderFlow, signal: renderSignal })[S.page]();
}

// ── 조건(소스·기간·판정기·정답) — 팝오버 ──────────────────────────────────
function applySourceDefaults() {
  const src = currentSource();
  F.t0 = src.t_min; F.t1 = src.t_max; F.t = src.t_max;
  if (!src.judges.includes(F.judge)) F.judge = 'rule';
  if (!src.has_truth) F.truth = false;
  F.mmsi = null; S.fitted = {};
}
function setCondUI() {
  const src = currentSource();
  $('src').value = F.src;
  $('t0').value = toLocalInput(F.t0); $('t1').value = toLocalInput(F.t1);
  $('judge').innerHTML = src.judges.filter((j) => j !== 'truth').map((j) => `<option value="${j}">${S.state.judges[j]}</option>`).join('');
  $('judge').value = F.judge;
  $('truthWrap').classList.toggle('hidden', !src.has_truth); $('truth').checked = F.truth;
  $('condInfo').textContent = `${src.label} · ${fmtN(src.rows)} 행 · ${fmtN(src.n_mmsi)} 척 · 자료 ${mmdd(src.t_min)} ~ ${mmdd(src.t_max)} · 유효 선수 ${fmtPct(src.dir_valid.heading, 0)} / 침로 ${fmtPct(src.dir_valid.course, 0)} (위치 보고 행)`;
  const n = minutesBetween(F.t0, F.t1);
  $('tslider').max = n; $('tslider').value = Math.min(n, minutesBetween(F.t0, F.t));
  $('tlabel').textContent = F.t ? F.t.slice(0, 16).replace('T', ' ') : '—';
}
function updateCondButton() {
  const src = currentSource(); if (!src) return;
  const name = src.kind === 'real' ? '부산 실해역' : '생성 ds_015';
  $('condBtn').textContent = `${name} · ${mmdd(F.t0)} ~ ${mmdd(F.t1)} · ${F.truth ? '정답' : S.state.judges[F.judge].split('(')[0].trim()} ▾`;
}
function condChanged() { syncHash(); loadWindow().then(() => { loadShipsAt(); }); }

// ── 지도 (OpenLayers) — 소스는 공유, 지도는 화면마다 ─────────────────────────
let shipSrc, trackSrc, shipOneSrc, contourSrcs = {};
const iconCache = {};
function cssColor(name, a) { const h = COLOR_HEX[name] || '#999'; return `rgba(${parseInt(h.slice(1, 3), 16)},${parseInt(h.slice(3, 5), 16)},${parseInt(h.slice(5, 7), 16)},${a})`; }
function iconStyle(color, rot, opacity, unknown) {
  const key = `${color}|${rot.toFixed(3)}|${opacity}|${unknown ? 'u' : ''}`;
  if (iconCache[key]) return iconCache[key];
  const st = new ol.style.Style({ image: new ol.style.Icon({ src: `/static/icons/vessel_${color}.png`, rotation: rot, rotateWithView: true, opacity, scale: 1.2 }) });
  if (unknown) {   // 방향 미상 — 북쪽 고정 에셋 + 작은 "?" 표식 (원형 점 없음)
    st.setText(new ol.style.Text({ text: '?', offsetY: -11, font: 'bold 11px sans-serif', fill: new ol.style.Fill({ color: '#fff' }), stroke: new ol.style.Stroke({ color: '#000', width: 3 }) }));
  }
  iconCache[key] = st; return st;
}
const selRing = new ol.style.Style({ image: new ol.style.Circle({ radius: 13, stroke: new ol.style.Stroke({ color: '#22c55e', width: 2 }), fill: null }) });
function shipStyle(f) {
  const s = f.get('ship');
  const selected = F.mmsi === s.mmsi;
  const color = CoastRotation.colorOf(s, mapping, selected);
  const course = CoastRotation.shipCourse(s);
  const rot = CoastRotation.iconRotationRad(course.deg, mapping.icon_points_deg);
  const opacity = s.age_s > (S.state.signal_basis.stale_s || 600) ? (mapping.stale_opacity || 0.45) : 1;
  const st = [iconStyle(color, rot, opacity, course.source === 'none')];
  if (selected) st.unshift(selRing);
  return st;
}
const dotCache = {};
function dotStyle(f) {
  const s = f.get('ship'); const color = CoastRotation.colorOf(s, mapping, F.mmsi === s.mmsi);
  if (!dotCache[color]) dotCache[color] = new ol.style.Style({ image: new ol.style.Circle({ radius: 3, fill: new ol.style.Fill({ color: cssColor(color, 0.9) }), stroke: new ol.style.Stroke({ color: 'rgba(0,0,0,.5)', width: 1 }) }) });
  return dotCache[color];
}
const LEVEL_COLORS = { margin: { 0: '#ef4444', 10: '#f59e0b', 20: '#22c55e' }, env: { '-10': '#7f1d1d', '-5': '#ef4444', 0: '#9aa5b1', 5: '#3b82f6' } };
function contourStyle(layer) {
  return (f) => { const lv = f.get('level'); const c = (LEVEL_COLORS[layer] || {})[String(lv)] || '#fff';
    return new ol.style.Style({ stroke: new ol.style.Stroke({ color: c, width: 2 }),
      text: new ol.style.Text({ text: `${lv > 0 ? '+' : ''}${lv}`, placement: 'line', fill: new ol.style.Fill({ color: c }), stroke: new ol.style.Stroke({ color: '#000', width: 3 }), font: '11px sans-serif', repeat: 300 }) }); };
}
function cellStyle(layer) {
  return (f) => { const p = f.getProperties(); const info = S.contourMeta[layer] ? S.contourMeta[layer].info : {}; let a, c;
    if (layer === 'density') { const mx = Math.log1p(info.max || 1); a = 0.08 + 0.6 * Math.log1p(p.ship_minutes || 0) / mx; c = `rgba(59,130,246,${a.toFixed(2)})`; }
    else { a = 0.05 + 0.7 * (p.envloss_ratio || 0); c = `rgba(244,114,182,${a.toFixed(2)})`; }
    return new ol.style.Style({ fill: new ol.style.Fill({ color: c }) }); };
}
const trackStyle = (f) => {
  if (f.getGeometry().getType() === 'LineString') return new ol.style.Style({ stroke: new ol.style.Stroke({ color: 'rgba(34,197,94,.8)', width: 2 }) });
  const stt = f.get('state'); const c = stt === 'abn' ? '#e5484d' : stt === 'hold' ? '#f472b6' : '#22c55e';
  return new ol.style.Style({ image: new ol.style.Circle({ radius: 2.5, fill: new ol.style.Fill({ color: c }) }) });
};
function baseLayer() {
  if (S.state.tiles_ok) return new ol.layer.Tile({ source: new ol.source.XYZ({ url: S.state.tile_url, crossOrigin: 'anonymous' }) });
  // 타일 서버 없음 — 항행수역(sea_mask) 칸을 바다색으로 깔아 육지 윤곽을 보인다
  if (!S.seaSrc) S.seaSrc = new ol.source.Vector({ url: '/api/seamask', format: new ol.format.GeoJSON({ dataProjection: 'EPSG:4326', featureProjection: 'EPSG:3857' }) });
  return new ol.layer.Vector({ source: S.seaSrc, style: new ol.style.Style({ fill: new ol.style.Fill({ color: 'rgba(30,58,95,.7)' }), stroke: new ol.style.Stroke({ color: 'rgba(30,58,95,.7)', width: 1 }) }) });
}
function ensureSources() {
  if (shipSrc) return;
  shipSrc = new ol.source.Vector(); trackSrc = new ol.source.Vector(); shipOneSrc = new ol.source.Vector();
  for (const k of ['density', 'envloss', 'margin', 'env']) contourSrcs[k] = new ol.source.Vector();
}
function contourLayers(mapName) {
  S.layers[mapName] = {};
  return ['density', 'envloss', 'margin', 'env'].map((k) => { const L = new ol.layer.Vector({ source: contourSrcs[k], visible: false, style: (k === 'margin' || k === 'env') ? contourStyle(k) : cellStyle(k) }); S.layers[mapName][k] = L; return L; });
}
function getMap(name) {
  if (S.maps[name]) return S.maps[name];
  ensureSources();
  const view = new ol.View({ center: ol.proj.fromLonLat([129.1, 35.05]), zoom: 10 });
  let map;
  if (name === 'main') {
    const trackLayer = new ol.layer.Vector({ source: trackSrc, style: trackStyle }); S.layers.main = {}; const cl = contourLayers('main'); S.layers.main.track = trackLayer;
    map = new ol.Map({ target: 'map-main', layers: [baseLayer(), ...cl, trackLayer, new ol.layer.Vector({ source: shipSrc, style: shipStyle, zIndex: 10 })], view, controls: ol.control.defaults.defaults({ attribution: false }) });
    const popupEl = $('popup');
    map.on('pointermove', (e) => {
      const f = map.forEachFeatureAtPixel(e.pixel, (ft) => ft.get('ship') ? ft : null, { hitTolerance: 4 });
      if (!f) { popupEl.classList.add('hidden'); map.getTargetElement().style.cursor = ''; return; }
      map.getTargetElement().style.cursor = 'pointer';
      popupEl.innerHTML = shipTip(f.get('ship'));
      popupEl.style.left = (e.pixel[0] + 14) + 'px'; popupEl.style.top = (e.pixel[1] + 14) + 'px';
      popupEl.classList.remove('hidden');
    });
    map.on('click', (e) => { const f = map.forEachFeatureAtPixel(e.pixel, (ft) => ft.get('ship') ? ft : null, { hitTolerance: 4 }); if (f) openCard(f.get('ship').mmsi, false); });
  } else if (name === 'mini') {
    map = new ol.Map({ target: 'map-mini', layers: [baseLayer(), new ol.layer.Vector({ source: shipSrc, style: dotStyle })], view, controls: [], interactions: [] });
  } else if (name === 'ship') {
    map = new ol.Map({ target: 'map-ship', layers: [baseLayer(), new ol.layer.Vector({ source: trackSrc, style: trackStyle }), new ol.layer.Vector({ source: shipOneSrc, style: shipStyle, zIndex: 10 })], view, controls: ol.control.defaults.defaults({ attribution: false }) });
  } else if (name === 'signal') {
    const cl = contourLayers('signal'); const ships = new ol.layer.Vector({ source: shipSrc, style: dotStyle, opacity: 0.7 }); S.layers.signal.ships = ships;
    map = new ol.Map({ target: 'map-signal', layers: [baseLayer(), ...cl, ships], view, controls: ol.control.defaults.defaults({ attribution: false }) });
  }
  S.maps[name] = map; return map;
}
// 배가 몰린 곳으로 맞춤 — 멀리 떨어진 한두 척(5~95 백분위 밖)은 무시한다
function fitShips(map, duration, src) {
  const fs = (src || shipSrc).getFeatures(); if (!fs.length) return;
  const xs = fs.map((f) => f.getGeometry().getCoordinates()[0]).sort((a, b) => a - b);
  const ys = fs.map((f) => f.getGeometry().getCoordinates()[1]).sort((a, b) => a - b);
  const q = (arr, p) => arr[Math.min(arr.length - 1, Math.floor(p * (arr.length - 1)))];
  const ext = [q(xs, 0.05), q(ys, 0.05), q(xs, 0.95), q(ys, 0.95)];
  if (ext[0] === ext[2]) { ext[0] -= 2000; ext[2] += 2000; } if (ext[1] === ext[3]) { ext[1] -= 2000; ext[3] += 2000; }
  map.getView().fit(ext, { padding: [30, 30, 30, 30], maxZoom: 13, duration: duration || 0 });
}
function shipTip(s) {
  const t = threatOf(s.threat);
  const grade = s.state === 'abn' ? `<span class="badge ${s.impact}">${s.impact}</span> 위협 ${s.threat} ${t ? t.title : ''} · ${t ? t.action : ''}` : `<span class="badge ${s.state}">${STATE_LABEL[s.state]}</span>`;
  const code = s.code ? `${s.code}${s.kind_of_code ? ' (' + s.kind_of_code + ')' : ''}` : '—';
  return `<b class="mono">MMSI ${s.mmsi}</b><br>${grade}<br>대표 코드: ${code}<br>신호: <span class="sig ${s.signal.level || 'none'}"></span>${LEVEL_LABEL[s.signal.level] || '자료 없음'} (여유 ${fmtDb(s.signal.margin_db, 0)})<br>` +
    `마지막 보고 ${hhmm(s.t)} (${s.age_s > 600 ? Math.round(s.age_s / 60) + '분 전 · 반투명' : s.age_s + '초 전'})<br>` +
    `${CoastRotation.courseText(s)} · 속력 ${s.sog === null || s.sog === undefined ? '—' : s.sog.toFixed(1) + ' kn'} · 주변 ${s.near_ships}척/3 km`;
}

// ── 공유 필터 ───────────────────────────────────────────────────────────────
function navOf(mmsi) {
  if (!S.shipsAt) return null; const s = S.shipsAt.byMmsi.get(mmsi); if (!s || s.sog === null || s.sog === undefined) return null;
  return s.sog >= 0.5 ? 'moving' : 'anchored';
}
function passFilter(s) {
  if (F.grades.size && !F.grades.has(gradeOf(s))) return false;
  if (F.threats.size && !F.threats.has(s.threat)) return false;
  if (F.site !== null && !(s.sites || [s.site]).includes(F.site)) return false;
  if (F.kind && !(s.kinds && s.kinds[F.kind] && s.kinds[F.kind][0] > 0)) return false;
  if (F.search && !String(s.mmsi).includes(F.search)) return false;
  if (F.nav && navOf(s.mmsi) !== F.nav) return false;
  return true;
}
function filteredShips() { return (S.window ? S.window.ships : []).filter(passFilter); }
function filterChips() {
  const chips = [];
  if (F.grades.size) chips.push(['g', '등급 ' + [...F.grades].map((g) => GRADE_LABEL[g] || g).join('·')]);
  if (F.threats.size) chips.push(['th', '위협 ' + [...F.threats].join('·')]);
  if (F.site !== null) chips.push(['site', `수신소 ${F.site}`]);
  if (F.kind) chips.push(['kind', KIND_LABEL[F.kind] || F.kind]);
  if (F.nav) chips.push(['nav', F.nav === 'moving' ? '항해 중' : '정박']);
  if (F.search) chips.push(['q', `MMSI "${F.search}"`]);
  return chips;
}
function renderFilterBar(el) {
  const chips = filterChips();
  el.innerHTML = (chips.length ? '공유 필터: ' : '공유 필터 없음 — 지도 ⚑ 필터·수신 현황 막대·상황판 타일로 거른다') +
    chips.map(([k, l]) => `<span class="chip" data-k="${k}">${l} ✕</span>`).join('') + (chips.length ? ' <span class="chip" data-k="all">모두 해제</span>' : '');
  el.querySelectorAll('.chip').forEach((c) => c.addEventListener('click', () => { clearFilter(c.dataset.k); afterFilter(); }));
}
function clearFilter(k) {
  if (k === 'all' || k === 'g') F.grades = new Set();
  if (k === 'all' || k === 'th') F.threats = new Set();
  if (k === 'all' || k === 'site') F.site = null;
  if (k === 'all' || k === 'kind') F.kind = null;
  if (k === 'all' || k === 'nav') F.nav = null;
  if (k === 'all' || k === 'q') F.search = '';
}
function afterFilter() { syncFilterUI(); syncHash(); renderPage(); renderShips(); }
function syncFilterUI() {
  $('kindSel').value = F.kind || ''; $('listKind').value = F.kind || ''; $('navSel').value = F.nav || ''; $('siteSel').value = F.site === null ? '' : String(F.site);
  $('search').value = F.search; $('listSearch').value = F.search;
  const g = F.grades; $('listState').value = !g.size ? '' : (g.has('hold') && g.size === 1) ? 'hold' : (g.has('ok') && g.size === 1) ? 'ok' : (['H', 'M', 'L'].every((x) => g.has(x)) && g.size === 3) ? 'abn' : '';
  document.querySelectorAll('#fGrades input').forEach((i) => { i.checked = !g.size || g.has(i.value); });
  document.querySelectorAll('#fThreats input').forEach((i) => { i.checked = !F.threats.size || F.threats.has(Number(i.value)); });
  const n = filterChips().length; $('filterCount').textContent = n ? String(n) : '';
  const fs = S.window ? filteredShips().length : null;
  $('filterSummary').textContent = fs === null ? '' : `${fmtN(fs)} / ${fmtN(S.window.ships.length)} 척`;
}
function readFilterPanel() {
  const gs = [...document.querySelectorAll('#fGrades input')].filter((i) => i.checked).map((i) => i.value);
  F.grades = gs.length === GRADES.length ? new Set() : (gs.length ? new Set(gs) : new Set(['-']));
  const ts = [...document.querySelectorAll('#fThreats input')].filter((i) => i.checked).map((i) => Number(i.value));
  F.threats = ts.length === 5 ? new Set() : (ts.length ? new Set(ts) : new Set([0]));
  F.kind = $('kindSel').value || null; F.nav = $('navSel').value || null; F.site = $('siteSel').value === '' ? null : Number($('siteSel').value);
  afterFilter();
}
function buildFilterPanel() {
  $('fGrades').innerHTML = GRADES.map((g) => `<label><input type="checkbox" value="${g}" checked> <span class="badge ${g}">${g === 'ok' || g === 'hold' ? '' : g}</span> ${GRADE_LABEL[g].replace(/^[HML] /, '')}</label>`).join('');
  $('fThreats').innerHTML = S.state.threats.map((t) => `<label title="${t.action} · 영향 ${t.impact}${t.implemented ? '' : ' · 탐지기 미구현'}"><input type="checkbox" value="${t.rank}" checked> ${t.rank} ${t.title}</label>`).join('');
  const kinds = S.state.msg_kinds.map((k) => `<option value="${k.key}">${k.label}</option>`).join('');
  $('kindSel').innerHTML += kinds; $('listKind').innerHTML += kinds;
  document.querySelectorAll('#fGrades input, #fThreats input').forEach((i) => i.addEventListener('change', readFilterPanel));
  $('kindSel').addEventListener('change', readFilterPanel); $('navSel').addEventListener('change', readFilterPanel); $('siteSel').addEventListener('change', readFilterPanel);
  $('filterClear').addEventListener('click', () => { clearFilter('all'); afterFilter(); });
  $('search').addEventListener('input', (e) => { F.search = e.target.value.trim(); renderSearchHits(); afterFilter(); });
  $('listSearch').addEventListener('input', (e) => { F.search = e.target.value.trim(); afterFilter(); });
  $('listKind').addEventListener('change', (e) => { F.kind = e.target.value || null; afterFilter(); });
  $('listState').addEventListener('change', (e) => { const v = e.target.value; F.grades = v === 'abn' ? new Set(['H', 'M', 'L']) : v ? new Set([v]) : new Set(); afterFilter(); });
}
function fillSiteSel() {
  const src = currentSource();
  $('siteSel').innerHTML = '<option value="">전체</option>' + src.sites.map((s) => `<option value="${s}">수신소 ${s}</option>`).join('');
}
function renderSearchHits() {
  const el = $('searchHits'); if (!F.search || !S.window) { el.innerHTML = ''; return; }
  const hits = S.window.ships.filter((s) => String(s.mmsi).includes(F.search)).slice(0, 30);
  el.innerHTML = hits.map((s) => `<div data-mmsi="${s.mmsi}"><span class="mono">${s.mmsi}</span> <span class="badge ${gradeOf(s)}">${GRADE_LABEL[gradeOf(s)]}</span> ${s.code || ''}</div>`).join('') || '<div class="muted">없음</div>';
  el.querySelectorAll('[data-mmsi]').forEach((d) => d.addEventListener('click', () => { openCard(Number(d.dataset.mmsi), true); }));
}

// ── ① 상황판 ────────────────────────────────────────────────────────────────
function gradeCounts(w) {
  const c = { H: 0, M: 0, L: 0, hold: 0, ok: 0 };
  for (const t of w.threat_cards) { if (typeof t.rank === 'number') c[t.impact] += t.n_ships; else c[t.rank] += t.n_ships; }
  return c;
}
function renderOverview() {
  const w = S.window; const c = gradeCounts(w);
  $('ovSentence').innerHTML = `지금 기간에 <b>${fmtN(w.n_ships)}척</b> 중 <b class="H">즉시 확인 ${fmtN(c.H)}척</b>, <b class="M">확인 필요 ${fmtN(c.M)}척</b>, <b class="L">참고 ${fmtN(c.L)}척</b>, <b class="hold">보류 ${fmtN(c.hold)}척</b>입니다. <small>나머지 ${fmtN(c.ok)}척은 정상 · 판정기 ${w.judge_label}</small>`;
  const tile = (g, title, desc) => `<div class="tile ${g}" data-g="${g}"><div class="t"><span class="badge ${g}">${g === 'hold' ? '보류' : g}</span> ${title}</div><div class="n">${fmtN(c[g])}<small> 척</small></div><div class="d">${desc}</div></div>`;
  $('ovTiles').innerHTML = tile('H', '즉시 확인', '영향 높음 — 위협 1 제어 · 위협 2 DOS') + tile('M', '확인 필요', '영향 중간 — 위협 3 스푸핑 · 위협 4 간섭') + tile('L', '참고', '영향 낮음 — 위협 5 오작동·설정') + tile('hold', '보류', '환경성 유실·미상·Unknown — 판정을 미룬 배');
  $('ovTiles').querySelectorAll('.tile').forEach((el) => el.addEventListener('click', () => { F.grades = new Set([el.dataset.g]); F.threats = new Set(); navigate('ships'); }));
  const top = w.ships.filter((s) => s.state === 'abn').sort(defaultCmp).slice(0, 5);
  $('ovTop').querySelector('tbody').innerHTML = top.map((s) => `<tr data-mmsi="${s.mmsi}"><td class="mono">${s.mmsi}</td><td><span class="badge ${s.impact}">${GRADE_LABEL[s.impact]}</span> <small>위협 ${s.threat}</small></td><td><b>${s.code}</b> <small>${codeDesc(s.code)}</small></td><td>${hhmm(s.t_last)}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">비정상 배 없음</td></tr>';
  $('ovTop').querySelectorAll('tr[data-mmsi]').forEach((tr) => tr.addEventListener('click', () => navigate('ship', tr.dataset.mmsi)));
  $('ovSite').innerHTML = w.site_cards.map((sc) => { const lv = levelOfMargin(sc.signal.margin_med_db);
    return `<b>수신소 ${sc.site}</b> · 받은 메시지 ${fmtN(sc.n_rows)}건 · 비정상 ${fmtPct(sc.abn_row_ratio)} (행) · ${fmtPct(sc.abn_ship_ratio)} (배) · 보류 ${fmtPct(sc.hold_row_ratio)} · 신호 종합 <span class="sig ${lv}"></span>${LEVEL_LABEL[lv] || '—'} (여유 중앙값 ${fmtDb(sc.signal.margin_med_db, 0)})`; }).join('<br>');
  $('threatCards').innerHTML = w.threat_cards.filter((t) => typeof t.rank === 'number').map((t) => {
    const on = F.threats.has(t.rank);
    const note = t.implemented === false ? '탐지기 미구현 — 0' : `${t.codes.length}개 코드`;
    return `<div class="card ${t.impact} ${on ? 'on' : ''}" data-rank="${t.rank}" title="${t.codes.join(', ')}"><div class="t"><b>위협 ${t.rank} ${t.title}</b><span class="badge ${t.impact}">${t.impact} ${t.action}</span></div><div class="n">${fmtN(t.n_ships)}<small> 척</small> <small>· 비정상 행 ${fmtN(t.n_rows)}</small></div><div class="d">${note}</div></div>`;
  }).join('');
  $('threatCards').querySelectorAll('.card').forEach((el) => el.addEventListener('click', () => { F.threats = new Set([Number(el.dataset.rank)]); F.grades = new Set(); navigate('ships'); }));
  const m = getMap('mini'); requestAnimationFrame(() => { m.updateSize(); fitShips(m, 0); });
}
function levelOfMargin(db) { return db === null || db === undefined ? 'none' : db < 0 ? 'bad' : db < 10 ? 'fair' : 'good'; }

// ── ② 지도 ──────────────────────────────────────────────────────────────────
function renderMapPage() {
  const m = getMap('main'); requestAnimationFrame(() => m.updateSize());
  renderLegend(); syncFilterUI();
  if (F.mmsi !== null && !$('shipCard').classList.contains('hidden')) { /* 열려 있음 */ } else if (F.mmsi !== null) openCard(F.mmsi, true);
}
function renderShips() {
  if (!S.shipsAt || !shipSrc) return;
  const allow = new Set(filteredShips().map((s) => s.mmsi));
  shipSrc.clear();
  const feats = [];
  for (const s of S.shipsAt.ships) {
    if (!allow.has(s.mmsi)) continue;
    const f = new ol.Feature({ geometry: new ol.geom.Point(ol.proj.fromLonLat([s.lon, s.lat])) }); f.set('ship', s); feats.push(f);
  }
  shipSrc.addFeatures(feats);
  $('mapCount').textContent = `${fmtN(feats.length)} 척 표시 (시점 직전 마지막 보고 · 색 = 기간 안 등급)`;
  if (!S.fitted[F.src] && feats.length && S.maps.main) { S.fitted[F.src] = true; fitShips(S.maps.main, 300); }
  if (S.page === 'overview' && S.maps.mini) fitShips(S.maps.mini, 0);
  if (S.page === 'signal' && S.maps.signal && !S.fitted['signal' + F.src] && feats.length) { S.fitted['signal' + F.src] = true; fitShips(S.maps.signal, 0); }
  syncFilterUI();
}
let shipsTimer = null;
function loadShipsAt() {
  clearTimeout(shipsTimer);
  shipsTimer = setTimeout(async () => {
    try {
      const r = await api('/api/ships_at', { src: F.src, t: tParam(), ...periodParams(), judge: judgeParam() });
      r.byMmsi = new Map(r.ships.map((s) => [s.mmsi, s])); S.shipsAt = r;
      renderShips();
      if (S.page === 'map' && F.mmsi !== null && !$('shipCard').classList.contains('hidden')) renderCard();
    } catch (e) { showError(e.message); }
  }, 150);
}
function openPanel(name) {
  S.panel = S.panel === name ? null : name;
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('hidden', p.id !== 'panel-' + S.panel));
  document.querySelectorAll('.toolbar .tb').forEach((b) => b.classList.toggle('on', b.dataset.panel === S.panel));
  if (S.panel === 'legend') renderLegend(); if (S.panel === 'search') renderSearchHits();
}
async function loadContour(key) {
  if (S.contourLoaded[key]) return;
  S.contourLoaded[key] = 'loading';
  try {
    S.loading++; setStatus(`${S.state.layers[key].label} 계산 중…`);
    const gj = await api('/api/contours', { src: F.src, layer: key, ...periodParams() });
    const fmt = new ol.format.GeoJSON({ dataProjection: 'EPSG:4326', featureProjection: 'EPSG:3857' });
    contourSrcs[key].clear(); contourSrcs[key].addFeatures(fmt.readFeatures(gj));
    S.contourMeta[key] = gj; S.contourLoaded[key] = true;
    for (const mn of ['main', 'signal']) if (S.layers[mn] && S.layers[mn][key]) S.layers[mn][key].changed();
    renderLegend(); renderSigLegend();
  } catch (e) { S.contourLoaded[key] = false; showError(e.message); }
  S.loading--; if (!S.loading) setStatus('');
}
function layerToggle(mapName, key, on) { getMap(mapName); S.layers[mapName][key].setVisible(on); if (on) loadContour(key); renderLegend(); renderSigLegend(); }
function contourLegendRows(mapName) {
  const rows = [];
  for (const k of ['margin', 'env']) {
    const L = S.layers[mapName] && S.layers[mapName][k]; if (!L || !L.getVisible()) continue;
    const meta = S.contourMeta[k]; const spec = S.state.layers[k];
    rows.push(`<div class="row" style="margin-top:4px"><b>${spec.label}</b> <small>${meta ? (meta.info.method === 'kriging' ? '정규 크리깅' : meta.info.method === 'idw' ? '⚠ 표본 적어 IDW 대체' : meta.info.method) + ` · 표본 칸 ${meta.info.n_samples}` : '계산 중'}</small></div>`);
    for (const lv of spec.levels) rows.push(`<div class="row"><span class="line" style="border-color:${LEVEL_COLORS[k][String(lv)]}"></span> ${lv > 0 ? '+' : ''}${lv} ${spec.unit}</div>`);
    rows.push(`<div class="row"><small>${spec.desc}</small></div>`);
  }
  for (const k of ['density', 'envloss']) {
    const L = S.layers[mapName] && S.layers[mapName][k]; if (!L || !L.getVisible()) continue;
    const spec = S.state.layers[k]; const meta = S.contourMeta[k];
    rows.push(`<div class="row" style="margin-top:4px"><span class="sw" style="background:${k === 'density' ? 'rgba(59,130,246,.6)' : 'rgba(244,114,182,.6)'}"></span><b>${spec.label}</b> <small>${meta ? `칸 ${meta.info.n_cells}` + (k === 'density' ? ` · 최대 ${meta.info.max}` : ` · ENV_LOSS 행 ${meta.info.n_envloss_rows}`) : '계산 중'}</small></div>`);
    rows.push(`<div class="row"><small>${spec.desc}</small></div>`);
  }
  if (rows.length) rows.push(`<div class="caveat">⚠ ${S.state.signal_basis.caveat}</div>`);
  return rows;
}
function renderLegend() {
  const el = $('legend'); const rows = [];
  rows.push('<div class="row"><b>배 색 = 기간 안 등급</b></div>');
  for (const [c, meaning] of Object.entries(mapping.meaning || {})) rows.push(`<div class="row" title="${meaning}"><img src="/static/icons/vessel_${c}.png" width="20" height="10"> ${meaning}</div>`);
  rows.push(`<div class="row"><small>반투명 = 시점에서 ${(S.state.signal_basis.stale_s / 60) | 0}분 넘게 지난 마지막 보고</small></div>`);
  rows.push('<div class="row" style="margin-top:4px"><b>방향 = 선수 기본</b></div>');
  rows.push('<div class="row"><small>선수 HDG → 침로 COG → 항적 추정(30 m) → 기간 안 마지막 유효값 → 북쪽 고정</small></div>');
  rows.push('<div class="row"><span style="font-weight:700">?</span> <small>방향 미상 — 북쪽을 향하게 두고 ? 표식 (원형 점 없음)</small></div>');
  if (S.shipsAt) { const cnt = {}; for (const s of S.shipsAt.ships) { const k = CoastRotation.shipCourse(s).source; cnt[k] = (cnt[k] || 0) + 1; }
    rows.push(`<div class="row"><small>이 시점 출처: 선수 ${cnt.heading || 0} · 침로 ${cnt.cog || 0} · 항적 ${cnt.track || 0} · 마지막값 ${cnt.last || 0} · 미상 ${cnt.none || 0} 척</small></div>`); }
  rows.push(...contourLegendRows('main'));
  if (!S.state.tiles_ok) rows.push('<div class="row"><small>타일 서버 없음(COAST_TILE_URL) — 항행수역 격자만 배경으로</small></div>');
  el.innerHTML = `<div class="legend">${rows.join('')}</div>`;
}
// 시점 재생 — 1초마다 1분
function setT(t) { F.t = clampT(t); $('tslider').value = minutesBetween(F.t0, F.t); $('tlabel').textContent = F.t.slice(0, 16).replace('T', ' '); syncHash(); loadShipsAt(); }
function stopPlay() { if (S.playing) { clearInterval(S.playing); S.playing = null; $('tPlay').textContent = '▶'; } }
function togglePlay() {
  if (S.playing) { stopPlay(); return; }
  if (F.t >= F.t1) setT(F.t0);
  $('tPlay').textContent = '❚❚';
  S.playing = setInterval(() => { if (F.t >= F.t1) { stopPlay(); return; } setT(addMinutes(F.t, 1)); }, 1000);
}
// 배 카드 (오른쪽 미끄러져 나옴)
async function getDetail(mmsi) {
  const key = `${F.src}|${F.t0}|${F.t1}|${judgeParam()}|${mmsi}`;
  if (!S.detailCache.has(key)) S.detailCache.set(key, api('/api/ship', { src: F.src, mmsi, ...periodParams(), judge: judgeParam() }));
  return S.detailCache.get(key);
}
async function openCard(mmsi, center) {
  F.mmsi = mmsi; shipSrc.changed(); syncHash();
  const card = $('shipCard'); card.classList.remove('hidden'); card.innerHTML = `<button class="close" id="cardClose">×</button><p class="muted">MMSI ${mmsi} 불러오는 중…</p>`;
  $('cardClose').addEventListener('click', closeCard);
  try { S.detail = await getDetail(mmsi); } catch (e) { card.innerHTML = `<button class="close" id="cardClose">×</button><p class="muted">${e.message}</p>`; $('cardClose').addEventListener('click', closeCard); return; }
  if (F.mmsi !== mmsi) return;
  renderCard(); renderTrack(trackSrc);
  const s = S.shipsAt && S.shipsAt.byMmsi.get(mmsi);
  if (center && S.maps.main) { const p = s ? [s.lon, s.lat] : (S.detail.at_last ? [S.detail.at_last.lon, S.detail.at_last.lat] : null); if (p) S.maps.main.getView().animate({ center: ol.proj.fromLonLat(p), zoom: Math.max(S.maps.main.getView().getZoom(), 12), duration: 300 }); }
}
function closeCard() { F.mmsi = null; $('shipCard').classList.add('hidden'); trackSrc.clear(); shipSrc.changed(); syncHash(); }
function renderCard() {
  const d = S.detail; const s = S.shipsAt && S.shipsAt.byMmsi.get(d.mmsi);
  $('shipCard').innerHTML = `<button class="close" id="cardClose">×</button>` + summaryHtml(d, s, true);
  $('cardClose').addEventListener('click', closeCard);
}
// 카드/상세 요약 — 지도 카드와 배 상세 위쪽이 같은 내용
function summaryHtml(d, s, withLink) {
  const sm = d.summary; const t = threatOf(sm.threat);
  const pos = s || d.at_last;     // 시점 스냅샷이 있으면 그것, 없으면 기간 안 마지막 위치 보고
  const grade = sm.state === 'abn' ? `<span class="badge ${sm.impact}">${sm.impact} ${t ? t.action : ''}</span> 위협 ${sm.threat} ${t ? t.title : ''}` : `<span class="badge ${sm.state}">${STATE_LABEL[sm.state]}</span>${sm.state === 'hold' ? ' 환경성 유실·미상·Unknown' : ' 판정 없음'}`;
  const age = s ? (s.age_s > 600 ? `${Math.round(s.age_s / 60)}분 전` : `${s.age_s}초 전`) : '';
  const c = d.signal_cards;
  return `<h3>MMSI <span class="mono">${sm.mmsi}</span> <small>${hhmm(sm.t_first)} ~ ${hhmm(sm.t_last)} · 판정기 ${S.window.judge_label}</small></h3>` +
    `<dl class="kv"><dt>등급</dt><dd>${grade}</dd>` +
    `<dt>대표 코드</dt><dd>${sm.code ? `<b>${sm.code}</b> ${sm.kind_of_code ? '(' + sm.kind_of_code + ')' : ''}<br><small>${codeDesc(sm.code)}</small>` : '—'}</dd>` +
    `<dt>속력 / 방향</dt><dd>${pos ? `${pos.sog === null || pos.sog === undefined ? '속력 —' : pos.sog.toFixed(1) + ' kn'} · ${CoastRotation.courseText(pos)}` : '위치 보고 없음'}</dd>` +
    `<dt>마지막 보고</dt><dd>${pos ? `${hhmm(pos.t)} ${age ? '(' + age + (s.age_s > 600 ? ' · 반투명' : '') + ')' : ''}` : '—'}${s ? ` · 주변 ${s.near_ships}척/3 km` : ''}</dd>` +
    `<dt>이 기간 비정상</dt><dd><b>${fmtPct(sm.abn_ratio)}</b> = ${fmtN(sm.n_abn)} / ${fmtN(sm.n_rows)} 행 · 보류 ${fmtN(sm.n_hold)} 행</dd>` +
    `<dt>신호</dt><dd><span class="level ${c.level || ''}">${c.level_label}</span> <small>수신 여유 ${fmtDb(c.margin_db, 0)} (RSSI 중앙값 − (${c.basis.sens_dbm} dBm))</small></dd></dl>` +
    `<h3 style="margin-top:8px">신호 원인 <small>저하 몫 %</small></h3>` + causeBars(c) +
    (withLink ? `<p><a href="${buildHash('ship', String(sm.mmsi))}">자세히 →</a> <small>시간별·코드별·메시지 종류</small></p>` : '');
}
function causeBars(c) {
  return c.cards.map((k) => `<div class="bar ${k.flag ? 'flag' : ''}"><span class="lab">${k.label}${k.flag ? ' ⚑' : ''}</span><div class="trk"><div class="fill" style="width:${(k.share * 100).toFixed(0)}%;background:${k.key === 'tx' ? 'var(--M)' : k.key === 'env' ? 'var(--L)' : k.key === 'cong' ? 'var(--hold)' : '#64748b'}"></div></div><span class="val">${(k.share * 100).toFixed(0)}%</span></div><p class="cardtext">${k.text}${k.db !== null && k.db !== undefined ? ' · 귀속 ' + fmtDb(k.db) : ''}</p>`).join('');
}
function renderTrack(src) {
  src.clear();
  if (!S.detail || !S.detail.track.length) return;
  const pts = S.detail.track.map((p) => ol.proj.fromLonLat([p[1], p[0]]));
  src.addFeature(new ol.Feature({ geometry: new ol.geom.LineString(pts) }));
  S.detail.track.forEach((p, i) => { if (p[3] !== 'ok' || i % 10 === 0) { const f = new ol.Feature({ geometry: new ol.geom.Point(pts[i]) }); f.set('state', p[3]); src.addFeature(f); } });
}

// ── ③ 선박 목록 · 배 상세 ────────────────────────────────────────────────────
const COLS = [
  { key: 'mmsi', label: 'MMSI' }, { key: 'threat', label: '위협', num: true }, { key: 'impact', label: '영향' }, { key: 'code', label: '대표 코드' },
  { key: 'kind_of_code', label: '갈래' }, { key: 'abn_ratio', label: '비정상 비율(행)', num: true }, { key: 't_last', label: '마지막 보고' }, { key: 'signal', label: '신호' },
];
const IMP_ORD = { H: 0, M: 1, L: 2 };
function defaultCmp(a, b) {
  const ia = a.impact ? IMP_ORD[a.impact] : (a.state === 'hold' ? 3 : 4), ib = b.impact ? IMP_ORD[b.impact] : (b.state === 'hold' ? 3 : 4);
  if (ia !== ib) return ia - ib;
  if ((a.threat || 9) !== (b.threat || 9)) return (a.threat || 9) - (b.threat || 9);
  return b.abn_ratio - a.abn_ratio;
}
function shipRatio(s) { if (F.kind && s.kinds && s.kinds[F.kind] && s.kinds[F.kind][0] > 0) return s.kinds[F.kind][1] / s.kinds[F.kind][0]; return s.abn_ratio; }
function renderList() {
  renderFilterBar($('filterBar'));
  const ships = filteredShips(); const { key, dir } = S.sort;
  ships.sort((a, b) => {
    if (key === 'default') return defaultCmp(a, b);
    let va = key === 'signal' ? (a.signal.margin_db ?? -999) : key === 'abn_ratio' ? shipRatio(a) : a[key];
    let vb = key === 'signal' ? (b.signal.margin_db ?? -999) : key === 'abn_ratio' ? shipRatio(b) : b[key];
    if (key === 'impact') { va = a.impact ? IMP_ORD[a.impact] : 9; vb = b.impact ? IMP_ORD[b.impact] : 9; }
    if (va === null || va === undefined) va = key === 'threat' ? 99 : ''; if (vb === null || vb === undefined) vb = key === 'threat' ? 99 : '';
    return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
  });
  $('listCount').textContent = `${fmtN(ships.length)} / ${fmtN(S.window.ships.length)} 척 (기간 합산 · 판정기 ${S.window.judge_label}) · 머리 클릭 = 정렬`;
  $('shipTable').querySelector('thead').innerHTML = '<tr>' + COLS.map((c) => `<th class="${c.num ? 'num' : ''} ${S.sort.key === c.key ? 'sorted' : ''}" data-key="${c.key}">${c.label}${S.sort.key === c.key ? (dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('') + '</tr>';
  $('shipTable').querySelectorAll('th').forEach((th) => th.addEventListener('click', () => {
    const k = th.dataset.key;
    if (S.sort.key === k) S.sort.dir = -S.sort.dir; else { S.sort.key = k; S.sort.dir = (k === 'abn_ratio' || k === 'signal' || k === 't_last') ? -1 : 1; }
    renderList();
  }));
  $('shipTable').querySelector('tbody').innerHTML = ships.slice(0, 1500).map((s) => {
    const g = gradeOf(s);
    return `<tr data-mmsi="${s.mmsi}" data-pos="${s.kinds && s.kinds.pos ? s.kinds.pos[0] : 0}"><td class="mono">${s.mmsi}</td><td class="num">${s.threat ?? '—'}</td><td><span class="badge ${g}">${GRADE_LABEL[g]}</span></td>` +
      `<td title="${codeDesc(s.code)}">${s.code || '—'}</td><td>${s.kind_of_code || ''}</td><td class="num">${fmtPct(shipRatio(s))}</td><td>${hhmm(s.t_last)}</td>` +
      `<td><span class="sig ${s.signal.level || 'none'}"></span>${LEVEL_LABEL[s.signal.level] || '—'} <small>${fmtDb(s.signal.margin_db, 0)}</small></td></tr>`;
  }).join('');
  $('shipTable').querySelectorAll('tr[data-mmsi]').forEach((tr) => tr.addEventListener('click', () => navigate('ship', tr.dataset.mmsi)));
}
async function renderShipPage() {
  const mmsi = Number(S.param); const el = $('shipDetail');
  if (!mmsi) { el.innerHTML = '<p class="muted">MMSI 가 없다 — 목록에서 배를 고른다.</p>'; return; }
  const keep = F.mmsi; F.mmsi = mmsi; $('toMap').href = buildHash('map'); F.mmsi = keep; $('backList').href = buildHash('ships');
  el.innerHTML = `<p class="muted">MMSI ${mmsi} 불러오는 중…</p>`;
  let d; try { d = await getDetail(mmsi); } catch (e) { el.innerHTML = `<p class="muted">${e.message}</p>`; return; }
  if (S.page !== 'ship' || Number(S.param) !== mmsi) return;
  S.detail = d; const s = S.shipsAt && S.shipsAt.byMmsi.get(mmsi); const sm = d.summary;
  let h = `<section class="box">${summaryHtml(d, s, false)}</section>`;
  h += `<section class="box"><h2>항적 <small>기간 안 위치 보고 ${fmtN(d.n_track_rows)} 점 — 빨강 비정상 · 분홍 보류 · 초록 정상</small></h2><div id="map-ship" class="shipmap"></div></section>`;
  h += `<section class="box"><h2>시간별 판정 <small>시간대마다 행 수 — 비정상(빨강) · 보류(분홍) · 정상(회색)</small></h2>${hourlyHtml(d.hourly)}` +
    `<h2 style="margin-top:10px">메시지 종류별 건수</h2><table class="plain"><tr><th>종류</th><th class="num">행</th><th class="num">비정상</th><th class="num">보류</th></tr>` +
    d.kinds.map((k) => `<tr><td>${k.label}</td><td class="num">${fmtN(k.n)}</td><td class="num">${k.n ? fmtPct(k.abn / k.n) : '— (자리)'}</td><td class="num">${k.n ? fmtPct(k.hold / k.n) : '—'}</td></tr>`).join('') + '</table></section>';
  h += `<section class="box wide"><h2>코드별 비정상 행 수 <small>n = 양성 행 · 대표 = 그 코드가 대표인 행 · 한 줄 설명</small></h2><table><tr><th>코드</th><th>뜻</th><th>위협</th><th>영향</th><th class="num">n</th><th class="num">대표</th><th>갈래</th></tr>` +
    (d.codes.map((c) => `<tr><td><b>${c.code}</b></td><td><small>${c.desc}</small></td><td>${c.threat} ${c.threat_title || ''}</td><td><span class="badge ${c.impact}">${c.impact} ${c.action}</span></td><td class="num">${fmtN(c.n)}</td><td class="num">${fmtN(c.n_primary)}</td><td><small>${Object.entries(c.kinds).map(([a, kv]) => a + ': ' + Object.entries(kv).map(([k, v]) => `${k} ${v}`).join(', ')).join(' · ')}</small></td></tr>`).join('') || '<tr><td colspan="7" class="muted">코드 없음(정상)</td></tr>') + '</table>' +
    `<p class="cap">신호 원인 카드의 몫 = dB 귀속의 절댓값 비율(잔차 평균 ${fmtDb(d.signal_cards.rssi_resid_mean_db)} · SNR 잔차 ${fmtDb(d.signal_cards.snr_resid_mean_db)}). 식·근거: <a href="/docs/SIGNAL_QUALITY_BASIS.md" target="_blank">docs/SIGNAL_QUALITY_BASIS.md</a></p></section>`;
  el.innerHTML = h;
  // 작은 지도 + 항적 + 배 아이콘
  delete S.maps.ship; const m = getMap('ship');
  renderTrack(trackSrc); shipOneSrc.clear();
  const pos = s || d.at_last;
  if (pos) { const f = new ol.Feature({ geometry: new ol.geom.Point(ol.proj.fromLonLat([pos.lon, pos.lat])) }); f.set('ship', { ...sm, ...pos, mmsi: sm.mmsi, age_s: s ? s.age_s : 0 }); shipOneSrc.addFeature(f); }
  requestAnimationFrame(() => { m.updateSize(); if (trackSrc.getFeatures().length) m.getView().fit(trackSrc.getExtent(), { padding: [20, 20, 20, 20], maxZoom: 13 }); else if (pos) m.getView().setCenter(ol.proj.fromLonLat([pos.lon, pos.lat])); });
}
function hourlyHtml(rows) {
  const mx = Math.max(1, ...rows.map((r) => r.n)); const HPX = 110;
  const cols = rows.map((r) => { const okn = r.n - r.abn - r.hold; const h = (v) => (HPX * v / mx).toFixed(1) + 'px';
    return `<div class="col" title="${hhmm(r.hour)}시 — ${r.n} 행 · 비정상 ${r.abn} · 보류 ${r.hold}"><div class="abn" style="height:${h(r.abn)}"></div><div class="hold" style="height:${h(r.hold)}"></div><div class="okn" style="height:${h(okn)}"></div></div>`; }).join('');
  return `<div class="hourly">${cols}</div><div class="hourlyAxis"><span>${rows.length ? rows[0].hour.slice(11, 13) + '시' : ''}</span><span>최대 ${fmtN(mx)} 행/시간</span><span>${rows.length ? rows[rows.length - 1].hour.slice(11, 13) + '시' : ''}</span></div>`;
}

// ── ④ 수신 현황 — 한 문장 + 가로 누적 막대 3개 + 표 ───────────────────────────
function hbar(label, sub, segs, total, right, cls) {
  const tr = segs.filter((g) => g.n > 0).map((g) => `<div class="seg ${g.cls} ${g.on ? 'on' : ''}" data-act="${g.act || ''}" style="width:${(100 * g.n / (total || 1)).toFixed(2)}%" title="${g.title}">${(g.n / (total || 1)) > 0.12 ? g.text || '' : ''}</div>`).join('');
  return `<div class="hbar ${cls || ''} ${total ? '' : 'empty'}"><div class="lab">${label}<small>${sub || ''}</small></div><div class="trk">${tr}</div><div class="val">${right}</div></div>`;
}
function renderFlow() {
  const w = S.window; const topo = w.topology; const tb = topo.tables; const tot = topo.total;
  renderFilterBar($('flowFilterBar'));
  $('flowSentence').innerHTML = tb.by_site.map((r) => `수신소 ${r.site}에 <b>${fmtN(r.n_rows)}건</b>이 들어왔고 그중 <b class="H">${fmtPct(r.abn / (r.n_rows || 1))}가 비정상</b>, <b class="hold">${fmtPct(r.hold / (r.n_rows || 1))}가 보류</b>입니다.`).join(' ') +
    ` <small>배 ${fmtN(tot.n_ships)}척 · 판정기 ${w.judge_label} · 행 = 메시지 1건</small>`;
  const stSeg = (r, act) => [{ cls: 'ok', n: r.n_rows - r.abn - r.hold, text: '정상', act: act + ':ok', on: F.grades.size === 1 && F.grades.has('ok'), title: `정상 ${fmtN(r.n_rows - r.abn - r.hold)} 행` },
    { cls: 'abn', n: r.abn, text: `비정상 ${fmtPct(r.abn / (r.n_rows || 1), 0)}`, act: act + ':abn', on: F.grades.size === 3 && ['H', 'M', 'L'].every((g) => F.grades.has(g)), title: `비정상 ${fmtN(r.abn)} 행` },
    { cls: 'hold', n: r.hold, text: '보류', act: act + ':hold', on: F.grades.size === 1 && F.grades.has('hold'), title: `보류 ${fmtN(r.hold)} 행` }];
  $('barSite').innerHTML = tb.by_site.map((r) => hbar(`수신소 ${r.site}`, F.site === r.site ? '필터 중' : '', stSeg(r, `site:${r.site}`), r.n_rows, `<b>${fmtN(r.n_rows)}</b> 건 · ${fmtN(r.n_ships)} 척<br><small>비정상 ${fmtPct(r.abn / (r.n_rows || 1))} · 보류 ${fmtPct(r.hold / (r.n_rows || 1))}</small>`)).join('');
  const mxKind = Math.max(1, ...tb.by_kind.map((r) => r.n_rows));
  $('barKind').innerHTML = tb.by_kind.map((r) => { const segs = stSeg(r, `kind:${r.kind}`); const share = r.n_rows / (tot.n_rows || 1);
    // 종류마다 막대 길이 = 전체 대비 비율(가장 큰 종류가 100 %), 안의 조각 = 정상/비정상/보류
    return hbar(r.label, F.kind === r.kind ? '필터 중' : (r.kind === 'vde' ? '0건 — 자리만' : fmtPct(share) + ' 차지'), segs.map((g) => ({ ...g, n: g.n * (r.n_rows / mxKind) })), r.n_rows || 1,
      r.n_rows ? `<b>${fmtN(r.n_rows)}</b> 건 · ${fmtN(r.n_ships)} 척<br><small>비정상 ${fmtPct(r.abn / r.n_rows)} · 보류 ${fmtPct(r.hold / r.n_rows)}</small>` : '<b>0</b> 건 — 자리만'); }).join('');
  const cards = w.threat_cards; const mxT = Math.max(1, ...cards.map((c) => c.n_ships));
  $('barThreat').innerHTML = cards.filter((c) => c.rank !== 'ok').map((c) => { const isT = typeof c.rank === 'number'; const on = isT ? F.threats.has(c.rank) : (F.grades.size === 1 && F.grades.has('hold'));
    return hbar(isT ? `위협 ${c.rank} ${c.title}` : '보류', isT ? `${c.impact} ${c.action}${c.implemented === false ? ' · 탐지기 미구현' : ''}` : '환경성 유실·미상·Unknown',
      [{ cls: isT ? c.impact : 'hold', n: c.n_ships, text: `${fmtN(c.n_ships)} 척`, act: isT ? `threat:${c.rank}` : 'grade:hold', on, title: `${fmtN(c.n_ships)} 척 · 비정상 행 ${fmtN(c.n_rows)}` }], mxT,
      `<b>${fmtN(c.n_ships)}</b> 척<br><small>${isT ? '비정상 행 ' + fmtN(c.n_rows) : '보류 행 ' + fmtN(c.n_rows)}</small>`); }).join('') +
    hbar('정상', '판정 없음', [{ cls: 'ok', n: cards.find((c) => c.rank === 'ok').n_ships, text: '', act: 'grade:ok', on: F.grades.size === 1 && F.grades.has('ok'), title: '정상 배' }], mxT, `<b>${fmtN(cards.find((c) => c.rank === 'ok').n_ships)}</b> 척`);
  document.querySelectorAll('#page-flow .seg[data-act]').forEach((el) => el.addEventListener('click', () => flowClick(el.dataset.act)));
  $('flowTop').innerHTML = '<table><tr><th>MMSI</th><th>위협</th><th>영향</th><th>대표 코드 · 뜻</th><th class="num">비정상(행)</th><th>마지막 보고</th></tr>' +
    tb.top_ships.map((s) => `<tr data-mmsi="${s.mmsi}"><td class="mono">${s.mmsi}</td><td>${s.threat}</td><td><span class="badge ${s.impact}">${GRADE_LABEL[s.impact]}</span></td><td>${s.code} <small>${codeDesc(s.code)}</small></td><td class="num">${fmtPct(s.abn_ratio)}</td><td>${hhmm(s.t_last)}</td></tr>`).join('') + '</table>';
  $('flowTop').querySelectorAll('tr[data-mmsi]').forEach((tr) => tr.addEventListener('click', () => navigate('ship', tr.dataset.mmsi)));
}
function flowClick(act) {
  const [kind, a, b] = act.split(':');
  const toggleGrade = (st) => { const want = st === 'abn' ? ['H', 'M', 'L'] : [st]; const same = F.grades.size === want.length && want.every((g) => F.grades.has(g)); F.grades = same ? new Set() : new Set(want); };
  if (kind === 'site') { const s = Number(a); F.site = F.site === s ? null : s; toggleGrade(b); }
  else if (kind === 'kind') { F.kind = F.kind === a ? null : a; toggleGrade(b); }
  else if (kind === 'threat') { const r = Number(a); F.threats = F.threats.has(r) && F.threats.size === 1 ? new Set() : new Set([r]); F.grades = new Set(); }
  else if (kind === 'grade') { toggleGrade(a); F.threats = new Set(); }
  afterFilter();
}

// ── ⑤ 신호 품질 ──────────────────────────────────────────────────────────────
async function renderSignal() {
  const m = getMap('signal'); requestAnimationFrame(() => { m.updateSize(); if (!S.fitted['signal' + F.src] && shipSrc.getFeatures().length) { S.fitted['signal' + F.src] = true; fitShips(m, 0); } });
  for (const [id, key] of [['sgMargin', 'margin'], ['sgEnv', 'env'], ['sgDensity', 'density'], ['sgEnvloss', 'envloss']]) { const on = $(id).checked; S.layers.signal[key].setVisible(on); if (on) loadContour(key); }
  S.layers.signal.ships.setVisible($('sgShips').checked);
  renderSigLegend(); renderSigWhy();
  if (!S.signal || S.signal._key !== `${F.src}|${F.t0}|${F.t1}|${judgeParam()}`) {
    $('sigSentence').textContent = '신호 품질 집계 중…'; $('sigCards').innerHTML = '';
    try { const r = await api('/api/signal_summary', { src: F.src, ...periodParams(), judge: judgeParam() }); r._key = `${F.src}|${F.t0}|${F.t1}|${judgeParam()}`; S.signal = r; }
    catch (e) { $('sigSentence').textContent = e.message; return; }
    if (S.page !== 'signal') return;
  }
  const r = S.signal; const lv = r.levels; const sh = Object.fromEntries(r.cards.map((c) => [c.key, c.share]));
  $('sigSentence').innerHTML = `이 기간 <b>${fmtN(r.n_ships)}척</b> 중 신호 <b style="color:var(--good)">좋음 ${fmtN(lv.good)}</b> · <b style="color:var(--fair)">보통 ${fmtN(lv.fair)}</b> · <b style="color:var(--bad)">나쁨 ${fmtN(lv.bad)}척</b>입니다 (수신 여유 중앙값 ${fmtDb(r.margin_med_db, 0)} · 감도 미만 행 ${fmtN(r.rows_below_sens)}). ` +
    `들리는 세기가 떨어진 몫은 해역 환경 ${fmtPct(sh.env, 0)} · 송신기 ${fmtPct(sh.tx, 0)} · 혼잡 ${fmtPct(sh.cong, 0)} · 미상 ${fmtPct(sh.unknown, 0)}.`;
  const meta = { tx: ['M', `기준 ${r.basis.tx_se} SE 아래거나 룰 TX_WEAK`], env: ['L', `기준 환경 잔차 ≤ −${r.basis.env_threshold_db} dB`], cong: ['hold', `기준 슬롯 사용 ≥ ${(r.basis.slot_flag * 100) | 0} % (반경 ${r.basis.near_km} km)`], unknown: ['ok', '기준 없음'] };
  $('sigCards').innerHTML = r.cards.map((c) => `<div class="tile ${meta[c.key][0]} sigcard" data-key="${c.key}"><div class="t">${c.label}</div><div class="n">${fmtPct(c.share, 0)}</div><div class="d">${c.text}</div><div class="d">으뜸 원인인 배 <b>${fmtN(c.n_dominant)}척</b> · ⚑ ${fmtN(c.n_flag)}척 · ${meta[c.key][1]}</div></div>`).join('');
}
function renderSigLegend() {
  if (!S.layers.signal) return;
  const rows = contourLegendRows('signal');
  rows.push(`<div class="row"><small>3단계: 나쁨 &lt; 0 dB · 보통 0~${S.state.signal_basis.prot_db} · 좋음 ≥ ${S.state.signal_basis.prot_db} (수신 여유 = RSSI 중앙값 − (${S.state.signal_basis.sens_dbm} dBm))</small></div>`);
  $('sigLegend').innerHTML = `<div class="legend">${rows.join('')}</div>`;
}
function renderSigWhy() {
  const b = S.state.signal_basis;
  const lines = [
    `수신 여유 = RSSI − (${b.sens_dbm} dBm). −107 dBm 은 ITU-R M.1371-6 이 요구하는 최소 수신기 감도(PER 20 %) — 이 아래는 수신 자체가 불안.`,
    `등고선 0 / 10 / 20 dB. 10 dB 는 같은 권고의 동일 채널 보호비 — 0~10 은 간섭 하나면 끊길 여유, ≥ 10 은 보호비만큼 여유.`,
    `20 dB 는 표준 값이 아니라 "넉넉" 눈금(설계값).`,
    `환경 잔차 = 관측 RSSI − 거리 기대값(ml_all 거리 모델, 참조 ITU-R P.1546 해상 경로). 음수가 큰 곳 = 가림·음영 의심.`,
    `가림 의심 문턱 −${b.env_threshold_db} dB 는 ml_all 룰의 rssi_resid_db 와 같은 값(설계값).`,
    `점값 → 0.5 km 칸(배 ${3}척 이상)의 중앙값 → 정규 크리깅(지수 반분산)으로 격자 보간 → marching squares 로 등고선.`,
    `표본점이 적으면 IDW 로 대체하고 범례에 적는다. 가장 가까운 표본점이 ${b.near_km} km 보다 멀면 그리지 않고, 육지(sea_mask 밖)는 비운다.`,
    `생존 편향: 수신된 메시지만 보이므로 아주 나쁜 곳은 값이 낮게 나오는 게 아니라 점이 없다 — 보고 밀도·ENV_LOSS 층을 같이 켜서 "비어 있는 곳"을 본다.`,
    `원인 카드 몫 = dB 귀속의 절댓값 비율: 해역 환경(그 자리의 등고선 값) · 송신기(같은 자리 다른 배보다 약한 정도) · 혼잡(세기로 설명 안 되는 SNR 손실) · 미상(나머지).`,
    `⚑ 기준: 송신기 ${2.5} SE 또는 룰 TX_WEAK · 해역 환경 −${b.env_threshold_db} dB · 혼잡 슬롯 사용 50 %(설계값). 3단계(좋음/보통/나쁨)는 수신 여유로만 정한다.`,
  ];
  $('sigWhy').innerHTML = lines.map((l) => `<li>${l}</li>`).join('');
}

// ── 데이터 흐름 ───────────────────────────────────────────────────────────────
async function loadWindow() {
  setStatus('기간 합산 중…');
  S.contourLoaded = {}; S.contourMeta = {}; S.detailCache = new Map(); S.signal = null;
  for (const k of Object.keys(contourSrcs)) contourSrcs[k].clear();
  try {
    S.window = await api('/api/window', { src: F.src, ...periodParams(), judge: judgeParam() });
    setStatus(`합산 ${fmtN(S.window.n_rows)} 행 · ${fmtN(S.window.n_ships)} 척 (${S.window.seconds}s)`);
  } catch (e) { showError(e.message); setStatus(''); return; }
  updateCondButton(); renderPage();
  for (const mn of ['main', 'signal']) for (const k of ['margin', 'env', 'density', 'envloss']) if (S.layers[mn] && S.layers[mn][k] && S.layers[mn][k].getVisible()) loadContour(k);
}

async function init() {
  try { S.state = await api('/api/state'); } catch (e) { showError(e.message); return; }
  mapping = S.state.icon_mapping; POLL_MS = S.state.poll_ms || 0;
  S.state.msg_kinds.forEach((k) => { KIND_LABEL[k.key] = k.label; });
  if (!S.state.sources.length) { showError('데이터 소스가 없습니다 — AISINT_ML_ALL_ROOT 의 output/datagen/risk_map_*.parquet 를 확인'); return; }
  $('src').innerHTML = S.state.sources.map((s) => `<option value="${s.id}">${s.label}</option>`).join('');
  buildFilterPanel();
  F.src = S.state.sources[0].id; applySourceDefaults();
  ensureSources();
  window.coast = { F, S, maps: S.maps, get shipSrc() { return shipSrc; }, fitShips, navigate, route, buildHash, gradeCounts };   // 검사·캡처용
  // 조건 팝오버
  $('condBtn').addEventListener('click', (e) => { e.stopPropagation(); $('condPop').classList.toggle('hidden'); });
  document.addEventListener('click', (e) => { if (!$('condPop').contains(e.target) && e.target !== $('condBtn')) $('condPop').classList.add('hidden'); });
  $('src').addEventListener('change', (e) => { F.src = e.target.value; applySourceDefaults(); fillSiteSel(); setCondUI(); closeCardSilently(); condChanged(); if (S.maps.main) S.maps.main.getView().animate({ center: ol.proj.fromLonLat(F.src === 'ds015' ? [128.9, 35.0] : [129.1, 35.05]), zoom: 9, duration: 300 }); });
  $('judge').addEventListener('change', (e) => { F.judge = e.target.value; condChanged(); });
  $('truth').addEventListener('change', (e) => { F.truth = e.target.checked; condChanged(); });
  $('applyPeriod').addEventListener('click', () => { const a = fromLocalInput($('t0').value), b = fromLocalInput($('t1').value); if (!a || !b) return; F.t0 = a < b ? a : b; F.t1 = a < b ? b : a; F.t = F.t1; setCondUI(); condChanged(); });
  $('resetPeriod').addEventListener('click', () => { const s = currentSource(); F.t0 = s.t_min; F.t1 = s.t_max; F.t = s.t_max; setCondUI(); condChanged(); });
  // 메뉴 — 조건·필터를 실은 해시로
  document.querySelectorAll('#menu a').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); navigate(a.dataset.page); }));
  // 지도 툴바·시점
  document.querySelectorAll('.toolbar .tb').forEach((b) => b.addEventListener('click', () => openPanel(b.dataset.panel)));
  for (const [id, key] of [['lyMargin', 'margin'], ['lyEnv', 'env'], ['lyDensity', 'density'], ['lyEnvloss', 'envloss']]) $(id).addEventListener('change', (ev) => layerToggle('main', key, ev.target.checked));
  $('lyTrack').addEventListener('change', (ev) => { getMap('main'); S.layers.main.track.setVisible(ev.target.checked); });
  $('tslider').addEventListener('input', (e) => { stopPlay(); setT(addMinutes(F.t0, Number(e.target.value))); });
  $('tPrev').addEventListener('click', () => { stopPlay(); setT(addMinutes(F.t, -1)); });
  $('tNext').addEventListener('click', () => { stopPlay(); setT(addMinutes(F.t, 1)); });
  $('tPlay').addEventListener('click', togglePlay);
  $('miniGo').parentElement.addEventListener('click', () => navigate('map'));
  for (const [id, key] of [['sgMargin', 'margin'], ['sgEnv', 'env'], ['sgDensity', 'density'], ['sgEnvloss', 'envloss']]) $(id).addEventListener('change', (ev) => layerToggle('signal', key, ev.target.checked));
  $('sgShips').addEventListener('change', (ev) => { getMap('signal'); S.layers.signal.ships.setVisible(ev.target.checked); });
  window.addEventListener('hashchange', route);
  fillSiteSel();
  await route();
  // 폴링 훅 — LiveProvider 가 붙어 poll_ms > 0 이면 변화분만 받아 지도를 갱신한다
  if (POLL_MS > 0) setInterval(async () => { try { const r = await api('/api/changes', { src: F.src, since: F.t }); if (r.delta) loadShipsAt(); } catch (e) { /* 조용히 */ } }, POLL_MS);
}
function closeCardSilently() { F.mmsi = null; $('shipCard').classList.add('hidden'); if (trackSrc) trackSrc.clear(); }
window.addEventListener('resize', () => { const m = S.maps[S.page === 'overview' ? 'mini' : S.page]; if (m) m.updateSize(); });
init();
