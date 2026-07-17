use goal_devin_rust::hook;
use std::path::PathBuf;

fn main() {
    let events_dir = std::env::args().nth(1).map(PathBuf::from);
    std::process::exit(hook::run(events_dir));
}
