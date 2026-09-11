"""Copy only the pinned SDK's Core, Hiyori model, and license text; never extract arbitrary archive paths."""
import sys
import zipfile
from pathlib import Path, PurePosixPath

archive, root = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
count = 0
with zipfile.ZipFile(archive) as bundle:
    for info in bundle.infolist():
        name = info.filename
        if info.is_dir():
            continue
        destination = None
        if name.endswith("/Core/live2dcubismcore.min.js"):
            destination = root / "public/vendor/live2dcubismcore.min.js"
        elif "/Samples/Resources/Hiyori/" in name:
            relative = PurePosixPath(name.split("/Samples/Resources/Hiyori/", 1)[1])
            if ".." in relative.parts or relative.is_absolute() or "\\" in str(relative):
                raise ValueError("Unsafe asset path")
            destination = root / "public/models/Hiyori" / str(relative)
        elif len(PurePosixPath(name).parts) == 2 and PurePosixPath(name).name in ("LICENSE.md", "NOTICE.md"):
            destination = root / "public/vendor" / PurePosixPath(name).name
        if destination:
            destination = destination.resolve()
            if not destination.is_relative_to(root / "public") or info.file_size > 40_000_000:
                raise ValueError("Invalid asset entry")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(info))
            count += 1
if not (root / "public/vendor/live2dcubismcore.min.js").exists():
    raise RuntimeError("Core missing from the SDK")
if not (root / "public/models/Hiyori/Hiyori.model3.json").exists():
    raise RuntimeError("Hiyori model missing from the SDK")
print(f"Prepared {count} official runtime / sample files.")
