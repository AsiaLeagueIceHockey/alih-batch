# ALIH-BATCH 프로젝트 컨텍스트

> 주의: 아래 내용 일부는 2025-26 기준의 과거 구조를 설명한다. 2026-27의 실제 production 상태, 시즌별 identity, 비활성 workflow, 신규 `score_url`, migration 및 런칭 순서는 반드시 `../alih/docs/2026-27-operations-audit.md`를 우선한다.

> 이 문서는 `alih-batch` 프로젝트의 구조와 기능을 설명하며, 향후 개발 작업 시 참조할 수 있도록 작성되었습니다.

## 📋 프로젝트 개요

- **프로젝트명**: alih-batch
- **설명**: 아시아리그 아이스하키 공식 홈페이지에서 경기/순위 정보 등을 배치(Batch) 방식으로 크롤링하여 Supabase에 저장하는 데이터 파이프라인
- **데이터 소스**: `alhockey.com`, `asiaicehockey.com`, `news.google.com` RSS
- **데이터 저장소**: Supabase (PostgreSQL)

---

## 🏗️ 디렉토리 구조

```
alih-batch/
├── .github/
│   └── workflows/             # GitHub Actions 워크플로우 정의
│       ├── capture-instagram.yaml # 인스타그램 캡처 + AI 멘트 (매일 21:00 KST)
│       ├── live-news.yaml     # 뉴스 스크래핑 (매시 정각)
│       ├── parse-gamesheet.yaml  # 경기 상세 정보 스크래핑 (20분 간격)
│       ├── update-standings.yaml  # 순위표 업데이트 (30분 간격)
│       └── update-stat.yaml   # 선수 통계 업데이트 (매시 정각)
├── node_modules/              # Node.js 의존성
├── capture.py                 # 인스타그램 캡처 + AI 멘트 + Slack 알림
├── change-news-url.py         # 뉴스 URL 리다이렉트 테스트 유틸리티
├── live-game.ts               # Supabase Edge Function용 라이브 스코어 폴링 (미사용)
├── package.json               # Node.js 프로젝트 메타데이터
├── README.md                  # 간단한 프로젝트 설명
├── scrape-news.py             # 뉴스 스크래핑 스크립트
├── scrape-players.py          # 선수 정보 스크래핑 스크립트
├── scrape-standings.py        # 순위표 스크래핑 스크립트
├── scrape-stat.py             # 선수 통계 스크래핑 스크립트
├── scrape-highlights.py       # YouTube 하이라이트 스크래핑 스크립트
├── scrapeSingleGame.js        # 경기 상세 정보 스크래핑 스크립트 (메인)
└── update-live-url.py         # 경기 라이브 URL 자동 갱신 스크립트
```

---

## 📊 Supabase 테이블 구조

| 테이블명 | 설명 | 주요 컬럼 |
|---------|------|---------|
| `alih_teams` | 팀 정보 | `id`, `name`, `english_name`, `japanese_name`, `team_code`, `youtube_channel_id` |
| `alih_schedule` | 경기 일정 | `id`, `game_no`, `match_at`, `home_alih_team_id`, `away_alih_team_id`, `home_alih_team_score`, `away_alih_team_score`, `highlight_url`, `highlight_title`, `live_url` |
| `alih_game_details` | 경기 상세 정보 (로스터, 골, 페널티) | `game_no` (UNIQUE), `spectators`, `game_info`, `game_summary`, `goalkeepers`, `home_roster`, `away_roster`, `goals`, `penalties` |
| `alih_standings` | 팀 순위표 | `team_id` (UNIQUE), `rank`, `games_played`, `win_60min`, `win_ot`, `win_pss`, `lose_pss`, `lose_ot`, `lose_60min`, `goals_for`, `goals_against`, `points` |
| `alih_players` | 선수 정보 | `team_id`, `name` (UNIQUE), `jersey_number`, `position`, `games_played`, `points`, `goals`, `assists`, `shots`, `plus_minus`, `pim` |
| `alih_player_stats` | 선수 통계 랭킹 | `team_id`, `player_name` (UNIQUE), `goals`, `assists`, `points`, `goals_rank`, `assists_rank`, `points_rank` |
| `alih_news` | 뉴스 기사 | `origin_url` (UNIQUE), `title`, `summary`, `language`, `published_at` |

---

## 🔄 스크래핑 스크립트 상세

### 1. `scrapeSingleGame.js` (Node.js)

**목적**: 진행 중인 경기의 Game Sheet을 파싱하여 상세 정보를 저장

**데이터 소스**: `https://www.alhockey.com/sheet/47/game/ogs{game_no}.html`

**실행 주기**: 20분 간격 (GitHub Actions: `parse-gamesheet.yaml`)

**주요 기능**:
- Supabase `alih_schedule`에서 "진행 중" 경기 조회 (6시간 전 ~ 현재 사이 시작된 경기)
- 아시아리그 공식 사이트의 Game Sheet HTML 파싱 (Shift_JIS 인코딩)
- 홈/원정 로스터, 득점 기록, 페널티 기록, 골키퍼 기록 파싱
- `alih_game_details` 테이블에 Upsert
- `alih_schedule` 테이블에 최종 스코어 업데이트

**의존성**:
```json
{
  "@supabase/supabase-js": "^2.81.0",
  "axios": "^1.13.2",
  "cheerio": "^1.1.2",
  "iconv-lite": "^0.7.0"
}
```

**파싱 대상 데이터**:
| 구분 | 내용 |
|------|------|
| `game_info` | 경기장, 관중, 시작/종료 시간, 심판 정보, 코치 정보 |
| `game_summary` | 피리어드별 스코어(1P, 2P, 3P, OVT, PSS), SOG, PIM, PPG, SHG |
| `goalkeepers` | 골키퍼 세이브, 실점, 출전 시간 |
| `home_roster` / `away_roster` | 선수 번호, 이름, 포지션, SOG, 캡틴/어시스턴트 여부 |
| `goals` | 득점 시간, 득점자, 어시스트, 상황(EV/PP/SH) |
| `penalties` | 페널티 시간, 선수, 분, 위반 종류 |

---

### 2. `scrape-standings.py` (Python)

**목적**: 리그 순위표를 스크래핑하여 저장

**데이터 소스**: `https://www.alhockey.com/popup/47/standings.html`

**실행 주기**: 30분 간격 (GitHub Actions: `update-standings.yaml`)

**주요 기능**:
- Shift_JIS 인코딩의 HTML 파싱
- 팀 이름 매핑 (`HTML_TO_DB_TEAM_MAP`)을 통해 DB의 `alih_teams`와 연결
- `alih_standings` 테이블에 `team_id` 기준 Upsert

**의존성**: `requests`, `beautifulsoup4`, `supabase`

---

### 3. `scrape-stat.py` (Python)

**목적**: 선수별 득점/어시스트/포인트 랭킹을 스크래핑하여 저장

**데이터 소스**: `https://www.alhockey.com/popup/47/point_rank.html`

**실행 주기**: 매시 정각 (GitHub Actions: `update-stat.yaml`)

**주요 기능**:
- Goal Ranking, Assist Ranking, Points Ranking 테이블 파싱
- 데이터 상호 보정 로직: `Goals + Assists = Points` 공식으로 누락 데이터 보정
- `alih_player_stats` 테이블에 `team_id, player_name` 기준 Upsert

**팀 코드 매핑**: `team_code` (예: HLA, REH, NIB 등) 사용

**의존성**: `requests`, `beautifulsoup4`, `supabase`

---

### 4. `scrape-players.py` (Python)

**목적**: 전체 선수 정보를 스크래핑하여 저장

**데이터 소스**: `https://www.alhockey.com/popup/47/individual.html`

**실행 주기**: 매시 정각 (GitHub Actions: `update-stat.yaml`에서 함께 실행)

**주요 기능**:
- 팀별 선수 목록 파싱 (등번호, 이름, 포지션, 경기수, 골, 어시스트 등)
- `alih_players` 테이블에 `team_id, name` 기준 Upsert

**의존성**: `requests`, `beautifulsoup4`, `supabase`

---

### 5. `scrape-news.py` (Python)

**목적**: 아시아리그 관련 뉴스를 Google News RSS에서 수집

**데이터 소스**: Google News RSS (한국어/일본어/영어)

**실행 주기**: 매시 정각 (GitHub Actions: `live-news.yaml`)

**주요 기능**:
1. Google News RSS에서 최신 뉴스 수집
2. Playwright를 사용하여 Google News 리다이렉트 URL → 원본 URL 추출
3. 원본 URL에서 기사 본문 추출 (`BeautifulSoup`)
4. Gemini API로 80자 이내 한국어 요약 생성
5. 비한국어 제목은 `deep-translator`로 한국어 번역
6. `alih_news` 테이블에 `origin_url` 기준 Upsert

**RSS 피드 목록**:
- `HL안양` (ko)
- `아이스하키` (ko)
- `아시아리그 아이스하키` (ko)
- `Asia League Ice Hockey` (en)
- `アジアリーグアイスホッケー` (ja)

**의존성**: `feedparser`, `deep-translator`, `playwright`, `requests`, `beautifulsoup4`, `supabase`, `google-genai`

---

### 6. `scrape-highlights.py` (Python)

**목적**: YouTube 채널에서 경기 하이라이트 영상을 스크래핑하여 alih_schedule에 연결

**데이터 소스**: `https://www.youtube.com/@ALhockey_JP/videos`

**실행 주기**: 매시 30분 (GitHub Actions: `update-highlights.yaml`)

**주요 기능**:
1. `yt-dlp`로 YouTube 채널에서 최근 영상 목록 가져오기
2. 영상 제목 파싱: `【YYYY.MM.DD】Team A vs Team B | Asia League Highlights |`
3. `alih_schedule`에서 날짜+팀 조합으로 경기 매칭
4. 일본어 제목을 한국어로 번역 (deep-translator)
5. `highlight_url`, `highlight_title` 필드 업데이트

**YouTube 팀명 매핑**:
| YouTube 팀명 | DB `english_name` |
|------------|-------------------|
| HL Anyang | HL ANYANG |
| Nikko IceBucks | ICEBUCKS |
| Tohoku FreeBlades | FREEBLADES |
| Stars Kobe | STARS |
| Yokohama Grits | GRITS |
| Red Eagles Hokkaido | EAGLES |

**의존성**: `yt-dlp`, `deep-translator`, `supabase`

---

### 7. `live-game.ts` (Deno/TypeScript)

**목적**: Supabase Edge Function으로 실시간 경기 스코어 폴링

**데이터 소스**: `https://asiaicehockey.com/score/{game_no + 20388}`

**상태**: 현재 미사용 (GitHub Actions 방식으로 대체됨)

**주요 기능**:
- 라이브 스코어 페이지 파싱
- 피리어드별 스코어 합산 (1P, 2P, 3P, OVT, PSS)
- `alih_schedule`과 `alih_game_details` 동시 업데이트

---

### 8. `capture.py` (Python)

**목적**: 인스타그램용 경기 Preview/Result 이미지 캡처 및 AI 멘트 생성

**데이터 소스**: 
- `https://alhockey.fans/instagram/preview?game_no={game_no}` (Preview)
- `https://alhockey.fans/instagram/score?game_no={game_no}` (Result)

**실행 주기**: 매일 21:00 KST (GitHub Actions: `capture-instagram.yaml`)

**주요 기능**:
1. Supabase에서 오늘/내일 경기 일정 조회
2. Playwright로 인스타그램 비율(1080x1350) 스크린샷 캡처
3. Groq AI (`openai/gpt-oss-120b`)로 팀 컨텍스트 포함 멘트 생성
4. Slack Webhook으로 이미지 + 멘트 알림 전송

**AI 멘트 생성 로직**:
- `alih_teams`에서 한국어 팀명 조회하여 프롬프트에 포함
- `alih_standings`에서 순위 정보 조회하여 경기 분석에 활용
- Preview: 기대포인트 중심 / Result: 경기 결과 분석 중심

**의존성**: `playwright`, `supabase`, `groq`, `requests`

---

### 9. `update-live-url.py` (Python)

**목적**: 경기 시작 전 홈팀 유튜브 채널에서 라이브 스트림을 검색하여 `live_url` 자동 갱신

**실행 주기**: 15분 간격 (GitHub Actions: `update-live-url.yaml`)

**지원 팀** (홈팀 기준):
| 팀명 | 유튜브 채널 | 언어 |
|------|-------------|------|
| HL Anyang | `@hlanyang` | 한국어 |
| RED EAGLES HOKKAIDO | `@OjiEaglesFan` | 일본어 |
| TOHOKU FREE BLADES | `@freeblades2009` | 일본어 |
| YOKOHAMA GRITS | `@grits5937` | 일본어 |

**주요 기능**:
1. `alih_schedule`에서 향후 6시간 이내 시작, `live_url` 없는 경기 조회
2. 홈팀 유튜브 채널의 `/streams` 페이지에서 라이브/예정 스트림 검색
3. 스트림 제목에서 상대팀 키워드 또는 경기 날짜 매칭
4. 매칭 성공 시 `alih_schedule.live_url` 업데이트

**매칭 전략**:
- 한국어, 영어, 일본어 팀명 키워드로 상대팀 매칭
- 날짜 패턴 (YYYY.MM.DD, MM/DD 등)으로 경기 날짜 매칭
- 라이브 관련 키워드 (live, ライブ, 生放送, vs, 試合 등) 확인

**의존성**: `supabase`, `yt-dlp`

---

### 10. `x_content.py` (Python)

**목적**: X(Twitter) 일본어 컨텐츠 자동 생성 (@alhockey_fans 계정용)

**실행 주기**: 
- Series Review: 매주 일요일 20:00 KST
- Series Preview: 매주 목요일 20:00 KST

**주요 기능**:
1. `alih_schedule`에서 지난/다음 주 경기 조회
2. `alih_teams`에서 일본어 팀명 조회
3. Groq AI로 일본어 컨텐츠 생성
4. 경기별 링크 포함: `https://alhockey.fans/schedule/{game_no}?lang=jp`
5. Slack Webhook으로 컨텐츠 전송 (복사하여 X에 게시)

**컨텐츠 유형**:
| 유형 | 발행일 | 내용 |
|------|--------|------|
| Review | 일요일 | 지난 주 경기 결과 요약, 순위 변동 |
| Preview | 목요일 | 다음 주 경기 예고, 관전 포인트 |

**의존성**: `supabase`, `groq`, `requests`

---

## ⚙️ GitHub Actions 워크플로우

| 워크플로우 | 스케줄 | 실행 스크립트 | 환경 |
|-----------|--------|--------------|------|
| `capture-instagram.yaml` | 매일 21:00 KST | `capture.py` | Python 3.10 + Playwright + Groq |
| `live-news.yaml` | 매시 정각 | `scrape-news.py` | Python 3.10 + Playwright |
| `parse-gamesheet.yaml` | 20분 간격 | `scrapeSingleGame.js` | Node.js 20 |
| `update-standings.yaml` | 30분 간격 | `scrape-standings.py` | Python 3.10 |
| `update-stat.yaml` | 매시 정각 | `scrape-stat.py`, `scrape-players.py` | Python 3.10 |
| `update-highlights.yaml` | 매시 30분 | `scrape-highlights.py` | Python 3.10 + yt-dlp |
| `x-content.yaml` | 일요일/목요일 20:00 KST | `x_content.py` | Python 3.10 + Groq |
| `update-live-url.yaml` | 15분 간격 | `update-live-url.py` | Python 3.10 + yt-dlp |

### GitHub Secrets 필요 변수:

| Secret 이름 | 설명 |
|------------|------|
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | Supabase Service Role Key (RLS 우회용) |
| `GEMINI_API_KEY` | Gemini API 키 (뉴스 요약용) |
| `GROQ_API_KEY` | Groq API 키 (인스타그램 멘트 생성용) |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL (알림용) |

---

## 🔗 팀 이름 매핑

HTML에서 사용하는 팀 이름과 DB의 팀 이름 간 매핑:

| HTML 팀명 | DB `english_name` |
|----------|-------------------|
| HL ANYANG ICE HOCKEY CLUB | HL ANYANG |
| RED EAGLES HOKKAIDO | EAGLES |
| NIKKO ICEBUCKS | ICEBUCKS |
| YOKOHAMA GRITS | GRITS |
| TOHOKU FREEBLADES | FREEBLADES |
| STARS KOBE | STARS |

---

## 🧰 개발 환경 설정

### Node.js 환경 (scrapeSingleGame.js)
```bash
npm install
```

### Python 환경
```bash
pip install requests beautifulsoup4 supabase feedparser deep-translator playwright google-genai
playwright install chromium
```

### 환경 변수 설정
```bash
export SUPABASE_URL="your_supabase_url"
export SUPABASE_SERVICE_KEY="your_service_key"
export GEMINI_API_KEY="your_gemini_api_key"  # 뉴스 스크래핑 시에만 필요
```

---

## 📝 주요 참고 사항

1. **인코딩**: `alhockey.com`의 HTML은 **Shift_JIS** 인코딩을 사용하므로 반드시 디코딩 처리 필요

2. **진행중 경기 판단**: `alih_schedule`에서 `match_at`이 현재 시간 기준 6시간 이내에 시작된 경기를 "진행중"으로 간주

3. **데이터 충돌 처리**: 모든 스크립트에서 **Upsert** 방식 사용 (`on_conflict`로 중복 키 처리)

4. **피리어드별 시간 계산** (`scrapeSingleGame.js`):
   - 1P: 00:00 ~ 19:59
   - 2P: 20:00 ~ 39:59
   - 3P: 40:00 ~ 59:59
   - OVT: 60:00 이상

5. **URL 리다이렉트 처리**: Google News RSS의 URL은 JavaScript 기반 리다이렉트를 사용하므로 Playwright 필요

---

## 🚀 향후 개선 가능 사항

1. **Error Handling 강화**: 네트워크 오류 시 재시도 로직 추가
2. **모니터링**: 스크래핑 실패 시 Slack/Discord 알림 연동
3. **데이터 검증**: 스크래핑된 데이터 무결성 검사 추가
4. **Edge Function 활용**: `live-game.ts`를 다시 활성화하여 더 빈번한 라이브 스코어 업데이트 가능
