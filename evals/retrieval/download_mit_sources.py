"""Download the five unchanged MIT OCW PDFs; never upload or embed them."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

def main():
    destination = Path(__file__).with_name("sources")
    destination.mkdir(exist_ok=True)
    fixture = json.loads(Path(__file__).with_name("mit_6006.json").read_text(encoding="utf-8"))
    for document in fixture["documents"]:
        name = document["name"]
        path = destination / name
        if path.exists():
            value = path.read_bytes()
        else:
            with urlopen(document["url"], timeout=60) as response:
                value = response.read()
            if not value.startswith(b"%PDF-") or hashlib.sha256(value).hexdigest() != document["sha256"]:
                raise ValueError(f"Unexpected PDF bytes: {name}")
            path.write_bytes(value)
        if hashlib.sha256(value).hexdigest() != document["sha256"]:
            raise ValueError(f"Existing PDF checksum mismatch: {name}")
        print(name, hashlib.sha256(value).hexdigest())


if __name__ == "__main__":
    main()
