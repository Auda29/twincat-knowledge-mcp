"""Synthetic source-to-typed-query integration; not real-corpus acceptance."""

from pathlib import Path
from zipfile import ZipFile

from twincat_knowledge.corpus.topic_package_load import load_topic_package
from twincat_knowledge.ingest.infosys_ingest import ingest_infosys_package
from twincat_knowledge.services.entity_contracts import (
    FindEntitiesInput,
    GetSymbolInput,
    LookupErrorInput,
)
from twincat_knowledge.services.topic_queries import TopicQueryService


def test_synthetic_archive_import_to_typed_tools(tmp_path: Path) -> None:
    declaration = "FUNCTION_BLOCK FB_Synthetic\nVAR_INPUT\n    x : BOOL;\nEND_VAR"
    article = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        '<title>FB_Synthetic</title><meta name="Library" content="SyntheticLib"/>'
        '<meta name="Namespace" content="Synthetic"/>'
        '<meta name="LibraryVersion" content="1.2.3"/>'
        '</head><body><pre data-language="ST">' + declaration + "</pre>"
        "<table><tr><th>Error code</th><th>Description</th><th>Domain</th></tr>"
        "<tr><td>0x0010</td><td>Synthetic error only</td><td>Fixture</td></tr>"
        "</table></body></html>"
    )
    archive = tmp_path / "synthetic.mshc"
    with ZipFile(archive, "w") as output:
        output.writestr("routing_directory/1033/symbol.html", article)
    built = ingest_infosys_package(
        tmp_path / "package",
        source=archive,
        language="en",
        libraries=None,
        rights_reference="synthetic-test-only",
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    with load_topic_package(
        built.package_path,
        expected_manifest_sha256=built.manifest_sha256,
        cache_dir=cache,
    ) as loaded:
        service = TopicQueryService(loaded)
        assert service._entity_service is None
        typed = service.entity_service
        found = typed.find_symbols(FindEntitiesInput(query="FB_Synthetic"))
        assert found.status == "ok"
        assert found.data is not None
        symbol = found.data.items[0]
        assert symbol.library == "SyntheticLib"
        assert symbol.namespace == "Synthetic"
        assert symbol.documented_version == "1.2.3"
        assert symbol.declaration == declaration
        assert symbol.sources[0].locator == "routing_directory/1033/symbol.html"
        assert found.snapshot_ids == (built.snapshot_id,)
        detail = typed.get_symbol(GetSymbolInput(symbol_id=symbol.id))
        assert detail.data is not None and detail.data.items == (symbol,)
        libraries = typed.find_libraries(FindEntitiesInput(query="SyntheticLib"))
        assert libraries.status == "ok"
        error = typed.lookup_error(LookupErrorInput(code="0x0010", domain="Fixture"))
        assert error.status == "ok"
        assert error.data is not None
        assert error.data.items[0].error_code == "0x0010"
        assert typed.lookup_error(LookupErrorInput(code="16")).status == "not_found"
