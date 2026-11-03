# Mean Reversion Insights

A daily macro dashboard for a deep-value, mean reversion investor (Boise, Idaho).

- **Live page:** https://anil2040.github.io/mean-reversion-insights
- **What it shows:** the Macro Heat Score (MHS), macro indicators from FRED (the St. Louis Fed's economic data), market
  gauges, value screens (Magic Formula, Acquirer's Multiple, Super Investors) and an AI summary of the morning newsletters.
- **How it runs:** a Claude Routine pushes clauderoutinedata.json each weekday morning; that push starts the GitHub Actions
  workflow in .github/workflows/daily.yml, which runs main.py and publishes index.html.
- **Companion project:** the Mean Reversion Audit (a Claude skill plus the Finviz Research Assistant Chrome extension) reads
  the hidden market-context block on the page.
- **Project history and rules:** SESSION_LOG.md (read first) and CLAUDE.md.
