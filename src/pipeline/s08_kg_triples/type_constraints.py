"""Type-pair constraint matrix for the Microbiome-CDM pipeline.

Defines which predicates are valid for each (subject_type, object_type) pair.
Triples that violate these constraints are either rejected or auto-corrected
(e.g., swapped subject/object, or predicate demoted to associated_with).

Adapted from EFRE's VALID_TYPE_PAIRS and INVERTED_TYPE_PAIRS, rebuilt for
MCDM's 14 entity types and 26 relation types.
"""
from __future__ import annotations

from pipeline.config import CDM_TYPES

# ── Canonical CDM predicates (26) ──
ALL_PREDICATES = frozenset({
    "associated_with", "treats", "treated_by", "produces", "produced_by",
    "disrupts", "depleted_in", "enriched_in", "co_occurs_with",
    "encodes", "expresses", "part_of_pathway", "participates_in", "implicated_in",
    "causes", "increases", "decreases", "activates", "inhibits", "regulates",
    "modulates", "prevents", "improves", "metabolizes", "binds", "predicts",
})

# ── Type-pair constraint matrix ──
# Maps (subject_type, object_type) -> set of valid predicates
# If a (subject_type, object_type) pair is not listed, falls back to:
#   {associated_with, co_occurs_with} (safe defaults)
TYPE_PAIR_CONSTRAINTS = {

    ('ORGANISM', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "depleted_in", "disrupts", "enriched_in", "implicated_in", "improves", "predicts", "prevents",
    },
    ('ORGANISM', 'CHEMICAL'): {
        "associated_with", "co_occurs_with", "decreases", "increases", "metabolizes", "modulates", "produced_by", "produces",
    },
    ('ORGANISM', 'PROTEIN'): {
        "activates", "associated_with", "co_occurs_with", "expresses", "inhibits", "modulates", "regulates",
    },
    ('ORGANISM', 'DNA_RNA'): {
        "associated_with", "co_occurs_with", "expresses",
    },
    ('ORGANISM', 'PATHWAY'): {
        "activates", "associated_with", "co_occurs_with", "inhibits", "modulates", "part_of_pathway", "participates_in", "regulates",
    },
    ('ORGANISM', 'CELL_TYPE'): {
        "activates", "associated_with", "co_occurs_with", "inhibits",
    },
    ('ORGANISM', 'CLINICAL'): {
        "associated_with", "causes", "co_occurs_with", "depleted_in", "enriched_in", "implicated_in", "improves", "predicts", "prevents",
    },
    ('ORGANISM', 'GENOMICS'): {
        "associated_with", "co_occurs_with", "expresses",
    },
    ('ORGANISM', 'ORGANISM'): {
        "associated_with", "binds", "co_occurs_with", "decreases", "increases", "inhibits", "modulates",
    },
    ('CHEMICAL', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "disrupts", "implicated_in", "improves", "predicts", "prevents", "treats",
    },
    ('CHEMICAL', 'ORGANISM'): {
        "activates", "associated_with", "co_occurs_with", "decreases", "disrupts", "increases", "inhibits", "modulates", "produced_by",
    },
    ('CHEMICAL', 'PROTEIN'): {
        "activates", "associated_with", "binds", "co_occurs_with", "decreases", "increases", "inhibits", "modulates", "regulates",
    },
    ('CHEMICAL', 'PATHWAY'): {
        "activates", "associated_with", "co_occurs_with", "inhibits", "modulates", "part_of_pathway", "participates_in", "regulates",
    },
    ('CHEMICAL', 'CHEMICAL'): {
        "associated_with", "binds", "co_occurs_with", "decreases", "disrupts", "increases", "metabolizes", "produced_by", "produces",
    },
    ('CHEMICAL', 'CLINICAL'): {
        "associated_with", "causes", "co_occurs_with", "disrupts", "implicated_in", "improves", "predicts", "prevents", "treats",
    },
    ('CHEMICAL', 'CELL_TYPE'): {
        "activates", "associated_with", "co_occurs_with", "disrupts", "inhibits",
    },
    ('CHEMICAL', 'DNA_RNA'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('CHEMICAL', 'GENOMICS'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('DISEASE', 'CHEMICAL'): {
        "associated_with", "co_occurs_with", "predicts", "treated_by",
    },
    ('DISEASE', 'ORGANISM'): {
        "associated_with", "co_occurs_with", "depleted_in", "enriched_in", "predicts",
    },
    ('DISEASE', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "predicts",
    },
    ('DISEASE', 'PROTEIN'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('DISEASE', 'DNA_RNA'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('DISEASE', 'CLINICAL'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('DISEASE', 'CELL_TYPE'): {
        "associated_with", "co_occurs_with",
    },
    ('DISEASE', 'PATHWAY'): {
        "associated_with", "co_occurs_with",
    },
    ('DISEASE', 'GENOMICS'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('PROTEIN', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "implicated_in", "predicts",
    },
    ('PROTEIN', 'CHEMICAL'): {
        "associated_with", "binds", "co_occurs_with", "decreases", "increases", "metabolizes", "produces",
    },
    ('PROTEIN', 'PROTEIN'): {
        "activates", "associated_with", "binds", "co_occurs_with", "decreases", "increases", "inhibits", "modulates", "regulates",
    },
    ('PROTEIN', 'PATHWAY'): {
        "activates", "associated_with", "co_occurs_with", "inhibits", "modulates", "part_of_pathway", "participates_in", "regulates",
    },
    ('PROTEIN', 'ORGANISM'): {
        "associated_with", "co_occurs_with", "decreases", "increases",
    },
    ('PROTEIN', 'DNA_RNA'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('PROTEIN', 'CELL_TYPE'): {
        "associated_with", "co_occurs_with",
    },
    ('PROTEIN', 'CLINICAL'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('PROTEIN', 'GENOMICS'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('DNA_RNA', 'PROTEIN'): {
        "activates", "associated_with", "binds", "co_occurs_with", "encodes", "inhibits", "modulates", "regulates",
    },
    ('DNA_RNA', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "implicated_in", "predicts",
    },
    ('DNA_RNA', 'PATHWAY'): {
        "activates", "associated_with", "co_occurs_with", "inhibits", "modulates", "part_of_pathway", "participates_in", "regulates",
    },
    ('DNA_RNA', 'CHEMICAL'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('DNA_RNA', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('DNA_RNA', 'DNA_RNA'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('DNA_RNA', 'CLINICAL'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('DNA_RNA', 'GENOMICS'): {
        "associated_with", "co_occurs_with",
    },
    ('CELL_TYPE', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "implicated_in", "predicts",
    },
    ('CELL_TYPE', 'PROTEIN'): {
        "activates", "associated_with", "co_occurs_with", "expresses", "inhibits", "modulates", "regulates",
    },
    ('CELL_TYPE', 'CHEMICAL'): {
        "associated_with", "co_occurs_with", "metabolizes", "produces",
    },
    ('CELL_TYPE', 'PATHWAY'): {
        "activates", "associated_with", "co_occurs_with", "inhibits", "modulates", "part_of_pathway", "participates_in", "regulates",
    },
    ('CELL_TYPE', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('CELL_TYPE', 'DNA_RNA'): {
        "associated_with", "co_occurs_with", "expresses",
    },
    ('CELL_TYPE', 'CELL_TYPE'): {
        "associated_with", "co_occurs_with",
    },
    ('CELL_TYPE', 'CLINICAL'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('GENOMICS', 'PROTEIN'): {
        "activates", "associated_with", "binds", "co_occurs_with", "encodes", "inhibits", "modulates", "regulates",
    },
    ('GENOMICS', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "implicated_in", "predicts",
    },
    ('GENOMICS', 'PATHWAY'): {
        "activates", "associated_with", "co_occurs_with", "inhibits", "modulates", "part_of_pathway", "participates_in", "regulates",
    },
    ('GENOMICS', 'CHEMICAL'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('GENOMICS', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('GENOMICS', 'DNA_RNA'): {
        "associated_with", "binds", "co_occurs_with",
    },
    ('GENOMICS', 'CELL_TYPE'): {
        "associated_with", "co_occurs_with",
    },
    ('GENOMICS', 'GENOMICS'): {
        "associated_with", "co_occurs_with",
    },
    ('GENOMICS', 'CLINICAL'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('PATHWAY', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "implicated_in",
    },
    ('PATHWAY', 'CHEMICAL'): {
        "associated_with", "co_occurs_with", "produces",
    },
    ('PATHWAY', 'PROTEIN'): {
        "activates", "associated_with", "co_occurs_with", "inhibits", "modulates", "produces", "regulates",
    },
    ('PATHWAY', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('PATHWAY', 'PATHWAY'): {
        "associated_with", "co_occurs_with",
    },
    ('PATHWAY', 'CLINICAL'): {
        "associated_with", "co_occurs_with", "implicated_in",
    },
    ('CLINICAL', 'CHEMICAL'): {
        "associated_with", "co_occurs_with", "treated_by",
    },
    ('CLINICAL', 'ORGANISM'): {
        "associated_with", "co_occurs_with", "depleted_in", "enriched_in",
    },
    ('CLINICAL', 'DISEASE'): {
        "associated_with", "causes", "co_occurs_with", "predicts",
    },
    ('CLINICAL', 'CLINICAL'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('CLINICAL', 'PROTEIN'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('CLINICAL', 'DNA_RNA'): {
        "associated_with", "co_occurs_with", "predicts",
    },
    ('LAB_METHOD', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('LAB_METHOD', 'CHEMICAL'): {
        "associated_with", "co_occurs_with",
    },
    ('LAB_METHOD', 'DISEASE'): {
        "associated_with", "co_occurs_with",
    },
    ('LAB_METHOD', 'PROTEIN'): {
        "associated_with", "co_occurs_with",
    },
    ('LAB_METHOD', 'DNA_RNA'): {
        "associated_with", "co_occurs_with",
    },
    ('LAB_METHOD', 'PATHWAY'): {
        "associated_with", "co_occurs_with",
    },
    ('LAB_METHOD', 'CELL_TYPE'): {
        "associated_with", "co_occurs_with",
    },
    ('LAB_METHOD', 'DATA_ANALYSIS'): {
        "associated_with", "co_occurs_with", "participates_in",
    },
    ('LAB_METHOD', 'EXPERIMENTAL_METHOD'): {
        "associated_with", "co_occurs_with", "participates_in",
    },
    ('DATA_ANALYSIS', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('DATA_ANALYSIS', 'CHEMICAL'): {
        "associated_with", "co_occurs_with",
    },
    ('DATA_ANALYSIS', 'DISEASE'): {
        "associated_with", "co_occurs_with",
    },
    ('DATA_ANALYSIS', 'PROTEIN'): {
        "associated_with", "co_occurs_with",
    },
    ('DATA_ANALYSIS', 'DNA_RNA'): {
        "associated_with", "co_occurs_with",
    },
    ('DATA_ANALYSIS', 'PATHWAY'): {
        "associated_with", "co_occurs_with",
    },
    ('DATA_ANALYSIS', 'CELL_TYPE'): {
        "associated_with", "co_occurs_with",
    },
    ('SAMPLE_METHOD', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('SAMPLE_METHOD', 'CHEMICAL'): {
        "associated_with", "co_occurs_with",
    },
    ('SAMPLE_METHOD', 'DISEASE'): {
        "associated_with", "co_occurs_with",
    },
    ('SAMPLE_METHOD', 'DNA_RNA'): {
        "associated_with", "co_occurs_with",
    },
    ('EXPERIMENTAL_METHOD', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('EXPERIMENTAL_METHOD', 'CHEMICAL'): {
        "associated_with", "co_occurs_with",
    },
    ('EXPERIMENTAL_METHOD', 'DISEASE'): {
        "associated_with", "co_occurs_with",
    },
    ('EXPERIMENTAL_METHOD', 'PROTEIN'): {
        "associated_with", "co_occurs_with",
    },
    ('EXPERIMENTAL_METHOD', 'DNA_RNA'): {
        "associated_with", "co_occurs_with",
    },
    ('EXPERIMENTAL_METHOD', 'CELL_TYPE'): {
        "associated_with", "co_occurs_with",
    },
    ('STUDY_DESIGN', 'DISEASE'): {
        "associated_with", "co_occurs_with",
    },
    ('STUDY_DESIGN', 'ORGANISM'): {
        "associated_with", "co_occurs_with",
    },
    ('STUDY_DESIGN', 'CHEMICAL'): {
        "associated_with", "co_occurs_with",
    },
}

# ── Default valid predicates for unlisted type pairs ──
DEFAULT_PREDICATES = frozenset({"associated_with", "co_occurs_with"})

# ── Inverted type-pair detection ──
# (subject_type, predicate, object_type) triples that are likely direction-inverted.
# When detected, the system attempts to swap subject/object or demote to associated_with.
INVERTED_TRIPLES = {
    # Disease does not "deplete" or "enrich" an organism — it's the other way around
    ("DISEASE", "depleted_in", "ORGANISM"): "swap",
    ("DISEASE", "enriched_in", "ORGANISM"): "swap",
    ("CLINICAL", "depleted_in", "ORGANISM"): "swap",
    ("CLINICAL", "enriched_in", "ORGANISM"): "swap",
    # Disease does not "produce" chemicals — organisms do
    ("DISEASE", "produces", "CHEMICAL"): "demote",
    # Disease does not "treat" chemicals — chemicals treat diseases
    ("DISEASE", "treats", "CHEMICAL"): "swap",
    ("DISEASE", "treats", "ORGANISM"): "swap",
    # Organism does not "treat" disease (unless it's a probiotic — keep but flag)
    ("ORGANISM", "treats", "DISEASE"): "keep_flag",
    # Chemical is not "depleted_in" organism
    ("CHEMICAL", "depleted_in", "ORGANISM"): "demote",
    ("CHEMICAL", "enriched_in", "ORGANISM"): "demote",
    # DNA_RNA does not "express" organism — organism expresses DNA_RNA
    ("DNA_RNA", "expresses", "ORGANISM"): "swap",
    ("DNA_RNA", "expresses", "CELL_TYPE"): "swap",
    # Protein does not "encode" DNA_RNA — DNA_RNA encodes protein
    ("PROTEIN", "encodes", "DNA_RNA"): "swap",
    ("PROTEIN", "encodes", "GENOMICS"): "swap",
    # Cell type does not "encode" anything — genes do
    ("CELL_TYPE", "encodes", "PROTEIN"): "swap",
    ("CELL_TYPE", "encodes", "DNA_RNA"): "swap",
    # Disease does not "metabolize" chemicals — organisms do
    ("DISEASE", "metabolizes", "CHEMICAL"): "demote",
    ("DISEASE", "metabolizes", "ORGANISM"): "demote",
    # Disease does not "bind" proteins — chemicals/proteins do
    ("DISEASE", "binds", "PROTEIN"): "demote",
    ("DISEASE", "binds", "CHEMICAL"): "demote",
    # Organism does not "predict" disease (biomarker direction)
    ("ORGANISM", "predicts", "DISEASE"): "keep_flag",
    # Protein does not "encode" protein
    ("PROTEIN", "encodes", "PROTEIN"): "demote",
    # Chemical does not "express" protein — organism/cell does
    ("CHEMICAL", "expresses", "PROTEIN"): "demote",
    # Disease does not "activate" or "inhibit" proteins
    ("DISEASE", "activates", "PROTEIN"): "demote",
    ("DISEASE", "inhibits", "PROTEIN"): "demote",
}


def get_valid_predicates(subject_type: str, object_type: str) -> frozenset:
    """Get the set of valid predicates for a (subject_type, object_type) pair."""
    key = (subject_type, object_type)
    if key in TYPE_PAIR_CONSTRAINTS:
        return TYPE_PAIR_CONSTRAINTS[key]
    return DEFAULT_PREDICATES


def is_valid_triple(subject_type: str, predicate: str, object_type: str) -> bool:
    """Check if a (subject_type, predicate, object_type) triple is valid."""
    valid = get_valid_predicates(subject_type, object_type)
    return predicate in valid


def check_inverted(subject_type: str, predicate: str, object_type: str):
    """Check if a triple is likely direction-inverted.

    Returns:
        None if not inverted
        "swap" if subject/object should be swapped
        "demote" if predicate should be demoted to associated_with
        "keep_flag" if valid but worth flagging
    """
    return INVERTED_TRIPLES.get((subject_type, predicate, object_type))


def validate_and_fix(
    subject: str, subject_type: str,
    predicate: str,
    object: str, object_type: str,
    evidence: str = "",
) -> dict:
    """Validate a triple and apply fixes.

    Returns a dict with:
        - valid: bool (whether the triple should be kept)
        - subject, subject_type, predicate, object, object_type: possibly fixed
        - original_predicate: the original predicate if changed
        - fix_action: None | "swapped" | "demoted" | "flagged" | "rejected"
        - fix_reason: explanation
    """
    result = {
        "valid": True,
        "subject": subject,
        "subject_type": subject_type,
        "predicate": predicate,
        "object": object,
        "object_type": object_type,
        "original_predicate": None,
        "fix_action": None,
        "fix_reason": None,
    }

    # Check if inverted
    inversion = check_inverted(subject_type, predicate, object_type)
    if inversion == "swap":
        result["subject"], result["object"] = object, subject
        result["subject_type"], result["object_type"] = object_type, subject_type
        result["fix_action"] = "swapped"
        result["fix_reason"] = f"inverted: ({subject_type}, {predicate}, {object_type}) \u2192 swapped"
    elif inversion == "demote":
        result["original_predicate"] = predicate
        result["predicate"] = "associated_with"
        result["fix_action"] = "demoted"
        result["fix_reason"] = f"inverted type-pair: {predicate} \u2192 associated_with"
    elif inversion == "keep_flag":
        result["fix_action"] = "flagged"
        result["fix_reason"] = f"borderline type-pair: {subject_type} {predicate} {object_type}"

    # After fixing, check if predicate is valid for the (possibly fixed) type pair
    s_type = result["subject_type"]
    o_type = result["object_type"]
    pred = result["predicate"]

    if not is_valid_triple(s_type, pred, o_type):
        valid_preds = get_valid_predicates(s_type, o_type)
        if "associated_with" in valid_preds and pred not in valid_preds:
            # Demote to associated_with rather than reject
            if result["original_predicate"] is None:
                result["original_predicate"] = pred
            result["predicate"] = "associated_with"
            if result["fix_action"] is None:
                result["fix_action"] = "demoted"
                result["fix_reason"] = (
                    f"invalid predicate '{pred}' for ({s_type}, {o_type}) "
                    f"\u2192 demoted to associated_with"
                )

    # Final check: if still invalid, reject
    if not is_valid_triple(result["subject_type"], result["predicate"], result["object_type"]):
        result["valid"] = False
        result["fix_action"] = "rejected"
        result["fix_reason"] = (
            f"no valid predicate for ({result['subject_type']}, {result['object_type']})"
        )

    return result

