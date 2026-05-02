# Setting Up Your Project

This guide walks you through everything you need to get lit-critic running with your novel.

---

## What you need

**Python 3.10 or newer.** Check what you have:

```
python --version
```

If you need to install it: [python.org/downloads](https://www.python.org/downloads/)

**An API key from at least one provider:**

| Provider | Models | Where to get a key |
|----------|--------|-------------------|
| Anthropic | Claude | [anthropic.com](https://www.anthropic.com) |
| OpenAI | GPT | [platform.openai.com](https://platform.openai.com) |

Set your key as an environment variable:

**Windows:**
```
setx ANTHROPIC_API_KEY "your-key-here"
```

**macOS / Linux:**
```
export ANTHROPIC_API_KEY="your-key-here"
```

*(Add the `export` line to your `.bashrc` or `.zshrc` to make it permanent.)*

---

## Installing lit-critic

```bash
git clone https://github.com/lit-pack/lit-critic.git
cd lit-critic
pip install -r requirements.txt
```

That's the complete installation. lit-critic runs locally — there's nothing to sign up for beyond the API key.

---

## Your novel project folder

lit-critic keeps your novel project completely separate from its own installation. You point it at your novel folder when you run a review.

Your project folder needs this structure:

```
my-novel/
├── CANON.md        ← World rules (you write this)
├── STYLE.md        ← Prose conventions (you write this)
└── text/
    ├── 01.01.01_opening.txt
    └── 01.01.02_the_sanctum.txt
```

### CANON.md

This is where you declare the immutable rules of your fictional world: magic systems, physical laws, social constraints, historical facts. lit-critic checks every scene against CANON.md and flags violations.

Start simple — you can build it up as you write:

```markdown
# Canon

## Magic System
- Magic requires blood contact with runestones
- Sanctuaries block all magic within their wards

## Biological Constraints
- Hematocrit below 25% causes loss of consciousness
```

### STYLE.md

This is where you record your prose conventions: tense choices, dialogue tag preferences, punctuation habits, anything you want to apply consistently.

```markdown
# Style Guide

## Tense
Past tense for present-time narrative.
Present tense for flashbacks (inverted convention).

## Dialogue Tags
Use "said" as the default neutral tag.
```

Both files can be empty when you start. They get more useful as you add to them.

> **Characters, terms, narrative threads, and timeline entries** are tracked automatically — you don't maintain separate files for them. After you write scenes, running "Refresh Knowledge" extracts them from your prose and stores them in the project database. See **[Knowledge and Continuity](knowledge-and-continuity.md)**.

---

## Your scene files

Each scene is a separate text file. Every scene file starts with a small metadata block called `@@META`.

### The @@META header

The metadata block tells lit-critic how your scenes connect to each other in reading order. It only needs two things: which scene comes before this one, and which comes after.

```
@@META
Prev: 01.01.01_opening.txt
Next: 01.01.03_the_vault.txt
@@END

The corridor smelled of rust and old stone. Amelia pressed one hand against
the wall, steadying herself as the vertigo came in waves...
```

- **`Prev:`** the filename of the previous scene, or `None` for your first scene
- **`Next:`** the filename of the next scene, or `TBD` if you haven't written it yet
- Everything after `@@END` is your prose

That's all the metadata you need. Everything else (characters, timeline, threads) is extracted automatically.

### Naming your scene files

lit-critic uses the filename as the scene's permanent identifier. Name your files however you like, as long as you're consistent:

```
01.01.01_opening.txt
01.01.02_the_sanctum.txt
ch03-showdown.txt
```

**Important:** If you need to rename a scene file later, use the rename command rather than renaming it in your file explorer — otherwise lit-critic loses track of it. In VS Code, right-click the scene in the Inputs view → **Rename Scene**.

### Inserting a new scene

If you insert a scene between two existing scenes, update the `Prev` and `Next` fields in the adjacent scenes:

1. Create the new scene file with correct `Prev` and `Next`
2. Update the previous scene's `Next` to point to your new file
3. Update the next scene's `Prev` to point to your new file

Then run "Refresh Knowledge" to validate the chain.

---

## Multilingual novels

Your scene files, CANON.md, and STYLE.md can all be written in any language your chosen AI model supports — Greek, Japanese, Spanish, Arabic, Chinese, and 100+ more. lit-critic analyzes your prose in its original language and provides feedback in English.

---

## Troubleshooting

**"No API key provided"**  
Make sure you set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in your environment. On Windows, open a new terminal window after running `setx` for the variable to take effect.

**"Missing CANON.md"**  
The tool warns but continues. Create an empty `CANON.md` in your project folder to start, even if it has no content yet.

**Analysis takes too long**  
Choose "quick" mode for faster reviews during drafting passes. Reserve "deep" mode for polished scenes.

---

## Next step

→ **[Your First Review](your-first-review.md)** — walk through an actual analysis session
