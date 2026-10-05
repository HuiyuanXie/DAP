import json
import tempfile
import unittest
from pathlib import Path

from dap.provider import ProviderError
from dap.simulation import DemoProvider, PROPOSAL, Simulation


class SocietyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def society(self, **kwargs):
        return Simulation(DemoProvider(), output_dir=self.directory.name, **kwargs)

    def finish(self, sim):
        while not sim.snapshot()['complete']:
            sim.step()
        return sim.snapshot()

    def amendment(self, sim):
        return sim.provider.decide('legislation', 'legislator-a',
                                  {'scenario': {'case': 'resources'}, 'foundations': sim.foundations,
                                   'laws': sim.laws}, PROPOSAL)

    def test_law_is_prospective_and_reduces_recurrence(self):
        sim = self.society(rounds=2)
        first = sim.step()
        self.assertEqual(first['metrics']['harm_events'], 1)
        self.assertEqual(first['laws'][-1]['effective_round'], 2)
        second = sim.step()
        self.assertEqual(second['metrics']['harm_events'], 1)
        self.assertEqual(second['metrics']['completed_tasks'], 4)
        self.assertEqual(second['metrics']['legal_violations'], 0)

    def test_fixed_control_cannot_legislate(self):
        sim = self.society(setting='fixed', rounds=2)
        result = self.finish(sim)
        self.assertEqual(result['metrics']['harm_events'], 2)
        self.assertEqual(len(result['laws']), 2)
        self.assertFalse(sim.enact(self.amendment(sim), [True, True])[0])

    def test_bounded_authority_rejects_unanimous_foundational_change(self):
        sim = self.society()
        self.assertFalse(sim.enact(self.amendment(sim), [True, True])[0])
        self.assertEqual(sim.foundations['reserve_units'], 4)

    def test_constitutional_amendment_does_not_change_external_harm_measure(self):
        result = self.finish(self.society(setting='constitutional'))
        self.assertEqual(result['foundations']['reserve_units'], 2)
        self.assertEqual(result['metrics']['foundational_amendments'], 1)
        self.assertEqual(result['metrics']['harm_events'], 2)
        self.assertEqual(result['metrics']['legal_violations'], 0)
        self.assertEqual(result['metrics']['completed_tasks'], 7)
        confirmations = [e for e in result['events'] if e['kind'] == 'Confirmation']
        self.assertEqual(len(confirmations), 2)

    def test_bounded_retains_reserve(self):
        result = self.finish(self.society())
        self.assertEqual(result['foundations']['reserve_units'], 4)
        self.assertEqual(result['metrics']['completed_tasks'], 6)
        self.assertEqual(result['metrics']['harm_events'], 1)

    def test_confirmation_dissent_prevents_amendment(self):
        class Dissenter(DemoProvider):
            def decide(self, role, agent, context, schema):
                result = super().decide(role, agent, context, schema)
                if role == 'confirmation' and agent == 'legislator-b':
                    result['approve'] = False
                return result
        sim = Simulation(Dissenter(), setting='constitutional', output_dir=self.directory.name)
        result = self.finish(sim)
        self.assertEqual(result['foundations']['reserve_units'], 4)
        self.assertEqual(result['metrics']['foundational_amendments'], 0)

    def test_no_discussion_retains_law_but_removes_messages(self):
        sim = self.society(rounds=2, communication=False)
        result = self.finish(sim)
        self.assertEqual(len(result['laws']), 3)
        self.assertEqual(sim.messages, [])
        self.assertEqual(result['metrics']['blocked_actions'], 2)
        self.assertEqual(result['metrics']['completed_tasks'], 2)

    def test_false_sanction_has_no_runtime_authority(self):
        class FalseAccuser(DemoProvider):
            def decide(self, role, agent, context, schema):
                result = super().decide(role, agent, context, schema)
                if role == 'enforcement':
                    result['blocks'] = [{'agent': 'worker-a', 'law_id': 'L1', 'reason': 'Unsupported accusation.'}]
                return result
        sim = Simulation(FalseAccuser(), rounds=1, output_dir=self.directory.name)
        result = self.finish(sim)
        self.assertEqual(result['metrics']['blocked_actions'], 0)
        self.assertEqual(result['metrics']['completed_tasks'], 2)

    def test_missed_violation_executes_and_is_measured(self):
        class BlindEnforcer(DemoProvider):
            def decide(self, role, agent, context, schema):
                result = super().decide(role, agent, context, schema)
                if role == 'enforcement':
                    result['blocks'] = []
                    result['needs_legislation'] = False
                return result
        sim = Simulation(BlindEnforcer(), setting='fixed', rounds=3, output_dir=self.directory.name)
        result = self.finish(sim)
        self.assertEqual(result['metrics']['legal_violations'], 1)
        self.assertEqual(result['metrics']['harm_events'], 3)

    def test_error_stops_and_preserves_partial_trace(self):
        class BrokenProvider(DemoProvider):
            def decide(self, *args):
                raise ProviderError('Simulated quota error.')
        sim = Simulation(BrokenProvider(), output_dir=self.directory.name)
        result = sim.step()
        self.assertTrue(result['failed'])
        saved = json.loads((Path(self.directory.name) / (sim.run_id + '.json')).read_text())
        self.assertEqual(saved['events'][-1]['data']['error'], 'Simulated quota error.')
        self.assertEqual(saved['metrics']['scheduled_tasks'], 0)

    def test_external_labels_never_enter_agent_contexts(self):
        class RecordingProvider(DemoProvider):
            contexts = []
            def decide(self, role, agent, context, schema):
                self.contexts.append(json.loads(json.dumps(context)))
                return super().decide(role, agent, context, schema)
        provider = RecordingProvider()
        sim = Simulation(provider, rounds=4, output_dir=self.directory.name)
        self.finish(sim)
        text = json.dumps(provider.contexts)
        self.assertNotIn('harm_events', text)
        self.assertNotIn('External outcome', text)
        self.assertNotIn('legal_violations', text)

    def test_vote_quorum_cannot_be_bypassed(self):
        sim = self.society(setting='constitutional')
        proposal = self.amendment(sim)
        for votes in ([], [True], [True, False], [True, True, True]):
            self.assertFalse(sim.enact(proposal, votes)[0])

    def test_snapshot_cannot_mutate_simulation(self):
        sim = self.society()
        state = sim.snapshot()
        state['foundations']['reserve_units'] = 0
        self.assertEqual(sim.foundations['reserve_units'], 4)


if __name__ == '__main__':
    unittest.main()
