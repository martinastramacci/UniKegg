"""Source-preserving UniKegg acquisition and transformation routines."""

import re
from collections import Counter
from pathlib import Path

from unikegg import tsv
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.config import ARTIFACTS, RAW
from unikegg.config import PROCESSED as OUTPUT
from unikegg.identifiers import EC_RE
from unikegg.kegg_data import detail_records as read_flat_records
from unikegg.kegg_data import orthology_links, tabular_rows
from unikegg.organisms import DEFAULT_CODES, active_codes
from unikegg.transforms.sorting import unique_rows

RAW_KEGG = RAW / "kegg"
REPORTS = ARTIFACTS
ORGANISMS = list(DEFAULT_CODES)

# The gene in UniProt's KEGG column is not always numeric: in Arabidopsis it is
# for example ath:AT1G01010. A regex with only \d+ would lose those mappings.
GENE_KEGG_RE = re.compile(r"([a-z][a-z0-9]{2,4}:[^;\s]+)")


def without_prefix(value: str) -> str:
    return value.split(":", 1)[1] if ":" in value else value


def read_tsv(path: Path):
    yield from tabular_rows(path)


def read_output(filename: str) -> list[dict[str, str]]:
    with (OUTPUT / filename).open(encoding="utf-8", newline="") as file:
        yield from tsv.dict_reader(file)


def column_set(filename: str, column: str) -> set[str]:
    return {row[column] for row in read_output(filename)}


def write_tsv(filename: str, header: list[str], rows) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    count = 0
    with (OUTPUT / filename).open("w", encoding="utf-8", newline="") as file:
        writer = tsv.writer(file)
        writer.writerow(header)
        for row in unique_rows(rows, len(header)):
            writer.writerow(row)
            count += 1
    print(f"[build_relationships] OK: {filename} ({count} rows)")


def read_uniprot_tsv():
    yield from reviewed_rows()


def build_gene_protein():
    genes = column_set("gene_kegg.tsv", "kegg_gene_id")
    proteins = column_set("protein_uniprot.tsv", "accession")
    counts = {code: Counter() for code in active_codes()}

    def rows():
        for code in active_codes():
            for gene_id, up_id in read_tsv(RAW_KEGG / "relations" / f"{code}_uniprot.tsv"):
                counts[code]["conv_read"] += 1
                accession = without_prefix(up_id)
                if gene_id not in genes:
                    counts[code]["conv_missing_gene"] += 1
                elif accession not in proteins:
                    # TrEMBL accession proposed by KEGG: outside reviewed scope.
                    counts[code]["conv_unreviewed"] += 1
                else:
                    counts[code]["conv_accepted"] += 1
                    yield [gene_id, accession, "KEGG_CONV"]
        for row in read_uniprot_tsv():
            accession = row.get("Entry", "").strip()
            for gene_id in GENE_KEGG_RE.findall(row.get("KEGG", "")):
                code = gene_id.split(":", 1)[0]
                if code not in counts:
                    continue
                counts[code]["dr_read"] += 1
                if accession not in proteins:
                    counts[code]["dr_unreviewed"] += 1
                elif gene_id not in genes:
                    counts[code]["dr_missing_gene"] += 1
                else:
                    counts[code]["dr_accepted"] += 1
                    yield [gene_id, accession, "UNIPROT_DR"]

    write_tsv("gene_protein.tsv", ["kegg_gene_id", "accession", "mapping_source"], rows())
    write_gene_protein_report(counts)


def write_gene_protein_report(counts: dict[str, Counter]) -> None:
    """Per-organism report of GENE_PROTEIN rejections."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / "report_gene_protein.tsv"
    columns = [
        "organism",
        "conv_read",
        "conv_accepted",
        "conv_rejected_unreviewed",
        "conv_rejected_missing_gene",
        "dr_read",
        "dr_accepted",
        "dr_rejected_unreviewed",
        "dr_rejected_missing_gene",
    ]
    total = Counter()
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = tsv.writer(file)
        writer.writerow(columns)
        for code in active_codes():
            c = counts[code]
            writer.writerow(
                [
                    code,
                    c["conv_read"],
                    c["conv_accepted"],
                    c["conv_unreviewed"],
                    c["conv_missing_gene"],
                    c["dr_read"],
                    c["dr_accepted"],
                    c["dr_unreviewed"],
                    c["dr_missing_gene"],
                ]
            )
            total.update(c)
    print(f"[build_relationships] Rejection report: {path.resolve()}")
    print(
        f"  KEGG_CONV: {total['conv_read']} read, {total['conv_accepted']} accepted, "
        f"{total['conv_unreviewed']} rejected because the accession is unreviewed, "
        f"{total['conv_missing_gene']} with missing gene."
    )
    print(
        f"  UNIPROT_DR: {total['dr_read']} read, {total['dr_accepted']} accepted, "
        f"{total['dr_unreviewed']} rejected because the accession is unreviewed, "
        f"{total['dr_missing_gene']} with missing gene."
    )


def build_gene_orthology():
    genes = column_set("gene_kegg.tsv", "kegg_gene_id")
    valid_kos = column_set("orthology_kegg.tsv", "ko_id")

    def rows():
        for code in active_codes():
            for gene_id, ko_id in read_tsv(RAW_KEGG / "relations" / f"{code}_gene_ko.tsv"):
                ko = without_prefix(ko_id)
                if gene_id in genes and ko in valid_kos:
                    yield [gene_id, ko]

    write_tsv("gene_orthology.tsv", ["kegg_gene_id", "ko_id"], rows())


def build_gene_pathway():
    genes = column_set("gene_kegg.tsv", "kegg_gene_id")
    valid_pathways = column_set("pathway_organism.tsv", "pathway_id")

    def rows():
        for code in active_codes():
            for gene_id, pathway_id in read_tsv(
                RAW_KEGG / "relations" / f"{code}_gene_pathway.tsv"
            ):
                pathway = without_prefix(pathway_id)
                if gene_id in genes and pathway in valid_pathways:
                    yield [gene_id, pathway]

    write_tsv("gene_pathway.tsv", ["kegg_gene_id", "pathway_id"], rows())


def build_simple_relationship(
    raw_file: str,
    out_file: str,
    header: list[str],
    parent_a: tuple[str, str],
    parent_b: tuple[str, str],
    invert: bool = False,
):
    valid_a = column_set(*parent_a)
    valid_b = column_set(*parent_b)

    def rows():
        for value_a, value_b in read_tsv(RAW_KEGG / "relations" / raw_file):
            a = without_prefix(value_a)
            b = without_prefix(value_b)
            if a in valid_a and b in valid_b:
                yield [b, a] if invert else [a, b]

    write_tsv(out_file, header, rows())


def build_reaction_ec():
    """Associate each reaction with the EC numbers in its ENZYME field (already downloaded).

    All ECs are present in EC_NUMBER by construction (entities.py unions UniProt
    and KEGG ECs); the membership check remains as a safety belt in case of
    future changes to entity generation.
    """
    reactions = column_set("reaction_kegg.tsv", "reaction_id")
    valid_ecs = column_set("ec_number.tsv", "ec_number")

    def rows():
        for record in read_flat_records(RAW_KEGG / "details" / "reaction", expected=reactions):
            entry = record.get("ENTRY", [""])[0].split()
            if not entry or entry[0] not in reactions:
                continue
            for ec_number in sorted(set(EC_RE.findall(" ".join(record.get("ENZYME", []))))):
                if ec_number in valid_ecs:
                    yield [entry[0], ec_number]

    write_tsv("reaction_ec.tsv", ["reaction_id", "ec_number"], rows())


def build_protein_go_ec():
    proteins = column_set("protein_uniprot.tsv", "accession")
    valid_gos = column_set("go_term.tsv", "go_id")
    valid_ecs = column_set("ec_number.tsv", "ec_number")

    def go_rows():
        for row in read_uniprot_tsv():
            accession = row.get("Entry", "").strip()
            if accession in proteins:
                for go_id in sorted(set(re.findall(r"GO:\d{7}", row.get("Gene Ontology IDs", "")))):
                    if go_id in valid_gos:
                        yield [accession, go_id]

    def ec_rows():
        for row in read_uniprot_tsv():
            accession = row.get("Entry", "").strip()
            if accession in proteins:
                for ec_number in sorted(set(EC_RE.findall(row.get("EC number", "")))):
                    if ec_number in valid_ecs:
                        yield [accession, ec_number]

    write_tsv(
        "protein_go.tsv", ["accession", "go_id"], go_rows()
    )
    write_tsv("protein_ec.tsv", ["accession", "ec_number"], ec_rows())


def main() -> None:
    build_gene_protein()
    build_gene_orthology()
    build_gene_pathway()
    write_tsv(
        "orthology_pathway.tsv", ["ko_id", "map_id"], orthology_links(RAW_KEGG, "pathway")
    )
    write_tsv("orthology_ec.tsv", ["ko_id", "ec_number"], orthology_links(RAW_KEGG, "ec"))
    build_simple_relationship(
        "ko_reaction.tsv",
        "orthology_reaction.tsv",
        ["ko_id", "reaction_id"],
        ("orthology_kegg.tsv", "ko_id"),
        ("reaction_kegg.tsv", "reaction_id"),
    )
    build_simple_relationship(
        "pathway_reaction.tsv",
        "pathway_reaction.tsv",
        ["map_id", "reaction_id"],
        ("pathway_reference.tsv", "map_id"),
        ("reaction_kegg.tsv", "reaction_id"),
    )
    build_simple_relationship(
        "reaction_compound.tsv",
        "reaction_compound.tsv",
        ["reaction_id", "compound_id"],
        ("reaction_kegg.tsv", "reaction_id"),
        ("compound_kegg.tsv", "compound_id"),
    )
    build_reaction_ec()
    build_protein_go_ec()
    print("[build_relationships] OK: all 11 relationships have been produced.")


if __name__ == "__main__":
    main()
