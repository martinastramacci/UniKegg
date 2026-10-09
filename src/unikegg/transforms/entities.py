"""Source-preserving UniKegg acquisition and transformation routines."""

import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from unikegg import tsv
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.config import PROCESSED as OUTPUT
from unikegg.config import RAW
from unikegg.identifiers import EC_RE
from unikegg.kegg_data import detail_records as read_flat_records
from unikegg.kegg_data import orthology_links, preflight, tabular_rows
from unikegg.organisms import active, recorded_selection

RAW_KEGG = RAW / "kegg"

# Identificatore locale e codice KEGG: scelta del progetto (quali organismi).
# taxonomy_id e nome scientifico sono invece ricavati dai dati.
ORGANISMS = [(o.id, o.code) for o in active()]
ORGANISM_BY_CODE = {codice: org_id for org_id, codice in ORGANISMS}
ORGANISM_BY_TAXID: dict[str, int] = {}  # taxid (str) -> organism_id; riempito da build_organisms()
PROTEIN_ACCESSIONS: set[str] = set()  # accession reviewed; riempito da build_uniprot_proteins()
EC_KEGG: set[str] = set()  # EC dalle reazioni e dai link diretti KO -> EC.

# Valori letterali del campo Sequence= di UniProt e loro traduzione nel
# dominio ENUM dello schema. Nel TSV il quarto caso non appare come
# letterale ma come identificatore di feature (Sequence=VSP_012345) e
# va tradotto in DESCRIBED. Non esiste alcun valore UniProt "VSP_DESCRIBED".
LITERAL_STATUSES = {
    "Displayed": "DISPLAYED",
    "External": "EXTERNAL",
    "Not described": "NOT_DESCRIBED",
}
ISOFORM_RE = re.compile(r"^[A-Z0-9]{6,10}-[1-9][0-9]*$")
XREF_KEGG_RE = re.compile(r"([a-z][a-z0-9]{2,4}):[^;\s]+")


def clean_text(valore: str | None) -> str:
    if valore is None:
        return ""
    return re.sub(r"\s+", " ", valore).strip()


def write_tsv(nome_file: str, intestazione: list[str], rows) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    percorso = OUTPUT / nome_file
    conteggio = 0
    with percorso.open("w", encoding="utf-8", newline="") as file:
        scrittore = tsv.writer(file)
        scrittore.writerow(intestazione)
        for riga in rows:
            scrittore.writerow(["" if valore is None else valore for valore in riga])
            conteggio += 1
    print(f"[build_entities] OK: {nome_file} ({conteggio} rows)")


def read_tsv(percorso: Path, columns=2, allow_empty=True):
    yield from tabular_rows(percorso, columns, allow_empty)


def read_uniprot_tsv():
    yield from reviewed_rows()


def record_text(record: dict, campo: str) -> str:
    return clean_text(" ".join(record.get(campo, [])))


def first_record_value(record: dict, campo: str) -> str:
    valori = record.get(campo, [])
    return clean_text(valori[0]) if valori else ""


def without_prefix(valore: str) -> str:
    return valore.split(":", 1)[1] if ":" in valore else valore


def scientific_name_from_kegg(testo: str) -> str:
    parte = testo.split(";", 1)[1].strip() if ";" in testo else testo
    parte = re.sub(r"\s*\([^)]*\)", "", parte)
    return clean_text(parte)


def split_gene(definizione: str) -> tuple[str, str]:
    testo = clean_text(definizione)
    if ";" not in testo:
        return "", testo
    sinistra, destra = testo.split(";", 1)
    return sinistra.split(",", 1)[0].strip(), destra.strip()


def build_organisms():
    """Use curated UniProt taxa for managed exports, empirical mapping for legacy raw.

    KEGG and UniProt strain scopes need not use the same taxid (eco, ddi).
    A managed export can legitimately contain zero reviewed proteins.
    """
    nomi_kegg = {}
    for _tid, descrizione in read_tsv(RAW_KEGG / "organism" / "organism_list.tsv"):
        codice = descrizione.split(";", 1)[0].strip()
        if codice in ORGANISM_BY_CODE:
            nomi_kegg[codice] = scientific_name_from_kegg(descrizione)
    mancanti = [c for c in ORGANISM_BY_CODE if c not in nomi_kegg]
    if mancanti:
        raise ValueError(f"KEGG codes missing from organism_list.tsv: {mancanti}")

    nomi_uniprot: dict[str, str] = {}
    proteine_per_taxid: Counter = Counter()
    xref_per_taxid: dict[str, Counter] = defaultdict(Counter)
    for row in read_uniprot_tsv():
        taxid = row.get("Organism (ID)", "").strip()
        if not taxid:
            continue
        nomi_uniprot.setdefault(taxid, row.get("Organism", "").strip())
        proteine_per_taxid[taxid] += 1
        for codice in XREF_KEGG_RE.findall(row.get("KEGG", "")):
            if codice in ORGANISM_BY_CODE:
                xref_per_taxid[taxid][codice] += 1

    managed = recorded_selection(Path(os.environ.get("UNIKEGG_REVIEWED_DIR", RAW / "uniprot")))

    # Voto di maggioranza: per ogni codice vince il taxid con piu' cross-ref.
    taxid_per_codice = {}
    for organism in active():
        codice = organism.code
        if managed:
            taxid_per_codice[codice] = organism.taxid
            continue
        candidati = sorted(
            (
                (conteggi[codice], taxid)
                for taxid, conteggi in xref_per_taxid.items()
                if codice in conteggi
            ),
            reverse=True,
        )
        if not candidati:
            raise ValueError(
                f"No UniProt cross-reference with prefix {codice}: cannot derive taxid"
            )
        taxid_per_codice[codice] = candidati[0][1]
    if len(set(taxid_per_codice.values())) != len(taxid_per_codice):
        raise ValueError(f"Code-to-taxid mapping is not one-to-one: {taxid_per_codice}")

    rows = []
    print("[build_entities] KEGG code to UniProt taxonomy_id mapping:")
    for organism in active():
        org_id, codice = organism.id, organism.code
        taxid = taxid_per_codice[codice]
        ORGANISM_BY_TAXID[taxid] = org_id
        rows.append([org_id, codice, taxid, nomi_kegg[codice]])
        print(
            f"  {codice} -> {taxid:<7} {nomi_kegg[codice]}"
            f" (UniProt: {nomi_uniprot.get(taxid, '?')};"
            f" proteins: {proteine_per_taxid[taxid]}; supporting cross-references: {xref_per_taxid[taxid][codice]})"
        )
    write_tsv(
        "organism.tsv", ["organism_id", "kegg_code", "taxonomy_id", "scientific_name"], rows
    )


def build_kegg_genes():
    def rows():
        for codice, organism_id in ORGANISM_BY_CODE.items():
            for riga in read_tsv(
                RAW_KEGG / "genes" / f"{codice}_genes.tsv", columns=4, allow_empty=False
            ):
                # I raw hanno 4 colonne: id, tipo, posizione, descrizione.
                # Conserviamo il tipo; la posizione genomica e' scartata per scope.
                gene_id, tipo, _posizione, descrizione = riga[:4]
                simbolo, definizione = split_gene(descrizione)
                yield [gene_id, organism_id, tipo, simbolo, definizione]

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
            sequenza = row.get("Sequence", "").strip()
            lunghezza = row.get("Length", "").strip() or str(len(sequenza))
            massa = row.get("Mass", "").replace(",", "").strip() or "0"
            yield [
                accession,
                ORGANISM_BY_TAXID[taxid],
                row.get("Entry Name", "").strip(),
                clean_text(row.get("Protein names", "")),
                lunghezza,
                massa,
                clean_text(row.get("Protein existence", "")) or "Not provided",
                row.get("Sequence version", "").strip() or "1",
                sequenza,
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
        for ko_id, descrizione in read_tsv(RAW_KEGG / "ko" / "ko_list.tsv"):
            yield [without_prefix(ko_id), descrizione.split(";", 1)[0].strip(), descrizione]

    write_tsv("orthology_kegg.tsv", ["ko_id", "name", "definition"], rows())


def build_reference_pathways():
    rows = [
        [without_prefix(map_id), nome]
        for map_id, nome in read_tsv(RAW_KEGG / "pathway" / "pathway_reference.tsv")
    ]
    write_tsv("pathway_reference.tsv", ["map_id", "name"], rows)


def build_organism_pathways():
    def rows():
        for codice, organism_id in ORGANISM_BY_CODE.items():
            for pathway_id, _nome in read_tsv(RAW_KEGG / "pathway" / f"{codice}_pathways.tsv"):
                pathway = without_prefix(pathway_id)
                if pathway.startswith(codice):
                    yield [pathway, organism_id, "map" + pathway[-5:]]

    write_tsv("pathway_organism.tsv", ["pathway_id", "organism_id", "map_id"], rows())


def build_reactions(expected=None):
    """Legge i dettagli delle reazioni e raccoglie anche gli EC (campo ENZYME).

    Gli EC finiscono in EC_KEGG e arricchiscono EC_NUMBER: l'associazione
    reazione <-> EC (tabella REACTION_EC) e' prodotta da build_relationships.
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


def extract_go_from_column(testo: str, namespace: str):
    for nome, go_id in re.findall(r"([^;\[]+)\s*\[(GO:\d{7})\]", testo or ""):
        yield go_id, clean_text(nome), namespace


def isoform_blocks(testo: str):
    """Segmenta 'Alternative products (isoforms)' in blocchi Name/IsoId/Sequence/Note.

    L'unico tag che attesta un identificatore di isoforma e' IsoId=. Il resto
    del commento (Event, Comment, Note) e' testo libero e non va mai scandito
    con espressioni regolari in cerca di codici: e' l'errore che generava
    falsi IsoId come ADAMTS-9.
    """
    blocco = None
    for token in testo.split(";"):
        chiave, sep, valore = token.partition("=")
        if not sep:
            continue
        chiave = chiave.strip()
        valore = valore.strip()
        if chiave == "Name":
            if blocco is not None:
                yield blocco
            blocco = {"name": valore, "ids": [], "sequence": "", "note": ""}
        elif blocco is not None and chiave == "IsoId":
            blocco["ids"] = [v.strip() for v in valore.split(",") if v.strip()]
        elif blocco is not None and chiave == "Sequence":
            blocco["sequence"] = valore
        elif blocco is not None and chiave == "Note":
            blocco["note"] = valore
    if blocco is not None:
        yield blocco


def isoform_status(valore: str) -> str:
    """Traduce il valore grezzo di Sequence= nel dominio ENUM dello schema."""
    if valore in LITERAL_STATUSES:
        return LITERAL_STATUSES[valore]
    if "VSP_" in valore:
        return "DESCRIBED"
    return ""


def build_go_ec_isoforms():
    go = {}
    ec_uniprot = set()
    isoforme, priorita = {}, {}
    conteggi = Counter()
    esempi_scartati = []
    for row in read_uniprot_tsv():
        for go_id, nome, ns in extract_go_from_column(
            row.get("Gene Ontology (biological process)", ""), "BP"
        ):
            go.setdefault(go_id, (nome, ns))
        for go_id, nome, ns in extract_go_from_column(
            row.get("Gene Ontology (molecular function)", ""), "MF"
        ):
            go.setdefault(go_id, (nome, ns))
        for go_id, nome, ns in extract_go_from_column(
            row.get("Gene Ontology (cellular component)", ""), "CC"
        ):
            go.setdefault(go_id, (nome, ns))
        ec_uniprot.update(EC_RE.findall(row.get("EC number", "")))
        for blocco in isoform_blocks(row.get("Alternative products (isoforms)", "")):
            stato = isoform_status(blocco["sequence"])
            if not stato:
                conteggi["stato_sconosciuto"] += 1
                continue
            for iso_id in blocco["ids"]:
                conteggi["letti"] += 1
                if not ISOFORM_RE.match(iso_id):
                    conteggi["formato_non_valido"] += 1
                    continue
                # Il genitore e' il prefisso dell'IsoId, non la entry in cui
                # compare il commento: per le isoforme External i due
                # differiscono (l'isoforma vive nell'altra entry).
                genitore = iso_id.rsplit("-", 1)[0]
                if genitore not in PROTEIN_ACCESSIONS:
                    conteggi["prefisso_assente"] += 1
                    if len(esempi_scartati) < 10:
                        esempi_scartati.append(iso_id)
                    continue
                # The numeric suffix belongs to the stored parent, unlike the
                # block position in an unrelated entry's External citation.
                candidato = [
                    iso_id,
                    genitore,
                    int(iso_id.rsplit("-", 1)[1]),
                    clean_text(blocco["name"]),
                    stato,
                    clean_text(blocco["note"]),
                ]
                fonte = row.get("Entry", "").strip()
                ordine = (fonte != genitore, fonte, tuple(candidato))
                if iso_id in isoforme:
                    conteggi["duplicati"] += 1
                    if ordine >= priorita[iso_id]:
                        continue
                # Prefer the parent's own metadata. Ties between external
                # sources have a deterministic order, independent of input order.
                isoforme[iso_id], priorita[iso_id] = candidato, ordine
    write_tsv(
        "go_term.tsv",
        ["go_id", "name", "namespace"],
        [[go_id, nome, ns] for go_id, (nome, ns) in sorted(go.items())],
    )
    ec_totali = ec_uniprot | EC_KEGG
    write_tsv("ec_number.tsv", ["ec_number"], [[valore] for valore in sorted(ec_totali)])
    print(
        f"[build_entities] EC_NUMBER: {len(ec_uniprot)} da UniProt, "
        f"{len(EC_KEGG - ec_uniprot)} aggiunti dalle reazioni KEGG, {len(ec_totali)} totali."
    )
    write_tsv(
        "protein_isoform.tsv",
        ["isoform_id", "accession", "ordinal", "name", "sequence_status", "note"],
        [isoforme[key] for key in sorted(isoforme)],
    )
    print(
        f"[build_entities] Isoforms: {conteggi['letti']} IsoIds read, {len(isoforme)} written, "
        f"{conteggi['prefisso_assente']} rejected (parent absent from PROTEIN_UNIPROT), "
        f"{conteggi['duplicati']} duplicate, {conteggi['formato_non_valido']} invalid format, "
        f"{conteggi['stato_sconosciuto']} with unknown status."
    )
    if esempi_scartati:
        print(f"[build_entities] Examples of rejected IsoIds: {', '.join(esempi_scartati)}")


def main() -> None:
    ORGANISM_BY_CODE.clear()
    ORGANISM_BY_CODE.update({o.code: o.id for o in active()})
    required = preflight(RAW_KEGG, ORGANISM_BY_CODE)
    ORGANISM_BY_TAXID.clear()
    PROTEIN_ACCESSIONS.clear()
    EC_KEGG.clear()
    EC_KEGG.update(ec for _, ec in orthology_links(RAW_KEGG, "ec"))
    build_organisms()  # riempie ORGANISM_BY_TAXID dai dati UniProt
    build_uniprot_proteins()  # riempie PROTEIN_ACCESSIONS
    build_kegg_genes()
    build_kegg_orthologies()
    build_reference_pathways()
    build_organism_pathways()
    build_reactions(required["reaction"])  # riempie EC_KEGG dal campo ENZYME
    build_compounds(required["compound"])
    build_go_ec_isoforms()
    print("[build_entities] OK: all 11 entities have been produced.")


if __name__ == "__main__":
    main()
