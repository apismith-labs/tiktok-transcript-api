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
was checked on 2026-10-27 and currently lists the following fields and types.
The schema describes the declared output shape; it is not a guarantee that
every Run produces usable values. Values can be empty or unavailable, so
handle missing data and errors.

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
| `segments` | object array | The public schema declares an array of objects but does not declare item properties here. `start`, `end`, and `text` have appeared in an observed result; treat those child fields and any timing units as unverified until confirmed from the Dataset you use. |
| `nickname` | string | Creator nickname. |
| `avatarUri` | string | Avatar URI. |
| `signature` | string | Creator signature. |
| `secUid` | string | Creator identifier. |
| `followerCount` | integer | Follower count. |
| `followingCount` | integer | Following count. |
| `heartCount` | integer | Creator heart count. |
| `errMsg` | string | Actor processing error text; an empty value does not replace Run/Dataset checks. |
| `timestamp` | string | Fetch timestamp. |

`videoUrl` is the Actor input field, not a guaranteed output field. `url` is
the field currently listed by the output schema. `audioUrl` is not in the
public Output schema. Do not make application logic depend on `videoUrl` or
`audioUrl` as Dataset fields.

The schema and one observed response are different evidence: check the Dataset
from your own Run before depending on optional values. The repository's
offline tests validate client behavior with fake responses; they do not
validate a live Actor response.

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
