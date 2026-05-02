# Scene File Format

This guide explains how to structure your scene files so that lit-critic can analyze them effectively.

## Overview

Each scene in your novel is saved as a **separate text file**. Every scene file has two parts:

1. **@@META header** A minimal metadata block at the very top (for reading-order navigation)
2. **Scene text** Your actual prose

The metadata header is lightweight by design — it contains only what the tool needs to navigate your scene chain. Everything else (characters, terms, threads, timeline) is extracted automatically from your prose when you run `knowledge refresh`.

---

## Scene File Naming

**Scene identity is the filename.** There is no separate `ID` field — the filename IS the scene's identifier throughout the system.

Use any consistent naming convention you like:

```
01.01.01_Amelia_awakens.txt
01.02.03_The_marketplace.txt
scene-042-showdown.txt
ch03-part2.txt
```

**Filenames are stable.** If you rename a scene, use `lit-critic scenes rename` (or the VS Code command) so the tool updates all Prev/Next references and database records atomically. Do not rename files by hand.

---

## The @@META Header

Every scene file starts with a metadata block:

```
@@META
Prev: [previous scene filename or None]
Next: [next scene filename or TBD]
@@END
```

### Delimiters
- **`@@META`** marks the start (on its own line)
- **`@@END`** marks the end (on its own line)
- Everything after `@@END` is your scene text

### Minimal Required Fields

Only two fields are required:

| Field | Value | Notes |
|-------|-------|-------|
| `Prev` | Filename of the previous scene, or `None` for the first scene | Strict format check |
| `Next` | Filename of the next scene, or `TBD` if not written yet | Strict format check |

#### `None` vs `TBD` — When to Use Each

| Sentinel | Meaning | When to use |
|----------|---------|-------------|
| `None` | No adjacent scene exists | The **first** scene in the manuscript (`Prev: None`), or the **last** scene in a finished manuscript (`Next: None`) |
| `TBD` | An adjacent scene will exist but isn't written yet | You're mid-draft and the next (or previous) scene hasn't been created yet |

The tool treats both as valid "no pointer" values and skips them during chain validation. Use `None` for permanent boundaries, `TBD` for temporary gaps.

Any other fields you include in the META block are silently ignored — they will not cause errors, but they are not used.

### Example

```
@@META
Prev: 01.02.05_The_negotiation.txt
Next: 01.03.02_Into_the_vault.txt
@@END

The corridor smelled of rust and old stone. Amelia pressed one hand against
the wall, steadying herself as the vertigo came in waves. Forty-seven minutes
until dawn. She had to reach the vault before the wards collapsed entirely.
```

First scene in the project:

```
@@META
Prev: None
Next: 01.01.02_The_upper_sanctum.txt
@@END

Amelia woke to the sound of the ward bell tolling three times.
```

Scene whose next scene isn't written yet:

```
@@META
Prev: 02.04.03_Aftermath.txt
Next: TBD
@@END

George stood at the window for a long time without speaking.
```

---

## The Prev/Next Chain

Prev and Next form a **doubly-linked list** across your scenes. This chain is what lit-critic uses to verify reading order, detect gaps, and ensure continuity context flows correctly.

### Chain Rules

- Each scene's `Next` must equal the following scene's `Prev`
- No two scenes may share the same `Next` value (no forks)
- No scene may be its own ancestor (no cycles)
- Gaps (missing links) are reported as warnings during `knowledge refresh`

### When Inserting a New Scene

If you insert a scene between `scene-A.txt` and `scene-B.txt`:

1. Create the new file, e.g. `scene-A2.txt`, with:
   ```
   @@META
   Prev: scene-A.txt
   Next: scene-B.txt
   @@END
   ```
2. Update `scene-A.txt`: change `Next: scene-B.txt` → `Next: scene-A2.txt`
3. Update `scene-B.txt`: change `Prev: scene-A.txt` → `Prev: scene-A2.txt`
4. Run `knowledge refresh` to validate the updated chain.

### When Renaming a Scene

Use the rename command — **do not rename files by hand**:

```bash
lit-critic scenes rename old-name.txt new-name.txt --project /path/to/project
```

Or in the VS Code extension: right-click the scene → **Rename Scene**.

The rename command atomically:
- Renames the file on disk
- Updates `Prev` / `Next` in the adjacent scene files
- Updates all database records referencing the old filename

### If you already renamed a file by hand

If you renamed a scene file outside the tool (via OS file explorer, git, etc.) and the database now has stale records pointing to the old filename, follow these recovery steps:

1. **Refresh Scenes** — Click the **Refresh Scenes** toolbar button in the VS Code Scenes panel, or run:
   ```bash
   lit-critic scenes refresh --project /path/to/project
   ```
   This makes the tool discover the newly-named file and register it in the database. The scene will reappear in the Scenes tree.

2. **Purge Orphaned Scene References** — In VS Code, open the Command Palette and run **"Literary Critic: Clean Up Stale Scene References"** (`litCritic.purgeOrphanedSceneRefs`). Confirm the prompt. The tool will remove all database rows that still reference the old filename, which no longer exists on disk. It reports how many stale rows were removed.

3. **Run Knowledge Refresh** — The newly-registered scene will have no extracted knowledge yet. Run **Refresh Knowledge** to extract its characters, terms, threads, and timeline entries.

> **Note:** This recovery path restores the scene to the Scenes tree and cleans up stale DB rows, but it cannot automatically reconstruct the `Prev` / `Next` chain links that used the old filename. After purging orphans, check the adjacent scenes' `@@META` headers and update any `Prev` or `Next` values that still reference the old filename.

---


## Auto-Extracted Knowledge

You no longer need to maintain `Cast`, `Threads`, `ContAnchors`, or any other scene-level metadata by hand. This information is extracted automatically from your prose.

After you write or revise a scene, running `knowledge refresh` will:

1. Detect which scenes have changed since the last extraction
2. Send changed scenes to the LLM with your CANON.md as context
3. Extract characters, terms, narrative threads, and timeline entries
4. Store results in the project database

The extracted knowledge is then used automatically during analysis to provide continuity context — just as the old index files were.

See the **[Knowledge Management Guide](index-files.md)** for details on how extraction works, how to review and correct extracted knowledge, and how to use the extraction lock.

---

## Multilingual Scenes

**lit-critic supports scenes in any language.** Your scene text can be in Greek, Japanese, Spanish, Arabic, or 100+ other languages depending on your chosen model. The tool analyzes your prose in its original language and provides English-language feedback.

Your CANON.md and STYLE.md can also be in your novel's language — the tool works seamlessly with multilingual content.

---

## Common Pitfalls

❌ **Forgetting to update Prev/Next when inserting a scene**  
✅ Update both adjacent scenes and run `knowledge refresh` to validate the chain

❌ **Renaming files by hand**  
✅ Use `lit-critic scenes rename` so database records stay in sync. If you already renamed by hand, see [the recovery steps above](#if-you-already-renamed-a-file-by-hand).


❌ **Expecting old-style META fields (Cast, Threads, etc.) to do anything**  
✅ These fields are silently ignored — Refresh Knowledge extracts them from your prose

---

## Stripping @@META for Final Compile

The metadata block is for you and the tool — readers don't see it. Your final compile script should remove everything from `@@META` to `@@END` (inclusive).

---

## See Also

- **[Knowledge Management Guide](index-files.md)** Auto-extraction, CANON.md, STYLE.md, and review workflow
- **[Getting Started](getting-started.md)** Project setup walkthrough
- **[Working with Findings](working-with-findings.md)** Understanding the tool's feedback
