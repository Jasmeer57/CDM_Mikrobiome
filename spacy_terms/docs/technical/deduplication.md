# 4-Layer Biomedical Deduplication

The pipeline features an advanced **4-layer deduplication system** that progressively removes duplicates at different levels of semantic understanding.

## 🔄 Deduplication Layers

### **Layer 1: Exact Deduplication**
- **Purpose**: Remove identical terms
- **Method**: String normalization and exact matching
- **Configuration**: Always enabled
- **Performance**: Very fast, removes obvious duplicates

### **Layer 2: Fuzzy Deduplication**
- **Purpose**: Remove similar terms with minor variations
- **Method**: RapidFuzz string similarity
- **Threshold**: 85% (configurable)
- **Examples**: `DNA extraction` vs `DNA extractions`

### **Layer 3: Semantic Deduplication**
- **Purpose**: Remove semantically equivalent terms
- **Method**: Sentence-transformer embeddings with cosine similarity
- **Models**: Mini-LM, Nomic v1.5, MPNet
- **Threshold**: 90% (configurable)
- **Examples**: `gut microbiota` vs `intestinal microflora`

### **Layer 4: BioMistral Biomedical Deduplication** ⭐ **NEW**
- **Purpose**: Context-aware biomedical duplicate detection
- **Method**: BioMistral/BioPubMedBERT classification with domain-specific prompts
- **Context**: Microbiome, biomedical, clinical, genomics
- **Confidence**: High-confidence duplicate detection with reasoning

## 🧬 BioMistral Biomedical Deduplication

### **How It Works**
1. **Semantic Grouping**: Terms are first grouped by semantic similarity
2. **Biomedical Classification**: Each term pair is evaluated by BioMistral for biomedical equivalence
3. **Context-Aware Prompts**: Specialized prompts for different biomedical domains
4. **Duplicate Clustering**: Advanced clustering to find duplicate groups
5. **Reasoning Storage**: Detailed reasoning for each duplicate decision

### **Biomedical Context Examples**

**Microbiome Context:**
```text
Compare these two biomedical terms in the context of microbiome research:
Term 1: "bacterial 16S rRNA"
Term 2: "16S rRNA gene"

Question: Are these terms referring to the same biological concept in microbiome research?
```

**Clinical Context:**
```text
Compare these two biomedical terms in the context of clinical research:
Term 1: "antibiotic treatment"
Term 2: "antimicrobial therapy"

Question: Are these terms referring to the same clinical intervention?
```

### **Output Features**
- **Duplicate Detection**: Identifies biomedical duplicates missed by other layers
- **Reasoning Storage**: Each duplicate decision includes detailed reasoning
- **Parseable Results**: Biomedical duplicates can be parsed separately
- **Confidence Scores**: High-confidence classifications
- **Context Specificity**: Tailored to specific biomedical domains

## ⚙️ Configuration

### **Command Line Arguments**
```bash
# Enable/disable biomedical deduplication
--disable_biomedical_dedup    # Disable BioMistral layer
--biomedical_context microbiome    # Set biomedical context
```

### **Configuration File**
```python
@dataclass
class DeduplicationConfig:
    # Existing layers
    exact_enabled: bool = True
    fuzzy_threshold: float = 0.85
    semantic_threshold: float = 0.9

    # BioMistral layer
    biomedical_enabled: bool = True
    biomedical_model: str = "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext"
    biomedical_context: str = "microbiome"
    biomedical_confidence_threshold: float = 0.7
```

## 📊 Performance Metrics

The pipeline tracks deduplication performance at each layer:

```json
{
  "statistics": {
    "deduplication": {
      "original_count": 453,
      "exact_removed": 15,
      "fuzzy_removed": 12,
      "semantic_removed": 8,
      "biomedical_removed": 5,
      "final_count": 413
    }
  }
}
```

## 🧪 Parsing Biomedical Duplicates

The `biomedical_duplicates` field contains detailed information about duplicates detected by BioMistral:

```json
{
  "biomedical_duplicates": [
    {
      "term": "bacterial 16S rRNA",
      "biomedical_duplicate_reason": {
        "kept_term": "16S rRNA gene",
        "removed_term": "bacterial 16S rRNA",
        "context": "microbiome_biomedical",
        "method": "biomistral_classification",
        "confidence": "high"
      }
    }
  ]
}
```

## 🎯 Use Cases

### **Microbiome Research**
- Detect duplicate bacterial taxa names
- Merge equivalent measurement terms
- Consolidate methodology descriptions

### **Clinical Research**
- Identify duplicate medical procedures
- Merge equivalent diagnostic terms
- Consolidate treatment descriptions

### **Genomics Research**
- Detect duplicate gene/protein names
- Merge equivalent sequence analysis terms
- Consolidate methodology descriptions

## 🔍 Advanced Features

### **Smart Term Selection**
When duplicates are found, the pipeline selects the best term based on:
1. **Frequency**: Most frequently occurring term
2. **Length**: Shorter, more concise terms preferred
3. **Position**: First occurrence in document

### **Duplicate Group Tracking**
Each kept term includes information about its duplicate group:
```python
{
  "term": "16S rRNA gene",
  "biomedical_kept": True,
  "biomedical_duplicate_group": ["16S rRNA gene", "bacterial 16S rRNA", "16S ribosomal RNA"]
}
```

### **Fallback Mechanisms**
If BioMistral is unavailable, the system gracefully falls back to semantic deduplication only.

## 🚀 Benefits

1. **Domain-Specific**: Understands biomedical terminology nuances
2. **Context-Aware**: Tailored to specific research domains
3. **High Precision**: BioMistral provides accurate classifications
4. **Detailed Reasoning**: Each decision is explainable
5. **Parseable Output**: Structured data for downstream processing
6. **Configurable**: Flexible for different research contexts

The 4-layer deduplication system ensures maximum precision while preserving scientifically meaningful distinctions in biomedical terminology.