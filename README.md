# lit-critic

**An AI editorial assistant that respects your voice and argues back.**

lit-critic reads your novel scenes and checks them against the rules you've written — your world's logic, your prose style, your characters, your timeline. It never generates prose or imposes external standards. When it finds something worth discussing, it presents it as a finding. You can accept, reject, or push back. If you push back, it holds its ground unless you give it a real reason to concede.

<p align="center">
  <img width="90%" src="assets/overview.png">
</p>

---

## What lit-critic does

It reads each scene through seven editorial lenses and presents findings — concrete observations with line references, evidence from your text, and brief conceptual guidance. You review them one by one and decide.

| Lens | What it checks |
|------|---------------|
| **Prose** | Rhythm, fluidity, voice consistency |
| **Structure** | Pacing, scene objectives, narrative threads |
| **Logic** | Character motivation, cause-and-effect, world consistency |
| **Clarity** | Reference resolution, grounding, legibility |
| **Continuity** | Facts, terms, timeline coherence |
| **Dialogue** | Character voice, register, subtext, turn dynamics |
| **Horizon** | What the scene systematically avoids — artistic possibilities not taken |

The last lens is different. It doesn't look for problems. It surfaces craft techniques, structural patterns, and voice registers that the scene never tries — not as criticism, but as an invitation to consider what roads aren't being taken.

## What lit-critic doesn't do

- **Write prose for you.** Not a word. Not a sentence.
- **Rewrite your sentences.** At most, two or three example words to illustrate a concept.
- **Impose external standards.** It checks your rules — CANON.md, STYLE.md — not some generic "good writing" rubric.
- **Capitulate easily.** When you push back, it examines the argument before conceding. It distinguishes "I don't like this finding" from "this finding is factually wrong." This is deliberate — [read why](docs/user-guide/sycophancy.md).

---

## 📚 For Novel Authors

### Quick Start

**1. Install**

```bash
git clone https://github.com/lit-pack/lit-critic.git
cd lit-critic
pip install -r requirements.txt
```

**2. Get an API key**

You need at least one:
- **Anthropic** (Claude): [anthropic.com](https://www.anthropic.com) → set `ANTHROPIC_API_KEY`
- **OpenAI** (GPT): [platform.openai.com](https://platform.openai.com) → set `OPENAI_API_KEY`

**Windows:**
```
setx ANTHROPIC_API_KEY "your-key-here"
```

**macOS / Linux:**
```
export ANTHROPIC_API_KEY="your-key-here"
```

**3. Set up your novel project**

Your project folder needs two files you write by hand, and a folder for your scenes:

```
my-novel/
├── CANON.md        ← World rules: magic systems, physical laws, constraints
├── STYLE.md        ← Prose conventions: tense, dialogue tags, punctuation
└── text/
    └── 01.01.01_scene.txt
```

Characters, terms, narrative threads, and timeline entries are extracted automatically from your prose — you don't maintain separate files for them.

**4. Open your project in VS Code**

The VS Code extension is the primary interface. It gives you squiggly underlines directly in your scene files, a sidebar for findings, and a discussion panel — all without leaving your editor. Install the extension, then open the folder containing your `CANON.md`.

**5. Run your first review (VS Code)**

1. Open your novel project folder in VS Code — the folder containing `CANON.md`
2. Press **`Ctrl+Shift+L`** or run `lit-critic: Analyze` from the Command Palette
3. Select one or more consecutive scenes
4. Wait ~30–90 seconds for the seven lenses to run in parallel
5. Review findings in the Discussion Panel — accept, reject, or debate each one

See the **[Setup Guide](docs/user-guide/setting-up-your-project.md)** and **[Your First Review](docs/user-guide/your-first-review.md)** for a full walkthrough.

---

### How it knows your world

lit-critic maintains a knowledge base for your project in a hidden file (`.lit-critic.db`) in your project folder. It holds:

- **CANON.md** and **STYLE.md** — you write and update these by hand
- **Characters, terms, threads, timeline** — extracted automatically from your prose when you run "Refresh Knowledge"

You review what was extracted, correct anything wrong, and the tool uses it all as context during analysis. The knowledge base accumulates quietly in the background. You don't have to maintain it manually. See **[Knowledge and Continuity](docs/user-guide/knowledge-and-continuity.md)**.

---

### Learning your preferences

Over time, lit-critic learns what kinds of findings you accept and reject. If you consistently dismiss a certain type of observation, it becomes quieter on that topic. If you consistently agree with a pattern it notices, it pays extra attention to it. You can export a snapshot of your preferences to `LEARNING.md` at any time.

See **[The Learning System](docs/user-guide/learning-system.md)**.

---

### Multilingual support

Your novel can be in **any language** your chosen AI model supports — Greek, Japanese, Spanish, Arabic, Chinese, and 100+ more. lit-critic analyzes your prose in its original language and provides feedback in English. Your CANON.md and STYLE.md can also be in your novel's language.

---

### 📖 Full Author Documentation

- **[Setting Up Your Project](docs/user-guide/setting-up-your-project.md)** — Installation, project structure, scene files
- **[Your First Review](docs/user-guide/your-first-review.md)** — Walkthrough for VS Code
- **[Understanding Findings](docs/user-guide/understanding-findings.md)** — What findings look like and how to respond
- **[Knowledge and Continuity](docs/user-guide/knowledge-and-continuity.md)** — CANON.md, STYLE.md, and auto-extracted knowledge
- **[The Learning System](docs/user-guide/learning-system.md)** — How the tool adapts to your style over time
- **[Why This Isn't Sycophantic](docs/user-guide/sycophancy.md)** — Why AI tends to agree with you and how we resist that
- **[Tips and FAQ](docs/user-guide/tips-and-faq.md)** — Practical guidance, cost, troubleshooting

---

## 🔧 For Developers

lit-critic is organized as three explicit layers:

- **Core (`core/`)** — stateless reasoning endpoints (`/v1/analyze`, `/v1/discuss`, `/v1/re-evaluate-finding`)
- **Platform (`orchestrator/`)** — session lifecycle, persistence, orchestration, retry/backoff
- **API server (`web/`)** and **VS Code extension (`vscode-extension/`)** — thin client layers over Platform

Session state, findings, and learning data are persisted in a per-project **SQLite database** (`.lit-critic.db`).

### Developer Quick Start

```bash
npm run install                    # Install Python + TypeScript dependencies
npm test                           # Run all tests (Python + TypeScript)
npm run release:check              # SemVer/compatibility checks
npm run hooks:install              # Install local git hooks
python lit-critic-server.py --reload  # API server with auto-reload
cd vscode-extension && code .      # VS Code extension development (then F5)
```

### 📖 Full Technical Documentation

- **[Architecture Guide](docs/technical/architecture.md)** — System design and layer responsibilities
- **[API Reference](docs/technical/api-reference.md)** — Complete REST API documentation
- **[Installation Guide](docs/technical/installation.md)** — Developer setup
- **[Testing Guide](docs/technical/testing.md)** — Running and writing tests
- **[Versioning & Compatibility](docs/technical/versioning.md)** — SemVer policy and local enforcement
- **[Release Checklist](docs/technical/release-checklist.md)** — Step-by-step no-CI release workflow

---

## Requirements

- **Python 3.10+**
- **At least one API key:** `ANTHROPIC_API_KEY` (Claude) or `OPENAI_API_KEY` (GPT), or both
- **Node.js 16+** *(for VS Code extension development only)*

---

## Beyond Fiction

If there is something generally useful in this repository, it is probably not the code itself but the **cooperative model** between human author and LLM that underpins it.

lit-critic is built around a deliberate division of labour:

- **The human**: creativity, intent, taste, and final judgement.
- **The LLM**: adherence to rules, cross-referencing of large context, and structured analysis.

Neither party does the other's job. The author never asks the LLM to write prose; the LLM never overrides the author's creative decisions. Instead, the author defines the rules (CANON.md, STYLE.md) and the LLM audits against them — plus auto-extracted knowledge about characters, terms, threads, and timeline — presenting findings for the author to accept, reject, or debate. The result is a feedback loop where each side contributes what it does best.

This pattern is not specific to fiction. The same principle — *human sets the rules and owns the creative/strategic decisions; LLM audits, cross-checks, and surfaces issues* — could apply to other domains: technical writing, legal document review, or even poetry. (A "lyric-critic" that checks your sonnets against your own declared meter and rhyme scheme? Mostly a joke but only mostly.)

---

## Support

> This is a personal tool that I maintain for my own novel-writing workflow. I'm sharing it publicly in case it's useful to others.

It started as a weekend exercise to test claude-opus-4-6 functionality. Later, all Anthropic and OpenAI models contributed code, tests, and documentation.

I intend to continue working on it for my personal use, but please note:
- **No support provided** — use at your own risk
- **Not accepting contributions** — I implement features as I need them
- **Issues/PRs will most probably be ignored** — I fix what affects me
- **Fork and adapt** — feel free to fork and adapt it to your needs

---

## License

MIT License. See the [LICENSE](LICENSE) file for details.

Copyright (c) 2026 Alexis Argyris
