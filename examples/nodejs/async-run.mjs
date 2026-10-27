import { parseArgs } from 'node:util';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  ApiRequestError,
  assertSuccessfulDataset,
  DEFAULT_MAX_WAIT_SECONDS,
  DEFAULT_VIDEO_URL,
  getDatasetItems,
  getRun,
  loadLocalEnv,
  parseMaxWaitSeconds,
  requireApifyToken,
  RUN_CREATION_LIMITATION,
  RunCreationUnknownError,
  safeError,
  startActorRunOnce,
  TIKTOK_ACTOR_SLUG,
  validateMaxWaitMs,
  validateTikTokVideoUrl,
  waitForRun,
  writeLine,
} from './apify-run.mjs';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '../..');
export const OUTPUT_DIR = path.join(REPO_ROOT, 'sample-output', 'generated');

export function parseCommandArgs(argv) {
  const { positionals, values } = parseArgs({
    args: argv,
    options: {
      'video-url': { type: 'string' },
      'run-id': { type: 'string' },
      'max-wait': { type: 'string' },
    },
    allowPositionals: true,
    strict: true,
  });
  const [command, ...extra] = positionals;
  if (extra.length || !['start', 'wait'].includes(command)) throw new Error('Usage: async-run.mjs start [--video-url URL] | wait --run-id ID [--max-wait SECONDS]');
  if (command === 'start') {
    if (values['run-id'] !== undefined || values['max-wait'] !== undefined) throw new Error('start does not accept --run-id or --max-wait.');
    return { command, videoUrl: values['video-url'] ?? DEFAULT_VIDEO_URL };
  }
  if (values['video-url'] !== undefined) throw new Error('wait does not accept a video URL and never creates a Run.');
  if (typeof values['run-id'] !== 'string' || values['run-id'].trim().length === 0) throw new Error('wait requires a non-empty --run-id.');
  const seconds = parseMaxWaitSeconds(values['max-wait'] ?? String(DEFAULT_MAX_WAIT_SECONDS));
  return { command, runId: values['run-id'].trim(), maxWaitMs: seconds * 1000 };
}

export async function startRun(token, videoUrl, {
  createRun = startActorRunOnce,
  output = process.stdout,
} = {}) {
  const validationError = validateTikTokVideoUrl(videoUrl);
  if (validationError) throw new Error(`Input error: ${validationError}`);
  await writeLine(`Actor: ${TIKTOK_ACTOR_SLUG}`, output);
  await writeLine(RUN_CREATION_LIMITATION, output);
  let run;
  try {
    run = await createRun(token, videoUrl);
  } catch (error) {
    throw new RunCreationUnknownError(
      `Run creation result is unknown; check Apify Console to see whether it was created. Do not retry or start another Run until checked. Details: ${safeError(error, token)}`,
      { cause: error },
    );
  }
  if (typeof run.id !== 'string' || run.id.length === 0) throw new Error('Run creation response did not contain a valid Run ID.');
  await writeLine(JSON.stringify({ run_id: run.id, status: run.status }), output);
  return run.id;
}

export async function waitAndReadRun(token, runId, {
  maxWaitMs = 900_000,
  pollIntervalMs,
  requestImpl,
  getRunFn = getRun,
  waitForRunFn = waitForRun,
  readDataset = getDatasetItems,
  outputDir = OUTPUT_DIR,
  output = process.stdout,
} = {}) {
  // CLI seconds are range-checked before conversion; keep direct millisecond callers finite too.
  validateMaxWaitMs(maxWaitMs);
  let run;
  try {
    run = await waitForRunFn(token, runId, { maxWaitMs, pollIntervalMs, requestImpl, getRunFn });
  } catch (error) {
    if (error instanceof ApiRequestError && error.statusCode === 404) throw new Error(`Run not found: ${runId}. No new Run was created.`);
    throw error;
  }
  await writeLine(`Run ID: ${run.id}`, output);
  await writeLine(`Run status: ${run.status}`, output);
  if (run.status !== 'SUCCEEDED') throw new Error(`Actor Run finished with failure status ${run.status}.`);
  if (typeof run.defaultDatasetId !== 'string' || run.defaultDatasetId.length === 0) {
    throw new Error('Dataset error: completed Run has no default Dataset ID.');
  }
  const items = await readDataset(token, run.defaultDatasetId, { requestImpl });
  await mkdir(outputDir, { recursive: true });
  const outputFile = path.join(outputDir, `nodejs-async-run-${run.id}.json`);
  await writeFile(outputFile, `${JSON.stringify(items, null, 2)}\n`, 'utf8');
  const transcript = assertSuccessfulDataset(run, items);
  await writeLine(`Dataset ID: ${run.defaultDatasetId}`, output);
  await writeLine(`Output path: ${outputFile}`, output);
  await writeLine(`text: ${transcript.text}`, output);
  await writeLine(`segments: ${JSON.stringify(items.find((item) => item?.segments !== undefined)?.segments ?? [])}`, output);
  await writeLine(`errMsg: ${transcript.errMsg}`, output);
  return { run, items, outputFile };
}

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const args = parseCommandArgs(argv);
  if (args.command === 'start') {
    const validationError = validateTikTokVideoUrl(args.videoUrl);
    if (validationError) throw new Error(`Input error: ${validationError}`);
  }
  (dependencies.loadEnv ?? loadLocalEnv)(REPO_ROOT);
  const token = (dependencies.requireToken ?? requireApifyToken)(dependencies.env ?? process.env);
  if (args.command === 'start') {
    return startRun(token, args.videoUrl, dependencies.startDependencies);
  }
  return waitAndReadRun(token, args.runId, { ...dependencies.waitDependencies, maxWaitMs: args.maxWaitMs });
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
