# Arline v1.2.1 — Character Rails & Scene Dynamics

Character Rails are generation-only steering for character expression and scene dynamics. They are intentionally separate from canon, Memory evidence, Timeline history, and accepted state.

The core rule is:

> A rail describes how Arline should realize an interaction now; it does not assert that the interaction already happened or permanently change who a character is.

## Why rails exist

A plain language-model prompt tends to collapse several different concerns into one string: who a character is, what they currently feel or know, what the user wants them to express, how quickly the scene should move, and what counts as a natural stopping point.

v1.2.1 separates those concerns. The Memory Query Engine supplies scoped character/world evidence; Character Rails supply temporary creative intent; the writer combines both.

Conceptually:

```text
Canonical character/world state
            +
Current temporal / relationship context
            +
Character Rail (generation-only intent)
            ↓
      Scene Dynamics
            ↓
          Writer
```

A rail seed is semantic by default. Arline may rewrite it to fit the character. Use `literal` only when the wording itself must be preserved.

## Commands

### `/mono`

Character-aware monologue/expression for one character.

```text
/mono @vian "ihhh malu banget tau"
```

Defaults to private internal thought. The seed means “express this intent as Vian would naturally think it,” not “copy this sentence exactly.”

Audible delivery changes the channel to speech:

```text
/mono @vian whisper "malu banget"
/mono @vian mutter "kesel dari tadi"
/mono @vian spoken "aku pengen bilang sesuatu"
```

Force private thought explicitly with:

```text
/mono @vian internal "jangan sampai dia sadar"
```

An internal rail is private. Another character must not learn it merely because the writer can see it.

### `/dia`

Character-aware multi-character interaction.

```text
/dia @vian@fano "main game"
```

This is **not** an alternating-turn generator and does not mean `Vian → Fano → Vian → Fano`.

Arline may naturally use:

- one or several consecutive utterances from the same character;
- interruptions;
- actions and gestures;
- meaningful silence/non-response;
- non-lexical vocalization;
- POV-authorized internal thought;
- changes in initiative as emotion and relationship state change.

For example, a normally talkative character may become terse while sulking, while another character carries most of the conversation. Another character may become more talkative when angry. The rail describes the topic/goal; canonical character evidence controls the realization.

Compact participant syntax is supported:

```text
/dia @vian@fano slow "main game"
```

and spaced mentions are equivalent:

```text
/dia @vian @fano slow "main game"
```

### `/ambience`

Controls temporary sensory and atmospheric emphasis without creating persistent world facts.

```text
/ambience slow "late-night rain, dim apartment, distant traffic and AC hum"
```

Ambience may guide soundscape, lighting, background motion, sensory density, and paragraph rhythm. It must not silently invent persistent facts that contradict the World Bible or active scene.

### `/intimacy`

Scene-level intimacy steering using the same character-aware beat/pacing system as every other interaction.

```text
/intimacy @vian solo slow "vulnerability and quiet aftermath"
```

```text
/intimacy @vian@fano slow "reconciliation and emotional vulnerability"
```

A single participant or the `solo` modifier selects solo mode. Intimacy remains a scene intent, not proof that an event already happened. Persistent consequences arise only from generated/accepted prose through the normal extractor/review/Memory path.

The shared engine may use speech, internal thought, physical action, silence, ambience, non-lexical vocalization, POV constraints, and aftermath. It does not require a separate character model or separate Memory system.

## Shared modifiers

### Pacing

Supported values:

```text
auto | immediate | fast | natural | slow | lingering
```

Pacing controls **meaningful intermediate state/reaction beats**, not filler word count.

Conceptually:

```text
immediate / fast
setup → core interaction → reaction → resolution

slow / lingering
setup → anticipation → reaction → pause → processing
      → changed response → further interaction → resolution → aftermath
```

A slow scene can still be concise. It simply should not teleport over the intermediate reactions that make the scene feel slow.

### Intensity

```text
auto | low | medium | high
```

Intensity is separate from pacing. A scene may be slow and high-intensity, or fast and low-intensity.

### Intensity curve

```text
curve=auto
curve=flat
curve=rising
curve=falling
curve=wave
curve=spike
```

The curve controls how intensity changes over the rail rather than how long the rail is.

### Length

```text
length=auto
length=short
length=medium
length=long
```

Length is a soft output-shape hint. It is not a dialogue-turn quota.

### Termination

By default a rail stops at a natural mini-resolution:

```text
termination = natural_resolution
```

A target may be supplied with `until=`:

```text
/dia @vian@fano slow until="the invitation receives a meaningful response" "main game"
```

`until=` is a generation boundary, not permission to violate canonical personality, knowledge, relationship state, or physical constraints just to force the requested outcome.

### Literal wording

```text
/mono @vian literal "Ihhh, malu banget tau."
```

Without `literal`, the text is a semantic seed. With `literal`, the writer should preserve the wording when the surrounding canon permits it.

## Expression model

Rails share a small set of expression channels instead of creating a new engine for every kind of scene:

```text
INTERNAL      private thought
SPEECH        lexical audible expression
VOCALIZATION  non-lexical audible expression
ACTION        physical/nonverbal behavior
SILENCE       meaningful lack of response
AMBIENCE      environmental sensory layer
```

Delivery is orthogonal to channel. For example, `whisper`, `murmur`, and `mutter` are deliveries of audible speech, not private thoughts.

This is why `/dia` can naturally contain an internal thought, a pause, several lines from one speaker, an action, and then a quiet reply without pretending each item is a fixed dialogue turn.

## Character-aware retrieval

A rail request routes through the ordinary Memory Query Engine as `STORY_CONTINUE`. Character names are resolved against Library identity families and world/branch variants. The structured lane can contribute:

- shared character identity/personality data;
- variant summary and attributes;
- character voice metadata;
- current/temporal state;
- first-class relationship data;
- relevant events and open story threads;
- Manuscript/chat FTS evidence;
- optional BGE-M3 dense recall when enabled.

The hard Scope Gate still runs before fusion. A rail therefore does not bypass branch, story-time, world-time, chat-fork, trust, or POV boundaries.

## Memory and canon isolation

Raw rail command lines are removed from semantic analysis and chat Memory evidence indexing.

For example:

```text
/dia @vian@fano "marriage"
```

does **not** mean:

```text
Vian and Fano discussed marriage.   # not established
```

The writer may generate such a discussion. If the user accepts that generated prose, the normal Structure Extractor can later propose events, state changes, or knowledge changes with provenance and review.

The direction is intentionally one-way:

```text
Rail command
   ↓
Writer steering only
   ↓
Generated prose
   ↓
User review / acceptance
   ↓
Extractor proposals
   ↓
Possible Memory / Timeline / canon change
```

A rail command itself never commits canon.

## Temporal interaction

v1.2.1 can query temporal state on two independent axes:

- story/discourse order;
- comparable fictional world time.

Timeline events with accepted/canon `state_patch` data can be projected into rebuildable temporal intervals. The Timeline remains authoritative history; intervals are derived caches.

ISO dates/times and numeric fictional-time axes can be ordered. Opaque labels such as `Day Ten` and `Day Two` are not lexically sorted because doing so would invent chronology. Exact opaque-label equality is still usable.

If a non-Timeline authoritative source already controls the same temporal state key, automatic Timeline projection abstains for that key and reports a diagnostic instead of overwriting the stronger source.

## Current v1.2.1 boundary

The first v1.2.1 implementation provides the rail grammar, writer contract, character/relationship retrieval, temporal dual-axis foundation, Timeline state projection, hybrid routing, and isolation guarantees.

It intentionally does not yet implement a second autonomous dialogue model or deterministic prose choreography. The generative writer remains responsible for natural prose; Arline supplies scoped evidence and a stable scene-dynamics contract.
