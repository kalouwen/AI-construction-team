// Commit message format: type(scope): description
// Examples:
//   feat(auth): add OAuth2 login
//   fix(api): handle null response from payment service
//   docs: update README with setup steps

module.exports = {
  extends: ["@commitlint/config-conventional"],
  plugins: [
    {
      rules: {
        // 检测多话题信号：逗号分隔列表、多个"and"连接、分号
        // 级别 1 = warn（不阻断，只提示），避免误报影响正常工作流
        "subject-no-multitopic": (parsed) => {
          const subject = parsed.subject || "";
          // 信号：逗号分隔多个动作、两个以上 and、加号连接
          const multiTopicPattern =
            /,\s*\w+(ed|ing|s)?\b|(\band\b.+\band\b)|\+.+\+/i;
          if (multiTopicPattern.test(subject)) {
            return [
              false,
              "Subject appears to contain multiple topics.\n" +
                "  Rule: if these changes can be reverted independently, split into separate commits.\n" +
                "  Example: 'feat: add login' and 'fix: update profile' → two commits.",
            ];
          }
          return [true, ""];
        },
      },
    },
  ],
  rules: {
    // Allow these types
    "type-enum": [
      2,
      "always",
      [
        "feat", // new feature
        "fix", // bug fix
        "refactor", // code change that neither fixes a bug nor adds a feature
        "test", // adding or updating tests
        "docs", // documentation only
        "chore", // build process, dependencies, tooling
        "ci", // CI/CD changes
        "perf", // performance improvement
        "revert", // revert a previous commit
      ],
    ],
    // Subject line max length
    "header-max-length": [2, "always", 100],
    // Subject must not end with period
    "subject-full-stop": [2, "never", "."],
    // 多话题警告（warn，不阻断）
    "subject-no-multitopic": [1, "always"],
  },
};
