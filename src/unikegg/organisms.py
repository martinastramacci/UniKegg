"""Curated, explicit KEGG / reviewed UniProt scopes (never inferred by name)."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Organism:
    id: int
    code: str
    taxid: str
    name: str
    kegg_taxid: str


CATALOG = tuple(
    Organism(index, *values)
    for index, values in enumerate(
        [
            ("hsa", "9606", "Homo sapiens", "9606"),
            ("mmu", "10090", "Mus musculus", "10090"),
            ("rno", "10116", "Rattus norvegicus", "10116"),
            ("dre", "7955", "Danio rerio", "7955"),
            ("dme", "7227", "Drosophila melanogaster", "7227"),
            ("cel", "6239", "Caenorhabditis elegans", "6239"),
            ("ath", "3702", "Arabidopsis thaliana", "3702"),
            ("sce", "559292", "Saccharomyces cerevisiae S288c", "559292"),
            ("eco", "83333", "Escherichia coli K-12", "511145"),
            ("bsu", "224308", "Bacillus subtilis 168", "224308"),
            ("spo", "284812", "Schizosaccharomyces pombe 972h-", "284812"),
            ("ddi", "44689", "Dictyostelium discoideum", "352472"),
            ("gga", "9031", "Gallus gallus", "9031"),
            ("xtr", "8364", "Xenopus tropicalis", "8364"),
            ("mtu", "83332", "Mycobacterium tuberculosis H37Rv", "83332"),
            ("pae", "208964", "Pseudomonas aeruginosa PAO1", "208964"),
        ],
        1,
    )
)
BY_CODE = {o.code: o for o in CATALOG}
DEFAULT_CODES = tuple(o.code for o in CATALOG)
_SELECTION = ContextVar("unikegg_organisms", default=DEFAULT_CODES)


def select(codes=None, limit=None, all_organisms=False):
    if sum([codes is not None, limit is not None, all_organisms]) > 1:
        raise ValueError("Choose only one organism selection mode")
    if limit is not None:
        if not 1 <= limit <= len(CATALOG):
            raise ValueError(f"--limit must be between 1 and {len(CATALOG)}")
        codes = [o.code for o in CATALOG[:limit]]
    elif all_organisms:
        codes = list(BY_CODE)
    elif codes is None:
        codes = DEFAULT_CODES
    elif isinstance(codes, str):
        codes = [value.strip() for value in codes.split(",")]
    codes = tuple(codes)
    if not codes or len(codes) != len(set(codes)) or set(codes) - BY_CODE.keys():
        raise ValueError("Expected distinct codes from list-organisms")
    return tuple(o.code for o in CATALOG if o.code in codes)


def active():
    return tuple(BY_CODE[code] for code in _SELECTION.get())


def active_codes():
    return _SELECTION.get()


@contextmanager
def selection(codes):
    token = _SELECTION.set(select(codes))
    try:
        yield
    finally:
        _SELECTION.reset(token)


def recorded_selection(root):
    path = Path(root) / "selection.json"
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != 1 or not isinstance(state.get("codes"), list):
        raise ValueError(f"Invalid selection manifest: {path}")
    state["codes"] = select(state["codes"])
    if state.get("status") != "complete":
        raise ValueError(f"Incomplete acquisition: {root}; resume its download first")
    return state
