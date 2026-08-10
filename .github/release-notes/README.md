# Release notes

The release workflow ([`../workflows/release-build.yml`](../workflows/release-build.yml))
looks for a file named `<version>.md` in this directory when it drafts a GitHub
release. For example `v1.3.3.md` for release `v1.3.3`.

- If the matching file exists, its contents become the release notes.
- If it does not exist, the workflow falls back to the head commit message.

A SHA-256 checksum note is appended automatically.

Keeping this file here also ensures the directory exists in the repository, so
the workflow's lookup path is always valid.
