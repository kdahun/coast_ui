# 해안국 관리자 화면(coast_ui) — 1차 지시서 (개발자 C1)

- 날짜: 2026-10-27. 사용자 확정(인터뷰 10-27): §0 그대로. 새 저장소 `C:/Develop/integrity_program/coast_ui`(git init 됨, 빈 저장소).
- 데이터·판정은 **옆 저장소 `../ais_integrity_ml_all` 의 산출물을 읽기만** 한다. 그쪽 코드·parquet·모델·원장은 **절대 수정하지 않는다.**
- 사용자는 ML 초심자 — 화면 문구·보고는 쉽게, 목적부터. 보고·문서는 한국어.

## 0. 사용자가 확정한 요구 (바꾸지 말 것)

| # | 요구 |
|---|---|
| ① | **해안국 관리자**가 보는 **읽기 전용** 화면. "지금 어느 배를 먼저 봐야 하나"가 첫 화면에서 보여야 한다. 쓰기 기능(확인함·메모·보고서·승격/기각) 없음 |
| ② | 데이터: **부산 실해역(수신소 1)** + **생성 벌 ds_015**. 여수 제외. 실시간 수집은 아직 없음 — 그러나 **나중에 실시간 소스를 같은 자리에 꽂을 수 있게**(§1 제공자 층) |
| ③ | **지도**에 선박을 **주어진 아이콘 에셋**(`static/icons/vessel_{gray,red,blue,green,pink,yellow}.png`, 20×10 px)으로, **선수 방향으로 회전**해서 띄운다. 위협 등급별로 보기(필터) |
| ④ | **선박 목록**: 위협 등급별 보기·**정렬** |
| ⑤ | **토폴로지** = 구성 비율 화면: 해안국 → 메시지 종류(AIS 위치 보고 / AIS 정적·기타 / ASM / VDE) → 정상/비정상 → 선박. 해안국별·선박별·메시지 종류별 정상/비정상 비율. VDE 는 데이터에 없어 0 으로 자리만 |
| ⑥ | **신호 품질**을 **원인별**(송신기 약함 / 해역 환경·가림 / 혼잡·간섭 / 미상)로 보여 준다. 해역 신호 품질은 **격자가 아니라 등고선**으로, **저명한 근거(표준·논문)를 출처와 함께** 적용하고 왜 그렇게 그렸는지 문서화(§4) |
| ⑦ | 시간: **기간 선택(합산)** + **시점 슬라이더**(지도 배 위치). 재생 없음 |
| ⑧ | 지도·목록·토폴로지가 **한 필터(기간·시점·위협 등급·해안국·메시지 종류·선택 배)를 공유** |

범위 밖: 쓰기 기능, 여수, 실시간 수집기 구현, 재생, 판정 엔진·콘솔 수정, 라벨·룰 변경.

## 1. 구조 — 데이터 제공자 층 (실시간 확장의 핵심)

1. 기술: **FastAPI + 정적 JS**(판정 콘솔과 같은 방식) + 지도는 **OpenLayers 9**(아이콘 에셋이 OpenLayers 용이고 사용자의 다른 프로젝트 `web-gis-ecdis-control` 도 OL 9). 토폴로지 그림은 d3(선버스트·생키). 외부 JS 는 `static/vendor/` 에 **버전 고정으로 내려받아 둔다**(CDN 의존 금지 — 사내망). Python 은 `../ais_integrity_ml_all/venv` 를 그대로 쓰지 말고 **자기 venv**(`requirements.txt`, 3.12). 포트 기본 **8800**, `run_coast.ps1` 로 띄움(`-Port`, `-BindHost` 기본 127.0.0.1).
2. 설정은 저장소 뿌리 `.env.local` 하나(견본 `.env.example`, git 제외): `AISINT_ML_ALL_ROOT`(기본 `../ais_integrity_ml_all`), `COAST_TILE_URL`(기본 `http://localhost:8080/styles/dark-matter/{z}/{x}/{y}.png`, 없으면 OL 기본 배경 없이 육지 윤곽만). **절대경로·호스트 하드코딩 금지.**
3. **제공자 인터페이스** `coast/providers/base.py`:
   ```
   class SnapshotProvider(Protocol):
       def sources(self) -> list[Source]                      # {id, label, kind: 'real'|'generated', t_min, t_max, sites, has_truth}
       def window(self, src, t0, t1, flt) -> WindowStats      # 기간 합산: 토폴로지·비율·목록
       def ships_at(self, src, t, flt) -> list[ShipState]     # 시점: 배마다 t 직전 마지막 보고(위치·선수·COG·SOG·등급·코드·신호 카드 요약)
       def ship(self, src, mmsi, t0, t1) -> ShipDetail        # 배 상세: 코드·갈래·시간대별 비정상·신호 원인 카드·항적
       def contours(self, src, t0, t1, layer) -> GeoJSON      # §4 등고선
       def changes_since(self, src, t) -> Delta | None        # 실시간용 자리 — 1차는 None(문서에 "LiveProvider 가 구현" 명시)
   ```
   1차 구현 `ParquetProvider`: `AISINT_ML_ALL_ROOT/output/datagen/risk_map_real.parquet`(실해역)·`risk_map_ds015.parquet`(생성 벌) — 열: `mmsi·vsi_time·site_id·msg_type·channel·rssi(dBm)·snr(dB)·rssi_resid·snr_resid·dist_site_km·lat·lon·y_rule__*·code_primary·rule_*_kind·xgb_G__*·knn_G__*·knn_unknown_G·y_truth__*(생성 벌)`. 선수(`heading`)·COG·SOG 열이 없으면 **같은 뿌리의 `ml_table_*.parquet`/원본 df 에서 (mmsi, vsi_time) 조인**해 가져온다 — 없으면 1차 보고에 적고 COG 로 대체.
   프런트는 **제공자가 바뀌어도 모르게** `/api/*` 만 본다. `/api/ships_at?src&t` 는 `since` 를 받을 자리를 두고(1차는 무시) 프런트에 "폴링 훅" 자리(주기 상수 하나, 1차 0 = 꺼짐)를 둔다.
4. **판정의 뜻은 ml_all 과 하나**: 위협 1~5·영향 H/M/L 매핑은 `AISINT_ML_ALL_ROOT/src/aisint/risk/threats.py` 를 **읽어 들여**(sys.path 에 그 `src` 추가, import 만) 쓴다 — 복사 금지. 코드 설명 문구도 그쪽 `code_info` 가 있으면 그것.
5. **"비정상" 정의(한 곳 `coast/judge.py`)**: 행 단위 = `code_primary` 가 붙은 행(룰 기준; 판정기 선택 XGB G·kNN G 는 `xgb_G__*`/`knn_G__*` 의 가족 우선순위 `PRIMARY_ORDER` 로 같은 식). **보류** = `REPORT_RATE_SLOW` 갈래 ENV_LOSS·UNKNOWN, kNN Unknown — 비정상이 아니라 별도 색. 배 단위 = 보는 기간 안 비정상 1건 이상. 생성 벌은 "정답 기준"도 같은 식으로(관리자 화면에는 **판정 기준이 기본**, 정답은 "정답 보기" 토글 하나).

## 2. 화면 — 해안국 관리자 관점 (첫 화면 = 상황판)

6. 배치(한 화면, 1440 px 기준·1280 에서도 깨지지 않게):
   - 상단 띠: 데이터 소스 선택(부산 실해역 / 생성 ds_015) · **기간**(시작~끝, 기본 전체) · **시점 슬라이더**(분 단위, 기본 기간 끝) · 판정기(룰 / XGB G / kNN G, 기본 룰) · 생성 벌이면 "정답 보기" 토글.
   - 왼쪽 열(요약): **위협 등급 카드 5장**(위협 1~5, 영향 H/M/L 색) — 배 수·비정상 행 수, 누르면 필터. 그 아래 **해안국 카드**(수신소마다; 지금은 1 곳): 받은 메시지·배 수·비정상 비율(행/배)·보류 비율·신호 품질 요약(§4 카드).
   - 가운데: **지도**(OL). 배 = 아이콘 회전(선수 `heading`; 없으면 COG; 둘 다 없으면 회전 없이 원형 점). 아이콘 색 매핑은 **`static/icons/mapping.json` 한 곳**: `red`=H, `yellow`=M, `blue`=L, `gray`=정상/판정 없음, `pink`=보류(ENV_LOSS·Unknown), `green`=선택한 배(테두리 강조와 병행). 시점에서 10 분보다 오래된 마지막 보고는 반투명. 배 hover = 이름표(MMSI·등급·대표 코드·신호 3단계), 클릭 = 상세 패널 + 항적(기간 안). 레이어 토글: 등고선 2종(§4)·보고 밀도·항적.
   - 오른쪽 열: **선박 목록** — 열: MMSI·위협(1~5)·영향·대표 코드·갈래·비정상 비율(행)·마지막 보고 시각·신호(3단계). **정렬**: 기본 영향 H→M→L → 위협 번호 → 비정상 비율 내림차순, 열 머리 클릭으로 바꿈. 필터: 위협 등급·해안국·메시지 종류·검색(MMSI).
   - 하단 탭: **토폴로지**(§3) · **배 상세**(클릭한 배: 코드별·시간대별 비정상, 신호 원인 카드, 메시지 종류 비율).
7. 관리자 문구: 코드 이름 옆에 한 줄 설명(ml_all `code_info`), 등급은 "즉시 확인 / 확인 필요 / 참고" 같은 **행동 표현**을 H/M/L 옆에 붙인다. 모든 수치에 단위·기준(행/배)을 적는다.

## 3. 토폴로지

8. 세 층 나무: 해안국(site) → 메시지 종류(AIS 위치 보고 Msg 1·2·3·18·19·27 / AIS 정적·기타 Msg 5·24·4·20·22·23·… / ASM Msg 6·8·25·26 / VDE(0)) → 정상 / 비정상 / 보류 → 선박. 마디마다: 행 수·배 수·비율.
9. 그림 둘(d3): **선버스트**(해안국 → 종류 → 정상/비정상/보류) · **생키**(해안국 → 종류 → 위협 등급 1~5·정상·보류). 마디 클릭 = 공유 필터 갱신(지도·목록이 따라 걸러짐). 표도 같이(해안국별·종류별·선박 상위 20).
10. 해안국이 지금은 1 곳이라도 **N 곳으로 설계**(여수가 들어오면 그대로 늘어나게).

## 4. 신호 품질 — 원인별 카드 + 등고선 (근거 필수)

11. **배 원인 카드**(배 상세·hover 요약): 네 몫을 막대로.
    - 송신기 약함: 그 배 24 h 거리 모델 잔차 평균(`rssi_resid` 배 평균, ml_all `REPORT_RATE_SLOW` TX_WEAK 와 같은 2.5 SE 기준·`rule_slow_kind=TX_WEAK`) → "다른 배보다 n dB 약하게 들림".
    - 해역 환경(가림): 배 위치에서의 **환경 잔차 등고선 값**(아래 (나)) → "이 위치는 원래 n dB 낮게 들리는 곳".
    - 혼잡·간섭: 같은 분 반경 3 km 안 배 수 + 그 프레임의 슬롯 사용률(frame 당 보고 수 / 2250) → "주변 배 n척, 슬롯 n% 사용".
    - 미상: 위 셋으로 설명 안 되는 나머지.
    종합 3단계(좋음/보통/나쁨)는 **(가) 수신 여유**로 정한다(아래).
12. **등고선 2종**(OL 벡터 레이어, 켜고 끄기):
    - **(가) 수신 여유(dB)** = `rssi − (−107 dBm)`. 등고선 **0 / 10 / 20 dB**. 근거: ITU-R M.1371-6 최소 수신기 감도 **−107 dBm(PER 20 %)**, 동일 채널 보호비 **10 dB**(C/(I+N) ≈ 10 dB 에서 PER 20 %) — 0 dB 아래는 표준 감도 미만(수신 자체가 불안), 0~10 은 간섭 하나면 끊길 여유, ≥ 10 은 보호비만큼 여유, ≥ 20 은 넉넉. 3단계 = 나쁨 < 0, 보통 0~10, 좋음 ≥ 10.
    - **(나) 환경 잔차(dB)** = `rssi_resid`(관측 − 거리 기대값; 거리 기대값은 ml_all 의 거리 모델 그대로 — 표준 참조는 ITU-R P.1546 해상 경로 곡선). 등고선 **−10 / −5 / 0 / +5 dB**(−X 문턱은 ml_all `rssi_resid_db` 와 같은 값으로 맞출 것 — 설계값임을 명시). 가림·음영을 보는 층.
    만드는 법(둘 다 같음): 기간 안 위치 있는 보고의 점값 → **정규 크리깅(Ordinary Kriging)** 으로 격자(해상 0.5 km, 육지 마스크는 ml_all `sea_mask`)에 보간 → **marching squares**(d3-contour, 서버에서 계산해 GeoJSON 으로 내려줌)로 등고선. 점이 적으면(격자 칸당 < 3 척) IDW 로 대체하고 범례에 표시. 반경 밖(가장 가까운 점 > 3 km)은 그리지 않는다.
    **생존 편향 주의**: 수신된 메시지만 보이므로 "아주 나쁜 곳"은 값이 낮게 나오는 게 아니라 **점이 없다** — 그래서 **보고 밀도(배×분)** 층과 ENV_LOSS 비율을 같이 켤 수 있게 하고 범례에 이 주의를 적는다.
13. 문서 `docs/SIGNAL_QUALITY_BASIS.md`: 왜 등고선 값이 이것인지 **출처 URL 과 함께**(아래 목록 그대로 + 구현에서 쓴 식), 설계값(−X, 3 km, 0.5 km, 10 분)은 표로 "설계값·근거 없음" 명시.
    - ITU-R M.1371-6 (02/2026) 수신기 감도 −107 dBm @ PER 20 %, 동일 채널 보호비 10 dB: https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.1371-6-202602-I!!PDF-E.pdf (M.1371-4/-5 표 7 도 같음)
    - Report ITU-R M.2169: 시판 장비 전형 감도 −109 dBm(참고): https://www.itu.int/dms_pub/itu-r/opb/rep/R-REP-M.2169-2009-PDF-E.pdf
    - ITU-R P.1546(-5/-6) 30–3000 MHz 점-대-면 전계강도 예측(해상 경로 곡선): https://itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.1546-5-201309-I!!PDF-A.pdf
    - 라디오 환경 지도(REM) 보간에 정규 크리깅: arXiv 1611.03725 https://arxiv.org/pdf/1611.03725 · WiOpt 2014 https://dl.ifip.org/index.html/db/conf/wiopt/wiopt2014/BrahamJSFM14.pdf · NWU 비교 연구 https://repository.nwu.ac.za/handle/10394/14462
    - 등고선 알고리즘 marching squares: https://en.wikipedia.org/wiki/Marching_squares · d3-contour https://github.com/d3/d3-contour

## 5. 시간

14. 기간 선택(합산) → 토폴로지·목록·카드·등고선. 시점 슬라이더(분) → 지도 배 위치(그 시각 직전 마지막 보고, 기간 안). 시점을 옮겨도 합산 쪽은 안 바뀐다(두 모드가 충돌하지 않게). 응답은 기간·시점별 캐시.

## 6. 검사·캡처·문서·금지

15. 검사 스크립트 `tests/`: (a) API 응답의 위협 등급 수·비정상 비율이 parquet 에서 직접 센 값과 같음(실해역·ds_015 각 1 기간) (b) 토폴로지 마디 합 = 전체 (c) `ships_at` 가 시점 직전 마지막 보고를 주는지 (d) 등고선 GeoJSON 이 유효하고 레벨이 §4 값인지 (e) 아이콘 회전 각이 선수와 같은지(단위 검사). 헤드리스 브라우저 캡처 4장 `docs/screenshots/coast_{dashboard,topology,ship_detail,contours}.png`.
16. 문서: `README.md`(목적·실행·설정·구조·확장 방법 = LiveProvider 자리), `docs/2026-10-27-coast-ui-CHANGES.md`(만든 것·전/후 없음이므로 "한 것"·검사 결과·캡처·못 한 것·설계값 표), `docs/SIGNAL_QUALITY_BASIS.md`(§4-13).
17. 금지: `../ais_integrity_ml_all` 아래 어떤 파일도 수정 금지(읽기만) · 절대경로/호스트 하드코딩 · 비밀번호 출력(`grep -v -i password`) · **git commit/push 하지 말 것**(코디네이터가 사용자 확인 뒤) · 검사용 서버는 끝나면 반드시 내리고 남긴 것은 보고.

## 7. 보고

18. `worker_done` 은 사용자가 읽는다 — 한국어, ML 초심자 기준: (1) 만든 화면과 구조(제공자 층·확장 자리) (2) 지도 아이콘·색 매핑 (3) 토폴로지 구성 (4) 신호 품질 등고선 — 값과 **출처** (5) 검사 결과 (6) 실행 방법·캡처 경로 (7) 남긴 것(서버·백그라운드) (8) 못 한 것·설계값.
