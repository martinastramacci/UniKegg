"""Invented raw records for parser tests; NOT a real Swiss-Prot/KEGG export."""

import csv
import gzip
from pathlib import Path

from unikegg.transforms.entities import ORGANISMI

HEADERS = [
    "Entry",
    "Reviewed",
    "Entry Name",
    "Organism (ID)",
    "Organism",
    "KEGG",
    "Protein names",
    "Length",
    "Mass",
    "Protein existence",
    "Sequence version",
    "Sequence",
    "Gene Ontology IDs",
    "Gene Ontology (molecular function)",
    "EC number",
    "Alternative products (isoforms)",
]


def raw_tsv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join("\t".join(map(str, row)) + "\n" for row in rows), encoding="utf-8")


def raw_record(path, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key:<12}{value}\n" for key, value in fields) + "///\n", encoding="utf-8"
    )


def write_uniprot(path, proteins):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows([HEADERS, *proteins])


def generate(home):
    home = Path(home)
    kegg = home / "data/raw/kegg"
    proteins, organisms = [], []
    for index, code in ORGANISMI:
        accession, gene = f"SYN{index:06d}", f"{code}:demo1"
        proteins.append(
            [
                accession,
                "reviewed",
                f"SYN_{index}",
                9000000 + index,
                f"Synthetic {code}",
                gene + ";",
                "Synthetic protein",
                4,
                400,
                "Evidence at protein level",
                1,
                "MACK",
                "GO:0000001",
                "Synthetic function [GO:0000001]",
                "1.1.1.1; 3.5.1.n3",
                f"Name=Canonical; IsoId={accession}-1; Sequence=Displayed;",
            ]
        )
        organisms.append([f"T{90000 + index}", f"{code}; Synthetic {code}"])
        raw_tsv(
            kegg / f"genes/{code}_genes.tsv", [[gene, "CDS", "1:1..12", "demo; Synthetic gene"]]
        )
        raw_tsv(kegg / f"pathway/{code}_pathways.tsv", [[f"{code}00010", "Synthetic pathway"]])
        raw_tsv(kegg / f"relations/{code}_uniprot.tsv", [[gene, "up:" + accession]])
        raw_tsv(kegg / f"relations/{code}_gene_ko.tsv", [[gene, "ko:K00001"]])
        raw_tsv(kegg / f"relations/{code}_gene_pathway.tsv", [[gene, f"path:{code}00010"]])
    raw_tsv(kegg / "organism/organism_list.tsv", organisms)
    raw_tsv(kegg / "ko/ko_list.tsv", [["K00001", 'Synthetic "orthology"; synthetic definition']])
    raw_tsv(kegg / "pathway/pathway_reference.tsv", [["map00010", "Synthetic pathway"]])
    raw_tsv(kegg / "relations/ko_reaction.tsv", [["ko:K00001", "rn:R00001"]])
    raw_tsv(kegg / "relations/pathway_reaction.tsv", [["path:map00010", "rn:R00001"]])
    raw_tsv(kegg / "relations/reaction_compound.tsv", [["rn:R00001", "cpd:C00001"]])
    raw_record(
        kegg / "details/reaction/R00001.txt",
        [
            ("ENTRY", "R00001 Reaction"),
            ("NAME", "Synthetic reaction"),
            ("DEFINITION", "Synthetic definition"),
            ("EQUATION", "C00001 = C00001"),
            ("ENZYME", "1.1.1.1 3.5.1.n3"),
        ],
    )
    raw_record(
        kegg / "details/compound/C00001.txt",
        [
            ("ENTRY", "C00001 Compound"),
            ("NAME", "Synthetic compound;"),
            ("FORMULA", "H2O"),
            ("EXACT_MASS", "18.0106"),
            ("MOL_WEIGHT", "18.015"),
        ],
    )
    write_uniprot(home / "data/raw/uniprot/synthetic-test-only.tsv.gz", proteins)
    return proteins
