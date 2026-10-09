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

# Il gene nella colonna KEGG di UniProt non e' sempre numerico: in Arabidopsis
# e' per esempio ath:AT1G01010. Una regex con soli \d+ perderebbe quei mapping.
GENE_KEGG_RE = re.compile(r"([a-z][a-z0-9]{2,4}:[^;\s]+)")


def without_prefix(valore: str) -> str:
    return valore.split(":", 1)[1] if ":" in valore else valore


def read_tsv(percorso: Path):
    yield from tabular_rows(percorso)


def read_output(nome_file: str) -> list[dict[str, str]]:
    with (OUTPUT / nome_file).open(encoding="utf-8", newline="") as file:
        yield from tsv.dict_reader(file)


def column_set(nome_file: str, colonna: str) -> set[str]:
    return {riga[colonna] for riga in read_output(nome_file)}


def write_tsv(nome_file: str, intestazione: list[str], rows) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    count = 0
    with (OUTPUT / nome_file).open("w", encoding="utf-8", newline="") as file:
        scrittore = tsv.writer(file)
        scrittore.writerow(intestazione)
        for row in unique_rows(rows, len(intestazione)):
            scrittore.writerow(row)
            count += 1
    print(f"[build_relationships] OK: {nome_file} ({count} rows)")


def read_uniprot_tsv():
    yield from reviewed_rows()


def build_gene_protein():
    geni = column_set("gene_kegg.tsv", "kegg_gene_id")
    proteins = column_set("protein_uniprot.tsv", "accession")
    conteggi = {codice: Counter() for codice in active_codes()}

    def rows():
        for codice in active_codes():
            for gene_id, up_id in read_tsv(RAW_KEGG / "relations" / f"{codice}_uniprot.tsv"):
                conteggi[codice]["conv_read"] += 1
                accession = without_prefix(up_id)
                if gene_id not in geni:
                    conteggi[codice]["conv_missing_gene"] += 1
                elif accession not in proteins:
                    # Accession TrEMBL proposta da KEGG: fuori dal perimetro reviewed.
                    conteggi[codice]["conv_unreviewed"] += 1
                else:
                    conteggi[codice]["conv_accepted"] += 1
                    yield [gene_id, accession, "KEGG_CONV"]
        for row in read_uniprot_tsv():
            accession = row.get("Entry", "").strip()
            for gene_id in GENE_KEGG_RE.findall(row.get("KEGG", "")):
                codice = gene_id.split(":", 1)[0]
                if codice not in conteggi:
                    continue
                conteggi[codice]["dr_read"] += 1
                if accession not in proteins:
                    conteggi[codice]["dr_unreviewed"] += 1
                elif gene_id not in geni:
                    conteggi[codice]["dr_missing_gene"] += 1
                else:
                    conteggi[codice]["dr_accepted"] += 1
                    yield [gene_id, accession, "UNIPROT_DR"]

    write_tsv("gene_protein.tsv", ["kegg_gene_id", "accession", "mapping_source"], rows())
    write_gene_protein_report(conteggi)


def write_gene_protein_report(conteggi: dict[str, Counter]) -> None:
    """Report per organism degli scarti di GENE_PROTEIN, per la presentazione."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    percorso = REPORTS / "report_gene_protein.tsv"
    colonne = [
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
    tot = Counter()
    with percorso.open("w", encoding="utf-8", newline="") as file:
        scrittore = tsv.writer(file)
        scrittore.writerow(colonne)
        for codice in active_codes():
            c = conteggi[codice]
            scrittore.writerow(
                [
                    codice,
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
            tot.update(c)
    print(f"[build_relationships] Rejection report: {percorso.resolve()}")
    print(
        f"  KEGG_CONV: {tot['conv_read']} read, {tot['conv_accepted']} accepted, "
        f"{tot['conv_unreviewed']} rejected because the accession is unreviewed, "
        f"{tot['conv_missing_gene']} with missing gene."
    )
    print(
        f"  UNIPROT_DR: {tot['dr_read']} read, {tot['dr_accepted']} accepted, "
        f"{tot['dr_unreviewed']} rejected because the accession is unreviewed, "
        f"{tot['dr_missing_gene']} with missing gene."
    )


def build_gene_orthology():
    geni = column_set("gene_kegg.tsv", "kegg_gene_id")
    ko_validi = column_set("orthology_kegg.tsv", "ko_id")

    def rows():
        for codice in active_codes():
            for gene_id, ko_id in read_tsv(RAW_KEGG / "relations" / f"{codice}_gene_ko.tsv"):
                ko = without_prefix(ko_id)
                if gene_id in geni and ko in ko_validi:
                    yield [gene_id, ko]

    write_tsv("gene_orthology.tsv", ["kegg_gene_id", "ko_id"], rows())


def build_gene_pathway():
    geni = column_set("gene_kegg.tsv", "kegg_gene_id")
    pathway_validi = column_set("pathway_organism.tsv", "pathway_id")

    def rows():
        for codice in active_codes():
            for gene_id, pathway_id in read_tsv(
                RAW_KEGG / "relations" / f"{codice}_gene_pathway.tsv"
            ):
                pathway = without_prefix(pathway_id)
                if gene_id in geni and pathway in pathway_validi:
                    yield [gene_id, pathway]

    write_tsv("gene_pathway.tsv", ["kegg_gene_id", "pathway_id"], rows())


def build_simple_relationship(
    raw_file: str,
    out_file: str,
    intestazione: list[str],
    padre_a: tuple[str, str],
    padre_b: tuple[str, str],
    inverti: bool = False,
):
    validi_a = column_set(*padre_a)
    validi_b = column_set(*padre_b)

    def rows():
        for valore_a, valore_b in read_tsv(RAW_KEGG / "relations" / raw_file):
            a = without_prefix(valore_a)
            b = without_prefix(valore_b)
            if a in validi_a and b in validi_b:
                yield [b, a] if inverti else [a, b]

    write_tsv(out_file, intestazione, rows())


def build_reaction_ec():
    """Associa ogni reazione ai numeri EC del suo campo ENZYME (gia' scaricato).

    Gli EC sono tutti presenti in EC_NUMBER per costruzione (02 unisce gli EC
    UniProt e quelli KEGG); il controllo di appartenenza resta come cintura di
    sicurezza in caso di modifiche future allo script 02.
    """
    reazioni = column_set("reaction_kegg.tsv", "reaction_id")
    ec_validi = column_set("ec_number.tsv", "ec_number")

    def rows():
        for record in read_flat_records(RAW_KEGG / "details" / "reaction", expected=reazioni):
            entry = record.get("ENTRY", [""])[0].split()
            if not entry or entry[0] not in reazioni:
                continue
            for ec_number in sorted(set(EC_RE.findall(" ".join(record.get("ENZYME", []))))):
                if ec_number in ec_validi:
                    yield [entry[0], ec_number]

    write_tsv("reaction_ec.tsv", ["reaction_id", "ec_number"], rows())


def build_protein_go_ec():
    proteins = column_set("protein_uniprot.tsv", "accession")
    go_validi = column_set("go_term.tsv", "go_id")
    ec_validi = column_set("ec_number.tsv", "ec_number")

    def go_rows():
        for row in read_uniprot_tsv():
            accession = row.get("Entry", "").strip()
            if accession in proteins:
                for go_id in sorted(set(re.findall(r"GO:\d{7}", row.get("Gene Ontology IDs", "")))):
                    if go_id in go_validi:
                        yield [accession, go_id, "", "UniProt export"]

    def ec_rows():
        for row in read_uniprot_tsv():
            accession = row.get("Entry", "").strip()
            if accession in proteins:
                for ec_number in sorted(set(EC_RE.findall(row.get("EC number", "")))):
                    if ec_number in ec_validi:
                        yield [accession, ec_number]

    write_tsv(
        "protein_go.tsv", ["accession", "go_id", "evidence_code", "evidence_source"], go_rows()
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
