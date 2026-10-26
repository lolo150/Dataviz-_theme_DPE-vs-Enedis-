import csv
import io
import os

INPUT_FILE = "dataset_electrique_enrichi_2023_2024.csv"
OUTPUT_FILE = "dataset_electrique_enrichi_48mb.csv"

# Taille maximale souhaitée
MAX_SIZE_MB = 48
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

rows_kept = 0

with open(
    INPUT_FILE,
    "r",
    encoding="utf-8",
    errors="replace",
    newline=""
) as f_in:

    reader = csv.reader(f_in)

    with open(
        OUTPUT_FILE,
        "wb"
    ) as f_out:

        for row_number, row in enumerate(reader):

            # Transformer la ligne CSV en texte
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(row)

            row_bytes = buffer.getvalue().encode("utf-8")

            # Vérifier si la nouvelle ligne dépasserait 48 Mo
            if f_out.tell() + len(row_bytes) > MAX_SIZE_BYTES:
                break

            f_out.write(row_bytes)

            # Ne pas compter l'en-tête
            if row_number > 0:
                rows_kept += 1


final_size = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)

print("✅ Réduction terminée")
print(f"Fichier créé : {OUTPUT_FILE}")
print(f"Lignes conservées : {rows_kept}")
print(f"Taille finale : {final_size:.2f} Mo")