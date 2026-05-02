# Knowledge and Continuity

lit-critic checks your scenes for consistency with your world — catching things like "Amelia's hematocrit was 32% in the previous scene, but 28% here without explanation" or "the vault was established as sealed in CANON.md, but a character enters it freely." To do this, it maintains a **knowledge base** for your project.

---

## Two kinds of knowledge

| Kind | What it covers | How it's maintained |
|------|---------------|---------------------|
| **Author-authored** | World rules, prose conventions | You write and update CANON.md and STYLE.md by hand |
| **Auto-extracted** | Characters, terms, narrative threads, timeline | Extracted from your prose automatically |

You never maintain separate files for characters, terms, or timeline. The tool reads your scenes and builds that knowledge for you.

---

## CANON.md — world rules

CANON.md is where you declare the inviolable rules of your world: the physics of your magic system, biological constraints, historical facts, social laws. The tool reads CANON.md during every analysis and checks each scene against it.

**When to update it:** whenever you establish a new rule in a scene that must never be violated.

```markdown
# Canon

## Magic System
- Magic requires direct contact with a runestone
- Sanctuaries block all magic within their wards
- Ward strength degrades 5% per day without maintenance

## Biological Constraints
- Hematocrit below 25% causes loss of consciousness
```

Start minimal. Add rules as your world solidifies around you.

---

## STYLE.md — prose conventions

STYLE.md records your conscious prose choices: tense conventions, dialogue tag preferences, punctuation habits, terminology decisions. The tool reads it and flags deviations from your declared style.

**When to update it:** whenever you settle on a convention you want applied consistently.

```markdown
# Style Guide

## Tense
Past tense for present-time narrative.
Present tense for flashbacks (inverted convention).

## Dialogue Tags
Use "said" as the default neutral tag.

## Em Dashes
Use em dashes (—) for abrupt interruptions. No spaces around the dash.
```

---

## Auto-extracted knowledge

The following categories are built automatically from your prose:

| Category | What it tracks |
|----------|---------------|
| **Cast** | Character names, aliases, traits, relationships |
| **Glossary** | Specialized terms, definitions, usage notes |
| **Threads** | Narrative threads opened, advanced, or closed per scene |
| **Timeline** | Scene-level location, POV, objective, continuity anchors |

### How it works

After you write or revise scenes, run **Refresh Knowledge**:

- **VS Code:** click the Refresh Knowledge button in the Knowledge view toolbar
- **Terminal:** `python -m cli knowledge refresh --project ~/my-novel/`

The tool identifies which scenes have changed since the last extraction, sends them to the AI model, and stores the results in the project database. Unchanged scenes are skipped — extraction only processes what's new.

The next time you analyze a scene, all of this extracted knowledge is loaded as context, enabling continuity and logic checks across your whole manuscript.

---

## Reviewing what was extracted

Open the **Knowledge** view in VS Code (click the lit-critic icon in the Activity Bar, then select Knowledge). Entries are grouped by category. Each entry shows its current state:

| State | Icon | Label | Color | What to do |
|---|---|---|---|---|
| Normal | property | — | default | No action needed |
| Overridden | property | `overridden` | teal | Review; reset if extraction corrected itself |
| Locked | lock | `locked` | gold | Unlock to allow future updates |
| Stale | ⚠ | `stale` | red | Run **Refresh Knowledge** |
| Flagged | ⚠ | `flagged` | orange | Use inline Keep or Delete buttons |

**Stale** entries appear when a scene you've edited hasn't been re-extracted yet. Run Refresh Knowledge to clear them.

**Flagged** entries appear after the reconciliation pass — the tool's second look at the extracted data to check for entries no longer supported by the text. For each flagged entry, choose:
- **Keep & Lock** — keep the entry and prevent future updates to it
- **Keep Only** — dismiss the flag without locking
- **Delete** — remove the entry permanently

---

## Correcting extraction errors

Extraction is reliable but not perfect. If the tool gets something wrong — a character's trait misidentified, a term with an incorrect definition — you correct it with an **override** rather than editing the raw data.

**In VS Code:** click an entity in the Knowledge tree, or right-click → **Open Knowledge Review Panel**. The panel shows the extracted value and your override side by side. You can edit individual fields and save them.

Overrides survive re-extraction: if a scene is processed again, the new extraction result is stored, but your correction stays on top of it.

To remove a correction (if the extraction later fixes itself): right-click the entity → **Reset Knowledge Override**.

---

## Locking entries

If you've reviewed an entry and are satisfied with it, you can **lock** it to prevent **Refresh Knowledge** from overwriting it in future runs:

- Right-click an entity in the Knowledge tree → **Toggle Knowledge Lock**

Locked entries are skipped during extraction and reconciliation. Unlock them the same way when you want the tool to update them again.

Locking is also available for whole scenes. If you've reviewed all the knowledge from a scene and want to freeze it: in VS Code, right-click the scene in the Inputs view → **Lock Scene for Extraction**.

---

## Frequently asked questions

**Do I need CAST.md, GLOSSARY.md, THREADS.md, or TIMELINE.md files?**  
No. Those files are no longer used. Characters, terms, threads, and timeline entries are extracted automatically and stored in the project database.

**What if extraction misses something important?**  
Add an override for the missing information. You can also add it to CANON.md if it's a world rule that should always be in context during analysis.

**How often should I run Refresh Knowledge?**  
After any writing session where you changed scenes. Extraction is incremental, so it only processes what changed.

**What if CANON.md changes?**  
All knowledge entries are marked stale because the world rules have changed. Run Refresh Knowledge to re-extract everything against the new canon.

**Can I export the extracted knowledge?**  
Yes: `python -m cli knowledge export --project ~/my-novel/` produces a markdown file. This is read-only — it doesn't affect the database, it's just for your reference.

---

## See also

- **[Setting Up Your Project](setting-up-your-project.md)** — CANON.md, STYLE.md, and scene file format
- **[Understanding Findings](understanding-findings.md)** — How knowledge feeds into continuity and logic findings
- **[Templates](templates/)** — Starter files for CANON.md and STYLE.md
