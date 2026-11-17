"""Bounded comparison exercises. Selecting an exercise never diagnoses a defect."""
import json
from copy import deepcopy
from pathlib import Path
from .coaching_methods import profile

METHODS = json.loads((Path(__file__).resolve().parents[1] / 'shared/practice-experiments.json').read_text())


def choices_for(issue):
    return {key: deepcopy(METHODS[key]) for key in profile(issue)['strategies'] if key in METHODS}


def validate_choice(issue, choice):
    if choice.strategyId not in choices_for(issue):
        raise ValueError('Practice strategy does not match this measured feature')
    observations = issue.get('observations') or []
    target = next((row for row in observations if row['segmentId'] == choice.segmentId), None)
    if target is None:
        raise ValueError('Practice must refer to a verified observation in this finding')
    return target


def experiment_for(issue, choice):
    target = validate_choice(issue, choice)
    return {'kind': 'comparison_experiment', 'source': 'ai_selected',
            'strategyId': choice.strategyId, 'segmentId': choice.segmentId,
            'startMs': target['startMs'], 'endMs': target['endMs'],
            'definitionVersion': 'comparison-experiments-v1',
            **({'instructions': choice.instructions.model_dump()} if choice.instructions else {})}
