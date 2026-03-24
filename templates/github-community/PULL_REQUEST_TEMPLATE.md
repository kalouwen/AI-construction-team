## What

<!-- One sentence: what changed -->

## Why

<!-- Why is this change needed? Link to issue if applicable -->

## Test

<!-- How did you verify this works? -->
- [ ] Tests added / updated
- [ ] Manually tested: [describe what you tried]

## Revert

<!-- How to roll back if this breaks production -->

```bash
git revert <commit-sha>
```

---

**原子化检查**（CI 自动执行，无需手动勾选）
- PR 大小：CI 会自动量行数，超过 200 行会警告，超过 500 行会阻断
- 单一主题：一个 PR 只做一件事，可以独立回滚
- Commit 格式：`type(scope): description`，commitlint 会自动校验
