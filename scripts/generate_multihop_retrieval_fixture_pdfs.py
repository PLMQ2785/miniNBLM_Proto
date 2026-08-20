"""멀티홉 RAG 회귀 평가용 소형 PDF 자료를 생성한다."""

from pathlib import Path

import fitz


DOCUMENTS = {
    "evaluation/retrieval_multihop_git.pdf": (
        (
            "Ignored files",
            "A .gitignore entry tells Git to ignore matching files that are not already tracked. "
            "An ignored secret.txt remains in the working directory but does not become an ordinary "
            "untracked candidate for version control.",
        ),
        (
            "Stash eligibility",
            "The default git stash operation saves changes to tracked files and changes already staged "
            "in the index. It does not include ignored files. To include an ignored file in the default "
            "stash workflow, it must first be force-added with git add -f so it is staged. When tracking "
            "the file is not appropriate, git stash --all is the explicit alternative that also includes "
            "ignored files.",
        ),
        (
            "Reset and history",
            "git reset --hard moves the current branch pointer to a selected commit and resets the index "
            "and working tree. Commits after the selected point disappear from the branch's visible history.",
        ),
        (
            "Revert and history",
            "git revert creates a new commit whose changes reverse an earlier commit. The original commit "
            "and the previous history remain present, so the reversal itself is recorded in history.",
        ),
        (
            "Distributed collaboration",
            "After commits are pushed, collaborators can base their local work on the shared remote history. "
            "Rewriting that shared history makes their local history diverge and requires reconciliation. "
            "Adding a new reversing commit preserves the shared sequence and can be pulled normally.",
        ),
    ),
    "evaluation/retrieval_multihop_licenses.pdf": (
        (
            "AGPL network use",
            "The GNU Affero General Public License addresses software used through a network service. "
            "When users interact remotely with a modified AGPL-covered program, those users must be offered "
            "the corresponding source code even if no executable copy is downloaded to them.",
        ),
        (
            "MPL and GPL compatibility",
            "MPL 1.1 and GPL 2.0 requirements can conflict when covered modules are combined into one program. "
            "MPL 2.0 added a secondary-license mechanism that can permit distribution of a larger work under "
            "GPL 2.0, LGPL 2.1, or AGPL 3.0 terms when its conditions are satisfied.",
        ),
        (
            "Hybrid notices",
            "A centralized notice alone can make the origin of individually reused files unclear. The hybrid "
            "notice approach places an appropriate notice in each file and also maintains a project-level "
            "notice, preserving attribution when only selected modules or files are reused.",
        ),
    ),
}


def generate_document(output: Path, pages: tuple[tuple[str, str], ...]) -> None:
    """페이지 자료를 PDF로 저장하고 열린 문서를 닫는다."""
    output.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for page_number, (title, body) in enumerate(pages, start=1):
        page = document.new_page(width=595, height=842)
        page.insert_text((48, 62), f"Multi-hop RAG fixture {page_number}", fontsize=11)
        page.insert_text((48, 105), title, fontsize=22)
        remaining = page.insert_textbox(
            fitz.Rect(48, 145, 547, 760),
            body,
            fontsize=12,
            lineheight=1.5,
        )
        if remaining < 0:
            raise RuntimeError(f"Fixture text did not fit: {title}")
    document.set_metadata(
        {
            "title": output.stem,
            "author": "miniNBLM evaluation generator",
        }
    )
    document.save(output, garbage=4, deflate=True)
    document.close()


if __name__ == "__main__":
    for path, pages in DOCUMENTS.items():
        generate_document(Path(path), pages)
