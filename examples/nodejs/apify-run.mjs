import https from 'node:https';
import { existsSync } from 'node:fs';
import { loadEnvFile } from 'node:process';
import { once } from 'node:events';
import path from 'node:path';

export const TIKTOK_ACTOR_SLUG = 'apple_yang/tiktok-transcripts-scraper';
export const TIKTOK_ACTOR_API_ID = 'apple_yang~tiktok-transcripts-scraper';
export const DEFAULT_VIDEO_URL = 'https://www.tiktok.com/@carter.braydon/video/7647694374876319007';
export const DEFAULT_MAX_WAIT_SECONDS = 900;
export const MAX_MAX_WAIT_SECONDS = 86_400;
export const TERMINAL_RUN_STATUSES = new Set(['SUCCEEDED', 'FAILED', 'TIMED-OUT', 'ABORTED']);
export const RUN_CREATION_LIMITATION = 'Run creation uses one client-side send attempt; this does not guarantee exactly-once creation on the server.';

export class RunCreationUnknownError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = 'RunCreationUnknownError';
    this.outcomeUnknown = true;
  }
}

export class ApiRequestError extends Error {
  constructor(message, { statusCode, ...options } = {}) {
    super(message, options);
    this.name = 'ApiRequestError';
    this.statusCode = statusCode;
  }
}

export class WaitTimeoutError extends Error {
  constructor(runId, maxWaitMs) {
    super(`Wait limit reached after ${maxWaitMs / 1000} seconds. Run ${runId} may still be running; wait again with the same Run ID.`);
    this.name = 'WaitTimeoutError';
    this.runId = runId;
  }
}

export function validateTikTokVideoUrl(videoUrl) {
  if (typeof videoUrl !== 'string' || videoUrl.length === 0 || videoUrl !== videoUrl.trim()) {
    return 'videoUrl is empty or contains surrounding whitespace.';
  }
  let parsed;
  try {
    parsed = new URL(videoUrl);
  } catch {
    return 'videoUrl is not a valid TikTok video URL.';
  }
  const host = parsed.hostname.toLowerCase();
  if (parsed.protocol !== 'https:' || !(host === 'tiktok.com' || host.endsWith('.tiktok.com'))) {
    return 'videoUrl must be an HTTPS TikTok URL.';
  }
  if (!parsed.pathname.includes('/video/')) {
    return 'videoUrl must point to a TikTok video path containing /video/.';
  }
  return null;
}

export function parseMaxWaitSeconds(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 1 || seconds > MAX_MAX_WAIT_SECONDS) {
    throw new Error(`--max-wait must be a finite number from 1 to ${MAX_MAX_WAIT_SECONDS} seconds.`);
  }
  const milliseconds = seconds * 1000;
  if (!Number.isFinite(milliseconds)) {
    throw new Error(`--max-wait must be no more than ${MAX_MAX_WAIT_SECONDS} seconds.`);
  }
  return seconds;
}

export function validateMaxWaitMs(maxWaitMs) {
  if (!Number.isFinite(maxWaitMs) || maxWaitMs <= 0 || maxWaitMs > MAX_MAX_WAIT_SECONDS * 1000) {
    throw new Error(`Wait limit must be between 1 and ${MAX_MAX_WAIT_SECONDS} seconds.`);
  }
}

export function loadLocalEnv(repoRoot) {
  const envPath = path.join(repoRoot, '.env');
  if (existsSync(envPath)) loadEnvFile(envPath);
}

export function requireApifyToken(env = process.env) {
  if (typeof env.APIFY_TOKEN !== 'string' || env.APIFY_TOKEN.length === 0) {
    throw new Error('APIFY_TOKEN is required. Set it in .env or the environment.');
  }
  return env.APIFY_TOKEN;
}

export function redactToken(value, token) {
  const text = String(value);
  return typeof token === 'string' && token.length > 0 ? text.split(token).join('[REDACTED]') : text;
}

export function safeError(error, token) {
  return redactToken(error?.message ?? error, token);
}

export async function writeLine(line, stream = process.stdout) {
  if (!stream.write(`${line}\n`)) await once(stream, 'drain');
}

function requestJson({ method, requestPath, token, body }, requestImpl = https.request) {
  const serializedBody = body === undefined ? undefined : JSON.stringify(body);
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/json',
  };
  if (serializedBody !== undefined) {
    headers['Content-Type'] = 'application/json';
    headers['Content-Length'] = Buffer.byteLength(serializedBody);
  }
  const requestOptions = {
    hostname: 'api.apify.com',
    port: 443,
    path: requestPath,
    method,
    headers,
  };

  return new Promise((resolve, reject) => {
    let settled = false;
    const fail = (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    let request;
    try {
      request = requestImpl(requestOptions, (response) => {
        let responseBody = '';
        response.setEncoding?.('utf8');
        response.on('data', (chunk) => { responseBody += chunk; });
        response.on('error', fail);
        response.on('end', () => {
          if (settled) return;
          settled = true;
          const statusCode = response.statusCode ?? 0;
          if (statusCode < 200 || statusCode >= 300) {
            reject(new ApiRequestError(`Apify API returned HTTP ${statusCode}.`, { statusCode }));
            return;
          }
          try {
            resolve(responseBody.length ? JSON.parse(responseBody) : null);
          } catch (error) {
            reject(new ApiRequestError('Apify API returned an invalid JSON response.', { statusCode, cause: error }));
          }
        });
      });
    } catch (error) {
      fail(error);
      return;
    }
    request.on('error', fail);
    request.setTimeout?.(30_000, () => request.destroy(new Error('Apify API request timed out.')));
    request.end(serializedBody);
  });
}

export async function startActorRunOnce(token, videoUrl, { requestImpl = https.request } = {}) {
  // No SDK or transport retry is configured for this POST. One client send attempt cannot guarantee server-side exactly-once creation.
  const validationError = validateTikTokVideoUrl(videoUrl);
  if (validationError) throw new Error(`Input error: ${validationError}`);
  const requestPath = `/v2/actors/${encodeURIComponent(TIKTOK_ACTOR_API_ID).replace('%7E', '~')}/runs`;
  let payload;
  try {
    payload = await requestJson({ method: 'POST', requestPath, token, body: { videoUrl } }, requestImpl);
  } catch (error) {
    throw new RunCreationUnknownError(
      `Run creation result is unknown; the Run may already have been created. Check Apify Console before retrying or starting another Run. Details: ${safeError(error, token)}`,
      { cause: error },
    );
  }

  let run;
  let structureError;
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    structureError = 'top-level JSON must be an object';
  } else if (Object.hasOwn(payload, 'data') && (!payload.data || typeof payload.data !== 'object' || Array.isArray(payload.data))) {
    structureError = "the 'data' field must be an object";
  } else {
    run = Object.hasOwn(payload, 'data') ? payload.data : payload;
    if (typeof run.id !== 'string' || run.id.trim().length === 0) structureError = 'a non-empty string Run ID is required';
  }
  if (structureError) {
    throw new RunCreationUnknownError(
      `Apify accepted the Run creation request but returned an unreadable Run ID (${structureError}); the Run may already have been created. Check Apify Console before retrying.`,
    );
  }
  return run;
}

export async function getRun(token, runId, { requestImpl = https.request } = {}) {
  if (typeof runId !== 'string' || runId.trim().length === 0) throw new Error('Run ID must be a non-empty string.');
  const response = await requestJson({ method: 'GET', requestPath: `/v2/actor-runs/${encodeURIComponent(runId)}`, token }, requestImpl);
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new ApiRequestError('Apify Run API response must be an object containing a data object.');
  }
  if (!Object.hasOwn(response, 'data') || !response.data || typeof response.data !== 'object' || Array.isArray(response.data)) {
    throw new ApiRequestError("Apify Run API response is malformed: expected an object in the 'data' field.");
  }
  const run = response.data;
  if (typeof run.id !== 'string' || run.id.trim().length === 0) {
    throw new ApiRequestError("Apify Run API response is malformed: 'data.id' must be a non-empty string.");
  }
  if (run.id !== runId) {
    throw new ApiRequestError(`Apify Run API response ID does not match requested Run ID ${runId}.`);
  }
  if (typeof run.status !== 'string' || run.status.trim().length === 0) {
    throw new ApiRequestError("Apify Run API response is malformed: 'data.status' must be a non-empty string.");
  }
  if (Object.hasOwn(run, 'defaultDatasetId') && run.defaultDatasetId !== null
    && (typeof run.defaultDatasetId !== 'string' || run.defaultDatasetId.trim().length === 0)) {
    throw new ApiRequestError("Apify Run API response is malformed: 'data.defaultDatasetId' must be a non-empty string when present.");
  }
  return run;
}

export async function getDatasetItems(token, datasetId, { requestImpl = https.request } = {}) {
  if (typeof datasetId !== 'string' || datasetId.trim().length === 0) throw new Error('Dataset ID must be a non-empty string.');
  const result = await requestJson({
    method: 'GET',
    requestPath: `/v2/datasets/${encodeURIComponent(datasetId)}/items?format=json`,
    token,
  }, requestImpl);
  if (!Array.isArray(result)) throw new ApiRequestError('Dataset response is not a JSON array.');
  return result;
}

export function inspectTranscript(items) {
  const text = items.find((item) => item?.text !== undefined && item?.text !== null)?.text;
  const errMsg = items.find((item) => item?.errMsg !== undefined && item?.errMsg !== null)?.errMsg;
  const problems = [];
  if (typeof text !== 'string' || text.trim().length === 0) problems.push('transcript text is empty or missing');
  if (errMsg !== '' && errMsg !== undefined && errMsg !== null) problems.push(`Actor errMsg is non-empty: ${errMsg}`);
  return { text: typeof text === 'string' ? text : '', errMsg: errMsg ?? '', problems };
}

export function assertSuccessfulDataset(run, items) {
  if (!run || run.status !== 'SUCCEEDED') throw new Error(`Actor Run finished with failure status ${run?.status ?? 'unknown'}.`);
  if (!run.defaultDatasetId) throw new Error('Dataset error: completed Run has no default Dataset ID.');
  if (!Array.isArray(items) || items.length === 0) throw new Error('Dataset is empty: Run completed but returned no items.');
  const transcript = inspectTranscript(items);
  if (transcript.problems.length) throw new Error(`Transcript failure: ${transcript.problems.join('; ')}`);
  return transcript;
}

export async function waitForRun(token, runId, {
  maxWaitMs = 900_000,
  pollIntervalMs = 5_000,
  requestImpl = https.request,
  getRunFn = getRun,
} = {}) {
  validateMaxWaitMs(maxWaitMs);
  const startedAt = Date.now();
  while (true) {
    const run = await getRunFn(token, runId, { requestImpl });
    if (!run || typeof run !== 'object') throw new ApiRequestError(`Run ${runId} could not be read.`);
    if (TERMINAL_RUN_STATUSES.has(run.status)) return run;
    const remaining = maxWaitMs - (Date.now() - startedAt);
    if (remaining <= 0) throw new WaitTimeoutError(runId, maxWaitMs);
    await new Promise((resolve) => setTimeout(resolve, Math.min(pollIntervalMs, remaining)));
  }
}
