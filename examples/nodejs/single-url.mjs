import { ApifyClient } from 'apify-client';
import dotenv from 'dotenv';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DEFAULT_ACTOR_ID = 'apple_yang/tiktok-transcripts-scraper';
const DEFAULT_VIDEO_URL = 'https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392';
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '../..');
const OUTPUT_DIR = path.join(REPO_ROOT, 'sample-output', 'generated');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'nodejs-single-url-response.json');

dotenv.config({ path: path.join(REPO_ROOT, '.env') });

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Error: ${name} is required. Set it in .env or your environment.`);
  }
  return value;
}

function firstValue(items, key) {
  for (const item of items) {
    if (item?.[key] !== undefined && item[key] !== null && item[key] !== '') {
      return item[key];
    }
  }
  return undefined;
}

async function main() {
  const token = requireEnv('APIFY_TOKEN');
  const actorId = process.env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const videoUrl = process.argv[2] || process.env.TIKTOK_VIDEO_URL || DEFAULT_VIDEO_URL;

  const client = new ApifyClient({ token });
  console.log(`Actor ID: ${actorId}`);
  console.log('Running request...');

  const run = await client.actor(actorId).call({ videoUrl });
  if (run?.status && run.status !== 'SUCCEEDED') {
    throw new Error(`Error: Actor run finished with status ${run.status}.`);
  }

  const datasetId = run?.defaultDatasetId;
  if (!datasetId) {
    throw new Error('Error: Actor run completed without a defaultDatasetId.');
  }

  const response = await client.dataset(datasetId).listItems();
  const items = response.items ?? [];
  if (items.length === 0) {
    throw new Error('Error: Actor returned an empty dataset.');
  }

  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(OUTPUT_FILE, `${JSON.stringify(items, null, 2)}\n`, 'utf8');

  const text = firstValue(items, 'text') || '';
  console.log(`Output path: ${OUTPUT_FILE}`);
  console.log(`Items: ${items.length}`);
  console.log(`Title: ${firstValue(items, 'title') || ''}`);
  console.log(`Creator: ${firstValue(items, 'nickname') || ''}`);
  console.log(`Play count: ${firstValue(items, 'playCount') || ''}`);
  console.log(`Transcript characters: ${typeof text === 'string' ? text.length : 0}`);
  if (typeof text === 'string' && text) {
    console.log('Transcript preview:');
    console.log(text.slice(0, 500));
  }
  const errMsg = firstValue(items, 'errMsg');
  if (errMsg) {
    console.log(`errMsg: ${errMsg}`);
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
