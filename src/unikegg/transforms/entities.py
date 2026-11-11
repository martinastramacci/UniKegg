"""Source-preserving UniKegg acquisition and transformation routines."""

import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from unikegg import tsv
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.config import PROCESSED as OUTPUT
from unikegg.config import RAW
from unikegg.enzymes import EC_FIELDS, read_catalog
from unikegg.identifiers import EC_RE, without_ec_annotations
from unikegg.kegg_data import detail_records as read_flat_records
from unikegg.kegg_data import orthology_links, preflight, tabular_rows
from unikegg.organisms import active, recorded_selection

RAW_KEGG = RAW / "kegg"

# Local identifier and KEGG code: project selection (which organisms).
# taxonomy_id and scientific name are derived from source data instead.
ORGANISMS = [(o.id, o.code) for o in active()]
ORGANISM_BY_CODE = {code: org_id for org_id, code in ORGANISMS}
ORGANISM_BY_TAXID: dict[str, int] = {}  # taxid (str) -> organism_id; populated by build_organisms()
PROTEIN_ACCESSIONS: set[str] = set()  # reviewed accessions; populated by build_uniprot_proteins()
EC_KEGG: set[str] = set()  # ECs from reactions and direct KO -> EC links.

# Literal values of the UniProt Sequence= field and their translation into the
# schema ENUM domain. In the TSV the fourth case does not appear as a literal
# but as a feature identifier (Sequence=VSP_012345) and is translated to
# DESCRIBED. There is no UniProt literal value "VSP_DESCRIBED".
LITERAL_STATUSES = {
    "Displayed": "DISPLAYED",
    "External": "EXTERNAL",
    "Not described": "NOT_DESCRIBED",
}
ISOFORM_RE = re.compile(r"^[A-Z0-9]{6,10}-[1-9][0-9]*$")
XREF_KEGG_RE = re.compile(r"([a-z][a-z0-9]{2,4}):[^;\s]+")


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def write_tsv(filename: str, header: list[str], rows) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / filename
    count = 0
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = tsv.writer(file)
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])
            count += 1
    print(f"[build_entities] OK: {filename} ({count} rows)")


def read_tsv(path: Path, columns=2, allow_empty=True):
    yield from tabular_rows(path, columns, allow_empty)


def read_uniprot_tsv():
    yield from reviewed_rows()


def record_text(record: dict, field: str) -> str:
    return clean_text(" ".join(record.get(field, [])))


def first_record_value(record: dict, field: str) -> str:
    values = record.get(field, [])
    return clean_text(values[0]) if values else ""


def without_prefix(value: str) -> str:
    return value.split(":", 1)[1] if ":" in value else value


def scientific_name_from_kegg(text: str) -> str:
    part = text.split(";", 1)[1].strip() if ";" in text else text
    part = re.sub(r"\s*\([^)]*\)", "", part)
    return clean_text(part)


def split_gene(definition: str) -> tuple[str, str]:
    text = clean_text(definition)
    if ";" not in text:
        return "", text
    left, right = text.split(";", 1)
    return left.split(",", 1)[0].strip(), right.strip()


def build_organisms():
    """Use curated UniProt taxa for managed exports, empirical mapping for legacy raw.

    KEGG and UniProt strain scopes need not use the same taxid (eco, ddi).
    A managed export can legitimately contain zero reviewed proteins.
    """
    kegg_names = {}
    for _tid, description in read_tsv(RAW_KEGG / "organism" / "organism_list.tsv"):
        code = description.split(";", 1)[0].strip()
        if code in ORGANISM_BY_CODE:
            kegg_names[code] = scientific_name_from_kegg(description)
    missing = [c for c in ORGANISM_BY_CODE if c not in kegg_names]
    if missing:
        raise ValueError(f"KEGG codes missing from organism_list.tsv: {missing}")

    uniprot_names: dict[str, str] = {}
    proteins_by_taxid: Counter = Counter()
    xrefs_by_taxid: dict[str, Counter] = defaultdict(Counter)
    for row in read_uniprot_tsv():
        taxid = row.get("Organism (ID)", "").strip()
        if not taxid:
            continue
        uniprot_names.setdefault(taxid, row.get("Organism", "").strip())
        proteins_by_taxid[taxid] += 1
        for code in XREF_KEGG_RE.findall(row.get("KEGG", "")):
            if code in ORGANISM_BY_CODE:
                xrefs_by_taxid[taxid][code] += 1

    managed = recorded_selection(Path(os.environ.get("UNIKEGG_REVIEWED_DIR", RAW / "uniprot")))

    # Majority vote: for each code, the taxid with the most cross-references wins.
    taxid_by_code = {}
    for organism in active():
        code = organism.code
        if managed:
            taxid_by_code[code] = organism.taxid
            continue
        candidates = sorted(
            (
                (counts[code], taxid)
                for taxid, counts in xrefs_by_taxid.items()
                if code in counts
            ),
            reverse=True,
        )
        if not candidates:
            raise ValueError(
                f"No UniProt cross-reference with prefix {code}: cannot derive taxid"
            )
        taxid_by_code[code] = candidates[0][1]
    if len(set(taxid_by_code.values())) != len(taxid_by_code):
        raise ValueError(f"Code-to-taxid mapping is not one-to-one: {taxid_by_code}")

    rows = []
    print("[build_entities] KEGG code to UniProt taxonomy_id mapping:")
    for organism in active():
        org_id, code = organism.id, organism.code
        taxid = taxid_by_code[code]
        ORGANISM_BY_TAXID[taxid] = org_id
        rows.append([org_id, code, taxid, kegg_names[code]])
        print(
            f"  {code} -> {taxid:<7} {kegg_names[code]}"
            f" (UniProt: {uniprot_names.get(taxid, '?')};"
            f" proteins: {proteins_by_taxid[taxid]}; supporting cross-references: {xrefs_by_taxid[taxid][code]})"
        )
    write_tsv(
        "organism.tsv", ["organism_id", "kegg_code", "taxonomy_id", "scientific_name"], rows
    )


def build_kegg_genes():
    def rows():
        for code, organism_id in ORGANISM_BY_CODE.items():
            for row in read_tsv(
                RAW_KEGG / "genes" / f"{code}_genes.tsv", columns=4, allow_empty=False
            ):
                # Raw files have 4 columns: id, type, position, description.
                # Retain the gene type; genomic position is discarded by scope.
                gene_id, gene_type, _position, description = row[:4]
                symbol, definition = split_gene(description)
                yield [gene_id, organism_id, gene_type, symbol, definition]

    write_tsv(
        "gene_kegg.tsv",
        ["kegg_gene_id", "organism_id", "gene_type", "symbol", "definition"],
        rows(),
    )


def build_uniprot_proteins():
    if not ORGANISM_BY_TAXID:
        raise RuntimeError("ORGANISM_BY_TAXID is empty: run build_organisms() first.")

    def rows():
        for row in read_uniprot_tsv():
            accession = row.get("Entry", "").strip()
            taxid = row.get("Organism (ID)", "").strip()
            if not accession or taxid not in ORGANISM_BY_TAXID or accession in PROTEIN_ACCESSIONS:
                continue
            PROTEIN_ACCESSIONS.add(accession)
            sequence = row.get("Sequence", "").strip()
            length = row.get("Length", "").strip() or str(len(sequence))
            mass = row.get("Mass", "").replace(",", "").strip() or "0"
            yield [
                accession,
                ORGANISM_BY_TAXID[taxid],
                row.get("Entry Name", "").strip(),
                without_ec_annotations(clean_text(row.get("Protein names", ""))),
                length,
                mass,
                clean_text(row.get("Protein existence", "")) or "Not provided",
                row.get("Sequence version", "").strip() or "1",
                sequence,
            ]

    write_tsv(
        "protein_uniprot.tsv",
        [
            "accession",
            "organism_id",
            "entry_name",
            "protein_name",
            "sequence_length",
            "molecular_mass",
            "protein_existence",
            "sequence_version",
            "amino_acid_sequence",
        ],
        rows(),
    )


def build_kegg_orthologies():
    def rows():
        for ko_id, description in read_tsv(RAW_KEGG / "ko" / "ko_list.tsv"):
            yield [without_prefix(ko_id), description.split(";", 1)[0].strip(), description]

    write_tsv("orthology_kegg.tsv", ["ko_id", "name", "definition"], rows())


def build_reference_pathways():
    rows = [
        [without_prefix(map_id), name]
        for map_id, name in read_tsv(RAW_KEGG / "pathway" / "pathway_reference.tsv")
    ]
    write_tsv("pathway_reference.tsv", ["map_id", "name"], rows)


def build_organism_pathways():
    def rows():
        for code, organism_id in ORGANISM_BY_CODE.items():
            for pathway_id, _name in read_tsv(RAW_KEGG / "pathway" / f"{code}_pathways.tsv"):
                pathway = without_prefix(pathway_id)
                if pathway.startswith(code):
                    yield [pathway, organism_id, "map" + pathway[-5:]]

    write_tsv("pathway_organism.tsv", ["pathway_id", "organism_id", "map_id"], rows())


def build_reactions(expected=None):
    """Read reaction details and collect EC numbers (ENZYME field).

    Collected ECs are added to EC_KEGG and enrich EC_NUMBER; the reaction <-> EC
    association (table REACTION_EC) is produced by build_relationships.
    """

    def rows():
        for record in read_flat_records(RAW_KEGG / "details" / "reaction", expected):
            reaction_id = first_record_value(record, "ENTRY").split()[0]
            EC_KEGG.update(EC_RE.findall(" ".join(record.get("ENZYME", []))))
            yield [
                reaction_id,
                record_text(record, "NAME"),
                record_text(record, "DEFINITION"),
                record_text(record, "EQUATION"),
            ]

    write_tsv("reaction_kegg.tsv", ["reaction_id", "name", "definition", "equation"], rows())


def build_compounds(expected=None):
    def rows():
        for record in read_flat_records(RAW_KEGG / "details" / "compound", expected):
            compound_id = first_record_value(record, "ENTRY").split()[0]
            yield [
                compound_id,
                record_text(record, "NAME").rstrip(";"),
                record_text(record, "FORMULA"),
                record_text(record, "EXACT_MASS"),
                record_text(record, "MOL_WEIGHT"),
            ]

    write_tsv(
        "compound_kegg.tsv",
        ["compound_id", "name", "formula", "exact_mass", "molecular_weight"],
        rows(),
    )


def extract_go_from_column(text: str, namespace: str):
    for name, go_id in re.findall(r"([^;\[]+)\s*\[(GO:\d{7})\]", text or ""):
        yield go_id, clean_text(name), namespace


def isoform_blocks(text: str):
    """Segment 'Alternative products (isoforms)' into Name/IsoId/Sequence/Note blocks.

    The only tag that attests an isoform identifier is IsoId=. The rest of the
    comment (Event, Comment, Note) is free text and must never be scanned with
    regular expressions looking for codes: that mistake generated false IsoIds
    such as ADAMTS-9.
    """
    block = None
    for token in text.split(";"):
        key, sep, value = token.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key == "Name":
            if block is not None:
                yield block
            block = {"name": value, "ids": [], "sequence": "", "note": ""}
        elif block is not None and key == "IsoId":
            block["ids"] = [v.strip() for v in value.split(",") if v.strip()]
        elif block is not None and key == "Sequence":
            block["sequence"] = value
        elif block is not None and key == "Note":
            block["note"] = value
    if block is not None:
        yield block


def isoform_status(value: str) -> str:
    """Translate the raw Sequence= value into the schema ENUM domain."""
    if value in LITERAL_STATUSES:
        return LITERAL_STATUSES[value]
    if "VSP_" in value:
        return "DESCRIBED"
    return ""


def build_go_ec_isoforms():
    go = {}
    ec_uniprot = set()
    isoforms, priorities = {}, {}
    counts = Counter()
    rejected_examples = []
    for row in read_uniprot_tsv():
        for go_id, name, ns in extract_go_from_column(
            row.get("Gene Ontology (biological process)", ""), "BP"
        ):
            go.setdefault(go_id, (name, ns))
        for go_id, name, ns in extract_go_from_column(
            row.get("Gene Ontology (molecular function)", ""), "MF"
        ):
            go.setdefault(go_id, (name, ns))
        for go_id, name, ns in extract_go_from_column(
            row.get("Gene Ontology (cellular component)", ""), "CC"
        ):
            go.setdefault(go_id, (name, ns))
        ec_uniprot.update(EC_RE.findall(row.get("EC number", "")))
        for block in isoform_blocks(row.get("Alternative products (isoforms)", "")):
            status = isoform_status(block["sequence"])
            if not status:
                counts["unknown_status"] += 1
                continue
            for iso_id in block["ids"]:
                counts["read"] += 1
                if not ISOFORM_RE.match(iso_id):
                    counts["invalid_format"] += 1
                    continue
                # The parent is the IsoId prefix, not the entry where the comment
                # appears: for External isoforms the two differ (the isoform lives
                # in the other entry).
                parent = iso_id.rsplit("-", 1)[0]
                if parent not in PROTEIN_ACCESSIONS:
                    counts["missing_prefix"] += 1
                    if len(rejected_examples) < 10:
                        rejected_examples.append(iso_id)
                    continue
                # The numeric suffix belongs to the stored parent, unlike the
                # block position in an unrelated entry's External citation.
                candidate = [
                    iso_id,
                    parent,
                    int(iso_id.rsplit("-", 1)[1]),
                    clean_text(block["name"]),
                    status,
                    clean_text(block["note"]),
                ]
                source = row.get("Entry", "").strip()
                order = (source != parent, source, tuple(candidate))
                if iso_id in isoforms:
                    counts["duplicates"] += 1
                    if order >= priorities[iso_id]:
                        continue
                # Prefer the parent's own metadata. Ties between external
                # sources have a deterministic order, independent of input order.
                isoforms[iso_id], priorities[iso_id] = candidate, order
    write_tsv(
        "go_term.tsv",
        ["go_id", "name", "namespace"],
        [[go_id, name, ns] for go_id, (name, ns) in sorted(go.items())],
    )
    total_ecs = ec_uniprot | EC_KEGG
    catalog = read_catalog(RAW_KEGG.parent / "enzyme/enzyme.rdf.xz")
    write_tsv(
        "ec_number.tsv", ["ec_number", *EC_FIELDS],
        [[value, *catalog.get(value, ["", "", ""])] for value in sorted(total_ecs)],
    )
    print(
        f"[build_entities] EC_NUMBER: {len(ec_uniprot)} from UniProt, "
        f"{len(EC_KEGG - ec_uniprot)} added from KEGG reactions/KO links, {len(total_ecs)} total."
    )
    write_tsv(
        "protein_isoform.tsv",
        ["isoform_id", "accession", "ordinal", "name", "sequence_status", "note"],
        [isoforms[key] for key in sorted(isoforms)],
    )
    print(
        f"[build_entities] Isoforms: {counts['read']} IsoIds read, {len(isoforms)} written, "
        f"{counts['missing_prefix']} rejected (parent absent from PROTEIN_UNIPROT), "
        f"{counts['duplicates']} duplicate, {counts['invalid_format']} invalid format, "
        f"{counts['unknown_status']} with unknown status."
    )
    if rejected_examples:
        print(f"[build_entities] Examples of rejected IsoIds: {', '.join(rejected_examples)}")


def main() -> None:
    ORGANISM_BY_CODE.clear()
    ORGANISM_BY_CODE.update({o.code: o.id for o in active()})
    required = preflight(RAW_KEGG, ORGANISM_BY_CODE)
    ORGANISM_BY_TAXID.clear()
    PROTEIN_ACCESSIONS.clear()
    EC_KEGG.clear()
    EC_KEGG.update(ec for _, ec in orthology_links(RAW_KEGG, "ec"))
    build_organisms()  # populates ORGANISM_BY_TAXID from UniProt data
    build_uniprot_proteins()  # populates PROTEIN_ACCESSIONS
    build_kegg_genes()
    build_kegg_orthologies()
    build_reference_pathways()
    build_organism_pathways()
    build_reactions(required["reaction"])  # populates EC_KEGG from ENZYME field
    build_compounds(required["compound"])
    build_go_ec_isoforms()
    print("[build_entities] OK: all 11 entities have been produced.")


if __name__ == "__main__":
    main()
