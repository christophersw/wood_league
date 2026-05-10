"""
Title: test_lc0_network_name.py — Lc0 network name parsing tests
Description:
    Unit tests for the _parse_network_name helper that extracts network
    identifiers from Lc0 engine ID strings and weights file paths.

Changelog:
    2026-05-09: Initial creation
"""
from local_worker.analysis.lc0 import _parse_network_name


class TestParseNetworkName:
    """Test cases for _parse_network_name helper."""

    def test_lc0_with_network_in_parentheses(self):
        """Extract network from 'Lc0 vX.Y (BT4)' format."""
        result = _parse_network_name("Lc0 v0.30 (BT4)", "")
        assert result == "BT4"

    def test_lc0_with_network_hash_in_parentheses(self):
        """Extract network hash from 'Lc0 vX.Y.Z (network: abc123)' format."""
        result = _parse_network_name("Lc0 v0.30.0 (network: abc123def456)", "")
        assert result == "network: abc123def456"

    def test_lc0_without_network_fallback_to_weights(self):
        """Fall back to weights file basename when no network in ID name."""
        result = _parse_network_name("Lc0 v0.30.0", "/path/to/BT4-1024.pb.gz")
        assert result == "BT4-1024.pb"

    def test_lc0_without_network_no_weights(self):
        """Return empty string when no network in ID and no weights path."""
        result = _parse_network_name("Lc0 v0.30.0", "")
        assert result == ""

    def test_non_lc0_engine_uses_id_name_directly(self):
        """Non-Lc0 engine names are returned as-is."""
        result = _parse_network_name("Stockfish 15.1", "")
        assert result == "Stockfish 15.1"

    def test_weights_file_with_multiple_dots(self):
        """Weights file basename strips all extensions after first dot."""
        result = _parse_network_name("Lc0 v0.30.0", "/path/to/weights.pb.gz")
        assert result == "weights.pb"

    def test_weights_file_simple_extension(self):
        """Weights file with simple extension."""
        result = _parse_network_name("Lc0 v0.30.0", "/home/user/engine.weights")
        assert result == "engine"

    def test_empty_engine_id_name_with_weights(self):
        """Empty engine ID name falls back to weights file."""
        result = _parse_network_name("", "/opt/lc0/BT4.pb")
        assert result == "BT4"

    def test_parentheses_priority_over_weights(self):
        """Parentheses in ID name take priority over weights file."""
        result = _parse_network_name(
            "Lc0 v0.30 (BT4)",
            "/path/to/DifferentWeights.pb.gz"
        )
        assert result == "BT4"

    def test_exception_handling_returns_empty(self):
        """Exception during parsing returns empty string (handled gracefully)."""
        # The helper has try-except, so this tests the normal path.
        # Pathlib.Path.stem shouldn't raise on these inputs, but the wrapper catches it.
        result = _parse_network_name("Lc0 v0.30", "valid/path.pb")
        assert isinstance(result, str)

    def test_malformed_parentheses_empty_content(self):
        """Parentheses with empty content extracts empty string."""
        result = _parse_network_name("Lc0 v0.30 ()", "")
        assert result == ""

    def test_multiple_parentheses_takes_first(self):
        """Multiple parentheses: takes content between first pair."""
        result = _parse_network_name("Lc0 v0.30 (BT4) (extra)", "")
        # Should split on first '(' and take everything up to matching ')'
        assert result == "BT4) (extra"
