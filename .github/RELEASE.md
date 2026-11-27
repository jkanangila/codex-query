Here is a ready-to-use Markdown guide you can save as `.github/RELEASE.md` (or `.github/releasing.md`).

````markdown
# Release Process — Codex Query

Releases are automated via `.github/workflows/release.yml` when changes land on `main` and a new version tag (`v<VERSION>`) does not yet exist.

Because the workflow fails fast if release notes are missing and skips releasing if the tag already exists, every release requires the steps below.

---

## 1. Before Cutting a Release

1. **Confirm `main` is green and up to date:** All target changes and dependency updates (`uv.lock` and `[tool.flet.<platform>].dependencies` in `pyproject.toml`) are merged into `main`.
2. **Verify repository secrets (for Android signing):** Ensure the following GitHub Actions secrets are configured:
   - `ANDROID_KEYSTORE_BASE64` (base64-encoded `.jks` keystore)
   - `ANDROID_KEYSTORE_PASSWORD`
   - `ANDROID_KEY_ALIAS`

---

## 2. Bump the Version

Update `[project].version` in `pyproject.toml` to the new release version (for example, `1.2.0`):

```toml
[project]
name = "codex-query"
version = "1.2.0"
```
````

- The workflow reads this value directly and checks whether tag `v<VERSION>` already exists.
- If `v<VERSION>` already exists, the `prepare` job sets `should_release=false` and skips building and publishing.

---

## 3. Add Release Notes

Create a Markdown file at `.github/release-notes/v<VERSION>.md` matching the exact version in `pyproject.toml` (for example, `.github/release-notes/v1.2.0.md`):

- The `prepare` job checks for this file **before** starting the four platform builds (`windows`, `linux`, `macos`, `android`).
- If the file is missing, `prepare` exits with an error so CI minutes are not wasted.
- The workflow uses this file as the release body and also enables `generate_release_notes: true`.

---

## 4. Merge to `main` and Monitor the Workflow

1. Merge the version bump and release notes commit into `main` (or trigger `workflow_dispatch` while on `main`).
2. Watch the **Release** workflow in **Actions**:

- **`prepare`**: Validates `pyproject.toml` version, confirms `v<VERSION>` is new, and verifies `.github/release-notes/v<VERSION>.md` exists.
- **`build`**: Runs in parallel across `windows-latest`, `ubuntu-latest` (`linux`), `macos-latest` (`--arch arm64`), and `ubuntu-latest` (`apk`), using `uv run --locked --no-dev flet build ... --build-number ${{ github.run_number }}` and packaging outputs into `dist/`:
- `codex-query-<VERSION>-windows.zip`
- `codex-query-<VERSION>-linux.tar.gz`
- `codex-query-<VERSION>-macos.zip`
- `codex-query-<VERSION>-android-<apk-name>.apk`

- **`release`**: Downloads all four build artifacts, creates a draft release for `v<VERSION>`, uploads `dist/*`, and publishes the release via `gh release edit "v$VERSION" --draft=false`.

---

## 5. Post-Release Verification

1. Open the published **GitHub Release** for `v<VERSION>` and verify:

- All four platform assets (`windows`, `linux`, `macos`, `android`) are attached.
- Release notes and version title (`Codex Query v<VERSION>`) look right.
- Tag `v<VERSION>` points to the intended commit on `main`.

2. Download and smoke-test the platform archives/APKs as needed.

---

## Troubleshooting Quick Reference

- **Workflow exits early with "Tag v... already exists":** Bump `[project].version` in `pyproject.toml` to an unused version number.
- **`prepare` fails with "Missing .github/release-notes/v....md":** Add `.github/release-notes/v<VERSION>.md` in the same commit or prior commit on `main`.
- **A single platform build fails in `build`:** Because `fail-fast: false` is set, other platform builds still complete. Inspect the failing matrix job logs, fix the issue on `main`, and re-run (since the release is only published after all required builds succeed and upload).

```

```
