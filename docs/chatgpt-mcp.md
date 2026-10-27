# ChatGPT MCP Setup for TikTok Transcript API

This guide shows how to manually configure ChatGPT to use the TikTok transcripts
Actor through Apify MCP.

This repository does not directly configure ChatGPT or provide a ready-made
ChatGPT connector. This is a manual configuration guide for accounts where MCP
or custom connectors are available.

## Before you start

- ChatGPT account with Developer Mode or custom connectors available
- Apify account
- Apify MCP connection
- Access to the Actor `apple_yang/tiktok-transcripts-scraper`
- Public TikTok video URL

Availability can depend on account plan, workspace settings, admin permissions,
region, and rollout status. If the create option is not visible, Developer Mode
may need to be enabled or your account may not have access yet.

For the central MCP reference, see [Apify MCP setup](apify-mcp.md).

## Step-by-step setup

1. Open ChatGPT settings.
2. Go to Apps, Apps & Connectors, or the equivalent connector area for your
   account.
3. Create a new custom connector.
4. Fill in the connector fields:

   - Name: `apify-tiktok-transcripts`
   - Description: `Run the TikTok transcripts Apify Actor and retrieve transcript output.`
   - MCP Server URL: `https://mcp.apify.com?tools=apple_yang/tiktok-transcripts-scraper`
   - Authentication: OAuth, when available

5. If the UI asks for the MCP server URL separately, use:

   ```text
   https://mcp.apify.com?tools=apple_yang/tiktok-transcripts-scraper
   ```

6. Use OAuth if available.
7. Authorize Apify in the browser when prompted.
8. Start a new chat.
9. Add or select the connector.
10. Run the test prompt below.

Exact ChatGPT UI labels may vary by account, workspace, and feature rollout.
ChatGPT may not allow changing selected MCP tools after connector creation. If
you need different tools later, create a new connector.

## Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
}
```

## Test prompt

```text
Use Apify MCP to run the Actor `apple_yang/tiktok-transcripts-scraper` with this input:

{
  "videoUrl": "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
}

After the Actor run finishes, retrieve the dataset output and return:

- transcript text
- title
- creator nickname
- duration
- play count
- any `errMsg`
```

## What to ask ChatGPT after extraction

After ChatGPT retrieves the transcript output, ask for tasks such as:

- Summarize the transcript.
- Extract the opening hook.
- Classify the content by topic or format.
- Identify product or brand mentions.
- Generate structured insights as JSON.
- Turn the transcript into a content brief.
- Compare the transcript with other saved outputs.

## Troubleshooting

### Connector not visible

- Confirm custom connectors are available for your account.
- Check whether the connector was enabled for the current chat or workspace.
- Restart the chat after saving connector settings.

### Developer Mode unavailable

- Your account or workspace may not have access to the required feature.
- Use the local examples in this repository or another MCP-capable client.

### Tool not listed

- Confirm the MCP server URL includes
  `?tools=apple_yang/tiktok-transcripts-scraper`.
- Reconnect the connector.
- Ask ChatGPT to list available MCP tools.

### Authorization failed

- Re-run the Apify OAuth flow.
- Confirm you are signing in with the intended Apify account.
- If using token-based configuration in another client, confirm the token is
  valid.

### Actor returns empty transcript

- Try another public TikTok video URL.
- Ask ChatGPT to return the raw dataset item, including `errMsg`.
- Treat transcript availability as video-dependent.

### Full dataset output not shown

Use a follow-up prompt:

```text
Retrieve the full dataset output for the Actor run and show the raw fields before summarizing.
```
