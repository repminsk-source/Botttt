# 50-workstream baseline inventory
Generated from the current Git tree.

## Git
[31m??[m FIFTY_WORKSTREAM_BASELINE.md
[33mff2b668[m Polish AI errors and deployment guidance

## Python modules
ai.py
anti_spam.py
bot.py
check_handlers.py
config.py
countries.py
db.py
market.py
playtest_advanced.py
playtest_beginner.py
territory.py
test_ai_provider.py
test_ai_safety.py
test_antispam.py
test_callback_card_lifecycle.py
test_command_registry.py
test_config_edge_cases.py
test_countries.py
test_delayed_cleanup.py
test_hidden_war.py
test_keyboard_dispatch.py
test_keyboard_routes.py
test_market_balance.py
test_market_ui.py
test_message_cleanup.py
test_min_narrative.py
test_ownership_guard.py
test_pmc.py
test_premium_shop.py
test_progression_balance.py
test_second_pass_regressions.py
test_stats.py
test_verdict_antiraid_local.py
test_war_pending.py
test_world_rankings.py
test_world_trade.py
world_data.py

## Tests
test_ai_provider.py
test_ai_safety.py
test_antispam.py
test_callback_card_lifecycle.py
test_command_registry.py
test_config_edge_cases.py
test_countries.py
test_delayed_cleanup.py
test_hidden_war.py
test_keyboard_dispatch.py
test_keyboard_routes.py
test_market_balance.py
test_market_ui.py
test_message_cleanup.py
test_min_narrative.py
test_ownership_guard.py
test_pmc.py
test_premium_shop.py
test_progression_balance.py
test_second_pass_regressions.py
test_stats.py
test_verdict_antiraid_local.py
test_war_pending.py
test_world_rankings.py
test_world_trade.py

## Commands
action
alliance_create
alliance_info
alliance_join
alliance_leave
alliances
attack
build
build_base
buy
collect
country
defend
founding
give_points
guide
help
history
kick
market
mobilize
myid
news
pmc_accept
pmc_create
pmc_fund
pmc_help
pmc_list
pmc_profile
pmc_recruit
pmc_reject
pmc_request
pmc_requests
pmc_sanction
policy
premium
premium_grant
progress
raid_status
seed_alliances
set_stat
set_year
spy
top
trade
trade_accept
trade_offer
trade_reject
transfer
upgrade
wars
world
world_event
year

## Callback handlers
@dp.callback_query(F.data == "army:base"
@dp.callback_query(F.data == "army:mobilize:1"
@dp.callback_query(F.data == "eco:collect"
@dp.callback_query(F.data == "eco:market"
@dp.callback_query(F.data == "ui:army"
@dp.callback_query(F.data == "ui:back"
@dp.callback_query(F.data == "ui:build"
@dp.callback_query(F.data == "ui:collect"
@dp.callback_query(F.data == "ui:country"
@dp.callback_query(F.data == "ui:diplomacy"
@dp.callback_query(F.data == "ui:economy"
@dp.callback_query(F.data == "ui:guide"
@dp.callback_query(F.data == "ui:more"
@dp.callback_query(F.data == "ui:news"
@dp.callback_query(F.data == "ui:policy"
@dp.callback_query(F.data == "ui:premium"
@dp.callback_query(F.data == "ui:progress"
@dp.callback_query(F.data == "ui:top"
@dp.callback_query(F.data == "ui:trade"
@dp.callback_query(F.data == "ui:world"
@dp.callback_query(F.data.startswith("build:"
@dp.callback_query(F.data.startswith("premium:buy:"

## Database tables
alliance_members
alliances
buildings
countries
events
pending_wars
pmc_contracts
pmc_requests
pmc_sanctions
pmcs
premium_items
premium_ledger
premium_wallets
trade_contracts
wars
world_events
world_state

## Environment keys
ADMIN_IDS
AI_PROVIDER
BOT_TOKEN
DB_PATH
GEMINI_API_KEY
GEMINI_MODEL
GROK_API_KEY
GROK_MODEL
MARKET_TICK_SECONDS
NUKE_COOLDOWN_SECONDS
OLLAMA_API_KEY
OLLAMA_BASE_URL
OLLAMA_ENABLED
OLLAMA_MODEL
SECONDS_PER_GAME_YEAR
START_DATA_YEAR

## Render model/cooldowns
      - key: ACTION_COOLDOWN_SECONDS
        value: "600"
      - key: ATTACK_COOLDOWN_SECONDS
        value: "600"
      - key: COLLECT_COOLDOWN_SECONDS
        value: "2700"
      - key: BUILD_COOLDOWN_SECONDS
        value: "60"
--
      - key: AI_PROVIDER
        value: "ollama"
--
      - key: OLLAMA_MODEL
        value: "gpt-oss:20b-cloud"
