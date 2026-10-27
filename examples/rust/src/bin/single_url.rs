use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::Path;
use tiktok_transcript_api_rust_examples::{
    generated_output_path, preflight_output_directory, transcript_failure, ApiClient,
    ACTOR_DISPLAY_NAME, DEFAULT_MAX_WAIT_SECONDS, DEFAULT_VIDEO_URL,
};

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut video_url = DEFAULT_VIDEO_URL.to_string();
    let mut max_wait = DEFAULT_MAX_WAIT_SECONDS;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--video-url" => video_url = args.next().ok_or("--video-url requires a URL")?,
            "--max-wait" => {
                max_wait = tiktok_transcript_api_rust_examples::parse_max_wait_seconds(
                    &args.next().ok_or("--max-wait requires seconds")?,
                )?;
            }
            _ => return Err(format!("Unknown argument: {arg}").into()),
        }
    }
    tiktok_transcript_api_rust_examples::validate_video_url(&video_url)?;
    tiktok_transcript_api_rust_examples::validate_max_wait_seconds(max_wait)?;
    let token =
        env::var("APIFY_TOKEN").map_err(|_| "APIFY_TOKEN is required in the environment")?;
    let client = ApiClient::production(token)?;

    run_single(
        &client,
        &video_url,
        max_wait,
        &generated_output_path("rust-single-url-response.json"),
    )
    .await
}

async fn run_single(
    client: &ApiClient,
    video_url: &str,
    max_wait: u64,
    output: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    tiktok_transcript_api_rust_examples::validate_video_url(video_url)?;
    tiktok_transcript_api_rust_examples::validate_max_wait_seconds(max_wait)?;
    let output_directory = output
        .parent()
        .ok_or("Output path has no parent directory.")?;
    preflight_output_directory(output_directory)?;
    println!("Actor: {ACTOR_DISPLAY_NAME}");
    println!("Creating Run and waiting for completion...");
    io::stdout().flush()?;
    let created = client.start_run(video_url).await?;
    println!("Run ID: {}", created.id);
    io::stdout().flush()?;
    let run = client.wait_for_run(&created.id, max_wait).await?;
    if run.status != "SUCCEEDED" {
        return Err(format!("Actor Run finished with status {}.", run.status).into());
    }
    let dataset_id = run
        .default_dataset_id
        .as_deref()
        .ok_or("Run succeeded without a default Dataset ID.")?;
    let items = client.dataset_items(dataset_id).await?;
    fs::write(
        output,
        format!("{}\n", serde_json::to_string_pretty(&items)?),
    )?;
    println!("Dataset Items: {}", items.len());
    println!("Output: {}", output.display());
    for field in ["text", "segments", "errMsg"] {
        let value = items.first().and_then(|item| item.get(field));
        println!(
            "{field}: {}",
            value
                .map(|v| v.to_string())
                .unwrap_or_else(|| "<missing>".to_string())
        );
    }
    if let Some((_, message)) = transcript_failure(&run, &items) {
        return Err(message.into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use tiktok_transcript_api_rust_examples::{
        HttpRequest, HttpTransport, TransportError, TransportFuture,
    };

    static TEMP_SEQUENCE: AtomicUsize = AtomicUsize::new(0);

    fn unique_temp_dir(label: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "{label}-{}-{}",
            std::process::id(),
            TEMP_SEQUENCE.fetch_add(1, Ordering::SeqCst)
        ));
        std::fs::create_dir(&path).unwrap();
        path
    }

    struct CountingTransport(Arc<AtomicUsize>);

    impl HttpTransport for CountingTransport {
        fn send<'a>(&'a self, _request: HttpRequest) -> TransportFuture<'a> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Box::pin(async { Err(TransportError) })
        }
    }

    #[tokio::test]
    async fn output_preflight_failure_happens_before_run_creation() {
        let temp = unique_temp_dir("rust-output-preflight-test");
        let blocker = temp.join("not-a-directory");
        std::fs::write(&blocker, "preserve me").unwrap();
        let requests = Arc::new(AtomicUsize::new(0));
        let client = ApiClient::new(
            "offline-token",
            Arc::new(CountingTransport(requests.clone())),
        )
        .unwrap();
        let error = run_single(
            &client,
            DEFAULT_VIDEO_URL,
            DEFAULT_MAX_WAIT_SECONDS,
            &blocker.join("generated").join("result.json"),
        )
        .await
        .unwrap_err();
        assert!(error
            .to_string()
            .contains("Output directory preflight failed"));
        assert_eq!(requests.load(Ordering::SeqCst), 0);
        assert_eq!(std::fs::read_to_string(&blocker).unwrap(), "preserve me");
        assert_eq!(std::fs::read_dir(&temp).unwrap().count(), 1);
        std::fs::remove_dir_all(temp).unwrap();
    }

    #[test]
    fn successful_output_probe_is_removed_without_truncating_existing_result() {
        let temp = unique_temp_dir("rust-output-probe-test");
        let result = temp.join("rust-single-url-response.json");
        std::fs::write(&result, "existing result").unwrap();
        preflight_output_directory(&temp).unwrap();
        assert_eq!(std::fs::read_to_string(&result).unwrap(), "existing result");
        assert_eq!(std::fs::read_dir(&temp).unwrap().count(), 1);
        std::fs::remove_dir_all(temp).unwrap();
    }
}
