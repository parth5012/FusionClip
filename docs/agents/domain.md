Domain Docs

How engineering skills consume repo's domain documentation when exploring codebase.

Before exploring, read

`CONTEXT.md`repo root,
- **`CONTEXT-MAP.md`repo root exists — points one`CONTEXT.md`per context. Read each one relevant topic.
`docs/adr/`read ADRs touch area you're work in. multi-context repos, check`src/<context>/docs/adr/`context-scoped decisions.

any files don't exist, **proceed silently**. Don't flag absence; don't suggest creating upfront.`/domain-modeling`skill (reached`/grill-with-docs``/improve-codebase-architecture`creates lazily when terms decisions actually get resolved.

File structure

Single-contextrepo (most repos)

```
/
├── CONTEXT.md
├── docs/adr/
├── 0001-event-sourced-orders.md
└── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence`CONTEXT-MAP.md`root):

```
/
├── CONTEXT-MAP.md
├── docs/adr/ system-wide decisions
└── src/
├── ordering/
├── CONTEXT.md
└── docs/adr/ context-specific decisions
└── billing/
├── CONTEXT.md
└── docs/adr/
```

Use glossary's vocabulary

When output names domainconcept (in an issue title, a refactor proposal, a hypothesis, a test name)use term defined`CONTEXT.md`. Don't drift synonyms glossary explicitly avoids.

concept isn't glossary yet, that's signal either you're inventing language project doesn'tuse (reconsider)there's real gap (note`/domain-modeling`).

Flag ADR conflicts

output contradicts existing ADR, surface explicitly than silently overriding:

_Contradicts ADR-0007 (event-sourced orders) worth reopening because…_
