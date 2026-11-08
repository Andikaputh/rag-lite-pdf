import json
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient

import tests.test_answering as fixtures
from web.conversations import Conversation, MAX_HISTORY_BYTES
from web.documents import DocumentError
from web.generation import OllamaGenerator


class ConversationStateTests(unittest.TestCase):
    def test_turn_and_byte_budgets_and_copy_isolation(self):
        conversation = Conversation()
        conversation.bind("doc", "index", {"model": "test", "digest": "v1"})
        for number in range(12):
            conversation.append(str(number), str(number), {"status": "answered", "answer": "猫" * 2500}, False)
        self.assertLessEqual(len(conversation.turns), 6)
        self.assertLessEqual(len(json.dumps(conversation.turns, ensure_ascii=False).encode()), MAX_HISTORY_BYTES)
        snapshot = conversation.snapshot({"id": "doc"}, False)
        snapshot["turns"][0]["question"] = "mutated"
        self.assertNotEqual(conversation.turns[0]["question"], "mutated")

    def test_context_only_uses_bounded_successful_questions_not_answers(self):
        conversation = Conversation()
        for question in ("A" * 500, "猫" * 500, "B" * 500):
            conversation.append(question, question, {"status": "answered", "answer": "UNTRUSTED_AI_SECRET"}, False)
        context = conversation.context_questions()
        self.assertEqual(len(context), 2)
        self.assertLessEqual(sum(len(q.encode()) for q in context), 1800)
        self.assertNotIn("UNTRUSTED_AI_SECRET", str(context))
        conversation.append("missing", "missing", {"status": "abstained"}, False)
        self.assertEqual(conversation.context_questions(), [])

    def test_scope_changes_clear_history_and_increment_revision(self):
        conversation = Conversation()
        conversation.bind("doc", "key", {"digest": "v1"})
        conversation.append("Q", "Q", {"status": "answered"}, False)
        revision = conversation.revision
        self.assertFalse(conversation.bind("doc", "key", {"digest": "v1"}))
        self.assertTrue(conversation.bind("doc", "key", {"digest": "v2"}))
        self.assertEqual(conversation.turns, [])
        self.assertGreater(conversation.revision, revision)


class RewriteAdapterTests(unittest.TestCase):
    def response(self, payload):
        return BytesIO(json.dumps({"done": True, "done_reason": "stop", "message": {"content": json.dumps(payload)}}).encode())

    def test_rewrite_uses_only_questions_and_local_structured_contract(self):
        generator = OllamaGenerator()
        with patch.object(generator.opener, "open", return_value=self.response({"question": "Berapa bulan garansi perangkat?", "needs_clarification": False})) as transport:
            result = generator.rewrite("Berapa bulannya?", ["Berapa masa garansi perangkat?"])
        self.assertFalse(result["needs_clarification"])
        request = transport.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        data = json.loads(payload["messages"][1]["content"])
        self.assertEqual(set(data), {"previous_user_questions", "current_question"})
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["options"]["num_predict"], 256)

    def test_ambiguous_rewrite_and_invented_numbers(self):
        generator = OllamaGenerator()
        with patch.object(generator.opener, "open", return_value=self.response({"question": "", "needs_clarification": True})):
            self.assertTrue(generator.rewrite("Yang mana?", ["Topik A dan B?"])["needs_clarification"])
        for payload in ({"question": "Garansi 99 bulan?", "needs_clarification": False},
                        {"question": "valid", "needs_clarification": "false"}, {"question": "", "needs_clarification": False}):
            with patch.object(generator.opener, "open", return_value=self.response(payload)), self.assertRaises(DocumentError):
                generator.rewrite("Berapa bulan?", ["Masa garansi?"])

    def test_unchanged_reference_gets_visible_user_topic_not_ai_facts(self):
        generator = OllamaGenerator()
        with patch.object(generator.opener, "open", return_value=self.response({"question": "Berapa lamanya?", "needs_clarification": False})):
            result = generator.rewrite("Berapa lamanya?", ["Apa masa garansi perangkat?"])
        self.assertIn("Topik pertanyaan sebelumnya: Apa masa garansi perangkat?", result["question"])


class ConversationGatewayTests(unittest.TestCase):
    setUp = fixtures.AnswerGatewayTests.setUp
    ask = fixtures.AnswerGatewayTests.ask

    def history(self):
        return self.client.get("/api/chat").json()

    def test_followup_rewrites_then_retrieves_and_cites_fresh_evidence(self):
        self.ask()
        rewritten = "Berapa bulan masa garansi perangkat?"
        with patch.object(self.generator, "rewrite", return_value={"question": rewritten, "needs_clarification": False}) as rewrite, \
             patch.object(self.embedder, "embed", wraps=self.embedder.embed) as embed:
            response = self.ask("Bisa ulangi berapa bulan?")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["used_history"])
        self.assertEqual(data["resolved_question"], rewritten)
        self.assertEqual(embed.call_args.args[0], [rewritten])
        self.assertEqual(rewrite.call_args.args[1], ["Berapa masa garansi perangkat?"])
        self.assertEqual(self.generator.seen[-1][0], rewritten)
        self.assertEqual(data["sources"][0]["quote"], fixtures.QUOTE)

    def test_history_reloads_with_verified_sources_and_stable_turn_ids(self):
        response = self.ask().json()
        first = self.history()
        second = self.history()
        self.assertEqual(first, second)
        self.assertEqual(first["turns"][0]["id"], response["turn_id"])
        self.assertEqual(first["turns"][0]["response"]["sources"][0]["page"], 1)
        self.assertEqual(len(first["turns"]), 1)

    def test_opt_out_skips_rewrite_and_backend_still_owns_history(self):
        self.ask()
        with patch.object(self.generator, "rewrite") as rewrite:
            response = self.client.post("/api/chat", json={"question": "New topic", "use_history": False}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["used_history"])
        rewrite.assert_not_called()
        self.assertEqual(len(self.history()["turns"]), 2)
        self.assertEqual(self.client.post("/api/chat", json={"question": "Q", "history": []}, headers=self.headers).status_code, 422)

    def test_six_turn_limit_and_failed_requests_are_not_recorded(self):
        for number in range(8):
            self.assertEqual(self.ask(f"Pertanyaan {number}").status_code, 200)
        self.assertEqual(len(self.history()["turns"]), 6)
        self.assertEqual(self.history()["turns"][0]["question"], "Pertanyaan 2")
        revision = self.history()["revision"]
        with patch.object(self.generator, "generate", side_effect=DocumentError("generation_unavailable", "offline", 503)):
            self.assertEqual(self.ask().status_code, 503)
        self.assertEqual(self.history()["revision"], revision)

    def test_abstention_is_visible_but_breaks_followup_context(self):
        self.ask()
        self.ask("Pertanyaan tidak relevan")
        with patch.object(self.generator, "rewrite") as rewrite:
            self.ask("Topik baru")
        rewrite.assert_not_called()
        self.assertEqual(self.history()["turns"][1]["response"]["status"], "abstained")

    def test_unclear_followup_requests_clarification_without_embedding(self):
        self.ask()
        calls = self.embedder.calls
        with patch.object(self.generator, "rewrite", return_value={"question": "", "needs_clarification": True}):
            data = self.ask("Yang mana?").json()
        self.assertEqual(data["reason"], "needs_clarification")
        self.assertEqual(data["sources"], [])
        self.assertEqual(self.embedder.calls, calls)

    def test_reset_keeps_pdf_index_and_rejects_stale_revision(self):
        self.ask()
        revision = self.history()["revision"]
        response = self.client.delete("/api/chat", headers={**self.headers, "X-Conversation-Revision": str(revision)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["turns"], [])
        self.assertEqual(self.session.document["index"]["status"], "ready")
        self.assertTrue((self.directory / "index.sqlite3").exists())
        stale = self.ask(**{"X-Conversation-Revision": str(revision)})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "conversation_changed")

    def test_replacement_delete_and_rename_clear_history_but_same_bytes_preserve(self):
        from tests.pdf_fixtures import pdf_bytes
        self.ask()
        headers = {"X-CSRF-Token": self.csrf, "Content-Type": "application/pdf", "X-File-Name": "warranty.pdf"}
        self.client.post("/api/documents", content=pdf_bytes(fixtures.TEXT), headers=headers)
        self.assertEqual(len(self.history()["turns"]), 1)
        self.client.post("/api/documents", content=b"broken", headers=headers)
        self.assertEqual(len(self.history()["turns"]), 1)
        self.client.post("/api/documents", content=pdf_bytes(fixtures.TEXT), headers={**headers, "X-File-Name": "renamed.pdf"})
        self.assertEqual(self.history()["turns"], [])
        self.ask()
        self.client.delete("/api/documents", headers=self.headers)
        self.assertEqual(self.history()["turns"], [])

    def test_index_cache_hit_preserves_history_new_config_resets_it(self):
        from web.indexing import ChunkConfig
        self.ask()
        self.client.post("/api/documents/index", headers=self.headers)
        self.assertEqual(len(self.history()["turns"]), 1)
        self.indexer.config = ChunkConfig(size=800)
        self.client.post("/api/documents/index", headers=self.headers)
        self.assertEqual(self.history()["turns"], [])

    def test_generator_digest_change_clears_history_before_using_context(self):
        self.ask()
        self.generator.digest = "v2"
        with patch.object(self.generator, "rewrite") as rewrite:
            response = self.ask("Berapa bulannya?")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conversation_reset")
        rewrite.assert_not_called()
        self.assertEqual(self.history()["turns"], [])

    def test_history_and_reset_isolation_csrf_revision_and_busy(self):
        self.ask()
        other = TestClient(self.app)
        self.assertEqual(other.get("/api/chat").status_code, 403)
        other.get("/api/documents")
        self.assertEqual(other.get("/api/chat").json()["turns"], [])
        self.assertEqual(self.client.delete("/api/chat").status_code, 403)
        self.assertEqual(self.client.delete("/api/chat", headers={**self.headers, "Origin": "https://evil.invalid"}).status_code, 403)
        self.assertEqual(self.ask(**{"X-Conversation-Revision": "bad"}).status_code, 400)
        self.session.busy = True
        self.assertEqual(self.client.delete("/api/chat", headers=self.headers).status_code, 409)
        self.session.busy = False

    def test_expiry_and_embedding_changes_remove_access_to_old_history(self):
        self.ask()
        self.embedder.digest = "new-embedding"
        self.assertEqual(self.ask().json()["error"]["code"], "index_stale")
        self.assertEqual(self.history()["turns"], [])
        self.client.post("/api/documents/index", headers=self.headers)
        self.ask()
        self.session.touched -= self.store.ttl + 1
        self.assertEqual(self.client.get("/api/chat").status_code, 403)
        self.client.get("/api/documents")
        self.assertEqual(self.history()["turns"], [])

    def test_different_pdf_clears_history_and_invalid_context_flags_rejected(self):
        from tests.pdf_fixtures import pdf_bytes
        self.ask()
        for flag in (1, "false", [], None):
            self.assertEqual(self.client.post("/api/chat", json={"question": "Q", "use_history": flag}, headers=self.headers).status_code, 422)
        self.client.post("/api/documents", content=pdf_bytes("Different synthetic PDF."), headers={
            "X-CSRF-Token": self.csrf, "X-File-Name": "new.pdf", "Content-Type": "application/pdf"})
        self.assertEqual(self.history()["turns"], [])


if __name__ == "__main__":
    unittest.main()
