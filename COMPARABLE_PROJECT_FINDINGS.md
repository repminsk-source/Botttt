# Comparable strategy project findings

## Sources inspected

1. https://github.com/iliyadindar/Telegram-Strategic-GameBot
2. https://github.com/pooyanzarif/worldwar
3. https://github.com/GFardad/Telegram-village-war

## Verified mechanics and product patterns

### Telegram Strategic GameBot
The repository describes a multiplayer resource-management game for Telegram groups. Its stated mechanics include resource management, building upgrades, military training, treaties, planned attacks, admin controls, configurable asset types, status-section ordering, private messaging, channel statements, and a test-oriented project structure. It supports multiple languages and has separate admin and asset-management modules.

Potentially useful for VPI GAVAN: a configurable asset/catalog layer, curator-controlled status sections, treaty confirmation flows, formal admin tools, and explicit player/operator documentation.

### WorldWar
The README describes a text strategy game in which players found a village, create workers, build farms, produce food, sell food for gold, prepare an army, attack neighbors, conquer them, receive loot, improve army skill, and compete for a top-10 ranking. It uses explicit starting resources and a simple first-session progression loop.

Potentially useful for VPI GAVAN: a highly visible first-ten-minutes loop, worker/labor allocation, production chains, resource-to-cash conversion, post-war loot with clear limits, and a simple power-ranking explanation.

### Telegram-village-war / Telegram Strategic GameBot fork
The README describes eight resource types, factories and buildings, trainable military unit classes, treaties with interactive confirmation, detailed campaign tracking, weekly production collection, private messages, public statements, admin-triggered updates, shields, cooldowns, and multiplayer group flow.

Potentially useful for VPI GAVAN: a treaty lifecycle with pending/confirm/reject states, multiple military branches or roles, explicit campaign history, public statements/news, scheduled production, and a clear separation between player and admin operations.

## Initial gap hypotheses for VPI GAVAN

VPI GAVAN already has many deeper mechanics: real-country data, hidden attack/defense turns, AI verdicts, economy, resources, market, diplomacy, anti-raid, PMC, premium wallet, and extensive tests. The likely valuable gaps are not basic systems but presentation and lifecycle layers: worker/population allocation, explicit treaty state transitions, campaign history, public statements, clearer production chains, a structured news feed, and curator-configurable status sections.

Do not copy their simpler mechanics wholesale. VPI GAVAN should retain its realism filters, atomic stat application, secret war inputs, and no-artificial-population-cap rule.
