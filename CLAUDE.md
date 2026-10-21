# CLAUDE.md

Microsoft Rewards bot for Windows: Playwright drives Microsoft Edge (one persistent profile per account) and a
pywebview UI (`rewards_bot/ui/web`). The user speaks Vietnamese. UI strings, log messages and code comments are
written in Vietnamese, and new ones should be too. Identifiers stay in English.

## Commands

```bash
python -m pytest -q tests                  # or check.bat; run before every commit
python -m rewards_bot                      # UI (single instance: data/app.lock)
python -m rewards_bot --check              # self-check every account, no searches
python -m rewards_bot --run-all --headless # what Task Scheduler runs
```

## Layout

- `core/bot.py`: `RewardsBot`, one account per thread. Entry points `run()`, `diagnose()` and `refresh()` all go
  through `_session()`, which opens the browser and handles errors.
- `core/rewards_page.py`: parses rewards.bing.com (points, cards, Points breakdown). It is tested against
  `tests/fixtures`.
- `core/runner.py`: runs accounts in parallel (`max_parallel`) and writes `data/logs/<date>.log` (kept 14 days).
- `core/config.py`: settings defaults plus atomic JSON writes (`.bak` kept). `ui/webapp.py` has `SETTING_SCHEMA`:
  every new setting needs a default in `DEFAULT_SETTINGS`, an entry in the schema and a field in
  `ui/web/app.js` (`SETTING_FIELDS`).
- `search/catalog.py`: the query catalog. `search/bank.py` hands out queries without repeats across accounts or
  across `history_days`.
- `data/` holds login sessions and cookies. It is never committed. Profile dir = `data/profiles/<profile["dir"]>`,
  which is fixed at creation and is not the display name (for example account `namanh` uses `namanh_2`).

## Hard-won facts (verified 2026-10)

- **Mobile searches counted as PC.** Bing sets the session cookie `_Rwho=u=d` (desktop) on the first desktop search
  or bing.com visit. Every later search in that browser session is then counted as PC, including the emulated
  mobile tab, so Mobile earns +0 once PC is full. `RewardsBot.new_bing_session()` clears `_Rwho`, `_SS` and
  `_EDGE_S` before and after the mobile tab. Clearing only `_SS`/`_EDGE_S` is not enough. Do not remove this.
- Mobile emulation (`_emulate_mobile`) builds UA and client hints from the real running Edge version. Both the old
  hard-coded UA and the new one earn points, so the UA was not the cause of the mobile bug.
- Points for a search usually show up in Points breakdown immediately (3 per search). A "rate limit / delayed credit"
  theory was tested and was wrong. Do not reintroduce slow-mode style workarounds without an A/B test.
- Edge adds desktop-only headers (`sec-ms-gec`, `x-client-data`, `x-edge-*`) at the network layer. Playwright
  `route` cannot remove them. Chrome cannot read Edge's cookies (app-bound encryption), so a copied profile is
  logged out.
- Windows can auto-sign the Edge *browser* into the user's work account in every bot profile, even
  when bing.com cookies belong to another account. This did not affect search points.

## Debugging against real accounts

- Write throwaway scripts in the scratchpad, not the repo. Import `RewardsBot`, load settings with
  `load_settings()`, and call `bot._session(work, headless=True, label=...)` or `bot.diagnose()`.
- A profile can be opened by only one browser at a time. Check that the app is not running that account (look for
  `msedge.exe` with `--user-data-dir=...\<dir>`) before you launch it.
- Prove a fix with an A/B run on the same account: read Points breakdown, do 3 searches, read it again. Do not draw
  conclusions from log timing alone, because the user also searches manually on their phone.

## Conventions

- The user commits straight to `main` and asks before each push. End commit messages with the Co-Authored-By line.
- Tests use fakes (`FakePage`, `FakeBank`, `bot.sleep` patched out). Keep bot logic testable without a browser.
