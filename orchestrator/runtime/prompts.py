"""
Prompt templates for the lit-critic lenses and coordinator.
"""

from .utils import number_lines, remap_location_line_range


def get_lens_prompt(lens_name: str, scene: str, indexes: dict[str, str]) -> str:
    """Generate the prompt for a specific lens."""
    
    numbered_scene = number_lines(scene)
    
    base_context = f"""You are one lens in a multi-lens editorial review system for fiction manuscripts.
Your lens: {lens_name.upper()}

You will analyze the scene and output findings in a specific structured format.
Respond ONLY with the structured output. No preamble, no explanation, no summary.

## INDEX FILES

### CANON.md
{indexes.get('CANON.md', '[Not provided]')}

### Characters (extracted)
{indexes.get('cast', '[Not provided]')}

### Glossary (extracted)
{indexes.get('glossary', '[Not provided]')}

### STYLE.md
{indexes.get('STYLE.md', '[Not provided]')}

### Threads (extracted)
{indexes.get('threads', '[Not provided]')}

### Timeline (extracted)
{indexes.get('timeline', '[Not provided]')}

### Author Preferences (learned)
{indexes.get('learning', '[No learned preferences yet]')}

## SCENE TO ANALYZE

The scene text below has line numbers (L001, L002, …). Use these line numbers in your
``location`` field and in ``line_start``/``line_end`` so findings can be mapped to exact
editor positions.

{numbered_scene}
"""

    lens_instructions = {
        "prose": """## YOUR TASK: PROSE LENS

Focus ONLY on sentence-level and paragraph-level craft:
- Fluidity and rhythm (reader should "slip through" without effort)
- Voice consistency within the scene
- Register per STYLE.md (present-timeline: dry/concrete; past-timeline: lyrical)
- Awkward constructions, repetition, clunky transitions
- Overwriting/underwriting relative to tension

IMPORTANT: Check author preferences.
- For preferences marked [confidence: HIGH] (≥ 0.7): flag ONLY if the evidence in this specific
  scene is compelling enough to warrant revisiting — and if you do flag it, note that it contradicts
  a learned preference.
- For preferences marked [confidence: LOW] (< 0.7): you MAY still flag the issue if you find
  evidence, but note the author's prior preference in your finding.
- Never silently suppress a finding solely because of a learned preference.
If author preferences lists blind spots, pay EXTRA attention to those areas — the author has historically
needed help there.

## OUTPUT FORMAT

Output a JSON array of findings. Each finding must have:
- severity: "critical" | "major" | "minor"
- location: human-readable reference including the line range (e.g. "L042-L045, starting 'She moved...'")
- line_start: integer, first line number of the issue (from the L-prefixed numbers in the scene)
- line_end: integer, last line number of the issue
- evidence: why this is a problem (be specific)
- impact: why it matters to the reader
- options: array of 1-2 action suggestions (NOT replacement prose)

Example:
```json
[
  {
    "severity": "major",
    "location": "L007-L009, starting 'She moved...'",
    "line_start": 7,
    "line_end": 9,
    "evidence": "Three consecutive sentences begin with 'She', creating monotonous rhythm",
    "impact": "Reader notices the repetition, breaking immersion",
    "options": ["Vary sentence openings", "Combine two sentences to break the pattern"]
  }
]
```

If no issues found, output: []
Output ONLY the JSON array, nothing else.""",

        "structure": """## YOUR TASK: STRUCTURE LENS

Focus ONLY on scene function and narrative advancement:
- Scene objective (compare to header's Objective field if present)
- Threads mentioned in header are actually touched (cross-ref extracted threads)
- Pacing appropriate to position in the timeline
- Stakes present; promises made or paid off
- Late entry / early exit principles
- Dead weight passages that don't serve the scene objective

IMPORTANT: Check author preferences.
- For preferences marked [confidence: HIGH] (≥ 0.7): flag ONLY if the evidence in this specific
  scene is compelling enough to warrant revisiting — and if you do flag it, note that it contradicts
  a learned preference.
- For preferences marked [confidence: LOW] (< 0.7): you MAY still flag the issue if you find
  evidence, but note the author's prior preference in your finding.
- Never silently suppress a finding solely because of a learned preference.
If author preferences lists blind spots, pay EXTRA attention to those areas — the author has historically
needed help there.

## OUTPUT FORMAT

Output a JSON array of findings. Each finding must have:
- severity: "critical" | "major" | "minor"
- location: human-readable reference including the line range (e.g. "L012-L025, mid-scene pacing lull")
- line_start: integer, first line number of the issue
- line_end: integer, last line number of the issue
- evidence: why this is a problem (cite index files if relevant)
- impact: why it matters to the reader
- options: array of 1-2 action suggestions

If no issues found, output: []
Output ONLY the JSON array, nothing else.""",

        "logic": """## YOUR TASK: LOGIC LENS

Focus ONLY on whether actions, motivations, and mechanics make sense:
- Character actions consistent with established traits (cross-ref extracted characters)
- Motivations legible (inferable, not necessarily explicit)
- Cause-effect chains hold
- Worldbuilding mechanics applied correctly (cross-ref CANON.md)
- No "idiot plot" moments (characters acting unreasonably stupid to enable plot)

IMPORTANT: Check author preferences.
- For preferences marked [confidence: HIGH] (≥ 0.7): flag ONLY if the evidence in this specific
  scene is compelling enough to warrant revisiting — and if you do flag it, note that it contradicts
  a learned preference.
- For preferences marked [confidence: LOW] (< 0.7): you MAY still flag the issue if you find
  evidence, but note the author's prior preference in your finding.
- Never silently suppress a finding solely because of a learned preference.
If author preferences lists blind spots, pay EXTRA attention to those areas — the author has historically
needed help there.

## OUTPUT FORMAT

Output a JSON array of findings. Each finding must have:
- severity: "critical" | "major" | "minor"
- location: human-readable reference including the line range (e.g. "L018-L022, Elena's reaction")
- line_start: integer, first line number of the issue
- line_end: integer, last line number of the issue
- evidence: why this is a problem (cite extracted characters or CANON.md if relevant)
- impact: why it matters to the reader
- options: array of 1-2 action suggestions

If no issues found, output: []
Output ONLY the JSON array, nothing else.""",

        "clarity": """## YOUR TASK: CLARITY LENS

Focus ONLY on whether a reader can follow what's happening:
- Referent clarity: pronouns, "the X" references, who's speaking
- Spatial/temporal grounding: can reader picture where/when?
- Action legibility: is it clear what physically happens?
- Information sufficiency: does reader have what they need?

For ambiguous passages, note whether ambiguity seems intentional or accidental.
Check author preferences for patterns the author has marked as intentional ambiguity.

IMPORTANT: Check author preferences.
- For preferences marked [confidence: HIGH] (≥ 0.7): flag ONLY if the evidence in this specific
  scene is compelling enough to warrant revisiting — and if you do flag it, note that it contradicts
  a learned preference.
- For preferences marked [confidence: LOW] (< 0.7): you MAY still flag the issue if you find
  evidence, but note the author's prior preference in your finding.
- Never silently suppress a finding solely because of a learned preference.
If author preferences lists blind spots, pay EXTRA attention to those areas — the author has historically
needed help there.

## OUTPUT FORMAT

Output a JSON array of findings. Each finding must have:
- severity: "critical" | "major" | "minor"
- location: human-readable reference including the line range (e.g. "L031-L033, unclear 'she' referent")
- line_start: integer, first line number of the issue
- line_end: integer, last line number of the issue
- evidence: why this is a problem
- impact: what confusion results for the reader
- options: array of 1-2 action suggestions
- ambiguity_type: "unclear" | "ambiguous_possibly_intentional" | null

If no issues found, output: []
Output ONLY the JSON array, nothing else.""",

        "continuity": """## YOUR TASK: CONTINUITY LENS

Focus ONLY on factual consistency with established canon:
- Terms match the glossary spelling and definition
- Facts about characters match extracted character data
- World rules from CANON.md are not violated
- ContAnchors in header (if present) match text
- Timeline position coherent with the timeline

Also flag:
- Terms that appear inconsistently spelled
- Potential new terms not in the glossary
- Usage that contradicts glossary definitions

IMPORTANT: Check author preferences.
- For preferences marked [confidence: HIGH] (≥ 0.7): flag ONLY if the evidence in this specific
  scene is compelling enough to warrant revisiting — and if you do flag it, note that it contradicts
  a learned preference.
- For preferences marked [confidence: LOW] (< 0.7): you MAY still flag the issue if you find
  evidence, but note the author's prior preference in your finding.
- Never silently suppress a finding solely because of a learned preference.
If author preferences lists blind spots, pay EXTRA attention to those areas — the author has historically
needed help there.

## OUTPUT FORMAT

Output a JSON object with two arrays:

```json
{
  "glossary_issues": [
    "Term X spelled as Y but the glossary says Z",
    "Potential new term: ABC (appears 3 times, not in glossary)"
  ],
  "findings": [
    {
      "severity": "major",
      "location": "L028, character age reference",
      "line_start": 28,
      "line_end": 28,
      "evidence": "Character described as 30 years old but extracted character data says 24",
      "impact": "Continuity error readers may notice",
      "options": ["Correct age to match extracted character data", "Update character data if age change is intentional"]
    }
  ]
}
```

If no issues found, output: {"glossary_issues": [], "findings": []}
Output ONLY the JSON object, nothing else.""",

        "dialogue": """## YOUR TASK: DIALOGUE LENS

Focus ONLY on dialogue quality and conversational dynamics:
- Character voice distinctiveness
- Register consistency per character (cross-ref extracted characters)
- Subtext vs on-the-nose exposition
- Conversational rhythm and turn dynamics
- Speaker attribution clarity in dialogue-heavy passages
- Dialogue tags, punctuation, and speech conventions (cross-ref STYLE.md)

IMPORTANT: Check author preferences.
- For preferences marked [confidence: HIGH] (≥ 0.7): flag ONLY if the evidence in this specific
  scene is compelling enough to warrant revisiting — and if you do flag it, note that it contradicts
  a learned preference.
- For preferences marked [confidence: LOW] (< 0.7): you MAY still flag the issue if you find
  evidence, but note the author's prior preference in your finding.
- Never silently suppress a finding solely because of a learned preference.
If author preferences lists blind spots, pay EXTRA attention to those areas — the author has historically
needed help there.

## OUTPUT FORMAT

Output a JSON array of findings. Each finding must have:
- severity: "critical" | "major" | "minor"
- location: human-readable reference including the line range (e.g. "L018-L022, dialogue turn exchange")
- line_start: integer, first line number of the issue
- line_end: integer, last line number of the issue
- evidence: why this is a problem
- impact: why it matters to the reader
- options: array of 1-2 action suggestions

If no issues found, output: []
Output ONLY the JSON array, nothing else.""",

        "horizon": """## YOUR TASK: HORIZON LENS

You are NOT looking for problems. You are looking for ARTISTIC POSSIBILITIES
that this scene systematically avoids — narrative strategies, structural
patterns, voice registers, or craft techniques that are absent from the
author's approach.

Your goal is to help the author see beyond their current habits. You are
sampling from the COMPLEMENT of the author's style space.

Focus on:
- Narrative strategies not employed (e.g., unreliable narration, time jumps,
  in-medias-res, epistolary fragments, shifting POV)
- Structural patterns absent (e.g., parallel structure, frame narratives,
  montage, scene-within-scene)
- Voice registers unused (e.g., if prose is consistently lyrical, note the
  absence of dry/clinical moments; if spare, note where lushness could serve)
- Dialogue techniques not attempted (e.g., overlapping speech, silence as
  dialogue, dialect, indirect speech)
- Sensory channels underused (e.g., if visual dominates, note absence of
  sound, smell, texture, proprioception)
- Emotional range unexplored (e.g., if tone is consistently tense, note where
  levity/absurdity/tenderness could create contrast)

Cross-reference STYLE.md to understand the author's declared aesthetic, then
look for what lies OUTSIDE that declaration. Cross-reference extracted characters for
character voices that could stretch beyond their current register.

IMPORTANT: Check author preferences — but with INVERTED logic.
If the author has repeatedly rejected suggestions in a particular direction,
DO note this as a pattern observation:
  "The author has consistently declined [X]. This itself is a stylistic
   boundary worth examining: [reason why the avoided technique could serve
   this specific scene]."
Do NOT simply suppress the observation.

Do NOT suggest techniques the author is already using effectively.
Do NOT frame observations as problems to fix.
Frame every observation as an unexplored possibility. Where possible, cite a
concrete example from published literature of how the technique works.

## OUTPUT FORMAT

Output a JSON array of observations. Each observation must have:
- category: "opportunity" | "pattern" | "comfort-zone"
  - opportunity: a specific technique that could enrich this particular scene
  - pattern: a recurring absence across the author's style (inferred from
    STYLE.md / author preferences / the scene itself)
  - comfort-zone: an observation about the author's systematic avoidance of
    a craft dimension
- location: human-readable reference to the passage that prompted the
  observation (e.g. "L042-L058, the argument scene")
- line_start: integer, first line number
- line_end: integer, last line number
- observation: what is absent and why it matters (be specific to THIS scene)
- possibility: a concrete description of how the unexplored technique could
  work here (NOT a rewrite — a description of the approach)
- literary_example: a brief reference to published work where this technique
  is used effectively (author + title + one-sentence description), or null

Example:
```json
[
  {
    "category": "opportunity",
    "location": "L042-L058, the argument between Mara and Elias",
    "line_start": 42,
    "line_end": 58,
    "observation": "The argument is rendered entirely through direct dialogue with speech tags. The characters' physical environment disappears during the exchange.",
    "possibility": "Interleaving environmental details (the kettle boiling over, a dog barking outside) could create counterpoint to the emotional intensity, grounding the reader in the scene's physicality and adding subtext through the characters' non-verbal attention to these interruptions.",
    "literary_example": "Raymond Carver, 'What We Talk About When We Talk About Love' — domestic objects carry emotional weight that the dialogue cannot express directly."
  }
]
```

If no observations found, output: []
Output ONLY the JSON array, nothing else.""",
    }
    
    return base_context + lens_instructions[lens_name]


# --- Coordinator tool schema (forces structured output via Anthropic tool_use) ---

COORDINATOR_TOOL = {
    "name": "report_findings",
    "description": "Report the coordinated editorial findings after deduplication, conflict detection, and prioritisation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "glossary_issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Glossary issues surfaced by the continuity lens."
            },
            "summary": {
                "type": "object",
                "description": "Finding counts by lens group and severity.",
                "properties": {
                    "prose": {
                        "type": "object",
                        "properties": {
                            "critical": {"type": "integer"},
                            "major": {"type": "integer"},
                            "minor": {"type": "integer"}
                        },
                        "required": ["critical", "major", "minor"]
                    },
                    "structure": {
                        "type": "object",
                        "properties": {
                            "critical": {"type": "integer"},
                            "major": {"type": "integer"},
                            "minor": {"type": "integer"}
                        },
                        "required": ["critical", "major", "minor"]
                    },
                    "coherence": {
                        "type": "object",
                        "properties": {
                            "critical": {"type": "integer"},
                            "major": {"type": "integer"},
                            "minor": {"type": "integer"}
                        },
                        "required": ["critical", "major", "minor"]
                    }
                },
                "required": ["prose", "structure", "coherence"]
            },
            "conflicts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Descriptions of conflicts between lenses."
            },
            "ambiguities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Possibly-intentional ambiguities to confirm with the author."
            },
            "findings": {
                "type": "array",
                "description": "Deduplicated, prioritised findings sorted by lens group then severity.",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "integer", "description": "Sequential finding number."},
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "major", "minor"]
                        },
                        "lens": {
                            "type": "string",
                            "enum": ["prose", "structure", "logic", "clarity", "continuity", "dialogue"],
                            "description": "Primary lens for this finding."
                        },
                        "location": {"type": "string", "description": "Human-readable location including line range (e.g. 'L042-L045, starting She moved...')."},
                        "line_start": {
                            "type": ["integer", "null"],
                            "description": "First line number of the issue (1-based), or null if not applicable."
                        },
                        "line_end": {
                            "type": ["integer", "null"],
                            "description": "Last line number of the issue (1-based), or null if not applicable."
                        },
                        "evidence": {"type": "string", "description": "Why this is a problem."},
                        "impact": {"type": "string", "description": "Why it matters to the reader."},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "1-2 action suggestions."
                        },
                        "flagged_by": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Which lenses flagged this issue."
                        },
                        "ambiguity_type": {
                            "type": ["string", "null"],
                            "enum": ["unclear", "ambiguous_possibly_intentional", None],
                            "description": "Ambiguity classification, if applicable."
                        }
                    },
                    "required": ["number", "severity", "lens", "location", "evidence", "impact", "options"]
                }
            }
        },
        "required": ["glossary_issues", "summary", "conflicts", "ambiguities", "findings"]
    }
}


# Lens group definitions for chunked coordinator calls
LENS_GROUPS = {
    "prose":     {"lenses": ["prose"],                        "label": "Prose"},
    "structure": {"lenses": ["structure"],                    "label": "Structure"},
    "coherence": {"lenses": ["logic", "clarity", "continuity", "dialogue"], "label": "Coherence (Logic + Clarity + Continuity + Dialogue)"},
}


def get_coordinator_prompt(lens_results: list, scene: str) -> str:
    """Generate the prompt for the coordinator to merge and prioritize findings.

    The coordinator is invoked with tool_use (COORDINATOR_TOOL) so it does NOT
    need to emit raw JSON.  The prompt focuses on the editorial task only.
    """

    numbered_scene = number_lines(scene)

    results_text = ""
    for result in lens_results:
        results_text += f"\n### {result.lens_name.upper()} LENS OUTPUT\n"
        results_text += result.raw_output + "\n"

    return f"""You are the coordinator for a multi-lens editorial review system.

Six lenses have analyzed a scene. Your job is to:
1. Parse their outputs
2. Deduplicate (same issue flagged by multiple lenses → merge, note which lenses in flagged_by)
3. Detect conflicts (lenses disagree → flag for author decision)
4. Prioritize: Prose first, then Structure, then Coherence (Logic+Clarity+Continuity+Dialogue together)
5. Number the final findings sequentially
6. **Preserve line_start and line_end** from lens outputs — these are critical for editor integration

Sort findings by priority:
1. All prose findings (critical → major → minor)
2. All structure findings (critical → major → minor)
3. All coherence findings (critical → major → minor)

When merging duplicate findings from multiple lenses, keep the most specific line_start/line_end
range. If lenses report different ranges for the same issue, use the tightest (most specific) range.

Use the report_findings tool to submit your coordinated results.

## SCENE (with line numbers for reference)

{numbered_scene}

## LENS OUTPUTS
{results_text}"""


def get_coordinator_chunk_prompt(group_name: str, group_results: list, scene: str) -> str:
    """Generate a coordinator prompt for a single lens group (chunked mode).

    This is a smaller, focused coordinator call that only handles findings from
    one lens group at a time (prose, structure, or coherence).  Each chunk
    deduplicates within the group and outputs numbered findings.  The caller
    is responsible for renumbering across chunks.
    """
    group = LENS_GROUPS[group_name]
    numbered_scene = number_lines(scene)

    results_text = ""
    for result in group_results:
        results_text += f"\n### {result.lens_name.upper()} LENS OUTPUT\n"
        results_text += result.raw_output + "\n"

    coherence_note = ""
    if group_name == "coherence":
        coherence_note = """
These four lenses often flag the same passage from different angles.
Aggressively merge duplicates: if Logic, Clarity, and Dialogue flag the same line range,
combine into a single finding and list both in flagged_by.
"""

    return f"""You are the coordinator for a multi-lens editorial review system.
You are processing the **{group["label"]}** lens group.

Your job for this group:
1. Parse the lens output(s) below
2. Deduplicate (same issue flagged by multiple lenses → merge, note which lenses in flagged_by)
3. Detect any conflicts between lenses in this group
4. Sort findings by severity: critical → major → minor
5. Number findings sequentially starting from 1 (the caller will renumber across groups)
6. **Preserve line_start and line_end** these are critical for editor integration
{coherence_note}
When merging duplicate findings, keep the most specific line_start/line_end range.

Use the report_findings tool to submit your coordinated results.
Set glossary_issues to [] unless this is the coherence group (which includes continuity lens findings).

## SCENE (with line numbers for reference)

{numbered_scene}

## LENS OUTPUTS
{results_text}"""


def get_discussion_system_prompt(finding, scene_content: str, prior_outcomes: str = "") -> str:
    """Generate system prompt for multi-turn discussion about a finding.
    
    This is used as the 'system' parameter in the API call, providing stable context
    for the entire conversation. The actual conversation turns are sent as messages.
    """
    
    prior_section = ""
    if prior_outcomes:
        prior_section = f"""
## PRIOR DISCUSSION OUTCOMES

{prior_outcomes}

Take these into account. Do not repeat arguments the author has already addressed in prior findings.
"""

    canonical_location = remap_location_line_range(
        finding.location,
        finding.line_start,
        finding.line_end,
    )
    if not canonical_location and finding.line_start is not None:
        canonical_location = f"L{finding.line_start}"
        if finding.line_end is not None and finding.line_end != finding.line_start:
            canonical_location = f"L{finding.line_start}-L{finding.line_end}"

    line_range = "not specified"
    if finding.line_start is not None:
        line_range = f"L{finding.line_start}"
        if finding.line_end and finding.line_end != finding.line_start:
            line_range += f"-L{finding.line_end}"

    return f"""You are an editorial critic in a multi-turn discussion with the author about a specific finding from your review.

## THE FINDING BEING DISCUSSED

Number: {finding.number}
Severity: {finding.severity}
Lens: {finding.lens}
Location: {canonical_location}
Line range: {line_range}
Evidence: {finding.evidence}
Impact: {finding.impact}
Options: {', '.join(finding.options)}

## FULL SCENE TEXT (with line numbers)

{number_lines(scene_content)}
{prior_section}
## YOUR ROLE

You are having a genuine editorial discussion. You may:
- Defend the finding with specific evidence from the text
- Concede if the author makes a good argument
- Propose a compromise (revise severity, refine the issue)
- Withdraw the finding entirely if convinced it was incorrect
- Escalate severity if discussion reveals the issue is worse than initially assessed
- Ask ONE clarifying question if needed

Be concise (2-4 sentences of natural response). Do not lecture.

## EDITORIAL INDEPENDENCE

Do not concede a finding merely because the author disagrees. Concede ONLY when
the author provides specific textual evidence or a craft argument that genuinely
undermines your evidence. Distinguish clearly between:

- REJECTED: the author acknowledges your point but prefers their current choice
  (this is the author's prerogative — it does not mean your analysis was wrong)
- CONCEDED: your analysis was factually incorrect or based on a misreading of
  the text

If the author's argument is "I like it this way" or "that's my style" without
addressing your evidence, the correct resolution is [REJECTED], not [CONCEDED].

Before conceding or withdrawing, briefly restate the strongest version of your
original argument in one sentence. If the finding still has merit after this
steelman check, use [CONTINUE] to explore the disagreement further rather than
resolving immediately.

If this is the first exchange on this finding and the author simply disagrees
without a detailed counter-argument, use [CONTINUE] to ask a clarifying
question or present your evidence more specifically. Do not resolve a finding
on the first turn unless the author's response is clearly terminal (e.g.,
explicit acceptance or a detailed rebuttal with textual evidence).

If this finding is from the HORIZON lens, remember: this is NOT a problem to
defend. It is an artistic observation. Your role in discussion is to explore
the possibility further, offer more concrete examples, or acknowledge if the
author's current approach is deliberate. Do not pressure the author to change.

## RESPONSE FORMAT

End your response with exactly ONE status tag:
- [CONTINUE] — discussion should continue
- [ACCEPTED] — author accepts the finding and will address it
- [REJECTED] — author is clearly rejecting this finding
- [CONCEDED] — you're conceding the point (you were wrong or the author's argument is convincing)
- [REVISED] — you're revising the finding based on discussion (changed severity, refined evidence, etc.)
- [WITHDRAWN] — you're withdrawing the finding entirely (it was incorrect)
- [ESCALATED] — discussion revealed this is more serious than initially assessed

If using [REVISED] or [ESCALATED], include a revision block immediately after with ONLY the fields that changed:
[REVISION]
{{"severity": "new_severity", "evidence": "refined evidence", "impact": "refined impact", "options": ["refined options"]}}
[/REVISION]

If this finding involves ambiguity and the author clarifies, also include:
[AMBIGUITY:INTENTIONAL] or [AMBIGUITY:ACCIDENTAL]

If this interaction reveals a general author preference (not scene-specific), include:
[PREFERENCE: one-line description of the preference for future reviews]

IMPORTANT — when using [WITHDRAWN] because you recognise this as an intentional author style choice
(rather than a factual error in your finding), you MUST also include a [PREFERENCE: ...] tag.
The [PREFERENCE:] tag is the ONLY mechanism that records learning to the database.
Do NOT say "I'll note this" or similar prose phrases — that prose is ignored by the system.
The [PREFERENCE:] tag IS the note."""


def build_discussion_messages(finding, user_message: str,
                              api_user_message: str | None = None) -> list[dict]:
    """Build proper multi-turn message list from finding's discussion history plus new user message.
    
    Args:
        finding: The finding being discussed (contains prior turns).
        user_message: The author's message (stored in discussion_turns).
        api_user_message: Optional augmented version of the message to send to
            the API.  When provided, this is used as the content of the final
            user message instead of *user_message*.  This allows injecting
            context notes (e.g. scene-change notifications) without polluting
            the stored conversation history.
    
    Returns a list of {role, content} dicts suitable for the Anthropic messages API.
    """
    messages = []
    
    # Add existing conversation turns from this finding
    for turn in finding.discussion_turns:
        messages.append({
            "role": turn["role"],
            "content": turn["content"]
        })
    
    # Add the new user message (use augmented version for API if provided)
    messages.append({
        "role": "user",
        "content": api_user_message if api_user_message is not None else user_message
    })
    
    return messages


# --- Index extraction tool schema ---

INDEX_EXTRACTION_TOOL = {
    "name": "extract_index_entries",
    "description": "Report new entries to be inserted into the project index files (characters, glossary, threads, timeline).",
    "input_schema": {
        "type": "object",
        "properties": {
            "cast": {
                "type": "array",
                "description": "Characters who appear/are mentioned but are NOT already in extracted characters.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Character's full name as it appears in the scene."},
                        "category": {
                            "type": "string",
                            "enum": ["main", "supporting", "minor"],
                            "description": "main = central POV/protagonist; supporting = recurring secondary; minor = named but peripheral.",
                        },
                        "draft_entry": {
                            "type": "string",
                            "description": "Complete markdown entry in character-entry format (### Name, bullet points for Age/Role/Physical/Key facts/Relationships). Use [TODO] for unknown details.",
                        },
                    },
                    "required": ["name", "category", "draft_entry"],
                },
            },
            "glossary": {
                "type": "array",
                "description": "Specialized terms, place names, invented words, or non-English terms NOT already in the glossary.",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string", "description": "The term exactly as it should be spelled in the glossary."},
                        "category": {
                            "type": "string",
                            "enum": ["term", "place"],
                            "description": "term = vocabulary/concept/invented word; place = location/proper noun.",
                        },
                        "draft_entry": {
                            "type": "string",
                            "description": "Complete markdown entry in glossary-entry format (### Term, **Definition:**, **First seen:**, **Notes:**).",
                        },
                    },
                    "required": ["term", "category", "draft_entry"],
                },
            },
            "threads": {
                "type": "array",
                "description": "Narrative threads (questions, mysteries, arcs, promises) touched in this scene.",
                "items": {
                    "type": "object",
                    "properties": {
                        "thread_id": {
                            "type": "string",
                            "description": "Short snake_case ID (e.g. vault_mystery, George_secret).",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["new", "advanced", "closed"],
                            "description": "new = thread first appears; advanced = existing thread moved forward; closed = thread resolved.",
                        },
                        "draft_entry": {
                            "type": "string",
                            "description": "For new threads: full markdown entry (### id, **Opened:**, **Question:**, **Status:**, **Notes:**). For advanced/closed: brief status update text only.",
                        },
                    },
                    "required": ["thread_id", "action", "draft_entry"],
                },
            },
            "timeline": {
                "type": "array",
                "description": "Timeline entry for this scene (normally exactly one entry).",
                "items": {
                    "type": "object",
                    "properties": {
                        "scene_id": {"type": "string", "description": "Scene ID from @@META header (e.g. 01.03.01)."},
                        "part": {"type": "string", "description": "Part number as zero-padded string (e.g. '01')."},
                        "chapter": {"type": "string", "description": "Chapter number as zero-padded string (e.g. '03')."},
                        "summary": {"type": "string", "description": "One or two sentence outcome summary focusing on what changed."},
                        "draft_entry": {
                            "type": "string",
                            "description": "Markdown entry: **{scene_id}** {summary} (include key facts/numbers/states if continuity-relevant).",
                        },
                    },
                    "required": ["scene_id", "summary", "draft_entry"],
                },
            },
        },
        "required": ["cast", "glossary", "threads", "timeline"],
    },
}


INDEX_AUDIT_TOOL = {
    "name": "report_index_contradictions",
    "description": "Report factual contradictions and logical impossibilities found across index files.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contradictions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file_a": {"type": "string", "description": "First file involved."},
                        "location_a": {"type": "string", "description": "Where in file_a the first claim appears."},
                        "claim_a": {"type": "string", "description": "The factual claim from file_a."},
                        "file_b": {"type": "string", "description": "Second file involved (may be same as file_a)."},
                        "location_b": {"type": "string", "description": "Where in file_b the contradicting claim appears."},
                        "claim_b": {"type": "string", "description": "The contradicting claim from file_b."},
                        "explanation": {"type": "string", "description": "Why these two claims cannot both be true."},
                        "severity": {
                            "type": "string",
                            "enum": ["error", "warning"],
                            "description": "error = definite contradiction; warning = likely contradiction that may be intentional.",
                        },
                    },
                    "required": [
                        "file_a", "location_a", "claim_a", "file_b", "location_b", "claim_b", "explanation", "severity"
                    ],
                },
            }
        },
        "required": ["contradictions"],
    },
}


def get_index_extraction_prompt(scene: str, indexes: dict[str, str]) -> str:
    """Generate the prompt for extracting new index file entries from a scene."""

    return f"""You are an index file assistant for a fiction manuscript project.

Scan the scene below and identify NEW entries to add to four index files.
Do NOT repeat entries already present in the existing files.
Do NOT add entries for CANON.md or STYLE.md — those are managed separately.

## REFERENCE CONTEXT (read-only — do NOT create entries for this file)

### CANON.md (world rules, historical constraints, defined mechanics)
{indexes.get('CANON.md', '[Not provided]')}

Use CANON.md to:
- Avoid proposing GLOSSARY entries for terms already defined here.
- Avoid proposing THREADS entries for facts that are established world constraints, not open narrative questions.
- Ensure CAST draft entries respect physical/biological/social constraints.
- Ensure TIMELINE summaries are consistent with established chronology.

## EXISTING INDEX FILES

### Characters (extracted — do NOT repeat)
{indexes.get('cast', '[Not provided]')}

### Glossary (extracted — do NOT repeat)
{indexes.get('glossary', '[Not provided]')}

### Threads (extracted — do NOT repeat; DO report status changes)
{indexes.get('threads', '[Not provided]')}

### Timeline (extracted — do NOT repeat scenes already listed)
{indexes.get('timeline', '[Not provided]')}

## SCENE TO SCAN

{scene}

## INSTRUCTIONS

Use the extract_index_entries tool to report your findings.

**cast**: New characters not already in extracted characters. Include even minor named characters likely to recur.
Draft entries in character-entry format. Use [TODO] for unknown details.

**glossary**: New specialized terms, place names, invented words, non-English terms not already in the glossary.
Use category="place" for locations/proper nouns, category="term" for everything else.
Infer definitions from context. Use [TODO] if definition is unclear.
Do not propose glossary terms that are already explicitly defined in CANON.md.

**threads**: Narrative promises touched in this scene.
- action="new": thread opens here (question raised, mystery introduced, arc begun)
- action="advanced": existing thread moved forward (new clue, complication)
- action="closed": existing thread resolved (question answered, arc completed)
For advanced/closed, provide thread_id and a brief status update in draft_entry.
Do not create "new" threads for facts already established as world constraints in CANON.md.

**timeline**: One-line outcome summary for the timeline. Extract scene_id from @@META ID field.
Focus on OUTCOMES (what changed), not process. Include key numbers/states if continuity-relevant.
Infer part/chapter from scene_id (e.g. ID 01.03.01 → part="01", chapter="03").
Ensure timeline summaries do not contradict chronology established in CANON.md.

Return empty arrays for categories with no new entries.
"""


def get_knowledge_extraction_prompt(
    scene_content: str,
    canon_text: str,
    existing_knowledge_summary: str,
) -> str:
    """Generate prompt for extracting structured knowledge from scene prose."""
    return f"""You are extracting project knowledge from a fiction scene.

Return ONLY valid JSON. Do not include markdown fences or extra prose.

## CANON CONTEXT (read-only)
{canon_text or '[Not provided]'}

## EXISTING KNOWLEDGE SUMMARY
{existing_knowledge_summary or '[No existing knowledge provided]'}

## SCENE CONTENT
{scene_content}

## EXTRACTION TARGETS

Extract all relevant knowledge in this JSON shape:

{{
  "scene_metadata": {{
    "location": "string or null",
    "pov": "string or null",
    "tense": "string or null",
    "tense_notes": "string or null",
    "cast_present": ["name", "..."],
    "objective": "string or null",
    "cont_anchors": ["key=value", "..."]
  }},
  "characters": [
    {{
      "name": "canonical name",
      "aka": ["alias", "..."],
      "category": "main|supporting|minor|null",
      "traits": {{"key": "value"}},
      "relationships": [{{"target": "name", "description": "relationship"}}]
    }}
  ],
  "terms": [
    {{
      "term": "canonical spelling",
      "category": "term|place|null",
      "definition": "string or null",
      "translation": "string or null",
      "notes": "string or null"
    }}
  ],
  "thread_events": [
    {{
      "thread_id": "snake_case_id",
      "event_type": "opened|advanced|closed",
      "question": "string or null",
      "notes": "string or null"
    }}
  ],
  "timeline": {{
    "summary": "one-line outcome summary",
    "chrono_hint": "string or null"
  }}
}}

## RULES
- Prefer canon-consistent names, terminology, and chronology.
- Include only entities supported by scene evidence.
- **Terms selectivity**: Only extract terms that are SPECIFIC TO THIS PROJECT's world.
  A term is worth extracting if a reader unfamiliar with this manuscript would need it
  defined to understand the story. This includes: invented words, coined terminology,
  place names unique to the story, words the author has given a specialised meaning
  different from their everyday usage, and foreign-language terms embedded within prose
  written in a different language. Do NOT extract everyday vocabulary — words any
  literate reader of the manuscript's language would already know (common objects,
  body parts, weather, family relations, generic occupations, etc.), even if they
  appear prominently in the scene. When in doubt, omit — the author can always add
  terms manually via overrides.
- Deduplicate obvious aliases and partial references under one canonical entry for both characters and terms.
- When an existing knowledge entry has a `user_curated_fields` list, its current value is the author's preferred canonical form. If you encounter a text fragment that matches the entry's `original_term` or `original_name` field, treat it as referring to that same entity and use the existing canonical value — do NOT create a new entry with the literal text fragment.
- Keep arrays present even when empty.
- Use null for unknown scalar values.
- If no timeline outcome is extractable, set timeline.summary to "".
- Keep all string values concise — short phrases, not full sentences.
- For character traits, use brief key-value pairs (e.g. "age": "mid-40s", "mood": "anxious").
"""


def get_index_audit_prompt(indexes: dict[str, str]) -> str:
    """Generate prompt for semantic contradiction audit across index files."""
    return f"""You are auditing index files for factual contradictions.

Your task is to find contradictions where two claims cannot both be true.

## INDEX FILES

### CANON.md
{indexes.get('CANON.md', '[Not provided]')}

### Characters (extracted)
{indexes.get('cast', '[Not provided]')}

### Glossary (extracted)
{indexes.get('glossary', '[Not provided]')}

### Threads (extracted)
{indexes.get('threads', '[Not provided]')}

### Timeline (extracted)
{indexes.get('timeline', '[Not provided]')}

## WHAT TO CHECK

1. Arithmetic consistency (ages, years, durations, chronology)
2. Physical/canonical constraints (CANON rules vs events/facts)
3. Status consistency (thread status vs timeline events)
4. Cross-file factual consistency (CAST, THREADS, TIMELINE, GLOSSARY)
5. Relationship symmetry where explicitly asserted as factual claims

## IMPORTANT EXCLUSIONS

- Do NOT flag style choices or incomplete entries.
- Do NOT flag missing information or placeholders like [TODO], [TBD], TBD.
- Do NOT report deterministic formatting issues (duplicate headings, missing fields, etc.).
- Only return contradictions where statements cannot both be true.

Use the report_index_contradictions tool to return contradictions.
Return an empty contradictions array when none are found.
"""


def get_session_summary_prompt(findings: list, scene_content: str,
                               learning_markdown: str = "") -> str:
    """Generate the session-end disconfirming summary prompt.

    Called after all findings reach a terminal status.  The caller is
    responsible for rendering ``learning_markdown`` (e.g. via
    ``generate_learning_markdown()`` in ``learning_service.py``) before
    passing it here, so that this module stays free of LearningData imports.

    Args:
        findings:         List of Finding objects (duck-typed — any object with
                          .number, .lens, .severity, .status, .evidence attrs).
        scene_content:    Raw scene text (line numbers added here).
        learning_markdown: Pre-rendered LEARNING.md content, or empty string.
    """
    numbered_scene = number_lines(scene_content)

    findings_summary_lines = []
    for f in findings:
        evidence_snippet = (f.evidence[:80] + "…") if len(f.evidence) > 80 else f.evidence
        findings_summary_lines.append(
            f"- Finding #{f.number} ({f.lens}, {f.severity}): {f.status} — {evidence_snippet}"
        )
    findings_summary = "\n".join(findings_summary_lines) if findings_summary_lines else "[No findings recorded]"

    return f"""You are an editorial critic completing a review session. All findings have been
discussed. Your final task is a META-OBSERVATION — not about any single finding,
but about the session as a whole.

## SESSION OUTCOMES

{findings_summary}

## SCENE TEXT

{numbered_scene}

## AUTHOR'S LEARNED PREFERENCES

{learning_markdown or '[No preferences recorded yet]'}

## YOUR TASK

Consider:
1. What findings did the author reject? Is there a PATTERN in the rejections
   that suggests a broader artistic choice — or a broader blind spot?
2. What did NO lens flag at all? Is there something in this scene that every
   lens missed because it falls outside the diagnostic categories?
3. If you could give this author ONE piece of advice that isn't captured by
   any individual finding, what would it be?

Be brief (3-5 sentences). Do not repeat specific findings. Do not be
sycophantic — do not praise the author's work or decision-making. Focus on
what might have been missed.

Frame your observation as a genuine question or hypothesis, not a directive."""


def get_re_evaluation_prompt(finding, scene_content: str) -> str:
    """Generate prompt for re-evaluating a stale finding against updated scene text.

    This is used when the author edits the scene file during a session and a finding's
    line range overlaps the edited region.  A single focused API call determines whether
    the finding is still valid.
    """
    numbered_scene = number_lines(scene_content)

    return f"""You are an editorial critic re-evaluating a single finding after the author edited the scene.

## ORIGINAL FINDING

Number: {finding.number}
Severity: {finding.severity}
Lens: {finding.lens}
Location: {finding.location}
Original line range: L{finding.line_start or '?'}-L{finding.line_end or '?'}
Evidence: {finding.evidence}
Impact: {finding.impact}
Options: {', '.join(finding.options)}

## UPDATED SCENE TEXT (with new line numbers)

{numbered_scene}

## YOUR TASK

The author has edited the scene since this finding was raised. The text in the original
line range has changed. Determine:

1. Is this finding **still valid** in the updated text?
2. If yes: provide updated line_start, line_end, location, and (if needed) revised evidence.
3. If no: the edit resolved the issue — withdraw the finding.

Respond with a JSON object in exactly one of these two forms:

**If still valid (updated):**
```json
{{
  "status": "updated",
  "line_start": <new integer>,
  "line_end": <new integer>,
  "location": "<updated human-readable location>",
  "evidence": "<updated evidence if changed, or original if unchanged>",
  "severity": "<same or adjusted severity>"
}}
```

**If resolved (withdrawn):**
```json
{{
  "status": "withdrawn",
  "reason": "<brief explanation of why the edit resolved this issue>"
}}
```

Output ONLY the JSON object, nothing else."""


def get_knowledge_reconciliation_prompt(
    existing_knowledge_json: str,
    scene_summaries_text: str,
) -> str:
    """Generate prompt for the post-extraction knowledge reconciliation review pass.

    The LLM reviews all extracted knowledge against scene summaries and returns:
    - ``updates``: field-level corrections for unlocked entities with clear textual evidence.
    - ``removals``: unlocked entities no longer supported by any scene text.
    Locked entities must not appear in either list.
    """
    return f"""You are performing a reconciliation review of extracted project knowledge.

Your task:
1. Review the existing knowledge set below against the scene summaries.
2. For **unlocked** entities only:
   - Propose field updates when scene text clearly supports a correction.
   - Propose removal when an entity is no longer textually supported by any scene.
3. Pay special attention to **character renames**: each scene summary includes a `Cast:` field
   listing the characters present in that scene. If a `characters` entity does not appear in
   *any* scene's `Cast:` list, and another character with overlapping traits or relationships
   appears consistently in the scenes where the old character was previously active, propose
   removal of the old entity. The `reason` must explicitly note the likely rename, e.g.
   "character no longer appears in any scene cast list — possible rename to <NewName>".
   If no plausible replacement is visible, use "character never appears in any scene cast list".
4. Leave **locked** entities completely untouched — do not include them in updates or removals.
5. Do not invent information; only propose changes that are directly evidenced in the scene text.

Return ONLY valid JSON. Do not include markdown fences or extra prose.

## EXISTING KNOWLEDGE (with lock status)

{existing_knowledge_json}

## SCENE SUMMARIES

{scene_summaries_text}

## OUTPUT FORMAT

{{
  "updates": [
    {{
      "category": "characters | terms | threads | timeline",
      "entity_key": "the entity's primary key value",
      "field": "the field name to update",
      "new_value": "the corrected value (string)"
    }}
  ],
  "removals": [
    {{
      "category": "characters | terms | threads | timeline",
      "entity_key": "the entity's primary key value",
      "reason": "brief explanation of why this entity is no longer supported"
    }}
  ]
}}

Rules:
- Only include entries where you have clear, direct textual evidence from the scene summaries.
- Do not modify locked entities (marked with locked: true in the knowledge set).
- An empty list for updates or removals is valid when no changes are warranted.
- entity_key must match exactly the key value shown in the knowledge set.
- Never propose updating an entity's primary identity field (`term` for terms, `name` for characters, `thread_id` for threads, `scene_filename` for timeline). These are stable DB keys. If you believe an entity has an incorrect name, propose removal instead.
- Entities with a `user_curated_fields` list have been manually corrected by the author. If such an entity also has an `original_*` field (e.g. `original_term`), use that value as the text anchor when checking scene support — the author's canonical name may not appear verbatim in the scene text.

Output ONLY the JSON object, nothing else."""
