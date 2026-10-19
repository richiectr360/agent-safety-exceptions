import unittest
from unittest.mock import patch
from permission_thresholds.actors import ActorError
from permission_thresholds.ollama_adapter import OllamaActor, model_inventory, local_json


class OllamaTests(unittest.TestCase):
    def actor(self):
        return OllamaActor("test-model", {"think": False, "temperature": 0.6, "num_ctx": 8192, "num_predict": 128}, 42)

    def request(self):
        return {"system": "Complete the task", "observation": {"tools": [{"name": "finish"}]}, "history": []}

    def test_real_response_provenance_and_fixed_local_endpoint(self):
        response = {"model": "test-model", "done": True, "done_reason": "stop", "response": '{"tool":"finish","arguments":{}}', "context": [1, 2]}
        with patch("permission_thresholds.ollama_adapter.local_json", return_value=response) as call:
            actor = self.actor()
            result = actor.next_action(self.request())
        self.assertEqual(result["action"]["tool"], "finish")
        self.assertEqual(call.call_args[0][0], "/api/generate")
        payload = call.call_args[0][1]
        self.assertEqual(payload["options"]["seed"], 42)
        self.assertFalse(payload["think"])
        self.assertEqual(payload["format"]["oneOf"][0]["properties"]["tool"]["enum"], ["finish"])
        self.assertEqual(payload["format"]["oneOf"][0]["properties"]["arguments"]["properties"], {})
        self.assertNotIn("context", actor.last_call["response"])
        self.assertIn("request", actor.last_call)

    def test_truncation_is_error_and_raw_output_retained(self):
        with patch("permission_thresholds.ollama_adapter.local_json", return_value={"done": True, "done_reason": "length", "response": "partial"}):
            actor = self.actor()
            with self.assertRaisesRegex(ActorError, "incomplete"):
                actor.next_action(self.request())
            self.assertEqual(actor.last_call["response"]["response"], "partial")

    def test_invalid_action_is_error(self):
        with patch("permission_thresholds.ollama_adapter.local_json", return_value={"done": True, "done_reason": "stop", "response": '{"wrong":1}'}):
            with self.assertRaises(ActorError):
                self.actor().next_action(self.request())

    def test_inventory_no_silent_model_substitution(self):
        with patch("permission_thresholds.ollama_adapter.local_json", return_value={"models": []}):
            with self.assertRaisesRegex(ActorError, "not_installed"):
                model_inventory("missing")

    def test_unknown_endpoint_rejected_before_network(self):
        with self.assertRaises(ValueError):
            local_json("https://example.org")


if __name__ == "__main__":
    unittest.main()
