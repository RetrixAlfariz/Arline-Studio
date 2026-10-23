#![cfg_attr(
    all(windows, feature = "desktop", not(debug_assertions)),
    windows_subsystem = "windows"
)]

use arline_runtime::{config::RuntimeConfig, router, ApiError, ApiResult, AppState};
use clap::Parser;
use std::{net::IpAddr, path::PathBuf, time::Duration};

#[derive(Parser, Debug)]
#[command(
    version,
    about = "Arline Studio native Rust runtime — no Python interpreter required"
)]
struct Arguments {
    /// Existing TOML runtime configuration. Relative storage paths use --root.
    #[arg(long)]
    config: Option<PathBuf>,
    /// Resource and legacy storage root, independent from the launch directory.
    #[arg(long)]
    root: Option<PathBuf>,
    /// Override local app data location. Never overwrites an existing legacy workspace.
    #[arg(long)]
    data_dir: Option<PathBuf>,
    /// Loopback port (0 selects an available ephemeral port).
    #[arg(long)]
    port: Option<u16>,
    /// Start the HTTP runtime without opening a native desktop window.
    #[arg(long)]
    headless: bool,
    /// Copy an existing SQLite workspace using SQLite's online backup API.
    #[arg(long)]
    import_workspace: Option<PathBuf>,
    /// On first launch, copy this legacy project's config and workspace into app data.
    #[arg(long)]
    bootstrap_from: Option<PathBuf>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Arline could not start: {error}");
        std::process::exit(1);
    }
}

fn run() -> ApiResult<()> {
    let args = Arguments::parse();
    let root = args
        .root
        .unwrap_or(std::env::current_dir()?)
        .canonicalize()?;
    let data_dir = args.data_dir.map(|path| {
        if path.is_absolute() {
            path
        } else {
            root.join(path)
        }
    });
    let base = data_dir.clone().unwrap_or_else(app_data_dir);
    let mut bootstrap_import: Option<(PathBuf, PathBuf)> = None;
    if args.config.is_none() {
        std::fs::create_dir_all(&base)?;
        if let Some(source_root) = args.bootstrap_from {
            let source_root = source_root.canonicalize()?;
            let source_config = source_root.join("config/arline.toml");
            let target_config = base.join("config/arline.toml");
            if !target_config.exists() {
                let source = RuntimeConfig::load(&source_config, &source_root)?;
                std::fs::create_dir_all(target_config.parent().unwrap())?;
                copy_new(
                    &source.prompt_path(),
                    &base.join("config/writer_system.txt"),
                )?;
                let mut copied = source.raw.clone();
                if let Some(writer) = copied.get_mut("writer").and_then(toml::Value::as_table_mut) {
                    writer.insert(
                        "system_prompt_file".into(),
                        toml::Value::String("writer_system.txt".into()),
                    );
                }
                use std::io::Write;
                let mut file = std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&target_config)?;
                file.write_all(
                    toml::to_string_pretty(&copied)
                        .map_err(|e| ApiError::internal(e.to_string()))?
                        .as_bytes(),
                )?;
                file.sync_all()?;
                let target = base.join("arline_history.db");
                let source_history = source
                    .raw
                    .get("history")
                    .and_then(toml::Value::as_table)
                    .and_then(|table| table.get("database_path"))
                    .and_then(toml::Value::as_str)
                    .map(|path| source.root.join(path))
                    .unwrap_or_else(|| source.database_path());
                let source_workspace = source
                    .raw
                    .get("workspace")
                    .and_then(toml::Value::as_table)
                    .and_then(|table| table.get("database_path"))
                    .and_then(toml::Value::as_str)
                    .map(|path| source.root.join(path))
                    .unwrap_or_else(|| source_history.clone());
                if (source_history.is_file() || source_workspace.is_file()) && !target.exists() {
                    bootstrap_import = Some((source_history, source_workspace));
                }
            }
        }
    }
    let mut config = if let Some(path) = &args.config {
        RuntimeConfig::load(path, &root)?
    } else {
        std::fs::create_dir_all(&base)?;
        RuntimeConfig::create_default(base.join("config/arline.toml"), &base)?
    };
    if data_dir.is_some() || args.config.is_none() {
        std::fs::create_dir_all(&base)?;
        for (key, name) in [
            ("workspace.database_path", "arline_history.db"),
            ("history.database_path", "arline_history.db"),
            ("history.dataset_root", "datasets"),
            ("artifacts.output_root", "output"),
            ("artifacts.saved_root", "saved"),
        ] {
            config.set(
                key,
                toml::Value::String(base.join(name).to_string_lossy().into_owned()),
            )?;
        }
    }
    let import_sources = args
        .import_workspace
        .map(|source| (source.clone(), source))
        .or(bootstrap_import);
    if let Some((history_source, workspace_source)) = import_sources {
        let report = arline_runtime::import::import_legacy_workspace(
            &history_source,
            &workspace_source,
            &config.database_path(),
        )?;
        println!(
            "Imported workspace: {} media copied, {} missing, {} sessions, {} turns",
            report.media_copied,
            report.media_missing,
            report.history_sessions,
            report.history_turns
        );
    }
    let host: IpAddr = config
        .str("ui.host", "127.0.0.1")
        .parse()
        .map_err(|_| ApiError::bad_request("ui.host must be a loopback IP address"))?;
    if !host.is_loopback() {
        return Err(ApiError::bad_request(
            "The native runtime only binds loopback addresses",
        ));
    }
    let port = args.port.unwrap_or(
        u16::try_from(config.u64("ui.port", 7860))
            .map_err(|_| ApiError::bad_request("Invalid UI port"))?,
    );
    let state = AppState::open(config)?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    let listener = runtime
        .block_on(tokio::net::TcpListener::bind((host, port)))
        .map_err(|error| ApiError::internal(format!("Cannot bind {host}:{port}: {error}")))?;
    let address = listener.local_addr()?;
    let origin = format!("http://{address}");
    println!("Arline Rust runtime {origin}");
    println!("Storage: {}", state.store.path.display());
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel::<()>();
    let server = runtime.spawn(async move {
        axum::serve(listener, router(state))
            .with_graceful_shutdown(async {
                let _ = shutdown_rx.await;
            })
            .await
    });
    #[cfg(feature = "desktop")]
    if !args.headless {
        desktop_window(&origin)?;
    }
    #[cfg(not(feature = "desktop"))]
    if !args.headless {
        println!("Native window feature is not enabled; build with --features desktop or use --headless.");
    }
    if args.headless || !cfg!(feature = "desktop") {
        runtime
            .block_on(tokio::signal::ctrl_c())
            .map_err(|error| ApiError::internal(error.to_string()))?;
    }
    let _ = shutdown_tx.send(());
    match runtime.block_on(async { tokio::time::timeout(Duration::from_secs(5), server).await }) {
        Ok(Ok(Ok(()))) => Ok(()),
        Ok(Ok(Err(error))) => Err(ApiError::internal(error.to_string())),
        Ok(Err(error)) => Err(ApiError::internal(error.to_string())),
        Err(_) => {
            runtime.shutdown_timeout(Duration::from_secs(1));
            Ok(())
        }
    }
}

fn copy_new(source: &std::path::Path, target: &std::path::Path) -> ApiResult<()> {
    if target.exists() {
        return Ok(());
    }
    let mut source = std::fs::File::open(source)?;
    let mut target = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)?;
    std::io::copy(&mut source, &mut target)?;
    target.sync_all()?;
    Ok(())
}

fn app_data_dir() -> PathBuf {
    #[cfg(windows)]
    if let Some(value) = std::env::var_os("LOCALAPPDATA") {
        return PathBuf::from(value).join("Arline Studio");
    }
    if let Some(value) = std::env::var_os("XDG_DATA_HOME") {
        return PathBuf::from(value).join("arline-studio");
    }
    if let Some(value) = std::env::var_os("HOME") {
        return PathBuf::from(value).join(".local/share/arline-studio");
    }
    std::env::temp_dir().join("arline-studio")
}

#[cfg(feature = "desktop")]
fn desktop_window(origin: &str) -> ApiResult<()> {
    let url = origin
        .parse::<url::Url>()
        .map_err(|error| ApiError::internal(error.to_string()))?;
    tauri::Builder::default()
        .setup(move |app| {
            tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(url))
                .title("Arline Studio")
                .inner_size(1440.0, 900.0)
                .min_inner_size(760.0, 560.0)
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .map_err(|error| ApiError::internal(error.to_string()))
}
