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

## 설치

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # https://console.anthropic.com 에서 발급
```

## 사용법

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

### 주제 목록 (`topics.csv`)

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
