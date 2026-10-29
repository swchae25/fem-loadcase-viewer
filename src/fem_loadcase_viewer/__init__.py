"""Read Nastran/OptiStruct bulk-data decks and visualise their load cases."""

from .parser import parse_deck, parse_file, nastran_float
from .model import Model, Subcase

__all__ = ["parse_deck", "parse_file", "nastran_float", "Model", "Subcase"]
__version__ = "0.1.0"
