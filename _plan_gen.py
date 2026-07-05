import sys
sys.stdout.reconfigure(encoding="utf-8")

P = 'docs/superpowers/plans/2026-07-05-async-indexing-lifecycle.md'

with open(P, 'a', encoding='utf-8') as f:
    f.write('# 异步索引与运维 API 实施计划\n\n')
    f.write('> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox () syntax for tracking.\n\n')
