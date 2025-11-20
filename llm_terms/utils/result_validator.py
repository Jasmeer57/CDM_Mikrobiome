"""
Result Validation and Consistency Checks Module for CDM Pipeline
Ensures quality, consistency, and reliability of extraction results
"""

import logging
import re
import json
from typing import Dict, List, Set, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, Counter
import statistics

logger = logging.getLogger(__name__)

class ValidationLevel(Enum):
    """Validation severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class ValidationIssue:
    """Represents a validation issue found in results"""
    level: ValidationLevel
    category: str
    message: str
    entity_index: Optional[int] = None
    entity_type: Optional[str] = None
    confidence_score: Optional[float] = None
    suggestion: Optional[str] = None

@dataclass
class ValidationResult:
    """Complete validation result for entities"""
    is_valid: bool
    total_entities: int
    valid_entities: int
    issues: List[ValidationIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    validation_metadata: Dict[str, Any] = field(default_factory=dict)

class EntityValidator:
    """Validates individual entities for quality and consistency"""

    def __init__(self):
        # Valid CDM entity types
        self.valid_entity_types = {
            'GENE', 'PROTEIN', 'ORGANISM', 'DISEASE', 'CHEMICAL',
            'DNA_RNA', 'CELL_TYPE', 'PATHWAY', 'PHENOTYPE', 'DRUG'
        }

        # Minimum entity lengths by type
        self.min_lengths = {
            'GENE': 2,
            'PROTEIN': 2,
            'ORGANISM': 3,
            'DISEASE': 3,
            'CHEMICAL': 2,
            'DNA_RNA': 2,
            'CELL_TYPE': 3,
            'PATHWAY': 3,
            'PHENOTYPE': 3,
            'DRUG': 2,
            'default': 2
        }

        # Maximum entity lengths to prevent garbage
        self.max_lengths = {
            'GENE': 50,
            'PROTEIN': 100,
            'ORGANISM': 100,
            'DISEASE': 200,
            'CHEMICAL': 100,
            'DNA_RNA': 100,
            'CELL_TYPE': 50,
            'PATHWAY': 200,
            'PHENOTYPE': 100,
            'DRUG': 100,
            'default': 100
        }

        # Patterns for potentially invalid entities
        self.invalid_patterns = [
            r'^\d+$',  # Pure numbers
            r'^[^a-zA-Z]+$',  # No letters
            r'.*[<>{}[\]\\].*',  # HTML/markup symbols
            r'^\s+$',  # Just whitespace
            r'^(the|and|or|but|in|on|at|to|for|of|with|by)\s*$',  # Common stop words alone
        ]

        # Known organism suffixes/prefixes for validation
        self.organism_indicators = [
            'bacterium', 'bacteria', 'species', 'strain', 'family', 'phylum',
            'genus', 'order', 'class', 'kingdom', 'domain', 'coli', 'coccus',
            'bacillus', 'streptococcus', 'lactobacillus', 'bifidobacterium'
        ]

        # Gene/protein patterns
        self.gene_patterns = [
            r'^[A-Z]{2,}\d*',  # Gene symbols like TP53, BRCA1
            r'^[a-z]+-\d+',     # Gene names like p53, gata-1
            r'.*gene.*',        # Contains 'gene'
            r'.*protein.*',     # Contains 'protein'
        ]

    def validate_entity(self, entity: Dict[str, Any], index: int) -> List[ValidationIssue]:
        """Validate a single entity and return any issues"""
        issues = []

        # Check required fields
        required_fields = ['entity', 'type', 'confidence']
        for field in required_fields:
            if field not in entity or entity[field] is None:
                issues.append(ValidationIssue(
                    level=ValidationLevel.ERROR,
                    category='missing_field',
                    message=f"Missing required field: {field}",
                    entity_index=index,
                    suggestion=f"Add {field} field to entity"
                ))

        # Get entity values safely
        entity_text = str(entity.get('entity', '')).strip()
        entity_type = str(entity.get('type', '')).upper()
        confidence = float(entity.get('confidence', 0.0))

        # Validate entity text
        if entity_text:
            text_issues = self._validate_entity_text(entity_text, entity_type, index)
            issues.extend(text_issues)
        else:
            issues.append(ValidationIssue(
                level=ValidationLevel.ERROR,
                category='empty_entity',
                message="Entity text is empty",
                entity_index=index,
                suggestion="Remove empty entity"
            ))

        # Validate entity type
        if entity_type:
            type_issues = self._validate_entity_type(entity_type, index)
            issues.extend(type_issues)
        else:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='unknown_type',
                message="Entity type is empty or invalid",
                entity_index=index,
                suggestion="Assign appropriate CDM entity type"
            ))

        # Validate confidence score
        if confidence is not None:
            confidence_issues = self._validate_confidence_score(confidence, entity_type, index)
            issues.extend(confidence_issues)
        else:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='missing_confidence',
                message="Confidence score is missing",
                entity_index=index,
                suggestion="Add confidence score between 0.0 and 1.0"
            ))

        # Type-specific validation
        if entity_type and entity_text:
            type_specific_issues = self._validate_type_specific(entity_text, entity_type, index)
            issues.extend(type_specific_issues)

        return issues

    def _validate_entity_text(self, text: str, entity_type: str, index: int) -> List[ValidationIssue]:
        """Validate the entity text content"""
        issues = []

        # Length validation
        min_len = self.min_lengths.get(entity_type, self.min_lengths['default'])
        max_len = self.max_lengths.get(entity_type, self.max_lengths['default'])

        if len(text) < min_len:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='too_short',
                message=f"Entity text too short: {len(text)} < {min_len}",
                entity_index=index,
                entity_type=entity_type,
                suggestion="Consider removing or merging with other entities"
            ))

        if len(text) > max_len:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='too_long',
                message=f"Entity text too long: {len(text)} > {max_len}",
                entity_index=index,
                entity_type=entity_type,
                suggestion="Check for truncated or malformed text"
            ))

        # Pattern validation
        for pattern in self.invalid_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                issues.append(ValidationIssue(
                    level=ValidationLevel.ERROR,
                    category='invalid_pattern',
                    message=f"Entity matches invalid pattern: {pattern}",
                    entity_index=index,
                    entity_type=entity_type,
                    suggestion="Remove entity as it appears to be noise"
                ))

        # Character validation
        if re.search(r'[^\w\s\-\.]', text):
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='special_characters',
                message="Entity contains unusual special characters",
                entity_index=index,
                entity_type=entity_type,
                suggestion="Review for potential formatting issues"
            ))

        return issues

    def _validate_entity_type(self, entity_type: str, index: int) -> List[ValidationIssue]:
        """Validate the entity type"""
        issues = []

        if entity_type not in self.valid_entity_types:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='invalid_type',
                message=f"Unknown entity type: {entity_type}",
                entity_index=index,
                entity_type=entity_type,
                suggestion=f"Use one of: {', '.join(sorted(self.valid_entity_types))}"
            ))

        return issues

    def _validate_confidence_score(self, confidence: float, entity_type: str, index: int) -> List[ValidationIssue]:
        """Validate confidence score"""
        issues = []

        if not (0.0 <= confidence <= 1.0):
            issues.append(ValidationIssue(
                level=ValidationLevel.ERROR,
                category='invalid_confidence',
                message=f"Confidence score out of range: {confidence}",
                entity_index=index,
                entity_type=entity_type,
                confidence_score=confidence,
                suggestion="Ensure confidence is between 0.0 and 1.0"
            ))

        elif confidence < 0.3:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='low_confidence',
                message=f"Very low confidence score: {confidence:.2f}",
                entity_index=index,
                entity_type=entity_type,
                confidence_score=confidence,
                suggestion="Consider increasing confidence threshold"
            ))

        return issues

    def _validate_type_specific(self, text: str, entity_type: str, index: int) -> List[ValidationIssue]:
        """Type-specific validation rules"""
        issues = []
        text_lower = text.lower()

        if entity_type == 'ORGANISM':
            # Check if it looks like an organism
            has_organism_indicator = any(indicator in text_lower for indicator in self.organism_indicators)
            has_scientific_pattern = re.search(r'\b[A-Z][a-z]+ [a-z]+\b', text)  # Genus species

            if not (has_organism_indicator or has_scientific_pattern):
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='organism_validation',
                    message="May not be a valid organism name",
                    entity_index=index,
                    entity_type=entity_type,
                    suggestion="Verify organism classification"
                ))

        elif entity_type == 'GENE':
            # Check if it looks like a gene name
            has_gene_pattern = any(re.search(pattern, text, re.IGNORECASE) for pattern in self.gene_patterns)

            if not has_gene_pattern and not re.search(r'[A-Z]{2,}\d*', text):
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='gene_validation',
                    message="May not be a standard gene name/symbol",
                    entity_index=index,
                    entity_type=entity_type,
                    suggestion="Verify gene nomenclature"
                ))

        return issues

class ResultConsistencyChecker:
    """Checks for consistency across multiple entities"""

    def __init__(self):
        self.similarity_threshold = 0.9  # High similarity threshold for duplicates

    def check_consistency(self, entities: List[Dict[str, Any]]) -> List[ValidationIssue]:
        """Check consistency across all entities"""
        issues = []

        # Check for exact duplicates
        exact_duplicates = self._find_exact_duplicates(entities)
        for duplicate_group in exact_duplicates:
            if len(duplicate_group) > 1:
                issues.append(ValidationIssue(
                    level=ValidationLevel.WARNING,
                    category='exact_duplicates',
                    message=f"Found {len(duplicate_group)} exact duplicates: {[entities[i]['entity'] for i in duplicate_group]}",
                    suggestion="Remove duplicate entities"
                ))

        # Check for near duplicates
        near_duplicates = self._find_near_duplicates(entities)
        for duplicate_group in near_duplicates:
            if len(duplicate_group) > 1:
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='near_duplicates',
                    message=f"Found similar entities: {[entities[i]['entity'] for i in duplicate_group]}",
                    suggestion="Consider if these should be merged"
                ))

        # Check confidence consistency
        confidence_issues = self._check_confidence_consistency(entities)
        issues.extend(confidence_issues)

        # Check type consistency
        type_issues = self._check_type_consistency(entities)
        issues.extend(type_issues)

        return issues

    def _find_exact_duplicates(self, entities: List[Dict[str, Any]]) -> List[List[int]]:
        """Find groups of exact duplicate entities"""
        entity_map = defaultdict(list)

        for i, entity in enumerate(entities):
            key = (entity.get('entity', '').lower().strip(), entity.get('type', '').upper())
            entity_map[key].append(i)

        return [indices for indices in entity_map.values() if len(indices) > 1]

    def _find_near_duplicates(self, entities: List[Dict[str, Any]]) -> List[List[int]]:
        """Find groups of near-duplicate entities using string similarity"""
        duplicate_groups = []

        for i, entity1 in enumerate(entities):
            for j, entity2 in enumerate(entities[i+1:], i+1):
                if entity1.get('type') == entity2.get('type'):
                    text1 = entity1.get('entity', '').lower()
                    text2 = entity2.get('entity', '').lower()

                    # Simple similarity check (can be enhanced with more sophisticated methods)
                    similarity = self._string_similarity(text1, text2)
                    if similarity >= self.similarity_threshold:
                        duplicate_groups.append([i, j])

        return duplicate_groups

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using Jaccard similarity of words"""
        words1 = set(s1.split())
        words2 = set(s2.split())

        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union)

    def _check_confidence_consistency(self, entities: List[Dict[str, Any]]) -> List[ValidationIssue]:
        """Check for unusual confidence score patterns"""
        issues = []
        confidences = [entity.get('confidence', 0.0) for entity in entities]

        if confidences:
            avg_confidence = statistics.mean(confidences)
            std_confidence = statistics.stdev(confidences) if len(confidences) > 1 else 0

            # Very low average confidence
            if avg_confidence < 0.5:
                issues.append(ValidationIssue(
                    level=ValidationLevel.WARNING,
                    category='low_average_confidence',
                    message=f"Low average confidence: {avg_confidence:.2f}",
                    suggestion="Consider improving extraction quality or lowering threshold"
                ))

            # Very high standard deviation (inconsistent quality)
            if std_confidence > 0.3:
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='inconsistent_confidence',
                    message=f"Inconsistent confidence scores (std: {std_confidence:.2f})",
                    suggestion="Review extraction process for consistency"
                ))

        return issues

    def _check_type_consistency(self, entities: List[Dict[str, Any]]) -> List[ValidationIssue]:
        """Check entity type distribution"""
        issues = []
        type_counts = Counter(entity.get('type', 'UNKNOWN') for entity in entities)

        # Warn if too many unknown types
        unknown_count = type_counts.get('UNKNOWN', 0)
        if unknown_count > len(entities) * 0.2:  # More than 20% unknown
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='many_unknown_types',
                message=f"Many unknown entity types: {unknown_count}/{len(entities)}",
                suggestion="Review entity type classification"
            ))

        return issues

class CDMResultValidator:
    """Main result validator that combines all validation checks"""

    def __init__(self):
        self.entity_validator = EntityValidator()
        self.consistency_checker = ResultConsistencyChecker()

    def validate_results(self, entities: List[Dict[str, Any]],
                        context: Dict[str, Any] = None) -> ValidationResult:
        """
        Validate complete extraction results

        Args:
            entities: List of extracted entities
            context: Additional context about the extraction

        Returns:
            Complete validation result
        """
        context = context or {}
        all_issues = []

        # Validate individual entities
        for i, entity in enumerate(entities):
            entity_issues = self.entity_validator.validate_entity(entity, i)
            all_issues.extend(entity_issues)

        # Check consistency across entities
        consistency_issues = self.consistency_checker.check_consistency(entities)
        all_issues.extend(consistency_issues)

        # Additional validation checks
        additional_issues = self._additional_validations(entities, context)
        all_issues.extend(additional_issues)

        # Count issues by severity
        critical_count = sum(1 for issue in all_issues if issue.level == ValidationLevel.CRITICAL)
        error_count = sum(1 for issue in all_issues if issue.level == ValidationLevel.ERROR)

        is_valid = critical_count == 0 and error_count == 0

        # Create summary
        summary = self._create_summary(entities, all_issues)

        # Generate recommendations
        recommendations = self._generate_recommendations(all_issues, summary)

        result = ValidationResult(
            is_valid=is_valid,
            total_entities=len(entities),
            valid_entities=len(entities) - error_count - critical_count,
            issues=all_issues,
            summary=summary,
            recommendations=recommendations,
            validation_metadata={
                'validation_timestamp': context.get('timestamp'),
                'source_file': context.get('source_file'),
                'extraction_model': context.get('model_used')
            }
        )

        logger.info(f"🔍 Result validation: {is_valid}, "
                   f"issues: {len(all_issues)} (E:{error_count}, W:{sum(1 for issue in all_issues if issue.level == ValidationLevel.WARNING)})")

        return result

    def _additional_validations(self, entities: List[Dict[str, Any]],
                              context: Dict[str, Any]) -> List[ValidationIssue]:
        """Additional validation checks"""
        issues = []

        # Check if we have enough entities (context-dependent)
        expected_min = context.get('expected_min_entities', 1)
        if len(entities) < expected_min:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='insufficient_entities',
                message=f"Too few entities extracted: {len(entities)} < {expected_min}",
                suggestion="Adjust extraction parameters or check input quality"
            ))

        # Check if we have too many entities (might indicate over-extraction)
        expected_max = context.get('expected_max_entities', 1000)
        if len(entities) > expected_max:
            issues.append(ValidationIssue(
                level=ValidationLevel.INFO,
                category='excessive_entities',
                message=f"Many entities extracted: {len(entities)} > {expected_max}",
                suggestion="Review for potential over-extraction"
            ))

        return issues

    def _create_summary(self, entities: List[Dict[str, Any]],
                       issues: List[ValidationIssue]) -> Dict[str, Any]:
        """Create validation summary"""
        issue_counts = Counter(issue.category for issue in issues)
        level_counts = Counter(issue.level.value for issue in issues)

        type_counts = Counter(entity.get('type', 'UNKNOWN') for entity in entities)
        confidences = [entity.get('confidence', 0.0) for entity in entities if entity.get('confidence') is not None]

        summary = {
            'total_entities': len(entities),
            'total_issues': len(issues),
            'issues_by_category': dict(issue_counts),
            'issues_by_level': dict(level_counts),
            'entity_types': dict(type_counts),
            'confidence_stats': {
                'mean': statistics.mean(confidences) if confidences else 0.0,
                'min': min(confidences) if confidences else 0.0,
                'max': max(confidences) if confidences else 0.0,
                'median': statistics.median(confidences) if confidences else 0.0
            }
        }

        return summary

    def _generate_recommendations(self, issues: List[ValidationIssue],
                                summary: Dict[str, Any]) -> List[str]:
        """Generate improvement recommendations"""
        recommendations = []

        # Based on issue patterns
        issue_categories = [issue.category for issue in issues]
        issue_levels = [issue.level for issue in issues]

        if ValidationLevel.ERROR in issue_levels or ValidationLevel.CRITICAL in issue_levels:
            recommendations.append("🚨 Fix critical errors before using results")

        if 'invalid_confidence' in issue_categories:
            recommendations.append("📊 Ensure all confidence scores are between 0.0 and 1.0")

        if 'low_confidence' in issue_categories:
            recommendations.append("🎯 Consider increasing confidence threshold")

        if 'invalid_type' in issue_categories:
            recommendations.append("🏷️  Review entity type classification")

        if 'exact_duplicates' in issue_categories:
            recommendations.append("🔄 Run deduplication process")

        if summary['confidence_stats']['mean'] < 0.6:
            recommendations.append("📈 Improve extraction quality - average confidence low")

        if summary.get('entity_types', {}).get('UNKNOWN', 0) > 0:
            recommendations.append("🔍 Review entities with UNKNOWN type")

        if not recommendations:
            recommendations.append("✅ Results appear to be good quality")

        return recommendations

    def save_validation_report(self, result: ValidationResult, output_file: str):
        """Save validation report to file"""
        report = {
            'validation_summary': {
                'is_valid': result.is_valid,
                'total_entities': result.total_entities,
                'valid_entities': result.valid_entities,
                'total_issues': len(result.issues)
            },
            'detailed_summary': result.summary,
            'issues': [
                {
                    'level': issue.level.value,
                    'category': issue.category,
                    'message': issue.message,
                    'entity_index': issue.entity_index,
                    'entity_type': issue.entity_type,
                    'suggestion': issue.suggestion
                }
                for issue in result.issues
            ],
            'recommendations': result.recommendations,
            'metadata': result.validation_metadata
        }

        try:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            logger.info(f"📋 Validation report saved to {output_file}")
        except Exception as e:
            logger.error(f"Failed to save validation report: {e}")

# Utility functions
def create_default_validator() -> CDMResultValidator:
    """Create a default result validator"""
    return CDMResultValidator()

def validate_extraction_results(entities: List[Dict[str, Any]],
                               context: Dict[str, Any] = None) -> ValidationResult:
    """Convenience function to validate extraction results"""
    validator = create_default_validator()
    return validator.validate_results(entities, context)