#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for core/models.py - specifically the FormattableResult base class."""

import pytest
from abc import ABC


class TestFormattableResult:
    """Tests for the FormattableResult abstract base class."""

    def test_formattable_result_is_abstract(self):
        """FormattableResult should be an abstract base class."""
        from core.models import FormattableResult
        assert issubclass(FormattableResult, ABC)

    def test_formattable_result_has_format_method(self):
        """FormattableResult should define a format() method."""
        from core.models import FormattableResult
        assert hasattr(FormattableResult, 'format')

    def test_citation_result_is_formattable(self):
        """CitationResult should inherit from FormattableResult."""
        from core.models import CitationResult, FormattableResult
        assert issubclass(CitationResult, FormattableResult)

    def test_injection_result_is_formattable(self):
        """InjectionResult should inherit from FormattableResult."""
        from core.models import InjectionResult, FormattableResult
        assert issubclass(InjectionResult, FormattableResult)

    def test_decay_result_is_formattable(self):
        """DecayResult should inherit from FormattableResult."""
        from core.models import DecayResult, FormattableResult
        assert issubclass(DecayResult, FormattableResult)

    def test_handoff_complete_result_is_formattable(self):
        """HandoffCompleteResult should inherit from FormattableResult."""
        from core.models import HandoffCompleteResult, FormattableResult
        assert issubclass(HandoffCompleteResult, FormattableResult)

    def test_handoff_resume_result_is_formattable(self):
        """HandoffResumeResult should inherit from FormattableResult."""
        from core.models import HandoffResumeResult, FormattableResult
        assert issubclass(HandoffResumeResult, FormattableResult)

    def test_validation_result_is_formattable(self):
        """ValidationResult should inherit from FormattableResult."""
        from core.models import ValidationResult, FormattableResult
        assert issubclass(ValidationResult, FormattableResult)

    def test_relevance_result_is_formattable(self):
        """RelevanceResult should inherit from FormattableResult."""
        from core.models import RelevanceResult, FormattableResult
        assert issubclass(RelevanceResult, FormattableResult)

    def test_all_results_have_format(self):
        """All result classes should have a format() method."""
        from core.models import (
            CitationResult, InjectionResult, DecayResult,
            HandoffCompleteResult, HandoffResumeResult, ValidationResult,
            RelevanceResult, FormattableResult
        )
        result_classes = [
            CitationResult, InjectionResult, DecayResult,
            HandoffCompleteResult, HandoffResumeResult, ValidationResult,
            RelevanceResult
        ]
        for cls in result_classes:
            assert hasattr(cls, 'format'), f"{cls.__name__} missing format() method"

    def test_cannot_instantiate_formattable_result_directly(self):
        """FormattableResult should not be directly instantiable."""
        from core.models import FormattableResult
        with pytest.raises(TypeError):
            FormattableResult()
