import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ComposerTray } from "@/components/chat/home/ComposerTray";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))
// The folder browser is loaded on demand in the app; the test resolves it
// right away so the dialog can be driven synchronously.
vi.mock("next/dynamic", async () => {
  const picker = await import("@/components/workspaces/ServerFolderPicker");
  const Picker = picker.ServerFolderPicker as React.ComponentType<Record<string, unknown>>;
  return {
    default: () =>
      function Lazy(props: Record<string, unknown>) {
        return <Picker {...props} />;
      },
  };
})
vi.mock("@/components/workspaces/ServerFolderPicker", () => ({
  ServerFolderPicker: ({
    onSelect,
    scope,
  }: {
    onSelect: (folder: { name: string; path: string }) => void
    scope: string
  }) => (
    <button
      type="button"
      onClick={() => onSelect({ name: "Course Materials", path: "/data/materials" })}
    >
      pick:{scope}
    </button>
  ),
}))

it("lists the mounted folders and asks for them only once the list opens", async () => {
  const load = vi.fn()
  const onChange = vi.fn()
  render(
    <ComposerTray
      placement="down"
      mounts={{
        mounts: [{ name: "materials", path: "/data/materials" }],
        onChange,
        load,
      }}
    />,
  )
  expect(load).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: /Folders/ }))
  await waitFor(() => expect(load).toHaveBeenCalled())
  expect(screen.getByText("materials")).toBeInTheDocument()
})

it("removes a folder when its row is picked", async () => {
  const onChange = vi.fn()
  render(
    <ComposerTray
      placement="down"
      mounts={{
        mounts: [{ name: "materials", path: "/data/materials" }],
        onChange,
        load: vi.fn(),
      }}
    />,
  )
  fireEvent.click(screen.getByRole("button", { name: /Folders/ }))
  await act(async () => {
    fireEvent.click(await screen.findByRole("option", { name: /materials/ }))
  })
  expect(onChange).toHaveBeenCalledWith([])
})

it("mounts a folder the user picks on the server", async () => {
  const onChange = vi.fn()
  render(
    <ComposerTray
      placement="down"
      mounts={{ mounts: [], onChange, load: vi.fn() }}
    />,
  )
  fireEvent.click(screen.getByRole("button", { name: /Folders/ }))
  fireEvent.click(await screen.findByRole("button", { name: "Mount a folder" }))
  await act(async () => {
    fireEvent.click(await screen.findByRole("button", { name: "pick:mount" }))
  })
  await waitFor(() =>
    expect(onChange).toHaveBeenCalledWith([
      { name: "course-materials", path: "/data/materials" },
    ]),
  )
})

it("hides the Folders menu when the page customization turns it off", () => {
  render(
    <ComposerTray
      placement="down"
      mounts={{ mounts: [], onChange: vi.fn() }}
      controls={{ skills: true, mcp: true, partners: true, preferences: true, voice: true, mounts: false }}
    />,
  )
  expect(screen.queryByRole("button", { name: /Folders/ })).not.toBeInTheDocument()
})
