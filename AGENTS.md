# Taotian BSR Ranking Weekly Report Project Guide

This project owns Taotian BSR ranking weekly monitoring and report workflows.

## Codex Project Layout

- Project-level Codex config: `.codex/config.toml`
- Project-level skills: `.agents/skills`
- Project-scoped skill:
  - `TT-bsr-ranking-report`

Do not move `TT-bsr-ranking-report` back to a user-level `.agents/skills` directory unless it becomes broadly reusable outside this project.

## Working Principles

- Use `TT-bsr-ranking-report` for Taotian BSR ranking change analysis and Feishu Base/report sync.
- Keep Taotian BSR outputs and intermediate data under this project or the project skill folder.
- Keep generic data import capabilities such as `stream-load` user-level unless they become specific to this project.
