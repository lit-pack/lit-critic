# Tips and FAQ

Practical guidance for day-to-day use.

---

## Interface

lit-critic is used through the **VS Code extension**. The extension connects to a local REST API server (`lit-critic-server.py`) which you start automatically or manually. All review data is stored in your project folder in `.lit-critic.db`.

---

## Quick vs. deep mode

Every review runs all seven lenses. The difference between modes is the thoroughness of the checking.

| Mode | Good for | Cost |
|------|----------|------|
| **quick** | Regular drafting passes, frequent reviews | Lower |
| **deep** | Polished scenes, final review before submission | Higher |

Start with **quick** while you're actively drafting. Switch to **deep** when a scene feels close to finished and you want a more thorough look.

**In VS Code:** use the **Config** button in the Sessions toolbar before starting a session.

---

## Cost

lit-critic uses your own API key and you pay your AI provider directly. There's no subscription or markup.

Typical cost for a 3–4 page scene:
- **Quick mode:** a few cents
- **Deep mode:** somewhat more, depending on the model configured

The exact cost depends on the AI model you've chosen and how much discussion you do. Discussion adds cost per message.

To reduce costs: run quick mode for drafting passes. Use **Skip Minor** during review to move through the session faster.

---

## Everything is saved automatically

You don't need to save manually. Every action — accepting a finding, rejecting one, typing a discussion message, navigating to the next finding — is saved to your project the moment it happens.

If you close VS Code mid-review, your progress is fully preserved. The next time you start an analysis, the tool will offer to resume the session where you left off.

---

## Editing your scene during a review

Yes, you can edit your scene while a review is in progress. lit-critic detects the change, adjusts line numbers for all findings, and re-evaluates any findings that are now potentially stale. You don't need to restart the session.

In VS Code, this happens automatically. Use **Review Current Finding** in the Command Palette to manually re-check the current finding after making an edit.

---

## Resuming a session

**VS Code:** press `Ctrl+Shift+L` — the tool automatically offers to resume an active session.

If you've moved your project folder to a new location or different computer, the tool will detect the mismatch and prompt you for the new path. You can correct it and resume without losing any progress.

---

## Multi-scene reviews

To analyze several consecutive scenes in one session — useful for arc-level continuity checks across chapter boundaries:

**VS Code:** when the scene selector opens, add multiple scenes in reading order.

---

## Multilingual novels

lit-critic supports novels written in any language your chosen AI model handles. Your scenes, CANON.md, and STYLE.md can all be in the same non-English language. The tool analyzes your prose in its original language and provides findings in English.

---

## Frequently asked questions

**Do I have to act on every finding?**  
No. Reject what doesn't apply. The learning system tracks your rejections and calibrates future reviews accordingly.

**What if the AI is wrong about a continuity issue?**  
Discuss it. Explain the context the AI missed. It will either withdraw the finding or ask you to verify it against CANON.md or your extracted knowledge.

**Can I use lit-critic without VS Code?**  
The VS Code extension is the primary interface. The underlying REST API (`/api/*`) is open and documented in `docs/technical/api-reference.md` for integrators who want to build other clients.

**Should I commit `.lit-critic.db` to Git?**  
No. Add `.lit-critic.db` to your `.gitignore`. It contains your review history and grows as you use the tool. You don't want it in version control.

**Does lit-critic send my scenes to a third party?**  
Your scenes are sent to the AI provider you've configured (Anthropic or OpenAI) for analysis. They leave your machine only to reach those APIs. The lit-critic code itself runs locally.

**What's LEARNING.md for?**  
It's a human-readable export of your preference history. You can read it, share it with a co-author, or edit it manually. Future reviews load your preferences automatically from the project; LEARNING.md is the export format.

---

## See also

- **[Setting Up Your Project](setting-up-your-project.md)** — installation and project structure
- **[Your First Review](your-first-review.md)** — end-to-end walkthrough
- **[Understanding Findings](understanding-findings.md)** — accept, reject, discuss
- **[The Learning System](learning-system.md)** — how preferences are tracked over time
