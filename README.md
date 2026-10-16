# Qawsqazx — AI 블로그 자동화

주제 목록(`topics.csv`)을 넣어두면 Claude가 블로그 글을 쓰고, Markdown 파일로 저장·발행합니다.
GitHub Actions로 매일 자동 실행할 수도 있습니다.

```
topics.csv ──▶ Claude로 글 생성 ──▶ drafts/ (초안) ──▶ posts/ (발행) ──▶ (선택) 웹훅 POST
```

- 생성된 파일은 `YYYY-MM-DD-slug.md` 형식이고 front matter(제목, 날짜, 설명, 태그)를 포함합니다.
  Jekyll, Hugo, Astro, Gatsby 같은 정적 블로그에 그대로 쓸 수 있습니다.
- 웹훅 URL을 설정하면 발행할 때 글을 JSON으로 보냅니다. Zapier, Make, n8n 등에 연결해
  WordPress나 다른 플랫폼으로 넘길 수 있습니다.

## 웹/휴대폰에서 쓰기 (설치 필요 없음)

### 1. 처음 한 번만: API 키 준비

1. https://console.anthropic.com 에 가입하고 로그인합니다.
2. **Billing**에서 결제 수단을 등록하고 크레딧을 충전합니다. (사용한 만큼 요금이 나가요)
3. **API Keys → Create Key**로 키를 만들고 `sk-ant-...`로 시작하는 값을 복사합니다.
   이 값은 다시 볼 수 없으니 바로 다음 단계로 넘어가세요. 다른 사람에게 보여주면 안 돼요.
4. GitHub 저장소에서 **Settings → Secrets and variables → Actions → New repository secret**을 누릅니다.
5. Name에 `ANTHROPIC_API_KEY`, Secret에 복사한 키를 넣고 저장합니다.

### 2. 글 쓰기

1. 저장소 상단의 **Actions** 탭 → 왼쪽 **Blog automation** → 오른쪽 **Run workflow**를 누릅니다.
2. **글 주제**에 원하는 주제를 적고(키워드는 선택) **Run workflow**를 누릅니다.
3. 1~3분 뒤 초록색 체크가 뜨면 완료입니다. 저장소의 `posts/` 폴더에서 새 글을 볼 수 있어요.
   (발행을 끄고 실행했다면 `drafts/` 폴더에 있어요)

### 3. 주제 목록으로 자동 연재

- 저장소에서 `topics.csv`를 열고 연필 아이콘으로 편집해 주제를 한 줄씩 추가합니다.
  새 줄은 `주제,키워드,pending,,` 형식으로 쓰면 됩니다.
- 매일 오전 9시에 대기 중인 주제로 글 1개가 자동으로 써집니다.
- 바로 돌리고 싶으면 **Run workflow**에서 주제를 비워두고 실행하면 목록에서 가져다 씁니다.

## 내 컴퓨터에서 쓰기

### 설치

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # https://console.anthropic.com 에서 발급
```

### 사용법

```bash
# 주제 하나로 바로 글 쓰기
python -m blog_auto write "제주도 3박 4일 여행 코스" --keywords "제주 여행, 렌터카"

# topics.csv의 대기(pending) 주제를 일괄 처리
python -m blog_auto run --limit 3            # 초안만 생성 (drafts/)
python -m blog_auto run --limit 3 --publish  # 생성 후 바로 발행 (posts/)
python -m blog_auto run --retry-failed       # 실패한 주제 다시 시도

# 초안 검토 후 발행
python -m blog_auto publish                  # drafts/ 전부 발행
python -m blog_auto publish drafts/2026-10-16-my-post.md

# 진행 현황
python -m blog_auto status
```

### 주제 목록 형식 (`topics.csv`)

| 열 | 설명 |
|---|---|
| `topic` | 글 주제 (필수) |
| `keywords` | 글에 넣을 키워드 (선택) |
| `status` | `pending` → `drafted` → `published`, 실패 시 `failed` (자동 갱신) |
| `file` | 생성된 파일 경로 (자동 기록) |
| `updated_at` | 마지막 처리 시각 (자동 기록) |

새 주제는 `topic`만 채워서 줄을 추가하면 됩니다.

### 설정 (`config.yaml`)

| 키 | 기본값 | 설명 |
|---|---|---|
| `model` | `claude-opus-5-5` | 사용할 Claude 모델 |
| `effort` | `medium` | 생각 깊이: `low`~`max`. 높을수록 품질↑ 비용↑ |
| `language`, `tone`, `target_length` | 한국어 / 친근하게 / 2000자 | 글 스타일 |
| `posts_per_run` | `1` | `run` 한 번에 만들 글 수 |
| `auto_publish` | `false` | `true`면 생성 즉시 발행 |
| `webhook_url` | 비어 있음 | 발행 시 POST할 URL. 환경 변수 `BLOG_WEBHOOK_URL`이 우선 |

## 예약 실행 (GitHub Actions)

`.github/workflows/blog-auto.yml`이 매일 09:00(KST)에 글 1개를 생성·발행하고 결과를 저장소에 커밋합니다.

1. 저장소 **Settings → Secrets and variables → Actions**에 `ANTHROPIC_API_KEY`를 추가합니다.
   (웹훅을 쓰면 `BLOG_WEBHOOK_URL`도 추가)
2. 주기를 바꾸려면 워크플로의 `cron` 값을 수정합니다.
3. **Actions → Blog automation → Run workflow**로 바로 실행해 볼 수도 있습니다.

로컬 PC에서 돌리려면 cron에 등록하세요:

```cron
0 9 * * * cd /path/to/Qawsqazx && python -m blog_auto run --publish >> blog.log 2>&1
```

## 테스트

```bash
pip install pytest
python -m pytest
```

테스트는 가짜 생성기를 써서 API 키 없이 돌아갑니다.
