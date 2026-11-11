import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AddMaterialsDialog } from "@/components/reading/library/AddMaterialsDialog";

const mock = vi.hoisted(() => ({
  uploadMaterial: vi.fn(),
  supportedFormats: {
    extensions: [".pdf", ".mp3", ".mp4"],
    max_bytes: 300 * 1024 * 1024,
    max_audio_bytes: 250 * 1024 * 1024,
    max_video_bytes: 1024 * 1024 * 1024,
    audio_extensions: [".mp3"],
    video_extensions: [".mp4"],
    raw_view_extensions: [],
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string>) =>
      values
        ? Object.entries(values).reduce(
            (text, [name, value]) => text.replaceAll(`{{${name}}}`, value),
            key,
          )
        : key,
  }),
}));

vi.mock("@/components/watching/WatchingBrowser", () => ({
  WatchingBrowser: () => null,
}));

vi.mock("@/lib/reading-api", () => ({
  uploadMaterial: mock.uploadMaterial,
  getSupportedFormats: () => Promise.resolve(mock.supportedFormats),
}));

vi.mock("@/lib/reading-workspace-api", () => ({
  addReadingWorkspaceMaterial: vi.fn(),
  checkReadingDuplicates: vi.fn().mockResolvedValue([]),
  createReadingWorkspace: vi.fn(),
  importReadingUrls: vi.fn(),
  listReadingLibraryMaterials: vi.fn().mockResolvedValue([]),
  readingContentId: vi.fn(),
}));

/** A file of a given size, without allocating one. */
function sizedFile(name: string, bytes: number): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

async function renderDialog() {
  const view = render(
    <AddMaterialsDialog mode="upload" onClose={() => undefined} onDone={() => undefined} />,
  );
  const input = view.container.querySelector('input[type="file"]');
  if (!input) throw new Error("the dialog has no file input");
  // The dialog asks the server for its ceilings; wait until they are in.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return { view, input };
}

it("refuses a video that is over the video ceiling, without uploading it", async () => {
  const { input } = await renderDialog();

  fireEvent.change(input!, {
    target: { files: [sizedFile("lecture.mp4", 1100 * 1024 * 1024)] },
  });

  await waitFor(() =>
    expect(screen.getByText(/File too large/)).toHaveTextContent("lecture.mp4"),
  );
  expect(screen.getByText(/File too large/)).toHaveTextContent("1024 MB");
});

it("refuses an audio track that is over the audio ceiling, not the video one", async () => {
  const { input } = await renderDialog();

  fireEvent.change(input!, {
    target: { files: [sizedFile("lecture.mp3", 300 * 1024 * 1024)] },
  });

  await waitFor(() =>
    expect(screen.getByText(/File too large/)).toHaveTextContent("250 MB"),
  );
});

it("refuses a document that is over the document ceiling", async () => {
  const { input } = await renderDialog();

  fireEvent.change(input!, {
    target: { files: [sizedFile("notes.pdf", 400 * 1024 * 1024)] },
  });

  await waitFor(() =>
    expect(screen.getByText(/File too large/)).toHaveTextContent("300 MB"),
  );
});

it("accepts a video that is under the video ceiling", async () => {
  const { input } = await renderDialog();

  fireEvent.change(input!, {
    target: { files: [sizedFile("lecture.mp4", 1000 * 1024 * 1024)] },
  });

  await waitFor(() => expect(screen.queryByText(/File too large/)).toBeNull());
});
