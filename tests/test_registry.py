import pytest

from config import settings
from rules.rule_registry import PieceRuleRegistry, UnknownPieceKindError, build_default_registry
from rules.movement_strategy import MovementStrategy


class DummyStrategy(MovementStrategy):
    def is_legal(self, dr, dc, context):
        return True


def test_register_and_get():
    registry = PieceRuleRegistry()
    strategy = DummyStrategy()
    registry.register("C", strategy)
    assert registry.get("C") is strategy


def test_unknown_kind_raises():
    registry = PieceRuleRegistry()
    with pytest.raises(UnknownPieceKindError):
        registry.get("Z")


def test_registered_kinds_reflects_custom_registration():
    registry = PieceRuleRegistry()
    registry.register("C", DummyStrategy())
    assert "C" in registry.registered_kinds()


def test_default_registry_has_standard_pieces():
    registry = build_default_registry(settings)
    for kind in ("K", "Q", "R", "B", "N", "P"):
        assert kind in registry.registered_kinds()
