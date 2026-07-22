# CG Conference Timeline — automatic edition

CCCG, WADS, SWAT, STACS, SODA, SoCG, LATIN, ISAAC, FSTTCS, WALCOM, IWOCA, FOCS, STOC, SEA의 CFP와 개최 일정을 보여주는 정적 웹사이트입니다.

이 버전은 GitHub Pages에 배포하면 **매일 오전 9시 7분(KST)** GitHub Actions가 일정을 확인하고, 검증된 변경만 자동 반영합니다. 별도 유료 서버나 API 키는 필요하지 않습니다.

## 자동 수집 순서

1. WikiCFP에서 `학회 약어 + 연도`를 검색합니다.
2. 약어, 연도, 정식 학회명 일치도를 검사해 동명이인 행사를 제외합니다.
3. WikiCFP 항목에 공식 홈페이지 링크가 있으면 그 페이지를 함께 검사합니다.
4. WikiCFP에서 검색되지 않으면 기존 시리즈 홈페이지에서 해당 연도의 링크를 탐색합니다.
5. 그래도 찾지 못하면 DuckDuckGo HTML 검색으로 공식 홈페이지 후보를 찾습니다.
6. 공식 도메인, 학회명, 약어, 연도를 검증한 뒤 날짜와 장소를 추출합니다.
7. 새 정보가 모호하거나 기존 확정값과 충돌하면 자동으로 덮어쓰지 않고 기존 값을 유지합니다.

WADS처럼 WikiCFP에서 현재 연도가 검색되지 않는 학회는 `https://www.wads.org/`를 시작점으로 연도별 공식 페이지를 찾습니다.

## WikiCFP 이용 방식

WikiCFP 검색 URL은 다음 형식입니다.

```text
https://www.wikicfp.com/cfp/servlet/tool.search?q=WADS+2027&year=t
```

WikiCFP의 크롤러 안내에 맞춰 요청 사이에 **최소 5.2초** 간격을 둡니다. 따라서 전체 확인에는 몇 분이 걸릴 수 있지만 GitHub Actions가 서버에서 실행하므로 사용자가 기다릴 필요는 없습니다.

## GitHub에서 배포하기

1. 이 폴더의 파일을 새 GitHub 저장소에 올립니다.
2. 저장소의 **Settings → Pages**로 이동합니다.
3. **Build and deployment → Source**를 `GitHub Actions`로 선택합니다.
4. **Actions** 탭에서 `Daily CFP update and Pages deploy`를 한 번 수동 실행합니다.
5. 이후 매일 오전 9시 7분(KST)에 자동 확인 및 배포됩니다.

저장소가 비공개인 경우 계정 플랜에 따라 GitHub Pages 사용 조건이 달라질 수 있습니다.

## 로컬 실행

```bash
python3 -m http.server 8000
```

브라우저에서 `http://localhost:8000`을 엽니다. 파일을 직접 열 수도 있지만 브라우저에 따라 로컬 스크립트 정책이 다를 수 있어 간단한 로컬 서버 사용을 권장합니다.

## 수동으로 자동 갱신 시험하기

```bash
python -m pip install -r requirements.txt
python scripts/update_conferences.py --verbose
python scripts/build_single_html.py
```

`data.json`이 원본 데이터이고, `data.js`는 웹사이트에서 바로 읽기 위한 자동 생성 파일입니다.

## 학회별 검색 설정

`conference_sources.json`에서 다음을 관리합니다.

- `aliases`: 과거 또는 대체 정식 명칭
- `seriesHomepage`: 매년 바뀌는 홈페이지를 찾기 위한 고정 시작점
- `officialDomains`: 공식 홈페이지 판별에 사용할 허용 도메인
- `years`: 격년 학회의 홀수/짝수 연도 제한

## 안전장치와 한계

- WikiCFP는 사용자 기여 데이터이므로 공식 홈페이지에서 찾은 값을 우선합니다.
- 날짜 추출이 애매하면 기존 값이 유지됩니다.
- PDF 안에만 CFP가 있거나, JavaScript로만 내용을 표시하거나, 봇 접속을 차단하는 사이트는 자동 추출에 실패할 수 있습니다.
- 실패한 학회는 Actions 실행 요약의 `failures`에 기록되고 다른 학회 업데이트는 계속 진행됩니다.
- 웹 검색 결과가 없거나 공식성 검증을 통과하지 못하면 추정값을 새로 만들지 않습니다.

## 파일 구조

```text
.
├── index.html
├── styles.css
├── app.js
├── data.json
├── data.js
├── conference_sources.json
├── requirements.txt
├── scripts/
│   ├── update_conferences.py
│   ├── build_single_html.py
│   └── build_site.py
└── .github/workflows/
    └── daily-update.yml
```
