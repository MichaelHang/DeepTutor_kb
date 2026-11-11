"use client";

import { useCallback, useState } from "react";

import {
  listWorkspaces,
  saveWorkspace,
  type WorkspaceMount,
} from "@/lib/workspaces-api";

export interface WorkspaceMountDraft {
  name: string;
  path: string;
}

/**
 * A mount name is a path segment the agent reads, so it is built from the
 * folder's own name and kept short: letters, digits, dots, dashes and
 * underscores, starting with a letter or a digit.
 */
export function mountNameFromFolder(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[^a-z0-9]+/, "")
    .replace(/[^a-z0-9]+$/, "")
    .slice(0, 64);
  return slug || "folder";
}

/** A name no other mount in the list already uses. */
export function uniqueMountName(name: string, taken: readonly string[]): string {
  const used = new Set(taken.map((entry) => entry.toLowerCase()));
  if (!used.has(name.toLowerCase())) return name;
  for (let suffix = 2; suffix < 100; suffix += 1) {
    const candidate = `${name}-${suffix}`.slice(0, 64);
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
  return name;
}

/**
 * The folders mounted into the conversation's workspace.
 *
 * A mount is a read-only view: the agent reads the folder under a short
 * name, and anything it produces still lands in the workspace's `outputs/`.
 * The workspace without a chosen one is the default workspace, so an
 * unbound conversation still has somewhere to mount into.
 *
 * Nothing is fetched until `load` is called: most conversations never ask
 * about folders, and a request nobody made is a request nobody waits for.
 */
export function useWorkspaceMounts(workspaceId: string | null | undefined) {
  const [mounts, setMounts] = useState<WorkspaceMount[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const resolve = useCallback(async () => {
    const rows = await listWorkspaces(true);
    return workspaceId
      ? rows.find((row) => row.workspace_id === workspaceId)
      : rows.find((row) => row.kind === "general");
  }, [workspaceId]);

  const load = useCallback(async () => {
    try {
      const row = await resolve();
      setMounts(row?.mounts ?? []);
    } catch {
      // The picker simply reports nothing to pick; the conversation keeps
      // the folders it already had.
      setMounts([]);
    }
  }, [resolve]);

  const save = useCallback(
    async (next: WorkspaceMountDraft[]) => {
      setBusy(true);
      setError("");
      try {
        const row = await resolve();
        if (!row) throw new Error("This workspace is not available.");
        await saveWorkspace({ mounts: next }, row.workspace_id);
        setMounts(next.map((mount) => ({ ...mount, read_only: true, available: true })));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [resolve],
  );

  return { mounts, load, save, busy, error };
}
