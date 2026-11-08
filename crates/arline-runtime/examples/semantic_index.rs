//! Explicit index maintenance. No semantic-search or writer endpoint is exposed.
use arline_runtime::{
    config::RuntimeConfig,
    foundation::memory::{
        embedding::BekkoConfig,
        semantic_index::{self, IndexScope},
    },
    AppState,
};
use clap::{Parser, Subcommand};
use serde_json::{json, Value};
use std::path::PathBuf;

#[derive(Parser)]
struct Args {
    /// Explicit application data root; never infer a database from the CWD.
    #[arg(long)]
    root: PathBuf,
    #[arg(long)]
    config: PathBuf,
    /// Optional explicit database override (must be absolute).
    #[arg(long)]
    database: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Status {
        #[arg(long)]
        fingerprint: String,
        #[arg(long)]
        project: Option<String>,
    },
    Reconcile {
        #[arg(long)]
        fingerprint: String,
        #[arg(long)]
        project: Option<String>,
    },
    IndexPending {
        #[arg(long)]
        project: Option<String>,
        #[arg(long, default_value_t = 32)]
        batch_size: usize,
    },
    IndexSource {
        #[arg(long)]
        source_type: String,
        #[arg(long)]
        source_id: String,
        #[arg(long, default_value_t = 32)]
        batch_size: usize,
    },
    Resume {
        job_id: String,
        #[arg(long, default_value_t = 32)]
        batch_size: usize,
    },
    Cancel {
        job_id: String,
    },
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    if !args.root.is_absolute() || !args.config.is_absolute() {
        return Err("--root and --config must be absolute".into());
    }
    let mut config = RuntimeConfig::load(&args.config, &args.root)?;
    if let Some(path) = args.database {
        if !path.is_absolute() {
            return Err("--database must be absolute".into());
        }
        config.set(
            "workspace.database_path",
            toml::Value::String(path.to_string_lossy().into_owned()),
        )?;
    }
    let native = || BekkoConfig::from_runtime(&config);
    if !config.database_path().is_file() {
        return Err(
            "configured database does not exist; use --database to select an existing workspace"
                .into(),
        );
    }
    let state = AppState::open_index_maintenance(config.clone())?;
    let result: Value = match args.command {
        Command::Status {
            fingerprint,
            project,
        } => serde_json::to_value(semantic_index::index_status(
            &state,
            &fingerprint,
            &IndexScope {
                project_id: project,
                ..Default::default()
            },
        )?)?,
        Command::Reconcile {
            fingerprint,
            project,
        } => serde_json::to_value(semantic_index::reconcile_index(
            &state,
            &fingerprint,
            &IndexScope {
                project_id: project,
                ..Default::default()
            },
        )?)?,
        Command::IndexPending {
            project,
            batch_size,
        } => {
            semantic_index::index_pending(
                state,
                native()?,
                IndexScope {
                    project_id: project,
                    ..Default::default()
                },
                batch_size,
            )
            .await?
        }
        Command::IndexSource {
            source_type,
            source_id,
            batch_size,
        } => {
            semantic_index::index_source(state, native()?, &source_type, &source_id, batch_size)
                .await?
        }
        Command::Resume { job_id, batch_size } => {
            semantic_index::resume_job(state, &job_id, native()?, batch_size).await?
        }
        Command::Cancel { job_id } => {
            json!({"job_id":job_id,"cancel_requested":semantic_index::cancel_index_job(&state,&job_id)?})
        }
    };
    println!("{}", serde_json::to_string_pretty(&result)?);
    Ok(())
}
