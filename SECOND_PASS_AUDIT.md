# VPI GAVAN — Second Improvement Pass Audit

## Baseline

The repository contains a working aiogram 3 bot with SQLite persistence, Ollama Cloud integration, inline navigation, delayed interface cleanup, pending wars, trade and alliance systems, country matching, world rankings, and a substantial regression suite. `bot.py` is approximately 2,360 lines, while `db.py` is approximately 1,118 lines.

## High-priority findings

1. The main bot module is monolithic and retains the old instant-war resolution path after the new pending-war creation return. It is unreachable in normal execution but creates maintenance risk and should be isolated or removed after the new flow is fully covered.
2. SQLite persistence remains the largest deployment risk on Render. The code should make the storage requirement explicit, validate the database path, and add a startup warning/health check rather than silently presenting a production-ready state without durable storage.
3. Interface cleanup and private/group delivery are functional but need stronger lifecycle tests around task cancellation, restart behavior, and group permission failures.
4. War mechanics currently have a hidden attack/defense exchange and one final verdict, but lack a clear status card for attackers, response-state visibility, and a structured resolution audit trail.
5. The richest/intimidating rankings are deterministic but need a compact explanation of scoring and should handle ties and small populations gracefully.
6. Onboarding still depends heavily on commands and needs a guided first-session path with explicit next action and cooldown explanations.
7. The repository has broad tests but lacks long-play balance assertions, startup configuration validation, pending-war deletion/transfer cleanup tests, and a full command-to-callback authorization matrix.
8. Configuration contains dormant nuclear constants and legacy provider variables. These should be clearly separated from active gameplay or removed from user-facing guidance.

## Repair order

The pass hardened persistence, lifecycle, concurrency, and authorization. It improved onboarding and interface guidance, expanded pending-war visibility for both sides, retained secret war turns, removed the unreachable instant-war implementation, and added adversarial persistence/configuration regressions.

## Implemented in this pass

The configuration parser now safely handles malformed, negative, and invalid timing environment values. SQLite runs an integrity check before polling starts, and Render emits a warning when `DB_PATH` is relative and therefore likely ephemeral. The new database cleanup test verifies that pending wars are removed when a country is deleted.

The first-session flow now tells a new player to follow three concrete actions instead of presenting the full command surface. `/guide` explains the first ten minutes, cooldown meaning, and the hidden-turn war flow. `/wars` now shows both wars awaiting the player's defense and wars initiated by the player that are awaiting an opponent or finalization.

The unreachable legacy instant-war code and unused in-memory war gate were removed. The active system is now the persistent attack → hidden defense → final verdict path. The full regression suite remains green after removal.

## Operational boundary

A complete production deployment still requires a Render Persistent Disk or external database. Code can warn about ephemeral storage, but it cannot make a free ephemeral filesystem durable. Long-play balance should continue to be measured with real player telemetry after deployment rather than guessed from a short test run.
