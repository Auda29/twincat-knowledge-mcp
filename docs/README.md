# Documentation index

Knowledge `0.1.2` is published as [GitHub Release v0.1.2](https://github.com/Auda29/twincat-knowledge-mcp/releases/tag/v0.1.2), at source commit `84c437aea8e27da930a246e7bb3ae310e8e5d31d`. Its nine read-only stdio tools comprise four topic tools and five typed tools for finding and getting symbols and libraries and looking up errors. The full 15-tool plan remains incomplete.

- [Published setup](setup.md) covers versioned asset URLs, exact SHA-256 pins, isolated installation and client configuration.
- [Release notes](releases/v0.1.2.md) record the released assets, compatibility and limitations. Repository-level release immutability is not asserted.
- [Status](STATUS.md) gives current status followed by dated historical evidence.
- [Typed entities](implementation/typed-entities.md) defines supported extraction grammar and typed tool contracts.
- [stdio serving](implementation/stdio-serving-cli.md) describes server operation and snapshot behavior.
- [Plan](PLAN.md) and [goal](GOAL.md) retain historical planning, requirements and evidence with current status summaries.
- [Development candidate](implementation/development-candidate.md) records the historical pre-release receipt.

Real-corpus extraction acceptance remains open. Unsupported grammar and missing or conflicting fields remain unknown. Lazy typed indexing defers work to the first typed query; it does not prove the cold-start goal. Documentation and metadata do not establish live editor, compiled PLC, or installed-library state.
