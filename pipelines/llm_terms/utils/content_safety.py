"""
Content Safety Filtering Module for Clinical-Grade CDM Pipeline
Provides filtering for high-risk medical content and compliance checking
"""

import re
import logging
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import hashlib

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    """Risk levels for medical content"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class SafetyPolicy:
    """Safety policy configuration"""
    block_personal_health_info: bool = True
    block_treatment_recommendations: bool = True
    block_dosage_information: bool = True
    block_diagnostic_advice: bool = True
    block_medical_disclaimers: bool = False  # Usually want to keep these
    require_medical_disclaimer: bool = True
    max_severity_threshold: RiskLevel = RiskLevel.MEDIUM
    preserve_research_content: bool = True

class ContentSafetyFilter:
    """Advanced content safety filtering for medical text"""

    def __init__(self, policy: SafetyPolicy = None):
        self.policy = policy or SafetyPolicy()

        # High-risk medical content patterns
        self.high_risk_patterns = {
            'treatment_recommendations': [
                r'\b(take|prescribe|administer|give|use)\s+(this|these|the)\s+(medicine|drug|medication|treatment)\b',
                r'\b(should|must|need to|have to)\s+(take|use|follow)\s+(this|the)\s+(regimen|protocol|therapy)\b',
                r'\b(dosage|dose|strength|concentration)\s+(of|is|should be)\s+\d+\s*(mg|ml|g|mcg)\b',
                r'\b(times?\s+(daily|per\s+day|a\s+day)|once|twice|three\s+times)\s+(daily|per\s+day)\b',
            ],

            'diagnostic_advice': [
                r'\b(you\s+(have|are|suffer\s+from)|diagnosed\s+with)\s+(diabetes|cancer|heart\s+disease|depression)\b',
                r'\b(symptoms|signs)\s+(indicate|suggest|mean)\s+(serious|severe|critical)\b',
                r'\b(see|consult|contact)\s+(a|your)\s+(doctor|physician|healthcare\s+provider)\s+(immediately|urgently|right\s+away)\b',
                r'\bmedical\s+emergency|urgent\s+care|immediate\s+attention\b',
            ],

            'personal_health_info': [
                r'\b(my|our|your)\s+(patient|client|user)\s+(id|number|record)\s+(is|#)\s*\w+',
                r'\b(medical\s+record|patient\s+id|health\s+record)[:\s#]*\w+',
                r'\bssn|social\s+security\s+number[:\s#]*\d{3}-?\d{2}-?\d{4}',
                r'\b(phone|telephone|mobile)[:\s#]*\d{3}-?\d{3}-?\d{4}',
            ],

            'dosage_information': [
                r'\b\d+\s*(mg|ml|g|mcg|µg|mmol|iu)\s+(per|/|each|every)\s+(day|dose|time)\b',
                r'\b(take|administer|give)\s+\d+\s*(tablets?|capsules?|pills?|doses?)\b',
                r'\b\d+\s*(times?|hours?)\s+(daily|per\s+day|a\s+day)\b',
                r'\b(mg|ml|g|mcg)\s+\/\s*(kg|lb|day|hour)\b',
            ]
        }

        # Moderate risk patterns (warnings but may be acceptable in research)
        self.moderate_risk_patterns = {
            'medical_claims': [
                r'\b(cures?|heals?|treats?|prevents?)\s+(cancer|diabetes|heart\s+disease|alzheimer)\b',
                r'\b(proven|clinically\s+proven|scientifically\s+proven)\s+(effective|results)\b',
                r'\b(100%|complete|total)\s+(cure|recovery|relief)\b',
            ],

            'product_promotion': [
                r'\b(buy|purchase|order|get)\s+(now|today|immediately)\b',
                r'\b(special\s+offer|discount|sale|promotion)\b',
                r'\b(money\s+back\s+guarantee|risk\s+free|satisfaction\s+guaranteed)\b',
            ]
        }

        # Essential medical disclaimer patterns (should be preserved)
        self.disclaimer_patterns = [
            r'\b(not\s+a\s+medical\s+professional|not\s+medical\s+advice)\b',
            r'\b(consult|speak\s+to)\s+(your|a)\s+(doctor|physician|healthcare\s+provider)\b',
            r'\b(for\s+informational\s+purposes\s+only|research\s+purposes\s+only)\b',
            r'\b(not\s+intended\s+to\s+(diagnose|treat|cure|prevent))\b',
        ]

        # Safe research content patterns
        self.research_safe_patterns = [
            r'\b(study|research|investigation|analysis|trial)\s+(shows|found|demonstrated)\b',
            r'\b(according\s+to|based\s+on)\s+(research|studies|clinical\s+trials)\b',
            r'\b(published\s+in|appears\s+in)\s+(the\s+journal|journal\s+of)\b',
            r'\b(randomized\s+controlled\s+trial|rct|double-blind)\b',
        ]

        # Pre-compiled regex patterns for performance
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for better performance"""
        self.compiled_high_risk = {}
        for category, patterns in self.high_risk_patterns.items():
            self.compiled_high_risk[category] = [
                re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for pattern in patterns
            ]

        self.compiled_moderate_risk = {}
        for category, patterns in self.moderate_risk_patterns.items():
            self.compiled_moderate_risk[category] = [
                re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for pattern in patterns
            ]

        self.compiled_disclaimers = [
            re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            for pattern in self.disclaimer_patterns
        ]

        self.compiled_research_safe = [
            re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            for pattern in self.research_safe_patterns
        ]

    def analyze_content_safety(self, text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Analyze content for safety risks and provide recommendations

        Args:
            text: Text to analyze
            context: Additional context (source, intended_use, etc.)

        Returns:
            Safety analysis with risk assessment and recommendations
        """
        analysis = {
            'overall_risk_level': RiskLevel.LOW,
            'risk_scores': {},
            'detected_issues': [],
            'recommended_actions': [],
            'safe_to_process': True,
            'content_hash': self._generate_content_hash(text),
            'preserve_content': True,
            'context': context or {}
        }

        # Check for high-risk content
        high_risk_issues = self._check_high_risk_content(text)
        if high_risk_issues:
            analysis['detected_issues'].extend(high_risk_issues)
            analysis['risk_scores']['high_risk'] = len(high_risk_issues)
            analysis['overall_risk_level'] = RiskLevel.HIGH

        # Check for moderate-risk content
        moderate_risk_issues = self._check_moderate_risk_content(text)
        if moderate_risk_issues:
            analysis['detected_issues'].extend(moderate_risk_issues)
            analysis['risk_scores']['moderate_risk'] = len(moderate_risk_issues)
            if analysis['overall_risk_level'] == RiskLevel.LOW:
                analysis['overall_risk_level'] = RiskLevel.MEDIUM

        # Check for essential disclaimers
        has_disclaimer = self._check_medical_disclaimers(text)
        analysis['has_medical_disclaimer'] = has_disclaimer

        # Check if content is research-oriented
        is_research_content = self._check_research_content(text)
        analysis['is_research_content'] = is_research_content

        # Determine if content is safe to process
        analysis['safe_to_process'] = self._determine_safe_to_process(analysis)

        # Generate recommendations
        analysis['recommended_actions'] = self._generate_recommendations(analysis)

        logger.info(f"🛡️ Content safety analysis: {analysis['overall_risk_level'].value} risk, "
                   f"safe_to_process: {analysis['safe_to_process']}, "
                   f"issues: {len(analysis['detected_issues'])}")

        return analysis

    def _check_high_risk_content(self, text: str) -> List[Dict[str, Any]]:
        """Check for high-risk medical content"""
        issues = []

        for category, patterns in self.compiled_high_risk.items():
            for pattern in patterns:
                matches = pattern.finditer(text)
                for match in matches:
                    # Get context around the match
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    context = text[start:end].strip()

                    issues.append({
                        'risk_level': RiskLevel.HIGH,
                        'category': category,
                        'pattern': pattern.pattern,
                        'match': match.group(),
                        'context': context,
                        'position': match.start(),
                        'severity': 'high'
                    })

        return issues

    def _check_moderate_risk_content(self, text: str) -> List[Dict[str, Any]]:
        """Check for moderate-risk medical content"""
        issues = []

        for category, patterns in self.compiled_moderate_risk.items():
            for pattern in patterns:
                matches = pattern.finditer(text)
                for match in matches:
                    # Get context around the match
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    context = text[start:end].strip()

                    issues.append({
                        'risk_level': RiskLevel.MEDIUM,
                        'category': category,
                        'pattern': pattern.pattern,
                        'match': match.group(),
                        'context': context,
                        'position': match.start(),
                        'severity': 'moderate'
                    })

        return issues

    def _check_medical_disclaimers(self, text: str) -> bool:
        """Check if text contains medical disclaimers"""
        for pattern in self.compiled_disclaimers:
            if pattern.search(text):
                return True
        return False

    def _check_research_content(self, text: str) -> bool:
        """Check if content is research-oriented"""
        research_matches = 0
        for pattern in self.compiled_research_safe:
            if pattern.search(text):
                research_matches += 1

        # Consider content research-oriented if multiple research patterns are found
        return research_matches >= 2

    def _determine_safe_to_process(self, analysis: Dict[str, Any]) -> bool:
        """Determine if content is safe to process based on policy and risk level"""
        risk_level = analysis['overall_risk_level']
        has_disclaimer = analysis.get('has_medical_disclaimer', False)
        is_research = analysis.get('is_research_content', False)

        # Critical risk - never safe
        if risk_level == RiskLevel.CRITICAL:
            return False

        # High risk - only safe if research content with disclaimer
        if risk_level == RiskLevel.HIGH:
            if self.policy.preserve_research_content and is_research and has_disclaimer:
                return True
            return False

        # Medium risk - safe with disclaimer or research context
        if risk_level == RiskLevel.MEDIUM:
            if has_disclaimer or is_research:
                return True
            if not self.policy.require_medical_disclaimer:
                return True
            return False

        # Low risk - generally safe
        return True

    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """Generate safety recommendations based on analysis"""
        recommendations = []
        risk_level = analysis['overall_risk_level']
        has_disclaimer = analysis.get('has_medical_disclaimer', False)
        is_research = analysis.get('is_research_content', False)

        if risk_level == RiskLevel.CRITICAL:
            recommendations.append("🚨 CRITICAL: Content contains potentially harmful medical information - DO NOT PROCESS")
            return recommendations

        if risk_level == RiskLevel.HIGH:
            if not is_research:
                recommendations.append("⚠️ HIGH RISK: Content contains treatment/diagnostic advice - requires clinical review")
            if not has_disclaimer and self.policy.require_medical_disclaimer:
                recommendations.append("📝 Add medical disclaimer: 'This is not medical advice. Consult healthcare professionals.'")
            recommendations.append("🔍 Consider manual review before processing")

        if risk_level == RiskLevel.MEDIUM:
            if not has_disclaimer and self.policy.require_medical_disclaimer:
                recommendations.append("📝 Add medical disclaimer for compliance")
            if not is_research:
                recommendations.append("🔍 Review for potentially misleading medical claims")

        if risk_level == RiskLevel.LOW:
            if is_research:
                recommendations.append("✅ Content appears suitable for research purposes")
            else:
                recommendations.append("✅ Content appears safe to process")

        # Add disclaimer recommendation if missing
        if not has_disclaimer and self.policy.require_medical_disclaimer:
            recommendations.append("ℹ️ Consider adding disclaimer for research transparency")

        return recommendations

    def _generate_content_hash(self, text: str) -> str:
        """Generate hash for content tracking and audit"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

    def filter_entities_safely(self, entities: List[Dict[str, Any]],
                             content_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Filter extracted entities based on content safety analysis

        Args:
            entities: List of extracted entities
            content_analysis: Safety analysis of source content

        Returns:
            Filtered list of entities with safety metadata
        """
        if not content_analysis.get('safe_to_process', True):
            logger.warning("🚫 Content not safe to process - no entities returned")
            return []

        filtered_entities = []
        high_risk_positions = {issue['position'] for issue in content_analysis['detected_issues']
                              if issue['risk_level'] == RiskLevel.HIGH}

        for entity in entities:
            # Check if entity is from high-risk content area
            entity_pos = entity.get('position', 0)

            # Simple proximity check (within 100 characters of high-risk content)
            is_high_risk_proximity = any(
                abs(entity_pos - pos) < 100 for pos in high_risk_positions
            )

            # Add safety metadata
            safe_entity = entity.copy()
            safe_entity['safety_metadata'] = {
                'content_risk_level': content_analysis['overall_risk_level'].value,
                'high_risk_proximity': is_high_risk_proximity,
                'content_safe': True,
                'preservation_reason': 'research_content' if content_analysis.get('is_research_content') else 'general_content'
            }

            filtered_entities.append(safe_entity)

        logger.info(f"🛡️ Entity safety filtering: {len(filtered_entities)}/{len(entities)} entities preserved")
        return filtered_entities

    def generate_compliance_report(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate compliance report for batch processing"""
        report = {
            'total_documents': len(analyses),
            'risk_distribution': {},
            'common_issues': {},
            'compliance_rate': 0.0,
            'recommendations': []
        }

        safe_count = 0
        all_issues = []

        for analysis in analyses:
            risk_level = analysis['overall_risk_level']
            report['risk_distribution'][risk_level.value] = report['risk_distribution'].get(risk_level.value, 0) + 1

            if analysis.get('safe_to_process', False):
                safe_count += 1

            # Track common issues
            for issue in analysis['detected_issues']:
                category = issue['category']
                report['common_issues'][category] = report['common_issues'].get(category, 0) + 1
                all_issues.append(issue)

        report['compliance_rate'] = (safe_count / len(analyses)) * 100 if analyses else 0

        # Generate summary recommendations
        if report['compliance_rate'] < 80:
            report['recommendations'].append("Low compliance rate - review content sources and policies")

        if report['risk_distribution'].get('high', 0) > 0:
            report['recommendations'].append("High-risk content detected - implement stricter review process")

        most_common_issue = max(report['common_issues'].items(), key=lambda x: x[1]) if report['common_issues'] else None
        if most_common_issue:
            report['recommendations'].append(f"Most common issue: {most_common_issue[0]} - consider targeted filtering")

        logger.info(f"📊 Compliance report: {report['compliance_rate']:.1f}% compliance rate")
        return report

# Utility functions for easy integration
def create_medical_safety_filter() -> ContentSafetyFilter:
    """Create a safety filter configured for medical content"""
    policy = SafetyPolicy(
        block_personal_health_info=True,
        block_treatment_recommendations=True,
        block_dosage_information=True,
        block_diagnostic_advice=True,
        require_medical_disclaimer=True,
        max_severity_threshold=RiskLevel.MEDIUM,
        preserve_research_content=True
    )
    return ContentSafetyFilter(policy)

def create_research_safety_filter() -> ContentSafetyFilter:
    """Create a safety filter configured for research content"""
    policy = SafetyPolicy(
        block_personal_health_info=True,
        block_treatment_recommendations=False,  # May be relevant for research
        block_dosage_information=False,  # May be relevant for research
        block_diagnostic_advice=False,  # May be relevant for research
        require_medical_disclaimer=False,
        max_severity_threshold=RiskLevel.HIGH,
        preserve_research_content=True
    )
    return ContentSafetyFilter(policy)