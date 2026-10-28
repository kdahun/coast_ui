# 2026-10-27 coast_ui 1차 — 한 것·검사·캡처·못 한 것·설계값 (개발자 C1)

지시서 [2026-10-27-coast-ui-spec-C1.md](2026-10-27-coast-ui-spec-C1.md) §0 요구 ①~⑧ 을 새 저장소에 구현했다. 전/후 비교는 없다(빈 저장소에서 시작).
`../ais_integrity_ml_all` 은 어떤 파일도 고치지 않았다(git status 변화 없음 · parquet mtime 그대로). git commit 은 하지 않았다(코디네이터가 사용자 확인 뒤).

## 1. 한 것

| 지시서 | 만든 것 |
|---|---|
| §1-1 기술 | FastAPI + 정적 JS · OpenLayers **9.2.4** · d3 7.9.0 · d3-sankey 0.12.3 — `static/vendor/` 에 버전 고정 사본(VERSIONS.txt, CDN 없음) · 자기 venv 3.12(`requirements.txt`) · `run_coast.ps1`(-Port 8800 · -BindHost 127.0.0.1) |
| §1-2 설정 | `.env.local` 하나(견본 `.env.example`): `AISINT_ML_ALL_ROOT`·`COAST_TILE_URL`·`COAST_PORT`·`COAST_POLL_MS`. 절대경로·호스트 없음. 타일 서버 없으면 항행수역(sea_mask) 칸을 배경으로 |
| §1-3 제공자 층 | `coast/providers/base.py` `SnapshotProvider`(sources·window·ships_at·ship·contours·changes_since) · `parquet.py` **ParquetProvider**(risk_map_real·risk_map_ds015, `ml_table_*` 에서 `speed`=SOG 조인) · `live.py` **LiveProvider 자리**(NotImplemented, README 에 꽂는 법) · `/api/ships_at` 의 `since` 자리 · 프런트 `POLL_MS` 폴링 훅(1차 0) |
| §1-4 판정의 뜻 | `coast/mlall.py` — ml_all `risk/threats.py`·`engines/threat/rules.py` 를 sys.path 로 **import**(복사 없음). 코드 한 줄 설명은 `rules.py` 모듈 docstring 의 15코드 표에서 읽음(`code_info` 문구표가 그쪽에 없어서) |
| §1-5 비정상 정의 | `coast/judge.py` 한 곳 — 행: 룰 `code_primary` / XGB G·kNN G·정답은 양성 코드 중 `PRIMARY_ORDER` 첫 코드 · 보류 = REPORT_RATE_SLOW ENV_LOSS·UNKNOWN(룰 갈래 빌림) + kNN Unknown · 배 = 기간 안 비정상 1건↑. 생성 벌 "정답 보기" 토글 = judge=truth |
| §2 상황판 | 상단 띠(소스·기간·시점 슬라이더(분)·판정기·정답 토글) · 왼쪽 위협 카드 5장+보류+정상(배 수·비정상 행 수, 클릭=필터) · 해안국 카드(받은 메시지·배·비정상 비율 행/배·보류·신호 요약) · 가운데 OL 지도(아이콘 회전·색 `static/icons/mapping.json`·10분 지난 보고 반투명·hover 이름표·클릭 상세+항적·층 토글) · 오른쪽 선박 목록(MMSI·위협·영향·대표 코드·갈래·비정상 비율·마지막 보고·신호 3단계, 기본 정렬 영향→위협→비율, 머리 클릭 정렬, 검색·종류·상태 필터) · 하단 탭 토폴로지/배 상세 |
| §2-7 문구 | 코드 옆 한 줄 설명(툴팁·상세) · 영향 H/M/L 옆 "즉시 확인 / 확인 필요 / 참고" · 수치마다 단위(행/배/척/dB) |
| §3 토폴로지 | 세 층 나무(수신소 → 종류 4 → 정상/비정상/보류 → 선박 상위 20) · 선버스트 · 생키(수신소 → 종류 → 위협 1~5·정상·보류) · 표(해안국별·종류별·선박 상위 20) · 마디 클릭 = 공유 필터 · VDE 0 자리 · 해안국 N 곳 설계(site 열 groupby) |
| §4 신호 품질 | 배 원인 카드 4몫(송신기/해역 환경/혼잡·간섭/미상, dB 귀속, ⚑ 기준) + 종합 3단계(수신 여유) · 등고선 2종(수신 여유 0/10/20 · 환경 잔차 −10/−5/0/+5) 정규 크리깅(지수 반분산·이웃 16) → marching squares(서버 Python, 방향 있는 선분) → GeoJSON · 표본 부족 시 IDW 대체+범례 표시 · 3 km 밖·육지 비움 · 보고 밀도·ENV_LOSS 층 · 범례에 생존 편향 주의 · `docs/SIGNAL_QUALITY_BASIS.md` |
| §5 시간 | 기간(합산) ≠ 시점(지도만). 응답은 (소스·기간·시점·판정기)별 서버 캐시 |
| §6 검사·캡처·문서 | `tests/` 5종 + `capture.py` 4장 · README · 이 문서 · SIGNAL_QUALITY_BASIS |

## 2. 검사 결과 (2026-10-27, 서버 127.0.0.1:8800)

| 검사 | 무엇을 | 결과 |
|---|---|---|
| (a) `check_counts.py` | API 위협 등급별 배 수·비정상 행 수·해안국 비정상 비율(행/배)·배별 비율·행 수·배 위협 = parquet 에서 **직접** 센 값(coast.judge 안 거침). 실해역·ds_015 × 전체+부분 기간, ds_015 정답 판정기 | **통과 594 건** |
| (b) `check_topology_sum.py` | 나무 각 층 합 = 전체 · 생키 1층/2층 링크 합 = 전체 · 위협 링크 합 = 비정상 · 표 합 · 목록 종류별 합 = 배 행. 룰·XGB(실해역) / 룰·정답(ds_015) | **통과 430 건** |
| (c) `check_ships_at.py` | 시점 3개 × 소스 2개 — 배 수·시각·위치 = parquet 의 t 직전 마지막 위치 보고 · age_s · 항적 추정 침로 재계산 일치 · 기간 밖 없음 | **통과 288 건** |
| (d) `check_contours.py` | marching squares 단위(평면·NaN·원 고리 1개 닫힘·반지름) · 크리깅 표본점 재현·중간점 오차 · IDW 정확 · API GeoJSON 유효 · 레벨 = §4 값 · 감도 −107/보호비 10/문턱 4 · 범례 주의·설계값 | **통과 64 건** |
| (e) `check_icon_rotation.js` | 침로 0/90/180/270/… → OL 회전(아이콘이 동쪽을 향하므로 침로−90°) · 아이콘 끝점 벡터 = 나침반 방위 · 범위 [0,2π) · 우선순위 heading>cog>null · 색 매핑 6색 · app.js 가 같은 함수를 씀 | **통과 229 건** |
| `capture.py` | Chrome 헤드리스 1440×900, 콘솔/페이지 오류 0 | 4장 생성, 오류 없음 |

검사 중 잡아서 고친 것: 기간 기본 끝이 초 단위로 잘려 마지막 초의 행(실해역 7행·ds_015 6행)이 빠지던 것 → 실제 최대 시각 사용 ·
marching squares 가 격자점 값 = 레벨인 퇴화에서 고리를 쪼개던 것 → 방향 있는 선분 + 길이 0 선분 제거 + 직진 우선 잇기 ·
IDW 표본점 정확 보간 · 생성 벌 정답 판정기의 대표 코드 순서(검사 쪽 오류).

## 3. 캡처 (`docs/screenshots/`)

| 파일 | 장면 |
|---|---|
| `coast_dashboard.png` | 상황판 — 실해역, 위협 카드·지도(아이콘 회전)·목록·토폴로지 |
| `coast_topology.png` | 아래 패널 크게 — 선버스트·생키·표 |
| `coast_ship_detail.png` | 목록 첫 번째 위치 보고 있는 배(영향 H) — 코드별·시간대별·종류 비율·신호 원인 카드·항적 |
| `coast_contours.png` | 수신 여유·환경 잔차 등고선 + 보고 밀도, 항만 쪽 확대, 범례 |

캡처 때 `localhost:8080` 타일 서버가 켜져 있어 배경 지도가 보인다. 꺼져 있으면 항행수역 격자만 배경이 된다(코드 경로 둘 다 확인).

## 4. 못 한 것 · 데이터 사실

- **선수(heading)·COG 열이 없다** — `risk_map_*`·`ml_table_*` 어디에도 없다(`output/datagen/df.parquet` 은 2020-03-11 다른 벌). 지시서 §1-3 대로
  보고에 적고 **항적 추정 침로**(직전 30 m 이상 떨어진 위치의 방위, 최대 20행 거슬러)로 회전, 추정 안 되면 원형 점. 실해역 631척 중 328척·ds_015 1,377척 중 690척이 회전,
  나머지는 정지 배(원형). SOG 는 `ml_table` `speed` 조인(실해역 91.8 % 적중). 실시간/DB 에서 heading·course 를 받으면 ParquetProvider 의 조인 열 목록(`want`)에 이름만 추가하면 된다.
- **위협 4 무선 간섭**은 ml_all 에 탐지기가 없어 카드 0(“탐지기 미구현”). VDE 는 데이터에 없어 0 자리.
- **SPOOF_BASE_STATION 의 VDO_NA 갈래**(대조 불가)는 지시서 §1-5 보류 목록에 없어 정상으로 센다(ml_all 콘솔은 위반 아닌 갈래로 따로 색). 보류에 넣으려면 `judge.HOLD_KINDS` 한 줄.
- 판정기 XGB·kNN 은 **G 판** 고정(`judge.ML_VERSION`). R 판 선택은 넣지 않았다.
- 실시간: `LiveProvider`·`/api/changes`·`since`·`POLL_MS` 는 자리만. 수집기 없음(범위 밖).
- 토폴로지 선박 층은 마디마다 **상위 20척**만 내려준다(전체는 선박 목록 쪽).
- 배 원인 카드의 "해역 환경" 은 항적 위 환경 잔차 장 값의 중앙값 — 항적이 표본(3 km) 밖이면 "값 없음" 으로 미상에 들어간다.
- 1280 px 는 CSS 로 열 너비만 줄였다(실측 캡처는 1440).

## 5. 설계값 표 (근거 없음)

| 값 | 어디 | 비고 |
|---|---|---|
| 20 dB | 수신 여유 셋째 등고선 | 보호비 10 dB 의 두 배 |
| −4 dB | 가림 의심 문턱(카드 ⚑) | ml_all `rssi_resid_db` 와 같은 값 |
| 0.5 km · 3 척 · 30 개 · 16 · 15 km | 격자 · 표본 칸 최소 배 · 크리깅 최소 표본 · 이웃 · 반분산 최대 거리 | SIGNAL_QUALITY_BASIS §4 |
| 3 km | 등고선 반경 밖 비움 · 혼잡 반경 | ml_all `NEAR_KM` 과 같음 |
| 10 분 | 시점에서 오래된 보고 반투명(투명도 0.45) | 요구 §2-6 |
| 30 m · 20 행 | 항적 추정 침로 최소 이동 · 거슬러 보는 행 수 | 데이터에 선수 없음 |
| 50 % | 혼잡 카드 ⚑ 슬롯 사용률 | — |
| G | XGB·kNN 판 | — |
| 2000 점 | 상세 항적 최대 점 수(균등 표본) | — |
| 5~95 백분위 | 지도 첫 맞춤 범위(멀리 떨어진 배 무시) | — |

## 6. 남긴 것

검사용 서버(8800)는 작업 끝에 내렸다. 백그라운드 프로세스 없음. `venv/`·`__pycache__` 는 `.gitignore`.
