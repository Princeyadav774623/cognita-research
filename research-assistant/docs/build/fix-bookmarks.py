"""Give every bookmark a unique numeric id.

docx-js emits w:id="1" on every bookmark it writes. The names are unique, so
Word navigates correctly, but duplicate ids are a schema violation and the
validator rejects the file. Renumbered in document order, start and end paired.
"""
import re, shutil, sys, zipfile
from pathlib import Path

def fix(path: Path) -> int:
    src = zipfile.ZipFile(path)
    items = {n: src.read(n) for n in src.namelist()}
    src.close()

    xml = items["word/document.xml"].decode("utf-8")
    counter = [100]          # start above anything docx-js allocates itself
    stack = []

    def start(m):
        counter[0] += 1
        stack.append(counter[0])
        return m.group(0).replace(f'w:id="{m.group(1)}"', f'w:id="{counter[0]}"')

    def end(m):
        cur = stack.pop() if stack else counter[0]
        return f'<w:bookmarkEnd w:id="{cur}"/>'

    xml, n_start = re.subn(r'<w:bookmarkStart w:name="[^"]*" w:id="(\d+)"\s*/>', start, xml)
    xml, _ = re.subn(r'<w:bookmarkEnd w:id="\d+"\s*/>', end, xml)
    items["word/document.xml"] = xml.encode("utf-8")

    tmp = path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in items.items():
            out.writestr(name, data)
    shutil.move(tmp, path)
    return n_start

for p in sys.argv[1:]:
    print(f"{Path(p).name}: renumbered {fix(Path(p))} bookmarks")
