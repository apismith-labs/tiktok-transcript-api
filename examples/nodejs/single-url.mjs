import { parseArgs } from 'node:util';
import { mkdir, open, unlink, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  assertSuccessfulDataset,
  DEFAULT_MAX_WAIT_SECONDS,
  DEFAULT_VIDEO_URL,
  getDatasetItems,
  loadLocalEnv,
  parseMaxWaitSeconds,
  requireApifyToken,
  RUN_CREATION_LIMITATION,
  RunCreationUnknownError,
  safeError,
  startActorRunOnce,
  TIKTOK_ACTOR_SLUG,
  validateTikTokVideoUrl,
  waitForRun,
  writeLine,
} from './apify-run.mjs';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '../..');
export const OUTPUT_DIR = path.join(REPO_ROOT, 'sample-output', 'generated');
export const OUTPUT_FILE = path.join(OUTPUT_DIR, 'nodejs-single-url-response.json');

async function preflightOutputDirectory(directory) {
  let handle;
  let probePath;
  try {
    await mkdir(directory, { recursive: true });
    probePath = path.join(directory, `.tiktok-transcript-output-probe-${randomUUID()}`);
    handle = await open(probePath, 'wx', 0o600);
    await handle.close();
    handle = undefined;
    await unlink(probePath);
    probePath = undefined;
  } catch (error) {
    await handle?.close().catch(() => {});
    if (probePath) await unlink(probePath).catch(() => {});
    throw new Error(`Output directory preflight failed for ${directory}: ${error.message}`, { cause: error });
  }
}

export function resolveSingleArgs(argv) {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      options: {
        'video-url': { type: 'string' },
        'max-wait': { type: 'string' },
      },
      allowPositionals: true,
      strict: true,
    });
  } catch (error) {
    // Node's parser treats a space-separated negative value as an ambiguous option argument.
    if (error?.code === 'ERR_PARSE_ARGS_INVALID_OPTION_VALUE' && error.message.includes("Option '--max-wait'")) {
      throw new Error('--max-wait must be a finite number from 1 to 86400 seconds.');
    }
    throw error;
  }
  const { values, positionals } = parsed;
  if (positionals.length > 1) throw new Error('Provide at most one positional TikTok video URL.');
  if (positionals.length && values['video-url'] !== undefined) {
    throw new Error('Provide the video URL either positionally or with --video-url, not both.');
  }
  return {
    videoUrl: values['video-url'] ?? positionals[0] ?? DEFAULT_VIDEO_URL,
    maxWaitSeconds: parseMaxWaitSeconds(values['max-wait'] ?? String(DEFAULT_MAX_WAIT_SECONDS)),
  };
}

export function resolveVideoUrlArgs(argv) {
  return resolveSingleArgs(argv).videoUrl;
}

export async function runSingleVideo({
  token,
  videoUrl,
  maxWaitSeconds = DEFAULT_MAX_WAIT_SECONDS,
  createRun = startActorRunOnce,
  waitRun = waitForRun,
  readDataset = getDatasetItems,
  outputFile = OUTPUT_FILE,
  output = process.stdout,
}) {
  const validatedMaxWaitSeconds = parseMaxWaitSeconds(maxWaitSeconds);
  const maxWaitMs = validatedMaxWaitSeconds * 1000;
  const validationError = validateTikTokVideoUrl(videoUrl);
  if (validationError) throw new Error(`Input error: ${validationError}`);
  await preflightOutputDirectory(path.dirname(outputFile));
  await writeLine(`Actor: ${TIKTOK_ACTOR_SLUG}`, output);
  await writeLine(RUN_CREATION_LIMITATION, output);
  await writeLine('Starting one Actor Run and waiting for its terminal state...', output);
  let started;
  try {
    started = await createRun(token, videoUrl);
  } catch (error) {
    throw new RunCreationUnknownError(
      `Run creation result is unknown; check Apify Console to see whether it was created. Do not retry or start another Run until checked. Details: ${safeError(error, token)}`,
      { cause: error },
    );
  }
  const runId = started.id;
  if (typeof runId !== 'string' || runId.length === 0) throw new Error('Run creation response did not contain a valid Run ID.');
  await writeLine(`Run ID: ${runId}`, output);

  let run;
  try {
    run = await waitRun(token, runId, { maxWaitMs });
  } catch (error) {
    const resumeCommand = `node examples/nodejs/async-run.mjs wait --run-id ${runId} --max-wait ${validatedMaxWaitSeconds}`;
    throw new Error(
      `Waiting for Run ${runId} did not complete: ${safeError(error, token)}. Retry only the read with the same Run ID: ${resumeCommand}`,
      { cause: error },
    );
  }
  if (run.status !== 'SUCCEEDED') throw new Error(`Actor Run finished with failure status ${run.status}.`);
  if (typeof run.defaultDatasetId !== 'string' || !run.defaultDatasetId) {
    throw new Error('Dataset error: completed Run has no default Dataset ID.');
  }
  const items = await readDataset(token, run.defaultDatasetId);
  await mkdir(path.dirname(outputFile), { recursive: true });
  await writeFile(outputFile, `${JSON.stringify(items, null, 2)}\n`, 'utf8');
  const transcript = assertSuccessfulDataset(run, items);
  await writeLine(`Run status: ${run.status}`, output);
  await writeLine(`Dataset ID: ${run.defaultDatasetId}`, output);
  await writeLine(`Output path: ${outputFile}`, output);
  await writeLine(`text: ${transcript.text}`, output);
  await writeLine(`segments: ${JSON.stringify(items.find((item) => item?.segments !== undefined)?.segments ?? [])}`, output);
  await writeLine(`errMsg: ${transcript.errMsg}`, output);
  return { run, items, outputFile };
}

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const { videoUrl, maxWaitSeconds } = resolveSingleArgs(argv);
  const validationError = validateTikTokVideoUrl(videoUrl);
  if (validationError) throw new Error(`Input error: ${validationError}`);
  (dependencies.loadEnv ?? loadLocalEnv)(REPO_ROOT);
  const token = (dependencies.requireToken ?? requireApifyToken)(dependencies.env ?? process.env);
  return runSingleVideo({ token, videoUrl, ...dependencies.runDependencies, maxWaitSeconds });
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
