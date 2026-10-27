use std::env;
use std::io::{self, Write};
use tiktok_transcript_api_rust_examples::{
    transcript_failure, ApiClient, ACTOR_DISPLAY_NAME, DEFAULT_MAX_WAIT_SECONDS, DEFAULT_VIDEO_URL,
};

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let operation = args.next().ok_or("Usage: async_run start [--video-url URL] [--max-wait SECONDS] | wait --run-id ID [--max-wait SECONDS]")?;
    let mut video_url = DEFAULT_VIDEO_URL.to_string();
    let mut run_id: Option<String> = None;
    let mut max_wait = DEFAULT_MAX_WAIT_SECONDS;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--video-url" if operation == "start" => {
                video_url = args.next().ok_or("--video-url requires a URL")?
            }
            "--run-id" if operation == "wait" => {
                run_id = Some(args.next().ok_or("--run-id requires an ID")?)
            }
            "--max-wait" => {
                max_wait = tiktok_transcript_api_rust_examples::parse_max_wait_seconds(
                    &args.next().ok_or("--max-wait requires seconds")?,
                )?
            }
            _ => return Err(format!("Invalid argument for {operation}: {arg}").into()),
        }
    }
    tiktok_transcript_api_rust_examples::validate_max_wait_seconds(max_wait)?;
    if operation == "start" {
        tiktok_transcript_api_rust_examples::validate_video_url(&video_url)?;
    } else if operation == "wait" {
        tiktok_transcript_api_rust_examples::validate_resource_run_id(
            run_id.as_deref().ok_or("wait requires --run-id")?,
        )?;
    } else {
        return Err("Operation must be start or wait".into());
    }
    let token =
        env::var("APIFY_TOKEN").map_err(|_| "APIFY_TOKEN is required in the environment")?;
    let client = ApiClient::production(token)?;
    let id = match operation.as_str() {
        "start" => {
            println!("Actor: {ACTOR_DISPLAY_NAME}");
            io::stdout().flush()?;
            let run = client.start_run(&video_url).await?;
            println!("Run ID: {}", run.id);
            io::stdout().flush()?;
            println!(
                "Run started. Use `async_run wait --run-id {}` to wait for and read its result.",
                run.id
            );
            return Ok(());
        }
        _ => run_id.expect("validated above"),
    };
    let run = client.wait_for_run(&id, max_wait).await?;
    if run.status != "SUCCEEDED" {
        return Err(format!("Actor Run {id} finished with status {}.", run.status).into());
    }
    let dataset_id = run
        .default_dataset_id
        .as_deref()
        .ok_or("Run succeeded without a default Dataset ID.")?;
    let items = client.dataset_items(dataset_id).await?;
    println!(
        "Run ID: {id}\nDataset ID: {dataset_id}\nDataset Items: {}",
        items.len()
    );
    if let Some((_, message)) = transcript_failure(&run, &items) {
        return Err(message.into());
    }
    println!("Transcript available in Dataset Items.");
    Ok(())
}
