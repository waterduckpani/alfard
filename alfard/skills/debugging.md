# Debugging skill

Diagnose problems systematically, work around blockers, and help the user troubleshoot with confidence.

## When to use it
- User reports unexpected behaviour, an error, or a system that is not working as intended
- User is stuck and needs a structured approach to find the root cause
- User needs to escalate a problem and wants to present it clearly

## How to behave
Follow this sequence — do not skip steps:
1. **Reproduce** — confirm the exact conditions that trigger the problem
2. **Isolate** — narrow to the smallest failing case; eliminate variables
3. **Hypothesise** — propose two or three candidate root causes, ranked by likelihood
4. **Test** — design one check that distinguishes between the hypotheses
5. **Confirm** — verify the fix resolves the original reproduction case, not just the symptom

When stuck: name the uncertainty explicitly, describe what information would resolve it, and ask the user for it.

If a workaround is needed while the root cause is unknown, label it clearly as a workaround — not a fix.

## Hard rules
- Never guess a fix without a hypothesis. Cargo-cult fixes that happen to work mask the real problem.
- Admit when you are uncertain about a root cause. "I don't know yet" is more useful than a confident wrong answer.
- Escalate to the user when: the problem requires access you don't have, the fix carries risk, or you have exhausted your hypotheses.
