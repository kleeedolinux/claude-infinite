---
name: idea-lab
description: Unbiased ideation and decision protocol - generate genuinely different options, separate memory from fresh reasoning, premortem, steelman, decide with explicit criteria, and park ideas without losing focus. Use when the user brings a new idea, asks for ideas/brainstorm/opinions/"what if"/"e se"/which is better, or plans a big decision.
---

# Idea lab

Goal: memory should inform the thinking without anchoring it. Ideas should be captured without derailing the current work, the way a good colleague handles it.

## If the idea arrives mid-task
`mem idea "<idea in the user's words>"`, a one-line acknowledgement ("parked: X"), then continue the task. Expand it later, or now if the user asks.

## Protocol (for real ideation or decisions)
1. **Restate** the goal and constraints in one or two lines. Ask only if something is truly ambiguous.
2. **Fresh pass first:** sketch options from first principles without consulting memory.
3. **Memory pass:** `mem bias "<idea>"` lists anchors and past decisions or failures from all projects. Note where memory adds evidence and where it is only habit.
4. **Options:** at least 3 genuinely different ones, not variations of one. Include one that contradicts a past choice and one unconventional or cheap one. For each: the core bet, cost, risk and fastest test.
5. **Steelman and devil's advocate:** the strongest case for the option you like least, and the strongest attack on your favourite. For big calls, use the `idea-critic` agent for an independent read; give it the options, not your conclusion.
6. **Premortem:** "a year from now this failed. Why?" Give the top 3 causes and a mitigation for each.
7. **Bias scan:** anchoring on the first framing, sunk cost, confirmation of past decisions, recency, availability, overconfidence, IKEA effect (favouring our own earlier work). Name any that apply.
8. **Decide:** a recommendation plus the evidence that would change it, and the cheapest experiment that tests it.
9. **Record:** `mem note -k idea|decision "..."`. Failed experiments go in as `-k experiment` with the verdict, so they are not retried blindly. Retrying one requires saying what changed in the hypothesis.
