'use client'

import { useState } from 'react'
import { Folder, FolderPlus, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ServerFolderPicker } from '@/components/workspaces/ServerFolderPicker'
import { mountNameFromFolder, uniqueMountName } from '@/hooks/useWorkspaceMounts'
import type { WorkspaceMount } from '@/lib/workspaces-api'

const inputClass = 'w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm'

/**
 * The folders a workspace mounts, named for the agent.
 *
 * A mount is a read-only view: the folder keeps its own place on disk and the
 * agent reaches it under the name given here. The name is what the model
 * sees, so it is short and edited in place; the path stays visible so the
 * owner can tell which folder is meant.
 */
export function WorkspaceMountsEditor({
  mounts,
  onChange,
  disabled = false,
}: {
  mounts: WorkspaceMount[]
  onChange: (mounts: WorkspaceMount[]) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [browsing, setBrowsing] = useState(false)

  const patch = (index: number, next: Partial<WorkspaceMount>) => {
    onChange(
      mounts.map((mount, position) =>
        position === index ? { ...mount, ...next } : mount
      )
    )
  }

  const remove = (index: number) => {
    onChange(mounts.filter((_, position) => position !== index))
  }

  const add = (folder: { name: string; path: string }) => {
    const name = uniqueMountName(
      mountNameFromFolder(folder.name),
      mounts.map((mount) => mount.name)
    )
    onChange([...mounts, { name, path: folder.path, read_only: true }])
  }

  return (
    <div className="space-y-2">
      {mounts.map((mount, index) => (
        <div
          key={`${mount.path}-${index}`}
          className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] p-2"
        >
          <Folder size={15} className="shrink-0 text-[var(--muted-foreground)]" />
          <div className="min-w-0 flex-1 space-y-1">
            <input
              aria-label={t('Folder name')}
              className={inputClass}
              value={mount.name}
              maxLength={64}
              disabled={disabled}
              onChange={event => patch(index, { name: event.target.value })}
            />
            <p className="select-all break-all font-mono text-[11.5px] text-[var(--muted-foreground)]">
              {mount.path}
            </p>
            {mount.available === false && (
              <p className="text-[11.5px] text-[var(--destructive)]">
                {t('This folder is no longer available.')}
              </p>
            )}
          </div>
          <button
            type="button"
            aria-label={t('Remove folder')}
            disabled={disabled}
            onClick={() => remove(index)}
            className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
          >
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setBrowsing(true)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
      >
        <FolderPlus size={15} />
        {t('Mount a folder')}
      </button>
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        {t(
          'Mounted folders are read-only: the agent reads them under the name given here, and its own files still go into outputs/.'
        )}
      </p>
      {browsing && (
        <ServerFolderPicker
          scope="mount"
          onClose={() => setBrowsing(false)}
          onSelect={folder => {
            add(folder)
          }}
        />
      )}
    </div>
  )
}
