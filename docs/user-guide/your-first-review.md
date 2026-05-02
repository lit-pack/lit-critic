# Your First Review

This guide walks through an actual review session from start to finish using VS Code, the primary interface.

---

## Before you start

Make sure you have:
- lit-critic installed (`pip install -r requirements.txt` in the lit-critic folder)
- Your API key set in your environment
- Your novel project folder with `CANON.md`, `STYLE.md`, and at least one scene file

If any of those aren't in place yet, start with **[Setting Up Your Project](setting-up-your-project.md)**.

---

## In VS Code (recommended)

### 1. Install the extension

Package the extension as a VSIX file and install it:

```bash
cd vscode-extension
npm install
npm run package
code --install-extension lit-critic-*.vsix --force
```

After installation, reload VS Code.

### 2. Open your novel project

Open the folder that contains your `CANON.md` — not the lit-critic installation folder, your actual novel folder. VS Code detects the presence of `CANON.md` and activates lit-critic automatically. You'll see the **lit-critic** icon appear in the Activity Bar on the left.

> **If your novel project is outside the lit-critic installation folder**, you need to tell the extension where lit-critic lives. Open VS Code Settings (`Ctrl+,`), search for `litCritic.repoPath`, and set it to the full path of your lit-critic installation directory (the folder containing `lit-critic-server.py`).

### 3. Start the analysis

Press **`Ctrl+Shift+L`** (or open the Command Palette with `Ctrl+Shift+P` and type "lit-critic: Analyze").

A **scene selector** appears. Choose one or more consecutive scenes you want reviewed. For your first time, pick just one.

Click **Analyze**. The status bar at the bottom of VS Code shows a progress indicator. Behind the scenes, seven lenses are running in parallel — this usually takes 30–90 seconds for a typical scene.

### 4. The first finding appears

When analysis completes, the **Discussion Panel** opens on the right side of your editor. The first finding is displayed:

```
Finding #1 — Major — Prose

Lines 42–45

Evidence: "She walked across the room and picked up the glass and looked 
at it and set it back down without drinking."

Impact: Four coordinated clauses with "and" flatten the rhythm and 
slow the scene's momentum at a moment that calls for urgency.

Suggestion: Consider varying the sentence structure — perhaps a short 
declarative followed by a fragment.
```

The finding has:
- **Severity** (Critical, Major, or Minor)
- **Lens** (which of the seven found it)
- **Line range** in your scene
- **Evidence** — the exact text
- **Impact** — why it matters to the reader
- **Suggestion** — a direction, never a rewrite

At the same time, a squiggly underline appears on those lines in your scene file.

### 5. Respond to the finding

You have four choices:

**Accept** — You agree with the observation and plan to address it. The underline disappears. The finding is marked accepted.

**Reject** — You disagree, or the issue is intentional. Optionally type a brief reason ("Intentional rhythm — these coordinated clauses mirror her exhaustion"). The finding is dismissed.

**Discuss** — You type a message in the Discussion Panel and debate it with the AI. It may revise, hold its ground, or withdraw the finding based on the argument you make. The conversation is saved.

**Skip** — Move on without deciding. The finding stays pending. You can come back to it.

### 6. Continue through all findings

After each response, the next finding loads automatically. Work through them at your own pace. You can close VS Code at any point — everything is saved instantly. When you reopen the project, run `lit-critic: Analyze` again and it will offer to resume where you left off.

### 7. At the end of the session

When all findings have been addressed, lit-critic generates a **session summary** — a brief meta-observation about patterns it noticed in your accept/reject decisions, and things every lens may have missed. This appears at the end of the Discussion Panel. It's read-only, not interactive (by design: adding an accept/reject mechanism to the summary would invite the same AI agreeableness the summary is meant to counteract).

---

## Choosing an analysis mode

| Mode | What it means | When to use it |
|------|---------------|---------------|
| **quick** | Full 7-lens analysis, faster and less expensive | Regular drafting passes |
| **deep** | Full 7-lens analysis, more thorough | Polished scenes before final review |

The difference is which AI model handles the detailed checking work. Both modes run all seven lenses. Start with **quick** to get a sense of the tool, then use **deep** when it matters more.

---

## What to do with the findings

Not every finding deserves action. A typical session might produce 8–15 findings. You might accept 4, reject 3 (because they misunderstand your intent), discuss and resolve 2, and skip 1 to think about it later.

That pattern is healthy. The tool is not infallible. It doesn't know your full vision for the scene. When it's wrong, tell it why — and it will either concede or push back with a better argument.

See **[Understanding Findings](understanding-findings.md)** for a fuller guide to what each finding contains and how to respond effectively.

---

## After your first session

Run **Refresh Knowledge** from the Knowledge view toolbar in VS Code. This extracts characters, terms, narrative threads, and timeline entries from your scene and stores them. Future reviews will use this knowledge to catch continuity issues across scenes.

See **[Knowledge and Continuity](knowledge-and-continuity.md)** for details on how this works.
