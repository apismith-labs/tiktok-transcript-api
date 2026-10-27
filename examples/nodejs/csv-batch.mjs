import { parseArgs } from 'node:util';
import { appendFileSync, closeSync, fsyncSync, mkdirSync, openSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  ApiRequestError,
  assertSuccessfulDataset,
  DEFAULT_MAX_WAIT_SECONDS,
  parseMaxWaitSeconds,
  getDatasetItems,
  getRun,
  loadLocalEnv,
  requireApifyToken,
  RUN_CREATION_LIMITATION,
  safeError,
  startActorRunOnce,
  TIKTOK_ACTOR_SLUG,
  validateTikTokVideoUrl,
  validateMaxWaitMs,
  waitForRun,
  writeLine,
} from './apify-run.mjs';

export { DEFAULT_MAX_WAIT_SECONDS };

export const DEFAULT_CONCURRENCY = 2;
export const CONCURRENCY_LIMIT = 16;
// Keep this in sync with examples/python/csv_batch.py FINAL_RECORD_STATUSES.
const FINAL_RECORD_STATUSES = new Set([
  'completed_with_transcript',
  'transcript_empty',
  'transcript_failed',
  'actor_failed',
  'dataset_empty',
  'dataset_id_missing',
  'input_error',
  'duplicate_id',
]);
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '../..');
export const OUTPUT_FILE = path.join(REPO_ROOT, 'sample-output', 'generated', 'nodejs-csv-batch-results.jsonl');

export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"' && field.length === 0) {
      quoted = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[index + 1] === '\n') index += 1;
      row.push(field);
      field = '';
      if (row.some((value) => value.length > 0)) rows.push(row);
      row = [];
    } else {
      field += char;
    }
  }
  if (quoted) throw new Error('Input CSV contains an unterminated quoted field.');
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    if (row.some((value) => value.length > 0)) rows.push(row);
  }
  return rows;
}

export function csvRecords(csvText) {
  const rows = parseCsv(csvText.replace(/^\uFEFF/, ''));
  if (rows.length === 0 || !rows[0].includes('videoUrl')) throw new Error("Input CSV must contain a 'videoUrl' column.");
  const headers = rows[0];
  if (new Set(headers).size !== headers.length) throw new Error('Input CSV contains duplicate column names.');
  return rows.slice(1).map((values, index) => ({
    ...Object.fromEntries(headers.map((header, column) => [header, values[column] ?? ''])),
    row_number: index + 2,
  }));
}

export function stableKey(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

export function readLatestRecords(outputFile) {
  const latest = new Map();
  let content;
  try {
    content = readFileSync(outputFile, 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return latest;
    throw error;
  }
  for (const [index, line] of content.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    let record;
    try {
      record = JSON.parse(line);
    } catch (error) {
      throw new Error(`Invalid JSONL record at line ${index + 1}: ${error.message}`);
    }
    if (!record || typeof record !== 'object' || Array.isArray(record) || typeof record.record_key !== 'string') {
      throw new Error(`JSONL record at line ${index + 1} is missing a record_key.`);
    }
    latest.set(record.record_key, record);
  }
  return latest;
}

export function appendRecord(fd, record, token) {
  const serialized = JSON.stringify(record);
  const safeText = typeof token === 'string' && token.length > 0 ? serialized.split(token).join('[REDACTED]') : serialized;
  appendFileSync(fd, `${safeText}\n`, 'utf8');
  fsyncSync(fd);
}

export function summarize(records) {
  const counts = new Map();
  for (const record of records) counts.set(record.status ?? 'unknown', (counts.get(record.status ?? 'unknown') ?? 0) + 1);
  return counts;
}

export function printSummary(records, output = process.stdout) {
  const counts = summarize(records);
  output.write('Batch summary:\n');
  for (const [status, count] of [...counts].sort(([left], [right]) => left.localeCompare(right))) {
    output.write(`  ${status}: ${count}\n`);
  }
  output.write(`  Total rows: ${records.length}\n`);
  return counts;
}

function parseConcurrency(value) {
  const concurrency = Number(value);
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > CONCURRENCY_LIMIT) {
    throw new Error(`--concurrency must be an integer from 1 to ${CONCURRENCY_LIMIT}.`);
  }
  return concurrency;
}

function parseMaxWait(value) {
  return parseMaxWaitSeconds(value) * 1000;
}

export function parseCommandArgs(argv) {
  const { positionals, values } = parseArgs({
    args: argv,
    options: {
      concurrency: { type: 'string' },
      'max-wait': { type: 'string' },
      reconcile: { type: 'boolean' },
    },
    allowPositionals: true,
    strict: true,
  });
  if (positionals.length > 1) throw new Error('Provide one CSV input path.');
  if (values.reconcile) {
    if (positionals.length || values.concurrency !== undefined || values['max-wait'] !== undefined) {
      throw new Error('--reconcile does not accept a CSV path, concurrency, or wait options.');
    }
    return { reconcile: true };
  }
  if (!positionals[0]) throw new Error('Provide a CSV path, or use --reconcile to inspect unresolved records.');
  return {
    reconcile: false,
    csvPath: path.resolve(positionals[0]),
    concurrency: parseConcurrency(values.concurrency ?? String(DEFAULT_CONCURRENCY)),
    maxWaitMs: parseMaxWait(values['max-wait'] ?? String(DEFAULT_MAX_WAIT_SECONDS)),
  };
}

function latestForRows(rows, latest) {
  const idColumn = rows.length > 0 && Object.hasOwn(rows[0], 'id');
  const idCounts = new Map();
  if (idColumn) {
    for (const row of rows) {
      const id = row.id.trim();
      if (id) idCounts.set(id, (idCounts.get(id) ?? 0) + 1);
    }
  }
  const occurrences = new Map();
  const prepared = rows.map((row) => {
    const videoUrl = row.videoUrl ?? '';
    let recordKey;
    let inputError = null;
    if (idColumn) {
      const id = row.id.trim();
      if (!id) {
        const count = (occurrences.get(videoUrl) ?? 0) + 1;
        occurrences.set(videoUrl, count);
        recordKey = `invalid-id:${stableKey(videoUrl)}:${count}`;
        inputError = 'The optional id column contains an empty id; no Run was started.';
      } else if (idCounts.get(id) > 1) {
        const count = (occurrences.get(`id:${id}`) ?? 0) + 1;
        occurrences.set(`id:${id}`, count);
        recordKey = `invalid-id:${stableKey(id)}:${count}`;
        inputError = `Duplicate id value at CSV row ${row.row_number}; no Run was started.`;
      } else {
        recordKey = `id:${stableKey(id)}`;
      }
    } else {
      const count = (occurrences.get(videoUrl) ?? 0) + 1;
      occurrences.set(videoUrl, count);
      recordKey = `url:${stableKey(videoUrl)}:${count}`;
    }
    inputError ??= validateTikTokVideoUrl(videoUrl);
    return { ...row, videoUrl, record_key: recordKey, inputError, id: row.id?.trim() || null, prior: latest.get(recordKey) };
  });
  return prepared;
}

async function resolveRun({ token, runId, maxWaitMs, requestImpl, waitRun, readDataset }) {
  let run;
  try {
    run = await waitRun(token, runId, { maxWaitMs, requestImpl });
  } catch (error) {
    if (error?.name === 'WaitTimeoutError') return { status: 'run_pending', run_status: error.run?.status ?? 'RUNNING', error: safeError(error, token) };
    if (error instanceof ApiRequestError && error.statusCode === 404) return { status: 'run_lookup_error', error: `Run ${runId} was not found.` };
    return { status: 'poll_error', error: safeError(error, token) };
  }
  const runStatus = run?.status;
  if (!run || runStatus !== 'SUCCEEDED') return { status: 'actor_failed', run_status: runStatus, error: `Actor Run finished with status ${runStatus ?? 'unknown'}.` };
  if (typeof run.defaultDatasetId !== 'string' || !run.defaultDatasetId) {
    return { status: 'dataset_id_missing', run_status: runStatus, error: 'Completed Run has no default Dataset ID.' };
  }
  let items;
  try {
    items = await readDataset(token, run.defaultDatasetId, { requestImpl });
  } catch (error) {
    return { status: 'dataset_error', run_status: runStatus, dataset_id: run.defaultDatasetId, error: safeError(error, token) };
  }
  if (!Array.isArray(items) || items.length === 0) {
    return { status: 'dataset_empty', run_status: runStatus, dataset_id: run.defaultDatasetId, items: [], error: 'Run completed with an empty Dataset.' };
  }
  try {
    assertSuccessfulDataset(run, items);
    return { status: 'completed_with_transcript', run_status: runStatus, dataset_id: run.defaultDatasetId, items, error: null };
  } catch (error) {
    const transcript = items.find((item) => item?.errMsg !== undefined && item?.errMsg !== null && item.errMsg !== '');
    return {
      status: transcript ? 'transcript_failed' : 'transcript_empty',
      run_status: runStatus,
      dataset_id: run.defaultDatasetId,
      items,
      error: safeError(error, token),
    };
  }
}

async function processRow(row, context) {
  const { token, latest, fd, maxWaitMs, requestImpl, waitRun, readDataset } = context;
  const rowFields = { record_key: row.record_key, row_number: row.row_number, id: row.id, videoUrl: row.videoUrl };
  let prior = row.prior;
  if (prior?.status === 'needs_reconciliation') {
    const unresolved = {
      ...rowFields,
      original_videoUrl: prior.original_videoUrl ?? prior.videoUrl ?? null,
      requested_videoUrl: row.videoUrl,
      status: 'needs_reconciliation',
      run_id: prior.run_id ?? null,
      error: prior.error ?? 'This row requires manual reconciliation before it can be resumed.',
    };
    if (prior.requested_videoUrl !== row.videoUrl || prior.videoUrl !== row.videoUrl) appendRecord(fd, unresolved, token);
    latest.set(row.record_key, unresolved);
    return;
  }
  if (prior && prior.videoUrl !== row.videoUrl) {
    if (FINAL_RECORD_STATUSES.has(prior.status)) {
      // A terminal row may be deliberately edited to request a new video; do not carry its Run or Dataset forward.
      prior = null;
    } else {
      const unresolved = {
        ...rowFields,
        original_videoUrl: prior.original_videoUrl ?? prior.videoUrl ?? null,
        requested_videoUrl: row.videoUrl,
        status: 'needs_reconciliation',
        run_id: prior.run_id ?? null,
        error: 'CSV videoUrl changed since this record was created; do not use the previous Run for the new URL. Reconcile the old Run before starting another.',
      };
      appendRecord(fd, unresolved, token);
      latest.set(row.record_key, unresolved);
      return;
    }
  }
  if (row.inputError) {
    const invalid = { ...rowFields, status: row.inputError.startsWith('Duplicate id') ? 'duplicate_id' : 'input_error', error: row.inputError, run_id: null };
    appendRecord(fd, invalid, token);
    latest.set(row.record_key, invalid);
    return;
  }
  if (prior && FINAL_RECORD_STATUSES.has(prior.status)) return;
  if (prior && !prior.run_id) {
    const unresolved = {
      ...rowFields,
      original_videoUrl: prior.videoUrl ?? null,
      requested_videoUrl: row.videoUrl,
      status: 'needs_reconciliation',
      run_id: null,
      error: 'Found a prior record without a Run ID; check Apify Console before any new POST.',
    };
    if (prior.status !== 'needs_reconciliation') appendRecord(fd, unresolved, token);
    latest.set(row.record_key, unresolved);
    return;
  }

  let runId = prior?.run_id ?? null;
  if (!runId) {
    const attempted = { ...rowFields, status: 'start_attempted', run_id: null, error: null };
    appendRecord(fd, attempted, token);
    latest.set(row.record_key, attempted);
    try {
      const started = await startActorRunOnce(token, row.videoUrl, { requestImpl });
      runId = started.id;
      const created = { ...attempted, status: 'run_started', run_id: runId, run_status: started.status ?? null };
      appendRecord(fd, created, token);
      latest.set(row.record_key, created);
    } catch (error) {
      const unknown = {
        ...attempted,
        status: 'run_creation_unknown',
        error: `Run creation result is unknown; the Run may already have been created. Check Apify Console before retrying or starting another Run. Details: ${safeError(error, token)}`,
      };
      appendRecord(fd, unknown, token);
      latest.set(row.record_key, unknown);
      return;
    }
  }

  try {
    const result = await resolveRun({ token, runId, maxWaitMs, requestImpl, waitRun, readDataset });
    const record = { ...rowFields, ...result, run_id: runId };
    appendRecord(fd, record, token);
    latest.set(row.record_key, record);
  } catch (error) {
    const record = { ...rowFields, run_id: runId, status: 'processing_error', error: safeError(error, token) };
    appendRecord(fd, record, token);
    latest.set(row.record_key, record);
  }
}

export async function processCsv({
  csvText,
  token,
  outputFile = OUTPUT_FILE,
  concurrency = DEFAULT_CONCURRENCY,
  maxWaitMs = DEFAULT_MAX_WAIT_SECONDS * 1000,
  requestImpl,
  waitRun = waitForRun,
  readDataset = getDatasetItems,
  output = process.stdout,
}) {
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > CONCURRENCY_LIMIT) {
    throw new Error(`concurrency must be an integer from 1 to ${CONCURRENCY_LIMIT}.`);
  }
  validateMaxWaitMs(maxWaitMs);
  const rows = csvRecords(csvText);
  if (rows.length === 0) throw new Error('Input CSV is empty: it contains a header but no video rows were processed.');
  const latest = readLatestRecords(outputFile);
  const prepared = latestForRows(rows, latest);
  mkdirSync(path.dirname(outputFile), { recursive: true });
  const fd = openSync(outputFile, 'a');
  const context = { token, latest, fd, maxWaitMs, requestImpl, waitRun, readDataset };
  await writeLine(`Actor: ${TIKTOK_ACTOR_SLUG}`, output);
  await writeLine(RUN_CREATION_LIMITATION, output);
  let nextIndex = 0;
  const worker = async () => {
    while (nextIndex < prepared.length) {
      const row = prepared[nextIndex];
      nextIndex += 1;
      try {
        await processRow(row, context);
      } catch (error) {
        const record = { record_key: row.record_key, row_number: row.row_number, id: row.id, videoUrl: row.videoUrl, status: 'processing_error', error: safeError(error, token) };
        appendRecord(fd, record, token);
        latest.set(row.record_key, record);
      }
    }
  };
  try {
    await Promise.all(Array.from({ length: Math.min(concurrency, prepared.length) }, worker));
  } finally {
    closeSync(fd);
  }
  const records = prepared.map((row) => latest.get(row.record_key)).filter(Boolean);
  printSummary(records, output);
  const failed = records.filter((record) => record.status !== 'completed_with_transcript');
  if (failed.length) throw new Error(`Batch incomplete: ${failed.length} row(s) failed or need follow-up; inspect JSONL and reconcile unknown Run creation before retrying.`);
  return records;
}

export function reconcile(outputFile = OUTPUT_FILE, output = process.stdout) {
  const latest = readLatestRecords(outputFile);
  const unresolved = [...latest.values()].filter((record) =>
    ['start_attempted', 'run_creation_unknown', 'needs_reconciliation'].includes(record.status),
  );
  output.write('Run-creation records requiring manual reconciliation:\n');
  if (!unresolved.length) output.write('No unresolved Run-creation records.\n');
  for (const record of unresolved) {
    output.write(`${JSON.stringify({
      record_key: record.record_key,
      id: record.id,
      original_videoUrl: record.original_videoUrl ?? record.videoUrl ?? null,
      current_videoUrl: record.requested_videoUrl ?? record.videoUrl ?? null,
      run_id: record.run_id ?? null,
      status: record.status,
      error: record.error,
    })}\n`);
  }
  return unresolved;
}

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const args = parseCommandArgs(argv);
  if (args.reconcile) return reconcile(dependencies.outputFile ?? OUTPUT_FILE, dependencies.output ?? process.stdout);
  const csvText = readFileSync(args.csvPath, 'utf8');
  (dependencies.loadEnv ?? loadLocalEnv)(REPO_ROOT);
  const token = (dependencies.requireToken ?? requireApifyToken)(dependencies.env ?? process.env);
  return processCsv({ csvText, token, outputFile: dependencies.outputFile ?? OUTPUT_FILE, concurrency: args.concurrency, maxWaitMs: args.maxWaitMs, ...dependencies.processDependencies });
}

function isMainModule() {
  return process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
}

if (isMainModule()) {
  main().catch((error) => {
    console.error(safeError(error, process.env.APIFY_TOKEN));
    process.exitCode = 1;
  });
}
