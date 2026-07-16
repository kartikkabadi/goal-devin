use clap::Parser;
use std::path::PathBuf;

#[derive(Parser, Debug, Clone)]
#[command(
    name = "goal-devin-dev",
    about = "Goal Devin R1B native launcher candidate"
)]
pub struct Args {
    #[arg(long)]
    pub model: String,

    #[arg(long)]
    pub permission_mode: String,

    #[arg(long)]
    pub devin_bin: PathBuf,

    #[arg(long)]
    pub contract_dir: PathBuf,

    #[arg(long)]
    pub runtime_root: PathBuf,

    #[arg(long)]
    pub canary: Option<PathBuf>,

    #[arg(long)]
    pub existing_hooks: Option<PathBuf>,

    #[arg(long, default_value_t = false)]
    pub keep_canary: bool,

    #[arg(long, default_value_t = false)]
    pub companion: bool,

    #[arg(long, default_value_t = 100)]
    pub companion_poll_ms: u64,
}
