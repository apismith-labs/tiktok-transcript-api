# Prompt Recipes for TikTok Transcript Analysis

Use these prompts after extracting transcript data with the Apify Actor
`apple_yang/tiktok-transcripts-scraper`.

Assume your application passes some or all of these fields:

- `{{text}}`
- `{{segments}}`
- `{{title}}`
- `{{nickname}}`
- `{{playCount}}`
- `{{commentCount}}`
- `{{diggCount}}`
- `{{shareCount}}`
- `{{url}}` (the public Output schema field, when present)

## Summarize a TikTok video

```text
Summarize this TikTok transcript in 5 bullet points.

Creator: {{nickname}}
Title: {{title}}
Transcript:
{{text}}

Include the main topic, key claims, and final takeaway.
```

## Extract hooks

```text
Analyze this TikTok transcript and extract:
- Opening hook
- Main promise or argument
- Emotional trigger
- Call to action, if present
- Whether the hook is clear within the first few seconds

Transcript:
{{text}}
```

## Identify content structure

```text
Identify the structure of this TikTok video.

Transcript:
{{text}}

Return:
- Hook
- Setup
- Main points
- Proof or examples
- Ending
- Call to action
```

## Generate title ideas

```text
Generate 10 title ideas for this TikTok transcript.

Transcript:
{{text}}

Keep titles concise, specific, and suitable for short-form video analysis.
```

## Convert transcript into a blog outline

```text
Turn this TikTok transcript into a blog post outline.

Transcript:
{{text}}

Return:
- SEO-friendly title
- Suggested introduction
- H2/H3 outline
- Key examples to include
- Suggested conclusion
```

## Extract product mentions

```text
Extract all product, brand, feature, and offer mentions from this TikTok
transcript.

Title: {{title}}
Transcript:
{{text}}

Return a table with:
- Mention
- Type
- Exact phrase
- Context
- Sentiment or framing
```

## Analyze creator style

```text
Analyze this creator's style based on the transcript.

Creator: {{nickname}}
Transcript:
{{text}}

Return:
- Tone
- Pacing cues
- Repeated phrases
- Audience assumptions
- Content strengths
- Ideas that could inspire future content without copying
```

## Classify sentiment

```text
Classify the sentiment and emotional framing of this TikTok transcript.

Transcript:
{{text}}

Return:
- Overall sentiment
- Emotional drivers
- Positive phrases
- Negative or risk-related phrases
- Neutral factual claims
```

## Generate subtitles or captions

```text
Create subtitle-friendly lines from this transcript.

Segments, if available:
{{segments}}

Transcript:
{{text}}

Return short readable lines. Preserve the meaning and avoid adding claims that
are not in the transcript.
```
