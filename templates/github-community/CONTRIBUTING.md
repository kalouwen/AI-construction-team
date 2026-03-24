# Contributing to __PROJECT_NAME__

## Quick Start

```bash
git clone <repo-url>
cd __PROJECT_NAME__
npm install        # or your install command
__TEST_CMD__       # verify everything works before you start
```

## Workflow

1. **Create a branch** — one topic per branch
   ```bash
   git checkout -b fix/your-issue-name
   ```

2. **Write code and tests together** — feature and test in the same PR, different commits

3. **Commit with format** — enforced by commitlint on commit
   ```
   type(scope): description

   Types: feat | fix | refactor | test | docs | chore
   ```

4. **Push** — auto-rebases on main and runs tests
   ```bash
   git push origin fix/your-issue-name
   ```

5. **Open PR** — use the PR template, keep it under 200 lines changed

## Rules

| Rule | Why |
|------|-----|
| One branch = one topic | So each change can be reverted independently |
| Tests required with every feature | No test = not done |
| PR < 200 lines | Large PRs don't get real review |
| Never `--no-verify` | If the hook caught something, fix it |

## Reporting Bugs

Use the **Bug Report** issue template. Include steps to reproduce.

## Security Issues

Do **not** open a public issue. See [SECURITY.md](SECURITY.md).
