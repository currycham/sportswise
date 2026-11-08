"""Offline sport knowledge and budgeted synthetic-audit contract tests."""
import copy
import json
from datetime import date, timedelta

import pytest

from app import db, services, training_knowledge
from scripts import evaluate_sport_plans as audit


def test_each_sport_selects_specific_primary_sources_and_common_load_rules():
    sources = {'basketball': 'fiba_physical', 'badminton': 'bwf_pathway', 'javelin': 'wa_javelin'}
    for case, profile in audit.build_cases('2026-11-09').items():
        knowledge = training_knowledge.select(profile)
        ids = [s['id'] for s in knowledge['sources']]
        assert len(ids) == len(set(ids))
        if case in sources:
            assert sources[case] in ids and 'nsca_needs' in ids
            assert case in knowledge['sports']
            assert {'sport_needs_and_coach', 'sport_season_load'} <= {r['id'] for r in knowledge['rules']}
        else:
            assert not knowledge['sports'] and 'nsca_needs' not in ids


def test_basketball_youth_source_cannot_be_silently_applied_to_adult():
    adult = audit.build_cases('2026-11-09')['basketball']
    assert 'usab_youth' not in {s['id'] for s in training_knowledge.select(adult)['sources']}
    youth = {**adult, 'adult': False}
    assert 'usab_youth' in {s['id'] for s in training_knowledge.select(youth)['sources']}


def test_sport_is_found_in_existing_free_text_without_new_schema_field():
    p = audit.build_cases('2026-11-09')['javelin']
    assert 'sport' not in p
    assert 'javelin' in training_knowledge.select(p)['sports']


def test_four_fixtures_pass_real_profile_contract_and_keep_sport_details():
    from app.main import Profile
    cases = audit.build_cases('2026-11-09')
    for case, profile in cases.items():
        assert set(profile) <= set(Profile.model_fields)
        assert Profile.model_validate(profile).model_dump(mode='json') == profile
        assert not {'gym', 'court', 'track', 'javelin'} & set(profile['equipment'])
        assert not {'basketball', 'javelin'} & set(profile['likes'])
        if case != 'beginner':
            assert 'other' in profile['equipment'] and profile['equipment_detail']
            assert profile['activity_detail'] and profile['training_structure']
    assert '篮球' in cases['basketball']['activity_detail']
    assert '标枪' in cases['javelin']['activity_detail']
    assert '规格未提供不能推定' in cases['javelin']['equipment_detail']


def test_normalization_rejects_silent_extra_fixture_fields():
    profile = audit.build_cases('2026-11-09')['javelin']
    with pytest.raises(ValueError, match='cannot save'):
        audit.normalize_profile({**profile, 'sport': 'javelin'})


def test_javelin_rules_do_not_invent_throw_load_or_substitute_medicine_ball():
    p = audit.build_cases('2026-11-09')['javelin']
    assert '未提供投掷次数、强度、器械规格' in p['routine_detail']
    text = ' '.join(r['principle'] for r in training_knowledge.select(p)['rules'])
    assert '不得冒充标枪技术课' in text
    assert '不自行规定' in text and '比赛试投次数' in text
    checks = audit.review_checklist('javelin')
    assert any('精确投掷次数' in c['question'] and c['blocking'] for c in checks)


def test_offline_export_never_connects_db_calls_api_or_sends_mail(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline fixture export touched external state')
    monkeypatch.setattr(db, 'connect', forbidden)
    monkeypatch.setattr(services, 'planning_model_json', forbidden)
    monkeypatch.setattr(services, 'send_mail', forbidden)
    output = tmp_path/'offline'
    summary = audit.run_evaluation(list(audit.CASE_IDS), output, '2026-11-09')
    assert summary['calls'] == 0 and len(summary['cases']) == 4
    assert all(c['verification_status'] == 'not_run' and not c['pipeline_accepted'] for c in summary['cases'])
    assert (output/'summary.json').exists()
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output/'beginner/input.json').stat().st_mode & 0o777 == 0o600


def test_global_call_limit_shared_across_case_wrappers(tmp_path):
    calls = []
    def fake(messages, actor, task, **kwargs):
        calls.append((actor, task, kwargs))
        kwargs['metrics']({'status': 'ok'})
        return {'fixture': True}
    caller = audit.LimitedCaller(2, 'sportswise-sport-eval-unit', fake)
    profiles = audit.build_cases('2026-11-09')
    a = caller.for_case(profiles['beginner'], tmp_path)
    b = caller.for_case(profiles['javelin'], tmp_path)
    a([], 'plan_generate')
    b([], 'plan_review')
    with pytest.raises(audit.CallLimitError):
        b([], 'plan_generate')
    assert caller.calls == len(calls) == 2
    assert all(c[0] == 'sportswise-sport-eval-unit' for c in calls)
    assert calls[1][2]['model'] == audit.config.PLANNER_EXPERT_MODEL


def test_real_pipeline_with_stub_transport_reserves_pairs_and_rejects_duplicate_dates(tmp_path, monkeypatch):
    """No alternative scoring path: actual pipeline must reject structural failure."""
    def forbidden(*args, **kwargs):
        pytest.fail('synthetic pipeline touched account/database/mail')
    monkeypatch.setattr(db, 'connect', forbidden)
    monkeypatch.setattr(services, 'send_mail', forbidden)
    start = date(2026, 11, 9)
    draft = {'week': str(start), 'rationale': '故意日期重复的结构错误测试稿', 'phase': '测试',
        'scope': 'calibration', 'assumptions': ['离线测试'], 'questions': ['请补充信息'],
        'source_ids': ['ace_ift'], 'programming': {'progression': '测试', 'deload': '测试', 'review': '测试'},
        'sessions': [{'date': str(start), 'kind': 'rest', 'title': '休息',
                      'purpose': '测试', 'minutes': 0, 'intensity': '休息', 'steps': []} for i in range(7)]}
    tasks = []
    received_profiles = []
    real_pipeline = audit.ai_planning.pipeline
    def checked_pipeline(profile, state, model_call, progress):
        from app.main import Profile
        assert Profile.model_validate(profile).model_dump(mode='json') == profile
        assert profile == state['profile']
        received_profiles.append(copy.deepcopy(profile))
        return real_pipeline(profile, state, model_call, progress)
    monkeypatch.setattr(audit.ai_planning, 'pipeline', checked_pipeline)
    def fake(messages, actor, task, **kwargs):
        tasks.append(task)
        kwargs['metrics']({'status': 'ok', 'estimated_cost_yuan': 0})
        return {'score': 99, 'passed': True, 'issues': [], 'must_fix': []} if task == 'plan_review' else copy.deepcopy(draft)
    summary = audit.run_evaluation(list(audit.CASE_IDS), tmp_path/'pipeline', str(start), 8,
                                   run=True, transport=fake)
    assert summary['calls'] == len(tasks) == 8
    assert len(received_profiles) == 4
    assert tasks == ['plan_generate', 'plan_review']*4
    assert not any(c['pipeline_accepted'] for c in summary['cases'])
    assert all(c['verification_status'] == 'needs_human_sport_review' for c in summary['cases'])
    for case in audit.CASE_IDS:
        path = tmp_path/'pipeline'/case
        assert (path/'result.json').exists()
        records = [json.loads(p.read_text()) for p in path.glob('call-*.json')]
        assert len(records) == 2 and all('messages' in r and 'output' in r for r in records)


@pytest.mark.parametrize('limit', [0, 25, True])
def test_invalid_call_budget_is_rejected(limit):
    with pytest.raises(ValueError):
        audit.LimitedCaller(limit, 'sportswise-sport-eval-test')
