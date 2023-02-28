mod lyftkube;
use crate::lyftkube::lk::lk;
use clap::{ Parser, Subcommand};

#[derive(Parser)]
#[clap(author, version, about, long_about = None)]
struct Cli {
    #[arg(short, long, value_name = "PROJECT")]
    project: Option<String>,
    #[clap(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    #[clap(
        about = "lyftkube -> kubectl commands"
    )]
    #[command(arg_required_else_help = true)]
    Lk {
        #[arg(allow_hyphen_values = true)]
        #[clap(required = true)]
        commands: Vec<String>,
    },
    #[clap(external_subcommand)]
    External(Vec<String>),
}

fn main() {
    let args = Cli::parse();

    match &args.command {
        Commands::Lk { commands } => {
            lk(commands, if let Some(name) = &args.project.as_deref() { name } else { "" });
        }
        Commands::External(args) => {
            println!("Calling out to {:?} with {:?}", &args[0], &args[1..]);
        }
    }
}
