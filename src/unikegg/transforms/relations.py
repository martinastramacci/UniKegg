"""Source-preserving UniKegg acquisition and transformation routines."""

import re
from collections import Counter
from pathlib import Path

from unikegg import tsv
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.config import ARTIFACTS, RAW
from unikegg.config import PROCESSED as OUTPUT
from unikegg.identifiers import EC_RE
from unikegg.kegg_data import detail_records as leggi_record_flat_file
from unikegg.kegg_data import tabular_rows

RAW_KEGG = RAW / "kegg"
CONTROLLI = ARTIFACTS
ORGANISMI = ["hsa", "mmu", "rno", "dre", "dme", "cel", "ath", "sce", "eco", "bsu"]

# Il gene nella colonna KEGG di UniProt non e' sempre numerico: in Arabidopsis
# e' per esempio ath:AT1G01010. Una regex con soli \d+ perderebbe quei mapping.
GENE_KEGG_RE = re.compile(r"([a-z][a-z0-9]{2,4}:[^;\s]+)")


def senza_prefisso(valore: str) -> str:
    return valore.split(":", 1)[1] if ":" in valore else valore


def leggi_tsv(percorso: Path):
    yield from tabular_rows(percorso)


def leggi_output(nome_file: str) -> list[dict[str, str]]:
    with (OUTPUT / nome_file).open(encoding="utf-8", newline="") as file:
        return list(tsv.dict_reader(file))


def set_colonna(nome_file: str, colonna: str) -> set[str]:
    return {riga[colonna] for riga in leggi_output(nome_file)}


def scrivi_tsv(nome_file: str, intestazione: list[str], righe) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    righe_uniche = sorted(set(tuple(riga) for riga in righe))
    with (OUTPUT / nome_file).open("w", encoding="utf-8", newline="") as file:
        scrittore = tsv.writer(file)
        scrittore.writerow(intestazione)
        scrittore.writerows(righe_uniche)
    print(f"[03_produci_relazioni] OK: {nome_file} ({len(righe_uniche)} righe)")


def leggi_uniprot_tsv():
    yield from reviewed_rows()


def costruisci_gene_proteina():
    geni = set_colonna("gene_kegg.tsv", "kegg_gene_id")
    proteine = set_colonna("protein_uniprot.tsv", "accession")
    righe = []
    conteggi = {codice: Counter() for codice in ORGANISMI}
    for codice in ORGANISMI:
        for gene_id, up_id in leggi_tsv(RAW_KEGG / "relations" / f"{codice}_uniprot.tsv"):
            conteggi[codice]["conv_letti"] += 1
            accession = senza_prefisso(up_id)
            if gene_id not in geni:
                conteggi[codice]["conv_gene_assente"] += 1
            elif accession not in proteine:
                # Accession TrEMBL proposta da KEGG: fuori dal perimetro reviewed.
                conteggi[codice]["conv_non_reviewed"] += 1
            else:
                conteggi[codice]["conv_accettati"] += 1
                righe.append([gene_id, accession, "KEGG_CONV"])
    for row in leggi_uniprot_tsv():
        accession = row.get("Entry", "").strip()
        for gene_id in GENE_KEGG_RE.findall(row.get("KEGG", "")):
            codice = gene_id.split(":", 1)[0]
            if codice not in conteggi:
                continue
            conteggi[codice]["dr_letti"] += 1
            if accession not in proteine:
                conteggi[codice]["dr_non_reviewed"] += 1
            elif gene_id not in geni:
                conteggi[codice]["dr_gene_assente"] += 1
            else:
                conteggi[codice]["dr_accettati"] += 1
                righe.append([gene_id, accession, "UNIPROT_DR"])
    scrivi_tsv("gene_proteina.tsv", ["kegg_gene_id", "accession", "mapping_source"], righe)
    scrivi_report_gene_proteina(conteggi)


def scrivi_report_gene_proteina(conteggi: dict[str, Counter]) -> None:
    """Report per organismo degli scarti di GENE_PROTEINA, per la presentazione."""
    CONTROLLI.mkdir(parents=True, exist_ok=True)
    percorso = CONTROLLI / "report_gene_proteina.tsv"
    colonne = [
        "organismo",
        "conv_letti",
        "conv_accettati",
        "conv_scartati_non_reviewed",
        "conv_scartati_gene_assente",
        "dr_letti",
        "dr_accettati",
        "dr_scartati_non_reviewed",
        "dr_scartati_gene_assente",
    ]
    tot = Counter()
    with percorso.open("w", encoding="utf-8", newline="") as file:
        scrittore = tsv.writer(file)
        scrittore.writerow(colonne)
        for codice in ORGANISMI:
            c = conteggi[codice]
            scrittore.writerow(
                [
                    codice,
                    c["conv_letti"],
                    c["conv_accettati"],
                    c["conv_non_reviewed"],
                    c["conv_gene_assente"],
                    c["dr_letti"],
                    c["dr_accettati"],
                    c["dr_non_reviewed"],
                    c["dr_gene_assente"],
                ]
            )
            tot.update(c)
    print(f"[03_produci_relazioni] Report scarti: {percorso.resolve()}")
    print(
        f"  KEGG_CONV: {tot['conv_letti']} letti, {tot['conv_accettati']} accettati, "
        f"{tot['conv_non_reviewed']} scartati perche' l'accession non e' reviewed, "
        f"{tot['conv_gene_assente']} con gene assente."
    )
    print(
        f"  UNIPROT_DR: {tot['dr_letti']} letti, {tot['dr_accettati']} accettati, "
        f"{tot['dr_non_reviewed']} scartati perche' l'accession non e' reviewed, "
        f"{tot['dr_gene_assente']} con gene assente."
    )


def costruisci_gene_ortologia():
    geni = set_colonna("gene_kegg.tsv", "kegg_gene_id")
    ko_validi = set_colonna("ortologia_kegg.tsv", "ko_id")
    righe = []
    for codice in ORGANISMI:
        for gene_id, ko_id in leggi_tsv(RAW_KEGG / "relations" / f"{codice}_gene_ko.tsv"):
            ko = senza_prefisso(ko_id)
            if gene_id in geni and ko in ko_validi:
                righe.append([gene_id, ko])
    scrivi_tsv("gene_ortologia.tsv", ["kegg_gene_id", "ko_id"], righe)


def costruisci_gene_pathway():
    geni = set_colonna("gene_kegg.tsv", "kegg_gene_id")
    pathway_validi = set_colonna("pathway_organismo.tsv", "pathway_id")
    righe = []
    for codice in ORGANISMI:
        for gene_id, pathway_id in leggi_tsv(RAW_KEGG / "relations" / f"{codice}_gene_pathway.tsv"):
            pathway = senza_prefisso(pathway_id)
            if gene_id in geni and pathway in pathway_validi:
                righe.append([gene_id, pathway])
    scrivi_tsv("gene_pathway.tsv", ["kegg_gene_id", "pathway_id"], righe)


def costruisci_relazione_semplice(
    raw_file: str,
    out_file: str,
    intestazione: list[str],
    padre_a: tuple[str, str],
    padre_b: tuple[str, str],
    inverti: bool = False,
):
    validi_a = set_colonna(*padre_a)
    validi_b = set_colonna(*padre_b)
    righe = []
    for valore_a, valore_b in leggi_tsv(RAW_KEGG / "relations" / raw_file):
        a = senza_prefisso(valore_a)
        b = senza_prefisso(valore_b)
        if a in validi_a and b in validi_b:
            righe.append([b, a] if inverti else [a, b])
    scrivi_tsv(out_file, intestazione, righe)


def costruisci_reazione_ec():
    """Associa ogni reazione ai numeri EC del suo campo ENZYME (gia' scaricato).

    Gli EC sono tutti presenti in NUMERO_EC per costruzione (02 unisce gli EC
    UniProt e quelli KEGG); il controllo di appartenenza resta come cintura di
    sicurezza in caso di modifiche future allo script 02.
    """
    reazioni = set_colonna("reazione_kegg.tsv", "reaction_id")
    ec_validi = set_colonna("numero_ec.tsv", "ec_number")
    righe = []
    for record in leggi_record_flat_file(RAW_KEGG / "details" / "reaction", expected=reazioni):
        entry = record.get("ENTRY", [""])[0].split()
        if not entry or entry[0] not in reazioni:
            continue
        for ec_number in sorted(set(EC_RE.findall(" ".join(record.get("ENZYME", []))))):
            if ec_number in ec_validi:
                righe.append([entry[0], ec_number])
    scrivi_tsv("reazione_ec.tsv", ["reaction_id", "ec_number"], righe)


def costruisci_proteina_go_ec():
    proteine = set_colonna("protein_uniprot.tsv", "accession")
    go_validi = set_colonna("termine_go.tsv", "go_id")
    ec_validi = set_colonna("numero_ec.tsv", "ec_number")
    proteina_go = []
    proteina_ec = []
    for row in leggi_uniprot_tsv():
        accession = row.get("Entry", "").strip()
        if accession not in proteine:
            continue
        for go_id in sorted(set(re.findall(r"GO:\d{7}", row.get("Gene Ontology IDs", "")))):
            if go_id in go_validi:
                proteina_go.append([accession, go_id, "", "UniProt export"])
        for ec_number in sorted(set(EC_RE.findall(row.get("EC number", "")))):
            if ec_number in ec_validi:
                proteina_ec.append([accession, ec_number])
    scrivi_tsv(
        "proteina_go.tsv", ["accession", "go_id", "evidence_code", "evidence_source"], proteina_go
    )
    scrivi_tsv("proteina_ec.tsv", ["accession", "ec_number"], proteina_ec)


def main() -> None:
    costruisci_gene_proteina()
    costruisci_gene_ortologia()
    costruisci_gene_pathway()
    costruisci_relazione_semplice(
        "ko_reaction.tsv",
        "ortologia_reazione.tsv",
        ["ko_id", "reaction_id"],
        ("ortologia_kegg.tsv", "ko_id"),
        ("reazione_kegg.tsv", "reaction_id"),
    )
    costruisci_relazione_semplice(
        "pathway_reaction.tsv",
        "pathway_reazione.tsv",
        ["map_id", "reaction_id"],
        ("pathway_riferimento.tsv", "map_id"),
        ("reazione_kegg.tsv", "reaction_id"),
    )
    costruisci_relazione_semplice(
        "reaction_compound.tsv",
        "reazione_composto.tsv",
        ["reaction_id", "compound_id"],
        ("reazione_kegg.tsv", "reaction_id"),
        ("composto_kegg.tsv", "compound_id"),
    )
    costruisci_reazione_ec()
    costruisci_proteina_go_ec()
    print("[03_produci_relazioni] OK: tutte le 9 relazioni sono state prodotte.")


if __name__ == "__main__":
    main()
