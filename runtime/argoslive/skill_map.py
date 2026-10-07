"""Task-scoped skill map: grouped by domains with fixed criteria and model binding.

Domains:
- Understanding (Short documents, instruction following, long documents [future])
- Reasoning (Arithmetic reasoning, knowledge & logic, deductive planning [future])
- Planning (Structured JSON, multi-step execution [future])
- Tool use (Tool-call formatting, sandboxed execution [future])
- Memory (Storage retention, episodic memory [future])
- Perception (Multimodal vision [future], audio speech [future])

Evidence states:
- 'untested': outline (no completed test for selected model files)
- 'measured': cyan (tested baseline, criteria pending or speed/storage observed)
- 'qualified': teal (met fixed qualification criteria under matching model digest)
- 'attention': amber (criteria missed, format errors, or storage issue)
- 'unavailable': future suite not yet implemented in this build
"""
from typing import Any, Dict, List, Optional


DOMAINS = [
    {
        'id': 'understanding',
        'label': 'Understanding',
        'icon': 'book',
        'summary': 'Reading comprehension, following directions, and extracting facts from text.',
    },
    {
        'id': 'reasoning',
        'label': 'Reasoning',
        'icon': 'brain',
        'summary': 'Arithmetic calculations, multi-step logic, and factual deduction.',
    },
    {
        'id': 'planning',
        'label': 'Planning',
        'icon': 'workflow',
        'summary': 'Structured JSON formatting and multi-step execution schemas.',
    },
    {
        'id': 'tools',
        'label': 'Tool use',
        'icon': 'tools',
        'summary': 'Function calling syntax and sandboxed tool invocations.',
    },
    {
        'id': 'memory',
        'label': 'Memory',
        'icon': 'storage',
        'summary': 'Persistent storage retention and long-term recall across sessions.',
    },
    {
        'id': 'perception',
        'label': 'Perception',
        'icon': 'eye',
        'summary': 'Multimodal vision and audio perception pipelines.',
    },
]


def digest_of(value: Any) -> Optional[str]:
    """Bare hex digest, or None when the identity is unknown."""
    if not isinstance(value, str):
        return None
    value = value[7:] if value.startswith('sha256:') else value
    return value if len(value) == 64 and all(c in '0123456789abcdef' for c in value) else None


def is_selected(run: Dict[str, Any], selected: Optional[Dict[str, Any]]) -> bool:
    """Does this run describe the weights currently selected? Unknown identity never matches."""
    digest = digest_of((selected or {}).get('digest'))
    return (digest is not None and run.get('model') == (selected or {}).get('model')
            and digest_of(run.get('manifest_digest')) == digest)


def build_skill_map(facts: Dict[str, Any], selected: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive task-scoped skill map from validated facts and active model selection."""
    selected_model = (selected or {}).get('model')
    selected_digest = digest_of((selected or {}).get('digest'))

    runs = facts.get('runs', [])
    doc_models = facts.get('doc_models', [])
    storage_view = facts.get('storage') or {}

    # Find matching document run for selected model
    matching_doc_run = next((r for r in doc_models if is_selected(r, selected)), None)

    # Find matching complete quick ability run for selected model
    matching_quick_run = None
    for r in runs:
        if (r.get('kind') == 'ability' and r.get('suite') == 'quick'
                and r.get('state') == 'completed'
                and r.get('coverage', {}).get('complete', False)
                and is_selected(r, selected)):
            matching_quick_run = r
            break

    # Helper to evaluate quick suite category state
    def eval_quick_cat(cat_id: str) -> tuple[str, Optional[Dict[str, Any]]]:
        if not matching_quick_run:
            return 'untested', None
        summary = matching_quick_run.get('summary', {})
        cat = summary.get('categories', {}).get(cat_id)
        if not cat or cat.get('total', 0) == 0:
            return 'untested', None
        correct = cat.get('correct', 0)
        total = cat.get('total', 0)
        format_errors = cat.get('format_errors', 0)
        evidence = {
            'run_id': matching_quick_run['id'],
            'created': matching_quick_run.get('created'),
            'correct': correct,
            'total': total,
            'format_errors': format_errors,
            'accuracy': correct / total if total else 0.0,
        }
        if correct == total and format_errors == 0:
            return 'qualified', evidence
        if correct > 0 and format_errors == 0:
            return 'measured', evidence
        return 'attention', evidence

    # Document short state
    doc_state = 'untested'
    doc_evidence = None
    if matching_doc_run:
        q = matching_doc_run.get('qualification', {})
        s = matching_doc_run.get('summary', {})
        doc_evidence = {
            'run_id': matching_doc_run['id'],
            'created': matching_doc_run.get('created'),
            'qualified': q.get('qualified', False),
            'correct': s.get('correct', 0),
            'total': s.get('total', 0),
            'format_errors': s.get('format_errors', 0),
            'checks': q.get('checks', []),
        }
        if q.get('qualified', False):
            doc_state = 'qualified'
        else:
            doc_state = 'attention'

    # Storage retention state
    storage_state = 'untested'
    storage_evidence = None
    locations = storage_view.get('locations', [])
    models_loc = next((l for l in locations if l.get('key') == 'models'), {})
    reboot = models_loc.get('reboot', {}).get('state')
    confirmed = storage_view.get('confirmed', False)
    st_general = storage_view.get('state')

    if reboot == 'retained':
        storage_state = 'qualified'
        storage_evidence = {'reboot': 'retained', 'verified_at': models_loc.get('reboot', {}).get('verified_at')}
    elif confirmed:
        storage_state = 'measured'
        storage_evidence = {'reboot': reboot or 'pending', 'confirmed': True}
    elif st_general == 'needs-attention':
        storage_state = 'attention'
        storage_evidence = {'state': 'needs-attention'}

    # Build all nodes across domains
    inst_state, inst_ev = eval_quick_cat('instruction')
    num_state, num_ev = eval_quick_cat('numeric')
    choice_state, choice_ev = eval_quick_cat('choice')
    json_state, json_ev = eval_quick_cat('json')
    tool_state, tool_ev = eval_quick_cat('tool-call')

    domain_nodes = {
        'understanding': [
            {
                'id': 'doc-short',
                'title': 'Short Document Reading',
                'state': doc_state,
                'available': True,
                'suite': 'documents-short',
                'action': 'documents',
                'action_label': 'Pause chat and test Short Documents',
                'criteria': 'Answers 7/8, Quotations 6/8 supported from text, "Not stated" 7/8 recognized, at most 2 format errors.',
                'scope': 'Short passages (~150 words) at context 4096. Does not qualify long documents, arbitrary files, or real-world tasks.',
                'evidence': doc_evidence,
            },
            {
                'id': 'instruction-following',
                'title': 'Instruction Following',
                'state': inst_state,
                'available': True,
                'suite': 'quick',
                'action': 'baseline',
                'action_label': 'Pause chat and test Quick Suite',
                'criteria': 'Adhere to word count bounds, required keywords, single-line format, and case constraints. 100% pass required.',
                'scope': 'Fixed synthetic prompt constraints at context 2048. Probes rule following only, not multi-turn conversation.',
                'evidence': inst_ev,
            },
            {
                'id': 'long-documents',
                'title': 'Long Documents & Books',
                'state': 'unavailable',
                'available': False,
                'suite': None,
                'action': None,
                'action_label': 'Not available in this build',
                'criteria': 'Multi-chapter comprehension across 16k+ context windows.',
                'scope': 'Unavailable in this build. No unverified capability is claimed.',
                'evidence': None,
            },
        ],
        'reasoning': [
            {
                'id': 'numeric-reasoning',
                'title': 'Arithmetic & Numbers',
                'state': num_state,
                'available': True,
                'suite': 'quick',
                'action': 'baseline',
                'action_label': 'Pause chat and test Quick Suite',
                'criteria': 'Exact decimal evaluation on word arithmetic problems without rounding or format errors.',
                'scope': 'Fixed numeric problems at context 2048. Does not qualify advanced mathematics or symbolic proof.',
                'evidence': num_ev,
            },
            {
                'id': 'knowledge-logic',
                'title': 'Knowledge & Logic',
                'state': choice_state,
                'available': True,
                'suite': 'quick',
                'action': 'baseline',
                'action_label': 'Pause chat and test Quick Suite',
                'criteria': 'Select single correct choice letter (A–D) from curated logic and factual questions.',
                'scope': 'Deterministic multiple-choice probes at context 2048. Does not qualify encyclopedic mastery.',
                'evidence': choice_ev,
            },
            {
                'id': 'deductive-planning',
                'title': 'Multi-Step Deduction',
                'state': 'unavailable',
                'available': False,
                'suite': None,
                'action': None,
                'action_label': 'Not available in this build',
                'criteria': 'Multi-hypothesis branch deduction across hidden constraints.',
                'scope': 'Unavailable in this build.',
                'evidence': None,
            },
        ],
        'planning': [
            {
                'id': 'structured-json',
                'title': 'Structured JSON Output',
                'state': json_state,
                'available': True,
                'suite': 'quick',
                'action': 'baseline',
                'action_label': 'Pause chat and test Quick Suite',
                'criteria': 'Produce valid closed JSON schema matching expected types and keys with no wrapper leaks.',
                'scope': 'Schema syntax conformance at context 2048. Does not qualify autonomous workflows.',
                'evidence': json_ev,
            },
            {
                'id': 'multi-step-plan',
                'title': 'Autonomous Workflow Planning',
                'state': 'unavailable',
                'available': False,
                'suite': None,
                'action': None,
                'action_label': 'Not available in this build',
                'criteria': 'Requires J4 sandbox agentic qualification with code-verified artifacts.',
                'scope': 'Unavailable in this build. Syntax formatting is not autonomous execution.',
                'evidence': None,
            },
        ],
        'tools': [
            {
                'id': 'tool-formatting',
                'title': 'Tool Call Formatting',
                'state': tool_state,
                'available': True,
                'suite': 'quick',
                'action': 'baseline',
                'action_label': 'Pause chat and test Quick Suite',
                'criteria': 'Emit valid tool invocation JSON with correct function name and matching argument schema.',
                'scope': 'Syntax formatting probe only. Does NOT execute tools, grant host access, or qualify agentic autonomy.',
                'evidence': tool_ev,
            },
            {
                'id': 'sandboxed-execution',
                'title': 'Sandboxed Agentic Tools',
                'state': 'unavailable',
                'available': False,
                'suite': None,
                'action': None,
                'action_label': 'Not available in this build',
                'criteria': 'Requires J4 opt-in disposable sandbox with allowlisted tool boundaries.',
                'scope': 'Unavailable in this build. Formatting probes cannot qualify real tool execution.',
                'evidence': None,
            },
        ],
        'memory': [
            {
                'id': 'storage-retention',
                'title': 'Model Storage Retention',
                'state': storage_state,
                'available': True,
                'suite': 'storage_view',
                'action': 'storage',
                'action_label': 'Configure and verify model storage',
                'criteria': 'Model store folder retains a random marker across machine reboot.',
                'scope': 'Directory persistence only. Does not verify encryption, drive speed, or conversation recall.',
                'evidence': storage_evidence,
            },
            {
                'id': 'episodic-memory',
                'title': 'Episodic Long-Term Memory',
                'state': 'unavailable',
                'available': False,
                'suite': None,
                'action': None,
                'action_label': 'Not available in this build',
                'criteria': 'Cross-session memory retrieval and semantic association.',
                'scope': 'Unavailable in this build.',
                'evidence': None,
            },
        ],
        'perception': [
            {
                'id': 'vision-multimodal',
                'title': 'Vision & Image Understanding',
                'state': 'unavailable',
                'available': False,
                'suite': None,
                'action': None,
                'action_label': 'Not available in this build',
                'criteria': 'Multimodal image question answering via supported vision model.',
                'scope': 'Unavailable in this build.',
                'evidence': None,
            },
            {
                'id': 'audio-speech',
                'title': 'Audio & Speech Transcription',
                'state': 'unavailable',
                'available': False,
                'suite': None,
                'action': None,
                'action_label': 'Not available in this build',
                'criteria': 'Local audio transcription and speech comprehension.',
                'scope': 'Unavailable in this build.',
                'evidence': None,
            },
        ],
    }

    domains_output = []
    tally = {'total_nodes': 0, 'active_nodes': 0, 'qualified': 0, 'measured': 0, 'attention': 0, 'untested': 0, 'unavailable': 0}

    for d in DOMAINS:
        nodes = domain_nodes.get(d['id'], [])
        for node in nodes:
            tally['total_nodes'] += 1
            st = node['state']
            tally[st] = tally.get(st, 0) + 1
            if node['available']:
                tally['active_nodes'] += 1
            node['model'] = selected_model
            node['manifest_digest'] = selected_digest
        domains_output.append({**d, 'nodes': nodes})

    return {
        'schema': 'argos-skill-map/1',
        'model': selected_model,
        'manifest_digest': selected_digest,
        'domains': domains_output,
        'tally': tally,
        'scope': 'Task-scoped skills. Evidence binds strictly to the selected model weights and manifest digest.',
    }
