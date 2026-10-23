"""Git 子进程适配器安全测试（合成仓库；不触碰真实业务仓库）。"""
from __future__ import annotations

import hashlib
import os

import pytest

from app.adapters.git import GitAdapter, GitError
from tests.helpers import git, make_repo


def _adapter(base) -> GitAdapter:
    return GitAdapter([str(base)])


def test_read_only_facts_sha1(tmp_path) -> None:
    repo = make_repo(tmp_path)
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    assert adapter.object_format(root) == "sha1"
    sha = adapter.commit_sha(root)
    assert len(sha) == 40
    assert adapter.branch(root) in {"master", "main"}
    status = adapter.workspace_status(root)
    assert status["clean"] is True
    report = adapter.verify_snapshot(root, sha)
    assert report.available is True and report.entry_count >= 1


def test_dirty_and_untracked(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="\n")
    (repo / "new.txt").write_text("x\n", encoding="utf-8", newline="\n")
    adapter = _adapter(tmp_path)
    status = adapter.workspace_status(str(repo))
    assert status["clean"] is False
    assert status["modified"] == 1
    assert status["untracked"] == 1


def test_invalid_path_rejected(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    with pytest.raises(GitError) as exc:
        adapter.repo_root(str(tmp_path / "does-not-exist"))
    assert exc.value.code == "invalid_path"


def test_non_git_repo_rejected(tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    adapter = _adapter(tmp_path)
    with pytest.raises(GitError) as exc:
        adapter.repo_root(str(plain))
    assert exc.value.code == "not_git_repository"


def test_unauthorized_root_rejected(tmp_path) -> None:
    repo = make_repo(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    adapter = _adapter(allowed)
    with pytest.raises(GitError) as exc:
        adapter.repo_root(str(repo))
    assert exc.value.code == "path_not_authorized"


def test_sha256_object_format(tmp_path) -> None:
    repo = make_repo(tmp_path, name="repo256", object_format="sha256")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    assert adapter.object_format(root) == "sha256"
    assert len(adapter.commit_sha(root)) == 64
    report = adapter.verify_snapshot(root, adapter.commit_sha(root))
    assert report.available is True


def test_path_traversal_guard() -> None:
    with pytest.raises(GitError) as exc:
        GitAdapter._check_paths_safe(["../etc/passwd"])
    assert exc.value.code == "path_traversal"
    with pytest.raises(GitError):
        GitAdapter._check_paths_safe(["C:/windows/system32"])


def test_missing_commit_unavailable(tmp_path) -> None:
    repo = make_repo(tmp_path)
    adapter = _adapter(tmp_path)
    report = adapter.verify_snapshot(str(repo), "0" * 40)
    assert report.available is False and report.reason == "commit_missing"


def test_symlink_and_gitlink_flagged(tmp_path) -> None:
    repo = make_repo(tmp_path)
    blob = git(repo, "rev-parse", "HEAD:a.txt").stdout.strip()
    commit = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", "120000", blob, "link")
    git(repo, "update-index", "--add", "--cacheinfo", "160000", commit, "sub")
    git(repo, "commit", "-m", "special entries")
    adapter = _adapter(tmp_path)
    sha = adapter.commit_sha(str(repo))
    report = adapter.verify_snapshot(str(repo), sha)
    assert report.available is True
    assert report.symlink_count >= 1
    assert report.gitlink_count >= 1
    assert any("symlink" in w for w in report.summary["warnings"])
    assert any("gitlink" in w for w in report.summary["warnings"])


def test_original_repo_not_modified(tmp_path) -> None:
    repo = make_repo(tmp_path)
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    before_head = adapter.commit_sha(root)
    before_status = adapter.workspace_status(root)["entries"]
    adapter.verify_snapshot(root, before_head)
    adapter.workspace_status(root)
    after_head = adapter.commit_sha(root)
    after_status = adapter.workspace_status(root)["entries"]
    assert before_head == after_head
    assert before_status == after_status


def test_git_metadata_not_written_by_read_ops(tmp_path) -> None:
    repo = make_repo(tmp_path)
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))

    def snapshot() -> dict:
        result = {}
        for dirpath, _dirs, files in os.walk(os.path.join(root, ".git")):
            for name in files:
                path = os.path.join(dirpath, name)
                with open(path, "rb") as handle:
                    result[os.path.relpath(path, root)] = hashlib.sha256(
                        handle.read()
                    ).hexdigest()
        return result

    before = snapshot()
    adapter.workspace_status(root)
    adapter.branch(root)
    adapter.commit_sha(root)
    adapter.verify_snapshot(root, adapter.commit_sha(root))
    after = snapshot()
    assert before == after, set(before) ^ set(after)