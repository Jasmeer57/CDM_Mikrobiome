<!-- DRAFT v0, not sent. Placeholders in {braces}. -->
Each item is a (subject, relation, object) triple extracted from a microbiome paper, with the one sentence it
came from. Classify it (schema: triple_proposal):
- TYPED_RELATION only if the sentence itself states a specific relation between exactly these two entities.
  Give the predicate from this list: {relation_vocabulary}; the direction (AS_ORIGINAL, REVERSED or UNDIRECTED);
  the exact supporting sentence copied verbatim; and the evidence reference.
- GENERIC_COOCCURRENCE if both entities appear but the sentence states no specific relation between them.
- UNSUPPORTED if the sentence does not support the triple. AMBIGUOUS if it cannot be decided.
Never infer a relation from co-occurrence, never upgrade an association to a mechanism, and reverse the
direction only if the sentence says so. Keep the triple id unchanged.
Items: {items}
