import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from mayors import parse  # noqa: E402

PAGE = """
<ul>
<li><strong>Glenn Aby</strong><div>Mayor (Lind) <a href="mailto:x@y">x@y</a> City/Town Phone: <a>(509) 677-3241</a></div></li>
<li><strong>Gene Achziger</strong><div>Deputy Mayor (Des Moines)</div></li>
<li><strong>Pat Doe</strong><div>Mayor Pro Tem (Ruston)</div></li>
<li><strong>Jo&#39;s Name</strong><div>Mayor (Sedro-Woolley)</div></li>
<li><strong>Ann Lee</strong><div>Councilmember (Mayor)</div></li>
</ul>
"""


def test_only_mayors():
    assert parse(PAGE) == [("Lind", "Glenn Aby"), ("Sedro-Woolley", "Jo's Name")]
