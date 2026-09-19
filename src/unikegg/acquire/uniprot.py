"""Source-preserving UniKegg acquisition and transformation routines."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

from unikegg.config import RAW as RAW_ROOT

RAW = RAW_ROOT / "uniprot"
URL = "https://rest.uniprot.org/uniprotkb/stream"
ORGANISMI = (
    ("9606", "hsa"),
    ("10090", "mmu"),
    ("10116", "rno"),
    ("7955", "dre"),
    ("7227", "dme"),
    ("6239", "cel"),
    ("3702", "ath"),
    ("559292", "sce"),
    ("83333", "eco"),
    ("224308", "bsu"),
)
CAMPI = (
    "accession",
    "id",
    "reviewed",
    "protein_name",
    "gene_primary",
    "gene_synonym",
    "organism_name",
    "organism_id",
    "length",
    "mass",
    "protein_existence",
    "sequence",
    "sequence_version",
    "version",
    "date_created",
    "date_modified",
    "date_sequence_modified",
    "cc_alternative_products",
    "ft_var_seq",
    "go",
    "go_id",
    "go_p",
    "go_f",
    "go_c",
    "ec",
    "xref_kegg",
    "xref_pdb",
    "rhea",
    "keyword",
    "cc_function",
    "cc_catalytic_activity",
    "cc_pathway",
    "cc_subunit",
    "cc_subcellular_location",
    "cc_ptm",
    "cc_disease",
    "cc_interaction",
    "ft_signal",
    "ft_transmem",
    "ft_domain",
    "ft_act_site",
    "ft_binding",
    "ft_mod_res",
    "ft_carbohyd",
    "ft_disulfid",
    "ft_variant",
)


def crea_url(query: str, formato: str, campi=()) -> str:
    parametri = {"query": query, "format": formato, "compressed": "true"}
    if campi:
        parametri["fields"] = ",".join(campi)
    return URL + "?" + urllib.parse.urlencode(parametri)


def controlla_gzip(percorso: Path) -> None:
    """Legge fino alla fine: un archivio troncato non diventa definitivo."""
    totale = 0
    with gzip.open(percorso, "rb") as archivio:
        while blocco := archivio.read(1024 * 1024):
            totale += len(blocco)
    if totale == 0:
        raise ValueError("archivio gzip vuoto")


def scarica(url: str, destinazione: Path, dry_run: bool) -> None:
    print("GET", url, "->", destinazione)
    if dry_run:
        return
    if destinazione.is_file() and destinazione.stat().st_size > 0:
        try:
            controlla_gzip(destinazione)
        except (OSError, EOFError, zlib.error, ValueError) as errore:
            print(f"  File esistente non integro: {errore}. Ripeto il download.")
        else:
            print("  OK: già presente e gzip integro; non riscaricato")
            return
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = destinazione.with_suffix(destinazione.suffix + ".part")
    for tentativo in range(1, 5):
        try:
            richiesta = urllib.request.Request(url, headers={"User-Agent": "UniKegg/0.1"})
            impronta = hashlib.sha256()
            byte = 0
            with (
                urllib.request.urlopen(richiesta, timeout=300) as risposta,
                temporaneo.open("wb") as out,
            ):
                while blocco := risposta.read(1024 * 1024):
                    out.write(blocco)
                    impronta.update(blocco)
                    byte += len(blocco)
            if byte == 0:
                raise ValueError("risposta vuota")
            controlla_gzip(temporaneo)
            temporaneo.replace(destinazione)
            voce = {
                "url": url,
                "file": destinazione.relative_to(RAW_ROOT).as_posix(),
                "data_utc": datetime.now(timezone.utc).isoformat(),
                "byte": byte,
                "sha256": impronta.hexdigest(),
            }
            with (RAW / "manifest.jsonl").open("a", encoding="utf-8") as manifest:
                manifest.write(json.dumps(voce, ensure_ascii=False) + "\n")
            print(f"  OK: salvati {byte} byte; gzip verificato fino alla fine")
            return
        except (
            OSError,
            ValueError,
            EOFError,
            zlib.error,
            http.client.HTTPException,
            urllib.error.URLError,
        ) as errore:
            print(f"  tentativo {tentativo}/4 fallito: {errore}")
            if tentativo == 4:
                raise RuntimeError(
                    f"Download non completato: {destinazione.name}. "
                    "Il file .part è incompleto. Rilanciare lo stesso comando; "
                    "i file definitivi integri saranno riutilizzati."
                ) from errore
            print("  Riparto dall'inizio di questo file, senza accodare dati parziali.")
            time.sleep(2**tentativo)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="mostra URL senza scaricare")
    args = parser.parse_args()
    for taxid, codice in ORGANISMI:
        query = f"(organism_id:{taxid}) AND (reviewed:true)"
        scarica(crea_url(query, "json"), RAW / f"{taxid}_{codice}.json.gz", args.dry_run)
        scarica(crea_url(query, "tsv", CAMPI), RAW / f"{taxid}_{codice}.index.tsv.gz", args.dry_run)
    print("OK: raw UniProt pianificati/completati. Nessuna trasformazione ETL eseguita.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as errore:
        raise SystemExit(f"ERRORE: {errore}")
