import json

import httpx
import pytest


@pytest.fixture()
def provider(monkeypatch):
    from app import embeddings
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-do-not-log")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_REVISION", raising=False)

    def install(body, status=200):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(status, json=body)

        client = httpx.Client(transport=httpx.MockTransport(handle))
        monkeypatch.setattr(embeddings.httpx, "post", client.post)
        return requests

    return install


def test_embed_text_uses_configured_model_and_fixed_dimension(provider, monkeypatch):
    from app.embeddings import embed_text
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    requests = provider({"object": "list", "model": "text-embedding-3-large",
                         "data": [{"object": "embedding", "index": 0,
                                   "embedding": [1.0] + [0.0] * 1535}],
                         "usage": {"prompt_tokens": 3, "total_tokens": 3}})
    assert embed_text("Parallel speedup") == [1.0] + [0.0] * 1535
    request = requests[0]
    assert str(request.url) == "https://api.openai.com/v1/embeddings"
    assert request.method == "POST"
    assert json.loads(request.content) == {
        "input": "Parallel speedup", "model": "text-embedding-3-large",
        "dimensions": 1536, "encoding_format": "float",
    }
    assert 0 < request.extensions["timeout"]["read"] <= 30


def test_configuration_identity_and_snapshot(monkeypatch):
    from app.embeddings import get_embedding_config
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_REVISION", "v1")
    config = get_embedding_config()
    monkeypatch.setenv("EMBEDDING_REVISION", "v2")
    assert config.identifier == "openai:text-embedding-3-small:1536:v1"
    assert get_embedding_config().identifier == "openai:text-embedding-3-small:1536:v2"
    assert "test-secret" not in repr(config)


@pytest.mark.parametrize("setting,value", [
    ("EMBEDDING_MODEL", "unsupported"), ("EMBEDDING_REVISION", ""),
    ("EMBEDDING_REVISION", "contains:delimiter"),
])
def test_invalid_configuration_is_rejected(monkeypatch, setting, value):
    from app.embeddings import EmbeddingError, get_embedding_config
    monkeypatch.setenv(setting, value)
    with pytest.raises(EmbeddingError):
        get_embedding_config()


@pytest.mark.parametrize("vector", [
    [], [1.0, 0.0], [0.0] * 1536, [float("nan")] + [0.0] * 1535,
    [float("inf")] + [0.0] * 1535, [1e40] + [0.0] * 1535,
    [1e-100] + [0.0] * 1535, [True] + [0.0] * 1535,
    ["1"] + [0.0] * 1535,
])
def test_invalid_vectors_are_rejected(vector):
    from app.embeddings import EmbeddingError, validate_embedding
    with pytest.raises(EmbeddingError):
        validate_embedding(vector)


@pytest.mark.parametrize("body,status", [
    ({"error": {"message": "test-secret-do-not-log provider error"}}, 429),
    ({"data": []}, 200), ({"data": [{"embedding": [1, 2]}]}, 200),
    ({"data": "bad"}, 200),
])
def test_provider_failures_have_safe_errors(provider, body, status, caplog):
    from app.embeddings import EmbeddingError, embed_text
    provider(body, status)
    with pytest.raises(EmbeddingError) as error:
        embed_text("Parallel speedup")
    assert "test-secret-do-not-log" not in str(error.value)
    assert "provider error" not in str(error.value)
    assert error.value.__cause__ is None
    assert "test-secret-do-not-log" not in caplog.text


def test_missing_key_is_safe(monkeypatch):
    from app.embeddings import EmbeddingError, embed_text
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EmbeddingError):
        embed_text("Parallel speedup")


@pytest.mark.parametrize("query", ["", " \n "])
def test_empty_input_is_rejected(provider, query):
    from app.embeddings import EmbeddingError, embed_text
    provider({"data": []})
    with pytest.raises(EmbeddingError):
        embed_text(query)


def test_operation_uses_captured_configuration(provider, monkeypatch):
    from app.embeddings import embed_text, get_embedding_config
    config = get_embedding_config()
    requests = provider({"data": [{"embedding": [1.0] + [0.0] * 1535}]})
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    embed_text("Parallel speedup", config=config)
    assert json.loads(requests[0].content)["model"] == "text-embedding-3-small"


def test_network_failure_is_safe(provider, monkeypatch):
    from app import embeddings

    def fail(*args, **kwargs):
        raise httpx.TimeoutException("test-secret-do-not-log")

    provider({})
    monkeypatch.setattr(embeddings.httpx, "post", fail)
    with pytest.raises(embeddings.EmbeddingError) as error:
        embeddings.embed_text("Parallel speedup")
    assert "test-secret-do-not-log" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize("magnitude", [1e30, 1e-40, 3.0])
def test_finite_nonunit_vectors_are_normalized_safely(magnitude):
    from app.embeddings import validate_embedding
    vector = validate_embedding([magnitude, magnitude] + [0.0] * 1534)
    assert vector[:2] == pytest.approx([0.70710678, 0.70710678], abs=1e-7)
    assert vector[2:] == [0.0] * 1534
