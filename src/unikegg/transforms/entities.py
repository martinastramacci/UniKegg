"""Source-preserving UniKegg acquisition and transformation routines."""

import re
from collections import Counter, defaultdict
from pathlib import Path

from unikegg import tsv
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.config import PROCESSED as OUTPUT
from unikegg.config import RAW
from unikegg.identifiers import EC_RE
from unikegg.kegg_data import detail_records as leggi_record_flat_file
from unikegg.kegg_data import preflight, tabular_rows

RAW_KEGG = RAW / "kegg"

# Identificatore locale e codice KEGG: scelta del progetto (quali organismi).
# taxonomy_id e nome scientifico sono invece ricavati dai dati.
ORGANISMI = [
    (1, "hsa"),
    (2, "mmu"),
    (3, "rno"),
    (4, "dre"),
    (5, "dme"),
    (6, "cel"),
    (7, "ath"),
    (8, "sce"),
    (9, "eco"),
    (10, "bsu"),
]
ORG_DA_CODICE = {codice: org_id for org_id, codice in ORGANISMI}
ORG_DA_TAXID: dict[str, int] = {}  # taxid (str) -> organism_id; riempito da costruisci_organismi()
PROTEINE_ACC: set[str] = set()  # accession reviewed; riempito da costruisci_proteine_uniprot()
EC_KEGG: set[str] = set()  # EC dal campo ENZYME delle reazioni; riempito da costruisci_reazioni()

# Valori letterali del campo Sequence= di UniProt e loro traduzione nel
# dominio ENUM dello schema. Nel TSV il quarto caso non appare come
# letterale ma come identificatore di feature (Sequence=VSP_012345) e
# va tradotto in DESCRIBED. Non esiste alcun valore UniProt "VSP_DESCRIBED".
STATI_LETTERALI = {
    "Displayed": "DISPLAYED",
    "External": "EXTERNAL",
    "Not described": "NOT_DESCRIBED",
}
ISOFORM_RE = re.compile(r"^[A-Z0-9]{6,10}-[1-9][0-9]*$")
XREF_KEGG_RE = re.compile(r"([a-z][a-z0-9]{2,4}):[^;\s]+")


def pulisci_testo(valore: str | None) -> str:
    if valore is None:
        return ""
    return re.sub(r"\s+", " ", valore).strip()


def scrivi_tsv(nome_file: str, intestazione: list[str], righe) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    percorso = OUTPUT / nome_file
    conteggio = 0
    with percorso.open("w", encoding="utf-8", newline="") as file:
        scrittore = tsv.writer(file)
        scrittore.writerow(intestazione)
        for riga in righe:
            scrittore.writerow(["" if valore is None else valore for valore in riga])
            conteggio += 1
    print(f"[02_produci_entita] OK: {nome_file} ({conteggio} righe)")


def leggi_tsv(percorso: Path, columns=2, allow_empty=True):
    yield from tabular_rows(percorso, columns, allow_empty)


def leggi_uniprot_tsv():
    yield from reviewed_rows()


def testo_record(record: dict, campo: str) -> str:
    return pulisci_testo(" ".join(record.get(campo, [])))


def primo_record(record: dict, campo: str) -> str:
    valori = record.get(campo, [])
    return pulisci_testo(valori[0]) if valori else ""


def senza_prefisso(valore: str) -> str:
    return valore.split(":", 1)[1] if ":" in valore else valore


def nome_scientifico_da_kegg(testo: str) -> str:
    parte = testo.split(";", 1)[1].strip() if ";" in testo else testo
    parte = re.sub(r"\s*\([^)]*\)", "", parte)
    return pulisci_testo(parte)


def dividi_gene(definizione: str) -> tuple[str, str]:
    testo = pulisci_testo(definizione)
    if ";" not in testo:
        return "", testo
    sinistra, destra = testo.split(";", 1)
    return sinistra.split(",", 1)[0].strip(), destra.strip()


def costruisci_organismi():
    """Ricava taxonomy_id dal TSV UniProt e lo collega al codice KEGG.

    KEGG non esporta il taxid NCBI in /list/genome; UniProt si'. Il ponte
    empirico e' la colonna KEGG del TSV UniProt: ogni cross-reference e'
    scritto come 'codice:gene' (es. hsa:10458), quindi contando i prefissi
    per taxid si ricava la coppia codice <-> taxid direttamente dai dati.
    Il caso eco e' risolto cosi' dai dati stessi: le entry UniProt di
    E. coli K-12 stanno sotto il taxid 83333 e puntano ai geni KEGG eco.
    """
    nomi_kegg = {}
    for _tid, descrizione in leggi_tsv(RAW_KEGG / "organism" / "organism_list.tsv"):
        codice = descrizione.split(";", 1)[0].strip()
        if codice in ORG_DA_CODICE:
            nomi_kegg[codice] = nome_scientifico_da_kegg(descrizione)
    mancanti = [c for c in ORG_DA_CODICE if c not in nomi_kegg]
    if mancanti:
        raise ValueError(f"Codici KEGG non trovati in organism_list.tsv: {mancanti}")

    nomi_uniprot: dict[str, str] = {}
    proteine_per_taxid: Counter = Counter()
    xref_per_taxid: dict[str, Counter] = defaultdict(Counter)
    for row in leggi_uniprot_tsv():
        taxid = row.get("Organism (ID)", "").strip()
        if not taxid:
            continue
        nomi_uniprot.setdefault(taxid, row.get("Organism", "").strip())
        proteine_per_taxid[taxid] += 1
        for codice in XREF_KEGG_RE.findall(row.get("KEGG", "")):
            if codice in ORG_DA_CODICE:
                xref_per_taxid[taxid][codice] += 1

    # Voto di maggioranza: per ogni codice vince il taxid con piu' cross-ref.
    taxid_per_codice = {}
    for codice in ORG_DA_CODICE:
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
                f"Nessun cross-reference UniProt con prefisso {codice}: taxid non ricavabile"
            )
        taxid_per_codice[codice] = candidati[0][1]
    if len(set(taxid_per_codice.values())) != len(taxid_per_codice):
        raise ValueError(f"Collegamento codice -> taxid non biettivo: {taxid_per_codice}")

    righe = []
    print("[02_produci_entita] Collegamento codice KEGG -> taxonomy_id ricavato dai dati UniProt:")
    for org_id, codice in ORGANISMI:
        taxid = taxid_per_codice[codice]
        ORG_DA_TAXID[taxid] = org_id
        righe.append([org_id, codice, taxid, nomi_kegg[codice]])
        print(
            f"  {codice} -> {taxid:<7} {nomi_kegg[codice]}"
            f" (UniProt: {nomi_uniprot.get(taxid, '?')};"
            f" proteine: {proteine_per_taxid[taxid]}; xref a sostegno: {xref_per_taxid[taxid][codice]})"
        )
    scrivi_tsv(
        "organismo.tsv", ["organism_id", "kegg_code", "taxonomy_id", "scientific_name"], righe
    )


def costruisci_geni_kegg():
    righe = []
    for codice, organism_id in ORG_DA_CODICE.items():
        for riga in leggi_tsv(
            RAW_KEGG / "genes" / f"{codice}_genes.tsv", columns=4, allow_empty=False
        ):
            # I raw hanno 4 colonne: id, tipo, posizione, descrizione.
            # Conserviamo il tipo; la posizione genomica e' scartata per scope.
            gene_id, tipo, _posizione, descrizione = riga[:4]
            simbolo, definizione = dividi_gene(descrizione)
            righe.append([gene_id, organism_id, tipo, simbolo, definizione])
    scrivi_tsv(
        "gene_kegg.tsv", ["kegg_gene_id", "organism_id", "gene_type", "symbol", "definition"], righe
    )


def costruisci_proteine_uniprot():
    if not ORG_DA_TAXID:
        raise RuntimeError("ORG_DA_TAXID vuoto: costruisci_organismi() deve girare prima.")
    righe = []
    for row in leggi_uniprot_tsv():
        accession = row.get("Entry", "").strip()
        taxid = row.get("Organism (ID)", "").strip()
        if not accession or taxid not in ORG_DA_TAXID or accession in PROTEINE_ACC:
            continue
        PROTEINE_ACC.add(accession)
        sequenza = row.get("Sequence", "").strip()
        lunghezza = row.get("Length", "").strip() or str(len(sequenza))
        massa = row.get("Mass", "").replace(",", "").strip() or "0"
        righe.append(
            [
                accession,
                ORG_DA_TAXID[taxid],
                row.get("Entry Name", "").strip(),
                pulisci_testo(row.get("Protein names", "")),
                lunghezza,
                massa,
                pulisci_testo(row.get("Protein existence", "")) or "Not provided",
                row.get("Sequence version", "").strip() or "1",
                sequenza,
            ]
        )
    scrivi_tsv(
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
        righe,
    )


def costruisci_ortologia_kegg():
    righe = []
    for ko_id, descrizione in leggi_tsv(RAW_KEGG / "ko" / "ko_list.tsv"):
        righe.append([senza_prefisso(ko_id), descrizione.split(";", 1)[0].strip(), descrizione])
    scrivi_tsv("ortologia_kegg.tsv", ["ko_id", "name", "definition"], righe)


def costruisci_pathway_riferimento():
    righe = [
        [senza_prefisso(map_id), nome]
        for map_id, nome in leggi_tsv(RAW_KEGG / "pathway" / "pathway_reference.tsv")
    ]
    scrivi_tsv("pathway_riferimento.tsv", ["map_id", "name"], righe)


def costruisci_pathway_organismo():
    righe = []
    for codice, organism_id in ORG_DA_CODICE.items():
        for pathway_id, _nome in leggi_tsv(RAW_KEGG / "pathway" / f"{codice}_pathways.tsv"):
            pathway = senza_prefisso(pathway_id)
            if pathway.startswith(codice):
                righe.append([pathway, organism_id, "map" + pathway[-5:]])
    scrivi_tsv("pathway_organismo.tsv", ["pathway_id", "organism_id", "map_id"], righe)


def costruisci_reazioni(expected=None):
    """Legge i dettagli delle reazioni e raccoglie anche gli EC (campo ENZYME).

    Gli EC finiscono in EC_KEGG e arricchiscono NUMERO_EC: l'associazione
    reazione <-> EC (tabella REAZIONE_EC) e' prodotta da 03_produci_relazioni.
    """
    righe = []
    for record in leggi_record_flat_file(RAW_KEGG / "details" / "reaction", expected):
        reaction_id = primo_record(record, "ENTRY").split()[0]
        EC_KEGG.update(EC_RE.findall(" ".join(record.get("ENZYME", []))))
        righe.append(
            [
                reaction_id,
                testo_record(record, "NAME"),
                testo_record(record, "DEFINITION"),
                testo_record(record, "EQUATION"),
            ]
        )
    scrivi_tsv("reazione_kegg.tsv", ["reaction_id", "name", "definition", "equation"], righe)


def costruisci_composti(expected=None):
    righe = []
    for record in leggi_record_flat_file(RAW_KEGG / "details" / "compound", expected):
        compound_id = primo_record(record, "ENTRY").split()[0]
        righe.append(
            [
                compound_id,
                testo_record(record, "NAME").rstrip(";"),
                testo_record(record, "FORMULA"),
                testo_record(record, "EXACT_MASS"),
                testo_record(record, "MOL_WEIGHT"),
            ]
        )
    scrivi_tsv(
        "composto_kegg.tsv",
        ["compound_id", "name", "formula", "exact_mass", "molecular_weight"],
        righe,
    )


def estrai_go_da_colonna(testo: str, namespace: str):
    for nome, go_id in re.findall(r"([^;\[]+)\s*\[(GO:\d{7})\]", testo or ""):
        yield go_id, pulisci_testo(nome), namespace


def blocchi_isoforme(testo: str):
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


def stato_isoforma(valore: str) -> str:
    """Traduce il valore grezzo di Sequence= nel dominio ENUM dello schema."""
    if valore in STATI_LETTERALI:
        return STATI_LETTERALI[valore]
    if "VSP_" in valore:
        return "DESCRIBED"
    return ""


def costruisci_go_ec_isoforme():
    if not PROTEINE_ACC:
        raise RuntimeError("PROTEINE_ACC vuoto: costruisci_proteine_uniprot() deve girare prima.")
    go = {}
    ec_uniprot = set()
    isoforme, priorita = {}, {}
    conteggi = Counter()
    esempi_scartati = []
    for row in leggi_uniprot_tsv():
        for go_id, nome, ns in estrai_go_da_colonna(
            row.get("Gene Ontology (biological process)", ""), "BP"
        ):
            go.setdefault(go_id, (nome, ns))
        for go_id, nome, ns in estrai_go_da_colonna(
            row.get("Gene Ontology (molecular function)", ""), "MF"
        ):
            go.setdefault(go_id, (nome, ns))
        for go_id, nome, ns in estrai_go_da_colonna(
            row.get("Gene Ontology (cellular component)", ""), "CC"
        ):
            go.setdefault(go_id, (nome, ns))
        ec_uniprot.update(EC_RE.findall(row.get("EC number", "")))
        for blocco in blocchi_isoforme(row.get("Alternative products (isoforms)", "")):
            stato = stato_isoforma(blocco["sequence"])
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
                if genitore not in PROTEINE_ACC:
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
                    pulisci_testo(blocco["name"]),
                    stato,
                    pulisci_testo(blocco["note"]),
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
    scrivi_tsv(
        "termine_go.tsv",
        ["go_id", "name", "namespace"],
        [[go_id, nome, ns] for go_id, (nome, ns) in sorted(go.items())],
    )
    ec_totali = ec_uniprot | EC_KEGG
    scrivi_tsv("numero_ec.tsv", ["ec_number"], [[valore] for valore in sorted(ec_totali)])
    print(
        f"[02_produci_entita] NUMERO_EC: {len(ec_uniprot)} da UniProt, "
        f"{len(EC_KEGG - ec_uniprot)} aggiunti dalle reazioni KEGG, {len(ec_totali)} totali."
    )
    scrivi_tsv(
        "protein_isoform.tsv",
        ["isoform_id", "accession", "ordinal", "name", "sequence_status", "note"],
        [isoforme[key] for key in sorted(isoforme)],
    )
    print(
        f"[02_produci_entita] Isoforme: {conteggi['letti']} IsoId letti, {len(isoforme)} scritte, "
        f"{conteggi['prefisso_assente']} scartate (prefisso non in PROTEIN_UNIPROT), "
        f"{conteggi['duplicati']} duplicate, {conteggi['formato_non_valido']} formato non valido, "
        f"{conteggi['stato_sconosciuto']} con stato sconosciuto."
    )
    if esempi_scartati:
        print(f"[02_produci_entita] Esempi di IsoId scartati: {', '.join(esempi_scartati)}")


def main() -> None:
    required = preflight(RAW_KEGG, ORG_DA_CODICE)
    ORG_DA_TAXID.clear()
    PROTEINE_ACC.clear()
    EC_KEGG.clear()
    costruisci_organismi()  # riempie ORG_DA_TAXID dai dati UniProt
    costruisci_proteine_uniprot()  # riempie PROTEINE_ACC
    costruisci_geni_kegg()
    costruisci_ortologia_kegg()
    costruisci_pathway_riferimento()
    costruisci_pathway_organismo()
    costruisci_reazioni(required["reaction"])  # riempie EC_KEGG dal campo ENZYME
    costruisci_composti(required["compound"])
    costruisci_go_ec_isoforme()
    print("[02_produci_entita] OK: tutte le 11 entita' sono state prodotte.")


if __name__ == "__main__":
    main()
