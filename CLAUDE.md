# Rules for Claude Code in this project (Mean Reversion Insights)

## Who you are working with
The owner is a deep-value investor, NOT a programmer. Explain everything in plain English.
He uses Windows 11 Home and VS Code. Never give Mac instructions or shortcuts.
Do not use em dashes or en dashes in anything you write for him (replies, comments, files).

## How to work with him
1. Ask before you code or decide anything. Propose first, then wait for a yes.
2. Before EVERY command or edit that needs his approval, say in one plain sentence what it does,
   why you are doing it, what could go wrong, and whether it can be undone.
3. Ask separately, and explain the risk, before any of these: deleting files, git push --force,
   git reset --hard, installing software, touching anything outside this project folder, and
   anything involving passwords, API keys, tokens or GitHub secrets.
4. Make the smallest change that solves the problem. Do not rewrite or reformat files he did not ask about.
5. After a change, give a short plain-English summary of every file you changed and what changed.
6. How changes reach GitHub (owner's decision, Nov 2 2026): for normal changes, run a shadow test (old code vs new
   code on the same data), show him the difference, wait for his go, then pull and push straight to main. Use a
   branch and pull request only for risky changes: the workflow triggers in daily.yml, GitHub secrets, API keys or
   tokens, or deleting files. Always include a ready-to-use commit message.

## Project facts
- Live site: https://anil2040.github.io/mean-reversion-insights
- Read SESSION_LOG.md first. It holds the architecture rules, decisions and open items.
  Update it after meaningful changes.
- The GitHub workflow runs Python 3.13. Test with the same version.
- Never put a backslash inside the curly braces of an f-string.
- The Claude Routine instructions must be search-only: that environment cannot open web pages.
- The pipeline starts when clauderoutinedata.json is pushed. Do not change the triggers in
  .github/workflows/daily.yml without asking.
- The routine and a bot push to main every day. Use "git pull --no-rebase --no-edit" before
  pushing, and never force-push.
- AI model order and retry rules are the owner's decisions (see SESSION_LOG.md). Ask before changing them.
