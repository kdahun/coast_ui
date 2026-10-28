# coast_ui — 해안국 관리자 화면 (읽기 전용)

"지금 어느 배를 먼저 봐야 하나"를 첫 화면에서 보여 주는 **해안국 관리자용** 화면이다. 판정은 하지 않는다 —
옆 저장소 `../ais_integrity_ml_all` 이 만든 판정 결과(`output/datagen/risk_map_*.parquet`)를 **읽기만** 해서 보여 준다.
쓰기 기능(확인함·메모·보고서·승격/기각)은 없다. 지시서: 1차 [docs/2026-10-27-coast-ui-spec-C1.md](docs/2026-10-27-coast-ui-spec-C1.md) ·
2차 [docs/2026-10-27-coast-ui-spec-C2.md](docs/2026-10-27-coast-ui-spec-C2.md) (화면 분리 · 선수 방향 기본, 변경 내역 [CHANGES-C2](docs/2026-10-27-coast-ui-CHANGES-C2.md)).

**화면 하나 = 질문 하나.** 상단 띠의 메뉴 5개로 화면을 바꾼다(해시 라우터). 조건(소스·기간·판정기·정답 보기)은 오른쪽 **조건 버튼 하나**에 접혀 있고
URL 해시에 실려 화면을 옮겨도 유지된다.

| 메뉴 | 질문 | 무엇 |
|---|---|---|
| ① 상황판 `#/overview` | 지금 급한 배가 몇 척? | 한 문장 · 숫자 타일 4장(즉시 확인 H · 확인 필요 M · 참고 L · 보류, 클릭 → 목록) · 지금 봐야 할 배 5척 · 작은 지도(점만) + 해안국 요약 1줄 · 위협 1~5 카드 가로 5장 |
| ② 지도 `#/map` | 어디 있나? | 지도가 화면 전체(MarineTraffic 식). 왼쪽 위 아이콘 4개(🔍 검색 · ⚑ 필터 · ◧ 레이어 · ≡ 범례) — 누르면 패널 하나만. 아래 시점 슬라이더(◀ ▶ 1분, ▶ 재생 1초=1분). 배 클릭 → 오른쪽 카드(등급·코드·속력/방향·마지막 보고·비정상 비율·신호 원인·자세히 →) + 항적 |
| ③ 선박 목록 `#/ships` · 배 상세 `#/ship/<mmsi>` | 어느 배? | 전체 폭 표(8열, 머리 클릭 정렬·검색·종류·상태 필터, 배지에 글자). 상세 = 요약 카드 · 작은 지도+항적 · 시간별 막대 · 메시지 종류별 건수 · 코드별 비정상 행 수 + 한 줄 설명 · 신호 원인 |
| ④ 수신 현황 `#/flow` | 어디서 얼마나 들어오나? | 한 문장 + 가로 누적 막대 3개(해안국별 · 메시지 종류별(VDE 0 자리) · 위협별 배 수) + 선박 상위 20 표. 막대 조각 클릭 = 공유 필터(목록·지도에 반영). 옛 토폴로지와 숫자 같음(API 불변) |
| ⑤ 신호 품질 `#/signal` | 전파 상태는? | 한 문장 + 원인 카드 4장(송신기 약함 · 해역 환경 · 혼잡·간섭 · 미상, 해안국 전체 몫 %) · 지도(수신 여유·환경 잔차 등고선 + 보고 밀도 + ENV_LOSS) · "왜 이렇게 그렸나" 10줄 — 근거 [docs/SIGNAL_QUALITY_BASIS.md](docs/SIGNAL_QUALITY_BASIS.md) |

모든 화면이 **한 필터**(등급·위협·해안국·메시지 종류·상태(항해 중/정박)·검색)를 공유하고 해시 질의(`g th site kind nav q`)에 실린다.
기간(시작~끝) = 합산, 시점(분) = 지도 배 위치만. 캡처: `docs/screenshots/coast_r2_*.png`(1440×900 · `_1280` = 1280×800), 1차는 `coast_*.png`.

## 실행

처음 한 번 — 자기 venv(Python 3.12). ml_all 의 venv 는 쓰지 않는다.

```powershell
cd C:\Develop\integrity_program\coast_ui
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env.local          # 필요하면 값 수정
```

띄우기 — 기본 http://127.0.0.1:8800 , 종료는 Ctrl+C (백그라운드에 아무것도 남지 않는다).

```powershell
.\run_coast.ps1                            # -Port 8800 -BindHost 127.0.0.1 이 기본
.\run_coast.ps1 -Port 8801 -BindHost 0.0.0.0
```

## 설정 — `.env.local` 한 파일 (견본 `.env.example`, git 제외)

| 이름 | 무엇 | 비우면 |
|---|---|---|
| `AISINT_ML_ALL_ROOT` | 판정 산출물이 있는 ml_all 저장소(상대경로는 이 저장소 뿌리 기준) | `../ais_integrity_ml_all` |
| `COAST_TILE_URL` | 지도 타일 `{z}/{x}/{y}` | `http://localhost:8080/styles/dark-matter/{z}/{x}/{y}.png` — 타일 서버가 없으면 배경 없이 항행수역(sea_mask) 윤곽만 |
| `COAST_PORT` | 기본 포트 | `8800` |
| `COAST_POLL_MS` | 프런트 폴링 주기(ms) | `0` = 꺼짐(실시간 제공자가 붙으면 켠다) |

이미 설정된 환경변수가 파일보다 이긴다. 절대경로·호스트는 코드에 없다. DB 는 쓰지 않는다(비밀번호 없음).

## 데이터 — ml_all 에서 읽는 것 (수정하지 않는다)

| 파일 | 쓰임 |
|---|---|
| `output/datagen/risk_map_real.parquet` | 부산 실해역(수신소 1) — 룰·XGB G·kNN G 판정 열 |
| `output/datagen/risk_map_ds015.parquet` | 생성 벌 ds_015 — + 정답 열(`y_truth__*`) → "정답 보기" 토글 |
| `output/datagen/ml_table_{real,ds015}.parquet` | `heading`·`course`·`speed` 가 risk_map 에 **없을 때만** (mmsi, vsi_time) 조인(폴백). 2026-10-27 부터 risk_map 에 세 열이 있어 조인하지 않는다 |
| `config/sea_mask.json` | 항행수역 격자 — 등고선 육지 마스크·타일 없을 때 배경 |
| `src/aisint/risk/threats.py` · `engines/threat/rules.py` | 위협 1~5·영향 H/M/L·코드 목록·우선순위·문턱 — **import 만**(복사 금지) |

**방향 = 선수 기본.** risk_map 의 `heading`(HDG)·`course`(COG)·`speed`(SOG) 는 DB 값 그대로(AIS 관례 511 · 360 · 102.3 = 없음).
우선순위(서버 `ParquetProvider._direction` 과 `static/rotation.js shipCourse` 가 같다): **선수 HDG → COG 데이터 → 항적 추정(직전 30 m, `track`) →
그 배의 기간 안(시점 이전) 마지막 유효 HDG/COG(`last`) → 없으면 북쪽 0° 고정(`none`, 아이콘 + "?" 표식)**. 원형 점은 없다.
실해역 기간 끝 시점 631척: 선수 375 · 침로 244 · 항적 0 · 마지막값 5 · 미상 7. 여수(site 7·8)는 표에 없다.

## 구조

```
coast/
  app.py              FastAPI — /api/* 만. 제공자(PROVIDER) 한 줄
  settings.py         .env.local
  mlall.py            ml_all 의 threats·rules 를 sys.path 로 import (복사 금지)
  judge.py            ★ "비정상·보류·정상" 정의 — 한 곳
  msgkind.py          메시지 종류(AIS 위치 보고 / 정적·기타 / ASM / VDE)
  signal.py           신호 품질 — 수신 여유·환경 잔차·크리깅·marching squares·원인 카드
  providers/
    base.py           ★ SnapshotProvider 계약(6 메서드) — 프런트가 보는 유일한 데이터 모양
    parquet.py        1차 구현 ParquetProvider (ml_all parquet 읽기 전용)
    live.py           LiveProvider 자리 (실시간 수집기가 생기면 여기)
static/
  index.html · style.css · app.js     화면 5개(해시 라우터 · 한 필터 공유 · OpenLayers 9 지도 · 막대는 DOM/CSS)
  rotation.js         아이콘 회전·색·방향 우선순위 — 지도와 단위 검사가 같은 함수
  icons/              vessel_{gray,red,blue,green,pink,yellow}.png + mapping.json(색 매핑 한 곳)
  vendor/             ol 9.2.4 — 버전 고정 사본(CDN 안 씀, VERSIONS.txt). d3 는 2차에서 삭제
tests/                검사 6종 + 캡처
docs/                 지시서(C1·C2) · SIGNAL_QUALITY_BASIS · CHANGES(1차·C2) · screenshots/
```

### 비정상의 뜻 (`coast/judge.py`)

- 행: 판정기가 코드를 붙인 행 = **비정상**(룰은 `code_primary`, XGB G·kNN G·정답은 양성 코드 중 `PRIMARY_ORDER` 가장 앞).
  비정상이 아니면서 REPORT_RATE_SLOW 환경성 갈래(ENV_LOSS·UNKNOWN) 또는 kNN Unknown 이면 **보류**. 나머지 **정상**.
- 배(보는 기간 안): 비정상 1건 이상 = 비정상 배, 그 위협·영향·대표 코드 = 가장 앞 코드의 것. 보류만 있으면 보류 배.
- 지도 색·목록 등급은 **배 단위(기간)**, 시점 슬라이더는 위치만 바꾼다.

### API (`/api/docs` 에 OpenAPI)

| 경로 | 무엇 |
|---|---|
| `GET /api/state` | 소스·위협·코드(설명)·판정기·아이콘 매핑·층·설정 |
| `GET /api/window?src&t0&t1&judge` | 기간 합산 — 카드·해안국·토폴로지·선박 목록 |
| `GET /api/ships_at?src&t&t0&t1&judge[&since]` | 시점 — 배마다 t 직전 마지막 보고 (`since` 는 실시간용 자리) |
| `GET /api/ship?src&mmsi&t0&t1&judge` | 배 상세 |
| `GET /api/contours?src&layer&t0&t1` | `margin` · `env`(등고선 GeoJSON) · `density` · `envloss`(칸 폴리곤) |
| `GET /api/signal_summary?src&t0&t1&judge` | (2차) ⑤ 신호 품질 — 해안국 전체 원인 카드 4장(몫 %·으뜸 원인 배 수·⚑ 수)·3단계 배 수 |
| `GET /docs/<name>.md` | docs/*.md 읽기 전용(화면의 근거 문서 링크) |
| `GET /api/changes?src&since` | 실시간 자리 — ParquetProvider 는 `null` |
| `GET /api/seamask` | 항행수역 격자 GeoJSON |

## 확장 — 실시간 소스를 꽂는 자리 (LiveProvider)

프런트는 `/api/*` 만 보고, `/api/*` 는 `coast/providers/base.py` 의 `SnapshotProvider` 일곱 메서드(2차에 `signal_summary` 추가)만 부른다.
실시간 수집기가 생기면:

1. `coast/providers/live.py` 의 `LiveProvider` 에 일곱 메서드를 구현한다(수집기 버퍼에서 같은 모양의 dict). **비정상 정의는 `coast/judge.py` 를 그대로 쓴다.**
2. `changes_since(src, t)` 가 t 이후 바뀐 배를 `Delta` 로 돌려준다.
3. `coast/app.py` 의 `PROVIDER` 를 바꾸거나(소스 하나로 합치려면 두 제공자를 감싸는 라우터 제공자) `.env.local` 의 `COAST_POLL_MS` 를 켠다 →
   프런트 폴링 훅(`app.js` 의 `POLL_MS`)이 `/api/changes` 를 주기로 부르고 지도만 갱신한다.

화면·집계·등고선 코드는 손대지 않아도 된다. 해안국(수신소)은 N 곳으로 설계돼 있어 여수가 들어오면 카드·토폴로지가 그대로 늘어난다.

## 검사

검사용 서버는 **8801** 로 띄운다(`.\run_coast.ps1 -Port 8801` — 8800 은 사용자 화면이 떠 있을 수 있다). 검사 스크립트는 기본이 8800 이라 주소를 인자로 준다. 끝나면 서버를 내린다.

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt     # playwright · requests (한 번)
.\venv\Scripts\python.exe tests\check_counts.py http://127.0.0.1:8801        # (a) 위협 등급 수·비정상 비율 = parquet 직접 센 값
.\venv\Scripts\python.exe tests\check_topology_sum.py http://127.0.0.1:8801  # (b) 수신 현황 숫자(topology) 합 = 전체
.\venv\Scripts\python.exe tests\check_ships_at.py http://127.0.0.1:8801      # (c) ships_at = 시점 직전 마지막 보고 · 선수/COG = parquet · 방향 우선순위 · 원형 0척
.\venv\Scripts\python.exe tests\check_contours.py http://127.0.0.1:8801      # (d) 등고선 GeoJSON 유효 · 레벨 = §4 값 · marching squares·크리깅 단위
node tests\check_icon_rotation.js                                              # (e) 아이콘 회전 각 = 선수 · 우선순위 last/none (서버 불필요)
.\venv\Scripts\python.exe tests\check_pages.py http://127.0.0.1:8801         # (f) 5 화면 + 상세: 콘솔 오류 0 · 고유 요소 · 문장 숫자 = API · 막대 합 (1440·1280)
.\venv\Scripts\python.exe tests\capture.py --base http://127.0.0.1:8801     # 캡처 14장 → docs/screenshots/coast_r2_* (설치된 Chrome/Edge 사용)
```

## 하지 않는 것

쓰기 기능 · 여수 · 실시간 수집기 구현 · 재생 · 판정 엔진·콘솔 수정 · 라벨·룰 변경 · ml_all 파일 수정.
