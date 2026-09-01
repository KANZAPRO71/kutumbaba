# Kontrak Antar-Modul (v1)

Interface ringkas — align dengan [ARCHITECTURE.md](ARCHITECTURE.md) v1.  
Detail behavior: [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) §18 (BDV).

---

## SessionManager

```
create_session(user_id, persona_id, channel) → Session
get_context(session_id) → SessionContext
record_turn(session_id, turn_result) → void
close_session(session_id) → void
```

---

## ConversationEngine

```
handle_turn(TurnRequest) → TurnResult
```

Satu entry point. Linear pipeline — no logic duplication.

---

## BehaviorEngine ★

```
decide(BehaviorInput, arc: ConversationArc) → BehaviorDirectiveVector
feedback(output, bdv, arc) → (QualitySnapshot, ConversationArc)
```

**Owns:** pressure, OAL, stability, CQF, CPS.  
**Calls:** arc (read in decide, write via returned arc in feedback).  
**Must NOT import:** llm, memory.

```yaml
BehaviorInput:
  message: Message
  history: Turn[]
  session: SessionContext
  policy_signals: PolicySignal[]
  plugin_signals: PluginSignal[]
```

---

## ArcEngine

```
load(session_id) → ConversationArc
save(session_id, arc) → void
apply_decay(arc) → ConversationArc
```

**Owns:** trajectory state, decay formulas (BEHAVIOR §8.6).  
**Must NOT:** decide speak/silence, store user facts.

---

## CoherenceEngine

```
bind(CoherenceInput) → VoiceDirective
verify_voice(output, directive) → VoiceCoherenceResult
update_anchor(anchor, directive, output) → IdentityAnchor
```

**Owns:** identity stability, expression merge, single voice constraint.  
**Must NOT:** change BDV speak/question_budget, run OAL, safety blocks.  
Detail: [COHERENCE.md](COHERENCE.md)

---

## PersonalityEngine

```
apply(profile, bdv: BehaviorDirectiveVector, arc_hint?, execution_profile) → ExpressionConstraints
```

Maps BDV tone/engagement → LLM-safe expression. **Never** changes BDV.  
Detail: [PERSONALITY.md](PERSONALITY.md)

---

## PolicyEngine

```
load_policy_context(session, persona, plugins) → PolicyContext
get_tier0_signals(context, input) → PolicySignal[]
pre_check(input, bdv, memory, context) → PolicyConstraints
post_check(draft, constraints, voice_directive) → PolicyResult
```

**Owns:** safety, forbidden content, compliance, Tier-0 `must_respond` signals.  
**Must NOT:** re-decide BDV, tone, OAL, CQF.  
Detail: [CONVERSATION_POLICY.md](CONVERSATION_POLICY.md)

---

## MemoryEngine

```
retrieve(user_id, persona_id, query, scopes[]) → MemoryBundle
get_signals(bundle) → MemorySignals              # for behavior.decide()
commit(user_id, turn, candidates[]) → CommitResult
forget(user_id, filter) → void
```

**Owns:** semantic, preference, relational, episodic, working memory.  
**Must NOT:** override BDV, store arc/CPS/CQF, import behavior.  
Detail: [MEMORY.md](MEMORY.md)

---

## SpeechEngine

```
transcribe(audio_bytes) → TranscriptResult
synthesize(text, expression, timing?) → AudioResult
```

Optional for text channel.

---

## LLMAdapter

```
complete(LLMRequest) → LLMResponse
```

`LLMRequest` built from BDV + VoiceDirective (coherence) + memory + policy.

---

## PluginRegistry

```
register(plugin) → void
get_hooks(event) → Plugin[]

Hooks:
  on_turn_start → PluginSignal[]
  on_behavior_signals → PluginSignal[]
  on_memory_retrieve → MemoryEnrichment[]
  on_llm_tools → ToolDefinition[]
  on_response_post → TurnResult
```

---

## Dependency matrix

| Module | May import |
|--------|------------|
| core | — |
| session | core |
| arc | core |
| behavior | core, arc |
| memory | core |
| policy | core |
| personality | core |
| coherence | core |
| llm | core |
| speech | core |
| plugins | core |
| conversation | all via DI |

**Forbidden:** behavior→llm, behavior→memory, arc→behavior, duplicate CQF/CPS/OAL outside behavior/, policy re-deciding speak/silence, coherence mutating BDV action fields

---

## Authority stack (reference)

```
Behavior → BDV (action)
Personality → ExpressionConstraints (draft)
Coherence → VoiceDirective (unified voice)
Policy → hard gate only
```
