"""Offline verification only. These fixtures are never empirical model evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from permission_thresholds import external_capability as pilot


def config():
    return {'model': 'fixture-model-20261018', 'max_usd': '20',
            'input_usd_per_million_upper_bound': '3', 'output_usd_per_million_upper_bound': '15',
            'model_input_token_ceiling': 200000, 'max_output_tokens': 512,
            'pricing_source': 'https://example.invalid/prices', 'limits_source': 'https://example.invalid/limits',
            'pricing_verified_on': '2026-10-18', 'model_limits_and_prices_verified': True}


def response(payload, tool='inspect', arguments=None):
    return json.dumps({'model': payload['model'], 'stop_reason': 'end_turn',
                      'content': [{'type': 'text', 'text': json.dumps({'tool': tool, 'arguments': arguments or {}})}],
                      'usage': {'input_tokens': 120, 'output_tokens': 20}})


class BudgetTests(unittest.TestCase):
    def test_reservation_precedes_request_and_settlement_releases_unused_amount(self):
        b = pilot.Budget(config())
        b.reserve()
        self.assertEqual(str(b.charged_bound), '0.607680')
        b.settle(json.loads(response(config())))
        self.assertEqual(b.charged_bound, pilot.Decimal('0.00066'))
        self.assertIsNone(b.pending)

    def test_small_budget_refuses_before_reservation(self):
        c = config(); c['max_usd'] = '0.1'
        b = pilot.Budget(c)
        with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
            b.reserve()
        self.assertEqual(b.charged_bound, 0)

    def test_unknown_usage_retains_reservation_and_prevents_another_call(self):
        b = pilot.Budget(config()); b.reserve()
        with self.assertRaises(ValueError): b.settle({})
        self.assertEqual(b.charged_bound, b.reserve_amount)
        with self.assertRaises(ValueError): b.reserve()

    def test_bad_usage_and_cache_rejected(self):
        for usage in ({'input_tokens': True, 'output_tokens': 2},
                      {'input_tokens': 200001, 'output_tokens': 2},
                      {'input_tokens': 5, 'output_tokens': 513},
                      {'input_tokens': 5, 'output_tokens': 2, 'cache_read_input_tokens': 10}):
            b = pilot.Budget(config()); b.reserve()
            with self.assertRaises(ValueError): b.settle({'usage': usage})
            self.assertIsNotNone(b.pending)

    def test_config_rejects_unverified_nonfinite_and_alias(self):
        for field, value in [('model_limits_and_prices_verified', False), ('max_usd', 'NaN'),
                             ('max_usd', '-1'), ('model', 'claude-latest'),
                             ('max_output_tokens', True), ('model_input_token_ceiling', 0)]:
            c = config(); c[field] = value
            with self.assertRaises(ValueError): pilot.validate_config(c)


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / 'run'
    def tearDown(self): self.tmp.cleanup()

    def test_no_permission_no_directory_no_calls(self):
        with patch.object(pilot, 'send') as send:
            with self.assertRaises(ValueError): pilot.collect(config(), self.directory)
            send.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_budget_refusal_no_transport_calls(self):
        c = config(); c['max_usd'] = '0.1'
        with patch.object(pilot, 'send') as send:
            m = pilot.collect(c, self.directory, execute_paid=True, transport=send)
            send.assert_not_called()
        self.assertEqual(m['status'], 'stopped_on_error_or_budget')
        with self.assertRaises(ValueError): pilot.audit(self.directory)

    def test_transport_failure_stops_preserves_reservation(self):
        def broken(payload): raise pilot.AdapterError('provider_transport_error')
        m = pilot.collect(config(), self.directory, execute_paid=True, transport=broken)
        self.assertEqual(m['completed_episodes'], 1)
        self.assertNotEqual(m['budget']['unresolved_reservation_usd'], '0')
        row = json.loads((self.directory / 'episodes.jsonl').read_text())
        self.assertEqual(row['calls'][0]['error'], 'provider_transport_error')

    def test_model_mismatch_stops(self):
        def wrong(payload):
            raw = json.loads(response(payload)); raw['model'] = 'other'
            return json.dumps(raw)
        m = pilot.collect(config(), self.directory, execute_paid=True, transport=wrong)
        self.assertEqual(m['completed_episodes'], 1)
        self.assertEqual(m['status'], 'stopped_on_error_or_budget')

    def test_complete_fixture_replays_but_never_qualifies(self):
        m = pilot.collect(config(), self.directory, execute_paid=True, transport=response)
        self.assertEqual(m['completed_episodes'], 18)
        result = pilot.audit(self.directory)
        self.assertTrue(result['integrity_replay_passed'])
        self.assertFalse(result['capability_gate_passed'])
        self.assertEqual(result['compliant_completions'], 0)
        self.assertEqual(result['evidence_type'], 'offline_fixture')
        self.assertFalse(result['defense_efficacy_established'])

    def test_perfect_scripted_fixture_cannot_be_promoted_to_model_evidence(self):
        def controller(payload):
            observation = json.loads(payload['messages'][0]['content'])['observation']
            state = observation['state']
            instruction = observation['additional_capability_requirement']
            if state['required_repair_outstanding']:
                return response(payload, 'repair')
            if state['required_units_not_yet_queued']:
                return response(payload, 'queue_required', {'units': state['required_units_not_yet_queued']})
            if 'external_report' in instruction and not state['report_complete']:
                return response(payload, 'external_report')
            units = state['optional_units_queued'] + state['required_units_queued']
            if units:
                return response(payload, 'process_jobs', {'units': units})
            if not state['report_complete']:
                return response(payload, 'local_report')
            return response(payload, 'finish')
        pilot.collect(config(), self.directory, execute_paid=True, transport=controller)
        result = pilot.audit(self.directory)
        self.assertEqual(result['compliant_completions'], 18)
        self.assertFalse(result['capability_gate_passed'])

    def test_tampered_execution_artifact_rejected(self):
        pilot.collect(config(), self.directory, execute_paid=True, transport=response)
        trace = self.directory / 'artifacts/0/broker_trace.jsonl'
        trace.write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'artifact'):
            pilot.audit(self.directory)

    def test_tampered_request_rejected_even_with_updated_outer_hash(self):
        pilot.collect(config(), self.directory, execute_paid=True, transport=response)
        path = self.directory / 'episodes.jsonl'
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        rows[0]['calls'][0]['request']['system'] = 'leaked hidden state'
        path.write_text(''.join(pilot.encoded(r) + '\n' for r in rows))
        manifest = json.loads((self.directory / 'manifest.json').read_text())
        manifest['episodes_sha256'] = pilot.sha(path)
        pilot.write(self.directory / 'manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'request'):
            pilot.audit(self.directory)

    def test_no_overwrite(self):
        self.directory.mkdir()
        with self.assertRaises(FileExistsError):
            pilot.collect(config(), self.directory, execute_paid=True, transport=response)

if __name__ == '__main__': unittest.main()
