"""Empaqueta solo los archivos de entrega; excluye datos raw, altas, logs y secretos."""

import hashlib
import json
import zipfile

from dataset import ROOT


def main() -> None:
    files = [
        p
        for p in ROOT.iterdir()
        if p.is_file() and p.suffix in {".py", ".md", ".toml", ".yaml", ".txt", ".ps1"}
    ]
    files += [
        ROOT / ".gitignore",
        ROOT / ".gitattributes",
        ROOT / ".streamlit/config.toml",
        ROOT / "modelo.joblib",
        ROOT / "metrics.json",
    ]
    files += list((ROOT / "data").glob("*.csv")) + list((ROOT / "data").glob("*.json"))
    files += [p for p in (ROOT / "docs").iterdir() if p.suffix in {".md", ".txt", ".png"}]
    files += list((ROOT / "tests").glob("*.py"))
    output = ROOT / "dist/movieflix-render.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(set(files)):
            if path.is_symlink():
                raise ValueError("No se empaquetan enlaces simbólicos.")
            archive.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if any(n.startswith(("data/raw/", "storage/", ".venv/")) or ".env" in n for n in names):
            raise ValueError("El paquete contiene un archivo excluido.")
        if archive.testzip() is not None:
            raise ValueError("Falló la comprobación de integridad ZIP.")
    manifest = {"files": names, "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    (output.parent / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Paquete verificado: {len(names)} archivos, {output.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
