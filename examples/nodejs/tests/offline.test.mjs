import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import {
  DEFAULT_MAX_WAIT_SECONDS,
  DEFAULT_VIDEO_URL,
  MAX_MAX_WAIT_SECONDS,
  ApiRequestError,
  RunCreationUnknownError,
  assertSuccessfulDataset,
  getDatasetItems,
  getRun,
  parseMaxWaitSeconds,
  startActorRunOnce,
  WaitTimeoutError,
  waitForRun,
} from '../apify-run.mjs';
import { main as asyncMain, parseCommandArgs as parseAsyncArgs, startRun, waitAndReadRun } from '../async-run.mjs';
import { parseCommandArgs as parseCsvArgs, printSummary, processCsv, reconcile, stableKey } from '../csv-batch.mjs';
import { main as singleMain, resolveSingleArgs, resolveVideoUrlArgs, runSingleVideo } from '../single-url.mjs';

const TEST_TOKEN = 'offline-test-secret';
const TEST_URL = 'https://www.tiktok.com/@offline/video/1234567890123456789';

function tempDirectory() {
  return mkdtempSync(path.join(os.tmpdir(), 'tiktok-node-offline-'));
}

function fakeTransport({ body = '{"data":{"id":"run-1","status":"READY"}}', statusCode = 201, onEnd } = {}) {
  const calls = [];
  const requestImpl = (options, callback) => {
    const request = new EventEmitter();
    request.setTimeout = () => {};
    request.destroy = (error) => queueMicrotask(() => request.emit('error', error));
    request.end = (requestBody) => {
      calls.push({ options, body: requestBody });
      onEnd?.({ options, body: requestBody });
      const response = new EventEmitter();
      response.statusCode = statusCode;
      callback(response);
      queueMicrotask(() => {
        if (body !== '') response.emit('data', Buffer.from(body));
        response.emit('end');
      });
    };
    return request;
  };
  return { requestImpl, calls };
}

test('Run creation builds the fixed single-URL POST and ignores legacy environment overrides', async () => {
  const fake = fakeTransport();
  const originalActor = process.env.APIFY_ACTOR_ID;
  const originalUrl = process.env.TIKTOK_VIDEO_URL;
  process.env.APIFY_ACTOR_ID = 'S9A11NvceWaGorwwh';
  process.env.TIKTOK_VIDEO_URL = 'https://www.tiktok.com/@wrong/video/111';
  try {
    const run = await startActorRunOnce(TEST_TOKEN, TEST_URL, { requestImpl: fake.requestImpl });
    assert.equal(run.id, 'run-1');
  } finally {
    if (originalActor === undefined) delete process.env.APIFY_ACTOR_ID;
    else process.env.APIFY_ACTOR_ID = originalActor;
    if (originalUrl === undefined) delete process.env.TIKTOK_VIDEO_URL;
    else process.env.TIKTOK_VIDEO_URL = originalUrl;
  }
  assert.equal(fake.calls.length, 1);
  const [{ options, body }] = fake.calls;
  assert.equal(options.hostname, 'api.apify.com');
  assert.equal(options.path, '/v2/actors/apple_yang~tiktok-transcripts-scraper/runs');
  assert.equal(options.method, 'POST');
  assert.deepEqual(JSON.parse(body), { videoUrl: TEST_URL });
  assert.equal(options.headers.Authorization, `Bearer ${TEST_TOKEN}`);
  assert.equal(options.path.includes(TEST_TOKEN), false);
});

test('2xx malformed creation responses are unknown and cause exactly one client request attempt', async (t) => {
  for (const body of ['null', '[]', '"ok"', '123', '{"data":null}', '{"data":[]}', '{"data":{"id":7}}']) {
    await t.test(body, async () => {
      const fake = fakeTransport({ body });
      await assert.rejects(
        startActorRunOnce(TEST_TOKEN, TEST_URL, { requestImpl: fake.requestImpl }),
        (error) => error instanceof RunCreationUnknownError && error.outcomeUnknown,
      );
      assert.equal(fake.calls.length, 1);
    });
  }
});

test('Run and Dataset reads use GET paths derived only from known IDs', async () => {
  const responses = [
    '{"data":{"id":"known run","status":"SUCCEEDED"}}',
    '[{"text":"result"}]',
  ];
  const requests = [];
  const requestImpl = (options, callback) => {
    requests.push(options);
    const request = new EventEmitter();
    request.setTimeout = () => {};
    request.end = () => {
      const response = new EventEmitter();
      response.statusCode = 200;
      callback(response);
      queueMicrotask(() => { response.emit('data', Buffer.from(responses.shift())); response.emit('end'); });
    };
    request.destroy = (error) => queueMicrotask(() => request.emit('error', error));
    return request;
  };
  await getRun(TEST_TOKEN, 'known run', { requestImpl });
  await getDatasetItems(TEST_TOKEN, 'known-dataset', { requestImpl });
  assert.deepEqual(requests.map(({ hostname, method, path: requestPath }) => [hostname, method, requestPath]), [
    ['api.apify.com', 'GET', '/v2/actor-runs/known%20run'],
    ['api.apify.com', 'GET', '/v2/datasets/known-dataset/items?format=json'],
  ]);
  assert.ok(requests.every(({ headers }) => headers.Authorization === `Bearer ${TEST_TOKEN}`));
  assert.ok(requests.every(({ path: requestPath }) => !requestPath.includes(TEST_TOKEN)));
});

test('getRun unwraps data and actual waitForRun stops polling at SUCCEEDED before reading Dataset Items', async () => {
  const requests = [];
  const requestImpl = (options, callback) => {
    requests.push(options);
    const request = new EventEmitter();
    request.setTimeout = () => {};
    request.destroy = (error) => queueMicrotask(() => request.emit('error', error));
    request.end = () => {
      const response = new EventEmitter();
      response.statusCode = 200;
      callback(response);
      let payload;
      if (options.path === '/v2/actor-runs/RUN123') {
        payload = { data: { id: 'RUN123', status: 'SUCCEEDED', defaultDatasetId: 'DS123' } };
      } else if (options.path === '/v2/datasets/DS123/items?format=json') {
        payload = [{ text: 'offline transcript', segments: [], errMsg: '' }];
      } else {
        throw new Error(`Unexpected fake request: ${options.path}`);
      }
      queueMicrotask(() => { response.emit('data', Buffer.from(JSON.stringify(payload))); response.emit('end'); });
    };
    return request;
  };
  const run = await getRun(TEST_TOKEN, 'RUN123', { requestImpl });
  assert.deepEqual(run, { id: 'RUN123', status: 'SUCCEEDED', defaultDatasetId: 'DS123' });

  requests.length = 0;
  const directory = tempDirectory();
  try {
    const result = await waitAndReadRun(TEST_TOKEN, 'RUN123', {
      requestImpl,
      maxWaitMs: 100,
      pollIntervalMs: 1,
      outputDir: directory,
      output: new PassThrough(),
    });
    assert.equal(result.run.id, 'RUN123');
    assert.equal(result.run.defaultDatasetId, 'DS123');
    assert.equal(result.items[0].text, 'offline transcript');
    assertSuccessfulDataset(result.run, result.items);
    assert.equal(requests.filter((request) => request.path === '/v2/actor-runs/RUN123').length, 1);
    assert.equal(requests.filter((request) => request.path === '/v2/datasets/DS123/items?format=json').length, 1);
    assert.ok(requests.every((request) => request.method === 'GET'));
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('malformed Run GET envelopes fail immediately instead of polling as RUNNING', async (t) => {
  for (const body of ['{}', '{"data":null}', '{"data":[]}', '{"data":{"id":"RUN123"}}', '{"data":{"id":"OTHER","status":"SUCCEEDED"}}']) {
    await t.test(body, async () => {
      const fake = fakeTransport({ body, statusCode: 200 });
      await assert.rejects(getRun(TEST_TOKEN, 'RUN123', { requestImpl: fake.requestImpl }), ApiRequestError);
      assert.equal(fake.calls.length, 1);
      const runPollTransport = fakeTransport({ body, statusCode: 200 });
      await assert.rejects(waitForRun(TEST_TOKEN, 'RUN123', { requestImpl: runPollTransport.requestImpl, maxWaitMs: 60_000 }), ApiRequestError);
      assert.equal(runPollTransport.calls.length, 1);
    });
  }
});

test('single URL CLI defaults and explicit positional/option URLs are predictable', () => {
  assert.equal(resolveVideoUrlArgs([]), DEFAULT_VIDEO_URL);
  assert.equal(resolveVideoUrlArgs([TEST_URL]), TEST_URL);
  assert.equal(resolveVideoUrlArgs(['--video-url', TEST_URL]), TEST_URL);
  assert.throws(() => resolveVideoUrlArgs([TEST_URL, '--video-url', TEST_URL]), /not both/);
  assert.deepEqual(resolveSingleArgs([]), { videoUrl: DEFAULT_VIDEO_URL, maxWaitSeconds: 900 });
  assert.deepEqual(resolveSingleArgs(['--video-url', TEST_URL, '--max-wait', '1']), { videoUrl: TEST_URL, maxWaitSeconds: 1 });
  assert.deepEqual(resolveSingleArgs(['--max-wait', '86400']), { videoUrl: DEFAULT_VIDEO_URL, maxWaitSeconds: 86400 });
});

test('single run prints its run ID before waiting and performs only one creation', async () => {
  const output = new PassThrough();
  let visibleOutput = '';
  output.on('data', (chunk) => { visibleOutput += chunk.toString(); });
  const sequence = [];
  let createCount = 0;
  const directory = tempDirectory();
  try {
    const result = await runSingleVideo({
      token: TEST_TOKEN,
      videoUrl: TEST_URL,
      outputFile: path.join(directory, 'single.json'),
      output,
      createRun: async () => { createCount += 1; sequence.push('created'); return { id: 'run-known' }; },
      waitRun: async (_token, runId, { maxWaitMs }) => {
        assert.equal(runId, 'run-known');
        assert.equal(maxWaitMs, 900_000);
        assert.match(visibleOutput, /Run ID: run-known/);
        sequence.push('waited');
        return { id: runId, status: 'SUCCEEDED', defaultDatasetId: 'dataset-1' };
      },
      readDataset: async () => [{ text: 'offline text', segments: [], errMsg: '' }],
    });
    assert.deepEqual(sequence, ['created', 'waited']);
    assert.equal(createCount, 1);
    assert.equal(JSON.parse(readFileSync(result.outputFile, 'utf8'))[0].text, 'offline text');
    assert.deepEqual(readdirSync(directory), ['single.json']);
  } finally {
    output.destroy();
    rmSync(directory, { recursive: true, force: true });
  }
});

test('single CLI passes default and boundary max-wait values into its real wait path', async () => {
  for (const [args, expectedMs] of [[[], 900_000], [['--max-wait', '1'], 1_000], [['--max-wait', '86400'], 86_400_000]]) {
    const directory = tempDirectory();
    const output = new PassThrough();
    let createCalls = 0;
    let waitOptions;
    try {
      await singleMain(args, {
        loadEnv() {},
        requireToken: () => TEST_TOKEN,
        runDependencies: {
          outputFile: path.join(directory, 'single.json'),
          output,
          createRun: async () => { createCalls += 1; return { id: 'single-run' }; },
          waitRun: async (_token, runId, options) => {
            assert.equal(runId, 'single-run');
            waitOptions = options;
            return { id: runId, status: 'SUCCEEDED', defaultDatasetId: 'single-dataset' };
          },
          readDataset: async () => [{ text: 'offline transcript', segments: [], errMsg: '' }],
        },
      });
      assert.equal(createCalls, 1);
      assert.equal(waitOptions.maxWaitMs, expectedMs);
    } finally {
      output.destroy();
      rmSync(directory, { recursive: true, force: true });
    }
  }
});

test('single wait timeout prints a reusable async wait command for the same Run without creating another', async () => {
  const directory = tempDirectory();
  const output = new PassThrough();
  let text = '';
  output.on('data', (chunk) => { text += chunk.toString(); });
  let creates = 0;
  try {
    await assert.rejects(runSingleVideo({
      token: TEST_TOKEN,
      videoUrl: TEST_URL,
      maxWaitSeconds: 1200,
      outputFile: path.join(directory, 'single.json'),
      output,
      createRun: async () => { creates += 1; return { id: 'same-run-id' }; },
      waitRun: async () => { throw new WaitTimeoutError('same-run-id', 1_200_000); },
    }), /node examples\/nodejs\/async-run\.mjs wait --run-id same-run-id --max-wait 1200/);
    assert.match(text, /Run ID: same-run-id/);
    assert.equal(creates, 1);
  } finally {
    output.destroy();
    rmSync(directory, { recursive: true, force: true });
  }
});

test('invalid single CLI max-wait values fail before env/token reads, output preflight, or HTTP', async () => {
  const directory = tempDirectory();
  const blocker = path.join(directory, 'not-a-directory');
  writeFileSync(blocker, 'preserve me');
  const fake = fakeTransport();
  const invalid = ['0', '-1', '86401', '1e308', 'Infinity', 'NaN', 'not-a-number'];
  let envReads = 0;
  let tokenReads = 0;
  try {
    for (const value of invalid) {
      await assert.rejects(singleMain(['--max-wait', value], {
        loadEnv() { envReads += 1; },
        requireToken() { tokenReads += 1; return TEST_TOKEN; },
        runDependencies: {
          outputFile: path.join(blocker, 'single.json'),
          createRun: (token, url) => startActorRunOnce(token, url, { requestImpl: fake.requestImpl }),
        },
      }), /--max-wait.*1 to 86400 seconds/);

      await assert.rejects(runSingleVideo({
        token: TEST_TOKEN,
        videoUrl: TEST_URL,
        maxWaitSeconds: Number(value),
        outputFile: path.join(blocker, 'direct.json'),
        createRun: (token, url) => startActorRunOnce(token, url, { requestImpl: fake.requestImpl }),
        waitRun: async () => { throw new Error('must not wait'); },
      }), /--max-wait.*1 to 86400 seconds/);
    }
    assert.equal(envReads, 0);
    assert.equal(tokenReads, 0);
    assert.equal(fake.calls.length, 0);
    assert.equal(readFileSync(blocker, 'utf8'), 'preserve me');
    assert.deepEqual(readdirSync(directory), ['not-a-directory']);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('single output directory preflight failure occurs before the real create helper can send POST', async () => {
  const directory = tempDirectory();
  const blocker = path.join(directory, 'not-a-directory');
  writeFileSync(blocker, 'preserve me');
  const fake = fakeTransport();
  const output = new PassThrough();
  try {
    await assert.rejects(runSingleVideo({
      token: TEST_TOKEN,
      videoUrl: TEST_URL,
      outputFile: path.join(blocker, 'single.json'),
      output,
      createRun: (token, videoUrl) => startActorRunOnce(token, videoUrl, { requestImpl: fake.requestImpl }),
      waitRun: async () => { throw new Error('must not wait'); },
      readDataset: async () => [],
    }), /Output directory preflight failed/);
    assert.equal(fake.calls.length, 0);
    assert.equal(readFileSync(blocker, 'utf8'), 'preserve me');
    assert.deepEqual(readdirSync(directory), ['not-a-directory']);
  } finally {
    output.destroy();
    rmSync(directory, { recursive: true, force: true });
  }
});

test('Node.js async and CSV wait bounds default to 900 and reject values outside 1-86400 before requests', async () => {
  assert.equal(DEFAULT_MAX_WAIT_SECONDS, 900);
  assert.equal(MAX_MAX_WAIT_SECONDS, 86_400);
  assert.equal(parseMaxWaitSeconds('1'), 1);
  assert.equal(parseMaxWaitSeconds('86400'), 86400);
  assert.deepEqual(parseAsyncArgs(['wait', '--run-id', 'R1']), { command: 'wait', runId: 'R1', maxWaitMs: 900_000 });
  assert.equal(parseAsyncArgs(['wait', '--run-id', 'R1', '--max-wait', '1']).maxWaitMs, 1_000);
  assert.equal(parseAsyncArgs(['wait', '--run-id', 'R1', '--max-wait', '86400']).maxWaitMs, 86_400_000);
  assert.equal(parseCsvArgs(['input.csv']).maxWaitMs, 900_000);
  assert.equal(parseCsvArgs(['input.csv', '--max-wait', '1']).maxWaitMs, 1_000);
  assert.equal(parseCsvArgs(['input.csv', '--max-wait', '86400']).maxWaitMs, 86_400_000);

  const invalid = ['0', '0.5', '86401', '86400.1', '1e308', '1e309', 'Infinity', 'NaN', 'not-a-number'];
  for (const value of invalid) {
    assert.throws(() => parseMaxWaitSeconds(value), /max-wait/);
    assert.throws(() => parseAsyncArgs(['wait', '--run-id', 'R1', '--max-wait', value]), /max-wait/);
    assert.throws(() => parseCsvArgs(['input.csv', '--max-wait', value]), /max-wait/);
  }

  let requests = 0;
  const requestImpl = (...args) => { requests += 1; return fakeTransport().requestImpl(...args); };
  await assert.rejects(asyncMain(['wait', '--run-id', 'R1', '--max-wait', '1e308'], {
    env: { APIFY_TOKEN: TEST_TOKEN },
    loadEnv() {},
    waitDependencies: { requestImpl },
  }), /max-wait/);
  await assert.rejects(waitAndReadRun(TEST_TOKEN, 'R1', {
    maxWaitMs: Infinity,
    getRunFn: async () => { requests += 1; throw new Error('must not query'); },
  }), /Wait limit/);
  const directory = tempDirectory();
  try {
    await assert.rejects(processCsv({
      csvText: `videoUrl\n${TEST_URL}\n`,
      token: TEST_TOKEN,
      outputFile: path.join(directory, 'batch.jsonl'),
      maxWaitMs: Infinity,
      requestImpl,
    }), /Wait limit/);
    assert.equal(requests, 0);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('transcript checks distinguish Run, Dataset, empty text, errMsg, and non-success status', async () => {
  const directory = tempDirectory();
  const base = {
    token: TEST_TOKEN,
    videoUrl: TEST_URL,
    outputFile: path.join(directory, 'result.json'),
    output: new PassThrough(),
    createRun: async () => ({ id: 'run-x' }),
    waitRun: async () => ({ id: 'run-x', status: 'SUCCEEDED', defaultDatasetId: 'dataset-x' }),
  };
  try {
    await assert.rejects(runSingleVideo({ ...base, waitRun: async () => ({ id: 'run-x', status: 'FAILED' }) }), /failure status FAILED/);
    await assert.rejects(runSingleVideo({ ...base, waitRun: async () => ({ id: 'run-x', status: 'SUCCEEDED' }) }), /no default Dataset ID/);
    await assert.rejects(runSingleVideo({ ...base, readDataset: async () => [] }), /Dataset is empty/);
    await assert.rejects(runSingleVideo({ ...base, readDataset: async () => [{ segments: [] }] }), /text is empty or missing/);
    await assert.rejects(runSingleVideo({ ...base, readDataset: async () => [{ text: 'text', errMsg: 'failed' }] }), /errMsg is non-empty/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('ordinary create errors and async RunCreationUnknownError show safe guidance without token leakage', async () => {
  const output = new PassThrough();
  let written = '';
  output.on('data', (chunk) => { written += chunk.toString(); });
  await assert.rejects(startRun(TEST_TOKEN, TEST_URL, {
    output,
    createRun: async () => { throw new Error(`network failed ${TEST_TOKEN}`); },
  }), (error) => /unknown/.test(error.message) && /Apify Console/.test(error.message) && /Do not retry/.test(error.message) && !error.message.includes(TEST_TOKEN) && !error.message.includes('UnboundLocalError'));
  assert.match(written, /^Actor: apple_yang\/tiktok-transcripts-scraper/);
  assert.equal(written.includes(TEST_TOKEN), false);
  await assert.rejects(startRun(TEST_TOKEN, TEST_URL, {
    output,
    createRun: async () => { throw new RunCreationUnknownError(`unknown ${TEST_TOKEN}`); },
  }), (error) => /Apify Console/.test(error.message) && /Do not retry/.test(error.message) && !error.message.includes(TEST_TOKEN));
  await assert.rejects(runSingleVideo({
    token: TEST_TOKEN,
    videoUrl: TEST_URL,
    output: new PassThrough(),
    createRun: async () => { throw new Error(`network failed ${TEST_TOKEN}`); },
  }), (error) => /unknown/.test(error.message) && /Apify Console/.test(error.message) && /Do not retry/.test(error.message) && !error.message.includes(TEST_TOKEN) && !error.message.includes('UnboundLocalError'));
  output.destroy();
});

test('async wait queries only the given Run ID, reads its Dataset, and does not create a Run', async () => {
  const runIds = [];
  const datasetIds = [];
  const outputDirectory = tempDirectory();
  try {
    const result = await waitAndReadRun(TEST_TOKEN, 'existing-run', {
      outputDir: outputDirectory,
      output: new PassThrough(),
      waitForRunFn: async (_token, runId) => {
        runIds.push(runId);
        return { id: runId, status: 'SUCCEEDED', defaultDatasetId: 'existing-dataset' };
      },
      readDataset: async (_token, datasetId) => {
        datasetIds.push(datasetId);
        return [{ text: 'retrieved', segments: [], errMsg: '' }];
      },
    });
    assert.deepEqual(runIds, ['existing-run']);
    assert.deepEqual(datasetIds, ['existing-dataset']);
    assert.equal(JSON.parse(readFileSync(result.outputFile, 'utf8'))[0].text, 'retrieved');
  } finally {
    rmSync(outputDirectory, { recursive: true, force: true });
  }
  assert.equal(parseAsyncArgs(['start']).videoUrl, DEFAULT_VIDEO_URL);
  assert.equal(parseAsyncArgs(['start', '--video-url', TEST_URL]).videoUrl, TEST_URL);
  assert.deepEqual(parseAsyncArgs(['wait', '--run-id', 'same-run']).runId, 'same-run');
  assert.throws(() => parseAsyncArgs(['wait', '--run-id', 'same-run', '--video-url', TEST_URL]), /never creates a Run/);
  await assert.rejects(waitAndReadRun(TEST_TOKEN, 'missing-run', {
    waitForRunFn: async () => { throw new ApiRequestError('not found', { statusCode: 404 }); },
  }), /Run not found: missing-run/);
});

test('wait timeout advises reuse of the same Run ID and a later wait can complete it', async () => {
  const fake = fakeTransport({ body: '{"data":{"id":"run-ignored"}}' });
  let readCount = 0;
  const getRunFn = async (_token, runId) => {
    assert.equal(runId, 'same-run');
    readCount += 1;
    return { id: runId, status: 'RUNNING' };
  };
  await assert.rejects(waitForRun(TEST_TOKEN, 'same-run', { maxWaitMs: 1, pollIntervalMs: 1, requestImpl: fake.requestImpl, getRunFn }), /same Run ID/);
  const directory = tempDirectory();
  try {
    const result = await waitAndReadRun(TEST_TOKEN, 'same-run', {
      outputDir: directory,
      output: new PassThrough(),
      waitForRunFn: async (_token, runId) => ({ id: runId, status: 'SUCCEEDED', defaultDatasetId: 'dataset-again' }),
      readDataset: async () => [{ text: 'done', errMsg: '' }],
    });
    assert.equal(result.run.id, 'same-run');
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
  assert.ok(readCount >= 1);
  assert.equal(fake.calls.length, 0);
});

test('CSV runs rows with bounded concurrency and flushes start_attempted before POST', async () => {
  const directory = tempDirectory();
  const outputFile = path.join(directory, 'results.jsonl');
  const urls = [1, 2, 3, 4].map((index) => `https://www.tiktok.com/@offline/video/${String(index).padStart(19, '0')}`);
  const csvText = `id,videoUrl\n${urls.map((url, index) => `row-${index},${url}`).join('\n')}\n`;
  let created = 0;
  let active = 0;
  let maxActive = 0;
  const requests = [];
  const requestImpl = (options, callback) => {
    const request = new EventEmitter();
    request.setTimeout = () => {};
    request.destroy = (error) => queueMicrotask(() => request.emit('error', error));
    request.end = (requestBody) => {
      requests.push({ options, body: requestBody });
      let responseBody = '';
      if (options.method === 'POST') {
        const existing = readFileSync(outputFile, 'utf8').trim().split('\n').map((line) => JSON.parse(line));
        assert.ok(existing.some((record) => record.status === 'start_attempted'));
        responseBody = JSON.stringify({ data: { id: `run-${++created}`, status: 'READY' } });
      }
      const response = new EventEmitter();
      response.statusCode = 201;
      callback(response);
      queueMicrotask(() => {
        if (responseBody) response.emit('data', Buffer.from(responseBody));
        response.emit('end');
      });
    };
    return request;
  };
  const waitRun = async (_token, runId) => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 2));
    active -= 1;
    return { id: runId, status: 'SUCCEEDED', defaultDatasetId: `dataset-${runId}` };
  };
  try {
    const records = await processCsv({
      csvText,
      token: TEST_TOKEN,
      outputFile,
      concurrency: 2,
      waitRun,
      readDataset: async () => [{ text: 'transcript', segments: [], errMsg: '' }],
      requestImpl,
      output: new PassThrough(),
    });
    assert.equal(records.length, 4);
    assert.ok(records.every((record) => record.status === 'completed_with_transcript'));
    assert.ok(maxActive <= 2);
    assert.equal(requests.filter(({ options }) => options.method === 'POST').length, 4);
    assert.ok(requests.every(({ options }) => options.hostname === 'api.apify.com'));
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('CSV unknown creation is reconciled read-only and resume never posts again', async () => {
  const directory = tempDirectory();
  const outputFile = path.join(directory, 'results.jsonl');
  const csvText = `videoUrl\n${TEST_URL}\n`;
  let postCount = 0;
  const failingRequest = (options) => {
    if (options.method === 'POST') postCount += 1;
    const request = new EventEmitter();
    request.setTimeout = () => {};
    request.end = () => queueMicrotask(() => request.emit('error', new Error(`socket lost ${TEST_TOKEN}`)));
    request.destroy = (error) => queueMicrotask(() => request.emit('error', error));
    return request;
  };
  try {
    await assert.rejects(processCsv({ csvText, token: TEST_TOKEN, outputFile, requestImpl: failingRequest, output: new PassThrough() }), /Batch incomplete/);
    assert.equal(postCount, 1);
    const text = readFileSync(outputFile, 'utf8');
    assert.equal(text.includes(TEST_TOKEN), false);
    const latestRecord = JSON.parse(text.trim().split('\n').at(-1));
    assert.equal(latestRecord.status, 'run_creation_unknown');
    await assert.rejects(processCsv({ csvText, token: TEST_TOKEN, outputFile, requestImpl: failingRequest, output: new PassThrough() }), /Batch incomplete/);
    assert.equal(postCount, 1);
    const output = new PassThrough();
    let reconcileText = '';
    output.on('data', (chunk) => { reconcileText += chunk.toString(); });
    const unresolved = reconcile(outputFile, output);
    assert.equal(unresolved.length, 1);
    assert.match(reconcileText, /needs_reconciliation/);
    assert.equal(postCount, 1);
    output.destroy();
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('CSV URL change with an existing Run is quarantined and reconciliation shows both URLs and Run ID', async () => {
  const directory = tempDirectory();
  const outputFile = path.join(directory, 'by-id.jsonl');
  const oldUrl = 'https://www.tiktok.com/@offline/video/1111111111111111111';
  const newUrl = 'https://www.tiktok.com/@offline/video/2222222222222222222';
  const originalInput = `id,videoUrl\nclip-1,${oldUrl}\n`;
  const changedInput = `id,videoUrl\nclip-1,${newUrl}\n`;
  const creationTransport = fakeTransport({ body: '{"data":{"id":"RUN-OLD","status":"READY"}}' });
  try {
    await assert.rejects(processCsv({
      csvText: originalInput,
      token: TEST_TOKEN,
      outputFile,
      requestImpl: creationTransport.requestImpl,
      waitRun: async (_token, runId) => { assert.equal(runId, 'RUN-OLD'); throw new WaitTimeoutError(runId, 100); },
      output: new PassThrough(),
    }), /Batch incomplete/);
    assert.equal(creationTransport.calls.length, 1);

    let waitCalls = 0;
    const noRequests = () => { throw new Error('URL change must not create another Run or read the old Run'); };
    await assert.rejects(processCsv({
      csvText: changedInput,
      token: TEST_TOKEN,
      outputFile,
      requestImpl: noRequests,
      waitRun: async () => { waitCalls += 1; throw new Error('old Run must not be read'); },
      readDataset: async () => { throw new Error('old Run Dataset must not be read'); },
      output: new PassThrough(),
    }), /Batch incomplete/);
    assert.equal(waitCalls, 0);

    const latest = JSON.parse(readFileSync(outputFile, 'utf8').trim().split('\n').at(-1));
    assert.equal(latest.status, 'needs_reconciliation');
    assert.equal(latest.original_videoUrl, oldUrl);
    assert.equal(latest.requested_videoUrl, newUrl);
    assert.equal(latest.videoUrl, newUrl);
    assert.equal(latest.run_id, 'RUN-OLD');

    const reconcileOutput = new PassThrough();
    let reconcileText = '';
    reconcileOutput.on('data', (chunk) => { reconcileText += chunk.toString(); });
    const records = reconcile(outputFile, reconcileOutput);
    assert.equal(records.length, 1);
    assert.match(reconcileText, new RegExp(oldUrl));
    assert.match(reconcileText, new RegExp(newUrl));
    assert.match(reconcileText, /RUN-OLD/);
    reconcileOutput.destroy();

    await assert.rejects(processCsv({
      csvText: changedInput,
      token: TEST_TOKEN,
      outputFile,
      requestImpl: noRequests,
      waitRun: async () => { waitCalls += 1; throw new Error('needs_reconciliation must remain blocked'); },
      output: new PassThrough(),
    }), /Batch incomplete/);
    assert.equal(waitCalls, 0);
    const finalLatest = JSON.parse(readFileSync(outputFile, 'utf8').trim().split('\n').at(-1));
    assert.equal(finalLatest.status, 'needs_reconciliation');
    assert.equal(finalLatest.run_id, 'RUN-OLD');
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('CSV changed URL after a Python-terminal status starts a fresh Run and binds the new Dataset only', async () => {
  const directory = tempDirectory();
  const outputFile = path.join(directory, 'terminal-edit.jsonl');
  const oldUrl = 'https://www.tiktok.com/@offline/video/3333333333333333333';
  const newUrl = 'https://www.tiktok.com/@offline/video/4444444444444444444';
  const recordKey = `id:${stableKey('clip-terminal')}`;
  const prior = {
    record_key: recordKey,
    row_number: 2,
    id: 'clip-terminal',
    videoUrl: oldUrl,
    run_id: 'RUN-OLD-FINISHED',
    run_status: 'SUCCEEDED',
    dataset_id: 'DS-OLD',
    status: 'completed_with_transcript',
    items: [{ text: 'old transcript', errMsg: '' }],
    error: null,
  };
  writeFileSync(outputFile, `${JSON.stringify(prior)}\n`);
  const transport = fakeTransport({ body: '{"data":{"id":"RUN-NEW","status":"READY"}}' });
  const waitedRuns = [];
  const datasetReads = [];
  const csvText = `id,videoUrl\nclip-terminal,${newUrl}\n`;
  try {
    const records = await processCsv({
      csvText,
      token: TEST_TOKEN,
      outputFile,
      requestImpl: transport.requestImpl,
      waitRun: async (_token, runId) => {
        waitedRuns.push(runId);
        return { id: runId, status: 'SUCCEEDED', defaultDatasetId: 'DS-NEW' };
      },
      readDataset: async (_token, datasetId) => {
        datasetReads.push(datasetId);
        return [{ text: 'new transcript', errMsg: '' }];
      },
      output: new PassThrough(),
    });
    assert.equal(transport.calls.length, 1);
    assert.equal(transport.calls[0].options.method, 'POST');
    assert.deepEqual(JSON.parse(transport.calls[0].body), { videoUrl: newUrl });
    assert.deepEqual(waitedRuns, ['RUN-NEW']);
    assert.deepEqual(datasetReads, ['DS-NEW']);
    assert.equal(records[0].status, 'completed_with_transcript');
    assert.equal(records[0].videoUrl, newUrl);
    assert.equal(records[0].run_id, 'RUN-NEW');
    assert.equal(records[0].dataset_id, 'DS-NEW');
    assert.equal(records[0].items[0].text, 'new transcript');
    assert.equal(records[0].items.some((item) => item.text === 'old transcript'), false);

    const resumed = await processCsv({
      csvText,
      token: TEST_TOKEN,
      outputFile,
      requestImpl: () => { throw new Error('completed current record must not POST'); },
      waitRun: async () => { throw new Error('completed current record must not re-wait'); },
      readDataset: async () => { throw new Error('completed current record must not re-read Dataset'); },
      output: new PassThrough(),
    });
    assert.equal(resumed[0].videoUrl, newUrl);
    assert.equal(resumed[0].run_id, 'RUN-NEW');
    assert.equal(transport.calls.length, 1);
    assert.deepEqual(waitedRuns, ['RUN-NEW']);
    assert.deepEqual(datasetReads, ['DS-NEW']);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('CSV resumes the same URL by waiting on its prior Run ID without creating another Run', async () => {
  const directory = tempDirectory();
  const outputFile = path.join(directory, 'resume.jsonl');
  const csvText = `id,videoUrl\nclip-2,${TEST_URL}\n`;
  const creationTransport = fakeTransport({ body: '{"data":{"id":"RUN-SAME","status":"READY"}}' });
  let datasetReads = 0;
  try {
    await assert.rejects(processCsv({
      csvText,
      token: TEST_TOKEN,
      outputFile,
      requestImpl: creationTransport.requestImpl,
      waitRun: async (_token, runId) => { assert.equal(runId, 'RUN-SAME'); throw new WaitTimeoutError(runId, 100); },
      output: new PassThrough(),
    }), /Batch incomplete/);
    assert.equal(creationTransport.calls.length, 1);

    const records = await processCsv({
      csvText,
      token: TEST_TOKEN,
      outputFile,
      requestImpl: () => { throw new Error('known Run resume must not POST'); },
      waitRun: async (_token, runId) => ({ id: runId, status: 'SUCCEEDED', defaultDatasetId: 'DS-SAME' }),
      readDataset: async (_token, datasetId) => {
        datasetReads += 1;
        assert.equal(datasetId, 'DS-SAME');
        return [{ text: 'resumed transcript', errMsg: '' }];
      },
      output: new PassThrough(),
    });
    assert.equal(datasetReads, 1);
    assert.equal(records[0].run_id, 'RUN-SAME');
    assert.equal(records[0].status, 'completed_with_transcript');
    assert.equal(creationTransport.calls.length, 1);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('CSV Run, Dataset, transcript, errMsg, pending, and processing failures all exit nonzero', async (t) => {
  const cases = [
    ['actor_failed', async () => ({ id: 'run-1', status: 'FAILED' }), async () => []],
    ['run_pending', async () => { throw new WaitTimeoutError('run-1', 100); }, async () => []],
    ['dataset_error', async () => ({ id: 'run-1', status: 'SUCCEEDED', defaultDatasetId: 'dataset-1' }), async () => { throw new Error(`read failed ${TEST_TOKEN}`); }],
    ['dataset_empty', async () => ({ id: 'run-1', status: 'SUCCEEDED', defaultDatasetId: 'dataset-1' }), async () => []],
    ['transcript_empty', async () => ({ id: 'run-1', status: 'SUCCEEDED', defaultDatasetId: 'dataset-1' }), async () => [{ segments: [] }]],
    ['transcript_failed', async () => ({ id: 'run-1', status: 'SUCCEEDED', defaultDatasetId: 'dataset-1' }), async () => [{ text: 'text', errMsg: 'Actor error' }]],
    ['processing_error', async () => Object.defineProperty({}, 'status', { get() { throw new Error('unexpected status access'); } }), async () => []],
  ];
  for (const [expectedStatus, waitRun, readDataset] of cases) {
    await t.test(expectedStatus, async () => {
      const directory = tempDirectory();
      const outputFile = path.join(directory, 'rows.jsonl');
      const fake = fakeTransport();
      try {
        await assert.rejects(processCsv({
          csvText: `videoUrl\n${TEST_URL}\n`,
          token: TEST_TOKEN,
          outputFile,
          waitRun,
          readDataset,
          requestImpl: fake.requestImpl,
          output: new PassThrough(),
        }), /Batch incomplete/);
        const lines = readFileSync(outputFile, 'utf8').trim().split('\n');
        const latest = JSON.parse(lines.at(-1));
        assert.equal(latest.status, expectedStatus);
        assert.equal(readFileSync(outputFile, 'utf8').includes(TEST_TOKEN), false);
      } finally {
        rmSync(directory, { recursive: true, force: true });
      }
    });
  }
});

test('CSV stable URL occurrence keys, duplicate IDs, processing summaries, and invalid concurrency', async () => {
  const directory = tempDirectory();
  const outputFile = path.join(directory, 'results.jsonl');
  const repeated = `${TEST_URL}\n${TEST_URL}`;
  await assert.rejects(processCsv({ csvText: `videoUrl\n${repeated}\n`, token: TEST_TOKEN, outputFile, concurrency: 17 }), /concurrency/);
  await assert.rejects(processCsv({ csvText: `videoUrl\n${repeated}\n`, token: TEST_TOKEN, outputFile, concurrency: 0 }), /concurrency/);
  for (const concurrency of [0, 17]) assert.throws(() => parseCsvArgs(['input.csv', '--concurrency', String(concurrency)]), /concurrency/);

  const fake = fakeTransport({ body: '{"data":{"id":"run-x","status":"READY"}}' });
  const records = await processCsv({
    csvText: `videoUrl\n${TEST_URL}\n${TEST_URL}\n`, token: TEST_TOKEN, outputFile,
    requestImpl: fake.requestImpl,
    waitRun: async (_token, runId) => ({ id: runId, status: 'SUCCEEDED', defaultDatasetId: 'dataset-1' }),
    readDataset: async () => [{ text: 'text', errMsg: '' }], output: new PassThrough(),
  });
  assert.ok(records.some((record) => record.record_key.endsWith(':1')));
  assert.ok(records.some((record) => record.record_key.endsWith(':2')));
  const duplicateIdOutput = path.join(directory, 'duplicate-id.jsonl');
  await assert.rejects(processCsv({
    csvText: `id,videoUrl\nsame,${TEST_URL}\nsame,${TEST_URL}\n`, token: TEST_TOKEN, outputFile: duplicateIdOutput,
    requestImpl: () => { throw new Error('duplicate IDs must not create a request'); }, output: new PassThrough(),
  }), /Batch incomplete/);
  const duplicateRecords = readFileSync(duplicateIdOutput, 'utf8').trim().split('\n').map((line) => JSON.parse(line));
  assert.ok(duplicateRecords.every((record) => record.status === 'duplicate_id'));
  await assert.rejects(processCsv({ csvText: 'videoUrl\n', token: TEST_TOKEN, outputFile, output: new PassThrough() }), /no video rows/);
  assert.throws(() => parseCsvArgs(['--reconcile', 'input.csv']), /does not accept/);
  const summary = new PassThrough();
  let summaryText = '';
  summary.on('data', (chunk) => { summaryText += chunk.toString(); });
  printSummary([{ status: 'processing_error' }], summary);
  assert.match(summaryText, /processing_error: 1/);
  summary.destroy();
  rmSync(directory, { recursive: true, force: true });
});
