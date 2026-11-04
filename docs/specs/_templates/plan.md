# NNN — Technical plan

## Design
How it is solved: components, pipeline stages, data flow. What is reused from the existing code. A diagram if it helps.

## Data model
New or changed tables, columns, constraints and indexes. Each change is a small migration that applies on a clean database.

## Contracts
Function, CLI and HTTP interfaces: inputs, outputs, errors. External dependencies (model provider, database, network) sit behind interfaces so they can be tested.

## Test strategy
Every AC of the spec, with the layer that tests it.

| AC | Layer | Test |
|---|---|---|
| AC-NNN-01 | integration (Postgres) | … |
| AC-NNN-02 | unit | … |

## Evaluation impact
Can this change move retrieval or answer metrics? Which evaluation runs before merging, against which baseline? ("none" if it cannot.)

## Risks
What can go wrong and how it is detected or mitigated.

## ADRs
New or affected ADRs (or "none").
