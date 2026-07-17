use clap::Parser;
use goal_devin_rust::companion::app::App;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    name = "goal-devin-companion",
    about = "Optional Goal Devin companion TUI"
)]
struct Args {
    #[arg(long)]
    runtime_dir: PathBuf,
    #[arg(long, default_value_t = 100)]
    poll_ms: u64,
    #[arg(long, action = clap::ArgAction::SetTrue)]
    no_color: bool,
    #[arg(long, action = clap::ArgAction::SetTrue)]
    ascii: bool,
}

fn main() {
    let args = Args::parse();
    let mut app = App::new(&args.runtime_dir, args.no_color, args.ascii, args.poll_ms);
    match app.run() {
        Ok(code) => std::process::exit(code),
        Err(e) => {
            eprintln!("goal-devin-companion: {}", e);
            std::process::exit(1);
        }
    }
}
