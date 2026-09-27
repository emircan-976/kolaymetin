"""Kurallar. Modüllerin içe aktarılması kuralları kayda ekler."""

from kolaymetin.rules import format, sentence, text_level, word  # noqa: F401
from kolaymetin.rules.base import Rule, all_rules, get_rule, register

__all__ = ["Rule", "all_rules", "get_rule", "register"]
