"""Inference budgets and state/safety regressions, independent of local speed."""
import json

import pytest

from purrfect.local_api import LocalState, respond
from purrfect.ollama import OllamaCompletion
from test_chat_troubleshooting import begin, send
from test_local_api import inventory, request


class Once:
    def __init__(self, output=None, error=None):
        self.output, self.error, self.calls = output, error, 0

    async def complete(self, system, user, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.output


@pytest.mark.parametrize('output', [
    'not json', '[]', 'null', '{}', '{"selection":"mock-layout"}',
    '{"intent":[],"target":null,"response":"What happened?","options":[]}',
    '{"intent":"product","target":"invented","response":null}',
    '{"intent":"social","target":null,"response":"Run this command."}',
    '{"intent":"help","target":null,"response":"Choose?","options":[{"id":"invented","label":"X"}]}',
    '{"intent":"social","target":null,"response":"Hello!","extra":"secret"}',
])
@pytest.mark.parametrize('message', ['Hii Purrr!!', 'I need help', 'How do I edit layout blocks?'])
def test_invalid_classifier_never_invokes_another_model(output, message):
    model = Once(output)
    answer = respond(request('invalid', message) | {'debug': True}, LocalState(model=model))
    assert model.calls == answer['debug']['model_calls'] == 1
    assert answer['status'] == 'needs_input'
    assert answer['sources'] == []
    assert answer['routing'] == 'brain-clarify'
    assert any(s['stage'] == 'Validation' and 'Rejected' in s['result']
               for s in answer['debug']['stages'])
    assert answer['context']['last_question'] == message


@pytest.mark.parametrize('error', [TypeError('internal adapter failure'), ConnectionError('offline')])
def test_adapter_failure_is_not_retried(error):
    model = Once(error=error)
    answer = respond(request('error', 'hello') | {'debug': True}, LocalState(model=model))
    assert model.calls == answer['debug']['model_calls'] == 1
    assert answer['routing'] == 'brain-unavailable'
    assert any(s.get('error') == type(error).__name__ for s in answer['debug']['stages'])


def test_truncation_is_rejected_even_if_json_happens_to_parse():
    model = Once(OllamaCompletion('{"intent":"social","target":null,"response":"Hello!"}',
                                 {'done_reason': 'length'}))
    answer = respond(request('cutoff', 'hello') | {'debug': True}, LocalState(model=model))
    assert model.calls == 1
    assert answer['routing'] == 'brain-clarify'
    assert any('generation limit' in s.get('result', '') for s in answer['debug']['stages'])


def test_social_and_clarification_preserve_active_workflow_and_evidence():
    state = LocalState()
    original = begin(state)
    model = Once('{"intent":"social","target":null,"response":"Good to see you!"}')
    state.model = model
    social = send(state, message='hey, how are you?')
    assert social['context']['troubleshooting'] == original['context']['troubleshooting']
    for key in ('last_scope', 'last_question', 'outcome', 'evidence_id'):
        assert social['context'][key] == original['context'][key]
    model.output = 'invalid'
    clarify = send(state, message='huh?')
    assert clarify['context']['troubleshooting'] == original['context']['troubleshooting']
    assert clarify['context']['evidence_id'] == original['context']['evidence_id']
    done = send(state, selection='check:plugin:worked')
    assert done['status'] == 'resolved'
    assert model.calls == 2  # Button contracts never invoke inference.


@pytest.mark.parametrize('message', ["It isn't fixed now", 'not working now',
                                    'it still does not work', 'it stil dosnt work'])
def test_model_cannot_resolve_negated_success(message):
    state = LocalState()
    first = respond(request('negation', 'How do I edit layout blocks?'), state)
    model = Once('{"intent":"resolved","target":null,"response":null}')
    state.model = model
    answer = respond(request('negation', message), state)
    assert model.calls == 1
    assert answer['context']['outcome'] != 'resolved'
    assert answer['context']['evidence_id'] == first['context']['evidence_id']
    assert answer['context']['last_scope'] == 'mock-layout'


@pytest.mark.parametrize('kind', ['followup', 'simplify'])
def test_contextual_intent_uses_verified_evidence_in_one_call(kind):
    state = LocalState()
    first = respond(request('context', 'How do I edit layout blocks?'), state)
    model = Once(json.dumps({'intent': kind, 'target': None, 'response': None}))
    state.model = model
    answer = respond(request('context', 'Could you explain the bit you mentioned?'), state)
    assert model.calls == 1
    assert answer['context']['evidence_id'] == first['context']['evidence_id']
    assert answer['context']['last_scope'] == 'mock-layout'
    if kind == 'simplify':
        assert answer['sources'] == first['sources']
        assert inventory()['signals'][0]['knowledge'][0]['text'] in answer['message']


def test_current_registry_revokes_in_memory_scope_on_social_turn():
    state = LocalState()
    respond(request('revoke', 'How do I edit layout blocks?'), state)
    state.model = Once('{"intent":"social","target":null,"response":"Hello again!"}')
    answer = respond(request('revoke', 'hello', registry={'active': [], 'signals': []}), state)
    assert answer['context']['last_scope'] is None
    assert answer['context']['evidence_id'] is None
    assert answer['sources'] == []


def test_selection_trace_has_zero_model_calls():
    state = LocalState()
    respond(request('button', 'help'), state)
    model = Once(error=AssertionError('Selection must not infer'))
    state.model = model
    answer = respond(request('button', '', 'mock-layout') | {'debug': True}, state)
    assert answer['scope'] == 'product'
    assert model.calls == answer['debug']['model_calls'] == 0


def test_product_identity_cannot_ground_an_unrelated_capability():
    model = Once('{"intent":"product","target":"mock-layout","response":null}')
    answer = respond(request('capability', 'Enable automatic translation payment refunds for mock-layout.'),
                     LocalState(model=model))
    assert model.calls == 1
    assert answer['scope'] == 'product'
    assert answer['status'] == 'needs_input'
    assert answer['interaction']['key'] == 'support_intent'
    assert answer['sources'] == []


def test_feedback_guard_overriding_null_support_reply_still_returns_text():
    model = Once('{"intent":"product","target":"mock-layout","response":null}')
    answer = respond(request('contradiction', "That didn't work."), LocalState(model=model))
    assert answer['status'] == 'clarification'
    assert isinstance(answer['message'], str) and answer['message'].endswith('.')
    assert answer['context']['outcome'] == 'unresolved'
    assert model.calls == 1


@pytest.mark.parametrize('route,scope', [('product:mock-layout', 'product'), ('wordpress', 'wordpress')])
def test_compact_route_still_requires_current_evidence(route, scope):
    model = Once(json.dumps({'route': route, 'response': None}))
    question = 'How do I edit blocks in mock-layout?' if scope == 'product' else 'WordPress password reset'
    answer = respond(request('compact', question), LocalState(model=model))
    assert answer['routing'] == 'unified-intent'
    assert answer['scope'] == scope
    assert answer['sources']
    assert model.calls == 1


def test_compact_route_cannot_introduce_an_unregistered_product():
    model = Once('{"route":"product:invented","response":null}')
    answer = respond(request('compact-invalid', 'Use the invented tool'), LocalState(model=model))
    assert model.calls == 1
    assert answer['routing'] == 'brain-clarify'
    assert answer['sources'] == []


@pytest.mark.parametrize('selection', ['wordpress', 'other'])
def test_scope_selection_clears_an_incompatible_active_workflow(selection):
    state = LocalState()
    begin(state)
    answer = send(state, selection=selection)
    assert 'troubleshooting' not in answer['context']
    assert 'a' not in state.workflows
    stale = send(state, selection='check:plugin:worked')
    assert stale['status'] == 'clarification'
    assert stale['context']['outcome'] != 'resolved'
