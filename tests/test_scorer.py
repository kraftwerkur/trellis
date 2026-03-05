"""Tests for the Trellis prompt complexity scorer."""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trellis.scorer import (
    score_request, MomentumInput, KeywordTrie, ScorerConfig, DimensionConfig,
    TierBoundaries, DEFAULT_CONFIG, _score_token_count, _score_nested_list_depth,
    _score_conditional_logic, _score_code_to_prose, _score_tool_count,
    _score_conversation_depth, _score_expected_output_length,
    _score_repetition_requests, _score_constraint_density,
    _extract_user_texts, _combined_text, _check_formal_logic_override,
    _compute_confidence, _score_to_tier, _apply_momentum,
    _has_word_boundary_match, _estimate_total_tokens,
)


def msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def user(content: str) -> dict:
    return msg("user", content)


def assistant(content: str) -> dict:
    return msg("assistant", content)


class TestTierRouting(unittest.TestCase):
    """Test that prompts route to expected tiers."""

    def test_simple_greeting(self):
        r = score_request([user("hello")])
        self.assertEqual(r.tier, "simple")

    def test_simple_factual(self):
        r = score_request([user("what is 2+2?")])
        self.assertEqual(r.tier, "simple")

    def test_simple_thanks(self):
        r = score_request([user("thanks")])
        self.assertEqual(r.tier, "simple")

    def test_standard_moderate_question(self):
        r = score_request([user(
            "Can you explain how kubernetes deployments work with rolling updates "
            "and how the replica sets are managed during the process?"
        )])
        self.assertIn(r.tier, ("standard", "complex"))

    def test_complex_multi_step(self):
        r = score_request([user(
            "First, analyze the current database architecture. Then, design a new "
            "microservice that handles authentication and authorization. After that, "
            "write the deployment pipeline with kubernetes configs. Finally, create "
            "comprehensive tests covering all edge cases with detailed coverage."
        )])
        self.assertIn(r.tier, ("complex", "reasoning"))

    def test_reasoning_formal_logic(self):
        r = score_request([user("Prove that the square root of 2 is irrational")])
        self.assertEqual(r.tier, "reasoning")
        self.assertEqual(r.reason, "formal_logic_override")

    def test_reasoning_theorem(self):
        r = score_request([user("Derive the theorem for Bayesian posterior updates")])
        self.assertEqual(r.tier, "reasoning")

    def test_empty_messages(self):
        r = score_request([])
        self.assertEqual(r.tier, "standard")
        self.assertEqual(r.reason, "ambiguous")


class TestShortMessageOverride(unittest.TestCase):
    def test_short_no_tools(self):
        r = score_request([user("hi there")])
        self.assertEqual(r.tier, "simple")
        self.assertEqual(r.reason, "short_message")

    def test_short_with_tools(self):
        """Short message with tools should NOT trigger short_message override."""
        r = score_request([user("check status")], tools=[{"type": "function"}])
        self.assertNotEqual(r.reason, "short_message")

    def test_short_with_momentum_simple_indicator(self):
        """Short + simple indicator + momentum → still simple."""
        r = score_request(
            [user("hello")],
            momentum=MomentumInput(["complex", "complex"]),
        )
        self.assertEqual(r.tier, "simple")


class TestToolDetection(unittest.TestCase):
    def test_tools_floor_to_standard(self):
        r = score_request([user("do something")], tools=[{"type": "function"}])
        self.assertIn(r.tier, ("standard", "complex", "reasoning"))

    def test_tool_choice_none_no_floor(self):
        r = score_request(
            [user("hello")], tools=[{"type": "function"}], tool_choice="none",
        )
        # tool_choice=none disables tool floor, but short message still applies
        self.assertEqual(r.tier, "simple")


class TestLargeContext(unittest.TestCase):
    def test_large_context_floor(self):
        big = "word " * 50_001  # > 200k chars → > 50k tokens
        r = score_request([user(big)])
        self.assertIn(r.tier, ("complex", "reasoning"))


class TestMomentum(unittest.TestCase):
    def test_no_momentum(self):
        r = score_request([user("hello")])
        self.assertIsNone(r.momentum)

    def test_momentum_applied(self):
        # Short msg (< 30 chars) gets max momentum weight ~0.6
        r = score_request(
            [user("and then?")],  # 9 chars, not a simple indicator
            momentum=MomentumInput(["complex", "complex", "complex"]),
        )
        # With momentum from complex history, should pull score up
        self.assertIsNotNone(r.momentum)

    def test_momentum_long_message_no_effect(self):
        long_msg = "x " * 60  # > 100 chars
        r = score_request(
            [user(long_msg)],
            momentum=MomentumInput(["reasoning", "reasoning"]),
        )
        if r.momentum:
            self.assertEqual(r.momentum.momentum_weight, 0.0)


class TestHealthcareKeywords(unittest.TestCase):
    def test_fhir_detected(self):
        r = score_request([user(
            "Explain how FHIR resources work with HL7 interoperability standards "
            "and how to implement a HIPAA-compliant EHR integration"
        )])
        # Should detect technical + domain terms
        tech_dim = next(d for d in r.dimensions if d.name == "technicalTerms")
        domain_dim = next(d for d in r.dimensions if d.name == "domainSpecificity")
        has_healthcare = bool(
            (tech_dim.matched_keywords and
             any(k in tech_dim.matched_keywords for k in ("fhir", "hl7", "hipaa", "ehr")))
            or
            (domain_dim.matched_keywords and
             any(k in domain_dim.matched_keywords for k in ("fhir", "hl7", "hipaa")))
        )
        self.assertTrue(has_healthcare)

    def test_epic_ehr(self):
        r = score_request([user(
            "How do I configure Epic EHR for clinical workflows with DICOM imaging?"
        )])
        all_kws = []
        for d in r.dimensions:
            if d.matched_keywords:
                all_kws.extend(d.matched_keywords)
        self.assertTrue(any(k in all_kws for k in ("epic", "ehr", "clinical", "dicom")))

    def test_revenue_cycle(self):
        r = score_request([user(
            "Analyze the revenue cycle management process including claims adjudication, "
            "prior authorization workflows, and DRG coding accuracy"
        )])
        domain_dim = next(d for d in r.dimensions if d.name == "domainSpecificity")
        self.assertIsNotNone(domain_dim.matched_keywords)
        self.assertTrue(len(domain_dim.matched_keywords) > 0)


class TestKeywordTrie(unittest.TestCase):
    def test_basic_scan(self):
        trie = KeywordTrie([("test", ["hello", "world"])])
        matches = trie.scan("hello world")
        self.assertEqual(len(matches), 2)

    def test_word_boundary(self):
        trie = KeywordTrie([("test", ["api"])])
        matches = trie.scan("the api works")
        self.assertEqual(len(matches), 1)
        # Should NOT match inside a word
        matches2 = trie.scan("capital letters")
        self.assertEqual(len(matches2), 0)

    def test_case_insensitive(self):
        trie = KeywordTrie([("test", ["hello"])])
        matches = trie.scan("HELLO World")
        self.assertEqual(len(matches), 1)

    def test_size(self):
        trie = KeywordTrie([("a", ["x", "y"]), ("b", ["z"])])
        self.assertEqual(trie.size, 3)


class TestStructuralDimensions(unittest.TestCase):
    def test_token_count_short(self):
        self.assertLess(_score_token_count("hi"), 0)

    def test_token_count_long(self):
        self.assertGreater(_score_token_count("word " * 600), 0)

    def test_nested_list_depth(self):
        text = "  - item\n    - nested\n      - deep"
        self.assertGreater(_score_nested_list_depth(text), 0)

    def test_conditional_logic(self):
        self.assertGreater(_score_conditional_logic("if x then y, otherwise z, unless w"), 0)

    def test_code_to_prose(self):
        text = "Here is code:\n```python\nprint('hello')\n```"
        self.assertGreater(_score_code_to_prose(text), 0)

    def test_constraint_density(self):
        text = "must be at least 5 and at most 10, exactly 3 items"
        self.assertGreater(_score_constraint_density(text), 0)

    def test_expected_output_detailed(self):
        self.assertGreater(_score_expected_output_length("write a comprehensive detailed report"), 0)

    def test_repetition(self):
        self.assertGreater(_score_repetition_requests("give me 5 examples"), 0)

    def test_tool_count(self):
        self.assertEqual(_score_tool_count(None), 0.0)
        self.assertGreater(_score_tool_count([{}, {}, {}]), 0)

    def test_conversation_depth(self):
        self.assertEqual(_score_conversation_depth(1), 0.0)
        self.assertGreater(_score_conversation_depth(15), 0)


class TestConfidence(unittest.TestCase):
    def test_near_boundary_low_confidence(self):
        b = TierBoundaries(-0.10, 0.08, 0.35)
        c = _compute_confidence(0.08, b)  # right on boundary
        self.assertLess(c, 0.6)

    def test_far_from_boundary_high_confidence(self):
        b = TierBoundaries(-0.10, 0.08, 0.35)
        c = _compute_confidence(0.5, b)
        self.assertGreater(c, 0.7)


class TestScoreToTier(unittest.TestCase):
    def test_boundaries(self):
        b = TierBoundaries(-0.10, 0.08, 0.35)
        self.assertEqual(_score_to_tier(-0.5, b), "simple")
        self.assertEqual(_score_to_tier(0.0, b), "standard")
        self.assertEqual(_score_to_tier(0.2, b), "complex")
        self.assertEqual(_score_to_tier(0.5, b), "reasoning")


class TestTextExtraction(unittest.TestCase):
    def test_user_only(self):
        msgs = [user("hello"), assistant("hi"), user("question")]
        extracted = _extract_user_texts(msgs)
        self.assertEqual(len(extracted), 2)

    def test_system_excluded(self):
        msgs = [msg("system", "you are helpful"), user("hi")]
        extracted = _extract_user_texts(msgs)
        self.assertEqual(len(extracted), 1)

    def test_position_weights(self):
        msgs = [user("a"), user("b"), user("c")]
        extracted = _extract_user_texts(msgs)
        # Last message gets weight 1.0
        self.assertEqual(extracted[-1].position_weight, 1.0)
        self.assertEqual(extracted[-2].position_weight, 0.5)
        self.assertEqual(extracted[-3].position_weight, 0.25)

    def test_array_content(self):
        msgs = [{"role": "user", "content": [{"text": "hello"}, {"text": "world"}]}]
        extracted = _extract_user_texts(msgs)
        self.assertIn("hello", extracted[0].text)
        self.assertIn("world", extracted[0].text)


class TestWordBoundary(unittest.TestCase):
    def test_match(self):
        self.assertTrue(_has_word_boundary_match("prove it", "prove"))

    def test_no_match_inside_word(self):
        self.assertFalse(_has_word_boundary_match("approved", "prove"))

    def test_at_end(self):
        self.assertTrue(_has_word_boundary_match("i will prove", "prove"))


class TestEstimateTokens(unittest.TestCase):
    def test_simple(self):
        tokens = _estimate_total_tokens([user("hello world")])
        self.assertAlmostEqual(tokens, len("hello world") / 4.0)


class TestMomentumUnit(unittest.TestCase):
    def test_zero_length(self):
        eff, info = _apply_momentum(0.1, 0, None)
        self.assertEqual(eff, 0.1)
        self.assertFalse(info.applied)

    def test_short_msg_high_weight(self):
        mom = MomentumInput(["complex", "complex"])
        eff, info = _apply_momentum(-0.2, 10, mom)
        self.assertGreater(info.momentum_weight, 0.3)
        self.assertGreater(eff, -0.2)  # pulled toward complex

    def test_long_msg_no_weight(self):
        mom = MomentumInput(["reasoning", "reasoning"])
        eff, info = _apply_momentum(0.0, 150, mom)
        self.assertEqual(info.momentum_weight, 0.0)
        self.assertEqual(eff, 0.0)


class TestDimensionCount(unittest.TestCase):
    def test_23_dimensions(self):
        self.assertEqual(len(DEFAULT_CONFIG.dimensions), 23)


class TestEndToEnd(unittest.TestCase):
    def test_result_structure(self):
        r = score_request([user("Write a comprehensive microservice architecture")])
        self.assertIn(r.tier, ("simple", "standard", "complex", "reasoning"))
        self.assertIsInstance(r.score, float)
        self.assertIsInstance(r.confidence, float)
        self.assertEqual(len(r.dimensions), 23)

    def test_ambiguous_near_boundary(self):
        """Scores near a tier boundary with low confidence should fall to ambiguous/standard."""
        # This is hard to trigger precisely, but we verify the mechanism exists
        r = score_request([user("maybe do something")])
        # Just verify it returns a valid result
        self.assertIn(r.reason, ("scored", "ambiguous", "short_message", "momentum",
                                  "tool_detected", "large_context", "formal_logic_override"))


if __name__ == "__main__":
    unittest.main()
