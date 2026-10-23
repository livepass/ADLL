"""快照物化：tree/归档一致性、export-ignore/subst、LFS、symlink/gitlink、敏感排除。"""
from __future__ import annotations

from app.adapters.git import GitAdapter
from app.services import snapshot
from tests.helpers import git, make_repo


def _adapter(base) -> GitAdapter:
    return GitAdapter([str(base)])


def _commit(repo, *names) -> None:
    for name in names:
        git(repo, "add", name)
    git(repo, "commit", "-m", "fixture")


def test_materialize_clean(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / "b.txt").write_text("b\n", encoding="utf-8", newline="\n")
    _commit(repo, "b.txt")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    sha = adapter.commit_sha(root)
    result = snapshot.materialize(adapter, root, sha)
    assert result.available is True
    assert {f["path"] for f in result.files} == {"a.txt", "b.txt"}
    assert result.digest and result.lfs_pointers == []
    assert any("attribute_mode=" in w for w in result.warnings)


def test_authorized_subset(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / "b.txt").write_text("b\n", encoding="utf-8", newline="\n")
    _commit(repo, "b.txt")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    result = snapshot.materialize(
        adapter, root, adapter.commit_sha(root), authorized_paths=["a.txt"]
    )
    assert [f["path"] for f in result.files] == ["a.txt"]
    assert any(e["path"] == "b.txt" and e["reason"] == "not_authorized" for e in result.excluded)


def test_sensitive_excluded(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".env").write_text("X=1\n", encoding="utf-8", newline="\n")
    (repo / "secret.key").write_text("key\n", encoding="utf-8", newline="\n")
    _commit(repo, ".env", "secret.key")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    result = snapshot.materialize(adapter, root, adapter.commit_sha(root))
    paths = {f["path"] for f in result.files}
    assert ".env" not in paths and "secret.key" not in paths
    reasons = {e["path"]: e["reason"] for e in result.excluded}
    assert reasons.get(".env") == "sensitive" and reasons.get("secret.key") == "sensitive"


def test_symlink_and_gitlink_excluded(tmp_path) -> None:
    repo = make_repo(tmp_path)
    blob = git(repo, "rev-parse", "HEAD:a.txt").stdout.strip()
    commit = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", "120000", blob, "link")
    git(repo, "update-index", "--add", "--cacheinfo", "160000", commit, "sub")
    git(repo, "commit", "-m", "special")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    result = snapshot.materialize(adapter, root, adapter.commit_sha(root))
    reasons = {e["path"]: e["reason"] for e in result.excluded}
    assert reasons.get("link") == "symlink"
    assert reasons.get("sub") == "gitlink"


def test_export_ignore_excluded(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".gitattributes").write_text("ignored.txt export-ignore\n", encoding="utf-8", newline="\n")
    (repo / "ignored.txt").write_text("x\n", encoding="utf-8", newline="\n")
    _commit(repo, ".gitattributes", "ignored.txt")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    result = snapshot.materialize(adapter, root, adapter.commit_sha(root))
    assert "ignored.txt" not in {f["path"] for f in result.files}
    assert any(e["path"] == "ignored.txt" and e["reason"] == "export-ignore" for e in result.excluded)


def test_export_subst_tolerated(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".gitattributes").write_text("subst.txt export-subst\n", encoding="utf-8", newline="\n")
    (repo / "subst.txt").write_text("hash=$Format:%H$\n", encoding="utf-8", newline="\n")
    _commit(repo, ".gitattributes", "subst.txt")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    result = snapshot.materialize(adapter, root, adapter.commit_sha(root))
    assert result.available is True
    assert "subst.txt" in {f["path"] for f in result.files}


def test_lfs_pointer_flagged(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / "lfs.bin").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 3\n",
        encoding="utf-8",
        newline="\n",
    )
    _commit(repo, "lfs.bin")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    result = snapshot.materialize(adapter, root, adapter.commit_sha(root))
    assert "lfs.bin" in result.lfs_pointers
    assert "lfs.bin" not in {f["path"] for f in result.files}
    assert any(
        e["path"] == "lfs.bin" and e["reason"] == "lfs_pointer" for e in result.excluded
    )


def test_materialized_archive_tamper_detected(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / "b.txt").write_text("b\n", encoding="utf-8", newline="\n")
    _commit(repo, "b.txt")
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    dest = tmp_path / "archive"
    result = snapshot.materialize(
        adapter, root, adapter.commit_sha(root), dest_dir=str(dest)
    )
    assert result.available is True
    check = snapshot.verify_materialized(str(dest), result.files)
    assert check == {"ok": True, "missing": [], "mismatched": [], "extra": []}

    (dest / "a.txt").write_text("tampered\n", encoding="utf-8")
    (dest / "extra.txt").write_text("extra\n", encoding="utf-8")
    (dest / "b.txt").unlink()
    tampered = snapshot.verify_materialized(str(dest), result.files)
    assert tampered["ok"] is False
    assert "a.txt" in tampered["mismatched"]
    assert "b.txt" in tampered["missing"]
    assert "extra.txt" in tampered["extra"]


def test_attribute_source_unavailable_fails_closed(tmp_path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    adapter = _adapter(tmp_path)
    root = adapter.repo_root(str(repo))
    monkeypatch.setattr(adapter, "supports_check_attr_source", lambda *_: False)
    result = snapshot.materialize(adapter, root, adapter.commit_sha(root))
    assert result.available is False
    assert result.reason == "attribute_verification_unavailable"
    assert result.files == []


def test_symlink_escape_detection() -> None:
    assert snapshot._symlink_escapes("../../etc/passwd")
    assert snapshot._symlink_escapes("/etc/passwd")
    assert not snapshot._symlink_escapes("sub/file.txt")