mod lyftkube;
use crate::lyftkube::lk::lk;
use clap::{AppSettings, Parser, Subcommand};

#[derive(Parser)]
#[clap(author, version, about, long_about = None)]
struct Cli {
    #[clap(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    #[clap(
        setting(AppSettings::ArgRequiredElseHelp),
        setting(AppSettings::AllowHyphenValues),
        about = "lyftkube -> kubectl commands"
    )]
    Lk {
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
            lk(commands)
        }
        Commands::External(args) => {
            println!("Calling out to {:?} with {:?}", &args[0], &args[1..]);
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_main() {
        assert!(true)
    }
}
