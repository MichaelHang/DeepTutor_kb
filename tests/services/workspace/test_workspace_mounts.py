"""Read-only folder mounts for a content workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.path_service import PathService
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError
from deeptutor.services.workspace.mounts import (
    MAX_MOUNTS,
    RESERVED_MOUNT_NAMES,
    describe_mounts,
    parse_mounts,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    from deeptutor.services.workspace import service as module

    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    monkeypatch.setattr(module, "get_path_service", lambda: paths)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)
    return ContentWorkspaceService()


@pytest.fixture
def materials(tmp_path) -> Path:
    """A folder outside the workspace that a mount may point at."""
    folder = tmp_path / "materials"
    (folder / "geo").mkdir(parents=True)
    (folder / "geo" / "notes.md").write_text("plate tectonics", encoding="utf-8")
    (folder / "readme.txt").write_text("course materials", encoding="utf-8")
    return folder


def test_mount_definitions_are_validated(materials: Path) -> None:
    mounted = parse_mounts([{"name": "materials", "path": str(materials)}])
    assert mounted[0].name == "materials"
    assert mounted[0].path == materials.resolve()
    assert mounted[0].read_only is True

    with pytest.raises(WorkspaceError):
        parse_mounts([{"name": "has space", "path": str(materials)}])
    with pytest.raises(WorkspaceError):
        parse_mounts([{"name": "-leading", "path": str(materials)}])
    with pytest.raises(WorkspaceError):
        parse_mounts([{"name": "relative", "path": "materials"}])
    with pytest.raises(WorkspaceError):
        parse_mounts([{"name": "materials", "path": str(materials)}] * 2)
    with pytest.raises(WorkspaceError):
        parse_mounts([{"name": "missing", "path": str(materials / "nope")}])
    for reserved in RESERVED_MOUNT_NAMES:
        with pytest.raises(WorkspaceError):
            parse_mounts([{"name": reserved, "path": str(materials)}])
    with pytest.raises(WorkspaceError):
        parse_mounts(
            [{"name": f"m{index}", "path": str(materials)} for index in range(MAX_MOUNTS + 1)]
        )


def test_a_missing_folder_is_skipped_rather_than_failing_the_list(materials: Path) -> None:
    assert (
        parse_mounts([{"name": "gone", "path": str(materials / "nope")}], skip_unavailable=True)
        == []
    )
    described = describe_mounts(
        [
            {"name": "materials", "path": str(materials)},
            {"name": "gone", "path": str(materials / "nope")},
        ]
    )
    assert [row["available"] for row in described] == [True, False]


def test_a_workspace_keeps_its_mounts(service, materials: Path) -> None:
    workspace = service.create_workspace(
        "Geo", mounts=[{"name": "materials", "path": str(materials)}]
    )
    assert workspace["mounts"] == [
        {
            "name": "materials",
            "path": str(materials.resolve()),
            "read_only": True,
            "available": True,
        }
    ]
    assert service.workspace_mounts(workspace["workspace_id"])[0].name == "materials"

    service.update_workspace(workspace["workspace_id"], mounts=[])
    assert service.workspace_mounts(workspace["workspace_id"]) == []


def test_a_mount_name_may_not_shadow_a_workspace_folder(service, materials: Path) -> None:
    workspace = service.create_workspace("Geo")
    root = Path(workspace["path"])
    (root / "materials").mkdir()
    with pytest.raises(WorkspaceError):
        service.update_workspace(
            workspace["workspace_id"], mounts=[{"name": "materials", "path": str(materials)}]
        )


def test_a_mounted_folder_is_reachable_under_its_name(service, materials: Path) -> None:
    workspace = service.create_workspace(
        "Geo", mounts=[{"name": "materials", "path": str(materials)}]
    )
    binding = service.binding_by_id(workspace["workspace_id"])
    mounts = service.workspace_mounts(workspace["workspace_id"])

    root_rows = service.list_entries_page(binding, ".", mounts=mounts)["entries"]
    assert [row["name"] for row in root_rows if row["kind"] == "mount"] == ["materials"]

    rows = service.list_entries_page(binding, "materials/geo", mounts=mounts)["entries"]
    assert [row["path"] for row in rows] == ["materials/geo/notes.md"]

    read = service.read_text(binding, "materials/geo/notes.md", mounts=mounts)
    assert "plate tectonics" in read["content"]

    matches = service.search(binding, "tectonics", mounts=mounts)
    assert [row["path"] for row in matches] == ["materials/geo/notes.md"]


def test_a_mount_cannot_be_written_to(service, materials: Path) -> None:
    workspace = service.create_workspace(
        "Geo", mounts=[{"name": "materials", "path": str(materials)}]
    )
    binding = service.binding_by_id(workspace["workspace_id"])
    mounts = service.workspace_mounts(workspace["workspace_id"])
    context = service.create_runtime_context(
        capability="chat",
        session_id="s/one",
        turn_id="t/one",
        workspace_id=workspace["workspace_id"],
    )
    produced = Path(context.output_dir) / "result.txt"
    produced.write_text("done", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        service.validate_export(
            binding,
            source_path=context.logical_output_dir + "/result.txt",
            destination_path="materials/result.txt",
            mounts=mounts,
        )


def test_a_mount_cannot_escape_its_folder(service, materials: Path) -> None:
    workspace = service.create_workspace(
        "Geo", mounts=[{"name": "materials", "path": str(materials)}]
    )
    binding = service.binding_by_id(workspace["workspace_id"])
    mounts = service.workspace_mounts(workspace["workspace_id"])

    with pytest.raises(WorkspaceError):
        service.read_text(binding, "materials/../secrets.txt", mounts=mounts)
    with pytest.raises(WorkspaceError):
        service.list_entries_page(binding, "materials/..", mounts=mounts)


def test_a_session_mount_overrides_the_workspace_mount_by_name(
    service, materials: Path, tmp_path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.md").write_text("from the session mount", encoding="utf-8")
    workspace = service.create_workspace(
        "Geo", mounts=[{"name": "materials", "path": str(materials)}]
    )
    binding = service.binding_by_id(workspace["workspace_id"])

    effective = service.effective_mounts(binding, [{"name": "materials", "path": str(other)}])
    assert effective[0]["path"] == str(other.resolve())

    # A folder that has gone away is dropped, not fatal.
    assert (
        service.session_mounts(
            workspace["workspace_id"], [{"name": "gone", "path": str(tmp_path / "nope")}]
        )
        == []
    )


def test_the_runtime_context_carries_the_mount_names_only(service, materials: Path) -> None:
    workspace = service.create_workspace(
        "Geo", mounts=[{"name": "materials", "path": str(materials)}]
    )
    context = service.create_runtime_context(
        capability="chat",
        session_id="s/one",
        turn_id="t/one",
        workspace_id=workspace["workspace_id"],
    )
    assert context.mounts == ({"name": "materials", "path": str(materials.resolve())},)
