from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backend.adapters.mock_scm import MockScm
from backend.db import build_engine, build_session_factory, session_scope
from backend.models import Base, Task
from backend.repositories.task_repository import TaskCreateParams, TaskRepository
from backend.schemas import ScmWorkspace, ScmWorkspaceEnsurePayload
from backend.settings import get_settings
from backend.task_constants import TaskType
from backend.workers.execute_worker import ExecuteWorker
from test_execute_worker import EnsureWorkspaceRecorderMockScm, RecordingAgentRunner


def _build_session_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _build_settings(tmp_path):
    return replace(get_settings(), workspace_root=str(tmp_path / "workspaces"))


def test_prepare_triage_execution_with_repo_uses_ensure_workspace(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = EnsureWorkspaceRecorderMockScm()
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-1",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-1",
                context={"title": "Tracker task"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-1",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-1",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_task_id = triage_task.id
        chain = repository.load_task_chain(fetch_task.id)
        triage_in_chain = next(t for t in chain if t.id == triage_task_id)
        prepared = worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )

    assert prepared.workspace is not None
    assert prepared.workspace.workspace_key == "repo-1"
    assert prepared.workspace_path == prepared.workspace.local_path
    assert prepared.cleanup_paths == ()
    assert len(scm.ensure_workspace_payloads) == 1
    assert prepared.runtime_metadata["action"] == "triage"
    assert prepared.runtime_metadata["repo_available"] is True
    assert prepared.runtime_metadata["workspace_key"] == "repo-1"
    assert prepared.runtime_metadata["repo_url"] == "https://example.test/repo.git"
    assert prepared.runtime_metadata["repo_ref"] == "main"
    assert prepared.runtime_metadata["branch_name"] is None


def test_prepare_triage_execution_without_repo_creates_tmp_dir(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = EnsureWorkspaceRecorderMockScm()
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-NOREPO",
                context={"title": "Tracker task without repo"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-NOREPO",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_task_id = triage_task.id
        chain = repository.load_task_chain(fetch_task.id)
        triage_in_chain = next(t for t in chain if t.id == triage_task_id)
        prepared = worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )

    expected_path = Path(settings.workspace_root) / "__triage__" / f"task-{triage_task_id}"
    assert prepared.workspace is None
    assert prepared.workspace_path == str(expected_path)
    assert Path(prepared.workspace_path).is_dir()
    assert prepared.cleanup_paths == (Path(prepared.workspace_path),)
    assert scm.ensure_workspace_payloads == []
    assert prepared.runtime_metadata["repo_available"] is False
    assert prepared.runtime_metadata["workspace_key"] is None
    assert prepared.runtime_metadata["repo_url"] is None
    assert prepared.runtime_metadata["repo_ref"] is None
    assert prepared.runtime_metadata["branch_name"] is None
    assert prepared.runtime_metadata["action"] == "triage"


def test_prepare_triage_execution_tmp_dir_idempotent(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=EnsureWorkspaceRecorderMockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-IDEM",
                context={"title": "Tracker task without repo"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-IDEM",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_task_id = triage_task.id
        chain = repository.load_task_chain(fetch_task.id)
        triage_in_chain = next(t for t in chain if t.id == triage_task_id)
        first = worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )
        second = worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )

    assert first.workspace_path == second.workspace_path
    assert Path(first.workspace_path).is_dir()
    assert first.cleanup_paths == second.cleanup_paths


def test_prepare_triage_execution_passes_brief_resolver(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=EnsureWorkspaceRecorderMockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-BRIEF",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-brief",
                context={"title": "Tracker task"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-BRIEF",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-brief",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
                result_payload={
                    "summary": "Triage done",
                    "metadata": {"handover_brief": "BRIEF-XYZ"},
                },
            )
        )
        impl_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-BRIEF",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-brief",
                context={"title": "Implementation execute"},
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage_task.id,
                        "from_role": "triage",
                        "brief_markdown": None,
                    },
                },
            )
        )
        impl_task_id = impl_task.id
        chain = repository.load_task_chain(fetch_task.id)
        impl_in_chain = next(t for t in chain if t.id == impl_task_id)
        prepared = worker._prepare_triage_execution(
            repository=repository, task=impl_in_chain, task_chain=chain
        )

    assert prepared.task_context.handover_brief == "BRIEF-XYZ"


def test_prepare_triage_execution_persists_workspace_context_for_real_repo(tmp_path) -> None:
    session_factory = _build_session_factory(tmp_path)
    scm = EnsureWorkspaceRecorderMockScm()
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-PERSIST",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-persist",
                context={"title": "Tracker task"},
            )
        )
        # Create triage task with empty repo_url / repo_ref — those should be
        # resolved by ContextBuilder via lineage (from fetch_task) and persisted
        # back onto the triage row through update_task_workspace_context.
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-PERSIST",
                repo_url=None,
                repo_ref=None,
                workspace_key="repo-persist",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_task_id = triage_task.id
        chain = repository.load_task_chain(fetch_task.id)
        triage_in_chain = next(t for t in chain if t.id == triage_task_id)
        worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )

    with session_scope(session_factory=session_factory) as session:
        refreshed = session.get(Task, triage_task_id)
        assert refreshed is not None
        # repo_url / repo_ref were initially None on the triage row; they got
        # resolved from the fetch ancestor and persisted back via
        # update_task_workspace_context.
        assert refreshed.repo_url == "https://example.test/repo.git"
        assert refreshed.repo_ref == "main"
        assert refreshed.workspace_key == "repo-persist"


def test_prepare_triage_execution_does_not_persist_workspace_context_when_no_repo(
    tmp_path,
) -> None:
    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=EnsureWorkspaceRecorderMockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-NO-PERSIST",
                context={"title": "Tracker task without repo"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-NO-PERSIST",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_task_id = triage_task.id
        chain = repository.load_task_chain(fetch_task.id)
        triage_in_chain = next(t for t in chain if t.id == triage_task_id)
        worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )

    with session_scope(session_factory=session_factory) as session:
        refreshed = session.get(Task, triage_task_id)
        assert refreshed is not None
        assert refreshed.repo_url is None
        assert refreshed.repo_ref is None
        assert refreshed.workspace_key is None


def test_prepare_execution_still_uses_extracted_brief_resolver(tmp_path) -> None:
    """Regression: refactoring `_prepare_execution` to share `_build_brief_resolver`
    must not break the impl-flow handover_brief lookup."""

    session_factory = _build_session_factory(tmp_path)
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=EnsureWorkspaceRecorderMockScm(),
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-IMPL-BRIEF",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-impl-brief",
                context={"title": "Tracker task"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-IMPL-BRIEF",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-impl-brief",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
                result_payload={
                    "summary": "Triage done",
                    "metadata": {"handover_brief": "BRIEF-A"},
                },
            )
        )
        impl_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-IMPL-BRIEF",
                repo_url="https://example.test/repo.git",
                repo_ref="main",
                workspace_key="repo-impl-brief",
                context={"title": "Implementation execute"},
                input_payload={
                    "action": "implementation",
                    "handoff": {
                        "from_task_id": triage_task.id,
                        "from_role": "triage",
                        "brief_markdown": None,
                    },
                    "instructions": "Implement the brief.",
                    "base_branch": "main",
                    "branch_name": "task-impl-brief/run",
                },
            )
        )
        impl_task_id = impl_task.id
        chain = repository.load_task_chain(fetch_task.id)
        impl_in_chain = next(t for t in chain if t.id == impl_task_id)
        prepared = worker._prepare_execution(
            repository=repository, task=impl_in_chain, task_chain=chain
        )

    assert prepared.task_context.handover_brief == "BRIEF-A"


class _ResolvingMockScm(MockScm):
    """SCM stub имитирующий backend, у которого ``ensure_workspace`` доразрешает
    ``repo_url`` / ``repo_ref`` через ``default_repo_url`` / ``default_repo_ref``
    (как, например, GitHubScm).

    Принимает payload с ``repo_url=None``. Возвращает workspace с
    предустановленными ``resolved_repo_url`` / ``resolved_repo_ref`` и
    канонным ``local_path`` под workspace_key.
    """

    def __init__(
        self,
        *,
        resolved_repo_url: str = "https://example.test/repo.git",
        resolved_repo_ref: str = "main",
    ) -> None:
        super().__init__()
        self._resolved_repo_url = resolved_repo_url
        self._resolved_repo_ref = resolved_repo_ref
        self.ensure_workspace_payloads: list[ScmWorkspaceEnsurePayload] = []

    def ensure_workspace(self, payload: ScmWorkspaceEnsurePayload) -> ScmWorkspace:
        self.ensure_workspace_payloads.append(payload.model_copy(deep=True))
        repo_url = payload.repo_url or self._resolved_repo_url
        repo_ref = payload.repo_ref or self._resolved_repo_ref
        local_path = f"/tmp/mock-scm/{payload.workspace_key}"
        return ScmWorkspace(
            repo_url=repo_url,
            workspace_key=payload.workspace_key,
            repo_ref=repo_ref,
            local_path=local_path,
            metadata=payload.metadata,
        )


def test_prepare_triage_execution_treats_workspace_key_alone_as_real_repo(tmp_path) -> None:
    """Regression for Codex P2 #1: пустой ``repo_url`` сам по себе не должен
    уводить триаж в tmp-каталог. Если ``workspace_key`` есть — backend (SCM)
    может дорезолвить URL через ``default_repo_url``."""

    session_factory = _build_session_factory(tmp_path)
    scm = _ResolvingMockScm()
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-K",
                repo_url=None,
                repo_ref=None,
                workspace_key="repo-K",
                context={"title": "Tracker task without explicit repo_url"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-K",
                repo_url=None,
                repo_ref=None,
                workspace_key="repo-K",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_task_id = triage_task.id
        chain = repository.load_task_chain(fetch_task.id)
        triage_in_chain = next(t for t in chain if t.id == triage_task_id)
        prepared = worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )

    assert prepared.workspace is not None
    assert prepared.workspace.workspace_key == "repo-K"
    assert prepared.workspace_path == prepared.workspace.local_path
    assert prepared.cleanup_paths == ()
    # Реально пошли по SCM-пути, а не в tmp-fallback.
    assert len(scm.ensure_workspace_payloads) == 1
    assert prepared.runtime_metadata["repo_available"] is True


def test_prepare_triage_execution_refreshes_task_context_after_scm_resolve(tmp_path) -> None:
    """Regression for Codex P2 #2: после ``_ensure_workspace`` SCM мог
    дорезолвить ``repo_url`` / ``repo_ref``; возвращаемый ``task_context``
    обязан отражать эти канонные значения, иначе ``TriageStep.build_prompt``
    видит ``repo_available: false`` несмотря на готовый чекаут."""

    session_factory = _build_session_factory(tmp_path)
    scm = _ResolvingMockScm(
        resolved_repo_url="https://example.test/repo.git",
        resolved_repo_ref="main",
    )
    settings = _build_settings(tmp_path)
    worker = ExecuteWorker(
        scm=scm,
        agent_runner=RecordingAgentRunner(),
        session_factory=session_factory,
        settings=settings,
    )

    with session_scope(session_factory=session_factory) as session:
        repository = TaskRepository(session)
        fetch_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.FETCH,
                tracker_name="mock",
                external_task_id="TASK-R",
                repo_url=None,
                repo_ref=None,
                workspace_key="repo-R",
                context={"title": "Tracker task without repo_url/repo_ref"},
            )
        )
        triage_task = repository.create_task(
            TaskCreateParams(
                task_type=TaskType.EXECUTE,
                parent_id=fetch_task.id,
                tracker_name="mock",
                external_parent_id="TASK-R",
                repo_url=None,
                repo_ref=None,
                workspace_key="repo-R",
                context={"title": "Triage execute"},
                input_payload={"action": "triage"},
            )
        )
        triage_task_id = triage_task.id
        chain = repository.load_task_chain(fetch_task.id)
        triage_in_chain = next(t for t in chain if t.id == triage_task_id)
        prepared = worker._prepare_triage_execution(
            repository=repository, task=triage_in_chain, task_chain=chain
        )

    assert prepared.task_context.repo_url == "https://example.test/repo.git"
    assert prepared.task_context.repo_ref == "main"
    assert prepared.task_context.workspace_key == "repo-R"
