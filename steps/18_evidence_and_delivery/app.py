"""Step 18: manifest verificabile, bundle read-only e delivery gate."""

import tempfile
from pathlib import Path

from agent_harness.evidence import (
    assess_delivery_readiness,
    build_evidence_manifest,
    create_evidence_bundle,
    run_independent_checker,
    verify_evidence_manifest,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "report.txt").write_text("risultato verificato\n", encoding="utf-8")
        manifest = build_evidence_manifest(
            run_id="lesson-18",
            session_id="student",
            goal="Crea report.txt",
            answer="Report creato e verificato.",
            terminal_status="completed",
            workspace=workspace,
            artifact_paths=["report.txt"],
            events=[],
            requires_runtime_verification=False,
        )
        integrity = verify_evidence_manifest(manifest, workspace)
        bundle = create_evidence_bundle(manifest, workspace, root / "bundle")
        checker = run_independent_checker(bundle)
        delivery = assess_delivery_readiness(manifest, integrity, checker, gate=None)
        print("Manifest:", manifest.manifest_sha256)
        print("Integrità:", integrity.valid, "checker:", checker.passed)
        print("Delivery rilevante:", delivery.relevant, "ready:", delivery.ready)


if __name__ == "__main__":
    main()
