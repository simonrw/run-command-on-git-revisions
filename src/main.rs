use eyre::{Result, WrapErr};
use git2::Repository;
use rayon::prelude::*;
use std::fmt::Display;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use structopt::StructOpt;

#[derive(Debug, StructOpt)]
struct Opts {
    #[structopt(short, long)]
    start: String,
    #[structopt(short, long)]
    end: String,
    #[structopt(short, long)]
    path: Option<PathBuf>,
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

#[tracing::instrument]
fn main() -> Result<()> {
    color_eyre::install().unwrap();
    tracing_subscriber::fmt::init();

    let args = Opts::from_args();
    tracing::trace!(?args, "parsed arguments");
    let repo_path = args.path.unwrap_or_else(|| PathBuf::from("."));
    let commits = get_commits(&repo_path, &args.start, &args.end).wrap_err("computing commits")?;
    tracing::debug!(?commits, "got commits");

    let tempdir = tempfile::tempdir()?;
    let repo_path_str = repo_path.to_str().unwrap();
    commits.into_iter().for_each(|oid| {
        let clone_path = tempdir.path().join(oid.to_string());

        let mut builder = git2::build::RepoBuilder::new();
        let repo = builder.clone(&repo_path_str, clone_path.as_path()).unwrap();
        eprintln!("cloned repo for commit {:?}", oid);
    });
    Ok(())
}
