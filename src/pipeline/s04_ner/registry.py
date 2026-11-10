"""Model registry — maps short names to model classes and configs.

This is the single source of truth for available NER models. Both the
production runner and the benchmark script use this registry.

To add a new model, add an entry to :data:`MODEL_REGISTRY` with:
    key   — short name used in CLI (``--models <name>``)
    class — model class inheriting :class:`BaseNERModel`
    kwargs — constructor keyword arguments

The registry is domain-agnostic: entity types come from the model class
defaults or can be overridden via ``kwargs["entity_types"]``.
"""
from pipeline.s04_ner.bert_variants import BertVariantModel
from pipeline.s04_ner.gliner import GLiNERModel
from pipeline.s04_ner.gliner2 import GLiNER2Model
from pipeline.s04_ner.hunflair2 import HunFlair2Model
from pipeline.s04_ner.pubmedbert import PubMedBERTModel
from pipeline.s04_ner.scispacy import SpaCyNERModel, SPACY_MODELS
from pipeline.s04_ner.pubtator import PubTatorModel

MODEL_REGISTRY = {
    # ── GLiNER variants ──
    # The two legacy entries pin max_tokens=None to reproduce the frozen
    # zenodo_v1 baseline exactly (fixed 2000-char stride, which silently
    # truncates ~13% of chunks). Do not "fix" these two — the baseline
    # all_ner_sections_combined.csv (1,705,501 rows) depends on it.
    "gliner": {
        "class": GLiNERModel,
        "kwargs": {
            "model_name": "urchade/gliner_medium",
            "name": "gliner_medium",
            "output_file": "gliner_ner.csv",
            "revision": "b63645e3596b70a7d66e0597b3e739ad17bffe9d",
            "max_tokens": None,
        },
    },
    "gliner_biomed": {
        "class": GLiNERModel,
        "kwargs": {
            "model_name": "Ihor/gliner-biomed-large-v1.0",
            "name": "gliner_biomed",
            "output_file": "gliner_biomed_ner.csv",
            "revision": "f79771210ab2111a2081ef31620fdb7342f602e9",
            "max_tokens": None,
        },
    },
    # ── newest GLiNER checkpoints (2026) ──
    # Two distinct architectures, run together for breadth; do NOT compare
    # scores across the gliner2/ and gliner->v2.5 rows as if they were one family.
    #   gliner2  — fastino `gliner2` package, 205M, apache-2.0, Sep 2026
    #   *-v2.5  — gliner-community `gliner` package, deberta-v3 encoder
    "gliner2_base": {
        "class": GLiNER2Model,
        "kwargs": {
            "model_name": "fastino/gliner2-base-v1",
            "name": "gliner2_base",
            "output_file": "gliner2_base_ner.csv",
            "revision": "f9634218e53580c56edf0de97ca1a7d3f1c2354e",
        },
    },
    "gliner2_large": {
        "class": GLiNER2Model,
        "kwargs": {
            "model_name": "fastino/gliner2-large-v1",
            "name": "gliner2_large",
            "output_file": "gliner2_large_ner.csv",
            "revision": "d7aa8a2850d175a9227ff80358ea380723d03ad2",
        },
    },
    "gliner_v25_medium": {
        "class": GLiNERModel,
        "kwargs": {
            "model_name": "gliner-community/gliner_medium-v2.5",
            "name": "gliner_v25_medium",
            "output_file": "gliner_v25_medium_ner.csv",
            "revision": "88c3b98b57ad5e7d66fb209ed61c53f4b1fd05da",
        },
    },
    # NOTE: this checkpoint ships model.safetensors + spm.model but no README
    # and no license metadata on the Hub. Flagged before citing in the manuscript.
    "gliner_v25_biomed": {
        "class": GLiNERModel,
        "kwargs": {
            "model_name": "Ihor/gliner-large-v2.5-biomed",
            "name": "gliner_v25_biomed",
            "output_file": "gliner_v25_biomed_ner.csv",
            "revision": "304d250ab2373a0d4ef0bc9524868cf04de0d509",
        },
    },
    # ── PubMedBERT / BioBERT ──
    "pubmedbert": {
        "class": PubMedBERTModel,
        "kwargs": {
            "model_name": "alvaroalon2/biobert_diseases_ner",
            "name": "biobert_diseases",
            "output_file": "pubmedbert_ner.csv",
            "revision": "0a4ed7dd4fd3e6db7229e5b801b70eefcb253759",
        },
    },
    # ── BioBERT / SciBERT variants (notebook Cell 6b, word-level v2 decoding) ──
    # `pubmedbert` above is a sentence-split, pipeline-aggregated legacy wrapper;
    # these four are the notebook's raw token-classification path, run here over
    # the full 452-paper segmented-section corpus.
    "bert_disease": {
        "class": BertVariantModel,
        "kwargs": {
            "model_name": "alvaroalon2/biobert_diseases_ner",
            "name": "biobert_diseases_wl",
            "output_file": "bert_disease_ner.csv",
        },
    },
    "bert_chemical": {
        "class": BertVariantModel,
        "kwargs": {
            "model_name": "alvaroalon2/biobert_chemical_ner",
            "name": "biobert_chemical",
            "output_file": "bert_chemical_ner.csv",
        },
    },
    "bert_genetic": {
        "class": BertVariantModel,
        "kwargs": {
            "model_name": "alvaroalon2/biobert_genetic_ner",
            "name": "biobert_genetic",
            "output_file": "bert_genetic_ner.csv",
        },
    },
    "scibert_jnlpba": {
        "class": BertVariantModel,
        "kwargs": {
            "model_name": "fran-martinez/scibert_scivocab_cased_ner_jnlpba",
            "name": "scibert_jnlpba",
            "output_file": "scibert_jnlpba_ner.csv",
        },
    },
    # ── PubTator3 API ──
    "pubtator": {
        "class": PubTatorModel,
        "kwargs": {
            "name": "pubtator3",
            "output_file": "pubtator3_ner.csv",
        },
    },
    # ── sciSpaCy models (one entry per spaCy model) ──
    "scispacy": {
        "class": SpaCyNERModel,
        "kwargs": {
            "spacy_model": "en_core_sci_lg",
            "name": "en_core_sci_lg",
            "output_file": "scispacy_ner_lg.csv",
        },
    },
    "scispacy_bc5cdr": {
        "class": SpaCyNERModel,
        "kwargs": {
            "spacy_model": "en_ner_bc5cdr_md",
            "name": "en_ner_bc5cdr_md",
            "output_file": "scispacy_ner_bc5cdr.csv",
        },
    },
    "scispacy_craft": {
        "class": SpaCyNERModel,
        "kwargs": {
            "spacy_model": "en_ner_craft_md",
            "name": "en_ner_craft_md",
            "output_file": "scispacy_ner_craft.csv",
        },
    },
    "scispacy_jnlpba": {
        "class": SpaCyNERModel,
        "kwargs": {
            "spacy_model": "en_ner_jnlpba_md",
            "name": "en_ner_jnlpba_md",
            "output_file": "scispacy_ner_jnlpba.csv",
        },
    },
    # 5th sciSpaCy NER model (notebook Cell 7) — needs its own venv; in
    # en_core_sci_lg / en_ner_bc5cdr_md / en_ner_craft_md / en_ner_jnlpba_md above
    # it was never run. Installed via src/scripts/setup_ner_variants_venv.sh.
    "scispacy_bionlp13cg": {
        "class": SpaCyNERModel,
        "kwargs": {
            "spacy_model": "en_ner_bionlp13cg_md",
            "name": "en_ner_bionlp13cg_md",
            "output_file": "scispacy_ner_bionlp13cg.csv",
        },
    },
    # ── HunFlair2 (flair SequenceTagger, notebook Cell 6) ──
    "hunflair2": {
        "class": HunFlair2Model,
        "kwargs": {
            "model_name": "hunflair/hunflair2-ner",
            "name": "hunflair2",
            "output_file": "hunflair2_ner.csv",
        },
    },
}

# Models that run on raw text (suitable for benchmarking)
LOCAL_MODELS = {"gliner", "gliner_biomed", "pubmedbert",
                "bert_disease", "bert_chemical", "bert_genetic", "scibert_jnlpba",
                "scispacy", "scispacy_bc5cdr", "scispacy_craft", "scispacy_jnlpba"}

# BioBERT / SciBERT token-classification group (notebook Cell 6b)
BERT_VARIANTS = ["bert_disease", "bert_chemical", "bert_genetic", "scibert_jnlpba"]

# Newest GLiNER checkpoints (2026): GLiNER2 base+large (fastino/gliner2) and
# gliner v2.5 medium + biomedical. Two architectures, both zero-shot.
GLINER_NEW = ["gliner2_base", "gliner2_large", "gliner_v25_medium", "gliner_v25_biomed"]

# Models that need the isolated `venvs/ner_variants` env (spacy 3.7 + flair),
# not `venvs/vllm`: see src/scripts/setup_ner_variants_venv.sh
EXTRA_MODELS = ["scispacy_bionlp13cg", "hunflair2"]

# Models that require API access (not suitable for offline benchmarking)
API_MODELS = {"pubtator"}

# Default model set for production multi-NER ensemble
DEFAULT_MODELS = ["gliner", "pubmedbert", "pubtator",
                  "scispacy_bc5cdr", "scispacy_craft", "scispacy_jnlpba"]

# sciSpaCy model group (run all 4 together)
SCISPACY_ALL = ["scispacy", "scispacy_bc5cdr", "scispacy_craft", "scispacy_jnlpba"]


def get_model(key, **override_kwargs):
    """Instantiate a model from the registry.

    Args:
        key: registry key (e.g. ``"gliner"``)
        **override_kwargs: constructor keyword overrides

    Returns:
        Model instance (not yet loaded)
    """
    if key not in MODEL_REGISTRY:
        raise KeyError("Unknown model: %s. Available: %s" % (
            key, sorted(MODEL_REGISTRY.keys())))
    entry = MODEL_REGISTRY[key]
    kwargs = dict(entry["kwargs"])
    kwargs.update(override_kwargs)
    return entry["class"](**kwargs)
