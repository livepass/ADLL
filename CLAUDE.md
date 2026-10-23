@AGENTS.md

# CLAUDE.md — Claude Code 适配

本文件仅负责 Claude Code 适配，不维护独立的工程规范。
文件顶部的 `@AGENTS.md` 已导入统一操作规则入口（所有编程 Agent 必须遵守，
本文件不再重复其规则）。

- 最高工程规范：`.specify/memory/constitution.md`（ADLL 项目开发宪章，
  生效版本见文件末尾版本行）
- 规则冲突时以宪章为准；发现任何层级的规则矛盾时立即报告，
  不得自行取舍或合并。

## Spec Kit Skills（必须使用）

- 需求定义、澄清、技术规划、任务拆解、实施与验证等阶段，
  必须使用本项目已安装的 Spec Kit Skills（`.claude/skills/` 下的
  speckit-specify、speckit-clarify、speckit-plan、speckit-tasks、
  speckit-implement 等）按规范驱动流程执行，不得绕过或自造流程。
- 禁止：覆盖或修改 `.claude/skills/` 中已有的 Spec Kit Skills；
  如需变更 Skill 内容，先请求人工批准。
