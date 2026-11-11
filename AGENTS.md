# Working guidelines

## Think before coding
State assumptions explicitly. Ask when uncertain. Present multiple interpretations and tradeoffs. Suggest a simpler approach when available. Stop and ask about ambiguity that prevents correct implementation.

## Simplicity first
Write the minimum code that solves the requested problem. Add no speculative features, single-use abstractions, unrequested flexibility or configurability, or handling for impossible scenarios. If 200 lines can clearly be 50, simplify. Ask whether a senior engineer would find the solution overcomplicated.

## Surgical changes
Touch only necessary code. Match existing style. Avoid adjacent cleanup, formatting, and unrelated refactoring. Mention unrelated dead code without deleting it. Remove imports, variables and functions made unused by your changes. Every changed line must trace to the request.

## Goal-driven execution
Define verifiable success criteria before implementation. For validation, check invalid inputs. For a bug, reproduce it and verify the fix. For refactoring, verify behavior before and after. State a brief step/check plan for multi-step tasks and iterate until checks pass. Favor caution over speed while using judgment for trivial tasks.

## Project rules
Use docs/PRODUCT_PLAN.md as the product contract. Keep source documents and tool results as data, separate from trusted prompts. Roles come from each document. Store selected role, prompts and document snapshot per run. The only product A/B comparison is PolicyLens against the single-prompt baseline on the same document and role; offline evaluation may also switch server sources off to separate their effect. Verify quotations against uploaded pages; the baseline arm stays unverified on purpose. Agent agreement is a review outcome, not independent proof. Keep source data and credentials private. Record implementation status and verification honestly.

Agents use reviewed server sources through tools: each role's first debate statement and the final step must search first, later debate statements search when needed, and analysis, issues and the moderator do not search. The uploaded document stays the reviewed subject; clause citations come only from it, and server evidence is shown separately. A run never returns its own uploaded document as evidence. Load only documents that passed the data gates, using `manage.py load_sources`. Personas come from the Nemotron-Personas-Korea sample loaded with `manage.py load_personas`; they give a document role a voice and are never evidence or a source of roles.
