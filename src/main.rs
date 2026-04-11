use clap::Parser;

#[derive(Parser)]
#[clap(author, version, about, long_about = None)]
struct Cli {
    #[arg(short, long, value_name = "PROJECT")]
    project: Option<String>,
}

fn main() {
    let _args = Cli::parse();
}
