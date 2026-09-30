# ============================================================
# fetch_cache.py -- refresh dataroma_cache.json from YOUR PC
# Mean Reversion Macro Insights
# ============================================================
#
# WHAT THIS IS (simplified Sep 2026):
#   A small tool you run by hand on your Windows PC. It is NOT part of
#   the daily GitHub workflow any more.
#
#   Dataroma's 13F "superinvestor buys" list only changes once a quarter
#   (filings are due ~45 days after quarter end: mid Feb, May, Aug, Nov)
#   and Dataroma sometimes blocks GitHub's servers. Your home internet
#   usually works. So: run this on your PC after each 13F deadline, then
#   commit the updated dataroma_cache.json. The dashboard turns amber
#   with a reminder when a refresh is due.
#
# HOW TO RUN (VS Code terminal, PowerShell):
#   1. Open the market-pulse-ai folder in VS Code
#   2. Press Ctrl+` to open the terminal
#   3. Type:  python fetch_cache.py   and press Enter
#   4. Source Control icon (Ctrl+Shift+G) -> type a message -> Commit -> Sync Changes
#
# Acquirer's Multiple is no longer fetched here. main.py fetches it live
# every day (it works) and keeps its own fallback copy in run_cache.json.
# ============================================================

from screens import fetch_dataroma_live, write_dataroma_cache, ScreenError


def main():
    print("=" * 50)
    print("fetch_cache.py -- refresh Dataroma 13F cache")
    print("=" * 50)
    print("\nFetching Dataroma superinvestor quarterly buys...")
    try:
        buys = fetch_dataroma_live()
    except ScreenError as e:
        print(f"\nFAILED: {e}")
        print("Nothing was changed. Your existing dataroma_cache.json is still in place.")
        print("Try again in a few minutes, or on a different network.")
        return

    write_dataroma_cache(buys)
    top = sorted(buys.items(), key=lambda x: -x[1])[:5]
    print(f"\nOK: {len(buys)} stocks saved to dataroma_cache.json")
    print(f"Top 5 by number of superinvestors buying: {top}")
    print("\nNEXT STEP: commit and push dataroma_cache.json")
    print("  Source Control icon (Ctrl+Shift+G) -> message -> Commit -> Sync Changes")
    print("=" * 50)


if __name__ == "__main__":
    main()