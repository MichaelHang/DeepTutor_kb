# Choose a server folder as a workspace

In a new conversation, open the workspace menu next to the composer and choose
**Choose a server folder**. Open folders until the desired project is displayed,
then choose **Select this folder**. New registrations use the folder name;
existing registrations retain their names and settings. Selecting an archived
registration restores it. Conversations with messages keep their existing binding.

The same picker is available in **Settings → Workspaces → New workspace**,
where it fills the existing-folder path and a default workspace name.
Browsing folders is read-only. Registration continues to use the existing
workspace validation and output-directory initialization.

## Link a knowledge base to a local folder

A knowledge base can take its documents from a local folder. In the knowledge
base's **Link folder** dialog, choose **Browse folders on the server** and walk
down to the folder you want. The path field stays available for a path that is
easier to type.

Linking only records where the documents live — nothing is imported until
**Sync now** is pressed. The linked folder is a read-only source: the agent may
read the documents it provides, but it never writes into the folder.

## Mount a folder for the agent to read

A workspace can mount a local folder so the agent may read it. In the composer's
**Folders** menu, choose **Mount a folder**, walk down to the folder you want and
choose **Select this folder**. **Settings → Workspaces → Mounted folders** manages
the same list.

A mount is a read-only view: the folder keeps its own place on disk, and the agent
reaches it under the short name given to the mount — `materials/geo/notes.md` is
`notes.md` inside the mount `materials`. The agent never writes into a mounted
folder; its own output still belongs in the workspace's `outputs/`.

The host path never reaches the model: it sees the mount name only. When code run
through `exec` must open a file inside a mount, it joins the mount name from the
`DEEPTUTOR_WORKSPACE_MOUNTS` environment variable with the exact relative path a
workspace tool returned, and never prints that variable's value.

## Deployment

The picker browses the filesystem of the backend, rather than the computer
running the browser. In Docker, project folders must be bind-mounted first.
For example, mount `/srv/projects` at `/srv/projects` inside the container and
set `DEEPTUTOR_WORKSPACE_BROWSER_ROOTS=/srv/projects`.

Multiple roots are separated by the backend platform's path separator (`:` on
Linux/macOS, `;` on Windows). Without this setting, the picker uses the roots
already provided by the content-workspace policy. Configured roots are also
checked against that policy for the requesting user; this setting does not
grant a non-admin access to additional folders. Admins remain confined to the
picker's configured browsing roots as well.

The knowledge base picker browses a wider set of roots, because a document
source is not a workspace: it may live on a mounted volume. Without
configuration it offers the backend's home directory, the platform's mount
points (`/Volumes` on macOS, `/mnt` and `/media` on Linux, `C:/` on Windows) and
the workspace roots. Set `DEEPTUTOR_LINK_FOLDER_ROOTS` to name the folders a
knowledge base may link documents from — for example
`DEEPTUTOR_LINK_FOLDER_ROOTS=/srv/materials`. Multiple roots are separated by
the backend platform's path separator. This scope is read-only as well:
linking records where the documents live and does not give the agent a place
to write.

The mounted-folder picker browses the same roots as the knowledge base picker,
because a mounted folder is read from the server just like a linked document
source. The same `DEEPTUTOR_LINK_FOLDER_ROOTS` setting therefore names the
folders that may be mounted.

The picker shows accessible non-hidden subdirectories and omits symlinks that
resolve outside the current root. Each directory scan is bounded to 10,000
entries and returns at most 500 folders. Filtering applies to the displayed
directory, not recursively to the whole project tree. The API is
`GET /api/settings/workspace/folders?path=...&scope=workspace|source|mount` and
inherits settings authentication.
