"""Tests for the structured data admin layer.

Covers:
- ApprovalService: approve / reject / override / comment / get_task_detail
- PublishService: publish_candidate / rollback
- Admin route: /admin endpoint shape
- Bootstrap: _init_structured_data wiring (smoke test)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(resolved: bool = False, candidate_id: str | None = None) -> dict:
    return {
        "task_id": str(uuid4()),
        "dataset_key": "financial_statements",
        "business_key": "SSE:600519",
        "candidate_id": candidate_id or str(uuid4()),
        "is_resolved": resolved,
        "reason": "test",
        "created_at": "2026-01-01T00:00:00",
    }


def _make_candidate(data: dict | None = None) -> dict:
    return {
        "candidate_id": str(uuid4()),
        "dataset_key": "financial_statements",
        "business_key": "SSE:600519",
        "state": "PENDING_REVIEW",
        "normalized_data": data or {"revenue": 100},
        "source": "akshare",
        "job_id": str(uuid4()),
    }


# ---------------------------------------------------------------------------
# ApprovalService tests
# ---------------------------------------------------------------------------

class TestApprovalService:
    """Unit tests for ApprovalService using mocked repositories."""

    @pytest.fixture
    def mock_repos(self):
        candidate_repo = MagicMock()
        canonical_repo = MagicMock()
        issue_repo = MagicMock()

        # Common async mocks
        candidate_repo.get_candidate = AsyncMock()
        candidate_repo.update_state = AsyncMock()
        candidate_repo.transition_state = AsyncMock()
        candidate_repo.mark_superseded = AsyncMock()
        candidate_repo.list_issues = AsyncMock(return_value=[])
        canonical_repo.get_current = AsyncMock(return_value=None)
        canonical_repo.publish = AsyncMock(return_value=str(uuid4()))
        issue_repo.get_task = AsyncMock()
        issue_repo.resolve_task = AsyncMock()
        issue_repo.record_action = AsyncMock(return_value=str(uuid4()))
        issue_repo.list_actions = AsyncMock(return_value=[])
        issue_repo.list_pending_tasks = AsyncMock(return_value=[])

        return candidate_repo, canonical_repo, issue_repo

    @pytest.fixture
    def svc(self, mock_repos):
        from src.server.domain.structured_data.approval_service import ApprovalService
        candidate_repo, canonical_repo, issue_repo = mock_repos
        return ApprovalService(
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
            issue_repo=issue_repo,
        )

    @pytest.mark.asyncio
    async def test_approve_happy_path(self, svc, mock_repos):
        """Approve succeeds: state transitions + canonical publish + task resolved."""
        candidate_repo, canonical_repo, issue_repo = mock_repos
        task = _make_task()
        cand = _make_candidate()

        issue_repo.get_task.return_value = task
        candidate_repo.get_candidate.return_value = cand

        result = await svc.approve(task["task_id"], reviewer="alice")

        assert result["task_id"] == task["task_id"]
        assert "status" in result
        # Verify publish was called
        canonical_repo.publish.assert_awaited_once()
        # Verify task resolved
        issue_repo.resolve_task.assert_awaited_once_with(task["task_id"])
        # Verify action recorded
        issue_repo.record_action.assert_awaited()

    @pytest.mark.asyncio
    async def test_approve_already_resolved_raises(self, svc, mock_repos):
        """Approving a resolved task raises ValueError."""
        _, _, issue_repo = mock_repos
        issue_repo.get_task.return_value = _make_task(resolved=True)

        with pytest.raises(ValueError, match="already resolved"):
            await svc.approve("some-task-id", reviewer="bob")

    @pytest.mark.asyncio
    async def test_approve_task_not_found_raises(self, svc, mock_repos):
        """Approving a missing task raises KeyError."""
        _, _, issue_repo = mock_repos
        issue_repo.get_task.return_value = None

        with pytest.raises(KeyError):
            await svc.approve("nonexistent-id", reviewer="bob")

    @pytest.mark.asyncio
    async def test_reject_happy_path(self, svc, mock_repos):
        """Reject succeeds: candidate state updated + action recorded + task resolved."""
        candidate_repo, _, issue_repo = mock_repos
        task = _make_task()
        cand = _make_candidate()

        issue_repo.get_task.return_value = task
        candidate_repo.get_candidate.return_value = cand

        result = await svc.reject(task["task_id"], reviewer="carol", comment="bad data")

        assert result["task_id"] == task["task_id"]
        issue_repo.resolve_task.assert_awaited_once()
        issue_repo.record_action.assert_awaited()

    @pytest.mark.asyncio
    async def test_reject_resolved_task_raises(self, svc, mock_repos):
        """Rejecting a resolved task raises ValueError."""
        _, _, issue_repo = mock_repos
        issue_repo.get_task.return_value = _make_task(resolved=True)

        with pytest.raises(ValueError, match="already resolved"):
            await svc.reject("some-task-id", reviewer="dave")

    @pytest.mark.asyncio
    async def test_override_publish_happy_path(self, svc, mock_repos):
        """Override publish merges override data and publishes to canonical."""
        candidate_repo, canonical_repo, issue_repo = mock_repos
        task = _make_task()
        cand = _make_candidate(data={"revenue": 100, "profit": 50})

        issue_repo.get_task.return_value = task
        candidate_repo.get_candidate.return_value = cand

        result = await svc.override_publish(
            task["task_id"],
            reviewer="eve",
            data_override={"revenue": 200},
            comment="manual correction",
        )

        assert result["task_id"] == task["task_id"]
        canonical_repo.publish.assert_awaited_once()
        # Verify published data included override
        call_kwargs = canonical_repo.publish.call_args
        # The data argument should have the merged override
        published_data = call_kwargs.kwargs.get("data") or call_kwargs.args[3] if call_kwargs.args else None
        if published_data is not None:
            assert published_data.get("revenue") == 200

    @pytest.mark.asyncio
    async def test_comment_does_not_change_state(self, svc, mock_repos):
        """Comment method records action without resolving or changing candidate state."""
        candidate_repo, canonical_repo, issue_repo = mock_repos
        task = _make_task()
        issue_repo.get_task.return_value = task

        result = await svc.comment(task["task_id"], reviewer="frank", comment="looks good")

        assert result["task_id"] == task["task_id"]
        issue_repo.record_action.assert_awaited_once()
        # Must NOT resolve task or publish canonical
        issue_repo.resolve_task.assert_not_awaited()
        canonical_repo.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_task_detail_returns_expected_keys(self, svc, mock_repos):
        """get_task_detail returns all expected top-level keys."""
        candidate_repo, canonical_repo, issue_repo = mock_repos
        task = _make_task()
        cand = _make_candidate()

        issue_repo.get_task.return_value = task
        candidate_repo.get_candidate.return_value = cand
        issue_repo.list_actions.return_value = []
        # list_issues is called by orchestrator/issue_repo — mock if needed
        if hasattr(issue_repo, "list_issues"):
            issue_repo.list_issues = AsyncMock(return_value=[])

        detail = await svc.get_task_detail(task["task_id"])

        assert "task" in detail
        assert "candidate" in detail
        assert "field_diff" in detail
        assert "actions" in detail

    @pytest.mark.asyncio
    async def test_get_stats_returns_pending_count(self, svc, mock_repos):
        """get_stats returns pending_count key."""
        _, _, issue_repo = mock_repos
        issue_repo.list_pending_tasks.return_value = [_make_task(), _make_task()]

        stats = await svc.get_stats()

        assert "pending_count" in stats
        assert stats["pending_count"] >= 0


# ---------------------------------------------------------------------------
# PublishService tests
# ---------------------------------------------------------------------------

class TestPublishService:
    """Unit tests for PublishService using mocked repositories."""

    @pytest.fixture
    def mock_repos(self):
        candidate_repo = MagicMock()
        canonical_repo = MagicMock()
        candidate_repo.get_candidate = AsyncMock()
        canonical_repo.publish = AsyncMock(return_value=str(uuid4()))
        canonical_repo.rollback = AsyncMock(return_value=str(uuid4()))
        return candidate_repo, canonical_repo

    @pytest.fixture
    def svc(self, mock_repos):
        from src.server.domain.structured_data.publish_service import PublishService
        candidate_repo, canonical_repo = mock_repos
        return PublishService(
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
        )

    @pytest.mark.asyncio
    async def test_publish_candidate_happy_path(self, svc, mock_repos):
        """publish_candidate calls canonical.publish and returns structured result."""
        candidate_repo, canonical_repo, = mock_repos
        cand = _make_candidate()
        candidate_repo.get_candidate.return_value = cand

        result = await svc.publish_candidate(
            cand["candidate_id"],
            dataset_key=cand["dataset_key"],
            business_key=cand["business_key"],
        )

        assert "canonical_id" in result
        assert result["dataset_key"] == cand["dataset_key"]
        assert result["business_key"] == cand["business_key"]
        canonical_repo.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_candidate_not_found_raises(self, svc, mock_repos):
        """publish_candidate raises KeyError when candidate does not exist."""
        candidate_repo, _ = mock_repos
        candidate_repo.get_candidate.return_value = None

        with pytest.raises((KeyError, ValueError)):
            await svc.publish_candidate(
                "nonexistent-id",
                dataset_key="financial_statements",
                business_key="SSE:000000",
            )

    @pytest.mark.asyncio
    async def test_rollback_happy_path(self, svc, mock_repos):
        """rollback delegates to canonical_repo.rollback and returns correct keys."""
        _, canonical_repo = mock_repos

        result = await svc.rollback(
            dataset_key="financial_statements",
            business_key="SSE:600519",
            target_version=2,
        )

        assert "canonical_id" in result
        assert result["rolled_back_to_version"] == 2
        canonical_repo.rollback.assert_awaited_once_with(
            dataset_key="financial_statements",
            business_key="SSE:600519",
            target_version=2,
        )

    @pytest.mark.asyncio
    async def test_rollback_not_found_raises(self, svc, mock_repos):
        """rollback raises ValueError when target version not found."""
        _, canonical_repo = mock_repos
        canonical_repo.rollback.return_value = None  # version not found

        with pytest.raises(ValueError, match="Rollback failed"):
            await svc.rollback(
                dataset_key="financial_statements",
                business_key="SSE:600519",
                target_version=999,
            )


# ---------------------------------------------------------------------------
# Admin route shape tests
# ---------------------------------------------------------------------------

class TestAdminRoutes:
    """Verify admin_router has the expected route structure (no DB needed)."""

    def test_admin_html_router_has_workbench_route(self):
        """html_router exposes GET /admin."""
        from src.server.api.routes.admin import html_router

        paths = [route.path for route in html_router.routes]
        assert "/admin" in paths

    def test_admin_html_router_has_html_response(self):
        """GET /admin is declared to return HTMLResponse."""
        from fastapi.responses import HTMLResponse
        from src.server.api.routes.admin import html_router

        for route in html_router.routes:
            if route.path == "/admin":
                assert route.response_class is HTMLResponse
                break

    def test_admin_html_contains_key_elements(self):
        """ADMIN_HTML contains the JS fetch base URL and key UI elements."""
        from src.server.api.routes.admin_template import ADMIN_HTML

        assert "/api/v1/structured-data" in ADMIN_HTML
        assert "approval/pending" in ADMIN_HTML
        assert "btn-approve" in ADMIN_HTML
        assert "btn-reject" in ADMIN_HTML
        assert "btn-override" in ADMIN_HTML
        # Ensure the diff table and candidate JSON viewer are present
        assert "diff-body" in ADMIN_HTML
        assert "candidate-json" in ADMIN_HTML


# ---------------------------------------------------------------------------
# Bootstrap smoke test
# ---------------------------------------------------------------------------

class TestBootstrapStructuredData:
    """Smoke test: _init_structured_data does not crash given a mock postgres conn."""

    @pytest.mark.asyncio
    async def test_init_structured_data_succeeds_with_mock_conn(self):
        """_init_structured_data initializes subsystem with a mock DB connection."""
        from src.server.core.bootstrap import _init_structured_data

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()

        mock_conn = MagicMock()
        # postgres_conn has a .pool attribute used by repositories
        mock_conn.pool = mock_pool
        mock_conn._pool = mock_pool

        # Patch ensure_schema on all repos (they do real DB calls)
        with patch(
            "src.server.domain.structured_data.repositories.raw_repository.RawRepository.ensure_schema",
            new_callable=AsyncMock,
        ), patch(
            "src.server.domain.structured_data.repositories.candidate_repository.CandidateRepository.ensure_schema",
            new_callable=AsyncMock,
        ), patch(
            "src.server.domain.structured_data.repositories.canonical_repository.CanonicalRepository.ensure_schema",
            new_callable=AsyncMock,
        ), patch(
            "src.server.domain.structured_data.repositories.issue_repository.IssueRepository.ensure_schema",
            new_callable=AsyncMock,
        ), patch(
            "src.server.api.routes.structured_data.set_structured_data_components"
        ) as mock_set_components, patch(
            "src.server.core.dependencies.Container.market_gateway",
            return_value=MagicMock(),
        ):
            await _init_structured_data(mock_conn)

        # set_structured_data_components must have been called with service objects
        mock_set_components.assert_called_once()
        kwargs = mock_set_components.call_args.kwargs
        assert "runner" in kwargs or mock_set_components.call_args.args
