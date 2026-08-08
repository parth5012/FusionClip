"""T-01 refactor-equivalence tests derived from an INDEPENDENT baseline.

``test_routers_smoke.py`` pins the legacy contract against a hand-typed
``LEGACY_HTTP_ROUTES`` constant. That constant is only as good as the memory of
whoever typed it: a route dropped in the refactor *and* omitted from the list
passes silently.

The tests here close that hole two ways:

1. ``TestContractAgainstGitBaseline`` reconstructs the pre-refactor contract by
   AST-parsing the last committed revision of ``backend/app/main.py`` that still
   contained the ``celery_app_instance`` circular-import shim. Nothing is
   trusted except git history. Skipped when git or that revision is unavailable.
2. ``TestGoldenContract`` hardcodes the same contract — paths, HTTP methods,
   query-parameter *names* and query-parameter *defaults* — transcribed from
   that revision, so the coverage survives in environments without git.

Query-parameter defaults matter as much as names: the Playwright suite calls
``/api/generate/image`` with no ``steps`` and relies on 28, and
``/api/tasks/process`` with no ``task_type`` and relies on ``transcode``.
"""

import ast
import subprocess
from pathlib import Path

import pytest

from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# Golden contract, transcribed from the pre-refactor main.py.
# (method, path) -> {param_name: default}; `...` marks a required parameter.
# Body/path/file parameters are excluded — only query parameters appear here.
# --------------------------------------------------------------------------
GOLDEN_CONTRACT = {
    ("GET", "/"): {},
    ("POST", "/api/storage/upload"): {"folder": ""},
    ("GET", "/api/storage/list"): {"prefix": ""},
    ("DELETE", "/api/storage/delete"): {"path": ...},
    ("POST", "/api/storage/create-folder"): {"folder_path": ...},
    ("POST", "/api/tasks/process"): {"path": ..., "task_type": "transcode"},
    ("GET", "/api/tasks/status/{task_id}"): {"task_id": ...},
    ("GET", "/api/settings"): {},
    ("POST", "/api/settings"): {},
    ("POST", "/api/colab/tunnel"): {"url": ..., "status": "running"},
    ("POST", "/api/generate/text"): {"prompt": ...},
    ("POST", "/api/generate/audio"): {"prompt": ..., "type": "tts"},
    ("POST", "/api/generate/image"): {"prompt": ..., "steps": 28, "scale": 7.5},
    ("GET", "/api/media"): {},
    ("GET", "/api/media/search"): {"query": ..., "limit": 10},
}

LEGACY_WEBSOCKETS = {"/api/ws/tasks"}


def _openapi_contract():
    """(method, path) -> {param: default} for the live app, from its OpenAPI schema."""
    spec = app.openapi()
    contract = {}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            params = {}
            for param in operation.get("parameters", []):
                schema = param.get("schema", {})
                params[param["name"]] = (
                    schema["default"] if "default" in schema else ...
                )
            contract[(method.upper(), path)] = params
    return contract


# --------------------------------------------------------------------------
# 1. Baseline reconstructed from git history
# --------------------------------------------------------------------------


def _pre_refactor_main_source():
    """Fetch the newest committed main.py still containing the pre-refactor shim."""
    try:
        revisions = subprocess.run(
            ["git", "log", "--format=%H", "--", "backend/app/main.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if revisions.returncode != 0:
        return None

    for sha in revisions.stdout.split():
        blob = subprocess.run(
            ["git", "show", f"{sha}:backend/app/main.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if blob.returncode == 0 and "def celery_app_instance" in blob.stdout:
            return blob.stdout
    return None


def _routes_from_source(source):
    """AST-extract (method, path) -> {query_param: default} from decorated handlers.

    Only ``Query(...)``-defaulted arguments are treated as query parameters,
    mirroring how FastAPI itself classifies them.
    """
    tree = ast.parse(source)
    contract = {}
    websockets = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.args
            ):
                continue
            verb = decorator.func.attr
            path = getattr(decorator.args[0], "value", None)
            if not isinstance(path, str):
                continue

            if verb == "websocket":
                websockets.add(path)
                continue
            if verb not in ("get", "post", "put", "patch", "delete"):
                continue

            params = {}
            args = node.args.args
            defaults = node.args.defaults
            # Line up defaults with the trailing positional arguments.
            for arg, default in zip(args[len(args) - len(defaults):], defaults):
                if not (
                    isinstance(default, ast.Call)
                    and getattr(default.func, "id", None) == "Query"
                ):
                    continue
                if default.args and isinstance(default.args[0], ast.Constant):
                    params[arg.arg] = default.args[0].value
                else:
                    # Query(...) — Ellipsis literal means required.
                    params[arg.arg] = ...
            # Path parameters are declared in the URL template itself.
            for arg in args:
                if "{" + arg.arg + "}" in path:
                    params[arg.arg] = ...
            contract[(verb.upper(), path)] = params

    return contract, websockets


@pytest.fixture(scope="module")
def baseline():
    """(routes, websockets) parsed from the pre-refactor main.py in git."""
    source = _pre_refactor_main_source()
    if source is None:
        pytest.skip("pre-refactor main.py revision not reachable via git")
    return _routes_from_source(source)


class TestContractAgainstGitBaseline:
    """Compare the live app to the contract reconstructed from git history."""

    def test_baseline_is_non_trivial(self, baseline):
        """Guard the oracle itself: a broken parse must not silently pass."""
        routes, websockets = baseline
        assert len(routes) >= 15, f"baseline parse looks wrong: {routes}"
        assert websockets == LEGACY_WEBSOCKETS

    def test_no_legacy_route_was_dropped(self, baseline):
        routes, _ = baseline
        live = _openapi_contract()
        missing = sorted(set(routes) - set(live))
        assert not missing, f"routes lost in the T-01 refactor: {missing}"

    def test_no_legacy_query_parameter_was_renamed(self, baseline):
        routes, _ = baseline
        live = _openapi_contract()
        renamed = {}
        for key, params in routes.items():
            if key not in live:
                continue
            lost = set(params) - set(live[key])
            if lost:
                renamed[key] = sorted(lost)
        assert not renamed, f"query parameters renamed or dropped: {renamed}"

    def test_no_legacy_query_default_changed(self, baseline):
        routes, _ = baseline
        live = _openapi_contract()
        changed = {}
        for key, params in routes.items():
            if key not in live:
                continue
            for name, default in params.items():
                if name not in live[key]:
                    continue
                if live[key][name] != default:
                    changed[f"{key[0]} {key[1]}?{name}"] = {
                        "was": default,
                        "now": live[key][name],
                    }
        assert not changed, f"query-parameter defaults changed: {changed}"

    def test_git_baseline_matches_the_golden_constant(self, baseline):
        """Cross-check the two oracles against each other."""
        routes, _ = baseline
        assert set(routes) == set(GOLDEN_CONTRACT)
        for key, params in routes.items():
            assert params == GOLDEN_CONTRACT[key], f"golden constant stale for {key}"


# --------------------------------------------------------------------------
# 2. Golden contract (works without git)
# --------------------------------------------------------------------------


class TestGoldenContract:
    @pytest.mark.parametrize("method,path", sorted(GOLDEN_CONTRACT))
    def test_route_still_exists(self, method, path):
        assert (method, path) in _openapi_contract(), f"{method} {path} was lost"

    @pytest.mark.parametrize("method,path", sorted(GOLDEN_CONTRACT))
    def test_query_parameters_unchanged(self, method, path):
        live = _openapi_contract()[(method, path)]
        for name, default in GOLDEN_CONTRACT[(method, path)].items():
            assert name in live, f"{method} {path}: parameter '{name}' disappeared"
            assert live[name] == default, (
                f"{method} {path}: default for '{name}' changed "
                f"from {default!r} to {live[name]!r}"
            )

    def test_websocket_route_preserved(self):
        from fastapi.routing import APIWebSocketRoute

        from tests.test_routers_smoke import _walk_routes

        live = {
            route.path
            for route in _walk_routes(app.routes)
            if isinstance(route, APIWebSocketRoute)
        }
        assert LEGACY_WEBSOCKETS <= live


# --------------------------------------------------------------------------
# 3. Response-shape equivalence for defaulted calls
# --------------------------------------------------------------------------


class TestDefaultedCallShapes:
    """The smoke suite exercises explicit parameters; these use the defaults.

    A default silently changing type (e.g. steps 28 -> "28") would not be caught
    by a path-presence check but breaks e2e/05's `parameters.steps` assertion.
    """

    def test_generate_audio_default_type_is_tts(self, client, stub_storage):
        body = client.post("/api/generate/audio?prompt=defaults").json()
        assert body["type"] == "tts"
        assert set(body) == {"status", "type", "filename", "url"}

    def test_generate_image_default_parameter_types(self, client, stub_storage):
        params = client.post("/api/generate/image?prompt=defaults").json()["parameters"]
        assert params == {"steps": 28, "scale": 7.5}
        assert isinstance(params["steps"], int)
        assert isinstance(params["scale"], float)

    def test_storage_list_default_prefix_is_root(self, client):
        body = client.get("/api/storage/list").json()
        assert set(body) == {"current_dir", "directories", "files"}
        assert body["current_dir"] == ""

    def test_media_search_default_limit_is_ten(self, client, db_session, stub_storage):
        from app.models import MediaAsset

        db_session.add_all(
            [
                MediaAsset(
                    title=f"clip {index}",
                    file_path=f"clip{index}.mp4",
                    file_size=1,
                    content_type="video/mp4",
                    duration=1.0,
                )
                for index in range(15)
            ]
        )
        db_session.commit()
        assert len(client.get("/api/media/search?query=clip").json()) == 10

    def test_colab_tunnel_default_status_is_running(self, client):
        body = client.post("/api/colab/tunnel?url=https://defaults.test").json()
        assert body["colab_status"] == "running"

    def test_task_process_default_task_type_is_transcode(self, client, monkeypatch):
        recorded = {}

        class _Result:
            id = "default-task"
            status = "PENDING"

        def _delay(path, task_type):
            recorded["args"] = (path, task_type)
            return _Result()

        monkeypatch.setattr(
            "app.routers.tasks.process_multimedia_task.delay", _delay, raising=True
        )
        client.post("/api/tasks/process?path=a.mp4")
        assert recorded["args"] == ("a.mp4", "transcode")
