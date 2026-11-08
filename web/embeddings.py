"""Local-only Ollama embedding adapter. Never auto-pulls or falls back to cloud."""
import json
import math
import socket
import urllib.error
import urllib.request

from web.documents import DocumentError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalOllamaClient:
    transport_code = "embedding_unavailable"
    transport_message = "Local Ollama is unavailable or timed out. Start Ollama and check that bge-m3 is installed."
    response_code = "invalid_embeddings"
    response_message = "Invalid local embedding response. Check Ollama and try again."

    def __init__(self):
        # Fixed loopback and proxies disabled: PDFs must never follow environment
        # proxy settings or HTTP redirects to an external provider.
        self.base_url = "http://127.0.0.1:11434"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _request(self, path, payload=None, *, timeout=30):
        request = urllib.request.Request(
            self.base_url + path,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("Response exceeds limit")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("Invalid response")
                return result
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError):
            raise DocumentError(self.transport_code, self.transport_message, 503) from None
        except (ValueError, UnicodeError):
            raise DocumentError(self.response_code, self.response_message, 502) from None


class OllamaEmbedder(LocalOllamaClient):
    model = "bge-m3:latest"
    dimensions = 1024

    def identity(self, *, timeout=5):
        data = self._request("/api/tags", timeout=timeout)
        models = data.get("models")
        if not isinstance(models, list):
            raise DocumentError("invalid_embeddings", "Invalid Ollama model list.", 502)
        for model in models:
            if isinstance(model, dict) and model.get("name") == self.model and isinstance(model.get("digest"), str) and model["digest"]:
                return {"model": self.model, "digest": model["digest"], "dimensions": self.dimensions}
        raise DocumentError("model_missing", "Local bge-m3 is missing. Run: ollama pull bge-m3. Models are not downloaded automatically.", 503)

    def embed(self, texts, *, timeout=30):
        result = self._request("/api/embed", {
            "model": self.model, "input": texts, "truncate": False, "keep_alive": "5m",
        }, timeout=timeout)
        return normalize_vectors(result.get("embeddings"), len(texts), self.dimensions)


def normalize_vectors(vectors, count, dimensions):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise DocumentError("invalid_embeddings", "The embedding count does not match the text chunks.", 502)
    normalized = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions or any(
            isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) for value in vector
        ):
            raise DocumentError("invalid_embeddings", "Invalid embedding dimensions or values.", 502)
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm <= 0:
            raise DocumentError("invalid_embeddings", "Empty or invalid embedding.", 502)
        normalized.append([value / norm for value in vector])
    return normalized
