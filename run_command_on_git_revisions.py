#!/usr/bin/env python

from __future__ import annotations
from abc import ABC, abstractmethod

import argparse
import tempfile
from contextlib import contextmanager
import subprocess as sp
from concurrent.futures import ThreadPoolExecutor, as_completed
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List, Optional

from rich.console import Console
from rich.progress import track, Progress


class TestRunner(ABC):
    def __init__(self, root: Path) -> None:
        self.root = root

    @abstractmethod
    def run_tests(
        self, commits: List[str], command: str, show_output: bool
    ) -> TestResults:
        ...

    def run_test(self, commit: str, command: str, show_output: bool) -> TestResult:
        cmd = shlex.split(command)
        with self.create_worktree(commit) as worktree_path:
            if show_output:
                res = sp.run(cmd, cwd=worktree_path)
            else:
                res = sp.run(cmd, cwd=worktree_path, stdout=sp.PIPE, stderr=sp.PIPE)
            return TestResult.from_child(commit, res)

    @contextmanager
    def create_worktree(self, commit: str) -> Generator[Path, None, None]:
        with tempfile.TemporaryDirectory(prefix="rcogr-") as tdir:
            self.git_worktree_add(tdir, commit)
            try:
                yield Path(tdir)
            finally:
                self.git_worktree_rm(tdir)

    def git_worktree_add(self, path: str, commit: str):
        cmd = ["git", "-C", str(self.root), "worktree", "add", path, commit]
        sp.run(cmd, check=True, stdout=sp.PIPE, stderr=sp.PIPE)

    def git_worktree_rm(self, path: str):
        cmd = ["git", "-C", str(self.root), "worktree", "remove", "--force", path]
        sp.run(cmd, check=True, stdout=sp.PIPE, stderr=sp.PIPE)


def null_track(c, **kwargs):
    return c


class SingleThreadedTestRunner(TestRunner):
    def run_tests(
        self, commits: List[str], command: str, show_output: bool
    ) -> TestResults:
        results = []

        if show_output:
            progress_wrapper = null_track
        else:
            progress_wrapper = track

        for commit in progress_wrapper(commits, description="Working..."):
            res = self.run_test(commit, command, show_output)
            results.append(res)

        return TestResults(results)


class NullProgress:
    def add_task(self, *args, **kwargs):
        pass

    def advance(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        pass


class MultiThreadedTestRunner(TestRunner):
    def run_tests(
        self, commits: List[str], command: str, show_output: bool
    ) -> TestResults:
        futures = []

        if show_output:
            progress_cls = NullProgress
        else:
            progress_cls = Progress

        with progress_cls() as progress:
            task = progress.add_task("Working...", total=len(commits))
            with ThreadPoolExecutor() as pool:
                for commit in commits:
                    fut = pool.submit(self.run_test, commit, command, show_output)
                    futures.append(fut)

                results = []
                for fut in as_completed(futures):
                    results.append(fut.result())
                    progress.advance(task)

        return TestResults(results)


class Repository:
    test_runner: TestRunner

    def __init__(self, root: Path, single_threaded: bool) -> None:
        self.root = root
        if single_threaded:
            self.test_runner = SingleThreadedTestRunner(root)
        else:
            self.test_runner = MultiThreadedTestRunner(root)

    def run_tests(
        self, start: str, end: str, command: str, show_output: bool
    ) -> TestResults:
        commits_in_range = self.get_commit_range(start, end)
        return self.test_runner.run_tests(commits_in_range, command, show_output)

    def get_commit_range(self, start: str, end: str) -> List[str]:
        cmd = ["git", "-C", str(self.root), "rev-list", f"{start}..{end}"]
        res = sp.run(cmd, check=True, stdout=sp.PIPE)
        return [every.strip() for every in res.stdout.decode("utf-8").split()]


@dataclass
class TestResult:
    stdout: Optional[str]
    stderr: Optional[str]
    return_code: int
    commit: str

    def success(self) -> bool:
        return self.return_code == 0

    @classmethod
    def from_child(cls, commit: str, child: sp.CompletedProcess) -> TestResult:
        return cls(
            return_code=child.returncode,
            stdout=child.stdout.decode("utf-8") if child.stdout is not None else None,
            stderr=child.stderr.decode("utf-8") if child.stderr is not None else None,
            commit=commit,
        )


class TestResults:
    def __init__(self, test_results: List[TestResult]) -> None:
        self.test_results = test_results

    def present(self, console: Console):
        for result in self.test_results:
            if result.success():
                console.print(f"Commit {result.commit} ok")
            else:
                console.print(f"Commit {result.commit} failed")
                if result.stdout is not None:
                    console.print("--- stdout:")
                    for line in result.stdout.split():
                        line = line.strip()
                        console.print(f"--- {line}")

                if result.stderr is not None:
                    console.print("--- stderr:")
                    for line in result.stderr.split():
                        line = line.strip()
                        console.print(f"--- {line}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("-s", "--start", required=True)
    parser.add_argument("-e", "--end", required=False, default="HEAD")
    parser.add_argument("-p", "--path", required=False, type=Path, default=Path.cwd())
    parser.add_argument("--show-output", action="store_true", default=False)
    parser.add_argument("--single-threaded", action="store_true", default=False)
    args = parser.parse_args()

    console = Console()
    repo = Repository(args.path, args.single_threaded)
    results = repo.run_tests(
        args.start, args.end, args.command, show_output=args.show_output
    )
    results.present(console)
