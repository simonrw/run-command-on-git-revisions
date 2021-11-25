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

fn get_commits(
    repo: &Repository,
    start: impl Display,
    end: impl Display,
) -> Result<Vec<git2::Oid>> {
    let mut walk = repo.revwalk()?;
    let range = format!("{start}..{end}", start = start, end = end);
    walk.set_sorting(git2::Sort::REVERSE)?;
    walk.push_range(&range).wrap_err("defining walk range")?;
    Ok(walk.map(|oid| oid.unwrap()).collect::<Vec<_>>())
}

struct DropGuard {
    worktree: git2::Worktree,
    path: PathBuf,
}

impl Deref for DropGuard {
    type Target = git2::Worktree;

    fn deref(&self) -> &Self::Target {
        &self.worktree
    }
}

impl DropGuard {
    fn path(&self) -> &Path {
        self.path.as_path()
    }

    fn new(worktree: git2::Worktree, path: impl Into<PathBuf>) -> Self {
        Self {
            worktree,
            path: path.into(),
        }
    }
}

impl Drop for DropGuard {
    fn drop(&mut self) {
        eprintln!("pruning worktree");
        let _ = self.worktree.prune(None);

        eprintln!("removing worktree dir: {:?}", self.worktree.path());
        let _ = std::fs::remove_dir_all(self.worktree.path());

        eprintln!("dropping temporary directory: {:?}", &self.path);
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn main() -> Result<()> {
    let args = Opts::from_args();
    let repo = match args.path {
        Some(path) => Repository::open(path).wrap_err("opening git repository")?,
        None => Repository::open(".").wrap_err("opening git repository")?,
    };

    let commits = get_commits(&repo, &args.start, &args.end).wrap_err("computing commits")?;

    let repo = Arc::new(Mutex::new(repo));
    commits.into_iter().for_each(|oid| {
        let worktree_name = format!("worktree-{}-{}", oid, uuid::Uuid::new_v4());
        let new_path = dbg!(std::env::temp_dir().join(&worktree_name));
        {
            let repo = repo.lock().unwrap();
            let worktree = DropGuard::new(
                repo.worktree(&worktree_name, &new_path, None).unwrap(),
                new_path,
            );
        }
    });
    Ok(())
}
