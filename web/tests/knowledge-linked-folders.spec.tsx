import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KbLinkedFoldersSection from "@/components/knowledge/KbLinkedFoldersSection";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";

const fixture = vi.hoisted(() => ({
  t: (key: string, values?: Record<string, string | number>) =>
    key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values?.[name] ?? `{{${name}}}`)),
  list: vi.fn(),
  browse: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("@/features/knowledge/api/folders", () => ({
  listLinkedFolders: fixture.list,
}));

vi.mock("@/lib/workspaces-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workspaces-api")>()),
  browseServerFolders: fixture.browse,
}));

const kb: KnowledgeBase = {
  name: "papers",
  status: "ready",
  statistics: { raw_documents: 1 },
};

const folder = {
  id: "folder-1",
  path: "/notes",
  added_at: "2026-09-09T10:00:00",
  file_count: 0,
  last_sync: null,
  imported_count: 0,
};

beforeEach(() => {
  fixture.list.mockReset().mockResolvedValue([]);
  fixture.browse.mockReset().mockImplementation(async (path: string) => {
    if (path === "/materials/地理") {
      return {
        roots: [{ name: "materials", path: "/materials" }],
        path: "/materials/地理",
        name: "地理",
        parent: "/materials",
        folders: [],
        truncated: false,
      };
    }
    return {
      roots: [{ name: "materials", path: "/materials" }],
      path: "/materials",
      name: "materials",
      parent: null,
      folders: [{ name: "地理", path: "/materials/地理" }],
      truncated: false,
    };
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("loads linked folders with the qualified workspace KB reference", async () => {
  const qualified = "workspace:course-1:kb:papers";
  render(
    <KbLinkedFoldersSection
      kb={{ ...kb, id: qualified }}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  await waitFor(() =>
    expect(fixture.list).toHaveBeenCalledWith(qualified, expect.any(Object)),
  );
});

it("links a folder without automatically starting its first sync", async () => {
  const onLinkFolder = vi.fn().mockResolvedValue(undefined);
  const onUnlinkFolder = vi.fn().mockResolvedValue(undefined);
  const onSyncFolder = vi.fn().mockResolvedValue({
    message: "No new or modified files to sync",
    files: [],
    new_files: 0,
    modified_files: 0,
    file_count: 0,
    task_id: null,
  });
  fixture.list.mockResolvedValueOnce([]).mockResolvedValue([folder]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={onLinkFolder}
      onUnlinkFolder={onUnlinkFolder}
      onSyncFolder={onSyncFolder}
    />,
  );

  await waitFor(() => expect(fixture.list).toHaveBeenCalled());
  fireEvent.click(screen.getAllByRole("button", { name: "Link folder" })[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Folder path"), {
    target: { value: "/notes" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Link folder" }));

  await waitFor(() => expect(onLinkFolder).toHaveBeenCalledWith("/notes"));
  expect(onSyncFolder).not.toHaveBeenCalled();
  expect(await screen.findByText("/notes")).toBeInTheDocument();
  expect(screen.getByText(/Never synced/)).toBeInTheDocument();
});

it("picks a server folder with the browser and links it without typing a path", async () => {
  const onLinkFolder = vi.fn().mockResolvedValue(undefined);
  fixture.list.mockResolvedValue([]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={onLinkFolder}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  fireEvent.click((await screen.findAllByRole("button", { name: "Link folder" }))[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Choose a server folder" }));

  const picker = await screen.findByRole("dialog", { name: "Choose a server folder" });
  fireEvent.click(await within(picker).findByRole("button", { name: "地理" }));
  await waitFor(() =>
    expect(screen.getByLabelText("Current folder")).toHaveTextContent("/materials/地理"),
  );
  fireEvent.click(within(picker).getByRole("button", { name: "Select this folder" }));

  await waitFor(() =>
    expect(within(dialog).getByLabelText("Folder path")).toHaveValue("/materials/地理"),
  );
  expect(fixture.browse).toHaveBeenCalledWith("", "source");

  fireEvent.click(within(dialog).getByRole("button", { name: "Link folder" }));
  await waitFor(() => expect(onLinkFolder).toHaveBeenCalledWith("/materials/地理"));
});

it("does not complain about an empty path when the folder browser is opened", async () => {
  fixture.list.mockResolvedValue([]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  fireEvent.click((await screen.findAllByRole("button", { name: "Link folder" }))[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Choose a server folder" }));

  await screen.findByRole("dialog", { name: "Choose a server folder" });
  expect(
    within(dialog).queryByRole("alert"),
  ).not.toBeInTheDocument();
});

it("does not complain about an empty path when the dialog is cancelled", async () => {
  fixture.list.mockResolvedValue([]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  fireEvent.click((await screen.findAllByRole("button", { name: "Link folder" }))[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "Link a local folder" })).not.toBeInTheDocument(),
  );
  expect(screen.queryByText("Folder path is required.")).not.toBeInTheDocument();
});

it("shows the no-change result after a manual sync", async () => {
  fixture.list.mockResolvedValue([folder]);
  const onSyncFolder = vi.fn().mockResolvedValue({
    message: "No new or modified files to sync",
    files: [],
    new_files: 0,
    modified_files: 0,
    file_count: 0,
    task_id: null,
  });

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={onSyncFolder}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

  await waitFor(() =>
    expect(onSyncFolder).toHaveBeenCalledWith("folder-1"),
  );
  expect(
    await screen.findByText("No new or modified files to sync"),
  ).toBeInTheDocument();
});

it("shows queued sync counts for new and modified files", async () => {
  fixture.list.mockResolvedValue([folder]);
  const onSyncFolder = vi.fn().mockResolvedValue({
    message: "Syncing 3 files from linked folder",
    folder_path: "/notes",
    files: ["/notes/a.md", "/notes/b.md", "/notes/c.md"],
    new_files: 2,
    modified_files: 1,
    file_count: 3,
    task_id: "sync-task",
  });

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={onSyncFolder}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

  expect(
    await screen.findByText("Queued 3 files for indexing. 2 new, 1 modified."),
  ).toBeInTheDocument();
});

it("shows a retry action when the linked-folder list fails to load", async () => {
  fixture.list
    .mockRejectedValueOnce(new Error("Folder service unavailable"))
    .mockResolvedValueOnce([]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Folder service unavailable",
  );
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  await waitFor(() => expect(fixture.list).toHaveBeenCalledTimes(2));
  expect(
    screen.getByText(/No linked folders yet/),
  ).toBeInTheDocument();
});

it("validates the link modal and confirms unlinking", async () => {
  fixture.list.mockResolvedValue([{ ...folder, file_count: 3, imported_count: 3 }]);
  const onLinkFolder = vi.fn().mockResolvedValue(undefined);
  const onUnlinkFolder = vi.fn().mockResolvedValue({
    message: "Folder unlinked successfully",
    folder_id: "folder-1",
    removed_count: 3,
    removed_files: ["a.md", "b.md", "c.md"],
    was_indexed: true,
    reindex_task_id: "reindex-task",
    reindex_error: null,
  });

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={onLinkFolder}
      onUnlinkFolder={onUnlinkFolder}
      onSyncFolder={vi.fn()}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getAllByRole("button", { name: "Link folder" })[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Link folder" }));
  expect(onLinkFolder).not.toHaveBeenCalled();
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Folder path is required.",
  );

  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(screen.getByRole("button", { name: "Unlink /notes" }));
  const confirmDialog = await screen.findByRole("alertdialog");
  expect(confirmDialog).toHaveTextContent(
    "This folder has imported 3 document(s) into this knowledge base.",
  );
  fireEvent.click(within(confirmDialog).getByRole("button", { name: "Cancel" }));
  expect(onUnlinkFolder).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Unlink /notes" }));
  const confirmed = await screen.findByRole("alertdialog");
  fireEvent.click(
    within(confirmed).getByRole("button", { name: "Unlink and delete documents" }),
  );
  await waitFor(() => expect(onUnlinkFolder).toHaveBeenCalledWith("folder-1"));
  expect(screen.queryByText("/notes")).not.toBeInTheDocument();
});

it("does not claim that a never-synced folder imported documents", async () => {
  fixture.list.mockResolvedValue([{ ...folder, file_count: 102, imported_count: 0 }]);

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Unlink /notes" }));
  const confirmDialog = await screen.findByRole("alertdialog");
  expect(confirmDialog).toHaveTextContent(
    "This folder has not imported any documents into this knowledge base yet.",
  );
  expect(confirmDialog).not.toHaveTextContent("document(s)");
});

it("reports a failed index rebuild after unlinking", async () => {
  fixture.list.mockResolvedValue([folder]);
  const onUnlinkFolder = vi.fn().mockResolvedValue({
    message: "Folder unlinked successfully",
    folder_id: "folder-1",
    removed_count: 1,
    removed_files: ["a.md"],
    was_indexed: true,
    reindex_task_id: null,
    reindex_error: "An indexing worker still owns this knowledge base.",
  });

  render(
    <KbLinkedFoldersSection
      kb={kb}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={onUnlinkFolder}
      onSyncFolder={vi.fn()}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Unlink /notes" }));
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Unlink and delete documents" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The documents were removed, but the index could not be rebuilt automatically",
  );
});

it("keeps linked-folder controls disabled for a read-only knowledge base", async () => {
  fixture.list.mockResolvedValue([folder]);

  render(
    <KbLinkedFoldersSection
      kb={{ ...kb, read_only: true }}
      onLinkFolder={vi.fn()}
      onUnlinkFolder={vi.fn()}
      onSyncFolder={vi.fn()}
    />,
  );

  await waitFor(() => expect(screen.getByText("/notes")).toBeInTheDocument());
  expect(
    screen.getByText(
      "This knowledge base is read-only. Linked folders can be viewed but not changed.",
    ),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Link folder" })[0]).toBeDisabled();
  expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Unlink /notes" })).toBeDisabled();
});
