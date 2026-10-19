[中文](README.md) · **English**

# Mac Cleaner

A Mac cleaner that shows you the list first, lets you pick, and lets you undo.

Nothing is deleted until you approve it, and **everything goes to the Trash** — drag it back if you
change your mind. Prefer not to use a UI? It is also a CLI, and AI clients (Claude / Codex / Cursor)
can call it directly.

---

<details id="ai-prompt-quick-start" open>
<summary><strong>Beginner: tell your AI this</strong></summary>

Hook the repo into your AI client (see [docs/mcp.md](docs/mcp.md)), then paste these two prompts.

**First — look, don't touch**

```text
only audit and show me a list; do not delete or modify any files.
explain, in plain words, what each item is, how big it is, and whether it is recoverable.
```

**Second — delete only what you named**

```text
only run the target_id values i explicitly approve from the current plan: home-caches, vscode-cache
leave everything else alone.
```

The point: however eager the model is, it can only act inside the scope you named.

</details>

<details id="features" open>
<summary><strong>What it actually does</strong></summary>

| You want to | It does |
|---|---|
| **Free up disk space** | Scans caches, logs, Xcode leftovers, package-manager caches; shows a list and **changes nothing until you tick items** |
| **Remove an app completely** | Finds the bundle plus its caches, preferences, containers, launch agents — including `.ShipIt` updater leftovers |
| **Update software** | Checks Homebrew, App Store, npm, and more; apps with their own Sparkle updater go first, store apps fall back to the App Store |
| **See what is eating the disk** | Disk page drills down one folder at a time, down to the big files |
| **Check what a past cleanup did** | History page reads each receipt: time, item count, bytes, dry-run or not |
| **Let an AI do it** | 7 MCP tools behind a one-time local link; the model stays inside your approved scope |

Deliberate speed bumps:

- scanning is read-only; a second click is required to start;
- one more **confirmation page** shows how many groups and how many bytes;
- high-risk targets (`~/Downloads`, Docker data) **cannot be ticked** on the review page at all —
  they need a separate confirmation;
- mistakes are recoverable: everything lands in the Trash.

</details>

<details id="installation" open>
<summary><strong>Install</strong></summary>

macOS + Python 3.10+. The core CLI has **no third-party runtime dependencies**.

```bash
pipx install maccleaner
maccleaner --help
```

Not on PyPI yet — install from source:

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git"
```

For AI clients, install with the MCP extra:

```bash
pipx install "maccleaner[mcp]"
```

For the native window (outside the browser):

```bash
bash scripts/install_launcher.sh     # builds ~/Applications/MacCleaner.app
```

Build your own offline artifacts (verified with a clean venv and `pip install --no-index`):

```bash
python3 -m pip install wheel
python3 -m build --no-isolation     # dist/*.whl + *.tar.gz
```

</details>

<details id="interface" open>
<summary><strong>The window</strong></summary>

Open `~/Applications/MacCleaner.app`, or run `maccleaner ui`. Seven entries in the sidebar:

| Entry | What it does |
|---|---|
| **Mac Cleanup** | scan → tick items → confirm → done |
| **Uninstall** | app list; inspect leftovers one by one, or batch-uninstall |
| **Updates** | grouped by source (Homebrew / App Store / npm…); Sparkle apps get their own group |
| **Disk** | capacity + common folders, drill down level by level |
| **System** | load, memory, top CPU processes |
| **History** | one row per cleanup receipt |
| **Skills** | agent skills installed on this machine |

Interaction follows macOS list habits:

- tick with the small checkbox; **clicking elsewhere on the row opens the detail** (no mis-ticking);
- `⌘A` select all, `Shift+click` range select, `Enter` primary action, `Esc` close menu;
- sort by **size / name**; long lists have an A–Z index on the right;
- right-click for "Copy path" / "Reveal in Finder";
- going back from a detail restores your **scroll position**.

</details>

<details id="cli">
<summary><strong>CLI</strong></summary>

```bash
maccleaner audit                      # read-only overview
maccleaner plan                       # items with target_id / risk / reason
maccleaner clean --apply --yes        # actually remove (low-risk, regenerable by default)
maccleaner uninstall --app-path /Applications/Foo.app --apply
maccleaner updates                    # check only
maccleaner updates --apply --only aom,cmake
maccleaner trace <plan_id>            # what a given plan did
```

</details>

<details id="mcp">
<summary><strong>MCP (for AI clients)</strong></summary>

`maccleaner-mcp` speaks stdio and exposes 7 tools: `audit_storage`, `plan_storage`,
`apply_storage_plan`, `uninstall_plan`, `uninstall_apply`, `updates_check`, `updates_apply`.

A minimal read-only session:

```json
{"name": "audit_storage", "arguments": {"profile": "generic"}}
{"name": "plan_storage", "arguments": {"profile": "generic"}}
{"name": "apply_storage_plan", "arguments": {
  "plan_id": "<from plan_storage>",
  "approved_targets": ["home-caches"]
}}
```

Empty `approved_targets`, or a `plan_id` older than 15 minutes, is refused.
Client configuration: [docs/mcp.md](docs/mcp.md).

</details>

<details id="verification">
<summary><strong>Verify it yourself</strong></summary>

```bash
python3 -m unittest discover -s tests -v      # 262 unit tests
```

GUI acceptance scripts (run manually):

```bash
bash tests/acceptance_native_smoke.sh      # real window, 11 steps incl. a real cleanup
bash tests/acceptance_uninstall_batch.py   # batch uninstall end to end
bash tests/acceptance_quit.sh              # nothing left running after quit
bash tests/acceptance_portability.sh       # copy the repo elsewhere + fresh HOME
bash tests/acceptance_package.sh           # build + offline install + real audit
```

</details>

<details id="privacy">
<summary><strong>Safety and privacy</strong></summary>

- **No telemetry**; no file names, paths or usage data are uploaded;
- the UI binds to `127.0.0.1` only, uses a one-time entry link, and requires cookie + header per action;
- deletions go to the Trash; protected paths (`.ssh`, Keychains, browser login data) never appear;
- the only network traffic is package managers' own checks plus App Store version lookups
  (app id + country only).

Details: [PRIVACY.md](PRIVACY.md). MIT licensed.

</details>

---

Maintained jointly by **AI·Maho** and **Human·Matoya**
