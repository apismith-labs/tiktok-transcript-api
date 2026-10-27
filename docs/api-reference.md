# API reference

The examples call the fixed Apify Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper):

- Actor API ID: `apple_yang~tiktok-transcripts-scraper`
- API host: `api.apify.com`
- One Run input: a single `videoUrl` string

The examples send the minimal input:

```json
{
  "videoUrl": "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
}
```

The Actor does not accept a URL array. Batch examples start one Run per valid
CSV row from the client.

## Run and Dataset flow

1. Create a Run with `POST /v2/actors/apple_yang~tiktok-transcripts-scraper/runs`.
2. Read the Run by its returned Run ID. The Run resource response has a `data`
   object containing `id`, `status`, and, after completion,
   `defaultDatasetId`.
3. Once the Run is `SUCCEEDED`, read
   `GET /v2/datasets/{defaultDatasetId}/items`. Dataset Items are a JSON array.

`SUCCEEDED` only describes the Run. It does not prove that a Dataset item or
usable transcript exists. Check the Dataset response, `text`, and `errMsg`.
The examples report Run failures, missing/empty Dataset results, missing or
blank transcript text, and non-empty `errMsg` separately.

A create request is sent once by the client; that does not guarantee
server-side exactly-once creation. If the request response is uncertain, first
check Apify Console and do not automatically submit another POST. After a wait
timeout, use the same Run ID to continue reading status.

## Public Output schema

The [Actor Output schema](https://apify.com/apple_yang/tiktok-transcripts-scraper/output-schema)
currently lists these fields and types. Values are generated from TikTok data
and can vary by video and run; handle errors and empty transcript values.

| Field | Schema type | Notes |
| --- | --- | --- |
| `url` | string | Video URL field in the output schema. |
| `title` | string | Video title. |
| `createTime` | string | Creation-time value. |
| `playCount` | integer | Play count. |
| `commentCount` | integer | Comment count. |
| `diggCount` | integer | Like count. |
| `shareCount` | integer | Share count. |
| `collectCount` | integer | Collection count. |
| `duration` | number | Video duration. |
| `text` | string | Transcript text; may be empty when transcript is unavailable. |
| `segments` | object array | Timestamped transcript segments. An observed item has `start`, `end`, and `text`; check current output before relying on additional properties or units. |
| `nickname` | string | Creator nickname. |
| `avatarUri` | string | Avatar URI. |
| `signature` | string | Creator signature. |
| `secUid` | string | Creator identifier. |
| `followerCount` | integer | Follower count. |
| `followingCount` | integer | Following count. |
| `heartCount` | integer | Creator heart count. |
| `errMsg` | string | Actor processing error text; an empty value does not replace Run/Dataset checks. |
| `timestamp` | string | Fetch timestamp. |

`videoUrl` is the Actor input field, not a guaranteed output field.
`audioUrl` is not in the current public Output schema. Do not make application
logic depend on either as a Dataset output field.

## Inspect a generated Dataset

No live Dataset JSON is committed as a fixture. Single-video examples that
write files save complete Dataset Items under `sample-output/generated/`,
which Git ignores. Async `wait` commands that only report a summary do not
write Dataset files. For example, after a Python single-video run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

items = json.loads(Path("sample-output/generated/python-single-url-response.json").read_text(encoding="utf-8"))
print(json.dumps(items[0] if items else [], ensure_ascii=False, indent=2))
PY
```

Preserve raw items while integrating. Normalize only the fields your
application needs, and retain `errMsg` for records that did not produce usable
transcript text.
