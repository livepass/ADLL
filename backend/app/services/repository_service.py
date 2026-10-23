"""仓库关联与分析基准服务（T012/T013）。"""
from __future__ import annotations

from ..adapters.git import GitAdapter, GitError
from ..models.repository import AnalysisBaseline, GitRepository

ALLOWED_DECISIONS = {"clean", "accept_uncommitted"}


def _deactivate_others(db) -> None:
    db.query(GitRepository).filter_by(active=True).update({"active": False})


def create_baseline(
    db, git: GitAdapter, repo: GitRepository, commit_sha: str, decision: str
) -> AnalysisBaseline:
    report = git.verify_snapshot(repo.path, commit_sha)
    baseline = AnalysisBaseline(
        repository_id=repo.id,
        commit_sha=commit_sha,
        object_format=repo.object_format,
        workspace_decision=decision,
        snapshot_digest=report.digest,
        available=report.available,
        unavailable_reason=report.reason,
        inventory_summary=report.summary,
    )
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    return baseline


def link(db, git: GitAdapter, path: str):
    """关联仓库。脏工作区→需用户决策（不建基准）；干净→自动建基准。"""
    root = git.repo_root(path)
    identity = git.repo_identity(root)
    objfmt = git.object_format(root)
    branch = git.branch(root)
    commit = git.commit_sha(root)
    status = git.workspace_status(root)

    _deactivate_others(db)
    repo = GitRepository(
        path=root,
        repo_identity=identity,
        object_format=objfmt,
        branch=branch,
        active=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    needs_decision = not status["clean"]
    baseline = None
    if not needs_decision:
        baseline = create_baseline(db, git, repo, commit, "clean")
    return repo, baseline, status, needs_decision


def apply_decision(db, git: GitAdapter, repo: GitRepository, decision: str) -> AnalysisBaseline:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"invalid decision: {decision}")
    commit = git.commit_sha(repo.path)
    return create_baseline(db, git, repo, commit, decision)


def latest_baseline(db, repo: GitRepository) -> AnalysisBaseline | None:
    return (
        db.query(AnalysisBaseline)
        .filter_by(repository_id=repo.id)
        .order_by(AnalysisBaseline.id.desc())
        .first()
    )