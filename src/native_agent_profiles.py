"""Bounded role recommendations and profile validation, without model execution."""
from copy import deepcopy
from pathlib import Path
import tomllib

ROLES = {
    'Implementer': ('implementer', 'own worktree only'),
    'ImplementerQuick': ('implementer_quick', 'own worktree only'),
    'ImplementerAdvanced': ('implementer_advanced', 'own worktree only'),
    'Orchestrator': ('orchestrator', 'none'),
    'IndependentReviewer': ('independent_reviewer', 'none'),
    'SecurityReviewer': ('security_reviewer', 'none'),
    'TestReviewer': ('test_reviewer', 'none'),
    'PerformanceReviewer': ('performance_reviewer', 'none'),
    'DocumentationReviewer': ('documentation_reviewer', 'none'),
    'Verifier': ('verifier', 'verification outputs only'),
    'Researcher': ('researcher', 'none'),
    'Coordinator': ('parent', 'integration only'),
}
MODELS = {'gpt-6.1-sol', 'gpt-6-luna'}
PRIMARY_MODEL = 'gpt-6.1-sol'
REVIEW_ROLES = {
    'correctness': 'IndependentReviewer',
    'security': 'SecurityReviewer',
    'tests': 'TestReviewer',
    'performance': 'PerformanceReviewer',
    'documentation': 'DocumentationReviewer',
}
BUDGET_CEILINGS = {
    'cloud_concurrency': 6, 'local_concurrency': 1,
    'max_dispatches': 24, 'max_retries': 2,
    'task_timeout_s': 300, 'run_timeout_s': 900,
}


def role_registry():
    return {name: {'native_role': native, 'writes': writes}
            for name, (native, writes) in ROLES.items()}


def load_profile(project, role):
    """Read one bounded TOML profile. Caller supplies symlink/path guards."""
    if role not in ROLES or role == 'Coordinator':
        raise ValueError('UNSUPPORTED_ROLE_PROFILE')
    native = ROLES[role][0]
    path = Path(project) / '.codex' / 'agents' / (native + '.toml')
    if path.stat().st_size > 65536:
        raise ValueError('ROLE_SIZE_LIMIT')
    raw = path.read_bytes()
    value = tomllib.loads(raw.decode('utf-8'))
    if (set(value) != {'name', 'description', 'developer_instructions',
                       'model', 'model_reasoning_effort'}
            or value['name'] != native
            or any(not isinstance(v, str) or not v.strip() for v in value.values())
            or value['model'] not in MODELS
            or value['model_reasoning_effort'] != 'max'):
        raise ValueError('UNSUPPORTED_ROLE_SETTINGS')
    return raw, value


def recommend(purpose, complexity='standard', *, parallel_parts=1,
              security_sensitive=False, performance_sensitive=False,
              cross_project=False):
    """Select roles, not actors or permissions. The parent constructs the DAG."""
    if purpose not in {'implementation', 'documentation', 'research', 'orchestration'}:
        raise ValueError('UNKNOWN_TASK_PURPOSE')
    if complexity not in {'quick', 'standard', 'advanced'}:
        raise ValueError('UNKNOWN_TASK_COMPLEXITY')
    if type(parallel_parts) is not int or not 1 <= parallel_parts <= 24:
        raise ValueError('INVALID_PARALLEL_PARTS')
    if any(type(v) is not bool for v in
           [security_sensitive, performance_sensitive, cross_project]):
        raise ValueError('BOOLEAN_RISK_FLAGS_REQUIRED')
    if purpose in {'research', 'orchestration'} and parallel_parts != 1:
        raise ValueError('SINGLE_ADVISORY_ASSIGNMENT_REQUIRED')
    planning = (purpose != 'orchestration'
                and (parallel_parts > 1 or cross_project or complexity == 'advanced'))
    primary = {
        'implementation': {'quick': 'ImplementerQuick', 'standard': 'Implementer',
                           'advanced': 'ImplementerAdvanced'}[complexity],
        'documentation': 'ImplementerQuick',
        'research': 'Researcher',
        'orchestration': 'Orchestrator',
    }[purpose]
    reviews = []
    if purpose == 'implementation':
        reviews.extend(['IndependentReviewer', 'TestReviewer'])
    elif purpose == 'documentation':
        reviews.append('DocumentationReviewer')
    if security_sensitive:
        reviews.append('SecurityReviewer')
    if performance_sensitive:
        reviews.append('PerformanceReviewer')
    assignments = []
    if planning:
        assignments.append({'phase': 'plan', 'role': 'Orchestrator', 'count': 1})
    assignments.append({'phase': 'work', 'role': primary, 'count': parallel_parts})
    assignments.extend({'phase': 'review', 'role': role, 'count': 1} for role in reviews)
    if purpose in {'implementation', 'documentation'}:
        assignments.append({'phase': 'verify', 'role': 'Verifier', 'count': 1})
    # Coordinator admission is a dispatch too, even though it does not spawn a child.
    integration_dispatches = int(purpose in {'implementation', 'documentation'})
    dispatches = sum(item['count'] for item in assignments) + integration_dispatches
    if dispatches > BUDGET_CEILINGS['max_dispatches']:
        raise ValueError('RECOMMENDATION_EXCEEDS_DISPATCH_BUDGET')
    return {'assignments': assignments,
            'budgets': deepcopy(BUDGET_CEILINGS),
            'suggested_concurrency': min(parallel_parts, BUDGET_CEILINGS['cloud_concurrency']),
            'required_dispatches': dispatches,
            'parent_integration_dispatches': integration_dispatches,
            'automatic_dispatch': False, 'automatic_retry': False,
            'availability_verified': False}
