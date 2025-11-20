"""
Input Validation and Sanitization Module for Clinical Safety
Provides comprehensive input validation for the CDM pipeline
"""

import re
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class InputValidator:
    """Enhanced input validation for clinical safety"""

    def __init__(self):
        self.max_text_length = 100000  # 100KB limit
        self.min_text_length = 10      # Minimum characters

        # Forbidden patterns for security
        self.security_patterns = [
            r'<script.*?>.*?</script>',  # XSS protection
            r'javascript:',              # JS injection
            r'data:text/html',          # Data URI attacks
            r'vbscript:',               # VBScript injection
            r'on\w+\s*=',              # Event handlers
        ]

        # Medical disclaimers that should trigger warnings
        self.medical_warning_patterns = [
            r'\b(diagnos|prognosis|treatment|prescription|dosage)\b',
            r'\b(advise|recommend|suggest)\s+(medical|clinical)\b',
            r'\b(medical advice|clinical decision)\b'
        ]

        # PII/PHI patterns to flag for review
        self.pii_patterns = [
            r'\b\d{3}-\d{2}-\d{4}\b',        # SSN
            r'\b\d{3}-\d{3}-\d{4}\b',        # Phone
            r'\b\d{2}/\d{2}/\d{4}\b',        # Date MM/DD/YYYY
            r'\b\d{4}-\d{2}-\d{2}\b',        # Date YYYY-MM-DD
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'  # Email
        ]

        # Character encoding validation
        self.allowed_char_ranges = [
            (0x20, 0x7E),      # ASCII printable
            (0x09, 0x0D),      # Tab, CR, LF
            (0x00A0, 0x00FF),   # Latin-1 supplement
            (0x0370, 0x03FF),   # Greek and Coptic
            (0x0400, 0x04FF),   # Cyrillic
            (0x0590, 0x05FF),   # Hebrew
            (0x0600, 0x06FF),   # Arabic
        ]

    def validate_text_input(self, text: str, strict_mode: bool = True) -> Dict:
        """
        Comprehensive input validation

        Args:
            text: Input text to validate
            strict_mode: Whether to apply strict validation rules

        Returns:
            Dictionary containing validation results
        """
        validation_result = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'sanitized_text': text,
            'metadata': {
                'validation_timestamp': datetime.utcnow().isoformat(),
                'text_length': len(text),
                'strict_mode': strict_mode,
                'security_score': 1.0
            }
        }

        # Length validation
        length_check = self._validate_length(text)
        if not length_check['is_valid']:
            validation_result['errors'].extend(length_check['errors'])
            validation_result['is_valid'] = False
        validation_result['warnings'].extend(length_check['warnings'])

        # Security validation
        security_check = self._validate_security(text)
        if not security_check['is_valid']:
            validation_result['errors'].extend(security_check['errors'])
            validation_result['is_valid'] = False
        validation_result['metadata']['security_score'] = security_check['score']
        validation_result['warnings'].extend(security_check['warnings'])

        # Character encoding validation
        encoding_check = self._validate_encoding(text)
        if not encoding_check['is_valid']:
            validation_result['errors'].extend(encoding_check['errors'])
            validation_result['is_valid'] = False
        validation_result['warnings'].extend(encoding_check['warnings'])

        # Medical content warnings (if strict mode)
        if strict_mode:
            medical_check = self._validate_medical_content(text)
            validation_result['warnings'].extend(medical_check['warnings'])

        # PII/PHI detection
        pii_check = self._detect_pii(text)
        if pii_check['detected']:
            validation_result['warnings'].extend(pii_check['warnings'])
            if strict_mode:
                # Sanitize PII in strict mode
                validation_result['sanitized_text'] = self._sanitize_pii(text, pii_check['matches'])

        # Content analysis
        content_analysis = self._analyze_content(text)
        validation_result['metadata'].update(content_analysis)

        # Generate text hash for tracking
        validation_result['metadata']['text_hash'] = self._generate_text_hash(validation_result['sanitized_text'])

        logger.info(f"🔍 Input validation complete: {validation_result['is_valid']}, "
                   f"errors: {len(validation_result['errors'])}, "
                   f"warnings: {len(validation_result['warnings'])}, "
                   f"security_score: {validation_result['metadata']['security_score']:.2f}")

        return validation_result

    def _validate_length(self, text: str) -> Dict:
        """Validate text length"""
        result = {'is_valid': True, 'errors': [], 'warnings': []}
        text_length = len(text)

        if text_length > self.max_text_length:
            result['is_valid'] = False
            result['errors'].append(
                f"Text too long: {text_length:,} characters > {self.max_text_length:,} limit"
            )

        if text_length < self.min_text_length:
            result['is_valid'] = False
            result['errors'].append(
                f"Text too short: {text_length} characters < {self.min_text_length} minimum"
            )

        # Warn about very large inputs even if within limit
        if text_length > self.max_text_length * 0.8:
            result['warnings'].append(
                f"Large input size: {text_length:,} characters. Consider processing in chunks."
            )

        return result

    def _validate_security(self, text: str) -> Dict:
        """Validate text for security threats"""
        result = {'is_valid': True, 'errors': [], 'warnings': [], 'score': 1.0}
        text_lower = text.lower()

        security_issues = 0

        for pattern in self.security_patterns:
            matches = re.findall(pattern, text_lower, re.IGNORECASE | re.MULTILINE)
            if matches:
                security_issues += len(matches)
                result['warnings'].append(
                    f"Security pattern detected: {pattern} ({len(matches)} matches)"
                )

        # Check for potential command injection
        command_patterns = [
            r'(\$\(|\`\`|\\x[0-9a-fA-F]{2})',  # Shell commands
            r'(eval|exec|system)\s*\(',     # Code execution
            r'(rm\s+-rf|del\s+/)',           # Dangerous file operations
        ]

        for pattern in command_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                security_issues += 1
                result['errors'].append(
                    f"Dangerous command pattern detected: {pattern}"
                )
                result['is_valid'] = False

        # Calculate security score
        result['score'] = max(0.0, 1.0 - (security_issues * 0.2))

        return result

    def _validate_encoding(self, text: str) -> Dict:
        """Validate character encoding"""
        result = {'is_valid': True, 'errors': [], 'warnings': []}

        try:
            # Try UTF-8 encoding/decoding
            encoded = text.encode('utf-8')
            decoded = encoded.decode('utf-8')

            # Check for null bytes
            if '\x00' in text:
                result['warnings'].append("Null bytes detected in text")

            # Check for control characters (except common ones)
            control_chars = [c for c in text if ord(c) < 32 and c not in '\t\n\r']
            if control_chars:
                result['warnings'].append(f"Control characters detected: {len(control_chars)}")

        except UnicodeError as e:
            result['is_valid'] = False
            result['errors'].append(f"Invalid character encoding: {str(e)}")
        except Exception as e:
            result['errors'].append(f"Encoding validation error: {str(e)}")
            result['is_valid'] = False

        return result

    def _validate_medical_content(self, text: str) -> Dict:
        """Validate medical content for disclaimers"""
        result = {'warnings': []}

        for pattern in self.medical_warning_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                result['warnings'].append(
                    f"Medical content detected: {pattern} - This is a research tool, not for clinical decision making"
                )
                break  # Only need to warn once for medical content

        return result

    def _detect_pii(self, text: str) -> Dict:
        """Detect potential PII/PHI in text"""
        result = {'detected': False, 'matches': [], 'warnings': []}

        for pattern in self.pii_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                result['detected'] = True
                result['matches'].extend(matches)
                result['warnings'].append(
                    f"Potential PII/PHI detected: {len(matches)} matches of pattern {pattern}"
                )

        return result

    def _sanitize_pii(self, text: str, pii_matches: List[str]) -> str:
        """Sanitize PII from text by replacing with placeholders"""
        sanitized = text

        for match in pii_matches:
            # Replace with generic placeholder
            placeholder = self._generate_placeholder(match)
            sanitized = sanitized.replace(match, placeholder, 1)  # Only replace first occurrence

        return sanitized

    def _generate_placeholder(self, original: str) -> str:
        """Generate appropriate placeholder for PII"""
        if re.match(r'\b\d{3}-\d{2}-\d{4}\b', original):
            return "[SSN_REDACTED]"
        elif re.match(r'\b\d{3}-\d{3}-\d{4}\b', original):
            return "[PHONE_REDACTED]"
        elif re.match(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', original):
            return "[EMAIL_REDACTED]"
        elif re.match(r'\b\d{2}/\d{2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b', original):
            return "[DATE_REDACTED]"
        else:
            return "[PII_REDACTED]"

    def _analyze_content(self, text: str) -> Dict:
        """Analyze text content for metadata"""
        analysis = {
            'word_count': len(text.split()),
            'sentence_count': len(re.split(r'[.!?]+', text)),
            'paragraph_count': len(re.split(r'\n\s*\n', text)),
            'language_estimate': 'unknown'
        }

        # Simple language detection based on character patterns
        if re.search(r'[\\u0600-\\u06FF]', text):  # Arabic
            analysis['language_estimate'] = 'arabic'
        elif re.search(r'[\\u0590-\\u05FF]', text):  # Hebrew
            analysis['language_estimate'] = 'hebrew'
        elif re.search(r'[\\u0400-\\u04FF]', text):  # Cyrillic
            analysis['language_estimate'] = 'cyrillic'
        elif re.search(r'[\\u0370-\\u03FF]', text):  # Greek
            analysis['language_estimate'] = 'greek'
        elif re.search(r'[a-zA-Z]', text):  # Latin
            analysis['language_estimate'] = 'latin'

        return analysis

    def _generate_text_hash(self, text: str) -> str:
        """Generate SHA-256 hash of text for tracking"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def validate_batch_inputs(self, texts: List[str], strict_mode: bool = True) -> Dict:
        """Validate multiple texts in a batch"""
        batch_result = {
            'batch_valid': True,
            'total_texts': len(texts),
            'valid_texts': 0,
            'invalid_texts': 0,
            'individual_results': [],
            'summary': {
                'total_errors': 0,
                'total_warnings': 0,
                'average_security_score': 0.0
            }
        }

        total_security_score = 0.0

        for i, text in enumerate(texts):
            result = self.validate_text_input(text, strict_mode)
            result['text_index'] = i

            batch_result['individual_results'].append(result)

            if result['is_valid']:
                batch_result['valid_texts'] += 1
            else:
                batch_result['invalid_texts'] += 1
                batch_result['batch_valid'] = False

            batch_result['summary']['total_errors'] += len(result['errors'])
            batch_result['summary']['total_warnings'] += len(result['warnings'])
            total_security_score += result['metadata']['security_score']

        if texts:
            batch_result['summary']['average_security_score'] = total_security_score / len(texts)

        logger.info(f"🔍 Batch validation complete: {batch_result['valid_texts']}/{batch_result['total_texts']} valid")

        return batch_result