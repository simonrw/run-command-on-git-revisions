use eyre::{Result, WrapErr};
use git2::Repository;
use rayon::prelude::*;
use std::fmt::Display;
use std::path::{Path, PathBuf};
use std::process::Command;
use structopt::StructOpt;

#[derive(Debug, StructOpt)]
struct Opts {
    /// Start ref
    #[structopt(short, long)]
    start: String,
    /// End ref
    #[structopt(short, long)]
    end: String,
    /// Command to run on each commit
    command: String,
    /// Path to repository (defaults to current directory)
    #[structopt(short, long)]
    path: Option<PathBuf>,
    /// Run a single task at once
    #[structopt(long)]
    single: bool,
}

#[tracing::instrument(skip(start, end))]
fn get_commits(repo_path: &Path, start: impl Display, end: impl Display) -> Result<Vec<git2::Oid>> {
    tracing::debug!(%start, %end, "getting commits");
    let repo = Repository::open(repo_path)?;
    let mut walk = repo.revwalk()?;
    let range = format!("{start}..{end}", start = start, end = end);
    walk.set_sorting(git2::Sort::REVERSE)?;
    walk.push_range(&range).wrap_err("defining walk range")?;
    Ok(walk.map(|oid| oid.unwrap()).collect::<Vec<_>>())
}

#[derive(Debug)]
struct ErrorDetail {
    code: i32,
    stderr: String,
    oid: git2::Oid,
}

fn checkout(repo: &Repository, oid: git2::Oid) -> Result<()> {
    let obj = repo.revparse_single(&oid.to_string())?;
    let mut checkout_options = git2::build::CheckoutBuilder::new();
    checkout_options.force();
    repo.checkout_tree(&obj, Some(&mut checkout_options))?;
    repo.set_head_detached(obj.id())?;
    Ok(())
}

#[tracing::instrument]
fn main() -> Result<()> {
    color_eyre::install().unwrap();
    tracing_subscriber::fmt::init();

    let args = Opts::from_args();
    tracing::trace!(?args, "parsed arguments");

    // configure the thread pool
    if args.single {
        rayon::ThreadPoolBuilder::new()
            .num_threads(1)
            .build_global()
            .unwrap();
    }

    let repo_path = args.path.unwrap_or_else(|| PathBuf::from("."));

    let commits = get_commits(&repo_path, &args.start, &args.end).wrap_err("computing commits")?;
    tracing::debug!(?commits, "got commits");

    let tempdir = tempfile::tempdir()?;
    let repo_path_str = repo_path.to_str().unwrap();
    let error_messages = commits.into_par_iter().map(|oid| {

        let clone_path = tempdir.path().join(oid.to_string());

        let mut builder = git2::build::RepoBuilder::new();
        let repo = builder.clone(&repo_path_str, clone_path.as_path()).unwrap();
        tracing::trace!("checking out commit");
        checkout(&repo, oid).unwrap();
        let working_dir = repo.path().join("..").canonicalize().unwrap();

        let span = tracing::debug_span!("commit", sha = ?oid, path = ?working_dir, command = ?args.command);
        let _enter = span.enter();
        tracing::debug!("cloned repo");

        tracing::info!("running user specified command");
        let output = Command::new("bash")
            .current_dir(&working_dir)
            .args(&["-c", &args.command]).output().expect("spawning user command");
        let code = output.status.code().unwrap_or(1);

        if output.status.success() {
            let stdout = String::from_utf8(output.stdout).unwrap();
            tracing::trace!(%stdout, %code, "successful exit code");
            Ok(oid)
        } else {
            let stderr = String::from_utf8(output.stderr).unwrap();
            tracing::trace!(%stderr, %code, "failed exit code");
            Err(ErrorDetail {
                code,
                oid,
                stderr,
            })
        }
    }).collect::<Vec<_>>();

    for result in error_messages {
        match result {
            Ok(oid) => println!("Commit {:?} successful", oid),
            Err(ErrorDetail { oid, code, stderr }) => {
                eprintln!("Commit {:?} failed with exit code {}", oid, code);
                eprintln!("{}", stderr);
            }
        }
    }
    Ok(())
}
