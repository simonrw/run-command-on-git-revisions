#!/usr/bin/env python

from __future__ import annotations
from abc import ABC, abstractmethod

import argparse
import tempfile
from contextlib import contextmanager
import subprocess as sp
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Iterator, List


class TestRunner(ABC):
    def __init__(self, root: Path) -> None:
        self.root = root

    @abstractmethod
    def run_tests(self, commits: List[str], command: str) -> TestResults:
        pass

    def run_test(self, commit: str, command: str) -> TestResult:
        cmd = shlex.split(command)
        with self.create_worktree(commit) as worktree_path:
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


class Repository:
    test_runner: TestRunner

    def __init__(self, root: Path, single_threaded: bool) -> None:
        self.root = root
        if single_threaded:
            self.test_runner = SingleThreadedTestRunner(root)
        else:
            self.test_runner = MultiThreadedTestRunner(root)

    def run_tests(self, start: str, end: str, command: str) -> TestResults:
        commits_in_range = self.get_commit_range(start, end)
        return self.test_runner.run_tests(commits_in_range, command)

    def get_commit_range(self, start: str, end: str) -> List[str]:
        cmd = ["git", "-C", str(self.root), "rev-list", f"{start}..{end}"]
        res = sp.run(cmd, check=True, stdout=sp.PIPE)
        return [every.strip() for every in res.stdout.decode("utf-8").split()]


class SingleThreadedTestRunner(TestRunner):
    def run_tests(self, commits: List[str], command: str) -> TestResults:
        results = []
        for commit in commits:
            res = self.run_test(commit, command)
            results.append(res)

        return TestResults(results)


class MultiThreadedTestRunner(TestRunner):
    def run_tests(self, commits: List[str], command: str) -> TestResults:
        futures = []
        with ThreadPoolExecutor() as pool:
            for commit in commits:
                fut = pool.submit(self.run_test, commit, command)
                futures.append(fut)

        return TestResults.from_futures(as_completed(futures))


@dataclass
class TestResult:
    stdout: str
    stderr: str
    return_code: int
    commit: str

    def success(self) -> bool:
        return self.return_code == 0

    @classmethod
    def from_child(cls, commit: str, child: sp.CompletedProcess) -> TestResult:
        return cls(
            return_code=child.returncode,
            stdout=child.stdout.decode("utf-8"),
            stderr=child.stderr.decode("utf-8"),
            commit=commit,
        )


class TestResults:
    def __init__(self, test_results: List[TestResult]) -> None:
        self.test_results = test_results

    @classmethod
    def from_futures(cls, futures: Iterator[Future[TestResult]]) -> TestResults:
        results = []
        for fut in futures:
            results.append(fut.result())

        return cls(results)

    def present(self):
        for result in self.test_results:
            print(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("-s", "--start", required=True)
    parser.add_argument("-e", "--end", required=False, default="HEAD")
    parser.add_argument("-p", "--path", required=False, type=Path, default=Path.cwd())
    parser.add_argument("--single-threaded", action="store_true", default=False)
    args = parser.parse_args()

    repo = Repository(args.path, args.single_threaded)
    results = repo.run_tests(args.start, args.end, args.command)
    results.present()
