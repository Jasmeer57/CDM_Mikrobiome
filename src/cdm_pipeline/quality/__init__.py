"""Quality modules for the Microbiome-CDM pipeline.

Ported and adapted from the EFRE pipeline:
- predicate_synonyms: Normalize LLM-emitted predicate variants to 14 canonical CDM predicates
- type_constraints: Type-pair constraint matrix for 14 CDM entity types
- llm_verifier_gate: LLM-based semantic verification with direction-demotion
- corroboration_merge: Merge multiple triples for same entity pair across papers
- schema_migration: Add demotion tracking columns to relationships table
- bio_audit: Biological plausibility audit with 14 microbiome-specific flags
- external_validation: Cross-validation against DisGeNET/MONDO/DOID/ChEBI/NCBITaxon
- confidence_scoring: 8-component scientific quality score with direction recovery
"""
