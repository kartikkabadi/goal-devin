use goal_devin_rust::cli::Args;
use goal_devin_rust::supervisor::Supervisor;

fn main() {
    let args = <Args as clap::Parser>::parse();
    match Supervisor::new(args) {
        Ok(supervisor) => std::process::exit(supervisor.run()),
        Err(e) => {
            eprintln!("goal-devin-dev: {}", e);
            std::process::exit(1);
        }
    }
}
