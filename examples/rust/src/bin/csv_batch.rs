use std::env;
use std::path::PathBuf;
use tiktok_transcript_api_rust_examples::{
    generated_output_path, process_csv, reconcile_csv, validate_concurrency,
    validate_max_wait_seconds, ApiClient, DEFAULT_MAX_WAIT_SECONDS,
};

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut csv = None;
    let mut journal = None;
    let mut concurrency = 2usize;
    let mut max_wait = DEFAULT_MAX_WAIT_SECONDS;
    let mut reconcile = false;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--csv" => csv = Some(PathBuf::from(args.next().ok_or("--csv requires a path")?)),
            "--journal" => {
                journal = Some(PathBuf::from(
                    args.next().ok_or("--journal requires a path")?,
                ))
            }
            "--concurrency" => {
                concurrency = args
                    .next()
                    .ok_or("--concurrency requires a number")?
                    .parse()
                    .map_err(|_| "--concurrency must be an integer")?
            }
            "--max-wait" => {
                max_wait = tiktok_transcript_api_rust_examples::parse_max_wait_seconds(
                    &args.next().ok_or("--max-wait requires seconds")?,
                )?
            }
            "--reconcile" => reconcile = true,
            _ => return Err(format!("Unknown argument: {arg}").into()),
        }
    }
    validate_concurrency(concurrency)?;
    validate_max_wait_seconds(max_wait)?;
    let csv = csv.ok_or("--csv is required")?;
    let journal = journal.unwrap_or_else(|| generated_output_path("rust-csv-batch.jsonl"));
    if reconcile {
        for record in reconcile_csv(&csv, &journal)? {
            println!(
                "key={} status={} videoUrl={:?} currentUrl={:?} run_id={:?} error={:?}",
                record.key,
                record.status,
                record.video_url,
                record.current_url,
                record.run_id,
                record.error
            );
        }
        return Ok(());
    }
    let token =
        env::var("APIFY_TOKEN").map_err(|_| "APIFY_TOKEN is required in the environment")?;
    let api = ApiClient::production(token)?;
    let summary = process_csv(&csv, &journal, concurrency, max_wait, api).await?;
    println!("Batch summary: {summary:?}");
    Ok(())
}
