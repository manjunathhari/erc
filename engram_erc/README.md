# Engram Reasoning Core (ERC) — ERC-4.0 General Core

**Milestone:** General-domain case intelligence (surgery becomes a profile)  
**Version:** 0.8.0 (0.4.1 plus four temporal increments: 0.5.0, the temporal contract foundation, B1, additive types with no change in reasoning; 0.6.0, the temporal comparison, B3, which reads that contract; and 0.7.0, rule temporal requirements, B4, by which a rule may declare the temporal relationship it needs between its premises and fires only when that relationship is established; and 0.8.0, conclusion temporal propagation, B5, by which a rule may declare the time its conclusion takes, alternative derivations of one conclusion are kept and each is evaluated on its own; see RELEASE_NOTES.md)  
**Status:** Cumulative local implementation, ERC-1.1 through ERC-4.0 General Core.
**Naming:** "ERC-4.0" now means this general core. The earlier surgical release that carried the 4.0 label is referred to by its package version, **0.4.0**; its notes are kept in the ERC_4_0_General_Core release zip. The General Core was released as package version 0.4.1, so it sorts above 0.4.0; the current package version is 0.7.0.  
**Test runner:** pytest only (`python -m pytest`). Tests from ERC-3.1 on are plain pytest functions, which `python -m unittest discover` does not collect.

ERC applies governed knowledge to a **case**, watches events over time, compares the case with past cases, and structures the options a **reviewer** decides between. The core is the same for any field: a matter for a lawyer, an incident for an engineer, a student's progress for a teacher, a patient for a surgeon. Every check, threshold, rule and comparison works the same whatever the subject.

A field's own words live in a **domain profile** (`engram_erc/profiles/`). The profile supplies labels and maps the field's evidence types onto the core's; it never affects a decision. This release ships two profiles: `general` (the default) and `surgical`, which reproduces the 0.4.0 surgical release's words exactly.

Two worked examples:

- `python -m engram_erc.examples.general_incident` — an IT incident through the full pipeline.
- `engram_erc/examples/surgical/` — the ERC-3.x/0.4.0 surgical examples, ported to the General Core names.

Start with `RELEASE_NOTES.md` (what changed, the rename table, the compatibility layer) and `INTEGRATION.md` (how a host calls ERC). Earlier milestone notes (ERC-3.x and the 0.4.0 surgical release) are in the release zip; they use the 0.4.0 names.

The package is not merged into the private Engram repository, is not connected to a live record system or P6 deployment, and is not a safety certification for any field.
