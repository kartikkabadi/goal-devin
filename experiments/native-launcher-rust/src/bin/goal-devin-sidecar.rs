use goal_devin_rust::sidecar;
use std::path::PathBuf;

fn main() {
    let runtime_dir = std::env::args().nth(1).map(PathBuf::from);
    let code = match runtime_dir {
        Some(dir) => sidecar::run(dir),
        None => {
            eprintln!("usage: goal-devin-sidecar <runtime-dir>");
            2
        }
    };
    std::process::exit(code);
}
